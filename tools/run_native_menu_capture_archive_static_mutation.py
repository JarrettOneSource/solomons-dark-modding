#!/usr/bin/env python3
"""Mutation-test the archived menufix capture-provenance receipt."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


CASE = "capture_archive_rejects_wrong_bundle_hash"
ARCHIVE_SHA = "c9d521db6917d1ff997604aaf7038537a510673548a5bd091ad315e7ac78fb50"
TRIP_MESSAGE = (
    "menufix capture source archive no longer pins the exact bundle hash, "
    "prerequisite, heads, and recorded object types"
)
GREEN_FRAGMENT = "17 capture objects are externally archived"


def atomic_bytes(path: Path, value: bytes) -> None:
    temporary = path.with_name(path.name + ".menufix.tmp")
    temporary.write_bytes(value)
    os.replace(temporary, path)


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_bytes(path, (json.dumps(value, indent=2) + "\n").encode("utf-8"))


def clear_bytecode(repo: Path) -> list[str]:
    cleared = []
    for relative in ("tests/__pycache__", "tests/re/__pycache__", "tools/__pycache__"):
        path = repo / relative
        if path.is_dir():
            shutil.rmtree(path)
        cleared.append(relative)
    return cleared


def run_contract(repo: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = str(repo / "tests/re")
    return subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from static_re_binary_tooling_contracts import "
                "test_recorded_capture_provenance_resolves_or_is_declared as "
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
        or GREEN_FRAGMENT not in completed.stdout
        or completed.stderr
    ):
        raise RuntimeError(
            f"capture-archive contract {phase} was not green: "
            f"rc={completed.returncode} stdout={completed.stdout!r} "
            f"stderr={completed.stderr!r}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo_root.resolve()
    output = args.output_directory.resolve()
    source_path = repo / "tests/re/static_re_binary_tooling_contracts.py"
    original = source_path.read_bytes()
    token = ARCHIVE_SHA.encode("ascii")
    if original.count(token) != 3:
        raise RuntimeError("capture-archive mutation lost its exact three-site SHA witness")

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
    mutated = original.replace(token, b"0" * 64, 1)
    try:
        atomic_bytes(source_path, mutated)
        trip = run_contract(repo)
    finally:
        atomic_bytes(source_path, original)
    if trip.returncode == 0 or TRIP_MESSAGE not in trip.stderr:
        raise RuntimeError(
            "capture-archive SHA mutation did not trip its exact named claim"
        )
    trip_path = output / f"{CASE}.trip.json"
    atomic_json(
        trip_path,
        {
            "case": CASE,
            "phase": "trip",
            "edit": "replace only the recorded menu capture bundle SHA",
            "bytecode_cleared": mutation_cleared,
            "returncode": trip.returncode,
            "stdout": trip.stdout,
            "stderr": trip.stderr,
            "expected_message": TRIP_MESSAGE,
            "tripped_named_claim": True,
        },
    )

    after_cleared = clear_bytecode(repo)
    after = run_contract(repo)
    require_green(after, "green-after-restore")
    if source_path.read_bytes() != original:
        raise RuntimeError("capture-archive mutation did not restore exact source bytes")
    after_path = output / f"{CASE}.green-after.json"
    atomic_json(
        after_path,
        {
            "case": CASE,
            "phase": "green_after_restore",
            "bytecode_cleared": after_cleared,
            "returncode": after.returncode,
            "stdout": after.stdout,
            "stderr": after.stderr,
            "exact_source_bytes_restored": True,
        },
    )
    table = {
        "schema": "solomon-dark-menufix-capture-archive-static-mutation-v1",
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
    atomic_json(output / "capture-archive-static-mutation-table.json", table)
    print(json.dumps(table, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
