#!/usr/bin/env python3
"""Live regression for native bot cast gates and active spell-object lookup.

The probe verifies the current native contract for gameplay-slot bot casts:
the actor keeps its real slot/progression state while calling the stock player
cast path, and while the cast is active the cached native spell object resolves
through the same handle path recovered in Ghidra.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import cast_state_probe as csp  # noqa: E402
from run_live_bot_native_mana_spend_probe import (  # noqa: E402
    read_loader_log_lines,
    stop_bot,
)
from run_live_native_spell_stats_probe import (  # noqa: E402
    force_bot_mana,
    queue_skill,
    read_runtime_layout_offset,
    tail_loader_log,
)


OUTPUT_PATH = ROOT / "runtime" / "live_cast_shim_snapshot_probe.json"
# Earth primary leaves a stable world-bucket boulder object long enough for a
# Lua snapshot. In the no-wave harness it currently completes through the
# bounded-cast safety cap, so the default timeout must cover that path.
CAST_SNAPSHOT_SKILL_ID = 0x3F6
FORCED_MANA = 500.0

CAST_COMPLETE_RE = re.compile(
    r"cast complete \((?P<label>[^)]+)\)\. bot_id=(?P<bot_id>\d+) "
    r"skill_id=(?P<skill_id>-?\d+) (?P<rest>.*)"
)

RESTORE_FIELDS = (
    "gameplay_player_actor",
    "gameplay_player_progression_handle",
    "bot_actor_slot",
    "bot_actor_progression_handle",
    "primary_skill_id",
    "previous_skill_id",
    "selection_group",
    "selection_slot",
    "selection_retarget_ticks",
    "native_active_spell_object.group",
    "native_active_spell_object.slot",
    "native_active_spell_object.object",
    "actor_primary_action_latch_e4",
)
CAST_GROUP_SENTINEL = 0xFF
CAST_SLOT_SENTINEL = 0xFFFF
MAX_POST_CAST_IDLE_ACTION_LATCH_E8 = 1


class LiveCastShimSnapshotProbeFailure(RuntimeError):
    pass


def int_or_zero(value: Any) -> int:
    try:
        if isinstance(value, str) and value.lower().startswith("0x"):
            return int(value, 16)
        return int(value)
    except (TypeError, ValueError):
        return 0


def parse_log_fields(rest: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for part in rest.split():
        key, sep, value = part.partition("=")
        if sep:
            parsed[key] = value
    return parsed


def capture_cast_fields(bot_id: int) -> dict[str, str]:
    offsets = {
        name: read_runtime_layout_offset(name)
        for name in (
            "gameplay_player_actor",
            "gameplay_player_progression_handle",
            "actor_slot",
            "actor_progression_handle",
            "actor_progression_runtime_state",
            "actor_owner",
            "actor_primary_skill_id",
            "actor_previous_skill_id",
            "actor_active_cast_group_byte",
            "actor_active_cast_slot_short",
            "actor_animation_selection_state",
            "actor_control_brain_target_slot",
            "actor_control_brain_target_handle",
            "actor_control_brain_retarget_ticks",
            "actor_primary_action_latch_e4",
            "actor_primary_action_latch_e8",
            "actor_world_bucket_table",
            "actor_world_bucket_stride",
            "game_object_type_id",
            "object_position_x",
            "object_position_y",
            "object_heading",
            "object_collision_radius",
            "spell_object_charge",
            "spell_object_release_charge",
            "spell_object_max_charge",
            "spell_object_phase",
            "spell_object_release_timer",
        )
    }
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
local function parse_address(value)
  if type(value) == 'number' then
    return value
  end
  if type(value) ~= 'string' then
    return 0
  end
  local hex = value:match('^0x(.+)$')
  if hex then
    return tonumber(hex, 16) or 0
  end
  return tonumber(value) or 0
end

local scene = sd.world and sd.world.get_scene and sd.world.get_scene()
local gameplay = type(scene) == 'table' and parse_address(scene.scene_id or scene.id) or 0
local bot = sd.bots.get_state({bot_id})
if gameplay == 0 or type(bot) ~= 'table' then
  emit('available', false)
  return
end

local actor = tonumber(bot.actor_address) or 0
local selection = actor ~= 0 and sd.debug.read_ptr(actor + {offsets["actor_animation_selection_state"]}) or 0
local world = actor ~= 0 and sd.debug.read_ptr(actor + {offsets["actor_owner"]}) or 0
local group = actor ~= 0 and sd.debug.read_u8(actor + {offsets["actor_active_cast_group_byte"]}) or 0xff
local slot = actor ~= 0 and sd.debug.read_u16(actor + {offsets["actor_active_cast_slot_short"]}) or 0xffff
local handle_from_selection = false
if selection ~= 0 and (group == 0xff or slot == 0xffff) then
  local selection_group = sd.debug.read_u8(selection + {offsets["actor_control_brain_target_slot"]})
  local selection_slot = sd.debug.read_u16(selection + {offsets["actor_control_brain_target_handle"]})
  if selection_group ~= 0xff and selection_slot ~= 0xffff then
    group = selection_group
    slot = selection_slot
    handle_from_selection = true
  end
end

local object = 0
if world ~= 0 and group ~= 0xff and slot ~= 0xffff then
  local entry = world + {offsets["actor_world_bucket_table"]} +
    ((group * {offsets["actor_world_bucket_stride"]}) + slot) * 4
  object = sd.debug.read_ptr(entry)
end
emit('available', true)
emit('gameplay', gameplay)
emit('bot_actor', actor)
emit('gameplay_player_actor', sd.debug.read_ptr(gameplay + {offsets["gameplay_player_actor"]}))
emit('gameplay_player_progression_handle', sd.debug.read_ptr(gameplay + {offsets["gameplay_player_progression_handle"]}))
emit('bot_actor_slot', actor ~= 0 and sd.debug.read_u8(actor + {offsets["actor_slot"]}) or nil)
emit('bot_actor_progression_handle', actor ~= 0 and sd.debug.read_ptr(actor + {offsets["actor_progression_handle"]}) or nil)
emit('bot_actor_progression_runtime', actor ~= 0 and sd.debug.read_ptr(actor + {offsets["actor_progression_runtime_state"]}) or nil)
emit('primary_skill_id', actor ~= 0 and sd.debug.read_i32(actor + {offsets["actor_primary_skill_id"]}) or nil)
emit('previous_skill_id', actor ~= 0 and sd.debug.read_i32(actor + {offsets["actor_previous_skill_id"]}) or nil)
emit('actor_primary_action_latch_e4', actor ~= 0 and sd.debug.read_u32(actor + {offsets["actor_primary_action_latch_e4"]}) or nil)
emit('actor_primary_action_latch_e8', actor ~= 0 and sd.debug.read_u32(actor + {offsets["actor_primary_action_latch_e8"]}) or nil)
emit('selection_state', selection)
emit('selection_group', selection ~= 0 and sd.debug.read_u8(selection + {offsets["actor_control_brain_target_slot"]}) or nil)
emit('selection_slot', selection ~= 0 and sd.debug.read_u16(selection + {offsets["actor_control_brain_target_handle"]}) or nil)
emit('selection_retarget_ticks', selection ~= 0 and sd.debug.read_i32(selection + {offsets["actor_control_brain_retarget_ticks"]}) or nil)
emit('native_active_spell_object.group', group)
emit('native_active_spell_object.slot', slot)
emit('native_active_spell_object.handle_from_selection_state', handle_from_selection)
emit('native_active_spell_object.world', world)
emit('native_active_spell_object.object', object)
emit('native_active_spell_object.object_type', object ~= 0 and sd.debug.read_u32(object + {offsets["game_object_type_id"]}) or nil)
emit('native_active_spell_object.x', object ~= 0 and sd.debug.read_float(object + {offsets["object_position_x"]}) or nil)
emit('native_active_spell_object.y', object ~= 0 and sd.debug.read_float(object + {offsets["object_position_y"]}) or nil)
emit('native_active_spell_object.heading', object ~= 0 and sd.debug.read_float(object + {offsets["object_heading"]}) or nil)
emit('native_active_spell_object.radius', object ~= 0 and sd.debug.read_float(object + {offsets["object_collision_radius"]}) or nil)
emit('native_active_spell_object.charge', object ~= 0 and sd.debug.read_float(object + {offsets["spell_object_charge"]}) or nil)
emit('native_active_spell_object.release_charge', object ~= 0 and sd.debug.read_float(object + {offsets["spell_object_release_charge"]}) or nil)
emit('native_active_spell_object.max_charge', object ~= 0 and sd.debug.read_float(object + {offsets["spell_object_max_charge"]}) or nil)
emit('native_active_spell_object.phase', object ~= 0 and sd.debug.read_u32(object + {offsets["spell_object_phase"]}) or nil)
emit('native_active_spell_object.release_timer', object ~= 0 and sd.debug.read_u32(object + {offsets["spell_object_release_timer"]}) or nil)
""".strip()
        )
    )


