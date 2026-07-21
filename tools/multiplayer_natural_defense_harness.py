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
    place_player,
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
PARKED_PLAYER_X = 2350.0
PARKED_PLAYER_Y = 1750.0
TEST_LIFE = 1_000.0
TARGET_LAYOUT_TOLERANCE = 8.0
TARGET_LAYOUT_ATTEMPTS = 6
MIN_TARGET_SEPARATION = 300.0


ARM_ENEMY_ARENA_LUA = r"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
_G.__sdmod_defense_enemies = _G.__sdmod_defense_enemies or {
  mode = 'park',
  target_x = __TARGET_X__,
  target_y = __TARGET_Y__,
  selected_actor_address = 0,
  target_actor = 0,
  attack_distance = 128.0,
}
local function drive(arena, rebind)
  local ox = sd.debug.layout_offset('actor_position_x')
  local oy = sd.debug.layout_offset('actor_position_y')
  local ot = sd.debug.layout_offset('actor_current_target_actor')
  local ob = sd.debug.layout_offset('actor_current_target_bucket_delta')
  local bucket_stride = sd.debug.layout_offset('actor_world_bucket_stride')
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
  local selected_count = 0
  local offsets = {{1,0},{-1,0},{0,1},{0,-1}}
  for _, actor in ipairs(actors) do
    local address = tonumber(actor.actor_address) or 0
    local hp = tonumber(actor.hp) or 0
    local max_hp = tonumber(actor.max_hp) or 0
    if address ~= 0 and actor.tracked_enemy and not actor.dead and max_hp > 0 and hp > 0 then
      count = count + 1
      local selected = arena.selected_actor_address == 0 or
        address == arena.selected_actor_address
      local attacking = arena.mode == 'attack' and selected
      local x, y
      if attacking then
        selected_count = selected_count + 1
        local offset = offsets[((selected_count - 1) % #offsets) + 1]
        local distance = tonumber(arena.attack_distance) or 128.0
        x = arena.target_x + offset[1] * distance
        y = arena.target_y + offset[2] * distance
      else
        x = 7000.0 + count * 41.0
        y = 7000.0 + count * 37.0
      end
      if not attacking or rebind then
        if ox ~= nil then sd.debug.write_float(address + ox, x) end
        if oy ~= nil then sd.debug.write_float(address + oy, y) end
      end
      local target_slot = attacking and arena.target_actor ~= 0 and oas ~= nil and
        (tonumber(sd.debug.read_i8(arena.target_actor + oas)) or -1) or -1
      local target_handle = attacking and arena.target_actor ~= 0 and ows ~= nil and
        (tonumber(sd.debug.read_i16(arena.target_actor + ows)) or -1) or -1
      if ot ~= nil then
        sd.debug.write_ptr(
          address + ot, arena.mode == 'attack' and selected and
            arena.target_actor or 0)
      end
      if ob ~= nil then
        local hostile_slot = oas ~= nil and
          (tonumber(sd.debug.read_i8(address + oas)) or -1) or -1
        local bucket_delta = 0
        if attacking and bucket_stride ~= nil and hostile_slot >= 0 and
            target_slot >= 0 and target_handle >= 0 then
          bucket_delta = target_slot * bucket_stride + target_handle -
            hostile_slot * bucket_stride
        end
        sd.debug.write_i32(address + ob, bucket_delta)
      end
      if attacking and os ~= nil then
        local brain = tonumber(sd.debug.read_ptr(address + os)) or 0
        if brain ~= 0 then
          if ots ~= nil then sd.debug.write_u8(brain + ots, target_slot) end
          if oth ~= nil then sd.debug.write_u16(brain + oth, target_handle) end
          if rebind then
            if ort ~= nil then sd.debug.write_u32(brain + ort, 0) end
            if otc ~= nil then sd.debug.write_u32(brain + otc, 0) end
            if oac ~= nil then sd.debug.write_u32(brain + oac, 0) end
          end
        end
      end
      if rebind and sd.world and sd.world.rebind_actor then
        sd.world.rebind_actor(address)
      end
    end
  end
  arena.count = count
  arena.selected_count = selected_count
end
_G.__sdmod_defense_drive = drive
if not _G.__sdmod_defense_enemies_registered then
  sd.events.on('runtime.tick', function()
    local arena = _G.__sdmod_defense_enemies
    if type(arena) == 'table' then
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
arena.selected_actor_address = __ENEMY_ACTOR_ADDRESS__
arena.attack_distance = __ATTACK_DISTANCE__
local target_participant_id = __TARGET_PARTICIPANT_ID__
local target_actor = 0
if target_participant_id == 0 then
  local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
  target_actor = tonumber(player and player.actor_address) or 0
elseif sd.bots and sd.bots.get_participant_state then
  local bot = sd.bots.get_participant_state(target_participant_id)
  target_actor = tonumber(bot and bot.actor_address) or 0
end
arena.target_actor = target_actor
if type(_G.__sdmod_defense_drive) == 'function' then
  _G.__sdmod_defense_drive(arena, true)
else
  emit('ok', false)
  return
end
emit('ok', true)
local affected_count = arena.mode == 'attack' and
  (arena.selected_count or 0) or (arena.count or 0)
emit('count', affected_count)
emit('mode', arena.mode)
emit('target_actor', target_actor)
"""


def _pipe_values(pipe_name: str, code: str) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, code, timeout=10.0))


def configure_target_layout(target_pipe: str) -> dict[str, Any]:
    if target_pipe == HOST_PIPE:
        host_xy = (TARGET_X, TARGET_Y)
        client_xy = (PARKED_PLAYER_X, PARKED_PLAYER_Y)
    elif target_pipe == CLIENT_PIPE:
        host_xy = (PARKED_PLAYER_X, PARKED_PLAYER_Y)
        client_xy = (TARGET_X, TARGET_Y)
    else:
        raise VerifyFailure(f"unknown defense target pipe: {target_pipe}")

    attempts: list[dict[str, Any]] = []
    for attempt in range(1, TARGET_LAYOUT_ATTEMPTS + 1):
        host = place_player(HOST_PIPE, *host_xy, 0.0)
        client = place_player(CLIENT_PIPE, *client_xy, 0.0)
        convergence = wait_for_pair_transform_convergence(
            timeout=4.0,
            stable_seconds=0.5,
        )

        def view_point(name: str) -> tuple[float, float]:
            view = convergence.get(name, {})
            return _float(view, "x"), _float(view, "y")

        def point_distance(
            first: tuple[float, float],
            second: tuple[float, float],
        ) -> float:
            return math.hypot(first[0] - second[0], first[1] - second[1])

        if target_pipe == HOST_PIPE:
            owner_local = view_point("host_settled")
            owner_remote = view_point("client_seen_host")
            parked_local = view_point("client_settled")
            parked_remote = view_point("host_seen_client")
        else:
            owner_local = view_point("client_settled")
            owner_remote = view_point("host_seen_client")
            parked_local = view_point("host_settled")
            parked_remote = view_point("client_seen_host")
        metrics = {
            "owner_local_distance": point_distance(
                owner_local, (TARGET_X, TARGET_Y)
            ),
            "owner_remote_distance": point_distance(
                owner_remote, (TARGET_X, TARGET_Y)
            ),
            "parked_peer_delta": point_distance(parked_local, parked_remote),
            "participant_separation": point_distance(owner_local, parked_local),
        }
        record = {
            "attempt": attempt,
            "host": host,
            "client": client,
            "convergence": convergence,
            **metrics,
        }
        attempts.append(record)
        exact_owner = (
            math.isfinite(metrics["owner_local_distance"])
            and metrics["owner_local_distance"] <= TARGET_LAYOUT_TOLERANCE
            and math.isfinite(metrics["owner_remote_distance"])
            and metrics["owner_remote_distance"] <= TARGET_LAYOUT_TOLERANCE
        )
        safe_bystander = (
            math.isfinite(metrics["parked_peer_delta"])
            and metrics["parked_peer_delta"] <= TARGET_LAYOUT_TOLERANCE
            and math.isfinite(metrics["participant_separation"])
            and metrics["participant_separation"] >= MIN_TARGET_SEPARATION
        )
        if exact_owner and safe_bystander:
            return {
                "planned": {"host": host_xy, "client": client_xy},
                "tolerance": TARGET_LAYOUT_TOLERANCE,
                "minimum_separation": MIN_TARGET_SEPARATION,
                "attempts": attempts,
                "final": record,
            }
        time.sleep(0.15)

    raise VerifyFailure(
        "target layout did not hold in both local and remote views: "
        f"attempts={attempts}"
    )


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
    enemy_actor_address: int | None = None,
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
            "__ENEMY_ACTOR_ADDRESS__",
            str(enemy_actor_address or 0),
        )
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


def query_enemy_target_state(
    enemy_actor_address: int,
    target_actor_address: int,
) -> dict[str, str]:
    code = f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local actor = {enemy_actor_address}
local expected_target = {target_actor_address}
local ox = sd.debug.layout_offset('actor_position_x')
local oy = sd.debug.layout_offset('actor_position_y')
local oradius = sd.debug.layout_offset('actor_collision_radius')
local ot = sd.debug.layout_offset('actor_current_target_actor')
local ob = sd.debug.layout_offset('actor_current_target_bucket_delta')
local oas = sd.debug.layout_offset('actor_slot')
local ows = sd.debug.layout_offset('actor_world_slot')
local os = sd.debug.layout_offset('actor_animation_selection_state')
local ots = sd.debug.layout_offset('actor_control_brain_target_slot')
local oth = sd.debug.layout_offset('actor_control_brain_target_handle')
local brain = os ~= nil and (tonumber(sd.debug.read_ptr(actor + os)) or 0) or 0
local actor_x = ox ~= nil and tonumber(sd.debug.read_float(actor + ox)) or nil
local actor_y = oy ~= nil and tonumber(sd.debug.read_float(actor + oy)) or nil
local target_x = ox ~= nil and tonumber(sd.debug.read_float(expected_target + ox)) or nil
local target_y = oy ~= nil and tonumber(sd.debug.read_float(expected_target + oy)) or nil
local target_distance = nil
if actor_x ~= nil and actor_y ~= nil and target_x ~= nil and target_y ~= nil then
  local dx = actor_x - target_x
  local dy = actor_y - target_y
  target_distance = math.sqrt(dx * dx + dy * dy)
end
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
local local_actor = tonumber(player and player.actor_address) or 0
local local_x = local_actor ~= 0 and ox ~= nil and
  tonumber(sd.debug.read_float(local_actor + ox)) or nil
local local_y = local_actor ~= 0 and oy ~= nil and
  tonumber(sd.debug.read_float(local_actor + oy)) or nil
local local_distance = nil
if actor_x ~= nil and actor_y ~= nil and local_x ~= nil and local_y ~= nil then
  local dx = actor_x - local_x
  local dy = actor_y - local_y
  local_distance = math.sqrt(dx * dx + dy * dy)
end
emit('actor', actor)
emit('actor_x', actor_x)
emit('actor_y', actor_y)
emit('actor_slot', oas ~= nil and sd.debug.read_i8(actor + oas) or nil)
emit('actor_world_slot', ows ~= nil and sd.debug.read_i16(actor + ows) or nil)
emit('current_target_actor', ot ~= nil and sd.debug.read_ptr(actor + ot) or nil)
emit('target_bucket_delta', ob ~= nil and sd.debug.read_i32(actor + ob) or nil)
emit('brain', brain)
emit('brain_target_slot', brain ~= 0 and ots ~= nil and
  sd.debug.read_i8(brain + ots) or nil)
emit('brain_target_handle', brain ~= 0 and oth ~= nil and
  sd.debug.read_i16(brain + oth) or nil)
emit('expected_target', expected_target)
emit('target_slot', oas ~= nil and sd.debug.read_i8(expected_target + oas) or nil)
emit('target_world_slot', ows ~= nil and sd.debug.read_i16(expected_target + ows) or nil)
emit('target_x', target_x)
emit('target_y', target_y)
emit('target_distance', target_distance)
emit('target_contact_radius', oradius ~= nil and
  sd.debug.read_float(expected_target + oradius) or nil)
emit('local_actor', local_actor)
emit('local_x', local_x)
emit('local_y', local_y)
emit('local_distance', local_distance)
emit('local_contact_radius', local_actor ~= 0 and oradius ~= nil and
  sd.debug.read_float(local_actor + oradius) or nil)
emit('ok', actor ~= 0 and expected_target ~= 0)
"""
    result = _pipe_values(HOST_PIPE, code)
    if result.get("ok") != "true":
        raise VerifyFailure(f"failed to query enemy target state: {result}")
    return result


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
