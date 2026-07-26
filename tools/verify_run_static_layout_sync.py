#!/usr/bin/env python3
"""Verify that host/client testrun static layout generation matches."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

import multiplayer_frame_capture
import verify_local_multiplayer_sync as local_sync
from PIL import Image, ImageChops, ImageFilter, ImageOps
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
    place_player,
    select_available_windows_udp_ports,
    start_host_testrun_and_wait_for_clients,
    wait_for_remote,
)


RUNTIME_OUTPUT = ROOT / "runtime" / "run_static_layout_sync_verification.json"
CAPTURE_FRAMES_PER_PEER = 16
CAPTURE_ATTEMPTS_PER_FRAME = 8
CAPTURE_RETRY_DELAY_SECONDS = 0.25
STABLE_PROFILE_CAPTURE_ATTEMPTS = 3
STABLE_PROFILE_CAPTURE_RETRY_DELAY_SECONDS = 0.25
DECOR_ROI_HALF_EXTENT = 120.0
MINIMUM_DECOR_ROI_CLEARANCE = 120.0
STABLE_TEMPORAL_CHANNEL_RANGE = 2
STABLE_CROSS_PEER_CHANNEL_DELTA = 2
ACTOR_LIGHT_PARKING_OFFSET_X = -320.0
ACTOR_LIGHT_PARKING_OFFSET_Y = 0.0
MINIMUM_PLAYER_LIGHT_DISTANCE = 310.0
TARGET_PLAYER_LIGHT_DISTANCE = 320.0
MAXIMUM_PLAYER_LIGHT_DISTANCE = 330.0
NATIVE_COLLISION_RADIAL_TOLERANCE = 25.0
MINIMUM_MATCHED_AREA_SEPARATION = 250.0


class ParkingSelectionFailure(VerifyFailure):
    """Raised when every ranked nav sample settles outside the spatial gate."""


def capture_information_frame(
    pipe_name: str,
    output_path: Path,
    *,
    capture: Callable[..., dict[str, Any]] = (
        multiplayer_frame_capture.capture_game_backbuffer
    ),
    attempts: int = CAPTURE_ATTEMPTS_PER_FRAME,
    retry_delay: float = CAPTURE_RETRY_DELAY_SECONDS,
) -> tuple[Path, dict[str, Any]]:
    """Capture one informative frame despite a bounded native damage flash."""

    if attempts <= 0:
        raise ValueError("capture attempts must be positive")

    rejected_capture_errors: list[str] = []
    for capture_attempt in range(1, attempts + 1):
        candidate_path = (
            output_path
            if capture_attempt == 1
            else output_path.with_name(
                f"{output_path.stem}-retry-{capture_attempt:02d}"
                f"{output_path.suffix}"
            )
        )
        try:
            evidence = capture(
                pipe_name,
                candidate_path,
                maximum_dominant_fraction=0.99,
            )
            evidence["capture_attempt"] = capture_attempt
            evidence["low_information_retries"] = len(
                rejected_capture_errors
            )
            evidence["rejected_capture_errors"] = rejected_capture_errors
            return candidate_path, evidence
        except VerifyFailure as error:
            message = str(error)
            if "blank or low-information" not in message:
                raise
            rejected_capture_errors.append(message)
            if capture_attempt < attempts:
                time.sleep(retry_delay)

    raise VerifyFailure(
        "D3D9 backbuffer stayed blank or low-information through bounded "
        f"layout-frame retries: pipe={pipe_name} attempts={attempts} "
        f"errors={rejected_capture_errors}"
    )


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

local marker_tint_scale_address =
  tonumber(sd.debug.resolve_game_address(0x00785D34)) or 0
local marker_tint_bias_address =
  tonumber(sd.debug.resolve_game_address(0x00784E20)) or 0
local marker_tint_scale_bits = read_u32(marker_tint_scale_address)
local marker_tint_bias_low_bits = read_u32(marker_tint_bias_address)
local marker_tint_bias_high_bits = read_u32(marker_tint_bias_address + 4)
local arena_ambient_kind =
  read_u8(world_address + off("boneyard_arena_ambient_kind"))
local presentation_values = {
  local_run_nonce,
  arena_ambient_kind,
  0x00471805,
  0,
  0x004723C2,
  0,
  0x004712BB,
  marker_tint_scale_bits,
  0,
  marker_tint_bias_low_bits,
  marker_tint_bias_high_bits,
  0x004726E3,
  marker_tint_scale_bits,
  0,
  marker_tint_bias_low_bits,
  marker_tint_bias_high_bits,
}
emit("boneyard_presentation_run_seed", hx(local_run_nonce))
emit("boneyard_presentation_arena_ambient_kind", arena_ambient_kind)
emit("boneyard_presentation_compact_ambient_result", 0)
emit("boneyard_presentation_secondary_ambient_result", 0)
emit("boneyard_presentation_marker_scale_bits", hx(marker_tint_scale_bits))
emit("boneyard_presentation_marker_sign_mode", 0)
emit("boneyard_presentation_marker_bias_low_bits", hx(marker_tint_bias_low_bits))
emit("boneyard_presentation_marker_bias_high_bits", hx(marker_tint_bias_high_bits))
emit("boneyard_presentation_digest", hx(digest_values(presentation_values)))

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
        read_u32(scenery + off("boneyard_scenery_common_scalar")),
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
local scenery_render_rows = {}
for _, scenery in ipairs(scenery_rows) do
  local render_row = {}
  for field_index, value in ipairs(scenery) do
    -- Common scenery +0xCC is read only by Tree's complex-lighting overlay.
    -- Include it for Tree while retaining it only diagnostically for families
    -- whose complete renderer set does not consume the word.
    if field_index ~= 12 or scenery[2] == TREE_TYPE_ID then
      append(render_row, value)
    end
  end
  table.insert(scenery_render_rows, render_row)
end
emit("boneyard_scenery_digest", hx(
  digest_rows(scenery_render_rows, {scenery_count, #scenery_rows})))
emit("boneyard_scenery_diagnostic_digest", hx(
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
    append(render_row, tree[19])
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
  digest_rows(boneyard_trees, {#boneyard_trees}, 19)))
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
  emit("boneyard_tree." .. index .. ".common_scalar_bits", hx(tree[19]))
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
            "common_scalar_bits",
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
            "common_scalar_bits": u32(
                row[prefix + "common_scalar_bits"]
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
    presentation_inputs = {
        "run_seed": u32(row["boneyard_presentation_run_seed"]),
        "arena_ambient_kind": integer(
            row, "boneyard_presentation_arena_ambient_kind"
        ),
        "ambient_spawn_results": {
            "compact": integer(
                row, "boneyard_presentation_compact_ambient_result"
            ),
            "secondary": integer(
                row, "boneyard_presentation_secondary_ambient_result"
            ),
        },
        "marker_tint": {
            "primary_salt": 0x004712BB,
            "secondary_salt": 0x004726E3,
            "scale_bits": u32(
                row["boneyard_presentation_marker_scale_bits"]
            ),
            "sign_mode": integer(
                row, "boneyard_presentation_marker_sign_mode"
            ),
            "bias_bits": [
                u32(row["boneyard_presentation_marker_bias_low_bits"]),
                u32(row["boneyard_presentation_marker_bias_high_bits"]),
            ],
        },
        "digest": row["boneyard_presentation_digest"],
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
        "presentation_inputs": presentation_inputs,
    }


def render_decor_tables(decor: dict[str, Any]) -> dict[str, Any]:
    scenery: list[dict[str, Any]] = []
    for row in decor["scenery"]:
        render_row = dict(row)
        if row["type_id"] != 2001:
            render_row.pop("common_scalar_bits", None)
        scenery.append(render_row)
    return {
        "scenery": scenery,
        "trees": decor["trees"],
        "roads": decor["roads"],
        "fences": decor["fences"],
        "terrain": decor["terrain"],
        "compact": decor["compact"],
        "presentation_inputs": decor["presentation_inputs"],
    }


def verified_render_profile_inputs(
    profile: dict[str, str],
) -> dict[str, int]:
    names = (
        "complex_lighting",
        "complex_shadows",
        "multiple_shadows",
        "zoom_effects",
        "enhanced_effects",
    )
    return {
        name: int(profile[f"after.{name}"])
        for name in names
    }


def full_render_input_digest(
    render_decor: dict[str, Any],
    render_profile: dict[str, str],
) -> str:
    payload = {
        "native_order_render_decor": render_decor,
        "verified_render_profile": verified_render_profile_inputs(
            render_profile
        ),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
        "boneyard_presentation_digest",
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
            host_render_decor = render_decor_tables(host_decor)
            client_render_decor = render_decor_tables(client_decor)
            mismatched_render_tables = [
                table_name
                for table_name in host_render_decor
                if (
                    host_render_decor[table_name]
                    != client_render_decor[table_name]
                )
            ]
            if mismatched_render_tables:
                raise VerifyFailure(
                    "decor digests matched but exact render-input tables "
                    "differed: " + ", ".join(mismatched_render_tables)
                )
            return {
                "host": last_host,
                "client": last_client,
                "decor_tables": {
                    "host": host_decor,
                    "client": client_decor,
                },
                "render_decor_tables": {
                    "host": host_render_decor,
                    "client": client_render_decor,
                },
                "render_decor_tables_exact": True,
                "diagnostic_decor_tables_exact": (
                    host_decor == client_decor
                ),
            }
        time.sleep(0.25)
    raise VerifyFailure(f"run static layout did not converge: host={last_host} client={last_client}")


def _normalize_windows_path(path: str) -> str:
    return path.replace("/", "\\").rstrip("\\").casefold()


def expected_owned_process_identities(
    launch: dict[str, object],
    instance_prefix: str,
    runtime_root: Path = ROOT / "runtime",
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
            runtime_root
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


def matched_camera_targets(
    decor: dict[str, Any],
    actor_positions: list[list[float]],
    actor_parking_samples: list[list[float]] | None = None,
) -> list[dict[str, Any]]:
    categories = (
        (
            "trees",
            "scenery",
            [
                row
                for row in decor["trees"]
                if row["type_id"] == 2001
            ],
        ),
        (
            "large-rocks",
            "compact",
            [
                row
                for row in decor["compact"]
                if 21 <= row["type_id"] <= 24
            ],
        ),
        (
            "ground-clutter",
            "compact",
            [
                row
                for row in decor["compact"]
                if 0 <= row["type_id"] <= 20 or row["type_id"] == 30
            ],
        ),
        (
            "scenery-props",
            "scenery",
            [
                row
                for row in decor["scenery"]
                if row["type_id"]
                in {
                    2009,
                    2029,
                    2040,
                    2061,
                    2062,
                }
            ],
        ),
    )
    normalized_actors = [
        [float(position[0]), float(position[1])]
        for position in actor_positions
        if (
            len(position) == 2
            and math.isfinite(float(position[0]))
            and math.isfinite(float(position[1]))
        )
    ]
    all_decor_positions = [
        [
            float(row["position"][0]),
            float(row["position"][1]),
        ]
        for table_name in ("scenery", "compact")
        for row in decor[table_name]
        if (
            len(row.get("position", ())) == 2
            and math.isfinite(float(row["position"][0]))
            and math.isfinite(float(row["position"][1]))
        )
    ]
    if not all_decor_positions:
        raise VerifyFailure("matched-camera capture lacks decor positions")
    min_world_x = min(position[0] for position in all_decor_positions)
    max_world_x = max(position[0] for position in all_decor_positions)
    min_world_y = min(position[1] for position in all_decor_positions)
    max_world_y = max(position[1] for position in all_decor_positions)
    camera_safe_margin = 650.0
    world_center = [
        sum(position[axis] for position in all_decor_positions)
        / len(all_decor_positions)
        for axis in (0, 1)
    ]
    plans: list[dict[str, Any]] = []
    for family, source, candidates in categories:
        parking_cache: dict[
            int,
            tuple[list[float], float] | None,
        ] = {}

        def parking_sample(
            row: dict[str, Any],
        ) -> tuple[list[float], float] | None:
            cache_key = id(row)
            if cache_key in parking_cache:
                return parking_cache[cache_key]
            if actor_parking_samples is None:
                return None
            target_x = float(row["position"][0])
            target_y = float(row["position"][1])
            eligible: list[tuple[list[float], float]] = []
            for sample in actor_parking_samples:
                if len(sample) < 2:
                    continue
                sample_x = float(sample[0])
                sample_y = float(sample[1])
                if not all(
                    math.isfinite(value)
                    for value in (sample_x, sample_y)
                ):
                    continue
                horizontal = abs(sample_x - target_x)
                vertical = abs(sample_y - target_y)
                target_gap = math.hypot(horizontal, vertical)
                if (
                    max(horizontal, vertical) - DECOR_ROI_HALF_EXTENT
                    >= MINIMUM_DECOR_ROI_CLEARANCE
                    and MINIMUM_PLAYER_LIGHT_DISTANCE
                    <= target_gap
                    <= MAXIMUM_PLAYER_LIGHT_DISTANCE
                ):
                    eligible.append(
                        ([sample_x, sample_y], target_gap)
                    )
            if not eligible:
                parking_cache[cache_key] = None
                return None
            goal_x, goal_y = actor_light_parking_goal(
                target_x,
                target_y,
            )
            parking_cache[cache_key] = min(
                eligible,
                key=lambda item: (
                    abs(item[1] - TARGET_PLAYER_LIGHT_DISTANCE),
                    math.hypot(
                        item[0][0] - goal_x,
                        item[0][1] - goal_y,
                    ),
                    item[0][0],
                    item[0][1],
                ),
            )
            return parking_cache[cache_key]

        def actor_clearance(row: dict[str, Any]) -> float:
            position = row["position"]
            return (
                min(math.dist(position, actor) for actor in normalized_actors)
                if normalized_actors
                else math.inf
            )

        valid = [
            row
            for row in candidates
            if (
                len(row.get("position", ())) == 2
                and math.isfinite(float(row["position"][0]))
                and math.isfinite(float(row["position"][1]))
                and actor_clearance(row) >= 1000.0
                and min_world_x + camera_safe_margin
                <= float(row["position"][0])
                <= max_world_x - camera_safe_margin
                and min_world_y + camera_safe_margin
                <= float(row["position"][1])
                <= max_world_y - camera_safe_margin
                and (
                    actor_parking_samples is None
                    or parking_sample(row) is not None
                )
            )
        ]
        if not valid:
            raise VerifyFailure(
                f"matched-camera capture lacks actor-clear {family} "
                f"candidates"
            )

        def density_key(row: dict[str, Any]) -> tuple[int, int, float, int]:
            position = row["position"]
            near = sum(
                math.dist(position, other) <= 160.0
                for other in all_decor_positions
            )
            neighborhood = sum(
                math.dist(position, other) <= 300.0
                for other in all_decor_positions
            )
            return (
                near,
                neighborhood,
                -math.dist(position, world_center),
                int(row.get("native_index", -1)),
            )

        ranked = sorted(valid, key=density_key, reverse=True)
        distinct: list[dict[str, Any]] = []
        for entity in ranked:
            target_position = [
                float(entity["position"][0]),
                float(entity["position"][1]),
            ]
            if any(
                math.dist(target_position, target["position"])
                < MINIMUM_MATCHED_AREA_SEPARATION
                for target in distinct
            ):
                continue
            selected_parking = parking_sample(entity)
            distinct.append(
                {
                    "family": family,
                    "source": source,
                    "position": target_position,
                    "entity": entity,
                    "actor_clearance": actor_clearance(entity),
                    "decor_density_160": density_key(entity)[0],
                    "decor_density_300": density_key(entity)[1],
                    "camera_safe_margin": camera_safe_margin,
                    "preselected_actor_parking_sample": (
                        {
                            "position": selected_parking[0],
                            "target_distance": selected_parking[1],
                        }
                        if selected_parking is not None
                        else None
                    ),
                }
            )
        if not distinct:
            raise VerifyFailure(
                f"matched-camera capture lacks a distinct {family} area"
            )
        plans.append(
            {
                "family": family,
                "source": source,
                "minimum_area_separation": (
                    MINIMUM_MATCHED_AREA_SEPARATION
                ),
                "candidates": distinct,
            }
        )
    return plans


def first_launch_control_picker_worker(
    pipe_names: list[str],
    stop_event: threading.Event,
    records: dict[str, dict[str, Any]],
) -> None:
    if stop_event.wait(20.0):
        return
    code = """
