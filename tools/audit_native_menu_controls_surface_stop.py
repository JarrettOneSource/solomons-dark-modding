#!/usr/bin/env python3
"""Seal the controls-tag/main-menu-surface promotion STOP."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from native_menu_landed_diagnosis_v25 import _signature


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} is not a JSON object")
    return value


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def receipt(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "sha256": file_sha256(path),
        "bytes": path.stat().st_size,
    }


def elements(layout: dict[str, Any], label: str) -> list[dict[str, Any]]:
    values = layout.get("elements")
    if not isinstance(values, list) or not values or not all(
        isinstance(value, dict) for value in values
    ):
        raise ValueError(f"{label} has no real element census")
    return values


def semantic_diff(
    left: list[dict[str, Any]], right: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], int]:
    left_counter = Counter(_signature(element) for element in left)
    right_counter = Counter(_signature(element) for element in right)
    residual = right_counter - left_counter
    by_signature: dict[bytes, list[dict[str, Any]]] = defaultdict(list)
    for element in right:
        by_signature[_signature(element)].append(element)
    witnesses: list[dict[str, Any]] = []
    for signature in sorted(residual):
        matching = by_signature[signature]
        witnesses.append(
            {
                "count": residual[signature],
                "semantic_sha256": hashlib.sha256(signature).hexdigest(),
                "payload": json.loads(signature.decode("utf-8")),
                "captured_ids": [
                    element.get("id") for element in matching[: residual[signature]]
                ],
                "captured_draw_orders": [
                    element.get("draw_order")
                    for element in matching[: residual[signature]]
                ],
            }
        )
    common_count = sum((left_counter & right_counter).values())
    return witnesses, common_count


def settled_identity(trace: dict[str, Any], label: str) -> dict[str, Any]:
    samples = trace.get("settled_window_samples")
    header = trace.get("header")
    if (
        not isinstance(samples, list)
        or len(samples) < 40
        or not isinstance(header, dict)
    ):
        raise ValueError(f"{label} trace has no qualifying settled window")
    surfaces: set[Any] = set()
    semantic_generations: set[Any] = set()
    tagged_screens: set[Any] = set()
    layout_generations: set[Any] = set()
    censuses: set[int] = set()
    for sample in samples:
        if not isinstance(sample, dict) or not isinstance(sample.get("payload"), dict):
            raise ValueError(f"{label} trace contains a malformed settled sample")
        payload = sample["payload"]
        surfaces.add(sample.get("semantic_surface"))
        semantic_generations.add(sample.get("semantic_generation"))
        tagged_screens.add(payload.get("screen_id"))
        layout_generations.add(payload.get("generation"))
        censuses.add(len(elements(payload, f"{label} settled payload")))
    return {
        "instance": header.get("instance"),
        "process_id": header.get("process_id"),
        "sample_count": len(samples),
        "stable_span_milliseconds": (
            samples[-1].get("elapsed_milliseconds", 0)
            - samples[0].get("elapsed_milliseconds", 0)
        ),
        "semantic_surfaces": sorted(surfaces),
        "semantic_generations": sorted(semantic_generations),
        "operator_tagged_screens": sorted(tagged_screens),
        "layout_generations": sorted(layout_generations),
        "element_censuses": sorted(censuses),
        "capture_method": header.get("capture_method"),
    }


def build_audit(
    landed_fixture_path: Path,
    candidate_fixture_path: Path,
    primary_trace_path: Path,
    confirmation_trace_path: Path,
    candidate_aggregate_path: Path,
    promoter_log_path: Path,
) -> dict[str, Any]:
    landed_fixture = read_object(landed_fixture_path)
    candidate_fixture = read_object(candidate_fixture_path)
    primary_trace = read_object(primary_trace_path)
    confirmation_trace = read_object(confirmation_trace_path)
    aggregate = read_object(candidate_aggregate_path)
    landed = landed_fixture.get("layout")
    candidate = candidate_fixture.get("layout")
    if not isinstance(landed, dict) or not isinstance(candidate, dict):
        raise ValueError("controls audit has no landed/candidate layouts")
    primary_identity = settled_identity(primary_trace, "primary")
    confirmation_identity = settled_identity(confirmation_trace, "confirmation")
    for identity in (primary_identity, confirmation_identity):
        if identity["semantic_surfaces"] != ["main_menu"]:
            raise ValueError("controls STOP no longer reproduces the main_menu surface")
        if identity["operator_tagged_screens"] != ["controls"]:
            raise ValueError("controls STOP no longer reproduces the controls tag")
    if (
        primary_identity["instance"],
        primary_identity["process_id"],
    ) == (
        confirmation_identity["instance"],
        confirmation_identity["process_id"],
    ):
        raise ValueError("controls STOP did not reach two fresh instance identities")

    landed_elements = elements(landed, "landed controls")
    candidate_elements = elements(candidate, "candidate controls core")
    missing_from_landed, common_count = semantic_diff(
        landed_elements, candidate_elements
    )
    landed_only, reverse_common = semantic_diff(candidate_elements, landed_elements)
    if common_count != reverse_common or not missing_from_landed or not landed_only:
        raise ValueError("controls STOP semantic diff is absent or asymmetric")
    edges = aggregate.get("navigation_graph", {}).get("edges")
    if not isinstance(edges, list) or not edges:
        raise ValueError("controls STOP navigation audit reached no edges")
    endpoints: list[dict[str, Any]] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        for side in ("before", "after"):
            endpoint = edge.get(side)
            if isinstance(endpoint, dict) and endpoint.get("layout_id") == "controls":
                endpoints.append(
                    {
                        "edge_id": edge.get("id"),
                        "side": side,
                        "trigger": edge.get("trigger"),
                        "semantic_surface": endpoint.get("semantic_surface"),
                        "tagged_screen": endpoint.get("tagged_screen"),
                        "layout_generation": endpoint.get("layout_generation"),
                        "element_count": endpoint.get("element_count"),
                        "frame_sha256": endpoint.get("frame_sha256"),
                    }
                )
    if len(endpoints) != 2 or {entry["side"] for entry in endpoints} != {
        "before",
        "after",
    }:
        raise ValueError("controls STOP did not reach both navigation endpoint roles")
    promoter_text = promoter_log_path.read_text(encoding="utf-8", errors="replace")
    expected_stop = (
        "STOP: standalone controls: landed-vs-settled structural core mismatch: "
        "reproduced core member 'quit' is missing from the landed layout"
    )
    if expected_stop not in promoter_text:
        raise ValueError("promoter transcript does not carry the named controls STOP")
    return {
        "schema": "solomon-dark-native-menu-controls-surface-stop-audit-v1",
        "finding": "controls_tag_settled_on_main_menu_surface",
        "status": "QUESTION",
        "promoter_stop": expected_stop,
        "inputs": {
            "landed_fixture": receipt(landed_fixture_path),
            "candidate_fixture": receipt(candidate_fixture_path),
            "primary_trace": receipt(primary_trace_path),
            "confirmation_trace": receipt(confirmation_trace_path),
            "candidate_aggregate": receipt(candidate_aggregate_path),
            "promoter_transcript": receipt(promoter_log_path),
        },
        "landed": {
            "screen_id": landed.get("screen_id"),
            "generation": landed.get("generation"),
            "element_count": len(landed_elements),
            "capture_method": landed.get("capture_method"),
        },
        "candidate": {
            "screen_id": candidate.get("screen_id"),
            "generation": candidate.get("generation"),
            "structural_core_element_count": len(candidate_elements),
            "structural_core_sha256": candidate.get("structural_core_sha256"),
            "capture_method": candidate.get("capture_method"),
        },
        "paired_settled_identity": {
            "primary": primary_identity,
            "confirmation": confirmation_identity,
            "cross_instance_surface_and_tag_equal": (
                primary_identity["semantic_surfaces"]
                == confirmation_identity["semantic_surfaces"]
                and primary_identity["operator_tagged_screens"]
                == confirmation_identity["operator_tagged_screens"]
            ),
            "fresh_instance_identities": True,
        },
        "semantic_core_diff": {
            "common_semantic_member_count": common_count,
            "candidate_members_missing_from_landed_count": sum(
                entry["count"] for entry in missing_from_landed
            ),
            "candidate_members_missing_from_landed": missing_from_landed,
            "landed_members_missing_from_candidate_count": sum(
                entry["count"] for entry in landed_only
            ),
            "landed_members_missing_from_candidate": landed_only,
        },
        "navigation_endpoints": endpoints,
        "consequence": (
            "the candidate is a stable main-menu art/text remnant carrying an "
            "operator-supplied controls tag, not a settled controls layout; "
            "promoting it would replace controls semantics and could change "
            "controller traversal"
        ),
        "decision_required": (
            "recapture controls from a classifier-agreed controls surface in two "
            "fresh instances; do not authorize this mismatched candidate"
        ),
    }


def write_object(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--landed-fixture", type=Path, required=True)
    parser.add_argument("--candidate-fixture", type=Path, required=True)
    parser.add_argument("--primary-trace", type=Path, required=True)
    parser.add_argument("--confirmation-trace", type=Path, required=True)
    parser.add_argument("--candidate-aggregate", type=Path, required=True)
    parser.add_argument("--promoter-log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    audit = build_audit(
        args.landed_fixture.resolve(),
        args.candidate_fixture.resolve(),
        args.primary_trace.resolve(),
        args.confirmation_trace.resolve(),
        args.candidate_aggregate.resolve(),
        args.promoter_log.resolve(),
    )
    write_object(args.output.resolve(), audit)
    print(json.dumps(audit, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
