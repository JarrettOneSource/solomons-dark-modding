#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "dist" / "launcher" / "SolomonDarkModLauncher.exe"
LUA_EXEC = ROOT / "tools" / "lua-exec.py"


class ProofFailure(RuntimeError):
    pass


def run_command(args: list[str], *, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


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
    result = run_command([sys.executable, str(LUA_EXEC), code], timeout=timeout)
    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0:
        raise ProofFailure(f"lua-exec failed with exit code {result.returncode}: {output}")
    return output


def parse_kv(output: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


SCENE_CODE = """
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


def wait_for_scene(name: str, *, timeout_s: float = 90.0) -> dict[str, str]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        values = parse_kv(run_lua(SCENE_CODE))
        if (
            values.get("available") == "true"
            and values.get("name") == name
            and values.get("transitioning") == "false"
            and values.get("world") not in {"", "0", "0x0", "nil", None}
        ):
            return values
        time.sleep(0.5)
    raise ProofFailure(f"scene {name!r} not ready before timeout")


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


def clear_bots() -> None:
    run_lua("if type(sd)=='table' and type(sd.bots)=='table' and type(sd.bots.clear)=='function' then sd.bots.clear() end")


def create_shared_hub_bot() -> int:
    output = run_lua(
        """
local p=sd.player.get_state()
local id=sd.bots.create({
  name='SharedHubProof',
  profile={
    element_id=1,
    discipline_id=1,
    level=1,
    experience=0,
    loadout={ primary_skill_id=11, primary_combo_id=22, secondary_skill_ids={33,44,55} }
  },
  scene={ kind='shared_hub' },
  ready=true,
  position={ x=(tonumber(p.x) or 0)+96.0, y=tonumber(p.y) or 0 }
})
print('bot_id='..tostring(id))
""".strip()
    )
    values = parse_kv(output)
    bot_id = int(values.get("bot_id", "0") or "0")
    if bot_id == 0:
        raise ProofFailure(f"failed to create shared hub bot: {output}")
    return bot_id


def create_private_region_bot(region_index: int, region_type_id: int) -> int:
    output = run_lua(
        f"""
local p=sd.player.get_state()
local id=sd.bots.create({{
  name='PrivateMemorator',
  profile={{
    element_id=1,
    discipline_id=1,
    level=1,
    experience=0,
    loadout={{ primary_skill_id=11, primary_combo_id=22, secondary_skill_ids={{33,44,55}} }}
  }},
  scene={{ kind='private_region', region_index={region_index}, region_type_id={region_type_id} }},
  ready=true,
  position={{ x=(tonumber(p.x) or 0)+96.0, y=tonumber(p.y) or 0 }}
}})
print('bot_id='..tostring(id))
""".strip()
    )
    values = parse_kv(output)
    bot_id = int(values.get("bot_id", "0") or "0")
    if bot_id == 0:
        raise ProofFailure(f"failed to create private bot: {output}")
    return bot_id


def get_bot_state(bot_id: int) -> dict[str, str]:
    output = run_lua(
        f"""
local s=sd.bots.get_state({bot_id})
if type(s)~='table' then
  print('available=false')
  return
end
print('available='..tostring(s.available))
print('actor='..tostring(s.actor_address))
print('x='..tostring(s.x))
print('y='..tostring(s.y))
if type(s.scene)=='table' then
  print('kind='..tostring(s.scene.kind))
  print('region='..tostring(s.scene.region_index))
  print('region_type='..tostring(s.scene.region_type_id))
end
""".strip()
    )
    return parse_kv(output)


def wait_for_bot_state(
    bot_id: int,
    *,
    expect_kind: str,
    materialized: bool,
    timeout_s: float = 20.0,
) -> dict[str, str]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        values = get_bot_state(bot_id)
        actor = values.get("actor")
        actor_materialized = actor not in {"", "0", "0x0", "nil", None}
        if values.get("kind") == expect_kind and actor_materialized == materialized:
            return values
        time.sleep(0.25)
    raise ProofFailure(
        f"bot {bot_id} failed expected state kind={expect_kind} materialized={materialized}; last={json.dumps(values, sort_keys=True)}"
    )


def switch_region(region_index: int) -> None:
    output = run_lua(f"print('ok='..tostring(sd.debug.switch_region({region_index})))", timeout=10.0)
    values = parse_kv(output)
    if values.get("ok") != "true":
        raise ProofFailure(f"switch_region({region_index}) failed: {output}")


def discover_log_path() -> Path | None:
    candidates = [
        ROOT / "runtime" / "logs" / "solomondarkmodloader.log",
        ROOT / "runtime" / "stage" / ".sdmod" / "logs" / "solomondarkmodloader.log",
        ROOT / "dist" / "launcher" / "runtime" / "logs" / "solomondarkmodloader.log",
        ROOT / "dist" / "runtime" / "logs" / "solomondarkmodloader.log",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def print_log_tail() -> None:
    log_path = discover_log_path()
    if log_path is None:
        return
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    tail = "\n".join(lines[-120:])
    print("log_tail_begin")
    print(tail)
    print("log_tail_end")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--launch", action="store_true", help="stop existing game processes and launch a fresh session")
    args = parser.parse_args()

    try:
        if args.launch:
            stop_game()
            launch_game()
        wait_for_lua_pipe()

        hub = wait_for_scene("hub")
        clear_bots()

        shared_bot_id = create_shared_hub_bot()
        shared_hub = wait_for_bot_state(shared_bot_id, expect_kind="SharedHub", materialized=True)

        switch_region(1)
        memorator = wait_for_scene("memorator")
        shared_hidden = wait_for_bot_state(shared_bot_id, expect_kind="SharedHub", materialized=False)

        region_index = int(memorator["region"])
        region_type_id = int(memorator["region_type"])
        private_bot_id = create_private_region_bot(region_index, region_type_id)
        private_mem = wait_for_bot_state(private_bot_id, expect_kind="PrivateRegion", materialized=True)

        switch_region(0)
        hub_return = wait_for_scene("hub")
        shared_back = wait_for_bot_state(shared_bot_id, expect_kind="SharedHub", materialized=True, timeout_s=30.0)
        private_hidden = wait_for_bot_state(private_bot_id, expect_kind="PrivateRegion", materialized=False, timeout_s=10.0)

        result = {
            "hub": hub,
            "shared_hub": shared_hub,
            "memorator": memorator,
            "shared_hidden_in_memorator": shared_hidden,
            "private_in_memorator": private_mem,
            "hub_return": hub_return,
            "shared_back_in_hub": shared_back,
            "private_hidden_in_hub": private_hidden,
            "split_scene_ok": True,
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except ProofFailure as exc:
        print(f"proof_failed={exc}")
        print_log_tail()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
