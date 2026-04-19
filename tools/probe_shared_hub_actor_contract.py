#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "dist" / "launcher" / "SolomonDarkModLauncher.exe"
LUA_EXEC = ROOT / "tools" / "lua-exec.py"
ACTIVE_PRESET = ROOT / "mods" / "lua_ui_sandbox_lab" / "config" / "active_preset.txt"
DEFAULT_OUTPUT = ROOT / "runtime" / "shared_hub_actor_contract_probe.json"
LOG_DIR = ROOT / "runtime" / "stage" / ".sdmod" / "logs"
LOADER_LOG = LOG_DIR / "solomondarkmodloader.log"
CRASH_LOG = LOG_DIR / "solomondarkmodloader.crash.log"
BOT_NAME = "Lua Patrol Bot"
DEFAULT_PRESET = "map_create_fire_mind_hub"
STUDENT_TYPE = 0x138A
GAME_NPC_TYPE = 0x1397
VENDOR_TYPES = {
    0x1389: "witch",
    0x138B: "annalist",
    0x138C: "potion_guy",
    0x138D: "scavenger",
    0x138F: "enforcer",
    0x1390: "teacher",
}
KNOWN_TYPES = {
    0x1: "player_wizard",
    STUDENT_TYPE: "student",
    GAME_NPC_TYPE: "gamenpc",
    **VENDOR_TYPES,
}


class ProbeFailure(RuntimeError):
    pass


def run_command(args: list[str], *, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def stop_game() -> None:
    run_command(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "Get-Process SolomonDark,SolomonDarkModLauncher -ErrorAction SilentlyContinue | Stop-Process -Force",
        ]
    )


def launch_game() -> None:
    try:
        subprocess.Popen(
            [str(LAUNCHER), "launch"],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError as exc:
        raise ProbeFailure(f"launcher start failed: {exc}") from exc
    time.sleep(0.5)


def set_active_preset(preset: str) -> None:
    ACTIVE_PRESET.parent.mkdir(parents=True, exist_ok=True)
    ACTIVE_PRESET.write_text(preset, encoding="utf-8")


def run_lua(code: str, *, timeout: float = 20.0) -> str:
    deadline = time.time() + timeout
    last_error = ""
    while time.time() < deadline:
        result = run_command([sys.executable, str(LUA_EXEC), code], timeout=min(timeout, 10.0))
        output = (result.stdout or "") + (result.stderr or "")
        if result.returncode == 0:
            return output
        last_error = output.strip()
        if "Lua engine is busy" not in output and "Cannot connect to pipe" not in output:
            raise ProbeFailure(last_error or "lua-exec failed")
        time.sleep(0.2)
    raise ProbeFailure(last_error or "lua-exec timed out")


def parse_key_values(output: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def convert_value(raw: str) -> object:
    lowered = raw.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"nil", "none", ""}:
        return None
    if raw.startswith("0x") or raw.startswith("0X"):
        try:
            return int(raw, 16)
        except ValueError:
            return raw
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


def build_nested(values: dict[str, str]) -> dict[str, object]:
    root: dict[str, object] = {}
    for key, raw_value in values.items():
        parts = key.split(".")
        cursor = root
        for part in parts[:-1]:
            child = cursor.get(part)
            if not isinstance(child, dict):
                child = {}
                cursor[part] = child
            cursor = child
        cursor[parts[-1]] = convert_value(raw_value)
    return root


def wait_for_lua_pipe(*, timeout_s: float = 60.0) -> None:
    deadline = time.time() + timeout_s
    last_error = ""
    while time.time() < deadline:
        result = run_command([sys.executable, str(LUA_EXEC), "print('ready=true')"], timeout=10.0)
        output = (result.stdout or "") + (result.stderr or "")
        if result.returncode == 0 and "ready=true" in output:
            return
        last_error = output.strip()
        time.sleep(0.5)
    raise ProbeFailure(f"lua pipe not ready before timeout: {last_error}")


def is_game_running() -> bool:
    result = run_command(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "@(Get-Process SolomonDark -ErrorAction SilentlyContinue).Count",
        ],
        timeout=10.0,
    )
    if result.returncode != 0:
        return False
    try:
        return int((result.stdout or "").strip() or "0") > 0
    except ValueError:
        return False


