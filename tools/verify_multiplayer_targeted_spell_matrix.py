#!/usr/bin/env python3
"""Verify targeted enemy spell casts across all multiplayer player elements."""

from __future__ import annotations

import json
import math
import re
import time
import argparse
from dataclasses import dataclass
from pathlib import Path

from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    CLIENT_PIPE,
    HOST_ID,
    HOST_NAME,
    HOST_PIPE,
    VerifyFailure,
    disable_bots,
    launch_pair,
    lua,
    parse_key_values,
    start_host_testrun_and_wait_for_clients,
    stop_games,
    wait_for_remote,
)
from verify_player_health_death_sync import set_local_player_vitals
from verify_real_input_spell_cast_sync import (
    CLIENT_LOG,
    HOST_LOG,
    Direction,
    detect_instance_pids,
    ensure_host_combat_started,
    log_after,
    queue_gameplay_mouse_left,
    read_log,
    sustain_pair_vitals,
    wait_for_source_cast,
)
from multiplayer_telemetry import MultiplayerTelemetryRecorder
from verify_run_world_snapshot import wait_for_run_snapshot


ROOT = Path(__file__).resolve().parent.parent
TELEMETRY_PATH = ROOT / "runtime" / "multiplayer_targeted_spell_matrix_telemetry.jsonl"
TELEMETRY: MultiplayerTelemetryRecorder | None = None
TEST_PLAYER_HP = 5000.0
FIRE_TAP_FRAMES = 2
TAP_FRAMES = 12
HOLD_FRAMES = 170


@dataclass(frozen=True)
class ElementSpec:
    element: str
    mode: str
    frames: int

    @property
    def preset(self) -> str:
        return f"map_create_{self.element}_mind_hub"


ELEMENTS = (
    ElementSpec("fire", "projectile", FIRE_TAP_FRAMES),
    ElementSpec("earth", "projectile", HOLD_FRAMES),
    ElementSpec("ether", "projectile", TAP_FRAMES),
    ElementSpec("water", "continuous", HOLD_FRAMES),
    ElementSpec("air", "continuous", HOLD_FRAMES),
)
ELEMENT_BY_NAME = {spec.element: spec for spec in ELEMENTS}


def record_telemetry(label: str, **extra: object) -> None:
    if TELEMETRY is not None:
        TELEMETRY.record(label, **extra)


def sample_telemetry_window(label: str, *, duration: float, interval: float = 0.2, **extra: object) -> None:
    if TELEMETRY is not None:
        TELEMETRY.sample_window(label, duration=duration, interval=interval, **extra)


TARGET_SETUP_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local function finite(v) return type(v) == "number" and v == v and v ~= math.huge and v ~= -math.huge end
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
if player == nil or tonumber(player.actor_address) == 0 then
  emit("ok", false)
  emit("reason", "player_missing")
  return
end
local player_actor = tonumber(player.actor_address) or 0
local actors = sd.world.list_actors and sd.world.list_actors() or {}
local replicated = sd.world.get_replicated_actors and sd.world.get_replicated_actors() or nil
if replicated == nil or replicated.actors == nil then
  emit("ok", false)
  emit("reason", "replicated_snapshot_missing")
  return
end

local local_by_address = {}
for _, actor in ipairs(actors) do
  local address = tonumber(actor.actor_address) or 0
  if address ~= 0 then local_by_address[address] = actor end
end

local snapshot_by_id = {}
for _, actor in ipairs(replicated.actors) do
  local id = tonumber(actor.network_actor_id) or 0
  if id ~= 0 then snapshot_by_id[id] = actor end
end

local network_by_local = {}
if replicated.bindings ~= nil then
  for _, binding in ipairs(replicated.bindings) do
    local id = tonumber(binding.network_actor_id) or 0
    local address = tonumber(binding.local_actor_address) or 0
    if id ~= 0 and address ~= 0 and binding.matched and not binding.parked and not binding.removed then
      network_by_local[address] = id
    end
  end
end