local snap = sd.ui.get_snapshot()
local surface = type(snap) == "table" and tostring(snap.surface_id or "") or ""
print("surface=" .. surface)
if surface == "control_scheme_picker" then
  local ok, request = sd.ui.activate_action(
    "control_scheme_picker.select_wasd",
    "control_scheme_picker")
  print("accepted=" .. tostring(ok))
  print("request=" .. tostring(request))
end
"""
    pending = set(pipe_names)
    while pending and not stop_event.is_set():
        for pipe_name in list(pending):
            if stop_event.is_set():
                break
            try:
                row = parse_key_values(lua(pipe_name, code, timeout=2.0))
                records[pipe_name] = row
                if (
                    row.get("surface") == "control_scheme_picker"
                    and row.get("accepted") == "true"
                ):
                    records[pipe_name]["dispatched"] = True
                    pending.remove(pipe_name)
            except Exception as exc:
                records[pipe_name] = {"last_error": str(exc)}
        stop_event.wait(0.2)


def configure_visual_gate_render_profile(
    pipe_name: str,
    *,
    complex_lighting: bool = True,
) -> dict[str, str]:
    values = parse_key_values(
        lua(
            pipe_name,
            """
local slots = {
  complex_lighting = { address = 0x00B3BCA8, value = __COMPLEX_LIGHTING__ },
  complex_shadows = { address = 0x00B3BCA9, value = __COMPLEX_SHADOWS__ },
  multiple_shadows = { address = 0x00B3BCAA, value = __MULTIPLE_SHADOWS__ },
  zoom_effects = { address = 0x00B3BCAC, value = __ZOOM_EFFECTS__ },
  enhanced_effects = { address = 0x00B3BCAD, value = 0 },
}
for name, slot in pairs(slots) do
  slot.live = assert(sd.debug.resolve_game_address(slot.address))
  print("address." .. name .. "=" .. tostring(slot.live))
  print("before." .. name .. "=" .. tostring(sd.debug.read_u8(slot.live)))
end
for _, slot in pairs(slots) do
  assert(sd.debug.write_u8(slot.live, slot.value))
end
for name, slot in pairs(slots) do
  print("expected." .. name .. "=" .. tostring(slot.value))
  print("after." .. name .. "=" .. tostring(sd.debug.read_u8(slot.live)))
