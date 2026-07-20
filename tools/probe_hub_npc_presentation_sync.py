#!/usr/bin/env python3
"""Verify host-authored hub NPC presentation state on a connected client."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from multiplayer_lua_probe import DEFAULT_CLIENTS, parse_client, run_all  # noqa: E402


RUNTIME_OUTPUT = ROOT / "runtime" / "hub_npc_presentation_sync.json"

STUDENT_TYPE_ID = 0x138A
HUB_NPC_TYPE_MIN = 0x1389
HUB_NPC_TYPE_MAX = 0x1390
DRIVE_PHASE_TOLERANCE = 8
HUB_ANIMATION_DRIVE_PHASE_UNITS_PER_SECOND = 150
PHASE_ADVANCING_NPC_TYPES = frozenset((0x138B, 0x138C, 0x138D, 0x138F))


LUA_CAPTURE = r"""
local function emit(k, v)
  print(k .. "=" .. tostring(v))
end

local function hx(v)
  return string.format("0x%08X", tonumber(v) or 0)
end

local function f(v)
  if v == nil then return "nil" end
  return string.format("%.3f", tonumber(v) or 0)
end

local function u8(address)
  return tonumber(sd.debug.read_u8(address)) or 0
end

local function u32(address)
  return tonumber(sd.debug.read_u32(address)) or 0
end

local function flt(address)
  return tonumber(sd.debug.read_float(address)) or 0
end

