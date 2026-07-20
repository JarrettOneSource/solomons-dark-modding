#!/usr/bin/env python3
"""Sample named hub NPC memory fields across host/client for serializer decisions."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from multiplayer_lua_probe import DEFAULT_CLIENTS, parse_client, run_all  # noqa: E402


RUNTIME_OUTPUT = ROOT / "runtime" / "named_hub_npc_field_probe.json"

NAMED_TYPES: dict[int, dict[str, Any]] = {
    0x1389: {"name": "witch", "size": 0x1C0, "ctor": "FUN_005018d0"},
    0x138B: {"name": "annal", "size": 0x174, "ctor": "FUN_00502120"},
    0x138C: {"name": "potion_guy", "size": 0x180, "ctor": "FUN_005023a0"},
    0x138D: {"name": "scavenger", "size": 0x174, "ctor": "FUN_005024c0"},
    0x138F: {"name": "enforcer", "size": 0x180, "ctor": "FUN_00502450"},
    0x1390: {"name": "teacher", "size": 0x178, "ctor": "FUN_00502570"},
}

ALIGNED_OFFSETS = tuple(range(0x120, 0x264, 4))
BYTE_OFFSETS = (0x23C, 0x23D, 0x23E, 0x23F, 0x240)

OFFSET_NAMES: dict[int, str] = {
    0x138: "render_drive_flags",
    0x158: "animation_config_word0",
    0x15C: "animation_drive_parameter",
    0x160: "animation_drive_state_word",
    0x174: "hub_visual_source_kind",
    0x178: "hub_visual_source_profile",
    0x1BC: "animation_move_duration_ticks",
    0x1C0: "source_profile_56_mirror",
    0x1C4: "magic_shield_absorb_remaining",
    0x1C8: "magic_shield_absorb_capacity",
    0x1CC: "magic_shield_explosion_fraction",
    0x1D0: "magic_shield_hit_flash",
    0x1F0: "render_drive_idle_bob",
    0x218: "move_step_scale",
    0x21C: "animation_selection_state",
    0x220: "walk_cycle_primary",
    0x224: "walk_cycle_secondary",
    0x228: "render_drive_stride_scale",
    0x22C: "render_frame_state",
    0x234: "render_advance_rate",
    0x238: "render_advance_phase",
    0x23C: "render_variant_primary",
    0x23D: "render_variant_secondary",
    0x23E: "render_weapon_type",
    0x23F: "render_selection_byte",
    0x240: "render_variant_tertiary",
}


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

local named = {
  [0x1389] = {name = "witch", size = 0x1C0, ctor = "FUN_005018d0"},
  [0x138B] = {name = "annal", size = 0x174, ctor = "FUN_00502120"},
  [0x138C] = {name = "potion_guy", size = 0x180, ctor = "FUN_005023a0"},
  [0x138D] = {name = "scavenger", size = 0x174, ctor = "FUN_005024c0"},
  [0x138F] = {name = "enforcer", size = 0x180, ctor = "FUN_00502450"},
  [0x1390] = {name = "teacher", size = 0x178, ctor = "FUN_00502570"},
}

local aligned_offsets = {
  0x120, 0x124, 0x128, 0x12C, 0x130, 0x134, 0x138, 0x13C,
  0x140, 0x144, 0x148, 0x14C, 0x150, 0x154, 0x158, 0x15C,
  0x160, 0x164, 0x168, 0x16C, 0x170, 0x174, 0x178, 0x17C,
  0x180, 0x184, 0x188, 0x18C, 0x190, 0x194, 0x198, 0x19C,
  0x1A0, 0x1A4, 0x1A8, 0x1AC, 0x1B0, 0x1B4, 0x1B8, 0x1BC,
  0x1C0, 0x1C4, 0x1C8, 0x1CC, 0x1D0, 0x1D4, 0x1D8, 0x1DC,
  0x1E0, 0x1E4, 0x1E8, 0x1EC, 0x1F0, 0x1F4, 0x1F8, 0x1FC,
  0x200, 0x204, 0x208, 0x20C, 0x210, 0x214, 0x218, 0x21C,
  0x220, 0x224, 0x228, 0x22C, 0x230, 0x234, 0x238, 0x23C,
  0x240, 0x244, 0x248, 0x24C, 0x250, 0x254, 0x258, 0x25C,
  0x260,
}

local byte_offsets = {0x23C, 0x23D, 0x23E, 0x23F, 0x240}

local scene = sd.world.get_scene()
emit("scene.name", scene and scene.name or "")
emit("scene.kind", scene and scene.kind or "")

local actors = sd.world.list_actors() or {}
for _, actor in ipairs(actors) do
  local address = tonumber(actor.actor_address) or 0
  local type_id = tonumber(actor.object_type_id) or 0
  local type_info = named[type_id]
  if address ~= 0 and type_info ~= nil then
    local prefix = string.format("type.%04X", type_id)
    emit(prefix .. ".name", type_info.name)
    emit(prefix .. ".size", hx(type_info.size))
    emit(prefix .. ".ctor", type_info.ctor)
    emit(prefix .. ".address", hx(address))
    emit(prefix .. ".x", f(actor.x))
    emit(prefix .. ".y", f(actor.y))
    emit(prefix .. ".heading", f(flt(address + 0x6C)))
    emit(prefix .. ".drive_byte", u8(address + 0x160))
    emit(prefix .. ".drive_word", hx(u32(address + 0x160)))
    for _, offset in ipairs(aligned_offsets) do
      if offset + 4 <= type_info.size then
        emit(prefix .. string.format(".u32_%03X", offset), hx(u32(address + offset)))
      end
    end
    for _, offset in ipairs(byte_offsets) do
      if offset < type_info.size then
        emit(prefix .. string.format(".u8_%03X", offset), u8(address + offset))
      end
    end
  end
end
"""


