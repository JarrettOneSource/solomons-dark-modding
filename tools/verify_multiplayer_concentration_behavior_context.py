#!/usr/bin/env python3
"""Verify distinct player Concentrate contexts survive remote behavior replay."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import time
from pathlib import Path
from typing import Any

from multiplayer_progression_probe import query_progression_snapshot
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    CLIENT_PIPE,
    HOST_ID,
    HOST_NAME,
    HOST_PIPE,
    VerifyFailure,
    disable_bots,
    launch_pair,
    lua,
    parse_key_values,
    start_host_testrun_and_wait_for_clients,
    stop_games,
    wait_for_remote,
)
from verify_multiplayer_all_upgrade_sync import (
    FLAT_BONEYARD,
    choose_offer,
    enable_quiet_progression_test_mode,
    new_crash_artifacts,
    publish_deterministic_offer,
    wait_for_offer,
    wait_for_pause,
    wait_for_post_run_progression_ready,
    wait_for_result,
    wait_for_target_parity,
)
from verify_spell_cast_sync import HOST_TO_CLIENT, verify_direction


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "runtime/multiplayer_concentration_behavior_context.json"
HOST_CONCENTRATION_ROW = 57  # Channel
CLIENT_CONCENTRATION_ROW = 59  # Battle Mage


def apply_first_stat(target_id: int, row: int, timeout: float) -> dict[str, Any]:
    target_pipe = HOST_PIPE if target_id == HOST_ID else CLIENT_PIPE
    before = query_progression_snapshot(target_pipe)
    target_level = int(before["native"]["level"]) + 1
    target_experience = int(math.ceil(before["native"]["next_xp_threshold"]))
    before_active = int(before["native"]["entries"][row]["active"])

    publish = publish_deterministic_offer(
        target_id,
        target_level,
        target_experience,
        row,
    )
    offer = wait_for_offer(target_pipe, target_id, target_level, row, timeout)
    pause_active = wait_for_pause(target_id, True, timeout)
    choice = choose_offer(target_pipe, offer["offer_id"], row)
    result = wait_for_result(
        offer["offer_id"],
        target_id,
        target_level,
        row,
        before_active + 1,
        timeout,
    )
    parity = wait_for_target_parity(
        target_id,
        row,
        before_active + 1,
        target_level,
        timeout,
    )
    pause_cleared = wait_for_pause(target_id, False, timeout)
    return {
        "target_participant_id": target_id,
        "row": row,
        "publish": publish,
        "offer": offer,
        "pause_active": pause_active,
        "choice": choice,
        "result": result,
        "parity": parity,
        "pause_cleared": pause_cleared,
    }


def all_views() -> dict[str, dict[str, Any]]:
    return {
        "host_owner": query_progression_snapshot(HOST_PIPE),
        "client_observes_host": query_progression_snapshot(
            CLIENT_PIPE, participant_id=HOST_ID
        ),
        "client_owner": query_progression_snapshot(CLIENT_PIPE),
        "host_observes_client": query_progression_snapshot(
            HOST_PIPE, participant_id=CLIENT_ID
        ),
    }


def compact_context(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "gameplay_slot": snapshot["native"]["gameplay_slot"],
        "process_a": snapshot["native"]["process_concentration_entry_a"],
        "process_b": snapshot["native"]["process_concentration_entry_b"],
        "slot_a": snapshot["native"]["slot_concentration_entry_a"],
        "slot_b": snapshot["native"]["slot_concentration_entry_b"],
        "ledger_a": snapshot["ledger"]["concentration_entry_a"],
        "ledger_b": snapshot["ledger"]["concentration_entry_b"],
        "mana_recovery_multiplier": snapshot["native"]["derived"][
            "mana_recovery_multiplier"
        ],
        "offensive_mana_multiplier": snapshot["native"]["derived"][
            "offensive_mana_multiplier"
        ],
        "row_57": snapshot["native"]["entries"][57],
        "row_59": snapshot["native"]["entries"][59],
    }


def assert_distinct_contexts(views: dict[str, dict[str, Any]]) -> dict[str, Any]:
    expected = {
        "host_owner": (HOST_CONCENTRATION_ROW, HOST_CONCENTRATION_ROW),
        "client_observes_host": (
            CLIENT_CONCENTRATION_ROW,
            HOST_CONCENTRATION_ROW,
        ),
        "client_owner": (CLIENT_CONCENTRATION_ROW, CLIENT_CONCENTRATION_ROW),
        "host_observes_client": (
            HOST_CONCENTRATION_ROW,
            CLIENT_CONCENTRATION_ROW,
        ),
    }
    compact = {label: compact_context(snapshot) for label, snapshot in views.items()}
    mismatches: list[dict[str, Any]] = []
    for label, (expected_process, expected_slot) in expected.items():
        actual = compact[label]
        if int(actual["process_a"]) != expected_process:
            mismatches.append(
                {
                    "view": label,
                    "field": "process_a",
                    "actual": actual["process_a"],
                    "expected": expected_process,
                }
            )
        for field in ("slot_a", "ledger_a"):
            if int(actual[field]) != expected_slot:
                mismatches.append(
                    {
                        "view": label,
                        "field": field,
                        "actual": actual[field],
                        "expected": expected_slot,
                    }
                )
        for field in ("process_b", "slot_b", "ledger_b"):
            if int(actual[field]) != -1:
                mismatches.append(
                    {
                        "view": label,
                        "field": field,
                        "actual": actual[field],
                        "expected": -1,
                    }
                )

    host_recovery = float(compact["host_owner"]["mana_recovery_multiplier"])
    client_recovery = float(compact["client_owner"]["mana_recovery_multiplier"])
    host_mana_cost = float(compact["host_owner"]["offensive_mana_multiplier"])
    client_mana_cost = float(compact["client_owner"]["offensive_mana_multiplier"])
    if host_recovery <= client_recovery + 0.1:
        mismatches.append(
            {
                "field": "participant_specific_channel_behavior",
                "host": host_recovery,
                "client": client_recovery,
            }
        )
    if client_mana_cost >= host_mana_cost - 0.01:
        mismatches.append(
            {
                "field": "participant_specific_battle_mage_behavior",
                "host": host_mana_cost,
                "client": client_mana_cost,
            }
        )
    if mismatches:
        raise VerifyFailure(f"distinct Concentrate contexts diverged: {mismatches}")
    return {"views": compact, "mismatches": []}


def corrupt_remote_runtime_lane(observer_pipe: str, participant_id: int) -> dict[str, str]:
    code = f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local bot = sd.bots.get_participant_state({participant_id})
local selection = sd.gameplay.get_selection_debug_state()
local slot = tonumber(bot and bot.gameplay_slot) or -1
local table_address = tonumber(selection and selection.table_address) or 0
local address_a = table_address + (16 + slot) * 4
local address_b = table_address + (20 + slot) * 4
emit('slot', slot)
emit('table', table_address)
emit('before_a', table_address ~= 0 and sd.debug.read_i32(address_a) or -999)
emit('before_b', table_address ~= 0 and sd.debug.read_i32(address_b) or -999)
emit('write_a', table_address ~= 0 and sd.debug.write_i32(address_a, -1) or false)
emit('write_b', table_address ~= 0 and sd.debug.write_i32(address_b, -1) or false)
emit('after_a', table_address ~= 0 and sd.debug.read_i32(address_a) or -999)
emit('after_b', table_address ~= 0 and sd.debug.read_i32(address_b) or -999)
"""
    values = parse_key_values(lua(observer_pipe, code, timeout=8.0))
    if values.get("write_a") != "true" or values.get("write_b") != "true":
        raise VerifyFailure(
            f"failed to corrupt remote Concentrate runtime lane: {values}"
        )
    return values


