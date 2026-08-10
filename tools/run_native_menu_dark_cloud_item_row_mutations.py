#!/usr/bin/env python3
"""Mutation-test the exact Dark Cloud public-tab Item 1 supersession."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, Callable

from native_menu_dark_cloud_item_row_supersession import (
    CONTROL_LAYOUT,
    CONTROL_ROW_STOP,
    EXACT_MEMBER_STOP,
    WRONG_SCOPE_STOP,
    DarkCloudItemRowSupersessionError,
    consume_exact_landed_residual,
    validate_control_layout,
)
from native_menu_landed_diagnosis_v25 import (
    LandedDiagnosisError,
    diagnose_landed_layout,
)


DISABLED_STOP = (
    "landed-vs-settled mismatch survives ambient, population, overlay, and "
    "animation diagnosis: 'dark_cloud_browser.text.item_1.1' / 'Item 1'"
)


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} is not a JSON object")
    return value


def file_receipt(path: Path) -> dict[str, Any]:
    return {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size,
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


def clear_bytecode(repo: Path) -> list[str]:
    cleared: list[str] = []
    for relative in (
        "tests/__pycache__",
        "tests/re/__pycache__",
        "tools/__pycache__",
    ):
        directory = repo / relative
        if directory.is_dir():
            shutil.rmtree(directory)
        cleared.append(relative)
    return cleared


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = args.repo_root.resolve()
    candidate_root = args.candidate_root.resolve()
    output = args.output_directory.resolve()
    contract = read_object(
        repo
        / "tests/fixtures/webgame/native-menu-dark-cloud-item-row-supersession-v219.json"
    )
    overlay = read_object(candidate_root / "menu-overlay-reference.json")

    browser_landed_path = (
        repo
        / "webgame-contracts/baseline-snapshots/menu-layouts/dark-cloud-browser.json"
    )
    browser_candidate_path = (
        candidate_root / "menu-layouts/dark-cloud-browser.json"
    )
    browser_landed = read_object(browser_landed_path)["layout"]
    browser_candidate = read_object(browser_candidate_path)["layout"]
    primary_trace = read_object(
        candidate_root
        / "menu-settlement-traces/dark-cloud-browser.settlement.json"
    )
    confirmation_trace = read_object(
        candidate_root
        / "menu-animation-confirmations/dark-cloud-browser.confirmation.json"
    )
    browser_landed_receipt = file_receipt(browser_landed_path)
    browser_candidate_receipt = file_receipt(browser_candidate_path)
    browser_entry = next(
        entry
        for entry in contract["affected_layouts"]
        if entry["layout_id"] == "dark-cloud-browser"
    )
    exact_row = copy.deepcopy(browser_entry["superseded_member"]["payload"])

    my_levels_path = candidate_root / "menu-layouts/dark-cloud-my-levels.json"
    my_levels = read_object(my_levels_path)["layout"]
    my_levels_receipt = file_receipt(my_levels_path)

    def green() -> dict[str, Any]:
        disposition, remaining = consume_exact_landed_residual(
            "dark-cloud-browser",
            copy.deepcopy(browser_landed),
            copy.deepcopy(browser_candidate),
            [copy.deepcopy(exact_row)],
            contract,
            browser_landed_receipt,
            browser_candidate_receipt,
        )
        validate_control_layout(
            CONTROL_LAYOUT,
            copy.deepcopy(my_levels),
            contract,
            my_levels_receipt,
        )
        if (
            not isinstance(disposition, dict)
            or disposition.get("member_id") != exact_row["id"]
            or disposition.get("candidate_member_removed") is not False
            or remaining
        ):
            raise ValueError(
                "Item 1 green baseline did not exercise the exact landed-only supersession"
            )
        return {
            "status": "accepted_exact_landed_only_member",
            "layout_id": disposition["layout_id"],
            "member_id": disposition["member_id"],
            "candidate_member_removed": disposition["candidate_member_removed"],
            "my_levels_positive_control": "retained",
        }

    def disabled_authorization() -> str | None:
        try:
            diagnose_landed_layout(
                "dark-cloud-browser",
                copy.deepcopy(browser_landed),
                copy.deepcopy(browser_candidate),
                primary_trace,
                confirmation_trace,
                overlay,
                landed_fixture_receipt=browser_landed_receipt,
                candidate_fixture_receipt=browser_candidate_receipt,
            )
        except LandedDiagnosisError as error:
            return str(error)
        return None

    def second_unclassified_member() -> str | None:
        mutated = copy.deepcopy(browser_landed)
        extra = copy.deepcopy(exact_row)
        extra["id"] = "dark_cloud_browser.text.unreviewed_second_member.1"
        extra["text"] = "Unreviewed second member"
        mutated["elements"].append(extra)
        try:
            diagnose_landed_layout(
                "dark-cloud-browser",
                mutated,
                copy.deepcopy(browser_candidate),
                primary_trace,
                confirmation_trace,
                overlay,
                landed_fixture_receipt=browser_landed_receipt,
                candidate_fixture_receipt=browser_candidate_receipt,
                item_row_supersession_contract=contract,
            )
        except LandedDiagnosisError as error:
            return str(error)
        return None

    def remove_my_levels_row() -> str | None:
        mutated = copy.deepcopy(my_levels)
        mutated["elements"] = [
            element
            for element in mutated["elements"]
            if element.get("id") != "dark_cloud_my_levels.text.item_1.1"
        ]
        try:
            validate_control_layout(
                CONTROL_LAYOUT,
                mutated,
                contract,
                my_levels_receipt,
            )
        except DarkCloudItemRowSupersessionError as error:
            return str(error)
        return None

    def fresh_public_row_is_not_filtered() -> dict[str, Any]:
        mutated = copy.deepcopy(browser_candidate)
        mutated["elements"].append(copy.deepcopy(exact_row))
        before = copy.deepcopy(mutated)
        disposition, remaining = consume_exact_landed_residual(
            "dark-cloud-browser",
            copy.deepcopy(browser_landed),
            mutated,
            [],
            contract,
            browser_landed_receipt,
            browser_candidate_receipt,
        )
        if disposition is not None or remaining or mutated != before:
            raise ValueError(
                "Item 1 evidence-of-era record filtered a fresh settled candidate"
            )
        return {
            "status": "accepted_without_supersession",
            "candidate_item_row_count": sum(
                element.get("text") == "Item 1" for element in mutated["elements"]
            ),
            "candidate_unchanged": True,
        }

    def wrong_layout_scope() -> str | None:
        try:
            consume_exact_landed_residual(
                "dark-cloud-options",
                copy.deepcopy(browser_landed),
                copy.deepcopy(browser_candidate),
                [copy.deepcopy(exact_row)],
                contract,
                browser_landed_receipt,
                browser_candidate_receipt,
            )
        except DarkCloudItemRowSupersessionError as error:
            return str(error)
        return None

    cases: list[
        tuple[str, str, Callable[[], str | dict[str, Any] | None], str | None]
    ] = [
        (
            "authorization_disabled_reproduces_exact_stop",
            "disable the exact evidence-of-era record",
            disabled_authorization,
            DISABLED_STOP,
        ),
        (
            "second_unclassified_member_stops",
            "append a different surviving member beside the named Item 1 row",
            second_unclassified_member,
            EXACT_MEMBER_STOP,
        ),
        (
            "my_levels_positive_control_cannot_be_removed",
            "remove the reproduced My Levels Item 1 member",
            remove_my_levels_row,
            CONTROL_ROW_STOP,
        ),
        (
            "fresh_public_item_row_is_never_filtered",
            "present a fresh settled public-tab candidate containing Item 1",
            fresh_public_row_is_not_filtered,
            None,
        ),
        (
            "same_member_pattern_on_other_layout_stops",
            "claim the same member pattern on another layout",
            wrong_layout_scope,
            WRONG_SCOPE_STOP,
        ),
    ]
    expected_cases = {
        "authorization_disabled_reproduces_exact_stop",
        "second_unclassified_member_stops",
        "my_levels_positive_control_cannot_be_removed",
        "fresh_public_item_row_is_never_filtered",
        "same_member_pattern_on_other_layout_stops",
    }
    if {case[0] for case in cases} != expected_cases:
        raise ValueError("Item 1 mutation fleet lost a required claim witness")

    summaries: list[dict[str, Any]] = []
    for name, mutation, run_mutation, expected_error in cases:
        baseline_cleared = clear_bytecode(repo)
        baseline = green()
        mutation_cleared = clear_bytecode(repo)
        result = run_mutation()
        actual_error = result if isinstance(result, str) else None
        positive_result = result if isinstance(result, dict) else None
        if expected_error is None:
            if actual_error is not None or positive_result is None:
                raise ValueError(
                    f"Item 1 positive mutation {name} did not pass: {actual_error}"
                )
        elif actual_error != expected_error:
            raise ValueError(
                f"Item 1 mutation {name} did not trip its named claim: "
                f"expected={expected_error!r} actual={actual_error!r}"
            )
        restore_cleared = clear_bytecode(repo)
        restored = green()
        transcript = {
            "schema": "solomon-dark-native-menu-item-row-mutation-transcript-v1",
            "case": name,
            "mutation": mutation,
            "bytecode_cleared_before_green_baseline": baseline_cleared,
            "green_baseline": baseline,
            "bytecode_cleared_before_mutation": mutation_cleared,
            "expected_trip_message": expected_error,
            "actual_trip_message": actual_error,
            "positive_result": positive_result,
            "bytecode_cleared_before_restored_green": restore_cleared,
            "restored_green": restored,
            "passed": True,
        }
        transcript_path = output / f"item-row-{name}.json"
        write_object(transcript_path, transcript)
        summaries.append(
            {"case": name, "transcript": transcript_path.name, "passed": True}
        )

    table = {
        "schema": "solomon-dark-native-menu-item-row-mutation-table-v1",
        "case_count": len(summaries),
        "all_passed": all(summary["passed"] for summary in summaries),
        "cases": summaries,
    }
    if table["case_count"] != len(expected_cases):
        raise ValueError("Item 1 mutation table did not exercise all five claims")
    write_object(output / "item-row-mutation-table.json", table)
    print(json.dumps(table, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
