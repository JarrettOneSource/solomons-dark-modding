#!/usr/bin/env python3
"""Capture the stock arena combat-state transition before and after start_waves."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

import cast_state_probe as csp


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = ROOT / "runtime" / "probe_combat_state_transition.json"


class CombatProbeFailure(RuntimeError):
    pass


def query_combat_snapshot() -> dict[str, str]:
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

local scene = sd.world and sd.world.get_scene and sd.world.get_scene()
local world = sd.world and sd.world.get_state and sd.world.get_state()
local combat = sd.gameplay and sd.gameplay.get_combat_state and sd.gameplay.get_combat_state()
local gameplay_global = sd.debug and sd.debug.read_ptr and sd.debug.read_ptr(0x0081C264) or 0

emit("scene.available", type(scene) == "table")
if type(scene) == "table" then
  emit("scene.kind", scene.kind)
  emit("scene.name", scene.name)
  emit("scene.world_id", scene.world_id)
  emit("scene.arena_id", scene.arena_id)
  emit("scene.region_index", scene.region_index)
  emit("scene.region_type_id", scene.region_type_id)
end

emit("world.available", type(world) == "table")
if type(world) == "table" then
  emit("world.wave", world.wave)
  emit("world.enemy_count", world.enemy_count)
  emit("world.time_elapsed_ms", world.time_elapsed_ms)
end

emit("combat.available", type(combat) == "table")
if type(combat) == "table" then
  for _, key in ipairs({
    "arena_id",
    "section_index",
    "wave_index",
    "wait_ticks",
    "advance_mode",
    "advance_threshold",
    "wave_counter",
    "started_music",
    "transition_requested",
    "active"
  }) do
    emit("combat." .. key, combat[key])
  end
end

emit("raw.gameplay_global", gameplay_global)
if gameplay_global ~= nil and gameplay_global ~= 0 then
  emit("raw.gameplay_global_1abe", sd.debug.read_u8(gameplay_global + 0x1ABE))
  emit("raw.gameplay_global_1c30", sd.debug.read_u16(gameplay_global + 0x1C30))
end
""".strip()
        )
    )


def wait_for_testrun() -> dict[str, str]:
    return csp.wait_for_scene("testrun", timeout_s=45.0)


def start_testrun_without_waves() -> dict[str, str]:
    scene = csp.query_scene_state()
    if csp.is_settled_scene(scene, "testrun"):
        return scene
    values = csp.parse_key_values(csp.run_lua("print('ok='..tostring(sd.hub.start_testrun()))"))
    if values.get("ok") != "true":
        raise CombatProbeFailure(f"sd.hub.start_testrun failed: {values}")
    return wait_for_testrun()


def current_game_pid() -> int:
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "(Get-Process SolomonDark -ErrorAction Stop | Select-Object -First 1 -ExpandProperty Id)",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise CombatProbeFailure(
            f"failed to resolve SolomonDark pid\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return int(result.stdout.strip(), 10)


def launch_clean_testrun(element: str, discipline: str) -> list[dict[str, object]]:
    navigation: list[dict[str, object]] = []
    csp.stop_game()
    time.sleep(1.0)
    csp.clear_loader_log()
    csp.launch_game()
    csp.wait_for_lua_pipe()
    pid = current_game_pid()
    navigation.append({"step": "game_started", "pid": pid})
    hub_flow = csp.drive_hub_flow(pid, element=element, discipline=discipline, prefer_resume=True)
    navigation.append({"step": "hub_ready", "flow": hub_flow, "scene": csp.query_scene_state()})
    navigation.append({"step": "testrun_ready", "scene": start_testrun_without_waves()})
    return navigation


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture the stock arena combat-state cluster before and after start_waves."
    )
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--element", default="water", choices=tuple(csp.CREATE_ELEMENT_CENTERS.keys()))
    parser.add_argument("--discipline", default="arcane", choices=tuple(csp.CREATE_DISCIPLINE_CENTERS.keys()))
    parser.add_argument("--attach", action="store_true", help="Attach to the current live game instead of relaunching.")
    parser.add_argument(
        "--skip-start-waves",
        action="store_true",
        help="Only capture the pre-wave combat state without dispatching sd.gameplay.start_waves().",
    )
    parser.add_argument(
        "--enable-combat-prelude",
        action="store_true",
        help="Dispatch sd.gameplay.enable_combat_prelude() instead of sd.gameplay.start_waves().",
    )
    args = parser.parse_args()

    result: dict[str, object] = {
        "launcher_freshness": csp.ensure_launcher_bundle_fresh(),
        "element": args.element,
        "discipline": args.discipline,
        "attach": args.attach,
        "skip_start_waves": args.skip_start_waves,
        "enable_combat_prelude": args.enable_combat_prelude,
        "navigation": [],
    }

    try:
        if args.attach:
            csp.wait_for_lua_pipe()
            result["navigation"].append({"step": "attached", "scene": csp.query_scene_state()})
        else:
            result["navigation"] = launch_clean_testrun(args.element, args.discipline)

        result["before"] = query_combat_snapshot()
        if not args.skip_start_waves:
            if args.enable_combat_prelude:
                dispatch_result = csp.parse_key_values(
                    csp.run_lua("print('ok='..tostring(sd.gameplay.enable_combat_prelude()))")
                )
                result["enable_combat_prelude"] = dispatch_result
                if dispatch_result.get("ok") != "true":
                    raise CombatProbeFailure(
                        f"sd.gameplay.enable_combat_prelude failed: {dispatch_result}"
                    )
            else:
                dispatch_result = csp.parse_key_values(
                    csp.run_lua("print('ok='..tostring(sd.gameplay.start_waves()))")
                )
                result["start_waves"] = dispatch_result
                if dispatch_result.get("ok") != "true":
                    raise CombatProbeFailure(f"sd.gameplay.start_waves failed: {dispatch_result}")
            time.sleep(1.0)
            result["after"] = query_combat_snapshot()
        else:
            result["after"] = None
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        raise

    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
