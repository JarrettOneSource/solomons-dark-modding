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
    spawn_one_enemy,
)
from verify_real_input_spell_cast_sync import detect_instance_pids


FIXTURE = ROOT / "tests" / "fixtures" / "boneyards" / "flat_multiplayer_test.boneyard"
EXPECTED_SHA256 = "8ae9cd4d371f926b7bf24b05d2a1b1a2a521d797e3f925f3ed9447e8bcff3828"
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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def nav_summary(pipe_name: str, timeout: float = 8.0) -> dict[str, Any]:
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
        ):
            return summary
        time.sleep(0.1)
    raise VerifyFailure(f"flat boneyard did not expose a broad replicated nav grid: {summary}")


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
    result["run_entry"] = start_host_testrun_and_wait_for_clients(timeout=60.0)
    result["run_ready"] = {
        "host_observes_client": wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "testrun"),
        "client_observes_host": wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "testrun"),
    }
    result["nav"] = {
        "host": nav_summary(HOST_PIPE),
        "client": nav_summary(CLIENT_PIPE),
    }
    result["initial_actor_set"] = {
        label: {
            "active_count": summary["replicated_actor_count"],
            "total_count": summary["replicated_actor_total_count"],
        }
        for label, summary in result["nav"].items()
    }
    for label, actor_set in result["initial_actor_set"].items():
        if actor_set != {"active_count": 2, "total_count": 2}:
            raise VerifyFailure(
                f"{label} flat boneyard was not empty before manual test spawning: {actor_set}"
            )

    pids = detect_instance_pids()
    # The fixture intentionally presents a large, uniform flat floor. Keep the
    # strong unique-color check, but allow more dominant background area than
    # the generic scene-capture default.
    flat_capture_dominant_limit = 0.85
    result["screenshots"] = {
        "host": capture_game_backbuffer(
            HOST_PIPE,
            pids["host"],
            HOST_SCREENSHOT,
            maximum_dominant_fraction=flat_capture_dominant_limit,
        ),
        "client": capture_game_backbuffer(
            CLIENT_PIPE,
            pids["client"],
            CLIENT_SCREENSHOT,
            maximum_dominant_fraction=flat_capture_dominant_limit,
        ),
    }

    result["manual_combat"] = enable_manual_stock_spawner_combat()
    cleanup_live_enemies()
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
        "nav": result.get("nav"),
        "enemy_views": result.get("enemy_views"),
        "screenshots": result.get("screenshots"),
        "output": str(OUTPUT),
    }, indent=2, sort_keys=True))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
