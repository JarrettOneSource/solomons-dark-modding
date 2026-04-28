#!/usr/bin/env python3
"""Launch a clean player run, arm cast watches, and wait for a manual cast."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cast_state_probe as csp
from cast_trace_profiles import build_trace_specs, trace_profile_is_stable, trace_profile_names


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = ROOT / "runtime" / "watch_player_cast_dispatch.json"

GAMEPLAY_CAST_INTENT_OFFSET = 0x1E4
GAMEPLAY_MOUSE_LEFT_FALLBACK_OFFSET = 0x279
PROGRESSION_CURRENT_SPELL_ID_OFFSET = 0x750
DEFAULT_AUTO_CLICK_X = 0.5
DEFAULT_AUTO_CLICK_Y = 0.5
DEFAULT_AUTO_CLICK_DELAY_SECONDS = 1.0
DEFAULT_AUTO_CLICK_INTERVAL_SECONDS = 0.35
DEFAULT_TRACE_PROFILE = "safe_entry"
ARENA_ENEMY_CURRENT_HP_OFFSET = 0x174
EARTH_NATIVE_TRACE_POINTS: dict[str, int] = {
    "earth_primary_handler": 0x00544C60,
    "earth_active_handle_resolve": 0x0045ADE0,
    "earth_cast_cleanup": 0x0052F3B0,
    "earth_release_finalize": 0x005E5450,
    "earth_release_line_check": 0x00524D70,
    "earth_release_secondary": 0x0060B700,
    "earth_update": 0x0060AC40,
    "earth_collision_damage": 0x005F1F00,
    "earth_direct_damage": 0x005F2360,
    "earth_splash_damage": 0x005F25B0,
    "earth_radius_scan": 0x005F2980,
    "earth_child_radius_damage": 0x005F3830,
}


class WatchFailure(RuntimeError):
    pass


def parse_int(values: dict[str, str], key: str) -> int:
    value = values.get(key, "")
    try:
        return int(value, 0)
    except (TypeError, ValueError):
        return 0


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


def query_player_runtime() -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            """
local player = sd.player and sd.player.get_state and sd.player.get_state()
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
if type(player) ~= 'table' then
  emit('available', false)
  return
end
emit('available', true)
for _, key in ipairs({
  'actor_address','progression_handle_address','progression_address',
  'actor_slot','hp','max_hp','mp','max_mp','x','y'
}) do
  emit(key, player[key])
end
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


def query_watchable_enemies(limit: int) -> list[dict[str, object]]:
    output = csp.run_lua(
        f"""
local actors = sd.world and sd.world.list_actors and sd.world.list_actors() or {{}}
local player = sd.player and sd.player.get_state and sd.player.get_state() or {{}}
local px = tonumber(player.x) or 0.0
local py = tonumber(player.y) or 0.0
local rows = {{}}
for _, actor in ipairs(actors) do
  local actor_address = tonumber(actor.actor_address) or 0
  local tracked = actor.tracked_enemy == true
  local dead = actor.dead == true
  local hp = tonumber(actor.hp) or 0.0
  local max_hp = tonumber(actor.max_hp) or 0.0
  if actor_address ~= 0 and tracked and not dead and hp > 0.0 and max_hp > 0.0 then
    local ax = tonumber(actor.x) or 0.0
    local ay = tonumber(actor.y) or 0.0
    local dx = ax - px
    local dy = ay - py
    rows[#rows + 1] = {{
      actor_address = actor_address,
      object_type_id = actor.object_type_id,
      enemy_type = actor.enemy_type,
      hp = hp,
      max_hp = max_hp,
      x = ax,
      y = ay,
      gap = math.sqrt(dx * dx + dy * dy),
    }}
  end
end
table.sort(rows, function(a, b) return a.gap < b.gap end)
for i = 1, math.min(#rows, {limit}) do
  local row = rows[i]
  print('enemy.' .. i .. '.actor_address=' .. tostring(row.actor_address))
  print('enemy.' .. i .. '.object_type_id=' .. tostring(row.object_type_id))
  print('enemy.' .. i .. '.enemy_type=' .. tostring(row.enemy_type))
  print('enemy.' .. i .. '.hp=' .. tostring(row.hp))
  print('enemy.' .. i .. '.max_hp=' .. tostring(row.max_hp))
  print('enemy.' .. i .. '.x=' .. tostring(row.x))
  print('enemy.' .. i .. '.y=' .. tostring(row.y))
  print('enemy.' .. i .. '.gap=' .. tostring(row.gap))
end
print('count=' .. tostring(math.min(#rows, {limit})))
print('total=' .. tostring(#rows))
""".strip()
    )
    values = csp.parse_key_values(output)
    rows: list[dict[str, object]] = []
    for index in range(1, parse_int(values, "count") + 1):
        actor_address = parse_int(values, f"enemy.{index}.actor_address")
        if actor_address == 0:
            continue
        rows.append(
            {
                "name": f"player_enemy_hp_{index}",
                "actor_address": actor_address,
                "hp_address": actor_address + ARENA_ENEMY_CURRENT_HP_OFFSET,
                "object_type_id": parse_int(values, f"enemy.{index}.object_type_id"),
                "enemy_type": values.get(f"enemy.{index}.enemy_type", ""),
                "hp": values.get(f"enemy.{index}.hp", ""),
                "max_hp": values.get(f"enemy.{index}.max_hp", ""),
                "x": values.get(f"enemy.{index}.x", ""),
                "y": values.get(f"enemy.{index}.y", ""),
                "gap": values.get(f"enemy.{index}.gap", ""),
            }
        )
    return rows


