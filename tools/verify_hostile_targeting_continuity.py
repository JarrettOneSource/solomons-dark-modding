#!/usr/bin/env python3
"""Verify sane nearest targeting and autonomous distant-straggler cleanup."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import re
import shutil
import sys
import time
import traceback
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
for search_path in (ROOT, TOOLS):
    if str(search_path) not in sys.path:
        sys.path.insert(0, str(search_path))

from tools._real_flow_e2e.evidence import write_json, write_manifest  # noqa: E402
from tools._real_flow_e2e.runtime import LuaPipe  # noqa: E402
from tools._real_flow_e2e.windows import (  # noqa: E402
    BOT_PLAY_TEAM_ROSTER,
    PowerShell,
    assert_ports_free,
    port_inventory,
    windows_path,
    windows_processes,
)
from tools.verify_bot_level_up_continuity import (  # noqa: E402
    _probe as bot_probe,
    _protect_participants,
    _respawn_bot_roster,
    _set_bot_mana,
    _stage_reproducer_package,
    _wait_for,
)
from tools.verify_bot_play_for_me_solo import (  # noqa: E402
    _copy_runtime_artifacts,
    _exact_process,
    _git_sha,
    _launch,
    _ledger_process_id,
    _request_until_true,
    _stop_exact_process,
    _wait_live_wave,
    _wait_run_loading_started,
    _wait_run_ready,
    _wait_scene,
    _write_initial_settings,
)
from tools.verify_multiplayer_organic_player_death import (  # noqa: E402
    WAVE_FIXTURES,
    _materialize_native_wave_schedule,
)
from tools.verify_real_flow_e2e import (  # noqa: E402
    BOT_MOD_ID,
    _drain_damage_observations,
    _reset_damage_observations,
    _udp_exclusion_inventory,
)


TARGET_SAMPLE_SECONDS = 3.0
TARGET_SAMPLE_INTERVAL_SECONDS = 0.1
MINIMUM_TARGET_SAMPLES = 20
MINIMUM_STRAGGLER_DISTANCE = 450.0
# The native movement step can run between the Lua tick lock and the sampler.
# Keep this above one observed step while remaining far below pursuit distance.
MAXIMUM_LOCKED_ENEMY_DISPLACEMENT = 40.0
MAXIMUM_OWNER_DISPLACEMENT = 16.0
STABILIZED_ENEMY_HP = 5000.0
STRAGGLER_ENEMY_HP = 1.0


class HostileTargetingContinuityFailure(RuntimeError):
    """The live hostile-targeting class did not satisfy its contract."""


TARGET_PROBE_LUA = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local enemy_address = __ENEMY_ACTOR_ADDRESS__
local original_enemy_addresses = __ENEMY_ACTOR_ADDRESSES__
local original_enemy_network_ids = __ENEMY_NETWORK_ACTOR_IDS__
local bot_id = __BOT_PARTICIPANT_ID__
local player = sd.player.get_state() or {}
local bot = bot_id ~= 0 and sd.bots.get_participant_state(bot_id) or {}
local root = rawget(_G, "bot_brain_debug") or {}
local brain = type(root.bots) == "table" and root.bots[1] or {}
local ox = sd.debug.layout_offset("actor_position_x")
local oy = sd.debug.layout_offset("actor_position_y")
local target_offset = sd.debug.layout_offset("actor_current_target_actor")
local bucket_offset =
  sd.debug.layout_offset("actor_current_target_bucket_delta")
local latch_offset = sd.debug.layout_offset("actor_register_transient")
local actor_slot_offset = sd.debug.layout_offset("actor_slot")
local world_slot_offset = sd.debug.layout_offset("actor_world_slot")
local function read_x(actor)
  return actor ~= 0 and tonumber(sd.debug.read_float(actor + ox)) or 0
end
local function read_y(actor)
  return actor ~= 0 and tonumber(sd.debug.read_float(actor + oy)) or 0
end
local owner_actor = tonumber(player.actor_address) or 0
local bot_actor = tonumber(bot.actor_address) or 0
local enemy = nil
local original_live_count = 0
local original_network_live_count = 0
local original_set = {}
local original_network_set = {}
for _, address in ipairs(original_enemy_addresses) do
  original_set[address] = true
end
for _, network_id in ipairs(original_enemy_network_ids) do
  original_network_set[network_id] = true
end
for _, actor in ipairs(sd.world.list_actors() or {}) do
  if original_set[tonumber(actor.actor_address) or 0] and
      actor.tracked_enemy and not actor.dead and
      (tonumber(actor.hp) or 0) > 0 then
    original_live_count = original_live_count + 1
  end
  if tonumber(actor.actor_address) == enemy_address then
    enemy = actor
  end
end
local replicated = sd.world.get_replicated_actors() or {}
for _, actor in ipairs(replicated.actors or {}) do
  if original_network_set[tonumber(actor.network_actor_id) or 0] and
      actor.tracked_enemy and not actor.dead and
      (tonumber(actor.hp) or 0) > 0 then
    original_network_live_count = original_network_live_count + 1
  end
end
local target_actor = enemy_address ~= 0 and
  tonumber(sd.debug.read_ptr(enemy_address + target_offset)) or 0
local target_participant_id = 0
if target_actor == owner_actor and owner_actor ~= 0 then
  target_participant_id = __OWNER_PARTICIPANT_ID__
elseif target_actor == bot_actor and bot_actor ~= 0 then
  target_participant_id = bot_id
end
local combat = sd.gameplay.get_combat_state() or {}
local wave = sd.waves.get_state() or {}
emit("owner.actor", owner_actor)
emit("owner.x", read_x(owner_actor))
emit("owner.y", read_y(owner_actor))
emit("bot.actor", bot_actor)
emit("bot.x", read_x(bot_actor))
emit("bot.y", read_y(bot_actor))
emit("bot.cast_accepted", brain.cast_accepted or 0)
emit("bot.move_accepted", brain.move_accepted or 0)
emit("bot.mode", brain.mode or "")
emit("bot.live_enemy_count", brain.live_enemy_count or 0)
emit("bot.target_network_actor_id", brain.target_network_actor_id or 0)
emit("bot.target_distance", brain.target_distance or 0)
emit("enemy.found", enemy ~= nil)
emit("enemy.alive", enemy ~= nil and not enemy.dead and
  (tonumber(enemy.hp) or 0) > 0)
emit("enemy.hp", enemy and enemy.hp or 0)
emit("enemy.x", read_x(enemy_address))
emit("enemy.y", read_y(enemy_address))
emit("enemy.target_actor", target_actor)
emit("enemy.target_participant_id", target_participant_id)
emit("enemy.bucket_delta", enemy_address ~= 0 and
  sd.debug.read_i32(enemy_address + bucket_offset) or 0)
emit("enemy.selector_latch", enemy_address ~= 0 and
  sd.debug.read_u8(enemy_address + latch_offset) or 0)
emit("enemy.actor_group", enemy_address ~= 0 and
  sd.debug.read_i8(enemy_address + actor_slot_offset) or -1)
emit("enemy.world_slot", enemy_address ~= 0 and
  sd.debug.read_i16(enemy_address + world_slot_offset) or -1)
emit("original.live_count", original_live_count)
emit("original.network_live_count", original_network_live_count)
emit("combat.wave", combat.wave_index or 0)
emit("combat.active", combat.active or false)
emit("wave.phase", wave.phase or "")
emit("wave.alive", wave.alive or 0)
"""


