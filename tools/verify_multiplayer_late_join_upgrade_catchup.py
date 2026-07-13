#!/usr/bin/env python3
"""Verify a late third client catches up upgraded native player state and behavior."""

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
    THIRD_PIPE,
    VerifyFailure,
    complete_native_create,
    launch_additional_client,
    stop_games,
    wait_for_scene,
)
from verify_multiplayer_all_upgrade_sync import (
    choose_offer,
    enable_quiet_progression_test_mode,
    publish_deterministic_offer,
    wait_for_offer,
    wait_for_pause,
    wait_for_result,
    wait_for_target_parity,
)
from verify_multiplayer_lightning_chaining_effect_sync import (
    CHAINING_OPTION_ID,
    FLAT_BONEYARD,
    enable_flat_manual_cluster_combat,
    launch_pair_ready,
)
from verify_multiplayer_primary_kill_stress import set_manual_spawner_test_mode
from verify_multiplayer_third_observer_upgrade_sync import (
    CLIENT,
    HOST,
    THIRD,
    PARTICIPANTS,
    compact_snapshot,
    new_crash_artifacts,
    verify_native_object_isolation,
    verify_owner_behavior,
    wait_for_all_relationships,
    wait_for_owner_parity,
)
from verify_real_input_spell_cast_sync import detect_instance_pids


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "runtime" / "multiplayer_late_join_upgrade_catchup_current.json"


def apply_pair_chaining(owner: Any, timeout: float) -> dict[str, Any]:
    before = query_progression_snapshot(owner.pipe)
    row = before["native"]["entries"].get(CHAINING_OPTION_ID)
    if row is None:
        raise VerifyFailure(f"{owner.label} is missing Chaining row {CHAINING_OPTION_ID}")
    expected_active = int(row["active"]) + 1
    if expected_active > int(row["statbook_max_level"]):
        raise VerifyFailure(
            f"{owner.label} Chaining is already maxed: "
            f"active={row['active']} max={row['statbook_max_level']}"
        )
    target_level = int(before["native"]["level"]) + 1
    target_experience = int(math.ceil(before["native"]["next_xp_threshold"]))
    publish = publish_deterministic_offer(
        owner.participant_id,
        target_level,
        target_experience,
        CHAINING_OPTION_ID,
    )
    offer = wait_for_offer(
        owner.pipe,
        owner.participant_id,
        target_level,
        CHAINING_OPTION_ID,
        timeout,
    )
    pause_active = wait_for_pause(owner.participant_id, True, timeout)
    choice = choose_offer(owner.pipe, offer["offer_id"], CHAINING_OPTION_ID)
    result = wait_for_result(
        offer["offer_id"],
        owner.participant_id,
        target_level,
        CHAINING_OPTION_ID,
        expected_active,
        timeout,
    )
    pair_parity = wait_for_target_parity(
        owner.participant_id,
        CHAINING_OPTION_ID,
        expected_active,
        target_level,
        timeout,
    )
    pause_cleared = wait_for_pause(owner.participant_id, False, timeout)
    return {
        "owner": owner.label,
        "participant_id": owner.participant_id,
        "before_active": row["active"],
        "expected_active": expected_active,
        "target_level": target_level,
        "target_experience": target_experience,
        "publish": publish,
        "offer": offer,
        "pause_active": pause_active,
        "choice": choice,
        "result": result,
        "pair_parity": pair_parity,
        "pause_cleared": pause_cleared,
    }


