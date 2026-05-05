#!/usr/bin/env python3
"""Live RE probe for the disabled registered GameNpc participant rail.

The registered rail must remain blocked until a native long-lived 0x1397
publication lifecycle is recovered. This probe materializes a shared-hub bot
through the staged runtime and fails if the loader uses the registered rail,
classifies the actor as RegisteredGameNpc, or produces a 0x1397 actor from the
old clone handoff path.
"""

from __future__ import annotations

import argparse
import json
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


OUTPUT_PATH = ROOT / "runtime" / "live_registered_gamenpc_blocker_probe.json"
RUNTIME_BINARY_LAYOUT_PATH = ROOT / "runtime/stage/.sdmod/config/binary-layout.ini"
BOT_NAME = "Registered GameNpc Blocker Probe"


class LiveRegisteredGameNpcBlockerFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class TraceSpec:
    name: str
    layout_key: str


TRACE_SPECS = (
    TraceSpec("create_wizard_preview_source", "create_wizard_preview_source"),
    TraceSpec("gamenpc_set_move_goal", "gamenpc_set_move_goal"),
    TraceSpec("gamenpc_set_tracked_slot_assist", "gamenpc_set_tracked_slot_assist"),
    TraceSpec("gamenpc_movement_tick", "gamenpc_movement_tick"),
)


def read_runtime_layout_offset(name: str) -> int:
    text = RUNTIME_BINARY_LAYOUT_PATH.read_text(encoding="utf-8", errors="replace")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return int(value.strip(), 0)
    raise LiveRegisteredGameNpcBlockerFailure(
        f"Unable to find {name!r} in {RUNTIME_BINARY_LAYOUT_PATH}"
    )


def trace_specs_lua_table() -> str:
    rows = []
    for spec in TRACE_SPECS:
        rows.append(
            "{name="
            + json.dumps(spec.name)
            + ", address="
            + str(read_runtime_layout_offset(spec.layout_key))
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
  local resolved = sd.debug.resolve_game_address(spec.address) or spec.address
  local mem = sd.debug.query_memory(resolved)
  emit('trace.' .. spec.name .. '.requested', spec.address)
  emit('trace.' .. spec.name .. '.resolved', resolved)
  emit('trace.' .. spec.name .. '.executable', mem and mem.executable or false)
  emit('trace.' .. spec.name .. '.armed', sd.debug.trace_function(spec.address, spec.name))
  emit('trace.' .. spec.name .. '.last_error', sd.debug.get_last_error())
end
""".strip()
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


def clear_traces() -> None:
    csp.run_lua(
        "\n".join(
            [
                f"pcall(sd.debug.untrace_function, {read_runtime_layout_offset(spec.layout_key)})\n"
                f"sd.debug.clear_trace_hits({json.dumps(spec.name)})"
                for spec in TRACE_SPECS
            ]
        )
    )


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
  position = {{
    x = (tonumber(player.x) or 0.0) + 96.0,
    y = tonumber(player.y) or 0.0,
    heading = 90.0,
  }},
}})
emit('ok', id ~= nil)
emit('bot_id', id)
""".strip()
    )
    values = csp.parse_key_values(output)
    if values.get("ok") != "true":
        raise LiveRegisteredGameNpcBlockerFailure(f"sd.bots.create failed: {values}")
    bot_id = csp.int_value(values, "bot_id")
    if bot_id == 0:
        raise LiveRegisteredGameNpcBlockerFailure(f"sd.bots.create returned invalid id: {values}")
    return bot_id


def query_world_actor_type_summary() -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            """
local actors = sd.world and sd.world.list_actors and sd.world.list_actors() or {}
local function emit(key, value)
  if value == nil then
    print(key .. '=')
  else
    print(key .. '=' .. tostring(value))
  end
end
local count = 0
local gamenpc_count = 0
local player_family_count = 0
for _, actor in ipairs(actors) do
  count = count + 1
  local type_id = tonumber(actor.object_type_id) or 0
  if type_id == 0x1397 then
    gamenpc_count = gamenpc_count + 1
    if gamenpc_count <= 8 then
      emit('gamenpc.' .. gamenpc_count .. '.actor_address', actor.actor_address)
      emit('gamenpc.' .. gamenpc_count .. '.object_type_id', actor.object_type_id)
      emit('gamenpc.' .. gamenpc_count .. '.x', actor.x)
      emit('gamenpc.' .. gamenpc_count .. '.y', actor.y)
    end
  end
  if type_id == 1 then
    player_family_count = player_family_count + 1
  end
end
emit('actor_count', count)
emit('gamenpc_count', gamenpc_count)
emit('player_family_count', player_family_count)
""".strip()
        )
    )


def query_bot_by_id(bot_id: int) -> dict[str, str]:
    object_type_offset = read_runtime_layout_offset("game_object_type_id")
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
  'id', 'name', 'actor_address', 'world_address', 'entity_materialized',
  'entity_kind', 'participant_kind', 'controller_kind', 'gameplay_slot',
  'actor_slot', 'x', 'y'
}}) do
  emit(key, bot[key])
end
emit('scene_kind', type(bot.scene) == 'table' and bot.scene.kind or nil)