def read_log_tail(path: Path, line_count: int) -> list[str]:
    if not path.exists():
        return []
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-line_count:]
    except OSError:
        return []


def wait_for_shared_hub(*, timeout_s: float = 120.0) -> dict[str, str]:
    deadline = time.time() + timeout_s
    last_values: dict[str, str] = {}
    code = """
local s=sd.world.get_scene()
if type(s)~='table' then
  print('available=false')
  return
end
print('available=true')
print('name='..tostring(s.name))
print('kind='..tostring(s.kind))
print('transitioning='..tostring(s.transitioning))
print('world='..tostring(s.world_id))
print('region_index='..tostring(s.region_index))
print('region_type_id='..tostring(s.region_type_id))
""".strip()
    while time.time() < deadline:
        last_values = parse_key_values(run_lua(code))
        if (
            last_values.get("available") == "true"
            and last_values.get("name") == "hub"
            and last_values.get("transitioning") == "false"
            and last_values.get("world") not in {"", "0", "0x0", "nil", None}
        ):
            return last_values
        time.sleep(0.25)
    raise ProbeFailure(f"shared hub not ready before timeout: {json.dumps(last_values, sort_keys=True)}")


def wait_for_bot_materialized(*, timeout_s: float = 30.0) -> dict[str, str]:
    deadline = time.time() + timeout_s
    last_values: dict[str, str] = {}
    code = f"""
local bots=sd.bots.get_state()
if type(bots)~='table' then
  print('available=false')
  return
end
for _, bot in ipairs(bots) do
  if type(bot)=='table' and tostring(bot.name)=={json.dumps(BOT_NAME)} then
    print('available='..tostring(bot.available))
    print('bot_id='..tostring(bot.id))
    print('actor='..tostring(bot.actor_address))
    print('world='..tostring(bot.world_address))
    print('entity_materialized='..tostring(bot.entity_materialized))
    print('participant_kind='..tostring(bot.participant_kind))
    print('controller_kind='..tostring(bot.controller_kind))
    print('scene_kind='..tostring(type(bot.scene)=='table' and bot.scene.kind or nil))
    return
  end
end
print('available=false')
""".strip()
    while time.time() < deadline:
        last_values = parse_key_values(run_lua(code))
        if (
            last_values.get("available") == "true"
            and last_values.get("entity_materialized") == "true"
            and last_values.get("actor") not in {"", "0", "0x0", "nil", None}
            and last_values.get("scene_kind") == "SharedHub"
        ):
            return last_values
        time.sleep(0.2)
    raise ProbeFailure(f"bot failed to materialize before timeout: {json.dumps(last_values, sort_keys=True)}")


