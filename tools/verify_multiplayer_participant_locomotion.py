#!/usr/bin/env python3
"""Verify native collision and footstep behavior for remote players and bots."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import time
from pathlib import Path
from typing import Any

import verify_local_multiplayer_sync as local_sync


ROOT = Path(__file__).resolve().parents[1]
GAME_DIRECTORY = Path(
    "/mnt/c/Users/User/Documents/GitHub/SB Modding/"
    "Solomon Dark/SolomonDarkAbandonware"
)
EVIDENCE_DIRECTORY = Path(
    "/mnt/d/codex-evidence/fieldfix-20260727"
)
OUTPUT_PATH = EVIDENCE_DIRECTORY / "participant-locomotion-fixed.json"
FLAT_BONEYARD = (
    ROOT / "tests/fixtures/boneyards/flat_multiplayer_test.boneyard"
)
INSTANCE_PREFIX = "ffix"
HOST_PORT = 49711
CLIENT_PORT = 49712
HOST_PIPE = "SolomonDarkModLoader_LuaExec_ffix-host"
CLIENT_PIPE = "SolomonDarkModLoader_LuaExec_ffix-client"
HOST_ID = local_sync.HOST_ID
CLIENT_ID = local_sync.CLIENT_ID
ACCEPTANCE_MOD_ID = "sample.lua.ui_sandbox_lab"
BOT_NAME = "Stride"
BOT_CLASS = "fire"


class LocomotionFailure(RuntimeError):
    pass


def _number(
    values: dict[str, str],
    key: str,
    default: float = 0.0,
) -> float:
    try:
        return float(values.get(key, str(default)))
    except (TypeError, ValueError):
        return default


def _integer(
    values: dict[str, str],
    key: str,
    default: int = 0,
) -> int:
    return int(_number(values, key, float(default)))


def _windows_path_to_wsl(value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise LocomotionFailure(f"launcher path is missing: {value!r}")
    completed = subprocess.run(
        ["wslpath", "-u", value],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=5.0,
        check=False,
    )
    path = completed.stdout.strip()
    if completed.returncode != 0 or not path:
        raise LocomotionFailure(
            f"could not convert launcher path {value!r}: "
            f"{completed.stdout}"
        )
    return Path(path)


def _wait(
    probe,
    predicate,
    *,
    timeout: float,
    label: str,
    interval: float = 0.1,
):
    deadline = time.monotonic() + timeout
    last: Any = None
    last_error = ""
    while time.monotonic() < deadline:
        try:
            last = probe()
            last_error = ""
            if predicate(last):
                return last
        except (
            LocomotionFailure,
            local_sync.VerifyFailure,
            subprocess.TimeoutExpired,
        ) as exc:
            last_error = str(exc)
        time.sleep(interval)
    detail = f" last={last!r}"
    if last_error:
        detail += f" error={last_error}"
    raise LocomotionFailure(f"{label} timed out.{detail}")


def _query(pipe_name: str) -> dict[str, str]:
    return local_sync.query(pipe_name)


def _wait_remote(
    observer_pipe: str,
    participant_id: int,
    *,
    timeout: float = 10.0,
) -> dict[str, str]:
    prefix = f"peer.{participant_id}."
    return _wait(
        lambda: _query(observer_pipe),
        lambda values: (
            values.get(prefix + "materialized") == "true"
            and values.get(prefix + "transform") == "true"
            and _integer(values, prefix + "actor") > 0
            and math.isfinite(_number(values, prefix + "x", math.nan))
            and math.isfinite(_number(values, prefix + "y", math.nan))
        ),
        timeout=timeout,
        label=f"participant {participant_id} on {observer_pipe}",
    )


def _start_testrun() -> None:
    last_error = ""
    for _ in range(60):
        try:
            local_sync.start_testrun(HOST_PIPE)
            return
        except local_sync.VerifyFailure as exc:
            last_error = str(exc)
            if "still settling" not in last_error:
                raise
            time.sleep(0.25)
    raise LocomotionFailure(
        f"host could not enter the test run: {last_error}"
    )


def _wait_remote_near(
    observer_pipe: str,
    participant_id: int,
    x: float,
    y: float,
    *,
    tolerance: float = 4.0,
    timeout: float = 10.0,
) -> dict[str, str]:
    prefix = f"peer.{participant_id}."
    return _wait(
        lambda: _query(observer_pipe),
        lambda values: math.hypot(
            _number(values, prefix + "x", math.nan) - x,
            _number(values, prefix + "y", math.nan) - y,
        )
        <= tolerance,
        timeout=timeout,
        label=f"participant {participant_id} convergence",
    )


def _configure_native_drive(
    pipe_name: str,
    x: float,
    y: float,
    ticks: int,
    *,
    obstacle_participant_id: int = 0,
) -> dict[str, str]:
    code = f"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
if not _G.__sdmod_locomotion_drive_registered then
  sd.events.on("runtime.tick", function()
    local drive = _G.__sdmod_locomotion_drive
    if type(drive) ~= "table" then return end
    local player = sd.player.get_state()
    if player ~= nil then
      if drive.start_x == nil then
        drive.start_x = tonumber(player.x)
        drive.start_y = tonumber(player.y)
      end
      drive.last_x = tonumber(player.x)
      drive.last_y = tonumber(player.y)
      if drive.obstacle_participant_id ~= 0 then
        local obstacle = sd.bots.get_participant_state(
          drive.obstacle_participant_id)
        if obstacle ~= nil and obstacle.transform_valid then
          local dx = (tonumber(player.x) or 0) -
            (tonumber(obstacle.x) or 0)
          local dy = (tonumber(player.y) or 0) -
            (tonumber(obstacle.y) or 0)
          local distance = math.sqrt(dx * dx + dy * dy)
          drive.min_obstacle_distance = math.min(
            drive.min_obstacle_distance,
            distance)
          drive.max_lateral_displacement = math.max(
            drive.max_lateral_displacement,
            math.abs((tonumber(player.y) or 0) -
              (tonumber(drive.start_y) or 0)))
          drive.obstacle_x = tonumber(obstacle.x)
          drive.obstacle_y = tonumber(obstacle.y)
        end
      end
    end
    if drive.remaining > 0 then
      local ok, result = pcall(
        sd.input.hold_movement_frames,
        drive.x,
        drive.y,
        1)
      drive.write_ok = ok and result == true
      if not drive.write_ok then
        drive.error = tostring(result)
        drive.remaining = 0
        drive.cleared = true
        return
      end
      drive.remaining = drive.remaining - 1
      drive.applied = drive.applied + 1
      return
    end
    if not drive.cleared then
      drive.cleared = true
    end
  end)
  _G.__sdmod_locomotion_drive_registered = true
end
_G.__sdmod_locomotion_drive = {{
  remaining = {ticks},
  applied = 0,
  x = {x:.9f},
  y = {y:.9f},
  write_ok = true,
  cleared = false,
  error = "",
  obstacle_participant_id = {obstacle_participant_id},
  min_obstacle_distance = math.huge,
  max_lateral_displacement = 0,
}}
emit("registered", _G.__sdmod_locomotion_drive_registered)
emit("requested", {ticks})
"""
    values = local_sync.parse_key_values(
        local_sync.lua(pipe_name, code, timeout=8.0)
    )
    if values.get("registered") != "true":
        raise LocomotionFailure(
            f"native movement drive registration failed: {values}"
        )
    return values


