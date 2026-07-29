"""Exact-process headless game bridge for live bot-policy training."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Mapping

from owned_process_ledger import (
    OwnedProcessError,
    register_owned_launch,
    stop_owned_process_ids,
)
import verify_local_multiplayer_sync as local_sync

from . import spec
from .model import BotPolicy, render_lua_weights

ROOT = Path(__file__).resolve().parents[2]
MAX_ROLLOUTS_PER_RESPONSE = 256
RUN_READY_STABILITY_SECONDS = 0.35
BOT_MATERIALIZATION_GRACE_SECONDS = 15.0
PRIMARY_ENTRY_BY_ELEMENT = {
    "fire": 0x10,
    "water": 0x20,
    "earth": 0x28,
    "air": 0x18,
    "ether": 0x08,
}
SOLO_LAUNCHER = ROOT / "scripts" / "Launch-LocalSoloSession.ps1"
DEFAULT_LAUNCHER = (
    ROOT / "dist" / "launcher" / "SolomonDarkModLauncher.exe"
)
if os.name == "nt":
    DEFAULT_GAME_DIRECTORY = Path(
        "C:/Users/User/Documents/GitHub/SB Modding/"
        "Solomon Dark/SolomonDarkAbandonware"
    )
else:
    DEFAULT_GAME_DIRECTORY = Path(
        "/mnt/c/Users/User/Documents/GitHub/SB Modding/"
        "Solomon Dark/SolomonDarkAbandonware"
    )


class BridgeError(RuntimeError):
    pass


@dataclass(frozen=True)
class RolloutRecord:
    trajectory_version: int
    episode_id: int
    participant_id: int
    simulation_tick: int
    observation: list[float]
    movement_mask: list[bool]
    cast_mask: list[bool]
    movement_action: int
    cast_action: int
    old_log_probability: float
    old_value: float
    reward: float
    done: bool


def _path_for_powershell(path: Path) -> str:
    resolved = path.resolve()
    if os.name == "nt":
        return str(resolved)
    completed = subprocess.run(
        ["wslpath", "-w", str(resolved)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=5.0,
        check=False,
    )
    converted = completed.stdout.strip()
    if completed.returncode != 0 or not converted:
        raise BridgeError(
            f"could not convert path for PowerShell: {path}: "
            f"{completed.stderr.strip()}"
        )
    return converted


def _local_path(path: str) -> Path:
    if os.name == "nt":
        return Path(path)
    completed = subprocess.run(
        ["wslpath", "-u", path],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=5.0,
        check=False,
    )
    converted = completed.stdout.strip()
    if completed.returncode != 0 or not converted:
        raise BridgeError(f"could not convert Windows path: {path}")
    return Path(converted)


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp"
    )
    with temporary.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _bits(value: str, expected: int, label: str) -> list[bool]:
    if len(value) != expected or any(bit not in "01" for bit in value):
        raise BridgeError(f"invalid {label} bit mask: {value!r}")
    return [bit == "1" for bit in value]


def _floats(value: str, expected: int, label: str) -> list[float]:
    try:
        result = [float(item) for item in value.split(",")]
    except ValueError as error:
        raise BridgeError(f"invalid {label} vector") from error
    if len(result) != expected:
        raise BridgeError(
            f"{label} vector has {len(result)} entries, expected {expected}"
        )
    if not all(math.isfinite(item) for item in result):
        raise BridgeError(f"{label} vector contains a non-finite value")
    return result


def parse_rollout_output(
    output: str,
    *,
    expected_count: int,
) -> list[RolloutRecord]:
    records: list[RolloutRecord] = []
    for line in output.splitlines():
        if not line.startswith("R\t"):
            continue
        fields = line.split("\t")
        if len(fields) != 14:
            raise BridgeError(
                f"rollout frame has {len(fields)} fields"
            )
        try:
            record = RolloutRecord(
                trajectory_version=int(fields[1]),
                episode_id=int(fields[2]),
                participant_id=int(fields[3]),
                simulation_tick=int(fields[4]),
                movement_action=int(fields[5]),
                cast_action=int(fields[6]),
                old_log_probability=float(fields[7]),
                old_value=float(fields[8]),
                reward=float(fields[9]),
                done=fields[10] == "1",
                observation=_floats(
                    fields[11],
                    len(spec.OBSERVATION_NAMES),
                    "observation",
                ),
                movement_mask=_bits(
                    fields[12],
                    len(spec.MOVEMENT_ACTION_NAMES),
                    "movement",
                ),
                cast_mask=_bits(
                    fields[13],
                    len(spec.CAST_ACTION_NAMES),
                    "cast",
                ),
            )
        except ValueError as error:
            raise BridgeError("rollout frame contains an invalid number") from error
        if record.trajectory_version != spec.TRAJECTORY_VERSION:
            raise BridgeError(
                "rollout trajectory version does not match trainer"
            )
        if not (
            math.isfinite(record.old_log_probability)
            and math.isfinite(record.old_value)
            and math.isfinite(record.reward)
        ):
            raise BridgeError("rollout frame contains a non-finite scalar")
        if not 0 <= record.movement_action < len(spec.MOVEMENT_ACTION_NAMES):
            raise BridgeError("rollout movement action is outside the policy head")
        if not 0 <= record.cast_action < len(spec.CAST_ACTION_NAMES):
            raise BridgeError("rollout cast action is outside the policy head")
        if not record.movement_mask[record.movement_action]:
            raise BridgeError("rollout selected a masked movement action")
        if not record.cast_mask[record.cast_action]:
            raise BridgeError("rollout selected a masked cast action")
        records.append(record)
    if len(records) != expected_count:
        raise BridgeError(
            f"drained {len(records)} rollouts, expected {expected_count}"
        )
    return records


GOD_MODE = r"""
local hp_offset = assert(
  sd.debug.layout_offset('progression_hp'))
local max_hp_offset = assert(
  sd.debug.layout_offset('progression_max_hp'))
local mp_offset = assert(
  sd.debug.layout_offset('progression_mp'))
