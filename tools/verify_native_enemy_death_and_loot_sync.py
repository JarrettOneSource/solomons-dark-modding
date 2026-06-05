#!/usr/bin/env python3
"""Verify native enemy death presentation and host-authored loot sync."""

from __future__ import annotations

import argparse
import json
import time
from typing import Any

from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    CLIENT_PIPE,
    HOST_ID,
    HOST_NAME,
    HOST_PIPE,
    ROOT,
    VerifyFailure,
    disable_bots,
    launch_pair,
    lua,
    parse_key_values,
    snap_to_nav,
    start_host_testrun_and_wait_for_clients,
    stop_games,
    wait_for_remote,
)
from verify_player_health_death_sync import set_local_player_vitals
from verify_real_input_spell_cast_sync import (
    CLIENT_LOG,
    HOST_LOG,
    Direction,
    detect_instance_pids,
    log_after,
    read_log,
)
from verify_run_world_snapshot import start_host_waves, wait_for_run_snapshot
from verify_multiplayer_loot_drop_materialization import (
    GOLD_TYPE_ID,
    capture as capture_loot_snapshot,
    require_host_spawn,
    select_materialized_drop,
)


RUNTIME_OUTPUT = ROOT / "runtime" / "native_enemy_death_and_loot_sync.json"
TEST_PLAYER_HP = 5000.0
CONTROLLED_TARGET_COUNT = 3
LOW_TARGET_HP = 0.75
TARGET_SPACING = 1200.0
TARGET_FORWARD_DISTANCE = 176.0
CONTROL_TARGET_CENTER_X = 1850.0
CONTROL_TARGET_Y = 1775.0
CONTROL_TARGET_POSITIONS = (
    (650.0, 1750.0),
    (1850.0, 1750.0),
    (2950.0, 1750.0),
)
FORCED_LOOT_GOLD_AMOUNT = 11


def values(pipe_name: str, code: str, timeout: float = 8.0) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, code, timeout=timeout))


def parse_int(value: str | None, default: int = 0) -> int:
    if value is None:
        return default
    try:
        if value.startswith(("0x", "0X")):
            return int(value, 16)
        return int(float(value))
    except (TypeError, ValueError):
        return default


