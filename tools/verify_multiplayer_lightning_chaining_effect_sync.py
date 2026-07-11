#!/usr/bin/env python3
"""Verify that native Lightning chaining increases real host-side victim count."""

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
from verify_multiplayer_targeted_spell_matrix import (
    HOST_ENEMY_BY_ID_LUA,
    TARGET_REFRESH_LUA,
    host_enemy_by_id,
    refresh_target_aim,
)
from verify_multiplayer_primary_kill_stress import quiesce_gameplay_primary_input, values
from verify_player_health_death_sync import set_local_player_vitals
from verify_real_input_spell_cast_sync import (
    CLIENT_LOG,
    Direction,
    HOST_LOG,
    detect_instance_pids,
    ensure_host_combat_started,
    queue_gameplay_mouse_left,
    read_log,
    wait_for_source_cast,
)


ROOT = Path(__file__).resolve().parent.parent
RUNTIME_OUTPUT = ROOT / "runtime" / "multiplayer_lightning_chaining_effect_sync.json"
AIR_PRESET = "map_create_air_mind_hub"
TARGET_SKILL_FILE = "chaining.cfg"
TARGET_HP = 40.0
TARGET_DAMAGE_EPSILON = 0.05
MIN_PRIMARY_TARGET_MAX_HP = 1.0
MIN_PRIMARY_TARGET_RATIO = 0.9
LIGHTNING_CAST_FRAMES = 170
MAX_LEVEL_STEPS = 25
PIN_INTERVAL = 0.05
TARGET_REFRESH_DURATION = 1.8
NATURAL_CLUSTER_PATTERNS = (
    ((36.0, 24.0), (36.0, -24.0), (72.0, 24.0), (72.0, -24.0)),
    ((48.0, 24.0), (48.0, -24.0), (96.0, 24.0), (96.0, -24.0)),
    ((48.0, 36.0), (48.0, -36.0), (108.0, 36.0), (108.0, -36.0)),
    ((60.0, 36.0), (60.0, -36.0), (120.0, 36.0), (120.0, -36.0)),
    ((72.0, 36.0), (72.0, -36.0), (144.0, 36.0), (144.0, -36.0)),
)

