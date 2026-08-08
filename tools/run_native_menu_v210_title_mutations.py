#!/usr/bin/env python3
"""Run the bounded v2.10 Controls-title mutation table on campaign data."""

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
    file_receipt,
    read_json,
    validate_settlement_fixture_v25,
)


TITLE_MISMATCH = (
    "landed-vs-settled mismatch outside authorized classes: layout field "
    "'screen_title' differs"
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
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    return parser.parse_args()


def unique_landed_layout(
    aggregate: dict[str, Any], layout_id: str
) -> dict[str, Any]:
    matches = [
        entry
        for entry in aggregate.get("layouts", [])
        if isinstance(entry, dict)
        and Path(str(entry.get("fixture", ""))).stem == layout_id
    ]
    if len(matches) != 1:
        raise ValueError(
            f"v2.10 mutation runner found {len(matches)} landed {layout_id!r} layouts"
        )
    layout = matches[0].get("layout")
    if not isinstance(layout, dict):
        raise ValueError(
            f"v2.10 mutation runner found no landed {layout_id!r} layout payload"
        )
    return layout


def main() -> int:
    args = parse_args()
    repo = args.repo_root.resolve()
    candidate_root = args.candidate_root.resolve()
    evidence_root = args.evidence_root.resolve()
    output_directory = args.output_directory.resolve()
    aggregate = read_json(repo / "tests/fixtures/webgame/menu-goldens.json")
    overlay = read_json(candidate_root / "menu-overlay-reference.json")
    order_contract = read_json(
        repo / "tests/fixtures/webgame/native-menu-beta-notice-order-v29.json"
    )
    title_contract = read_json(
        repo / "tests/fixtures/webgame/native-menu-controls-title-v210.json"
    )
    core_contract = read_json(
        repo / "tests/fixtures/webgame/native-menu-controls-core-v211.json"
    )

    records: dict[str, dict[str, Any]] = {}
    landed: dict[str, dict[str, Any]] = {}
    candidate_paths: dict[str, Path] = {}
    for layout_id in ("controls", "control-scheme-picker"):
        fixture_path = candidate_root / "menu-layouts" / f"{layout_id}.json"
        candidate_paths[layout_id] = fixture_path
        records[layout_id] = validate_settlement_fixture_v25(
            repo,
            evidence_root,
            fixture_path,
            read_json(fixture_path),
        )
        landed[layout_id] = unique_landed_layout(aggregate, layout_id)

    def diagnose(layout_id: str, layout: dict[str, Any]) -> dict[str, Any]:
        record = records[layout_id]
        return diagnose_landed_layout(
            layout_id,
            landed[layout_id],
            layout,
            record["primary_trace"],
            record["confirmation_trace"],
            overlay,
            order_contract,
            title_contract,
            core_contract,
            file_receipt(
                repo
                / "tests/fixtures/webgame/menu-layouts"
                / f"{layout_id}.json"
            ),
            file_receipt(candidate_paths[layout_id]),
        )

    def controls_green() -> dict[str, Any]:
        result = diagnose("controls", copy.deepcopy(records["controls"]["layout"]))
        correction = result.get("screen_title_correction")
        if (
            result.get("status") != "corrected"
            or not isinstance(correction, dict)
            or correction.get("layout_id") != "controls"
            or correction.get("old_value") != ""
            or correction.get("new_value") != "Wizard Controls"
        ):
            raise ValueError(
                "v2.10 green baseline did not exercise the exact Controls title correction"
            )
        return {
            "status": result["status"],
            "screen_title_correction": copy.deepcopy(correction),
        }

    def other_layout_green() -> dict[str, Any]:
        result = diagnose(
            "control-scheme-picker",
            copy.deepcopy(records["control-scheme-picker"]["layout"]),
        )
        return {
            "status": result.get("status"),
            "screen_title_correction": result.get("screen_title_correction"),
        }

    def exact_controls(_: dict[str, Any]) -> None:
        return

    def case_variant(layout: dict[str, Any]) -> None:
        layout["screen_title"] = "WIZARD CONTROLS"

    def other_layout_title(layout: dict[str, Any]) -> None:
        layout["screen_title"] = "Changed title outside Controls"

    cases: list[
        tuple[
            str,
            str,
            str,
            Callable[[], dict[str, Any]],
            Callable[[dict[str, Any]], None],
            str | None,
        ]
    ] = [
        (
            "exact_controls_title_positive",
            "retain the measured case-sensitive Controls title",
            "controls",
            controls_green,
            exact_controls,
            None,
        ),
        (
            "controls_title_case_variant",
            "replace the measured title with WIZARD CONTROLS",
            "controls",
            controls_green,
            case_variant,
            TITLE_MISMATCH,
        ),
        (
            "other_layout_title_change",
            "change the control-scheme-picker title outside Controls",
            "control-scheme-picker",
            other_layout_green,
            other_layout_title,
            TITLE_MISMATCH,
        ),
    ]

    summary: list[dict[str, Any]] = []
    for (
        name,
        mutation,
        layout_id,
        green,
        apply_mutation,
        expected_error,
    ) in cases:
        cleared_before_baseline = clear_contract_bytecode(repo)
        before = green()
        scratch = copy.deepcopy(records[layout_id]["layout"])
        apply_mutation(scratch)
        cleared_before_mutation = clear_contract_bytecode(repo)
        actual_error: str | None = None
        mutated_result: dict[str, Any] | None = None
        try:
            result = diagnose(layout_id, scratch)
            mutated_result = {
                "status": result.get("status"),
                "screen_title_correction": copy.deepcopy(
                    result.get("screen_title_correction")
                ),
            }
        except LandedDiagnosisError as error:
            actual_error = str(error)
        if expected_error is None:
            if actual_error is not None or mutated_result is None:
                raise ValueError(
                    f"v2.10 positive case {name} did not pass: {actual_error}"
                )
        elif actual_error != expected_error:
            raise ValueError(
                f"v2.10 mutation {name} did not trip its named claim: "
                f"expected={expected_error!r} actual={actual_error!r}"
            )
        cleared_before_restore = clear_contract_bytecode(repo)
        restored = green()
        transcript = {
            "schema": "solomon-dark-native-menu-v210-mutation-transcript-v1",
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
        transcript_path = output_directory / f"v210-{name}.json"
        write_object(transcript_path, transcript)
        summary.append(
            {
                "case": name,
                "transcript": transcript_path.name,
                "passed": True,
            }
        )

    result = {
        "schema": "solomon-dark-native-menu-v210-mutation-table-v1",
        "case_count": len(summary),
        "all_passed": all(entry["passed"] for entry in summary),
        "cases": summary,
    }
    write_object(output_directory / "v210-mutation-table.json", result)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