def _choose_player_drive(pipe_name: str) -> dict[str, str]:
    return _wait(
        lambda: local_sync.parse_key_values(
            local_sync.lua(
                pipe_name,
                """
local player = sd.player.get_state()
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local best = nil
if player ~= nil then
  for _, distance in ipairs({300, 240, 180}) do
    for index = 0, 15 do
      local radians = index * math.pi / 8
      local dx = math.cos(radians)
      local dy = math.sin(radians)
      local x = player.x + dx * distance
      local y = player.y + dy * distance
      local ok, traversable = pcall(
        sd.nav.test_segment,
        player.x,
        player.y,
        x,
        y)
      if ok and traversable then
        best = {
          x=x, y=y, dx=dx, dy=dy, distance=distance
        }
        break
      end
    end
    if best ~= nil then break end
  end
end
emit("ready", best ~= nil)
emit("x", best and best.x or 0)
emit("y", best and best.y or 0)
emit("dx", best and best.dx or 0)
emit("dy", best and best.dy or 0)
emit("distance", best and best.distance or 0)
""",
                timeout=8.0,
            )
        ),
        lambda values: values.get("ready") == "true",
        timeout=12.0,
        label=f"player traversable movement lane on {pipe_name}",
    )


def _query_native_drive(pipe_name: str) -> dict[str, str]:
    return local_sync.parse_key_values(
        local_sync.lua(
            pipe_name,
            """
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local drive = _G.__sdmod_locomotion_drive or {}
for _, key in ipairs({
  "remaining", "applied", "write_ok", "cleared", "error",
  "start_x", "start_y", "last_x", "last_y",
  "min_obstacle_distance", "max_lateral_displacement",
  "obstacle_x", "obstacle_y"
}) do emit(key, drive[key]) end
local player = sd.player.get_state()
emit("player_x", player and player.x or 0)
emit("player_y", player and player.y or 0)
""",
            timeout=8.0,
        )
    )


