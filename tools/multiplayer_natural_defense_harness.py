#!/usr/bin/env python3
"""Natural enemy-contact helpers for multiplayer defense-stat verification."""

from __future__ import annotations

import math
import time
from typing import Any

from multiplayer_defense_behavior_harness import wait_for_observer_life
from verify_local_multiplayer_sync import (
    CLIENT_PIPE,
    HOST_PIPE,
    VerifyFailure,
    lua,
    parse_int_text,
    parse_key_values,
)
from verify_multiplayer_primary_kill_stress import (
    ENABLE_PRELUDE_LUA,
    START_WAVES_LUA,
    set_manual_spawner_test_mode,
    values,
    wait_for_pair_transform_convergence,
)
from verify_player_health_death_sync import (
    query_local_player_vitals,
    set_local_player_vitals,
)


TARGET_X = 1850.0
TARGET_Y = 1750.0
PARKED_PLAYER_X = 2750.0
PARKED_PLAYER_Y = 1750.0
TEST_LIFE = 1_000.0


PIN_PLAYER_LUA = r"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
_G.__sdmod_defense_pin = {
  active = true,
  x = __X__,
  y = __Y__,
}
if not _G.__sdmod_defense_pin_registered then
  sd.events.on('runtime.tick', function()
    local pin = _G.__sdmod_defense_pin
    if type(pin) ~= 'table' or not pin.active then return end
    if sd.input and sd.input.clear_mouse_left then sd.input.clear_mouse_left() end
    if sd.input and sd.input.clear_local_cast_state then
      pcall(sd.input.clear_local_cast_state)
    end
    local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
    local actor = tonumber(player and player.actor_address) or 0
    if actor == 0 then return end
    local ox = sd.debug.layout_offset('actor_position_x')
    local oy = sd.debug.layout_offset('actor_position_y')
    if ox ~= nil then sd.debug.write_float(actor + ox, pin.x) end
    if oy ~= nil then sd.debug.write_float(actor + oy, pin.y) end
  end)
  _G.__sdmod_defense_pin_registered = true
end
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
local actor = tonumber(player and player.actor_address) or 0
if actor ~= 0 then
  local ox = sd.debug.layout_offset('actor_position_x')
  local oy = sd.debug.layout_offset('actor_position_y')
  if ox ~= nil then sd.debug.write_float(actor + ox, _G.__sdmod_defense_pin.x) end
  if oy ~= nil then sd.debug.write_float(actor + oy, _G.__sdmod_defense_pin.y) end
  if sd.world and sd.world.rebind_actor then sd.world.rebind_actor(actor) end
end
emit('ok', true)
emit('x', _G.__sdmod_defense_pin.x)
emit('y', _G.__sdmod_defense_pin.y)
"""


ARM_ENEMY_ARENA_LUA = r"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
_G.__sdmod_defense_enemies = _G.__sdmod_defense_enemies or {
  mode = 'park',
  target_x = __TARGET_X__,
  target_y = __TARGET_Y__,
}
local function desired(index, arena)
  if arena.mode == 'attack' and index <= 4 then
    local offsets = {{128,0},{-128,0},{0,128},{0,-128}}
    return arena.target_x + offsets[index][1], arena.target_y + offsets[index][2]
  end
  return 7000.0 + index * 41.0, 7000.0 + index * 37.0
end
local function drive(arena, rebind)
  local ox = sd.debug.layout_offset('actor_position_x')
  local oy = sd.debug.layout_offset('actor_position_y')
  local actors = sd.world and sd.world.list_actors and sd.world.list_actors() or {}
  local count = 0
  for _, actor in ipairs(actors) do
    local address = tonumber(actor.actor_address) or 0
    local hp = tonumber(actor.hp) or 0
    local max_hp = tonumber(actor.max_hp) or 0
    if address ~= 0 and actor.tracked_enemy and not actor.dead and max_hp > 0 and hp > 0 then
      count = count + 1
      local x, y = desired(count, arena)
      if ox ~= nil then sd.debug.write_float(address + ox, x) end
      if oy ~= nil then sd.debug.write_float(address + oy, y) end
      if rebind and sd.world and sd.world.rebind_actor then
        sd.world.rebind_actor(address)
      end
    end
  end
  arena.count = count
end
if not _G.__sdmod_defense_enemies_registered then
  sd.events.on('runtime.tick', function()
    local arena = _G.__sdmod_defense_enemies
    if type(arena) == 'table' and arena.mode == 'park' then
      drive(arena, false)
    end
  end)
  _G.__sdmod_defense_enemies_registered = true
end
drive(_G.__sdmod_defense_enemies, true)
emit('ok', true)
emit('count', _G.__sdmod_defense_enemies.count or 0)
emit('mode', _G.__sdmod_defense_enemies.mode)
"""


