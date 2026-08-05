#!/usr/bin/env python3
"""Prove host-authoritative wave progression with only a bot alive."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from multiplayer_defense_behavior_harness import invoke_native_magic_hit_trial
from run_bot_match import DAMAGE_DRAIN_PROBE
from verify_multiplayer_enemy_retarget import _capture_targets
from verify_lua_wave_spawn_filters import _kill_one as kill_one_native_enemy
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    HOST_ID,
    HOST_NAME,
    VerifyFailure,
    game_process_ids,
    launch_pair,
    lua,
    parse_key_values,
    stop_exact_game_processes,
    wait_for_remote,
    wait_for_scene,
)
from verify_multiplayer_death_spectator_respawn import (
    SPECTATOR_STATE_PROBE,
    _apply_authoritative_client_lethal_hit,
    _apply_authoritative_host_lethal_hit,
    _establish_host_lethal_precondition,
    _establish_local_lethal_precondition,
)
from verify_multiplayer_organic_player_death import (
    _materialize_native_wave_schedule,
)
from verify_player_health_death_sync import set_local_player_vitals
from verify_remote_latency_wave5 import atomic_write_json


ROOT = Path(__file__).resolve().parents[1]
BOT_MOD_ID = "bot.brain"
AUTOMATION_MOD_ID = "sample.lua.ui_sandbox_lab"
BOT_TARGET_HEADER = "-- sdmod-exec-target: bot.brain\n"
DEFAULT_EVIDENCE_ROOT = Path("/mnt/d/codex-evidence/botwaves-20260804")
DEFAULT_GAME_DIRECTORY = DEFAULT_EVIDENCE_ROOT / "game-source"
DEFAULT_RUNTIME_ROOT = DEFAULT_EVIDENCE_ROOT / "runtime"
DEFAULT_LAUNCHER = ROOT / "dist/launcher/SolomonDarkModLauncher.exe"
DEFAULT_WAVE_FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "waves"
    / "bot_only_wave_progression_test.txt"
)
PORT_MIN = 52261
PORT_MAX = 52268
CLIENT_AUTHORITY_LETHAL_HP_MAX = 5.0


class BotOnlyWaveFailure(RuntimeError):
    """Raised when the bot-only wave contract fails to converge."""

    def __init__(
        self,
        message: str,
        evidence: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.evidence = dict(evidence or {})


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def source_sha() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def materialize_effective_wave_schedule(
    *,
    game_directory: Path,
    fixture_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    return _materialize_native_wave_schedule(
        retail_wave_path=game_directory / "data" / "wave.txt",
        fixture_path=fixture_path,
        output_path=output_path,
        spawn_delay_ticks=4096,
        wave_delay_ticks=100,
    )


def integer(values: Mapping[str, str], key: str, default: int = 0) -> int:
    raw = values.get(key, str(default))
    try:
        return int(raw, 0)
    except (TypeError, ValueError):
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            return default


def number(
    values: Mapping[str, str],
    key: str,
    default: float = math.nan,
) -> float:
    try:
        value = float(values.get(key, str(default)))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def wait_for(
    operation: Callable[[], Any],
    predicate: Callable[[Any], bool],
    *,
    label: str,
    timeout: float,
    interval: float = 0.1,
) -> tuple[Any, str]:
    deadline = time.monotonic() + timeout
    last: Any = None
    last_error = ""
    while time.monotonic() < deadline:
        try:
            last = operation()
            last_error = ""
            if predicate(last):
                return last, utc_now()
        except (OSError, ValueError, VerifyFailure, subprocess.SubprocessError) as error:
            last_error = str(error)
        time.sleep(interval)
    raise BotOnlyWaveFailure(
        f"Timed out waiting for {label}; last={last!r}; "
        f"last_error={last_error!r}"
    )


def start_stock_match(host_pipe: str) -> dict[str, str]:
    started, _ = wait_for(
        lambda: parse_key_values(
            lua(
                host_pipe,
                """
local invoked, result = pcall(sd.hub.start_match)
print("invoked=" .. tostring(invoked))
print("queued=" .. tostring(invoked and result == true))
print("detail=" .. tostring(result))
""",
            )
        ),
        lambda values: (
            values.get("invoked") == "true"
            and values.get("queued") == "true"
        ),
        label="stock hosted Start Match request",
        timeout=30.0,
    )
    return started


STATE_PROBE = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local wave = sd.waves.get_state() or {}
local combat = sd.gameplay.get_combat_state() or {}
local spawner = sd.gameplay.get_manual_enemy_spawner_state() or {}
local runtime = sd.runtime.get_multiplayer_state() or {}
local spectator = runtime.death_spectator or {}
local game_over = runtime.game_over or {}
local pause = runtime.shared_gameplay_pause or {}
local level_wait = runtime.level_up_wait_status or {}
local player = sd.player.get_state() or {}
local ui = sd.ui and sd.ui.get_snapshot and sd.ui.get_snapshot() or nil
local bots = {}
local brain = rawget(_G, "bot_brain_debug") or {}
local brain_by_id = {}
for _, row in ipairs(brain.bots or {}) do
  brain_by_id[tonumber(row.participant_id) or 0] = row
end
for _, bot in ipairs(sd.bots.get_state() or {}) do
  if bot.in_run == true then bots[#bots + 1] = bot end
end
table.sort(bots, function(left, right)
  return (tonumber(left.id) or 0) < (tonumber(right.id) or 0)
end)
local enemies = {}
for _, actor in ipairs(sd.world.list_actors() or {}) do
  if actor.tracked_enemy == true then enemies[#enemies + 1] = actor end
end
table.sort(enemies, function(left, right)
  local left_id = tonumber(left.network_actor_id) or
    tonumber(left.actor_address) or 0
  local right_id = tonumber(right.network_actor_id) or
    tonumber(right.actor_address) or 0
  return left_id < right_id
end)
emit("wave", wave.wave or 0)
emit("monotonic_ms", rawget(_G, "__botwaves_monotonic_ms") or 0)
emit("phase", wave.phase or "")
emit("alive", wave.alive or 0)
emit("killed", wave.killed or 0)
emit("remaining", wave.remaining_to_spawn or 0)
emit("combat_active", combat.active == true)
emit("combat_wave_index", combat.wave_index or 0)
emit("combat_wave_counter", combat.wave_counter or 0)
emit("combat_wait_ticks", combat.wait_ticks or 0)
emit("combat_advance_mode", combat.advance_mode or 0)
emit("combat_advance_threshold", combat.advance_threshold or 0)
emit("spawner_address", spawner.spawner_address or 0)
local spawner_address = tonumber(spawner.spawner_address) or 0
if spawner_address ~= 0 then
  emit("spawner_remaining", sd.debug.read_u32(spawner_address + 0x20) or 0)
  emit("spawner_spawn_delay", sd.debug.read_u32(spawner_address + 0x24) or 0)
  emit("spawner_spawn_delay_base", sd.debug.read_u32(spawner_address + 0x28) or 0)
  emit("spawner_wave_delay", sd.debug.read_u32(spawner_address + 0x2C) or 0)
else
  emit("spawner_remaining", 0)
  emit("spawner_spawn_delay", 0)
  emit("spawner_spawn_delay_base", 0)
  emit("spawner_wave_delay", 0)
end
emit("player_hp", player.hp or 0)
emit("player_anim_drive", player.anim_drive_state or -1)
emit("spectator_active", spectator.active == true)
emit("spectator_phase", spectator.phase or "")
emit("spectator_target", spectator.target_participant_id or 0)
emit("respawn_epoch", spectator.last_applied_respawn_epoch or 0)
emit("respawn_wave", spectator.last_applied_respawn_wave or 0)
emit("game_over_command_epoch", game_over.command_epoch or 0)
emit("game_over_accepted_epoch", game_over.accepted_epoch or 0)
emit("game_over_pending_dispatch", game_over.pending_dispatch == true)
emit("game_over_dispatch_count", game_over.dispatch_count or 0)
emit("game_over_surface", ui ~= nil and ui.surface_id == "game_over")
emit("shared_pause", pause.pause_active == true)
emit("shared_pause_deadline_ms", pause.deadline_remaining_ms or 0)
emit("level_wait", level_wait.pause_active == true)
emit("level_wait_count", #(level_wait.waiting_participant_ids or {}))
local health_fixture = rawget(_G, "__botwaves_enemy_health_fixture") or {}
emit("health_fixture_existing", health_fixture.existing or 0)
emit("health_fixture_spawned", health_fixture.spawned or 0)
emit("participant_count", #(runtime.participants or {}))
for index, participant in ipairs(runtime.participants or {}) do
  local prefix = "participant." .. tostring(index) .. "."
  emit(prefix .. "id", participant.participant_id or 0)
  emit(prefix .. "kind", participant.kind or "")
  emit(prefix .. "ready", participant.ready == true)
  emit(prefix .. "connected", participant.transport_connected == true)
  emit(prefix .. "in_run", participant.in_run == true)
  emit(prefix .. "life", participant.life_current or 0)
  emit(prefix .. "max_life", participant.life_max or 0)
  emit(prefix .. "anim_drive", participant.anim_drive_state or -1)
end
emit("bot_count", #bots)
for index, bot in ipairs(bots) do
  local prefix = "bot." .. tostring(index) .. "."
  local brain_row = brain_by_id[tonumber(bot.id) or 0] or {}
  emit(prefix .. "id", bot.id or 0)
  emit(prefix .. "name", bot.name or "")
  emit(prefix .. "actor", bot.actor_address or 0)
  emit(prefix .. "slot", bot.gameplay_slot or -1)
  emit(prefix .. "hp", bot.hp or 0)
  emit(prefix .. "max_hp", bot.max_hp or 0)
  emit(prefix .. "mp", bot.mp or 0)
  emit(prefix .. "max_mp", bot.max_mp or 0)
  emit(prefix .. "anim_drive", bot.anim_drive_state or -1)
  emit(prefix .. "materialized", bot.entity_materialized == true)
  emit(prefix .. "brain_mode", brain_row.mode or "")
  emit(prefix .. "hp_fleeing", brain_row.hp_fleeing == true)
  emit(prefix .. "mana_fleeing", brain_row.mana_fleeing == true)
  emit(prefix .. "cast_accepted", brain_row.cast_accepted or 0)
end
emit("enemy_count", #enemies)
for index, enemy in ipairs(enemies) do
  local prefix = "enemy." .. tostring(index) .. "."
  emit(prefix .. "network_id", enemy.network_actor_id or 0)
  emit(prefix .. "actor", enemy.actor_address or 0)
  emit(prefix .. "type", enemy.enemy_type or enemy.object_type_id or -1)
  emit(prefix .. "hp", enemy.hp or 0)
  emit(prefix .. "max_hp", enemy.max_hp or 0)
  emit(prefix .. "dead", enemy.dead == true)
  emit(prefix .. "target_participant", enemy.target_participant_id or 0)
  emit(prefix .. "target_slot", enemy.target_gameplay_slot or -1)
end
local wave_events = rawget(_G, "__botwaves_wave_events") or {}
emit("wave_event_count", #wave_events)
for index, event in ipairs(wave_events) do
  local prefix = "wave_event." .. tostring(index) .. "."
  emit(prefix .. "kind", event.kind or "")
  emit(prefix .. "wave", event.wave or 0)
  emit(prefix .. "monotonic_ms", event.monotonic_ms or 0)
  emit(prefix .. "planned", event.planned or 0)
end
"""