def capture_probe() -> dict[str, object]:
    vendor_type_list = ",".join(f"0x{type_id:X}" for type_id in sorted(VENDOR_TYPES))
    code = f"""
local function emit(key, value)
  if value == nil then
    print(key .. '=nil')
  else
    print(key .. '=' .. tostring(value))
  end
end

local function read_u8(addr, off)
  if not addr or addr == 0 then return nil end
  return sd.debug.read_u8(addr + off)
end

local function read_u32(addr, off)
  if not addr or addr == 0 then return nil end
  return sd.debug.read_u32(addr + off)
end

local function read_f32(addr, off)
  if not addr or addr == 0 then return nil end
  return sd.debug.read_float(addr + off)
end

local function distance_sq(ax, ay, bx, by)
  if not ax or not ay or not bx or not by then return math.huge end
  local dx = ax - bx
  local dy = ay - by
  return dx * dx + dy * dy
end

local scene = sd.world.get_scene()
local player = sd.player.get_state()
local bots = sd.bots.get_state()
local actors = sd.world.list_actors()

emit('scene.available', type(scene) == 'table')
if type(scene) == 'table' then
  emit('scene.name', scene.name)
  emit('scene.kind', scene.kind)
  emit('scene.transitioning', scene.transitioning)
  emit('scene.world_id', scene.world_id)
  emit('scene.region_index', scene.region_index)
  emit('scene.region_type_id', scene.region_type_id)
end

emit('player.available', type(player) == 'table')
if type(player) == 'table' then
  emit('player.actor_address', player.actor_address)
  emit('player.world_address', player.world_address)
  emit('player.progression_handle_address', player.progression_handle_address)
  emit('player.equip_handle_address', player.equip_handle_address)
  emit('player.animation_state_ptr', player.animation_state_ptr)
  emit('player.actor_slot', player.actor_slot)
  emit('player.x', player.x)
  emit('player.y', player.y)
end

local bot = nil
if type(bots) == 'table' then
  for _, candidate in ipairs(bots) do
    if type(candidate) == 'table' and tostring(candidate.name) == {json.dumps(BOT_NAME)} then
      bot = candidate
      break
    end
  end
end

emit('bot_snapshot.available', type(bot) == 'table')
if type(bot) == 'table' then
  emit('bot_snapshot.id', bot.id)
  emit('bot_snapshot.actor_address', bot.actor_address)
  emit('bot_snapshot.world_address', bot.world_address)
  emit('bot_snapshot.entity_materialized', bot.entity_materialized)
  emit('bot_snapshot.gameplay_slot', bot.gameplay_slot)
  emit('bot_snapshot.actor_slot', bot.actor_slot)
  emit('bot_snapshot.participant_kind', bot.participant_kind)
  emit('bot_snapshot.controller_kind', bot.controller_kind)
  emit('bot_snapshot.scene_kind', type(bot.scene) == 'table' and bot.scene.kind or nil)
  emit('bot_snapshot.hub_visual_source_kind', bot.hub_visual_source_kind)
  emit('bot_snapshot.hub_visual_source_profile_address', bot.hub_visual_source_profile_address)
  emit('bot_snapshot.hub_visual_attachment_ptr', bot.hub_visual_attachment_ptr)
  emit('bot_snapshot.progression_runtime_state_address', bot.progression_runtime_state_address)
  emit('bot_snapshot.equip_runtime_state_address', bot.equip_runtime_state_address)
  emit('bot_snapshot.progression_handle_address', bot.progression_handle_address)
  emit('bot_snapshot.equip_handle_address', bot.equip_handle_address)
  emit('bot_snapshot.animation_state_ptr', bot.animation_state_ptr)
  emit('bot_snapshot.resolved_animation_state_id', bot.resolved_animation_state_id)
  emit('bot_snapshot.render_variant_primary', bot.render_variant_primary)
  emit('bot_snapshot.render_variant_secondary', bot.render_variant_secondary)
  emit('bot_snapshot.render_weapon_type', bot.render_weapon_type)
  emit('bot_snapshot.render_variant_tertiary', bot.render_variant_tertiary)
  emit('bot_snapshot.render_selection_byte', bot.render_selection_byte)
  emit('bot_snapshot.x', bot.x)
  emit('bot_snapshot.y', bot.y)
  emit('bot_snapshot.heading', bot.heading)
end

local actor_count = 0
local counts = {{}}
local player_actor = nil
local bot_actor = nil
local student_actor = nil
local vendor_actor = nil
local vendor_label = nil
local vendor_types = {{ {vendor_type_list} }}
local player_addr = type(player) == 'table' and tonumber(player.actor_address) or 0
local bot_addr = type(bot) == 'table' and tonumber(bot.actor_address) or 0
local anchor_x = type(player) == 'table' and tonumber(player.x) or nil
local anchor_y = type(player) == 'table' and tonumber(player.y) or nil
local best_student_dist = math.huge
local best_vendor_dist = math.huge

if type(actors) == 'table' then
  actor_count = #actors
  for _, actor in ipairs(actors) do
    local type_id = tonumber(actor.object_type_id) or 0
    counts[type_id] = (counts[type_id] or 0) + 1
    local actor_addr = tonumber(actor.actor_address) or 0
    if player_addr ~= 0 and actor_addr == player_addr then
      player_actor = actor
    end
    if bot_addr ~= 0 and actor_addr == bot_addr then
      bot_actor = actor
    end
    if type_id == {STUDENT_TYPE} then
      local dist = distance_sq(anchor_x, anchor_y, tonumber(actor.x), tonumber(actor.y))
      if dist < best_student_dist then
        best_student_dist = dist
        student_actor = actor
      end
    end
    for _, vendor_type in ipairs(vendor_types) do
      if type_id == vendor_type then
        local dist = distance_sq(anchor_x, anchor_y, tonumber(actor.x), tonumber(actor.y))
        if dist < best_vendor_dist then
          best_vendor_dist = dist
          vendor_actor = actor
          vendor_label = string.format('0x%X', vendor_type)
        end
      end
    end
  end
end

emit('actors.total', actor_count)
for type_id, count in pairs(counts) do
  emit(string.format('actors.counts.0x%X', type_id), count)
end
emit('actors.student_distance_sq', best_student_dist ~= math.huge and best_student_dist or nil)
emit('actors.vendor_distance_sq', best_vendor_dist ~= math.huge and best_vendor_dist or nil)
emit('actors.vendor_type', vendor_label)

local function dump_actor(prefix, actor)
  emit(prefix .. '.available', type(actor) == 'table')
  if type(actor) ~= 'table' then
    return
  end

  local actor_addr = tonumber(actor.actor_address) or 0
  local packed_slot_word = read_u32(actor_addr, 0x5C)
  emit(prefix .. '.actor_address', actor.actor_address)
  emit(prefix .. '.vtable_address', actor.vtable_address)
  emit(prefix .. '.first_method_address', actor.first_method_address)
  emit(prefix .. '.object_type_id', actor.object_type_id)
  emit(prefix .. '.object_header_word', actor.object_header_word)
  emit(prefix .. '.owner_address', actor.owner_address)
  emit(prefix .. '.actor_slot', actor.actor_slot)
  emit(prefix .. '.world_slot', actor.world_slot)
  emit(prefix .. '.x', actor.x)
  emit(prefix .. '.y', actor.y)
  emit(prefix .. '.anim_drive_state', actor.anim_drive_state)
  emit(prefix .. '.progression_handle_address', actor.progression_handle_address)
  emit(prefix .. '.equip_handle_address', actor.equip_handle_address)
  emit(prefix .. '.animation_state_ptr', actor.animation_state_ptr)
  emit(prefix .. '.raw.radius', read_f32(actor_addr, 0x30))
  emit(prefix .. '.raw.mask', read_u32(actor_addr, 0x38))
  emit(prefix .. '.raw.mask2', read_u32(actor_addr, 0x3C))
  emit(prefix .. '.raw.cell', read_u32(actor_addr, 0x54))
  emit(prefix .. '.raw.owner_field', read_u32(actor_addr, 0x58))
  emit(prefix .. '.raw.slot_byte', read_u8(actor_addr, 0x5C))
  emit(prefix .. '.raw.packed_slot_word', packed_slot_word)
  emit(
    prefix .. '.raw.world_slot_derived',
    packed_slot_word ~= nil and (math.floor(packed_slot_word / 65536) % 65536) or nil
  )
  emit(prefix .. '.raw.source_kind', read_u32(actor_addr, 0x174))
  emit(prefix .. '.raw.source_profile', read_u32(actor_addr, 0x178))
  emit(prefix .. '.raw.source_aux', read_u32(actor_addr, 0x17C))
  emit(prefix .. '.raw.source_profile_74_mirror', read_u32(actor_addr, 0x194))
  emit(prefix .. '.raw.source_profile_56_mirror', read_u32(actor_addr, 0x1C0))
  emit(prefix .. '.raw.attachment_ptr', read_u32(actor_addr, 0x264))

  if (tonumber(actor.object_type_id) or 0) == {GAME_NPC_TYPE} then
    emit(prefix .. '.gamenpc.mode', read_u32(actor_addr, 0x174))
    emit(prefix .. '.gamenpc.record_id', read_u32(actor_addr, 0x17C))
    emit(prefix .. '.gamenpc.active', read_u8(actor_addr, 0x180))
    emit(prefix .. '.gamenpc.branch', read_u8(actor_addr, 0x181))
    emit(prefix .. '.gamenpc.desired_yaw', read_f32(actor_addr, 0x188))
    emit(prefix .. '.gamenpc.tick_counter', read_u32(actor_addr, 0x18C))
    emit(prefix .. '.gamenpc.move_flag', read_u8(actor_addr, 0x198))
    emit(prefix .. '.gamenpc.goal_x', read_f32(actor_addr, 0x19C))
    emit(prefix .. '.gamenpc.goal_y', read_f32(actor_addr, 0x1A0))
    emit(prefix .. '.gamenpc.move_speed', read_f32(actor_addr, 0x1B4))
    emit(prefix .. '.gamenpc.tracked_mode', read_u32(actor_addr, 0x1C0))
    emit(prefix .. '.gamenpc.tracked_slot', read_u8(actor_addr, 0x1C2))
    emit(prefix .. '.gamenpc.callback', read_u8(actor_addr, 0x1C3))
    emit(prefix .. '.gamenpc.late_timer', read_u32(actor_addr, 0x1C4))
  end
end

dump_actor('samples.player_actor', player_actor)
dump_actor('samples.bot_actor', bot_actor)
dump_actor('samples.student_actor', student_actor)
dump_actor('samples.vendor_actor', vendor_actor)

local world_addr =
  (type(bot) == 'table' and tonumber(bot.world_address)) or
  (type(player) == 'table' and tonumber(player.world_address)) or
  0
local movement_ctx = world_addr ~= 0 and (world_addr + 0x378) or 0
emit('movement.available', movement_ctx ~= 0)
emit('movement.world_address', world_addr)
emit('movement.ctx', movement_ctx)
emit('movement.primary_count', read_u32(movement_ctx, 0x40))
emit('movement.primary_list', read_u32(movement_ctx, 0x4C))
local primary_list = read_u32(movement_ctx, 0x4C) or 0
emit('movement.primary0', read_u32(primary_list, 0x0))
emit('movement.primary1', read_u32(primary_list, 0x4))
emit('movement.secondary_count', read_u32(movement_ctx, 0x70))
emit('movement.secondary_list', read_u32(movement_ctx, 0x7C))
local secondary_list = read_u32(movement_ctx, 0x7C) or 0
emit('movement.secondary0', read_u32(secondary_list, 0x0))
emit('movement.secondary1', read_u32(secondary_list, 0x4))
""".strip()
    return build_nested(parse_key_values(run_lua(code, timeout=30.0)))