local max_mp_offset = assert(
  sd.debug.layout_offset('progression_max_mp'))

local function sustain_progression(progression)
  progression = tonumber(progression) or 0
  if progression == 0 then
    return 0
  end
  local max_hp = tonumber(
    sd.debug.read_float(progression + max_hp_offset)) or 0
  local max_mp = tonumber(
    sd.debug.read_float(progression + max_mp_offset)) or 0
  if max_hp > 0 then
    sd.debug.write_float(progression + hp_offset, max_hp)
  end
  if max_mp > 0 then
    sd.debug.write_float(progression + mp_offset, max_mp)
  end
  return 1
end

local function sustain()
  local count = 0
  local player = sd.player.get_state()
  if type(player) == 'table' then
    local progression =
      tonumber(player.progression_address) or 0
    if progression == 0 then
      local actor = tonumber(player.actor_address) or 0
      local actor_offset = tonumber(
        sd.debug.layout_offset(
          'actor_progression_runtime_state')) or 0
      if actor ~= 0 and actor_offset ~= 0 then
        progression =
          tonumber(sd.debug.read_ptr(actor + actor_offset)) or 0
      end
    end
    count = count + sustain_progression(progression)
  end
  for _, bot in ipairs(sd.bots.list()) do
    local participant_id = bot:participant_id()
    local state = sd.bots.get_participant_state(participant_id)
    if type(state) == 'table' then
      count = count + sustain_progression(
        state.progression_runtime_state_address)
    end
  end
  return count
end
if not _G.__sdmod_ml_training_godmode then
  local last_tick = -10
  sd.events.on('runtime.tick', function(event)
    local tick = type(event) == 'table' and
      tonumber(event.tick_count) or 0
    if tick <= 0 or tick - last_tick >= 10 then
      last_tick = tick
      sustain()
    end
  end)
  _G.__sdmod_ml_training_godmode = true
end
print('registered=true')
print('initial_apply=' .. tostring(sustain()))
"""


STATUS = r"""
local training = assert(
  rawget(_G, 'bot_policy_training'),
  'bot policy training API is unavailable')
local status = training.status()
local debug = rawget(_G, 'bot_brain_debug') or {}
print('enabled=' .. tostring(status.enabled))
print('episode_id=' .. tostring(status.episode_id or 0))
print('capacity=' .. tostring(status.capacity or 0))
print('buffered=' .. tostring(status.buffered or 0))
print('dropped=' .. tostring(status.dropped or 0))
print('recorded=' .. tostring(status.recorded or 0))
print('generation=' .. tostring(
  status.policy and status.policy.generation or 0))
print('clock_source=' .. tostring(debug.clock_source or ''))
print('simulation_tick=' .. tostring(
  debug.simulation_tick_count or 0))
print('active_bot_count=' .. tostring(
  debug.active_bot_count or 0))
print('behavior=' .. tostring(debug.behavior or ''))
print('policy_decision_count=' .. tostring(
  debug.policy_decision_count or 0))
print('move_accepted=' .. tostring(debug.move_accepted or 0))
print('cast_accepted=' .. tostring(debug.cast_accepted or 0))
"""

RUN_READY_STATUS = r"""
local scene = sd.world.get_scene()
local multiplayer = sd.runtime.get_multiplayer_state() or {}
local loading = multiplayer.run_loading_barrier or {}
local handles = sd.bots.list()
local bot = handles[1]
local participant_id = 0
local position_ok = false
local hp_ok = false
local alive_ok = false
local slot_ok = false
local member = nil
if bot ~= nil then
  local ok, x, y = pcall(function()
    return bot:position()
  end)
  position_ok =
    ok and tonumber(x) ~= nil and tonumber(y) ~= nil
  local hp_call_ok, hp = pcall(function()
    return bot:hp()
  end)
  local max_hp_call_ok, max_hp = pcall(function()
    return bot:max_hp()
  end)
  hp_ok =
    hp_call_ok and tonumber(hp) ~= nil and
    max_hp_call_ok and (tonumber(max_hp) or 0) > 0
  local alive_call_ok, alive = pcall(function()
    return bot:alive()
  end)
  alive_ok = alive_call_ok and alive == true
  local slot_call_ok, slot = pcall(function()
    return bot:slot()
  end)
  slot = tonumber(slot) or -1
  slot_ok = slot_call_ok and slot >= 1 and slot <= 3
  participant_id = tonumber(bot:participant_id()) or 0
  for _, candidate in ipairs(multiplayer.participants or {}) do
    if tonumber(candidate.participant_id) == participant_id then
      member = candidate
      break
    end
  end
end
print('scene=' .. tostring(
  scene and (scene.name or scene.kind) or ''))
print('session_state=' .. tostring(
  multiplayer.session_state or ''))
print('loading_active=' .. tostring(loading.active or false))
print('loading_released=' .. tostring(
  loading.released or false))
print('loading_timed_out=' .. tostring(
  loading.timed_out or false))
print('loading_run_nonce=' .. tostring(
  loading.run_nonce or 0))
print('loading_release_reason=' .. tostring(
  loading.release_reason or ''))
print('loading_expected=' .. tostring(
  loading.expected_participant_count or 0))
print('loading_ready=' .. tostring(
  loading.ready_participant_count or 0))
