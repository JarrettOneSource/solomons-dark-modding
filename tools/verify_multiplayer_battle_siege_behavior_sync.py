#!/usr/bin/env python3
"""Verify Battle Mage mana and Siege Mage damage behavior for both owners."""

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
    parse_int_text,
    stop_games,
)
from verify_multiplayer_all_stat_sync import (
    apply_stat_batch,
    load_stat_contract_values,
)
from verify_multiplayer_all_upgrade_sync import (
    build_and_verify_catalog,
    enable_quiet_progression_test_mode,
    load_skill_configs,
    new_crash_artifacts,
    wait_for_catalog_views,
    wait_for_post_run_progression_ready,
)
from verify_multiplayer_fireball_explode_effect_sync import (
    build_manual_pair,
    cast_fireball_pair,
    launch_pair_ready,
)
from verify_multiplayer_primary_kill_stress import (
    SKELETON_TYPE_ID,
    cleanup_live_enemies,
    parse_float,
    query_run_enemy_by_network_id,
    wait_for_cast_runtime_ready,
    values,
)
from verify_real_input_spell_cast_sync import (
    CLIENT_LOG,
    Direction,
    HOST_LOG,
    detect_instance_pids,
)


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "runtime/multiplayer_battle_siege_behavior_sync.json"
BATTLE_MAGE_ROW = 59
SIEGE_MAGE_ROW = 61
TARGET_HP = 100000.0
RESOURCE_VALUE = 10000.0
SECONDARY_TARGET_OFFSET = (0.0, 0.0)
FIRE_PRIMARY_ENTRY = 16
AIR_PRIMARY_ENTRY = 24
MINIMUM_AIR_DAMAGE_CLAIM_SAMPLES = 3


def direction_for_owner(owner: str, pids: dict[str, int]) -> Direction:
    if owner == "host":
        return Direction(
            "host_owned",
            HOST_ID,
            HOST_NAME,
            HOST_PIPE,
            HOST_LOG,
            pids["host"],
            CLIENT_PIPE,
            CLIENT_LOG,
        )
    return Direction(
        "client_owned",
        CLIENT_ID,
        CLIENT_NAME,
        CLIENT_PIPE,
        CLIENT_LOG,
        pids["client"],
        HOST_PIPE,
        HOST_LOG,
    )


def reset_local_cast_observation(
    pipe_name: str,
    network_actor_id: int,
) -> dict[str, str]:
    result = values(
        pipe_name,
        f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
emit('reset', sd.debug.reset_local_cast_observation({network_actor_id}))
""",
    )
    if result.get("reset") != "true":
        raise VerifyFailure(f"local cast observation did not reset: {result}")
    return result


def read_local_cast_observation(
    pipe_name: str,
    network_actor_id: int,
) -> dict[str, Any]:
    raw = values(
        pipe_name,
        f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local observation = sd.debug.get_local_cast_observation({network_actor_id})
for _, key in ipairs({{
  'mana_valid',
  'mana_actor_address',
  'mana_call_count',
  'mana_spend_call_count',
  'mana_recovery_call_count',
  'mana_spent_total',
  'mana_recovered_total',
  'mana_last_delta',
  'damage_claim_valid',
  'damage_claim_count',
  'damage_associated_claim_count',
  'damage_unassociated_claim_count',
  'damage_associated_skill_id',
  'damage_associated_skill_consistent',
  'damage_claimed_total',
  'damage_claimed_minimum',
  'damage_claimed_maximum',
  'damage_claim_sample_count',
}}) do
  emit(key, observation[key])
end
for index, sample in ipairs(observation.damage_claim_samples or {{}}) do
  emit('damage_claim_sample.' .. tostring(index), sample)
end
""",
    )
    sample_count = parse_int_text(raw.get("damage_claim_sample_count"), 0)
    return {
        "mana_valid": raw.get("mana_valid") == "true",
        "mana_actor_address": parse_int_text(raw.get("mana_actor_address"), 0),
        "mana_call_count": parse_int_text(raw.get("mana_call_count"), 0),
        "mana_spend_call_count": parse_int_text(
            raw.get("mana_spend_call_count"), 0
        ),
        "mana_recovery_call_count": parse_int_text(
            raw.get("mana_recovery_call_count"), 0
        ),
        "mana_spent_total": parse_float(raw.get("mana_spent_total"), math.nan),
        "mana_recovered_total": parse_float(
            raw.get("mana_recovered_total"), math.nan
        ),
        "mana_last_delta": parse_float(raw.get("mana_last_delta"), math.nan),
        "damage_claim_valid": raw.get("damage_claim_valid") == "true",
        "damage_claim_count": parse_int_text(raw.get("damage_claim_count"), 0),
        "damage_associated_claim_count": parse_int_text(
            raw.get("damage_associated_claim_count"), 0
        ),
        "damage_unassociated_claim_count": parse_int_text(
            raw.get("damage_unassociated_claim_count"), 0
        ),
        "damage_associated_skill_id": parse_int_text(
            raw.get("damage_associated_skill_id"), -1
        ),
        "damage_associated_skill_consistent": (
            raw.get("damage_associated_skill_consistent") == "true"
        ),
        "damage_claimed_total": parse_float(
            raw.get("damage_claimed_total"), 0.0
        ),
        "damage_claimed_minimum": parse_float(
            raw.get("damage_claimed_minimum"), 0.0
        ),
        "damage_claimed_maximum": parse_float(
            raw.get("damage_claimed_maximum"), 0.0
        ),
        "damage_claim_samples": [
            parse_float(raw.get(f"damage_claim_sample.{index}"), math.nan)
            for index in range(1, sample_count + 1)
        ],
    }