ARRANGE_LUA = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local enemy_addresses = __ENEMY_ACTOR_ADDRESSES__
local enemy_address = enemy_addresses[1] or 0
local bot_id = __BOT_PARTICIPANT_ID__
local player = sd.player.get_state() or {}
local bot = bot_id ~= 0 and sd.bots.get_participant_state(bot_id) or {}
local owner_actor = tonumber(player.actor_address) or 0
local bot_actor = tonumber(bot.actor_address) or 0
local ox = sd.debug.layout_offset("actor_position_x")
local oy = sd.debug.layout_offset("actor_position_y")
local target_offset = sd.debug.layout_offset("actor_current_target_actor")
local bucket_offset =
  sd.debug.layout_offset("actor_current_target_bucket_delta")
local enemy_hp_offset = sd.debug.layout_offset("enemy_current_hp")
local enemy_max_hp_offset = sd.debug.layout_offset("enemy_max_hp")
local progression_offset =
  sd.debug.layout_offset("actor_progression_runtime_state")
local progression_hp_offset = sd.debug.layout_offset("progression_hp")
local progression_max_hp_offset =
  sd.debug.layout_offset("progression_max_hp")
local function move(actor, x, y)
  if actor == 0 then return false end
  local ok = sd.debug.write_float(actor + ox, x)
  ok = sd.debug.write_float(actor + oy, y) and ok
  if sd.world and sd.world.rebind_actor then
    ok = sd.world.rebind_actor(actor) and ok
  end
  return ok
end
local live_by_address = {}
local selected_x = 0.0
local selected_y = 0.0
for _, actor in ipairs(sd.world.list_actors() or {}) do
  if actor.tracked_enemy and not actor.dead and
      (tonumber(actor.hp) or 0) > 0 then
    local address = tonumber(actor.actor_address) or 0
    live_by_address[address] = true
  end
  if tonumber(actor.actor_address) == enemy_address then
    selected_x = tonumber(sd.debug.read_float(enemy_address + ox)) or 0.0
    selected_y = tonumber(sd.debug.read_float(enemy_address + oy)) or 0.0
  end
end
local ok = #enemy_addresses > 0
local owner_x = __OWNER_X__
local owner_y = __OWNER_Y__
local bot_x = __BOT_X__
local bot_y = __BOT_Y__
local function resolve_clear_destination(offset_x, offset_y)
  if not __REQUIRE_CLEAR_PATHS__ then
    return selected_x + offset_x, selected_y + offset_y, true
  end
  local radius = math.sqrt(offset_x * offset_x + offset_y * offset_y)
  local base_angle = math.atan(offset_y, offset_x)
  for index = 0, 23 do
    local angle = base_angle + index * math.pi / 12.0
    local candidate_x = selected_x + math.cos(angle) * radius
    local candidate_y = selected_y + math.sin(angle) * radius
    local call_ok, clear = pcall(
      sd.nav.test_segment,
      selected_x,
      selected_y,
      candidate_x,
      candidate_y)
    if call_ok and clear then
      return candidate_x, candidate_y, true
    end
  end
  return selected_x, selected_y, false
end
if __RELATIVE_LAYOUT__ then
  local owner_clear
  local bot_clear
  owner_x, owner_y, owner_clear =
    resolve_clear_destination(owner_x, owner_y)
  bot_x, bot_y, bot_clear =
    resolve_clear_destination(bot_x, bot_y)
  ok = owner_clear and bot_clear and ok
end
ok = move(owner_actor, owner_x, owner_y) and ok
if bot_actor ~= 0 then
  ok = move(bot_actor, bot_x, bot_y) and ok
elseif not __ALLOW_MISSING_BOT__ then
  ok = false
