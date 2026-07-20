#!/usr/bin/env python3
"""Verify Mindstar's +1 skill rank and mana hoard for either owner."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import time
from pathlib import Path
from typing import Any

from multiplayer_log_probe import log_position
from multiplayer_persistent_status_harness import (
    PERSISTENT_MINDSTAR,
    query_persistent_status,
    wait_for_persistent_status,
)
from multiplayer_progression_probe import (
    query_progression_snapshot,
    query_ranked_numeric_stat,
)
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_PIPE,
    HOST_ID,
    HOST_PIPE,
    VerifyFailure,
    stop_games,
)
from verify_multiplayer_battle_siege_behavior_sync import (
    AIR_PRIMARY_ENTRY,
    FIRE_PRIMARY_ENTRY,
    estimate_fundamental_damage_quantum,
    read_local_cast_observation,
    reset_local_cast_observation,
)
from verify_multiplayer_all_upgrade_sync import (
    new_crash_artifacts,
    wait_for_post_run_progression_ready,
)
from verify_multiplayer_fireball_embers_effect_sync import (
    SECONDARY_OFFSET,
    direction_for_owner,
)
from verify_multiplayer_fireball_explode_effect_sync import (
    build_manual_pair,
    cast_fireball_pair,
    launch_pair_ready,
)
from verify_multiplayer_focus_behavior_sync import (
    DIRECTIONS,
    Direction,
    acquire_secondary_to_rank,
)
from verify_multiplayer_persistent_status_sync import toggle_once
from verify_multiplayer_primary_kill_stress import (
    cleanup_live_enemies,
    enable_manual_stock_spawner_combat,
    wait_for_cast_runtime_ready,
)
from verify_player_health_death_sync import set_local_player_vitals
from verify_real_input_spell_cast_sync import detect_instance_pids
from verify_spell_cast_sync import (
    remote_cast_state_lua,
    values,
    wait_for_remote_completion,
)


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "runtime/multiplayer_mindstar_behavior_sync.json"
MINDSTAR_ROW = 0x4E
CONTROLLED_RESOURCE = 100.0


def observer_pipe(direction: Direction) -> str:
    return HOST_PIPE if direction.source_pipe == CLIENT_PIPE else CLIENT_PIPE


def ensure_mindstar_inactive(
    direction: Direction,
    *,
    belt_slot: int,
    timeout: float,
) -> dict[str, Any]:
    owner = query_persistent_status(direction.source_pipe)
    if owner["local_flags"] & PERSISTENT_MINDSTAR:
        return {
            "already_inactive": False,
            "toggle": toggle_once(
                direction,
                belt_slot=belt_slot,
                expected_values=0,
                timeout=timeout,
            ),
        }
    return {
        "already_inactive": True,
        "convergence": wait_for_persistent_status(
            direction.source_pipe,
            observer_pipe(direction),
            direction.source_id,
            0,
            timeout=timeout,
        ),
    }


def query_spell_views(direction: Direction) -> dict[str, Any]:
    owner = query_progression_snapshot(direction.source_pipe)
    observer = query_progression_snapshot(
        observer_pipe(direction),
        participant_id=direction.source_id,
    )
    combo_entry = int(owner["loadout"]["combo_entry"])
    return {
        "owner": owner,
        "observer": observer,
        "combo_entry": combo_entry,
        "base_mana_property": query_ranked_numeric_stat(
            direction.source_pipe,
            combo_entry,
            "mManaCost",
        ),
        "mindstar_hoard_property": query_ranked_numeric_stat(
            direction.source_pipe,
            MINDSTAR_ROW,
            "mHoard",
        ),
    }


def compact_spell(view: dict[str, Any]) -> dict[str, Any]:
    spell = view["spell"]
    return {
        "resolved": spell["resolved"],
        "build_skill_id": spell["build_skill_id"],
        "current_spell_id": spell["current_spell_id"],
        "progression_level": spell["progression_level"],
        "secondary_damage_available": spell["secondary_damage_available"],
        "mana_cost_available": spell["mana_cost_available"],
        "mana_spend_cost_available": spell["mana_spend_cost_available"],
        "mana_output_scaled": spell["mana_output_scaled"],
        "damage": spell["damage"],
        "secondary_damage": spell["secondary_damage"],
        "mana_cost": spell["mana_cost"],
        "mana_spend_cost": spell["mana_spend_cost"],
        "mana_output_scale": spell["mana_output_scale"],
        "builder_seh_code": spell["builder_seh_code"],
        "error": spell["error"],
    }


def compact_native_output_buffer(view: dict[str, Any]) -> dict[str, Any]:
    spell = view["spell"]
    return {
        "count": spell["raw_output_count"],
        "outputs": spell["raw_outputs"],
    }


def wait_for_spell_views(
    direction: Direction,
    label: str,
    timeout: float = 4.0,
) -> dict[str, Any]:
    """Wait until owner and observer expose the same semantic spell state."""

    deadline = time.monotonic() + timeout
    attempts = 0
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        attempts += 1
        last = query_spell_views(direction)
        owner = compact_spell(last["owner"])
        observer = compact_spell(last["observer"])
        if owner["resolved"] and observer["resolved"] and owner == observer:
            last["quiescent_attempt_count"] = attempts
            return last
        time.sleep(0.05)
    raise VerifyFailure(
        f"{direction.name} {label} semantic primary spell state did not "
        f"converge: owner={compact_spell(last['owner']) if last else {}} "
        f"observer={compact_spell(last['observer']) if last else {}} "
        f"native_output_buffers={{'owner': "
        f"{compact_native_output_buffer(last['owner']) if last else {}}, "
        f"'observer': "
        f"{compact_native_output_buffer(last['observer']) if last else {}}}}"
    )


def verify_owner_observer_spell_parity(
    direction: Direction,
    label: str,
    views: dict[str, Any],
) -> dict[str, Any]:
    owner = compact_spell(views["owner"])
    observer = compact_spell(views["observer"])
    if not owner["resolved"] or not observer["resolved"] or owner != observer:
        raise VerifyFailure(
            f"{direction.name} {label} semantic primary spell state diverged: "
            f"owner={owner} observer={observer} native_output_buffers="
            f"{{'owner': {compact_native_output_buffer(views['owner'])}, "
            f"'observer': {compact_native_output_buffer(views['observer'])}}}"
        )
    owner_buffer = compact_native_output_buffer(views["owner"])
    observer_buffer = compact_native_output_buffer(views["observer"])
    return {
        "owner": owner,
        "observer": observer,
        "semantic_exact_match": True,
        "native_output_buffer_diagnostic": {
            "owner": owner_buffer,
            "observer": observer_buffer,
            "exact_match": owner_buffer == observer_buffer,
        },
    }


def run_fireball_trial(
    direction: Direction,
    cast_direction: Any,
    label: str,
    primary_entry: int,
) -> dict[str, Any]:
    cleanup = cleanup_live_enemies()
    pair = build_manual_pair(cast_direction, *SECONDARY_OFFSET)
    network_actor_id = int(pair["primary_network_id"])
    receiver_log_offset = log_position(cast_direction.receiver_log)
    cast = cast_fireball_pair(
        cast_direction,
        pair,
        f"mindstar.{direction.name}.{label}",
        before_source_cast=lambda: reset_local_cast_observation(
            direction.source_pipe,
            network_actor_id,
        ),
    )
    damage = cast["damage"]
    if primary_entry == FIRE_PRIMARY_ENTRY:
        geometry_valid = (
            damage["primary_damaged"] and not damage["secondary_damaged"]
        )
        expected_geometry = "isolated Fire projectile"
    elif primary_entry == AIR_PRIMARY_ENTRY:
        geometry_valid = damage["primary_damaged"]
        expected_geometry = "selected-target Air damage"
    else:
        raise VerifyFailure(
            "Mindstar behavior requires the exact Fire/Air Steam profile: "
            f"primary_entry={primary_entry}"
        )
    if not geometry_valid:
        raise VerifyFailure(
            f"{direction.name} {label} did not produce {expected_geometry}: {damage}"
        )
    if not cast.get("replicated_cast_delivery", {}).get("ok"):
        raise VerifyFailure(
            f"{direction.name} {label} Fireball did not execute natively on both peers: "
            f"{cast.get('replicated_cast_delivery')}"
        )
    completion = wait_for_remote_completion(
        cast_direction,
        receiver_log_offset,
    )
    deadline = time.monotonic() + 3.0
    final_state: dict[str, str] = {}
    while time.monotonic() < deadline:
        final_state = values(
            cast_direction.receiver_pipe,
            remote_cast_state_lua(direction.source_id),
        )
        if final_state.get("cast_active") != "true" and final_state.get(
            "cast_pending"
        ) != "true":
            break
        time.sleep(0.05)
    if final_state.get("cast_active") == "true" or final_state.get(
        "cast_pending"
    ) == "true":
        raise VerifyFailure(
            f"{direction.name} {label} remote Fireball did not settle: {final_state}"
        )
    cast_settled = wait_for_cast_runtime_ready(cast_direction, timeout=8.0)
    cast_observation = read_local_cast_observation(
        direction.source_pipe,
        network_actor_id,
    )
    return {
        "cleanup": cleanup,
        "pair": pair,
        "cast": cast,
        "remote_completion": completion,
        "remote_final_state": final_state,
        "cast_settled": cast_settled,
        "cast_observation": cast_observation,
    }


def measure_primary_damage_trial(
    primary_entry: int,
    trial: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    authoritative_damage = float(trial["cast"]["damage"]["primary_damage"])
    if primary_entry == FIRE_PRIMARY_ENTRY:
        quantum = authoritative_damage
        measurement: dict[str, Any] = {
            "method": "single_fire_projectile_authoritative_damage",
            "quantum": quantum,
        }
    elif primary_entry == AIR_PRIMARY_ENTRY:
        observation = trial["cast_observation"]
        if (
            not observation["damage_claim_valid"]
            or observation["damage_associated_skill_id"] != AIR_PRIMARY_ENTRY
            or not observation["damage_associated_skill_consistent"]
        ):
            raise VerifyFailure(
                f"{label} Air damage claims were not associated exclusively "
                f"with primary row {AIR_PRIMARY_ENTRY}: {observation}"
            )
        measurement = {
            "method": "client_air_damage_claim_quantum",
            **estimate_fundamental_damage_quantum(
                observation["damage_claim_samples"],
                authoritative_damage=authoritative_damage,
            ),
        }
        quantum = float(measurement["quantum"])
    else:
        raise VerifyFailure(
            "Mindstar behavior requires the exact Fire/Air Steam profile: "
            f"primary_entry={primary_entry}"
        )

    if authoritative_damage <= 0.0 or not math.isfinite(quantum) or quantum <= 0.0:
        raise VerifyFailure(
            f"{label} primary cast produced invalid damage measurement: "
            f"damage={authoritative_damage} measurement={measurement}"
        )
    authoritative_multiple = authoritative_damage / quantum
    authoritative_multiple_residual = abs(
        authoritative_multiple - round(authoritative_multiple)
    )
    if authoritative_multiple_residual > 0.15:
        raise VerifyFailure(
            f"{label} damage quantum does not explain authoritative HP loss: "
            f"damage={authoritative_damage} quantum={quantum} "
            f"multiple={authoritative_multiple}"
        )
    measurement.update(
        {
            "authoritative_damage": authoritative_damage,
            "authoritative_multiple": authoritative_multiple,
            "authoritative_multiple_residual": authoritative_multiple_residual,
        }
    )
    return measurement


def wait_for_hoarded_mana(
    direction: Direction,
    expected_mana: float,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    attempts = 0
    owner: dict[str, Any] = {}
    observer: dict[str, Any] = {}
    while time.monotonic() < deadline:
        attempts += 1
        owner = query_persistent_status(direction.source_pipe)
        observer = query_persistent_status(
            observer_pipe(direction),
            participant_id=direction.source_id,
        )
        if (
            math.isclose(owner["mp"], expected_mana, abs_tol=0.15)
            and math.isclose(observer["mp"], expected_mana, abs_tol=0.75)
            and math.isclose(owner["max_mp"], CONTROLLED_RESOURCE, abs_tol=0.15)
            and math.isclose(observer["max_mp"], CONTROLLED_RESOURCE, abs_tol=0.75)
        ):
            return {
                "attempt_count": attempts,
                "expected_mana": expected_mana,
                "owner": owner,
                "observer": observer,
            }
        time.sleep(0.05)
    raise VerifyFailure(
        f"{direction.name} Mindstar mana hoard did not converge to "
        f"{expected_mana}: owner={owner} observer={observer}"
    )


def verify_behavior_transition(
    direction: Direction,
    baseline_views: dict[str, Any],
    active_views: dict[str, Any],
    baseline_cast: dict[str, Any],
    active_cast: dict[str, Any],
) -> dict[str, Any]:
    baseline_spell = compact_spell(baseline_views["owner"])
    active_spell = compact_spell(active_views["owner"])
    if baseline_spell["current_spell_id"] != active_spell["current_spell_id"]:
        raise VerifyFailure(
            f"{direction.name} Mindstar changed the selected spell instead of its rank"
        )
    if baseline_spell["build_skill_id"] != active_spell["build_skill_id"]:
        raise VerifyFailure(
            f"{direction.name} Mindstar changed the primary build skill"
        )
    stable_shape_fields = (
        "progression_level",
        "secondary_damage_available",
        "mana_cost_available",
        "mana_spend_cost_available",
        "mana_output_scaled",
        "mana_output_scale",
        "builder_seh_code",
        "error",
    )
    changed_shape_fields = [
        field
        for field in stable_shape_fields
        if baseline_spell[field] != active_spell[field]
    ]
    if changed_shape_fields:
        raise VerifyFailure(
            f"{direction.name} Mindstar changed primary semantic shape fields "
            f"{changed_shape_fields}: baseline={baseline_spell} active={active_spell}"
        )
    if (
        active_spell["damage"] <= baseline_spell["damage"]
        or active_spell["mana_cost"] <= baseline_spell["mana_cost"]
    ):
        raise VerifyFailure(
            f"{direction.name} Mindstar did not advance the primary native outputs: "
            f"baseline={baseline_spell} active={active_spell}"
        )

    primary_entry = int(baseline_views["combo_entry"])
    if int(active_views["combo_entry"]) != primary_entry:
        raise VerifyFailure(
            f"{direction.name} Mindstar changed the primary entry during measurement"
        )
    baseline_measurement = measure_primary_damage_trial(
        primary_entry,
        baseline_cast,
        f"{direction.name} baseline",
    )
    active_measurement = measure_primary_damage_trial(
        primary_entry,
        active_cast,
        f"{direction.name} active",
    )
    baseline_damage = float(baseline_measurement["authoritative_damage"])
    active_damage = float(active_measurement["authoritative_damage"])
    native_ratio = active_spell["damage"] / baseline_spell["damage"]
    behavior_ratio = (
        float(active_measurement["quantum"])
        / float(baseline_measurement["quantum"])
    )
    if not math.isclose(behavior_ratio, native_ratio, rel_tol=0.0, abs_tol=0.08):
        raise VerifyFailure(
            f"{direction.name} real primary-hit damage did not follow Mindstar's "
            f"native +1 output: native_ratio={native_ratio} "
            f"behavior_ratio={behavior_ratio} baseline={baseline_measurement} "
            f"active={active_measurement}"
        )
    return {
        "baseline_native_damage": baseline_spell["damage"],
        "active_native_damage": active_spell["damage"],
        "baseline_native_mana": baseline_spell["mana_cost"],
        "active_native_mana": active_spell["mana_cost"],
        "baseline_real_damage": baseline_damage,
        "active_real_damage": active_damage,
        "native_damage_ratio": native_ratio,
        "real_damage_ratio": behavior_ratio,
        "baseline_damage_measurement": baseline_measurement,
        "active_damage_measurement": active_measurement,
        "ok": True,
    }


def run_direction(
    direction: Direction,
    acquisition: dict[str, Any],
    cast_direction: Any,
    timeout: float,
) -> dict[str, Any]:
    belt_slot = int(acquisition["belt_slot"])
    inactive_before = ensure_mindstar_inactive(
        direction,
        belt_slot=belt_slot,
        timeout=timeout,
    )
    baseline_views = wait_for_spell_views(direction, "baseline")
    baseline_parity = verify_owner_observer_spell_parity(
        direction,
        "baseline",
        baseline_views,
    )
    resource_reset = set_local_player_vitals(
        direction.source_pipe,
        CONTROLLED_RESOURCE,
        CONTROLLED_RESOURCE,
    )
    try:
        activated = toggle_once(
            direction,
            belt_slot=belt_slot,
            expected_values=PERSISTENT_MINDSTAR,
            timeout=timeout,
        )
        hoard_property = query_ranked_numeric_stat(
            direction.source_pipe,
            MINDSTAR_ROW,
            "mHoard",
        )
        if not hoard_property["property_found"]:
            raise VerifyFailure(
                f"{direction.name} Mindstar mHoard is unavailable: {hoard_property}"
            )
        expected_mana = CONTROLLED_RESOURCE * (
            1.0 - float(hoard_property["value"]) / 100.0
        )
        hoarded_mana = wait_for_hoarded_mana(direction, expected_mana, timeout)

        active_views = wait_for_spell_views(direction, "active")
        active_parity = verify_owner_observer_spell_parity(
            direction,
            "active",
            active_views,
        )
    finally:
        deactivated = ensure_mindstar_inactive(
            direction,
            belt_slot=belt_slot,
            timeout=timeout,
        )
    restored_views = wait_for_spell_views(direction, "restored")
    restored_parity = verify_owner_observer_spell_parity(
        direction,
        "restored",
        restored_views,
    )
    if compact_spell(restored_views["owner"]) != compact_spell(
        baseline_views["owner"]
    ):
        raise VerifyFailure(
            f"{direction.name} Mindstar outputs did not restore after toggle-off: "
            f"baseline={compact_spell(baseline_views['owner'])} "
            f"restored={compact_spell(restored_views['owner'])}"
        )

    # Exercise real damage only after the full stock builder vectors have been
    # compared. A completed remote Fireball intentionally leaves additional
    # stock construction outputs in its participant-owned native buffer; those
    # trailing values are runtime work state, not Mindstar rank outputs.
    #
    # Establish the actual stock arena spawner immediately before the first
    # manual target. Progression setup can legitimately take longer than the
    # bounded lifetime of an unproven generic spawner pointer. The first target
    # then promotes this exact stock spawner to the arena-owned witness on both
    # peers; no alternate spawning path is used.
    pre_prime_cleanup = cleanup_live_enemies()
    manual_spawner_prime = enable_manual_stock_spawner_combat()
    baseline_cast = run_fireball_trial(
        direction,
        cast_direction,
        "baseline",
        int(baseline_views["combo_entry"]),
    )
    cast_resource_reset = set_local_player_vitals(
        direction.source_pipe,
        CONTROLLED_RESOURCE,
        CONTROLLED_RESOURCE,
    )
    try:
        reactivated = toggle_once(
            direction,
            belt_slot=belt_slot,
            expected_values=PERSISTENT_MINDSTAR,
            timeout=timeout,
        )
        active_cast = run_fireball_trial(
            direction,
            cast_direction,
            "active",
            int(active_views["combo_entry"]),
        )
        transition = verify_behavior_transition(
            direction,
            baseline_views,
            active_views,
            baseline_cast,
            active_cast,
        )
    finally:
        final_deactivated = ensure_mindstar_inactive(
            direction,
            belt_slot=belt_slot,
            timeout=timeout,
        )
    return {
        "inactive_before": inactive_before,
        "baseline": {
            "views": baseline_views,
            "parity": baseline_parity,
            "pre_prime_cleanup": pre_prime_cleanup,
            "manual_spawner_prime": manual_spawner_prime,
            "cast": baseline_cast,
        },
        "resource_reset": resource_reset,
        "activated": activated,
        "hoarded_mana": hoarded_mana,
        "active": {
            "views": active_views,
            "parity": active_parity,
            "cast": active_cast,
        },
        "transition": transition,
        "deactivated": deactivated,
        "restored": {
            "views": restored_views,
            "parity": restored_parity,
        },
        "cast_resource_reset": cast_resource_reset,
        "reactivated": reactivated,
        "final_deactivated": final_deactivated,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--keep-open", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    started_at = time.time()
    output: dict[str, Any] = {"ok": False}
    return_code = 1
    try:
        startup = launch_pair_ready(args.timeout, god_mode=False)
        output["launch"] = startup["launch"]
        output["manual_combat"] = startup["manual_combat"]
        output["post_run_progression_ready"] = (
            wait_for_post_run_progression_ready(args.timeout)
        )
        acquisitions = {
            direction.name: acquire_secondary_to_rank(
                direction,
                MINDSTAR_ROW,
                1,
                args.timeout,
            )
            for direction in DIRECTIONS
        }
        output["acquisitions"] = acquisitions

        pids = detect_instance_pids()
        output["directions"] = {}
        for direction in DIRECTIONS:
            owner = "host" if direction.source_id == HOST_ID else "client"
            output["directions"][direction.name] = run_direction(
                direction,
                acquisitions[direction.name],
                direction_for_owner(owner, pids),
                args.timeout,
            )

        crashes = new_crash_artifacts(started_at)
        output["new_crash_artifacts"] = crashes
        if crashes:
            raise VerifyFailure(
                f"new crash artifacts during Mindstar test: {crashes}"
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
