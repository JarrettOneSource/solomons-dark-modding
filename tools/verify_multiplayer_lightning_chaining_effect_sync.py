#!/usr/bin/env python3
"""Verify native Lightning Chaining behavior on its owner and remote observer."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from cast_state_probe import read_runtime_layout_offset
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
    capture,
    choose_client_option,
    enrich_offer_options,
    publish_offer,
    query_progression_entry,
    query_progression_stats,
    wait_for_choice_result,
    wait_for_client_offer,
    wait_for_wait_status,
)
from verify_multiplayer_host_owned_level_up_sync import (
    choose_host_option,
    publish_host_self_offer,
    wait_for_broadcast_result,
    wait_for_host_offer,
)
from verify_multiplayer_targeted_spell_matrix import (
    host_enemy_by_id,
)
from verify_multiplayer_primary_kill_stress import (
    CLIENT_TARGET,
    cleanup_live_enemies,
    enable_manual_stock_spawner_combat,
    find_target,
    place_pair_on_clear_lane,
    prepare_and_queue_caster,
    quiesce_gameplay_primary_input,
    set_manual_spawner_test_mode,
    spawn_one_enemy,
    values,
    wait_for_cast_runtime_ready,
)
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
FLAT_BONEYARD = ROOT / "tests" / "fixtures" / "boneyards" / "flat_multiplayer_test.boneyard"
TARGET_SKILL_FILE = "chaining.cfg"
CHAINING_OPTION_ID = 25
AIR_PRIMARY_DISPATCHER_FUNCTION = read_runtime_layout_offset("spell_cast_018")
LIGHTNING_CHAIN_TARGET_FUNCTION = read_runtime_layout_offset("air_lightning_chain_target")
AIR_LIGHTNING_CHAIN_COUNT_OFFSET = read_runtime_layout_offset("actor_air_lightning_chain_count")
TARGET_HP = 40.0
# Level-one Lightning can author a 0.025 HP tick on the host when the client
# owns the held cast.  Keep this above ordinary float noise while accepting a
# single genuine native tick in either ownership direction.
TARGET_DAMAGE_EPSILON = 0.01
MIN_PRIMARY_TARGET_MAX_HP = 1.0
MIN_PRIMARY_TARGET_RATIO = 0.9
LIGHTNING_CAST_FRAMES = 170
MAX_LEVEL_STEPS = 25
PIN_INTERVAL = 0.05
TARGET_REFRESH_DURATION = 1.8
MAX_AIR_CHAIN_ENDPOINT_ERROR = 2.0
CLUSTER_PATTERNS = (
    ((72.0, 36.0), (72.0, -36.0), (144.0, 36.0), (144.0, -36.0)),
    ((60.0, 36.0), (60.0, -36.0), (120.0, 36.0), (120.0, -36.0)),
    ((48.0, 36.0), (48.0, -36.0), (108.0, 36.0), (108.0, -36.0)),
    ((48.0, 24.0), (48.0, -24.0), (96.0, 24.0), (96.0, -24.0)),
    ((36.0, 24.0), (36.0, -24.0), (72.0, 24.0), (72.0, -24.0)),
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

NATURAL_ENEMY_POPULATION_LUA = r"""
local function emit(k,v) print(k .. '=' .. tostring(v)) end
local rep = sd.world.get_replicated_actors and sd.world.get_replicated_actors() or nil
local count = 0
if rep ~= nil and rep.actors ~= nil then
  for _, actor in ipairs(rep.actors) do
    if tonumber(actor.network_actor_id) ~= 0 and
       actor.tracked_enemy and
       not actor.dead and
       (tonumber(actor.hp) or 0) > 0.05 then
      count = count + 1
    end
  end
end
emit('ok', rep ~= nil and rep.actors ~= nil)
emit('count', count)
"""

PARK_LOCAL_OBSERVER_LUA = r"""
local x = tonumber("__X__") or 0
local y = tonumber("__Y__") or 0
local function emit(k,v) print(k .. '=' .. tostring(v)) end
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
local actor = tonumber(player and player.actor_address or 0) or 0
if sd.input ~= nil and sd.input.clear_mouse_left ~= nil then sd.input.clear_mouse_left() end
if sd.input ~= nil and sd.input.clear_local_cast_state ~= nil then
  pcall(sd.input.clear_local_cast_state)
end
local ox = sd.debug.layout_offset("actor_position_x")
local oy = sd.debug.layout_offset("actor_position_y")
local ot = sd.debug.layout_offset("actor_current_target_actor")
local ob = sd.debug.layout_offset("actor_current_target_bucket_delta")
emit("actor", actor)
emit("write_x", actor ~= 0 and ox ~= nil and sd.debug.write_float(actor + ox, x) or false)
emit("write_y", actor ~= 0 and oy ~= nil and sd.debug.write_float(actor + oy, y) or false)
emit("write_target", actor ~= 0 and ot ~= nil and sd.debug.write_ptr(actor + ot, 0) or false)
emit("write_bucket", actor ~= 0 and ob ~= nil and sd.debug.write_i32(actor + ob, 0) or false)
if actor ~= 0 and sd.world ~= nil and sd.world.rebind_actor ~= nil then
  local ok, err = sd.world.rebind_actor(actor)
  emit("rebind", ok)
  emit("rebind_error", err or "")
end
emit("ok", actor ~= 0)
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

PIN_CLUSTER_BATCH_LUA = r"""
local rows = __ROWS__
local hp = tonumber("__HP__")
local write_hp = "__WRITE_HP__" == "true"
local do_rebind = "__REBIND__" == "true"
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local x_offset = sd.debug.layout_offset("actor_position_x")
local y_offset = sd.debug.layout_offset("actor_position_y")
local found = 0
local positioned = 0
local health_writes = 0
local rebound = 0
for _, row in ipairs(rows) do
  local actor = sd.world.get_run_enemy_by_network_id and sd.world.get_run_enemy_by_network_id(row.id) or nil
  if actor ~= nil then
    found = found + 1
    local address = tonumber(actor.actor_address) or 0
    local wrote_x = x_offset ~= nil and sd.debug.write_float(address + x_offset, row.x)
    local wrote_y = y_offset ~= nil and sd.debug.write_float(address + y_offset, row.y)
    if wrote_x and wrote_y then positioned = positioned + 1 end
    if write_hp and row.selected and sd.gameplay.set_run_enemy_health(address, hp, hp) then
      health_writes = health_writes + 1
    end
    if do_rebind and sd.world ~= nil and sd.world.rebind_actor ~= nil then
      local ok = sd.world.rebind_actor(address)
      if ok then rebound = rebound + 1 end
    end
  end
end
emit("row_count", #rows)
emit("found", found)
emit("positioned", positioned)
emit("health_writes", health_writes)
emit("rebound", rebound)
emit("ok", found == #rows and positioned == #rows)
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
local bound = sd.world.get_run_enemy_by_network_id and sd.world.get_run_enemy_by_network_id(target_id) or nil
local best_actor = tonumber(bound and bound.actor_address or 0) or 0
if best_actor == 0 then
  emit("ok", false)
  emit("reason", "target_actor_missing")
  return
end
local player_actor = tonumber(player.actor_address) or 0
local position_x_offset = sd.debug.layout_offset("actor_position_x")
local position_y_offset = sd.debug.layout_offset("actor_position_y")
local heading_offset = sd.debug.layout_offset("actor_heading")
local target_offset = sd.debug.layout_offset("actor_current_target_actor")
local aim_x_offset = sd.debug.layout_offset("actor_aim_target_x")
local aim_y_offset = sd.debug.layout_offset("actor_aim_target_y")
emit("ok", true)
emit("network_actor_id", string.format("%.0f", target_id))
emit("target_actor", string.format("0x%08X", best_actor))
emit("target_x", sx)
emit("target_y", sy)
emit("write.player_x", position_x_offset ~= nil and sd.debug.write_float(player_actor + position_x_offset, sx) or false)
emit("write.player_y", position_y_offset ~= nil and sd.debug.write_float(player_actor + position_y_offset, sy + 176.0) or false)
emit("write.heading", heading_offset ~= nil and sd.debug.write_float(player_actor + heading_offset, 0.0) or false)
emit("write.current_target", target_offset ~= nil and sd.debug.write_ptr(player_actor + target_offset, best_actor) or false)
emit("write.aim_x", aim_x_offset ~= nil and sd.debug.write_float(player_actor + aim_x_offset, sx) or false)
emit("write.aim_y", aim_y_offset ~= nil and sd.debug.write_float(player_actor + aim_y_offset, sy) or false)
"""