end
local entries = {}
for index, address in ipairs(enemy_addresses) do
  local x = tonumber(sd.debug.read_float(address + ox)) or 0.0
  local y = tonumber(sd.debug.read_float(address + oy)) or 0.0
  if not __PRESERVE_ENEMY_POSITIONS__ then
    x = selected_x + __ENEMY_X__
    y = selected_y + __ENEMY_Y__ + (index - 1) * __ENEMY_SPACING__
    if __PARK_OTHER_ENEMIES__ and index > 1 then
      x = 3300.0 + index * 20.0
      y = __ENEMY_Y__ + index * 20.0
    end
  end
  ok = live_by_address[address] == true and ok
  if not __PRESERVE_ENEMY_POSITIONS__ then
    ok = move(address, x, y) and ok
  end
  sd.debug.write_float(address + enemy_max_hp_offset, __ENEMY_HP__)
  sd.debug.write_float(address + enemy_hp_offset, __ENEMY_HP__)
  local progression =
    tonumber(sd.debug.read_ptr(address + progression_offset)) or 0
  if progression ~= 0 then
    sd.debug.write_float(
      progression + progression_max_hp_offset, __ENEMY_HP__)
    sd.debug.write_float(
      progression + progression_hp_offset, __ENEMY_HP__)
  end
  sd.debug.write_ptr(address + target_offset, 0)
  sd.debug.write_i32(address + bucket_offset, 0)
  entries[address] = {x = x, y = y}
end
_G.__botlevel_stationary_straggler = {
  enabled = true,
  entries = entries,
  bot_actor = __LOCK_BOT__ and bot_actor or 0,
  bot_x = bot_x,
  bot_y = bot_y,
}
if not _G.__botlevel_stationary_straggler_registered then
  sd.events.on("runtime.tick", function()
    local lock = _G.__botlevel_stationary_straggler
    if type(lock) ~= "table" or not lock.enabled then return end
    local live_count = 0
    for _, actor in ipairs(sd.world.list_actors() or {}) do
      local address = tonumber(actor.actor_address) or 0
      local entry = lock.entries[address]
      if entry and actor.tracked_enemy and not actor.dead and
          (tonumber(actor.hp) or 0) > 0 then
        live_count = live_count + 1
        sd.debug.write_float(address + ox, entry.x)
        sd.debug.write_float(address + oy, entry.y)
      end
    end
    if lock.bot_actor ~= 0 then
      sd.debug.write_float(lock.bot_actor + ox, lock.bot_x)
      sd.debug.write_float(lock.bot_actor + oy, lock.bot_y)
    end
    if live_count == 0 then
      lock.enabled = false
    end
  end)
  _G.__botlevel_stationary_straggler_registered = true
