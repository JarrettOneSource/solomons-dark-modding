#!/usr/bin/env python3
"""Live smoke test for local UDP multiplayer participant visibility and movement."""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOST_ID = 0x2000000000001001
CLIENT_ID = 0x2000000000001002
HOST_NAME = "Host Player"
CLIENT_NAME = "Client Player"
HOST_PIPE = "SolomonDarkModLoader_LuaExec_local-mp-host"
CLIENT_PIPE = "SolomonDarkModLoader_LuaExec_local-mp-client"


class VerifyFailure(RuntimeError):
    pass


def run_command(args: list[str], *, env: dict[str, str] | None = None, timeout: float = 30.0) -> str:
    completed = subprocess.run(
        args,
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise VerifyFailure(
            f"command failed ({completed.returncode}): {' '.join(args)}\n{completed.stdout}"
        )
    return completed.stdout


def stop_games() -> None:
    subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "Get-Process SolomonDark* -ErrorAction SilentlyContinue | Stop-Process -Force",
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def extract_json(buffer: str) -> dict[str, object] | None:
    start = buffer.find("{")
    if start < 0:
        return None
    candidate = buffer[start:]
    decoder = json.JSONDecoder()
    try:
        value, _ = decoder.raw_decode(candidate)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        raise VerifyFailure(f"launcher returned non-object JSON: {value!r}")
    return value


def launch_pair(
    preset: str = "map_create_fire_mind_hub",
    *,
    host_preset: str | None = None,
    client_preset: str | None = None,
    temporary_host_profile: bool = True,
) -> dict[str, object]:
    args = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        "scripts/Launch-LocalMultiplayerPair.ps1",
        "-HostName",
        HOST_NAME,
        "-ClientName",
        CLIENT_NAME,
    ]
    if host_preset is not None or client_preset is not None:
        if host_preset is not None:
            args.extend(["-HostPreset", host_preset])
        if client_preset is not None:
            args.extend(["-ClientPreset", client_preset])
    else:
        args.extend(["-Preset", preset])
    if temporary_host_profile:
        args.append("-TemporaryHostProfile")
    process = subprocess.Popen(
        args,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    assert process.stdout is not None

    def terminate_launcher() -> None:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            process.kill()

    def query_scene_for_launch(pipe_name: str) -> str:
        env = os.environ.copy()
        env["SDMOD_LUA_EXEC_PIPE_NAME"] = pipe_name
        try:
            completed = subprocess.run(
                [
                    "python3",
                    "tools/lua-exec.py",
                    "local s=sd.world.get_scene(); return tostring(s and (s.name or s.kind) or '')",
                ],
                cwd=ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=2.0,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ""
        if completed.returncode != 0:
            return ""
        return completed.stdout.strip()

    deadline = time.monotonic() + 120.0
    buffer = ""
    last_hub_probe = 0.0
    hub_ready_since: float | None = None
    while time.monotonic() < deadline:
        ready, _, _ = select.select([process.stdout], [], [], 0.1)
        if ready:
            line = process.stdout.readline()
            if line:
                buffer += line
                parsed = extract_json(buffer)
                if parsed is not None:
                    terminate_launcher()
                    return parsed
            elif process.poll() is not None:
                break

        if process.poll() is not None:
            remainder = process.stdout.read()
            if remainder:
                buffer += remainder
                parsed = extract_json(buffer)
                if parsed is not None:
                    return parsed
            if process.returncode != 0:
                raise VerifyFailure(f"pair launcher failed ({process.returncode}):\n{buffer}")
            break

        now = time.monotonic()
        if now - last_hub_probe >= 1.0:
            last_hub_probe = now
            if (
                query_scene_for_launch(HOST_PIPE) == "hub"
                and query_scene_for_launch(CLIENT_PIPE) == "hub"
            ):
                if hub_ready_since is None:
                    hub_ready_since = now
                elif now - hub_ready_since >= 1.0:
                    terminate_launcher()
                    return {
                        "fallbackReady": True,
                        "hostLuaPipe": HOST_PIPE,
                        "clientLuaPipe": CLIENT_PIPE,
                        "hostName": HOST_NAME,
                        "clientName": CLIENT_NAME,
                    }
            else:
                hub_ready_since = None

    terminate_launcher()
    raise VerifyFailure(f"timed out waiting for pair launcher JSON:\n{buffer}")


def lua(pipe_name: str, code: str, timeout: float = 10.0) -> str:
    env = os.environ.copy()
    env["SDMOD_LUA_EXEC_PIPE_NAME"] = pipe_name
    return run_command(
        ["python3", "tools/lua-exec.py", code],
        env=env,
        timeout=timeout,
    ).strip()


def parse_key_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def parse_int_text(value: str | None, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value, 0)
    except ValueError:
        return int(float(value))


def visual_blocks_by_type(values: dict[str, str], prefix: str) -> dict[int, str]:
    blocks: dict[int, str] = {}
    for lane in ("primary", "secondary"):
        type_id = parse_int_text(values.get(f"{prefix}.{lane}_visual_type"), 0)
        block = values.get(f"{prefix}.{lane}_visual_block", "")
        if type_id != 0 and block:
            blocks[type_id] = block
    return blocks


QUERY_LUA = r"""
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
local scene = sd.world.get_scene()
local player = sd.player.get_state()
emit("scene", scene and (scene.name or scene.kind) or "")
emit("player.actor", player and player.actor_address or 0)
emit("player.x", player and player.x or 0)
emit("player.y", player and player.y or 0)
emit("player.heading", player and player.heading or 0)
local radius_offset = sd.debug.layout_offset("actor_collision_radius")
local function actor_radius(actor_address)
  if actor_address == nil or actor_address == 0 or radius_offset == nil then
    return 0
  end
  return sd.debug.read_float(actor_address + radius_offset) or 0
end
local function staff_visual_state(lane)
  if lane == nil or lane.current_object_address == nil or lane.current_object_address == 0 then
    return 0
  end
  return sd.debug.read_u32(lane.current_object_address + 0x84) or 0
end
local function visual_link_block(lane)
  if lane == nil or lane.current_object_address == nil or lane.current_object_address == 0 then
    return ""
  end
  local out = {}
  for i = 0, 31 do
    out[#out + 1] = string.format("%02X", tonumber(sd.debug.read_u8(lane.current_object_address + 0x88 + i)) or 0)
  end
  return table.concat(out, " ")
end
local function visual_link_type(lane)
  if lane == nil then
    return 0
  end
  return lane.current_object_type_id or 0
end
local function render_selector(state)
  if state == nil then
    return ""
  end
  return table.concat({
    tostring(state.render_variant_primary or 0),
    tostring(state.render_variant_secondary or 0),
    tostring(state.render_weapon_type or 0),
    tostring(state.render_selection_byte or 0),
    tostring(state.render_variant_tertiary or 0),
  }, ",")
end
emit("player.radius", player and actor_radius(player.actor_address) or 0)
emit("player.staff_visual_state", player and staff_visual_state(player.attachment_visual_lane) or 0)
emit("player.render_selector", render_selector(player))
emit("player.primary_visual_type", player and visual_link_type(player.primary_visual_lane) or 0)
emit("player.primary_visual_block", player and visual_link_block(player.primary_visual_lane) or "")
emit("player.secondary_visual_type", player and visual_link_type(player.secondary_visual_lane) or 0)
emit("player.secondary_visual_block", player and visual_link_block(player.secondary_visual_lane) or "")
local peers = sd.bots.get_participants()
emit("peer.count", #peers)
for i, peer in ipairs(peers) do
  local prefix = "peer." .. tostring(peer.id) .. "."
  emit(prefix .. "name", peer.name)
  emit(prefix .. "kind", peer.participant_kind)
  emit(prefix .. "controller", peer.controller_kind)
  emit(prefix .. "materialized", peer.entity_materialized)
  emit(prefix .. "transform", peer.transform_valid)
  emit(prefix .. "actor", peer.actor_address)
  emit(prefix .. "x", peer.x)
  emit(prefix .. "y", peer.y)
  emit(prefix .. "heading", peer.heading)
  emit(prefix .. "radius", actor_radius(peer.actor_address))
  emit(prefix .. "staff_visual_state", staff_visual_state(peer.attachment_visual_lane))
  emit(prefix .. "render_selector", render_selector(peer))
  emit(prefix .. "primary_visual_type", visual_link_type(peer.primary_visual_lane))
  emit(prefix .. "primary_visual_block", visual_link_block(peer.primary_visual_lane))
  emit(prefix .. "secondary_visual_type", visual_link_type(peer.secondary_visual_lane))
  emit(prefix .. "secondary_visual_block", visual_link_block(peer.secondary_visual_lane))
  local nameplate = nil
  if peer.actor_address ~= nil and peer.actor_address ~= 0 then
    nameplate = sd.bots.get_nameplate(peer.actor_address)
  end
  emit(prefix .. "nameplate", nameplate and nameplate.name or "")
end
local replicated = nil
if sd.world.get_replicated_actors ~= nil then
  replicated = sd.world.get_replicated_actors()
end
emit("replicated.valid", replicated ~= nil)
emit("replicated.scene_kind", replicated and replicated.scene_kind or "")
emit("replicated.actor_count", replicated and replicated.actor_count or 0)
emit("replicated.actor_total_count", replicated and replicated.actor_total_count or 0)
emit("replicated.authority_participant_id", replicated and replicated.authority_participant_id or 0)
emit("replicated.apply_valid", replicated and replicated.apply_valid or false)
"""


def query(pipe_name: str) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, QUERY_LUA))


