#!/usr/bin/env python3
"""Audit the first landed mismatch exposed after exact Item 1 supersession."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from native_menu_dark_cloud_item_row_supersession import (
    PUBLIC_LAYOUT_MEMBER_IDS,
    consume_exact_landed_residual,
    require_contract,
    semantic_sha256,
)
from native_menu_landed_diagnosis_v25 import (
    _overlay_counter,
    _population_evidence,
    _signature,
    canonical_bytes,
    match_ambient_members,
    match_overlay_members,
    match_population_members,
    project_structural_core,
    sha256_json,
)
from native_menu_overlay_v25 import overlay_draw_payload


SCHEMA = "solomon-dark-native-menu-dark-cloud-post-item-stop-audit-v1"
LAYOUTS = (
    "dark-cloud-browser",
    "dark-cloud-recent",
    "dark-cloud-online-levels",
    "dark-cloud-my-levels",
)


class AuditError(RuntimeError):
    """The post-supersession STOP no longer reproduces exactly."""


def read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise AuditError(f"cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise AuditError(f"{path} is not a JSON object")
    return value


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def receipt(path: Path, root: Path) -> dict[str, Any]:
    resolved = path.resolve()
    base = root.resolve()
    if not resolved.is_relative_to(base):
        raise AuditError(f"receipt target escapes root: {resolved}")
    return {
        "path": resolved.relative_to(base).as_posix(),
        "sha256": file_sha256(resolved),
        "bytes": resolved.stat().st_size,
    }


def write_object(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".menufix.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def pair_evidence(
    primary_trace: dict[str, Any], confirmation_trace: dict[str, Any]
) -> dict[str, Any]:
    primary = _population_evidence(primary_trace, "post-item primary")
    confirmation = _population_evidence(
        confirmation_trace, "post-item confirmation"
    )
    primary_header = primary_trace.get("header")
    confirmation_header = confirmation_trace.get("header")
    if not isinstance(primary_header, dict) or not isinstance(
        confirmation_header, dict
    ):
        raise AuditError("post-item trace pair has no capture identities")
    primary_identity = (
        primary_header.get("instance"),
        primary_header.get("process_id"),
    )
    confirmation_identity = (
        confirmation_header.get("instance"),
        confirmation_header.get("process_id"),
    )
    if primary_identity == confirmation_identity:
        raise AuditError("post-item trace pair is not two independent instances")
    return {
        "primary_identity": list(primary_identity),
        "confirmation_identity": list(confirmation_identity),
        "primary_population_element_counts": primary["element_count_trace"],
        "confirmation_population_element_counts": confirmation[
            "element_count_trace"
        ],
        "primary_population_generations": primary["generation_trace"],
        "confirmation_population_generations": confirmation[
            "generation_trace"
        ],
        "primary_settled_sample_count": primary["settled_sample_count"],
        "confirmation_settled_sample_count": confirmation[
            "settled_sample_count"
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--promoter-log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo_root.resolve()
    candidate_root = args.candidate_root.resolve()
    evidence = args.evidence_root.resolve()
    promoter_log = args.promoter_log.resolve()

    contract_path = (
        repo
        / "tests/fixtures/webgame/native-menu-dark-cloud-item-row-supersession-v219.json"
    )
    contract = read_object(contract_path)
    require_contract(contract)
    item_audit_path = (
        evidence
        / "raw-v9/dark-cloud-item-row-question/dark-cloud-item-row-stop-audit.json"
    )
    item_audit = read_object(item_audit_path)
    overlay_path = candidate_root / "menu-overlay-reference.json"
    overlay = read_object(overlay_path)
    overlay_required = _overlay_counter(overlay)

    results: list[dict[str, Any]] = []
    unclassified_multisets: list[Counter[bytes]] = []
    overlay_match_multisets: list[Counter[bytes]] = []
    for layout_id in LAYOUTS:
        landed_path = (
            repo
            / f"webgame-contracts/baseline-snapshots/menu-layouts/{layout_id}.json"
        )
        current_landed_path = (
            repo / f"tests/fixtures/webgame/menu-layouts/{layout_id}.json"
        )
        candidate_path = candidate_root / f"menu-layouts/{layout_id}.json"
        if landed_path.read_bytes() != current_landed_path.read_bytes():
            raise AuditError(
                f"{layout_id} changed before post-item audit completed"
            )
        landed_fixture = read_object(landed_path)
        candidate_fixture = read_object(candidate_path)
        landed = landed_fixture.get("layout")
        settled = candidate_fixture.get("layout")
        if not isinstance(landed, dict) or not isinstance(settled, dict):
            raise AuditError(f"{layout_id} has no comparable layouts")
        primary_path = (
            candidate_root
            / f"menu-settlement-traces/{layout_id}.settlement.json"
        )
        confirmation_path = (
            candidate_root
            / f"menu-animation-confirmations/{layout_id}.confirmation.json"
        )
        primary_trace = read_object(primary_path)
        confirmation_trace = read_object(confirmation_path)
        projected, residual = project_structural_core(landed, settled)
        lifecycle, animation, unmatched = match_ambient_members(residual, settled)
        population, after_population, population_proof = match_population_members(
            unmatched,
            landed.get("generation"),
            settled.get("generation"),
            primary_trace,
            confirmation_trace,
        )
        item_disposition = None
        if layout_id in PUBLIC_LAYOUT_MEMBER_IDS:
            item_disposition, after_population = consume_exact_landed_residual(
                layout_id,
                landed,
                settled,
                after_population,
                contract,
                {
                    "sha256": file_sha256(landed_path),
                    "bytes": landed_path.stat().st_size,
                },
                {
                    "sha256": file_sha256(candidate_path),
                    "bytes": candidate_path.stat().st_size,
                },
            )
            if item_disposition is None:
                raise AuditError(f"{layout_id} did not consume its exact Item 1 row")

        overlay_gate_match, overlay_gate_residual = match_overlay_members(
            after_population, overlay
        )
        if overlay_gate_match or overlay_gate_residual != after_population:
            raise AuditError(
                f"{layout_id} unexpectedly passed the exact v2.4 overlay gate"
            )

        available = overlay_required.copy()
        overlay_members: list[dict[str, Any]] = []
        unclassified: list[dict[str, Any]] = []
        for element in after_population:
            signature = canonical_bytes(overlay_draw_payload(element))
            if available[signature] > 0:
                available[signature] -= 1
                overlay_members.append(element)
            else:
                unclassified.append(element)
        if any(available.values()) or not overlay_members or not unclassified:
            raise AuditError(
                f"{layout_id} post-item residual did not split into complete "
                "overlay reference plus a non-empty unclassified remainder"
            )

        primary_evidence = _population_evidence(
            primary_trace, f"{layout_id} post-item primary"
        )
        confirmation_evidence = _population_evidence(
            confirmation_trace, f"{layout_id} post-item confirmation"
        )
        member_records: list[dict[str, Any]] = []
        for element in unclassified:
            signature = _signature(element)
            primary_phase_counts = [
                counter[signature]
                for counter in primary_evidence["phase_counters"]
            ]
            confirmation_phase_counts = [
                counter[signature]
                for counter in confirmation_evidence["phase_counters"]
            ]
            primary_settled_counts = [
                counter[signature]
                for counter in primary_evidence["settled_counters"]
            ]
            confirmation_settled_counts = [
                counter[signature]
                for counter in confirmation_evidence["settled_counters"]
            ]
            if any(
                count
                for count in (
                    *primary_phase_counts,
                    *confirmation_phase_counts,
                    *primary_settled_counts,
                    *confirmation_settled_counts,
                )
            ):
                raise AuditError(
                    f"{layout_id} unclassified member {element.get('id')} "
                    "appears in a fresh trace"
                )
            member_records.append(
                {
                    "id": element["id"],
                    "art_id": element.get("art_id"),
                    "semantic_sha256": semantic_sha256(element),
                    "payload": copy.deepcopy(element),
                    "primary_population_counts": primary_phase_counts,
                    "confirmation_population_counts": confirmation_phase_counts,
                    "primary_settled_counts": sorted(
                        set(primary_settled_counts)
                    ),
                    "confirmation_settled_counts": sorted(
                        set(confirmation_settled_counts)
                    ),
                }
            )

        unclassified_counter = Counter(_signature(value) for value in unclassified)
        overlay_counter = Counter(_signature(value) for value in overlay_members)
        unclassified_multisets.append(unclassified_counter)
        overlay_match_multisets.append(overlay_counter)
        audit_layout = item_audit.get("layouts", {}).get(layout_id)
        if not isinstance(audit_layout, dict):
            raise AuditError(f"accepted Item 1 audit missed {layout_id}")
        results.append(
            {
                "layout_id": layout_id,
                "landed_fixture": receipt(landed_path, repo),
                "candidate_fixture": receipt(candidate_path, evidence),
                "landed_generation": landed.get("generation"),
                "settled_generation": settled.get("generation"),
                "landed_element_count": len(landed.get("elements", [])),
                "settled_structural_core_element_count": len(
                    settled.get("elements", [])
                ),
                "projected_core_element_count": len(projected),
                "ambient_disposition_count": len(lifecycle) + len(animation),
                "population_disposition_count": len(population),
                "population_proof": population_proof,
                "item_row_disposition": item_disposition,
                "post_item_residual_count": len(after_population),
                "post_item_first_residual": {
                    "id": after_population[0]["id"],
                    "art_id": after_population[0].get("art_id"),
                    "semantic_sha256": semantic_sha256(after_population[0]),
                    "overlay_reference_submultiset_member": (
                        after_population[0] in overlay_members
                    ),
                },
                "overlay_reference_submultiset_match_count": len(
                    overlay_members
                ),
                "overlay_gate_exact_equality": False,
                "unclassified_member_count": len(unclassified),
                "unclassified_semantic_multiset_sha256": sha256_json(
                    [
                        {
                            "semantic_sha256": key.hex(),
                            "count": unclassified_counter[key],
                        }
                        for key in sorted(unclassified_counter)
                    ]
                ),
                "unclassified_members": member_records,
                "fresh_pair": pair_evidence(
                    primary_trace, confirmation_trace
                ),
                "landed_capture_identity": {
                    "instance": audit_layout["landed"].get("instance"),
                    "process_id": audit_layout["landed"].get("process_id"),
                    "profile_state_provenance_present": audit_layout[
                        "landed"
                    ].get("profile_state_provenance_present"),
                },
                "primary_trace": receipt(primary_path, evidence),
                "confirmation_trace": receipt(confirmation_path, evidence),
            }
        )

    if not all(
        value == unclassified_multisets[0]
        for value in unclassified_multisets[1:]
    ) or not all(
        value == overlay_match_multisets[0]
        for value in overlay_match_multisets[1:]
    ):
        raise AuditError(
            "four browser-family layouts do not share exact post-item residual semantics"
        )
    first_residual = results[0]["post_item_first_residual"]
    expected_error = (
        "STOP: standalone dark-cloud-browser: landed-vs-settled mismatch "
        "survives ambient, population, overlay, and animation diagnosis: "
        f"'{first_residual['id']}' / '{first_residual['art_id']}'"
    )
    promoter = read_object(promoter_log)
    if promoter != {"success": False, "error": expected_error}:
        raise AuditError("post-item full promoter STOP changed or did not fail closed")

    float_path = repo / "tests/fixtures/webgame/float-rng-goldens.json"
    aggregate_path = candidate_root / "menu-goldens.json"
    audit = {
        "schema": SCHEMA,
        "status": "QUESTION",
        "finding": (
            "exact Item 1 supersession advances the full promoter to a "
            "second independent four-layout browser-chrome residual"
        ),
        "layouts": results,
        "cross_layout": {
            "layout_ids": list(LAYOUTS),
            "unclassified_semantic_multisets_equal": True,
            "unclassified_member_count": len(
                results[0]["unclassified_members"]
            ),
            "overlay_reference_submultiset_match_count": results[0][
                "overlay_reference_submultiset_match_count"
            ],
            "complete_overlay_reference_present": True,
            "full_residual_equals_overlay_reference": False,
            "landed_capture_identity_equal": len(
                {
                    (
                        value["landed_capture_identity"]["instance"],
                        value["landed_capture_identity"]["process_id"],
                    )
                    for value in results
                }
            )
            == 1,
        },
        "item_row_contract": receipt(contract_path, repo),
        "item_row_source_audit": receipt(item_audit_path, evidence),
        "overlay_reference": receipt(overlay_path, evidence),
        "promoter_stop": {
            "transcript": receipt(promoter_log, evidence),
            "message": expected_error,
        },
        "candidate_aggregate": receipt(aggregate_path, evidence),
        "float_rng_fixture": receipt(float_path, repo),
        "candidate_applied": False,
        "authorization": (
            "none: Item 1 record covers only three named text members; the "
            "post-item art residual remains fail-closed"
        ),
    }
    write_object(args.output.resolve(), audit)
    print(json.dumps(audit, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