HEALTHY_TARGET_SETUP_LUA = r"""
local min_max_hp = tonumber("__MIN_MAX_HP__") or 1
local min_ratio = tonumber("__MIN_RATIO__") or 0.9
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local function finite(v) return type(v) == "number" and v == v and v ~= math.huge and v ~= -math.huge end
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
if player == nil or tonumber(player.actor_address) == 0 then
  emit("ok", false)
  emit("reason", "player_missing")
  return
end
local player_actor = tonumber(player.actor_address) or 0
local actors = sd.world.list_actors and sd.world.list_actors() or {}
local replicated = sd.world.get_replicated_actors and sd.world.get_replicated_actors() or nil
if replicated == nil or replicated.actors == nil then
  emit("ok", false)
  emit("reason", "replicated_snapshot_missing")
  return
end

local local_by_address = {}
for _, actor in ipairs(actors) do
  local address = tonumber(actor.actor_address) or 0
  if address ~= 0 then local_by_address[address] = actor end
end

local binding_by_id = {}
if replicated.bindings ~= nil then
  for _, binding in ipairs(replicated.bindings) do
    local id = tonumber(binding.network_actor_id) or 0
    local address = tonumber(binding.local_actor_address) or 0
    if id ~= 0 and address ~= 0 and binding.matched and not binding.parked and not binding.removed then
      binding_by_id[id] = address
    end
  end
end

local function resolve_local_actor(snapshot)
  local id = tonumber(snapshot.network_actor_id) or 0
  local bound_address = binding_by_id[id]
  if bound_address ~= nil and local_by_address[bound_address] ~= nil then
    return local_by_address[bound_address]
  end
  local snapshot_type = tonumber(snapshot.native_type_id or snapshot.object_type_id) or 0
  local sx = tonumber(snapshot.x) or 0
  local sy = tonumber(snapshot.y) or 0
  local best = nil
  local best_d2 = nil
  for _, actor in ipairs(actors) do
    local address = tonumber(actor.actor_address) or 0
    local actor_type = tonumber(actor.object_type_id) or 0
    if address ~= 0 and actor.tracked_enemy and not actor.dead and actor_type == snapshot_type then
      local dx = (tonumber(actor.x) or 0) - sx
      local dy = (tonumber(actor.y) or 0) - sy
      local d2 = dx * dx + dy * dy
      if d2 <= (192.0 * 192.0) and (best_d2 == nil or d2 < best_d2) then
        best = actor
        best_d2 = d2
      end
    end
  end
  return best
end

local best_snapshot = nil
local best_local = nil
local best_d2 = nil
local player_x = tonumber(player.x) or 0
local player_y = tonumber(player.y) or 0
for _, snapshot in ipairs(replicated.actors) do
  local id = tonumber(snapshot.network_actor_id) or 0
  local hp = tonumber(snapshot.hp) or 0
  local max_hp = tonumber(snapshot.max_hp) or 0
  local sx = tonumber(snapshot.x) or 0
  local sy = tonumber(snapshot.y) or 0
  if id ~= 0 and
     snapshot.tracked_enemy and
     not snapshot.dead and
     max_hp >= min_max_hp and
     hp > 0 and
     (hp / max_hp) >= min_ratio and
     finite(sx) and
     finite(sy) then
    local local_actor = resolve_local_actor(snapshot)
    local address = tonumber(local_actor and local_actor.actor_address or 0) or 0
    if address ~= 0 then
      local dx = sx - player_x
      local dy = sy - player_y
      local d2 = dx * dx + dy * dy
      if best_snapshot == nil or d2 < best_d2 then
        best_snapshot = snapshot
        best_local = local_actor
        best_d2 = d2
      end
    end
  end
end

if best_snapshot == nil or best_local == nil then
  emit("ok", false)
  emit("reason", "healthy_target_missing")
  return
end

local target_actor = tonumber(best_local.actor_address) or 0
local target_x = tonumber(best_snapshot.x) or tonumber(best_local.x) or 0
local target_y = tonumber(best_snapshot.y) or tonumber(best_local.y) or 0
local caster_x = target_x
local caster_y = target_y + 176.0
local heading = 0.0
local ox = sd.debug.layout_offset("actor_position_x")
local oy = sd.debug.layout_offset("actor_position_y")
local oh = sd.debug.layout_offset("actor_heading")
local os = sd.debug.layout_offset("actor_animation_selection_state")
local oha = sd.debug.layout_offset("actor_control_brain_heading_accumulator")
local odf = sd.debug.layout_offset("actor_control_brain_desired_facing")
local odfs = sd.debug.layout_offset("actor_control_brain_desired_facing_smoothed")
local otarget = sd.debug.layout_offset("actor_current_target_actor")
local oaimx = sd.debug.layout_offset("actor_aim_target_x")
local oaimy = sd.debug.layout_offset("actor_aim_target_y")
local function write_facing(actor, value)
  local wrote = sd.debug.write_float(actor + oh, value)
  if os ~= nil and oha ~= nil and odf ~= nil and odfs ~= nil then
    local control = sd.debug.read_u32(actor + os) or 0
    if control ~= 0 then
      wrote = sd.debug.write_float(control + oha, value) and wrote
      wrote = sd.debug.write_float(control + odf, value) and wrote
      wrote = sd.debug.write_float(control + odfs, value) and wrote
    end
  end
  return wrote
end
local parked_count = 0
if ox ~= nil and oy ~= nil then
  for index, actor in ipairs(actors) do
    local address = tonumber(actor.actor_address) or 0
    if address ~= 0 and address ~= target_actor and actor.tracked_enemy and not actor.dead then
      local park_x = target_x + 2400.0 + (index * 37.0)
      local park_y = target_y + 2400.0 + (index * 29.0)
      if sd.debug.write_float(address + ox, park_x) and sd.debug.write_float(address + oy, park_y) then
        parked_count = parked_count + 1
      end
    end
  end
end

emit("ok", true)
emit("network_actor_id", string.format("%.0f", tonumber(best_snapshot.network_actor_id) or 0))
emit("target_actor", target_actor)
emit("target_type", tonumber(best_local.object_type_id) or 0)
emit("target_x", target_x)
emit("target_y", target_y)
emit("target_hp", tonumber(best_snapshot.hp) or 0)
emit("target_max_hp", tonumber(best_snapshot.max_hp) or 0)
emit("parked_count", parked_count)
emit("write.player_x", sd.debug.write_float(player_actor + ox, caster_x))
emit("write.player_y", sd.debug.write_float(player_actor + oy, caster_y))
emit("write.heading", write_facing(player_actor, heading))
emit("write.current_target", otarget ~= nil and sd.debug.write_ptr(player_actor + otarget, target_actor) or false)
emit("write.aim_x", oaimx ~= nil and sd.debug.write_float(player_actor + oaimx, target_x) or false)
emit("write.aim_y", oaimy ~= nil and sd.debug.write_float(player_actor + oaimy, target_y) or false)
local after = sd.player.get_state and sd.player.get_state() or nil
emit("after_x", after and after.x or 0)
emit("after_y", after and after.y or 0)
emit("after_heading", after and after.heading or 0)
"""

