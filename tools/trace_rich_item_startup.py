#!/usr/bin/env python3
"""Launch Solomon Dark, arm stock startup attachment traces, drive stock startup, and dump trace hits."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
LUA_EXEC = ROOT / "tools" / "lua-exec.py"
OUTPUT_PATH = ROOT / "runtime" / "startup_attachment_trace.json"

TRACE_FINALIZE = 0x005CFA80
TRACE_ATTACH = 0x005758D2
TRACE_RICH_ITEM_BUILD = 0x004645B0
TRACE_RICH_ITEM_CLONE = 0x004699B0
LUA_BUSY_RETRY_COUNT = 20
LUA_BUSY_RETRY_DELAY_SECONDS = 0.25


def run_lua(code: str) -> str:
    last_message = "Lua exec failed."
    for attempt in range(LUA_BUSY_RETRY_COUNT):
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

        last_message = result.stderr.strip() or result.stdout.strip() or "Lua exec failed."
        if "Lua engine is busy executing on another thread" not in last_message:
            break

        if attempt + 1 < LUA_BUSY_RETRY_COUNT:
            time.sleep(LUA_BUSY_RETRY_DELAY_SECONDS)

    raise RuntimeError(last_message)


def parse_key_values(output: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def query_snapshot() -> dict[str, str]:
    code = r"""
local scene = sd.world and sd.world.get_scene and sd.world.get_scene()
local snap = sd.ui and sd.ui.get_snapshot and sd.ui.get_snapshot()
local function emit(key, value)
  print(key .. "=" .. tostring(value))
end
emit("scene", scene and scene.name or "")
emit("transitioning", scene and scene.transitioning or false)
emit("surface", snap and snap.surface_id or "")
"""
    return parse_key_values(run_lua(code))


def wait_for_surface(surface_id: str, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    last = {}
    while time.monotonic() < deadline:
        last = query_snapshot()
        if last.get("surface") == surface_id:
            print(f"[trace-startup] surface={surface_id} reached", flush=True)
            return
        time.sleep(0.25)
    raise RuntimeError(f"Timed out waiting for surface '{surface_id}'. Last={last}")


def wait_for_any_surface(surface_ids: list[str], timeout_seconds: float) -> str:
    deadline = time.monotonic() + timeout_seconds
    wanted = set(surface_ids)
    last = {}
    while time.monotonic() < deadline:
        last = query_snapshot()
        surface = last.get("surface", "")
        if surface in wanted:
            print(f"[trace-startup] surface={surface} reached", flush=True)
            return surface
        time.sleep(0.25)
    raise RuntimeError(f"Timed out waiting for any surface {surface_ids}. Last={last}")


def wait_for_create_or_transition(timeout_seconds: float) -> str:
    deadline = time.monotonic() + timeout_seconds
    last = {}
    while time.monotonic() < deadline:
        last = query_snapshot()
        surface = last.get("surface", "")
        if surface == "create":
            print("[trace-startup] surface=create reached", flush=True)
            return "create"
        if last.get("scene") == "transition" or last.get("transitioning") == "True":
            print("[trace-startup] scene transition reached before create surface", flush=True)
            return "transition"
        time.sleep(0.25)
    raise RuntimeError(f"Timed out waiting for create surface or transition. Last={last}")


def wait_for_scene(scene_name: str, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    last = {}
    while time.monotonic() < deadline:
        last = query_snapshot()
        if last.get("scene") == scene_name and last.get("transitioning") == "False":
            print(f"[trace-startup] scene={scene_name} reached", flush=True)
            return
        time.sleep(0.25)
    raise RuntimeError(f"Timed out waiting for scene '{scene_name}'. Last={last}")


def activate_action(action_id: str, surface_id: str) -> None:
    code = f"""
local ok, result = sd.ui.activate_action({json.dumps(action_id)}, {json.dumps(surface_id)})
print("ok=" .. tostring(ok))
print("result=" .. tostring(result))
"""
    result = parse_key_values(run_lua(code))
    if result.get("ok") != "true":
        raise RuntimeError(f"activate_action failed: action={action_id} surface={surface_id} result={result}")
    print(f"[trace-startup] activate {surface_id}:{action_id}", flush=True)


def arm_traces() -> None:
    code = f"""