local function byte_string(address, count)
  local out = {}
  for i = 0, count - 1 do
    out[#out + 1] = string.format("%02X", u8(address + i))
  end
  return table.concat(out, " ")
end

local function student_book_palette_string(address)
  local count = u32(address + 0x1C0)
  if count > 5 then
    return "invalid:" .. tostring(count)
  end
  local out = { tostring(count) }
  for index = 0, count - 1 do
    local color = address + 0x1C4 + index * 0x10
    for component = 0, 3 do
      out[#out + 1] = hx(u32(color + component * 4))
    end
    out[#out + 1] = hx(u32(address + 0x214 + index * 4))
    out[#out + 1] = hx(u32(address + 0x228 + index * 4))
  end
  return table.concat(out, ":")
end

local function float_hex(value)
  local packed = string.pack("<f", tonumber(value) or 0)
  local b1, b2, b3, b4 = string.byte(packed, 1, 4)
  return string.format("0x%02X%02X%02X%02X", b4, b3, b2, b1)
end

local function student_visual_state_string(actor)
  local out = {}
  for index = 1, 32 do
    out[#out + 1] = string.format(
      "%02X", tonumber(actor.student_visual_state and actor.student_visual_state[index]) or 0)
  end
  return table.concat(out, " ")
end

local function student_book_palette_snapshot_string(actor)
  local count = tonumber(actor.student_book_palette_count) or 0
  if count > 5 then
    return "invalid:" .. tostring(count)
  end
  local out = { tostring(count) }
  for index = 1, count do
    local entry = actor.student_book_palette and actor.student_book_palette[index] or {}
    out[#out + 1] = float_hex(entry.red)
    out[#out + 1] = float_hex(entry.green)
    out[#out + 1] = float_hex(entry.blue)
    out[#out + 1] = float_hex(entry.alpha)
    out[#out + 1] = float_hex(entry.radial_offset)
    out[#out + 1] = float_hex(entry.angular_offset)
  end
  return table.concat(out, ":")
end

local function finite(v)
  return type(v) == "number" and v == v and v ~= math.huge and v ~= -math.huge
end

local function hub_npc_type(type_id)
  return type_id >= 0x1389 and type_id <= 0x1390
end

local scene = sd.world.get_scene()
emit("scene.name", scene and scene.name or "")
emit("scene.kind", scene and scene.kind or "")

local actors = sd.world.list_actors() or {}
local actor_index = 0
for _, actor in ipairs(actors) do
  local address = tonumber(actor.actor_address) or 0
  local type_id = tonumber(actor.object_type_id) or 0
  if address ~= 0 and hub_npc_type(type_id) and finite(tonumber(actor.x)) and finite(tonumber(actor.y)) then
    actor_index = actor_index + 1
    local prefix = "actor." .. tostring(actor_index)
    emit(prefix .. ".address", hx(address))
    emit(prefix .. ".type", type_id)
    emit(prefix .. ".actor_slot", actor.actor_slot or -1)
    emit(prefix .. ".world_slot", actor.world_slot or -1)
    emit(prefix .. ".x", f(actor.x))
    emit(prefix .. ".y", f(actor.y))
    emit(prefix .. ".heading", f(flt(address + 0x6C)))
    emit(prefix .. ".snapshot_drive", actor.anim_drive_state or 0)
    emit(prefix .. ".drive_byte", u8(address + 0x160))
    emit(prefix .. ".drive_raw", hx(u32(address + 0x160)))
    emit(prefix .. ".walk_primary", hx(u32(address + 0x220)))
    emit(prefix .. ".walk_secondary", hx(u32(address + 0x224)))
    emit(prefix .. ".stride_scale", hx(u32(address + 0x228)))
    emit(prefix .. ".render_table", hx(u32(address + 0x22C)))
    emit(prefix .. ".render_rate", hx(u32(address + 0x234)))
    emit(prefix .. ".render_phase", hx(u32(address + 0x238)))
    emit(prefix .. ".variant_primary", u8(address + 0x23C))
    emit(prefix .. ".variant_secondary", u8(address + 0x23D))
    emit(prefix .. ".weapon_type", u8(address + 0x23E))
    emit(prefix .. ".selection_byte", u8(address + 0x23F))
    emit(prefix .. ".variant_tertiary", u8(address + 0x240))
    if type_id == 0x138A then
      emit(prefix .. ".student_color_190", byte_string(address + 0x190, 32))
      emit(prefix .. ".student_book_palette_1c0", student_book_palette_string(address))
    end
  end
end
emit("actor.count", actor_index)

local replicated = sd.world.get_replicated_actors and sd.world.get_replicated_actors() or nil
emit("replicated.valid", replicated ~= nil)
emit("replicated.scene_kind", replicated and replicated.scene_kind or "")
emit("replicated.sampled_ms", replicated and replicated.sampled_ms or 0)
emit("replicated.received_ms", replicated and replicated.received_ms or 0)
emit("replicated.sequence", replicated and replicated.sequence or 0)
emit("replicated.scene_epoch", replicated and replicated.scene_epoch or 0)
emit("replicated.apply_valid", replicated and replicated.apply_valid or false)
emit("replicated.apply_sequence", replicated and replicated.apply_sequence or 0)
emit("replicated.apply_scene_epoch", replicated and replicated.apply_scene_epoch or 0)
emit(
  "replicated.apply_presentation_sequence",
  replicated and replicated.apply_presentation_sequence or 0)
emit(
  "replicated.apply_presentation_scene_epoch",
  replicated and replicated.apply_presentation_scene_epoch or 0)
emit(
  "replicated.apply_presentation_received_ms",
  replicated and replicated.apply_presentation_received_ms or 0)
emit("replicated.applied_ms", replicated and replicated.applied_ms or 0)
emit("replicated.actor_count", replicated and replicated.actor_count or 0)
emit("replicated.total_count", replicated and replicated.actor_total_count or 0)
emit("replicated.truncated", replicated and replicated.truncated or false)
emit("replicated.binding_count", replicated and replicated.binding_count or 0)
emit("replicated.local_actor_count", replicated and replicated.local_actor_count or 0)
emit("replicated.matched_actor_count", replicated and replicated.matched_actor_count or 0)
emit("replicated.created_actor_count", replicated and replicated.created_actor_count or 0)
emit(
  "replicated.created_actor_total_count",
  replicated and replicated.created_actor_total_count or 0)
emit("replicated.removed_actor_count", replicated and replicated.removed_actor_count or 0)
emit(
  "replicated.removed_actor_total_count",
  replicated and replicated.removed_actor_total_count or 0)
emit(
  "replicated.failed_remove_actor_count",
  replicated and replicated.failed_remove_actor_count or 0)
emit(
  "replicated.failed_remove_actor_total_count",
  replicated and replicated.failed_remove_actor_total_count or 0)
emit(
  "replicated.apply_presentation_available",
  replicated and replicated.apply_presentation_available or false)
emit(
  "replicated.apply_actors_available",
  replicated and replicated.apply_actors_available or false)

local function emit_snapshot_actor(prefix, actor)
  emit(prefix .. ".network_id", actor.network_actor_id or 0)
  emit(prefix .. ".type", actor.object_type_id or 0)
  emit(prefix .. ".actor_slot", actor.actor_slot or -1)
  emit(prefix .. ".world_slot", actor.world_slot or -1)
  emit(prefix .. ".x", f(actor.x))
  emit(prefix .. ".y", f(actor.y))
  emit(prefix .. ".heading", f(actor.heading))
  emit(prefix .. ".drive", actor.anim_drive_state or 0)
  emit(prefix .. ".presentation_flags", actor.presentation_flags or 0)
  emit(prefix .. ".drive_word", hx(actor.anim_drive_state_word or 0))
  emit(prefix .. ".variant_primary", actor.render_variant_primary or 0)
  emit(prefix .. ".variant_secondary", actor.render_variant_secondary or 0)
  emit(prefix .. ".weapon_type", actor.render_weapon_type or 0)
  emit(prefix .. ".selection_byte", actor.render_selection_byte or 0)
  emit(prefix .. ".variant_tertiary", actor.render_variant_tertiary or 0)
  emit(prefix .. ".student_book_palette_count", actor.student_book_palette_count or 0)
  if tonumber(actor.object_type_id) == 0x138A then
    emit(prefix .. ".student_color_190", student_visual_state_string(actor))
    emit(prefix .. ".student_book_palette_1c0", student_book_palette_snapshot_string(actor))
  end
end

if replicated ~= nil and replicated.actors ~= nil then
  for index, actor in ipairs(replicated.actors) do
    emit_snapshot_actor("repactor." .. tostring(index), actor)
  end
end

if replicated ~= nil and replicated.apply_actors ~= nil then
  for index, actor in ipairs(replicated.apply_actors) do
    emit_snapshot_actor("applyactor." .. tostring(index), actor)
  end
end

if replicated ~= nil and replicated.apply_presentation_actors ~= nil then
  for index, actor in ipairs(replicated.apply_presentation_actors) do
    emit_snapshot_actor("presactor." .. tostring(index), actor)
  end
end

if replicated ~= nil and replicated.bindings ~= nil then
  for index, binding in ipairs(replicated.bindings) do
    local prefix = "binding." .. tostring(index)
    emit(prefix .. ".network_id", binding.network_actor_id or 0)
    emit(prefix .. ".address", hx(binding.local_actor_address or 0))
    emit(prefix .. ".type", binding.object_type_id or 0)
    emit(prefix .. ".matched", binding.matched or false)
    emit(prefix .. ".parked", binding.parked or false)
    emit(prefix .. ".removed", binding.removed or false)
  end
end
"""


def parse_indexed(values: dict[str, str], prefix: str) -> list[dict[str, str]]:
    records: dict[int, dict[str, str]] = {}
    stem = prefix + "."
    for key, value in values.items():
        if not key.startswith(stem):
            continue
        rest = key[len(stem) :]
        index_text, dot, field = rest.partition(".")
        if not dot:
            continue
        try:
            index = int(index_text)
        except ValueError:
            continue
        records.setdefault(index, {})[field] = value
    return [records[index] for index in sorted(records)]


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


def drive_phase_distance(left: str | None, right: str | None) -> int:
    left_phase = parse_int(left) & 0xFFFF
    right_phase = parse_int(right) & 0xFFFF
    delta = (left_phase - right_phase) & 0xFFFF
    if delta > 0x7FFF:
        delta = 0x10000 - delta
    return delta


def advance_drive_phase(drive_word: str | None, elapsed_ms: int) -> int:
    value = parse_int(drive_word)
    phase_delta = (
        elapsed_ms * HUB_ANIMATION_DRIVE_PHASE_UNITS_PER_SECOND + 500
    ) // 1000
    return (value & 0xFFFF0000) | ((value + phase_delta) & 0xFFFF)


def dist_sq(actor: dict[str, str], x: float, y: float) -> float:
    dx = parse_float(actor.get("x")) - x
    dy = parse_float(actor.get("y")) - y
    return dx * dx + dy * dy


def nearest_actor(
    actors: list[dict[str, str]],
    type_id: int,
    x: float,
    y: float,
    used: set[int],
) -> tuple[int, dict[str, str] | None, float]:
    best_index = -1
    best_actor: dict[str, str] | None = None
    best_distance = math.inf
    for index, actor in enumerate(actors):
        if index in used or parse_int(actor.get("type")) != type_id:
            continue
        distance = dist_sq(actor, x, y)
        if distance < best_distance:
            best_index = index
            best_actor = actor
            best_distance = distance
    return best_index, best_actor, math.sqrt(best_distance) if math.isfinite(best_distance) else math.inf


def match_snapshot_actor(
    actors: list[dict[str, str]],
    snapshot: dict[str, str],
    used: set[int],
) -> tuple[int, dict[str, str] | None, float]:
    type_id = parse_int(snapshot.get("type"))
    actor_slot = parse_int(snapshot.get("actor_slot"), -1)
    world_slot = parse_int(snapshot.get("world_slot"), -1)
    exact: list[tuple[int, dict[str, str]]] = []
    for index, actor in enumerate(actors):
        if index in used or parse_int(actor.get("type")) != type_id:
            continue
        if (
            parse_int(actor.get("actor_slot"), -1) == actor_slot
            and parse_int(actor.get("world_slot"), -1) == world_slot
        ):
            exact.append((index, actor))
    if len(exact) == 1:
        index, actor = exact[0]
        return index, actor, math.sqrt(
            dist_sq(actor, parse_float(snapshot.get("x")), parse_float(snapshot.get("y")))
        )
    return nearest_actor(
        actors,
        type_id,
        parse_float(snapshot.get("x")),
        parse_float(snapshot.get("y")),
        used,
    )


def build_client_snapshot(values: dict[str, str]) -> dict[str, Any]:
    actors = parse_indexed(values, "actor")
    repactors = parse_indexed(values, "repactor")
    applyactors = parse_indexed(values, "applyactor")
    presentationactors = parse_indexed(values, "presactor")
    bindings = parse_indexed(values, "binding")
    local_by_address = {parse_int(actor.get("address")): actor for actor in actors}
    binding_by_id = {
        parse_int(binding.get("network_id")): binding
        for binding in bindings
        if binding.get("matched") == "true"
        and binding.get("parked") != "true"
        and binding.get("removed") != "true"
    }
    return {
        "scene_name": values.get("scene.name", ""),
        "scene_kind": values.get("scene.kind", ""),
        "actors": actors,
        "repactors": repactors,
        "applyactors": applyactors,
        "presentationactors": presentationactors,
        "presentationactor_by_id": {
            parse_int(actor.get("network_id")): actor
            for actor in presentationactors
            if parse_int(actor.get("network_id")) != 0
        },
        "repactor_by_id": {
            parse_int(actor.get("network_id")): actor
            for actor in repactors
            if parse_int(actor.get("network_id")) != 0
        },
        "bindings": bindings,
        "local_by_address": local_by_address,
        "binding_by_id": binding_by_id,
        "replicated_valid": values.get("replicated.valid") == "true",
        "replicated_sampled_ms": parse_int(values.get("replicated.sampled_ms")),
        "replicated_received_ms": parse_int(values.get("replicated.received_ms")),
        "replicated_sequence": parse_int(values.get("replicated.sequence")),
        "replicated_scene_epoch": parse_int(values.get("replicated.scene_epoch")),
        "replicated_apply_valid": values.get("replicated.apply_valid") == "true",
        "replicated_apply_presentation_available": (
            values.get("replicated.apply_presentation_available") == "true"
        ),
        "replicated_apply_actors_available": (
            values.get("replicated.apply_actors_available") == "true"
        ),
        "replicated_apply_sequence": parse_int(values.get("replicated.apply_sequence")),
        "replicated_apply_scene_epoch": parse_int(values.get("replicated.apply_scene_epoch")),
        "replicated_apply_presentation_sequence": parse_int(
            values.get("replicated.apply_presentation_sequence")
        ),
        "replicated_apply_presentation_scene_epoch": parse_int(
            values.get("replicated.apply_presentation_scene_epoch")
        ),
        "replicated_apply_presentation_received_ms": parse_int(
            values.get("replicated.apply_presentation_received_ms")
        ),
        "replicated_applied_ms": parse_int(values.get("replicated.applied_ms")),
        "replicated_actor_count": parse_int(values.get("replicated.actor_count")),
        "replicated_total_count": parse_int(values.get("replicated.total_count")),
        "replicated_truncated": values.get("replicated.truncated") == "true",
        "replicated_local_actor_count": parse_int(
            values.get("replicated.local_actor_count")
        ),
        "replicated_matched_actor_count": parse_int(
            values.get("replicated.matched_actor_count")
        ),
        "replicated_created_actor_count": parse_int(
            values.get("replicated.created_actor_count")
        ),
        "replicated_created_actor_total_count": parse_int(
            values.get("replicated.created_actor_total_count")
        ),
        "replicated_removed_actor_count": parse_int(
            values.get("replicated.removed_actor_count")
        ),
        "replicated_removed_actor_total_count": parse_int(
            values.get("replicated.removed_actor_total_count")
        ),
        "replicated_failed_remove_actor_count": parse_int(
            values.get("replicated.failed_remove_actor_count")
        ),
        "replicated_failed_remove_actor_total_count": parse_int(
            values.get("replicated.failed_remove_actor_total_count")
        ),
    }


def compare_host_to_client(host_values: dict[str, str], client_values: dict[str, str]) -> dict[str, Any]:
    host = build_client_snapshot(host_values)
    client = build_client_snapshot(client_values)
    client_apply_presentation_available = (
        client["replicated_apply_valid"]
        and client["replicated_apply_presentation_available"]
    )
    client_apply_actors_available = (
        client["replicated_apply_valid"]
        and client["replicated_apply_actors_available"]
    )
    client_presentation_clock_valid = (
        client["replicated_applied_ms"]
        >= client["replicated_apply_presentation_received_ms"]
        and client["replicated_sampled_ms"] >= client["replicated_applied_ms"]
    )
    client_presentation_age_ms = (
        client["replicated_applied_ms"]
        - client["replicated_apply_presentation_received_ms"]
        if client_presentation_clock_valid
        else 0
    )
    host_actors: list[dict[str, str]] = host["actors"]
    used_host: set[int] = set()
    host_actor_by_network_id: dict[int, tuple[dict[str, str], float]] = {}
    for repactor in host["repactors"]:
        type_id = parse_int(repactor.get("type"))
        if type_id < HUB_NPC_TYPE_MIN or type_id > HUB_NPC_TYPE_MAX:
            continue
        host_index, host_actor, host_distance = match_snapshot_actor(
            host_actors, repactor, used_host
        )
        if host_actor is None:
            continue
        used_host.add(host_index)
        host_actor_by_network_id[parse_int(repactor.get("network_id"))] = (
            host_actor,
            host_distance,
        )

    comparisons: list[dict[str, Any]] = []
    for apply_actor in client["applyactors"]:
        type_id = parse_int(apply_actor.get("type"))
        if type_id < HUB_NPC_TYPE_MIN or type_id > HUB_NPC_TYPE_MAX:
            continue
        network_id = parse_int(apply_actor.get("network_id"))
        applied_repactor = client["presentationactor_by_id"].get(
            network_id,
            apply_actor,
        )
        binding = client["binding_by_id"].get(network_id)
        if binding is None:
            continue
        local_actor = client["local_by_address"].get(parse_int(binding.get("address")))
        if local_actor is None:
            continue
        host_match = host_actor_by_network_id.get(network_id)
        host_repactor = host["repactor_by_id"].get(network_id, applied_repactor)
        host_actor, host_distance = host_match if host_match is not None else ({}, math.inf)

        row = {
            "network_id": str(network_id),
            "type": type_id,
            "host_match_distance": round(host_distance, 3) if math.isfinite(host_distance) else None,
            "host_address": host_actor.get("address", ""),
            "client_address": local_actor.get("address", ""),
            "variant_primary_match": host_actor.get("variant_primary") == local_actor.get("variant_primary"),
            "variant_secondary_match": host_actor.get("variant_secondary") == local_actor.get("variant_secondary"),
            "weapon_type_match": host_actor.get("weapon_type") == local_actor.get("weapon_type"),
            "selection_byte_match": host_actor.get("selection_byte") == local_actor.get("selection_byte"),
            "variant_tertiary_match": host_actor.get("variant_tertiary") == local_actor.get("variant_tertiary"),
            "drive_byte_matches_snapshot": local_actor.get("drive_byte") == applied_repactor.get("drive"),
            "drive_word_matches_snapshot": local_actor.get("drive_raw") == applied_repactor.get("drive_word"),
            "drive_raw_match": host_actor.get("drive_raw") == local_actor.get("drive_raw"),
            "walk_primary_match": host_actor.get("walk_primary") == local_actor.get("walk_primary"),
            "walk_secondary_match": host_actor.get("walk_secondary") == local_actor.get("walk_secondary"),
            "stride_scale_match": host_actor.get("stride_scale") == local_actor.get("stride_scale"),
            "render_rate_match": host_actor.get("render_rate") == local_actor.get("render_rate"),
            "render_phase_match": host_actor.get("render_phase") == local_actor.get("render_phase"),
            "host_variant_primary": host_actor.get("variant_primary", ""),
            "client_variant_primary": local_actor.get("variant_primary", ""),
            "host_drive_raw": host_actor.get("drive_raw", ""),
            "client_drive_raw": local_actor.get("drive_raw", ""),
            "snapshot_drive_word": applied_repactor.get("drive_word", ""),
            "snapshot_presentation_flags": applied_repactor.get("presentation_flags", ""),
            "host_render_phase": host_actor.get("render_phase", ""),
            "client_render_phase": local_actor.get("render_phase", ""),
        }
        expected_client_drive = parse_int(applied_repactor.get("drive_word"))
        if type_id in PHASE_ADVANCING_NPC_TYPES:
            expected_client_drive = advance_drive_phase(
                applied_repactor.get("drive_word"),
                client_presentation_age_ms,
            )
        phase_distance = drive_phase_distance(
            str(expected_client_drive), local_actor.get("drive_raw")
        )
        row["expected_client_drive"] = f"0x{expected_client_drive:08X}"
        row["drive_phase_distance"] = phase_distance
        row["drive_phase_within_tolerance"] = (
            phase_distance <= DRIVE_PHASE_TOLERANCE
            if client_apply_presentation_available
            and client_presentation_clock_valid
            else None
        )
        if type_id == STUDENT_TYPE_ID:
            row["variant_primary_match"] = (
                local_actor.get("variant_primary") == applied_repactor.get("variant_primary")
            )
            row["variant_secondary_match"] = (
                local_actor.get("variant_secondary") == applied_repactor.get("variant_secondary")
            )
            row["weapon_type_match"] = (
                local_actor.get("weapon_type") == applied_repactor.get("weapon_type")
            )
            row["selection_byte_match"] = (
                local_actor.get("selection_byte") == applied_repactor.get("selection_byte")
            )
            row["variant_tertiary_match"] = (
                local_actor.get("variant_tertiary") == applied_repactor.get("variant_tertiary")
            )
            row["student_color_match"] = (
                applied_repactor.get("student_color_190") == local_actor.get("student_color_190")
            )
            row["student_book_palette_match"] = (
                applied_repactor.get("student_book_palette_1c0") ==
                local_actor.get("student_book_palette_1c0")
            )
            row["student_book_palette_count_matches_snapshot"] = (
                parse_int(local_actor.get("student_book_palette_1c0", "").partition(":")[0]) ==
                parse_int(applied_repactor.get("student_book_palette_count"))
            )
            row["host_student_color_190"] = host_repactor.get("student_color_190", "")
            row["client_student_color_190"] = local_actor.get("student_color_190", "")
            row["host_student_book_palette_1c0"] = host_actor.get(
                "student_book_palette_1c0", host_repactor.get("student_book_palette_1c0", "")
            )
            row["client_student_book_palette_1c0"] = local_actor.get(
                "student_book_palette_1c0", ""
            )
        comparisons.append(row)

    student_rows = [row for row in comparisons if row["type"] == STUDENT_TYPE_ID]
    named_rows = [row for row in comparisons if row["type"] != STUDENT_TYPE_ID]

    def count_false(rows: list[dict[str, Any]], field: str) -> int:
        return sum(1 for row in rows if row.get(field) is False)

    summary = {
        "host_scene": host["scene_name"],
        "client_scene": client["scene_name"],
        "client_replicated_valid": client["replicated_valid"],
        "host_replicated_sequence": host["replicated_sequence"],
        "client_replicated_sequence": client["replicated_sequence"],
        "client_replicated_scene_epoch": client["replicated_scene_epoch"],
        "client_replicated_received_ms": client["replicated_received_ms"],
        "client_replicated_apply_valid": client["replicated_apply_valid"],
        "client_replicated_apply_sequence": client["replicated_apply_sequence"],
        "client_replicated_apply_scene_epoch": client["replicated_apply_scene_epoch"],
        "client_replicated_apply_presentation_sequence": client[
            "replicated_apply_presentation_sequence"
        ],
        "client_replicated_apply_presentation_scene_epoch": client[
            "replicated_apply_presentation_scene_epoch"
        ],
        "client_replicated_apply_presentation_received_ms": client[
            "replicated_apply_presentation_received_ms"
        ],
        "client_apply_actors_available": client_apply_actors_available,
        "client_applied_actor_count": len(client["applyactors"]),
        "client_apply_presentation_available": client_apply_presentation_available,
        "client_presentation_source_actor_count": len(
            client["presentationactors"]
        ),
        "client_presentation_clock_valid": client_presentation_clock_valid,
        "client_presentation_age_ms": client_presentation_age_ms,
        "client_replicated_applied_ms": client["replicated_applied_ms"],
        "client_replicated_actor_count": client["replicated_actor_count"],
        "client_replicated_total_count": client["replicated_total_count"],
        "client_replicated_truncated": client["replicated_truncated"],
        "client_replicated_local_actor_count": client[
            "replicated_local_actor_count"
        ],
        "client_replicated_matched_actor_count": client[
            "replicated_matched_actor_count"
        ],
        "client_replicated_created_actor_count": client[
            "replicated_created_actor_count"
        ],
        "client_replicated_created_actor_total_count": client[
            "replicated_created_actor_total_count"
        ],
        "client_replicated_removed_actor_count": client[
            "replicated_removed_actor_count"
        ],
        "client_replicated_removed_actor_total_count": client[
            "replicated_removed_actor_total_count"
        ],
        "client_replicated_failed_remove_actor_count": client[
            "replicated_failed_remove_actor_count"
        ],
        "client_replicated_failed_remove_actor_total_count": client[
            "replicated_failed_remove_actor_total_count"
        ],
        "compared_total": len(comparisons),
        "student_compared": len(student_rows),
        "student_variant_primary_mismatches": count_false(student_rows, "variant_primary_match"),
        "student_color_mismatches": count_false(student_rows, "student_color_match"),
        "student_book_palette_mismatches": count_false(
            student_rows, "student_book_palette_match"
        ),
        "student_book_palette_snapshot_count_mismatches": count_false(
            student_rows, "student_book_palette_count_matches_snapshot"
        ),
        "named_compared": len(named_rows),
        "named_drive_raw_mismatches": count_false(named_rows, "drive_raw_match"),
        "named_drive_phase_tolerance": DRIVE_PHASE_TOLERANCE,
        "named_drive_phase_out_of_tolerance": count_false(named_rows, "drive_phase_within_tolerance"),
        "named_drive_phase_max_distance": max(
            (int(row.get("drive_phase_distance", 0)) for row in named_rows),
            default=0,
        ),
        "named_drive_word_snapshot_mismatches": count_false(named_rows, "drive_word_matches_snapshot"),
        "named_render_phase_mismatches": count_false(named_rows, "render_phase_match"),
        "named_render_rate_mismatches": count_false(named_rows, "render_rate_match"),
        "named_variant_primary_mismatches": count_false(named_rows, "variant_primary_match"),
    }
    return {
        "summary": summary,
        "comparisons": comparisons,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--client",
        action="append",
        type=parse_client,
        help="Lua exec endpoint as NAME=PIPE. Defaults to local multiplayer host/client.",
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--interval", type=float, default=0.25)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--fail-on-divergence",
        action="store_true",
        help="Return non-zero when compared presentation fields diverge.",
    )
    args = parser.parse_args()
    if args.samples <= 0:
        parser.error("--samples must be positive")
    if args.interval < 0.0:
        parser.error("--interval cannot be negative")

    clients = args.client or list(DEFAULT_CLIENTS)
    samples: list[dict[str, Any]] = []
    all_clients_ok = True
    for sample_index in range(args.samples):
        results = run_all(clients, LUA_CAPTURE, args.timeout)
        all_clients_ok = all_clients_ok and all(
            result["returncode"] == 0 for result in results
        )
        values_by_name = {
            str(result["name"]): {
                str(k): str(v)
                for k, v in result.get("values", {}).items()
            }
            for result in results
            if isinstance(result.get("values"), dict)
        }
        if "host" not in values_by_name or "client" not in values_by_name:
            raise SystemExit("expected clients named 'host' and 'client'")
        samples.append({
            "clients": results,
            "comparison": compare_host_to_client(
                values_by_name["host"],
                values_by_name["client"],
            ),
        })
        if sample_index + 1 < args.samples and args.interval > 0.0:
            time.sleep(args.interval)

    results = samples[-1]["clients"]
    comparison = samples[-1]["comparison"]
    summaries = [sample["comparison"]["summary"] for sample in samples]
    aggregate = {
        "sample_count": len(samples),
        "all_client_calls_ok": all_clients_ok,
        "all_replicated_valid": all(
            bool(summary["client_replicated_valid"])
            for summary in summaries
        ),
        "all_apply_actors_available": all(
            bool(summary["client_apply_actors_available"])
            for summary in summaries
        ),
        "all_apply_presentation_available": all(
            bool(summary["client_apply_presentation_available"])
            for summary in summaries
        ),
        "all_presentation_clocks_valid": all(
            bool(summary["client_presentation_clock_valid"])
            for summary in summaries
        ),
        "any_replicated_truncated": any(
            bool(summary["client_replicated_truncated"])
            for summary in summaries
        ),
        "maximum_failed_remove_actor_count": max(
            int(summary["client_replicated_failed_remove_actor_count"])
            for summary in summaries
        ),
        "maximum_failed_remove_actor_total_count": max(
            int(summary["client_replicated_failed_remove_actor_total_count"])
            for summary in summaries
        ),
        "minimum_compared_total": min(
            int(summary["compared_total"])
            for summary in summaries
        ),
        "minimum_student_compared": min(
            int(summary["student_compared"])
            for summary in summaries
        ),
        "minimum_named_compared": min(
            int(summary["named_compared"])
            for summary in summaries
        ),
        "maximum_student_variant_primary_mismatches": max(
            int(summary["student_variant_primary_mismatches"])
            for summary in summaries
        ),
        "maximum_student_color_mismatches": max(
            int(summary["student_color_mismatches"])
            for summary in summaries
        ),
        "maximum_student_book_palette_mismatches": max(
            int(summary["student_book_palette_mismatches"])
            for summary in summaries
        ),
        "maximum_student_book_palette_snapshot_count_mismatches": max(
            int(summary["student_book_palette_snapshot_count_mismatches"])
            for summary in summaries
        ),
        "maximum_named_drive_phase_out_of_tolerance": max(
            int(summary["named_drive_phase_out_of_tolerance"])
            for summary in summaries
        ),
        "maximum_named_drive_phase_distance": max(
            int(summary["named_drive_phase_max_distance"])
            for summary in summaries
        ),
    }
    output = {
        "ok": all_clients_ok,
        "clients": results,
        "comparison": comparison,
        "samples": samples,
        "aggregate": aggregate,
    }
    RUNTIME_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_OUTPUT.write_text(json.dumps(output, indent=2, sort_keys=True), encoding="utf-8")

    if args.json:
        print(json.dumps(output, indent=2, sort_keys=True))
    else:
        print(json.dumps(aggregate, indent=2, sort_keys=True))
        print(f"wrote {RUNTIME_OUTPUT}")

    if not output["ok"]:
        return 1
    if args.fail_on_divergence:
        diverged = (
            not aggregate["all_replicated_valid"] or
            not aggregate["all_apply_actors_available"] or
            not aggregate["all_apply_presentation_available"] or
            not aggregate["all_presentation_clocks_valid"] or
            aggregate["any_replicated_truncated"] or
            aggregate["maximum_failed_remove_actor_count"] > 0 or
            aggregate["maximum_failed_remove_actor_total_count"] > 0 or
            aggregate["minimum_compared_total"] <= 0 or
            aggregate["minimum_student_compared"] <= 0 or
            aggregate["minimum_named_compared"] <= 0 or
            any(
                int(aggregate[field]) > 0
                for field in (
                    "maximum_student_variant_primary_mismatches",
                    "maximum_student_color_mismatches",
                    "maximum_student_book_palette_mismatches",
                    "maximum_student_book_palette_snapshot_count_mismatches",
                    "maximum_named_drive_phase_out_of_tolerance",
                )
            )
        )
        return 1 if diverged else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