SET_ENEMY_MODE_LUA = r"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local arena = _G.__sdmod_defense_enemies
if type(arena) ~= 'table' then emit('ok', false); return end
arena.mode = '__MODE__'
arena.target_x = __TARGET_X__
arena.target_y = __TARGET_Y__
local target_participant_id = __TARGET_PARTICIPANT_ID__
local target_actor = 0
if target_participant_id == 0 then
  local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
  target_actor = tonumber(player and player.actor_address) or 0
elseif sd.bots and sd.bots.get_participant_state then
  local bot = sd.bots.get_participant_state(target_participant_id)
  target_actor = tonumber(bot and bot.actor_address) or 0
end
local ox = sd.debug.layout_offset('actor_position_x')
local oy = sd.debug.layout_offset('actor_position_y')
local ot = sd.debug.layout_offset('actor_current_target_actor')
local oas = sd.debug.layout_offset('actor_slot')
local ows = sd.debug.layout_offset('actor_world_slot')
local os = sd.debug.layout_offset('actor_animation_selection_state')
local ots = sd.debug.layout_offset('actor_control_brain_target_slot')
local oth = sd.debug.layout_offset('actor_control_brain_target_handle')
local ort = sd.debug.layout_offset('actor_control_brain_retarget_ticks')
local otc = sd.debug.layout_offset('actor_control_brain_target_cooldown_ticks')
local oac = sd.debug.layout_offset('actor_control_brain_action_cooldown_ticks')
local actors = sd.world and sd.world.list_actors and sd.world.list_actors() or {}
local count = 0
local distance = __ATTACK_DISTANCE__
local offsets = {{distance,0},{-distance,0},{0,distance},{0,-distance}}
for _, actor in ipairs(actors) do
  local address = tonumber(actor.actor_address) or 0
  local hp = tonumber(actor.hp) or 0
  local max_hp = tonumber(actor.max_hp) or 0
  if address ~= 0 and actor.tracked_enemy and not actor.dead and max_hp > 0 and hp > 0 then
    count = count + 1
    local x, y
    if arena.mode == 'attack' and count <= 4 then
      x = arena.target_x + offsets[count][1]
      y = arena.target_y + offsets[count][2]
    else
      x = 7000.0 + count * 41.0
      y = 7000.0 + count * 37.0
    end
    if ox ~= nil then sd.debug.write_float(address + ox, x) end
    if oy ~= nil then sd.debug.write_float(address + oy, y) end
    if ot ~= nil then
      sd.debug.write_ptr(
        address + ot,
        arena.mode == 'attack' and target_actor or 0)
    end
    if arena.mode == 'attack' and os ~= nil then
      local brain = tonumber(sd.debug.read_ptr(address + os)) or 0
      if brain ~= 0 then
        local target_slot = target_actor ~= 0 and oas ~= nil and
          (tonumber(sd.debug.read_i8(target_actor + oas)) or -1) or -1
        local target_handle = target_actor ~= 0 and ows ~= nil and
          (tonumber(sd.debug.read_i16(target_actor + ows)) or -1) or -1
        if ots ~= nil then sd.debug.write_u8(brain + ots, target_slot) end
        if oth ~= nil then sd.debug.write_u16(brain + oth, target_handle) end
        if ort ~= nil then sd.debug.write_u32(brain + ort, 0) end
        if otc ~= nil then sd.debug.write_u32(brain + otc, 0) end
        if oac ~= nil then sd.debug.write_u32(brain + oac, 0) end
      end
    end
    if sd.world and sd.world.rebind_actor then sd.world.rebind_actor(address) end
  end
