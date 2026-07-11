#!/usr/bin/env python3
"""Verify host-authoritative enemy target state reaches clients."""

from __future__ import annotations

import argparse
import json
import time
from typing import Any

from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_PIPE,
    HOST_ID,
    HOST_PIPE,
    ROOT,
    VerifyFailure,
    disable_bots,
    launch_pair,
    lua,
    parse_key_values,
    place_player,
    start_host_testrun_and_wait_for_clients,
    stop_games,
)
from verify_run_world_snapshot import start_host_waves, wait_for_run_snapshot


RUNTIME_OUTPUT = ROOT / "runtime" / "run_enemy_target_authority.json"


CAPTURE_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local function num(value, default)
  local n = tonumber(value)
  if n == nil or n ~= n or n == math.huge or n == -math.huge then return default or 0 end
  return n
end
local function hx(v) return string.format("0x%08X", tonumber(v) or 0) end
local function read_u32(address)
  if address == nil or address == 0 then return 0 end
  return tonumber(sd.debug.read_u32(address)) or 0
end
local function read_i32(address)
  local v = read_u32(address)
  if v >= 0x80000000 then return v - 0x100000000 end
  return v
end
local function read_i16(address)
  local v = tonumber(sd.debug.read_u16(address)) or 0
  if v >= 0x8000 then return v - 0x10000 end
  return v
end
local function read_i8(address)
  local v = tonumber(sd.debug.read_u8(address)) or 0
  if v >= 0x80 then return v - 0x100 end
  return v
end

local local_participant_id = __LOCAL_PARTICIPANT_ID__
local participant_by_actor = {}
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
if player and tonumber(player.actor_address) and local_participant_id ~= 0 then
  participant_by_actor[tonumber(player.actor_address)] = local_participant_id
end
local peers = sd.bots and sd.bots.get_participants and sd.bots.get_participants() or {}
for _, peer in ipairs(peers) do
  local actor_address = tonumber(peer.actor_address) or 0
  local participant_id = peer.id or 0
  if actor_address ~= 0 and participant_id ~= 0 and participant_by_actor[actor_address] == nil then
    participant_by_actor[actor_address] = participant_id
  end
end

	local current_target_offset = sd.debug.layout_offset("actor_current_target_actor")
	local type_id_offset = sd.debug.layout_offset("game_object_type_id")
	local bucket_delta_offset = sd.debug.layout_offset("actor_current_target_bucket_delta")
local actor_slot_offset = sd.debug.layout_offset("actor_slot")
local world_slot_offset = sd.debug.layout_offset("actor_world_slot")
local selection_state_offset = sd.debug.layout_offset("actor_animation_selection_state")
local brain_state_offset = sd.debug.layout_offset("actor_control_brain_state_id")
local brain_target_slot_offset = sd.debug.layout_offset("actor_control_brain_target_slot")
local brain_target_handle_offset = sd.debug.layout_offset("actor_control_brain_target_handle")
local brain_action_cooldown_offset = sd.debug.layout_offset("actor_control_brain_action_cooldown_ticks")
local brain_action_burst_offset = sd.debug.layout_offset("actor_control_brain_action_burst_ticks")
local brain_heading_lock_offset = sd.debug.layout_offset("actor_control_brain_heading_lock_ticks")
local brain_move_x_offset = sd.debug.layout_offset("actor_control_brain_move_input_x")
local brain_move_y_offset = sd.debug.layout_offset("actor_control_brain_move_input_y")
local drive_offset = sd.debug.layout_offset("actor_animation_drive_state_byte")

local replicated = sd.world and sd.world.get_replicated_actors and sd.world.get_replicated_actors() or nil
local network_by_local = {}
local network_by_slot_key = {}
	local replicated_target_by_network = {}
	local replicated_target_native_type_by_network = {}
	local replicated_target_actor_slot_by_network = {}
	local replicated_target_world_slot_by_network = {}
	local replicated_target_bucket_delta_by_network = {}
	local replicated_target_authoritative_by_network = {}
local function actor_key(type_id, actor_slot, world_slot)
  return tostring(type_id or 0) .. ":" .. tostring(actor_slot or -1) .. ":" .. tostring(world_slot or -1)
