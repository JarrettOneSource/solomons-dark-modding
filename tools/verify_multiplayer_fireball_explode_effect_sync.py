#!/usr/bin/env python3
"""Verify that native Fireball explode changes real host-side secondary damage."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

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
    parse_int_text,
    start_host_testrun_and_wait_for_clients,
    stop_games,
    wait_for_remote,
)
from verify_multiplayer_level_up_offer_sync import (
    choose_client_option,
    enrich_offer_options,
    publish_offer,
    query_progression_entry,
    query_progression_stats,
    wait_for_choice_result,
    wait_for_client_offer,
    wait_for_wait_status,
)
from verify_multiplayer_primary_kill_stress import (
    CLIENT_TARGET,
    clear_gameplay_mouse_left,
    cleanup_live_enemies,
    enable_manual_stock_spawner_combat,
    find_target,
    place_pair_on_clear_lane,
    prepare_and_queue_caster,
    primary_input_released,
    spawn_one_enemy,
    wait_for_cast_runtime_ready,
    values,
)
from verify_multiplayer_targeted_spell_matrix import HOST_ENEMY_BY_ID_LUA
from verify_player_health_death_sync import set_local_player_vitals
from verify_real_input_spell_cast_sync import (
    CLIENT_LOG,
    Direction,
    HOST_LOG,
    detect_instance_pids,
    read_log,
    wait_for_source_cast,
)


ROOT = Path(__file__).resolve().parent.parent
RUNTIME_OUTPUT = ROOT / "runtime" / "multiplayer_fireball_explode_effect_sync.json"
FIRE_PRESET = "map_create_fire_mind_hub"
TARGET_SKILL_FILE = "explode.cfg"
TARGET_HP = 40.0
TARGET_DAMAGE_EPSILON = 0.25
MAX_LEVEL_STEPS = 25
FIREBALL_CAST_FRAMES = 2
PIN_INTERVAL = 0.05
PIN_DURATION = 0.7
BASELINE_OFFSET_CANDIDATES = (
    (24.0, 0.0),
    (36.0, 0.0),
    (48.0, 0.0),
    (60.0, 0.0),
)
UPGRADED_OFFSET_CANDIDATES = (
    (18.0, 0.0),
    (24.0, 0.0),
    (30.0, 0.0),
    (36.0, 0.0),
    (42.0, 0.0),
)

PIN_ENEMY_TRANSFORM_LUA = r"""
local network_actor_id = tonumber("__NETWORK_ID__") or 0
local x = tonumber("__X__") or 0
local y = tonumber("__Y__") or 0
local hp = tonumber("__HP__")
local write_hp = "__WRITE_HP__" == "true"
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local actor = sd.world.get_run_enemy_by_network_id and sd.world.get_run_enemy_by_network_id(network_actor_id) or nil
emit("found", actor ~= nil)
if actor ~= nil then
  local actor_address = tonumber(actor.actor_address) or 0
  local x_offset = sd.debug.layout_offset("actor_position_x")
  local y_offset = sd.debug.layout_offset("actor_position_y")
  emit("actor_address", string.format("0x%08X", actor_address))
  emit("write_x", x_offset ~= nil and sd.debug.write_float(actor_address + x_offset, x) or false)
  emit("write_y", y_offset ~= nil and sd.debug.write_float(actor_address + y_offset, y) or false)
  if write_hp then
    emit("write_health", sd.gameplay.set_run_enemy_health(actor_address, hp, hp))
  else
    emit("write_health", "skipped")
  end
  if sd.world ~= nil and sd.world.rebind_actor ~= nil then
    local ok, err = sd.world.rebind_actor(actor_address)
    emit("rebind", ok)
    emit("rebind_err", err or "")
  end