end
""".replace(
                "__COMPLEX_LIGHTING__",
                "1" if complex_lighting else "0",
            ).replace(
                "__COMPLEX_SHADOWS__",
                "1" if complex_lighting else "0",
            ).replace(
                "__MULTIPLE_SHADOWS__",
                "1" if complex_lighting else "0",
            ).replace(
                "__ZOOM_EFFECTS__",
                "1" if complex_lighting else "0",
            ),
            timeout=10.0,
        )
    )
    after = {
        key: value
        for key, value in values.items()
        if key.startswith("after.")
    }
    expected = {
        key.removeprefix("expected."): value
        for key, value in values.items()
        if key.startswith("expected.")
    }
    actual = {
        key.removeprefix("after."): value
        for key, value in after.items()
    }
    if not expected or actual != expected:
        raise VerifyFailure(
            f"visual-gate render profile did not converge on {pipe_name}: "
            f"{values}"
        )
    return values


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


def roi_excluded_pixel_mask(
    image_size: tuple[int, int],
    roi_bounds: tuple[int, int, int, int],
    excluded_rectangles: list[list[int]] | None,
) -> list[bool]:
    roi_left, roi_top, roi_right, roi_bottom = roi_bounds
    roi_width = roi_right - roi_left
    roi_height = roi_bottom - roi_top
    mask = [False] * (roi_width * roi_height)
    if not excluded_rectangles:
        return mask
    image_width, image_height = image_size
    for rectangle in excluded_rectangles:
        if len(rectangle) != 4:
            raise VerifyFailure(
                f"invalid pixel exclusion rectangle: {rectangle}"
            )
        left, top, right, bottom = (int(value) for value in rectangle)
        left = max(0, min(image_width, left))
        top = max(0, min(image_height, top))
        right = max(0, min(image_width, right))
        bottom = max(0, min(image_height, bottom))
        if right <= left or bottom <= top:
            continue
        for y in range(max(top, roi_top), min(bottom, roi_bottom)):
            row_offset = (y - roi_top) * roi_width
            for x in range(max(left, roi_left), min(right, roi_right)):
                mask[row_offset + x - roi_left] = True
    return mask


def exact_decor_pixel_comparison(
    host_path: Path,
    client_path: Path,
    camera: dict[str, Any],
    evidence_prefix: Path,
    world_half_extent: float = DECOR_ROI_HALF_EXTENT,
    excluded_rectangles: list[list[int]] | None = None,
) -> dict[str, Any]:
    with Image.open(host_path) as host_source:
        host = host_source.convert("RGB")
    with Image.open(client_path) as client_source:
        client = client_source.convert("RGB")
    if host.size != client.size:
        raise VerifyFailure(
            f"matched captures have different dimensions: "
            f"host={host.size} client={client.size}"
        )

    camera_width = float(camera["width"])
    camera_height = float(camera["height"])
    if camera_width <= 0.0 or camera_height <= 0.0:
        raise VerifyFailure(f"invalid camera dimensions: {camera}")
    half_width_pixels = max(
        1,
        round(world_half_extent * host.width / camera_width),
    )
    half_height_pixels = max(
        1,
        round(world_half_extent * host.height / camera_height),
    )
    center_x = host.width // 2
    center_y = host.height // 2
    bounds = (
        max(0, center_x - half_width_pixels),
        max(0, center_y - half_height_pixels),
        min(host.width, center_x + half_width_pixels),
        min(host.height, center_y + half_height_pixels),
    )
    excluded_mask = roi_excluded_pixel_mask(
        host.size,
        bounds,
        excluded_rectangles,
    )
    host_roi = host.crop(bounds)
    client_roi = client.crop(bounds)
    host_pixels = list(host_roi.get_flattened_data())
    client_pixels = list(client_roi.get_flattened_data())
    for index, excluded in enumerate(excluded_mask):
        if excluded:
            host_pixels[index] = (0, 0, 0)
            client_pixels[index] = (0, 0, 0)
    host_roi.putdata(host_pixels)
    client_roi.putdata(client_pixels)
    difference = ImageChops.difference(host_roi, client_roi)
    difference_pixels = list(difference.get_flattened_data())
    differing_pixel_count = sum(
        pixel != (0, 0, 0) for pixel in difference_pixels
    )
    maximum_channel_delta = max(
        (max(pixel) for pixel in difference_pixels),
        default=0,
    )
    host_visible_pixels = sum(max(pixel) > 8 for pixel in host_pixels)
    client_visible_pixels = sum(max(pixel) > 8 for pixel in client_pixels)
    host_unique_colors = len(set(host_pixels))
    client_unique_colors = len(set(client_pixels))

    host_roi_path = Path(f"{evidence_prefix}-host-decor-roi.png")
    client_roi_path = Path(f"{evidence_prefix}-client-decor-roi.png")
    difference_path = Path(f"{evidence_prefix}-decor-diff.png")
    host_roi.save(host_roi_path)
    client_roi.save(client_roi_path)
    difference.save(difference_path)
    host_hash = hashlib.sha256(host_roi.tobytes()).hexdigest()
    client_hash = hashlib.sha256(client_roi.tobytes()).hexdigest()
    sufficient_visual_content = (
        host_visible_pixels >= 512
        and client_visible_pixels >= 512
        and host_unique_colors >= 32
        and client_unique_colors >= 32
    )
    return {
        "roi_bounds": list(bounds),
        "roi_world_half_extent": world_half_extent,
        "pixel_count": host_roi.width * host_roi.height,
        "excluded_pixel_count": sum(excluded_mask),
        "excluded_rectangles": excluded_rectangles or [],
        "differing_pixel_count": differing_pixel_count,
        "maximum_channel_delta": maximum_channel_delta,
        "host_pixel_sha256": host_hash,
        "client_pixel_sha256": client_hash,
        "pixel_hashes_match": host_hash == client_hash,
        "host_visible_pixels": host_visible_pixels,
        "client_visible_pixels": client_visible_pixels,
        "host_unique_colors": host_unique_colors,
        "client_unique_colors": client_unique_colors,
        "sufficient_visual_content": sufficient_visual_content,
        "exact_match": (
            differing_pixel_count == 0
            and host_hash == client_hash
            and sufficient_visual_content
        ),
        "host_roi_path": str(host_roi_path),
        "client_roi_path": str(client_roi_path),
        "difference_path": str(difference_path),
    }


def exact_stable_decor_pixel_comparison(
    host_paths: list[Path],
    client_paths: list[Path],
    camera: dict[str, Any],
    evidence_prefix: Path,
    world_half_extent: float = DECOR_ROI_HALF_EXTENT,
    excluded_rectangles: list[list[int]] | None = None,
) -> dict[str, Any]:
    if len(host_paths) != len(client_paths) or len(host_paths) < 3:
        raise VerifyFailure(
            "stable decor comparison requires at least three paired frames"
        )

    frames: dict[str, list[Image.Image]] = {"host": [], "client": []}
    for peer, paths in (("host", host_paths), ("client", client_paths)):
        for path in paths:
            with Image.open(path) as source:
                frames[peer].append(source.convert("RGB"))
    sizes = {
        image.size
        for peer_frames in frames.values()
        for image in peer_frames
    }
    if len(sizes) != 1:
        raise VerifyFailure(
            f"stable decor captures have different dimensions: {sizes}"
        )
    width, height = next(iter(sizes))

    camera_width = float(camera["width"])
    camera_height = float(camera["height"])
    if camera_width <= 0.0 or camera_height <= 0.0:
        raise VerifyFailure(f"invalid camera dimensions: {camera}")
    half_width_pixels = max(
        1,
        round(world_half_extent * width / camera_width),
    )
    half_height_pixels = max(
        1,
        round(world_half_extent * height / camera_height),
    )
    center_x = width // 2
    center_y = height // 2
    bounds = (
        max(0, center_x - half_width_pixels),
        max(0, center_y - half_height_pixels),
        min(width, center_x + half_width_pixels),
        min(height, center_y + half_height_pixels),
    )
    pixels = {
        peer: [
            list(image.crop(bounds).get_flattened_data())
            for image in peer_frames
        ]
        for peer, peer_frames in frames.items()
    }
    pixel_count = len(pixels["host"][0])
    excluded_mask = roi_excluded_pixel_mask(
        (width, height),
        bounds,
        excluded_rectangles,
    )
    stable_mask_pixels: list[int] = []
    stable_host_pixels: list[tuple[int, int, int]] = []
    stable_client_pixels: list[tuple[int, int, int]] = []
    stable_difference_pixels: list[tuple[int, int, int]] = []
    host_hash = hashlib.sha256()
    client_hash = hashlib.sha256()
    stable_pixel_count = 0
    stable_visible_pixel_count = 0
    differing_stable_pixel_count = 0
    maximum_stable_channel_delta = 0
    maximum_stable_envelope_gap = 0
    stable_host_colors: set[tuple[int, int, int]] = set()
    stable_client_colors: set[tuple[int, int, int]] = set()

    for index in range(pixel_count):
        if excluded_mask[index]:
            stable_mask_pixels.append(0)
            stable_host_pixels.append((0, 0, 0))
            stable_client_pixels.append((0, 0, 0))
            stable_difference_pixels.append((0, 0, 0))
            continue
        host_samples = [row[index] for row in pixels["host"]]
        client_samples = [row[index] for row in pixels["client"]]
        host_minimum = tuple(
            min(sample[channel] for sample in host_samples)
            for channel in range(3)
        )
        host_maximum = tuple(
            max(sample[channel] for sample in host_samples)
            for channel in range(3)
        )
        client_minimum = tuple(
            min(sample[channel] for sample in client_samples)
            for channel in range(3)
        )
        client_maximum = tuple(
            max(sample[channel] for sample in client_samples)
            for channel in range(3)
        )
        stable = (
            max(
                host_maximum[channel] - host_minimum[channel]
                for channel in range(3)
            )
            <= STABLE_TEMPORAL_CHANNEL_RANGE
            and max(
                client_maximum[channel] - client_minimum[channel]
                for channel in range(3)
            )
            <= STABLE_TEMPORAL_CHANNEL_RANGE
        )
        if not stable:
            stable_mask_pixels.append(0)
            stable_host_pixels.append((0, 0, 0))
            stable_client_pixels.append((0, 0, 0))
            stable_difference_pixels.append((0, 0, 0))
            continue

        host_pixel = host_samples[0]
        client_pixel = client_samples[0]
        delta = tuple(
            abs(host_value - client_value)
            for host_value, client_value in zip(
                host_pixel,
                client_pixel,
                strict=True,
            )
        )
        stable_mask_pixels.append(255)
        stable_host_pixels.append(host_pixel)
        stable_client_pixels.append(client_pixel)
        stable_difference_pixels.append(delta)
        stable_pixel_count += 1
        stable_host_colors.add(host_pixel)
        stable_client_colors.add(client_pixel)
        if max(host_pixel) > 8 or max(client_pixel) > 8:
            stable_visible_pixel_count += 1
        if host_pixel != client_pixel:
            differing_stable_pixel_count += 1
        maximum_stable_channel_delta = max(
            maximum_stable_channel_delta,
            max(delta),
        )
        envelope_gap = max(
            max(
                host_minimum[channel] - client_maximum[channel],
                client_minimum[channel] - host_maximum[channel],
                0,
            )
            for channel in range(3)
        )
        maximum_stable_envelope_gap = max(
            maximum_stable_envelope_gap,
            envelope_gap,
        )
        coordinate = index.to_bytes(4, "little", signed=False)
        host_hash.update(coordinate)
        host_hash.update(bytes(host_pixel))
        client_hash.update(coordinate)
        client_hash.update(bytes(client_pixel))

    roi_width = bounds[2] - bounds[0]
    roi_height = bounds[3] - bounds[1]
    stable_mask = Image.new("L", (roi_width, roi_height))
    stable_host = Image.new("RGB", (roi_width, roi_height))
    stable_client = Image.new("RGB", (roi_width, roi_height))
    stable_difference = Image.new("RGB", (roi_width, roi_height))
    stable_mask.putdata(stable_mask_pixels)
    stable_host.putdata(stable_host_pixels)
    stable_client.putdata(stable_client_pixels)
    stable_difference.putdata(stable_difference_pixels)
    stable_mask_path = Path(f"{evidence_prefix}-stable-mask.png")
    stable_host_path = Path(f"{evidence_prefix}-host-stable-decor.png")
    stable_client_path = Path(f"{evidence_prefix}-client-stable-decor.png")
    stable_difference_path = Path(
        f"{evidence_prefix}-stable-decor-diff.png"
    )
    stable_mask.save(stable_mask_path)
    stable_host.save(stable_host_path)
    stable_client.save(stable_client_path)
    stable_difference.save(stable_difference_path)

    minimum_stable_visible_pixel_count = 1024
    minimum_stable_unique_colors = 128
    stable_hashes_match = host_hash.digest() == client_hash.digest()
    sufficient_stable_content = (
        stable_visible_pixel_count >= minimum_stable_visible_pixel_count
        and len(stable_host_colors) >= minimum_stable_unique_colors
        and len(stable_client_colors) >= minimum_stable_unique_colors
    )
    exact_match = (
        differing_stable_pixel_count == 0
        and stable_hashes_match
        and sufficient_stable_content
    )
    bounded_match = (
        maximum_stable_envelope_gap
        <= STABLE_CROSS_PEER_CHANNEL_DELTA
        and sufficient_stable_content
    )
    return {
        "roi_bounds": list(bounds),
        "roi_world_half_extent": world_half_extent,
        "pixel_count": pixel_count,
        "excluded_pixel_count": sum(excluded_mask),
        "excluded_rectangles": excluded_rectangles or [],
        "stable_pixel_count": stable_pixel_count,
        "stable_pixel_fraction": stable_pixel_count / pixel_count,
        "stable_pixel_fraction_is_diagnostic_only": True,
        "stable_visible_pixel_count": stable_visible_pixel_count,
        "minimum_stable_visible_pixel_count": (
            minimum_stable_visible_pixel_count
        ),
        "stable_host_unique_colors": len(stable_host_colors),
        "stable_client_unique_colors": len(stable_client_colors),
        "minimum_stable_unique_colors": minimum_stable_unique_colors,
        "maximum_stable_temporal_channel_range": (
            STABLE_TEMPORAL_CHANNEL_RANGE
        ),
        "maximum_allowed_stable_cross_peer_envelope_gap": (
            STABLE_CROSS_PEER_CHANNEL_DELTA
        ),
        "differing_stable_pixel_count": differing_stable_pixel_count,
        "maximum_stable_channel_delta": maximum_stable_channel_delta,
        "maximum_stable_envelope_gap": maximum_stable_envelope_gap,
        "host_stable_pixel_sha256": host_hash.hexdigest(),
        "client_stable_pixel_sha256": client_hash.hexdigest(),
        "stable_pixel_hashes_match": stable_hashes_match,
        "sufficient_stable_content": sufficient_stable_content,
        "actors_and_ui_excluded": {
            "method": (
                "intersection of pixels staying within a two-value "
                "per-channel temporal band across native backbuffers on "
                "each peer, compared by their cross-peer temporal-envelope "
                "gap rather than capture order"
            ),
            "frames_per_peer": len(host_paths),
        },
        "exact_match": exact_match,
        "bounded_match": bounded_match,
        "stable_mask_path": str(stable_mask_path),
        "host_stable_decor_path": str(stable_host_path),
        "client_stable_decor_path": str(stable_client_path),
        "stable_difference_path": str(stable_difference_path),
    }


def exact_temporal_envelope_decor_pixel_comparison(
    host_paths: list[Path],
    client_paths: list[Path],
    camera: dict[str, Any],
    evidence_prefix: Path,
    world_half_extent: float = DECOR_ROI_HALF_EXTENT,
    excluded_rectangles: list[list[int]] | None = None,
) -> dict[str, Any]:
    if len(host_paths) != len(client_paths) or len(host_paths) < 3:
        raise VerifyFailure(
            "temporal decor comparison requires at least three paired frames"
        )
    frames: dict[str, list[Image.Image]] = {"host": [], "client": []}
    for peer, paths in (("host", host_paths), ("client", client_paths)):
        for path in paths:
            with Image.open(path) as source:
                frames[peer].append(source.convert("RGB"))
    sizes = {
        image.size
        for peer_frames in frames.values()
        for image in peer_frames
    }
    if len(sizes) != 1:
        raise VerifyFailure(
            f"temporal decor captures have different dimensions: {sizes}"
        )
    width, height = next(iter(sizes))
    camera_width = float(camera["width"])
    camera_height = float(camera["height"])
    if camera_width <= 0.0 or camera_height <= 0.0:
        raise VerifyFailure(f"invalid camera dimensions: {camera}")
    half_width_pixels = max(
        1,
        round(world_half_extent * width / camera_width),
    )
    half_height_pixels = max(
        1,
        round(world_half_extent * height / camera_height),
    )
    center_x = width // 2
    center_y = height // 2
    bounds = (
        max(0, center_x - half_width_pixels),
        max(0, center_y - half_height_pixels),
        min(width, center_x + half_width_pixels),
        min(height, center_y + half_height_pixels),
    )
    pixels = {
        peer: [
            list(image.crop(bounds).get_flattened_data())
            for image in peer_frames
        ]
        for peer, peer_frames in frames.items()
    }
    pixel_count = len(pixels["host"][0])
    excluded_mask = roi_excluded_pixel_mask(
        (width, height),
        bounds,
        excluded_rectangles,
    )
    minima: dict[str, list[tuple[int, int, int]]] = {
        "host": [],
        "client": [],
    }
    maxima: dict[str, list[tuple[int, int, int]]] = {
        "host": [],
        "client": [],
    }
    gap_pixels: list[tuple[int, int, int]] = []
    differing_envelope_pixel_count = 0
    maximum_envelope_channel_gap = 0
    for index in range(pixel_count):
        if excluded_mask[index]:
            for peer in ("host", "client"):
                minima[peer].append((0, 0, 0))
                maxima[peer].append((0, 0, 0))
            gap_pixels.append((0, 0, 0))
            continue
        for peer in ("host", "client"):
            samples = [frame[index] for frame in pixels[peer]]
            minima[peer].append(
                tuple(min(sample[channel] for sample in samples) for channel in range(3))
            )
            maxima[peer].append(
                tuple(max(sample[channel] for sample in samples) for channel in range(3))
            )
        gap = tuple(
            max(
                0,
                max(minima["host"][index][channel], minima["client"][index][channel])
                - min(maxima["host"][index][channel], maxima["client"][index][channel]),
            )
            for channel in range(3)
        )
        gap_pixels.append(gap)
        if gap != (0, 0, 0):
            differing_envelope_pixel_count += 1
        maximum_envelope_channel_gap = max(
            maximum_envelope_channel_gap,
            max(gap),
        )

    visible_counts = {
        peer: sum(max(pixel) > 8 for pixel in maxima[peer])
        for peer in ("host", "client")
    }
    unique_colors = {
        peer: len(set(maxima[peer]))
        for peer in ("host", "client")
    }
    # Complex lighting intentionally makes some Boneyard regions nearly
    # black.  Requiring 512 lit pixels plus 32 distinct colors rejects an
    # empty capture while retaining those stock dark Tree silhouettes.
    minimum_visible_pixel_count = 512
    minimum_unique_colors = 32
    sufficient_visual_content = (
        all(
            count >= minimum_visible_pixel_count
            for count in visible_counts.values()
        )
        and all(
            count >= minimum_unique_colors
            for count in unique_colors.values()
        )
    )

    roi_size = (bounds[2] - bounds[0], bounds[3] - bounds[1])
    artifact_paths: dict[str, str] = {}
    for peer in ("host", "client"):
        for bound_name, values in (
            ("minimum", minima[peer]),
            ("maximum", maxima[peer]),
        ):
            image = Image.new("RGB", roi_size)
            image.putdata(values)
            path = Path(
                f"{evidence_prefix}-{peer}-temporal-{bound_name}.png"
            )
            image.save(path)
            artifact_paths[f"{peer}_{bound_name}_path"] = str(path)
    gap_image = Image.new("RGB", roi_size)
    gap_image.putdata(gap_pixels)
    gap_path = Path(f"{evidence_prefix}-temporal-envelope-gap.png")
    gap_image.save(gap_path)
    artifact_paths["gap_path"] = str(gap_path)

    return {
        "roi_bounds": list(bounds),
        "roi_world_half_extent": world_half_extent,
        "frames_per_peer": len(host_paths),
        "pixel_count": pixel_count,
        "excluded_pixel_count": sum(excluded_mask),
        "excluded_rectangles": excluded_rectangles or [],
        "differing_envelope_pixel_count": (
            differing_envelope_pixel_count
        ),
        "maximum_envelope_channel_gap": maximum_envelope_channel_gap,
        "host_visible_pixel_count": visible_counts["host"],
        "client_visible_pixel_count": visible_counts["client"],
        "minimum_visible_pixel_count": minimum_visible_pixel_count,
        "host_unique_colors": unique_colors["host"],
        "client_unique_colors": unique_colors["client"],
        "minimum_unique_colors": minimum_unique_colors,
        "sufficient_visual_content": sufficient_visual_content,
        "actors_and_ui_excluded": {
            "method": (
                "the live gate proves every local and replicated actor is "
                "outside the central decor ROI; optional explicit rectangles "
                "remain supported by the pixel comparator"
            ),
            "frames_per_peer": len(host_paths),
            "renderer_nameplate_rectangles": (
                excluded_rectangles or []
            ),
            "allowed_unexplained_channel_gap": 0,
        },
        "exact_match": (
            differing_envelope_pixel_count == 0
            and sufficient_visual_content
        ),
        **artifact_paths,
    }


def temporal_minimum_edge_comparison(
    host_paths: list[Path],
    client_paths: list[Path],
    camera: dict[str, Any],
    evidence_prefix: Path,
    world_half_extent: float = DECOR_ROI_HALF_EXTENT,
) -> dict[str, Any]:
    if len(host_paths) != len(client_paths) or len(host_paths) < 3:
        raise VerifyFailure(
            "temporal edge comparison requires at least three paired frames"
        )

    composites: dict[str, Image.Image] = {}
    for peer, paths in (("host", host_paths), ("client", client_paths)):
        with Image.open(paths[0]) as source:
            composite = source.convert("RGB")
        for path in paths[1:]:
            with Image.open(path) as source:
                composite = ImageChops.darker(
                    composite,
                    source.convert("RGB"),
                )
        composites[peer] = composite

    if composites["host"].size != composites["client"].size:
        raise VerifyFailure(
            "temporal edge captures have different dimensions: "
            f"host={composites['host'].size} "
            f"client={composites['client'].size}"
        )
    width, height = composites["host"].size
    camera_width = float(camera["width"])
    camera_height = float(camera["height"])
    if camera_width <= 0.0 or camera_height <= 0.0:
        raise VerifyFailure(f"invalid camera dimensions: {camera}")
    half_width_pixels = max(
        1,
        round(world_half_extent * width / camera_width),
    )
    half_height_pixels = max(
        1,
        round(world_half_extent * height / camera_height),
    )
    center_x = width // 2
    center_y = height // 2
    bounds = (
        max(0, center_x - half_width_pixels),
        max(0, center_y - half_height_pixels),
        min(width, center_x + half_width_pixels),
        min(height, center_y + half_height_pixels),
    )

    edge_masks: dict[str, Image.Image] = {}
    artifact_paths: dict[str, str] = {}
    for peer in ("host", "client"):
        minimum = composites[peer].crop(bounds)
        minimum_path = Path(
            f"{evidence_prefix}-{peer}-temporal-minimum-edge-source.png"
        )
        minimum.save(minimum_path)
        artifact_paths[f"{peer}_minimum_path"] = str(minimum_path)
        grayscale = ImageOps.autocontrast(
            ImageOps.grayscale(minimum),
            cutoff=1,
        ).filter(ImageFilter.GaussianBlur(1.0))
        edges = grayscale.filter(ImageFilter.FIND_EDGES).point(
            lambda value: 255 if value >= 40 else 0
        )
        edge_path = Path(f"{evidence_prefix}-{peer}-edge-mask.png")
        edges.save(edge_path)
        edge_masks[peer] = edges
        artifact_paths[f"{peer}_edge_path"] = str(edge_path)

    host_pixels = list(edge_masks["host"].get_flattened_data())
    client_pixels = list(edge_masks["client"].get_flattened_data())
    host_dilated = list(
        edge_masks["host"]
        .filter(ImageFilter.MaxFilter(5))
        .get_flattened_data()
    )
    client_dilated = list(
        edge_masks["client"]
        .filter(ImageFilter.MaxFilter(5))
        .get_flattened_data()
    )
    host_edge_count = sum(value != 0 for value in host_pixels)
    client_edge_count = sum(value != 0 for value in client_pixels)
    host_matched = sum(
        value != 0 and client_dilated[index] != 0
        for index, value in enumerate(host_pixels)
    )
    client_matched = sum(
        value != 0 and host_dilated[index] != 0
        for index, value in enumerate(client_pixels)
    )
    total_edge_count = host_edge_count + client_edge_count
    symmetric_match_fraction = (
        (host_matched + client_matched) / total_edge_count
        if total_edge_count
        else 0.0
    )
    minimum_edge_count = 2_000
    minimum_symmetric_match_fraction = 0.985

    mismatch = Image.new("RGB", edge_masks["host"].size)
    mismatch.putdata(
        [
            (
                (255, 0, 0)
                if host_value and not client_dilated[index]
                else (
                    (0, 128, 255)
                    if client_pixels[index] and not host_dilated[index]
                    else (0, 0, 0)
                )
            )
            for index, host_value in enumerate(host_pixels)
        ]
    )
    mismatch_path = Path(f"{evidence_prefix}-edge-mismatch.png")
    mismatch.save(mismatch_path)
    artifact_paths["mismatch_path"] = str(mismatch_path)

    sufficient_content = (
        host_edge_count >= minimum_edge_count
        and client_edge_count >= minimum_edge_count
    )
    return {
        "roi_bounds": list(bounds),
        "roi_world_half_extent": world_half_extent,
        "frames_per_peer": len(host_paths),
        "host_edge_count": host_edge_count,
        "client_edge_count": client_edge_count,
        "minimum_edge_count": minimum_edge_count,
        "host_matched_edge_count": host_matched,
        "client_matched_edge_count": client_matched,
        "symmetric_match_fraction": symmetric_match_fraction,
        "minimum_symmetric_match_fraction": (
            minimum_symmetric_match_fraction
        ),
        "tolerance_radius_pixels": 2,
        "sufficient_content": sufficient_content,
        "exact_input_derivation": (
            "per-channel temporal minimum for persistent geometry, 1% "
            "autocontrast, one-pixel Gaussian blur, FIND_EDGES, threshold 40"
        ),
        "ok": (
            sufficient_content
            and symmetric_match_fraction
            >= minimum_symmetric_match_fraction
        ),
        **artifact_paths,
    }


def actor_light_parking_goal(
    target_x: float,
    target_y: float,
) -> tuple[float, float]:
    return (
        target_x + ACTOR_LIGHT_PARKING_OFFSET_X,
        target_y + ACTOR_LIGHT_PARKING_OFFSET_Y,
    )


def actor_light_parking_geometry(
    target_x: float,
    target_y: float,
    parking_x: float,
    parking_y: float,
) -> dict[str, Any]:
    values = (target_x, target_y, parking_x, parking_y)
    if not all(math.isfinite(value) for value in values):
        raise VerifyFailure(f"invalid actor-light parking geometry: {values}")
    horizontal = abs(parking_x - target_x)
    vertical = abs(parking_y - target_y)
    target_distance = math.hypot(horizontal, vertical)
    decor_roi_clearance = (
        max(horizontal, vertical) - DECOR_ROI_HALF_EXTENT
    )
    if decor_roi_clearance < MINIMUM_DECOR_ROI_CLEARANCE:
        raise VerifyFailure(
            "actor-light parking point intersects the decor exclusion zone: "
            f"target=({target_x},{target_y}) "
            f"parking=({parking_x},{parking_y}) "
            f"clearance={decor_roi_clearance}"
        )
    if not (
        MINIMUM_PLAYER_LIGHT_DISTANCE
        <= target_distance
        <= MAXIMUM_PLAYER_LIGHT_DISTANCE
    ):
        raise VerifyFailure(
            "actor-light parking point is outside player-light radial band: "
            f"target=({target_x},{target_y}) "
            f"parking=({parking_x},{parking_y}) "
            f"distance={target_distance}"
        )
    shared_position = [parking_x, parking_y]
    return {
        "host": shared_position,
        "client": list(shared_position),
        "target_distances": {
            "host": target_distance,
            "client": target_distance,
        },
        "decor_roi_clearance": decor_roi_clearance,
        "actor_separation": 0.0,
    }


def settled_actor_parking_geometry(
    target_x: float,
    target_y: float,
    owner_positions: dict[str, tuple[float, float] | list[float]],
) -> dict[str, Any]:
    if set(owner_positions) != {"host", "client"}:
        raise VerifyFailure(
            "settled actor-light geometry requires host and client owners"
        )
    target_distances: dict[str, float] = {}
    decor_roi_clearances: dict[str, float] = {}
    for owner, position in owner_positions.items():
        if len(position) < 2:
            raise VerifyFailure(
                f"invalid settled actor-light position: {owner}={position}"
            )
        x = float(position[0])
        y = float(position[1])
        if not all(
            math.isfinite(value)
            for value in (target_x, target_y, x, y)
        ):
            raise VerifyFailure(
                f"invalid settled actor-light position: {owner}={position}"
            )
        horizontal = abs(x - target_x)
        vertical = abs(y - target_y)
        target_distance = math.hypot(horizontal, vertical)
        decor_roi_clearance = (
            max(horizontal, vertical) - DECOR_ROI_HALF_EXTENT
        )
        if decor_roi_clearance < MINIMUM_DECOR_ROI_CLEARANCE:
            raise VerifyFailure(
                "settled actor-light position intersects the decor "
                f"exclusion zone: owner={owner} "
                f"target=({target_x},{target_y}) "
                f"position=({x},{y}) clearance={decor_roi_clearance}"
            )
        minimum_settled_distance = (
            MINIMUM_PLAYER_LIGHT_DISTANCE
            - NATIVE_COLLISION_RADIAL_TOLERANCE
        )
        maximum_settled_distance = (
            MAXIMUM_PLAYER_LIGHT_DISTANCE
            + NATIVE_COLLISION_RADIAL_TOLERANCE
        )
        if not (
            minimum_settled_distance
            <= target_distance
            <= maximum_settled_distance
        ):
            raise VerifyFailure(
                "settled actor-light position is outside player-light "
                f"radial band: owner={owner} "
                f"target=({target_x},{target_y}) "
                f"position=({x},{y}) distance={target_distance}"
            )
        target_distances[owner] = target_distance
        decor_roi_clearances[owner] = decor_roi_clearance
    host = owner_positions["host"]
    client = owner_positions["client"]
    return {
        "owner_positions": {
            "host": [float(host[0]), float(host[1])],
            "client": [float(client[0]), float(client[1])],
        },
        "target_distances": target_distances,
        "decor_roi_clearances": decor_roi_clearances,
        "settled_target_distance_range": [
            MINIMUM_PLAYER_LIGHT_DISTANCE
            - NATIVE_COLLISION_RADIAL_TOLERANCE,
            MAXIMUM_PLAYER_LIGHT_DISTANCE
            + NATIVE_COLLISION_RADIAL_TOLERANCE,
        ],
        "owner_separation": math.hypot(
            float(host[0]) - float(client[0]),
            float(host[1]) - float(client[1]),
        ),
        "native_collision_displacement_allowed": True,
    }


def nav_traversable_positions(pipe_name: str) -> list[list[float]]:
    code = """
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local grid = sd.debug.get_nav_grid(1)
local scene = sd.world.get_scene()
local player = sd.player.get_state()
local scene_world =
  tonumber(scene and scene.world_address) or
  tonumber(player and player.world_address) or 0
