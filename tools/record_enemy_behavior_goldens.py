#!/usr/bin/env python3
"""Record native enemy behavior traces from one owned solo instance.

The recorder primes the retail wave spawner through ``start_waves``, then uses
the existing exact-group test seam to select one stock archetype at a time. It
never calls an enemy constructor directly. A runtime-tick callback records the
native actor/action fields and player-damage observations. Moving-target trials
drive the local player through the stock movement-input seam.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import record_native_sim_goldens as native_goldens  # noqa: E402
from record_native_sim_goldens import (  # noqa: E402
    CaptureFailure,
    OwnedSoloSession,
    discover_capture_lane,
    place_player,
    require,
    sha256_file,
    source_revision,
)
from verify_player_health_death_sync import set_local_player_vitals  # noqa: E402


INSTANCE = "mon-behavior"
PORTS = (52351, 52352)
PARTICIPANT_ID = "0x2000000000003A31"
MOD_ID = "bot.brain"
RUNTIME_ROOT = ROOT / "runtime" / "monre-live"
GAME_DIRECTORY = Path(
    "/mnt/c/Users/User/Documents/GitHub/SB Modding/"
    "Solomon Dark/SolomonDarkAbandonware"
)
GAME_BINARY = GAME_DIRECTORY / "SolomonDark.exe"
LOADER = ROOT / "bin" / "Release" / "Win32" / "SolomonDarkModLoader.dll"
STAGED_LOADER = ROOT / "dist" / "launcher" / "SolomonDarkModLoader.dll"
DEFAULT_OUTPUT = (
    ROOT / "tests" / "fixtures" / "webgame" /
    "enemy-behavior-goldens.json"
)

FIXED_TICK_MS = 10
RUN_SEED = 0x013579BD
TARGET_HP = 5000.0
SCENARIOS = (
    {
        "archetype": "skeleton",
        "type_id": 0x3E9,
        "ticks": 1000,
        "projectiles": (),
        "active_frames": {0x0E: (4.0,), 0x0F: (9.0,), 0x10: (2.0,)},
    },
    {
        "archetype": "skeleton_archer",
        "type_id": 0x3EA,
        "ticks": 1400,
        "projectiles": (0x7DA,),
        "active_frames": {0x11: (13.0,)},
    },
    {
        "archetype": "skeleton_mage",
        "type_id": 0x3EB,
        "ticks": 1600,
        "projectiles": (0x7EB, 0x7EC),
        "active_frames": {0x12: (25.0, 31.0)},
    },
    {
        "archetype": "dire_faculty",
        "type_id": 0x3F2,
        "ticks": 4000,
        "enemy_offset": 300.0,
        "projectiles": (0x800, 0x801, 0x802, 0x804),
        "active_frames": {0x1F: (15.0,), 0x20: (20.0,)},
    },
)


def _ensure_windows_powershell_is_runnable() -> str:
    """Make the existing solo launcher usable from minimal WSL PATHs."""
    resolved = shutil.which("powershell.exe")
    if resolved:
        completed = subprocess.run(
            [resolved, "-NoProfile", "-NonInteractive", "-Command", "$PSVersionTable.PSVersion.Major"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10.0,
            check=False,
        )
        require(
            completed.returncode == 0 and completed.stdout.strip().isdigit(),
            "powershell.exe resolved but cannot run",
        )
        return resolved

    windows_directory = Path(
        "/mnt/c/Windows/System32/WindowsPowerShell/v1.0"
    )
    executable = windows_directory / "powershell.exe"
    require(executable.is_file(), "Windows PowerShell executable is missing")
    completed = subprocess.run(
        [str(executable), "-NoProfile", "-NonInteractive", "-Command", "$PSVersionTable.PSVersion.Major"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10.0,
        check=False,
    )
    require(
        completed.returncode == 0 and completed.stdout.strip().isdigit(),
        "Windows PowerShell exists but cannot run",
    )
    os.environ["PATH"] = f"{windows_directory}:{os.environ.get('PATH', '')}"
    return str(executable)


def _parse_values(session: OwnedSoloSession, code: str) -> dict[str, str]:
    return session.values(code, timeout=15.0)


def _wait_until(
    session: OwnedSoloSession,
    description: str,
    query: Any,
    predicate: Any,
    *,
    timeout: float,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    last_error = ""
    while time.monotonic() < deadline:
        try:
            last = query()
            if predicate(last):
                return last
        except subprocess.TimeoutExpired as error:
            session.assert_wait_target_runnable(description)
            last_error = str(error)
        time.sleep(0.05)
    detail = f" last_error={last_error}" if last_error else ""
    raise CaptureFailure(f"{description} did not become ready: {last}{detail}")


def start_stock_match(session: OwnedSoloSession) -> dict[str, Any]:
    seeded = _parse_values(
        session,
        f"""