def estimate_fundamental_damage_quantum(
    samples: list[float],
    *,
    authoritative_damage: float | None = None,
) -> dict[str, Any]:
    positive = [
        value for value in samples if math.isfinite(value) and value > 0.0
    ]
    if len(positive) < MINIMUM_AIR_DAMAGE_CLAIM_SAMPLES:
        raise VerifyFailure(
            "Air damage observation did not capture enough native claims: "
            f"samples={positive}"
        )

    candidates = {
        value / multiple
        for value in positive
        for multiple in range(1, 65)
        if value / multiple > 0.0
    }
    required_matches = math.ceil(len(positive) * 0.8)
    smallest_sample = min(positive)
    if authoritative_damage is not None and (
        not math.isfinite(authoritative_damage) or authoritative_damage <= 0.0
    ):
        raise VerifyFailure(
            "Air damage observation received invalid authoritative damage: "
            f"{authoritative_damage}"
        )
    for candidate in sorted(candidates, reverse=True):
        if candidate > smallest_sample * 1.04:
            continue
        matches = []
        for value in positive:
            multiple = max(1, round(value / candidate))
            residual = abs(value - candidate * multiple)
            if multiple <= 128 and residual <= max(0.0002, candidate * 0.04):
                matches.append(
                    {
                        "sample": value,
                        "multiple": multiple,
                        "residual": residual,
                    }
                )
        if len(matches) >= required_matches:
            authoritative_multiple = (
                authoritative_damage / candidate
                if authoritative_damage is not None
                else None
            )
            authoritative_residual = (
                abs(authoritative_multiple - round(authoritative_multiple))
                if authoritative_multiple is not None
                else None
            )
            if authoritative_residual is not None and authoritative_residual > 0.15:
                continue
            return {
                "quantum": candidate,
                "sample_count": len(positive),
                "required_matches": required_matches,
                "matched_count": len(matches),
                "matches": matches,
                "authoritative_multiple": authoritative_multiple,
                "authoritative_multiple_residual": authoritative_residual,
            }
    raise VerifyFailure(
        "Air damage claims did not share a stable native quantum: "
        f"samples={positive}"
    )


def max_stat_for_target(
    catalog: list[dict[str, Any]],
    row: int,
    target_id: int,
    initial_by_target: dict[int, dict[str, Any]],
    contract_values: dict[int, dict[str, list[float]]],
    timeout: float,
) -> list[dict[str, Any]]:
    target_pipe = HOST_PIPE if target_id == HOST_ID else CLIENT_PIPE
    steps: list[dict[str, Any]] = []
    maximum = int(catalog[row]["native_max_level"])
    while True:
        snapshot = query_progression_snapshot(target_pipe)
        active = int(snapshot["native"]["entries"][row]["active"])
        if active >= maximum:
            return steps
        steps.append(
            apply_stat_batch(
                catalog,
                row,
                target_id,
                min(2, maximum - active),
                initial_by_target,
                contract_values,
                timeout,
            )
        )