def _wait_native_drive(
    pipe_name: str,
    ticks: int,
    *,
    timeout: float,
) -> dict[str, str]:
    return _wait(
        lambda: _query_native_drive(pipe_name),
        lambda values: (
            not values.get("error")
            and _integer(values, "remaining", -1) == 0
            and _integer(values, "applied", -1) == ticks
            and values.get("write_ok") == "true"
            and values.get("cleared") == "true"
        ),
        timeout=timeout,
        label=f"native movement drive on {pipe_name}",
        interval=0.05,
    )


def _native_collision_probe(
    pipe_name: str,
    x: float,
    y: float,
    radius: float,
    circle_block_mask: int = 1,
) -> dict[str, str]:
    code = f"""
local result = sd.debug.test_native_movement_collision(
  {x:.9f}, {y:.9f}, {radius:.9f}, {circle_block_mask}, 0)
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
for _, key in ipairs({{
  "ok", "blocked", "native_result", "radius",
  "circle_block_mask", "overlap_allow_mask", "mode",
  "movement_controller_address", "exception_code"
}}) do emit(key, result[key]) end
"""
    return local_sync.parse_key_values(
        local_sync.lua(pipe_name, code, timeout=8.0)
    )


def _actor_collision_fields(
    pipe_name: str,
    actor_address: int,
) -> dict[str, str]:
    return local_sync.parse_key_values(
        local_sync.lua(
            pipe_name,
            f"""
local actor = {actor_address}
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local function offset(name)
  return sd.debug.layout_offset(name)
end
local function read_u8(name)
  local value = offset(name)
  return value ~= nil and sd.debug.read_u8(actor + value) or nil
end
local function read_u32(name)
  local value = offset(name)
  return value ~= nil and sd.debug.read_u32(actor + value) or nil
end
local function read_ptr(name)
  local value = offset(name)
  return value ~= nil and sd.debug.read_ptr(actor + value) or nil
end
emit("actor", actor)
emit("grid_cell_ptr", read_ptr("actor_grid_cell_ptr"))
emit("grid_member_flag", read_u8("actor_grid_member_flag"))
emit("collision_response_flag",
  read_u8("actor_collision_response_flag"))
emit("movement_suppressed_flag",
  read_u8("actor_movement_suppressed_flag"))
emit("primary_flag_mask", read_u32("actor_primary_flag_mask"))
""",
            timeout=8.0,
        )
    )


def _read_log_after(path: Path, offset: int) -> str:
    with path.open("rb") as handle:
        handle.seek(offset)
        return handle.read().decode("utf-8", "replace")


def _footstep_lines(text: str, participant_id: int) -> list[str]:
    participant_token = f"participant_id={participant_id}"
    return [
        line
        for line in text.splitlines()
        if "[native-audio] event=play" in line
        and "owner=movement.footstep" in line
        and participant_token in line
    ]


def _spawn_bot() -> int:
    values = local_sync.parse_key_values(
        local_sync.lua(
            HOST_PIPE,
            f"""
_G.__sdmod_locomotion_bot = assert(
  sd.bots.spawn{{
    name={json.dumps(BOT_NAME)},
    class={json.dumps(BOT_CLASS)}
  }})
print("participant_id=" ..
  tostring(_G.__sdmod_locomotion_bot:participant_id()))
""",
            timeout=10.0,
        )
    )
    participant_id = _integer(values, "participant_id")
    if participant_id <= 0:
        raise LocomotionFailure(f"bot spawn failed: {values}")
    return participant_id