def state(pipe_name: str) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, BOT_TARGET_HEADER + STATE_PROBE))


def indexed_rows(values: Mapping[str, str], prefix: str) -> list[dict[str, str]]:
    count = integer(values, f"{prefix}_count")
    rows: list[dict[str, str]] = []
    for index in range(1, count + 1):
        stem = f"{prefix}.{index}."
        rows.append(
            {
                key[len(stem) :]: value
                for key, value in values.items()
                if key.startswith(stem)
            }
        )
    return rows


def participant(values: Mapping[str, str], participant_id: int) -> dict[str, str]:
    for row in indexed_rows(values, "participant"):
        if integer(row, "id") == participant_id:
            return row
    return {}


def local_human(values: Mapping[str, str]) -> dict[str, str]:
    for row in indexed_rows(values, "participant"):
        if row.get("kind") == "LocalHuman":
            return row
    return {}


def bot(values: Mapping[str, str]) -> dict[str, str]:
    rows = indexed_rows(values, "bot")
    return rows[0] if len(rows) == 1 else {}


def stock_game_over_observed(values: Mapping[str, str]) -> bool:
    bot_terminal = (
        integer(values, "bot_count") == 0
        or number(bot(values), "hp", 1.0) <= 0.0
    )
    return (
        bot_terminal
        and integer(values, "game_over_accepted_epoch") != 0
        and integer(values, "game_over_dispatch_count") == 1
    )


def configure_one_bot(
    runtime_root: Path,
    instance_prefix: str,
    host_pipe: str,
) -> dict[str, Any]:
    settings_path = (
        runtime_root
        / "instances"
        / f"{instance_prefix}-host".casefold()
        / "stage/.sdmod/mod-settings/bot.brain.json"
    )
    payload = {
        "schemaVersion": 1,
        "values": {
            "focus_bot_key": "NONE",
            "kite_radius": 100,
            "offense_enabled": False,
            "think_profile": "standard",
            "roster": [
                {
                    "name": "Brook",
                    "element": "water",
                    "discipline": "arcane",
                    "behavior": "skirmisher",
                }
            ],
        },
    }
    atomic_write_json(settings_path, payload)
    reloaded = parse_key_values(
        lua(
            host_pipe,
            BOT_TARGET_HEADER
            + f"""
local result = sd.__settings_reload({json.dumps(BOT_MOD_ID)})
print("ok=" .. tostring(result.ok))
print("changed=" .. table.concat(result.changed or {{}}, ","))
print("error=" .. tostring(result.error or ""))
""",
        )
    )
    if reloaded.get("ok") != "true" or reloaded.get("error"):
        raise BotOnlyWaveFailure(f"Bot settings reload failed: {reloaded}")
    settled, settled_at = wait_for(
        lambda: parse_key_values(
            lua(
                host_pipe,
                BOT_TARGET_HEADER
                + """
local roster = sd.settings.get("roster") or {}
local debug = rawget(_G, "bot_brain_debug") or {}
print("count=" .. tostring(#roster))
print("name=" .. tostring(roster[1] and roster[1].name or ""))
print("offense_enabled=" .. tostring(debug.offense_enabled == true))
""",
            )
        ),
        lambda values: integer(values, "count") == 1
        and values.get("name") == "Brook"
        and values.get("offense_enabled") == "false",
        label="one-seat bot roster",
        timeout=15.0,
    )
    return {
        "settingsPath": str(settings_path),
        "reload": reloaded,
        "settled": settled,
        "settledAt": settled_at,
    }


def set_bot_offense(
    settings_path: Path,
    host_pipe: str,
    *,
    enabled: bool,
) -> dict[str, Any]:
    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    payload["values"]["offense_enabled"] = enabled
    atomic_write_json(settings_path, payload)
    reloaded = parse_key_values(
        lua(
            host_pipe,
            BOT_TARGET_HEADER
            + f"""
local result = sd.__settings_reload({json.dumps(BOT_MOD_ID)})
print("ok=" .. tostring(result.ok))
print("changed=" .. table.concat(result.changed or {{}}, ","))
print("error=" .. tostring(result.error or ""))
""",
        )
    )
    expected = "true" if enabled else "false"
    settled, settled_at = wait_for(
        lambda: parse_key_values(
            lua(
                host_pipe,
                BOT_TARGET_HEADER
                + """
local debug = rawget(_G, "bot_brain_debug") or {}
print("offense_enabled=" .. tostring(debug.offense_enabled == true))
""",
            )
        ),
        lambda values: values.get("offense_enabled") == expected,
        label=f"bot offense enabled={enabled}",
        timeout=8.0,
    )
    return {
        "settingsPath": str(settings_path),
        "enabled": enabled,
        "reload": reloaded,
        "settled": settled,
        "settledAt": settled_at,
    }


