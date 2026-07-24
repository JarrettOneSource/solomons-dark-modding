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
    local x_address = scenery + off("actor_position_x")
    local y_address = scenery + off("actor_position_y")
    local radius_address = scenery + off("actor_collision_radius")
    local x_value = read_f(x_address)
    local y_value = read_f(y_address)
    local radius_value = read_f(radius_address)
    local x = qf(x_value)
    local y = qf(y_value)
    local radius = qf(radius_value)
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
        read_u32(x_address),
        read_u32(y_address),
        read_u32(radius_address),
        materialization_key,
        variant,
        overlay_variant,
        overlay_enabled,
        x_value,
        y_value,
        radius_value,
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
local function digest_rows(rows, prefix, field_count)
  local values = prefix
  for _, row in ipairs(rows) do
    local count = field_count or #row
    for index = 1, count do table.insert(values, row[index]) end
  end
  return digest_values(values)
end
sort_rows(scenery_rows, 5)
sort_rows(boneyard_trees, 8)
emit("boneyard_scenery_count", scenery_count)
emit("boneyard_scenery_digest", hx(
  digest_rows(scenery_rows, {scenery_count, #scenery_rows})))
emit("boneyard_tree_count", #boneyard_trees)
emit("boneyard_tree_digest", hx(
  digest_rows(boneyard_trees, {#boneyard_trees}, 8)))
for index, tree in ipairs(boneyard_trees) do
  emit("boneyard_tree." .. index .. ".type_id", tree[1])
  emit("boneyard_tree." .. index .. ".x_bits", hx(tree[2]))
  emit("boneyard_tree." .. index .. ".y_bits", hx(tree[3]))
  emit("boneyard_tree." .. index .. ".radius_bits", hx(tree[4]))
  emit("boneyard_tree." .. index .. ".materialization_key", tree[5])
  emit("boneyard_tree." .. index .. ".variant", tree[6])
  emit("boneyard_tree." .. index .. ".overlay_variant", tree[7])
  emit("boneyard_tree." .. index .. ".overlay_enabled", tree[8])
  emit("boneyard_tree." .. index .. ".x", tree[9])
  emit("boneyard_tree." .. index .. ".y", tree[10])
  emit("boneyard_tree." .. index .. ".radius", tree[11])
end

-- RegionLayout section 11 is a separate PointerList of fixed 0x2C-byte
-- compact-decoration records. Hash every serialized semantic field by its
-- exact IEEE-754 bits, including the flags byte that was previously omitted.
local compact_list = world_address + off("actor_world_compact_decoration_list")
local compact_count = read_i32(compact_list + off("pointer_list_count"))
local compact_items = read_ptr(compact_list + off("pointer_list_items"))
local compact_rows = {}
local compact_ignored_flag_bits_count = 0
local compact_type_7_8_count = 0
local compact_type_7_8_noncanonical_flags = 0
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
    table.insert(compact_rows, {
      type_id,
      x_bits,
      y_bits,
      rotation_bits,
      scale_bits,
      alpha_bits,
      flags,
    })
  end
end
sort_rows(compact_rows, 7)
emit("boneyard_compact_count", compact_count)
emit("boneyard_compact_sampled", #compact_rows)
emit("boneyard_compact_digest", hx(
  digest_rows(compact_rows, {compact_count, #compact_rows}, 7)))
emit("boneyard_compact_ignored_flag_bits_count",
  compact_ignored_flag_bits_count)
emit("boneyard_compact_type_7_8_count", compact_type_7_8_count)
emit("boneyard_compact_type_7_8_noncanonical_flags",
  compact_type_7_8_noncanonical_flags)
for index, compact in ipairs(compact_rows) do
  emit(
    "boneyard_compact." .. index .. ".row",
    string.format(
      "%d,%s,%s,%s,%s,%s,%d",
      compact[1],
      hx(compact[2]),
      hx(compact[3]),
      hx(compact[4]),
      hx(compact[5]),
      hx(compact[6]),
      compact[7]))
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
        )
        missing = [field for field in required if prefix + field not in row]
        if missing:
            raise VerifyFailure(
                f"Tree decor dump {index} is incomplete: {', '.join(missing)}"
            )
        x_bits = row[prefix + "x_bits"]
        y_bits = row[prefix + "y_bits"]
        radius_bits = row[prefix + "radius_bits"]
        trees.append(
            {
                "type_id": integer(row, prefix + "type_id"),
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
            }
        )

    compact: list[dict[str, Any]] = []
    for index in range(1, integer(row, "boneyard_compact_sampled") + 1):
        key = f"boneyard_compact.{index}.row"
        fields = row.get(key, "").split(",")
        if len(fields) != 7:
            raise VerifyFailure(
                f"compact decor dump {index} is malformed: {row.get(key)!r}"
            )
        (
            type_id_text,
            x_bits,
            y_bits,
            rotation_bits,
            scale_bits,
            alpha_bits,
            flags_text,
        ) = fields
        compact.append(
            {
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
            }
        )

    return {
        "tree_count": integer(row, "boneyard_tree_count"),
        "tree_digest": row.get("boneyard_tree_digest", ""),
        "trees": trees,
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
        "compact": compact,
    }


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
        "boneyard_compact_count",
        "boneyard_compact_digest",
        "boneyard_compact_type_7_8_count",
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
        and integer(host, "boneyard_compact_count") > 0
        and integer(host, "boneyard_compact_type_7_8_count") > 0
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
