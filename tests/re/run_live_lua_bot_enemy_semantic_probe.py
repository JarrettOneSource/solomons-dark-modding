#!/usr/bin/env python3
"""Live RE probe for the Lua bot enemy-target semantic surface.

This validates the native-facing `sd.world.list_actors()` contract used by the
Lua autonomous combat controller: stock combat hostiles must be exposed through
the semantic `tracked_enemy` flag with usable actor, health, and type fields.
Lua combat code can then avoid duplicating native object type constants.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = ROOT / "runtime" / "live_lua_bot_enemy_semantic_probe.json"
SOURCE_RAW_OUTPUT_PATH = ROOT / "runtime" / "live_lua_bot_enemy_semantic_probe.source.raw.json"
SOURCE_OUTPUT_PATH = ROOT / "runtime" / "live_lua_bot_enemy_semantic_probe.source.json"
EXISTING_BOULDER_RAW_OUTPUT_PATH = ROOT / "runtime" / "live_boulder_impact_projection_probe.raw.json"
EXISTING_BOULDER_OUTPUT_PATH = ROOT / "runtime" / "live_boulder_impact_projection_probe.json"
ELEMENT_DAMAGE_PROBE = ROOT / "tools/probe_bot_element_damage.py"


class LiveLuaBotEnemySemanticProbeFailure(RuntimeError):
    pass


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def is_true(value: Any) -> bool:
    return value is True or str(value).lower() == "true"


def repo_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:
        return str(path)


def run_source_probe(raw_output: Path, output: Path, timeout_s: float) -> dict[str, Any]:
    command = [
        sys.executable,
        str(ELEMENT_DAMAGE_PROBE),
        "--element",
        "earth",
        "--output",
        str(raw_output),
        "--semantic-snapshot-only",
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=timeout_s + 10.0,
        check=False,
    )
    summary: dict[str, Any] = {
        "source_kind": "probe_execution",
        "command": [str(part) for part in command],
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    if not raw_output.exists():
        raise LiveLuaBotEnemySemanticProbeFailure(f"source probe wrote no raw output: {raw_output}")
    return summary


def load_source_summary(output: Path) -> dict[str, Any]:
    if not output.exists():
        return {}
    return json.loads(output.read_text(encoding="utf-8"))


def collect_actor_entries(node: Any, path: str = "$") -> tuple[int, list[dict[str, Any]]]:
    actor_count = 0
    tracked: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if "actor_address" in node:
            actor_count += 1
        if is_true(node.get("tracked_enemy")):
            entry = dict(node)
            entry["_source_path"] = path
            tracked.append(entry)
        for key, value in node.items():
            child_count, child_tracked = collect_actor_entries(value, f"{path}.{key}")
            actor_count += child_count
            tracked.extend(child_tracked)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            child_count, child_tracked = collect_actor_entries(value, f"{path}[{index}]")
            actor_count += child_count
            tracked.extend(child_tracked)
    return actor_count, tracked


def dedupe_tracked_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[int, int, str]] = set()
    unique: list[dict[str, Any]] = []
    for entry in entries:
        key = (
            as_int(entry.get("actor_address")),
            as_int(entry.get("object_type_id")),
            str(entry.get("_source_path", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(entry)
    return unique


def summarize_semantic_surface(raw: dict[str, Any]) -> dict[str, Any]:
    snapshot = extract_tracked_enemy_semantic_snapshot(raw)
    if snapshot is not None:
        actor_count = as_int(snapshot.get("actor_count"))
        tracked_entries = [
            entry for entry in snapshot.get("hostiles", [])
            if isinstance(entry, dict) and is_true(entry.get("tracked_enemy"))
        ]
    else:
        actor_count, tracked_entries = collect_actor_entries(raw)
    tracked_entries = dedupe_tracked_entries(tracked_entries)
    invalid_health = [
        entry for entry in tracked_entries
        if as_float(entry.get("hp")) <= 0.0 or as_float(entry.get("max_hp")) <= 0.0
    ]
    type_mismatches = [
        entry for entry in tracked_entries
        if as_int(entry.get("object_type_id")) != 0
        and as_int(entry.get("enemy_type")) != 0
        and as_int(entry.get("object_type_id")) != as_int(entry.get("enemy_type"))
    ]
    missing_addresses = [
        entry for entry in tracked_entries
        if as_int(entry.get("actor_address")) == 0
    ]
    first = tracked_entries[0] if tracked_entries else {}
    return {
        "available": True,
        "actor_count": actor_count,
        "tracked_count": len(tracked_entries),
        "invalid_health_count": len(invalid_health),
        "type_mismatch_count": len(type_mismatches),
        "missing_address_count": len(missing_addresses),
        "first_actor_address": as_int(first.get("actor_address")),
        "first_object_type_id": as_int(first.get("object_type_id")),
        "first_enemy_type": as_int(first.get("enemy_type")),
        "first_hp": as_float(first.get("hp")),
        "first_max_hp": as_float(first.get("max_hp")),
        "first_dead": first.get("dead"),
        "first_source_path": first.get("_source_path", ""),
        "sample_sources": [entry.get("_source_path", "") for entry in tracked_entries[:8]],
        "source_kind": "tracked_enemy_semantic_snapshot" if snapshot is not None else "recursive_raw_scan",
    }


def extract_tracked_enemy_semantic_snapshot(node: Any) -> dict[str, Any] | None:
    if isinstance(node, dict):
        snapshot = node.get("tracked_enemy_semantic_snapshot")
        if isinstance(snapshot, dict):
            return snapshot
        for value in node.values():
            found = extract_tracked_enemy_semantic_snapshot(value)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = extract_tracked_enemy_semantic_snapshot(value)
            if found is not None:
                return found
    return None


def validate_enemy_semantic_surface(surface: dict[str, Any]) -> None:
    if surface.get("available") is not True:
        raise LiveLuaBotEnemySemanticProbeFailure(f"semantic source unavailable: {surface}")
    if as_int(surface.get("tracked_count")) <= 0:
        raise LiveLuaBotEnemySemanticProbeFailure(f"no tracked_enemy actors published: {surface}")
    if as_int(surface.get("invalid_health_count")) != 0:
        raise LiveLuaBotEnemySemanticProbeFailure(f"tracked_enemy actor has invalid health: {surface}")
    if as_int(surface.get("type_mismatch_count")) != 0:
        raise LiveLuaBotEnemySemanticProbeFailure(f"tracked_enemy enemy_type mismatch: {surface}")
    if as_int(surface.get("missing_address_count")) != 0:
        raise LiveLuaBotEnemySemanticProbeFailure(f"tracked_enemy actor has no address: {surface}")


def validate_source_summary(summary: dict[str, Any], output: Path) -> None:
    if not summary:
        raise LiveLuaBotEnemySemanticProbeFailure(f"source summary is missing: {output}")
    if summary.get("source_kind") == "probe_execution":
        if as_int(summary.get("returncode"), -1) != 0:
            raise LiveLuaBotEnemySemanticProbeFailure(f"source live probe did not pass: {summary}")
        return
    if summary.get("passed") is not True:
        raise LiveLuaBotEnemySemanticProbeFailure(f"source live probe did not pass: {summary}")


def run_probe(
    *,
    raw_output: Path,
    source_output: Path,
    timeout_s: float,
    reuse_existing_source: bool,
) -> dict[str, Any]:
    source_execution: dict[str, Any]
    if reuse_existing_source:
        raw_output = EXISTING_BOULDER_RAW_OUTPUT_PATH
        source_output = EXISTING_BOULDER_OUTPUT_PATH
        source_execution = {"mode": "reuse_existing_source"}
    else:
        source_execution = run_source_probe(raw_output, source_output, timeout_s)

    if not raw_output.exists():
        raise LiveLuaBotEnemySemanticProbeFailure(f"source raw output is missing: {raw_output}")
    raw = json.loads(raw_output.read_text(encoding="utf-8"))
    source_summary = load_source_summary(source_output)
    validate_source_summary(source_summary, source_output)
    surface = summarize_semantic_surface(raw)
    validate_enemy_semantic_surface(surface)
    return {
        "source_execution": source_execution,
        "source_raw_output": repo_relative(raw_output),
        "source_summary_output": repo_relative(source_output),
        "enemy_semantic_surface": surface,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-output", type=Path, default=SOURCE_RAW_OUTPUT_PATH)
    parser.add_argument("--source-output", type=Path, default=SOURCE_OUTPUT_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--reuse-existing-source",
        action="store_true",
        help="Validate the latest boulder live-probe artifacts instead of rerunning the source probe.",
    )
    parser.add_argument("--json", action="store_true", help="Only print structured JSON.")
    args = parser.parse_args()

    result: dict[str, Any]
    exit_code = 0
    try:
        result = run_probe(
            raw_output=args.raw_output,
            source_output=args.source_output,
            timeout_s=args.timeout,
            reuse_existing_source=args.reuse_existing_source,
        )
        result["passed"] = True
    except Exception as exc:  # noqa: BLE001 - live probes preserve diagnostics in JSON.
        result = {
            "passed": False,
            "error": str(exc),
            "source_raw_output": repo_relative(args.raw_output),
            "source_summary_output": repo_relative(args.source_output),
        }
        exit_code = 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif exit_code == 0:
        surface = result["enemy_semantic_surface"]
        print(
            "Live Lua bot enemy semantic probe passed. "
            f"tracked={surface['tracked_count']} first_actor={surface['first_actor_address']}"
        )
        print(f"Wrote {args.output}")
    else:
        print(f"Live Lua bot enemy semantic probe failed. Wrote {args.output}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
