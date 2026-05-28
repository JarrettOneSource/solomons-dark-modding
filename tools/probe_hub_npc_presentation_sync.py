#!/usr/bin/env python3
"""Probe host/client hub NPC presentation state that the current world snapshot misses."""

from __future__ import annotations

import argparse
import json
import math
import sys
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
    emit(prefix .. ".slot", actor.world_slot or -1)
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
      emit(prefix .. ".student_path_block_1c0", byte_string(address + 0x1C0, 64))
    end
  end
end
emit("actor.count", actor_index)

local replicated = sd.world.get_replicated_actors and sd.world.get_replicated_actors() or nil
emit("replicated.valid", replicated ~= nil)
emit("replicated.scene_kind", replicated and replicated.scene_kind or "")
emit("replicated.actor_count", replicated and replicated.actor_count or 0)
emit("replicated.total_count", replicated and replicated.actor_total_count or 0)
emit("replicated.truncated", replicated and replicated.truncated or false)
emit("replicated.binding_count", replicated and replicated.binding_count or 0)

if replicated ~= nil and replicated.actors ~= nil then
  for index, actor in ipairs(replicated.actors) do
    local prefix = "repactor." .. tostring(index)
    emit(prefix .. ".network_id", actor.network_actor_id or 0)
    emit(prefix .. ".type", actor.object_type_id or 0)
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


def build_client_snapshot(values: dict[str, str]) -> dict[str, Any]:
    actors = parse_indexed(values, "actor")
    repactors = parse_indexed(values, "repactor")
    bindings = parse_indexed(values, "binding")
    local_by_address = {parse_int(actor.get("address")): actor for actor in actors}
    binding_by_id = {
        parse_int(binding.get("network_id")): binding
        for binding in bindings
        if binding.get("matched") == "true" and binding.get("parked") != "true"
    }
    return {
        "scene_name": values.get("scene.name", ""),
        "scene_kind": values.get("scene.kind", ""),
        "actors": actors,
        "repactors": repactors,
        "bindings": bindings,
        "local_by_address": local_by_address,
        "binding_by_id": binding_by_id,
        "replicated_valid": values.get("replicated.valid") == "true",
        "replicated_actor_count": parse_int(values.get("replicated.actor_count")),
        "replicated_total_count": parse_int(values.get("replicated.total_count")),
        "replicated_truncated": values.get("replicated.truncated") == "true",
    }