local selected = sd.rng.set_seed({RUN_SEED})
print('selected=' .. tostring(selected or 0))
print('observed=' .. tostring(sd.rng.get_seed() or 0))
""",
    )
    require(
        int(seeded.get("selected", "0")) == RUN_SEED
        and int(seeded.get("observed", "0")) == RUN_SEED,
        f"stock match seed was not accepted: {seeded}",
    )
    requested = _wait_until(
        session,
        "stock Start Match request",
        lambda: _parse_values(
            session,
            """
local call_ok, result = pcall(sd.hub.start_match)
print('call_ok=' .. tostring(call_ok))
print('ok=' .. tostring(call_ok and result == true))
print('error=' .. tostring(call_ok and '' or result))
""",
        ),
        lambda values: values.get("ok") == "true",
        timeout=30.0,
    )
    session.wait_for_scene("testrun")
    return {"seed": seeded, "request": requested}


def prime_stock_spawner(session: OwnedSoloSession) -> dict[str, Any]:
    initial_mode = _parse_values(
        session,
        """
local ok, active = sd.gameplay.set_manual_enemy_spawner_test_mode(false)
print('ok=' .. tostring(ok))
print('active=' .. tostring(active))
""",
    )
    require(
        initial_mode == {"ok": "true", "active": "false"},
        f"manual mode disable failed: {initial_mode}",
    )
    player_vitals = set_local_player_vitals(
        session.pipe_name,
        TARGET_HP,
        TARGET_HP,
    )
    waves = _parse_values(
        session,
        "print('ok=' .. tostring(sd.gameplay.start_waves()))",
    )
    require(waves.get("ok") == "true", f"start_waves failed: {waves}")

    return {
        "initial_manual_mode": initial_mode,
        "player_vitals": player_vitals,
        "start_waves": waves,
    }


def spawn_enemy(
    session: OwnedSoloSession,
    *,
    type_id: int,
    x: float,
    y: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    armed = _parse_values(
        session,
        f"""
_G.__monre_pending_enemy_spawn = {{
  type_id={type_id}, x={x:.9f}, y={y:.9f},
  done=false, ok=false, error='', request=0, filter_calls=0, spawner=0,
}}
if not _G.__monre_enemy_spawn_filter_registered then
  sd.events.filter('wave.spawning', function(event)
    local pending = rawget(_G, '__monre_pending_enemy_spawn')
    if type(pending) == 'table' and not pending.done then
      pending.filter_calls = pending.filter_calls + 1
      pending.spawner = tonumber(event.spawner_address) or 0
      local mode_ok, active = sd.gameplay.set_manual_enemy_spawner_test_mode(true)
      local ok, err, request = sd.gameplay.spawn_manual_run_enemy{{
        type_id=pending.type_id, x=pending.x, y=pending.y,
        freeze_on_spawn=true, allow_direct_arena_spawn=false
      }}
      pending.mode_ok = mode_ok == true
      pending.manual = active == true
      pending.ok = ok == true
      pending.error = tostring(err or '')
      pending.request = tonumber(request) or 0
      pending.done = true
    end
    return {{
      count=event.count,
      spawn_delay=1000000,
      wave_delay=1000000,
      randomize_spawn_delay=false,
    }}
  end)
  _G.__monre_enemy_spawn_filter_registered = true
end
print('registered=' .. tostring(_G.__monre_enemy_spawn_filter_registered))
print('pending=' .. tostring(_G.__monre_pending_enemy_spawn.done == false))
""",
    )
    require(
        armed == {"registered": "true", "pending": "true"},
        f"enemy spawn wave filter was not armed: {armed}",
    )

    spawner_priming = prime_stock_spawner(session)
    deadline = time.monotonic() + 5.0
    queued: dict[str, str] = {}
    while time.monotonic() < deadline:
        queued = _parse_values(
            session,
            """
local pending = rawget(_G, '__monre_pending_enemy_spawn') or {}
print('done=' .. tostring(pending.done or false))
print('mode_ok=' .. tostring(pending.mode_ok or false))
print('manual=' .. tostring(pending.manual or false))
print('ok=' .. tostring(pending.ok or false))
print('error=' .. tostring(pending.error or ''))
print('request=' .. tostring(pending.request or 0))
print('filter_calls=' .. tostring(pending.filter_calls or 0))
print('spawner=' .. tostring(pending.spawner or 0))
""",
        )
        if queued.get("done") == "true":
            break
        time.sleep(0.05)
    else:
        filter_calls = int(queued.get("filter_calls", "0"))
        if filter_calls == 0:
            raise CaptureFailure("enemy spawn wave.spawning filter never ran")
        raise CaptureFailure(
            "stock wave spawner rejected the request inside "
            f"{filter_calls} wave.spawning callback(s)"
        )

    request_id = int(queued.get("request", "0"))
    require(
        queued.get("mode_ok") == "true"
        and queued.get("manual") == "true"
        and queued.get("ok") == "true"
        and request_id > 0,
        f"enemy spawn request was rejected: {queued}",
    )
    result = _wait_until(
        session,
        f"type {type_id} exact-group spawn",
        lambda: _parse_values(
            session,
            f"""