print('bot_count=' .. tostring(#handles))
print('bot_position_ok=' .. tostring(position_ok))
print('bot_hp_ok=' .. tostring(hp_ok))
print('bot_alive=' .. tostring(alive_ok))
print('bot_slot_ok=' .. tostring(slot_ok))
print('member_in_run=' .. tostring(
  member and member.in_run or false))
print('member_runtime_valid=' .. tostring(
  member and member.runtime_valid or false))
print('member_controller=' .. tostring(
  member and member.controller_kind or ''))
"""

TRAINING_ARENA_MANAGER = r"""
local enemy_type_id = 1001
local enemy_hp = 750.0
local spawn_distance = 260.0

local function live_enemy_count()
  local count = 0
  for _, actor in ipairs(sd.world.list_actors() or {}) do
    if actor.tracked_enemy == true and
        actor.dead ~= true and
        (tonumber(actor.hp) or 0) > 0.05 then
      count = count + 1
    end
  end
  return count
end

local function bot_position()
  local bot = (sd.bots.list() or {})[1]
  if bot == nil then
    return nil
  end
  local ok, x, y = pcall(function()
    return bot:position()
  end)
  if not ok then
    return nil
  end
  x, y = tonumber(x), tonumber(y)
  if x == nil or y == nil then
    return nil
  end
  return x, y
end

local manager = rawget(_G, '__sdmod_ml_training_arena')
if type(manager) ~= 'table' then
  manager = {
    pending_request_id = 0,
    spawn_count = 0,
    failed_spawn_count = 0,
    last_error = '',
    last_tick = -25,
  }
  _G.__sdmod_ml_training_arena = manager

  sd.events.on('runtime.tick', function(event)
    local tick = type(event) == 'table' and
      tonumber(event.tick_count) or 0
    if tick > 0 and tick - manager.last_tick < 25 then
      return
    end
    manager.last_tick = tick

    if manager.pending_request_id > 0 then
      local result = sd.gameplay.get_last_manual_run_enemy_spawn(
        manager.pending_request_id)
      if type(result) ~= 'table' then
        return
      end
      if result.ok == true then
        local actor = tonumber(result.actor_address) or 0
        if actor > 0 then
          sd.gameplay.set_run_enemy_health(
            actor,
            enemy_hp,
            enemy_hp)
        end
        manager.spawn_count = manager.spawn_count + 1
      else
        manager.failed_spawn_count =
          manager.failed_spawn_count + 1
        manager.last_error = tostring(result.error or '')
      end
      manager.pending_request_id = 0
    end

    if live_enemy_count() > 0 or
        manager.pending_request_id > 0 then
      return
    end
    local x, y = bot_position()
    if x == nil then
      return
    end
    local ok, spawn_error, request_id =
      sd.gameplay.spawn_manual_run_enemy({
        type_id = enemy_type_id,
        x = x + spawn_distance,
        y = y,
        freeze_on_spawn = false,
        allow_direct_arena_spawn = true,
      })
    if ok == true then
      manager.pending_request_id = tonumber(request_id) or 0
    else
      manager.failed_spawn_count =
        manager.failed_spawn_count + 1
      manager.last_error = tostring(spawn_error or '')
    end
  end)
end
print('registered=true')
print('spawn_count=' .. tostring(manager.spawn_count or 0))
print('failed_spawn_count=' ..
  tostring(manager.failed_spawn_count or 0))
print('last_error=' .. tostring(manager.last_error or ''))
"""

TRAINING_ARENA_STATUS = r"""
local live = 0
for _, actor in ipairs(sd.world.list_actors() or {}) do
  if actor.tracked_enemy == true and
      actor.dead ~= true and
      (tonumber(actor.hp) or 0) > 0.05 then
    live = live + 1
  end
end
print('live_enemy_count=' .. tostring(live))
local manager = rawget(_G, '__sdmod_ml_training_arena') or {}
print('pending_request_id=' ..
  tostring(manager.pending_request_id or 0))
print('spawn_count=' .. tostring(manager.spawn_count or 0))
print('failed_spawn_count=' ..
  tostring(manager.failed_spawn_count or 0))
print('last_error=' .. tostring(manager.last_error or ''))
"""


class SoloSession:
    def __init__(
        self,
        *,
        instance: str,
        game_directory: Path = DEFAULT_GAME_DIRECTORY,
        launcher_path: Path = DEFAULT_LAUNCHER,
        runtime_root: Path | None = None,
        local_port: int = 49780,
        unused_remote_port: int = 49781,
        headless: bool = True,
        element: str = "fire",
        discipline: str = "arcane",
    ) -> None:
        self.instance = instance
        self.game_directory = game_directory
        self.launcher_path = launcher_path
        self.runtime_root = runtime_root or ROOT / "runtime"
        self.local_port = local_port
        self.unused_remote_port = unused_remote_port
        self.headless = headless
        self.element = element
        self.discipline = discipline
        self.pipe_name = f"SolomonDarkModLoader_LuaExec_{instance}"
        self.launch_result: dict[str, Any] | None = None
        self.process_ids: list[int] = []

    @property
    def stage_root(self) -> Path:
        return (
            self.runtime_root
            / "instances"
            / self.instance.lower()
            / "stage"
        )

    @property
    def settings_path(self) -> Path:
        return (
            self.stage_root
            / ".sdmod"
            / "mod-settings"
            / "bot.brain.json"
        )

    def _rescue_partial(self, ledger_path: Path) -> None:
        if not ledger_path.is_file():
            return
        try:
            document = json.loads(
                ledger_path.read_text(encoding="utf-8-sig")
            )
            process_id = int(document.get("processId", 0))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return
        if process_id <= 0:
            return
        launch = {
            "processId": process_id,
            "instance": self.instance,
            "executablePath": _path_for_powershell(
                self.stage_root / "SolomonDark.exe"
            ),
        }
        try:
            register_owned_launch(
                launch,
                validate=True,
                require_processes=False,
            )
            stop_owned_process_ids([process_id])
        except OwnedProcessError:
            pass

    def launch(self) -> dict[str, Any]:
        if self.launch_result is not None:
            raise BridgeError("session is already launched")
        if not self.game_directory.is_dir():
            raise BridgeError(
                f"game directory does not exist: {self.game_directory}"
            )
        if not self.launcher_path.is_file():
            raise BridgeError(
                f"launcher does not exist: {self.launcher_path}"
            )

        ledger_path = (
            self.runtime_root
            / f".ml-bot-launch-{self.instance}-{os.getpid()}.json"
        )
        result_path = (
            self.runtime_root
            / f".ml-bot-result-{self.instance}-{os.getpid()}.json"
        )
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        arguments = [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            _path_for_powershell(SOLO_LAUNCHER),
            "-Instance",
            self.instance,
            "-Preset",
            f"map_create_{self.element}_{self.discipline}_hub",
            "-RuntimeRoot",
            _path_for_powershell(self.runtime_root),
            "-LocalPort",
            str(self.local_port),
            "-UnusedRemotePort",
            str(self.unused_remote_port),
            "-ParticipantId",
            "0x2000000000002A01",
            "-PlayerName",
            "ML Trainer",
            "-GameDirectory",
            _path_for_powershell(self.game_directory),
            "-LauncherPath",
            _path_for_powershell(self.launcher_path),
            "-FreshInstall",
            "-DisableMultiplayerTransport",
            "-ExactModIds",
            "bot.brain",
            "-ProcessIdOutputPath",
            _path_for_powershell(ledger_path),
            "-ResultOutputPath",
            _path_for_powershell(result_path),
        ]
        if self.headless:
            arguments.append("-Headless")

        try:
            completed = subprocess.run(
                arguments,
                cwd=ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=120.0,
                check=False,
            )
            if completed.returncode != 0:
                raise BridgeError(
                    "solo launch failed "
                    f"with exit code {completed.returncode}"
                )
            if not result_path.is_file():
                raise BridgeError(
                    "solo launch did not publish its result document"
                )
            result = json.loads(
                result_path.read_text(encoding="utf-8-sig")
            )
            if not isinstance(result, dict):
                raise BridgeError("solo launch result is not an object")
            if result.get("success") is not True:
                raise BridgeError(f"solo launch was not successful: {result}")
            identities = register_owned_launch(result)
            self.process_ids = [
                identity.process_id for identity in identities
            ]
            self.launch_result = result
            runtime_root = result.get("runtimeRoot")
            if isinstance(runtime_root, str) and runtime_root:
                self.runtime_root = _local_path(runtime_root)
            return result
        except BaseException:
            if self.process_ids:
                self.close()
            else:
                self._rescue_partial(ledger_path)
            raise
        finally:
            ledger_path.unlink(missing_ok=True)
            result_path.unlink(missing_ok=True)

    def close(self) -> list[dict[str, Any]]:
        process_ids = list(self.process_ids)
        self.process_ids = []
        try:
            if not process_ids:
                return []
            return stop_owned_process_ids(process_ids)
        finally:
            local_sync._kill_lua_daemon(self.pipe_name)

    def __enter__(self) -> "SoloSession":
        self.launch()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def lua(self, code: str, *, timeout: float = 15.0) -> str:
        return local_sync.lua(self.pipe_name, code, timeout=timeout)

    def wait_for_pipe(self, *, timeout: float = 45.0) -> None:
        deadline = time.monotonic() + timeout
        last_error = ""
        while time.monotonic() < deadline:
            try:
                if self.lua("return 'ready'", timeout=5.0).strip() == "ready":
                    return
            except (local_sync.VerifyFailure, subprocess.TimeoutExpired) as error:
                last_error = str(error)
            time.sleep(0.25)
        raise BridgeError(
            f"Lua pipe {self.pipe_name} did not become ready: {last_error}"
        )

    def drive_new_game_to_hub(
        self,
        *,
        timeout: float = 75.0,
    ) -> dict[str, str]:
        deadline = time.monotonic() + timeout
        activated: set[str] = set()
        attempts: dict[str, int] = {}
        last: dict[str, str] = {}
        while time.monotonic() < deadline:
            last = local_sync.parse_key_values(
                self.lua(
                    """
local scene = sd.world.get_scene() or {}
local snapshot = sd.ui.get_snapshot() or {}
print('scene=' .. tostring(scene.name or scene.kind or ''))
print('transitioning=' .. tostring(
  scene.transitioning or false))
print('surface=' .. tostring(snapshot.surface_id or ''))
print('generation=' .. tostring(snapshot.generation or 0))
for index, element in ipairs(snapshot.elements or {}) do
  if index > 16 then break end
  print('action.' .. tostring(index) .. '=' ..
    tostring(element.action_id or ''))
end
""",
                    timeout=10.0,
                )
            )
            if (
                last.get("scene") == "hub"
                and last.get("transitioning") == "false"
            ):
                return last

            actions = {
                value
                for key, value in last.items()
                if key.startswith("action.") and value
            }
            candidates = (
                ("dialog", "dialog.primary"),
                (
                    "control_scheme_picker",
                    "control_scheme_picker.select_wasd",
                ),
                ("main_menu", "main_menu.play"),
                ("main_menu", "main_menu.new_game"),
                (
                    "create",
                    f"create.select_element_{self.element}",
                ),
                (
                    "create",
                    f"create.select_discipline_{self.discipline}",
                ),
            )
            surface = last.get("surface", "")
            dispatched = False
            for expected_surface, action_id in candidates:
                if (
                    surface != expected_surface
                    or action_id not in actions
                    or action_id in activated
                ):
                    continue
                attempts[action_id] = attempts.get(action_id, 0) + 1
                if attempts[action_id] > 3:
                    raise BridgeError(
                        "fresh-game UI action did not latch after "
                        f"three attempts: {expected_surface}:{action_id}"
                    )
                values = local_sync.parse_key_values(
                    self.lua(
                        f"""
local ok, request = sd.ui.activate_action(
  {json.dumps(action_id)},
  {json.dumps(expected_surface)})
print('ok=' .. tostring(ok))
print('request_id=' .. tostring(request or 0))
""",
                        timeout=10.0,
                    )
                )
                if values.get("ok") == "true":
                    request_id = int(
                        values.get("request_id", "0")
                    )
                    dispatch_deadline = min(
                        deadline,
                        time.monotonic() + 15.0,
                    )
                    while time.monotonic() < dispatch_deadline:
                        dispatch = local_sync.parse_key_values(
                            self.lua(
                                f"""
local state = sd.ui.get_action_dispatch(
  {request_id})
print('available=' .. tostring(
  type(state) == 'table'))
print('status=' .. tostring(
  type(state) == 'table' and
  state.status or ''))
print('error=' .. tostring(
  type(state) == 'table' and
  state.error_message or ''))
""",
                                timeout=10.0,
                            )
                        )
                        status = dispatch.get("status", "")
                        if (
                            status == "completed"
                            or status.startswith("dispatched")
                        ):
                            dispatched = True
                            break
                        if status == "failed":
                            raise BridgeError(
                                "fresh-game UI action failed: "
                                f"{expected_surface}:{action_id}: "
                                f"{dispatch.get('error', '')}"
                            )
                        time.sleep(0.1)
                    if not dispatched:
                        raise BridgeError(
                            "fresh-game UI action timed out: "
                            f"{expected_surface}:{action_id}"
                        )
                    if action_id.startswith(
                        "create.select_element_"
                    ):
                        readiness_deadline = min(
                            deadline,
                            time.monotonic() + 5.0,
                        )
                        ready = False
                        while (
                            time.monotonic()
                            < readiness_deadline
                        ):
                            selection = (
                                local_sync.parse_key_values(
                                    self.lua(
                                        """
local owner = 0
local snapshot = sd.ui.get_snapshot() or {}
for _, element in ipairs(
    snapshot.elements or {}) do
  if element.surface_id == 'create' or
      element.surface_root_id == 'create' then
    owner = tonumber(
      element.surface_object_ptr) or 0
    if owner ~= 0 then break end
  end
end
local selected = owner ~= 0 and
  sd.debug.read_u32(owner + 0x1A4) or nil
local enabled = owner ~= 0 and
  sd.debug.read_u8(owner + 0x228) or nil
print('selected=' .. tostring(selected))
print('discipline_enabled=' ..
  tostring(enabled or 0))
print('ready=' .. tostring(
  selected ~= nil and
  selected ~= 4294967295 and
  (tonumber(enabled) or 0) ~= 0))
""",
                                        timeout=10.0,
                                    )
                                )
                            )
                            if selection.get("ready") == "true":
                                ready = True
                                break
                            time.sleep(0.1)
                        if not ready:
                            dispatched = False
                    if dispatched:
                        activated.add(action_id)
                break
            time.sleep(0.5 if dispatched else 0.1)
        raise BridgeError(
            f"could not drive a fresh game to the hub: {last}"
        )

    def _write_roster(
        self,
        roster: list[dict[str, str]],
    ) -> dict[str, str]:
        _atomic_write_json(
            self.settings_path,
            {
                "schemaVersion": 1,
                "values": {
                    "focus_bot_key": "NONE",
                    "kite_radius": 340,
                    "offense_enabled": True,
                    "roster": roster,
                    "think_profile": "standard",
                },
            },
        )
        values = local_sync.parse_key_values(
            self.lua(
                """
local result = sd.__settings_reload('bot.brain')
print('ok=' .. tostring(result.ok))
print('changed=' .. table.concat(result.changed or {}, ','))
print('error=' .. tostring(result.error or ''))
for key, message in pairs(result.entry_errors or {}) do
  print('entry_error.' .. key .. '=' .. tostring(message))
end
""",
                timeout=10.0,
            )
        )
        entry_errors = {
            key: value
            for key, value in values.items()
            if key.startswith("entry_error.")
        }
        transient_spawn = (
            set(entry_errors) == {"entry_error.roster"}
            and (
                "spawn transform unavailable"
                in entry_errors["entry_error.roster"]
            )
        )
        if (
            values.get("ok") != "true"
            and not transient_spawn
        ) or (entry_errors and not transient_spawn):
            raise BridgeError(
                f"could not apply learned bot settings: {values}"
            )
        if "roster" not in values.get("changed", "").split(","):
            raise BridgeError(
                f"learned bot roster did not change: {values}"
            )
        return values

    def write_empty_roster(self) -> dict[str, str]:
        return self._write_roster([])

    def write_learned_roster(self) -> dict[str, str]:
        return self._write_roster(
            [
                {
                    "name": "Learner",
                    "element": self.element,
                    "behavior": "learned",
                    "discipline": self.discipline,
                }
            ]
        )

    def wait_for_empty_roster(self, *, timeout: float = 30.0) -> dict[str, str]:
        deadline = time.monotonic() + timeout
        last: dict[str, str] = {}
        while time.monotonic() < deadline:
            try:
                last = self.status()
                if int(last.get("active_bot_count", "0")) == 0:
                    return last
            except (
                ValueError,
                local_sync.VerifyFailure,
                subprocess.TimeoutExpired,
            ):
                pass
            time.sleep(0.2)
        raise BridgeError(f"bot roster did not become empty: {last}")

    def wait_for_learned_bot(self, *, timeout: float = 30.0) -> dict[str, str]:
        deadline = time.monotonic() + timeout
        last: dict[str, str] = {}
        while time.monotonic() < deadline:
            try:
                last = self.status()
                if (
                    int(last.get("active_bot_count", "0")) >= 1
                    and last.get("behavior") == "learned"
                ):
                    return last
            except (
                ValueError,
                local_sync.VerifyFailure,
                subprocess.TimeoutExpired,
            ):
                pass
            time.sleep(0.2)
        raise BridgeError(f"learned bot did not become ready: {last}")

    def wait_for_run_ready(self, *, timeout: float = 45.0) -> dict[str, str]:
        if self.launch_result is None:
            raise BridgeError("session is not launched")
        transport_enabled = bool(
            self.launch_result.get("multiplayerTransportEnabled", True)
        )
        deadline = time.monotonic() + timeout
        last: dict[str, str] = {}
        ready_since: float | None = None
        ready_nonce = 0
        while time.monotonic() < deadline:
            try:
                last = local_sync.parse_key_values(
                    self.lua(RUN_READY_STATUS, timeout=10.0)
                )
                expected = int(last.get("loading_expected", "0"))
                ready = int(last.get("loading_ready", "0"))
                multiplayer_lifecycle_ready = (
                    last.get("scene") == "testrun"
                    and last.get("session_state") == "in-boneyard"
                    and last.get("loading_active") == "true"
                    and last.get("loading_released") == "true"
                    and last.get("loading_timed_out") == "false"
                    and int(last.get("loading_run_nonce", "0")) > 0
                    and last.get("loading_release_reason")
                    == "all-participants-ready"
                    and expected > 0
                    and ready == expected
                    and last.get("member_in_run") == "true"
                    and last.get("member_runtime_valid") == "true"
                    and last.get("member_controller") == "LuaBrain"
                )
                offline_lifecycle_ready = (
                    last.get("scene") == "testrun"
                    and last.get("session_state") == "not-in-game"
                    and last.get("loading_active") == "false"
                    and last.get("loading_released") == "false"
                    and last.get("loading_timed_out") == "false"
                    and int(last.get("loading_run_nonce", "0")) == 0
                    and expected == 0
                    and ready == 0
                    and last.get("member_in_run") == "true"
                    and last.get("member_runtime_valid") == "true"
                    and last.get("member_controller") == "LuaBrain"
                )
                lifecycle_ready = (
                    multiplayer_lifecycle_ready
                    if transport_enabled
                    else offline_lifecycle_ready
                )
                if lifecycle_ready:
                    nonce = (
                        int(last["loading_run_nonce"])
                        if transport_enabled
                        else 1
                    )
                    now = time.monotonic()
                    if nonce != ready_nonce:
                        ready_nonce = nonce
                        ready_since = now
                    if (
                        ready_since is None
                        or now - ready_since
                        < RUN_READY_STABILITY_SECONDS
                    ):
                        time.sleep(0.1)
                        continue
                    bot_ready = (
                        int(last.get("bot_count", "0")) == 1
                        and last.get("bot_position_ok") == "true"
                        and last.get("bot_hp_ok") == "true"
                        and last.get("bot_alive") == "true"
                        and last.get("bot_slot_ok") == "true"
                    )
                    last["bot_ready"] = str(bot_ready).lower()
                    return last
                ready_since = None
                ready_nonce = 0
            except (
                ValueError,
                local_sync.VerifyFailure,
                subprocess.TimeoutExpired,
            ):
                pass
            time.sleep(0.1)
        raise BridgeError(f"test run did not become ready: {last}")

    def wait_for_bot_materialized(
        self,
        *,
        timeout: float = 45.0,
    ) -> dict[str, str]:
        deadline = time.monotonic() + timeout
        started_at = time.monotonic()
        respawn_requested = False
        last: dict[str, str] = {}
        while time.monotonic() < deadline:
            try:
                last = local_sync.parse_key_values(
                    self.lua(RUN_READY_STATUS, timeout=10.0)
                )
                if (
                    last.get("scene") == "testrun"
                    and int(last.get("bot_count", "0")) == 1
                    and last.get("bot_position_ok") == "true"
                    and last.get("bot_hp_ok") == "true"
                    and last.get("bot_alive") == "true"
                    and last.get("bot_slot_ok") == "true"
                    and last.get("member_in_run") == "true"
                    and last.get("member_runtime_valid") == "true"
                    and last.get("member_controller") == "LuaBrain"
                ):
                    return last
                if (
                    not respawn_requested
                    and time.monotonic() - started_at
                    >= BOT_MATERIALIZATION_GRACE_SECONDS
                ):
                    action = local_sync.parse_key_values(
                        self.lua(
                            """
local result = sd.__settings_invoke_action(
  'bot.brain',
  'respawn_bot')
print('ok=' .. tostring(result.ok))
print('error=' .. tostring(result.error or ''))
""",
                            timeout=10.0,
                        )
                    )
                    if action.get("ok") != "true":
                        raise BridgeError(
                            "could not rematerialize the learned bot: "
                            f"{action}"
                        )
                    respawn_requested = True
            except (
                ValueError,
                local_sync.VerifyFailure,
                subprocess.TimeoutExpired,
            ):
                pass
            time.sleep(0.1)
        raise BridgeError(
            f"learned bot did not materialize in the test run: {last}"
        )

    def enable_god_mode(self) -> dict[str, str]:
        values = local_sync.parse_key_values(self.lua(GOD_MODE))
        if values.get("registered") != "true":
            raise BridgeError(f"failed to register god mode: {values}")
        return values

    def start_test_run(self, *, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        last_error = ""
        while time.monotonic() < deadline:
            try:
                values = local_sync.parse_key_values(
                    self.lua(
                        """
local ok, result = pcall(sd.hub.start_testrun)
print('pcall_ok=' .. tostring(ok))
print('result=' .. tostring(result))
""",
                        timeout=8.0,
                    )
                )
                if (
                    values.get("pcall_ok") == "true"
                    and values.get("result") == "true"
                ):
                    local_sync.wait_for_scene(
                        self.pipe_name,
                        "testrun",
                        timeout=timeout,
                    )
                    return
                last_error = str(values)
            except (local_sync.VerifyFailure, subprocess.TimeoutExpired) as error:
                last_error = str(error)
            time.sleep(0.25)
        raise BridgeError(f"could not start test run: {last_error}")

    def prepare_training_combat(
        self,
        *,
        timeout: float = 20.0,
    ) -> dict[str, str]:
        setup = local_sync.parse_key_values(
            self.lua(
                """
local combat = sd.gameplay.get_combat_state() or {}
local recover = (tonumber(combat.wave_index) or 0) > 0
local prelude_pcall_ok, prelude = pcall(function()
  if recover then
    return sd.gameplay.enable_combat_prelude({
      recover_untracked_wave = true,
    })
  end
  return sd.gameplay.enable_combat_prelude()
end)
local mode_call_ok, manual_mode =
  sd.gameplay.set_manual_enemy_spawner_test_mode(true)
print('recover_untracked_wave=' .. tostring(recover))
print('prelude_pcall_ok=' .. tostring(prelude_pcall_ok))
print('prelude=' .. tostring(prelude))
print('mode_call_ok=' .. tostring(mode_call_ok))
print('manual_mode=' .. tostring(manual_mode))
""",
                timeout=min(timeout, 10.0),
            )
        )
        if (
            setup.get("prelude_pcall_ok") != "true"
            or setup.get("prelude") != "true"
            or setup.get("mode_call_ok") != "true"
            or setup.get("manual_mode") != "true"
        ):
            raise BridgeError(
                f"could not prepare direct training combat: {setup}"
            )
        return setup

    def prime_training_progression(
        self,
        *,
        max_level_steps: int = 64,
        timeout: float = 30.0,
    ) -> dict[str, str]:
        if max_level_steps <= 0:
            raise ValueError("max_level_steps must be positive")
        try:
            primary_entry = PRIMARY_ENTRY_BY_ELEMENT[self.element]
        except KeyError as error:
            raise BridgeError(
                f"unsupported training element: {self.element}"
            ) from error

        values = local_sync.parse_key_values(
            self.lua(
                f"""
local primary_entry = {primary_entry}
local max_level_steps = {max_level_steps}
local level_offset = assert(
  sd.debug.layout_offset('progression_level'))
local next_xp_offset = assert(
  sd.debug.layout_offset('progression_next_xp_threshold'))

local handles = sd.bots.list() or {{}}
local bot = handles[1]
if bot == nil then
  print('ready=false')
  print('error=no learned bot handle')
  return
end
local participant_id = tonumber(bot:participant_id()) or 0
local bot_state = sd.bots.get_state(participant_id)
local progression = type(bot_state) == 'table' and
  tonumber(bot_state.progression_runtime_state_address) or 0
local player = sd.player.get_state()
local source_progression = type(player) == 'table' and
  tonumber(player.progression_address) or 0
if participant_id <= 0 or progression == 0 or
    source_progression == 0 then
  print('ready=false')
  print('error=training progression is not materialized')
  print('participant_id=' .. tostring(participant_id))
  print('progression=' .. tostring(progression))
  print('source_progression=' .. tostring(source_progression))
  return
end

local applied_choices = 0
local matched_primary = false
local last_error = ''
local elemental_primary = {{
  [8] = true,
  [16] = true,
  [24] = true,
  [32] = true,
  [40] = true,
}}
local function native_stats()
  local stats = sd.debug.resolve_native_primary_spell_stats(
    progression,
    primary_entry,
    primary_entry)
  if type(stats) ~= 'table' then
    return false, {{}}
  end
  local ready =
    stats.resolved == true and
    (tonumber(stats.mana_spend_cost) or 0) > 0 and
    (tonumber(stats.damage) or 0) > 0
  return ready, stats
end

local function apply_pending_choice()
  local choices = sd.bots.get_skill_choices(participant_id)
  if type(choices) ~= 'table' or
      choices.pending ~= true or
      type(choices.options) ~= 'table' or
      #choices.options == 0 then
    return false
  end
  local selected_index = nil
  for index, option in ipairs(choices.options) do
    if tonumber(option.id) == primary_entry then
      selected_index = index
      matched_primary = true
      break
    end
  end
  if selected_index == nil then
    for index, option in ipairs(choices.options) do
      if elemental_primary[tonumber(option.id)] ~= true then
        selected_index = index
        break
      end
    end
  end
  if selected_index == nil then
    last_error =
      'native choices contained only conflicting elemental primaries'
    return false
  end
  local ok, accepted = pcall(
    sd.bots.choose_skill,
    participant_id,
    selected_index,
    tonumber(choices.generation) or 0)
  if not ok or accepted ~= true then
    last_error = 'native skill choice apply failed: ' ..
      tostring(accepted)
    return false
  end
  applied_choices = applied_choices + 1
  return true
end

local ready, stats = native_stats()
local level_steps = 0
while not ready and level_steps < max_level_steps do
  apply_pending_choice()
  ready, stats = native_stats()
  if ready then
    break
  end

  local level = tonumber(
    sd.debug.read_i32(progression + level_offset)) or 0
  local next_xp = tonumber(
    sd.debug.read_float(progression + next_xp_offset)) or 0
  if level <= 0 or next_xp <= 0 or next_xp ~= next_xp then
    last_error = 'native level or next-xp is invalid'
    break
  end
  local sync_ok, synced = pcall(
    sd.bots.debug_sync_level_up,
    {{
      level = level + 1,
      experience = math.ceil(next_xp + 10.0),
      source_progression_address = source_progression,
    }})
  if not sync_ok or synced ~= true then
    last_error = 'native level-up sync failed: ' ..
      tostring(synced)
    break
  end
  level_steps = level_steps + 1
  if not apply_pending_choice() then
    last_error = last_error ~= '' and last_error or
      'native level-up produced no selectable option'
    break
  end
  ready, stats = native_stats()
end

print('ready=' .. tostring(ready))
print('participant_id=' .. tostring(participant_id))
print('primary_entry=' .. tostring(primary_entry))
print('progression=' .. tostring(progression))
print('source_progression=' .. tostring(source_progression))
print('level_steps=' .. tostring(level_steps))
print('applied_choices=' .. tostring(applied_choices))
print('matched_primary=' .. tostring(matched_primary))
print('resolved=' .. tostring(stats.resolved == true))
print('mana_spend_cost=' ..
  tostring(tonumber(stats.mana_spend_cost) or 0))
print('damage=' .. tostring(tonumber(stats.damage) or 0))
print('error=' .. tostring(
  ready and '' or
  (last_error ~= '' and last_error or
   (tostring(stats.error or '') ~= '' and
      tostring(stats.error) or
      'primary spell did not become available'))))
""",
                timeout=timeout,
            )
        )
        if (
            values.get("ready") != "true"
            or values.get("matched_primary") != "true"
            or float(values.get("mana_spend_cost", "0")) <= 0.0
            or float(values.get("damage", "0")) <= 0.0
        ):
            raise BridgeError(
                f"could not prime native training spell: {values}"
            )
        return values

    def start_training_arena(
        self,
        *,
        timeout: float = 20.0,
    ) -> dict[str, str]:
        manager = local_sync.parse_key_values(
            self.lua(TRAINING_ARENA_MANAGER, timeout=min(timeout, 10.0))
        )
        if manager.get("registered") != "true":
            raise BridgeError(
                f"could not register the training arena manager: {manager}"
            )
        return manager

    def wait_for_training_enemy(
        self,
        *,
        timeout: float = 20.0,
    ) -> dict[str, str]:
        deadline = time.monotonic() + timeout
        last: dict[str, str] = {}
        while time.monotonic() < deadline:
            last = local_sync.parse_key_values(
                self.lua(TRAINING_ARENA_STATUS, timeout=10.0)
            )
            if int(last.get("live_enemy_count", "0")) > 0:
                return last
            if int(last.get("failed_spawn_count", "0")) > 0:
                raise BridgeError(
                    f"direct training enemy spawn failed: {last}"
                )
            time.sleep(0.1)
        raise BridgeError(
            f"direct training enemy did not materialize: {last}"
        )

    def status(self) -> dict[str, str]:
        return local_sync.parse_key_values(
            self.lua(STATUS, timeout=10.0)
        )

    def enable_training(
        self,
        *,
        seed: int,
        capacity: int,
    ) -> dict[str, str]:
        values = local_sync.parse_key_values(
            self.lua(
                f"""
local api = assert(rawget(_G, 'bot_policy_training'))
local status = api.enable({{
  seed={int(seed)},
  capacity={int(capacity)}
}})
print('enabled=' .. tostring(status.enabled))
print('episode_id=' .. tostring(status.episode_id))
print('capacity=' .. tostring(status.capacity))
""",
                timeout=10.0,
            )
        )
        if values.get("enabled") != "true":
            raise BridgeError(f"could not enable policy training: {values}")
        return values

    def disable_training(self) -> dict[str, str]:
        values = local_sync.parse_key_values(
            self.lua(
                """
local status = assert(
  rawget(_G, 'bot_policy_training')).disable()
print('enabled=' .. tostring(status.enabled))
print('buffered=' .. tostring(status.buffered))
""",
                timeout=10.0,
            )
        )
        if values.get("enabled") != "false":
            raise BridgeError(f"could not disable policy training: {values}")
        return values

    def clear_training(self) -> dict[str, str]:
        return local_sync.parse_key_values(
            self.lua(
                """
local status = assert(
  rawget(_G, 'bot_policy_training')).clear()
print('buffered=' .. tostring(status.buffered))
print('dropped=' .. tostring(status.dropped))
print('recorded=' .. tostring(status.recorded))
""",
                timeout=10.0,
            )
        )

    def load_policy(self, policy: BotPolicy) -> int:
        source = render_lua_weights(policy)
        code = (
            "local candidate = (function()\n"
            + source
            + "end)()\n"
            + """
local result = assert(
  rawget(_G, 'bot_policy_training')).load_parameters(candidate)
print('generation=' .. tostring(result.generation))
"""
        )
        values = local_sync.parse_key_values(
            self.lua(code, timeout=30.0)
        )
        try:
            generation = int(values.get("generation", "0"))
        except ValueError as error:
            raise BridgeError(
                f"policy load returned invalid generation: {values}"
            ) from error
        if generation <= 0:
            raise BridgeError(f"policy load failed: {values}")
        return generation

    def wait_for_rollouts(
        self,
        count: int,
        *,
        timeout: float,
    ) -> dict[str, str]:
        deadline = time.monotonic() + timeout
        last: dict[str, str] = {}
        while time.monotonic() < deadline:
            last = self.status()
            if int(last.get("buffered", "0")) >= count:
                return last
            time.sleep(0.2)
        raise BridgeError(
            f"timed out waiting for {count} rollouts: {last}"
        )

    def _drain_rollout_chunk(self, count: int) -> list[RolloutRecord]:
        if count <= 0 or count > MAX_ROLLOUTS_PER_RESPONSE:
            raise ValueError(
                "rollout chunk count must be between 1 and "
                f"{MAX_ROLLOUTS_PER_RESPONSE}"
            )
        code = f"""
local api = assert(rawget(_G, 'bot_policy_training'))
local drained = api.drain({int(count)})
for _, record in ipairs(drained.records or {{}}) do
  local observation = {{}}
  for index, value in ipairs(record.observation or {{}}) do
    observation[index] = string.format('%.17g', value)
  end
  local movement_mask = {{}}
  for index, value in ipairs(record.movement_mask or {{}}) do
    movement_mask[index] = value and '1' or '0'
  end
  local cast_mask = {{}}
  for index, value in ipairs(record.cast_mask or {{}}) do
    cast_mask[index] = value and '1' or '0'
  end
  print(table.concat({{
    'R',
    tostring(record.trajectory_version),
    tostring(record.episode_id),
    string.format('%.0f', record.participant_id),
    tostring(record.simulation_tick),
    tostring(record.movement_action),
    tostring(record.cast_action),
    string.format('%.17g', record.old_log_probability),
    string.format('%.17g', record.old_value),
    string.format('%.17g', record.reward),
    record.done and '1' or '0',
    table.concat(observation, ','),
    table.concat(movement_mask),
    table.concat(cast_mask)
  }}, '\\t'))
end
print('buffered=' .. tostring(
  drained.status and drained.status.buffered or 0))
"""
        output = self.lua(code, timeout=30.0)
        return parse_rollout_output(output, expected_count=count)

    def drain_rollouts(self, count: int) -> list[RolloutRecord]:
        if count <= 0:
            raise ValueError("rollout count must be positive")
        records: list[RolloutRecord] = []
        while len(records) < count:
            chunk_count = min(
                count - len(records),
                MAX_ROLLOUTS_PER_RESPONSE,
            )
            records.extend(self._drain_rollout_chunk(chunk_count))
        return records
