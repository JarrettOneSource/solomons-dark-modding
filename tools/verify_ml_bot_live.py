#!/usr/bin/env python3
"""Live policy-v3 contract and learned-behavior acceptance verifier."""

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
DEFAULT_MODEL = ROOT / "models" / "bot-brain" / "policy-v3.json"
MINIMUM_LIVE_DISPLACEMENT = 1.0
PICKUP_AMOUNT = 7
NAV_CLEARANCE_RAY_RANGE = 480.0
PROCEDURAL_SURVIVAL_SELECTOR_RVA = 0x00B3BEDC


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

local ability_mismatches = 0
local ability_mask = debug.policy_ability_mask or {}
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
if ability_mask[1] ~= true then
  ability_mismatches = ability_mismatches + 1
end
local primary = loadout.primary or {}
local expected_primary =
  common and primary.occupied == true and
  primary.affordable == true and range_ok(primary)
if ability_mask[2] ~= expected_primary then
  ability_mismatches = ability_mismatches + 1
end
for slot = 1, 8 do
  local secondary = (loadout.secondaries or {})[slot] or {}
  local expected =
    common and secondary.occupied == true and
    secondary.affordable == true and
    secondary.ready == true and range_ok(secondary)
  if ability_mask[slot + 2] ~= expected then
    ability_mismatches = ability_mismatches + 1
  end
end

local inventory_capture = debug.policy_inventory or {}
for slot = 1, 12 do
  local expected =
    (inventory_capture.potion_legal or {})[slot] == true
  local potion =
    (inventory_capture.potion_rows or {})[slot] or {}
  local subtype = tonumber(
    type(potion.source) == 'table' and
      potion.source.stock_subtype or -1) or -1
  if subtype == 2 or subtype == 3 or subtype == 4 then
    expected = false
  end
  if ability_mask[slot + 10] ~= expected then
    ability_mismatches = ability_mismatches + 1
  end
end

local aim_mismatches = 0
local aim_mask = debug.policy_aim_mask or {}
local ability_action =
  tonumber(debug.policy_ability_action) or 0
local aim_free = false
if ability_action == 1 then
  aim_free = primary.aim_free == true
elseif ability_action >= 2 and ability_action <= 9 then
  local secondary =
    (loadout.secondaries or {})[ability_action - 1] or {}
  aim_free = secondary.aim_free == true
end
for index = 1, 9 do
  local expected = index == 1 or aim_free
  if aim_mask[index] ~= expected then
    aim_mismatches = aim_mismatches + 1
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
local enemy_status_resolved_count = 0
local enemy_species_known_count = 0
local enemy_telegraph_known_count = 0
local enemy_status_active_count = 0
for _, enemy in ipairs(debug.policy_enemy_slots or {}) do
  local descriptor = enemy.descriptor or {}
  if enemy.combat_status_resolved == true then
    enemy_status_resolved_count =
      enemy_status_resolved_count + 1
  end
  if descriptor.species_known == true then
    enemy_species_known_count =
      enemy_species_known_count + 1
  end
  if descriptor.telegraph_known == true then
    enemy_telegraph_known_count =
      enemy_telegraph_known_count + 1
  end
  if descriptor.slowed == true or descriptor.frozen == true or
      descriptor.poisoned == true or descriptor.webbed == true or
      descriptor.turn_undead == true then
    enemy_status_active_count =
      enemy_status_active_count + 1
  end
end
local first_hazard = (debug.policy_hazards or {})[1] or {}
local first_obstacle = (debug.policy_obstacles or {})[1] or {}
local potion_rows = inventory_capture.potion_rows or {}
local potion_lines = {}
for slot, potion in ipairs(potion_rows) do
  local source = potion.source or {}
  potion_lines[#potion_lines + 1] = table.concat({
    tostring(slot),
    tostring(tonumber(source.stock_subtype) or -1),
    tostring(tonumber(source.count) or 0),
    tostring((inventory_capture.potion_legal or {})[slot] == true),
  }, ':')
end
print('observation_version=' ..
  tostring(debug.policy_observation_version or 0))
