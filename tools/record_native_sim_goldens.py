#!/usr/bin/env python3
"""Record native movement and RNG browser-rebuild goldens from a live game.

The recorder owns two disposable solo instances. Movement samples are taken
from ``events.runtime.tick`` immediately before the stock player tick. RNG
samples call the retail initializer and integer sampler on an isolated stack
state; the active gameplay stream is observed read-only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from owned_process_ledger import (  # noqa: E402
    OwnedProcessError,
    register_owned_launch,
    stop_owned_process_ids,
)
import verify_local_multiplayer_sync as local_sync  # noqa: E402


MOVEMENT_INSTANCE = "phr-move"
RNG_INSTANCE = "phr-rng"
MOVEMENT_PORTS = (52271, 52272)
RNG_PORTS = (52273, 52274)
MOVEMENT_MOD = "bot.brain"
RNG_MOD = "sample.lua.rng_lab"
RUNTIME_ROOT = ROOT / "runtime" / "physre-live"
LAUNCHER = ROOT / "scripts" / "Launch-LocalSoloSession.ps1"
MOD_LAUNCHER = ROOT / "dist" / "launcher" / "SolomonDarkModLauncher.exe"
LOADER = ROOT / "bin" / "Release" / "Win32" / "SolomonDarkModLoader.dll"
STAGED_LOADER = MOD_LAUNCHER.parent / "SolomonDarkModLoader.dll"
GAME_DIRECTORY = Path(
    "C:/Users/User/Documents/GitHub/SB Modding/"
    "Solomon Dark/SolomonDarkAbandonware"
)
GAME_BINARY = GAME_DIRECTORY / "SolomonDark.exe"
DEFAULT_MOVEMENT_OUTPUT = (
    ROOT / "tests" / "fixtures" / "webgame" / "movement-goldens.json"
)
DEFAULT_RNG_OUTPUT = (
    ROOT / "tests" / "fixtures" / "webgame" / "rng-goldens.json"
)

TICK_INTERVAL_MS = 10
POSITION_EPSILON = 0.0001
SCALAR_EPSILON = 0.000001
NATIVE_RNG_MASK = 0x3FFFFFFF
NATIVE_RNG_WORDS = 55


class CaptureFailure(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CaptureFailure(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_text(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=15.0,
        check=True,
    ).stdout.strip()


def source_revision() -> dict[str, Any]:
    status = git_text("status", "--porcelain")
    return {
        "commit_sha": git_text("rev-parse", "HEAD"),
        "tree_sha": git_text("rev-parse", "HEAD^{tree}"),
        "worktree_dirty": bool(status),
    }


def common_header(
    *,
    instance: str,
    source: dict[str, Any],
    capture_method: str,
) -> dict[str, Any]:
    return {
        "instance": instance,
        "source_commit_sha": source["commit_sha"],
        "source_tree_sha": source["tree_sha"],
        "worktree_dirty_at_capture_start": source["worktree_dirty"],
        "loader_sha256": sha256_file(STAGED_LOADER),
        "build_loader_sha256": sha256_file(LOADER),
        "game_binary_sha256": sha256_file(GAME_BINARY),
        "capture_method": capture_method,
        "captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "epsilon": {
            "position_absolute": POSITION_EPSILON,
            "scalar_absolute": SCALAR_EPSILON,
            "justification": (
                "Native positions, velocities, radii, and movement scalars are "
                "32-bit floats. 1e-4 world units is above the float32 ULP over "
                "the captured arena coordinates while remaining far below any "
                "observed per-tick displacement; scalar comparisons use 1e-6."
            ),
        },
    }


def local_path_from_windows(value: str) -> Path:
    if os.name == "nt":
        return Path(value)
    completed = subprocess.run(
        ["wslpath", "-u", value],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=5.0,
        check=False,
    )
    require(completed.returncode == 0, f"could not convert path {value!r}")
    return Path(completed.stdout.strip())


class OwnedSoloSession:
    def __init__(
        self,
        *,
        instance: str,
        ports: tuple[int, int],
        mod_id: str,
        participant_id: str,
        test_blank_boneyard: bool,
    ) -> None:
        self.instance = instance
        self.ports = ports
        self.mod_id = mod_id
        self.participant_id = participant_id
        self.test_blank_boneyard = test_blank_boneyard
        self.pipe_name = f"SolomonDarkModLoader_LuaExec_{instance}"
        self.runtime_root = RUNTIME_ROOT
        self.process_ids: list[int] = []
        self.launch_result: dict[str, Any] | None = None

    @property
    def stage_root(self) -> Path:
        return (
            self.runtime_root
            / "instances"
            / self.instance.lower()
            / "stage"
        )

    def _rescue_partial_launch(self, ledger_path: Path) -> None:
        if not ledger_path.is_file():
            return
        try:
            document = json.loads(
                ledger_path.read_text(encoding="utf-8-sig")
            )
            process_id = int(document.get("processId", 0))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return
        if process_id <= 0:
            return
        identity = {
            "processId": process_id,
            "instance": self.instance,
            "executablePath": local_sync.path_for_powershell(
                self.stage_root / "SolomonDark.exe"
            ),
        }
        try:
            owned = register_owned_launch(
                identity,
                validate=True,
                require_processes=False,
            )
            stop_owned_process_ids(item.process_id for item in owned)
        except OwnedProcessError:
            return

    def launch(self) -> dict[str, Any]:
        require(self.launch_result is None, "session was already launched")
        require(GAME_DIRECTORY.is_dir(), f"missing game directory: {GAME_DIRECTORY}")
        require(MOD_LAUNCHER.is_file(), f"missing launcher: {MOD_LAUNCHER}")
        require(LOADER.is_file(), f"missing Release loader: {LOADER}")
        require(STAGED_LOADER.is_file(), f"missing staged loader: {STAGED_LOADER}")
        build_loader_hash = sha256_file(LOADER)
        require(
            sha256_file(STAGED_LOADER) == build_loader_hash,
            "staged launcher loader does not match the Release build",
        )
        RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
        ledger = RUNTIME_ROOT / f".{self.instance}-{os.getpid()}-ledger.json"
        result_path = RUNTIME_ROOT / f".{self.instance}-{os.getpid()}-result.json"
        arguments = [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            local_sync.path_for_powershell(LAUNCHER),
            "-Instance",
            self.instance,
            "-Preset",
            "map_create_fire_mind_hub",
            "-RuntimeRoot",
            local_sync.path_for_powershell(self.runtime_root),
            "-LocalPort",
            str(self.ports[0]),
            "-UnusedRemotePort",
            str(self.ports[1]),
            "-ParticipantId",
            self.participant_id,
            "-PlayerName",
            f"Physics RE {self.instance}",
            "-GameDirectory",
            local_sync.path_for_powershell(GAME_DIRECTORY),
            "-LauncherPath",
            local_sync.path_for_powershell(MOD_LAUNCHER),
            "-FreshInstall",
            "-QuickStart",
            "-QuickStartElement",
            "fire",
            "-QuickStartDiscipline",
            "mind",
            "-ExactModIds",
            self.mod_id,
            "-LuaExecTargetModId",
            self.mod_id,
            "-Headless",
            "-ProcessIdOutputPath",
            local_sync.path_for_powershell(ledger),
            "-ResultOutputPath",
            local_sync.path_for_powershell(result_path),
        ]
        if self.test_blank_boneyard:
            arguments.append("-TestBlankBoneyard")
        environment = os.environ.copy()
        environment["SDMOD_DISABLE_AUDIO"] = "1"
        environment["SDMOD_ENABLE_AUDIO"] = "0"
        wrapper: subprocess.Popen[str] | None = None
        try:
            wrapper = subprocess.Popen(
                arguments,
                cwd=ROOT,
                env=environment,
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            deadline = time.monotonic() + 180.0
            while time.monotonic() < deadline and not result_path.is_file():
                return_code = wrapper.poll()
                if return_code is not None:
                    require(
                        return_code == 0,
                        f"solo launcher exited with {return_code}",
                    )
                    break
                time.sleep(0.1)
            require(result_path.is_file(), "solo launcher published no result")
            result = json.loads(result_path.read_text(encoding="utf-8-sig"))
            require(isinstance(result, dict), "solo launch result is not an object")
            require(result.get("success") is True, f"solo launch failed: {result}")
            require(result.get("audioDisabled") is True, "audio was not disabled")
            require(result.get("headlessEnabled") is True, "instance was not headless")
            identities = register_owned_launch(result)
            self.process_ids = [item.process_id for item in identities]
            require(
                len(self.process_ids) == 1,
                f"expected one owned game process: {identities}",
            )
            runtime_root = result.get("runtimeRoot")
            if isinstance(runtime_root, str) and runtime_root:
                self.runtime_root = local_path_from_windows(runtime_root)
            self.launch_result = result
            return result
        except BaseException:
            if self.process_ids:
                self.close()
            else:
                self._rescue_partial_launch(ledger)
            raise
        finally:
            if wrapper is not None and wrapper.poll() is None:
                wrapper.terminate()
                try:
                    wrapper.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    wrapper.kill()
                    wrapper.wait(timeout=5.0)
            ledger.unlink(missing_ok=True)
            result_path.unlink(missing_ok=True)

    def close(self) -> list[dict[str, Any]]:
        process_ids = list(self.process_ids)
        self.process_ids.clear()
        try:
            if not process_ids:
                return []
            return stop_owned_process_ids(process_ids)
        finally:
            local_sync._kill_lua_daemon(self.pipe_name)

    def lua(self, code: str, *, timeout: float = 15.0) -> str:
        return local_sync.lua(self.pipe_name, code, timeout=timeout)

    def values(self, code: str, *, timeout: float = 15.0) -> dict[str, str]:
        return local_sync.parse_key_values(self.lua(code, timeout=timeout))

    def wait_for_pipe(self, timeout: float = 120.0) -> None:
        deadline = time.monotonic() + timeout
        last_error = ""
        while time.monotonic() < deadline:
            try:
                if self.lua("return 'ready'", timeout=5.0).strip() == "ready":
                    return
            except (local_sync.VerifyFailure, subprocess.TimeoutExpired) as error:
                last_error = str(error)
            time.sleep(0.25)
        raise CaptureFailure(f"Lua pipe did not become ready: {last_error}")

    def wait_for_scene(self, expected: str, timeout: float = 180.0) -> None:
        deadline = time.monotonic() + timeout
        last: dict[str, str] = {}
        while time.monotonic() < deadline:
            try:
                last = self.values(
                    """