pcall(sd.debug.untrace_function, {TRACE_FINALIZE})
pcall(sd.debug.untrace_function, {TRACE_ATTACH})
pcall(sd.debug.untrace_function, {TRACE_RICH_ITEM_BUILD})
pcall(sd.debug.untrace_function, {TRACE_RICH_ITEM_CLONE})
sd.debug.clear_trace_hits("trace_gameplay_finalize_player_start")
sd.debug.clear_trace_hits("trace_equip_attachment_sink_attach")
sd.debug.clear_trace_hits("trace_rich_item_build")
sd.debug.clear_trace_hits("trace_rich_item_clone")
print("finalize=" .. tostring(sd.debug.trace_function({TRACE_FINALIZE}, "trace_gameplay_finalize_player_start")))
print("finalize_error=" .. tostring(sd.debug.get_last_error and sd.debug.get_last_error() or ""))
print("attach=" .. tostring(sd.debug.trace_function({TRACE_ATTACH}, "trace_equip_attachment_sink_attach")))
print("attach_error=" .. tostring(sd.debug.get_last_error and sd.debug.get_last_error() or ""))
print("rich_build=" .. tostring(sd.debug.trace_function({TRACE_RICH_ITEM_BUILD}, "trace_rich_item_build")))
print("rich_build_error=" .. tostring(sd.debug.get_last_error and sd.debug.get_last_error() or ""))
print("rich_clone=" .. tostring(sd.debug.trace_function({TRACE_RICH_ITEM_CLONE}, "trace_rich_item_clone")))
print("rich_clone_error=" .. tostring(sd.debug.get_last_error and sd.debug.get_last_error() or ""))
"""
    result = parse_key_values(run_lua(code))
    if (
        result.get("finalize") != "true" or
        result.get("attach") != "true" or
        result.get("rich_build") != "true" or
        result.get("rich_clone") != "true"
    ):
        raise RuntimeError(f"Failed to arm traces: {result}")
    print(
        "[trace-startup] armed finalize_player_start + equip_attachment_sink_attach + rich_item_build + rich_item_clone",
        flush=True)


def start_testrun() -> None:
    code = """
print("ok=" .. tostring(sd.hub.start_testrun()))
"""
    result = parse_key_values(run_lua(code))
    if result.get("ok") != "true":
        raise RuntimeError(f"sd.hub.start_testrun failed: {result}")
    print("[trace-startup] requested testrun", flush=True)


def collect_hits() -> dict[str, object]:
    code = r"""
local finalize_hits = sd.debug.get_trace_hits("trace_gameplay_finalize_player_start") or {}
local attach_hits = sd.debug.get_trace_hits("trace_equip_attachment_sink_attach") or {}
local rich_build_hits = sd.debug.get_trace_hits("trace_rich_item_build") or {}
local rich_clone_hits = sd.debug.get_trace_hits("trace_rich_item_clone") or {}
local function emit_hits(prefix, hits)
  print(prefix .. ".count=" .. tostring(#hits))
  for index = 1, math.min(#hits, 16) do
    local hit = hits[index]
    print(string.format("%s.%d.ecx=0x%X", prefix, index, hit.ecx or 0))
    print(string.format("%s.%d.arg0=0x%X", prefix, index, hit.arg0 or 0))
    print(string.format("%s.%d.arg1=0x%X", prefix, index, hit.arg1 or 0))
    print(string.format("%s.%d.arg2=0x%X", prefix, index, hit.arg2 or 0))
    print(string.format("%s.%d.ret=0x%X", prefix, index, hit.ret or 0))
  end
end
emit_hits("finalize", finalize_hits)
emit_hits("attach", attach_hits)
emit_hits("rich_build", rich_build_hits)
emit_hits("rich_clone", rich_clone_hits)
"""
    return parse_key_values(run_lua(code))


def launch_game() -> None:
    command = (
        "Get-Process SolomonDark,SolomonDarkModLauncher -ErrorAction SilentlyContinue | "
        "Stop-Process -Force -ErrorAction SilentlyContinue; "
        "Start-Sleep -Milliseconds 750; "
        f"Set-Location '{ROOT}'; "
        "$env:SDMOD_UI_SANDBOX_PRESET='diagnostic_get_state'; "
        "Start-Process -FilePath 'dist\\launcher\\SolomonDarkModLauncher.exe' "
        "-ArgumentList 'launch' -WorkingDirectory 'dist\\launcher' | Out-Null"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "Launch failed."
        raise RuntimeError(message)
    print("[trace-startup] launcher finished", flush=True)


def main() -> int:
    print("[trace-startup] launch", flush=True)
    launch_game()
    print("[trace-startup] wait dialog/main_menu", flush=True)
    first_surface = wait_for_any_surface(["dialog", "main_menu"], 20.0)
    arm_traces()
    if first_surface == "dialog":
        activate_action("dialog.primary", "dialog")
        print("[trace-startup] wait main_menu", flush=True)
        wait_for_surface("main_menu", 10.0)
    activate_action("main_menu.play", "main_menu")
    wait_for_surface("main_menu", 10.0)
    activate_action("main_menu.new_game", "main_menu")
    next_stage = wait_for_create_or_transition(15.0)
    if next_stage == "create":
        activate_action("create.select_element_water", "create")
        print("[trace-startup] delay before discipline", flush=True)
        time.sleep(3.0)
        activate_action("create.select_discipline_arcane", "create")
        print("[trace-startup] long settle before testrun", flush=True)
        time.sleep(18.0)
        start_testrun()
    wait_for_scene("testrun", 30.0)
    print("[trace-startup] settle in testrun", flush=True)
    time.sleep(5.0)
    hits = collect_hits()
    OUTPUT_PATH.write_text(json.dumps(hits, indent=2), encoding="utf-8")
    print(json.dumps(hits, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
