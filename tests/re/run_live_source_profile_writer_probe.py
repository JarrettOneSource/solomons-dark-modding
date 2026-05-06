#!/usr/bin/env python3
"""Live writer/trace probe for native-derived clone-source seeding.

This complements ``run_live_source_profile_negative_probe.py``. The negative
probe proves finalized actors do not keep a reusable ``actor+0x178`` pointer.
This probe arms layout-backed native traces before player creation and keeps a
write watch on the finalized player actor source-profile window while a bot is
materialized. A passing run proves the observed runtime uses the blank
source-actor constructor plus native-derived source-profile staging, with no
hardcoded element color table and no finalized actor source-profile writer.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import cast_state_probe as csp  # noqa: E402


OUTPUT_PATH = ROOT / "runtime" / "live_source_profile_writer_probe.json"
BOT_NAME = "Source Profile Writer Probe"
PLAYER_SOURCE_WATCH = "source_profile_writer_player_source_window"

SOURCE_KIND_OFFSET = csp.read_runtime_layout_offset("actor_hub_visual_source_kind")
SOURCE_PROFILE_OFFSET = csp.read_runtime_layout_offset("actor_hub_visual_source_profile")
SOURCE_AUX_OFFSET = csp.read_runtime_layout_offset("actor_hub_visual_source_aux_pointer")

LOG_REQUIRED_TOKENS = (
    "native_derived_visual_seed_before",
    "native_derived_visual_seed_after",
    "native-derived source profile",
    "native-derived clone-source seeded",
    "clone_source_ready",
)


class LiveSourceProfileWriterFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class TraceSpec:
    name: str
    layout_key: str
    required: bool


TRACE_SPECS = (
    TraceSpec("player_actor_ctor", "player_actor_ctor", False),
    TraceSpec("player_appearance_apply_choice", "player_appearance_apply_choice", False),
    TraceSpec("source_profile_actor174_candidate_setup", "source_profile_actor174_candidate_setup", False),
    TraceSpec("source_actor_ctor", "source_actor_ctor", True),
    TraceSpec("actor_build_render_descriptor_from_source", "actor_build_render_descriptor_from_source", True),
    TraceSpec("wizard_clone_from_source_actor", "wizard_clone_from_source_actor", True),
)


def trace_specs_lua_table() -> str:
    rows = []
    for spec in TRACE_SPECS:
        rows.append(
            "{name="
            + json.dumps(spec.name)
            + ", address="
            + str(csp.read_runtime_layout_offset(spec.layout_key))
            + "}"
        )
    return "{" + ",".join(rows) + "}"


def arm_traces() -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local specs = {trace_specs_lua_table()}
local function emit(key, value)
  if value == nil then
    print(key .. '=')
  else
    print(key .. '=' .. tostring(value))
  end
end
for _, spec in ipairs(specs) do
  pcall(sd.debug.untrace_function, spec.address)
  sd.debug.clear_trace_hits(spec.name)
  local mem = sd.debug.query_memory(spec.address)
  emit('trace.' .. spec.name .. '.requested', spec.address)
  emit('trace.' .. spec.name .. '.resolved', mem and mem.resolved_address or 0)
  emit('trace.' .. spec.name .. '.executable', mem and mem.executable or false)
  emit('trace.' .. spec.name .. '.armed', sd.debug.trace_function(spec.address, spec.name))
  emit('trace.' .. spec.name .. '.last_error', sd.debug.get_last_error())
end
""".strip()
        )
    )


def clear_traces() -> None:
    csp.run_lua(
        "\n".join(
            [
                f"pcall(sd.debug.untrace_function, {csp.read_runtime_layout_offset(spec.layout_key)})\n"
                f"sd.debug.clear_trace_hits({json.dumps(spec.name)})"
                for spec in TRACE_SPECS
            ]
        )
    )


def query_trace_hits() -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local specs = {trace_specs_lua_table()}
local function emit(key, value)
  if value == nil then
    print(key .. '=')
  else
    print(key .. '=' .. tostring(value))
  end
