#!/usr/bin/env python3
"""Run an isolated four-fighter Solomon Dig match with no human input."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import permutations
from pathlib import Path
from typing import Any, Literal

from PIL import Image

import cast_state_probe as csp
from verify_remote_latency_wave5 import (
    VerificationFailure,
    atomic_write_json,
    close_local_process_wrapper,
    is_transient_scene_churn,
    launch_local_process_with_ledger,
    parse_key_values,
    run_checked,
    sha256_file,
    validate_backbuffer,
    windows_path,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "tools/bot_match.example.json"
LAUNCH_SCRIPT = ROOT / "scripts/Launch-LocalSoloSession.ps1"
STOP_SCRIPT = ROOT / "scripts/Stop-RemoteLatencyPeer.ps1"
LUA_CLIENT = ROOT / "tools/lua-exec.py"
EVIDENCE_ROOT = Path("/mnt/d/codex-evidence/botcombat-20260729")
ALLOWED_PORTS = (50611, 50612)
BOT_BRAIN_MOD_ID = "bot.brain"
CONTROLLER_GLOBAL = "__botmatch_controller"
LOCAL_FIGHTER_KEY = "slot0"
STUCK_TELEPORT_MARKER = "[bots] stuck teleport. bot_id="
ARRIVAL_DISTANCE_EPSILON = 0.01

Mode = Literal["gate", "smoke", "matrix", "full"]


class BotMatchFailure(RuntimeError):
    """Raised when an all-bot match invariant is not met."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_batch_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,47}", value):
        raise BotMatchFailure(f"Unsafe batch id: {value!r}")
    return value


def instance_name(mode: Mode, run_index: int, batch_id: str) -> str:
    prefix = f"botmatch-{mode}-{run_index:02d}-"
    budget = 48 - len(prefix)
    if len(batch_id) <= budget:
        suffix = batch_id
    else:
        suffix = f"{batch_id[:budget - 9]}-{batch_id[-8:]}"
    return safe_batch_id(prefix + suffix)


