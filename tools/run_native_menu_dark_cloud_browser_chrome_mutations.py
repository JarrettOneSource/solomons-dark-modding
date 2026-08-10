#!/usr/bin/env python3
"""Mutation-test the exact four-layout Dark Cloud browser-chrome record."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, Callable

from native_menu_dark_cloud_browser_chrome_supersession import (
    EXACT_RESIDUAL_STOP,
    FRESH_MEMBER_STOP,
    WRONG_SCOPE_STOP,
    DarkCloudBrowserChromeSupersessionError,
    consume_exact_landed_residual,
)
from native_menu_landed_diagnosis_v25 import LandedDiagnosisError, diagnose_landed_layout


DISABLED_STOP = (
    "landed-vs-settled mismatch survives ambient, population, overlay, and "
    "animation diagnosis: 'dark_cloud_browser.art.ui_107.1' / 'UI.107'"
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo_root.resolve()
    candidate = args.candidate_root.resolve()
    output = args.output_directory.resolve()
    contract = read_object(
        repo
        / "tests/fixtures/webgame/native-menu-dark-cloud-browser-chrome-supersession-v219.json"
    )
    item_contract = read_object(
        repo
        / "tests/fixtures/webgame/native-menu-dark-cloud-item-row-supersession-v219.json"
    )
    overlay = read_object(candidate / "menu-overlay-reference.json")
    landed_path = (
        repo
        / "webgame-contracts/baseline-snapshots/menu-layouts/dark-cloud-browser.json"
    )
    candidate_path = candidate / "menu-layouts/dark-cloud-browser.json"
    landed = read_object(landed_path)["layout"]
    settled = read_object(candidate_path)["layout"]
    primary = read_object(
        candidate / "menu-settlement-traces/dark-cloud-browser.settlement.json"
    )
    confirmation = read_object(
        candidate
        / "menu-animation-confirmations/dark-cloud-browser.confirmation.json"
    )
    landed_receipt = file_receipt(landed_path)
    candidate_receipt = file_receipt(candidate_path)
    entry = next(
        value
        for value in contract["affected_layouts"]
        if value["layout_id"] == "dark-cloud-browser"
    )
    exact_residual = [
        copy.deepcopy(member["payload"]) for member in entry["residual_members"]
    ]

    def green() -> dict[str, Any]:
        diagnosis = diagnose_landed_layout(
            "dark-cloud-browser",
            copy.deepcopy(landed),
            copy.deepcopy(settled),
            primary,
            confirmation,
            overlay,
            landed_fixture_receipt=landed_receipt,
            candidate_fixture_receipt=candidate_receipt,
            item_row_supersession_contract=item_contract,
            browser_chrome_supersession_contract=contract,
        )
        disposition = diagnosis.get("dark_cloud_browser_chrome_supersession")
        if (
            diagnosis.get("status") != "corrected"
            or not isinstance(disposition, dict)
            or disposition.get("residual_count") != 28
            or disposition.get("candidate_member_removed") is not False
            or disposition.get("v2_4_overlay_gate_unchanged") is not True
        ):
            raise ValueError("browser-chrome green baseline missed the exact record")
        return {
            "status": diagnosis["status"],
            "layout_id": disposition["layout_id"],
            "residual_count": disposition["residual_count"],
            "candidate_member_removed": disposition["candidate_member_removed"],
            "v2_4_overlay_gate_unchanged": disposition[
                "v2_4_overlay_gate_unchanged"
            ],
        }

    def authorization_disabled() -> str | None:
        try:
            diagnose_landed_layout(
                "dark-cloud-browser",
                copy.deepcopy(landed),
                copy.deepcopy(settled),
                primary,
                confirmation,
                overlay,
                landed_fixture_receipt=landed_receipt,
                candidate_fixture_receipt=candidate_receipt,
                item_row_supersession_contract=item_contract,
            )
        except LandedDiagnosisError as error:
            return str(error)
        return None

    def residual_29() -> str | None:
        mutated = copy.deepcopy(exact_residual)
        extra = copy.deepcopy(mutated[-1])
        extra["id"] = "dark_cloud_browser.art.unreviewed_29th.1"
        extra["art_id"] = "Unreviewed.29"
        mutated.append(extra)
        try:
            consume_exact_landed_residual(
                "dark-cloud-browser",
                copy.deepcopy(landed),
                copy.deepcopy(settled),
                mutated,
                contract,
                landed_receipt,
                candidate_receipt,
            )
        except DarkCloudBrowserChromeSupersessionError as error:
            return str(error)
        return None

    def residual_27() -> str | None:
        try:
            consume_exact_landed_residual(
                "dark-cloud-browser",
                copy.deepcopy(landed),
                copy.deepcopy(settled),
                copy.deepcopy(exact_residual[:-1]),
                contract,
                landed_receipt,
                candidate_receipt,
            )
        except DarkCloudBrowserChromeSupersessionError as error:
            return str(error)
        return None

    def fresh_member_is_not_stripped() -> str | None:
        mutated_settled = copy.deepcopy(settled)
        mutated_settled["elements"].append(copy.deepcopy(exact_residual[0]))
        before = copy.deepcopy(mutated_settled)
        try:
            consume_exact_landed_residual(
                "dark-cloud-browser",
                copy.deepcopy(landed),
                mutated_settled,
                copy.deepcopy(exact_residual),
                contract,
                landed_receipt,
                candidate_receipt,
            )
        except DarkCloudBrowserChromeSupersessionError as error:
            if mutated_settled != before:
                raise ValueError("browser-chrome record modified a fresh candidate")
            return str(error)
        return None

    def wrong_layout() -> str | None:
        try:
            consume_exact_landed_residual(
                "dark-cloud-options",
                copy.deepcopy(landed),
                copy.deepcopy(settled),
                copy.deepcopy(exact_residual),
                contract,
                landed_receipt,
                candidate_receipt,
            )
        except DarkCloudBrowserChromeSupersessionError as error:
            return str(error)
        return None

    cases: list[tuple[str, str, Callable[[], str | None], str]] = [
        (
            "authorization_disabled_reproduces_exact_ui107_stop",
            "disable the exact four-layout era record",
            authorization_disabled,
            DISABLED_STOP,
        ),
        (
            "synthetic_29th_residual_member_stops",
            "append one unreviewed residual member",
            residual_29,
            EXACT_RESIDUAL_STOP,
        ),
        (
            "missing_pinned_member_27_residual_stops",
            "remove one pinned residual member",
            residual_27,
            EXACT_RESIDUAL_STOP,
        ),
        (
            "fresh_settled_member_is_never_stripped",
            "present one pinned member in a fresh settled candidate",
            fresh_member_is_not_stripped,
            FRESH_MEMBER_STOP,
        ),
        (
            "identical_multiset_on_other_layout_stops",
            "present the exact 28-member multiset on another layout",
            wrong_layout,
            WRONG_SCOPE_STOP,
        ),
    ]
    expected_names = {
        "authorization_disabled_reproduces_exact_ui107_stop",
        "synthetic_29th_residual_member_stops",
        "missing_pinned_member_27_residual_stops",
        "fresh_settled_member_is_never_stripped",
        "identical_multiset_on_other_layout_stops",
    }
    if {name for name, *_ in cases} != expected_names:
        raise ValueError("browser-chrome mutation fleet lost a required witness")

    summaries: list[dict[str, Any]] = []
    for name, mutation, mutate, expected in cases:
        baseline_cleared = clear_bytecode(repo)
        baseline = green()
        mutation_cleared = clear_bytecode(repo)
        actual = mutate()
        if actual != expected:
            raise ValueError(
                f"browser-chrome mutation {name} missed its named claim: "
                f"expected={expected!r} actual={actual!r}"
            )
        restore_cleared = clear_bytecode(repo)
        restored = green()
        transcript = {
            "schema": "solomon-dark-native-menu-browser-chrome-mutation-transcript-v1",
            "case": name,
            "mutation": mutation,
            "bytecode_cleared_before_green_baseline": baseline_cleared,
            "green_baseline": baseline,
            "bytecode_cleared_before_mutation": mutation_cleared,
            "expected_trip_message": expected,
            "actual_trip_message": actual,
            "bytecode_cleared_before_restored_green": restore_cleared,
            "restored_green": restored,
            "passed": True,
        }
        transcript_path = output / f"browser-chrome-{name}.json"
        write_object(transcript_path, transcript)
        summaries.append(
            {"case": name, "transcript": transcript_path.name, "passed": True}
        )
    table = {
        "schema": "solomon-dark-native-menu-browser-chrome-mutation-table-v1",
        "case_count": len(summaries),
        "all_passed": all(summary["passed"] for summary in summaries),
        "cases": summaries,
    }
    if table["case_count"] != len(expected_names):
        raise ValueError("browser-chrome mutation table missed a required case")
    write_object(output / "browser-chrome-mutation-table.json", table)
    print(json.dumps(table, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
