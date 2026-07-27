#!/usr/bin/env python3
"""Verify host-authoritative native minions in an isolated loopback pair."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import multiplayer_frame_capture as frame_capture
import multiplayer_secondary_behavior_harness as secondary
import multiplayer_defense_behavior_harness as defense
import steam_friend_behavior_context as behavior_context
import verify_local_multiplayer_sync as local_sync
import verify_multiplayer_focus_behavior_sync as focus
import verify_multiplayer_primary_kill_stress as primary
import verify_multiplayer_replicated_audio_events as process_guard
import verify_multiplayer_rush_behavior_sync as rush
from steam_friend_active_pair import CLIENT_ENDPOINT, HOST_ENDPOINT
from verify_real_input_spell_cast_sync import read_log


ROOT = Path(__file__).resolve().parent.parent
ORIGINAL_LUA = local_sync.lua
GAME_DIRECTORY = Path(
    "/mnt/c/Users/User/Documents/GitHub/SB Modding/"
    "Solomon Dark/SolomonDarkAbandonware"
)
RUNTIME_ROOT = (ROOT / "runtime").resolve()
FLAT_BONEYARD = (
    ROOT
    / "tests"
    / "fixtures"
    / "boneyards"
    / "flat_multiplayer_test.boneyard"
)
INSTANCE_PREFIX = "mini"
HOST_PORT = 48511
CLIENT_PORT = 48512
GOLEM_TYPE_ID = 0x07F4
RAISE_GOLEM_ROW = 45
TARGET_HP = 5000.0
POSITION_TOLERANCE = 8.0
EXACT_FLOAT_TOLERANCE = 0.0001
INCOMING_DAMAGE = 7.25
GOLEM_SUMMON_OFFSET_X = -96.0
NATIVE_MINION_TERMINAL_NATIVE_DEATH = 1
NATIVE_MINION_TERMINAL_REPLACED = 3
NATIVE_MINION_TERMINAL_OWNER_DEATH = 4
NATIVE_MINION_TERMINAL_OWNER_DISCONNECTED = 5
NATIVE_MINION_TERMINAL_EXPLICIT_RETIREMENT = 6
LATE_TOMBSTONE_CLIENT_SUSPEND_MS = 2400


PROCESS_CONTROL_TYPE_DEFINITION = r"""
using System;
using System.Runtime.InteropServices;
public static class SdmodNativeProcessControl {
    [DllImport("ntdll.dll")]
    public static extern int NtSuspendProcess(IntPtr processHandle);
    [DllImport("ntdll.dll")]
    public static extern int NtResumeProcess(IntPtr processHandle);
}
"""


ARM_RUN_LUA = r"""
if _G.__mini_start_tick ~= nil then
  pcall(sd.events.off, _G.__mini_start_tick)
end
_G.__mini_start = {done=false, ok=false}
_G.__mini_start_tick = sd.events.on("runtime.tick", function()
  local state = _G.__mini_start
  if state.done then return end
  local scene = sd.world.get_scene()
  local name = scene and (scene.name or scene.kind) or ""
  if name ~= "testrun" then return end
  local mode_called, mode_ok = pcall(
    sd.gameplay.set_manual_enemy_spawner_test_mode, true)
  pcall(sd.gameplay.enable_combat_prelude)
  pcall(sd.gameplay.start_waves)
  local spawner_called, spawner = pcall(
    sd.gameplay.get_manual_enemy_spawner_state)
  state.ok = mode_called and mode_ok == true and
    spawner_called and type(spawner) == "table" and
    spawner.manual_mode == true and spawner.has_spawner == true
  state.done = state.ok
end)
print("armed=" .. tostring(_G.__mini_start_tick ~= nil))
"""


QUERY_RUN_LUA = r"""
local state = _G.__mini_start or {}
print("done=" .. tostring(state.done == true))
print("ok=" .. tostring(state.ok == true))
"""


QUERY_GOLEM_LUA = r"""
local target_id = tonumber("__TARGET_ID__") or 0
local expected_network_actor_id =
  tonumber("__NETWORK_ACTOR_ID__") or 0
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local scene_actors =
  sd.world.list_actors and sd.world.list_actors() or {}
local rows = {}
for _, actor in ipairs(scene_actors) do
  if (tonumber(actor.object_type_id) or 0) == 0x07F4 then
    table.insert(rows, actor)
  end
