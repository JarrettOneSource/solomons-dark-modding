#!/usr/bin/env python3
"""Verify connected death, spectator targeting, and wave respawn behavior."""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from collections.abc import Mapping
from pathlib import Path

from multiplayer_defense_behavior_harness import invoke_native_magic_hit_trial
from multiplayer_frame_capture import capture_game_backbuffer
from verify_player_health_death_sync import set_local_player_vitals
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    HOST_ID,
    HOST_NAME,
    ROOT,
    THIRD_ID,
    THIRD_NAME,
    VerifyFailure,
    game_process_ids,
    launch_pair,
    lua,
    parse_key_values,
    select_available_windows_udp_ports,
    start_testrun,
    stop_game_processes,
    wait_for_remote,
    wait_for_scene,
)
POSITION_TOLERANCE = 0.25
VITAL_TOLERANCE = 0.05
DEATH_TRANSITION_ADDRESS = 0x00534120
STAFF_DROP_ADDRESS = 0x00534270
DEATH_PRESENTATION_FLAG = 1 << 6
OUTPUT = ROOT / "runtime" / "multiplayer_death_spectator_respawn.json"
SCREENSHOT_ROOT = ROOT / "runtime" / "multiplayer_death_spectator_respawn"
ACCEPTANCE_MOD_ID = "sample.lua.ui_sandbox_lab"
WAVE_FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "waves"
    / "death_spectator_respawn_test.txt"
)


SPECTATOR_STATE_PROBE = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local multiplayer = assert(sd.runtime.get_multiplayer_state())
local spectator = assert(multiplayer.death_spectator)
local player = sd.player.get_state()
local actor = player and tonumber(player.actor_address) or 0
local world = sd.world.get_state()
local scene = sd.world.get_scene()
local ui = sd.ui and sd.ui.get_snapshot and sd.ui.get_snapshot() or nil
local camera_ok, camera = false, nil
if sd.camera ~= nil and sd.camera.get_state ~= nil then
  camera_ok, camera = pcall(sd.camera.get_state)
end
local target = nil
for _, participant in ipairs(multiplayer.participants or {}) do
  if participant.participant_id == spectator.target_participant_id then
    target = participant
    break
  end
end
local target_gameplay = nil
if spectator.target_participant_id ~= nil and
    spectator.target_participant_id ~= 0 then
  target_gameplay = sd.bots.get_participant_state(
    spectator.target_participant_id)
end
local death_drive_state = actor ~= 0 and
  (sd.debug.read_u8(actor +
    sd.debug.layout_offset("actor_animation_drive_state_byte")) or 0) or 0
local death_presentation_ticks = actor ~= 0 and
  (sd.debug.read_u32(actor +
    sd.debug.layout_offset("actor_animation_move_duration_ticks")) or 0) or 0
local terminal_pending = actor ~= 0 and
  (sd.debug.read_u8(actor +
    sd.debug.layout_offset("actor_terminal_dispatch_pending")) or 0) or 0
local terminal_countdown = actor ~= 0 and
  (sd.debug.read_u32(actor +
    sd.debug.layout_offset("actor_terminal_dispatch_countdown")) or 0) or 0
local death_transition_hits =
  sd.debug.get_trace_hits("player_death_transition") or {}
local staff_drop_hits =
  sd.debug.get_trace_hits("player_staff_drop") or {}
emit("active", spectator.active)
emit("phase", spectator.phase)
emit("death_started_ms", spectator.death_started_ms)
emit("presentation_remaining_ms", spectator.presentation_remaining_ms)
emit("target_participant_id", spectator.target_participant_id)
emit("target_name", spectator.target_name)
emit("waiting_for_alive_target", spectator.waiting_for_alive_target)
emit("last_applied_respawn_epoch", spectator.last_applied_respawn_epoch)
emit("last_applied_respawn_wave", spectator.last_applied_respawn_wave)
emit("last_respawn_x", spectator.last_respawn_x)
emit("last_respawn_y", spectator.last_respawn_y)
emit("display_text", spectator.display_text)
emit("scene", scene and (scene.name or scene.kind) or "")
emit("game_over_surface", ui ~= nil and ui.surface_id == "game_over")
emit("hp", player and player.hp or 0)
emit("max_hp", player and player.max_hp or 0)
emit("mp", player and player.mp or 0)
emit("max_mp", player and player.max_mp or 0)
emit("anim_drive_state", player and player.anim_drive_state or -1)
emit("materialized", actor ~= 0)
emit("actor_address", actor)
emit("grid_cell_address", player and player.grid_cell_address or 0)
emit("grid_member_flag", player and player.grid_member_flag or 0)
emit("render_sort_bias", player and player.render_sort_bias or 0)
emit("death_drive_state", death_drive_state)
emit("death_presentation_ticks", death_presentation_ticks)
emit("terminal_pending", terminal_pending)
emit("terminal_countdown", terminal_countdown)
emit("presentation_active", spectator.phase == "DeathPresentation")
emit("red_effect_active",
  death_drive_state ~= 0 and death_presentation_ticks > 150)