LIST_OTHER_TARGETS_LUA = r"""
local primary_id = tonumber("__PRIMARY__") or 0
local function emit(k,v) print(k .. '=' .. tostring(v)) end
local rep = sd.world.get_replicated_actors and sd.world.get_replicated_actors() or nil
emit("ok", rep ~= nil and rep.actors ~= nil)
if rep == nil or rep.actors == nil then return end
local count = 0
for _, actor in ipairs(rep.actors) do
  local id = tonumber(actor.network_actor_id) or 0
  local hp = tonumber(actor.hp) or 0
  local max_hp = tonumber(actor.max_hp) or 0
  if id ~= 0 and id ~= primary_id and actor.tracked_enemy and not actor.dead and max_hp > 0 and hp > 0.25 then
    count = count + 1
    local p = "row." .. tostring(count) .. "."
    emit(p .. "id", string.format("%.0f", id))
    emit(p .. "x", string.format("%.3f", tonumber(actor.x) or 0))
    emit(p .. "y", string.format("%.3f", tonumber(actor.y) or 0))
  end
end
emit("count", count)
"""

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

REFRESH_PRIMARY_TARGET_ONLY_LUA = r"""
local target_id = tonumber("__TARGET_ID__") or 0
local function emit(k, v) print(k .. '=' .. tostring(v)) end
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
if player == nil or tonumber(player.actor_address) == 0 then
  emit("ok", false)
  emit("reason", "player_missing")
  return
end
local replicated = sd.world.get_replicated_actors and sd.world.get_replicated_actors() or nil
local actors = sd.world.list_actors and sd.world.list_actors() or {}
if replicated == nil or replicated.actors == nil then
  emit("ok", false)
  emit("reason", "replicated_snapshot_missing")
  return
end
local snapshot = nil
for _, actor in ipairs(replicated.actors) do
  if tonumber(actor.network_actor_id) == target_id then
    snapshot = actor
    break
  end
end
if snapshot == nil then
  emit("ok", false)
  emit("reason", "target_snapshot_missing")
  return
end
local sx = tonumber(snapshot.x) or 0
local sy = tonumber(snapshot.y) or 0
local stype = tonumber(snapshot.native_type_id or snapshot.object_type_id) or 0
local best_actor = 0
local best_d2 = nil
for _, actor in ipairs(actors) do
  local actor_type = tonumber(actor.object_type_id) or 0
  local actor_address = tonumber(actor.actor_address) or 0
  if actor_address ~= 0 and actor.tracked_enemy and actor_type == stype and not actor.dead then
    local dx = (tonumber(actor.x) or 0) - sx
    local dy = (tonumber(actor.y) or 0) - sy
    local d2 = dx * dx + dy * dy
    if d2 <= (192.0 * 192.0) and (best_d2 == nil or d2 < best_d2) then
      best_actor = actor_address
      best_d2 = d2
    end
  end
end
if best_actor == 0 then
  emit("ok", false)
  emit("reason", "target_actor_missing")
  return
end
local player_actor = tonumber(player.actor_address) or 0
local target_offset = sd.debug.layout_offset("actor_current_target_actor")
local aim_x_offset = sd.debug.layout_offset("actor_aim_target_x")
local aim_y_offset = sd.debug.layout_offset("actor_aim_target_y")
emit("ok", true)
emit("target_x", sx)
emit("target_y", sy)
emit("write.current_target", target_offset ~= nil and sd.debug.write_ptr(player_actor + target_offset, best_actor) or false)
emit("write.aim_x", aim_x_offset ~= nil and sd.debug.write_float(player_actor + aim_x_offset, sx) or false)
emit("write.aim_y", aim_y_offset ~= nil and sd.debug.write_float(player_actor + aim_y_offset, sy) or false)
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


def query_enemy_state(network_actor_id: int) -> dict[str, str]:
    return host_enemy_by_id(str(network_actor_id))


def list_other_targets(primary_network_id: int) -> dict[str, str]:
    rows = values(CLIENT_PIPE, LIST_OTHER_TARGETS_LUA.replace("__PRIMARY__", str(primary_network_id)))
    if rows.get("ok") != "true":
        raise VerifyFailure(f"natural Lightning other-target listing failed: {rows}")
    return rows


def setup_healthy_target() -> dict[str, str]:
    result = values(
        CLIENT_PIPE,
        HEALTHY_TARGET_SETUP_LUA
        .replace("__MIN_MAX_HP__", f"{MIN_PRIMARY_TARGET_MAX_HP:.3f}")
        .replace("__MIN_RATIO__", f"{MIN_PRIMARY_TARGET_RATIO:.3f}"),
        timeout=5.0,
    )
    required_writes = (
        "write.player_x",
        "write.player_y",
        "write.heading",
        "write.current_target",
        "write.aim_x",
        "write.aim_y",
    )
    if result.get("ok") != "true" or any(result.get(key) != "true" for key in required_writes):
        raise VerifyFailure(f"healthy target setup failed on {CLIENT_PIPE}: {result}")
    return result


def build_natural_cluster(secondary_offsets: tuple[tuple[float, float], ...]) -> dict[str, Any]:
    setup: dict[str, str] | None = None
    for _ in range(6):
        try:
            setup = setup_healthy_target()
            break
        except VerifyFailure:
            time.sleep(0.2)
    if setup is None:
        raise VerifyFailure("natural Lightning could not find a sufficiently healthy primary target")
    primary_network_id = parse_int_text(setup.get("network_actor_id"), 0)
    primary_actor_address = parse_int_text(setup.get("target_actor"), 0)
    primary_x = parse_float(setup.get("target_x"))
    primary_y = parse_float(setup.get("target_y"))
    if primary_network_id == 0 or primary_actor_address == 0:
        raise VerifyFailure(f"natural Lightning setup produced no usable primary target: {setup}")

    rows = list_other_targets(primary_network_id)
    count = parse_int_text(rows.get("count"), 0)
    if count < len(secondary_offsets):
        raise VerifyFailure(
            f"natural Lightning did not expose enough secondary enemies: rows={rows} offsets={secondary_offsets}"
        )

    targets: list[dict[str, Any]] = [
        {
            "label": "primary",
            "network_id": primary_network_id,
            "x": primary_x,
            "y": primary_y,
        }
    ]
    for index, (offset_x, offset_y) in enumerate(secondary_offsets, start=1):
        network_id = parse_int_text(rows.get(f"row.{index}.id"), 0)
        if network_id == 0:
            raise VerifyFailure(f"natural Lightning secondary target {index} had no network id: rows={rows}")
        targets.append(
            {
                "label": f"secondary_{index}",
                "network_id": network_id,
                "x": primary_x + offset_x,
                "y": primary_y + offset_y,
            }
        )

    return {
        "setup": setup,
        "rows": rows,
        "secondary_offsets": [
            {"x": offset_x, "y": offset_y}
            for offset_x, offset_y in secondary_offsets
        ],
        "targets": targets,
        "primary_network_id": primary_network_id,
        "primary_actor_address": primary_actor_address,
        "primary_x": primary_x,
        "primary_y": primary_y,
    }


def stabilize_cluster(
    cluster: dict[str, Any],
    *,
    duration: float,
    interval: float = PIN_INTERVAL,
    write_hp: bool,
    include_host: bool = True,
    include_client: bool = True,
) -> dict[str, Any]:
    end_time = time.monotonic() + duration
    last_targets: list[dict[str, Any]] = []
    while time.monotonic() < end_time:
        hp_value = TARGET_HP if write_hp else None
        cycle: list[dict[str, Any]] = []
        for target in cluster["targets"]:
            record: dict[str, Any] = {"network_id": target["network_id"]}
            if include_host:
                record["host"] = pin_enemy_transform(
                    HOST_PIPE,
                    target["network_id"],
                    target["x"],
                    target["y"],
                    hp=hp_value,
                )
            if include_client:
                record["client"] = pin_enemy_transform(
                    CLIENT_PIPE,
                    target["network_id"],
                    target["x"],
                    target["y"],
                    hp=hp_value,
                )
            cycle.append(record)
        last_targets = cycle
        time.sleep(interval)
    return {"targets": last_targets}


def observe_cluster_damage(
    cluster: dict[str, Any],
    before_hp_by_id: dict[int, float],
    *,
    duration: float = 2.5,
    interval: float = 0.1,
) -> dict[str, Any]:
    deadline = time.monotonic() + duration
    min_hp_by_id = dict(before_hp_by_id)
    removed_by_id = {network_id: False for network_id in before_hp_by_id}
    last_by_id: dict[int, dict[str, str]] = {}
    while time.monotonic() < deadline:
        for target in cluster["targets"]:
            network_id = int(target["network_id"])
            current = query_enemy_state(network_id)
            last_by_id[network_id] = current
            if current.get("found") == "true":
                min_hp_by_id[network_id] = min(
                    min_hp_by_id[network_id],
                    parse_float(current.get("hp"), before_hp_by_id[network_id]),
                )
            else:
                removed_by_id[network_id] = True
                min_hp_by_id[network_id] = 0.0
        time.sleep(interval)

    victims: list[dict[str, Any]] = []
    for target in cluster["targets"]:
        network_id = int(target["network_id"])
        before_hp = before_hp_by_id[network_id]
        min_hp = min_hp_by_id[network_id]
        damage = before_hp - min_hp
        damaged = damage > TARGET_DAMAGE_EPSILON
        victim = {
            "network_id": network_id,
            "before_hp": before_hp,
            "min_hp": min_hp,
            "damage": damage,
            "damaged": damaged,
            "removed": removed_by_id[network_id],
            "target": network_id == cluster["primary_network_id"],
            "last": last_by_id.get(network_id, {}),
        }
        if damaged:
            victims.append(victim)
    return {
        "before_hp_by_id": before_hp_by_id,
        "victims": victims,
        "victim_count": len(victims),
        "target_damaged": any(victim["target"] for victim in victims),
        "last_by_id": last_by_id,
    }


def maintain_primary_target_aim(network_actor_id: int, *, duration: float = TARGET_REFRESH_DURATION) -> dict[str, Any]:
    deadline = time.monotonic() + duration
    attempts: list[dict[str, str]] = []
    while time.monotonic() < deadline:
        result = values(
            CLIENT_PIPE,
            REFRESH_PRIMARY_TARGET_ONLY_LUA.replace("__TARGET_ID__", str(network_actor_id)),
        )
        attempts.append(result)
        time.sleep(PIN_INTERVAL)
    return {
        "attempt_count": len(attempts),
        "last": attempts[-1] if attempts else {},
    }


def cast_lightning_cluster(direction: Direction, cluster: dict[str, Any], label: str) -> dict[str, Any]:
    quiesce_gameplay_primary_input(f"{label}.before")
    set_local_player_vitals(HOST_PIPE, 5000.0, 5000.0)
    set_local_player_vitals(CLIENT_PIPE, 5000.0, 5000.0)

    stabilize_cluster(cluster, duration=0.35, write_hp=True)
    before_hp_by_id = {
        int(target["network_id"]): parse_float(
            query_enemy_state(int(target["network_id"])).get("hp"),
            TARGET_HP,
        )
        for target in cluster["targets"]
    }

    source_offset = len(read_log(direction.source_log))
    aim_refresh = refresh_target_aim(CLIENT_PIPE, str(cluster["primary_network_id"]))
    queue_result = queue_gameplay_mouse_left(direction, LIGHTNING_CAST_FRAMES)
    target_refresh = maintain_primary_target_aim(cluster["primary_network_id"])
    pin_during_cast = stabilize_cluster(
        cluster,
        duration=TARGET_REFRESH_DURATION,
        write_hp=False,
        include_host=True,
        include_client=True,
    )
    source_log, phase_counts, native_hook_count = wait_for_source_cast(
        direction,
        source_offset,
        {"pressed": 1, "released": 1},
        timeout=8.0,
    )
    damage = observe_cluster_damage(cluster, before_hp_by_id)
    return {
        "aim_refresh": aim_refresh,
        "queue_result": queue_result,
        "target_refresh": target_refresh,
        "pin_during_cast": pin_during_cast,
        "phase_counts": phase_counts,
        "native_hook_count": native_hook_count,
        "source_log_tail": source_log[-4000:],
        "damage": damage,
        "primary_accepted": damage["target_damaged"],
        "accepted_target_count": damage["victim_count"],
    }


def run_pattern_search(direction: Direction, *, phase: str) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    for offsets in NATURAL_CLUSTER_PATTERNS:
        cluster = build_natural_cluster(offsets)
        cast = cast_lightning_cluster(
            direction,
            cluster,
            f"lightning_chain.{phase}.offsets_{'_'.join(f'{int(dx)}_{int(dy)}' for dx, dy in offsets)}",
        )
        attempt = {
            "offsets": offsets,
            "cluster": cluster,
            "cast": cast,
        }
        attempts.append(attempt)
    return {"attempts": attempts}


def wait_for_target_upgrade(timeout: float) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    for step in range(1, MAX_LEVEL_STEPS + 1):
        host_client_stats = query_progression_stats(HOST_PIPE, participant_id=CLIENT_ID)
        client_stats = query_progression_stats(CLIENT_PIPE)
        if not host_client_stats["available"] or not client_stats["available"]:
            raise VerifyFailure(
                "Lightning chaining probe could not read client progression stats: "
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
                raise VerifyFailure(f"host remote chaining active count did not increase: {step_record}")
            if after_client_selected["active"] <= before_client_selected["active"]:
                raise VerifyFailure(f"client local chaining active count did not increase: {step_record}")
            return {
                "step_record": step_record,
                "steps": steps,
            }
    raise VerifyFailure(
        f"Lightning chaining upgrade was not offered within {MAX_LEVEL_STEPS} level-up steps: "
        f"{[target_step_summary(step) for step in steps]}"
    )


def launch_pair_ready(timeout: float) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(1, 4):
        stop_games()
        try:
            launch = launch_pair(preset=AIR_PRESET, god_mode=True)
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
    output["combat"] = ensure_host_combat_started()

    pids = detect_instance_pids()
    direction = Direction(
        "client_to_host_lightning_chaining",
        CLIENT_ID,
        CLIENT_NAME,
        CLIENT_PIPE,
        CLIENT_LOG,
        pids["client"],
        HOST_PIPE,
        HOST_LOG,
    )

    output["baseline_pattern_search"] = run_pattern_search(direction, phase="baseline")
    baseline_attempts = output["baseline_pattern_search"]["attempts"]
    if not any(attempt["cast"]["primary_accepted"] for attempt in baseline_attempts):
        raise VerifyFailure(
            "baseline Lightning never damaged the primary target across searched patterns: "
            f"{output['baseline_pattern_search']}"
        )

    output["upgrade"] = wait_for_target_upgrade(timeout)
    step_record = output["upgrade"]["step_record"]
    output["upgrade_result_summary"] = {
        "selected_option_id": step_record["offer"]["selected_option_id"],
        "selected_option_index": step_record["offer"]["selected_option_index"],
        "selected_skill_file": step_record["offer"]["enriched_options"][step_record["offer"]["selected_option_index"] - 1]["skill_file"],
    }

    output["upgraded_pattern_search"] = run_pattern_search(direction, phase="upgraded")
    upgraded_attempts = output["upgraded_pattern_search"]["attempts"]
    if not any(attempt["cast"]["primary_accepted"] for attempt in upgraded_attempts):
        raise VerifyFailure(
            "upgraded Lightning never damaged the primary target across searched patterns: "
            f"{output['upgraded_pattern_search']}"
        )

    baseline_by_pattern = {
        tuple(attempt["offsets"]): attempt
        for attempt in baseline_attempts
    }
    upgraded_by_pattern = {
        tuple(attempt["offsets"]): attempt
        for attempt in upgraded_attempts
    }
    improvement: dict[str, Any] | None = None
    for offsets, baseline_attempt in baseline_by_pattern.items():
        upgraded_attempt = upgraded_by_pattern.get(offsets)
        if upgraded_attempt is None:
            continue
        baseline_count = baseline_attempt["cast"]["accepted_target_count"]
        upgraded_count = upgraded_attempt["cast"]["accepted_target_count"]
        if (
            baseline_attempt["cast"]["primary_accepted"]
            and upgraded_attempt["cast"]["primary_accepted"]
            and upgraded_count > baseline_count
        ):
            improvement = {
                "offsets": offsets,
                "baseline_victim_count": baseline_count,
                "upgraded_victim_count": upgraded_count,
                "baseline_attempt": baseline_attempt,
                "upgraded_attempt": upgraded_attempt,
            }
            break
    if improvement is None:
        raise VerifyFailure(
            "native chaining did not increase damaged Lightning target count across searched patterns: "
            f"baseline={output['baseline_pattern_search']} upgraded={output['upgraded_pattern_search']}"
        )
    output["improvement"] = improvement

    output["ok"] = True
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
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
