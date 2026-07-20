#!/usr/bin/env python3
"""Verify the stock-created flat boneyard as an isolated multiplayer arena."""

from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any

from multiplayer_frame_capture import capture_game_backbuffer
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    CLIENT_PIPE,
    HOST_ID,
    HOST_NAME,
    HOST_PIPE,
    ROOT,
    VerifyFailure,
    disable_bots,
    launch_pair,
    lua,
    parse_key_values,
    query,
    start_host_testrun_and_wait_for_clients,
    stop_games,
    wait_for_remote,
)
from verify_multiplayer_primary_kill_stress import (
    cleanup_live_enemies,
    enable_manual_stock_spawner_combat,
    find_target,
    select_clear_kill_lane,
    set_manual_spawner_test_mode,
    spawn_one_enemy,
)


FIXTURE = ROOT / "tests" / "fixtures" / "boneyards" / "flat_multiplayer_test.boneyard"
EXPECTED_SHA256 = "7c7d23f2fbfcdf73b5bb7f4af0f836cc9d199997fe9c7dd38183c7659b6d949d"
OUTPUT = ROOT / "runtime" / "flat_multiplayer_boneyard.json"
HOST_SCREENSHOT = ROOT / "runtime" / "flat_multiplayer_boneyard_host.png"
CLIENT_SCREENSHOT = ROOT / "runtime" / "flat_multiplayer_boneyard_client.png"


NAV_SUMMARY_LUA = r"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local scene = sd.world and sd.world.get_scene and sd.world.get_scene() or nil
local grid = sd.debug and sd.debug.get_nav_grid and sd.debug.get_nav_grid(1) or nil
local cells = type(grid) == 'table' and grid.cells or nil
local samples = 0
local traversable = 0
local min_x, max_x, min_y, max_y = nil, nil, nil, nil
if type(cells) == 'table' then
  for _, cell in ipairs(cells) do
    if type(cell) == 'table' and type(cell.samples) == 'table' then
      for _, sample in ipairs(cell.samples) do
        local x = tonumber(sample.world_x)
        local y = tonumber(sample.world_y)
        if x ~= nil and y ~= nil then
          samples = samples + 1
          if sample.traversable then traversable = traversable + 1 end
          min_x = min_x == nil and x or math.min(min_x, x)
          max_x = max_x == nil and x or math.max(max_x, x)
          min_y = min_y == nil and y or math.min(min_y, y)
          max_y = max_y == nil and y or math.max(max_y, y)
        end
      end
    end
  end