def wait_for_remote(
    pipe_name: str,
    participant_id: int,
    expected_name: str,
    expected_scene: str,
    timeout: float = 30.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    last_error = ""
    prefix = f"peer.{participant_id}."
    while time.monotonic() < deadline:
        try:
            last = query(pipe_name)
            last_error = ""
        except (VerifyFailure, subprocess.TimeoutExpired) as exc:
            last_error = str(exc)
            time.sleep(0.25)
            continue
        if (
            last.get("scene") == expected_scene
            and last.get(prefix + "name") == expected_name
            and last.get(prefix + "nameplate") == expected_name
            and last.get(prefix + "materialized") == "true"
            and last.get(prefix + "transform") == "true"
            and int(float(last.get(prefix + "actor", "0") or "0")) != 0
        ):
            return last
        time.sleep(0.25)
    suffix = f"; last_error={last_error}" if last_error else ""
    raise VerifyFailure(
        f"remote participant {participant_id} not visible on {pipe_name}; last={last}{suffix}"
    )


def nudge_player(pipe_name: str, dx: float, dy: float, heading: float) -> dict[str, str]:
    code = f"""
local player = sd.player.get_state()
local ox = sd.debug.layout_offset("actor_position_x")
local oy = sd.debug.layout_offset("actor_position_y")
local oh = sd.debug.layout_offset("actor_heading")
local os = sd.debug.layout_offset("actor_animation_selection_state")
local oha = sd.debug.layout_offset("actor_control_brain_heading_accumulator")
local odf = sd.debug.layout_offset("actor_control_brain_desired_facing")
local odfs = sd.debug.layout_offset("actor_control_brain_desired_facing_smoothed")
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local function write_facing(actor, heading)
  local wrote = sd.debug.write_float(actor + oh, heading)
  if os ~= nil and oha ~= nil and odf ~= nil and odfs ~= nil then
    local control = sd.debug.read_u32(actor + os) or 0
    if control ~= 0 then
      wrote = sd.debug.write_float(control + oha, heading) and wrote
      wrote = sd.debug.write_float(control + odf, heading) and wrote
      wrote = sd.debug.write_float(control + odfs, heading) and wrote
    end
  end
  return wrote
end
if player == nil or player.actor_address == nil or player.actor_address == 0 then
  error("player actor unavailable")
end
local nx = tonumber(player.x) + ({dx})
local ny = tonumber(player.y) + ({dy})
emit("before.x", player.x)
emit("before.y", player.y)
emit("write.x", sd.debug.write_float(player.actor_address + ox, nx))
emit("write.y", sd.debug.write_float(player.actor_address + oy, ny))
emit("write.heading", write_facing(player.actor_address, {heading}))
local after = sd.player.get_state()
emit("after.x", after and after.x or 0)
emit("after.y", after and after.y or 0)
emit("after.heading", after and after.heading or 0)
"""
    values = parse_key_values(lua(pipe_name, code))
    if values.get("write.x") != "true" or values.get("write.y") != "true":
        raise VerifyFailure(f"failed to nudge player on {pipe_name}: {values}")
    return values


def place_player(pipe_name: str, x: float, y: float, heading: float) -> dict[str, str]:
    code = f"""
local player = sd.player.get_state()
local ox = sd.debug.layout_offset("actor_position_x")
local oy = sd.debug.layout_offset("actor_position_y")
local oh = sd.debug.layout_offset("actor_heading")
local os = sd.debug.layout_offset("actor_animation_selection_state")
local oha = sd.debug.layout_offset("actor_control_brain_heading_accumulator")
local odf = sd.debug.layout_offset("actor_control_brain_desired_facing")
local odfs = sd.debug.layout_offset("actor_control_brain_desired_facing_smoothed")
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local function write_facing(actor, heading)
  local wrote = sd.debug.write_float(actor + oh, heading)
  if os ~= nil and oha ~= nil and odf ~= nil and odfs ~= nil then
    local control = sd.debug.read_u32(actor + os) or 0
    if control ~= 0 then
      wrote = sd.debug.write_float(control + oha, heading) and wrote
      wrote = sd.debug.write_float(control + odf, heading) and wrote
      wrote = sd.debug.write_float(control + odfs, heading) and wrote
    end
  end
  return wrote
end
if player == nil or player.actor_address == nil or player.actor_address == 0 then
  error("player actor unavailable")
end
emit("before.x", player.x)
emit("before.y", player.y)
emit("write.x", sd.debug.write_float(player.actor_address + ox, {x}))
emit("write.y", sd.debug.write_float(player.actor_address + oy, {y}))
emit("write.heading", write_facing(player.actor_address, {heading}))
local after = sd.player.get_state()
emit("after.x", after and after.x or 0)
emit("after.y", after and after.y or 0)
emit("after.heading", after and after.heading or 0)
"""
    values = parse_key_values(lua(pipe_name, code))
    if values.get("write.x") != "true" or values.get("write.y") != "true":
        raise VerifyFailure(f"failed to place player on {pipe_name}: {values}")
    return values


def snap_to_nav(pipe_name: str, x: float, y: float) -> tuple[float, float]:
    code = f"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local grid = sd.debug.get_nav_grid(1)
if type(grid) ~= "table" or grid.valid == false or type(grid.cells) ~= "table" then
  emit("available", false)
  return
end
local target_x = {x}
local target_y = {y}
local best = nil
local best_gap = nil
for _, cell in ipairs(grid.cells) do
  if type(cell) == "table" and type(cell.samples) == "table" then
    for _, sample in ipairs(cell.samples) do
      if type(sample) == "table" and sample.traversable and
          tonumber(sample.world_x) ~= nil and tonumber(sample.world_y) ~= nil then
        local dx = tonumber(sample.world_x) - target_x
        local dy = tonumber(sample.world_y) - target_y
        local gap = math.sqrt(dx * dx + dy * dy)
        if best_gap == nil or gap < best_gap then
          best_gap = gap
          best = sample
        end
      end
    end
  end
end
if best == nil then
  emit("available", false)
  return
end
emit("available", true)
emit("x", best.world_x)
emit("y", best.world_y)
emit("gap", string.format("%.3f", best_gap or 0))
"""
    deadline = time.monotonic() + 5.0
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = parse_key_values(lua(pipe_name, code))
        if last.get("available") == "true":
            return float(last["x"]), float(last["y"])
        time.sleep(0.25)
    raise VerifyFailure(f"nav grid did not produce a traversable sample on {pipe_name}: {last}")


def distance(ax: float, ay: float, bx: float, by: float) -> float:
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def heading_distance(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def query_local_transform(pipe_name: str) -> tuple[float, float, float]:
    values = query(pipe_name)
    return (
        float(values["player.x"]),
        float(values["player.y"]),
        float(values["player.heading"]),
    )


def wait_for_local_transform_settled(
    pipe_name: str,
    timeout: float = 6.0,
    stable_seconds: float = 0.5,
    distance_tolerance: float = 0.75,
    heading_tolerance: float = 0.5,
) -> tuple[float, float, float]:
    deadline = time.monotonic() + timeout
    stable_since: float | None = None
    last = query_local_transform(pipe_name)
    while time.monotonic() < deadline:
        time.sleep(0.1)
        current = query_local_transform(pipe_name)
        position_delta = distance(last[0], last[1], current[0], current[1])
        heading_delta = heading_distance(current[2], last[2])
        if position_delta <= distance_tolerance and heading_delta <= heading_tolerance:
            if stable_since is None:
                stable_since = time.monotonic()
            if time.monotonic() - stable_since >= stable_seconds:
                return current
        else:
            stable_since = None
        last = current
    return last


def wait_for_remote_motion(
    observer_pipe: str,
    participant_id: int,
    previous_x: float,
    previous_y: float,
    expected_heading: float,
    heading_tolerance: float = 0.25,
    timeout: float = 10.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    prefix = f"peer.{participant_id}."
    while time.monotonic() < deadline:
        last = query(observer_pipe)
        x = float(last.get(prefix + "x", "nan"))
        y = float(last.get(prefix + "y", "nan"))
        heading = float(last.get(prefix + "heading", "nan"))
        moved_distance = ((x - previous_x) ** 2 + (y - previous_y) ** 2) ** 0.5
        if (
            moved_distance >= 2.0
            and heading_distance(heading, expected_heading) <= heading_tolerance
        ):
            return last
        time.sleep(0.2)
    raise VerifyFailure(
        f"remote participant {participant_id} did not move from {previous_x:.3f},{previous_y:.3f} "
        f"with observed-motion heading {expected_heading:.3f} "
        f"on {observer_pipe}; last={last}"
    )


def wait_for_remote_convergence(
    observer_pipe: str,
    participant_id: int,
    expected_x: float,
    expected_y: float,
    expected_heading: float,
    timeout: float = 10.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    prefix = f"peer.{participant_id}."
    while time.monotonic() < deadline:
        last = query(observer_pipe)
        x = float(last.get(prefix + "x", "nan"))
        y = float(last.get(prefix + "y", "nan"))
        heading = float(last.get(prefix + "heading", "nan"))
        if (
            distance(x, y, expected_x, expected_y) <= 3.0
            and heading_distance(heading, expected_heading) <= 1.0
        ):
            return last
        time.sleep(0.15)
    raise VerifyFailure(
        f"remote participant {participant_id} did not settle near "
        f"{expected_x:.3f},{expected_y:.3f} heading {expected_heading:.3f} "
        f"on {observer_pipe}; last={last}"
    )


def wait_for_local_collision_push(
    *,
    scene_name: str,
    anchor_pipe: str,
    anchor_id: int,
    anchor_x: float,
    anchor_y: float,
    anchor_heading: float,
    mover_pipe: str,
    mover_peer_id: int,
    mover_x: float,
    mover_y: float,
    mover_heading: float,
    timeout: float = 12.0,
) -> dict[str, object]:
    place_player(anchor_pipe, anchor_x, anchor_y, anchor_heading)
    wait_for_remote_convergence(
        mover_pipe,
        anchor_id,
        anchor_x,
        anchor_y,
        anchor_heading,
        timeout=8.0,
    )
    mover_start = place_player(mover_pipe, mover_x, mover_y, mover_heading)
    mover_start_xy = (float(mover_start["after.x"]), float(mover_start["after.y"]))
    peer_prefix = f"peer.{mover_peer_id}."
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = query(mover_pipe)
        if last.get("scene") != scene_name:
            time.sleep(0.15)
            continue

        mover_player = (float(last["player.x"]), float(last["player.y"]))
        peer = (
            float(last.get(peer_prefix + "x", "nan")),
            float(last.get(peer_prefix + "y", "nan")),
        )
        mover_radius = float(last.get("player.radius", "0") or "0")
        peer_radius = float(last.get(peer_prefix + "radius", "0") or "0")
        min_separation = max(8.0, mover_radius + peer_radius - 1.0)

        if (
            distance(*mover_player, *mover_start_xy) >= 1.0
            and distance(*mover_player, *peer) >= min_separation
        ):
            return {
                "mover_pipe": mover_pipe,
                "mover_start": list(mover_start_xy),
                "mover_after_push": list(mover_player),
                "peer_after_push": list(peer),
                "min_separation": min_separation,
            }
        time.sleep(0.15)

    raise VerifyFailure(
        f"local player on {mover_pipe} did not push away from peer {mover_peer_id} "
        f"in {scene_name}; last={last}"
    )


def wait_for_collision_push(scene_name: str) -> dict[str, object]:
    host_before = query(HOST_PIPE)
    base_x = float(host_before["player.x"])
    base_y = float(host_before["player.y"])
    client_push = wait_for_local_collision_push(
        scene_name=scene_name,
        anchor_pipe=HOST_PIPE,
        anchor_id=HOST_ID,
        anchor_x=base_x,
        anchor_y=base_y,
        anchor_heading=90.0,
        mover_pipe=CLIENT_PIPE,
        mover_peer_id=HOST_ID,
        mover_x=base_x + 2.0,
        mover_y=base_y,
        mover_heading=270.0,
    )
    host_push = wait_for_local_collision_push(
        scene_name=scene_name,
        anchor_pipe=CLIENT_PIPE,
        anchor_id=CLIENT_ID,
        anchor_x=base_x + 160.0,
        anchor_y=base_y,
        anchor_heading=270.0,
        mover_pipe=HOST_PIPE,
        mover_peer_id=CLIENT_ID,
        mover_x=base_x + 162.0,
        mover_y=base_y,
        mover_heading=90.0,
    )
    return {
        "client_push": client_push,
        "host_push": host_push,
    }


def disable_bots() -> None:
    code = "lua_bots_disable_tick = true; sd.bots.clear(); return tostring(sd.bots.get_count())"

    def disable_one(pipe_name: str) -> str:
        deadline = time.monotonic() + 15.0
        last_error = ""
        last_count = ""
        while time.monotonic() < deadline:
            try:
                last_count = lua(pipe_name, code, timeout=5.0).strip()
                if last_count == "0":
                    return last_count
            except (VerifyFailure, subprocess.TimeoutExpired) as exc:
                last_error = str(exc)
            time.sleep(0.25)
        detail = last_error or last_count
        raise VerifyFailure(f"failed to disable bots on {pipe_name}: {detail!r}")

    host_count = disable_one(HOST_PIPE)
    client_count = disable_one(CLIENT_PIPE)
    if host_count.strip() != "0" or client_count.strip() != "0":
        raise VerifyFailure(f"failed to disable bots: host={host_count!r} client={client_count!r}")


def start_testrun(pipe_name: str) -> None:
    values = parse_key_values(lua(pipe_name, "print('ok=' .. tostring(sd.hub.start_testrun()))"))
    if values.get("ok") != "true":
        raise VerifyFailure(f"failed to start testrun on {pipe_name}: {values}")


def assert_client_start_testrun_blocked() -> dict[str, object]:
    expected = "host-only while connected to a multiplayer session"
    try:
        output = lua(CLIENT_PIPE, "print('ok=' .. tostring(sd.hub.start_testrun()))")
    except VerifyFailure as exc:
        if expected not in str(exc):
            raise VerifyFailure(f"client start_testrun failed for an unexpected reason: {exc}") from exc
        scene = lua(
            CLIENT_PIPE,
            "local s=sd.world.get_scene(); return tostring(s and (s.name or s.kind) or '')",
        ).strip()
        if scene != "hub":
            raise VerifyFailure(f"client start_testrun block left client in unexpected scene {scene!r}")
        return {
            "blocked": True,
            "expected_error": expected,
            "scene": scene,
        }
    raise VerifyFailure(f"client unexpectedly started testrun directly: {output!r}")


def wait_for_scene(pipe_name: str, scene_name: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    last = ""
    last_error = ""
    while time.monotonic() < deadline:
        try:
            last = lua(
                pipe_name,
                "local s=sd.world.get_scene(); return tostring(s and (s.name or s.kind) or '')",
                timeout=5.0,
            ).strip()
            last_error = ""
        except (VerifyFailure, subprocess.TimeoutExpired) as exc:
            last_error = str(exc)
            time.sleep(0.25)
            continue
        if last == scene_name:
            return
        time.sleep(0.25)
    suffix = f"; last_error={last_error}" if last_error else ""
    raise VerifyFailure(f"{pipe_name} did not reach scene {scene_name}; last={last}{suffix}")


def wait_for_both_hub_settled(settle_seconds: float = 3.0, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    settled_since: float | None = None
    last_host = ""
    last_client = ""
    while time.monotonic() < deadline:
        try:
            last_host = lua(
                HOST_PIPE,
                "local s=sd.world.get_scene(); return tostring(s and (s.name or s.kind) or '')",
                timeout=5.0,
            ).strip()
            last_client = lua(
                CLIENT_PIPE,
                "local s=sd.world.get_scene(); return tostring(s and (s.name or s.kind) or '')",
                timeout=5.0,
            ).strip()
        except (VerifyFailure, subprocess.TimeoutExpired):
            settled_since = None
            time.sleep(0.25)
            continue
        now = time.monotonic()
        if last_host == "" or last_client == "":
            time.sleep(0.25)
            continue
        if last_host == "hub" and last_client == "hub":
            if settled_since is None:
                settled_since = now
            elif now - settled_since >= settle_seconds:
                return
        else:
            settled_since = None
        time.sleep(0.25)
    raise VerifyFailure(
        f"instances did not remain hub-settled before run entry; host={last_host!r} client={last_client!r}"
    )


def start_host_testrun_and_wait_for_clients(timeout: float = 30.0) -> dict[str, object]:
    wait_for_both_hub_settled()
    start_testrun(HOST_PIPE)
    wait_for_scene(HOST_PIPE, "testrun", timeout=timeout)
    wait_for_scene(CLIENT_PIPE, "testrun", timeout=timeout)
    return {
        "host_started": True,
        "client_followed_host": True,
        "scene": "testrun",
    }


def verify_run_entry_bootstrap(timeout: float = 15.0) -> dict[str, object]:
    wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "testrun")
    wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "testrun")

    deadline = time.monotonic() + timeout
    last: dict[str, object] = {}
    while time.monotonic() < deadline:
        host = query(HOST_PIPE)
        client = query(CLIENT_PIPE)
        host_x = float(host["player.x"])
        host_y = float(host["player.y"])
        client_x = float(client["player.x"])
        client_y = float(client["player.y"])
        host_client_spawn_distance = distance(host_x, host_y, client_x, client_y)
        host_observed_client_distance = distance(
            float(host[f"peer.{CLIENT_ID}.x"]),
            float(host[f"peer.{CLIENT_ID}.y"]),
            client_x,
            client_y,
        )
        client_observed_host_distance = distance(
            float(client[f"peer.{HOST_ID}.x"]),
            float(client[f"peer.{HOST_ID}.y"]),
            host_x,
            host_y,
        )
        client_replicated_scene_kind = client.get("replicated.scene_kind", "")
        last = {
            "host_player": [host_x, host_y],
            "client_player": [client_x, client_y],
            "host_client_spawn_distance": host_client_spawn_distance,
            "host_observed_client_distance": host_observed_client_distance,
            "client_observed_host_distance": client_observed_host_distance,
            "client_replicated_scene_kind": client_replicated_scene_kind,
            "client_replicated_actor_count": parse_int_text(client.get("replicated.actor_count")),
            "client_replicated_actor_total_count": parse_int_text(client.get("replicated.actor_total_count")),
            "client_replicated_authority_participant_id": parse_int_text(client.get("replicated.authority_participant_id")),
        }
        if (
            host.get("scene") == "testrun"
            and client.get("scene") == "testrun"
            and client_replicated_scene_kind == "Run"
            and host_client_spawn_distance <= 112.0
            and host_observed_client_distance <= 32.0
            and client_observed_host_distance <= 32.0
        ):
            return last
        time.sleep(0.25)

    raise VerifyFailure(f"run entry bootstrap did not converge; last={last}")


def verify_scene(scene_name: str) -> dict[str, object]:
    host_seen = wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, scene_name)
    client_seen = wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, scene_name)
    host_source_staff_visual_state = int(
        float(host_seen.get("player.staff_visual_state", "0") or "0"))
    client_source_staff_visual_state = int(
        float(client_seen.get("player.staff_visual_state", "0") or "0"))
    host_remote_staff_visual_state = int(
        float(host_seen.get(f"peer.{CLIENT_ID}.staff_visual_state", "0") or "0"))
    client_remote_staff_visual_state = int(
        float(client_seen.get(f"peer.{HOST_ID}.staff_visual_state", "0") or "0"))
    # Staff attachment +0x84 is native-owned and can contain process-local data
    # in run scenes. Keep it in the report for diagnosis, but do not require
    # cross-client equality.
    host_source_selector = host_seen.get("player.render_selector", "")
    client_source_selector = client_seen.get("player.render_selector", "")
    host_remote_selector = host_seen.get(f"peer.{CLIENT_ID}.render_selector", "")
    client_remote_selector = client_seen.get(f"peer.{HOST_ID}.render_selector", "")
    if host_remote_selector != client_source_selector:
        raise VerifyFailure(
            "host remote render selector does not mirror client source: "
            f"remote={host_remote_selector!r} source={client_source_selector!r}")
    if client_remote_selector != host_source_selector:
        raise VerifyFailure(
            "client remote render selector does not mirror host source: "
            f"remote={client_remote_selector!r} source={host_source_selector!r}")
    client_source_visual_blocks = visual_blocks_by_type(client_seen, "player")
    host_source_visual_blocks = visual_blocks_by_type(host_seen, "player")
    host_remote_visual_blocks = visual_blocks_by_type(host_seen, f"peer.{CLIENT_ID}")
    client_remote_visual_blocks = visual_blocks_by_type(client_seen, f"peer.{HOST_ID}")
    for type_id, source_block in client_source_visual_blocks.items():
        remote_block = host_remote_visual_blocks.get(type_id, "")
        if remote_block != source_block:
            raise VerifyFailure(
                "host remote visual-link block does not mirror client source: "
                f"type=0x{type_id:04X} remote={remote_block!r} source={source_block!r}")
    for type_id, source_block in host_source_visual_blocks.items():
        remote_block = client_remote_visual_blocks.get(type_id, "")
        if remote_block != source_block:
            raise VerifyFailure(
                "client remote visual-link block does not mirror host source: "
                f"type=0x{type_id:04X} remote={remote_block!r} source={source_block!r}")

    host_player_before = query(HOST_PIPE)
    base_x = float(host_player_before["player.x"])
    base_y = float(host_player_before["player.y"])
    host_place_x, host_place_y = snap_to_nav(HOST_PIPE, base_x - 120.0, base_y)
    client_place_x, client_place_y = snap_to_nav(HOST_PIPE, base_x + 120.0, base_y)
    host_place = place_player(HOST_PIPE, host_place_x, host_place_y, 90.0)
    client_place = place_player(CLIENT_PIPE, client_place_x, client_place_y, 270.0)
    host_idle_x, host_idle_y, host_idle_heading = wait_for_local_transform_settled(HOST_PIPE)
    client_idle_x, client_idle_y, client_idle_heading = wait_for_local_transform_settled(CLIENT_PIPE)
    client_seen = wait_for_remote_convergence(
        CLIENT_PIPE,
        HOST_ID,
        host_idle_x,
        host_idle_y,
        host_idle_heading,
        timeout=12.0,
    )
    client_idle_x, client_idle_y, client_idle_heading = wait_for_local_transform_settled(
        CLIENT_PIPE,
        stable_seconds=0.75,
    )
    host_seen = wait_for_remote_convergence(
        HOST_PIPE,
        CLIENT_ID,
        client_idle_x,
        client_idle_y,
        client_idle_heading,
        timeout=12.0,
    )

    host_observed_client_before = (
        float(host_seen[f"peer.{CLIENT_ID}.x"]),
        float(host_seen[f"peer.{CLIENT_ID}.y"]),
    )
    client_observed_host_before = (
        float(client_seen[f"peer.{HOST_ID}.x"]),
        float(client_seen[f"peer.{HOST_ID}.y"]),
    )

    host_move = nudge_player(HOST_PIPE, 90.0, 0.0, 135.0)
    time.sleep(0.2)
    host_x, host_y, host_heading = wait_for_local_transform_settled(HOST_PIPE, stable_seconds=0.25)
    client_after_host_move = wait_for_remote_motion(
        CLIENT_PIPE,
        HOST_ID,
        client_observed_host_before[0],
        client_observed_host_before[1],
        host_heading,
    )
    client_after_host_settled = wait_for_remote_convergence(
        CLIENT_PIPE,
        HOST_ID,
        host_x,
        host_y,
        host_heading,
    )

    client_move = nudge_player(CLIENT_PIPE, -70.0, 30.0, 225.0)
    time.sleep(0.2)
    client_x, client_y, client_heading = wait_for_local_transform_settled(CLIENT_PIPE, stable_seconds=0.25)
    host_after_client_move = wait_for_remote_motion(
        HOST_PIPE,
        CLIENT_ID,
        host_observed_client_before[0],
        host_observed_client_before[1],
        client_heading,
    )
    host_after_client_settled = wait_for_remote_convergence(
        HOST_PIPE,
        CLIENT_ID,
        client_x,
        client_y,
        client_heading,
    )
    collision = wait_for_collision_push(scene_name)

    return {
        "scene": scene_name,
        "host_remote_name": host_seen[f"peer.{CLIENT_ID}.name"],
        "host_remote_nameplate": host_seen[f"peer.{CLIENT_ID}.nameplate"],
        "host_remote_staff_visual_state": f"0x{host_remote_staff_visual_state:08X}",
        "client_source_staff_visual_state": f"0x{client_source_staff_visual_state:08X}",
        "host_remote_render_selector": host_remote_selector,
        "client_source_render_selector": client_source_selector,
        "host_remote_visual_link_types": sorted(host_remote_visual_blocks),
        "client_remote_name": client_seen[f"peer.{HOST_ID}.name"],
        "client_remote_nameplate": client_seen[f"peer.{HOST_ID}.nameplate"],
        "client_remote_staff_visual_state": f"0x{client_remote_staff_visual_state:08X}",
        "host_source_staff_visual_state": f"0x{host_source_staff_visual_state:08X}",
        "client_remote_render_selector": client_remote_selector,
        "host_source_render_selector": host_source_selector,
        "client_remote_visual_link_types": sorted(client_remote_visual_blocks),
        "host_moved_to": [host_x, host_y],
        "client_observed_host_before": list(client_observed_host_before),
        "client_observed_host_at": [
            float(client_after_host_move[f"peer.{HOST_ID}.x"]),
            float(client_after_host_move[f"peer.{HOST_ID}.y"]),
        ],
        "client_observed_host_settled": [
            float(client_after_host_settled[f"peer.{HOST_ID}.x"]),
            float(client_after_host_settled[f"peer.{HOST_ID}.y"]),
        ],
        "client_observed_host_heading": float(client_after_host_move[f"peer.{HOST_ID}.heading"]),
        "client_moved_to": [client_x, client_y],
        "host_observed_client_before": list(host_observed_client_before),
        "host_observed_client_at": [
            float(host_after_client_move[f"peer.{CLIENT_ID}.x"]),
            float(host_after_client_move[f"peer.{CLIENT_ID}.y"]),
        ],
        "host_observed_client_settled": [
            float(host_after_client_settled[f"peer.{CLIENT_ID}.x"]),
            float(host_after_client_settled[f"peer.{CLIENT_ID}.y"]),
        ],
        "host_observed_client_heading": float(host_after_client_move[f"peer.{CLIENT_ID}.heading"]),
        "collision": collision,
    }


def main() -> int:
    result: dict[str, object] = {"ok": False, "checks": []}
    try:
        stop_games()
        result["launch"] = launch_pair()
        disable_bots()
        result["checks"].append(verify_scene("hub"))

        result["client_start_blocked"] = assert_client_start_testrun_blocked()
        result["host_run_entry"] = start_host_testrun_and_wait_for_clients()
        result["run_entry_bootstrap"] = verify_run_entry_bootstrap()
        result["checks"].append(verify_scene("testrun"))

        result["ok"] = True
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        result["error"] = str(exc)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1
    finally:
        stop_games()


if __name__ == "__main__":
    sys.exit(main())