local actor = tonumber(bot.actor_address) or 0
emit('raw.available', actor ~= 0)
if actor ~= 0 then
  emit('raw.object_type_id', sd.debug.read_u32(actor + {object_type_offset}))
end
""".strip()
        )
    )


def wait_for_bot(bot_id: int, *, timeout_s: float = 60.0) -> dict[str, str]:
    deadline = time.time() + timeout_s
    last: dict[str, str] = {}
    while time.time() < deadline:
        last = query_bot_by_id(bot_id)
        if last.get("available") == "true" and csp.int_value(last, "actor_address") != 0:
            return last
        time.sleep(0.25)
    raise LiveRegisteredGameNpcBlockerFailure(
        f"timed out waiting for bot materialization. Last={last}"
            )


def validate_trace_hits(trace_hits: dict[str, str]) -> None:
    for trace_name in (
        "gamenpc_set_move_goal",
        "gamenpc_set_tracked_slot_assist",
        "gamenpc_movement_tick",
    ):
        count = csp.int_value(trace_hits, f"trace.{trace_name}.count")
        if count != 0:
            raise LiveRegisteredGameNpcBlockerFailure(
                f"native GameNpc movement trace fired while registered rail is blocked: "
                f"{trace_name} count={count}"
            )


def validate_world_summary(summary: dict[str, str]) -> None:
    if csp.int_value(summary, "gamenpc_count") != 0:
        raise LiveRegisteredGameNpcBlockerFailure(
            f"live world still contains 0x1397 GameNpc actor(s): {summary}"
        )


def validate_sample(sample: dict[str, str]) -> None:
    if sample.get("available") != "true":
        raise LiveRegisteredGameNpcBlockerFailure(f"bot state unavailable: {sample}")
    if sample.get("entity_materialized") != "true":
        raise LiveRegisteredGameNpcBlockerFailure(f"bot is not materialized: {sample}")
    if sample.get("scene_kind") != "SharedHub":
        raise LiveRegisteredGameNpcBlockerFailure(
            f"expected SharedHub scene, got {sample.get('scene_kind')}: {sample}"
        )
    if csp.int_value(sample, "gameplay_slot") != -1:
        raise LiveRegisteredGameNpcBlockerFailure(f"expected standalone gameplay_slot=-1: {sample}")
    if csp.int_value(sample, "raw.object_type_id") == 0x1397:
        raise LiveRegisteredGameNpcBlockerFailure(
            "shared-hub bot materialized as a 0x1397 GameNpc despite the registered rail blocker"
        )
    for key in ("entity_kind", "participant_kind", "controller_kind"):
        value = sample.get(key, "")
        if "RegisteredGameNpc" in value or value == "3":
            raise LiveRegisteredGameNpcBlockerFailure(
                f"bot was classified as registered GameNpc via {key}={value}: {sample}"
            )


def validate_loader_log(log_tail: list[str]) -> None:
    joined = "\n".join(log_tail)
    required_tokens = (
        "rail=standalone_clone",
        "created standalone clone wizard actor",
        "gameplay_slot=-1",
    )
    missing = [token for token in required_tokens if token not in joined]
    if missing:
        raise LiveRegisteredGameNpcBlockerFailure(
            "loader log is missing standalone clone token(s): " + ", ".join(missing)
        )
    forbidden_tokens = (
        "rail=registered_gamenpc",
        "created registered GameNpc actor",
        "GameNpc_SetMoveGoal failed",
        "registered_gamenpc movement failed",
        "registered_gamenpc movement list anomaly",
    )
    present = [token for token in forbidden_tokens if token in joined]
    if present:
        raise LiveRegisteredGameNpcBlockerFailure(
            "loader log contains registered GameNpc rail token(s): " + ", ".join(present)
        )


def run_probe() -> dict[str, Any]:
    result: dict[str, Any] = {
        "launcher_freshness": csp.ensure_launcher_bundle_fresh(),
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
    result["trace_arm_state"] = arm_traces()

    hub_flow = csp.drive_hub_flow(process_id, element="fire", discipline="mind", prefer_resume=False)
    result["navigation"].append({"step": "hub_ready", "flow": hub_flow})
    result["lua_bot_tick_gate_after_hub"] = set_lua_tick_enabled(False)
    result["clear_bots_after_hub"] = clear_bots()
    time.sleep(0.25)

    bot_id = create_shared_hub_bot()
    result["bot_id"] = bot_id
    first_sample = wait_for_bot(bot_id)
    time.sleep(1.0)
    settled_sample = query_bot_by_id(bot_id)
    world_summary = query_world_actor_type_summary()
    trace_hits = query_trace_hits()
    log_tail = csp.tail_loader_log(240)

    validate_sample(first_sample)
    validate_sample(settled_sample)
    validate_world_summary(world_summary)
    validate_trace_hits(trace_hits)
    validate_loader_log(log_tail)

    result["first_sample"] = first_sample
    result["settled_sample"] = settled_sample
    result["world_actor_type_summary"] = world_summary
    result["trace_hits"] = trace_hits
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
        try:
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
        print("PASS: live registered GameNpc blocker probe validated standalone clone rail")
        print(f"Wrote {args.output}")
    else:
        print(f"FAIL: live registered GameNpc blocker probe: {result.get('error')}")
        print(f"Wrote {args.output}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
