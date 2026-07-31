#!/usr/bin/env python3
"""Unattended wave-five acceptance for the synthetic-participant bot brain."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import multiplayer_frame_capture
import verify_local_multiplayer_sync as local_sync


ROOT = Path(__file__).resolve().parents[1]
GAME_DIRECTORY = Path(
    "/mnt/c/Users/User/Documents/GitHub/SB Modding/"
    "Solomon Dark/SolomonDarkAbandonware"
)
EVIDENCE_ROOT = Path(
    "/mnt/d/codex-evidence/bot-players-20260726/phase3"
)
INSTANCE_PREFIX = "bot"
HOST_PORT = 48811
CLIENT_PORT = 48812
HOST_PIPE = "SolomonDarkModLoader_LuaExec_bot-host"
CLIENT_PIPE = "SolomonDarkModLoader_LuaExec_bot-client"
EXACT_MOD_ID = "bot.brain"
BOT_NAME = "Ember"
DEFAULT_RUN_COUNT = 3
DEFAULT_RUN_TIMEOUT_SECONDS = 900.0
SAMPLE_INTERVAL_SECONDS = 1.0
TIMELINE_INTERVAL_SECONDS = 2.0
WAVE_FIVE_STABILITY_SECONDS = 2.0
BOT_DEATH_CONFIRMATION_SECONDS = 2.0
BOT_ARENA_SEPARATION_DISTANCE = 600.0
ARENA_TRANSITION_TIMEOUT_SECONDS = 180.0


class BotBrainAcceptanceFailure(RuntimeError):
    pass


def _number(
    values: dict[str, str],
    key: str,
    default: float = 0.0,
) -> float:
    try:
        return float(values.get(key, str(default)))
    except (TypeError, ValueError):
        return default


def _integer(
    values: dict[str, str],
    key: str,
    default: int = 0,
) -> int:
    value = values.get(key)
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


PAIR_PROBE = """
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end

local scene = sd.world.get_scene()
emit("scene", scene and (scene.name or scene.kind) or "")
emit("authority", sd.state.is_authority())

local wave = sd.waves.get_state()
emit("wave.number", wave and wave.wave or 0)
emit("wave.phase", wave and wave.phase or "")
emit("wave.planned", wave and wave.planned or 0)
emit("wave.remaining", wave and wave.remaining_to_spawn or 0)
emit("wave.spawned", wave and wave.spawned or 0)
emit("wave.alive", wave and wave.alive or 0)
emit("wave.killed", wave and wave.killed or 0)