emit("death_transition_hits", #death_transition_hits)
emit("staff_drop_hits", #staff_drop_hits)
emit("attachment_type_id",
  player and player.attachment_visual_lane and
    player.attachment_visual_lane.current_object_type_id or 0)
emit("x", player and player.x or 0)
emit("y", player and player.y or 0)
emit("player_spawn_valid", world and world.player_spawn_valid or false)
emit("player_spawn_x", world and world.player_spawn_x or 0)
emit("player_spawn_y", world and world.player_spawn_y or 0)
emit("player_spawn_facing", world and world.player_spawn_facing or 0)
emit("arena_address", world and world.arena_address or 0)
emit("target_alive", target ~= nil and
  target.life_current > 0 and target.life_max > 0)
emit("target_x", target_gameplay and target_gameplay.x or 0)
emit("target_y", target_gameplay and target_gameplay.y or 0)
emit("camera_focus_active", camera_ok and camera.focus_active or false)
emit("camera_center_x", camera_ok and camera.center_x or 0)
emit("camera_center_y", camera_ok and camera.center_y or 0)
"""


REMOTE_DEATH_STATE_PROBE = r"""
local participant_id = __PARTICIPANT_ID__
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local multiplayer = assert(sd.runtime.get_multiplayer_state())
local participant = nil
for _, candidate in ipairs(multiplayer.participants or {}) do
  if candidate.participant_id == participant_id then
    participant = candidate
    break
  end
end
local gameplay = sd.bots.get_participant_state(participant_id)
local actor = gameplay and tonumber(gameplay.actor_address) or 0
local world = sd.world.get_state()
local grid_member_offset =
  sd.debug.layout_offset("actor_grid_member_flag")
local grid_cell_offset =
  sd.debug.layout_offset("actor_grid_cell_ptr")
local render_sort_offset =
  sd.debug.layout_offset("actor_render_sort_bias")
local death_drive_state = actor ~= 0 and
  (sd.debug.read_u8(actor +
    sd.debug.layout_offset("actor_animation_drive_state_byte")) or 0) or 0
local death_presentation_ticks = actor ~= 0 and
  (sd.debug.read_u32(actor +
    sd.debug.layout_offset("actor_animation_move_duration_ticks")) or 0) or 0
local terminal_pending = actor ~= 0 and
  (sd.debug.read_u8(actor +
    sd.debug.layout_offset("actor_terminal_dispatch_pending")) or 0) or 0
local terminal_countdown = actor ~= 0 and
  (sd.debug.read_u32(actor +
    sd.debug.layout_offset("actor_terminal_dispatch_countdown")) or 0) or 0
local presentation_flags = participant and participant.presentation_flags or 0
local death_transition_hits =
  sd.debug.get_trace_hits("player_death_transition") or {}
local staff_drop_hits =
  sd.debug.get_trace_hits("player_staff_drop") or {}
emit("materialized",
  gameplay ~= nil and gameplay.entity_materialized and actor ~= 0)
emit("actor_address", actor)
emit("x", gameplay and gameplay.x or 0)
emit("y", gameplay and gameplay.y or 0)
emit("participant_x", participant and participant.x or 0)
emit("participant_y", participant and participant.y or 0)
emit("grid_member_flag",
  actor ~= 0 and grid_member_offset ~= nil and
    (sd.debug.read_u8(actor + grid_member_offset) or 0) or 0)
emit("grid_cell_address",
  actor ~= 0 and grid_cell_offset ~= nil and
    (sd.debug.read_ptr(actor + grid_cell_offset) or 0) or 0)
emit("render_sort_bias",
  actor ~= 0 and render_sort_offset ~= nil and
    (sd.debug.read_float(actor + render_sort_offset) or 0) or 0)
emit("hp",
  gameplay and gameplay.hp or
    (participant and participant.life_current or 0))
emit("max_hp",
  gameplay and gameplay.max_hp or
    (participant and participant.life_max or 0))
emit("death_drive_state", death_drive_state)
emit("death_presentation_ticks", death_presentation_ticks)
emit("terminal_pending", terminal_pending)
emit("terminal_countdown", terminal_countdown)
emit("presentation_flags", presentation_flags)
emit("authoritative_death_presentation_ticks",
  participant and participant.death_presentation_tick or 0)
emit("presentation_active",
  math.floor(presentation_flags / __DEATH_PRESENTATION_FLAG__) % 2 == 1)
emit("red_effect_active",
  death_drive_state ~= 0 and death_presentation_ticks > 150)
emit("death_transition_hits", #death_transition_hits)
emit("staff_drop_hits", #staff_drop_hits)
emit("attachment_type_id",
  gameplay and gameplay.attachment_visual_lane and
    gameplay.attachment_visual_lane.current_object_type_id or 0)
emit("player_spawn_valid", world and world.player_spawn_valid or false)
emit("player_spawn_x", world and world.player_spawn_x or 0)
emit("player_spawn_y", world and world.player_spawn_y or 0)
emit("player_spawn_facing", world and world.player_spawn_facing or 0)
emit("arena_address", world and world.arena_address or 0)
"""


LOCAL_DEATH_VISUAL_PROBE = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local multiplayer = assert(sd.runtime.get_multiplayer_state())
local spectator = assert(multiplayer.death_spectator)
local player = sd.player.get_state()
local actor = player and tonumber(player.actor_address) or 0
local death_drive_state = actor ~= 0 and
  (sd.debug.read_u8(actor +
    sd.debug.layout_offset("actor_animation_drive_state_byte")) or 0) or 0
local death_presentation_ticks = actor ~= 0 and
  (sd.debug.read_u32(actor +
    sd.debug.layout_offset("actor_animation_move_duration_ticks")) or 0) or 0
local terminal_pending = actor ~= 0 and
  (sd.debug.read_u8(actor +
    sd.debug.layout_offset("actor_terminal_dispatch_pending")) or 0) or 0
emit("materialized", actor ~= 0)
emit("hp", player and player.hp or 0)
emit("death_drive_state", death_drive_state)
emit("death_presentation_ticks", death_presentation_ticks)
emit("terminal_pending", terminal_pending)
emit("presentation_active", spectator.phase == "DeathPresentation")
emit("red_effect_active",
  death_drive_state ~= 0 and death_presentation_ticks > 150)
"""


REMOTE_DEATH_VISUAL_PROBE = r"""
local participant_id = __PARTICIPANT_ID__
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local multiplayer = assert(sd.runtime.get_multiplayer_state())
local participant = nil
for _, candidate in ipairs(multiplayer.participants or {}) do
  if candidate.participant_id == participant_id then
    participant = candidate
    break
  end
end
local gameplay = sd.bots.get_participant_state(participant_id)
local actor = gameplay and tonumber(gameplay.actor_address) or 0
local death_drive_state = actor ~= 0 and
  (sd.debug.read_u8(actor +
    sd.debug.layout_offset("actor_animation_drive_state_byte")) or 0) or 0
local death_presentation_ticks = actor ~= 0 and
  (sd.debug.read_u32(actor +
    sd.debug.layout_offset("actor_animation_move_duration_ticks")) or 0) or 0
local terminal_pending = actor ~= 0 and
  (sd.debug.read_u8(actor +
    sd.debug.layout_offset("actor_terminal_dispatch_pending")) or 0) or 0
local presentation_flags = participant and participant.presentation_flags or 0
emit("materialized",
  gameplay ~= nil and gameplay.entity_materialized and actor ~= 0)
emit("hp",
  gameplay and gameplay.hp or
    (participant and participant.life_current or 0))
emit("death_drive_state", death_drive_state)
emit("death_presentation_ticks", death_presentation_ticks)
emit("terminal_pending", terminal_pending)
emit("presentation_active",
  math.floor(presentation_flags / __DEATH_PRESENTATION_FLAG__) % 2 == 1)
emit("red_effect_active",
  death_drive_state ~= 0 and death_presentation_ticks > 150)
"""


ARM_DEATH_TRACES = f"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
sd.debug.clear_trace_hits("player_death_transition")
sd.debug.clear_trace_hits("player_staff_drop")
local death_ok, death_error = sd.debug.trace_function(
  0x{DEATH_TRANSITION_ADDRESS:08X}, "player_death_transition", 7)
local staff_ok, staff_error = sd.debug.trace_function(
  0x{STAFF_DROP_ADDRESS:08X}, "player_staff_drop", 7)
emit("death_ok", death_ok)
emit("death_error", death_error or "")
emit("staff_ok", staff_ok)
emit("staff_error", staff_error or "")
"""


WAVE_STATE_PROBE = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local state = assert(sd.waves.get_state())
emit("wave", state.wave)
emit("phase", state.phase)
emit("remaining_to_spawn", state.remaining_to_spawn)
emit("alive", state.alive)
emit("killed", state.killed)
"""


KILL_LIVE_WAVE_ENEMIES = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local actors = sd.world.list_actors and sd.world.list_actors() or {}
local hp_offset = sd.debug.layout_offset("enemy_current_hp")
local max_hp_offset = sd.debug.layout_offset("enemy_max_hp")
local progression_offset =
  sd.debug.layout_offset("actor_progression_runtime_state")
local progression_hp_offset = sd.debug.layout_offset("progression_hp")
local progression_max_hp_offset =
  sd.debug.layout_offset("progression_max_hp")
local attempted = 0
local triggered = 0
for _, actor in ipairs(actors) do
  local address = tonumber(actor.actor_address) or 0
  local max_hp = tonumber(actor.max_hp) or 0
  if address ~= 0 and actor.tracked_enemy and not actor.dead and max_hp > 0 then
    attempted = attempted + 1
    sd.debug.write_float(address + max_hp_offset, math.max(max_hp, 1))
    sd.debug.write_float(address + hp_offset, 0)
    local progression =
      tonumber(sd.debug.read_ptr(address + progression_offset)) or 0
    if progression ~= 0 then
      sd.debug.write_float(
        progression + progression_max_hp_offset,
        math.max(max_hp, 1))
      sd.debug.write_float(progression + progression_hp_offset, 0)
    end
    local ok = sd.world.trigger_enemy_death(address)
    if ok then triggered = triggered + 1 end
  end
end
emit("attempted", attempted)
emit("triggered", triggered)
"""


def _apply_authoritative_host_lethal_hit(
    host_pipe: str,
) -> dict[str, object]:
    trial = invoke_native_magic_hit_trial(
        host_pipe,
        projectile_damage=0.0,
        magic_damage=1000.0,
        attempts=8,
        label="host death spectator",
        timeout=8.0,
        target_participant_id=0,
    )
    hp_after = float(trial["hp_after"])
    if not math.isfinite(hp_after) or hp_after > VITAL_TOLERANCE:
        raise VerifyFailure(
            "authoritative host lethal hit did not reach zero life: "
            f"{trial}"
        )
    return trial


def _apply_authoritative_client_lethal_hit(
    host_pipe: str,
) -> dict[str, object]:
    trial = invoke_native_magic_hit_trial(
        host_pipe,
        projectile_damage=0.0,
        magic_damage=1000.0,
        attempts=2,
        label="client death spectator",
        timeout=8.0,
        target_participant_id=CLIENT_ID,
    )
    hp_after = float(trial["hp_after"])
    if not math.isfinite(hp_after) or hp_after > VITAL_TOLERANCE:
        raise VerifyFailure(
            "authoritative client lethal hit did not reach zero life: "
            f"{trial}"
        )
    return trial


def _establish_local_lethal_precondition(
    pipe_name: str,
    owner_label: str,
) -> dict[str, str]:
    values = set_local_player_vitals(
        pipe_name,
        1.0,
        50.0,
        mp=50.0,
        max_mp=50.0,
    )
    hp = _number(values, "after.hp")
    max_hp = _number(values, "after.max_hp")
    if (
        not math.isfinite(hp)
        or abs(hp - 1.0) > VITAL_TOLERANCE
        or not math.isfinite(max_hp)
        or abs(max_hp - 50.0) > VITAL_TOLERANCE
        or _integer(values, "after.anim_drive_state") != 0
    ):
        raise VerifyFailure(
            f"{owner_label} lethal precondition did not preserve a living "
            "actor: "
            f"{values}"
        )
    return values


def _establish_host_lethal_precondition(
    host_pipe: str,
) -> dict[str, str]:
    return _establish_local_lethal_precondition(host_pipe, "host")


def _number(values: Mapping[str, str], key: str) -> float:
    try:
        value = float(values.get(key, "nan"))
    except (TypeError, ValueError):
        return math.nan
    return value if math.isfinite(value) else math.nan


def _integer(values: Mapping[str, str], key: str) -> int:
    raw = values.get(key, "")
    try:
        return int(raw, 0)
    except (TypeError, ValueError):
        try:
            return int(float(raw))
        except (TypeError, ValueError, OverflowError):
            return -1


def death_animation_sync_matches(
    states: list[Mapping[str, str]],
    *,
    presentation_active: bool,
) -> bool:
    if not states:
        return False
    for values in states:
        hp = _number(values, "hp")
        presentation_ticks = _integer(
            values,
            "death_presentation_ticks",
        )
        if (
            values.get("materialized") != "true"
            or not math.isfinite(hp)
            or hp > VITAL_TOLERANCE
            or _integer(values, "death_drive_state") != 1
            or _integer(values, "terminal_pending") != 0
            or values.get("presentation_active")
            != ("true" if presentation_active else "false")
            or presentation_ticks < 0
            or presentation_ticks > 298
        ):
            return False
        if not presentation_active and (
            presentation_ticks > 150
            or values.get("red_effect_active") != "false"
        ):
            return False
    return True


def death_animation_clock_sync_matches(
    states: list[Mapping[str, str]],
) -> bool:
    if not states:
        return False
    presentation_ticks = [
        _integer(values, "death_presentation_ticks")
        for values in states
    ]
    return (
        min(presentation_ticks) >= 0
        and max(presentation_ticks) - min(presentation_ticks) <= 40
    )


def red_death_effect_matches(
    values: Mapping[str, str],
    *,
    active: bool,
) -> bool:
    presentation_ticks = _integer(
        values,
        "death_presentation_ticks",
    )
    if active:
        return (
            values.get("presentation_active") == "true"
            and _integer(values, "death_drive_state") == 1
            and 150 < presentation_ticks <= 298
            and values.get("red_effect_active") == "true"
        )
    return (
        values.get("presentation_active") == "false"
        and presentation_ticks <= 150
        and values.get("red_effect_active") == "false"
    )


def staff_drop_once_matches(
    states: Mapping[str, Mapping[str, str]],
    *,
    owner_label: str,
) -> bool:
    if owner_label not in states:
        return False
    for label, values in states.items():
        expected = 1 if label == owner_label else 0
        if (
            _integer(values, "death_transition_hits") != expected
            or _integer(values, "staff_drop_hits") != expected
        ):
            return False
    return True


def spectator_state_matches(values: Mapping[str, str]) -> bool:
    target_id = _integer(values, "target_participant_id")
    center_x = _number(values, "camera_center_x")
    center_y = _number(values, "camera_center_y")
    target_x = _number(values, "target_x")
    target_y = _number(values, "target_y")
    target_name = values.get("target_name", "")
    display_text = values.get("display_text", "")
    return (
        values.get("active") == "true"
        and values.get("phase") == "Spectating"
        and _integer(values, "presentation_remaining_ms") == 0
        and target_id > 0
        and bool(target_name)
        and values.get("waiting_for_alive_target") == "false"
        and values.get("target_alive") == "true"
        and values.get("camera_focus_active") == "true"
        and math.isfinite(center_x)
        and math.isfinite(center_y)
        and math.isfinite(target_x)
        and math.isfinite(target_y)
        and abs(center_x - target_x) <= POSITION_TOLERANCE
        and abs(center_y - target_y) <= POSITION_TOLERANCE
        and display_text
        == f"Spectating {target_name}  |  Left / Right click: next player"
    )


def death_presentation_state_matches(
    values: Mapping[str, str],
) -> bool:
    remaining_ms = _integer(
        values,
        "presentation_remaining_ms",
    )
    hp = _number(values, "hp")
    return (
        values.get("active") == "true"
        and values.get("phase") == "DeathPresentation"
        and 0 < remaining_ms <= 3000
        and values.get("scene") == "testrun"
        and values.get("game_over_surface") == "false"
        and math.isfinite(hp)
        and hp <= VITAL_TOLERANCE
        and _integer(values, "anim_drive_state") == 1
        and values.get("display_text", "") == ""
    )


def respawn_state_matches(
    values: Mapping[str, str],
    *,
    previous_epoch: int,
    expected_wave: int,
) -> bool:
    epoch = _integer(values, "last_applied_respawn_epoch")
    hp = _number(values, "hp")
    max_hp = _number(values, "max_hp")
    mp = _number(values, "mp")
    max_mp = _number(values, "max_mp")
    x = _number(values, "x")
    y = _number(values, "y")
    respawn_x = _number(values, "last_respawn_x")
    respawn_y = _number(values, "last_respawn_y")
    return (
        values.get("active") == "false"
        and values.get("phase") == "Inactive"
        and epoch > previous_epoch
        and _integer(values, "last_applied_respawn_wave") == expected_wave
        and math.isfinite(hp)
        and math.isfinite(max_hp)
        and max_hp > 0.0
        and abs(hp - max_hp) <= VITAL_TOLERANCE
        and math.isfinite(mp)
        and math.isfinite(max_mp)
        and max_mp > 0.0
        and abs(mp - max_mp) <= VITAL_TOLERANCE
        and _integer(values, "anim_drive_state") == 0
        and _integer(values, "death_presentation_ticks") == 0
        and _integer(values, "terminal_pending") == 0
        and math.isfinite(x)
        and math.isfinite(y)
        and math.isfinite(respawn_x)
        and math.isfinite(respawn_y)
        and abs(x - respawn_x) <= POSITION_TOLERANCE
        and abs(y - respawn_y) <= POSITION_TOLERANCE
    )


def _reserve_udp_ports(count: int) -> list[int]:
    return select_available_windows_udp_ports(count)


def _resolve_udp_ports(
    host_port: int | None,
    client_port: int | None,
    third_port: int | None,
) -> list[int]:
    explicit = [host_port, client_port, third_port]
    if all(port is None for port in explicit):
        return _reserve_udp_ports(3)
    if any(port is None for port in explicit):
        raise ValueError(
            "all three ports must be provided together"
        )
    ports = [int(port) for port in explicit if port is not None]
    if any(port < 1 or port > 0xFFFF for port in ports):
        raise ValueError("explicit UDP ports must be between 1 and 65535")
    if len(set(ports)) != 3:
        raise ValueError("explicit UDP ports must be distinct")
    return ports


def _default_instance_prefix() -> str:
    return f"ds-{os.getpid():x}-{time.time_ns() & 0xFFFF:04x}"


def query_spectator_state(pipe_name: str) -> dict[str, str]:
    return parse_key_values(
        lua(pipe_name, SPECTATOR_STATE_PROBE, timeout=8.0)
    )


def query_remote_death_state(
    pipe_name: str,
    participant_id: int,
) -> dict[str, str]:
    code = REMOTE_DEATH_STATE_PROBE.replace(
        "__PARTICIPANT_ID__",
        str(participant_id),
    ).replace(
        "__DEATH_PRESENTATION_FLAG__",
        str(DEATH_PRESENTATION_FLAG),
    )
    return parse_key_values(lua(pipe_name, code, timeout=8.0))


def query_local_death_visual_state(
    pipe_name: str,
) -> dict[str, str]:
    return parse_key_values(
        lua(pipe_name, LOCAL_DEATH_VISUAL_PROBE, timeout=8.0)
    )


def query_remote_death_visual_state(
    pipe_name: str,
    participant_id: int,
) -> dict[str, str]:
    code = REMOTE_DEATH_VISUAL_PROBE.replace(
        "__PARTICIPANT_ID__",
        str(participant_id),
    ).replace(
        "__DEATH_PRESENTATION_FLAG__",
        str(DEATH_PRESENTATION_FLAG),
    )
    return parse_key_values(lua(pipe_name, code, timeout=8.0))


def _arm_death_traces(pipe_names: list[str]) -> dict[str, dict[str, str]]:
    armed: dict[str, dict[str, str]] = {}
    for pipe_name in pipe_names:
        values = parse_key_values(
            lua(pipe_name, ARM_DEATH_TRACES, timeout=8.0)
        )
        if (
            values.get("death_ok") != "true"
            or values.get("staff_ok") != "true"
        ):
            raise VerifyFailure(
                f"native death trace arm failed on {pipe_name}: {values}"
            )
        armed[pipe_name] = values
    return armed


def _disarm_death_traces(pipe_names: list[str]) -> None:
    for pipe_name in pipe_names:
        try:
            lua(
                pipe_name,
                "sd.debug.untrace_function("
                f"0x{STAFF_DROP_ADDRESS:08X}); "
                "sd.debug.untrace_function("
                f"0x{DEATH_TRANSITION_ADDRESS:08X}); return 'ok'",
                timeout=3.0,
            )
        except Exception:
            pass


def _wait_for_values(
    pipe_name: str,
    predicate,
    *,
    timeout: float,
    description: str,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    last_error = ""
    while time.monotonic() < deadline:
        try:
            last = query_spectator_state(pipe_name)
            last_error = ""
            if predicate(last):
                return last
        except Exception as exc:  # noqa: BLE001 - preserve probe evidence.
            last_error = str(exc)
        time.sleep(0.05)
    suffix = f" last_error={last_error}" if last_error else ""
    raise VerifyFailure(
        f"timed out waiting for {description} on {pipe_name}; "
        f"last={last}.{suffix}"
    )


def _wait_for_remote_death_values(
    pipe_name: str,
    participant_id: int,
    predicate,
    *,
    timeout: float,
    description: str,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    last_error = ""
    while time.monotonic() < deadline:
        try:
            last = query_remote_death_state(
                pipe_name,
                participant_id,
            )
            last_error = ""
            if predicate(last):
                return last
        except Exception as exc:  # noqa: BLE001 - preserve probe evidence.
            last_error = str(exc)
        time.sleep(0.05)
    suffix = f" last_error={last_error}" if last_error else ""
    raise VerifyFailure(
        f"timed out waiting for {description} on {pipe_name}; "
        f"last={last}.{suffix}"
    )


def _wait_for_participant_death_visual_phase(
    owner_label: str,
    owner_pipe: str,
    participant_id: int,
    observer_pipes: Mapping[str, str],
    *,
    active: bool,
    timeout: float,
) -> dict[str, dict[str, str]]:
    deadline = time.monotonic() + timeout
    last: dict[str, dict[str, str]] = {}
    last_error = ""
    while time.monotonic() < deadline:
        try:
            last = {
                owner_label: query_local_death_visual_state(owner_pipe),
                **{
                    label: query_remote_death_visual_state(
                        pipe_name,
                        participant_id,
                    )
                    for label, pipe_name in observer_pipes.items()
                },
            }
            last_error = ""
            if all(
                red_death_effect_matches(values, active=active)
                for values in last.values()
            ) and (
                not active
                or death_animation_clock_sync_matches(
                    list(last.values())
                )
            ):
                return last
        except Exception as exc:  # noqa: BLE001 - preserve probe evidence.
            last_error = str(exc)
        time.sleep(0.02)
    suffix = f" last_error={last_error}" if last_error else ""
    phase = "active" if active else "cleared"
    raise VerifyFailure(
        f"timed out waiting for synchronized {owner_label} red death "
        f"effect {phase}; "
        f"last={last}.{suffix}"
    )


def _disable_bots(pipe_names: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for pipe_name in pipe_names:
        raw = lua(
            pipe_name,
            "lua_bots_disable_tick = true; sd.bots.clear(); "
            "return tostring(sd.bots.get_count())",
        ).strip()
        try:
            count = int(raw)
        except ValueError as exc:
            raise VerifyFailure(
                f"invalid bot count on {pipe_name}: {raw!r}"
            ) from exc
        if count != 0:
            raise VerifyFailure(
                f"bots remained active on {pipe_name}: {count}"
            )
        counts[pipe_name] = count
    return counts


def _start_testrun_when_ready(
    host_pipe: str,
    *,
    timeout: float = 20.0,
) -> None:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            start_testrun(host_pipe)
            return
        except VerifyFailure as exc:
            last_error = str(exc)
        time.sleep(0.25)
    raise VerifyFailure(
        "host testrun request never reached stable scene identity: "
        f"{last_error}"
    )


def _wait_for_wave(
    pipe_name: str,
    predicate,
    *,
    timeout: float,
    description: str,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = parse_key_values(
            lua(pipe_name, WAVE_STATE_PROBE, timeout=8.0)
        )
        if predicate(last):
            return last
        time.sleep(0.1)
    raise VerifyFailure(
        f"timed out waiting for {description}; last={last}"
    )


def _trigger_all_live_wave_enemy_deaths(
    host_pipe: str,
    *,
    timeout: float = 15.0,
) -> list[dict[str, str]]:
    deadline = time.monotonic() + timeout
    attempts: list[dict[str, str]] = []
    while time.monotonic() < deadline:
        wave = parse_key_values(
            lua(host_pipe, WAVE_STATE_PROBE, timeout=8.0)
        )
        if (
            wave.get("phase") == "completed"
            and int(wave.get("wave", "0")) > 0
        ):
            return attempts
        result = parse_key_values(
            lua(host_pipe, KILL_LIVE_WAVE_ENEMIES, timeout=8.0)
        )
        attempts.append(result)
        time.sleep(0.1)
    raise VerifyFailure(
        "host wave did not complete after native enemy death triggers; "
        f"attempts={attempts[-5:]}"
    )


def _cycle_spectator_target(
    pipe_name: str,
    *,
    previous_target_id: int,
    input_code: str,
    description: str,
) -> dict[str, str]:
    accepted = lua(pipe_name, input_code).strip()
    if accepted != "true":
        raise VerifyFailure(
            f"{description} input was not accepted: {accepted!r}"
        )
    return _wait_for_values(
        pipe_name,
        lambda values: spectator_state_matches(values)
        and _integer(values, "target_participant_id")
        != previous_target_id,
        timeout=3.0,
        description=description,
    )


def _verify_client_death_regression(
    host_pipe: str,
    client_pipe: str,
    third_pipe: str,
    pipe_names: list[str],
) -> dict[str, object]:
    result: dict[str, object] = {}
    _disarm_death_traces(pipe_names)
    result["death_traces_armed"] = _arm_death_traces(pipe_names)
    result["predeath_client"] = _wait_for_values(
        client_pipe,
        lambda values: _integer(values, "attachment_type_id") == 0x1B5C,
        timeout=8.0,
        description="client staff attachment before death",
    )
    result["lethal_precondition"] = _establish_local_lethal_precondition(
        client_pipe,
        "client",
    )
    death_written_at = time.monotonic()
    result["lethal_hit"] = _apply_authoritative_client_lethal_hit(host_pipe)
    death_presentation = _wait_for_values(
        client_pipe,
        death_presentation_state_matches,
        timeout=5.0,
        description="client native death presentation without Game Over",
    )
    result["death_presentation"] = death_presentation

    red_effect_during_grace = (
        _wait_for_participant_death_visual_phase(
            "client",
            client_pipe,
            CLIENT_ID,
            {
                "host": host_pipe,
                "third": third_pipe,
            },
            active=True,
            timeout=3.2,
        )
    )
    result["death_animation_grace"] = red_effect_during_grace
    if not death_animation_sync_matches(
        list(red_effect_during_grace.values()),
        presentation_active=True,
    ) or not death_animation_clock_sync_matches(
        list(red_effect_during_grace.values())
    ):
        raise VerifyFailure(
            "client death presentation clocks diverged across owner and "
            f"observers: {red_effect_during_grace}"
        )
    result["red_effect_during_grace"] = red_effect_during_grace

    spectating = _wait_for_values(
        client_pipe,
        spectator_state_matches,
        timeout=6.0,
        description="client spectator mode with a live target",
    )
    spectator_delay = time.monotonic() - death_written_at
    if spectator_delay < 2.8:
        raise VerifyFailure(
            "client spectator mode started before the three-second native "
            f"death presentation elapsed: {spectator_delay:.3f}s"
        )
    result["spectator_delay_seconds"] = spectator_delay
    result["spectating_initial"] = spectating

    red_effect_after_grace = _wait_for_participant_death_visual_phase(
        "client",
        client_pipe,
        CLIENT_ID,
        {
            "host": host_pipe,
            "third": third_pipe,
        },
        active=False,
        timeout=5.0,
    )
    if not death_animation_sync_matches(
        list(red_effect_after_grace.values()),
        presentation_active=False,
    ):
        raise VerifyFailure(
            "client death effect remained active after the three-second "
            f"grace period: {red_effect_after_grace}"
        )
    result["death_animation_after_grace"] = red_effect_after_grace

    initial_target = _integer(spectating, "target_participant_id")
    after_left = _cycle_spectator_target(
        client_pipe,
        previous_target_id=initial_target,
        input_code="return tostring(sd.input.click_normalized(0.5, 0.5))",
        description="client left-click spectator cycle",
    )
    result["spectating_after_left"] = after_left
    time.sleep(0.25)
    result["spectating_after_right"] = _cycle_spectator_target(
        client_pipe,
        previous_target_id=_integer(
            after_left,
            "target_participant_id",
        ),
        input_code="return tostring(sd.input.hold_mouse_right_frames(1))",
        description="client right-click spectator cycle",
    )

    result["repeat_lethal_hit"] = invoke_native_magic_hit_trial(
        host_pipe,
        projectile_damage=0.0,
        magic_damage=1000.0,
        attempts=2,
        label="dead client repeated lethal hit",
        timeout=8.0,
        require_life_loss=False,
        target_participant_id=CLIENT_ID,
    )
    time.sleep(0.5)
    drop_trace_states = {
        "client": query_spectator_state(client_pipe),
        "host": query_remote_death_state(host_pipe, CLIENT_ID),
        "third": query_remote_death_state(third_pipe, CLIENT_ID),
    }
    if not staff_drop_once_matches(
        drop_trace_states,
        owner_label="client",
    ):
        raise VerifyFailure(
            "staff drop did not remain exactly once for the client death "
            f"epoch: {drop_trace_states}"
        )
    result["staff_drop_once"] = drop_trace_states
    return result


def run_live_verification(
    *,
    instance_prefix: str,
    ports: list[int],
    game_directory: Path | None,
) -> dict[str, object]:
    launch = launch_pair(
        host_preset="map_create_fire_mind_hub",
        client_preset="map_create_water_body_hub",
        third_preset="map_create_earth_arcane_hub",
        temporary_host_profile=True,
        tile_windows=False,
        test_wave_override=WAVE_FIXTURE,
        third_player=True,
        kill_existing=False,
        instance_prefix=instance_prefix,
        host_port=ports[0],
        client_port=ports[1],
        third_port=ports[2],
        game_directory=game_directory,
        exact_mod_id=ACCEPTANCE_MOD_ID,
    )
    process_ids = game_process_ids(launch)
    if len(process_ids) != 3:
        stop_game_processes(process_ids)
        raise VerifyFailure(
            f"isolated trio did not report three process IDs: {launch}"
        )

    host_pipe = str(launch["hostLuaPipe"])
    client_pipe = str(launch["clientLuaPipe"])
    third_pipe = str(launch["thirdLuaPipe"])
    pipe_names = [host_pipe, client_pipe, third_pipe]
    result: dict[str, object] = {
        "launch": launch,
        "process_ids": process_ids,
        "instance_prefix": instance_prefix,
        "ports": ports,
    }
    try:
        result["bots_disabled"] = _disable_bots(pipe_names)
        _start_testrun_when_ready(host_pipe)
        for pipe_name in pipe_names:
            wait_for_scene(pipe_name, "testrun", 45.0)

        participants = (
            (host_pipe, HOST_ID, HOST_NAME),
            (client_pipe, CLIENT_ID, CLIENT_NAME),
            (third_pipe, THIRD_ID, THIRD_NAME),
        )
        relationships: dict[str, dict[str, str]] = {}
        for observer_pipe, observer_id, _ in participants:
            for _, owner_id, owner_name in participants:
                if owner_id == observer_id:
                    continue
                key = f"{observer_id:x}_observes_{owner_id:x}"
                relationships[key] = wait_for_remote(
                    observer_pipe,
                    owner_id,
                    owner_name,
                    "testrun",
                    45.0,
                )
        result["relationships"] = relationships

        result["death_traces_armed"] = _arm_death_traces(pipe_names)
        predeath_host = _wait_for_values(
            host_pipe,
            lambda values: _integer(values, "attachment_type_id")
            == 0x1B5C,
            timeout=8.0,
            description="host staff attachment before death",
        )
        result["predeath_host"] = predeath_host

        result["host_lethal_precondition"] = (
            _establish_host_lethal_precondition(host_pipe)
        )
        death_written_at = time.monotonic()
        result["lethal_hit"] = _apply_authoritative_host_lethal_hit(
            host_pipe
        )
        death_presentation = _wait_for_values(
            host_pipe,
            death_presentation_state_matches,
            timeout=5.0,
            description="host native death presentation without Game Over",
        )
        result["death_presentation"] = death_presentation

        grace_observers = {
            "client": _wait_for_remote_death_values(
                client_pipe,
                HOST_ID,
                lambda values: death_animation_sync_matches(
                    [values],
                    presentation_active=True,
                ),
                timeout=5.0,
                description="client view of host death presentation",
            ),
            "third": _wait_for_remote_death_values(
                third_pipe,
                HOST_ID,
                lambda values: death_animation_sync_matches(
                    [values],
                    presentation_active=True,
                ),
                timeout=5.0,
                description="third view of host death presentation",
            ),
        }
        grace_states = [
            death_presentation,
            grace_observers["client"],
            grace_observers["third"],
        ]
        if not death_animation_sync_matches(
            grace_states,
            presentation_active=True,
        ):
            raise VerifyFailure(
                "host death animation phase did not agree across owner and "
                f"observers: {grace_states}"
            )
        result["death_animation_grace"] = {
            "host": death_presentation,
            **grace_observers,
        }

        red_effect_during_grace = _wait_for_participant_death_visual_phase(
            "host",
            host_pipe,
            HOST_ID,
            {
                "client": client_pipe,
                "third": third_pipe,
            },
            active=True,
            timeout=3.2,
        )
        if not death_animation_sync_matches(
            list(red_effect_during_grace.values()),
            presentation_active=True,
        ) or not death_animation_clock_sync_matches(
            list(red_effect_during_grace.values())
        ):
            raise VerifyFailure(
                "host death presentation clocks diverged across owner and "
                f"observers: {red_effect_during_grace}"
            )
        result["red_effect_during_grace"] = red_effect_during_grace
        result["red_effect_observed_delay_seconds"] = (
            time.monotonic() - death_written_at
        )

        spectating = _wait_for_values(
            host_pipe,
            spectator_state_matches,
            timeout=6.0,
            description="host spectator mode with a live target",
        )
        spectator_delay = time.monotonic() - death_written_at
        if spectator_delay < 2.8:
            raise VerifyFailure(
                "spectator mode started before the three-second native "
                f"death presentation elapsed: {spectator_delay:.3f}s"
            )
        if spectator_delay > 4.0:
            raise VerifyFailure(
                "spectator mode did not start when the three-second native "
                f"death presentation elapsed: {spectator_delay:.3f}s"
            )
        result["spectator_delay_seconds"] = spectator_delay
        result["spectating_initial"] = spectating

        red_effect_after_grace = _wait_for_participant_death_visual_phase(
            "host",
            host_pipe,
            HOST_ID,
            {
                "client": client_pipe,
                "third": third_pipe,
            },
            active=False,
            timeout=5.0,
        )
        post_grace_observers = {
            "client": red_effect_after_grace["client"],
            "third": red_effect_after_grace["third"],
        }
        post_grace_states = [
            red_effect_after_grace["host"],
            post_grace_observers["client"],
            post_grace_observers["third"],
        ]
        if not death_animation_sync_matches(
            post_grace_states,
            presentation_active=False,
        ):
            raise VerifyFailure(
                "death effect remained active after the three-second grace "
                f"period: {post_grace_states}"
            )
        result["death_animation_after_grace"] = {
            "host": red_effect_after_grace["host"],
            **post_grace_observers,
        }
        screenshot_directory = SCREENSHOT_ROOT / instance_prefix
        result["screenshots"] = {
            "spectating_host_owner": capture_game_backbuffer(
                host_pipe,
                screenshot_directory / "host-spectating-owner.png",
            ),
            "spectating_client_observer": capture_game_backbuffer(
                client_pipe,
                screenshot_directory
                / "host-spectating-client-observer.png",
            ),
        }

        initial_target = _integer(
            spectating,
            "target_participant_id",
        )
        after_left = _cycle_spectator_target(
            host_pipe,
            previous_target_id=initial_target,
            input_code=(
                "return tostring(sd.input.click_normalized(0.5, 0.5))"
            ),
            description="left-click spectator cycle",
        )
        result["spectating_after_left"] = after_left
        time.sleep(0.25)
        after_right = _cycle_spectator_target(
            host_pipe,
            previous_target_id=_integer(
                after_left,
                "target_participant_id",
            ),
            input_code=(
                "return tostring(sd.input.hold_mouse_right_frames(1))"
            ),
            description="right-click spectator cycle",
        )
        result["spectating_after_right"] = after_right

        result["repeat_lethal_hit"] = invoke_native_magic_hit_trial(
            host_pipe,
            projectile_damage=0.0,
            magic_damage=1000.0,
            attempts=5,
            label="dead host repeated lethal hit",
            timeout=8.0,
            require_life_loss=False,
            target_participant_id=0,
        )
        time.sleep(0.5)
        drop_trace_states = {
            "host": query_spectator_state(host_pipe),
            "client": query_remote_death_state(client_pipe, HOST_ID),
            "third": query_remote_death_state(third_pipe, HOST_ID),
        }
        if not staff_drop_once_matches(
            drop_trace_states,
            owner_label="host",
        ):
            raise VerifyFailure(
                "staff drop did not remain exactly once for the host death "
                f"epoch: {drop_trace_states}"
            )
        result["staff_drop_once"] = drop_trace_states

        previous_epochs = {
            pipe_name: _integer(
                query_spectator_state(pipe_name),
                "last_applied_respawn_epoch",
            )
            for pipe_name in pipe_names
        }
        start_values = parse_key_values(
            lua(
                host_pipe,
                "print('ok=' .. tostring(sd.gameplay.start_waves()))",
            )
        )
        if start_values.get("ok") != "true":
            raise VerifyFailure(
                f"host could not start the respawn wave: {start_values}"
            )
        host_authority_observers: dict[str, dict[str, str]] = {}
        for label, pipe_name in (
            ("host", host_pipe),
            ("client", client_pipe),
            ("third", third_pipe),
        ):
            host_authority_observers[label] = _wait_for_wave(
                pipe_name,
                lambda values: int(values.get("alive", "0")) > 0,
                timeout=15.0,
                description=(
                    f"{label} observing host-authored wave while host dead"
                ),
            )
        result["host_authority_observers"] = host_authority_observers
        result["enemy_death_triggers"] = (
            _trigger_all_live_wave_enemy_deaths(host_pipe)
        )
        completed = _wait_for_wave(
            host_pipe,
            lambda values: values.get("phase") == "completed"
            and int(values.get("wave", "0")) > 0,
            timeout=8.0,
            description="wave completion",
        )
        completed_wave = int(completed["wave"])
        result["wave_completed"] = completed
        result["wave_completed_observers"] = {
            label: _wait_for_wave(
                pipe_name,
                lambda values, wave=completed_wave:
                    values.get("phase") == "completed"
                    and int(values.get("wave", "0")) == wave,
                timeout=8.0,
                description=(
                    f"{label} observing host-authored wave completion"
                ),
            )
            for label, pipe_name in (
                ("client", client_pipe),
                ("third", third_pipe),
            )
        }

        respawned: dict[str, dict[str, str]] = {}
        for pipe_name in pipe_names:
            respawned[pipe_name] = _wait_for_values(
                pipe_name,
                lambda values, pipe=pipe_name: respawn_state_matches(
                    values,
                    previous_epoch=previous_epochs[pipe],
                    expected_wave=completed_wave,
                ),
                timeout=8.0,
                description=(
                    f"wave-{completed_wave} owner-local respawn"
                ),
            )
        result["respawned"] = respawned
        result["host_respawned"] = respawned[host_pipe]
        result["client_death_regression"] = (
            _verify_client_death_regression(
                host_pipe,
                client_pipe,
                third_pipe,
                pipe_names,
            )
        )
        result["ok"] = True
        return result
    finally:
        _disarm_death_traces(pipe_names)
        stop_game_processes(process_ids)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--instance-prefix",
        default="",
        help="Unique launcher instance prefix (generated by default).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT,
    )
    parser.add_argument(
        "--game-dir",
        type=Path,
        default=None,
        help="Retail game directory override for isolated worktrees.",
    )
    parser.add_argument("--host-port", type=int, default=None)
    parser.add_argument("--client-port", type=int, default=None)
    parser.add_argument("--third-port", type=int, default=None)
    args = parser.parse_args()

    instance_prefix = args.instance_prefix or _default_instance_prefix()
    result: dict[str, object] = {"ok": False}
    try:
        result = run_live_verification(
            instance_prefix=instance_prefix,
            ports=_resolve_udp_ports(
                args.host_port,
                args.client_port,
                args.third_port,
            ),
            game_directory=args.game_dir,
        )
        exit_code = 0
    except Exception as exc:  # noqa: BLE001 - emit full verifier failure.
        result["error"] = str(exc)
        result["instance_prefix"] = instance_prefix
        exit_code = 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