end
emit("ok", true)
"""


def parse_float(value: str | None, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def target_step_summary(step: dict[str, Any]) -> dict[str, Any]:
    offer = step["offer"]
    return {
        "step": step["step"],
        "target_level": step["target_level"],
        "target_experience": step["target_experience"],
        "offer_id": offer["offer_id"],
        "options": [
            {
                "id": option["id"],
                "name": option["name"],
                "skill_file": option["skill_file"],
            }
            for option in offer["enriched_options"]
        ],
        "selected_option_index": offer["selected_option_index"],
        "selected_option_id": offer["selected_option_id"],
    }


def query_enemy_state(network_actor_id: int) -> dict[str, str]:
    return values(
        HOST_PIPE,
        HOST_ENEMY_BY_ID_LUA.replace("__NETWORK_ACTOR_ID__", str(network_actor_id)),
        timeout=10.0,
    )


def pin_enemy_transform(
    pipe_name: str,
    network_actor_id: int,
    x: float,
    y: float,
    *,
    hp: float | None = None,
) -> dict[str, str]:
    return values(
        pipe_name,
        PIN_ENEMY_TRANSFORM_LUA
        .replace("__NETWORK_ID__", str(network_actor_id))
        .replace("__X__", f"{x:.3f}")
        .replace("__Y__", f"{y:.3f}")
        .replace("__HP__", f"{(hp if hp is not None else 0.0):.3f}")
        .replace("__WRITE_HP__", "true" if hp is not None else "false"),
    )


def quiesce_local_primary_input(label: str, stable_seconds: float = 0.45) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    for attempt in range(1, 7):
        host_clear = clear_gameplay_mouse_left(HOST_PIPE)
        client_clear = clear_gameplay_mouse_left(CLIENT_PIPE)
        attempts.append(
            {
                "attempt": attempt,
                "host_clear": host_clear,
                "client_clear": client_clear,
            }
        )
        if primary_input_released(host_clear) and primary_input_released(client_clear):
            time.sleep(stable_seconds)
            host_confirm = clear_gameplay_mouse_left(HOST_PIPE)
            client_confirm = clear_gameplay_mouse_left(CLIENT_PIPE)
            attempts[-1]["host_confirm"] = host_confirm
            attempts[-1]["client_confirm"] = client_confirm
            if primary_input_released(host_confirm) and primary_input_released(client_confirm):
                return {"ok": True, "label": label, "attempts": attempts}
        time.sleep(0.12)
    raise VerifyFailure(
        f"{label}: local Fireball input did not quiesce: attempts={attempts[-3:]}"
    )


def wait_for_client_target(
    x: float,
    y: float,
    *,
    network_id: int | None = None,
    timeout: float = 8.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = find_target(
            CLIENT_PIPE,
            x,
            y,
            network_id=network_id,
            timeout=1.5,
            require_local_binding=True,
        )
        if last.get("local.found") == "true":
            return last
        time.sleep(0.12)
    raise VerifyFailure(
        "client Fireball target never reached a local binding state: "
        f"network_id={network_id} x={x} y={y} last={last}"
    )


def build_manual_pair(direction: Direction, offset_x: float, offset_y: float) -> dict[str, Any]:
    lane = place_pair_on_clear_lane(direction, CLIENT_TARGET)
    target_x = float(lane["x"])
    target_y = float(lane["y"])

    primary = spawn_one_enemy(target_x, target_y, TARGET_HP)
    secondary = spawn_one_enemy(target_x + offset_x, target_y + offset_y, TARGET_HP)

    primary_network_id = parse_int_text(primary["result"].get("network_actor_id"), 0)
    secondary_network_id = parse_int_text(secondary["result"].get("network_actor_id"), 0)
    if primary_network_id == 0 or secondary_network_id == 0:
        raise VerifyFailure(
            f"manual Fireball pair did not expose replicated ids: primary={primary} secondary={secondary}"
        )

    client_primary = wait_for_client_target(
        target_x,
        target_y,
        network_id=primary_network_id,
    )
    client_secondary = wait_for_client_target(
        target_x + offset_x,
        target_y + offset_y,
        network_id=secondary_network_id,
    )

    return {
        "lane": lane,
        "offset_x": offset_x,
        "offset_y": offset_y,
        "primary_network_id": primary_network_id,
        "secondary_network_id": secondary_network_id,
        "primary_actor_address": parse_int_text(client_primary.get("local.actor_address"), 0),
        "primary_x": target_x,
        "primary_y": target_y,
        "secondary_x": target_x + offset_x,
        "secondary_y": target_y + offset_y,
        "primary_spawn": primary,
        "secondary_spawn": secondary,
        "client_primary": client_primary,
        "client_secondary": client_secondary,
    }


def stabilize_pair(
    pair: dict[str, Any],
    *,
    duration: float,
    interval: float = PIN_INTERVAL,
    write_hp: bool,
    include_host: bool = True,
    include_client: bool = True,
) -> dict[str, Any]:
    end_time = time.monotonic() + duration
    last_host_primary: dict[str, str] = {}
    last_host_secondary: dict[str, str] = {}
    last_client_primary: dict[str, str] = {}
    last_client_secondary: dict[str, str] = {}
    while time.monotonic() < end_time:
        hp_value = TARGET_HP if write_hp else None
        if include_host:
            last_host_primary = pin_enemy_transform(
                HOST_PIPE,
                pair["primary_network_id"],
                pair["primary_x"],
                pair["primary_y"],
                hp=hp_value,
            )
            last_host_secondary = pin_enemy_transform(
                HOST_PIPE,
                pair["secondary_network_id"],
                pair["secondary_x"],
                pair["secondary_y"],
                hp=hp_value,
            )
        if include_client:
            last_client_primary = pin_enemy_transform(
                CLIENT_PIPE,
                pair["primary_network_id"],
                pair["primary_x"],
                pair["primary_y"],
                hp=hp_value,
            )
            last_client_secondary = pin_enemy_transform(
                CLIENT_PIPE,
                pair["secondary_network_id"],
                pair["secondary_x"],
                pair["secondary_y"],
                hp=hp_value,
            )
        time.sleep(interval)
    return {
        "host_primary": last_host_primary,
        "host_secondary": last_host_secondary,
        "client_primary": last_client_primary,
        "client_secondary": last_client_secondary,
    }


def observe_pair_damage(
    primary_network_id: int,
    secondary_network_id: int,
    primary_before_hp: float,
    secondary_before_hp: float,
    *,
    duration: float = 3.0,
    interval: float = 0.1,
) -> dict[str, Any]:
    deadline = time.monotonic() + duration
    min_primary_hp = primary_before_hp
    min_secondary_hp = secondary_before_hp
    last_primary: dict[str, str] = {}
    last_secondary: dict[str, str] = {}
    primary_removed = False
    secondary_removed = False
    while time.monotonic() < deadline:
        last_primary = query_enemy_state(primary_network_id)
        last_secondary = query_enemy_state(secondary_network_id)
        if last_primary.get("found") == "true":
            min_primary_hp = min(min_primary_hp, parse_float(last_primary.get("hp"), primary_before_hp))
        else:
            primary_removed = True
            min_primary_hp = 0.0
        if last_secondary.get("found") == "true":
            min_secondary_hp = min(min_secondary_hp, parse_float(last_secondary.get("hp"), secondary_before_hp))
        else:
            secondary_removed = True
            min_secondary_hp = 0.0
        time.sleep(interval)
    return {
        "primary_before_hp": primary_before_hp,
        "secondary_before_hp": secondary_before_hp,
        "primary_min_hp": min_primary_hp,
        "secondary_min_hp": min_secondary_hp,
        "primary_damage": primary_before_hp - min_primary_hp,
        "secondary_damage": secondary_before_hp - min_secondary_hp,
        "primary_removed": primary_removed,
        "secondary_removed": secondary_removed,
        "primary_damaged": primary_before_hp - min_primary_hp > TARGET_DAMAGE_EPSILON,
        "secondary_damaged": secondary_before_hp - min_secondary_hp > TARGET_DAMAGE_EPSILON,
        "last_primary": last_primary,
        "last_secondary": last_secondary,
    }


def cast_fireball_pair(direction: Direction, pair: dict[str, Any], label: str) -> dict[str, Any]:
    quiesce_local_primary_input(f"{label}.before")
    wait_for_cast_runtime_ready(direction)
    set_local_player_vitals(HOST_PIPE, 5000.0, 5000.0)
    set_local_player_vitals(CLIENT_PIPE, 5000.0, 5000.0)

    stabilize_pair(pair, duration=0.35, write_hp=True)
    primary_before_hp = parse_float(query_enemy_state(pair["primary_network_id"]).get("hp"), TARGET_HP)
    secondary_before_hp = parse_float(query_enemy_state(pair["secondary_network_id"]).get("hp"), TARGET_HP)

    source_offset = len(read_log(direction.source_log))
    receiver_offset = len(read_log(direction.receiver_log))
    prepare = prepare_and_queue_caster(
        direction,
        pair["primary_actor_address"],
        pair["primary_x"],
        pair["primary_y"],
        FIREBALL_CAST_FRAMES,
    )
    source_log, phase_counts, native_hook_count = wait_for_source_cast(
        direction,
        source_offset,
        {"pressed": 1, "released": 1},
        timeout=8.0,
    )
    damage = observe_pair_damage(
        pair["primary_network_id"],
        pair["secondary_network_id"],
        primary_before_hp,
        secondary_before_hp,
    )
    return {
        "prepare": prepare,
        "phase_counts": phase_counts,
        "native_hook_count": native_hook_count,
        "source_log_tail": source_log[-4000:],
        "receiver_log_tail": read_log(direction.receiver_log)[receiver_offset:][-4000:],
        "damage": damage,
    }


def find_baseline_safe_offset(direction: Direction) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    for offset_x, offset_y in BASELINE_OFFSET_CANDIDATES:
        cleanup_live_enemies()
        pair = build_manual_pair(direction, offset_x, offset_y)
        cast = cast_fireball_pair(
            direction,
            pair,
            f"fireball_explode.baseline.offset_{int(offset_x)}_{int(offset_y)}",
        )
        attempt = {
            "offset_x": offset_x,
            "offset_y": offset_y,
            "pair": pair,
            "cast": cast,
        }
        attempts.append(attempt)
        damage = cast["damage"]
        if damage["primary_damaged"] and not damage["secondary_damaged"]:
            return {
                "selected": attempt,
                "attempts": attempts,
            }
    raise VerifyFailure(
        "could not find a baseline Fireball offset with single-target damage: "
        f"{attempts}"
    )


def find_upgraded_explode_offset(
    direction: Direction,
    *,
    candidate_offsets: list[tuple[float, float]],
) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    for offset_x, offset_y in candidate_offsets:
        cleanup_live_enemies()
        pair = build_manual_pair(direction, offset_x, offset_y)
        cast = cast_fireball_pair(
            direction,
            pair,
            f"fireball_explode.upgraded.offset_{int(offset_x)}_{int(offset_y)}",
        )
        attempt = {
            "offset_x": offset_x,
            "offset_y": offset_y,
            "pair": pair,
            "cast": cast,
        }
        attempts.append(attempt)
        damage = cast["damage"]
        if damage["primary_damaged"] and damage["secondary_damaged"]:
            return {
                "selected": attempt,
                "attempts": attempts,
            }
    raise VerifyFailure(
        "upgraded Fireball never damaged the secondary target on the host at any baseline-safe offset: "
        f"{attempts}"
    )


def wait_for_target_upgrade(timeout: float) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    for step in range(1, MAX_LEVEL_STEPS + 1):
        host_client_stats = query_progression_stats(HOST_PIPE, participant_id=CLIENT_ID)
        client_stats = query_progression_stats(CLIENT_PIPE)
        if not host_client_stats["available"] or not client_stats["available"]:
            raise VerifyFailure(
                "Fireball explode probe could not read client progression stats: "
                f"host_client={host_client_stats} client={client_stats}"
            )
        target_level = max(host_client_stats["level"], client_stats["level"]) + 1
        target_experience = int(
            max(
                host_client_stats["next_xp_threshold"],
                client_stats["next_xp_threshold"],
                125.0,
            ) + 10.0
        )

        publish = publish_offer(target_level, target_experience)
        offer = wait_for_client_offer(target_level, timeout)
        wait_active = wait_for_wait_status(
            participant_id=CLIENT_ID,
            pause_active=True,
            timeout=timeout,
        )
        enriched_options = enrich_offer_options(offer["option_ids"])

        selected_option_index = 1
        matched_target_upgrade = False
        for option_index, option in enumerate(enriched_options, start=1):
            if str(option.get("skill_file") or "").lower() == TARGET_SKILL_FILE:
                selected_option_index = option_index
                matched_target_upgrade = True
                break
        selected_option_id = offer["option_ids"][selected_option_index - 1]

        before_host_selected = query_progression_entry(
            HOST_PIPE,
            option_id=selected_option_id,
            participant_id=CLIENT_ID,
        )
        before_client_selected = query_progression_entry(
            CLIENT_PIPE,
            option_id=selected_option_id,
        )
        choice = choose_client_option(offer["offer_id"], selected_option_index)
        result = wait_for_choice_result(offer["offer_id"], target_level, timeout)
        wait_cleared = wait_for_wait_status(
            participant_id=CLIENT_ID,
            pause_active=False,
            timeout=timeout,
        )
        after_host_selected = query_progression_entry(
            HOST_PIPE,
            option_id=selected_option_id,
            participant_id=CLIENT_ID,
        )
        after_client_selected = query_progression_entry(
            CLIENT_PIPE,
            option_id=selected_option_id,
        )
        step_record = {
            "step": step,
            "target_level": target_level,
            "target_experience": target_experience,
            "stats_before": {
                "host_client": host_client_stats,
                "client": client_stats,
            },
            "publish": publish,
            "offer": {
                "offer_id": offer["offer_id"],
                "option_count": offer["option_count"],
                "option_ids": offer["option_ids"],
                "enriched_options": enriched_options,
                "selected_option_index": selected_option_index,
                "selected_option_id": selected_option_id,
            },
            "wait_active": {
                "host_waiting_count": parse_int_text(wait_active["host"].get("wait.waiting_count"), 0),
                "client_waiting_count": parse_int_text(wait_active["client"].get("wait.waiting_count"), 0),
            },
            "choice": choice,
            "result": result,
            "wait_cleared": {
                "host_waiting_count": parse_int_text(wait_cleared["host"].get("wait.waiting_count"), 0),
                "client_waiting_count": parse_int_text(wait_cleared["client"].get("wait.waiting_count"), 0),
            },
            "selected_entry": {
                "before_host": before_host_selected,
                "after_host": after_host_selected,
                "before_client": before_client_selected,
                "after_client": after_client_selected,
            },
            "matched_target_upgrade": matched_target_upgrade,
        }
        steps.append(step_record)
        if matched_target_upgrade:
            if after_host_selected["active"] <= before_host_selected["active"]:
                raise VerifyFailure(f"host remote explode active count did not increase: {step_record}")
            if after_client_selected["active"] <= before_client_selected["active"]:
                raise VerifyFailure(f"client local explode active count did not increase: {step_record}")
            return {
                "step_record": step_record,
                "steps": steps,
            }
    raise VerifyFailure(
        f"Fireball explode upgrade was not offered within {MAX_LEVEL_STEPS} level-up steps: "
        f"{[target_step_summary(step) for step in steps]}"
    )


def launch_pair_ready(timeout: float) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(1, 4):
        stop_games()
        try:
            launch = launch_pair(preset=FIRE_PRESET, god_mode=True)
            disable_bots()
            hub_ready = {
                "host_observes_client": wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "hub"),
                "client_observes_host": wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "hub"),
            }
            run_entry = start_host_testrun_and_wait_for_clients(timeout=timeout)
            run_ready = {
                "host_observes_client": wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "testrun"),
                "client_observes_host": wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "testrun"),
            }
            return {
                "attempt": attempt,
                "launch": launch,
                "hub_ready": hub_ready,
                "run_entry": run_entry,
                "run_ready": run_ready,
            }
        except Exception as exc:
            last_error = exc
            stop_games()
            time.sleep(1.0)
    if last_error is not None:
        raise last_error
    raise VerifyFailure("launch_pair_ready exhausted retries without a concrete error")


def run_verifier(timeout: float) -> dict[str, Any]:
    output: dict[str, Any] = {"ok": False}
    startup = launch_pair_ready(timeout)
    output["startup"] = {"attempt": startup["attempt"]}
    output["launch"] = startup["launch"]
    output["hub_ready"] = startup["hub_ready"]
    output["run_entry"] = startup["run_entry"]
    output["run_ready"] = startup["run_ready"]
    output["manual_combat"] = enable_manual_stock_spawner_combat()

    pids = detect_instance_pids()
    direction = Direction(
        "client_to_host_fireball_explode",
        CLIENT_ID,
        CLIENT_NAME,
        CLIENT_PIPE,
        CLIENT_LOG,
        pids["client"],
        HOST_PIPE,
        HOST_LOG,
    )

    output["baseline_offset_search"] = find_baseline_safe_offset(direction)
    output["baseline_pair"] = output["baseline_offset_search"]["selected"]["pair"]
    output["baseline_cast"] = output["baseline_offset_search"]["selected"]["cast"]
    baseline_damage = output["baseline_cast"]["damage"]
    if not baseline_damage["primary_damaged"]:
        raise VerifyFailure(f"baseline Fireball cast did not damage the primary target: {baseline_damage}")
    if baseline_damage["secondary_damaged"]:
        raise VerifyFailure(f"baseline Fireball cast unexpectedly damaged the secondary target: {baseline_damage}")

    cleanup_live_enemies()
    output["upgrade"] = wait_for_target_upgrade(timeout)
    step_record = output["upgrade"]["step_record"]
    output["upgrade_result_summary"] = {
        "selected_option_id": step_record["offer"]["selected_option_id"],
        "selected_option_index": step_record["offer"]["selected_option_index"],
        "selected_skill_file": step_record["offer"]["enriched_options"][step_record["offer"]["selected_option_index"] - 1]["skill_file"],
    }

    output["upgraded_offset_search"] = find_upgraded_explode_offset(
        direction,
        candidate_offsets=list(UPGRADED_OFFSET_CANDIDATES),
    )
    output["upgraded_pair"] = output["upgraded_offset_search"]["selected"]["pair"]
    output["upgraded_cast"] = output["upgraded_offset_search"]["selected"]["cast"]
    upgraded_damage = output["upgraded_cast"]["damage"]
    if not upgraded_damage["primary_damaged"]:
        raise VerifyFailure(f"upgraded Fireball cast did not damage the primary target: {upgraded_damage}")
    if not upgraded_damage["secondary_damaged"]:
        raise VerifyFailure(
            "upgraded Fireball cast did not damage the exploded secondary target on the host: "
            f"baseline={baseline_damage} upgraded={upgraded_damage} upgrade={target_step_summary(step_record)}"
        )

    output["ok"] = True
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()

    result: dict[str, Any]
    try:
        result = run_verifier(timeout=args.timeout)
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
        try:
            RUNTIME_OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        except Exception:
            pass
        print(json.dumps(result, indent=2, sort_keys=True))
        stop_games()
        return 1

    result["output"] = str(RUNTIME_OUTPUT)
    RUNTIME_OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    stop_games()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
