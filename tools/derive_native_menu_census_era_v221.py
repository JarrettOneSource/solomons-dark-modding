#!/usr/bin/env python3
"""Derive the exact v2.21 census-era disposition from sealed evidence."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

from native_menu_census_era_v221 import (
    CLASS_F_LAYOUTS,
    CLASS_F_WITNESS_AUDIT_SHA256,
    CHOICE_ROWS,
    CLASS_A_COUNTS,
    CLASS_A_OCCURRENCE_STOP,
    CLASS_B_COUNTS,
    CLASS_B_PAIR_STOP,
    FIELD_CORRECTIONS,
    FORBIDDEN,
    GENERATION_LAYOUTS,
    GUARD_SUBSUMPTIONS,
    SCHEMA,
    SEALED_CENSUS_SHA256,
    SEALED_OCCURRENCE_AUDIT_SHA256,
    SETTLEMENT_SPEC,
    require_contract,
)


class DerivationError(RuntimeError):
    """The accepted evidence no longer derives the bounded contract."""


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


def member_from_audit(row: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(row["semantic_payload"])
    payload["id"] = row["element_id"]
    return {
        "element_id": row["element_id"],
        "semantic_sha256": row["semantic_sha256"],
        "semantic_payload": payload,
        "source_census_occurrences": copy.deepcopy(
            row["source_census_occurrences"]
        ),
        "qualified_occurrences": copy.deepcopy(row["qualified_occurrences"]),
    }


def common_receipts(census_rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not census_rows:
        raise DerivationError("census-era layout group reached no real rows")
    fields = (
        "landed_fixture",
        "candidate_fixture",
        "primary_trace",
        "confirmation_trace",
        "profile_state_identity_sha256",
        "bound_endpoints",
    )
    expected = {
        field: copy.deepcopy(census_rows[0]["receipts"][field])
        for field in fields
    }
    if any(
        any(row["receipts"].get(field) != expected[field] for field in fields)
        for row in census_rows
    ):
        raise DerivationError("census-era layout receipts disagree within one group")
    return expected


def attest_class_a_rows(
    layout_id: str,
    rows: list[dict[str, Any]],
    expected_count: int,
) -> None:
    """Fail closed unless every exact Class-A row is absent everywhere."""
    if len(rows) != expected_count or any(
        row.get("absent_from_every_qualified_occurrence") is not True
        or any(
            occurrence.get("presence_sample_count") != 0
            for occurrence in row.get("qualified_occurrences", [])
        )
        for row in rows
    ):
        raise DerivationError(
            f"{CLASS_A_OCCURRENCE_STOP}: {layout_id} is not absent everywhere"
        )


def attest_class_b_rows(
    layout_id: str,
    rows: list[dict[str, Any]],
    expected_count: int,
) -> None:
    """Fail closed unless each adopted member exists in both paired traces."""
    for row in rows:
        paired = {
            occurrence.get("label"): occurrence
            for occurrence in row.get("qualified_occurrences", [])
            if occurrence.get("label")
            in {"standalone.primary", "standalone.confirmation"}
        }
        if set(paired) != {"standalone.primary", "standalone.confirmation"} or any(
            occurrence.get("presence_sample_count")
            != occurrence.get("sample_count")
            for occurrence in paired.values()
        ):
            raise DerivationError(f"{CLASS_B_PAIR_STOP}: {layout_id}")
    if len(rows) != expected_count or any(
        row.get("present_in_both_paired_standalone_traces") is not True
        for row in rows
    ):
        raise DerivationError(f"{CLASS_B_PAIR_STOP}: {layout_id}")


def build(
    evidence_root: Path,
    census_path: Path,
    occurrence_audit_path: Path,
    class_f_audit_path: Path,
    *,
    choice_slot_exclusion_enabled: bool = True,
) -> dict[str, Any]:
    mutation_tool = Path(__file__).with_name("run_native_menu_v221_mutations.py")
    if not mutation_tool.is_file():
        raise DerivationError("v2.21 mutation runner is absent")
    census_receipt = evidence_receipt(census_path, evidence_root)
    audit_receipt = evidence_receipt(occurrence_audit_path, evidence_root)
    class_f_receipt = evidence_receipt(class_f_audit_path, evidence_root)
    if census_receipt["sha256"] != SEALED_CENSUS_SHA256:
        raise DerivationError("source census is not the sealed 326-row audit")
    if audit_receipt["sha256"] != SEALED_OCCURRENCE_AUDIT_SHA256:
        raise DerivationError("qualified-occurrence audit changed")
    if class_f_receipt["sha256"] != CLASS_F_WITNESS_AUDIT_SHA256:
        raise DerivationError("bounded Class-F witness audit changed")
    census = read_object(census_path, "sealed census")
    audit = read_object(occurrence_audit_path, "qualified-occurrence audit")
    class_f_audit = read_object(class_f_audit_path, "Class-F witness audit")
    census_rows = census.get("unclassified_differences")
    layout_audits = audit.get("layout_audits")
    if (
        not isinstance(census_rows, list)
        or len(census_rows) != 326
        or not isinstance(layout_audits, list)
        or audit.get("summary", {}).get("class_a_row_count") != 263
        or audit.get("summary", {}).get("class_b_row_count") != 38
    ):
        raise DerivationError("sealed census/occurrence row census changed")
    class_f_layouts = class_f_audit.get("layouts")
    if (
        class_f_audit.get("schema")
        != "solomon-dark-native-menu-census-era-class-f-audit-v221"
        or class_f_audit.get("profile_state_identity_sha256")
        != "0539412d5c91207d5b225e86f79795d260fe7b73b8d9a1c29166bd09b445e372"
        or class_f_audit.get("class_f_layout_count") != len(CLASS_F_LAYOUTS)
        or class_f_audit.get("all_pairs_window_constant") is not True
        or class_f_audit.get("all_pairs_project_to_exact_qualified_cores") is not True
        or class_f_audit.get("counter_shopping_performed") is not False
        or not isinstance(class_f_layouts, dict)
        or set(class_f_layouts) != set(CLASS_F_LAYOUTS)
    ):
        raise DerivationError("bounded Class-F witness audit is incomplete")

    audit_rows: dict[tuple[str, str, str], dict[str, Any]] = {}
    for layout in layout_audits:
        layout_id = layout.get("layout_id") if isinstance(layout, dict) else None
        rows = layout.get("rows") if isinstance(layout, dict) else None
        if not isinstance(layout_id, str) or not isinstance(rows, list):
            raise DerivationError("occurrence audit layout lookup is incomplete")
        for row in rows:
            key = (
                layout_id,
                row.get("difference_type"),
                row.get("element_id"),
            )
            if key in audit_rows:
                raise DerivationError("occurrence audit row lookup is ambiguous")
            audit_rows[key] = row

    by_a: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_b: dict[str, list[dict[str, Any]]] = defaultdict(list)
    field_rows: list[dict[str, Any]] = []
    guard_rows: list[dict[str, Any]] = []
    for census_row in census_rows:
        layout_id = census_row.get("layout_id") if isinstance(census_row, dict) else None
        difference = census_row.get("difference") if isinstance(census_row, dict) else None
        if not isinstance(layout_id, str) or not isinstance(difference, dict):
            raise DerivationError("sealed census row is incomplete")
        kind = difference.get("difference_type")
        if kind in {"landed_only_member", "settled_only_member"}:
            element_id = difference.get("element_id")
            key = (layout_id, kind, element_id)
            audited = audit_rows.get(key)
            if audited is None:
                raise DerivationError(f"occurrence audit missed {key}")
            merged = {
                **copy.deepcopy(audited),
                "receipts": copy.deepcopy(census_row["receipts"]),
            }
            (by_a if kind == "landed_only_member" else by_b)[layout_id].append(
                merged
            )
        elif kind == "layout_field":
            field_rows.append(census_row)
        elif kind == "authorization_contract_failure":
            guard_rows.append(census_row)

    failures = audit.get("class_a_qualified_presence_failures")
    if not isinstance(failures, list) or {
        row.get("element_id"): row.get("semantic_sha256") for row in failures
    } != CHOICE_ROWS:
        raise DerivationError("two-row choice-slot gap did not reproduce")
    if not choice_slot_exclusion_enabled:
        first = sorted(failures, key=lambda row: row["element_id"])[0]
        confirmation = next(
            occurrence
            for occurrence in first["qualified_occurrences"]
            if occurrence["label"] == "standalone.confirmation"
        )
        raise DerivationError(
            f"{CLASS_A_OCCURRENCE_STOP}: '{first['element_id']}' is present "
            f"{confirmation['presence_sample_count']}/{confirmation['sample_count']} "
            "in standalone.confirmation"
        )

    class_a_records: list[dict[str, Any]] = []
    for layout_id, expected_count in CLASS_A_COUNTS.items():
        rows = [
            row for row in by_a[layout_id] if row["element_id"] not in CHOICE_ROWS
        ]
        attest_class_a_rows(layout_id, rows, expected_count)
        record = {
            "layout_id": layout_id,
            **common_receipts(rows),
            "members": [
                member_from_audit(row)
                for row in sorted(rows, key=lambda row: row["element_id"])
            ],
        }
        class_a_records.append(record)

    class_b_records: list[dict[str, Any]] = []
    for layout_id, expected_count in CLASS_B_COUNTS.items():
        rows = by_b[layout_id]
        attest_class_b_rows(layout_id, rows, expected_count)
        class_b_records.append(
            {
                "layout_id": layout_id,
                **common_receipts(rows),
                "members": [
                    member_from_audit(row)
                    for row in sorted(rows, key=lambda row: row["element_id"])
                ],
            }
        )

    choice_rows = []
    for row in sorted(failures, key=lambda value: value["element_id"]):
        matches = row.get("choice_slot_matches")
        if not isinstance(matches, list) or len(matches) != 1:
            raise DerivationError("choice-slot mapping is absent or ambiguous")
        choice_rows.append(member_from_audit(row))
    def normalized_slot_binding(row: dict[str, Any]) -> dict[str, Any]:
        binding = copy.deepcopy(row["choice_slot_matches"][0])
        binding.pop("observed_roster_evidence", None)
        binding.pop("measured_center", None)
        return binding

    slot_binding = normalized_slot_binding(failures[0])
    if any(normalized_slot_binding(row) != slot_binding for row in failures):
        raise DerivationError("two Skills.84 rows do not map to one exact slot")

    corrections = []
    for (layout_id, field), values in sorted(FIELD_CORRECTIONS.items()):
        matches = [
            row
            for row in field_rows
            if row["layout_id"] == layout_id
            and row["difference"].get("field") == field
        ]
        if len(matches) != 1 or (
            matches[0]["difference"].get("landed_value"),
            matches[0]["difference"].get("settled_value"),
        ) != values:
            raise DerivationError(f"field correction {layout_id}.{field} changed")
        receipts = matches[0]["receipts"]
        corrections.append(
            {
                "correction_id": f"v221-{layout_id}-{field}",
                "layout_id": layout_id,
                "field": field,
                "landed_value": values[0],
                "settled_value": values[1],
                **{
                    key: copy.deepcopy(receipts[key])
                    for key in (
                        "landed_fixture",
                        "candidate_fixture",
                        "primary_trace",
                        "confirmation_trace",
                        "profile_state_identity_sha256",
                        "bound_endpoints",
                    )
                },
            }
        )

    generation_rows = {
        row["layout_id"]
        for row in field_rows
        if row["difference"].get("field") == "generation"
    }
    if generation_rows != GENERATION_LAYOUTS:
        raise DerivationError("generation layout census changed")
    guard_map = {
        (row["layout_id"], row["difference"].get("field")): row
        for row in guard_rows
    }
    if not GUARD_SUBSUMPTIONS <= set(guard_map):
        raise DerivationError("guard-subsumption census changed")
    guard_subsumptions = [
        {
            "layout_id": layout_id,
            "guard": guard,
            "original_message": guard_map[(layout_id, guard)]["difference"][
                "message"
            ],
            "coverage": "exact_class_a_record_only",
        }
        for layout_id, guard in sorted(GUARD_SUBSUMPTIONS)
    ]

    equivalences = census.get("diagnostic_population_witness_equivalence_classes")
    if not isinstance(equivalences, list) or len(equivalences) != 1:
        raise DerivationError("pause-menu equivalence class did not reproduce")
    selection = equivalences[0].get("selection")
    outcomes = selection.get("candidate_outcomes") if isinstance(selection, dict) else None
    if (
        equivalences[0].get("layout_id") != "pause-menu"
        or not isinstance(outcomes, list)
        or len(outcomes) != 2
        or selection.get("diagnosis_converged") is not True
        or len({row.get("unclassified_differences_sha256") for row in outcomes})
        != 1
        or any(row.get("unclassified_difference_count") != 0 for row in outcomes)
    ):
        raise DerivationError("pause-menu equivalence outcomes differ")

    class_f_records: list[dict[str, Any]] = []
    for layout_id, (edge_id, core_count) in CLASS_F_LAYOUTS.items():
        source = class_f_layouts[layout_id]
        if not isinstance(source, dict):
            raise DerivationError(f"Class-F witness '{layout_id}' is not an object")
        pair = source.get("pair")
        if (
            source.get("status") != "class_f_population_witness_satisfied"
            or source.get("projected_core_element_count") != core_count
            or not isinstance(source.get("projected_core_sha256"), str)
            or len(source["projected_core_sha256"]) != 64
            or source.get("landed_generation_selection_performed") is not False
            or not isinstance(pair, list)
            or len(pair) != 2
        ):
            raise DerivationError(f"Class-F witness '{layout_id}' changed")
        projected_hashes = {row.get("projected_core_sha256") for row in pair}
        identities = {
            (row.get("instance"), row.get("process_id")) for row in pair
        }
        if (
            projected_hashes != {source["projected_core_sha256"]}
            or len(identities) != 2
            or any(row.get("settled_sample_count", 0) < 40 for row in pair)
            or any(row.get("settled_span_milliseconds", 0) < 2_000 for row in pair)
        ):
            raise DerivationError(f"Class-F pair '{layout_id}' is not exact")
        class_f_records.append(
            {
                "layout_id": layout_id,
                "edge_id": edge_id,
                "profile_state_identity_sha256": class_f_audit[
                    "profile_state_identity_sha256"
                ],
                "qualified_candidate": copy.deepcopy(
                    source["qualified_candidate"]
                ),
                "projected_core_sha256": source["projected_core_sha256"],
                "projected_core_element_count": core_count,
                "pair": [
                    {
                        key: copy.deepcopy(row[key])
                        for key in (
                            "instance",
                            "process_id",
                            "measured_generation",
                            "settled_sample_count",
                            "settled_span_milliseconds",
                            "projected_core_sha256",
                            "navigation_recording",
                            "launch",
                            "launch_profile_state",
                            "stage_report",
                            "pre_navigation_durable_census",
                            "post_capture_durable_census",
                            "exact_pid_disposal",
                            "host_quiescence_after",
                        )
                    }
                    for row in pair
                ],
                "acceptance_basis": source["acceptance_basis"],
                "landed_generation_selection_performed": False,
            }
        )

    contract = {
        "schema": SCHEMA,
        "settlement_spec": SETTLEMENT_SPEC,
        "class": "sealed_census_exact_disposition",
        "source_census": census_receipt,
        "occurrence_audit": audit_receipt,
        "choice_slot_reconciliation": {
            "layout_id": "skill-picker",
            "source_audit": audit_receipt,
            "slot_binding": slot_binding,
            "rows": choice_rows,
            "future_extension": "QUESTION_required",
        },
        "class_a_records": sorted(
            class_a_records, key=lambda record: record["layout_id"]
        ),
        "class_b_records": sorted(
            class_b_records, key=lambda record: record["layout_id"]
        ),
        "generation_layouts": sorted(GENERATION_LAYOUTS),
        "field_corrections": corrections,
        "guard_subsumptions": guard_subsumptions,
        "pause_menu_population_equivalence": {
            "layout_id": "pause-menu",
            "selection_performed": False,
            "diagnosis_converged": True,
            "unclassified_difference_count": 0,
            "candidate_bindings": copy.deepcopy(outcomes),
        },
        "class_f_witnesses": {
            "source_audit": class_f_receipt,
            "records": sorted(
                class_f_records, key=lambda record: record["layout_id"]
            ),
            "counter_shopping_performed": False,
        },
        "application": {
            "class_a_member_count": 261,
            "class_b_member_count": 38,
            "choice_slot_reconciliation_count": 2,
            "field_correction_count": 6,
            "generation_layout_count": 13,
            "guard_subsumption_count": 4,
            "class_f_witness_count": 2,
            "all_or_nothing_per_layout": True,
            "candidate_member_rewrite": False,
        },
        "forbidden": FORBIDDEN,
        "derivation": {
            "tool": "tools/derive_native_menu_census_era_v221.py",
            "tool_sha256": sha256_file(Path(__file__).resolve()),
            "tool_bytes": Path(__file__).resolve().stat().st_size,
            "mutation_tool": "tools/run_native_menu_v221_mutations.py",
            "mutation_tool_sha256": sha256_file(mutation_tool),
            "mutation_tool_bytes": mutation_tool.stat().st_size,
            "source_row_count": 326,
            "writes_only_contract": True,
            "future_choice_slot_rows_require_question": True,
        },
    }
    require_contract(contract)
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
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--census", type=Path, required=True)
    parser.add_argument("--occurrence-audit", type=Path, required=True)
    parser.add_argument("--class-f-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--disable-choice-slot-exclusion-for-mutation", action="store_true"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    contract = build(
        args.evidence_root.resolve(),
        args.census.resolve(),
        args.occurrence_audit.resolve(),
        args.class_f_audit.resolve(),
        choice_slot_exclusion_enabled=(
            not args.disable_choice_slot_exclusion_for_mutation
        ),
    )
    atomic_json(args.output.resolve(), contract)
    print(json.dumps(contract["application"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