def parse_int(value: str | None, default: int = 0) -> int:
    if value is None:
        return default
    try:
        if value.startswith("0x") or value.startswith("0X"):
            return int(value, 16)
        return int(float(value))
    except (TypeError, ValueError):
        return default


def unique_values(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def phase_distance(left: str | None, right: str | None) -> int:
    left_phase = parse_int(left) & 0xFFFF
    right_phase = parse_int(right) & 0xFFFF
    delta = (left_phase - right_phase) & 0xFFFF
    if delta > 0x7FFF:
        delta = 0x10000 - delta
    return delta


def field_label(field: str) -> str:
    if field.startswith("u32_") or field.startswith("u8_"):
        try:
            offset = int(field[4:], 16)
        except ValueError:
            return field
        name = OFFSET_NAMES.get(offset)
        if name is not None:
            return f"{field}:{name}"
    return field


def capture_once(clients: list[tuple[str, str]], timeout: float) -> dict[str, Any]:
    results = run_all(clients, LUA_CAPTURE, timeout)
    return {
        "ok": all(result["returncode"] == 0 for result in results),
        "clients": results,
        "values_by_client": {
            str(result["name"]): {str(k): str(v) for k, v in result.get("values", {}).items()}
            for result in results
            if isinstance(result.get("values"), dict)
        },
    }


def collect_type_values(
    samples: list[dict[str, Any]],
    client_name: str,
    type_id: int,
    field: str,
) -> list[str]:
    key = f"type.{type_id:04X}.{field}"
    values: list[str] = []
    for sample in samples:
        by_client = sample.get("values_by_client", {})
        if not isinstance(by_client, dict):
            continue
        values_for_client = by_client.get(client_name, {})
        if not isinstance(values_for_client, dict):
            continue
        value = values_for_client.get(key)
        if value is not None:
            values.append(str(value))
    return values


def summarize_field(samples: list[dict[str, Any]], type_id: int, field: str) -> dict[str, Any]:
    host_values = collect_type_values(samples, "host", type_id, field)
    client_values = collect_type_values(samples, "client", type_id, field)
    pair_count = min(len(host_values), len(client_values))
    pair_matches = sum(1 for index in range(pair_count) if host_values[index] == client_values[index])
    summary: dict[str, Any] = {
        "field": field,
        "label": field_label(field),
        "samples": pair_count,
        "host_unique": unique_values(host_values),
        "client_unique": unique_values(client_values),
        "host_changed": len(unique_values(host_values)) > 1,
        "client_changed": len(unique_values(client_values)) > 1,
        "pair_matches": pair_matches,
        "all_pairs_match": pair_count > 0 and pair_matches == pair_count,
    }
    if field in ("drive_word", "u32_160"):
        distances = [
            phase_distance(host_values[index], client_values[index])
            for index in range(pair_count)
        ]
        summary["phase_distances"] = distances
        summary["max_phase_distance"] = max(distances, default=0)
    return summary


def summarize_type(samples: list[dict[str, Any]], type_id: int) -> dict[str, Any]:
    fields = ["address", "x", "y", "heading", "drive_byte", "drive_word"]
    fields.extend(f"u32_{offset:03X}" for offset in ALIGNED_OFFSETS)
    fields.extend(f"u8_{offset:03X}" for offset in BYTE_OFFSETS)
    field_summaries = [summarize_field(samples, type_id, field) for field in fields]

    host_present = bool(collect_type_values(samples, "host", type_id, "address"))
    client_present = bool(collect_type_values(samples, "client", type_id, "address"))
    changed_fields = [
        field["label"]
        for field in field_summaries
        if field["host_changed"] or field["client_changed"]
    ]
    divergent_static_fields = [
        field["label"]
        for field in field_summaries
        if field["samples"] > 0
        and not field["host_changed"]
        and not field["client_changed"]
        and not field["all_pairs_match"]
    ]
    exact_fields = [
        field["label"]
        for field in field_summaries
        if field["all_pairs_match"]
    ]
    drive_summary = next(
        field for field in field_summaries if field["field"] == "drive_word"
    )
    return {
        "type_id": type_id,
        "type_hex": f"0x{type_id:04X}",
        "name": str(NAMED_TYPES[type_id]["name"]),
        "size": f"0x{int(NAMED_TYPES[type_id]['size']):X}",
        "ctor": str(NAMED_TYPES[type_id]["ctor"]),
        "host_present": host_present,
        "client_present": client_present,
        "drive_word": drive_summary,
        "changed_fields": changed_fields,
        "divergent_static_fields": divergent_static_fields,
        "exact_fields": exact_fields,
        "fields": field_summaries,
    }


def summarize(samples: list[dict[str, Any]]) -> dict[str, Any]:
    type_summaries = {
        f"0x{type_id:04X}": summarize_type(samples, type_id)
        for type_id in NAMED_TYPES
    }
    moving_drive_types = [
        type_summary["type_hex"]
        for type_summary in type_summaries.values()
        if type_summary["drive_word"]["host_changed"]
    ]
    max_drive_phase_distance = max(
        (
            int(type_summary["drive_word"].get("max_phase_distance", 0))
            for type_summary in type_summaries.values()
        ),
        default=0,
    )
    return {
        "sample_count": len(samples),
        "all_samples_ok": all(bool(sample.get("ok")) for sample in samples),
        "moving_drive_types": moving_drive_types,
        "max_drive_phase_distance": max_drive_phase_distance,
        "types": type_summaries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--client",
        action="append",
        type=parse_client,
        help="Lua exec endpoint as NAME=PIPE. Defaults to local multiplayer host/client.",
    )
    parser.add_argument("--samples", type=int, default=8)
    parser.add_argument("--interval", type=float, default=0.2)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    clients = args.client or list(DEFAULT_CLIENTS)
    samples: list[dict[str, Any]] = []
    for index in range(max(1, args.samples)):
        sample = capture_once(clients, args.timeout)
        sample["sample_index"] = index
        samples.append(sample)
        if index + 1 < args.samples:
            time.sleep(max(0.0, args.interval))

    analysis = summarize(samples)
    output = {
        "ok": analysis["all_samples_ok"],
        "analysis": analysis,
        "samples": samples,
    }
    RUNTIME_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_OUTPUT.write_text(json.dumps(output, indent=2, sort_keys=True), encoding="utf-8")

    if args.json:
        print(json.dumps(output, indent=2, sort_keys=True))
    else:
        compact = {
            "ok": output["ok"],
            "sample_count": analysis["sample_count"],
            "moving_drive_types": analysis["moving_drive_types"],
            "max_drive_phase_distance": analysis["max_drive_phase_distance"],
            "type_summaries": {
                type_hex: {
                    "name": type_summary["name"],
                    "drive_host_changed": type_summary["drive_word"]["host_changed"],
                    "drive_max_phase_distance": type_summary["drive_word"].get("max_phase_distance", 0),
                    "changed_fields": type_summary["changed_fields"],
                    "divergent_static_field_count": len(type_summary["divergent_static_fields"]),
                }
                for type_hex, type_summary in analysis["types"].items()
            },
            "output": str(RUNTIME_OUTPUT),
        }
        print(json.dumps(compact, indent=2, sort_keys=True))
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