end
for _, spec in ipairs(specs) do
  local hits = sd.debug.get_trace_hits(spec.name) or {{}}
  emit('trace.' .. spec.name .. '.count', #hits)
  for i = 1, math.min(#hits, 4) do
    local hit = hits[i]
    for _, key in ipairs({{
      'requested_address','resolved_address','thread_id','eax','ecx','edx',
      'ebx','esi','edi','ebp','esp_before_pushad','ret','arg0','arg1','arg2'
    }}) do
      emit('trace.' .. spec.name .. '.hit.' .. i .. '.' .. key, hit[key])
    end
  end
end
""".strip()
        )
    )


def query_player_visual_state() -> dict[str, str]:
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
local player = sd.player and sd.player.get_state and sd.player.get_state()
emit('available', type(player) == 'table')
if type(player) == 'table' then
  for _, key in ipairs({{
    'actor_address', 'hub_visual_source_kind',
    'hub_visual_source_profile_address',
    'render_subject_hub_visual_source_kind',
    'render_subject_hub_visual_source_profile_address'
  }}) do
    emit(key, player[key])
  end
  local actor = tonumber(player.actor_address) or 0
  emit('raw.actor_address', actor)
  if actor ~= 0 then
    emit('raw.source_kind', sd.debug.read_i32(actor + {SOURCE_KIND_OFFSET}))
    emit('raw.source_profile', sd.debug.read_ptr(actor + {SOURCE_PROFILE_OFFSET}))
    emit('raw.source_aux', sd.debug.read_ptr(actor + {SOURCE_AUX_OFFSET}))
  end
end
""".strip()
        )
    )


def wait_for_player_visual_state(label: str, *, timeout_s: float = 12.0) -> dict[str, str]:
    deadline = time.time() + timeout_s
    last: dict[str, str] = {}
    while time.time() < deadline:
        last = query_player_visual_state()
        if last.get("available") == "true" and csp.int_value(last, "actor_address") != 0:
            return last
        time.sleep(0.25)
    raise LiveSourceProfileWriterFailure(f"{label}: timed out waiting for player visual state. Last={last}")


def set_lua_tick_enabled(enabled: bool) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
lua_bots_disable_tick = {"false" if enabled else "true"}
print('ok=true')
print('lua_bots_disable_tick=' .. tostring(lua_bots_disable_tick))
""".strip()
        )
    )


def clear_bots() -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            """
if sd.bots and sd.bots.clear then
  sd.bots.clear()
end
local count = sd.bots and sd.bots.get_count and sd.bots.get_count() or 0
print('ok=true')
print('count=' .. tostring(count))
""".strip()
        )
    )


def arm_player_source_watch(actor_address: int) -> dict[str, str]:
    watch_address = actor_address + SOURCE_KIND_OFFSET
    return csp.parse_key_values(
        csp.run_lua(
            f"""
pcall(sd.debug.unwatch, {json.dumps(PLAYER_SOURCE_WATCH)})
sd.debug.clear_write_hits({json.dumps(PLAYER_SOURCE_WATCH)})
local function emit(key, value)
  if value == nil then
    print(key .. '=')
  else
    print(key .. '=' .. tostring(value))
  end
end
emit('actor_address', {actor_address})
emit('watch_address', {watch_address})
emit('watch_size', 12)
emit('watch_ok', sd.debug.watch_write({json.dumps(PLAYER_SOURCE_WATCH)}, {watch_address}, 12))
emit('last_error', sd.debug.get_last_error())
""".strip()
        )
    )


def query_player_source_write_hits() -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local hits = sd.debug.get_write_hits({json.dumps(PLAYER_SOURCE_WATCH)}) or {{}}
local function emit(key, value)
  if value == nil then
    print(key .. '=')
  else
    print(key .. '=' .. tostring(value))
  end
end
emit('count', #hits)
for i = 1, math.min(#hits, 32) do
  local hit = hits[i]
  for _, key in ipairs({{
    'requested_address','resolved_address','base_address','value_address',
    'access_address','thread_id','eip','esp','ebp','eax','ecx','edx',
    'ret','arg0','arg1','arg2','before_bytes_hex','after_bytes_hex'
  }}) do
    emit('hit.' .. i .. '.' .. key, hit[key])
  end
end
""".strip()
        )
    )


