#!/usr/bin/env python3
"""Verify Focus changes real secondary recharge cadence for both owners."""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from multiplayer_log_probe import log_after, log_position
from multiplayer_progression_probe import query_progression_snapshot
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_PIPE,
    HOST_ID,
    HOST_PIPE,
    VerifyFailure,
    lua,
    parse_key_values,
    stop_games,
)
from verify_multiplayer_all_stat_sync import apply_stat_batch, load_stat_contract_values
from verify_multiplayer_all_upgrade_sync import (
    build_and_verify_catalog,
    choose_offer,
    load_skill_configs,
    new_crash_artifacts,
    publish_deterministic_offer,
    verify_untargeted_progression_unchanged,
    wait_for_offer,
    wait_for_pause,
    wait_for_catalog_views,
    wait_for_post_run_progression_ready,
    wait_for_result,
    wait_for_target_parity,
)
from verify_multiplayer_fireball_explode_effect_sync import launch_pair_ready
from verify_player_health_death_sync import set_local_player_vitals
from verify_real_input_spell_cast_sync import (
    CLIENT_LOG,
    HOST_LOG,
)


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "runtime/multiplayer_focus_behavior_sync.json"
FOCUS_ROW = 60
BELT_BATCH_REGRESSION_ROW = 48  # Teleport: a two-rank choice must add one belt slot.
TEST_SECONDARY_ROW = 15  # Phasing has a finite one-second native cooldown.
TEST_SECONDARY_MAX_RANK = 1
TRIAL_COUNT = 3


@dataclass(frozen=True)
class Direction:
    name: str
    process_role: str
    source_id: int
    source_pipe: str
    source_log: Path
    observer_log: Path


DIRECTIONS = (
    Direction("host_owned", "host", HOST_ID, HOST_PIPE, HOST_LOG, CLIENT_LOG),
    Direction("client_owned", "client", CLIENT_ID, CLIENT_PIPE, CLIENT_LOG, HOST_LOG),
)


def secondary_binding_details(belt_slot: int) -> tuple[str, bool, str]:
    if belt_slot < 0 or belt_slot >= 8:
        raise VerifyFailure(f"invalid secondary belt slot: {belt_slot}")

    binding = f"belt_slot_{belt_slot + 1}"
    mouse_backed = belt_slot == 0
    consumption_marker = (
        "Injected gameplay mouse-right click."
        if mouse_backed
        else "Consumed queued gameplay keyboard edge."
    )
    return binding, mouse_backed, consumption_marker


