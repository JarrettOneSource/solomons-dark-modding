#!/usr/bin/env python3
"""Probe host/client run enemy presentation and death-state synchronization."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from verify_local_multiplayer_sync import (
    CLIENT_PIPE,
    HOST_PIPE,
    ROOT,
    VerifyFailure,
    disable_bots,
    launch_pair,
    lua,
    parse_key_values,
    start_host_testrun_and_wait_for_clients,
    stop_games,
)
from verify_run_world_snapshot import start_host_waves, wait_for_run_snapshot


RUNTIME_OUTPUT = ROOT / "runtime" / "run_enemy_presentation_sync.json"
LOCOMOTION_PRESENTATION_FLAG = 1 << 3
LOCOMOTION_FIELD_TOLERANCE = 0.35
LOCOMOTION_FIELDS = (
    "walk_cycle_primary",
    "walk_cycle_secondary",
)


CAPTURE_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local function hx(v) return string.format("0x%08X", tonumber(v) or 0) end
local function finite(v)
  return type(v) == "number" and v == v and v ~= math.huge and v ~= -math.huge
end
local function u8(address) return tonumber(sd.debug.read_u8(address)) or 0 end
local function u32(address) return tonumber(sd.debug.read_u32(address)) or 0 end
local function flt(address) return tonumber(sd.debug.read_float(address)) or 0 end
local drive_offset = sd.debug.layout_offset("actor_animation_drive_state_byte")
local death_handled_offset = sd.debug.layout_offset("enemy_death_handled")
local heading_offset = sd.debug.layout_offset("actor_heading")
local function actor_drive_byte(address)
  if address == nil or address == 0 or drive_offset == nil then return 0 end
  return u8(address + drive_offset)
end
local function actor_drive_word(address)
  if address == nil or address == 0 or drive_offset == nil then return 0 end
  return u32(address + drive_offset)
end
local function actor_death_handled(address)
  if address == nil or address == 0 or death_handled_offset == nil then return 0 end
  return u8(address + death_handled_offset)
end
local function actor_heading(address)
  if address == nil or address == 0 or heading_offset == nil then return 0 end
  return flt(address + heading_offset)
end
local walk_primary_offset = sd.debug.layout_offset("actor_walk_cycle_primary")
local walk_secondary_offset = sd.debug.layout_offset("actor_walk_cycle_secondary")
local function actor_float_field(address, offset)
  if address == nil or address == 0 or offset == nil then return 0 end
  return flt(address + offset)
end
local scene = sd.world.get_scene()
emit("scene", scene and (scene.name or scene.kind) or "")
local actors = sd.world.list_actors() or {}
local tracked = {}
local local_by_address = {}
for _, actor in ipairs(actors) do
  local address = tonumber(actor.actor_address) or 0
  local type_id = tonumber(actor.object_type_id) or 0
  if actor.tracked_enemy and address ~= 0 and type_id ~= 0 and type_id ~= 1 and finite(tonumber(actor.x)) and finite(tonumber(actor.y)) then
    tracked[#tracked + 1] = actor
    local_by_address[address] = actor
  end
end
emit("local.count", #tracked)
for index, actor in ipairs(tracked) do
  local address = tonumber(actor.actor_address) or 0
  local prefix = "local." .. tostring(index)
  emit(prefix .. ".address", hx(address))
  emit(prefix .. ".type", actor.object_type_id or 0)
  emit(prefix .. ".enemy_type", actor.enemy_type or -1)
  emit(prefix .. ".slot", actor.actor_slot or -1)
  emit(prefix .. ".world_slot", actor.world_slot or -1)
  emit(prefix .. ".x", string.format("%.3f", tonumber(actor.x) or 0))
  emit(prefix .. ".y", string.format("%.3f", tonumber(actor.y) or 0))
  emit(prefix .. ".heading", string.format("%.3f", actor_heading(address)))
  emit(prefix .. ".hp", string.format("%.3f", tonumber(actor.hp) or 0))
  emit(prefix .. ".max_hp", string.format("%.3f", tonumber(actor.max_hp) or 0))
  emit(prefix .. ".dead", actor.dead and 1 or 0)
  emit(prefix .. ".drive_byte", actor_drive_byte(address))
  emit(prefix .. ".drive_word", hx(actor_drive_word(address)))
  emit(prefix .. ".walk_cycle_primary", string.format("%.4f", actor_float_field(address, walk_primary_offset)))
  emit(prefix .. ".walk_cycle_secondary", string.format("%.4f", actor_float_field(address, walk_secondary_offset)))
  emit(prefix .. ".death_handled", actor_death_handled(address))
end

local replicated = sd.world.get_replicated_actors and sd.world.get_replicated_actors() or nil
emit("rep.valid", replicated ~= nil)
emit("rep.scene_kind", replicated and replicated.scene_kind or "")
emit("rep.actor_count", replicated and replicated.actor_count or 0)
emit("rep.total_count", replicated and replicated.actor_total_count or 0)
emit("rep.truncated", replicated and replicated.truncated or false)
emit("rep.apply_valid", replicated and replicated.apply_valid or false)
emit("rep.binding_count", replicated and replicated.binding_count or 0)
local local_by_id = {}
if replicated and replicated.bindings then
  for _, binding in ipairs(replicated.bindings) do
    if binding.matched and not binding.parked then
      local network_id = tonumber(binding.network_actor_id) or 0
      local address = tonumber(binding.local_actor_address) or 0
      local actor = local_by_address[address]
      if network_id ~= 0 and actor ~= nil then
        local_by_id[network_id] = actor
      end
    end
  end
end
if replicated and replicated.actors then
  for index, actor in ipairs(replicated.actors) do
    local network_id = tonumber(actor.network_actor_id) or 0
    local prefix = "rep." .. tostring(index)
    local local_actor = local_by_id[network_id]
    emit(prefix .. ".network_id", network_id)
    emit(prefix .. ".type", actor.object_type_id or 0)
    emit(prefix .. ".enemy_type", actor.enemy_type or -1)
    emit(prefix .. ".lifecycle_owned", actor.lifecycle_owned and 1 or 0)
    emit(prefix .. ".dead", actor.dead and 1 or 0)
    emit(prefix .. ".drive_byte", actor.anim_drive_state or 0)
    emit(prefix .. ".presentation_flags", actor.presentation_flags or 0)
    emit(prefix .. ".drive_word", hx(actor.anim_drive_state_word or 0))
    emit(prefix .. ".walk_cycle_primary", string.format("%.4f", tonumber(actor.walk_cycle_primary) or 0))
    emit(prefix .. ".walk_cycle_secondary", string.format("%.4f", tonumber(actor.walk_cycle_secondary) or 0))
    emit(prefix .. ".hp", string.format("%.3f", tonumber(actor.hp) or 0))
    emit(prefix .. ".max_hp", string.format("%.3f", tonumber(actor.max_hp) or 0))
    emit(prefix .. ".has_local", local_actor ~= nil and 1 or 0)
    if local_actor ~= nil then
      local address = tonumber(local_actor.actor_address) or 0
      emit(prefix .. ".local_address", hx(address))
      emit(prefix .. ".local_dead", local_actor.dead and 1 or 0)
      emit(prefix .. ".local_drive_byte", actor_drive_byte(address))
      emit(prefix .. ".local_drive_word", hx(actor_drive_word(address)))
      emit(prefix .. ".local_walk_cycle_primary", string.format("%.4f", actor_float_field(address, walk_primary_offset)))
      emit(prefix .. ".local_walk_cycle_secondary", string.format("%.4f", actor_float_field(address, walk_secondary_offset)))
      emit(prefix .. ".local_death_handled", actor_death_handled(address))
      emit(prefix .. ".local_hp", string.format("%.3f", tonumber(local_actor.hp) or 0))
      emit(prefix .. ".local_max_hp", string.format("%.3f", tonumber(local_actor.max_hp) or 0))
    end
  end
end
"""


