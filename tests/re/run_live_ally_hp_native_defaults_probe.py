#!/usr/bin/env python3
"""Live RE probe for native ally HP/MP defaults on clone materialization.

The probe targets the shared-hub standalone clone rail. It verifies that the
bot materializes through `WizardCloneFromSourceActor`, then checks the clone's
progression HP/MP fields against the native constructor globals recovered from
the staged binary.
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import cast_state_probe as csp  # noqa: E402


OUTPUT_PATH = ROOT / "runtime" / "live_ally_hp_native_defaults_probe.json"
RUNTIME_BINARY_LAYOUT_PATH = ROOT / "runtime/stage/.sdmod/config/binary-layout.ini"
STAGED_BINARY = ROOT / "runtime/stage/SolomonDark.exe"
NATIVE_WIZARD_DEFAULT_HP_GLOBAL_KEY = "wizard_default_hp"
NATIVE_WIZARD_DEFAULT_MP_GLOBAL_KEY = "wizard_default_mp"
BOT_NAME = "Native Ally HP Probe"


class LiveAllyHpProbeFailure(RuntimeError):
    pass


def read_runtime_layout_offset(name: str) -> int:
    text = RUNTIME_BINARY_LAYOUT_PATH.read_text(encoding="utf-8", errors="replace")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return int(value.strip(), 0)
    raise LiveAllyHpProbeFailure(f"Unable to find {name!r} in {RUNTIME_BINARY_LAYOUT_PATH}")


def read_pe_float_by_va(path: Path, virtual_address: int) -> float:
    data = path.read_bytes()
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise LiveAllyHpProbeFailure(f"not a PE image: {path}")
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe_offset:pe_offset + 4] != b"PE\0\0":
        raise LiveAllyHpProbeFailure(f"missing PE signature: {path}")
    number_of_sections = struct.unpack_from("<H", data, pe_offset + 6)[0]
    optional_header_size = struct.unpack_from("<H", data, pe_offset + 20)[0]
    optional_header = pe_offset + 24
    image_base = struct.unpack_from("<I", data, optional_header + 28)[0]
    rva = virtual_address - image_base
    section_offset = optional_header + optional_header_size
    for section_index in range(number_of_sections):
        header = section_offset + section_index * 40
        virtual_size, section_rva, raw_size, raw_offset = struct.unpack_from("<IIII", data, header + 8)
        section_size = max(virtual_size, raw_size)
        if section_rva <= rva < section_rva + section_size:
            return struct.unpack_from("<f", data, raw_offset + (rva - section_rva))[0]
    raise LiveAllyHpProbeFailure(f"virtual address 0x{virtual_address:X} is not mapped in {path}")


def native_defaults() -> dict[str, float]:
    hp_global = read_runtime_layout_offset(NATIVE_WIZARD_DEFAULT_HP_GLOBAL_KEY)
    mp_global = read_runtime_layout_offset(NATIVE_WIZARD_DEFAULT_MP_GLOBAL_KEY)
    return {
        "hp": read_pe_float_by_va(STAGED_BINARY, hp_global),
        "mp": read_pe_float_by_va(STAGED_BINARY, mp_global),
    }


def create_shared_hub_bot() -> int:
    output = csp.run_lua(
        f"""
local function emit(key, value)
  if value == nil then
    print(key .. '=')
  else
    print(key .. '=' .. tostring(value))
  end
end
if type(sd.bots.clear) == 'function' then
  sd.bots.clear()
end
local player = sd.player.get_state()
if type(player) ~= 'table' then
  emit('ok', false)
  emit('error', 'missing_player')
  return