local result = sd.gameplay.get_last_manual_run_enemy_spawn({request_id})
print('present=' .. tostring(result ~= nil))
print('ok=' .. tostring(result and result.ok or false))
print('actor=' .. tostring(result and result.actor_address or 0))
print('network=' .. tostring(result and result.network_actor_id or 0))
print('type=' .. tostring(result and result.type_id or 0))
print('x=' .. tostring(result and result.x or 0))
print('y=' .. tostring(result and result.y or 0))
print('error=' .. tostring(result and result.error or ''))
""",
        ),
        lambda values: (
            values.get("present") == "true"
            and values.get("ok") == "true"
            and int(values.get("actor", "0")) > 0
            and int(values.get("type", "0")) == type_id
        ),
        timeout=20.0,
    )
    actor = int(result["actor"])
    thaw = _parse_values(
        session,
        f"print('ok=' .. tostring(sd.gameplay.clear_manual_run_enemy_freeze({actor})))",
    )
    require(thaw.get("ok") == "true", f"enemy thaw failed: {thaw}")
    vitals = _parse_values(
        session,
        f"""
local actor = {actor}
local max_offset = sd.debug.layout_offset('enemy_max_hp')
local hp_offset = sd.debug.layout_offset('enemy_current_hp')
print('max=' .. tostring(sd.debug.write_float(
  actor + max_offset, {TARGET_HP:.1f})))
print('hp=' .. tostring(sd.debug.write_float(
  actor + hp_offset, {TARGET_HP:.1f})))
print('rng_seed=' .. tostring(sd.debug.read_i32(actor + 0x1C0) or 0))
""",
    )
    require(
        vitals.get("max") == "true"
        and vitals.get("hp") == "true"
        and "rng_seed" in vitals,
        f"captured enemy vitals failed: {vitals}",
    )
    _wait_until(
        session,
        "captured enemy vitals",
        lambda: _parse_values(
            session,
            f"""
local hp = 0
local found = false
for _, row in ipairs(sd.world.list_actors() or {{}}) do
  if tonumber(row.actor_address) == {actor} then
    found = true
    hp = tonumber(row.hp) or 0
  end
end
print('found=' .. tostring(found))
print('hp=' .. tostring(hp))
""",
        ),
        lambda current: (
            current.get("found") == "true"
            and abs(float(current.get("hp", "0")) - TARGET_HP) <= 0.05
        ),
        timeout=5.0,
    )
    spawner_priming["observed_spawner_address"] = int(queued["spawner"])
    return (
        {
            "request_id": request_id,
            "actor_address": actor,
            "network_actor_id": int(result.get("network", "0")),
            "type_id": type_id,
            "x": float(result["x"]),
            "y": float(result["y"]),
            "capture_vitals": vitals,
            "actor_rng_seed": int(vitals["rng_seed"]),
            "actor_rng_seed_source": (
                "construction draw from the then-active native stream; "
                "level construction may seed that stream from App+0x28 * 0xEF3"
            ),
        },
        spawner_priming,
    )


def retire_priming_enemies(
    session: OwnedSoloSession,
    keep_actor_address: int,
) -> dict[str, str]:
    values = _parse_values(
        session,
        f"""
local keep = {keep_actor_address}
local requested = 0
local failed = 0
for _, actor in ipairs(sd.world.list_actors() or {{}}) do
  local address = tonumber(actor.actor_address) or 0
  if actor.tracked_enemy and not actor.dead and address ~= keep then
    local ok = sd.world.trigger_enemy_death(address)
    if ok then requested = requested + 1 else failed = failed + 1 end
  end
end
print('requested=' .. tostring(requested))
print('failed=' .. tostring(failed))
""",
    )
    require(
        values.get("failed") == "0",
        f"priming enemy retirement failed: {values}",
    )
    settled = _wait_until(
        session,
        "priming enemy retirement",
        lambda: _parse_values(
            session,
            f"""
local keep = {keep_actor_address}
local alive = 0
local keep_alive = false
for _, actor in ipairs(sd.world.list_actors() or {{}}) do
  local address = tonumber(actor.actor_address) or 0
  if actor.tracked_enemy and not actor.dead then
    alive = alive + 1
    if address == keep then keep_alive = true end
  end
end
print('alive=' .. tostring(alive))
print('keep_alive=' .. tostring(keep_alive))
""",
        ),
        lambda current: (
            current.get("alive") == "1"
            and current.get("keep_alive") == "true"
        ),
        timeout=10.0,
    )
    return {**values, **{f"settled_{key}": value for key, value in settled.items()}}


def retire_enemy(session: OwnedSoloSession, actor_address: int) -> dict[str, str]:
    values = _parse_values(
        session,
        f"""
local ok, exception = sd.world.trigger_enemy_death({actor_address})
print('ok=' .. tostring(ok))
print('exception=' .. tostring(exception or 0))
""",
    )
    require(values.get("ok") == "true", f"enemy retirement failed: {values}")
    _wait_until(
        session,
        "retired enemy removal",
        lambda: _parse_values(
            session,
            f"""
local found = false
for _, actor in ipairs(sd.world.list_actors() or {{}}) do
  if tonumber(actor.actor_address) == {actor_address} then
    found = true
  end
