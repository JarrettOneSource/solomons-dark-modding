#!/usr/bin/env python3
"""Verify all stock powerup rewards on an active Steam friend pair."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import traceback
from pathlib import Path
from typing import Any

import verify_local_multiplayer_sync as local_sync
import verify_multiplayer_all_upgrade_sync as upgrades
import verify_multiplayer_level_up_offer_sync as offers
import verify_multiplayer_powerup_sync as powerups
from steam_friend_active_pair import (
    CLIENT_ENDPOINT,
    HOST_ENDPOINT,
    PAIR_BACKEND,
    ROOT,
    SteamFriendActivePair,
)
from steam_friend_behavior_context import (
    disable_runtime_test_godmode,
    require_shared_test_run,
)
from verify_local_multiplayer_sync import VerifyFailure
from verify_steam_friend_active_pair_progression import find_new_crash_artifacts


DEFAULT_OUTPUT = ROOT / "runtime/steam_friend_powerup_sync.json"
HOST_INSTANCE = os.environ.get("SDMOD_STEAM_HOST_INSTANCE", "").strip()
CLIENT_INSTANCE = os.environ.get("SDMOD_STEAM_CLIENT_INSTANCE", "").strip()


def configure(pair: SteamFriendActivePair) -> None:
    if not HOST_INSTANCE or not CLIENT_INSTANCE:
        raise VerifyFailure(
            "SDMOD_STEAM_HOST_INSTANCE and SDMOD_STEAM_CLIENT_INSTANCE are required"
        )
    replacements = {
        "HOST_ID": pair.host_participant_id,
        "CLIENT_ID": pair.client_participant_id,
        "HOST_PIPE": HOST_ENDPOINT,
        "CLIENT_PIPE": CLIENT_ENDPOINT,
        "lua": pair.lua,
    }
    for module in (local_sync, upgrades, offers, powerups):
        for name, value in replacements.items():
            if hasattr(module, name):
                setattr(module, name, value)


def stage(message: str) -> None:
    print(f"[steam-powerup] {message}", flush=True)


def run(
    pair: SteamFriendActivePair,
    timeout: float,
    selected_cases: set[str] | None,
) -> dict[str, Any]:
    stage("discovering active friend pair")
    pair_state = pair.discover()
    require_shared_test_run(pair_state)
    configure(pair)

    result: dict[str, Any] = {
        "ok": False,
        "transport": "steam_friend",
        "same_machine": PAIR_BACKEND == "wsl",
        "pair": pair_state,
        "test_godmode": disable_runtime_test_godmode(pair),
        "quiet_progression_test_mode": (
            upgrades.enable_quiet_progression_test_mode()
        ),
        "pair_ready": offers.wait_for_pair_ready(timeout),
    }
    stage("running stock powerup matrix")
    result["cases"] = powerups.run_cases(timeout, selected_cases)
    expected = selected_cases or set(powerups.CASE_NAMES)
    if set(result["cases"]) != expected:
        raise VerifyFailure(
            f"powerup matrix omitted cases: expected={sorted(expected)} "
            f"actual={sorted(result['cases'])}"
        )
    result["ok"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=25.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--case",
        action="append",
        choices=powerups.CASE_NAMES,
        dest="selected_cases",
        help="Run only the named case; may be repeated.",
    )
    args = parser.parse_args()

    started_at = time.time()
    pair = SteamFriendActivePair()
    result: dict[str, Any] = {"ok": False}
    return_code = 1
    try:
        result = run(
            pair,
            args.timeout,
            set(args.selected_cases) if args.selected_cases else None,
        )
        result["new_crash_artifacts"] = find_new_crash_artifacts(started_at)
        if result["new_crash_artifacts"]:
            raise VerifyFailure("new crash artifacts appeared during powerup tests")
        return_code = 0
    except (VerifyFailure, subprocess.TimeoutExpired, ValueError, OSError) as exc:
        result["error"] = str(exc)
        result["error_type"] = type(exc).__name__
        result["traceback"] = traceback.format_exc()
        result["new_crash_artifacts"] = find_new_crash_artifacts(started_at)
    finally:
        pair.close()
        result = pair.redact(result)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    print(
        json.dumps(
            {
                "ok": result.get("ok", False),
                "error": result.get("error"),
                "cases": sorted(result.get("cases", {})),
                "new_crash_artifacts": result.get("new_crash_artifacts", []),
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