end
local id = sd.bots.create({{
  name = {json.dumps(BOT_NAME)},
  profile = {{
    element_id = 1,
    discipline_id = 1,
    level = 1,
    experience = 0,
  }},
  scene = {{ kind = 'shared_hub' }},
  ready = true,
  heading = 90.0,
  position = {{
    x = (tonumber(player.x) or 0.0) + 96.0,
    y = tonumber(player.y) or 0.0,
  }},
}})
emit('ok', id ~= nil)
emit('bot_id', id)
""".strip()
    )
    values = csp.parse_key_values(output)
    if values.get("ok") != "true":
        raise LiveAllyHpProbeFailure(f"sd.bots.create failed: {values}")
    bot_id = csp.int_value(values, "bot_id")
    if bot_id == 0:
        raise LiveAllyHpProbeFailure(f"sd.bots.create returned invalid id: {values}")
    return bot_id


def query_bot_by_id(bot_id: int) -> dict[str, str]:
    hp_offset = read_runtime_layout_offset("progression_hp")
    max_hp_offset = read_runtime_layout_offset("progression_max_hp")
    mp_offset = read_runtime_layout_offset("progression_mp")
    max_mp_offset = read_runtime_layout_offset("progression_max_mp")
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local function emit(key, value)
  if value == nil then
    print(key .. '=')
  else
    print(key .. '=' .. tostring(value))
  end
end

local bot = sd.bots.get_state({bot_id})
if type(bot) ~= 'table' then
  local bots = sd.bots.get_state()
  if type(bots) == 'table' then
    for _, candidate in ipairs(bots) do
      if type(candidate) == 'table' and tonumber(candidate.id) == {bot_id} then
        bot = candidate
        break
      end
    end
  end
end

if type(bot) ~= 'table' then
  emit('available', false)
  return
end

emit('available', true)
for _, key in ipairs({{
  'id', 'name', 'actor_address', 'world_address',
  'progression_runtime_state_address', 'progression_handle_address',
  'entity_materialized', 'participant_kind', 'controller_kind',
  'gameplay_slot', 'actor_slot', 'hp', 'max_hp', 'mp', 'max_mp', 'x', 'y'
}}) do
  emit(key, bot[key])
end
emit('scene_kind', type(bot.scene) == 'table' and bot.scene.kind or nil)

local progression = tonumber(bot.progression_runtime_state_address) or 0
emit('raw.available', progression ~= 0)
if progression ~= 0 then
  emit('raw.hp', sd.debug.read_float(progression + {hp_offset}))
  emit('raw.max_hp', sd.debug.read_float(progression + {max_hp_offset}))
  emit('raw.mp', sd.debug.read_float(progression + {mp_offset}))
  emit('raw.max_mp', sd.debug.read_float(progression + {max_mp_offset}))
end
""".strip()
        )
    )


def wait_for_bot(bot_id: int, *, timeout_s: float = 30.0) -> dict[str, str]:
    deadline = time.time() + timeout_s
    last: dict[str, str] = {}
    while time.time() < deadline:
        last = query_bot_by_id(bot_id)
        if (
            last.get("available") == "true"
            and csp.int_value(last, "actor_address") != 0
            and csp.int_value(last, "progression_runtime_state_address") != 0
        ):
            return last
        time.sleep(0.25)
    raise LiveAllyHpProbeFailure(f"timed out waiting for bot materialization. Last={last}")


def require_close(label: str, actual: float, expected: float, *, tolerance: float = 0.01) -> None:
    if not math.isfinite(actual):
        raise LiveAllyHpProbeFailure(f"{label} is not finite: {actual}")
    if not math.isclose(actual, expected, rel_tol=0.0, abs_tol=tolerance):
        raise LiveAllyHpProbeFailure(f"{label} expected {expected}, got {actual}")


def sample_float(sample: dict[str, str], key: str) -> float:
    value = csp.float_value(sample, key)
    if not math.isfinite(value):
        raise LiveAllyHpProbeFailure(f"{key} is not finite in sample: {sample}")
    return value


