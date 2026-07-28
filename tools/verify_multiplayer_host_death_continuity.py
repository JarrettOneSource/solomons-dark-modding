#!/usr/bin/env python3
"""Verify organic wave and client-input continuity after host-character death."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import re
import shutil
import statistics
import time
import traceback
from pathlib import Path
from typing import Any

from multiplayer_defense_behavior_harness import invoke_native_magic_hit_trial
from multiplayer_frame_capture import capture_game_backbuffer
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    HOST_ID,
    HOST_NAME,
    ROOT,
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
    _arm_death_traces,
    _disarm_death_traces,
)
from verify_multiplayer_organic_player_death import (
    ACCEPTANCE_MOD_ID,
    _disable_companion_bots,
    _launch_log_path,
    _query_live_enemies,
    _start_testrun_when_ready,
    _start_waves,
    _wait_for_new_wave_enemy,
)
from verify_multiplayer_rush_behavior_sync import hold_real_key
from verify_player_health_death_sync import set_local_player_vitals


OUTPUT = ROOT / "runtime" / "multiplayer_host_death_continuity.json"
ARTIFACT_ROOT = ROOT / "runtime" / "multiplayer_host_death_continuity"
DEFAULT_OBSERVATION_SECONDS = 180.0
MINIMUM_OBSERVATION_SECONDS = 65.0
PROBE_INTERVAL_MS = 100
SURVIVOR_HP = 1_000_000.0
HOST_ARMING_HP = 1.0
HOST_MAX_HP = 50.0
REAL_INPUT_KEY = "d"
REAL_INPUT_HOLD_MS = 8_000
MINIMUM_ENEMY_DISPLACEMENT = 16.0
MINIMUM_CLIENT_B_DISPLACEMENT = 16.0


class HostDeathContinuityFailure(VerifyFailure):
    """Live verifier failure that retains all evidence captured so far."""

    def __init__(self, message: str, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


ARM_CONTINUITY_PROBE_LUA = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
_G.__sdmod_host_death_continuity_probe = {
  active = true,
  next_ms = 0,
  interval_ms = __INTERVAL_MS__,
  limit = __SAMPLE_LIMIT__,
  samples = {},
  enemy_actor_address = 0,
  enemy_network_id = 0,
}
if not _G.__sdmod_host_death_continuity_probe_registered then
  sd.events.on("runtime.tick", function(event)
    local probe = _G.__sdmod_host_death_continuity_probe
    if type(probe) ~= "table" or not probe.active then return end
    local now_ms = tonumber(event and event.monotonic_milliseconds) or 0
    if now_ms < (tonumber(probe.next_ms) or 0) then return end
    probe.next_ms = now_ms + probe.interval_ms

    local player = sd.player and sd.player.get_state and
      sd.player.get_state() or nil
    local replicated = sd.world.get_replicated_actors and
      sd.world.get_replicated_actors() or nil
    local multiplayer = sd.runtime and sd.runtime.get_multiplayer_state and
      sd.runtime.get_multiplayer_state() or nil
    local loading = multiplayer and multiplayer.run_loading_barrier or {}
    local pause = multiplayer and multiplayer.shared_gameplay_pause_status or {}
    local terminal = multiplayer and multiplayer.game_over or {}
    local local_row = nil
    for _, participant in ipairs(multiplayer and multiplayer.participants or {}) do
      if participant.kind == "LocalHuman" then
        local_row = participant
        break
      end
    end

    local wanted_local_address =
      tonumber(probe.enemy_actor_address) or 0
    local wanted_network_id = tonumber(probe.enemy_network_id) or 0
    local binding_matched = false
    local binding_parked = false
    local binding_removed = false
    if wanted_network_id ~= 0 then
      for _, binding in ipairs(replicated and replicated.bindings or {}) do
        if tonumber(binding.network_actor_id) == wanted_network_id then
          binding_matched = binding.matched == true
          binding_parked = binding.parked == true
          binding_removed = binding.removed == true
          if (tonumber(binding.local_actor_address) or 0) ~= 0 then
            wanted_local_address = tonumber(binding.local_actor_address)
            probe.enemy_actor_address = wanted_local_address
          end
          break
        end
      end
    end

    local local_enemy = nil
    for _, actor in ipairs(
        sd.world.list_actors and sd.world.list_actors() or {}) do
      if wanted_local_address ~= 0 and
          tonumber(actor.actor_address) == wanted_local_address then
        local_enemy = actor
        break
      end
    end
    local authority_enemy = nil
    for _, actor in ipairs(replicated and replicated.actors or {}) do
      if wanted_network_id ~= 0 and
          tonumber(actor.network_actor_id) == wanted_network_id then
        authority_enemy = actor
        break
      end
    end

    local local_address =
      tonumber(local_enemy and local_enemy.actor_address) or 0
    local pending_initialize = 0
    local selector_pending = 0
    if local_address ~= 0 then
      local pending_offset = sd.debug.layout_offset("actor_pending_initialize")
      local selector_offset = sd.debug.layout_offset("actor_register_transient")
      pending_initialize = pending_offset and
        (tonumber(sd.debug.read_u8(local_address + pending_offset)) or 0) or -1
      selector_pending = selector_offset and
        (tonumber(sd.debug.read_u8(local_address + selector_offset)) or 0) or -1
    end

    probe.samples[#probe.samples + 1] = {
      monotonic_ms = now_ms,
      received_ms = tonumber(replicated and replicated.received_ms) or 0,
      sequence = tonumber(replicated and replicated.sequence) or 0,
      player_hp = tonumber(player and player.hp) or 0,
      network_actor_id =
        tonumber(authority_enemy and authority_enemy.network_actor_id) or 0,
      authority_x = tonumber(authority_enemy and authority_enemy.x) or 0,
      authority_y = tonumber(authority_enemy and authority_enemy.y) or 0,
      authority_hp = tonumber(authority_enemy and authority_enemy.hp) or 0,
      authority_max_hp =
        tonumber(authority_enemy and authority_enemy.max_hp) or 0,
      target =
        tonumber(authority_enemy and authority_enemy.target_participant_id) or 0,
      local_address = local_address,
      local_type =
        tonumber(local_enemy and local_enemy.object_type_id) or 0,
      local_x = tonumber(local_enemy and local_enemy.x) or 0,
      local_y = tonumber(local_enemy and local_enemy.y) or 0,
      local_hp = tonumber(local_enemy and local_enemy.hp) or 0,
      local_max_hp = tonumber(local_enemy and local_enemy.max_hp) or 0,
      pending_initialize = pending_initialize,
      selector_pending = selector_pending,
      binding_matched = binding_matched,
      binding_parked = binding_parked,
      binding_removed = binding_removed,
      authority_participant_id =
        tonumber(replicated and replicated.authority_participant_id) or 0,
      session_state = tostring(multiplayer and multiplayer.session_state or ""),
      run_nonce = tonumber(local_row and local_row.run_nonce) or 0,
      loading_run_nonce = tonumber(loading.run_nonce) or 0,
      loading_release_nonce = tonumber(loading.release_nonce) or 0,
      shared_pause_active = pause.pause_active == true,
      teardown_active = multiplayer and multiplayer.teardown_active == true,
      game_over_command_epoch = tonumber(terminal.command_epoch) or 0,
      game_over_accepted_epoch = tonumber(terminal.accepted_epoch) or 0,
      game_over_pending_dispatch = terminal.pending_dispatch == true,
      game_over_dispatch_count = tonumber(terminal.dispatch_count) or 0,
    }
    if #probe.samples >= probe.limit then probe.active = false end
  end)
  _G.__sdmod_host_death_continuity_probe_registered = true
end
emit("registered", _G.__sdmod_host_death_continuity_probe_registered)
emit("active", _G.__sdmod_host_death_continuity_probe.active)
"""