end
print('gone=' .. tostring(not found))
""",
        ),
        lambda current: current.get("gone") == "true",
        timeout=10.0,
    )
    return values


ARM_TRACE_LUA = r"""
local actor_address = __ACTOR__
local total_ticks = __TICKS__
local target_mode = '__TARGET_MODE__'
local target_participant_id = __TARGET_ID__
local active_frames = __ACTIVE_FRAMES__
local projectile_types = __PROJECTILE_TYPES__

local trace = {
  active=true, done=false, error='', actor=actor_address,
  total_ticks=total_ticks, target_mode=target_mode,
  target_participant_id=target_participant_id,
  active_frames=active_frames,
  projectile_types=projectile_types,
  samples={}, events={}, seen={}, prior_action=0, prior_progress=0,
  route_leg=0,
}
for _, actor in ipairs(sd.world.list_actors() or {}) do
  trace.seen[tonumber(actor.actor_address) or 0] = true
end
_G.__monre_enemy_trace = trace
sd.debug.reset_player_damage_observations()

local function add_event(current, kind, details)
  local event = {
    tick=#current.samples,
    native_tick=current.native_tick or 0,
    kind=kind,
    action_id=current.action_id or 0,
    amount=0,
    target_participant_id=current.target_participant_id or 0,
    projectile_type=0,
    x=current.x or 0,
    y=current.y or 0,
    hp_before=0,
    hp_after=0,
    source_actor_address=0,
    source_native_type_id=0,
    source='native_runtime_tick',
  }
  for key, value in pairs(details or {}) do event[key] = value end
  current.events[#current.events + 1] = event
end

if not _G.__monre_enemy_trace_registered then
  sd.events.on('runtime.tick', function(event)
    local current = rawget(_G, '__monre_enemy_trace')
    if type(current) ~= 'table' or current.active ~= true then return end
    local row = nil
    for _, actor in ipairs(sd.world.list_actors() or {}) do
      if tonumber(actor.actor_address) == current.actor then row = actor end
    end
    if row == nil then
      current.error = 'enemy_actor_unavailable'
      current.active = false
      current.done = true
      return
    end

    local target = sd.player.get_state()
    if type(target) ~= 'table' then
      current.error = 'target_unavailable'
      current.active = false
      current.done = true
      return
    end

    local action_count = tonumber(sd.debug.read_i32(current.actor + 0xE4)) or 0
    local action_list = tonumber(sd.debug.read_ptr(current.actor + 0xF0)) or 0
    local action = 0
    if action_count < 0 or action_count > 1 then
      current.error = 'ambiguous_action_queue_count:' .. tostring(action_count)
      current.active = false
      current.done = true
      return
    end
    if action_count == 1 then
      if action_list == 0 then
        current.error = 'action_queue_list_missing'
        current.active = false
        current.done = true
        return
      end
      local control = tonumber(sd.debug.read_ptr(action_list)) or 0
      action = control ~= 0 and
        (tonumber(sd.debug.read_ptr(control)) or 0) or 0
      if action == 0 then
        current.error = 'action_queue_entry_unresolvable'
        current.active = false
        current.done = true
        return
      end
    end
    local action_id = action ~= 0 and
      (tonumber(sd.debug.read_i32(action + 0x14)) or 0) or 0
    local progress = action ~= 0 and
      (tonumber(sd.debug.read_float(action + 0x30)) or 0) or 0
    local target_actor = tonumber(sd.debug.read_ptr(current.actor + 0x168)) or 0
    local actor_slot_word = tonumber(sd.debug.read_i32(current.actor + 0x5C)) or 0
    local archer_ready_word = tonumber(sd.debug.read_i32(current.actor + 0x248)) or 0
    local heading_offset = sd.debug.layout_offset('actor_heading')
    local heading = tonumber(sd.debug.read_float(current.actor + heading_offset)) or 0
    local native_tick = type(event) == 'table' and
      (tonumber(event.tick_count) or 0) or 0
    current.native_tick = native_tick
    current.x = tonumber(row.x) or 0
    current.y = tonumber(row.y) or 0

    local attack_active = false
    if action_id ~= current.prior_action then
      if current.prior_action ~= 0 then
        add_event(current, 'action_end', {
          action_id=current.prior_action, source='native_action_queue'})
      end
      if action_id ~= 0 then
        add_event(current, 'action_start', {
          action_id=action_id, source='native_action_queue'})
      end
    elseif action_id ~= 0 then
      for _, threshold in ipairs(current.active_frames[action_id] or {}) do
        if current.prior_progress < threshold and progress >= threshold then
          attack_active = true
          add_event(current, 'attack_active', {
            action_id=action_id,
            source='derived_action_progress_marker',
          })
        end
      end
    end

    for _, actor in ipairs(sd.world.list_actors() or {}) do
      local address = tonumber(actor.actor_address) or 0
      local type_id = tonumber(actor.object_type_id) or 0
      if address ~= 0 and not current.seen[address] and current.projectile_types[type_id] then
        current.seen[address] = true
        attack_active = true
        add_event(current, 'projectile_spawn', {
          action_id=action_id, projectile_type=type_id,
          x=tonumber(actor.x) or 0, y=tonumber(actor.y) or 0,
          source='native_world_registration',
        })
      end
    end

    for _, damage in ipairs(sd.debug.take_player_damage_observations() or {}) do
      local target_participant_id = tonumber(damage.target_participant_id) or 0
      local source_actor_address = tonumber(damage.source_actor_address) or 0
      local source_native_type_id = tonumber(damage.source_native_type_id) or 0
      local owned_source = source_actor_address == current.actor or
        current.projectile_types[source_native_type_id] == true
      if target_participant_id == current.target_participant_id and owned_source then
        local before = tonumber(damage.target_hp_before) or 0
        local after = tonumber(damage.target_hp_after) or 0
        if source_actor_address == current.actor then attack_active = true end
        add_event(current, 'damage', {
          action_id=action_id,
          amount=before-after,
          target_participant_id=target_participant_id,
          projectile_type=current.projectile_types[source_native_type_id] and
            source_native_type_id or 0,
          source_actor_address=source_actor_address,
          source_native_type_id=source_native_type_id,
          hp_before=before,
          hp_after=after,
          source='native_player_damage_observation',
        })
      end
    end

    local state = 'approach'
    if row.dead or (tonumber(row.hp) or 0) <= 0 then
      state = 'death'
    elseif attack_active then
      state = 'attack_active'
    elseif action_id ~= 0 then
      local first = (current.active_frames[action_id] or {})[1]
      if first ~= nil and progress < first then state = 'attack_windup'
      else state = 'recovery' end
    elseif target_actor == 0 then
      state = 'acquire_or_wander'
    else
      state = 'approach_or_cooldown'
    end

    local sample = {
      index=#current.samples,
      native_tick=native_tick,
      x=tonumber(row.x) or 0,
      y=tonumber(row.y) or 0,
      facing=heading,
      state=state,
      action_count=action_count,
      action_id=action_id,
      action_progress=progress,
      target_x=tonumber(target.x) or 0,
      target_y=tonumber(target.y) or 0,
      target_participant_id=current.target_participant_id,
      target_actor_address=target_actor,
      native_actor_slot_u8=actor_slot_word % 256,
      native_archer_ready_u8=archer_ready_word % 256,
      native_attack_range=tonumber(sd.debug.read_float(current.actor + 0x1B0)) or 0,
      hp=tonumber(row.hp) or 0,
    }
    current.samples[#current.samples + 1] = sample
    current.native_tick = native_tick
    current.action_id = action_id
    current.x = sample.x
    current.y = sample.y
    current.target_participant_id = sample.target_participant_id
    current.prior_action = action_id
    current.prior_progress = progress

    if current.target_mode == 'moving_player' then
      local phase = (#current.samples - 1) % 400
      local direction_y = 0
      if phase < 80 then direction_y = 1
      elseif phase >= 200 and phase < 280 then direction_y = -1 end
      if direction_y ~= 0 then
        local ok, result = pcall(
          sd.input.hold_movement_frames, 0, direction_y, 1)
        if not ok or result ~= true then
          current.error = 'player_move_failed:' .. tostring(result or '')
          current.active = false
          current.done = true
          pcall(sd.input.set_native_control_allowance_frames, 0)
          return
        end
      end
    end

    if #current.samples >= current.total_ticks then
      current.active = false
      current.done = true
      if current.target_mode == 'moving_player' then
        pcall(sd.input.set_native_control_allowance_frames, 0)
      end
    end
  end)
  _G.__monre_enemy_trace_registered = true
end
print('registered=' .. tostring(_G.__monre_enemy_trace_registered))
print('active=' .. tostring(_G.__monre_enemy_trace.active))
"""


def _lua_table(values: tuple[int, ...]) -> str:
    return "{" + ",".join(f"[{value}]=true" for value in values) + "}"


def _active_frame_table(values: dict[int, tuple[float, ...]]) -> str:
    rows = []
    for action_id, frames in sorted(values.items()):
        rows.append(
            f"[{action_id}]={{" + ",".join(f"{frame:.9g}" for frame in frames) + "}"
        )
    return "{" + ",".join(rows) + "}"


def arm_trace(
    session: OwnedSoloSession,
    *,
    enemy: dict[str, int | float],
    scenario: dict[str, Any],
    target_mode: str,
    target_id: int,
) -> None:
    replacements = {
        "__ACTOR__": str(enemy["actor_address"]),
        "__TICKS__": str(scenario["ticks"]),
        "__TARGET_MODE__": target_mode,
        "__TARGET_ID__": str(target_id),
        "__ACTIVE_FRAMES__": _active_frame_table(scenario["active_frames"]),
        "__PROJECTILE_TYPES__": _lua_table(scenario["projectiles"]),
    }
    code = ARM_TRACE_LUA
    for token, replacement in replacements.items():
        code = code.replace(token, replacement)
    values = _parse_values(session, code)
    require(
        values == {"registered": "true", "active": "true"},
        f"trace arm failed: {values}",
    )


def wait_for_trace(session: OwnedSoloSession, ticks: int) -> dict[str, str]:
    return _wait_until(
        session,
        "enemy tick trace",
        lambda: _parse_values(
            session,
            """
local trace = rawget(_G, '__monre_enemy_trace') or {}
print('done=' .. tostring(trace.done or false))
print('active=' .. tostring(trace.active or false))
print('count=' .. tostring(#(trace.samples or {})))
print('events=' .. tostring(#(trace.events or {})))
print('error=' .. tostring(trace.error or ''))
""",
        ),
        lambda values: values.get("done") == "true",
        timeout=max(30.0, ticks * FIXED_TICK_MS / 1000.0 + 20.0),
    )


def _parse_sample(line: str) -> dict[str, Any]:
    fields = line.split("|")
    require(len(fields) == 18 and fields[0] == "S", f"malformed sample: {line!r}")
    return {
        "tick": int(fields[1]),
        "native_tick": int(fields[2]),
        "position": [float(fields[3]), float(fields[4])],
        "facing": float(fields[5]),
        "state": fields[6],
        "action_count": int(fields[7]),
        "action_id": int(fields[8]),
        "action_progress": float(fields[9]),
        "target_position": [float(fields[10]), float(fields[11])],
        "target_participant_id": int(fields[12]),
        "target_actor_address": int(fields[13]),
        "native_actor_slot_u8": int(fields[14]),
        "native_archer_ready_u8": int(fields[15]),
        "native_attack_range": float(fields[16]),
        "hp": float(fields[17]),
    }


def _parse_event(line: str) -> dict[str, Any]:
    fields = line.split("|")
    require(len(fields) == 15 and fields[0] == "E", f"malformed event: {line!r}")
    return {
        "tick": int(fields[1]),
        "native_tick": int(fields[2]),
        "kind": fields[3],
        "action_id": int(fields[4]),
        "amount": float(fields[5]),
        "target_participant_id": int(fields[6]),
        "projectile_type": int(fields[7]),
        "position": [float(fields[8]), float(fields[9])],
        "hp_before": float(fields[10]),
        "hp_after": float(fields[11]),
        "source_actor_address": int(fields[12]),
        "source_native_type_id": int(fields[13]),
        "source": fields[14],
    }


def read_trace(session: OwnedSoloSession, count: int, event_count: int) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    for first in range(1, count + 1, 48):
        text = session.lua(
            f"""
local trace = assert(rawget(_G, '__monre_enemy_trace'))
for index={first},math.min(#trace.samples,{first + 47}) do
  local s=trace.samples[index]
  print(table.concat({{'S',s.index,s.native_tick,
    string.format('%.6f',s.x),string.format('%.6f',s.y),
    string.format('%.6f',s.facing),s.state,s.action_count,s.action_id,
    string.format('%.6f',s.action_progress),
    string.format('%.6f',s.target_x),string.format('%.6f',s.target_y),
    s.target_participant_id,s.target_actor_address,
    s.native_actor_slot_u8,s.native_archer_ready_u8,
    string.format('%.6f',s.native_attack_range),
    string.format('%.6f',s.hp)}},'|'))
end
""",
            timeout=15.0,
        )
        samples.extend(_parse_sample(line) for line in text.splitlines() if line.startswith("S|"))
    events: list[dict[str, Any]] = []
    for first in range(1, event_count + 1, 48):
        text = session.lua(
            f"""
local trace = assert(rawget(_G, '__monre_enemy_trace'))
for index={first},math.min(#trace.events,{first + 47}) do
  local e=trace.events[index]
  print(table.concat({{'E',e.tick,e.native_tick,e.kind,e.action_id,
    string.format('%.6f',e.amount),e.target_participant_id,
    e.projectile_type,string.format('%.6f',e.x),string.format('%.6f',e.y),
    string.format('%.6f',e.hp_before),string.format('%.6f',e.hp_after),
    e.source_actor_address or 0,e.source_native_type_id or 0,
    e.source or 'native_runtime_tick'}},'|'))
end
""",
            timeout=15.0,
        )
        events.extend(_parse_event(line) for line in text.splitlines() if line.startswith("E|"))
    require(len(samples) == count and count > 0, f"sample retrieval lost rows: {len(samples)}/{count}")
    require(len(events) == event_count, f"event retrieval lost rows: {len(events)}/{event_count}")
    return {"samples": samples, "events": events}


def capture_scenario(
    session: OwnedSoloSession,
    *,
    scenario: dict[str, Any],
    target_mode: str,
    lane: dict[str, float],
) -> dict[str, Any]:
    center_x = lane["free_x"]
    center_y = lane["free_y"]
    enemy_x = center_x - float(scenario.get("enemy_offset", 50.0))
    enemy_y = center_y
    target_id = int(PARTICIPANT_ID, 0)
    place_player(session, center_x + 30.0, center_y)
    set_local_player_vitals(session.pipe_name, TARGET_HP, TARGET_HP)
    movement_control: dict[str, str] | None = None
    if target_mode == "moving_player":
        movement_control = _parse_values(
            session,
            f"""
local ok, result = pcall(
  sd.input.set_native_control_allowance_frames,
  math.min(3600, {int(scenario['ticks']) + 120}))
print('ok=' .. tostring(ok and result == true))
""",
        )
        require(
            movement_control == {"ok": "true"},
            f"moving-player control allowance failed: {movement_control}",
        )

    enemy, spawner_priming = spawn_enemy(
        session,
        type_id=int(scenario["type_id"]),
        x=enemy_x,
        y=enemy_y,
    )
    priming_retirement = retire_priming_enemies(
        session,
        int(enemy["actor_address"]),
    )
    special_setup: dict[str, str] | None = None
    if scenario["archetype"] == "dire_faculty":
        special_setup = _parse_values(
            session,
            f"""
local address = {int(enemy['actor_address'])} + 0x260
print('write=' .. tostring(sd.debug.write_i32(address, -1)))
print('observed=' .. tostring(sd.debug.read_i32(address) or 0))
""",
        )
        require(
            special_setup == {"write": "true", "observed": "-1"},
            f"Dire Faculty secondary-ready setup failed: {special_setup}",
        )
    arm_trace(
        session,
        enemy=enemy,
        scenario=scenario,
        target_mode=target_mode,
        target_id=target_id,
    )
    status = wait_for_trace(session, int(scenario["ticks"]))
    require(status.get("error") == "", f"trace failed: {status}")
    trace = read_trace(session, int(status["count"]), int(status["events"]))
    partial_path = (
        RUNTIME_ROOT / "partial-traces" /
        f"{scenario['archetype']}__{target_mode}.json"
    )
    partial_path.parent.mkdir(parents=True, exist_ok=True)
    partial_path.write_text(
        json.dumps(trace, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    attack_events = [
        event for event in trace["events"]
        if event["kind"] in {"action_start", "attack_active", "projectile_spawn"}
    ]
    damage_events = [event for event in trace["events"] if event["kind"] == "damage"]
    tail = trace["samples"][-1]
    separations = [
        math.hypot(
            sample["position"][0] - sample["target_position"][0],
            sample["position"][1] - sample["target_position"][1],
        )
        for sample in trace["samples"]
    ]
    distance_summary = {
        "first": separations[0],
        "minimum": min(separations),
        "last": separations[-1],
    }
    require(
        attack_events,
        f"{scenario['archetype']} {target_mode} produced no attack event; "
        f"distance={distance_summary} tail={tail} partial={partial_path}",
    )
    require(
        damage_events,
        f"{scenario['archetype']} {target_mode} produced no damage event; tail={tail} "
        f"events={trace['events'][-8:]}",
    )
    require(
        all(event["amount"] > 0.0 for event in damage_events),
        f"{scenario['archetype']} {target_mode} recorded non-positive damage",
    )
    require(
        all(
            int(event["target_participant_id"]) == target_id
            for event in damage_events
        ),
        f"{scenario['archetype']} trace damaged a non-target participant",
    )
    movement = max(
        math.hypot(
            sample["target_position"][0] - trace["samples"][0]["target_position"][0],
            sample["target_position"][1] - trace["samples"][0]["target_position"][1],
        )
        for sample in trace["samples"]
    )
    if target_mode == "stationary_player":
        require(movement <= 0.01, f"stationary target moved {movement}")
    else:
        require(movement >= 20.0, f"moving player displaced only {movement}")

    retirement = retire_enemy(session, int(enemy["actor_address"]))
    return {
        "id": f"{scenario['archetype']}__{target_mode}",
        "archetype": scenario["archetype"],
        "native_type_id": int(scenario["type_id"]),
        "target_mode": target_mode,
        "target_participant_id": target_id,
        "spawn": enemy,
        "spawner_priming": spawner_priming,
        "priming_retirement": priming_retirement,
        "special_setup": special_setup,
        "movement_control": movement_control,
        "movement_pattern": (
            "80 ticks +Y, 120 idle, 80 ticks -Y, 120 idle"
            if target_mode == "moving_player" else "stationary"
        ),
        "tick_count": len(trace["samples"]),
        "target_displacement": movement,
        "attack_event_count": len(attack_events),
        "damage_event_count": len(damage_events),
        "retirement": retirement,
        **trace,
    }


def build_document(
    *,
    source: dict[str, Any],
    powershell_path: str,
    launch: dict[str, Any],
    stock_match: dict[str, Any],
    lane: dict[str, float],
    traces: list[dict[str, Any]],
    cleanup: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "header": {
            "format": "solomon-dark-native-golden-v1",
            "capture": "enemy_behavior_per_tick",
            "fixture_is_machine_recorded": True,
            "captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "source_commit_sha": source["commit_sha"],
            "source_tree_sha": source["tree_sha"],
            "worktree_dirty_at_capture_start": source["worktree_dirty"],
            "game_binary_path": str(GAME_BINARY),
            "game_binary_sha256": sha256_file(GAME_BINARY),
            "loader_sha256": sha256_file(STAGED_LOADER),
            "build_loader_sha256": sha256_file(LOADER),
            "instance": INSTANCE,
            "ports": list(PORTS),
            "audio_disabled": True,
            "headless": False,
            "powershell_path": powershell_path,
            "capture_method": (
                "Retail fixed-tick runtime callback; stock wave spawner primed "
                "through sd.gameplay.start_waves; exact-group selection through "
                "the existing manual test queue; native SmartObjectManager<Action> "
                "queue reads; "
                "native player-damage observations; moving target driven through "
                "sd.input.hold_movement_frames."
            ),
            "fixed_tick_ms": FIXED_TICK_MS,
            "run_seed": RUN_SEED,
            "run_seed_source": (
                "explicit shared-stream seed before sd.hub.start_match; not a "
                "complete lifecycle seed because level construction can reseed "
                "from App+0x28 * 0xEF3"
            ),
            "stock_match": stock_match,
            "runtime_tick_address": "0x00427800",
            "enemy_action_manager_offset": "0xDC",
            "enemy_action_count_offset": "0xE4",
            "enemy_action_list_offset": "0xF0",
            "action_shared_pointer_layout": "list entry -> control block -> action object",
            "action_id_offset": "0x14",
            "action_progress_offset": "0x30",
            "launch_process_id": int(launch["processId"]),
            "launch_executable_path": launch["executablePath"],
            "spawner_priming": [trace["spawner_priming"] for trace in traces],
            "cleanup": cleanup,
        },
        "attack_timing_constants": {
            "fixed_tick_ms": FIXED_TICK_MS,
            "skeleton_claw": {"action_id": 0x0E, "rate": 0.125, "active_frame": 4.0, "end_frame": 7.0},
            "skeleton_weapon": {"action_id": 0x0F, "rate": 0.25, "active_frame": 9.0, "end_frame": 24.0},
            "skeleton_pike": {"action_id": 0x10, "rate": 0.125, "active_frame": 2.0, "end_frame": 12.0},
            "skeleton_archer": {"action_id": 0x11, "rate": 0.0843750015, "active_frame": 13.0, "end_frame": 16.0},
            "skeleton_mage": {"action_id": 0x12, "rate_base": 0.253125012, "active_frames": [25.0, 31.0], "end_frames": [41.0, 47.0]},
        },
        "capture_lane": lane,
        "traces": traces,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--raw-evidence", type=Path, default=None)
    parser.add_argument(
        "--scenario",
        choices=tuple(scenario["archetype"] for scenario in SCENARIOS),
        help="capture one archetype while diagnosing the live harness",
    )
    parser.add_argument(
        "--target-mode",
        choices=("stationary_player", "moving_player"),
        help="capture one target mode while diagnosing the live harness",
    )
    args = parser.parse_args()

    powershell_path = _ensure_windows_powershell_is_runnable()
    native_goldens.RUNTIME_ROOT = RUNTIME_ROOT
    native_goldens.GAME_DIRECTORY = GAME_DIRECTORY
    native_goldens.GAME_BINARY = GAME_BINARY
    source = source_revision()
    session = OwnedSoloSession(
        instance=INSTANCE,
        ports=PORTS,
        mod_id=MOD_ID,
        participant_id=PARTICIPANT_ID,
        test_blank_boneyard=False,
        headless=False,
    )
    launch: dict[str, Any] | None = None
    cleanup: list[dict[str, Any]] = []
    document: dict[str, Any] | None = None
    try:
        launch = session.launch()
        session.wait_for_pipe()
        session.wait_for_scene("hub")
        stock_match = start_stock_match(session)
        lane = discover_capture_lane(session)
        traces: list[dict[str, Any]] = []
        scenarios = [
            scenario for scenario in SCENARIOS
            if args.scenario is None or scenario["archetype"] == args.scenario
        ]
        target_modes = (
            (args.target_mode,)
            if args.target_mode is not None
            else ("stationary_player", "moving_player")
        )
        for scenario in scenarios:
            for target_mode in target_modes:
                traces.append(
                    capture_scenario(
                        session,
                        scenario=scenario,
                        target_mode=target_mode,
                        lane=lane,
                    )
                )
        cleanup = session.close()
        document = build_document(
            source=source,
            powershell_path=powershell_path,
            launch=launch,
            stock_match=stock_match,
            lane=lane,
            traces=traces,
            cleanup=cleanup,
        )
    finally:
        if session.process_ids:
            cleanup = session.close()

    require(document is not None, "capture produced no document")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(document, indent=2, sort_keys=False) + "\n"
    args.output.write_text(encoded, encoding="utf-8", newline="\n")
    if args.raw_evidence is not None:
        args.raw_evidence.parent.mkdir(parents=True, exist_ok=True)
        args.raw_evidence.write_text(encoded, encoding="utf-8", newline="\n")
    print(f"wrote={args.output}")
    print(f"traces={len(document['traces'])}")
    print(f"sha256={hashlib.sha256(encoded.encode('utf-8')).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