end
table.sort(rows, function(a, b)
  return (tonumber(a.actor_address) or 0) <
    (tonumber(b.actor_address) or 0)
end)
emit("count", #rows)
if #rows == 1 then
  local actor = rows[1]
  local address = tonumber(actor.actor_address) or 0
  emit("actor_address", address)
  emit("actor_slot", actor.actor_slot)
  emit("world_slot", actor.world_slot)
  local target_group =
    tonumber(sd.debug.read_u8(address + 0x164)) or 255
  local target_slot =
    tonumber(sd.debug.read_i16(address + 0x166)) or -1
  emit("target_group", target_group)
  emit("target_slot", target_slot)
  local native_target = nil
  for _, candidate in ipairs(scene_actors) do
    if tonumber(candidate.actor_slot) == target_group and
        tonumber(candidate.world_slot) == target_slot then
      native_target = candidate
      break
    end
  end
  emit("native_target_address",
    native_target and native_target.actor_address or 0)
  emit("native_target_type",
    native_target and native_target.object_type_id or 0)
  emit("native_target_x", native_target and native_target.x or "nan")
  emit("native_target_y", native_target and native_target.y or "nan")
  emit("x", actor.x)
  emit("y", actor.y)
  emit("animation_state_ptr", actor.animation_state_ptr)
  emit("hp", sd.debug.read_float(address + 0x170))
  emit("max_hp", sd.debug.read_float(address + 0x174))
  emit("target_refresh_timer",
    sd.debug.read_i32(address + 0x178))
  emit("locomotion_sample_counter",
    sd.debug.read_i32(address + 0x17C))
  emit("gait_primary", sd.debug.read_i32(address + 0x1E8))
  emit("gait_secondary", sd.debug.read_i32(address + 0x1EC))
  emit("damage_primary", sd.debug.read_float(address + 0x1F0))
  emit("damage_secondary", sd.debug.read_float(address + 0x1F4))
  emit("attack_timer", sd.debug.read_i32(address + 0x1F8))
  emit("attack_cooldown", sd.debug.read_i32(address + 0x200))
  emit("age", sd.debug.read_i32(address + 0x208))
  emit("ambient_effect_timer",
    sd.debug.read_i32(address + 0x218))
  emit("animation_phase",
    sd.debug.read_float(address + 0x21C))
end
local target = target_id ~= 0 and
  sd.world.get_run_enemy_by_network_id and
  sd.world.get_run_enemy_by_network_id(target_id) or nil
emit("target_found", target ~= nil)
emit("target_hp", target and target.hp or "nan")
local replicated = sd.world.get_replicated_actors and
  sd.world.get_replicated_actors() or nil
local replicated_count = 0
local active_replicated_count = 0
local terminal_replicated_count = 0
local selected_active = nil
local selected_terminal = nil
for _, actor in ipairs(replicated and replicated.actors or {}) do
  if (tonumber(actor.object_type_id) or 0) == 0x07F4 then
    replicated_count = replicated_count + 1
    local flags = tonumber(actor.native_minion_state_flags) or 0
    local network_actor_id =
      tonumber(actor.network_actor_id) or 0
    if flags % 2 == 1 then
      active_replicated_count = active_replicated_count + 1
      if selected_active == nil or
          network_actor_id >
            (tonumber(selected_active.network_actor_id) or 0) then
        selected_active = actor
      end
    end
    if math.floor(flags / 4) % 2 == 1 then
      terminal_replicated_count =
        terminal_replicated_count + 1
      if expected_network_actor_id ~= 0 and
          network_actor_id == expected_network_actor_id then
        selected_terminal = actor
      elseif expected_network_actor_id == 0 and
          (selected_terminal == nil or
           network_actor_id >
             (tonumber(selected_terminal.network_actor_id) or 0)) then
        selected_terminal = actor
      end
    end
  end
end
emit("replicated_count", replicated_count)
emit("active_replicated_count", active_replicated_count)
emit("terminal_replicated_count", terminal_replicated_count)
emit("created_actor_total_count",
  replicated and replicated.created_actor_total_count or 0)
emit("network_actor_id",
  selected_active and selected_active.network_actor_id or 0)
emit("owner_participant_id",
  selected_active and
    selected_active.native_minion_owner_participant_id or 0)
emit("state_flags",
  selected_active and selected_active.native_minion_state_flags or 0)
emit("replicated_age",
  selected_active and selected_active.native_minion_age or -1)
emit("replicated_gait_primary",
  selected_active and
    selected_active.native_minion_gait_primary or -1)
emit("replicated_gait_secondary",
  selected_active and
    selected_active.native_minion_gait_secondary or -1)
emit("replicated_animation_phase",
  selected_active and
    selected_active.native_minion_animation_phase or "nan")
emit("terminal_network_actor_id",
  selected_terminal and selected_terminal.network_actor_id or 0)
emit("terminal_reason",
  selected_terminal and
    selected_terminal.native_minion_terminal_reason or 0)
"""


RETIRE_GOLEMS_LUA = r"""
local ok, err, count =
  sd.gameplay.retire_test_run_player_created_actors(0x07F4)
print("ok=" .. tostring(ok))
print("error=" .. tostring(err or ""))
print("requested_count=" .. tostring(count or 0))
"""


CONTACT_GOLEM_LUA = r"""
local requested_damage = tonumber("__DAMAGE__") or 0
local found = 0
local actor_address = 0
local before_hp = 0
local before_age = 0
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  if (tonumber(actor.object_type_id) or 0) == 0x07F4 then
    found = found + 1
    actor_address = tonumber(actor.actor_address) or 0
    before_hp = tonumber(sd.debug.read_float(
      actor_address + 0x170)) or 0
    before_age = tonumber(sd.debug.read_i32(
      actor_address + 0x208)) or 0
  end
end
local target_global =
  tonumber(sd.debug.resolve_game_address(0x0081C6D8)) or 0
local source_global =
  tonumber(sd.debug.resolve_game_address(0x0081C6E0)) or 0
local flags_global =
  tonumber(sd.debug.resolve_game_address(0x0081C6E4)) or 0
local primary_global =
  tonumber(sd.debug.resolve_game_address(0x0081C6E8)) or 0
local secondary_global =
  tonumber(sd.debug.resolve_game_address(0x0081C6EC)) or 0
local setup = found == 1 and actor_address ~= 0 and
  target_global ~= 0 and source_global ~= 0 and
  flags_global ~= 0 and primary_global ~= 0 and
  secondary_global ~= 0 and
  sd.debug.write_ptr(target_global, actor_address) and
  sd.debug.write_ptr(source_global, 0) and
  sd.debug.write_u32(flags_global, 0) and
  sd.debug.write_float(primary_global, requested_damage) and
  sd.debug.write_float(secondary_global, 0)
local call_result = nil
if setup then
  call_result = sd.debug.call_thiscall_ret_u32(
    0x00607F60, actor_address)
end
local after_hp = actor_address ~= 0 and
  tonumber(sd.debug.read_float(actor_address + 0x170)) or 0
local cleanup = target_global ~= 0 and source_global ~= 0 and
  flags_global ~= 0 and primary_global ~= 0 and
  secondary_global ~= 0 and
  sd.debug.write_ptr(target_global, 0) and
  sd.debug.write_ptr(source_global, 0) and
  sd.debug.write_u32(flags_global, 0) and
  sd.debug.write_float(primary_global, 0) and
  sd.debug.write_float(secondary_global, 0)
print("found=" .. tostring(found))
print("actor_address=" .. tostring(actor_address))
print("before_age=" .. tostring(before_age))
print("before_hp=" .. tostring(before_hp))
print("setup=" .. tostring(setup))
print("called=" .. tostring(call_result ~= nil))
print("call_result=" .. tostring(call_result))
print("after_hp=" .. tostring(after_hp))
print("cleanup=" .. tostring(cleanup))
"""


@dataclass(frozen=True)
class LocalPair:
    host_pipe: str
    client_pipe: str
    host_participant_id: int = local_sync.HOST_ID
    client_participant_id: int = local_sync.CLIENT_ID

    def lua(
        self,
        endpoint: str,
        code: str,
        timeout: float = 8.0,
    ) -> str:
        pipe = {
            HOST_ENDPOINT: self.host_pipe,
            CLIENT_ENDPOINT: self.client_pipe,
            self.host_pipe: self.host_pipe,
            self.client_pipe: self.client_pipe,
        }.get(endpoint)
        if pipe is None:
            raise local_sync.VerifyFailure(
                f"unknown endpoint {endpoint}"
            )
        return ORIGINAL_LUA(pipe, code, timeout=timeout)


def values(pair: LocalPair, endpoint: str, code: str) -> dict[str, str]:
    return local_sync.parse_key_values(
        pair.lua(endpoint, code, timeout=10.0)
    )


def pair_values(
    pair: LocalPair,
    code: str,
) -> dict[str, dict[str, str]]:
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=2
    ) as executor:
        futures = {
            "host": executor.submit(
                values,
                pair,
                HOST_ENDPOINT,
                code,
            ),
            "client": executor.submit(
                values,
                pair,
                CLIENT_ENDPOINT,
                code,
            ),
        }
        return {
            label: future.result()
            for label, future in futures.items()
        }


def parse_float(value: str | None) -> float:
    try:
        return float(value if value is not None else "nan")
    except ValueError:
        return math.nan


def query_pair(
    pair: LocalPair,
    target_id: int = 0,
    network_actor_id: int = 0,
) -> dict[str, dict[str, Any]]:
    code = (
        QUERY_GOLEM_LUA
        .replace("__TARGET_ID__", str(target_id))
        .replace(
            "__NETWORK_ACTOR_ID__",
            str(network_actor_id),
        )
    )
    result: dict[str, dict[str, Any]] = {}
    for label, raw in pair_values(pair, code).items():
        result[label] = {
            "count": local_sync.parse_int_text(
                raw.get("count"),
                0,
            ),
            "actor_address": local_sync.parse_int_text(
                raw.get("actor_address"),
                0,
            ),
            "actor_slot": local_sync.parse_int_text(
                raw.get("actor_slot"),
                -1,
            ),
            "world_slot": local_sync.parse_int_text(
                raw.get("world_slot"),
                -1,
            ),
            "target_group": local_sync.parse_int_text(
                raw.get("target_group"),
                255,
            ),
            "target_slot": local_sync.parse_int_text(
                raw.get("target_slot"),
                -1,
            ),
            "native_target_address":
                local_sync.parse_int_text(
                    raw.get("native_target_address"),
                    0,
                ),
            "native_target_type":
                local_sync.parse_int_text(
                    raw.get("native_target_type"),
                    0,
                ),
            "native_target_x": parse_float(
                raw.get("native_target_x"),
            ),
            "native_target_y": parse_float(
                raw.get("native_target_y"),
            ),
            "x": parse_float(raw.get("x")),
            "y": parse_float(raw.get("y")),
            "animation_state_ptr": local_sync.parse_int_text(
                raw.get("animation_state_ptr"),
                0,
            ),
            "hp": parse_float(raw.get("hp")),
            "max_hp": parse_float(raw.get("max_hp")),
            "target_refresh_timer":
                local_sync.parse_int_text(
                    raw.get("target_refresh_timer"),
                    -1,
                ),
            "locomotion_sample_counter":
                local_sync.parse_int_text(
                    raw.get("locomotion_sample_counter"),
                    -1,
                ),
            "gait_primary": local_sync.parse_int_text(
                raw.get("gait_primary"),
                -1,
            ),
            "gait_secondary": local_sync.parse_int_text(
                raw.get("gait_secondary"),
                -1,
            ),
            "damage_primary": parse_float(
                raw.get("damage_primary"),
            ),
            "damage_secondary": parse_float(
                raw.get("damage_secondary"),
            ),
            "attack_timer": local_sync.parse_int_text(
                raw.get("attack_timer"),
                -1,
            ),
            "attack_cooldown":
                local_sync.parse_int_text(
                    raw.get("attack_cooldown"),
                    -1,
                ),
            "age": local_sync.parse_int_text(
                raw.get("age"),
                -1,
            ),
            "ambient_effect_timer":
                local_sync.parse_int_text(
                    raw.get("ambient_effect_timer"),
                    -1,
                ),
            "animation_phase":
                parse_float(raw.get("animation_phase")),
            "target_found": raw.get("target_found") == "true",
            "target_hp": parse_float(raw.get("target_hp")),
            "replicated_count":
                local_sync.parse_int_text(
                    raw.get("replicated_count"),
                    0,
                ),
            "active_replicated_count":
                local_sync.parse_int_text(
                    raw.get("active_replicated_count"),
                    0,
                ),
            "terminal_replicated_count":
                local_sync.parse_int_text(
                    raw.get("terminal_replicated_count"),
                    0,
                ),
            "created_actor_total_count":
                local_sync.parse_int_text(
                    raw.get("created_actor_total_count"),
                    0,
                ),
            "network_actor_id":
                local_sync.parse_int_text(
                    raw.get("network_actor_id"),
                    0,
                ),
            "owner_participant_id":
                local_sync.parse_int_text(
                    raw.get("owner_participant_id"),
                    0,
                ),
            "state_flags": local_sync.parse_int_text(
                raw.get("state_flags"),
                0,
            ),
            "replicated_age":
                local_sync.parse_int_text(
                    raw.get("replicated_age"),
                    -1,
                ),
            "replicated_gait_primary":
                local_sync.parse_int_text(
                    raw.get("replicated_gait_primary"),
                    -1,
                ),
            "replicated_gait_secondary":
                local_sync.parse_int_text(
                    raw.get("replicated_gait_secondary"),
                    -1,
                ),
            "replicated_animation_phase":
                parse_float(
                    raw.get("replicated_animation_phase"),
                ),
            "terminal_network_actor_id":
                local_sync.parse_int_text(
                    raw.get("terminal_network_actor_id"),
                    0,
                ),
            "terminal_reason":
                local_sync.parse_int_text(
                    raw.get("terminal_reason"),
                    0,
                ),
        }
    return result


def wait_for(
    probe: Any,
    predicate: Any,
    timeout: float,
    label: str,
) -> Any:
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        last = probe()
        if predicate(last):
            return last
        time.sleep(0.10)
    raise local_sync.VerifyFailure(
        f"{label} did not converge: {last}"
    )


def launch_pair() -> tuple[
    dict[str, Any],
    LocalPair,
    dict[int, Path],
]:
    # The standard pair launcher injects SDMOD_DISABLE_AUDIO when
    # enable_audio is false. Override an ambient opt-in before every launch.
    os.environ.pop("SDMOD_ENABLE_AUDIO", None)
    os.environ["SDMOD_DISABLE_AUDIO"] = "1"
    launched = local_sync.launch_pair(
        host_preset="map_create_earth_mind_hub",
        client_preset="map_create_earth_mind_hub",
        tile_windows=False,
        kill_existing=False,
        instance_prefix=INSTANCE_PREFIX,
        host_port=HOST_PORT,
        client_port=CLIENT_PORT,
        game_directory=GAME_DIRECTORY,
        runtime_root=RUNTIME_ROOT,
        exact_mod_id="sample.lua.ui_sandbox_lab",
        test_blank_boneyard=True,
        test_survival_boneyard_override=FLAT_BONEYARD,
        use_sandbox_preset_flow=True,
        god_mode=True,
        enable_audio=False,
    )
    if launched.get("audioDisabled") is not True:
        raise local_sync.VerifyFailure(
            f"audio-disable launch contract failed: {launched}"
        )
    expected = {
        int(launched["hostProcessId"]):
            process_guard.expected_executable(
                RUNTIME_ROOT,
                f"{INSTANCE_PREFIX}-host",
            ),
        int(launched["clientProcessId"]):
            process_guard.expected_executable(
                RUNTIME_ROOT,
                f"{INSTANCE_PREFIX}-client",
            ),
    }
    process_guard.validate_owned_processes(expected)
    return (
        launched,
        LocalPair(
            str(launched["hostLuaPipe"]),
            str(launched["clientLuaPipe"]),
        ),
        expected,
    )


def configure_pair(
    pair: LocalPair,
) -> behavior_context.BehaviorContext:
    host_log = (
        RUNTIME_ROOT
        / "instances"
        / "mini-host"
        / "stage"
        / ".sdmod"
        / "logs"
        / "solomondarkmodloader.log"
    )
    client_log = (
        RUNTIME_ROOT
        / "instances"
        / "mini-client"
        / "stage"
        / ".sdmod"
        / "logs"
        / "solomondarkmodloader.log"
    )
    local_sync.HOST_PIPE = pair.host_pipe
    local_sync.CLIENT_PIPE = pair.client_pipe
    local_sync.HOST_LOG = host_log
    local_sync.CLIENT_LOG = client_log
    behavior_context.HOST_INSTANCE = "mini-host"
    behavior_context.CLIENT_INSTANCE = "mini-client"
    return behavior_context.configure_behavior_context(pair)


def enter_run(
    pair: LocalPair,
) -> dict[str, Any]:
    local_sync.HOST_PIPE = pair.host_pipe
    local_sync.CLIENT_PIPE = pair.client_pipe
    armed = pair_values(pair, ARM_RUN_LUA)
    if any(row.get("armed") != "true" for row in armed.values()):
        raise local_sync.VerifyFailure(
            f"run setup did not arm: {armed}"
        )
    local_sync.start_host_testrun_and_wait_for_clients(
        timeout=45.0
    )
    ready = wait_for(
        lambda: pair_values(pair, QUERY_RUN_LUA),
        lambda rows: all(
            row.get("done") == "true" and
            row.get("ok") == "true"
            for row in rows.values()
        ),
        20.0,
        "manual run combat",
    )
    local_sync.disable_bots()
    return {"armed": armed, "ready": ready}


def prepare_cast(
    pair: LocalPair,
    direction: focus.Direction,
) -> dict[str, Any]:
    owner = rush.DIRECTIONS[
        0 if direction.source_pipe == HOST_ENDPOINT else 1
    ]
    observer = rush.DIRECTIONS[
        1 if direction.source_pipe == HOST_ENDPOINT else 0
    ]
    rush.place_player(
        owner.owner_pipe,
        rush.START_X,
        rush.START_Y,
        90.0,
    )
    rush.place_player(
        observer.owner_pipe,
        rush.START_X - 150.0,
        rush.START_Y + 20.0,
        90.0,
    )
    source = rush.wait_for_local_transform_settled(
        owner.owner_pipe,
        timeout=10.0,
        stable_seconds=0.45,
    )
    other = rush.wait_for_local_transform_settled(
        observer.owner_pipe,
        timeout=10.0,
        stable_seconds=0.45,
    )
    rush.wait_for_remote_convergence(
        owner.observer_pipe,
        owner.participant_id,
        *source,
        timeout=15.0,
    )
    rush.wait_for_remote_convergence(
        observer.observer_pipe,
        observer.participant_id,
        *other,
        timeout=15.0,
    )
    target_x = source[0] + 205.0
    target_y = source[1]
    spawned = primary.spawn_one_enemy(
        target_x,
        target_y,
        setup_hp=TARGET_HP,
        freeze_on_spawn=True,
    )
    target_id = int(spawned["network_actor_id"])
    local_target = primary.find_target(
        direction.source_pipe,
        target_x,
        target_y,
        target_id,
        timeout=10.0,
        require_local_binding=(
            direction.source_pipe != HOST_ENDPOINT
        ),
    )
    target_actor = (
        int(spawned["actor_address"])
        if direction.source_pipe == HOST_ENDPOINT
        else local_sync.parse_int_text(
            local_target.get("local.actor_address"),
            0,
        )
    )
    prepared = values(
        pair,
        direction.source_pipe,
        secondary.PREPARE_LOCAL_TARGET_LUA
        .replace("__TARGET_ACTOR__", str(target_actor))
        .replace("__TARGET_X__", f"{target_x:.3f}")
        .replace("__TARGET_Y__", f"{target_y:.3f}"),
    )
    if prepared.get("ok") != "true":
        raise local_sync.VerifyFailure(
            f"could not prepare golem target: {prepared}"
        )
    return {
        "target_id": target_id,
        "target_x": target_x,
        "target_y": target_y,
        "spawned": spawned,
        "prepared": prepared,
    }


def cast_golem(
    pair: LocalPair,
    direction: focus.Direction,
    belt_slot: int,
    target_x: float,
    target_y: float,
) -> dict[str, Any]:
    source_offset = len(read_log(direction.source_log))
    observer_offset = len(read_log(direction.observer_log))
    cast, delivery = secondary.cast_secondary_until_delivered(
        direction,
        RAISE_GOLEM_ROW,
        belt_slot,
        source_offset,
        observer_offset,
        30.0,
        cursor_world=(target_x, target_y),
    )
    return {"cast": cast, "delivery": delivery}


def host_summon(
    pair: LocalPair,
    direction: focus.Direction,
    belt_slot: int,
    target_x: float,
    target_y: float,
) -> dict[str, Any]:
    return cast_golem(
        pair,
        direction,
        belt_slot,
        target_x,
        target_y,
    )


def client_summon(
    pair: LocalPair,
    direction: focus.Direction,
    belt_slot: int,
    target_x: float,
    target_y: float,
) -> dict[str, Any]:
    return cast_golem(
        pair,
        direction,
        belt_slot,
        target_x,
        target_y,
    )


def assert_native_minion_visible_and_animating(
    pair: LocalPair,
    target_id: int,
    owner_participant_id: int,
) -> dict[str, Any]:
    samples: list[dict[str, dict[str, Any]]] = []
    converged_index: int | None = None
    started = time.monotonic()
    deadline = started + 10.0
    while time.monotonic() < deadline:
        sample = query_pair(pair, target_id)
        samples.append(sample)
        host = sample["host"]
        client = sample["client"]
        if (
            host["count"] == 1 and
            client["count"] == 1 and
            host["active_replicated_count"] == 1 and
            client["active_replicated_count"] == 1 and
            host["network_actor_id"] != 0 and
            host["network_actor_id"] ==
                client["network_actor_id"] and
            host["owner_participant_id"] ==
                owner_participant_id and
            client["owner_participant_id"] ==
                owner_participant_id and
            host["animation_state_ptr"] != 0 and
            client["animation_state_ptr"] != 0 and
            math.hypot(
                host["x"] - client["x"],
                host["y"] - client["y"],
            ) <= POSITION_TOLERANCE
        ):
            if len(samples) >= 6:
                converged_index = len(samples) - 1
                break
        time.sleep(0.15)
    else:
        raise local_sync.VerifyFailure(
            f"golem visibility did not converge: {samples[-1:]}"
        )
    time.sleep(1.0)
    samples.append(query_pair(pair, target_id))
    host_rows = [
        row["host"]
        for row in samples
        if row["host"]["count"] == 1
    ]
    client_rows = [
        row["client"]
        for row in samples
        if row["client"]["count"] == 1
    ]
    if (
        host_rows[-1]["age"] <= host_rows[0]["age"] or
        client_rows[-1]["age"] <= client_rows[0]["age"]
    ):
        raise local_sync.VerifyFailure(
            f"golem native animation clock did not advance: {samples}"
        )
    assert converged_index is not None
    replicated_samples = [
        row
        for row in samples[converged_index:]
        if (
            row["host"]["count"] == 1 and
            row["client"]["count"] == 1 and
            row["host"]["active_replicated_count"] == 1 and
            row["client"]["active_replicated_count"] == 1 and
            row["host"]["network_actor_id"] != 0 and
            row["host"]["network_actor_id"] ==
                row["client"]["network_actor_id"]
        )
    ]
    maximum_position_error = max(
        math.hypot(
            row["host"]["x"] - row["client"]["x"],
            row["host"]["y"] - row["client"]["y"],
        )
        for row in replicated_samples
    )
    if maximum_position_error > POSITION_TOLERANCE:
        raise local_sync.VerifyFailure(
            "golem position diverged after convergence: "
            f"error={maximum_position_error} samples={replicated_samples}"
        )
    return {
        "sample_count": len(samples),
        "first": samples[0],
        "last": samples[-1],
        "maximum_position_error": maximum_position_error,
    }


def assert_missing_native_minion_recovery(
    pair: LocalPair,
    target_id: int,
    owner_participant_id: int,
) -> dict[str, Any]:
    before = query_pair(pair, target_id)
    expected_network_actor_id = int(
        before["host"]["network_actor_id"]
    )
    if (
        expected_network_actor_id == 0 or
        expected_network_actor_id !=
            before["client"]["network_actor_id"]
    ):
        raise local_sync.VerifyFailure(
            f"missing-spawn recovery lacks stable identity: {before}"
        )

    retirement = values(
        pair,
        CLIENT_ENDPOINT,
        RETIRE_GOLEMS_LUA,
    )
    if (
        retirement.get("ok") != "true" or
        local_sync.parse_int_text(
            retirement.get("requested_count"),
            0,
        ) != 1
    ):
        raise local_sync.VerifyFailure(
            "could not remove the client observer before recovery: "
            f"{retirement}"
        )

    recovered = wait_for(
        lambda: query_pair(
            pair,
            target_id,
            expected_network_actor_id,
        ),
        lambda rows: (
            rows["host"]["count"] == 1 and
            rows["client"]["count"] == 1 and
            rows["host"]["actor_address"] ==
                before["host"]["actor_address"] and
            rows["client"]["created_actor_total_count"] >
                before["client"][
                    "created_actor_total_count"
                ] and
            rows["host"]["network_actor_id"] ==
                expected_network_actor_id and
            rows["client"]["network_actor_id"] ==
                expected_network_actor_id
        ),
        12.0,
        "missing native-minion observer recovery",
    )
    visible = assert_native_minion_visible_and_animating(
        pair,
        target_id,
        owner_participant_id,
    )
    return {
        "before": before,
        "retirement": retirement,
        "recovered": recovered,
        "visible": visible,
    }


def assert_exact_damage_convergence(
    pair: LocalPair,
    target_id: int,
) -> dict[str, Any]:
    baseline = query_pair(pair, target_id)
    baseline_hp = baseline["host"]["target_hp"]
    converged = wait_for(
        lambda: query_pair(pair, target_id),
        lambda rows: (
            rows["host"]["target_found"] and
            rows["client"]["target_found"] and
            baseline_hp - rows["host"]["target_hp"] > 0.05 and
            abs(
                rows["host"]["target_hp"] -
                rows["client"]["target_hp"]
            ) <= EXACT_FLOAT_TOLERANCE
        ),
        30.0,
        "native minion outgoing damage",
    )
    return {
        "baseline": baseline,
        "converged": converged,
        "damage": baseline_hp -
            converged["host"]["target_hp"],
    }


def call_native_golem_contact(
    pair: LocalPair,
    endpoint: str,
    damage: float,
) -> dict[str, Any]:
    result = values(
        pair,
        endpoint,
        CONTACT_GOLEM_LUA.replace(
            "__DAMAGE__",
            f"{damage:.9f}",
        ),
    )
    if (
        local_sync.parse_int_text(
            result.get("found"),
            0,
        ) != 1 or
        result.get("setup") != "true" or
        result.get("called") != "true" or
        result.get("cleanup") != "true"
    ):
        raise local_sync.VerifyFailure(
            f"native Golem contact call failed on {endpoint}: "
            f"{result}"
        )
    return {
        **result,
        "before_age": local_sync.parse_int_text(
            result.get("before_age"),
            -1,
        ),
        "before_hp": parse_float(result.get("before_hp")),
        "after_hp": parse_float(result.get("after_hp")),
    }


def assert_incoming_damage_convergence(
    pair: LocalPair,
    target_id: int,
) -> dict[str, Any]:
    baseline = wait_for(
        lambda: query_pair(pair, target_id),
        lambda rows: (
            rows["host"]["count"] == 1 and
            rows["client"]["count"] == 1 and
            rows["host"]["age"] >= 400 and
            rows["client"]["age"] >= 400 and
            abs(
                rows["host"]["hp"] -
                rows["client"]["hp"]
            ) <= EXACT_FLOAT_TOLERANCE and
            rows["host"]["hp"] > INCOMING_DAMAGE * 2.0
        ),
        20.0,
        "assembled damageable native minion",
    )
    baseline_hp = baseline["host"]["hp"]

    observer_call = call_native_golem_contact(
        pair,
        CLIENT_ENDPOINT,
        INCOMING_DAMAGE,
    )
    if (
        observer_call["before_age"] < 400 or
        abs(
            observer_call["before_hp"] -
            observer_call["after_hp"]
        ) > EXACT_FLOAT_TOLERANCE
    ):
        raise local_sync.VerifyFailure(
            "observer accepted native Golem contact damage: "
            f"{observer_call}"
        )
    observer_blocked = wait_for(
        lambda: query_pair(pair, target_id),
        lambda rows: (
            abs(rows["host"]["hp"] - baseline_hp) <=
                EXACT_FLOAT_TOLERANCE and
            abs(rows["client"]["hp"] - baseline_hp) <=
                EXACT_FLOAT_TOLERANCE
        ),
        3.0,
        "observer Golem contact suppression",
    )

    authority_call = call_native_golem_contact(
        pair,
        HOST_ENDPOINT,
        INCOMING_DAMAGE,
    )
    expected_hp = authority_call["after_hp"]
    if (
        authority_call["before_age"] < 400 or
        abs(
            authority_call["before_hp"] -
            baseline_hp
        ) > EXACT_FLOAT_TOLERANCE or
        abs(
            authority_call["before_hp"] -
            authority_call["after_hp"] -
            INCOMING_DAMAGE
        ) > EXACT_FLOAT_TOLERANCE
    ):
        raise local_sync.VerifyFailure(
            "host native Golem contact damage was not exact: "
            f"{authority_call}"
        )
    converged = wait_for(
        lambda: query_pair(pair, target_id),
        lambda rows: (
            rows["host"]["count"] == 1 and
            rows["client"]["count"] == 1 and
            abs(rows["host"]["hp"] - expected_hp) <=
                EXACT_FLOAT_TOLERANCE and
            abs(
                rows["host"]["hp"] -
                rows["client"]["hp"]
            ) <= EXACT_FLOAT_TOLERANCE
        ),
        8.0,
        "native minion incoming damage",
    )
    return {
        "baseline": baseline,
        "observer_call": observer_call,
        "observer_blocked": observer_blocked,
        "authority_call": authority_call,
        "converged": converged,
        "damage": baseline_hp - expected_hp,
    }


def capture_both_peer_screenshots(
    pair: LocalPair,
    output_directory: Path,
) -> dict[str, Any]:
    output_directory.mkdir(parents=True, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=2
    ) as executor:
        futures = {
            "host": executor.submit(
                frame_capture.capture_game_backbuffer,
                pair.host_pipe,
                output_directory / "host.png",
                maximum_dominant_fraction=0.997,
            ),
            "client": executor.submit(
                frame_capture.capture_game_backbuffer,
                pair.client_pipe,
                output_directory / "client.png",
                maximum_dominant_fraction=0.997,
            ),
        }
        return {
            label: {
                "path": str(output_directory / f"{label}.png"),
                "capture": future.result(),
            }
            for label, future in futures.items()
        }


def focus_pair_cameras(
    pair: LocalPair,
    target_x: float,
    target_y: float,
) -> dict[str, Any]:
    set_code = f"""
local accepted = sd.camera.set_focus({target_x!r}, {target_y!r})
print("accepted=" .. tostring(accepted))
"""
    accepted = pair_values(pair, set_code)
    if any(
        row.get("accepted") != "true"
        for row in accepted.values()
    ):
        raise local_sync.VerifyFailure(
            f"minion screenshot camera focus was rejected: {accepted}"
        )

    query_code = """
local camera = assert(sd.camera.get_state())
print("focus_active=" .. tostring(camera.focus_active))
print("center_x=" .. tostring(camera.center_x))
print("center_y=" .. tostring(camera.center_y))
"""
    settled = wait_for(
        lambda: pair_values(pair, query_code),
        lambda rows: all(
            row.get("focus_active") == "true" and
            abs(parse_float(row.get("center_x")) - target_x) <= 0.05 and
            abs(parse_float(row.get("center_y")) - target_y) <= 0.05
            for row in rows.values()
        ),
        8.0,
        "minion screenshot camera focus",
    )
    return {
        "target_x": target_x,
        "target_y": target_y,
        "accepted": accepted,
        "settled": settled,
    }


def clear_pair_camera_focus(
    pair: LocalPair,
) -> dict[str, dict[str, str]]:
    return pair_values(
        pair,
        """
local cleared = sd.camera.clear_focus()
print("cleared=" .. tostring(cleared))
""",
    )


def assert_recast_replacement(
    pair: LocalPair,
    direction: focus.Direction,
    belt_slot: int,
    target_id: int,
    target_x: float,
    target_y: float,
) -> dict[str, Any]:
    before = query_pair(pair, target_id)
    replaced_network_actor_id = int(
        before["host"]["network_actor_id"]
    )
    if (
        replaced_network_actor_id == 0 or
        replaced_network_actor_id !=
            before["client"]["network_actor_id"]
    ):
        raise local_sync.VerifyFailure(
            f"recast replacement lacks an active identity: {before}"
        )

    cast = cast_golem(
        pair,
        direction,
        belt_slot,
        target_x + GOLEM_SUMMON_OFFSET_X,
        target_y,
    )
    replaced = wait_for(
        lambda: query_pair(
            pair,
            target_id,
            replaced_network_actor_id,
        ),
        lambda rows: (
            rows["host"]["count"] == 1 and
            rows["client"]["count"] == 1 and
            rows["host"]["active_replicated_count"] == 1 and
            rows["client"]["active_replicated_count"] == 1 and
            rows["host"]["network_actor_id"] != 0 and
            rows["host"]["network_actor_id"] !=
                replaced_network_actor_id and
            rows["host"]["network_actor_id"] ==
                rows["client"]["network_actor_id"] and
            all(
                row["terminal_network_actor_id"] ==
                    replaced_network_actor_id and
                row["terminal_reason"] ==
                    NATIVE_MINION_TERMINAL_REPLACED
                for row in rows.values()
            )
        ),
        12.0,
        "native minion recast replacement",
    )
    return {
        "before": before,
        "cast": cast,
        "replaced": replaced,
        "replacement_network_actor_id":
            replaced["host"]["network_actor_id"],
    }


def assert_native_minion_death_convergence(
    pair: LocalPair,
    target_id: int,
) -> dict[str, Any]:
    before = wait_for(
        lambda: query_pair(pair, target_id),
        lambda rows: (
            rows["host"]["count"] == 1 and
            rows["client"]["count"] == 1 and
            rows["host"]["age"] >= 400 and
            rows["host"]["hp"] > 0.0 and
            abs(
                rows["host"]["hp"] -
                rows["client"]["hp"]
            ) <= EXACT_FLOAT_TOLERANCE
        ),
        12.0,
        "fatal Golem contact setup",
    )
    network_actor_id = int(
        before["host"]["network_actor_id"]
    )
    fatal_damage = before["host"]["hp"] + 25.0
    contact = call_native_golem_contact(
        pair,
        HOST_ENDPOINT,
        fatal_damage,
    )
    if contact["after_hp"] > 0.0:
        raise local_sync.VerifyFailure(
            f"fatal Golem contact left positive HP: {contact}"
        )

    terminal = wait_for(
        lambda: query_pair(
            pair,
            target_id,
            network_actor_id,
        ),
        lambda rows: (
            all(row["count"] == 0 for row in rows.values()) and
            all(
                row["terminal_network_actor_id"] ==
                    network_actor_id and
                row["terminal_reason"] ==
                    NATIVE_MINION_TERMINAL_NATIVE_DEATH
                for row in rows.values()
            )
        ),
        12.0,
        "native minion HP-death terminal",
    )
    return {
        "before": before,
        "contact": contact,
        "terminal": terminal,
    }


def suspend_exact_owned_process(
    process_id: int,
    expected_path: Path,
    duration_ms: int,
) -> tuple[subprocess.Popen[str], dict[str, Any]]:
    validated = process_guard.validate_owned_processes(
        {process_id: expected_path}
    )
    expected_windows_path = (
        local_sync.path_for_powershell(expected_path)
        .replace("'", "''")
    )
    escaped_type = (
        PROCESS_CONTROL_TYPE_DEFINITION
        .replace("'", "''")
    )
    command = (
        "$ErrorActionPreference='Stop';"
        f"$expectedPath='{expected_windows_path}';"
        f"$cim=Get-CimInstance Win32_Process -Filter "
        f"\"ProcessId={process_id}\";"
        "if($null -eq $cim -or "
        "-not [string]::Equals("
        "[string]$cim.ExecutablePath,$expectedPath,"
        "[System.StringComparison]::OrdinalIgnoreCase)){"
        "throw 'owned process identity changed'};"
        f"Add-Type -TypeDefinition '{escaped_type}';"
        f"$process=Get-Process -Id {process_id} "
        "-ErrorAction Stop;"
        "$suspended=$false;"
        "try {"
        "$status=[SdmodNativeProcessControl]::"
        "NtSuspendProcess($process.Handle);"
        "if($status -ne 0){"
        "throw \"NtSuspendProcess failed: $status\"};"
        "$suspended=$true;"
        "[Console]::Out.WriteLine('suspended');"
        "[Console]::Out.Flush();"
        f"Start-Sleep -Milliseconds {duration_ms};"
        "} finally {"
        "if($suspended){"
        "$status=[SdmodNativeProcessControl]::"
        "NtResumeProcess($process.Handle);"
        "if($status -ne 0){"
        "throw \"NtResumeProcess failed: $status\"};"
        "[Console]::Out.WriteLine('resumed');"
        "[Console]::Out.Flush();"
        "}"
        "}"
    )
    controller = subprocess.Popen(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
        ],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert controller.stdout is not None
    marker = controller.stdout.readline().strip()
    if marker != "suspended":
        assert controller.stderr is not None
        detail = controller.stderr.read().strip()
        controller.wait(timeout=10.0)
        raise local_sync.VerifyFailure(
            "exact owned-process suspension did not start: "
            f"marker={marker!r} detail={detail}"
        )
    return (
        controller,
        {
            "process_id": process_id,
            "expected_path": str(expected_path),
            "validated": validated,
            "duration_ms": duration_ms,
            "start_marker": marker,
        },
    )


def assert_native_minion_despawn_convergence(
    pair: LocalPair,
    network_actor_id: int,
    client_process_id: int,
    client_executable: Path,
) -> dict[str, Any]:
    controller, suspension = suspend_exact_owned_process(
        client_process_id,
        client_executable,
        LATE_TOMBSTONE_CLIENT_SUSPEND_MS,
    )
    request: dict[str, str] = {}
    try:
        request = values(
            pair,
            HOST_ENDPOINT,
            RETIRE_GOLEMS_LUA,
        )
    finally:
        stdout, stderr = controller.communicate(timeout=15.0)
        suspension["stdout"] = stdout.strip()
        suspension["stderr"] = stderr.strip()
        suspension["returncode"] = controller.returncode
    if (
        controller.returncode != 0 or
        "resumed" not in suspension["stdout"].splitlines()
    ):
        raise local_sync.VerifyFailure(
            "client late-tombstone suspension did not resume "
            f"cleanly: {suspension}"
        )
    if (
        request.get("ok") != "true" or
        local_sync.parse_int_text(
            request.get("requested_count"),
            0,
        ) != 1
    ):
        raise local_sync.VerifyFailure(
            f"host did not retire one golem: {request}"
        )
    absent = wait_for(
        lambda: query_pair(
            pair,
            network_actor_id=network_actor_id,
        ),
        lambda rows: (
            all(row["count"] == 0 for row in rows.values()) and
            all(
                row["terminal_network_actor_id"] ==
                    network_actor_id and
                row["terminal_reason"] ==
                    NATIVE_MINION_TERMINAL_EXPLICIT_RETIREMENT
                for row in rows.values()
            )
        ),
        10.0,
        "late native minion explicit tombstone",
    )
    return {
        "request": request,
        "suspension": suspension,
        "absent": absent,
    }


def assert_owner_death_convergence(
    pair: LocalPair,
    network_actor_id: int,
    progress: dict[str, Any],
) -> dict[str, Any]:
    precondition = secondary.set_local_player_vitals(
        HOST_ENDPOINT,
        1.0,
        1.0,
        mp=50.0,
        max_mp=50.0,
    )
    progress["precondition"] = precondition
    lethal_hit = defense.invoke_native_magic_hit_trial(
        HOST_ENDPOINT,
        projectile_damage=0.0,
        magic_damage=1000.0,
        attempts=1,
        label="native minion owner death",
        timeout=8.0,
        target_participant_id=0,
    )
    progress["lethal_hit"] = lethal_hit
    if float(lethal_hit["hp_after"]) > EXACT_FLOAT_TOLERANCE:
        raise local_sync.VerifyFailure(
            "native minion owner lethal hit did not reach zero life: "
            f"{lethal_hit}"
        )
    absent = wait_for(
        lambda: query_pair(
            pair,
            network_actor_id=network_actor_id,
        ),
        lambda rows: (
            all(row["count"] == 0 for row in rows.values()) and
            all(
                row["terminal_network_actor_id"] ==
                    network_actor_id and
                row["terminal_reason"] ==
                    NATIVE_MINION_TERMINAL_OWNER_DEATH
                for row in rows.values()
            )
        ),
        12.0,
        "owner-death minion teardown",
    )
    progress["absent"] = absent
    return progress


def assert_owner_disconnect_convergence(
    pair: LocalPair,
    expected: dict[int, Path],
    launched: dict[str, Any],
    network_actor_id: int,
    progress: dict[str, Any],
) -> dict[str, Any]:
    client_process_id = int(launched["clientProcessId"])
    stopped = process_guard.stop_owned_processes(
        {
            client_process_id:
                expected[client_process_id],
        }
    )
    progress["stopped"] = stopped
    query = (
        QUERY_GOLEM_LUA
        .replace("__TARGET_ID__", "0")
        .replace(
            "__NETWORK_ACTOR_ID__",
            str(network_actor_id),
        )
    )
    absent = wait_for(
        lambda: values(pair, HOST_ENDPOINT, query),
        lambda row: (
            local_sync.parse_int_text(
                row.get("count"),
                -1,
            ) == 0 and
            local_sync.parse_int_text(
                row.get("terminal_network_actor_id"),
                0,
            ) == network_actor_id and
            local_sync.parse_int_text(
                row.get("terminal_reason"),
                0,
            ) ==
                NATIVE_MINION_TERMINAL_OWNER_DISCONNECTED
        ),
        15.0,
        "owner-disconnect minion teardown",
    )
    progress["host_absent"] = absent
    return progress


def cleanup_exact_owned_processes(
    expected: dict[int, Path],
) -> dict[str, str]:
    return process_guard.stop_owned_processes(expected)


def acquire_raise_golem(
    context: behavior_context.BehaviorContext,
) -> dict[str, dict[str, Any]]:
    secondary.ensure_batch_capacity(
        context.focus_directions,
        [RAISE_GOLEM_ROW],
    )
    return {
        direction.name: secondary.acquire_skill(
            direction,
            RAISE_GOLEM_ROW,
            30.0,
        )
        for direction in context.focus_directions
    }


def run_direction(
    pair: LocalPair,
    context: behavior_context.BehaviorContext,
    direction: focus.Direction,
    acquisition: dict[str, Any],
    evidence_root: Path,
    client_process_id: int,
    client_executable: Path,
    progress: dict[str, Any],
) -> dict[str, Any]:
    progress["direction"] = direction.name
    behavior_context.reset_quiet_arena(
        require_manual_spawner=True
    )
    geometry = prepare_cast(pair, direction)
    progress["geometry"] = geometry
    secondary.set_local_player_vitals(
        direction.source_pipe,
        5000.0,
        5000.0,
        mp=5000.0,
        max_mp=5000.0,
    )
    summon = (
        host_summon
        if direction.source_pipe == HOST_ENDPOINT
        else client_summon
    )(
        pair,
        direction,
        int(acquisition["belt_slot"]),
        float(geometry["target_x"]) +
            GOLEM_SUMMON_OFFSET_X,
        float(geometry["target_y"]),
    )
    progress["summon"] = summon
    visibility = assert_native_minion_visible_and_animating(
        pair,
        int(geometry["target_id"]),
        direction.source_id,
    )
    progress["visibility"] = visibility
    outgoing_damage = assert_exact_damage_convergence(
        pair,
        int(geometry["target_id"]),
    )
    progress["outgoing_damage"] = outgoing_damage
    incoming_damage = assert_incoming_damage_convergence(
        pair,
        int(geometry["target_id"]),
    )
    progress["incoming_damage"] = incoming_damage
    recovery = assert_missing_native_minion_recovery(
        pair,
        int(geometry["target_id"]),
        direction.source_id,
    )
    progress["missing_observer_recovery"] = recovery
    progress["camera_focus"] = focus_pair_cameras(
        pair,
        float(geometry["target_x"]) - 48.0,
        float(geometry["target_y"]),
    )
    try:
        progress["screenshots"] = (
            capture_both_peer_screenshots(
                pair,
                evidence_root / direction.name,
            )
        )
    finally:
        progress["camera_release"] = (
            clear_pair_camera_focus(pair)
        )
    lifecycle: dict[str, Any]
    if direction.source_pipe == HOST_ENDPOINT:
        recast = assert_recast_replacement(
            pair,
            direction,
            int(acquisition["belt_slot"]),
            int(geometry["target_id"]),
            float(geometry["target_x"]),
            float(geometry["target_y"]),
        )
        replacement_visibility = (
            assert_native_minion_visible_and_animating(
                pair,
                int(geometry["target_id"]),
                direction.source_id,
            )
        )
        lifecycle = {
            "recast": recast,
            "replacement_visibility":
                replacement_visibility,
            "despawn":
                assert_native_minion_despawn_convergence(
                    pair,
                    int(
                        recast[
                            "replacement_network_actor_id"
                        ]
                    ),
                    client_process_id,
                    client_executable,
                ),
        }
    else:
        lifecycle = {
            "native_death":
                assert_native_minion_death_convergence(
                    pair,
                    int(geometry["target_id"]),
                ),
        }
    progress["lifecycle"] = lifecycle
    return progress


def run_owner_death(
    pair: LocalPair,
    context: behavior_context.BehaviorContext,
    acquisition: dict[str, Any],
    progress: dict[str, Any],
) -> dict[str, Any]:
    direction = context.focus_directions[0]
    behavior_context.reset_quiet_arena(
        require_manual_spawner=True
    )
    geometry = prepare_cast(pair, direction)
    host_summon(
        pair,
        direction,
        int(acquisition["belt_slot"]),
        float(geometry["target_x"]) +
            GOLEM_SUMMON_OFFSET_X,
        float(geometry["target_y"]),
    )
    visible = assert_native_minion_visible_and_animating(
        pair,
        int(geometry["target_id"]),
        direction.source_id,
    )
    progress["visible"] = visible
    progress["death"] = {}
    assert_owner_death_convergence(
        pair,
        int(
            visible["last"]["host"][
                "network_actor_id"
            ]
        ),
        progress["death"],
    )
    return progress


def run_disconnect(
    evidence_root: Path,
) -> dict[str, Any]:
    launched: dict[str, Any] = {}
    expected: dict[int, Path] = {}
    result: dict[str, Any] = {}
    try:
        launched, pair, expected = launch_pair()
        result["launch"] = launched
        result["run"] = enter_run(pair)
        context = configure_pair(pair)
        acquisitions = acquire_raise_golem(context)
        direction = context.focus_directions[1]
        behavior_context.reset_quiet_arena(
            require_manual_spawner=True
        )
        geometry = prepare_cast(pair, direction)
        result["summon"] = client_summon(
            pair,
            direction,
            int(
                acquisitions[direction.name][
                    "belt_slot"
                ]
            ),
            float(geometry["target_x"]) +
                GOLEM_SUMMON_OFFSET_X,
            float(geometry["target_y"]),
        )
        result["visible"] = (
            assert_native_minion_visible_and_animating(
                pair,
                int(geometry["target_id"]),
                direction.source_id,
            )
        )
        result["screenshots"] = (
            capture_both_peer_screenshots(
                pair,
                evidence_root / "owner_disconnect",
            )
        )
        result["disconnect"] = {}
        assert_owner_disconnect_convergence(
            pair,
            expected,
            launched,
            int(
                result["visible"]["last"]["host"][
                    "network_actor_id"
                ]
            ),
            result["disconnect"],
        )
        return result
    finally:
        if expected:
            result["cleanup"] = (
                cleanup_exact_owned_processes(expected)
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            RUNTIME_ROOT /
            "multiplayer_native_minion_sync.json"
        ),
    )
    parser.add_argument(
        "--evidence-root",
        type=Path,
        required=True,
    )
    args = parser.parse_args()
    result: dict[str, Any] = {
        "ok": False,
        "instance_prefix": INSTANCE_PREFIX,
        "ports": [HOST_PORT, CLIENT_PORT],
        "audio_disabled": True,
    }
    expected: dict[int, Path] = {}
    exit_code = 1
    try:
        launched, pair, expected = launch_pair()
        result["launch"] = launched
        result["run"] = enter_run(pair)
        context = configure_pair(pair)
        acquisitions = acquire_raise_golem(context)
        result["directions"] = []
        for direction in context.focus_directions:
            direction_result: dict[str, Any] = {}
            result["directions"].append(direction_result)
            run_direction(
                pair,
                context,
                direction,
                acquisitions[direction.name],
                args.evidence_root.resolve(),
                int(launched["clientProcessId"]),
                expected[
                    int(launched["clientProcessId"])
                ],
                direction_result,
            )
        result["owner_death"] = {}
        run_owner_death(
            pair,
            context,
            acquisitions["host_owned"],
            result["owner_death"],
        )
        result["cleanup_first_pair"] = (
            cleanup_exact_owned_processes(expected)
        )
        expected = {}
        result["owner_disconnect"] = run_disconnect(
            args.evidence_root.resolve()
        )
        result["ok"] = True
        exit_code = 0
    except Exception as exc:
        result["error"] = (
            f"{type(exc).__name__}: {exc}"
        )
    finally:
        if expected:
            try:
                result["cleanup"] = (
                    cleanup_exact_owned_processes(expected)
                )
            except Exception as exc:
                result["cleanup_error"] = (
                    f"{type(exc).__name__}: {exc}"
                )
                result["ok"] = False
                exit_code = 1
        args.output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        args.output.write_text(
            json.dumps(
                result,
                indent=2,
                sort_keys=True,
            ) + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "ok": result.get("ok"),
                    "error": result.get("error"),
                    "cleanup_error": result.get(
                        "cleanup_error"
                    ),
                    "output": str(args.output),
                },
                indent=2,
                sort_keys=True,
            )
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