def assert_restore_fields(before: dict[str, str], after: dict[str, str]) -> None:
    if before.get("available") != "true" or after.get("available") != "true":
        raise LiveCastShimSnapshotProbeFailure(f"capture unavailable: before={before} after={after}")
    mismatches = [
        f"{field}: before={before.get(field)} after={after.get(field)}"
        for field in RESTORE_FIELDS
        if before.get(field) != after.get(field)
    ]
    if mismatches:
        raise LiveCastShimSnapshotProbeFailure("cast shim restore mismatch: " + "; ".join(mismatches))


def assert_native_active_spell_object(snapshot: dict[str, str]) -> None:
    if int_or_zero(snapshot.get("native_active_spell_object.object")) == 0:
        raise LiveCastShimSnapshotProbeFailure(f"native active object did not resolve: {snapshot}")
    if int_or_zero(snapshot.get("native_active_spell_object.object_type")) == 0:
        raise LiveCastShimSnapshotProbeFailure(f"native active object did not resolve object type: {snapshot}")


def assert_post_cast_lifecycle(after: dict[str, str]) -> None:
    if int_or_zero(after.get("native_active_spell_object.group")) != CAST_GROUP_SENTINEL:
        raise LiveCastShimSnapshotProbeFailure(f"post-cast group was not sentinel: {after}")
    if int_or_zero(after.get("native_active_spell_object.slot")) != CAST_SLOT_SENTINEL:
        raise LiveCastShimSnapshotProbeFailure(f"post-cast slot was not sentinel: {after}")
    if int_or_zero(after.get("native_active_spell_object.object")) != 0:
        raise LiveCastShimSnapshotProbeFailure(f"post-cast active object still resolves: {after}")
    if int_or_zero(after.get("primary_skill_id")) != 0:
        raise LiveCastShimSnapshotProbeFailure(f"post-cast primary skill remains set: {after}")
    if int_or_zero(after.get("previous_skill_id")) != 0:
        raise LiveCastShimSnapshotProbeFailure(f"post-cast previous skill remains set: {after}")
    if int_or_zero(after.get("actor_primary_action_latch_e4")) != 0:
        raise LiveCastShimSnapshotProbeFailure(f"post-cast E4 latch remains set: {after}")
    if int_or_zero(after.get("actor_primary_action_latch_e8")) > MAX_POST_CAST_IDLE_ACTION_LATCH_E8:
        raise LiveCastShimSnapshotProbeFailure(f"post-cast E8 latch is not idle: {after}")


