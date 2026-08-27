"""Static contracts for the complete native frame-to-pixel pipeline."""

from __future__ import annotations

import json
from pathlib import Path

from static_re_contract_support import ROOT, StaticReTestFailure


REPORT = ROOT / "docs/reverse-engineering/native-full-render-pipeline.md"
XREFS = ROOT / "docs/reverse-engineering/native-full-render-pipeline-xrefs.json"
MEMBERSHIP = ROOT / "docs/reverse-engineering/native-full-render-pipeline-membership.json"
SCENE = ROOT / "docs/reverse-engineering/native-scene-composition.md"
ARENA = ROOT / "docs/reverse-engineering/native-arena-render-pipeline.md"
LAYOUT = ROOT / "config/binary-layout.ini"
GHIDRA_GENERATOR = ROOT / "tools/ghidra-scripts/catalog_full_render_pipeline.py"
JOIN_GENERATOR = ROOT / "tools/build_native_render_pipeline_membership.py"
RETAIL_SHA256 = "03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3"


def read(path: Path) -> str:
    if not path.is_file():
        raise StaticReTestFailure(
            f"full render-pipeline artifact is absent: {path.relative_to(ROOT)}"
        )
    return path.read_text(encoding="utf-8")


def load(path: Path) -> dict:
    try:
        return json.loads(read(path))
    except json.JSONDecodeError as exc:
        raise StaticReTestFailure(
            f"full render-pipeline artifact is not reviewable JSON: {exc}"
        ) from exc


def test_native_full_render_pipeline_xrefs_are_complete_and_regenerable() -> str:
    xrefs = load(XREFS)
    if xrefs.get("schema") != "solomon-dark-native-full-render-pipeline-xrefs-v1":
        raise StaticReTestFailure("full renderer xref schema drifted")
    if xrefs.get("program") != "SolomonDark.exe":
        raise StaticReTestFailure("full renderer xrefs target another program")
    if xrefs.get("executable_sha256") != RETAIL_SHA256:
        raise StaticReTestFailure("full renderer xrefs lost retail provenance")
    if xrefs.get("image_base") != "0x00400000":
        raise StaticReTestFailure("full renderer xrefs lost preferred-image addresses")
    if xrefs.get("graphics_subobject_offset") != "0x1D0":
        raise StaticReTestFailure("Graphics could again be confused with the MyApp base")

    expected_summary = {
        "group_count": 11,
        "reference_count": 4009,
        "renderer_state_write_count": 404,
        "target_count": 101,
        "unique_caller_count": 562,
    }
    if xrefs.get("summary") != expected_summary:
        raise StaticReTestFailure(
            f"full renderer xref census drifted: {xrefs.get('summary')}"
        )
    group_names = [group.get("name") for group in xrefs.get("groups", [])]
    expected_groups = [
        "application_frame",
        "graphics_lifecycle",
        "sprite_entry",
        "primitive",
        "color_and_state",
        "transform_and_clip",
        "texture_and_target",
        "shader",
        "device",
        "scene_root",
        "direct_device_global",
    ]
    if group_names != expected_groups:
        raise StaticReTestFailure(f"full renderer target groups drifted: {group_names}")

    generator = read(GHIDRA_GENERATOR)
    for token in (
        "TARGET_GROUPS",
        "RENDERER_STATE_OFFSETS",
        '"executable_sha256": executable_sha256',
        '"orphan_sites"',
        '"renderer_state_writes"',
    ):
        if token not in generator:
            raise StaticReTestFailure(f"full renderer generator lost {token}")
    return "101 renderer targets, 4,009 xrefs, and 404 state writes are regenerable"


