#!/usr/bin/env python3
"""Derive the exact v2.22 final-four disposition from sealed evidence."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from native_menu_census_era_v221 import (
    require_contract as require_v221_contract,
    semantic_sha256,
)
from native_menu_final_disposition_v222 import (
    NAMED_ENDPOINT_VACUITY,
    PROFILE_STATE_IDENTITY_SHA256,
    SCHEMA,
    SEALED_FINAL_CENSUS_SHA256,
    SEQUENCE_LAYOUTS,
    SETTLEMENT_SPEC,
    FinalDispositionV222Error,
    attest_sequence_derivation,
    canonical_bytes,
    require_contract,
    sequence_sha256,
)
from native_menu_landed_diagnosis_v25 import _ordered, _signature


class DerivationError(RuntimeError):
    """The sealed evidence no longer derives the bounded v2.22 contract."""


def read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise DerivationError(f"{label} is not readable JSON: {error}") from error
    if not isinstance(value, dict):
        raise DerivationError(f"{label} is not a JSON object")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def evidence_receipt(path: Path, evidence_root: Path) -> dict[str, Any]:
    resolved = path.resolve()
    root = evidence_root.resolve()
    if not resolved.is_relative_to(root):
        raise DerivationError(f"evidence path escapes the campaign root: {path}")
    return {
        "evidence_path": resolved.relative_to(root).as_posix(),
        "sha256": sha256_file(resolved),
        "bytes": resolved.stat().st_size,
    }


def repository_receipt(path: Path, repo_root: Path) -> dict[str, Any]:
    resolved = path.resolve()
    root = repo_root.resolve()
    if not resolved.is_relative_to(root):
        raise DerivationError(f"repository path escapes the clone: {path}")
    return {
        "repo_relative_path": resolved.relative_to(root).as_posix(),
        "sha256": sha256_file(resolved),
        "bytes": resolved.stat().st_size,
    }


def _class_b_semantics(
    layout_id: str, v221_contract: dict[str, Any]
) -> Counter[str]:
    view = require_v221_contract(v221_contract)
    record = view["class_b"].get(layout_id)
    if record is None:
        raise DerivationError(
            f"v2.22 sequence layout {layout_id} has no exact Class-B adoption"
        )
    return Counter(member["semantic_sha256"] for member in record["members"])


def _without_class_b(
    elements: list[dict[str, Any]],
    class_b: Counter[str],
    label: str,
) -> list[dict[str, Any]]:
    remaining = class_b.copy()
    result: list[dict[str, Any]] = []
    for element in elements:
        signature = semantic_sha256(element)
        if remaining[signature] > 0:
            remaining[signature] -= 1
        else:
            result.append(element)
    if any(remaining.values()):
        raise DerivationError(f"{label} omitted a pinned Class-B member")
    return result


def _project_landed(
    landed_elements: list[dict[str, Any]],
    settled_elements: list[dict[str, Any]],
    label: str,
) -> list[dict[str, Any]]:
    remaining = Counter(_signature(element) for element in settled_elements)
    projected: list[dict[str, Any]] = []
    for element in _ordered(landed_elements, label):
        signature = _signature(element)
        if remaining[signature] > 0:
            remaining[signature] -= 1
            projected.append(element)
    if any(remaining.values()):
        raise DerivationError(f"{label} has a membership delta before sequence proof")
    return projected


def _unique_edge(
    navigation: dict[str, Any], edge_id: str
) -> dict[str, Any]:
    matches = [
        edge
        for edge in navigation.get("edges", [])
        if isinstance(edge, dict) and edge.get("id") == edge_id
    ]
    if len(matches) != 1:
        raise DerivationError(f"navigation edge {edge_id!r} is absent or ambiguous")
    return matches[0]


def _receipt_matches(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    return {
        "sha256": expected.get("sha256"),
        "bytes": expected.get("bytes"),
    } == {
        "sha256": actual.get("sha256"),
        "bytes": actual.get("bytes"),
    }


def build(
    repo_root: Path,
    evidence_root: Path,
    census_path: Path,
    candidate_root: Path,
    navigation_path: Path,
    v221_contract_path: Path,
    *,
    census_override: dict[str, Any] | None = None,
    occurrence_sequence_overrides: dict[
        str, dict[tuple[str, str, str], str]
    ]
    | None = None,
) -> dict[str, Any]:
    mutation_tool = Path(__file__).with_name("run_native_menu_v222_mutations.py")
    if not mutation_tool.is_file():
        raise DerivationError("v2.22 mutation runner is absent")
    census_receipt = evidence_receipt(census_path, evidence_root)
    if census_receipt["sha256"] != SEALED_FINAL_CENSUS_SHA256:
        raise DerivationError("source census is not the sealed four-row audit")
    census = (
        copy.deepcopy(census_override)
        if census_override is not None
        else read_object(census_path, "sealed final census")
    )
    rows = census.get("unclassified_differences")
    if not isinstance(rows, list) or len(rows) != 4:
        raise DerivationError("sealed final census no longer contains exactly four rows")
    v221_contract = read_object(v221_contract_path, "v2.21 contract")
    require_v221_contract(v221_contract)
    navigation = read_object(navigation_path, "resolved navigation")
    navigation_receipt = evidence_receipt(navigation_path, evidence_root)

    sequence_rows = [
        row
        for row in rows
        if isinstance(row, dict)
        and isinstance(row.get("difference"), dict)
        and row["difference"].get("field") == "relative_draw_sequence"
    ]
    if {row.get("layout_id") for row in sequence_rows} != set(SEQUENCE_LAYOUTS):
        raise DerivationError("sealed sequence-row layout scope changed")

    sequence_records: list[dict[str, Any]] = []
    for row in sequence_rows:
        layout_id = row["layout_id"]
        expected = SEQUENCE_LAYOUTS[layout_id]
        candidate_path = candidate_root / f"menu-layouts/{layout_id}.json"
        primary_path = (
            candidate_root
            / f"menu-settlement-traces/{layout_id}.settlement.json"
        )
        confirmation_path = (
            candidate_root
            / f"menu-animation-confirmations/{layout_id}.confirmation.json"
        )
        landed_path = repo_root / f"tests/fixtures/webgame/menu-layouts/{layout_id}.json"
        baseline_path = (
            repo_root
            / f"webgame-contracts/baseline-snapshots/menu-layouts/{layout_id}.json"
        )
        candidate_fixture = read_object(candidate_path, f"{layout_id} candidate")
        landed_fixture = read_object(landed_path, f"{layout_id} landed fixture")
        class_b = _class_b_semantics(layout_id, v221_contract)
        settled = _without_class_b(
            candidate_fixture["layout"]["elements"],
            class_b,
            f"{layout_id} standalone",
        )
        projected = _project_landed(
            landed_fixture["layout"]["elements"], settled, f"{layout_id} landed"
        )
        edge_id, side = str(expected["transition_source"]).split(".", 1)
        edge = _unique_edge(navigation, edge_id)
        endpoint = edge.get(side)
        if (
            not isinstance(endpoint, dict)
            or endpoint.get("layout_id") != layout_id
            or not isinstance(endpoint.get("layout"), dict)
            or not isinstance(endpoint["layout"].get("elements"), list)
        ):
            raise DerivationError(
                f"{expected['transition_source']} no longer binds {layout_id}"
            )
        transition = _without_class_b(
            endpoint["layout"]["elements"],
            class_b,
            str(expected["transition_source"]),
        )
        observed = {
            ("standalone", "", ""): sequence_sha256(settled),
            ("transition_source", edge_id, side): sequence_sha256(transition),
        }
        if occurrence_sequence_overrides and layout_id in occurrence_sequence_overrides:
            observed = copy.deepcopy(occurrence_sequence_overrides[layout_id])
        try:
            attest_sequence_derivation(row, rows, observed)
        except FinalDispositionV222Error as error:
            raise DerivationError(str(error)) from error
        if (
            sequence_sha256(projected) != expected["landed"]
            or sequence_sha256(settled) != expected["settled"]
        ):
            raise DerivationError(f"{layout_id} sequence receipts no longer reproduce")
        receipts = row.get("receipts")
        if not isinstance(receipts, dict):
            raise DerivationError(f"{layout_id} census row has no receipts")
        landed_receipt = repository_receipt(landed_path, repo_root)
        candidate_receipt = evidence_receipt(candidate_path, evidence_root)
        primary_receipt = evidence_receipt(primary_path, evidence_root)
        confirmation_receipt = evidence_receipt(confirmation_path, evidence_root)
        if any(
            not _receipt_matches(receipts.get(field, {}), actual)
            for field, actual in (
                ("landed_fixture", landed_receipt),
                ("candidate_fixture", candidate_receipt),
                ("primary_trace", primary_receipt),
                ("confirmation_trace", confirmation_receipt),
            )
        ) or receipts.get("profile_state_identity_sha256") != PROFILE_STATE_IDENTITY_SHA256:
            raise DerivationError(f"{layout_id} census receipt chain changed")
        if sha256_file(baseline_path) != landed_receipt["sha256"]:
            raise DerivationError(
                f"{layout_id} immutable baseline is not the landed input"
            )
        occurrences: list[dict[str, Any]] = []
        for occurrence in row["occurrences"]:
            normalized = copy.deepcopy(occurrence)
            normalized["sequence_sha256"] = expected["settled"]
            occurrences.append(normalized)
        sequence_records.append(
            {
                "layout_id": layout_id,
                "source_census_sha256": SEALED_FINAL_CENSUS_SHA256,
                "landed_sequence_sha256": expected["landed"],
                "settled_sequence_sha256": expected["settled"],
                "moved_members": copy.deepcopy(row["difference"]["moved_members"]),
                "membership_delta": {
                    "landed_only_member_count": 0,
                    "settled_only_member_count": 0,
                },
                "occurrences": sorted(
                    occurrences,
                    key=lambda value: (
                        value.get("scope", ""),
                        value.get("edge_id", ""),
                        value.get("side", ""),
                    ),
                ),
                "landed_fixture": landed_receipt,
                "landed_baseline_snapshot": repository_receipt(
                    baseline_path, repo_root
                ),
                "candidate_fixture": candidate_receipt,
                "primary_trace": primary_receipt,
                "confirmation_trace": confirmation_receipt,
                "profile_state_identity_sha256": PROFILE_STATE_IDENTITY_SHA256,
            }
        )

    vacuity_records: list[dict[str, Any]] = []
    for layout_id, core_sha256 in sorted(NAMED_ENDPOINT_VACUITY.items()):
        candidate_path = candidate_root / f"menu-layouts/{layout_id}.json"
        primary_path = (
            candidate_root
            / f"menu-settlement-traces/{layout_id}.settlement.json"
        )
        confirmation_path = (
            candidate_root
            / f"menu-animation-confirmations/{layout_id}.confirmation.json"
        )
        fixture = read_object(candidate_path, f"{layout_id} candidate")
        header = fixture.get("header")
        layout = fixture.get("layout")
        if (
            not isinstance(header, dict)
            or not isinstance(layout, dict)
            or layout.get("structural_core_sha256") != core_sha256
            or header.get("profile_state", {}).get(
                "profile_state_identity_sha256"
            )
            != PROFILE_STATE_IDENTITY_SHA256
        ):
            raise DerivationError(f"{layout_id} paired-standalone identity changed")
        inbound = [
            edge.get("id")
            for edge in navigation.get("edges", [])
            if isinstance(edge, dict)
            and isinstance(edge.get("after"), dict)
            and edge["after"].get("layout_id") == layout_id
        ]
        if inbound or not navigation.get("edges"):
            raise DerivationError(
                f"{layout_id} endpoint-vacuity graph condition changed"
            )
        vacuity_records.append(
            {
                "layout_id": layout_id,
                "structural_core_sha256": core_sha256,
                "candidate_fixture": evidence_receipt(candidate_path, evidence_root),
                "primary_trace": evidence_receipt(primary_path, evidence_root),
                "confirmation_trace": evidence_receipt(
                    confirmation_path, evidence_root
                ),
                "profile_state_identity_sha256": PROFILE_STATE_IDENTITY_SHA256,
                "native_inbound_edge_count": 0,
                "paired_standalone_required": True,
            }
        )

    field_rows = {
        row.get("layout_id")
        for row in rows
        if isinstance(row, dict)
        and isinstance(row.get("difference"), dict)
        and row["difference"].get("field") == "generation"
    }
    if field_rows != {"map-picker", "skill-picker"}:
        raise DerivationError("sealed endpoint-vacuity row scope changed")

    contract = {
        "schema": SCHEMA,
        "settlement_spec": SETTLEMENT_SPEC,
        "class": "sealed_final_four_exact_disposition",
        "source_census": census_receipt,
        "resolved_navigation": navigation_receipt,
        "sequence_supersessions": sorted(
            sequence_records, key=lambda record: record["layout_id"]
        ),
        "endpoint_vacuity": {
            "named_layout_ids": sorted(NAMED_ENDPOINT_VACUITY),
            "records": vacuity_records,
            "promotion_time_recheck_required": True,
        },
        "application": {
            "sequence_supersession_count": 2,
            "moved_member_count": sum(
                len(record["moved_members"]) for record in sequence_records
            ),
            "named_endpoint_vacuity_count": 3,
            "candidate_sequence_rewrite": False,
            "generation_counter_rewrite": False,
        },
        "forbidden": [
            "general_order_tolerance",
            "sequence_rewrite",
            "membership_delta",
            "property_based_endpoint_vacuity",
            "generation_counter_edit",
        ],
        "derivation": {
            "tool": "tools/derive_native_menu_final_disposition_v222.py",
            "tool_sha256": sha256_file(Path(__file__).resolve()),
            "tool_bytes": Path(__file__).resolve().stat().st_size,
            "mutation_tool": "tools/run_native_menu_v222_mutations.py",
            "mutation_tool_sha256": sha256_file(mutation_tool),
            "mutation_tool_bytes": mutation_tool.stat().st_size,
            "source_row_count": 4,
            "writes_only_contract": True,
        },
    }
    try:
        require_contract(contract)
    except FinalDispositionV222Error as error:
        raise DerivationError(str(error)) from error
    return contract


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".menufix.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--census", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--navigation", type=Path, required=True)
    parser.add_argument("--v221-contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    contract = build(
        args.repo_root.resolve(),
        args.evidence_root.resolve(),
        args.census.resolve(),
        args.candidate_root.resolve(),
        args.navigation.resolve(),
        args.v221_contract.resolve(),
    )
    atomic_json(args.output.resolve(), contract)
    print(json.dumps(contract["application"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
