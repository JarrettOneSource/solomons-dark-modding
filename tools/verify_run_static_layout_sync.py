#!/usr/bin/env python3
"""Verify that host/client testrun static layout generation matches."""

from __future__ import annotations

import json
import time

from verify_local_multiplayer_sync import (
    CLIENT_PIPE,
    CLIENT_ID,
    CLIENT_NAME,
    HOST_PIPE,
    HOST_ID,
    HOST_NAME,
    ROOT,
    VerifyFailure,
    disable_bots,
    launch_pair,
    lua,
    parse_key_values,
    start_host_testrun_and_wait_for_clients,
    stop_games,
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
-- the transient actor lane above. First compare the complete materialized
-- scenery graph by type/geometry. Then compare Tree/Scrub art selectors while
-- deliberately excluding their independently ticking sway values.
local TREE_TYPE_ID = 2001
local SCRUB_TYPE_ID = 2062
local scenery_list = world_address + off("actor_world_scenery_object_list")
local scenery_count = read_i32(scenery_list + off("pointer_list_count"))
local scenery_items = read_ptr(scenery_list + off("pointer_list_items"))
local scenery_rows = {}
local boneyard_trees = {}
local max_scenery = scenery_items ~= 0
  and math.min(math.max(scenery_count, 0), 4096)
  or 0
for index = 0, max_scenery - 1 do
  local scenery = read_ptr(scenery_items + (index * 4))
  if scenery ~= 0 then
    local type_id = read_u32(scenery + off("game_object_type_id"))
    local x = qf(read_f(scenery + off("actor_position_x")))
    local y = qf(read_f(scenery + off("actor_position_y")))
    local radius = qf(read_f(scenery + off("actor_collision_radius")))
    local materialization_key =
      read_i32(scenery + off("boneyard_scenery_materialization_key"))
    table.insert(scenery_rows, {type_id, x, y, radius, materialization_key})

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
        x,
        y,
        radius,
        materialization_key,
        variant,
        overlay_variant,
        overlay_enabled,
      })
    end
  end
end
local function sort_rows(rows, field_count)
  table.sort(rows, function(a, b)
    for index = 1, field_count do
      if a[index] ~= b[index] then return a[index] < b[index] end
    end
    return false
  end)
end
local function digest_rows(rows, prefix)
  local values = prefix
  for _, row in ipairs(rows) do
    for _, value in ipairs(row) do table.insert(values, value) end
  end
  return digest_values(values)
end
sort_rows(scenery_rows, 5)
sort_rows(boneyard_trees, 8)
emit("boneyard_scenery_count", scenery_count)
emit("boneyard_scenery_digest", hx(
  digest_rows(scenery_rows, {scenery_count, #scenery_rows})))
emit("boneyard_tree_count", #boneyard_trees)
emit("boneyard_tree_digest", hx(digest_rows(boneyard_trees, {#boneyard_trees})))
for index, tree in ipairs(boneyard_trees) do
  emit("boneyard_tree." .. index .. ".type_id", tree[1])
  emit("boneyard_tree." .. index .. ".x_q10", tree[2])
  emit("boneyard_tree." .. index .. ".y_q10", tree[3])
  emit("boneyard_tree." .. index .. ".radius_q10", tree[4])
  emit("boneyard_tree." .. index .. ".materialization_key", tree[5])
  emit("boneyard_tree." .. index .. ".variant", tree[6])
  emit("boneyard_tree." .. index .. ".overlay_variant", tree[7])
  emit("boneyard_tree." .. index .. ".overlay_enabled", tree[8])
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
    return parse_key_values(lua(pipe_name, STATIC_LAYOUT_LUA, timeout=15.0))


def integer(row: dict[str, str], key: str) -> int:
    try:
        return int(float(row.get(key, "0") or "0"))
    except ValueError:
        return 0


def layouts_match(host: dict[str, str], client: dict[str, str]) -> bool:
    required_equal = [
        "local_run_nonce",
        "circle_mask4_count",
        "circle_mask4_digest",
        "shape_count",
        "shape_digest",
        "static_actor_count",
        "static_actor_digest",
        "boneyard_scenery_count",
        "boneyard_scenery_digest",
        "boneyard_tree_count",
        "boneyard_tree_digest",
    ]
    return (
        host.get("scene") == "testrun"
        and client.get("scene") == "testrun"
        and host.get("local_run_nonce") not in ("", "0x00000000")
        and client.get("local_run_nonce") == host.get("local_run_nonce")
        and integer(host, "circle_count") > 0
        and integer(host, "circle_mask4_count") > 0
        and integer(host, "boneyard_scenery_count") > 0
        and integer(host, "boneyard_tree_count") > 0
        and integer(client, "replicated_run_static_count") >= integer(host, "static_actor_count")
        and integer(client, "replicated_matched_actor_count") >= integer(host, "static_actor_count")
        and all(host.get(key) == client.get(key) for key in required_equal)
    )


def wait_for_layout_sync(timeout: float = 30.0) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last_host: dict[str, str] = {}
    last_client: dict[str, str] = {}
    while time.monotonic() < deadline:
        last_host = values(HOST_PIPE)
        last_client = values(CLIENT_PIPE)
        if layouts_match(last_host, last_client):
            return {"host": last_host, "client": last_client}
        time.sleep(0.25)
    raise VerifyFailure(f"run static layout did not converge: host={last_host} client={last_client}")


def main() -> int:
    result: dict[str, object] = {"ok": False}
    try:
        stop_games()
        result["launch"] = launch_pair()
        disable_bots()
        result["hub_remote_materialized"] = {
            "host": wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "hub"),
            "client": wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "hub"),
        }
        result["host_run_entry"] = start_host_testrun_and_wait_for_clients()
        result["layout_sync"] = wait_for_layout_sync()
        result["ok"] = True
        RUNTIME_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        result["error"] = str(exc)
        RUNTIME_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1
    finally:
        stop_games()


if __name__ == "__main__":
    raise SystemExit(main())