def test_native_full_render_pipeline_membership_has_no_silent_rows() -> str:
    membership = load(MEMBERSHIP)
    if membership.get("schema") != "solomon-dark-native-full-render-pipeline-membership-v1":
        raise StaticReTestFailure("full renderer membership schema drifted")
    if membership.get("executable_sha256") != RETAIL_SHA256:
        raise StaticReTestFailure("full renderer membership lost retail provenance")
    expected_dispositions = {
        "atlas-owned-render-helper": 46,
        "class-owned-render-helper": 138,
        "free-render-helper": 53,
        "pipeline-internal": 88,
        "vtable-render-member": 237,
    }
    summary = membership.get("summary", {})
    expected_counts = {
        "caller_count": 562,
        "class_relation_count": 1038,
        "atlas_relation_count": 451,
        "render_class_count": 524,
        "orphan_reference_count": 147,
        "renderer_state_write_count": 404,
        "class_state_program_count": 151,
    }
    for key, expected in expected_counts.items():
        if summary.get(key) != expected:
            raise StaticReTestFailure(
                f"full renderer membership {key} drifted: {summary.get(key)}"
            )
    if summary.get("dispositions") != expected_dispositions:
        raise StaticReTestFailure(
            f"full renderer dispositions drifted: {summary.get('dispositions')}"
        )

    callers = membership.get("callers", [])
    allowed = set(expected_dispositions)
    if len(callers) != 562 or any(caller.get("disposition") not in allowed for caller in callers):
        raise StaticReTestFailure("full renderer has a missing or illegal caller disposition")
    orphans = membership.get("orphan_references", [])
    if len(orphans) != 147 or any(
        row.get("disposition") != "data-or-vtable-reference" for row in orphans
    ):
        raise StaticReTestFailure("full renderer data/vtable xrefs are not dispositioned")
    if len(membership.get("render_classes", [])) != 524:
        raise StaticReTestFailure("full renderer class/slot membership drifted")

    joiner = read(JOIN_GENERATOR)
    for token in (
        "class_relations",
        "atlas_relations",
        "orphan_references",
        "class_state_programs",
    ):
        if token not in joiner:
            raise StaticReTestFailure(f"full renderer membership join lost {token}")
    return "all renderer callers, class slots, atlas joins, and data xrefs are dispositioned"


def test_native_full_render_pipeline_shader_and_state_programs_are_pinned() -> str:
    membership = load(MEMBERSHIP)
    dispositions: dict[str, int] = {}
    for write in membership.get("renderer_state_writes", []):
        key = write.get("disposition")
        dispositions[key] = dispositions.get(key, 0) + 1
    expected = {
        "additive-srcalpha-one": 150,
        "arena-saturation-request": 2,
        "dynamic-exact-selector": 43,
        "multiply-zero-srccolor": 14,
        "normal-srcalpha-invsrcalpha": 147,
        "textured-modulate": 21,
        "untextured-diffuse": 27,
    }
    if dispositions != expected:
        raise StaticReTestFailure(f"full renderer state program drifted: {dispositions}")

    report = " ".join(read(REPORT).split())
    required = (
        "exactly two game-authored `ps_2_0` sources",
        "No game-authored vertex shader source is present",
        "request remains constructor-zero and has no retail writer",
        "accumulated samples by 20",
        "dormant 1.2-gain cross blur",
        "No menu, world, actor, projectile, spell, weather, or effect class calls a raw device draw method",
        "There is no `blocked-by-platform` member",
    )
    for token in required:
        if token not in report:
            raise StaticReTestFailure(f"full renderer report lost: {token}")
    arena = " ".join(read(ARENA).split())
    if "24 samples by 20" not in arena or "has no retail writer" not in arena:
        raise StaticReTestFailure("Arena report restored the disproven 20-sample active blur claim")
    return "shader reachability, blur arithmetic, and every selector write are pinned"


def test_native_full_render_pipeline_residuals_and_layout_are_closed() -> str:
    scene = " ".join(read(SCENE).split())
    for token in (
        "2026-08-27 residual closure",
        "Tree overlay member",
        "Lantern::Render 0x005E61D0",
        "all 404 renderer-selector writes",
        "deterministic uniform `1 + magnitude` scale",
        "no remaining extractable native unknown",
    ):
        if token not in scene:
            raise StaticReTestFailure(f"scene report retained an open renderer residual: {token}")

    layout = read(LAYOUT)
    for token in (
        "[native_full_render_pipeline]",
        "graphics_subobject_offset=0x000001D0",
        "app_render_frame=0x0040D230",
        "graphics_constructor=0x0041C780",
        "indexed_mesh_draw=0x0041DA00",
        "render_to_texture_begin=0x004214C0",
        "d3d_transform_program=0x00440BA0",
        "blur_retail_writer_count=0",
    ):
        if token not in layout:
            raise StaticReTestFailure(f"full renderer layout address drifted: {token}")
    return "former queue/blend/shader/camera residuals and full-pipeline addresses are closed"
