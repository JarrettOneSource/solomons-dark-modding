#!/usr/bin/env python3
"""Verify that host/client testrun static layout generation matches."""

from __future__ import annotations

import argparse
import json
import math
import struct
import subprocess
import time
from pathlib import Path
from typing import Any

import multiplayer_frame_capture
import verify_local_multiplayer_sync as local_sync
from PIL import Image, ImageFilter
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    HOST_ID,
    HOST_NAME,
    ROOT,
    VerifyFailure,
    disable_bots,
    game_process_ids,
    launch_pair,
    lua,
    parse_key_values,
    path_for_powershell,
    select_available_windows_udp_ports,
    start_host_testrun_and_wait_for_clients,
    wait_for_remote,
)


RUNTIME_OUTPUT = ROOT / "runtime" / "run_static_layout_sync_verification.json"


STATIC_LAYOUT_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local function hx(v) return string.format("0x%08X", tonumber(v) or 0) end
local function read_ptr(address) return tonumber(sd.debug.read_ptr(address)) or 0 end
local function read_u32(address) return tonumber(sd.debug.read_u32(address)) or 0 end
local function read_i32(address) return tonumber(sd.debug.read_i32(address)) or 0 end
local function read_i16(address) return tonumber(sd.debug.read_i16(address)) or 0 end
local function read_u8(address) return tonumber(sd.debug.read_u8(address)) or 0 end
local function read_f(address) return tonumber(sd.debug.read_float(address)) or 0 end
local function off(name) return tonumber(sd.debug.layout_offset(name)) or 0 end
local function qf(v) return math.floor((tonumber(v) or 0) * 10.0 + 0.5) end
local function append(values, value)
  table.insert(values, tonumber(value) or 0)
end
local function append_u32_words(values, address, first_offset, last_offset)
  for offset = first_offset, last_offset, 4 do
    append(values, read_u32(address + offset))
  end
end
local function comma_row(values)
  local rendered = {}
  for index, value in ipairs(values) do
    rendered[index] = tostring(value)
  end
  return table.concat(rendered, ",")
end

local hash = 2166136261
local function mix(v)
  local n = math.floor(tonumber(v) or 0) & 0xffffffff
  hash = (hash ~ n) & 0xffffffff
  hash = (hash * 16777619) & 0xffffffff
end
local function digest_values(values)
  hash = 2166136261
  for _, value in ipairs(values) do mix(value) end
  return hash
end

local scene = sd.world.get_scene()
local player = sd.player.get_state()
local world_address = tonumber(scene and scene.world_address) or tonumber(player and player.world_address) or 0
emit("scene", scene and (scene.name or scene.kind) or "")
emit("world", hx(world_address))
emit("rng.global_818b08", hx(read_u32(0x00818B08)))
emit("player_x", player and player.x or 0)
emit("player_y", player and player.y or 0)

local local_run_nonce = 0
local remote_run_nonce = 0
local mp = sd.runtime.get_multiplayer_state and sd.runtime.get_multiplayer_state() or nil
if mp and mp.participants then
  for _, participant in ipairs(mp.participants) do
    local nonce = tonumber(participant.run_nonce) or 0
    if participant.kind == "LocalHuman" then
      local_run_nonce = nonce
    elseif nonce ~= 0 then
      remote_run_nonce = nonce
    end
  end
end
emit("local_run_nonce", hx(local_run_nonce))
emit("remote_run_nonce", hx(remote_run_nonce))

local controller = world_address + off("actor_owner_movement_controller")
local circle_count = read_i32(controller + off("movement_controller_circle_count"))
local circle_list = read_ptr(controller + off("movement_controller_circle_list"))
local circles = {}
local static_circles = {}
local mask4_count = 0
local max_circles = math.min(math.max(circle_count, 0), 2048)
for index = 0, max_circles - 1 do
  local circle = read_ptr(circle_list + (index * 4))
  if circle ~= 0 then
    local object_type = read_u32(circle + off("movement_circle_object_type"))
    local mask = read_u32(circle + off("movement_circle_mask"))
    local x = qf(read_f(circle + off("movement_circle_x")))
    local y = qf(read_f(circle + off("movement_circle_y")))
    local radius = qf(read_f(circle + off("movement_circle_radius")))
    local entry = {object_type, mask, x, y, radius}
    if (mask & 0x4) ~= 0 then
      mask4_count = mask4_count + 1
      table.insert(static_circles, entry)
    end
    table.insert(circles, entry)
  end
end
local function sort_circle_rows(rows)
  table.sort(rows, function(a, b)
    for index = 1, 5 do
      if a[index] ~= b[index] then return a[index] < b[index] end
    end
    return false
  end)
end
sort_circle_rows(circles)
sort_circle_rows(static_circles)
local function digest_circle_rows(rows, prefix)
  local values = prefix
  for _, circle in ipairs(rows) do
    for index = 1, 5 do table.insert(values, circle[index]) end
  end
  return digest_values(values)
