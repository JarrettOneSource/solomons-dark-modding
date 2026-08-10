#!/usr/bin/env python3
"""Run the exact five-row v2.20 Dark Cloud login title mutation table."""

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
    TITLE_MISMATCH,
    diagnose_dark_cloud_login_title_v220,
)


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"v2.20 mutation input is not an object: {path}")
    return value


def file_receipt(path: Path) -> dict[str, Any]:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"sha256": digest.hexdigest(), "bytes": path.stat().st_size}


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = args.repo_root.resolve()
    candidate_root = args.candidate_root.resolve()
    output = args.output_directory.resolve()
    landed_path = (
        repo
        / "webgame-contracts/baseline-snapshots/menu-layouts/"
        "dark-cloud-login-settings.json"
    )
    candidate_path = (
        candidate_root / "menu-layouts/dark-cloud-login-settings.json"
    )
    contract_path = (
        repo
        / "tests/fixtures/webgame/native-menu-dark-cloud-login-title-v220.json"
    )
    landed = read_object(landed_path)["layout"]
    settled = read_object(candidate_path)["layout"]
    contract = read_object(contract_path)
    landed_receipt = file_receipt(landed_path)
    candidate_receipt = file_receipt(candidate_path)

    def green() -> dict[str, Any]:
        correction = diagnose_dark_cloud_login_title_v220(
            "dark-cloud-login-settings",
            copy.deepcopy(landed),
            copy.deepcopy(settled),
            copy.deepcopy(contract),
            landed_receipt,
            candidate_receipt,
        )
        if (
            not isinstance(correction, dict)
            or correction.get("settlement_spec") != "2.20"
            or correction.get("layout_id") != "dark-cloud-login-settings"
            or correction.get("old_value") != ""
            or correction.get("new_value") != "Dark Cloud Browser"
            or correction.get("general_tolerance") is not False
        ):
            raise ValueError("v2.20 green baseline did not exercise the exact title correction")
        return correction

    def disabled(
        layout_id: str,
        landed_layout: dict[str, Any],
        settled_layout: dict[str, Any],
        contract_value: dict[str, Any],
    ) -> tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]:
        return layout_id, landed_layout, settled_layout, {}

    def target_case_variant(
        layout_id: str,
        landed_layout: dict[str, Any],
        settled_layout: dict[str, Any],
        contract_value: dict[str, Any],
    ) -> tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]:
        contract_value["settled_value"] = "DARK CLOUD BROWSER"
        return layout_id, landed_layout, settled_layout, contract_value

    def wrong_layout(
        layout_id: str,
        landed_layout: dict[str, Any],
        settled_layout: dict[str, Any],
        contract_value: dict[str, Any],
    ) -> tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]:
        return "hall-of-fame", landed_layout, settled_layout, contract_value

    def second_field(
        layout_id: str,
        landed_layout: dict[str, Any],
        settled_layout: dict[str, Any],
        contract_value: dict[str, Any],
    ) -> tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]:
        settled_layout["screen_id"] = "dark_cloud_login_settings_mutated"
        return layout_id, landed_layout, settled_layout, contract_value

    def settled_title_variant(
        layout_id: str,
        landed_layout: dict[str, Any],
        settled_layout: dict[str, Any],
        contract_value: dict[str, Any],
    ) -> tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]:
        settled_layout["screen_title"] = "DARK CLOUD BROWSER"
        return layout_id, landed_layout, settled_layout, contract_value

    cases: list[
        tuple[
            str,
            str,
            Callable[
                [str, dict[str, Any], dict[str, Any], dict[str, Any]],
                tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]],
            ],
        ]
    ] = [
        (
            "authorization_disabled_reproduces_title_stop",
            "remove the v2.20 authorization contract",
            disabled,
        ),
        (
            "case_mutated_target_value_stops",
            "change only the contract target to DARK CLOUD BROWSER",
            target_case_variant,
        ),
        (
            "same_pattern_on_other_layout_stops",
            "claim the exact title change on hall-of-fame",
            wrong_layout,
        ),
        (
            "second_differing_layout_field_stops",
            "change screen_id alongside the title correction",
            second_field,
        ),
        (
            "settled_title_disagrees_with_pin_stops",
            "change the measured settled title case",
            settled_title_variant,
        ),
    ]

    rows: list[dict[str, Any]] = []
    for name, edit, mutate in cases:
        before_cleared = clear_bytecode(repo)
        before = green()
        layout_id, mutated_landed, mutated_settled, mutated_contract = mutate(
            "dark-cloud-login-settings",
            copy.deepcopy(landed),
            copy.deepcopy(settled),
            copy.deepcopy(contract),
        )
        mutation_cleared = clear_bytecode(repo)
        actual_error: str | None = None
        try:
            diagnose_dark_cloud_login_title_v220(
                layout_id,
                mutated_landed,
                mutated_settled,
                mutated_contract,
                landed_receipt,
                candidate_receipt,
            )
        except LandedDiagnosisError as error:
            actual_error = str(error)
        if actual_error != TITLE_MISMATCH:
            raise ValueError(
                f"v2.20 mutation {name} did not trip the named title claim: "
                f"expected={TITLE_MISMATCH!r} actual={actual_error!r}"
            )
        restore_cleared = clear_bytecode(repo)
        restored = green()
        before_path = output / f"v220-{name}.green-before.json"
        trip_path = output / f"v220-{name}.trip.json"
        after_path = output / f"v220-{name}.green-after.json"
        atomic_json(
            before_path,
            {
                "case": name,
                "phase": "green_before",
                "bytecode_cleared": before_cleared,
                "correction": before,
            },
        )
        atomic_json(
            trip_path,
            {
                "case": name,
                "phase": "trip",
                "edit": edit,
                "bytecode_cleared": mutation_cleared,
                "expected_error": TITLE_MISMATCH,
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
                "correction": restored,
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
        "schema": "solomon-dark-native-menu-v220-title-mutation-table-v1",
        "settlement_spec": "2.20",
        "contract": file_receipt(contract_path),
        "landed_fixture": file_receipt(landed_path),
        "candidate_fixture": file_receipt(candidate_path),
        "row_count": len(rows),
        "all_passed": all(row["passed"] for row in rows),
        "rows": rows,
    }
    atomic_json(output / "v220-title-mutation-table.json", result)
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
