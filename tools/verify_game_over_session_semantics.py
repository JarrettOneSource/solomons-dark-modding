#!/usr/bin/env python3
"""Verify stock Game Over semantics for solo and terminal multiplayer deaths."""

from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import math
import ntpath
import os
import select
import shutil
import subprocess
import tempfile
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageStat

from multiplayer_defense_behavior_harness import invoke_native_magic_hit_trial
from multiplayer_frame_capture import capture_game_backbuffer
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    HOST_ID,
    HOST_NAME,
    ROOT,
    THIRD_ID,
    THIRD_NAME,
    VerifyFailure,
    activate_native_ui_action,
    extract_json,
    game_process_ids,
    launch_pair,
    lua,
    parse_key_values,
    path_for_powershell,
    select_available_windows_udp_ports,
    start_testrun,
    wait_for_remote,
    wait_for_scene,
)
from verify_multiplayer_death_spectator_respawn import (
    death_presentation_state_matches,
    query_spectator_state,
    spectator_state_matches,
)
from verify_player_health_death_sync import set_local_player_vitals


ACCEPTANCE_MOD_ID = "sample.lua.ui_sandbox_lab"
BOT_PLAY_MOD_ID = "bot.brain"
SOLO_PARTICIPANT_ID = 0x2000000000001A01
SOLO_PLAYER_NAME = "Solo Game Over"
OUTPUT = ROOT / "runtime" / "game_over_session_semantics.json"
ARTIFACT_ROOT = ROOT / "runtime" / "game-over-acceptance"
LOADING_BACKGROUND = ROOT / "assets" / "loading" / "Wizards_dire_BG.png"
SOLO_LAUNCHER = ROOT / "scripts" / "Launch-LocalSoloSession.ps1"
CLICK_WINDOW = ROOT / "scripts" / "click_window.py"
VITAL_TOLERANCE = 0.05
GAME_OVER_LAYOUT = ROOT / "config" / "binary-layout.ini"
EXISTING_WIZARD_SAVE_FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "savegames"
    / "fieldbreak25_existing_wizard"
    / "solomondark"
)
CREATE_ELEMENT_IDS = {
    "ether": 0,
    "fire": 1,
    "air": 2,
    "water": 3,
    "earth": 4,
}
CREATE_DISCIPLINE_IDS = {
    "mind": 2,
    "body": 1,
    "arcane": 0,
}


def _acceptance_mod_ids(
    with_bot_play_mod: bool,
) -> tuple[str, ...]:
    if with_bot_play_mod:
        return (ACCEPTANCE_MOD_ID, BOT_PLAY_MOD_ID)
    return (ACCEPTANCE_MOD_ID,)