local scene = sd.world and sd.world.get_scene and sd.world.get_scene() or {}
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
print('scene=' .. tostring(scene.name or scene.kind or ''))
print('transitioning=' .. tostring(scene.transitioning or false))
print('player=' .. tostring(type(player) == 'table'))
"""
                )
            except (local_sync.VerifyFailure, subprocess.TimeoutExpired):
                time.sleep(0.25)
                continue
            if (
                last.get("scene") == expected
                and last.get("transitioning") == "false"
                and last.get("player") == "true"
            ):
                return
            time.sleep(0.25)
        raise CaptureFailure(f"scene {expected!r} did not settle: {last}")


def start_quiet_testrun(session: OwnedSoloSession) -> dict[str, str]:
    deadline = time.monotonic() + 30.0
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = session.values(
            """
local mode_ok, mode_active =
  sd.gameplay.set_manual_enemy_spawner_test_mode(true)
local call_ok, start_result = pcall(sd.hub.start_testrun)
print('mode_ok=' .. tostring(mode_ok))
print('mode_active=' .. tostring(mode_active))
print('call_ok=' .. tostring(call_ok))
print('start_ok=' .. tostring(call_ok and start_result == true))
print('error=' .. tostring(call_ok and '' or start_result))
"""
        )
        require(last.get("mode_ok") == "true", f"manual mode failed: {last}")
        require(last.get("mode_active") == "true", f"manual mode inactive: {last}")
        if last.get("start_ok") == "true":
            session.wait_for_scene("testrun")
            return last
        time.sleep(0.25)
    raise CaptureFailure(f"testrun start did not become available: {last}")


def start_testrun_when_ready(session: OwnedSoloSession) -> dict[str, str]:
    deadline = time.monotonic() + 30.0
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = session.values(
            """
local call_ok, start_result = pcall(sd.hub.start_testrun)
print('call_ok=' .. tostring(call_ok))
print('start_ok=' .. tostring(call_ok and start_result == true))
print('error=' .. tostring(call_ok and '' or start_result))
"""
        )
        if last.get("start_ok") == "true":
            session.wait_for_scene("testrun")
            return last
        time.sleep(0.25)
    raise CaptureFailure(f"testrun start did not become available: {last}")


def place_player(
    session: OwnedSoloSession,
    x: float,
    y: float,
    heading: float = 0.0,
) -> dict[str, str]:
    values = local_sync.place_player(session.pipe_name, x, y, heading)
    require(values.get("clear_control") == "true", f"control clear failed: {values}")
    require(values.get("rebind") == "true", f"player rebind failed: {values}")
    return values


def discover_capture_lane(session: OwnedSoloSession) -> dict[str, float]:
    code = r"""