end
arena.count = count
emit('ok', true)
emit('count', count)
emit('mode', arena.mode)
emit('target_actor', target_actor)
"""


def _pipe_values(pipe_name: str, code: str) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, code, timeout=10.0))


def configure_player_pin(pipe_name: str, x: float, y: float) -> dict[str, str]:
    result = _pipe_values(
        pipe_name,
        PIN_PLAYER_LUA.replace("__X__", f"{x:.6f}").replace("__Y__", f"{y:.6f}"),
    )
    if result.get("ok") != "true":
        raise VerifyFailure(f"failed to configure defense pin on {pipe_name}: {result}")
    return result


def configure_target_layout(target_pipe: str) -> dict[str, Any]:
    if target_pipe == HOST_PIPE:
        host_xy = (TARGET_X, TARGET_Y)
        client_xy = (PARKED_PLAYER_X, PARKED_PLAYER_Y)
    elif target_pipe == CLIENT_PIPE:
        host_xy = (PARKED_PLAYER_X, PARKED_PLAYER_Y)
        client_xy = (TARGET_X, TARGET_Y)
    else:
        raise VerifyFailure(f"unknown defense target pipe: {target_pipe}")
    result = {
        "host": configure_player_pin(HOST_PIPE, *host_xy),
        "client": configure_player_pin(CLIENT_PIPE, *client_xy),
    }
    result["convergence"] = wait_for_pair_transform_convergence(timeout=15.0)
    return result


def arm_enemy_arena() -> dict[str, str]:
    result = values(
        HOST_PIPE,
        ARM_ENEMY_ARENA_LUA.replace("__TARGET_X__", f"{TARGET_X:.6f}").replace(
            "__TARGET_Y__", f"{TARGET_Y:.6f}"
        ),
    )
    if result.get("ok") != "true":
        raise VerifyFailure(f"failed to arm defense enemy arena: {result}")
    return result


def set_enemy_mode(
    mode: str,
    target_participant_id: int | None = None,
    attack_distance: float = 128.0,
    timeout: float = 10.0,
) -> dict[str, str]:
    if mode not in {"park", "attack"}:
        raise ValueError(f"unknown defense enemy mode: {mode}")
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    code = (
        SET_ENEMY_MODE_LUA.replace("__MODE__", mode)
        .replace("__TARGET_X__", f"{TARGET_X:.6f}")
        .replace("__TARGET_Y__", f"{TARGET_Y:.6f}")
        .replace("__ATTACK_DISTANCE__", f"{attack_distance:.6f}")
        .replace(
            "__TARGET_PARTICIPANT_ID__",
            str(target_participant_id or 0),
        )
    )
    while time.monotonic() < deadline:
        last = values(HOST_PIPE, code)
        if last.get("ok") == "true" and parse_int_text(last.get("count"), 0) > 0:
            return last
        time.sleep(0.1)
    raise VerifyFailure(f"defense enemy arena had no live enemies in mode={mode}: {last}")


def start_natural_enemy_wave() -> dict[str, Any]:
    manual = {
        "host": set_manual_spawner_test_mode(HOST_PIPE, False),
        "client": set_manual_spawner_test_mode(CLIENT_PIPE, False),
    }
    prelude = values(HOST_PIPE, ENABLE_PRELUDE_LUA)
    waves = values(HOST_PIPE, START_WAVES_LUA)
    if prelude.get("ok") != "true" or waves.get("ok") != "true":
        raise VerifyFailure(
            f"failed to start natural defense wave: prelude={prelude} waves={waves}"
        )
    armed = arm_enemy_arena()
    parked = set_enemy_mode("park")
    return {"manual": manual, "prelude": prelude, "waves": waves, "armed": armed, "parked": parked}


def _float(values: dict[str, str], key: str) -> float:
    try:
        return float(values.get(key, "nan"))
    except ValueError:
        return math.nan


def measure_natural_damage(
    *,
    owner_pipe: str,
    observer_pipe: str,
    participant_id: int,
    seconds: float,
    samples: int,
    timeout: float,
    attack_distance: float = 128.0,
) -> dict[str, Any]:
    if seconds <= 0.0 or samples <= 0:
        raise ValueError("natural damage windows must be positive")
    layout = configure_target_layout(owner_pipe)
    windows: list[dict[str, Any]] = []
    for index in range(samples):
        set_enemy_mode("park")
        set_local_player_vitals(HOST_PIPE, TEST_LIFE, TEST_LIFE)
        set_local_player_vitals(CLIENT_PIPE, TEST_LIFE, TEST_LIFE)
        wait_for_observer_life(observer_pipe, participant_id, TEST_LIFE, timeout, tolerance=0.2)
        attack = set_enemy_mode(
            "attack",
            participant_id if owner_pipe == CLIENT_PIPE else None,
            attack_distance,
        )
        before = query_local_player_vitals(owner_pipe)
        time.sleep(seconds)
        after = query_local_player_vitals(owner_pipe)
        set_enemy_mode("park")
        hp_before = _float(before, "hp")
        hp_after = _float(after, "hp")
        damage = hp_before - hp_after
        if not math.isfinite(damage) or damage < 0.0:
            raise VerifyFailure(
                f"invalid natural damage sample participant={participant_id}: "
                f"before={before} after={after}"
            )
        observer = wait_for_observer_life(
            observer_pipe,
            participant_id,
            hp_after,
            timeout,
            tolerance=8.0,
        )
        windows.append(
            {
                "index": index + 1,
                "seconds": seconds,
                "before": before,
                "after": after,
                "damage": damage,
                "damage_per_second": damage / seconds,
                "enemy_count": parse_int_text(attack.get("count"), 0),
                "observer": observer,
            }
        )
    total_damage = sum(window["damage"] for window in windows)
    total_seconds = seconds * samples
    if total_damage <= 0.01:
        raise VerifyFailure(
            f"natural enemies never damaged participant={participant_id}: {windows}"
        )
    return {
        "layout": layout,
        "windows": windows,
        "total_damage": total_damage,
        "total_seconds": total_seconds,
        "damage_per_second": total_damage / total_seconds,
    }