AIR_CHAIN_AUDIT_LUA = r"""
local owner_id = tonumber("__OWNER_ID__") or 0
local function emit(k, v) print(k .. '=' .. tostring(v)) end
local function emit_target(prefix, target)
  emit(prefix .. '.ordinal', tonumber(target.ordinal) or -1)
  emit(prefix .. '.network_actor_id', tostring(target.network_actor_id or 0))
  emit(prefix .. '.local_actor_address', tostring(target.local_actor_address or 0))
  emit(prefix .. '.fallback_actor_address', tostring(target.fallback_actor_address or 0))
  emit(prefix .. '.matched', target.matched == true)
  emit(prefix .. '.authoritative_null', target.authoritative_null == true)
  emit(prefix .. '.source_override_attempted', target.source_override_attempted == true)
  emit(prefix .. '.source_override_applied', target.source_override_applied == true)
  emit(prefix .. '.target_override_attempted', target.target_override_attempted == true)
  emit(prefix .. '.target_override_applied', target.target_override_applied == true)
  for _, key in ipairs({
    'source_x', 'source_y', 'target_x', 'target_y',
    'local_source_x', 'local_source_y', 'local_target_x', 'local_target_y',
    'source_error', 'source_error_before_override',
    'target_error', 'target_error_before_override'
  }) do
    emit(prefix .. '.' .. key, tonumber(target[key]) or 0)
  end
end
local function emit_snapshot(prefix, snapshot)
  snapshot = snapshot or {}
  emit(prefix .. '.valid', snapshot.valid == true)
  emit(prefix .. '.active', snapshot.active == true)
  emit(prefix .. '.terminal', snapshot.terminal == true)
  emit(prefix .. '.truncated', snapshot.truncated == true)
  emit(prefix .. '.owner_participant_id', tostring(snapshot.owner_participant_id or 0))
  emit(prefix .. '.received_ms', tostring(snapshot.received_ms or 0))
  emit(prefix .. '.sequence', tonumber(snapshot.sequence) or 0)
  emit(prefix .. '.run_nonce', tonumber(snapshot.run_nonce) or 0)
  emit(prefix .. '.cast_sequence', tonumber(snapshot.cast_sequence) or 0)
  emit(prefix .. '.frame_sequence', tonumber(snapshot.frame_sequence) or 0)
  emit(prefix .. '.target_count', tonumber(snapshot.target_count) or 0)
  emit(prefix .. '.target_total_count', tonumber(snapshot.target_total_count) or 0)
  for index, target in ipairs(snapshot.targets or {}) do
    emit_target(prefix .. '.target.' .. tostring(index), target)
  end
end
local function emit_history(prefix, history, filter_owner)
  local selected = {}
  for _, snapshot in ipairs(history or {}) do
    if filter_owner == 0 or tonumber(snapshot.owner_participant_id) == filter_owner then
      table.insert(selected, snapshot)
    end
  end
  -- The runtime retains 128 frames. A remote replay can apply near the start of
  -- a 170-frame held cast while the owner continues publishing until release;
  -- emitting only 48 then drops the exact applied frame even though the apply
  -- binding and all later chain frames are correct. Preserve the full runtime
  -- window so frame-exact endpoint parity remains provable for every owner.
  local first = math.max(1, #selected - 127)
  local output_index = 0
  for index = first, #selected do
    output_index = output_index + 1
    emit_snapshot(prefix .. '.' .. tostring(output_index), selected[index])
  end
  emit(prefix .. '.count', output_index)
end

local audit = sd.world.get_replicated_air_chains and sd.world.get_replicated_air_chains() or nil
emit('available', audit ~= nil)
if audit == nil then return end
emit_snapshot('local_capture', audit.local_capture)
emit_history('local_history', audit.local_history, 0)
emit_history('snapshot_history', audit.snapshot_history, owner_id)
local apply = audit.apply or {}
for _, key in ipairs({
  'valid', 'applied_ms', 'owner_participant_id', 'cast_sequence', 'frame_sequence',
  'cumulative_override_attempt_count', 'cumulative_override_success_count',
  'cumulative_authoritative_null_count',
  'cumulative_missing_snapshot_fallback_count',
  'cumulative_stale_snapshot_fallback_count', 'cumulative_unmapped_target_count',
  'cumulative_source_override_success_count',
  'cumulative_source_override_failure_count',
  'cumulative_target_override_success_count',
  'cumulative_target_override_failure_count',
  'max_applied_target_count'
}) do
  emit('apply.' .. key, apply[key] or 0)
end
emit('apply.binding_count', #(apply.bindings or {}))
for index, binding in ipairs(apply.bindings or {}) do
  emit_target('apply.binding.' .. tostring(index), binding)
end
"""

AIR_CHAIN_STATE_LUA = r"""
local participant_id = tonumber("__PARTICIPANT_ID__") or 0
local chain_count_offset = tonumber("__CHAIN_COUNT_OFFSET__") or 0x284
local function emit(k, v) print(k .. '=' .. tostring(v)) end
local actor = 0
if participant_id == 0 then
  local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
  actor = tonumber(player and player.actor_address or 0) or 0
else
  local participant = sd.bots and sd.bots.get_participant_state and sd.bots.get_participant_state(participant_id) or nil
  actor = tonumber(participant and participant.actor_address or 0) or 0
end
emit("actor", string.format("0x%08X", actor))
if actor == 0 then
  emit("available", false)
  return
end
local ok, chain_count = pcall(sd.debug.read_i32, actor + chain_count_offset)
emit("available", ok)
emit("chain_count", ok and chain_count or "")
"""

AIR_CHAIN_NATIVE_SURFACE_LUA = r"""
local target_ids = __TARGET_IDS__
local function emit(k, v) print(k .. '=' .. tostring(v)) end
local function hx(v) return string.format("0x%08X", tonumber(v) or 0) end
local function offset(key) return sd.debug.layout_offset(key) end
local function read_ptr(address) return address ~= 0 and (sd.debug.read_ptr(address) or 0) or 0 end
local function read_u8(address) return address ~= 0 and (sd.debug.read_u8(address) or 0) or 0 end
local function read_u16(address) return address ~= 0 and (sd.debug.read_u16(address) or 0) or 0 end
local function read_u32(address) return address ~= 0 and (sd.debug.read_u32(address) or 0) or 0 end
local function read_i32(address) return address ~= 0 and (sd.debug.read_i32(address) or 0) or 0 end
local function read_float(address) return address ~= 0 and (sd.debug.read_float(address) or 0) or 0 end

local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
local player_actor = tonumber(player and player.actor_address or 0) or 0
local owner_offset = offset("actor_owner")
local player_world = player_actor ~= 0 and owner_offset ~= nil and read_ptr(player_actor + owner_offset) or 0

emit("ok", player_actor ~= 0 and player_world ~= 0)
emit("player.actor", hx(player_actor))
emit("player.world", hx(player_world))
emit("world.transient_count", player_world ~= 0 and read_i32(player_world + 0x8B78) or 0)
emit("world.transient_items", hx(player_world ~= 0 and read_ptr(player_world + 0x8B84) or 0))

local position_x_offset = offset("actor_position_x")
local position_y_offset = offset("actor_position_y")
local grid_cell_offset = offset("actor_grid_cell_ptr")
local slot_offset = offset("actor_slot")
local world_slot_offset = offset("actor_world_slot")
local spatial_handle_offset = offset("actor_spatial_handle")
for index, network_actor_id in ipairs(target_ids) do
  local prefix = "target." .. tostring(index) .. "."
  local snapshot = sd.world.get_run_enemy_by_network_id and sd.world.get_run_enemy_by_network_id(network_actor_id) or nil
  local actor = tonumber(snapshot and snapshot.actor_address or 0) or 0
  emit(prefix .. "network_actor_id", string.format("%.0f", network_actor_id))
  emit(prefix .. "actor", hx(actor))
  emit(prefix .. "vtable", hx(actor ~= 0 and read_ptr(actor) or 0))
  emit(prefix .. "header_word", actor ~= 0 and read_u32(actor + 0x04) or 0)
  emit(prefix .. "type_id", actor ~= 0 and read_u32(actor + 0x08) or 0)
  emit(prefix .. "native_flags_14", actor ~= 0 and read_u32(actor + 0x14) or 0)
  emit(prefix .. "x", actor ~= 0 and position_x_offset ~= nil and read_float(actor + position_x_offset) or 0)
  emit(prefix .. "y", actor ~= 0 and position_y_offset ~= nil and read_float(actor + position_y_offset) or 0)
  emit(prefix .. "grid_cell", hx(actor ~= 0 and grid_cell_offset ~= nil and read_ptr(actor + grid_cell_offset) or 0))
  emit(prefix .. "owner", hx(actor ~= 0 and owner_offset ~= nil and read_ptr(actor + owner_offset) or 0))
  emit(prefix .. "slot", actor ~= 0 and slot_offset ~= nil and read_u8(actor + slot_offset) or 0)
  emit(prefix .. "world_slot", actor ~= 0 and world_slot_offset ~= nil and read_u16(actor + world_slot_offset) or 0)
  emit(prefix .. "spatial_handle", actor ~= 0 and spatial_handle_offset ~= nil and read_u16(actor + spatial_handle_offset) or 0)
end
emit("target_count", #target_ids)
"""