def _query_bot(
    pipe_name: str,
    participant_id: int,
) -> dict[str, str]:
    return local_sync.parse_key_values(
        local_sync.lua(
            pipe_name,
            f"""
local bot = sd.bots.get_participant_state({participant_id})
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
emit("available", bot ~= nil and bot.available)
emit("materialized", bot ~= nil and bot.entity_materialized)
emit("transform", bot ~= nil and bot.transform_valid)
emit("actor", bot and bot.actor_address or 0)
emit("x", bot and bot.x or 0)
emit("y", bot and bot.y or 0)
emit("radius", bot and bot.actor_address and
  sd.debug.read_float(
    bot.actor_address + sd.debug.layout_offset("actor_collision_radius")) or 0)
""",
            timeout=8.0,
        )
    )


def _wait_bot(
    pipe_name: str,
    participant_id: int,
    *,
    timeout: float = 15.0,
) -> dict[str, str]:
    return _wait(
        lambda: _query_bot(pipe_name, participant_id),
        lambda values: (
            values.get("available") == "true"
            and values.get("materialized") == "true"
            and values.get("transform") == "true"
            and _integer(values, "actor") > 0
            and _number(values, "radius") > 0.0
        ),
        timeout=timeout,
        label=f"bot {participant_id} on {pipe_name}",
    )


def _clear_hostile_actors() -> dict[str, str]:
    code = """
local hp_offset = sd.debug.layout_offset("enemy_current_hp")
local cleaned = 0
local remaining = 0
for _, actor in ipairs(
    sd.world.list_actors and sd.world.list_actors() or {}) do
  local address = tonumber(actor.actor_address) or 0
  local hp = tonumber(actor.hp) or 0
  if address ~= 0 and actor.tracked_enemy and not actor.dead and hp > 0.05 then
    remaining = remaining + 1
    if hp_offset ~= nil then
      sd.debug.write_float(address + hp_offset, 0.0)
    end
    if sd.world.trigger_enemy_death(address) then
      cleaned = cleaned + 1
    end
  end
end
print("cleaned=" .. tostring(cleaned))
print("remaining=" .. tostring(remaining - cleaned))
"""
    last: dict[str, str] = {}
    for _ in range(20):
        last = local_sync.parse_key_values(
            local_sync.lua(HOST_PIPE, code, timeout=8.0)
        )
        if _integer(last, "remaining", -1) == 0:
            return last
        time.sleep(0.1)
    raise LocomotionFailure(
        f"hostile actors could not be cleared from the fixture: {last}"
    )


def _move_bot(participant_id: int, x: float, y: float) -> dict[str, str]:
    values = local_sync.parse_key_values(
        local_sync.lua(
            HOST_PIPE,
            f"""
local bot = nil
for _, candidate in ipairs(sd.bots.list() or {{}}) do
  if tonumber(candidate:participant_id()) == {participant_id} then
    bot = candidate
    break
  end
end
local ok, err = false, "missing_handle"
if bot ~= nil then
  ok, err = bot:move_to({x:.9f}, {y:.9f})
end
print("ok=" .. tostring(ok))
print("error=" .. tostring(err or ""))
""",
            timeout=8.0,
        )
    )
    if values.get("ok") != "true":
        raise LocomotionFailure(f"bot move failed: {values}")
    return values


def _choose_bot_target(participant_id: int) -> dict[str, str]:
    return _wait(
        lambda: local_sync.parse_key_values(
            local_sync.lua(
                HOST_PIPE,
                f"""
local bot = sd.bots.get_participant_state({participant_id})
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local best = nil
if bot ~= nil and bot.transform_valid then
  for _, distance in ipairs({{80, 120, 160}}) do
    for index = 0, 15 do
      local radians = index * math.pi / 8
      local x = bot.x + math.cos(radians) * distance
      local y = bot.y + math.sin(radians) * distance
      local ok, traversable = pcall(
        sd.nav.test_segment,
        bot.x,
        bot.y,
        x,
        y)
      if ok and traversable then
        best = {{x=x, y=y, distance=distance}}
        break
      end
    end
    if best ~= nil then break end
  end
end
emit("ready", best ~= nil)
emit("x", best and best.x or 0)
emit("y", best and best.y or 0)
emit("distance", best and best.distance or 0)
""",
                timeout=8.0,
            )
        ),
        lambda values: values.get("ready") == "true",
        timeout=12.0,
        label=f"bot {participant_id} traversable target",
    )


