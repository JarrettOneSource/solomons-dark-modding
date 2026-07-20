#!/usr/bin/env python3
"""Verify the all-player level-up barrier on a genuine Steam friend pair."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import traceback
from pathlib import Path
from typing import Any

import verify_multiplayer_level_up_barrier_sync as barrier
import verify_multiplayer_level_up_offer_sync as offer
from steam_friend_active_pair import (
    CLIENT_ENDPOINT,
    HOST_ENDPOINT,
    ROOT,
    SteamFriendActivePair,
)
from steam_friend_behavior_context import (
    configure_behavior_context,
    require_shared_test_run,
)
from verify_local_multiplayer_sync import VerifyFailure, parse_int_text
from verify_steam_friend_active_pair_progression import find_new_crash_artifacts


DEFAULT_OUTPUT = ROOT / "runtime/steam_friend_active_pair_level_up_barrier.json"


def configure(
    pair: SteamFriendActivePair,
) -> None:
    context = configure_behavior_context(pair)
    replacements = {
        "HOST_ID": pair.host_participant_id,
        "CLIENT_ID": pair.client_participant_id,
        "HOST_PIPE": HOST_ENDPOINT,
        "CLIENT_PIPE": CLIENT_ENDPOINT,
        "HOST_LOG": context.host_log,
        "CLIENT_LOG": context.client_log,
        "lua": pair.lua,
    }
    for module in (barrier, offer):
        for name, value in replacements.items():
            if hasattr(module, name):
                setattr(module, name, value)


def require_idle_barrier() -> dict[str, dict[str, Any]]:
    snapshots = {
        "host": offer.capture(HOST_ENDPOINT),
        "client": offer.capture(CLIENT_ENDPOINT),
    }
    compact = {
        label: {
            "offer_valid": snapshot.get("offer.valid") == "true",
            "pause_active": snapshot.get("wait.pause_active") == "true",
            "waiting_count": parse_int_text(
                snapshot.get("wait.waiting_count"),
                0,
            ),
        }
        for label, snapshot in snapshots.items()
    }
    if any(
        values["offer_valid"]
        or values["pause_active"]
        or values["waiting_count"] != 0
        for values in compact.values()
    ):
        raise VerifyFailure(
            f"level-up barrier profile did not start idle: {compact}"
        )
    return compact


def compact_summary(
    output: dict[str, Any],
    output_path: Path,
) -> dict[str, Any]:
    normal = output.get("matrix", {}).get("normal_barrier", {})
    timeout = output.get("matrix", {}).get("timeout_barrier", {})
    return {
        "ok": output.get("ok", False),
        "active_step": output.get("active_step"),
        "error": output.get("error"),
        "normal_client_wait_hud": normal.get(
            "client_waiting_for_host", {}
        ).get("client_hud"),
        "normal_world_pause": normal.get("world_activity", {}).get(
            "paused", {}
        ).get("pause_position_drift"),
        "timeout_host_wait_hud": timeout.get("host_wait_hud"),
        "timeout_elapsed_seconds": timeout.get("elapsed_seconds"),
        "timeout_auto_pick_option": timeout.get("auto_result", {}).get(
            "option_id"
        ),
        "new_crash_artifacts": output.get("new_crash_artifacts", []),
        "output": str(output_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=35.0)
    parser.add_argument("--auto-timeout", type=float, default=75.0)
    parser.add_argument("--normal-only", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    started_at = time.time()
    pair = SteamFriendActivePair()
    output: dict[str, Any] = {"ok": False}
    return_code = 1
    try:
        output["active_step"] = "discover_pair"
        output["pair"] = pair.discover()
        require_shared_test_run(output["pair"])
        configure(pair)
        output["initial_barrier"] = require_idle_barrier()

        output["active_step"] = "level_up_barrier"
        output["matrix"] = barrier.run_prepared_barrier_matrix(
            args.timeout,
            args.auto_timeout,
            normal_only=args.normal_only,
        )
        output["new_crash_artifacts"] = find_new_crash_artifacts(started_at)
        if output["new_crash_artifacts"]:
            raise VerifyFailure(
                "new crash artifacts appeared during level-up barrier test"
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
