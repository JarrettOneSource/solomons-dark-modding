#!/usr/bin/env python3
"""Sample hub NPC/world actor state from multiple local multiplayer clients."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from multiplayer_lua_probe import DEFAULT_CLIENTS, parse_client, run_all  # noqa: E402


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

local function i32(address)
  return tonumber(sd.debug.read_i32(address)) or 0
end

local function flt(address)
  return tonumber(sd.debug.read_float(address)) or 0
end

local scene = sd.world.get_scene()
emit("scene.kind", scene and scene.kind or "")
emit("scene.name", scene and scene.name or "")
emit("scene.world", scene and hx(scene.world_address) or "0x00000000")
emit("rng.global_818b08", hx(u32(0x00818B08)))

local actors = sd.world.list_actors()
emit("actors.total", #actors)

local counts = {}
for _, actor in ipairs(actors) do
  local type_id = tonumber(actor.object_type_id) or 0
  counts[type_id] = (counts[type_id] or 0) + 1
end
for type_id, count in pairs(counts) do
  emit("count.type." .. tostring(type_id), count)
end

local student_index = 0
local named_index = 0
for _, actor in ipairs(actors) do
  local address = tonumber(actor.actor_address) or 0
  local type_id = tonumber(actor.object_type_id) or 0
  if type_id == 5002 then
    student_index = student_index + 1
    local prefix = "student." .. tostring(student_index)
    emit(prefix .. ".addr", hx(address))
    emit(prefix .. ".slot", actor.world_slot)
    emit(prefix .. ".x", f(actor.x))
    emit(prefix .. ".y", f(actor.y))
    emit(prefix .. ".radius", f(actor.radius))
    emit(prefix .. ".heading", f(flt(address + 0x6C)))
    emit(prefix .. ".speed", f(flt(address + 0x74)))
    emit(prefix .. ".move_x", f(flt(address + 0x158)))
    emit(prefix .. ".move_y", f(flt(address + 0x15C)))
    emit(prefix .. ".drive", actor.anim_drive_state)
    emit(prefix .. ".drive_raw", u32(address + 0x160))
    emit(prefix .. ".raw_168", hx(u32(address + 0x168)))
    emit(prefix .. ".student_f174", f(flt(address + 0x174)))
    emit(prefix .. ".student_f178", f(flt(address + 0x178)))
    emit(prefix .. ".student_selector_17c", i32(address + 0x17C))
    emit(prefix .. ".wander_scale_1b4", f(flt(address + 0x1B4)))
    emit(prefix .. ".wander_target_x_1b8", f(flt(address + 0x1B8)))
    emit(prefix .. ".wander_target_y_1bc", f(flt(address + 0x1BC)))
    emit(prefix .. ".path_variant_count_1c0", i32(address + 0x1C0))
    emit(prefix .. ".path_block_1c4", hx(u32(address + 0x1C4)))
    emit(prefix .. ".path_block_1d0", hx(u32(address + 0x1D0)))
    emit(prefix .. ".path_block_1e0", hx(u32(address + 0x1E0)))
    emit(prefix .. ".path_block_1f0", hx(u32(address + 0x1F0)))
    emit(prefix .. ".raw_21c", hx(u32(address + 0x21C)))
    emit(prefix .. ".raw_220", hx(u32(address + 0x220)))
    emit(prefix .. ".raw_224", hx(u32(address + 0x224)))
    emit(prefix .. ".raw_228", hx(u32(address + 0x228)))
    emit(prefix .. ".raw_22c", hx(u32(address + 0x22C)))
    emit(prefix .. ".raw_230", hx(u32(address + 0x230)))
    emit(prefix .. ".raw_234", hx(u32(address + 0x234)))
    emit(prefix .. ".raw_238", hx(u32(address + 0x238)))
    emit(prefix .. ".student_flag_23c", i32(address + 0x23C))
    emit(prefix .. ".student_state_240", i32(address + 0x240))
    emit(prefix .. ".student_state_244", i32(address + 0x244))
    emit(prefix .. ".student_state_248", i32(address + 0x248))
    emit(prefix .. ".student_state_24c", i32(address + 0x24C))
  elseif type_id >= 5001 and type_id <= 5008 then
    named_index = named_index + 1
    local prefix = "hub_actor." .. tostring(named_index)
    emit(prefix .. ".type", type_id)
    emit(prefix .. ".addr", hx(address))
    emit(prefix .. ".slot", actor.world_slot)
    emit(prefix .. ".x", f(actor.x))
    emit(prefix .. ".y", f(actor.y))
    emit(prefix .. ".drive", actor.anim_drive_state)
    emit(prefix .. ".raw_21c", hx(u32(address + 0x21C)))
  end
end
emit("students.total", student_index)
emit("hub_actors.total", named_index)
"""