end
local circle_values = {circle_count, #circles, mask4_count}
for _, circle in ipairs(circles) do
  for index = 1, 5 do
    table.insert(circle_values, circle[index])
  end
end
emit("circle_count", circle_count)
emit("circle_sampled", #circles)
emit("circle_mask4_count", mask4_count)
emit("circle_digest", hx(digest_values(circle_values)))
emit("circle_mask4_digest", hx(digest_circle_rows(static_circles, {mask4_count, #static_circles})))

local shape_count = read_i32(controller + off("movement_controller_shape_count"))
local shape_list = read_ptr(controller + off("movement_controller_shape_list"))
local shapes = {}
local max_shapes = math.min(math.max(shape_count, 0), 512)
for index = 0, max_shapes - 1 do
  local shape = read_ptr(shape_list + (index * 4))
  if shape ~= 0 then
    local points = read_ptr(shape + off("movement_shape_points"))
    if points == 0 then points = read_ptr(shape + off("movement_shape_cached_points")) end
    local point_count = read_i32(shape + off("movement_shape_point_count"))
    local entry = {
      qf(read_f(shape + off("movement_shape_bounds_x"))),
      qf(read_f(shape + off("movement_shape_bounds_y"))),
      qf(read_f(shape + off("movement_shape_bounds_w"))),
      qf(read_f(shape + off("movement_shape_bounds_h"))),
      point_count,
    }
    local point_limit = math.min(math.max(point_count, 0), 64)
    for point_index = 0, point_limit - 1 do
      table.insert(entry, qf(read_f(points + (point_index * 8))))
      table.insert(entry, qf(read_f(points + (point_index * 8) + 4)))
    end
    table.insert(shapes, entry)
  end
end
table.sort(shapes, function(a, b)
  local count = math.min(#a, #b)
  for index = 1, count do
    if a[index] ~= b[index] then return a[index] < b[index] end
  end
  return #a < #b
end)
local shape_values = {shape_count, #shapes}
for _, shape in ipairs(shapes) do
  for _, value in ipairs(shape) do table.insert(shape_values, value) end
end
emit("shape_count", shape_count)
emit("shape_sampled", #shapes)
emit("shape_digest", hx(digest_values(shape_values)))

local static_actors = {}
for _, actor in ipairs(sd.world.list_actors() or {}) do
  local type_id = tonumber(actor.object_type_id) or 0
  if (type_id == 0x1391 or type_id == 0x1392) and not actor.tracked_enemy then
    table.insert(static_actors, {
      type_id,
      qf(actor.x),
      qf(actor.y),
      qf(actor.radius),
      tonumber(actor.world_slot) or -1,
      tonumber(actor.anim_drive_state) or 0,
    })
  end
end
table.sort(static_actors, function(a, b)
  for index = 1, 6 do
    if a[index] ~= b[index] then return a[index] < b[index] end
  end
  return false
end)
-- World slots are process-local container indices and legitimately differ when
-- participant or helper actors occupy different insertion slots. Compare the
-- replicated actor's semantic state, while retaining the complete local row as
-- a diagnostic digest below.
local actor_values = {#static_actors}
local local_actor_values = {#static_actors}
for _, actor in ipairs(static_actors) do
  table.insert(actor_values, actor[1])
  table.insert(actor_values, actor[2])
  table.insert(actor_values, actor[3])
  table.insert(actor_values, actor[4])
  table.insert(actor_values, actor[6])
  for _, value in ipairs(actor) do table.insert(local_actor_values, value) end
end
emit("static_actor_count", #static_actors)
emit("static_actor_digest", hx(digest_values(actor_values)))
emit("static_actor_local_digest", hx(digest_values(local_actor_values)))
for index, actor in ipairs(static_actors) do
  emit("static." .. index .. ".type_id", actor[1])
  emit("static." .. index .. ".x_q10", actor[2])
  emit("static." .. index .. ".y_q10", actor[3])
  emit("static." .. index .. ".radius_q10", actor[4])
  emit("static." .. index .. ".world_slot", actor[5])
  emit("static." .. index .. ".anim_drive_state", actor[6])
end

-- Boneyard scenery is owned by RegionLayout's native PointerList rather than
-- the transient actor lane above. Preserve native list order and hash common
-- render state plus every proved family-specific renderer input. The previous
-- gate sorted rows and excluded Tree/Scrub presentation state.
local TREE_TYPE_ID = 2001
local MONUMENT_TYPE_ID = 2009
local GRAVESTONE_TYPE_ID = 2029
local BUILDING_TYPE_ID = 2040
local GOODIE_TYPE_ID = 2061
local SCRUB_TYPE_ID = 2062
local FENCEPOST_TYPE_ID = 3006
local FENCEGRATE_TYPE_ID = 3007
local BROKEN_GRATE_TYPE_ID = 3011
local GATE_TYPE_ID = 3012
local WALL_TYPE_ID = 3013
local RAILS_TYPE_ID = 3014

local function scenery_family_inputs(scenery, type_id)
  local values = {}
  if type_id == TREE_TYPE_ID then
    append(values, read_i16(scenery + off("boneyard_tree_variant")))
    append(values, read_i16(scenery + off("boneyard_tree_overlay_variant")))
    append(values, read_u8(scenery + off("boneyard_tree_overlay_enabled")))
    append(values, read_u32(scenery + off("boneyard_tree_sway_target")))
    append(values, read_u32(scenery + off("boneyard_tree_sway_current")))
  elseif type_id == SCRUB_TYPE_ID then
    append(values, read_u32(scenery + off("boneyard_scrub_phase")))
    append(values, read_i32(scenery + off("boneyard_scrub_variant")))
    append(values, read_u32(scenery + off("boneyard_scrub_orientation_x")))
    append(values, read_u32(scenery + off("boneyard_scrub_orientation_y")))
    append(values, read_u8(scenery + off("boneyard_scrub_collision_flag")))
  elseif type_id == MONUMENT_TYPE_ID or type_id == BUILDING_TYPE_ID then
    append(values, read_i16(scenery + off("boneyard_simple_scenery_variant")))
  elseif type_id == GRAVESTONE_TYPE_ID then
    append(values, read_i16(scenery + off("boneyard_gravestone_variant")))
    append(values, read_i16(scenery + off("boneyard_gravestone_overlay_variant")))
    append_u32_words(
      values,
      scenery,
      off("boneyard_gravestone_tint"),
      off("boneyard_gravestone_tint") + 12)
  elseif type_id == GOODIE_TYPE_ID then
    append(values, read_i16(scenery + off("boneyard_goodie_subtype")))
    append(values, read_u8(scenery + off("boneyard_goodie_phase")))
    local active = read_u8(scenery + off("boneyard_goodie_active"))
    append(values, active)
    -- +0x144 is read by the renderer only while the Goodie indicator is
    -- active. Canonicalize the inactive value in this render-input digest;
    -- constructor-state diagnostics are retained separately in live evidence.
    append(values, active ~= 0
      and read_u32(scenery + off("boneyard_goodie_timer"))
      or 0)
    append(values, read_u32(scenery + off("boneyard_goodie_reward_seed")))
  elseif type_id == FENCEPOST_TYPE_ID then
    append(values, read_u32(scenery + off("boneyard_fencepost_variant")))
    append(values, read_i16(scenery + off("boneyard_fencepost_bank")))
  elseif type_id == FENCEGRATE_TYPE_ID or
         type_id == BROKEN_GRATE_TYPE_ID or
         type_id == GATE_TYPE_ID or
         type_id == RAILS_TYPE_ID then
    append_u32_words(
      values,
      scenery,
      off("boneyard_fencegrate_geometry_start"),
      off("boneyard_fencegrate_geometry_end"))
    append_u32_words(
      values,
      scenery,
      off("boneyard_fencegrate_bounds"),
      off("boneyard_fencegrate_bounds") + 12)
    if type_id ~= FENCEGRATE_TYPE_ID then
      append(values, read_u8(scenery + off("boneyard_fence_leaf_side")))
    end
    if type_id == GATE_TYPE_ID then
      append_u32_words(
        values,
        scenery,
        off("boneyard_gate_render_state_start"),
        off("boneyard_gate_render_state_end"))
    elseif type_id == RAILS_TYPE_ID then
      append_u32_words(
        values,
        scenery,
        off("boneyard_rails_render_state_start"),
        off("boneyard_rails_render_state_end"))
    end
  elseif type_id == WALL_TYPE_ID then
    append_u32_words(
      values,
      scenery,
      off("boneyard_wall_fixed_geometry_start"),
      off("boneyard_wall_self_reference_a") - 4)
    append_u32_words(
      values,
      scenery,
      off("boneyard_wall_fixed_geometry_after_self_references"),
      off("boneyard_wall_fixed_geometry_end"))
    local scalar_count = math.min(
      math.max(read_i32(scenery + off("boneyard_wall_scalar_count")), 0),
      4096)
    local scalar_items = read_ptr(
      scenery + off("boneyard_wall_scalar_items"))
    append(values, scalar_count)
    if scalar_items ~= 0 then
      for index = 0, scalar_count - 1 do
        append(values, read_u32(scalar_items + index * 4))
      end
    end
    local point_count = math.min(
      math.max(read_i32(scenery + off("boneyard_wall_point_count")), 0),
      4096)
    local point_items = read_ptr(
      scenery + off("boneyard_wall_point_items"))
    append(values, point_count)
    if point_items ~= 0 then
      for index = 0, point_count - 1 do
        append(values, read_u32(point_items + index * 8))
        append(values, read_u32(point_items + index * 8 + 4))
      end
    end
    local index_count = math.min(
      math.max(read_i32(scenery + off("boneyard_wall_index_count")), 0),
      8192)
    local index_items = read_ptr(
      scenery + off("boneyard_wall_index_items"))
    append(values, index_count)
    if index_items ~= 0 then
      for index = 0, index_count - 1 do
        append(values, read_u32(index_items + index * 4))
      end
    end
  end
  return values
end

local scenery_list = world_address + off("actor_world_scenery_object_list")
local scenery_count = read_i32(scenery_list + off("pointer_list_count"))
local scenery_items = read_ptr(scenery_list + off("pointer_list_items"))
local scenery_rows = {}
local boneyard_trees = {}
local scenery_family_counts = {}
local max_scenery = scenery_items ~= 0
  and math.min(math.max(scenery_count, 0), 4096)
  or 0
for index = 0, max_scenery - 1 do
  local scenery = read_ptr(scenery_items + (index * 4))
  if scenery ~= 0 then
    local type_id = read_u32(scenery + off("game_object_type_id"))
    local x_address = scenery + off("actor_position_x")
    local y_address = scenery + off("actor_position_y")
    local radius_address = scenery + off("actor_collision_radius")
    local x_value = read_f(x_address)
    local y_value = read_f(y_address)
    local radius_value = read_f(radius_address)
    local materialization_key =
      read_i32(scenery + off("boneyard_scenery_materialization_key"))
    local row = {
      index,
      type_id,
      read_u32(x_address),
      read_u32(y_address),
      read_u32(radius_address),
      materialization_key,
    }
    append_u32_words(
      row,
      scenery,
      off("boneyard_scenery_common_tint"),
      off("boneyard_scenery_common_tint") + 12)
    append(row, read_u32(scenery + off("actor_render_sort_bias")))
    append(row, read_u32(scenery + off("boneyard_scenery_common_scalar")))
    append(row, read_u32(scenery + off("boneyard_scenery_common_scale")))
    append_u32_words(
      row,
      scenery,
      off("boneyard_scenery_common_color"),
      off("boneyard_scenery_common_color") + 12)
    append(row, read_u32(scenery + off("boneyard_scenery_render_parameter")))
    local family_inputs = scenery_family_inputs(scenery, type_id)
    append(row, #family_inputs)
    for _, value in ipairs(family_inputs) do append(row, value) end
    table.insert(scenery_rows, row)
    scenery_family_counts[type_id] =
      (scenery_family_counts[type_id] or 0) + 1

    if type_id == TREE_TYPE_ID or type_id == SCRUB_TYPE_ID then
      local variant = type_id == TREE_TYPE_ID
        and read_i16(scenery + off("boneyard_tree_variant"))
        or read_i32(scenery + off("boneyard_scrub_variant"))
      local overlay_variant = type_id == TREE_TYPE_ID
        and read_i16(scenery + off("boneyard_tree_overlay_variant"))
        or 0
      local overlay_enabled = type_id == TREE_TYPE_ID
        and read_u8(scenery + off("boneyard_tree_overlay_enabled"))
        or 0
      table.insert(boneyard_trees, {
        type_id,
        read_u32(x_address),
        read_u32(y_address),
        read_u32(radius_address),
        materialization_key,
        variant,
        overlay_variant,
        overlay_enabled,
        read_u32(scenery + off("boneyard_scenery_phase")),
        read_u32(scenery + off("boneyard_scenery_render_parameter")),
        type_id == TREE_TYPE_ID
          and read_u32(scenery + off("boneyard_tree_sway_countdown"))
          or 0,
        type_id == TREE_TYPE_ID
          and read_u32(scenery + off("boneyard_tree_sway_target"))
          or read_u32(scenery + off("boneyard_scrub_orientation_x")),
        type_id == TREE_TYPE_ID
          and read_u32(scenery + off("boneyard_tree_sway_current"))
          or read_u32(scenery + off("boneyard_scrub_orientation_y")),
        type_id == SCRUB_TYPE_ID
          and read_u8(scenery + off("boneyard_scrub_collision_flag"))
          or 0,
        index,
        x_value,
        y_value,
        radius_value,
      })
    end
  end
end
local function digest_rows(rows, prefix, field_count)
  local values = prefix
  for _, row in ipairs(rows) do
    local count = field_count or #row
    for index = 1, count do table.insert(values, row[index]) end
  end
  return digest_values(values)
end
emit("boneyard_scenery_count", scenery_count)
emit("boneyard_scenery_sampled", #scenery_rows)
emit("boneyard_scenery_digest", hx(
  digest_rows(scenery_rows, {scenery_count, #scenery_rows})))
for index, scenery in ipairs(scenery_rows) do
  emit("boneyard_scenery." .. index .. ".row", comma_row(scenery))
end
for _, type_id in ipairs({
    TREE_TYPE_ID,
    MONUMENT_TYPE_ID,
    GRAVESTONE_TYPE_ID,
    BUILDING_TYPE_ID,
    GOODIE_TYPE_ID,
    SCRUB_TYPE_ID,
    FENCEPOST_TYPE_ID,
    FENCEGRATE_TYPE_ID,
    BROKEN_GRATE_TYPE_ID,
    GATE_TYPE_ID,
    WALL_TYPE_ID,
    RAILS_TYPE_ID,
  }) do
  emit(
    "boneyard_scenery_type_" .. type_id .. "_count",
    scenery_family_counts[type_id] or 0)
end
emit("boneyard_tree_count", #boneyard_trees)
local boneyard_tree_render_rows = {}
for _, tree in ipairs(boneyard_trees) do
  local render_row = {
    tree[1],
    tree[2],
    tree[3],
    tree[4],
    tree[5],
    tree[6],
    tree[7],
    tree[8],
    tree[10],
  }
  if tree[1] == TREE_TYPE_ID then
    append(render_row, tree[12])
    append(render_row, tree[13])
  else
    append(render_row, tree[9])
    append(render_row, tree[12])
    append(render_row, tree[13])
    append(render_row, tree[14])
  end
  append(render_row, tree[15])
  table.insert(boneyard_tree_render_rows, render_row)
end
emit("boneyard_tree_digest", hx(
  digest_rows(boneyard_tree_render_rows, {#boneyard_trees})))
emit("boneyard_tree_diagnostic_digest", hx(
  digest_rows(boneyard_trees, {#boneyard_trees}, 15)))
for index, tree in ipairs(boneyard_trees) do
  emit("boneyard_tree." .. index .. ".type_id", tree[1])
  emit("boneyard_tree." .. index .. ".x_bits", hx(tree[2]))
  emit("boneyard_tree." .. index .. ".y_bits", hx(tree[3]))
  emit("boneyard_tree." .. index .. ".radius_bits", hx(tree[4]))
  emit("boneyard_tree." .. index .. ".materialization_key", tree[5])
  emit("boneyard_tree." .. index .. ".variant", tree[6])
  emit("boneyard_tree." .. index .. ".overlay_variant", tree[7])
  emit("boneyard_tree." .. index .. ".overlay_enabled", tree[8])
  emit("boneyard_tree." .. index .. ".phase_bits", hx(tree[9]))
  emit("boneyard_tree." .. index .. ".render_parameter_bits", hx(tree[10]))
  emit("boneyard_tree." .. index .. ".sway_countdown", tree[11])
  emit("boneyard_tree." .. index .. ".sway_target_bits", hx(tree[12]))
  emit("boneyard_tree." .. index .. ".sway_current_bits", hx(tree[13]))
  emit("boneyard_tree." .. index .. ".scrub_collision_flag", tree[14])
  emit("boneyard_tree." .. index .. ".native_index", tree[15])
  emit("boneyard_tree." .. index .. ".x", tree[16])
  emit("boneyard_tree." .. index .. ".y", tree[17])
  emit("boneyard_tree." .. index .. ".radius", tree[18])
end

-- Roads, abstract Fence specifications, and Terrain live in separate
-- RegionLayout ObjectManagers. Their ordered serialized inputs feed the
-- deterministic mesh and derived-scenery builders, so include those inputs in
-- the same render-materialization gate.
local road_list = world_address + off("actor_world_road_list")
local road_count = read_i32(road_list + off("pointer_list_count"))
local road_items = read_ptr(road_list + off("pointer_list_items"))
local road_rows = {}
local max_roads = road_items ~= 0
  and math.min(math.max(road_count, 0), 2048)
  or 0
for index = 0, max_roads - 1 do
  local road = read_ptr(road_items + index * 4)
  if road ~= 0 then
    local row = {index}
    append_u32_words(
      row,
      road,
      off("boneyard_road_start"),
      off("boneyard_road_end") + 4)
    append_u32_words(
      row,
      road,
      off("boneyard_road_width_scales"),
      off("boneyard_road_width_scales") + 4)
    append_u32_words(
      row,
      road,
      off("boneyard_road_quad"),
      off("boneyard_road_quad") + 28)
    append(row, read_u8(road + off("boneyard_road_style")))
    table.insert(road_rows, row)
  end
end
emit("boneyard_road_count", road_count)
emit("boneyard_road_sampled", #road_rows)
emit("boneyard_road_digest", hx(
  digest_rows(road_rows, {road_count, #road_rows})))
for index, road in ipairs(road_rows) do
  emit("boneyard_road." .. index .. ".row", comma_row(road))
end

local fence_list = world_address + off("actor_world_fence_list")
local fence_count = read_i32(fence_list + off("pointer_list_count"))
local fence_items = read_ptr(fence_list + off("pointer_list_items"))
local fence_rows = {}
local max_fences = fence_items ~= 0
  and math.min(math.max(fence_count, 0), 2048)
  or 0
for index = 0, max_fences - 1 do
  local fence = read_ptr(fence_items + index * 4)
  if fence ~= 0 then
    local row = {index}
    append_u32_words(
      row,
      fence,
      off("boneyard_fence_start"),
      off("boneyard_fence_end") + 4)
    append(row, read_u32(fence + off("boneyard_fence_start_post_variant")))
    append(row, read_u32(fence + off("boneyard_fence_end_post_variant")))
    append(row, read_u8(fence + off("boneyard_fence_segment_code")))
    table.insert(fence_rows, row)
  end
end
emit("boneyard_fence_count", fence_count)
emit("boneyard_fence_sampled", #fence_rows)
emit("boneyard_fence_digest", hx(
  digest_rows(fence_rows, {fence_count, #fence_rows})))
for index, fence in ipairs(fence_rows) do
  emit("boneyard_fence." .. index .. ".row", comma_row(fence))
end

local terrain_list = world_address + off("actor_world_terrain_list")
local terrain_count = read_i32(terrain_list + off("pointer_list_count"))
local terrain_items = read_ptr(terrain_list + off("pointer_list_items"))
local terrain_rows = {}
local max_terrain = terrain_items ~= 0
  and math.min(math.max(terrain_count, 0), 512)
  or 0
for index = 0, max_terrain - 1 do
  local terrain = read_ptr(terrain_items + index * 4)
  if terrain ~= 0 then
    local row = {
      index,
      read_u32(terrain + off("boneyard_terrain_style")),
      read_u32(terrain + off("boneyard_terrain_reserved")),
      read_u32(terrain + off("boneyard_terrain_scale")),
      read_u32(terrain + off("boneyard_terrain_seed")),
    }
    local point_count = math.min(
      math.max(read_i32(terrain + off("boneyard_terrain_point_count")), 0),
      4096)
    local point_items = read_ptr(
      terrain + off("boneyard_terrain_point_items"))
    append(row, point_count)
    if point_items ~= 0 then
      for point_index = 0, point_count - 1 do
        append(row, read_u32(point_items + point_index * 8))
        append(row, read_u32(point_items + point_index * 8 + 4))
      end
    end
    local scalar_count = math.min(
      math.max(read_i32(terrain + off("boneyard_terrain_scalar_count")), 0),
      4096)
    local scalar_items = read_ptr(
      terrain + off("boneyard_terrain_scalar_items"))
    append(row, scalar_count)
    if scalar_items ~= 0 then
      for scalar_index = 0, scalar_count - 1 do
        append(row, read_u32(scalar_items + scalar_index * 4))
      end
    end
    table.insert(terrain_rows, row)
  end
end
emit("boneyard_terrain_count", terrain_count)
emit("boneyard_terrain_sampled", #terrain_rows)
emit("boneyard_terrain_digest", hx(
  digest_rows(terrain_rows, {terrain_count, #terrain_rows})))
for index, terrain in ipairs(terrain_rows) do
  emit("boneyard_terrain." .. index .. ".row", comma_row(terrain))
end

-- RegionLayout section 11 is a separate PointerList of fixed 0x2C-byte
-- compact-decoration records. Preserve native order and include both the
-- serialized draw controls and the four runtime bounds used by culling.
local compact_list = world_address + off("actor_world_compact_decoration_list")
local compact_count = read_i32(compact_list + off("pointer_list_count"))
local compact_items = read_ptr(compact_list + off("pointer_list_items"))
local compact_rows = {}
local compact_ignored_flag_bits_count = 0
local compact_type_7_8_count = 0
local compact_type_7_8_noncanonical_flags = 0
local compact_type_21_24_count = 0
local compact_family_counts = {
  tree_ground_cover = 0,
  ground_patches = 0,
  paving_stones = 0,
  pebbles = 0,
  twig_lattice = 0,
  large_rocks = 0,
  shadow_masks = 0,
  dead_roots = 0,
}
local max_compact = compact_items ~= 0
  and math.min(math.max(compact_count, 0), 4096)
  or 0
for index = 0, max_compact - 1 do
  local compact = read_ptr(compact_items + (index * 4))
  if compact ~= 0 then
    local type_id = read_u32(compact + off("boneyard_compact_type"))
    local x_bits = read_u32(compact + off("boneyard_compact_position_x"))
    local y_bits = read_u32(compact + off("boneyard_compact_position_y"))
    local rotation_bits = read_u32(compact + off("boneyard_compact_rotation"))
    local scale_bits = read_u32(compact + off("boneyard_compact_scale"))
    local alpha_bits = read_u32(compact + off("boneyard_compact_alpha"))
    local flags = read_u8(compact + off("boneyard_compact_flags"))
    local bounds_left_bits =
      read_u32(compact + off("boneyard_compact_bounds_left"))
    local bounds_top_bits =
      read_u32(compact + off("boneyard_compact_bounds_top"))
    local bounds_right_bits =
      read_u32(compact + off("boneyard_compact_bounds_right"))
    local bounds_bottom_bits =
      read_u32(compact + off("boneyard_compact_bounds_bottom"))
    if (flags & 0xFC) ~= 0 then
      compact_ignored_flag_bits_count = compact_ignored_flag_bits_count + 1
    end
    if type_id == 7 or type_id == 8 then
      compact_type_7_8_count = compact_type_7_8_count + 1
      if flags ~= 1 then
        compact_type_7_8_noncanonical_flags =
          compact_type_7_8_noncanonical_flags + 1
      end
    end
    if type_id >= 0 and type_id <= 6 then
      compact_family_counts.tree_ground_cover =
        compact_family_counts.tree_ground_cover + 1
    elseif type_id <= 8 then
      compact_family_counts.ground_patches =
        compact_family_counts.ground_patches + 1
    elseif type_id <= 12 then
      compact_family_counts.paving_stones =
        compact_family_counts.paving_stones + 1
    elseif type_id <= 18 then
      compact_family_counts.pebbles =
        compact_family_counts.pebbles + 1
    elseif type_id <= 20 then
      compact_family_counts.twig_lattice =
        compact_family_counts.twig_lattice + 1
    elseif type_id <= 24 then
      compact_type_21_24_count = compact_type_21_24_count + 1
      compact_family_counts.large_rocks =
        compact_family_counts.large_rocks + 1
    elseif type_id <= 29 then
      compact_family_counts.shadow_masks =
        compact_family_counts.shadow_masks + 1
    elseif type_id == 30 then
      compact_family_counts.dead_roots =
        compact_family_counts.dead_roots + 1
    end
    table.insert(compact_rows, {
      index,
      type_id,
      x_bits,
      y_bits,
      rotation_bits,
      scale_bits,
      alpha_bits,
      flags,
      bounds_left_bits,
      bounds_top_bits,
      bounds_right_bits,
      bounds_bottom_bits,
    })
  end
end
emit("boneyard_compact_count", compact_count)
emit("boneyard_compact_sampled", #compact_rows)
emit("boneyard_compact_digest", hx(
  digest_rows(compact_rows, {compact_count, #compact_rows}, 12)))
emit("boneyard_compact_ignored_flag_bits_count",
  compact_ignored_flag_bits_count)
emit("boneyard_compact_type_7_8_count", compact_type_7_8_count)
emit("boneyard_compact_type_7_8_noncanonical_flags",
  compact_type_7_8_noncanonical_flags)
emit("boneyard_compact_type_21_24_count", compact_type_21_24_count)
for family, count in pairs(compact_family_counts) do
  emit("boneyard_compact_family_" .. family .. "_count", count)
end
for index, compact in ipairs(compact_rows) do
  emit(
    "boneyard_compact." .. index .. ".row",
    string.format(
      "%d,%d,%s,%s,%s,%s,%s,%d,%s,%s,%s,%s",
      compact[1],
      compact[2],
      hx(compact[3]),
      hx(compact[4]),
      hx(compact[5]),
      hx(compact[6]),
      hx(compact[7]),
      compact[8],
      hx(compact[9]),
      hx(compact[10]),
      hx(compact[11]),
      hx(compact[12])))
end

local replicated = sd.world.get_replicated_actors and sd.world.get_replicated_actors() or nil
local replicated_run_static_count = 0
if replicated and replicated.actors then
  for _, actor in ipairs(replicated.actors) do
    if actor.run_static then replicated_run_static_count = replicated_run_static_count + 1 end
  end
end
emit("replicated_actor_count", replicated and replicated.actor_count or 0)
emit("replicated_run_static_count", replicated_run_static_count)
emit("replicated_matched_actor_count", replicated and replicated.matched_actor_count or 0)
"""


def values(pipe_name: str) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, STATIC_LAYOUT_LUA, timeout=25.0))


def integer(row: dict[str, str], key: str) -> int:
    try:
        return int(float(row.get(key, "0") or "0"))
    except ValueError:
        return 0


def u32(text: str) -> int:
    return int(text, 0) & 0xFFFFFFFF


def float_from_u32(text: str) -> float:
    return struct.unpack("<f", struct.pack("<I", u32(text)))[0]


def decor_tables(row: dict[str, str]) -> dict[str, Any]:
    scenery: list[dict[str, Any]] = []
    for index in range(1, integer(row, "boneyard_scenery_sampled") + 1):
        key = f"boneyard_scenery.{index}.row"
        fields = row.get(key, "").split(",")
        if len(fields) < 19:
            raise VerifyFailure(
                f"scenery decor dump {index} is malformed: {row.get(key)!r}"
            )
        values = [int(field, 0) for field in fields]
        family_input_count = values[18]
        if len(values) != 19 + family_input_count:
            raise VerifyFailure(
                f"scenery decor dump {index} family payload is malformed: "
                f"expected {family_input_count}, row={row.get(key)!r}"
            )
        scenery.append(
            {
                "native_index": values[0],
                "type_id": values[1],
                "position": [
                    float_from_u32(str(values[2])),
                    float_from_u32(str(values[3])),
                ],
                "position_bits": values[2:4],
                "radius_bits": values[4],
                "materialization_key": values[5],
                "common_tint_bits": values[6:10],
                "render_sort_bias_bits": values[10],
                "common_scalar_bits": values[11],
                "common_scale_bits": values[12],
                "common_color_bits": values[13:17],
                "render_parameter_bits": values[17],
                "family_inputs": values[19:],
            }
        )

    trees: list[dict[str, Any]] = []
    for index in range(1, integer(row, "boneyard_tree_count") + 1):
        prefix = f"boneyard_tree.{index}."
        required = (
            "type_id",
            "x_bits",
            "y_bits",
            "radius_bits",
            "materialization_key",
            "variant",
            "overlay_variant",
            "overlay_enabled",
            "phase_bits",
            "render_parameter_bits",
            "sway_countdown",
            "sway_target_bits",
            "sway_current_bits",
            "scrub_collision_flag",
            "native_index",
        )
        missing = [field for field in required if prefix + field not in row]
        if missing:
            raise VerifyFailure(
                f"Tree decor dump {index} is incomplete: {', '.join(missing)}"
            )
        x_bits = row[prefix + "x_bits"]
        y_bits = row[prefix + "y_bits"]
        radius_bits = row[prefix + "radius_bits"]
        type_id = integer(row, prefix + "type_id")
        tree = {
            "type_id": type_id,
            "position": [
                float_from_u32(x_bits),
                float_from_u32(y_bits),
            ],
            "position_bits": [x_bits, y_bits],
            "radius": float_from_u32(radius_bits),
            "radius_bits": radius_bits,
            "materialization_key": integer(
                row, prefix + "materialization_key"
            ),
            "variant": integer(row, prefix + "variant"),
            "overlay_variant": integer(row, prefix + "overlay_variant"),
            "overlay_enabled": integer(row, prefix + "overlay_enabled"),
            "render_parameter_bits": u32(
                row[prefix + "render_parameter_bits"]
            ),
            "sway_target_bits": u32(row[prefix + "sway_target_bits"]),
            "sway_current_bits": u32(row[prefix + "sway_current_bits"]),
            "native_index": integer(row, prefix + "native_index"),
        }
        if type_id == 2062:
            tree["phase_bits"] = u32(row[prefix + "phase_bits"])
            tree["scrub_collision_flag"] = integer(
                row, prefix + "scrub_collision_flag"
            )
        trees.append(tree)

    compact: list[dict[str, Any]] = []
    for index in range(1, integer(row, "boneyard_compact_sampled") + 1):
        key = f"boneyard_compact.{index}.row"
        fields = row.get(key, "").split(",")
        if len(fields) != 12:
            raise VerifyFailure(
                f"compact decor dump {index} is malformed: {row.get(key)!r}"
            )
        (
            native_index_text,
            type_id_text,
            x_bits,
            y_bits,
            rotation_bits,
            scale_bits,
            alpha_bits,
            flags_text,
            bounds_left_bits,
            bounds_top_bits,
            bounds_right_bits,
            bounds_bottom_bits,
        ) = fields
        compact.append(
            {
                "native_index": int(native_index_text),
                "type_id": int(type_id_text),
                "position": [
                    float_from_u32(x_bits),
                    float_from_u32(y_bits),
                ],
                "position_bits": [x_bits, y_bits],
                "rotation": float_from_u32(rotation_bits),
                "rotation_bits": rotation_bits,
                "scale": float_from_u32(scale_bits),
                "scale_bits": scale_bits,
                "alpha": float_from_u32(alpha_bits),
                "alpha_bits": alpha_bits,
                "flags": int(flags_text),
                "bounds_bits": [
                    u32(bounds_left_bits),
                    u32(bounds_top_bits),
                    u32(bounds_right_bits),
                    u32(bounds_bottom_bits),
                ],
            }
        )

    ordered_table_names = ("road", "fence", "terrain")
    ordered_tables: dict[str, list[list[int]]] = {}
    for table_name in ordered_table_names:
        table_rows: list[list[int]] = []
        sampled = integer(row, f"boneyard_{table_name}_sampled")
        for index in range(1, sampled + 1):
            key = f"boneyard_{table_name}.{index}.row"
            fields = row.get(key, "").split(",")
            if not fields or fields == [""]:
                raise VerifyFailure(
                    f"{table_name} dump {index} is malformed: "
                    f"{row.get(key)!r}"
                )
            table_rows.append([int(field, 0) for field in fields])
        ordered_tables[table_name] = table_rows

    scenery_type_counts = {
        str(type_id): integer(
            row, f"boneyard_scenery_type_{type_id}_count"
        )
        for type_id in (
            2001,
            2009,
            2029,
            2040,
            2061,
            2062,
            3006,
            3007,
            3011,
            3012,
            3013,
            3014,
        )
    }
    compact_family_counts = {
        family: integer(row, f"boneyard_compact_family_{family}_count")
        for family in (
            "tree_ground_cover",
            "ground_patches",
            "paving_stones",
            "pebbles",
            "twig_lattice",
            "large_rocks",
            "shadow_masks",
            "dead_roots",
        )
    }
    return {
        "scenery_count": integer(row, "boneyard_scenery_count"),
        "scenery_digest": row.get("boneyard_scenery_digest", ""),
        "scenery_type_counts": scenery_type_counts,
        "scenery": scenery,
        "tree_count": integer(row, "boneyard_tree_count"),
        "tree_digest": row.get("boneyard_tree_digest", ""),
        "trees": trees,
        "road_count": integer(row, "boneyard_road_count"),
        "road_digest": row.get("boneyard_road_digest", ""),
        "roads": ordered_tables["road"],
        "fence_count": integer(row, "boneyard_fence_count"),
        "fence_digest": row.get("boneyard_fence_digest", ""),
        "fences": ordered_tables["fence"],
        "terrain_count": integer(row, "boneyard_terrain_count"),
        "terrain_digest": row.get("boneyard_terrain_digest", ""),
        "terrain": ordered_tables["terrain"],
        "compact_count": integer(row, "boneyard_compact_count"),
        "compact_digest": row.get("boneyard_compact_digest", ""),
        "compact_ignored_flag_bits_count": integer(
            row, "boneyard_compact_ignored_flag_bits_count"
        ),
        "compact_type_7_8_count": integer(
            row, "boneyard_compact_type_7_8_count"
        ),
        "compact_type_7_8_noncanonical_flags": integer(
            row, "boneyard_compact_type_7_8_noncanonical_flags"
        ),
        "compact_type_21_24_count": integer(
            row, "boneyard_compact_type_21_24_count"
        ),
        "compact_family_counts": compact_family_counts,
        "compact": compact,
    }


def layouts_match(host: dict[str, str], client: dict[str, str]) -> bool:
    required_equal = [
        "local_run_nonce",
        "circle_mask4_count",
        "circle_mask4_digest",
        "shape_count",
        "shape_digest",
        "boneyard_scenery_count",
        "boneyard_scenery_digest",
        "boneyard_tree_count",
        "boneyard_tree_digest",
        "boneyard_road_count",
        "boneyard_road_digest",
        "boneyard_fence_count",
        "boneyard_fence_digest",
        "boneyard_terrain_count",
        "boneyard_terrain_digest",
        "boneyard_compact_count",
        "boneyard_compact_digest",
        "boneyard_compact_type_7_8_count",
        "boneyard_compact_type_21_24_count",
    ]
    required_equal.extend(
        f"boneyard_scenery_type_{type_id}_count"
        for type_id in (
            2001,
            2009,
            2029,
            2040,
            2061,
            2062,
            3006,
            3007,
            3011,
            3012,
            3013,
            3014,
        )
    )
    required_equal.extend(
        f"boneyard_compact_family_{family}_count"
        for family in (
            "tree_ground_cover",
            "ground_patches",
            "paving_stones",
            "pebbles",
            "twig_lattice",
            "large_rocks",
            "shadow_masks",
            "dead_roots",
        )
    )
    return (
        host.get("scene") == "testrun"
        and client.get("scene") == "testrun"
        and host.get("local_run_nonce") not in ("", "0x00000000")
        and client.get("local_run_nonce") == host.get("local_run_nonce")
        and integer(host, "circle_count") > 0
        and integer(host, "circle_mask4_count") > 0
        and integer(host, "boneyard_scenery_count") > 0
        and integer(host, "boneyard_tree_count") > 0
        and integer(host, "boneyard_compact_count") > 0
        and integer(host, "boneyard_compact_type_7_8_count") > 0
        and integer(host, "boneyard_compact_type_21_24_count") > 0
        and integer(host, "boneyard_compact_ignored_flag_bits_count") == 0
        and integer(client, "boneyard_compact_ignored_flag_bits_count") == 0
        and integer(host, "boneyard_compact_type_7_8_noncanonical_flags") == 0
        and integer(client, "boneyard_compact_type_7_8_noncanonical_flags") == 0
        and integer(client, "replicated_run_static_count") >= integer(host, "static_actor_count")
        and integer(client, "replicated_matched_actor_count") >= integer(host, "static_actor_count")
        and all(host.get(key) == client.get(key) for key in required_equal)
    )


def wait_for_layout_sync(
    host_pipe: str,
    client_pipe: str,
    timeout: float = 30.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last_host: dict[str, str] = {}
    last_client: dict[str, str] = {}
    while time.monotonic() < deadline:
        last_host = values(host_pipe)
        last_client = values(client_pipe)
        if layouts_match(last_host, last_client):
            host_decor = decor_tables(last_host)
            client_decor = decor_tables(last_client)
            if host_decor != client_decor:
                raise VerifyFailure(
                    "decor digests matched but the exact Tree/compact tables did not"
                )
            return {
                "host": last_host,
                "client": last_client,
                "decor_tables": {
                    "host": host_decor,
                    "client": client_decor,
                },
            }
        time.sleep(0.25)
    raise VerifyFailure(f"run static layout did not converge: host={last_host} client={last_client}")


def _normalize_windows_path(path: str) -> str:
    return path.replace("/", "\\").rstrip("\\").casefold()


def expected_owned_process_identities(
    launch: dict[str, object],
    instance_prefix: str,
) -> list[dict[str, Any]]:
    roles = (
        ("host", "hostProcessId"),
        ("client", "clientProcessId"),
    )
    identities: list[dict[str, Any]] = []
    for role, key in roles:
        process_id = integer({key: str(launch.get(key, ""))}, key)
        if process_id <= 0:
            raise VerifyFailure(f"launcher did not report the {role} process ID")
        expected_path = path_for_powershell(
            ROOT
            / "runtime"
            / "instances"
            / f"{instance_prefix}-{role}"
            / "stage"
            / "SolomonDark.exe"
        )
        identities.append(
            {
                "role": role,
                "process_id": process_id,
                "executable_path": expected_path,
            }
        )
    return identities


def capture_owned_process_identities(
    expected_identities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    expected = {
        int(identity["process_id"]): identity
        for identity in expected_identities
    }

    joined_ids = ",".join(str(process_id) for process_id in sorted(expected))
    script = (
        f"$ids = @({joined_ids}); "
        "$rows = @(Get-CimInstance Win32_Process | "
        "Where-Object { $ids -contains [int]$_.ProcessId } | "
        "Select-Object ProcessId,ExecutablePath); "
        "[Console]::Write((ConvertTo-Json -InputObject $rows -Compress))"
    )
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=15.0,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise VerifyFailure(f"could not inspect launched game processes: {detail}")
    try:
        rows = json.loads(completed.stdout.strip())
    except json.JSONDecodeError as exc:
        raise VerifyFailure(
            f"launched process inspection returned invalid JSON: {completed.stdout!r}"
        ) from exc
    if not isinstance(rows, list):
        rows = [rows]

    by_id = {
        int(row["ProcessId"]): row
        for row in rows
        if isinstance(row, dict) and "ProcessId" in row
    }
    identities: list[dict[str, Any]] = []
    for process_id, identity in expected.items():
        role = str(identity["role"])
        expected_path = str(identity["executable_path"])
        row = by_id.get(process_id)
        if row is None:
            raise VerifyFailure(
                f"{role} process {process_id} exited before identity capture"
            )
        executable_path = str(row.get("ExecutablePath") or "")
        if _normalize_windows_path(executable_path) != _normalize_windows_path(
            expected_path
        ):
            raise VerifyFailure(
                f"refusing ownership of {role} PID {process_id}: "
                f"expected={expected_path!r} actual={executable_path!r}"
            )
        identities.append(
            {
                "role": role,
                "process_id": process_id,
                "executable_path": executable_path,
            }
        )
    return identities


def stop_owned_processes(
    identities: list[dict[str, Any]],
) -> dict[str, Any]:
    if not identities:
        return {"exact_pid_path_cleanup": True, "processes": []}

    payload = json.dumps(identities, separators=(",", ":")).replace("'", "''")
    script = f"""
$ErrorActionPreference = "Stop"
$targets = ConvertFrom-Json -InputObject '{payload}'
$stopped = @()
foreach ($target in @($targets)) {{
    $processId = [int]$target.process_id
    $expectedPath = [string]$target.executable_path
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $processId"
    if ($null -eq $process) {{
        $stopped += [pscustomobject]@{{
            processId = $processId
            executablePath = $expectedPath
            alreadyExited = $true
        }}
        continue
    }}
    if (-not [string]::Equals(
            [string]$process.ExecutablePath,
            $expectedPath,
            [System.StringComparison]::OrdinalIgnoreCase)) {{
        throw "PID $processId path changed; refusing cleanup"
    }}
    Stop-Process -Id $processId -Force
    $stopped += [pscustomobject]@{{
        processId = $processId
        executablePath = $expectedPath
        alreadyExited = $false
    }}
}}
$deadline = [DateTime]::UtcNow.AddSeconds(10)
do {{
    $remaining = @(
        $targets |
            ForEach-Object {{ Get-Process -Id ([int]$_.process_id) -ErrorAction SilentlyContinue }}
    )
    if ($remaining.Count -eq 0) {{ break }}
    Start-Sleep -Milliseconds 100
}} while ([DateTime]::UtcNow -lt $deadline)
if ($remaining.Count -ne 0) {{
    throw "owned Solomon Dark processes did not exit"
}}
[Console]::Write((ConvertTo-Json -InputObject $stopped -Compress))
"""
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20.0,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise VerifyFailure(f"exact PID/path cleanup failed: {detail}")
    stopped = json.loads(completed.stdout.strip())
    if not isinstance(stopped, list):
        stopped = [stopped]
    return {
        "exact_pid_path_cleanup": True,
        "processes": stopped,
    }


def matched_camera_target(
    decor: dict[str, Any],
    anchor_position: list[float] | None = None,
) -> dict[str, Any]:
    trees = decor["trees"]
    compact = [
        row for row in decor["compact"] if row["type_id"] in (7, 8)
    ]
    if not trees or not compact:
        raise VerifyFailure("matched-camera capture lacks Tree or type 7/8 decor")

    anchor = anchor_position or [
        sum(tree["position"][axis] for tree in trees) / len(trees)
        for axis in (0, 1)
    ]
    min_x = min(tree["position"][0] for tree in trees)
    max_x = max(tree["position"][0] for tree in trees)
    min_y = min(tree["position"][1] for tree in trees)
    max_y = max(tree["position"][1] for tree in trees)
    margin_x = (max_x - min_x) * 0.15
    margin_y = (max_y - min_y) * 0.15
    interior_trees = [
        tree
        for tree in trees
        if min_x + margin_x <= tree["position"][0] <= max_x - margin_x
        and min_y + margin_y <= tree["position"][1] <= max_y - margin_y
    ]
    tree = min(
        interior_trees or trees,
        key=lambda row: math.dist(row["position"], anchor),
    )
    candidate = min(
        compact,
        key=lambda row: math.dist(row["position"], tree["position"]),
    )
    distance = math.dist(candidate["position"], tree["position"])
    return {
        "position": tree["position"],
        "selection_anchor": anchor,
        "tree": tree,
        "nearby_compact": candidate,
        "nearby_compact_distance": distance,
    }


def focus_camera(
    pipe_name: str,
    target_x: float,
    target_y: float,
    timeout: float = 8.0,
) -> dict[str, Any]:
    if not math.isfinite(target_x) or not math.isfinite(target_y):
        raise VerifyFailure(f"invalid camera target: {target_x}, {target_y}")
    set_code = f"""
local ok = sd.camera.set_focus({target_x!r}, {target_y!r})
print("accepted=" .. tostring(ok))
"""
    accepted = parse_key_values(lua(pipe_name, set_code, timeout=10.0))
    if accepted.get("accepted") != "true":
        raise VerifyFailure(
            f"camera focus was rejected on {pipe_name}: {accepted}"
        )

    query_code = """
local camera = assert(sd.camera.get_state())
print("focus_active=" .. tostring(camera.focus_active))
print("focus_x=" .. tostring(camera.focus_x))
print("focus_y=" .. tostring(camera.focus_y))
print("center_x=" .. tostring(camera.center_x))
print("center_y=" .. tostring(camera.center_y))
print("width=" .. tostring(camera.width))
print("height=" .. tostring(camera.height))
"""
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = parse_key_values(lua(pipe_name, query_code, timeout=10.0))
        if (
            last.get("focus_active") == "true"
            and abs(float(last.get("focus_x", "nan")) - target_x) <= 0.05
            and abs(float(last.get("focus_y", "nan")) - target_y) <= 0.05
            and abs(float(last.get("center_x", "nan")) - target_x) <= 0.05
            and abs(float(last.get("center_y", "nan")) - target_y) <= 0.05
        ):
            return {
                key: (
                    value == "true"
                    if key == "focus_active"
                    else float(value)
                )
                for key, value in last.items()
            }
        time.sleep(0.1)
    raise VerifyFailure(
        f"camera did not settle on {pipe_name}: target={target_x},{target_y} "
        f"last={last}"
    )


def _correlation(left: list[int], right: list[int]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("correlation inputs must be nonempty and equal length")
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    left_centered = [value - left_mean for value in left]
    right_centered = [value - right_mean for value in right]
    numerator = sum(
        left_value * right_value
        for left_value, right_value in zip(
            left_centered, right_centered, strict=True
        )
    )
    denominator = math.sqrt(
        sum(value * value for value in left_centered)
        * sum(value * value for value in right_centered)
    )
    return numerator / denominator if denominator > 0.0 else 0.0


def matched_frame_correlation(
    host_path: Path,
    client_path: Path,
) -> dict[str, float]:
    normalized: list[Image.Image] = []
    for path in (host_path, client_path):
        with Image.open(path) as source:
            gray = source.convert("L")
            top = gray.height // 9
            bottom = gray.height * 5 // 6
            world_view = gray.crop((0, top, gray.width, bottom))
            normalized.append(
                world_view.resize(
                    (
                        200,
                        max(
                            1,
                            round(
                                200
                                * world_view.height
                                / world_view.width
                            ),
                        ),
                    ),
                    Image.Resampling.BILINEAR,
                )
            )

    host_gray = list(normalized[0].get_flattened_data())
    client_gray = list(normalized[1].get_flattened_data())
    host_edges = list(
        normalized[0].filter(ImageFilter.FIND_EDGES).get_flattened_data()
    )
    client_edges = list(
        normalized[1].filter(ImageFilter.FIND_EDGES).get_flattened_data()
    )
    return {
        "grayscale_correlation": _correlation(host_gray, client_gray),
        "edge_correlation": _correlation(host_edges, client_edges),
    }


def capture_matched_camera_pair(
    host_pipe: str,
    client_pipe: str,
    decor: dict[str, Any],
    anchor_position: list[float],
    evidence_dir: Path,
    run_index: int,
) -> dict[str, Any]:
    target = matched_camera_target(decor, anchor_position)
    target_x, target_y = target["position"]
    host_camera = focus_camera(host_pipe, target_x, target_y)
    client_camera = focus_camera(client_pipe, target_x, target_y)
    if (
        abs(host_camera["center_x"] - client_camera["center_x"]) > 0.05
        or abs(host_camera["center_y"] - client_camera["center_y"]) > 0.05
    ):
        raise VerifyFailure(
            "matched camera centers differ: "
            f"host={host_camera} client={client_camera}"
        )
    evidence_dir.mkdir(parents=True, exist_ok=True)
    host_path = evidence_dir / f"run-{run_index:02d}-host.png"
    client_path = evidence_dir / f"run-{run_index:02d}-client.png"
    last: dict[str, Any] = {}
    for attempt in range(1, 4):
        host_camera = focus_camera(host_pipe, target_x, target_y)
        client_camera = focus_camera(client_pipe, target_x, target_y)
        time.sleep(1.0)
        screenshots = {
            "host": multiplayer_frame_capture.capture_game_backbuffer(
                host_pipe,
                host_path,
                maximum_dominant_fraction=0.97,
            ),
            "client": multiplayer_frame_capture.capture_game_backbuffer(
                client_pipe,
                client_path,
                maximum_dominant_fraction=0.97,
            ),
        }
        host_quality = screenshots["host"]["quality"]
        client_quality = screenshots["client"]["quality"]
        if (
            host_quality["width"] != client_quality["width"]
            or host_quality["height"] != client_quality["height"]
        ):
            raise VerifyFailure(
                f"matched captures have different dimensions: {screenshots}"
            )
        correlation = matched_frame_correlation(host_path, client_path)
        last = {
            "attempt": attempt,
            "correlation": correlation,
            "screenshots": screenshots,
        }
        if (
            correlation["grayscale_correlation"] >= 0.75
            and correlation["edge_correlation"] >= 0.65
        ):
            return {
                "target": target,
                "host_camera": host_camera,
                "client_camera": client_camera,
                "capture_attempts": attempt,
                "frame_correlation": correlation,
                "screenshots": screenshots,
            }
    raise VerifyFailure(
        "matched camera screenshots did not align their world landmarks "
        f"after three captures: {last}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify exact host/client seeded Boneyard decor tables and matched "
            "native backbuffers across fresh isolated runs."
        )
    )
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--instance-prefix", default="run-static-layout")
    parser.add_argument("--game-directory", type=Path)
    parser.add_argument("--exact-mod-id", default="sample.lua.camera_lab")
    parser.add_argument("--output", type=Path, default=RUNTIME_OUTPUT)
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=ROOT / "runtime" / "run_static_layout_sync",
    )
    parser.add_argument("--layout-timeout", type=float, default=45.0)
    args = parser.parse_args()
    if args.runs < 1 or args.runs > 10:
        parser.error("--runs must be between 1 and 10")
    if args.layout_timeout <= 0:
        parser.error("--layout-timeout must be positive")
    return args


def main() -> int:
    args = parse_args()
    output_path = args.output.resolve()
    evidence_dir = args.evidence_dir.resolve()
    result: dict[str, Any] = {
        "ok": False,
        "runs_requested": args.runs,
        "instance_prefix": args.instance_prefix,
        "transport": "loopback_udp",
        "runs": [],
    }

    def persist() -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    try:
        for run_index in range(1, args.runs + 1):
            run_result: dict[str, Any] = {"run_index": run_index}
            result["runs"].append(run_result)
            instance_prefix = f"{args.instance_prefix}-run{run_index:02d}"
            host_port, client_port = select_available_windows_udp_ports(2)
            launch: dict[str, object] = {}
            identities: list[dict[str, Any]] = []
            try:
                launch = launch_pair(
                    instance_prefix=instance_prefix,
                    host_port=host_port,
                    client_port=client_port,
                    game_directory=args.game_directory,
                    exact_mod_id=args.exact_mod_id,
                )
                run_result["launch"] = launch
                reported_ids = game_process_ids(launch)
                if len(reported_ids) != 2:
                    raise VerifyFailure(
                        f"pair launch did not report exactly two PIDs: {reported_ids}"
                    )
                identities = expected_owned_process_identities(
                    launch, instance_prefix
                )
                identities = capture_owned_process_identities(identities)
                run_result["owned_processes"] = identities

                host_pipe = str(
                    launch.get("hostLuaPipe")
                    or f"SolomonDarkModLoader_LuaExec_{instance_prefix}-host"
                )
                client_pipe = str(
                    launch.get("clientLuaPipe")
                    or f"SolomonDarkModLoader_LuaExec_{instance_prefix}-client"
                )
                local_sync.HOST_PIPE = host_pipe
                local_sync.CLIENT_PIPE = client_pipe
                disable_bots()
                run_result["hub_remote_materialized"] = {
                    "host": wait_for_remote(
                        host_pipe, CLIENT_ID, CLIENT_NAME, "hub"
                    ),
                    "client": wait_for_remote(
                        client_pipe, HOST_ID, HOST_NAME, "hub"
                    ),
                }
                run_result["host_run_entry"] = (
                    start_host_testrun_and_wait_for_clients()
                )
                layout_sync = wait_for_layout_sync(
                    host_pipe,
                    client_pipe,
                    timeout=args.layout_timeout,
                )
                run_result["layout_sync"] = layout_sync
                run_result["matched_camera"] = capture_matched_camera_pair(
                    host_pipe,
                    client_pipe,
                    layout_sync["decor_tables"]["host"],
                    [
                        (
                            float(layout_sync["host"]["player_x"])
                            + float(layout_sync["client"]["player_x"])
                        )
                        / 2.0,
                        (
                            float(layout_sync["host"]["player_y"])
                            + float(layout_sync["client"]["player_y"])
                        )
                        / 2.0,
                    ],
                    evidence_dir,
                    run_index,
                )
                run_result["ok"] = True
            finally:
                if identities:
                    run_result["cleanup"] = stop_owned_processes(identities)
                persist()

        nonces = [
            run["layout_sync"]["host"]["local_run_nonce"]
            for run in result["runs"]
        ]
        decor_digests = [
            (
                run["layout_sync"]["host"]["boneyard_tree_digest"],
                run["layout_sync"]["host"]["boneyard_compact_digest"],
            )
            for run in result["runs"]
        ]
        if len(set(nonces)) != len(nonces):
            raise VerifyFailure(f"fresh runs reused a run seed: {nonces}")
        if len(set(decor_digests)) != len(decor_digests):
            raise VerifyFailure(
                f"fresh run decor tables were unexpectedly reused: {decor_digests}"
            )
        result["fresh_run_summary"] = {
            "run_nonces": nonces,
            "decor_digests": decor_digests,
            "all_run_seeds_distinct": True,
            "all_decor_tables_distinct_between_runs": True,
        }
        result["ok"] = True
        persist()
        print(
            json.dumps(
                {
                    "ok": True,
                    "output": str(output_path),
                    "runs": args.runs,
                    "screenshots": [
                        run["matched_camera"]["screenshots"]
                        for run in result["runs"]
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except Exception as exc:
        result["error"] = str(exc)
        persist()
        print(
            json.dumps(
                {
                    "ok": False,
                    "output": str(output_path),
                    "error": str(exc),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
