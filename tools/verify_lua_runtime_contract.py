#!/usr/bin/env python3
"""Verify the current Lua namespace and read-only runtime contract live."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from multiplayer_lua_probe import DEFAULT_CLIENTS, parse_client, run_all
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    CLIENT_PIPE,
    HOST_ID,
    HOST_NAME,
    HOST_PIPE,
    disable_bots,
    launch_pair,
    stop_games,
    wait_for_remote,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_runtime_contract.json"

REQUIRED_FUNCTIONS: dict[str, tuple[str, ...]] = {
    "runtime": (
        "get_mod",
        "get_multiplayer_state",
        "choose_level_up_option",
        "debug_publish_level_up_offer",
        "has_capability",
        "get_capabilities",
        "get_environment_variable",
        "get_mod_text_file",
    ),
    "events": ("on", "broadcast", "filter"),
    "state": (
        "get",
        "set",
        "delete",
        "clear",
        "snapshot",
        "get_revision",
        "is_authority",
    ),
    "storage": ("get", "set", "delete", "clear", "snapshot"),
    "timer": ("after", "every", "sequence", "cancel", "clear"),
    "bus": ("publish", "subscribe", "unsubscribe", "has", "providers"),
    "net": ("send", "broadcast", "on", "off", "get_limits"),
    "time": ("get_scale", "get_state", "set_scale", "step"),
    "rng": ("get_seed", "set_seed"),
    "nav": ("get_grid", "test_segment"),
    "scene": ("get_state", "switch_region"),
    "waves": ("get_state", "get_schedule"),
    "spells": (
        "register",
        "get",
        "list",
        "select",
        "clear_selection",
        "get_selection",
        "cast",
        "get_effects",
    ),
    "items": ("register", "get", "list", "grant"),
    "enemies": ("register", "get", "list", "spawn"),
    "ai": (
        "register",
        "get_state",
        "list",
        "set_target",
        "set_move_goal",
        "stop",
        "clear",
    ),
    "audio": (
        "play_sample",
        "play_stream",
        "stop",
        "set_volume",
        "get_state",
        "clear",
        "is_available",
    ),
    "camera": ("get_state", "set_focus", "clear_focus", "shake"),
    "sprites": ("register", "unregister", "get", "list", "get_limits"),
    "draw": (
        "text",
        "rect",
        "line",
        "sprite",
        "world_to_screen",
        "get_viewport",
        "get_sprite_info",
        "get_limits",
    ),
    "bots": (
        "create",
        "destroy",
        "clear",
        "update",
        "move_to",
        "stop",
        "face",
        "face_target",
        "cast",
        "get_count",
        "get_state",
        "get_participant_state",
        "get_participants",
        "get_nameplate",
        "get_skill_choices",
        "choose_skill",
        "debug_sync_level_up",
        "resolve_primary_entry",
        "get_primary_attack_window",
    ),
    "ui": (
        "get_surface_id",
        "get_snapshot",
        "find_element",
        "find_action",
        "get_action_dispatch",
        "activate_action",
        "activate_element",
        "get_state",
        "perform",
        "create_surface",
        "create_panel",
        "create_label",
        "create_button",
        "show",
        "hide",
        "destroy",
        "set_text",
        "set_enabled",
        "focus",
        "get_authored_state",
    ),
    "input": (
        "press_key",
        "press_scancode",
        "click_normalized",
        "hold_mouse_left_frames",
        "hold_movement_frames",
        "set_native_control_allowance_frames",
        "pin_manual_primary_target",
        "clear_mouse_left",
        "clear_local_cast_state",
        "get_mouse_left_state",
        "queue_local_spell_cast",
        "queue_local_enemy_damage_claim",
    ),
    "gameplay": (
        "start_waves",
        "enable_combat_prelude",
        "set_manual_enemy_spawner_test_mode",
        "set_remote_progression_reconcile_suppressed_for_test",
        "get_manual_enemy_spawner_state",
        "get_combat_state",
        "get_selection_debug_state",
        "spawn_manual_run_enemy",
        "get_last_manual_run_enemy_spawn",
        "clear_manual_run_enemy_freeze",
        "set_run_enemy_health",
    ),
    "player": (
        "get_state",
        "get_inventory_state",
        "get_progression_book_state",
    ),
    "world": (
        "get_state",
        "get_scene",
        "list_actors",
        "get_replicated_actors",
        "get_run_enemy_by_network_id",
        "get_replicated_loot",
        "get_replicated_spell_effects",
        "get_replicated_air_chains",
        "request_loot_pickup",
        "rebind_actor",
        "spawn_reward",
        "trigger_enemy_death",
    ),
    "hub": (
        "start_testrun",
        "open_service",
        "get_surface_state",
    ),
    # sd.debug is intentionally development-facing. Check the read/probe spine
    # used by today's live verification without declaring every raw memory
    # helper a compatibility promise.
    "debug": (
        "get_last_error",
        "list_traces",
        "list_watches",
        "resolve_game_address",
        "layout_offset",
        "query_memory",
        "get_nav_grid",
        "get_world_movement_geometry",
        "resolve_native_primary_spell_stats",
        "capture_backbuffer",
        "set_run_generation_seed",
    ),
}


def _lua_quote(value: str) -> str:
    return json.dumps(value)


def build_probe() -> str:
    namespace_rows = []
    for namespace, functions in REQUIRED_FUNCTIONS.items():
        encoded = ", ".join(_lua_quote(function) for function in functions)
        namespace_rows.append(f"  [{_lua_quote(namespace)}] = {{{encoded}}},")
    required_lua = "\n".join(namespace_rows)

    return f"""
