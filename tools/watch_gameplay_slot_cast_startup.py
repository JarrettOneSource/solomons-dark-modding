#!/usr/bin/env python3
"""Launch a settled run, arm cast-startup write watches, and capture hits."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cast_state_probe as csp


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = ROOT / "runtime" / "watch_gameplay_slot_cast_startup.json"

GAMEPLAY_CAST_INTENT_OFFSET = 0x1E4
GAMEPLAY_MOUSE_LEFT_FALLBACK_OFFSET = 0x279
GAMEPLAY_INDEX_STATE_ACTOR_SELECTION_BASE_INDEX = 0x0C
PROGRESSION_CURRENT_SPELL_ID_OFFSET = 0x750
SPELL_DISPATCH_BODY_ADDRESS = 0x00548A03
SPELL_3EF_BODY_ADDRESS = 0x0052BB87


class WatchFailure(RuntimeError):
    pass


def parse_int(values: dict[str, str], key: str) -> int:
    value = values.get(key, "")
    try:
        return int(value, 0)
    except (TypeError, ValueError):
        return 0


def query_selection_state() -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            """
local state = sd.gameplay and sd.gameplay.get_selection_debug_state and sd.gameplay.get_selection_debug_state()
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
if type(state) ~= 'table' then
  emit('available', false)
  return
end
emit('available', true)
emit('table_address', state.table_address)
emit('entry_count', state.entry_count)
if type(state.slot_selection_entries) == 'table' then
  for i = 1, #state.slot_selection_entries do
    emit('slot_selection_entries.' .. i, state.slot_selection_entries[i])
  end
end
emit('player_selection_state_0', state.player_selection_state_0)
emit('player_selection_state_1', state.player_selection_state_1)
""".strip()
        )
    )


def arm_watches(
    bot_actor: int,
    bot_progression: int,
    gameplay_scene: int,
    selection_table: int,
) -> dict[str, int]:
    if bot_actor == 0 or bot_progression == 0 or gameplay_scene == 0 or selection_table == 0:
        raise WatchFailure(
            "Cannot arm watches without bot actor, progression runtime, gameplay scene, and selection table."
        )

    addresses = {
        "bot_actor_270": bot_actor + 0x270,
        "bot_actor_27c": bot_actor + 0x27C,
        "bot_prog_750": bot_progression + PROGRESSION_CURRENT_SPELL_ID_OFFSET,
        "slot0_selection": selection_table + GAMEPLAY_INDEX_STATE_ACTOR_SELECTION_BASE_INDEX * 4,
        "slot1_selection": selection_table + (GAMEPLAY_INDEX_STATE_ACTOR_SELECTION_BASE_INDEX + 1) * 4,
        "gameplay_cast_intent": gameplay_scene + GAMEPLAY_CAST_INTENT_OFFSET,
        "gameplay_mouse_left": gameplay_scene + GAMEPLAY_MOUSE_LEFT_FALLBACK_OFFSET,
    }

    lua_lines = [
        "local function emit(key, value)",
        "  if value == nil then",
        "    print(key .. '=')",
        "  else",
        "    print(key .. '=' .. tostring(value))",
        "  end",
        "end",
    ]
    for name in addresses:
        lua_lines.append(f"sd.debug.unwatch({json.dumps(name)})")
        lua_lines.append(f"sd.debug.clear_write_hits({json.dumps(name)})")
    for name, address in addresses.items():
        lua_lines.append(f"sd.debug.watch_write({json.dumps(name)}, {address}, 4)")
        lua_lines.append(f"emit({json.dumps(name)}, {address})")
    values = csp.parse_key_values(csp.run_lua("\n".join(lua_lines)))
    return {name: parse_int(values, name) for name in addresses}


def arm_traces() -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
sd.debug.untrace_function({SPELL_DISPATCH_BODY_ADDRESS})
sd.debug.untrace_function({SPELL_3EF_BODY_ADDRESS})
sd.debug.clear_trace_hits('dispatch_body')
sd.debug.clear_trace_hits('spell_3ef_body')
emit('dispatch_body', sd.debug.trace_function({SPELL_DISPATCH_BODY_ADDRESS}, 'dispatch_body', 6))
emit('spell_3ef_body', sd.debug.trace_function({SPELL_3EF_BODY_ADDRESS}, 'spell_3ef_body', 5))
""".strip()
        )
    )


def query_trace_hits(name: str) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local hits = sd.debug.get_trace_hits({json.dumps(name)}) or {{}}
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
emit('count', #hits)
for i = 1, math.min(#hits, 16) do
  local hit = hits[i]
  for _, key in ipairs({{
    'requested_address','resolved_address','thread_id','eax','ecx','edx','ebx',
    'esi','edi','ebp','esp_before_pushad','ret','arg0','arg1','arg2'
  }}) do
    emit('hit.' .. i .. '.' .. key, hit[key])
  end
end
""".strip()
        )
    )


def query_write_hits(name: str) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local hits = sd.debug.get_write_hits({json.dumps(name)}) or {{}}
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
emit('count', #hits)
for i = 1, math.min(#hits, 16) do
  local hit = hits[i]
  for _, key in ipairs({{
    'requested_address','resolved_address','base_address','access_address',
    'thread_id','eip','esp','ebp','eax','ecx','edx','ret','arg0','arg1','arg2'
  }}) do
    emit('hit.' .. i .. '.' .. key, hit[key])
  end
end
""".strip()
        )
    )


