#!/usr/bin/env python3
"""Live policy-v2 contract, targeting, weld, ally, and pickup verifier."""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
from pathlib import Path
import sys
import time

from ml_bot.bridge import (
    DEFAULT_GAME_DIRECTORY,
    DEFAULT_LAUNCHER,
    BridgeError,
    SoloSession,
)
from ml_bot import spec
from ml_bot.compositions import TeamComposition
from ml_bot.model import BotPolicy, load_model
import verify_local_multiplayer_sync as local_sync


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = ROOT / "models" / "bot-brain" / "policy-v2.json"
MINIMUM_LIVE_DISPLACEMENT = 1.0
PICKUP_AMOUNT = 7
NAV_CLEARANCE_RAY_RANGE = 480.0


POLICY_TELEMETRY = r"""
local root = rawget(_G, 'bot_brain_debug') or {}
local debug = (root.bots or {})[1] or {}
local function bits(values)
  local result = {}
  for index, value in ipairs(values or {}) do
    result[index] = value and '1' or '0'
  end
  return table.concat(result)
end
local function finite(value)
  return type(value) == 'number' and
    value == value and
    value ~= math.huge and value ~= -math.huge
end
local observation_finite = true
local observations = {}
for index, value in ipairs(debug.policy_observation or {}) do
  observation_finite = observation_finite and finite(value)
  observations[index] = string.format('%.17g', value)
end

local movement_mismatches = 0
local origin_x = tonumber(debug.policy_bot_x) or 0
local origin_y = tonumber(debug.policy_bot_y) or 0
for index, target in ipairs(
    debug.policy_movement_targets or {}) do
  local expected = true
  if index > 1 then
    local ok, traversable = pcall(
      sd.nav.test_segment,
      origin_x,
      origin_y,
      tonumber(target.x) or origin_x,
      tonumber(target.y) or origin_y)
    expected = ok and traversable == true
  end
  if (debug.policy_movement_mask or {})[index] ~= expected then
    movement_mismatches = movement_mismatches + 1
  end
end

local target_mismatches = 0
local enemy_ids = debug.enemy_slot_actor_ids or {}
local target_mask = debug.policy_target_mask or {}
local has_enemy = #enemy_ids > 0
local expected_keep =
  (tonumber(debug.policy_capture_target_id) or 0) > 0 or
  not has_enemy
if target_mask[1] ~= expected_keep then
  target_mismatches = target_mismatches + 1
end
for slot = 1, 8 do
  local expected = (tonumber(enemy_ids[slot]) or 0) > 0
  if target_mask[slot + 1] ~= expected then
    target_mismatches = target_mismatches + 1
  end
end

local cast_mismatches = 0
local cast_mask = debug.policy_cast_mask or {}
local loadout = debug.policy_loadout or {}
local snapshot = debug.policy_snapshot or {}
local target = debug.policy_selected_target
local common =
  type(target) == 'table' and
  snapshot.cast_ready == true and
  snapshot.cast_active ~= true and
  snapshot.cast_pending ~= true
local function range_ok(spell)
  if spell.range_resolved ~= true then return true end
  if type(target) ~= 'table' then return false end
  local dx = (tonumber(target.x) or 0) - origin_x
  local dy = (tonumber(target.y) or 0) - origin_y
  local contact = math.max(
    math.sqrt(dx * dx + dy * dy) -
      math.max(tonumber(target.radius) or 0, 0),
    0)
  return
    contact >= math.max(tonumber(spell.range_min) or 0, 0) and
    contact <= math.max(tonumber(spell.range_max) or 0, 0)
end
if cast_mask[1] ~= true then
  cast_mismatches = cast_mismatches + 1
end
local primary = loadout.primary or {}
local expected_primary =
  common and primary.occupied == true and
  primary.affordable == true and range_ok(primary)
if cast_mask[2] ~= expected_primary then
  cast_mismatches = cast_mismatches + 1
end
for slot = 1, 8 do
  local secondary = (loadout.secondaries or {})[slot] or {}
  local expected =
    common and secondary.occupied == true and
    secondary.affordable == true and
    secondary.ready == true and range_ok(secondary)
  if cast_mask[slot + 2] ~= expected then
    cast_mismatches = cast_mismatches + 1
  end
end

local participant_id = tonumber(debug.participant_id) or 0
local gold = 0
for _, participant in ipairs(
    (sd.runtime.get_multiplayer_state() or {}).participants or {}) do
  if tonumber(participant.participant_id) == participant_id then
    gold = tonumber(
      (participant.owned_progression or {}).gold) or 0
    break
  end
end
local loot = sd.world.get_replicated_loot() or {}
local pickup = loot.last_pickup_result or {}
local drop_count = 0
for _, drop in ipairs(loot.drops or {}) do
  if drop.active == true then drop_count = drop_count + 1 end
end
local details =
  sd.bots.get_loadout_details(participant_id) or {}
local first_secondary_slot = 0
for _, secondary in ipairs(details.secondaries or {}) do
  if first_secondary_slot == 0 and
      (tonumber(secondary.entry_id) or -1) >= 0 and
      secondary.mana_cost_resolved == true then
    first_secondary_slot = tonumber(secondary.slot) or 0
  end
end
print('observation_version=' ..
  tostring(debug.policy_observation_version or 0))
print('observation_count=' ..
  tostring(#(debug.policy_observation or {})))
print('observation_finite=' .. tostring(observation_finite))
print('observation=' .. table.concat(observations, ','))
print('movement_mask=' .. bits(debug.policy_movement_mask))
print('target_mask=' .. bits(target_mask))
print('cast_mask=' .. bits(cast_mask))
print('movement_mask_mismatches=' ..
  tostring(movement_mismatches))
print('target_mask_mismatches=' ..
  tostring(target_mismatches))
print('cast_mask_mismatches=' ..
  tostring(cast_mismatches))
print('selected_actions_legal=' ..
  tostring(debug.policy_selected_actions_legal == true))
print('participant_id=' ..
  tostring(participant_id))
print('target_network_actor_id=' ..
  tostring(tonumber(debug.target_network_actor_id) or 0))
print('target_contact_distance=' ..
  string.format(
    '%.17g',
    tonumber(
      type(target) == 'table' and
        target.contact_distance or 0) or 0))
print('target_in_primary_range=' ..
  tostring(
    type(target) == 'table' and
      target.in_primary_range == true))
print('current_target_slot=' ..
  tostring(debug.current_target_slot or 0))
print('enemy_slot_actor_ids=' ..
  table.concat(enemy_ids, ','))
print('primary_welded=' ..
  tostring(debug.primary_welded == true))
print('primary_build_id=' ..
  tostring(debug.primary_build_id or 0))
print('primary_range_max=' ..
  string.format('%.17g',
    tonumber(debug.primary_range_max) or 0))
print('first_secondary_slot=' ..
  tostring(first_secondary_slot))
print('pickup_observation_count=' ..
  tostring(debug.pickup_observation_count or 0))
print('pickup_observation_first_id=' ..
  tostring(tonumber(debug.pickup_observation_first_id) or 0))
print('pickup_range=' ..
  string.format('%.17g',
    tonumber(debug.pickup_range) or 0))
print('pickup_distance=' ..
  string.format('%.17g',
    tonumber(debug.pickup_distance) or 0))
print('loot_authority_participant_id=' ..
  tostring(debug.loot_authority_participant_id or 0))
print('pickup_request_issued=' ..
  tostring(debug.pickup_request_issued or 0))
print('pickup_request_accepted=' ..
  tostring(debug.pickup_request_accepted or 0))
print('last_pickup_error=' ..
  tostring(debug.last_pickup_error or ''))
print('last_pickup_network_drop_id=' ..
  tostring(tonumber(debug.last_pickup_network_drop_id) or 0))
print('last_pickup_request_distance=' ..
  string.format('%.17g',
    tonumber(debug.last_pickup_request_distance) or 0))
print('last_pickup_request_x=' ..
  string.format('%.17g',
    tonumber(debug.last_pickup_request_x) or 0))
print('last_pickup_request_y=' ..
  string.format('%.17g',
    tonumber(debug.last_pickup_request_y) or 0))
print('ally_observation_count=' ..
  tostring(debug.ally_observation_count or 0))
print('secondary_beyond_primary_accepted=' ..
  tostring(debug.secondary_beyond_primary_accepted or 0))
print('gold=' .. tostring(gold))
print('active_drop_count=' .. tostring(drop_count))
print('pickup_result=' .. tostring(pickup.result or ''))
print('pickup_result_participant_id=' ..
  tostring(tonumber(pickup.participant_id) or 0))
print('pickup_result_network_drop_id=' ..
  tostring(tonumber(pickup.network_drop_id) or 0))
print('pickup_result_amount=' ..
  tostring(pickup.amount or 0))
print('pickup_result_gold_revision=' ..
  tostring(pickup.gold_revision or 0))
print('policy_generation=' ..
  tostring(debug.policy_generation or 0))
print('policy_movement_action=' ..
  tostring(debug.policy_movement_action or 0))
print('policy_movement_name=' ..
  tostring(debug.policy_movement_name or ''))
print('policy_target_action=' ..
  tostring(debug.policy_target_action or 0))
print('policy_target_name=' ..
  tostring(debug.policy_target_name or ''))
print('policy_cast_action=' ..
  tostring(debug.policy_cast_action or 0))
print('policy_cast_name=' ..
  tostring(debug.policy_cast_name or ''))
print('cast_issued=' .. tostring(debug.cast_issued or 0))
print('cast_accepted=' .. tostring(debug.cast_accepted or 0))
print('last_error=' .. tostring(debug.last_error or ''))
"""

