#!/usr/bin/env python3
"""Trace retail RNG call sites for selected native skill-offer seeds."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import capture_skill_offer_100_rolls as capture  # noqa: E402
import record_native_sim_goldens as native_goldens  # noqa: E402
import record_progression_goldens as progression_goldens  # noqa: E402
from record_native_sim_goldens import CaptureFailure, OwnedSoloSession, require  # noqa: E402


TRACE_NAME = "offer_diff_rng_integer"
RESULT_TRACE_NAME = "offer_diff_rng_integer_result"
RNG_INTEGER = 0x00401170
RNG_INTEGER_RESULT = 0x004011E7
SEEDS = (929799, 510067, 96855)
OUTPUT = ROOT / "runtime" / "skill-offer-rng-call-trace.json"


def parse_trace(raw: str, seed: int) -> dict[str, object]:
    metadata: dict[str, str] = {}
    hits: list[dict[str, int]] = []
    result_hits: list[dict[str, int]] = []
    for line in raw.splitlines():
        if line.startswith("H|"):
            parts = line.split("|")
            hits.append({
                "index": int(parts[1]),
                "thread_id": int(parts[2]),
                "ecx": int(parts[3]),
                "bound": int(parts[4]),
                "sign_mode": int(parts[5]),
                "return_preferred": int(parts[6]),
            })
        elif line.startswith("R|"):
            parts = line.split("|")
            result_hits.append({
                "index": int(parts[1]),
                "result": int(parts[2]),
                "ecx": int(parts[3]),
                "thread_id": int(parts[4]),
            })
        elif "=" in line:
            key, value = line.split("=", 1)
            metadata[key] = value
    offer_hits = [
        hit for hit in hits
        if 0x0067CB70 <= hit["return_preferred"] <= 0x0067DF61
    ]
    count = int(metadata.get("option_count", "0"))
    return {
        "seed": seed,
        "armed": metadata.get("armed") == "true",
        "result_armed": metadata.get("result_armed") == "true",
        "roll_ok": metadata.get("roll_ok") == "true",
        "global_rng_address": int(metadata.get("global_rng_address", "0")),
        "option_ids": [int(metadata[f"option_{index}"]) for index in range(1, count + 1)],
        "all_hit_count": len(hits),
        "offer_hits": offer_hits,
        "result_hits": result_hits,
    }


def trace_seed(session: OwnedSoloSession, bot_id: int, seed: int) -> dict[str, object]:
    raw = session.lua(
        f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local bot = sd.bots.get_state({bot_id})
local progression = tonumber(bot and bot.progression_runtime_state_address) or 0
assert(progression ~= 0)
assert(sd.debug.write_i32(progression + 0x834, {seed}))
pcall(sd.debug.untrace_function, {RNG_INTEGER})
pcall(sd.debug.untrace_function, {RNG_INTEGER_RESULT})
sd.debug.clear_trace_hits('{TRACE_NAME}')
sd.debug.clear_trace_hits('{RESULT_TRACE_NAME}')
local memory = sd.debug.query_memory({RNG_INTEGER}) or {{}}
local resolved = tonumber(memory.resolved_address) or 0
local delta = resolved - {RNG_INTEGER}
local global_slot = sd.debug.resolve_game_address(0x00818B08)
local global_rng = global_slot and (sd.debug.read_u32(global_slot) or 0) or 0
emit('global_rng_address', global_rng)
emit('armed', sd.debug.trace_function({RNG_INTEGER}, '{TRACE_NAME}'))
emit('result_armed', sd.debug.trace_function(
  {RNG_INTEGER_RESULT},
  '{RESULT_TRACE_NAME}'
))
sd.debug.clear_trace_hits('{TRACE_NAME}')
sd.debug.clear_trace_hits('{RESULT_TRACE_NAME}')
emit('roll_ok', sd.bots.debug_sync_level_up({{
  level = {capture.TARGET_LEVEL}, experience = {capture.TARGET_EXPERIENCE}
}}))
local choices = sd.bots.get_skill_choices({bot_id}) or {{}}
emit('option_count', #(choices.options or {{}}))
for index, option in ipairs(choices.options or {{}}) do
  emit('option_' .. index, option.id)
end
local hits = sd.debug.get_trace_hits('{TRACE_NAME}') or {{}}
for index, hit in ipairs(hits) do
  print('H|' .. tostring(index) .. '|' .. tostring(hit.thread_id or 0) .. '|' ..
    tostring(hit.ecx or 0) .. '|' .. tostring(hit.arg0 or 0) .. '|' ..
    tostring(hit.arg1 or 0) .. '|' .. tostring((hit.ret or 0) - delta))
end
local results = sd.debug.get_trace_hits('{RESULT_TRACE_NAME}') or {{}}
for index, hit in ipairs(results) do
  print('R|' .. tostring(index) .. '|' .. tostring(hit.esi or 0) .. '|' ..
    tostring(hit.ecx or 0) .. '|' .. tostring(hit.thread_id or 0))
end
pcall(sd.debug.untrace_function, {RNG_INTEGER_RESULT})
pcall(sd.debug.untrace_function, {RNG_INTEGER})
""",
        timeout=30.0,
    )
    result = parse_trace(raw, seed)
    require(result["armed"] is True, f"RNG trace did not arm: {result}")
    require(result["result_armed"] is True, f"RNG result trace did not arm: {result}")
    require(result["result_hits"], f"RNG result trace did not capture: {result}")
    require(result["roll_ok"] is True, f"traced roll failed: {result}")
    require(len(result["option_ids"]) == 3, f"traced roll returned wrong option count: {result}")
    return result


