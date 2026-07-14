#!/usr/bin/env python3
"""Verify native Fireball Explode behavior for either multiplayer owner."""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any, Callable

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
from multiplayer_progression_probe import query_progression_snapshot
from verify_multiplayer_all_upgrade_sync import (
    choose_offer,
    publish_deterministic_offer,
    wait_for_offer,
    wait_for_pause,
    wait_for_result,
    wait_for_target_parity,
)
from verify_multiplayer_level_up_offer_sync import enrich_offer_options, query_progression_entry
from verify_multiplayer_primary_kill_stress import (
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
FLAT_BONEYARD = ROOT / "tests" / "fixtures" / "boneyards" / "flat_multiplayer_test.boneyard"
FIRE_PRESET = "map_create_fire_mind_hub"
TARGET_SKILL_FILE = "explode.cfg"
TARGET_OPTION_IDS = {
    "fireball.cfg": 16,
    "embers.cfg": 17,
    "explode.cfg": 18,
}
FIREBALL_IMPACT_DISPATCH = 0x00642BF0
TARGET_HP = 40.0
TARGET_DAMAGE_EPSILON = 0.25
# Native Fireball has a stricter projectile-safe lane than the flat fixture's
# nav probe. Keep the cast at the proven y=1750 lane, and park the observer
# downward so it remains inside the fixture's actor-tick region as well.
FIREBALL_TARGET = (1800.0, 1750.0)
FIREBALL_OBSERVER_Y_OFFSET = -320.0
# The native Fire primary is not a reliable two-frame tap under two-process
# playback.  The primary-kill stress harness proves this path with a 64-frame
# minimum, which gives both owner and observer projectiles time to reach the
# pinned target before release/cleanup.
FIREBALL_CAST_FRAMES = 64
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
local refresh_binding = "__REFRESH_BINDING__" == "true"
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
  if refresh_binding and sd.world ~= nil and sd.world.rebind_actor ~= nil then
    local ok, err = sd.world.rebind_actor(actor_address)
    emit("rebind", ok)
    emit("rebind_err", err or "")
  else
    -- Rebinding an unchanged frozen actor every 50 ms can mutate the stock
    -- index while its gameplay tick is iterating. The harness requests one
    -- explicit refresh only after the geometry has settled.
    emit("rebind", "skipped_existing_binding")
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


def arm_impact_trace(pipe_name: str, trace_name: str) -> dict[str, str]:
    escaped_name = json.dumps(trace_name)
    return values(
        pipe_name,
        f"""
pcall(sd.debug.untrace_function, {FIREBALL_IMPACT_DISPATCH})
sd.debug.clear_trace_hits({escaped_name})
local ok = sd.debug.trace_function({FIREBALL_IMPACT_DISPATCH}, {escaped_name})
print('ok=' .. tostring(ok))
print('error=' .. tostring(sd.debug.get_last_error and sd.debug.get_last_error() or ''))
""",
    )


def sample_impact_trace(pipe_name: str, trace_name: str) -> dict[str, str]:
    escaped_name = json.dumps(trace_name)
    return values(
        pipe_name,
        f"""
local hits = sd.debug.get_trace_hits and sd.debug.get_trace_hits({escaped_name}) or {{}}
print('call_count=' .. tostring(#hits))
for index, hit in ipairs(hits) do
  if index <= 8 then
    print('hit.' .. tostring(index) .. '.arg0=' .. tostring(hit.arg0 or 0))
    print('hit.' .. tostring(index) .. '.arg1=' .. tostring(hit.arg1 or 0))
    print('hit.' .. tostring(index) .. '.arg2=' .. tostring(hit.arg2 or 0))
    print('hit.' .. tostring(index) .. '.ret=' .. tostring(hit.ret or 0))
  end
end
""",
    )


def clear_impact_trace(pipe_name: str, trace_name: str) -> dict[str, str]:
    escaped_name = json.dumps(trace_name)
    return values(
        pipe_name,
        f"""
pcall(sd.debug.untrace_function, {FIREBALL_IMPACT_DISPATCH})
sd.debug.clear_trace_hits({escaped_name})
print('ok=true')
""",
    )


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
    refresh_binding: bool = False,
) -> dict[str, str]:
    return values(
        pipe_name,
        PIN_ENEMY_TRANSFORM_LUA
        .replace("__NETWORK_ID__", str(network_actor_id))
        .replace("__X__", f"{x:.3f}")
        .replace("__Y__", f"{y:.3f}")
        .replace("__HP__", f"{(hp if hp is not None else 0.0):.3f}")
        .replace("__WRITE_HP__", "true" if hp is not None else "false")
        .replace("__REFRESH_BINDING__", "true" if refresh_binding else "false"),
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
        try:
            last = find_target(
                CLIENT_PIPE,
                x,
                y,
                network_id=network_id,
                timeout=1.5,
                require_local_binding=True,
            )
        except VerifyFailure as exc:
            # find_target owns a short poll window and raises when it expires.
            # Keep the outer materialization window alive: the authoritative
            # snapshot can arrive before the gameplay-thread native actor does.
            last = {"poll_error": str(exc)}
            time.sleep(0.12)
            continue
        if last.get("local.found") == "true":
            return last
        time.sleep(0.12)
    raise VerifyFailure(
        "client Fireball target never reached a local binding state: "
        f"network_id={network_id} x={x} y={y} last={last}"
    )


def build_manual_pair(
    direction: Direction,
    offset_x: float,
    offset_y: float,
    *,
    target_hp: float = TARGET_HP,
    include_secondary: bool = True,
) -> dict[str, Any]:
    lane = place_pair_on_clear_lane(
        direction,
        FIREBALL_TARGET,
        receiver_y_offset=FIREBALL_OBSERVER_Y_OFFSET,
    )
    target_x = float(lane["x"])
    target_y = float(lane["y"])

    primary = spawn_one_enemy(target_x, target_y, target_hp)
    secondary = (
        spawn_one_enemy(target_x + offset_x, target_y + offset_y, target_hp)
        if include_secondary
        else None
    )

    primary_network_id = parse_int_text(primary["result"].get("network_actor_id"), 0)
    secondary_network_id = (
        parse_int_text(secondary["result"].get("network_actor_id"), 0)
        if secondary is not None
        else 0
    )
    if primary_network_id == 0 or (include_secondary and secondary_network_id == 0):
        raise VerifyFailure(
            f"manual Fireball pair did not expose replicated ids: primary={primary} secondary={secondary}"
        )

    client_primary = wait_for_client_target(
        target_x,
        target_y,
        network_id=primary_network_id,
    )
    client_secondary = (
        wait_for_client_target(
            target_x + offset_x,
            target_y + offset_y,
            network_id=secondary_network_id,
        )
        if include_secondary
        else {}
    )
    primary_actor_address = (
        int(primary["actor_address"])
        if direction.source_pipe == HOST_PIPE
        else parse_int_text(client_primary.get("local.actor_address"), 0)
    )
    if primary_actor_address == 0:
        raise VerifyFailure(
            f"{direction.name}: Fireball primary target has no actor on the casting owner: "
            f"host_spawn={primary} client_binding={client_primary}"
        )

    return {
        "lane": lane,
        "offset_x": offset_x,
        "offset_y": offset_y,
        "primary_network_id": primary_network_id,
        "secondary_network_id": secondary_network_id,
        "primary_actor_address": primary_actor_address,
        "primary_x": target_x,
        "primary_y": target_y,
        "secondary_x": target_x + offset_x,
        "secondary_y": target_y + offset_y,
        "target_hp": target_hp,
        "include_secondary": include_secondary,
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
        hp_value = float(pair.get("target_hp", TARGET_HP)) if write_hp else None
        if include_host:
            last_host_primary = pin_enemy_transform(
                HOST_PIPE,
                pair["primary_network_id"],
                pair["primary_x"],
                pair["primary_y"],
                hp=hp_value,
            )
            if pair.get("include_secondary", True):
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
            if pair.get("include_secondary", True):
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


def cast_fireball_pair(
    direction: Direction,
    pair: dict[str, Any],
    label: str,
    *,
    before_source_cast: Callable[[], Any] | None = None,
    after_source_cast: Callable[[], Any] | None = None,
    resource_value: float = 5000.0,
) -> dict[str, Any]:
    quiesce_local_primary_input(f"{label}.before")
    wait_for_cast_runtime_ready(direction)
    set_local_player_vitals(HOST_PIPE, resource_value, resource_value)
    set_local_player_vitals(CLIENT_PIPE, resource_value, resource_value)

    # Manual enemies are host-authored and frozen. Rebinding a client-side
    # replicated clone from the Lua pipe races gameplay-thread reconciliation,
    # which may replace that binding between lookup and write. Pin only the
    # authoritative host actors; their snapshots keep every observer aligned.
    stabilize_pair(
        pair,
        duration=0.35,
        write_hp=True,
        include_client=False,
    )
    # Explosion collision queries use the stock spatial index, not the raw
    # actor transform. Refresh each frozen target once after all pinning is
    # complete; repeated refreshes caused an iterator race in earlier runs.
    spatial_refresh: dict[str, Any] = {
        "primary": pin_enemy_transform(
            HOST_PIPE,
            pair["primary_network_id"],
            pair["primary_x"],
            pair["primary_y"],
            hp=TARGET_HP,
            refresh_binding=True,
        ),
    }
    if pair.get("include_secondary", True):
        spatial_refresh["secondary"] = pin_enemy_transform(
            HOST_PIPE,
            pair["secondary_network_id"],
            pair["secondary_x"],
            pair["secondary_y"],
            hp=TARGET_HP,
            refresh_binding=True,
        )
    else:
        spatial_refresh["secondary"] = {"skipped": "single_target_fixture"}
    target_hp = float(pair.get("target_hp", TARGET_HP))
    primary_before_hp = parse_float(
        query_enemy_state(pair["primary_network_id"]).get("hp"), target_hp
    )
    secondary_before_hp = (
        parse_float(
            query_enemy_state(pair["secondary_network_id"]).get("hp"), target_hp
        )
        if pair.get("include_secondary", True)
        else 0.0
    )

    impact_trace_names = {
        "owner": f"{label}.impact.owner",
        "observer": f"{label}.impact.observer",
    }
    impact_trace_arm = {
        "owner": arm_impact_trace(direction.source_pipe, impact_trace_names["owner"]),
        "observer": arm_impact_trace(
            direction.receiver_pipe, impact_trace_names["observer"]
        ),
    }
    pre_source_cast = before_source_cast() if before_source_cast is not None else None

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
    post_source_cast = after_source_cast() if after_source_cast is not None else None
    receiver_log = ""
    receiver_cast_queued = False
    receiver_cast_prepped = False
    delivery_deadline = time.monotonic() + 8.0
    while time.monotonic() < delivery_deadline:
        receiver_log = read_log(direction.receiver_log)[receiver_offset:]
        receiver_cast_queued = (
            f"Multiplayer remote cast queued. participant_id={direction.source_id}"
            in receiver_log
        )
        receiver_cast_prepped = (
            f"[bots] wizard cast prepped. bot_id={direction.source_id}"
            in receiver_log
        )
        if receiver_cast_queued and receiver_cast_prepped:
            break
        time.sleep(0.05)
    damage = observe_pair_damage(
        pair["primary_network_id"],
        pair["secondary_network_id"],
        primary_before_hp,
        secondary_before_hp,
    )
    impact_trace_sample = {
        "owner": sample_impact_trace(
            direction.source_pipe, impact_trace_names["owner"]
        ),
        "observer": sample_impact_trace(
            direction.receiver_pipe, impact_trace_names["observer"]
        ),
    }
    impact_trace_clear = {
        "owner": clear_impact_trace(
            direction.source_pipe, impact_trace_names["owner"]
        ),
        "observer": clear_impact_trace(
            direction.receiver_pipe, impact_trace_names["observer"]
        ),
    }
    return {
        "prepare": prepare,
        "spatial_refresh": spatial_refresh,
        "impact_trace": {
            "address": f"0x{FIREBALL_IMPACT_DISPATCH:08X}",
            "names": impact_trace_names,
            "arm": impact_trace_arm,
            "sample": impact_trace_sample,
            "clear": impact_trace_clear,
        },
        "phase_counts": phase_counts,
        "native_hook_count": native_hook_count,
        "pre_source_cast": pre_source_cast,
        "post_source_cast": post_source_cast,
        "source_log_tail": source_log[-4000:],
        "receiver_log_tail": receiver_log[-4000:],
        "replicated_cast_delivery": {
            "owner_native_hook_count": native_hook_count,
            "observer_remote_cast_queued": receiver_cast_queued,
            "observer_native_cast_prepped": receiver_cast_prepped,
            "ok": native_hook_count > 0 and receiver_cast_queued and receiver_cast_prepped,
        },
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


def _apply_exact_target_upgrade(
    owner: str,
    timeout: float,
    *,
    target_skill_file: str = TARGET_SKILL_FILE,
) -> dict[str, Any]:
    """Apply one exact Fire upgrade through the real authoritative offer path."""
    normalized_skill_file = target_skill_file.lower()
    option_id = TARGET_OPTION_IDS.get(normalized_skill_file)
    if option_id is None:
        raise VerifyFailure(
            f"focused Fire upgrade verifier has no native row for {target_skill_file!r}"
        )

    if owner == "host":
        target_id, target_pipe = HOST_ID, HOST_PIPE
        observer_id, observer_pipe = CLIENT_ID, CLIENT_PIPE
    elif owner == "client":
        target_id, target_pipe = CLIENT_ID, CLIENT_PIPE
        observer_id, observer_pipe = HOST_ID, HOST_PIPE
    else:
        raise VerifyFailure(f"unsupported Fire upgrade owner: {owner!r}")

    before_snapshot = query_progression_snapshot(target_pipe, timeout=8.0)
    before_row = before_snapshot["native"]["entries"].get(option_id)
    if not before_snapshot["available"] or before_row is None:
        raise VerifyFailure(
            f"{owner} native progression row {option_id} is unavailable: {before_snapshot}"
        )
    before_owner = query_progression_entry(target_pipe, option_id=option_id)
    before_observer = query_progression_entry(
        observer_pipe,
        option_id=option_id,
        participant_id=target_id,
    )
    expected_active = int(before_row["active"]) + 1
    if expected_active > int(before_row["statbook_max_level"]):
        raise VerifyFailure(
            f"{owner} {normalized_skill_file} is already maxed: {before_row}"
        )

    target_level = int(before_snapshot["native"]["level"]) + 1
    target_experience = int(
        math.ceil(before_snapshot["native"]["next_xp_threshold"])
    )
    publish = publish_deterministic_offer(
        target_id,
        target_level,
        target_experience,
        option_id,
    )
    offer = wait_for_offer(
        target_pipe,
        target_id,
        target_level,
        option_id,
        timeout,
    )
    pause_active = wait_for_pause(target_id, True, timeout)
    choice = choose_offer(target_pipe, offer["offer_id"], option_id)
    result = wait_for_result(
        offer["offer_id"],
        target_id,
        target_level,
        option_id,
        expected_active,
        timeout,
    )
    parity = wait_for_target_parity(
        target_id,
        option_id,
        expected_active,
        target_level,
        timeout,
    )
    pause_cleared = wait_for_pause(target_id, False, timeout)
    after_owner = query_progression_entry(target_pipe, option_id=option_id)
    after_observer = query_progression_entry(
        observer_pipe,
        option_id=option_id,
        participant_id=target_id,
    )
    if after_owner["active"] != expected_active:
        raise VerifyFailure(
            f"{owner}-local {normalized_skill_file} active count did not advance: "
            f"before={before_owner} after={after_owner}"
        )
    if after_observer["active"] != expected_active:
        raise VerifyFailure(
            f"{observer_id} observer {normalized_skill_file} active count did not converge: "
            f"before={before_observer} after={after_observer}"
        )

    enriched_options = enrich_offer_options([option_id])
    step_record = {
        "step": 1,
        "target_level": target_level,
        "target_experience": target_experience,
        "stats_before": {
            "level": before_snapshot["native"]["level"],
            "xp": before_snapshot["native"]["xp"],
            "next_xp_threshold": before_snapshot["native"]["next_xp_threshold"],
        },
        "publish": publish,
        "offer": {
            "offer_id": offer["offer_id"],
            "option_count": 1,
            "option_ids": [option_id],
            "enriched_options": enriched_options,
            "selected_option_index": 1,
            "selected_option_id": option_id,
            "selection_goal": normalized_skill_file,
        },
        "wait_active": pause_active,
        "choice": choice,
        "result": result,
        "parity": parity,
        "wait_cleared": pause_cleared,
        "selected_entry": {
            "before_owner": before_owner,
            "after_owner": after_owner,
            "before_observer": before_observer,
            "after_observer": after_observer,
        },
        "matched_target_upgrade": True,
    }
    return {"step_record": step_record, "steps": [step_record]}


def wait_for_target_upgrade(
    owner: str,
    timeout: float,
    *,
    target_skill_file: str = TARGET_SKILL_FILE,
) -> dict[str, Any]:
    normalized_skill_file = target_skill_file.lower()
    # Embers depends on Explode at behavior time. The base Fireball is already
    # active on a fresh Fire profile, so preserve that baseline and add only
    # the actual branch choices being tested.
    if normalized_skill_file == "embers.cfg":
        upgrade_path = ("explode.cfg", "embers.cfg")
    else:
        upgrade_path = (normalized_skill_file,)
    steps: list[dict[str, Any]] = []
    for skill_file in upgrade_path:
        applied = _apply_exact_target_upgrade(
            owner,
            timeout,
            target_skill_file=skill_file,
        )
        step_record = applied["step_record"]
        step_record["step"] = len(steps) + 1
        step_record["is_prerequisite"] = skill_file != normalized_skill_file
        steps.append(step_record)
    return {"step_record": steps[-1], "steps": steps}


def wait_for_client_target_upgrade(
    timeout: float,
    *,
    target_skill_file: str = TARGET_SKILL_FILE,
) -> dict[str, Any]:
    return wait_for_target_upgrade(
        "client", timeout, target_skill_file=target_skill_file
    )


def wait_for_host_target_upgrade(
    timeout: float,
    *,
    target_skill_file: str = TARGET_SKILL_FILE,
) -> dict[str, Any]:
    return wait_for_target_upgrade(
        "host", timeout, target_skill_file=target_skill_file
    )


def launch_pair_ready(
    timeout: float,
    *,
    preset: str = FIRE_PRESET,
    god_mode: bool = True,
    manual_combat: bool = True,
    boneyard_override: Path | None = FLAT_BONEYARD,
    wave_override: Path | None = None,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(1, 4):
        stop_games()
        try:
            launch = launch_pair(
                preset=preset,
                god_mode=god_mode,
                test_survival_boneyard_override=boneyard_override,
                test_wave_override=wave_override,
            )
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
            # Scene readiness can briefly precede the legacy client process
            # exiting during wave-spawner initialization. Include combat
            # bootstrap in this fresh-pair retry boundary so feature failures
            # are not conflated with that setup race.
            manual_combat_state = (
                enable_manual_stock_spawner_combat() if manual_combat else None
            )
            return {
                "attempt": attempt,
                "launch": launch,
                "hub_ready": hub_ready,
                "run_entry": run_entry,
                "run_ready": run_ready,
                "manual_combat": manual_combat_state,
            }
        except Exception as exc:
            last_error = exc
            stop_games()
            time.sleep(1.0)
    if last_error is not None:
        raise last_error
    raise VerifyFailure("launch_pair_ready exhausted retries without a concrete error")


def run_verifier(timeout: float, *, owner: str = "client") -> dict[str, Any]:
    output: dict[str, Any] = {"ok": False, "owner": owner}
    startup = launch_pair_ready(timeout)
    output["startup"] = {"attempt": startup["attempt"]}
    output["launch"] = startup["launch"]
    output["hub_ready"] = startup["hub_ready"]
    output["run_entry"] = startup["run_entry"]
    output["run_ready"] = startup["run_ready"]
    output["manual_combat"] = startup["manual_combat"]

    pids = detect_instance_pids()
    if owner == "host":
        direction = Direction(
            "host_to_client_fireball_explode",
            HOST_ID,
            HOST_NAME,
            HOST_PIPE,
            HOST_LOG,
            pids["host"],
            CLIENT_PIPE,
            CLIENT_LOG,
        )
    else:
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
    output["upgrade"] = (
        wait_for_host_target_upgrade(timeout)
        if owner == "host"
        else wait_for_client_target_upgrade(timeout)
    )
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
            "upgraded Fireball cast did not damage the exploded secondary target on the authority: "
            f"baseline={baseline_damage} upgraded={upgraded_damage} upgrade={target_step_summary(step_record)}"
        )

    output["ok"] = True
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--owner", choices=("host", "client"), default="client")
    parser.add_argument("--output", type=Path, default=RUNTIME_OUTPUT)
    args = parser.parse_args()

    result: dict[str, Any]
    try:
        result = run_verifier(timeout=args.timeout, owner=args.owner)
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
        try:
            args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        except Exception:
            pass
        print(json.dumps(result, indent=2, sort_keys=True))
        stop_games()
        return 1

    result["output"] = str(args.output)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    stop_games()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
