"""Static contracts for the G12 native scene-composition reconstruction."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from static_re_contract_support import (
    ROOT,
    StaticReTestFailure,
    assert_recorded_hash_matches_file,
)
from generate_native_scene_atlas_spans import render as render_native_scene_atlas_spans


DOC_PATH = ROOT / "docs/reverse-engineering/native-scene-composition.md"
GOLDEN_PATH = ROOT / "tests/fixtures/webgame/scene-composition-goldens.json"
WORLD_PIPELINE_PATH = ROOT / "docs/re/world-sprite-render-pipeline.md"
DEFAULT_BONEYARD_PATH = (
    ROOT / "docs/reverse-engineering/native-default-boneyard-load-seed-and-decor.md"
)
RNG_PATH = ROOT / "docs/reverse-engineering/native-movement-and-tick.md"
BYSCRIPT_PATH = ROOT / "docs/reverse-engineering/boneyard-scripting.md"
ASSET_MAP_PATH = ROOT / "docs/reverse-engineering/native-asset-object-map.json"
ATLAS_SPANS_PATH = (
    ROOT / "SolomonDarkModLoader/src/native_scene_capture/generated_atlas_spans.inl"
)
SCENE_COORDINATOR_PATH = ROOT / "SolomonDarkModLoader/src/native_scene_capture.cpp"
SCENE_ATLAS_RESOLVER_PATH = (
    ROOT / "SolomonDarkModLoader/src/native_scene_capture/atlas_resolver.inl"
)
SCENE_OBSERVATION_PATH = (
    ROOT / "SolomonDarkModLoader/src/native_scene_capture/observation.inl"
)
SCENE_HOOKS_PATH = ROOT / "SolomonDarkModLoader/src/native_scene_capture/hooks.inl"
SCENE_PUBLIC_API_PATH = (
    ROOT / "SolomonDarkModLoader/src/native_scene_capture/public_api.inl"
)
SCENE_INITIALIZE_PATH = ROOT / "SolomonDarkModLoader/src/mod_loader/initialize.inl"
WORLD_QUEUE_HOOK_PATH = (
    ROOT / "SolomonDarkModLoader/src/lua_world_renderer/native_carrier_queue.inl"
)

LAYER_ORDER = (
    "framebuffer-clear",
    "scene-underlay",
    "world-sorted",
    "scene-overdraw",
    "screen-overlay",
)
CAPTURE_LABELS = (
    "hub_camera_1000_375_final",
    "hub_camera_1200_375_final",
    "boneyard_seed_424242_camera_1000_1000_final",
    "boneyard_seed_424242_camera_1500_1500_final",
)
DRAW_COUNTS = {
    "hub_camera_1000_375_final": 1319,
    "hub_camera_1200_375_final": 1290,
    "boneyard_seed_424242_camera_1000_1000_final": 518,
    "boneyard_seed_424242_camera_1500_1500_final": 491,
}
LAYER_COUNTS = {
    "hub_camera_1000_375_final": {
        "framebuffer-clear": 1,
        "scene-underlay": 80,
        "world-sorted": 203,
        "scene-overdraw": 1035,
    },
    "hub_camera_1200_375_final": {
        "framebuffer-clear": 1,
        "scene-underlay": 83,
        "world-sorted": 171,
        "scene-overdraw": 1035,
    },
    "boneyard_seed_424242_camera_1000_1000_final": {
        "framebuffer-clear": 1,
        "scene-underlay": 477,
        "world-sorted": 40,
    },
    "boneyard_seed_424242_camera_1500_1500_final": {
        "framebuffer-clear": 1,
        "scene-underlay": 486,
        "world-sorted": 4,
    },
}
WORLD_PROJECTION_COUNTS = {
    "hub_camera_1000_375_final": 1318,
    "hub_camera_1200_375_final": 1289,
    "boneyard_seed_424242_camera_1000_1000_final": 517,
    "boneyard_seed_424242_camera_1500_1500_final": 490,
}
SORT_KEY_COUNTS = {
    "hub_camera_1000_375_final": 203,
    "hub_camera_1200_375_final": 171,
    "boneyard_seed_424242_camera_1000_1000_final": 37,
    "boneyard_seed_424242_camera_1500_1500_final": 3,
}
RAW_HASHES = {
    "hub_camera_1000_375_final": (
        "5cf53fcdf9ea2df4a74d0df453ab5628887f332bf8f5c32f3c5d919e41f0c721"
    ),
    "hub_camera_1200_375_final": (
        "583b61d5d9138d04206ba0b3a2c9e4bb0956d95801754cba16aa9480d3a19287"
    ),
    "boneyard_seed_424242_camera_1000_1000_final": (
        "d3956efbf6432aef45adaa5d4616efe1e1eb2a255da250cbb9ba7d0ab8f67f69"
    ),
    "boneyard_seed_424242_camera_1500_1500_final": (
        "bb47b4719a50c9f67778006eb1a40eca7b98e797f8324405e2ca48626aa754d3"
    ),
}
EXPECTED_SOURCE = {
    "base_commit_sha": "50332fc8d53c37bdf83d7ed6a56caf095caf04a1",
    "capture_tree": "base commit plus additive native scene recorder",
    "game_executable_sha256": (
        "03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3"
    ),
    "loader_dll_sha256": (
        "b8b3b2eb170571f01773cb40b4c08e8b12beb431eb07729e4c92491960599d18"
    ),
}


def _read(path: Path) -> str:
    if not path.is_file():
        raise StaticReTestFailure(
            f"scene-composition claim source is absent: {path.relative_to(ROOT)}"
        )
    return path.read_text(encoding="utf-8")


def _load_fixture() -> tuple[str, dict[str, Any], dict[str, dict[str, Any]]]:
    doc = _read(DOC_PATH)
    try:
        golden = json.loads(_read(GOLDEN_PATH))
    except json.JSONDecodeError as exc:
        raise StaticReTestFailure(
            f"scene-composition goldens are not reviewable JSON: {exc}"
        ) from exc
    if golden.get("schema") != "solomon-dark-scene-composition-goldens-v1":
        raise StaticReTestFailure(
            "scene-composition consumers would parse an unrecognized golden schema"
        )
    if golden.get("generated_by") != "tools/build_scene_composition_goldens.py":
        raise StaticReTestFailure(
            "scene-composition draw lists are no longer tied to their validating generator"
        )
    if tuple(golden.get("layer_order", ())) != LAYER_ORDER:
        raise StaticReTestFailure(
            "scene-composition goldens no longer expose the five physical passes in back-to-front order"
        )

    captures = golden.get("captures")
    if not isinstance(captures, list) or len(captures) != len(CAPTURE_LABELS):
        raise StaticReTestFailure(
            "scene-composition camera coverage must remain exactly two hub and two Boneyard captures"
        )
    labels = tuple(capture.get("header", {}).get("label") for capture in captures)
    if labels != CAPTURE_LABELS:
        raise StaticReTestFailure(
            "scene-composition capture order or a named hub/Boneyard camera witness drifted"
        )
    by_label = {capture["header"]["label"]: capture for capture in captures}
    if len(by_label) != len(CAPTURE_LABELS):
        raise StaticReTestFailure(
            "scene-composition lookup is ambiguous because capture labels are duplicated"
        )

    for label in CAPTURE_LABELS:
        capture = by_label[label]
        draws = capture.get("draws")
        if not isinstance(draws, list) or len(draws) != DRAW_COUNTS[label]:
            raise StaticReTestFailure(
                f"{label} no longer carries its complete live ordered draw list"
            )
        orders = [draw.get("draw_order") for draw in draws]
        if orders != list(range(DRAW_COUNTS[label])):
            raise StaticReTestFailure(
                f"{label} draw order is no longer contiguous native submission order"
            )
        header = capture.get("header", {})
        if header.get("instance") != "SolomonDarkModLoader_LuaExec_ren-scene-hub":
            raise StaticReTestFailure(
                f"{label} lost the exact live solo-instance provenance"
            )
        if not header.get("recorded_live"):
            raise StaticReTestFailure(
                f"{label} is no longer declared as a live native recording"
            )
        if header.get("capture_method") != (
            "native Region render + queue insertion/flush + Glyph/TextQuad + mesh/quad hooks"
        ):
            raise StaticReTestFailure(
                f"{label} no longer names the native composition capture boundary"
            )
        if header.get("source") != EXPECTED_SOURCE:
            raise StaticReTestFailure(
                f"{label} no longer identifies the exact source base, game, and recorder DLL"
            )
        raw = header.get("raw_recording", {})
        if raw.get("sha256") != RAW_HASHES[label]:
            raise StaticReTestFailure(
                f"{label} no longer identifies its immutable raw live recording"
            )
        epsilon = header.get("epsilon", {})
        if epsilon.get("screen_pixels") != 0.001 or epsilon.get("world_units") != 0.001:
            raise StaticReTestFailure(
                f"{label} no longer limits replay tolerance to sub-pixel serialization noise"
            )
        if "float32/x87" not in epsilon.get("reason", ""):
            raise StaticReTestFailure(
                f"{label} lost the numeric reason for its 0.001 replay epsilon"
            )
    return doc, golden, by_label


def _projected_rect(world_quad: list[float], camera: dict[str, Any]) -> list[float]:
    view = camera["primary_view"]
    scale = camera["scale"]
    xs = [(world_quad[index] - view[0]) * scale for index in range(0, 8, 2)]
    ys = [(world_quad[index] - view[1]) * scale for index in range(1, 8, 2)]
    return [min(xs), min(ys), max(xs), max(ys)]


def _max_error(left: list[float], right: list[float]) -> float:
    return max(abs(float(a) - float(b)) for a, b in zip(left, right, strict=True))


def _require_regex(text: str, pattern: str, message: str) -> None:
    if re.search(pattern, text, flags=re.MULTILINE) is None:
        raise StaticReTestFailure(message)


def test_native_scene_physical_layer_list_is_pinned() -> str:
    doc, _, captures = _load_fixture()
    physical_rows = (
        r"^\| 0 \| `framebuffer-clear` \|[^\n]*\n"
        r"\| 1 \| `scene-underlay` \|[^\n]*\n"
        r"\| 2 \| `world-sorted` \|[^\n]*\n"
        r"\| 3 \| `scene-overdraw` \|[^\n]*\n"
        r"\| 4 \| `screen-overlay` \|"
    )
    _require_regex(
        doc,
        physical_rows,
        "scene compositor would lose an adjacent back-to-front physical-pass boundary",
    )
    required_role_rows = (
        "Background/backdrop",
        "Terrain",
        "Decor",
        "Actors",
        "Projectiles and effects",
        "Overhead art",
        "World-space UI",
    )
    for role in required_role_rows:
        if f"| {role} |" not in doc:
            raise StaticReTestFailure(
                f"scene compositor no longer states the physical-pass placement of {role}"
            )

    allowed_roles = {
        "framebuffer-clear": {"framebuffer-clear"},
        "scene-underlay": {"background-backdrop", "terrain-base", "scene-underlay-art"},
        "world-sorted": {"shared-world-object"},
        "scene-overdraw": {"overhead-art", "world-space-ui"},
        "screen-overlay": {"screen-overlay-art"},
    }
    observed_roles: set[str] = set()
    layer_rank = {layer: rank for rank, layer in enumerate(LAYER_ORDER)}
    for label in CAPTURE_LABELS:
        draws = captures[label]["draws"]
        counts = Counter(draw["layer"] for draw in draws)
        if dict(counts) != LAYER_COUNTS[label]:
            raise StaticReTestFailure(
                f"{label} no longer preserves the live draw count at each physical pass boundary"
            )
        previous_rank = -1
        for draw in draws:
            layer = draw["layer"]
            role = draw["semantic_role"]
            if layer not in layer_rank:
                raise StaticReTestFailure(
                    f"{label} contains a draw outside the five physical scene passes"
                )
            if layer_rank[layer] < previous_rank:
                raise StaticReTestFailure(
                    f"{label} moves backward between physical passes and changes occlusion"
                )
            previous_rank = layer_rank[layer]
            if role not in allowed_roles[layer]:
                raise StaticReTestFailure(
                    f"{label} assigns semantic role {role!r} to the wrong physical pass"
                )
            observed_roles.add(role)
    expected_observed_roles = {
        "background-backdrop",
        "framebuffer-clear",
        "overhead-art",
        "scene-underlay-art",
        "shared-world-object",
        "terrain-base",
        "world-space-ui",
    }
    if observed_roles != expected_observed_roles:
        raise StaticReTestFailure(
            "live scene goldens no longer witness every captured semantic occupant role"
        )

    coordinator = _read(SCENE_COORDINATOR_PATH)
    public_api = _read(SCENE_PUBLIC_API_PATH)
    initialize = _read(SCENE_INITIALIZE_PATH)
    if '"SDMOD_NATIVE_SCENE_CAPTURE_DIRECTORY"' not in coordinator:
        raise StaticReTestFailure(
            "native scene probe would no longer remain disabled unless explicitly requested"
        )
    if "constexpr std::size_t kMaximumDrawsPerFrame = 32768;" not in coordinator:
        raise StaticReTestFailure(
            "native scene probe would lose its bounded per-frame draw allocation"
        )
    if (
        "native scene capture is busy with label" not in public_api
        or "native scene capture directory is not runnable" not in public_api
        or "native scene capture atlas resolver is runnable but no native atlas records are loaded"
        not in public_api
    ):
        raise StaticReTestFailure(
            "native scene probe would collapse broken, busy, and runnable states into an indefinite wait"
        )
    initialization_sequence = (
        r"^        if \(IsNativeSceneCaptureRequested\(\)\) \{\n"
        r"^            if \(!native_ui_bridge_initialized\) \{"
    )
    _require_regex(
        initialize,
        initialization_sequence,
        "native scene probe could start without proving its real Glyph/TextQuad bridge runs",
    )

    generated_spans = _read(ATLAS_SPANS_PATH)
    if generated_spans != render_native_scene_atlas_spans(ASSET_MAP_PATH):
        raise StaticReTestFailure(
            "native scene atlas resolver no longer matches the reviewed 28-atlas object map"
        )
    for atlas_name, witness in (
        ("BadGuys", '{"BadGuys", 0x00819978'),
        ("College", '{"College", 0x00819984'),
        ("DeadHawg", '{"DeadHawg", 0x00819994'),
        ("UI", '{"UI", 0x008199E4'),
    ):
        if witness not in generated_spans:
            raise StaticReTestFailure(
                f"native scene atlas generation lost named live-art witness {atlas_name}"
            )
    atlas_resolver = _read(SCENE_ATLAS_RESOLVER_PATH)
    if (
        'art.resolution = "ambiguous-direct-address";' not in atlas_resolver
        or 'art.resolution = "ambiguous-live-signature";' not in atlas_resolver
        or "if (art.candidates.size() == 1)" not in atlas_resolver
    ):
        raise StaticReTestFailure(
            "native scene atlas lookup could silently choose between duplicate sprite candidates"
        )

    recorded_hash = re.search(
        r"standalone fixture\s+SHA-256 is `([0-9a-f]{64})`\.", doc
    )
    if recorded_hash is None:
        raise StaticReTestFailure(
            "scene-composition documentation no longer records the committed golden hash"
        )
    assert_recorded_hash_matches_file(
        recorded_hash.group(1),
        GOLDEN_PATH,
        "scene-composition committed golden",
    )
    return "native scene physical layers and semantic occupants are pinned"


def test_native_scene_world_sort_key_and_ties_are_pinned() -> str:
    doc, _, captures = _load_fixture()
    formula = (
        r"^floor_y\s+= floor\(object\.world_y\)\n"
        r"^floor_sort_bias = floor\(object\.sort_bias\)\n"
        r"^reference_y\s+= floor\(local_player\.world_y\)\n"
        r"^relative\s+= floor_y \+ floor_sort_bias - reference_y\n"
        r"^bucket_offset\s+= trunc_toward_zero\(relative / 2\)\n"
        r"^bucket_index\s+= queue\.origin \+ bucket_offset$"
    )
    _require_regex(
        doc,
        formula,
        "world queue would compute a different floor/bias/reference/two-unit bucket key",
    )
    flattened_doc = " ".join(doc.split())
    for phrase, consequence in (
        (
            "everything in the same two-world-unit bucket remains in insertion order",
            "normal-bucket ties would lose stable native insertion order",
        ),
        (
            "existing_y <= new_y",
            "overflow raw-Y ties would no longer remain stable",
        ),
        (
            "leading overflow list, normal buckets from index zero upward, then the trailing overflow list",
            "world queue lanes would flush in the wrong back-to-front order",
        ),
    ):
        if " ".join(phrase.split()) not in flattened_doc:
            raise StaticReTestFailure(consequence)

    world_pipeline = _read(WORLD_PIPELINE_PATH)
    if "Sack` constructor overrides `+0xA0` with the stock constant `-25.0`" not in world_pipeline:
        raise StaticReTestFailure(
            "sort_bias would lose the stock drop-carrier witness that distinguishes it from raw Y"
        )

    observation_source = _read(SCENE_OBSERVATION_PATH)
    source_formula = (
        r"^    sort\.floor_world_y = static_cast<std::int32_t>\(std::floor\(sort\.world_y\)\);\n"
        r"^    sort\.floor_sort_bias =\n"
        r"^        static_cast<std::int32_t>\(std::floor\(sort\.sort_bias\)\);\n"
        r"^    sort\.relative =\n"
        r"^        sort\.floor_world_y \+ sort\.floor_sort_bias - reference_y;\n"
        r"^    sort\.bucket_offset = sort\.relative / 2;\n"
        r"^    sort\.bucket_index = origin \+ sort\.bucket_offset;"
    )
    _require_regex(
        observation_source,
        source_formula,
        "live sort probe would record a key different from the documented native queue arithmetic",
    )
    queue_hook = _read(WORLD_QUEUE_HOOK_PATH)
    flush_sequence = (
        r"^    NativeSceneCaptureBeginSortedQueue\(self, pass\);\n"
        r"^    InsertWorldSpriteCarriers\(self, pass\);\n"
        r"^    original\(self, pass\);\n"
        r"^    NativeSceneCaptureEndSortedQueue\(self, pass\);$"
    )
    _require_regex(
        queue_hook,
        flush_sequence,
        "live sort probe would not bracket the complete shared queue flush including loader carriers",
    )

    expected_missing = {
        "hub_camera_1000_375_final": [],
        "hub_camera_1200_375_final": [],
        "boneyard_seed_424242_camera_1000_1000_final": [
            (503, "DeadHawg.243"),
            (512, "BadGuys.34"),
            (517, "DeadHawg.243"),
        ],
        "boneyard_seed_424242_camera_1500_1500_final": [(487, "BadGuys.34")],
    }
    lane_rank = {"leading-overflow": 0, "normal": 1, "trailing-overflow": 2}
    for label in CAPTURE_LABELS:
        draws = captures[label]["draws"]
        keyed = [draw for draw in draws if draw["sort_key"] is not None]
        if len(keyed) != SORT_KEY_COUNTS[label]:
            raise StaticReTestFailure(
                f"{label} no longer carries every safely observable native queue key"
            )
        missing = [
            (draw["draw_order"], draw["sprite"]["id"])
            for draw in draws
            if draw["layer"] == "world-sorted" and draw["sort_key"] is None
        ]
        if missing != expected_missing[label]:
            raise StaticReTestFailure(
                f"{label} changed the explicitly bounded set of queue draws whose object context is not safely observable"
            )
        non_world_keys = [
            draw["draw_order"]
            for draw in draws
            if draw["layer"] != "world-sorted" and draw["sort_key"] is not None
        ]
        if non_world_keys:
            raise StaticReTestFailure(
                f"{label} invents queue sort keys for direct physical-pass draws"
            )

        entry_order: list[tuple[Any, ...]] = []
        prior_identity: tuple[Any, ...] | None = None
        for draw in keyed:
            key = draw["sort_key"]
            floor_y = math.floor(key["world_y"])
            floor_bias = math.floor(key["sort_bias"])
            relative = floor_y + floor_bias - key["reference_y"]
            bucket_offset = math.trunc(relative / 2)
            bucket_index = key["queue_origin"] + bucket_offset
            expected_lane = (
                "leading-overflow"
                if bucket_index < 0
                else "trailing-overflow"
                if bucket_index >= key["queue_bucket_count"]
                else "normal"
            )
            derived = (
                floor_y,
                floor_bias,
                relative,
                bucket_offset,
                bucket_index,
                expected_lane,
            )
            recorded = (
                key["floor_world_y"],
                key["floor_sort_bias"],
                key["relative"],
                key["bucket_offset"],
                key["bucket_index"],
                key["lane"],
            )
            if recorded != derived:
                raise StaticReTestFailure(
                    f"{label} draw {draw['draw_order']} no longer replays the exact native sort-key formula"
                )
            identity = (
                key["lane"],
                key["gather_index"],
                key["world_y"],
                key["sort_bias"],
                key["bucket_index"],
            )
            if identity != prior_identity:
                lane = lane_rank[key["lane"]]
                if key["lane"] == "normal":
                    entry_order.append((lane, key["bucket_index"], key["gather_index"]))
                else:
                    entry_order.append((lane, key["world_y"], key["gather_index"]))
                prior_identity = identity
        if not entry_order:
            raise StaticReTestFailure(
                f"{label} has no distinct queue entry to test native flush ordering"
            )
        if entry_order != sorted(entry_order):
            raise StaticReTestFailure(
                f"{label} no longer flushes overflow lanes/buckets with their native stable tie order"
            )

    tie_capture = captures["hub_camera_1200_375_final"]["draws"]
    earlier = tie_capture[100]["sort_key"]
    later = tie_capture[114]["sort_key"]
    if not (
        tie_capture[100]["sprite"]["id"] == "Clothes.880"
        and tie_capture[114]["sprite"]["id"] == "Clothes.908"
        and earlier["bucket_index"] == later["bucket_index"] == 250
        and earlier["gather_index"] == 12
        and later["gather_index"] == 21
        and earlier["world_y"] > later["world_y"]
    ):
        raise StaticReTestFailure(
            "normal bucket 250 no longer proves insertion order wins over a lower raw Y"
        )
    return "native world queue key, lane order, and stable ties are pinned"


def test_native_scene_camera_transform_and_backdrop_rate_are_pinned() -> str:
    doc, golden, captures = _load_fixture()
    transform = (
        r"^sx = \(wx - vx\) \* s\n"
        r"^sy = \(wy - vy\) \* s\n"
        r"^\n"
        r"^wx = sx / s \+ vx\n"
        r"^wy = sy / s \+ vy\n"
        r"^\n"
        r"^viewport_width_px\s+= vw \* s\n"
        r"^viewport_height_px = vh \* s$"
    )
    _require_regex(
        doc,
        transform,
        "browser projection would no longer subtract the primary origin and apply uniform native scale",
    )
    _require_regex(
        doc,
        r"^aim_anchor_px = project\(player_world\) \+ \(0, -25\)$",
        "P0 would lose the native 25-screen-pixel aim anchor",
    )
    aim_transform = (
        r"^reach_px = min\(aim_anchor_px\.x,\n"
        r"^\s+W - aim_anchor_px\.x,\n"
        r"^\s+aim_anchor_px\.y,\n"
        r"^\s+H - aim_anchor_px\.y\)\n"
        r"^\n"
        r"^reach_world = reach_px / camera_scale\n"
        r"^aim_world = player_world \+ \(0, -25 / camera_scale\)\n"
        r"^\s+\+ normalize\(stick\) \* reach_world$"
    )
    _require_regex(
        doc,
        aim_transform,
        "P0 would lose the screen-pixel aim anchor and scale-derived world reach",
    )

    for label in CAPTURE_LABELS:
        capture = captures[label]
        camera = capture["header"]["camera"]
        epsilon = capture["header"]["epsilon"]["screen_pixels"]
        world_draws = [
            draw
            for draw in capture["draws"]
            if draw["world_transform"]["space"] == "world"
        ]
        if len(world_draws) != WORLD_PROJECTION_COUNTS[label]:
            raise StaticReTestFailure(
                f"{label} no longer supplies the complete world-space projection witness set"
            )
        for draw in world_draws:
            quad = draw["world_transform"].get("inverse_projected_quad")
            if not isinstance(quad, list) or len(quad) != 8:
                raise StaticReTestFailure(
                    f"{label} draw {draw['draw_order']} lost its four recorded world vertices"
                )
            if not isinstance(draw.get("resolved_screen_rect"), list) or len(
                draw["resolved_screen_rect"]
            ) != 4:
                raise StaticReTestFailure(
                    f"{label} draw {draw['draw_order']} lost its complete resolved screen rectangle"
                )
            expected = _projected_rect(quad, camera)
            if _max_error(expected, draw["resolved_screen_rect"]) > epsilon:
                raise StaticReTestFailure(
                    f"{label} draw {draw['draw_order']} violates the primary-view world-to-screen formula"
                )
        view = camera["primary_view"]
        clear_rect = capture["draws"][0]["resolved_screen_rect"]
        expected_viewport = [0.0, 0.0, view[2] * camera["scale"], view[3] * camera["scale"]]
        if _max_error(clear_rect, expected_viewport) > epsilon:
            raise StaticReTestFailure(
                f"{label} physical viewport no longer equals primary-view size times scale"
            )

    observation_source = _read(SCENE_OBSERVATION_PATH)
    inverse_projection = (
        r"^        draw->inverse_projected_world_quad\[index \* 2\] =\n"
        r"^            camera\.primary_view\[0\] \+\n"
        r"^            draw->screen_quad\[index \* 2\] / camera\.scale;\n"
        r"^        draw->inverse_projected_world_quad\[index \* 2 \+ 1\] =\n"
        r"^            camera\.primary_view\[1\] \+\n"
        r"^            draw->screen_quad\[index \* 2 \+ 1\] / camera\.scale;"
    )
    _require_regex(
        observation_source,
        inverse_projection,
        "live camera probe would no longer invert screen quads with primary origin and uniform scale",
    )
    hooks_source = _read(SCENE_HOOKS_PATH)
    for region_witness in (
        '"courtyard_render"',
        '"mortuary_render"',
        '"storeroom_render"',
        '"library_render"',
        '"office_render"',
    ):
        if region_witness not in hooks_source:
            raise StaticReTestFailure(
                f"live camera probe lost fixed-Region render root {region_witness.strip(chr(34))}"
            )

    move = golden["cross_capture_observations"].get("hub_camera_move", {})
    witnesses = move.get("witnesses")
    if not isinstance(witnesses, list) or len(witnesses) != 3:
        raise StaticReTestFailure(
            "hub camera move no longer has three unambiguous compiled-backdrop witnesses"
        )
    if [entry.get("sprite_id") for entry in witnesses] != [
        "College.63",
        "College.64",
        "College.65",
    ]:
        raise StaticReTestFailure(
            "hub camera move silently selected a different or duplicate backdrop candidate"
        )
    for witness in witnesses:
        if witness.get("parallax_factor") != 1:
            raise StaticReTestFailure(
                f"{witness.get('sprite_id')} no longer proves the native backdrop moves at full camera rate"
            )
        if abs(witness["screen_left_delta"] - witness["expected_screen_delta"]) > 0.001:
            raise StaticReTestFailure(
                f"{witness['sprite_id']} backdrop displacement no longer matches -origin_delta * scale"
            )
        if witness["world_quad_max_error"] > 0.001:
            raise StaticReTestFailure(
                f"{witness['sprite_id']} changed world geometry instead of only camera projection"
            )
    boneyard_move = golden["cross_capture_observations"].get("boneyard_camera_move", {})
    if boneyard_move.get("world_sorted_draw_count") != {"before": 40, "after": 4}:
        raise StaticReTestFailure(
            "moved Boneyard capture no longer proves camera-dependent shared-queue culling"
        )
    if boneyard_move.get("visible_draw_count") != {"before": 131, "after": 97}:
        raise StaticReTestFailure(
            "moved Boneyard capture no longer proves finite scene visibility changes"
        )
    return "native camera projection, viewport, backdrop rate, and culling are pinned"


def test_native_scene_decor_determinism_path_is_pinned() -> str:
    doc, golden, captures = _load_fixture()
    generation_path = (
        r"^main-menu case 3\n"
        r"^    -> data\\levels\\survival\.boneyard Gameplay template\n"
        r"^    -> Gameplay_SwitchRegion\(region 5\)\n"
        r"^    -> Arena_Create\n"
        r"^    -> choose play\.boneyard or testrun\.boneyard\n"
        r"^    -> BoneyardGenerator 0x006388B0\n"
        r"^    -> serialize temporary Arena/RegionLayout\n"
        r"^    -> read through the ordinary structured loader\n"
        r"^    -> RegionLayout materialization 0x006531B0$"
    )
    _require_regex(
        doc,
        generation_path,
        "decor determinism would skip or reorder the native generate-save-reload-materialize path",
    )

    default_boneyard = _read(DEFAULT_BONEYARD_PATH)
    flattened_default_boneyard = " ".join(default_boneyard.split())
    for token, consequence in (
        (
            'ReinitializeAppliedRunGenerationSeedForArenaCreate("arena_create_pre_stock")',
            "decor generation lost the exact pre-Arena_Create reseed boundary",
        ),
        (
            "The integer draw at `0x0063890D` chooses a derived seed in `0..999999`",
            "decor generation lost the first native Boneyard private-stream seed draw",
        ),
        (
            "copy all `0x3A` dwords",
            "decor generation lost the 58-dword private-to-active RNG transfer",
        ),
        (
            "After reload, `0x006531B0`",
            "decor generation lost the RegionLayout materialization boundary",
        ),
    ):
        if " ".join(token.split()) not in flattened_default_boneyard:
            raise StaticReTestFailure(consequence)

    rng_doc = _read(RNG_PATH)
    flattened_rng_doc = " ".join(rng_doc.split())
    if "55-word additive lagged-Fibonacci generator modulo `2^30`" not in flattened_rng_doc:
        raise StaticReTestFailure(
            "decor selection no longer cites G1's exact native RNG family"
        )
    if "seed = *(int *)(*(App **)0x00b401a8 + 0x28) * 0xEF3" not in flattened_rng_doc:
        raise StaticReTestFailure(
            "decor selection no longer preserves G1's App-tick stock seeding source"
        )

    byscript = _read(BYSCRIPT_PATH)
    flattened_byscript = " ".join(byscript.split())
    if "post-load pass at `0x0064BC40` resolves those UIDs" not in flattened_byscript:
        raise StaticReTestFailure(
            "byscript recipes could be mistaken for a second static decor seed instead of post-load UID relinking"
        )
    if "Spawn events create transient `Spawner` objects" not in flattened_byscript:
        raise StaticReTestFailure(
            "runtime recipe spawns could be collapsed into the static decor draw list"
        )

    for label in CAPTURE_LABELS[2:]:
        scene = captures[label]["header"].get("scene", {})
        if scene.get("run_seed") != 424242 or scene.get("run_seed_hex") != "0x00067932":
            raise StaticReTestFailure(
                f"{label} no longer records the exact deterministic Boneyard input seed"
            )
        if scene.get("reseed_boundary") != "arena_create_pre_stock":
            raise StaticReTestFailure(
                f"{label} no longer records where the seed becomes authoritative"
            )
        if scene.get("template") != "play.boneyard":
            raise StaticReTestFailure(
                f"{label} no longer distinguishes the stock generated play path from testrun"
            )

    replay = golden["cross_capture_observations"].get("same_seed_boneyard_replay", {})
    expected_replay = {
        "run_seed": 424242,
        "reseed_boundary": "arena_create_pre_stock",
        "compared_prequeue_draws_each": 477,
        "sprite_atlas_kind_and_submitted_position_mismatches": 0,
        "matrix_mismatches": 1,
        "inverse_projected_quad_mismatches": 1,
        "tint_mismatches": 1,
    }
    for key, expected in expected_replay.items():
        if replay.get(key) != expected:
            raise StaticReTestFailure(
                f"same-seed decor replay no longer pins {key} at the layout/presentation boundary"
            )
    if replay.get("first_recording", {}).get("sha256") != (
        "20a9cb2a2dfa3f39a67cfaa1ace7b8eeb97a69dfd7eadc4378bdb844e0cd7f11"
    ):
        raise StaticReTestFailure(
            "same-seed decor comparison lost its first immutable live recording"
        )
    if replay.get("second_recording", {}).get("sha256") != RAW_HASHES[
        "boneyard_seed_424242_camera_1000_1000_final"
    ]:
        raise StaticReTestFailure(
            "same-seed decor comparison lost its second immutable live recording"
        )

    center = captures["boneyard_seed_424242_camera_1000_1000_final"]
    terrain = [
        draw for draw in center["draws"] if draw["semantic_role"] == "terrain-base"
    ]
    if len(terrain) != 12:
        raise StaticReTestFailure(
            "generated Boneyard no longer witnesses its finite 12-tile visible base coverage"
        )
    expected_positions = [
        [x, y]
        for x in (350, 700, 1050, 1400)
        for y in (350, 700, 1050)
    ]
    if [draw["world_transform"]["submitted_position"] for draw in terrain] != expected_positions:
        raise StaticReTestFailure(
            "generated Boneyard base tiles no longer follow the recorded 350-world-unit grid"
        )
    if any(draw["sprite"]["id"] != "DeadHawg.12" for draw in terrain):
        raise StaticReTestFailure(
            "generated Boneyard environment mode no longer resolves its concrete base sprite"
        )
    return "native decor RNG, save/reload, materialization, and byscript boundary are pinned"
