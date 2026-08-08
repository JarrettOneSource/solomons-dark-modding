#!/usr/bin/env python3
"""Seal the Controls structural-core STOP reached after v2.10 title diagnosis."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from native_menu_landed_diagnosis_v25 import (
    LandedDiagnosisError,
    _diagnose_layout_identity_v210,
    _signature,
    diagnose_landed_layout,
)
from promote_native_menu_recapture import (
    read_json,
    validate_settlement_fixture_v25,
)


EXPECTED_STOP = (
    "landed-vs-settled structural core mismatch: reproduced core member "
    "'Wizard Controls' is missing from the landed layout"
)
EXPECTED_NEXT_STOP = (
    "landed-vs-settled structural core mismatch: reproduced core member "
    "'MOVE UP' is missing from the landed layout"
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def receipt(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    return {
        "path": str(resolved),
        "sha256": file_sha256(resolved),
        "bytes": resolved.stat().st_size,
    }


def elements(layout: dict[str, Any], label: str) -> list[dict[str, Any]]:
    values = layout.get("elements")
    if not isinstance(values, list) or not values or not all(
        isinstance(value, dict) for value in values
    ):
        raise ValueError(f"{label} has no unambiguous element census")
    return values


def residual_witnesses(
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
        payload = json.loads(signature.decode("utf-8"))
        count = residual[signature]
        matching = by_signature[signature][:count]
        witnesses.append(
            {
                "count": count,
                "semantic_sha256": hashlib.sha256(signature).hexdigest(),
                "payload": payload,
                "captured_ids": [element.get("id") for element in matching],
                "captured_draw_orders": [
                    element.get("draw_order") for element in matching
                ],
            }
        )
    return witnesses, sum((left_counter & right_counter).values())


def settled_identity(
    samples: list[dict[str, Any]], header: dict[str, Any], label: str
) -> dict[str, Any]:
    if len(samples) < 40:
        raise ValueError(f"{label} has fewer than 40 settled samples")
    surfaces: set[Any] = set()
    tagged_screens: set[Any] = set()
    screen_titles: set[Any] = set()
    layout_generations: set[Any] = set()
    semantic_generations: set[Any] = set()
    censuses: set[int] = set()
    for sample in samples:
        payload = sample.get("payload")
        if not isinstance(payload, dict):
            raise ValueError(f"{label} contains a sample without a payload")
        surfaces.add(sample.get("semantic_surface"))
        semantic_generations.add(sample.get("semantic_generation"))
        tagged_screens.add(payload.get("screen_id"))
        screen_titles.add(payload.get("screen_title"))
        layout_generations.add(payload.get("generation"))
        censuses.add(len(elements(payload, f"{label} sample")))
    if (
        surfaces != {"controls"}
        or tagged_screens != {"controls"}
        or screen_titles != {"Wizard Controls"}
        or len(semantic_generations) != 1
        or len(layout_generations) != 1
    ):
        raise ValueError(
            f"{label} no longer reproduces one classifier-agreed Controls state"
        )
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
        "screen_titles": sorted(screen_titles),
        "layout_generations": sorted(layout_generations),
        "element_censuses": sorted(censuses),
    }


def run_diagnosis(
    landed: dict[str, Any],
    settled: dict[str, Any],
    record: dict[str, Any],
    overlay: dict[str, Any],
    order_contract: dict[str, Any],
    title_contract: dict[str, Any],
) -> str:
    try:
        diagnose_landed_layout(
            "controls",
            landed,
            settled,
            record["primary_trace"],
            record["confirmation_trace"],
            overlay,
            order_contract,
            title_contract,
        )
    except LandedDiagnosisError as error:
        return str(error)
    raise ValueError("Controls post-v2.10 diagnosis unexpectedly passed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--navigation-recording", type=Path, required=True)
    parser.add_argument("--promoter-log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = args.repo_root.resolve()
    candidate_root = args.candidate_root.resolve()
    evidence_root = args.evidence_root.resolve()
    candidate_path = candidate_root / "menu-layouts/controls.json"
    landed_path = repo / "tests/fixtures/webgame/menu-layouts/controls.json"
    candidate = read_json(candidate_path)
    landed_fixture = read_json(landed_path)
    record = validate_settlement_fixture_v25(
        repo, evidence_root, candidate_path, candidate
    )
    landed = landed_fixture.get("layout")
    settled = record.get("layout")
    if not isinstance(landed, dict) or not isinstance(settled, dict):
        raise ValueError("Controls post-v2.10 audit has no compared layouts")
    overlay_path = candidate_root / "menu-overlay-reference.json"
    overlay = read_json(overlay_path)
    order_contract_path = (
        repo / "tests/fixtures/webgame/native-menu-beta-notice-order-v29.json"
    )
    title_contract_path = (
        repo / "tests/fixtures/webgame/native-menu-controls-title-v210.json"
    )
    order_contract = read_json(order_contract_path)
    title_contract = read_json(title_contract_path)

    identity_correction = _diagnose_layout_identity_v210(
        "controls", landed, settled, title_contract
    )
    if not isinstance(identity_correction, dict):
        raise ValueError("the exact v2.10 top-level title correction did not apply")
    promoter_stop = run_diagnosis(
        landed,
        settled,
        record,
        overlay,
        order_contract,
        title_contract,
    )
    if promoter_stop != EXPECTED_STOP:
        raise ValueError(
            "post-v2.10 diagnosis did not reach its named structural STOP: "
            f"{promoter_stop}"
        )
    without_title_member = copy.deepcopy(settled)
    original_count = len(elements(without_title_member, "settled Controls"))
    without_title_member["elements"] = [
        element
        for element in without_title_member["elements"]
        if element.get("text") != "Wizard Controls"
    ]
    if len(without_title_member["elements"]) != original_count - 1:
        raise ValueError(
            "Controls post-v2.10 audit did not remove exactly one title member"
        )
    next_stop = run_diagnosis(
        landed,
        without_title_member,
        record,
        overlay,
        order_contract,
        title_contract,
    )
    if next_stop != EXPECTED_NEXT_STOP:
        raise ValueError(
            "title-member removal did not expose the next structural STOP: "
            f"{next_stop}"
        )

    landed_elements = elements(landed, "landed Controls")
    settled_elements = elements(settled, "settled Controls")
    settled_only, common_count = residual_witnesses(
        landed_elements, settled_elements
    )
    landed_only, reverse_common = residual_witnesses(
        settled_elements, landed_elements
    )
    if common_count != reverse_common or not settled_only or not landed_only:
        raise ValueError("Controls structural residual is absent or asymmetric")
    settled_only_count = sum(entry["count"] for entry in settled_only)
    landed_only_count = sum(entry["count"] for entry in landed_only)
    if (
        common_count + landed_only_count != len(landed_elements)
        or common_count + settled_only_count != len(settled_elements)
    ):
        raise ValueError("Controls semantic-multiset arithmetic does not close")

    primary_header = record["header"]
    confirmation_header = record["confirmation_trace"].get("header")
    if not isinstance(primary_header, dict) or not isinstance(
        confirmation_header, dict
    ):
        raise ValueError("Controls paired captures have no machine headers")
    primary_identity = settled_identity(
        record["primary_samples"], primary_header, "primary Controls"
    )
    confirmation_identity = settled_identity(
        record["confirmation_samples"],
        confirmation_header,
        "confirmation Controls",
    )
    if (
        primary_identity["instance"],
        primary_identity["process_id"],
    ) == (
        confirmation_identity["instance"],
        confirmation_identity["process_id"],
    ):
        raise ValueError("Controls confirmation reused the primary instance identity")

    promoter_text = args.promoter_log.read_text(
        encoding="utf-8", errors="replace"
    )
    expected_promoter_line = f"STOP: standalone controls: {EXPECTED_STOP}"
    if expected_promoter_line not in promoter_text:
        raise ValueError("full promoter transcript lacks the named structural STOP")

    navigation = read_json(args.navigation_recording)
    edges = navigation.get("navigation_graph", {}).get("edges")
    if not isinstance(edges, list) or not edges:
        raise ValueError("Controls post-v2.10 audit reached no navigation graph")
    controls_endpoints: list[dict[str, Any]] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        for side in ("before", "after"):
            endpoint = edge.get(side)
            if isinstance(endpoint, dict) and endpoint.get("layout_id") == "controls":
                controls_endpoints.append(
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
    if len(controls_endpoints) != 2:
        raise ValueError(
            "Controls post-v2.10 audit did not reach exactly two graph endpoints"
        )

    audit = {
        "schema": "solomon-dark-native-menu-controls-post-v210-stop-audit-v1",
        "status": "QUESTION",
        "finding": "valid_settled_controls_structural_core_not_covered_by_landed_diagnosis",
        "v210_top_level_title_correction": identity_correction,
        "promoter_stop": expected_promoter_line,
        "next_stop_after_removing_title_text_member": EXPECTED_NEXT_STOP,
        "inputs": {
            "landed_fixture": receipt(landed_path),
            "candidate_fixture": receipt(candidate_path),
            "primary_trace": receipt(record["primary_trace_path"]),
            "confirmation_trace": receipt(record["confirmation_trace_path"]),
            "overlay_reference": receipt(overlay_path),
            "order_contract": receipt(order_contract_path),
            "title_contract": receipt(title_contract_path),
            "navigation_recording": receipt(args.navigation_recording),
            "promoter_transcript": receipt(args.promoter_log),
        },
        "paired_settled_identity": {
            "primary": primary_identity,
            "confirmation": confirmation_identity,
            "fresh_instance_identities": True,
            "classifier_and_tag_agree": True,
        },
        "semantic_core_diff": {
            "landed_element_count": len(landed_elements),
            "settled_element_count": len(settled_elements),
            "common_semantic_member_count": common_count,
            "settled_members_missing_from_landed_count": settled_only_count,
            "settled_members_missing_from_landed": settled_only,
            "landed_members_missing_from_settled_count": landed_only_count,
            "landed_members_missing_from_settled": landed_only,
            "multiset_arithmetic_closed": True,
        },
        "navigation_endpoints": controls_endpoints,
        "guardrail": (
            "v2.10 remains limited to layout.screen_title; no settled-only "
            "structural member or whole-layout correction was inferred"
        ),
        "decision_required": (
            "authorize or reject an exact Controls-only landed-vs-settled "
            "structural correction for the classifier-agreed paired capture"
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(args.output.name + ".tmp")
    temporary.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, args.output)
    print(json.dumps(audit, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