def compare_host_to_client(host_values: dict[str, str], client_values: dict[str, str]) -> dict[str, Any]:
    host = build_client_snapshot(host_values)
    client = build_client_snapshot(client_values)
    host_actors: list[dict[str, str]] = host["actors"]
    used_host: set[int] = set()

    comparisons: list[dict[str, Any]] = []
    for repactor in client["repactors"]:
        type_id = parse_int(repactor.get("type"))
        if type_id < HUB_NPC_TYPE_MIN or type_id > HUB_NPC_TYPE_MAX:
            continue
        network_id = parse_int(repactor.get("network_id"))
        binding = client["binding_by_id"].get(network_id)
        if binding is None:
            continue
        local_actor = client["local_by_address"].get(parse_int(binding.get("address")))
        if local_actor is None:
            continue
        host_index, host_actor, host_distance = nearest_actor(
            host_actors,
            type_id,
            parse_float(repactor.get("x")),
            parse_float(repactor.get("y")),
            used_host,
        )
        if host_actor is None:
            continue
        used_host.add(host_index)

        row = {
            "network_id": str(network_id),
            "type": type_id,
            "host_match_distance": round(host_distance, 3),
            "host_address": host_actor.get("address", ""),
            "client_address": local_actor.get("address", ""),
            "variant_primary_match": host_actor.get("variant_primary") == local_actor.get("variant_primary"),
            "variant_secondary_match": host_actor.get("variant_secondary") == local_actor.get("variant_secondary"),
            "weapon_type_match": host_actor.get("weapon_type") == local_actor.get("weapon_type"),
            "selection_byte_match": host_actor.get("selection_byte") == local_actor.get("selection_byte"),
            "variant_tertiary_match": host_actor.get("variant_tertiary") == local_actor.get("variant_tertiary"),
            "drive_byte_matches_snapshot": local_actor.get("drive_byte") == repactor.get("drive"),
            "drive_word_matches_snapshot": local_actor.get("drive_raw") == repactor.get("drive_word"),
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
            "snapshot_drive_word": repactor.get("drive_word", ""),
            "snapshot_presentation_flags": repactor.get("presentation_flags", ""),
            "host_render_phase": host_actor.get("render_phase", ""),
            "client_render_phase": local_actor.get("render_phase", ""),
        }
        phase_distance = drive_phase_distance(host_actor.get("drive_raw"), local_actor.get("drive_raw"))
        row["drive_phase_distance"] = phase_distance
        row["drive_phase_within_tolerance"] = phase_distance <= DRIVE_PHASE_TOLERANCE
        if type_id == STUDENT_TYPE_ID:
            row["student_color_match"] = (
                host_actor.get("student_color_190") == local_actor.get("student_color_190")
            )
            row["student_path_block_match"] = (
                host_actor.get("student_path_block_1c0") == local_actor.get("student_path_block_1c0")
            )
            row["host_student_color_190"] = host_actor.get("student_color_190", "")
            row["client_student_color_190"] = local_actor.get("student_color_190", "")
        comparisons.append(row)

    student_rows = [row for row in comparisons if row["type"] == STUDENT_TYPE_ID]
    named_rows = [row for row in comparisons if row["type"] != STUDENT_TYPE_ID]

    def count_false(rows: list[dict[str, Any]], field: str) -> int:
        return sum(1 for row in rows if row.get(field) is False)

    summary = {
        "host_scene": host["scene_name"],
        "client_scene": client["scene_name"],
        "client_replicated_valid": client["replicated_valid"],
        "client_replicated_actor_count": client["replicated_actor_count"],
        "client_replicated_total_count": client["replicated_total_count"],
        "client_replicated_truncated": client["replicated_truncated"],
        "compared_total": len(comparisons),
        "student_compared": len(student_rows),
        "student_variant_primary_mismatches": count_false(student_rows, "variant_primary_match"),
        "student_color_mismatches": count_false(student_rows, "student_color_match"),
        "student_path_block_mismatches": count_false(student_rows, "student_path_block_match"),
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
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--fail-on-divergence",
        action="store_true",
        help="Return non-zero when compared presentation fields diverge.",
    )
    args = parser.parse_args()

    clients = args.client or list(DEFAULT_CLIENTS)
    results = run_all(clients, LUA_CAPTURE, args.timeout)
    values_by_name = {
        str(result["name"]): {str(k): str(v) for k, v in result.get("values", {}).items()}
        for result in results
        if isinstance(result.get("values"), dict)
    }
    if "host" not in values_by_name or "client" not in values_by_name:
        raise SystemExit("expected clients named 'host' and 'client'")

    comparison = compare_host_to_client(values_by_name["host"], values_by_name["client"])
    output = {
        "ok": all(result["returncode"] == 0 for result in results),
        "clients": results,
        "comparison": comparison,
    }
    RUNTIME_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_OUTPUT.write_text(json.dumps(output, indent=2, sort_keys=True), encoding="utf-8")

    if args.json:
        print(json.dumps(output, indent=2, sort_keys=True))
    else:
        print(json.dumps(comparison["summary"], indent=2, sort_keys=True))
        print(f"wrote {RUNTIME_OUTPUT}")

    if not output["ok"]:
        return 1
    if args.fail_on_divergence:
        summary = comparison["summary"]
        diverged = any(
            int(summary.get(field, 0)) > 0
            for field in (
                "student_variant_primary_mismatches",
                "student_color_mismatches",
                "named_drive_phase_out_of_tolerance",
            )
        )
        return 1 if diverged else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
