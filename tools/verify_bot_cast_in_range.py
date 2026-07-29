#!/usr/bin/env python3
"""Verify per-cast target-distance and applied damage on a retail pair."""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import verify_bot_polish as pair


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE_ROOT = Path(
    "/mnt/d/codex-evidence/botcast-20260729/after"
)
HOST_PORT = 50411
CLIENT_PORT = 50412
INSTANCE_PREFIX = "botcast"
HOST_INSTANCE = f"{INSTANCE_PREFIX}-host"
CLIENT_INSTANCE = f"{INSTANCE_PREFIX}-client"
HOST_PIPE = f"SolomonDarkModLoader_LuaExec_{HOST_INSTANCE}"
CLIENT_PIPE = f"SolomonDarkModLoader_LuaExec_{CLIENT_INSTANCE}"
HOST_ID_TEXT = "0x200000000000BC01"
CLIENT_ID_TEXT = "0x200000000000BC02"
HOST_NAME = "Bot cast host"
CLIENT_NAME = "client B"
EXACT_MOD_ID = "bot.brain"
CAPACITY = 3
POLL_SECONDS = 4.0
SCENARIO_TIMEOUT_SECONDS = 150.0
CAST_DAMAGE_WINDOW_MS = 8_000
AUTHORIZED_DAMAGE_EDGE_WINDOW_MS = 1_000
RANGE_TOLERANCE = 0.25

LEGACY_WATER_ROSTER = [
    {
        "name": "Brook",
        "element": "water",
        "discipline": "skirmisher",
    }
]
FIRE_ROSTER = [
    {
        "name": "Ember",
        "element": "fire",
        "discipline": "arcane",
        "behavior": "skirmisher",
    }
]


class BotCastRangeFailure(RuntimeError):
    """Raised when a bot does not produce native applied-damage evidence."""


@dataclass(frozen=True)
class Scenario:
    key: str
    bot_name: str
    element: str
    roster: list[dict[str, str]]
    expected_range_source: str
    legacy_migration: bool = False


SCENARIOS = (
    Scenario(
        key="short-water",
        bot_name="Brook",
        element="water",
        roster=LEGACY_WATER_ROSTER,
        expected_range_source="native_frost_jet_query_range",
        legacy_migration=True,
    ),
    Scenario(
        key="long-fire",
        bot_name="Ember",
        element="fire",
        roster=FIRE_ROSTER,
        expected_range_source="native_selection_pursuit_range",
    ),
)


