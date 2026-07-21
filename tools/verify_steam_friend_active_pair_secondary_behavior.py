#!/usr/bin/env python3
"""Verify selected secondary spells on a genuine Steam friend pair."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import traceback
from pathlib import Path
from typing import Any

import multiplayer_secondary_behavior_harness as secondary
import verify_multiplayer_primary_kill_stress as primary
from steam_friend_active_pair import ROOT, SteamFriendActivePair
from steam_friend_behavior_context import (
    configure_behavior_context,
    require_shared_test_run,
    reset_quiet_arena,
)
from verify_local_multiplayer_sync import VerifyFailure
from verify_steam_friend_active_pair_progression import find_new_crash_artifacts


DEFAULT_OUTPUT = ROOT / "runtime/steam_friend_active_pair_secondary_behavior.json"


def parse_rows(text: str) -> list[int]:
    rows: list[int] = []
    for raw in text.split(","):
        value = raw.strip()
        if not value:
            continue
        try:
            row = int(value, 0)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(
                f"invalid secondary row: {value}"
            ) from exc
        if row not in secondary.SKILL_BY_ROW:
            raise argparse.ArgumentTypeError(
                f"row {row} is not a native secondary skill"
            )
        if row in rows:
            raise argparse.ArgumentTypeError(f"duplicate secondary row: {row}")
        rows.append(row)
    if not rows:
        raise argparse.ArgumentTypeError("at least one secondary row is required")
    return rows


def compact_summary(output: dict[str, Any], output_path: Path) -> dict[str, Any]:
    directions = output.get("behaviors", {})
    return {
        "ok": output.get("ok", False),
        "active_step": output.get("active_step"),
        "error": output.get("error"),
        "rows": output.get("rows", []),
        "directions": {
            name: sorted(int(row) for row in behaviors)
            for name, behaviors in directions.items()
        },
        "new_crash_artifacts": output.get("new_crash_artifacts", []),
        "output": str(output_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", required=True, type=parse_rows)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    started_at = time.time()
    pair = SteamFriendActivePair()
    output: dict[str, Any] = {
        "ok": False,
        "rows": args.rows,
        "skills": [
            {
                "row": row,
                "name": secondary.SKILL_BY_ROW[row].name,
                "behavior": secondary.SKILL_BY_ROW[row].behavior,
            }
            for row in args.rows
        ],
    }
    return_code = 1
    try:
        output["active_step"] = "discover_pair"
        output["pair"] = pair.discover()
        require_shared_test_run(output["pair"])
        context = configure_behavior_context(pair)

        output["active_step"] = "combat_bootstrap"
        output["combat_bootstrap"] = primary.enable_manual_stock_spawner_combat()

        output["active_step"] = "initial_arena_reset"
        output["initial_arena_reset"] = reset_quiet_arena()

        output["active_step"] = "capacity"
        output["capacity"] = secondary.ensure_batch_capacity(
            context.focus_directions,
            args.rows,
        )

        output["active_step"] = "acquire"
        output["acquisitions"] = {}
        for direction in context.focus_directions:
            output["acquisitions"][direction.name] = {}
            for row in args.rows:
                output["active_step"] = f"acquire.{direction.name}.{row}"
                output["acquisitions"][direction.name][str(row)] = (
                    secondary.acquire_skill(direction, row, args.timeout)
                )

        output["behaviors"] = {}
        output["arena_resets"] = {}
        for direction in context.focus_directions:
            output["behaviors"][direction.name] = {}
            output["arena_resets"][direction.name] = {}
            for row in args.rows:
                skill = secondary.SKILL_BY_ROW[row]
                output["active_step"] = f"behavior.{direction.name}.{row}"
                output["arena_resets"][direction.name][str(row)] = (
                    reset_quiet_arena(
                        require_manual_spawner=skill.target_required
                    )
                )
                if skill.synchronized_effect_type is not None:
                    output["arena_resets"][direction.name][str(row)][
                        "prior_effect_retirement"
                    ] = secondary.wait_for_effect_type_absent(
                        pair,
                        skill.synchronized_effect_type,
                        args.timeout,
                    )
                output["behaviors"][direction.name][str(row)] = (
                    secondary.run_skill(
                        pair,
                        direction,
                        skill,
                        output["acquisitions"][direction.name][str(row)],
                        args.timeout,
                    )
                )

        output["new_crash_artifacts"] = find_new_crash_artifacts(started_at)
        if output["new_crash_artifacts"]:
            raise VerifyFailure(
                "new crash artifacts appeared during secondary behavior tests"
            )
        output.pop("active_step", None)
        output["ok"] = True
        return_code = 0
    except (VerifyFailure, subprocess.TimeoutExpired, ValueError, OSError) as exc:
        output["error"] = str(exc)
        output["error_type"] = type(exc).__name__
        output["traceback"] = traceback.format_exc()
        output["new_crash_artifacts"] = find_new_crash_artifacts(started_at)
    finally:
        pair.close()
        output = pair.redact(output)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(output, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    print(json.dumps(compact_summary(output, args.output), indent=2, sort_keys=True))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