def wait_for_watchable_enemies(limit: int, timeout_s: float) -> list[dict[str, object]]:
    deadline = time.time() + timeout_s
    enemies: list[dict[str, object]] = []
    while time.time() < deadline:
        enemies = query_watchable_enemies(limit)
        if enemies:
            return enemies
        time.sleep(0.25)
    return enemies


def arm_enemy_hp_watches(enemies: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    if not enemies:
        return {}

    lua_lines = [
        "local function emit(key, value)",
        "  if value == nil then",
        "    print(key .. '=')",
        "  else",
        "    print(key .. '=' .. tostring(value))",
        "  end",
        "end",
    ]
    for enemy in enemies:
        name = str(enemy["name"])
        lua_lines.append(f"pcall(sd.debug.unwatch, {json.dumps(name)})")
        lua_lines.append(f"sd.debug.clear_write_hits({json.dumps(name)})")
    for enemy in enemies:
        name = str(enemy["name"])
        hp_address = int(enemy["hp_address"])
        lua_lines.append(f"emit({json.dumps(name)}, sd.debug.watch_write({json.dumps(name)}, {hp_address}, 4))")
        lua_lines.append(f"emit({json.dumps(name)} .. '_hp_address', {hp_address})")
    values = csp.parse_key_values(csp.run_lua("\n".join(lua_lines)))

    armed: dict[str, dict[str, object]] = {}
    for enemy in enemies:
        name = str(enemy["name"])
        armed[name] = {
            **enemy,
            "watch_ok": values.get(name, "false"),
            "armed_hp_address": parse_int(values, f"{name}_hp_address"),
        }
    return armed


def arm_watches(player_actor: int, player_progression: int, gameplay_scene: int) -> dict[str, int]:
    if player_actor == 0 or player_progression == 0 or gameplay_scene == 0:
        raise WatchFailure(
            "Cannot arm player watches without actor, progression runtime, and gameplay scene."
        )

    addresses: dict[str, tuple[int, int]] = {
        "player_actor_270": (player_actor + 0x270, 4),
        "player_actor_27c": (player_actor + 0x27C, 4),
        "gameplay_cast_intent": (gameplay_scene + GAMEPLAY_CAST_INTENT_OFFSET, 4),
        "gameplay_mouse_left": (gameplay_scene + GAMEPLAY_MOUSE_LEFT_FALLBACK_OFFSET, 1),
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
        lua_lines.append(f"pcall(sd.debug.unwatch, {json.dumps(name)})")
        lua_lines.append(f"pcall(sd.debug.clear_write_hits, {json.dumps(name)})")
    for name, (address, size) in addresses.items():
        lua_lines.append(f"emit({json.dumps(name)}, sd.debug.watch_write({json.dumps(name)}, {address}, {size}))")
        lua_lines.append(f"emit({json.dumps(name)} .. '_address', {address})")
    values = csp.parse_key_values(csp.run_lua("\n".join(lua_lines)))
    return {name: parse_int(values, f"{name}_address") for name in addresses}


def arm_trace(name: str, address: int, patch_size: int) -> dict[str, str]:
    trace_call = (
        f"sd.debug.trace_function({address}, {json.dumps(name)})"
        if patch_size <= 0
        else f"sd.debug.trace_function({address}, {json.dumps(name)}, {patch_size})"
    )
    return csp.parse_key_values(
        csp.run_lua(
            f"""
pcall(sd.debug.untrace_function, {address})
sd.debug.clear_trace_hits({json.dumps(name)})
print('ok=' .. tostring({trace_call}))
print('error=' .. tostring(sd.debug.get_last_error and sd.debug.get_last_error() or ''))
""".strip()
        )
    )


def clear_trace(name: str, address: int) -> None:
    csp.run_lua(
        f"""
pcall(sd.debug.untrace_function, {address})
sd.debug.clear_trace_hits({json.dumps(name)})
""".strip()
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
    'esi','edi','ebp','esp_before_pushad','ret','arg0','arg1','arg2','arg3','arg4','arg5','arg6','arg7','arg8'
  }}) do
    emit('hit.' .. i .. '.' .. key, hit[key])
  end