def parse_damage(text: str, observed_at: str) -> list[dict[str, Any]]:
    if not text or text.strip() == "none":
        return []
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        parts = line.split("|")
        if parts[0] == "enemy" and len(parts) == 14:
            rows.append(
                {
                    "lane": "bot_to_enemy",
                    "sequence": int(parts[1]),
                    "monotonicMs": int(parts[2]),
                    "sourceParticipantId": int(parts[3]),
                    "sourceGameplaySlot": int(parts[6]),
                    "targetActor": int(parts[7]),
                    "targetNetworkActorId": int(parts[8]),
                    "targetNativeTypeId": int(parts[9]),
                    "hpBefore": float(parts[10]),
                    "hpAfter": float(parts[11]),
                    "maxHp": float(parts[12]),
                    "damage": float(parts[13]),
                    "observedUtc": observed_at,
                }
            )
        elif parts[0] == "player" and len(parts) == 12:
            rows.append(
                {
                    "lane": "enemy_to_participant",
                    "sequence": int(parts[1]),
                    "monotonicMs": int(parts[2]),
                    "targetParticipantId": int(parts[3]),
                    "targetGameplaySlot": int(parts[4]),
                    "targetActor": int(parts[5]),
                    "sourceActor": int(parts[6]),
                    "sourceNativeTypeId": int(parts[7]),
                    "hpBefore": float(parts[8]),
                    "hpAfter": float(parts[9]),
                    "maxHp": float(parts[10]),
                    "damage": float(parts[11]),
                    "observedUtc": observed_at,
                }
            )
        else:
            raise BotOnlyWaveFailure(f"Malformed damage row: {line!r}")
    return rows


def install_wave_event_observer(host_pipe: str) -> dict[str, str]:
    return parse_key_values(
        lua(
            host_pipe,
            BOT_TARGET_HEADER
            + r"""
local events = {}
rawset(_G, "__botwaves_wave_events", events)
local monotonic_ms = 0
rawset(_G, "__botwaves_monotonic_ms", monotonic_ms)
sd.events.on("runtime.tick", function(event)
  monotonic_ms = tonumber(event and event.monotonic_milliseconds) or
    monotonic_ms
  rawset(_G, "__botwaves_monotonic_ms", monotonic_ms)
end)
local function record(kind, event)
  local active = rawget(_G, "__botwaves_wave_events")
  if active ~= events then return end
  active[#active + 1] = {
    kind = kind,
    wave = tonumber(event and event.wave) or 0,
    monotonic_ms = monotonic_ms,
    planned = tonumber(event and event.planned) or 0,
  }
end
sd.events.on("wave.started", function(event) record("started", event) end)
sd.events.on("wave.completed", function(event) record("completed", event) end)
print("armed=true")
""",
        )
    )


def install_proof_wave_delay_filter(host_pipe: str) -> dict[str, str]:
    return parse_key_values(
        lua(
            host_pipe,
            BOT_TARGET_HEADER
            + r"""
if rawget(_G, "__botwaves_wave_delay_filter") ~= nil then
  error("botwaves wave delay filter is already installed")
end
local fixture = {actions = {}}
_G.__botwaves_wave_delay_filter = fixture
fixture.subscription = sd.events.filter("wave.spawning", function(event)
  local index = #fixture.actions + 1
  local record = {
    index = index,
    count = tonumber(event.count) or 0,
    applied_count = 5,
    original_wave_delay = tonumber(event.wave_delay) or 0,
    applied_wave_delay = 90000,
  }
  fixture.actions[index] = record
  return {
    count = record.applied_count,
    wave_delay = record.applied_wave_delay,
    randomize_spawn_delay = false,
  }
end)
print("installed=" .. tostring(fixture.subscription ~= nil))
print("capability=" .. tostring(
  sd.runtime.has_capability("events.filters.wave_spawn")))
print("proof_spawn_count=" .. tostring(5))
print("proof_wave_delay=" .. tostring(90000))
""",
        )
    )


def install_proof_enemy_health_fixture(host_pipe: str) -> dict[str, str]:
    return parse_key_values(
        lua(
            host_pipe,
            BOT_TARGET_HEADER
            + r"""
if rawget(_G, "__botwaves_enemy_health_fixture") ~= nil then
  error("botwaves enemy health fixture is already installed")
end
local wave = sd.waves.get_state() or {}
local fixture = {
  existing = 0,
  spawned = 0,
  proof_wave = tonumber(wave.wave) or 0,
  armed = false,
  predeath_hp = 10000.0,
  combat_hp = 0.1,
}
_G.__botwaves_enemy_health_fixture = fixture
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  if actor.tracked_enemy and not actor.dead and
      (tonumber(actor.hp) or 0) > 0 then
    local address = tonumber(actor.actor_address) or 0
    if address ~= 0 and sd.gameplay.set_run_enemy_health(
        address, fixture.predeath_hp, fixture.predeath_hp) then
      fixture.existing = fixture.existing + 1
    end
  end
end
fixture.subscription = sd.events.filter("enemy.spawning", function()
  fixture.spawned = fixture.spawned + 1
  local hp = fixture.armed and fixture.combat_hp or fixture.predeath_hp
  return {hp = hp}
end)
print("installed=" .. tostring(fixture.subscription ~= nil))
print("proof_wave=" .. tostring(fixture.proof_wave))
print("predeath_hp=" .. tostring(fixture.predeath_hp))
print("combat_hp=" .. tostring(fixture.combat_hp))
print("existing=" .. tostring(fixture.existing))
""",
        )
    )


def lower_live_proof_enemy_health(host_pipe: str) -> dict[str, str]:
    return parse_key_values(
        lua(
            host_pipe,
            BOT_TARGET_HEADER
            + r"""
local fixture = assert(
  rawget(_G, "__botwaves_enemy_health_fixture"),
  "botwaves enemy health fixture is not installed")
fixture.armed = true
local lowered = 0
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  if actor.tracked_enemy and not actor.dead and
      (tonumber(actor.hp) or 0) > fixture.combat_hp then
    local address = tonumber(actor.actor_address) or 0
    if address ~= 0 and sd.gameplay.set_run_enemy_health(
        address, fixture.combat_hp, fixture.combat_hp) then
      lowered = lowered + 1
    end
  end
end
fixture.lowered = (fixture.lowered or 0) + lowered
print("armed=" .. tostring(fixture.armed == true))
print("hp=" .. tostring(fixture.combat_hp))
print("lowered=" .. tostring(lowered))
print("lowered_total=" .. tostring(fixture.lowered))
""",
        )
    )


def arrange_native_pressure_contact(
    host_pipe: str,
    bot_id: int,
) -> dict[str, str]:
    return parse_key_values(
        lua(
            host_pipe,
            BOT_TARGET_HEADER
            + f"""
local bot_actor = 0
for _, current in ipairs(sd.bots.get_state() or {{}}) do
  if tonumber(current.id) == {bot_id} then
    bot_actor = tonumber(current.actor_address) or 0
    break
  end
end
local enemy_actors = {{}}
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {{}}) do
  if actor.tracked_enemy and not actor.dead and
      (tonumber(actor.hp) or 0) > 0 then
    local address = tonumber(actor.actor_address) or 0
    if address ~= 0 then enemy_actors[#enemy_actors + 1] = address end
  end
end
local ox = sd.debug.layout_offset("actor_position_x")
local oy = sd.debug.layout_offset("actor_position_y")
local bot_x = bot_actor ~= 0 and sd.debug.read_float(bot_actor + ox) or nil
local bot_y = bot_actor ~= 0 and sd.debug.read_float(bot_actor + oy) or nil
local moved = 0
local rebound_count = 0
for index, enemy_actor in ipairs(enemy_actors) do
  local x = bot_x ~= nil and bot_x + 20.0 + ((index - 1) * 8.0) or nil
  local y = bot_y ~= nil and bot_y + (((index - 1) % 2) * 8.0) or nil
  local write_x = x ~= nil and
    sd.debug.write_float(enemy_actor + ox, x) or false
  local write_y = y ~= nil and
    sd.debug.write_float(enemy_actor + oy, y) or false
  if write_x and write_y then
    moved = moved + 1
    if sd.world.rebind_actor and sd.world.rebind_actor(enemy_actor) then
      rebound_count = rebound_count + 1
    end
  end
end
print("bot_actor=" .. tostring(bot_actor))
print("enemy_actor=" .. tostring(enemy_actors[1] or 0))
print("enemy_count=" .. tostring(#enemy_actors))
print("bot_x=" .. tostring(bot_x or 0))
print("bot_y=" .. tostring(bot_y or 0))
print("moved=" .. tostring(moved))
print("rebound_count=" .. tostring(rebound_count))
print("rebound=" .. tostring(
  #enemy_actors > 0 and rebound_count == #enemy_actors))
""",
        )
    )