def owner_catchup(owner: Any, timeout: float) -> dict[str, Any]:
    current = query_progression_snapshot(owner.pipe)
    active = int(current["native"]["entries"][CHAINING_OPTION_ID]["active"])
    level = int(current["native"]["level"])
    parity = wait_for_owner_parity(
        owner,
        CHAINING_OPTION_ID,
        active,
        level,
        timeout,
    )
    third_view = query_progression_snapshot(
        THIRD_PIPE,
        participant_id=owner.participant_id,
    )
    if third_view["ledger"]["spellbook_revision"] == 0:
        raise VerifyFailure(f"late observer has no spellbook revision for {owner.label}")
    if third_view["ledger"]["statbook_revision"] == 0:
        raise VerifyFailure(f"late observer has no statbook revision for {owner.label}")
    return {
        "owner_label": owner.label,
        "participant_id": owner.participant_id,
        "owner_state": compact_snapshot(current, CHAINING_OPTION_ID),
        "late_observer": compact_snapshot(third_view, CHAINING_OPTION_ID),
        "parity": parity,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--keep-open", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    started_at = time.time()
    output: dict[str, Any] = {"ok": False}
    try:
        startup = launch_pair_ready(min(args.timeout, 45.0))
        output["pair_startup_attempt"] = startup["attempt"]
        output["pair_launch"] = startup["launch"]
        output["pair_hub_ready"] = startup["hub_ready"]
        output["pair_run_entry"] = startup["run_entry"]
        output["pair_run_ready"] = startup["run_ready"]
        output["manual_combat"] = enable_flat_manual_cluster_combat()
        output["quiet_progression_mode"] = enable_quiet_progression_test_mode()
        output["pre_join_upgrades"] = [
            apply_pair_chaining(HOST, args.timeout),
            apply_pair_chaining(CLIENT, args.timeout),
        ]
        output["pre_join_owner_state"] = {
            owner.label: compact_snapshot(
                query_progression_snapshot(owner.pipe),
                CHAINING_OPTION_ID,
            )
            for owner in (HOST, CLIENT)
        }
        before_pids = detect_instance_pids()
        output["process_ids_before_join"] = before_pids
        join_started = time.monotonic()
        output["late_join_launch"] = launch_additional_client(
            preset="create_manual",
            god_mode=True,
            test_survival_boneyard_override=FLAT_BONEYARD,
        )
        output["late_join_create"] = complete_native_create(
            THIRD_PIPE,
            element="fire",
            discipline="mind",
            timeout=args.timeout,
        )
        wait_for_scene(THIRD_PIPE, "testrun", args.timeout)
        output["late_join_relationships"] = wait_for_all_relationships(
            "testrun", args.timeout
        )
        third_manual_mode = set_manual_spawner_test_mode(THIRD_PIPE, True)
        if third_manual_mode.get("ok") != "true" or third_manual_mode.get("active") != "true":
            raise VerifyFailure(
                f"late client did not enter manual-spawner test mode: {third_manual_mode}"
            )
        output["late_join_manual_mode"] = third_manual_mode
        output["late_join_seconds"] = time.monotonic() - join_started
        after_pids = detect_instance_pids()
        output["process_ids_after_join"] = after_pids
        if (
            after_pids.get("host") != before_pids.get("host")
            or after_pids.get("client") != before_pids.get("client")
        ):
            raise VerifyFailure(
                f"late client launch disturbed the existing pair: "
                f"before={before_pids} after={after_pids}"
            )
        if "third" not in after_pids:
            raise VerifyFailure(f"late third process was not detected: {after_pids}")
        output["native_objects"] = verify_native_object_isolation(args.timeout)
        output["catchup"] = {
            owner.label: owner_catchup(owner, args.timeout)
            for owner in (HOST, CLIENT)
        }
        output["behavior"] = [
            verify_owner_behavior(HOST, CLIENT, THIRD, after_pids),
            verify_owner_behavior(CLIENT, HOST, THIRD, after_pids),
        ]
        crashes = new_crash_artifacts(started_at)
        output["new_crash_artifacts"] = crashes
        if crashes:
            raise VerifyFailure(f"new crash artifacts appeared: {crashes}")
        output["summary"] = {
            "existing_pair_preserved": True,
            "late_joined_participant_count": len(PARTICIPANTS),
            "caught_up_upgraded_owners": 2,
            "native_skillbook_catchup_checks": 2,
            "native_statbook_catchup_checks": 2,
            "loadout_and_spell_output_catchup_checks": 2,
            "late_observer_air_chain_behavior_checks": 2,
        }
        output["ok"] = True
        return_code = 0
    except (VerifyFailure, subprocess.TimeoutExpired, ValueError, KeyError) as exc:
        output["error"] = str(exc)
        output["new_crash_artifacts"] = new_crash_artifacts(started_at)
        return_code = 1
    finally:
        if not args.keep_open:
            stop_games()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(output, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    print(
        json.dumps(
            {
                "ok": output.get("ok", False),
                "error": output.get("error", ""),
                "summary": output.get("summary", {}),
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