end
""".strip()
        )
    )


def arm_builder_traces(profile: str) -> dict[str, dict[str, str]]:
    return {
        spec.name: arm_trace(spec.name, spec.address, spec.patch_size)
        for spec in build_trace_specs("player_primary", profile)
    }


def clear_builder_traces(profile: str) -> None:
    for spec in build_trace_specs("player_primary", profile):
        clear_trace(spec.name, spec.address)


def arm_earth_native_traces() -> dict[str, dict[str, str]]:
    return {
        f"player_{key}": arm_trace(f"player_{key}", address, 0)
        for key, address in EARTH_NATIVE_TRACE_POINTS.items()
    }


def clear_earth_native_traces() -> None:
    for key, address in EARTH_NATIVE_TRACE_POINTS.items():
        clear_trace(f"player_{key}", address)


def query_earth_native_trace_hits() -> dict[str, dict[str, str]]:
    return {
        f"player_{key}": query_trace_hits(f"player_{key}")
        for key in EARTH_NATIVE_TRACE_POINTS
    }


def click_normalized(normalized_x: float, normalized_y: float) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
print('ok=' .. tostring(sd.input.click_normalized({normalized_x}, {normalized_y})))
print('x=' .. tostring({normalized_x}))
print('y=' .. tostring({normalized_y}))
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


def clear_enemy_hp_watches(names: list[str]) -> None:
    if not names:
        return
    lua_lines = []
    for name in names:
        lua_lines.append(f"pcall(sd.debug.unwatch, {json.dumps(name)})")
        lua_lines.append(f"sd.debug.clear_write_hits({json.dumps(name)})")
    csp.run_lua("\n".join(lua_lines))


def query_spell_window(player_actor: int, player_progression: int) -> dict[str, str]:
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
local actor = {player_actor}
local progression = {player_progression}
emit('actor_160', sd.debug.read_u8(actor + 0x160))
emit('actor_1ec', sd.debug.read_u8(actor + 0x1EC))
emit('actor_270', sd.debug.read_u32(actor + 0x270))
emit('actor_27c', sd.debug.read_u8(actor + 0x27C))
emit('actor_27e', sd.debug.read_u16(actor + 0x27E))
emit('prog_750', sd.debug.read_u32(progression + {PROGRESSION_CURRENT_SPELL_ID_OFFSET}))
""".strip()
        )
    )