KILL_HOST_ENEMY_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local actors = sd.world.list_actors() or {}
local hp_offset = sd.debug.layout_offset("enemy_current_hp")
local death_handled_offset = sd.debug.layout_offset("enemy_death_handled")
local drive_offset = sd.debug.layout_offset("actor_animation_drive_state_byte")
for _, actor in ipairs(actors) do
  local type_id = tonumber(actor.object_type_id) or 0
  local address = tonumber(actor.actor_address) or 0
  local hp = tonumber(actor.hp) or 0
  local max_hp = tonumber(actor.max_hp) or 0
  if actor.tracked_enemy and type_id ~= 0 and type_id ~= 1 and address ~= 0 and hp_offset ~= nil and max_hp > 0 and hp > 0 then
    emit("selected_address", string.format("0x%08X", address))
    emit("selected_type", type_id)
    emit("old_hp", string.format("%.3f", hp))
    emit("max_hp", string.format("%.3f", max_hp))
    emit("old_dead", actor.dead and 1 or 0)
    emit("old_death_handled", death_handled_offset and (sd.debug.read_u8(address + death_handled_offset) or 0) or 0)
    emit("old_drive_byte", drive_offset and (sd.debug.read_u8(address + drive_offset) or 0) or 0)
    emit("write_hp", sd.debug.write_float(address + hp_offset, 0.0))
    return
  end