def parse_float(value: str | None, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def kv_rows(row: dict[str, str], prefix: str, count_key: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for index in range(1, parse_int(row.get(count_key)) + 1):
        row_prefix = f"{prefix}.{index}."
        values_for_row = {
            key[len(row_prefix):]: value
            for key, value in row.items()
            if key.startswith(row_prefix)
        }
        if values_for_row:
            rows.append(values_for_row)
    return rows


def planned_target_positions() -> list[tuple[float, float]]:
    if len(CONTROL_TARGET_POSITIONS) >= CONTROLLED_TARGET_COUNT:
        return list(CONTROL_TARGET_POSITIONS[:CONTROLLED_TARGET_COUNT])
    positions: list[tuple[float, float]] = []
    midpoint = (CONTROLLED_TARGET_COUNT - 1) / 2.0
    for index in range(CONTROLLED_TARGET_COUNT):
        positions.append((
            CONTROL_TARGET_CENTER_X + ((index - midpoint) * TARGET_SPACING),
            CONTROL_TARGET_Y,
        ))
    return positions


CONTROL_HOST_TARGETS_LUA = r"""
local target_count = tonumber("__TARGET_COUNT__") or 3
local low_hp = tonumber("__LOW_HP__") or 0.75
local spacing = tonumber("__SPACING__") or 420.0
local forward_distance = tonumber("__FORWARD__") or 176.0
local target_positions = {
__TARGET_POSITIONS__
}
if #target_positions > 0 then
  target_count = #target_positions
end
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local function finite(v) return type(v) == "number" and v == v and v ~= math.huge and v ~= -math.huge end
local function hx(v) return string.format("0x%08X", tonumber(v) or 0) end
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
if player == nil or tonumber(player.actor_address) == 0 then
  emit("ok", false)
  emit("reason", "player_missing")
  return
end

local actors = sd.world.list_actors and sd.world.list_actors() or {}
local replicated = sd.world.get_replicated_actors and sd.world.get_replicated_actors() or nil
if replicated == nil or replicated.actors == nil then
  emit("ok", false)
  emit("reason", "replicated_snapshot_missing")
  return
end

local used_ids = {}
local function resolve_network_id(local_actor)
  local local_type = tonumber(local_actor.object_type_id) or 0
  local local_x = tonumber(local_actor.x) or 0
  local local_y = tonumber(local_actor.y) or 0
  local best_id = 0
  local best_d2 = nil
  for _, snapshot in ipairs(replicated.actors) do
    local id = tonumber(snapshot.network_actor_id) or 0
    local snapshot_type = tonumber(snapshot.object_type_id or snapshot.native_type_id) or 0
    local hp = tonumber(snapshot.hp) or 0
    local max_hp = tonumber(snapshot.max_hp) or 0
    if id ~= 0 and not used_ids[id] and snapshot.tracked_enemy and snapshot_type == local_type and max_hp > 0 and hp > 0.05 then
      local dx = (tonumber(snapshot.x) or 0) - local_x
      local dy = (tonumber(snapshot.y) or 0) - local_y
      local d2 = dx * dx + dy * dy
      if best_d2 == nil or d2 < best_d2 then
        best_d2 = d2
        best_id = id
      end
    end
  end
  return best_id
end

local candidates = {}
local player_x = tonumber(player.x) or 0
local player_y = tonumber(player.y) or 0
for _, actor in ipairs(actors) do
  local address = tonumber(actor.actor_address) or 0
  local hp = tonumber(actor.hp) or 0
  local max_hp = tonumber(actor.max_hp) or 0
  local x = tonumber(actor.x) or 0
  local y = tonumber(actor.y) or 0
  if address ~= 0 and actor.tracked_enemy and not actor.dead and max_hp > 0 and hp > 0.05 and finite(x) and finite(y) then
    local network_id = resolve_network_id(actor)
    if network_id ~= 0 then
      used_ids[network_id] = true
      local dx = x - player_x
      local dy = y - player_y
      candidates[#candidates + 1] = {
        actor = actor,
        address = address,
        network_id = network_id,
        distance_sq = dx * dx + dy * dy,
      }
    end
  end
end
table.sort(candidates, function(a, b) return a.distance_sq < b.distance_sq end)
if #candidates < target_count then
  emit("ok", false)
  emit("reason", "not_enough_tracked_enemies")
  emit("candidate_count", #candidates)
  return
end

local ox = sd.debug.layout_offset("actor_position_x")
local oy = sd.debug.layout_offset("actor_position_y")
local ohp = sd.debug.layout_offset("enemy_current_hp")
local omaxhp = sd.debug.layout_offset("enemy_max_hp")
local oprog = sd.debug.layout_offset("actor_progression_runtime_state")
local oph = sd.debug.layout_offset("progression_hp")
local opmaxh = sd.debug.layout_offset("progression_max_hp")
if ox == nil or oy == nil or ohp == nil or omaxhp == nil then
  emit("ok", false)
  emit("reason", "layout_missing")
  return
end

local anchor_x = (#target_positions > 0 and target_positions[1].x) or player_x
local target_y = (#target_positions > 0 and target_positions[1].y) or (player_y - forward_distance)
local start_x = anchor_x - spacing
local selected_addresses = {}
local function seed_enemy(address, x, y)
  local wrote = sd.debug.write_float(address + ox, x)
  wrote = sd.debug.write_float(address + oy, y) and wrote
  wrote = sd.debug.write_float(address + omaxhp, math.max(low_hp, 1.0)) and wrote
  wrote = sd.debug.write_float(address + ohp, low_hp) and wrote
  if oprog ~= nil and oph ~= nil and opmaxh ~= nil then
    local prog = tonumber(sd.debug.read_ptr(address + oprog)) or 0
    if prog ~= 0 then
      sd.debug.write_float(prog + opmaxh, math.max(low_hp, 1.0))
      sd.debug.write_float(prog + oph, low_hp)
    end
  end
  return wrote
end

local target_index = 0
for index = 1, target_count do
  local candidate = candidates[index]
  local planned_position = target_positions[index] or {}
  local target_x = planned_position.x or (start_x + ((index - 1) * spacing))
  local target_y_for_index = planned_position.y or target_y
  target_index = target_index + 1
  selected_addresses[candidate.address] = true
  emit("target." .. target_index .. ".network_id", string.format("%.0f", candidate.network_id))
  emit("target." .. target_index .. ".actor_address", hx(candidate.address))
  emit("target." .. target_index .. ".object_type_id", tonumber(candidate.actor.object_type_id) or 0)
  emit("target." .. target_index .. ".enemy_type", tonumber(candidate.actor.enemy_type) or -1)
  emit("target." .. target_index .. ".x", string.format("%.3f", target_x))
  emit("target." .. target_index .. ".y", string.format("%.3f", target_y_for_index))
  emit("target." .. target_index .. ".hp", string.format("%.3f", low_hp))
  emit("target." .. target_index .. ".seed_ok", seed_enemy(candidate.address, target_x, target_y_for_index))
end

local parked = 0
for index, actor in ipairs(actors) do
  local address = tonumber(actor.actor_address) or 0
  if address ~= 0 and actor.tracked_enemy and not selected_addresses[address] and not actor.dead then
    local park_x = anchor_x + 4200.0 + (index * 47.0)
    local park_y = target_y + 4200.0 + (index * 31.0)
    if sd.debug.write_float(address + ox, park_x) and sd.debug.write_float(address + oy, park_y) then
      parked = parked + 1
    end
  end
end
emit("ok", true)
emit("target.count", target_index)
emit("parked_count", parked)
emit("anchor_x", string.format("%.3f", anchor_x))
emit("target_y", string.format("%.3f", target_y))
"""


RESOLVE_HOST_TARGET_IDS_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local targets = {
__TARGET_ROWS__
}
local replicated = sd.world.get_replicated_actors and sd.world.get_replicated_actors() or nil
if replicated == nil or replicated.actors == nil then
  emit("ok", false)
  emit("reason", "replicated_snapshot_missing")
  return
end
local used = {}
local resolved = 0
for index, target in ipairs(targets) do
  local best = nil
  local best_d2 = nil
  for _, snapshot in ipairs(replicated.actors) do
    local id = tonumber(snapshot.network_actor_id) or 0
    local snapshot_type = tonumber(snapshot.object_type_id or snapshot.native_type_id) or 0
    local hp = tonumber(snapshot.hp) or 0
    local max_hp = tonumber(snapshot.max_hp) or 0
    if id ~= 0 and not used[id] and snapshot.tracked_enemy and not snapshot.dead and
        snapshot_type == target.object_type_id and max_hp > 0 and hp > 0.05 then
      local dx = (tonumber(snapshot.x) or 0) - target.x
      local dy = (tonumber(snapshot.y) or 0) - target.y
      local d2 = dx * dx + dy * dy
      if d2 <= (180.0 * 180.0) and (best_d2 == nil or d2 < best_d2) then
        best = snapshot
        best_d2 = d2
      end
    end
  end
  if best ~= nil then
    used[tonumber(best.network_actor_id) or 0] = true
    resolved = resolved + 1
    emit("target." .. index .. ".network_id", string.format("%.0f", tonumber(best.network_actor_id) or 0))
    emit("target." .. index .. ".snapshot_x", string.format("%.3f", tonumber(best.x) or 0))
    emit("target." .. index .. ".snapshot_y", string.format("%.3f", tonumber(best.y) or 0))
    emit("target." .. index .. ".hp", string.format("%.3f", tonumber(best.hp) or 0))
  else
    emit("target." .. index .. ".network_id", 0)
  end
end
emit("ok", resolved == #targets)
emit("target.count", #targets)
emit("resolved_count", resolved)
"""


TARGET_BINDING_STATUS_LUA = r"""
local network_id = tonumber("__NETWORK_ID__") or 0
local target_x = tonumber("__TARGET_X__") or 0
local target_y = tonumber("__TARGET_Y__") or 0
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local function hx(v) return string.format("0x%08X", tonumber(v) or 0) end
local replicated = sd.world.get_replicated_actors and sd.world.get_replicated_actors() or nil
local actors = sd.world.list_actors and sd.world.list_actors() or {}
if replicated == nil or replicated.actors == nil or replicated.bindings == nil then
  emit("ok", false)
  emit("reason", "replicated_snapshot_missing")
  return
end

local snapshot = nil
for _, actor in ipairs(replicated.actors) do
  if (tonumber(actor.network_actor_id) or 0) == network_id then
    snapshot = actor
    break
  end
end
emit("snapshot_found", snapshot ~= nil)
if snapshot ~= nil then
  emit("snapshot.type", tonumber(snapshot.object_type_id or snapshot.native_type_id) or 0)
  emit("snapshot.x", string.format("%.3f", tonumber(snapshot.x) or 0))
  emit("snapshot.y", string.format("%.3f", tonumber(snapshot.y) or 0))
  emit("snapshot.hp", string.format("%.3f", tonumber(snapshot.hp) or 0))
  emit("snapshot.max_hp", string.format("%.3f", tonumber(snapshot.max_hp) or 0))
  emit("snapshot.dead", snapshot.dead or false)
end

local actors_by_address = {}
for _, actor in ipairs(actors) do
  local address = tonumber(actor.actor_address) or 0
  if address ~= 0 then
    actors_by_address[address] = actor
  end
end

local exact = nil
local nearest = nil
local nearest_d2 = nil
for _, binding in ipairs(replicated.bindings) do
  local id = tonumber(binding.network_actor_id) or 0
  local address = tonumber(binding.local_actor_address) or 0
  local actor = actors_by_address[address]
  if id == network_id then
    exact = binding
  end
  if actor ~= nil and actor.tracked_enemy and not binding.parked and not binding.removed then
    local dx = (tonumber(actor.x) or 0) - target_x
    local dy = (tonumber(actor.y) or 0) - target_y
    local d2 = dx * dx + dy * dy
    if nearest_d2 == nil or d2 < nearest_d2 then
      nearest = {
        binding = binding,
        actor = actor,
      }
      nearest_d2 = d2
    end
  end
end

emit("exact_binding_found", exact ~= nil)
local exact_actor = nil
if exact ~= nil then
  local address = tonumber(exact.local_actor_address) or 0
  exact_actor = actors_by_address[address]
  emit("binding.network_id", string.format("%.0f", tonumber(exact.network_actor_id) or 0))
  emit("binding.local_actor_address", hx(address))
  emit("binding.matched", exact.matched or false)
  emit("binding.parked", exact.parked or false)
  emit("binding.removed", exact.removed or false)
  emit("binding.has_actor", exact_actor ~= nil)
  if exact_actor ~= nil then
    local ax = tonumber(exact_actor.x) or 0
    local ay = tonumber(exact_actor.y) or 0
    local dx = ax - target_x
    local dy = ay - target_y
    emit("binding.actor_type", tonumber(exact_actor.object_type_id) or 0)
    emit("binding.actor_x", string.format("%.3f", ax))
    emit("binding.actor_y", string.format("%.3f", ay))
    emit("binding.actor_hp", string.format("%.3f", tonumber(exact_actor.hp) or 0))
    emit("binding.actor_max_hp", string.format("%.3f", tonumber(exact_actor.max_hp) or 0))
    emit("binding.actor_dead", exact_actor.dead or false)
    emit("binding.distance_to_target", string.format("%.3f", math.sqrt(dx * dx + dy * dy)))
  end
end

if nearest ~= nil then
  emit("nearest.network_id", string.format("%.0f", tonumber(nearest.binding.network_actor_id) or 0))
  emit("nearest.local_actor_address", hx(tonumber(nearest.binding.local_actor_address) or 0))
  emit("nearest.type", tonumber(nearest.actor.object_type_id) or 0)
  emit("nearest.x", string.format("%.3f", tonumber(nearest.actor.x) or 0))
  emit("nearest.y", string.format("%.3f", tonumber(nearest.actor.y) or 0))
  emit("nearest.distance_to_target", string.format("%.3f", math.sqrt(nearest_d2 or 0)))
end

local ok = snapshot ~= nil and exact ~= nil and exact_actor ~= nil and
  exact.matched and not exact.parked and not exact.removed and
  not exact_actor.dead and (tonumber(exact_actor.max_hp) or 0) > 0 and
  (tonumber(exact_actor.hp) or 0) > 0.05
emit("ok", ok)
if not ok then
  emit("reason", "exact_live_binding_missing")
end
"""


LOOT_NEAR_LUA = r"""
local cx = tonumber("__X__") or 0
local cy = tonumber("__Y__") or 0
local radius = tonumber("__RADIUS__") or 360
local radius_sq = radius * radius
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local count = 0
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  local type_id = tonumber(actor.object_type_id) or 0
  if type_id == 0x07DB or type_id == 0x07DC or type_id == 0x07DD then
    local x = tonumber(actor.x) or 0
    local y = tonumber(actor.y) or 0
    local dx = x - cx
    local dy = y - cy
    if dx * dx + dy * dy <= radius_sq then
      count = count + 1
      local prefix = "loot." .. tostring(count) .. "."
      emit(prefix .. "type", type_id)
      emit(prefix .. "x", string.format("%.3f", x))
      emit(prefix .. "y", string.format("%.3f", y))
      emit(prefix .. "distance", string.format("%.3f", math.sqrt(dx * dx + dy * dy)))
    end
  end
end
emit("loot.count", count)
"""


HOST_NATIVE_KILL_TARGET_LUA = r"""
local network_id = tonumber("__NETWORK_ID__") or 0
local preferred_address = tonumber("__ACTOR_ADDRESS__") or 0
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local function hx(v) return string.format("0x%08X", tonumber(v) or 0) end
local actors = sd.world.list_actors and sd.world.list_actors() or {}
local hp_offset = sd.debug.layout_offset("enemy_current_hp")
local max_hp_offset = sd.debug.layout_offset("enemy_max_hp")
local progression_offset = sd.debug.layout_offset("actor_progression_runtime_state")
local progression_hp_offset = sd.debug.layout_offset("progression_hp")
local progression_max_hp_offset = sd.debug.layout_offset("progression_max_hp")
local death_handled_offset = sd.debug.layout_offset("enemy_death_handled")
if hp_offset == nil or max_hp_offset == nil then
  emit("ok", false)
  emit("reason", "layout_missing")
  return
end
local target = nil
if preferred_address ~= 0 then
  for _, actor in ipairs(actors) do
    if (tonumber(actor.actor_address) or 0) == preferred_address then
      target = actor
      break
    end
  end
end
if target == nil and network_id ~= 0 then
  local replicated = sd.world.get_replicated_actors and sd.world.get_replicated_actors() or nil
  local snapshot = nil
  if replicated ~= nil and replicated.actors ~= nil then
    for _, actor in ipairs(replicated.actors) do
      if (tonumber(actor.network_actor_id) or 0) == network_id then
        snapshot = actor
        break
      end
    end
  end
  if snapshot ~= nil then
    local sx = tonumber(snapshot.x) or 0
    local sy = tonumber(snapshot.y) or 0
    local stype = tonumber(snapshot.object_type_id or snapshot.native_type_id) or 0
    local best_d2 = nil
    for _, actor in ipairs(actors) do
      local address = tonumber(actor.actor_address) or 0
      if address ~= 0 and actor.tracked_enemy and not actor.dead and
          (tonumber(actor.object_type_id) or 0) == stype then
        local dx = (tonumber(actor.x) or 0) - sx
        local dy = (tonumber(actor.y) or 0) - sy
        local d2 = dx * dx + dy * dy
        if d2 <= (220.0 * 220.0) and (best_d2 == nil or d2 < best_d2) then
          target = actor
          best_d2 = d2
        end
      end
    end
  end
end
if target == nil then
  emit("ok", false)
  emit("reason", "target_missing")
  emit("network_id", string.format("%.0f", network_id))
  return
end
local address = tonumber(target.actor_address) or 0
local hp = tonumber(target.hp) or 0
local max_hp = tonumber(target.max_hp) or 0
if address == 0 or not target.tracked_enemy or max_hp <= 0 then
  emit("ok", false)
  emit("reason", "invalid_target")
  emit("target_actor", hx(address))
  emit("hp", string.format("%.3f", hp))
  emit("max_hp", string.format("%.3f", max_hp))
  return
end
emit("target_actor", hx(address))
emit("network_id", string.format("%.0f", network_id))
emit("old_hp", string.format("%.3f", hp))
emit("old_max_hp", string.format("%.3f", max_hp))
emit("old_dead", target.dead or false)
emit("old_death_handled", death_handled_offset ~= nil and (sd.debug.read_u8(address + death_handled_offset) or 0) or 0)
emit("write_max_hp", sd.debug.write_float(address + max_hp_offset, math.max(max_hp, 1.0)))
emit("write_hp", sd.debug.write_float(address + hp_offset, 0.0))
if progression_offset ~= nil and progression_hp_offset ~= nil and progression_max_hp_offset ~= nil then
  local progression = tonumber(sd.debug.read_ptr(address + progression_offset)) or 0
  if progression ~= 0 then
    emit("write_progression_max_hp", sd.debug.write_float(progression + progression_max_hp_offset, math.max(max_hp, 1.0)))
    emit("write_progression_hp", sd.debug.write_float(progression + progression_hp_offset, 0.0))
  end
end
if sd.world == nil or sd.world.trigger_enemy_death == nil then
  emit("ok", false)
  emit("reason", "trigger_enemy_death_missing")
  return
end
local trigger_ok, trigger_seh = sd.world.trigger_enemy_death(address)
emit("trigger_enemy_death", trigger_ok)
emit("trigger_enemy_death_seh", trigger_seh or 0)
emit("ok", true)
"""


CLIENT_NATIVE_KILL_TARGET_LUA = r"""
local network_id = tonumber("__NETWORK_ID__") or 0
local local_address = tonumber("__LOCAL_ACTOR_ADDRESS__") or 0
local before_hp = tonumber("__BEFORE_HP__") or 0
local max_hp = tonumber("__MAX_HP__") or 0
local x = tonumber("__X__") or 0
local y = tonumber("__Y__") or 0
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local hp_offset = sd.debug.layout_offset("enemy_current_hp")
local max_hp_offset = sd.debug.layout_offset("enemy_max_hp")
local progression_offset = sd.debug.layout_offset("actor_progression_runtime_state")
local progression_hp_offset = sd.debug.layout_offset("progression_hp")
local progression_max_hp_offset = sd.debug.layout_offset("progression_max_hp")
if network_id == 0 or local_address == 0 or hp_offset == nil or max_hp_offset == nil or max_hp <= 0 then
  emit("ok", false)
  emit("reason", "invalid_target_or_layout")
  return
end
if sd.input == nil or sd.input.queue_local_enemy_damage_claim == nil then
  emit("ok", false)
  emit("reason", "damage_claim_queue_missing")
  return
end
emit("queue_claim", sd.input.queue_local_enemy_damage_claim(network_id, 0, before_hp, 0.0, max_hp, x, y))
emit("write_max_hp", sd.debug.write_float(local_address + max_hp_offset, math.max(max_hp, 1.0)))
emit("write_hp", sd.debug.write_float(local_address + hp_offset, 0.0))
if progression_offset ~= nil and progression_hp_offset ~= nil and progression_max_hp_offset ~= nil then
  local progression = tonumber(sd.debug.read_ptr(local_address + progression_offset)) or 0
  if progression ~= 0 then
    emit("write_progression_max_hp", sd.debug.write_float(progression + progression_max_hp_offset, math.max(max_hp, 1.0)))
    emit("write_progression_hp", sd.debug.write_float(progression + progression_hp_offset, 0.0))
  end
end
if sd.world == nil or sd.world.trigger_enemy_death == nil then
  emit("ok", false)
  emit("reason", "trigger_enemy_death_missing")
  return
end
local trigger_ok, trigger_seh = sd.world.trigger_enemy_death(local_address)
emit("trigger_enemy_death", trigger_ok)
emit("trigger_enemy_death_seh", trigger_seh or 0)
emit("ok", true)
emit("network_actor_id", string.format("%.0f", network_id))
emit("local_actor_address", local_address)
emit("before_hp", string.format("%.3f", before_hp))
emit("max_hp", string.format("%.3f", max_hp))
emit("x", string.format("%.3f", x))
emit("y", string.format("%.3f", y))
"""


def control_host_targets() -> list[dict[str, Any]]:
    position_rows = "\n".join(
        "  {x = %.3f, y = %.3f},"
        % (x, y)
        for x, y in planned_target_positions()
    )
    code = (
        CONTROL_HOST_TARGETS_LUA
        .replace("__TARGET_COUNT__", str(CONTROLLED_TARGET_COUNT))
        .replace("__LOW_HP__", f"{LOW_TARGET_HP:.3f}")
        .replace("__SPACING__", f"{TARGET_SPACING:.3f}")
        .replace("__FORWARD__", f"{TARGET_FORWARD_DISTANCE:.3f}")
        .replace("__TARGET_POSITIONS__", position_rows)
    )
    result = values(HOST_PIPE, code, timeout=10.0)
    if result.get("ok") != "true":
        raise VerifyFailure(f"failed to control host targets: {result}")
    targets: list[dict[str, Any]] = []
    for row in kv_rows(result, "target", "target.count"):
        targets.append({
            "network_id": parse_int(row.get("network_id")),
            "actor_address": parse_int(row.get("actor_address")),
            "object_type_id": parse_int(row.get("object_type_id")),
            "enemy_type": parse_int(row.get("enemy_type"), -1),
            "x": parse_float(row.get("x")),
            "y": parse_float(row.get("y")),
            "seed_ok": row.get("seed_ok") == "true",
        })
    if len(targets) < CONTROLLED_TARGET_COUNT or any(target["network_id"] == 0 for target in targets):
        raise VerifyFailure(f"controlled target list is incomplete: raw={result} targets={targets}")
    return targets


def refresh_host_target_network_ids(targets: list[dict[str, Any]], timeout: float = 5.0) -> list[dict[str, Any]]:
    target_rows = "\n".join(
        "  {x = %.3f, y = %.3f, object_type_id = %d},"
        % (target["x"], target["y"], target["object_type_id"])
        for target in targets
    )
    code = RESOLVE_HOST_TARGET_IDS_LUA.replace("__TARGET_ROWS__", target_rows)
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = values(HOST_PIPE, code, timeout=5.0)
        if last.get("ok") == "true":
            refreshed = [dict(target) for target in targets]
            for index, row in enumerate(kv_rows(last, "target", "target.count")):
                if index >= len(refreshed):
                    break
                refreshed[index]["network_id"] = parse_int(row.get("network_id"))
                refreshed[index]["snapshot_x"] = parse_float(row.get("snapshot_x"))
                refreshed[index]["snapshot_y"] = parse_float(row.get("snapshot_y"))
                refreshed[index]["snapshot_hp"] = parse_float(row.get("hp"))
            if all(target["network_id"] != 0 for target in refreshed):
                return refreshed
        time.sleep(0.2)
    raise VerifyFailure(f"host target network ids did not resolve after positioning: raw={last} targets={targets}")


def target_binding_status(pipe_name: str, target: dict[str, Any]) -> dict[str, str]:
    return values(
        pipe_name,
        TARGET_BINDING_STATUS_LUA
        .replace("__NETWORK_ID__", str(target["network_id"]))
        .replace("__TARGET_X__", f"{target['x']:.3f}")
        .replace("__TARGET_Y__", f"{target['y']:.3f}"),
        timeout=5.0,
    )


def wait_for_exact_target_binding(pipe_name: str, target: dict[str, Any], timeout: float = 8.0) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = target_binding_status(pipe_name, target)
        if last.get("ok") == "true":
            return last
        time.sleep(0.2)
    raise VerifyFailure(f"{pipe_name} never exact-bound target={target}: last={last}")


def kill_host_through_native_handler(direction: Direction, target: dict[str, Any]) -> dict[str, Any]:
    source_offset = len(read_log(direction.source_log))
    receiver_offset = len(read_log(direction.receiver_log))
    receiver_binding = wait_for_exact_target_binding(direction.receiver_pipe, target, timeout=6.0)
    kill = values(
        direction.source_pipe,
        HOST_NATIVE_KILL_TARGET_LUA
        .replace("__NETWORK_ID__", str(target["network_id"]))
        .replace("__ACTOR_ADDRESS__", str(target["actor_address"])),
        timeout=5.0,
    )
    if kill.get("ok") != "true" or kill.get("write_hp") != "true" or kill.get("trigger_enemy_death") != "true":
        raise VerifyFailure(f"{direction.name}: host native kill setup failed: target={target} result={kill}")
    death = wait_for_native_death(direction, target, source_offset, receiver_offset, timeout=8.0)
    return {
        "receiver_binding": receiver_binding,
        "kill": kill,
        "death": death,
    }


def kill_client_through_damage_claim(direction: Direction, target: dict[str, Any]) -> dict[str, Any]:
    source_offset = len(read_log(direction.source_log))
    receiver_offset = len(read_log(direction.receiver_log))
    source_binding = wait_for_exact_target_binding(direction.source_pipe, target, timeout=6.0)
    local_actor_address = parse_int(source_binding.get("binding.local_actor_address"))
    before_hp = parse_float(source_binding.get("binding.actor_hp"), LOW_TARGET_HP)
    max_hp = parse_float(source_binding.get("binding.actor_max_hp"), max(before_hp, 1.0))
    target_x = parse_float(source_binding.get("binding.actor_x"), target["x"])
    target_y = parse_float(source_binding.get("binding.actor_y"), target["y"])
    kill = values(
        direction.source_pipe,
        CLIENT_NATIVE_KILL_TARGET_LUA
        .replace("__NETWORK_ID__", str(target["network_id"]))
        .replace("__LOCAL_ACTOR_ADDRESS__", str(local_actor_address))
        .replace("__BEFORE_HP__", f"{before_hp:.3f}")
        .replace("__MAX_HP__", f"{max_hp:.3f}")
        .replace("__X__", f"{target_x:.3f}")
        .replace("__Y__", f"{target_y:.3f}"),
        timeout=5.0,
    )
    if (kill.get("ok") != "true" or
            kill.get("queue_claim") != "true" or
            kill.get("write_hp") != "true" or
            kill.get("trigger_enemy_death") != "true"):
        raise VerifyFailure(
            f"{direction.name}: client native damage-claim kill failed: "
            f"target={target} binding={source_binding} result={kill}"
        )
    death = wait_for_native_death(direction, target, source_offset, receiver_offset, timeout=8.0)
    return {
        "source_binding": source_binding,
        "kill": kill,
        "death": death,
    }


def capture_nearby_loot(pipe_name: str, x: float, y: float, radius: float = 360.0) -> dict[str, Any]:
    raw = values(
        pipe_name,
        LOOT_NEAR_LUA
        .replace("__X__", f"{x:.3f}")
        .replace("__Y__", f"{y:.3f}")
        .replace("__RADIUS__", f"{radius:.3f}"),
        timeout=5.0,
    )
    return {
        "count": parse_int(raw.get("loot.count")),
        "rows": kv_rows(raw, "loot", "loot.count"),
    }


def sample_natural_loot(target: dict[str, Any], duration: float = 0.8) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        samples.append({
            "host": capture_nearby_loot(HOST_PIPE, target["x"], target["y"]),
            "client": capture_nearby_loot(CLIENT_PIPE, target["x"], target["y"]),
        })
        time.sleep(0.2)
    return samples


def safe_forced_loot_position(target: dict[str, Any]) -> tuple[float, float]:
    return snap_to_nav(HOST_PIPE, target["x"], target["y"] - 640.0)


def wait_for_forced_loot(target: dict[str, Any], amount: int, timeout: float = 8.0) -> dict[str, Any]:
    loot_x, loot_y = safe_forced_loot_position(target)
    spawn = require_host_spawn("gold", amount, loot_x, loot_y)
    deadline = time.monotonic() + timeout
    last_client: dict[str, str] = {}
    while time.monotonic() < deadline:
        last_client = capture_loot_snapshot(CLIENT_PIPE)
        materialized = select_materialized_drop(
            last_client,
            type_id=GOLD_TYPE_ID,
            amount=amount,
            resource_kind=None,
            raw_value=None,
            x=loot_x,
            y=loot_y,
        )
        if materialized is not None:
            return {
                "x": loot_x,
                "y": loot_y,
                "spawn": spawn,
                "client_materialized": materialized,
            }
        time.sleep(0.15)
    raise VerifyFailure(
        f"forced host gold reward did not materialize on client: amount={amount} "
        f"target={target} x={loot_x:.3f} y={loot_y:.3f} last_client={last_client}"
    )


def wait_for_native_death(
    direction: Direction,
    target: dict[str, Any],
    source_offset: int,
    receiver_offset: int,
    timeout: float = 8.0,
) -> dict[str, Any]:
    network_id = str(target["network_id"])
    deadline = time.monotonic() + timeout
    last_source = ""
    last_receiver = ""
    while time.monotonic() < deadline:
        last_source = log_after(direction.source_log, source_offset)
        last_receiver = log_after(direction.receiver_log, receiver_offset)
        if direction.name == "host_to_client":
            source_native = (
                f"network_actor_id={network_id}" in last_source
                and "recorded host run enemy death snapshot from native hook" in last_source
            ) or (
                "native enemy death trigger result." in last_source
                or "native enemy death presenter invoked." in last_source
            )
            receiver_death = (
                f"network_actor_id={network_id}" in last_receiver
                and (
                    "triggered replicated run enemy death" in last_receiver
                    or "bound authoritative dead run enemy snapshot" in last_receiver
                )
            )
        else:
            source_native = (
                "enemy.death hook invoked." in last_source
                or "native enemy death trigger result." in last_source
                or "native enemy death presenter invoked." in last_source
            )
            receiver_death = (
                f"target_network_actor_id={network_id}" in last_receiver
                and "Multiplayer enemy damage claim accepted" in last_receiver
                and "lethal=1" in last_receiver
                and "death_called=1" in last_receiver
            ) or (
                f"network_actor_id={network_id}" in last_receiver
                and "recorded host run enemy death snapshot from native hook" in last_receiver
            )
        if source_native and receiver_death:
            return {
                "source_native_death": source_native,
                "receiver_death_effect": receiver_death,
                "source_log_tail": last_source[-1800:],
                "receiver_log_tail": last_receiver[-1800:],
            }
        time.sleep(0.1)
    raise VerifyFailure(
        f"{direction.name}: native death/effect evidence missing for network_id={network_id}; "
        f"source_tail={last_source[-1800:]} receiver_tail={last_receiver[-1800:]}"
    )


def verify_kill_loot(target: dict[str, Any], loot_amount: int) -> dict[str, Any]:
    return {
        "natural_loot_samples": sample_natural_loot(target),
        "forced_loot": wait_for_forced_loot(target, loot_amount),
    }


def launch_run_pair() -> tuple[dict[str, object], dict[str, int]]:
    launch = launch_pair(preset="map_create_fire_mind_hub")
    disable_bots()
    run_entry = start_host_testrun_and_wait_for_clients(timeout=45.0)
    wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "testrun")
    wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "testrun")
    start = start_host_waves()
    snapshot = wait_for_run_snapshot(require_complete_lifecycle=True, stable_seconds=1.0)
    vitals = {
        "host": set_local_player_vitals(HOST_PIPE, TEST_PLAYER_HP, TEST_PLAYER_HP),
        "client": set_local_player_vitals(CLIENT_PIPE, TEST_PLAYER_HP, TEST_PLAYER_HP),
    }
    pids = detect_instance_pids()
    return {
        "launch": launch,
        "run_entry": run_entry,
        "start_waves": start,
        "snapshot": snapshot,
        "vitals": vitals,
    }, pids


def run_verifier(*, keep_open: bool) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": False}
    stop_games()
    try:
        setup, pids = launch_run_pair()
        result["setup"] = setup
        result["pids"] = pids
        targets = refresh_host_target_network_ids(control_host_targets())
        result["controlled_targets"] = targets

        for target in targets:
            wait_for_exact_target_binding(CLIENT_PIPE, target)
        result["client_bindings_ready"] = True

        host_to_client = Direction(
            "host_to_client",
            HOST_ID,
            HOST_NAME,
            HOST_PIPE,
            HOST_LOG,
            pids["host"],
            CLIENT_PIPE,
            CLIENT_LOG,
        )
        client_to_host = Direction(
            "client_to_host",
            CLIENT_ID,
            CLIENT_NAME,
            CLIENT_PIPE,
            CLIENT_LOG,
            pids["client"],
            HOST_PIPE,
            HOST_LOG,
        )

        result["host_native_kill"] = kill_host_through_native_handler(host_to_client, targets[0])
        result["host_native_loot"] = verify_kill_loot(targets[0], FORCED_LOOT_GOLD_AMOUNT)
        time.sleep(0.75)
        result["vitals_between_kills"] = {
            "host": set_local_player_vitals(HOST_PIPE, TEST_PLAYER_HP, TEST_PLAYER_HP),
            "client": set_local_player_vitals(CLIENT_PIPE, TEST_PLAYER_HP, TEST_PLAYER_HP),
        }
        result["client_native_kill"] = kill_client_through_damage_claim(client_to_host, targets[1])
        result["client_native_loot"] = verify_kill_loot(targets[1], FORCED_LOOT_GOLD_AMOUNT)
        result["remaining_control_target"] = targets[2]
        result["ok"] = True
        return result
    except Exception as exc:
        result["error"] = str(exc)
        return result
    finally:
        if not keep_open:
            stop_games()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-open", action="store_true")
    args = parser.parse_args()

    result: dict[str, Any]
    try:
        result = run_verifier(keep_open=args.keep_open)
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
        if not args.keep_open:
            stop_games()

    RUNTIME_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "ok": result.get("ok", False),
        "error": result.get("error"),
        "controlled_targets": result.get("controlled_targets"),
        "host_native_kill": {
            "death": bool(result.get("host_native_kill", {}).get("death")),
            "kill": result.get("host_native_kill", {}).get("kill"),
        } if result.get("host_native_kill") else None,
        "client_native_kill": {
            "death": bool(result.get("client_native_kill", {}).get("death")),
            "kill": result.get("client_native_kill", {}).get("kill"),
        } if result.get("client_native_kill") else None,
        "output": str(RUNTIME_OUTPUT),
    }, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