def clear_player_source_watch() -> None:
    csp.run_lua(
        f"""
pcall(sd.debug.unwatch, {json.dumps(PLAYER_SOURCE_WATCH)})
sd.debug.clear_write_hits({json.dumps(PLAYER_SOURCE_WATCH)})
""".strip()
    )


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
    element_id = 4,
    discipline_id = 1,
    level = 1,
    experience = 0,
  }},
  scene = {{ kind = 'shared_hub' }},
  ready = true,
  heading = 90.0,
  position = {{
    x = (tonumber(player.x) or 0.0) + 128.0,
    y = tonumber(player.y) or 0.0,
  }},
}})
emit('ok', id ~= nil)
emit('bot_id', id)
""".strip()
    )
    values = csp.parse_key_values(output)
    if values.get("ok") != "true":
        raise LiveSourceProfileWriterFailure(f"sd.bots.create failed: {values}")
    bot_id = csp.int_value(values, "bot_id")
    if bot_id == 0:
        raise LiveSourceProfileWriterFailure(f"sd.bots.create returned invalid id: {values}")
    return bot_id


def query_bot_visual_state(bot_id: int) -> dict[str, str]:
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
emit('available', type(bot) == 'table')
if type(bot) == 'table' then
  for _, key in ipairs({{
    'actor_address', 'entity_materialized', 'hub_visual_source_kind',
    'hub_visual_source_profile_address',
    'render_subject_hub_visual_source_kind',
    'render_subject_hub_visual_source_profile_address'
  }}) do
    emit(key, bot[key])
  end
  local actor = tonumber(bot.actor_address) or 0
  emit('raw.actor_address', actor)
  if actor ~= 0 then
    emit('raw.source_kind', sd.debug.read_i32(actor + {SOURCE_KIND_OFFSET}))
    emit('raw.source_profile', sd.debug.read_ptr(actor + {SOURCE_PROFILE_OFFSET}))
    emit('raw.source_aux', sd.debug.read_ptr(actor + {SOURCE_AUX_OFFSET}))
  end
end
""".strip()
        )
    )


def wait_for_bot(bot_id: int, *, timeout_s: float = 30.0) -> dict[str, str]:
    deadline = time.time() + timeout_s
    last: dict[str, str] = {}
    while time.time() < deadline:
        last = query_bot_visual_state(bot_id)
        if (
            last.get("available") == "true"
            and last.get("entity_materialized") == "true"
            and csp.int_value(last, "actor_address") != 0
        ):
            return last
        time.sleep(0.25)
    raise LiveSourceProfileWriterFailure(f"timed out waiting for bot materialization. Last={last}")


def require_trace_armed(arm_state: dict[str, str], spec: TraceSpec) -> None:
    if not spec.required:
        return
    if arm_state.get(f"trace.{spec.name}.armed") != "true":
        raise LiveSourceProfileWriterFailure(
            f"required trace failed to arm: {spec.name}: {arm_state}"
        )


def require_trace_hit(trace_hits: dict[str, str], trace_name: str) -> None:
    count = csp.int_value(trace_hits, f"trace.{trace_name}.count")
    if count <= 0:
        raise LiveSourceProfileWriterFailure(f"expected trace hits for {trace_name}, got {count}")


def require_zero_source_profile(sample: dict[str, str], label: str) -> None:
    if sample.get("available") != "true":
        raise LiveSourceProfileWriterFailure(f"{label}: state unavailable: {sample}")
    if csp.int_value(sample, "actor_address") == 0:
        raise LiveSourceProfileWriterFailure(f"{label}: missing actor address: {sample}")
    for key in (
        "hub_visual_source_profile_address",
        "render_subject_hub_visual_source_profile_address",
        "raw.source_profile",
    ):
        if key in sample and csp.int_value(sample, key) != 0:
            raise LiveSourceProfileWriterFailure(f"{label}: expected {key}=0: {sample}")


def collect_log_evidence(log_tail: list[str]) -> dict[str, Any]:
    joined = "\n".join(log_tail)
    missing = [token for token in LOG_REQUIRED_TOKENS if token not in joined]
    if missing:
        raise LiveSourceProfileWriterFailure(
            "loader log is missing native clone-source lifecycle token(s): " + ", ".join(missing)
        )
    native_visual_sources = sorted(
        {
            "0x" + match.group(1).upper()
            for line in log_tail
            for match in re.finditer(r"native_visual_actor=0x([0-9A-Fa-f]+)", line)
            if int(match.group(1), 16) != 0
        }
    )
    if not native_visual_sources:
        raise LiveSourceProfileWriterFailure("loader log did not capture a native visual source actor")
    return {
        "required_tokens": list(LOG_REQUIRED_TOKENS),
        "native_visual_source_actors": native_visual_sources,
        "source_lines": [
            line
            for line in log_tail
            if "native_derived_visual_seed_" in line
            or "native-derived" in line
            or "clone_source_ready" in line
        ][-60:],
    }


