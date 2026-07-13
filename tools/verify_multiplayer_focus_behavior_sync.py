#!/usr/bin/env python3
"""Verify Focus changes real secondary recharge cadence for both owners."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
    read_log,
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


def log_after(path: Path, offset: int) -> str:
    return read_log(path)[offset:]


def press_secondary_belt_slot(direction: Direction, belt_slot: int) -> dict[str, str]:
    if belt_slot < 0 or belt_slot >= 8:
        raise VerifyFailure(f"{direction.name} invalid secondary belt slot: {belt_slot}")
    binding = f"belt_slot_{belt_slot + 1}"
    values = parse_key_values(
        lua(
            direction.source_pipe,
            f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local ok, result = pcall(sd.input.press_key, {json.dumps(binding)})
emit('pcall_ok', ok)
emit('result', result)
""",
            timeout=5.0,
        )
    )
    if values.get("pcall_ok") != "true" or values.get("result") != "true":
        raise VerifyFailure(
            f"{direction.name} could not inject native {binding}: {values}"
        )
    return values


def accepted_marker(direction: Direction) -> str:
    return (
        "Multiplayer local secondary cast queued from native dispatcher. "
        f"actor="
    )


def wait_for_next_accept(
    direction: Direction,
    source_offset: int,
    accepted_before: int,
    timeout: float,
    belt_slot: int,
) -> tuple[float, int, int]:
    started = time.monotonic()
    accepted = accepted_before
    rejected = 0
    accept_token = accepted_marker(direction)
    reject_token = "Multiplayer local secondary cast rejected by native dispatcher."
    deadline = started + timeout
    while time.monotonic() < deadline:
        press_secondary_belt_slot(direction, belt_slot)
        time.sleep(0.10)
        current = log_after(direction.source_log, source_offset)
        accepted = current.count(accept_token)
        rejected = current.count(reject_token)
        if accepted > accepted_before:
            return time.monotonic() - started, accepted, rejected
    raise VerifyFailure(
        f"{direction.name} secondary did not recharge within {timeout:.1f}s; "
        f"accepted={accepted} rejected={rejected}"
    )


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
    source_offset = len(read_log(direction.source_log))
    observer_offset = len(read_log(direction.observer_log))

    # The previous stage may still be cooling down. Obtain one accepted cast as
    # a deterministic start boundary, then time complete recharge intervals.
    _, accepted, rejected = wait_for_next_accept(
        direction,
        source_offset,
        accepted_before=0,
        timeout=timeout,
        belt_slot=belt_slot,
    )
    intervals: list[float] = []
    for _ in range(TRIAL_COUNT):
        elapsed, accepted, rejected = wait_for_next_accept(
            direction,
            source_offset,
            accepted_before=accepted,
            timeout=timeout,
            belt_slot=belt_slot,
        )
        intervals.append(elapsed)

    remote_count = wait_for_remote_delivery(
        direction,
        observer_offset,
        expected_count=TRIAL_COUNT + 1,
    )
    snapshot = query_progression_snapshot(direction.source_pipe)
    return {
        "resources": resources,
        "secondary_row": TEST_SECONDARY_ROW,
        "belt_slot": belt_slot,
        "belt": belt,
        "intervals_seconds": intervals,
        "median_seconds": statistics.median(intervals),
        "accepted_count": accepted,
        "rejected_count": rejected,
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
            return result
        time.sleep(0.1)
    raise VerifyFailure(f"native combat prelude did not activate: {last}")


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

        ratios: dict[str, float] = {}
        for direction in DIRECTIONS:
            baseline = float(output["baseline"][direction.name]["median_seconds"])
            upgraded = float(output["upgraded"][direction.name]["median_seconds"])
            if baseline < 0.65:
                raise VerifyFailure(
                    f"{direction.name} baseline recharge was bypassed by the test harness: "
                    f"{baseline:.3f}s"
                )
            ratio = upgraded / baseline
            ratios[direction.name] = ratio
            multiplier = float(
                output["upgraded"][direction.name]["secondary_recharge_multiplier"]
            )
            if multiplier < 1.99:
                raise VerifyFailure(
                    f"{direction.name} Focus native multiplier is not maxed: {multiplier}"
                )
            if ratio >= 0.72:
                raise VerifyFailure(
                    f"{direction.name} Focus did not materially shorten real recharge: "
                    f"baseline={baseline:.3f}s upgraded={upgraded:.3f}s ratio={ratio:.3f}"
                )
        if abs(ratios["host_owned"] - ratios["client_owned"]) > 0.15:
            raise VerifyFailure(f"Focus behavior diverged by owner: {ratios}")
        output["recharge_ratios"] = ratios

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