def sample_watch_state() -> dict[str, object]:
    code = f"""
local function emit(key, value)
  if value == nil then
    print(key .. '=nil')
  else
    print(key .. '=' .. tostring(value))
  end
end

local bots = sd.bots.get_state()
local bot = nil
if type(bots) == 'table' then
  for _, candidate in ipairs(bots) do
    if type(candidate) == 'table' and tostring(candidate.name) == {json.dumps(BOT_NAME)} then
      bot = candidate
      break
    end
  end
end

emit('bot.available', type(bot) == 'table')
if type(bot) ~= 'table' then
  return
end

local actor = tonumber(bot.actor_address) or 0
emit('bot.id', bot.id)
emit('bot.actor_address', bot.actor_address)
emit('bot.world_snapshot', bot.world_address)
emit('bot.materialized', bot.entity_materialized)
emit('bot.source_kind', bot.hub_visual_source_kind)
emit('bot.source_profile', bot.hub_visual_source_profile_address)
emit('bot.attachment', bot.hub_visual_attachment_ptr)
emit('bot.x', bot.x)
emit('bot.y', bot.y)
emit('bot.heading', bot.heading)
emit('bot.moving', bot.moving)
emit('bot.target_x', bot.target_x)
emit('bot.target_y', bot.target_y)

if actor == 0 then
  return
end

local function read_u8(address)
  if not address or address == 0 then return nil end
  return sd.debug.read_u8(address)
end

local function read_u32(address)
  if not address or address == 0 then return nil end
  return sd.debug.read_u32(address)
end

local function read_f32(address)
  if not address or address == 0 then return nil end
  return sd.debug.read_float(address)
end

emit('actor.owner_field', read_u32(actor + 0x58))
emit('actor.cell', read_u32(actor + 0x54))
emit('actor.mask', read_u32(actor + 0x38))
emit('actor.mask2', read_u32(actor + 0x3C))
emit('actor.slot_word', read_u32(actor + 0x5C))
emit('actor.radius', read_f32(actor + 0x30))
emit('actor.source_kind_field', read_u32(actor + 0x174))
emit('actor.source_profile_field', read_u32(actor + 0x178))
emit('actor.source_aux_field', read_u32(actor + 0x17C))
emit('actor.source_profile_74_mirror', read_u32(actor + 0x194))
emit('actor.source_profile_56_mirror', read_u32(actor + 0x1C0))
emit('actor.attachment_field', read_u32(actor + 0x264))
emit('gamenpc.source_kind', read_u32(actor + 0x174))
emit('gamenpc.active', read_u8(actor + 0x180))
emit('gamenpc.branch', read_u8(actor + 0x181))
emit('gamenpc.desired_yaw', read_f32(actor + 0x188))
emit('gamenpc.move_flag', read_u8(actor + 0x198))
emit('gamenpc.goal_x', read_f32(actor + 0x19C))
emit('gamenpc.goal_y', read_f32(actor + 0x1A0))
emit('gamenpc.move_speed', read_f32(actor + 0x1B4))

local listed = false
for _, scene_actor in ipairs(sd.world.list_actors() or {{}}) do
  if tonumber(scene_actor.actor_address) == actor then
    listed = true
    emit('listed.world_slot', scene_actor.world_slot)
    emit('listed.type', scene_actor.object_type_id)
    break
  end
end
emit('listed.available', listed)

local world = tonumber(bot.world_address) or read_u32(actor + 0x58) or 0
emit('movement.world', world)
if world == 0 then
  return
end

local ctx = world + 0x378
local primary_list = read_u32(ctx + 0x4C) or 0
local secondary_list = read_u32(ctx + 0x7C) or 0
emit('movement.ctx', ctx)
emit('movement.primary_count', read_u32(ctx + 0x40))
emit('movement.primary_list', primary_list)
emit('movement.primary0', read_u32(primary_list + 0x0))
emit('movement.primary1', read_u32(primary_list + 0x4))
local primary0 = read_u32(primary_list + 0x0) or 0
local primary1 = read_u32(primary_list + 0x4) or 0
emit('movement.primary0_deref_0c', read_u32(primary0 + 0x0C))
emit('movement.primary0_deref_10', read_u32(primary0 + 0x10))
emit('movement.primary0_deref_14', read_u32(primary0 + 0x14))
emit('movement.primary1_deref_0c', read_u32(primary1 + 0x0C))
emit('movement.primary1_deref_10', read_u32(primary1 + 0x10))
emit('movement.primary1_deref_14', read_u32(primary1 + 0x14))
emit('movement.secondary_count', read_u32(ctx + 0x70))
emit('movement.secondary_list', secondary_list)
emit('movement.secondary0', read_u32(secondary_list + 0x0))
emit('movement.secondary1', read_u32(secondary_list + 0x4))
local secondary0 = read_u32(secondary_list + 0x0) or 0
local secondary1 = read_u32(secondary_list + 0x4) or 0
emit('movement.secondary0_deref_0c', read_u32(secondary0 + 0x0C))
emit('movement.secondary0_deref_10', read_u32(secondary0 + 0x10))
emit('movement.secondary0_deref_14', read_u32(secondary0 + 0x14))
emit('movement.secondary1_deref_0c', read_u32(secondary1 + 0x0C))
emit('movement.secondary1_deref_10', read_u32(secondary1 + 0x10))
emit('movement.secondary1_deref_14', read_u32(secondary1 + 0x14))
for _, callback_offset in ipairs({{0x38, 0x50, 0x68}}) do
  local callback_ptr = read_u32(ctx + callback_offset) or 0
  local callback_key = string.format('movement.callback_%02X', callback_offset)
  emit(callback_key, callback_ptr)
  if callback_ptr ~= 0 then
    for i = 0, 5 do
      emit(string.format('%s_%d', callback_key, i), read_u32(callback_ptr + i * 4))
    end
  end
end
""".strip()
    return build_nested(parse_key_values(run_lua(code, timeout=10.0)))


