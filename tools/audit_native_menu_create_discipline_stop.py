#!/usr/bin/env python3
"""Audit the first post-v2.11 Create-discipline promotion STOP."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from native_menu_landed_diagnosis_v25 import (
    _population_evidence,
    _v29_beta_notice_order_projection,
    match_ambient_members,
    match_overlay_members,
    match_population_members,
)
from promote_native_menu_recapture import file_receipt, read_json


STOP_MESSAGE = (
    "STOP: standalone create-discipline: overlay correction generation "
    "difference lacks both population-trace witnesses"
)


def unique_landed_layout(aggregate: dict[str, Any]) -> dict[str, Any]:
    matches = [
        entry.get("layout")
        for entry in aggregate.get("layouts", [])
        if isinstance(entry, dict)
        and Path(str(entry.get("fixture", ""))).stem == "create-discipline"
    ]
    if len(matches) != 1 or not isinstance(matches[0], dict):
        raise ValueError(
            "create-discipline STOP audit did not reach one landed layout"
        )
    return matches[0]


def endpoint_population_witnesses(
    navigation_path: Path, capture_label: str
) -> list[dict[str, Any]]:
    navigation = read_json(navigation_path)
    edges = navigation.get("edges")
    if not isinstance(edges, list) or not edges:
        raise ValueError(
            f"create-discipline STOP audit reached no {capture_label} edges"
        )
    witnesses: list[dict[str, Any]] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        header = edge.get("header")
        for side in ("before", "after"):
            endpoint = edge.get(side)
            trace = endpoint.get("settlement_trace") if isinstance(endpoint, dict) else None
            if not isinstance(trace, dict):
                continue
            samples = trace.get("settled_window_samples")
            if not isinstance(samples, list) or not samples:
                continue
            payload = samples[0].get("payload")
            if not isinstance(payload, dict) or payload.get("screen_id") != (
                "create_discipline"
            ):
                continue
            evidence = _population_evidence(
                trace, f"{capture_label} {edge.get('id')} {side}"
            )
            witnesses.append(
                {
                    "capture": capture_label,
                    "edge_id": edge.get("id"),
                    "side": side,
                    "instance": header.get("instance")
                    if isinstance(header, dict)
                    else None,
                    "process_id": header.get("process_id")
                    if isinstance(header, dict)
                    else None,
                    "generation_trace": evidence["generation_trace"],
                    "element_count_trace": evidence["element_count_trace"],
                    "phase_observations": evidence["phase_observations"],
                    "settled_sample_count": evidence["settled_sample_count"],
                }
            )
    if not witnesses:
        raise ValueError(
            f"create-discipline STOP audit reached no {capture_label} endpoint witness"
        )
    return witnesses


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
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--primary-navigation", type=Path, required=True)
    parser.add_argument("--confirmation-navigation", type=Path, required=True)
    parser.add_argument("--promoter-log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = args.repo_root.resolve()
    candidate_root = args.candidate_root.resolve()
    landed_path = repo / "tests/fixtures/webgame/menu-goldens.json"
    candidate_path = candidate_root / "menu-layouts/create-discipline.json"
    primary_trace_path = (
        candidate_root
        / "menu-settlement-traces/create-discipline.settlement.json"
    )
    confirmation_trace_path = (
        candidate_root
        / "menu-animation-confirmations/create-discipline.confirmation.json"
    )
    overlay_path = candidate_root / "menu-overlay-reference.json"
    order_path = (
        repo
        / "tests/fixtures/webgame/native-menu-beta-notice-order-v29.json"
    )
    landed = unique_landed_layout(read_json(landed_path))
    candidate_fixture = read_json(candidate_path)
    settled = candidate_fixture["layout"]
    standalone_settlement = candidate_fixture["header"]["settlement"]
    primary_trace = read_json(primary_trace_path)
    confirmation_trace = read_json(confirmation_trace_path)
    overlay_reference = read_json(overlay_path)
    order_contract = read_json(order_path)

    projected, residual, order_correction = _v29_beta_notice_order_projection(
        landed, settled, overlay_reference, order_contract
    )
    lifecycle, animation, unmatched = match_ambient_members(residual, settled)
    population, after_population, population_proof = match_population_members(
        unmatched,
        landed.get("generation"),
        settled.get("generation"),
        primary_trace,
        confirmation_trace,
    )
    overlay, residual_after_overlay = match_overlay_members(
        after_population, overlay_reference
    )
    if order_correction is not None:
        raise ValueError(
            "create-discipline STOP audit unexpectedly used beta-notice order correction"
        )
    if not overlay or residual_after_overlay:
        raise ValueError(
            "create-discipline STOP audit did not reproduce exact overlay subtraction"
        )
    if population_proof.get("generation_difference_witnessed_in_both_traces"):
        raise ValueError(
            "create-discipline STOP audit unexpectedly found both generation witnesses"
        )

    navigation_witnesses = [
        *endpoint_population_witnesses(
            args.primary_navigation.resolve(), "primary"
        ),
        *endpoint_population_witnesses(
            args.confirmation_navigation.resolve(), "confirmation"
        ),
    ]
    result = {
        "schema": "solomon-dark-native-menu-create-discipline-stop-audit-v1",
        "status": "QUESTION",
        "finding": (
            "exact_overlay_subtraction_without_required_two-trace_landed_generation_witness"
        ),
        "named_stop": STOP_MESSAGE,
        "inputs": {
            "landed_aggregate": file_receipt(landed_path),
            "candidate_fixture": file_receipt(candidate_path),
            "primary_standalone_trace": file_receipt(primary_trace_path),
            "confirmation_standalone_trace": file_receipt(
                confirmation_trace_path
            ),
            "overlay_reference": file_receipt(overlay_path),
            "order_contract": file_receipt(order_path),
            "primary_navigation": file_receipt(
                args.primary_navigation.resolve()
            ),
            "confirmation_navigation": file_receipt(
                args.confirmation_navigation.resolve()
            ),
            "promoter_log": file_receipt(args.promoter_log.resolve()),
        },
        "comparison": {
            "landed_generation": landed.get("generation"),
            "landed_element_count": len(landed["elements"]),
            "settled_generation": settled.get("generation"),
            "standalone_settled_minimum_element_count": standalone_settlement.get(
                "minimum_element_count"
            ),
            "standalone_settled_peak_element_count": standalone_settlement.get(
                "peak_element_count"
            ),
            "resolved_campaign_peak_element_count": settled.get(
                "peak_element_count"
            ),
            "settled_structural_core_element_count": len(settled["elements"]),
            "projected_core_element_count": len(projected),
            "landed_residual_count": len(residual),
            "ambient_lifecycle_disposition_count": len(lifecycle),
            "animated_geometry_disposition_count": len(animation),
            "population_disposition_count": len(population),
            "overlay_disposition_count": len(overlay),
            "unexplained_residual_count": len(residual_after_overlay),
        },
        "standalone_population_proof": population_proof,
        "navigation_endpoint_population_witnesses": navigation_witnesses,
        "overlay_members": [
            {
                "element_id": value["element_id"],
                "art_id": value.get("art_id"),
                "semantic_payload": value["semantic_payload"],
            }
            for value in overlay
        ],
        "guardrail": (
            "v2.4 still requires a generation difference to be witnessed in "
            "both population traces; exact overlay subtraction alone is insufficient"
        ),
        "decision_required": (
            "ATC must either identify qualifying already-recorded paired "
            "generation witnesses or authorize a bounded rule; promotion remains stopped"
        ),
    }
    write_object(args.output.resolve(), result)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