local function resolve_network_id(local_actor)
  local address = tonumber(local_actor.actor_address) or 0
  if network_by_local[address] ~= nil then return network_by_local[address] end
  local local_type = tonumber(local_actor.object_type_id) or 0
  local local_x = tonumber(local_actor.x) or 0
  local local_y = tonumber(local_actor.y) or 0
  local best_id = 0
  local best_d2 = nil
  for _, snapshot in ipairs(replicated.actors) do
    local id = tonumber(snapshot.network_actor_id) or 0
    local snapshot_type = tonumber(snapshot.native_type_id or snapshot.object_type_id) or 0
    local hp = tonumber(snapshot.hp) or 0
    local max_hp = tonumber(snapshot.max_hp) or 0
    if id ~= 0 and snapshot.tracked_enemy and snapshot_type == local_type and max_hp > 0 and hp > 0.25 then
      local dx = (tonumber(snapshot.x) or 0) - local_x
      local dy = (tonumber(snapshot.y) or 0) - local_y
      local d2 = dx * dx + dy * dy
      if d2 <= (128.0 * 128.0) and (best_d2 == nil or d2 < best_d2) then
        best_d2 = d2
        best_id = id
      end
    end
  end
  return best_id
end

local best = nil
local best_d2 = nil
local player_x = tonumber(player.x) or 0
local player_y = tonumber(player.y) or 0
for _, actor in ipairs(actors) do
  local address = tonumber(actor.actor_address) or 0
  local hp = tonumber(actor.hp) or 0
  local max_hp = tonumber(actor.max_hp) or 0
  local x = tonumber(actor.x) or 0
  local y = tonumber(actor.y) or 0
  if address ~= 0 and actor.tracked_enemy and not actor.dead and max_hp > 0 and hp > 0.25 and finite(x) and finite(y) then
    local network_id = resolve_network_id(actor)
    if network_id ~= 0 then
      local dx = x - player_x
      local dy = y - player_y
      local d2 = dx * dx + dy * dy
      if best == nil or d2 < best_d2 then
        best = actor
        best.network_id = network_id
        best_d2 = d2
      end
    end
  end
end
if best == nil then
  emit("ok", false)
  emit("reason", "target_missing")
  return
end

local target_actor = tonumber(best.actor_address) or 0
local target_x = tonumber(best.x) or 0
local target_y = tonumber(best.y) or 0
local caster_x = target_x
local caster_y = target_y + 176.0
local heading = 0.0
local ox = sd.debug.layout_offset("actor_position_x")
local oy = sd.debug.layout_offset("actor_position_y")
local oh = sd.debug.layout_offset("actor_heading")
local os = sd.debug.layout_offset("actor_animation_selection_state")
local oha = sd.debug.layout_offset("actor_control_brain_heading_accumulator")
local odf = sd.debug.layout_offset("actor_control_brain_desired_facing")
local odfs = sd.debug.layout_offset("actor_control_brain_desired_facing_smoothed")
local otarget = sd.debug.layout_offset("actor_current_target_actor")
local oaimx = sd.debug.layout_offset("actor_aim_target_x")
local oaimy = sd.debug.layout_offset("actor_aim_target_y")
local function write_facing(actor, value)
  local wrote = sd.debug.write_float(actor + oh, value)
  if os ~= nil and oha ~= nil and odf ~= nil and odfs ~= nil then
    local control = sd.debug.read_u32(actor + os) or 0
    if control ~= 0 then
      wrote = sd.debug.write_float(control + oha, value) and wrote
      wrote = sd.debug.write_float(control + odf, value) and wrote
      wrote = sd.debug.write_float(control + odfs, value) and wrote
    end
  end
  return wrote
end
local parked_count = 0
if ox ~= nil and oy ~= nil then
  for index, actor in ipairs(actors) do
    local address = tonumber(actor.actor_address) or 0
    if address ~= 0 and address ~= target_actor and actor.tracked_enemy and not actor.dead then
      local park_x = target_x + 2400.0 + (index * 37.0)
      local park_y = target_y + 2400.0 + (index * 29.0)
      if sd.debug.write_float(address + ox, park_x) and sd.debug.write_float(address + oy, park_y) then
        parked_count = parked_count + 1
      end
    end
  end
end