def _seed_bot_play_settings(
    instances: list[str],
) -> dict[str, str]:
    payload = {
        "schemaVersion": 1,
        "values": {
            "play_for_me": False,
            "play_for_me_behavior": "skirmisher",
            "roster": [],
        },
    }
    seeded: dict[str, str] = {}
    for instance in instances:
        path = (
            ROOT
            / "runtime"
            / "instances"
            / instance.lower()
            / "stage"
            / ".sdmod"
            / "mod-settings"
            / f"{BOT_PLAY_MOD_ID}.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        seeded[instance] = str(path)
    return seeded


def _assert_bot_play_mod_active(pipe_name: str) -> dict[str, str]:
    values = parse_key_values(
        lua(
            pipe_name,
            f"""-- sdmod-exec-target: {BOT_PLAY_MOD_ID}
local debug = rawget(_G, "bot_brain_debug")
print("loaded=" .. tostring(debug ~= nil))
print("play_for_me=" ..
  tostring(debug and debug.play_for_me or false))
print("local_active=" ..
  tostring(debug and debug.local_player and
    debug.local_player.active or false))
""",
            timeout=8.0,
        )
    )
    if (
        values.get("loaded") != "true"
        or values.get("play_for_me") != "false"
        or values.get("local_active") != "false"
    ):
        raise VerifyFailure(
            f"Bot Play For Me mod was not active and inert: {values}"
        )
    return values


def _read_layout_address(section: str, key: str) -> int:
    parser = configparser.ConfigParser(strict=False)
    if not parser.read(GAME_OVER_LAYOUT, encoding="utf-8"):
        raise RuntimeError(
            f"Unable to read binary layout: {GAME_OVER_LAYOUT}"
        )
    try:
        return int(parser[section][key], 0)
    except (KeyError, ValueError) as exc:
        raise RuntimeError(
            f"Invalid binary layout entry: [{section}] {key}"
        ) from exc


GAME_OVER_APPLICATION_GLOBAL = _read_layout_address(
    "game_over.native",
    "application_global",
)
GAME_OVER_VTABLE = _read_layout_address(
    "game_over.native",
    "vtable",
)
GAME_OVER_BONEYARD_MODE = _read_layout_address(
    "game_over.native",
    "boneyard_mode",
)
GAME_OVER_APPLICATION_CPU_MANAGER = _read_layout_address(
    "game_over.native",
    "application_cpu_manager",
)
GAME_OVER_CPU_MANAGER_COUNT = _read_layout_address(
    "game_over.native",
    "cpu_manager_count",
)
GAME_OVER_CPU_MANAGER_ITEMS = _read_layout_address(
    "game_over.native",
    "cpu_manager_items",
)
GAME_OVER_SURFACE_CLOSED = _read_layout_address(
    "game_over.native",
    "surface_closed",
)
GAME_OVER_BACKGROUND_ALPHA = _read_layout_address(
    "game_over.native",
    "background_alpha",
)
GAME_OVER_TITLE_ALPHA = _read_layout_address(
    "game_over.native",
    "title_alpha",
)
GAME_OVER_CLICK_ALPHA = _read_layout_address(
    "game_over.native",
    "click_alpha",
)
GAME_OVER_CLOSE_ALPHA = _read_layout_address(
    "game_over.native",
    "close_alpha",
)
GAME_OVER_TICK_COUNT = _read_layout_address(
    "game_over.native",
    "tick_count",
)


SESSION_STATE_PROBE = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local multiplayer = assert(sd.runtime.get_multiplayer_state())
local spectator = assert(multiplayer.death_spectator)
local terminal = multiplayer.game_over or {}
local loading = multiplayer.run_loading_barrier or {}
local player = sd.player.get_state()
local scene = sd.world.get_scene()
local ui = sd.ui and sd.ui.get_snapshot and sd.ui.get_snapshot() or nil
local player_actor = player and tonumber(player.actor_address) or 0
local native_death_drive = player_actor ~= 0 and
  (sd.debug.read_u8(player_actor +
    sd.debug.layout_offset("actor_animation_drive_state_byte")) or 0) or 0
local native_death_tick = player_actor ~= 0 and
  (sd.debug.read_u32(player_actor +
    sd.debug.layout_offset("actor_animation_move_duration_ticks")) or 0) or 0
local local_row = nil
local create_owner = 0
local create_action_ids = {}
local connected_run_count = 0
local alive_run_count = 0
local remote_peer_count = 0
local run_nonce = 0
for _, participant in ipairs(multiplayer.participants or {}) do
  if participant.kind == "LocalHuman" then
    local_row = participant
    run_nonce = tonumber(participant.run_nonce) or 0
  elseif participant.transport_connected then
    remote_peer_count = remote_peer_count + 1
  end
end
for _, participant in ipairs(multiplayer.participants or {}) do
  if participant.ready and participant.transport_connected and
      participant.runtime_valid and participant.in_run and
      run_nonce ~= 0 and participant.run_nonce == run_nonce then
    connected_run_count = connected_run_count + 1
    local life_current = tonumber(participant.life_current)
    local life_max = tonumber(participant.life_max)
    if life_current ~= nil and life_max ~= nil and
        life_max > 0 and life_current > 0 then
      alive_run_count = alive_run_count + 1
    end
  end
end
if ui ~= nil and ui.surface_id == "create" then
  for _, element in ipairs(ui.elements or {}) do
    local surface_id = tostring(
      element.surface_root_id or element.surface_id or "")
    if surface_id == "create" then
      if create_owner == 0 then
        create_owner = tonumber(element.surface_object_ptr) or 0
      end
      local action_id = tostring(element.action_id or "")
      if action_id ~= "" then
        table.insert(create_action_ids, action_id)
      end
    end
  end
end
table.sort(create_action_ids)
emit("scene", scene and (scene.name or scene.kind) or "")
emit("surface", ui and ui.surface_id or "")
emit("create_owner", create_owner)
emit("create_action_ids", table.concat(create_action_ids, ","))
if create_owner ~= 0 then
  emit("create_element_enabled",
    sd.debug.read_u8(create_owner + 0x18C))
  emit("create_element_selected",
    sd.debug.read_u32(create_owner + 0x1A4))
  emit("create_discipline_enabled",
    sd.debug.read_u8(create_owner + 0x228))
  emit("create_discipline_selected",
    sd.debug.read_u32(create_owner + 0x22C))
end
emit("participant_count", multiplayer.participant_count or 0)
emit("connected_run_count", connected_run_count)
emit("alive_run_count", alive_run_count)
emit("remote_peer_count", remote_peer_count)
emit("run_nonce", run_nonce)
emit("local_in_run", local_row and local_row.in_run or false)
emit("local_loadout_generation",
  local_row and local_row.loadout_pick_generation or 0)
emit("local_loadout_state",
  local_row and local_row.loadout_pick_state or "")
emit("session_state", multiplayer.session_state or "")
emit("run_end_pending_lobby_return",
  multiplayer.run_end_pending_lobby_return or false)
emit("local_life_current", player and player.hp or
  (local_row and local_row.life_current or 0))
emit("local_life_max", player and player.max_hp or
  (local_row and local_row.life_max or 0))
emit("local_native_death_drive", native_death_drive)
emit("local_native_death_tick", native_death_tick)
emit("spectator_active", spectator.active)
emit("spectator_phase", spectator.phase)
emit("spectator_target_participant_id", spectator.target_participant_id)
emit("game_over_command_epoch", terminal.command_epoch or 0)
emit("game_over_accepted_epoch", terminal.accepted_epoch or 0)
emit("game_over_run_nonce", terminal.run_nonce or 0)
emit("game_over_authority_participant_id",
  terminal.authority_participant_id or 0)
emit("game_over_pending_dispatch", terminal.pending_dispatch or false)
emit("game_over_dispatch_count", terminal.dispatch_count or 0)
emit("loading_active", loading.active or false)
emit("loading_local_mutual_visibility",
  loading.local_mutual_visibility or false)
emit("loading_released", loading.released or false)
emit("loading_timed_out", loading.timed_out or false)
emit("loading_run_nonce", loading.run_nonce or 0)
emit("loading_local_ack_nonce", loading.local_ack_nonce or 0)
emit("loading_release_nonce", loading.release_nonce or 0)
emit("loading_deadline_remaining_ms",
  loading.deadline_remaining_ms or 0)
emit("loading_visible_participant_count",
  loading.visible_participant_count or 0)
emit("loading_expected_participant_count",
  loading.expected_participant_count or 0)
emit("loading_ready_participant_count",
  loading.ready_participant_count or 0)
emit("loading_visible_participant_set_hash",
  loading.visible_participant_set_hash or 0)
emit("loading_expected_participant_set_hash",
  loading.expected_participant_set_hash or 0)
emit("loading_release_reason", loading.release_reason or "")
"""

DEATH_RESET_STATE_PROBE = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local function profile_fingerprint(profile)
  if profile == nil then
    return ""
  end
  local choices = {}
  for _, value in ipairs(profile.appearance_choice_ids or {}) do
    table.insert(choices, tostring(value))
  end
  return table.concat({
    tostring(profile.element_id or -1),
    tostring(profile.discipline_id or -1),
    table.concat(choices, ","),
  }, ":")
end
local function render_selector(state)
  if state == nil then
    return ""
  end
  return table.concat({
    tostring(state.render_variant_primary or 0),
    tostring(state.render_variant_secondary or 0),
    tostring(state.render_weapon_type or 0),
    tostring(state.render_selection_byte or 0),
    tostring(state.render_variant_tertiary or 0),
  }, ",")
end
local multiplayer = assert(sd.runtime.get_multiplayer_state())
local scene = sd.world.get_scene()
local player = sd.player.get_state()
local local_row = nil
local remote_row = nil
for _, participant in ipairs(multiplayer.participants or {}) do
  if participant.kind == "LocalHuman" then
    local_row = participant
  elseif participant.transport_connected then
    remote_row = participant
  end
end
local remote_bot = nil
if remote_row ~= nil then
  for _, bot in ipairs(sd.bots.get_participants() or {}) do
    if bot.id == remote_row.participant_id then
      remote_bot = bot
      break
    end
  end
end
emit("scene", scene and (scene.name or scene.kind) or "")
emit("session_state", multiplayer.session_state or "")
emit("participant_count", multiplayer.participant_count or 0)
emit("local.participant_id", local_row and local_row.participant_id or 0)
emit("local.runtime.in_run", local_row and local_row.in_run or false)
emit("local.runtime.run_nonce", local_row and local_row.run_nonce or 0)
emit("local.runtime.life_current",
  local_row and local_row.life_current or 0)
emit("local.runtime.life_max", local_row and local_row.life_max or 0)
emit("local.runtime.presentation_flags",
  local_row and local_row.presentation_flags or 0)
emit("local.runtime.death_presentation_tick",
  local_row and local_row.death_presentation_tick or 0)
emit("local.runtime.persistent_status_flags",
  local_row and local_row.persistent_status_flags or 0)
emit("local.runtime.transient_status_flags",
  local_row and local_row.transient_status_flags or 0)
emit("local.runtime.poison_remaining_ticks",
  local_row and local_row.poison_remaining_ticks or 0)
emit("local.runtime.damage_x4_remaining_ticks",
  local_row and local_row.damage_x4_remaining_ticks or 0)
emit("local.native.life_current", player and player.hp or 0)
emit("local.native.life_max", player and player.max_hp or 0)
emit("local.native.persistent_status_flags",
  player and player.persistent_status_flags or 0)
emit("local.native.transient_status_flags",
  player and player.transient_status_flags or 0)
emit("local.native.poison_remaining_ticks",
  player and player.poison_remaining_ticks or 0)
emit("local.native.render_selector", render_selector(player))
emit("remote.participant_id",
  remote_row and remote_row.participant_id or 0)
emit("remote.runtime.in_run", remote_row and remote_row.in_run or false)
emit("remote.runtime.run_nonce", remote_row and remote_row.run_nonce or 0)
emit("remote.runtime.life_current",
  remote_row and remote_row.life_current or 0)
emit("remote.runtime.life_max", remote_row and remote_row.life_max or 0)
emit("remote.runtime.presentation_flags",
  remote_row and remote_row.presentation_flags or 0)
emit("remote.runtime.death_presentation_tick",
  remote_row and remote_row.death_presentation_tick or 0)
emit("remote.runtime.persistent_status_flags",
  remote_row and remote_row.persistent_status_flags or 0)
emit("remote.runtime.transient_status_flags",
  remote_row and remote_row.transient_status_flags or 0)
emit("remote.runtime.poison_remaining_ticks",
  remote_row and remote_row.poison_remaining_ticks or 0)
emit("remote.runtime.damage_x4_remaining_ticks",
  remote_row and remote_row.damage_x4_remaining_ticks or 0)
emit("remote.native.materialized",
  remote_bot and remote_bot.entity_materialized or false)
emit("remote.native.actor", remote_bot and remote_bot.actor_address or 0)
emit("remote.native.life_current", remote_bot and remote_bot.hp or 0)
emit("remote.native.life_max", remote_bot and remote_bot.max_hp or 0)
emit("remote.native.anim_drive_state",
  remote_bot and remote_bot.anim_drive_state or 0)
emit("remote.native.replicated_persistent_status_flags",
  remote_bot and remote_bot.replicated_persistent_status_flags or 0)
emit("remote.native.native_persistent_status_flags",
  remote_bot and remote_bot.native_persistent_status_flags or 0)
emit("remote.native.replicated_transient_status_flags",
  remote_bot and remote_bot.replicated_transient_status_flags or 0)
emit("remote.native.native_transient_status_flags",
  remote_bot and remote_bot.native_transient_status_flags or 0)
emit("remote.native.replicated_poison_remaining_ticks",
  remote_bot and remote_bot.replicated_poison_remaining_ticks or 0)
emit("remote.native.native_poison_remaining_ticks",
  remote_bot and remote_bot.native_poison_remaining_ticks or 0)
emit("remote.native.profile",
  remote_bot and profile_fingerprint(remote_bot.profile) or "")
emit("remote.native.render_selector", render_selector(remote_bot))
emit("remote.native.primary_visual_type",
  remote_bot and remote_bot.primary_visual_lane and
    remote_bot.primary_visual_lane.current_object_type_id or 0)
emit("remote.native.secondary_visual_type",
  remote_bot and remote_bot.secondary_visual_lane and
    remote_bot.secondary_visual_lane.current_object_type_id or 0)
emit("remote.native.attachment_visual_type",
  remote_bot and remote_bot.attachment_visual_lane and
    remote_bot.attachment_visual_lane.current_object_type_id or 0)
"""


NATIVE_GAME_OVER_PROBE = f"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local app_slot =
  tonumber(sd.debug.resolve_game_address(
    {GAME_OVER_APPLICATION_GLOBAL})) or 0
local game_over_vtable =
  tonumber(sd.debug.resolve_game_address({GAME_OVER_VTABLE})) or 0
local boneyard_mode_address =
  tonumber(sd.debug.resolve_game_address({GAME_OVER_BONEYARD_MODE})) or 0
local app =
  app_slot ~= 0 and (tonumber(sd.debug.read_ptr(app_slot)) or 0) or 0
local found = false
emit("boneyard_mode",
  boneyard_mode_address ~= 0 and
    (tonumber(sd.debug.read_u8(boneyard_mode_address)) or 0) or -1)
if app ~= 0 then
  local manager = tonumber(sd.debug.read_ptr(
    app + {GAME_OVER_APPLICATION_CPU_MANAGER:#x})) or 0
  if manager ~= 0 then
    local count = tonumber(sd.debug.read_i32(
      manager + {GAME_OVER_CPU_MANAGER_COUNT:#x})) or 0
    local items = tonumber(sd.debug.read_ptr(
      manager + {GAME_OVER_CPU_MANAGER_ITEMS:#x})) or 0
    if items ~= 0 and count > 0 then
      for index = 0, math.min(count - 1, 31) do
        local object = tonumber(sd.debug.read_ptr(items + index * 4)) or 0
        local vtable =
          object ~= 0 and (tonumber(sd.debug.read_ptr(object)) or 0) or 0
        if vtable == game_over_vtable then
          found = true
          emit("game_over_closed",
            tonumber(sd.debug.read_u8(
              object + {GAME_OVER_SURFACE_CLOSED:#x})) or -1)
          emit("game_over_background_alpha",
            tonumber(sd.debug.read_float(
              object + {GAME_OVER_BACKGROUND_ALPHA:#x})) or -1)
          emit("game_over_title_alpha",
            tonumber(sd.debug.read_float(
              object + {GAME_OVER_TITLE_ALPHA:#x})) or -1)
          emit("game_over_click_alpha",
            tonumber(sd.debug.read_float(
              object + {GAME_OVER_CLICK_ALPHA:#x})) or -1)
          emit("game_over_close_alpha",
            tonumber(sd.debug.read_float(
              object + {GAME_OVER_CLOSE_ALPHA:#x})) or -1)
          emit("game_over_tick_count",
            tonumber(sd.debug.read_i32(
              object + {GAME_OVER_TICK_COUNT:#x})) or -1)
          break
        end
      end
    end
  end
end
emit("game_over_found", found)
"""


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


def _default_instance_prefix() -> str:
    return f"go-{os.getpid():x}-{time.time_ns() & 0xFFFF:04x}"


def _launcher_instance_prefix(
    evidence_prefix: str,
    role_group: str,
) -> str:
    if role_group not in {"s", "m", "t"}:
        raise ValueError(f"unsupported launcher role group: {role_group}")
    digest = hashlib.sha256(
        evidence_prefix.encode("utf-8")
    ).hexdigest()[:8]
    if evidence_prefix.startswith("bply"):
        return f"bply-{digest}{role_group}"
    return f"g{digest}{role_group}"


def _resolve_udp_ports(explicit: list[int | None]) -> list[int]:
    if all(port is None for port in explicit):
        return select_available_windows_udp_ports(7)
    if any(port is None for port in explicit):
        raise ValueError("all seven ports must be provided together")
    ports = [int(port) for port in explicit if port is not None]
    if any(port < 1 or port > 0xFFFF for port in ports):
        raise ValueError("explicit UDP ports must be between 1 and 65535")
    if len(set(ports)) != 7:
        raise ValueError("explicit UDP ports must be distinct")
    return ports


def _resolve_death_reset_ports(
    host_port: int | None,
    client_port: int | None,
) -> list[int]:
    if host_port is None or client_port is None:
        raise ValueError("both death-reset ports must be provided")
    ports = [int(host_port), int(client_port)]
    if any(port < 1 or port > 0xFFFF for port in ports):
        raise ValueError("death-reset ports must be between 1 and 65535")
    if len(set(ports)) != 2:
        raise ValueError("death-reset ports must be distinct")
    return ports


def remote_appearance_fingerprint(
    values: Mapping[str, str],
) -> tuple[str, ...]:
    return (
        values.get("remote.native.profile", ""),
        values.get("remote.native.render_selector", ""),
        values.get("remote.native.primary_visual_type", ""),
        values.get("remote.native.secondary_visual_type", ""),
        values.get("remote.native.attachment_visual_type", ""),
    )


def _full_vitality_matches(
    values: Mapping[str, str],
    current_key: str,
    maximum_key: str,
) -> bool:
    current = _number(values, current_key)
    maximum = _number(values, maximum_key)
    return (
        math.isfinite(current)
        and math.isfinite(maximum)
        and maximum > VITAL_TOLERANCE
        and abs(current - maximum) <= VITAL_TOLERANCE
    )


def run_boundary_vitality_reset_matches(
    values: Mapping[str, str],
    *,
    expected_remote_appearance: tuple[str, ...],
    expected_scene: str,
) -> bool:
    zero_keys = (
        "local.runtime.death_presentation_tick",
        "local.runtime.poison_remaining_ticks",
        "local.runtime.damage_x4_remaining_ticks",
        "local.native.poison_remaining_ticks",
        "remote.runtime.death_presentation_tick",
        "remote.runtime.poison_remaining_ticks",
        "remote.runtime.damage_x4_remaining_ticks",
        "remote.native.replicated_poison_remaining_ticks",
        "remote.native.native_poison_remaining_ticks",
    )
    death_presentation_mask = 1 << 6
    persistent_combat_mask = 0x07
    transient_combat_mask = 0x1F
    presentation_keys = (
        "local.runtime.presentation_flags",
        "remote.runtime.presentation_flags",
    )
    persistent_status_keys = (
        "local.runtime.persistent_status_flags",
        "local.native.persistent_status_flags",
        "remote.runtime.persistent_status_flags",
        "remote.native.replicated_persistent_status_flags",
        "remote.native.native_persistent_status_flags",
    )
    transient_status_keys = (
        "local.runtime.transient_status_flags",
        "local.native.transient_status_flags",
        "remote.runtime.transient_status_flags",
        "remote.native.replicated_transient_status_flags",
        "remote.native.native_transient_status_flags",
    )
    expected_session = (
        "in-hub" if expected_scene == "hub" else "in-boneyard"
    )
    expected_in_run = expected_scene != "hub"
    return (
        values.get("scene") == expected_scene
        and values.get("session_state") == expected_session
        and _integer(values, "participant_count") == 2
        and values.get("local.runtime.in_run")
        == str(expected_in_run).lower()
        and values.get("remote.runtime.in_run")
        == str(expected_in_run).lower()
        and _integer(values, "local.participant_id") > 0
        and _integer(values, "remote.participant_id") > 0
        and _full_vitality_matches(
            values,
            "local.runtime.life_current",
            "local.runtime.life_max",
        )
        and _full_vitality_matches(
            values,
            "local.native.life_current",
            "local.native.life_max",
        )
        and _full_vitality_matches(
            values,
            "remote.runtime.life_current",
            "remote.runtime.life_max",
        )
        and _full_vitality_matches(
            values,
            "remote.native.life_current",
            "remote.native.life_max",
        )
        and values.get("remote.native.materialized") == "true"
        and _integer(values, "remote.native.actor") > 0
        and all(_integer(values, key) == 0 for key in zero_keys)
        and all(
            _integer(values, key) & death_presentation_mask == 0
            for key in presentation_keys
        )
        and all(
            _integer(values, key) & persistent_combat_mask == 0
            for key in persistent_status_keys
        )
        and all(
            _integer(values, key) & transient_combat_mask == 0
            for key in transient_status_keys
        )
        and remote_appearance_fingerprint(values)
        == expected_remote_appearance
    )


def local_hub_vitality_reset_without_remote_matches(
    values: Mapping[str, str],
) -> bool:
    local_zero_keys = (
        "local.runtime.death_presentation_tick",
        "local.runtime.poison_remaining_ticks",
        "local.runtime.damage_x4_remaining_ticks",
        "local.native.poison_remaining_ticks",
    )
    death_presentation_mask = 1 << 6
    persistent_combat_mask = 0x07
    transient_combat_mask = 0x1F
    return (
        values.get("scene") == "hub"
        and values.get("session_state") == "in-hub"
        and _integer(values, "participant_count") == 2
        and values.get("local.runtime.in_run") == "false"
        and _integer(values, "local.participant_id") > 0
        and _full_vitality_matches(
            values,
            "local.runtime.life_current",
            "local.runtime.life_max",
        )
        and _full_vitality_matches(
            values,
            "local.native.life_current",
            "local.native.life_max",
        )
        and all(_integer(values, key) == 0 for key in local_zero_keys)
        and _integer(values, "local.runtime.presentation_flags")
        & death_presentation_mask
        == 0
        and _integer(values, "local.runtime.persistent_status_flags")
        & persistent_combat_mask
        == 0
        and _integer(values, "local.native.persistent_status_flags")
        & persistent_combat_mask
        == 0
        and _integer(values, "local.runtime.transient_status_flags")
        & transient_combat_mask
        == 0
        and _integer(values, "local.native.transient_status_flags")
        & transient_combat_mask
        == 0
        and not values_have_materialized_remote(values)
    )


def _windows_path_equal(left: str, right: str) -> bool:
    return ntpath.normcase(ntpath.normpath(left)) == ntpath.normcase(
        ntpath.normpath(right)
    )


def _path_for_local_python(path: str) -> Path:
    if os.name == "nt":
        return Path(path)
    completed = subprocess.run(
        ["wslpath", "-u", path],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=5.0,
        check=False,
    )
    converted = completed.stdout.strip()
    if completed.returncode != 0 or not converted:
        raise VerifyFailure(
            f"could not convert Windows path for local inspection: "
            f"{path}: {completed.stdout}"
        )
    return Path(converted)


def _powershell_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _query_process_executable(process_id: int) -> str | None:
    command = (
        f'$p=Get-CimInstance Win32_Process -Filter "ProcessId = {process_id}" '
        "-ErrorAction SilentlyContinue; "
        'if ($null -eq $p) { [Console]::Write("null"); exit 0 }; '
        "[Console]::Write(($p.ExecutablePath | ConvertTo-Json -Compress))"
    )
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10.0,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise VerifyFailure(
            f"could not resolve executable ownership for PID {process_id}: {detail}"
        )
    raw = completed.stdout.strip().lstrip("\ufeff")
    if raw == "null":
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise VerifyFailure(
            f"invalid executable ownership response for PID {process_id}: {raw!r}"
        ) from exc
    if not isinstance(value, str) or not value:
        raise VerifyFailure(
            f"missing executable ownership response for PID {process_id}: {value!r}"
        )
    return value


def validate_owned_processes(
    expected_paths: Mapping[int, str],
) -> dict[int, str]:
    validated: dict[int, str] = {}
    for process_id, expected_path in expected_paths.items():
        actual_path = _query_process_executable(process_id)
        if actual_path is None:
            raise VerifyFailure(
                f"owned game PID {process_id} exited before validation"
            )
        if not _windows_path_equal(actual_path, expected_path):
            raise VerifyFailure(
                "game process ownership mismatch: "
                f"pid={process_id} expected={expected_path!r} "
                f"actual={actual_path!r}"
            )
        validated[process_id] = actual_path
    return validated


def stop_owned_processes(expected_paths: Mapping[int, str]) -> None:
    """Stop only PIDs whose live executable still matches their instance stage."""

    for process_id, expected_path in expected_paths.items():
        command = (
            f'$p=Get-CimInstance Win32_Process -Filter "ProcessId = {process_id}" '
            "-ErrorAction SilentlyContinue; "
            "if ($null -eq $p) { exit 0 }; "
            f"$expected={_powershell_literal(expected_path)}; "
            "if (-not [string]::Equals("
            "$p.ExecutablePath,$expected,"
            "[System.StringComparison]::OrdinalIgnoreCase)) { "
            'throw "Executable ownership mismatch for exact PID." }; '
            f"Stop-Process -Id {process_id} -Force"
        )
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                command,
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10.0,
            check=False,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise VerifyFailure(
                f"exact cleanup failed for PID {process_id}: {detail}"
            )


def _expected_instance_executable(
    runtime_root: str,
    instance: str,
) -> str:
    return ntpath.join(
        runtime_root,
        "instances",
        instance.lower(),
        "stage",
        "SolomonDark.exe",
    )


def _read_process_ledger(path: Path) -> list[int]:
    if not path.is_file():
        return []
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    return game_process_ids(document) if isinstance(document, dict) else []


def launch_solo(
    *,
    instance: str,
    local_port: int,
    unused_remote_port: int,
    game_directory: Path,
    launcher_path: Path | None = None,
    test_blank_boneyard: bool = False,
    test_wave_override: Path | None = None,
    quick_start: bool = True,
    fresh_install: bool = True,
    exact_mod_ids: tuple[str, ...] = (ACCEPTANCE_MOD_ID,),
) -> dict[str, object]:
    ledger = ROOT / "runtime" / f".game-over-solo-{os.getpid()}-{time.time_ns()}.json"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    args = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SOLO_LAUNCHER.relative_to(ROOT)).replace("/", "\\"),
        "-Instance",
        instance,
        "-Preset",
        "map_create_fire_mind_hub",
        "-LocalPort",
        str(local_port),
        "-UnusedRemotePort",
        str(unused_remote_port),
        "-ParticipantId",
        f"0x{SOLO_PARTICIPANT_ID:X}",
        "-PlayerName",
        SOLO_PLAYER_NAME,
        "-GameDirectory",
        path_for_powershell(game_directory),
        "-RuntimeRoot",
        path_for_powershell(ROOT / "runtime"),
        "-ExactModIds",
        ",".join(exact_mod_ids),
        "-ProcessIdOutputPath",
        path_for_powershell(ledger),
    ]
    if fresh_install:
        args.append("-FreshInstall")
    if quick_start:
        args.append("-QuickStart")
    if test_blank_boneyard:
        args.append("-TestBlankBoneyard")
    if test_wave_override is not None:
        args.extend(
            [
                "-TestWaveOverride",
                path_for_powershell(test_wave_override),
            ]
        )
    if launcher_path is not None:
        args.extend(
            [
                "-LauncherPath",
                path_for_powershell(launcher_path),
            ]
        )
    process = subprocess.Popen(
        args,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    assert process.stdout is not None
    parsed: dict[str, object] | None = None
    output = ""
    try:
        deadline = time.monotonic() + 90.0
        while time.monotonic() < deadline:
            ready, _, _ = select.select([process.stdout], [], [], 0.1)
            if ready:
                line = process.stdout.readline()
                if line:
                    output += line
                    parsed = extract_json(output)
                    if parsed is not None:
                        return parsed
                elif process.poll() is not None:
                    break
            if process.poll() is not None:
                output += process.stdout.read()
                parsed = extract_json(output)
                if parsed is not None:
                    return parsed
                break
        raise VerifyFailure(f"solo launcher did not return JSON:\n{output}")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                process.kill()
        if parsed is None:
            runtime_root = path_for_powershell(ROOT / "runtime")
            expected_path = _expected_instance_executable(
                runtime_root,
                instance,
            )
            for process_id in _read_process_ledger(ledger):
                stop_owned_processes({process_id: expected_path})
        ledger.unlink(missing_ok=True)


def query_session_state(pipe_name: str) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, SESSION_STATE_PROBE, timeout=8.0))


def query_death_reset_state(pipe_name: str) -> dict[str, str]:
    return parse_key_values(
        lua(pipe_name, DEATH_RESET_STATE_PROBE, timeout=8.0)
    )


def query_native_game_over_state(pipe_name: str) -> dict[str, str]:
    return parse_key_values(
        lua(pipe_name, NATIVE_GAME_OVER_PROBE, timeout=8.0)
    )


def _wait_for_death_reset_state(
    pipe_name: str,
    *,
    expected_scene: str,
    timeout: float = 20.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    last_error = ""
    while time.monotonic() < deadline:
        try:
            last = query_death_reset_state(pipe_name)
            last_error = ""
            if (
                last.get("scene") == expected_scene
                and _integer(last, "participant_count") == 2
                and values_have_materialized_remote(last)
            ):
                return last
        except Exception as exc:  # noqa: BLE001 - preserve live evidence.
            last_error = str(exc)
        time.sleep(0.1)
    suffix = f" last_error={last_error}" if last_error else ""
    raise VerifyFailure(
        f"timed out waiting for {expected_scene} vitality snapshot on "
        f"{pipe_name}; last={last}.{suffix}"
    )


def values_have_materialized_remote(values: Mapping[str, str]) -> bool:
    return (
        values.get("remote.native.materialized") == "true"
        and _integer(values, "remote.native.actor") > 0
        and _integer(values, "remote.participant_id") > 0
    )


def _wait_for_unmaterialized_remote_in_hub(
    pipe_name: str,
    *,
    timeout: float = 15.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = query_death_reset_state(pipe_name)
        if (
            last.get("scene") == "hub"
            and last.get("session_state") == "in-hub"
            and _integer(last, "participant_count") == 2
            and not values_have_materialized_remote(last)
        ):
            return last
        time.sleep(0.1)
    raise VerifyFailure(
        "host did not remain playable in the hub without materializing the "
        f"still-picking client: {last}"
    )


def _wait_for_state(
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
            last = query_session_state(pipe_name)
            last_error = ""
            if predicate(last):
                return last
        except Exception as exc:  # noqa: BLE001 - retain live failure evidence.
            last_error = str(exc)
        time.sleep(0.05)
    error_suffix = f" last_error={last_error}" if last_error else ""
    raise VerifyFailure(
        f"timed out waiting for {description} on {pipe_name}; "
        f"last={last}.{error_suffix}"
    )


def _wait_for_spectator_state(
    pipe_name: str,
    predicate,
    *,
    timeout: float,
    description: str,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = query_spectator_state(pipe_name)
        if predicate(last):
            return last
        time.sleep(0.05)
    raise VerifyFailure(
        f"timed out waiting for {description} on {pipe_name}; last={last}"
    )


def _start_testrun_when_ready(
    host_pipe: str,
    *,
    timeout: float = 25.0,
) -> None:
    deadline = time.monotonic() + timeout
    last_error = ""
    hub_stable_since: float | None = None
    while time.monotonic() < deadline:
        try:
            state = query_session_state(host_pipe)
            last_error = ""
            if (
                state.get("scene") == "hub"
                and state.get("session_state") == "in-hub"
            ):
                now = time.monotonic()
                if hub_stable_since is None:
                    hub_stable_since = now
                elif now - hub_stable_since >= 3.0:
                    break
            else:
                hub_stable_since = None
        except Exception as exc:  # noqa: BLE001 - retain last live error.
            last_error = str(exc)
            hub_stable_since = None
        time.sleep(0.1)
    else:
        raise VerifyFailure(
            "host never remained in the shared hub for 3 seconds before "
            f"run entry: {last_error}"
        )

    while time.monotonic() < deadline:
        try:
            start_testrun(host_pipe)
            return
        except VerifyFailure as exc:
            last_error = str(exc)
        time.sleep(0.25)
    raise VerifyFailure(
        "testrun request never reached stable scene identity: "
        f"{last_error}"
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


def solo_terminal_state_matches(values: Mapping[str, str]) -> bool:
    hp = _number(values, "local_life_current")
    return (
        values.get("scene") == "testrun"
        and _integer(values, "participant_count") == 1
        and _integer(values, "remote_peer_count") == 0
        and values.get("spectator_active") == "false"
        and values.get("spectator_phase") == "Inactive"
        and math.isfinite(hp)
        and hp <= VITAL_TOLERANCE
    )


def terminal_game_over_state_matches(
    values: Mapping[str, str],
) -> bool:
    command_epoch = _integer(values, "game_over_command_epoch")
    return (
        command_epoch > 0
        and _integer(values, "game_over_accepted_epoch") == command_epoch
        and _integer(values, "game_over_run_nonce") > 0
        and _integer(values, "game_over_authority_participant_id") > 0
        and values.get("game_over_pending_dispatch") == "false"
        and _integer(values, "game_over_dispatch_count") == 1
        and values.get("spectator_active") == "false"
        and values.get("spectator_phase") == "Inactive"
    )


def native_boneyard_game_over_state_matches(
    values: Mapping[str, str],
) -> bool:
    return (
        values.get("game_over_found") == "true"
        and _integer(values, "boneyard_mode") == 1
        and _integer(values, "game_over_closed") == 0
        and _integer(values, "game_over_tick_count") >= 600
        and _number(values, "game_over_title_alpha") >= 0.99
        and _number(values, "game_over_click_alpha") >= 0.99
        and _number(values, "game_over_close_alpha") <= 0.01
    )


def loading_barrier_wait_state_matches(
    values: Mapping[str, str],
    expected_participants: int,
) -> bool:
    expected_hash = values.get(
        "loading_expected_participant_set_hash",
        "0",
    )
    return (
        values.get("session_state") == "in-boneyard"
        and values.get("loading_active") == "true"
        and values.get("loading_released") == "false"
        and _integer(
            values,
            "loading_expected_participant_count",
        )
        == expected_participants
        and expected_hash not in ("", "0")
    )


def loading_barrier_released_state_matches(
    values: Mapping[str, str],
    expected_participants: int,
    *,
    expected_reason: str,
) -> bool:
    run_nonce = _integer(values, "run_nonce")
    expected_hash = values.get(
        "loading_expected_participant_set_hash",
        "0",
    )
    return (
        values.get("session_state") == "in-boneyard"
        and values.get("loading_active") == "true"
        and values.get("loading_released") == "true"
        and values.get("loading_release_reason") == expected_reason
        and _integer(values, "loading_run_nonce") == run_nonce
        and _integer(values, "loading_release_nonce") == run_nonce
        and _integer(
            values,
            "loading_expected_participant_count",
        )
        == expected_participants
        and expected_hash not in ("", "0")
    )


def healthy_loading_barrier_state_matches(
    values: Mapping[str, str],
    expected_participants: int,
) -> bool:
    run_nonce = _integer(values, "run_nonce")
    return (
        loading_barrier_released_state_matches(
            values,
            expected_participants,
            expected_reason="all-participants-ready",
        )
        and values.get("loading_local_mutual_visibility") == "true"
        and values.get("loading_timed_out") == "false"
        and _integer(values, "loading_local_ack_nonce") == run_nonce
        and _integer(
            values,
            "loading_visible_participant_count",
        )
        == expected_participants
        and _integer(
            values,
            "loading_ready_participant_count",
        )
        == expected_participants
        and values.get(
            "loading_visible_participant_set_hash"
        )
        == values.get(
            "loading_expected_participant_set_hash"
        )
    )


def classify_loading_boneyard_image(path: Path) -> dict[str, object]:
    """Recognize either supported in-game Loading Boneyard presentation."""

    with Image.open(path) as source:
        image = source.convert("RGB")
    center = _zone_pixels(image, (0.35, 0.42, 0.65, 0.58))
    all_pixels = _zone_pixels(image, (0.0, 0.0, 1.0, 1.0))
    center_light_fraction = sum(
        min(pixel) >= 120 for pixel in center
    ) / float(len(center))
    dark_fraction = sum(
        max(pixel) < 20 for pixel in all_pixels
    ) / float(len(all_pixels))
    legacy_matched = (
        center_light_fraction >= 0.003
        and dark_fraction >= 0.98
    )

    with Image.open(LOADING_BACKGROUND) as background_source:
        background = background_source.convert("RGB").resize(
            image.size,
            Image.Resampling.BILINEAR,
        )
    comparison_height = int(image.height * 0.72)
    difference = ImageChops.difference(
        image.crop((0, 0, image.width, comparison_height)),
        background.crop((0, 0, image.width, comparison_height)),
    )
    background_mean_error = sum(
        ImageStat.Stat(difference).mean
    ) / 3.0
    bar_left = int(round(image.width * 0.20))
    bar_right = int(round(image.width * 0.80))
    bar_y = min(
        image.height - 1,
        int(round(image.height * 0.925)) + 4,
    )
    bar_pixels = [
        image.getpixel((x, bar_y))
        for x in range(bar_left, bar_right)
    ]
    measured_bar_progress = sum(
        red >= 175
        and 110 <= green <= 205
        and blue <= 135
        and red > green
        for red, green, blue in bar_pixels
    ) / float(len(bar_pixels))
    branded_matched = (
        background_mean_error <= 8.0
        and 0.88 <= measured_bar_progress <= 1.0
    )
    return {
        "matched": legacy_matched or branded_matched,
        "width": image.width,
        "height": image.height,
        "center_light_fraction": center_light_fraction,
        "dark_fraction": dark_fraction,
        "legacy_matched": legacy_matched,
        "branded_matched": branded_matched,
        "canonical_background_mean_error": background_mean_error,
        "measured_bar_progress": measured_bar_progress,
    }


def _capture_loading_presentation(
    pipe_name: str,
    output_path: Path,
    expected_participants: int,
    timeout: float,
) -> dict[str, object]:
    state = _wait_for_state(
        pipe_name,
        lambda values: loading_barrier_wait_state_matches(
            values,
            expected_participants,
        ),
        timeout=timeout,
        description=(
            "unreleased mutual-visibility run-loading barrier"
        ),
    )
    capture = capture_game_backbuffer(
        pipe_name,
        output_path,
        minimum_unique_colors=20,
        maximum_dominant_fraction=0.9999,
    )
    classification = classify_loading_boneyard_image(output_path)
    if not classification["matched"]:
        raise VerifyFailure(
            "Loading Boneyard presentation was not visible on "
            f"{pipe_name}: {classification}"
        )
    return {
        "pre_capture_state": state,
        "capture": capture,
        "classification": classification,
        "post_capture_state": query_session_state(pipe_name),
    }


def capture_loading_presentations(
    pipes_by_label: Mapping[str, str],
    artifact_directory: Path,
    *,
    expected_participants: int,
    timeout: float = 30.0,
) -> dict[str, object]:
    artifact_directory.mkdir(parents=True, exist_ok=True)
    futures = {}
    with ThreadPoolExecutor(
        max_workers=len(pipes_by_label)
    ) as executor:
        for label, pipe_name in pipes_by_label.items():
            future = executor.submit(
                _capture_loading_presentation,
                pipe_name,
                artifact_directory
                / f"{label}-loading-boneyard.png",
                expected_participants,
                timeout,
            )
            futures[future] = label

        captures: dict[str, object] = {}
        for future, label in futures.items():
            captures[label] = future.result(
                timeout=timeout + 15.0
            )
    return captures


def _zone_pixels(
    image: Image.Image,
    bounds: tuple[float, float, float, float],
) -> list[tuple[int, int, int]]:
    width, height = image.size
    left, top, right, bottom = bounds
    crop = image.crop(
        (
            int(width * left),
            int(height * top),
            int(width * right),
            int(height * bottom),
        )
    ).convert("RGB")
    channel_bytes = crop.tobytes()
    return list(
        zip(
            channel_bytes[0::3],
            channel_bytes[1::3],
            channel_bytes[2::3],
            strict=True,
        )
    )


def classify_native_game_over_image(path: Path) -> dict[str, object]:
    """Recognize the stock three-line GAME / OVER / CLICK composition."""

    with Image.open(path) as source:
        image = source.convert("RGB")
    if image.width < 640 or image.height < 360:
        raise VerifyFailure(
            f"Game Over frame is too small for acceptance: {image.size}"
        )

    zones = {
        "game": (0.39, 0.21, 0.62, 0.39),
        "over": (0.39, 0.54, 0.62, 0.72),
        "continue": (0.38, 0.90, 0.63, 0.98),
    }
    gold_fractions: dict[str, float] = {}
    for label, bounds in zones.items():
        pixels = _zone_pixels(image, bounds)
        gold_count = sum(
            red >= 170 and green >= 130 and blue <= 130
            for red, green, blue in pixels
        )
        gold_fractions[label] = gold_count / float(len(pixels))

    all_pixels = _zone_pixels(image, (0.0, 0.0, 1.0, 1.0))
    dark_fraction = sum(
        max(pixel) < 20 for pixel in all_pixels
    ) / float(len(all_pixels))
    matched = (
        gold_fractions["game"] >= 0.01
        and gold_fractions["over"] >= 0.01
        and gold_fractions["continue"] >= 0.005
        and dark_fraction >= 0.70
    )
    return {
        "matched": matched,
        "width": image.width,
        "height": image.height,
        "gold_fractions": gold_fractions,
        "dark_fraction": dark_fraction,
    }


def capture_native_game_over(
    pipe_name: str,
    output_path: Path,
    *,
    timeout: float = 10.0,
    allow_boneyard_mode: bool = False,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last_error = ""
    last_classification: dict[str, object] = {}
    last_native_state: dict[str, str] = {}
    while time.monotonic() < deadline:
        try:
            if allow_boneyard_mode:
                last_native_state = query_native_game_over_state(pipe_name)
            capture = capture_game_backbuffer(
                pipe_name,
                output_path,
                minimum_unique_colors=(
                    20 if allow_boneyard_mode else 1000
                ),
                maximum_dominant_fraction=(
                    0.9999 if allow_boneyard_mode else 0.85
                ),
            )
            classification = classify_native_game_over_image(output_path)
            last_classification = classification
            if classification["matched"]:
                return {
                    "capture": capture,
                    "classification": classification,
                    "presentation": "story-title",
                }
            if (
                allow_boneyard_mode
                and native_boneyard_game_over_state_matches(
                    last_native_state
                )
                and classification["dark_fraction"] >= 0.70
                and max(
                    classification["gold_fractions"].values(),
                    default=0.0,
                )
                < 0.005
            ):
                return {
                    "capture": capture,
                    "classification": classification,
                    "native_state": last_native_state,
                    "presentation": "boneyard-fade",
                }
        except Exception as exc:  # noqa: BLE001 - retry through native fade.
            last_error = str(exc)
        time.sleep(0.2)
    raise VerifyFailure(
        "native Game Over presentation did not become visible on "
        f"{pipe_name}; classification={last_classification} "
        f"native_state={last_native_state} "
        f"last_error={last_error}"
    )


def _click_owned_window(
    process_id: int,
    x: float,
    y: float,
) -> str:
    command = subprocess.list2cmdline(
        [
            "py",
            "-3",
            path_for_powershell(CLICK_WINDOW),
            "--pid",
            str(process_id),
            "--relative",
            "--x",
            str(x),
            "--y",
            str(y),
            "--post-delay-ms",
            "150",
            "--hold-ms",
            "90",
            "--button",
            "left",
            "--window-only",
        ]
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=8.0,
        check=False,
    )
    if completed.returncode != 0:
        raise VerifyFailure(
            "exact-PID stock click failed "
            f"for process {process_id} ({completed.returncode}): "
            f"{completed.stdout.strip()}"
        )
    return completed.stdout.strip()


def _drive_stock_click_until(
    pipe_name: str,
    process_id: int,
    x: float,
    y: float,
    predicate,
    *,
    timeout: float,
    description: str,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    next_click_at = 0.0
    last: dict[str, str] = {}
    clicks: list[str] = []
    while time.monotonic() < deadline:
        now = time.monotonic()
        if now >= next_click_at:
            clicks.append(_click_owned_window(process_id, x, y))
            next_click_at = now + 0.5
        last = query_session_state(pipe_name)
        if predicate(last):
            return {
                "process_id": process_id,
                "clicks": clicks,
                "state": last,
            }
        time.sleep(0.05)
    raise VerifyFailure(
        f"stock click did not reach {description} on {pipe_name}; last={last}"
    )


def advance_stock_post_game_over(
    process_ids_by_pipe: Mapping[str, int],
) -> dict[str, object]:
    mortuary = {
        pipe_name: _drive_stock_click_until(
            pipe_name,
            process_id,
            0.5,
            0.5,
            lambda values: values.get("scene") == "memorator",
            timeout=15.0,
            description="native Mortuary",
        )
        for pipe_name, process_id in process_ids_by_pipe.items()
    }

    hall_of_fame = {
        pipe_name: _drive_stock_click_until(
            pipe_name,
            process_id,
            0.5,
            0.5,
            lambda values: values.get("surface") == "hall_of_fame",
            timeout=15.0,
            description="native Hall of Fame",
        )
        for pipe_name, process_id in process_ids_by_pipe.items()
    }

    main_menu = {
        pipe_name: _drive_stock_click_until(
            pipe_name,
            process_id,
            0.5,
            0.95,
            lambda values: values.get("surface") == "main_menu",
            timeout=15.0,
            description="stock main menu",
        )
        for pipe_name, process_id in process_ids_by_pipe.items()
    }
    return {
        "mortuary": mortuary,
        "hall_of_fame": hall_of_fame,
        "main_menu": main_menu,
    }


def advance_stock_boneyard_game_over(
    process_ids_by_pipe: Mapping[str, int],
    retained_loadouts_by_pipe: Mapping[str, tuple[str, str]],
) -> dict[str, object]:
    if process_ids_by_pipe.keys() != retained_loadouts_by_pipe.keys():
        raise ValueError(
            "owned process and retained-loadout pipe sets must match"
        )
    create: dict[str, object] = {}
    for pipe_name, process_id in process_ids_by_pipe.items():
        state = _wait_for_state(
            pipe_name,
            lambda values: (
                values.get("surface") == "create"
                and _integer(values, "create_owner") > 0
                and values.get("local_loadout_state") == "picking"
                and _integer(values, "local_loadout_generation") >= 2
            ),
            timeout=60.0,
            description="next-generation stock Create after Boneyard Game Over",
        )
        transition = {
            "process_id": process_id,
            "game_over_input_count": 0,
            "state": state,
        }
        element, discipline = retained_loadouts_by_pipe[pipe_name]
        _assert_retained_create_selection(
            pipe_name,
            transition["state"],
            element,
            discipline,
        )
        create[pipe_name] = transition

    confirmations = {
        pipe_name: _confirm_retained_create_selection(
            pipe_name,
            *retained_loadouts_by_pipe[pipe_name],
        )
        for pipe_name in process_ids_by_pipe
    }
    return {
        "progression": "passive-game-over-then-stock-create-confirmation",
        "owned_process_ids": dict(process_ids_by_pipe),
        "create": create,
        "confirmations": confirmations,
    }


def _assert_retained_create_selection(
    pipe_name: str,
    values: Mapping[str, str],
    element: str,
    discipline: str,
) -> None:
    expected = (
        CREATE_ELEMENT_IDS[element],
        CREATE_DISCIPLINE_IDS[discipline],
    )
    actual = (
        _integer(values, "create_element_selected"),
        _integer(values, "create_discipline_selected"),
    )
    if actual != expected:
        raise VerifyFailure(
            f"{pipe_name} did not preselect its previous loadout on the "
            f"next stock Create surface: expected={expected} actual={actual} "
            f"state={dict(values)}"
        )


def _confirm_retained_create_selection(
    pipe_name: str,
    element: str,
    discipline: str,
) -> dict[str, object]:
    action_id = f"create.select_discipline_{discipline}"
    ready = _wait_for_state(
        pipe_name,
        lambda values: (
            values.get("surface") == "create"
            and _integer(values, "create_discipline_enabled") != 0
            and action_id in values.get("create_action_ids", "").split(",")
        ),
        timeout=12.0,
        description="retained stock Create confirmation readiness",
    )
    _assert_retained_create_selection(
        pipe_name,
        ready,
        element,
        discipline,
    )
    action = activate_native_ui_action(pipe_name, action_id, "create")
    hub = _wait_for_state(
        pipe_name,
        lambda values: (
            values.get("scene") == "hub"
            and values.get("session_state") == "in-hub"
        ),
        timeout=45.0,
        description="same-lobby hub after one-click retained loadout confirmation",
    )
    return {
        "ready": ready,
        "action": action,
        "semantic_confirmation_clicks": 1,
        "hub": hub,
    }


def _apply_authoritative_remote_lethal_hit(
    host_pipe: str,
    target_participant_id: int,
    label: str,
) -> dict[str, object]:
    trial = invoke_native_magic_hit_trial(
        host_pipe,
        projectile_damage=0.0,
        magic_damage=1000.0,
        attempts=2,
        label=label,
        timeout=8.0,
        target_participant_id=target_participant_id,
    )
    hp_after = float(trial["hp_after"])
    if not math.isfinite(hp_after) or hp_after > VITAL_TOLERANCE:
        raise VerifyFailure(
            f"{label} did not reach terminal life: {trial}"
        )
    return trial


def _owned_solo_processes(
    launch: Mapping[str, object],
) -> dict[int, str]:
    process_ids = game_process_ids(dict(launch))
    executable = launch.get("executablePath")
    if len(process_ids) != 1 or not isinstance(executable, str):
        raise VerifyFailure(
            f"solo launcher did not report exact process ownership: {launch}"
        )
    return {process_ids[0]: executable}


def _owned_trio_processes(
    launch: Mapping[str, object],
) -> dict[int, str]:
    process_ids = {
        key: int(value)
        for key, value in (
            ("host", launch.get("hostProcessId")),
            ("client", launch.get("clientProcessId")),
            ("third", launch.get("thirdProcessId")),
        )
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
    }
    runtime_root = launch.get("runtimeRoot")
    instance_prefix = launch.get("instancePrefix")
    if (
        len(process_ids) != 3
        or not isinstance(runtime_root, str)
        or not isinstance(instance_prefix, str)
    ):
        raise VerifyFailure(
            f"trio launcher did not report exact process ownership: {launch}"
        )
    return {
        process_id: _expected_instance_executable(
            runtime_root,
            f"{instance_prefix}-{role}",
        )
        for role, process_id in process_ids.items()
    }


def _owned_pair_processes(
    launch: Mapping[str, object],
) -> dict[int, str]:
    process_ids = {
        key: int(value)
        for key, value in (
            ("host", launch.get("hostProcessId")),
            ("client", launch.get("clientProcessId")),
        )
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
    }
    runtime_root = launch.get("runtimeRoot")
    instance_prefix = launch.get("instancePrefix")
    if (
        len(process_ids) != 2
        or not isinstance(runtime_root, str)
        or not isinstance(instance_prefix, str)
    ):
        raise VerifyFailure(
            f"pair launcher did not report exact process ownership: {launch}"
        )
    return {
        process_id: _expected_instance_executable(
            runtime_root,
            f"{instance_prefix}-{role}",
        )
        for role, process_id in process_ids.items()
    }


def _copy_existing_wizard_save(destination: Path) -> None:
    if not EXISTING_WIZARD_SAVE_FIXTURE.is_dir():
        raise VerifyFailure(
            "existing-wizard save fixture is missing: "
            f"{EXISTING_WIZARD_SAVE_FIXTURE}"
        )
    destination.mkdir(parents=True, exist_ok=False)
    shutil.copytree(
        EXISTING_WIZARD_SAVE_FIXTURE,
        destination / "solomondark",
    )


def run_solo_verification(
    *,
    instance_prefix: str,
    ports: list[int],
    game_directory: Path,
    launcher_path: Path | None = None,
    with_bot_play_mod: bool = False,
) -> dict[str, object]:
    instance = _launcher_instance_prefix(instance_prefix, "s")
    bot_settings = (
        _seed_bot_play_settings([instance])
        if with_bot_play_mod
        else {}
    )
    launch = launch_solo(
        instance=instance,
        local_port=ports[0],
        unused_remote_port=ports[1],
        game_directory=game_directory,
        launcher_path=launcher_path,
        exact_mod_ids=_acceptance_mod_ids(with_bot_play_mod),
    )
    owned = _owned_solo_processes(launch)
    result: dict[str, object] = {
        "launch": launch,
        "owned_processes": validate_owned_processes(owned),
        "bot_play_settings": bot_settings,
    }
    pipe_name = str(launch["luaPipe"])
    artifact_directory = ARTIFACT_ROOT / instance_prefix / "solo"
    try:
        wait_for_scene(pipe_name, "hub", 30.0)
        if with_bot_play_mod:
            result["bot_play_mod_active"] = (
                _assert_bot_play_mod_active(pipe_name)
            )
        result["bots_disabled"] = _disable_bots([pipe_name])
        _start_testrun_when_ready(pipe_name)
        wait_for_scene(pipe_name, "testrun", 30.0)
        result["membership"] = _wait_for_state(
            pipe_name,
            lambda values: (
                _integer(values, "participant_count") == 1
                and _integer(values, "remote_peer_count") == 0
                and _integer(values, "connected_run_count") == 1
                and healthy_loading_barrier_state_matches(values, 1)
            ),
            timeout=10.0,
            description="stable one-participant run materialization",
        )
        result["primed_vitals"] = set_local_player_vitals(
            pipe_name,
            1.0,
            25.0,
        )
        result["lethal_hit"] = invoke_native_magic_hit_trial(
            pipe_name,
            projectile_damage=0.0,
            magic_damage=1000.0,
            attempts=2,
            label="solo native Game Over",
            timeout=8.0,
        )

        samples: list[dict[str, str]] = []
        sample_deadline = time.monotonic() + 2.0
        while time.monotonic() < sample_deadline:
            sample = query_session_state(pipe_name)
            samples.append(sample)
            if not solo_terminal_state_matches(sample):
                raise VerifyFailure(
                    "solo death entered spectator state or left stock terminal "
                    f"ownership: {sample}"
                )
            time.sleep(0.05)
        result["post_death_samples"] = samples
        native_death_ticks = [
            _integer(sample, "local_native_death_tick")
            for sample in samples
        ]
        if (
            len(native_death_ticks) < 2
            or native_death_ticks[-1] <= native_death_ticks[0]
            or max(native_death_ticks) < 159
            or any(
                _integer(sample, "local_native_death_drive") != 1
                for sample in samples
            )
        ):
            raise VerifyFailure(
                "native last-player corpse clock did not advance through the "
                f"terminal frame beneath Game Over: {samples}"
            )
        result["last_player_death_clock"] = {
            "first_tick": native_death_ticks[0],
            "last_tick": native_death_ticks[-1],
            "maximum_tick": max(native_death_ticks),
            "sample_count": len(native_death_ticks),
        }

        screenshot = artifact_directory / "game-over.png"
        result["game_over"] = capture_native_game_over(
            pipe_name,
            screenshot,
            allow_boneyard_mode=True,
        )
        result["post_game_over"] = advance_stock_boneyard_game_over(
            {pipe_name: next(iter(owned))},
            {pipe_name: ("fire", "mind")},
        )
        result["ok"] = True
        return result
    finally:
        stop_owned_processes(owned)


def run_trio_verification(
    *,
    instance_prefix: str,
    ports: list[int],
    game_directory: Path,
    launcher_path: Path | None = None,
    with_bot_play_mod: bool = False,
) -> dict[str, object]:
    trio_prefix = _launcher_instance_prefix(instance_prefix, "m")
    bot_settings = (
        _seed_bot_play_settings(
            [
                f"{trio_prefix}-host",
                f"{trio_prefix}-client",
                f"{trio_prefix}-third",
            ]
        )
        if with_bot_play_mod
        else {}
    )
    launch = launch_pair(
        host_preset="map_create_fire_mind_hub",
        client_preset="map_create_water_body_hub",
        third_preset="map_create_earth_arcane_hub",
        temporary_host_profile=False,
        fresh_install=True,
        tile_windows=False,
        third_player=True,
        kill_existing=False,
        instance_prefix=trio_prefix,
        runtime_root=ROOT / "runtime",
        host_port=ports[2],
        client_port=ports[3],
        third_port=ports[4],
        game_directory=game_directory,
        launcher_path=launcher_path,
        exact_mod_ids=_acceptance_mod_ids(with_bot_play_mod),
        quick_start=True,
    )
    owned = _owned_trio_processes(launch)
    result: dict[str, object] = {
        "launch": launch,
        "owned_processes": validate_owned_processes(owned),
        "bot_play_settings": bot_settings,
    }
    host_pipe = str(launch["hostLuaPipe"])
    client_pipe = str(launch["clientLuaPipe"])
    third_pipe = str(launch["thirdLuaPipe"])
    pipes = [host_pipe, client_pipe, third_pipe]
    pipes_by_label = {
        "host": host_pipe,
        "client": client_pipe,
        "third": third_pipe,
    }
    artifact_directory = ARTIFACT_ROOT / instance_prefix / "trio"
    try:
        if with_bot_play_mod:
            result["bot_play_mod_active"] = {
                label: _assert_bot_play_mod_active(pipe_name)
                for label, pipe_name in pipes_by_label.items()
            }
        result["bots_disabled"] = _disable_bots(pipes)
        _start_testrun_when_ready(host_pipe)
        result["loading_boneyard"] = (
            capture_loading_presentations(
                pipes_by_label,
                artifact_directory,
                expected_participants=3,
            )
        )
        for pipe_name in pipes:
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
        result["first_run_loading_release"] = {
            label: _wait_for_state(
                pipe_name,
                lambda values: healthy_loading_barrier_state_matches(
                    values,
                    3,
                ),
                timeout=15.0,
                description=(
                    "healthy all-participant run-loading release"
                ),
            )
            for label, pipe_name in pipes_by_label.items()
        }
        first_run_nonces = {
            _integer(values, "run_nonce")
            for values in result[
                "first_run_loading_release"
            ].values()
        }
        if len(first_run_nonces) != 1 or min(first_run_nonces) <= 0:
            raise VerifyFailure(
                "first run did not converge on one nonzero nonce: "
                f"{result['first_run_loading_release']}"
            )
        first_run_nonce = next(iter(first_run_nonces))
        result["first_run_ready_frames"] = {
            label: capture_game_backbuffer(
                pipe_name,
                artifact_directory
                / f"{label}-first-run-ready.png",
            )
            for label, pipe_name in pipes_by_label.items()
        }

        result["first_death"] = _apply_authoritative_remote_lethal_hit(
            host_pipe,
            CLIENT_ID,
            "first trio participant death",
        )
        result["first_death_presentation"] = _wait_for_spectator_state(
            client_pipe,
            death_presentation_state_matches,
            timeout=5.0,
            description="first native death presentation",
        )
        result["first_spectating"] = _wait_for_spectator_state(
            client_pipe,
            spectator_state_matches,
            timeout=12.0,
            description="first dead participant spectating",
        )
        result["first_spectator_frame"] = capture_game_backbuffer(
            client_pipe,
            artifact_directory / "first-death-spectator.png",
        )

        result["second_death"] = _apply_authoritative_remote_lethal_hit(
            host_pipe,
            THIRD_ID,
            "second trio participant death",
        )
        result["second_death_presentation"] = _wait_for_spectator_state(
            third_pipe,
            death_presentation_state_matches,
            timeout=5.0,
            description="second native death presentation",
        )
        result["second_spectating"] = _wait_for_spectator_state(
            third_pipe,
            spectator_state_matches,
            timeout=12.0,
            description="second dead participant spectating",
        )
        result["first_still_spectating"] = _wait_for_spectator_state(
            client_pipe,
            spectator_state_matches,
            timeout=3.0,
            description="first participant still spectating the host",
        )
        result["second_spectator_frame"] = capture_game_backbuffer(
            third_pipe,
            artifact_directory / "second-death-spectator.png",
        )

        result["host_primed_vitals"] = set_local_player_vitals(
            host_pipe,
            1.0,
            25.0,
        )
        result["last_death"] = invoke_native_magic_hit_trial(
            host_pipe,
            projectile_damage=0.0,
            magic_damage=1000.0,
            attempts=2,
            label="last trio participant death",
            timeout=8.0,
        )

        terminal_states = {
            pipe_name: _wait_for_state(
                pipe_name,
                terminal_game_over_state_matches,
                timeout=12.0,
                description="authority-scoped native Game Over dispatch",
            )
            for pipe_name in pipes
        }
        epochs = {
            _integer(values, "game_over_command_epoch")
            for values in terminal_states.values()
        }
        nonces = {
            _integer(values, "game_over_run_nonce")
            for values in terminal_states.values()
        }
        if len(epochs) != 1 or len(nonces) != 1:
            raise VerifyFailure(
                "participants did not consume one shared terminal command: "
                f"states={terminal_states}"
            )
        result["terminal_states"] = terminal_states

        result["game_over"] = {
            label: capture_native_game_over(
                pipe_name,
                artifact_directory / f"{label}-game-over.png",
                allow_boneyard_mode=True,
            )
            for label, pipe_name in (
                ("host", host_pipe),
                ("client", client_pipe),
                ("third", third_pipe),
            )
        }
        result["post_game_over"] = advance_stock_boneyard_game_over(
            {
                host_pipe: int(launch["hostProcessId"]),
                client_pipe: int(launch["clientProcessId"]),
                third_pipe: int(launch["thirdProcessId"]),
            },
            {
                host_pipe: ("fire", "mind"),
                client_pipe: ("water", "body"),
                third_pipe: ("earth", "arcane"),
            },
        )
        for pipe_name in pipes:
            wait_for_scene(pipe_name, "hub", 60.0)
        hub_relationships: dict[str, dict[str, str]] = {}
        for observer_pipe, observer_id, _ in participants:
            for _, owner_id, owner_name in participants:
                if owner_id == observer_id:
                    continue
                key = f"{observer_id:x}_observes_{owner_id:x}"
                hub_relationships[key] = wait_for_remote(
                    observer_pipe,
                    owner_id,
                    owner_name,
                    "hub",
                    45.0,
                )
        result["same_lobby_hub_relationships"] = (
            hub_relationships
        )
        result["same_lobby_hub_state"] = {
            label: _wait_for_state(
                pipe_name,
                lambda values: (
                    values.get("session_state") == "in-hub"
                    and values.get(
                        "run_end_pending_lobby_return"
                    )
                    == "false"
                    and _integer(
                        values,
                        "participant_count",
                    )
                    == 3
                    and _integer(
                        values,
                        "remote_peer_count",
                    )
                    == 2
                ),
                timeout=15.0,
                description=(
                    "same-session shared hub after Game Over"
                ),
            )
            for label, pipe_name in pipes_by_label.items()
        }
        result["same_lobby_hub_frames"] = {
            label: capture_game_backbuffer(
                pipe_name,
                artifact_directory
                / f"{label}-same-lobby-hub.png",
            )
            for label, pipe_name in pipes_by_label.items()
        }
        result["same_processes_after_game_over"] = (
            validate_owned_processes(owned)
        )

        _start_testrun_when_ready(host_pipe)
        for pipe_name in pipes:
            wait_for_scene(pipe_name, "testrun", 45.0)
        second_run_relationships: dict[
            str,
            dict[str, str],
        ] = {}
        for observer_pipe, observer_id, _ in participants:
            for _, owner_id, owner_name in participants:
                if owner_id == observer_id:
                    continue
                key = f"{observer_id:x}_observes_{owner_id:x}"
                second_run_relationships[key] = wait_for_remote(
                    observer_pipe,
                    owner_id,
                    owner_name,
                    "testrun",
                    45.0,
                )
        result["second_run_relationships"] = (
            second_run_relationships
        )
        result["second_run_loading_release"] = {
            label: _wait_for_state(
                pipe_name,
                lambda values: healthy_loading_barrier_state_matches(
                    values,
                    3,
                ),
                timeout=15.0,
                description=(
                    "second-run all-participant loading release"
                ),
            )
            for label, pipe_name in pipes_by_label.items()
        }
        second_run_nonces = {
            _integer(values, "run_nonce")
            for values in result[
                "second_run_loading_release"
            ].values()
        }
        if (
            len(second_run_nonces) != 1
            or min(second_run_nonces) <= 0
            or first_run_nonce in second_run_nonces
        ):
            raise VerifyFailure(
                "same-lobby second run did not allocate one fresh nonce: "
                f"first={first_run_nonce} second={second_run_nonces}"
            )
        result["second_run_ready_frames"] = {
            label: capture_game_backbuffer(
                pipe_name,
                artifact_directory
                / f"{label}-second-run-ready.png",
            )
            for label, pipe_name in pipes_by_label.items()
        }
        result["same_processes_in_second_run"] = (
            validate_owned_processes(owned)
        )
        result["session_continuity"] = {
            "same_process_ids": True,
            "same_instance_group": trio_prefix,
            "participant_count": 3,
            "first_run_nonce": first_run_nonce,
            "second_run_nonce": next(
                iter(second_run_nonces)
            ),
            "rejoin_performed": False,
            "relaunch_performed": False,
        }
        result["ok"] = True
        return result
    finally:
        stop_owned_processes(owned)


def run_loading_timeout_verification(
    *,
    instance_prefix: str,
    ports: list[int],
    game_directory: Path,
    launcher_path: Path | None = None,
    with_bot_play_mod: bool = False,
) -> dict[str, object]:
    pair_prefix = _launcher_instance_prefix(instance_prefix, "t")
    bot_settings = (
        _seed_bot_play_settings(
            [
                f"{pair_prefix}-host",
                f"{pair_prefix}-client",
            ]
        )
        if with_bot_play_mod
        else {}
    )
    launch = launch_pair(
        host_preset="map_create_fire_mind_hub",
        client_preset="map_create_water_body_hub",
        temporary_host_profile=False,
        fresh_install=True,
        tile_windows=False,
        third_player=False,
        kill_existing=False,
        instance_prefix=pair_prefix,
        runtime_root=ROOT / "runtime",
        host_port=ports[5],
        client_port=ports[6],
        game_directory=game_directory,
        launcher_path=launcher_path,
        exact_mod_ids=_acceptance_mod_ids(with_bot_play_mod),
        quick_start=True,
    )
    owned = _owned_pair_processes(launch)
    host_process_id = int(launch["hostProcessId"])
    client_process_id = int(launch["clientProcessId"])
    host_owned = {
        host_process_id: owned[host_process_id],
    }
    client_owned = {
        client_process_id: owned[client_process_id],
    }
    host_pipe = str(launch["hostLuaPipe"])
    client_pipe = str(launch["clientLuaPipe"])
    artifact_directory = (
        ARTIFACT_ROOT / instance_prefix / "timeout"
    )
    result: dict[str, object] = {
        "launch": launch,
        "owned_processes": validate_owned_processes(owned),
        "bot_play_settings": bot_settings,
    }
    try:
        if with_bot_play_mod:
            result["bot_play_mod_active"] = {
                "host": _assert_bot_play_mod_active(host_pipe),
                "client": _assert_bot_play_mod_active(client_pipe),
            }
        result["bots_disabled"] = _disable_bots(
            [host_pipe, client_pipe]
        )
        _start_testrun_when_ready(host_pipe)
        result["host_barrier_before_peer_kill"] = (
            _wait_for_state(
                host_pipe,
                lambda values: (
                    loading_barrier_wait_state_matches(
                        values,
                        2,
                    )
                    and _integer(
                        values,
                        "loading_ready_participant_count",
                    )
                    < 2
                ),
                timeout=20.0,
                description=(
                    "host barrier frozen with both peers before kill"
                ),
            )
        )
        killed_at = time.monotonic()
        stop_owned_processes(client_owned)
        if _query_process_executable(client_process_id) is not None:
            raise VerifyFailure(
                "exact client PID remained alive after timeout-drill kill"
            )
        result["killed_peer"] = {
            "process_id": client_process_id,
            "expected_executable": owned[
                client_process_id
            ],
            "exact_pid_absent_after_kill": True,
        }

        waiting = _wait_for_state(
            host_pipe,
            lambda values: (
                loading_barrier_wait_state_matches(
                    values,
                    2,
                )
                and _integer(
                    values,
                    "loading_ready_participant_count",
                )
                < 2
            ),
            timeout=20.0,
            description=(
                "host barrier waiting for killed peer"
            ),
        )
        result["host_waiting_state"] = waiting
        artifact_directory.mkdir(
            parents=True,
            exist_ok=True,
        )
        loading_path = (
            artifact_directory
            / "host-loading-after-peer-kill.png"
        )
        loading_capture = capture_game_backbuffer(
            host_pipe,
            loading_path,
            minimum_unique_colors=20,
            maximum_dominant_fraction=0.9999,
        )
        loading_classification = (
            classify_loading_boneyard_image(loading_path)
        )
        if not loading_classification["matched"]:
            raise VerifyFailure(
                "surviving host did not retain Loading Boneyard "
                "while waiting for the killed peer: "
                f"{loading_classification}"
            )
        result["host_loading_frame"] = {
            "capture": loading_capture,
            "classification": loading_classification,
        }

        release_wait_started = time.monotonic()
        released = _wait_for_state(
            host_pipe,
            lambda values: (
                loading_barrier_released_state_matches(
                    values,
                    2,
                    expected_reason="timeout",
                )
                and values.get("loading_timed_out")
                == "true"
                and _integer(
                    values,
                    "loading_ready_participant_count",
                )
                < 2
                and _integer(
                    values,
                    "loading_deadline_remaining_ms",
                )
                == 0
            ),
            timeout=35.0,
            description=(
                "bounded host loading-barrier timeout release"
            ),
        )
        result["host_timeout_state"] = released
        result["timing"] = {
            "seconds_from_peer_kill": (
                time.monotonic() - killed_at
            ),
            "seconds_waiting_after_observation": (
                time.monotonic()
                - release_wait_started
            ),
            "configured_timeout_ms": 25000,
        }
        proceeded_path = (
            artifact_directory
            / "host-proceeded-after-timeout.png"
        )
        proceeded_capture = capture_game_backbuffer(
            host_pipe,
            proceeded_path,
        )
        proceeded_classification = (
            classify_loading_boneyard_image(proceeded_path)
        )
        if proceeded_classification["matched"]:
            raise VerifyFailure(
                "surviving host still rendered Loading Boneyard "
                "after the timeout release"
            )
        result["host_proceeded_frame"] = {
            "capture": proceeded_capture,
            "loading_classification": proceeded_classification,
        }
        result["surviving_host_process"] = (
            validate_owned_processes(host_owned)
        )

        log_path = _path_for_local_python(str(launch["hostLog"]))
        try:
            log_lines = log_path.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines()
        except OSError as exc:
            raise VerifyFailure(
                f"timeout-drill loader log unavailable: {log_path}"
            ) from exc
        barrier_lines = [
            line
            for line in log_lines
            if "run-loading barrier" in line
        ]
        if not any(
            "reason=timeout" in line
            and "waiting_participant_ids=" in line
            for line in barrier_lines
        ):
            raise VerifyFailure(
                "timeout-drill log lacks bounded release evidence: "
                f"{barrier_lines[-20:]}"
            )
        result["barrier_log"] = {
            "path": str(log_path),
            "lines": barrier_lines[-20:],
        }
        result["ok"] = True
        return result
    finally:
        stop_owned_processes(owned)


def run_death_reset_pair_verification(
    *,
    instance_prefix: str,
    ports: list[int],
    game_directory: Path,
    launcher_path: Path | None = None,
    with_bot_play_mod: bool = False,
) -> dict[str, object]:
    if len(ports) != 2:
        raise ValueError("death-reset verification requires exactly two ports")
    required_prefixes = ("bply",) if with_bot_play_mod else ("drst", "ldt")
    if not instance_prefix.startswith(required_prefixes):
        raise ValueError(
            "death-reset verification instance prefix must start with one of "
            f"{required_prefixes}"
        )

    artifact_directory = ARTIFACT_ROOT / instance_prefix / "death-reset"
    artifact_directory.mkdir(parents=True, exist_ok=True)
    runtime_parent = ROOT / "runtime"
    runtime_parent.mkdir(parents=True, exist_ok=True)
    result: dict[str, object] = {
        "ok": False,
        "instance_prefix": instance_prefix,
        "ports": ports,
        "fixture": str(EXISTING_WIZARD_SAVE_FIXTURE),
    }
    if with_bot_play_mod:
        result["bot_play_settings"] = _seed_bot_play_settings(
            [
                f"{instance_prefix}-host",
                f"{instance_prefix}-client",
            ]
        )
    with tempfile.TemporaryDirectory(
        prefix=f"{instance_prefix}-save-",
        dir=runtime_parent,
    ) as temporary_root_text:
        temporary_root = Path(temporary_root_text)
        host_savegames = temporary_root / "host"
        client_savegames = temporary_root / "client"
        _copy_existing_wizard_save(host_savegames)
        _copy_existing_wizard_save(client_savegames)
        result["save_staging"] = {
            "mode": "copied_existing_wizard_per_peer",
            "host_root": str(host_savegames),
            "client_root": str(client_savegames),
        }

        launch = launch_pair(
            host_preset="map_create_air_mind_hub",
            client_preset="map_create_water_body_hub",
            temporary_host_profile=False,
            fresh_install=False,
            god_mode=False,
            tile_windows=False,
            third_player=False,
            allow_focus_steal=False,
            kill_existing=False,
            instance_prefix=instance_prefix,
            runtime_root=ROOT / "runtime",
            host_port=ports[0],
            client_port=ports[1],
            third_port=ports[1],
            game_directory=game_directory,
            launcher_path=launcher_path,
            exact_mod_ids=_acceptance_mod_ids(with_bot_play_mod),
            quick_start=True,
            no_lua_automation=True,
            host_savegames_root=host_savegames,
            client_savegames_root=client_savegames,
            enable_audio=False,
        )
        owned = _owned_pair_processes(launch)
        result["launch"] = launch
        result["owned_processes"] = validate_owned_processes(owned)
        host_pipe = str(launch["hostLuaPipe"])
        client_pipe = str(launch["clientLuaPipe"])
        pipes = {
            "host": host_pipe,
            "client": client_pipe,
        }
        try:
            if launch.get("audioDisabled") is not True:
                raise VerifyFailure(
                    f"death-reset pair did not disable audio: {launch}"
                )
            if launch.get("quickStartEnabled") is not True:
                raise VerifyFailure(
                    f"death-reset pair did not enable quick-start: {launch}"
                )
            if launch.get("noLuaAutomation") is not True:
                raise VerifyFailure(
                    "death-reset pair did not use native quick-start"
                )
            if with_bot_play_mod:
                result["bot_play_mod_active"] = {
                    "host": _assert_bot_play_mod_active(host_pipe),
                    "client": _assert_bot_play_mod_active(client_pipe),
                }

            result["bots_disabled"] = _disable_bots(list(pipes.values()))
            result["initial_hub_relationships"] = {
                "host_observes_client": wait_for_remote(
                    host_pipe,
                    CLIENT_ID,
                    CLIENT_NAME,
                    "hub",
                    45.0,
                ),
                "client_observes_host": wait_for_remote(
                    client_pipe,
                    HOST_ID,
                    HOST_NAME,
                    "hub",
                    45.0,
                ),
            }

            _start_testrun_when_ready(host_pipe)
            for pipe_name in pipes.values():
                wait_for_scene(pipe_name, "testrun", 45.0)
            result["first_run_relationships"] = {
                "host_observes_client": wait_for_remote(
                    host_pipe,
                    CLIENT_ID,
                    CLIENT_NAME,
                    "testrun",
                    45.0,
                ),
                "client_observes_host": wait_for_remote(
                    client_pipe,
                    HOST_ID,
                    HOST_NAME,
                    "testrun",
                    45.0,
                ),
            }
            result["first_run_loading_release"] = {
                label: _wait_for_state(
                    pipe_name,
                    lambda values: healthy_loading_barrier_state_matches(
                        values,
                        2,
                    ),
                    timeout=15.0,
                    description=(
                        "first-run two-participant loading release"
                    ),
                )
                for label, pipe_name in pipes.items()
            }
            first_run_states = {
                label: _wait_for_death_reset_state(
                    pipe_name,
                    expected_scene="testrun",
                )
                for label, pipe_name in pipes.items()
            }
            result["first_run_alive"] = first_run_states
            expected_appearance = {
                label: remote_appearance_fingerprint(values)
                for label, values in first_run_states.items()
            }
            result["expected_remote_appearance"] = expected_appearance
            result["first_run_frames"] = {
                label: capture_game_backbuffer(
                    pipe_name,
                    artifact_directory / f"{label}-first-run-alive.png",
                )
                for label, pipe_name in pipes.items()
            }

            result["client_death"] = (
                _apply_authoritative_remote_lethal_hit(
                    host_pipe,
                    CLIENT_ID,
                    "death-reset client death",
                )
            )
            result["client_death_presentation"] = (
                _wait_for_spectator_state(
                    client_pipe,
                    death_presentation_state_matches,
                    timeout=5.0,
                    description="death-reset client death presentation",
                )
            )
            result["client_spectating"] = _wait_for_spectator_state(
                client_pipe,
                spectator_state_matches,
                timeout=12.0,
                description="death-reset client spectator state",
            )
            result["host_primed_vitals"] = set_local_player_vitals(
                host_pipe,
                1.0,
                25.0,
            )
            result["host_death"] = invoke_native_magic_hit_trial(
                host_pipe,
                projectile_damage=0.0,
                magic_damage=1000.0,
                attempts=2,
                label="death-reset host terminal death",
                timeout=8.0,
            )

            result["terminal_states"] = {
                label: _wait_for_state(
                    pipe_name,
                    terminal_game_over_state_matches,
                    timeout=12.0,
                    description=(
                        "death-reset authority-scoped Game Over dispatch"
                    ),
                )
                for label, pipe_name in pipes.items()
            }
            result["game_over"] = {
                label: capture_native_game_over(
                    pipe_name,
                    artifact_directory / f"{label}-game-over.png",
                    allow_boneyard_mode=True,
                )
                for label, pipe_name in pipes.items()
            }
            host_create = _drive_stock_click_until(
                host_pipe,
                int(launch["hostProcessId"]),
                0.5,
                0.5,
                lambda values: (
                    values.get("surface") == "create"
                    and _integer(values, "create_owner") > 0
                    and values.get("local_loadout_state") == "picking"
                    and _integer(values, "local_loadout_generation") >= 2
                ),
                timeout=60.0,
                description=(
                    "host next-generation stock Create before client return"
                ),
            )
            _assert_retained_create_selection(
                host_pipe,
                host_create["state"],
                "air",
                "mind",
            )
            client_during_host_repick = query_session_state(client_pipe)
            if not terminal_game_over_state_matches(client_during_host_repick):
                raise VerifyFailure(
                    "client left native Game Over while only the host advanced "
                    f"to repick: {client_during_host_repick}"
                )
            host_confirmation = _confirm_retained_create_selection(
                host_pipe,
                "air",
                "mind",
            )
            host_first_hub = _wait_for_unmaterialized_remote_in_hub(host_pipe)
            result["host_first_hub_before_client_return"] = (
                host_first_hub
            )
            time.sleep(1.25)
            result["host_first_hub_after_join_presentation"] = (
                _wait_for_unmaterialized_remote_in_hub(host_pipe)
            )
            result["host_first_hub_frame"] = capture_game_backbuffer(
                host_pipe,
                artifact_directory
                / "host-first-hub-before-client-return.png",
            )
            result["client_state_during_host_first_hub"] = (
                query_session_state(client_pipe)
            )
            client_create = _drive_stock_click_until(
                client_pipe,
                int(launch["clientProcessId"]),
                0.5,
                0.5,
                lambda values: (
                    values.get("surface") == "create"
                    and _integer(values, "create_owner") > 0
                    and values.get("local_loadout_state") == "picking"
                    and _integer(values, "local_loadout_generation") >= 2
                ),
                timeout=60.0,
                description=(
                    "client next-generation stock Create after host-first hub"
                ),
            )
            _assert_retained_create_selection(
                client_pipe,
                client_create["state"],
                "water",
                "body",
            )
            client_confirmation = _confirm_retained_create_selection(
                client_pipe,
                "water",
                "body",
            )
            result["post_game_over"] = {
                "progression": (
                    "staggered-stock-create-with-retained-one-click-confirmation"
                ),
                "host_create": host_create,
                "client_during_host_repick": client_during_host_repick,
                "host_confirmation": host_confirmation,
                "client_create": client_create,
                "client_confirmation": client_confirmation,
            }

            for pipe_name in pipes.values():
                wait_for_scene(pipe_name, "hub", 60.0)
            result["same_lobby_hub_relationships"] = {
                "host_observes_client": wait_for_remote(
                    host_pipe,
                    CLIENT_ID,
                    CLIENT_NAME,
                    "hub",
                    45.0,
                ),
                "client_observes_host": wait_for_remote(
                    client_pipe,
                    HOST_ID,
                    HOST_NAME,
                    "hub",
                    45.0,
                ),
            }
            hub_states = {
                label: _wait_for_death_reset_state(
                    pipe_name,
                    expected_scene="hub",
                )
                for label, pipe_name in pipes.items()
            }
            result["same_lobby_hub_vitality"] = hub_states
            result["same_lobby_hub_frames"] = {
                label: capture_game_backbuffer(
                    pipe_name,
                    artifact_directory
                    / f"{label}-same-lobby-hub.png",
                )
                for label, pipe_name in pipes.items()
            }
            result["same_processes_after_game_over"] = (
                validate_owned_processes(owned)
            )

            _start_testrun_when_ready(host_pipe)
            for pipe_name in pipes.values():
                wait_for_scene(pipe_name, "testrun", 45.0)
            result["second_run_relationships"] = {
                "host_observes_client": wait_for_remote(
                    host_pipe,
                    CLIENT_ID,
                    CLIENT_NAME,
                    "testrun",
                    45.0,
                ),
                "client_observes_host": wait_for_remote(
                    client_pipe,
                    HOST_ID,
                    HOST_NAME,
                    "testrun",
                    45.0,
                ),
            }
            result["second_run_loading_release"] = {
                label: _wait_for_state(
                    pipe_name,
                    lambda values: healthy_loading_barrier_state_matches(
                        values,
                        2,
                    ),
                    timeout=15.0,
                    description=(
                        "second-run two-participant loading release"
                    ),
                )
                for label, pipe_name in pipes.items()
            }
            second_run_states = {
                label: _wait_for_death_reset_state(
                    pipe_name,
                    expected_scene="testrun",
                )
                for label, pipe_name in pipes.items()
            }
            result["second_run_vitality"] = second_run_states
            result["second_run_frames"] = {
                label: capture_game_backbuffer(
                    pipe_name,
                    artifact_directory / f"{label}-second-run-alive.png",
                )
                for label, pipe_name in pipes.items()
            }
            result["same_processes_in_second_run"] = (
                validate_owned_processes(owned)
            )

            assertions = {
                "host_first_hub_before_client_return": (
                    local_hub_vitality_reset_without_remote_matches(
                        host_first_hub
                    )
                ),
            }
            assertions.update(
                {
                    f"hub_{label}": (
                        run_boundary_vitality_reset_matches(
                            values,
                            expected_remote_appearance=(
                                expected_appearance[label]
                            ),
                            expected_scene="hub",
                        )
                    )
                    for label, values in hub_states.items()
                }
            )
            assertions.update(
                {
                    f"run2_{label}": (
                        run_boundary_vitality_reset_matches(
                            values,
                            expected_remote_appearance=(
                                expected_appearance[label]
                            ),
                            expected_scene="testrun",
                        )
                    )
                    for label, values in second_run_states.items()
                }
            )
            result["vitality_reset_assertions"] = assertions
            result["same_session_continuity"] = {
                "same_process_ids": True,
                "rejoin_performed": False,
                "relaunch_performed": False,
            }
            failed = [
                label
                for label, accepted in assertions.items()
                if not accepted
            ]
            if failed:
                result["error"] = (
                    "Game Over run-boundary vitality reset failed: "
                    + ", ".join(failed)
                )
            else:
                result["ok"] = True
            return result
        finally:
            stop_owned_processes(owned)


def run_live_verification(
    *,
    instance_prefix: str,
    ports: list[int],
    game_directory: Path,
    launcher_path: Path | None = None,
    with_bot_play_mod: bool = False,
) -> dict[str, object]:
    return {
        "instance_prefix": instance_prefix,
        "ports": ports,
        "solo": run_solo_verification(
            instance_prefix=instance_prefix,
            ports=ports,
            game_directory=game_directory,
            launcher_path=launcher_path,
            with_bot_play_mod=with_bot_play_mod,
        ),
        "trio": run_trio_verification(
            instance_prefix=instance_prefix,
            ports=ports,
            game_directory=game_directory,
            launcher_path=launcher_path,
            with_bot_play_mod=with_bot_play_mod,
        ),
        "timeout_drill": run_loading_timeout_verification(
            instance_prefix=instance_prefix,
            ports=ports,
            game_directory=game_directory,
            launcher_path=launcher_path,
            with_bot_play_mod=with_bot_play_mod,
        ),
        "with_bot_play_mod": with_bot_play_mod,
        "ok": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--instance-prefix",
        default="",
        help="Unique launcher group prefix (generated by default).",
    )
    parser.add_argument(
        "--game-dir",
        type=Path,
        required=True,
        help="Retail game directory used by isolated worktrees.",
    )
    parser.add_argument(
        "--launcher-path",
        type=Path,
        default=None,
        help="Exact built launcher used to stage every isolated instance.",
    )
    parser.add_argument("--solo-port", type=int, default=None)
    parser.add_argument("--solo-unused-port", type=int, default=None)
    parser.add_argument("--host-port", type=int, default=None)
    parser.add_argument("--client-port", type=int, default=None)
    parser.add_argument("--third-port", type=int, default=None)
    parser.add_argument("--timeout-host-port", type=int, default=None)
    parser.add_argument("--timeout-client-port", type=int, default=None)
    parser.add_argument(
        "--death-reset-only",
        action="store_true",
        help=(
            "Run the focused two-peer Game Over -> hub -> next-run "
            "vitality and appearance reset regression."
        ),
    )
    parser.add_argument(
        "--with-bot-play-mod",
        action="store_true",
        help=(
            "Enable bot.brain with local takeover disabled while the "
            "canonical stock Game Over semantics run."
        ),
    )
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    instance_prefix = args.instance_prefix or _default_instance_prefix()
    result: dict[str, object] = {
        "ok": False,
        "instance_prefix": instance_prefix,
    }
    try:
        if (
            args.with_bot_play_mod
            and not instance_prefix.startswith("bply")
        ):
            raise ValueError(
                "Bot Play For Me canonical instances require bply prefix"
            )
        if args.death_reset_only:
            result = run_death_reset_pair_verification(
                instance_prefix=instance_prefix,
                ports=_resolve_death_reset_ports(
                    args.host_port,
                    args.client_port,
                ),
                game_directory=args.game_dir,
                launcher_path=args.launcher_path,
                with_bot_play_mod=args.with_bot_play_mod,
            )
        else:
            result = run_live_verification(
                instance_prefix=instance_prefix,
                ports=_resolve_udp_ports(
                    [
                        args.solo_port,
                        args.solo_unused_port,
                        args.host_port,
                        args.client_port,
                        args.third_port,
                        args.timeout_host_port,
                        args.timeout_client_port,
                    ]
                ),
                game_directory=args.game_dir,
                launcher_path=args.launcher_path,
                with_bot_play_mod=args.with_bot_play_mod,
            )
        exit_code = 0 if result.get("ok") is True else 1
    except Exception as exc:  # noqa: BLE001 - preserve full verifier failure.
        result["error"] = str(exc)
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
