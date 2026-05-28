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


def launch_pair() -> dict[str, object]:
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
emit("player.radius", player and actor_radius(player.actor_address) or 0)
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
  local nameplate = nil
  if peer.actor_address ~= nil and peer.actor_address ~= 0 then
    nameplate = sd.bots.get_nameplate(peer.actor_address)
  end
  emit(prefix .. "nameplate", nameplate and nameplate.name or "")
end
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
    prefix = f"peer.{participant_id}."
    while time.monotonic() < deadline:
        last = query(pipe_name)
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
    raise VerifyFailure(
        f"remote participant {participant_id} not visible on {pipe_name}; last={last}"
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
        heading_delta = abs(current[2] - last[2])
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
            and abs(heading - expected_heading) <= heading_tolerance
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
            and abs(heading - expected_heading) <= 1.0
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
    host_count = lua(HOST_PIPE, code)
    client_count = lua(CLIENT_PIPE, code)
    if host_count.strip() != "0" or client_count.strip() != "0":
        raise VerifyFailure(f"failed to disable bots: host={host_count!r} client={client_count!r}")


def start_testrun(pipe_name: str) -> None:
    values = parse_key_values(lua(pipe_name, "print('ok=' .. tostring(sd.hub.start_testrun()))"))
    if values.get("ok") != "true":
        raise VerifyFailure(f"failed to start testrun on {pipe_name}: {values}")


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


def verify_scene(scene_name: str) -> dict[str, object]:
    host_seen = wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, scene_name)
    client_seen = wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, scene_name)

    host_player_before = query(HOST_PIPE)
    base_x = float(host_player_before["player.x"])
    base_y = float(host_player_before["player.y"])
    host_place_x, host_place_y = snap_to_nav(HOST_PIPE, base_x - 120.0, base_y)
    client_place_x, client_place_y = snap_to_nav(HOST_PIPE, base_x + 120.0, base_y)
    host_place = place_player(HOST_PIPE, host_place_x, host_place_y, 90.0)
    client_place = place_player(CLIENT_PIPE, client_place_x, client_place_y, 270.0)
    host_idle_x, host_idle_y, _ = wait_for_local_transform_settled(HOST_PIPE)
    client_idle_x, client_idle_y, _ = wait_for_local_transform_settled(CLIENT_PIPE)
    client_seen = wait_for_remote_convergence(
        CLIENT_PIPE,
        HOST_ID,
        host_idle_x,
        host_idle_y,
        90.0,
        timeout=12.0,
    )
    client_idle_x, client_idle_y, _ = wait_for_local_transform_settled(
        CLIENT_PIPE,
        stable_seconds=0.75,
    )
    host_seen = wait_for_remote_convergence(
        HOST_PIPE,
        CLIENT_ID,
        client_idle_x,
        client_idle_y,
        270.0,
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
    host_x, host_y, _ = wait_for_local_transform_settled(HOST_PIPE, stable_seconds=0.25)
    client_after_host_move = wait_for_remote_motion(
        CLIENT_PIPE,
        HOST_ID,
        client_observed_host_before[0],
        client_observed_host_before[1],
        135.0,
    )
    client_after_host_settled = wait_for_remote_convergence(
        CLIENT_PIPE,
        HOST_ID,
        host_x,
        host_y,
        135.0,
    )

    client_move = nudge_player(CLIENT_PIPE, -70.0, 30.0, 225.0)
    time.sleep(0.2)
    client_x, client_y, _ = wait_for_local_transform_settled(CLIENT_PIPE, stable_seconds=0.25)
    host_after_client_move = wait_for_remote_motion(
        HOST_PIPE,
        CLIENT_ID,
        host_observed_client_before[0],
        host_observed_client_before[1],
        225.0,
    )
    host_after_client_settled = wait_for_remote_convergence(
        HOST_PIPE,
        CLIENT_ID,
        client_x,
        client_y,
        225.0,
    )
    collision = wait_for_collision_push(scene_name)

    return {
        "scene": scene_name,
        "host_remote_name": host_seen[f"peer.{CLIENT_ID}.name"],
        "host_remote_nameplate": host_seen[f"peer.{CLIENT_ID}.nameplate"],
        "client_remote_name": client_seen[f"peer.{HOST_ID}.name"],
        "client_remote_nameplate": client_seen[f"peer.{HOST_ID}.nameplate"],
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

        start_testrun(HOST_PIPE)
        start_testrun(CLIENT_PIPE)
        wait_for_scene(HOST_PIPE, "testrun")
        wait_for_scene(CLIENT_PIPE, "testrun")
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