end
local replicated = sd.world and sd.world.get_replicated_actors and sd.world.get_replicated_actors() or nil
emit('scene', scene and (scene.name or scene.kind) or '')
emit('grid_valid', type(grid) == 'table' and grid.valid ~= false)
emit('cell_count', type(cells) == 'table' and #cells or 0)
emit('sample_count', samples)
emit('traversable_count', traversable)
emit('min_x', min_x or 0)
emit('max_x', max_x or 0)
emit('min_y', min_y or 0)
emit('max_y', max_y or 0)
emit('replicated_valid', replicated ~= nil)
emit('replicated_scene_kind', replicated and replicated.scene_kind or '')
emit('replicated_actor_count', replicated and replicated.actor_count or 0)
emit('replicated_actor_total_count', replicated and replicated.actor_total_count or 0)
"""


BLANK_ARENA_CENSUS_LUA = r"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local function offset(name) return tonumber(sd.debug.layout_offset(name)) or 0 end
local function u8(address) return tonumber(sd.debug.read_u8(address)) or 0 end
local function u32(address) return tonumber(sd.debug.read_u32(address)) or 0 end
local function ptr(address) return tonumber(sd.debug.read_ptr(address)) or 0 end
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
local scene = sd.world and sd.world.get_scene and sd.world.get_scene() or nil
local world = tonumber(player and player.world_address) or 0
local gameplay = tonumber(scene and (scene.scene_id or scene.id)) or 0
local pointer_count = offset('pointer_list_count')
local function list_count(offset_name)
  local list_offset = offset(offset_name)
  if world == 0 or list_offset == 0 or pointer_count == 0 then return -1 end
  return u32(world + list_offset + pointer_count)
end
local controller = world + offset('actor_owner_movement_controller')
local movement_circle_count = u32(controller + offset('movement_controller_circle_count'))
local movement_circle_items = ptr(controller + offset('movement_controller_circle_list'))
local object_type_offset = offset('game_object_type_id')
local scenery_types = {
  [2001] = true,
  [2029] = true,
  [2040] = true,
  [2061] = true,
  [3006] = true,
  [3007] = true,
  [3012] = true,
}
local scenery_circle_count = 0
for index = 0, movement_circle_count - 1 do
  local object = ptr(movement_circle_items + index * 4)
  local object_type = object ~= 0 and u32(object + object_type_offset) or 0
  if scenery_types[object_type] then scenery_circle_count = scenery_circle_count + 1 end
end
local scripted_setpiece_actor_count = 0
for _, actor in ipairs(sd.world.list_actors() or {}) do
  local type_id = tonumber(actor.object_type_id) or 0
  if type_id == 0x1391 or type_id == 0x1392 then
    scripted_setpiece_actor_count = scripted_setpiece_actor_count + 1
  end
end
emit('blank_mode', sd.runtime.get_environment_variable('SDMOD_TEST_BLANK_BONEYARD') or '')
emit('world', string.format('0x%08X', world))
emit('scripted_setpiece_actor_count', scripted_setpiece_actor_count)
emit('primary_gate_blocked', gameplay ~= 0 and u8(gameplay + offset('gameplay_primary_gate_block_flag')) or -1)
emit('cast_ui_blocked', gameplay ~= 0 and u8(gameplay + offset('gameplay_cast_ui_block_flag')) or -1)
emit('scenery_count', list_count('actor_world_scenery_object_list'))
emit('road_count', list_count('actor_world_road_list'))
emit('fence_count', list_count('actor_world_fence_list'))
emit('movement_circle_count', movement_circle_count)
emit('scenery_circle_count', scenery_circle_count)
emit('static_circle_count', u32(controller + offset('movement_controller_static_circle_count')))
emit('shape_count', u32(controller + offset('movement_controller_shape_count')))
"""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def nav_summary(
    pipe_name: str,
    timeout: float = 8.0,
    *,
    expected_actor_count: int | None = None,
) -> dict[str, Any]:
    # get_nav_grid() queues its first snapshot rebuild on the gameplay thread,
    # so the first Lua call after run entry is expected to report no grid.
    deadline = time.monotonic() + timeout
    summary: dict[str, Any] = {}
    while time.monotonic() < deadline:
        values = parse_key_values(lua(pipe_name, NAV_SUMMARY_LUA, timeout=5.0))
        summary = dict(values)
        for key in (
            "cell_count",
            "sample_count",
            "traversable_count",
            "replicated_actor_count",
            "replicated_actor_total_count",
        ):
            summary[key] = int(float(values.get(key, "0") or 0))
        for key in ("min_x", "max_x", "min_y", "max_y"):
            summary[key] = float(values.get(key, "0") or 0.0)
        summary["span_x"] = summary["max_x"] - summary["min_x"]
        summary["span_y"] = summary["max_y"] - summary["min_y"]
        summary["broad_nav_grid"] = (
            values.get("grid_valid") == "true"
            and summary["traversable_count"] >= 16
            and summary["span_x"] >= 400.0
            and summary["span_y"] >= 400.0
        )
        if (
            values.get("scene") == "testrun"
            and values.get("replicated_valid") == "true"
            and summary["broad_nav_grid"]
            and (
                expected_actor_count is None
                or (
                    summary["replicated_actor_count"] == expected_actor_count
                    and summary["replicated_actor_total_count"]
                    == expected_actor_count
                )
            )
        ):
            return summary
        time.sleep(0.1)
    expectation = (
        ""
        if expected_actor_count is None
        else f" with {expected_actor_count} replicated actors"
    )
    raise VerifyFailure(
        f"flat boneyard did not expose a broad replicated nav grid{expectation}: "
        f"{summary}"
    )


def wait_for_blank_arena_census(
    pipe_name: str,
    timeout: float = 10.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = parse_key_values(lua(pipe_name, BLANK_ARENA_CENSUS_LUA))
        if (
            last.get("blank_mode") == "1"
            and int(last.get("scripted_setpiece_actor_count", "-1")) == 0
            and int(last.get("primary_gate_blocked", "-1")) == 0
            and int(last.get("cast_ui_blocked", "-1")) == 0
            and int(last.get("scenery_count", "-1")) == 0
            and int(last.get("road_count", "-1")) == 0
            and int(last.get("fence_count", "-1")) == 0
            and int(last.get("static_circle_count", "-1")) == 0
            and int(last.get("scenery_circle_count", "-1")) == 0
        ):
            return {
                "blank_mode": last["blank_mode"],
                "world": last["world"],
                "scripted_setpiece_actor_count": int(
                    last["scripted_setpiece_actor_count"]
                ),
                "primary_gate_blocked": int(last["primary_gate_blocked"]),
                "cast_ui_blocked": int(last["cast_ui_blocked"]),
                "scenery_count": int(last["scenery_count"]),
                "road_count": int(last["road_count"]),
                "fence_count": int(last["fence_count"]),
                "movement_circle_count": int(last["movement_circle_count"]),
                "scenery_circle_count": int(last["scenery_circle_count"]),
                "static_circle_count": int(last["static_circle_count"]),
                "shape_count": int(last["shape_count"]),
            }
        time.sleep(0.1)
    raise VerifyFailure(
        f"explicit blank arena was not reconciled on {pipe_name}: {last}"
    )


def wait_for_enemy_convergence(
    network_id: int,
    x: float,
    y: float,
    expected_hp: float,
    timeout: float = 8.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        host = find_target(
            HOST_PIPE,
            x,
            y,
            network_id,
            timeout=0.5,
            require_local_binding=False,
        )
        client = find_target(
            CLIENT_PIPE,
            x,
            y,
            network_id,
            timeout=0.5,
        )
        host_snapshot_hp = float(host.get("snapshot.hp", "nan"))
        client_snapshot_hp = float(client.get("snapshot.hp", "nan"))
        client_local_hp = float(client.get("local.hp", "nan"))
        last = {"host": host, "client": client}
        if all(
            math.isfinite(value) and abs(value - expected_hp) <= 0.05
            for value in (host_snapshot_hp, client_snapshot_hp, client_local_hp)
        ):
            return last
        time.sleep(0.1)
    raise VerifyFailure(
        f"flat-arena enemy did not converge to {expected_hp:.3f} HP on both instances: {last}"
    )


def run() -> dict[str, Any]:
    if not FIXTURE.is_file():
        raise VerifyFailure(f"flat boneyard fixture is missing: {FIXTURE}")
    fixture_hash = sha256(FIXTURE)
    if fixture_hash != EXPECTED_SHA256:
        raise VerifyFailure(
            f"flat boneyard checksum mismatch: expected={EXPECTED_SHA256} actual={fixture_hash}"
        )

    result: dict[str, Any] = {
        "ok": False,
        "fixture": {
            "path": str(FIXTURE),
            "bytes": FIXTURE.stat().st_size,
            "sha256": fixture_hash,
        },
    }
    result["launch"] = launch_pair(
        god_mode=True,
        test_survival_boneyard_override=FIXTURE,
        test_blank_boneyard=True,
    )

    staged_paths = {
        "host": ROOT / "runtime" / "instances" / "local-mp-host" / "stage" / "data" / "levels" / "survival.boneyard",
        "client": ROOT / "runtime" / "instances" / "local-mp-client" / "stage" / "data" / "levels" / "survival.boneyard",
    }
    result["staged_overrides"] = {}
    for label, path in staged_paths.items():
        staged_hash = sha256(path) if path.is_file() else ""
        result["staged_overrides"][label] = {
            "path": str(path),
            "sha256": staged_hash,
            "matches_fixture": staged_hash == fixture_hash,
        }
        if staged_hash != fixture_hash:
            raise VerifyFailure(f"{label} staged survival.boneyard did not match the fixture: {path}")

    disable_bots()
    result["hub_ready"] = {
        "host_observes_client": wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "hub"),
        "client_observes_host": wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "hub"),
    }
    result["manual_spawner_prearm"] = {
        "host": set_manual_spawner_test_mode(HOST_PIPE, True),
        "client": set_manual_spawner_test_mode(CLIENT_PIPE, True),
    }
    for label, state in result["manual_spawner_prearm"].items():
        if state.get("ok") != "true" or state.get("active") != "true":
            raise VerifyFailure(f"failed to prearm {label} manual spawner mode: {state}")
    result["run_entry"] = start_host_testrun_and_wait_for_clients(timeout=60.0)
    result["run_ready"] = {
        "host_observes_client": wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "testrun"),
        "client_observes_host": wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "testrun"),
    }
    result["manual_combat"] = enable_manual_stock_spawner_combat()
    result["initial_enemy_cleanup"] = cleanup_live_enemies()
    result["blank_arena"] = {
        "host": wait_for_blank_arena_census(HOST_PIPE),
        "client": wait_for_blank_arena_census(CLIENT_PIPE),
    }
    result["nav"] = {
        "host": nav_summary(HOST_PIPE, expected_actor_count=0),
        "client": nav_summary(CLIENT_PIPE, expected_actor_count=0),
    }
    result["initial_actor_set"] = {
        label: {
            "active_count": summary["replicated_actor_count"],
            "total_count": summary["replicated_actor_total_count"],
        }
        for label, summary in result["nav"].items()
    }
    for label, actor_set in result["initial_actor_set"].items():
        if actor_set != {"active_count": 0, "total_count": 0}:
            raise VerifyFailure(
                f"{label} flat boneyard was not empty before manual test spawning: {actor_set}"
            )

    # The explicit test mode removes stock-generated scenery while preserving
    # native floor and weather rendering. Keep the strong unique-color check,
    # but allow more dominant background area than the generic default.
    flat_capture_dominant_limit = 0.85
    result["screenshots"] = {
        "host": capture_game_backbuffer(
            HOST_PIPE,
            HOST_SCREENSHOT,
            maximum_dominant_fraction=flat_capture_dominant_limit,
        ),
        "client": capture_game_backbuffer(
            CLIENT_PIPE,
            CLIENT_SCREENSHOT,
            maximum_dominant_fraction=flat_capture_dominant_limit,
        ),
    }

    host_state = query(HOST_PIPE)
    anchor = (float(host_state["player.x"]), float(host_state["player.y"]))
    result["clear_lane"] = select_clear_kill_lane(anchor)
    lane_x = float(result["clear_lane"]["x"])
    lane_y = float(result["clear_lane"]["y"])
    result["spawn"] = spawn_one_enemy(lane_x, lane_y, setup_hp=40.0)
    network_id = int(result["spawn"]["result"]["network_actor_id"])
    result["enemy_views"] = wait_for_enemy_convergence(
        network_id,
        lane_x,
        lane_y,
        expected_hp=40.0,
    )

    result["ok"] = True
    return result


def main() -> int:
    result: dict[str, Any] = {"ok": False}
    try:
        stop_games()
        result = run()
        return_code = 0
    except Exception as exc:
        result["error"] = str(exc)
        return_code = 1
    finally:
        stop_games()

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "ok": result.get("ok", False),
        "error": result.get("error"),
        "fixture": result.get("fixture"),
        "staged_overrides": result.get("staged_overrides"),
        "blank_arena": result.get("blank_arena"),
        "nav": result.get("nav"),
        "enemy_views": result.get("enemy_views"),
        "screenshots": result.get("screenshots"),
        "output": str(OUTPUT),
    }, indent=2, sort_keys=True))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