def queue_secondary_belt_slot(
    direction: Direction,
    belt_slot: int,
) -> dict[str, str]:
    """Queue one exact live binding without waiting on mirrored log delivery."""
    binding, mouse_backed, _ = secondary_binding_details(belt_slot)
    cast = parse_key_values(
        lua(
            direction.source_pipe,
            f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local ok, value = pcall(sd.input.press_binding, {json.dumps(binding)})
emit('pcall_ok', ok)
emit('result', value)
""",
            timeout=5.0,
        )
    )
    if cast.get("pcall_ok") != "true" or cast.get("result") != "true":
        raise VerifyFailure(
            f"{direction.name} could not inject native {binding}: {cast}"
        )
    return {
        "binding": binding,
        "input_kind": "mouse_right" if mouse_backed else "keyboard",
        "pcall_ok": cast["pcall_ok"],
        "result": cast["result"],
    }


def cast_secondary_belt_slot(
    direction: Direction,
    belt_slot: int,
    timeout: float,
) -> dict[str, str]:
    """Cast a secondary belt entry through its exact live stock binding."""
    binding, _, consumption_marker = secondary_binding_details(belt_slot)
    source_offset = log_position(direction.source_log)
    cast = queue_secondary_belt_slot(direction, belt_slot)
    deadline = time.monotonic() + timeout
    while True:
        if consumption_marker in log_after(direction.source_log, source_offset):
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0.0:
            raise VerifyFailure(
                f"{direction.name} native {binding} activation was not consumed"
            )
        time.sleep(min(0.05, remaining))
    return {**cast, "consumed": "true"}


def parse_secondary_accept_times(
    log_text: str,
    belt_slot: int,
) -> list[datetime]:
    pattern = re.compile(
        r"^\[(?P<timestamp>[^\]]+)\] "
        r"Multiplayer local secondary cast queued from native dispatcher\. "
        rf".*?skill_entry={TEST_SECONDARY_ROW} belt_slot={belt_slot}\b",
        re.MULTILINE,
    )
    return [
        datetime.fromisoformat(match.group("timestamp"))
        for match in pattern.finditer(log_text)
    ]


def queue_until_accepted_casts(
    direction: Direction,
    source_offset: int,
    belt_slot: int,
    required_count: int,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    queued_count = 0
    input_kinds: set[str] = set()
    last_log = ""
    accepted_times: list[datetime] = []
    while True:
        last_log = log_after(direction.source_log, source_offset)
        accepted_times = parse_secondary_accept_times(last_log, belt_slot)
        if len(accepted_times) >= required_count:
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0.0:
            break
        queued = queue_secondary_belt_slot(direction, belt_slot)
        queued_count += 1
        input_kinds.add(queued["input_kind"])
        time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))

    if len(accepted_times) < required_count:
        raise VerifyFailure(
            f"{direction.name} secondary produced {len(accepted_times)}/"
            f"{required_count} native accepts within {timeout:.1f}s; "
            f"queued_inputs={queued_count}"
        )
    reject_token = (
        "Multiplayer local secondary cast rejected by native dispatcher."
    )
    rejected = sum(
        reject_token in line
        and f"skill_entry={TEST_SECONDARY_ROW}" in line
        and f"belt_slot={belt_slot}" in line
        for line in last_log.splitlines()
    )
    return {
        "accepted_times": accepted_times,
        "accepted_count": len(accepted_times),
        "rejected_count": rejected,
        "queued_input_count": queued_count,
        "input_kinds": sorted(input_kinds),
    }


def wait_for_remote_delivery(
    direction: Direction,
    observer_offset: int,
    expected_count: int,
    timeout: float = 8.0,
) -> int:
    marker = (
        "Multiplayer remote secondary cast queued. "
        f"participant_id={direction.source_id}"
    )
    deadline = time.monotonic() + timeout
    count = 0
    while time.monotonic() < deadline:
        count = log_after(direction.observer_log, observer_offset).count(marker)
        if count >= expected_count:
            return count
        time.sleep(0.05)
    raise VerifyFailure(
        f"{direction.name} observer received {count}/{expected_count} secondary casts"
    )


def measure_recharge(
    direction: Direction,
    timeout: float,
) -> dict[str, Any]:
    # Keep resource availability out of the cadence result without enabling
    # god mode, which bypasses other native spell costs.
    resources = set_local_player_vitals(direction.source_pipe, 10000.0, 10000.0)
    snapshot_before = query_progression_snapshot(direction.source_pipe)
    belt = snapshot_before["loadout"]["secondary_entry_indices"]
    if TEST_SECONDARY_ROW not in belt:
        raise VerifyFailure(
            f"{direction.name} Phasing is missing from native belt: {belt}"
        )
    belt_slot = belt.index(TEST_SECONDARY_ROW)
    source_offset = log_position(direction.source_log)
    observer_offset = log_position(direction.observer_log)

    required_count = TRIAL_COUNT + 1
    cadence = queue_until_accepted_casts(
        direction,
        source_offset,
        belt_slot=belt_slot,
        required_count=required_count,
        timeout=timeout,
    )
    sample_times = cadence["accepted_times"][:required_count]
    intervals = [
        (current - previous).total_seconds()
        for previous, current in zip(sample_times, sample_times[1:])
    ]

    remote_count = wait_for_remote_delivery(
        direction,
        observer_offset,
        expected_count=required_count,
    )
    snapshot = query_progression_snapshot(direction.source_pipe)
    return {
        "resources": resources,
        "secondary_row": TEST_SECONDARY_ROW,
        "belt_slot": belt_slot,
        "belt": belt,
        "queued_input_count": cadence["queued_input_count"],
        "input_kinds": cadence["input_kinds"],
        "native_accept_timestamps": [
            timestamp.isoformat(timespec="milliseconds")
            for timestamp in sample_times
        ],
        "intervals_seconds": intervals,
        "median_seconds": statistics.median(intervals),
        "accepted_count": cadence["accepted_count"],
        "rejected_count": cadence["rejected_count"],
        "remote_delivery_count": remote_count,
        "secondary_recharge_multiplier": snapshot["native"]["derived"][
            "secondary_recharge_multiplier"
        ],
    }


def acquire_secondary_to_rank(
    direction: Direction,
    entry_row: int,
    desired_active: int,
    timeout: float,
) -> dict[str, Any]:
    target_pipe = direction.source_pipe
    untargeted_id = CLIENT_ID if direction.source_id == HOST_ID else HOST_ID
    untargeted_pipe = CLIENT_PIPE if direction.source_id == HOST_ID else HOST_PIPE
    before = query_progression_snapshot(target_pipe)
    before_active = int(before["native"]["entries"][entry_row]["active"])
    remaining = desired_active - before_active
    already_maxed = remaining <= 0

    # The debug-authority API intentionally mirrors the native offer's maximum
    # two-rank payload. Reach the requested rank through real accepted offers
    # instead of bypassing that contract with a direct progression write.
    steps: list[dict[str, Any]] = []
    current = before
    current_active = before_active
    while remaining > 0:
        apply_count = min(2, remaining)
        expected_active = current_active + apply_count
        untargeted_before = query_progression_snapshot(untargeted_pipe)
        target_level = int(current["native"]["level"]) + 1
        target_experience = int(math.ceil(current["native"]["next_xp_threshold"]))
        publish = publish_deterministic_offer(
            direction.source_id,
            target_level,
            target_experience,
            entry_row,
            apply_count,
        )
        offer = wait_for_offer(
            target_pipe,
            direction.source_id,
            target_level,
            entry_row,
            timeout,
            apply_count,
        )
        pause_active = wait_for_pause(direction.source_id, True, timeout)
        choice = choose_offer(target_pipe, offer["offer_id"], entry_row)
        result = wait_for_result(
            offer["offer_id"],
            direction.source_id,
            target_level,
            entry_row,
            expected_active,
            timeout,
            apply_count,
        )
        parity = wait_for_target_parity(
            direction.source_id,
            entry_row,
            expected_active,
            target_level,
            timeout,
        )
        pause_cleared = wait_for_pause(direction.source_id, False, timeout)
        untargeted_after = query_progression_snapshot(untargeted_pipe)
        isolation = verify_untargeted_progression_unchanged(
            untargeted_id,
            untargeted_before,
            untargeted_after,
        )
        steps.append(
            {
                "apply_count": apply_count,
                "expected_active": expected_active,
                "publish": publish,
                "offer": offer,
                "pause_active": pause_active,
                "choice": choice,
                "result": result,
                "parity": parity,
                "pause_cleared": pause_cleared,
                "untargeted_isolation": isolation,
            }
        )
        current = query_progression_snapshot(target_pipe)
        current_active = expected_active
        remaining -= apply_count

    owner = query_progression_snapshot(target_pipe)
    observer_pipe = CLIENT_PIPE if direction.source_id == HOST_ID else HOST_PIPE
    observer = query_progression_snapshot(
        observer_pipe,
        participant_id=direction.source_id,
    )
    owner_belt = owner["loadout"]["secondary_entry_indices"]
    observer_belt = observer["loadout"]["secondary_entry_indices"]
    owner_slot_count = owner_belt.count(entry_row)
    observer_slot_count = observer_belt.count(entry_row)
    if (
        owner_belt != observer_belt
        or owner_slot_count != 1
        or observer_slot_count != 1
    ):
        raise VerifyFailure(
            f"{direction.name} secondary row {entry_row} belt ownership did not converge: "
            f"owner={owner_belt} observer={observer_belt} "
            f"owner_slots={owner_slot_count} observer_slots={observer_slot_count}"
        )
    return {
        "entry_row": entry_row,
        "desired_active": desired_active,
        "already_maxed": already_maxed,
        "steps": steps,
        "owner_belt": owner_belt,
        "observer_belt": observer_belt,
        "belt_slot": owner_belt.index(entry_row),
        "owner_slot_count": owner_slot_count,
        "observer_slot_count": observer_slot_count,
    }


def acquire_test_secondary(direction: Direction, timeout: float) -> dict[str, Any]:
    # Exercise the two-rank acquisition path that previously duplicated a
    # secondary belt entry, then acquire the repeatable one-second Phasing
    # witness used for the actual Focus cadence measurement.
    return {
        "two_rank_belt_regression": acquire_secondary_to_rank(
            direction,
            BELT_BATCH_REGRESSION_ROW,
            2,
            timeout,
        ),
        "cadence_secondary": acquire_secondary_to_rank(
            direction,
            TEST_SECONDARY_ROW,
            TEST_SECONDARY_MAX_RANK,
            timeout,
        ),
    }


def enable_unsuppressed_combat_prelude(timeout: float) -> dict[str, Any]:
    """Activate native player controls without starting ambient waves."""
    result: dict[str, Any] = {"requests": {}}
    for label, pipe_name in (("host", HOST_PIPE), ("client", CLIENT_PIPE)):
        request = parse_key_values(
            lua(
                pipe_name,
                "local function emit(k,v) print(k .. '=' .. tostring(v)) end; "
                "emit('ok', sd.gameplay.enable_combat_prelude())",
                timeout=8.0,
            )
        )
        if request.get("ok") != "true":
            raise VerifyFailure(
                f"{label} could not enable native combat prelude: {request}"
            )
        result["requests"][label] = request

    deadline = time.monotonic() + timeout
    last: dict[str, dict[str, str]] = {}
    state_code = """
local function emit(k,v) print(k .. '=' .. tostring(v)) end
local state = sd.gameplay.get_combat_state()
emit('valid', state ~= nil)
emit('active', state and state.active or false)
emit('wave_index', state and state.wave_index or 0)
emit('wave_counter', state and state.wave_counter or 0)
"""
    while time.monotonic() < deadline:
        last = {
            label: parse_key_values(lua(pipe_name, state_code, timeout=8.0))
            for label, pipe_name in (("host", HOST_PIPE), ("client", CLIENT_PIPE))
        }
        if all(
            state.get("valid") == "true" and state.get("active") == "true"
            for state in last.values()
        ):
            result["states"] = last
            result["manual_spawner_release"] = {}
            release_code = """
local function emit(k,v) print(k .. '=' .. tostring(v)) end
local ok, active = sd.gameplay.set_manual_enemy_spawner_test_mode(false)
emit('ok', ok)
emit('active', active)
"""
            for label, pipe_name in (("host", HOST_PIPE), ("client", CLIENT_PIPE)):
                release = parse_key_values(lua(pipe_name, release_code, timeout=8.0))
                if release.get("ok") != "true" or release.get("active") != "false":
                    raise VerifyFailure(
                        f"{label} could not release manual-spawner control "
                        f"suppression after combat prelude: {release}"
                    )
                result["manual_spawner_release"][label] = release
            return result
        time.sleep(0.1)
    raise VerifyFailure(f"native combat prelude did not activate: {last}")


def verify_recharge_contracts(
    directions: tuple[Direction, ...],
    baseline: dict[str, dict[str, Any]],
    upgraded: dict[str, dict[str, Any]],
) -> dict[str, float]:
    ratios: dict[str, float] = {}
    for direction in directions:
        baseline_seconds = float(baseline[direction.name]["median_seconds"])
        upgraded_seconds = float(upgraded[direction.name]["median_seconds"])
        if baseline_seconds < 0.65:
            raise VerifyFailure(
                f"{direction.name} baseline recharge was bypassed by the test "
                f"harness: {baseline_seconds:.3f}s"
            )
        ratio = upgraded_seconds / baseline_seconds
        ratios[direction.name] = ratio
        multiplier = float(
            upgraded[direction.name]["secondary_recharge_multiplier"]
        )
        if multiplier < 1.99:
            raise VerifyFailure(
                f"{direction.name} Focus native multiplier is not maxed: "
                f"{multiplier}"
            )
        if ratio >= 0.72:
            raise VerifyFailure(
                f"{direction.name} Focus did not materially shorten real recharge: "
                f"baseline={baseline_seconds:.3f}s "
                f"upgraded={upgraded_seconds:.3f}s ratio={ratio:.3f}"
            )
    if abs(ratios["host_owned"] - ratios["client_owned"]) > 0.15:
        raise VerifyFailure(f"Focus behavior diverged by owner: {ratios}")
    return ratios


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=18.0)
    parser.add_argument("--keep-open", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    started_at = time.time()
    output: dict[str, Any] = {"ok": False}
    return_code = 1
    try:
        startup = launch_pair_ready(
            args.timeout,
            god_mode=False,
            manual_combat=False,
            prearm_manual_spawner=True,
        )
        output["launch"] = startup["launch"]
        output["combat_prelude"] = enable_unsuppressed_combat_prelude(args.timeout)
        output["quiet_progression_test_mode"] = {
            "enabled": False,
            "reason": "native secondary cadence requires unsuppressed player control",
        }
        output["post_run_progression_ready"] = wait_for_post_run_progression_ready(
            args.timeout
        )
        catalog_result = build_and_verify_catalog(
            wait_for_catalog_views(args.timeout),
            load_skill_configs(),
        )
        catalog = catalog_result["catalog"]
        contract_values = load_stat_contract_values(catalog)
        initial = {
            HOST_ID: query_progression_snapshot(HOST_PIPE),
            CLIENT_ID: query_progression_snapshot(CLIENT_PIPE),
        }
        output["test_secondary_acquisition"] = {
            direction.name: acquire_test_secondary(direction, args.timeout)
            for direction in DIRECTIONS
        }

        output["baseline"] = {
            direction.name: measure_recharge(direction, args.timeout)
            for direction in DIRECTIONS
        }
        output["focus_upgrades"] = {
            direction.name: apply_stat_batch(
                catalog,
                FOCUS_ROW,
                direction.source_id,
                1,
                initial,
                contract_values,
                args.timeout,
            )
            for direction in DIRECTIONS
        }
        output["upgraded"] = {
            direction.name: measure_recharge(direction, args.timeout)
            for direction in DIRECTIONS
        }

        output["recharge_ratios"] = verify_recharge_contracts(
            DIRECTIONS,
            output["baseline"],
            output["upgraded"],
        )

        crashes = new_crash_artifacts(started_at)
        output["new_crash_artifacts"] = crashes
        if crashes:
            raise VerifyFailure(f"new crash artifacts during Focus test: {crashes}")
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
                "recharge_ratios": output.get("recharge_ratios"),
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