def run_cast_trial(
    direction: Direction,
    label: str,
    *,
    native_type_id: int = SKELETON_TYPE_ID,
) -> dict[str, Any]:
    cleanup_live_enemies()
    pair = build_manual_pair(
        direction,
        *SECONDARY_TARGET_OFFSET,
        target_hp=TARGET_HP,
        include_secondary=False,
        native_type_id=native_type_id,
    )
    cast = cast_fireball_pair(
        direction,
        pair,
        label,
        resource_value=RESOURCE_VALUE,
        before_source_cast=lambda: reset_local_cast_observation(
            direction.source_pipe,
            int(pair["primary_network_id"]),
        ),
    )
    cast_settled = wait_for_cast_runtime_ready(direction, timeout=8.0)
    observation = read_local_cast_observation(
        direction.source_pipe,
        int(pair["primary_network_id"]),
    )
    mana_spend = float(observation["mana_spent_total"])
    damage = float(cast["damage"]["primary_damage"])
    progression = query_progression_snapshot(direction.source_pipe)
    primary_entry = int(progression["loadout"]["primary_entry"])
    damage_measurement: dict[str, Any]
    if primary_entry == FIRE_PRIMARY_ENTRY:
        native_damage_quantum = damage
        damage_measurement = {
            "method": "single_fire_projectile_authoritative_damage",
            "quantum": native_damage_quantum,
        }
    elif primary_entry == AIR_PRIMARY_ENTRY:
        if direction.source_pipe != CLIENT_PIPE:
            raise VerifyFailure(
                "mixed Battle/Siege profile requires Air to be the client-owned "
                f"primary so native damage claims are observable: {direction.name}"
            )
        if not observation["damage_claim_valid"]:
            raise VerifyFailure(
                f"{direction.name} {label} produced no semantic damage claims: "
                f"{observation}"
            )
        if (
            observation["damage_associated_skill_id"] != AIR_PRIMARY_ENTRY
            or not observation["damage_associated_skill_consistent"]
        ):
            raise VerifyFailure(
                f"{direction.name} {label} damage claims were not associated "
                f"exclusively with Air primary row {AIR_PRIMARY_ENTRY}: "
                f"{observation}"
            )
        damage_measurement = {
            "method": "client_air_damage_claim_quantum",
            **estimate_fundamental_damage_quantum(
                observation["damage_claim_samples"],
                authoritative_damage=damage,
            ),
        }
        native_damage_quantum = float(damage_measurement["quantum"])
    else:
        raise VerifyFailure(
            "mixed Battle/Siege verifier requires Fire/Air primaries: "
            f"direction={direction.name} primary_entry={primary_entry}"
        )
    if (
        damage <= 0.0
        or not observation["mana_valid"]
        or observation["mana_spend_call_count"] <= 0
        or not math.isfinite(mana_spend)
        or mana_spend <= 0.0
        or not math.isfinite(native_damage_quantum)
        or native_damage_quantum <= 0.0
    ):
        raise VerifyFailure(
            f"{direction.name} {label} did not produce positive native damage/mana: "
            f"authoritative_damage={damage} observation={observation} "
            f"damage_measurement={damage_measurement}"
        )
    authoritative_multiple = damage / native_damage_quantum
    authoritative_multiple_residual = abs(
        authoritative_multiple - round(authoritative_multiple)
    )
    if authoritative_multiple_residual > 0.15:
        raise VerifyFailure(
            f"{direction.name} {label} semantic damage quantum does not explain "
            f"the authoritative HP reduction: damage={damage} "
            f"quantum={native_damage_quantum} "
            f"multiple={authoritative_multiple}"
        )
    damage_measurement["authoritative_damage"] = damage
    damage_measurement["authoritative_multiple"] = authoritative_multiple
    damage_measurement["authoritative_multiple_residual"] = (
        authoritative_multiple_residual
    )
    replicated_cast_delivery = cast["replicated_cast_delivery"]
    if not replicated_cast_delivery["ok"]:
        raise VerifyFailure(
            f"{direction.name} {label} measurement cast did not replicate: "
            f"{replicated_cast_delivery}"
        )
    network_id = int(pair["primary_network_id"])
    host_view = query_run_enemy_by_network_id(HOST_PIPE, network_id)
    client_view = query_run_enemy_by_network_id(CLIENT_PIPE, network_id)
    host_hp = parse_float(host_view.get("hp"), math.nan)
    client_hp = parse_float(client_view.get("hp"), math.nan)
    if not math.isfinite(host_hp) or not math.isfinite(client_hp) or abs(host_hp - client_hp) > 0.25:
        raise VerifyFailure(
            f"{direction.name} {label} enemy HP diverged across peers: "
            f"host={host_view} client={client_view}"
        )
    result = {
        "direction": direction.name,
        "label": label,
        "damage": damage,
        "native_damage_quantum": native_damage_quantum,
        "primary_entry": primary_entry,
        "mana_spend": mana_spend,
        "base_damage": float(progression["spell"]["damage"]),
        "base_mana_spend": float(progression["spell"]["mana_spend_cost"]),
        "offensive_damage_multiplier": float(
            progression["native"]["derived"]["offensive_damage_multiplier"]
        ),
        "offensive_mana_multiplier": float(
            progression["native"]["derived"]["offensive_mana_multiplier"]
        ),
        "progression_level": int(progression["native"]["level"]),
        "replicated_cast_delivery": replicated_cast_delivery,
        "cast_settled": cast_settled,
        "cast_observation": observation,
        "damage_measurement": damage_measurement,
        "host_enemy": host_view,
        "client_enemy": client_view,
        "pair": {
            "primary_network_id": network_id,
            "target_hp": pair["target_hp"],
            "primary_x": pair["primary_x"],
            "primary_y": pair["primary_y"],
            "native_type_id": native_type_id,
        },
    }
    cleanup_live_enemies()
    return result