local grid_world = tonumber(grid and grid.world_address) or 0
emit("scene_world", scene_world)
emit("grid_world", grid_world)
if type(grid) ~= "table" or grid.valid == false or
    type(grid.cells) ~= "table" or scene_world == 0 or
    grid_world ~= scene_world then
  emit("available", false)
  return
end
local positions = {}
for _, cell in ipairs(grid.cells) do
  for _, sample in ipairs(
      type(cell) == "table" and cell.samples or {}) do
    local x = tonumber(sample and sample.world_x)
    local y = tonumber(sample and sample.world_y)
    if sample and sample.traversable and x ~= nil and y ~= nil then
      table.insert(positions, { x = x, y = y })
    end
  end
end
emit("available", true)
emit("count", #positions)
for index, position in ipairs(positions) do
  emit("position." .. index .. ".x", position.x)
  emit("position." .. index .. ".y", position.y)
end
"""
    deadline = time.monotonic() + 6.0
    values: dict[str, str] = {}
    while time.monotonic() < deadline:
        values = parse_key_values(
            lua(
                pipe_name,
                code,
                timeout=10.0,
            )
        )
        if values.get("available") == "true":
            break
        time.sleep(0.25)
    if values.get("available") != "true":
        raise VerifyFailure(
            "native nav grid lacks traversable actor-light samples: "
            f"{values}"
        )
    count = int(values.get("count", "0"), 0)
    positions = [
        [
            float(values[f"position.{index}.x"]),
            float(values[f"position.{index}.y"]),
        ]
        for index in range(1, count + 1)
    ]
    if not positions:
        raise VerifyFailure("native nav grid has no traversable positions")
    return positions


def nav_actor_parking_positions(
    pipe_name: str,
    target_x: float,
    target_y: float,
    candidate_index: int = 1,
) -> dict[str, Any]:
    if candidate_index < 1:
        raise VerifyFailure(
            f"invalid actor-light parking candidate index: {candidate_index}"
        )
    goal_x, goal_y = actor_light_parking_goal(target_x, target_y)
    code = f"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local grid = sd.debug.get_nav_grid(1)
local scene = sd.world.get_scene()
local player = sd.player.get_state()
local scene_world =
  tonumber(scene and scene.world_address) or
  tonumber(player and player.world_address) or 0
local grid_world = tonumber(grid and grid.world_address) or 0
emit("scene_world", scene_world)
emit("grid_world", grid_world)
if type(grid) ~= "table" or grid.valid == false or
    type(grid.cells) ~= "table" or scene_world == 0 or
    grid_world ~= scene_world then
  emit("grid_available", false)
  emit("available", false)
  return
end
emit("grid_available", true)
local target_x = {target_x!r}
local target_y = {target_y!r}
local goal_x = {goal_x!r}
local goal_y = {goal_y!r}
local candidate_index = {candidate_index}
local candidates = {{}}
local traversable_count = 0
for _, cell in ipairs(grid.cells) do
  for _, sample in ipairs(
      type(cell) == "table" and cell.samples or {{}}) do
    local x = tonumber(sample and sample.world_x)
    local y = tonumber(sample and sample.world_y)
    if sample and sample.traversable and x ~= nil and y ~= nil then
      traversable_count = traversable_count + 1
      local dx = math.abs(x - target_x)
      local dy = math.abs(y - target_y)
      local target_gap = math.sqrt(dx * dx + dy * dy)
      local decor_roi_clearance =
        math.max(dx, dy) - {DECOR_ROI_HALF_EXTENT!r}
      if decor_roi_clearance >= {MINIMUM_DECOR_ROI_CLEARANCE!r} and
          target_gap >= {MINIMUM_PLAYER_LIGHT_DISTANCE!r} and
          target_gap <= {MAXIMUM_PLAYER_LIGHT_DISTANCE!r} then
        local goal_dx = x - goal_x
        local goal_dy = y - goal_y
        table.insert(candidates, {{
          x = x,
          y = y,
          target_gap = target_gap,
          radial_error =
            math.abs(target_gap - {TARGET_PLAYER_LIGHT_DISTANCE!r}),
          goal_gap = math.sqrt(goal_dx * goal_dx + goal_dy * goal_dy),
        }})
      end
    end
  end
end
table.sort(candidates, function(a, b)
  if a.radial_error ~= b.radial_error then
    return a.radial_error < b.radial_error
  end
  if a.goal_gap ~= b.goal_gap then return a.goal_gap < b.goal_gap end
  if a.x ~= b.x then return a.x < b.x end
  return a.y < b.y
end)
local shared = candidates[candidate_index]
emit("traversable_count", traversable_count)
emit("candidate_count", #candidates)
emit("candidate_index", candidate_index)
emit("goal.x", goal_x)
emit("goal.y", goal_y)
emit("available", shared ~= nil)
if shared ~= nil then
  emit("shared.x", shared.x)
  emit("shared.y", shared.y)
  emit("shared.target_gap", shared.target_gap)
  emit("shared.radial_error", shared.radial_error)
  emit("shared.goal_gap", shared.goal_gap)
end
"""
    deadline = time.monotonic() + 6.0
    values: dict[str, str] = {}
    while time.monotonic() < deadline:
        values = parse_key_values(
            lua(
                pipe_name,
                code,
                timeout=10.0,
            )
        )
        if values.get("available") == "true":
            break
        time.sleep(0.25)
    if values.get("available") != "true":
        raise VerifyFailure(
            "native nav grid lacks an actor-clear parking sample: "
            f"target=({target_x},{target_y}) result={values}"
        )
    parking = actor_light_parking_geometry(
        target_x,
        target_y,
        float(values["shared.x"]),
        float(values["shared.y"]),
    )
    return {
        **parking,
        "goal": [float(values["goal.x"]), float(values["goal.y"])],
        "goal_snap_distance": float(values["shared.goal_gap"]),
        "traversable_sample_count": int(
            values["traversable_count"],
            0,
        ),
        "actor_light_candidate_count": int(
            values["candidate_count"],
            0,
        ),
        "candidate_index": int(values["candidate_index"], 0),
        "source": (
            "ranked shared sd.debug.get_nav_grid(1) traversable sample, "
            "ordered by 320-unit target-radius error and then the fixed "
            "actor-light offset"
        ),
        "scene_world": int(values["scene_world"], 0),
        "grid_world": int(values["grid_world"], 0),
    }


def settle_shared_actor_parking(
    host_pipe: str,
    client_pipe: str,
    target_x: float,
    target_y: float,
    attempts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if attempts is None:
        attempts = []
    candidate_index = 1
    candidate_count: int | None = None
    while candidate_count is None or candidate_index <= candidate_count:
        parking = nav_actor_parking_positions(
            host_pipe,
            target_x,
            target_y,
            candidate_index,
        )
        reported_candidate_count = int(
            parking["actor_light_candidate_count"]
        )
        if candidate_count is None:
            candidate_count = reported_candidate_count
        elif reported_candidate_count != candidate_count:
            raise VerifyFailure(
                "native actor-light parking candidate set changed while "
                f"settling: expected={candidate_count} "
                f"actual={reported_candidate_count}"
            )
        owner_placements = {
            "host": place_player(
                host_pipe,
                *parking["host"],
                0.0,
            ),
            "client": place_player(
                client_pipe,
                *parking["client"],
                0.0,
            ),
        }
        settled_host_actor = (
            local_sync.wait_for_local_transform_settled(
                host_pipe,
                timeout=12.0,
                stable_seconds=2.0,
            )
        )
        settled_client_actor = (
            local_sync.wait_for_local_transform_settled(
                client_pipe,
                timeout=12.0,
                stable_seconds=2.0,
            )
        )
        attempt = {
            "candidate_index": candidate_index,
            "parking": parking,
            "owner_placements": owner_placements,
            "settled_owner_positions": {
                "host": list(settled_host_actor[:2]),
                "client": list(settled_client_actor[:2]),
            },
        }
        attempts.append(attempt)
        try:
            settled_actor_geometry = settled_actor_parking_geometry(
                target_x,
                target_y,
                {
                    "host": settled_host_actor[:2],
                    "client": settled_client_actor[:2],
                },
            )
        except VerifyFailure as error:
            attempt["ok"] = False
            attempt["error"] = str(error)
            candidate_index += 1
            continue
        attempt["ok"] = True
        attempt["settled_actor_geometry"] = settled_actor_geometry
        return {
            "parking": parking,
            "owner_placements": owner_placements,
            "settled_host_actor": settled_host_actor,
            "settled_client_actor": settled_client_actor,
            "settled_actor_geometry": settled_actor_geometry,
            "attempts": attempts,
        }
    errors = [attempt["error"] for attempt in attempts if not attempt["ok"]]
    raise ParkingSelectionFailure(
        "no native actor-light parking candidate remained valid after "
        f"placement: target=({target_x},{target_y}) "
        f"candidates={candidate_count} errors={errors}"
    )


def settle_matched_camera_target(
    host_pipe: str,
    client_pipe: str,
    target_plan: dict[str, Any],
    selected_target_positions: list[list[float]],
    attempts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if attempts is None:
        attempts = []
    for candidate in target_plan["candidates"]:
        position = [
            float(candidate["position"][0]),
            float(candidate["position"][1]),
        ]
        nearest_selected_distance = (
            min(
                math.dist(position, selected_position)
                for selected_position in selected_target_positions
            )
            if selected_target_positions
            else math.inf
        )
        target_attempt: dict[str, Any] = {
            "target": candidate,
            "parking_attempts": [],
            "nearest_selected_area_distance": (
                nearest_selected_distance
                if math.isfinite(nearest_selected_distance)
                else None
            ),
        }
        attempts.append(target_attempt)
        if (
            nearest_selected_distance
            < MINIMUM_MATCHED_AREA_SEPARATION
        ):
            target_attempt["ok"] = False
            target_attempt["skipped"] = True
            target_attempt["error"] = (
                "candidate overlaps a previously accepted matched-camera "
                f"area: distance={nearest_selected_distance}"
            )
            continue
        try:
            settled_parking = settle_shared_actor_parking(
                host_pipe,
                client_pipe,
                position[0],
                position[1],
                target_attempt["parking_attempts"],
            )
        except ParkingSelectionFailure as error:
            target_attempt["ok"] = False
            target_attempt["error"] = str(error)
            continue
        accepted_target = {
            **candidate,
            "nearest_selected_area_distance": (
                nearest_selected_distance
                if math.isfinite(nearest_selected_distance)
                else None
            ),
        }
        target_attempt["ok"] = True
        target_attempt["accepted"] = True
        return {
            "target": accepted_target,
            "settled_parking": settled_parking,
            "attempts": attempts,
        }
    errors = [
        attempt["error"]
        for attempt in attempts
        if not attempt.get("ok")
    ]
    raise VerifyFailure(
        "no placement-safe matched-camera target remained for "
        f"family={target_plan['family']} errors={errors}"
    )


def capture_stable_render_profile(
    capture_profile_frames: Callable[
        [str, list[dict[str, Any]]],
        tuple[list[Path], list[Path]],
    ],
    settled_camera: dict[str, float],
    evidence_prefix: Path,
    *,
    excluded_rectangles: list[list[int]] | None = None,
    attempts: int = STABLE_PROFILE_CAPTURE_ATTEMPTS,
    retry_delay: float = STABLE_PROFILE_CAPTURE_RETRY_DELAY_SECONDS,
) -> dict[str, Any]:
    """Retry a whole simple-lighting batch when it contains too little decor."""

    if attempts <= 0:
        raise ValueError("stable profile capture attempts must be positive")

    capture_batches: list[dict[str, Any]] = []
    for capture_attempt in range(1, attempts + 1):
        profile_slug = (
            "simple-lighting"
            if capture_attempt == 1
            else f"simple-lighting-retry-{capture_attempt:02d}"
        )
        frame_attempts: list[dict[str, Any]] = []
        host_paths, client_paths = capture_profile_frames(
            profile_slug,
            frame_attempts,
        )
        comparison_prefix = Path(
            f"{evidence_prefix}-{profile_slug}"
        )
        stable_pixels = exact_stable_decor_pixel_comparison(
            host_paths,
            client_paths,
            settled_camera,
            comparison_prefix,
            excluded_rectangles=excluded_rectangles,
        )
        edge_geometry = temporal_minimum_edge_comparison(
            host_paths,
            client_paths,
            settled_camera,
            comparison_prefix,
        )
        batch = {
            "capture_attempt": capture_attempt,
            "profile_slug": profile_slug,
            "screenshot_pairs": [
                attempt["screenshots"]
                for attempt in frame_attempts
            ],
            "stable_decor_pixels": stable_pixels,
            "temporal_minimum_edge_geometry": edge_geometry,
        }
        capture_batches.append(batch)
        if stable_pixels["sufficient_stable_content"]:
            return {
                "accepted_capture_attempt": capture_attempt,
                "capture_batches": capture_batches,
                "screenshot_pairs": batch["screenshot_pairs"],
                "stable_decor_pixels": stable_pixels,
                "temporal_minimum_edge_geometry": edge_geometry,
            }
        if capture_attempt < attempts:
            time.sleep(retry_delay)

    return {
        "accepted_capture_attempt": None,
        "capture_batches": capture_batches,
        "screenshot_pairs": capture_batches[-1]["screenshot_pairs"],
        "stable_decor_pixels": capture_batches[-1][
            "stable_decor_pixels"
        ],
        "temporal_minimum_edge_geometry": capture_batches[-1][
            "temporal_minimum_edge_geometry"
        ],
    }


def capture_matched_camera_areas(
    host_pipe: str,
    client_pipe: str,
    targets: list[dict[str, Any]],
    evidence_dir: Path,
    run_index: int,
    areas: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    if areas is None:
        areas = []
    selected_target_positions: list[list[float]] = []
    for area_index, target_plan in enumerate(targets, start=1):
        area_attempts: list[dict[str, Any]] = []
        area_result: dict[str, Any] = {
            "area_index": area_index,
            "family": target_plan["family"],
            "attempts": area_attempts,
            "target_attempts": [],
        }
        areas.append(area_result)
        settled_target = settle_matched_camera_target(
            host_pipe,
            client_pipe,
            target_plan,
            selected_target_positions,
            area_result["target_attempts"],
        )
        target = settled_target["target"]
        area_result["target"] = target
        target_x, target_y = target["position"]
        selected_target_positions.append([target_x, target_y])
        family_slug = str(target["family"]).replace("_", "-")
        settled_parking = settled_target["settled_parking"]
        area_result["parking_attempts"] = settled_parking["attempts"]
        parking = settled_parking["parking"]
        owner_placements = settled_parking["owner_placements"]
        settled_host_actor = settled_parking["settled_host_actor"]
        settled_client_actor = settled_parking["settled_client_actor"]
        settled_actor_geometry = settled_parking[
            "settled_actor_geometry"
        ]
        host_on_client = local_sync.wait_for_remote_convergence(
            client_pipe,
            HOST_ID,
            *settled_host_actor,
        )
        client_on_host = local_sync.wait_for_remote_convergence(
            host_pipe,
            CLIENT_ID,
            *settled_client_actor,
        )
        settled_host_camera = focus_camera(
            host_pipe,
            target_x,
            target_y,
        )
        settled_client_camera = focus_camera(
            client_pipe,
            target_x,
            target_y,
        )
        if (
            abs(
                settled_host_camera["center_x"]
                - settled_client_camera["center_x"]
            )
            > 0.05
            or abs(
                settled_host_camera["center_y"]
                - settled_client_camera["center_y"]
            )
            > 0.05
            or abs(
                settled_host_camera["width"]
                - settled_client_camera["width"]
            )
            > 0.05
            or abs(
                settled_host_camera["height"]
                - settled_client_camera["height"]
            )
            > 0.05
        ):
            raise VerifyFailure(
                "matched camera geometry differs: "
                f"host={settled_host_camera} "
                f"client={settled_client_camera}"
            )
        host_actor_view = local_sync.query(host_pipe)
        client_actor_view = local_sync.query(client_pipe)
        observed_actor_positions = {
            "host": {
                "local_host": [
                    float(host_actor_view["player.x"]),
                    float(host_actor_view["player.y"]),
                ],
                "remote_client": [
                    float(host_actor_view[f"peer.{CLIENT_ID}.x"]),
                    float(host_actor_view[f"peer.{CLIENT_ID}.y"]),
                ],
            },
            "client": {
                "local_client": [
                    float(client_actor_view["player.x"]),
                    float(client_actor_view["player.y"]),
                ],
                "remote_host": [
                    float(client_actor_view[f"peer.{HOST_ID}.x"]),
                    float(client_actor_view[f"peer.{HOST_ID}.y"]),
                ],
            },
        }
        decor_roi_half_extent = 120.0
        minimum_decor_roi_clearance = 120.0
        actor_decor_roi_clearances: dict[str, dict[str, float]] = {}
        expected_actor_positions = {
            "host": {
                "local_host": settled_host_actor[:2],
                "remote_client": settled_client_actor[:2],
            },
            "client": {
                "local_client": settled_client_actor[:2],
                "remote_host": settled_host_actor[:2],
            },
        }
        observed_actor_position_deltas: dict[str, dict[str, float]] = {}
        for observer, positions in observed_actor_positions.items():
            actor_decor_roi_clearances[observer] = {}
            observed_actor_position_deltas[observer] = {}
            for identity, position in positions.items():
                expected = expected_actor_positions[observer][identity]
                position_delta = math.hypot(
                    position[0] - expected[0],
                    position[1] - expected[1],
                )
                observed_actor_position_deltas[observer][
                    identity
                ] = position_delta
                if position_delta > 3.0:
                    raise VerifyFailure(
                        "actor moved away from the shared lighting position: "
                        f"family={target['family']} observer={observer} "
                        f"identity={identity} position={position} "
                        f"expected={expected} delta={position_delta}"
                    )
                horizontal = abs(position[0] - target_x)
                vertical = abs(position[1] - target_y)
                clearance = max(horizontal, vertical)
                clearance -= decor_roi_half_extent
                actor_decor_roi_clearances[observer][identity] = clearance
                if clearance < minimum_decor_roi_clearance:
                    raise VerifyFailure(
                        "actor remained too close to the matched decor ROI: "
                        f"family={target['family']} observer={observer} "
                        f"identity={identity} position={position} "
                        f"clearance={clearance}"
                    )
        area_result["excluded_actors"] = {
            "method": (
                "both owners are moved without damage through ranked "
                "traversable native-nav samples inside player-light range; "
                "native collision displacement is allowed, and the first "
                "sample where each settled owner plus replicated mirror "
                "remains valid must "
                "settle at least 120 world units beyond the central "
                "120-world-unit decor ROI"
            ),
            "parking": parking,
            "world_roi_excluded": True,
            "owner_placements": owner_placements,
            "settled_owner_positions": {
                "host": list(settled_host_actor[:2]),
                "client": list(settled_client_actor[:2]),
            },
            "settled_actor_geometry": settled_actor_geometry,
            "remote_convergence": {
                "host_on_client": host_on_client,
                "client_on_host": client_on_host,
            },
            "observed_positions": observed_actor_positions,
            "observed_position_deltas": observed_actor_position_deltas,
            "decor_roi_clearances": actor_decor_roi_clearances,
            "decor_roi_half_extent": decor_roi_half_extent,
            "minimum_decor_roi_clearance": (
                minimum_decor_roi_clearance
            ),
        }
        area_result["settled_camera"] = {
            "host": settled_host_camera,
            "client": settled_client_camera,
        }
        # Nav parking is the only geometry mutation.  The isolated launcher
        # keeps both players alive.  No damage or spell probe is allowed in the
        # decor capture phase.
        time.sleep(2.0)
        excluded_rectangles: list[list[int]] = []

        def capture_profile_frames(
            profile_slug: str,
            attempts: list[dict[str, Any]],
        ) -> tuple[list[Path], list[Path]]:
            host_paths: list[Path] = []
            client_paths: list[Path] = []
            for attempt in range(1, CAPTURE_FRAMES_PER_PEER + 1):
                host_camera = focus_camera(host_pipe, target_x, target_y)
                client_camera = focus_camera(
                    client_pipe,
                    target_x,
                    target_y,
                )
                if (
                    abs(
                        host_camera["center_x"]
                        - client_camera["center_x"]
                    )
                    > 0.05
                    or abs(
                        host_camera["center_y"]
                        - client_camera["center_y"]
                    )
                    > 0.05
                    or abs(
                        host_camera["width"] - client_camera["width"]
                    )
                    > 0.05
                    or abs(
                        host_camera["height"] - client_camera["height"]
                    )
                    > 0.05
                ):
                    raise VerifyFailure(
                        "matched camera geometry differs during capture: "
                        f"host={host_camera} client={client_camera}"
                    )
                time.sleep(0.5)
                evidence_prefix = (
                    evidence_dir
                    / (
                        f"run-{run_index:02d}-area-{area_index:02d}-"
                        f"{family_slug}-{profile_slug}-"
                        f"attempt-{attempt:02d}"
                    )
                )
                host_path = Path(f"{evidence_prefix}-host.png")
                client_path = Path(f"{evidence_prefix}-client.png")
                host_path, host_capture = capture_information_frame(
                    host_pipe,
                    host_path,
                )
                client_path, client_capture = capture_information_frame(
                    client_pipe,
                    client_path,
                )
                host_paths.append(host_path)
                client_paths.append(client_path)
                screenshots = {
                    "host": host_capture,
                    "client": client_capture,
                }
                host_quality = screenshots["host"]["quality"]
                client_quality = screenshots["client"]["quality"]
                if (
                    host_quality["width"] != client_quality["width"]
                    or host_quality["height"] != client_quality["height"]
                ):
                    raise VerifyFailure(
                        "matched captures have different dimensions: "
                        f"{screenshots}"
                    )
                exact_pixels = exact_decor_pixel_comparison(
                    host_path,
                    client_path,
                    host_camera,
                    evidence_prefix,
                    excluded_rectangles=excluded_rectangles,
                )
                attempts.append(
                    {
                        "attempt": attempt,
                        "render_profile": profile_slug,
                        "host_camera": host_camera,
                        "client_camera": client_camera,
                        "frame_correlation": matched_frame_correlation(
                            host_path,
                            client_path,
                        ),
                        "exact_decor_pixels": exact_pixels,
                        "screenshots": screenshots,
                    }
                )
            return host_paths, client_paths

        complex_host_paths, complex_client_paths = (
            capture_profile_frames("complex-lighting", area_attempts)
        )

        stable_prefix = (
            evidence_dir
            / (
                f"run-{run_index:02d}-area-{area_index:02d}-"
                f"{family_slug}"
            )
        )
        temporal_envelope = (
            exact_temporal_envelope_decor_pixel_comparison(
                complex_host_paths,
                complex_client_paths,
                settled_host_camera,
                stable_prefix,
                excluded_rectangles=excluded_rectangles,
            )
        )
        simple_profile = {
            "host": configure_visual_gate_render_profile(
                host_pipe,
                complex_lighting=False,
            ),
            "client": configure_visual_gate_render_profile(
                client_pipe,
                complex_lighting=False,
            ),
        }
        time.sleep(0.5)
        stable_profile = capture_stable_render_profile(
            capture_profile_frames,
            settled_host_camera,
            stable_prefix,
            excluded_rectangles=excluded_rectangles,
        )
        stable_pixels = stable_profile["stable_decor_pixels"]
        edge_geometry = stable_profile[
            "temporal_minimum_edge_geometry"
        ]
        restored_complex_profile = {
            "host": configure_visual_gate_render_profile(host_pipe),
            "client": configure_visual_gate_render_profile(client_pipe),
        }
        area_result.update(
            {
                "ok": (
                    stable_pixels["bounded_match"]
                    and temporal_envelope["exact_match"]
                    and edge_geometry["ok"]
                ),
                "host_camera": settled_host_camera,
                "client_camera": settled_client_camera,
                "complex_lighting_profile": {
                    "host": "configured before area capture",
                    "client": "configured before area capture",
                },
                "simple_lighting_profile": simple_profile,
                "restored_complex_lighting_profile": (
                    restored_complex_profile
                ),
                "stable_decor_pixels": stable_pixels,
                "temporal_decor_envelope": temporal_envelope,
                "temporal_minimum_edge_geometry": edge_geometry,
                "screenshots": area_attempts[0]["screenshots"],
                "screenshot_pairs": [
                    attempt["screenshots"]
                    for attempt in area_attempts
                ],
                "simple_lighting_screenshot_pairs": stable_profile[
                    "screenshot_pairs"
                ],
                "simple_lighting_capture_attempt": stable_profile[
                    "accepted_capture_attempt"
                ],
                "simple_lighting_capture_batches": stable_profile[
                    "capture_batches"
                ],
                "actors_and_ui_excluded": {
                    "actor_placement": area_result["excluded_actors"],
                    "pixel_comparison": temporal_envelope[
                        "actors_and_ui_excluded"
                    ],
                },
            }
        )
        if not stable_pixels["bounded_match"]:
            raise VerifyFailure(
                "matched-camera stable decor pixels differed: "
                f"family={target['family']} "
                f"stable={stable_pixels} "
                f"capture_batches={stable_profile['capture_batches']}"
            )
        if not temporal_envelope["exact_match"]:
            raise VerifyFailure(
                "matched-camera temporal decor pixels differed: "
                f"family={target['family']} "
                f"envelope={temporal_envelope}"
            )
        if not edge_geometry["ok"]:
            raise VerifyFailure(
                "matched-camera temporal-minimum decor edges differed: "
                f"family={target['family']} edges={edge_geometry}"
            )
    return areas


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
    parser.add_argument(
        "--runtime-root",
        type=Path,
        default=ROOT / "runtime",
        help="isolated launcher runtime root (including per-peer stages)",
    )
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
    runtime_root = args.runtime_root.resolve()
    result: dict[str, Any] = {
        "ok": False,
        "runs_requested": args.runs,
        "instance_prefix": args.instance_prefix,
        "transport": "loopback_udp",
        "runtime_root": str(runtime_root),
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
            host_pipe = ""
            picker_stop = threading.Event()
            picker_records: dict[str, dict[str, Any]] = {}
            picker_pipe_names = [
                (
                    "SolomonDarkModLoader_LuaExec_"
                    f"{instance_prefix}-{role}"
                )
                for role in ("host", "client")
            ]
            picker_thread = threading.Thread(
                target=first_launch_control_picker_worker,
                args=(picker_pipe_names, picker_stop, picker_records),
                name=f"{instance_prefix}-control-picker",
                daemon=True,
            )
            try:
                picker_thread.start()
                try:
                    launch = launch_pair(
                        instance_prefix=instance_prefix,
                        host_port=host_port,
                        client_port=client_port,
                        game_directory=args.game_directory,
                        runtime_root=runtime_root,
                        exact_mod_id=args.exact_mod_id,
                        god_mode=True,
                    )
                finally:
                    picker_stop.set()
                    picker_thread.join(timeout=5.0)
                    run_result["first_launch_control_picker"] = {
                        "records": picker_records,
                        "worker_stopped": not picker_thread.is_alive(),
                    }
                run_result["launch"] = launch
                reported_ids = game_process_ids(launch)
                if len(reported_ids) != 2:
                    raise VerifyFailure(
                        f"pair launch did not report exactly two PIDs: {reported_ids}"
                    )
                identities = expected_owned_process_identities(
                    launch, instance_prefix, runtime_root
                )
                identities = capture_owned_process_identities(identities)
                run_result["owned_processes"] = identities
                if launch.get("godModeEnabled") is not True:
                    raise VerifyFailure(
                        "layout-only launch did not enable its player "
                        "survival guard"
                    )
                run_result["layout_capture_survival_guard"] = {
                    "god_mode_enabled": True,
                    "scope": (
                        "sustain owner HP/MP only; decor generation and "
                        "render inputs remain stock"
                    ),
                }

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
                visual_gate_render_profile = {
                    "host": configure_visual_gate_render_profile(host_pipe),
                    "client": configure_visual_gate_render_profile(
                        client_pipe
                    ),
                }
                run_result["visual_gate_render_profile"] = (
                    visual_gate_render_profile
                )
                host_full_render_input_digest = full_render_input_digest(
                    layout_sync["render_decor_tables"]["host"],
                    visual_gate_render_profile["host"],
                )
                client_full_render_input_digest = full_render_input_digest(
                    layout_sync["render_decor_tables"]["client"],
                    visual_gate_render_profile["client"],
                )
                run_result["full_render_input_gate"] = {
                    "host_sha256": host_full_render_input_digest,
                    "client_sha256": client_full_render_input_digest,
                    "exact": (
                        host_full_render_input_digest
                        == client_full_render_input_digest
                    ),
                    "covers": [
                        "native-order decor entity tables",
                        "Tree/Scrub/Goodie presentation fields",
                        "Arena ambient suppression inputs",
                        "Arena marker tint inputs",
                        "verified render profile",
                    ],
                }
                if (
                    host_full_render_input_digest
                    != client_full_render_input_digest
                ):
                    raise VerifyFailure(
                        "full render-input digest differed after render "
                        "profile configuration"
                    )
                settled_host_actor = (
                    local_sync.wait_for_local_transform_settled(
                        host_pipe,
                        timeout=12.0,
                        stable_seconds=2.0,
                    )
                )
                settled_client_actor = (
                    local_sync.wait_for_local_transform_settled(
                        client_pipe,
                        timeout=12.0,
                        stable_seconds=2.0,
                    )
                )
                host_on_client = (
                    local_sync.wait_for_remote_convergence(
                        client_pipe,
                        HOST_ID,
                        *settled_host_actor,
                    )
                )
                client_on_host = (
                    local_sync.wait_for_remote_convergence(
                        host_pipe,
                        CLIENT_ID,
                        *settled_client_actor,
                    )
                )
                actor_positions = [
                    list(settled_host_actor[:2]),
                    list(settled_client_actor[:2]),
                ]
                run_result["visual_gate_actor_settle"] = {
                    "owner_positions": {
                        "host": actor_positions[0],
                        "client": actor_positions[1],
                    },
                    "remote_convergence": {
                        "host_on_client": host_on_client,
                        "client_on_host": client_on_host,
                    },
                    "preselection_movement_or_damage_injected": False,
                }
                actor_parking_samples = nav_traversable_positions(host_pipe)
                run_result["actor_light_parking_sample_count"] = len(
                    actor_parking_samples
                )
                targets = matched_camera_targets(
                    layout_sync["decor_tables"]["host"],
                    actor_positions,
                    actor_parking_samples,
                )
                run_result["matched_camera_targets"] = targets
                matched_areas: list[dict[str, Any]] = []
                run_result["matched_camera_areas"] = matched_areas
                capture_matched_camera_areas(
                    host_pipe,
                    client_pipe,
                    targets,
                    evidence_dir,
                    run_index,
                    matched_areas,
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
            tuple(
                run["layout_sync"]["host"][key]
                for key in (
                    "boneyard_scenery_digest",
                    "boneyard_tree_digest",
                    "boneyard_road_digest",
                    "boneyard_fence_digest",
                    "boneyard_terrain_digest",
                    "boneyard_compact_digest",
                )
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
                        area["screenshots"]
                        for run in result["runs"]
                        for area in run["matched_camera_areas"]
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