STOP_CONTINUITY_PROBE_LUA = r"""
local probe = _G.__sdmod_host_death_continuity_probe
if type(probe) ~= "table" then error("continuity probe unavailable") end
probe.active = false
print("count=" .. tostring(#(probe.samples or {})))
"""


QUERY_CONTINUITY_PROBE_LUA = r"""
local probe = _G.__sdmod_host_death_continuity_probe
if type(probe) ~= "table" then error("continuity probe unavailable") end
local first = __FIRST_SAMPLE__
local count = __SAMPLE_COUNT__
local last = math.min(#(probe.samples or {}), first + count - 1)
for index = first, last do
  local sample = probe.samples[index]
  print(table.concat({
    "S",
    tostring(sample.monotonic_ms or 0),
    tostring(sample.received_ms or 0),
    tostring(sample.sequence or 0),
    string.format("%.6f", sample.player_hp or 0),
    tostring(sample.network_actor_id or 0),
    string.format("%.6f", sample.authority_x or 0),
    string.format("%.6f", sample.authority_y or 0),
    string.format("%.6f", sample.authority_hp or 0),
    string.format("%.6f", sample.authority_max_hp or 0),
    tostring(sample.target or 0),
    tostring(sample.local_address or 0),
    tostring(sample.local_type or 0),
    string.format("%.6f", sample.local_x or 0),
    string.format("%.6f", sample.local_y or 0),
    string.format("%.6f", sample.local_hp or 0),
    string.format("%.6f", sample.local_max_hp or 0),
    tostring(sample.pending_initialize or 0),
    tostring(sample.selector_pending or 0),
    sample.binding_matched and "1" or "0",
    sample.binding_parked and "1" or "0",
    sample.binding_removed and "1" or "0",
    tostring(sample.authority_participant_id or 0),
    sample.session_state or "",
    tostring(sample.run_nonce or 0),
    tostring(sample.loading_run_nonce or 0),
    tostring(sample.loading_release_nonce or 0),
    sample.shared_pause_active and "1" or "0",
    sample.teardown_active and "1" or "0",
    tostring(sample.game_over_command_epoch or 0),
    tostring(sample.game_over_accepted_epoch or 0),
    sample.game_over_pending_dispatch and "1" or "0",
    tostring(sample.game_over_dispatch_count or 0),
  }, "|"))
end
"""


CONFIGURE_CONTINUITY_ENEMY_LUA = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local probe = _G.__sdmod_host_death_continuity_probe
if type(probe) ~= "table" then error("continuity probe unavailable") end
local wanted_address = __ENEMY_ACTOR_ADDRESS__
local wanted_network_id = __ENEMY_NETWORK_ID__
if wanted_network_id == 0 and wanted_address ~= 0 then
  local selected = nil
  for _, actor in ipairs(
      sd.world.list_actors and sd.world.list_actors() or {}) do
    if tonumber(actor.actor_address) == wanted_address then
      selected = actor
      break
    end
  end
  local replicated = sd.world.get_replicated_actors and
    sd.world.get_replicated_actors() or nil
  local best_distance = math.huge
  for _, actor in ipairs(replicated and replicated.actors or {}) do
    if selected and actor.tracked_enemy and not actor.dead and
        tonumber(actor.object_type_id) ==
          tonumber(selected.object_type_id) then
      local dx = (tonumber(actor.x) or 0) - (tonumber(selected.x) or 0)
      local dy = (tonumber(actor.y) or 0) - (tonumber(selected.y) or 0)
      local distance = math.sqrt(dx * dx + dy * dy)
      if distance < best_distance then
        best_distance = distance
        wanted_network_id = tonumber(actor.network_actor_id) or 0
      end
    end
  end
  emit("distance", best_distance)
end
if wanted_network_id ~= 0 then
  local replicated = sd.world.get_replicated_actors and
    sd.world.get_replicated_actors() or nil
  for _, binding in ipairs(replicated and replicated.bindings or {}) do
    if tonumber(binding.network_actor_id) == wanted_network_id and
        (tonumber(binding.local_actor_address) or 0) ~= 0 then
      wanted_address = tonumber(binding.local_actor_address)
      break
    end
  end
end
probe.enemy_actor_address = wanted_address
probe.enemy_network_id = wanted_network_id
emit("actor_address", probe.enemy_actor_address)
emit("network_id", probe.enemy_network_id)
"""


POSTDEATH_ENEMY_BOUNDARY_LUA = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local address = __ENEMY_ACTOR_ADDRESS__
local selected = nil
for _, actor in ipairs(
    sd.world.list_actors and sd.world.list_actors() or {}) do
  if tonumber(actor.actor_address) == address then
    selected = actor
    break
  end
end
local function off(name) return sd.debug.layout_offset(name) end
local pending = off("actor_pending_initialize")
local selector = off("actor_register_transient")
local target = off("actor_current_target_actor")
local group = off("actor_world_group")
local slot = off("actor_world_slot")
emit("available", selected ~= nil)
emit("pending_initialize", selected and pending and
  sd.debug.read_u8(address + pending) or -1)
emit("selector_pending", selected and selector and
  sd.debug.read_u8(address + selector) or -1)
emit("target_actor", selected and target and
  sd.debug.read_ptr(address + target) or 0)
emit("actor_group", selected and group and
  sd.debug.read_u8(address + group) or -1)
emit("actor_slot", selected and slot and
  sd.debug.read_u16(address + slot) or -1)
emit("x", selected and selected.x or 0)
emit("y", selected and selected.y or 0)
"""


ARM_SURVIVOR_INPUT_PROBE_LUA = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
_G.__sdmod_hostdeath_input_probe = {
  active = true,
  samples = {},
  limit = 2000,
}
if not _G.__sdmod_hostdeath_input_probe_registered then
  sd.events.on("runtime.tick", function(event)
    local probe = _G.__sdmod_hostdeath_input_probe
    if type(probe) ~= "table" or not probe.active then return end
    local player = sd.player and sd.player.get_state and
      sd.player.get_state() or nil
    local actor = tonumber(player and player.actor_address) or 0
    local scene = sd.world and sd.world.get_scene and sd.world.get_scene() or nil
    local gameplay = tonumber(scene and scene.id) or 0
    if actor == 0 or gameplay == 0 then return end
    local function off(name) return sd.debug.layout_offset(name) end
    local native_x = tonumber(sd.debug.read_float(
      actor + off("actor_animation_config_block"))) or 0
    local native_y = tonumber(sd.debug.read_float(
      actor + off("actor_animation_drive_parameter"))) or 0
    local gameplay_x = tonumber(sd.debug.read_float(
      gameplay + off("gameplay_local_movement_input_x"))) or 0
    local gameplay_y = tonumber(sd.debug.read_float(
      gameplay + off("gameplay_local_movement_input_y"))) or 0
    local selection = tonumber(sd.debug.read_ptr(
      actor + off("actor_animation_selection_state"))) or 0
    local control_x = selection ~= 0 and tonumber(sd.debug.read_float(
      selection + off("actor_control_brain_move_input_x"))) or 0
    local control_y = selection ~= 0 and tonumber(sd.debug.read_float(
      selection + off("actor_control_brain_move_input_y"))) or 0
    local host_life = 0
    local host_life_valid = false
    local multiplayer = sd.runtime and sd.runtime.get_multiplayer_state and
      sd.runtime.get_multiplayer_state() or nil
    for _, participant in ipairs(multiplayer and multiplayer.participants or {}) do
      if tonumber(participant.participant_id) == __HOST_ID__ then
        host_life = tonumber(participant.life_current) or 0
        host_life_valid = participant.runtime_valid == true
        break
      end
    end
    probe.samples[#probe.samples + 1] = {
      monotonic_ms = tonumber(event and event.monotonic_milliseconds) or 0,
      host_life = host_life,
      host_life_valid = host_life_valid,
      intent_x = gameplay_x,
      intent_y = gameplay_y,
      native_x = native_x,
      native_y = native_y,
      gameplay_x = gameplay_x,
      gameplay_y = gameplay_y,
      control_x = control_x,
      control_y = control_y,
      x = tonumber(player and player.x) or 0,
      y = tonumber(player and player.y) or 0,
    }
    if #probe.samples >= probe.limit then probe.active = false end
  end)
  _G.__sdmod_hostdeath_input_probe_registered = true
