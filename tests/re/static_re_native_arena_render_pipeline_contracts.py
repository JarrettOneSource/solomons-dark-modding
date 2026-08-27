"""Static contracts for the native Arena pixel-production pipeline."""

from __future__ import annotations

import json
from pathlib import Path

from static_re_contract_support import ROOT, StaticReTestFailure


REPORT_PATH = ROOT / "docs/reverse-engineering/native-arena-render-pipeline.md"
CALLER_CATALOG_PATH = (
    ROOT / "docs/reverse-engineering/native-render-pipeline-callers.json"
)
SCENE_PATH = ROOT / "docs/reverse-engineering/native-scene-composition.md"
ASSET_PATH = ROOT / "docs/reverse-engineering/native-asset-system.md"
PROJECTILE_PATH = ROOT / "docs/reverse-engineering/native-projectiles-and-effects.md"
LIGHTING_PATH = ROOT / "docs/reverse-engineering/native-lighting-and-shadow-system.md"
LAYOUT_PATH = ROOT / "config/binary-layout.ini"
CATALOG_SCRIPT_PATH = ROOT / "tools/ghidra-scripts/catalog_renderer_callers.py"

RETAIL_SHA256 = "03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3"
EXPECTED_TARGETS = {
    "0x004143D0": ("Glyph_Draw", 386, 152, 0),
    "0x00414540": ("FUN_00414540", 126, 69, 0),
    "0x00414EA0": ("FUN_00414ea0", 315, 118, 0),
    "0x00414710": ("FUN_00414710", 18, 13, 0),
    "0x0041DD70": ("FUN_0041dd70", 152, 74, 0),
    "0x0041DF10": ("FUN_0041df10", 57, 21, 0),
    "0x0041E990": ("TextQuad_Draw", 35, 26, 0),
    "0x0041FE50": ("FUN_0041fe50", 1287, 300, 0),
    "0x0041FF60": ("FUN_0041ff60", 134, 70, 0),
    "0x00420030": ("FUN_00420030", 56, 50, 0),
    "0x004208A0": ("FUN_004208a0", 439, 160, 0),
    "0x00421560": ("FUN_00421560", 78, 34, 0),
    "0x0041D8F0": ("FUN_0041d8f0", 98, 46, 0),
    "0x0043FD80": ("FUN_0043fd80", 1, 1, 0),
    "0x0046EC80": ("FUN_0046ec80", 1, 0, 1),
    "0x0057D670": ("FUN_0057d670", 2, 1, 0),
}


def _read(path: Path) -> str:
    if not path.is_file():
        raise StaticReTestFailure(
            f"Arena render-pipeline evidence is absent: {path.relative_to(ROOT)}"
        )
    return path.read_text(encoding="utf-8")


def test_native_arena_saturation_shader_and_frame_boundary_are_pinned() -> str:
    report = _read(REPORT_PATH)
    required = (
        "Arena::Render 0x0046EC80",
        "0x0043FD80",
        "0x00B401F4",
        "0x00784DC0",
        "0x0046ECA9",
        "0x0046ECB7",
        "0x00470A6A",
        "0x00470A76",
        "float mSaturation : register(c0)",
        "float aVGrey=(vColor.r+vColor.g+vColor.b)/3",
        "float aGrey=(oCol.r+oCol.g+oCol.b)/3",
        "oCol.rgb=lerp(oCol.rgb,aRealCol.rgb,mSaturation)",
        "out.rgb     = grey * (1 - s) + real * s",
        "out.a       = textureAlpha * vertexAlpha",
        "later gameplay HUD/menu code is outside this shader interval",
        "There is no browser platform blocker",
    )
    normalized = "".join(report.split())
    for token in required:
        if "".join(token.split()) not in normalized:
            raise StaticReTestFailure(
                f"Arena saturation evidence or boundary drifted: {token}"
            )

    scene = _read(SCENE_PATH)
    if "Arena pixel path corrected 2026-08-27" not in scene:
        raise StaticReTestFailure(
            "scene composition still claims closure without the Arena pixel path"
        )
    if "lerp(avg(T)*avg(V), T*V, 0.65)" not in scene:
        raise StaticReTestFailure(
            "scene composition lost the separate texture/vertex saturation formula"
        )

    projectile = _read(PROJECTILE_PATH)
    if "marker, BadGuys-63 ring, splash, and DeadHawg-4 residue all remain inside" not in projectile:
        raise StaticReTestFailure(
            "Acid Rain could again bypass the shared Arena shader in the native report"
        )
    normalized_projectile = " ".join(projectile.split())
    if "A web painter that uses the requested greens directly" not in normalized_projectile:
        raise StaticReTestFailure(
            "Acid's requested tint could again be mistaken for final framebuffer color"
        )

    asset = _read(ASSET_PATH)
    if "without premultiplying RGB by alpha" not in " ".join(asset.split()):
        raise StaticReTestFailure(
            "native page upload lost its unpremultiplied-alpha contract"
        )
    lighting = _read(LIGHTING_PATH)
    if (
        "The `.2375..25` value above is therefore the final native source alpha"
        not in " ".join(lighting.split())
    ):
        raise StaticReTestFailure(
            "late player light could again acquire a non-native browser brightness scale"
        )
    return "Arena saturation, Acid membership, texture alpha, and late-light boundaries are pinned"