end
if replicated and replicated.bindings then
  for _, binding in ipairs(replicated.bindings) do
    local local_address = tonumber(binding.local_actor_address) or 0
    local network_id = binding.network_actor_id or 0
    if local_address ~= 0 and network_id ~= 0 and binding.matched and not binding.parked then
      network_by_local[local_address] = network_id
    end
  end
end
if replicated and replicated.actors then
  for _, actor in ipairs(replicated.actors) do
    local network_id = actor.network_actor_id or 0
    if network_id ~= 0 then
      network_by_slot_key[actor_key(
        tonumber(actor.object_type_id) or 0,
        tonumber(actor.actor_slot) or -1,
        tonumber(actor.world_slot) or -1)] = network_id
	      replicated_target_by_network[network_id] = actor.target_participant_id or 0
	      replicated_target_native_type_by_network[network_id] = actor.target_native_type_id or 0
	      replicated_target_actor_slot_by_network[network_id] = actor.target_actor_slot or -1
	      replicated_target_world_slot_by_network[network_id] = actor.target_world_slot or -1
	      replicated_target_bucket_delta_by_network[network_id] = actor.target_bucket_delta or 0
	      replicated_target_authoritative_by_network[network_id] = actor.target_authoritative and 1 or 0
    end
  end
end

local scene = sd.world and sd.world.get_scene and sd.world.get_scene() or nil
emit("scene", scene and (scene.name or scene.kind) or "")
emit("local_participant_id", tostring(local_participant_id))
emit("replicated_valid", replicated ~= nil)
emit("replicated_actor_count", replicated and replicated.actor_count or 0)
emit("replicated_binding_count", replicated and replicated.binding_count or 0)

local actors = sd.world and sd.world.list_actors and sd.world.list_actors() or {}
local count = 0
for _, actor in ipairs(actors) do
  local address = tonumber(actor.actor_address) or 0
  local type_id = tonumber(actor.object_type_id) or 0
  local hp = num(actor.hp, 0)
  local max_hp = num(actor.max_hp, 0)
  local parked = num(actor.x, 0) >= 50000.0 and num(actor.y, 0) >= 50000.0
  if address ~= 0 and actor.tracked_enemy and not actor.dead and not parked and type_id ~= 0 and type_id ~= 1 and max_hp > 0 and hp > 0.05 then
    local actor_slot = actor_slot_offset and read_i8(address + actor_slot_offset) or -1
    local world_slot = world_slot_offset and read_i16(address + world_slot_offset) or -1
    local network_id = network_by_local[address] or network_by_slot_key[actor_key(type_id, actor_slot, world_slot)] or 0
    if network_id ~= 0 then
      count = count + 1
      local prefix = "enemy." .. tostring(count) .. "."
	      local target_actor = current_target_offset and read_u32(address + current_target_offset) or 0
	      local target_participant_id = participant_by_actor[target_actor] or 0
	      local target_native_type_id = type_id_offset and target_actor ~= 0 and read_u32(target_actor + type_id_offset) or 0
	      local target_actor_slot = actor_slot_offset and target_actor ~= 0 and read_i8(target_actor + actor_slot_offset) or -1
	      local target_world_slot = world_slot_offset and target_actor ~= 0 and read_i16(target_actor + world_slot_offset) or -1
	      local selection_state = selection_state_offset and read_u32(address + selection_state_offset) or 0
      emit(prefix .. "network_id", tostring(network_id))
      emit(prefix .. "actor", hx(address))
      emit(prefix .. "type", type_id)
      emit(prefix .. "enemy_type", actor.enemy_type or -1)
      emit(prefix .. "x", string.format("%.3f", num(actor.x, 0)))
      emit(prefix .. "y", string.format("%.3f", num(actor.y, 0)))
      emit(prefix .. "hp", string.format("%.3f", hp))
	      emit(prefix .. "target_actor", hx(target_actor))
	      emit(prefix .. "target_participant_id", tostring(target_participant_id))
	      emit(prefix .. "target_native_type_id", tostring(target_native_type_id))
	      emit(prefix .. "target_actor_slot", tostring(target_actor_slot))
	      emit(prefix .. "target_world_slot", tostring(target_world_slot))
	      emit(prefix .. "replicated_target_participant_id", tostring(replicated_target_by_network[network_id] or 0))
	      emit(prefix .. "replicated_target_native_type_id", tostring(replicated_target_native_type_by_network[network_id] or 0))
	      emit(prefix .. "replicated_target_actor_slot", tostring(replicated_target_actor_slot_by_network[network_id] or -1))
	      emit(prefix .. "replicated_target_world_slot", tostring(replicated_target_world_slot_by_network[network_id] or -1))
	      emit(prefix .. "replicated_target_bucket_delta", tostring(replicated_target_bucket_delta_by_network[network_id] or 0))
	      emit(prefix .. "replicated_target_authoritative", replicated_target_authoritative_by_network[network_id] or 0)
      emit(prefix .. "bucket_delta", bucket_delta_offset and read_i32(address + bucket_delta_offset) or 0)
      emit(prefix .. "actor_slot", actor_slot)
      emit(prefix .. "world_slot", world_slot)
      emit(prefix .. "drive_byte", drive_offset and (tonumber(sd.debug.read_u8(address + drive_offset)) or 0) or 0)
      emit(prefix .. "brain", hx(selection_state))
      if selection_state ~= 0 then
        emit(prefix .. "brain_state", brain_state_offset and read_i32(selection_state + brain_state_offset) or 0)
        emit(prefix .. "brain_target_slot", brain_target_slot_offset and read_i8(selection_state + brain_target_slot_offset) or -1)
        emit(prefix .. "brain_target_handle", brain_target_handle_offset and read_i16(selection_state + brain_target_handle_offset) or -1)
        emit(prefix .. "brain_action_cooldown", brain_action_cooldown_offset and read_i32(selection_state + brain_action_cooldown_offset) or 0)
        emit(prefix .. "brain_action_burst", brain_action_burst_offset and read_i32(selection_state + brain_action_burst_offset) or 0)
        emit(prefix .. "brain_heading_lock", brain_heading_lock_offset and read_i32(selection_state + brain_heading_lock_offset) or 0)
        emit(prefix .. "brain_move_x", brain_move_x_offset and string.format("%.3f", tonumber(sd.debug.read_float(selection_state + brain_move_x_offset)) or 0) or "0.000")
        emit(prefix .. "brain_move_y", brain_move_y_offset and string.format("%.3f", tonumber(sd.debug.read_float(selection_state + brain_move_y_offset)) or 0) or "0.000")
      end
    end
  end