end
local allowance_ok, allowance_result = pcall(
  sd.input.set_native_control_allowance_frames, 1200)
emit("registered", _G.__sdmod_hostdeath_input_probe_registered)
emit("active", _G.__sdmod_hostdeath_input_probe.active)
emit("allowance_ok", allowance_ok and allowance_result == true)
"""


SURVIVOR_INPUT_STATUS_LUA = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local probe = _G.__sdmod_hostdeath_input_probe
local samples = type(probe) == "table" and probe.samples or {}
local sample = samples[#samples] or {}
emit("count", #samples)
emit("intent", math.sqrt(
  (tonumber(sample.gameplay_x) or 0)^2 +
  (tonumber(sample.gameplay_y) or 0)^2))
emit("native_vector", math.sqrt(
  (tonumber(sample.native_x) or 0)^2 +
  (tonumber(sample.native_y) or 0)^2))
emit("gameplay_input", math.sqrt(
  (tonumber(sample.gameplay_x) or 0)^2 +
  (tonumber(sample.gameplay_y) or 0)^2))
emit("control_vector", math.sqrt(
  (tonumber(sample.control_x) or 0)^2 +
  (tonumber(sample.control_y) or 0)^2))
emit("host_life", sample.host_life or 0)
emit("host_life_valid", sample.host_life_valid == true)
emit("x", sample.x or 0)
emit("y", sample.y or 0)
"""


STOP_SURVIVOR_INPUT_PROBE_LUA = r"""
local probe = _G.__sdmod_hostdeath_input_probe
if type(probe) ~= "table" then error("input probe unavailable") end
probe.active = false
local allowance_ok, allowance_result = pcall(
  sd.input.set_native_control_allowance_frames, 0)
print("count=" .. tostring(#(probe.samples or {})))
print("allowance_cleared=" ..
  tostring(allowance_ok and allowance_result == true))
"""


QUERY_SURVIVOR_INPUT_PROBE_LUA = r"""
local probe = _G.__sdmod_hostdeath_input_probe
if type(probe) ~= "table" then error("input probe unavailable") end
local first = __FIRST_SAMPLE__
local count = __SAMPLE_COUNT__
local last = math.min(#(probe.samples or {}), first + count - 1)
for index = first, last do
  local sample = probe.samples[index]
  print(table.concat({
    "I",
    tostring(sample.monotonic_ms or 0),
    string.format("%.6f", sample.host_life or 0),
    sample.host_life_valid and "1" or "0",
    string.format("%.6f", sample.intent_x or 0),
    string.format("%.6f", sample.intent_y or 0),
    string.format("%.6f", sample.native_x or 0),
    string.format("%.6f", sample.native_y or 0),
    string.format("%.6f", sample.gameplay_x or 0),
    string.format("%.6f", sample.gameplay_y or 0),
    string.format("%.6f", sample.control_x or 0),
    string.format("%.6f", sample.control_y or 0),
    string.format("%.6f", sample.x or 0),
    string.format("%.6f", sample.y or 0),
  }, "|"))
end
"""


ENEMY_CENSUS_LUA = r"""
local rows = {}
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  if actor.tracked_enemy and not actor.dead and
      (tonumber(actor.hp) or 0) > 0 then
    rows[#rows + 1] = actor
  end
end
table.sort(rows, function(left, right)
  return (tonumber(left.actor_address) or 0) <
    (tonumber(right.actor_address) or 0)
end)
print("count=" .. tostring(#rows))
for _, actor in ipairs(rows) do
  print(table.concat({
    "E",
    tostring(tonumber(actor.actor_address) or 0),
    tostring(tonumber(actor.object_type_id) or 0),
    string.format("%.6f", tonumber(actor.hp) or 0),
    string.format("%.6f", tonumber(actor.max_hp) or 0),
    string.format("%.6f", tonumber(actor.x) or 0),
    string.format("%.6f", tonumber(actor.y) or 0),
  }, "|"))
end
"""


HOST_DEATH_BOUNDARY_LUA = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local player = sd.player and sd.player.get_state and
  sd.player.get_state() or nil
local multiplayer = sd.runtime and sd.runtime.get_multiplayer_state and
  sd.runtime.get_multiplayer_state() or nil