def _wait_bot_moved(
    participant_id: int,
    start_x: float,
    start_y: float,
    *,
    minimum_distance: float = 30.0,
    timeout: float = 12.0,
) -> dict[str, str]:
    return _wait(
        lambda: _query_bot(HOST_PIPE, participant_id),
        lambda values: math.hypot(
            _number(values, "x", math.nan) - start_x,
            _number(values, "y", math.nan) - start_y,
        )
        >= minimum_distance,
        timeout=timeout,
        label=f"bot {participant_id} native locomotion",
    )


def verify(
    *,
    game_directory: Path,
    output_path: Path,
) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    launch: dict[str, object] = {}
    record: dict[str, Any] = {
        "ok": False,
        "instancePrefix": INSTANCE_PREFIX,
        "ports": {"host": HOST_PORT, "client": CLIENT_PORT},
        "audioExpectedDisabled": True,
    }
    failure: BaseException | None = None
    try:
        launch = local_sync.launch_pair(
            instance_prefix=INSTANCE_PREFIX,
            host_port=HOST_PORT,
            client_port=CLIENT_PORT,
            temporary_host_profile=True,
            kill_existing=False,
            god_mode=True,
            exact_mod_id=ACCEPTANCE_MOD_ID,
            test_survival_boneyard_override=FLAT_BONEYARD,
            test_blank_boneyard=True,
            use_sandbox_preset_flow=True,
            tile_windows=False,
            game_directory=game_directory,
            enable_audio=False,
        )
        record["launch"] = launch
        if launch.get("audioDisabled") is not True:
            raise LocomotionFailure(
                f"game audio was not disabled: {launch}"
            )
        if (
            int(launch.get("hostPort", 0)) != HOST_PORT
            or int(launch.get("clientPort", 0)) != CLIENT_PORT
        ):
            raise LocomotionFailure(
                f"launcher used unexpected ports: {launch}"
            )
        expected_stage = str(
            (ROOT / "runtime/instances").resolve()
        ).lower()
        for role in ("host", "client"):
            executable = _windows_path_to_wsl(
                launch.get(f"{role}ExecutablePath")
            ).resolve()
            if expected_stage not in str(executable).lower():
                raise LocomotionFailure(
                    f"{role} executable is outside the isolated runtime: "
                    f"{executable}"
                )

        bot_id = _spawn_bot()
        record["bot"] = {
            "participantId": bot_id,
            "name": BOT_NAME,
            "class": BOT_CLASS,
        }
        record["bot"]["hubHost"] = _wait_bot(
            HOST_PIPE,
            bot_id,
            timeout=20.0,
        )
        record["bot"]["hubClient"] = _wait_bot(
            CLIENT_PIPE,
            bot_id,
            timeout=20.0,
        )
        _start_testrun()
        local_sync.wait_for_scene(HOST_PIPE, "testrun", 45.0)
        local_sync.wait_for_scene(CLIENT_PIPE, "testrun", 45.0)
        _wait_remote(HOST_PIPE, CLIENT_ID)
        _wait_remote(CLIENT_PIPE, HOST_ID)
        bot_host = _wait_bot(HOST_PIPE, bot_id, timeout=30.0)
        bot_client = _wait_bot(CLIENT_PIPE, bot_id, timeout=30.0)
        record["runReady"] = {
            "hostBot": bot_host,
            "clientBot": bot_client,
            "hostileCleanup": _clear_hostile_actors(),
        }

        host_log = _windows_path_to_wsl(launch.get("hostLog"))
        host_log_offset = host_log.stat().st_size
        client_lane = _choose_player_drive(CLIENT_PIPE)
        _configure_native_drive(
            CLIENT_PIPE,
            _number(client_lane, "dx", 1.0),
            _number(client_lane, "dy", 0.0),
            240,
        )
        client_drive = _wait_native_drive(
            CLIENT_PIPE,
            240,
            timeout=24.0,
        )
        remote_after_drive = _wait_remote(HOST_PIPE, CLIENT_ID)
        time.sleep(0.4)
        native_footstep_dispatch = _footstep_lines(
            _read_log_after(host_log, host_log_offset),
            CLIENT_ID,
        )
        record["remoteFootsteps"] = {
            "lane": client_lane,
            "drive": client_drive,
            "observer": remote_after_drive,
            "native_footstep_dispatch": native_footstep_dispatch,
        }
        if not native_footstep_dispatch:
            raise LocomotionFailure(
                "remote player movement produced no observed native "
                "footstep dispatch"
            )
        remote_x = _number(
            remote_after_drive,
            f"peer.{CLIENT_ID}.x",
            math.nan,
        )
        remote_y = _number(
            remote_after_drive,
            f"peer.{CLIENT_ID}.y",
            math.nan,
        )
        remote_radius = _number(
            remote_after_drive,
            f"peer.{CLIENT_ID}.radius",
            0.0,
        )
        if (
            not math.isfinite(remote_x)
            or not math.isfinite(remote_y)
            or remote_radius <= 0.0
        ):
            raise LocomotionFailure(
                f"remote collision state is invalid: {remote_after_drive}"
            )
        local_sync.place_player(
            CLIENT_PIPE,
            remote_x,
            remote_y,
            0.0,
        )
        client_local = _query(CLIENT_PIPE)
        remote_x = _number(client_local, "player.x", math.nan)
        remote_y = _number(client_local, "player.y", math.nan)
        remote_on_host = _wait_remote_near(
            HOST_PIPE,
            CLIENT_ID,
            remote_x,
            remote_y,
        )
        local_sync.place_player(
            HOST_PIPE,
            remote_x - 220.0,
            remote_y,
            0.0,
        )
        time.sleep(0.5)
        host_start = _query(HOST_PIPE)
        collision_query = _native_collision_probe(
            HOST_PIPE,
            _number(
                remote_on_host,
                f"peer.{CLIENT_ID}.x",
                remote_x,
            ),
            _number(
                remote_on_host,
                f"peer.{CLIENT_ID}.y",
                remote_y,
            ),
            _number(host_start, f"peer.{CLIENT_ID}.radius", remote_radius),
            1,
        )
        collision_diagnostics = {
            "remoteActorFields": _actor_collision_fields(
                HOST_PIPE,
                _integer(
                    remote_on_host,
                    f"peer.{CLIENT_ID}.actor",
                ),
            ),
            "localActorFields": _actor_collision_fields(
                HOST_PIPE,
                _integer(host_start, "player.actor"),
            ),
            "localCenterQuery": _native_collision_probe(
                HOST_PIPE,
                _number(host_start, "player.x", math.nan),
                _number(host_start, "player.y", math.nan),
                _number(host_start, "player.radius", 25.0),
            ),
        }
        record["collisionDiagnostics"] = collision_diagnostics
        if (
            collision_query.get("ok") != "true"
            or collision_query.get("blocked") != "true"
            or _integer(collision_query, "native_result") == 0
            or _integer(collision_query, "exception_code") != 0
        ):
            raise LocomotionFailure(
                "the stock movement collision test did not see the remote "
                f"actor: {collision_query}; "
                f"diagnostics={collision_diagnostics}"
            )

        start_x = _number(host_start, "player.x", math.nan)
        start_y = _number(host_start, "player.y", math.nan)
        _configure_native_drive(
            HOST_PIPE,
            1.0,
            0.0,
            420,
            obstacle_participant_id=CLIENT_ID,
        )
        host_drive = _wait_native_drive(
            HOST_PIPE,
            420,
            timeout=28.0,
        )
        host_final = _query(HOST_PIPE)
        final_x = _number(host_final, "player.x", math.nan)
        final_y = _number(host_final, "player.y", math.nan)
        remote_final = _wait_remote(HOST_PIPE, CLIENT_ID)
        remote_final_x = _number(
            remote_final,
            f"peer.{CLIENT_ID}.x",
            math.nan,
        )
        remote_final_y = _number(
            remote_final,
            f"peer.{CLIENT_ID}.y",
            math.nan,
        )
        local_radius = _number(host_start, "player.radius", 25.0)
        combined_radius = local_radius + remote_radius
        minimum_observed_distance = _number(
            host_drive,
            "min_obstacle_distance",
            0.0,
        )
        final_distance = math.hypot(
            final_x - remote_final_x,
            final_y - remote_final_y,
        )
        passed_through = minimum_observed_distance < (
            combined_radius - 2.0
        )
        if (
            not math.isfinite(final_x)
            or final_x - start_x < 30.0
            or minimum_observed_distance > combined_radius + 8.0
            or passed_through
            or final_distance < combined_radius - 2.0
        ):
            raise LocomotionFailure(
                "the local player was not stopped by the remote actor: "
                f"start=({start_x},{start_y}) "
                f"final=({final_x},{final_y}) "
                f"remote=({remote_final_x},{remote_final_y}) "
                f"minimum_distance={minimum_observed_distance} "
                f"combined_radius={combined_radius}"
            )
        record["remoteCollision"] = {
            "test_native_movement_collision": collision_query,
            "walkthrough": {
                "start": {"x": start_x, "y": start_y},
                "final": {"x": final_x, "y": final_y},
                "remoteFinal": {
                    "x": remote_final_x,
                    "y": remote_final_y,
                },
                "forwardDisplacement": final_x - start_x,
                "minimumObservedDistance":
                    minimum_observed_distance,
                "combinedRadius": combined_radius,
                "finalDistance": final_distance,
                "maximumLateralDisplacement": _number(
                    host_drive,
                    "max_lateral_displacement",
                    0.0,
                ),
                "passedThrough": passed_through,
                "blockedOrDeflectedAtContact":
                    not passed_through,
            },
            "drive": host_drive,
        }

        bot_before = _wait_bot(HOST_PIPE, bot_id)
        bot_start_x = _number(bot_before, "x", math.nan)
        bot_start_y = _number(bot_before, "y", math.nan)
        bot_target = _choose_bot_target(bot_id)
        bot_log_offset = host_log.stat().st_size
        _move_bot(
            bot_id,
            _number(bot_target, "x", math.nan),
            _number(bot_target, "y", math.nan),
        )
        bot_after = _wait_bot_moved(
            bot_id,
            bot_start_x,
            bot_start_y,
        )
        bot_x = _number(bot_after, "x", math.nan)
        bot_y = _number(bot_after, "y", math.nan)
        bot_radius = _number(bot_after, "radius", 0.0)
        time.sleep(0.4)
        bot_footsteps = _footstep_lines(
            _read_log_after(host_log, bot_log_offset),
            bot_id,
        )
        bot_collision = _native_collision_probe(
            HOST_PIPE,
            bot_x,
            bot_y,
            bot_radius,
        )
        bot_inherits_player_family_locomotion = (
            bool(bot_footsteps)
            and bot_collision.get("ok") == "true"
            and bot_collision.get("blocked") == "true"
            and _integer(bot_collision, "native_result") != 0
        )
        if not bot_inherits_player_family_locomotion:
            raise LocomotionFailure(
                "bot did not inherit native collision and footstep behavior: "
                f"footsteps={bot_footsteps} collision={bot_collision}"
            )
        record["botInheritance"] = {
            "bot_inherits_player_family_locomotion":
                bot_inherits_player_family_locomotion,
            "before": bot_before,
            "after": bot_after,
            "target": bot_target,
            "native_footstep_dispatch": bot_footsteps,
            "test_native_movement_collision": bot_collision,
        }
        record["ok"] = True
    except BaseException as exc:
        failure = exc
        record["failure"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
    finally:
        if launch:
            try:
                record["cleanup"] = (
                    local_sync.stop_exact_game_processes(launch)
                )
            except BaseException as cleanup_error:
                record["cleanupFailure"] = {
                    "type": type(cleanup_error).__name__,
                    "message": str(cleanup_error),
                }
                if failure is None:
                    failure = cleanup_error
                    record["ok"] = False
        output_path.write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if failure is not None:
        raise failure
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--game-directory",
        type=Path,
        default=GAME_DIRECTORY,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_PATH,
    )
    args = parser.parse_args()
    result = verify(
        game_directory=args.game_directory,
        output_path=args.output,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