def isolate_human_death_edge(host_pipe: str) -> dict[str, str]:
    return parse_key_values(
        lua(
            host_pipe,
            BOT_TARGET_HEADER
            + r"""
local player = sd.player.get_state() or {}
local player_actor = tonumber(player.actor_address) or 0
local ox = sd.debug.layout_offset("actor_position_x")
local oy = sd.debug.layout_offset("actor_position_y")
local px = player_actor ~= 0 and sd.debug.read_float(player_actor + ox) or 0
local py = player_actor ~= 0 and sd.debug.read_float(player_actor + oy) or 0
local attempted = 0
local moved = 0
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  if actor.tracked_enemy and not actor.dead and
      (tonumber(actor.hp) or 0) > 0 then
    local address = tonumber(actor.actor_address) or 0
    if address ~= 0 then
      attempted = attempted + 1
      local write_x = sd.debug.write_float(
        address + ox, px + 3000.0 + (attempted * 8.0))
      local write_y = sd.debug.write_float(address + oy, py + 3000.0)
      if write_x and write_y and sd.world.rebind_actor and
          sd.world.rebind_actor(address) then
        moved = moved + 1
      end
    end
  end
end
print("attempted=" .. tostring(attempted))
print("moved=" .. tostring(moved))
print("player_x=" .. tostring(px))
print("player_y=" .. tostring(py))
""",
        )
    )


def set_probe_bot_vitals(
    host_pipe: str,
    bot_id: int,
    hp: float,
    mp: float,
) -> dict[str, Any]:
    written = parse_key_values(
        lua(
            host_pipe,
            BOT_TARGET_HEADER
            + f"""
local bot = sd.bots.get_participant_state({bot_id})
local progression = bot and
  tonumber(bot.progression_runtime_state_address) or 0
local hp_offset = sd.debug.layout_offset("progression_hp")
local max_hp_offset = sd.debug.layout_offset("progression_max_hp")
local mp_offset = sd.debug.layout_offset("progression_mp")
local max_mp_offset = sd.debug.layout_offset("progression_max_mp")
print("progression=" .. tostring(progression))
print("hp_ok=" .. tostring(
  progression ~= 0 and hp_offset ~= nil and
  sd.debug.write_float(progression + hp_offset, {hp:.9f})))
print("max_hp_ok=" .. tostring(
  progression ~= 0 and max_hp_offset ~= nil and
  sd.debug.write_float(progression + max_hp_offset, {hp:.9f})))
print("mp_ok=" .. tostring(
  progression ~= 0 and mp_offset ~= nil and
  sd.debug.write_float(progression + mp_offset, {mp:.9f})))
print("max_mp_ok=" .. tostring(
  progression ~= 0 and max_mp_offset ~= nil and
  sd.debug.write_float(progression + max_mp_offset, {mp:.9f})))
""",
        )
    )
    if any(
        written.get(key) != "true"
        for key in ("hp_ok", "max_hp_ok", "mp_ok", "max_mp_ok")
    ):
        raise BotOnlyWaveFailure(f"Could not set probe bot vitals: {written}")
    settled, settled_at = wait_for(
        lambda: state(host_pipe),
        lambda values: (
            abs(number(bot(values), "hp", 0.0) - hp) <= 0.05
            and abs(number(bot(values), "max_hp", 0.0) - hp) <= 0.05
            and abs(number(bot(values), "mp", 0.0) - mp) <= 0.05
            and abs(number(bot(values), "max_mp", 0.0) - mp) <= 0.05
        ),
        label=f"probe bot {hp:g} HP / {mp:g} MP vitals",
        timeout=8.0,
    )
    return {
        "requestedHp": hp,
        "requestedMp": mp,
        "write": written,
        "settledState": settled,
        "settledAt": settled_at,
    }


def client_lethal_authority_precondition(
    values: Mapping[str, str],
) -> bool:
    client = participant(values, CLIENT_ID)
    return (
        0.0 < number(client, "life", math.inf)
        <= CLIENT_AUTHORITY_LETHAL_HP_MAX
        and integer(client, "anim_drive", 1) == 0
    )


def participant_is_terminally_dead(values: Mapping[str, str]) -> bool:
    return (
        number(values, "life", 1.0) <= 0.0
        and integer(values, "anim_drive", 0) != 0
    )


def kill_humans(
    host_pipe: str,
    client_pipe: str,
    *,
    label: str,
    skip_already_dead: bool = False,
) -> dict[str, Any]:
    killed: dict[str, Any] = {
        "label": label,
        "skipAlreadyDead": skip_already_dead,
        "startedAt": utc_now(),
    }
    killed["hostilesIsolated"] = isolate_human_death_edge(host_pipe)
    before = state(host_pipe)
    client_before = participant(before, CLIENT_ID)
    if skip_already_dead and participant_is_terminally_dead(client_before):
        killed["clientPrecondition"] = {
            "alreadyDead": True,
            "participant": client_before,
        }
        killed["clientAuthorityPrecondition"] = {
            "alreadyDead": True,
            "state": before,
            "utc": utc_now(),
        }
        killed["clientHit"] = {"skipped": True, "reason": "already dead"}
    else:
        killed["clientPrecondition"] = _establish_local_lethal_precondition(
            client_pipe,
            "client",
        )
        client_authority, client_authority_at = wait_for(
            lambda: state(host_pipe),
            client_lethal_authority_precondition,
            label=f"client lethal precondition at host authority ({label})",
            timeout=8.0,
        )
        killed["clientAuthorityPrecondition"] = {
            "state": client_authority,
            "utc": client_authority_at,
        }
        killed["clientHit"] = _apply_authoritative_client_lethal_hit(host_pipe)
        wait_for(
            lambda: state(host_pipe),
            lambda values: (
                number(participant(values, CLIENT_ID), "life", 1.0) <= 0.0
            ),
            label=f"client terminal death ({label})",
            timeout=8.0,
        )

    before_host = state(host_pipe)
    host_before = local_human(before_host)
    if skip_already_dead and participant_is_terminally_dead(host_before):
        killed["hostPrecondition"] = {
            "alreadyDead": True,
            "participant": host_before,
        }
        killed["hostHit"] = {"skipped": True, "reason": "already dead"}
    else:
        killed["hostPrecondition"] = _establish_host_lethal_precondition(host_pipe)
        killed["hostHit"] = _apply_authoritative_host_lethal_hit(host_pipe)
    terminal, killed_at = wait_for(
        lambda: state(host_pipe),
        lambda values: (
            number(local_human(values), "life", 1.0) <= 0.0
            and number(participant(values, CLIENT_ID), "life", 1.0) <= 0.0
            and integer(values, "game_over_accepted_epoch") == 0
        ),
        label=f"both humans dead while bot keeps Game Over open ({label})",
        timeout=8.0,
    )
    killed["terminalState"] = terminal
    killed["completedAt"] = killed_at
    return killed