NATIVE_PRIMARY_OUTPUTS_LUA = r"""
local participant_id = tonumber("__PARTICIPANT_ID__") or 0
local function emit(k, v) print(k .. '=' .. tostring(v)) end
local progression = 0
if participant_id == 0 then
  local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
  local actor = tonumber(player and player.actor_address or 0) or 0
  local offset = sd.debug.layout_offset("actor_progression_runtime_state")
  progression = actor ~= 0 and offset ~= nil and (tonumber(sd.debug.read_ptr(actor + offset)) or 0) or 0
else
  local participant = sd.bots and sd.bots.get_participant_state and sd.bots.get_participant_state(participant_id) or nil
  progression = tonumber(participant and participant.progression_runtime_state_address or 0) or 0
end
emit("progression", string.format("0x%08X", progression))
local stats = progression ~= 0 and sd.debug.resolve_native_primary_spell_stats(progression, 0x18, 0x18) or nil
emit("resolved", stats and stats.resolved or false)
if stats == nil then return end
for _, key in ipairs({"build_skill_id", "resolved_build_skill_id", "current_spell_id", "progression_level", "output_count", "damage", "secondary_damage", "mana_cost", "mana_spend_cost", "error"}) do
  emit(key, stats[key])
end
if stats.outputs ~= nil then
  for index, value in ipairs(stats.outputs) do
    emit("output." .. tostring(index), value)
  end
end
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


def pin_cluster_batch(
    pipe_name: str,
    cluster: dict[str, Any],
    *,
    hp: float | None,
    rebind: bool,
) -> dict[str, str]:
    selected_ids = {int(target["network_id"]) for target in cluster["targets"]}
    targets = list(cluster["targets"]) + list(cluster.get("parked_targets", []))
    rows = "{" + ",".join(
        "{id=%d,x=%.6f,y=%.6f,selected=%s}"
        % (
            int(target["network_id"]),
            float(target["x"]),
            float(target["y"]),
            "true" if int(target["network_id"]) in selected_ids else "false",
        )
        for target in targets
    ) + "}"
    return values(
        pipe_name,
        PIN_CLUSTER_BATCH_LUA
        .replace("__ROWS__", rows)
        .replace("__HP__", f"{(hp if hp is not None else 0.0):.3f}")
        .replace("__WRITE_HP__", "true" if hp is not None else "false")
        .replace("__REBIND__", "true" if rebind else "false"),
    )


def query_enemy_state(network_actor_id: int) -> dict[str, str]:
    return host_enemy_by_id(str(network_actor_id))


def _parse_air_chain_target(raw: dict[str, str], prefix: str) -> dict[str, Any]:
    return {
        "ordinal": parse_int_text(raw.get(f"{prefix}.ordinal"), -1),
        "network_actor_id": parse_int_text(raw.get(f"{prefix}.network_actor_id"), 0),
        "local_actor_address": parse_int_text(raw.get(f"{prefix}.local_actor_address"), 0),
        "fallback_actor_address": parse_int_text(raw.get(f"{prefix}.fallback_actor_address"), 0),
        "matched": raw.get(f"{prefix}.matched") == "true",
        "authoritative_null": raw.get(f"{prefix}.authoritative_null") == "true",
        "source_override_attempted": raw.get(f"{prefix}.source_override_attempted") == "true",
        "source_override_applied": raw.get(f"{prefix}.source_override_applied") == "true",
        "target_override_attempted": raw.get(f"{prefix}.target_override_attempted") == "true",
        "target_override_applied": raw.get(f"{prefix}.target_override_applied") == "true",
        **{
            key: parse_float(raw.get(f"{prefix}.{key}"))
            for key in (
                "source_x", "source_y", "target_x", "target_y",
                "local_source_x", "local_source_y", "local_target_x", "local_target_y",
                "source_error", "source_error_before_override",
                "target_error", "target_error_before_override",
            )
        },
    }


def _parse_air_chain_snapshot(raw: dict[str, str], prefix: str) -> dict[str, Any]:
    target_count = parse_int_text(raw.get(f"{prefix}.target_count"), 0)
    return {
        "valid": raw.get(f"{prefix}.valid") == "true",
        "active": raw.get(f"{prefix}.active") == "true",
        "terminal": raw.get(f"{prefix}.terminal") == "true",
        "truncated": raw.get(f"{prefix}.truncated") == "true",
        "owner_participant_id": parse_int_text(raw.get(f"{prefix}.owner_participant_id"), 0),
        "received_ms": parse_int_text(raw.get(f"{prefix}.received_ms"), 0),
        "sequence": parse_int_text(raw.get(f"{prefix}.sequence"), 0),
        "run_nonce": parse_int_text(raw.get(f"{prefix}.run_nonce"), 0),
        "cast_sequence": parse_int_text(raw.get(f"{prefix}.cast_sequence"), 0),
        "frame_sequence": parse_int_text(raw.get(f"{prefix}.frame_sequence"), 0),
        "target_count": target_count,
        "target_total_count": parse_int_text(raw.get(f"{prefix}.target_total_count"), 0),
        "targets": [
            _parse_air_chain_target(raw, f"{prefix}.target.{index}")
            for index in range(1, target_count + 1)
        ],
    }


def query_air_chain_audit(pipe_name: str, owner_participant_id: int) -> dict[str, Any]:
    raw = values(
        pipe_name,
        AIR_CHAIN_AUDIT_LUA.replace("__OWNER_ID__", str(owner_participant_id)),
    )
    local_count = parse_int_text(raw.get("local_history.count"), 0)
    snapshot_count = parse_int_text(raw.get("snapshot_history.count"), 0)
    binding_count = parse_int_text(raw.get("apply.binding_count"), 0)
    apply: dict[str, Any] = {
        "valid": raw.get("apply.valid") == "true",
        "applied_ms": parse_int_text(raw.get("apply.applied_ms"), 0),
        "owner_participant_id": parse_int_text(raw.get("apply.owner_participant_id"), 0),
        "cast_sequence": parse_int_text(raw.get("apply.cast_sequence"), 0),
        "frame_sequence": parse_int_text(raw.get("apply.frame_sequence"), 0),
        "bindings": [
            _parse_air_chain_target(raw, f"apply.binding.{index}")
            for index in range(1, binding_count + 1)
        ],
    }
    for key in (
        "cumulative_override_attempt_count",
        "cumulative_override_success_count",
        "cumulative_authoritative_null_count",
        "cumulative_missing_snapshot_fallback_count",
        "cumulative_stale_snapshot_fallback_count",
        "cumulative_unmapped_target_count",
        "cumulative_source_override_success_count",
        "cumulative_source_override_failure_count",
        "cumulative_target_override_success_count",
        "cumulative_target_override_failure_count",
        "max_applied_target_count",
    ):
        apply[key] = parse_int_text(raw.get(f"apply.{key}"), 0)
    return {
        "available": raw.get("available") == "true",
        "local_capture": _parse_air_chain_snapshot(raw, "local_capture"),
        "local_history": [
            _parse_air_chain_snapshot(raw, f"local_history.{index}")
            for index in range(1, local_count + 1)
        ],
        "snapshot_history": [
            _parse_air_chain_snapshot(raw, f"snapshot_history.{index}")
            for index in range(1, snapshot_count + 1)
        ],
        "apply": apply,
    }


def query_native_primary_outputs(
    pipe_name: str,
    *,
    participant_id: int = 0,
) -> dict[str, str]:
    return values(
        pipe_name,
        NATIVE_PRIMARY_OUTPUTS_LUA.replace("__PARTICIPANT_ID__", str(participant_id)),
    )


def query_air_chain_state(
    pipe_name: str,
    *,
    participant_id: int = 0,
) -> dict[str, str]:
    return values(
        pipe_name,
        AIR_CHAIN_STATE_LUA
        .replace("__PARTICIPANT_ID__", str(participant_id))
        .replace("__CHAIN_COUNT_OFFSET__", str(AIR_LIGHTNING_CHAIN_COUNT_OFFSET)),
    )


def query_air_chain_native_surface(
    pipe_name: str,
    cluster: dict[str, Any],
) -> dict[str, str]:
    target_ids = "{" + ",".join(
        str(int(target["network_id"]))
        for target in cluster["targets"]
    ) + "}"
    return values(
        pipe_name,
        AIR_CHAIN_NATIVE_SURFACE_LUA.replace("__TARGET_IDS__", target_ids),
    )


def air_chain_native_surface_ready(
    surface: dict[str, str],
    target_count: int,
) -> bool:
    if surface.get("ok") != "true":
        return False
    player_world = parse_int_text(surface.get("player.world"), 0)
    if player_world == 0:
        return False
    for index in range(1, target_count + 1):
        prefix = f"target.{index}."
        if (
            parse_int_text(surface.get(f"{prefix}actor"), 0) == 0
            or parse_int_text(surface.get(f"{prefix}type_id"), 0) == 0
            or parse_int_text(surface.get(f"{prefix}native_flags_14"), 0) & 0x2 == 0
            or parse_int_text(surface.get(f"{prefix}grid_cell"), 0) == 0
            or parse_int_text(surface.get(f"{prefix}owner"), 0) != player_world
        ):
            return False
    return True


def wait_for_air_chain_native_surfaces(
    direction: Direction,
    cluster: dict[str, Any],
    timeout: float = 3.0,
) -> dict[str, Any]:
    target_count = len(cluster["targets"])
    deadline = time.monotonic() + timeout
    attempts = 0
    last: dict[str, dict[str, str]] = {}
    while time.monotonic() < deadline:
        attempts += 1
        last = {
            "owner": query_air_chain_native_surface(direction.source_pipe, cluster),
            "observer": query_air_chain_native_surface(direction.receiver_pipe, cluster),
        }
        if all(
            air_chain_native_surface_ready(surface, target_count)
            for surface in last.values()
        ):
            return {"attempts": attempts, **last}
        time.sleep(0.1)
    raise VerifyFailure(
        "Lightning targets did not enter both peers' native mask=2 spatial surfaces: "
        f"attempts={attempts} last={last}"
    )


def refresh_primary_target_exact(pipe_name: str, network_actor_id: int) -> dict[str, str]:
    result = values(
        pipe_name,
        REFRESH_PRIMARY_TARGET_ONLY_LUA.replace("__TARGET_ID__", str(network_actor_id)),
    )
    required = (
        "write.player_x",
        "write.player_y",
        "write.heading",
        "write.current_target",
        "write.aim_x",
        "write.aim_y",
    )
    if result.get("ok") != "true" or any(result.get(key) != "true" for key in required):
        raise VerifyFailure(
            f"exact Lightning target refresh failed on {pipe_name}: "
            f"network_actor_id={network_actor_id} result={result}"
        )
    return result


def list_other_targets(pipe_name: str, primary_network_id: int) -> dict[str, str]:
    rows = values(pipe_name, LIST_OTHER_TARGETS_LUA.replace("__PRIMARY__", str(primary_network_id)))
    if rows.get("ok") != "true":
        raise VerifyFailure(f"natural Lightning other-target listing failed: {rows}")
    return rows


def wait_for_natural_enemy_population(
    minimum: int,
    timeout: float = 15.0,
) -> dict[str, dict[str, str]]:
    deadline = time.monotonic() + timeout
    last: dict[str, dict[str, str]] = {}
    while time.monotonic() < deadline:
        last = {
            "host": values(HOST_PIPE, NATURAL_ENEMY_POPULATION_LUA),
            "client": values(CLIENT_PIPE, NATURAL_ENEMY_POPULATION_LUA),
        }
        if all(
            view.get("ok") == "true"
            and parse_int_text(view.get("count"), 0) >= minimum
            for view in last.values()
        ):
            return last
        time.sleep(0.15)
    raise VerifyFailure(
        f"stock wave did not expose {minimum} native Lightning targets on both peers: "
        f"last={last}"
    )


def enable_scripted_input_control_with_live_waves() -> dict[str, Any]:
    host = set_manual_spawner_test_mode(HOST_PIPE, True)
    client = set_manual_spawner_test_mode(CLIENT_PIPE, True)
    if host.get("ok") != "true" or client.get("ok") != "true":
        raise VerifyFailure(
            "failed to enable scripted primary control over existing stock enemies: "
            f"host={host} client={client}"
        )
    return {"host": host, "client": client}


def enable_flat_manual_cluster_combat() -> dict[str, Any]:
    try:
        return {
            "mode": "prelude_manual_spawner",
            "setup": enable_manual_stock_spawner_combat(),
        }
    except VerifyFailure as exc:
        # A flat boneyard can advance into its first stock wave while the pair
        # finishes participant convergence. The tracked native spawner is
        # already usable in that state; enable its test gate and remove those
        # stock enemies before creating the deterministic cluster.
        if "waves are already active" not in str(exc).lower():
            raise
        return {
            "mode": "existing_wave_manual_spawner",
            "prelude_error": str(exc),
            "scripted_control": enable_scripted_input_control_with_live_waves(),
            "cleanup": cleanup_live_enemies(),
        }


def park_remote_observer(direction: Direction, cluster: dict[str, Any]) -> dict[str, str]:
    return values(
        direction.receiver_pipe,
        PARK_LOCAL_OBSERVER_LUA
        .replace("__X__", f"{float(cluster['primary_x']) - 1200.0:.3f}")
        .replace("__Y__", f"{float(cluster['primary_y']) + 1200.0:.3f}"),
    )


def setup_healthy_target(pipe_name: str) -> dict[str, str]:
    result = values(
        pipe_name,
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
        raise VerifyFailure(f"healthy target setup failed on {pipe_name}: {result}")
    return result


def build_natural_cluster(
    direction: Direction,
    secondary_offsets: tuple[tuple[float, float], ...],
) -> dict[str, Any]:
    setup: dict[str, str] | None = None
    for _ in range(6):
        try:
            setup = setup_healthy_target(direction.source_pipe)
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

    rows = list_other_targets(direction.source_pipe, primary_network_id)
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

    parked_targets: list[dict[str, Any]] = []
    for row_index in range(len(secondary_offsets) + 1, count + 1):
        network_id = parse_int_text(rows.get(f"row.{row_index}.id"), 0)
        if network_id == 0:
            continue
        parked_targets.append(
            {
                "label": f"parked_{row_index}",
                "network_id": network_id,
                "x": primary_x + 2400.0 + row_index * 37.0,
                "y": primary_y + 2400.0 + row_index * 29.0,
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
        "parked_targets": parked_targets,
        "primary_network_id": primary_network_id,
        "primary_actor_address": primary_actor_address,
        "primary_x": primary_x,
        "primary_y": primary_y,
    }


def wait_for_client_manual_target(
    x: float,
    y: float,
    network_id: int,
    timeout: float = 8.0,
) -> dict[str, str]:
    return find_target(
        CLIENT_PIPE,
        x,
        y,
        network_id=network_id,
        timeout=timeout,
        require_local_binding=True,
    )


def build_manual_cluster(
    direction: Direction,
    secondary_offsets: tuple[tuple[float, float], ...],
) -> dict[str, Any]:
    lane = place_pair_on_clear_lane(direction, CLIENT_TARGET)
    primary_x = float(lane["x"])
    primary_y = float(lane["y"])
    target_positions = ((0.0, 0.0),) + secondary_offsets

    targets: list[dict[str, Any]] = []
    spawns: list[dict[str, Any]] = []
    for index, (offset_x, offset_y) in enumerate(target_positions):
        x = primary_x + offset_x
        y = primary_y + offset_y
        spawn: dict[str, Any] | None = None
        spawn_errors: list[str] = []
        for spawn_attempt in range(1, 6):
            try:
                spawn = spawn_one_enemy(x, y, TARGET_HP)
                spawn["attempt"] = spawn_attempt
                spawn["prior_errors"] = spawn_errors
                break
            except VerifyFailure as exc:
                spawn_errors.append(str(exc))
                time.sleep(0.75)
        if spawn is None:
            raise VerifyFailure(
                f"manual Lightning target {index} exhausted stock-spawner retries: "
                f"x={x} y={y} errors={spawn_errors}"
            )
        network_id = parse_int_text(spawn["result"].get("network_actor_id"), 0)
        if network_id == 0:
            raise VerifyFailure(
                f"manual Lightning target {index} did not expose a replicated id: {spawn}"
            )
        client_target = wait_for_client_manual_target(x, y, network_id)
        source_target = (
            client_target
            if direction.source_pipe == CLIENT_PIPE
            else {
                "local.found": "true",
                "local.actor_address": str(int(spawn["actor_address"])),
                "network_id": str(network_id),
            }
        )
        targets.append(
            {
                "label": "primary" if index == 0 else f"secondary_{index}",
                "network_id": network_id,
                "x": x,
                "y": y,
                "client": client_target,
                "source": source_target,
            }
        )
        spawns.append(spawn)

    return {
        "lane": lane,
        "spawns": spawns,
        "secondary_offsets": [
            {"x": offset_x, "y": offset_y}
            for offset_x, offset_y in secondary_offsets
        ],
        "targets": targets,
        "primary_network_id": targets[0]["network_id"],
        "primary_actor_address": parse_int_text(
            targets[0]["source"].get("local.actor_address"),
            0,
        ),
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
    last_targets: dict[str, Any] = {}
    deadline = time.monotonic() + max(duration, 0.0)
    cycle_index = 0
    while True:
        hp_value = TARGET_HP if write_hp else None
        cycle: dict[str, Any] = {}
        if include_host:
            cycle["host"] = pin_cluster_batch(
                HOST_PIPE,
                cluster,
                hp=hp_value,
                rebind=cycle_index == 0,
            )
        if include_client:
            cycle["client"] = pin_cluster_batch(
                CLIENT_PIPE,
                cluster,
                hp=hp_value,
                rebind=cycle_index == 0,
            )
        last_targets = cycle
        cycle_index += 1
        remaining = deadline - time.monotonic()
        if remaining <= 0.0:
            break
        time.sleep(min(max(interval, 0.01), remaining))
    return {"cycles": cycle_index, "targets": last_targets}


def observe_cluster_damage(
    direction: Direction,
    cluster: dict[str, Any],
    before_hp_by_id: dict[int, float],
    *,
    duration: float = 2.5,
    interval: float = 0.1,
    pin_transforms: bool = False,
    pin_observer_pipes: tuple[str, ...] = (),
) -> dict[str, Any]:
    deadline = time.monotonic() + duration
    min_hp_by_id = dict(before_hp_by_id)
    removed_by_id = {network_id: False for network_id in before_hp_by_id}
    last_by_id: dict[int, dict[str, str]] = {}
    primary_network_id = int(cluster["primary_network_id"])
    primary_target = next(
        target
        for target in cluster["targets"]
        if int(target["network_id"]) == primary_network_id
    )
    client_primary_min_local_hp = before_hp_by_id[primary_network_id]
    client_primary_min_snapshot_hp = before_hp_by_id[primary_network_id]
    client_primary_last: dict[str, str] = {}
    target_refresh_attempts = 0
    target_refresh_last: dict[str, str] = {}
    last_pin_cycle: dict[str, Any] = {}
    while time.monotonic() < deadline:
        if pin_transforms:
            last_pin_cycle = {
                "host": pin_cluster_batch(HOST_PIPE, cluster, hp=None, rebind=False),
            }
            for pipe_name in dict.fromkeys(pin_observer_pipes):
                if pipe_name == HOST_PIPE:
                    continue
                # Position-only fixture stabilization: never write observer HP
                # and never rebind its already-verified network actor pointer.
                last_pin_cycle[pipe_name] = pin_cluster_batch(
                    pipe_name,
                    cluster,
                    hp=None,
                    rebind=False,
                )
        target_refresh_last = values(
            direction.source_pipe,
            REFRESH_PRIMARY_TARGET_ONLY_LUA.replace(
                "__TARGET_ID__",
                str(primary_network_id),
            ),
        )
        target_refresh_attempts += 1
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
        try:
            client_primary_last = find_target(
                direction.source_pipe,
                float(primary_target["x"]),
                float(primary_target["y"]),
                network_id=primary_network_id,
                timeout=0.5,
                require_local_binding=True,
            )
            client_primary_min_local_hp = min(
                client_primary_min_local_hp,
                parse_float(
                    client_primary_last.get("local.hp"),
                    before_hp_by_id[primary_network_id],
                ),
            )
            client_primary_min_snapshot_hp = min(
                client_primary_min_snapshot_hp,
                parse_float(
                    client_primary_last.get("snapshot.hp"),
                    before_hp_by_id[primary_network_id],
                ),
            )
        except VerifyFailure:
            pass
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
        "client_primary": {
            "min_local_hp": client_primary_min_local_hp,
            "min_snapshot_hp": client_primary_min_snapshot_hp,
            "last": client_primary_last,
        },
        "target_refresh": {
            "attempt_count": target_refresh_attempts,
            "last": target_refresh_last,
        },
        "last_pin_cycle": last_pin_cycle,
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


def cast_lightning_cluster(
    direction: Direction,
    cluster: dict[str, Any],
    label: str,
    *,
    scripted_manual_control: bool,
    additional_geometry_pipes: tuple[str, ...] = (),
) -> dict[str, Any]:
    quiesce = quiesce_gameplay_primary_input(f"{label}.before")
    observer_park = park_remote_observer(direction, cluster)
    set_local_player_vitals(HOST_PIPE, 5000.0, 5000.0)
    set_local_player_vitals(CLIENT_PIPE, 5000.0, 5000.0)
    native_outputs_before_cast = {
        "owner": query_native_primary_outputs(direction.source_pipe),
        "observer": query_native_primary_outputs(
            direction.receiver_pipe,
            participant_id=direction.source_id,
        ),
    }
    native_chain_state_before_cast = {
        "owner": query_air_chain_state(direction.source_pipe),
        "observer": query_air_chain_state(
            direction.receiver_pipe,
            participant_id=direction.source_id,
        ),
    }

    manual_cluster = "spawns" in cluster
    # Only the host owns enemy transforms and health. Mutating/rebinding a
    # client's replicated clone races world-snapshot reconciliation and can
    # leave a native spell holding an obsolete actor pointer.
    stabilize_cluster(
        cluster,
        duration=0.35,
        write_hp=manual_cluster,
        include_client=False,
    )
    native_selection_surface_before_cast = wait_for_air_chain_native_surfaces(
        direction,
        cluster,
    )
    before_hp_by_id = {
        int(target["network_id"]): parse_float(
            query_enemy_state(int(target["network_id"])).get("hp"),
            TARGET_HP,
        )
        for target in cluster["targets"]
    }

    air_chain_audit_before = {
        "owner": query_air_chain_audit(direction.source_pipe, direction.source_id),
        "observer": query_air_chain_audit(direction.receiver_pipe, direction.source_id),
    }
    source_offset = len(read_log(direction.source_log))
    receiver_offset = len(read_log(direction.receiver_log))
    if scripted_manual_control:
        cast_runtime = wait_for_cast_runtime_ready(direction)
        cast_start = {
            "prepare": prepare_and_queue_caster(
                direction,
                cluster["primary_actor_address"],
                cluster["primary_x"],
                cluster["primary_y"],
                LIGHTNING_CAST_FRAMES,
            ),
        }
    else:
        cast_runtime = {
            "ready_gate_skipped": True,
            "reason": "Air keeps native selection/latch fields populated while target-ready",
        }
        cast_start = {
            "aim_refresh": refresh_primary_target_exact(
                direction.source_pipe,
                int(cluster["primary_network_id"]),
            ),
            "queue_result": queue_gameplay_mouse_left(
                direction,
                LIGHTNING_CAST_FRAMES,
            ),
        }
    time.sleep(0.2)
    air_chain_audit_during = {
        "owner": query_air_chain_audit(direction.source_pipe, direction.source_id),
        "observer": query_air_chain_audit(direction.receiver_pipe, direction.source_id),
    }
    native_chain_state_during_cast = {
        "owner": query_air_chain_state(direction.source_pipe),
        "observer": query_air_chain_state(
            direction.receiver_pipe,
            participant_id=direction.source_id,
        ),
    }
    damage = observe_cluster_damage(
        direction,
        cluster,
        before_hp_by_id,
        duration=2.5,
        # Keep the host-owned targets at the geometry whose authoritative arc
        # endpoints are being compared. With a second observer, ordinary enemy
        # locomotion plus one snapshot of relay latency can otherwise make both
        # observers equally stale even though they received and applied the
        # exact same endpoint packet. Position writes remain host-only and do
        # not alter native targeting, damage, or observer bindings.
        pin_transforms=True,
        pin_observer_pipes=tuple(
            dict.fromkeys(
                (
                    direction.source_pipe,
                    direction.receiver_pipe,
                    *additional_geometry_pipes,
                )
            )
        ),
    )
    air_chain_audit_after = {
        "owner": query_air_chain_audit(direction.source_pipe, direction.source_id),
        "observer": query_air_chain_audit(direction.receiver_pipe, direction.source_id),
    }
    native_chain_state_after_cast = {
        "owner": query_air_chain_state(direction.source_pipe),
        "observer": query_air_chain_state(
            direction.receiver_pipe,
            participant_id=direction.source_id,
        ),
    }
    source_log, phase_counts, native_hook_count = wait_for_source_cast(
        direction,
        source_offset,
        {"pressed": 1, "released": 1},
        timeout=8.0,
    )
    time.sleep(0.2)
    air_chain_audit_terminal = {
        "owner": query_air_chain_audit(direction.source_pipe, direction.source_id),
        "observer": query_air_chain_audit(direction.receiver_pipe, direction.source_id),
    }
    receiver_log = read_log(direction.receiver_log)[receiver_offset:]
    receiver_cast_queued = (
        f"Multiplayer remote cast queued. participant_id={direction.source_id}" in receiver_log
    )
    receiver_cast_prepped = (
        f"[bots] wizard cast prepped. bot_id={direction.source_id}" in receiver_log
    )
    return {
        "quiesce": quiesce,
        "cast_runtime": cast_runtime,
        "cast_start": cast_start,
        "native_selection_surface_before_cast": native_selection_surface_before_cast,
        "native_outputs_before_cast": native_outputs_before_cast,
        "native_chain_state": {
            "before": native_chain_state_before_cast,
            "during": native_chain_state_during_cast,
            "after": native_chain_state_after_cast,
        },
        "air_chain_sync": {
            "before": air_chain_audit_before,
            "during": air_chain_audit_during,
            "after": air_chain_audit_after,
            "terminal": air_chain_audit_terminal,
        },
        "replicated_cast_delivery": {
            "owner_native_hook_count": native_hook_count,
            "observer_remote_cast_queued": receiver_cast_queued,
            "observer_native_cast_prepped": receiver_cast_prepped,
            "ok": native_hook_count > 0 and receiver_cast_queued and receiver_cast_prepped,
        },
        "observer_park": observer_park,
        "phase_counts": phase_counts,
        "native_hook_count": native_hook_count,
        "source_log_tail": source_log[-4000:],
        "receiver_log_tail": receiver_log[-4000:],
        "damage": damage,
        "primary_accepted": damage["target_damaged"],
        "accepted_target_count": damage["victim_count"],
    }


def run_pattern_search(
    direction: Direction,
    *,
    phase: str,
    pattern_limit: int | None = None,
    primary_only: bool = False,
    natural_cluster: bool = False,
    scripted_manual_control: bool = False,
) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    skipped_patterns: list[dict[str, Any]] = []
    patterns = ((),) if primary_only else CLUSTER_PATTERNS
    if pattern_limit is not None:
        patterns = patterns[:max(pattern_limit, 1)]
    for offsets in patterns:
        retry_errors: list[str] = []
        cast: dict[str, Any] | None = None
        cluster: dict[str, Any] | None = None
        for cast_attempt in range(1, 3):
            if natural_cluster:
                cluster = build_natural_cluster(direction, offsets)
            else:
                cleanup_live_enemies()
                cluster = build_manual_cluster(direction, offsets)
            try:
                cast = cast_lightning_cluster(
                    direction,
                    cluster,
                    f"lightning_chain.{phase}.offsets_"
                    f"{'_'.join(f'{int(dx)}_{int(dy)}' for dx, dy in offsets)}",
                    scripted_manual_control=scripted_manual_control,
                )
                break
            except VerifyFailure as exc:
                error = str(exc)
                retry_errors.append(error)
                startup_only_miss = (
                    "source cast did not reach native hook/phases" in error
                    and "native_hooks=0 phases={}" in error
                )
                if not startup_only_miss:
                    raise VerifyFailure(
                        f"Lightning {phase} pattern offsets={offsets} "
                        f"failed on cast attempt {cast_attempt}: {error}"
                    ) from exc
                if cast_attempt >= 2:
                    skipped_patterns.append(
                        {
                            "offsets": offsets,
                            "reason": "native_cast_not_started",
                            "cast_retry_errors": retry_errors,
                        }
                    )
                    break
                quiesce_gameplay_primary_input(
                    f"lightning_chain.{phase}.retry_{cast_attempt}"
                )
                time.sleep(0.75)
        if cast is None or cluster is None:
            continue
        attempt = {
            "offsets": offsets,
            "cluster": cluster,
            "cast": cast,
            "cast_retry_errors": retry_errors,
        }
        attempts.append(attempt)
    if not attempts:
        raise VerifyFailure(
            f"Lightning {phase} did not start a native cast for any geometry pattern: "
            f"{skipped_patterns}"
        )
    return {"attempts": attempts, "skipped_patterns": skipped_patterns}


def build_air_chain_sync_evidence(attempt: dict[str, Any]) -> dict[str, Any]:
    sync = attempt["cast"].get("air_chain_sync", {})
    before_observer = sync.get("before", {}).get("observer", {})
    terminal_owner = sync.get("terminal", {}).get("owner", {})
    terminal_observer = sync.get("terminal", {}).get("observer", {})
    owner_history = terminal_owner.get("local_history", [])
    observer_history = terminal_observer.get("snapshot_history", [])

    owner_terminal_casts = {
        int(snapshot["cast_sequence"])
        for snapshot in owner_history
        if snapshot.get("valid") and snapshot.get("terminal")
    }
    observer_terminal_casts = {
        int(snapshot["cast_sequence"])
        for snapshot in observer_history
        if snapshot.get("valid") and snapshot.get("terminal")
    }
    common_terminal_casts = owner_terminal_casts & observer_terminal_casts
    cast_sequence = max(common_terminal_casts, default=0)
    if cast_sequence == 0:
        cast_sequence = int(
            terminal_observer.get("apply", {}).get("cast_sequence", 0)
        )

    owner_active = {
        int(snapshot["frame_sequence"]): snapshot
        for snapshot in owner_history
        if snapshot.get("valid")
        and snapshot.get("active")
        and int(snapshot.get("cast_sequence", 0)) == cast_sequence
    }
    observer_active = {
        int(snapshot["frame_sequence"]): snapshot
        for snapshot in observer_history
        if snapshot.get("valid")
        and snapshot.get("active")
        and int(snapshot.get("cast_sequence", 0)) == cast_sequence
    }

    matching_frames: list[dict[str, Any]] = []
    for frame_sequence in sorted(owner_active.keys() & observer_active.keys()):
        owner_frame = owner_active[frame_sequence]
        observer_frame = observer_active[frame_sequence]
        owner_targets = owner_frame.get("targets", [])
        observer_targets = observer_frame.get("targets", [])
        same_targets = (
            owner_frame.get("target_total_count") == observer_frame.get("target_total_count")
            and owner_frame.get("truncated") == observer_frame.get("truncated")
            and len(owner_targets) == len(observer_targets)
            and all(
                int(left.get("network_actor_id", 0)) == int(right.get("network_actor_id", 0))
                and abs(float(left.get("source_x", 0.0)) - float(right.get("source_x", 0.0))) <= 0.001
                and abs(float(left.get("source_y", 0.0)) - float(right.get("source_y", 0.0))) <= 0.001
                and abs(float(left.get("target_x", 0.0)) - float(right.get("target_x", 0.0))) <= 0.001
                and abs(float(left.get("target_y", 0.0)) - float(right.get("target_y", 0.0))) <= 0.001
                for left, right in zip(owner_targets, observer_targets)
            )
        )
        if same_targets:
            matching_frames.append(
                {
                    "frame_sequence": frame_sequence,
                    "target_total_count": owner_frame.get("target_total_count", 0),
                    "network_actor_ids": [
                        int(target.get("network_actor_id", 0))
                        for target in owner_targets
                    ],
                }
            )

    apply = terminal_observer.get("apply", {})
    apply_frame_sequence = int(apply.get("frame_sequence", 0))
    applied_owner_frame = owner_active.get(apply_frame_sequence)
    applied_observer_frame = observer_active.get(apply_frame_sequence)
    bindings = apply.get("bindings", [])
    authoritative_targets = (
        applied_owner_frame.get("targets", [])
        if applied_owner_frame is not None
        else []
    )
    binding_by_ordinal = {
        int(binding.get("ordinal", -1)): binding
        for binding in bindings
    }
    applied_target_parity = (
        applied_owner_frame is not None
        and applied_observer_frame is not None
        and int(apply.get("cast_sequence", 0)) == cast_sequence
        and len(authoritative_targets) > 0
        and all(
            (
                int(target.get("network_actor_id", 0)) ==
                int(binding_by_ordinal.get(index, {}).get("network_actor_id", -1))
            )
            and binding_by_ordinal.get(index, {}).get("matched") is True
            and (
                int(target.get("network_actor_id", 0)) == 0
                or int(binding_by_ordinal.get(index, {}).get("local_actor_address", 0)) != 0
            )
            for index, target in enumerate(authoritative_targets)
        )
    )
    max_source_error = max(
        (
            float(binding.get("source_error", 0.0))
            for binding in bindings
            if int(binding.get("network_actor_id", 0)) != 0
        ),
        default=0.0,
    )
    max_target_error = max(
        (
            float(binding.get("target_error", 0.0))
            for binding in bindings
            if int(binding.get("network_actor_id", 0)) != 0
        ),
        default=0.0,
    )
    max_target_error_before_override = max(
        (
            float(binding.get("target_error_before_override", 0.0))
            for binding in bindings
            if int(binding.get("network_actor_id", 0)) != 0
        ),
        default=0.0,
    )
    override_success_delta = int(apply.get("cumulative_override_success_count", 0)) - int(
        before_observer.get("apply", {}).get("cumulative_override_success_count", 0)
    )
    unmapped_delta = int(apply.get("cumulative_unmapped_target_count", 0)) - int(
        before_observer.get("apply", {}).get("cumulative_unmapped_target_count", 0)
    )
    source_override_success_delta = int(
        apply.get("cumulative_source_override_success_count", 0)
    ) - int(
        before_observer.get("apply", {}).get(
            "cumulative_source_override_success_count", 0
        )
    )
    source_override_failure_delta = int(
        apply.get("cumulative_source_override_failure_count", 0)
    ) - int(
        before_observer.get("apply", {}).get(
            "cumulative_source_override_failure_count", 0
        )
    )
    target_override_success_delta = int(
        apply.get("cumulative_target_override_success_count", 0)
    ) - int(
        before_observer.get("apply", {}).get(
            "cumulative_target_override_success_count", 0
        )
    )
    target_override_failure_delta = int(
        apply.get("cumulative_target_override_failure_count", 0)
    ) - int(
        before_observer.get("apply", {}).get(
            "cumulative_target_override_failure_count", 0
        )
    )
    applied_source_endpoint_parity = (
        len(authoritative_targets) > 0
        and all(
            int(target.get("network_actor_id", 0)) == 0
            or binding_by_ordinal.get(index, {}).get("source_override_applied") is True
            for index, target in enumerate(authoritative_targets)
        )
    )
    applied_target_endpoint_parity = (
        len(authoritative_targets) > 0
        and all(
            int(target.get("network_actor_id", 0)) == 0
            or binding_by_ordinal.get(index, {}).get("target_override_applied") is True
            for index, target in enumerate(authoritative_targets)
        )
    )
    max_owner_target_count = max(
        (int(frame.get("target_total_count", 0)) for frame in owner_active.values()),
        default=-1,
    )
    max_observer_target_count = max(
        (int(frame.get("target_total_count", 0)) for frame in observer_active.values()),
        default=-1,
    )
    return {
        "cast_sequence": cast_sequence,
        "owner_terminal_seen": cast_sequence in owner_terminal_casts,
        "observer_terminal_seen": cast_sequence in observer_terminal_casts,
        "owner_active_frame_count": len(owner_active),
        "observer_active_frame_count": len(observer_active),
        "matching_frame_count": len(matching_frames),
        "matching_frames": matching_frames,
        "max_owner_target_count": max_owner_target_count,
        "max_observer_target_count": max_observer_target_count,
        "apply_frame_sequence": apply_frame_sequence,
        "apply_binding_count": len(bindings),
        "applied_network_actor_ids": [
            int(binding.get("network_actor_id", 0))
            for binding in bindings
        ],
        "applied_target_parity": applied_target_parity,
        "override_success_delta": override_success_delta,
        "unmapped_target_delta": unmapped_delta,
        "source_override_success_delta": source_override_success_delta,
        "source_override_failure_delta": source_override_failure_delta,
        "target_override_success_delta": target_override_success_delta,
        "target_override_failure_delta": target_override_failure_delta,
        "applied_source_endpoint_parity": applied_source_endpoint_parity,
        "applied_target_endpoint_parity": applied_target_endpoint_parity,
        "max_source_error": max_source_error,
        "max_target_error": max_target_error,
        "max_target_error_before_override": max_target_error_before_override,
        "endpoint_error_ok": (
            max_source_error <= MAX_AIR_CHAIN_ENDPOINT_ERROR
            and max_target_error <= MAX_AIR_CHAIN_ENDPOINT_ERROR
        ),
    }


def dispatcher_chain_count(attempt: dict[str, Any], side: str) -> int:
    trace = attempt["cast"].get("native_chain_state", {})
    sampled_counts: list[int] = []
    for phase in ("during", "after"):
        sample = trace.get(phase, {}).get(side, {})
        if sample.get("available") == "true":
            sampled_counts.append(parse_int_text(sample.get("chain_count"), -1))
    return max(sampled_counts, default=-1)


def wait_for_client_target_upgrade(timeout: float) -> dict[str, Any]:
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


def wait_for_host_target_upgrade(timeout: float) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    for step in range(1, MAX_LEVEL_STEPS + 1):
        host_stats = query_progression_stats(HOST_PIPE)
        client_observer_stats = query_progression_stats(
            CLIENT_PIPE,
            participant_id=HOST_ID,
        )
        if not host_stats["available"] or not client_observer_stats["available"]:
            raise VerifyFailure(
                "Lightning chaining probe could not read host progression stats: "
                f"host={host_stats} client_observer={client_observer_stats}"
            )
        target_level = max(host_stats["level"], client_observer_stats["level"]) + 1
        target_experience = int(
            max(
                host_stats["next_xp_threshold"],
                client_observer_stats["next_xp_threshold"],
                125.0,
            )
            + 10.0
        )

        publish = publish_host_self_offer(target_level, target_experience)
        offer = wait_for_host_offer(target_level, timeout)
        wait_active = wait_for_wait_status(
            participant_id=HOST_ID,
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

        before_host = query_progression_entry(HOST_PIPE, option_id=selected_option_id)
        before_observer = query_progression_entry(
            CLIENT_PIPE,
            option_id=selected_option_id,
            participant_id=HOST_ID,
        )
        choice = choose_host_option(offer["offer_id"], selected_option_index)
        result = wait_for_broadcast_result(offer["offer_id"], target_level, timeout)

        client_offer_resolution: dict[str, Any] | None = None
        client_offer = capture(CLIENT_PIPE)
        if (
            client_offer.get("offer.valid") == "true"
            and parse_int_text(client_offer.get("offer.target"), 0) == CLIENT_ID
        ):
            client_offer_id = parse_int_text(client_offer.get("offer.id"), 0)
            client_offer_resolution = {
                "offer_id": client_offer_id,
                "choice": choose_client_option(client_offer_id, 1),
                "result": wait_for_choice_result(client_offer_id, target_level, timeout),
            }

        wait_cleared = wait_for_wait_status(
            participant_id=HOST_ID,
            pause_active=False,
            timeout=timeout,
        )
        after_host = query_progression_entry(HOST_PIPE, option_id=selected_option_id)
        after_observer = query_progression_entry(
            CLIENT_PIPE,
            option_id=selected_option_id,
            participant_id=HOST_ID,
        )
        step_record = {
            "step": step,
            "target_level": target_level,
            "target_experience": target_experience,
            "stats_before": {
                "host": host_stats,
                "client_observer": client_observer_stats,
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
            "client_offer_resolution": client_offer_resolution,
            "wait_cleared": {
                "host_waiting_count": parse_int_text(wait_cleared["host"].get("wait.waiting_count"), 0),
                "client_waiting_count": parse_int_text(wait_cleared["client"].get("wait.waiting_count"), 0),
            },
            "selected_entry": {
                "before_owner": before_host,
                "after_owner": after_host,
                "before_observer": before_observer,
                "after_observer": after_observer,
            },
            "matched_target_upgrade": matched_target_upgrade,
        }
        steps.append(step_record)
        if matched_target_upgrade:
            if after_host["active"] <= before_host["active"]:
                raise VerifyFailure(f"host-local chaining active count did not increase: {step_record}")
            if after_observer["active"] <= before_observer["active"]:
                raise VerifyFailure(f"client observer chaining active count did not increase: {step_record}")
            return {"step_record": step_record, "steps": steps}

    raise VerifyFailure(
        f"Host Lightning chaining upgrade was not offered within {MAX_LEVEL_STEPS} level-up steps: "
        f"{[target_step_summary(step) for step in steps]}"
    )


def launch_pair_ready(timeout: float) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(1, 4):
        stop_games()
        try:
            launch = launch_pair(
                preset=AIR_PRESET,
                god_mode=True,
                test_survival_boneyard_override=FLAT_BONEYARD,
                test_blank_boneyard=True,
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


def run_verifier(
    timeout: float,
    *,
    owner: str = "client",
    pattern_limit: int | None = None,
    baseline_only: bool = False,
    upgrade_only: bool = False,
    primary_only: bool = False,
    natural_cluster: bool = False,
    require_chain_evidence: bool = True,
) -> dict[str, Any]:
    output: dict[str, Any] = {"ok": False}
    output["native_path"] = {
        "air_primary_dispatcher": f"0x{AIR_PRIMARY_DISPATCHER_FUNCTION:08X}",
        "actor_chain_count_offset": f"0x{AIR_LIGHTNING_CHAIN_COUNT_OFFSET:X}",
        "chain_target_function": f"0x{LIGHTNING_CHAIN_TARGET_FUNCTION:08X}",
    }
    startup = launch_pair_ready(timeout)
    output["startup"] = {"attempt": startup["attempt"]}
    output["launch"] = startup["launch"]
    output["hub_ready"] = startup["hub_ready"]
    output["run_entry"] = startup["run_entry"]
    output["run_ready"] = startup["run_ready"]
    if natural_cluster:
        output["combat"] = ensure_host_combat_started()
        output["natural_enemy_population"] = wait_for_natural_enemy_population(5)
        scripted_manual_control = False
    else:
        output["manual_combat"] = enable_flat_manual_cluster_combat()
        scripted_manual_control = True

    pids = detect_instance_pids()
    if owner == "host":
        direction = Direction(
            "host_to_client_lightning_chaining",
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
            "client_to_host_lightning_chaining",
            CLIENT_ID,
            CLIENT_NAME,
            CLIENT_PIPE,
            CLIENT_LOG,
            pids["client"],
            HOST_PIPE,
            HOST_LOG,
        )
    output["pre_behavior_chaining"] = {
        "owner_local": query_progression_entry(
            direction.source_pipe,
            option_id=CHAINING_OPTION_ID,
        ),
        "remote_observer": query_progression_entry(
            direction.receiver_pipe,
            option_id=CHAINING_OPTION_ID,
            participant_id=direction.source_id,
        ),
    }
    output["pre_behavior_native_primary_outputs"] = {
        "owner": query_native_primary_outputs(direction.source_pipe),
        "remote_observer": query_native_primary_outputs(
            direction.receiver_pipe,
            participant_id=direction.source_id,
        ),
    }

    baseline_attempts: list[dict[str, Any]] = []
    if not upgrade_only:
        output["baseline_pattern_search"] = run_pattern_search(
            direction,
            phase="baseline",
            pattern_limit=pattern_limit,
            primary_only=primary_only,
            natural_cluster=natural_cluster,
            scripted_manual_control=scripted_manual_control,
        )
        baseline_attempts = output["baseline_pattern_search"]["attempts"]
        output["baseline_native_chain_evidence"] = [
            {
                "offsets": attempt["offsets"],
                "replicated_cast_delivery_ok": attempt["cast"]["replicated_cast_delivery"]["ok"],
                "owner_dispatcher_chain_count": dispatcher_chain_count(attempt, "owner"),
                "observer_dispatcher_chain_count": dispatcher_chain_count(attempt, "observer"),
                "air_chain_sync": build_air_chain_sync_evidence(attempt),
            }
            for attempt in baseline_attempts
        ]
        baseline_chain_evidence_ok = any(
            row["replicated_cast_delivery_ok"]
            and row["owner_dispatcher_chain_count"] == 0
            and row["observer_dispatcher_chain_count"] == 0
            and row["air_chain_sync"]["max_owner_target_count"] == 0
            and row["air_chain_sync"]["max_observer_target_count"] == 0
            and row["air_chain_sync"]["matching_frame_count"] > 0
            and row["air_chain_sync"]["override_success_delta"] == 0
            and row["air_chain_sync"]["owner_terminal_seen"]
            and row["air_chain_sync"]["observer_terminal_seen"]
            for row in output["baseline_native_chain_evidence"]
        )
        output["baseline_native_chain_evidence_ok"] = baseline_chain_evidence_ok
        if not baseline_chain_evidence_ok and require_chain_evidence:
            raise VerifyFailure(
                "baseline Lightning did not execute with zero native chain count on both owner and observer: "
                f"{output['baseline_native_chain_evidence']}"
            )
    if baseline_only:
        output["ok"] = True
        output["baseline_only"] = True
        return output

    if not natural_cluster:
        output["pre_upgrade_cleanup"] = cleanup_live_enemies()
    output["upgrade"] = (
        wait_for_host_target_upgrade(timeout)
        if owner == "host"
        else wait_for_client_target_upgrade(timeout)
    )
    step_record = output["upgrade"]["step_record"]
    output["post_upgrade_native_primary_outputs"] = {
        "owner": query_native_primary_outputs(direction.source_pipe),
        "remote_observer": query_native_primary_outputs(
            direction.receiver_pipe,
            participant_id=direction.source_id,
        ),
    }
    output["upgrade_result_summary"] = {
        "selected_option_id": step_record["offer"]["selected_option_id"],
        "selected_option_index": step_record["offer"]["selected_option_index"],
        "selected_skill_file": step_record["offer"]["enriched_options"][step_record["offer"]["selected_option_index"] - 1]["skill_file"],
    }

    output["upgraded_pattern_search"] = run_pattern_search(
        direction,
        phase="upgraded",
        pattern_limit=pattern_limit,
        primary_only=primary_only,
        natural_cluster=natural_cluster,
        scripted_manual_control=scripted_manual_control,
    )
    upgraded_attempts = output["upgraded_pattern_search"]["attempts"]
    output["upgraded_native_chain_evidence"] = [
        {
            "offsets": attempt["offsets"],
            "replicated_cast_delivery_ok": attempt["cast"]["replicated_cast_delivery"]["ok"],
            "owner_dispatcher_chain_count": dispatcher_chain_count(attempt, "owner"),
            "observer_dispatcher_chain_count": dispatcher_chain_count(attempt, "observer"),
            "air_chain_sync": build_air_chain_sync_evidence(attempt),
        }
        for attempt in upgraded_attempts
    ]
    upgraded_chain_evidence_ok = any(
        row["replicated_cast_delivery_ok"]
        and row["owner_dispatcher_chain_count"] > 0
        and row["observer_dispatcher_chain_count"] > 0
        and row["air_chain_sync"]["max_owner_target_count"] > 0
        and row["air_chain_sync"]["max_observer_target_count"] > 0
        and row["air_chain_sync"]["matching_frame_count"] > 0
        and row["air_chain_sync"]["applied_target_parity"]
        and row["air_chain_sync"]["override_success_delta"] > 0
        and row["air_chain_sync"]["source_override_success_delta"] > 0
        and row["air_chain_sync"]["source_override_failure_delta"] == 0
        and row["air_chain_sync"]["target_override_success_delta"] > 0
        and row["air_chain_sync"]["target_override_failure_delta"] == 0
        and row["air_chain_sync"]["applied_target_endpoint_parity"]
        and row["air_chain_sync"]["applied_source_endpoint_parity"]
        and row["air_chain_sync"]["endpoint_error_ok"]
        and row["air_chain_sync"]["owner_terminal_seen"]
        and row["air_chain_sync"]["observer_terminal_seen"]
        for row in output["upgraded_native_chain_evidence"]
    )
    output["upgraded_native_chain_evidence_ok"] = upgraded_chain_evidence_ok
    if not upgraded_chain_evidence_ok and require_chain_evidence:
        raise VerifyFailure(
            "upgraded native Lightning dispatcher did not expose a positive chain count and execute "
            "its extra-target loop on both owner and observer: "
            f"{output['upgraded_native_chain_evidence']}"
        )
    if upgrade_only:
        output["ok"] = upgraded_chain_evidence_ok
        output["upgrade_only"] = True
        if not upgraded_chain_evidence_ok:
            output["diagnostic_failure"] = (
                "upgraded native Lightning chain count/extra-target loop was absent on owner or observer"
            )
        return output

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
        baseline_owner_chain_count = dispatcher_chain_count(baseline_attempt, "owner")
        baseline_observer_chain_count = dispatcher_chain_count(baseline_attempt, "observer")
        upgraded_owner_chain_count = dispatcher_chain_count(upgraded_attempt, "owner")
        upgraded_observer_chain_count = dispatcher_chain_count(upgraded_attempt, "observer")
        baseline_air_sync = build_air_chain_sync_evidence(baseline_attempt)
        upgraded_air_sync = build_air_chain_sync_evidence(upgraded_attempt)
        baseline_delivery_ok = baseline_attempt["cast"]["replicated_cast_delivery"]["ok"]
        upgraded_delivery_ok = upgraded_attempt["cast"]["replicated_cast_delivery"]["ok"]
        if (
            baseline_delivery_ok
            and upgraded_delivery_ok
            and baseline_owner_chain_count == 0
            and baseline_observer_chain_count == 0
            and baseline_air_sync["max_owner_target_count"] == 0
            and baseline_air_sync["max_observer_target_count"] == 0
            and baseline_air_sync["matching_frame_count"] > 0
            and upgraded_owner_chain_count > 0
            and upgraded_observer_chain_count > 0
            and upgraded_air_sync["max_owner_target_count"] > 0
            and upgraded_air_sync["max_observer_target_count"] > 0
            and upgraded_air_sync["matching_frame_count"] > 0
            and upgraded_air_sync["applied_target_parity"]
            and upgraded_air_sync["source_override_success_delta"] > 0
            and upgraded_air_sync["source_override_failure_delta"] == 0
            and upgraded_air_sync["target_override_success_delta"] > 0
            and upgraded_air_sync["target_override_failure_delta"] == 0
            and upgraded_air_sync["applied_source_endpoint_parity"]
            and upgraded_air_sync["applied_target_endpoint_parity"]
            and upgraded_air_sync["endpoint_error_ok"]
            and upgraded_air_sync["owner_terminal_seen"]
            and upgraded_air_sync["observer_terminal_seen"]
        ):
            improvement = {
                "offsets": offsets,
                "baseline_victim_count": baseline_count,
                "upgraded_victim_count": upgraded_count,
                "baseline_replicated_cast_delivery_ok": baseline_delivery_ok,
                "upgraded_replicated_cast_delivery_ok": upgraded_delivery_ok,
                "baseline_owner_dispatcher_chain_count": baseline_owner_chain_count,
                "baseline_observer_dispatcher_chain_count": baseline_observer_chain_count,
                "baseline_air_chain_sync": baseline_air_sync,
                "upgraded_owner_dispatcher_chain_count": upgraded_owner_chain_count,
                "upgraded_observer_dispatcher_chain_count": upgraded_observer_chain_count,
                "upgraded_air_chain_sync": upgraded_air_sync,
                "baseline_attempt": baseline_attempt,
                "upgraded_attempt": upgraded_attempt,
            }
            break
    if improvement is None:
        raise VerifyFailure(
            "native Chaining did not transition both owner and observer from zero chain count/no "
            "extra-target loop to positive chain count/loop execution: "
            f"baseline={output['baseline_pattern_search']} upgraded={output['upgraded_pattern_search']}"
        )
    output["improvement"] = improvement

    output["ok"] = True
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--owner", choices=("host", "client"), default="client")
    parser.add_argument("--pattern-limit", type=int)
    parser.add_argument("--baseline-only", action="store_true")
    parser.add_argument("--upgrade-only", action="store_true")
    parser.add_argument("--primary-only", action="store_true")
    parser.add_argument(
        "--natural-cluster",
        action="store_true",
        help=(
            "diagnostic: reuse the finite natural-wave population instead of "
            "the deterministic flat-boneyard stock-spawner cluster"
        ),
    )
    parser.add_argument(
        "--diagnostic-allow-missing-chain-evidence",
        "--diagnostic-allow-missing-arcs",
        dest="diagnostic_allow_missing_chain_evidence",
        action="store_true",
    )
    parser.add_argument("--output", type=Path, default=RUNTIME_OUTPUT)
    args = parser.parse_args()
    if args.baseline_only and args.upgrade_only:
        parser.error("--baseline-only and --upgrade-only are mutually exclusive")

    result: dict[str, Any]
    try:
        result = run_verifier(
            timeout=args.timeout,
            owner=args.owner,
            pattern_limit=args.pattern_limit,
            baseline_only=args.baseline_only,
            upgrade_only=args.upgrade_only,
            primary_only=args.primary_only,
            natural_cluster=args.natural_cluster,
            require_chain_evidence=not args.diagnostic_allow_missing_chain_evidence,
        )
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
    return 0 if result.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