local spectator = multiplayer and multiplayer.death_spectator or {}
emit("hp", player and player.hp or 0)
emit("max_hp", player and player.max_hp or 0)
emit("phase", spectator.phase or "")
emit("session_state", multiplayer and multiplayer.session_state or "")
"""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_census(text: str) -> list[dict[str, int | float]]:
    rows: list[dict[str, int | float]] = []
    for line in text.splitlines():
        if not line.startswith("E|"):
            continue
        parts = line.split("|")
        if len(parts) != 7:
            raise VerifyFailure(f"malformed enemy census row: {line!r}")
        rows.append(
            {
                "actor_address": int(parts[1]),
                "object_type_id": int(parts[2]),
                "hp": float(parts[3]),
                "max_hp": float(parts[4]),
                "x": float(parts[5]),
                "y": float(parts[6]),
            }
        )
    return rows


def _wait_for_host_death_boundary(
    host_pipe: str,
    *,
    timeout: float = 3.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = parse_key_values(lua(host_pipe, HOST_DEATH_BOUNDARY_LUA))
        if (
            float(last.get("hp", "inf")) <= 0.0
            and last.get("phase") == "DeathPresentation"
            and last.get("session_state") == "in-boneyard"
        ):
            return last
        time.sleep(0.02)
    raise VerifyFailure(
        "native host hit did not enter the in-run death boundary: "
        f"{last}"
    )


def _arm_continuity_probe(
    pipe_name: str,
    observation_seconds: float,
) -> dict[str, str]:
    limit = math.ceil(
        (observation_seconds + 45.0) * 1000.0 / PROBE_INTERVAL_MS
    )
    code = (
        ARM_CONTINUITY_PROBE_LUA
        .replace("__INTERVAL_MS__", str(PROBE_INTERVAL_MS))
        .replace("__SAMPLE_LIMIT__", str(limit))
    )
    values = parse_key_values(lua(pipe_name, code, timeout=10.0))
    if values.get("registered") != "true" or values.get("active") != "true":
        raise VerifyFailure(f"continuity probe failed to arm: {values}")
    return values


def _configure_continuity_enemy(
    *,
    host_pipe: str,
    client_pipe: str,
    enemy_actor_address: int,
    timeout: float = 8.0,
) -> dict[str, dict[str, str]]:
    deadline = time.monotonic() + timeout
    host: dict[str, str] = {}
    client: dict[str, str] = {}
    host_code = (
        CONFIGURE_CONTINUITY_ENEMY_LUA
        .replace("__ENEMY_ACTOR_ADDRESS__", str(enemy_actor_address))
        .replace("__ENEMY_NETWORK_ID__", "0")
    )
    while time.monotonic() < deadline:
        host = parse_key_values(lua(host_pipe, host_code))
        network_id = int(host.get("network_id", "0"))
        distance = float(host.get("distance", "inf"))
        if network_id == 0 or distance > 32.0:
            time.sleep(0.1)
            continue
        client_code = (
            CONFIGURE_CONTINUITY_ENEMY_LUA
            .replace("__ENEMY_ACTOR_ADDRESS__", "0")
            .replace("__ENEMY_NETWORK_ID__", str(network_id))
        )
        client = parse_key_values(lua(client_pipe, client_code))
        if int(client.get("actor_address", "0")) != 0:
            return {"host": host, "client": client}
        time.sleep(0.1)
    raise VerifyFailure(
        "post-death stock enemy did not resolve to both continuity probes: "
        f"host={host} client={client}"
    )


def _wait_for_postdeath_enemy_boundary(
    host_pipe: str,
    enemy_actor_address: int,
    *,
    timeout: float = 5.0,
) -> dict[str, Any]:
    code = POSTDEATH_ENEMY_BOUNDARY_LUA.replace(
        "__ENEMY_ACTOR_ADDRESS__",
        str(enemy_actor_address),
    )
    deadline = time.monotonic() + timeout
    attempts: list[dict[str, str]] = []
    while time.monotonic() < deadline:
        values = parse_key_values(lua(host_pipe, code))
        attempts.append(values)
        if (
            values.get("available") == "true"
            and int(values.get("pending_initialize", "-1")) == 0
            and int(values.get("selector_pending", "-1")) == 0
            and int(values.get("target_actor", "0")) != 0
        ):
            return {
                "completed": True,
                "attempt_count": len(attempts),
                "first": attempts[0],
                "final": values,
            }
        time.sleep(0.02)
    raise VerifyFailure(
        "post-death authority enemy did not complete native target/chase "
        f"initialization: actor={enemy_actor_address} attempts={attempts[-8:]}"
    )


def _parse_continuity_samples(text: str) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.startswith("S|"):
            continue
        parts = line.split("|")
        if len(parts) != 33:
            raise VerifyFailure(f"malformed continuity sample: {line!r}")
        samples.append(
            {
                "monotonic_ms": int(parts[1]),
                "received_ms": int(parts[2]),
                "sequence": int(parts[3]),
                "player_hp": float(parts[4]),
                "network_actor_id": int(parts[5]),
                "authority_x": float(parts[6]),
                "authority_y": float(parts[7]),
                "authority_hp": float(parts[8]),
                "authority_max_hp": float(parts[9]),
                "target": int(parts[10]),
                "local_address": int(parts[11]),
                "local_type": int(parts[12]),
                "local_x": float(parts[13]),
                "local_y": float(parts[14]),
                "local_hp": float(parts[15]),
                "local_max_hp": float(parts[16]),
                "pending_initialize": int(parts[17]),
                "selector_pending": int(parts[18]),
                "binding_matched": int(parts[19]),
                "binding_parked": int(parts[20]),
                "binding_removed": int(parts[21]),
                "authority_participant_id": int(parts[22]),
                "session_state": parts[23],
                "run_nonce": int(parts[24]),
                "loading_run_nonce": int(parts[25]),
                "loading_release_nonce": int(parts[26]),
                "shared_pause_active": int(parts[27]),
                "teardown_active": int(parts[28]),
                "game_over_command_epoch": int(parts[29]),
                "game_over_accepted_epoch": int(parts[30]),
                "game_over_pending_dispatch": int(parts[31]),
                "game_over_dispatch_count": int(parts[32]),
            }
        )
    return samples


def _read_continuity_probe(pipe_name: str) -> list[dict[str, Any]]:
    status = parse_key_values(
        lua(pipe_name, STOP_CONTINUITY_PROBE_LUA, timeout=10.0)
    )
    count = int(status.get("count", "0"))
    samples: list[dict[str, Any]] = []
    for first in range(1, count + 1, 64):
        code = (
            QUERY_CONTINUITY_PROBE_LUA
            .replace("__FIRST_SAMPLE__", str(first))
            .replace("__SAMPLE_COUNT__", "64")
        )
        samples.extend(
            _parse_continuity_samples(lua(pipe_name, code, timeout=15.0))
        )
    return samples


def _arm_survivor_input_probe(client_pipe: str) -> dict[str, str]:
    code = ARM_SURVIVOR_INPUT_PROBE_LUA.replace(
        "__HOST_ID__",
        str(HOST_ID),
    )
    values = parse_key_values(lua(client_pipe, code, timeout=10.0))
    if (
        values.get("registered") != "true"
        or values.get("active") != "true"
        or values.get("allowance_ok") != "true"
    ):
        raise VerifyFailure(
            f"client B input probe failed to arm: {values}"
        )
    return values


def _wait_for_real_input(
    client_pipe: str,
    key_future: concurrent.futures.Future[str],
    *,
    timeout: float = 5.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        if key_future.done():
            exception = key_future.exception()
            if exception is not None:
                raise VerifyFailure(
                    f"real client B key helper failed before input: {exception}"
                )
        last = parse_key_values(
            lua(client_pipe, SURVIVOR_INPUT_STATUS_LUA, timeout=8.0)
        )
        if (
            float(last.get("intent", "0")) > 0.01
            and float(last.get("native_vector", "0")) > 0.01
            and float(last.get("gameplay_input", "0")) > 0.01
            and last.get("host_life_valid") == "true"
            and float(last.get("host_life", "0")) > 0.0
        ):
            return last
        time.sleep(0.02)
    raise VerifyFailure(
        "real held movement input did not reach intent and native-vector "
        f"lanes before host death: {last}"
    )


def _parse_input_samples(text: str) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.startswith("I|"):
            continue
        parts = line.split("|")
        if len(parts) != 14:
            raise VerifyFailure(f"malformed survivor-input sample: {line!r}")
        samples.append(
            {
                "monotonic_ms": int(parts[1]),
                "host_life": float(parts[2]),
                "host_life_valid": int(parts[3]),
                "intent_x": float(parts[4]),
                "intent_y": float(parts[5]),
                "native_x": float(parts[6]),
                "native_y": float(parts[7]),
                "gameplay_x": float(parts[8]),
                "gameplay_y": float(parts[9]),
                "control_x": float(parts[10]),
                "control_y": float(parts[11]),
                "x": float(parts[12]),
                "y": float(parts[13]),
            }
        )
    return samples


def _read_survivor_input_probe(client_pipe: str) -> list[dict[str, Any]]:
    status = parse_key_values(
        lua(client_pipe, STOP_SURVIVOR_INPUT_PROBE_LUA, timeout=10.0)
    )
    if status.get("allowance_cleared") != "true":
        raise VerifyFailure(
            f"client B native input allowance did not clear: {status}"
        )
    count = int(status.get("count", "0"))
    samples: list[dict[str, Any]] = []
    for first in range(1, count + 1, 96):
        code = (
            QUERY_SURVIVOR_INPUT_PROBE_LUA
            .replace("__FIRST_SAMPLE__", str(first))
            .replace("__SAMPLE_COUNT__", "96")
        )
        samples.extend(_parse_input_samples(lua(client_pipe, code)))
    return samples


def _vector_magnitude(sample: dict[str, Any], prefix: str) -> float:
    return math.hypot(
        float(sample[f"{prefix}_x"]),
        float(sample[f"{prefix}_y"]),
    )


def analyze_survivor_input(samples: list[dict[str, Any]]) -> dict[str, Any]:
    positive_seen = False
    death_ms: int | None = None
    for sample in samples:
        if not int(sample["host_life_valid"]):
            continue
        if float(sample["host_life"]) > 0.0:
            positive_seen = True
        elif positive_seen:
            death_ms = int(sample["monotonic_ms"])
            break
    if death_ms is None:
        return {
            "passed": False,
            "failure": "client B input probe did not observe host life crossing zero",
            "sample_count": len(samples),
        }

    before = [
        sample
        for sample in samples
        if death_ms - 500 <= int(sample["monotonic_ms"]) < death_ms
    ]
    after = [
        sample
        for sample in samples
        if death_ms <= int(sample["monotonic_ms"]) <= death_ms + 750
    ]
    input_samples = [
        sample
        for sample in samples
        if _vector_magnitude(sample, "intent") > 0.01
    ]
    if input_samples:
        origin = (
            float(input_samples[0]["x"]),
            float(input_samples[0]["y"]),
        )
        maximum_displacement = max(
            math.hypot(
                float(sample["x"]) - origin[0],
                float(sample["y"]) - origin[1],
            )
            for sample in input_samples
        )
    else:
        maximum_displacement = 0.0

    def window_has(
        window: list[dict[str, Any]],
        prefix: str,
    ) -> bool:
        return any(_vector_magnitude(sample, prefix) > 0.01 for sample in window)

    analysis = {
        "sample_count": len(samples),
        "death_monotonic_ms": death_ms,
        "before_window_sample_count": len(before),
        "after_window_sample_count": len(after),
        "intent_before_death": window_has(before, "intent"),
        "intent_after_death": window_has(after, "intent"),
        "native_vector_before_death": window_has(before, "native"),
        "native_vector_after_death": window_has(after, "native"),
        "gameplay_input_before_death": window_has(before, "gameplay"),
        "gameplay_input_after_death": window_has(after, "gameplay"),
        "control_vector_before_death": window_has(before, "control"),
        "control_vector_after_death": window_has(after, "control"),
        "peak_intent": max(
            (_vector_magnitude(sample, "intent") for sample in samples),
            default=0.0,
        ),
        "peak_native_vector": max(
            (_vector_magnitude(sample, "native") for sample in samples),
            default=0.0,
        ),
        "peak_gameplay_input": max(
            (_vector_magnitude(sample, "gameplay") for sample in samples),
            default=0.0,
        ),
        "maximum_displacement": maximum_displacement,
    }
    analysis["passed"] = bool(
        before
        and after
        and analysis["intent_before_death"]
        and analysis["intent_after_death"]
        and analysis["native_vector_before_death"]
        and analysis["native_vector_after_death"]
        and analysis["gameplay_input_before_death"]
        and analysis["gameplay_input_after_death"]
        and maximum_displacement > MINIMUM_CLIENT_B_DISPLACEMENT
    )
    return analysis


def _negative_hp_edges(
    samples: list[dict[str, Any]],
    *,
    start_ms: int,
    end_ms: int | None = None,
) -> list[dict[str, float]]:
    edges: list[dict[str, float]] = []
    previous: dict[str, Any] | None = None
    for sample in samples:
        timestamp = int(sample["monotonic_ms"])
        if timestamp < start_ms:
            continue
        if end_ms is not None and timestamp > end_ms:
            continue
        if previous is not None:
            damage = float(previous["player_hp"]) - float(sample["player_hp"])
            if damage > 0.01:
                edges.append(
                    {
                        "monotonic_ms": float(timestamp),
                        "damage": damage,
                    }
                )
        previous = sample
    return edges


def _edge_cadence(edges: list[dict[str, float]]) -> dict[str, float | int]:
    intervals = [
        right["monotonic_ms"] - left["monotonic_ms"]
        for left, right in zip(edges, edges[1:])
    ]
    return {
        "edge_count": len(edges),
        "interval_count": len(intervals),
        "mean_interval_ms": (
            statistics.fmean(intervals) if intervals else math.inf
        ),
        "maximum_interval_ms": max(intervals, default=math.inf),
        "mean_damage": (
            statistics.fmean(edge["damage"] for edge in edges)
            if edges else 0.0
        ),
    }


def _terminal_damage_segment_coverage(
    edges: list[dict[str, float]],
    *,
    start_ms: int,
    end_ms: int,
    segment_count: int = 3,
) -> dict[str, Any]:
    duration = max(end_ms - start_ms, 1)
    covered: set[int] = set()
    for edge in edges:
        offset = int(edge["monotonic_ms"]) - start_ms
        if 0 <= offset <= duration:
            covered.add(min(segment_count - 1, offset * segment_count // duration))
    return {
        "segment_count": segment_count,
        "covered_segments": sorted(covered),
        "covered_segment_count": len(covered),
        "complete": len(covered) == segment_count,
    }


def _movement_summary(
    samples: list[dict[str, Any]],
    *,
    start_ms: int,
    x_key: str,
    y_key: str,
) -> dict[str, float | int]:
    points = [
        (
            int(sample["monotonic_ms"]),
            float(sample[x_key]),
            float(sample[y_key]),
        )
        for sample in samples
        if int(sample["monotonic_ms"]) >= start_ms
        and int(sample["local_address"]) != 0
    ]
    steps = [
        math.hypot(right[1] - left[1], right[2] - left[2])
        for left, right in zip(points, points[1:])
    ]
    moving_steps = [step for step in steps if step > 0.25]
    duration_ms = points[-1][0] - points[0][0] if len(points) > 1 else 0
    if points:
        origin_x, origin_y = points[0][1], points[0][2]
        maximum_displacement = max(
            math.hypot(point[1] - origin_x, point[2] - origin_y)
            for point in points
        )
    else:
        maximum_displacement = 0.0
    return {
        "sample_count": len(points),
        "step_count": len(steps),
        "moving_step_count": len(moving_steps),
        "duration_ms": duration_ms,
        "path_distance": sum(steps),
        "maximum_displacement": maximum_displacement,
        "maximum_step": max(steps, default=0.0),
    }


def _snapshot_cadence(
    samples: list[dict[str, Any]],
    *,
    start_ms: int,
) -> dict[str, float | int]:
    arrivals: list[int] = []
    previous = 0
    for sample in samples:
        if int(sample["monotonic_ms"]) < start_ms:
            continue
        received_ms = int(sample["received_ms"])
        if received_ms > 0 and received_ms != previous:
            arrivals.append(received_ms)
            previous = received_ms
    gaps = [
        float(right - left)
        for left, right in zip(arrivals, arrivals[1:])
        if right > left
    ]
    return {
        "arrival_count": len(arrivals),
        "gap_count": len(gaps),
        "maximum_gap_ms": max(gaps, default=math.inf),
        "mean_gap_ms": statistics.fmean(gaps) if gaps else math.inf,
    }


def _client_binding_summary(
    samples: list[dict[str, Any]],
) -> dict[str, float | int]:
    def is_bound(sample: dict[str, Any]) -> bool:
        return (
            int(sample["binding_matched"]) == 1
            and int(sample["binding_parked"]) == 0
            and int(sample["binding_removed"]) == 0
        )

    tracked = [
        sample
        for sample in samples
        if int(sample["network_actor_id"]) != 0
        and int(sample["local_address"]) != 0
    ]
    bound = [
        sample
        for sample in tracked
        if is_bound(sample)
    ]
    unbound = [sample for sample in tracked if not is_bound(sample)]
    return {
        "tracked_sample_count": len(tracked),
        "bound_sample_count": len(bound),
        "unbound_sample_count": len(unbound),
        "bound_ratio": len(bound) / len(tracked) if tracked else 0.0,
        "simulation_eligible_unbound_sample_count": sum(
            int(sample["pending_initialize"]) == 0
            for sample in unbound
        ),
    }


def _state_regression_summary(
    samples: list[dict[str, Any]],
    *,
    death_ms: int,
) -> dict[str, Any]:
    post = [
        sample
        for sample in samples
        if int(sample["monotonic_ms"]) >= death_ms + 1000
    ]
    baseline_candidates = [
        sample
        for sample in samples
        if int(sample["monotonic_ms"]) < death_ms
    ]
    baseline = baseline_candidates[-1] if baseline_candidates else None
    barrier_fields = (
        "run_nonce",
        "loading_run_nonce",
        "loading_release_nonce",
    )
    baseline_barrier = (
        tuple(int(baseline[field]) for field in barrier_fields)
        if baseline is not None else None
    )
    barrier_restarts = [
        tuple(int(sample[field]) for field in barrier_fields)
        for sample in post
        if baseline_barrier is not None
        and tuple(int(sample[field]) for field in barrier_fields)
        != baseline_barrier
    ]
    return {
        "sample_count": len(post),
        "baseline_barrier": baseline_barrier,
        "barrier_restart_count": len(barrier_restarts),
        "authority_change_count": sum(
            int(sample["authority_participant_id"]) != HOST_ID
            for sample in post
        ),
        "shared_pause_count": sum(
            bool(sample["shared_pause_active"]) for sample in post
        ),
        "teardown_count": sum(
            bool(sample["teardown_active"]) for sample in post
        ),
        "game_over_armed_count": sum(
            int(sample["game_over_command_epoch"]) != 0
            or int(sample["game_over_accepted_epoch"]) != 0
            or bool(sample["game_over_pending_dispatch"])
            or int(sample["game_over_dispatch_count"]) != 0
            for sample in post
        ),
        "wrong_session_state_count": sum(
            sample["session_state"] != "in-boneyard" for sample in post
        ),
    }


def analyze_continuity(
    host_samples: list[dict[str, Any]],
    client_samples: list[dict[str, Any]],
) -> dict[str, Any]:
    death_samples = [
        sample
        for sample in host_samples
        if float(sample["player_hp"]) <= 0.0
    ]
    if not death_samples:
        raise VerifyFailure("host continuity probe never observed terminal HP")
    death_ms = int(death_samples[0]["monotonic_ms"])
    tracked_start_ms = max(
        (
            min(
                int(sample["monotonic_ms"])
                for sample in samples
                if int(sample["network_actor_id"]) != 0
            )
            for samples in (host_samples, client_samples)
            if any(int(sample["network_actor_id"]) != 0 for sample in samples)
        ),
        default=death_ms,
    )
    final_ms = max(
        (
            int(sample["monotonic_ms"])
            for sample in host_samples + client_samples
        ),
        default=death_ms,
    )
    terminal_start_ms = max(death_ms, final_ms - 60_000)
    target_samples = [
        int(sample["target"])
        for sample in client_samples
        if int(sample["monotonic_ms"]) >= tracked_start_ms
        and int(sample["network_actor_id"]) != 0
        and int(sample["target"]) != 0
    ]
    terminal_damage_edges = _negative_hp_edges(
        client_samples,
        start_ms=terminal_start_ms,
    )
    host_tracked = [
        sample
        for sample in host_samples
        if int(sample["network_actor_id"]) != 0
        and int(sample["local_address"]) != 0
    ]
    client_tracked = [
        sample
        for sample in client_samples
        if int(sample["network_actor_id"]) != 0
        and int(sample["local_address"]) != 0
    ]
    clone_errors = [
        math.hypot(
            float(sample["local_x"]) - float(sample["authority_x"]),
            float(sample["local_y"]) - float(sample["authority_y"]),
        )
        for sample in client_tracked
    ]
    client_binding = _client_binding_summary(client_samples)
    analysis = {
        "death_monotonic_ms": death_ms,
        "tracked_enemy_start_ms": tracked_start_ms,
        "terminal_window_start_ms": terminal_start_ms,
        "final_sample_ms": final_ms,
        "host_sample_count": len(host_samples),
        "client_sample_count": len(client_samples),
        "host_authority_movement": _movement_summary(
            host_samples,
            start_ms=tracked_start_ms,
            x_key="local_x",
            y_key="local_y",
        ),
        "client_b_clone_movement": _movement_summary(
            client_samples,
            start_ms=tracked_start_ms,
            x_key="local_x",
            y_key="local_y",
        ),
        "client_snapshot_cadence": _snapshot_cadence(
            client_samples,
            start_ms=tracked_start_ms,
        ),
        "post_death_damage_edges": _negative_hp_edges(
            client_samples,
            start_ms=death_ms + 1000,
        ),
        "terminal_damage_edges": terminal_damage_edges,
        "terminal_damage_coverage": _terminal_damage_segment_coverage(
            terminal_damage_edges,
            start_ms=terminal_start_ms,
            end_ms=final_ms,
        ),
        "post_death_target_sample_count": len(target_samples),
        "client_b_target_count": sum(
            target == CLIENT_ID for target in target_samples
        ),
        "wrong_target_count": sum(
            target != CLIENT_ID for target in target_samples
        ),
        "host_initialization_complete_sample_count": sum(
            int(sample["pending_initialize"]) == 0
            and int(sample["selector_pending"]) == 0
            for sample in host_tracked
        ),
        "host_final_pending_initialize": (
            int(host_tracked[-1]["pending_initialize"])
            if host_tracked else -1
        ),
        "host_final_selector_pending": (
            int(host_tracked[-1]["selector_pending"])
            if host_tracked else -1
        ),
        "client_bound_replica_sample_count":
            client_binding["bound_sample_count"],
        "client_tracked_sample_count":
            client_binding["tracked_sample_count"],
        "client_unbound_replica_sample_count":
            client_binding["unbound_sample_count"],
        "client_bound_replica_ratio": client_binding["bound_ratio"],
        "client_simulation_eligible_unbound_sample_count":
            client_binding[
                "simulation_eligible_unbound_sample_count"
            ],
        "client_clone_maximum_snapshot_error": max(
            clone_errors,
            default=math.inf,
        ),
        "host_state_regressions": _state_regression_summary(
            host_samples,
            death_ms=death_ms,
        ),
        "client_state_regressions": _state_regression_summary(
            client_samples,
            death_ms=death_ms,
        ),
    }
    analysis["retarget_success_ratio"] = (
        analysis["client_b_target_count"] / len(target_samples)
        if target_samples else 0.0
    )
    analysis["post_death_attack_cadence"] = _edge_cadence(
        analysis["post_death_damage_edges"]
    )
    analysis["terminal_attack_cadence"] = _edge_cadence(
        terminal_damage_edges
    )
    return analysis


def _log_metrics(log_path: Path, death_timestamp: str) -> dict[str, Any]:
    text = log_path.read_text(encoding="utf-8", errors="replace")
    after = text
    if death_timestamp:
        marker = f"[{death_timestamp}]"
        position = text.find(marker)
        if position >= 0:
            after = text[position:]
    gaps = [
        int(value)
        for value in re.findall(
            r"Multiplayer app-thread gameplay tick gap\. gap_ms=(\d+)",
            after,
        )
    ]
    return {
        "tick_gap_count": len(gaps),
        "maximum_tick_gap_ms": max(gaps, default=0),
        "catch_up_count": after.count(
            "client enemy pool catch-up"
        ),
        "manual_spawn_request_count": after.count(
            "manual run enemy spawn: queued stock-spawner request."
        ),
        "session_teardown_count": after.count(
            "Canonical session teardown started."
        ),
        "actor_world_hold_count": after.count(
            "ActorWorld_Tick held for shared simulation control."
        ),
        "snapshot_stall_count": after.count(
            "holding last authoritative actor state during transient snapshot stall"
        ),
    }


def _remote_death_timestamp(client_log: Path) -> str:
    text = client_log.read_text(encoding="utf-8", errors="replace")
    matches = re.findall(
        r"\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3})\] "
        r"\[bots\] native remote death epoch started\. "
        rf"participant_id={HOST_ID}\b",
        text,
    )
    return matches[-1] if matches else ""


def _local_death_timestamp(host_log: Path) -> str:
    text = host_log.read_text(encoding="utf-8", errors="replace")
    matches = re.findall(
        r"\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3})\] "
        rf"Multiplayer death presentation started\. participant_id={HOST_ID}\b",
        text,
    )
    return matches[-1] if matches else ""


def _preserve_logs(
    artifact_root: Path,
    host_log: Path,
    client_log: Path,
) -> dict[str, str]:
    preserved: dict[str, str] = {}
    for role, source in (("host", host_log), ("client-b", client_log)):
        if not source.is_file():
            continue
        destination = artifact_root / f"{role}-solomondarkmodloader.log"
        shutil.copy2(source, destination)
        preserved[role] = str(destination)
    return preserved


def _analysis_failures(
    continuity: dict[str, Any],
    survivor_input: dict[str, Any],
    log_metrics: dict[str, dict[str, Any]],
) -> list[str]:
    failures: list[str] = []
    if continuity["post_death_target_sample_count"] < 5:
        failures.append("post-death enemy target evidence was too short")
    if continuity["retarget_success_ratio"] != 1.0:
        failures.append("post-death enemy did not target only client B")
    if (
        continuity["host_authority_movement"]["maximum_displacement"]
        <= MINIMUM_ENEMY_DISPLACEMENT
    ):
        failures.append("post-death authority enemy displaced at most 16 units")
    if (
        continuity["client_b_clone_movement"]["maximum_displacement"]
        <= MINIMUM_ENEMY_DISPLACEMENT
    ):
        failures.append("client B's replicated enemy displaced at most 16 units")
    if continuity["host_initialization_complete_sample_count"] < 3:
        failures.append("post-death authority enemy did not finish initialization")
    if (
        continuity["host_final_pending_initialize"] != 0
        or continuity["host_final_selector_pending"] != 0
    ):
        failures.append("post-death authority enemy ended with a pending native gate")
    if not continuity["post_death_damage_edges"]:
        failures.append("the organic wave produced no post-host-death damage")
    if not continuity["terminal_damage_coverage"]["complete"]:
        failures.append(
            "the organic wave did not damage client B throughout all thirds "
            "of the terminal minute"
        )
    if continuity["client_simulation_eligible_unbound_sample_count"] != 0:
        failures.append(
            "client B exposed an initialization-complete enemy outside "
            "replica binding"
        )
    for role in ("host", "client"):
        state = continuity[f"{role}_state_regressions"]
        for key in (
            "barrier_restart_count",
            "authority_change_count",
            "shared_pause_count",
            "teardown_count",
            "game_over_armed_count",
            "wrong_session_state_count",
        ):
            if state[key] != 0:
                failures.append(f"{role} death-window regression: {key}={state[key]}")
    if not survivor_input.get("passed"):
        failures.append(
            "client B real movement input did not preserve "
            "intent -> native vector -> displacement across host death"
        )
    if log_metrics["client"]["catch_up_count"] != 0:
        failures.append("client B enemy pool catch-up did not converge")
    if log_metrics["client"]["snapshot_stall_count"] != 0:
        failures.append("client B held stale enemy state during a snapshot stall")
    if log_metrics["host"]["manual_spawn_request_count"] != 0:
        failures.append("organic host run used the manual enemy spawner")
    for role in ("host", "client"):
        if log_metrics[role]["session_teardown_count"] != 0:
            failures.append(
                f"{role} armed canonical session teardown after host death"
            )
    return failures


def run_live_verification(
    *,
    instance_prefix: str,
    ports: list[int],
    game_directory: Path,
    launcher_path: Path | None,
    artifact_root: Path,
    observation_seconds: float,
    measure_only: bool,
) -> dict[str, Any]:
    if observation_seconds < MINIMUM_OBSERVATION_SECONDS:
        raise VerifyFailure(
            "host-death continuity requires at least one terminal minute: "
            f"observation_seconds={observation_seconds}"
        )
    artifact_root.mkdir(parents=True, exist_ok=True)
    retail_wave = game_directory / "data" / "wave.txt"
    if not retail_wave.is_file():
        raise VerifyFailure(f"retail wave schedule is missing: {retail_wave}")
    effective_wave = artifact_root / "effective-retail-wave.txt"
    shutil.copy2(retail_wave, effective_wave)
    wave_lines = [
        line
        for line in effective_wave.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()
        if line.strip() and not line.lstrip().startswith(("#", ";"))
    ]
    wave_schedule = {
        "source_path": str(retail_wave.resolve()),
        "effective_path": str(effective_wave.resolve()),
        "sha256": _sha256(effective_wave),
        "nonempty_record_count": len(wave_lines),
        "unmodified_retail_schedule": True,
    }
    launch = launch_pair(
        host_preset="map_create_fire_mind_hub",
        client_preset="map_create_air_mind_hub",
        temporary_host_profile=True,
        tile_windows=False,
        test_blank_boneyard=False,
        test_wave_override=effective_wave,
        use_sandbox_preset_flow=True,
        kill_existing=False,
        instance_prefix=instance_prefix,
        host_port=ports[0],
        client_port=ports[1],
        game_directory=game_directory,
        launcher_path=launcher_path,
        exact_mod_id=ACCEPTANCE_MOD_ID,
        enable_audio=False,
    )
    result: dict[str, Any] = {
        "ok": False,
        "measure_only": measure_only,
        "instance_prefix": instance_prefix,
        "ports": ports,
        "observation_seconds": observation_seconds,
        "wave_schedule": wave_schedule,
        "organic_constraints": {
            "enemy_isolation": False,
            "forced_target": False,
            "forced_arena": False,
            "scripted_teleport": False,
            "client_enemy_simulation": False,
        },
        "launch": launch,
        "process_ids": game_process_ids(launch),
    }
    if launch.get("audioDisabled") is not True:
        result["cleanup"] = stop_exact_game_processes(launch)
        raise VerifyFailure(f"pair audio was not disabled: {launch}")
    if len(result["process_ids"]) != 2:
        result["cleanup"] = stop_exact_game_processes(launch)
        raise VerifyFailure(f"pair launch omitted exact process IDs: {launch}")

    host_pipe = str(launch["hostLuaPipe"])
    client_pipe = str(launch["clientLuaPipe"])
    host_log = _launch_log_path(launch, "hostLog")
    client_log = _launch_log_path(launch, "clientLog")
    client_process_id = int(launch["clientProcessId"])
    pipes = [host_pipe, client_pipe]
    death_traces_armed = False
    input_probe_armed = False
    input_probe_read = False
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    key_future: concurrent.futures.Future[str] | None = None
    try:
        _disable_companion_bots(pipes)
        _start_testrun_when_ready(host_pipe)
        wait_for_scene(host_pipe, "testrun", 45.0)
        wait_for_scene(client_pipe, "testrun", 45.0)
        result["relationships"] = {
            "host_observes_client_b": wait_for_remote(
                host_pipe,
                CLIENT_ID,
                CLIENT_NAME,
                "testrun",
                45.0,
            ),
            "client_b_observes_host": wait_for_remote(
                client_pipe,
                HOST_ID,
                HOST_NAME,
                "testrun",
                45.0,
            ),
        }
        result["host_pre_wave_vitals"] = set_local_player_vitals(
            host_pipe,
            SURVIVOR_HP,
            SURVIVOR_HP,
        )
        result["client_b_vitals"] = set_local_player_vitals(
            client_pipe,
            SURVIVOR_HP,
            SURVIVOR_HP,
        )
        result["probe_arm"] = {
            "host": _arm_continuity_probe(host_pipe, observation_seconds),
            "client_b": _arm_continuity_probe(
                client_pipe,
                observation_seconds,
            ),
        }
        result["death_traces_armed"] = _arm_death_traces(pipes)
        death_traces_armed = True

        before_wave = {
            int(actor["actor_address"])
            for actor in _query_live_enemies(host_pipe)
        }
        result["wave_start"] = _start_waves(host_pipe)
        result["first_native_wave_enemy"] = _wait_for_new_wave_enemy(
            host_pipe,
            pre_wave_actor_addresses=before_wave,
        )
        predeath_census = _parse_census(lua(host_pipe, ENEMY_CENSUS_LUA))
        if not predeath_census:
            raise VerifyFailure(
                "retail wave had no live enemies before host death"
            )
        result["predeath_census"] = predeath_census

        result["client_b_input_probe_arm"] = _arm_survivor_input_probe(
            client_pipe
        )
        input_probe_armed = True
        key_future = executor.submit(
            hold_real_key,
            client_process_id,
            REAL_INPUT_KEY,
            REAL_INPUT_HOLD_MS,
            REAL_INPUT_HOLD_MS / 1000.0 + 15.0,
        )
        result["client_b_input_before_death"] = _wait_for_real_input(
            client_pipe,
            key_future,
        )
        result["host_armed"] = set_local_player_vitals(
            host_pipe,
            HOST_ARMING_HP,
            HOST_MAX_HP,
        )
        death_requested_at = time.monotonic()
        result["host_native_lethal_hit"] = invoke_native_magic_hit_trial(
            host_pipe,
            projectile_damage=0.0,
            magic_damage=1000.0,
            attempts=8,
            label="organic host-death wave continuity",
            timeout=8.0,
            target_participant_id=0,
        )
        result["host_death_requested_monotonic_seconds"] = death_requested_at
        result["host_death_boundary"] = _wait_for_host_death_boundary(
            host_pipe
        )
        death_boundary_census = _parse_census(
            lua(host_pipe, ENEMY_CENSUS_LUA)
        )
        result["death_boundary_census"] = death_boundary_census
        death_boundary_addresses = {
            int(actor["actor_address"]) for actor in death_boundary_census
        }

        postdeath_enemy = _wait_for_new_wave_enemy(
            host_pipe,
            pre_wave_actor_addresses=death_boundary_addresses,
            timeout=12.0,
        )
        if int(postdeath_enemy["actor_address"]) in death_boundary_addresses:
            raise VerifyFailure(
                "selected enemy existed at the confirmed host-death "
                f"boundary: {postdeath_enemy}"
            )
        result["postdeath_native_wave_enemy"] = postdeath_enemy
        result["postdeath_enemy_boundary"] = (
            _wait_for_postdeath_enemy_boundary(
                host_pipe,
                int(postdeath_enemy["actor_address"]),
            )
        )
        result["probe_enemy"] = _configure_continuity_enemy(
            host_pipe=host_pipe,
            client_pipe=client_pipe,
            enemy_actor_address=int(postdeath_enemy["actor_address"]),
        )

        if key_future is None:
            raise VerifyFailure("real client B input future was not started")
        result["client_b_key_helper_output"] = key_future.result(
            timeout=REAL_INPUT_HOLD_MS / 1000.0 + 15.0
        )
        input_samples = _read_survivor_input_probe(client_pipe)
        input_probe_read = True
        input_probe_armed = False
        result["client_b_input_samples"] = input_samples
        result["client_b_input_analysis"] = analyze_survivor_input(
            input_samples
        )
        result["early_screenshots"] = {
            "host": capture_game_backbuffer(
                host_pipe,
                artifact_root / "host-post-death-wave-early.png",
            ),
            "client_b": capture_game_backbuffer(
                client_pipe,
                artifact_root / "client-b-post-death-wave-early.png",
            ),
        }

        observation_started = time.monotonic()
        while time.monotonic() - observation_started < observation_seconds:
            time.sleep(0.25)
        result["postdeath_census"] = _parse_census(
            lua(host_pipe, ENEMY_CENSUS_LUA)
        )
        result["terminal_screenshots"] = {
            "host": capture_game_backbuffer(
                host_pipe,
                artifact_root / "host-post-death-terminal.png",
            ),
            "client_b": capture_game_backbuffer(
                client_pipe,
                artifact_root / "client-b-post-death-terminal.png",
            ),
        }
        host_samples = _read_continuity_probe(host_pipe)
        client_samples = _read_continuity_probe(client_pipe)
        result["probe_samples"] = {
            "host": host_samples,
            "client_b": client_samples,
        }
        result["analysis"] = analyze_continuity(
            host_samples,
            client_samples,
        )
        remote_death_timestamp = _remote_death_timestamp(client_log)
        local_death_timestamp = _local_death_timestamp(host_log)
        result["death_timestamps"] = {
            "host_local": local_death_timestamp,
            "client_b_remote": remote_death_timestamp,
        }
        result["log_metrics"] = {
            "host": _log_metrics(host_log, local_death_timestamp),
            "client": _log_metrics(client_log, remote_death_timestamp),
        }
        result["failures"] = _analysis_failures(
            result["analysis"],
            result["client_b_input_analysis"],
            result["log_metrics"],
        )
        result["movement_symptom_reproduced"] = not bool(
            result["client_b_input_analysis"].get("passed")
        )
        result["ok"] = measure_only or not result["failures"]
        return result
    except Exception as exc:
        result["error"] = str(exc)
        result["error_type"] = type(exc).__name__
        result["traceback"] = traceback.format_exc()
        raise HostDeathContinuityFailure(str(exc), result) from exc
    finally:
        if input_probe_armed and not input_probe_read:
            try:
                result["client_b_input_cleanup_samples"] = (
                    _read_survivor_input_probe(client_pipe)
                )
            except Exception as exc:  # noqa: BLE001 - cleanup evidence.
                result["client_b_input_cleanup_error"] = str(exc)
        executor.shutdown(wait=True, cancel_futures=False)
        if death_traces_armed:
            try:
                result["death_traces_disarmed"] = _disarm_death_traces(pipes)
            except Exception as exc:  # noqa: BLE001 - cleanup evidence.
                result["death_trace_cleanup_error"] = str(exc)
        try:
            result["preserved_logs"] = _preserve_logs(
                artifact_root,
                host_log,
                client_log,
            )
        except Exception as exc:  # noqa: BLE001 - evidence preservation.
            result["log_preservation_error"] = str(exc)
        result["cleanup"] = stop_exact_game_processes(launch)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance-prefix", required=True)
    parser.add_argument("--host-port", type=int, required=True)
    parser.add_argument("--client-port", type=int, required=True)
    parser.add_argument("--game-dir", type=Path, required=True)
    parser.add_argument("--launcher-path", type=Path)
    parser.add_argument("--artifact-root", type=Path, default=ARTIFACT_ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument(
        "--observation-seconds",
        type=float,
        default=DEFAULT_OBSERVATION_SECONDS,
    )
    parser.add_argument("--measure-only", action="store_true")
    args = parser.parse_args()
    result: dict[str, Any] = {
        "ok": False,
        "instance_prefix": args.instance_prefix,
    }
    exit_code = 1
    try:
        result = run_live_verification(
            instance_prefix=args.instance_prefix,
            ports=[args.host_port, args.client_port],
            game_directory=args.game_dir,
            launcher_path=args.launcher_path,
            artifact_root=args.artifact_root,
            observation_seconds=args.observation_seconds,
            measure_only=args.measure_only,
        )
        exit_code = 0 if result["ok"] else 1
    except Exception as exc:  # noqa: BLE001 - retain exact live evidence.
        evidence = getattr(exc, "evidence", None)
        if isinstance(evidence, dict):
            result = evidence
        result.setdefault("error", str(exc))
        result.setdefault("error_type", type(exc).__name__)
        result.setdefault("traceback", traceback.format_exc())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "ok": result.get("ok", False),
                "failures": result.get("failures"),
                "error": result.get("error"),
                "output": str(args.output),
                "artifact_root": str(args.artifact_root),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
