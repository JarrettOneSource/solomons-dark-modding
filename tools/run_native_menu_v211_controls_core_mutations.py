#!/usr/bin/env python3
"""Mutation-test the exact Controls-only v2.11 structural supersession."""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
from pathlib import Path
from typing import Any, Callable

from native_menu_landed_diagnosis_v25 import (
    LandedDiagnosisError,
    V211_STRUCTURAL_MISMATCH,
    V211_WRONG_LAYOUT,
    diagnose_landed_layout,
)
from promote_native_menu_recapture import file_receipt, read_json


def write_object(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def clear_contract_bytecode(repo: Path) -> list[str]:
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
    output_directory = args.output_directory.resolve()
    contract = read_json(
        repo / "tests/fixtures/webgame/native-menu-controls-core-v211.json"
    )
    title_contract = read_json(
        repo / "tests/fixtures/webgame/native-menu-controls-title-v210.json"
    )
    landed_path = (
        repo
        / "webgame-contracts/baseline-snapshots/menu-layouts/controls.json"
    )
    candidate_path = candidate_root / "menu-layouts/controls.json"
    landed = read_json(landed_path)["layout"]
    candidate = read_json(candidate_path)["layout"]
    recorded_landed = contract["superseded_landed_fixture"]
    landed_receipt = {
        "sha256": recorded_landed["sha256"],
        "bytes": recorded_landed["bytes"],
    }
    candidate_receipt = file_receipt(candidate_path)

    def diagnose(
        layout: dict[str, Any], layout_id: str = "controls"
    ) -> dict[str, Any]:
        return diagnose_landed_layout(
            layout_id,
            copy.deepcopy(landed),
            layout,
            {},
            {},
            {},
            controls_title_contract=title_contract,
            controls_core_contract=contract,
            landed_fixture_receipt=landed_receipt,
            candidate_fixture_receipt=candidate_receipt,
        )

    def green() -> dict[str, Any]:
        result = diagnose(copy.deepcopy(candidate))
        correction = result.get("structural_core_supersession")
        if (
            result.get("status") != "corrected"
            or not isinstance(correction, dict)
            or correction.get("layout_id") != "controls"
            or correction.get("general_tolerance") is not False
        ):
            raise ValueError(
                "v2.11 green baseline did not exercise the exact Controls supersession"
            )
        return {
            "status": result["status"],
            "structural_core_supersession": copy.deepcopy(correction),
        }

    def retain_exact(_: dict[str, Any]) -> None:
        return

    def drop_one(layout: dict[str, Any]) -> None:
        layout["elements"].pop()

    def mutate_one(layout: dict[str, Any]) -> None:
        layout["elements"][0]["rect"][0] += 1

    def add_one(layout: dict[str, Any]) -> None:
        extra = copy.deepcopy(layout["elements"][0])
        extra["id"] = "controls.v211.unreviewed_extra"
        layout["elements"].append(extra)

    def claim_wrong_layout(layout: dict[str, Any]) -> None:
        layout["screen_title"] = ""

    cases: list[
        tuple[
            str,
            str,
            str,
            Callable[[dict[str, Any]], None],
            str | None,
        ]
    ] = [
        (
            "exact_55_member_core_positive",
            "retain the byte-pinned candidate core",
            "controls",
            retain_exact,
            None,
        ),
        (
            "drop_one_core_member",
            "remove one member from the authorized semantic multiset",
            "controls",
            drop_one,
            V211_STRUCTURAL_MISMATCH,
        ),
        (
            "mutate_one_core_rect",
            "move one member rect by one pixel",
            "controls",
            mutate_one,
            V211_STRUCTURAL_MISMATCH,
        ),
        (
            "add_one_core_member",
            "append one unreviewed semantic member",
            "controls",
            add_one,
            V211_STRUCTURAL_MISMATCH,
        ),
        (
            "wrong_layout_claim",
            "claim the exact Controls supersession for another layout",
            "control-scheme-picker",
            claim_wrong_layout,
            V211_WRONG_LAYOUT,
        ),
    ]

    summaries: list[dict[str, Any]] = []
    for name, mutation, layout_id, apply_mutation, expected_error in cases:
        cleared_before_baseline = clear_contract_bytecode(repo)
        before = green()
        scratch = copy.deepcopy(candidate)
        apply_mutation(scratch)
        cleared_before_mutation = clear_contract_bytecode(repo)
        actual_error: str | None = None
        mutated_result: dict[str, Any] | None = None
        try:
            result = diagnose(scratch, layout_id)
            mutated_result = {
                "status": result.get("status"),
                "structural_core_supersession": copy.deepcopy(
                    result.get("structural_core_supersession")
                ),
            }
        except LandedDiagnosisError as error:
            actual_error = str(error)
        if expected_error is None:
            if actual_error is not None or mutated_result is None:
                raise ValueError(
                    f"v2.11 positive case {name} did not pass: {actual_error}"
                )
        elif actual_error != expected_error:
            raise ValueError(
                f"v2.11 mutation {name} did not trip its named claim: "
                f"expected={expected_error!r} actual={actual_error!r}"
            )
        cleared_before_restore = clear_contract_bytecode(repo)
        restored = green()
        transcript = {
            "schema": "solomon-dark-native-menu-v211-mutation-transcript-v1",
            "case": name,
            "mutation": mutation,
            "layout_id": layout_id,
            "bytecode_cleared_before_green_baseline": cleared_before_baseline,
            "green_baseline": before,
            "bytecode_cleared_before_mutation": cleared_before_mutation,
            "expected_trip_message": expected_error,
            "actual_trip_message": actual_error,
            "mutated_positive_result": mutated_result,
            "bytecode_cleared_before_restored_green": cleared_before_restore,
            "restored_green": restored,
            "passed": True,
        }
        transcript_path = output_directory / f"v211-{name}.json"
        write_object(transcript_path, transcript)
        summaries.append(
            {"case": name, "transcript": transcript_path.name, "passed": True}
        )

    table = {
        "schema": "solomon-dark-native-menu-v211-mutation-table-v1",
        "case_count": len(summaries),
        "all_passed": all(value["passed"] for value in summaries),
        "cases": summaries,
    }
    write_object(output_directory / "v211-mutation-table.json", table)
    print(json.dumps(table, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