local required = {{
{required_lua}
}}
local failures = {{}}
local function fail(message) failures[#failures + 1] = message end
local function allowed_type(value, allowed)
  local actual = type(value)
  for _, expected in ipairs(allowed) do
    if actual == expected then return true end
  end
  return false
end
local function check_call(label, fn, allowed)
  local ok, value = pcall(fn)
  if not ok then
    fail(label .. ':error:' .. tostring(value))
  elseif not allowed_type(value, allowed) then
    fail(label .. ':type:' .. type(value))
  end
end

local namespace_count = 0
local required_function_count = 0
for namespace, functions in pairs(required) do
  namespace_count = namespace_count + 1
  local api = type(sd) == 'table' and sd[namespace] or nil
  if type(api) ~= 'table' then
    fail('missing_namespace:' .. namespace)
  else
    for _, name in ipairs(functions) do
      required_function_count = required_function_count + 1
      if type(api[name]) ~= 'function' then
        fail('missing_function:' .. namespace .. '.' .. name)
      end
    end
  end
end

for _, name in ipairs({{'debug', 'dofile', 'io', 'loadfile', 'os', 'package', 'require'}}) do
  if _G[name] ~= nil then fail('unsafe_global:' .. name) end
end
if sd.hud ~= sd.draw then fail('hud_alias_mismatch') end

check_call('runtime.get_mod', sd.runtime.get_mod, {{'table'}})
check_call('runtime.get_capabilities', sd.runtime.get_capabilities, {{'table'}})
check_call('runtime.get_multiplayer_state', sd.runtime.get_multiplayer_state, {{'table'}})
check_call('state.snapshot', sd.state.snapshot, {{'table'}})
check_call('state.get_revision', sd.state.get_revision, {{'number'}})
check_call('state.is_authority', sd.state.is_authority, {{'boolean'}})
check_call('rng.get_seed', sd.rng.get_seed, {{'number', 'nil'}})
check_call('nav.get_grid', sd.nav.get_grid, {{'table', 'nil'}})
check_call('draw.get_limits', sd.draw.get_limits, {{'table'}})
check_call('audio.is_available', sd.audio.is_available, {{'boolean'}})
check_call('audio.get_state', sd.audio.get_state, {{'table'}})
check_call('camera.get_state', sd.camera.get_state, {{'table'}})
check_call('sprites.list', sd.sprites.list, {{'table'}})
check_call('sprites.get_limits', sd.sprites.get_limits, {{'table'}})
check_call('draw.get_viewport', sd.draw.get_viewport, {{'table', 'nil'}})
check_call('draw.get_sprite_info', function()
  return sd.draw.get_sprite_info('Title', 9)
end, {{'table'}})
check_call('bots.get_count', sd.bots.get_count, {{'number'}})
check_call('bots.get_participants', sd.bots.get_participants, {{'table'}})
check_call('ui.get_surface_id', sd.ui.get_surface_id, {{'string', 'nil'}})
check_call('ui.get_snapshot', sd.ui.get_snapshot, {{'table', 'nil'}})
check_call('input.get_mouse_left_state', sd.input.get_mouse_left_state, {{'table'}})
check_call('gameplay.get_manual_enemy_spawner_state', sd.gameplay.get_manual_enemy_spawner_state, {{'table'}})
check_call('gameplay.get_combat_state', sd.gameplay.get_combat_state, {{'table'}})
check_call('player.get_state', sd.player.get_state, {{'table', 'nil'}})
check_call('player.get_inventory_state', sd.player.get_inventory_state, {{'table', 'nil'}})
check_call('player.get_progression_book_state', sd.player.get_progression_book_state, {{'table', 'nil'}})
check_call('world.get_state', sd.world.get_state, {{'table'}})
check_call('world.get_scene', sd.world.get_scene, {{'table', 'nil'}})
check_call('world.list_actors', sd.world.list_actors, {{'table'}})

print('ok=' .. tostring(#failures == 0))
print('namespace_count=' .. tostring(namespace_count))
print('required_function_count=' .. tostring(required_function_count))
print('failure_count=' .. tostring(#failures))
print('failures=' .. table.concat(failures, '|'))
"""


def _parse_values(stdout: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def validate_peer_results(
    result: dict[str, Any],
    peer_results: list[dict[str, Any]],
) -> None:
    result["peers"] = peer_results
    failures: list[str] = []
    for peer in peer_results:
        name = str(peer["name"])
        values = _parse_values(str(peer.get("stdout", "")))
        peer["contract_values"] = values
        if peer.get("returncode") != 0:
            failures.append(f"{name}:exec:{str(peer.get('stderr', '')).strip()}")
        elif values.get("ok") != "true" or values.get("failure_count") != "0":
            failures.append(f"{name}:contract:{values.get('failures', 'unknown')}")
        elif int(values.get("namespace_count", "0")) != len(REQUIRED_FUNCTIONS):
            failures.append(f"{name}:namespace_count:{values.get('namespace_count')}")
        elif int(values.get("required_function_count", "0")) != result["required_function_count"]:
            failures.append(
                f"{name}:function_count:{values.get('required_function_count')}"
            )
    result["failures"] = failures
    result["ok"] = not failures


def base_result(*, launched_pair: bool, steam_friend_pair: bool) -> dict[str, Any]:
    return {
        "ok": False,
        "launched_pair": launched_pair,
        "steam_friend_pair": steam_friend_pair,
        "required_namespaces": sorted(REQUIRED_FUNCTIONS),
        "required_function_count": sum(map(len, REQUIRED_FUNCTIONS.values())),
    }


def run(clients: list[tuple[str, str]], launch: bool) -> dict[str, Any]:
    result = base_result(launched_pair=launch, steam_friend_pair=False)
    if launch:
        stop_games()
        launch_pair(god_mode=True)
        disable_bots()
        wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "hub")
        wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "hub")

    validate_peer_results(
        result,
        run_all(clients, build_probe(), timeout=12.0),
    )
    return result


def run_steam_friend_pair() -> dict[str, Any]:
    from steam_friend_active_pair import (  # Local import keeps UDP-only use standalone.
        CLIENT_ENDPOINT,
        HOST_ENDPOINT,
        SteamFriendActivePair,
    )

    pair = SteamFriendActivePair()
    result = base_result(launched_pair=False, steam_friend_pair=True)
    try:
        result["pair"] = pair.discover()
        probe = build_probe()
        peer_results = []
        for name, endpoint in (
            ("host", HOST_ENDPOINT),
            ("client", CLIENT_ENDPOINT),
        ):
            peer_results.append(
                {
                    "name": name,
                    "returncode": 0,
                    "stdout": pair.lua(endpoint, probe, timeout=12.0),
                    "stderr": "",
                }
            )
        validate_peer_results(result, peer_results)
        return pair.redact(result)
    finally:
        pair.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--client",
        action="append",
        type=parse_client,
        help="Lua exec endpoint as NAME=PIPE; defaults to local host/client.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--launch-pair",
        action="store_true",
        help="Stage and launch a local UDP host/client pair before probing.",
    )
    mode.add_argument(
        "--steam-friend",
        action="store_true",
        help="Probe an already-authenticated Windows/Proton Steam friend pair.",
    )
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.steam_friend and args.client:
        parser.error("--client cannot be combined with --steam-friend")

    result: dict[str, Any] = {"ok": False}
    try:
        result = (
            run_steam_friend_pair()
            if args.steam_friend
            else run(args.client or list(DEFAULT_CLIENTS), args.launch_pair)
        )
        return_code = 0 if result["ok"] else 1
    except Exception as exc:  # noqa: BLE001 - verifier reports structured failure.
        result["error"] = str(exc)
        return_code = 1
    finally:
        if args.launch_pair:
            stop_games()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "ok": result.get("ok", False),
                "error": result.get("error"),
                "failures": result.get("failures", []),
                "required_function_count": result.get("required_function_count"),
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
