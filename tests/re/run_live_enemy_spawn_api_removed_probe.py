#!/usr/bin/env python3
"""Live regression probe for removal of the manual enemy-spawn API.

The loader must not expose `sd.world.spawn_enemy` or
`sd.world.get_last_spawned_enemy`: those APIs depended on an incomplete
`0x00469580` call shape. Enemy creation for tests and gameplay must come from
the native wave spawner and the semantic tracked-enemy surface instead.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import cast_state_probe as csp  # noqa: E402


OUTPUT_PATH = ROOT / "runtime" / "live_enemy_spawn_api_removed_probe.json"


class LiveEnemySpawnApiRemovedProbeFailure(RuntimeError):
    pass


def query_world_api_surface() -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            """
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
emit('world_type', type(sd.world))
emit('spawn_enemy_type', type(sd.world and sd.world.spawn_enemy))
emit('get_last_spawned_enemy_type', type(sd.world and sd.world.get_last_spawned_enemy))
emit('list_actors_type', type(sd.world and sd.world.list_actors))
emit('spawn_reward_type', type(sd.world and sd.world.spawn_reward))
emit('start_waves_type', type(sd.gameplay and sd.gameplay.start_waves))
""".strip()
        )
    )


def validate_world_api_surface(surface: dict[str, str], label: str) -> None:
    expected = {
        "world_type": "table",
        "spawn_enemy_type": "nil",
        "get_last_spawned_enemy_type": "nil",
        "list_actors_type": "function",
        "spawn_reward_type": "function",
        "start_waves_type": "function",
    }
    mismatches = [
        f"{key}: expected {expected_value}, got {surface.get(key)!r}"
        for key, expected_value in expected.items()
        if surface.get(key) != expected_value
    ]
    if mismatches:
        raise LiveEnemySpawnApiRemovedProbeFailure(
            f"{label} API surface mismatch: " + "; ".join(mismatches)
        )


def run_probe(element: str, discipline: str) -> dict[str, Any]:
    result: dict[str, Any] = {"navigation": []}
    result["launcher_freshness"] = csp.ensure_launcher_bundle_fresh()

    csp.stop_game()
    csp.clear_loader_log()
    csp.launch_game()
    process_id = csp.wait_for_game_process()
    result["process_id"] = process_id
    csp.wait_for_lua_pipe()
    result["navigation"].append({"step": "launch", "process_id": process_id})

    hub_flow = csp.drive_hub_flow(process_id, element=element, discipline=discipline, prefer_resume=False)
    result["navigation"].append({"step": "hub_ready", "flow": hub_flow})
    hub_surface = query_world_api_surface()
    validate_world_api_surface(hub_surface, "hub")
    result["hub_surface"] = hub_surface

    csp.start_run_and_waves()
    csp.boost_player_survival()
    enemy = csp.wait_for_nearest_enemy(timeout_s=30.0, max_gap=5000.0)
    if csp.int_value(enemy, "actor_address") == 0:
        raise LiveEnemySpawnApiRemovedProbeFailure(f"native wave spawner produced no tracked enemy: {enemy}")
    result["navigation"].append({"step": "native_wave_enemy", "enemy": enemy})

    run_surface = query_world_api_surface()
    validate_world_api_surface(run_surface, "run")
    result["run_surface"] = run_surface
    result["loader_log_tail"] = csp.tail_loader_log(160)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--element", default="fire", choices=sorted(csp.CREATE_ELEMENT_CENTERS))
    parser.add_argument("--discipline", default="mind", choices=sorted(csp.CREATE_DISCIPLINE_CENTERS))
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--json", action="store_true", help="Only print structured JSON.")
    parser.add_argument("--keep-running", action="store_true", help="Leave the game process running after the probe.")
    args = parser.parse_args()

    result: dict[str, Any]
    exit_code = 0
    try:
        result = run_probe(args.element, args.discipline)
        result["passed"] = True
    except Exception as exc:  # noqa: BLE001 - live probes preserve diagnostics in JSON.
        result = {
            "passed": False,
            "error": str(exc),
            "loader_log_tail": csp.tail_loader_log(160),
        }
        exit_code = 1
    finally:
        if not args.keep_running:
            csp.stop_game()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        status = "passed" if exit_code == 0 else "failed"
        print(f"live enemy spawn API removal probe {status}; wrote {args.output}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
