#!/usr/bin/env python3
"""Stress real primary-cast kills against one frozen manual run enemy at a time."""

from __future__ import annotations

import argparse
import json
import math
import time
import traceback
from pathlib import Path
from typing import Any

from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    CLIENT_PIPE,
    HOST_ID,
    HOST_NAME,
    HOST_PIPE,
    ROOT,
    VerifyFailure,
    disable_bots,
    launch_pair,
    lua,
    parse_key_values,
    place_player,
    query,
    resolve_level_ups_from_snapshots,
    snap_to_nav,
    start_host_testrun_and_wait_for_clients,
    stop_games,
    wait_for_remote,
)
from verify_player_health_death_sync import set_local_player_vitals
from verify_real_input_spell_cast_sync import (
    CLIENT_LOG,
    HOST_LOG,
    Direction,
    count_local_native_queues,
    detect_instance_pids,
    log_after,
    log_position,
    parse_phase_counts,
)
from verify_multiplayer_level_up_offer_sync import (
    choose_client_option,
    publish_offer,
    query_progression_entry,
    query_progression_stats,
    wait_for_progression_entry_active,
    wait_for_choice_result,
    wait_for_client_offer,
    wait_for_wait_status,
)


# When False (default), the per-kill forensic captures (stock placement vector
# probes and runtime-context snapshots) are skipped. Those captures add ~20
# PowerShell-bridge round-trips per kill, which is both the dominant latency and
# the dominant source of bridge-timeout fragility on long runs. They carry no
# control-flow meaning -- they are only written into the result record for human
# inspection -- so skipping them on healthy runs is lossless. Failure forensics
# are still captured independently in run_verifier's except handler. Pass
# --diagnostics to re-enable the full per-kill capture when investigating.
DIAGNOSTICS_ENABLED = False
FAST_LUA_TIMEOUT_SECONDS = 8.0

_RUN_START_MONOTONIC: float | None = None


def stage(message: str) -> None:
    """Emit a timestamped, flushed progress line so long runs are observable live."""
    global _RUN_START_MONOTONIC
    now = time.monotonic()
    if _RUN_START_MONOTONIC is None:
        _RUN_START_MONOTONIC = now
    elapsed = now - _RUN_START_MONOTONIC
    # Elapsed comes from a monotonic clock; the wall clock is intentionally
    # omitted because WSL can skew localtime() relative to monotonic, which made
    # the wall timestamps read non-monotonically in earlier runs.
    print(f"[+{elapsed:7.1f}s] {message}", flush=True)