end
emit("enemy.count", count)
"""


ARRANGE_HOST_ENEMIES_LUA = r"""
local anchor_x = 1850.0
local anchor_y = 1750.0
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local function finite(v) return type(v) == "number" and v == v and v ~= math.huge and v ~= -math.huge end
local ox = sd.debug.layout_offset("actor_position_x")
local oy = sd.debug.layout_offset("actor_position_y")
local oh = sd.debug.layout_offset("actor_heading")
local ohp = sd.debug.layout_offset("enemy_current_hp")
local omaxhp = sd.debug.layout_offset("enemy_max_hp")
local actors = sd.world and sd.world.list_actors and sd.world.list_actors() or {}
local selected = 0
local parked = 0
for _, actor in ipairs(actors) do
  local address = tonumber(actor.actor_address) or 0
  local hp = tonumber(actor.hp) or 0
  local max_hp = tonumber(actor.max_hp) or 0
  if address ~= 0 and actor.tracked_enemy and not actor.dead and max_hp > 0 and hp > 0 and finite(tonumber(actor.x)) and finite(tonumber(actor.y)) then
    selected = selected + 1
    if selected <= 4 then
      local x = anchor_x + 128.0 + ((selected - 1) * 44.0)
      local y = anchor_y + ((selected % 2 == 0) and 44.0 or -44.0)
      local wrote = sd.debug.write_float(address + ox, x)
      wrote = sd.debug.write_float(address + oy, y) and wrote
      if oh ~= nil then sd.debug.write_float(address + oh, 180.0) end
      if ohp ~= nil and omaxhp ~= nil then
        sd.debug.write_float(address + omaxhp, math.max(max_hp, 10.0))
        sd.debug.write_float(address + ohp, math.max(hp, 10.0))
      end
      if sd.world and sd.world.rebind_actor then sd.world.rebind_actor(address) end
      emit("enemy." .. tostring(selected) .. ".actor", string.format("0x%08X", address))
      emit("enemy." .. tostring(selected) .. ".x", string.format("%.3f", x))
      emit("enemy." .. tostring(selected) .. ".y", string.format("%.3f", y))
    else
      local x = anchor_x + 4200.0 + (selected * 37.0)
      local y = anchor_y + 4200.0 + (selected * 29.0)
      if sd.debug.write_float(address + ox, x) and sd.debug.write_float(address + oy, y) then
        parked = parked + 1
        if sd.world and sd.world.rebind_actor then sd.world.rebind_actor(address) end
      end
    end
  end