emit("ok", true)
emit("network_actor_id", string.format("%.0f", best.network_id))
emit("target_actor", target_actor)
emit("target_type", tonumber(best.object_type_id) or 0)
emit("target_x", target_x)
emit("target_y", target_y)
emit("target_hp", tonumber(best.hp) or 0)
emit("target_max_hp", tonumber(best.max_hp) or 0)
emit("parked_count", parked_count)
emit("write.player_x", sd.debug.write_float(player_actor + ox, caster_x))
emit("write.player_y", sd.debug.write_float(player_actor + oy, caster_y))
emit("write.heading", write_facing(player_actor, heading))
emit("write.current_target", otarget ~= nil and sd.debug.write_ptr(player_actor + otarget, target_actor) or false)
emit("write.aim_x", oaimx ~= nil and sd.debug.write_float(player_actor + oaimx, target_x) or false)
emit("write.aim_y", oaimy ~= nil and sd.debug.write_float(player_actor + oaimy, target_y) or false)
local after = sd.player.get_state and sd.player.get_state() or nil
emit("after_x", after and after.x or 0)
emit("after_y", after and after.y or 0)
emit("after_heading", after and after.heading or 0)
"""


HOST_ENEMY_BY_ID_LUA = r"""
local target_id = tonumber("__NETWORK_ACTOR_ID__") or 0
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local replicated = sd.world.get_replicated_actors and sd.world.get_replicated_actors() or nil
local actors = sd.world.list_actors and sd.world.list_actors() or {}
if replicated == nil or replicated.actors == nil then
  emit("found", false)
  emit("reason", "replicated_snapshot_missing")
  return
end
for _, snapshot in ipairs(replicated.actors) do
  local id = tonumber(snapshot.network_actor_id) or 0
  if id == target_id then
    local sx = tonumber(snapshot.x) or 0
    local sy = tonumber(snapshot.y) or 0
    local stype = tonumber(snapshot.native_type_id or snapshot.object_type_id) or 0
    local hp = tonumber(snapshot.hp) or 0
    local max_hp = tonumber(snapshot.max_hp) or 0
    local dead = snapshot.dead or false
    for _, actor in ipairs(actors) do
      local actor_type = tonumber(actor.object_type_id) or 0
      if actor.tracked_enemy and actor_type == stype then
        local dx = (tonumber(actor.x) or 0) - sx
        local dy = (tonumber(actor.y) or 0) - sy
        if dx * dx + dy * dy <= (128.0 * 128.0) then
          hp = tonumber(actor.hp) or hp
          max_hp = tonumber(actor.max_hp) or max_hp
          dead = actor.dead or dead
          break
        end
      end
    end
    emit("found", true)
    emit("network_actor_id", string.format("%.0f", target_id))
    emit("hp", string.format("%.3f", hp))
    emit("max_hp", string.format("%.3f", max_hp))
    emit("dead", dead)
    emit("x", sx)
    emit("y", sy)
    return
  end
end
emit("found", false)
"""

TARGET_REFRESH_LUA = r"""
local target_id = tonumber("__NETWORK_ACTOR_ID__") or 0
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
if player == nil or tonumber(player.actor_address) == 0 then
  emit("ok", false)
  emit("reason", "player_missing")
  return
end
local replicated = sd.world.get_replicated_actors and sd.world.get_replicated_actors() or nil
if replicated == nil or replicated.actors == nil then
  emit("ok", false)
  emit("reason", "replicated_snapshot_missing")
  return
end
local snapshot = nil
for _, actor in ipairs(replicated.actors) do
  if tonumber(actor.network_actor_id) == target_id then
    snapshot = actor
    break
  end
end
if snapshot == nil then
  emit("ok", false)
  emit("reason", "target_snapshot_missing")
  return
end

local sx = tonumber(snapshot.x) or 0
local sy = tonumber(snapshot.y) or 0
local stype = tonumber(snapshot.native_type_id or snapshot.object_type_id) or 0
local best_actor = 0
local best_d2 = nil
local actors = sd.world.list_actors and sd.world.list_actors() or {}
for _, actor in ipairs(actors) do
  local actor_type = tonumber(actor.object_type_id) or 0
  local actor_address = tonumber(actor.actor_address) or 0
  if actor_address ~= 0 and actor.tracked_enemy and actor_type == stype and not actor.dead then
    local dx = (tonumber(actor.x) or 0) - sx
    local dy = (tonumber(actor.y) or 0) - sy
    local d2 = dx * dx + dy * dy
    if d2 <= (192.0 * 192.0) and (best_d2 == nil or d2 < best_d2) then
      best_actor = actor_address
      best_d2 = d2
    end
  end
end