def tail_loader_log(lines: int = 120) -> list[str]:
    if not csp.LOADER_LOG.exists():
        return []
    try:
        content = csp.LOADER_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return content[-lines:]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launch a clean player run, arm cast traces, and wait for a manual primary/secondary cast."
    )
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--element", default="ether", choices=tuple(csp.CREATE_ELEMENT_CENTERS.keys()))
    parser.add_argument("--discipline", default="mind", choices=tuple(csp.CREATE_DISCIPLINE_CENTERS.keys()))
    parser.add_argument("--wait-seconds", type=float, default=20.0)
    parser.add_argument("--start-waves", action="store_true")
    parser.add_argument(
        "--enable-combat-prelude",
        action="store_true",
        help="Enable casting/combat state without starting waves.",
    )
    parser.add_argument("--trace-builder-window", action="store_true")
    parser.add_argument(
        "--trace-earth-native-path",
        action="store_true",
        help="Trace recovered Earth primary cleanup/release/damage functions during the manual player cast.",
    )
    parser.add_argument(
        "--trace-profile",
        default=DEFAULT_TRACE_PROFILE,
        choices=trace_profile_names(),
        help="Trace subset to arm when --trace-builder-window is set.",
    )
    parser.add_argument(
        "--allow-unstable-inline-traces",
        action="store_true",
        help=(
            "Permit in-function trace points. These can destabilize player casts; "
            "safe entry traces are used by default."
        ),
    )
    parser.add_argument("--auto-click", action="store_true")
    parser.add_argument("--click-normalized-x", type=float, default=DEFAULT_AUTO_CLICK_X)
    parser.add_argument("--click-normalized-y", type=float, default=DEFAULT_AUTO_CLICK_Y)
    parser.add_argument("--auto-click-delay", type=float, default=DEFAULT_AUTO_CLICK_DELAY_SECONDS)
    parser.add_argument("--auto-click-interval", type=float, default=DEFAULT_AUTO_CLICK_INTERVAL_SECONDS)
    parser.add_argument("--auto-click-count", type=int, default=1)
    parser.add_argument(
        "--skip-write-watches",
        action="store_true",
        help="Do not arm page-guard write watches; use loader logs and snapshots only.",
    )
    parser.add_argument(
        "--attach",
        action="store_true",
        help="Attach to the current live game instead of relaunching and driving menu flow.",
    )
    parser.add_argument(
        "--watch-enemy-hp",
        action="store_true",
        help="Arm write watches on the nearest live enemy HP fields before waiting for the player cast.",
    )
    parser.add_argument("--enemy-watch-count", type=int, default=8)
    parser.add_argument("--enemy-watch-timeout", type=float, default=12.0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result: dict[str, object] = {
        "launcher_freshness": csp.ensure_launcher_bundle_fresh(),
        "navigation": [],
        "element": args.element,
        "discipline": args.discipline,
        "start_waves": args.start_waves,
        "enable_combat_prelude": args.enable_combat_prelude,
        "wait_seconds": args.wait_seconds,
        "attach": args.attach,
        "trace_builder_window": args.trace_builder_window,
        "trace_earth_native_path": args.trace_earth_native_path,
        "trace_profile": args.trace_profile,
        "allow_unstable_inline_traces": args.allow_unstable_inline_traces,
        "auto_click": args.auto_click,
        "skip_write_watches": args.skip_write_watches,
        "watch_enemy_hp": args.watch_enemy_hp,
    }
    traces_armed = False
    earth_native_traces_armed = False
    enemy_watch_names: list[str] = []

    try:
        if args.start_waves and args.enable_combat_prelude:
            raise WatchFailure("--start-waves and --enable-combat-prelude are mutually exclusive")
        if (
            args.trace_builder_window
            and not args.allow_unstable_inline_traces
            and not trace_profile_is_stable(args.trace_profile)
        ):
            raise WatchFailure(
                f"trace profile {args.trace_profile!r} contains unstable inline trace points; "
                "use --trace-profile safe_entry or pass --allow-unstable-inline-traces explicitly"
            )

        if args.attach:
            process_id = csp.wait_for_game_process(timeout_s=10.0)
            csp.wait_for_lua_pipe()
            result["process_id"] = process_id
            result["navigation"].append({"step": "attach", "process_id": process_id})
            result["lua_tick"] = set_lua_tick_enabled(False)
            result["clear_bots"] = clear_bots()
            scene = csp.query_scene_state()
            if scene.get("available") != "true":
                raise WatchFailure(f"scene unavailable while attaching: {scene}")
            if scene.get("name") != "testrun":
                raise WatchFailure(
                    f"attach requires a live testrun scene. current_scene={scene}"
                )
            result["navigation"].append({"step": "attached_scene", "scene": scene})
            if args.start_waves:
                waves = csp.parse_key_values(csp.run_lua("print('ok='..tostring(sd.gameplay.start_waves()))"))
                if waves.get("ok") != "true":
                    raise WatchFailure(f"sd.gameplay.start_waves failed: {waves}")
                result["navigation"].append({"step": "waves_started"})
            elif args.enable_combat_prelude:
                combat = csp.parse_key_values(csp.run_lua("print('ok='..tostring(sd.gameplay.enable_combat_prelude()))"))
                if combat.get("ok") != "true":
                    raise WatchFailure(f"sd.gameplay.enable_combat_prelude failed: {combat}")
                result["navigation"].append({"step": "combat_prelude_enabled"})
        else:
            csp.stop_game()
            csp.clear_loader_log()

            csp.launch_game()
            process_id = csp.wait_for_game_process()
            csp.wait_for_lua_pipe()
            result["process_id"] = process_id
            result["navigation"].append({"step": "launch", "process_id": process_id})

            result["lua_tick"] = set_lua_tick_enabled(False)
            result["clear_bots"] = clear_bots()
            hub_flow = csp.drive_hub_flow(process_id, element=args.element, discipline=args.discipline, prefer_resume=False)
            result["navigation"].append({"step": "hub_ready", "flow": hub_flow})

            scene_before_testrun = csp.query_scene_state()
            if csp.is_settled_scene(scene_before_testrun, "testrun"):
                testrun = {"ok": "true", "already_testrun": "true"}
                scene = scene_before_testrun
            else:
                testrun = csp.parse_key_values(csp.run_lua("print('ok='..tostring(sd.hub.start_testrun()))"))
                if testrun.get("ok") != "true":
                    raise WatchFailure(f"sd.hub.start_testrun failed: {testrun}")
                scene = csp.wait_for_scene("testrun", timeout_s=45.0)
            result["navigation"].append({"step": "testrun", "scene": scene})

            if args.start_waves:
                waves = csp.parse_key_values(csp.run_lua("print('ok='..tostring(sd.gameplay.start_waves()))"))
                if waves.get("ok") != "true":
                    raise WatchFailure(f"sd.gameplay.start_waves failed: {waves}")
                result["navigation"].append({"step": "waves_started"})
            elif args.enable_combat_prelude:
                combat = csp.parse_key_values(csp.run_lua("print('ok='..tostring(sd.gameplay.enable_combat_prelude()))"))
                if combat.get("ok") != "true":
                    raise WatchFailure(f"sd.gameplay.enable_combat_prelude failed: {combat}")
                result["navigation"].append({"step": "combat_prelude_enabled"})

        player = query_player_runtime()
        if player.get("available") != "true":
            raise WatchFailure(f"player runtime unavailable: {player}")
        result["player"] = player

        player_actor = parse_int(player, "actor_address")
        player_progression = parse_int(player, "progression_handle_address")
        gameplay_scene = parse_int(scene, "scene_id")

        result["spell_window_before"] = query_spell_window(player_actor, player_progression)
        if args.skip_write_watches:
            result["watched_addresses"] = {}
        else:
            result["watched_addresses"] = arm_watches(player_actor, player_progression, gameplay_scene)
        if args.trace_builder_window:
            result["trace_arm_results"] = arm_builder_traces(args.trace_profile)
            traces_armed = True
        if args.trace_earth_native_path:
            result["earth_native_trace_arm_results"] = arm_earth_native_traces()
            earth_native_traces_armed = True
        if args.watch_enemy_hp:
            enemies = wait_for_watchable_enemies(args.enemy_watch_count, args.enemy_watch_timeout)
            result["watched_enemies"] = enemies
            result["enemy_hp_watches"] = arm_enemy_hp_watches(enemies)
            enemy_watch_names = list(result["enemy_hp_watches"].keys())
        else:
            result["watched_enemies"] = []
            result["enemy_hp_watches"] = {}

        print(
            f"Player cast watch armed. Scene ready for {args.element}/{args.discipline}. "
            f"Cast now within {args.wait_seconds:.1f}s."
        )
        started_wait = time.time()
        if args.auto_click:
            if args.auto_click_delay > 0:
                time.sleep(args.auto_click_delay)
            clicks: list[dict[str, str]] = []
            for index in range(max(0, args.auto_click_count)):
                click_result = click_normalized(args.click_normalized_x, args.click_normalized_y)
                click_result["index"] = str(index + 1)
                clicks.append(click_result)
                if index + 1 < args.auto_click_count and args.auto_click_interval > 0:
                    time.sleep(args.auto_click_interval)
            result["auto_click_results"] = clicks
        remaining_wait = args.wait_seconds - (time.time() - started_wait)
        if remaining_wait > 0:
            time.sleep(remaining_wait)

        result["spell_window_after"] = query_spell_window(player_actor, player_progression)
        result["write_hits"] = (
            {}
            if args.skip_write_watches
            else {
                name: query_write_hits(name)
                for name in result["watched_addresses"].keys()
            }
        )
        result["enemy_hp_write_hits"] = {
            name: query_write_hits(name)
            for name in enemy_watch_names
        }
        if traces_armed:
            result["trace_hits"] = {
                spec.name: query_trace_hits(spec.name)
                for spec in build_trace_specs("player_primary", args.trace_profile)
            }
        else:
            result["trace_hits"] = {}
        result["earth_native_trace_hits"] = (
            query_earth_native_trace_hits() if earth_native_traces_armed else {}
        )
        result["loader_log_tail"] = tail_loader_log()
        result["status"] = "ok"
    except Exception as exc:
        result["status"] = "error"
        result["error"] = str(exc)
    finally:
        if traces_armed:
            try:
                clear_builder_traces(args.trace_profile)
            except Exception:
                pass
        if earth_native_traces_armed:
            try:
                clear_earth_native_traces()
            except Exception:
                pass
        if enemy_watch_names:
            try:
                clear_enemy_hp_watches(enemy_watch_names)
            except Exception:
                pass
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))

    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