def test_native_render_pipeline_caller_catalog_is_complete() -> str:
    try:
        catalog = json.loads(_read(CALLER_CATALOG_PATH))
    except json.JSONDecodeError as exc:
        raise StaticReTestFailure(
            f"native renderer caller catalog is not reviewable JSON: {exc}"
        ) from exc

    if catalog.get("schema") != 1:
        raise StaticReTestFailure("native renderer caller catalog schema drifted")
    if catalog.get("program") != "SolomonDark.exe":
        raise StaticReTestFailure("native renderer caller catalog targets another program")
    if catalog.get("executable_sha256") != RETAIL_SHA256:
        raise StaticReTestFailure("native renderer caller catalog lost retail provenance")
    if catalog.get("image_base") != "0x00400000":
        raise StaticReTestFailure("native renderer caller catalog lost preferred-image addresses")

    targets = catalog.get("targets")
    if not isinstance(targets, list) or len(targets) != len(EXPECTED_TARGETS):
        raise StaticReTestFailure(
            "native renderer caller catalog no longer contains the complete primitive/state target set"
        )
    by_address = {target.get("address"): target for target in targets}
    if set(by_address) != set(EXPECTED_TARGETS):
        raise StaticReTestFailure("native renderer caller target membership drifted")

    for address, (name, references, callers, orphans) in EXPECTED_TARGETS.items():
        target = by_address[address]
        actual = (
            target.get("name"),
            target.get("reference_count"),
            len(target.get("callers", [])),
            len(target.get("orphan_sites", [])),
        )
        if actual != (name, references, callers, orphans):
            raise StaticReTestFailure(
                f"native renderer xref closure drifted for {address}: {actual}"
            )
        for caller in target.get("callers", []):
            callsites = caller.get("callsites")
            if not callsites or any(not site.startswith("0x00") for site in callsites):
                raise StaticReTestFailure(
                    f"native renderer caller {caller.get('address')} lost exact callsites"
                )

    if by_address["0x0046EC80"].get("orphan_sites") != ["0x00785940"]:
        raise StaticReTestFailure(
            "Arena render must retain its vtable data xref instead of inventing a direct caller"
        )
    script = _read(CATALOG_SCRIPT_PATH)
    if '"executable_sha256": executable_sha256' not in script or '"orphan_sites"' not in script:
        raise StaticReTestFailure(
            "renderer catalog generator no longer preserves identity or data xrefs"
        )
    return "all shared renderer primitive and state xrefs are machine-enumerated"


def test_native_arena_render_pipeline_layout_addresses_are_pinned() -> str:
    layout = _read(LAYOUT_PATH)
    required = (
        "[native_arena_render_pipeline]",
        "arena_render=0x0046EC80",
        "shader_initializer=0x0043FD80",
        "saturation_shader_global=0x00B401F4",
        "blur_shader_global=0x00B401F8",
        "saturation_constant=0x00784DC0",
        "saturation_request_offset=0x00000228",
        "blur_request_offset=0x00000230",
        "saturation_bind_write=0x0046ECA9",
        "saturation_restore_write=0x00470A6A",
        "state_dispatcher=0x004208A0",
        "vertex_color_quad_draw=0x0041DF10",
        "filter_selector=0x00421560",
        "buffer_flush=0x0041D8F0",
    )
    for token in required:
        if token not in layout:
            raise StaticReTestFailure(
                f"native Arena render address catalog drifted: {token}"
            )
    return "Arena shader, state, primitive, and flush addresses are pinned"
