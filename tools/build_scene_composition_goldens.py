#!/usr/bin/env python3
"""Build the committed scene-composition fixture from native live captures.

The native recorder writes evidence-bundle JSON. This tool validates the
recording invariants and copies only the renderer-facing fields into the
committed golden. It never synthesizes a draw or repairs an ambiguous sprite.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any


SCHEMA = "solomon-dark-scene-composition-goldens-v1"
RAW_SCHEMA = "solomon-dark-native-scene-capture-v1"
LAYER_ORDER = [
    "framebuffer-clear",
    "scene-underlay",
    "world-sorted",
    "scene-overdraw",
    "screen-overlay",
]
CAPTURES = [
    {
        "filename": "hub_camera_1000_375_final.json",
        "label": "hub_camera_1000_375_final",
        "camera_center": [1000.0, 375.0],
        "scene": {"kind": "courtyard", "name": "hub"},
    },
    {
        "filename": "hub_camera_1200_375_final.json",
        "label": "hub_camera_1200_375_final",
        "camera_center": [1200.0, 375.0],
        "scene": {"kind": "courtyard", "name": "hub"},
    },
    {
        "filename": "boneyard_seed_424242_camera_1000_1000_final.json",
        "label": "boneyard_seed_424242_camera_1000_1000_final",
        "camera_center": [1000.0, 1000.0],
        "scene": {
            "kind": "arena",
            "name": "generated-boneyard",
            "run_seed": 424242,
            "run_seed_hex": "0x00067932",
            "reseed_boundary": "arena_create_pre_stock",
            "template": "play.boneyard",
        },
    },
    {
        "filename": "boneyard_seed_424242_camera_1500_1500_final.json",
        "label": "boneyard_seed_424242_camera_1500_1500_final",
        "camera_center": [1500.0, 1500.0],
        "scene": {
            "kind": "arena",
            "name": "generated-boneyard",
            "run_seed": 424242,
            "run_seed_hex": "0x00067932",
            "reseed_boundary": "arena_create_pre_stock",
            "template": "play.boneyard",
        },
    },
]
REPLAY_FIRST_FILENAME = "boneyard_seed_424242_camera_1000_1000_pixels.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-base-sha", required=True)
    parser.add_argument("--game-sha256", required=True)
    parser.add_argument("--loader-sha256", required=True)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_hex(value: str, length: int, name: str) -> str:
    normalized = value.lower()
    if len(normalized) != length or any(c not in "0123456789abcdef" for c in normalized):
        raise ValueError(f"{name} must be exactly {length} lowercase hexadecimal characters")
    return normalized


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"{path.name}: root must be an object")
    return value


def camera_center(camera: dict[str, Any]) -> list[float]:
    view = camera["primary_view"]
    return [view[0] + view[2] / 2.0, view[1] + view[3] / 2.0]


def projected_rect(world_quad: list[float], camera: dict[str, Any]) -> list[float]:
    if len(world_quad) != 8:
        raise ValueError("world quad must contain exactly four x/y points")
    view = camera["primary_view"]
    scale = camera["scale"]
    xs = [(world_quad[i] - view[0]) * scale for i in range(0, 8, 2)]
    ys = [(world_quad[i] - view[1]) * scale for i in range(1, 8, 2)]
    return [min(xs), min(ys), max(xs), max(ys)]


def max_error(actual: list[float], expected: list[float]) -> float:
    if len(actual) != len(expected):
        raise ValueError("coordinate arrays have different lengths")
    return max(abs(float(a) - float(b)) for a, b in zip(actual, expected, strict=True))


def validate_sort_key(key: dict[str, Any], label: str, draw_order: int) -> None:
    floor_y = math.floor(float(key["world_y"]))
    floor_bias = math.floor(float(key["sort_bias"]))
    relative = floor_y + floor_bias - int(key["reference_y"])
    bucket_offset = math.trunc(relative / 2)
    bucket_index = int(key["queue_origin"]) + bucket_offset
    if floor_y != key["floor_world_y"]:
        raise ValueError(f"{label} draw {draw_order}: recorded floor(world_y) is wrong")
    if floor_bias != key["floor_sort_bias"]:
        raise ValueError(f"{label} draw {draw_order}: recorded floor(sort_bias) is wrong")
    if relative != key["relative"]:
        raise ValueError(f"{label} draw {draw_order}: recorded relative sort value is wrong")
    if bucket_offset != key["bucket_offset"]:
        raise ValueError(f"{label} draw {draw_order}: recorded bucket offset is wrong")
    if bucket_index != key["bucket_index"]:
        raise ValueError(f"{label} draw {draw_order}: recorded bucket index is wrong")
    if bucket_index < 0:
        lane = "leading-overflow"
    elif bucket_index >= int(key["queue_bucket_count"]):
        lane = "trailing-overflow"
    else:
        lane = "normal"
    if lane != key["lane"]:
        raise ValueError(f"{label} draw {draw_order}: recorded queue lane is wrong")


def validate_raw(raw: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    label = spec["label"]
    if raw.get("schema") != RAW_SCHEMA:
        raise ValueError(f"{label}: unexpected raw schema")
    if raw.get("label") != label:
        raise ValueError(f"{label}: raw label does not match its unique filename")
    if raw.get("layer_order") != LAYER_ORDER:
        raise ValueError(f"{label}: native layer order does not match the five-pass contract")
    if raw.get("scene", {}).get("kind") != spec["scene"]["kind"]:
        raise ValueError(f"{label}: live scene kind does not match the requested capture")
    epsilon = raw.get("epsilon")
    if not isinstance(epsilon, dict) or not epsilon.get("reason"):
        raise ValueError(f"{label}: live header lacks an epsilon justification")
    if float(epsilon.get("screen_pixels", 0)) <= 0:
        raise ValueError(f"{label}: screen epsilon must be positive")

    observed_center = camera_center(raw["camera"])
    if max_error(observed_center, spec["camera_center"]) > float(epsilon["world_units"]):
        raise ValueError(f"{label}: live camera is not at its named world position")

    draws = raw.get("draws")
    if not isinstance(draws, list) or len(draws) < 1:
        raise ValueError(f"{label}: live draw list is empty")
    ranks = {name: rank for rank, name in enumerate(LAYER_ORDER)}
    previous_rank = -1
    world_projection_witnesses = 0
    sort_witnesses = 0
    for expected_order, draw in enumerate(draws):
        if draw.get("draw_order") != expected_order:
            raise ValueError(f"{label}: draw order is not contiguous at {expected_order}")
        layer = draw.get("layer")
        if layer not in ranks:
            raise ValueError(f"{label} draw {expected_order}: unknown physical layer")
        if ranks[layer] < previous_rank:
            raise ValueError(f"{label} draw {expected_order}: physical layers move backwards")
        previous_rank = ranks[layer]

        sprite = draw.get("sprite")
        if not isinstance(sprite, dict) or not sprite.get("id") or not sprite.get("atlas"):
            raise ValueError(f"{label} draw {expected_order}: sprite/atlas identity is absent")
        candidates = sprite.get("candidates", [])
        if len(candidates) > 1:
            raise ValueError(f"{label} draw {expected_order}: sprite resolution is ambiguous")
        if sprite.get("resolution") == "ambiguous-live-signature":
            raise ValueError(f"{label} draw {expected_order}: ambiguous signature was accepted")

        tint = draw.get("tint")
        if not isinstance(tint, dict) or set(tint) != {"r", "g", "b", "a"}:
            raise ValueError(f"{label} draw {expected_order}: complete RGBA tint is absent")
        if any(not 0.0 <= float(tint[channel]) <= 1.0 for channel in tint):
            raise ValueError(f"{label} draw {expected_order}: RGBA tint is outside [0, 1]")

        transform = draw.get("world_transform")
        if not isinstance(transform, dict):
            raise ValueError(f"{label} draw {expected_order}: world transform is absent")
        rect = draw.get("resolved_screen_rect")
        if not isinstance(rect, list) or len(rect) != 4:
            raise ValueError(f"{label} draw {expected_order}: resolved screen rect is absent")
        if transform.get("space") == "world":
            quad = transform.get("inverse_projected_quad")
            if not isinstance(quad, list):
                raise ValueError(f"{label} draw {expected_order}: world quad is absent")
            expected_rect = projected_rect(quad, raw["camera"])
            if max_error(expected_rect, rect) > float(epsilon["screen_pixels"]):
                raise ValueError(
                    f"{label} draw {expected_order}: world-to-screen transform exceeds epsilon"
                )
            world_projection_witnesses += 1

        key = draw.get("sort_key")
        if key is not None:
            if layer != "world-sorted":
                raise ValueError(f"{label} draw {expected_order}: queue key escaped world-sorted")
            validate_sort_key(key, label, expected_order)
            sort_witnesses += 1
    if world_projection_witnesses == 0:
        raise ValueError(f"{label}: no world-space draw exercised camera projection")
    if sort_witnesses == 0:
        raise ValueError(f"{label}: no draw exercised native queue-key capture")

    return {
        "draw_count": len(draws),
        "world_projection_witnesses": world_projection_witnesses,
        "sort_key_witnesses": sort_witnesses,
    }


def normalized_draw(draw: dict[str, Any]) -> dict[str, Any]:
    sprite = draw["sprite"]
    return {
        "draw_order": draw["draw_order"],
        "layer": draw["layer"],
        "semantic_role": draw["semantic_role"],
        "native_phase": draw["native_phase"],
        "draw_kind": draw["draw_kind"],
        "caller": draw["caller"],
        "sprite": {
            "id": sprite["id"],
            "atlas": sprite["atlas"],
            "index": sprite["index"],
            "texture_handle": sprite["texture_handle"],
            "resolution": sprite["resolution"],
        },
        "world_transform": draw["world_transform"],
        "tint": draw["tint"],
        "lighting_scalar": draw["lighting_scalar"],
        "blend": draw["blend"],
        "resolved_screen_rect": draw["resolved_screen_rect"],
        "visible": draw["visible"],
        "sort_key": draw["sort_key"],
    }


def capture_fixture(
    raw_path: Path,
    raw: dict[str, Any],
    spec: dict[str, Any],
    validation: dict[str, Any],
    source: dict[str, str],
) -> dict[str, Any]:
    camera = dict(raw["camera"])
    camera["center_world"] = camera_center(camera)
    return {
        "header": {
            "label": spec["label"],
            "instance": raw["instance"],
            "source": source,
            "capture_method": raw["capture_method"],
            "recorded_live": True,
            "raw_recording": {
                "evidence_filename": raw_path.name,
                "sha256": sha256_file(raw_path),
                "bytes": raw_path.stat().st_size,
            },
            "epsilon": raw["epsilon"],
            "scene": spec["scene"],
            "camera": camera,
            "validation": validation,
        },
        "draws": [normalized_draw(draw) for draw in raw["draws"]],
    }


def unique_sprite(draws: list[dict[str, Any]], sprite_id: str, label: str) -> dict[str, Any]:
    matches = [draw for draw in draws if draw["sprite"]["id"] == sprite_id]
    if len(matches) != 1:
        raise ValueError(
            f"{label}: expected one {sprite_id} backdrop witness, found {len(matches)}"
        )
    return matches[0]


def build_hub_camera_observation(
    first: dict[str, Any], second: dict[str, Any]
) -> dict[str, Any]:
    first_header = first["header"]
    second_header = second["header"]
    origin_delta = [
        second_header["camera"]["primary_view"][axis]
        - first_header["camera"]["primary_view"][axis]
        for axis in (0, 1)
    ]
    if max_error(origin_delta, [200.0, 0.0]) > first_header["epsilon"]["world_units"]:
        raise ValueError("hub camera pair does not contain the requested +200 world-X move")
    scale = first_header["camera"]["scale"]
    witnesses = []
    for sprite_id in ("College.63", "College.64", "College.65"):
        before = unique_sprite(first["draws"], sprite_id, first_header["label"])
        after = unique_sprite(second["draws"], sprite_id, second_header["label"])
        world_before = before["world_transform"]["inverse_projected_quad"]
        world_after = after["world_transform"]["inverse_projected_quad"]
        world_error = max_error(world_before, world_after)
        screen_delta = after["resolved_screen_rect"][0] - before["resolved_screen_rect"][0]
        expected_delta = -origin_delta[0] * scale
        if world_error > first_header["epsilon"]["world_units"]:
            raise ValueError(f"{sprite_id}: world backdrop geometry changed across camera move")
        if abs(screen_delta - expected_delta) > first_header["epsilon"]["screen_pixels"]:
            raise ValueError(f"{sprite_id}: backdrop did not move at the full camera rate")
        witnesses.append(
            {
                "sprite_id": sprite_id,
                "world_quad_max_error": world_error,
                "screen_left_delta": screen_delta,
                "expected_screen_delta": expected_delta,
                "parallax_factor": 1,
            }
        )
    return {
        "from_capture": first_header["label"],
        "to_capture": second_header["label"],
        "camera_origin_delta_world": origin_delta,
        "camera_scale": scale,
        "witnesses": witnesses,
        "conclusion": "compiled hub backdrop is finite world art at full camera rate",
    }


def count_layer(capture: dict[str, Any], layer: str) -> int:
    return sum(draw["layer"] == layer for draw in capture["draws"])


def count_visible(capture: dict[str, Any]) -> int:
    return sum(bool(draw["visible"]) for draw in capture["draws"])


def build_boneyard_camera_observation(
    first: dict[str, Any], second: dict[str, Any]
) -> dict[str, Any]:
    return {
        "from_capture": first["header"]["label"],
        "to_capture": second["header"]["label"],
        "same_generated_run_seed": 424242,
        "camera_center_delta_world": [
            second["header"]["camera"]["center_world"][axis]
            - first["header"]["camera"]["center_world"][axis]
            for axis in (0, 1)
        ],
        "world_sorted_draw_count": {
            "before": count_layer(first, "world-sorted"),
            "after": count_layer(second, "world-sorted"),
        },
        "visible_draw_count": {
            "before": count_visible(first),
            "after": count_visible(second),
        },
        "conclusion": "camera movement changes finite Arena submissions and queue culling",
    }


def prequeue_art(raw: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        draw
        for draw in raw["draws"]
        if draw["native_phase"] == "pre-queue"
        and draw["sprite"]["id"] != "native.framebuffer-clear"
    ]


def mismatch_count(
    first: list[dict[str, Any]], second: list[dict[str, Any]], getter: Any
) -> int:
    return sum(getter(a) != getter(b) for a, b in zip(first, second, strict=True))


def build_same_seed_observation(
    first_path: Path, first_raw: dict[str, Any], second_path: Path, second_raw: dict[str, Any]
) -> dict[str, Any]:
    first = prequeue_art(first_raw)
    second = prequeue_art(second_raw)
    if len(first) != len(second):
        raise ValueError("same-seed replay has different pre-queue art counts")

    selection = lambda draw: (
        draw["draw_kind"],
        draw["sprite"]["id"],
        draw["sprite"]["atlas"],
        draw["sprite"]["index"],
        draw["world_transform"]["submitted_position"],
    )
    selection_mismatches = mismatch_count(first, second, selection)
    matrix_mismatches = mismatch_count(
        first, second, lambda draw: draw["world_transform"]["matrix"]
    )
    world_quad_mismatches = mismatch_count(
        first, second, lambda draw: draw["world_transform"]["inverse_projected_quad"]
    )
    tint_mismatches = mismatch_count(first, second, lambda draw: draw["tint"])
    if len(first) != 477:
        raise ValueError("same-seed replay no longer has the 477 recorded pre-queue draws")
    if selection_mismatches != 0:
        raise ValueError("same-seed replay changed static sprite selection or placement")
    if (matrix_mismatches, world_quad_mismatches, tint_mismatches) != (1, 1, 1):
        raise ValueError("same-seed replay no longer isolates its one presentation-state difference")
    return {
        "run_seed": 424242,
        "reseed_boundary": "arena_create_pre_stock",
        "first_recording": {
            "evidence_filename": first_path.name,
            "sha256": sha256_file(first_path),
            "bytes": first_path.stat().st_size,
        },
        "second_recording": {
            "evidence_filename": second_path.name,
            "sha256": sha256_file(second_path),
            "bytes": second_path.stat().st_size,
        },
        "compared_prequeue_draws_each": len(first),
        "sprite_atlas_kind_and_submitted_position_mismatches": selection_mismatches,
        "matrix_mismatches": matrix_mismatches,
        "inverse_projected_quad_mismatches": world_quad_mismatches,
        "tint_mismatches": tint_mismatches,
        "conclusion": "seeded layout selection and placement match; presentation state is a separate pixel input",
    }


def main() -> None:
    args = parse_args()
    source_base_sha = require_hex(args.source_base_sha, 40, "source base SHA")
    game_sha256 = require_hex(args.game_sha256, 64, "game SHA-256")
    loader_sha256 = require_hex(args.loader_sha256, 64, "loader SHA-256")
    source = {
        "base_commit_sha": source_base_sha,
        "capture_tree": "base commit plus additive native scene recorder",
        "game_executable_sha256": game_sha256,
        "loader_dll_sha256": loader_sha256,
    }

    captures: list[dict[str, Any]] = []
    raw_by_label: dict[str, dict[str, Any]] = {}
    raw_path_by_label: dict[str, Path] = {}
    for spec in CAPTURES:
        raw_path = args.raw_directory / spec["filename"]
        if not raw_path.is_file():
            raise FileNotFoundError(f"required live recording is absent: {raw_path}")
        raw = load_json(raw_path)
        validation = validate_raw(raw, spec)
        fixture = capture_fixture(raw_path, raw, spec, validation, source)
        captures.append(fixture)
        raw_by_label[spec["label"]] = raw
        raw_path_by_label[spec["label"]] = raw_path

    replay_first_path = args.raw_directory / REPLAY_FIRST_FILENAME
    if not replay_first_path.is_file():
        raise FileNotFoundError(f"required same-seed recording is absent: {replay_first_path}")
    replay_first_raw = load_json(replay_first_path)
    replay_second_label = "boneyard_seed_424242_camera_1000_1000_final"
    replay_second_path = raw_path_by_label[replay_second_label]
    replay_second_raw = raw_by_label[replay_second_label]

    output = {
        "schema": SCHEMA,
        "generated_by": "tools/build_scene_composition_goldens.py",
        "layer_order": LAYER_ORDER,
        "captures": captures,
        "cross_capture_observations": {
            "hub_camera_move": build_hub_camera_observation(captures[0], captures[1]),
            "boneyard_camera_move": build_boneyard_camera_observation(captures[2], captures[3]),
            "same_seed_boneyard_replay": build_same_seed_observation(
                replay_first_path,
                replay_first_raw,
                replay_second_path,
                replay_second_raw,
            ),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(output, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


if __name__ == "__main__":
    main()