GAMEPLAY_STATUS = r"""
local debug = rawget(_G, 'bot_brain_debug') or {}
local handles = sd.bots.list()
local bot = handles[1]
local bot_x, bot_y = 0, 0
if bot ~= nil then
  local ok, x, y = pcall(function()
    return bot:position()
  end)
  if ok then
    bot_x = tonumber(x) or 0
    bot_y = tonumber(y) or 0
  end
end
local minimum_enemy_hp_ratio = 1.0
local damaged_enemy_count = 0
for _, actor in ipairs(sd.world.list_actors() or {}) do
  local hp = tonumber(actor.hp) or 0
  local max_hp = tonumber(actor.max_hp) or 0
  if actor.tracked_enemy == true and max_hp > 0 and hp > 0 then
    local ratio = math.max(0, math.min(1, hp / max_hp))
    minimum_enemy_hp_ratio =
      math.min(minimum_enemy_hp_ratio, ratio)
    if ratio < 0.999 then
      damaged_enemy_count = damaged_enemy_count + 1
    end
  end
end
local wave = sd.waves.get_state() or {}
print('bot_x=' .. string.format('%.17g', bot_x))
print('bot_y=' .. string.format('%.17g', bot_y))
print('wave=' .. tostring(wave.wave or 0))
print('wave_alive=' .. tostring(wave.alive or 0))
print('wave_killed=' .. tostring(wave.killed or 0))
print('damaged_enemy_count=' .. tostring(damaged_enemy_count))
print('minimum_enemy_hp_ratio=' ..
  string.format('%.17g', minimum_enemy_hp_ratio))
print('policy_movement_name=' ..
  tostring(debug.policy_movement_name or ''))
print('policy_cast_name=' ..
  tostring(debug.policy_cast_name or ''))
"""