INSTALL_RECORDER = r"""
local recorder = {
  enabled = true,
  ticks = 0,
  ticks_with_enemies = 0,
  previous_hp = {},
  previous_casts = {},
  bots = {},
  casts = {},
  damage_edges = {},
}
rawset(_G, "__botcast_range_recorder", recorder)

local function distance(x1, y1, x2, y2)
  local dx = x2 - x1
  local dy = y2 - y1
  return math.sqrt(dx * dx + dy * dy)
end

local function bot_stats(id, row)
  local stats = recorder.bots[id]
  if stats == nil then
    stats = {
      id = id,
      name = tostring(row.name or ""),
      active_ticks = 0,
      approach_ticks = 0,
      outside_range_approach_ticks = 0,
      range_unavailable_ticks = 0,
      min_enemy_center_distance = math.huge,
      max_enemy_center_distance = 0.0,
      latest_range = 0.0,
      latest_range_source = "",
      modes = {},
    }
    recorder.bots[id] = stats
  end
  return stats
end

sd.events.on("runtime.tick", function(event)
  if recorder.enabled ~= true then return end
  local now_ms = tonumber(event and event.monotonic_milliseconds) or 0
  recorder.ticks = recorder.ticks + 1

  local snapshot = sd.world.get_replicated_actors() or {}
  local enemies = {}
  for _, actor in ipairs(snapshot.actors or {}) do
    if actor.tracked_enemy == true then
      local id = tonumber(actor.network_actor_id) or 0
      local hp = tonumber(actor.hp) or 0.0
      local previous_hp = recorder.previous_hp[id]
      if previous_hp ~= nil and hp < previous_hp - 0.001 and
          #recorder.damage_edges < 512 then
        table.insert(recorder.damage_edges, {
          now_ms = now_ms,
          target_network_actor_id = id,
          hp_before = previous_hp,
          hp_after = hp,
          damage = previous_hp - hp,
        })
      end
      recorder.previous_hp[id] = hp
      if actor.dead ~= true and hp > 0.0 then
        enemies[id] = actor
      end
    end
  end
  if next(enemies) ~= nil then
    recorder.ticks_with_enemies = recorder.ticks_with_enemies + 1
  end

  local debug = rawget(_G, "bot_brain_debug")
  for _, row in ipairs(debug and debug.bots or {}) do
    local id = tonumber(row.participant_id) or 0
    local participant =
      id > 0 and sd.bots.get_participant_state(id) or nil
    if id > 0 and participant ~= nil then
      local stats = bot_stats(id, row)
      if row.active == true then
        stats.active_ticks = stats.active_ticks + 1
      end
      local mode = tostring(row.mode or "")
      stats.modes[mode] = (stats.modes[mode] or 0) + 1
      if mode == "approach" then
        stats.approach_ticks = stats.approach_ticks + 1
      end

      local window_ok, window = pcall(
        sd.bots.get_primary_attack_window,
        id)
      local spell_range = 0.0
      local range_source = ""
      if window_ok and type(window) == "table" then
        spell_range = tonumber(window.max_range) or 0.0
        range_source = tostring(window.source or "")
      end
      if spell_range <= 0.0 then
        stats.range_unavailable_ticks =
          stats.range_unavailable_ticks + 1
      else
        stats.latest_range = spell_range
        stats.latest_range_source = range_source
      end

      local bot_x = tonumber(participant.x) or 0.0
      local bot_y = tonumber(participant.y) or 0.0
      local nearest_center = math.huge
      for _, enemy in pairs(enemies) do
        nearest_center = math.min(
          nearest_center,
          distance(
            bot_x,
            bot_y,
            tonumber(enemy.x) or 0.0,
            tonumber(enemy.y) or 0.0))
      end
      if nearest_center < math.huge then
        stats.min_enemy_center_distance =
          math.min(stats.min_enemy_center_distance, nearest_center)
        stats.max_enemy_center_distance =
          math.max(stats.max_enemy_center_distance, nearest_center)
        if mode == "approach" and spell_range > 0.0 and
            nearest_center > spell_range then
          stats.outside_range_approach_ticks =
            stats.outside_range_approach_ticks + 1
        end
      end

      local accepted = tonumber(row.cast_accepted) or 0
      local previous_casts = recorder.previous_casts[id] or 0
      if accepted > previous_casts then
        local target_id =
          tonumber(row.target_network_actor_id) or 0
        for accepted_count = previous_casts + 1, accepted do
          if #recorder.casts < 512 then
            table.insert(recorder.casts, {
              now_ms = now_ms,
              accepted_count = accepted_count,
              participant_id = id,
              target_network_actor_id = target_id,
              target_distance =
                tonumber(row.target_distance) or 0.0,
              spell_range = spell_range,
              range_source = range_source,
              mode = mode,
            })
          end
        end
      end
      recorder.previous_casts[id] = accepted
    end
  end
end)

print("installed=true")
"""


RECORDER_REPORT = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local recorder = rawget(_G, "__botcast_range_recorder") or {}
emit("tick_count", recorder.ticks or 0)
emit("ticks_with_enemies", recorder.ticks_with_enemies or 0)

local bot_index = 0
for _, stats in pairs(recorder.bots or {}) do
  bot_index = bot_index + 1
  local prefix = "bot." .. tostring(bot_index) .. "."
  emit(prefix .. "id", stats.id)
  emit(prefix .. "name", stats.name)
  emit(prefix .. "active_ticks", stats.active_ticks)
  emit(prefix .. "approach_ticks", stats.approach_ticks)
  emit(prefix .. "outside_range_approach_ticks",
    stats.outside_range_approach_ticks)
  emit(prefix .. "range_unavailable_ticks",
    stats.range_unavailable_ticks)
  emit(prefix .. "min_enemy_center_distance",
    stats.min_enemy_center_distance)
  emit(prefix .. "max_enemy_center_distance",
    stats.max_enemy_center_distance)
  emit(prefix .. "latest_range", stats.latest_range)
  emit(prefix .. "latest_range_source",
    stats.latest_range_source)
  local modes = {}
  for mode, count in pairs(stats.modes or {}) do
    table.insert(modes, tostring(mode) .. ":" .. tostring(count))
  end
  table.sort(modes)
  emit(prefix .. "modes", table.concat(modes, ","))
end
emit("bot_count", bot_index)