end
emit("write_hp", false)
"""


def values(pipe_name: str, code: str, timeout: float = 10.0) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, code, timeout=timeout))


def parse_int(value: str | None, default: int = 0) -> int:
    if value is None:
        return default
    try:
        if value.startswith("0x") or value.startswith("0X"):
            return int(value, 16)
        return int(float(value))
    except (TypeError, ValueError):
        return default


def parse_float(value: str | None, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def capture_pair() -> dict[str, Any]:
    host = values(HOST_PIPE, CAPTURE_LUA)
    client = values(CLIENT_PIPE, CAPTURE_LUA)
    return {
        "host": host,
        "client": client,
        "summary": summarize_capture(host, client),
    }


def summarize_capture(host: dict[str, str], client: dict[str, str]) -> dict[str, Any]:
    rep_count = parse_int(client.get("rep.actor_count"))
    local_count = parse_int(client.get("local.count"))
    host_count = parse_int(host.get("local.count"))
    compared = 0
    drive_byte_mismatches = 0
    local_dead_mismatches = 0
    local_hp_mismatches = 0
    local_death_handled_dead = 0
    snapshot_dead = 0
    snapshot_drive_word_present = 0
    snapshot_locomotion_present = 0
    locomotion_compared = 0
    locomotion_mismatches = 0
    max_locomotion_delta = 0.0
    client_drive_words_nonzero = 0
    host_client_ordinal_drive_word_mismatches = 0
    host_client_ordinal_death_handled_mismatches = 0
    max_host_client_ordinal_hp_delta = 0.0
    for index in range(1, rep_count + 1):
        if parse_int(client.get(f"rep.{index}.has_local")) == 0:
            continue
        compared += 1
        snapshot_drive = parse_int(client.get(f"rep.{index}.drive_byte"))
        local_drive = parse_int(client.get(f"rep.{index}.local_drive_byte"))
        if snapshot_drive != local_drive:
            drive_byte_mismatches += 1
        snapshot_dead_value = parse_int(client.get(f"rep.{index}.dead"))
        local_dead_value = parse_int(client.get(f"rep.{index}.local_dead"))
        if snapshot_dead_value:
            snapshot_dead += 1
        if snapshot_dead_value != local_dead_value:
            local_dead_mismatches += 1
        local_death_handled = parse_int(client.get(f"rep.{index}.local_death_handled"))
        if local_dead_value and local_death_handled:
            local_death_handled_dead += 1
        if parse_int(client.get(f"rep.{index}.presentation_flags")) & 1:
            snapshot_drive_word_present += 1
        if parse_int(client.get(f"rep.{index}.presentation_flags")) & LOCOMOTION_PRESENTATION_FLAG:
            snapshot_locomotion_present += 1
            for field in LOCOMOTION_FIELDS:
                snapshot_value = parse_float(client.get(f"rep.{index}.{field}"))
                local_value = parse_float(client.get(f"rep.{index}.local_{field}"))
                delta = abs(snapshot_value - local_value)
                locomotion_compared += 1
                if delta > max_locomotion_delta:
                    max_locomotion_delta = delta
                if delta > LOCOMOTION_FIELD_TOLERANCE:
                    locomotion_mismatches += 1
        if parse_int(client.get(f"rep.{index}.local_drive_word")) != 0:
            client_drive_words_nonzero += 1
        snapshot_hp = parse_float(client.get(f"rep.{index}.hp"))
        local_hp = parse_float(client.get(f"rep.{index}.local_hp"))
        if abs(snapshot_hp - local_hp) > 0.25:
            local_hp_mismatches += 1
        if index <= host_count:
            host_word = parse_int(host.get(f"local.{index}.drive_word"))
            client_word = parse_int(client.get(f"rep.{index}.local_drive_word"))
            if host_word != client_word:
                host_client_ordinal_drive_word_mismatches += 1
            host_death = parse_int(host.get(f"local.{index}.death_handled"))
            client_death = parse_int(client.get(f"rep.{index}.local_death_handled"))
            if host_death != client_death:
                host_client_ordinal_death_handled_mismatches += 1
            host_hp = parse_float(host.get(f"local.{index}.hp"))
            hp_delta = abs(host_hp - local_hp)
            if hp_delta > max_host_client_ordinal_hp_delta:
                max_host_client_ordinal_hp_delta = hp_delta
    return {
        "host_scene": host.get("scene", ""),
        "client_scene": client.get("scene", ""),
        "host_local_count": host_count,
        "client_local_count": local_count,
        "client_snapshot_count": rep_count,
        "client_snapshot_total_count": parse_int(client.get("rep.total_count")),
        "client_snapshot_truncated": client.get("rep.truncated") == "true",
        "client_apply_valid": client.get("rep.apply_valid") == "true",
        "compared": compared,
        "drive_byte_mismatches": drive_byte_mismatches,
        "snapshot_drive_word_present": snapshot_drive_word_present,
        "snapshot_locomotion_present": snapshot_locomotion_present,
        "locomotion_compared": locomotion_compared,
        "locomotion_mismatches": locomotion_mismatches,
        "max_locomotion_delta": round(max_locomotion_delta, 4),
        "client_drive_words_nonzero": client_drive_words_nonzero,
        "host_client_ordinal_drive_word_mismatches": host_client_ordinal_drive_word_mismatches,
        "snapshot_dead": snapshot_dead,
        "local_dead_mismatches": local_dead_mismatches,
        "local_death_handled_dead": local_death_handled_dead,
        "host_client_ordinal_death_handled_mismatches": host_client_ordinal_death_handled_mismatches,
        "local_hp_mismatches": local_hp_mismatches,
        "max_host_client_ordinal_hp_delta": round(max_host_client_ordinal_hp_delta, 3),
    }


def aggregate_samples(samples: list[dict[str, Any]]) -> dict[str, Any]:
    summaries = [sample["summary"] for sample in samples]

    def max_value(key: str) -> Any:
        return max((summary.get(key, 0) for summary in summaries), default=0)

    def min_value(key: str) -> Any:
        return min((summary.get(key, 0) for summary in summaries), default=0)

    return {
        "sample_count": len(samples),
        "host_scene": summaries[-1].get("host_scene", "") if summaries else "",
        "client_scene": summaries[-1].get("client_scene", "") if summaries else "",
        "min_compared": min_value("compared"),
        "max_compared": max_value("compared"),
        "max_drive_byte_mismatches": max_value("drive_byte_mismatches"),
        "max_snapshot_drive_word_present": max_value("snapshot_drive_word_present"),
        "max_snapshot_locomotion_present": max_value("snapshot_locomotion_present"),
        "min_locomotion_compared": min_value("locomotion_compared"),
        "max_locomotion_mismatches": max_value("locomotion_mismatches"),
        "max_locomotion_delta": max_value("max_locomotion_delta"),
        "max_client_drive_words_nonzero": max_value("client_drive_words_nonzero"),
        "max_host_client_ordinal_drive_word_mismatches": max_value(
            "host_client_ordinal_drive_word_mismatches"
        ),
        "max_snapshot_dead": max_value("snapshot_dead"),
        "max_local_dead_mismatches": max_value("local_dead_mismatches"),
        "max_local_death_handled_dead": max_value("local_death_handled_dead"),
        "max_host_client_ordinal_death_handled_mismatches": max_value(
            "host_client_ordinal_death_handled_mismatches"
        ),
        "max_local_hp_mismatches": max_value("local_hp_mismatches"),
        "max_host_client_ordinal_hp_delta": max_value("max_host_client_ordinal_hp_delta"),
    }


def collect_samples(count: int, interval: float) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for index in range(count):
        samples.append(capture_pair())
        if index + 1 < count:
            time.sleep(interval)
    return samples


def kill_host_enemy() -> dict[str, str]:
    result = values(HOST_PIPE, KILL_HOST_ENEMY_LUA)
    if result.get("write_hp") != "true":
        raise VerifyFailure(f"failed to set host enemy HP to zero: {result}")
    return result


def wait_for_dead_snapshot(timeout: float, interval: float) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout
    samples: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        sample = capture_pair()
        samples.append(sample)
        summary = sample["summary"]
        if (
            summary.get("snapshot_dead", 0) > 0
            and summary.get("local_dead_mismatches", 0) == 0
            and summary.get("local_hp_mismatches", 0) == 0
        ):
            return samples
        time.sleep(interval)
    return samples


def setup_live_run_pair(max_attempts: int = 3) -> dict[str, Any]:
    last_error = ""
    for attempt in range(1, max_attempts + 1):
        try:
            stop_games()
            launch = launch_pair()
            disable_bots()
            host_run_entry = start_host_testrun_and_wait_for_clients()
            start_waves = start_host_waves()
            snapshot_ready = wait_for_run_snapshot(require_complete_lifecycle=True)
            return {
                "attempt": attempt,
                "launch": launch,
                "host_run_entry": host_run_entry,
                "start_waves": start_waves,
                "snapshot_ready": snapshot_ready,
            }
        except Exception as exc:
            last_error = str(exc)
            stop_games()
            time.sleep(1.0)
    raise VerifyFailure(f"failed to prepare live run pair after {max_attempts} attempts: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=8)
    parser.add_argument("--interval", type=float, default=0.2)
    parser.add_argument("--death-timeout", type=float, default=8.0)
    parser.add_argument("--no-launch", action="store_true")
    parser.add_argument("--skip-death", action="store_true")
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    try:
        if not args.no_launch:
            result["setup"] = setup_live_run_pair()
        baseline_samples = collect_samples(args.samples, args.interval)
        result["baseline"] = aggregate_samples(baseline_samples)
        result["baseline_samples"] = baseline_samples
        baseline_ok = (
            result["baseline"]["min_compared"] > 0
            and result["baseline"]["max_drive_byte_mismatches"] == 0
            and result["baseline"]["max_snapshot_locomotion_present"] > 0
            and result["baseline"]["min_locomotion_compared"] > 0
            and result["baseline"]["max_locomotion_mismatches"] == 0
        )
        if not args.skip_death:
            result["host_kill"] = kill_host_enemy()
            death_samples = wait_for_dead_snapshot(args.death_timeout, args.interval)
            result["death"] = aggregate_samples(death_samples)
            result["death_samples"] = death_samples
        else:
            result["host_kill"] = None
            result["death"] = None
            result["death_samples"] = []
        result["ok"] = (
            baseline_ok
            and (
                args.skip_death
                or (
                    result["death"]["max_snapshot_dead"] > 0
                    and result["death"]["max_local_dead_mismatches"] == 0
                    and result["death"]["max_local_hp_mismatches"] == 0
                )
            )
        )
        RUNTIME_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({
            "ok": result["ok"],
            "baseline": result["baseline"],
            "death": result["death"],
            "host_kill": result["host_kill"],
            "output": str(RUNTIME_OUTPUT),
        }, indent=2, sort_keys=True))
        return 0 if result["ok"] else 1
    except Exception as exc:
        result["error"] = str(exc)
        RUNTIME_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1
    finally:
        if not args.no_launch:
            stop_games()


if __name__ == "__main__":
    raise SystemExit(main())