def validate_sample(
    label: str,
    sample: dict[str, str],
    defaults: dict[str, float],
) -> None:
    if sample.get("available") != "true":
        raise LiveAllyHpProbeFailure(f"{label}: bot state unavailable: {sample}")
    if sample.get("entity_materialized") != "true":
        raise LiveAllyHpProbeFailure(f"{label}: bot is not materialized: {sample}")
    if sample.get("scene_kind") != "SharedHub":
        raise LiveAllyHpProbeFailure(f"{label}: expected SharedHub scene, got {sample.get('scene_kind')}")
    if csp.int_value(sample, "gameplay_slot") != -1:
        raise LiveAllyHpProbeFailure(f"{label}: expected standalone gameplay_slot=-1, got {sample}")

    for field in ("hp", "max_hp", "raw.hp", "raw.max_hp"):
        require_close(f"{label}.{field}", sample_float(sample, field), defaults["hp"])
    for field in ("mp", "max_mp", "raw.mp", "raw.max_mp"):
        require_close(f"{label}.{field}", sample_float(sample, field), defaults["mp"])

    hp = sample_float(sample, "hp")
    max_hp = sample_float(sample, "max_hp")
    mp = sample_float(sample, "mp")
    max_mp = sample_float(sample, "max_mp")
    require_close(f"{label}.hp_full_ratio", hp / max_hp, 1.0)
    require_close(f"{label}.mp_full_ratio", mp / max_mp, 1.0)


def validate_loader_log(log_tail: list[str]) -> None:
    joined = "\n".join(log_tail)
    required_tokens = (
        "rail=standalone_clone",
        "created standalone clone wizard actor",
        "gameplay_slot=-1",
    )
    missing = [token for token in required_tokens if token not in joined]
    if missing:
        raise LiveAllyHpProbeFailure("loader log is missing standalone clone token(s): " + ", ".join(missing))
    if "rail=gameplay_slot_bot" in joined:
        raise LiveAllyHpProbeFailure("shared-hub ally HP probe unexpectedly used gameplay_slot_bot rail")


def run_probe() -> dict[str, Any]:
    defaults = native_defaults()
    result: dict[str, Any] = {
        "launcher_freshness": csp.ensure_launcher_bundle_fresh(),
        "native_defaults": defaults,
        "navigation": [],
    }

    csp.stop_game()
    csp.clear_loader_log()
    csp.launch_game()
    process_id = csp.wait_for_game_process()
    csp.wait_for_lua_pipe()
    result["process_id"] = process_id
    result["navigation"].append({"step": "launch", "process_id": process_id})

    hub_flow = csp.drive_hub_flow(process_id, element="fire", discipline="mind", prefer_resume=False)
    result["navigation"].append({"step": "hub_ready", "flow": hub_flow})

    bot_id = create_shared_hub_bot()
    result["bot_id"] = bot_id
    first_sample = wait_for_bot(bot_id)
    time.sleep(1.0)
    settled_sample = query_bot_by_id(bot_id)
    log_tail = csp.tail_loader_log(240)

    validate_sample(
        "first",
        first_sample,
        defaults,
    )
    validate_sample(
        "settled",
        settled_sample,
        defaults,
    )
    validate_loader_log(log_tail)

    result["first_sample"] = first_sample
    result["settled_sample"] = settled_sample
    result["loader_log_tail"] = log_tail
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--json", action="store_true", help="Only print structured JSON.")
    parser.add_argument("--keep-running", action="store_true")
    args = parser.parse_args()

    exit_code = 0
    try:
        result = run_probe()
        result["passed"] = True
    except Exception as exc:  # noqa: BLE001 - probe preserves diagnostics in JSON.
        result = {
            "passed": False,
            "error": str(exc),
            "loader_log_tail": csp.tail_loader_log(240),
        }
        exit_code = 1
    finally:
        if not args.keep_running:
            csp.stop_game()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif result.get("passed"):
        print("PASS: live ally HP probe validated native defaults")
        print(f"Wrote {args.output}")
    else:
        print(f"FAIL: live ally HP probe: {result.get('error')}")
        print(f"Wrote {args.output}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