end
emit("ok", ok)
emit("owner_actor", owner_actor)
emit("bot_actor", bot_actor)
emit("enemy_actor", enemy_address)
emit("enemy_count", #enemy_addresses)
emit("enemy_hp", __ENEMY_HP__)
emit("stationary_lock", true)
emit("bot_lock", __LOCK_BOT__)
emit("preserved_native_enemy_positions", __PRESERVE_ENEMY_POSITIONS__)
"""


def _parse_scalar(value: str) -> Any:
    lowered = value.casefold()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        return int(value, 0)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def _parse_key_values(text: str) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = _parse_scalar(value.strip())
    return values


def _target_probe(
    pipe: LuaPipe,
    *,
    enemy_actor_addresses: list[int],
    enemy_network_actor_ids: list[int] | None = None,
    bot_id: int,
    owner_id: int,
) -> dict[str, Any]:
    if not enemy_actor_addresses:
        raise ValueError("target probe requires original enemy addresses")
    lua_addresses = "{" + ",".join(
        str(address) for address in enemy_actor_addresses
    ) + "}"
    lua_network_ids = "{" + ",".join(
        str(network_id) for network_id in (enemy_network_actor_ids or [])
    ) + "}"
    code = (
        TARGET_PROBE_LUA
        .replace("__ENEMY_ACTOR_ADDRESS__", str(enemy_actor_addresses[0]))
        .replace("__ENEMY_ACTOR_ADDRESSES__", lua_addresses)
        .replace("__ENEMY_NETWORK_ACTOR_IDS__", lua_network_ids)
        .replace("__BOT_PARTICIPANT_ID__", str(bot_id))
        .replace("__OWNER_PARTICIPANT_ID__", str(owner_id))
    )
    return _parse_key_values(pipe.execute(code))


def _arrange(
    pipe: LuaPipe,
    *,
    enemy_actor_addresses: list[int],
    bot_id: int,
    owner_x: float,
    owner_y: float,
    bot_x: float,
    bot_y: float,
    enemy_x: float,
    enemy_y: float,
    enemy_hp: float,
    enemy_spacing: float,
    park_other_enemies: bool,
    allow_missing_bot: bool,
    preserve_enemy_positions: bool,
    relative_layout: bool,
    require_clear_paths: bool,
    lock_bot: bool,
) -> dict[str, Any]:
    if not enemy_actor_addresses:
        raise ValueError("target layout requires original enemy addresses")
    lua_addresses = "{" + ",".join(
        str(address) for address in enemy_actor_addresses
    ) + "}"
    replacements = {
        "__ENEMY_ACTOR_ADDRESSES__": lua_addresses,
        "__BOT_PARTICIPANT_ID__": str(bot_id),
        "__OWNER_X__": f"{owner_x:.6f}",
        "__OWNER_Y__": f"{owner_y:.6f}",
        "__BOT_X__": f"{bot_x:.6f}",
        "__BOT_Y__": f"{bot_y:.6f}",
        "__ENEMY_X__": f"{enemy_x:.6f}",
        "__ENEMY_Y__": f"{enemy_y:.6f}",
        "__ENEMY_HP__": f"{enemy_hp:.6f}",
        "__ENEMY_SPACING__": f"{enemy_spacing:.6f}",
        "__PARK_OTHER_ENEMIES__": (
            "true" if park_other_enemies else "false"
        ),
        "__ALLOW_MISSING_BOT__": (
            "true" if allow_missing_bot else "false"
        ),
        "__PRESERVE_ENEMY_POSITIONS__": (
            "true" if preserve_enemy_positions else "false"
        ),
        "__RELATIVE_LAYOUT__": (
            "true" if relative_layout else "false"
        ),
        "__REQUIRE_CLEAR_PATHS__": (
            "true" if require_clear_paths else "false"
        ),
        "__LOCK_BOT__": "true" if lock_bot else "false",
    }
    code = ARRANGE_LUA
    for token, value in replacements.items():
        code = code.replace(token, value)
    values = _parse_key_values(pipe.execute(code))
    if values.get("ok") is not True:
        raise HostileTargetingContinuityFailure(
            f"could not arrange hostile-targeting layout: {values}"
        )
    return values


def _release_bot_lock(pipe: LuaPipe) -> dict[str, Any]:
    values = _parse_key_values(pipe.execute(r"""
local lock = rawget(_G, "__botlevel_stationary_straggler")
local released = type(lock) == "table" and lock.bot_actor ~= 0
if type(lock) == "table" then lock.bot_actor = 0 end
print("released=" .. tostring(released))
"""))
    if values.get("released") is not True:
        raise HostileTargetingContinuityFailure(
            f"stationary fixture bot lock was not active: {values}"
        )
    return values


def _distance(row: dict[str, Any], prefix: str) -> float:
    return math.hypot(
        float(row["enemy.x"]) - float(row[f"{prefix}.x"]),
        float(row["enemy.y"]) - float(row[f"{prefix}.y"]),
    )


def analyze_target_samples(
    samples: list[dict[str, Any]],
    *,
    bot_id: int,
) -> dict[str, Any]:
    live = [row for row in samples if row.get("enemy.alive") is True]
    nearest_bot = [
        row for row in live
        if _distance(row, "bot") + 0.001 < _distance(row, "owner")
    ]
    correctly_targeted = [
        row for row in nearest_bot
        if int(row.get("enemy.target_participant_id", 0)) == bot_id
    ]
    latch_clear = [
        row for row in live
        if int(row.get("enemy.selector_latch", -1)) == 0
    ]
    assessment = {
        "sampleCount": len(samples),
        "liveSampleCount": len(live),
        "nearestBotSampleCount": len(nearest_bot),
        "correctNearestTargetSampleCount": len(correctly_targeted),
        "selectorLatchClearSampleCount": len(latch_clear),
        "targetParticipantIds": sorted({
            int(row.get("enemy.target_participant_id", 0)) for row in live
        }),
    }
    if not (
        len(live) >= MINIMUM_TARGET_SAMPLES
        and len(nearest_bot) == len(live)
        and len(correctly_targeted) == len(live)
        and len(latch_clear) == len(live)
    ):
        raise HostileTargetingContinuityFailure(
            f"skeleton did not hold the sane nearest live target: {assessment}"
        )
    return assessment


def analyze_selector_log(
    text: str,
    *,
    hostile_actor_address: int,
    owner_actor_address: int,
    bot_actor_address: int,
) -> dict[str, Any]:
    hostile = (
        f"hostile=0x{hostile_actor_address:X}".casefold()
        if hostile_actor_address != 0 else ""
    )
    owner = f"previous_target=0x{owner_actor_address:X}".casefold()
    bot = f"target=0x{bot_actor_address:X}".casefold()
    native_lines = [
        line for line in text.splitlines()
        if "[hostile_ai] authoritative nearest target applied" in line
        and "reason=native_selector" in line
        and (not hostile or hostile in line.casefold())
    ]
    owner_to_bot = [
        line for line in native_lines
        if owner in line.casefold() and bot in line.casefold()
    ]
    return {
        "nativeSelectorApplyCount": len(native_lines),
        "stockOwnerToExtendedBotRewriteCount": len(owner_to_bot),
        "rejectedExtendedCandidateCount": text.count(
            "[hostile_ai] rejected extended target candidate"
        ),
        "ownerToBotExamples": owner_to_bot[:12],
    }


def analyze_wave_completion(
    samples: list[dict[str, Any]],
    *,
    starting_wave: int,
    bot_id: int,
    original_enemy_actor_addresses: list[int],
    original_enemy_network_ids: list[int] | None = None,
    damage_rows: list[dict[str, Any]],
    expect_stall: bool = False,
) -> dict[str, Any]:
    alive = [row for row in samples if row.get("enemy.alive") is True]
    initial = alive[0] if alive else samples[0] if samples else {}
    initial_distance = _distance(initial, "bot") if initial else 0.0
    owner_origin = (
        float(initial.get("owner.x", 0.0)),
        float(initial.get("owner.y", 0.0)),
    )
    enemy_origin = (
        float(initial.get("enemy.x", 0.0)),
        float(initial.get("enemy.y", 0.0)),
    )
    owner_displacement = max(
        (
            math.hypot(
                float(row.get("owner.x", 0.0)) - owner_origin[0],
                float(row.get("owner.y", 0.0)) - owner_origin[1],
            )
            for row in samples
        ),
        default=0.0,
    )
    enemy_displacement = max(
        (
            math.hypot(
                float(row.get("enemy.x", 0.0)) - enemy_origin[0],
                float(row.get("enemy.y", 0.0)) - enemy_origin[1],
            )
            for row in alive
        ),
        default=0.0,
    )
    final_wave = max(
        (int(row.get("combat.wave", 0)) for row in samples),
        default=0,
    )
    completed_phase_observed = any(
        str(row.get("wave.phase", "")).casefold() == "completed"
        for row in samples
    )
    bot_damage = [
        row for row in damage_rows
        if int(row.get("sourceParticipantId", 0)) == bot_id
        and float(row.get("damage", 0.0)) > 0.0
    ]
    original_enemy_set = set(original_enemy_actor_addresses)
    original_network_set = set(original_enemy_network_ids or [])
    if original_network_set:
        bot_damaged_original_enemies = sorted({
            int(row.get("targetNetworkActorId", 0))
            for row in bot_damage
            if int(row.get("targetNetworkActorId", 0)) in original_network_set
        })
        original_live_key = "original.network_live_count"
        original_enemy_count = len(original_network_set)
        identity_kind = "network_actor_id"
    else:
        bot_damaged_original_enemies = sorted({
            int(row.get("targetActorAddress", 0))
            for row in bot_damage
            if int(row.get("targetActorAddress", 0)) in original_enemy_set
        })
        original_live_key = "original.live_count"
        original_enemy_count = len(original_enemy_set)
        identity_kind = "actor_address"
    cast_delta = (
        int(samples[-1].get("bot.cast_accepted", 0))
        - int(samples[0].get("bot.cast_accepted", 0))
        if samples else 0
    )
    move_delta = (
        int(samples[-1].get("bot.move_accepted", 0))
        - int(samples[0].get("bot.move_accepted", 0))
        if samples else 0
    )
    original_live_at_start = int(
        initial.get("original.live_count", original_enemy_count)
    )
    phase_boundary_deaths = max(
        0,
        original_enemy_count - original_live_at_start,
    )
    accounted_original_enemies = min(
        original_enemy_count,
        len(bot_damaged_original_enemies) + phase_boundary_deaths,
    )
    assessment = {
        "startingWave": starting_wave,
        "finalWave": final_wave,
        "advanced": final_wave > starting_wave or completed_phase_observed,
        "completedPhaseObserved": completed_phase_observed,
        "initialBotDistance": initial_distance,
        "stationaryEnemyMaxDisplacement": enemy_displacement,
        "ownerMaxDisplacement": owner_displacement,
        "ownerSearchInputRequests": 0,
        "botDamageEdgeCount": len(bot_damage),
        "botCastAcceptedDelta": cast_delta,
        "botMoveAcceptedDelta": move_delta,
        "originalEnemyIdentityKind": identity_kind,
        "originalEnemyLiveAtEnd": bool(
            samples and int(samples[-1].get(original_live_key, 0)) > 0
        ),
        "originalEnemyCount": original_enemy_count,
        "botDamagedOriginalEnemyCount": len(bot_damaged_original_enemies),
        "botDamagedOriginalEnemyIdentities": bot_damaged_original_enemies,
        "phaseBoundaryOriginalDeathCount": phase_boundary_deaths,
        "accountedOriginalEnemyCount": accounted_original_enemies,
        "allOriginalEnemiesBotDamaged": (
            len(bot_damaged_original_enemies) == original_enemy_count
        ),
        "allOriginalEnemiesAccounted": (
            accounted_original_enemies == original_enemy_count
        ),
    }
    completed = (
        assessment["advanced"]
        and initial_distance >= MINIMUM_STRAGGLER_DISTANCE
        and enemy_displacement <= MAXIMUM_LOCKED_ENEMY_DISPLACEMENT
        and owner_displacement <= MAXIMUM_OWNER_DISPLACEMENT
        and len(bot_damage) >= 1
        and cast_delta >= 1
        and assessment["allOriginalEnemiesAccounted"]
    )
    stalled_under_active_bot = (
        not assessment["advanced"]
        and initial_distance >= MINIMUM_STRAGGLER_DISTANCE
        and owner_displacement <= MAXIMUM_OWNER_DISPLACEMENT
        and len(bot_damage) >= 1
        and cast_delta >= 1
        and assessment["originalEnemyLiveAtEnd"]
    )
    assessment["completedAutonomously"] = completed
    assessment["preFixStallReproduced"] = stalled_under_active_bot
    accepted = stalled_under_active_bot if expect_stall else completed
    if not accepted:
        raise HostileTargetingContinuityFailure(
            "stationary distant straggler outcome missed its expected state: "
            f"{assessment}"
        )
    return assessment


def _runtime_log_text(runtime_root: Path, instance: str) -> str:
    log_root = runtime_root / "instances" / instance / "stage" / ".sdmod" / "logs"
    chunks: list[str] = []
    if log_root.is_dir():
        for path in sorted(log_root.rglob("*")):
            if path.is_file():
                chunks.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(chunks)


def _prepare_single_skeleton_wave(
    evidence_root: Path,
    game_directory: Path,
) -> dict[str, Any]:
    return _materialize_native_wave_schedule(
        retail_wave_path=game_directory / "data" / "wave.txt",
        fixture_path=WAVE_FIXTURES["melee"],
        output_path=evidence_root / "inputs" / "single-skeleton-wave.txt",
        wave_delay_ticks=4096,
    )


def _find_live_enemy_addresses(state: dict[str, Any]) -> list[int]:
    enemies = state.get("nativeEnemies", [])
    live = [
        row for row in enemies
        if float(row.get("hp", 0.0)) > 0.0 and not row.get("dead", False)
    ]
    if not live:
        raise HostileTargetingContinuityFailure(
            "native wave did not materialize any live skeletons"
        )
    addresses = [int(
        row.get(
            "address",
            row.get("actorAddress", row.get("actor_address", 0)),
        )
    ) for row in live]
    if any(address == 0 for address in addresses):
        raise HostileTargetingContinuityFailure(
            f"native wave skeleton omitted its actor address: {live}"
        )
    return sorted(addresses)


_NETWORK_ASSIGNMENT = re.compile(
    r"assigned host-local run actor network id\. actor=0x([0-9a-f]+)"
    r".*?network_actor_id=(\d+)",
    re.IGNORECASE,
)
_SPAWN_ASSIGNMENT = re.compile(
    r"enemy\.spawned hook invoked\. enemy=0x([0-9a-f]+)"
    r"\s+spawn_serial=(\d+)",
    re.IGNORECASE,
)
_RUN_WORLD_ACTOR_NETWORK_ID_BASE = 0x1000000000000


def _enemy_network_ids_from_log(
    text: str,
    actor_addresses: list[int],
) -> list[int]:
    assignments: dict[int, int] = {}
    for line in text.splitlines():
        spawn = _SPAWN_ASSIGNMENT.search(line)
        if spawn is not None:
            assignments[int(spawn.group(1), 16)] = (
                _RUN_WORLD_ACTOR_NETWORK_ID_BASE | int(spawn.group(2))
            )
        host_local = _NETWORK_ASSIGNMENT.search(line)
        if host_local is not None:
            assignments[int(host_local.group(1), 16)] = int(
                host_local.group(2)
            )
    network_ids = [assignments.get(address, 0) for address in actor_addresses]
    if (
        any(network_id <= 0 for network_id in network_ids)
        or len(set(network_ids)) != len(actor_addresses)
    ):
        raise HostileTargetingContinuityFailure(
            "log did not capture one immutable network id per skeleton: "
            f"addresses={actor_addresses} network_ids={network_ids}"
        )
    return sorted(network_ids)


def _wait_enemy_network_ids_from_log(
    runtime_root: Path,
    instance: str,
    actor_addresses: list[int],
    timeout: float,
) -> list[int]:
    deadline = time.monotonic() + timeout
    last_error: HostileTargetingContinuityFailure | None = None
    while time.monotonic() < deadline:
        try:
            return _enemy_network_ids_from_log(
                _runtime_log_text(runtime_root, instance),
                actor_addresses,
            )
        except HostileTargetingContinuityFailure as exc:
            last_error = exc
            time.sleep(0.05)
    assert last_error is not None
    raise last_error


def _sample_targets(
    pipe: LuaPipe,
    *,
    enemy_actor_addresses: list[int],
    bot_id: int,
    owner_id: int,
    seconds: float,
) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        row = _target_probe(
            pipe,
            enemy_actor_addresses=enemy_actor_addresses,
            bot_id=bot_id,
            owner_id=owner_id,
        )
        row["utcNanoseconds"] = time.time_ns()
        samples.append(row)
        time.sleep(TARGET_SAMPLE_INTERVAL_SECONDS)
    return samples


def _run_live(args: argparse.Namespace, result: dict[str, Any]) -> None:
    ps = PowerShell(ROOT)
    ports = {args.local_port, args.unused_remote_port}
    result["udpExclusions"] = _udp_exclusion_inventory(ps, ports)
    assert_ports_free(ps, ports)
    write_json(
        args.evidence_root / "safety" / "before.json",
        {
            "utcNanoseconds": time.time_ns(),
            "reservedPorts": port_inventory(ps, ports),
            "processes": [asdict(row) for row in windows_processes(ps)],
        },
    )

    bundle_root = _stage_reproducer_package(
        args.package_root,
        args.evidence_root,
    )
    runtime_root = args.evidence_root / "staging" / "runtime"
    wave = _prepare_single_skeleton_wave(
        args.evidence_root,
        args.game_directory,
    )
    result["waveOverride"] = wave
    settings_path = _write_initial_settings(
        args.evidence_root,
        "skirmisher",
        BOT_PLAY_TEAM_ROSTER[:1],
    )
    ledger = args.evidence_root / "safety" / "process-ledger.json"
    expected_executable = windows_path(
        runtime_root / "instances" / args.instance / "stage" / "SolomonDark.exe"
    )
    process_id = 0
    primary_error: BaseException | None = None
    try:
        launch = _launch(
            bundle_root=bundle_root,
            runtime_root=runtime_root,
            game_directory=args.game_directory,
            settings_path=settings_path,
            evidence_root=args.evidence_root,
            instance=args.instance,
            local_port=args.local_port,
            unused_remote_port=args.unused_remote_port,
            element="air",
            discipline="mind",
            max_participants=2,
            participant_id=args.participant_id,
            test_wave_override=Path(wave["effective_path"]),
        )
        result["launch"] = launch
        if launch.get("audioDisabled") is not True:
            raise HostileTargetingContinuityFailure(
                "isolated launch did not disable audio"
            )
        process_id = int(launch["processId"])
        result["ownedProcess"] = _exact_process(
            ps, process_id, expected_executable
        )
        pipe = LuaPipe(ROOT, str(launch["luaPipe"]))
        result["hub"] = _wait_scene(pipe, "hub", 45.0)
        result["runSeed"] = _request_until_true(
            pipe,
            f"sd.rng.set_seed({args.run_seed}) == {args.run_seed}",
            timeout=10.0,
            label="deterministic run seed",
        )
        result["startRun"] = _request_until_true(
            pipe,
            "sd.hub.start_match()",
            timeout=30.0,
            label="stock hosted Start Match request",
        )
        result["runLoadingStarted"] = _wait_run_loading_started(pipe, 20.0)
        result["runMaterialized"] = _wait_scene(pipe, "testrun", 45.0)
        result["runReady"] = _wait_run_ready(pipe, 45.0)
        result["rosterRespawn"] = _respawn_bot_roster(pipe)
        prewave_ready = _wait_for(
            pipe,
            lambda row: (
                row["bot.count"] == 1
                and row["bot.participant_id"] > 0
                and row["bot.progression"] > 0
            ),
            timeout=30.0,
            label="one materialized pre-wave Lua teammate",
        )
        bot_id = int(prewave_ready["bot.participant_id"])
        result["prewaveBotReady"] = prewave_ready
        result["survivalProtection"] = _protect_participants(pipe, bot_id)
        result["manaPrime"] = _set_bot_mana(
            pipe,
            int(prewave_ready["bot.progression"]),
            1000.0,
            1000.0,
        )
        result["waveStart"] = _request_until_true(
            pipe,
            "sd.gameplay.start_waves()",
            timeout=20.0,
            label="native skeleton wave start",
        )
        live_wave = _wait_live_wave(pipe, 30.0)
        result["liveWave"] = live_wave
        enemy_actor_addresses = _find_live_enemy_addresses(live_wave)
        enemy_actor_address = enemy_actor_addresses[0]
        result["enemyActorAddresses"] = enemy_actor_addresses
        result["enemyPrime"] = _arrange(
            pipe,
            enemy_actor_addresses=enemy_actor_addresses,
            bot_id=bot_id,
            owner_x=750.0,
            owner_y=0.0,
            bot_x=50.0,
            bot_y=0.0,
            enemy_x=0.0,
            enemy_y=0.0,
            enemy_hp=STABILIZED_ENEMY_HP,
            enemy_spacing=0.0,
            park_other_enemies=False,
            allow_missing_bot=False,
            preserve_enemy_positions=True,
            relative_layout=True,
            require_clear_paths=True,
            lock_bot=False,
        )
        ready = _wait_for(
            pipe,
            lambda row: (
                row["bot.count"] == 1
                and row["bot.participant_id"] == bot_id
                and row["brain.active"]
                and row["brain.live_enemy_count"] > 0
            ),
            timeout=30.0,
            label="active Lua teammate and native skeleton wave",
        )
        result["botReady"] = ready
        result["nearestLayout"] = _arrange(
            pipe,
            enemy_actor_addresses=enemy_actor_addresses,
            bot_id=bot_id,
            owner_x=750.0,
            owner_y=0.0,
            bot_x=50.0,
            bot_y=0.0,
            enemy_x=0.0,
            enemy_y=0.0,
            enemy_hp=STABILIZED_ENEMY_HP,
            enemy_spacing=0.0,
            park_other_enemies=True,
            allow_missing_bot=False,
            preserve_enemy_positions=True,
            relative_layout=True,
            require_clear_paths=True,
            lock_bot=True,
        )
        first_target: dict[str, Any] = {}
        first_target_deadline = time.monotonic() + 10.0
        while time.monotonic() < first_target_deadline:
            first_target = _target_probe(
                pipe,
                enemy_actor_addresses=enemy_actor_addresses,
                bot_id=bot_id,
                owner_id=args.participant_id,
            )
            if first_target.get("enemy.target_participant_id") == bot_id:
                break
            time.sleep(0.1)
        else:
            raise HostileTargetingContinuityFailure(
                "skeleton never selected the nearer Lua participant: "
                f"{first_target}"
            )
        result["firstNearestTarget"] = first_target
        target_samples = _sample_targets(
            pipe,
            enemy_actor_addresses=enemy_actor_addresses,
            bot_id=bot_id,
            owner_id=args.participant_id,
            seconds=TARGET_SAMPLE_SECONDS,
        )
        result["targetSamples"] = target_samples
        result["nearestTargetAssessment"] = analyze_target_samples(
            target_samples,
            bot_id=bot_id,
        )

        first = target_samples[0]
        selector = analyze_selector_log(
            _runtime_log_text(runtime_root, args.instance),
            hostile_actor_address=enemy_actor_address,
            owner_actor_address=int(first["owner.actor"]),
            bot_actor_address=int(first["bot.actor"]),
        )
        result["selectorAssessment"] = selector
        result["selectorActors"] = {
            "hostile": enemy_actor_address,
            "owner": int(first["owner.actor"]),
            "bot": int(first["bot.actor"]),
        }
        enemy_network_actor_ids = _wait_enemy_network_ids_from_log(
            runtime_root,
            args.instance,
            enemy_actor_addresses,
            5.0,
        )
        result["stragglerEnemyNetworkActorIds"] = enemy_network_actor_ids

        result["damageResetBeforeStraggler"] = _reset_damage_observations(
            pipe,
            target_mod_id=BOT_MOD_ID,
        )
        straggler_layout = _arrange(
            pipe,
            enemy_actor_addresses=enemy_actor_addresses,
            bot_id=bot_id,
            owner_x=1000.0,
            owner_y=0.0,
            bot_x=500.0,
            bot_y=0.0,
            enemy_x=0.0,
            enemy_y=0.0,
            enemy_hp=STRAGGLER_ENEMY_HP,
            enemy_spacing=10.0,
            park_other_enemies=False,
            allow_missing_bot=False,
            preserve_enemy_positions=True,
            relative_layout=True,
            require_clear_paths=True,
            lock_bot=True,
        )
        result["stragglerLayout"] = straggler_layout
        enemy_rows: list[dict[str, Any]] = []
        player_rows: list[dict[str, Any]] = []
        first_wave_sample = _target_probe(
            pipe,
            enemy_actor_addresses=enemy_actor_addresses,
            enemy_network_actor_ids=enemy_network_actor_ids,
            bot_id=bot_id,
            owner_id=args.participant_id,
        )
        first_wave_sample["utcNanoseconds"] = time.time_ns()
        result["stragglerBotRelease"] = _release_bot_lock(pipe)
        starting_wave = int(first_wave_sample.get("combat.wave", 0))
        wave_samples: list[dict[str, Any]] = [first_wave_sample]
        deadline = time.monotonic() + args.wave_timeout
        while time.monotonic() < deadline:
            row = _target_probe(
                pipe,
                enemy_actor_addresses=enemy_actor_addresses,
                enemy_network_actor_ids=enemy_network_actor_ids,
                bot_id=bot_id,
                owner_id=args.participant_id,
            )
            row["utcNanoseconds"] = time.time_ns()
            wave_samples.append(row)
            _drain_damage_observations(
                pipe,
                enemy_rows,
                player_rows,
                target_mod_id=BOT_MOD_ID,
            )
            if (
                (
                    int(row.get("combat.wave", 0)) > starting_wave
                    or str(row.get("wave.phase", "")).casefold()
                    == "completed"
                )
                and int(row.get("original.network_live_count", -1)) == 0
            ):
                break
            time.sleep(0.2)
        result["stragglerSamples"] = wave_samples
        result["stragglerDamageRows"] = enemy_rows
        result["stragglerPlayerDamageRows"] = player_rows
        result["stragglerAssessment"] = analyze_wave_completion(
            wave_samples,
            starting_wave=starting_wave,
            bot_id=bot_id,
            original_enemy_actor_addresses=enemy_actor_addresses,
            original_enemy_network_ids=enemy_network_actor_ids,
            damage_rows=enemy_rows,
            expect_stall=args.expect == "churn",
        )
        result["finalBot"] = bot_probe(pipe)
        result["ok"] = True
    except BaseException as exc:
        primary_error = exc
        result["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
    finally:
        if process_id <= 0:
            process_id = _ledger_process_id(ledger)
        cleanup: dict[str, Any] = {}
        if process_id > 0:
            try:
                cleanup["processStop"] = _stop_exact_process(
                    ps, process_id, expected_executable
                )
            except BaseException as exc:
                cleanup["processStopError"] = f"{type(exc).__name__}: {exc}"
                result["ok"] = False
        try:
            cleanup["runtimeArtifacts"] = _copy_runtime_artifacts(
                runtime_root,
                args.instance,
                args.evidence_root,
            )
        except BaseException as exc:
            cleanup["artifactError"] = f"{type(exc).__name__}: {exc}"
            result["ok"] = False
        selector_actors = result.get("selectorActors")
        if isinstance(selector_actors, dict):
            selector = analyze_selector_log(
                _runtime_log_text(runtime_root, args.instance),
                hostile_actor_address=0,
                owner_actor_address=int(selector_actors["owner"]),
                bot_actor_address=int(selector_actors["bot"]),
            )
            result["selectorAssessment"] = selector
            selector_ok = (
                selector["stockOwnerToExtendedBotRewriteCount"] >= 1
                if args.expect == "churn"
                else (
                    selector["stockOwnerToExtendedBotRewriteCount"] == 0
                    and selector["rejectedExtendedCandidateCount"] == 0
                )
            )
            if not selector_ok:
                result["ok"] = False
                if primary_error is None:
                    result["error"] = {
                        "type": "HostileTargetingContinuityFailure",
                        "message": (
                            "selector log did not satisfy expected state "
                            f"{args.expect}: {selector}"
                        ),
                    }
        staging_root = args.evidence_root / "staging"
        if staging_root.is_dir():
            shutil.rmtree(staging_root)
            cleanup["stagingDeleted"] = str(staging_root)
        after_ports = port_inventory(ps, ports)
        after_process = (
            [asdict(row) for row in windows_processes(ps) if row.pid == process_id]
            if process_id > 0 else []
        )
        write_json(
            args.evidence_root / "safety" / "after.json",
            {
                "utcNanoseconds": time.time_ns(),
                "reservedPorts": after_ports,
                "ownedProcess": after_process,
            },
        )
        if after_ports or after_process:
            cleanup["residualPorts"] = after_ports
            cleanup["residualProcess"] = after_process
            result["ok"] = False
        result["cleanup"] = cleanup
        if primary_error is None and not result["ok"] and "error" not in result:
            result["error"] = {
                "type": "CleanupFailure",
                "message": "acceptance passed but exact cleanup failed",
            }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--game-directory", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--instance", default="botlevel-targeting")
    parser.add_argument("--local-port", type=int, default=52751)
    parser.add_argument("--unused-remote-port", type=int, default=52752)
    parser.add_argument(
        "--participant-id",
        type=lambda value: int(value, 0),
        default=76561198120430463,
    )
    parser.add_argument(
        "--run-seed", type=lambda value: int(value, 0), default=0xB071E7
    )
    parser.add_argument("--expect", choices=("churn", "stable"), required=True)
    parser.add_argument("--wave-timeout", type=float, default=45.0)
    args = parser.parse_args()
    args.package_root = args.package_root.resolve()
    args.game_directory = args.game_directory.resolve()
    args.evidence_root = args.evidence_root.resolve()
    if args.evidence_root.exists():
        parser.error("evidence root must be new")
    if not (args.package_root / "launcher" / "SolomonDarkModLauncher.exe").is_file():
        parser.error("package root is missing the desktop launcher")
    if not (args.game_directory / "SolomonDark.exe").is_file():
        parser.error("game directory is missing SolomonDark.exe")
    if not args.instance.startswith("botlevel-"):
        parser.error("instance must use botlevel- prefix")
    if (
        args.local_port == args.unused_remote_port
        or min(args.local_port, args.unused_remote_port) < 51400
    ):
        parser.error("ports must be distinct and at or above 51400")
    return args


def main() -> int:
    args = parse_args()
    actual_sha = _git_sha()
    if actual_sha != args.expected_source_sha.casefold():
        raise SystemExit(
            f"source SHA changed: expected={args.expected_source_sha} actual={actual_sha}"
        )
    args.evidence_root.mkdir(parents=True, exist_ok=False)
    result: dict[str, Any] = {
        "schemaVersion": 1,
        "ok": False,
        "sourceSha": actual_sha,
        "instance": args.instance,
        "ports": [args.local_port, args.unused_remote_port],
        "transportParticipantId": args.participant_id,
        "expectedSelectorState": args.expect,
        "audioDisabledRequired": True,
        "stationaryStraggler": True,
        "playerSearchInputAllowed": False,
    }
    _run_live(args, result)
    write_json(args.evidence_root / "result.json", result)
    write_manifest(args.evidence_root)
    print(json.dumps(
        {
            key: result.get(key)
            for key in (
                "ok",
                "error",
                "sourceSha",
                "instance",
                "ports",
                "ownedProcess",
                "nearestTargetAssessment",
                "selectorAssessment",
                "stragglerAssessment",
                "cleanup",
            )
        },
        indent=2,
        sort_keys=True,
    ))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