def query_spell_window(bot_actor: int, bot_progression: int) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
local actor = {bot_actor}
local progression = {bot_progression}
emit('actor_270', sd.debug.read_u32(actor + 0x270))
emit('actor_27c', sd.debug.read_u32(actor + 0x27C))
emit('actor_160', sd.debug.read_u32(actor + 0x160))
emit('actor_1ec', sd.debug.read_u32(actor + 0x1EC))
emit('actor_200', sd.debug.read_u32(actor + 0x200))
emit('actor_21c', sd.debug.read_u32(actor + 0x21C))
emit('prog_750', sd.debug.read_u32(progression + {PROGRESSION_CURRENT_SPELL_ID_OFFSET}))
""".strip()
        )
    )


def queue_primary_cast(target_x: float, target_y: float) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local bots = sd.bots.get_state()
local bot = type(bots) == 'table' and bots[1] or nil
if type(bot) ~= 'table' then
  print('available=false')
  return
end
print('available=true')
print('bot_id=' .. tostring(bot.id))
print('ok=' .. tostring(sd.bots.cast({{
  id = bot.id,
  kind = 'primary',
  target = {{ x = {target_x}, y = {target_y} }},
}})))
""".strip()
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launch a settled run, arm gameplay-slot cast write watches, and capture hit history."
    )
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--arm-traces", action="store_true")
    parser.add_argument("--keep-running", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result: dict[str, object] = {
        "launcher_freshness": csp.ensure_launcher_bundle_fresh(),
        "navigation": [],
    }

    try:
        csp.stop_game()
        csp.clear_loader_log()

        csp.launch_game()
        process_id = csp.wait_for_game_process()
        result["process_id"] = process_id
        csp.wait_for_lua_pipe()
        result["navigation"].append({"step": "launch", "process_id": process_id})

        hub_flow = csp.drive_hub_flow(
            process_id,
            element=csp.DEFAULT_ELEMENT,
            discipline=csp.DEFAULT_DISCIPLINE,
            prefer_resume=False,
        )
        result["navigation"].append(
            {
                "step": "hub_ready",
                "flow": hub_flow,
                "element": csp.DEFAULT_ELEMENT,
                "discipline": csp.DEFAULT_DISCIPLINE,
            }
        )

        csp.start_run_and_waves()
        csp.boost_player_survival()
        result["navigation"].append({"step": "testrun_started"})

        bot = csp.wait_for_materialized_bot()
        player = csp.query_player_state()
        scene = csp.query_scene_state()
        selection = query_selection_state()
        result["before"] = {
            "bot": bot,
            "player": player,
            "scene": scene,
            "selection": selection,
            "bot_spell_window": query_spell_window(
                parse_int(bot, "actor_address"),
                parse_int(bot, "progression_runtime_state_address"),
            ),
        }

        enemy = csp.wait_for_nearest_enemy()
        result["enemy"] = enemy
        watch_addresses = arm_watches(
            parse_int(bot, "actor_address"),
            parse_int(bot, "progression_runtime_state_address"),
            parse_int(scene, "scene_id"),
            parse_int(selection, "table_address"),
        )
        result["watch_addresses"] = watch_addresses
        if args.arm_traces:
            result["trace_armed"] = arm_traces()

        bot_cast = queue_primary_cast(csp.float_value(enemy, "x"), csp.float_value(enemy, "y"))
        result["bot_cast"] = bot_cast

        time.sleep(2.0)

        bot_after = csp.query_bot_state()
        selection_after = query_selection_state()
        result["after"] = {
            "bot": bot_after,
            "selection": selection_after,
            "bot_spell_window": query_spell_window(
                parse_int(bot_after, "actor_address"),
                parse_int(bot_after, "progression_runtime_state_address"),
            ),
        }
        result["write_hits"] = {
            name: query_write_hits(name)
            for name in watch_addresses
        }
        if args.arm_traces:
            result["trace_hits"] = {
                name: query_trace_hits(name)
                for name in ["dispatch_body", "spell_3ef_body"]
            }
        result["loader_log_tail"] = csp.tail_loader_log()

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (csp.ProbeFailure, WatchFailure) as exc:
        result["error"] = str(exc)
        result["loader_log_tail"] = csp.tail_loader_log()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1
    finally:
        if not args.keep_running:
            csp.stop_game()


if __name__ == "__main__":
    raise SystemExit(main())
