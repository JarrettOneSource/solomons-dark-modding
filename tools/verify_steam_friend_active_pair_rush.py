#!/usr/bin/env python3
"""Verify Rush on an already-running Windows/Proton Steam friend pair."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import traceback
from functools import partial
from pathlib import Path
from typing import Any

import verify_multiplayer_rush_behavior_sync as rush
import verify_steam_friend_real_input_control as real_input_control
from steam_friend_active_pair import ROOT, SteamFriendActivePair
from steam_friend_behavior_context import (
    configure_behavior_context,
    require_shared_test_run,
)
from steam_friend_hub_automation import (
    hold_proton_key,
    proton_input_process_id,
)
from verify_local_multiplayer_sync import VerifyFailure
from verify_steam_friend_active_pair_progression import find_new_crash_artifacts


DEFAULT_OUTPUT = ROOT / "runtime/steam_friend_active_pair_rush.json"
HOST_INSTANCE = os.environ.get("SDMOD_STEAM_HOST_INSTANCE", "").strip()


def resolve_keyboard_drivers() -> dict[str, rush.KeyboardDriver]:
    if not HOST_INSTANCE:
        raise VerifyFailure("SDMOD_STEAM_HOST_INSTANCE is required")
    return {
        "host_owned": partial(
            rush.hold_real_key,
            real_input_control.windows_process_id(HOST_INSTANCE),
        ),
        "client_owned": partial(
            hold_proton_key,
            proton_input_process_id(),
        ),
    }


def compact_summary(output: dict[str, Any], output_path: Path) -> dict[str, Any]:
    keyboard = output.get("real_keyboard_contract", {})
    return {
        "ok": output.get("ok", False),
        "active_step": output.get("active_step"),
        "error": output.get("error"),
        "directions": sorted(keyboard),
        "ranked_rush_step_ratios": {
            name: values.get("ranked_rush_step_ratio")
            for name, values in keyboard.items()
        },
        "concentrate_motion_ratios": output.get(
            "concentrate_motion_ratios", {}
        ),
        "new_crash_artifacts": output.get("new_crash_artifacts", []),
        "output": str(output_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument(
        "--minimum-concentrate-motion-ratio",
        type=float,
        default=1.15,
    )
    parser.add_argument(
        "--minimum-ranked-rush-step-ratio",
        type=float,
        default=1.30,
    )
    parser.add_argument(
        "--native-rush-evidence",
        type=Path,
        default=rush.NATIVE_RUSH_EVIDENCE,
    )
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
        configure_behavior_context(pair)

        output["active_step"] = "validate_native_evidence"
        native_evidence = rush.load_native_rush_evidence(
            args.native_rush_evidence
        )
        output["native_rush_evidence"] = native_evidence
        keyboard_drivers = resolve_keyboard_drivers()

        output["active_step"] = "prepare_progression"
        output["quiet_progression_test_mode"] = (
            rush.enable_quiet_progression_test_mode()
        )
        output["post_run_progression_ready"] = (
            rush.wait_for_post_run_progression_ready(args.timeout)
        )
        output["quiet_stock_input_mode"] = rush.enable_quiet_stock_input_mode(
            args.timeout
        )

        output["active_step"] = "rush_matrix"
        output.update(
            rush.run_prepared_rush_matrix(
                keyboard_drivers,
                args.timeout,
                native_evidence,
                minimum_concentrate_motion_ratio=(
                    args.minimum_concentrate_motion_ratio
                ),
                minimum_ranked_rush_step_ratio=(
                    args.minimum_ranked_rush_step_ratio
                ),
            )
        )

        output["new_crash_artifacts"] = find_new_crash_artifacts(started_at)
        if output["new_crash_artifacts"]:
            raise VerifyFailure("new crash artifacts appeared during Rush test")
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