def wait_for_runtime_lane_repair(
    observer_pipe: str,
    participant_id: int,
    expected_a: int,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        snapshot = query_progression_snapshot(
            observer_pipe,
            participant_id=participant_id,
        )
        last = compact_context(snapshot)
        if int(last["slot_a"]) == expected_a and int(last["slot_b"]) == -1:
            return last
        time.sleep(0.1)
    raise VerifyFailure(
        f"remote Concentrate runtime lane was not repaired for {participant_id}: {last}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=40.0)
    parser.add_argument("--keep-open", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    started_at = time.time()
    output: dict[str, Any] = {"ok": False}
    return_code = 1
    try:
        stop_games()
        output["launch"] = launch_pair(
            preset="map_create_fire_mind_hub",
            god_mode=True,
            test_survival_boneyard_override=FLAT_BONEYARD,
        )
        disable_bots()
        output["hub_ready"] = {
            "host": wait_for_remote(
                HOST_PIPE, CLIENT_ID, CLIENT_NAME, "hub", args.timeout
            ),
            "client": wait_for_remote(
                CLIENT_PIPE, HOST_ID, HOST_NAME, "hub", args.timeout
            ),
        }
        output["run_entry"] = start_host_testrun_and_wait_for_clients(args.timeout)
        output["quiet_progression_test_mode"] = enable_quiet_progression_test_mode()
        output["post_run_progression_ready"] = wait_for_post_run_progression_ready(
            args.timeout
        )

        output["host_channel"] = apply_first_stat(
            HOST_ID, HOST_CONCENTRATION_ROW, args.timeout
        )
        output["client_battle_mage"] = apply_first_stat(
            CLIENT_ID, CLIENT_CONCENTRATION_ROW, args.timeout
        )
        output["distinct_before_corruption"] = assert_distinct_contexts(all_views())

        output["corruption"] = {
            "host_observes_client": corrupt_remote_runtime_lane(
                HOST_PIPE, CLIENT_ID
            ),
            "host_observes_client_repaired": wait_for_runtime_lane_repair(
                HOST_PIPE,
                CLIENT_ID,
                CLIENT_CONCENTRATION_ROW,
                args.timeout,
            ),
            "client_observes_host": corrupt_remote_runtime_lane(
                CLIENT_PIPE, HOST_ID
            ),
            "client_observes_host_repaired": wait_for_runtime_lane_repair(
                CLIENT_PIPE,
                HOST_ID,
                HOST_CONCENTRATION_ROW,
                args.timeout,
            ),
        }
        output["distinct_after_repair"] = assert_distinct_contexts(all_views())

        # Host is the Fire participant in this deterministic pair. A real remote
        # Fireball replay exercises the participant-scoped native tick/cast path
        # while the observing client keeps its distinct Battle Mage context.
        output["remote_fire_cast"] = verify_direction(HOST_TO_CLIENT)
        output["distinct_after_remote_cast"] = assert_distinct_contexts(all_views())

        crashes = new_crash_artifacts(started_at)
        output["new_crash_artifacts"] = crashes
        if crashes:
            raise VerifyFailure(
                f"new crash artifacts appeared during Concentrate context test: {crashes}"
            )
        output["ok"] = True
        return_code = 0
    except (VerifyFailure, subprocess.TimeoutExpired, ValueError, OSError) as exc:
        output["error"] = str(exc)
        output["new_crash_artifacts"] = new_crash_artifacts(started_at)
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(output, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if not args.keep_open:
            stop_games()

    print(
        json.dumps(
            {
                "ok": output.get("ok", False),
                "error": output.get("error"),
                "new_crash_artifacts": output.get("new_crash_artifacts", []),
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
