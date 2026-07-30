#!/usr/bin/env python3
"""Verify native wave respawn for a host-owned synthetic participant."""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from PIL import Image

import cast_state_probe as csp
from verify_remote_latency_wave5 import (
    atomic_write_json,
    parse_key_values,
    validate_backbuffer,
    windows_path,
)
from run_bot_match import OPENABLE_PROBE


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = Path("/mnt/d/codex-evidence/botcombat-20260729")
RUNTIME_ROOT = EVIDENCE_ROOT / "runtime"
GAME_DIRECTORY = Path(
    "/mnt/c/Users/User/Documents/GitHub/SB Modding/"
    "Solomon Dark/SolomonDarkAbandonware"
)
LAUNCHER = ROOT / "dist/launcher/SolomonDarkModLauncher.exe"
PAIR_LAUNCHER = ROOT / "scripts/Launch-LocalMultiplayerPair.ps1"
STOP_SCRIPT = ROOT / "scripts/Stop-RemoteLatencyPeer.ps1"
LUA_EXEC = ROOT / "scripts/Invoke-LuaExec.ps1"
BOT_MOD_ID = "bot.brain"
HOST_PORT = 50611
CLIENT_PORT = 50612
HOST_ID = "0x200000000000BC01"
CLIENT_ID = "0x200000000000BC02"
HOST_NAME = "Host"
CLIENT_NAME = "client B"
TARGET_HEADER = "-- sdmod-exec-target: bot.brain\n"
VITAL_TOLERANCE = 0.1
POSITION_TOLERANCE = 35.0
ROUTE_ARRIVAL_RADIUS = 34.0
RETAIL_RUN_SEED = 0x2E9D3B65
NATIVE_LETHAL_PROBE_LIMIT = 10
NATIVE_LETHAL_RETRY_INTERVAL = 0.5
LETHAL_WINDOW_MAX_OUTSTANDING = 3