def _integer(values: dict[str, str], key: str) -> int:
    try:
        return int(values.get(key, "0"))
    except ValueError as error:
        raise BridgeError(f"invalid integer {key}: {values.get(key)!r}") from error


def _finite(values: dict[str, str], key: str) -> float:
    try:
        value = float(values.get(key, "nan"))
    except ValueError as error:
        raise BridgeError(f"invalid number {key}: {values.get(key)!r}") from error
    if not math.isfinite(value):
        raise BridgeError(f"non-finite number {key}: {value}")
    return value


def _forced_policy(
    source: BotPolicy,
    *,
    movement_action: int,
    target_action: int,
    cast_action: int,
) -> BotPolicy:
    policy = BotPolicy.from_dict(copy.deepcopy(source.to_dict()))
    for weight in (
        policy.movement_weight,
        policy.target_weight,
        policy.cast_weight,
    ):
        weight.fill(0.0)
    for bias, action in (
        (policy.movement_bias, movement_action),
        (policy.target_bias, target_action),
        (policy.cast_bias, cast_action),
    ):
        bias.fill(-10.0)
        bias[action] = 10.0
    if target_action != 0:
        policy.target_bias[0] = 9.0
    return policy


def _telemetry(session: SoloSession) -> dict[str, str]:
    return local_sync.parse_key_values(
        session.lua(POLICY_TELEMETRY, timeout=15.0)
    )