emit("cast_event_count", #(recorder.casts or {}))
for index, cast in ipairs(recorder.casts or {}) do
  local prefix = "cast." .. tostring(index) .. "."
  for _, key in ipairs({
    "now_ms",
    "accepted_count",
    "participant_id",
    "target_network_actor_id",
    "target_distance",
    "spell_range",
    "range_source",
    "mode",
  }) do
    emit(prefix .. key, cast[key])
  end
end

emit("damage_edge_count", #(recorder.damage_edges or {}))
for index, edge in ipairs(recorder.damage_edges or {}) do
  local prefix = "damage." .. tostring(index) .. "."
  for _, key in ipairs({
    "now_ms",
    "target_network_actor_id",
    "hp_before",
    "hp_after",
    "damage",
  }) do
    emit(prefix .. key, edge[key])
  end
end
"""


PROGRESS_REPORT = r"""
local recorder = rawget(_G, "__botcast_range_recorder") or {}
print("casts=" .. tostring(#(recorder.casts or {})))
print("damage_edges=" ..
  tostring(#(recorder.damage_edges or {})))
print("ticks_with_enemies=" ..
  tostring(recorder.ticks_with_enemies or 0))
local wave = sd.waves.get_state() or {}
print("wave=" .. tostring(wave.wave or 0))
print("phase=" .. tostring(wave.phase or ""))
"""

NATIVE_PROGRESSION_REPORT = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end

local participant_id = __PARTICIPANT_ID__
local bot = sd.bots.get_participant_state(participant_id)
local progression =
  tonumber(bot and bot.progression_runtime_state_address) or 0
local actor = tonumber(bot and bot.actor_address) or 0
emit("participant_id", participant_id)
emit("progression", progression)
emit("actor", actor)
if progression == 0 then return end

local function off(name)
  return sd.debug.layout_offset(name)
end

local table_address = tonumber(sd.debug.read_ptr(
  progression +
    off("standalone_wizard_progression_table_base"))) or 0
local table_count = tonumber(sd.debug.read_i32(
  progression +
    off("standalone_wizard_progression_table_count"))) or 0
emit("table_address", table_address)
emit("table_count", table_count)

local function emit_property(prefix, entry_index, property_name)
  emit(prefix .. ".entry_index", entry_index)
  emit(prefix .. ".property_name", property_name)
  if table_address == 0 or entry_index < 0 or
      entry_index >= table_count then
    emit(prefix .. ".available", false)
    return
  end

  local entry = table_address +
    entry_index *
      off("standalone_wizard_progression_entry_stride")
  local active = tonumber(sd.debug.read_u16(
    entry +
      off("standalone_wizard_progression_active_flag"))) or 0
  local visible = tonumber(sd.debug.read_u16(
    entry +
      off("standalone_wizard_progression_visible_flag"))) or 0
  local statbook = tonumber(sd.debug.read_ptr(
    entry +
      off("standalone_wizard_progression_entry_statbook"))) or 0
  emit(prefix .. ".active", active)
  emit(prefix .. ".visible", visible)
  emit(prefix .. ".statbook", statbook)
  if statbook == 0 then
    emit(prefix .. ".available", false)
    return
  end

  local property_list =
    statbook + off("statbook_numeric_property_list")
  local property_count = tonumber(sd.debug.read_i32(
    property_list + off("pointer_list_count"))) or 0
  local property_items = tonumber(sd.debug.read_ptr(
    property_list + off("pointer_list_items"))) or 0
  emit(prefix .. ".property_count", property_count)
  if property_count <= 0 or property_count > 64 or
      property_items == 0 then
    emit(prefix .. ".available", false)
    return
  end

  for index = 0, property_count - 1 do
    local wrapper = tonumber(
      sd.debug.read_ptr(property_items + index * 4)) or 0
    local property = wrapper ~= 0 and
      (tonumber(sd.debug.read_ptr(wrapper)) or 0) or 0
    if property ~= 0 then
      local name_data = tonumber(sd.debug.read_ptr(
        property + off("native_string_data"))) or 0
      local name_length = tonumber(sd.debug.read_i32(
        property + off("native_string_length"))) or 0
      local name = ""
      if name_data ~= 0 and name_length > 0 and
          name_length <= 128 then
        name = sd.debug.read_string(
          name_data,
          name_length + 1) or ""
        name = string.sub(name, 1, name_length)
      end
      if name == property_name then
        local values_address = tonumber(sd.debug.read_ptr(
          property +
            off("statbook_numeric_property_values"))) or 0
        local value_count = tonumber(sd.debug.read_i32(
          property +
            off("statbook_numeric_property_value_count"))) or 0
        emit(prefix .. ".value_count", value_count)
        if values_address == 0 or value_count <= 0 or
            value_count > 1024 then
          emit(prefix .. ".available", false)
          return
        end
        local resolved_rank =
          math.min(active, value_count - 1)
        emit(prefix .. ".resolved_rank", resolved_rank)
        emit(
          prefix .. ".value",
          sd.debug.read_float(
            values_address + resolved_rank * 4))
        emit(prefix .. ".available", true)
        return
      end
    end
  end
  emit(prefix .. ".available", false)
end

emit_property("water_damage", 0x20, "mDamage")
emit_property("water_mana", 0x20, "mManaCost")
emit_property("water_widen", 0x22, "mWiden")
if actor ~= 0 then
  emit(
    "actor_frost_jet_widen_range",
    sd.debug.read_float(actor + 0x290))
end
"""


def configure_pair(evidence_root: Path) -> None:
    pair.EVIDENCE_ROOT = evidence_root
    pair.RUNTIME_ROOT = evidence_root / "runtime"
    pair.AFTER_ROOT = evidence_root / "captures"
    pair.FLOW_ROOT = evidence_root / "flow"
    pair.INSTANCE_PREFIX = INSTANCE_PREFIX
    pair.HOST_INSTANCE = HOST_INSTANCE
    pair.CLIENT_INSTANCE = CLIENT_INSTANCE
    pair.HOST_PORT = HOST_PORT
    pair.CLIENT_PORT = CLIENT_PORT
    pair.HOST_ID_TEXT = HOST_ID_TEXT
    pair.CLIENT_ID_TEXT = CLIENT_ID_TEXT
    pair.HOST_ID = int(HOST_ID_TEXT, 16)
    pair.CLIENT_ID = int(CLIENT_ID_TEXT, 16)
    pair.HOST_PIPE = HOST_PIPE
    pair.CLIENT_PIPE = CLIENT_PIPE
    pair.HOST_NAME = HOST_NAME
    pair.CLIENT_NAME = CLIENT_NAME
    pair.EXACT_MOD_ID = EXACT_MOD_ID
    pair.CAPACITY = CAPACITY


def write_settings(
    instance: str,
    roster: list[dict[str, str]],
) -> None:
    pair.atomic_write_json(
        pair.settings_path(instance),
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


def report_rows(values: dict[str, str]) -> dict[str, Any]:
    bots: list[dict[str, Any]] = []
    for index in range(1, pair.integer(values, "bot_count") + 1):
        prefix = f"bot.{index}."
        bots.append(
            {
                "id": pair.integer(values, prefix + "id"),
                "name": values.get(prefix + "name", ""),
                "activeTicks": pair.integer(
                    values, prefix + "active_ticks"),
                "approachTicks": pair.integer(
                    values, prefix + "approach_ticks"),
                "outsideRangeApproachTicks": pair.integer(
                    values,
                    prefix + "outside_range_approach_ticks",
                ),
                "rangeUnavailableTicks": pair.integer(
                    values, prefix + "range_unavailable_ticks"),
                "minEnemyCenterDistance": pair.number(
                    values, prefix + "min_enemy_center_distance"),
                "maxEnemyCenterDistance": pair.number(
                    values, prefix + "max_enemy_center_distance"),
                "latestRange": pair.number(
                    values, prefix + "latest_range"),
                "latestRangeSource": values.get(
                    prefix + "latest_range_source", ""),
                "modes": values.get(prefix + "modes", ""),
            }
        )

    casts: list[dict[str, Any]] = []
    for index in range(
        1,
        pair.integer(values, "cast_event_count") + 1,
    ):
        prefix = f"cast.{index}."
        casts.append(
            {
                "nowMs": pair.integer(values, prefix + "now_ms"),
                "acceptedCount": pair.integer(
                    values, prefix + "accepted_count"),
                "participantId": pair.integer(
                    values, prefix + "participant_id"),
                "targetNetworkActorId": pair.integer(
                    values,
                    prefix + "target_network_actor_id",
                ),
                "targetDistance": pair.number(
                    values, prefix + "target_distance"),
                "spellRange": pair.number(
                    values, prefix + "spell_range"),
                "rangeSource": values.get(
                    prefix + "range_source", ""),
                "mode": values.get(prefix + "mode", ""),
            }
        )

    damage_edges: list[dict[str, Any]] = []
    for index in range(
        1,
        pair.integer(values, "damage_edge_count") + 1,
    ):
        prefix = f"damage.{index}."
        damage_edges.append(
            {
                "nowMs": pair.integer(values, prefix + "now_ms"),
                "targetNetworkActorId": pair.integer(
                    values,
                    prefix + "target_network_actor_id",
                ),
                "hpBefore": pair.number(
                    values, prefix + "hp_before"),
                "hpAfter": pair.number(
                    values, prefix + "hp_after"),
                "damage": pair.number(
                    values, prefix + "damage"),
            }
        )

    return {
        "tickCount": pair.integer(values, "tick_count"),
        "ticksWithEnemies": pair.integer(
            values, "ticks_with_enemies"),
        "bots": bots,
        "casts": casts,
        "damageEdges": damage_edges,
    }


def applied_damage_links(
    casts: list[dict[str, Any]],
    damage_edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    for edge_index, edge in enumerate(damage_edges):
        candidates = [
            (cast_index, cast)
            for cast_index, cast in enumerate(casts)
            if cast["targetNetworkActorId"] > 0
            and cast["targetNetworkActorId"]
            == edge["targetNetworkActorId"]
            and 0 <= edge["nowMs"] - cast["nowMs"]
            <= CAST_DAMAGE_WINDOW_MS
        ]
        if not candidates:
            continue
        cast_index, cast = max(
            candidates,
            key=lambda candidate: candidate[1]["nowMs"],
        )
        links.append(
            {
                "castIndex": cast_index,
                "damageEdgeIndex": edge_index,
                "targetNetworkActorId":
                    edge["targetNetworkActorId"],
                "elapsedMs": edge["nowMs"] - cast["nowMs"],
                "damage": edge["damage"],
            }
        )
    return links


def parse_authorized_fireball_damage(
    loader_log: str,
) -> list[dict[str, int]]:
    pattern = re.compile(
        r"host synthetic Fireball native damage authorized\. "
        r"monotonic_ms=(?P<now_ms>\d+) "
        r"participant_id=(?P<participant_id>\d+) "
        r"projectile_actor=0x[0-9A-Fa-f]+ "
        r"target_actor=0x[0-9A-Fa-f]+ "
        r"target_network_actor_id=(?P<target_id>\d+)"
    )
    return [
        {
            "nowMs": int(match.group("now_ms")),
            "participantId": int(
                match.group("participant_id")
            ),
            "targetNetworkActorId": int(
                match.group("target_id")
            ),
        }
        for match in pattern.finditer(loader_log)
    ]


def authorized_fireball_damage_links(
    casts: list[dict[str, Any]],
    damage_edges: list[dict[str, Any]],
    authorizations: list[dict[str, int]],
) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    for edge_index, edge in enumerate(damage_edges):
        candidates: list[
            tuple[int, dict[str, Any], dict[str, int]]
        ] = []
        for authorization in authorizations:
            if (
                authorization["targetNetworkActorId"] <= 0
                or authorization["targetNetworkActorId"]
                != edge["targetNetworkActorId"]
                or not (
                    0
                    <= edge["nowMs"] - authorization["nowMs"]
                    <= AUTHORIZED_DAMAGE_EDGE_WINDOW_MS
                )
            ):
                continue
            cast_candidates = [
                (cast_index, cast)
                for cast_index, cast in enumerate(casts)
                if (
                    cast["participantId"]
                    == authorization["participantId"]
                    and 0
                    <= authorization["nowMs"] - cast["nowMs"]
                    <= CAST_DAMAGE_WINDOW_MS
                )
            ]
            if not cast_candidates:
                continue
            cast_index, cast = max(
                cast_candidates,
                key=lambda candidate: candidate[1]["nowMs"],
            )
            candidates.append(
                (cast_index, cast, authorization)
            )
        if not candidates:
            continue
        cast_index, cast, authorization = max(
            candidates,
            key=lambda candidate: candidate[2]["nowMs"],
        )
        links.append(
            {
                "castIndex": cast_index,
                "damageEdgeIndex": edge_index,
                "aimedTargetNetworkActorId":
                    cast["targetNetworkActorId"],
                "targetNetworkActorId":
                    edge["targetNetworkActorId"],
                "authorizationMonotonicMs":
                    authorization["nowMs"],
                "elapsedFromAuthorizationMs":
                    edge["nowMs"] - authorization["nowMs"],
                "damage": edge["damage"],
            }
        )
    return links


def copy_runtime_artifacts(
    scenario_root: Path,
) -> dict[str, str]:
    destination = scenario_root / "runtime-evidence"
    destination.mkdir(parents=True, exist_ok=True)
    copied: dict[str, str] = {}
    for label, instance in (
        ("host", HOST_INSTANCE),
        ("client-b", CLIENT_INSTANCE),
    ):
        for relative, output_name in (
            (
                Path(".sdmod/logs/solomondarkmodloader.log"),
                f"{label}-loader.log",
            ),
            (
                Path(".sdmod/multiplayer-session-status.json"),
                f"{label}-session-status.json",
            ),
            (
                Path(f".sdmod/mod-settings/{EXACT_MOD_ID}.json"),
                f"{label}-settings.json",
            ),
            (
                Path(".sdmod/stage-report.json"),
                f"{label}-stage-report.json",
            ),
        ):
            source = pair.stage_root(instance) / relative
            if not source.is_file():
                continue
            target = destination / output_name
            shutil.copy2(source, target)
            copied[output_name] = str(target)
    for label, source in (
        ("retail-wave.txt", pair.GAME_ROOT / "data/wave.txt"),
        (
            "staged-wave.txt",
            pair.stage_root(HOST_INSTANCE) / "data/wave.txt",
        ),
    ):
        if source.is_file():
            target = destination / label
            shutil.copy2(source, target)
            copied[label] = str(target)
    return copied


def require_migration(
    scenario: Scenario,
) -> dict[str, Any]:
    settings = json.loads(
        pair.settings_path(HOST_INSTANCE).read_text(
            encoding="utf-8"
        )
    )
    if not scenario.legacy_migration:
        return settings
    row = settings["values"]["roster"][0]
    if (
        row.get("behavior") != "skirmisher"
        or row.get("discipline") != "arcane"
        or row.get("name") != scenario.bot_name
    ):
        raise BotCastRangeFailure(
            f"legacy roster did not migrate once: {row}"
        )
    return settings


def validate_scenario(
    scenario: Scenario,
    report: dict[str, Any],
    loader_log: str,
) -> dict[str, Any]:
    bots = [
        bot
        for bot in report["bots"]
        if bot["name"] == scenario.bot_name
    ]
    if len(bots) != 1:
        raise BotCastRangeFailure(
            f"{scenario.key} did not report exactly one bot: "
            f"{report['bots']}"
        )
    bot = bots[0]
    casts = [
        cast
        for cast in report["casts"]
        if cast["participantId"] == bot["id"]
    ]
    if not casts:
        raise BotCastRangeFailure(
            f"{scenario.key} queued no primary casts"
        )
    if not report["damageEdges"]:
        raise BotCastRangeFailure(
            f"{scenario.key} applied no enemy damage"
        )

    out_of_range = [
        cast
        for cast in casts
        if (
            not math.isfinite(cast["targetDistance"])
            or not math.isfinite(cast["spellRange"])
            or cast["spellRange"] <= 0.0
            or cast["targetDistance"]
            > cast["spellRange"] + RANGE_TOLERANCE
        )
    ]
    if out_of_range:
        raise BotCastRangeFailure(
            f"{scenario.key} cast outside its native range: "
            f"{out_of_range[:4]}"
        )
    bad_sources = {
        cast["rangeSource"]
        for cast in casts
        if cast["rangeSource"] != scenario.expected_range_source
    }
    if bad_sources:
        raise BotCastRangeFailure(
            f"{scenario.key} used non-native range sources: "
            f"{sorted(bad_sources)}"
        )

    links = applied_damage_links(casts, report["damageEdges"])
    if scenario.element == "fire":
        links = authorized_fireball_damage_links(
            casts,
            report["damageEdges"],
            parse_authorized_fireball_damage(loader_log),
        )
    if not links:
        raise BotCastRangeFailure(
            f"{scenario.key} had accepted casts and HP changes, but no "
            "bot-attributed native cast produced an applied-damage edge"
        )
    if "unknown mana cost for bot cast" in loader_log:
        raise BotCastRangeFailure(
            f"{scenario.key} retained the pre-fix mana rejection"
        )
    if "gameplay-slot cast prepare failed" in loader_log:
        raise BotCastRangeFailure(
            f"{scenario.key} had a native cast-preparation failure"
        )
    if (
        scenario.element == "water"
        and bot["outsideRangeApproachTicks"] <= 0
    ):
        raise BotCastRangeFailure(
            "short-range Water bot did not approach while its target "
            "center was outside Frost Jet range"
        )

    return {
        "bot": bot,
        "castCount": len(casts),
        "damageEdgeCount": len(report["damageEdges"]),
        "appliedDamageLinks": links,
        "minimumCastDistance": min(
            cast["targetDistance"] for cast in casts
        ),
        "maximumCastDistance": max(
            cast["targetDistance"] for cast in casts
        ),
        "minimumSpellRange": min(
            cast["spellRange"] for cast in casts
        ),
        "maximumSpellRange": max(
            cast["spellRange"] for cast in casts
        ),
        "allCastDistancesWithinSpellRange": True,
        "combatAcceptance": "applied enemy HP damage edges",
    }


def run_scenario(
    scenario: Scenario,
    evidence_root: Path,
) -> dict[str, Any]:
    scenario_root = evidence_root / scenario.key
    scenario_root.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "scenario": scenario.key,
        "botName": scenario.bot_name,
        "element": scenario.element,
        "ports": {
            "host": HOST_PORT,
            "clientB": CLIENT_PORT,
        },
        "instances": {
            "host": HOST_INSTANCE,
            "clientB": CLIENT_INSTANCE,
        },
        "exactModId": EXACT_MOD_ID,
        "rosterInput": scenario.roster,
        "legacyMigration": scenario.legacy_migration,
        "waveSchedule": "retail staged data/wave.txt; no override",
        "audioDisabled": True,
        "acceptanceMetric": "authoritative enemy HP damage edges",
        "success": False,
    }
    launch: dict[str, Any] | None = None
    pair_process: subprocess.Popen[str] | None = None
    failure: BaseException | None = None
    try:
        port_owners = pair.query_udp_owners()
        if port_owners not in ("", "null", "[]"):
            raise BotCastRangeFailure(
                f"ports 50411/50412 are occupied: {port_owners}"
            )
        pair.assert_no_existing_stage_processes()
        write_settings(HOST_INSTANCE, scenario.roster)
        write_settings(CLIENT_INSTANCE, [])

        pair_process, pid_path = pair.launch_pair(enable_audio=False)
        launch, observed_utc = pair.wait_for(
            lambda: pair.read_launch(pid_path),
            lambda value: (
                value.get("hostProcessId") is not None
                and value.get("clientProcessId") is not None
            ),
            label=f"{scenario.key} exact staged PIDs",
            timeout=180,
            interval=0.2,
        )
        result["launch"] = {
            **launch,
            "observedUtc": observed_utc,
        }
        for role in ("host", "client"):
            pid = int(launch[f"{role}ProcessId"])
            expected = str(launch[f"{role}ExecutablePath"])
            actual = pair.process_path(pid)
            if (
                actual is None
                or actual.casefold() != expected.casefold()
            ):
                raise BotCastRangeFailure(
                    f"{role} PID/path mismatch: "
                    f"{pid} {actual} != {expected}"
                )

        lobby, lobby_utc = pair.wait_for(
            lambda: {
                "host": pair.bot_probe(HOST_PIPE),
                "clientB": pair.bot_probe(CLIENT_PIPE),
            },
            lambda value: (
                pair.integer(value["host"], "count", -1) == 1
                and pair.integer(
                    value["clientB"], "count", -1
                ) == 1
                and pair.integer(
                    value["host"], "brain.active", -1
                ) == 1
                and pair.integer(
                    value["clientB"], "brain.active", -1
                ) == 1
                and value["host"].get("scene") == "hub"
                and value["clientB"].get("scene") == "hub"
            ),
            label=f"{scenario.key} launcher-configured bot lobby",
            timeout=120,
            interval=0.5,
        )
        result["lobby"] = lobby
        result["lobbyObservedUtc"] = lobby_utc
        result["migratedSettings"] = require_migration(scenario)

        result["runStart"] = pair.start_testrun()
        _, host_run_utc = pair.wait_for(
            lambda: pair.scene(HOST_PIPE),
            lambda value: value == "testrun",
            label=f"{scenario.key} host retail run",
            timeout=45,
        )
        _, client_run_utc = pair.wait_for(
            lambda: pair.scene(CLIENT_PIPE),
            lambda value: value == "testrun",
            label=f"{scenario.key} client B retail run",
            timeout=45,
        )
        result["runObservedUtc"] = {
            "host": host_run_utc,
            "clientB": client_run_utc,
        }

        run_bot, bot_run_utc = pair.wait_for(
            lambda: {
                "host": pair.bot_rows(
                    pair.bot_probe(HOST_PIPE)
                ).get(scenario.bot_name),
                "clientB": pair.bot_rows(
                    pair.bot_probe(CLIENT_PIPE)
                ).get(scenario.bot_name),
            },
            lambda value: all(
                row is not None
                and row["materialized"]
                and row["actor"] > 0
                and row["progression"] > 0
                for row in value.values()
            ),
            label=(
                f"{scenario.key} bot materialized on host and "
                "client B"
            ),
            timeout=45,
            interval=0.25,
        )
        result["runBot"] = {
            "state": run_bot,
            "observedUtc": bot_run_utc,
        }

        installed = pair.parse_key_values(
            pair.lua(HOST_PIPE, INSTALL_RECORDER)
        )
        if installed.get("installed") != "true":
            raise BotCastRangeFailure(
                f"recorder did not install: {installed}"
            )
        result["recorderInstall"] = installed

        run_bots = pair.bot_rows(pair.bot_probe(HOST_PIPE))
        bot = run_bots.get(scenario.bot_name)
        if bot is None or int(bot["id"]) <= 0:
            raise BotCastRangeFailure(
                f"{scenario.key} bot did not materialize: {run_bots}"
            )
        result["survivalGuard"] = {
            "hostAndBot": pair.arm_survival_guard(
                HOST_PIPE,
                int(bot["id"]),
            ),
            "clientB": pair.arm_survival_guard(CLIENT_PIPE),
            "scope": (
                "participant HP only; retail waves, targeting, "
                "movement, casting, enemy vitality, and damage "
                "are untouched"
            ),
        }
        result["nativeProgressionBeforeCombat"] = (
            pair.parse_key_values(
                pair.lua(
                    HOST_PIPE,
                    NATIVE_PROGRESSION_REPORT.replace(
                        "__PARTICIPANT_ID__",
                        str(int(bot["id"])),
                    ),
                )
            )
        )
        wave_start = pair.parse_key_values(
            pair.lua(
                HOST_PIPE,
                """
print("prelude=" ..
  tostring(sd.gameplay.enable_combat_prelude()))
print("waves=" ..
  tostring(sd.gameplay.start_waves()))
""",
            )
        )
        if (
            wave_start.get("prelude") != "true"
            or wave_start.get("waves") != "true"
        ):
            raise BotCastRangeFailure(
                f"retail waves did not start: {wave_start}"
            )
        result["waveStart"] = wave_start

        progress: list[dict[str, Any]] = []
        started = time.monotonic()
        while (
            time.monotonic() - started
            < SCENARIO_TIMEOUT_SECONDS
        ):
            time.sleep(POLL_SECONDS)
            values = pair.parse_key_values(
                pair.lua(HOST_PIPE, PROGRESS_REPORT)
            )
            sample = {
                "elapsedSeconds": round(
                    time.monotonic() - started,
                    3,
                ),
                **values,
            }
            progress.append(sample)
            print(
                f"{scenario.key}="
                + json.dumps(sample, sort_keys=True),
                flush=True,
            )
            if (
                pair.integer(values, "casts") > 0
                and pair.integer(values, "damage_edges") > 0
            ):
                break
        result["progress"] = progress

        raw_report = pair.parse_key_values(
            pair.lua(
                HOST_PIPE,
                RECORDER_REPORT,
                timeout=30,
            )
        )
        report = report_rows(raw_report)
        result["report"] = report
        loader_log_path = pair.log_path(HOST_INSTANCE)
        loader_log = loader_log_path.read_text(
            encoding="utf-8",
            errors="replace",
        )
        result["acceptance"] = validate_scenario(
            scenario,
            report,
            loader_log,
        )
        result["runtimeArtifacts"] = copy_runtime_artifacts(
            scenario_root
        )
        result["success"] = True
    except BaseException as error:
        failure = error
        result["failure"] = (
            f"{type(error).__name__}: {error}"
        )
        if launch is not None:
            try:
                result["runtimeArtifacts"] = (
                    copy_runtime_artifacts(scenario_root)
                )
            except BaseException as copy_error:
                result["artifactCopyFailure"] = (
                    f"{type(copy_error).__name__}: "
                    f"{copy_error}"
                )
    finally:
        if launch is not None:
            try:
                result["cleanup"] = []
                for role in ("host", "client"):
                    pid = int(launch[f"{role}ProcessId"])
                    expected = str(
                        launch[f"{role}ExecutablePath"]
                    )
                    if pair.process_path(pid) is None:
                        result["cleanup"].append(
                            {
                                "pid": pid,
                                "executablePath": expected,
                                "alreadyExited": True,
                                "forced": False,
                            }
                        )
                    else:
                        result["cleanup"].append(
                            pair.stop_owned_process(pid, expected)
                        )
            except BaseException as cleanup_error:
                result["cleanupFailure"] = (
                    f"{type(cleanup_error).__name__}: "
                    f"{cleanup_error}"
                )
                if failure is None:
                    failure = cleanup_error
                    result["success"] = False
        if pair_process is not None:
            try:
                pair_process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                pair_process.terminate()
                pair_process.wait(timeout=5)
        result_path = scenario_root / "result.json"
        pair.atomic_write_json(result_path, result)
        print(f"result={result_path}", flush=True)
    if failure is not None:
        raise failure
    return result


def validate_cross_scenario(
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    by_key = {
        result["scenario"]: result
        for result in results
    }
    water = by_key["short-water"]["acceptance"]
    fire = by_key["long-fire"]["acceptance"]
    if (
        fire["maximumCastDistance"]
        <= water["maximumSpellRange"] + RANGE_TOLERANCE
    ):
        raise BotCastRangeFailure(
            "long-range Fire bot did not cast beyond the short-range "
            "Water spell window: "
            f"fire={fire['maximumCastDistance']} "
            f"water={water['maximumSpellRange']}"
        )
    return {
        "shortRangeApproachedThenAppliedDamage": True,
        "longRangeCastBeyondShortRangeWindow": True,
        "everyCastWithinNativeSpellRange": True,
        "legacyRosterMigratedAndAppliedDamage": True,
        "combatAcceptance": "applied enemy HP damage edges",
        "waterMaximumSpellRange":
            water["maximumSpellRange"],
        "fireMaximumCastDistance":
            fire["maximumCastDistance"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the isolated retail-wave Lua Bots cast-range "
            "applied-damage regression."
        )
    )
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=DEFAULT_EVIDENCE_ROOT,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    evidence_root = args.evidence_root.resolve()
    evidence_root.mkdir(parents=True, exist_ok=True)
    configure_pair(evidence_root)
    output: dict[str, Any] = {
        "contract": "bot-cast-in-native-range-applied-damage",
        "ports": {
            "host": HOST_PORT,
            "clientB": CLIENT_PORT,
        },
        "audioDisabled": True,
        "exactModId": EXACT_MOD_ID,
        "waveSchedule": "retail staged data/wave.txt; no override",
        "acceptanceMetric": "authoritative enemy HP damage edges",
        "scenarios": [],
        "success": False,
    }
    output_path = evidence_root / "bot-cast-in-range.json"
    try:
        for scenario in SCENARIOS:
            output["scenarios"].append(
                run_scenario(scenario, evidence_root)
            )
        output["acceptance"] = validate_cross_scenario(
            output["scenarios"]
        )
        output["success"] = True
    except BaseException as error:
        output["failure"] = (
            f"{type(error).__name__}: {error}"
        )
        pair.atomic_write_json(output_path, output)
        raise
    pair.atomic_write_json(output_path, output)
    print(f"result={output_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