def as_path(value: Any, *, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise BotMatchFailure(f"{field} must be a nonempty path.")
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def number(
    values: dict[str, str],
    key: str,
    default: float = math.nan,
) -> float:
    try:
        return float(values.get(key, str(default)))
    except (TypeError, ValueError):
        return default


def integer(
    values: dict[str, str],
    key: str,
    default: int = 0,
) -> int:
    try:
        return int(values.get(key, str(default)), 10)
    except (TypeError, ValueError):
        value = number(values, key, float(default))
        return int(value) if math.isfinite(value) else default


def boolean(values: dict[str, str], key: str) -> bool:
    return values.get(key, "").casefold() == "true"


def is_transient_lua_pipe_transition(message: str) -> bool:
    return "pipe closed without returning a response" in message.casefold()


def distance(
    left: tuple[float, float],
    right: tuple[float, float],
) -> float:
    return math.hypot(right[0] - left[0], right[1] - left[1])


def within_arrival_radius(value: float, radius: float) -> bool:
    return value <= radius + ARRIVAL_DISTANCE_EPSILON


def segments_properly_cross(
    first_start: tuple[float, float],
    first_end: tuple[float, float],
    second_start: tuple[float, float],
    second_end: tuple[float, float],
) -> bool:
    def orientation(
        start: tuple[float, float],
        end: tuple[float, float],
        point: tuple[float, float],
    ) -> float:
        return (
            (end[0] - start[0]) * (point[1] - start[1])
            - (end[1] - start[1]) * (point[0] - start[0])
        )

    first_left = orientation(first_start, first_end, second_start)
    first_right = orientation(first_start, first_end, second_end)
    second_left = orientation(second_start, second_end, first_start)
    second_right = orientation(second_start, second_end, first_end)
    return (
        first_left * first_right < -1e-6
        and second_left * second_right < -1e-6
    )


def signed_gate_progress(
    position: tuple[float, float],
    midpoint: tuple[float, float],
    transit_unit: tuple[float, float],
) -> float:
    return (
        (position[0] - midpoint[0]) * transit_unit[0]
        + (position[1] - midpoint[1]) * transit_unit[1]
    )


def gate_lateral_offset(
    position: tuple[float, float],
    midpoint: tuple[float, float],
    tangent_unit: tuple[float, float],
) -> float:
    return (
        (position[0] - midpoint[0]) * tangent_unit[0]
        + (position[1] - midpoint[1]) * tangent_unit[1]
    )


def normalize(x: float, y: float) -> tuple[float, float]:
    length = math.hypot(x, y)
    if length <= 0.0001:
        raise BotMatchFailure("Cannot normalize a zero-length route.")
    return x / length, y / length


@dataclass(frozen=True)
class FighterConfig:
    name: str
    element: str
    discipline: str
    behavior: str

    def settings_row(self) -> dict[str, str]:
        return {
            "name": self.name,
            "element": self.element,
            "discipline": self.discipline,
            "behavior": self.behavior,
        }


@dataclass(frozen=True)
class BotMatchConfig:
    source_path: Path
    evidence_root: Path
    runtime_root: Path
    game_directory: Path
    launcher_path: Path
    local_port: int
    unused_remote_port: int
    participant_id: str
    player_name: str
    player_element: str
    player_discipline: str
    bots: tuple[FighterConfig, FighterConfig, FighterConfig]
    gate_formation_spacing: float
    gate_approach_distance: float
    gate_exit_distance: float
    gate_arrival_radius: float
    gate_parking_arrival_radius: float
    gate_alignment_lateral_tolerance: float
    gather_distance: float
    gather_search_step: float
    gather_search_limit: float
    gather_spacing: float
    gather_arrival_radius: float
    trigger_spacing: float
    route_timeout_seconds: float
    trigger_timeout_seconds: float
    full_match_timeout_seconds: float
    full_stall_timeout_seconds: float
    monitor_interval_seconds: float
    run_count: int

    @classmethod
    def load(cls, path: Path) -> "BotMatchConfig":
        source = path.resolve()
        try:
            document = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise BotMatchFailure(
                f"Could not load bot-match config {source}: {error}"
            ) from error
        if not isinstance(document, dict) or document.get("schemaVersion") != 1:
            raise BotMatchFailure("Bot-match config must use schemaVersion 1.")

        paths = document.get("paths")
        network = document.get("network")
        player = document.get("player")
        navigation = document.get("navigation")
        match = document.get("match")
        roster = document.get("bots")
        if not all(
            isinstance(value, dict)
            for value in (paths, network, player, navigation, match)
        ) or not isinstance(roster, list):
            raise BotMatchFailure(
                "Bot-match config lacks paths/network/player/navigation/"
                "match/bots objects."
            )

        evidence_root = as_path(paths.get("evidenceRoot"), field="paths.evidenceRoot")
        if evidence_root != EVIDENCE_ROOT:
            raise BotMatchFailure(
                f"Evidence root must remain {EVIDENCE_ROOT}, got {evidence_root}."
            )
        local_port = int(network.get("localPort", 0))
        unused_remote_port = int(network.get("unusedRemotePort", 0))
        if (local_port, unused_remote_port) != ALLOWED_PORTS:
            raise BotMatchFailure(
                "The bot-match harness permits only ports 50611/50612."
            )
        if len(roster) != 3:
            raise BotMatchFailure(
                "Exactly three synthetic bots are required; slot 0 is the "
                "fourth automated fighter."
            )

        fighters: list[FighterConfig] = []
        allowed_elements = {"ether", "fire", "air", "water", "earth"}
        allowed_disciplines = {"mind", "body", "arcane"}
        allowed_behaviors = {"skirmisher", "guardian", "striker"}
        for index, row in enumerate(roster, start=1):
            if not isinstance(row, dict):
                raise BotMatchFailure(f"bots[{index}] must be an object.")
            fighter = FighterConfig(
                name=str(row.get("name", "")),
                element=str(row.get("element", "")),
                discipline=str(row.get("discipline", "")),
                behavior=str(row.get("behavior", "")),
            )
            if (
                not fighter.name
                or len(fighter.name.encode("utf-8")) > 31
                or fighter.element not in allowed_elements
                or fighter.discipline not in allowed_disciplines
                or fighter.behavior not in allowed_behaviors
            ):
                raise BotMatchFailure(
                    f"Invalid bot roster row {index}: {row!r}"
                )
            fighters.append(fighter)
        if len({fighter.name for fighter in fighters}) != 3:
            raise BotMatchFailure("Bot names must be unique.")

        player_element = str(player.get("element", ""))
        player_discipline = str(player.get("discipline", ""))
        if (
            player_element not in allowed_elements
            or player_discipline not in allowed_disciplines
        ):
            raise BotMatchFailure("The slot-0 element or discipline is invalid.")

        config = cls(
            source_path=source,
            evidence_root=evidence_root,
            runtime_root=as_path(paths.get("runtimeRoot"), field="paths.runtimeRoot"),
            game_directory=as_path(
                paths.get("gameDirectory"), field="paths.gameDirectory"
            ),
            launcher_path=as_path(
                paths.get("launcherPath"), field="paths.launcherPath"
            ),
            local_port=local_port,
            unused_remote_port=unused_remote_port,
            participant_id=str(network.get("participantId", "")),
            player_name=str(player.get("name", "")),
            player_element=player_element,
            player_discipline=player_discipline,
            bots=(fighters[0], fighters[1], fighters[2]),
            gate_formation_spacing=float(
                navigation.get("gateFormationSpacing", 65.0)
            ),
            gate_approach_distance=float(
                navigation.get("gateApproachDistance", 100.0)
            ),
            gate_exit_distance=float(
                navigation.get("gateExitDistance", 110.0)
            ),
            gate_arrival_radius=float(
                navigation.get("gateArrivalRadius", 45.0)
            ),
            gate_parking_arrival_radius=float(
                navigation.get("gateParkingArrivalRadius", 12.0)
            ),
            gate_alignment_lateral_tolerance=float(
                navigation.get(
                    "gateAlignmentLateralTolerance",
                    35.0,
                )
            ),
            gather_distance=float(navigation.get("gatherDistance", 280.0)),
            gather_search_step=float(
                navigation.get("gatherSearchStep", 65.0)
            ),
            gather_search_limit=float(
                navigation.get("gatherSearchLimit", 260.0)
            ),
            gather_spacing=float(navigation.get("gatherSpacing", 22.0)),
            gather_arrival_radius=float(
                navigation.get("gatherArrivalRadius", 50.0)
            ),
            trigger_spacing=float(navigation.get("triggerSpacing", 12.0)),
            route_timeout_seconds=float(
                navigation.get("routeTimeoutSeconds", 120.0)
            ),
            trigger_timeout_seconds=float(
                navigation.get("triggerTimeoutSeconds", 90.0)
            ),
            full_match_timeout_seconds=float(
                match.get("fullTimeoutSeconds", 900.0)
            ),
            full_stall_timeout_seconds=float(
                match.get("stallTimeoutSeconds", 120.0)
            ),
            monitor_interval_seconds=float(
                match.get("monitorIntervalSeconds", 0.5)
            ),
            run_count=int(match.get("runCount", 3)),
        )
        config.validate_files_and_ranges()
        return config

    def validate_files_and_ranges(self) -> None:
        required_files = (
            self.launcher_path,
            self.game_directory / "SolomonDark.exe",
            LAUNCH_SCRIPT,
            STOP_SCRIPT,
            LUA_CLIENT,
            ROOT / "bin/Release/Win32/SolomonDarkModLoader.dll",
        )
        missing = [str(path) for path in required_files if not path.exists()]
        if missing:
            raise BotMatchFailure(f"Required staged inputs are missing: {missing}")
        if not re.fullmatch(r"0x[0-9A-Fa-f]{1,16}", self.participant_id):
            raise BotMatchFailure("network.participantId must be a hexadecimal ID.")
        if not self.player_name or len(self.player_name.encode("utf-8")) > 31:
            raise BotMatchFailure("player.name must be 1-31 UTF-8 bytes.")
        positive = {
            "gateFormationSpacing": self.gate_formation_spacing,
            "gateApproachDistance": self.gate_approach_distance,
            "gateExitDistance": self.gate_exit_distance,
            "gateArrivalRadius": self.gate_arrival_radius,
            "gateParkingArrivalRadius":
                self.gate_parking_arrival_radius,
            "gateAlignmentLateralTolerance":
                self.gate_alignment_lateral_tolerance,
            "gatherDistance": self.gather_distance,
            "gatherSearchStep": self.gather_search_step,
            "gatherSearchLimit": self.gather_search_limit,
            "gatherSpacing": self.gather_spacing,
            "gatherArrivalRadius": self.gather_arrival_radius,
            "triggerSpacing": self.trigger_spacing,
            "routeTimeoutSeconds": self.route_timeout_seconds,
            "triggerTimeoutSeconds": self.trigger_timeout_seconds,
            "fullTimeoutSeconds": self.full_match_timeout_seconds,
            "stallTimeoutSeconds": self.full_stall_timeout_seconds,
            "monitorIntervalSeconds": self.monitor_interval_seconds,
        }
        bad = [name for name, value in positive.items() if value <= 0]
        invalid_gate_parking = (
            self.gate_parking_arrival_radius
            >= min(
                self.gate_exit_distance,
                self.gate_formation_spacing / 2.0,
            )
        )
        if bad or invalid_gate_parking or not 1 <= self.run_count <= 20:
            raise BotMatchFailure(
                "Bot-match numeric settings are out of range: "
                f"nonpositive={bad}, "
                f"invalidGateParking={invalid_gate_parking}"
            )


STATE_PROBE = r"""
local output = {}
local function emit(key, value)
  output[#output + 1] =
    key .. "=" .. tostring(value == nil and "" or value)
end
local scene = sd.world.get_scene() or {}
local player = sd.player.get_state() or {}
local wave = sd.waves.get_state() or {}
local combat = sd.gameplay.get_combat_state() or {}
local runtime = sd.runtime.get_multiplayer_state() or {}
local solomon = nil
local solomon_ok, solomon_value =
  pcall(sd.hub.get_solomon_dig_state)
if solomon_ok and type(solomon_value) == "table" then
  solomon = solomon_value
end

emit("scene.kind", scene.kind or "")
emit("scene.name", scene.name or "")
emit("player.actor", player.actor_address or 0)
emit("player.x", player.x or 0)
emit("player.y", player.y or 0)
emit("player.hp", player.hp or 0)
emit("player.max_hp", player.max_hp or 0)
emit("player.participant_id",
  runtime.local_participant_id or
  runtime.participant_id or 0)
emit("wave.number", wave.wave or 0)
emit("wave.phase", wave.phase or "")
emit("wave.planned", wave.planned or 0)
emit("wave.remaining_to_spawn", wave.remaining_to_spawn or 0)
emit("wave.spawned", wave.spawned or 0)
emit("wave.alive", wave.alive or 0)
emit("wave.killed", wave.killed or 0)
local wave_composition = wave.composition or {}
emit("wave.composition_count", #wave_composition)
for index, row in ipairs(wave_composition) do
  local prefix = "wave.composition." .. tostring(index) .. "."
  emit(prefix .. "enemy_type", row.enemy_type or -1)
  emit(prefix .. "planned", row.planned or 0)
  emit(prefix .. "spawned", row.spawned or 0)
  emit(prefix .. "alive", row.alive or 0)
  emit(prefix .. "killed", row.killed or 0)
end
emit("combat.active", combat.active or false)
emit("combat.wave_index", combat.wave_index or 0)
emit("combat.wait_ticks", combat.wait_ticks or 0)
emit("solomon.available", solomon ~= nil)
emit("solomon.actor", solomon and solomon.actor_address or 0)
emit("solomon.x", solomon and solomon.x or 0)
emit("solomon.y", solomon and solomon.y or 0)
emit("solomon.state", solomon and solomon.interaction_state or -1)
emit("solomon.acquired",
  solomon and solomon.participant_acquired or false)
emit("solomon.target_slot",
  solomon and solomon.target_gameplay_slot or -1)

local brain = rawget(_G, "bot_brain_debug") or {}
emit("brain.active", brain.active_bot_count or 0)
emit("brain.desired", brain.desired_bot_count or 0)
local debug_by_id = {}
for _, row in ipairs(brain.bots or {}) do
  debug_by_id[tonumber(row.participant_id) or 0] = row
end
local bots = sd.bots.get_state() or {}
emit("bot.count", #bots)
for index, bot in ipairs(bots) do
  local prefix = "bot." .. tostring(index) .. "."
  local row = debug_by_id[tonumber(bot.id) or 0] or {}
  emit(prefix .. "id", bot.id or 0)
  emit(prefix .. "name", bot.name or "")
  emit(prefix .. "slot", bot.gameplay_slot or -1)
  emit(prefix .. "actor", bot.actor_address or 0)
  emit(prefix .. "materialized",
    (tonumber(bot.actor_address) or 0) ~= 0)
  emit(prefix .. "x", bot.x or 0)
  emit(prefix .. "y", bot.y or 0)
  emit(prefix .. "hp", bot.hp or 0)
  emit(prefix .. "max_hp", bot.max_hp or 0)
  emit(prefix .. "state", bot.state or "")
  emit(prefix .. "mode", row.mode or "")
  emit(prefix .. "cast_accepted", row.cast_accepted or 0)
  emit(prefix .. "skill_choices_accepted",
    row.skill_choices_accepted or 0)
end

local enemies = {}
for _, actor in ipairs(sd.world.list_actors() or {}) do
  if actor.tracked_enemy == true then
    enemies[#enemies + 1] = actor
  end
end
emit("enemy.count", #enemies)
for index, actor in ipairs(enemies) do
  local prefix = "enemy." .. tostring(index) .. "."
  emit(prefix .. "actor", actor.actor_address or 0)
  emit(prefix .. "type", actor.enemy_type or actor.object_type_id or -1)
  emit(prefix .. "hp", actor.hp or 0)
  emit(prefix .. "max_hp", actor.max_hp or 0)
  emit(prefix .. "dead", actor.dead or false)
  emit(prefix .. "x", actor.x or 0)
  emit(prefix .. "y", actor.y or 0)
end

local controller = rawget(_G, "__botmatch_controller") or {}
emit("controller.armed", controller.armed == true)
emit("controller.mode", controller.mode or "")
emit("controller.destination_active",
  type(controller.destination) == "table")
emit("controller.destination_distance",
  controller.destination_distance or -1)
emit("controller.local_cast_attempts",
  controller.local_cast_attempts or 0)
emit("controller.local_cast_accepted",
  controller.local_cast_accepted or 0)
emit("controller.run_ended", controller.run_ended == true)
local completed_waves = {}
for completed_wave, completed_ms in pairs(
    controller.wave_completed or {}) do
  completed_waves[#completed_waves + 1] = {
    wave = tonumber(completed_wave) or 0,
    monotonic_ms = tonumber(completed_ms) or 0,
  }
end
table.sort(completed_waves, function(left, right)
  return left.wave < right.wave
end)
emit("controller.completed_count", #completed_waves)
for index, row in ipairs(completed_waves) do
  local prefix = "controller.completed." .. tostring(index) .. "."
  emit(prefix .. "wave", row.wave)
  emit(prefix .. "monotonic_ms", row.monotonic_ms)
end
local wave_plans = {}
for planned_wave, plan in pairs(controller.wave_plans or {}) do
  wave_plans[#wave_plans + 1] = {
    wave = tonumber(planned_wave) or 0,
    plan = plan,
  }
end
table.sort(wave_plans, function(left, right)
  return left.wave < right.wave
end)
emit("controller.plan_count", #wave_plans)
for plan_index, entry in ipairs(wave_plans) do
  local prefix = "controller.plan." .. tostring(plan_index) .. "."
  emit(prefix .. "wave", entry.wave)
  emit(prefix .. "planned", entry.plan.planned or 0)
  local composition = entry.plan.composition or {}
  emit(prefix .. "composition_count", #composition)
  for row_index, row in ipairs(composition) do
    local row_prefix =
      prefix .. "composition." .. tostring(row_index) .. "."
    emit(row_prefix .. "enemy_type", row.enemy_type or -1)
    emit(row_prefix .. "planned", row.planned or 0)
  end
end
return table.concat(output, "\n")
"""


OPENABLE_PROBE = r"""
local output = {}
local function emit(key, value)
  output[#output + 1] =
    key .. "=" .. tostring(value == nil and "" or value)
end
local obstacles = sd.debug.list_openable_path_obstacles() or {}
emit("count", #obstacles)
for index, obstacle in ipairs(obstacles) do
  local prefix = "obstacle." .. tostring(index) .. "."
  emit(prefix .. "object", obstacle.object_address or 0)
  emit(prefix .. "record", obstacle.collision_record_address or 0)
  emit(prefix .. "start_x", obstacle.start_x or 0)
  emit(prefix .. "start_y", obstacle.start_y or 0)
  emit(prefix .. "end_x", obstacle.end_x or 0)
  emit(prefix .. "end_y", obstacle.end_y or 0)
end
return table.concat(output, "\n")
"""


DAMAGE_DRAIN_PROBE = r"""
local output = {}
local enemy = sd.debug.take_enemy_damage_observations() or {}
for _, row in ipairs(enemy) do
  output[#output + 1] = table.concat({
    "enemy",
    tostring(row.sequence or 0),
    tostring(row.monotonic_ms or 0),
    tostring(row.source_participant_id or 0),
    tostring(row.source_native_type_id or 0),
    tostring(row.source_owner_native_type_id or 0),
    tostring(row.source_gameplay_slot or -1),
    tostring(row.target_actor_address or 0),
    tostring(row.target_network_actor_id or 0),
    tostring(row.target_native_type_id or 0),
    tostring(row.target_hp_before or 0),
    tostring(row.target_hp_after or 0),
    tostring(row.target_max_hp or 0),
    tostring(row.hp_delta or 0),
  }, "|")
end
local player = sd.debug.take_player_damage_observations() or {}
for _, row in ipairs(player) do
  output[#output + 1] = table.concat({
    "player",
    tostring(row.sequence or 0),
    tostring(row.monotonic_ms or 0),
    tostring(row.target_participant_id or 0),
    tostring(row.target_gameplay_slot or -1),
    tostring(row.target_actor_address or 0),
    tostring(row.source_actor_address or 0),
    tostring(row.source_native_type_id or 0),
    tostring(row.target_hp_before or 0),
    tostring(row.target_hp_after or 0),
    tostring(row.target_max_hp or 0),
    tostring(row.hp_delta or 0),
  }, "|")
end
if #output == 0 then
  return "none"
end
return table.concat(output, "\n")
"""


def controller_source(wave_capture_pattern: str) -> str:
    return f"""
local previous = rawget(_G, "{CONTROLLER_GLOBAL}")
if type(previous) == "table" then
  previous.armed = false
end
local controller = {{
  armed = true,
  mode = "prewave",
  destination = nil,
  destination_distance = -1,
  arrival_radius = 18.0,
  last_cast_ms = 0,
  local_cast_attempts = 0,
  local_cast_accepted = 0,
  movement_frames = 0,
  run_ended = false,
  wave_started = {{}},
  wave_completed = {{}},
  wave_plans = {{}},
  wave_captures = {{}},
  wave_capture_pattern = {json.dumps(wave_capture_pattern)},
}}
rawset(_G, "{CONTROLLER_GLOBAL}", controller)

local function normalize(x, y)
  local length = math.sqrt(x * x + y * y)
  if length <= 0.0001 then return 0.0, 0.0, 0.0 end
  return x / length, y / length, length
end

local function live_enemy(player_x, player_y)
  local nearest, nearest_distance = nil, math.huge
  for _, actor in ipairs(sd.world.list_actors() or {{}}) do
    local hp = tonumber(actor.hp) or 0
    if actor.tracked_enemy == true and
        actor.dead ~= true and hp > 0 then
      local x = tonumber(actor.x) or 0
      local y = tonumber(actor.y) or 0
      local dx, dy = x - player_x, y - player_y
      local candidate = math.sqrt(dx * dx + dy * dy)
      if candidate < nearest_distance then
        nearest = actor
        nearest_distance = candidate
      end
    end
  end
  return nearest, nearest_distance
end

local function drive_local(event)
  local active = rawget(_G, "{CONTROLLER_GLOBAL}")
  if active ~= controller or active.armed ~= true then return end
  local scene = sd.world.get_scene() or {{}}
  if tostring(scene.name or scene.kind or "") ~= "testrun" then
    return
  end
  local player = sd.player.get_state() or {{}}
  local x, y = tonumber(player.x), tonumber(player.y)
  local hp = tonumber(player.hp) or 0
  if x == nil or y == nil or
      (tonumber(player.actor_address) or 0) == 0 then
    return
  end
  local wave = sd.waves.get_state() or {{}}
  local wave_number = tonumber(wave.wave) or 0
  pcall(sd.input.set_native_control_allowance_frames, 120)
  if wave_number <= 0 then
    active.mode = "prewave"
    if type(active.destination) ~= "table" then return end
    local dx = active.destination.x - x
    local dy = active.destination.y - y
    local nx, ny, remaining = normalize(dx, dy)
    active.destination_distance = remaining
    if remaining <= active.arrival_radius then
      active.destination = nil
      return
    end
    local ok, accepted =
      pcall(sd.input.hold_movement_frames, nx, ny, 1)
    if ok and accepted == true then
      active.movement_frames = active.movement_frames + 1
    end
    return
  end

  active.mode = hp > 0 and "combat" or "dead"
  if hp <= 0 then return end
  local enemy, enemy_distance = live_enemy(x, y)
  if enemy == nil then return end
  local ex, ey = tonumber(enemy.x) or x, tonumber(enemy.y) or y
  local toward_x, toward_y = normalize(ex - x, ey - y)
  local move_x, move_y = 0.0, 0.0
  if enemy_distance > 220.0 then
    move_x, move_y = toward_x, toward_y
  elseif enemy_distance < 95.0 then
    move_x, move_y = -toward_x, -toward_y
  else
    move_x = -toward_y + toward_x * 0.15
    move_y = toward_x + toward_y * 0.15
    move_x, move_y = normalize(move_x, move_y)
  end
  local move_ok, moved =
    pcall(sd.input.hold_movement_frames, move_x, move_y, 1)
  if move_ok and moved == true then
    active.movement_frames = active.movement_frames + 1
  end

  local now_ms = tonumber(
    event and event.monotonic_milliseconds) or 0
  if now_ms - active.last_cast_ms < 350 then return end
  active.last_cast_ms = now_ms
  active.local_cast_attempts = active.local_cast_attempts + 1
  local actor = tonumber(enemy.actor_address) or 0
  local pin_ok, pinned =
    pcall(sd.input.pin_manual_primary_target, actor)
  local cast_ok, accepted =
    pcall(sd.input.hold_mouse_left_frames, 3)
  if pin_ok and pinned == true and
      cast_ok and accepted == true then
    active.local_cast_accepted =
      active.local_cast_accepted + 1
  end
end

sd.events.on("runtime.tick", drive_local)
sd.events.on("wave.started", function(event)
  local active = rawget(_G, "{CONTROLLER_GLOBAL}")
  if active ~= controller or active.armed ~= true then return end
  local wave = tonumber(event and event.wave) or 0
  local now_ms = tonumber(
    event and event.monotonic_milliseconds) or 0
  active.wave_started[wave] = now_ms
  local composition = {{}}
  for _, row in ipairs(event and event.composition or {{}}) do
    composition[#composition + 1] = {{
      enemy_type = tonumber(row.enemy_type) or -1,
      planned = tonumber(row.planned) or 0,
    }}
  end
  active.wave_plans[wave] = {{
    planned = tonumber(event and event.planned) or 0,
    composition = composition,
  }}
  local path = string.format(active.wave_capture_pattern, wave)
  if wave > 0 and
      active.wave_captures[wave] == nil then
    local ok, err = sd.debug.capture_backbuffer(path)
    active.wave_captures[wave] = {{
      ok = ok == true,
      error = tostring(err or ""),
      monotonic_ms = now_ms,
    }}
  end
end)
sd.events.on("wave.completed", function(event)
  local active = rawget(_G, "{CONTROLLER_GLOBAL}")
  if active ~= controller or active.armed ~= true then return end
  local wave = tonumber(event and event.wave) or 0
  local now_ms = tonumber(
    event and event.monotonic_milliseconds) or 0
  if wave > 0 then
    active.wave_completed[wave] = now_ms
  end
end)
sd.events.on("run.ended", function()
  local active = rawget(_G, "{CONTROLLER_GLOBAL}")
  if active == controller then active.run_ended = true end
end)
print("armed=" .. tostring(controller.armed))
"""


class BotMatchRun:
    def __init__(
        self,
        config: BotMatchConfig,
        *,
        mode: Mode,
        run_index: int,
        batch_directory: Path,
        instance: str,
    ) -> None:
        self.config = config
        self.mode = mode
        self.run_index = run_index
        self.instance = instance
        self.run_directory = batch_directory / f"run-{run_index:02d}"
        self.screenshot_directory = self.run_directory / "screenshots"
        self.ledger_path = self.run_directory / "process-ledger.json"
        self.bot_settings_path = self.run_directory / "bot-settings.json"
        self.launch: dict[str, Any] = {}
        self.launch_wrapper: subprocess.Popen[str] | None = None
        self.launch_log = self.run_directory / "local-launch.log"
        self.pipe_name = f"SolomonDarkModLoader_LuaExec_{instance}"
        self.process_started = False
        self.timeline: list[dict[str, Any]] = []
        self.enemy_damage: list[dict[str, Any]] = []
        self.player_damage: list[dict[str, Any]] = []
        self.wave_summaries: dict[int, dict[str, Any]] = {}
        self.wave_plans: dict[int, dict[str, Any]] = {}
        self.completed_waves: dict[int, int] = {}
        self.wave_screenshots: dict[int, dict[str, Any]] = {}
        self.death_transitions: list[dict[str, Any]] = []
        self.respawn_transitions: list[dict[str, Any]] = []
        self.last_alive: dict[int, bool] = {}
        self.last_death_damage_sequence: dict[int, int] = {}
        self.fighter_names_by_id: dict[int, str] = {}
        self.furthest_wave = 0
        self.last_damage_monotonic = 0.0
        self.started_monotonic = time.monotonic()

    @property
    def stage_root(self) -> Path:
        return (
            self.config.runtime_root
            / "instances"
            / self.instance.casefold()
            / "stage"
        )

    @property
    def loader_log(self) -> Path:
        return self.stage_root / ".sdmod/logs/solomondarkmodloader.log"

    def write_settings(self) -> None:
        atomic_write_json(
            self.bot_settings_path,
            {
                "schemaVersion": 1,
                "values": {
                    "focus_bot_key": "NONE",
                    "kite_radius": 340,
                    "offense_enabled": True,
                    "think_profile": "standard",
                    "roster": [
                        fighter.settings_row()
                        for fighter in self.config.bots
                    ],
                },
            },
        )

    def launch_game(self) -> None:
        self.run_directory.mkdir(parents=True, exist_ok=False)
        self.screenshot_directory.mkdir(parents=True, exist_ok=False)
        self.write_settings()
        command = [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            windows_path(LAUNCH_SCRIPT),
            "-Instance",
            self.instance,
            "-Preset",
            "idle",
            "-RuntimeRoot",
            windows_path(self.config.runtime_root),
            "-LocalPort",
            str(self.config.local_port),
            "-UnusedRemotePort",
            str(self.config.unused_remote_port),
            "-ParticipantId",
            self.config.participant_id,
            "-PlayerName",
            self.config.player_name,
            "-GameDirectory",
            windows_path(self.config.game_directory),
            "-LauncherPath",
            windows_path(self.config.launcher_path),
            "-ExactModIds",
            BOT_BRAIN_MOD_ID,
            "-BotSettingsPath",
            windows_path(self.bot_settings_path),
            "-LuaExecTargetModId",
            BOT_BRAIN_MOD_ID,
            "-MaxParticipants",
            "4",
            "-EnableNetworkTelemetry",
            "-ProcessIdOutputPath",
            windows_path(self.ledger_path),
        ]
        try:
            self.launch, self.launch_wrapper = (
                launch_local_process_with_ledger(
                    command,
                    ledger=self.ledger_path,
                    launch_log=self.launch_log,
                )
            )
        except Exception as error:
            raise BotMatchFailure(
                f"Local launcher did not establish ownership: {error}"
            ) from error
        self.process_started = True
        if (
            self.launch.get("audioDisabled") is not True
            or int(self.launch.get("localPort", 0))
            != self.config.local_port
            or int(self.launch.get("unusedRemotePort", 0))
            != self.config.unused_remote_port
            or int(self.launch.get("maxParticipants", 0)) != 4
        ):
            raise BotMatchFailure(
                f"Launcher returned an unsafe session contract: {self.launch}"
            )
        executable = Path(
            subprocess.run(
                [
                    "wslpath",
                    "-u",
                    str(self.launch.get("executablePath", "")),
                ],
                capture_output=True,
                text=True,
                timeout=15,
                check=True,
            ).stdout.strip()
        ).resolve()
        if executable != (self.stage_root / "SolomonDark.exe").resolve():
            raise BotMatchFailure(
                "Launcher executable does not match the owned stage: "
                f"{executable}"
            )
        os.environ["SDMOD_LUA_EXEC_PIPE_NAME"] = self.pipe_name
        self.wait_for_lua()

    def stop_game(self) -> dict[str, Any]:
        if not self.process_started:
            close_local_process_wrapper(self.launch_wrapper)
            self.launch_wrapper = None
            return {"stopped": False, "notStarted": True}
        try:
            output = run_checked(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    windows_path(STOP_SCRIPT),
                    "-ProcessLedgerPath",
                    windows_path(self.ledger_path),
                ],
                timeout=30,
                cwd=ROOT,
            )
            self.process_started = False
            rows = [
                line.strip()
                for line in output.splitlines()
                if line.strip().startswith("{")
            ]
            result = (
                json.loads(rows[-1]) if rows else {"raw": output}
            )
            atomic_write_json(
                self.run_directory / "process-stop.json",
                result,
            )
            return result
        finally:
            close_local_process_wrapper(self.launch_wrapper)
            self.launch_wrapper = None

    def lua(
        self,
        code: str,
        *,
        timeout: float = 30,
        transition_retry_seconds: float = 0,
    ) -> str:
        environment = os.environ.copy()
        environment["SDMOD_LUA_EXEC_PIPE_NAME"] = self.pipe_name
        source = f"-- sdmod-exec-target: {BOT_BRAIN_MOD_ID}\n{code}"
        retry_deadline = time.monotonic() + transition_retry_seconds
        while True:
            try:
                return run_checked(
                    [sys.executable, str(LUA_CLIENT), source],
                    timeout=timeout,
                    cwd=ROOT,
                    environment=environment,
                )
            except Exception as error:
                if (
                    time.monotonic() < retry_deadline
                    and is_transient_lua_pipe_transition(str(error))
                ):
                    time.sleep(0.1)
                    continue
                raise BotMatchFailure(
                    f"Lua exec failed: {error}"
                ) from error

    def values(
        self,
        code: str,
        *,
        timeout: float = 30,
        transition_retry_seconds: float = 0,
    ) -> dict[str, str]:
        return parse_key_values(
            self.lua(
                code,
                timeout=timeout,
                transition_retry_seconds=transition_retry_seconds,
            )
        )

    def wait_for_lua(self) -> None:
        deadline = time.monotonic() + 60
        last_error = ""
        while time.monotonic() < deadline:
            try:
                if "botmatch-ready" in self.lua(
                    'return "botmatch-ready"', timeout=8
                ):
                    return
            except BotMatchFailure as error:
                last_error = str(error)
            time.sleep(0.25)
        raise BotMatchFailure(
            f"Lua pipe did not become ready: {last_error}"
        )

    def drive_to_hub(self) -> dict[str, Any]:
        process_id = int(self.launch["processId"])
        try:
            navigation = csp.drive_hub_flow(
                process_id,
                element=self.config.player_element,
                discipline=self.config.player_discipline,
                prefer_resume=False,
            )
        except Exception as error:
            raise BotMatchFailure(
                f"Retail menu-to-hub flow failed: {error}"
            ) from error
        return navigation

    def wait_for_roster(self, *, timeout: float = 45) -> dict[str, Any]:
        expected = {fighter.name for fighter in self.config.bots}
        deadline = time.monotonic() + timeout
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            last = self.snapshot()
            names = {
                row["name"]
                for row in last["bots"]
                if row["id"] > 0
            }
            if (
                names == expected
                and len(last["bots"]) == 3
                and last["brainActive"] == 3
            ):
                return last
            time.sleep(0.25)
        raise BotMatchFailure(
            f"Three-seat bot roster did not settle: {last}"
        )

    def start_testrun(self) -> dict[str, str]:
        code = r"""
local invoked, ok, result = pcall(sd.hub.start_testrun)
print("ok=" .. tostring(invoked and ok == true))
print("result=" .. tostring(
  invoked and (result or "") or ok or ""))
"""
        deadline = time.monotonic() + 30
        last: dict[str, str] = {}
        while time.monotonic() < deadline:
            last = self.values(code)
            if last.get("ok") == "true":
                break
            if not is_transient_scene_churn(
                last.get("result", "")
            ):
                raise BotMatchFailure(
                    f"Host could not enter the retail test run: {last}"
                )
            time.sleep(0.25)
        else:
            raise BotMatchFailure(
                f"Host run transition never settled: {last}"
            )

        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            snapshot = self.snapshot()
            if (
                snapshot["sceneName"] == "testrun"
                and snapshot["player"]["actor"] > 0
                and snapshot["solomon"]["available"]
            ):
                return last
            time.sleep(0.25)
        raise BotMatchFailure("Testrun did not materialize Solomon and slot 0.")

    def arm_controller(self) -> dict[str, str]:
        capture_pattern = windows_path(
            self.screenshot_directory / "wave-%02d.bmp"
        )
        values = self.values(controller_source(capture_pattern))
        if values.get("armed") != "true":
            raise BotMatchFailure(
                f"Slot-0 bot controller did not arm: {values}"
            )
        return values

    def promote_bots_at_run_entry(self) -> dict[str, Any]:
        offsets = (-28.0, 0.0, 28.0)
        rows = ",\n".join(
            (
                f"[{json.dumps(fighter.name)}] = "
                f"{{ x = 0.0, y = {offsets[index]:.9f} }}"
            )
            for index, fighter in enumerate(self.config.bots)
        )
        output = self.values(
            f"""
local player = assert(sd.player.get_state(), "slot 0 unavailable")
local offsets = {{
  {rows}
}}
local applied = 0
local failures = {{}}
for _, bot in ipairs(sd.bots.get_state() or {{}}) do
  local offset = offsets[tostring(bot.name or "")]
  if offset ~= nil then
    local ok = sd.bots.update({{
      id = bot.id,
      scene = {{ kind = "run" }},
      heading = 0.0,
      position = {{
        x = (tonumber(player.x) or 0) + offset.x,
        y = (tonumber(player.y) or 0) + offset.y,
      }},
    }})
    if ok == true then
      applied = applied + 1
    else
      failures[#failures + 1] = tostring(bot.name)
    end
  end
end
print("applied=" .. tostring(applied))
print("failures=" .. table.concat(failures, ","))
"""
        )
        if integer(output, "applied") != 3 or output.get("failures"):
            raise BotMatchFailure(
                f"Run-entry bot materialization failed: {output}"
            )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            snapshot = self.snapshot()
            if (
                len(snapshot["bots"]) == 3
                and all(
                    row["materialized"]
                    and row["slot"] in {1, 2, 3}
                    and row["hp"] > 0
                    for row in snapshot["bots"]
                )
            ):
                return {
                    "sceneEntryReanchors": 3,
                    "positions": self.fighter_position_record(snapshot),
                }
            time.sleep(0.25)
        raise BotMatchFailure("Run-entry bot actors did not materialize.")

    def snapshot(
        self,
        *,
        transition_retry_seconds: float = 0,
    ) -> dict[str, Any]:
        values = self.values(
            STATE_PROBE,
            transition_retry_seconds=transition_retry_seconds,
        )
        bots = []
        for index in range(1, integer(values, "bot.count") + 1):
            prefix = f"bot.{index}."
            bots.append(
                {
                    "id": integer(values, prefix + "id"),
                    "name": values.get(prefix + "name", ""),
                    "slot": integer(values, prefix + "slot", -1),
                    "actor": integer(values, prefix + "actor"),
                    "materialized": boolean(
                        values, prefix + "materialized"
                    ),
                    "x": number(values, prefix + "x", 0.0),
                    "y": number(values, prefix + "y", 0.0),
                    "hp": number(values, prefix + "hp", 0.0),
                    "maxHp": number(values, prefix + "max_hp", 0.0),
                    "state": values.get(prefix + "state", ""),
                    "mode": values.get(prefix + "mode", ""),
                    "castAccepted": integer(
                        values, prefix + "cast_accepted"
                    ),
                    "skillChoicesAccepted": integer(
                        values,
                        prefix + "skill_choices_accepted",
                    ),
                }
            )
        enemies = []
        for index in range(1, integer(values, "enemy.count") + 1):
            prefix = f"enemy.{index}."
            enemies.append(
                {
                    "actor": integer(values, prefix + "actor"),
                    "type": integer(values, prefix + "type", -1),
                    "hp": number(values, prefix + "hp", 0.0),
                    "maxHp": number(values, prefix + "max_hp", 0.0),
                    "dead": boolean(values, prefix + "dead"),
                    "x": number(values, prefix + "x", 0.0),
                    "y": number(values, prefix + "y", 0.0),
                }
            )
        wave_composition = []
        for index in range(
            1,
            integer(values, "wave.composition_count") + 1,
        ):
            prefix = f"wave.composition.{index}."
            wave_composition.append(
                {
                    "enemyType": integer(
                        values,
                        prefix + "enemy_type",
                        -1,
                    ),
                    "planned": integer(values, prefix + "planned"),
                    "spawned": integer(values, prefix + "spawned"),
                    "alive": integer(values, prefix + "alive"),
                    "killed": integer(values, prefix + "killed"),
                }
            )
        completed_waves = []
        for index in range(
            1,
            integer(values, "controller.completed_count") + 1,
        ):
            prefix = f"controller.completed.{index}."
            completed_waves.append(
                {
                    "wave": integer(values, prefix + "wave"),
                    "monotonicMs": integer(
                        values,
                        prefix + "monotonic_ms",
                    ),
                }
            )
        wave_plans = []
        for index in range(
            1,
            integer(values, "controller.plan_count") + 1,
        ):
            prefix = f"controller.plan.{index}."
            composition = []
            for row_index in range(
                1,
                integer(
                    values,
                    prefix + "composition_count",
                ) + 1,
            ):
                row_prefix = (
                    f"{prefix}composition.{row_index}."
                )
                composition.append(
                    {
                        "enemyType": integer(
                            values,
                            row_prefix + "enemy_type",
                            -1,
                        ),
                        "planned": integer(
                            values,
                            row_prefix + "planned",
                        ),
                    }
                )
            wave_plans.append(
                {
                    "wave": integer(values, prefix + "wave"),
                    "planned": integer(values, prefix + "planned"),
                    "composition": composition,
                }
            )
        snapshot = {
            "sampledAt": utc_now(),
            "monotonicSeconds": time.monotonic(),
            "sceneKind": values.get("scene.kind", ""),
            "sceneName": values.get("scene.name", ""),
            "wave": integer(values, "wave.number"),
            "wavePhase": values.get("wave.phase", ""),
            "waveSummary": {
                "wave": integer(values, "wave.number"),
                "phase": values.get("wave.phase", ""),
                "planned": integer(values, "wave.planned"),
                "remainingToSpawn": integer(
                    values,
                    "wave.remaining_to_spawn",
                ),
                "spawned": integer(values, "wave.spawned"),
                "alive": integer(values, "wave.alive"),
                "killed": integer(values, "wave.killed"),
                "composition": wave_composition,
            },
            "combatActive": boolean(values, "combat.active"),
            "combatWaveIndex": integer(values, "combat.wave_index"),
            "combatWaitTicks": integer(values, "combat.wait_ticks"),
            "player": {
                "actor": integer(values, "player.actor"),
                "participantId": integer(
                    values, "player.participant_id"
                ),
                "x": number(values, "player.x", 0.0),
                "y": number(values, "player.y", 0.0),
                "hp": number(values, "player.hp", 0.0),
                "maxHp": number(values, "player.max_hp", 0.0),
            },
            "solomon": {
                "available": boolean(values, "solomon.available"),
                "actor": integer(values, "solomon.actor"),
                "x": number(values, "solomon.x", 0.0),
                "y": number(values, "solomon.y", 0.0),
                "state": integer(values, "solomon.state", -1),
                "acquired": boolean(values, "solomon.acquired"),
                "targetSlot": integer(
                    values, "solomon.target_slot", -1
                ),
            },
            "bots": bots,
            "enemies": enemies,
            "brainActive": integer(values, "brain.active"),
            "brainDesired": integer(values, "brain.desired"),
            "controller": {
                "armed": boolean(values, "controller.armed"),
                "mode": values.get("controller.mode", ""),
                "destinationActive": boolean(
                    values, "controller.destination_active"
                ),
                "destinationDistance": number(
                    values, "controller.destination_distance", -1.0
                ),
                "localCastAttempts": integer(
                    values, "controller.local_cast_attempts"
                ),
                "localCastAccepted": integer(
                    values, "controller.local_cast_accepted"
                ),
                "runEnded": boolean(values, "controller.run_ended"),
                "completedWaves": completed_waves,
                "wavePlans": wave_plans,
            },
        }
        local_id = snapshot["player"]["participantId"]
        if local_id <= 0:
            local_id = int(self.config.participant_id, 16)
            snapshot["player"]["participantId"] = local_id
        self.fighter_names_by_id[local_id] = self.config.player_name
        for row in bots:
            if row["id"] > 0 and row["name"]:
                self.fighter_names_by_id[row["id"]] = row["name"]
        self.furthest_wave = max(self.furthest_wave, snapshot["wave"])
        return snapshot

    def list_openables(self) -> list[dict[str, Any]]:
        values = self.values(OPENABLE_PROBE)
        obstacles = []
        for index in range(1, integer(values, "count") + 1):
            prefix = f"obstacle.{index}."
            start = (
                number(values, prefix + "start_x"),
                number(values, prefix + "start_y"),
            )
            end = (
                number(values, prefix + "end_x"),
                number(values, prefix + "end_y"),
            )
            obstacles.append(
                {
                    "object": integer(values, prefix + "object"),
                    "record": integer(values, prefix + "record"),
                    "start": start,
                    "end": end,
                    "midpoint": (
                        (start[0] + end[0]) * 0.5,
                        (start[1] + end[1]) * 0.5,
                    ),
                }
            )
        return obstacles

    def select_route_gate(
        self,
        start: tuple[float, float],
        solomon: tuple[float, float],
        obstacles: list[dict[str, Any]],
    ) -> dict[str, Any]:
        route_x, route_y = normalize(
            solomon[0] - start[0],
            solomon[1] - start[1],
        )
        route_length = distance(start, solomon)
        candidates = []
        for obstacle in obstacles:
            midpoint = obstacle["midpoint"]
            relative_x = midpoint[0] - start[0]
            relative_y = midpoint[1] - start[1]
            projection = relative_x * route_x + relative_y * route_y
            perpendicular = abs(
                relative_x * -route_y + relative_y * route_x
            )
            if 40.0 < projection < route_length - 80.0:
                candidates.append(
                    (perpendicular, projection, obstacle)
                )
        if not candidates:
            raise BotMatchFailure(
                "No native openable obstacle lies on the slot-0-to-Solomon "
                f"route. openables={obstacles}"
            )
        candidates.sort(key=lambda row: (row[0], row[1]))
        anchor = candidates[0][2]["midpoint"]
        cluster = [
            row[2]
            for row in candidates
            if distance(row[2]["midpoint"], anchor) <= 140.0
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
        segment_vectors = [
            (
                obstacle["end"][0] - obstacle["start"][0],
                obstacle["end"][1] - obstacle["start"][1],
            )
            for obstacle in cluster
        ]
        reference = max(
            segment_vectors,
            key=lambda vector: math.hypot(vector[0], vector[1]),
        )
        reference_x, reference_y = normalize(*reference)
        tangent_x = 0.0
        tangent_y = 0.0
        for vector_x, vector_y in segment_vectors:
            unit_x, unit_y = normalize(vector_x, vector_y)
            if unit_x * reference_x + unit_y * reference_y < 0.0:
                unit_x = -unit_x
                unit_y = -unit_y
            weight = math.hypot(vector_x, vector_y)
            tangent_x += unit_x * weight
            tangent_y += unit_y * weight
        tangent_x, tangent_y = normalize(tangent_x, tangent_y)
        transit_x, transit_y = -tangent_y, tangent_x
        if (
            (solomon[0] - midpoint[0]) * transit_x
            + (solomon[1] - midpoint[1]) * transit_y
            < 0.0
        ):
            transit_x = -transit_x
            transit_y = -transit_y
        return {
            "routeUnit": (transit_x, transit_y),
            "solomonRouteUnit": (route_x, route_y),
            "gateTangentUnit": (tangent_x, tangent_y),
            "routeLength": route_length,
            "midpoint": midpoint,
            "segments": cluster,
            "candidateCount": len(candidates),
        }

    def gate_formation(
        self,
        front_center: tuple[float, float],
        transit_unit: tuple[float, float],
    ) -> dict[str, tuple[float, float]]:
        spacing = self.config.gate_formation_spacing
        tangent = (-transit_unit[1], transit_unit[0])
        offsets = (
            (0.0, -0.5),
            (0.0, 0.5),
            (-1.0, -0.5),
            (-1.0, 0.5),
        )
        fighter_keys = [
            LOCAL_FIGHTER_KEY,
            *(fighter.name for fighter in self.config.bots),
        ]
        return {
            key: (
                front_center[0]
                + transit_unit[0] * forward * spacing
                + tangent[0] * lateral * spacing,
                front_center[1]
                + transit_unit[1] * forward * spacing
                + tangent[1] * lateral * spacing,
            )
            for key, (forward, lateral) in zip(
                fighter_keys,
                offsets,
                strict=True,
            )
        }

    def gate_convoy_destinations(
        self,
        gate: dict[str, Any],
    ) -> dict[str, tuple[float, float]]:
        midpoint = tuple(gate["midpoint"])
        route = tuple(gate["routeUnit"])
        tangent = (-route[1], route[0])
        spacing = self.config.gate_formation_spacing
        offsets = (
            (self.config.gate_exit_distance + 2.0 * spacing, 0.0),
            (self.config.gate_exit_distance + spacing, -spacing),
            (self.config.gate_exit_distance + spacing, spacing),
            (self.config.gate_exit_distance, 0.0),
        )
        fighter_keys = [
            LOCAL_FIGHTER_KEY,
            *(fighter.name for fighter in self.config.bots),
        ]
        return {
            key: (
                midpoint[0] + route[0] * forward
                + tangent[0] * lateral,
                midpoint[1] + route[1] * forward
                + tangent[1] * lateral,
            )
            for key, (forward, lateral) in zip(
                fighter_keys,
                offsets,
                strict=True,
            )
        }

    def plan_gate_convoy(
        self,
        gate: dict[str, Any],
        holding_points: dict[str, tuple[float, float]],
    ) -> dict[str, Any]:
        midpoint = tuple(gate["midpoint"])
        route = tuple(gate["routeUnit"])
        tangent = tuple(gate["gateTangentUnit"])
        positions = self.fighter_position_record(self.snapshot())
        alignment_progress_threshold = -(
            self.config.gate_approach_distance
            + self.config.gate_formation_spacing / 2.0
        )
        fighter_frames = {}
        for fighter_key, row in positions.items():
            position = (row["x"], row["y"])
            progress = signed_gate_progress(
                position,
                midpoint,
                route,
            )
            lateral = gate_lateral_offset(
                position,
                midpoint,
                tangent,
            )
            fighter_frames[fighter_key] = {
                "signedProgress": progress,
                "lateralOffset": lateral,
                "needsAlignment": (
                    progress < alignment_progress_threshold
                    or abs(lateral)
                    > self.config.gate_alignment_lateral_tolerance
                ),
            }
        direct = sorted(
            (
                key
                for key, row in fighter_frames.items()
                if not row["needsAlignment"]
            ),
            key=lambda key: fighter_frames[key]["signedProgress"],
            reverse=True,
        )
        aligned = sorted(
            (
                key
                for key, row in fighter_frames.items()
                if row["needsAlignment"]
            ),
            key=lambda key: fighter_frames[key]["signedProgress"],
            reverse=True,
        )
        order = [*direct, *aligned]
        points = list(holding_points.values())
        return {
            "order": order,
            "fighters": fighter_frames,
            "alignmentProgressThreshold":
                alignment_progress_threshold,
            "alignmentLateralTolerance":
                self.config.gate_alignment_lateral_tolerance,
            "destinations": dict(
                zip(order, points, strict=True)
            ),
        }

    def formation(
        self,
        center: tuple[float, float],
        route_unit: tuple[float, float],
        spacing: float,
    ) -> dict[str, tuple[float, float]]:
        perpendicular = (-route_unit[1], route_unit[0])
        fighter_keys = [
            LOCAL_FIGHTER_KEY,
            *(fighter.name for fighter in self.config.bots),
        ]
        offsets = (
            (-0.5, -0.5),
            (-0.5, 0.5),
            (0.5, -0.5),
            (0.5, 0.5),
        )
        return {
            key: (
                center[0]
                + route_unit[0] * forward * spacing
                + perpendicular[0] * lateral * spacing,
                center[1]
                + route_unit[1] * forward * spacing
                + perpendicular[1] * lateral * spacing,
            )
            for key, (forward, lateral) in zip(
                fighter_keys,
                offsets,
                strict=True,
            )
        }

    def assign_destinations_without_crossing(
        self,
        destinations: dict[str, tuple[float, float]],
    ) -> dict[str, tuple[float, float]]:
        snapshot = self.snapshot()
        positions = self.fighter_position_record(snapshot)
        fighter_keys = list(destinations)
        if set(positions) != set(fighter_keys):
            raise BotMatchFailure(
                "Cannot assign group destinations without all four "
                f"fighters: positions={list(positions)}, "
                f"destinations={fighter_keys}"
            )
        points = tuple(destinations.values())

        def score(
            assignment: tuple[tuple[float, float], ...],
        ) -> tuple[int, float]:
            segments = [
                (
                    (
                        positions[key]["x"],
                        positions[key]["y"],
                    ),
                    target,
                )
                for key, target in zip(
                    fighter_keys,
                    assignment,
                    strict=True,
                )
            ]
            crossings = sum(
                segments_properly_cross(
                    left[0],
                    left[1],
                    right[0],
                    right[1],
                )
                for left_index, left in enumerate(segments)
                for right in segments[left_index + 1:]
            )
            travel = sum(
                distance(start, target)
                for start, target in segments
            )
            return crossings, travel

        best = min(permutations(points), key=score)
        return dict(zip(fighter_keys, best, strict=True))

    def command_group(
        self,
        destinations: dict[str, tuple[float, float]],
        *,
        arrival_radius: float,
    ) -> dict[str, str]:
        positions = self.fighter_position_record(self.snapshot())
        needs_move = {
            key: (
                key not in positions
                or distance(
                    (positions[key]["x"], positions[key]["y"]),
                    target,
                )
                > arrival_radius + ARRIVAL_DISTANCE_EPSILON
            )
            for key, target in destinations.items()
        }
        self.stop_group()
        local = destinations[LOCAL_FIGHTER_KEY]
        local_arrival_radius = min(
            arrival_radius,
            self.config.gate_parking_arrival_radius,
        )
        local_command = (
            f"""
controller.arrival_radius = {local_arrival_radius:.9f}
controller.destination = {{
  x = {local[0]:.9f},
  y = {local[1]:.9f},
}}"""
            if needs_move[LOCAL_FIGHTER_KEY]
            else """
controller.destination = nil
controller.destination_distance = 0"""
        )
        bot_rows = ",\n".join(
            (
                f"[{json.dumps(name)}] = "
                f"{{ x = {point[0]:.9f}, y = {point[1]:.9f} }}"
            )
            for name, point in destinations.items()
            if name != LOCAL_FIGHTER_KEY and needs_move[name]
        )
        expected_bot_moves = len(
            [
                key
                for key, move in needs_move.items()
                if key != LOCAL_FIGHTER_KEY and move
            ]
        )
        values = self.values(
            f"""
local controller = assert(
  rawget(_G, "{CONTROLLER_GLOBAL}"),
  "slot-0 controller unavailable")
{local_command}
local destinations = {{
  {bot_rows}
}}
local accepted = 0
local failures = {{}}
for _, handle in ipairs(sd.bots.list() or {{}}) do
  local id = tonumber(handle:participant_id()) or 0
  local state = sd.bots.get_participant_state(id) or {{}}
  local target = destinations[tostring(state.name or "")]
  if target ~= nil then
    local ok, moved, err =
      pcall(handle.move_to, handle, target.x, target.y)
    if ok and moved == true then
      accepted = accepted + 1
    else
      failures[#failures + 1] =
        tostring(state.name) .. ":" ..
        tostring(err or moved)
    end
  end
end
print("accepted=" .. tostring(accepted))
print("failures=" .. table.concat(failures, ","))
"""
        )
        if (
            integer(values, "accepted") != expected_bot_moves
            or values.get("failures")
        ):
            raise BotMatchFailure(
                f"Group movement command was rejected: {values}"
            )
        values["skipped"] = ",".join(
            key for key, move in needs_move.items() if not move
        )
        return values

    def validate_gate_convoy_destinations(
        self,
        destinations: dict[str, tuple[float, float]],
    ) -> dict[str, str]:
        probes = "\n".join(
            (
                f"local ok_{index}, clear_{index} = pcall("
                f"sd.nav.test_segment, "
                f"{point[0]:.9f}, {point[1]:.9f}, "
                f"{point[0]:.9f}, {point[1]:.9f})\n"
                f'print("probe.{index}.ok=" .. tostring(ok_{index}))\n'
                f'print("probe.{index}.clear=" .. '
                f"tostring(clear_{index}))"
            )
            for index, point in enumerate(
                destinations.values(),
                start=1,
            )
        )
        values = self.values(probes)
        failures = [
            key
            for index, key in enumerate(destinations, start=1)
            if not boolean(values, f"probe.{index}.ok")
            or not boolean(values, f"probe.{index}.clear")
        ]
        if failures:
            raise BotMatchFailure(
                "Native path placement rejected gate convoy holding "
                f"points for {failures}: {values}"
            )
        return values

    def validate_group_segments(
        self,
        destinations: dict[str, tuple[float, float]],
    ) -> dict[str, Any]:
        positions = self.fighter_position_record(self.snapshot())
        if set(positions) != set(destinations):
            raise BotMatchFailure(
                "Cannot validate group paths without all four fighters: "
                f"positions={list(positions)}, "
                f"destinations={list(destinations)}"
            )
        probes = "\n".join(
            (
                f"local ok_{index}, clear_{index} = pcall("
                f"sd.nav.test_segment, "
                f"{positions[key]['x']:.9f}, "
                f"{positions[key]['y']:.9f}, "
                f"{target[0]:.9f}, {target[1]:.9f})\n"
                f'print("probe.{index}.ok=" .. tostring(ok_{index}))\n'
                f'print("probe.{index}.clear=" .. '
                f"tostring(clear_{index}))"
            )
            for index, (key, target) in enumerate(
                destinations.items(),
                start=1,
            )
        )
        values = self.values(probes)
        fighters = {
            key: {
                "start": [
                    positions[key]["x"],
                    positions[key]["y"],
                ],
                "destination": list(target),
                "queryOk": boolean(
                    values,
                    f"probe.{index}.ok",
                ),
                "traversable": boolean(
                    values,
                    f"probe.{index}.clear",
                ),
            }
            for index, (key, target) in enumerate(
                destinations.items(),
                start=1,
            )
        }
        blocked_count = sum(
            not row["queryOk"] or not row["traversable"]
            for row in fighters.values()
        )
        total_distance = sum(
            distance(
                tuple(row["start"]),
                tuple(row["destination"]),
            )
            for row in fighters.values()
        )
        return {
            "allTraversable": blocked_count == 0,
            "blockedCount": blocked_count,
            "totalDistance": total_distance,
            "fighters": fighters,
        }

    def plan_hub_gather(
        self,
        solomon: tuple[float, float],
        gate: dict[str, Any],
        dig_route: tuple[float, float],
    ) -> dict[str, Any]:
        gate_distance = distance(solomon, tuple(gate["midpoint"]))
        maximum_distance = min(
            self.config.gather_distance
            + self.config.gather_search_limit,
            gate_distance - self.config.gate_exit_distance,
        )
        if maximum_distance <= 0:
            raise BotMatchFailure(
                "No dig-side hub gather space remains between Solomon "
                "and the configured gate exit."
            )

        candidate_distances = []
        candidate_distance = min(
            self.config.gather_distance,
            maximum_distance,
        )
        while candidate_distance <= maximum_distance + 0.001:
            candidate_distances.append(candidate_distance)
            candidate_distance += self.config.gather_search_step
        if (
            not candidate_distances
            or maximum_distance - candidate_distances[-1] > 0.001
        ):
            candidate_distances.append(maximum_distance)

        attempts = []
        selected_attempt = None
        for candidate_distance in candidate_distances:
            center = (
                solomon[0] - dig_route[0] * candidate_distance,
                solomon[1] - dig_route[1] * candidate_distance,
            )
            destinations = self.assign_destinations_without_crossing(
                self.formation(
                    center,
                    dig_route,
                    self.config.gather_spacing,
                )
            )
            attempt: dict[str, Any] = {
                "distanceFromSolomon": candidate_distance,
                "center": list(center),
                "destinations": destinations,
            }
            try:
                attempt["placement"] = (
                    self.validate_gate_convoy_destinations(
                        destinations
                    )
                )
            except BotMatchFailure as error:
                attempt["placementError"] = str(error)
                attempts.append(attempt)
                continue

            attempt["segments"] = self.validate_group_segments(
                destinations
            )
            attempt["routeScore"] = [
                attempt["segments"]["blockedCount"],
                attempt["segments"]["totalDistance"],
                candidate_distance,
            ]
            attempts.append(attempt)
            if (
                selected_attempt is None
                or tuple(attempt["routeScore"])
                < tuple(selected_attempt["routeScore"])
            ):
                selected_attempt = attempt
            if attempt["segments"]["allTraversable"]:
                break

        if selected_attempt is None:
            raise BotMatchFailure(
                "No natively placed four-fighter hub gather formation "
                f"was found: {attempts}"
            )
        return {
            "configuredTargetDistance":
                self.config.gather_distance,
            "routeCapped":
                maximum_distance < self.config.gather_distance,
            "selectedDistance":
                selected_attempt["distanceFromSolomon"],
            "gateDistance": gate_distance,
            "attempts": attempts,
            "selectionRule": [
                "blockedNativeSegments",
                "aggregateTravelDistance",
                "distanceFromSolomon",
            ],
            "destinations": selected_attempt["destinations"],
            "selectedAttemptIndex":
                attempts.index(selected_attempt),
        }

    def command_fighter(
        self,
        fighter_key: str,
        destination: tuple[float, float],
    ) -> dict[str, str]:
        arrival_radius = self.config.gate_parking_arrival_radius
        if fighter_key == LOCAL_FIGHTER_KEY:
            values = self.values(
                f"""
local controller = assert(
  rawget(_G, "{CONTROLLER_GLOBAL}"),
  "slot-0 controller unavailable")
controller.arrival_radius = {arrival_radius:.9f}
controller.destination = {{
  x = {destination[0]:.9f},
  y = {destination[1]:.9f},
}}
print("accepted=true")
"""
            )
        else:
            values = self.values(
                f"""
local wanted = {json.dumps(fighter_key)}
local accepted = false
local error_message = "fighter handle unavailable"
for _, handle in ipairs(sd.bots.list() or {{}}) do
  local id = tonumber(handle:participant_id()) or 0
  local state = sd.bots.get_participant_state(id) or {{}}
  if tostring(state.name or "") == wanted then
    local ok, moved, err = pcall(
      handle.move_to,
      handle,
      {destination[0]:.9f},
      {destination[1]:.9f})
    accepted = ok and moved == true
    error_message = tostring(err or moved)
    break
  end
end
print("accepted=" .. tostring(accepted))
print("error=" .. tostring(error_message))
"""
            )
        if not boolean(values, "accepted"):
            raise BotMatchFailure(
                f"Gate convoy command failed for {fighter_key}: {values}"
            )
        return values

    def wait_fighter_destination(
        self,
        fighter_key: str,
        destination: tuple[float, float],
    ) -> dict[str, Any]:
        deadline = time.monotonic() + self.config.route_timeout_seconds
        stable = 0
        samples = []
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            teleports = self.stuck_teleport_lines()
            if teleports:
                raise BotMatchFailure(
                    "Gate convoy used the forbidden stuck-teleport "
                    f"failsafe: {teleports}; "
                    f"lastSample={samples[-1] if samples else None}"
                )
            last = self.snapshot()
            positions = self.fighter_position_record(last)
            row = positions.get(fighter_key)
            remaining = (
                distance((row["x"], row["y"]), destination)
                if row is not None
                else math.inf
            )
            sample = {
                "sampledAt": last["sampledAt"],
                "fighter": fighter_key,
                "destination": destination,
                "distance": remaining,
                "position": row,
                "solomon": last["solomon"],
            }
            samples.append(sample)
            if last["solomon"]["acquired"]:
                raise BotMatchFailure(
                    "Solomon acquired a fighter during the gate convoy: "
                    f"{sample}"
                )
            arrived = (
                row is not None
                and remaining
                <= self.config.gate_parking_arrival_radius
            )
            stable = stable + 1 if arrived else 0
            if stable >= 3:
                return {
                    "fighter": fighter_key,
                    "arrivalRadius":
                        self.config.gate_parking_arrival_radius,
                    "final": sample,
                    "samples": samples,
                    "stuckTeleports": 0,
                }
            time.sleep(0.25)
        raise BotMatchFailure(
            f"Gate convoy fighter {fighter_key} timed out: "
            f"{samples[-1] if samples else last}"
        )

    def transit_gate_convoy(
        self,
        gate: dict[str, Any],
        destinations: dict[str, tuple[float, float]],
        fighter_plan: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        midpoint = tuple(gate["midpoint"])
        route = tuple(gate["routeUnit"])
        crossing = (
            midpoint[0] + route[0] * self.config.gate_exit_distance,
            midpoint[1] + route[1] * self.config.gate_exit_distance,
        )
        crossing_placement = self.validate_gate_convoy_destinations(
            {"crossing": crossing}
        )
        alignment = (
            midpoint[0]
            - route[0] * self.config.gate_approach_distance,
            midpoint[1]
            - route[1] * self.config.gate_approach_distance,
        )
        alignment_placement = self.validate_gate_convoy_destinations(
            {"alignment": alignment}
        )
        stops = [self.stop_group()]
        legs = []
        for fighter_key, holding_destination in destinations.items():
            alignment_command = None
            alignment_arrival = None
            if fighter_plan[fighter_key]["needsAlignment"]:
                alignment_command = self.command_fighter(
                    fighter_key,
                    alignment,
                )
                alignment_arrival = self.wait_fighter_destination(
                    fighter_key,
                    alignment,
                )
            crossing_command = self.command_fighter(
                fighter_key,
                crossing,
            )
            crossing_arrival = self.wait_fighter_destination(
                fighter_key,
                crossing,
            )
            holding_command = None
            holding_arrival = crossing_arrival
            if distance(crossing, holding_destination) > 0.001:
                holding_command = self.command_fighter(
                    fighter_key,
                    holding_destination,
                )
                holding_arrival = self.wait_fighter_destination(
                    fighter_key,
                    holding_destination,
                )
            legs.append(
                {
                    "fighter": fighter_key,
                    "alignment": alignment_arrival,
                    "alignmentCommand": alignment_command,
                    "crossing": crossing_arrival,
                    "crossingCommand": crossing_command,
                    "holding": holding_arrival,
                    "holdingCommand": holding_command,
                }
            )
            stops.append(self.stop_group())
        return {
            "order": list(destinations),
            "alignment": alignment,
            "alignmentPlacement": alignment_placement,
            "crossing": crossing,
            "crossingPlacement": crossing_placement,
            "legs": legs,
            "stops": stops,
            "stuckTeleports": 0,
        }

    def fighter_position_record(
        self,
        snapshot: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        rows = {
            LOCAL_FIGHTER_KEY: {
                "name": self.config.player_name,
                "participantId": snapshot["player"]["participantId"],
                "slot": 0,
                "x": snapshot["player"]["x"],
                "y": snapshot["player"]["y"],
                "hp": snapshot["player"]["hp"],
                "maxHp": snapshot["player"]["maxHp"],
            }
        }
        for bot in snapshot["bots"]:
            rows[bot["name"]] = {
                "name": bot["name"],
                "participantId": bot["id"],
                "slot": bot["slot"],
                "x": bot["x"],
                "y": bot["y"],
                "hp": bot["hp"],
                "maxHp": bot["maxHp"],
            }
        return rows

    def stop_group(self) -> dict[str, str]:
        values = self.values(
            f"""
local controller = assert(
  rawget(_G, "{CONTROLLER_GLOBAL}"),
  "slot-0 controller unavailable")
controller.destination = nil
controller.destination_distance = 0
pcall(sd.input.hold_movement_frames, 0, 0, 1)
local stopped = 0
local failures = {{}}
for _, handle in ipairs(sd.bots.list() or {{}}) do
  local ok, accepted, err = pcall(handle.stop, handle)
  if ok and accepted == true then
    stopped = stopped + 1
  else
    failures[#failures + 1] =
      tostring(handle:participant_id()) .. ":" ..
      tostring(err or accepted)
  end
end
print("stopped=" .. tostring(stopped))
print("failures=" .. table.concat(failures, ","))
"""
        )
        if integer(values, "stopped") != 3 or values.get("failures"):
            raise BotMatchFailure(
                f"Group movement stop was rejected: {values}"
            )
        return values

    def stop_fighter(self, fighter_key: str) -> dict[str, str]:
        if fighter_key == LOCAL_FIGHTER_KEY:
            values = self.values(
                f"""
local controller = assert(
  rawget(_G, "{CONTROLLER_GLOBAL}"),
  "slot-0 controller unavailable")
controller.destination = nil
controller.destination_distance = 0
pcall(sd.input.hold_movement_frames, 0, 0, 1)
print("accepted=true")
"""
            )
        else:
            values = self.values(
                f"""
local wanted = {json.dumps(fighter_key)}
local accepted = false
for _, handle in ipairs(sd.bots.list() or {{}}) do
  local id = tonumber(handle:participant_id()) or 0
  local state = sd.bots.get_participant_state(id) or {{}}
  if tostring(state.name or "") == wanted then
    local ok, stopped = pcall(handle.stop, handle)
    accepted = ok and stopped == true
    break
  end
end
print("accepted=" .. tostring(accepted))
"""
            )
        if not boolean(values, "accepted"):
            raise BotMatchFailure(
                f"Movement stop failed for {fighter_key}: {values}"
            )
        return values

    def reconcile_group_holds(
        self,
        accepted_fighters: set[str],
        released_fighters: set[str],
        destinations: dict[str, tuple[float, float]],
    ) -> list[str]:
        reissued = []
        for fighter_key in sorted(
            released_fighters - accepted_fighters
        ):
            self.command_fighter(
                fighter_key,
                destinations[fighter_key],
            )
            released_fighters.remove(fighter_key)
            reissued.append(fighter_key)
        for fighter_key in sorted(
            accepted_fighters - released_fighters
        ):
            self.stop_fighter(fighter_key)
            released_fighters.add(fighter_key)
        return reissued

    def wait_gate_transit(
        self,
        gate: dict[str, Any],
    ) -> dict[str, Any]:
        midpoint = tuple(gate["midpoint"])
        transit_unit = tuple(gate["routeUnit"])
        minimum_progress = (
            self.config.gate_exit_distance
            - self.config.gate_arrival_radius
        )
        deadline = time.monotonic() + self.config.route_timeout_seconds
        stable = 0
        last: dict[str, Any] = {}
        samples = []
        while time.monotonic() < deadline:
            teleports = self.stuck_teleport_lines()
            if teleports:
                raise BotMatchFailure(
                    "Gate transit used the forbidden stuck-teleport "
                    f"failsafe: {teleports}"
                )
            last = self.snapshot()
            positions = self.fighter_position_record(last)
            progress = {
                key: signed_gate_progress(
                    (row["x"], row["y"]),
                    midpoint,
                    transit_unit,
                )
                for key, row in positions.items()
            }
            sample = {
                "sampledAt": last["sampledAt"],
                "wave": last["wave"],
                "minimumSignedProgress": minimum_progress,
                "signedProgress": progress,
                "positions": positions,
                "solomon": last["solomon"],
            }
            samples.append(sample)
            if last["solomon"]["acquired"]:
                raise BotMatchFailure(
                    "Solomon acquired a fighter before gate transit "
                    f"completed: {sample}"
                )
            arrived = (
                len(progress) == 4
                and all(
                    value >= minimum_progress
                    for value in progress.values()
                )
            )
            stable = stable + 1 if arrived else 0
            if stable >= 3:
                stopped = self.stop_group()
                teleports = self.stuck_teleport_lines()
                if teleports:
                    raise BotMatchFailure(
                        "Gate transit used the forbidden stuck-teleport "
                        f"failsafe: {teleports}"
                    )
                return {
                    "label": "gate-exit",
                    "minimumSignedProgress": minimum_progress,
                    "final": sample,
                    "samples": samples,
                    "stop": stopped,
                    "stuckTeleports": 0,
                }
            time.sleep(0.25)
        raise BotMatchFailure(
            "Four-fighter signed gate transit timed out: "
            f"{samples[-1] if samples else last}"
        )

    def wait_gate_approach(
        self,
        gate: dict[str, Any],
        destinations: dict[str, tuple[float, float]],
    ) -> dict[str, Any]:
        midpoint = tuple(gate["midpoint"])
        transit_unit = tuple(gate["routeUnit"])
        tangent_unit = tuple(gate["gateTangentUnit"])
        # This is a staging region, not an exact parking check. Native A*
        # endpoints can stop one collision-spaced row behind a nominal point
        # when another wizard owns the final cell. The convoy stage that
        # follows realigns and moves each fighter individually.
        minimum_progress = -(
            self.config.gate_approach_distance
            + 2.0 * self.config.gate_formation_spacing
        )
        maximum_progress = -(
            self.config.gate_approach_distance
            - self.config.gate_arrival_radius
        )
        endpoint_offsets = [
            abs(
                gate_lateral_offset(
                    tuple(point),
                    midpoint,
                    tangent_unit,
                )
            )
            for segment in gate["segments"]
            for point in (segment["start"], segment["end"])
        ]
        maximum_lateral_offset = (
            max(endpoint_offsets)
            + self.config.gate_formation_spacing
        )
        deadline = time.monotonic() + self.config.route_timeout_seconds
        stable = 0
        last: dict[str, Any] = {}
        samples = []
        released = set()
        while time.monotonic() < deadline:
            teleports = self.stuck_teleport_lines()
            if teleports:
                raise BotMatchFailure(
                    "Gate approach used the forbidden stuck-teleport "
                    f"failsafe: {teleports}"
                )
            last = self.snapshot()
            positions = self.fighter_position_record(last)
            progress = {}
            lateral_offsets = {}
            destination_distances = {}
            for key, row in positions.items():
                position = (row["x"], row["y"])
                progress[key] = signed_gate_progress(
                    position,
                    midpoint,
                    transit_unit,
                )
                lateral_offsets[key] = gate_lateral_offset(
                    position,
                    midpoint,
                    tangent_unit,
                )
                if key in destinations:
                    destination_distances[key] = distance(
                        position,
                        destinations[key],
                    )
            sample = {
                "sampledAt": last["sampledAt"],
                "wave": last["wave"],
                "signedProgressBand": [
                    minimum_progress,
                    maximum_progress,
                ],
                "maximumLateralOffset": maximum_lateral_offset,
                "signedProgress": progress,
                "lateralOffsets": lateral_offsets,
                "destinationDistances": destination_distances,
                "positions": positions,
                "solomon": last["solomon"],
            }
            samples.append(sample)
            if last["solomon"]["acquired"]:
                raise BotMatchFailure(
                    "Solomon acquired a fighter before the gate approach "
                    f"regrouped: {sample}"
                )
            accepted_fighters = {
                key
                for key in progress
                if (
                    key in destinations
                    and minimum_progress
                    <= progress[key]
                    <= maximum_progress
                    and abs(lateral_offsets[key])
                    <= maximum_lateral_offset
                )
            }
            reissued = self.reconcile_group_holds(
                accepted_fighters,
                released,
                destinations,
            )
            sample["releasedFighters"] = sorted(released)
            sample["reissuedFighters"] = reissued
            arrived = (
                len(progress) == 4
                and all(
                    minimum_progress <= value <= maximum_progress
                    for value in progress.values()
                )
                and all(
                    abs(value) <= maximum_lateral_offset
                    for value in lateral_offsets.values()
                )
            )
            stable = stable + 1 if arrived else 0
            if stable >= 3:
                return {
                    "label": "gate-approach",
                    "signedProgressBand": [
                        minimum_progress,
                        maximum_progress,
                    ],
                    "maximumLateralOffset": maximum_lateral_offset,
                    "final": sample,
                    "samples": samples,
                    "releasedFighters": sorted(released),
                    "stuckTeleports": 0,
                }
            time.sleep(0.25)
        raise BotMatchFailure(
            "Four-fighter gate approach regroup timed out: "
            f"{samples[-1] if samples else last}"
        )

    def wait_group(
        self,
        destinations: dict[str, tuple[float, float]],
        *,
        arrival_radius: float,
        label: str,
        require_unacquired: bool,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + self.config.route_timeout_seconds
        stable = 0
        last: dict[str, Any] = {}
        samples = []
        released = set()
        while time.monotonic() < deadline:
            last = self.snapshot()
            positions = self.fighter_position_record(last)
            distances = {
                key: distance(
                    (positions[key]["x"], positions[key]["y"]),
                    target,
                )
                for key, target in destinations.items()
                if key in positions
            }
            sample = {
                "sampledAt": last["sampledAt"],
                "wave": last["wave"],
                "distances": distances,
                "positions": positions,
                "solomon": last["solomon"],
            }
            samples.append(sample)
            if require_unacquired and last["solomon"]["acquired"]:
                raise BotMatchFailure(
                    f"Solomon acquired a fighter before {label} regrouped: "
                    f"{sample}"
                )
            accepted_fighters = {
                key
                for key, remaining in distances.items()
                if within_arrival_radius(
                    remaining,
                    arrival_radius,
                )
            }
            reissued = self.reconcile_group_holds(
                accepted_fighters,
                released,
                destinations,
            )
            sample["releasedFighters"] = sorted(released)
            sample["reissuedFighters"] = reissued
            arrived = (
                len(distances) == 4
                and all(
                    within_arrival_radius(value, arrival_radius)
                    for value in distances.values()
                )
            )
            stable = stable + 1 if arrived else 0
            if stable >= 3:
                return {
                    "label": label,
                    "arrivalRadius": arrival_radius,
                    "final": sample,
                    "samples": samples,
                    "releasedFighters": sorted(released),
                }
            time.sleep(0.25)
        raise BotMatchFailure(
            f"Four-fighter regroup timed out at {label}: "
            f"{samples[-1] if samples else last}"
        )

    def stuck_teleport_lines(self) -> list[str]:
        if not self.loader_log.is_file():
            return []
        return [
            line
            for line in self.loader_log.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
            if STUCK_TELEPORT_MARKER in line
        ]

    def capture(
        self,
        label: str,
        *,
        armed: bool = False,
    ) -> dict[str, Any]:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", label):
            raise BotMatchFailure(f"Unsafe screenshot label: {label!r}")
        raw = self.screenshot_directory / f"{label}.bmp"
        output = self.screenshot_directory / f"{label}.png"
        output.unlink(missing_ok=True)
        if not armed:
            raw.unlink(missing_ok=True)
        deadline = time.monotonic() + 15
        capture_attempts = 0
        rejected_frames: list[dict[str, Any]] = []
        awaiting_armed_capture = armed
        last_error = ""
        while time.monotonic() < deadline:
            if awaiting_armed_capture:
                if not raw.is_file() or raw.stat().st_size < 10_000:
                    time.sleep(0.1)
                    continue
                awaiting_armed_capture = False
            else:
                raw.unlink(missing_ok=True)
                values = self.values(
                    f"""
local ok, err =
  sd.debug.capture_backbuffer({json.dumps(windows_path(raw))})
print("ok=" .. tostring(ok))
print("error=" .. tostring(err or ""))
"""
                )
                if values.get("ok") != "true":
                    raise BotMatchFailure(
                        f"Backbuffer capture {label} failed: {values}"
                    )
            capture_attempts += 1
            try:
                details = validate_backbuffer(raw, output)
            except VerificationFailure as error:
                last_error = str(error)
                rejected = self.screenshot_directory / (
                    f"{label}-rejected-{capture_attempts:02d}.bmp"
                )
                raw.replace(rejected)
                rejected_frames.append(
                    {
                        "path": str(rejected),
                        "sha256": sha256_file(rejected),
                        "error": last_error,
                    }
                )
                time.sleep(0.5)
                continue
            raw.unlink(missing_ok=True)
            return {
                "label": label,
                "path": str(output),
                "sha256": sha256_file(output),
                "captureAttempts": capture_attempts,
                "rejectedFrames": rejected_frames,
                **details,
            }
        raise BotMatchFailure(
            f"Backbuffer capture {label} did not produce an informative "
            f"frame within 15 seconds; last validation error: {last_error}"
        )

    def collect_wave_screenshot(self, wave: int) -> dict[str, Any]:
        existing = self.wave_screenshots.get(wave)
        if existing is not None:
            return existing
        artifact = self.capture(
            f"wave-{wave:02d}",
            armed=True,
        )
        self.wave_screenshots[wave] = artifact
        return artifact

    def collect_pending_wave_screenshots(self) -> list[int]:
        collected: list[int] = []
        for raw in sorted(self.screenshot_directory.glob("wave-*.bmp")):
            match = re.fullmatch(r"wave-(\d+)\.bmp", raw.name)
            if match is None or raw.stat().st_size < 10_000:
                continue
            wave = int(match.group(1))
            self.collect_wave_screenshot(wave)
            collected.append(wave)
        return collected

    def reset_damage_observations(self) -> dict[str, str]:
        values = self.values(
            r"""
print("enemy=" ..
  tostring(sd.debug.reset_enemy_damage_observations()))
print("player=" ..
  tostring(sd.debug.reset_player_damage_observations()))
"""
        )
        if values.get("enemy") != "true" or values.get("player") != "true":
            raise BotMatchFailure(
                f"Applied-damage observers did not arm: {values}"
            )
        return values

    def drain_damage(
        self,
        *,
        transition_retry_seconds: float = 0,
    ) -> None:
        output = self.lua(
            DAMAGE_DRAIN_PROBE,
            transition_retry_seconds=transition_retry_seconds,
        )
        for line in output.splitlines():
            parts = line.strip().split("|")
            if not parts:
                continue
            try:
                if parts[0] == "enemy" and len(parts) == 14:
                    row = {
                        "sequence": int(parts[1], 10),
                        "monotonicMs": int(parts[2], 10),
                        "sourceParticipantId": int(parts[3], 10),
                        "sourceNativeTypeId": int(parts[4], 10),
                        "sourceOwnerNativeTypeId": int(parts[5], 10),
                        "sourceGameplaySlot": int(parts[6], 10),
                        "targetActor": int(parts[7], 10),
                        "targetNetworkActorId": int(parts[8], 10),
                        "targetNativeTypeId": int(parts[9], 10),
                        "targetHpBefore": float(parts[10]),
                        "targetHpAfter": float(parts[11]),
                        "targetMaxHp": float(parts[12]),
                        "damage": float(parts[13]),
                    }
                    self.enemy_damage.append(row)
                    self.last_damage_monotonic = time.monotonic()
                elif parts[0] == "player" and len(parts) == 12:
                    row = {
                        "sequence": int(parts[1], 10),
                        "monotonicMs": int(parts[2], 10),
                        "targetParticipantId": int(parts[3], 10),
                        "targetGameplaySlot": int(parts[4], 10),
                        "targetActor": int(parts[5], 10),
                        "sourceActor": int(parts[6], 10),
                        "sourceNativeTypeId": int(parts[7], 10),
                        "targetHpBefore": float(parts[8]),
                        "targetHpAfter": float(parts[9]),
                        "targetMaxHp": float(parts[10]),
                        "damage": float(parts[11]),
                    }
                    self.player_damage.append(row)
                    self.last_damage_monotonic = time.monotonic()
            except ValueError as error:
                raise BotMatchFailure(
                    f"Malformed applied-damage row: {line!r}"
                ) from error

    def lethal_damage_cause(
        self,
        participant_id: int,
    ) -> dict[str, Any] | None:
        after_sequence = self.last_death_damage_sequence.get(
            participant_id,
            0,
        )
        matching = [
            row
            for row in self.player_damage
            if row["targetParticipantId"] == participant_id
            and row["sequence"] > after_sequence
        ]
        if not matching:
            return None
        lethal = [
            row for row in matching if row["targetHpAfter"] <= 0
        ]
        cause = (lethal or matching)[-1]
        self.last_death_damage_sequence[participant_id] = cause[
            "sequence"
        ]
        return {
            "observationSequence": cause["sequence"],
            "monotonicMs": cause["monotonicMs"],
            "sourceActor": cause["sourceActor"],
            "sourceNativeTypeId": cause["sourceNativeTypeId"],
            "damage": cause["damage"],
            "targetHpBefore": cause["targetHpBefore"],
            "targetHpAfter": cause["targetHpAfter"],
        }

    def update_match_observations(self, snapshot: dict[str, Any]) -> None:
        wave = snapshot["wave"]
        self.furthest_wave = max(self.furthest_wave, wave)
        summary = snapshot["waveSummary"]
        if wave > 0:
            self.wave_summaries[wave] = summary
        for plan in snapshot["controller"]["wavePlans"]:
            planned_wave = plan["wave"]
            if planned_wave > 0:
                self.wave_plans[planned_wave] = plan
                self.furthest_wave = max(
                    self.furthest_wave,
                    planned_wave,
                )
        for completion in snapshot["controller"]["completedWaves"]:
            completed_wave = completion["wave"]
            if completed_wave <= 0:
                continue
            self.completed_waves[completed_wave] = completion[
                "monotonicMs"
            ]
            completed_summary = self.wave_summaries.get(
                completed_wave
            )
            if completed_summary is not None:
                completed_summary["phase"] = "completed"
                completed_summary["alive"] = 0
                completed_summary["killed"] = completed_summary[
                    "spawned"
                ]
        live_composition = Counter(
            enemy["type"]
            for enemy in snapshot["enemies"]
            if not enemy["dead"] and enemy["hp"] > 0
        )

        positions = self.fighter_position_record(snapshot)
        for fighter in positions.values():
            participant_id = fighter["participantId"]
            if participant_id <= 0:
                continue
            alive = (
                fighter["hp"] > 0
                and not snapshot["controller"]["runEnded"]
            )
            previous = self.last_alive.get(participant_id)
            if previous is True and not alive:
                lethal_damage = self.lethal_damage_cause(
                    participant_id
                )
                self.death_transitions.append(
                    {
                        "sampledAt": snapshot["sampledAt"],
                        "wave": wave,
                        "participantId": participant_id,
                        "name": fighter["name"],
                        "enemyComposition": dict(live_composition),
                        "lethalDamage": lethal_damage,
                    }
                )
            elif previous is False and alive:
                self.respawn_transitions.append(
                    {
                        "sampledAt": snapshot["sampledAt"],
                        "wave": wave,
                        "participantId": participant_id,
                        "name": fighter["name"],
                        "hp": fighter["hp"],
                    }
                )
            self.last_alive[participant_id] = alive

    def real_solomon_trigger(self) -> dict[str, Any]:
        values = self.values(
            r"""
local ok, state = sd.hub.trigger_solomon_dig()
print("triggered=" .. tostring(ok))
print("state=" .. tostring(state and state.interaction_state or -1))
print("acquired=" ..
  tostring(state and state.participant_acquired or false))
print("target_slot=" ..
  tostring(state and state.target_gameplay_slot or -1))
print("actor=" .. tostring(state and state.actor_address or 0))
"""
        )
        return {
            "triggered": values.get("triggered") == "true",
            "state": integer(values, "state", -1),
            "acquired": values.get("acquired") == "true",
            "targetSlot": integer(values, "target_slot", -1),
            "actor": integer(values, "actor"),
        }

    def wait_for_real_trigger(self) -> dict[str, Any]:
        deadline = time.monotonic() + self.config.trigger_timeout_seconds
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            last = self.real_solomon_trigger()
            if (
                last["triggered"]
                and last["acquired"]
                and 0 <= last["targetSlot"] <= 3
                and last["state"] >= 1
            ):
                return last
            time.sleep(0.1)
        raise BotMatchFailure(
            "The real Solomon proximity/conversation path did not trigger: "
            f"{last}"
        )

    def monitor_match(self) -> dict[str, Any]:
        deadline = time.monotonic() + self.config.full_match_timeout_seconds
        started = False
        end_reason = ""
        last_snapshot: dict[str, Any] = {}
        last_progress = time.monotonic()
        last_wave = 0
        last_wave_signature: tuple[Any, ...] | None = None
        while time.monotonic() < deadline:
            snapshot = self.snapshot(transition_retry_seconds=15)
            last_snapshot = snapshot
            self.drain_damage(transition_retry_seconds=15)
            self.update_match_observations(snapshot)
            self.timeline.append(
                {
                    "sampledAt": snapshot["sampledAt"],
                    "scene": snapshot["sceneName"],
                    "wave": snapshot["wave"],
                    "phase": snapshot["wavePhase"],
                    "waveSummary": snapshot["waveSummary"],
                    "completedWaves": sorted(self.completed_waves),
                    "enemyCount": len(
                        [
                            row
                            for row in snapshot["enemies"]
                            if not row["dead"] and row["hp"] > 0
                        ]
                    ),
                    "fighters": self.fighter_position_record(snapshot),
                    "enemyDamageEdges": len(self.enemy_damage),
                    "playerDamageEdges": len(self.player_damage),
                }
            )
            if snapshot["wave"] > 0:
                started = True
            self.collect_pending_wave_screenshots()
            if snapshot["wave"] > last_wave:
                last_wave = snapshot["wave"]
                last_progress = time.monotonic()
                self.collect_wave_screenshot(last_wave)
            summary = snapshot["waveSummary"]
            wave_signature = (
                summary["wave"],
                summary["phase"],
                summary["remainingToSpawn"],
                summary["spawned"],
                summary["alive"],
                summary["killed"],
                tuple(
                    (
                        row["enemyType"],
                        row["spawned"],
                        row["alive"],
                        row["killed"],
                    )
                    for row in summary["composition"]
                ),
                tuple(sorted(self.completed_waves)),
            )
            if (
                last_wave_signature is not None
                and wave_signature != last_wave_signature
            ):
                last_progress = time.monotonic()
            last_wave_signature = wave_signature
            if self.last_damage_monotonic > last_progress:
                last_progress = self.last_damage_monotonic

            if self.mode == "smoke" and 1 in self.completed_waves:
                end_reason = "wave_1_cleared"
                break
            if (
                self.mode == "matrix"
                and started
                and self.matrix_damage_status()["complete"]
            ):
                end_reason = "four_fighter_damage_matrix_satisfied"
                break
            if (
                self.mode in ("matrix", "full")
                and started
                and (
                    snapshot["sceneName"] != "testrun"
                    or snapshot["controller"]["runEnded"]
                )
            ):
                end_reason = (
                    "native_run_ended"
                    if snapshot["controller"]["runEnded"]
                    else f"scene_transition:{snapshot['sceneName']}"
                )
                break
            if (
                self.mode in ("matrix", "full")
                and started
                and time.monotonic() - last_progress
                >= self.config.full_stall_timeout_seconds
            ):
                end_reason = "no_wave_or_damage_progress"
                break
            time.sleep(self.config.monitor_interval_seconds)
        if not end_reason:
            end_reason = "match_timeout"
        self.drain_damage(transition_retry_seconds=15)
        self.collect_pending_wave_screenshots()
        return {
            "reason": end_reason,
            "lastSnapshot": last_snapshot,
            "elapsedSeconds": time.monotonic() - self.started_monotonic,
        }

    def damage_summary(self) -> dict[str, Any]:
        dealt: defaultdict[int, float] = defaultdict(float)
        taken: defaultdict[int, float] = defaultdict(float)
        edges_dealt: Counter[int] = Counter()
        edges_taken: Counter[int] = Counter()
        for row in self.enemy_damage:
            participant_id = row["sourceParticipantId"]
            dealt[participant_id] += row["damage"]
            edges_dealt[participant_id] += 1
        for row in self.player_damage:
            participant_id = row["targetParticipantId"]
            taken[participant_id] += row["damage"]
            edges_taken[participant_id] += 1

        fighters = {}
        for participant_id, name in sorted(
            self.fighter_names_by_id.items(),
            key=lambda row: row[1],
        ):
            fighters[name] = {
                "participantId": participant_id,
                "damageDealt": dealt[participant_id],
                "damageDealtEdges": edges_dealt[participant_id],
                "damageTaken": taken[participant_id],
                "damageTakenEdges": edges_taken[participant_id],
                "deaths": len(
                    [
                        row
                        for row in self.death_transitions
                        if row["participantId"] == participant_id
                    ]
                ),
                "respawns": len(
                    [
                        row
                        for row in self.respawn_transitions
                        if row["participantId"] == participant_id
                    ]
                ),
            }
        return {
            "fighters": fighters,
            "enemyDamageEdges": len(self.enemy_damage),
            "playerDamageEdges": len(self.player_damage),
            "totalDamageDealt": sum(dealt.values()),
            "totalDamageTaken": sum(taken.values()),
        }

    def assert_smoke_damage(self) -> None:
        summary = self.damage_summary()["fighters"]
        damaging_synthetic = [
            name
            for name, row in summary.items()
            if name != self.config.player_name
            and row["damageDealtEdges"] > 0
            and row["damageDealt"] > 0
        ]
        if len(summary) != 4 or not damaging_synthetic:
            raise BotMatchFailure(
                "Wave-1 smoke requires four registered fighters and "
                "bot-attributed post-native damage; "
                f"damagingSynthetic={damaging_synthetic}, "
                f"summary={summary}"
            )

    def matrix_damage_status(self) -> dict[str, Any]:
        fighters = self.damage_summary()["fighters"]
        damaging = sorted(
            name
            for name, row in fighters.items()
            if row["damageDealtEdges"] > 0
            and row["damageDealt"] > 0
        )
        return {
            "registered": sorted(fighters),
            "damaging": damaging,
            "complete": (
                len(fighters) == 4
                and len(damaging) == 4
            ),
        }

    def assert_matrix_damage(self) -> None:
        status = self.matrix_damage_status()
        if not status["complete"]:
            raise BotMatchFailure(
                "Primary matrix requires an authoritative enemy-HP "
                "damage edge from slot 0 and every synthetic fighter; "
                f"status={status}, "
                f"summary={self.damage_summary()['fighters']}"
            )

    def run(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schemaVersion": 1,
            "mode": self.mode,
            "runIndex": self.run_index,
            "instance": self.instance,
            "startedAt": utc_now(),
            "configuration": str(self.config.source_path),
            "screenshots": {},
        }
        failure: Exception | None = None
        try:
            self.launch_game()
            result["launch"] = self.launch
            result["navigation"] = self.drive_to_hub()
            result["hubRoster"] = self.wait_for_roster()
            result["testrun"] = self.start_testrun()
            result["controller"] = self.arm_controller()
            result["runEntry"] = self.promote_bots_at_run_entry()

            initial = self.snapshot()
            solomon = (
                initial["solomon"]["x"],
                initial["solomon"]["y"],
            )
            start = (
                initial["player"]["x"],
                initial["player"]["y"],
            )
            if initial["solomon"]["acquired"]:
                raise BotMatchFailure(
                    "Solomon was already acquired before physical routing."
                )
            gate = self.select_route_gate(
                start,
                solomon,
                self.list_openables(),
            )
            result["gate"] = gate
            route = gate["routeUnit"]
            approach_center = (
                gate["midpoint"][0]
                - route[0] * self.config.gate_approach_distance,
                gate["midpoint"][1]
                - route[1] * self.config.gate_approach_distance,
            )
            approach = self.gate_formation(
                approach_center,
                route,
            )
            approach = self.assign_destinations_without_crossing(
                approach
            )
            self.command_group(
                approach,
                arrival_radius=self.config.gate_arrival_radius,
            )
            result["gateApproachDestinations"] = approach
            result["gateApproach"] = self.wait_gate_approach(
                gate,
                approach,
            )

            gate_holding_points = self.gate_convoy_destinations(gate)
            gate_convoy_plan = self.plan_gate_convoy(
                gate,
                gate_holding_points,
            )
            gate_exit = gate_convoy_plan["destinations"]
            result["gateConvoyPlan"] = gate_convoy_plan
            result["gateExitDestinations"] = gate_exit
            result["gateExitPlacement"] = (
                self.validate_gate_convoy_destinations(gate_exit)
            )
            result["gateConvoy"] = self.transit_gate_convoy(
                gate,
                gate_exit,
                gate_convoy_plan["fighters"],
            )
            result["gateTransit"] = self.wait_gate_transit(gate)
            result["gateTransit"]["stuckTeleports"] = 0
            result["screenshots"]["gateTransit"] = self.capture(
                "gate-transit"
            )
            if self.mode == "gate":
                result["end"] = {
                    "reason": "gate_transit_complete",
                    "furthestWave": 0,
                }
                result["ok"] = True
                return result

            dig_route = normalize(
                solomon[0] - gate["midpoint"][0],
                solomon[1] - gate["midpoint"][1],
            )
            result["digRouteUnit"] = dig_route
            gather_plan = self.plan_hub_gather(
                solomon,
                gate,
                dig_route,
            )
            result["hubGatherPlan"] = gather_plan
            gather = gather_plan["destinations"]
            result["hubGatherDestinations"] = gather
            selected_gather_attempt = gather_plan["attempts"][
                gather_plan["selectedAttemptIndex"]
            ]
            result["hubGatherPlacement"] = (
                selected_gather_attempt["placement"]
            )
            result["hubGatherSegments"] = (
                selected_gather_attempt["segments"]
            )
            self.command_group(
                gather,
                arrival_radius=self.config.gather_arrival_radius,
            )
            result["hubGather"] = self.wait_group(
                gather,
                arrival_radius=self.config.gather_arrival_radius,
                label="hub-gather",
                require_unacquired=True,
            )
            result["hubGatherStop"] = self.stop_group()
            result["screenshots"]["hubGather"] = self.capture(
                "hub-gather"
            )

            self.reset_damage_observations()
            trigger = self.formation(
                solomon,
                dig_route,
                self.config.trigger_spacing,
            )
            trigger = self.assign_destinations_without_crossing(trigger)
            result["solomonTriggerDestinations"] = trigger
            self.command_group(
                trigger,
                arrival_radius=self.config.gather_arrival_radius,
            )
            result["solomonDig"] = self.wait_for_real_trigger()
            result["screenshots"]["digTrigger"] = self.capture(
                "dig-trigger"
            )

            result["end"] = self.monitor_match()
            result["screenshots"]["runEnd"] = self.capture("run-end")
            result["furthestWave"] = self.furthest_wave
            result["damage"] = self.damage_summary()
            result["deaths"] = self.death_transitions
            result["respawns"] = self.respawn_transitions
            result["waveSummaries"] = {
                str(wave): summary
                for wave, summary in sorted(
                    self.wave_summaries.items()
                )
            }
            result["wavePlans"] = {
                str(wave): plan
                for wave, plan in sorted(self.wave_plans.items())
            }
            result["completedWaves"] = [
                {
                    "wave": wave,
                    "monotonicMs": monotonic_ms,
                }
                for wave, monotonic_ms in sorted(
                    self.completed_waves.items()
                )
            ]
            result["waveCompositions"] = {
                str(wave): {
                    str(row["enemyType"]): row["planned"]
                    for row in plan["composition"]
                }
                for wave, plan in sorted(self.wave_plans.items())
            }
            result["waveScreenshots"] = {
                str(wave): artifact
                for wave, artifact in sorted(
                    self.wave_screenshots.items()
                )
            }
            result["enemyDamageObservations"] = self.enemy_damage
            result["playerDamageObservations"] = self.player_damage
            result["timeline"] = self.timeline
            if self.mode == "smoke":
                if result["end"]["reason"] != "wave_1_cleared":
                    raise BotMatchFailure(
                        f"Wave-1 smoke did not clear: {result['end']}"
                    )
                self.assert_smoke_damage()
            elif self.mode == "matrix":
                if (
                    result["end"]["reason"]
                    != "four_fighter_damage_matrix_satisfied"
                ):
                    raise BotMatchFailure(
                        "Primary matrix did not reach four damaging "
                        f"fighters: {result['end']}"
                    )
                self.assert_matrix_damage()
            result["ok"] = True
            return result
        except Exception as error:
            failure = error
            result["ok"] = False
            result["error"] = str(error)
            result["furthestWave"] = self.furthest_wave
            result["damage"] = self.damage_summary()
            try:
                if self.process_started:
                    result["screenshots"]["failure"] = self.capture(
                        "failure"
                    )
            except Exception as capture_error:
                result["failureCaptureError"] = str(capture_error)
            raise
        finally:
            result["completedAt"] = utc_now()
            cleanup_error: Exception | None = None
            try:
                result["processStop"] = self.stop_game()
            except Exception as stop_error:
                cleanup_error = stop_error
                result["processStopError"] = str(stop_error)
            atomic_write_json(self.run_directory / "result.json", result)
            if cleanup_error is not None and failure is None:
                raise BotMatchFailure(
                    f"Owned process cleanup failed: {cleanup_error}"
                ) from cleanup_error
            if failure is not None and not isinstance(
                failure, BotMatchFailure
            ):
                raise BotMatchFailure(str(failure)) from failure


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a staged four-fighter all-bot match through the real "
            "Solomon Dig path."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
    )
    parser.add_argument(
        "--mode",
        choices=("gate", "smoke", "full"),
        default="full",
    )
    parser.add_argument(
        "--run-count",
        type=int,
        default=None,
        help="Override match.runCount (full mode only).",
    )
    parser.add_argument(
        "--batch-id",
        default="",
        help="Filename-safe evidence batch id; defaults to a UTC timestamp.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        config = BotMatchConfig.load(args.config)
        mode: Mode = args.mode
        run_count = (
            args.run_count
            if args.run_count is not None
            else config.run_count if mode == "full" else 1
        )
        if mode != "full" and run_count != 1:
            raise BotMatchFailure(
                "--run-count is supported only for full mode."
            )
        if not 1 <= run_count <= 20:
            raise BotMatchFailure("--run-count must be between 1 and 20.")
        batch_id = safe_batch_id(
            args.batch_id
            or datetime.now(timezone.utc).strftime(
                f"%Y%m%dT%H%M%SZ-{mode}"
            )
        )
        batch_directory = config.evidence_root / "runs" / batch_id
        batch_directory.mkdir(parents=True, exist_ok=False)
        atomic_write_json(
            batch_directory / "batch-config.json",
            {
                "schemaVersion": 1,
                "mode": mode,
                "runCount": run_count,
                "sourceConfig": str(config.source_path),
                "sourceConfigSha256": sha256_file(config.source_path),
                "startedAt": utc_now(),
                "gitHead": run_checked(
                    ["git", "rev-parse", "HEAD"],
                    timeout=15,
                    cwd=ROOT,
                ).strip(),
            },
        )

        results = []
        for run_index in range(1, run_count + 1):
            instance = instance_name(mode, run_index, batch_id)
            runner = BotMatchRun(
                config,
                mode=mode,
                run_index=run_index,
                batch_directory=batch_directory,
                instance=instance,
            )
            result = runner.run()
            results.append(result)
            print(
                json.dumps(
                    {
                        "run": run_index,
                        "mode": mode,
                        "ok": result.get("ok"),
                        "furthestWave": result.get("furthestWave", 0),
                        "end": result.get("end", {}),
                        "result": str(
                            runner.run_directory / "result.json"
                        ),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )

        summary = {
            "schemaVersion": 1,
            "ok": all(result.get("ok") is True for result in results),
            "mode": mode,
            "runCount": run_count,
            "completedAt": utc_now(),
            "runs": [
                {
                    "runIndex": result["runIndex"],
                    "furthestWave": result.get("furthestWave", 0),
                    "end": result.get("end", {}),
                    "damage": result.get("damage", {}),
                    "result": str(
                        batch_directory
                        / f"run-{result['runIndex']:02d}"
                        / "result.json"
                    ),
                }
                for result in results
            ],
        }
        atomic_write_json(batch_directory / "summary.json", summary)
        print(
            json.dumps(
                {
                    "ok": summary["ok"],
                    "summary": str(batch_directory / "summary.json"),
                },
                sort_keys=True,
            )
        )
        return 0 if summary["ok"] else 1
    except (
        BotMatchFailure,
        OSError,
        subprocess.SubprocessError,
        csp.ProbeFailure,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
