#!/usr/bin/env python3
"""Live helper for bot render investigations on a settled gameplay scene."""

from __future__ import annotations

import argparse
import configparser
import json
import subprocess
import sys
import textwrap
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
LUA_EXEC = ROOT / "tools" / "lua-exec.py"
PROBE_LAYOUT = ROOT / "mods" / "lua_ui_sandbox_lab" / "config" / "probe-layout.ini"
STATE_PATH = ROOT / "runtime" / "live_bot_render_debug_state.json"

TRACE_TARGETS = [
    ("gameplay.create_player_slot", "trace_gameplay_create_player_slot"),
    ("player.appearance_apply_choice", "trace_player_appearance_apply_choice"),
    ("gameplay.finalize_player_start", "trace_gameplay_finalize_player_start"),
    ("world.register_gameplay_slot_actor", "trace_actor_world_register_gameplay_slot_actor"),
    ("world.unregister_actor", "trace_actor_world_unregister"),
    ("puppet_manager.delete_puppet", "trace_puppet_manager_delete_puppet"),
    ("actor.build_render_descriptor_from_source", "trace_actor_build_render_descriptor_from_source"),
]

SHARED_WATCH_NAMES = (
    "gameplay.item_list",
    "gameplay.sink.primary",
    "gameplay.sink.secondary",
    "gameplay.sink.attachment",
    "player.actor.variant_window",
    "player.actor.descriptor",
    "player.actor.attachment",
)

BOT_WATCH_NAMES = (
    "bot.actor.variant_window",
    "bot.actor.descriptor",
    "bot.actor.source_window",
    "bot.actor.attachment",
    "bot.source.render_fields",
)


def load_probe_layout() -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    if not parser.read(PROBE_LAYOUT, encoding="utf-8"):
        raise RuntimeError(f"Unable to read probe layout: {PROBE_LAYOUT}")
    return parser