def main() -> int:
    progression_goldens._powershell()
    native_goldens.RUNTIME_ROOT = Path("/mnt/c/sd-skill-offer-rng-trace-20260824-root")
    native_goldens.GAME_DIRECTORY = progression_goldens.GAME_DIRECTORY
    native_goldens.GAME_BINARY = progression_goldens.GAME_BINARY
    native_goldens.sha256_file = progression_goldens.windows_sha256
    os.environ["SDMOD_LUA_BOTS_ACTIVE"] = "none"
    forwarded = set(filter(None, os.environ.get("WSLENV", "").split(":")))
    forwarded.update({"SDMOD_LUA_BOTS_ACTIVE", "SDMOD_DISABLE_AUDIO", "SDMOD_ENABLE_AUDIO"})
    os.environ["WSLENV"] = ":".join(sorted(forwarded))

    session = OwnedSoloSession(
        instance="offer-rng-trace",
        ports=(52691, 52692),
        mod_id=capture.MOD_ID,
        participant_id="0x2000000000006A65",
        test_blank_boneyard=False,
        headless=True,
        quick_start_element="ether",
        quick_start_discipline="arcane",
    )
    cleanup: list[dict[str, object]] = []
    try:
        launch = session.launch()
        session.wait_for_pipe()
        session.wait_for_scene("hub")
        session.values("sd.bots.clear(); print('ok=true')")
        local_state = capture.capture_progression(session, None)
        bot_id = capture.create_standard_bot(session)
        capture.normalize_bot_to_local(session, bot_id, local_state)
        setup = session.values(
            f"""
print('ok=' .. tostring(sd.bots.debug_sync_level_up({{
  level = {capture.TARGET_LEVEL}, experience = {capture.TARGET_EXPERIENCE}
}})))
"""
        )
        require(setup.get("ok") == "true", f"level setup failed: {setup}")
        traces = [trace_seed(session, bot_id, seed) for seed in SEEDS]
        cleanup = session.close()
        require(len(cleanup) == 1, f"trace cleanup did not stop one process: {cleanup}")
        document = {
            "schema": "solomon-dark-skill-offer-rng-trace-v1",
            "captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "retail_binary_sha256": progression_goldens.windows_sha256(
                progression_goldens.GAME_BINARY
            ),
            "launch": launch,
            "cleanup": cleanup,
            "traces": traces,
        }
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"ok": True, "output": str(OUTPUT), "traces": traces}, indent=2))
        return 0
    finally:
        if session.process_ids:
            session.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CaptureFailure as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