print('observation_count=' ..
  tostring(#(debug.policy_observation or {})))
print('observation_finite=' .. tostring(observation_finite))
print('observation=' .. table.concat(observations, ','))
print('movement_mask=' .. bits(debug.policy_movement_mask))
print('target_mask=' .. bits(target_mask))
print('ability_mask=' .. bits(ability_mask))
print('aim_mask=' .. bits(aim_mask))
print('movement_mask_mismatches=' ..
  tostring(movement_mismatches))
print('target_mask_mismatches=' ..
  tostring(target_mismatches))
print('ability_mask_mismatches=' ..
  tostring(ability_mismatches))
print('aim_mask_mismatches=' ..
  tostring(aim_mismatches))
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
print('enemy_status_resolved_count=' ..
  tostring(enemy_status_resolved_count))
print('enemy_species_known_count=' ..
  tostring(enemy_species_known_count))
print('enemy_telegraph_known_count=' ..
  tostring(enemy_telegraph_known_count))
print('enemy_status_active_count=' ..
  tostring(enemy_status_active_count))
print('hazard_observation_count=' ..
  tostring(#(debug.policy_hazards or {})))
print('hazard_1_id=' ..
  tostring(tonumber(first_hazard.hazard_id) or 0))
print('hazard_1_kind=' .. tostring(first_hazard.kind or ''))
print('hazard_1_type_known=' ..
  tostring(first_hazard.type_known == true))
print('hazard_1_targeting_self=' ..
  tostring(first_hazard.targeting_self == true))
print('hazard_1_dx=' ..
  string.format('%.17g', tonumber(first_hazard.dx) or 0))
print('hazard_1_dy=' ..
  string.format('%.17g', tonumber(first_hazard.dy) or 0))
print('hazard_1_velocity_dx=' ..
  string.format('%.17g', tonumber(first_hazard.velocity_x) or 0))
print('hazard_1_velocity_dy=' ..
  string.format('%.17g', tonumber(first_hazard.velocity_y) or 0))
print('hazard_1_time_to_contact=' ..
  string.format('%.17g', tonumber(first_hazard.time_to_contact) or 0))
print('obstacle_observation_count=' ..
  tostring(#(debug.policy_obstacles or {})))
print('obstacle_1_id=' ..
  tostring(first_obstacle.geometry_id or ''))
print('obstacle_1_kind=' .. tostring(first_obstacle.kind or ''))
print('obstacle_1_radius=' ..
  string.format('%.17g', tonumber(first_obstacle.radius) or 0))
print('obstacle_1_clearance=' ..
  string.format('%.17g', tonumber(first_obstacle.clearance) or 0))
print('obstacle_1_normal_dx=' ..
  string.format('%.17g', tonumber(first_obstacle.normal_dx) or 0))
print('obstacle_1_normal_dy=' ..
  string.format('%.17g', tonumber(first_obstacle.normal_dy) or 0))
print('potion_rows=' .. table.concat(potion_lines, ','))
print('inventory_revision=' ..
  tostring((inventory_capture.details or {}).inventory_revision or 0))
print('skill_choice_mode=' ..
  tostring(debug.skill_choice_mode or ''))
print('skill_choice_generation=' ..
  tostring(debug.skill_choice_generation or 0))
print('skill_choice_option_index=' ..
  tostring(debug.skill_choice_option_index or 0))
print('skill_choice_option_id=' ..
  tostring(debug.skill_choice_option_id or -1))
print('skill_choice_probability=' ..
  string.format('%.17g',
    tonumber(debug.skill_choice_probability) or 0))
print('skill_choices_accepted=' ..
  tostring(debug.skill_choices_accepted or 0))
print('potion_use_issued=' ..
  tostring(debug.potion_use_issued or 0))
print('potion_use_accepted=' ..
  tostring(debug.potion_use_accepted or 0))
print('last_potion_slot=' ..
  tostring(debug.last_potion_slot or 0))
print('last_potion_use_id=' ..
  tostring(debug.last_potion_use_id or 0))
print('hazard_dodge_accepted=' ..
  tostring(debug.hazard_dodge_accepted or 0))
print('last_hazard_dodge_id=' ..
  tostring(debug.last_hazard_dodge_id or 0))
print('last_hazard_slot=' ..
  tostring(debug.last_hazard_slot or 0))
print('last_hazard_type_known=' ..
  tostring(debug.last_hazard_type_known == true))
print('last_hazard_targeting_self=' ..
  tostring(debug.last_hazard_targeting_self == true))
print('last_hazard_time_to_contact=' ..
  string.format(
    '%.17g',
    tonumber(debug.last_hazard_time_to_contact) or 0))
print('exact_obstacle_clearance_accepted=' ..
  tostring(debug.exact_obstacle_clearance_accepted or 0))
print('last_exact_obstacle_id=' ..
  tostring(debug.last_exact_obstacle_id or ''))
print('lead_cast_accepted=' ..
  tostring(debug.lead_cast_accepted or 0))
print('last_lead_aim_offset_x=' ..
  string.format('%.17g', tonumber(debug.last_lead_aim_offset_x) or 0))
print('last_lead_aim_offset_y=' ..
  string.format('%.17g', tonumber(debug.last_lead_aim_offset_y) or 0))
print('last_lead_velocity_dx=' ..
  string.format('%.17g', tonumber(debug.last_lead_velocity_dx) or 0))
print('last_lead_velocity_dy=' ..
  string.format('%.17g', tonumber(debug.last_lead_velocity_dy) or 0))
print('center_mask_cast_accepted=' ..
  tostring(debug.center_mask_cast_accepted or 0))
print('last_aim_offset_x=' ..
  string.format('%.17g', tonumber(debug.last_aim_offset_x) or 0))
print('last_aim_offset_y=' ..
  string.format('%.17g', tonumber(debug.last_aim_offset_y) or 0))
print('target_velocity_dx=' ..
  string.format('%.17g',
    type(target) == 'table' and
      tonumber(target.velocity_dx) or 0))
print('target_velocity_dy=' ..
  string.format('%.17g',
    type(target) == 'table' and
      tonumber(target.velocity_dy) or 0))
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
print('policy_ability_action=' ..
  tostring(debug.policy_ability_action or 0))
print('policy_ability_name=' ..
  tostring(debug.policy_ability_name or ''))
print('policy_aim_action=' ..
  tostring(debug.policy_aim_action or 0))
print('policy_aim_name=' ..
  tostring(debug.policy_aim_name or ''))
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
print('policy_ability_name=' ..
  tostring(debug.policy_ability_name or ''))
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
    ability_action: int,
    aim_action: int = 0,
) -> BotPolicy:
    policy = BotPolicy.from_dict(copy.deepcopy(source.to_dict()))
    for weight in (
        policy.movement_weight,
        policy.target_weight,
        policy.ability_weight,
        policy.aim_weight,
    ):
        weight.fill(0.0)
    for bias, action in (
        (policy.movement_bias, movement_action),
        (policy.target_bias, target_action),
        (policy.ability_bias, ability_action),
        (policy.aim_bias, aim_action),
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


def _select_procedural_survival_layout(
    session: SoloSession,
) -> dict[str, str]:
    values = local_sync.parse_key_values(
        session.lua(
            f"""
local selector = sd.debug.resolve_game_address(
  {PROCEDURAL_SURVIVAL_SELECTOR_RVA})
local ok = selector ~= nil and selector ~= 0 and
  sd.debug.write_i32(selector, 1)
print('ok=' .. tostring(ok == true))
"""
        )
    )
    if values.get("ok") != "true":
        raise BridgeError(
            f"could not select procedural survival layout: {values}"
        )
    return values


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
        ("ability_mask", len(spec.ABILITY_ACTION_NAMES)),
        ("aim_mask", len(spec.AIM_ACTION_NAMES)),
    ):
        mask = values.get(key, "")
        if len(mask) != expected or any(bit not in "01" for bit in mask):
            raise BridgeError(f"invalid live {key}: {mask!r}")
    if (
        values.get("selected_actions_legal") != "true"
        or _integer(values, "movement_mask_mismatches") != 0
        or _integer(values, "target_mask_mismatches") != 0
        or _integer(values, "ability_mask_mismatches") != 0
        or _integer(values, "aim_mask_mismatches") != 0
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


def _learned_weld_policy(source: BotPolicy) -> BotPolicy:
    policy = _forced_policy(
        source,
        movement_action=0,
        target_action=0,
        ability_action=0,
        aim_action=0,
    )
    policy.choice_option_weight.fill(0.0)
    policy.choice_option_bias.fill(0.0)
    policy.choice_score_weight.fill(0.0)
    policy.choice_score_bias.fill(0.0)
    latent_width = policy.hidden_weight.shape[0]
    weld_column = latent_width + spec.OPTION_DESCRIPTOR_NAMES.index(
        "is_weld"
    )
    primary_column = latent_width + spec.OPTION_DESCRIPTOR_NAMES.index(
        "is_primary"
    )
    policy.choice_option_weight[0, weld_column] = 8.0
    policy.choice_score_weight[0] = 12.0
    policy.choice_option_weight[1, primary_column] = 6.0
    policy.choice_score_weight[1] = 4.0
    return policy


def _apply_one_weld(
    session: SoloSession,
    participant_id: int,
    source_policy: BotPolicy,
    *,
    seed: int,
    max_rolls: int = 64,
) -> dict[str, object]:
    prerequisites = local_sync.parse_key_values(
        session.lua(
            f"""
local participant_id = {participant_id}
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
local ok =
  current_primary >= 0 and second_primary >= 0 and
  current_primary < table_count and second_primary < table_count and
  table_address > 0 and table_stride > 0
if ok then
  for _, entry_id in ipairs({{current_primary, second_primary}}) do
    local row = table_address + entry_id * table_stride
    ok =
      sd.debug.write_u16(row + active_offset, 1) and
      sd.debug.write_u16(row + effective_offset, 1) and ok
  end
end
print('prerequisite_writes_ok=' .. tostring(ok == true))
print('current_primary=' .. tostring(current_primary))
print('second_primary=' .. tostring(second_primary))
print('table_count=' .. tostring(table_count))
"""
        )
    )
    if prerequisites.get("prerequisite_writes_ok") != "true":
        raise BridgeError(
            f"could not prepare learned weld offer: {prerequisites}"
        )

    session.clear_training()
    session.enable_training(seed=seed, capacity=5000)
    policy_generation = session.load_policy(
        _learned_weld_policy(source_policy)
    )
    previous_accepted = _integer(
        _telemetry(session),
        "skill_choices_accepted",
    )
    selected: dict[str, str] | None = None
    for roll in range(1, max_rolls + 1):
        advanced = local_sync.parse_key_values(
            session.lua(
                f"""
local participant_id = {participant_id}
local state = sd.bots.get_state(participant_id) or {{}}
local progression =
  tonumber(state.progression_runtime_state_address) or 0
local player = sd.player.get_state() or {{}}
local source_progression =
  tonumber(player.progression_address) or 0
local level_offset = assert(
  sd.debug.layout_offset('progression_level'))
local next_xp_offset = assert(
  sd.debug.layout_offset(
    'progression_next_xp_threshold'))
local level = progression > 0 and
  (tonumber(sd.debug.read_i32(
    progression + level_offset)) or 0) or 0
local next_xp = progression > 0 and
  (tonumber(sd.debug.read_float(
    progression + next_xp_offset)) or 0) or 0
local ok = progression > 0 and source_progression > 0 and
  level > 0 and next_xp > 0 and
  sd.bots.debug_sync_level_up({{
    level = level + 1,
    experience = math.ceil(next_xp + 10),
    source_progression_address = source_progression,
  }}) == true
print('ok=' .. tostring(ok == true))
print('level=' .. tostring(level))
"""
            )
        )
        if advanced.get("ok") != "true":
            raise BridgeError(
                f"could not roll learned skill choice {roll}: {advanced}"
            )
        selected = _wait_for(
            session,
            lambda value: _integer(
                value,
                "skill_choices_accepted",
            ) > previous_accepted,
            timeout=10.0,
            label=f"learned skill choice {roll}",
        )
        previous_accepted = _integer(
            selected,
            "skill_choices_accepted",
        )
        if _integer(selected, "skill_choice_option_id") == 52:
            selected["roll_count"] = str(roll)
            break
    if (
        selected is None
        or _integer(selected, "skill_choice_option_id") != 52
    ):
        raise BridgeError(
            f"learned policy did not select a weld offer: {selected}"
        )

    welded = _wait_for(
        session,
        lambda value: (
            value.get("primary_welded") == "true"
            and _integer(value, "primary_build_id") >= 1000
        ),
        timeout=10.0,
        label="learned weld promotion",
    )
    time.sleep(0.35)
    finished = session.finish_training_episode()
    choice_count = _integer(finished, "choice_buffered")
    records = session.drain_choice_rollouts(choice_count)
    session.clear_training()
    weld_descriptor_index = spec.OPTION_DESCRIPTOR_NAMES.index("is_weld")
    weld_record = next(
        (
            record
            for record in records
            if record.accepted
            and record.choice_mode == "learned"
            and record.trainable
            and record.option_descriptors[record.selected_option][
                weld_descriptor_index
            ]
            == 1.0
        ),
        None,
    )
    if weld_record is None or weld_record.duration_steps <= 0:
        raise BridgeError(
            "learned weld choice did not produce a complete positive-duration "
            f"choice-event-v3 interval: {records}"
        )
    build_id = _integer(welded, "primary_build_id")
    return {
        **prerequisites,
        **selected,
        "applied": "true",
        "captured_build_id": str(build_id),
        "active_build_id": str(build_id),
        "active_build_resolved": "true",
        "policy_generation": policy_generation,
        "choice_record_count": len(records),
        "choice_trajectory": {
            "version": weld_record.choice_trajectory_version,
            "generation": weld_record.generation,
            "duration_steps": weld_record.duration_steps,
            "reward_count": len(weld_record.rewards),
            "selected_option": weld_record.selected_option,
            "accepted": weld_record.accepted,
            "trainable": weld_record.trainable,
            "mode": weld_record.choice_mode,
        },
        "log_line": _find_runtime_log_line(
            session,
            "policy skill choice accepted mode=learned",
        ),
    }
def _spawn_enemy(
    session: SoloSession,
    *,
    offset_x: float,
    offset_y: float = 0.0,
    type_id: int = 1001,
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
    type_id = {type_id},
    x = x + {offset_x:.17g},
    y = y + {offset_y:.17g},
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
print('network_actor_id=' ..
  tostring(result.network_actor_id or 0))
""",
                timeout=10.0,
            )
        )
        if result.get("available") == "true":
            if result.get("ok") != "true":
                raise BridgeError(
                    f"manual enemy materialization failed: {result}"
                )
            if (
                _integer(result, "actor_address") > 0
                and _integer(result, "network_actor_id") > 0
            ):
                return _integer(result, "actor_address")
        time.sleep(0.05)
    raise BridgeError("manual enemy materialization timed out")


def _retire_enemy(session: SoloSession, actor_address: int) -> None:
    values = local_sync.parse_key_values(
        session.lua(
            f"""
local ok = sd.gameplay.set_run_enemy_health(
  {actor_address}, 0.0, 1.0)
print('ok=' .. tostring(ok == true))
"""
        )
    )
    if values.get("ok") != "true":
        raise BridgeError(f"manual enemy retirement failed: {values}")


def _retire_all_tracked_enemies(
    session: SoloSession,
    *,
    timeout: float,
) -> dict[str, int]:
    deadline = time.monotonic() + timeout
    retired_total = 0
    quiet_samples = 0
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = local_sync.parse_key_values(
            session.lua(
                """
local active = 0
local retired = 0
for _, actor in ipairs(sd.world.list_actors() or {}) do
  local address = tonumber(actor.actor_address) or 0
  if actor.tracked_enemy == true and
      actor.dead ~= true and
      (tonumber(actor.hp) or 0) > 0 and address > 0 then
    active = active + 1
    if sd.gameplay.set_run_enemy_health(address, 0.0, 1.0) then
      retired = retired + 1
    end
  end
end
print('active=' .. tostring(active))
print('retired=' .. tostring(retired))
"""
            )
        )
        active = _integer(last, "active")
        retired = _integer(last, "retired")
        if retired != active:
            raise BridgeError(
                f"tracked-enemy cleanup was incomplete: {last}"
            )
        retired_total += retired
        quiet_samples = quiet_samples + 1 if active == 0 else 0
        if quiet_samples >= 3:
            return {
                "retired": retired_total,
                "quiet_samples": quiet_samples,
            }
        time.sleep(0.1)
    raise BridgeError(f"tracked enemies did not quiesce: {last}")


def _release_enemy_freeze(
    session: SoloSession,
    actor_address: int,
) -> dict[str, str]:
    values = local_sync.parse_key_values(
        session.lua(
            f"""
local ok = sd.gameplay.clear_manual_run_enemy_freeze({actor_address})
print('ok=' .. tostring(ok == true))
"""
        )
    )
    if values.get("ok") != "true":
        raise BridgeError(f"manual enemy freeze release failed: {values}")
    return values


def _aim_action_for_velocity(dx: float, dy: float) -> int:
    magnitude = math.hypot(dx, dy)
    if magnitude <= 1e-4:
        raise BridgeError("target velocity is too small for a lead proof")
    unit_x = dx / magnitude
    unit_y = dy / magnitude
    return max(
        range(1, len(spec.MOVEMENT_DIRECTIONS)),
        key=lambda action: (
            unit_x * spec.MOVEMENT_DIRECTIONS[action][0]
            + unit_y * spec.MOVEMENT_DIRECTIONS[action][1]
        ),
    )


def _velocity_lead_policy(source: BotPolicy) -> BotPolicy:
    policy = _forced_policy(
        source,
        movement_action=0,
        target_action=1,
        ability_action=1,
        aim_action=0,
    )
    policy.input_weight.fill(0.0)
    policy.input_bias.fill(0.0)
    policy.hidden_weight.fill(0.0)
    policy.hidden_bias.fill(0.0)
    policy.aim_weight.fill(0.0)
    policy.aim_bias.fill(-5.0)
    policy.aim_bias[0] = 0.0
    velocity_x = spec.OBSERVATION_NAMES.index("target_velocity_dx")
    velocity_y = spec.OBSERVATION_NAMES.index("target_velocity_dy")
    policy.input_weight[0, velocity_x] = 512.0
    policy.input_weight[1, velocity_y] = 512.0
    policy.hidden_weight[0, 0] = 4.0
    policy.hidden_weight[1, 1] = 4.0
    for action, (direction_x, direction_y) in enumerate(
        spec.MOVEMENT_DIRECTIONS[1:],
        start=1,
    ):
        policy.aim_weight[action, 0] = direction_x * 20.0
        policy.aim_weight[action, 1] = direction_y * 20.0
    return policy


def _run_lead_and_status_check(
    session: SoloSession,
    policy: BotPolicy,
    *,
    timeout: float,
) -> dict[str, object]:
    session.load_policy(
        _forced_policy(
            policy,
            movement_action=0,
            target_action=1,
            ability_action=0,
            aim_action=0,
        )
    )
    status_actor = _spawn_enemy(
        session,
        offset_x=220.0,
        type_id=1010,
        hp=10000.0,
        freeze_on_spawn=True,
    )
    telegraph_write = local_sync.parse_key_values(
        session.lua(
            f"""
local offset = assert(
  sd.debug.layout_offset('actor_animation_drive_state_byte'))
local previous = sd.debug.read_i8({status_actor} + offset)
local ok = previous ~= nil and
  sd.debug.write_i8({status_actor} + offset, 0x1F)
print('ok=' .. tostring(ok == true))
print('previous=' .. tostring(previous or 0))
"""
        )
    )
    if telegraph_write.get("ok") != "true":
        raise BridgeError(
            f"could not stage a proven telegraph state: {telegraph_write}"
        )
    target_ready = _wait_for(
        session,
        lambda value: (
            _integer(value, "target_network_actor_id") > 0
            and _integer(value, "enemy_species_known_count") > 0
            and _integer(value, "enemy_status_resolved_count") > 0
            and _integer(value, "enemy_telegraph_known_count") > 0
        ),
        timeout=timeout,
        label="enemy identity/status/telegraph",
    )
    _validate_contract(target_ready)
    status_actor_id = _integer(target_ready, "target_network_actor_id")
    _retire_enemy(session, status_actor)
    generation = session.load_policy(
        _velocity_lead_policy(policy)
    )
    lead_spawn_distance = max(
        _finite(target_ready, "primary_range_max") + 360.0,
        600.0,
    )
    moving_actor = _spawn_enemy(
        session,
        offset_x=lead_spawn_distance,
        type_id=1001,
        hp=10000.0,
        freeze_on_spawn=True,
    )
    moving_ready = _wait_for(
        session,
        lambda value: (
            _integer(value, "target_network_actor_id") > 0
            and _integer(value, "target_network_actor_id")
            != status_actor_id
            and _integer(value, "enemy_species_known_count") > 0
            and math.hypot(
                _finite(value, "target_velocity_dx"),
                _finite(value, "target_velocity_dy"),
            )
            <= 1e-6
        ),
        timeout=timeout,
        label="frozen moving-enemy history baseline",
    )
    _validate_contract(moving_ready)
    freeze_release = _release_enemy_freeze(session, moving_actor)
    led = _wait_for(
        session,
        lambda value: (
            _integer(value, "target_network_actor_id") > 0
            and _integer(value, "target_network_actor_id")
            != status_actor_id
            and _integer(value, "lead_cast_accepted") > 0
            and _integer(value, "cast_accepted") > 0
            and math.hypot(
                _finite(value, "last_lead_velocity_dx"),
                _finite(value, "last_lead_velocity_dy"),
            )
            > 1e-4
        ),
        timeout=timeout,
        label="straight-projectile velocity-conditioned aim lead",
    )
    _validate_contract(led)
    offset = (
        _finite(led, "last_lead_aim_offset_x"),
        _finite(led, "last_lead_aim_offset_y"),
    )
    observed_velocity = (
        _finite(led, "last_lead_velocity_dx"),
        _finite(led, "last_lead_velocity_dy"),
    )
    lead_dot = (
        offset[0] * observed_velocity[0]
        + offset[1] * observed_velocity[1]
    )
    if (
        not math.isclose(math.hypot(*offset), 60.0, abs_tol=0.05)
        or lead_dot <= 0.0
    ):
        raise BridgeError(
            "aim-head cast did not lead along target motion: "
            f"offset={offset} velocity={observed_velocity}"
        )
    log_line = _find_runtime_log_line(
        session,
        "policy lead cast accepted",
    )
    aim_action = _aim_action_for_velocity(*offset)
    _retire_enemy(session, moving_actor)
    return {
        "status_enemy_type_id": 1010,
        "species_known_count": _integer(
            target_ready,
            "enemy_species_known_count",
        ),
        "status_resolved_count": _integer(
            target_ready,
            "enemy_status_resolved_count",
        ),
        "telegraph_known_count": _integer(
            target_ready,
            "enemy_telegraph_known_count",
        ),
        "moving_enemy_type_id": 1001,
        "moving_enemy_spawn_distance": lead_spawn_distance,
        "freeze_release": freeze_release,
        "aim_action": aim_action,
        "aim_name": spec.AIM_ACTION_NAMES[aim_action],
        "offset": list(offset),
        "target_velocity": list(observed_velocity),
        "lead_dot": lead_dot,
        "policy_generation": generation,
        "log_line": log_line,
    }


def _hazard_reactive_policy(
    source: BotPolicy,
    movement_action: int,
) -> BotPolicy:
    policy = _forced_policy(
        source,
        movement_action=0,
        target_action=0,
        ability_action=0,
        aim_action=0,
    )
    policy.input_weight.fill(0.0)
    policy.input_bias.fill(0.0)
    policy.hidden_weight.fill(0.0)
    policy.hidden_bias.fill(0.0)
    policy.movement_weight.fill(0.0)
    policy.movement_bias.fill(-10.0)
    absent_output = math.tanh(4.0 * math.tanh(-10.0))
    for slot in range(1, spec.HAZARD_SLOT_COUNT + 1):
        neuron = slot - 1
        for suffix in ("present", "type_known", "kind_projectile"):
            feature = spec.OBSERVATION_NAMES.index(
                f"hazard_{slot}_{suffix}"
            )
            policy.input_weight[neuron, feature] = 4.0
        policy.input_bias[neuron] = -10.0
        policy.hidden_weight[neuron, neuron] = 4.0
        policy.movement_weight[movement_action, neuron] = 8.0
    policy.movement_bias[0] = 0.0
    policy.movement_bias[movement_action] = (
        -8.0 * spec.HAZARD_SLOT_COUNT * absent_output - 4.0
    )
    return policy


def _trigger_hostile_arrow(
    session: SoloSession,
    archer_address: int,
    participant_id: int,
) -> dict[str, str]:
    values = local_sync.parse_key_values(
        session.lua(
            f"""
local operator_new =
  tonumber(sd.debug.resolve_game_address(0x0074784D)) or 0
local event = operator_new ~= 0 and
  sd.debug.call_cdecl_u32_ret_u32(operator_new, 0x20) or nil
local fn =
  tonumber(sd.debug.resolve_game_address(0x00477B90)) or 0
local bot = assert(sd.bots.get_state({participant_id}), 'bot missing')
local target_slot = tonumber(bot.actor_slot) or -1
local original_slot = sd.debug.read_i8({archer_address} + 0x5C)
local ready = type(event) == 'number' and event ~= 0 and
  fn ~= 0 and target_slot > 0 and
  type(original_slot) == 'number'
local dispatched = ready and
  sd.debug.write_i8({archer_address} + 0x5C, target_slot) and
  sd.debug.write_i32(event + 0x14, 0x11) and
  sd.debug.call_thiscall_u32(fn, {archer_address}, event)
local restored = type(original_slot) == 'number' and
  sd.debug.write_i8({archer_address} + 0x5C, original_slot)
local arrow_count = 0
for _, row in ipairs(sd.world.list_actors() or {{}}) do
  if tonumber(row.object_type_id) == 0x07DA then
    arrow_count = arrow_count + 1
  end
end
local hazards = sd.world.get_replicated_hazards() or {{}}
print('ready=' .. tostring(ready))
print('dispatched=' .. tostring(dispatched == true))
print('restored=' .. tostring(restored == true))
print('arrow_count=' .. tostring(arrow_count))
print('hazard_count=' .. tostring(hazards.hazard_count or 0))
"""
        )
    )
    if (
        values.get("ready") != "true"
        or values.get("dispatched") != "true"
        or values.get("restored") != "true"
    ):
        raise BridgeError(f"hostile Arrow dispatch failed: {values}")
    return values


def _select_hazard_probe_geometry(
    session: SoloSession,
    participant_id: int,
) -> dict[str, str]:
    values = local_sync.parse_key_values(
        session.lua(
            f"""
local bot = assert(sd.bots.get_state({participant_id}), 'bot missing')
local root = rawget(_G, 'bot_brain_debug') or {{}}
local debug = (root.bots or {{}})[1] or {{}}
local distance = 360.0
local directions = {{
  {{dx=1, dy=0, action=1}},
  {{dx=0.7071067811865476, dy=0.7071067811865476, action=2}},
  {{dx=0, dy=1, action=3}},
  {{dx=-0.7071067811865476, dy=0.7071067811865476, action=4}},
  {{dx=-1, dy=0, action=5}},
  {{dx=-0.7071067811865476, dy=-0.7071067811865476, action=6}},
  {{dx=0, dy=-1, action=7}},
  {{dx=0.7071067811865476, dy=-0.7071067811865476, action=8}},
}}
local selected = nil
for _, source in ipairs(directions) do
  local spawn_x = bot.x + source.dx * distance
  local spawn_y = bot.y + source.dy * distance
  if selected == nil and
      sd.nav.test_segment(bot.x, bot.y, spawn_x, spawn_y) then
    local dodge = nil
    local best_dot = math.huge
    for _, candidate in ipairs(directions) do
      local legal =
        (debug.policy_movement_mask or {{}})[
          candidate.action + 1] == true
      local dot = math.abs(
        source.dx * candidate.dx + source.dy * candidate.dy)
      if legal and dot < best_dot then
        dodge = candidate
        best_dot = dot
      end
    end
    if dodge ~= nil and best_dot < 0.1 then
      selected = {{
        offset_x=source.dx * distance,
        offset_y=source.dy * distance,
        movement_action=dodge.action,
        perpendicular_dot=best_dot,
      }}
    end
  end
end
print('ok=' .. tostring(selected ~= nil))
print('offset_x=' .. tostring(selected and selected.offset_x or 0))
print('offset_y=' .. tostring(selected and selected.offset_y or 0))
print('movement_action=' .. tostring(
  selected and selected.movement_action or 0))
print('perpendicular_dot=' .. tostring(
  selected and selected.perpendicular_dot or 1))
"""
        )
    )
    if (
        values.get("ok") != "true"
        or not 1 <= _integer(values, "movement_action") <= 8
        or _finite(values, "perpendicular_dot") >= 0.1
    ):
        raise BridgeError(
            f"no clear hostile-projectile probe lane exists: {values}"
        )
    return values


def _run_hazard_dodge_check(
    session: SoloSession,
    policy: BotPolicy,
    participant_id: int,
    *,
    timeout: float,
) -> dict[str, object]:
    probe_geometry = _select_hazard_probe_geometry(
        session,
        participant_id,
    )
    movement_action = _integer(probe_geometry, "movement_action")
    position_before = local_sync.parse_key_values(
        session.lua(
            f"""
local bot = assert(sd.bots.get_state({participant_id}), 'bot missing')
print('x=' .. tostring(bot.x or 0))
print('y=' .. tostring(bot.y or 0))
"""
        )
    )
    generation = session.load_policy(
        _hazard_reactive_policy(policy, movement_action)
    )
    archer = _spawn_enemy(
        session,
        offset_x=_finite(probe_geometry, "offset_x"),
        offset_y=_finite(probe_geometry, "offset_y"),
        type_id=0x3EA,
        hp=50000.0,
        freeze_on_spawn=False,
    )
    time.sleep(0.25)
    progress: dict[str, str] = {}
    retriggers = 0
    deadline = time.monotonic() + min(timeout, 20.0)
    while time.monotonic() < deadline:
        _trigger_hostile_arrow(session, archer, participant_id)
        retriggers += 1
        time.sleep(0.05)
        progress = local_sync.parse_key_values(
            session.lua(
                """
local root = rawget(_G, 'bot_brain_debug') or {}
local debug = (root.bots or {})[1] or {}
local hazard_rows = {}
for slot, hazard in ipairs(debug.policy_hazards or {}) do
  if slot <= 12 then
    hazard_rows[#hazard_rows + 1] = table.concat({
      tostring(slot),
      tostring(hazard.hazard_id or 0),
      tostring(hazard.kind or ''),
      tostring(hazard.type_known == true),
      tostring(hazard.time_to_contact or 0),
    }, ':')
  end
end
local movement_bits = {}
for slot, legal in ipairs(debug.policy_movement_mask or {}) do
  movement_bits[slot] = legal and '1' or '0'
end
print('hazard_dodge_accepted=' ..
  tostring(debug.hazard_dodge_accepted or 0))
print('last_hazard_dodge_id=' ..
  tostring(debug.last_hazard_dodge_id or 0))
print('last_hazard_slot=' ..
  tostring(debug.last_hazard_slot or 0))
print('last_hazard_type_known=' ..
  tostring(debug.last_hazard_type_known == true))
print('last_hazard_targeting_self=' ..
  tostring(debug.last_hazard_targeting_self == true))
print('last_hazard_time_to_contact=' ..
  tostring(debug.last_hazard_time_to_contact or 0))
print('policy_movement_action=' ..
  tostring(debug.policy_movement_action or 0))
print('hazard_rows=' .. table.concat(hazard_rows, ','))
print('movement_mask=' .. table.concat(movement_bits))
"""
            )
        )
        if (
            _integer(progress, "hazard_dodge_accepted") > 0
            and _integer(progress, "last_hazard_dodge_id") > 0
            and _integer(progress, "policy_movement_action")
            == movement_action
        ):
            break
    if _integer(progress, "hazard_dodge_accepted") <= 0:
        raise BridgeError(
            "learned policy never observed/dodged the Arrow after "
            f"{retriggers} native retriggers: {progress}"
        )
    before = (
        _finite(position_before, "x"),
        _finite(position_before, "y"),
    )
    deadline = time.monotonic() + timeout
    after = before
    displacement = 0.0
    while time.monotonic() < deadline:
        position_after = local_sync.parse_key_values(
            session.lua(
                f"""
local bot = assert(sd.bots.get_state({participant_id}), 'bot missing')
print('x=' .. tostring(bot.x or 0))
print('y=' .. tostring(bot.y or 0))
"""
            )
        )
        after = (
            _finite(position_after, "x"),
            _finite(position_after, "y"),
        )
        displacement = math.hypot(
            after[0] - before[0],
            after[1] - before[1],
        )
        if displacement >= MINIMUM_LIVE_DISPLACEMENT:
            break
        time.sleep(0.05)
    if displacement < MINIMUM_LIVE_DISPLACEMENT:
        raise BridgeError(
            f"hazard response did not move the learned bot: {displacement}"
        )
    _validate_contract(_telemetry(session))
    log_line = _find_runtime_log_line(
        session,
        "policy hazard dodge accepted",
    )
    _retire_enemy(session, archer)
    return {
        "hazard_id": _integer(progress, "last_hazard_dodge_id"),
        "hazard_slot": _integer(progress, "last_hazard_slot"),
        "type_known": progress.get("last_hazard_type_known") == "true",
        "targeting_self": (
            progress.get("last_hazard_targeting_self") == "true"
        ),
        "native_retriggers": retriggers,
        "perpendicular_dot": _finite(
            probe_geometry,
            "perpendicular_dot",
        ),
        "movement_action": movement_action,
        "movement_name": spec.MOVEMENT_ACTION_NAMES[movement_action],
        "displacement": displacement,
        "time_to_contact": _finite(
            progress,
            "last_hazard_time_to_contact",
        ),
        "policy_generation": generation,
        "log_line": log_line,
    }


def _wait_for_collision_geometry(
    session: SoloSession,
    participant_id: int,
    *,
    timeout: float,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = local_sync.parse_key_values(
            session.lua(
                f"""
local geometry =
  sd.nav.get_collision_geometry({participant_id}) or {{}}
local grid = sd.nav.get_grid(4) or {{}}
local primitive_count =
  #(geometry.circles or {{}}) +
  #(geometry.segments or {{}}) +
  #(geometry.polygons or {{}})
print('geometry_valid=' .. tostring(geometry.valid == true))
print('geometry_refresh_pending=' ..
  tostring(geometry.refresh_pending == true))
print('primitive_count=' .. tostring(primitive_count))
print('circle_count=' .. tostring(#(geometry.circles or {{}})))
print('segment_count=' .. tostring(#(geometry.segments or {{}})))
print('polygon_count=' .. tostring(#(geometry.polygons or {{}})))
print('grid_refresh_pending=' ..
  tostring(grid.refresh_pending == true))
print('grid_subdivisions=' .. tostring(grid.subdivisions or 0))
print('grid_cell_count=' .. tostring(#(grid.cells or {{}})))
""",
                timeout=15.0,
            )
        )
        if (
            last.get("geometry_valid") == "true"
            and last.get("geometry_refresh_pending") == "false"
            and _integer(last, "primitive_count") > 0
            and last.get("grid_refresh_pending") == "false"
            and _integer(last, "grid_subdivisions") == 4
            and _integer(last, "grid_cell_count") > 0
        ):
            return last
        time.sleep(0.1)
    raise BridgeError(
        f"collision geometry/grid did not become complete: {last}"
    )


def _run_geometry_spot_audit(
    session: SoloSession,
    participant_id: int,
) -> dict[str, object]:
    clearance_indexes = [
        spec.OBSERVATION_NAMES.index(
            f"clearance_{name}_scaled"
        )
        + 1
        for name in spec.MOVEMENT_ACTION_NAMES[1:]
    ]
    patch_indexes = [
        index + 1
        for index, name in enumerate(spec.OBSERVATION_NAMES)
        if name.startswith("walkability_patch_")
    ]
    values = local_sync.parse_key_values(
        session.lua(
            f"""
local participant_id = {participant_id}
local root = rawget(_G, 'bot_brain_debug') or {{}}
local debug = (root.bots or {{}})[1] or {{}}
local observation = debug.policy_observation or {{}}
local geometry = assert(
  sd.nav.get_collision_geometry(participant_id),
  'collision geometry unavailable')
local runtime = sd.runtime.get_multiplayer_state() or {{}}
local bot = assert(sd.bots.get_state(participant_id), 'bot missing')
local radius = tonumber(geometry.observer_radius) or 0
local padding =
  tonumber(geometry.participant_collision_padding) or 0
local clearance_indexes =
  {{{','.join(str(value) for value in clearance_indexes)}}}
local patch_indexes =
  {{{','.join(str(value) for value in patch_indexes)}}}
local directions = {{
  {{1, 0}}, {{0.7071067811865476, 0.7071067811865476}},
  {{0, 1}}, {{-0.7071067811865476, 0.7071067811865476}},
  {{-1, 0}}, {{-0.7071067811865476, -0.7071067811865476}},
  {{0, -1}}, {{0.7071067811865476, -0.7071067811865476}},
}}
local radii = {{}}
for _, row in ipairs(geometry.participant_radii or {{}}) do
  if row.radius_resolved == true then
    radii[tostring(row.participant_id)] =
      tonumber(row.radius) or radius
  end
end
local participants = {{}}
for _, row in ipairs(runtime.participants or {{}}) do
  if tonumber(row.participant_id) ~= participant_id and
      row.in_run == true and
      (tonumber(row.life_current) or 0) > 0 then
    participants[#participants + 1] = {{
      x = tonumber(row.x) or 0,
      y = tonumber(row.y) or 0,
      radius =
        (radii[tostring(row.participant_id)] or radius) + padding,
    }}
  end
end
local function segment_distance_sq(x, y, ax, ay, bx, by)
  local dx, dy = bx - ax, by - ay
  local length = dx * dx + dy * dy
  if length <= 0.0000001 then
    return (x - ax) ^ 2 + (y - ay) ^ 2
  end
  local t = math.max(0, math.min(1,
    ((x - ax) * dx + (y - ay) * dy) / length))
  local px, py = ax + dx * t, ay + dy * t
  return (x - px) ^ 2 + (y - py) ^ 2
end
local function inside_polygon(x, y, points)
  local inside = false
  local previous = points[#points]
  for _, point in ipairs(points) do
    if ((point.y > y) ~= (previous.y > y)) and
        x < (previous.x - point.x) * (y - point.y) /
          (previous.y - point.y) + point.x then
      inside = not inside
    end
    previous = point
  end
  return inside
end
local function polygon_blocked(x, y, points)
  if #points < 3 then return false end
  if inside_polygon(x, y, points) then return true end
  local previous = points[#points]
  for _, point in ipairs(points) do
    if segment_distance_sq(
        x, y, previous.x, previous.y, point.x, point.y) <=
        radius * radius then
      return true
    end
    previous = point
  end
  return false
end
local function walkable(x, y)
  for _, row in ipairs(geometry.circles or {{}}) do
    if row.path_blocks == true then
      local combined = radius + (tonumber(row.radius) or 0)
      if (x - row.x) ^ 2 + (y - row.y) ^ 2 <=
          combined * combined then
        return false
      end
    end
  end
  for _, row in ipairs(geometry.segments or {{}}) do
    if row.path_blocks == true and
        segment_distance_sq(
          x, y, row.start_x, row.start_y, row.end_x, row.end_y) <=
          radius * radius then
      return false
    end
  end
  for _, row in ipairs(geometry.polygons or {{}}) do
    if row.path_blocks == true and
        polygon_blocked(x, y, row.points or {{}}) then
      return false
    end
  end
  for _, row in ipairs(participants) do
    local combined = radius + row.radius
    if (x - row.x) ^ 2 + (y - row.y) ^ 2 <=
        combined * combined then
      return false
    end
  end
  return true
end
local bx, by = tonumber(bot.x) or 0, tonumber(bot.y) or 0
local patch_samples, patch_mismatches = 0, 0
local patch_index = 1
for row = -3, 3 do
  for column = -3, 3 do
    if row ~= 0 or column ~= 0 then
      local x, y = bx + column * 60, by + row * 60
      local predicted = walkable(x, y)
      local observed = observation[patch_indexes[patch_index]] == 1
      patch_samples = patch_samples + 1
      if predicted ~= observed then
        patch_mismatches = patch_mismatches + 1
      end
      patch_index = patch_index + 1
    end
  end
end
local ray_samples, ray_mismatches = 0, 0
for direction_index, direction in ipairs(directions) do
  local expected = 480
  for distance = 60, 480, 60 do
    local x = bx + direction[1] * distance
    local y = by + direction[2] * distance
    local predicted = walkable(x, y)
    if expected == 480 and not predicted then expected = distance end
    ray_samples = ray_samples + 1
  end
  local observed =
    (tonumber(observation[clearance_indexes[direction_index]]) or 0) * 480
  if math.abs(observed - expected) > 0.001 then
    ray_mismatches = ray_mismatches + 1
  end
end
print('geometry_valid=' .. tostring(geometry.valid == true))
print('refresh_pending=' .. tostring(geometry.refresh_pending == true))
print('observer_radius=' .. tostring(radius))
print('circle_count=' .. tostring(#(geometry.circles or {{}})))
print('segment_count=' .. tostring(#(geometry.segments or {{}})))
print('polygon_count=' .. tostring(#(geometry.polygons or {{}})))
print('self_walkable=' .. tostring(sd.nav.test_segment(bx, by, bx, by)))
print('patch_samples=' .. tostring(patch_samples))
print('patch_mismatches=' .. tostring(patch_mismatches))
print('ray_samples=' .. tostring(ray_samples))
print('ray_mismatches=' .. tostring(ray_mismatches))
""",
            timeout=30.0,
        )
    )
    if (
        values.get("geometry_valid") != "true"
        or values.get("refresh_pending") != "false"
        or values.get("self_walkable") != "true"
        or (
            _integer(values, "circle_count")
            + _integer(values, "segment_count")
            + _integer(values, "polygon_count")
        )
        <= 0
        or _integer(values, "patch_samples") != 48
        or _integer(values, "patch_mismatches") != 0
        or _integer(values, "ray_samples") != 64
        or _integer(values, "ray_mismatches") != 0
    ):
        raise BridgeError(f"exact-geometry spot audit failed: {values}")
    return {
        "observer_radius": _finite(values, "observer_radius"),
        "primitive_counts": {
            "circles": _integer(values, "circle_count"),
            "segments": _integer(values, "segment_count"),
            "polygons": _integer(values, "polygon_count"),
        },
        "patch_samples": _integer(values, "patch_samples"),
        "patch_mismatches": 0,
        "ray_samples": _integer(values, "ray_samples"),
        "ray_mismatches": 0,
        "self_walkable": True,
    }


def _obstacle_reactive_policy(
    source: BotPolicy,
    movement_action: int,
    obstacle_slot: int = 1,
) -> BotPolicy:
    if obstacle_slot < 1 or obstacle_slot > spec.OBSTACLE_SLOT_COUNT:
        raise ValueError("obstacle_slot is outside the policy-v3 block")
    policy = _forced_policy(
        source,
        movement_action=0,
        target_action=0,
        ability_action=0,
        aim_action=0,
    )
    policy.input_weight.fill(0.0)
    policy.input_bias.fill(0.0)
    policy.hidden_weight.fill(0.0)
    policy.hidden_bias.fill(0.0)
    policy.movement_weight.fill(0.0)
    policy.movement_bias.fill(-10.0)
    feature = spec.OBSERVATION_NAMES.index(
        f"obstacle_{obstacle_slot}_present"
    )
    policy.input_weight[0, feature] = 8.0
    policy.input_bias[0] = -4.0
    policy.hidden_weight[0, 0] = 4.0
    policy.movement_weight[0, 0] = -8.0
    policy.movement_weight[movement_action, 0] = 8.0
    return policy


def _run_small_obstacle_clearance_check(
    session: SoloSession,
    policy: BotPolicy,
    participant_id: int,
    *,
    timeout: float,
) -> dict[str, object]:
    selected = local_sync.parse_key_values(
        session.lua(
            f"""
local participant_id = {participant_id}
local geometry = assert(
  sd.nav.get_collision_geometry(participant_id),
  'collision geometry unavailable')
local grid = assert(sd.nav.get_grid(4), 'nav grid unavailable')
assert(
  grid.refresh_pending == false and
  tonumber(grid.subdivisions) == 4,
  'four-subdivision v2 grid unavailable')
local bot = assert(sd.bots.get_state(participant_id), 'bot missing')
local root = rawget(_G, 'bot_brain_debug') or {{}}
local debug = (root.bots or {{}})[1] or {{}}
local radius = tonumber(geometry.observer_radius) or 0
local endpoint_only_distance = radius * 2 + 0.51
local sample_width = grid.cell_width / grid.subdivisions
local sample_height = grid.cell_height / grid.subdivisions
local walkability = {{}}
local columns = grid.height * grid.subdivisions
for _, cell in ipairs(grid.cells or {{}}) do
  for _, sample in ipairs(cell.samples or {{}}) do
    local row = cell.grid_x * grid.subdivisions + sample.sample_x
    local column = cell.grid_y * grid.subdivisions + sample.sample_y
    walkability[row * columns + column + 1] =
      sample.traversable == true
  end
end
local function old_grid_open(x, y)
  local column = math.floor(x / sample_width)
  local row = math.floor(y / sample_height)
  if row < 0 or column < 0 then return false end
  return walkability[row * columns + column + 1] == true
end
local directions = {{
  {{dx=-1, dy=0, action=5}},
  {{dx=1, dy=0, action=1}},
  {{dx=0, dy=-1, action=7}},
  {{dx=0, dy=1, action=3}},
  {{dx=0.7071067811865476, dy=0.7071067811865476, action=2}},
  {{dx=-0.7071067811865476, dy=0.7071067811865476, action=4}},
  {{dx=-0.7071067811865476, dy=-0.7071067811865476, action=6}},
  {{dx=0.7071067811865476, dy=-0.7071067811865476, action=8}},
}}
local radial_fractions = {{0, 0.25, 0.5, 0.75, 0.95}}
local circles = {{}}
for _, circle in ipairs(geometry.circles or {{}}) do
  circles[tostring(circle.geometry_id or '')] = circle
end
local selected = nil
for slot, obstacle in ipairs(debug.policy_obstacles or {{}}) do
  if selected == nil and slot <= {spec.OBSTACLE_SLOT_COUNT} and
      obstacle.kind == 'circle' and
      obstacle.is_participant ~= true and
      (tonumber(obstacle.radius) or 0) > 0 and
      (tonumber(obstacle.radius) or 0) <= 30 then
    local id = tostring(obstacle.geometry_id or '')
    local circle = circles[id]
    if circle ~= nil and circle.path_blocks == true then
      local miss = nil
      for _, direction in ipairs(directions) do
        for _, fraction in ipairs(radial_fractions) do
          local blocked_distance =
            (radius + circle.radius) * fraction
          local miss_x =
            circle.x + direction.dx * blocked_distance
          local miss_y =
            circle.y + direction.dy * blocked_distance
          local native_open = sd.nav.test_segment(
            miss_x - endpoint_only_distance,
            miss_y,
            miss_x,
            miss_y)
          if old_grid_open(miss_x, miss_y) and
              native_open == false then
            miss = {{x=miss_x, y=miss_y}}
            break
          end
        end
        if miss ~= nil then break end
      end
      if miss ~= nil then
        local movement = nil
        local movement_score = -math.huge
        for _, direction in ipairs(directions) do
          local legal =
            (debug.policy_movement_mask or {{}})[
              direction.action + 1] == true
          local score =
            direction.dx * (tonumber(obstacle.normal_dx) or 0) +
            direction.dy * (tonumber(obstacle.normal_dy) or 0)
          if legal and score > movement_score then
            movement = direction
            movement_score = score
          end
        end
        if movement ~= nil and movement_score > 0.5 then
          selected = {{
            id=id,
            slot=slot,
            radius=circle.radius,
            x=circle.x,
            y=circle.y,
            bot_x=bot.x,
            bot_y=bot.y,
            miss_x=miss.x,
            miss_y=miss.y,
            action=movement.action,
            movement_score=movement_score,
            clearance=obstacle.clearance,
          }}
        end
      end
    end
  end
end
print('ok=' .. tostring(selected ~= nil))
print('geometry_id=' .. tostring(selected and selected.id or ''))
print('slot=' .. tostring(selected and selected.slot or 0))
print('radius=' .. tostring(selected and selected.radius or 0))
print('clearance=' .. tostring(selected and selected.clearance or 0))
print('circle_x=' .. tostring(selected and selected.x or 0))
print('circle_y=' .. tostring(selected and selected.y or 0))
print('bot_x=' .. tostring(selected and selected.bot_x or 0))
print('bot_y=' .. tostring(selected and selected.bot_y or 0))
print('miss_x=' .. tostring(selected and selected.miss_x or 0))
print('miss_y=' .. tostring(selected and selected.miss_y or 0))
print('movement_action=' .. tostring(selected and selected.action or 0))
print('movement_score=' .. tostring(
  selected and selected.movement_score or 0))
print('v2_grid_open=' .. tostring(
  selected ~= nil and
    old_grid_open(selected.miss_x, selected.miss_y)))
print('native_miss_walkable=' .. tostring(
  selected ~= nil and
    sd.nav.test_segment(
      selected.miss_x - endpoint_only_distance,
      selected.miss_y,
      selected.miss_x,
      selected.miss_y)))
""",
            timeout=30.0,
        )
    )
    if (
        selected.get("ok") != "true"
        or selected.get("v2_grid_open") != "true"
        or selected.get("native_miss_walkable") != "false"
        or not selected.get("geometry_id")
        or not 1
        <= _integer(selected, "slot")
        <= spec.OBSTACLE_SLOT_COUNT
        or _finite(selected, "radius") <= 0.0
        or _finite(selected, "radius") > 30.0
        or _finite(selected, "movement_score") <= 0.5
    ):
        raise BridgeError(
            "no currently observed exact small primitive also exhibits the "
            f"v2 grid miss: {selected}"
        )
    movement_action = _integer(selected, "movement_action")
    geometry_id = selected["geometry_id"]
    obstacle_slot = _integer(selected, "slot")
    _validate_contract(_telemetry(session))
    before = (
        _finite(selected, "bot_x"),
        _finite(selected, "bot_y"),
    )
    generation = session.load_policy(
        _obstacle_reactive_policy(
            policy,
            movement_action,
            obstacle_slot,
        )
    )
    cleared = _wait_for(
        session,
        lambda value: (
            _integer(value, "exact_obstacle_clearance_accepted") > 0
            and _integer(value, "policy_movement_action")
            == movement_action
        ),
        timeout=timeout,
        label="exact small-obstacle clearance response",
    )
    _validate_contract(cleared)
    log_line = _find_runtime_log_line(
        session,
        "policy exact-obstacle clearance accepted geometry_id="
        f"{geometry_id}",
    )
    center = (
        _finite(selected, "circle_x"),
        _finite(selected, "circle_y"),
    )
    distance_before = math.hypot(
        before[0] - center[0],
        before[1] - center[1],
    )
    deadline = time.monotonic() + timeout
    after = before
    distance_after = distance_before
    while time.monotonic() < deadline:
        after_values = local_sync.parse_key_values(
            session.lua(
                f"""
local bot = assert(sd.bots.get_state({participant_id}), 'bot missing')
print('x=' .. tostring(bot.x or 0))
print('y=' .. tostring(bot.y or 0))
"""
            )
        )
        after = (
            _finite(after_values, "x"),
            _finite(after_values, "y"),
        )
        distance_after = math.hypot(
            after[0] - center[0],
            after[1] - center[1],
        )
        if distance_after > distance_before + MINIMUM_LIVE_DISPLACEMENT:
            break
        time.sleep(0.05)
    if distance_after <= distance_before + MINIMUM_LIVE_DISPLACEMENT:
        raise BridgeError(
            "learned movement did not increase small-obstacle clearance: "
            f"{distance_before}->{distance_after}"
        )
    return {
        "geometry_id": geometry_id,
        "radius": _finite(selected, "radius"),
        "clearance": _finite(selected, "clearance"),
        "v2_grid_open": True,
        "native_miss_walkable": False,
        "v2_missed_point": [
            _finite(selected, "miss_x"),
            _finite(selected, "miss_y"),
        ],
        "movement_action": movement_action,
        "movement_name": spec.MOVEMENT_ACTION_NAMES[movement_action],
        "observation_slot": obstacle_slot,
        "distance_before": distance_before,
        "distance_after": distance_after,
        "policy_generation": generation,
        "log_line": log_line,
    }


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


def _potion_inventory_snapshot(
    session: SoloSession,
    participant_id: int,
    subtype: int,
) -> dict[str, str]:
    return local_sync.parse_key_values(
        session.lua(
            f"""
local details =
  sd.bots.get_inventory_details({participant_id}) or {{}}
local count = 0
for _, row in ipairs(details.potions or {{}}) do
  if tonumber(row.stock_subtype) == {subtype} and
      tonumber(row.content_id) == 0 then
    count = count + (tonumber(row.count) or 0)
  end
end
local bot = sd.bots.get_state({participant_id}) or {{}}
local runtime = sd.runtime.get_multiplayer_state() or {{}}
local runtime_hp, runtime_mp = -1, -1
for _, row in ipairs(runtime.participants or {{}}) do
  if tonumber(row.participant_id) == {participant_id} then
    runtime_hp = tonumber(row.life_current) or -1
    runtime_mp = tonumber(row.mana_current) or -1
  end
end
print('count=' .. tostring(count))
print('revision=' .. tostring(details.inventory_revision or 0))
print('hp=' .. tostring(bot.hp or 0))
print('max_hp=' .. tostring(bot.max_hp or 0))
print('mp=' .. tostring(bot.mp or 0))
print('max_mp=' .. tostring(bot.max_mp or 0))
print('runtime_hp=' .. tostring(runtime_hp))
print('runtime_mp=' .. tostring(runtime_mp))
"""
        )
    )


def _spawn_and_pick_up_potion(
    session: SoloSession,
    participant_id: int,
    subtype: int,
) -> dict[str, object]:
    time.sleep(0.75)
    before = _potion_inventory_snapshot(
        session,
        participant_id,
        subtype,
    )
    before_ids = {
        int(value)
        for key, value in local_sync.parse_key_values(
            session.lua(
                """
for index, row in ipairs(
    (sd.world.get_replicated_loot() or {}).drops or {}) do
  if row.active == true then
    print('drop.' .. tostring(index) .. '=' ..
      tostring(row.network_drop_id or 0))
  end
end
"""
            )
        ).items()
        if key.startswith("drop.") and int(value) > 0
    }
    spawned = local_sync.parse_key_values(
        session.lua(
            f"""
local bot = assert(sd.bots.get_state({participant_id}), 'bot missing')
local ok, error_message = sd.world.spawn_reward({{
  kind='potion{subtype}', amount=1,
  x=tonumber(bot.x) or 0, y=tonumber(bot.y) or 0,
}})
print('ok=' .. tostring(ok == true))
print('error=' .. tostring(error_message or ''))
"""
        )
    )
    if spawned.get("ok") != "true":
        raise BridgeError(
            f"stock potion{subtype} spawn failed: {spawned}"
        )
    drop_id = 0
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        values = local_sync.parse_key_values(
            session.lua(
                f"""
for index, row in ipairs(
    (sd.world.get_replicated_loot() or {{}}).drops or {{}}) do
  if row.active == true and
      tonumber(row.item_type_id) == 7001 and
      tonumber(row.item_slot) == {subtype} then
    print('drop.' .. tostring(index) .. '=' ..
      tostring(row.network_drop_id or 0))
  end
end
"""
            )
        )
        candidates = {
            int(value)
            for value in values.values()
            if int(value) > 0 and int(value) not in before_ids
        }
        if candidates:
            drop_id = min(candidates)
            break
        time.sleep(0.05)
    if drop_id <= 0:
        raise BridgeError(
            f"stock potion{subtype} did not enter replicated loot"
        )
    pickup = local_sync.parse_key_values(
        session.lua(
            f"""
local ok, sequence_or_error =
  sd.world.request_loot_pickup({drop_id}, {participant_id})
print('ok=' .. tostring(ok == true))
print('sequence=' .. tostring(
  type(sequence_or_error) == 'number' and sequence_or_error or 0))
print('error=' .. tostring(
  type(sequence_or_error) == 'string' and sequence_or_error or ''))
"""
        )
    )
    deadline = time.monotonic() + 15.0
    after = before
    while time.monotonic() < deadline:
        after = _potion_inventory_snapshot(
            session,
            participant_id,
            subtype,
        )
        if (
            _integer(after, "count") == _integer(before, "count") + 1
            and _integer(after, "revision")
            > _integer(before, "revision")
        ):
            break
        time.sleep(0.05)
    if (
        _integer(after, "count") != _integer(before, "count") + 1
        or _integer(after, "revision") <= _integer(before, "revision")
    ):
        raise BridgeError(
            f"stock potion{subtype} pickup did not reach the synthetic "
            f"inventory: before={before} after={after} pickup={pickup}"
        )
    return {
        "subtype": subtype,
        "drop_id": drop_id,
        "pickup_sequence": _integer(pickup, "sequence"),
        "count_before": _integer(before, "count"),
        "count_after": _integer(after, "count"),
        "revision_before": _integer(before, "revision"),
        "revision_after": _integer(after, "revision"),
    }


def _wait_for_potion_resources(
    session: SoloSession,
    participant_id: int,
    subtype: int,
    predicate,
    *,
    timeout: float,
    label: str,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = _potion_inventory_snapshot(
            session,
            participant_id,
            subtype,
        )
        if predicate(last):
            return last
        time.sleep(0.05)
    raise BridgeError(f"{label} timed out: {last}")


def _stage_potion_deficit_if_present(
    session: SoloSession,
    participant_id: int,
    subtype: int,
) -> dict[str, str]:
    values = local_sync.parse_key_values(
        session.lua(
            f"""
local participant_id = {participant_id}
local subtype = {subtype}
local details =
  sd.bots.get_inventory_details(participant_id) or {{}}
local count = 0
for _, row in ipairs(details.potions or {{}}) do
  if tonumber(row.stock_subtype) == subtype and
      tonumber(row.content_id) == 0 then
    count = count + (tonumber(row.count) or 0)
  end
end
local state = sd.bots.get_state(participant_id) or {{}}
local progression =
  tonumber(state.progression_runtime_state_address) or 0
local hp_offset = assert(sd.debug.layout_offset('progression_hp'))
local max_hp_offset = assert(
  sd.debug.layout_offset('progression_max_hp'))
local mp_offset = assert(sd.debug.layout_offset('progression_mp'))
local max_mp_offset = assert(
  sd.debug.layout_offset('progression_max_mp'))
local max_hp = progression > 0 and
  (tonumber(sd.debug.read_float(
    progression + max_hp_offset)) or 0) or 0
local max_mp = progression > 0 and
  (tonumber(sd.debug.read_float(
    progression + max_mp_offset)) or 0) or 0
local staged = count > 0 and progression > 0 and
  max_hp > 0 and max_mp > 0
if staged and (subtype == 0 or subtype == 5) then
  staged = sd.debug.write_float(
    progression + hp_offset, max_hp * 0.25) and staged
end
if staged and (subtype == 1 or subtype == 5) then
  staged = sd.debug.write_float(
    progression + mp_offset, max_mp * 0.25) and staged
end
print('staged=' .. tostring(staged == true))
print('count=' .. tostring(count))
print('revision=' .. tostring(details.inventory_revision or 0))
print('max_hp=' .. tostring(max_hp))
print('max_mp=' .. tostring(max_mp))
"""
        )
    )
    if _integer(values, "count") > 0 and values.get("staged") != "true":
        raise BridgeError(f"potion deficit staging failed: {values}")
    return values


def _potion_slots(values: dict[str, str]) -> dict[int, tuple[int, int, bool]]:
    result: dict[int, tuple[int, int, bool]] = {}
    for encoded in values.get("potion_rows", "").split(","):
        if not encoded:
            continue
        fields = encoded.split(":")
        if len(fields) != 4:
            raise BridgeError(f"invalid potion row telemetry: {encoded!r}")
        slot, subtype, count = map(int, fields[:3])
        result[subtype] = (slot, count, fields[3] == "true")
    return result


def _run_potion_action_checks(
    session: SoloSession,
    policy: BotPolicy,
    participant_id: int,
    *,
    timeout: float,
) -> dict[str, object]:
    supported_results: dict[str, object] = {}
    accepted_total = _integer(
        _telemetry(session),
        "potion_use_accepted",
    )
    for subtype, name in (
        (0, "Health"),
        (1, "Mana"),
        (5, "Rejuvenation"),
    ):
        pickup = _spawn_and_pick_up_potion(
            session,
            participant_id,
            subtype,
        )
        ready = _wait_for(
            session,
            lambda value: (
                subtype in _potion_slots(value)
                and _potion_slots(value)[subtype][1] > 0
            ),
            timeout=timeout,
            label=f"{name} policy inventory observation",
        )
        _validate_contract(ready)
        slot, count_before, legal = _potion_slots(ready)[subtype]
        revision_before = _integer(ready, "inventory_revision")
        generation = session.load_policy(
            _forced_policy(
                policy,
                movement_action=0,
                target_action=0,
                ability_action=slot + 9,
                aim_action=0,
            )
        )
        used: dict[str, str] = {}
        staging_attempts = 0
        staged: dict[str, str] = {}
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            staged = _stage_potion_deficit_if_present(
                session,
                participant_id,
                subtype,
            )
            if staged.get("staged") == "true":
                staging_attempts += 1
            used = _telemetry(session)
            if (
                _integer(used, "potion_use_accepted")
                == accepted_total + 1
                and _integer(used, "last_potion_slot") == slot
                and _integer(used, "last_potion_use_id") > 0
            ):
                break
            time.sleep(0.01)
        if (
            _integer(used, "potion_use_accepted")
            != accepted_total + 1
            or _integer(used, "last_potion_slot") != slot
            or _integer(used, "last_potion_use_id") <= 0
        ):
            raise BridgeError(
                f"{name} learned policy action timed out: "
                f"staging_attempts={staging_attempts} telemetry={used}"
            )
        _validate_contract(used)
        accepted_total += 1
        use_id = _integer(used, "last_potion_use_id")
        after = _wait_for_potion_resources(
            session,
            participant_id,
            subtype,
            lambda value: (
                _integer(value, "count") == count_before - 1
                and _integer(value, "revision") == revision_before + 1
                and (
                    subtype not in (0, 5)
                    or math.isclose(
                        _finite(value, "hp"),
                        _finite(value, "max_hp"),
                        abs_tol=0.02,
                    )
                )
                and (
                    subtype not in (1, 5)
                    or math.isclose(
                        _finite(value, "mp"),
                        _finite(value, "max_mp"),
                        abs_tol=0.02,
                    )
                )
                and math.isclose(
                    _finite(value, "runtime_hp"),
                    _finite(value, "hp"),
                    abs_tol=0.02,
                )
                and math.isclose(
                    _finite(value, "runtime_mp"),
                    _finite(value, "mp"),
                    abs_tol=0.02,
                )
            ),
            timeout=timeout,
            label=f"{name} replicated exactly-once effect",
        )
        if (
            _integer(after, "count") != count_before - 1
            or _integer(after, "revision") != revision_before + 1
        ):
            raise BridgeError(
                f"{name} stack/revision transition was not exactly once: "
                f"ready={ready} after={after}"
            )
        max_hp = _finite(after, "max_hp")
        max_mp = _finite(after, "max_mp")
        if subtype in (0, 5) and not math.isclose(
            _finite(after, "hp"), max_hp, abs_tol=0.02
        ):
            raise BridgeError(f"{name} did not restore HP: {after}")
        if subtype in (1, 5) and not math.isclose(
            _finite(after, "mp"), max_mp, abs_tol=0.02
        ):
            raise BridgeError(f"{name} did not restore mana: {after}")
        if (
            not math.isclose(
                _finite(after, "runtime_hp"),
                _finite(after, "hp"),
                abs_tol=0.02,
            )
            or not math.isclose(
                _finite(after, "runtime_mp"),
                _finite(after, "mp"),
                abs_tol=0.02,
            )
        ):
            raise BridgeError(f"{name} vitals were not replicated: {after}")
        time.sleep(0.5)
        stable = _telemetry(session)
        if (
            _integer(stable, "potion_use_accepted") != accepted_total
            or _integer(stable, "last_potion_use_id") != use_id
        ):
            raise BridgeError(f"{name} use credit repeated: {stable}")
        supported_results[name] = {
            "subtype": subtype,
            "slot": slot,
            "pickup": pickup,
            "initially_legal": legal,
            "staging_attempts": staging_attempts,
            "staged_max_hp": _finite(staged, "max_hp"),
            "staged_max_mp": _finite(staged, "max_mp"),
            "count_before": count_before,
            "count_after": _integer(after, "count"),
            "revision_before": revision_before,
            "revision_after": _integer(after, "revision"),
            "hp_after": _finite(after, "hp"),
            "mp_after": _finite(after, "mp"),
            "use_id": use_id,
            "policy_generation": generation,
            "log_line": _find_runtime_log_line(
                session,
                f"policy potion accepted slot={slot} use_id={use_id}",
            ),
        }

    unsupported: dict[str, object] = {}
    for subtype, name in (
        (2, "Wizard Chug"),
        (3, "Antidote"),
        (4, "Mind Chug"),
    ):
        pickup = _spawn_and_pick_up_potion(
            session,
            participant_id,
            subtype,
        )
        observed = _wait_for(
            session,
            lambda value: (
                subtype in _potion_slots(value)
                and _potion_slots(value)[subtype][1] > 0
            ),
            timeout=timeout,
            label=f"{name} observation-only potion row",
        )
        _validate_contract(observed)
        slot, count, legal = _potion_slots(observed)[subtype]
        action = slot + 9
        if legal or observed["ability_mask"][action] != "0":
            raise BridgeError(
                f"{name} was not permanently action-masked: {observed}"
            )
        before_accepted = _integer(
            observed,
            "potion_use_accepted",
        )
        generation = session.load_policy(
            _forced_policy(
                policy,
                movement_action=0,
                target_action=0,
                ability_action=action,
                aim_action=0,
            )
        )
        masked = _wait_for(
            session,
            lambda value: (
                _integer(value, "policy_generation") == generation
                and _integer(value, "policy_ability_action") != action
            ),
            timeout=timeout,
            label=f"{name} permanent action mask",
        )
        if _integer(masked, "potion_use_accepted") != before_accepted:
            raise BridgeError(f"{name} masked action mutated inventory")
        unsupported[name] = {
            "subtype": subtype,
            "slot": slot,
            "count": count,
            "action_masked": True,
            "pickup": pickup,
            "policy_generation": generation,
        }
    return {
        "supported": supported_results,
        "permanently_masked": unsupported,
        "accepted_total": accepted_total,
    }


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


def _find_runtime_log_line(
    session: SoloSession,
    token: str,
) -> str:
    log_path = (
        session.stage_root
        / ".sdmod"
        / "logs"
        / "solomondarkmodloader.log"
    )
    if not log_path.is_file():
        raise BridgeError(f"runtime log is unavailable: {log_path}")
    matches = [
        line
        for line in log_path.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()
        if token in line
    ]
    if not matches:
        raise BridgeError(
            f"runtime log contains no {token!r} evidence"
        )
    return matches[-1]


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
        element="ether",
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
                ability_action=0,
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
                _integer(value, "observation_count")
                == len(spec.OBSERVATION_NAMES)
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


def _verify_homing_center_mask(
    args: argparse.Namespace,
    policy: BotPolicy,
    instance: str,
) -> dict[str, object]:
    solo = TeamComposition("solo-homing", 1, ())
    session = SoloSession(
        instance=f"{instance[:38]}-homing",
        game_directory=Path(args.game_directory),
        launcher_path=Path(args.launcher_path),
        runtime_root=Path(args.runtime_root),
        local_port=args.local_port + 40,
        unused_remote_port=args.unused_remote_port + 40,
        max_participants=solo.participant_count + 1,
        headless=not args.visible,
        element="ether",
        discipline=args.discipline,
        multiplayer_transport=True,
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
                target_action=1,
                ability_action=0,
            )
        )
        homing_seed = args.seed % 0x3FFFFFFF + 1
        seed_round_trip = session.set_run_seed(homing_seed)
        session.enable_god_mode()
        session.start_test_run(timeout=args.startup_timeout)
        session.prepare_training_combat(timeout=args.startup_timeout)
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
        progression = session.prime_learned_progression(
            minimum_secondary_slots=0,
            timeout=args.startup_timeout,
        )
        actor = _spawn_enemy(
            session,
            offset_x=180.0,
            hp=10000.0,
            freeze_on_spawn=True,
        )
        targeted = _wait_for(
            session,
            lambda value: (
                _integer(value, "target_network_actor_id") > 0
                and _integer(value, "primary_build_id") == 8
                and value.get("ability_mask", "")[1:2] == "1"
            ),
            timeout=args.timeout,
            label="replicated Ether-primary target",
        )
        _validate_contract(targeted)
        center_generation = session.load_policy(
            _forced_policy(
                policy,
                movement_action=0,
                target_action=1,
                ability_action=1,
                aim_action=8,
            )
        )
        center_mask = _wait_for(
            session,
            lambda value: (
                value.get("aim_mask") == "100000000"
                and _integer(value, "policy_aim_action") == 0
                and _integer(value, "center_mask_cast_accepted") > 0
            ),
            timeout=args.timeout,
            label="homing Ether primary center-only aim mask",
        )
        _validate_contract(center_mask)
        center_log = _find_runtime_log_line(
            session,
            "policy center-mask cast accepted",
        )
        _retire_enemy(session, actor)
        return {
            "instance": session.instance,
            "process_id": launch.get("processId"),
            "seed_round_trip": seed_round_trip,
            "layout_sha256": session.layout_sha256(),
            "primary_build_id": _integer(
                center_mask,
                "primary_build_id",
            ),
            "aim_mask": center_mask["aim_mask"],
            "selected_aim_action": _integer(
                center_mask,
                "policy_aim_action",
            ),
            "policy_generation": center_generation,
            "progression": progression,
            "log_line": center_log,
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
    homing_center = _verify_homing_center_mask(
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
            ability_action=0,
        )
        generation = session.load_policy(setup_policy)
        seed_round_trip = session.set_run_seed(args.seed)
        procedural_layout = _select_procedural_survival_layout(session)
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
                _integer(value, "observation_count")
                == len(spec.OBSERVATION_NAMES)
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

        geometry_ready = _wait_for_collision_geometry(
            session,
            participant_id,
            timeout=args.timeout,
        )
        geometry_fidelity = _run_geometry_spot_audit(
            session,
            participant_id,
        )
        small_obstacle = _run_small_obstacle_clearance_check(
            session,
            policy,
            participant_id,
            timeout=args.timeout,
        )
        lead_and_status = _run_lead_and_status_check(
            session,
            policy,
            timeout=args.timeout,
        )
        hazard_dodge = _run_hazard_dodge_check(
            session,
            policy,
            participant_id,
            timeout=args.timeout,
        )

        weld = _apply_one_weld(
            session,
            participant_id,
            policy,
            seed=args.seed + 1,
        )
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
        secondary_enemy = _spawn_enemy(
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
        ability_mask = target_ready.get("ability_mask", "")
        secondary_slot = next(
            (
                slot
                for slot in range(1, 9)
                if len(ability_mask) > slot + 1
                and ability_mask[slot + 1] == "1"
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
            ability_action=secondary_slot + 1,
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
                and _integer(value, "ability_mask_mismatches") == 0
                and _integer(value, "aim_mask_mismatches") == 0
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
            ability_action=0,
        )
        persistence_generation = session.load_policy(
            persistence_policy
        )
        resort_enemy = _spawn_enemy(
            session,
            offset_x=80.0,
            hp=10000.0,
        )
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
            ability_action=0,
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

        _retire_enemy(session, secondary_enemy)
        _retire_enemy(session, resort_enemy)
        combat_cleanup = _retire_all_tracked_enemies(
            session,
            timeout=args.timeout,
        )
        _wait_for(
            session,
            lambda value: _integer(
                value,
                "target_network_actor_id",
            )
            == 0,
            timeout=args.timeout,
            label="combat isolation before potion actions",
        )
        potion_actions = _run_potion_action_checks(
            session,
            policy,
            participant_id,
            timeout=args.timeout,
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
            "policy hazard dodge accepted",
            "policy exact-obstacle clearance accepted",
            "policy lead cast accepted",
            "policy skill choice accepted mode=learned",
            "policy potion accepted",
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
            "procedural_layout": procedural_layout,
            "observed_run_nonce": run_identity["run_nonce"],
            "layout_sha256": session.layout_sha256(),
            "offline_solo": offline_solo,
            "homing_center_mask": homing_center,
            "policy_generations": [
                generation,
                small_obstacle["policy_generation"],
                lead_and_status["policy_generation"],
                hazard_dodge["policy_generation"],
                weld["policy_generation"],
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
                "ability": "exact-target-and-inventory-conditioned-match",
                "aim": "exact-family-conditioned-match",
            },
            "geometry_fidelity": geometry_fidelity,
            "geometry_ready": geometry_ready,
            "small_obstacle_clearance": small_obstacle,
            "enemy_status_and_lead": lead_and_status,
            "hazard_dodge": hazard_dodge,
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
            "potion_actions": potion_actions,
            "pre_potion_combat_cleanup": combat_cleanup,
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
            "last_ability": gameplay.get("policy_ability_name"),
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
