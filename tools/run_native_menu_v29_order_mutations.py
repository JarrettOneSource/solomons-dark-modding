#!/usr/bin/env python3
"""Run the bounded v2.9 beta-notice mutation table on real campaign data."""

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
    diagnose_landed_layout,
)
from promote_native_menu_recapture import (
    read_json,
    validate_settlement_fixture_v25,
)


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
    for relative in ("tests/__pycache__", "tests/re/__pycache__", "tools/__pycache__"):
        directory = repo / relative
        if directory.is_dir():
            shutil.rmtree(directory)
        cleared.append(relative)
    return cleared


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = args.repo_root.resolve()
    candidate_root = args.candidate_root.resolve()
    evidence_root = args.evidence_root.resolve()
    output_directory = args.output_directory.resolve()
    fixture_path = candidate_root / "menu-layouts/beta-notice.json"
    record = validate_settlement_fixture_v25(
        repo, evidence_root, fixture_path, read_json(fixture_path)
    )
    landed_golden = read_json(repo / "tests/fixtures/webgame/menu-goldens.json")
    landed_matches = [
        entry
        for entry in landed_golden.get("layouts", [])
        if isinstance(entry, dict)
        and Path(str(entry.get("fixture", ""))).stem == "beta-notice"
    ]
    if len(landed_matches) != 1:
        raise ValueError("v2.9 mutation runner found an ambiguous landed beta-notice")
    landed = landed_matches[0].get("layout")
    if not isinstance(landed, dict):
        raise ValueError("v2.9 mutation runner found no landed beta-notice layout")
    overlay = read_json(candidate_root / "menu-overlay-reference.json")
    contract = read_json(
        repo / "tests/fixtures/webgame/native-menu-beta-notice-order-v29.json"
    )
    baseline = record["layout"]

    def diagnose(layout: dict[str, Any]) -> dict[str, Any]:
        result = diagnose_landed_layout(
            "beta-notice",
            landed,
            layout,
            record["primary_trace"],
            record["confirmation_trace"],
            overlay,
            contract,
        )
        correction = result.get("core_order_correction")
        if result.get("status") != "corrected" or not isinstance(correction, dict):
            raise ValueError("v2.9 mutation green baseline did not exercise the correction")
        return {
            "status": result["status"],
            "core_member_count": correction.get("core_member_count"),
            "longest_common_subsequence_count": correction.get(
                "longest_common_subsequence_count"
            ),
            "moved_semantic_sha256": [
                member.get("semantic_sha256")
                for member in correction.get("moved_members", [])
                if isinstance(member, dict)
            ],
        }

    def swap_non_exempt(layout: dict[str, Any]) -> None:
        layout["elements"][0], layout["elements"][1] = (
            layout["elements"][1],
            layout["elements"][0],
        )

    def exact_positive(_: dict[str, Any]) -> None:
        return

    def drop_trio_member(layout: dict[str, Any]) -> None:
        layout["elements"].pop()

    def mutate_trio_rect(layout: dict[str, Any]) -> None:
        layout["elements"][-1]["rect"][0] += 1.0

    def move_trio_to_middle(layout: dict[str, Any]) -> None:
        trio = layout["elements"][-3:]
        del layout["elements"][-3:]
        layout["elements"][20:20] = trio

    cases: list[
        tuple[str, str, Callable[[dict[str, Any]], None], str | None]
    ] = [
        (
            "non_exempt_core_reorder",
            "swap the first two non-exempt settled core members",
            swap_non_exempt,
            "v2.9 beta-notice paint-order correction: a non-exempt core member moved",
        ),
        (
            "exact_exempt_trio_positive",
            "retain the measured exempt trio at the final three core positions",
            exact_positive,
            None,
        ),
        (
            "drop_exempt_trio_member",
            "drop one exempt trio member from the settled core",
            drop_trio_member,
            "v2.9 beta-notice paint-order correction: exact core set identity failed",
        ),
        (
            "mutate_exempt_trio_rect",
            "move one exempt member rectangle by one pixel",
            mutate_trio_rect,
            "v2.9 beta-notice paint-order correction: exact core set identity failed",
        ),
        (
            "place_exempt_trio_at_middle_positions",
            "move the exempt trio from final positions to positions 20-22",
            move_trio_to_middle,
            "v2.9 beta-notice paint-order correction: bounded landed-to-settled positions differ",
        ),
    ]
    summary: list[dict[str, Any]] = []
    for name, mutation, apply_mutation, expected_error in cases:
        cleared_before_baseline = clear_contract_bytecode(repo)
        before = diagnose(copy.deepcopy(baseline))
        scratch = copy.deepcopy(baseline)
        apply_mutation(scratch)
        cleared_before_mutation = clear_contract_bytecode(repo)
        actual_error: str | None = None
        mutated_result: dict[str, Any] | None = None
        try:
            mutated_result = diagnose(scratch)
        except LandedDiagnosisError as error:
            actual_error = str(error)
        if expected_error is None:
            if actual_error is not None or mutated_result is None:
                raise ValueError(
                    f"v2.9 positive case {name} did not pass: {actual_error}"
                )
        elif actual_error != expected_error:
            raise ValueError(
                f"v2.9 mutation {name} did not trip its named claim: "
                f"expected={expected_error!r} actual={actual_error!r}"
            )
        cleared_before_restore = clear_contract_bytecode(repo)
        restored = diagnose(copy.deepcopy(baseline))
        transcript = {
            "schema": "solomon-dark-native-menu-v29-mutation-transcript-v1",
            "case": name,
            "mutation": mutation,
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
        transcript_path = output_directory / f"v29-{name}.json"
        write_object(transcript_path, transcript)
        summary.append(
            {
                "case": name,
                "transcript": transcript_path.name,
                "passed": True,
            }
        )
    result = {
        "schema": "solomon-dark-native-menu-v29-mutation-table-v1",
        "case_count": len(summary),
        "all_passed": all(entry["passed"] for entry in summary),
        "cases": summary,
    }
    write_object(output_directory / "v29-mutation-table.json", result)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