class RespawnVerificationFailure(RuntimeError):
    """Raised when the synthetic respawn contract does not converge."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def source_sha() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def integer(
    values: dict[str, str],
    key: str,
    default: int = 0,
) -> int:
    try:
        return int(values.get(key, str(default)), 0)
    except (TypeError, ValueError):
        try:
            return int(float(values.get(key, str(default))))
        except (TypeError, ValueError):
            return default


def number(
    values: dict[str, str],
    key: str,
    default: float = math.nan,
) -> float:
    try:
        value = float(values.get(key, str(default)))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def boolean(values: dict[str, str], key: str) -> bool:
    return values.get(key, "").casefold() == "true"


def wait_for(
    operation: Callable[[], Any],
    predicate: Callable[[Any], bool],
    *,
    label: str,
    timeout: float,
    interval: float = 0.25,
) -> tuple[Any, str]:
    deadline = time.monotonic() + timeout
    last: Any = None
    last_error = ""
    while time.monotonic() < deadline:
        try:
            last = operation()
            last_error = ""
            if predicate(last):
                return last, utc_now()
        except (
            OSError,
            ValueError,
            json.JSONDecodeError,
            subprocess.SubprocessError,
            RespawnVerificationFailure,
        ) as error:
            last_error = str(error)
        time.sleep(interval)
    raise RespawnVerificationFailure(
        f"Timed out waiting for {label}; last={last!r}; "
        f"last_error={last_error!r}"
    )


def lua(pipe_name: str, code: str, timeout: float = 15.0) -> str:
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            windows_path(LUA_EXEC),
            "-PipeName",
            pipe_name,
            "-ResponseTimeoutMilliseconds",
            str(int(timeout * 1000)),
            "-Code",
            TARGET_HEADER + code,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout + 8,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RespawnVerificationFailure(
            f"Lua exec failed for {pipe_name}: {detail}"
        )
    return completed.stdout


def values(
    pipe_name: str,
    code: str,
    timeout: float = 15.0,
) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, code, timeout))


def drive_peer_to_hub(
    pipe_name: str,
    process_id: int,
    *,
    element: str,
) -> dict[str, Any]:
    prior_pipe = os.environ.get("SDMOD_LUA_EXEC_PIPE_NAME")
    os.environ["SDMOD_LUA_EXEC_PIPE_NAME"] = pipe_name
    try:
        picker_deadline = time.monotonic() + 15
        while time.monotonic() < picker_deadline:
            snapshot = csp.query_ui_snapshot()
            if csp.snapshot_contains_action(
                snapshot,
                "control_scheme_picker.select_wasd",
                "control_scheme_picker",
            ):
                csp.activate_ui_action(
                    "control_scheme_picker.select_wasd",
                    "control_scheme_picker",
                )
                break
            if (
                snapshot.get("available") == "true"
                and snapshot.get("surface_id")
                != "control_scheme_picker"
            ):
                break
            time.sleep(0.1)
        return csp.drive_hub_flow(
            process_id,
            element=element,
            discipline="mind",
            prefer_resume=False,
        )
    except Exception as error:
        raise RespawnVerificationFailure(
            f"Retail semantic menu-to-hub flow failed for "
            f"{pipe_name}: {error}"
        ) from error
    finally:
        if prior_pipe is None:
            os.environ.pop("SDMOD_LUA_EXEC_PIPE_NAME", None)
        else:
            os.environ["SDMOD_LUA_EXEC_PIPE_NAME"] = prior_pipe


def parse_last_json(output: str) -> dict[str, Any]:
    for line in reversed(output.replace("\r", "").splitlines()):
        candidate = line.strip()
        if not candidate.startswith("{"):
            continue
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise RespawnVerificationFailure(
        f"Pair launcher returned no JSON contract: {output[-4000:]}"
    )


def expected_stage_paths(instance_prefix: str) -> dict[str, str]:
    return {
        role: windows_path(
            RUNTIME_ROOT
            / "instances"
            / f"{instance_prefix}-{role}".casefold()
            / "stage/SolomonDark.exe"
        )
        for role in ("host", "client")
    }


def assert_owned_stages_idle(instance_prefix: str) -> None:
    expected = {
        path.casefold()
        for path in expected_stage_paths(instance_prefix).values()
    }
    script = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $null -ne $_.ExecutablePath } | "
        "Select-Object ProcessId,ExecutablePath | "
        "ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise RespawnVerificationFailure(
            "Could not inspect exact staged process ownership: "
            f"{completed.stderr.strip()}"
        )
    raw = completed.stdout.replace("\r", "").strip()
    rows = json.loads(raw) if raw else []
    if isinstance(rows, dict):
        rows = [rows]
    conflicts = [
        row
        for row in rows
        if str(row.get("ExecutablePath", "")).casefold() in expected
    ]
    if conflicts:
        raise RespawnVerificationFailure(
            "The respawn verifier's exact stages are already running; "
            f"nothing was touched: {conflicts}"
        )


def launch_pair(
    instance_prefix: str,
    ledger_path: Path,
    launch_log: Path,
) -> tuple[dict[str, Any], subprocess.Popen[str]]:
    command = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        windows_path(PAIR_LAUNCHER),
        "-HostPreset",
        "idle",
        "-ClientPreset",
        "idle",
        "-HostPort",
        str(HOST_PORT),
        "-ClientPort",
        str(CLIENT_PORT),
        "-MaxParticipants",
        "4",
        "-HostParticipantId",
        HOST_ID,
        "-ClientParticipantId",
        CLIENT_ID,
        "-HostName",
        HOST_NAME,
        "-ClientName",
        CLIENT_NAME,
        "-InstancePrefix",
        instance_prefix,
        "-GameDirectory",
        windows_path(GAME_DIRECTORY),
        "-RuntimeRoot",
        windows_path(RUNTIME_ROOT),
        "-LauncherPath",
        windows_path(LAUNCHER),
        "-TemporaryHostProfile",
        "-NoTileWindows",
        "-ExactModIds",
        BOT_MOD_ID,
        "-ProcessIdOutputPath",
        windows_path(ledger_path),
    ]
    environment = os.environ.copy()
    environment["SDMOD_DISABLE_AUDIO"] = "1"
    environment["SDMOD_ENABLE_AUDIO"] = "0"
    output = launch_log.open("w", encoding="utf-8", newline="\n")
    try:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=environment,
            stdout=output,
            stderr=subprocess.STDOUT,
            text=True,
        )
    finally:
        output.close()

    expected = expected_stage_paths(instance_prefix)
    deadline = time.monotonic() + 240
    pair: dict[str, Any] = {}
    while time.monotonic() < deadline:
        if ledger_path.is_file():
            try:
                pair = json.loads(
                    ledger_path.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                pair = {}
            if (
                int(pair.get("hostProcessId") or 0) > 0
                and int(pair.get("clientProcessId") or 0) > 0
                and pair.get("hostExecutablePath")
                and pair.get("clientExecutablePath")
            ):
                break
        if process.poll() is not None:
            detail = (
                launch_log.read_text(encoding="utf-8", errors="replace")
                if launch_log.is_file()
                else ""
            )
            raise RespawnVerificationFailure(
                "Pair launcher exited before publishing both owned PIDs: "
                f"exit={process.returncode} output={detail[-4000:]}"
            )
        time.sleep(0.1)
    else:
        close_pair_wrapper(process)
        raise RespawnVerificationFailure(
            "Pair launcher did not publish both owned staged PIDs."
        )

    result = {
        **pair,
        "hostPort": HOST_PORT,
        "clientPort": CLIENT_PORT,
        "audioDisabled": True,
        "quickStartEnabled": False,
        "noLuaAutomation": False,
        "hostLuaPipe": (
            "SolomonDarkModLoader_LuaExec_"
            f"{instance_prefix}-host"
        ),
        "clientLuaPipe": (
            "SolomonDarkModLoader_LuaExec_"
            f"{instance_prefix}-client"
        ),
    }
    if (
        result.get("audioDisabled") is not True
        or result.get("quickStartEnabled") is not False
        or result.get("noLuaAutomation") is not False
        or int(result.get("hostPort", 0)) != HOST_PORT
        or int(result.get("clientPort", 0)) != CLIENT_PORT
        or str(result.get("hostExecutablePath", "")).casefold()
        != expected["host"].casefold()
        or str(result.get("clientExecutablePath", "")).casefold()
        != expected["client"].casefold()
    ):
        close_pair_wrapper(process)
        raise RespawnVerificationFailure(
            f"Pair launcher returned an unsafe ownership contract: {result}"
        )
    return result, process


def close_pair_wrapper(
    process: subprocess.Popen[str] | None,
) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def cleanup_owned_pair(
    pair_ledger: Path,
    cleanup_directory: Path,
) -> list[dict[str, Any]]:
    if not pair_ledger.is_file():
        return []
    pair = json.loads(pair_ledger.read_text(encoding="utf-8"))
    results = []
    for role in ("client", "host"):
        process_id = pair.get(f"{role}ProcessId")
        executable = pair.get(f"{role}ExecutablePath")
        if process_id is None or not executable:
            continue
        ledger = cleanup_directory / f"{role}-stop-ledger.json"
        atomic_write_json(
            ledger,
            {
                "processId": int(process_id),
                "executablePath": str(executable),
            },
        )
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                windows_path(STOP_SCRIPT),
                "-ProcessLedgerPath",
                windows_path(ledger),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if completed.returncode != 0:
            raise RespawnVerificationFailure(
                f"Exact {role} cleanup failed: "
                f"{(completed.stderr or completed.stdout).strip()}"
            )
        results.append(parse_last_json(completed.stdout))
    return results


SCENE_PROBE = r"""
local scene = sd.world.get_scene() or {}
print("scene=" .. tostring(scene.name or scene.kind or ""))
print("ready=true")
"""


BOT_ROSTER_PROBE = r"""
local rows = {}
for _, bot in ipairs(sd.bots.get_state() or {}) do
  if bot.in_run == true and bot.entity_materialized == true then
    rows[#rows + 1] = bot
  end
end
table.sort(rows, function(left, right)
  return (tonumber(left.id) or 0) < (tonumber(right.id) or 0)
end)
print("count=" .. tostring(#rows))
for index, bot in ipairs(rows) do
  print("bot." .. index .. ".id=" .. tostring(bot.id or 0))
  print("bot." .. index .. ".name=" .. tostring(bot.name or ""))
end
"""


def configure_host_bot_roster(
    instance_prefix: str,
    host_pipe: str,
) -> dict[str, Any]:
    settings_path = (
        RUNTIME_ROOT
        / "instances"
        / f"{instance_prefix}-host".casefold()
        / "stage/.sdmod/mod-settings/bot.brain.json"
    )
    atomic_write_json(
        settings_path,
        {
            "schemaVersion": 1,
            "values": {
                "focus_bot_key": "NONE",
                "kite_radius": 340,
                "offense_enabled": True,
                "think_profile": "standard",
                "roster": [
                    {
                        "name": "Ember",
                        "element": "air",
                        "discipline": "arcane",
                        "behavior": "skirmisher",
                    },
                    {
                        "name": "Brook",
                        "element": "fire",
                        "discipline": "mind",
                        "behavior": "striker",
                    },
                ],
            },
        },
    )
    reloaded = values(
        host_pipe,
        f"""
local result = sd.__settings_reload({json.dumps(BOT_MOD_ID)})
print("ok=" .. tostring(result.ok))
print("changed=" .. table.concat(result.changed or {{}}, ","))
print("error=" .. tostring(result.error or ""))
""",
    )
    if (
        reloaded.get("ok") != "true"
        or "roster" not in reloaded.get("changed", "").split(",")
        or reloaded.get("error", "")
    ):
        raise RespawnVerificationFailure(
            f"Host bot roster reload failed: {reloaded}"
        )
    settled, settled_at = wait_for(
        lambda: values(
            host_pipe,
            r"""
local roster = sd.settings.get("roster") or {}
print("count=" .. tostring(#roster))
for index, row in ipairs(roster) do
  print("name." .. tostring(index) .. "=" ..
    tostring(row.name or ""))
end
""",
        ),
        lambda row: (
            integer(row, "count") == 2
            and row.get("name.1") == "Ember"
            and row.get("name.2") == "Brook"
        ),
        label="two-seat host bot settings",
        timeout=15,
        interval=0.1,
    )
    return {
        "path": str(settings_path),
        "reload": reloaded,
        "settled": settled,
        "settledAt": settled_at,
    }


def participant_probe(participant_id: int) -> str:
    return f"""
local id = {participant_id}
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local bot = sd.bots.get_participant_state(id)
local actor = bot and tonumber(bot.actor_address) or 0
local progression = bot and
  tonumber(bot.progression_runtime_state_address) or 0
local runtime = sd.runtime.get_multiplayer_state() or {{}}
local participant = nil
for _, candidate in ipairs(runtime.participants or {{}}) do
  if tonumber(candidate.participant_id) == id then
    participant = candidate
    break
  end
end
local spectator = runtime.death_spectator or {{}}
local world = sd.world.get_state() or {{}}
local local_player = sd.player.get_state() or {{}}
local respawn_observer =
  rawget(_G, "__botcombat_respawn_observer") or {{}}
local first_respawn =
  type(respawn_observer.first_respawn) == "table" and
    respawn_observer.first_respawn or {{}}
local nameplate = actor ~= 0 and sd.bots.get_nameplate(actor) or nil
local grid_member = actor ~= 0 and
  (sd.debug.read_u8(actor +
    sd.debug.layout_offset("actor_grid_member_flag")) or 0) or 0
local grid_cell = actor ~= 0 and
  (sd.debug.read_ptr(actor +
    sd.debug.layout_offset("actor_grid_cell_ptr")) or 0) or 0
local actor_x = actor ~= 0 and
  (sd.debug.read_float(actor +
    sd.debug.layout_offset("actor_position_x")) or 0) or 0
local actor_y = actor ~= 0 and
  (sd.debug.read_float(actor +
    sd.debug.layout_offset("actor_position_y")) or 0) or 0
local collision_radius = actor ~= 0 and
  (sd.debug.read_float(actor +
    sd.debug.layout_offset("actor_collision_radius")) or 0) or 0
local move_step_scale = actor ~= 0 and
  (sd.debug.read_float(actor +
    sd.debug.layout_offset("actor_move_step_scale")) or 0) or 0
local spawn_nav_ok, spawn_nav_traversable = pcall(
  sd.nav.test_segment,
  tonumber(world.player_spawn_x) or 0,
  tonumber(world.player_spawn_y) or 0,
  tonumber(world.player_spawn_x) or 0,
  tonumber(world.player_spawn_y) or 0)
local actor_nav_ok, actor_nav_traversable = pcall(
  sd.nav.test_segment,
  actor_x, actor_y, actor_x, actor_y)
local terminal = actor ~= 0 and
  (sd.debug.read_u8(actor +
    sd.debug.layout_offset("actor_terminal_dispatch_pending")) or 0) or 0
local drive = actor ~= 0 and
  (sd.debug.read_u8(actor +
    sd.debug.layout_offset("actor_animation_drive_state_byte")) or 0) or 0
emit("found", bot ~= nil)
emit("id", id)
emit("name", bot and bot.name or "")
emit("materialized", bot and bot.entity_materialized == true)
emit("in_run", bot and bot.in_run == true)
emit("run_nonce", bot and bot.run_nonce or 0)
emit("gameplay_slot", bot and bot.gameplay_slot or -1)
emit("actor", actor)
emit("progression", progression)
emit("hp", bot and bot.hp or 0)
emit("max_hp", bot and bot.max_hp or 0)
emit("mp", bot and bot.mp or 0)
emit("max_mp", bot and bot.max_mp or 0)
emit("x", bot and bot.x or 0)
emit("y", bot and bot.y or 0)
emit("actor_x", actor_x)
emit("actor_y", actor_y)
emit("collision_radius", collision_radius)
emit("move_step_scale", move_step_scale)
emit("local_player_x", local_player.x or 0)
emit("local_player_y", local_player.y or 0)
emit("spawn_nav_traversable",
  spawn_nav_ok and spawn_nav_traversable == true)
emit("actor_nav_traversable",
  actor_nav_ok and actor_nav_traversable == true)
emit("grid_member", grid_member)
emit("grid_cell", grid_cell)
emit("terminal_pending", terminal)
emit("anim_drive", drive)
emit("presentation_flags",
  participant and participant.presentation_flags or 0)
emit("death_tick",
  participant and participant.death_presentation_tick or 0)
emit("respawn_epoch",
  spectator.last_applied_respawn_epoch or 0)
emit("respawn_wave",
  spectator.last_applied_respawn_wave or 0)
emit("first_respawn_epoch", first_respawn.epoch or 0)
emit("first_respawn_actor", first_respawn.actor or 0)
emit("first_respawn_progression",
  first_respawn.progression or 0)
emit("first_respawn_hp", first_respawn.hp or 0)
emit("first_respawn_max_hp", first_respawn.max_hp or 0)
emit("first_respawn_mp", first_respawn.mp or 0)
emit("first_respawn_max_mp", first_respawn.max_mp or 0)
emit("first_respawn_x", first_respawn.x or 0)
emit("first_respawn_y", first_respawn.y or 0)
emit("spawn_valid", world.player_spawn_valid == true)
emit("spawn_x", world.player_spawn_x or 0)
emit("spawn_y", world.player_spawn_y or 0)
emit("nameplate_id", nameplate and nameplate.id or 0)
emit("nameplate_name", nameplate and nameplate.name or "")
emit("nameplate_health_ratio",
  nameplate and nameplate.health_ratio or -1)
emit("bots_tick_disabled", lua_bots_disable_tick == true)
"""


WAVE_PROBE = r"""
local state = sd.waves.get_state() or {}
print("wave=" .. tostring(state.wave or 0))
print("phase=" .. tostring(state.phase or ""))
print("alive=" .. tostring(state.alive or 0))
print("killed=" .. tostring(state.killed or 0))
print("remaining=" .. tostring(state.remaining_to_spawn or 0))
"""


ROUTE_CONTROLLER_GLOBAL = "__botcombat_respawn_route"
ROUTE_CONTROLLER_SOURCE = f"""
local prior = rawget(_G, "{ROUTE_CONTROLLER_GLOBAL}")
if type(prior) == "table" then prior.armed = false end
local controller = {{
  armed = true,
  destination = nil,
  arrival = nil,
  destination_distance = -1,
  movement_frames = 0,
  arrival_radius = {ROUTE_ARRIVAL_RADIUS:.1f},
  last_cast_ms = 0,
  cast_attempts = 0,
  cast_accepted = 0,
  combat_enabled = true,
  combat_movement_enabled = true,
}}
rawset(_G, "{ROUTE_CONTROLLER_GLOBAL}", controller)

local function normalize(x, y)
  local length = math.sqrt(x * x + y * y)
  if length <= 0.0001 then return 0.0, 0.0, 0.0 end
  return x / length, y / length, length
end

local function drive_route(event)
  local active = rawget(_G, "{ROUTE_CONTROLLER_GLOBAL}")
  if active ~= controller or active.armed ~= true then
    return
  end
  local scene = sd.world.get_scene() or {{}}
  if tostring(scene.name or scene.kind or "") ~= "testrun" then
    return
  end
  local player = sd.player.get_state() or {{}}
  local x, y = tonumber(player.x), tonumber(player.y)
  if x == nil or y == nil or
      (tonumber(player.actor_address) or 0) == 0 then
    return
  end
  pcall(sd.input.set_native_control_allowance_frames, 120)
  if type(active.destination) == "table" then
    local dx = (tonumber(active.destination.x) or x) - x
    local dy = (tonumber(active.destination.y) or y) - y
    local nx, ny, remaining = normalize(dx, dy)
    active.destination_distance = remaining
    if remaining <= active.arrival_radius then
      active.arrival = {{ x = x, y = y }}
      active.destination = nil
      pcall(sd.input.hold_movement_frames, 0.0, 0.0, 1)
      return
    end
    local ok, accepted = pcall(
      sd.input.hold_movement_frames, nx, ny, 1)
    if ok and accepted == true then
      active.movement_frames = active.movement_frames + 1
    end
    return
  end

  local wave = sd.waves.get_state() or {{}}
  if (tonumber(wave.wave) or 0) <= 0 or
      (tonumber(player.hp) or 0) <= 0 then
    return
  end
  if active.combat_enabled == false then
    pcall(sd.input.hold_movement_frames, 0.0, 0.0, 1)
    return
  end
  local enemy, enemy_distance = nil, math.huge
  for _, actor in ipairs(sd.world.list_actors() or {{}}) do
    local hp = tonumber(actor.hp) or 0
    if actor.tracked_enemy == true and
        actor.dead ~= true and hp > 0 then
      local ex, ey = tonumber(actor.x) or x, tonumber(actor.y) or y
      local candidate = math.sqrt((ex - x) ^ 2 + (ey - y) ^ 2)
      if candidate < enemy_distance then
        enemy, enemy_distance = actor, candidate
      end
    end
  end
  if enemy == nil then return end
  local ex, ey = tonumber(enemy.x) or x, tonumber(enemy.y) or y
  local toward_x, toward_y = normalize(ex - x, ey - y)
  local move_x, move_y = 0.0, 0.0
  local max_hp = tonumber(player.max_hp) or 0
  local low_health =
    max_hp > 0 and (tonumber(player.hp) or 0) / max_hp < 0.5
  if low_health then
    move_x, move_y = -toward_x, -toward_y
  elseif enemy_distance > 220.0 then
    move_x, move_y = toward_x, toward_y
  elseif enemy_distance < 95.0 then
    move_x, move_y = -toward_x, -toward_y
  else
    move_x, move_y = normalize(
      -toward_y + toward_x * 0.15,
      toward_x + toward_y * 0.15)
  end
  if active.combat_movement_enabled ~= false then
    local moved_ok, moved = pcall(
      sd.input.hold_movement_frames, move_x, move_y, 1)
    if moved_ok and moved == true then
      active.movement_frames = active.movement_frames + 1
    end
  end

  local now_ms = tonumber(
    event and event.monotonic_milliseconds) or 0
  if now_ms - active.last_cast_ms < 350 then return end
  active.last_cast_ms = now_ms
  active.cast_attempts = active.cast_attempts + 1
  local pin_ok, pinned = pcall(
    sd.input.pin_manual_primary_target,
    tonumber(enemy.actor_address) or 0)
  local cast_ok, cast = pcall(
    sd.input.hold_mouse_left_frames, 3)
  if pin_ok and pinned == true and
      cast_ok and cast == true then
    active.cast_accepted = active.cast_accepted + 1
  end
end

sd.events.on("runtime.tick", drive_route)
lua_bots_disable_tick = true
print("armed=" .. tostring(controller.armed))
print("bots_quiesced=" .. tostring(lua_bots_disable_tick))
"""


ROUTE_STATE_PROBE = f"""
local player = sd.player.get_state() or {{}}
local controller =
  rawget(_G, "{ROUTE_CONTROLLER_GLOBAL}") or {{}}
local ok, solomon = pcall(sd.hub.get_solomon_dig_state)
solomon = ok and solomon or {{}}
print("player_x=" .. tostring(player.x or 0))
print("player_y=" .. tostring(player.y or 0))
print("destination_active=" ..
  tostring(type(controller.destination) == "table"))
print("destination_distance=" ..
  tostring(controller.destination_distance or -1))
print("arrival_valid=" ..
  tostring(type(controller.arrival) == "table"))
print("arrival_x=" ..
  tostring(type(controller.arrival) == "table" and
    controller.arrival.x or 0))
print("arrival_y=" ..
  tostring(type(controller.arrival) == "table" and
    controller.arrival.y or 0))
print("movement_frames=" ..
  tostring(controller.movement_frames or 0))
print("cast_attempts=" ..
  tostring(controller.cast_attempts or 0))
print("cast_accepted=" ..
  tostring(controller.cast_accepted or 0))
print("solomon_actor=" ..
  tostring(solomon.actor_address or 0))
print("solomon_x=" .. tostring(solomon.x or 0))
print("solomon_y=" .. tostring(solomon.y or 0))
print("solomon_state=" ..
  tostring(solomon.interaction_state or -1))
print("solomon_acquired=" ..
  tostring(solomon.participant_acquired == true))
print("solomon_target_slot=" ..
  tostring(solomon.target_gameplay_slot or -1))
"""


def normalize(x: float, y: float) -> tuple[float, float]:
    length = math.hypot(x, y)
    if length <= 0.0001:
        raise RespawnVerificationFailure(
            "Cannot normalize a zero-length retail route."
        )
    return x / length, y / length


def route_state(host_pipe: str) -> dict[str, str]:
    return values(host_pipe, ROUTE_STATE_PROBE)


def list_openables(host_pipe: str) -> list[dict[str, Any]]:
    observed = values(host_pipe, OPENABLE_PROBE)
    obstacles = []
    for index in range(1, integer(observed, "count") + 1):
        prefix = f"obstacle.{index}."
        start = (
            number(observed, prefix + "start_x"),
            number(observed, prefix + "start_y"),
        )
        end = (
            number(observed, prefix + "end_x"),
            number(observed, prefix + "end_y"),
        )
        obstacles.append(
            {
                "object": integer(observed, prefix + "object"),
                "record": integer(observed, prefix + "record"),
                "start": start,
                "end": end,
                "midpoint": (
                    (start[0] + end[0]) * 0.5,
                    (start[1] + end[1]) * 0.5,
                ),
            }
        )
    return obstacles


def select_retail_gate(
    start: tuple[float, float],
    solomon: tuple[float, float],
    obstacles: list[dict[str, Any]],
) -> dict[str, Any]:
    route = normalize(solomon[0] - start[0], solomon[1] - start[1])
    route_length = math.dist(start, solomon)
    candidates = []
    for obstacle in obstacles:
        relative = (
            obstacle["midpoint"][0] - start[0],
            obstacle["midpoint"][1] - start[1],
        )
        projection = relative[0] * route[0] + relative[1] * route[1]
        perpendicular = abs(
            relative[0] * -route[1] + relative[1] * route[0]
        )
        if 40.0 < projection < route_length - 80.0:
            candidates.append((perpendicular, projection, obstacle))
    if not candidates:
        raise RespawnVerificationFailure(
            "No native openable lies between slot 0 and Solomon: "
            f"{obstacles}"
        )
    candidates.sort(key=lambda row: (row[0], row[1]))
    anchor = candidates[0][2]["midpoint"]
    cluster = [
        row[2]
        for row in candidates
        if math.dist(row[2]["midpoint"], anchor) <= 140.0
    ]
    endpoints = [
        point
        for obstacle in cluster
        for point in (obstacle["start"], obstacle["end"])
    ]
    midpoint = (
        sum(point[0] for point in endpoints) / len(endpoints),
        sum(point[1] for point in endpoints) / len(endpoints),
    )
    reference = max(
        (
            (
                obstacle["end"][0] - obstacle["start"][0],
                obstacle["end"][1] - obstacle["start"][1],
            )
            for obstacle in cluster
        ),
        key=lambda vector: math.hypot(*vector),
    )
    tangent = normalize(*reference)
    transit = (-tangent[1], tangent[0])
    if (
        (solomon[0] - midpoint[0]) * transit[0]
        + (solomon[1] - midpoint[1]) * transit[1]
        < 0.0
    ):
        transit = (-transit[0], -transit[1])
    return {
        "midpoint": midpoint,
        "routeUnit": transit,
        "segments": cluster,
    }


def command_route_destination(
    host_pipe: str,
    destination: tuple[float, float],
) -> dict[str, str]:
    accepted = values(
        host_pipe,
        f"""
local controller = assert(
  rawget(_G, "{ROUTE_CONTROLLER_GLOBAL}"),
  "route controller unavailable")
controller.destination = {{
  x = {destination[0]:.9f},
  y = {destination[1]:.9f},
}}
controller.arrival = nil
print("accepted=true")
""",
    )
    if not boolean(accepted, "accepted"):
        raise RespawnVerificationFailure(
            f"Retail route destination was rejected: {accepted}"
        )
    return accepted


def wait_route_destination(
    host_pipe: str,
    destination: tuple[float, float],
    *,
    label: str,
    allow_solomon_acquisition: bool = False,
) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []

    def sample() -> dict[str, Any]:
        observed = route_state(host_pipe)
        row = {
            "sampledAt": utc_now(),
            "position": [
                number(observed, "player_x"),
                number(observed, "player_y"),
            ],
            "destination": list(destination),
            "distance": math.hypot(
                number(observed, "player_x") - destination[0],
                number(observed, "player_y") - destination[1],
            ),
            "movementFrames": integer(observed, "movement_frames"),
            "destinationActive": boolean(
                observed,
                "destination_active",
            ),
            "arrivalValid": boolean(
                observed,
                "arrival_valid",
            ),
            "arrivalDistance": math.hypot(
                number(observed, "arrival_x") - destination[0],
                number(observed, "arrival_y") - destination[1],
            ),
            "solomonAcquired": boolean(
                observed,
                "solomon_acquired",
            ),
            "solomonState": integer(observed, "solomon_state", -1),
            "solomonTargetSlot": integer(
                observed,
                "solomon_target_slot",
                -1,
            ),
        }
        samples.append(row)
        return row

    final, completed_at = wait_for(
        sample,
        lambda row: (
            (
                allow_solomon_acquisition
                and row["solomonAcquired"]
                and row["solomonState"] >= 1
            )
            or (
                row["arrivalValid"]
                and row["arrivalDistance"]
                <= ROUTE_ARRIVAL_RADIUS + 1.0
            )
        ),
        label=label,
        timeout=45,
        interval=0.1,
    )
    return {
        "completedAt": completed_at,
        "final": final,
        "samples": samples,
    }


def segment_is_clear(
    host_pipe: str,
    start: tuple[float, float],
    end: tuple[float, float],
) -> bool:
    observed = values(
        host_pipe,
        f"""
local ok, clear = pcall(
  sd.nav.test_segment,
  {start[0]:.9f}, {start[1]:.9f},
  {end[0]:.9f}, {end[1]:.9f})
print("ok=" .. tostring(ok))
print("clear=" .. tostring(clear))
""",
    )
    return boolean(observed, "ok") and boolean(observed, "clear")


def find_solomon_proximity_route(
    host_pipe: str,
    current: tuple[float, float],
    solomon: tuple[float, float],
) -> dict[str, Any]:
    def circle_points(
        radii: tuple[float, ...],
        count: int,
    ) -> list[tuple[float, float]]:
        return [
            (
                solomon[0] + radius * math.cos(index * math.tau / count),
                solomon[1] + radius * math.sin(index * math.tau / count),
            )
            for radius in radii
            for index in range(count)
        ]

    targets = circle_points((42.0, 65.0, 90.0), 16)
    intermediates = circle_points((180.0, 280.0, 380.0), 16)

    def lua_rows(points: list[tuple[float, float]]) -> str:
        return ",\n".join(
            f"{{ x = {point[0]:.9f}, y = {point[1]:.9f} }}"
            for point in points
        )

    observed = values(
        host_pipe,
        f"""
local current = {{ x = {current[0]:.9f}, y = {current[1]:.9f} }}
local targets = {{
{lua_rows(targets)}
}}
local intermediates = {{
{lua_rows(intermediates)}
}}
local function clear(from, target)
  local ok, traversable = pcall(
    sd.nav.test_segment,
    from.x, from.y, target.x, target.y)
  return ok and traversable == true
end
for _, target in ipairs(targets) do
  if clear(target, target) and clear(current, target) then
    print("kind=direct")
    print("target_x=" .. tostring(target.x))
    print("target_y=" .. tostring(target.y))
    return
  end
end
for _, intermediate in ipairs(intermediates) do
  if clear(intermediate, intermediate) and
      clear(current, intermediate) then
    for _, target in ipairs(targets) do
      if clear(target, target) and clear(intermediate, target) then
        print("kind=via")
        print("intermediate_x=" .. tostring(intermediate.x))
        print("intermediate_y=" .. tostring(intermediate.y))
        print("target_x=" .. tostring(target.x))
        print("target_y=" .. tostring(target.y))
        return
      end
    end
  end
end
print("kind=none")
""",
        timeout=30,
    )
    kind = observed.get("kind", "")
    if kind not in {"direct", "via"}:
        raise RespawnVerificationFailure(
            "No native-segment route reaches Solomon conversation "
            f"proximity: {observed}"
        )
    route = {
        "kind": kind,
        "target": (
            number(observed, "target_x"),
            number(observed, "target_y"),
        ),
    }
    if kind == "via":
        route["intermediate"] = (
            number(observed, "intermediate_x"),
            number(observed, "intermediate_y"),
        )
    return route


def route_slot_zero_to_retail_waves(host_pipe: str) -> dict[str, Any]:
    initial, materialized_at = wait_for(
        lambda: route_state(host_pipe),
        lambda row: (
            integer(row, "solomon_actor") > 0
            and math.isfinite(number(row, "player_x"))
            and math.isfinite(number(row, "player_y"))
        ),
        label="live Solomon actor before physical routing",
        timeout=45,
        interval=0.1,
    )
    armed = values(host_pipe, ROUTE_CONTROLLER_SOURCE)
    if (
        not boolean(armed, "armed")
        or not boolean(armed, "bots_quiesced")
    ):
        raise RespawnVerificationFailure(
            f"Could not arm the native slot-0 retail route: {armed}"
        )
    start = (
        number(initial, "player_x"),
        number(initial, "player_y"),
    )
    solomon = (
        number(initial, "solomon_x"),
        number(initial, "solomon_y"),
    )
    if integer(initial, "solomon_actor") <= 0:
        raise RespawnVerificationFailure(
            f"Solomon was unavailable for physical routing: {initial}"
        )
    gate = select_retail_gate(start, solomon, list_openables(host_pipe))
    transit = gate["routeUnit"]
    midpoint = gate["midpoint"]
    destinations = {
        "gateApproach": (
            midpoint[0] - transit[0] * 105.0,
            midpoint[1] - transit[1] * 105.0,
        ),
        "gateExit": (
            midpoint[0] + transit[0] * 175.0,
            midpoint[1] + transit[1] * 175.0,
        ),
    }
    route_legs = {}
    for label in ("gateApproach", "gateExit"):
        destination = destinations[label]
        command_route_destination(host_pipe, destination)
        route_legs[label] = wait_route_destination(
            host_pipe,
            destination,
            label=label,
        )

    current_state = route_state(host_pipe)
    current = (
        number(current_state, "player_x"),
        number(current_state, "player_y"),
    )
    dig_route = normalize(
        solomon[0] - midpoint[0],
        solomon[1] - midpoint[1],
    )
    gather = None
    for distance_from_solomon in range(650, 149, -50):
        candidate = (
            solomon[0] - dig_route[0] * distance_from_solomon,
            solomon[1] - dig_route[1] * distance_from_solomon,
        )
        if segment_is_clear(host_pipe, current, candidate):
            gather = candidate
            break
    if gather is None:
        raise RespawnVerificationFailure(
            "No natively traversable post-gate segment reaches the "
            "Solomon side of the retail hub."
        )
    command_route_destination(host_pipe, gather)
    route_legs["hubGather"] = wait_route_destination(
        host_pipe,
        gather,
        label="hub gather",
    )

    gather_state = route_state(host_pipe)
    gather_position = (
        number(gather_state, "player_x"),
        number(gather_state, "player_y"),
    )
    proximity_route = find_solomon_proximity_route(
        host_pipe,
        gather_position,
        solomon,
    )
    if "intermediate" in proximity_route:
        intermediate = proximity_route["intermediate"]
        command_route_destination(host_pipe, intermediate)
        route_legs["solomonApproach"] = wait_route_destination(
            host_pipe,
            intermediate,
            label="native Solomon approach",
        )
    trigger = proximity_route["target"]
    command_route_destination(host_pipe, trigger)
    route_legs["solomonProximity"] = wait_route_destination(
        host_pipe,
        trigger,
        label="native Solomon proximity",
        allow_solomon_acquisition=True,
    )

    triggered, triggered_at = wait_for(
        lambda: values(
            host_pipe,
            r"""
local ok, state = sd.hub.trigger_solomon_dig()
print("triggered=" .. tostring(ok))
print("state=" ..
  tostring(state and state.interaction_state or -1))
print("acquired=" ..
  tostring(state and state.participant_acquired or false))
print("target_slot=" ..
  tostring(state and state.target_gameplay_slot or -1))
""",
        ),
        lambda row: (
            boolean(row, "triggered")
            and boolean(row, "acquired")
            and integer(row, "state", -1) >= 1
            and 0 <= integer(row, "target_slot", -1) <= 3
        ),
        label="real Solomon proximity/conversation trigger",
        timeout=15,
        interval=0.1,
    )
    resumed = values(
        host_pipe,
        f"""
local controller = assert(
  rawget(_G, "{ROUTE_CONTROLLER_GLOBAL}"),
  "route controller unavailable")
controller.destination = nil
controller.destination_distance = 0
lua_bots_disable_tick = false
print("resumed=" .. tostring(lua_bots_disable_tick == false))
""",
    )
    if not boolean(resumed, "resumed"):
        raise RespawnVerificationFailure(
            f"Could not resume bot combat policy: {resumed}"
        )
    active, active_at = wait_for(
        lambda: values(host_pipe, WAVE_PROBE),
        lambda row: integer(row, "wave") > 0 and integer(row, "alive") > 0,
        label="live retail wave schedule",
        timeout=45,
        interval=0.1,
    )
    return {
        "initial": initial,
        "solomonMaterializedAt": materialized_at,
        "gate": gate,
        "destinations": destinations,
        "proximityRoute": proximity_route,
        "legs": route_legs,
        "solomonTrigger": triggered,
        "solomonTriggerAt": triggered_at,
        "activeWave": active,
        "activeWaveAt": active_at,
    }


def arm_client_b_combat(client_pipe: str) -> dict[str, str]:
    armed = values(client_pipe, ROUTE_CONTROLLER_SOURCE)
    if not boolean(armed, "armed"):
        raise RespawnVerificationFailure(
            f"Could not arm client B local combat controller: {armed}"
        )
    return armed


def set_combat_activity(
    pipe_name: str,
    *,
    enabled: bool,
    manage_bots: bool,
) -> dict[str, str]:
    lua_boolean = "true" if enabled else "false"
    bot_assignment = (
        f"lua_bots_disable_tick = {str(not enabled).lower()}"
        if manage_bots
        else ""
    )
    observed = values(
        pipe_name,
        f"""
local controller = assert(
  rawget(_G, "{ROUTE_CONTROLLER_GLOBAL}"),
  "combat controller unavailable")
controller.combat_enabled = {lua_boolean}
{bot_assignment}
print("combat_enabled=" .. tostring(
  controller.combat_enabled == true))
print("expected_enabled={lua_boolean}")
print("bots_expected=" .. tostring({str(manage_bots).lower()}))
print("bots_disabled=" .. tostring(lua_bots_disable_tick == true))
""",
    )
    if boolean(observed, "combat_enabled") != enabled:
        raise RespawnVerificationFailure(
            f"Could not set combat activity on {pipe_name}: {observed}"
        )
    if manage_bots and boolean(observed, "bots_disabled") == enabled:
        raise RespawnVerificationFailure(
            f"Could not set bot activity on {pipe_name}: {observed}"
        )
    return observed


def state_is_alive(state: dict[str, str]) -> bool:
    hp = number(state, "hp")
    maximum = number(state, "max_hp")
    return (
        boolean(state, "found")
        and boolean(state, "materialized")
        and boolean(state, "in_run")
        and integer(state, "actor") > 0
        and integer(state, "progression") > 0
        and integer(state, "gameplay_slot", -1) in (1, 2, 3)
        and math.isfinite(hp)
        and math.isfinite(maximum)
        and maximum > 0.0
        and hp > 0.0
        and integer(state, "grid_member") == 1
        and integer(state, "grid_cell") > 0
    )


def lethal_window_ready(
    wave: dict[str, str],
    target: dict[str, str],
    minimum_wave: int,
) -> bool:
    alive = integer(wave, "alive")
    remaining = integer(wave, "remaining")
    return (
        state_is_alive(target)
        and integer(wave, "wave") > minimum_wave
        and wave.get("phase") in {"spawning", "clearing"}
        and alive > 0
        and remaining >= 0
        and alive + remaining <= LETHAL_WINDOW_MAX_OUTSTANDING
    )


def state_is_dead(
    state: dict[str, str],
    *,
    actor: int,
    progression: int,
) -> bool:
    return (
        boolean(state, "found")
        and integer(state, "actor") == actor
        and integer(state, "progression") == progression
        and number(state, "hp", 1.0) <= 0.0
        and (
            integer(state, "presentation_flags") & (1 << 6)
            or integer(state, "death_tick") > 0
            or integer(state, "anim_drive") != 0
        )
    )


def validate_respawn_transition(
    host_dead: dict[str, str],
    client_dead: dict[str, str],
    host_alive: dict[str, str],
    client_alive: dict[str, str],
) -> dict[str, Any]:
    for role, dead, alive in (
        ("host", host_dead, host_alive),
        ("client B", client_dead, client_alive),
    ):
        if not state_is_alive(alive):
            raise RespawnVerificationFailure(
                f"{role} respawned participant is not natively alive: {alive}"
            )
        if (
            integer(dead, "actor") != integer(alive, "actor")
            or integer(dead, "progression")
            != integer(alive, "progression")
        ):
            raise RespawnVerificationFailure(
                f"{role} replaced the actor/progression across respawn: "
                f"dead={dead} alive={alive}"
            )
        hp = number(alive, "hp")
        maximum = number(alive, "max_hp")
        first_hp = number(alive, "first_respawn_hp")
        first_maximum = number(alive, "first_respawn_max_hp")
        first_mp = number(alive, "first_respawn_mp")
        first_maximum_mp = number(
            alive,
            "first_respawn_max_mp",
        )
        first_x = number(alive, "first_respawn_x")
        first_y = number(alive, "first_respawn_y")
        actor_x = number(alive, "actor_x")
        actor_y = number(alive, "actor_y")
        if (
            integer(alive, "first_respawn_epoch")
            != integer(alive, "respawn_epoch")
            or integer(alive, "first_respawn_actor")
            != integer(alive, "actor")
            or integer(alive, "first_respawn_progression")
            != integer(alive, "progression")
            or abs(first_hp - first_maximum) > VITAL_TOLERANCE
            or abs(first_mp - first_maximum_mp) > VITAL_TOLERANCE
            or not math.isfinite(first_x)
            or not math.isfinite(first_y)
            or not math.isfinite(actor_x)
            or not math.isfinite(actor_y)
        ):
            raise RespawnVerificationFailure(
                f"{role} did not first publish full native respawn "
                f"resources on the preserved actor: {alive}"
            )
        if (
            integer(alive, "nameplate_id")
            != integer(alive, "id")
            or not alive.get("nameplate_name")
            or abs(
                number(alive, "nameplate_health_ratio") - hp / maximum
            )
            > 0.02
        ):
            raise RespawnVerificationFailure(
                f"{role} nameplate HP is incoherent: {alive}"
            )
        if number(alive, "move_step_scale", 0.0) <= 0.0:
            raise RespawnVerificationFailure(
                f"{role} respawn destroyed the native move-step scale: "
                f"{alive}"
            )
        if not boolean(alive, "spawn_valid"):
            raise RespawnVerificationFailure(
                f"{role} has no Arena-authored respawn tuple: {alive}"
            )
        if not boolean(alive, "actor_nav_traversable"):
            raise RespawnVerificationFailure(
                f"{role} respawned outside traversable Arena space: {alive}"
            )

    epoch = integer(host_alive, "respawn_epoch")
    if (
        epoch <= integer(host_dead, "respawn_epoch")
        or epoch != integer(client_alive, "respawn_epoch")
        or integer(host_alive, "respawn_wave")
        != integer(client_alive, "respawn_wave")
        or integer(host_alive, "presentation_flags") & (1 << 6)
        or integer(client_alive, "presentation_flags") & (1 << 6)
    ):
        raise RespawnVerificationFailure(
            "host/client B death epochs did not retire coherently: "
            f"host_dead={host_dead} client_dead={client_dead} "
            f"host_alive={host_alive} client_alive={client_alive}"
        )
    host_first_spawn_delta = math.hypot(
        number(host_alive, "first_respawn_x")
        - number(host_alive, "spawn_x"),
        number(host_alive, "first_respawn_y")
        - number(host_alive, "spawn_y"),
    )
    if (
        host_first_spawn_delta > POSITION_TOLERANCE
        or not boolean(host_alive, "bots_tick_disabled")
    ):
        raise RespawnVerificationFailure(
            "host did not freeze the bot at its first Arena-authored "
            f"respawn placement: delta={host_first_spawn_delta} "
            f"host={host_alive}"
        )
    peer_placement_delta = math.hypot(
        number(host_alive, "actor_x")
        - number(client_alive, "actor_x"),
        number(host_alive, "actor_y")
        - number(client_alive, "actor_y"),
    )
    if peer_placement_delta > POSITION_TOLERANCE:
        raise RespawnVerificationFailure(
            "host/client B did not converge on respawn placement: "
            f"delta={peer_placement_delta} "
            f"host={host_alive} client={client_alive}"
        )
    return {
        "epoch": epoch,
        "wave": integer(host_alive, "respawn_wave"),
        "hostActorPreserved": True,
        "clientActorPreserved": True,
        "fullResources": True,
        "hostFirstRespawnSpawnDelta": host_first_spawn_delta,
        "peerRespawnPlacementConverged": True,
        "peerRespawnPlacementDelta": peer_placement_delta,
        "hostRespawnDisplacement": math.hypot(
            number(host_alive, "first_respawn_x")
            - number(host_dead, "actor_x"),
            number(host_alive, "first_respawn_y")
            - number(host_dead, "actor_y"),
        ),
        "clientBRespawnDisplacement": math.hypot(
            number(host_alive, "first_respawn_x")
            - number(client_dead, "actor_x"),
            number(host_alive, "first_respawn_y")
            - number(client_dead, "actor_y"),
        ),
        "hostRequestedSpawnNavTraversable": boolean(
            host_alive,
            "spawn_nav_traversable",
        ),
        "hostSettledActorNavTraversable": boolean(
            host_alive,
            "actor_nav_traversable",
        ),
        "clientBSettledActorNavTraversable": boolean(
            client_alive,
            "actor_nav_traversable",
        ),
        "nativeMoveStepScale": number(
            client_alive,
            "move_step_scale",
        ),
        "nameplateHealthRatio": number(
            client_alive,
            "nameplate_health_ratio",
        ),
    }


def invoke_native_lethal_hit(
    host_pipe: str,
    participant_id: int,
) -> dict[str, Any]:
    probes: list[dict[str, Any]] = []
    for probe_index in range(NATIVE_LETHAL_PROBE_LIMIT):
        queued = values(
            host_pipe,
            f"""
local ok, err, serial =
  sd.debug.queue_native_magic_hit_behavior_probe(
    0.0, 10000.0, 8, {participant_id}, 0.0)
print("ok=" .. tostring(ok))
print("error=" .. tostring(err or ""))
print("serial=" .. tostring(serial or 0))
""",
        )
        serial = integer(queued, "serial")
        if queued.get("ok") != "true" or serial <= 0:
            raise RespawnVerificationFailure(
                f"Native lethal hit did not queue: {queued}"
            )
        result, completed_at = wait_for(
            lambda: values(
                host_pipe,
                f"""
local completed, success, before, after, err =
  sd.debug.get_native_magic_hit_behavior_probe_result({serial})
print("completed=" .. tostring(completed))
print("success=" .. tostring(success))
print("before=" .. tostring(before or 0))
print("after=" .. tostring(after or 0))
print("error=" .. tostring(err or ""))
""",
            ),
            lambda row: row.get("completed") == "true",
            label="native synthetic lethal hit",
            timeout=12,
            interval=0.05,
        )
        hp_before = number(result, "before")
        hp_after = number(result, "after")
        if (
            result.get("success") != "true"
            or not math.isfinite(hp_before)
            or not math.isfinite(hp_after)
            or hp_before <= 0.0
            or hp_after > hp_before + VITAL_TOLERANCE
        ):
            raise RespawnVerificationFailure(
                f"Native lethal hit returned an invalid result: {result}"
            )
        probes.append(
            {
                "serial": serial,
                "completedAt": completed_at,
                "hpBefore": hp_before,
                "hpAfter": hp_after,
                "raw": result,
            }
        )
        if hp_after <= 0.0:
            return {
                "serial": serial,
                "serials": [probe["serial"] for probe in probes],
                "completedAt": completed_at,
                "hpBefore": probes[0]["hpBefore"],
                "hpAfter": hp_after,
                "probeCount": len(probes),
                "probes": probes,
                "raw": result,
            }
        if probe_index + 1 < NATIVE_LETHAL_PROBE_LIMIT:
            time.sleep(NATIVE_LETHAL_RETRY_INTERVAL)

    raise RespawnVerificationFailure(
        "Native lethal hit did not kill the synthetic target after "
        f"{NATIVE_LETHAL_PROBE_LIMIT} separated stock probes: {probes}"
    )


def damage_edges_for(
    host_pipe: str,
    participant_id: int,
) -> dict[str, Any]:
    result = values(
        host_pipe,
        f"""
local count, damage = 0, 0.0
local rows = {{}}
for _, row in ipairs(
    sd.debug.take_enemy_damage_observations() or {{}}) do
  if tonumber(row.source_participant_id) == {participant_id} and
      (tonumber(row.hp_delta) or 0) > 0 then
    count = count + 1
    damage = damage + (tonumber(row.hp_delta) or 0)
    rows[#rows + 1] = table.concat({{
      tostring(row.sequence or 0),
      tostring(row.target_actor_address or 0),
      tostring(row.target_hp_before or 0),
      tostring(row.target_hp_after or 0),
      tostring(row.hp_delta or 0),
    }}, "|")
  end
end
print("count=" .. tostring(count))
print("damage=" .. tostring(damage))
print("rows=" .. table.concat(rows, ";"))
""",
    )
    return {
        "count": integer(result, "count"),
        "damage": number(result, "damage", 0.0),
        "rows": result.get("rows", ""),
    }


def target_probe(
    host_pipe: str,
    client_pipe: str,
    participant_id: int,
) -> dict[str, Any]:
    host = values(
        host_pipe,
        f"""
local observer =
  rawget(_G, "__botcombat_respawn_targetability") or {{}}
local ids = {{}}
for key in pairs(observer.network_actor_ids or {{}}) do
  ids[#ids + 1] = tonumber(key) or 0
end
for _, actor in ipairs(sd.world.list_actors() or {{}}) do
  if actor.tracked_enemy == true and actor.dead ~= true and
      tonumber(actor.target_participant_id) == {participant_id} then
    ids[#ids + 1] = tonumber(actor.network_actor_id) or 0
  end
end
for _, actor in ipairs(
    (sd.world.get_replicated_actors() or {{}}).actors or {{}}) do
  if tonumber(actor.target_participant_id) == {participant_id} then
    ids[#ids + 1] = tonumber(actor.network_actor_id) or 0
  end
end
table.sort(ids)
local unique, prior = {{}}, nil
for _, id in ipairs(ids) do
  if id > 0 and id ~= prior then
    unique[#unique + 1] = tostring(id)
    prior = id
  end
end
print("ids=" .. table.concat(unique, ","))
""",
    )
    client = values(
        client_pipe,
        f"""
local observer =
  rawget(_G, "__botcombat_respawn_targetability") or {{}}
local ids = {{}}
for key in pairs(observer.network_actor_ids or {{}}) do
  ids[#ids + 1] = tonumber(key) or 0
end
for _, actor in ipairs(
    (sd.world.get_replicated_actors() or {{}}).actors or {{}}) do
  if tonumber(actor.target_participant_id) == {participant_id} then
    ids[#ids + 1] = tonumber(actor.network_actor_id) or 0
  end
end
table.sort(ids)
local unique, prior = {{}}, nil
for _, id in ipairs(ids) do
  if id > 0 and id ~= prior then
    unique[#unique + 1] = tostring(id)
    prior = id
  end
end
print("ids=" .. table.concat(unique, ","))
""",
    )

    def observed_ids(row: dict[str, str]) -> set[int]:
        return {
            int(token)
            for token in row.get("ids", "").split(",")
            if token.isdigit() and int(token) > 0
        }

    host_ids = observed_ids(host)
    client_ids = observed_ids(client)
    coherent_ids = sorted(host_ids & client_ids)
    return {
        "host": host,
        "clientB": client,
        "hostNetworkActorIds": sorted(host_ids),
        "clientBNetworkActorIds": sorted(client_ids),
        "networkActorId": coherent_ids[0] if coherent_ids else 0,
        "coherent": bool(coherent_ids),
    }


def capture_client_b(
    client_pipe: str,
    screenshot_directory: Path,
    participant: dict[str, str],
) -> dict[str, Any]:
    raw = screenshot_directory / "client-b-respawn.bmp"
    output = screenshot_directory / "client-b-respawn.png"
    raw.unlink(missing_ok=True)
    output.unlink(missing_ok=True)
    focus_x = number(participant, "actor_x")
    focus_y = number(participant, "actor_y")
    focused = values(
        client_pipe,
        f"""
local ok, err = pcall(sd.camera.set_focus, {focus_x}, {focus_y})
local camera = sd.camera.get_state() or {{}}
print("ok=" .. tostring(ok))
print("error=" .. tostring(err or ""))
print("owns_focus=" .. tostring(camera.owns_focus == true))
print("focus_x=" .. tostring(camera.focus_x or 0))
print("focus_y=" .. tostring(camera.focus_y or 0))
""",
    )
    if focused.get("ok") != "true":
        raise RespawnVerificationFailure(
            f"client B could not focus the respawned bot: {focused}"
        )
    time.sleep(0.25)
    captured = values(
        client_pipe,
        f"""
local ok, err =
  sd.debug.capture_backbuffer({json.dumps(windows_path(raw))})
print("ok=" .. tostring(ok))
print("error=" .. tostring(err or ""))
""",
    )
    if captured.get("ok") != "true":
        raise RespawnVerificationFailure(
            f"client B backbuffer capture failed: {captured}"
        )
    quality = validate_backbuffer(raw, output)
    with Image.open(output) as image:
        if image.width < 640 or image.height < 360:
            raise RespawnVerificationFailure(
                f"client B capture is too small: {image.size}"
            )
    return {
        "path": str(output),
        "rawPath": str(raw),
        "quality": quality,
        "focus": focused,
    }


def promote_host_bots(host_pipe: str) -> dict[str, str]:
    return values(
        host_pipe,
        r"""
local player = assert(sd.player.get_state(), "slot 0 unavailable")
local applied = 0
for index, bot in ipairs(sd.bots.get_state() or {}) do
  local ok = sd.bots.update({
    id = bot.id,
    scene = { kind = "run" },
    heading = 0.0,
    position = {
      x = (tonumber(player.x) or 0) + (index - 1) * 28.0,
      y = tonumber(player.y) or 0,
    },
  })
  if ok == true then applied = applied + 1 end
end
print("applied=" .. tostring(applied))
""",
    )


def run_verification(
    batch_directory: Path,
    batch_id: str,
    instance_prefix_override: str = "",
) -> dict[str, Any]:
    instance_prefix = instance_prefix_override or (
        f"botcombat-respawn-{batch_id}"[:48].rstrip("._-")
    )
    ledger_path = batch_directory / "pair-process-ledger.json"
    launch_log = batch_directory / "pair-launch.log"
    screenshot_directory = batch_directory / "screenshots"
    screenshot_directory.mkdir()
    assert_owned_stages_idle(instance_prefix)

    result: dict[str, Any] = {
        "schemaVersion": 1,
        "startedAt": utc_now(),
        "sourceSha": source_sha(),
        "ports": [HOST_PORT, CLIENT_PORT],
        "instancePrefix": instance_prefix,
    }
    cleanup: list[dict[str, Any]] = []
    launch_wrapper: subprocess.Popen[str] | None = None
    failure: Exception | None = None
    try:
        launch, launch_wrapper = launch_pair(
            instance_prefix,
            ledger_path,
            launch_log,
        )
        result["launch"] = launch
        host_pipe = str(launch["hostLuaPipe"])
        client_pipe = str(launch["clientLuaPipe"])
        wait_for(
            lambda: values(host_pipe, SCENE_PROBE),
            lambda row: row.get("ready") == "true",
            label="host Lua pipe",
            timeout=30,
        )
        result["hostNavigation"] = drive_peer_to_hub(
            host_pipe,
            int(launch["hostProcessId"]),
            element="fire",
        )
        wait_for(
            lambda: values(client_pipe, SCENE_PROBE),
            lambda row: row.get("ready") == "true",
            label="client B Lua pipe",
            timeout=45,
        )
        result["clientBNavigation"] = drive_peer_to_hub(
            client_pipe,
            int(launch["clientProcessId"]),
            element="fire",
        )
        result["hostHubReady"] = wait_for(
            lambda: values(host_pipe, SCENE_PROBE),
            lambda row: row.get("scene") == "hub",
            label="host hub",
            timeout=60,
        )[1]
        result["clientBHubReady"] = wait_for(
            lambda: values(client_pipe, SCENE_PROBE),
            lambda row: row.get("scene") == "hub",
            label="client B hub",
            timeout=60,
        )[1]
        result["hostBotRosterConfig"] = configure_host_bot_roster(
            instance_prefix,
            host_pipe,
        )
        run_seed = values(
            host_pipe,
            f"""
lua_bots_disable_tick = true
local seed = sd.rng.set_seed({RETAIL_RUN_SEED})
print("seed=" .. tostring(seed or 0))
print("bots_quiesced=" .. tostring(lua_bots_disable_tick))
""",
        )
        if (
            integer(run_seed, "seed") != RETAIL_RUN_SEED
            or not boolean(run_seed, "bots_quiesced")
        ):
            raise RespawnVerificationFailure(
                f"Deterministic retail run setup failed: {run_seed}"
            )
        result["retailRunSeed"] = run_seed

        started, started_at = wait_for(
            lambda: values(
                host_pipe,
                r"""
local invoked, ok, detail = pcall(sd.hub.start_testrun)
print("ok=" .. tostring(invoked and ok == true))
print("detail=" ..
  tostring(invoked and (detail or "") or ok or ""))
""",
            ),
            lambda row: row.get("ok") == "true",
            label="settled host retail test-run transition",
            timeout=30,
            interval=0.25,
        )
        result["runStart"] = started
        result["runStartAt"] = started_at
        result["hostRunReady"] = wait_for(
            lambda: values(host_pipe, SCENE_PROBE),
            lambda row: row.get("scene") == "testrun",
            label="host test run",
            timeout=60,
        )[1]
        result["clientBRunReady"] = wait_for(
            lambda: values(client_pipe, SCENE_PROBE),
            lambda row: row.get("scene") == "testrun",
            label="client B test run",
            timeout=60,
        )[1]
        result["clientBCombatController"] = arm_client_b_combat(
            client_pipe
        )
        result["botPromotion"] = promote_host_bots(host_pipe)

        roster, roster_at = wait_for(
            lambda: values(host_pipe, BOT_ROSTER_PROBE),
            lambda row: integer(row, "count") == 2,
            label="two-seat host-owned run bot roster",
            timeout=45,
        )
        participant_id = integer(roster, "bot.1.id")
        if participant_id <= 0:
            raise RespawnVerificationFailure(
                f"Host returned an invalid synthetic participant: {roster}"
            )
        result["target"] = {
            "participantId": participant_id,
            "name": roster.get("bot.1.name", ""),
            "selectedAt": roster_at,
        }
        initial_host, initial_host_at = wait_for(
            lambda: values(
                host_pipe,
                participant_probe(participant_id),
            ),
            state_is_alive,
            label="host live synthetic actor",
            timeout=30,
        )
        initial_client, initial_client_at = wait_for(
            lambda: values(
                client_pipe,
                participant_probe(participant_id),
            ),
            state_is_alive,
            label="client B live synthetic actor",
            timeout=30,
        )
        result["initial"] = {
            "host": initial_host,
            "hostAt": initial_host_at,
            "clientB": initial_client,
            "clientBAt": initial_client_at,
        }

        reset = values(
            host_pipe,
            r"""
print("enemy=" ..
  tostring(sd.debug.reset_enemy_damage_observations()))
print("player=" ..
  tostring(sd.debug.reset_player_damage_observations()))
""",
        )
        result["damageObserversReset"] = reset
        result["retailRoute"] = route_slot_zero_to_retail_waves(
            host_pipe
        )
        active_wave = result["retailRoute"]["activeWave"]
        active_at = result["retailRoute"]["activeWaveAt"]
        result["activeWave"] = active_wave
        result["activeWaveAt"] = active_at
        mid_wave, mid_wave_at = wait_for(
            lambda: values(host_pipe, WAVE_PROBE),
            lambda row: (
                integer(row, "wave") >= integer(active_wave, "wave")
                and integer(row, "alive") > 0
                and row.get("phase") in {"spawning", "clearing"}
            ),
            label="active live retail wave with surviving enemies",
            timeout=15,
            interval=0.1,
        )
        result["midWaveCheckpoint"] = mid_wave
        result["midWaveCheckpointAt"] = mid_wave_at

        lethal_window, lethal_window_at = wait_for(
            lambda: {
                "wave": values(host_pipe, WAVE_PROBE),
                "target": values(
                    host_pipe,
                    participant_probe(participant_id),
                ),
            },
            lambda row: lethal_window_ready(
                row["wave"],
                row["target"],
                integer(active_wave, "wave"),
            ),
            label="late retail wave lethal window",
            timeout=90,
            interval=0.05,
        )
        result["lethalWindow"] = lethal_window
        result["lethalWindowAt"] = lethal_window_at
        result["preLethalCombatPause"] = {
            "host": set_combat_activity(
                host_pipe,
                enabled=False,
                manage_bots=True,
            ),
            "clientB": set_combat_activity(
                client_pipe,
                enabled=False,
                manage_bots=False,
            ),
        }
        time.sleep(0.25)
        result["nativeLethalHit"] = invoke_native_lethal_hit(
            host_pipe,
            participant_id,
        )
        result["postLethalTargetHold"] = values(
            host_pipe,
            f"""
local hold = {{
  active = true,
  participant_id = {participant_id},
  stops = 0,
}}
rawset(_G, "__botcombat_respawn_target_hold", hold)
local baseline_runtime =
  sd.runtime.get_multiplayer_state() or {{}}
local baseline_spectator =
  baseline_runtime.death_spectator or {{}}
local observer = {{
  participant_id = {participant_id},
  baseline_epoch =
    tonumber(baseline_spectator.last_applied_respawn_epoch) or 0,
  first_respawn = nil,
}}
rawset(_G, "__botcombat_respawn_observer", observer)
rawset(_G, "__botcombat_respawn_targetability", {{
  participant_id = {participant_id},
  network_actor_ids = {{}},
}})
sd.events.on("runtime.tick", function()
  local current =
    rawget(_G, "__botcombat_respawn_target_hold")
  if type(current) == "table" and current.active == true then
    local ok, stopped = pcall(
      sd.bots.stop,
      current.participant_id)
    if ok and stopped == true then
      current.stops = current.stops + 1
    end
  end
  local current_observer =
    rawget(_G, "__botcombat_respawn_observer")
  local runtime = sd.runtime.get_multiplayer_state() or {{}}
  local spectator = runtime.death_spectator or {{}}
  local epoch =
    tonumber(spectator.last_applied_respawn_epoch) or 0
  if type(current_observer) ~= "table" or
      epoch <= (tonumber(current_observer.baseline_epoch) or 0) then
    return
  end
  lua_bots_disable_tick = true
  if type(current_observer.first_respawn) ~= "table" then
    local bot = sd.bots.get_participant_state(
      current_observer.participant_id)
    if type(bot) == "table" and
        (tonumber(bot.hp) or 0) > 0 then
      current_observer.first_respawn = {{
        epoch = epoch,
        actor = tonumber(bot.actor_address) or 0,
        progression =
          tonumber(bot.progression_runtime_state_address) or 0,
        hp = tonumber(bot.hp) or 0,
        max_hp = tonumber(bot.max_hp) or 0,
        mp = tonumber(bot.mp) or 0,
        max_mp = tonumber(bot.max_mp) or 0,
        x = tonumber(bot.x) or 0,
        y = tonumber(bot.y) or 0,
      }}
    end
  end
  local targetability =
    rawget(_G, "__botcombat_respawn_targetability")
  local function observe_target(actor)
    if type(targetability) == "table" and
        tonumber(actor.target_participant_id) ==
          targetability.participant_id then
      local network_id =
        tonumber(actor.network_actor_id) or 0
      if network_id > 0 then
        targetability.network_actor_ids[
          tostring(network_id)] = true
      end
    end
  end
  for _, actor in ipairs(sd.world.list_actors() or {{}}) do
    if actor.tracked_enemy == true and actor.dead ~= true then
      observe_target(actor)
    end
  end
  for _, actor in ipairs(
      (sd.world.get_replicated_actors() or {{}}).actors or {{}}) do
    observe_target(actor)
  end
end)
lua_bots_disable_tick = false
local route_controller =
  rawget(_G, "{ROUTE_CONTROLLER_GLOBAL}")
if type(route_controller) == "table" then
  route_controller.combat_enabled = true
end
print("target_held=" .. tostring(
  type(rawget(_G, "__botcombat_respawn_target_hold")) ==
    "table"))
print("other_bots_active=" .. tostring(
  lua_bots_disable_tick == false))
print("host_slot_zero_combat_active=" .. tostring(
  type(route_controller) == "table" and
  route_controller.combat_enabled == true and
  route_controller.combat_movement_enabled == true))
""",
        )
        if (
            not boolean(
                result["postLethalTargetHold"],
                "target_held",
            )
            or not boolean(
                result["postLethalTargetHold"],
                "other_bots_active",
            )
            or not boolean(
                result["postLethalTargetHold"],
                "host_slot_zero_combat_active",
            )
        ):
            raise RespawnVerificationFailure(
                "Could not hold the dead target while keeping the living "
                "combat controllers active."
            )
        result["clientBPostLethalCombat"] = values(
            client_pipe,
            f"""
local baseline_runtime =
  sd.runtime.get_multiplayer_state() or {{}}
local baseline_spectator =
  baseline_runtime.death_spectator or {{}}
local observer = {{
  participant_id = {participant_id},
  baseline_epoch =
    tonumber(baseline_spectator.last_applied_respawn_epoch) or 0,
  first_respawn = nil,
}}
rawset(_G, "__botcombat_respawn_observer", observer)
rawset(_G, "__botcombat_respawn_targetability", {{
  participant_id = {participant_id},
  network_actor_ids = {{}},
}})
local route_controller =
  rawget(_G, "{ROUTE_CONTROLLER_GLOBAL}")
if type(route_controller) == "table" then
  route_controller.combat_enabled = true
end
sd.events.on("runtime.tick", function()
  local current =
    rawget(_G, "__botcombat_respawn_observer")
  if type(current) ~= "table" then return end
  local runtime = sd.runtime.get_multiplayer_state() or {{}}
  local spectator = runtime.death_spectator or {{}}
  local epoch =
    tonumber(spectator.last_applied_respawn_epoch) or 0
  if epoch <= (tonumber(current.baseline_epoch) or 0) then return end
  if type(current.first_respawn) ~= "table" then
    local bot =
      sd.bots.get_participant_state(current.participant_id)
    if type(bot) == "table" and
        (tonumber(bot.hp) or 0) > 0 then
      current.first_respawn = {{
        epoch = epoch,
        actor = tonumber(bot.actor_address) or 0,
        progression =
          tonumber(bot.progression_runtime_state_address) or 0,
        hp = tonumber(bot.hp) or 0,
        max_hp = tonumber(bot.max_hp) or 0,
        mp = tonumber(bot.mp) or 0,
        max_mp = tonumber(bot.max_mp) or 0,
        x = tonumber(bot.x) or 0,
        y = tonumber(bot.y) or 0,
      }}
    end
  end
  local targetability =
    rawget(_G, "__botcombat_respawn_targetability")
  for _, actor in ipairs(
      (sd.world.get_replicated_actors() or {{}}).actors or {{}}) do
    if type(targetability) == "table" and
        tonumber(actor.target_participant_id) ==
          targetability.participant_id then
      local network_id =
        tonumber(actor.network_actor_id) or 0
      if network_id > 0 then
        targetability.network_actor_ids[
          tostring(network_id)] = true
      end
    end
  end
end)
local route_controller =
  rawget(_G, "{ROUTE_CONTROLLER_GLOBAL}")
print("client_b_combat_active=" .. tostring(
  type(route_controller) == "table" and
  route_controller.combat_enabled == true and
  route_controller.combat_movement_enabled == true))
""",
        )
        if not boolean(
            result["clientBPostLethalCombat"],
            "client_b_combat_active",
        ):
            raise RespawnVerificationFailure(
                "Could not keep client B combat active during the native "
                "respawn observation."
            )
        host_actor = integer(initial_host, "actor")
        host_progression = integer(initial_host, "progression")
        client_actor = integer(initial_client, "actor")
        client_progression = integer(initial_client, "progression")
        host_dead, host_dead_at = wait_for(
            lambda: values(
                host_pipe,
                participant_probe(participant_id),
            ),
            lambda row: state_is_dead(
                row,
                actor=host_actor,
                progression=host_progression,
            ),
            label="host synthetic corpse",
            timeout=10,
            interval=0.05,
        )
        client_dead, client_dead_at = wait_for(
            lambda: values(
                client_pipe,
                participant_probe(participant_id),
            ),
            lambda row: state_is_dead(
                row,
                actor=client_actor,
                progression=client_progression,
            ),
            label="client B synthetic corpse",
            timeout=10,
            interval=0.05,
        )
        result["corpse"] = {
            "host": host_dead,
            "hostAt": host_dead_at,
            "clientB": client_dead,
            "clientBAt": client_dead_at,
        }

        host_alive, host_alive_at = wait_for(
            lambda: values(
                host_pipe,
                participant_probe(participant_id),
            ),
            lambda row: (
                state_is_alive(row)
                and integer(row, "respawn_epoch")
                > integer(host_dead, "respawn_epoch")
            ),
            label="host native synthetic wave respawn",
            timeout=120,
            interval=0.05,
        )
        completed_wave = values(host_pipe, WAVE_PROBE)
        respawn_wave = integer(host_alive, "respawn_wave")
        if not (
            integer(active_wave, "wave")
            <= respawn_wave
            <= integer(completed_wave, "wave")
        ):
            raise RespawnVerificationFailure(
                "synthetic participant respawned for the wrong completed "
                f"wave: active={active_wave}, death={mid_wave}, "
                f"alive={host_alive}"
            )
        result["completedWave"] = {
            "wave": respawn_wave,
            "durableRespawnEpoch": integer(host_alive, "respawn_epoch"),
            "observedWaveStateAfterRespawn": completed_wave,
        }
        result["completedWaveAt"] = host_alive_at
        client_alive, client_alive_at = wait_for(
            lambda: values(
                client_pipe,
                participant_probe(participant_id),
            ),
            lambda row: (
                state_is_alive(row)
                and integer(row, "respawn_epoch")
                == integer(host_alive, "respawn_epoch")
            ),
            label="client B replicated synthetic wave respawn",
            timeout=15,
            interval=0.05,
        )
        aligned, aligned_at = wait_for(
            lambda: {
                "host": values(
                    host_pipe,
                    participant_probe(participant_id),
                ),
                "clientB": values(
                    client_pipe,
                    participant_probe(participant_id),
                ),
            },
            lambda row: (
                state_is_alive(row["host"])
                and state_is_alive(row["clientB"])
                and integer(row["host"], "respawn_epoch")
                == integer(row["clientB"], "respawn_epoch")
                and math.hypot(
                    number(row["host"], "actor_x")
                    - number(row["clientB"], "actor_x"),
                    number(row["host"], "actor_y")
                    - number(row["clientB"], "actor_y"),
                )
                <= POSITION_TOLERANCE
            ),
            label="host/client B aligned synthetic respawn placement",
            timeout=15,
            interval=0.05,
        )
        host_alive = aligned["host"]
        client_alive = aligned["clientB"]
        result["respawn"] = {
            "host": host_alive,
            "hostAt": host_alive_at,
            "clientB": client_alive,
            "clientBAt": client_alive_at,
            "alignedAt": aligned_at,
            "contract": validate_respawn_transition(
                host_dead,
                client_dead,
                host_alive,
                client_alive,
            ),
        }
        result["clientBVisual"] = capture_client_b(
            client_pipe,
            screenshot_directory,
            client_alive,
        )
        result["postRespawnBotResume"] = values(
            host_pipe,
            f"""
local hold =
  rawget(_G, "__botcombat_respawn_target_hold")
if type(hold) == "table" then hold.active = false end
lua_bots_disable_tick = false
print("resumed=" .. tostring(
  lua_bots_disable_tick == false and
  (type(hold) ~= "table" or hold.active == false) and
  type(rawget(
    _G,
    "__botcombat_respawn_targetability")) == "table"))
""",
        )
        if not boolean(
            result["postRespawnBotResume"],
            "resumed",
        ):
            raise RespawnVerificationFailure(
                "Could not resume bot policy after respawn validation."
            )
        result["clientBPostRespawnResume"] = values(
            client_pipe,
            f"""
print("resumed=" .. tostring(
  type(rawget(
    _G,
    "__botcombat_respawn_targetability")) == "table"))
""",
        )
        if not boolean(
            result["clientBPostRespawnResume"],
            "resumed",
        ):
            raise RespawnVerificationFailure(
                "Could not retain client B targetability observations."
            )

        values(
            host_pipe,
            "print('ok=' .. tostring("
            "sd.debug.reset_enemy_damage_observations()))",
        )
        accumulated = {"count": 0, "damage": 0.0, "rows": []}
        target_evidence: dict[str, Any] | None = None
        last_target_probe: dict[str, Any] | None = None
        post_deadline = time.monotonic() + 120
        while time.monotonic() < post_deadline:
            edges = damage_edges_for(host_pipe, participant_id)
            accumulated["count"] += edges["count"]
            accumulated["damage"] += edges["damage"]
            if edges["rows"]:
                accumulated["rows"].append(edges["rows"])
            if target_evidence is None:
                probe = target_probe(
                    host_pipe,
                    client_pipe,
                    participant_id,
                )
                last_target_probe = probe
                if probe["coherent"]:
                    target_evidence = probe
            if (
                accumulated["count"] >= 1
                and accumulated["damage"] > 0.0
                and target_evidence is not None
            ):
                break
            time.sleep(0.25)
        result["postRespawnDamage"] = accumulated
        result["clientBTargetabilityLast"] = last_target_probe
        if accumulated["count"] < 1 or accumulated["damage"] <= 0.0:
            raise RespawnVerificationFailure(
                "The synthetic bot produced no authoritative enemy-HP "
                f"edge after respawn: {accumulated}"
            )
        if target_evidence is None:
            raise RespawnVerificationFailure(
                "No hostile native target selection for the respawned bot "
                "replicated coherently to client B."
            )
        result["clientBTargetability"] = target_evidence
        result["ok"] = True
        result["completedAt"] = utc_now()
        return result
    except Exception as error:
        failure = error
        result["ok"] = False
        result["error"] = str(error)
        result["completedAt"] = utc_now()
        raise
    finally:
        cleanup_error: Exception | None = None
        try:
            close_pair_wrapper(launch_wrapper)
            cleanup = cleanup_owned_pair(
                ledger_path,
                batch_directory,
            )
            result["processStop"] = cleanup
        except Exception as error:
            cleanup_error = error
            result["processStopError"] = str(error)
        atomic_write_json(batch_directory / "result.json", result)
        if cleanup_error is not None and failure is None:
            raise cleanup_error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Kill one host-owned synthetic fighter through the native "
            "damage handler, prove native wave respawn on host and client "
            "B, then require a post-respawn enemy-HP damage edge."
        )
    )
    parser.add_argument(
        "--batch-id",
        default="",
        help="Filename-safe evidence id; defaults to a UTC timestamp.",
    )
    parser.add_argument(
        "--instance-prefix",
        default="",
        help="Optional isolated launcher instance prefix.",
    )
    parser.add_argument(
        "--host-port",
        type=int,
        default=HOST_PORT,
        help=f"Host UDP port; defaults to {HOST_PORT}.",
    )
    parser.add_argument(
        "--client-port",
        type=int,
        default=CLIENT_PORT,
        help=f"Client UDP port; defaults to {CLIENT_PORT}.",
    )
    return parser


def main() -> int:
    global HOST_PORT, CLIENT_PORT
    args = build_parser().parse_args()
    HOST_PORT = args.host_port
    CLIENT_PORT = args.client_port
    batch_id = args.batch_id or datetime.now(timezone.utc).strftime(
        "respawn-%Y%m%dT%H%M%SZ"
    )
    safe_characters = (
        "abcdefghijklmnopqrstuvwxyz"
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    )
    unsafe_value = next(
        (
            value
            for value in (batch_id, args.instance_prefix)
            if value
            and any(
                character not in safe_characters
                for character in value
            )
        ),
        "",
    )
    if (
        not batch_id
        or unsafe_value
        or HOST_PORT < 1
        or HOST_PORT > 65535
        or CLIENT_PORT < 1
        or CLIENT_PORT > 65535
        or HOST_PORT == CLIENT_PORT
    ):
        print(
            "ERROR: Unsafe batch, instance prefix, or port selection: "
            f"batch={batch_id!r} prefix={args.instance_prefix!r} "
            f"ports={HOST_PORT}/{CLIENT_PORT}",
            file=sys.stderr,
        )
        return 1
    batch_directory = EVIDENCE_ROOT / "runs" / batch_id
    try:
        batch_directory.mkdir(parents=True, exist_ok=False)
        result = run_verification(
            batch_directory,
            batch_id,
            args.instance_prefix,
        )
        print(
            json.dumps(
                {
                    "ok": result["ok"],
                    "result": str(batch_directory / "result.json"),
                    "screenshot": result["clientBVisual"]["path"],
                },
                sort_keys=True,
            )
        )
        return 0
    except (
        OSError,
        ValueError,
        subprocess.SubprocessError,
        RespawnVerificationFailure,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