def clear_warmup_wave(
    host_pipe: str,
    starting_wave: int,
    *,
    timeout: float,
) -> dict[str, Any]:
    receipts: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    probe = r"""
local wave = sd.waves.get_state() or {}
print("wave=" .. tostring(wave.wave or 0))
print("phase=" .. tostring(wave.phase or ""))
print("alive=" .. tostring(wave.alive or 0))
print("killed=" .. tostring(wave.killed or 0))
print("remaining=" .. tostring(wave.remaining_to_spawn or 0))
"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        observed_at = utc_now()
        observed = parse_key_values(lua(host_pipe, BOT_TARGET_HEADER + probe))
        timeline.append({"utc": observed_at, **observed})
        if integer(observed, "wave") > starting_wave:
            return {
                "startingWave": starting_wave,
                "nativeDeaths": receipts,
                "timeline": timeline,
                "completedAt": observed_at,
            }
        if integer(observed, "alive") > 0:
            receipts.append(
                {
                    "utc": utc_now(),
                    **kill_one_native_enemy(host_pipe),
                }
            )
        else:
            time.sleep(0.05)
    raise BotOnlyWaveFailure(
        f"Warmup wave {starting_wave} did not reach its native boundary: "
        f"{timeline[-1] if timeline else None}",
        {
            "startingWave": starting_wave,
            "nativeDeaths": receipts,
            "timeline": timeline,
        },
    )


def resolve_level_up_offers(host_pipe: str, client_pipe: str) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    code = r"""
local state = sd.runtime.get_multiplayer_state() or {}
local offer = state.active_level_up_offer or {}
if offer.valid == true and offer.selection_submitted ~= true then
  print("offer_id=" .. tostring(offer.offer_id or 0))
  print("option_count=" .. tostring(#(offer.options or {})))
else
  print("offer_id=0")
  print("option_count=0")
end
"""
    for label, pipe_name in (("client", client_pipe), ("host", host_pipe)):
        pending = parse_key_values(lua(pipe_name, code))
        offer_id = integer(pending, "offer_id")
        if offer_id == 0:
            continue
        submitted = parse_key_values(
            lua(
                pipe_name,
                "print('ok=' .. tostring(sd.gameplay.submit_level_up_choice("
                f"{offer_id}, 0)))",
            )
        )
        resolved.append(
            {
                "participant": label,
                "offerId": offer_id,
                "optionCount": integer(pending, "option_count"),
                "submitted": submitted,
                "utc": utc_now(),
            }
        )
    return resolved


def observe_cycles(
    host_pipe: str,
    client_pipe: str,
    bot_id: int,
    *,
    settings_path: Path,
    starting_wave: int,
    cycles: int,
    timeout: float,
) -> dict[str, Any]:
    target_wave = starting_wave + cycles
    timeline: list[dict[str, Any]] = []
    spawns: dict[str, dict[str, Any]] = {}
    target_samples: list[dict[str, Any]] = []
    damage: list[dict[str, Any]] = []
    wave_transitions: list[dict[str, Any]] = []
    contact_samples: list[dict[str, Any]] = []
    pressure_setups: list[dict[str, Any]] = []
    pressure_releases: list[dict[str, Any]] = []
    level_ups: list[dict[str, Any]] = []
    rekills: list[dict[str, Any]] = []
    actor_spawn_waves: dict[int, int] = {}
    seen_wave = starting_wave
    pending_rekill_wave = 0
    pending_rekill_since = 0.0
    pending_pressure_wave = 0
    last_signature: tuple[Any, ...] | None = None
    last_level_up_probe = 0.0
    last_contact_at = 0.0
    terminal_hold_prepared = False
    previous_director_state: dict[str, Any] | None = None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        observed_at = utc_now()
        observed = state(host_pipe)
        wave = integer(observed, "wave")
        signature = (
            wave,
            observed.get("phase"),
            integer(observed, "alive"),
            integer(observed, "killed"),
            integer(observed, "remaining"),
            integer(observed, "game_over_accepted_epoch"),
            observed.get("shared_pause"),
            observed.get("level_wait"),
        )
        if signature != last_signature:
            timeline.append(
                {
                    "utc": observed_at,
                    "wave": wave,
                    "phase": observed.get("phase", ""),
                    "alive": integer(observed, "alive"),
                    "killed": integer(observed, "killed"),
                    "remainingToSpawn": integer(observed, "remaining"),
                    "sharedPause": observed.get("shared_pause") == "true",
                    "levelWait": observed.get("level_wait") == "true",
                    "gameOverAcceptedEpoch": integer(
                        observed,
                        "game_over_accepted_epoch",
                    ),
                }
            )
            last_signature = signature

        for enemy in indexed_rows(observed, "enemy"):
            network_id = integer(enemy, "network_id")
            actor = integer(enemy, "actor")
            key = f"network:{network_id}" if network_id else f"actor:{actor}"
            if key not in spawns and actor != 0:
                spawns[key] = {
                    "key": key,
                    "networkActorId": network_id,
                    "actor": actor,
                    "nativeTypeId": integer(enemy, "type"),
                    "firstSeenUtc": observed_at,
                    "firstSeenWave": wave,
                    "hp": number(enemy, "hp", 0.0),
                }
                actor_spawn_waves[actor] = wave
            if (
                integer(enemy, "target_participant") == bot_id
                and number(enemy, "hp", 0.0) > 0.0
                and enemy.get("dead") != "true"
            ):
                target_samples.append(
                    {
                        "utc": observed_at,
                        "wave": wave,
                        "spawnWave": actor_spawn_waves.get(actor, wave),
                        "networkActorId": network_id,
                        "actor": actor,
                        "targetParticipantId": bot_id,
                        "targetGameplaySlot": integer(enemy, "target_slot", -1),
                    }
                )

        precise_targets = _capture_targets(host_pipe, HOST_ID)
        for network_id, record in precise_targets.items():
            spawn_key = f"network:{network_id}"
            if spawn_key not in spawns:
                spawns[spawn_key] = {
                    "key": spawn_key,
                    "networkActorId": network_id,
                    "actor": record["actor_address"],
                    "nativeTypeId": record["native_type_id"],
                    "firstSeenUtc": observed_at,
                    "firstSeenWave": wave,
                }
                actor_spawn_waves[record["actor_address"]] = wave
            if (
                record["target_participant_id"] == bot_id
                and record["authority_target_participant_id"] == bot_id
                and record["authority_target_authoritative"] == 1
            ):
                target_samples.append(
                    {
                        "utc": observed_at,
                        "wave": wave,
                        "spawnWave": actor_spawn_waves.get(
                            record["actor_address"],
                            wave,
                        ),
                        **record,
                    }
                )

        damage_rows = parse_damage(
            lua(host_pipe, BOT_TARGET_HEADER + DAMAGE_DRAIN_PROBE),
            observed_at,
        )
        for damage_row in damage_rows:
            damage_row["observedWave"] = wave
            actor_key = (
                "sourceActor"
                if damage_row["lane"] == "enemy_to_participant"
                else "targetActor"
            )
            damage_row["combatWave"] = actor_spawn_waves.get(
                int(damage_row.get(actor_key) or 0),
                wave,
            )
        damage.extend(damage_rows)
        now = time.monotonic()
        if (
            starting_wave <= wave < target_wave
            and integer(observed, "enemy_count") > 0
            and now - last_contact_at >= 2.0
        ):
            contact_samples.append(
                {
                    "wave": wave,
                    "utc": utc_now(),
                    **arrange_native_pressure_contact(host_pipe, bot_id),
                }
            )
            last_contact_at = time.monotonic()
        if pending_pressure_wave != 0 and any(
            row["lane"] == "enemy_to_participant"
            and row["targetParticipantId"] == bot_id
            and row["combatWave"] == pending_pressure_wave
            and row["damage"] > 0.0
            for row in damage_rows
        ):
            pressure_releases.append(
                {
                    "wave": pending_pressure_wave,
                    "utc": utc_now(),
                    "offense": set_bot_offense(
                        settings_path,
                        host_pipe,
                        enabled=True,
                    ),
                    "hold": parse_key_values(
                        lua(
                            host_pipe,
                            BOT_TARGET_HEADER
                            + """
__botwaves_pressure_hold = false
print("held=" .. tostring(__botwaves_pressure_hold == true))
""",
                        )
                    ),
                }
            )
            pending_pressure_wave = 0
        if now - last_level_up_probe >= 1.0:
            last_level_up_probe = now
            level_ups.extend(resolve_level_up_offers(host_pipe, client_pipe))

        if wave > seen_wave:
            wave_transitions.append(
                {
                    "utc": observed_at,
                    "fromWave": seen_wave,
                    "toWave": wave,
                    "previousState": previous_director_state,
                    "currentState": {
                        "phase": observed.get("phase", ""),
                        "alive": integer(observed, "alive"),
                        "killed": integer(observed, "killed"),
                        "remainingToSpawn": integer(observed, "remaining"),
                    },
                }
            )
            seen_wave = wave
            if wave <= target_wave:
                pending_rekill_wave = wave
                pending_rekill_since = now

        if pending_rekill_wave != 0 and now - pending_rekill_since >= 1.0:
            host_row = local_human(observed)
            client_row = participant(observed, CLIENT_ID)
            if (
                number(host_row, "life", 0.0) > 0.0
                and integer(host_row, "anim_drive", 1) == 0
                and number(client_row, "life", 0.0) > 0.0
                and integer(client_row, "anim_drive", 1) == 0
            ):
                boundary_wave = pending_rekill_wave
                rekill = kill_humans(
                    host_pipe,
                    client_pipe,
                    label=f"wave-{boundary_wave}-boundary-respawn",
                )
                rekills.append(rekill)
                if boundary_wave < target_wave:
                    pressure_setups.append(
                        {
                            "wave": boundary_wave,
                            "utc": utc_now(),
                            "offense": set_bot_offense(
                                settings_path,
                                host_pipe,
                                enabled=False,
                            ),
                            "hold": parse_key_values(
                                lua(
                                    host_pipe,
                                    BOT_TARGET_HEADER
                                    + """
__botwaves_pressure_hold = true
for _, current in ipairs(sd.bots.get_state() or {}) do
  if current.in_run == true then sd.bots.stop(current.id) end
end
print("held=" .. tostring(__botwaves_pressure_hold == true))
""",
                                )
                            ),
                            "contact": arrange_native_pressure_contact(
                                host_pipe,
                                bot_id,
                            ),
                        }
                    )
                    pending_pressure_wave = boundary_wave
                pending_rekill_wave = 0
                pending_rekill_since = 0.0

        if wave >= target_wave and pending_rekill_wave == 0:
            current = state(host_pipe)
            completed_event_waves = {
                integer(row, "wave")
                for row in indexed_rows(current, "wave_event")
                if row.get("kind") == "completed"
            }
            required_completed_waves = set(range(starting_wave, target_wave))
            if (
                number(local_human(current), "life", 1.0) <= 0.0
                and number(participant(current, CLIENT_ID), "life", 1.0) <= 0.0
                and pending_pressure_wave == 0
                and required_completed_waves <= completed_event_waves
            ):
                if terminal_hold_prepared:
                    break
                pressure_setups.append(
                    {
                        "wave": wave,
                        "purpose": "terminal-hostile-preservation",
                        "utc": utc_now(),
                        "offense": set_bot_offense(
                            settings_path,
                            host_pipe,
                            enabled=False,
                        ),
                        "hold": parse_key_values(
                            lua(
                                host_pipe,
                                BOT_TARGET_HEADER
                                + """
__botwaves_pressure_hold = true
for _, current in ipairs(sd.bots.get_state() or {}) do
  if current.in_run == true then sd.bots.stop(current.id) end
end
print("held=" .. tostring(__botwaves_pressure_hold == true))
""",
                            )
                        ),
                    }
                )
                terminal_hold_prepared = True
        previous_director_state = {
            "wave": wave,
            "phase": observed.get("phase", ""),
            "alive": integer(observed, "alive"),
            "killed": integer(observed, "killed"),
            "remainingToSpawn": integer(observed, "remaining"),
        }
        time.sleep(0.25)
    else:
        final_state = state(host_pipe)
        final_events = indexed_rows(final_state, "wave_event")
        completed_event_waves = {
            integer(row, "wave")
            for row in final_events
            if row.get("kind") == "completed"
        }
        partial = {
            "startingWave": starting_wave,
            "targetWave": target_wave,
            "completedCycles": sum(
                wave in completed_event_waves
                for wave in range(starting_wave, target_wave)
            ),
            "timeline": timeline,
            "spawns": list(spawns.values()),
            "targetSamples": target_samples,
            "damage": damage,
            "waveTransitions": wave_transitions,
            "contactSamples": contact_samples,
            "pressureSetups": pressure_setups,
            "pressureReleases": pressure_releases,
            "levelUpChoices": level_ups,
            "boundaryRekills": rekills,
            "waveEvents": final_events,
            "finalState": final_state,
            "failedAt": utc_now(),
        }
        raise BotOnlyWaveFailure(
            f"Wave progression stalled before {cycles} completed cycles; "
            f"last={timeline[-1] if timeline else None}",
            partial,
        )

    final_state = state(host_pipe)
    final_events = indexed_rows(final_state, "wave_event")
    completed_event_waves = {
        integer(row, "wave")
        for row in final_events
        if row.get("kind") == "completed"
    }
    return {
        "startingWave": starting_wave,
        "targetWave": target_wave,
        "completedCycles": sum(
            wave in completed_event_waves
            for wave in range(starting_wave, target_wave)
        ),
        "timeline": timeline,
        "spawns": list(spawns.values()),
        "targetSamples": target_samples,
        "damage": damage,
        "waveTransitions": wave_transitions,
        "contactSamples": contact_samples,
        "pressureSetups": pressure_setups,
        "pressureReleases": pressure_releases,
        "levelUpChoices": level_ups,
        "boundaryRekills": rekills,
        "waveEvents": final_events,
        "finalState": final_state,
        "completedAt": utc_now(),
    }


def assert_cycle_contract(observation: Mapping[str, Any], bot_id: int) -> None:
    starting_wave = int(observation["startingWave"])
    target_wave = int(observation["targetWave"])
    completed_waves = range(starting_wave, target_wave)
    spawns = observation["spawns"]
    targets = observation["targetSamples"]
    damage = observation["damage"]
    transitions = observation["waveTransitions"]
    events = observation["waveEvents"]
    missing: list[str] = []
    for wave in completed_waves:
        if not any(row["firstSeenWave"] == wave for row in spawns):
            missing.append(f"wave {wave} spawn")
        if not any(row["spawnWave"] == wave for row in targets):
            missing.append(f"wave {wave} hostile target")
        if not any(
            row.get("kind") == "started" and integer(row, "wave") == wave
            for row in events
        ):
            missing.append(f"wave {wave} started event")
        if not any(
            row["fromWave"] == wave and row["toWave"] > wave
            for row in transitions
        ):
            missing.append(f"wave {wave} director-counter advancement")
        if not any(
            row.get("kind") == "completed" and integer(row, "wave") == wave
            for row in events
        ):
            missing.append(f"wave {wave} completed event")
        if not any(
            row["lane"] == "bot_to_enemy"
            and row["sourceParticipantId"] == bot_id
            and row["combatWave"] == wave
            and row["damage"] > 0.0
            for row in damage
        ):
            missing.append(f"wave {wave} bot damage edge")
        if not any(
            row["lane"] == "enemy_to_participant"
            and row["targetParticipantId"] == bot_id
            and row["combatWave"] == wave
            and row["damage"] > 0.0
            for row in damage
        ):
            missing.append(f"wave {wave} enemy damage edge")
    if missing:
        raise BotOnlyWaveFailure(
            "Bot-only cycle contract missing: " + ", ".join(sorted(set(missing)))
        )


def await_stock_game_over(
    host_pipe: str,
    client_pipe: str,
    bot_id: int,
    *,
    settings_path: Path,
    timeout: float,
) -> dict[str, Any]:
    before = state(host_pipe)
    current_bot = bot(before)
    hp = number(current_bot, "hp", 0.0)
    if hp <= 0.0:
        raise BotOnlyWaveFailure(f"Bot was already dead before terminal proof: {current_bot}")
    terminal_human_deaths = kill_humans(
        host_pipe,
        client_pipe,
        label="terminal-client-then-host",
        skip_already_dead=True,
    )
    offense_disabled = set_bot_offense(
        settings_path,
        host_pipe,
        enabled=False,
    )
    held = parse_key_values(
        lua(
            host_pipe,
            BOT_TARGET_HEADER
            + """
__botwaves_pressure_hold = true
for _, current in ipairs(sd.bots.get_state() or {}) do
  if current.in_run == true then sd.bots.stop(current.id) end
end
print("held=" .. tostring(__botwaves_pressure_hold == true))
""",
        )
    )
    hostile_ready, hostile_ready_at = wait_for(
        lambda: state(host_pipe),
        lambda values: any(
            number(enemy, "hp", 0.0) > 0.0
            and enemy.get("dead") != "true"
            for enemy in indexed_rows(values, "enemy")
        ),
        label="live hostile for the terminal bot",
        timeout=min(timeout, 30.0),
    )
    restored_vitals = set_probe_bot_vitals(host_pipe, bot_id, 50.0, 100.0)
    # Keep the final edge organic: a stock native hit lowers the bot, then a
    # hostile already targeting it supplies the terminal damage.
    setup_damage = max(0.1, hp * 0.5)
    setup = invoke_native_magic_hit_trial(
        host_pipe,
        projectile_damage=0.0,
        magic_damage=setup_damage,
        attempts=1,
        label="bot terminal setup",
        timeout=8.0,
        target_participant_id=bot_id,
    )
    if float(setup["hp_after"]) <= 0.0:
        raise BotOnlyWaveFailure(
            f"Terminal setup hit killed the bot instead of an enemy: {setup}"
        )
    pressure_contact = arrange_native_pressure_contact(host_pipe, bot_id)
    pressure_contacts = [
        {
            "utc": utc_now(),
            **pressure_contact,
        }
    ]
    last_pressure_contact_at = time.monotonic()
    damage: list[dict[str, Any]] = []
    terminal: dict[str, str] = {}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        observed_at = utc_now()
        terminal = state(host_pipe)
        if time.monotonic() - last_pressure_contact_at >= 1.0:
            pressure_contacts.append(
                {
                    "utc": utc_now(),
                    **arrange_native_pressure_contact(host_pipe, bot_id),
                }
            )
            last_pressure_contact_at = time.monotonic()
        damage.extend(
            parse_damage(
                lua(host_pipe, BOT_TARGET_HEADER + DAMAGE_DRAIN_PROBE),
                observed_at,
            )
        )
        if stock_game_over_observed(terminal):
            break
        time.sleep(0.1)
    else:
        raise BotOnlyWaveFailure(
            f"Timed out waiting for stock Game Over after bot death: {terminal}"
        )
    terminal_at = utc_now()
    lethal_edges = [
        row
        for row in damage
        if row["lane"] == "enemy_to_participant"
        and row["targetParticipantId"] == bot_id
        and row["hpAfter"] <= 0.0
        and row["damage"] > 0.0
    ]
    if not lethal_edges:
        raise BotOnlyWaveFailure(
            "Game Over fired without a captured hostile terminal edge: "
            f"damage={damage}"
        )
    client_terminal, client_terminal_at = wait_for(
        lambda: state(client_pipe),
        lambda values: (
            integer(values, "game_over_accepted_epoch") != 0
            and integer(values, "game_over_dispatch_count") == 1
        ),
        label="client stock Game Over dispatch",
        timeout=8.0,
    )
    return {
        "humanDeaths": terminal_human_deaths,
        "restoredBotVitals": restored_vitals,
        "botOffenseDisabled": offense_disabled,
        "botBrainHeld": held,
        "hostileReadyState": hostile_ready,
        "hostileReadyAt": hostile_ready_at,
        "setupNativeHit": setup,
        "nativePressureContact": pressure_contact,
        "nativePressureContacts": pressure_contacts,
        "damage": damage,
        "lethalEnemyEdges": lethal_edges,
        "terminalState": terminal,
        "terminalAt": terminal_at,
        "clientTerminalState": client_terminal,
        "clientTerminalAt": client_terminal_at,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    if not (
        PORT_MIN <= args.host_port <= PORT_MAX
        and PORT_MIN <= args.client_port <= PORT_MAX
        and args.host_port != args.client_port
    ):
        raise BotOnlyWaveFailure(
            f"Ports must be distinct and inside {PORT_MIN}-{PORT_MAX}"
        )
    output_path = args.output.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "schemaVersion": 1,
        "status": "running",
        "startedAt": utc_now(),
        "sourceSha": source_sha(),
        "instancePrefix": args.instance_prefix,
        "ports": {"host": args.host_port, "client": args.client_port},
        "audioDisabled": True,
        "waveFixture": str(args.wave_fixture.resolve()),
    }
    launch: dict[str, object] | None = None
    try:
        effective_wave_path = (
            output_path.parent / f"{args.instance_prefix}-effective-wave.txt"
        )
        result["waveSchedule"] = materialize_effective_wave_schedule(
            game_directory=args.game_directory.resolve(),
            fixture_path=args.wave_fixture.resolve(),
            output_path=effective_wave_path,
        )
        launch = launch_pair(
            host_preset="map_create_fire_mind_hub",
            client_preset="map_create_fire_mind_hub",
            temporary_host_profile=True,
            fresh_install=False,
            tile_windows=True,
            allow_focus_steal=False,
            kill_existing=False,
            instance_prefix=args.instance_prefix,
            host_port=args.host_port,
            client_port=args.client_port,
            third_port=args.client_port + 1,
            game_directory=args.game_directory.resolve(),
            launcher_path=args.launcher.resolve(),
            runtime_root=args.runtime_root.resolve(),
            exact_mod_ids=(AUTOMATION_MOD_ID, BOT_MOD_ID),
            test_wave_override=effective_wave_path,
            enable_audio=False,
        )
        result["launch"] = launch
        result["ownedProcessIds"] = game_process_ids(launch)
        host_pipe = str(launch.get("hostLuaPipe") or "")
        client_pipe = str(launch.get("clientLuaPipe") or "")
        if not host_pipe or not client_pipe:
            raise BotOnlyWaveFailure(f"Launcher omitted Lua pipes: {launch}")

        result["botConfiguration"] = configure_one_bot(
            args.runtime_root.resolve(),
            args.instance_prefix,
            host_pipe,
        )
        result["startMatch"] = start_stock_match(host_pipe)
        wait_for_scene(host_pipe, "testrun", 45.0)
        wait_for_scene(client_pipe, "testrun", 45.0)
        wait_for_remote(host_pipe, CLIENT_ID, CLIENT_NAME, "testrun", 45.0)
        wait_for_remote(client_pipe, HOST_ID, HOST_NAME, "testrun", 45.0)
        bot_state, bot_ready_at = wait_for(
            lambda: state(host_pipe),
            lambda values: (
                integer(values, "bot_count") == 1
                and integer(bot(values), "id") != 0
                and bot(values).get("materialized") == "true"
                and number(bot(values), "hp", 0.0) > 0.0
            ),
            label="one materialized bot",
            timeout=30.0,
        )
        bot_id = integer(bot(bot_state), "id")
        result["botReady"] = {
            "participantId": bot_id,
            "state": bot_state,
            "utc": bot_ready_at,
        }
        result["botProbeVitals"] = set_probe_bot_vitals(
            host_pipe,
            bot_id,
            args.bot_probe_hp,
            args.bot_probe_mp,
        )
        result["botBrainHeldForPressure"] = parse_key_values(
            lua(
                host_pipe,
                BOT_TARGET_HEADER
                + """
__botwaves_pressure_hold = true
if rawget(_G, "__botwaves_pressure_hold_subscription") == nil then
  __botwaves_pressure_hold_subscription = sd.events.on(
    "runtime.tick", function()
      if rawget(_G, "__botwaves_pressure_hold") ~= true then return end
      for _, current in ipairs(sd.bots.get_state() or {}) do
        if current.in_run == true then sd.bots.stop(current.id) end
      end
    end)
end
print("held=" .. tostring(__botwaves_pressure_hold == true))
""",
            )
        )
        result["damageObserversReset"] = parse_key_values(
            lua(
                host_pipe,
                BOT_TARGET_HEADER
                + """
print("enemy=" .. tostring(sd.debug.reset_enemy_damage_observations()))
print("player=" .. tostring(sd.debug.reset_player_damage_observations()))
""",
            )
        )
        result["waveEventObserver"] = install_wave_event_observer(host_pipe)
        result["proofWaveDelayFilter"] = install_proof_wave_delay_filter(
            host_pipe
        )
        started_at = utc_now()
        started = parse_key_values(
            lua(
                host_pipe,
                "print('ok=' .. tostring(sd.gameplay.start_waves()))",
            )
        )
        if started.get("ok") != "true":
            raise BotOnlyWaveFailure(f"Could not start waves: {started}")
        first_wave, first_wave_at = wait_for(
            lambda: state(host_pipe),
            lambda values: (
                integer(values, "wave") > 0
                and (
                    integer(values, "alive") > 0
                    or integer(values, "remaining") > 0
                )
            ),
            label="first scheduled wave with native hostiles",
            timeout=15.0,
        )
        starting_wave = integer(first_wave, "wave")
        result["warmupWave"] = clear_warmup_wave(
            host_pipe,
            starting_wave,
            timeout=45.0,
        )
        result["humanBoundaryShields"] = {
            "host": set_local_player_vitals(
                host_pipe,
                10000.0,
                10000.0,
                mp=50.0,
                max_mp=50.0,
            ),
            "client": set_local_player_vitals(
                client_pipe,
                10000.0,
                10000.0,
                mp=50.0,
                max_mp=50.0,
            ),
        }
        initial_boundary, initial_boundary_at = wait_for(
            lambda: state(host_pipe),
            lambda values: (
                integer(values, "wave") > starting_wave
                and number(local_human(values), "life", 0.0) > 0.0
                and number(participant(values, CLIENT_ID), "life", 0.0) > 0.0
                and any(
                    row.get("kind") == "started"
                    and integer(row, "wave") == integer(values, "wave")
                    and integer(values, "monotonic_ms")
                    - integer(row, "monotonic_ms")
                    >= 9000
                    for row in indexed_rows(values, "wave_event")
                )
                and (
                    integer(values, "alive") > 0
                    or integer(values, "remaining") > 0
                )
            ),
            label="current-wave respawn window elapsed before human deaths",
            timeout=20.0,
        )
        starting_wave = integer(initial_boundary, "wave")
        result["waveStart"] = {
            "request": started,
            "requestedAt": started_at,
            "firstState": first_wave,
            "firstObservedAt": first_wave_at,
            "boundaryState": initial_boundary,
            "boundaryObservedAt": initial_boundary_at,
        }
        result["proofEnemyHealthFixture"] = install_proof_enemy_health_fixture(
            host_pipe
        )
        result["proofDamageObserversReset"] = parse_key_values(
            lua(
                host_pipe,
                BOT_TARGET_HEADER
                + """
print("enemy=" .. tostring(sd.debug.reset_enemy_damage_observations()))
print("player=" .. tostring(sd.debug.reset_player_damage_observations()))
""",
            )
        )
        result["humanDeaths"] = [
            kill_humans(host_pipe, client_pipe, label="initial-client-then-host")
        ]
        spectating, spectating_at = wait_for(
            lambda: parse_key_values(
                lua(host_pipe, BOT_TARGET_HEADER + SPECTATOR_STATE_PROBE)
            ),
            lambda values: (
                values.get("active") == "true"
                and values.get("phase") == "Spectating"
                and integer(values, "target_participant_id") == bot_id
                and values.get("game_over_surface") == "false"
            ),
            label="dead host spectating the surviving bot",
            timeout=8.0,
        )
        result["hostSpectatingBot"] = {
            "state": spectating,
            "utc": spectating_at,
        }
        result["nativePressureContact"] = arrange_native_pressure_contact(
            host_pipe,
            bot_id,
        )
        pressure_state, pressure_at = wait_for(
            lambda: state(host_pipe),
            lambda values: (
                number(bot(values), "hp", args.bot_probe_hp)
                < args.bot_probe_hp
                and integer(values, "game_over_accepted_epoch") == 0
            ),
            label="native hostile damage against the surviving bot",
            timeout=30.0,
        )
        result["botPressureBeforeHealthReduction"] = {
            "state": pressure_state,
            "utc": pressure_at,
        }
        result["botOffenseEnabledForCombat"] = set_bot_offense(
            Path(result["botConfiguration"]["settingsPath"]),
            host_pipe,
            enabled=True,
        )
        result["botBrainReleasedForCombat"] = parse_key_values(
            lua(
                host_pipe,
                BOT_TARGET_HEADER
                + """
__botwaves_pressure_hold = false
print("held=" .. tostring(__botwaves_pressure_hold == true))
""",
            )
        )
        result["proofEnemyHealthReduction"] = lower_live_proof_enemy_health(
            host_pipe
        )
        cycles = observe_cycles(
            host_pipe,
            client_pipe,
            bot_id,
            settings_path=Path(
                result["botConfiguration"]["settingsPath"]
            ),
            starting_wave=starting_wave,
            cycles=args.cycles,
            timeout=args.progression_timeout,
        )
        result["cycles"] = cycles
        assert_cycle_contract(cycles, bot_id)
        if not args.skip_terminal:
            result["terminal"] = await_stock_game_over(
                host_pipe,
                client_pipe,
                bot_id,
                settings_path=Path(
                    result["botConfiguration"]["settingsPath"]
                ),
                timeout=args.terminal_timeout,
            )
        result["status"] = "passed"
        result["completedAt"] = utc_now()
        return result
    except Exception as error:
        result["status"] = "failed"
        result["error"] = f"{type(error).__name__}: {error}"
        if isinstance(error, BotOnlyWaveFailure) and error.evidence:
            result["partialEvidence"] = error.evidence
        result["failedAt"] = utc_now()
        raise
    finally:
        cleanup: list[dict[str, object]] = []
        if launch is not None:
            cleanup = stop_exact_game_processes(launch)
        result["cleanup"] = cleanup
        atomic_write_json(output_path, result)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE_ROOT)
    parser.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME_ROOT)
    parser.add_argument("--game-directory", type=Path, default=DEFAULT_GAME_DIRECTORY)
    parser.add_argument("--launcher", type=Path, default=DEFAULT_LAUNCHER)
    parser.add_argument("--wave-fixture", type=Path, default=DEFAULT_WAVE_FIXTURE)
    parser.add_argument("--instance-prefix", default="bw-final")
    parser.add_argument("--host-port", type=int, default=52261)
    parser.add_argument("--client-port", type=int, default=52262)
    parser.add_argument("--cycles", type=int, default=2)
    parser.add_argument("--bot-probe-hp", type=float, default=10000.0)
    parser.add_argument("--bot-probe-mp", type=float, default=1000.0)
    parser.add_argument("--progression-timeout", type=float, default=120.0)
    parser.add_argument("--terminal-timeout", type=float, default=60.0)
    parser.add_argument("--skip-terminal", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output is None:
        args.output = args.evidence_root / f"{args.instance_prefix}.json"
    if args.cycles < 2:
        parser.error("--cycles must be at least 2")
    if not math.isfinite(args.bot_probe_hp) or args.bot_probe_hp < 50.0:
        parser.error("--bot-probe-hp must be finite and at least 50")
    if not math.isfinite(args.bot_probe_mp) or args.bot_probe_mp < 100.0:
        parser.error("--bot-probe-mp must be finite and at least 100")
    return args


def main() -> int:
    args = parse_args()
    try:
        result = run(args)
    except Exception as error:
        print(f"FAIL: {error}")
        print(f"Evidence: {args.output.resolve()}")
        return 1
    print(
        "PASS: bot-only waves advanced "
        f"{result['cycles']['completedCycles']} full cycles"
    )
    print(f"Evidence: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
