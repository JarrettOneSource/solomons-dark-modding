#!/usr/bin/env python3
"""Mutation-test the registered Settlement v2.21 static contract."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


CASE = "static_contract_rejects_choice_slot_anchor_mutation"
GREEN_OUTPUT = (
    "Settlement v2.21 dispositions are exact across 261 Class-A members, "
    "38 Class-B members, six fields, two witnesses, and two Skills.84 rows"
)
TRIP_MESSAGE = (
    "Settlement v2.21 exact sealed census disposition no longer validates"
)


def atomic_bytes(path: Path, value: bytes) -> None:
    temporary = path.with_name(path.name + ".menufix.tmp")
    temporary.write_bytes(value)
    os.replace(temporary, path)


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_bytes(
        path,
        (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )


def clear_bytecode(repo: Path) -> list[str]:
    cleared: list[str] = []
    for relative in ("tests/__pycache__", "tests/re/__pycache__", "tools/__pycache__"):
        path = repo / relative
        if path.is_dir():
            shutil.rmtree(path)
        cleared.append(relative)
    return cleared


def run_contract(repo: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = os.pathsep.join(
        (str(repo / "tests/re"), str(repo / "tools"))
    )
    return subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from static_re_native_menu_shell_contracts import "
                "test_native_menu_v221_census_era_disposition_is_exact as "
                "contract; print(contract())"
            ),
        ],
        cwd=repo,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def require_green(completed: subprocess.CompletedProcess[str], phase: str) -> None:
    if (
        completed.returncode != 0
        or completed.stdout.strip() != GREEN_OUTPUT
        or completed.stderr
    ):
        raise RuntimeError(
            f"v2.21 static contract {phase} was not green: "
            f"rc={completed.returncode} stdout={completed.stdout!r} "
            f"stderr={completed.stderr!r}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = args.repo_root.resolve()
    output = args.output_directory.resolve()
    contract_path = (
        repo / "tests/fixtures/webgame/native-menu-census-era-disposition-v221.json"
    )
    original = contract_path.read_bytes()
    parsed = json.loads(original.decode("utf-8"))
    anchor = parsed.get("choice_slot_reconciliation", {}).get(
        "slot_binding", {}
    ).get("anchor")
    if anchor != {"x": 604, "y": 386.5}:
        raise RuntimeError("v2.21 static mutation did not reach the exact choice slot")

    before_cleared = clear_bytecode(repo)
    before = run_contract(repo)
    require_green(before, "green-before")
    before_path = output / f"{CASE}.green-before.json"
    atomic_json(
        before_path,
        {
            "case": CASE,
            "phase": "green_before",
            "bytecode_cleared": before_cleared,
            "returncode": before.returncode,
            "stdout": before.stdout,
            "stderr": before.stderr,
        },
    )

    mutation_cleared = clear_bytecode(repo)
    mutated = json.loads(original.decode("utf-8"))
    mutated["choice_slot_reconciliation"]["slot_binding"]["anchor"]["x"] += 1
    try:
        atomic_bytes(
            contract_path,
            (json.dumps(mutated, ensure_ascii=False, indent=2) + "\n").encode(
                "utf-8"
            ),
        )
        trip = run_contract(repo)
    finally:
        atomic_bytes(contract_path, original)
    if (
        trip.returncode == 0
        or TRIP_MESSAGE not in trip.stderr
        or GREEN_OUTPUT in trip.stdout
    ):
        raise RuntimeError(
            "v2.21 anchor-mutated contract did not trip its exact registered claim"
        )
    trip_path = output / f"{CASE}.trip.json"
    atomic_json(
        trip_path,
        {
            "case": CASE,
            "phase": "trip",
            "edit": "move the exact Skills.84 choice-slot anchor x by one pixel",
            "bytecode_cleared": mutation_cleared,
            "returncode": trip.returncode,
            "stdout": trip.stdout,
            "stderr": trip.stderr,
            "expected_message": TRIP_MESSAGE,
            "tripped_named_claim": True,
        },
    )

    restore_cleared = clear_bytecode(repo)
    restored = run_contract(repo)
    require_green(restored, "green-after-restore")
    if contract_path.read_bytes() != original:
        raise RuntimeError("v2.21 static mutation did not restore the exact contract bytes")
    after_path = output / f"{CASE}.green-after.json"
    atomic_json(
        after_path,
        {
            "case": CASE,
            "phase": "green_after_restore",
            "bytecode_cleared": restore_cleared,
            "returncode": restored.returncode,
            "stdout": restored.stdout,
            "stderr": restored.stderr,
            "exact_contract_bytes_restored": True,
        },
    )
    table = {
        "schema": "solomon-dark-native-menu-v221-static-contract-mutation-table-v1",
        "row_count": 1,
        "all_passed": True,
        "rows": [
            {
                "case": CASE,
                "green_before": before_path.name,
                "trip": trip_path.name,
                "green_after": after_path.name,
                "actual_message": TRIP_MESSAGE,
                "passed": True,
            }
        ],
    }
    atomic_json(output / "v221-static-contract-mutation-table.json", table)
    print(json.dumps(table, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
