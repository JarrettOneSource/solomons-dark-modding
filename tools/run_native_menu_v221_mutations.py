#!/usr/bin/env python3
"""Run the complete green-trip-green Settlement v2.21 mutation fleet."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, Callable

from derive_native_menu_census_era_v221 import (
    DerivationError,
    attest_class_a_rows,
    attest_class_b_rows,
    build,
)
from native_menu_census_era_v221 import (
    CHOICE_ROWS,
    CHOICE_SLOT_STOP,
    CLASS_A_OCCURRENCE_STOP,
    CLASS_A_RESIDUAL_STOP,
    CLASS_B_PAIR_STOP,
    CONTRACT_SCOPE_STOP,
    FIELD_CORRECTION_STOP,
    PAUSE_EQUIVALENCE_STOP,
    STALE_SCREEN_ID_STOP,
    CensusEraV221Error,
    consume_choice_slot_rows,
    consume_class_a_residual,
    diagnose_field_corrections,
    require_class_f_witness,
    require_contract,
    semantic_sha256,
    split_class_b_additions,
    validate_dark_cloud_menu_references,
    validate_pause_equivalence,
)
from native_menu_landed_diagnosis_v25 import (
    LandedDiagnosisError,
    diagnose_landed_layout,
)


ORIGINAL_FIRST_STOP = (
    "STOP: standalone dark-cloud-login-settings: landed-vs-settled structural "
    "core mismatch: reproduced core member 'dark_cloud_browser.login' is missing "
    "from the landed layout"
)
UNCOVERED_CHROME_GUARD = (
    "v2.19 Dark Cloud browser-chrome era supersession does not authorize "
    "another layout"
)
CHOICE_EXCLUSION_REFUSAL = (
    f"{CLASS_A_OCCURRENCE_STOP}: 'skill_picker.art.skills_84.1' is present "
    "40/40 in standalone.confirmation"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    return parser.parse_args()


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"v2.21 mutation input is not an object: {path}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_receipt(path: Path) -> dict[str, Any]:
    return {"sha256": sha256_file(path), "bytes": path.stat().st_size}


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".menufix.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def clear_bytecode(repo: Path) -> list[str]:
    cleared: list[str] = []
    for relative in ("tests/__pycache__", "tests/re/__pycache__", "tools/__pycache__"):
        path = repo / relative
        if path.is_dir():
            shutil.rmtree(path)
        cleared.append(relative)
    return cleared


def record_by_layout(contract: dict[str, Any], field: str, layout_id: str) -> dict[str, Any]:
    matches = [
        record
        for record in contract[field]
        if isinstance(record, dict) and record.get("layout_id") == layout_id
    ]
    if len(matches) != 1:
        raise ValueError(f"v2.21 mutation fixture lookup is ambiguous: {field}/{layout_id}")
    return matches[0]


def audit_rows(
    audit: dict[str, Any],
    layout_id: str,
    difference_type: str,
) -> list[dict[str, Any]]:
    matches = [
        layout
        for layout in audit.get("layout_audits", [])
        if isinstance(layout, dict) and layout.get("layout_id") == layout_id
    ]
    if len(matches) != 1:
        raise ValueError(f"v2.21 occurrence audit lookup is ambiguous: {layout_id}")
    rows = [
        copy.deepcopy(row)
        for row in matches[0].get("rows", [])
        if isinstance(row, dict) and row.get("difference_type") == difference_type
    ]
    if not rows:
        raise ValueError(
            f"v2.21 occurrence audit reached no {difference_type} rows for {layout_id}"
        )
    return rows


def expected_elements(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [copy.deepcopy(member["semantic_payload"]) for member in record["members"]]


def minimal_corrected_references() -> tuple[dict[str, Any], dict[str, Any]]:
    layout = {
        "screen_id": "dark_cloud_menu",
        "elements": [],
    }
    aggregate = {
        "layouts": [
            {
                "fixture": "menu-layouts/dark-cloud-menu.json",
                "layout": copy.deepcopy(layout),
            }
        ]
    }
    endpoint = {
        "layout_id": "dark-cloud-menu",
        "semantic_surface": "dark_cloud_menu",
        "tagged_screen": "dark_cloud_menu",
        "layout": copy.deepcopy(layout),
    }
    navigation = {
        "edges": [
            {
                "id": "dark_cloud_browser_to_menu",
                "before": {"layout_id": "dark-cloud-browser"},
                "after": endpoint,
            }
        ]
    }
    return aggregate, navigation


def main() -> int:
    args = parse_args()
    repo = args.repo_root.resolve()
    evidence = args.evidence_root.resolve()
    output = args.output_directory.resolve()
    contract_path = (
        repo / "tests/fixtures/webgame/native-menu-census-era-disposition-v221.json"
    )
    contract = read_object(contract_path)
    census_path = evidence / contract["source_census"]["evidence_path"]
    occurrence_path = evidence / contract["occurrence_audit"]["evidence_path"]
    class_f_path = evidence / contract["class_f_witnesses"]["source_audit"]["evidence_path"]
    occurrence_audit = read_object(occurrence_path)
    candidate_root = evidence / "raw-v9/candidates/candidate-v214-profile-final"
    overlay_reference = read_object(candidate_root / "menu-overlay-reference.json")

    class_a_record = record_by_layout(contract, "class_a_records", "dark-cloud-options")
    class_b_record = record_by_layout(contract, "class_b_records", "hall-of-fame")
    choice_rows = contract["choice_slot_reconciliation"]["rows"]

    def green() -> dict[str, Any]:
        view = require_contract(copy.deepcopy(contract))
        choice, choice_remaining = consume_choice_slot_rows(
            "skill-picker",
            expected_elements({"members": choice_rows}),
            copy.deepcopy(contract),
        )
        class_a, class_a_remaining = consume_class_a_residual(
            "dark-cloud-options",
            expected_elements(class_a_record),
            copy.deepcopy(contract),
            class_a_record["landed_fixture"],
            class_a_record["candidate_fixture"],
        )
        class_b, class_b_remaining = split_class_b_additions(
            "hall-of-fame",
            expected_elements(class_b_record),
            copy.deepcopy(contract),
            class_b_record["landed_fixture"],
            class_b_record["candidate_fixture"],
        )
        corrections: list[str] = []
        for record in contract["field_corrections"]:
            landed = {record["field"]: record["landed_value"]}
            settled = {record["field"]: record["settled_value"]}
            result = diagnose_field_corrections(
                record["layout_id"],
                landed,
                settled,
                copy.deepcopy(contract),
                record["landed_fixture"],
                record["candidate_fixture"],
            )
            if len(result) != 1:
                raise ValueError("v2.21 green field-correction census changed")
            corrections.append(result[0]["correction_id"])
        pause = validate_pause_equivalence(
            copy.deepcopy(contract),
            copy.deepcopy(contract["pause_menu_population_equivalence"]["candidate_bindings"]),
        )
        aggregate, navigation = minimal_corrected_references()
        references = validate_dark_cloud_menu_references(aggregate, navigation)
        class_f = [
            require_class_f_witness(layout_id, copy.deepcopy(contract))["layout_id"]
            for layout_id in ("performance", "profile-save-select")
        ]
        attest_class_a_rows(
            "dark-cloud-options",
            audit_rows(occurrence_audit, "dark-cloud-options", "landed_only_member"),
            28,
        )
        attest_class_b_rows(
            "hall-of-fame",
            audit_rows(occurrence_audit, "hall-of-fame", "settled_only_member"),
            4,
        )
        if (
            choice is None
            or choice_remaining
            or class_a is None
            or class_a_remaining
            or class_b is None
            or class_b_remaining
            or len(corrections) != 6
            or pause.get("zero_difference") is not True
            or references.get("dangling") != 0
            or class_f != ["performance", "profile-save-select"]
            or set(view["class_a"]) != set(contract_record["layout_id"] for contract_record in contract["class_a_records"])
        ):
            raise ValueError("v2.21 green baseline did not exercise every disposition class")
        return {
            "class_a_member_count": class_a["superseded_member_count"],
            "class_b_member_count": class_b["adopted_member_count"],
            "choice_member_ids": choice["member_ids"],
            "field_correction_ids": sorted(corrections),
            "pause_equivalence": pause["diagnosis_converged"],
            "screen_id_reference_count": len(references["references"]),
            "class_f_layouts": class_f,
        }

    cases: list[tuple[str, str, str, Callable[[], None]]] = []

    missing_residual = expected_elements(class_a_record)[1:]
    cases.append(
        (
            "class_a_record_missing_one_member_trips_residual",
            "remove one of the exact 28 residual members",
            CLASS_A_RESIDUAL_STOP,
            lambda: consume_class_a_residual(
                "dark-cloud-options",
                copy.deepcopy(missing_residual),
                copy.deepcopy(contract),
                class_a_record["landed_fixture"],
                class_a_record["candidate_fixture"],
            ),
        )
    )

    def class_a_member_not_in_census() -> None:
        mutated = copy.deepcopy(contract)
        record = record_by_layout(mutated, "class_a_records", "dark-cloud-options")
        member = record["members"][0]
        member["element_id"] = "dark_cloud_options.art.not_in_sealed_census.1"
        member["semantic_payload"]["id"] = member["element_id"]
        member["semantic_sha256"] = semantic_sha256(member["semantic_payload"])
        require_contract(mutated)

    cases.append(
        (
            "class_a_member_not_in_census_trips",
            "replace one exact census member with a valid but unrecorded member",
            CONTRACT_SCOPE_STOP,
            class_a_member_not_in_census,
        )
    )

    def class_a_wrong_layout() -> None:
        mutated = copy.deepcopy(contract)
        record_by_layout(mutated, "class_a_records", "dark-cloud-options")[
            "layout_id"
        ] = "game-over"
        require_contract(mutated)

    cases.append(
        (
            "class_a_supersession_on_unrecorded_layout_trips",
            "move an exact Class-A record to game-over",
            CONTRACT_SCOPE_STOP,
            class_a_wrong_layout,
        )
    )

    def generator_refuses_qualified_presence() -> None:
        rows = audit_rows(occurrence_audit, "dark-cloud-options", "landed_only_member")
        rows[0]["absent_from_every_qualified_occurrence"] = False
        rows[0]["qualified_occurrences"][0]["presence_sample_count"] = 1
        attest_class_a_rows("dark-cloud-options", rows, 28)

    cases.append(
        (
            "class_a_generator_refuses_qualified_presence",
            "make one Class-A row present in one qualified sample",
            f"{CLASS_A_OCCURRENCE_STOP}: dark-cloud-options is not absent everywhere",
            generator_refuses_qualified_presence,
        )
    )

    def generator_refuses_single_trace_class_b() -> None:
        rows = audit_rows(occurrence_audit, "hall-of-fame", "settled_only_member")
        rows[0]["present_in_both_paired_standalone_traces"] = False
        rows[0]["qualified_occurrences"] = [
            occurrence
            for occurrence in rows[0]["qualified_occurrences"]
            if occurrence["label"] != "standalone.confirmation"
        ]
        attest_class_b_rows("hall-of-fame", rows, 4)

    cases.append(
        (
            "class_b_generator_refuses_single_trace_member",
            "remove the confirmation observation for one adopted member",
            f"{CLASS_B_PAIR_STOP}: hall-of-fame",
            generator_refuses_single_trace_class_b,
        )
    )

    for correction in contract["field_corrections"]:
        def target_mutation(record: dict[str, Any] = correction) -> None:
            mutated = copy.deepcopy(contract)
            target = next(
                entry
                for entry in mutated["field_corrections"]
                if entry["correction_id"] == record["correction_id"]
            )
            target["settled_value"] = str(target["settled_value"]).swapcase()
            require_contract(mutated)

        cases.append(
            (
                f"field_correction_target_mutation_{correction['layout_id']}_{correction['field']}",
                f"change the exact case-sensitive target for {correction['layout_id']}.{correction['field']}",
                FIELD_CORRECTION_STOP,
                target_mutation,
            )
        )

    def field_wrong_layout() -> None:
        diagnose_field_corrections(
            "pause-menu",
            {"screen_title": ""},
            {"screen_title": "GAME SETTINGS"},
            copy.deepcopy(contract),
            {},
            {},
        )

    cases.append(
        (
            "field_correction_family_rejects_other_layout",
            "claim the title pattern on pause-menu",
            FIELD_CORRECTION_STOP,
            field_wrong_layout,
        )
    )

    def field_second_difference() -> None:
        record = next(
            entry
            for entry in contract["field_corrections"]
            if entry["layout_id"] == "dark-cloud-search"
        )
        diagnose_field_corrections(
            "dark-cloud-search",
            {"screen_id": "dark_cloud_search", "screen_title": ""},
            {"screen_id": "wrong_second_field", "screen_title": "Dark Cloud Search"},
            copy.deepcopy(contract),
            record["landed_fixture"],
            record["candidate_fixture"],
        )

    cases.append(
        (
            "field_correction_family_rejects_second_field",
            "change screen_id alongside an exact title correction",
            FIELD_CORRECTION_STOP,
            field_second_difference,
        )
    )

    def field_authorization_disabled() -> None:
        mutated = copy.deepcopy(contract)
        mutated["field_corrections"] = []
        require_contract(mutated)

    cases.append(
        (
            "field_correction_family_rejects_disabled_authorization",
            "remove every exact field-correction authorization",
            FIELD_CORRECTION_STOP,
            field_authorization_disabled,
        )
    )

    def field_candidate_disagreement() -> None:
        record = next(
            entry
            for entry in contract["field_corrections"]
            if entry["layout_id"] == "hall-of-fame"
        )
        diagnose_field_corrections(
            "hall-of-fame",
            {"screen_title": ""},
            {"screen_title": "HALL OF FAME"},
            copy.deepcopy(contract),
            record["landed_fixture"],
            record["candidate_fixture"],
        )

    cases.append(
        (
            "field_correction_family_rejects_candidate_disagreement",
            "change the measured title away from its pin",
            FIELD_CORRECTION_STOP,
            field_candidate_disagreement,
        )
    )

    def stale_screen_id_reference() -> None:
        aggregate, navigation = minimal_corrected_references()
        navigation["edges"][0]["after"]["semantic_surface"] = "simple_menu"
        validate_dark_cloud_menu_references(aggregate, navigation)

    cases.append(
        (
            "screen_id_correction_rejects_stale_aggregate_reference",
            "leave one edge endpoint on simple_menu",
            STALE_SCREEN_ID_STOP,
            stale_screen_id_reference,
        )
    )

    def uncovered_guard() -> None:
        layout_id = "dark-cloud-options"
        landed_path = repo / f"tests/fixtures/webgame/menu-layouts/{layout_id}.json"
        candidate_path = candidate_root / f"menu-layouts/{layout_id}.json"
        diagnose_landed_layout(
            layout_id,
            read_object(landed_path)["layout"],
            read_object(candidate_path)["layout"],
            read_object(candidate_root / f"menu-settlement-traces/{layout_id}.settlement.json"),
            read_object(candidate_root / f"menu-animation-confirmations/{layout_id}.confirmation.json"),
            copy.deepcopy(overlay_reference),
            landed_fixture_receipt=file_receipt(landed_path),
            candidate_fixture_receipt=file_receipt(candidate_path),
            browser_chrome_supersession_contract=read_object(
                repo
                / "tests/fixtures/webgame/native-menu-dark-cloud-browser-chrome-supersession-v219.json"
            ),
        )

    cases.append(
        (
            "pattern_residual_without_census_coverage_trips_original_guard",
            "run a chrome-shaped residual without its census-era record",
            UNCOVERED_CHROME_GUARD,
            uncovered_guard,
        )
    )

    def pause_nonidentical() -> None:
        outcomes = copy.deepcopy(
            contract["pause_menu_population_equivalence"]["candidate_bindings"]
        )
        outcomes[1]["unclassified_differences_sha256"] = "f" * 64
        validate_pause_equivalence(copy.deepcopy(contract), outcomes)

    cases.append(
        (
            "pause_population_routing_nonidentical_outcomes_stop",
            "perturb one routing outcome hash",
            PAUSE_EQUIVALENCE_STOP,
            pause_nonidentical,
        )
    )

    def all_classes_disabled() -> None:
        layout_id = "dark-cloud-login-settings"
        landed_path = repo / f"tests/fixtures/webgame/menu-layouts/{layout_id}.json"
        candidate_path = candidate_root / f"menu-layouts/{layout_id}.json"
        try:
            diagnose_landed_layout(
                layout_id,
                read_object(landed_path)["layout"],
                read_object(candidate_path)["layout"],
                read_object(candidate_root / f"menu-settlement-traces/{layout_id}.settlement.json"),
                read_object(candidate_root / f"menu-animation-confirmations/{layout_id}.confirmation.json"),
                copy.deepcopy(overlay_reference),
                dark_cloud_login_title_contract=read_object(
                    repo
                    / "tests/fixtures/webgame/native-menu-dark-cloud-login-title-v220.json"
                ),
                landed_fixture_receipt=file_receipt(landed_path),
                candidate_fixture_receipt=file_receipt(candidate_path),
            )
        except LandedDiagnosisError as error:
            raise LandedDiagnosisError(f"STOP: standalone {layout_id}: {error}") from error

    cases.append(
        (
            "all_census_classes_disabled_reproduce_original_first_stop",
            "run the original first layout with every v2.21 class disabled",
            ORIGINAL_FIRST_STOP,
            all_classes_disabled,
        )
    )

    for excluded_id in sorted(CHOICE_ROWS):
        def excluded_in_class_a(element_id: str = excluded_id) -> None:
            mutated = copy.deepcopy(contract)
            skill_record = record_by_layout(mutated, "class_a_records", "skill-picker")
            source = next(
                row
                for row in mutated["choice_slot_reconciliation"]["rows"]
                if row["element_id"] == element_id
            )
            skill_record["members"][0] = copy.deepcopy(source)
            require_contract(mutated)

        cases.append(
            (
                f"skill_picker_class_a_rejects_excluded_{excluded_id.rsplit('.', 1)[-1]}",
                f"put excluded row {excluded_id} into the skill-picker Class-A record",
                CLASS_A_OCCURRENCE_STOP,
                excluded_in_class_a,
            )
        )

    def choice_geometry_mutation() -> None:
        residual = expected_elements({"members": choice_rows})
        residual[0]["rect"][0] += 1
        consume_choice_slot_rows(
            "skill-picker",
            residual,
            copy.deepcopy(contract),
        )

    cases.append(
        (
            "choice_slot_reconciliation_rejects_mutated_geometry",
            "move one Skills.84 layer one pixel off its measured slot geometry",
            CHOICE_SLOT_STOP,
            choice_geometry_mutation,
        )
    )

    def choice_zero_qualified_presence() -> None:
        mutated = copy.deepcopy(contract)
        for occurrence in mutated["choice_slot_reconciliation"]["rows"][0][
            "qualified_occurrences"
        ]:
            occurrence["presence_sample_count"] = 0
        require_contract(mutated)

    cases.append(
        (
            "choice_slot_reconciliation_rejects_zero_qualified_presence",
            "erase every measured presence event for one choice row",
            CHOICE_SLOT_STOP,
            choice_zero_qualified_presence,
        )
    )

    def choice_exclusion_disabled() -> None:
        build(
            evidence,
            census_path,
            occurrence_path,
            class_f_path,
            choice_slot_exclusion_enabled=False,
        )

    cases.append(
        (
            "choice_slot_exclusion_disabled_reproduces_occurrence_refusal",
            "disable only the exact two-row v2.8 reconciliation",
            CHOICE_EXCLUSION_REFUSAL,
            choice_exclusion_disabled,
        )
    )

    rows: list[dict[str, Any]] = []
    for index, (name, edit, expected_error, trip) in enumerate(cases, start=1):
        before_cleared = clear_bytecode(repo)
        before = green()
        mutation_cleared = clear_bytecode(repo)
        actual_error: str | None = None
        try:
            trip()
        except (CensusEraV221Error, DerivationError, LandedDiagnosisError) as error:
            actual_error = str(error)
        if actual_error != expected_error:
            raise ValueError(
                f"v2.21 mutation {name} did not trip its named claim: "
                f"expected={expected_error!r} actual={actual_error!r}"
            )
        restore_cleared = clear_bytecode(repo)
        restored = green()
        stem = f"v221-{index:02d}-{name}"
        before_path = output / f"{stem}.green-before.json"
        trip_path = output / f"{stem}.trip.json"
        after_path = output / f"{stem}.green-after.json"
        atomic_json(
            before_path,
            {
                "case": name,
                "phase": "green_before",
                "bytecode_cleared": before_cleared,
                "baseline": before,
            },
        )
        atomic_json(
            trip_path,
            {
                "case": name,
                "phase": "trip",
                "edit": edit,
                "bytecode_cleared": mutation_cleared,
                "expected_error": expected_error,
                "actual_error": actual_error,
                "tripped_named_claim": True,
            },
        )
        atomic_json(
            after_path,
            {
                "case": name,
                "phase": "green_after_restore",
                "bytecode_cleared": restore_cleared,
                "baseline": restored,
            },
        )
        rows.append(
            {
                "case": name,
                "edit": edit,
                "green_before": before_path.name,
                "trip": trip_path.name,
                "green_after": after_path.name,
                "actual_error": actual_error,
                "passed": True,
            }
        )

    result = {
        "schema": "solomon-dark-native-menu-v221-mutation-table-v1",
        "settlement_spec": "2.21",
        "contract": file_receipt(contract_path),
        "source_census": file_receipt(census_path),
        "occurrence_audit": file_receipt(occurrence_path),
        "class_f_audit": file_receipt(class_f_path),
        "row_count": len(rows),
        "all_passed": all(row["passed"] for row in rows),
        "rows": rows,
    }
    atomic_json(output / "v221-mutation-table.json", result)
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