local player_actor = tonumber(player.actor_address) or 0
local caster_x = sx
local caster_y = sy + 176.0
local heading = 0.0
local ox = sd.debug.layout_offset("actor_position_x")
local oy = sd.debug.layout_offset("actor_position_y")
local oh = sd.debug.layout_offset("actor_heading")
local os = sd.debug.layout_offset("actor_animation_selection_state")
local oha = sd.debug.layout_offset("actor_control_brain_heading_accumulator")
local odf = sd.debug.layout_offset("actor_control_brain_desired_facing")
local odfs = sd.debug.layout_offset("actor_control_brain_desired_facing_smoothed")
local otarget = sd.debug.layout_offset("actor_current_target_actor")
local oaimx = sd.debug.layout_offset("actor_aim_target_x")
local oaimy = sd.debug.layout_offset("actor_aim_target_y")
local function write_facing(actor, value)
  local wrote = sd.debug.write_float(actor + oh, value)
  if os ~= nil and oha ~= nil and odf ~= nil and odfs ~= nil then
    local control = sd.debug.read_u32(actor + os) or 0
    if control ~= 0 then
      wrote = sd.debug.write_float(control + oha, value) and wrote
      wrote = sd.debug.write_float(control + odf, value) and wrote
      wrote = sd.debug.write_float(control + odfs, value) and wrote
    end
  end
  return wrote
end
local parked_count = 0
if ox ~= nil and oy ~= nil then
  for index, actor in ipairs(actors) do
    local address = tonumber(actor.actor_address) or 0
    if address ~= 0 and address ~= best_actor and actor.tracked_enemy and not actor.dead then
      local park_x = sx + 2400.0 + (index * 37.0)
      local park_y = sy + 2400.0 + (index * 29.0)
      if sd.debug.write_float(address + ox, park_x) and sd.debug.write_float(address + oy, park_y) then
        parked_count = parked_count + 1
      end
    end
  end
end

emit("ok", true)
emit("network_actor_id", string.format("%.0f", target_id))
emit("target_actor", best_actor)
emit("target_x", sx)
emit("target_y", sy)
emit("parked_count", parked_count)
emit("write.player_x", ox ~= nil and sd.debug.write_float(player_actor + ox, caster_x) or false)
emit("write.player_y", oy ~= nil and sd.debug.write_float(player_actor + oy, caster_y) or false)
emit("write.target_x", ox ~= nil and best_actor ~= 0 and sd.debug.write_float(best_actor + ox, sx) or false)
emit("write.target_y", oy ~= nil and best_actor ~= 0 and sd.debug.write_float(best_actor + oy, sy) or false)
emit("write.heading", oh ~= nil and write_facing(player_actor, heading) or false)
emit("write.current_target", otarget ~= nil and best_actor ~= 0 and sd.debug.write_ptr(player_actor + otarget, best_actor) or false)
emit("write.aim_x", oaimx ~= nil and sd.debug.write_float(player_actor + oaimx, sx) or false)
emit("write.aim_y", oaimy ~= nil and sd.debug.write_float(player_actor + oaimy, sy) or false)
local after = sd.player.get_state and sd.player.get_state() or nil
emit("after_x", after and after.x or 0)
emit("after_y", after and after.y or 0)
emit("after_heading", after and after.heading or 0)
"""

DAMAGE_CLAIM_LUA = r"""
local network_actor_id = tonumber("__NETWORK_ACTOR_ID__") or 0
local before_hp = tonumber("__BEFORE_HP__") or 0
local after_hp = tonumber("__AFTER_HP__") or 0
local max_hp = tonumber("__MAX_HP__") or 0
local target_x = tonumber("__TARGET_X__") or 0
local target_y = tonumber("__TARGET_Y__") or 0
local function emit(key, value) print(key .. "=" .. tostring(value)) end
if sd.input == nil or sd.input.queue_local_enemy_damage_claim == nil then
  emit("ok", false)
  emit("reason", "damage_claim_queue_missing")
  return
end
emit("ok", true)
emit("queue_claim", sd.input.queue_local_enemy_damage_claim(
  network_actor_id,
  0,
  before_hp,
  after_hp,
  max_hp,
  target_x,
  target_y))
