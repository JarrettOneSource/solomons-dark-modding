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
BOT_NAME = "Lua Bot Fire"


class ProofFailure(RuntimeError):
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
        raise ProofFailure(f"launcher failed with exit code {result.returncode}")


def run_lua(code: str, *, timeout: float = 20.0) -> str:
    deadline = time.time() + timeout
    last_error = ""
    while time.time() < deadline:
        result = run_command([sys.executable, str(LUA_EXEC), code], timeout=10.0)
        output = (result.stdout or "") + (result.stderr or "")
        if result.returncode == 0:
            return output
        last_error = output.strip()
        if "Lua engine is busy" not in output and "Cannot connect to pipe" not in output:
            raise ProofFailure(last_error)
        time.sleep(0.1)
    raise ProofFailure(last_error)


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
    raise ProofFailure(f"lua pipe not ready before timeout: {last_error}")


def wait_for_scene(scene_name: str, *, timeout_s: float = 90.0) -> dict[str, str]:
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
            and values.get("name") == scene_name
            and values.get("transitioning") == "false"
            and values.get("world") not in {"", "0", "0x0", "nil", None}
        ):
            return values
        time.sleep(0.25)
    raise ProofFailure(f"scene {scene_name!r} not ready before timeout")


def get_managed_bot() -> dict[str, str]:
    output = run_lua(
        f"""
local bots=sd.bots.get_state()
if type(bots)~='table' then
  print('id=nil')
  return
end
for _, bot in ipairs(bots) do
  if type(bot)=='table' and tostring(bot.name)=='{BOT_NAME}' then
    print('id='..tostring(bot.id))
    print('x='..tostring(bot.x))
    print('y='..tostring(bot.y))
    print('moving='..tostring(bot.moving))
    print('actor='..tostring(bot.actor_address))
    if type(bot.scene)=='table' then
      print('kind='..tostring(bot.scene.kind))
      print('region='..tostring(bot.scene.region_index))
      print('region_type='..tostring(bot.scene.region_type_id))
    end
    if bot.target_x~=nil then
      print('target_x='..tostring(bot.target_x))
      print('target_y='..tostring(bot.target_y))
    end
    return
  end
end
print('id=nil')
""".strip()
    )
    return parse_kv(output)


def wait_for_managed_bot(scene_kind: str, *, materialized: bool, timeout_s: float = 60.0) -> dict[str, str]:
    deadline = time.time() + timeout_s
    last = {}
    while time.time() < deadline:
        last = get_managed_bot()
        actor_materialized = last.get("actor") not in {"", "0", "0x0", "nil", None}
        if last.get("id") not in {"nil", None} and last.get("kind") == scene_kind and actor_materialized == materialized:
            return last
        time.sleep(0.25)
    raise ProofFailure(
        f"managed bot failed expected scene kind={scene_kind} materialized={materialized}; last={json.dumps(last, sort_keys=True)}"
    )


def switch_region(region_index: int) -> None:
    values = parse_kv(run_lua(f"print('ok='..tostring(sd.debug.switch_region({region_index})))"))
    if values.get("ok") != "true":
        raise ProofFailure(f"switch_region({region_index}) failed")


def arm_memorator_entrance_candidate() -> None:
    run_lua(
        """
lua_bots_debug.hub_candidate_name='memorator'
lua_bots_debug.hub_candidate_since_ms=0
lua_bots_debug.scene_entered_ms=0
""".strip()
    )


def main() -> int:
    try:
        stop_game()
        launch_game()
        wait_for_lua_pipe()
        hub = wait_for_scene("hub")
        bot_hub = wait_for_managed_bot("SharedHub", materialized=True)

        arm_memorator_entrance_candidate()
        stage_samples = []
        for step in range(20):
            sample = get_managed_bot()
            sample["step"] = step
            stage_samples.append(sample)
            time.sleep(0.25)
        staged_bot = get_managed_bot()

        switch_region(1)
        memorator = wait_for_scene("memorator")
        bot_mem = wait_for_managed_bot("PrivateRegion", materialized=False)
        for _ in range(12):
            time.sleep(0.25)
        bot_mem = get_managed_bot()

        switch_region(0)
        hub_return = wait_for_scene("hub")
        bot_hub_return = wait_for_managed_bot("SharedHub", materialized=False)
        for _ in range(12):
            time.sleep(0.25)
        bot_hub_return = get_managed_bot()

        result = {
            "hub": hub,
            "initial_bot": bot_hub,
            "memorator": memorator,
            "stage_samples": stage_samples,
            "staged_bot": staged_bot,
            "bot_in_memorator": bot_mem,
            "hub_return": hub_return,
            "bot_back_in_hub": bot_hub_return,
            "lua_follow_memorator_roundtrip_ok": True,
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except ProofFailure as exc:
        print(f"proof_failed={exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