local bots = sd.bots.list() or {}
local bot = bots[1]
emit("bot.count", #bots)
emit("bot.found", bot ~= nil)
local participant_id = bot and tonumber(bot:participant_id()) or 0
emit("bot.participant_id", participant_id)
if bot ~= nil then
  local position_ok, x, y = pcall(function() return bot:position() end)
  local hp_ok, hp = pcall(function() return bot:hp() end)
  local max_hp_ok, max_hp = pcall(function() return bot:max_hp() end)
  local alive_ok, alive = pcall(function() return bot:alive() end)
  local slot_ok, slot = pcall(function() return bot:slot() end)
  emit("bot.position_ok", position_ok and x ~= nil and y ~= nil)
  emit("bot.x", x or 0)
  emit("bot.y", y or 0)
  emit("bot.hp_ok", hp_ok and hp ~= nil)
  emit("bot.hp", hp or 0)
  emit("bot.max_hp", max_hp_ok and max_hp or 0)
  emit("bot.alive", alive_ok and alive == true)
  emit("bot.slot", slot_ok and slot or -1)
end

local multiplayer = sd.runtime.get_multiplayer_state()
local local_participant_id = 0
local bot_member = nil
for _, participant in ipairs(multiplayer and multiplayer.participants or {}) do
  if participant.is_owner == true and
      tostring(participant.controller_kind or "") ~= "LuaBrain" then
    local_participant_id = tonumber(participant.participant_id) or 0
  end
  if tonumber(participant.participant_id) == participant_id then
    bot_member = participant
  end
end
emit("local.participant_id", local_participant_id)
local player = sd.player.get_state() or {}
emit("local.x", player.x or 0)
emit("local.y", player.y or 0)
emit("member.name", bot_member and bot_member.name or "")
emit("member.controller", bot_member and bot_member.controller_kind or "")
emit("member.in_run", bot_member and bot_member.in_run or false)
emit("member.level", bot_member and bot_member.level or 0)
emit("member.life", bot_member and bot_member.life_current or 0)
emit("member.max_life", bot_member and bot_member.life_max or 0)

local offer = multiplayer and multiplayer.active_level_up_offer or nil
emit("offer.valid", offer and offer.valid or false)
emit("offer.submitted", offer and offer.selection_submitted or false)
emit("offer.id", offer and offer.offer_id or 0)
emit("offer.target", offer and offer.target_participant_id or 0)
emit("offer.count", offer and offer.option_count or 0)
for index, option in ipairs(offer and offer.options or {}) do
  emit("offer.option." .. tostring(index), option.option_id or option.id or -1)
end

local snapshot = sd.world.get_replicated_actors()
local live_enemies = 0
local enemies_targeting_bot = 0
local status_resolved_enemies = 0
local telegraph_fields_present = 0
for _, actor in ipairs(snapshot and snapshot.actors or {}) do
  if actor.tracked_enemy == true and actor.dead ~= true and
      (tonumber(actor.hp) or 0) > 0.0 then
    live_enemies = live_enemies + 1
    if tonumber(actor.target_participant_id) == participant_id then
      enemies_targeting_bot = enemies_targeting_bot + 1
    end
    if actor.combat_status_resolved == true then
      status_resolved_enemies = status_resolved_enemies + 1
    end
    if actor.anim_drive_state ~= nil and actor.heading ~= nil then
      telegraph_fields_present = telegraph_fields_present + 1
    end
  end
end
emit("world.live_enemies", live_enemies)
emit("world.enemies_targeting_bot", enemies_targeting_bot)
emit("world.status_resolved_enemies", status_resolved_enemies)
emit("world.telegraph_fields_present", telegraph_fields_present)

local hazards = sd.world.get_replicated_hazards() or {}
emit("world.hazards_valid", hazards.valid == true)
emit("world.hazard_count", hazards.hazard_count or 0)
local geometry = participant_id > 0 and
  sd.nav.get_collision_geometry(participant_id) or nil
emit("nav.geometry_valid", geometry and geometry.valid == true)
emit("nav.refresh_pending",
  geometry and geometry.refresh_pending == true or false)
emit("nav.circle_count", geometry and #geometry.circles or 0)
emit("nav.segment_count", geometry and #geometry.segments or 0)
emit("nav.polygon_count", geometry and #geometry.polygons or 0)
local self_walkable = false
if bot ~= nil then
  local ok, x, y = pcall(function() return bot:position() end)
  local test_ok, accepted = pcall(
    sd.nav.test_segment,
    tonumber(x) or 0,
    tonumber(y) or 0,
    tonumber(x) or 0,
    tonumber(y) or 0)
  self_walkable = ok and test_ok and accepted == true
end
emit("nav.self_walkable", self_walkable)
local inventory = participant_id > 0 and
  sd.bots.get_inventory_details(participant_id) or nil
emit("inventory.valid", type(inventory) == "table")
emit("inventory.descriptors_resolved",
  inventory and inventory.descriptors_resolved == true)
emit("inventory.equipment_rows",
  inventory and #inventory.equipped or 0)
local forbidden_inventory_keys = 0
local function inspect_inventory(value, seen)
  if type(value) ~= "table" or seen[value] then return end
  seen[value] = true
  for key, child in pairs(value) do
    if type(key) == "string" then
      local lowered = string.lower(key)
      if string.find(lowered, "address", 1, true) or
          string.find(lowered, "pointer", 1, true) or
          string.find(lowered, "exception", 1, true) or
          string.find(lowered, "seh", 1, true) then
        forbidden_inventory_keys = forbidden_inventory_keys + 1
      end
    end
    inspect_inventory(child, seen)
  end
end
inspect_inventory(inventory, {})
emit("inventory.forbidden_keys", forbidden_inventory_keys)

local debug_state = rawget(_G, "bot_brain_debug")
local policy = type(debug_state) == "table" and
  debug_state.policy or {}
emit("policy.version", policy.version or 0)
emit("policy.architecture", policy.architecture or "")
emit("policy.observation_size", policy.observation_size or 0)
emit("policy.hidden_1",
  type(policy.hidden_sizes) == "table" and
    policy.hidden_sizes[1] or 0)
emit("policy.hidden_2",
  type(policy.hidden_sizes) == "table" and
    policy.hidden_sizes[2] or 0)
emit("policy.movement_actions",
  policy.movement_action_size or 0)
emit("policy.target_actions",
  policy.target_action_size or 0)
emit("policy.ability_actions",
  policy.ability_action_size or 0)
emit("policy.aim_actions",
  policy.aim_action_size or 0)
emit("policy.option_descriptor_size",
  policy.option_descriptor_size or 0)
emit("policy.choice_hidden_size",
  policy.choice_hidden_size or 0)
for _, key in ipairs({
  "authority",
  "active",
  "participant_id",
  "wave",
  "mode",
  "hp",
  "max_hp",
  "live_enemy_count",
  "threat_count",
  "target_network_actor_id",
  "target_distance",
  "think_count",
  "move_issued",
  "move_accepted",
  "movement_candidates_blocked",
  "cast_issued",
  "cast_accepted",
  "skill_choices_accepted",
  "kite_path_distance",
  "arena_grid_backed",
  "nearest_threat_distance",
  "edge_pressure",
  "destination_x",
  "destination_y",
  "last_error"
}) do
  emit("brain." .. key, type(debug_state) == "table" and debug_state[key] or "")
end
"""


def _query(pipe_name: str) -> dict[str, str]:
    return local_sync.parse_key_values(
        local_sync.lua(pipe_name, PAIR_PROBE, timeout=10.0)
    )


def _wait(
    probe,
    predicate,
    *,
    timeout: float,
    label: str,
    interval: float = 0.25,
):
    deadline = time.monotonic() + timeout
    last: Any = None
    last_error = ""
    while time.monotonic() < deadline:
        try:
            last = probe()
            last_error = ""
            if predicate(last):
                return last
        except (
            BotBrainAcceptanceFailure,
            local_sync.VerifyFailure,
            TimeoutError,
        ) as exc:
            last_error = str(exc)
        time.sleep(interval)
    detail = f" last={last!r}"
    if last_error:
        detail += f" error={last_error}"
    raise BotBrainAcceptanceFailure(f"{label} timed out.{detail}")


def _pair_bot_ready(
    views: dict[str, dict[str, str]],
    *,
    expected_scene: str,
) -> bool:
    host = views["host"]
    client = views["client"]
    participant_id = _integer(host, "bot.participant_id")
    return (
        host.get("scene") == expected_scene
        and client.get("scene") == expected_scene
        and host.get("authority") == "true"
        and client.get("authority") == "false"
        and _integer(host, "bot.count") == 1
        and _integer(client, "bot.count") == 1
        and participant_id > 0
        and _integer(client, "bot.participant_id") == participant_id
        and host.get("bot.position_ok") == "true"
        and client.get("bot.position_ok") == "true"
        and host.get("bot.hp_ok") == "true"
        and client.get("bot.hp_ok") == "true"
        and host.get("bot.alive") == "true"
        and client.get("bot.alive") == "true"
        and _integer(host, "bot.slot", -1) >= 1
        and _integer(client, "bot.slot", -1) >= 1
        and host.get("member.name") == BOT_NAME
        and client.get("member.name") == BOT_NAME
        and host.get("member.controller") == "LuaBrain"
        and client.get("member.controller") == "LuaBrain"
        and _integer(host, "policy.version") == 3
        and _integer(client, "policy.version") == 3
        and host.get("policy.architecture")
        == "mlp-tanh-four-head-v3"
        and client.get("policy.architecture")
        == "mlp-tanh-four-head-v3"
        and _integer(host, "policy.observation_size") == 1279
        and _integer(client, "policy.observation_size") == 1279
        and _integer(host, "policy.hidden_1") == 512
        and _integer(host, "policy.hidden_2") == 256
        and _integer(host, "policy.movement_actions") == 9
        and _integer(host, "policy.target_actions") == 9
        and _integer(host, "policy.ability_actions") == 22
        and _integer(host, "policy.aim_actions") == 9
        and _integer(host, "policy.option_descriptor_size") == 56
        and _integer(host, "policy.choice_hidden_size") == 128
        and _integer(client, "policy.option_descriptor_size") == 56
        and _integer(client, "policy.choice_hidden_size") == 128
    )


def _start_testrun() -> None:
    last_error = ""
    for _ in range(60):
        try:
            local_sync.start_testrun(HOST_PIPE)
            return
        except local_sync.VerifyFailure as exc:
            last_error = str(exc)
            if "still settling" not in last_error:
                raise
            time.sleep(0.25)
    raise BotBrainAcceptanceFailure(
        f"host could not enter the test run: {last_error}"
    )


SCRIPTED_PRIMARY_PRIME = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value))
end

local primary_entry = 16
local maximum_level_steps = 64
local elemental_primaries = {
  [8] = true,
  [16] = true,
  [24] = true,
  [32] = true,
  [40] = true,
}
local level_offset = assert(
  sd.debug.layout_offset("progression_level"))
local next_xp_offset = assert(
  sd.debug.layout_offset("progression_next_xp_threshold"))
local bot = (sd.bots.list() or {})[1]
if bot == nil then
  emit("ready", false)
  emit("error", "bot handle unavailable")
  return
end

local participant_id = tonumber(bot:participant_id()) or 0
local state = sd.bots.get_state(participant_id) or {}
local progression =
  tonumber(state.progression_runtime_state_address) or 0
local player = sd.player.get_state() or {}
local source_progression =
  tonumber(player.progression_address) or 0
if participant_id <= 0 or progression == 0 or
    source_progression == 0 then
  emit("ready", false)
  emit("error", "native progression is not materialized")
  return
end

local applied_choices = 0
local matched_primary = false
local last_error = ""
local function primary_details()
  local details =
    sd.bots.get_loadout_details(participant_id) or {}
  local primary = details.primary or {}
  local ready =
    primary.mana_cost_resolved == true and
    (tonumber(primary.mana_cost) or 0) > 0 and
    primary.range_resolved == true and
    (tonumber(primary.range_max) or 0) > 0
  return primary, ready
end

local function apply_pending_choice()
  local choices =
    sd.bots.get_skill_choices(participant_id) or {}
  if choices.pending ~= true or
      type(choices.options) ~= "table" or
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
      local option_id = tonumber(option.id) or -1
      if elemental_primaries[option_id] ~= true and
          option_id ~= 52 then
        selected_index = index
        break
      end
    end
  end
  if selected_index == nil then
    return false
  end

  local ok, accepted = pcall(
    sd.bots.choose_skill,
    participant_id,
    selected_index,
    tonumber(choices.generation) or 0)
  if not ok or accepted ~= true then
    last_error = "native skill choice apply failed"
    return false
  end
  applied_choices = applied_choices + 1
  return true
end

local primary, ready = primary_details()
matched_primary =
  tonumber(primary.entry_id) == primary_entry
local level_steps = 0
while not ready and level_steps < maximum_level_steps do
  apply_pending_choice()
  primary, ready = primary_details()
  if ready then
    break
  end

  local level =
    tonumber(sd.debug.read_i32(
      progression + level_offset)) or 0
  local next_xp =
    tonumber(sd.debug.read_float(
      progression + next_xp_offset)) or 0
  if level <= 0 or next_xp <= 0 or next_xp ~= next_xp then
    last_error = "native level or next-xp is invalid"
    break
  end
  local ok, synced = pcall(
    sd.bots.debug_sync_level_up,
    {
      level = level + 1,
      experience = math.ceil(next_xp + 10.0),
      source_progression_address = source_progression,
    })
  if not ok or synced ~= true then
    last_error = "native level-up sync failed"
    break
  end
  level_steps = level_steps + 1
  apply_pending_choice()
  primary, ready = primary_details()
end

emit("ready", ready)
emit("participant_id", participant_id)
emit("primary_entry", primary_entry)
emit("level_steps", level_steps)
emit("applied_choices", applied_choices)
emit("matched_primary", matched_primary)
emit("mana_cost_resolved",
  primary.mana_cost_resolved == true)
emit("mana_cost", tonumber(primary.mana_cost) or 0)
emit("range_resolved", primary.range_resolved == true)
emit("range_max", tonumber(primary.range_max) or 0)
emit("error", ready and "" or
  (last_error ~= "" and last_error or
   "primary spell did not become available"))
"""


SCRIPTED_BOT_GOD_MODE = r"""
local hp_offset = assert(
  sd.debug.layout_offset('progression_hp'))
local max_hp_offset = assert(
  sd.debug.layout_offset('progression_max_hp'))
local mp_offset = assert(
  sd.debug.layout_offset('progression_mp'))
local max_mp_offset = assert(
  sd.debug.layout_offset('progression_max_mp'))

local function sustain()
  local applied = 0
  for _, bot in ipairs(sd.bots.list() or {}) do
    local state = sd.bots.get_participant_state(
      bot:participant_id()) or {}
    local progression = tonumber(
      state.progression_runtime_state_address) or 0
    if progression > 0 then
      local max_hp = tonumber(sd.debug.read_float(
        progression + max_hp_offset)) or 0
      local max_mp = tonumber(sd.debug.read_float(
        progression + max_mp_offset)) or 0
      if max_hp > 0 then
        sd.debug.write_float(progression + hp_offset, max_hp)
      end
      if max_mp > 0 then
        sd.debug.write_float(progression + mp_offset, max_mp)
      end
      applied = applied + 1
    end
  end
  return applied
end
if not _G.__sdmod_bot_brain_acceptance_godmode then
  sd.events.on('runtime.tick', function()
    sustain()
  end)
  _G.__sdmod_bot_brain_acceptance_godmode = true
end
print('registered=true')
print('initial_apply=' .. tostring(sustain()))
"""


def _prime_scripted_primary() -> dict[str, str]:
    values = local_sync.parse_key_values(
        local_sync.lua(
            HOST_PIPE,
            SCRIPTED_PRIMARY_PRIME,
            timeout=30.0,
        )
    )
    if (
        values.get("ready") != "true"
        or values.get("matched_primary") != "true"
        or _number(values, "mana_cost") <= 0.0
        or _number(values, "range_max") <= 0.0
    ):
        raise BotBrainAcceptanceFailure(
            f"could not prime the scripted bot primary: {values}"
        )
    return values


def _enable_scripted_bot_god_mode() -> dict[str, dict[str, str]]:
    results: dict[str, dict[str, str]] = {}
    for role, pipe_name in (
        ("host", HOST_PIPE),
        ("client", CLIENT_PIPE),
    ):
        values = local_sync.parse_key_values(
            local_sync.lua(
                pipe_name,
                SCRIPTED_BOT_GOD_MODE,
                timeout=10.0,
            )
        )
        if (
            values.get("registered") != "true"
            or _integer(values, "initial_apply") < 1
        ):
            raise BotBrainAcceptanceFailure(
                f"could not protect the {role} scripted bot replica: "
                f"{values}"
            )
        results[role] = values
    return results


def _finite_position(
    values: dict[str, str],
    prefix: str,
) -> tuple[float, float]:
    position = (
        _number(values, f"{prefix}.x", math.nan),
        _number(values, f"{prefix}.y", math.nan),
    )
    if not all(math.isfinite(value) for value in position):
        raise BotBrainAcceptanceFailure(
            f"{prefix} position is not finite: {values}"
        )
    return position


def _prepare_stock_arena(
    run_views: dict[str, dict[str, str]],
) -> dict[str, Any]:
    entry_player = _finite_position(run_views["host"], "local")
    entry_participant_id = _integer(
        run_views["host"],
        "bot.participant_id",
    )
    transitioned = _wait(
        lambda: {
            "host": _query(HOST_PIPE),
            "client": _query(CLIENT_PIPE),
        },
        lambda views: (
            _integer(views["host"], "wave.number") >= 1
            and _integer(views["host"], "world.live_enemies") > 0
        ),
        timeout=ARENA_TRANSITION_TIMEOUT_SECONDS,
        label="stock arena wave activation",
        interval=0.5,
    )
    player_position = _finite_position(transitioned["host"], "local")
    bot_position = _finite_position(transitioned["host"], "bot")
    separation_before = _distance(player_position, bot_position)
    respawned = separation_before > BOT_ARENA_SEPARATION_DISTANCE
    action: dict[str, str] | None = None
    ready = transitioned
    if respawned:
        action = local_sync.parse_key_values(
            local_sync.lua(
                HOST_PIPE,
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
            raise BotBrainAcceptanceFailure(
                f"could not respawn the roster in the stock arena: {action}"
            )
        ready = _wait(
            lambda: {
                "host": _query(HOST_PIPE),
                "client": _query(CLIENT_PIPE),
            },
            lambda views: (
                _pair_bot_ready(
                    views,
                    expected_scene="testrun",
                )
                and _integer(
                    views["host"],
                    "bot.participant_id",
                )
                != entry_participant_id
            ),
            timeout=30.0,
            label="respawned bot brain participant in the stock arena",
        )

    final_player = _finite_position(ready["host"], "local")
    final_bot = _finite_position(ready["host"], "bot")
    separation_after = _distance(final_player, final_bot)
    if separation_after > BOT_ARENA_SEPARATION_DISTANCE:
        raise BotBrainAcceptanceFailure(
            "bot remained outside the stock arena after roster "
            f"materialization: separation={separation_after}"
        )
    return {
        "entryPlayer": {
            "x": entry_player[0],
            "y": entry_player[1],
        },
        "arenaPlayer": {
            "x": player_position[0],
            "y": player_position[1],
        },
        "playerTransitionDistance": _distance(
            entry_player,
            player_position,
        ),
        "botParticipantIdBefore": entry_participant_id,
        "botParticipantIdAfter": _integer(
            ready["host"],
            "bot.participant_id",
        ),
        "botSeparationBefore": separation_before,
        "botSeparationAfter": separation_after,
        "respawned": respawned,
        "respawnAction": action,
    }


def _resolve_local_offer(
    pipe_name: str,
    values: dict[str, str],
    resolved: set[tuple[str, int]],
) -> dict[str, Any] | None:
    if (
        values.get("offer.valid") != "true"
        or values.get("offer.submitted") == "true"
    ):
        return None
    offer_id = _integer(values, "offer.id")
    option_count = _integer(values, "offer.count")
    local_participant_id = _integer(values, "local.participant_id")
    target_participant_id = _integer(values, "offer.target")
    key = (pipe_name, offer_id)
    if (
        offer_id <= 0
        or option_count <= 0
        or local_participant_id <= 0
        or target_participant_id != local_participant_id
        or key in resolved
    ):
        return None

    priority = (64, 16, 18, 17)
    option_ids = [
        _integer(values, f"offer.option.{index}", -1)
        for index in range(1, option_count + 1)
    ]
    option_index = 1
    for wanted in priority:
        if wanted in option_ids:
            option_index = option_ids.index(wanted) + 1
            break
    code = f"""
local ok, result = pcall(
  sd.runtime.choose_level_up_option,
  {{offer_id={offer_id}, option_index={option_index}}})
print("pcall_ok=" .. tostring(ok))
print("result=" .. tostring(result))
"""
    response = local_sync.parse_key_values(
        local_sync.lua(pipe_name, code, timeout=7.5)
    )
    if (
        response.get("pcall_ok") != "true"
        or response.get("result") != "true"
    ):
        return {
            "offerId": offer_id,
            "targetParticipantId": target_participant_id,
            "optionIds": option_ids,
            "optionIndex": option_index,
            "accepted": False,
            "response": response,
        }
    resolved.add(key)
    return {
        "offerId": offer_id,
        "targetParticipantId": target_participant_id,
        "optionIds": option_ids,
        "optionIndex": option_index,
        "selectedOptionId": option_ids[option_index - 1],
        "accepted": True,
        "response": response,
    }


def _distance(
    first: tuple[float, float],
    second: tuple[float, float],
) -> float:
    return math.hypot(first[0] - second[0], first[1] - second[1])


def _compact_sample(
    elapsed_seconds: float,
    views: dict[str, dict[str, str]],
) -> dict[str, Any]:
    host = views["host"]
    client = views["client"]
    return {
        "elapsedSeconds": round(elapsed_seconds, 3),
        "wave": _integer(host, "wave.number"),
        "wavePhase": host.get("wave.phase", ""),
        "enemiesAlive": _integer(host, "world.live_enemies"),
        "enemiesTargetingBot": _integer(
            host,
            "world.enemies_targeting_bot",
        ),
        "bot": {
            "hp": _number(host, "bot.hp"),
            "maxHp": _number(host, "bot.max_hp"),
            "alive": host.get("bot.alive") == "true",
            "x": _number(host, "bot.x"),
            "y": _number(host, "bot.y"),
            "mode": host.get("brain.mode", ""),
        },
        "client": {
            "hp": _number(client, "bot.hp"),
            "alive": client.get("bot.alive") == "true",
            "x": _number(client, "bot.x"),
            "y": _number(client, "bot.y"),
        },
        "brain": {
            "castsIssued": _integer(host, "brain.cast_issued"),
            "castsAccepted": _integer(host, "brain.cast_accepted"),
            "movesAccepted": _integer(host, "brain.move_accepted"),
            "kitePathDistance": _number(
                host,
                "brain.kite_path_distance",
            ),
            "threatCount": _integer(host, "brain.threat_count"),
            "targetNetworkActorId": _integer(
                host,
                "brain.target_network_actor_id",
            ),
        },
    }


def _set_camera_focus(
    pipe_name: str,
    values: dict[str, str],
) -> dict[str, str]:
    x = _number(values, "bot.x", math.nan)
    y = _number(values, "bot.y", math.nan)
    if not math.isfinite(x) or not math.isfinite(y):
        raise BotBrainAcceptanceFailure(
            f"bot camera focus lacks a finite position on {pipe_name}"
        )
    response = local_sync.parse_key_values(
        local_sync.lua(
            pipe_name,
            f"""
local ok, result = pcall(sd.camera.set_focus, {x:.9f}, {y:.9f})
print("pcall_ok=" .. tostring(ok))
print("result=" .. tostring(result))
""",
            timeout=7.5,
        )
    )
    if (
        response.get("pcall_ok") != "true"
        or response.get("result") != "true"
    ):
        raise BotBrainAcceptanceFailure(
            f"bot camera focus failed on {pipe_name}: {response}"
        )
    return response


def _clear_camera_focus(pipe_name: str) -> dict[str, str]:
    return local_sync.parse_key_values(
        local_sync.lua(
            pipe_name,
            """
local ok, result = pcall(sd.camera.clear_focus)
print("pcall_ok=" .. tostring(ok))
print("result=" .. tostring(result))
""",
            timeout=7.5,
        )
    )


def _capture_bot_fight_views(
    output_directory: Path,
    views: dict[str, dict[str, str]],
    *,
    wave: int,
    elapsed_seconds: float,
) -> dict[str, Any]:
    focus: dict[str, dict[str, str]] = {}
    try:
        focus["host"] = _set_camera_focus(HOST_PIPE, views["host"])
        focus["client"] = _set_camera_focus(
            CLIENT_PIPE,
            views["client"],
        )
        time.sleep(0.35)
        host_capture = multiplayer_frame_capture.capture_game_backbuffer(
            HOST_PIPE,
            output_directory / f"host-wave{wave}-mid-fight.png",
        )
        client_capture = multiplayer_frame_capture.capture_game_backbuffer(
            CLIENT_PIPE,
            output_directory / f"client-wave{wave}-mid-fight.png",
        )
    finally:
        if "host" in focus:
            focus["hostClear"] = _clear_camera_focus(HOST_PIPE)
        if "client" in focus:
            focus["clientClear"] = _clear_camera_focus(CLIENT_PIPE)
    return {
        "wave": wave,
        "elapsedSeconds": round(elapsed_seconds, 3),
        "cameraFocus": focus,
        "host": host_capture,
        "client": client_capture,
    }


def _copy_runtime_evidence(
    output_directory: Path,
) -> dict[str, str]:
    copied: dict[str, str] = {}
    for role in ("host", "client"):
        stage_path = (
            ROOT
            / "runtime"
            / "instances"
            / f"{INSTANCE_PREFIX}-{role}"
            / "stage"
        )
        for relative, label in (
            (
                Path(".sdmod/logs/solomondarkmodloader.log"),
                f"{role}-solomondarkmodloader.log",
            ),
            (
                Path(".sdmod/startup-status.json"),
                f"{role}-startup-status.json",
            ),
            (
                Path(".sdmod/multiplayer-session-status.json"),
                f"{role}-multiplayer-session-status.json",
            ),
        ):
            source = stage_path / relative
            if not source.is_file():
                continue
            destination = output_directory / label
            shutil.copy2(source, destination)
            copied[label] = str(destination)
    return copied


def _brain_log_summary(output_directory: Path) -> dict[str, Any]:
    log_path = output_directory / "host-solomondarkmodloader.log"
    if not log_path.is_file():
        return {"available": False}
    text = log_path.read_text(encoding="utf-8", errors="replace")
    brain_lines = [
        line for line in text.splitlines() if "[bot-brain]" in line
    ]
    accepted_cast_lines = [
        line for line in brain_lines if "cast accepted count=" in line
    ]
    return {
        "available": True,
        "lineCount": len(brain_lines),
        "acceptedCastLineCount": len(accepted_cast_lines),
        "lastLines": brain_lines[-40:],
    }


def _monitor_run(
    output_directory: Path,
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    started = time.monotonic()
    last_timeline_sample = -TIMELINE_INTERVAL_SECONDS
    last_sample_position: tuple[float, float] | None = None
    harness_kite_distance = 0.0
    highest_wave = 0
    timeline: list[dict[str, Any]] = []
    offer_choices: list[dict[str, Any]] = []
    resolved_offers: set[tuple[str, int]] = set()
    screenshots: dict[str, Any] | None = None
    wave_five_since: float | None = None
    last_views: dict[str, dict[str, str]] = {}
    consecutive_query_failures = 0
    previous_cast_accepted = 0
    death_since: float | None = None
    maximum_status_resolved_enemies = 0
    maximum_telegraph_fields_present = 0
    maximum_hazard_count = 0
    v3_seams_seen = False

    while time.monotonic() - started < timeout_seconds:
        elapsed = time.monotonic() - started
        try:
            views = {
                "host": _query(HOST_PIPE),
                "client": _query(CLIENT_PIPE),
            }
            last_views = views
            consecutive_query_failures = 0
        except (local_sync.VerifyFailure, TimeoutError) as exc:
            consecutive_query_failures += 1
            if consecutive_query_failures >= 3:
                raise BotBrainAcceptanceFailure(
                    "pair stopped responding during autonomous run: "
                    f"{exc}"
                ) from exc
            time.sleep(SAMPLE_INTERVAL_SECONDS)
            continue

        for role, pipe_name in (
            ("host", HOST_PIPE),
            ("client", CLIENT_PIPE),
        ):
            choice = _resolve_local_offer(
                pipe_name,
                views[role],
                resolved_offers,
            )
            if choice is not None:
                choice["role"] = role
                choice["elapsedSeconds"] = round(elapsed, 3)
                offer_choices.append(choice)

        host = views["host"]
        client = views["client"]
        wave = _integer(host, "wave.number")
        cast_accepted = _integer(host, "brain.cast_accepted")
        cast_advanced = cast_accepted > previous_cast_accepted
        highest_wave = max(highest_wave, wave)
        maximum_status_resolved_enemies = max(
            maximum_status_resolved_enemies,
            _integer(host, "world.status_resolved_enemies"),
        )
        maximum_telegraph_fields_present = max(
            maximum_telegraph_fields_present,
            _integer(host, "world.telegraph_fields_present"),
        )
        maximum_hazard_count = max(
            maximum_hazard_count,
            _integer(host, "world.hazard_count"),
        )
        v3_seams_seen = v3_seams_seen or (
            host.get("world.hazards_valid") == "true"
            and host.get("nav.geometry_valid") == "true"
            and host.get("nav.refresh_pending") == "false"
            and host.get("nav.self_walkable") == "true"
            and _integer(host, "nav.circle_count") > 0
            and host.get("inventory.valid") == "true"
            and host.get("inventory.descriptors_resolved") == "true"
            and _integer(host, "inventory.equipment_rows") == 7
            and _integer(host, "inventory.forbidden_keys") == 0
        )
        host_position = (
            _number(host, "bot.x", math.nan),
            _number(host, "bot.y", math.nan),
        )
        if all(math.isfinite(value) for value in host_position):
            if last_sample_position is not None:
                step = _distance(last_sample_position, host_position)
                if step <= 350.0:
                    harness_kite_distance += step
            last_sample_position = host_position

        if elapsed - last_timeline_sample >= TIMELINE_INTERVAL_SECONDS:
            timeline.append(_compact_sample(elapsed, views))
            last_timeline_sample = elapsed

        host_hp = _number(host, "bot.hp")
        client_hp = _number(client, "bot.hp")
        death_observed = wave > 0 and (
            host_hp <= 0.0
            or client_hp <= 0.0
            or host.get("brain.mode") == "dead"
        )
        if death_observed:
            if death_since is None:
                death_since = time.monotonic()
        else:
            death_since = None
        if (
            death_since is not None
            and time.monotonic() - death_since
            >= BOT_DEATH_CONFIRMATION_SECONDS
        ):
            return {
                "success": False,
                "completionReason": "bot_died",
                "highestWaveReached": highest_wave,
                "botAliveAtWaveFive": False,
                "death": {
                    "wave": wave,
                    "hostHp": host_hp,
                    "clientHp": client_hp,
                    "liveEnemies": _integer(
                        host,
                        "world.live_enemies",
                    ),
                    "enemiesTargetingBot": _integer(
                        host,
                        "world.enemies_targeting_bot",
                    ),
                    "cause": (
                        "native bot HP reached zero during stock wave "
                        "combat"
                    ),
                },
                "timeline": timeline,
                "offerChoices": offer_choices,
                "harnessKitePathDistance": harness_kite_distance,
                "lastViews": last_views,
                "v3LiveMaxima": {
                    "statusResolvedEnemies": (
                        maximum_status_resolved_enemies
                    ),
                    "telegraphFieldsPresent": (
                        maximum_telegraph_fields_present
                    ),
                    "hazardCount": maximum_hazard_count,
                    "semanticSeamsSeen": v3_seams_seen,
                },
            }

        if (
            screenshots is None
            and wave >= 1
            and _integer(host, "world.live_enemies") > 0
            and host.get("bot.alive") == "true"
            and client.get("bot.alive") == "true"
            and cast_advanced
            and _integer(
                host,
                "brain.target_network_actor_id",
            ) > 0
        ):
            screenshots = _capture_bot_fight_views(
                output_directory,
                views,
                wave=wave,
                elapsed_seconds=elapsed,
            )

        bot_alive_at_wave_five = (
            wave >= 5
            and host.get("bot.alive") == "true"
            and client.get("bot.alive") == "true"
            and host_hp > 0.0
            and client_hp > 0.0
        )
        if bot_alive_at_wave_five:
            if wave_five_since is None:
                wave_five_since = time.monotonic()
            elif (
                time.monotonic() - wave_five_since
                >= WAVE_FIVE_STABILITY_SECONDS
            ):
                timeline.append(_compact_sample(elapsed, views))
                return {
                    "success": screenshots is not None,
                    "completionReason": (
                        "wave_five_reached_alive"
                        if screenshots is not None
                        else "wave_five_without_combat_visual"
                    ),
                    "highestWaveReached": highest_wave,
                    "botAliveAtWaveFive": True,
                    "timeline": timeline,
                    "offerChoices": offer_choices,
                    "screenshots": screenshots,
                    "harnessKitePathDistance": harness_kite_distance,
                    "lastViews": last_views,
                    "v3LiveMaxima": {
                        "statusResolvedEnemies": (
                            maximum_status_resolved_enemies
                        ),
                        "telegraphFieldsPresent": (
                            maximum_telegraph_fields_present
                        ),
                        "hazardCount": maximum_hazard_count,
                        "semanticSeamsSeen": v3_seams_seen,
                    },
                }
        else:
            wave_five_since = None

        previous_cast_accepted = cast_accepted
        time.sleep(SAMPLE_INTERVAL_SECONDS)

    return {
        "success": False,
        "completionReason": "timeout",
        "highestWaveReached": highest_wave,
        "botAliveAtWaveFive": False,
        "timeline": timeline,
        "offerChoices": offer_choices,
        "screenshots": screenshots,
        "harnessKitePathDistance": harness_kite_distance,
        "lastViews": last_views,
        "v3LiveMaxima": {
            "statusResolvedEnemies": maximum_status_resolved_enemies,
            "telegraphFieldsPresent": maximum_telegraph_fields_present,
            "hazardCount": maximum_hazard_count,
            "semanticSeamsSeen": v3_seams_seen,
        },
    }


def verify_one_run(
    run_index: int,
    *,
    output_directory: Path,
    game_directory: Path,
    launcher_path: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    output_directory.mkdir(parents=True, exist_ok=True)
    launch: dict[str, object] = {}
    result: dict[str, Any] = {
        "runId": f"bot-wave5-{run_index}",
        "runIndex": run_index,
        "startedUtc": _utc_now(),
        "instancePrefix": INSTANCE_PREFIX,
        "ports": {"host": HOST_PORT, "client": CLIENT_PORT},
        "exactModId": EXACT_MOD_ID,
        "audioExpectedDisabled": True,
        "waveSchedule": "retail staged data/wave.txt; no test override",
    }
    failure: BaseException | None = None
    try:
        launch = local_sync.launch_pair(
            instance_prefix=INSTANCE_PREFIX,
            host_port=HOST_PORT,
            client_port=CLIENT_PORT,
            temporary_host_profile=True,
            kill_existing=False,
            god_mode=True,
            exact_mod_id=EXACT_MOD_ID,
            launcher_path=launcher_path,
            game_directory=game_directory,
            enable_audio=False,
        )
        result["launch"] = launch
        if (
            launch.get("audioDisabled") is not True
            or int(launch.get("hostPort", 0)) != HOST_PORT
            or int(launch.get("clientPort", 0)) != CLIENT_PORT
            or launch.get("testWaveOverride") not in ("", None)
        ):
            raise BotBrainAcceptanceFailure(
                f"isolated retail-wave pair contract failed: {launch}"
            )

        hub_views = _wait(
            lambda: {
                "host": _query(HOST_PIPE),
                "client": _query(CLIENT_PIPE),
            },
            lambda values: _pair_bot_ready(
                values,
                expected_scene="hub",
            ),
            timeout=25.0,
            label="bot brain participant in the shared hub",
        )
        result["hub"] = hub_views

        _start_testrun()
        local_sync.wait_for_scene(
            HOST_PIPE,
            "testrun",
            timeout=45.0,
        )
        local_sync.wait_for_scene(
            CLIENT_PIPE,
            "testrun",
            timeout=45.0,
        )
        run_views = _wait(
            lambda: {
                "host": _query(HOST_PIPE),
                "client": _query(CLIENT_PIPE),
            },
            lambda values: _pair_bot_ready(
                values,
                expected_scene="testrun",
            ),
            timeout=25.0,
            label="bot brain participant in the shared run",
        )
        result["runEntry"] = run_views
        result["scriptedBotGodMode"] = (
            _enable_scripted_bot_god_mode()
        )

        start = local_sync.parse_key_values(
            local_sync.lua(
                HOST_PIPE,
                """
print("prelude=" ..
  tostring(sd.gameplay.enable_combat_prelude()))
print("waves=" ..
  tostring(sd.gameplay.start_waves()))
""",
                timeout=10.0,
            )
        )
        if (
            start.get("prelude") != "true"
            or start.get("waves") != "true"
        ):
            raise BotBrainAcceptanceFailure(
                f"stock waves did not start: {start}"
            )
        result["waveStart"] = start
        result["arenaTransition"] = _prepare_stock_arena(run_views)
        result["primaryPrime"] = _prime_scripted_primary()

        monitored = _monitor_run(
            output_directory,
            timeout_seconds=timeout_seconds,
        )
        result.update(monitored)
        v3_maxima = monitored.get("v3LiveMaxima", {})
        if (
            v3_maxima.get("semanticSeamsSeen") is not True
            or int(v3_maxima.get("statusResolvedEnemies", 0)) <= 0
            or int(v3_maxima.get("telegraphFieldsPresent", 0)) <= 0
        ):
            raise BotBrainAcceptanceFailure(
                "scripted run did not retain the v3 semantic nav/enemy/"
                f"inventory contract: {v3_maxima}"
            )
        if not monitored["success"]:
            raise BotBrainAcceptanceFailure(
                "autonomous run failed: "
                f"{monitored['completionReason']} "
                f"highest_wave={monitored['highestWaveReached']}"
            )
    except BaseException as exc:
        result["success"] = False
        result["error"] = f"{type(exc).__name__}: {exc}"
        failure = exc
    finally:
        result["finishedUtc"] = _utc_now()
        if launch:
            try:
                result["runtimeEvidence"] = _copy_runtime_evidence(
                    output_directory
                )
                result["brainLog"] = _brain_log_summary(
                    output_directory
                )
                if "lastViews" in result:
                    host = result["lastViews"]["host"]
                    result["castsIssued"] = _integer(
                        host,
                        "brain.cast_issued",
                    )
                    result["castsAccepted"] = _integer(
                        host,
                        "brain.cast_accepted",
                    )
                    result["kitePathDistance"] = _number(
                        host,
                        "brain.kite_path_distance",
                    )
                    result["botHpAtFinish"] = _number(
                        host,
                        "bot.hp",
                    )
            except BaseException as evidence_error:
                result["evidenceError"] = (
                    f"{type(evidence_error).__name__}: "
                    f"{evidence_error}"
                )
                if failure is None:
                    failure = evidence_error
                    result["success"] = False
            try:
                result["cleanup"] = (
                    local_sync.stop_exact_game_processes(launch)
                )
            except BaseException as cleanup_error:
                result["cleanupError"] = (
                    f"{type(cleanup_error).__name__}: "
                    f"{cleanup_error}"
                )
                if failure is None:
                    failure = cleanup_error
                    result["success"] = False

        result_path = output_directory / "result.json"
        result_path.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(
            f"RUN={run_index} SUCCESS={result.get('success')} "
            f"WAVE={result.get('highestWaveReached', 0)} "
            f"HP={result.get('botHpAtFinish', 0)} "
            f"RESULT={result_path}"
        )

    if failure is not None:
        raise failure
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--runs",
        type=int,
        default=DEFAULT_RUN_COUNT,
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_RUN_TIMEOUT_SECONDS,
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=EVIDENCE_ROOT,
    )
    parser.add_argument(
        "--game-dir",
        type=Path,
        default=GAME_DIRECTORY,
    )
    parser.add_argument(
        "--launcher",
        type=Path,
        default=ROOT / "dist/launcher/SolomonDarkModLauncher.exe",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.runs < 1:
        raise SystemExit("--runs must be positive")
    if args.timeout_seconds <= 0.0:
        raise SystemExit("--timeout-seconds must be positive")
    if not (args.game_dir / "SolomonDark.exe").is_file():
        raise SystemExit(
            f"source game directory is invalid: {args.game_dir}"
        )
    if not args.launcher.is_file():
        raise SystemExit(
            f"launcher does not exist: {args.launcher}"
        )

    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {
        "phase": "autonomous_wave_five",
        "startedUtc": _utc_now(),
        "requiredConsecutiveRuns": args.runs,
        "retailWaveSchedule": True,
        "runs": [],
        "success": False,
    }
    summary_path = args.evidence_dir / "result.json"
    try:
        for run_index in range(1, args.runs + 1):
            result = verify_one_run(
                run_index,
                output_directory=(
                    args.evidence_dir / f"run-{run_index}"
                ),
                game_directory=args.game_dir,
                launcher_path=args.launcher,
                timeout_seconds=args.timeout_seconds,
            )
            summary["runs"].append(
                {
                    "runId": result["runId"],
                    "result": str(
                        args.evidence_dir
                        / f"run-{run_index}"
                        / "result.json"
                    ),
                    "highestWaveReached": result[
                        "highestWaveReached"
                    ],
                    "botAliveAtWaveFive": result[
                        "botAliveAtWaveFive"
                    ],
                    "botHpAtFinish": result[
                        "botHpAtFinish"
                    ],
                    "castsIssued": result["castsIssued"],
                    "castsAccepted": result["castsAccepted"],
                    "kitePathDistance": result[
                        "kitePathDistance"
                    ],
                }
            )
        summary["success"] = (
            len(summary["runs"]) == args.runs
            and all(
                run["highestWaveReached"] >= 5
                and run["botAliveAtWaveFive"] is True
                for run in summary["runs"]
            )
        )
    except BaseException as exc:
        summary["error"] = f"{type(exc).__name__}: {exc}"
        summary["success"] = False
        raise
    finally:
        summary["finishedUtc"] = _utc_now()
        summary_path.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"SUMMARY={summary_path}")

    return 0 if summary["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