def numeric(values: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        return float(values.get(key, default))
    except (TypeError, ValueError):
        return default


def integer(values: dict[str, str], key: str, default: int = 0) -> int:
    try:
        return int(float(values.get(key, default)))
    except (TypeError, ValueError):
        return default


def summarize_client(samples: list[dict[str, str]]) -> dict[str, object]:
    if not samples:
        return {"samples": 0}

    student_counts = [integer(sample, "students.total") for sample in samples]
    actor_totals = [integer(sample, "actors.total") for sample in samples]
    scenes = sorted({sample.get("scene.name", "") for sample in samples})

    changed_students = 0
    first = samples[0]
    last = samples[-1]
    for index in range(1, max(student_counts or [0]) + 1):
        prefix = f"student.{index}"
        if first.get(f"{prefix}.addr") != last.get(f"{prefix}.addr"):
            continue
        dx = numeric(last, f"{prefix}.x") - numeric(first, f"{prefix}.x")
        dy = numeric(last, f"{prefix}.y") - numeric(first, f"{prefix}.y")
        drive_changed = first.get(f"{prefix}.drive") != last.get(f"{prefix}.drive")
        motion_state_changed = (
            first.get(f"{prefix}.move_x") != last.get(f"{prefix}.move_x") or
            first.get(f"{prefix}.move_y") != last.get(f"{prefix}.move_y") or
            first.get(f"{prefix}.wander_target_x_1b8") != last.get(f"{prefix}.wander_target_x_1b8") or
            first.get(f"{prefix}.wander_target_y_1bc") != last.get(f"{prefix}.wander_target_y_1bc") or
            first.get(f"{prefix}.path_variant_count_1c0") != last.get(f"{prefix}.path_variant_count_1c0")
        )
        if dx * dx + dy * dy > 0.01 or drive_changed or motion_state_changed:
            changed_students += 1

    first_student_positions = []
    for index in range(1, min(student_counts[0], 8) + 1):
        prefix = f"student.{index}"
        first_student_positions.append(
            {
                "slot": first.get(f"{prefix}.slot", ""),
                "x": first.get(f"{prefix}.x", ""),
                "y": first.get(f"{prefix}.y", ""),
                "drive": first.get(f"{prefix}.drive", ""),
                "move_x": first.get(f"{prefix}.move_x", ""),
                "move_y": first.get(f"{prefix}.move_y", ""),
                "wander_target_x": first.get(f"{prefix}.wander_target_x_1b8", ""),
                "wander_target_y": first.get(f"{prefix}.wander_target_y_1bc", ""),
                "path_variant_count": first.get(f"{prefix}.path_variant_count_1c0", ""),
            }
        )

    return {
        "samples": len(samples),
        "scenes": scenes,
        "actor_totals": actor_totals,
        "student_counts": student_counts,
        "changed_students_over_window": changed_students,
        "first_student_positions": first_student_positions,
    }


def build_summary(results_by_sample: list[dict[str, object]]) -> dict[str, object]:
    by_client: dict[str, list[dict[str, str]]] = {}
    for sample in results_by_sample:
        for client in sample["clients"]:
            name = str(client["name"])
            values = client.get("values", {})
            if isinstance(values, dict):
                by_client.setdefault(name, []).append({str(k): str(v) for k, v in values.items()})

    client_summaries = {name: summarize_client(samples) for name, samples in by_client.items()}
    first_counts = {
        name: (samples[0].get("students.total", "") if samples else "")
        for name, samples in by_client.items()
    }
    first_actor_totals = {
        name: (samples[0].get("actors.total", "") if samples else "")
        for name, samples in by_client.items()
    }
    first_student_signatures = {
        name: [
            {
                "slot": samples[0].get(f"student.{index}.slot", ""),
                "x": samples[0].get(f"student.{index}.x", ""),
                "y": samples[0].get(f"student.{index}.y", ""),
                "drive": samples[0].get(f"student.{index}.drive", ""),
                "wander_target_x": samples[0].get(f"student.{index}.wander_target_x_1b8", ""),
                "wander_target_y": samples[0].get(f"student.{index}.wander_target_y_1bc", ""),
                "path_variant_count": samples[0].get(f"student.{index}.path_variant_count_1c0", ""),
            }
            for index in range(1, min(integer(samples[0], "students.total"), 8) + 1)
        ]
        for name, samples in by_client.items()
        if samples
    }
    student_signature_rows = {
        name: json.dumps(signature, sort_keys=True)
        for name, signature in first_student_signatures.items()
    }
    return {
        "clients": client_summaries,
        "first_sample_student_counts": first_counts,
        "first_sample_actor_totals": first_actor_totals,
        "first_sample_student_signatures": first_student_signatures,
        "student_count_diverged": len(set(first_counts.values())) > 1,
        "actor_total_diverged": len(set(first_actor_totals.values())) > 1,
        "student_state_diverged": len(set(student_signature_rows.values())) > 1,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--client",
        action="append",
        type=parse_client,
        help="Lua exec endpoint as NAME=PIPE. Defaults to local multiplayer host/client.",
    )
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--interval", type=float, default=0.4)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    clients = args.client or list(DEFAULT_CLIENTS)
    results_by_sample: list[dict[str, object]] = []
    for index in range(max(args.samples, 1)):
        results = run_all(clients, LUA_CAPTURE, args.timeout)
        results_by_sample.append({"index": index, "clients": results})
        if index + 1 < args.samples:
            time.sleep(max(args.interval, 0.0))

    output = {
        "ok": all(
            client["returncode"] == 0
            for sample in results_by_sample
            for client in sample["clients"]
        ),
        "sample_count": len(results_by_sample),
        "summary": build_summary(results_by_sample),
        "samples": results_by_sample,
    }

    if args.json:
        print(json.dumps(output, indent=2, sort_keys=True))
    else:
        print(json.dumps(output["summary"], indent=2, sort_keys=True))

    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