def run_lua(code: str) -> str:
    last_error = ""
    for attempt in range(12):
        result = subprocess.run(
            [sys.executable, str(LUA_EXEC), code],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode == 0:
            return result.stdout

        last_error = result.stderr.strip() or result.stdout.strip() or "Lua exec failed."
        if "Lua engine is busy executing on another thread" not in last_error:
            raise RuntimeError(last_error)
        time.sleep(0.5)

    raise RuntimeError(last_error or "Lua exec failed after busy retries.")


def parse_key_values(output: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed[key.strip()] = value.strip()
    return parsed


def query_scene() -> dict[str, str]:
    code = textwrap.dedent(
        """
        local scene = sd.world and sd.world.get_scene and sd.world.get_scene()
        local function emit(key, value)
          if value == nil then
            print(key .. "=")
          else
            print(key .. "=" .. tostring(value))
          end
        end
        if type(scene) ~= "table" then
          emit("available", false)
          return
        end
        emit("available", true)
        emit("name", scene.name)
        emit("kind", scene.kind)
        emit("transitioning", scene.transitioning)
        emit("world_id", scene.world_id)
        emit("scene_id", scene.scene_id or scene.id)
        emit("id", scene.id)
        emit("region_index", scene.region_index)
        emit("region_type_id", scene.region_type_id)
        emit("scene_type_id", scene.scene_type_id)
        """
    ).strip()
    return parse_key_values(run_lua(code))


def query_player_state() -> dict[str, str]:
    code = textwrap.dedent(
        """
        local player = sd.player and sd.player.get_state and sd.player.get_state()
        local function emit(key, value)
          if value == nil then
            print(key .. "=")
          else
            print(key .. "=" .. tostring(value))
          end
        end
        if type(player) ~= "table" then
          emit("available", false)
          return
        end
        emit("available", true)
        for _, key in ipairs({
          "actor_address",
          "render_subject_address",
          "x",
          "y",
          "render_variant_primary",
          "render_variant_secondary",
          "render_weapon_type",
          "render_selection_byte",
          "render_variant_tertiary",
          "hub_visual_attachment_ptr",
          "hub_visual_source_profile_address",
          "render_frame_table",
          "resolved_animation_state_id",
          "progression_address",
          "world_id",
        }) do
          emit(key, player[key])
        end
        """
    ).strip()
    return parse_key_values(run_lua(code))


def query_bot_state(bot_id: int) -> dict[str, str]:
    code = textwrap.dedent(
        f"""
        local bot = sd.bots and sd.bots.get_state and sd.bots.get_state({bot_id})
        local function emit(key, value)
          if value == nil then
            print(key .. "=")
          else
            print(key .. "=" .. tostring(value))
          end
        end
        if type(bot) ~= "table" then
          emit("available", false)
          return
        end
        emit("available", bot.available)
        for _, key in ipairs({{
          "bot_id",
          "actor_address",
          "x",
          "y",
          "render_variant_primary",
          "render_variant_secondary",
          "render_weapon_type",
          "render_selection_byte",
          "render_variant_tertiary",
          "hub_visual_attachment_ptr",
          "hub_visual_source_profile_address",
          "render_frame_table",
          "resolved_animation_state_id",
          "progression_runtime_state_address",
          "equip_runtime_state_address",
          "moving",
        }}) do
          emit(key, bot[key])
        end
        """
    ).strip()
    return parse_key_values(run_lua(code))


def wait_for_scene(name: str, timeout_seconds: float) -> dict[str, str]:
    deadline = time.monotonic() + timeout_seconds
    last_scene: dict[str, str] = {}
    while time.monotonic() < deadline:
        last_scene = query_scene()
        if (
            last_scene.get("available") == "true"
            and last_scene.get("name") == name
            and last_scene.get("transitioning") == "false"
            and last_scene.get("world_id") not in {"", "0", "0x0", "nil"}
        ):
            return last_scene
        time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for stable scene '{name}'. Last scene={last_scene}")


def clear_probe(config: configparser.ConfigParser) -> None:
    addresses = config["addresses"]
    unwatch_lines = []
    for name in (*SHARED_WATCH_NAMES, *BOT_WATCH_NAMES):
        unwatch_lines.append(f"pcall(sd.debug.unwatch, {json.dumps(name)})")
    untrace_lines = []
    for _, key in TRACE_TARGETS:
        untrace_lines.append(f"pcall(sd.debug.untrace_function, {int(addresses[key], 0)})")
    code = "\n".join(unwatch_lines + untrace_lines)
    run_lua(code)


def arm_shared_probe(config: configparser.ConfigParser, gameplay_address: int, player_actor: int) -> None:
    addresses = config["addresses"]
    lines = []
    for name, key in TRACE_TARGETS:
        lines.append(
            f"print('trace.{name}=' .. tostring(sd.debug.trace_function({int(addresses[key], 0)}, {json.dumps(name)})))"
        )
    run_lua("\n".join(lines))


def arm_shared_write_watches(config: configparser.ConfigParser, gameplay_address: int, player_actor: int) -> None:
    offsets = config["offsets"]
    sizes = config["sizes"]
    shared_watches = [
        ("gameplay.item_list", gameplay_address + int(offsets["gameplay_item_list"], 0), int(sizes["gameplay_item_list_window"], 0)),
        ("gameplay.sink.primary", gameplay_address + int(offsets["gameplay_visual_sink_primary"], 0), int(sizes["gameplay_visual_sink_window"], 0)),
        ("gameplay.sink.secondary", gameplay_address + int(offsets["gameplay_visual_sink_secondary"], 0), int(sizes["gameplay_visual_sink_window"], 0)),
        ("gameplay.sink.attachment", gameplay_address + int(offsets["gameplay_visual_sink_attachment"], 0), int(sizes["gameplay_visual_sink_window"], 0)),
        ("player.actor.variant_window", player_actor + int(offsets["actor_render_variant_window"], 0), int(sizes["actor_render_variant_window"], 0)),
        ("player.actor.descriptor", player_actor + int(offsets["actor_descriptor_block"], 0), int(sizes["actor_descriptor_block"], 0)),
        ("player.actor.attachment", player_actor + int(offsets["actor_attachment_ptr"], 0), 4),
    ]
    lines = []
    for name, address, size in shared_watches:
        lines.append(
            f"print('watch.{name}=' .. tostring(sd.debug.watch_write({json.dumps(name)}, {address}, {size})))"
        )
    run_lua("\n".join(lines))


def spawn_bot(config: configparser.ConfigParser, wizard_id: int, offset_x: float, offset_y: float, heading: float) -> int:
    code = textwrap.dedent(
        f"""
        local player = sd.player and sd.player.get_state and sd.player.get_state()
        if type(player) ~= "table" then
          error("player state unavailable")
        end
        local x = (tonumber(player.x) or 0.0) + ({offset_x})
        local y = (tonumber(player.y) or 0.0) + ({offset_y})
        local bot_id = sd.bots.create({{
          name = "Live Render Debug Bot",
          wizard_id = {wizard_id},
          ready = true,
          position = {{ x = x, y = y }},
          heading = {heading},
        }})
        if bot_id == nil then
          error("sd.bots.create returned nil")
        end
        print("bot_id=" .. tostring(bot_id))
        print("spawn_x=" .. tostring(x))
        print("spawn_y=" .. tostring(y))
        """
    ).strip()
    parsed = parse_key_values(run_lua(code))
    bot_id = parsed.get("bot_id")
    if bot_id is None:
        raise RuntimeError(f"Bot spawn did not return a bot id. Output={parsed}")
    return int(bot_id, 0)


def wait_for_bot_materialized(bot_id: int, timeout_seconds: float) -> dict[str, str]:
    deadline = time.monotonic() + timeout_seconds
    last_state: dict[str, str] = {}
    while time.monotonic() < deadline:
        last_state = query_bot_state(bot_id)
        actor_address = last_state.get("actor_address", "")
        if last_state.get("available") == "true" and actor_address not in {"", "0", "0x0", "nil"}:
            return last_state
        time.sleep(0.25)
    raise RuntimeError(f"Timed out waiting for bot materialization. bot_id={bot_id} last={last_state}")


def arm_bot_probe(config: configparser.ConfigParser, bot_state: dict[str, str]) -> None:
    offsets = config["offsets"]
    sizes = config["sizes"]
    actor_address = int(bot_state["actor_address"], 0)
    source_profile = int(bot_state.get("hub_visual_source_profile_address") or "0", 0)
    lines = [
        f"print('watch.bot.actor.variant_window=' .. tostring(sd.debug.watch_write('bot.actor.variant_window', {actor_address + int(offsets['actor_render_variant_window'], 0)}, {int(sizes['actor_render_variant_window'], 0)})))",
        f"print('watch.bot.actor.descriptor=' .. tostring(sd.debug.watch_write('bot.actor.descriptor', {actor_address + int(offsets['actor_descriptor_block'], 0)}, {int(sizes['actor_descriptor_block'], 0)})))",
        f"print('watch.bot.actor.source_window=' .. tostring(sd.debug.watch_write('bot.actor.source_window', {actor_address + int(offsets['actor_source_kind'], 0)}, 16)))",
        f"print('watch.bot.actor.attachment=' .. tostring(sd.debug.watch_write('bot.actor.attachment', {actor_address + int(offsets['actor_attachment_ptr'], 0)}, 4)))",
    ]
    if source_profile != 0:
        lines.append(
            f"print('watch.bot.source.render_fields=' .. tostring(sd.debug.watch_write('bot.source.render_fields', {source_profile + int(offsets['source_render_fields'], 0)}, {int(sizes['source_render_fields'], 0)})))"
        )
    run_lua("\n".join(lines))


def save_state(data: dict[str, object]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def load_state() -> dict[str, object]:
    if not STATE_PATH.exists():
        raise RuntimeError(f"No saved state at {STATE_PATH}")
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def cmd_scene(args: argparse.Namespace) -> int:
    scene = wait_for_scene(args.name, args.timeout) if args.wait else query_scene()
    print(json.dumps(scene, indent=2, sort_keys=True))
    return 0


def cmd_clear(args: argparse.Namespace) -> int:
    config = load_probe_layout()
    clear_probe(config)
    print("Cleared trace/watch state.")
    return 0


def cmd_arm_and_spawn(args: argparse.Namespace) -> int:
    config = load_probe_layout()
    clear_probe(config)
    scene = wait_for_scene(args.scene, args.timeout)
    player = query_player_state()
    gameplay_address = int(scene["scene_id"], 0)
    player_actor = int(player["actor_address"], 0)
    arm_shared_probe(config, gameplay_address, player_actor)
    if args.with_write_watches:
        arm_shared_write_watches(config, gameplay_address, player_actor)
    bot_id = spawn_bot(config, args.wizard_id, args.offset_x, args.offset_y, args.heading)
    partial_state = {
        "scene": scene,
        "player_before_spawn": player,
        "bot_id": bot_id,
        "write_watches_enabled": args.with_write_watches,
    }
    save_state(partial_state)
    bot = wait_for_bot_materialized(bot_id, args.timeout)
    if args.with_write_watches:
        arm_bot_probe(config, bot)
    player_after = query_player_state()
    state = {
        "scene": scene,
        "player_before_spawn": player,
        "player_after_spawn": player_after,
        "bot": bot,
        "bot_id": bot_id,
        "write_watches_enabled": args.with_write_watches,
    }
    save_state(state)
    print(json.dumps(state, indent=2, sort_keys=True))
    return 0


def cmd_dump(args: argparse.Namespace) -> int:
    state = load_state()
    bot_id = args.bot_id if args.bot_id is not None else int(state["bot_id"])
    scene = query_scene()
    player = query_player_state()
    bot = query_bot_state(bot_id)
    current = {
        "scene": scene,
        "player": player,
        "bot": bot,
        "bot_id": bot_id,
        "saved_state": state,
    }
    print(json.dumps(current, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    scene_parser = subparsers.add_parser("scene", help="Print the current scene or wait for a stable scene.")
    scene_parser.add_argument("--name", default="testrun")
    scene_parser.add_argument("--timeout", type=float, default=30.0)
    scene_parser.add_argument("--wait", action="store_true")
    scene_parser.set_defaults(func=cmd_scene)

    clear_parser = subparsers.add_parser("clear", help="Remove live bot render traces and watches.")
    clear_parser.set_defaults(func=cmd_clear)

    arm_parser = subparsers.add_parser(
        "arm-and-spawn",
        help="Wait for a stable scene, arm the live render probe, spawn a bot, and save the resulting state.",
    )
    arm_parser.add_argument("--scene", default="testrun")
    arm_parser.add_argument("--timeout", type=float, default=30.0)
    arm_parser.add_argument("--wizard-id", type=int, default=0)
    arm_parser.add_argument("--offset-x", type=float, default=32.0)
    arm_parser.add_argument("--offset-y", type=float, default=0.0)
    arm_parser.add_argument("--heading", type=float, default=0.0)
    arm_parser.add_argument(
        "--with-write-watches",
        action="store_true",
        help="Also arm hardware write watches. This is intentionally opt-in because single-step traps are still destabilizing some live runs.",
    )
    arm_parser.set_defaults(func=cmd_arm_and_spawn)

    dump_parser = subparsers.add_parser("dump", help="Dump current scene/player/bot state using the saved bot id.")
    dump_parser.add_argument("--bot-id", type=int)
    dump_parser.set_defaults(func=cmd_dump)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
