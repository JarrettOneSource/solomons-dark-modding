#!/usr/bin/env python3
"""Derive the campaign-wide Settlement v2.18 paired-generation STOP census."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from native_menu_generation_v218 import (
    PAIRED_GENERATION_STOP,
    measure_generation_window,
)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{path} is not a JSON object")
    return value


def file_receipt(path: Path, *, root: Path | None = None) -> dict[str, Any]:
    data = path.read_bytes()
    result: dict[str, Any] = {
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }
    if root is not None:
        result["path"] = path.resolve().relative_to(root.resolve()).as_posix()
    return result


def resolve_candidate_receipt(
    candidate_root: Path,
    fixture_path: Path,
    receipt: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    filename = receipt.get("evidence_filename")
    if not isinstance(filename, str) or Path(filename).name != filename:
        raise RuntimeError(f"{fixture_path} has no unambiguous evidence filename")
    candidates = {
        path.resolve()
        for path in (
            fixture_path.parent / filename,
            candidate_root / filename,
            candidate_root / "menu-settlement-traces" / filename,
            candidate_root / "menu-animation-confirmations" / filename,
        )
        if path.is_file()
    }
    if len(candidates) != 1:
        raise RuntimeError(
            f"{fixture_path} receipt lookup is absent or ambiguous: "
            f"{sorted(str(path) for path in candidates)}"
        )
    path = candidates.pop()
    measured = file_receipt(path)
    if (
        measured["sha256"] != receipt.get("sha256")
        or measured["bytes"] != receipt.get("bytes")
    ):
        raise RuntimeError(f"{fixture_path} carries a false evidence receipt")
    return path, measured


def trace_identity(trace: dict[str, Any]) -> dict[str, Any]:
    header = trace.get("header")
    if not isinstance(header, dict):
        raise RuntimeError("settlement trace has no capture header")
    profile = header.get("profile_state")
    source = header.get("source")
    if not isinstance(profile, dict) or not isinstance(source, dict):
        raise RuntimeError("settlement trace lost profile/source provenance")
    return {
        "instance": header.get("instance"),
        "process_id": header.get("process_id"),
        "baseline_id": profile.get("baseline_id"),
        "profile_state_identity_sha256": profile.get(
            "profile_state_identity_sha256"
        ),
        "base_commit_sha": source.get("base_commit_sha"),
        "source_tree_sha": source.get("source_tree_sha"),
        "game_executable_sha256": source.get("game_executable_sha256"),
        "loader_dll_sha256": source.get("loader_dll_sha256"),
    }


def standalone_census(candidate_root: Path) -> dict[str, Any]:
    fixture_paths = sorted(
        [
            *(candidate_root / "menu-layouts").glob("*.json"),
            *(candidate_root / "menu-transition-layouts").glob("*.json"),
        ]
    )
    if len(fixture_paths) != 30 or not any(
        path.name == "control-scheme-picker.json" for path in fixture_paths
    ):
        raise RuntimeError(
            "v2.18 standalone sweep did not reach 27 menus plus three Hub layouts"
        )
    mismatches: list[dict[str, Any]] = []
    matching: list[str] = []
    for fixture_path in fixture_paths:
        fixture = read_json(fixture_path)
        header = fixture.get("header")
        layout = fixture.get("layout")
        if not isinstance(header, dict) or not isinstance(layout, dict):
            raise RuntimeError(f"{fixture_path} is not a menu layout fixture")
        primary_receipt = header.get(
            "settlement_trace", header.get("raw_recording")
        )
        confirmation_receipt = header.get("animation_confirmation")
        if not isinstance(primary_receipt, dict) or not isinstance(
            confirmation_receipt, dict
        ):
            raise RuntimeError(f"{fixture_path} lost its paired trace receipts")
        primary_path, primary_file = resolve_candidate_receipt(
            candidate_root, fixture_path, primary_receipt
        )
        confirmation_path, confirmation_file = resolve_candidate_receipt(
            candidate_root, fixture_path, confirmation_receipt
        )
        primary_trace = read_json(primary_path)
        confirmation_trace = read_json(confirmation_path)
        primary = measure_generation_window(
            primary_trace.get("settled_window_samples", []),
            f"{fixture_path.stem} primary",
        )
        confirmation = measure_generation_window(
            confirmation_trace.get("settled_window_samples", []),
            f"{fixture_path.stem} confirmation",
        )
        if primary["generation"] == confirmation["generation"]:
            matching.append(fixture_path.stem)
            continue
        mismatches.append(
            {
                "layout_id": fixture_path.stem,
                "candidate_fixture": {
                    **file_receipt(fixture_path, root=candidate_root),
                    "recorded_generation": layout.get("generation"),
                },
                "primary": {
                    **primary,
                    **trace_identity(primary_trace),
                    "trace": {
                        **primary_file,
                        "path": primary_path.relative_to(candidate_root).as_posix(),
                    },
                },
                "confirmation": {
                    **confirmation,
                    **trace_identity(confirmation_trace),
                    "trace": {
                        **confirmation_file,
                        "path": confirmation_path.relative_to(
                            candidate_root
                        ).as_posix(),
                    },
                },
                "same_binding": fixture_path.stem,
                "same_profile_state_identity": (
                    trace_identity(primary_trace)[
                        "profile_state_identity_sha256"
                    ]
                    == trace_identity(confirmation_trace)[
                        "profile_state_identity_sha256"
                    ]
                ),
                "stop_reason": PAIRED_GENERATION_STOP,
            }
        )
    return {
        "examined_layout_count": len(fixture_paths),
        "matching_layout_count": len(matching),
        "matching_layout_ids": matching,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
    }


def edge_map(recording: dict[str, Any], label: str) -> dict[str, dict[str, Any]]:
    edges = recording.get("edges")
    if not isinstance(edges, list) or len(edges) != 39:
        raise RuntimeError(f"{label} does not contain the exact 39-edge census")
    result: dict[str, dict[str, Any]] = {}
    for edge in edges:
        edge_id = edge.get("id") if isinstance(edge, dict) else None
        if not isinstance(edge_id, str) or not edge_id or edge_id in result:
            raise RuntimeError(f"{label} contains an absent or ambiguous edge id")
        result[edge_id] = edge
    if "control_scheme_picker_to_create" not in result:
        raise RuntimeError(f"{label} missed the picker witness edge")
    return result


def navigation_census(
    primary_path: Path, confirmation_path: Path
) -> dict[str, Any]:
    primary = edge_map(read_json(primary_path), "primary navigation")
    confirmation = edge_map(read_json(confirmation_path), "confirmation navigation")
    if set(primary) != set(confirmation):
        raise RuntimeError("paired navigation edge censuses differ")
    mismatches: list[dict[str, Any]] = []
    matching_count = 0
    non_layout_endpoints: list[str] = []
    for edge_id in sorted(primary):
        for side in ("before", "after"):
            first = primary[edge_id].get(side)
            second = confirmation[edge_id].get(side)
            if not isinstance(first, dict) or not isinstance(second, dict):
                raise RuntimeError(f"edge {edge_id} {side} endpoint is absent")
            if first.get("layout_generation") is None:
                non_layout_endpoints.append(f"{edge_id}.{side}")
                continue
            first_trace = first.get("settlement_trace")
            second_trace = second.get("settlement_trace")
            if not isinstance(first_trace, dict) or not isinstance(second_trace, dict):
                raise RuntimeError(f"edge {edge_id} {side} trace is absent")
            first_window = measure_generation_window(
                first_trace.get("settled_window_samples", []),
                f"edge {edge_id} {side} primary",
            )
            second_window = measure_generation_window(
                second_trace.get("settled_window_samples", []),
                f"edge {edge_id} {side} confirmation",
            )
            if first_window["generation"] == second_window["generation"]:
                matching_count += 1
                continue
            mismatches.append(
                {
                    "edge_id": edge_id,
                    "side": side,
                    "primary": first_window,
                    "confirmation": second_window,
                    "primary_surface": first.get("semantic_surface"),
                    "confirmation_surface": second.get("semantic_surface"),
                    "stop_reason": PAIRED_GENERATION_STOP,
                }
            )
    return {
        "edge_count": len(primary),
        "layout_endpoint_count": 78 - len(non_layout_endpoints),
        "matching_layout_endpoint_count": matching_count,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "typed_nonlayout_endpoints": non_layout_endpoints,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--primary-navigation", type=Path, required=True)
    parser.add_argument("--confirmation-navigation", type=Path, required=True)
    parser.add_argument("--source-stop-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    candidate_root = args.candidate_root.resolve()
    output = args.output.resolve()
    source_stop_audit = args.source_stop_audit.resolve()
    standalone = standalone_census(candidate_root)
    navigation = navigation_census(
        args.primary_navigation.resolve(),
        args.confirmation_navigation.resolve(),
    )
    if standalone["mismatch_count"] == 0 or navigation["mismatch_count"] == 0:
        raise RuntimeError(
            "v2.18 STOP audit did not reproduce both standalone and navigation pair failures"
        )
    result = {
        "schema": "solomon-dark-native-menu-generation-pair-stop-v218",
        "settlement_spec": "2.18",
        "finding": "paired_same_route_generation_not_reproduced",
        "stop_reason": PAIRED_GENERATION_STOP,
        "source_v218_question_audit": {
            **file_receipt(source_stop_audit),
            "path": source_stop_audit.name,
        },
        "standalone_census": standalone,
        "navigation_census": navigation,
        "candidate_applied": False,
        "landed_picker_fixture": file_receipt(
            repo_root
            / "tests/fixtures/webgame/menu-layouts/control-scheme-picker.json"
        ),
        "float_rng_fixture": file_receipt(
            repo_root / "tests/fixtures/webgame/float-rng-goldens.json"
        ),
        "required_disposition": (
            "STOP; paired instances disagree on the named path-local generation "
            "field, so v2.18 forbids promotion and counter-shopping"
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, output)
    print(json.dumps({"output": str(output), **file_receipt(output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
