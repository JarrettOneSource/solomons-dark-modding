#!/usr/bin/env python3
"""Verify combat-stat behavior on an already-running Steam friend pair."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import time
import traceback
from pathlib import Path
from typing import Any

import multiplayer_progression_probe as progression
import verify_multiplayer_battle_siege_behavior_sync as battle_siege
import verify_multiplayer_faster_caster_behavior_sync as faster_caster
import verify_multiplayer_focus_behavior_sync as focus
import verify_multiplayer_meditation_behavior_sync as meditation
import verify_multiplayer_mindstar_behavior_sync as mindstar
import verify_multiplayer_telekinesis_behavior_sync as telekinesis
import verify_multiplayer_transient_status_sync as transient
from steam_friend_active_pair import (
    CLIENT_ENDPOINT,
    HOST_ENDPOINT,
    ROOT,
    SteamFriendActivePair,
)
from steam_friend_behavior_context import (
    BehaviorContext,
    configure_behavior_context,
    disable_runtime_test_godmode,
    load_progression_inputs,
    require_shared_test_run,
    reset_quiet_arena,
)
from verify_local_multiplayer_sync import VerifyFailure, parse_key_values
from verify_multiplayer_all_stat_sync import compact_snapshot, wait_for_derived_parity
from verify_steam_friend_active_pair_progression import find_new_crash_artifacts


DEFAULT_OUTPUT = ROOT / "runtime/steam_friend_active_pair_combat_stats.json"

PROFILE_SUITES = {
    "general": (
        "transient_status",
        "mindstar",
        "battle_siege",
        "telekinesis",
        "focus",
    ),
    "meditation": ("meditation",),
    "faster-caster": ("faster_caster",),
    "faster-caster-air": ("faster_caster_air",),
}


def require_fresh_combat_profile(
    pair: SteamFriendActivePair,
) -> dict[str, dict[str, Any]]:
    code = r"""