def _wait_for(
    session: SoloSession,
    predicate,
    *,
    timeout: float,
    label: str,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = _telemetry(session)
        if predicate(last):
            return last
        time.sleep(0.05)
    raise BridgeError(f"{label} timed out: {last}")


def _observation(values: dict[str, str]) -> list[float]:
    try:
        observation = [
            float(value)
            for value in values.get("observation", "").split(",")
            if value
        ]
    except ValueError as error:
        raise BridgeError("live observation contains invalid text") from error
    if len(observation) != len(spec.OBSERVATION_NAMES):
        raise BridgeError(
            f"live observation has {len(observation)} values"
        )
    if not all(math.isfinite(value) for value in observation):
        raise BridgeError("live observation contains a non-finite value")
    return observation


def _validate_contract(values: dict[str, str]) -> list[float]:
    observation = _observation(values)
    if (
        _integer(values, "observation_version")
        != spec.OBSERVATION_VERSION
        or _integer(values, "observation_count")
        != len(spec.OBSERVATION_NAMES)
        or values.get("observation_finite") != "true"
    ):
        raise BridgeError(f"live observation contract failed: {values}")
    for key, expected in (
        ("movement_mask", len(spec.MOVEMENT_ACTION_NAMES)),
        ("target_mask", len(spec.TARGET_ACTION_NAMES)),
        ("cast_mask", len(spec.CAST_ACTION_NAMES)),
    ):
        mask = values.get(key, "")
        if len(mask) != expected or any(bit not in "01" for bit in mask):
            raise BridgeError(f"invalid live {key}: {mask!r}")
    if (
        values.get("selected_actions_legal") != "true"
        or _integer(values, "movement_mask_mismatches") != 0
        or _integer(values, "target_mask_mismatches") != 0
        or _integer(values, "cast_mask_mismatches") != 0
    ):
        raise BridgeError(f"live mask contract failed: {values}")

    indexes = {
        name: index
        for index, name in enumerate(spec.OBSERVATION_NAMES)
    }
    clearance = [
        observation[indexes[f"clearance_{direction}_scaled"]]
        for direction in (
            "east",
            "southeast",
            "south",
            "southwest",
            "west",
            "northwest",
            "north",
            "northeast",
        )
    ]
    patch = [
        observation[index]
        for name, index in indexes.items()
        if name.startswith("walkability_patch_")
    ]
    if (
        len(patch) != 48
        or any(value not in (0.0, 1.0) for value in patch)
        or any(value < 0.0 or value > 1.0 for value in clearance)
    ):
        raise BridgeError(
            "live navigation observation is outside its contract"
        )
    return observation


def _apply_one_weld(
    session: SoloSession,
    participant_id: int,
    *,
    max_rolls: int = 64,
) -> dict[str, str]:
    values = local_sync.parse_key_values(
        session.lua(
            f"""
local participant_id = {participant_id}
local max_rolls = {max_rolls}
local captured_build = 0
local captured_generation = 0
local roll_count = 0
local applied = false
local elemental_primary = {{
  [8] = true, [16] = true, [24] = true,
  [32] = true, [40] = true,
}}
local state = sd.bots.get_state(participant_id) or {{}}
local progression =
  tonumber(state.progression_runtime_state_address) or 0
local details =
  sd.bots.get_loadout_details(participant_id) or {{}}
local current_primary =
  tonumber((details.primary or {{}}).entry_id) or -1
local second_primary = current_primary == 8 and 16 or 8
local table_base_offset = assert(
  sd.debug.layout_offset(
    'standalone_wizard_progression_table_base'))
local table_count_offset = assert(
  sd.debug.layout_offset(
    'standalone_wizard_progression_table_count'))
local table_stride = assert(
  sd.debug.layout_offset(
    'standalone_wizard_progression_entry_stride'))
local active_offset = assert(
  sd.debug.layout_offset(
    'standalone_wizard_progression_active_flag'))
local effective_offset = assert(
  sd.debug.layout_offset(
    'standalone_wizard_progression_entry_effective_rank'))
local table_address = progression > 0 and
  (tonumber(sd.debug.read_ptr(
    progression + table_base_offset)) or 0) or 0
local table_count = progression > 0 and
  (tonumber(sd.debug.read_i32(
    progression + table_count_offset)) or 0) or 0
local prerequisite_writes_ok =
  current_primary >= 0 and
  second_primary >= 0 and
  current_primary < table_count and
  second_primary < table_count and
  table_address > 0 and table_stride > 0
if prerequisite_writes_ok then
  for _, entry_id in ipairs({{
      current_primary,
      second_primary,
    }}) do
    local row = table_address + entry_id * table_stride
    prerequisite_writes_ok =
      sd.debug.write_u16(row + active_offset, 1) and
      sd.debug.write_u16(row + effective_offset, 1) and
      prerequisite_writes_ok
  end
end
for roll = 1, max_rolls do
  local state = sd.bots.get_state(participant_id) or {{}}
  local progression =
    tonumber(state.progression_runtime_state_address) or 0
  local level_offset = assert(
    sd.debug.layout_offset('progression_level'))
  local next_xp_offset = assert(
    sd.debug.layout_offset(
      'progression_next_xp_threshold'))
  local level = progression > 0 and
    (tonumber(sd.debug.read_i32(
      progression + level_offset)) or 1) or 1
  local next_xp = progression > 0 and
    (tonumber(sd.debug.read_float(
      progression + next_xp_offset)) or 90) or 90
  local sync_ok = sd.bots.debug_sync_level_up({{
    level = level + 1,
    experience = math.ceil(next_xp + 10),
  }})
  if sync_ok ~= true then break end
  local choices =
    sd.bots.get_skill_choices(participant_id) or {{}}
  local details =
    sd.bots.get_loadout_details(participant_id) or {{}}
  roll_count = roll
  local weld_index = nil
  local fallback_index = nil
  local primary_index = nil
  for index, option in ipairs(choices.options or {{}}) do
    local option_id = tonumber(option.id) or -1
    if option_id == 52 then
      weld_index = index
    elseif elemental_primary[option_id] == true then
      primary_index = primary_index or index
    else
      fallback_index = fallback_index or index
    end
  end
  if weld_index ~= nil and
      details.pending_weld_build_id_resolved == true then
    captured_build =
      tonumber(details.pending_weld_build_id) or 0
    captured_generation =
      tonumber(choices.generation) or 0
    local ok, accepted = pcall(
      sd.bots.choose_skill,
      participant_id,
      weld_index,
      captured_generation)
    applied = ok and accepted == true
    break
  end
  local selected = primary_index or fallback_index
  if selected ~= nil then
    sd.bots.choose_skill(
      participant_id,
      selected,
      tonumber(choices.generation) or 0)
  end
end
local details =
  sd.bots.get_loadout_details(participant_id) or {{}}
local primary = details.primary or {{}}
print('applied=' .. tostring(applied))
print('roll_count=' .. tostring(roll_count))
print('captured_build_id=' .. tostring(captured_build))
print('captured_generation=' ..
  tostring(captured_generation))
print('active_build_id=' ..
  tostring(primary.build_id or 0))
print('active_build_resolved=' ..
  tostring(primary.build_id_resolved == true))
print('prerequisite_writes_ok=' ..
  tostring(prerequisite_writes_ok))
print('current_primary=' .. tostring(current_primary))
print('second_primary=' .. tostring(second_primary))
print('table_count=' .. tostring(table_count))
""",
            timeout=30.0,
        )
    )
    if (
        values.get("applied") != "true"
        or values.get("prerequisite_writes_ok") != "true"
        or values.get("active_build_resolved") != "true"
        or _integer(values, "captured_build_id") < 1000
        or _integer(values, "active_build_id")
        != _integer(values, "captured_build_id")
    ):
        raise BridgeError(f"live weld activation failed: {values}")
    return values


def _spawn_enemy(
    session: SoloSession,
    *,
    offset_x: float,
    hp: float = 750.0,
    freeze_on_spawn: bool = True,
) -> int:
    values = local_sync.parse_key_values(
        session.lua(
            f"""
local bot = (sd.bots.list() or {{}})[1]
local x, y = bot:position()
local ok, error_message, request_id =
  sd.gameplay.spawn_manual_run_enemy({{
    type_id = 1001,
    x = x + {offset_x:.17g},
    y = y,
    freeze_on_spawn = {str(freeze_on_spawn).lower()},
    allow_direct_arena_spawn = true,
  }})
print('ok=' .. tostring(ok))
print('error=' .. tostring(error_message or ''))
print('request_id=' .. tostring(request_id or 0))
""",
            timeout=10.0,
        )
    )
    request_id = _integer(values, "request_id")
    if values.get("ok") != "true" or request_id <= 0:
        raise BridgeError(f"manual enemy request failed: {values}")
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        result = local_sync.parse_key_values(
            session.lua(
                f"""
local result =
  sd.gameplay.get_last_manual_run_enemy_spawn(
    {request_id}) or {{}}
if result.ok == true and
    (tonumber(result.actor_address) or 0) > 0 then
  sd.gameplay.set_run_enemy_health(
    result.actor_address,
    {hp:.17g},
    {hp:.17g})
end
print('available=' .. tostring(next(result) ~= nil))
print('ok=' .. tostring(result.ok == true))
print('actor_address=' ..
  tostring(result.actor_address or 0))
""",
                timeout=10.0,
            )
        )
        if result.get("available") == "true":
            if (
                result.get("ok") != "true"
                or _integer(result, "actor_address") <= 0
            ):
                raise BridgeError(
                    f"manual enemy materialization failed: {result}"
                )
            return _integer(result, "actor_address")
        time.sleep(0.05)
    raise BridgeError("manual enemy materialization timed out")


def _spawn_gold_ahead(
    session: SoloSession,
    *,
    amount: int,
    distance: float,
    direction_x: float,
    direction_y: float,
) -> dict[str, float | int]:
    before = _telemetry(session)
    before_ids = {
        int(value)
        for value in local_sync.parse_key_values(
            session.lua(
                """
local loot = sd.world.get_replicated_loot() or {}
for index, drop in ipairs(loot.drops or {}) do
  if drop.active == true then
    print('drop.' .. tostring(index) .. '=' ..
      tostring(drop.network_drop_id))
  end
end
"""
            )
        ).values()
    }
    values = local_sync.parse_key_values(
        session.lua(
            f"""
local bot = (sd.bots.list() or {{}})[1]
local x, y = bot:position()
local spawn_x = x + {direction_x:.17g} * {distance:.17g}
local spawn_y = y + {direction_y:.17g} * {distance:.17g}
local ok, error_message = sd.world.spawn_reward({{
  kind='gold',
  amount={amount},
  x=spawn_x,
  y=spawn_y,
}})
print('ok=' .. tostring(ok))
print('error=' .. tostring(error_message or ''))
print('spawn_x=' .. string.format('%.17g', spawn_x))
print('spawn_y=' .. string.format('%.17g', spawn_y))
""",
            timeout=10.0,
        )
    )
    if values.get("ok") != "true":
        raise BridgeError(f"gold spawn request failed: {values}")
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        rows = local_sync.parse_key_values(
            session.lua(
                """
local loot = sd.world.get_replicated_loot() or {}
for index, drop in ipairs(loot.drops or {}) do
  if drop.active == true and drop.kind == 'Gold' then
    print('drop.' .. tostring(index) .. '=' ..
      tostring(drop.network_drop_id))
  end
end
"""
            )
        )
        new_ids = {
            int(value)
            for value in rows.values()
            if int(value) not in before_ids
        }
        if new_ids:
            return {
                "network_drop_id": min(new_ids),
                "gold_before": _integer(before, "gold"),
                "spawn_x": _finite(values, "spawn_x"),
                "spawn_y": _finite(values, "spawn_y"),
            }
        time.sleep(0.05)
    raise BridgeError("spawned gold did not enter the loot snapshot")


def _clearest_pickup_direction(
    values: dict[str, str],
    *,
    required_distance: float,
) -> tuple[int, float, float, float]:
    observation = _observation(values)
    indexes = {
        name: index
        for index, name in enumerate(spec.OBSERVATION_NAMES)
    }
    candidates = []
    for action, name in enumerate(
        spec.MOVEMENT_ACTION_NAMES[1:],
        start=1,
    ):
        clearance = (
            observation[indexes[f"clearance_{name}_scaled"]]
            * NAV_CLEARANCE_RAY_RANGE
        )
        direction_x, direction_y = spec.MOVEMENT_DIRECTIONS[action]
        candidates.append(
            (clearance, action, direction_x, direction_y)
        )
    clearance, action, direction_x, direction_y = max(candidates)
    if clearance < required_distance:
        raise BridgeError(
            "no navigation ray has enough clearance for the pickup "
            f"approach: required={required_distance}, available={clearance}"
        )
    return action, direction_x, direction_y, clearance


def _verify_offline_solo_ally_zero(
    args: argparse.Namespace,
    policy: BotPolicy,
    instance: str,
) -> dict[str, object]:
    solo = TeamComposition("solo-live", 1, ())
    session = SoloSession(
        instance=f"{instance[:40]}-solo",
        game_directory=Path(args.game_directory),
        launcher_path=Path(args.launcher_path),
        runtime_root=Path(args.runtime_root),
        local_port=args.local_port + 20,
        unused_remote_port=args.unused_remote_port + 20,
        max_participants=solo.participant_count + 1,
        headless=not args.visible,
        element=args.element,
        discipline=args.discipline,
        multiplayer_transport=False,
    )
    try:
        launch = session.launch()
        session.wait_for_pipe(timeout=args.startup_timeout)
        session.drive_new_game_to_hub(timeout=args.startup_timeout)
        session.write_empty_roster()
        session.wait_for_empty_roster(timeout=args.startup_timeout)
        session.load_policy(
            _forced_policy(
                policy,
                movement_action=0,
                target_action=0,
                cast_action=0,
            )
        )
        seed_round_trip = session.set_run_seed(args.seed)
        session.enable_god_mode()
        session.start_test_run(timeout=args.startup_timeout)
        session.prepare_training_combat(
            timeout=args.startup_timeout
        )
        session.write_composition(solo)
        session.wait_for_composition(
            expected_bot_count=1,
            expected_learned_count=1,
            timeout=args.startup_timeout,
        )
        session.wait_for_run_ready(
            expected_bot_count=1,
            expected_learned_count=1,
            timeout=args.startup_timeout,
        )
        session.wait_for_bot_materialized(
            expected_bot_count=1,
            expected_learned_count=1,
            timeout=args.startup_timeout,
        )
        values = _wait_for(
            session,
            lambda value: (
                _integer(value, "observation_count") == 395
                and _integer(
                    value,
                    "ally_observation_count",
                )
                == 0
            ),
            timeout=args.timeout,
            label="offline solo zeroed ally observation",
        )
        observation = _validate_contract(values)
        ally_indexes = [
            index
            for index, name in enumerate(spec.OBSERVATION_NAMES)
            if name.startswith("ally_")
        ]
        if any(observation[index] != 0.0 for index in ally_indexes):
            raise BridgeError(
                "offline solo observation did not zero every ally value"
            )
        return {
            "instance": session.instance,
            "process_id": launch.get("processId"),
            "seed_round_trip": seed_round_trip,
            "layout_sha256": session.layout_sha256(),
            "ally_count": 0,
            "observation_count": len(observation),
        }
    finally:
        session.close()


def verify(args: argparse.Namespace) -> dict[str, object]:
    policy = load_model(Path(args.model))
    instance = args.instance or f"ml-live-{os.getpid()}"
    offline_solo = _verify_offline_solo_ally_zero(
        args,
        policy,
        instance,
    )
    solo = TeamComposition("solo-live", 1, ())
    team = TeamComposition(
        "live-mixed",
        1,
        ("guardian",),
    )
    session = SoloSession(
        instance=instance,
        game_directory=Path(args.game_directory),
        launcher_path=Path(args.launcher_path),
        runtime_root=Path(args.runtime_root),
        local_port=args.local_port,
        unused_remote_port=args.unused_remote_port,
        max_participants=max(
            solo.participant_count,
            team.participant_count,
        ) + 1,
        headless=not args.visible,
        element=args.element,
        discipline=args.discipline,
        multiplayer_transport=True,
        weld_preference="avoid",
    )
    launch: dict[str, object] | None = None
    started_at = time.monotonic()
    try:
        launch = session.launch()
        session.wait_for_pipe(timeout=args.startup_timeout)
        session.drive_new_game_to_hub(timeout=args.startup_timeout)
        session.write_empty_roster()
        session.wait_for_empty_roster(timeout=args.startup_timeout)
        setup_policy = _forced_policy(
            policy,
            movement_action=0,
            target_action=1,
            cast_action=0,
        )
        generation = session.load_policy(setup_policy)
        seed_round_trip = session.set_run_seed(args.seed)
        session.enable_god_mode()
        session.start_test_run(timeout=args.startup_timeout)
        session.prepare_training_combat(
            timeout=args.startup_timeout
        )
        session.write_composition(solo)
        session.wait_for_composition(
            expected_bot_count=1,
            expected_learned_count=1,
            timeout=args.startup_timeout,
        )
        session.wait_for_run_ready(
            expected_bot_count=1,
            expected_learned_count=1,
            timeout=args.startup_timeout,
        )
        session.wait_for_bot_materialized(
            expected_bot_count=1,
            expected_learned_count=1,
            timeout=args.startup_timeout
        )
        run_identity = session.get_run_identity()
        if (
            run_identity["observed_seed"] != args.seed
            or run_identity["run_nonce"] != args.seed
        ):
            raise BridgeError(
                "live verifier run identity did not match its seed"
            )
        progression = session.prime_learned_progression(
            minimum_secondary_slots=1,
            timeout=args.startup_timeout
        )
        participant_id = session.learned_participant_ids()[0]
        pre_weld = _wait_for(
            session,
            lambda value: (
                _integer(value, "observation_count") == 395
                and value.get("primary_welded") == "false"
            ),
            timeout=args.timeout,
            label="pre-weld policy observation",
        )
        _validate_contract(pre_weld)
        authority_host_ally_count = _integer(
            pre_weld,
            "ally_observation_count",
        )
        if authority_host_ally_count < 1:
            raise BridgeError(
                "local-authority episode did not observe its native owner"
            )

        weld = _apply_one_weld(session, participant_id)
        post_weld = _wait_for(
            session,
            lambda value: (
                value.get("primary_welded") == "true"
                and _integer(value, "primary_build_id")
                == _integer(weld, "captured_build_id")
            ),
            timeout=args.timeout,
            label="post-weld policy observation",
        )
        _validate_contract(post_weld)
        primary_range = _finite(post_weld, "primary_range_max")
        spawn_distance = primary_range + args.secondary_range_margin
        _spawn_enemy(
            session,
            offset_x=spawn_distance,
            hp=10000.0,
            freeze_on_spawn=True,
        )
        target_ready = _wait_for(
            session,
            lambda value: (
                _integer(value, "target_network_actor_id") > 0
                and _integer(value, "current_target_slot") == 1
                and value.get("target_in_primary_range") == "false"
                and _finite(value, "target_contact_distance")
                > primary_range
            ),
            timeout=args.timeout,
            label="policy-selected initial target",
        )
        _validate_contract(target_ready)
        cast_mask = target_ready.get("cast_mask", "")
        secondary_slot = next(
            (
                slot
                for slot in range(1, 9)
                if len(cast_mask) > slot + 1
                and cast_mask[slot + 1] == "1"
            ),
            0,
        )
        if secondary_slot < 1:
            raise BridgeError(
                "no target-conditioned secondary was legal beyond "
                f"the primary window: {target_ready}"
            )
        forced_secondary = _forced_policy(
            policy,
            movement_action=0,
            target_action=1,
            cast_action=secondary_slot + 1,
        )
        secondary_generation = session.load_policy(
            forced_secondary
        )
        secondary = _wait_for(
            session,
            lambda value: (
                _integer(
                    value,
                    "secondary_beyond_primary_accepted",
                )
                > 0
                and _integer(value, "target_network_actor_id") > 0
                and _integer(value, "cast_mask_mismatches") == 0
            ),
            timeout=args.timeout,
            label="target-conditioned beyond-primary secondary cast",
        )
        _validate_contract(secondary)
        persisted_actor_id = _integer(
            secondary,
            "target_network_actor_id",
        )
        first_target_slot = _integer(
            secondary,
            "current_target_slot",
        )
        if first_target_slot != 1:
            raise BridgeError(
                f"initial selected enemy was not slot 1: {secondary}"
            )

        persistence_policy = _forced_policy(
            policy,
            movement_action=0,
            target_action=0,
            cast_action=0,
        )
        persistence_generation = session.load_policy(
            persistence_policy
        )
        _spawn_enemy(session, offset_x=80.0, hp=10000.0)
        persisted = _wait_for(
            session,
            lambda value: (
                _integer(value, "target_network_actor_id")
                == persisted_actor_id
                and _integer(value, "current_target_slot") >= 2
            ),
            timeout=args.timeout,
            label="actor-ID target persistence after enemy re-sort",
        )
        _validate_contract(persisted)

        pickup_range = _finite(persisted, "pickup_range") * 30.0
        pickup_distance = pickup_range + args.pickup_range_margin
        (
            pickup_movement_action,
            pickup_direction_x,
            pickup_direction_y,
            pickup_clearance,
        ) = _clearest_pickup_direction(
            persisted,
            required_distance=pickup_distance,
        )
        position_before_values = local_sync.parse_key_values(
            session.lua(
                """
local bot = (sd.bots.list() or {})[1]
local x, y = bot:position()
print('x=' .. string.format('%.17g', x))
print('y=' .. string.format('%.17g', y))
"""
            )
        )
        position_before = (
            _finite(position_before_values, "x"),
            _finite(position_before_values, "y"),
        )
        spawned_pickup = _spawn_gold_ahead(
            session,
            amount=PICKUP_AMOUNT,
            distance=pickup_distance,
            direction_x=pickup_direction_x,
            direction_y=pickup_direction_y,
        )
        drop_id = int(spawned_pickup["network_drop_id"])
        pickup_observed = _wait_for(
            session,
            lambda value: (
                _integer(value, "pickup_observation_count") > 0
                and _integer(
                    value,
                    "pickup_observation_first_id",
                )
                == drop_id
            ),
            timeout=args.timeout,
            label="pickup observation block population",
        )
        _validate_contract(pickup_observed)

        movement_policy = _forced_policy(
            policy,
            movement_action=pickup_movement_action,
            target_action=0,
            cast_action=0,
        )
        movement_generation = session.load_policy(movement_policy)
        credited = _wait_for(
            session,
            lambda value: (
                value.get("pickup_result") == "Accepted"
                and _integer(
                    value,
                    "pickup_result_network_drop_id",
                )
                == drop_id
                and _integer(
                    value,
                    "pickup_result_participant_id",
                )
                == participant_id
                and _integer(value, "gold")
                == spawned_pickup["gold_before"] + PICKUP_AMOUNT
            ),
            timeout=args.timeout,
            label="native exactly-once pickup credit",
        )
        if (
            _integer(credited, "pickup_request_accepted") != 1
            or _integer(credited, "pickup_result_amount")
            != PICKUP_AMOUNT
        ):
            raise BridgeError(
                f"pickup request was not credited exactly once: {credited}"
            )
        request_position = (
            _finite(credited, "last_pickup_request_x"),
            _finite(credited, "last_pickup_request_y"),
        )
        request_distance = _finite(
            credited,
            "last_pickup_request_distance",
        )
        displacement = math.hypot(
            request_position[0] - position_before[0],
            request_position[1] - position_before[1],
        )
        distance_before = math.hypot(
            float(spawned_pickup["spawn_x"]) - position_before[0],
            float(spawned_pickup["spawn_y"]) - position_before[1],
        )
        if (
            displacement < MINIMUM_LIVE_DISPLACEMENT
            or request_distance >= distance_before
            or request_distance > pickup_range
        ):
            raise BridgeError(
                "learned bot did not walk into native pickup range"
            )
        settled_generation = session.load_policy(
            persistence_policy
        )
        credit_revision = _integer(
            credited,
            "pickup_result_gold_revision",
        )
        time.sleep(0.5)
        credit_stable = _telemetry(session)
        if (
            _integer(credit_stable, "gold")
            != spawned_pickup["gold_before"] + PICKUP_AMOUNT
            or _integer(
                credit_stable,
                "pickup_result_gold_revision",
            )
            != credit_revision
            or _integer(
                credit_stable,
                "pickup_request_accepted",
            )
            != 1
        ):
            raise BridgeError(
                f"pickup credit repeated after deactivation: {credit_stable}"
            )
        position_after_values = local_sync.parse_key_values(
            session.lua(
                """
local bot = (sd.bots.list() or {})[1]
local x, y = bot:position()
print('x=' .. string.format('%.17g', x))
print('y=' .. string.format('%.17g', y))
"""
            )
        )
        position_after = (
            _finite(position_after_values, "x"),
            _finite(position_after_values, "y"),
        )
        distance_after = math.hypot(
            float(spawned_pickup["spawn_x"]) - position_after[0],
            float(spawned_pickup["spawn_y"]) - position_after[1],
        )

        session.write_composition(team)
        session.wait_for_composition(
            expected_bot_count=2,
            expected_learned_count=1,
            timeout=args.startup_timeout,
        )
        session.wait_for_bot_materialized(
            expected_bot_count=2,
            expected_learned_count=1,
            timeout=args.startup_timeout,
        )
        team_observation = _wait_for(
            session,
            lambda value: (
                _integer(value, "ally_observation_count")
                > authority_host_ally_count
            ),
            timeout=args.timeout,
            label="team ally observation population",
        )
        team_values = _validate_contract(team_observation)
        ally_present_index = spec.OBSERVATION_NAMES.index(
            "ally_1_present"
        )
        ally_count_index = spec.OBSERVATION_NAMES.index(
            "ally_count_scaled"
        )
        if (
            team_values[ally_present_index] != 1.0
            or team_values[ally_count_index] <= 0.0
        ):
            raise BridgeError(
                "team ally observation values were not populated"
            )

        status = session.status()
        gameplay = local_sync.parse_key_values(
            session.lua(GAMEPLAY_STATUS, timeout=10.0)
        )
        log_path = (
            session.stage_root
            / ".sdmod"
            / "logs"
            / "solomondarkmodloader.log"
        )
        log_tokens = (
            "policy target selected",
            "policy secondary accepted",
            "pickup request queued",
            "Multiplayer loot pickup accepted",
        )
        key_log_lines: dict[str, str] = {}
        if log_path.is_file():
            for line in log_path.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines():
                for token in log_tokens:
                    if token in line and token not in key_log_lines:
                        key_log_lines[token] = line

        elapsed = time.monotonic() - started_at
        result: dict[str, object] = {
            "status": "ok",
            "instance": instance,
            "headless": not args.visible,
            "process_id": launch.get("processId") if launch else None,
            "seed_round_trip": seed_round_trip,
            "observed_run_nonce": run_identity["run_nonce"],
            "layout_sha256": session.layout_sha256(),
            "offline_solo": offline_solo,
            "policy_generations": [
                generation,
                secondary_generation,
                persistence_generation,
                movement_generation,
                settled_generation,
            ],
            "clock_source": status.get("clock_source"),
            "simulation_tick_end": _integer(
                status,
                "simulation_tick",
            ),
            "policy_decision_count": _integer(
                status,
                "policy_decision_count",
            ),
            "move_accepted": _integer(status, "move_accepted"),
            "cast_accepted": _integer(status, "cast_accepted"),
            "maximum_bot_displacement": displacement,
            "observation_count": len(team_values),
            "mask_checks": {
                "movement": "exact-live-segment-match",
                "target": "exact-slot-and-persistence-match",
                "cast": "exact-target-conditioned-match",
            },
            "weld": weld,
            "target_persistence": {
                "network_actor_id": persisted_actor_id,
                "slot_before": first_target_slot,
                "slot_after": _integer(
                    persisted,
                    "current_target_slot",
                ),
            },
            "secondary_beyond_primary": {
                "slot": secondary_slot,
                "primary_range_max": primary_range,
                "spawn_distance": spawn_distance,
                "accepted_count": _integer(
                    secondary,
                    "secondary_beyond_primary_accepted",
                ),
            },
            "pickup": {
                "network_drop_id": drop_id,
                "amount": PICKUP_AMOUNT,
                "gold_before": spawned_pickup["gold_before"],
                "gold_after": _integer(credit_stable, "gold"),
                "gold_revision": credit_revision,
                "request_count": _integer(
                    credit_stable,
                    "pickup_request_accepted",
                ),
                "native_range": pickup_range,
                "spawn_distance": pickup_distance,
                "movement_action": pickup_movement_action,
                "movement_name": spec.MOVEMENT_ACTION_NAMES[
                    pickup_movement_action
                ],
                "clearance": pickup_clearance,
                "position_before": list(position_before),
                "request_position": list(request_position),
                "request_distance": request_distance,
                "position_after": list(position_after),
                "distance_before": distance_before,
                "distance_after": distance_after,
            },
            "ally_observations": {
                "solo_count": offline_solo["ally_count"],
                "authority_host_baseline_count": (
                    authority_host_ally_count
                ),
                "team_count": _integer(
                    team_observation,
                    "ally_observation_count",
                ),
            },
            "progression": progression,
            "wave": _integer(gameplay, "wave"),
            "last_movement": gameplay.get("policy_movement_name"),
            "last_cast": gameplay.get("policy_cast_name"),
            "key_log_lines": [
                key_log_lines[token]
                for token in log_tokens
                if token in key_log_lines
            ],
            "elapsed_wall_seconds": elapsed,
        }
        return result
    finally:
        session.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=str(DEFAULT_MODEL))
    parser.add_argument("--instance")
    parser.add_argument(
        "--game-directory",
        default=str(DEFAULT_GAME_DIRECTORY),
    )
    parser.add_argument("--launcher-path", default=str(DEFAULT_LAUNCHER))
    parser.add_argument(
        "--runtime-root",
        default=str(ROOT / "runtime"),
    )
    parser.add_argument("--local-port", type=int, default=49790)
    parser.add_argument("--unused-remote-port", type=int, default=49791)
    parser.add_argument("--startup-timeout", type=float, default=45.0)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--seed", type=int, default=20260729)
    parser.add_argument(
        "--secondary-range-margin",
        type=float,
        default=180.0,
    )
    parser.add_argument(
        "--pickup-range-margin",
        type=float,
        default=20.0,
    )
    parser.add_argument(
        "--element",
        choices=("fire", "water", "earth", "air", "ether"),
        default="fire",
    )
    parser.add_argument(
        "--discipline",
        choices=("mind", "body", "arcane"),
        default="arcane",
    )
    parser.add_argument("--visible", action="store_true")
    parser.add_argument("--output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.seed < 1 or args.seed > 0x3FFFFFFF:
            raise ValueError("seed must be between 1 and 0x3fffffff")
        if (
            args.secondary_range_margin <= 0.0
            or args.pickup_range_margin <= 0.0
        ):
            raise ValueError(
                "range margin and pickup distance must be positive"
            )
        result = verify(args)
        output = json.dumps(result, indent=2, sort_keys=True)
        print(output)
        if args.output:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(output + "\n", encoding="utf-8")
        return 0
    except (
        BridgeError,
        local_sync.VerifyFailure,
        OSError,
        RuntimeError,
        ValueError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
