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
    cleanup_live_enemies,
    parse_float,
    query_run_enemy_by_network_id,
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


def arm_mana_monitor(pipe_name: str) -> dict[str, str]:
    return values(
        pipe_name,
        """
local function emit(key, value) print(key .. '=' .. tostring(value)) end
if not _G.__sdmod_stat_mana_monitor_registered then
  sd.events.on('runtime.tick', function()
    local monitor = _G.__sdmod_stat_mana_monitor
    if type(monitor) ~= 'table' or not monitor.active then return end
    local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
    local progression = player and tonumber(player.progression_address) or 0
    if progression == 0 then return end
    local current = tonumber(sd.debug.read_float(
      progression + sd.debug.layout_offset('progression_mp'))) or 0
    monitor.samples = monitor.samples + 1
    monitor.minimum = math.min(monitor.minimum, current)
    monitor.latest = current
  end)
  _G.__sdmod_stat_mana_monitor_registered = true
end
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
local progression = player and tonumber(player.progression_address) or 0
local current = progression ~= 0 and tonumber(sd.debug.read_float(
  progression + sd.debug.layout_offset('progression_mp'))) or -1
_G.__sdmod_stat_mana_monitor = {
  active = true,
  initial = current,
  minimum = current,
  latest = current,
  samples = 0,
}
emit('registered', _G.__sdmod_stat_mana_monitor_registered)
emit('progression', progression)
emit('initial', current)
""",
    )


def stop_mana_monitor(pipe_name: str) -> dict[str, str]:
    result = values(
        pipe_name,
        """
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local monitor = _G.__sdmod_stat_mana_monitor or {}
monitor.active = false
for _, key in ipairs({'initial','minimum','latest','samples'}) do
  emit(key, monitor[key])
end
""",
    )
    initial = parse_float(result.get("initial"), math.nan)
    minimum = parse_float(result.get("minimum"), math.nan)
    samples = parse_int_text(result.get("samples"), 0)
    if not math.isfinite(initial) or not math.isfinite(minimum) or samples <= 0:
        raise VerifyFailure(f"native mana monitor captured no valid cast samples: {result}")
    result["spend"] = f"{initial - minimum:.6f}"
    return result


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


def run_cast_trial(direction: Direction, label: str) -> dict[str, Any]:
    cleanup_live_enemies()
    pair = build_manual_pair(
        direction,
        *SECONDARY_TARGET_OFFSET,
        target_hp=TARGET_HP,
        include_secondary=False,
    )
    cast = cast_fireball_pair(
        direction,
        pair,
        label,
        resource_value=RESOURCE_VALUE,
        before_source_cast=lambda: arm_mana_monitor(direction.source_pipe),
        after_source_cast=lambda: stop_mana_monitor(direction.source_pipe),
    )
    damage = float(cast["damage"]["primary_damage"])
    mana_spend = parse_float(cast["post_source_cast"].get("spend"), math.nan)
    if damage <= 0.0 or not math.isfinite(mana_spend) or mana_spend <= 0.0:
        raise VerifyFailure(
            f"{direction.name} {label} did not produce positive damage/mana spend: "
            f"damage={damage} mana={cast['post_source_cast']}"
        )
    if not cast["replicated_cast_delivery"]["ok"]:
        raise VerifyFailure(
            f"{direction.name} {label} cast did not replicate: "
            f"{cast['replicated_cast_delivery']}"
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
    progression = query_progression_snapshot(direction.source_pipe)
    result = {
        "direction": direction.name,
        "label": label,
        "damage": damage,
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
        "replicated_cast_delivery": cast["replicated_cast_delivery"],
        "mana_monitor": cast["post_source_cast"],
        "host_enemy": host_view,
        "client_enemy": client_view,
        "pair": {
            "primary_network_id": network_id,
            "target_hp": pair["target_hp"],
            "primary_x": pair["primary_x"],
            "primary_y": pair["primary_y"],
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
        expected_battle_mana = (
            battle_trial["base_mana_spend"]
            * battle_trial["offensive_mana_multiplier"]
        )
        if abs(battle_trial["mana_spend"] - expected_battle_mana) > 1.1:
            raise VerifyFailure(
                f"{direction} Battle Mage mana behavior mismatch: "
                f"actual={battle_trial['mana_spend']:.3f} "
                f"expected={expected_battle_mana:.3f} trial={battle_trial}"
            )
        if battle_trial["mana_spend"] >= base["mana_spend"] * 0.75:
            raise VerifyFailure(
                f"{direction} Battle Mage did not materially reduce real cast spend: "
                f"baseline={base['mana_spend']:.3f} battle={battle_trial['mana_spend']:.3f}"
            )

        damage_scale = base["damage"] / base["base_damage"]
        expected_siege_damage = (
            siege_trial["base_damage"]
            * damage_scale
            * siege_trial["offensive_damage_multiplier"]
        )
        damage_tolerance = max(0.5, expected_siege_damage * 0.08)
        if abs(siege_trial["damage"] - expected_siege_damage) > damage_tolerance:
            raise VerifyFailure(
                f"{direction} Siege Mage damage behavior mismatch: "
                f"actual={siege_trial['damage']:.3f} expected={expected_siege_damage:.3f} "
                f"tolerance={damage_tolerance:.3f} trial={siege_trial}"
            )
        if siege_trial["damage"] <= battle_trial["damage"] * 1.75:
            raise VerifyFailure(
                f"{direction} Siege Mage did not materially increase real damage: "
                f"before={battle_trial['damage']:.3f} siege={siege_trial['damage']:.3f}"
            )
        contracts[direction] = {
            "battle_expected_mana_spend": expected_battle_mana,
            "battle_actual_mana_spend": battle_trial["mana_spend"],
            "baseline_damage_scale": damage_scale,
            "siege_expected_damage": expected_siege_damage,
            "siege_actual_damage": siege_trial["damage"],
            "siege_damage_tolerance": damage_tolerance,
        }

    for stage_name, stage in (("baseline", baseline), ("battle", battle), ("siege", siege)):
        left = stage["host_owned"]
        right = stage["client_owned"]
        for field in ("damage", "mana_spend"):
            tolerance = max(0.75, max(abs(left[field]), abs(right[field])) * 0.10)
            if abs(left[field] - right[field]) > tolerance:
                raise VerifyFailure(
                    f"{stage_name} host/client {field} behavior diverged: "
                    f"host={left[field]} client={right[field]} tolerance={tolerance}"
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