local function emit(k,v) print(k .. '=' .. tostring(v or 0)) end
local state = sd.gameplay.get_combat_state()
emit('valid', state ~= nil)
emit('active', state and state.active or false)
emit('wave_index', state and state.wave_index or 0)
emit('wave_counter', state and state.wave_counter or 0)
"""
    result: dict[str, dict[str, Any]] = {}
    for label, endpoint in (("host", HOST_ENDPOINT), ("client", CLIENT_ENDPOINT)):
        values = parse_key_values(pair.lua(endpoint, code, timeout=8.0))
        wave_index = int(values.get("wave_index", "0"), 0)
        if wave_index != 0:
            raise VerifyFailure(
                f"{label} combat-stat profile reused a run with active stock "
                f"waves (wave_index={wave_index}); launch a fresh run for each "
                "progression-isolated profile"
            )
        result[label] = {
            "valid": values.get("valid") == "true",
            "active": values.get("active") == "true",
            "wave_index": wave_index,
            "wave_counter": int(values.get("wave_counter", "0"), 0),
        }
    return result


def current_progression(pair: SteamFriendActivePair) -> dict[int, dict[str, Any]]:
    return {
        pair.host_participant_id: progression.query_progression_snapshot(
            HOST_ENDPOINT
        ),
        pair.client_participant_id: progression.query_progression_snapshot(
            CLIENT_ENDPOINT
        ),
    }


def assert_concentrated_row(
    label: str,
    owner: dict[str, Any],
    observer: dict[str, Any],
    row: int,
) -> dict[str, Any]:
    views = {
        "owner_ledger": (
            int(owner["ledger"]["concentration_entry_a"]),
            int(owner["ledger"]["concentration_entry_b"]),
        ),
        "owner_process": (
            int(owner["native"]["process_concentration_entry_a"]),
            int(owner["native"]["process_concentration_entry_b"]),
        ),
        "owner_slot": (
            int(owner["native"]["slot_concentration_entry_a"]),
            int(owner["native"]["slot_concentration_entry_b"]),
        ),
        "observer_ledger": (
            int(observer["ledger"]["concentration_entry_a"]),
            int(observer["ledger"]["concentration_entry_b"]),
        ),
        "observer_slot": (
            int(observer["native"]["slot_concentration_entry_a"]),
            int(observer["native"]["slot_concentration_entry_b"]),
        ),
    }
    missing = [name for name, entries in views.items() if row not in entries]
    if missing:
        raise VerifyFailure(
            f"{label} requires a pristine profile with row {row} concentrated; "
            f"missing from {missing}: {views}"
        )
    return views


def run_transient_status(
    context: BehaviorContext,
    timeout: float,
) -> dict[str, Any]:
    directions = {
        direction.name: transient.run_direction(direction, timeout)
        for direction in context.transient_directions
    }
    return {
        "directions": directions,
        "host_mirror_owner_correction": transient.run_host_mirror_owner_correction(
            timeout
        ),
    }


def run_battle_siege(
    context: BehaviorContext,
    catalog: list[dict[str, Any]],
    contract_values: dict[int, dict[str, list[float]]],
    timeout: float,
) -> dict[str, Any]:
    directions = tuple(
        battle_siege.direction_for_owner(owner, {"host": 0, "client": 0})
        for owner in ("host", "client")
    )
    initial = current_progression(context.pair)
    baseline = {
        direction.name: battle_siege.run_cast_trial(direction, "baseline")
        for direction in directions
    }
    battle_upgrades = {
        direction.name: battle_siege.max_stat_for_target(
            catalog,
            battle_siege.BATTLE_MAGE_ROW,
            direction.source_id,
            initial,
            contract_values,
            timeout,
        )
        for direction in directions
    }
    battle_trials = {
        direction.name: battle_siege.run_cast_trial(
            direction,
            "battle_mage_max",
        )
        for direction in directions
    }
    siege_upgrades = {
        direction.name: battle_siege.max_stat_for_target(
            catalog,
            battle_siege.SIEGE_MAGE_ROW,
            direction.source_id,
            initial,
            contract_values,
            timeout,
        )
        for direction in directions
    }
    siege_trials = {
        direction.name: battle_siege.run_cast_trial(
            direction,
            "siege_mage_max",
        )
        for direction in directions
    }
    return {
        "baseline": baseline,
        "battle_mage_upgrades": battle_upgrades,
        "battle_mage": battle_trials,
        "siege_mage_upgrades": siege_upgrades,
        "siege_mage": siege_trials,
        "contracts": battle_siege.verify_behavior_contracts(
            baseline,
            battle_trials,
            siege_trials,
        ),
    }


def run_telekinesis(
    context: BehaviorContext,
    catalog: list[dict[str, Any]],
    contract_values: dict[int, dict[str, list[float]]],
    timeout: float,
) -> dict[str, Any]:
    geometry = telekinesis.select_geometry()
    initial = current_progression(context.pair)
    return {
        "geometry": geometry,
        "directions": {
            direction.name: telekinesis.run_direction(
                direction,
                geometry,
                catalog,
                initial,
                contract_values,
                timeout,
            )
            for direction in context.telekinesis_directions
        },
    }


def run_meditation(
    context: BehaviorContext,
    catalog: list[dict[str, Any]],
    contract_values: dict[int, dict[str, list[float]]],
    timeout: float,
) -> dict[str, Any]:
    directions = context.meditation_directions
    initial = current_progression(context.pair)
    baseline = {
        direction.name: meditation.run_trial(
            direction,
            "baseline_stationary",
            moving=False,
            interrupt_with_cast=False,
            timeout=timeout,
        )
        for direction in directions
    }
    upgrades = {
        direction.name: battle_siege.max_stat_for_target(
            catalog,
            meditation.MEDITATION_ROW,
            direction.participant_id,
            initial,
            contract_values,
            timeout,
        )
        for direction in directions
    }
    upgraded_views: dict[str, Any] = {}
    for direction in directions:
        owner, observer = wait_for_derived_parity(direction.participant_id, timeout)
        active = int(owner["native"]["entries"][meditation.MEDITATION_ROW]["active"])
        maximum = int(catalog[meditation.MEDITATION_ROW]["native_max_level"])
        derived = owner["native"]["derived"]
        if active != maximum:
            raise VerifyFailure(
                f"{direction.name} Meditation rank is {active}, expected {maximum}"
            )
        if int(derived["meditation_idle_ticks"]) != 100 or not math.isclose(
            float(derived["meditation_recovery_bonus"]),
            5.0,
            abs_tol=0.002,
        ):
            raise VerifyFailure(
                f"{direction.name} max Meditation native fields are wrong: {derived}"
            )
        upgraded_views[direction.name] = {
            "owner": compact_snapshot(owner, meditation.MEDITATION_ROW),
            "observer": compact_snapshot(observer, meditation.MEDITATION_ROW),
            "concentration": assert_concentrated_row(
                direction.name,
                owner,
                observer,
                meditation.MEDITATION_ROW,
            ),
        }

    stationary = {
        direction.name: meditation.run_trial(
            direction,
            "max_stationary",
            moving=False,
            interrupt_with_cast=True,
            timeout=timeout,
        )
        for direction in directions
    }
    moving = {
        direction.name: meditation.run_trial(
            direction,
            "max_moving",
            moving=True,
            interrupt_with_cast=True,
            timeout=timeout,
        )
        for direction in directions
    }
    behavior = {
        direction.name: meditation.assert_behavior(
            direction,
            baseline[direction.name],
            stationary[direction.name],
            moving[direction.name],
        )
        for direction in directions
    }
    idle_multipliers = [
        float(behavior[direction.name]["idle_multiplier_vs_baseline"])
        for direction in directions
    ]
    if max(idle_multipliers) / min(idle_multipliers) > 1.30:
        raise VerifyFailure(
            f"Meditation behavior differs materially by owner: {idle_multipliers}"
        )
    return {
        "baseline": baseline,
        "upgrades": upgrades,
        "upgraded_views": upgraded_views,
        "upgraded_stationary": stationary,
        "upgraded_moving": moving,
        "behavior": behavior,
    }


def run_faster_caster_behavior(
    context: BehaviorContext,
    catalog: list[dict[str, Any]],
    contract_values: dict[int, dict[str, list[float]]],
    timeout: float,
    *,
    continuous: bool,
) -> dict[str, Any]:
    directions = context.faster_directions
    initial = current_progression(context.pair)
    measure = (
        faster_caster.measure_continuous_damage_rate
        if continuous
        else faster_caster.measure_cadence
    )
    baseline = {
        direction.name: measure(direction, timeout)
        for direction in directions
    }
    upgrades = {
        direction.name: faster_caster.max_faster_caster(
            direction,
            catalog,
            initial,
            contract_values,
            timeout,
        )
        for direction in directions
    }
    concentration_views: dict[str, Any] = {}
    for direction in directions:
        owner, observer = wait_for_derived_parity(direction.source_id, timeout)
        concentration_views[direction.name] = assert_concentrated_row(
            direction.name,
            owner,
            observer,
            faster_caster.FASTER_CASTER_ROW,
        )
    upgraded = {
        direction.name: measure(direction, timeout)
        for direction in directions
    }
    result = {
        "measurement": (
            "continuous_authoritative_damage_rate"
            if continuous
            else "discrete_pure_primary_cadence"
        ),
        "baseline": baseline,
        "upgrades": upgrades,
        "concentration_views": concentration_views,
        "upgraded": upgraded,
    }
    if continuous:
        result["rate_ratios"] = faster_caster.verify_continuous_rate_contracts(
            directions,
            baseline,
            upgraded,
        )
    else:
        result["cadence_ratios"] = faster_caster.verify_cadence_contracts(
            directions,
            baseline,
            upgraded,
        )
    return result


def run_faster_caster(
    context: BehaviorContext,
    catalog: list[dict[str, Any]],
    contract_values: dict[int, dict[str, list[float]]],
    timeout: float,
) -> dict[str, Any]:
    return run_faster_caster_behavior(
        context,
        catalog,
        contract_values,
        timeout,
        continuous=False,
    )


def run_faster_caster_air(
    context: BehaviorContext,
    catalog: list[dict[str, Any]],
    contract_values: dict[int, dict[str, list[float]]],
    timeout: float,
) -> dict[str, Any]:
    return run_faster_caster_behavior(
        context,
        catalog,
        contract_values,
        timeout,
        continuous=True,
    )


def run_mindstar(
    context: BehaviorContext,
    timeout: float,
) -> dict[str, Any]:
    acquisitions = {
        direction.name: focus.acquire_secondary_to_rank(
            direction,
            mindstar.MINDSTAR_ROW,
            1,
            timeout,
        )
        for direction in context.focus_directions
    }
    directions: dict[str, Any] = {}
    for direction in context.focus_directions:
        owner = (
            "host"
            if direction.source_id == context.pair.host_participant_id
            else "client"
        )
        cast_direction = mindstar.direction_for_owner(
            owner,
            {"host": 0, "client": 0},
        )
        directions[direction.name] = mindstar.run_direction(
            direction,
            acquisitions[direction.name],
            cast_direction,
            timeout,
        )
    return {"acquisitions": acquisitions, "directions": directions}


def run_focus(
    context: BehaviorContext,
    catalog: list[dict[str, Any]],
    contract_values: dict[int, dict[str, list[float]]],
    timeout: float,
) -> dict[str, Any]:
    directions = context.focus_directions
    combat_prelude = focus.enable_unsuppressed_combat_prelude(timeout)
    initial = current_progression(context.pair)
    acquisitions = {
        direction.name: focus.acquire_test_secondary(direction, timeout)
        for direction in directions
    }
    baseline = {
        direction.name: focus.measure_recharge(direction, timeout)
        for direction in directions
    }
    upgrades = {
        direction.name: battle_siege.max_stat_for_target(
            catalog,
            focus.FOCUS_ROW,
            direction.source_id,
            initial,
            contract_values,
            timeout,
        )
        for direction in directions
    }
    upgraded = {
        direction.name: focus.measure_recharge(direction, timeout)
        for direction in directions
    }
    return {
        "combat_prelude": combat_prelude,
        "acquisitions": acquisitions,
        "baseline": baseline,
        "upgrades": upgrades,
        "upgraded": upgraded,
        "recharge_ratios": focus.verify_recharge_contracts(
            directions,
            baseline,
            upgraded,
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--profile",
        choices=tuple(PROFILE_SUITES),
        default="general",
        help="run one progression-isolated combat-stat profile",
    )
    args = parser.parse_args()

    started_at = time.time()
    pair = SteamFriendActivePair()
    suites = PROFILE_SUITES[args.profile]
    output: dict[str, Any] = {"ok": False, "profile": args.profile}
    return_code = 1
    try:
        output["pair"] = pair.discover()
        require_shared_test_run(output["pair"])
        context = configure_behavior_context(pair)
        output["initial_profile_state"] = require_fresh_combat_profile(pair)
        output["test_godmode"] = disable_runtime_test_godmode(pair)
        output["active_step"] = "combat_prelude"
        output["combat_prelude"] = focus.enable_unsuppressed_combat_prelude(
            args.timeout
        )
        output["initial_arena_reset"] = reset_quiet_arena()
        progression_inputs = load_progression_inputs(args.timeout)
        output["post_run_progression_ready"] = progression_inputs["ready"]
        catalog = progression_inputs["catalog"]
        contract_values = progression_inputs["contract_values"]

        for suite_index, suite in enumerate(suites):
            output["active_step"] = suite
            if suite == "transient_status":
                output[suite] = run_transient_status(context, args.timeout)
            elif suite == "battle_siege":
                output[suite] = run_battle_siege(
                    context,
                    catalog,
                    contract_values,
                    args.timeout,
                )
            elif suite == "telekinesis":
                output[suite] = run_telekinesis(
                    context,
                    catalog,
                    contract_values,
                    args.timeout,
                )
            elif suite == "meditation":
                output[suite] = run_meditation(
                    context,
                    catalog,
                    contract_values,
                    args.timeout,
                )
            elif suite == "faster_caster":
                output[suite] = run_faster_caster(
                    context,
                    catalog,
                    contract_values,
                    args.timeout,
                )
            elif suite == "faster_caster_air":
                output[suite] = run_faster_caster_air(
                    context,
                    catalog,
                    contract_values,
                    args.timeout,
                )
            elif suite == "mindstar":
                output[suite] = run_mindstar(context, args.timeout)
            elif suite == "focus":
                output[suite] = run_focus(
                    context,
                    catalog,
                    contract_values,
                    args.timeout,
                )
            if suite_index + 1 < len(suites):
                output[f"reset_after_{suite}"] = reset_quiet_arena()

        output["new_crash_artifacts"] = find_new_crash_artifacts(started_at)
        if output["new_crash_artifacts"]:
            raise VerifyFailure(
                "new crash artifacts appeared during Steam combat-stat tests"
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

    print(
        json.dumps(
            {
                "ok": output.get("ok", False),
                "active_step": output.get("active_step"),
                "error": output.get("error"),
                "completed_suites": [
                    suite for suite in suites if suite in output
                ],
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