local function emit(key, value)
  print(key .. '=' .. tostring(value == nil and '' or value))
end
local grid = sd.nav.get_grid(2)
if type(grid) ~= 'table' or type(grid.cells) ~= 'table' or
    grid.refresh_pending == true then
  emit('ready', false)
  return
end
local cells = {}
for _, cell in ipairs(grid.cells) do
  cells[tostring(cell.grid_x) .. ':' .. tostring(cell.grid_y)] = cell
end
local function cell(x, y)
  return cells[tostring(x) .. ':' .. tostring(y)]
end
local function clear_at(x, y)
  local value = cell(x, y)
  return value ~= nil and value.path_traversable == true
end
local function blocked_at(x, y)
  local value = cell(x, y)
  -- The blank arena exposes traversable cells up to its outer wall. The first
  -- cell beyond that finite grid is therefore a blocked wall lane too.
  return value == nil or value.path_traversable ~= true
end
local normals = {
  { 1, 0 }, { -1, 0 }, { 0, 1 }, { 0, -1 },
}
local clear_count, sum_x, sum_y = 0, 0.0, 0.0
for _, value in ipairs(grid.cells) do
  if value.path_traversable == true then
    clear_count = clear_count + 1
    sum_x = sum_x + value.center_x
    sum_y = sum_y + value.center_y
  end
end
local center_x = sum_x / math.max(clear_count, 1)
local center_y = sum_y / math.max(clear_count, 1)
local free = nil
local north = nil
for _, value in ipairs(grid.cells) do
  if value.path_traversable == true then
    local dx = value.center_x - center_x
    local dy = value.center_y - center_y
    local gap = dx * dx + dy * dy
    if free == nil or gap < free.gap then
      free = { x = value.center_x, y = value.center_y, gap = gap }
    end
    if north == nil or value.center_y < north.y or
        (value.center_y == north.y and
          math.abs(value.center_x - center_x) < north.center_gap) then
      north = {
        x = value.center_x,
        y = value.center_y,
        center_gap = math.abs(value.center_x - center_x),
      }
    end
  end
end
local best = nil
for _, stage in ipairs(grid.cells) do
  if stage.path_traversable == true then
    for _, normal in ipairs(normals) do
      local nx, ny = normal[1], normal[2]
      local tx, ty = -ny, nx
      if blocked_at(stage.grid_x + nx, stage.grid_y + ny) then
        local positive = 0
        for step = 0, 12 do
          if clear_at(stage.grid_x + tx * step, stage.grid_y + ty * step) and
              blocked_at(
                stage.grid_x + nx + tx * step,
                stage.grid_y + ny + ty * step) then
            positive = positive + 1
          else
            break
          end
        end
        local negative = 0
        for step = 1, 4 do
          if clear_at(stage.grid_x - tx * step, stage.grid_y - ty * step) and
              blocked_at(
                stage.grid_x + nx - tx * step,
                stage.grid_y + ny - ty * step) then
            negative = negative + 1
          else
            break
          end
        end
        local score = positive + negative
        if positive >= 5 and negative >= 1 and
            (best == nil or score > best.score) then
          local wall = cell(stage.grid_x + nx, stage.grid_y + ny)
          local dx = wall ~= nil and
            (wall.center_x - stage.center_x) or
            nx * (tonumber(grid.cell_width) or 1)
          local dy = wall ~= nil and
            (wall.center_y - stage.center_y) or
            ny * (tonumber(grid.cell_height) or 1)
          local length = math.sqrt(dx * dx + dy * dy)
          best = {
            score = score,
            open_x = stage.center_x,
            open_y = stage.center_y,
            wall_x = wall ~= nil and wall.center_x or stage.center_x + dx,
            wall_y = wall ~= nil and wall.center_y or stage.center_y + dy,
            normal_x = dx / length,
            normal_y = dy / length,
            tangent_x = -dy / length,
            tangent_y = dx / length,
            positive_cells = positive,
            negative_cells = negative,
          }
        end
      end
    end
  end
end
if best == nil then
  emit('ready', false)
  emit('error', 'no_straight_wall_lane')
  return
end
emit('ready', true)
for key, value in pairs(best) do emit(key, value) end
emit('free_x', free and free.x or best.open_x)
emit('free_y', free and free.y or best.open_y)
emit('boundary_start_x', north and north.x or best.open_x)
emit('boundary_start_y', north and north.y or best.open_y)
emit('boundary_normal_x', 0)
emit('boundary_normal_y', -1)
emit('boundary_tangent_x', 1)
emit('boundary_tangent_y', 0)
emit('cell_width', grid.cell_width)
emit('cell_height', grid.cell_height)
"""
    deadline = time.monotonic() + 20.0
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = session.values(code, timeout=12.0)
        if last.get("ready") == "true":
            result = {
                key: float(value)
                for key, value in last.items()
                if key != "ready"
            }
            require(result["positive_cells"] >= 5, f"wall lane too short: {result}")
            return result
        time.sleep(0.25)
    raise CaptureFailure(f"could not discover a wall lane: {last}")


def read_native_movement_baseline(session: OwnedSoloSession) -> dict[str, Any]:
    values = session.values(
        """
local function emit(key, value)
  print(key .. '=' .. tostring(value == nil and '' or value))
end
local player = assert(sd.player.get_state())
local actor = tonumber(player.actor_address) or 0
local progression = tonumber(player.progression_address) or 0
local function off(name) return sd.debug.layout_offset(name) end
local speed_scalar = assert(sd.debug.resolve_game_address(0x00784740))
local input_divisor = assert(sd.debug.resolve_game_address(0x007de810))
local damping_controlled = assert(sd.debug.resolve_game_address(0x00784e20))
local damping_uncontrolled = assert(sd.debug.resolve_game_address(0x00784970))
emit('actor_address', actor)
emit('progression_address', progression)
emit('actor_move_speed_scale', sd.debug.read_float(
  actor + off('actor_move_speed_scale')))
emit('actor_movement_speed_multiplier', sd.debug.read_float(
  actor + off('actor_movement_speed_multiplier')))
emit('actor_move_step_scale', sd.debug.read_float(
  actor + off('actor_move_step_scale')))
emit('actor_collision_radius', sd.debug.read_float(
  actor + off('actor_collision_radius')))