RUNTIME_OUTPUT = ROOT / "runtime" / "multiplayer_primary_kill_stress.json"
HOST_CRASH_LOG = ROOT / "runtime/instances/local-mp-host/stage/.sdmod/logs/solomondarkmodloader.crash.log"
CLIENT_CRASH_LOG = ROOT / "runtime/instances/local-mp-client/stage/.sdmod/logs/solomondarkmodloader.crash.log"
SKELETON_TYPE_ID = 1001
LOW_TARGET_HP = 0.75
SETUP_TARGET_HP = 50000.0
CAST_ATTEMPT_FRAMES = (64, 96, 128)
TARGET_FORWARD_DISTANCE = 176.0
MAX_SCRIPTED_PRIMARY_TARGET_DISTANCE = 260.0
RECEIVER_PARK_DISTANCE = 320.0
HOST_TARGET = (650.0, 1750.0)
# Keep the client-owned lane in the central, projectile-safe region of the
# flat fixture.  The old x=2950 lane was nav-walkable, but native Fireball
# projectiles fail their stricter world-bounds check there and are deleted
# before the actor-hit query runs.
CLIENT_TARGET = (1800.0, 1750.0)
PLAYER_SPAWN_PARK_DISTANCE = 2800.0
PLAYER_SPAWN_PARK_SPACING = 360.0
PLAYER_HEADING_EAST = 90.0
PAIR_POSITION_STABLE_SECONDS = 1.0
PAIR_POSITION_STABLE_TOLERANCE = 1.25
PAIR_REMOTE_SYNC_TOLERANCE = 8.0
# Absolute time a single convergence call may spend resolving natural level-up
# pauses (offer authoring round-trip + choice + pause release), on top of its
# own convergence budget. Bounds the self-healing loop so a pause that never
# clears still surfaces as a failure instead of hanging forever.
LEVEL_UP_RESOLVE_BUDGET = 20.0
LEVEL_UP_PAUSE_LOG_MARKERS = (
    "Multiplayer level-up barrier started.",
    "ActorWorld_Tick held for multiplayer level-up wait.",
)
LANE_HALF_WIDTH = 72.0
LANE_END_PADDING = 96.0
LANE_ACTOR_PADDING = 34.0
DROP_MATCH_RADIUS = 128.0
FORCED_GOLD_AMOUNT = 11
FORCED_GOLD_OFFSET_X = 420.0
FORCED_GOLD_OFFSET_Y = 48.0
FORCED_GOLD_MIN_PLAYER_DISTANCE = 900.0
FORCED_GOLD_STANDABLE_DRIFT_TOLERANCE = 96.0
FORCED_GOLD_CANDIDATE_OFFSETS = (
    (100.0, -1200.0),
    (-960.0, -720.0),
    (960.0, -720.0),
    (-1280.0, FORCED_GOLD_OFFSET_Y),
    (1280.0, FORCED_GOLD_OFFSET_Y),
    (0.0, 1200.0),
    (FORCED_GOLD_OFFSET_X, FORCED_GOLD_OFFSET_Y),
)
FORCED_PICKUP_POSITION_TOLERANCE = 32.0
FORCED_PICKUP_PLACEMENT_ATTEMPTS = 6
FORCED_PICKUP_CONVERGENCE_SECONDS = 0.35
LOOT_GOLD_TYPE_ID = 0x07DC
LOOT_ORB_TYPE_ID = 0x07DB
LOOT_ITEM_DROP_TYPE_ID = 0x07DD
LOOT_POSITION_TOLERANCE = 1.0
ANIMATED_LOOT_POSITION_TOLERANCE = 8.0
LOOT_RADIUS_TOLERANCE = 0.25
LOOT_VALUE_TOLERANCE = 0.01
NATURAL_DROP_WAIT_SECONDS = 1.8
PRIMARY_CAST_HOOK_MARKER = "Multiplayer local primary cast queued from native pure-primary"
RUNTIME_CONTEXT_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local scene = sd.world and sd.world.get_scene and sd.world.get_scene() or nil
emit("scene", scene and (scene.name or scene.kind) or "")
local snap = sd.ui and sd.ui.get_snapshot and sd.ui.get_snapshot() or nil
emit("ui.available", snap ~= nil)
emit("ui.surface", snap and snap.surface_id or "")
emit("ui.title", snap and snap.surface_title or "")
emit("ui.captured_ms", snap and snap.captured_at_milliseconds or 0)
emit("ui.element_count", snap and #(snap.elements or {}) or 0)
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
emit("player.valid", player ~= nil and player.actor_address ~= nil and player.actor_address ~= 0)
emit("player.actor", player and string.format("0x%08X", tonumber(player.actor_address) or 0) or "0x00000000")
emit("player.x", player and player.x or 0)
emit("player.y", player and player.y or 0)
emit("player.heading", player and player.heading or 0)
local input = sd.input and sd.input.get_mouse_left_state and sd.input.get_mouse_left_state() or nil
emit("input.down", input and input.down or false)
emit("input.edge_serial", input and input.edge_serial or 0)
emit("input.edge_tick_ms", input and input.edge_tick_ms or 0)
local mp = sd.runtime and sd.runtime.get_multiplayer_state and sd.runtime.get_multiplayer_state() or nil
emit("mp.valid", mp ~= nil)
emit("mp.session_status", mp and mp.session_status or "")
emit("mp.transport_ready", mp and mp.transport_ready or false)
emit("mp.participant_count", mp and mp.participant_count or 0)
emit("ok", true)
"""
CLEAR_GAMEPLAY_PRIMARY_INPUT_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local function parse_address(value)
  if type(value) == "number" then return tonumber(value) or 0 end
  if type(value) ~= "string" then return 0 end
  local hex = value:match("^0[xX](%x+)$")
  if hex ~= nil then return tonumber(hex, 16) or 0 end
  return tonumber(value) or 0
end
local function safe_read_u8(address)
  local ok, value = pcall(sd.debug.read_u8, address)
  if ok then return tonumber(value) or 0 end
  return -1
end
local function safe_read_i32(address)
  local ok, value = pcall(sd.debug.read_i32, address)
  if ok then return tonumber(value) or -1 end
  return -1
end
local function safe_read_u16(address)
  local ok, value = pcall(sd.debug.read_u16, address)
  if ok then return tonumber(value) or 0 end
  return 0
end
local function safe_read_u32(address)
  local ok, value = pcall(sd.debug.read_u32, address)
  if ok then return tonumber(value) or 0 end
  return 0
end
local function safe_read_ptr(address)
  local ok, value = pcall(sd.debug.read_ptr, address)
  if ok then return tonumber(value) or 0 end
  return 0
end
local function safe_write_i32(address, value)
  local ok, result = pcall(sd.debug.write_i32, address, value)
  return ok and result == true
end
local function safe_write_ptr(address, value)
  local ok, result = pcall(sd.debug.write_ptr, address, value)
  return ok and result == true
end
local function emit_input(prefix)
  local state = nil
  if sd.input ~= nil and sd.input.get_mouse_left_state ~= nil then
    local ok, result = pcall(sd.input.get_mouse_left_state)
    if ok and type(result) == "table" then state = result end
  end
  emit(prefix .. ".input.down", state ~= nil and state.down or false)
  emit(prefix .. ".input.edge_serial", state ~= nil and state.edge_serial or 0)
  emit(prefix .. ".input.edge_tick_ms", state ~= nil and state.edge_tick_ms or 0)
end
local function emit_cast_state(prefix, actor)
  local oskill = sd.debug.layout_offset("actor_primary_skill_id")
  local oprev = sd.debug.layout_offset("actor_previous_skill_id")
  local oe4 = sd.debug.layout_offset("actor_primary_action_latch_e4")
  local oe8 = sd.debug.layout_offset("actor_primary_action_latch_e8")
  local opost = sd.debug.layout_offset("actor_post_gate_active_byte")
  local ospell_group = sd.debug.layout_offset("actor_spell_target_group_byte")
  local ospell_slot = sd.debug.layout_offset("actor_spell_target_slot_short")
  local oselection = sd.debug.layout_offset("actor_animation_selection_state")
  local ots = sd.debug.layout_offset("actor_control_brain_target_slot")
  local oth = sd.debug.layout_offset("actor_control_brain_target_handle")
  local ort = sd.debug.layout_offset("actor_control_brain_retarget_ticks")
  local otc = sd.debug.layout_offset("actor_control_brain_target_cooldown_ticks")
  local oac = sd.debug.layout_offset("actor_control_brain_action_cooldown_ticks")
  local oab = sd.debug.layout_offset("actor_control_brain_action_burst_ticks")
  emit(prefix .. ".skill", actor ~= 0 and oskill ~= nil and safe_read_i32(actor + oskill) or -1)
  emit(prefix .. ".previous", actor ~= 0 and oprev ~= nil and safe_read_i32(actor + oprev) or -1)
  emit(prefix .. ".latch_e4", actor ~= 0 and oe4 ~= nil and safe_read_u32(actor + oe4) or 0)
  emit(prefix .. ".latch_e8", actor ~= 0 and oe8 ~= nil and safe_read_u32(actor + oe8) or 0)
  emit(prefix .. ".post_gate", actor ~= 0 and opost ~= nil and safe_read_u8(actor + opost) or 0)
  emit(prefix .. ".spell_group", actor ~= 0 and ospell_group ~= nil and safe_read_u8(actor + ospell_group) or 255)
  emit(prefix .. ".spell_slot", actor ~= 0 and ospell_slot ~= nil and safe_read_u16(actor + ospell_slot) or 65535)
  local selection = actor ~= 0 and oselection ~= nil and safe_read_ptr(actor + oselection) or 0
  emit(prefix .. ".selection", string.format("0x%08X", selection))
  emit(prefix .. ".selection_target_slot", selection ~= 0 and ots ~= nil and safe_read_u8(selection + ots) or 255)
  emit(prefix .. ".selection_target_handle", selection ~= 0 and oth ~= nil and safe_read_u16(selection + oth) or 65535)
  emit(prefix .. ".selection_retarget_ticks", selection ~= 0 and ort ~= nil and safe_read_i32(selection + ort) or -1)
  emit(prefix .. ".selection_target_cooldown", selection ~= 0 and otc ~= nil and safe_read_i32(selection + otc) or -1)
  emit(prefix .. ".selection_action_cooldown", selection ~= 0 and oac ~= nil and safe_read_i32(selection + oac) or -1)
  emit(prefix .. ".selection_action_burst", selection ~= 0 and oab ~= nil and safe_read_i32(selection + oab) or -1)
end
local scene = sd.world and sd.world.get_scene and sd.world.get_scene() or nil
local gameplay = parse_address(scene and (scene.scene_id or scene.id) or 0)
emit("gameplay", string.format("0x%08X", gameplay))
local cast_intent_offset = sd.debug.layout_offset("gameplay_cast_intent")
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
local actor = tonumber(player and player.actor_address or 0) or 0
emit("player.actor", string.format("0x%08X", actor))
emit_input("before")
if gameplay ~= 0 and cast_intent_offset ~= nil then
  emit("before.cast_intent", safe_read_u8(gameplay + cast_intent_offset))
end
emit_cast_state("before.cast_state", actor)
local clear_ok = false
if sd.input ~= nil and sd.input.clear_mouse_left ~= nil then
  local ok, result = pcall(sd.input.clear_mouse_left)
  clear_ok = ok and result == true
end
emit("clear_mouse_left", clear_ok)
local clear_cast_ok = false
local clear_cast_error = ""
if sd.input ~= nil and sd.input.clear_local_cast_state ~= nil then
  local ok, result = pcall(sd.input.clear_local_cast_state)
  clear_cast_ok = ok and result == true
  if not ok then clear_cast_error = tostring(result) end
end
emit("clear_local_cast_state", clear_cast_ok)
emit("clear_local_cast_state_error", clear_cast_error)
emit_input("after")
if gameplay ~= 0 and cast_intent_offset ~= nil then
  emit("after.cast_intent", safe_read_u8(gameplay + cast_intent_offset))
end
emit_cast_state("after.cast_state", actor)
if actor ~= 0 then
  local target_offset = sd.debug.layout_offset("actor_current_target_actor")
  local target_bucket_offset = sd.debug.layout_offset("actor_current_target_bucket_delta")
  if target_offset ~= nil then emit("player.target.write", safe_write_ptr(actor + target_offset, 0)) end
  if target_bucket_offset ~= nil then emit("player.target_bucket.write", safe_write_i32(actor + target_bucket_offset, 0)) end
end
local projectile_count = 0
local projectile_addresses = {}
for _, actor_state in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  local type_id = tonumber(actor_state.object_type_id) or 0
  if type_id == 0x7D3 or type_id == 0x7D4 or type_id == 0x7D5 then
    projectile_count = projectile_count + 1
    projectile_addresses[#projectile_addresses + 1] = tostring(actor_state.actor_address or 0)
  end
end
emit("projectile_count", projectile_count)
emit("projectile_addresses", table.concat(projectile_addresses, ","))
emit("ok", gameplay ~= 0 and clear_ok)
"""
FAST_CLEAR_GAMEPLAY_PRIMARY_INPUT_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local function parse_address(value)
  if type(value) == "number" then return tonumber(value) or 0 end
  if type(value) ~= "string" then return 0 end
  local hex = value:match("^0[xX](%x+)$")
  if hex ~= nil then return tonumber(hex, 16) or 0 end
  return tonumber(value) or 0
end
local function safe_read_u8(address)
  local ok, value = pcall(sd.debug.read_u8, address)
  if ok then return tonumber(value) or 0 end
  return 0
end
local function safe_write_i32(address, value)
  local ok, result = pcall(sd.debug.write_i32, address, value)
  return ok and result == true
end
local function safe_write_ptr(address, value)
  local ok, result = pcall(sd.debug.write_ptr, address, value)
  return ok and result == true
end
local function emit_input(prefix)
  local state = nil
  if sd.input ~= nil and sd.input.get_mouse_left_state ~= nil then
    local ok, result = pcall(sd.input.get_mouse_left_state)
    if ok and type(result) == "table" then state = result end
  end
  emit(prefix .. ".input.down", state ~= nil and state.down or false)
  emit(prefix .. ".input.edge_serial", state ~= nil and state.edge_serial or 0)
  emit(prefix .. ".input.edge_tick_ms", state ~= nil and state.edge_tick_ms or 0)
end
local scene = sd.world and sd.world.get_scene and sd.world.get_scene() or nil
local gameplay = parse_address(scene and (scene.scene_id or scene.id) or 0)
local cast_intent_offset = sd.debug.layout_offset("gameplay_cast_intent")
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
local actor = tonumber(player and player.actor_address or 0) or 0
emit("gameplay", string.format("0x%08X", gameplay))
emit("player.actor", string.format("0x%08X", actor))
emit_input("before")
if gameplay ~= 0 and cast_intent_offset ~= nil then
  emit("before.cast_intent", safe_read_u8(gameplay + cast_intent_offset))
end
local clear_ok = false
if sd.input ~= nil and sd.input.clear_mouse_left ~= nil then
  local ok, result = pcall(sd.input.clear_mouse_left)
  clear_ok = ok and result == true
end
emit("clear_mouse_left", clear_ok)
local clear_cast_ok = false
local clear_cast_error = ""
if sd.input ~= nil and sd.input.clear_local_cast_state ~= nil then
  local ok, result = pcall(sd.input.clear_local_cast_state)
  clear_cast_ok = ok and result == true
  if not ok then clear_cast_error = tostring(result) end
end
emit("clear_local_cast_state", clear_cast_ok)
emit("clear_local_cast_state_error", clear_cast_error)
emit_input("after")
if gameplay ~= 0 and cast_intent_offset ~= nil then
  emit("after.cast_intent", safe_read_u8(gameplay + cast_intent_offset))
end
if actor ~= 0 then
  local target_offset = sd.debug.layout_offset("actor_current_target_actor")
  local target_bucket_offset = sd.debug.layout_offset("actor_current_target_bucket_delta")
  if target_offset ~= nil then emit("player.target.write", safe_write_ptr(actor + target_offset, 0)) end
  if target_bucket_offset ~= nil then emit("player.target_bucket.write", safe_write_i32(actor + target_bucket_offset, 0)) end
end
local projectile_count = 0
for _, actor_state in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  local type_id = tonumber(actor_state.object_type_id) or 0
  if type_id == 0x7D3 or type_id == 0x7D4 or type_id == 0x7D5 then
    projectile_count = projectile_count + 1
  end
end
emit("projectile_count", projectile_count)
emit("ok", gameplay ~= 0 and clear_ok)
"""


def values(pipe_name: str, code: str, timeout: float = 8.0) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, code, timeout=timeout))


def pipe_runtime_context(pipe_name: str, timeout: float = 3.0) -> dict[str, Any]:
    try:
        return {"ok": True, **values(pipe_name, RUNTIME_CONTEXT_LUA, timeout=timeout)}
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
        }


def capture_runtime_context(label: str, *, include_processes: bool = False) -> dict[str, Any]:
    context: dict[str, Any] = {
        "label": label,
        "captured_at": time.time(),
        "host": pipe_runtime_context(HOST_PIPE),
        "client": pipe_runtime_context(CLIENT_PIPE),
    }
    if include_processes:
        try:
            context["pids"] = detect_instance_pids()
        except Exception as exc:
            context["pids_error"] = str(exc)
    return context


def append_runtime_context(record: dict[str, Any], label: str) -> None:
    if not DIAGNOSTICS_ENABLED:
        return
    record.setdefault("runtime_context", []).append(capture_runtime_context(label))


def clear_gameplay_mouse_left(pipe_name: str) -> dict[str, str]:
    return values(
        pipe_name,
        FAST_CLEAR_GAMEPLAY_PRIMARY_INPUT_LUA,
        timeout=FAST_LUA_TIMEOUT_SECONDS,
    )


def clear_gameplay_mouse_left_diagnostics(pipe_name: str) -> dict[str, str]:
    return values(pipe_name, CLEAR_GAMEPLAY_PRIMARY_INPUT_LUA, timeout=4.0)


def projectile_count(state: dict[str, str]) -> int:
    return parse_int(state.get("projectile_count"))


def truthy(value: str | None) -> bool:
    return value in {"true", "True", "1"}


def primary_input_released(state: dict[str, str]) -> bool:
    if parse_int(state.get("after.cast_intent"), 0) != 0:
        return False
    return not truthy(state.get("after.input.down"))


def quiesce_gameplay_primary_input(label: str, stable_seconds: float = 0.9) -> dict[str, Any]:
    # The stable window is a *detection* window, not a settle delay: input is
    # already cleared on both sides and the players are parked (god mode, bots
    # off), so the only way a new primary cast can appear is a stuck/repeating
    # input latch, which fires every frame. ~0.9s (~54 frames at 60fps) is ample
    # to catch a repeating cast hook or an in-flight projectile; the retry loop
    # below re-arms if anything is detected. 2.75s was pure dead time per call.
    attempts: list[dict[str, Any]] = []
    for attempt in range(1, 7):
        host_offset = log_position(HOST_LOG)
        client_offset = log_position(CLIENT_LOG)
        host_clear_before = clear_gameplay_mouse_left(HOST_PIPE)
        client_clear_before = clear_gameplay_mouse_left(CLIENT_PIPE)
        time.sleep(stable_seconds)
        host_clear_after = clear_gameplay_mouse_left(HOST_PIPE)
        client_clear_after = clear_gameplay_mouse_left(CLIENT_PIPE)
        host_delta = log_after(HOST_LOG, host_offset)
        client_delta = log_after(CLIENT_LOG, client_offset)
        host_casts = host_delta.count(PRIMARY_CAST_HOOK_MARKER)
        client_casts = client_delta.count(PRIMARY_CAST_HOOK_MARKER)
        host_projectiles = projectile_count(host_clear_after)
        client_projectiles = projectile_count(client_clear_after)
        host_input_released = primary_input_released(host_clear_after)
        client_input_released = primary_input_released(client_clear_after)
        attempt_result = {
            "attempt": attempt,
            "host_clear_before": host_clear_before,
            "client_clear_before": client_clear_before,
            "host_clear_after": host_clear_after,
            "client_clear_after": client_clear_after,
            "host_primary_cast_hooks": host_casts,
            "client_primary_cast_hooks": client_casts,
            "host_projectile_count": host_projectiles,
            "client_projectile_count": client_projectiles,
            "host_input_released": host_input_released,
            "client_input_released": client_input_released,
            "stable_seconds": stable_seconds,
        }
        attempts.append(attempt_result)
        if (
            host_casts == 0
            and client_casts == 0
            and host_projectiles == 0
            and client_projectiles == 0
            and host_input_released
            and client_input_released
        ):
            return {"ok": True, "label": label, "attempts": attempts}
        time.sleep(0.15)
    diagnostics: dict[str, Any] = {}
    try:
        diagnostics["host"] = clear_gameplay_mouse_left_diagnostics(HOST_PIPE)
    except Exception as exc:
        diagnostics["host_error"] = str(exc)
    try:
        diagnostics["client"] = clear_gameplay_mouse_left_diagnostics(CLIENT_PIPE)
    except Exception as exc:
        diagnostics["client_error"] = str(exc)
    raise VerifyFailure(
        f"{label}: gameplay primary input did not quiesce before manual spawn: "
        f"attempts={attempts[-3:]} diagnostics={diagnostics}"
    )


def parse_int(value: str | None, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        if value.startswith(("0x", "0X")):
            return int(value, 16)
        return int(float(value))
    except (TypeError, ValueError):
        return default


def parse_float(value: str | None, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes"}


def distance(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(ax - bx, ay - by)


def row_values(raw: dict[str, str], prefix: str, count_key: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for index in range(1, parse_int(raw.get(count_key)) + 1):
        row_prefix = f"{prefix}.{index}."
        row = {
            key[len(row_prefix):]: value
            for key, value in raw.items()
            if key.startswith(row_prefix)
        }
        if row:
            rows.append(row)
    return rows


COMBAT_STATE_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local state = sd.gameplay and sd.gameplay.get_combat_state and sd.gameplay.get_combat_state() or nil
emit("valid", state ~= nil)
emit("active", state and state.active or false)
emit("music_started", state and state.music_started or false)
emit("wave_index", state and state.wave_index or 0)
emit("wave_counter", state and state.wave_counter or 0)
emit("transition_requested", state and state.transition_requested or false)
"""


STOCK_PLACEMENT_VECTOR_LUA = r"""
local label = "__LABEL__"
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local function hx(v) return string.format("0x%08X", tonumber(v) or 0) end
local function read_ptr(address)
  local ok, value = pcall(sd.debug.read_ptr, address)
  if not ok then return 0 end
  return tonumber(value) or 0
end
local function read_i32(address)
  local ok, value = pcall(sd.debug.read_i32, address)
  if not ok then return 0 end
  return tonumber(value) or 0
end
local function read_u8(address)
  local ok, value = pcall(sd.debug.read_u8, address)
  if not ok then return 0 end
  return tonumber(value) or 0
end
local function read_float(address)
  local ok, value = pcall(sd.debug.read_float, address)
  if not ok then return 0.0 end
  return tonumber(value) or 0.0
end
local function query(address)
  local ok, value = pcall(sd.debug.query_memory, address)
  if ok and type(value) == "table" then return value end
  return nil
end
local vector_base = 0x00819EC0
local data_slot = 0x00819EC4
local count_slot = 0x00819EC8
local lock_slot = 0x00819ECC
local resolved_base = sd.debug.resolve_game_address(vector_base) or 0
local resolved_data_slot = sd.debug.resolve_game_address(data_slot) or 0
local resolved_count_slot = sd.debug.resolve_game_address(count_slot) or 0
local resolved_lock_slot = sd.debug.resolve_game_address(lock_slot) or 0
local data = resolved_data_slot ~= 0 and read_ptr(resolved_data_slot) or 0
local count = resolved_count_slot ~= 0 and read_i32(resolved_count_slot) or 0
local locked = resolved_lock_slot ~= 0 and read_u8(resolved_lock_slot) or 0
local slot_memory = resolved_data_slot ~= 0 and query(resolved_data_slot) or nil
local data_memory = data ~= 0 and query(data) or nil
emit("label", label)
emit("vector_base", hx(resolved_base))
emit("data_slot", hx(resolved_data_slot))
emit("count_slot", hx(resolved_count_slot))
emit("lock_slot", hx(resolved_lock_slot))
emit("data", hx(data))
emit("count", count)
emit("locked", locked)
emit("slot_readable", slot_memory and slot_memory.readable or false)
emit("slot_translated", slot_memory and slot_memory.translated or false)
emit("data_readable", data_memory and data_memory.readable or false)
emit("data_base", data_memory and hx(data_memory.base or 0) or "0x00000000")
emit("valid", data ~= 0 and data ~= 0x10 and count >= 0 and count <= 64 and data_memory ~= nil and data_memory.readable == true)
if data ~= 0 and data_memory ~= nil and data_memory.readable == true then
  for index = 0, math.min(count - 1, 4) do
    local entry = data + index * 8
    emit("entry." .. tostring(index) .. ".a_u32", hx(read_i32(entry)))
    emit("entry." .. tostring(index) .. ".b_u32", hx(read_i32(entry + 4)))
    emit("entry." .. tostring(index) .. ".a_f32", string.format("%.3f", read_float(entry)))
    emit("entry." .. tostring(index) .. ".b_f32", string.format("%.3f", read_float(entry + 4)))
  end
end
local combat = sd.gameplay and sd.gameplay.get_combat_state and sd.gameplay.get_combat_state() or nil
emit("combat.valid", combat ~= nil)
emit("combat.active", combat and combat.active or false)
emit("combat.wave_index", combat and combat.wave_index or 0)
emit("combat.wave_counter", combat and combat.wave_counter or 0)
local scene = sd.world and sd.world.get_scene and sd.world.get_scene() or nil
emit("scene", scene and (scene.name or scene.scene or scene.kind) or "")
"""


ENABLE_PRELUDE_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
emit("ok", sd.gameplay.enable_combat_prelude())
"""


START_WAVES_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
emit("ok", sd.gameplay.start_waves())
"""


SET_MANUAL_SPAWNER_TEST_MODE_LUA = r"""
local enabled = __ENABLED__
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local ok, active = sd.gameplay.set_manual_enemy_spawner_test_mode(enabled)
emit("ok", ok)
emit("active", active)
"""


MANUAL_SPAWNER_STATE_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local state = sd.gameplay.get_manual_enemy_spawner_state()
emit("manual_mode", state and state.manual_mode or false)
emit("has_spawner", state and state.has_spawner or false)
emit("spawner_address", state and state.spawner_address or 0)
emit("spawner_id", state and state.spawner_id or "")
"""


CLEANUP_LIVE_ENEMIES_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local hp_offset = sd.debug.layout_offset("enemy_current_hp")
local x_offset = sd.debug.layout_offset("actor_position_x")
local y_offset = sd.debug.layout_offset("actor_position_y")
local cleaned = 0
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  local address = tonumber(actor.actor_address) or 0
  local hp = tonumber(actor.hp) or 0
  if address ~= 0 and actor.tracked_enemy and not actor.dead and hp > 0.05 then
    if hp_offset ~= nil then sd.debug.write_float(address + hp_offset, 0.0) end
    if sd.world.trigger_enemy_death ~= nil then sd.world.trigger_enemy_death(address) end
    if x_offset ~= nil then sd.debug.write_float(address + x_offset, 100000.0 + cleaned * 400.0) end
    if y_offset ~= nil then sd.debug.write_float(address + y_offset, 100000.0 + cleaned * 400.0) end
    cleaned = cleaned + 1
  end
end
emit("cleaned", cleaned)
"""


LIVE_ENEMY_COUNT_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local count = 0
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  if actor.tracked_enemy and not actor.dead and (tonumber(actor.hp) or 0) > 0.05 then
    count = count + 1
  end
end
emit("live_enemy_count", count)
"""


CLEAR_CAST_LANE_LUA = r"""
local source_x = tonumber("__SOURCE_X__") or 0
local source_y = tonumber("__SOURCE_Y__") or 0
local target_x = tonumber("__TARGET_X__") or 0
local target_y = tonumber("__TARGET_Y__") or 0
local half_width = tonumber("__HALF_WIDTH__") or 72
local end_padding = tonumber("__END_PADDING__") or 96
local actor_padding = tonumber("__ACTOR_PADDING__") or 34
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local dx = target_x - source_x
local dy = target_y - source_y
local len_sq = dx * dx + dy * dy
if len_sq < 1 then
  emit("ok", false)
  emit("blocked", true)
  emit("reason", "degenerate lane")
  return
end
local len = math.sqrt(len_sq)
local blocked = {}
local blocker_count = 0
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  local address = tonumber(actor.actor_address) or 0
  local ax = tonumber(actor.x) or 0
  local ay = tonumber(actor.y) or 0
  local radius = math.max(tonumber(actor.radius) or 0, 0)
  local object_type_id = tonumber(actor.object_type_id) or 0
  local progression = tonumber(actor.progression_runtime_address) or 0
  local is_player_like = progression ~= 0
  local is_enemy = actor.tracked_enemy == true
  local is_drop = object_type_id == 0x07DB or object_type_id == 0x07DC or object_type_id == 0x07DD
  if address ~= 0 and not is_player_like and not is_enemy and not is_drop and not actor.dead then
    local wx = ax - source_x
    local wy = ay - source_y
    local t_len = (wx * dx + wy * dy) / len
    local closest_x
    local closest_y
    if t_len < 0 then
      closest_x = source_x
      closest_y = source_y
    elseif t_len > len then
      closest_x = target_x
      closest_y = target_y
    else
      local t = t_len / len
      closest_x = source_x + dx * t
      closest_y = source_y + dy * t
    end
    local pdx = ax - closest_x
    local pdy = ay - closest_y
    local dist = math.sqrt(pdx * pdx + pdy * pdy)
    local in_span = t_len >= -end_padding and t_len <= len + end_padding
    local limit = half_width + radius + actor_padding
    if in_span and dist <= limit then
      blocker_count = blocker_count + 1
      blocked[blocker_count] = {
        address = address,
        object_type_id = object_type_id,
        x = ax,
        y = ay,
        radius = radius,
        distance = dist,
        t_len = t_len,
      }
    end
  end
end
table.sort(blocked, function(a, b) return a.distance < b.distance end)
emit("ok", blocker_count == 0)
emit("blocked", blocker_count > 0)
emit("blocker_count", blocker_count)
if blocker_count > 0 then
  local first = blocked[1]
  emit("blocker_address", first.address)
  emit("blocker_type", first.object_type_id)
  emit("blocker_x", string.format("%.3f", first.x))
  emit("blocker_y", string.format("%.3f", first.y))
  emit("blocker_radius", string.format("%.3f", first.radius))
  emit("blocker_distance", string.format("%.3f", first.distance))
  emit("blocker_t", string.format("%.3f", first.t_len))
end
"""


SPAWN_MANUAL_ENEMY_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local ok, err, request_id = sd.gameplay.spawn_manual_run_enemy({
  type_id = __TYPE_ID__,
  x = __X__,
  y = __Y__,
  freeze_on_spawn = __FREEZE_ON_SPAWN__
})
emit("ok", ok)
emit("err", err or "")
emit("request_id", request_id or 0)
"""


SPAWN_RESULT_LUA = r"""
local request_id = tonumber("__REQUEST_ID__") or 0
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local result = sd.gameplay.get_last_manual_run_enemy_spawn(request_id)
emit("present", result ~= nil)
if result == nil then return end
emit("valid", result.valid or false)
emit("ok", result.ok or false)
emit("request_id", result.request_id or 0)
emit("type_id", result.type_id or 0)
emit("actor_address", result.actor_address or 0)
emit("actor_id", result.actor_id or "")
emit("network_actor_id", string.format("%.0f", tonumber(result.network_actor_id) or 0))
emit("requested_x", string.format("%.3f", tonumber(result.requested_x) or 0))
emit("requested_y", string.format("%.3f", tonumber(result.requested_y) or 0))
emit("x", string.format("%.3f", tonumber(result.x) or 0))
emit("y", string.format("%.3f", tonumber(result.y) or 0))
emit("wrote_x", result.wrote_x or false)
emit("wrote_y", result.wrote_y or false)
emit("rebind_ok", result.rebind_ok or false)
emit("rebind_exception_code", result.rebind_exception_code or 0)
emit("error", result.error or "")
"""


CONFIGURE_ENEMY_LUA = r"""
local actor_address = tonumber("__ACTOR__") or 0
local x = tonumber("__X__") or 0
local y = tonumber("__Y__") or 0
local hp = tonumber("__HP__") or 0.75
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local death_offset = sd.debug.layout_offset("enemy_death_handled")
local x_offset = sd.debug.layout_offset("actor_position_x")
local y_offset = sd.debug.layout_offset("actor_position_y")
local target_offset = sd.debug.layout_offset("actor_current_target_actor")
local target_bucket_offset = sd.debug.layout_offset("actor_current_target_bucket_delta")
emit("actor_address", actor_address)
emit("write_x", x_offset ~= nil and sd.debug.write_float(actor_address + x_offset, x) or false)
emit("write_y", y_offset ~= nil and sd.debug.write_float(actor_address + y_offset, y) or false)
emit("write_health", sd.gameplay.set_run_enemy_health(actor_address, hp, hp))
if death_offset ~= nil then emit("write_death", sd.debug.write_u8(actor_address + death_offset, 0)) end
if target_offset ~= nil then emit("write_target", sd.debug.write_ptr(actor_address + target_offset, 0)) end
if target_bucket_offset ~= nil then emit("write_target_bucket", sd.debug.write_i32(actor_address + target_bucket_offset, 0)) end
if sd.world ~= nil and sd.world.rebind_actor ~= nil then
  local ok, err = sd.world.rebind_actor(actor_address)
  emit("rebind", ok)
  emit("rebind_err", err or "")
end
emit("ok", true)
"""


FIND_TARGET_LUA = r"""
local wanted_network_id = tonumber("__NETWORK_ID__") or 0
local target_x = tonumber("__X__") or 0
local target_y = tonumber("__Y__") or 0
local radius = tonumber("__RADIUS__") or 360
local verbose = __VERBOSE__
local radius_sq = radius * radius
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local function hx(v) return string.format("0x%08X", tonumber(v) or 0) end
local death_offset = sd.debug.layout_offset("enemy_death_handled")
local local_by_address = {}
local live_local = 0
local live_diag_count = 0
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  local address = tonumber(actor.actor_address) or 0
  if address ~= 0 then local_by_address[address] = actor end
  if actor.tracked_enemy and not actor.dead and (tonumber(actor.hp) or 0) > 0.05 then
    live_local = live_local + 1
    if verbose and live_diag_count < 8 then
      local prefix = "live." .. tostring(live_diag_count)
      emit(prefix .. ".actor_address", hx(address))
      emit(prefix .. ".type_id", actor.object_type_id or 0)
      emit(prefix .. ".enemy_type", actor.enemy_type or -1)
      emit(prefix .. ".x", string.format("%.3f", tonumber(actor.x) or 0))
      emit(prefix .. ".y", string.format("%.3f", tonumber(actor.y) or 0))
      emit(prefix .. ".hp", string.format("%.3f", tonumber(actor.hp) or 0))
      emit(prefix .. ".max_hp", string.format("%.3f", tonumber(actor.max_hp) or 0))
      emit(prefix .. ".dead", actor.dead or false)
      emit(prefix .. ".tracked", actor.tracked_enemy or false)
      emit(prefix .. ".distance", string.format("%.3f", math.sqrt(((tonumber(actor.x) or 0) - target_x) ^ 2 + ((tonumber(actor.y) or 0) - target_y) ^ 2)))
      live_diag_count = live_diag_count + 1
    end
  end
end
emit("live_local_count", live_local)
local replicated = sd.world.get_replicated_actors and sd.world.get_replicated_actors() or nil
emit("rep.valid", replicated ~= nil)
emit("rep.actor_count", replicated and replicated.actor_count or 0)
emit("rep.binding_count", replicated and replicated.binding_count or 0)
emit("rep.apply_valid", replicated and replicated.apply_valid or false)
emit("rep.apply_holding_stale_snapshot", replicated and replicated.apply_holding_stale_snapshot or false)
emit("rep.apply_source_snapshot_age_ms", replicated and replicated.apply_source_snapshot_age_ms or 0)
emit("rep.sequence", replicated and replicated.sequence or 0)
emit("rep.scene_epoch", replicated and replicated.scene_epoch or 0)
emit("rep.received_ms", replicated and replicated.received_ms or 0)
emit("rep.age_ms", replicated and math.max(0, (tonumber(replicated.sampled_ms) or 0) - (tonumber(replicated.received_ms) or 0)) or 0)
emit("rep.apply_sequence", replicated and replicated.apply_sequence or 0)
emit("rep.apply_scene_epoch", replicated and replicated.apply_scene_epoch or 0)
emit("rep.applied_ms", replicated and replicated.applied_ms or 0)
emit("rep.apply_age_ms", replicated and math.max(0, (tonumber(replicated.sampled_ms) or 0) - (tonumber(replicated.applied_ms) or 0)) or 0)
emit("rep.local_actor_count", replicated and replicated.local_actor_count or 0)
emit("rep.matched_actor_count", replicated and replicated.matched_actor_count or 0)
local local_by_network = {}
if replicated and replicated.bindings then
  local binding_diag_count = 0
  for _, binding in ipairs(replicated.bindings) do
    local id = tonumber(binding.network_actor_id) or 0
    local address = tonumber(binding.local_actor_address) or 0
    if id ~= 0 and address ~= 0 and binding.matched and not binding.parked and not binding.removed then
      local_by_network[id] = local_by_address[address]
    end
    if verbose and binding_diag_count < 8 then
      local prefix = "binding." .. tostring(binding_diag_count)
      emit(prefix .. ".network_id", string.format("%.0f", id))
      emit(prefix .. ".local_actor_address", hx(address))
      emit(prefix .. ".matched", binding.matched or false)
      emit(prefix .. ".parked", binding.parked or false)
      emit(prefix .. ".removed", binding.removed or false)
      binding_diag_count = binding_diag_count + 1
    end
  end
end
local best = nil
local best_d2 = nil
local nearest = nil
local nearest_d2 = nil
local rep_diag_count = 0
local replicated_tracked_actor_count = 0
if replicated and replicated.actors then
  for _, actor in ipairs(replicated.actors) do
    local id = tonumber(actor.network_actor_id) or 0
    local x = tonumber(actor.x) or 0
    local y = tonumber(actor.y) or 0
    local hp = tonumber(actor.hp) or 0
    local max_hp = tonumber(actor.max_hp) or 0
    local dead = actor.dead and true or false
    local tracked = actor.tracked_enemy and true or false
    if tracked then
      replicated_tracked_actor_count = replicated_tracked_actor_count + 1
    end
    local matches_id = wanted_network_id ~= 0 and id == wanted_network_id
    local dx = x - target_x
    local dy = y - target_y
    local d2 = dx * dx + dy * dy
    if tracked and (nearest == nil or d2 < nearest_d2) then
      nearest = actor
      nearest_d2 = d2
    end
    if verbose and rep_diag_count < 8 then
      local prefix = "rep." .. tostring(rep_diag_count)
      emit(prefix .. ".network_id", string.format("%.0f", id))
      emit(prefix .. ".type_id", actor.object_type_id or 0)
      emit(prefix .. ".enemy_type", actor.enemy_type or -1)
      emit(prefix .. ".x", string.format("%.3f", x))
      emit(prefix .. ".y", string.format("%.3f", y))
      emit(prefix .. ".hp", string.format("%.3f", hp))
      emit(prefix .. ".max_hp", string.format("%.3f", max_hp))
      emit(prefix .. ".dead", dead)
      emit(prefix .. ".tracked", tracked)
      emit(prefix .. ".distance", string.format("%.3f", math.sqrt(d2)))
      rep_diag_count = rep_diag_count + 1
    end
    if tracked and (matches_id or (wanted_network_id == 0 and d2 <= radius_sq)) then
      if best == nil or matches_id or d2 < best_d2 then
        best = actor
        best_d2 = d2
      end
    end
  end
end
emit("rep.tracked_actor_count", replicated_tracked_actor_count)
emit("found", best ~= nil)
if verbose and best == nil and nearest ~= nil then
  emit("nearest.network_id", string.format("%.0f", tonumber(nearest.network_actor_id) or 0))
  emit("nearest.type_id", nearest.object_type_id or 0)
  emit("nearest.enemy_type", nearest.enemy_type or -1)
  emit("nearest.x", string.format("%.3f", tonumber(nearest.x) or 0))
  emit("nearest.y", string.format("%.3f", tonumber(nearest.y) or 0))
  emit("nearest.hp", string.format("%.3f", tonumber(nearest.hp) or 0))
  emit("nearest.max_hp", string.format("%.3f", tonumber(nearest.max_hp) or 0))
  emit("nearest.dead", nearest.dead or false)
  emit("nearest.tracked", nearest.tracked_enemy or false)
  emit("nearest.distance", string.format("%.3f", math.sqrt(nearest_d2 or 0)))
end
if best == nil then return end
local network_id = tonumber(best.network_actor_id) or 0
local local_actor = local_by_network[network_id]
emit("network_id", string.format("%.0f", network_id))
emit("snapshot.x", string.format("%.3f", tonumber(best.x) or 0))
emit("snapshot.y", string.format("%.3f", tonumber(best.y) or 0))
emit("snapshot.hp", string.format("%.3f", tonumber(best.hp) or 0))
emit("snapshot.max_hp", string.format("%.3f", tonumber(best.max_hp) or 0))
emit("snapshot.dead", best.dead or false)
emit("snapshot.tracked", best.tracked_enemy or false)
emit("snapshot.enemy_type", best.enemy_type or -1)
emit("snapshot.distance", string.format("%.3f", math.sqrt(best_d2 or 0)))
emit("local.found", local_actor ~= nil)
if local_actor ~= nil then
  local address = tonumber(local_actor.actor_address) or 0
  emit("local.actor_address", hx(address))
  emit("local.x", string.format("%.3f", tonumber(local_actor.x) or 0))
  emit("local.y", string.format("%.3f", tonumber(local_actor.y) or 0))
  emit("local.hp", string.format("%.3f", tonumber(local_actor.hp) or 0))
  emit("local.max_hp", string.format("%.3f", tonumber(local_actor.max_hp) or 0))
  emit("local.dead", local_actor.dead or false)
  emit("local.enemy_type", local_actor.enemy_type or -1)
  emit("local.death_handled", death_offset ~= nil and (sd.debug.read_u8(address + death_offset) or 0) or 0)
end
"""


INSPECT_ACTOR_LUA = r"""
local actor_address = tonumber("__ACTOR__") or 0
local target_x = tonumber("__X__") or 0
local target_y = tonumber("__Y__") or 0
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local function hx(v) return string.format("0x%08X", tonumber(v) or 0) end
local function safe_read_float(address)
  if address == nil or address == 0 then return nil end
  local ok, value = pcall(sd.debug.read_float, address)
  if ok then return tonumber(value) end
  return nil
end
local function safe_read_u8(address)
  if address == nil or address == 0 then return nil end
  local ok, value = pcall(sd.debug.read_u8, address)
  if ok then return tonumber(value) end
  return nil
end
local function safe_read_i32(address)
  if address == nil or address == 0 then return nil end
  local ok, value = pcall(sd.debug.read_i32, address)
  if ok then return tonumber(value) end
  return nil
end
emit("actor_address", hx(actor_address))
local x_offset = sd.debug.layout_offset("actor_position_x")
local y_offset = sd.debug.layout_offset("actor_position_y")
local death_offset = sd.debug.layout_offset("enemy_death_handled")
local hp_offset = sd.debug.layout_offset("actor_health")
local max_hp_offset = sd.debug.layout_offset("actor_max_health")
local type_offset = sd.debug.layout_offset("actor_object_type_id")
emit("raw.x", x_offset ~= nil and string.format("%.3f", safe_read_float(actor_address + x_offset) or -999999) or "offset_missing")
emit("raw.y", y_offset ~= nil and string.format("%.3f", safe_read_float(actor_address + y_offset) or -999999) or "offset_missing")
emit("raw.hp", hp_offset ~= nil and string.format("%.3f", safe_read_float(actor_address + hp_offset) or -999999) or "offset_missing")
emit("raw.max_hp", max_hp_offset ~= nil and string.format("%.3f", safe_read_float(actor_address + max_hp_offset) or -999999) or "offset_missing")
emit("raw.death_handled", death_offset ~= nil and (safe_read_u8(actor_address + death_offset) or -1) or "offset_missing")
emit("raw.type_id", type_offset ~= nil and (safe_read_i32(actor_address + type_offset) or -1) or "offset_missing")
local in_list = false
local live_count = 0
local nearest_distance = nil
local nearest_address = 0
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  local address = tonumber(actor.actor_address) or 0
  if address == actor_address then
    in_list = true
    emit("list.match.type_id", actor.object_type_id or 0)
    emit("list.match.x", string.format("%.3f", tonumber(actor.x) or 0))
    emit("list.match.y", string.format("%.3f", tonumber(actor.y) or 0))
    emit("list.match.hp", string.format("%.3f", tonumber(actor.hp) or 0))
    emit("list.match.max_hp", string.format("%.3f", tonumber(actor.max_hp) or 0))
    emit("list.match.dead", actor.dead or false)
    emit("list.match.tracked", actor.tracked_enemy or false)
  end
  if actor.tracked_enemy and not actor.dead and (tonumber(actor.hp) or 0) > 0.05 then
    live_count = live_count + 1
    local dx = (tonumber(actor.x) or 0) - target_x
    local dy = (tonumber(actor.y) or 0) - target_y
    local distance = math.sqrt(dx * dx + dy * dy)
    if nearest_distance == nil or distance < nearest_distance then
      nearest_distance = distance
      nearest_address = address
    end
  end
end
emit("list.found", in_list)
emit("list.live_count", live_count)
emit("list.nearest_address", hx(nearest_address))
emit("list.nearest_distance", nearest_distance ~= nil and string.format("%.3f", nearest_distance) or "none")
local replicated = sd.world.get_replicated_actors and sd.world.get_replicated_actors() or nil
emit("rep.valid", replicated ~= nil)
emit("rep.actor_count", replicated and replicated.actor_count or 0)
emit("rep.binding_count", replicated and replicated.binding_count or 0)
local found_binding = false
if replicated and replicated.bindings then
  for _, binding in ipairs(replicated.bindings) do
    local local_address = tonumber(binding.local_actor_address) or 0
    if local_address == actor_address then
      found_binding = true
      emit("binding.network_id", string.format("%.0f", tonumber(binding.network_actor_id) or 0))
      emit("binding.matched", binding.matched or false)
      emit("binding.parked", binding.parked or false)
      emit("binding.removed", binding.removed or false)
    end
  end
end
emit("binding.found", found_binding)
"""


RUN_ENEMY_BY_NETWORK_ID_LUA = r"""
local network_actor_id = tonumber("__NETWORK_ID__") or 0
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local actor = sd.world.get_run_enemy_by_network_id and sd.world.get_run_enemy_by_network_id(network_actor_id) or nil
emit("found", actor ~= nil)
emit("network_actor_id", string.format("%.0f", network_actor_id))
if actor ~= nil then
  emit("actor_address", string.format("0x%08X", tonumber(actor.actor_address) or 0))
  emit("object_type_id", actor.object_type_id or 0)
  emit("enemy_type", actor.enemy_type or -1)
  emit("x", string.format("%.3f", tonumber(actor.x) or 0))
  emit("y", string.format("%.3f", tonumber(actor.y) or 0))
  emit("hp", string.format("%.3f", tonumber(actor.hp) or 0))
  emit("max_hp", string.format("%.3f", tonumber(actor.max_hp) or 0))
  emit("dead", actor.dead or false)
  emit("tracked", actor.tracked_enemy or false)
end
"""


PREPARE_AND_QUEUE_CASTER_LUA = r"""
local target_actor = tonumber("__TARGET_ACTOR__") or 0
local target_x = tonumber("__TARGET_X__") or 0
local target_y = tonumber("__TARGET_Y__") or 0
local heading = tonumber("__HEADING__") or 90
local frames = tonumber("__FRAMES__") or 1
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local function read_ptr(address)
  if address == nil or address == 0 then return 0 end
  local ok, value = pcall(sd.debug.read_ptr, address)
  if ok then return tonumber(value) or 0 end
  return 0
end
local function read_float(address)
  if address == nil or address == 0 then return 0 end
  local ok, value = pcall(sd.debug.read_float, address)
  if ok then return tonumber(value) or 0 end
  return 0
end
local player = sd.player.get_state()
if player == nil or player.actor_address == nil or player.actor_address == 0 then
  emit("ok", false)
  emit("reason", "player_missing")
  return
end
local actor = tonumber(player.actor_address) or 0
local heading_offset = sd.debug.layout_offset("actor_heading")
local aim_x_offset = sd.debug.layout_offset("actor_aim_target_x")
local aim_y_offset = sd.debug.layout_offset("actor_aim_target_y")
local aim_aux0_offset = sd.debug.layout_offset("actor_aim_target_aux0")
local aim_aux1_offset = sd.debug.layout_offset("actor_aim_target_aux1")
local target_offset = sd.debug.layout_offset("actor_current_target_actor")
local target_bucket_offset = sd.debug.layout_offset("actor_current_target_bucket_delta")
emit("actor", actor)
emit("target_actor", target_actor)
if sd.input.clear_mouse_left ~= nil then emit("clear_before", sd.input.clear_mouse_left()) end
emit("write_heading", heading_offset ~= nil and sd.debug.write_float(actor + heading_offset, heading) or false)
emit("write_aim_x", aim_x_offset ~= nil and sd.debug.write_float(actor + aim_x_offset, target_x) or false)
emit("write_aim_y", aim_y_offset ~= nil and sd.debug.write_float(actor + aim_y_offset, target_y) or false)
if aim_aux0_offset ~= nil then emit("write_aux0", sd.debug.write_u32(actor + aim_aux0_offset, 0)) end
if aim_aux1_offset ~= nil then emit("write_aux1", sd.debug.write_u32(actor + aim_aux1_offset, 0)) end
if target_offset ~= nil then emit("write_target", sd.debug.write_ptr(actor + target_offset, target_actor)) end
if target_bucket_offset ~= nil then emit("write_target_bucket", sd.debug.write_i32(actor + target_bucket_offset, 0)) end
emit("after.target_actor", target_offset ~= nil and string.format("0x%08X", read_ptr(actor + target_offset)) or "0x00000000")
emit("after.heading", heading_offset ~= nil and string.format("%.3f", read_float(actor + heading_offset)) or "0.000")
emit("after.aim_x", aim_x_offset ~= nil and string.format("%.3f", read_float(actor + aim_x_offset)) or "0.000")
emit("after.aim_y", aim_y_offset ~= nil and string.format("%.3f", read_float(actor + aim_y_offset)) or "0.000")
local hold_ok = sd.input.hold_mouse_left_frames(frames)
emit("mouse_left_frames", hold_ok)
if sd.input.pin_manual_primary_target ~= nil then
  local pin_ok, pin_result = pcall(sd.input.pin_manual_primary_target, target_actor)
  emit("pin_manual_primary_target", pin_ok and pin_result == true)
  emit("pin_manual_primary_target_error", pin_ok and "" or tostring(pin_result))
else
  emit("pin_manual_primary_target", false)
  emit("pin_manual_primary_target_error", "missing_api")
end
emit("ok", true)
"""


CAST_IMPACT_OBSERVATION_LUA = r"""
local wanted_network_id = tonumber("__NETWORK_ID__") or 0
local target_x = tonumber("__X__") or 0
local target_y = tonumber("__Y__") or 0
local radius_sq = 520.0 * 520.0
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local function hx(v) return string.format("0x%08X", tonumber(v) or 0) end
local function safe_read_float(address)
  if address == nil or address == 0 then return 0 end
  local ok, value = pcall(sd.debug.read_float, address)
  if ok then return tonumber(value) or 0 end
  return 0
end
local function safe_read_ptr(address)
  if address == nil or address == 0 then return 0 end
  local ok, value = pcall(sd.debug.read_ptr, address)
  if ok then return tonumber(value) or 0 end
  return 0
end
local function safe_read_u8(address)
  if address == nil or address == 0 then return 0 end
  local ok, value = pcall(sd.debug.read_u8, address)
  if ok then return tonumber(value) or 0 end
  return 0
end
local function safe_read_u16(address)
  if address == nil or address == 0 then return 0 end
  local ok, value = pcall(sd.debug.read_u16, address)
  if ok then return tonumber(value) or 0 end
  return 0
end
local function safe_read_i32(address)
  if address == nil or address == 0 then return 0 end
  local ok, value = pcall(sd.debug.read_i32, address)
  if ok then return tonumber(value) or 0 end
  return 0
end
local actors = sd.world.list_actors and sd.world.list_actors() or {}
local local_by_address = {}
for _, actor in ipairs(actors) do
  local address = tonumber(actor.actor_address) or 0
  if address ~= 0 then local_by_address[address] = actor end
end
local replicated = sd.world.get_replicated_actors and sd.world.get_replicated_actors() or nil
local snapshot = nil
local local_actor = nil
if replicated ~= nil and replicated.actors ~= nil then
  for _, actor in ipairs(replicated.actors) do
    if (tonumber(actor.network_actor_id) or 0) == wanted_network_id then
      snapshot = actor
      break
    end
  end
end
if replicated ~= nil and replicated.bindings ~= nil then
  for _, binding in ipairs(replicated.bindings) do
    if (tonumber(binding.network_actor_id) or 0) == wanted_network_id then
      local_actor = local_by_address[tonumber(binding.local_actor_address) or 0]
      break
    end
  end
end
if local_actor == nil then
  local best_d2 = nil
  for _, actor in ipairs(actors) do
    if actor.tracked_enemy then
      local dx = (tonumber(actor.x) or 0) - target_x
      local dy = (tonumber(actor.y) or 0) - target_y
      local d2 = dx * dx + dy * dy
      if d2 <= radius_sq and (best_d2 == nil or d2 < best_d2) then
        local_actor = actor
        best_d2 = d2
      end
    end
  end
end
local death_offset = sd.debug.layout_offset("enemy_death_handled")
emit("snapshot.found", snapshot ~= nil)
if snapshot ~= nil then
  emit("snapshot.hp", string.format("%.3f", tonumber(snapshot.hp) or 0))
  emit("snapshot.max_hp", string.format("%.3f", tonumber(snapshot.max_hp) or 0))
  emit("snapshot.dead", snapshot.dead or false)
  emit("snapshot.x", string.format("%.3f", tonumber(snapshot.x) or 0))
  emit("snapshot.y", string.format("%.3f", tonumber(snapshot.y) or 0))
end
emit("local.found", local_actor ~= nil)
if local_actor ~= nil then
  local address = tonumber(local_actor.actor_address) or 0
  emit("local.actor", hx(address))
  emit("local.hp", string.format("%.3f", tonumber(local_actor.hp) or 0))
  emit("local.max_hp", string.format("%.3f", tonumber(local_actor.max_hp) or 0))
  emit("local.dead", local_actor.dead or false)
  emit("local.death_handled", death_offset ~= nil and safe_read_u8(address + death_offset) or 0)
  emit("local.x", string.format("%.3f", tonumber(local_actor.x) or 0))
  emit("local.y", string.format("%.3f", tonumber(local_actor.y) or 0))
end
local player = sd.player.get_state and sd.player.get_state() or nil
local player_actor = tonumber(player and player.actor_address or 0) or 0
local heading_offset = sd.debug.layout_offset("actor_heading")
local aim_x_offset = sd.debug.layout_offset("actor_aim_target_x")
local aim_y_offset = sd.debug.layout_offset("actor_aim_target_y")
local target_offset = sd.debug.layout_offset("actor_current_target_actor")
local selection_offset = sd.debug.layout_offset("actor_animation_selection_state")
local selection_group_offset = sd.debug.layout_offset("actor_control_brain_target_slot")
local selection_slot_offset = sd.debug.layout_offset("actor_control_brain_target_handle")
emit("player.actor", hx(player_actor))
if player_actor ~= 0 then
  emit("player.x", string.format("%.3f", tonumber(player.x) or 0))
  emit("player.y", string.format("%.3f", tonumber(player.y) or 0))
  emit("player.heading", heading_offset ~= nil and string.format("%.3f", safe_read_float(player_actor + heading_offset)) or "0.000")
  emit("player.aim_x", aim_x_offset ~= nil and string.format("%.3f", safe_read_float(player_actor + aim_x_offset)) or "0.000")
  emit("player.aim_y", aim_y_offset ~= nil and string.format("%.3f", safe_read_float(player_actor + aim_y_offset)) or "0.000")
  emit("player.target", target_offset ~= nil and hx(safe_read_ptr(player_actor + target_offset)) or "0x00000000")
  local selection = selection_offset ~= nil and safe_read_ptr(player_actor + selection_offset) or 0
  emit("player.selection", hx(selection))
  emit("player.selection_group", selection ~= 0 and selection_group_offset ~= nil and safe_read_u8(selection + selection_group_offset) or 255)
  emit("player.selection_slot", selection ~= 0 and selection_slot_offset ~= nil and safe_read_u16(selection + selection_slot_offset) or 65535)
end
local projectile_count = 0
local nearest_projectile = nil
local nearest_projectile_d2 = nil
for _, actor in ipairs(actors) do
  local type_id = tonumber(actor.object_type_id) or 0
  if type_id == 0x7D3 or type_id == 0x7D4 or type_id == 0x7D5 then
    projectile_count = projectile_count + 1
    local dx = (tonumber(actor.x) or 0) - target_x
    local dy = (tonumber(actor.y) or 0) - target_y
    local d2 = dx * dx + dy * dy
    if nearest_projectile == nil or d2 < nearest_projectile_d2 then
      nearest_projectile = actor
      nearest_projectile_d2 = d2
    end
  end
end
emit("projectile.count", projectile_count)
if nearest_projectile ~= nil then
  emit("projectile.nearest_actor", hx(tonumber(nearest_projectile.actor_address) or 0))
  emit("projectile.nearest_type", tonumber(nearest_projectile.object_type_id) or 0)
  emit("projectile.nearest_x", string.format("%.3f", tonumber(nearest_projectile.x) or 0))
  emit("projectile.nearest_y", string.format("%.3f", tonumber(nearest_projectile.y) or 0))
  emit("projectile.nearest_distance", string.format("%.3f", math.sqrt(nearest_projectile_d2 or 0)))
end
emit("ok", true)
"""


CAST_RUNTIME_STATE_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local function hx(v) return string.format("0x%08X", tonumber(v) or 0) end
local function read_ptr(address)
  if address == nil or address == 0 then return 0 end
  return tonumber(sd.debug.read_ptr(address)) or 0
end
local function read_i32(address)
  if address == nil or address == 0 then return 0 end
  return tonumber(sd.debug.read_i32(address)) or 0
end
local function read_u8(address)
  if address == nil or address == 0 then return 0 end
  local ok, value = pcall(sd.debug.read_u8, address)
  if ok then return tonumber(value) or 0 end
  return 0
end
local function read_u16(address)
  if address == nil or address == 0 then return 0 end
  local ok, value = pcall(sd.debug.read_u16, address)
  if ok then return tonumber(value) or 0 end
  return 0
end
local function read_u32(address)
  if address == nil or address == 0 then return 0 end
  local ok, value = pcall(sd.debug.read_u32, address)
  if ok then return tonumber(value) or 0 end
  return 0
end
local player = sd.player.get_state()
if player == nil or player.actor_address == nil or player.actor_address == 0 then
  emit("ok", false)
  emit("reason", "player_missing")
  return
end
local actor = tonumber(player.actor_address) or 0
local oprogr = sd.debug.layout_offset("actor_progression_runtime_state")
local oprog_handle = sd.debug.layout_offset("actor_progression_handle")
local oequip = sd.debug.layout_offset("actor_equip_runtime_state")
local oequip_handle = sd.debug.layout_offset("actor_equip_handle")
local oselection = sd.debug.layout_offset("actor_animation_selection_state")
local oskill = sd.debug.layout_offset("actor_primary_skill_id")
local oprev = sd.debug.layout_offset("actor_previous_skill_id")
local ospell = sd.debug.layout_offset("progression_current_spell_id")
local oe4 = sd.debug.layout_offset("actor_primary_action_latch_e4")
local oe8 = sd.debug.layout_offset("actor_primary_action_latch_e8")
local opost = sd.debug.layout_offset("actor_post_gate_active_byte")
local ospell_group = sd.debug.layout_offset("actor_spell_target_group_byte")
local ospell_slot = sd.debug.layout_offset("actor_spell_target_slot_short")
local oselection_target_group = sd.debug.layout_offset("actor_control_brain_target_slot")
local oselection_target_slot = sd.debug.layout_offset("actor_control_brain_target_handle")
local oselection_retarget = sd.debug.layout_offset("actor_control_brain_retarget_ticks")
local oselection_target_cooldown = sd.debug.layout_offset("actor_control_brain_target_cooldown_ticks")
local oselection_action_cooldown = sd.debug.layout_offset("actor_control_brain_action_cooldown_ticks")
local oselection_action_burst = sd.debug.layout_offset("actor_control_brain_action_burst_ticks")
local progression_runtime = oprogr ~= nil and read_ptr(actor + oprogr) or 0
local progression_handle = oprog_handle ~= nil and read_ptr(actor + oprog_handle) or 0
local progression_inner = progression_handle ~= 0 and read_ptr(progression_handle) or 0
local progression = progression_runtime ~= 0 and progression_runtime or progression_inner
local equip_runtime = oequip ~= nil and read_ptr(actor + oequip) or 0
local equip_handle = oequip_handle ~= nil and read_ptr(actor + oequip_handle) or 0
local equip_inner = equip_handle ~= 0 and read_ptr(equip_handle) or 0
local selection_ptr = oselection ~= nil and read_ptr(actor + oselection) or 0
local selection_state = selection_ptr ~= 0 and read_i32(selection_ptr) or -1
local progression_spell = progression ~= 0 and ospell ~= nil and read_i32(progression + ospell) or 0
local primary_skill = oskill ~= nil and read_i32(actor + oskill) or 0
local previous_skill = oprev ~= nil and read_i32(actor + oprev) or 0
local selection_action_cooldown = selection_ptr ~= 0 and oselection_action_cooldown ~= nil and read_i32(selection_ptr + oselection_action_cooldown) or -1
local selection_action_burst = selection_ptr ~= 0 and oselection_action_burst ~= nil and read_i32(selection_ptr + oselection_action_burst) or -1
local equip_ready = equip_runtime ~= 0 or equip_inner ~= 0
local native_local_control = equip_runtime == 0 and selection_ptr == 0
local ready = progression_runtime ~= 0
  and progression_inner ~= 0
  and progression_runtime == progression_inner
  and progression_spell > 0
  and primary_skill == 0
  and previous_skill == 0
  and selection_action_cooldown <= 0
  and selection_action_burst <= 0
emit("ok", true)
emit("ready", ready)
emit("equip_ready", equip_ready)
emit("native_local_control", native_local_control)
emit("actor", hx(actor))
emit("progression_runtime", hx(progression_runtime))
emit("progression_handle", hx(progression_handle))
emit("progression_inner", hx(progression_inner))
emit("equip_runtime", hx(equip_runtime))
emit("equip_handle", hx(equip_handle))
emit("equip_inner", hx(equip_inner))
emit("selection_ptr", hx(selection_ptr))
emit("selection_state", selection_state)
emit("progression_spell", progression_spell)
emit("primary_skill", primary_skill)
emit("previous_skill", previous_skill)
emit("latch_e4", oe4 ~= nil and read_u32(actor + oe4) or 0)
emit("latch_e8", oe8 ~= nil and read_u32(actor + oe8) or 0)
emit("post_gate", opost ~= nil and read_u8(actor + opost) or 0)
emit("spell_group", ospell_group ~= nil and read_u8(actor + ospell_group) or 255)
emit("spell_slot", ospell_slot ~= nil and read_u16(actor + ospell_slot) or 65535)
emit("selection_target_group", selection_ptr ~= 0 and oselection_target_group ~= nil and read_u8(selection_ptr + oselection_target_group) or 255)
emit("selection_target_slot", selection_ptr ~= 0 and oselection_target_slot ~= nil and read_u16(selection_ptr + oselection_target_slot) or 65535)
emit("selection_retarget_ticks", selection_ptr ~= 0 and oselection_retarget ~= nil and read_i32(selection_ptr + oselection_retarget) or -1)
emit("selection_target_cooldown", selection_ptr ~= 0 and oselection_target_cooldown ~= nil and read_i32(selection_ptr + oselection_target_cooldown) or -1)
emit("selection_action_cooldown", selection_action_cooldown)
emit("selection_action_burst", selection_action_burst)
if sd.input ~= nil and sd.input.get_mouse_left_state ~= nil then
  local ok_input, input = pcall(sd.input.get_mouse_left_state)
  if ok_input and type(input) == "table" then
    emit("input.down", input.down or false)
    emit("input.edge_serial", input.edge_serial or 0)
    emit("input.edge_tick_ms", input.edge_tick_ms or 0)
  end
end
local mp = sd.runtime and sd.runtime.get_multiplayer_state and sd.runtime.get_multiplayer_state() or nil
if mp ~= nil and mp.participants ~= nil then
  for _, participant in ipairs(mp.participants) do
    if participant.is_local then
      emit("participant_id", participant.participant_id or 0)
      if participant.owned_progression ~= nil and participant.owned_progression.ability_loadout ~= nil then
        emit("loadout.primary", participant.owned_progression.ability_loadout.primary_entry_index or -1)
        emit("loadout.combo", participant.owned_progression.ability_loadout.primary_combo_entry_index or -1)
        emit("loadout.revision", participant.owned_progression.loadout_revision or 0)
        emit("spellbook.revision", participant.owned_progression.spellbook_revision or 0)
        emit("statbook.revision", participant.owned_progression.statbook_revision or 0)
      end
    end
  end
end
"""


SPAWN_REWARD_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local ok, err = sd.world.spawn_reward({kind="gold", amount=__AMOUNT__, x=__X__, y=__Y__})
emit("ok", ok)
emit("err", err or "")
"""


LIST_HOST_NATIVE_GOLD_DROPS_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local function hx(v) return string.format("0x%08X", tonumber(v) or 0) end
local count = 0
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  local type_id = tonumber(actor.object_type_id) or 0
  local address = tonumber(actor.actor_address) or 0
  if address ~= 0 and type_id == 0x07DC then
    count = count + 1
    local prefix = "gold." .. tostring(count) .. "."
    emit(prefix .. "address", hx(address))
    emit(prefix .. "amount", tonumber(sd.debug.read_u32(address + 0x140)) or 0)
    emit(prefix .. "lifetime", tonumber(sd.debug.read_u32(address + 0x144)) or 0)
    emit(prefix .. "presentation", tonumber(sd.debug.read_u8(address + 0x148)) or 0)
    emit(prefix .. "x", string.format("%.3f", tonumber(actor.x) or 0))
    emit(prefix .. "y", string.format("%.3f", tonumber(actor.y) or 0))
  end
end
emit("gold.count", count)
"""


ACTOR_LIST_MEMBERSHIP_LUA = r"""
local actor_address = tonumber("__ACTOR__") or 0
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local found = false
local object_type_id = 0
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  if (tonumber(actor.actor_address) or 0) == actor_address then
    found = true
    object_type_id = tonumber(actor.object_type_id) or 0
    break
  end
end
emit("found", found)
emit("object_type_id", object_type_id)
"""


FIND_HOST_NATIVE_GOLD_DROP_LUA = r"""
local amount = tonumber("__AMOUNT__") or 0
local x = tonumber("__X__") or 0
local y = tonumber("__Y__") or 0
local radius = tonumber("__RADIUS__") or 420
local radius_sq = radius * radius
local excluded = {__EXCLUDED_ADDRESSES__}
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local function hx(v) return string.format("0x%08X", tonumber(v) or 0) end
local best = nil
local best_d2 = nil
local native_count = 0
local transport_active_count = 0
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  local type_id = tonumber(actor.object_type_id) or 0
  local address = tonumber(actor.actor_address) or 0
  if address ~= 0 and type_id == 0x07DC then
    native_count = native_count + 1
    local amount_raw = tonumber(sd.debug.read_u32(address + 0x140)) or 0
    local lifetime = tonumber(sd.debug.read_u32(address + 0x144)) or 0
    local presentation = tonumber(sd.debug.read_u8(address + 0x148)) or 0
    if amount_raw > 0 and lifetime ~= 0 then
      transport_active_count = transport_active_count + 1
    end
    local dx = (tonumber(actor.x) or 0) - x
    local dy = (tonumber(actor.y) or 0) - y
    local d2 = dx * dx + dy * dy
    if not excluded[address] and amount_raw == amount and lifetime ~= 0 and d2 <= radius_sq then
      if best == nil or d2 < best_d2 then
        best = {
          actor = actor,
          address = address,
          amount = amount_raw,
          lifetime = lifetime,
          presentation = presentation,
          amount_tier = tonumber(sd.debug.read_u8(address + 0x13C)) or 0,
        }
        best_d2 = d2
      end
    end
  end
end
emit("native_count", native_count)
emit("transport_active_count", transport_active_count)
emit("found", best ~= nil)
if best ~= nil then
  emit("actor_address", hx(best.address))
  emit("amount", best.amount)
  emit("amount_tier", best.amount_tier)
  emit("lifetime", best.lifetime)
  emit("presentation", best.presentation)
  emit("x", string.format("%.3f", tonumber(best.actor.x) or 0))
  emit("y", string.format("%.3f", tonumber(best.actor.y) or 0))
  emit("distance", string.format("%.3f", math.sqrt(best_d2 or 0)))
end
"""


FIND_REPLICATED_GOLD_DROP_LUA = r"""
local amount = tonumber("__AMOUNT__") or 0
local x = tonumber("__X__") or 0
local y = tonumber("__Y__") or 0
local radius = tonumber("__RADIUS__") or 420
local radius_sq = radius * radius
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local best = nil
local best_d2 = nil
local loot = sd.world.get_replicated_loot and sd.world.get_replicated_loot() or nil
emit("loot.valid", loot ~= nil)
emit("loot.drop_count", loot and loot.drop_count or 0)
if loot and loot.drops then
  for _, drop in ipairs(loot.drops) do
    local type_id = tonumber(drop.object_type_id or drop.native_type_id) or 0
    local drop_amount = tonumber(drop.amount) or 0
    local dx = (tonumber(drop.x) or 0) - x
    local dy = (tonumber(drop.y) or 0) - y
    local d2 = dx * dx + dy * dy
    if type_id == 0x07DC and drop_amount == amount and drop.active and d2 <= radius_sq then
      if best == nil or d2 < best_d2 then
        best = drop
        best_d2 = d2
      end
    end
  end
end
emit("found", best ~= nil)
if best ~= nil then
  emit("network_drop_id", string.format("%.0f", tonumber(best.network_drop_id) or 0))
  emit("amount", best.amount or 0)
  emit("x", string.format("%.3f", tonumber(best.x) or 0))
  emit("y", string.format("%.3f", tonumber(best.y) or 0))
  emit("active", best.active and 1 or 0)
  emit("materialized", best.materialized and 1 or 0)
  emit("local_actor_address", best.local_actor_address or 0)
  emit("distance", string.format("%.3f", math.sqrt(best_d2 or 0)))
end
"""


REPLICATED_LOOT_DIAGNOSTIC_LUA = r"""
local amount = tonumber("__AMOUNT__") or 0
local x = tonumber("__X__") or 0
local y = tonumber("__Y__") or 0
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local function hx(v) return string.format("0x%08X", tonumber(v) or 0) end
local loot = sd.world.get_replicated_loot and sd.world.get_replicated_loot() or nil
emit("loot.valid", loot ~= nil)
emit("loot.drop_count", loot and loot.drop_count or 0)
emit("loot.drop_total_count", loot and loot.drop_total_count or 0)
emit("loot.sequence", loot and loot.sequence or 0)
emit("loot.scene_epoch", loot and loot.scene_epoch or 0)
emit("loot.run_nonce", loot and loot.run_nonce or 0)
emit("loot.scene_kind", loot and loot.scene_kind or "")
emit("loot.truncated", loot and loot.truncated or false)
emit("loot.received_ms", loot and loot.received_ms or 0)
if loot and loot.drops then
  for index, drop in ipairs(loot.drops) do
    if index > 8 then break end
    local prefix = "drop." .. tostring(index) .. "."
    local dx = (tonumber(drop.x) or 0) - x
    local dy = (tonumber(drop.y) or 0) - y
    emit(prefix .. "network_drop_id", string.format("%.0f", tonumber(drop.network_drop_id) or 0))
    emit(prefix .. "type_id", tonumber(drop.object_type_id or drop.native_type_id) or 0)
    emit(prefix .. "amount", tonumber(drop.amount) or 0)
    emit(prefix .. "active", drop.active or false)
    emit(prefix .. "materialized", drop.materialized or false)
    emit(prefix .. "local_actor_address", hx(drop.local_actor_address or 0))
    emit(prefix .. "x", string.format("%.3f", tonumber(drop.x) or 0))
    emit(prefix .. "y", string.format("%.3f", tonumber(drop.y) or 0))
    emit(prefix .. "distance", string.format("%.3f", math.sqrt(dx * dx + dy * dy)))
    emit(prefix .. "amount_matches", (tonumber(drop.amount) or 0) == amount)
  end
end
local mp = sd.runtime and sd.runtime.get_multiplayer_state and sd.runtime.get_multiplayer_state() or nil
emit("mp.valid", mp ~= nil)
emit("mp.session_status", mp and mp.session_status or "")
emit("mp.transport_ready", mp and mp.transport_ready or false)
emit("mp.participant_count", mp and mp.participant_count or 0)
if mp and mp.participants then
  for index, participant in ipairs(mp.participants) do
    if index > 4 then break end
    local prefix = "participant." .. tostring(index) .. "."
    emit(prefix .. "id", participant.participant_id or 0)
    emit(prefix .. "name", participant.name or "")
    emit(prefix .. "is_owner", participant.is_owner or false)
    emit(prefix .. "runtime_valid", participant.runtime_valid or false)
    emit(prefix .. "in_run", participant.in_run or false)
    emit(prefix .. "run_nonce", participant.run_nonce or 0)
    emit(prefix .. "scene_kind", participant.scene_kind or "")
  end
end
	"""


REPLICATED_LOOT_CAPTURE_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local function hx(v) return string.format("0x%08X", tonumber(v) or 0) end
local function finite(v)
  return type(v) == "number" and v == v and v ~= math.huge and v ~= -math.huge
end
local function safe_read_u8(address)
  local ok, value = pcall(sd.debug.read_u8, address)
  if ok then return tonumber(value) or 0 end
  return 0
end
local function safe_read_u32(address)
  local ok, value = pcall(sd.debug.read_u32, address)
  if ok then return tonumber(value) or 0 end
  return 0
end
local function safe_read_i32(address)
  local ok, value = pcall(sd.debug.read_i32, address)
  if ok then return tonumber(value) or 0 end
  return 0
end
local function safe_read_float(address)
  local ok, value = pcall(sd.debug.read_float, address)
  if ok then return tonumber(value) or 0 end
  return 0
end
local function safe_read_ptr(address)
  local ok, value = pcall(sd.debug.read_ptr, address)
  if ok then return tonumber(value) or 0 end
  return 0
end

local pos_x_offset = sd.debug.layout_offset("actor_position_x")
local pos_y_offset = sd.debug.layout_offset("actor_position_y")
local radius_offset = sd.debug.layout_offset("actor_collision_radius")
local type_id_offset = sd.debug.layout_offset("game_object_type_id")
local item_slot_offset = sd.debug.layout_offset("item_slot")
local potion_stack_count_offset = sd.debug.layout_offset("potion_stack_count")
local item_drop_held_item_offset = sd.debug.layout_offset("item_drop_held_item")

local function actor_x(address, fallback)
  if address ~= 0 and pos_x_offset ~= nil then return safe_read_float(address + pos_x_offset) end
  return tonumber(fallback) or 0
end
local function actor_y(address, fallback)
  if address ~= 0 and pos_y_offset ~= nil then return safe_read_float(address + pos_y_offset) end
  return tonumber(fallback) or 0
end
local function actor_radius(address, fallback)
  if address ~= 0 and radius_offset ~= nil then return safe_read_float(address + radius_offset) end
  return tonumber(fallback) or 0
end

local loot = sd.world.get_replicated_loot and sd.world.get_replicated_loot() or nil
emit("loot.valid", loot ~= nil)
emit("loot.authority_participant_id", loot and string.format("%.0f", tonumber(loot.authority_participant_id) or 0) or "0")
emit("loot.sequence", loot and loot.sequence or 0)
emit("loot.scene_epoch", loot and loot.scene_epoch or 0)
emit("loot.run_nonce", loot and loot.run_nonce or 0)
emit("loot.scene_kind", loot and loot.scene_kind or "")
emit("loot.drop_count", loot and loot.drop_count or 0)
emit("loot.drop_total_count", loot and loot.drop_total_count or 0)
emit("loot.truncated", loot and loot.truncated or false)
local pickup = loot and loot.last_pickup_result or nil
emit("pickup.valid", pickup ~= nil)
if pickup then
  emit("pickup.authority_participant_id", string.format("%.0f", tonumber(pickup.authority_participant_id) or 0))
  emit("pickup.participant_id", string.format("%.0f", tonumber(pickup.participant_id) or 0))
  emit("pickup.sequence", pickup.sequence or 0)
  emit("pickup.request_sequence", pickup.request_sequence or 0)
  emit("pickup.run_nonce", pickup.run_nonce or 0)
  emit("pickup.network_drop_id", string.format("%.0f", tonumber(pickup.network_drop_id) or 0))
  emit("pickup.result", pickup.result or "")
  emit("pickup.kind", pickup.kind or "")
  emit("pickup.amount", pickup.amount or 0)
  emit("pickup.resulting_gold", pickup.resulting_gold or 0)
  emit("pickup.gold_revision", pickup.gold_revision or 0)
  emit("pickup.resource_kind", pickup.resource_kind or -1)
  emit("pickup.resource_delta", string.format("%.3f", tonumber(pickup.resource_delta) or 0))
  emit("pickup.item_type_id", pickup.item_type_id or 0)
  emit("pickup.item_slot", pickup.item_slot or -1)
  emit("pickup.stack_count", pickup.stack_count or 0)
end

local count = 0
if loot and loot.drops then
  for _, drop in ipairs(loot.drops) do
    local type_id = tonumber(drop.object_type_id or drop.native_type_id) or 0
    local network_drop_id = tonumber(drop.network_drop_id) or 0
    if network_drop_id ~= 0 and (type_id == 0x07DB or type_id == 0x07DC or type_id == 0x07DD) then
      count = count + 1
      local prefix = "drop." .. tostring(count) .. "."
      local address = tonumber(drop.local_actor_address or drop.presentation_actor_address) or 0
      emit(prefix .. "network_drop_id", string.format("%.0f", network_drop_id))
      emit(prefix .. "type_id", type_id)
      emit(prefix .. "kind", drop.kind or "")
      emit(prefix .. "active", drop.active or false)
      emit(prefix .. "presentation_state", drop.presentation_state or 0)
      emit(prefix .. "amount", tonumber(drop.amount) or 0)
      emit(prefix .. "amount_tier", tonumber(drop.amount_tier or drop.resource_kind) or 0)
      emit(prefix .. "value", string.format("%.3f", tonumber(drop.value) or 0))
      emit(prefix .. "motion", string.format("%.3f", tonumber(drop.motion) or 0))
      emit(prefix .. "progress", string.format("%.3f", tonumber(drop.progress) or 0))
      emit(prefix .. "item_type_id", tonumber(drop.item_type_id) or 0)
      emit(prefix .. "item_slot", tonumber(drop.item_slot) or -1)
      emit(prefix .. "stack_count", tonumber(drop.stack_count) or 0)
      emit(prefix .. "actor_slot", tonumber(drop.actor_slot) or -1)
      emit(prefix .. "world_slot", tonumber(drop.world_slot) or -1)
      emit(prefix .. "lifetime", tonumber(drop.lifetime) or 0)
      emit(prefix .. "x", string.format("%.3f", tonumber(drop.x) or 0))
      emit(prefix .. "y", string.format("%.3f", tonumber(drop.y) or 0))
      emit(prefix .. "radius", string.format("%.3f", tonumber(drop.radius) or 0))
      emit(prefix .. "materialized", drop.materialized or false)
      emit(prefix .. "local_actor_address", hx(address))
      emit(prefix .. "actor_type_id", address ~= 0 and type_id_offset ~= nil and safe_read_u32(address + type_id_offset) or 0)
      emit(prefix .. "actor_x", string.format("%.3f", actor_x(address, drop.x)))
      emit(prefix .. "actor_y", string.format("%.3f", actor_y(address, drop.y)))
      emit(prefix .. "actor_radius", string.format("%.3f", actor_radius(address, drop.radius)))
      emit(prefix .. "actor_amount_tier", address ~= 0 and safe_read_u8(address + 0x13C) or 0)
      if type_id == 0x07DC then
        emit(prefix .. "actor_amount", address ~= 0 and safe_read_u32(address + 0x140) or 0)
      elseif type_id == 0x07DB then
        emit(prefix .. "actor_value", string.format("%.3f", address ~= 0 and safe_read_float(address + 0x140) or 0))
        emit(prefix .. "actor_motion", string.format("%.3f", address ~= 0 and safe_read_float(address + 0x148) or 0))
        emit(prefix .. "actor_progress", string.format("%.3f", address ~= 0 and safe_read_float(address + 0x14C) or 0))
      elseif type_id == 0x07DD then
        local held_item = address ~= 0 and item_drop_held_item_offset ~= nil and safe_read_ptr(address + item_drop_held_item_offset) or 0
        emit(prefix .. "actor_held_item", hx(held_item))
        emit(prefix .. "actor_item_type_id", held_item ~= 0 and type_id_offset ~= nil and safe_read_u32(held_item + type_id_offset) or 0)
        emit(prefix .. "actor_item_slot", held_item ~= 0 and item_slot_offset ~= nil and safe_read_i32(held_item + item_slot_offset) or -1)
        emit(prefix .. "actor_stack_count", held_item ~= 0 and potion_stack_count_offset ~= nil and safe_read_i32(held_item + potion_stack_count_offset) or 0)
      end
    end
  end
end
emit("drop.count", count)
"""


REQUEST_LOOT_PICKUP_LUA = r"""
local network_drop_id = tonumber("__DROP_ID__") or 0
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local ok, value = sd.world.request_loot_pickup(network_drop_id)
emit("ok", ok)
emit("value", value or "")
"""


LOOT_PICKUP_RESULT_LUA = r"""
local network_drop_id = tonumber("__DROP_ID__") or 0
local amount = tonumber("__AMOUNT__") or 0
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local loot = sd.world.get_replicated_loot and sd.world.get_replicated_loot() or nil
emit("loot.valid", loot ~= nil)
emit("loot.drop_count", loot and loot.drop_count or 0)
local result = loot and loot.last_pickup_result or nil
emit("result.valid", result ~= nil)
if result ~= nil then
  emit("result.authority_participant_id", result.authority_participant_id or 0)
  emit("result.participant_id", result.participant_id or 0)
  emit("result.sequence", result.sequence or 0)
  emit("result.request_sequence", result.request_sequence or 0)
  emit("result.run_nonce", result.run_nonce or 0)
  emit("result.network_drop_id", string.format("%.0f", tonumber(result.network_drop_id) or 0))
  emit("result.result", result.result or "")
  emit("result.kind", result.kind or "")
  emit("result.amount", result.amount or 0)
  emit("result.resulting_gold", result.resulting_gold or 0)
  emit("result.gold_revision", result.gold_revision or 0)
  emit("matches", (tonumber(result.network_drop_id) or 0) == network_drop_id
    and (result.result or "") == "Accepted"
    and (result.kind or "") == "Gold"
    and (tonumber(result.amount) or 0) == amount)
end
"""


CLEAR_FREEZE_LUA = r"""
local actor = tonumber("__ACTOR__") or 0
local function emit(key, value) print(key .. "=" .. tostring(value)) end
emit("ok", sd.gameplay.clear_manual_run_enemy_freeze(actor))
"""


def combat_ready(state: dict[str, str]) -> bool:
    return (
        state.get("active") == "true"
        and parse_int(state.get("wave_index")) == 0
        and parse_int(state.get("wave_counter")) == 999999999
    )


def set_manual_spawner_test_mode(pipe_name: str, enabled: bool) -> dict[str, str]:
    return values(
        pipe_name,
        SET_MANUAL_SPAWNER_TEST_MODE_LUA.replace("__ENABLED__", "true" if enabled else "false"),
    )


def stock_placement_vector_state(pipe_name: str, label: str) -> dict[str, str]:
    return values(pipe_name, STOCK_PLACEMENT_VECTOR_LUA.replace("__LABEL__", label))


def manual_spawner_state(pipe_name: str) -> dict[str, str]:
    return values(pipe_name, MANUAL_SPAWNER_STATE_LUA)


def wait_for_manual_spawner_ready(pipe_name: str, timeout: float = 8.0) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = manual_spawner_state(pipe_name)
        if last.get("manual_mode") == "true" and last.get("has_spawner") == "true":
            return last
        time.sleep(0.12)
    raise VerifyFailure(f"{pipe_name} did not expose a ready native manual enemy spawner: last={last}")


def probe_stock_placement_vectors(label: str) -> dict[str, Any]:
    if not DIAGNOSTICS_ENABLED:
        return {"skipped": "diagnostics_disabled"}
    result: dict[str, Any] = {}
    for name, pipe_name in (("host", HOST_PIPE), ("client", CLIENT_PIPE)):
        try:
            result[name] = stock_placement_vector_state(pipe_name, f"{name}.{label}")
        except Exception as exc:
            result[name] = {"error": str(exc)}
    return result


def enable_manual_stock_spawner_combat() -> dict[str, Any]:
    result: dict[str, Any] = {
        "host_before": values(HOST_PIPE, COMBAT_STATE_LUA),
        "client_before": values(CLIENT_PIPE, COMBAT_STATE_LUA),
        "vector_before": probe_stock_placement_vectors("combat.before"),
    }
    result["host_manual_spawner_mode"] = set_manual_spawner_test_mode(HOST_PIPE, True)
    if result["host_manual_spawner_mode"].get("ok") != "true":
        raise VerifyFailure(f"failed to enable host manual spawner test mode: {result['host_manual_spawner_mode']}")
    result["client_manual_spawner_mode"] = set_manual_spawner_test_mode(CLIENT_PIPE, True)
    if result["client_manual_spawner_mode"].get("ok") != "true":
        raise VerifyFailure(f"failed to enable client manual spawner test mode: {result['client_manual_spawner_mode']}")
    result["pre_prime_cleanup"] = cleanup_live_enemies()
    result["vector_after_manual_mode"] = probe_stock_placement_vectors("combat.after_manual_mode")
    result["host_enable"] = values(HOST_PIPE, ENABLE_PRELUDE_LUA)
    result["client_enable"] = values(CLIENT_PIPE, ENABLE_PRELUDE_LUA)
    result["vector_after_prelude"] = probe_stock_placement_vectors("combat.after_prelude")
    deadline = time.monotonic() + 8.0
    last_host: dict[str, str] = {}
    last_client: dict[str, str] = {}
    while time.monotonic() < deadline:
        last_host = values(HOST_PIPE, COMBAT_STATE_LUA)
        last_client = values(CLIENT_PIPE, COMBAT_STATE_LUA)
        if combat_ready(last_host) and combat_ready(last_client):
            result["host_after"] = last_host
            result["client_after"] = last_client
            result["vector_after_ready"] = probe_stock_placement_vectors("combat.after_ready")
            result["host_start_waves"] = values(HOST_PIPE, START_WAVES_LUA)
            if result["host_start_waves"].get("ok") != "true":
                raise VerifyFailure(f"failed to prime host native wave spawner: {result['host_start_waves']}")
            result["client_start_waves"] = values(CLIENT_PIPE, START_WAVES_LUA)
            if result["client_start_waves"].get("ok") != "true":
                raise VerifyFailure(f"failed to prime client native wave spawner: {result['client_start_waves']}")
            result["host_manual_spawner_ready"] = wait_for_manual_spawner_ready(HOST_PIPE)
            result["client_manual_spawner_ready"] = wait_for_manual_spawner_ready(CLIENT_PIPE)
            result["host_after_spawner_enemy_count"] = values(HOST_PIPE, LIVE_ENEMY_COUNT_LUA)
            if parse_int(result["host_after_spawner_enemy_count"].get("live_enemy_count")) != 0:
                raise VerifyFailure(
                    "host native manual-spawner priming leaked stock enemies: "
                    f"{result['host_after_spawner_enemy_count']}"
                )
            result["client_after_spawner_enemy_count"] = values(CLIENT_PIPE, LIVE_ENEMY_COUNT_LUA)
            if parse_int(result["client_after_spawner_enemy_count"].get("live_enemy_count")) != 0:
                raise VerifyFailure(
                    "client native manual-spawner priming leaked stock enemies: "
                    f"{result['client_after_spawner_enemy_count']}"
                )
            return result
        time.sleep(0.15)
    raise VerifyFailure(f"manual stock-spawner combat did not settle: host={last_host} client={last_client}")


def cleanup_live_enemies() -> dict[str, str]:
    result = values(HOST_PIPE, CLEANUP_LIVE_ENEMIES_LUA)
    time.sleep(0.35)
    count = values(HOST_PIPE, LIVE_ENEMY_COUNT_LUA)
    if parse_int(count.get("live_enemy_count")) != 0:
        raise VerifyFailure(f"live enemy cleanup left enemies behind: cleanup={result} count={count}")
    result.update({f"after.{key}": value for key, value in count.items()})
    return result


def clear_lane_probe(target_x: float, target_y: float, pipe_name: str = HOST_PIPE) -> dict[str, str]:
    source_x = target_x - TARGET_FORWARD_DISTANCE
    source_y = target_y
    return clear_lane_between(source_x, source_y, target_x, target_y, pipe_name=pipe_name)


def clear_lane_between(
    source_x: float,
    source_y: float,
    target_x: float,
    target_y: float,
    *,
    pipe_name: str = HOST_PIPE,
) -> dict[str, str]:
    result = values(
        pipe_name,
        CLEAR_CAST_LANE_LUA
        .replace("__SOURCE_X__", f"{source_x:.3f}")
        .replace("__SOURCE_Y__", f"{source_y:.3f}")
        .replace("__TARGET_X__", f"{target_x:.3f}")
        .replace("__TARGET_Y__", f"{target_y:.3f}")
        .replace("__HALF_WIDTH__", f"{LANE_HALF_WIDTH:.3f}")
        .replace("__END_PADDING__", f"{LANE_END_PADDING:.3f}")
        .replace("__ACTOR_PADDING__", f"{LANE_ACTOR_PADDING:.3f}"),
    )
    result["pipe"] = pipe_name
    return result


def lane_candidates(anchor: tuple[float, float]) -> list[tuple[float, float]]:
    anchor_x, anchor_y = anchor
    offsets = [
        (0.0, 0.0),
        (0.0, 220.0),
        (0.0, -220.0),
        (260.0, 0.0),
        (-260.0, 0.0),
        (260.0, 220.0),
        (260.0, -220.0),
        (-260.0, 220.0),
        (-260.0, -220.0),
        (520.0, 0.0),
        (-520.0, 0.0),
        (0.0, 440.0),
        (0.0, -440.0),
    ]
    return [(anchor_x + dx, anchor_y + dy) for dx, dy in offsets]


def select_clear_kill_lane(anchor: tuple[float, float], pipe_name: str = HOST_PIPE) -> dict[str, Any]:
    probes: list[dict[str, Any]] = []
    for x, y in lane_candidates(anchor):
        probe = clear_lane_probe(x, y, pipe_name=pipe_name)
        probes.append({"x": x, "y": y, "probe": probe})
        if probe.get("ok") == "true" and parse_int(probe.get("blocker_count")) == 0:
            return {"x": x, "y": y, "probe": probe, "attempts": probes}
    raise VerifyFailure(f"no clear cast lane found near anchor={anchor}: attempts={probes}")


def wait_for_spawn_result(request_id: int, timeout: float = 20.0) -> dict[str, str]:
    code = SPAWN_RESULT_LUA.replace("__REQUEST_ID__", str(request_id))
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = values(HOST_PIPE, code)
        if last.get("present") == "true":
            if last.get("ok") != "true":
                raise VerifyFailure(f"manual enemy spawn completed with failure: {last}")
            return last
        time.sleep(0.1)
    raise VerifyFailure(f"manual enemy spawn result did not appear: request_id={request_id} last={last}")


def configure_enemy(actor_address: int, x: float, y: float, hp: float) -> dict[str, str]:
    config = values(
        HOST_PIPE,
        CONFIGURE_ENEMY_LUA
        .replace("__ACTOR__", str(actor_address))
        .replace("__X__", f"{x:.3f}")
        .replace("__Y__", f"{y:.3f}")
        .replace("__HP__", f"{hp:.3f}"),
    )
    if (
        config.get("ok") != "true"
        or config.get("write_health") != "true"
        or config.get("rebind") == "false"
    ):
        raise VerifyFailure(f"manual enemy HP/position configuration failed: actor={actor_address} hp={hp} config={config}")
    return config


def inspect_spawned_actor(actor_address: int, x: float, y: float) -> dict[str, str]:
    return values(
        HOST_PIPE,
        INSPECT_ACTOR_LUA
        .replace("__ACTOR__", str(actor_address))
        .replace("__X__", f"{x:.3f}")
        .replace("__Y__", f"{y:.3f}"),
    )


def spawn_one_enemy(
    x: float,
    y: float,
    setup_hp: float = SETUP_TARGET_HP,
    *,
    freeze_on_spawn: bool = True,
) -> dict[str, Any]:
    spawn = values(
        HOST_PIPE,
        SPAWN_MANUAL_ENEMY_LUA
        .replace("__TYPE_ID__", str(SKELETON_TYPE_ID))
        .replace("__X__", f"{x:.3f}")
        .replace("__Y__", f"{y:.3f}")
        .replace("__FREEZE_ON_SPAWN__", "true" if freeze_on_spawn else "false"),
    )
    if spawn.get("ok") != "true":
        raise VerifyFailure(f"host manual run enemy spawn failed: {spawn}")
    request_id = parse_int(spawn.get("request_id"))
    result = wait_for_spawn_result(request_id)
    actor_address = parse_int(result.get("actor_address"))
    if actor_address == 0:
        raise VerifyFailure(f"manual run enemy spawn returned no actor: spawn={spawn} result={result}")
    network_actor_id = parse_int(result.get("network_actor_id"))
    if network_actor_id == 0:
        raise VerifyFailure(
            "manual run enemy spawn returned no network actor id: "
            f"spawn={spawn} result={result}"
        )
    config = configure_enemy(actor_address, x, y, setup_hp)
    inspect = inspect_spawned_actor(actor_address, x, y)
    return {
        "request": spawn,
        "result": result,
        "config": config,
        "inspect": inspect,
        "actor_address": actor_address,
        "network_actor_id": network_actor_id,
        "setup_hp": setup_hp,
        "freeze_on_spawn": freeze_on_spawn,
        "x": x,
        "y": y,
    }


def query_run_enemy_by_network_id(pipe_name: str, network_id: int) -> dict[str, str]:
    return values(
        pipe_name,
        RUN_ENEMY_BY_NETWORK_ID_LUA.replace("__NETWORK_ID__", str(network_id)),
    )


def find_target(
    pipe_name: str,
    x: float,
    y: float,
    network_id: int = 0,
    timeout: float = 6.0,
    *,
    require_local_binding: bool = True,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = find_target_or_last(pipe_name, x, y, network_id)
        if last.get("found") == "true" and (
            not require_local_binding or last.get("local.found") == "true"
        ):
            return last
        time.sleep(0.12)
    diagnostic = diagnose_target_or_last(pipe_name, x, y, network_id)
    raise VerifyFailure(
        f"{pipe_name} did not find exact manual enemy target: "
        f"network_id={network_id} last={last} diagnostic={diagnostic}"
    )


def require_target_alive(label: str, target_state: dict[str, str], diagnostics: dict[str, Any]) -> None:
    snapshot_hp = parse_float(target_state.get("snapshot.hp"), 0.0)
    local_hp = parse_float(target_state.get("local.hp"), snapshot_hp)
    if (
        target_state.get("snapshot.dead") == "true"
        or target_state.get("local.dead") == "true"
        or snapshot_hp <= 0.05
        or local_hp <= 0.05
    ):
        raise VerifyFailure(
            f"{label}: manual target died before scripted cast. "
            f"target={target_state} diagnostics={diagnostics}"
        )


def require_target_hp_at_least(
    label: str,
    target_state: dict[str, str],
    min_hp: float,
    diagnostics: dict[str, Any],
) -> None:
    snapshot_hp = parse_float(target_state.get("snapshot.hp"), 0.0)
    local_hp = parse_float(target_state.get("local.hp"), snapshot_hp)
    observed_hp = min(snapshot_hp, local_hp)
    if observed_hp < min_hp:
        raise VerifyFailure(
            f"{label}: manual target took unexpected setup damage. "
            f"min_hp={min_hp:.3f} observed_hp={observed_hp:.3f} "
            f"target={target_state} diagnostics={diagnostics}"
        )


def wait_for_remote_position_convergence(
    observer_pipe: str,
    participant_id: int,
    expected_x: float,
    expected_y: float,
    timeout: float = 8.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    prefix = f"peer.{participant_id}."
    while time.monotonic() < deadline:
        last = query(observer_pipe)
        x = parse_float(last.get(prefix + "x"), float("nan"))
        y = parse_float(last.get(prefix + "y"), float("nan"))
        if distance(x, y, expected_x, expected_y) <= 3.0:
            return last
        time.sleep(0.15)
    raise VerifyFailure(
        f"remote participant {participant_id} did not settle near "
        f"{expected_x:.3f},{expected_y:.3f} on {observer_pipe}; last={last}"
    )


def wait_for_local_position_settled(
    pipe_name: str,
    timeout: float = 6.0,
    stable_seconds: float = 0.5,
    distance_tolerance: float = 0.75,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    stable_since: float | None = None
    last = query(pipe_name)
    while time.monotonic() < deadline:
        time.sleep(0.1)
        current = query(pipe_name)
        last_x = parse_float(last.get("player.x"), float("nan"))
        last_y = parse_float(last.get("player.y"), float("nan"))
        current_x = parse_float(current.get("player.x"), float("nan"))
        current_y = parse_float(current.get("player.y"), float("nan"))
        if distance(last_x, last_y, current_x, current_y) <= distance_tolerance:
            if stable_since is None:
                stable_since = time.monotonic()
            if time.monotonic() - stable_since >= stable_seconds:
                return current
        else:
            stable_since = None
        last = current
    return last


def wait_for_pair_transform_convergence(
    timeout: float = 10.0,
    stable_seconds: float = PAIR_POSITION_STABLE_SECONDS,
    local_tolerance: float = PAIR_POSITION_STABLE_TOLERANCE,
    remote_tolerance: float = PAIR_REMOTE_SYNC_TOLERANCE,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    level_up_deadline = time.monotonic() + timeout + LEVEL_UP_RESOLVE_BUDGET
    stable_since: float | None = None
    previous_host: dict[str, str] | None = None
    previous_client: dict[str, str] | None = None
    resolved_level_ups: list[dict[str, Any]] = []
    last_record: dict[str, Any] = {}

    while time.monotonic() < deadline:
        host = query(HOST_PIPE)
        client = query(CLIENT_PIPE)
        # A natural level-up (accumulated kill XP crossing a threshold) opens a
        # host-coordinated skill picker that holds BOTH instances paused until
        # the target participant chooses an option. While paused, the
        # gameplay-tick-driven transform publish freezes, so the peer's mirror
        # stops updating and the pair can never converge -- this is the kill-loop
        # freeze, not a sync defect. Resolve the offer inline (choose on whichever
        # pipe is the target) and restart the convergence window so an expected
        # gameplay event is not counted as a failure.
        if (
            host.get("levelup.pause_active") == "true"
            or client.get("levelup.pause_active") == "true"
        ):
            if time.monotonic() >= level_up_deadline:
                raise VerifyFailure(
                    "level-up pause did not clear within budget: "
                    f"resolved={resolved_level_ups} "
                    f"host_pause={host.get('levelup.pause_active')} "
                    f"client_pause={client.get('levelup.pause_active')} "
                    f"host_offer={host.get('levelup.offer_valid')} "
                    f"client_offer={client.get('levelup.offer_valid')}"
                )
            resolved_level_ups.extend(resolve_level_ups_from_snapshots(host, client))
            stable_since = None
            previous_host = None
            previous_client = None
            # Only start counting convergence once the session is actually live.
            deadline = time.monotonic() + timeout
            time.sleep(0.1)
            continue
        host_x = parse_float(host.get("player.x"), float("nan"))
        host_y = parse_float(host.get("player.y"), float("nan"))
        client_x = parse_float(client.get("player.x"), float("nan"))
        client_y = parse_float(client.get("player.y"), float("nan"))
        host_seen_client_x = parse_float(host.get(f"peer.{CLIENT_ID}.x"), float("nan"))
        host_seen_client_y = parse_float(host.get(f"peer.{CLIENT_ID}.y"), float("nan"))
        client_seen_host_x = parse_float(client.get(f"peer.{HOST_ID}.x"), float("nan"))
        client_seen_host_y = parse_float(client.get(f"peer.{HOST_ID}.y"), float("nan"))

        host_local_delta = float("inf")
        client_local_delta = float("inf")
        if previous_host is not None and previous_client is not None:
            host_local_delta = distance(
                parse_float(previous_host.get("player.x"), float("nan")),
                parse_float(previous_host.get("player.y"), float("nan")),
                host_x,
                host_y,
            )
            client_local_delta = distance(
                parse_float(previous_client.get("player.x"), float("nan")),
                parse_float(previous_client.get("player.y"), float("nan")),
                client_x,
                client_y,
            )

        host_remote_delta = distance(host_seen_client_x, host_seen_client_y, client_x, client_y)
        client_remote_delta = distance(client_seen_host_x, client_seen_host_y, host_x, host_y)
        local_stable = host_local_delta <= local_tolerance and client_local_delta <= local_tolerance
        remote_synced = host_remote_delta <= remote_tolerance and client_remote_delta <= remote_tolerance
        last_record = {
            "host_settled": {
                "x": host.get("player.x"),
                "y": host.get("player.y"),
                "heading": host.get("player.heading"),
            },
            "client_settled": {
                "x": client.get("player.x"),
                "y": client.get("player.y"),
                "heading": client.get("player.heading"),
            },
            "host_seen_client": {
                "x": host.get(f"peer.{CLIENT_ID}.x"),
                "y": host.get(f"peer.{CLIENT_ID}.y"),
                "heading": host.get(f"peer.{CLIENT_ID}.heading"),
            },
            "client_seen_host": {
                "x": client.get(f"peer.{HOST_ID}.x"),
                "y": client.get(f"peer.{HOST_ID}.y"),
                "heading": client.get(f"peer.{HOST_ID}.heading"),
            },
            "host_local_delta": host_local_delta,
            "client_local_delta": client_local_delta,
            "host_remote_delta": host_remote_delta,
            "client_remote_delta": client_remote_delta,
        }
        if local_stable and remote_synced:
            if stable_since is None:
                stable_since = time.monotonic()
            if time.monotonic() - stable_since >= stable_seconds:
                last_record["stable_seconds"] = stable_seconds
                if resolved_level_ups:
                    last_record["resolved_level_ups"] = resolved_level_ups
                return last_record
        else:
            stable_since = None

        previous_host = host
        previous_client = client
        time.sleep(0.12)

    if resolved_level_ups:
        last_record["resolved_level_ups"] = resolved_level_ups
    raise VerifyFailure(f"host/client transform convergence timed out: last={last_record}")


def participant_views_for_pipe(
    sync: dict[str, Any],
    pipe_name: str,
    expected_x: float,
    expected_y: float,
) -> dict[str, Any]:
    if pipe_name == HOST_PIPE:
        local_key = "host_settled"
        remote_key = "client_seen_host"
        participant_id = HOST_ID
    elif pipe_name == CLIENT_PIPE:
        local_key = "client_settled"
        remote_key = "host_seen_client"
        participant_id = CLIENT_ID
    else:
        raise VerifyFailure(f"unknown pickup participant pipe: {pipe_name}")

    local_view = sync.get(local_key, {})
    remote_view = sync.get(remote_key, {})
    local_x = parse_float(local_view.get("x"), float("nan"))
    local_y = parse_float(local_view.get("y"), float("nan"))
    remote_x = parse_float(remote_view.get("x"), float("nan"))
    remote_y = parse_float(remote_view.get("y"), float("nan"))
    return {
        "participant_id": participant_id,
        "local_key": local_key,
        "remote_key": remote_key,
        "expected": {"x": expected_x, "y": expected_y},
        "local_view": local_view,
        "remote_view": remote_view,
        "local_distance": distance(local_x, local_y, expected_x, expected_y),
        "remote_distance": distance(remote_x, remote_y, expected_x, expected_y),
    }


def probe_standable_pickup_location(
    pipe_name: str,
    x: float,
    y: float,
    heading: float,
    *,
    label: str,
) -> dict[str, Any]:
    before = query(pipe_name)
    placed = place_player(pipe_name, x, y, heading)
    clear = clear_gameplay_mouse_left(pipe_name)
    try:
        sync = wait_for_pair_transform_convergence(
            timeout=4.0,
            stable_seconds=FORCED_PICKUP_CONVERGENCE_SECONDS,
        )
        views = participant_views_for_pipe(sync, pipe_name, x, y)
        local_view = views.get("local_view", {})
        remote_view = views.get("remote_view", {})
        actual_x = parse_float(local_view.get("x"), float("nan"))
        actual_y = parse_float(local_view.get("y"), float("nan"))
        remote_x = parse_float(remote_view.get("x"), float("nan"))
        remote_y = parse_float(remote_view.get("y"), float("nan"))
        remote_delta = distance(actual_x, actual_y, remote_x, remote_y)
        drift = views["local_distance"]
        ok = (
            math.isfinite(actual_x)
            and math.isfinite(actual_y)
            and remote_delta <= PAIR_REMOTE_SYNC_TOLERANCE
            and drift <= FORCED_GOLD_STANDABLE_DRIFT_TOLERANCE
        )
    except VerifyFailure as exc:
        sync = {"error": str(exc)}
        views = {}
        actual_x = float("nan")
        actual_y = float("nan")
        remote_delta = float("nan")
        drift = float("nan")
        ok = False

    return {
        "ok": ok,
        "label": label,
        "before": {
            "x": before.get("player.x"),
            "y": before.get("player.y"),
            "heading": before.get("player.heading"),
        },
        "placed": placed,
        "clear": clear,
        "sync": sync,
        "views": views,
        "actual_x": actual_x,
        "actual_y": actual_y,
        "remote_delta": remote_delta,
        "drift": drift,
        "drift_tolerance": FORCED_GOLD_STANDABLE_DRIFT_TOLERANCE,
    }


def place_player_and_require_pair_views_at(
    pipe_name: str,
    x: float,
    y: float,
    heading: float,
    *,
    label: str,
    attempts: int = FORCED_PICKUP_PLACEMENT_ATTEMPTS,
    tolerance: float = FORCED_PICKUP_POSITION_TOLERANCE,
) -> dict[str, Any]:
    attempt_records: list[dict[str, Any]] = []
    for attempt in range(1, attempts + 1):
        before = query(pipe_name)
        placed = place_player(pipe_name, x, y, heading)
        clear = clear_gameplay_mouse_left(pipe_name)
        try:
            sync = wait_for_pair_transform_convergence(
                timeout=4.0,
                stable_seconds=FORCED_PICKUP_CONVERGENCE_SECONDS,
            )
            views = participant_views_for_pipe(sync, pipe_name, x, y)
            ok = (
                views["local_distance"] <= tolerance
                and views["remote_distance"] <= tolerance
            )
        except VerifyFailure as exc:
            sync = {"error": str(exc)}
            views = {}
            ok = False

        record = {
            "attempt": attempt,
            "before": {
                "x": before.get("player.x"),
                "y": before.get("player.y"),
                "heading": before.get("player.heading"),
            },
            "placed": placed,
            "clear": clear,
            "sync": sync,
            "views": views,
            "tolerance": tolerance,
            "ok": ok,
        }
        attempt_records.append(record)
        if ok:
            return {
                "ok": True,
                "label": label,
                "attempts": attempt_records,
                "final": record,
            }
        time.sleep(0.15)

    raise VerifyFailure(
        f"{label}: pickup actor did not hold at forced drop position "
        f"{x:.3f},{y:.3f}; attempts={attempt_records}"
    )


def place_pair_for_direction(
    direction: Direction,
    target_x: float,
    target_y: float,
    *,
    receiver_y_offset: float = RECEIVER_PARK_DISTANCE,
) -> dict[str, Any]:
    source_x = target_x - TARGET_FORWARD_DISTANCE
    source_y = target_y
    receiver_x = source_x
    receiver_y = target_y + receiver_y_offset
    if direction.source_pipe == HOST_PIPE:
        host_pos = place_player(HOST_PIPE, source_x, source_y, PLAYER_HEADING_EAST)
        client_pos = place_player(CLIENT_PIPE, receiver_x, receiver_y, PLAYER_HEADING_EAST)
    else:
        client_pos = place_player(CLIENT_PIPE, source_x, source_y, PLAYER_HEADING_EAST)
        host_pos = place_player(HOST_PIPE, receiver_x, receiver_y, PLAYER_HEADING_EAST)
    host_post_place_clear = clear_gameplay_mouse_left(HOST_PIPE)
    client_post_place_clear = clear_gameplay_mouse_left(CLIENT_PIPE)
    sync = wait_for_pair_transform_convergence()
    return {
        "planned": {
            "source_x": source_x,
            "source_y": source_y,
            "receiver_x": receiver_x,
            "receiver_y": receiver_y,
        },
        "host_pos": host_pos,
        "client_pos": client_pos,
        "host_post_place_clear": host_post_place_clear,
        "client_post_place_clear": client_post_place_clear,
        **sync,
    }


def park_pair_away_from_target(target_x: float, target_y: float) -> dict[str, Any]:
    park_x = target_x - TARGET_FORWARD_DISTANCE
    host_y = target_y + PLAYER_SPAWN_PARK_DISTANCE
    client_y = host_y + PLAYER_SPAWN_PARK_SPACING
    host_pos = place_player(HOST_PIPE, park_x, host_y, PLAYER_HEADING_EAST)
    client_pos = place_player(CLIENT_PIPE, park_x, client_y, PLAYER_HEADING_EAST)
    host_post_place_clear = clear_gameplay_mouse_left(HOST_PIPE)
    client_post_place_clear = clear_gameplay_mouse_left(CLIENT_PIPE)
    sync = wait_for_pair_transform_convergence()
    return {
        "planned": {
            "park_x": park_x,
            "host_y": host_y,
            "client_y": client_y,
            "distance_from_target": PLAYER_SPAWN_PARK_DISTANCE,
        },
        "host_pos": host_pos,
        "client_pos": client_pos,
        "host_post_place_clear": host_post_place_clear,
        "client_post_place_clear": client_post_place_clear,
        **sync,
    }


def source_settled_position(direction: Direction, placement: dict[str, Any]) -> tuple[float, float]:
    key = "host_settled" if direction.source_pipe == HOST_PIPE else "client_settled"
    settled = placement[key]
    return parse_float(settled.get("x"), float("nan")), parse_float(settled.get("y"), float("nan"))


def placement_player_positions(placement: dict[str, Any]) -> list[tuple[str, float, float]]:
    positions: list[tuple[str, float, float]] = []
    for key in ("host_settled", "client_settled"):
        settled = placement.get(key)
        if not isinstance(settled, dict):
            continue
        x = parse_float(settled.get("x"), float("nan"))
        y = parse_float(settled.get("y"), float("nan"))
        if math.isfinite(x) and math.isfinite(y):
            positions.append((key, x, y))
    return positions


def select_forced_gold_location(
    target_x: float,
    target_y: float,
    pickup_pipe: str,
    placement: dict[str, Any],
) -> dict[str, Any]:
    player_positions = placement_player_positions(placement)
    attempts: list[dict[str, Any]] = []
    for dx, dy in FORCED_GOLD_CANDIDATE_OFFSETS:
        planned_x = target_x + dx
        planned_y = target_y + dy
        attempt: dict[str, Any] = {
            "offset_x": dx,
            "offset_y": dy,
            "planned_x": planned_x,
            "planned_y": planned_y,
        }
        attempts.append(attempt)
        try:
            snap_x, snap_y = snap_to_nav(pickup_pipe, planned_x, planned_y)
        except Exception as exc:
            attempt["snap_error"] = str(exc)
            continue
        snap_distance = distance(planned_x, planned_y, snap_x, snap_y)
        player_distances = [
            {
                "player": label,
                "distance": distance(snap_x, snap_y, player_x, player_y),
            }
            for label, player_x, player_y in player_positions
        ]
        min_player_distance = min(
            (item["distance"] for item in player_distances),
            default=float("inf"),
        )
        attempt.update({
            "snap_x": snap_x,
            "snap_y": snap_y,
            "snap_distance": snap_distance,
            "player_distances": player_distances,
            "min_player_distance": min_player_distance,
        })
        if (
            snap_distance <= DROP_MATCH_RADIUS
            and min_player_distance >= FORCED_GOLD_MIN_PLAYER_DISTANCE
        ):
            standable = probe_standable_pickup_location(
                pickup_pipe,
                snap_x,
                snap_y,
                PLAYER_HEADING_EAST,
                label=f"forced_gold_candidate.{len(attempts)}",
            )
            attempt["standable"] = standable
            if not standable["ok"]:
                continue
            return {
                "x": standable["actual_x"],
                "y": standable["actual_y"],
                "planned_x": planned_x,
                "planned_y": planned_y,
                "snap_x": snap_x,
                "snap_y": snap_y,
                "snap_distance": snap_distance,
                "standable": standable,
                "min_player_distance": min_player_distance,
                "player_positions": player_positions,
                "attempts": attempts,
            }
    raise VerifyFailure(
        "HARNESS: no nav-safe forced gold spawn location found away from players: "
        f"target=({target_x:.3f},{target_y:.3f}) attempts={attempts}"
    )


def place_pair_on_clear_lane(
    direction: Direction,
    anchor: tuple[float, float],
    *,
    receiver_y_offset: float = RECEIVER_PARK_DISTANCE,
) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    for planned_target_x, planned_target_y in lane_candidates(anchor):
        planned_probe = clear_lane_probe(planned_target_x, planned_target_y, pipe_name=direction.source_pipe)
        attempt: dict[str, Any] = {
            "planned_target_x": planned_target_x,
            "planned_target_y": planned_target_y,
            "planned_probe": planned_probe,
        }
        attempts.append(attempt)
        if planned_probe.get("ok") != "true" or parse_int(planned_probe.get("blocker_count")) != 0:
            continue
        placement = place_pair_for_direction(
            direction,
            planned_target_x,
            planned_target_y,
            receiver_y_offset=receiver_y_offset,
        )
        source_x, source_y = source_settled_position(direction, placement)
        target_x = source_x + TARGET_FORWARD_DISTANCE
        target_y = source_y
        source_target_distance = distance(source_x, source_y, target_x, target_y)
        settled_probe = clear_lane_between(
            source_x,
            source_y,
            target_x,
            target_y,
            pipe_name=direction.source_pipe,
        )
        attempt["placement"] = placement
        attempt["settled_source_x"] = source_x
        attempt["settled_source_y"] = source_y
        attempt["resolved_target_x"] = target_x
        attempt["resolved_target_y"] = target_y
        attempt["source_target_distance"] = source_target_distance
        attempt["settled_probe"] = settled_probe
        if (
            settled_probe.get("ok") == "true"
            and parse_int(settled_probe.get("blocker_count")) == 0
            and source_target_distance <= MAX_SCRIPTED_PRIMARY_TARGET_DISTANCE
        ):
            return {
                "x": target_x,
                "y": target_y,
                "probe": settled_probe,
                "planned_probe": planned_probe,
                "settled_probe": settled_probe,
                "placement": placement,
                "settled_source_x": source_x,
                "settled_source_y": source_y,
                "source_target_distance": source_target_distance,
                "attempts": attempts,
            }
    raise VerifyFailure(f"no clear settled cast lane found near anchor={anchor}: attempts={attempts}")


def prepare_and_queue_caster(
    direction: Direction,
    target_actor: int,
    target_x: float,
    target_y: float,
    frames: int,
) -> dict[str, str]:
    result = values(
        direction.source_pipe,
        PREPARE_AND_QUEUE_CASTER_LUA
        .replace("__TARGET_ACTOR__", str(target_actor))
        .replace("__TARGET_X__", f"{target_x:.3f}")
        .replace("__TARGET_Y__", f"{target_y:.3f}")
        .replace("__HEADING__", f"{PLAYER_HEADING_EAST:.3f}")
        .replace("__FRAMES__", str(frames)),
        timeout=5.0,
    )
    if (
        result.get("ok") != "true"
        or result.get("mouse_left_frames") != "true"
        or result.get("pin_manual_primary_target") != "true"
    ):
        raise VerifyFailure(f"{direction.name}: prepare-and-queue primary input failed: {result}")
    return result


def cast_runtime_state(pipe_name: str) -> dict[str, str]:
    result = values(pipe_name, CAST_RUNTIME_STATE_LUA)
    if result.get("ok") != "true":
        raise VerifyFailure(f"{pipe_name}: local caster runtime state unavailable: {result}")
    return result


def wait_for_cast_runtime_ready(direction: Direction, timeout: float = 4.0) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    stable_key: tuple[str | None, ...] | None = None
    while time.monotonic() < deadline:
        last = cast_runtime_state(direction.source_pipe)
        if last.get("ready") == "true":
            current_key = (
                last.get("actor"),
                last.get("progression_runtime"),
                last.get("progression_inner"),
                last.get("equip_runtime"),
                last.get("equip_inner"),
                last.get("selection_ptr"),
                last.get("progression_spell"),
                last.get("loadout.revision"),
                last.get("spellbook.revision"),
                last.get("statbook.revision"),
            )
            if stable_key == current_key:
                return last
            stable_key = current_key
        else:
            stable_key = None
        time.sleep(0.12)
    raise VerifyFailure(f"{direction.name}: local caster runtime never became primary-cast ready: {last}")


def resolve_active_level_up_barrier(label: str) -> dict[str, Any]:
    deadline = time.monotonic() + LEVEL_UP_RESOLVE_BUDGET
    pause_observed = False
    barrier_state_observed = False
    resolved: list[dict[str, Any]] = []
    resolved_keys: set[tuple[str, int]] = set()
    last_host: dict[str, str] = {}
    last_client: dict[str, str] = {}

    while time.monotonic() < deadline:
        last_host = query(HOST_PIPE)
        last_client = query(CLIENT_PIPE)
        pause_active = (
            last_host.get("levelup.pause_active") == "true"
            or last_client.get("levelup.pause_active") == "true"
        )
        offer_active = (
            last_host.get("levelup.offer_valid") == "true"
            or last_client.get("levelup.offer_valid") == "true"
        )
        pause_observed = pause_observed or pause_active
        barrier_state_observed = barrier_state_observed or pause_active or offer_active
        for choice in resolve_level_ups_from_snapshots(last_host, last_client):
            key = (str(choice["pipe"]), int(choice["offer_id"]))
            if key not in resolved_keys:
                resolved_keys.add(key)
                resolved.append(choice)
        if barrier_state_observed and not pause_active and not offer_active:
            return {
                "ok": True,
                "label": label,
                "pause_observed": True,
                "resolved": resolved,
            }
        time.sleep(0.1)

    raise VerifyFailure(
        f"{label}: level-up pause did not clear within {LEVEL_UP_RESOLVE_BUDGET:.1f}s: "
        f"resolved={resolved} host={last_host} client={last_client}"
    )


def wait_for_source_cast_resolving_level_ups(
    direction: Direction,
    source_offset: int,
    receiver_offset: int,
    required_counts: dict[str, int],
    timeout: float,
) -> tuple[str, dict[str, int], int, list[dict[str, Any]]]:
    deadline = time.monotonic() + timeout
    level_up_handled = False
    level_up_resolutions: list[dict[str, Any]] = []
    last_log = ""
    last_counts: dict[str, int] = {}
    last_native_hook_count = 0

    while time.monotonic() < deadline:
        last_log = log_after(direction.source_log, source_offset)
        last_counts = parse_phase_counts(last_log, direction.source_id)
        last_native_hook_count = count_local_native_queues(last_log)
        if last_native_hook_count >= 1 and all(
            last_counts.get(phase, 0) >= count
            for phase, count in required_counts.items()
        ):
            return last_log, last_counts, last_native_hook_count, level_up_resolutions

        if not level_up_handled:
            receiver_log = log_after(direction.receiver_log, receiver_offset)
            combined_log = last_log + receiver_log
            if any(marker in combined_log for marker in LEVEL_UP_PAUSE_LOG_MARKERS):
                resolution_started = time.monotonic()
                level_up_resolutions.append(
                    resolve_active_level_up_barrier(
                        f"{direction.name}.source_cast"
                    )
                )
                deadline += time.monotonic() - resolution_started
                level_up_handled = True
        time.sleep(0.05)

    raise VerifyFailure(
        f"{direction.name}: source cast did not reach native hook/phases. "
        f"required={required_counts} native_hooks={last_native_hook_count} "
        f"phases={last_counts} level_up_resolutions={level_up_resolutions}"
    )


def execute_primary_kill_attempt(
    direction: Direction,
    target: dict[str, Any],
    frames: int,
    attempt_index: int,
) -> dict[str, Any]:
    network_id = int(target["network_id"])
    target_x = float(target["x"])
    target_y = float(target["y"])
    target_actor = int(target["source_actor_address"])
    attempt: dict[str, Any] = {
        "attempt": attempt_index,
        "frames": frames,
        "status": "created",
    }
    attempt["source_cast_runtime_before"] = wait_for_cast_runtime_ready(direction)
    set_local_player_vitals(direction.source_pipe, 5000.0, 5000.0)
    source_offset = log_position(direction.source_log)
    receiver_offset = log_position(direction.receiver_log)
    attempt["source_log_offset"] = source_offset
    attempt["receiver_log_offset"] = receiver_offset
    attempt["prepare"] = prepare_and_queue_caster(direction, target_actor, target_x, target_y, frames)
    attempt["queue"] = {
        "clear_before": attempt["prepare"].get("clear_before"),
        "mouse_left_frames": attempt["prepare"].get("mouse_left_frames"),
    }
    attempt["status"] = "cast_queued"
    try:
        source_log, phase_counts, native_hook_count, level_up_resolutions = (
            wait_for_source_cast_resolving_level_ups(
                direction,
                source_offset,
                receiver_offset,
                {"pressed": 1, "released": 1},
                timeout=8.0,
            )
        )
    except VerifyFailure as exc:
        attempt["status"] = "source_cast_missing"
        attempt["source_cast_error"] = str(exc)
        attempt["source_log_tail"] = log_after(direction.source_log, source_offset)[-2000:]
        attempt["target_after"] = sample_target_state(direction, target)
        return attempt

    attempt["phase_counts"] = phase_counts
    attempt["native_hook_count"] = native_hook_count
    attempt["level_up_resolutions"] = level_up_resolutions
    attempt["source_log_tail"] = source_log[-2000:]
    attempt["cast_impact_timeline"] = collect_cast_impact_timeline(
        direction,
        target_x,
        target_y,
        network_id,
        duration=2.4,
    )
    attempt["source_effect_observed"] = cast_timeline_has_source_effect(attempt["cast_impact_timeline"])
    attempt["target_after"] = sample_target_state(direction, target)
    target_alive_on_both = (
        target_state_alive(attempt["target_after"].get("host", {}))
        and target_state_alive(attempt["target_after"].get("client", {}))
    )
    attempt["target_alive_on_both_after_attempt"] = target_alive_on_both
    if target_alive_on_both:
        attempt["status"] = "native_primary_no_kill"
        attempt["source_cast_runtime_after"] = cast_runtime_state(direction.source_pipe)
        return attempt

    try:
        death_logs = require_death_logs(
            direction,
            {
                "network_id": network_id,
                "actor_address": int(target["host_actor_address"]),
                "x": target_x,
                "y": target_y,
            },
            source_offset,
            receiver_offset,
            timeout=8.0,
        )
    except VerifyFailure as exc:
        attempt["status"] = "death_logs_missing"
        attempt["death_log_error"] = str(exc)
        return attempt
    attempt["death_logs"] = death_logs
    attempt["status"] = "death_logs_observed"
    return attempt


def observe_cast_impact(pipe_name: str, x: float, y: float, network_id: int) -> dict[str, str]:
    return values(
        pipe_name,
        CAST_IMPACT_OBSERVATION_LUA
        .replace("__NETWORK_ID__", str(network_id))
        .replace("__X__", f"{x:.3f}")
        .replace("__Y__", f"{y:.3f}"),
        timeout=4.0,
    )


def collect_cast_impact_timeline(
    direction: Direction,
    x: float,
    y: float,
    network_id: int,
    duration: float = 1.6,
    interval: float = 0.12,
) -> list[dict[str, Any]]:
    started = time.monotonic()
    timeline: list[dict[str, Any]] = []
    while True:
        elapsed = time.monotonic() - started
        sample: dict[str, Any] = {"t": round(elapsed, 3)}
        try:
            sample["source"] = observe_cast_impact(direction.source_pipe, x, y, network_id)
        except Exception as exc:
            sample["source_error"] = str(exc)
        try:
            sample["receiver"] = observe_cast_impact(direction.receiver_pipe, x, y, network_id)
        except Exception as exc:
            sample["receiver_error"] = str(exc)
        timeline.append(sample)
        if elapsed >= duration:
            return timeline
        time.sleep(interval)


def target_state_dead(state: dict[str, str]) -> bool:
    return (
        state.get("snapshot.dead") == "true"
        or state.get("local.dead") == "true"
        or parse_int(state.get("local.death_handled")) != 0
        or parse_float(state.get("snapshot.hp"), 1.0) <= 0.05
        or parse_float(state.get("local.hp"), 1.0) <= 0.05
    )


def target_state_alive(state: dict[str, str]) -> bool:
    if state.get("found") != "true":
        return False
    return not target_state_dead(state)


def finalize_late_primary_death(
    direction: Direction,
    target: dict[str, Any],
    attempt: dict[str, Any],
    settled_target: dict[str, dict[str, str]],
) -> bool:
    if attempt.get("status") != "native_primary_no_kill":
        return False
    death_visible = any(
        target_state_dead(settled_target.get(side, {}))
        for side in ("host", "client")
    )
    target_removed = all(
        settled_target.get(side, {}).get("found") == "false"
        and parse_int(
            settled_target.get(side, {}).get("live_local_count")
        ) == 0
        for side in ("host", "client")
    )
    if not death_visible and not target_removed:
        return False

    death_logs = require_death_logs(
        direction,
        {
            "network_id": int(target["network_id"]),
            "actor_address": int(target["host_actor_address"]),
            "x": float(target["x"]),
            "y": float(target["y"]),
        },
        int(attempt["source_log_offset"]),
        int(attempt["receiver_log_offset"]),
        timeout=8.0,
    )
    attempt["target_after_late_settle"] = settled_target
    if target_removed:
        attempt["target_removed_after_late_death"] = True
    attempt["death_logs"] = death_logs
    attempt["late_death_observed"] = True
    attempt["status"] = "death_logs_observed"
    return True


def cast_timeline_has_source_effect(timeline: list[dict[str, Any]]) -> bool:
    for sample in timeline:
        source = sample.get("source")
        if not isinstance(source, dict):
            continue
        if parse_int(source.get("projectile.count")) > 0:
            return True
        if target_state_dead(source):
            return True
        if parse_float(source.get("snapshot.hp"), LOW_TARGET_HP) < LOW_TARGET_HP - 0.05:
            return True
        if parse_float(source.get("local.hp"), LOW_TARGET_HP) < LOW_TARGET_HP - 0.05:
            return True
    return False


def sample_target_state(direction: Direction, target: dict[str, Any]) -> dict[str, dict[str, str]]:
    network_id = int(target["network_id"])
    target_x = float(target["x"])
    target_y = float(target["y"])
    return {
        "host": find_target_or_last(HOST_PIPE, target_x, target_y, network_id),
        "client": find_target_or_last(CLIENT_PIPE, target_x, target_y, network_id),
    }


def wait_for_death(
    direction: Direction,
    target: dict[str, Any],
    timeout: float = 8.0,
    *,
    allow_removed: bool = False,
) -> dict[str, Any]:
    network_id = int(target["network_id"])
    target_x = float(target["x"])
    target_y = float(target["y"])
    deadline = time.monotonic() + timeout
    last_host: dict[str, str] = {}
    last_client: dict[str, str] = {}
    def has_live_local_at_target(state: dict[str, str]) -> bool:
        for index in range(8):
            hp = parse_float(state.get(f"live.{index}.hp"), 0.0)
            distance_to_target = parse_float(state.get(f"live.{index}.distance"), float("inf"))
            if hp > 0.05 and distance_to_target <= 480.0:
                return True
        return False

    while time.monotonic() < deadline:
        last_host = find_target_or_last(HOST_PIPE, target_x, target_y, network_id)
        last_client = find_target_or_last(CLIENT_PIPE, target_x, target_y, network_id)
        host_dead = (
            last_host.get("snapshot.dead") == "true"
            or last_host.get("local.dead") == "true"
            or parse_int(last_host.get("local.death_handled")) != 0
            or parse_float(last_host.get("snapshot.hp"), 1.0) <= 0.05
        )
        client_dead = (
            last_client.get("snapshot.dead") == "true"
            or last_client.get("local.dead") == "true"
            or parse_int(last_client.get("local.death_handled")) != 0
            or parse_float(last_client.get("snapshot.hp"), 1.0) <= 0.05
        )
        if host_dead and client_dead:
            return {
                "host": last_host,
                "client": last_client,
            }
        if (
            allow_removed
            and last_host.get("found") == "false"
            and last_client.get("found") == "false"
            and not has_live_local_at_target(last_host)
            and not has_live_local_at_target(last_client)
        ):
            return {
                "host": last_host,
                "client": last_client,
                "removed_after_death_logs": True,
            }
        time.sleep(0.1)
    raise VerifyFailure(
        f"{direction.name}: target did not die on both instances. "
        f"target={target} host={last_host} client={last_client}"
    )


def build_find_target_lua(
    x: float,
    y: float,
    network_id: int,
    *,
    verbose: bool,
) -> str:
    return (
        FIND_TARGET_LUA
        .replace("__NETWORK_ID__", str(network_id))
        .replace("__X__", f"{x:.3f}")
        .replace("__Y__", f"{y:.3f}")
        .replace("__RADIUS__", "480")
        .replace("__VERBOSE__", "true" if verbose else "false")
    )


def find_target_or_last(pipe_name: str, x: float, y: float, network_id: int) -> dict[str, str]:
    code = build_find_target_lua(x, y, network_id, verbose=False)
    try:
        return values(pipe_name, code)
    except Exception as exc:
        return {"error": str(exc)}


def diagnose_target_or_last(pipe_name: str, x: float, y: float, network_id: int) -> dict[str, str]:
    code = (
        build_find_target_lua(x, y, network_id, verbose=True)
    )
    try:
        return values(pipe_name, code)
    except Exception as exc:
        return {"error": str(exc)}


def wait_for_target_hp(
    pipe_name: str,
    x: float,
    y: float,
    network_id: int,
    expected_hp: float,
    timeout: float = 5.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = find_target_or_last(pipe_name, x, y, network_id)
        local_hp = parse_float(last.get("local.hp"), float("nan"))
        snapshot_hp = parse_float(last.get("snapshot.hp"), float("nan"))
        if (
            last.get("found") == "true"
            and last.get("local.found") == "true"
            and last.get("local.dead") != "true"
            and math.isfinite(local_hp)
            and math.isfinite(snapshot_hp)
            and local_hp <= expected_hp + 0.05
            and snapshot_hp <= expected_hp + 0.05
        ):
            return last
        time.sleep(0.1)
    raise VerifyFailure(
        f"{pipe_name} did not converge target hp to {expected_hp}: "
        f"network_id={network_id} last={last} "
        f"diagnostic={diagnose_target_or_last(pipe_name, x, y, network_id)}"
    )


def wait_for_target_hp_at_least(
    pipe_name: str,
    x: float,
    y: float,
    network_id: int,
    min_hp: float,
    timeout: float = 5.0,
    *,
    require_local_binding: bool = True,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = find_target_or_last(pipe_name, x, y, network_id)
        local_hp = parse_float(last.get("local.hp"), float("nan"))
        snapshot_hp = parse_float(last.get("snapshot.hp"), float("nan"))
        local_ok = not require_local_binding or (
            last.get("local.found") == "true"
            and math.isfinite(local_hp)
            and local_hp >= min_hp - 0.05
        )
        if (
            last.get("found") == "true"
            and last.get("snapshot.dead") != "true"
            and last.get("local.dead") != "true"
            and math.isfinite(snapshot_hp)
            and snapshot_hp >= min_hp - 0.05
            and local_ok
        ):
            return last
        time.sleep(0.1)
    raise VerifyFailure(
        f"{pipe_name} did not converge target hp to at least {min_hp}: "
        f"network_id={network_id} last={last} "
        f"diagnostic={diagnose_target_or_last(pipe_name, x, y, network_id)}"
    )


def require_death_logs(
    direction: Direction,
    target: dict[str, Any],
    source_offset: int,
    receiver_offset: int,
    timeout: float = 8.0,
) -> dict[str, Any]:
    network_id = int(target["network_id"])
    actor_hex = f"0x{int(target['actor_address']):08X}"
    deadline = time.monotonic() + timeout
    last_source = ""
    last_receiver = ""
    while time.monotonic() < deadline:
        last_source = log_after(direction.source_log, source_offset)
        last_receiver = log_after(direction.receiver_log, receiver_offset)
        if direction.source_pipe == HOST_PIPE:
            receiver_removed_without_death = (
                "world_snapshot: unregistered extra run actor" in last_receiver
                and f"network_actor_id={network_id}" in last_receiver
            )
            if receiver_removed_without_death:
                raise VerifyFailure(
                    f"{direction.name}: receiver structurally removed target {network_id} "
                    "before its authoritative native death presentation. "
                    f"receiver_tail={last_receiver[-3000:]}"
                )
            source_ok = "enemy.death hook invoked" in last_source and actor_hex in last_source
            receiver_ok = (
                "world_snapshot: triggered replicated run enemy death" in last_receiver
                and f"network_actor_id={network_id}" in last_receiver
            )
        else:
            source_ok = "enemy.death hook invoked" in last_source
            receiver_ok = (
                "Multiplayer enemy damage claim accepted" in last_receiver
                and f"target_network_actor_id={network_id}" in last_receiver
                and "lethal=1" in last_receiver
                and "death_called=1" in last_receiver
            )
        if source_ok and receiver_ok:
            return {
                "source_ok": source_ok,
                "receiver_ok": receiver_ok,
                "source_tail": last_source[-2000:],
                "receiver_tail": last_receiver[-2000:],
            }
        time.sleep(0.08)
    raise VerifyFailure(
        f"{direction.name}: missing native death/effect log evidence for target={target}. "
        f"source_tail={last_source[-3000:]} receiver_tail={last_receiver[-3000:]}"
    )


def list_host_active_native_gold_addresses() -> set[int]:
    drops = values(HOST_PIPE, LIST_HOST_NATIVE_GOLD_DROPS_LUA)
    return {
        parse_int(row.get("address"))
        for row in row_values(drops, "gold", "gold.count")
        if parse_int(row.get("address")) != 0
        and parse_int(row.get("amount")) > 0
        and parse_int(row.get("lifetime")) != 0
    }


def wait_for_native_actor_absent(
    pipe_name: str,
    actor_address: int,
    label: str,
    timeout: float = 6.0,
) -> dict[str, str]:
    if actor_address == 0:
        raise VerifyFailure(f"{label}: native actor address is missing")
    code = ACTOR_LIST_MEMBERSHIP_LUA.replace("__ACTOR__", str(actor_address))
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = values(pipe_name, code)
        if last.get("found") != "true":
            return last
        time.sleep(0.1)
    raise VerifyFailure(
        f"{label}: native actor remained registered after accepted pickup: "
        f"actor={actor_address:#x} last={last}"
    )


def lua_excluded_address_table(addresses: set[int]) -> str:
    if not addresses:
        return ""
    return ",".join(f"[{address}]=true" for address in sorted(addresses))


def verify_forced_gold_drop(amount: int, x: float, y: float, pickup_pipe: str) -> dict[str, Any]:
    host_log_offset = log_position(HOST_LOG)
    client_log_offset = log_position(CLIENT_LOG)
    before_addresses = list_host_active_native_gold_addresses()
    pre_spawn_client_loot = replicated_loot_diagnostics(CLIENT_PIPE, amount, x, y)
    spawn = values(
        HOST_PIPE,
        SPAWN_REWARD_LUA
        .replace("__AMOUNT__", str(amount))
        .replace("__X__", f"{x:.3f}")
        .replace("__Y__", f"{y:.3f}"),
    )
    if spawn.get("ok") != "true":
        raise VerifyFailure(f"host forced gold drop spawn failed: {spawn}")
    host_drop = wait_for_host_native_gold_drop(amount, x, y, before_addresses=before_addresses)
    try:
        client_drop = wait_for_replicated_gold_drop(CLIENT_PIPE, amount, x, y, materialized_required=True)
    except VerifyFailure as exc:
        host_find_after = values(
            HOST_PIPE,
            FIND_HOST_NATIVE_GOLD_DROP_LUA
            .replace("__AMOUNT__", str(amount))
            .replace("__X__", f"{x:.3f}")
            .replace("__Y__", f"{y:.3f}")
            .replace("__RADIUS__", f"{DROP_MATCH_RADIUS:.3f}")
            .replace("__EXCLUDED_ADDRESSES__", lua_excluded_address_table(before_addresses)),
            timeout=5.0,
        )
        diagnostics = {
            "pre_spawn_client_loot": pre_spawn_client_loot,
            "spawn": spawn,
            "host_drop": host_drop,
            "host_native_after": values(HOST_PIPE, LIST_HOST_NATIVE_GOLD_DROPS_LUA, timeout=5.0),
            "host_find_after": host_find_after,
            "client_loot_after": replicated_loot_diagnostics(CLIENT_PIPE, amount, x, y),
            "host_log_after_spawn": log_after(HOST_LOG, host_log_offset)[-5000:],
            "client_log_after_spawn": log_after(CLIENT_LOG, client_log_offset)[-5000:],
        }
        raise VerifyFailure(f"{exc}; forced_gold_diagnostics={diagnostics}") from exc
    network_drop_id = parse_int(client_drop.get("network_drop_id"))
    if network_drop_id == 0:
        raise VerifyFailure(f"forced gold drop had no network id: host={host_drop} client={client_drop}")
    pickup_x = parse_float(client_drop.get("x"), x)
    pickup_y = parse_float(client_drop.get("y"), y)
    try:
        nav_x, nav_y = snap_to_nav(pickup_pipe, pickup_x, pickup_y)
    except Exception as exc:
        nav_x = pickup_x
        nav_y = pickup_y
        snap_error = str(exc)
    else:
        snap_error = ""
    placement_x = pickup_x
    placement_y = pickup_y
    snap_distance = distance(pickup_x, pickup_y, nav_x, nav_y)
    if snap_distance > DROP_MATCH_RADIUS:
        raise VerifyFailure(
            "HARNESS: forced gold drop landed too far from pickup nav target: "
            f"drop=({pickup_x:.3f},{pickup_y:.3f}) snapped=({nav_x:.3f},{nav_y:.3f}) "
            f"distance={snap_distance:.3f} radius={DROP_MATCH_RADIUS:.3f}"
        )
    pickup_position = place_player_and_require_pair_views_at(
        pickup_pipe,
        placement_x,
        placement_y,
        PLAYER_HEADING_EAST,
        label=f"forced_gold.{network_drop_id}.pickup_position",
    )
    post_placement_pickup_state = wait_for_replicated_gold_present_or_picked_up(
        CLIENT_PIPE,
        amount,
        x,
        y,
        network_drop_id,
        timeout=6.0,
    )
    if post_placement_pickup_state["state"] == "present":
        pickup = values(
            pickup_pipe,
            REQUEST_LOOT_PICKUP_LUA.replace("__DROP_ID__", str(network_drop_id)),
        )
        if pickup.get("ok") != "true":
            raise VerifyFailure(f"loot pickup request failed: drop={client_drop} pickup={pickup}")
        pickup_result = wait_for_exact_loot_pickup_result(CLIENT_PIPE, network_drop_id, amount, timeout=6.0)
    else:
        pickup = {
            "ok": "native_auto_pickup",
            "network_drop_id": str(network_drop_id),
        }
        pickup_result = post_placement_pickup_state["pickup_result"]
    absent = wait_for_replicated_gold_absent(CLIENT_PIPE, amount, x, y, timeout=6.0)
    host_actor_absent = wait_for_native_actor_absent(
        HOST_PIPE,
        parse_int(host_drop.get("actor_address")),
        f"forced_gold.{network_drop_id}.host",
    )
    client_actor_absent = wait_for_native_actor_absent(
        CLIENT_PIPE,
        parse_int(client_drop.get("local_actor_address")),
        f"forced_gold.{network_drop_id}.client",
    )
    return {
        "before_host_gold_count": len(before_addresses),
        "pre_spawn_client_loot": pre_spawn_client_loot,
        "spawn": spawn,
        "host_drop": host_drop,
        "client_drop": client_drop,
        "pickup_nav": {
            "drop_x": pickup_x,
            "drop_y": pickup_y,
            "placement_x": placement_x,
            "placement_y": placement_y,
            "nav_x": nav_x,
            "nav_y": nav_y,
            "snap_distance": snap_distance,
            "snap_error": snap_error,
        },
        "pickup_position": pickup_position,
        "post_placement_pickup_state": post_placement_pickup_state,
        "pickup": pickup,
        "pickup_result": pickup_result,
        "absent_after_pickup": absent,
        "host_native_actor_absent_after_pickup": host_actor_absent,
        "client_native_actor_absent_after_pickup": client_actor_absent,
    }


def wait_for_host_native_gold_drop(
    amount: int,
    x: float,
    y: float,
    *,
    before_addresses: set[int],
    timeout: float = 6.0,
) -> dict[str, str]:
    code = (
        FIND_HOST_NATIVE_GOLD_DROP_LUA
        .replace("__AMOUNT__", str(amount))
        .replace("__X__", f"{x:.3f}")
        .replace("__Y__", f"{y:.3f}")
        .replace("__RADIUS__", f"{DROP_MATCH_RADIUS:.3f}")
        .replace("__EXCLUDED_ADDRESSES__", lua_excluded_address_table(before_addresses))
    )
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = values(HOST_PIPE, code)
        if last.get("found") == "true":
            return last
        time.sleep(0.1)
    raise VerifyFailure(f"host did not expose native forced gold amount={amount}: last={last}")


def wait_for_replicated_gold_drop(
    pipe_name: str,
    amount: int,
    x: float,
    y: float,
    *,
    materialized_required: bool,
    timeout: float = 6.0,
) -> dict[str, str]:
    code = (
        FIND_REPLICATED_GOLD_DROP_LUA
        .replace("__AMOUNT__", str(amount))
        .replace("__X__", f"{x:.3f}")
        .replace("__Y__", f"{y:.3f}")
        .replace("__RADIUS__", f"{DROP_MATCH_RADIUS:.3f}")
    )
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = values(pipe_name, code)
        if last.get("found") == "true" and (
            not materialized_required
            or (last.get("materialized") == "1" and parse_int(last.get("local_actor_address")) != 0)
        ):
            return last
        time.sleep(0.1)
    raise VerifyFailure(f"{pipe_name} did not observe replicated forced gold amount={amount}: last={last}")


def replicated_loot_diagnostics(pipe_name: str, amount: int, x: float, y: float) -> dict[str, str]:
    return values(
        pipe_name,
        REPLICATED_LOOT_DIAGNOSTIC_LUA
        .replace("__AMOUNT__", str(amount))
        .replace("__X__", f"{x:.3f}")
        .replace("__Y__", f"{y:.3f}"),
        timeout=5.0,
    )


def capture_replicated_loot(pipe_name: str) -> dict[str, str]:
    return values(pipe_name, REPLICATED_LOOT_CAPTURE_LUA, timeout=5.0)


def replicated_loot_rows(capture: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in row_values(capture, "drop", "drop.count"):
        rows.append({
            "network_drop_id": parse_int(row.get("network_drop_id")),
            "type_id": parse_int(row.get("type_id")),
            "kind": row.get("kind", ""),
            "active": parse_bool(row.get("active")),
            "presentation_state": parse_int(row.get("presentation_state")),
            "amount": parse_int(row.get("amount")),
            "amount_tier": parse_int(row.get("amount_tier")),
            "value": parse_float(row.get("value")),
            "motion": parse_float(row.get("motion")),
            "progress": parse_float(row.get("progress")),
            "item_type_id": parse_int(row.get("item_type_id")),
            "item_slot": parse_int(row.get("item_slot"), -1),
            "stack_count": parse_int(row.get("stack_count")),
            "actor_slot": parse_int(row.get("actor_slot"), -1),
            "world_slot": parse_int(row.get("world_slot"), -1),
            "lifetime": parse_int(row.get("lifetime")),
            "x": parse_float(row.get("x")),
            "y": parse_float(row.get("y")),
            "radius": parse_float(row.get("radius")),
            "materialized": parse_bool(row.get("materialized")),
            "local_actor_address": parse_int(row.get("local_actor_address")),
            "actor_type_id": parse_int(row.get("actor_type_id")),
            "actor_x": parse_float(row.get("actor_x")),
            "actor_y": parse_float(row.get("actor_y")),
            "actor_radius": parse_float(row.get("actor_radius")),
            "actor_amount_tier": parse_int(row.get("actor_amount_tier")),
            "actor_amount": parse_int(row.get("actor_amount")),
            "actor_value": parse_float(row.get("actor_value")),
            "actor_motion": parse_float(row.get("actor_motion")),
            "actor_progress": parse_float(row.get("actor_progress")),
            "actor_item_type_id": parse_int(row.get("actor_item_type_id")),
            "actor_item_slot": parse_int(row.get("actor_item_slot"), -1),
            "actor_stack_count": parse_int(row.get("actor_stack_count")),
            "raw": row,
        })
    return rows


def supported_active_loot_rows(capture: dict[str, str]) -> list[dict[str, Any]]:
    return [
        row for row in replicated_loot_rows(capture)
        if row["network_drop_id"] != 0
        and row["type_id"] in {LOOT_GOLD_TYPE_ID, LOOT_ORB_TYPE_ID, LOOT_ITEM_DROP_TYPE_ID}
        and row["active"]
    ]


def replicated_loot_pickup_result(capture: dict[str, str]) -> dict[str, Any] | None:
    if not parse_bool(capture.get("pickup.valid")):
        return None
    return {
        "authority_participant_id": parse_int(capture.get("pickup.authority_participant_id")),
        "participant_id": parse_int(capture.get("pickup.participant_id")),
        "sequence": parse_int(capture.get("pickup.sequence")),
        "request_sequence": parse_int(capture.get("pickup.request_sequence")),
        "run_nonce": parse_int(capture.get("pickup.run_nonce")),
        "network_drop_id": parse_int(capture.get("pickup.network_drop_id")),
        "result": capture.get("pickup.result", ""),
        "kind": capture.get("pickup.kind", ""),
        "amount": parse_int(capture.get("pickup.amount")),
        "resulting_gold": parse_int(capture.get("pickup.resulting_gold")),
        "gold_revision": parse_int(capture.get("pickup.gold_revision")),
        "resource_kind": parse_int(capture.get("pickup.resource_kind"), -1),
        "resource_delta": parse_float(capture.get("pickup.resource_delta")),
        "item_type_id": parse_int(capture.get("pickup.item_type_id")),
        "item_slot": parse_int(capture.get("pickup.item_slot"), -1),
        "stack_count": parse_int(capture.get("pickup.stack_count")),
    }


def summarize_replicated_loot_capture(capture: dict[str, str]) -> dict[str, Any]:
    rows = supported_active_loot_rows(capture)
    pickup = replicated_loot_pickup_result(capture)
    return {
        "valid": capture.get("loot.valid"),
        "authority_participant_id": capture.get("loot.authority_participant_id"),
        "sequence": capture.get("loot.sequence"),
        "scene_epoch": capture.get("loot.scene_epoch"),
        "run_nonce": capture.get("loot.run_nonce"),
        "scene_kind": capture.get("loot.scene_kind"),
        "drop_count": capture.get("loot.drop_count"),
        "drop_total_count": capture.get("loot.drop_total_count"),
        "truncated": capture.get("loot.truncated"),
        "supported_active_count": len(rows),
        "supported_active_ids": [row["network_drop_id"] for row in rows],
        "last_pickup": pickup,
    }


def find_loot_row_by_id(capture: dict[str, str], network_drop_id: int) -> dict[str, Any] | None:
    for row in replicated_loot_rows(capture):
        if row["network_drop_id"] == network_drop_id:
            return row
    return None


def client_loot_presentation_converged(drop: dict[str, Any]) -> bool:
    if (
        not drop["active"]
        or not drop["materialized"]
        or drop["local_actor_address"] == 0
        or drop["actor_type_id"] != drop["type_id"]
        or distance(
            drop["x"],
            drop["y"],
            drop["actor_x"],
            drop["actor_y"],
        ) > LOOT_POSITION_TOLERANCE
        or abs(drop["radius"] - drop["actor_radius"])
        > LOOT_RADIUS_TOLERANCE
    ):
        return False

    if drop["type_id"] == LOOT_GOLD_TYPE_ID:
        return (
            drop["actor_amount"] == drop["amount"]
            and drop["actor_amount_tier"] == drop["amount_tier"]
        )
    if drop["type_id"] == LOOT_ORB_TYPE_ID:
        return (
            drop["actor_amount_tier"] == drop["amount_tier"]
            and abs(drop["actor_value"] - drop["value"])
            <= LOOT_VALUE_TOLERANCE
        )
    if drop["type_id"] == LOOT_ITEM_DROP_TYPE_ID:
        return (
            drop["actor_item_type_id"] == drop["item_type_id"]
            and drop["actor_item_slot"] == drop["item_slot"]
            and drop["actor_stack_count"] == drop["stack_count"]
        )
    return False


def wait_for_client_materialized_loot(
    network_drop_id: int,
    authority_participant_id: int,
    timeout: float = 5.0,
) -> dict[str, Any]:
    started = time.monotonic()
    deadline = time.monotonic() + timeout
    attempts = 0
    last_capture: dict[str, str] = {}
    last_row: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        attempts += 1
        last_capture = capture_replicated_loot(CLIENT_PIPE)
        last_row = find_loot_row_by_id(last_capture, network_drop_id)
        authority_id = parse_int(last_capture.get("loot.authority_participant_id"))
        if (
            last_row is not None
            and client_loot_presentation_converged(last_row)
            and authority_id == authority_participant_id
        ):
            return {
                "capture": summarize_replicated_loot_capture(last_capture),
                "drop": last_row,
                "presentation_convergence": {
                    "attempts": attempts,
                    "elapsed_seconds": time.monotonic() - started,
                },
            }
        time.sleep(0.03)
    raise VerifyFailure(
        "client natural-loot actor did not converge to its received snapshot "
        f"network_drop_id={network_drop_id}: last_row={last_row} "
        f"last_capture={summarize_replicated_loot_capture(last_capture)}"
    )


def compare_replicated_loot_drop(host_drop: dict[str, Any], client_drop: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []

    def fail(message: str) -> None:
        failures.append(message)

    if client_drop["network_drop_id"] != host_drop["network_drop_id"]:
        fail("network_drop_id differs")
    if client_drop["type_id"] != host_drop["type_id"]:
        fail("native type differs")
    if not client_drop["active"]:
        fail("client snapshot does not mark drop active")
    if not client_drop["materialized"] or client_drop["local_actor_address"] == 0:
        fail("client did not materialize a presentation actor")
    if client_drop["actor_type_id"] != host_drop["type_id"]:
        fail("client presentation actor native type differs")
    if client_drop["presentation_state"] != host_drop["presentation_state"]:
        fail("drop presentation state differs")

    snapshot_position_delta = distance(
        host_drop["x"], host_drop["y"], client_drop["x"], client_drop["y"])
    actor_position_delta = distance(
        client_drop["x"], client_drop["y"], client_drop["actor_x"], client_drop["actor_y"])
    snapshot_radius_delta = abs(host_drop["radius"] - client_drop["radius"])
    actor_radius_delta = abs(host_drop["radius"] - client_drop["actor_radius"])
    snapshot_position_tolerance = (
        ANIMATED_LOOT_POSITION_TOLERANCE
        if host_drop["type_id"] in {LOOT_GOLD_TYPE_ID, LOOT_ORB_TYPE_ID}
        else LOOT_POSITION_TOLERANCE
    )
    if snapshot_position_delta > snapshot_position_tolerance:
        fail("client snapshot drop position differs from host")
    if actor_position_delta > LOOT_POSITION_TOLERANCE:
        fail("client presentation actor position differs from received snapshot")
    if snapshot_radius_delta > LOOT_RADIUS_TOLERANCE:
        fail("client snapshot drop radius differs from host")
    if actor_radius_delta > LOOT_RADIUS_TOLERANCE:
        fail("client presentation actor radius differs from host")

    if client_drop["amount"] != host_drop["amount"]:
        fail("drop amount differs")
    if client_drop["amount_tier"] != host_drop["amount_tier"]:
        fail("drop amount/resource tier differs")
    if abs(client_drop["value"] - host_drop["value"]) > LOOT_VALUE_TOLERANCE:
        fail("drop value differs")

    type_id = host_drop["type_id"]
    if type_id == LOOT_GOLD_TYPE_ID:
        if client_drop["actor_amount"] != host_drop["amount"]:
            fail("client gold actor amount differs from host")
        if client_drop["actor_amount_tier"] != host_drop["amount_tier"]:
            fail("client gold actor tier differs from host")
    elif type_id == LOOT_ORB_TYPE_ID:
        if client_drop["actor_amount_tier"] != host_drop["amount_tier"]:
            fail("client orb actor resource kind differs from host")
        if abs(client_drop["actor_value"] - host_drop["value"]) > LOOT_VALUE_TOLERANCE:
            fail("client orb actor value differs from host")
    elif type_id == LOOT_ITEM_DROP_TYPE_ID:
        if client_drop["item_type_id"] != host_drop["item_type_id"]:
            fail("client item drop snapshot item type differs")
        if client_drop["item_slot"] != host_drop["item_slot"]:
            fail("client item drop snapshot slot differs")
        if client_drop["stack_count"] != host_drop["stack_count"]:
            fail("client item drop snapshot stack count differs")
        if client_drop["actor_item_type_id"] != host_drop["item_type_id"]:
            fail("client item presentation item type differs")
        if client_drop["actor_item_slot"] != host_drop["item_slot"]:
            fail("client item presentation slot differs")
        if client_drop["actor_stack_count"] != host_drop["stack_count"]:
            fail("client item presentation stack count differs")

    return {
        "ok": not failures,
        "failures": failures,
        "network_drop_id": host_drop["network_drop_id"],
        "type_id": type_id,
        "kind": host_drop["kind"],
        "host_drop": host_drop,
        "client_drop": client_drop,
        "snapshot_position_delta": round(snapshot_position_delta, 4),
        "snapshot_position_tolerance": snapshot_position_tolerance,
        "actor_position_delta": round(actor_position_delta, 4),
        "snapshot_radius_delta": round(snapshot_radius_delta, 4),
        "actor_radius_delta": round(actor_radius_delta, 4),
    }


def wait_for_new_host_natural_loot(
    before_capture: dict[str, str],
    *,
    timeout: float = NATURAL_DROP_WAIT_SECONDS,
) -> dict[str, Any]:
    before_ids = {
        row["network_drop_id"]
        for row in replicated_loot_rows(before_capture)
        if row["network_drop_id"] != 0
    }
    before_pickup = replicated_loot_pickup_result(before_capture)
    before_pickup_id = before_pickup["network_drop_id"] if before_pickup else 0
    deadline = time.monotonic() + timeout
    last_capture: dict[str, str] = {}
    while time.monotonic() < deadline:
        last_capture = capture_replicated_loot(HOST_PIPE)
        new_rows = [
            row for row in supported_active_loot_rows(last_capture)
            if row["network_drop_id"] not in before_ids
        ]
        if new_rows:
            return {
                "observed": True,
                "before": summarize_replicated_loot_capture(before_capture),
                "host_after": summarize_replicated_loot_capture(last_capture),
                "drops": new_rows,
            }
        pickup = replicated_loot_pickup_result(last_capture)
        if (
            pickup is not None
            and pickup["network_drop_id"] != 0
            and pickup["network_drop_id"] not in before_ids
            and pickup["network_drop_id"] != before_pickup_id
            and pickup["result"] == "Accepted"
        ):
            return {
                "observed": True,
                "observed_mode": "quick_pickup",
                "before": summarize_replicated_loot_capture(before_capture),
                "host_after": summarize_replicated_loot_capture(last_capture),
                "drops": [],
                "quick_pickups": [pickup],
            }
        time.sleep(0.1)
    return {
        "observed": False,
        "observed_mode": "none",
        "before": summarize_replicated_loot_capture(before_capture),
        "host_after": summarize_replicated_loot_capture(last_capture),
        "drops": [],
        "quick_pickups": [],
    }


def verify_natural_death_loot(before_capture: dict[str, str]) -> dict[str, Any]:
    host_new = wait_for_new_host_natural_loot(before_capture)
    if not host_new["observed"]:
        return host_new
    expected_authority_id = parse_int(
        before_capture.get("loot.authority_participant_id"),
        parse_int(host_new["host_after"].get("authority_participant_id")),
    )
    host_authority_id = parse_int(host_new["host_after"].get("authority_participant_id"))
    if expected_authority_id == 0 or host_authority_id != expected_authority_id:
        raise VerifyFailure(
            "host natural loot snapshot did not report host authority: "
            f"authority_participant_id={host_authority_id} expected={expected_authority_id} "
            f"snapshot={host_new['host_after']}"
        )
    quick_pickup_failures = [
        pickup for pickup in host_new.get("quick_pickups", [])
        if pickup.get("authority_participant_id") != expected_authority_id
        or pickup.get("result") != "Accepted"
    ]
    if quick_pickup_failures:
        raise VerifyFailure(f"natural loot quick-pickup authority mismatch: {quick_pickup_failures}")

    comparisons: list[dict[str, Any]] = []
    for host_drop in host_new["drops"]:
        client = wait_for_client_materialized_loot(
            host_drop["network_drop_id"],
            expected_authority_id,
        )
        comparison = compare_replicated_loot_drop(host_drop, client["drop"])
        comparison["client_capture"] = client["capture"]
        comparison["presentation_convergence"] = client["presentation_convergence"]
        client_authority_id = parse_int(client["capture"].get("authority_participant_id"))
        if client_authority_id != expected_authority_id:
            comparison["ok"] = False
            comparison.setdefault("failures", []).append("client snapshot authority is not host")
        comparisons.append(comparison)

    failures = [comparison for comparison in comparisons if not comparison["ok"]]
    if failures:
        raise VerifyFailure(f"natural loot presentation mismatch: {failures}")

    return {
        **host_new,
        "authority_participant_id": expected_authority_id,
        "comparisons": comparisons,
    }


def loot_pickup_result(pipe_name: str, network_drop_id: int, amount: int) -> dict[str, str]:
    return values(
        pipe_name,
        LOOT_PICKUP_RESULT_LUA
        .replace("__DROP_ID__", str(network_drop_id))
        .replace("__AMOUNT__", str(amount)),
        timeout=5.0,
    )


def pickup_result_accepted(result: dict[str, str]) -> bool:
    return result.get("matches") == "true"


def wait_for_exact_loot_pickup_result(
    pipe_name: str,
    network_drop_id: int,
    amount: int,
    *,
    timeout: float = 6.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = loot_pickup_result(pipe_name, network_drop_id, amount)
        if pickup_result_accepted(last):
            return last
        time.sleep(0.1)
    raise VerifyFailure(
        f"{pipe_name} did not receive accepted loot pickup result "
        f"network_drop_id={network_drop_id}: last={last}"
    )


def wait_for_replicated_gold_present_or_picked_up(
    pipe_name: str,
    amount: int,
    x: float,
    y: float,
    network_drop_id: int,
    *,
    timeout: float = 6.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_drop: dict[str, str] = {}
    last_pickup: dict[str, str] = {}
    while time.monotonic() < deadline:
        try:
            drop = wait_for_replicated_gold_drop(
                pipe_name,
                amount,
                x,
                y,
                materialized_required=True,
                timeout=0.15,
            )
        except VerifyFailure as exc:
            last_drop = {"error": str(exc)}
        else:
            return {
                "state": "present",
                "drop": drop,
                "pickup_result": last_pickup,
            }

        last_pickup = loot_pickup_result(pipe_name, network_drop_id, amount)
        if pickup_result_accepted(last_pickup):
            return {
                "state": "picked_up",
                "drop": last_drop,
                "pickup_result": last_pickup,
            }
        time.sleep(0.1)

    raise VerifyFailure(
        f"{pipe_name} did not retain or natively pick up forced gold "
        f"network_drop_id={network_drop_id}: last_drop={last_drop} last_pickup={last_pickup}"
    )


def wait_for_replicated_gold_absent(pipe_name: str, amount: int, x: float, y: float, timeout: float) -> dict[str, str]:
    code = (
        FIND_REPLICATED_GOLD_DROP_LUA
        .replace("__AMOUNT__", str(amount))
        .replace("__X__", f"{x:.3f}")
        .replace("__Y__", f"{y:.3f}")
        .replace("__RADIUS__", f"{DROP_MATCH_RADIUS:.3f}")
    )
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = values(pipe_name, code)
        if last.get("found") != "true":
            return last
        time.sleep(0.1)
    raise VerifyFailure(f"{pipe_name} still sees forced gold drop amount={amount}: last={last}")


def verify_one_kill(direction: Direction, kill_index: int, record: dict[str, Any] | None = None) -> dict[str, Any]:
    if record is None:
        record = {
            "direction": direction.name,
            "kill_index": kill_index,
        }
    record["status"] = "setup"
    anchor = HOST_TARGET if direction.source_pipe == HOST_PIPE else CLIENT_TARGET
    append_runtime_context(record, f"{direction.name}.{kill_index}.start")
    quiesce_before_cleanup = quiesce_gameplay_primary_input(f"{direction.name}.{kill_index}.before_cleanup")
    record.setdefault("quiesce", {})["before_cleanup"] = quiesce_before_cleanup
    append_runtime_context(record, f"{direction.name}.{kill_index}.after_before_cleanup_quiesce")
    vector_before_cleanup = probe_stock_placement_vectors(f"{direction.name}.{kill_index}.before_cleanup")
    record.setdefault("stock_placement_vectors", {})["before_cleanup"] = vector_before_cleanup
    cleanup = cleanup_live_enemies()
    record["cleanup"] = cleanup
    append_runtime_context(record, f"{direction.name}.{kill_index}.after_cleanup")
    vector_after_cleanup = probe_stock_placement_vectors(f"{direction.name}.{kill_index}.after_cleanup")
    record.setdefault("stock_placement_vectors", {})["after_cleanup"] = vector_after_cleanup
    lane = place_pair_on_clear_lane(direction, anchor)
    record["clear_lane_planned"] = lane
    append_runtime_context(record, f"{direction.name}.{kill_index}.after_lane_selection")
    vector_after_lane = probe_stock_placement_vectors(f"{direction.name}.{kill_index}.after_lane_selection")
    record.setdefault("stock_placement_vectors", {})["after_lane_selection"] = vector_after_lane
    target_x = float(lane["x"])
    target_y = float(lane["y"])
    park = park_pair_away_from_target(target_x, target_y)
    record["park_before_spawn"] = park
    append_runtime_context(record, f"{direction.name}.{kill_index}.after_park_before_spawn")
    vector_after_park = probe_stock_placement_vectors(f"{direction.name}.{kill_index}.after_park")
    record.setdefault("stock_placement_vectors", {})["after_park"] = vector_after_park
    quiesce_before_spawn = quiesce_gameplay_primary_input(f"{direction.name}.{kill_index}.before_spawn")
    record.setdefault("quiesce", {})["before_spawn"] = quiesce_before_spawn
    spawn = spawn_one_enemy(target_x, target_y)
    record["spawn"] = spawn
    append_runtime_context(record, f"{direction.name}.{kill_index}.after_spawn")
    vector_after_spawn = probe_stock_placement_vectors(f"{direction.name}.{kill_index}.after_spawn")
    record.setdefault("stock_placement_vectors", {})["after_spawn"] = vector_after_spawn
    network_id = int(spawn["network_actor_id"])
    initial_host_target = find_target(
        HOST_PIPE,
        target_x,
        target_y,
        network_id,
        timeout=6.0,
        require_local_binding=False,
    )
    record["initial_host_target"] = initial_host_target
    stage(f"  kill {kill_index}: enemy spawned net_id={network_id} actor=0x{int(spawn['actor_address']):08X}")
    host_target = wait_for_target_hp_at_least(
        HOST_PIPE,
        target_x,
        target_y,
        network_id,
        SETUP_TARGET_HP,
        timeout=6.0,
        require_local_binding=False,
    )
    client_target = wait_for_target_hp_at_least(
        CLIENT_PIPE,
        target_x,
        target_y,
        network_id,
        SETUP_TARGET_HP,
        timeout=6.0,
    )
    record["host_target"] = host_target
    record["client_target"] = client_target
    quiesce_after_spawn_parked = quiesce_gameplay_primary_input(
        f"{direction.name}.{kill_index}.after_spawn_parked"
    )
    record.setdefault("quiesce", {})["after_spawn_parked"] = quiesce_after_spawn_parked
    host_spawn_parked_target = wait_for_target_hp_at_least(
        HOST_PIPE,
        target_x,
        target_y,
        network_id,
        SETUP_TARGET_HP,
        timeout=4.0,
        require_local_binding=False,
    )
    client_spawn_parked_target = wait_for_target_hp_at_least(
        CLIENT_PIPE,
        target_x,
        target_y,
        network_id,
        SETUP_TARGET_HP,
        timeout=4.0,
    )
    record["host_spawn_parked_target"] = host_spawn_parked_target
    record["client_spawn_parked_target"] = client_spawn_parked_target
    placement = place_pair_for_direction(direction, target_x, target_y)
    record["placement"] = placement
    source_x, source_y = source_settled_position(direction, placement)
    source_target_distance = distance(source_x, source_y, target_x, target_y)
    settled_probe = clear_lane_between(
        source_x,
        source_y,
        target_x,
        target_y,
        pipe_name=direction.source_pipe,
    )
    record["clear_lane"] = {
        "x": target_x,
        "y": target_y,
        "planned_probe": lane["probe"],
        "settled_probe": settled_probe,
        "source_x": source_x,
        "source_y": source_y,
        "source_target_distance": source_target_distance,
        "placement": placement,
        "attempts": lane["attempts"],
    }
    if (
        settled_probe.get("ok") != "true"
        or parse_int(settled_probe.get("blocker_count")) != 0
        or source_target_distance > MAX_SCRIPTED_PRIMARY_TARGET_DISTANCE
    ):
        raise VerifyFailure(
            f"{direction.name}: settled cast lane became blocked after placement: {record['clear_lane']}"
        )
    vector_after_placement = probe_stock_placement_vectors(f"{direction.name}.{kill_index}.after_placement")
    record.setdefault("stock_placement_vectors", {})["after_placement"] = vector_after_placement
    quiesce_after_placement = quiesce_gameplay_primary_input(f"{direction.name}.{kill_index}.after_placement")
    record.setdefault("quiesce", {})["after_placement"] = quiesce_after_placement
    reset_full_hp_config = configure_enemy(int(spawn["actor_address"]), target_x, target_y, SETUP_TARGET_HP)
    record["reset_full_hp_config"] = reset_full_hp_config
    host_reset_target = wait_for_target_hp_at_least(
        HOST_PIPE,
        target_x,
        target_y,
        network_id,
        SETUP_TARGET_HP,
        timeout=5.0,
        require_local_binding=False,
    )
    client_reset_target = wait_for_target_hp_at_least(
        CLIENT_PIPE,
        target_x,
        target_y,
        network_id,
        SETUP_TARGET_HP,
        timeout=5.0,
    )
    record["host_reset_target"] = host_reset_target
    record["client_reset_target"] = client_reset_target
    quiesce_before_low_hp = quiesce_gameplay_primary_input(f"{direction.name}.{kill_index}.before_low_hp")
    record.setdefault("quiesce", {})["before_low_hp"] = quiesce_before_low_hp
    host_pre_low_hp_target = wait_for_target_hp_at_least(
        HOST_PIPE,
        target_x,
        target_y,
        network_id=network_id,
        min_hp=SETUP_TARGET_HP,
        timeout=4.0,
        require_local_binding=False,
    )
    client_pre_low_hp_target = wait_for_target_hp_at_least(
        CLIENT_PIPE,
        target_x,
        target_y,
        network_id=network_id,
        min_hp=SETUP_TARGET_HP,
        timeout=4.0,
    )
    record["host_pre_low_hp_target"] = host_pre_low_hp_target
    record["client_pre_low_hp_target"] = client_pre_low_hp_target
    require_target_alive(
        f"{direction.name}: host target before low-hp setup",
        host_pre_low_hp_target,
        {"quiesce_before_low_hp": quiesce_before_low_hp, "spawn": spawn},
    )
    require_target_hp_at_least(
        f"{direction.name}: host target before low-hp setup",
        host_pre_low_hp_target,
        SETUP_TARGET_HP - 0.05,
        {"quiesce_before_low_hp": quiesce_before_low_hp, "spawn": spawn},
    )
    require_target_alive(
        f"{direction.name}: client target before low-hp setup",
        client_pre_low_hp_target,
        {"quiesce_before_low_hp": quiesce_before_low_hp, "spawn": spawn},
    )
    require_target_hp_at_least(
        f"{direction.name}: client target before low-hp setup",
        client_pre_low_hp_target,
        SETUP_TARGET_HP - 0.05,
        {"quiesce_before_low_hp": quiesce_before_low_hp, "spawn": spawn},
    )
    low_hp_config = configure_enemy(int(spawn["actor_address"]), target_x, target_y, LOW_TARGET_HP)
    record["low_hp_config"] = low_hp_config
    host_low_hp_target = find_target(
        HOST_PIPE,
        target_x,
        target_y,
        network_id=network_id,
        timeout=4.0,
        require_local_binding=False,
    )
    client_low_hp_target = wait_for_target_hp(
        CLIENT_PIPE,
        target_x,
        target_y,
        network_id,
        LOW_TARGET_HP,
        timeout=5.0,
    )
    record["host_low_hp_target"] = host_low_hp_target
    record["client_low_hp_target"] = client_low_hp_target
    source_target = host_low_hp_target if direction.source_pipe == HOST_PIPE else client_low_hp_target
    target_actor = (
        int(spawn["actor_address"])
        if direction.source_pipe == HOST_PIPE
        else parse_int(source_target.get("local.actor_address"))
    )
    if target_actor == 0:
        raise VerifyFailure(f"{direction.name}: source target actor missing: {source_target}")
    target_descriptor = {
        "network_id": network_id,
        "host_actor_address": int(spawn["actor_address"]),
        "source_actor_address": target_actor,
        "x": target_x,
        "y": target_y,
    }
    record["target"] = target_descriptor
    natural_loot_before = capture_replicated_loot(HOST_PIPE)
    record["natural_loot_before"] = summarize_replicated_loot_capture(natural_loot_before)
    stage(f"  kill {kill_index}: arming primary cast toward target")
    record["cast_attempts"] = []
    selected_attempt: dict[str, Any] | None = None
    for attempt_index, frames in enumerate(CAST_ATTEMPT_FRAMES, start=1):
        if attempt_index > 1:
            retry_clear = quiesce_gameplay_primary_input(
                f"{direction.name}.{kill_index}.retry_{attempt_index}.before_rearm",
                stable_seconds=1.25,
            )
            retry_placement = place_pair_for_direction(direction, target_x, target_y)
            retry_source_x, retry_source_y = source_settled_position(direction, retry_placement)
            retry_lane_probe = clear_lane_between(
                retry_source_x,
                retry_source_y,
                target_x,
                target_y,
                pipe_name=direction.source_pipe,
            )
            retry_target = sample_target_state(direction, target_descriptor)
            rearm_record = {
                "attempt": attempt_index,
                "status": "rearm",
                "clear": retry_clear,
                "placement": retry_placement,
                "lane_probe": retry_lane_probe,
                "target": retry_target,
            }
            record["cast_attempts"].append(rearm_record)
            if (
                retry_lane_probe.get("ok") != "true"
                or parse_int(retry_lane_probe.get("blocker_count")) != 0
            ):
                raise VerifyFailure(
                    f"{direction.name}: unable to re-arm scripted primary kill attempt "
                    f"{attempt_index}: lane={retry_lane_probe} target={retry_target}"
                )
            target_alive_on_both = (
                target_state_alive(retry_target.get("host", {}))
                and target_state_alive(retry_target.get("client", {}))
            )
            if not target_alive_on_both:
                if finalize_late_primary_death(
                    direction,
                    target_descriptor,
                    attempt,
                    retry_target,
                ):
                    rearm_record["status"] = "late_death_observed"
                    selected_attempt = attempt
                    break
                raise VerifyFailure(
                    f"{direction.name}: unable to re-arm scripted primary kill attempt "
                    f"{attempt_index}: lane={retry_lane_probe} target={retry_target}"
                )
        attempt = execute_primary_kill_attempt(
            direction,
            target_descriptor,
            frames,
            attempt_index,
        )
        record["cast_attempts"].append(attempt)
        if attempt.get("status") == "death_logs_observed":
            selected_attempt = attempt
            break
        if attempt.get("status") not in {"native_primary_no_kill", "source_cast_missing"}:
            break
    if selected_attempt is None:
        raise VerifyFailure(
            f"{direction.name}: scripted primary never produced a source-side kill effect. "
            f"attempts={record['cast_attempts']}"
        )
    record["source_cast_runtime_before"] = selected_attempt.get("source_cast_runtime_before")
    record["prepare"] = selected_attempt.get("prepare")
    record["queue"] = selected_attempt.get("queue")
    record["status"] = "cast_queued"
    record["phase_counts"] = selected_attempt.get("phase_counts")
    record["native_hook_count"] = selected_attempt.get("native_hook_count")
    record["level_up_resolutions"] = selected_attempt.get("level_up_resolutions", [])
    record["source_log_tail"] = selected_attempt.get("source_log_tail")
    record["cast_impact_timeline"] = selected_attempt.get("cast_impact_timeline")
    death_logs = selected_attempt["death_logs"]
    record["death_logs"] = death_logs
    death_state = wait_for_death(
        direction,
        {
            "network_id": network_id,
            "actor_address": int(spawn["actor_address"]),
            "x": target_x,
            "y": target_y,
        },
        timeout=8.0,
        allow_removed=True,
    )
    record["death_state"] = death_state
    record["natural_loot"] = verify_natural_death_loot(natural_loot_before)
    stage(f"  kill {kill_index}: death confirmed on both views; verifying loot drop+pickup")
    clear_freeze = values(
        HOST_PIPE,
        CLEAR_FREEZE_LUA.replace("__ACTOR__", str(int(spawn["actor_address"]))),
    )
    record["clear_freeze"] = clear_freeze
    forced_gold_location = select_forced_gold_location(
        target_x,
        target_y,
        CLIENT_PIPE,
        placement,
    )
    record["forced_gold_location"] = forced_gold_location
    forced_gold_park = park_pair_away_from_target(
        forced_gold_location["x"],
        forced_gold_location["y"],
    )
    record["forced_gold_park"] = forced_gold_park
    forced_gold = verify_forced_gold_drop(
        amount=FORCED_GOLD_AMOUNT,
        x=forced_gold_location["x"],
        y=forced_gold_location["y"],
        pickup_pipe=CLIENT_PIPE,
    )
    record["forced_gold"] = forced_gold
    post_kill_cleanup = cleanup_live_enemies()
    record["post_kill_cleanup"] = post_kill_cleanup
    append_runtime_context(record, f"{direction.name}.{kill_index}.passed")
    record["status"] = "passed"
    return record


def verify_level_up_choice_without_waves(timeout: float = 12.0) -> dict[str, Any]:
    host_stats = query_progression_stats(HOST_PIPE, participant_id=CLIENT_ID)
    client_stats = query_progression_stats(CLIENT_PIPE)
    target_level = max(host_stats["level"], client_stats["level"], 1) + 1
    target_experience = int(max(host_stats["next_xp_threshold"], client_stats["next_xp_threshold"], 125.0) + 10.0)
    publish = publish_offer(target_level, target_experience)
    offer = wait_for_client_offer(target_level, timeout)
    wait_active = wait_for_wait_status(participant_id=CLIENT_ID, pause_active=True, timeout=timeout)
    selected_option_index = 1
    selected_option_id = offer["option_ids"][selected_option_index - 1]
    before_host = query_progression_entry(HOST_PIPE, option_id=selected_option_id, participant_id=CLIENT_ID)
    before_client = query_progression_entry(CLIENT_PIPE, option_id=selected_option_id)
    choice = choose_client_option(offer["offer_id"], selected_option_index)
    result = wait_for_choice_result(offer["offer_id"], target_level, timeout)
    wait_cleared = wait_for_wait_status(participant_id=CLIENT_ID, pause_active=False, timeout=timeout)
    after_host = wait_for_progression_entry_active(
        HOST_PIPE,
        option_id=selected_option_id,
        expected_active=result["resulting_active"],
        timeout=timeout,
        participant_id=CLIENT_ID,
    )
    after_client = wait_for_progression_entry_active(
        CLIENT_PIPE,
        option_id=selected_option_id,
        expected_active=result["resulting_active"],
        timeout=timeout,
    )
    if after_host["active"] <= before_host["active"]:
        raise VerifyFailure(
            f"host did not apply selected client skill option: before={before_host} after={after_host}"
        )
    if after_client["active"] <= before_client["active"]:
        raise VerifyFailure(
            f"client did not apply selected local skill option: before={before_client} after={after_client}"
        )
    host_combat = values(HOST_PIPE, COMBAT_STATE_LUA)
    client_combat = values(CLIENT_PIPE, COMBAT_STATE_LUA)
    host_enemies = values(HOST_PIPE, LIVE_ENEMY_COUNT_LUA)
    client_enemies = values(CLIENT_PIPE, LIVE_ENEMY_COUNT_LUA)
    if parse_int(host_enemies.get("live_enemy_count")) != 0 or parse_int(client_enemies.get("live_enemy_count")) != 0:
        raise VerifyFailure(
            "level-up verification left ambient enemies alive: "
            f"host={host_combat}/{host_enemies} client={client_combat}/{client_enemies}"
        )
    return {
        "host_stats_before": host_stats,
        "client_stats_before": client_stats,
        "target_level": target_level,
        "target_experience": target_experience,
        "publish": publish,
        "offer": offer,
        "wait_active": wait_active,
        "selected_option_index": selected_option_index,
        "selected_option_id": selected_option_id,
        "choice": choice,
        "result": result,
        "wait_cleared": wait_cleared,
        "selected_entry": {
            "before_host": before_host,
            "after_host": after_host,
            "before_client": before_client,
            "after_client": after_client,
        },
        "combat_after": {
            "host": host_combat,
            "client": client_combat,
        },
        "live_enemy_count_after": {
            "host": host_enemies,
            "client": client_enemies,
        },
    }


def summarize_natural_loot_records(kills: list[dict[str, Any]]) -> dict[str, Any]:
    observed_kill_indices: list[int] = []
    compared_drop_count = 0
    quick_pickup_count = 0
    by_type: dict[str, int] = {}
    by_direction: dict[str, dict[str, int]] = {}
    failures: list[dict[str, Any]] = []
    for record in kills:
        natural = record.get("natural_loot") or {}
        if not natural.get("observed"):
            continue
        direction = str(record.get("direction") or "unknown")
        direction_counts = by_direction.setdefault(direction, {
            "observed_kills": 0,
            "compared_drop_count": 0,
            "quick_pickup_count": 0,
        })
        direction_counts["observed_kills"] += 1
        observed_kill_indices.append(int(record.get("kill_index") or 0))
        for comparison in natural.get("comparisons") or []:
            compared_drop_count += 1
            direction_counts["compared_drop_count"] += 1
            key = str(comparison.get("type_id") or "unknown")
            by_type[key] = by_type.get(key, 0) + 1
            if not comparison.get("ok"):
                failures.append({
                    "kill_index": record.get("kill_index"),
                    "comparison": comparison,
                })
        for pickup in natural.get("quick_pickups") or []:
            quick_pickup_count += 1
            direction_counts["quick_pickup_count"] += 1
            key = "pickup:" + str(pickup.get("kind") or "unknown")
            by_type[key] = by_type.get(key, 0) + 1
    return {
        "observed_kill_count": len(observed_kill_indices),
        "observed_kill_indices": observed_kill_indices,
        "drop_count": compared_drop_count + quick_pickup_count,
        "compared_drop_count": compared_drop_count,
        "quick_pickup_count": quick_pickup_count,
        "by_type": by_type,
        "by_direction": by_direction,
        "failures": failures,
    }


def crash_log_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def crash_log_tail(path: Path, offset: int) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[offset:]


def validated_resume_kills(
    prior: dict[str, Any],
    direction_names: tuple[str, ...],
    kills_per_participant: int,
) -> list[dict[str, Any]]:
    records = prior.get("kills")
    if not isinstance(records, list):
        raise VerifyFailure("primary-kill resume evidence has no kill list")

    planned_directions = [
        direction_name
        for direction_name in direction_names
        for _ in range(kills_per_participant)
    ]
    passed_prefix: list[dict[str, Any]] = []
    gap_seen = False
    for expected_index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise VerifyFailure(
                f"primary-kill resume record {expected_index} is not an object"
            )
        if expected_index > len(planned_directions):
            raise VerifyFailure(
                "primary-kill resume evidence contains more records than the "
                "requested matrix"
            )
        if record.get("kill_index") != expected_index:
            raise VerifyFailure(
                "primary-kill resume evidence is not sequential: "
                f"expected kill {expected_index}, got {record.get('kill_index')!r}"
            )
        expected_direction = planned_directions[expected_index - 1]
        if record.get("direction") != expected_direction:
            raise VerifyFailure(
                "primary-kill resume direction mismatch at kill "
                f"{expected_index}: expected {expected_direction}, "
                f"got {record.get('direction')!r}"
            )
        if record.get("status") == "passed":
            if gap_seen:
                raise VerifyFailure(
                    "primary-kill resume evidence contains a passed kill after "
                    "an incomplete record"
                )
            passed_prefix.append(dict(record))
        else:
            gap_seen = True
    return passed_prefix


def load_resume_kills(
    path: Path,
    direction_names: tuple[str, ...],
    kills_per_participant: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        prior = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise VerifyFailure(
            f"cannot read primary-kill resume evidence {path}: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise VerifyFailure(
            f"primary-kill resume evidence is not valid JSON: {path}"
        ) from exc
    if not isinstance(prior, dict):
        raise VerifyFailure("primary-kill resume evidence root is not an object")
    parameters = prior.get("parameters")
    if not isinstance(parameters, dict):
        raise VerifyFailure("primary-kill resume evidence has no parameters")
    if parameters.get("kills_per_participant") != kills_per_participant:
        raise VerifyFailure(
            "primary-kill resume count does not match this run: "
            f"evidence={parameters.get('kills_per_participant')!r} "
            f"requested={kills_per_participant}"
        )
    if prior.get("host_crash_delta") or prior.get("client_crash_delta"):
        raise VerifyFailure(
            "primary-kill resume evidence contains a new crash-log delta"
        )
    return prior, validated_resume_kills(
        prior,
        direction_names,
        kills_per_participant,
    )


def run_verifier(args: argparse.Namespace) -> dict[str, Any]:
    result: dict[str, Any] = {
        "parameters": {
            key: str(value) if isinstance(value, Path) else value
            for key, value in vars(args).items()
        },
        "started_at": time.time(),
        "kills": [],
    }
    host_crash_start = crash_log_size(HOST_CRASH_LOG)
    client_crash_start = crash_log_size(CLIENT_CRASH_LOG)
    try:
        if not args.attach:
            stage("stopping any running games")
            stop_games()
            stage("launching host+client pair (god mode)")
            result["launch"] = launch_pair(god_mode=True, tile_windows=False)
        stage("disabling bots on both instances")
        result["disable_bots"] = disable_bots()
        result["pids"] = detect_instance_pids()
        result.setdefault("stock_placement_vectors", {})["before_run_entry"] = (
            probe_stock_placement_vectors("before_run_entry")
        )
        result["run_entry_mode"] = "stock_testrun"
        host_scene = query(HOST_PIPE).get("scene", "")
        client_scene = query(CLIENT_PIPE).get("scene", "")
        if args.attach and host_scene == "testrun" and client_scene == "testrun":
            stage("using already-running shared stock testrun")
            result["run_entry"] = {
                "already_testrun": True,
                "host_scene": host_scene,
                "client_scene": client_scene,
            }
        else:
            stage("entering stock testrun, waiting for both clients in scene")
            result["run_entry"] = start_host_testrun_and_wait_for_clients(timeout=60.0)
        wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "testrun")
        wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "testrun")
        result.setdefault("stock_placement_vectors", {})["after_run_entry"] = (
            probe_stock_placement_vectors("after_run_entry")
        )
        existing_manual_spawners = {
            "host": manual_spawner_state(HOST_PIPE),
            "client": manual_spawner_state(CLIENT_PIPE),
        }
        manual_spawners_ready = all(
            state.get("manual_mode") == "true"
            and state.get("has_spawner") == "true"
            for state in existing_manual_spawners.values()
        )
        if args.attach and manual_spawners_ready:
            stage("using already-ready native manual stock spawners")
            result["combat_bootstrap"] = {
                "already_ready": True,
                "spawners": existing_manual_spawners,
            }
        else:
            stage("enabling manual stock spawner combat")
            result["combat_bootstrap"] = enable_manual_stock_spawner_combat()
        result.setdefault("stock_placement_vectors", {})["after_combat_bootstrap"] = (
            probe_stock_placement_vectors("after_combat_bootstrap")
        )
        result["initial_cleanup"] = cleanup_live_enemies()
        result.setdefault("stock_placement_vectors", {})["after_initial_cleanup"] = (
            probe_stock_placement_vectors("after_initial_cleanup")
        )
        directions = [
            Direction("host_to_client", HOST_ID, HOST_NAME, HOST_PIPE, HOST_LOG, result["pids"]["host"], CLIENT_PIPE, CLIENT_LOG),
            Direction("client_to_host", CLIENT_ID, CLIENT_NAME, CLIENT_PIPE, CLIENT_LOG, result["pids"]["client"], HOST_PIPE, HOST_LOG),
        ]
        direction_names = tuple(direction.name for direction in directions)
        resume_output = args.resume_output
        if resume_output is not None:
            if not args.attach:
                raise VerifyFailure("--resume-output requires --attach")
            prior, resumed_kills = load_resume_kills(
                resume_output,
                direction_names,
                args.kills_per_participant,
            )
            result["kills"] = resumed_kills
            result["resume"] = {
                "source": str(resume_output),
                "passed_prefix_count": len(resumed_kills),
                "prior_ok": bool(prior.get("ok")),
                "prior_error_type": prior.get("error_type"),
            }
            stage(
                "accepted contiguous passed resume prefix: "
                f"{len(resumed_kills)} kills"
            )
        planned_directions = [
            direction
            for direction in directions
            for _ in range(args.kills_per_participant)
        ]
        total_kills = len(planned_directions)
        stage(
            f"entering kill loop: {total_kills} kills "
            f"({args.kills_per_participant}/participant x {len(directions)} directions)"
        )
        for kill_index, direction in enumerate(planned_directions, start=1):
            if kill_index <= len(result["kills"]):
                continue
            kill_started = time.monotonic()
            stage(f"=== kill {kill_index}/{total_kills} [{direction.name}] begin ===")
            record = {
                "direction": direction.name,
                "kill_index": kill_index,
                "status": "created",
            }
            result["kills"].append(record)
            verify_one_kill(direction, kill_index, record)
            stage(
                f"=== kill {kill_index}/{total_kills} [{direction.name}] PASSED "
                f"in {time.monotonic() - kill_started:.1f}s ==="
            )
            if (kill_index + 1) % 4 == 0:
                result.setdefault("vitals", []).append({
                    "host": set_local_player_vitals(HOST_PIPE, 5000.0, 5000.0),
                    "client": set_local_player_vitals(CLIENT_PIPE, 5000.0, 5000.0),
                })
        result["natural_loot_summary"] = summarize_natural_loot_records(result["kills"])
        if args.require_natural_drop and result["natural_loot_summary"]["drop_count"] <= 0:
            raise VerifyFailure(
                "no real host-authored natural death-roll loot drops were observed "
                f"across {len(result['kills'])} kills"
            )
        result["level_up_choice"] = verify_level_up_choice_without_waves(timeout=args.timeout)
        result["final_combat"] = {
            "host": values(HOST_PIPE, COMBAT_STATE_LUA),
            "client": values(CLIENT_PIPE, COMBAT_STATE_LUA),
        }
        result["ok"] = True
    except Exception as exc:
        result["ok"] = False
        result["error"] = str(exc)
        result["error_type"] = type(exc).__name__
        result["error_traceback"] = traceback.format_exc()
        result["failure_context"] = capture_runtime_context("failure", include_processes=True)
        result["host_crash_delta"] = crash_log_tail(HOST_CRASH_LOG, host_crash_start)
        result["client_crash_delta"] = crash_log_tail(CLIENT_CRASH_LOG, client_crash_start)
        raise
    finally:
        result["ended_at"] = time.time()
        result["duration_seconds"] = round(result["ended_at"] - result["started_at"], 3)
        result["host_crash_delta"] = crash_log_tail(HOST_CRASH_LOG, host_crash_start)
        result["client_crash_delta"] = crash_log_tail(CLIENT_CRASH_LOG, client_crash_start)
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        if not args.attach:
            stop_games()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kills-per-participant", type=int, default=30)
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--attach", action="store_true", help="Use already-running local multiplayer pair.")
    parser.add_argument(
        "--diagnostics",
        action="store_true",
        help="Capture per-kill forensic vector/runtime-context snapshots (slower, more bridge round-trips).",
    )
    parser.add_argument(
        "--require-natural-drop",
        action="store_true",
        help="Fail unless at least one real host-authored death-roll loot drop is observed and verified.",
    )
    parser.add_argument(
        "--resume-output",
        type=Path,
        help="Resume only the contiguous passed prefix in prior evidence (attach mode only).",
    )
    parser.add_argument("--output", type=Path, default=RUNTIME_OUTPUT)
    args = parser.parse_args()
    if args.kills_per_participant <= 0:
        raise SystemExit("--kills-per-participant must be positive")
    global DIAGNOSTICS_ENABLED
    DIAGNOSTICS_ENABLED = bool(args.diagnostics)
    try:
        result = run_verifier(args)
    except Exception as exc:
        print(f"multiplayer primary kill stress failed: {exc}")
        print(f"wrote {args.output}")
        return 1
    print(
        "multiplayer primary kill stress passed; "
        f"kills={len(result['kills'])} wrote {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