def verify_behavior_contracts(
    baseline: dict[str, dict[str, Any]],
    battle: dict[str, dict[str, Any]],
    siege: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    contracts: dict[str, Any] = {}
    for direction in ("host_owned", "client_owned"):
        base = baseline[direction]
        battle_trial = battle[direction]
        siege_trial = siege[direction]
        expected_battle_ratio = (
            battle_trial["offensive_mana_multiplier"]
            / base["offensive_mana_multiplier"]
        )
        actual_battle_ratio = battle_trial["mana_spend"] / base["mana_spend"]
        if abs(actual_battle_ratio - expected_battle_ratio) > 0.12:
            raise VerifyFailure(
                f"{direction} Battle Mage mana behavior mismatch: "
                f"actual_ratio={actual_battle_ratio:.3f} "
                f"expected_ratio={expected_battle_ratio:.3f} trial={battle_trial}"
            )
        if battle_trial["mana_spend"] >= base["mana_spend"] * 0.75:
            raise VerifyFailure(
                f"{direction} Battle Mage did not materially reduce real cast spend: "
                f"baseline={base['mana_spend']:.3f} battle={battle_trial['mana_spend']:.3f}"
            )

        expected_siege_ratio = (
            siege_trial["offensive_damage_multiplier"]
            / base["offensive_damage_multiplier"]
        )
        actual_siege_ratio = (
            siege_trial["native_damage_quantum"]
            / base["native_damage_quantum"]
        )
        ratio_tolerance = 0.12
        if abs(actual_siege_ratio - expected_siege_ratio) > ratio_tolerance:
            raise VerifyFailure(
                f"{direction} Siege Mage damage behavior mismatch: "
                f"actual_ratio={actual_siege_ratio:.3f} "
                f"expected_ratio={expected_siege_ratio:.3f} "
                f"tolerance={ratio_tolerance:.3f} trial={siege_trial}"
            )
        if (
            siege_trial["native_damage_quantum"]
            <= battle_trial["native_damage_quantum"] * 1.75
        ):
            raise VerifyFailure(
                f"{direction} Siege Mage did not materially increase native hit damage: "
                f"before={battle_trial['native_damage_quantum']:.3f} "
                f"siege={siege_trial['native_damage_quantum']:.3f}"
            )
        contracts[direction] = {
            "battle_expected_mana_ratio": expected_battle_ratio,
            "battle_actual_mana_ratio": actual_battle_ratio,
            "battle_actual_mana_spend": battle_trial["mana_spend"],
            "siege_expected_damage_ratio": expected_siege_ratio,
            "siege_actual_damage_ratio": actual_siege_ratio,
            "siege_native_damage_quantum": siege_trial[
                "native_damage_quantum"
            ],
            "siege_actual_damage": siege_trial["damage"],
            "ratio_tolerance": ratio_tolerance,
        }

    for field in ("battle_actual_mana_ratio", "siege_actual_damage_ratio"):
        host_ratio = contracts["host_owned"][field]
        client_ratio = contracts["client_owned"][field]
        if abs(host_ratio - client_ratio) > 0.12:
            raise VerifyFailure(
                f"host/client normalized {field} diverged across primary spell "
                f"types: host={host_ratio} client={client_ratio}"
            )
    return {"directions": contracts, "mismatches": []}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--keep-open", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    started_at = time.time()
    output: dict[str, Any] = {"ok": False}
    return_code = 1
    try:
        startup = launch_pair_ready(args.timeout, god_mode=False)
        output["launch"] = startup["launch"]
        output["startup"] = {"attempt": startup["attempt"]}
        output["quiet_progression_test_mode"] = enable_quiet_progression_test_mode()
        output["post_run_progression_ready"] = wait_for_post_run_progression_ready(
            args.timeout
        )
        catalog_result = build_and_verify_catalog(
            wait_for_catalog_views(args.timeout),
            load_skill_configs(),
        )
        catalog = catalog_result["catalog"]
        contract_values = load_stat_contract_values(catalog)
        initial_by_target = {
            HOST_ID: query_progression_snapshot(HOST_PIPE),
            CLIENT_ID: query_progression_snapshot(CLIENT_PIPE),
        }
        profile_contract = {
            "host_primary_entry": int(
                initial_by_target[HOST_ID]["loadout"]["primary_entry"]
            ),
            "client_primary_entry": int(
                initial_by_target[CLIENT_ID]["loadout"]["primary_entry"]
            ),
            "expected_host_primary_entry": FIRE_PRIMARY_ENTRY,
            "expected_client_primary_entry": AIR_PRIMARY_ENTRY,
        }
        profile_contract["ok"] = (
            profile_contract["host_primary_entry"] == FIRE_PRIMARY_ENTRY
            and profile_contract["client_primary_entry"] == AIR_PRIMARY_ENTRY
        )
        output["profile_contract"] = profile_contract
        if not profile_contract["ok"]:
            raise VerifyFailure(
                "Battle/Siege behavior requires the exact mixed Steam profile "
                f"host=Fire/client=Air: {profile_contract}"
            )
        pids = detect_instance_pids()
        directions = {
            owner: direction_for_owner(owner, pids)
            for owner in ("host", "client")
        }

        output["baseline"] = {
            direction.name: run_cast_trial(direction, "baseline")
            for direction in directions.values()
        }
        output["battle_mage_upgrades"] = {
            direction.name: max_stat_for_target(
                catalog,
                BATTLE_MAGE_ROW,
                direction.source_id,
                initial_by_target,
                contract_values,
                args.timeout,
            )
            for direction in directions.values()
        }
        output["battle_mage"] = {
            direction.name: run_cast_trial(direction, "battle_mage_max")
            for direction in directions.values()
        }
        output["siege_mage_upgrades"] = {
            direction.name: max_stat_for_target(
                catalog,
                SIEGE_MAGE_ROW,
                direction.source_id,
                initial_by_target,
                contract_values,
                args.timeout,
            )
            for direction in directions.values()
        }
        output["siege_mage"] = {
            direction.name: run_cast_trial(direction, "siege_mage_max")
            for direction in directions.values()
        }
        output["behavior_contracts"] = verify_behavior_contracts(
            output["baseline"],
            output["battle_mage"],
            output["siege_mage"],
        )

        crashes = new_crash_artifacts(started_at)
        output["new_crash_artifacts"] = crashes
        if crashes:
            raise VerifyFailure(
                f"new crash artifacts appeared during Battle/Siege behavior test: {crashes}"
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
                "behavior_contracts": output.get("behavior_contracts"),
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