def annotate_probe(probe: dict[str, object]) -> None:
    counts = probe.get("actors", {}).get("counts") if isinstance(probe.get("actors"), dict) else None
    if isinstance(counts, dict):
        for type_key, count in list(counts.items()):
            if not isinstance(type_key, str):
                continue
            try:
                type_id = int(type_key, 16)
            except ValueError:
                continue
            counts[type_key] = {
                "count": count,
                "label": KNOWN_TYPES.get(type_id, "unknown"),
            }

    samples = probe.get("samples")
    if not isinstance(samples, dict):
        return
    for sample in samples.values():
        if not isinstance(sample, dict):
            continue
        type_id = sample.get("object_type_id")
        if isinstance(type_id, int):
            sample["object_type_label"] = KNOWN_TYPES.get(type_id, "unknown")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--launch", action="store_true", help="Stop existing game processes and launch a fresh staged session.")
    parser.add_argument("--preset", default=DEFAULT_PRESET, help="UI sandbox preset to activate before launch.")
    parser.add_argument("--settle-ms", type=int, default=750, help="Extra settle delay after bot materialization before sampling.")
    parser.add_argument("--watch-seconds", type=float, default=0.0, help="Optional post-capture watch duration.")
    parser.add_argument("--interval-ms", type=int, default=500, help="Sampling interval during watch mode.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Path to write the captured JSON payload.")
    args = parser.parse_args()

    try:
        set_active_preset(args.preset)
        if args.launch:
            stop_game()
            launch_game()
        wait_for_lua_pipe()
        wait_for_shared_hub()
        wait_for_bot_materialized()
        time.sleep(max(args.settle_ms, 0) / 1000.0)
        probe = capture_probe()
        annotate_probe(probe)
        if args.watch_seconds > 0:
            watch = {
                "duration_seconds": args.watch_seconds,
                "interval_ms": args.interval_ms,
                "samples": [],
            }
            deadline = time.time() + max(args.watch_seconds, 0.0)
            while time.time() < deadline:
                if not is_game_running():
                    watch["game_running"] = False
                    break
                sample = sample_watch_state()
                sample["host_time"] = time.time()
                watch["samples"].append(sample)
                time.sleep(max(args.interval_ms, 0) / 1000.0)
            else:
                watch["game_running"] = is_game_running()
            watch["loader_log_tail"] = read_log_tail(LOADER_LOG, 80)
            watch["crash_log_tail"] = read_log_tail(CRASH_LOG, 120)
            probe["watch"] = watch
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(probe, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(probe, indent=2, sort_keys=True))
        return 0
    except ProbeFailure as exc:
        print(f"probe_failed={exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