emit('progression_move_speed', sd.debug.read_float(
  progression + off('progression_move_speed')))
emit('speed_scalar_low', sd.debug.read_u32(speed_scalar))
emit('speed_scalar_high', sd.debug.read_u32(speed_scalar + 4))
emit('input_divisor_low', sd.debug.read_u32(input_divisor))
emit('input_divisor_high', sd.debug.read_u32(input_divisor + 4))
emit('damping_controlled_low', sd.debug.read_u32(damping_controlled))
emit('damping_controlled_high', sd.debug.read_u32(damping_controlled + 4))
emit('damping_uncontrolled_low', sd.debug.read_u32(damping_uncontrolled))
emit('damping_uncontrolled_high', sd.debug.read_u32(damping_uncontrolled + 4))
"""
    )

    def integer(name: str) -> int:
        require(values.get(name) not in (None, ""), f"missing movement field {name}")
        return int(values[name], 10)

    def floating(name: str) -> float:
        require(values.get(name) not in (None, ""), f"missing movement field {name}")
        value = float(values[name])
        require(math.isfinite(value), f"non-finite movement field {name}: {value}")
        return value

    def double_from_words(name: str) -> float:
        value = struct.unpack(
            "<d",
            struct.pack(
                "<II",
                integer(f"{name}_low") & 0xFFFFFFFF,
                integer(f"{name}_high") & 0xFFFFFFFF,
            ),
        )[0]
        require(math.isfinite(value), f"non-finite native double {name}: {value}")
        return value

    actor_speed_scale = floating("actor_move_speed_scale")
    actor_multiplier = floating("actor_movement_speed_multiplier")
    progression_speed = floating("progression_move_speed")
    global_speed_scalar = double_from_words("speed_scalar")
    speed_cap = (
        actor_speed_scale
        * actor_multiplier
        * progression_speed
        * global_speed_scalar
    )
    require(speed_cap > 0.0, f"invalid native movement speed cap: {speed_cap}")
    return {
        "actor_address": integer("actor_address"),
        "progression_address": integer("progression_address"),
        "actor_move_speed_scale": actor_speed_scale,
        "actor_movement_speed_multiplier": actor_multiplier,
        "progression_move_speed": progression_speed,
        "global_movement_speed_scalar": global_speed_scalar,
        "computed_velocity_cap": speed_cap,
        "actor_move_step_scale": floating("actor_move_step_scale"),
        "actor_collision_radius": floating("actor_collision_radius"),
        "input_acceleration_divisor": double_from_words("input_divisor"),
        "controlled_velocity_damping": double_from_words("damping_controlled"),
        "uncontrolled_velocity_damping": double_from_words("damping_uncontrolled"),
    }


def arm_movement_trial(
    session: OwnedSoloSession,
    *,
    label: str,
    direction_x: float,
    direction_y: float,
    active_ticks: int,
    total_ticks: int,
    stop_after_knockback: bool = False,
) -> dict[str, str]:
    code = f"""
local function emit(key, value)
  print(key .. '=' .. tostring(value == nil and '' or value))
end
if not _G.__physre_movement_recorder_registered then
  sd.events.on('runtime.tick', function(event)
    local trial = rawget(_G, '__physre_movement_trial')
    if type(trial) ~= 'table' or trial.active ~= true then return end
    local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
    local actor = player and tonumber(player.actor_address) or 0
    if actor == 0 then
      trial.error = 'player_actor_unavailable'
      trial.active = false
      trial.done = true
      return
    end
    local function off(name) return sd.debug.layout_offset(name) end
    local vx = tonumber(sd.debug.read_float(
      actor + off('actor_animation_config_block'))) or 0
    local vy = tonumber(sd.debug.read_float(
      actor + off('actor_animation_drive_parameter'))) or 0
    local speed_scale = tonumber(sd.debug.read_float(
      actor + off('actor_move_speed_scale'))) or 0
    local radius = tonumber(sd.debug.read_float(
      actor + off('actor_collision_radius'))) or 0
    local native_knockback =
      (tonumber(trial.native_knockback_actor) or 0) > 0 and
      (tonumber(trial.native_knockback_calls_remaining) or 0) > 0
    local knockback = native_knockback
    for _, world_actor in ipairs(sd.world.list_actors() or {{}}) do
      if tonumber(world_actor.object_type_id) == 0x7e9 then
        knockback = true
        break
      end
    end
    local index = #trial.samples + 1
    local apply_input = index <= trial.active_ticks
    trial.samples[index] = {{
      index = index - 1,
      native_tick = type(event) == 'table' and
        (tonumber(event.tick_count) or 0) or 0,
      x = tonumber(player.x) or 0,
      y = tonumber(player.y) or 0,
      vx = vx,
      vy = vy,
      speed_scalar = speed_scale,
      radius = radius,
      intent_x = tonumber(player.movement_intent_x) or 0,
      intent_y = tonumber(player.movement_intent_y) or 0,
      applied_input_x = apply_input and trial.direction_x or 0,
      applied_input_y = apply_input and trial.direction_y or 0,
      knockback_present = knockback,
    }}
    if knockback and trial.first_knockback_index == nil then
      trial.first_knockback_index = index - 1
      if trial.stop_after_knockback then
        trial.finish_at = math.min(trial.total_ticks, index + 120)
      end
    end
    if apply_input then
      local ok, result = pcall(
        sd.input.hold_movement_frames,
        trial.direction_x,
        trial.direction_y,
        1)
      if not ok or result ~= true then
        trial.error = tostring(result)
        trial.active = false
        trial.done = true
        return
      end
    end
    if native_knockback then
      local call_ok = pcall(
        sd.debug.call_thiscall_ret_u32,
        0x00600220,
        trial.native_knockback_actor)
      if not call_ok then
        trial.error = 'native_knockback_tick_failed'
        trial.active = false
        trial.done = true
        return
      end
      trial.native_knockback_calls_remaining =
        trial.native_knockback_calls_remaining - 1
    end
    local finish_at = trial.finish_at or trial.total_ticks
    if index >= finish_at then
      trial.active = false
      trial.done = true
      pcall(sd.input.set_native_control_allowance_frames, 0)
    end
  end)
  _G.__physre_movement_recorder_registered = true