def wait_for_native_active_spell_object(bot_id: int, timeout_s: float) -> dict[str, str]:
    deadline = time.time() + timeout_s
    last_snapshot: dict[str, str] = {}
    while time.time() < deadline:
        snapshot = capture_cast_fields(bot_id)
        last_snapshot = snapshot
        if int_or_zero(snapshot.get("native_active_spell_object.object")) != 0:
            return snapshot
        time.sleep(0.2)
    raise LiveCastShimSnapshotProbeFailure(
        "timed out waiting for active native spell object; "
        f"last_snapshot={json.dumps(last_snapshot, indent=2, sort_keys=True)}"
    )


def wait_for_cast_complete(bot_id: int, skill_id: int, start_line_count: int, timeout_s: float) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last_tail: list[str] = []
    while time.time() < deadline:
        lines = read_loader_log_lines()
        last_tail = lines[-200:]
        for line in lines[start_line_count:]:
            match = CAST_COMPLETE_RE.search(line)
            if (
                match
                and int(match.group("bot_id")) == bot_id
                and int(match.group("skill_id")) == skill_id
            ):
                parsed = parse_log_fields(match.group("rest"))
                parsed["line"] = line
                parsed["label"] = match.group("label")
                parsed["bot_id"] = match.group("bot_id")
                parsed["skill_id"] = match.group("skill_id")
                return parsed
        time.sleep(0.25)
    raise LiveCastShimSnapshotProbeFailure(
        "timed out waiting for terminal cast; "
        f"tail={json.dumps(last_tail[-30:], indent=2)}"
    )


