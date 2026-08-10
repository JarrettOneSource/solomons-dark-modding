#!/usr/bin/env python3
"""Derive v2.19 exact core proofs for every v2.18 pair disagreement."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from native_menu_generation_v219 import (
    NativeMenuGenerationV219Error,
    derive_pair_core_equality,
)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{path} is not a JSON object")
    return value


def file_receipt(path: Path, *, root: Path | None = None) -> dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    result: dict[str, Any] = {
        "sha256": digest.hexdigest(),
        "bytes": path.stat().st_size,
    }
    if root is not None:
        result["path"] = path.resolve().relative_to(root.resolve()).as_posix()
    return result


def edge_map(recording: dict[str, Any], label: str) -> dict[str, dict[str, Any]]:
    edges = recording.get("edges")
    if not isinstance(edges, list) or len(edges) != 39:
        raise RuntimeError(f"{label} did not reach the exact 39-edge census")
    result: dict[str, dict[str, Any]] = {}
    for edge in edges:
        edge_id = edge.get("id") if isinstance(edge, dict) else None
        if not isinstance(edge_id, str) or not edge_id or edge_id in result:
            raise RuntimeError(f"{label} has an absent or ambiguous edge id")
        result[edge_id] = edge
    if "control_scheme_picker_to_create" not in result:
        raise RuntimeError(f"{label} missed the picker witness edge")
    return result


def fixture_path(candidate_root: Path, layout_id: str) -> Path:
    candidates = [
        path
        for path in (
            candidate_root / "menu-layouts" / f"{layout_id}.json",
            candidate_root
            / "menu-transition-layouts"
            / f"{layout_id}.json",
        )
        if path.is_file()
    ]
    if len(candidates) != 1:
        raise RuntimeError(
            f"v2.19 fixture lookup for '{layout_id}' is absent or ambiguous"
        )
    return candidates[0]


def trace_from_stop_receipt(
    candidate_root: Path, receipt: dict[str, Any], label: str
) -> tuple[Path, dict[str, Any]]:
    relative = receipt.get("trace", {}).get("path")
    if not isinstance(relative, str) or not relative:
        raise RuntimeError(f"{label} stop receipt has no exact trace path")
    path = (candidate_root / relative).resolve()
    if not path.is_relative_to(candidate_root.resolve()) or not path.is_file():
        raise RuntimeError(f"{label} trace is absent or escapes the candidate root")
    measured = file_receipt(path)
    expected = receipt["trace"]
    if (
        measured["sha256"] != expected.get("sha256")
        or measured["bytes"] != expected.get("bytes")
    ):
        raise RuntimeError(f"{label} trace receipt is false")
    return path, read_json(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--v218-stop-audit", type=Path, required=True)
    parser.add_argument("--resolved-navigation", type=Path, required=True)
    parser.add_argument("--confirmation-navigation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    evidence_root = args.evidence_root.resolve()
    candidate_root = args.candidate_root.resolve()
    stop_path = args.v218_stop_audit.resolve()
    resolved_path = args.resolved_navigation.resolve()
    confirmation_path = args.confirmation_navigation.resolve()
    output = args.output.resolve()
    stop = read_json(stop_path)
    resolved = read_json(resolved_path)
    confirmation = read_json(confirmation_path)
    resolved_edges = edge_map(resolved, "v2.19 resolved navigation")
    confirmation_edges = edge_map(
        confirmation, "v2.19 confirmation navigation"
    )
    if set(resolved_edges) != set(confirmation_edges):
        raise RuntimeError("v2.19 paired navigation edge censuses differ")

    standalone_mismatches = stop.get("standalone_census", {}).get("mismatches")
    endpoint_mismatches = stop.get("navigation_census", {}).get("mismatches")
    if (
        not isinstance(standalone_mismatches, list)
        or len(standalone_mismatches) != 10
        or not isinstance(endpoint_mismatches, list)
        or len(endpoint_mismatches) != 24
    ):
        raise RuntimeError(
            "v2.19 audit did not inherit the exact 10-standalone/24-endpoint STOP census"
        )

    standalone_results: list[dict[str, Any]] = []
    for mismatch in standalone_mismatches:
        layout_id = mismatch.get("layout_id")
        if not isinstance(layout_id, str):
            raise RuntimeError("v2.19 standalone mismatch has no layout identity")
        path = fixture_path(candidate_root, layout_id)
        fixture = read_json(path)
        layout = fixture.get("layout")
        if not isinstance(layout, dict):
            raise RuntimeError(f"v2.19 fixture '{layout_id}' has no layout")
        primary_path, primary_trace = trace_from_stop_receipt(
            candidate_root, mismatch.get("primary", {}), f"{layout_id} primary"
        )
        confirmation_trace_path, confirmation_trace = trace_from_stop_receipt(
            candidate_root,
            mismatch.get("confirmation", {}),
            f"{layout_id} confirmation",
        )
        bound_endpoints = sorted(
            f"{edge_id}.{side}"
            for edge_id, edge in resolved_edges.items()
            for side in ("before", "after")
            if isinstance(edge.get(side), dict)
            and edge[side].get("layout_id") == layout_id
        )
        try:
            proof = derive_pair_core_equality(
                primary_trace.get("settled_window_samples", []),
                confirmation_trace.get("settled_window_samples", []),
                layout,
                label=f"standalone {layout_id}",
                bound_endpoints=bound_endpoints,
                bound_endpoint_census_complete=True,
            )
        except NativeMenuGenerationV219Error as error:
            raise RuntimeError(
                f"STOP: standalone {layout_id} failed v2.19 core proof: {error}"
            ) from error
        standalone_results.append(
            {
                "layout_id": layout_id,
                "fixture": file_receipt(path, root=candidate_root),
                "primary_trace": file_receipt(
                    primary_path, root=candidate_root
                ),
                "confirmation_trace": file_receipt(
                    confirmation_trace_path, root=candidate_root
                ),
                "proof": proof,
                "all_other_member_system_fields_equal": True,
                "verdict": "pass",
            }
        )

    endpoint_results: list[dict[str, Any]] = []
    for mismatch in endpoint_mismatches:
        edge_id = mismatch.get("edge_id")
        side = mismatch.get("side")
        if (
            not isinstance(edge_id, str)
            or side not in {"before", "after"}
            or edge_id not in resolved_edges
        ):
            raise RuntimeError("v2.19 endpoint mismatch has no exact identity")
        primary = resolved_edges[edge_id].get(side)
        second = confirmation_edges[edge_id].get(side)
        if not isinstance(primary, dict) or not isinstance(second, dict):
            raise RuntimeError(f"v2.19 endpoint {edge_id}.{side} is absent")
        layout = primary.get("layout")
        primary_trace = primary.get("settlement_trace")
        confirmation_trace = second.get("settlement_trace")
        if (
            not isinstance(layout, dict)
            or not isinstance(primary_trace, dict)
            or not isinstance(confirmation_trace, dict)
        ):
            raise RuntimeError(
                f"v2.19 endpoint {edge_id}.{side} lost layout/trace content"
            )
        try:
            proof = derive_pair_core_equality(
                primary_trace.get("settled_window_samples", []),
                confirmation_trace.get("settled_window_samples", []),
                layout,
                label=f"edge {edge_id}.{side}",
                bound_endpoints=[f"{edge_id}.{side}"],
                bound_endpoint_census_complete=True,
            )
        except NativeMenuGenerationV219Error as error:
            raise RuntimeError(
                f"STOP: endpoint {edge_id}.{side} failed v2.19 core proof: {error}"
            ) from error
        endpoint_results.append(
            {
                "edge_id": edge_id,
                "side": side,
                "layout_id": primary.get("layout_id"),
                "primary_trace": {
                    "recording": file_receipt(
                        resolved_path, root=evidence_root
                    ),
                    "json_pointer": f"/edges/{edge_id}/{side}/settlement_trace",
                },
                "confirmation_trace": {
                    "recording": file_receipt(
                        confirmation_path, root=evidence_root
                    ),
                    "json_pointer": f"/edges/{edge_id}/{side}/settlement_trace",
                },
                "proof": proof,
                "all_other_member_system_fields_equal": True,
                "verdict": "pass",
            }
        )

    skill = [
        result
        for result in standalone_results
        if result["layout_id"] == "skill-picker"
    ]
    if len(skill) != 1:
        raise RuntimeError("v2.19 audit missed the v2.14 Skill Picker witness")
    result = {
        "schema": "solomon-dark-native-menu-generation-core-audit-v219",
        "settlement_spec": "2.19",
        "source_v218_stop_audit": file_receipt(stop_path, root=evidence_root),
        "resolved_navigation": file_receipt(
            resolved_path, root=evidence_root
        ),
        "confirmation_navigation": file_receipt(
            confirmation_path, root=evidence_root
        ),
        "standalone_pair_count": len(standalone_results),
        "navigation_endpoint_pair_count": len(endpoint_results),
        "pair_count": len(standalone_results) + len(endpoint_results),
        "pass_count": sum(
            value["verdict"] == "pass"
            for value in [*standalone_results, *endpoint_results]
        ),
        "fail_count": 0,
        "all_pairs_core_equal": True,
        "all_pairs_zero_residual": True,
        "standalone_pairs": standalone_results,
        "navigation_endpoint_pairs": endpoint_results,
        "skill_picker_v214_disposition": {
            "layout_id": "skill-picker",
            "primary_generation": skill[0]["proof"]["primary"]["generation"],
            "confirmation_generation": skill[0]["proof"]["confirmation"][
                "generation"
            ],
            "core_equal": skill[0]["proof"]["core_equal"],
            "zero_residual": skill[0]["proof"]["zero_residual"],
            "promotion": "stands_under_v2.19_without_recapture",
        },
        "generation_semantics": (
            "session-cumulative instance-timing-sensitive layout-rebuild counter; "
            "recorded per instance, excluded from representation only after exact core proof"
        ),
        "candidate_applied": False,
    }
    if result["pair_count"] != 34 or result["pass_count"] != 34:
        raise RuntimeError("v2.19 core audit did not prove all 34 named pairs")
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
