#!/usr/bin/env python3
"""Prove production still stops first while exhaustive diagnostics coexist."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


class MutationError(RuntimeError):
    """The diagnostic/production mode boundary no longer fails closed."""


CASE = "production_stops_first_while_census_enumerates_all"


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise MutationError(f"stop-first mutation input is not an object: {path}")
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


def verify_green(
    repo: Path,
    evidence_root: Path,
    census_path: Path,
    expected_census_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    census = read_object(census_path)
    census_receipt = file_receipt(census_path)
    if expected_census_receipt is not None and census_receipt != expected_census_receipt:
        raise MutationError("stop-first production probe changed the exhaustive census")
    counts = census.get("census")
    first_stop = census.get("first_production_stop")
    if (
        census.get("schema")
        != "solomon-dark-native-menu-landed-difference-census-v1"
        or census.get("mode") != "enumerate_all_unclassified"
        or census.get("success") is not True
        or census.get("dry_run") is not True
        or census.get("writes_performed") is not False
        or census.get("candidate_applied") is not False
        or census.get("production_behavior")
        != "stop_at_first_unclassified_difference"
        or not isinstance(counts, dict)
        or counts.get("unclassified_difference_count", 0) <= 1
        or not isinstance(first_stop, str)
        or not first_stop.startswith("STOP: standalone ")
    ):
        raise MutationError(
            "exhaustive diagnostic green baseline does not prove multiple findings without writes"
        )
    inputs = census.get("inputs")
    if not isinstance(inputs, dict):
        raise MutationError("exhaustive diagnostic has no source receipt census")
    landed = inputs.get("landed_aggregate")
    candidate = inputs.get("candidate_aggregate")
    if not isinstance(landed, dict) or not isinstance(candidate, dict):
        raise MutationError("exhaustive diagnostic omitted landed or candidate receipts")
    landed_path = repo / str(landed.get("repo_relative_path"))
    candidate_path = evidence_root / str(candidate.get("evidence_path"))
    for label, recorded, path in (
        ("landed aggregate", landed, landed_path),
        ("candidate aggregate", candidate, candidate_path),
    ):
        if not path.is_file() or file_receipt(path) != {
            "sha256": recorded.get("sha256"),
            "bytes": recorded.get("bytes"),
        }:
            raise MutationError(
                f"stop-first mutation cannot prove the {label} remained unchanged"
            )
    return {
        "census": census_receipt,
        "unclassified_difference_count": counts["unclassified_difference_count"],
        "first_production_stop": first_stop,
        "landed_aggregate": file_receipt(landed_path),
        "candidate_aggregate": file_receipt(candidate_path),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--navigation-recording", type=Path, required=True)
    parser.add_argument("--census", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = args.repo_root.resolve()
    candidate = args.candidate_root.resolve()
    evidence = args.evidence_root.resolve()
    navigation = args.navigation_recording.resolve()
    census = args.census.resolve()
    output = args.output_directory.resolve()
    if not output.is_relative_to(evidence):
        raise MutationError("stop-first mutation transcripts escape the evidence root")

    before_cleared = clear_bytecode(repo)
    before = verify_green(repo, evidence, census)
    before_receipt = before["census"]
    before_path = output / f"{CASE}.green-before.json"
    atomic_json(
        before_path,
        {
            "case": CASE,
            "phase": "green_before",
            "bytecode_cleared": before_cleared,
            "diagnostic": before,
        },
    )

    mutation_cleared = clear_bytecode(repo)
    command = [
        sys.executable,
        str(repo / "tools/promote_native_menu_recapture.py"),
        "--repo-root",
        str(repo),
        "--candidate-root",
        str(candidate),
        "--evidence-root",
        str(evidence),
        "--navigation-recording",
        str(navigation),
        "--dry-run",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise MutationError("production stop-first probe emitted non-JSON output") from error
    if (
        completed.returncode != 1
        or result
        != {"success": False, "error": before["first_production_stop"]}
        or completed.stderr
    ):
        raise MutationError(
            "production path did not stop on the exhaustive census's first unclassified claim"
        )
    trip_path = output / f"{CASE}.trip.json"
    atomic_json(
        trip_path,
        {
            "case": CASE,
            "phase": "trip",
            "edit": "omit --enumerate-all-unclassified-output and exercise production dry-run",
            "bytecode_cleared": mutation_cleared,
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "expected_error": before["first_production_stop"],
            "actual_error": result.get("error"),
            "tripped_named_claim": True,
        },
    )

    restore_cleared = clear_bytecode(repo)
    restored = verify_green(repo, evidence, census, before_receipt)
    after_path = output / f"{CASE}.green-after.json"
    atomic_json(
        after_path,
        {
            "case": CASE,
            "phase": "green_after_restore",
            "bytecode_cleared": restore_cleared,
            "diagnostic": restored,
        },
    )
    table = {
        "schema": "solomon-dark-native-menu-stop-first-census-mutation-table-v1",
        "row_count": 1,
        "all_passed": True,
        "rows": [
            {
                "case": CASE,
                "green_before": before_path.name,
                "trip": trip_path.name,
                "green_after": after_path.name,
                "actual_error": result["error"],
                "passed": True,
            }
        ],
    }
    atomic_json(output / "stop-first-census-mutation-table.json", table)
    print(json.dumps(table, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