def drive_to_materialized_bot_without_waves(element: str, discipline: str) -> dict[str, Any]:
    result: dict[str, Any] = {"navigation": []}
    result["launcher_freshness"] = csp.ensure_launcher_bundle_fresh()

    csp.stop_game()
    csp.clear_loader_log()
    csp.launch_game()
    process_id = csp.wait_for_game_process()
    result["process_id"] = process_id
    csp.wait_for_lua_pipe()
    result["navigation"].append({"step": "launch", "process_id": process_id})

    hub_flow = csp.drive_hub_flow(
        process_id,
        element=element,
        discipline=discipline,
        prefer_resume=False,
    )
    result["navigation"].append({"step": "hub_ready", "flow": hub_flow})

    scene = csp.query_scene_state()
    if not csp.is_settled_scene(scene, "testrun"):
        values = csp.parse_key_values(
            csp.run_lua("print('ok='..tostring(sd.hub.start_testrun()))")
        )
        if values.get("ok") != "true":
            raise LiveCastShimSnapshotProbeFailure(f"sd.hub.start_testrun failed: {values}")
        scene = csp.wait_for_scene("testrun", timeout_s=45.0)
    result["navigation"].append({"step": "testrun_started_without_waves", "scene": scene})

    csp.boost_player_survival()
    bot = csp.wait_for_materialized_bot()
    bot_id = csp.int_value(bot, "id")
    actor_address = csp.int_value(bot, "actor_address")
    if bot_id == 0 or actor_address == 0:
        raise LiveCastShimSnapshotProbeFailure(f"materialized bot has invalid identity: {bot}")
    result["bot_initial"] = bot
    return result


def run_probe(element: str, discipline: str, timeout_s: float) -> dict[str, Any]:
    result = drive_to_materialized_bot_without_waves(element, discipline)
    bot = dict(result["bot_initial"])
    bot_id = csp.int_value(bot, "id")
    bot_x = csp.float_value(bot, "x")
    bot_y = csp.float_value(bot, "y")
    if bot_id == 0 or bot_x != bot_x or bot_y != bot_y:
        raise LiveCastShimSnapshotProbeFailure(f"materialized bot has invalid state: {bot}")

    stop_result = stop_bot(bot_id)
    mana_write = force_bot_mana(bot_id, FORCED_MANA, FORCED_MANA)
    if mana_write.get("ok") != "true":
        raise LiveCastShimSnapshotProbeFailure(f"failed to force bot mana: {mana_write}")

    before = capture_cast_fields(bot_id)
    target_x = bot_x + 160.0
    target_y = bot_y
    start_line_count = len(read_loader_log_lines())
    cast_result = queue_skill(bot_id, CAST_SNAPSHOT_SKILL_ID, target_x, target_y)
    if cast_result.get("ok") != "true":
        raise LiveCastShimSnapshotProbeFailure(f"sd.bots.cast rejected Earth primary: {cast_result}")

    native_active_spell_object = wait_for_native_active_spell_object(bot_id, timeout_s)
    completion = wait_for_cast_complete(bot_id, CAST_SNAPSHOT_SKILL_ID, start_line_count, timeout_s)
    after = capture_cast_fields(bot_id)
    assert_restore_fields(before, after)
    assert_native_active_spell_object(native_active_spell_object)
    assert_post_cast_lifecycle(after)
    if int_or_zero(completion.get("cleanup_state_restore")) == 0:
        raise LiveCastShimSnapshotProbeFailure(f"native cleanup did not restore gameplay state: {completion}")

    result["stop_result"] = stop_result
    result["mana_write"] = mana_write
    result["cast_result"] = cast_result
    result["cast_fields_before"] = before
    result["native_active_spell_object"] = native_active_spell_object
    result["completion"] = completion
    result["cast_fields_after"] = after
    result["bot_final"] = csp.query_bot_state()
    result["loader_log_tail"] = tail_loader_log()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--element", default="earth", choices=sorted(csp.CREATE_ELEMENT_CENTERS))
    parser.add_argument("--discipline", default="mind", choices=sorted(csp.CREATE_DISCIPLINE_CENTERS))
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--json", action="store_true", help="Only print structured JSON.")
    parser.add_argument("--keep-running", action="store_true", help="Leave the game process running after the probe.")
    args = parser.parse_args()

    exit_code = 0
    try:
        result = run_probe(args.element, args.discipline, args.timeout)
        result["passed"] = True
    except Exception as exc:  # noqa: BLE001 - preserve live diagnostics in JSON.
        result = {
            "passed": False,
            "error": str(exc),
            "loader_log_tail": tail_loader_log(),
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
        completion = result["completion"]
        snapshot = result["native_active_spell_object"]
        print(
            "PASS: live native cast gate/object lookup "
            f"label={completion['label']} "
            f"object={snapshot.get('native_active_spell_object.object')} "
            f"slot={result['cast_fields_after'].get('bot_actor_slot')}"
        )
        print(f"Wrote {args.output}")
    else:
        print(f"FAIL: live native cast gate/object lookup probe: {result.get('error')}")
        print(f"Wrote {args.output}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