end
emit("selected", math.min(selected, 4))
emit("parked", parked)
"""


def values(pipe_name: str, code: str, timeout: float = 8.0) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, code, timeout=timeout))


def parse_int(value: str | None, default: int = 0) -> int:
    if value is None:
        return default
    try:
        if value.startswith(("0x", "0X")):
            return int(value, 16)
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default


def enemy_rows(row: dict[str, str]) -> dict[int, dict[str, str]]:
    rows: dict[int, dict[str, str]] = {}
    for index in range(1, parse_int(row.get("enemy.count")) + 1):
        prefix = f"enemy.{index}."
        network_id = parse_int(row.get(prefix + "network_id"))
        if network_id == 0:
            continue
        rows[network_id] = {
            key[len(prefix):]: value
            for key, value in row.items()
            if key.startswith(prefix)
        }
    return rows


def capture_lua(local_participant_id: int) -> str:
    return CAPTURE_LUA.replace("__LOCAL_PARTICIPANT_ID__", str(local_participant_id))


def capture_pair(elapsed: float) -> dict[str, Any]:
    host = values(HOST_PIPE, capture_lua(HOST_ID))
    client = values(CLIENT_PIPE, capture_lua(CLIENT_ID))
    host_rows = enemy_rows(host)
    client_rows = enemy_rows(client)
    compared = 0
    host_targeted = 0
    client_replicated_targeted = 0
    target_mismatches = []
    unauthorized_target_mismatches = []
    replicated_lag_mismatches = []
    for network_id, host_enemy in host_rows.items():
        client_enemy = client_rows.get(network_id)
        if client_enemy is None:
            continue
        compared += 1
        host_target = parse_int(host_enemy.get("replicated_target_participant_id"))
        host_native_type = parse_int(host_enemy.get("replicated_target_native_type_id"))
        if host_target == 0 and host_native_type == 0:
            host_target = parse_int(host_enemy.get("target_participant_id"))
            host_native_type = parse_int(host_enemy.get("target_native_type_id"))
        client_expected_target = parse_int(client_enemy.get("replicated_target_participant_id"))
        client_expected_native_type = parse_int(client_enemy.get("replicated_target_native_type_id"))
        client_expected_actor_slot = parse_int(client_enemy.get("replicated_target_actor_slot"), -1)
        client_expected_world_slot = parse_int(client_enemy.get("replicated_target_world_slot"), -1)
        client_expected_bucket_delta = parse_int(client_enemy.get("replicated_target_bucket_delta"))
        client_target = parse_int(client_enemy.get("target_participant_id"))
        client_target_actor = parse_int(client_enemy.get("target_actor"))
        client_target_native_type = parse_int(client_enemy.get("target_native_type_id"))
        client_target_actor_slot = parse_int(client_enemy.get("target_actor_slot"), -1)
        client_target_world_slot = parse_int(client_enemy.get("target_world_slot"), -1)
        client_bucket_delta = parse_int(client_enemy.get("bucket_delta"))
        if host_target != 0 or host_native_type != 0:
            host_targeted += 1
        if client_expected_target != 0 or client_expected_native_type != 0:
            client_replicated_targeted += 1
        if host_target != client_expected_target or host_native_type != client_expected_native_type:
            replicated_lag_mismatches.append({
                "network_id": network_id,
                "host_replicated_target": host_target,
                "client_replicated_target": client_expected_target,
                "host_replicated_native_type": host_native_type,
                "client_replicated_native_type": client_expected_native_type,
            })
        if client_expected_target != 0 and client_target != client_expected_target:
            target_mismatches.append({
                "network_id": network_id,
                "expected_target": client_expected_target,
                "client_target": client_target,
                "host_actor": host_enemy.get("actor"),
                "client_actor": client_enemy.get("actor"),
                "host_bucket_delta": parse_int(host_enemy.get("bucket_delta")),
                "client_bucket_delta": client_bucket_delta,
                "host_brain_action_burst": parse_int(host_enemy.get("brain_action_burst")),
                "client_brain_action_burst": parse_int(client_enemy.get("brain_action_burst")),
            })
        if (
            client_expected_target == 0
            and client_expected_native_type != 0
            and (
                client_target_native_type != client_expected_native_type
                or client_target_actor_slot != client_expected_actor_slot
                or client_target_world_slot != client_expected_world_slot
                or client_bucket_delta != client_expected_bucket_delta
            )
        ):
            target_mismatches.append({
                "network_id": network_id,
                "expected_native_type": client_expected_native_type,
                "expected_actor_slot": client_expected_actor_slot,
                "expected_world_slot": client_expected_world_slot,
                "expected_bucket_delta": client_expected_bucket_delta,
                "client_target_native_type": client_target_native_type,
                "client_target_actor_slot": client_target_actor_slot,
                "client_target_world_slot": client_target_world_slot,
                "client_target_actor": client_enemy.get("target_actor"),
                "host_actor": host_enemy.get("actor"),
                "client_actor": client_enemy.get("actor"),
                "host_bucket_delta": parse_int(host_enemy.get("bucket_delta")),
                "client_bucket_delta": client_bucket_delta,
                "host_brain_action_burst": parse_int(host_enemy.get("brain_action_burst")),
                "client_brain_action_burst": parse_int(client_enemy.get("brain_action_burst")),
            })
        if client_expected_target == 0 and client_expected_native_type == 0 and client_target_actor != 0:
            unauthorized_target_mismatches.append({
                "network_id": network_id,
                "client_target": client_target,
                "host_actor": host_enemy.get("actor"),
                "client_actor": client_enemy.get("actor"),
                "client_target_actor": client_enemy.get("target_actor"),
                "client_target_native_type": client_target_native_type,
                "client_target_actor_slot": client_target_actor_slot,
                "client_target_world_slot": client_target_world_slot,
                "host_bucket_delta": parse_int(host_enemy.get("bucket_delta")),
                "client_bucket_delta": client_bucket_delta,
                "host_brain_action_burst": parse_int(host_enemy.get("brain_action_burst")),
                "client_brain_action_burst": parse_int(client_enemy.get("brain_action_burst")),
            })
    return {
        "elapsed": round(elapsed, 3),
        "host_enemy_count": len(host_rows),
        "client_enemy_count": len(client_rows),
        "compared": compared,
        "host_targeted": host_targeted,
        "client_replicated_targeted": client_replicated_targeted,
        "target_mismatch_count": len(target_mismatches),
        "target_mismatches": target_mismatches[:8],
        "unauthorized_target_mismatch_count": len(unauthorized_target_mismatches),
        "unauthorized_target_mismatches": unauthorized_target_mismatches[:8],
        "replicated_lag_mismatch_count": len(replicated_lag_mismatches),
        "replicated_lag_mismatches": replicated_lag_mismatches[:8],
        "host": host,
        "client": client,
    }


def arrange_close_range() -> dict[str, Any]:
    host_place = place_player(HOST_PIPE, 1850.0, 1750.0, 0.0)
    client_place = place_player(CLIENT_PIPE, 1910.0, 1750.0, 0.0)
    enemies = values(HOST_PIPE, ARRANGE_HOST_ENEMIES_LUA)
    selected = parse_int(enemies.get("selected"))
    if selected <= 0:
        raise VerifyFailure(f"no host enemies available for close-range target probe: {enemies}")
    return {
        "host_place": host_place,
        "client_place": client_place,
        "enemies": enemies,
    }


def run_verifier(sample_seconds: float, interval: float) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": False}
    stop_games()
    try:
        result["launch"] = launch_pair(god_mode=True)
        disable_bots()
        result["host_run_entry"] = start_host_testrun_and_wait_for_clients(timeout=60.0)
        result["start_waves"] = start_host_waves()
        result["initial_snapshot"] = wait_for_run_snapshot(
            require_complete_lifecycle=True,
            stable_seconds=1.0,
        )
        result["close_range_arrangement"] = arrange_close_range()
        result["post_arrangement_snapshot"] = wait_for_run_snapshot(
            require_complete_lifecycle=True,
            stable_seconds=0.5,
        )

        samples: list[dict[str, Any]] = []
        started = time.monotonic()
        deadline = started + sample_seconds
        while time.monotonic() < deadline:
            samples.append(capture_pair(time.monotonic() - started))
            time.sleep(interval)

        targeted_samples = [sample for sample in samples if sample["host_targeted"] > 0]
        client_targeted_samples = [sample for sample in samples if sample["client_replicated_targeted"] > 0]
        mismatch_samples = [sample for sample in samples if sample["target_mismatch_count"] > 0]
        unauthorized_mismatch_samples = [
            sample for sample in samples if sample["unauthorized_target_mismatch_count"] > 0
        ]
        clean_client_targeted_samples = [
            sample
            for sample in client_targeted_samples
            if sample["target_mismatch_count"] == 0
        ]
        result["samples"] = samples
        result["summary"] = {
            "sample_count": len(samples),
            "targeted_sample_count": len(targeted_samples),
            "client_targeted_sample_count": len(client_targeted_samples),
            "clean_client_targeted_sample_count": len(clean_client_targeted_samples),
            "mismatch_sample_count": len(mismatch_samples),
            "unauthorized_mismatch_sample_count": len(unauthorized_mismatch_samples),
            "max_host_targeted": max((sample["host_targeted"] for sample in samples), default=0),
            "max_client_replicated_targeted": max(
                (sample["client_replicated_targeted"] for sample in samples),
                default=0,
            ),
            "max_target_mismatches": max((sample["target_mismatch_count"] for sample in samples), default=0),
            "max_unauthorized_target_mismatches": max(
                (sample["unauthorized_target_mismatch_count"] for sample in samples),
                default=0,
            ),
            "final": samples[-1] if samples else None,
        }
        RUNTIME_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")

        if not samples:
            raise VerifyFailure("no target authority samples collected")
        if not targeted_samples:
            raise VerifyFailure("host enemies never acquired a participant or native target during sample window")
        if not client_targeted_samples:
            raise VerifyFailure("client never received a nonzero authoritative enemy target during sample window")
        if not clean_client_targeted_samples:
            first = mismatch_samples[0] if mismatch_samples else client_targeted_samples[0]
            raise VerifyFailure(
                "client native enemy target pointers never matched received authoritative targets; "
                f"first_mismatch={first['target_mismatches'][:3]}"
            )
        if unauthorized_mismatch_samples:
            first = unauthorized_mismatch_samples[0]
            raise VerifyFailure(
                "client kept native enemy targets when the authoritative snapshot had no target; "
                f"first_mismatch={first['unauthorized_target_mismatches'][:3]}"
            )
        if samples[-1]["target_mismatch_count"] > 0:
            raise VerifyFailure(
                "client native enemy target pointers were still mismatched in final sample; "
                f"final_mismatch={samples[-1]['target_mismatches'][:3]}"
            )
        if samples[-1]["unauthorized_target_mismatch_count"] > 0:
            raise VerifyFailure(
                "client still had unauthorized native enemy targets in final sample; "
                f"final_mismatch={samples[-1]['unauthorized_target_mismatches'][:3]}"
            )

        result["ok"] = True
        return result
    finally:
        stop_games()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-seconds", type=float, default=8.0)
    parser.add_argument("--interval", type=float, default=0.25)
    args = parser.parse_args()

    result: dict[str, Any] = {}
    try:
        result = run_verifier(args.sample_seconds, args.interval)
    except Exception as exc:
        if not result:
            runtime_partial = {}
            if RUNTIME_OUTPUT.exists():
                try:
                    runtime_partial = json.loads(RUNTIME_OUTPUT.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    runtime_partial = {}
            result = runtime_partial if isinstance(runtime_partial, dict) else {}
        result["ok"] = False
        result["error"] = str(exc)
        stop_games()

    RUNTIME_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "ok": result.get("ok", False),
        "summary": result.get("summary"),
        "error": result.get("error"),
        "output": str(RUNTIME_OUTPUT),
    }, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