def run_probe() -> dict[str, Any]:
    result: dict[str, Any] = {
        "launcher_freshness": csp.ensure_launcher_bundle_fresh(),
        "layout_offsets": {
            "actor_hub_visual_source_kind": SOURCE_KIND_OFFSET,
            "actor_hub_visual_source_profile": SOURCE_PROFILE_OFFSET,
            "actor_hub_visual_source_aux_pointer": SOURCE_AUX_OFFSET,
        },
        "trace_specs": [
            {
                "name": spec.name,
                "layout_key": spec.layout_key,
                "address": f"0x{csp.read_runtime_layout_offset(spec.layout_key):X}",
                "required": spec.required,
            }
            for spec in TRACE_SPECS
        ],
        "navigation": [],
    }

    csp.stop_game()
    csp.clear_loader_log()
    csp.launch_game()
    process_id = csp.wait_for_game_process()
    csp.wait_for_lua_pipe()
    result["process_id"] = process_id
    result["navigation"].append({"step": "launch", "process_id": process_id})
    result["lua_bot_tick_gate_before_hub"] = set_lua_tick_enabled(False)

    arm_state = arm_traces()
    result["trace_arm_state"] = arm_state
    for spec in TRACE_SPECS:
        require_trace_armed(arm_state, spec)

    hub_flow = csp.drive_hub_flow(process_id, element="fire", discipline="mind", prefer_resume=False)
    result["navigation"].append({"step": "hub_ready", "flow": hub_flow})
    result["lua_bot_tick_gate_after_hub"] = set_lua_tick_enabled(False)
    result["clear_bots_after_hub"] = clear_bots()
    time.sleep(0.25)

    player_before_watch = wait_for_player_visual_state("player_before_watch")
    require_zero_source_profile(player_before_watch, "player_before_watch")
    player_actor = csp.int_value(player_before_watch, "actor_address")
    watch_state = arm_player_source_watch(player_actor)
    if watch_state.get("watch_ok") != "true":
        raise LiveSourceProfileWriterFailure(f"player source write watch failed: {watch_state}")

    result["lua_bot_tick_gate_before_probe_bot"] = set_lua_tick_enabled(False)
    result["clear_bots_before_probe_bot"] = clear_bots()
    bot_id = create_shared_hub_bot()
    result["bot_id"] = bot_id
    bot_sample = wait_for_bot(bot_id)
    time.sleep(0.5)
    player_after_bot = wait_for_player_visual_state("player_after_bot")
    bot_settled = query_bot_visual_state(bot_id)
    log_tail = csp.tail_loader_log(280)
    player_source_writes = query_player_source_write_hits()
    trace_hits = query_trace_hits()

    require_zero_source_profile(player_after_bot, "player_after_bot")
    require_zero_source_profile(bot_sample, "bot")
    require_zero_source_profile(bot_settled, "bot_settled")
    if csp.int_value(player_source_writes, "count") != 0:
        raise LiveSourceProfileWriterFailure(
            f"finalized player source window was written during bot materialization: {player_source_writes}"
        )

    require_trace_hit(trace_hits, "source_actor_ctor")
    require_trace_hit(trace_hits, "actor_build_render_descriptor_from_source")
    require_trace_hit(trace_hits, "wizard_clone_from_source_actor")

    result["player_before_watch"] = player_before_watch
    result["watch_state"] = watch_state
    result["bot_sample"] = bot_sample
    result["player_after_bot"] = player_after_bot
    result["bot_settled"] = bot_settled
    result["player_source_write_hits"] = player_source_writes
    result["trace_hits"] = trace_hits
    result["source_profile_log_evidence"] = collect_log_evidence(log_tail)
    result["loader_log_tail"] = log_tail
    result["conclusion"] = (
        "The runtime hit the blank source-actor constructor plus descriptor and clone "
        "consumers while materializing the bot. No write was observed to the finalized "
        "player source window, and finalized player/bot actors still had actor+0x178 "
        "set to zero. No replacement native source-profile producer is proven."
    )
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
            "loader_log_tail": csp.tail_loader_log(280),
        }
        exit_code = 1
    finally:
        try:
            clear_player_source_watch()
            clear_traces()
        except Exception:
            pass
        if not args.keep_running:
            csp.stop_game()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif result.get("passed"):
        print("PASS: live source-profile writer probe found no native finalized-actor producer")
        print(f"Wrote {args.output}")
    else:
        print(f"FAIL: live source-profile writer probe: {result.get('error')}")
        print(f"Wrote {args.output}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
