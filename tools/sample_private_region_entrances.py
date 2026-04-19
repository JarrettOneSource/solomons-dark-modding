#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "dist" / "launcher" / "SolomonDarkModLauncher.exe"
LUA_EXEC = ROOT / "tools" / "lua-exec.py"
REGIONS = {
    1: "memorator",
    2: "librarian",
    3: "dowser",
    4: "polisher_arch",
}


class SampleFailure(RuntimeError):
    pass


def run_command(args: list[str], *, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=timeout, check=False)


def stop_game() -> None:
    run_command(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "Get-Process SolomonDark,SolomonDarkModLauncher -ErrorAction SilentlyContinue | Stop-Process -Force",
        ]
    )


def launch_game() -> None:
    result = run_command([str(LAUNCHER), "launch"], timeout=120.0)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    if result.returncode != 0:
        raise SampleFailure(f"launcher failed with exit code {result.returncode}")


def run_lua(code: str, *, timeout: float = 20.0) -> str:
    deadline = time.time() + timeout
    last_error = ""
    while time.time() < deadline:
        result = run_command([sys.executable, str(LUA_EXEC), code], timeout=10.0)
        output = (result.stdout or "") + (result.stderr or "")
        if result.returncode == 0:
            return output
        last_error = output.strip()
        if "Lua engine is busy" not in output:
            raise SampleFailure(last_error)
        time.sleep(0.1)
    raise SampleFailure(last_error)


def parse_kv(output: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def wait_for_lua_pipe(*, timeout_s: float = 60.0) -> None:
    deadline = time.time() + timeout_s
    last_error = ""
    while time.time() < deadline:
        result = run_command([sys.executable, str(LUA_EXEC), "print('ready=true')"], timeout=10.0)
        output = (result.stdout or "") + (result.stderr or "")
        if result.returncode == 0 and "ready=true" in output:
            return
        last_error = output.strip()
        time.sleep(0.5)
    raise SampleFailure(f"lua pipe not ready before timeout: {last_error}")


def wait_for_scene(name: str, *, timeout_s: float = 90.0) -> dict[str, str]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        values = parse_kv(
            run_lua(
                """
local s=sd.world.get_scene()
if type(s)~='table' then
  print('available=false')
  return
end
print('available=true')
print('name='..tostring(s.name))
print('region='..tostring(s.region_index))
print('region_type='..tostring(s.region_type_id))
print('transitioning='..tostring(s.transitioning))
print('world='..tostring(s.world_id))
""".strip()
            )
        )
        if (
            values.get("available") == "true"
            and values.get("name") == name
            and values.get("transitioning") == "false"
            and values.get("world") not in {"", "0", "0x0", "nil", None}
        ):
            return values
        time.sleep(0.25)
    raise SampleFailure(f"scene {name!r} not ready before timeout")


def get_player_state() -> dict[str, str]:
    return parse_kv(
        run_lua(
            """
local p=sd.player.get_state()
if type(p)~='table' then
  print('available=false')
  return
end
print('available=true')
print('x='..tostring(p.x))
print('y='..tostring(p.y))
print('heading='..tostring(p.heading))
print('actor='..tostring(p.actor_address))
""".strip()
        )
    )


def switch_region(region_index: int) -> None:
    values = parse_kv(run_lua(f"print('ok='..tostring(sd.debug.switch_region({region_index})))"))
    if values.get("ok") != "true":
        raise SampleFailure(f"switch_region({region_index}) failed")


def main() -> int:
    try:
        stop_game()
        launch_game()
        wait_for_lua_pipe()
        wait_for_scene("hub")

        results: dict[str, object] = {}
        for region_index, scene_name in REGIONS.items():
            switch_region(region_index)
            interior_scene = wait_for_scene(scene_name)
            interior_player = get_player_state()

            switch_region(0)
            hub_scene = wait_for_scene("hub")
            hub_player = get_player_state()

            results[scene_name] = {
                "region_index": region_index,
                "interior_scene": interior_scene,
                "interior_player": interior_player,
                "hub_scene": hub_scene,
                "hub_return_player": hub_player,
            }

        print(json.dumps(results, indent=2, sort_keys=True))
        return 0
    except SampleFailure as exc:
        print(f"sample_failed={exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