end
_G.__physre_movement_trial = {{
  label = {json.dumps(label)},
  active = true,
  done = false,
  error = '',
  direction_x = {direction_x:.17g},
  direction_y = {direction_y:.17g},
  active_ticks = {active_ticks},
  total_ticks = {total_ticks},
  stop_after_knockback = {str(stop_after_knockback).lower()},
  native_knockback_actor = 0,
  native_knockback_calls_remaining = 0,
  samples = {{}},
}}
local allowance_ok, allowance_result = pcall(
  sd.input.set_native_control_allowance_frames,
  math.min(3600, {total_ticks} + 120))
emit('registered', _G.__physre_movement_recorder_registered)
emit('allowance_ok', allowance_ok and allowance_result == true)
emit('label', _G.__physre_movement_trial.label)
"""
    values = session.values(code)
    require(values.get("registered") == "true", f"recorder not registered: {values}")
    require(values.get("allowance_ok") == "true", f"control allowance failed: {values}")
    return values


def movement_trial_status(session: OwnedSoloSession) -> dict[str, str]:
    return session.values(
        """
local trial = rawget(_G, '__physre_movement_trial') or {}
print('done=' .. tostring(trial.done == true))
print('active=' .. tostring(trial.active == true))
print('count=' .. tostring(type(trial.samples) == 'table' and #trial.samples or 0))
print('error=' .. tostring(trial.error or ''))
print('first_knockback_index=' .. tostring(trial.first_knockback_index or ''))
"""
    )


def wait_for_movement_trial(
    session: OwnedSoloSession,
    *,
    timeout: float = 20.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = movement_trial_status(session)
        require(not last.get("error"), f"movement recorder failed: {last}")
        if last.get("done") == "true":
            return last
        time.sleep(0.05)
    raise CaptureFailure(f"movement trial timed out: {last}")


def read_movement_samples(
    session: OwnedSoloSession,
    count: int,
) -> list[dict[str, Any]]:
    fields = (
        "index",
        "native_tick",
        "x",
        "y",
        "vx",
        "vy",
        "speed_scalar",
        "radius",
        "intent_x",
        "intent_y",
        "applied_input_x",
        "applied_input_y",
        "knockback_present",
    )
    integer_fields = {"index", "native_tick"}
    result: list[dict[str, Any]] = []
    for start in range(1, count + 1, 48):
        finish = min(count, start + 47)
        text = session.lua(
            f"""
local trial = assert(rawget(_G, '__physre_movement_trial'))
for index = {start}, {finish} do
  local row = assert(trial.samples[index])
  print(string.format(
    'S|%d|%d|%.17g|%.17g|%.17g|%.17g|%.17g|%.17g|%.17g|%.17g|%.17g|%.17g|%d',
    row.index, row.native_tick, row.x, row.y, row.vx, row.vy,
    row.speed_scalar, row.radius, row.intent_x, row.intent_y,
    row.applied_input_x, row.applied_input_y,
    row.knockback_present and 1 or 0))
end
""",
            timeout=15.0,
        )
        for line in text.splitlines():
            if not line.startswith("S|"):
                continue
            values = line.split("|")[1:]
            require(len(values) == len(fields), f"malformed sample row: {line}")
            row: dict[str, Any] = {}
            for field, value in zip(fields, values):
                if field == "knockback_present":
                    row[field] = value == "1"
                elif field in integer_fields:
                    row[field] = int(value, 10)
                else:
                    row[field] = float(value)
            result.append(row)
    require(len(result) == count, f"read {len(result)} of {count} samples")
    for previous, current in zip(result, result[1:]):
        current["position_step_x"] = current["x"] - previous["x"]
        current["position_step_y"] = current["y"] - previous["y"]
        current["position_step"] = math.hypot(
            current["position_step_x"], current["position_step_y"]
        )
    result[0]["position_step_x"] = 0.0
    result[0]["position_step_y"] = 0.0
    result[0]["position_step"] = 0.0
    return result


def capture_movement_trial(
    session: OwnedSoloSession,
    *,
    label: str,
    start: tuple[float, float],
    direction: tuple[float, float],
    active_ticks: int,
    total_ticks: int,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    placement = place_player(session, *start)
    arm_movement_trial(
        session,
        label=label,
        direction_x=direction[0],
        direction_y=direction[1],
        active_ticks=active_ticks,
        total_ticks=total_ticks,
    )
    status = wait_for_movement_trial(session)
    samples = read_movement_samples(session, int(status["count"], 10))
    require(len(samples) == total_ticks, f"{label} captured wrong tick count")
    displacement = math.hypot(
        samples[-1]["x"] - samples[0]["x"],
        samples[-1]["y"] - samples[0]["y"],
    )
    require(displacement > 5.0, f"{label} displacement too small: {displacement}")
    return {
        "id": label,
        "start": {"x": start[0], "y": start[1]},
        "direction": {"x": direction[0], "y": direction[1]},
        "active_ticks": active_ticks,
        "total_ticks": total_ticks,
        "placement": placement,
        "metadata": metadata or {},
        "samples": samples,
    }


def prepare_native_knockback(session: OwnedSoloSession) -> dict[str, str]:
    values = session.values(
        """
local function emit(key, value)
  print(key .. '=' .. tostring(value == nil and '' or value))
end
local player = assert(sd.player.get_state())
local actor = tonumber(player.actor_address) or 0
local world = tonumber(player.world_address) or 0
local factory = assert(sd.debug.resolve_game_address(0x005b7080))
local context = assert(sd.debug.resolve_game_address(0x0081f630))
local knockback = tonumber(sd.debug.call_thiscall_u32_ret_u32(
  factory, context, 0x7e9)) or 0
local list = knockback + 0x144
local list_vtable = knockback ~= 0 and
  (tonumber(sd.debug.read_u32(list)) or 0) or 0
local add = list_vtable ~= 0 and
  (tonumber(sd.debug.read_u32(list_vtable + 0x10)) or 0) or 0
local target_x = actor ~= 0 and
  tonumber(sd.debug.read_float(actor + 0x18)) or 0
local target_y = actor ~= 0 and
  tonumber(sd.debug.read_float(actor + 0x1c)) or 0
local seeded = knockback ~= 0 and actor ~= 0 and world ~= 0 and add ~= 0 and
  sd.debug.write_ptr(knockback + 0x58, world) and
  sd.debug.write_float(knockback + 0x18, target_x - 100.0) and
  sd.debug.write_float(knockback + 0x1c, target_y) and
  sd.debug.write_float(knockback + 0x13c, 100.0) and
  sd.debug.write_float(knockback + 0x140, 0.0) and
  sd.debug.call_thiscall_u32(add, list, actor)
local count = knockback ~= 0 and
  (tonumber(sd.debug.read_i32(knockback + 0x14c)) or 0) or 0
emit('ok', seeded and count == 1)
emit('knockback_actor', knockback)
emit('target_actor', actor)
emit('world', world)
emit('target_center_x', target_x)
emit('target_center_y', target_y)
emit('origin_x', target_x - 100.0)
emit('origin_y', target_y)
emit('affected_count', count)
"""
    )
    require(values.get("ok") == "true", f"native Knockback setup failed: {values}")
    require(int(values.get("affected_count", "0"), 10) == 1, f"bad target list: {values}")
    return values


def release_native_knockback(
    session: OwnedSoloSession,
    actor_address: int,
) -> dict[str, str]:
    values = session.values(
        f"""
local actor = {actor_address}
local vtable = tonumber(sd.debug.read_u32(actor)) or 0
local destructor = vtable ~= 0 and
  (tonumber(sd.debug.read_u32(vtable)) or 0) or 0
local ok = destructor ~= 0 and
  sd.debug.call_thiscall_u32(destructor, actor, 1)
print('ok=' .. tostring(ok == true))
"""
    )
    require(values.get("ok") == "true", f"Knockback release failed: {values}")
    return values


def capture_knockback_trial(
    session: OwnedSoloSession,
    *,
    start: tuple[float, float],
) -> dict[str, Any]:
    placement = place_player(session, *start)
    arm_movement_trial(
        session,
        label="knockback_contact",
        direction_x=0.0,
        direction_y=0.0,
        active_ticks=0,
        total_ticks=900,
        stop_after_knockback=True,
    )
    prepared = prepare_native_knockback(session)
    knockback_actor = int(prepared["knockback_actor"], 10)
    armed = session.values(
        f"""
local trial = assert(rawget(_G, '__physre_movement_trial'))
trial.native_knockback_actor = {knockback_actor}
trial.native_knockback_calls_remaining = 2
print('ok=true')
"""
    )
    require(armed.get("ok") == "true", f"Knockback arm failed: {armed}")
    status = wait_for_movement_trial(session, timeout=15.0)
    require(
        status.get("first_knockback_index") not in (None, ""),
        f"retail Knockback tick was not observed: {status}",
    )
    samples = read_movement_samples(session, int(status["count"], 10))
    require(any(row["knockback_present"] for row in samples), "knockback was not sampled")
    require(
        max(row["position_step"] for row in samples) > 0.2,
        "knockback actor did not produce player displacement",
    )
    released = release_native_knockback(session, knockback_actor)
    return {
        "id": "knockback_contact",
        "start": {"x": start[0], "y": start[1]},
        "direction": {"x": 0.0, "y": 0.0},
        "active_ticks": 0,
        "total_ticks": len(samples),
        "placement": placement,
        "metadata": {
            "trigger": (
                "retail Knockback factory type 0x07E9 plus two direct calls "
                "to its native tick 0x00600220 through existing sd.debug "
                "raw-call probes"
            ),
            "observed_knockback_object_type": "0x07E9",
            "first_knockback_index": int(status["first_knockback_index"], 10),
            "prepared": prepared,
            "released": released,
        },
        "samples": samples,
    }


def validate_free_movement(scenarios: list[dict[str, Any]]) -> None:
    by_id = {scenario["id"]: scenario for scenario in scenarios}
    for label, axis, sign in (
        ("cardinal_east", "x", 1),
        ("cardinal_west", "x", -1),
        ("cardinal_south", "y", 1),
        ("cardinal_north", "y", -1),
    ):
        samples = by_id[label]["samples"]
        delta = samples[-1][axis] - samples[0][axis]
        require(delta * sign > 20.0, f"{label} moved the wrong way: {delta}")
        cross = "y" if axis == "x" else "x"
        cross_delta = samples[-1][cross] - samples[0][cross]
        require(abs(cross_delta) < 0.05, f"{label} drifted cross-axis: {cross_delta}")
    east = by_id["cardinal_east"]["samples"]
    diagonal = by_id["diagonal_southeast"]["samples"]
    east_distance = math.hypot(
        east[-1]["x"] - east[0]["x"],
        east[-1]["y"] - east[0]["y"],
    )
    diagonal_distance = math.hypot(
        diagonal[-1]["x"] - diagonal[0]["x"],
        diagonal[-1]["y"] - diagonal[0]["y"],
    )
    require(
        math.isclose(diagonal_distance, east_distance, rel_tol=0.03),
        f"diagonal normalization mismatch: {diagonal_distance} vs {east_distance}",
    )


def validate_wall_movement(
    scenarios: list[dict[str, Any]],
    lane: dict[str, float],
) -> None:
    by_id = {scenario["id"]: scenario for scenario in scenarios}
    normal = (lane["boundary_normal_x"], lane["boundary_normal_y"])
    tangent = (lane["boundary_tangent_x"], lane["boundary_tangent_y"])
    reference_normal_displacement: float | None = None
    for angle in (0, 30, 60):
        samples = by_id[f"wall_{angle}_degrees"]["samples"]
        dx = samples[-1]["x"] - samples[0]["x"]
        dy = samples[-1]["y"] - samples[0]["y"]
        normal_displacement = dx * normal[0] + dy * normal[1]
        tangent_displacement = dx * tangent[0] + dy * tangent[1]
        if angle == 0:
            require(
                5.0 < normal_displacement < 80.0,
                f"normal wall drive did not stop early: {normal_displacement}",
            )
            reference_normal_displacement = normal_displacement
            require(
                abs(tangent_displacement) < 0.05,
                f"normal wall impact drifted: {tangent_displacement}",
            )
        else:
            require(reference_normal_displacement is not None, "wall reference missing")
            require(
                math.isclose(
                    normal_displacement,
                    reference_normal_displacement,
                    rel_tol=0.0,
                    abs_tol=0.1,
                ),
                f"wall {angle} crossed the 0-degree contact plane: "
                f"{normal_displacement} vs {reference_normal_displacement}",
            )
            require(
                tangent_displacement > 10.0,
                f"wall {angle} did not slide: {tangent_displacement}",
            )


def record_movement(
    source: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    session = OwnedSoloSession(
        instance=MOVEMENT_INSTANCE,
        ports=MOVEMENT_PORTS,
        mod_id=MOVEMENT_MOD,
        participant_id="0x2000000000002F01",
        test_blank_boneyard=True,
    )
    launch: dict[str, Any] | None = None
    cleanup: list[dict[str, Any]] = []
    failure: BaseException | None = None
    document: dict[str, Any] = {}
    try:
        launch = session.launch()
        session.wait_for_pipe()
        session.wait_for_scene("hub")
        start_quiet_testrun(session)
        lane = discover_capture_lane(session)
        native_baseline = read_native_movement_baseline(session)
        open_start = (lane["free_x"], lane["free_y"])
        scenarios: list[dict[str, Any]] = []
        for label, direction in (
            ("cardinal_east", (1.0, 0.0)),
            ("cardinal_west", (-1.0, 0.0)),
            ("cardinal_south", (0.0, 1.0)),
            ("cardinal_north", (0.0, -1.0)),
            ("diagonal_southeast", (math.sqrt(0.5), math.sqrt(0.5))),
        ):
            scenarios.append(
                capture_movement_trial(
                    session,
                    label=label,
                    start=open_start,
                    direction=direction,
                    active_ticks=40,
                    total_ticks=120,
                    metadata={"collision_lane": "open nav-grid cell"},
                )
            )
        wall_start = (lane["boundary_start_x"], lane["boundary_start_y"])
        normal = (lane["boundary_normal_x"], lane["boundary_normal_y"])
        tangent = (lane["boundary_tangent_x"], lane["boundary_tangent_y"])
        for angle in (0, 30, 60):
            radians = math.radians(angle)
            direction = (
                normal[0] * math.cos(radians) + tangent[0] * math.sin(radians),
                normal[1] * math.cos(radians) + tangent[1] * math.sin(radians),
            )
            scenarios.append(
                capture_movement_trial(
                    session,
                    label=f"wall_{angle}_degrees",
                    start=wall_start,
                    direction=direction,
                    active_ticks=100,
                    total_ticks=180,
                    metadata={
                        "incidence_degrees_from_wall_normal": angle,
                        "wall_normal": {"x": normal[0], "y": normal[1]},
                        "wall_tangent": {"x": tangent[0], "y": tangent[1]},
                        "native_contact_contract": {
                            "derivation": (
                                "measured by the 0-degree trace; the 30/60-degree "
                                "traces must stop at the same normal coordinate"
                            ),
                        },
                    },
                )
            )
        scenarios.append(capture_knockback_trial(session, start=open_start))
        validate_free_movement(scenarios)
        validate_wall_movement(scenarios, lane)
        document = {
            "schema_version": 1,
            "header": {
                **common_header(
                    instance=MOVEMENT_INSTANCE,
                    source=source,
                    capture_method=(
                        "Live headless solo instance; Lua events.runtime.tick "
                        "samples immediately before PlayerActor_Tick while "
                        "sd.input.hold_movement_frames publishes one scripted "
                        "native-control frame. Stock MoveStep/collision and "
                        "the retail Knockback implementation remain unmodified."
                    ),
                ),
                "ports": list(MOVEMENT_PORTS),
                "audio_disabled": True,
                "tick_interval_ms": TICK_INTERVAL_MS,
                "sample_phase": "loader runtime.tick, pre-stock PlayerActor_Tick",
                "fixture_is_machine_recorded": True,
                "launch_process_ids": list(session.process_ids),
            },
            "native_layout": {
                "position": ["actor+0x18", "actor+0x1C"],
                "velocity_accumulator": ["actor+0x158", "actor+0x15C"],
                "movement_scalar": "actor+0x218",
                "collision_radius": "actor+0x30",
            },
            "native_baseline": native_baseline,
            "capture_lane": lane,
            "scenarios": scenarios,
        }
    except BaseException as error:
        failure = error
    finally:
        try:
            cleanup = session.close()
        except BaseException as cleanup_error:
            if failure is None:
                failure = cleanup_error
        if document:
            document["header"]["cleanup"] = cleanup
    if failure is not None:
        raise failure
    require(launch is not None, "movement launch record missing")
    return document, launch


def model_native_rng(
    seed: int,
    bound: int,
    count: int,
) -> tuple[list[int], int, int, list[int]]:
    words = [seed & NATIVE_RNG_MASK, 1]
    while len(words) < NATIVE_RNG_WORDS:
        words.append((words[-1] + words[-2]) & NATIVE_RNG_MASK)
    index_a = 0
    index_b = 31
    power_of_two = 2
    while power_of_two < bound:
        power_of_two <<= 1
    outputs: list[int] = []
    for _ in range(count):
        value = (words[index_b] + words[index_a]) & NATIVE_RNG_MASK
        words[index_a] = value
        index_a = (index_a + 1) % NATIVE_RNG_WORDS
        index_b = (index_b + 1) % NATIVE_RNG_WORDS
        outputs.append(((value >> 6) & (power_of_two - 1)) % bound)
    return outputs, index_a, index_b, words


def sample_native_rng(
    session: OwnedSoloSession,
    seed: int,
    bound: int,
    count: int,
) -> dict[str, Any]:
    text = session.lua(
        f"""
local result = assert(sd.debug.sample_native_rng({seed}, {bound}, {count}))
print('M|seed|' .. tostring(result.seed))
print('M|range|' .. tostring(result.range))
print('M|count|' .. tostring(result.count))
print('M|stream|' .. tostring(result.stream))
print('M|final_index_a|' .. tostring(result.final_index_a))
print('M|final_index_b|' .. tostring(result.final_index_b))
for index, value in ipairs(result.outputs or {{}}) do
  print('O|' .. tostring(index - 1) .. '|' .. tostring(value))
end
for index, value in ipairs(result.final_state_words or {{}}) do
  print('W|' .. tostring(index - 1) .. '|' .. tostring(value))
end
""",
        timeout=20.0,
    )
    metadata: dict[str, str] = {}
    outputs: list[int] = []
    words: list[int] = []
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) == 3 and parts[0] == "M":
            metadata[parts[1]] = parts[2]
        elif len(parts) == 3 and parts[0] == "O":
            require(int(parts[1], 10) == len(outputs), f"RNG output gap: {line}")
            outputs.append(int(parts[2], 10))
        elif len(parts) == 3 and parts[0] == "W":
            require(int(parts[1], 10) == len(words), f"RNG state gap: {line}")
            words.append(int(parts[2], 10))
    expected_outputs, expected_index_a, expected_index_b, expected_words = (
        model_native_rng(seed, bound, count)
    )
    require(outputs == expected_outputs, f"native RNG outputs diverged for seed={seed}")
    require(
        int(metadata.get("final_index_a", "-1"), 10) == expected_index_a,
        f"native RNG index A diverged for seed={seed}",
    )
    require(
        int(metadata.get("final_index_b", "-1"), 10) == expected_index_b,
        f"native RNG index B diverged for seed={seed}",
    )
    require(words == expected_words, f"native RNG state diverged for seed={seed}")
    require(metadata.get("stream") == "native-private-stack-state", f"bad stream: {metadata}")
    return {
        "seed": seed,
        "range": bound,
        "count": count,
        "stream": metadata["stream"],
        "outputs": outputs,
        "final_index_a": expected_index_a,
        "final_index_b": expected_index_b,
        "final_state_words": words,
    }


def read_active_rng_state(session: OwnedSoloSession) -> dict[str, Any]:
    text = session.lua(
        """
local global_address = assert(sd.debug.resolve_game_address(0x00818b08))
local state_address = tonumber(sd.debug.read_u32(global_address)) or 0
print('M|global_address|' .. tostring(global_address))
print('M|state_address|' .. tostring(state_address))
print('M|index_a|' .. tostring(sd.debug.read_u32(state_address)))
print('M|index_b|' .. tostring(sd.debug.read_u32(state_address + 4)))
print('M|divisor|' .. tostring(sd.debug.read_u32(state_address + 0xe4)))
for index = 0, 54 do
  print('W|' .. tostring(index) .. '|' ..
    tostring(sd.debug.read_u32(state_address + 8 + index * 4)))
end
print('M|published_seed|' .. tostring(sd.rng.get_seed()))
""",
        timeout=20.0,
    )
    metadata: dict[str, int] = {}
    words: list[int] = []
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) != 3:
            continue
        if parts[0] == "M":
            metadata[parts[1]] = int(parts[2], 10)
        elif parts[0] == "W":
            require(int(parts[1], 10) == len(words), f"active state gap: {line}")
            words.append(int(parts[2], 10))
    require(len(words) == NATIVE_RNG_WORDS, "active RNG state has wrong width")
    require(metadata.get("state_address", 0) > 0, "active RNG pointer was null")
    require(metadata.get("divisor") == 100000, f"bad float divisor: {metadata}")
    return {**metadata, "state_words": words}


def record_rng(
    source: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    session = OwnedSoloSession(
        instance=RNG_INSTANCE,
        ports=RNG_PORTS,
        mod_id=RNG_MOD,
        participant_id="0x2000000000002F02",
        test_blank_boneyard=True,
    )
    launch: dict[str, Any] | None = None
    cleanup: list[dict[str, Any]] = []
    failure: BaseException | None = None
    document: dict[str, Any] = {}
    published_seed = 0x01234567
    try:
        launch = session.launch()
        session.wait_for_pipe()
        session.wait_for_scene("hub")
        samples = [
            sample_native_rng(session, 1, 16, 64),
            sample_native_rng(session, published_seed, 100, 96),
            sample_native_rng(session, published_seed, 1001, 96),
            sample_native_rng(session, NATIVE_RNG_MASK, 999999, 96),
        ]
        selected = session.values(
            f"""
local selected = sd.rng.set_seed({published_seed})
print('selected=' .. tostring(selected))
print('observed=' .. tostring(sd.rng.get_seed()))
"""
        )
        require(
            int(selected.get("selected", "0"), 10) == published_seed,
            f"set_seed did not return the seed: {selected}",
        )
        require(
            int(selected.get("observed", "0"), 10) == published_seed,
            f"get_seed did not observe the seed: {selected}",
        )
        started = start_testrun_when_ready(session)
        active_state = read_active_rng_state(session)
        require(
            active_state["published_seed"] == published_seed,
            f"run seed was not retained: {active_state}",
        )
        document = {
            "schema_version": 1,
            "header": {
                **common_header(
                    instance=RNG_INSTANCE,
                    source=source,
                    capture_method=(
                        "Live headless solo instance. sd.debug.sample_native_rng "
                        "calls retail 0x00401110/0x00401170 on an isolated 0xE8-byte "
                        "stack state; sd.rng.set_seed publishes the observed run "
                        "seed; active 0x00818B08 state is read-only after entry."
                    ),
                ),
                "ports": list(RNG_PORTS),
                "audio_disabled": True,
                "fixture_is_machine_recorded": True,
                "launch_process_ids": list(session.process_ids),
            },
            "algorithm": {
                "family": "additive_lagged_fibonacci",
                "modulus": 1 << 30,
                "state_word_bits": 30,
                "state_word_count": NATIVE_RNG_WORDS,
                "lags": [55, 24],
                "initial_indices": [0, 31],
                "integer_output": (
                    "((new_word >> 6) & (ceil_pow2(range)-1)) % range"
                ),
            },
            "observed_run_seed": {
                "selected_in_hub": published_seed,
                "get_seed_in_hub": int(selected["observed"], 10),
                "active_state_after_world_generation": active_state,
                "note": (
                    "World generation has already consumed the shared stream; "
                    "this state is a read-only post-generation observation, not "
                    "the initializer state."
                ),
            },
            "sequences": samples,
        }
    except BaseException as error:
        failure = error
    finally:
        try:
            cleanup = session.close()
        except BaseException as cleanup_error:
            if failure is None:
                failure = cleanup_error
        if document:
            document["header"]["cleanup"] = cleanup
    if failure is not None:
        raise failure
    require(launch is not None, "RNG launch record missing")
    return document, launch


def write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--movement-output", type=Path, default=DEFAULT_MOVEMENT_OUTPUT)
    parser.add_argument("--rng-output", type=Path, default=DEFAULT_RNG_OUTPUT)
    parser.add_argument("--evidence-output", type=Path)
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow a smoke capture from an uncommitted tree; final goldens reject this.",
    )
    args = parser.parse_args()

    source = source_revision()
    require(
        args.allow_dirty or not source["worktree_dirty"],
        "refusing final live goldens from a dirty worktree",
    )
    movement, movement_launch = record_movement(source)
    rng, rng_launch = record_rng(source)
    write_json(args.movement_output, movement)
    write_json(args.rng_output, rng)
    summary = {
        "ok": True,
        "source": source,
        "movement_output": str(args.movement_output),
        "rng_output": str(args.rng_output),
        "movement_scenarios": len(movement["scenarios"]),
        "rng_sequences": len(rng["sequences"]),
        "launches": {
            "movement": movement_launch,
            "rng": rng_launch,
        },
        "cleanup": {
            "movement": movement["header"]["cleanup"],
            "rng": rng["header"]["cleanup"],
        },
    }
    if args.evidence_output is not None:
        write_json(args.evidence_output, summary)
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