"""


def values(pipe_name: str, code: str, timeout: float = 5.0) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, code, timeout=timeout))


def number(row: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        value = float(row.get(key, default))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def setup_target(pipe_name: str) -> dict[str, str]:
    result = values(pipe_name, TARGET_SETUP_LUA, timeout=5.0)
    required_writes = (
        "write.player_x",
        "write.player_y",
        "write.heading",
        "write.current_target",
        "write.aim_x",
        "write.aim_y",
    )
    if result.get("ok") != "true" or any(result.get(key) != "true" for key in required_writes):
        raise VerifyFailure(f"target setup failed on {pipe_name}: {result}")
    return result


def host_enemy_by_id(network_actor_id: str) -> dict[str, str]:
    return values(
        HOST_PIPE,
        HOST_ENEMY_BY_ID_LUA.replace("__NETWORK_ACTOR_ID__", network_actor_id),
        timeout=5.0,
    )


def refresh_target_aim(pipe_name: str, network_actor_id: str) -> dict[str, str]:
    result = values(
        pipe_name,
        TARGET_REFRESH_LUA.replace("__NETWORK_ACTOR_ID__", network_actor_id),
        timeout=5.0,
    )
    required_writes = (
        "write.player_x",
        "write.player_y",
        "write.target_x",
        "write.target_y",
        "write.heading",
        "write.aim_x",
        "write.aim_y",
    )
    if result.get("ok") != "true" or any(result.get(key) != "true" for key in required_writes):
        raise VerifyFailure(f"target aim refresh failed on {pipe_name}: network_actor_id={network_actor_id} result={result}")
    return result


def queue_enemy_damage_claim(
    pipe_name: str,
    network_actor_id: str,
    before_hp: float,
    after_hp: float,
    max_hp: float,
    target_x: float,
    target_y: float,
) -> dict[str, str]:
    replacements = {
        "__NETWORK_ACTOR_ID__": network_actor_id,
        "__BEFORE_HP__": f"{before_hp:.6f}",
        "__AFTER_HP__": f"{after_hp:.6f}",
        "__MAX_HP__": f"{max_hp:.6f}",
        "__TARGET_X__": f"{target_x:.6f}",
        "__TARGET_Y__": f"{target_y:.6f}",
    }
    code = DAMAGE_CLAIM_LUA
    for key, value in replacements.items():
        code = code.replace(key, value)
    result = values(pipe_name, code, timeout=5.0)
    if result.get("ok") != "true" or result.get("queue_claim") != "true":
        raise VerifyFailure(f"enemy damage claim queue failed on {pipe_name}: network_actor_id={network_actor_id} result={result}")
    return result


def parse_targeted_local_casts(log_text: str, participant_id: int) -> list[dict[str, int]]:
    pattern = re.compile(
        rf"Multiplayer local cast sent\. participant_id={participant_id} "
        rf"cast_sequence=(\d+) phase=pressed skill_id=\d+ target_network_actor_id=(\d+)"
    )
    return [
        {"cast_sequence": int(sequence), "target_network_actor_id": int(target_id)}
        for sequence, target_id in pattern.findall(log_text)
    ]


def parse_targeted_remote_queues(log_text: str, participant_id: int) -> list[dict[str, object]]:
    pattern = re.compile(
        rf"Multiplayer remote cast queued\. participant_id={participant_id} "
        rf"cast_sequence=(\d+) phase=pressed skill_id=\d+ target_network_actor_id=(\d+) "
        rf"target_actor=([0-9A-Fa-fx]+) target_source=([a-z_]+)"
    )
    return [
        {
            "cast_sequence": int(sequence),
            "target_network_actor_id": int(target_id),
            "target_actor": target_actor,
            "target_source": target_source,
        }
        for sequence, target_id, target_actor, target_source in pattern.findall(log_text)
    ]


def parse_remote_fire_projectile_lifecycles(
    log_text: str,
    participant_id: int,
) -> list[dict[str, int]]:
    result: list[dict[str, int]] = []
    marker = f"[bots] cast complete (pure_primary_no_handle_settled). bot_id={participant_id}"
    for line in log_text.splitlines():
        if marker not in line or "remote_input_controlled=1" not in line:
            continue
        if "remote_projectile_expected_type=0x7D4" not in line:
            continue
        fields: dict[str, int] = {}
        for key in (
            "remote_cast_sequence",
            "remote_projectile_observed_ticks",
            "remote_projectile_missing_ticks",
            "remote_projectile_reached_target",
            "remote_projectile_target_ticks",
        ):
            match = re.search(rf"{key}=([0-9]+)", line)
            if match:
                fields[key] = int(match.group(1))
        if "remote_cast_sequence" in fields:
            result.append(fields)
    return result


def wait_for_remote_fire_projectile_lifecycle(
    direction: Direction,
    receiver_offset: int,
    cast_sequences: list[int],
    timeout: float = 4.0,
) -> list[dict[str, int]]:
    expected = set(cast_sequences)
    deadline = time.monotonic() + timeout
    last_matches: list[dict[str, int]] = []
    while time.monotonic() < deadline:
        lifecycles = parse_remote_fire_projectile_lifecycles(
            log_after(direction.receiver_log, receiver_offset),
            direction.source_id,
        )
        last_matches = [
            item for item in lifecycles
            if item.get("remote_cast_sequence") in expected
        ]
        by_sequence = {
            item.get("remote_cast_sequence"): item
            for item in last_matches
        }
        if expected.issubset(by_sequence):
            bad = [
                item for item in by_sequence.values()
                if item.get("remote_projectile_missing_ticks", 0) < 2
            ]
            if bad:
                raise VerifyFailure(
                    f"{direction.name} fire: receiver completed targeted fireball before native despawn: {bad}"
                )
            return [by_sequence[sequence] for sequence in cast_sequences]
        time.sleep(0.05)
    raise VerifyFailure(
        f"{direction.name} fire: receiver did not complete targeted fireball lifecycle "
        f"for sequences={cast_sequences}; last={last_matches}"
    )


def wait_for_host_hp_drop(network_actor_id: str, before_hp: float, timeout: float = 12.0) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    missing_since: float | None = None
    while time.monotonic() < deadline:
        last = host_enemy_by_id(network_actor_id)
        if last.get("found") == "true":
            missing_since = None
            hp = number(last, "hp", before_hp)
            if last.get("dead") == "true" or hp + 0.1 < before_hp:
                return last
        else:
            now = time.monotonic()
            if missing_since is None:
                missing_since = now
            elif now - missing_since >= 0.4:
                removed = dict(last)
                removed["found"] = "false"
                removed["dead"] = "true"
                removed["removed"] = "true"
                return removed
        time.sleep(0.2)
    raise VerifyFailure(
        f"host enemy hp did not drop for network_actor_id={network_actor_id}; "
        f"before_hp={before_hp:.3f} last={last}"
    )


def verify_targeted_cast(direction: Direction, spec: ElementSpec) -> dict[str, object]:
    record_telemetry("targeted.cast.setup.before", element=spec.element, direction=direction.name)
    setup = setup_target(direction.source_pipe)
    setup_network_actor_id = setup["network_actor_id"]
    network_actor_id = setup_network_actor_id
    record_telemetry(
        "targeted.cast.setup.after",
        element=spec.element,
        direction=direction.name,
        network_actor_id=network_actor_id,
        setup=setup,
    )
    before = host_enemy_by_id(network_actor_id)
    if before.get("found") != "true":
        record_telemetry(
            "targeted.cast.failure.host_target_missing",
            element=spec.element,
            direction=direction.name,
            network_actor_id=network_actor_id,
            setup=setup,
            host=before,
        )
        raise VerifyFailure(f"{direction.name} {spec.element}: host target missing before cast: setup={setup} host={before}")
    before_hp = number(before, "hp")
    source_offset = len(read_log(direction.source_log))
    receiver_offset = len(read_log(direction.receiver_log))
    record_telemetry(
        "targeted.cast.input.before",
        element=spec.element,
        direction=direction.name,
        network_actor_id=network_actor_id,
        before=before,
    )
    aim_refresh = refresh_target_aim(direction.source_pipe, network_actor_id)
    queue_result = queue_gameplay_mouse_left(direction, spec.frames)
    sample_telemetry_window(
        "targeted.cast.input.after",
        duration=0.7,
        interval=0.2,
        element=spec.element,
        direction=direction.name,
        network_actor_id=network_actor_id,
        aim_refresh=aim_refresh,
        queue_result=queue_result,
    )
    source_log, phase_counts, native_hook_count = wait_for_source_cast(
        direction,
        source_offset,
        {"pressed": 1, "released": 1},
        timeout=7.0,
    )
    local_casts = parse_targeted_local_casts(source_log, direction.source_id)
    if len(local_casts) != 1:
        record_telemetry(
            "targeted.cast.failure.local_cast_count",
            element=spec.element,
            direction=direction.name,
            network_actor_id=network_actor_id,
            local_casts=local_casts,
            phase_counts=phase_counts,
            native_hook_count=native_hook_count,
        )
        raise VerifyFailure(f"{direction.name} {spec.element}: expected one local targeted cast, got {local_casts}")
    local_target_id = str(local_casts[0]["target_network_actor_id"])
    if local_target_id != network_actor_id:
        actual_before = host_enemy_by_id(local_target_id)
        record_telemetry(
            "targeted.cast.local_target_swapped",
            element=spec.element,
            direction=direction.name,
            setup_network_actor_id=network_actor_id,
            local_target_id=local_target_id,
            local_casts=local_casts,
            actual_before=actual_before,
        )
        if actual_before.get("found") != "true":
            raise VerifyFailure(
                f"{direction.name} {spec.element}: local cast target mismatch setup={network_actor_id} "
                f"sent={local_target_id}, but sent target is not host-visible: {actual_before}"
            )
        network_actor_id = local_target_id
        before = actual_before
        before_hp = number(before, "hp")
    remote_fire_projectile_lifecycles: list[dict[str, int]] | None = None
    if spec.element == "fire":
        remote_fire_projectile_lifecycles = wait_for_remote_fire_projectile_lifecycle(
            direction,
            receiver_offset,
            [item["cast_sequence"] for item in local_casts],
        )
    receiver_log = log_after(direction.receiver_log, receiver_offset)
    remote_queues = parse_targeted_remote_queues(receiver_log, direction.source_id)
    matching_remote = [
        item for item in remote_queues
        if str(item["target_network_actor_id"]) == network_actor_id and item["target_source"] == "network_id"
    ]
    if not matching_remote:
        record_telemetry(
            "targeted.cast.failure.remote_queue_missing",
            element=spec.element,
            direction=direction.name,
            network_actor_id=network_actor_id,
            remote_queues=remote_queues,
        )
        raise VerifyFailure(
            f"{direction.name} {spec.element}: receiver did not queue network-id targeted cast; "
            f"target={network_actor_id} remote_queues={remote_queues}"
        )
    damage_claim: dict[str, str] | None = None
    if direction.source_id == CLIENT_ID:
        claim_target_x = number(before, "x")
        claim_target_y = number(before, "y")
        if network_actor_id == setup_network_actor_id:
            claim_target_x = number(aim_refresh, "target_x", claim_target_x)
            claim_target_y = number(aim_refresh, "target_y", claim_target_y)
        damage_claim = queue_enemy_damage_claim(
            direction.source_pipe,
            network_actor_id,
            before_hp,
            0.0,
            number(before, "max_hp", before_hp),
            claim_target_x,
            claim_target_y,
        )
        after = wait_for_host_hp_drop(network_actor_id, before_hp)
    else:
        after = {
            "skipped": "host_authority_cast_visual_only",
            "reason": "host-origin targeted matrix verifies cast relay; client-origin direction verifies damage claim acceptance",
        }
    record_telemetry(
        "targeted.cast.done",
        element=spec.element,
        direction=direction.name,
        setup_network_actor_id=setup_network_actor_id,
        network_actor_id=network_actor_id,
        before=before,
        after=after,
        damage_claim=damage_claim,
        local_casts=local_casts,
        remote_queues=remote_queues,
    )
    return {
        "setup": setup,
        "setup_network_actor_id": setup_network_actor_id,
        "network_actor_id": network_actor_id,
        "before": before,
        "after": after,
        "damage_claim": damage_claim,
        "queue_result": queue_result,
        "phase_counts": phase_counts,
        "native_hook_count": native_hook_count,
        "local_casts": local_casts,
        "remote_queues": remote_queues,
        "remote_fire_projectile_lifecycles": remote_fire_projectile_lifecycles,
    }


def launch_element_pair(spec: ElementSpec) -> dict[str, object]:
    record_telemetry("targeted.element.launch.start", element=spec.element, preset=spec.preset)
    launch = launch_pair(preset=spec.preset)
    record_telemetry("targeted.element.launch.ready", element=spec.element, launch=launch)
    pids = detect_instance_pids()
    wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "hub")
    wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "hub")
    record_telemetry("targeted.element.hub.ready", element=spec.element, pids=pids)
    run_entry = start_host_testrun_and_wait_for_clients()
    record_telemetry("targeted.element.run_entry.dispatched", element=spec.element, run_entry=run_entry)
    wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "testrun")
    wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "testrun")
    record_telemetry("targeted.element.run.ready", element=spec.element)
    disable_bots()
    vitals = sustain_pair_vitals()
    record_telemetry("targeted.element.vitals.sustained", element=spec.element)
    combat = ensure_host_combat_started()
    record_telemetry("targeted.element.combat.started", element=spec.element, combat=combat)
    vitals_after_combat = sustain_pair_vitals()
    record_telemetry("targeted.element.combat.vitals_sustained", element=spec.element)
    snapshot = wait_for_run_snapshot(require_complete_lifecycle=True)
    record_telemetry("targeted.element.snapshot.ready", element=spec.element)
    return {
        "launch": launch,
        "pids": pids,
        "run_entry": run_entry,
        "vitals": vitals,
        "combat": combat,
        "vitals_after_combat": vitals_after_combat,
        "snapshot": snapshot,
    }


def verify_element(spec: ElementSpec) -> dict[str, object]:
    record_telemetry("targeted.element.start", element=spec.element, mode=spec.mode, preset=spec.preset)
    setup = launch_element_pair(spec)
    pids = setup["pids"]
    directions = [
        Direction("host_to_client", HOST_ID, HOST_NAME, HOST_PIPE, HOST_LOG, pids["host"], CLIENT_PIPE, CLIENT_LOG),
        Direction("client_to_host", CLIENT_ID, CLIENT_NAME, CLIENT_PIPE, CLIENT_LOG, pids["client"], HOST_PIPE, HOST_LOG),
    ]
    result: dict[str, object] = {
        "element": spec.element,
        "mode": spec.mode,
        "preset": spec.preset,
        "setup": setup,
    }
    for direction in directions:
        record_telemetry("targeted.direction.start", element=spec.element, direction=direction.name)
        result[f"{direction.name}_vitals"] = {
            "host": set_local_player_vitals(HOST_PIPE, TEST_PLAYER_HP, TEST_PLAYER_HP),
            "client": set_local_player_vitals(CLIENT_PIPE, TEST_PLAYER_HP, TEST_PLAYER_HP),
        }
        record_telemetry("targeted.direction.vitals_set", element=spec.element, direction=direction.name)
        result[f"{direction.name}_targeted_cast"] = verify_targeted_cast(direction, spec)
        record_telemetry("targeted.direction.done", element=spec.element, direction=direction.name)
        time.sleep(0.5)
    record_telemetry("targeted.element.done", element=spec.element)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--elements",
        default=",".join(spec.element for spec in ELEMENTS),
        help="Comma-separated element list to verify. Defaults to the full matrix.",
    )
    parser.add_argument(
        "--no-telemetry",
        action="store_true",
        help="Disable heavy host/client telemetry sampling during the focused verifier run.",
    )
    return parser.parse_args()


def selected_elements(raw: str) -> tuple[ElementSpec, ...]:
    names = [name.strip() for name in raw.split(",") if name.strip()]
    if not names:
        raise VerifyFailure("--elements must name at least one element")
    unknown = [name for name in names if name not in ELEMENT_BY_NAME]
    if unknown:
        known = ", ".join(sorted(ELEMENT_BY_NAME))
        raise VerifyFailure(f"unknown element(s) for --elements: {', '.join(unknown)}; expected one of {known}")
    return tuple(ELEMENT_BY_NAME[name] for name in names)


def main() -> int:
    global TELEMETRY
    args = parse_args()
    specs = selected_elements(args.elements)
    TELEMETRY = None if args.no_telemetry else MultiplayerTelemetryRecorder(TELEMETRY_PATH)
    result: dict[str, object] = {"ok": False, "elements": [], "selected_elements": [spec.element for spec in specs]}
    if TELEMETRY is not None:
        result["telemetry_path"] = str(TELEMETRY_PATH)
    record_telemetry("targeted.harness.start", selected_elements=[spec.element for spec in specs])
    try:
        for spec in specs:
            try:
                result["elements"].append(verify_element(spec))
            finally:
                record_telemetry("targeted.element.cleanup", element=spec.element)
                stop_games()
        result["ok"] = True
        record_telemetry("targeted.harness.success")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        result["error"] = str(exc)
        record_telemetry("targeted.harness.failure", error=str(exc))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1
    finally:
        stop_games()


if __name__ == "__main__":
    raise SystemExit(main())
