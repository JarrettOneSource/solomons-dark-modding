#!/usr/bin/env python3
"""Launch Solomon Dark into a settled run and capture cast-state diagnostics."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = ROOT / "dist" / "launcher" / "SolomonDarkModLauncher.exe"
DIST_LOADER_DLL = ROOT / "dist" / "launcher" / "SolomonDarkModLoader.dll"
RELEASE_LOADER_DLL = ROOT / "bin" / "Release" / "Win32" / "SolomonDarkModLoader.dll"
LUA_EXEC = ROOT / "tools" / "lua-exec.py"
CLICK_WINDOW = ROOT / "scripts" / "click_window.py"
LOADER_LOG = ROOT / "runtime" / "stage" / ".sdmod" / "logs" / "solomondarkmodloader.log"
OUTPUT_PATH = ROOT / "runtime" / "cast_state_probe.json"

DEFAULT_ELEMENT = "fire"
DEFAULT_DISCIPLINE = "mind"
DEFAULT_BOT_SKILL_ID = 0x3EF
CREATE_ELEMENT_CENTERS = {
    "ether": (826, 369),
    "earth": (656, 417),
    "fire": (924, 515),
    "water": (650, 593),
    "air": (816, 654),
}
CREATE_DISCIPLINE_CENTERS = {
    "arcane": (725, 460),
    "body": (875, 460),
    "mind": (1025, 460),
}
CREATE_OWNER_ELEMENT_ENABLED_BYTE_OFFSET = 0x18C
CREATE_OWNER_ELEMENT_SELECTED_OFFSET = 0x1A4
CREATE_OWNER_DISCIPLINE_ENABLED_BYTE_OFFSET = 0x228
CREATE_OWNER_DISCIPLINE_SELECTED_OFFSET = 0x22C
ALLOW_MOUSE_UI_AUTOMATION = os.environ.get("SD_PROBE_ALLOW_MOUSE", "").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
ACTOR_RAW_OFFSETS = {
    "owner_ptr": ("ptr", 0x58),
    "runtime_profile_ptr": ("ptr", 0x200),
    "pure_primary_e4": ("u32", 0xE4),
    "pure_primary_e8": ("u32", 0xE8),
    "walk_x": ("float", 0x158),
    "walk_y": ("float", 0x15C),
    "spell_cfg_278_raw": ("u32", 0x278),
    "pure_primary_timer_1b8": ("float", 0x1B8),
    "pure_primary_item_sink": ("ptr", 0x1FC),
    "spell_cfg_298_raw": ("u32", 0x298),
    "spell_cfg_29c_float": ("float", 0x29C),
    "spell_cfg_2a0_float": ("float", 0x2A0),
    "spell_cfg_2a4_float": ("float", 0x2A4),
    "spell_cfg_2c8_raw": ("u32", 0x2C8),
    "spell_cfg_2cc_float": ("float", 0x2CC),
    "spell_cfg_2d0_float": ("float", 0x2D0),
    "spell_cfg_2d4_float": ("float", 0x2D4),
    "spell_cfg_2d8_float": ("float", 0x2D8),
    "heading": ("float", 0x6C),
    "cast_drive_state": ("u8", 0x160),
    "cast_no_interrupt": ("u8", 0x1EC),
    "cast_primary_skill_id": ("u32", 0x270),
    "cast_group_byte": ("u8", 0x27C),
    "cast_slot_short": ("u16", 0x27E),
    "aim_x": ("float", 0x2A8),
    "aim_y": ("float", 0x2AC),
    "aim_aux0": ("u32", 0x2B0),
    "aim_aux1": ("u32", 0x2B4),
    "aim_spread_mode": ("u8", 0x2DC),
}
PROFILE_TEMPLATE_OFFSET = 0x750
GAMEPLAY_PLAYER_PROGRESSION_HANDLE_OFFSET = 0x1654
GAMEPLAY_PLAYER_SLOT_STRIDE = 4
PROGRESSION_HP_OFFSET = 0x70
PROGRESSION_MAX_HP_OFFSET = 0x74


class ProbeFailure(RuntimeError):
    pass


def run_command(
    args: list[str],
    *,
    cwd: Path = ROOT,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def run_powershell(command: str, *, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    return run_command(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        timeout=timeout,
    )


def to_windows_path(path: Path) -> str:
    result = run_command(["wslpath", "-w", str(path)], timeout=10.0)
    if result.returncode != 0:
        raise ProbeFailure(
            f"wslpath failed for {path}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result.stdout.strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_launcher_bundle_fresh() -> dict[str, object]:
    if not DIST_LOADER_DLL.exists():
        raise ProbeFailure(f"dist loader DLL is missing: {DIST_LOADER_DLL}")
    if not RELEASE_LOADER_DLL.exists():
        raise ProbeFailure(f"release loader DLL is missing: {RELEASE_LOADER_DLL}")

    dist_hash = sha256_file(DIST_LOADER_DLL)
    release_hash = sha256_file(RELEASE_LOADER_DLL)
    result = {
        "dist_loader_dll": str(DIST_LOADER_DLL),
        "release_loader_dll": str(RELEASE_LOADER_DLL),
        "dist_hash": dist_hash,
        "release_hash": release_hash,
        "dist_size": DIST_LOADER_DLL.stat().st_size,
        "release_size": RELEASE_LOADER_DLL.stat().st_size,
        "dist_mtime": DIST_LOADER_DLL.stat().st_mtime,
        "release_mtime": RELEASE_LOADER_DLL.stat().st_mtime,
        "matches": dist_hash == release_hash,
    }
    if not result["matches"]:
        raise ProbeFailure(
            "launcher bundle is stale: "
            f"{DIST_LOADER_DLL.name} does not match {RELEASE_LOADER_DLL}. "
            "Run `pwsh ./scripts/Build-All.ps1 -Configuration Release` before probing."
        )
    return result


def stop_game() -> None:
    run_powershell(
        "Get-Process SolomonDark,SolomonDarkModLauncher -ErrorAction SilentlyContinue | "
        "Stop-Process -Force -ErrorAction SilentlyContinue",
        timeout=10.0,
    )


def clear_loader_log() -> None:
    if not LOADER_LOG.exists():
        return
    try:
        LOADER_LOG.unlink()
    except OSError:
        run_powershell(
            f"Remove-Item -LiteralPath {json.dumps(to_windows_path(LOADER_LOG))} -Force -ErrorAction SilentlyContinue",
            timeout=10.0,
        )


def launch_game() -> None:
    launcher_path = to_windows_path(LAUNCHER).replace("'", "''")
    working_directory = to_windows_path(LAUNCHER.parent).replace("'", "''")
    result = run_powershell(
        f"Start-Process -FilePath '{launcher_path}' -ArgumentList 'launch' "
        f"-WorkingDirectory '{working_directory}' | Out-Null",
        timeout=15.0,
    )
    if result.returncode != 0:
        raise ProbeFailure(
            f"launcher start failed with exit code {result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )


def wait_for_game_process(timeout_s: float = 45.0) -> int:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        result = run_powershell(
            "Get-Process SolomonDark -ErrorAction SilentlyContinue | "
            "Select-Object -First 1 -ExpandProperty Id",
            timeout=10.0,
        )
        output = (result.stdout or "").strip()
        if result.returncode == 0 and output:
            return int(output)
        time.sleep(0.25)
    raise ProbeFailure("Timed out waiting for SolomonDark to start.")


def parse_key_values(output: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def run_lua(code: str, *, timeout_s: float = 20.0) -> str:
    deadline = time.time() + timeout_s
    last_error = ""
    while time.time() < deadline:
        result = run_command([sys.executable, str(LUA_EXEC), code], timeout=10.0)
        output = (result.stdout or "") + (result.stderr or "")
        if result.returncode == 0:
            return output
        last_error = output.strip()
        if "Lua engine is busy" not in output and "Cannot connect to pipe" not in output:
            raise ProbeFailure(last_error or "lua-exec failed")
        time.sleep(0.25)
    raise ProbeFailure(last_error or "Timed out waiting for lua-exec")


def wait_for_lua_pipe(timeout_s: float = 60.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            output = run_lua("print('ready=true')", timeout_s=5.0)
        except ProbeFailure:
            time.sleep(0.25)
            continue
        if "ready=true" in output:
            return
        time.sleep(0.25)
    raise ProbeFailure("Timed out waiting for Lua exec pipe.")


def query_ui_snapshot() -> dict[str, str]:
    return parse_key_values(
        run_lua(
            """
local snap = sd.ui and sd.ui.get_snapshot and sd.ui.get_snapshot()
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
if type(snap) ~= 'table' then
  emit('available', false)
  return
end
emit('available', true)
emit('surface_id', snap.surface_id)
emit('title', snap.title)
if type(snap.elements) == 'table' then
  emit('element_count', #snap.elements)
  for i = 1, math.min(#snap.elements, 12) do
    local e = snap.elements[i]
    emit('element.' .. i .. '.label', e.label)
    emit('element.' .. i .. '.action_id', e.action_id)
    emit('element.' .. i .. '.source_object_ptr', e.source_object_ptr)
    emit('element.' .. i .. '.surface_object_ptr', e.surface_object_ptr)
    emit('element.' .. i .. '.left', e.left)
    emit('element.' .. i .. '.top', e.top)
    emit('element.' .. i .. '.right', e.right)
    emit('element.' .. i .. '.bottom', e.bottom)
  end
end
""".strip()
        )
    )


def query_scene_state() -> dict[str, str]:
    return parse_key_values(
        run_lua(
            """
local scene = sd.world and sd.world.get_scene and sd.world.get_scene()
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
if type(scene) ~= 'table' then
  emit('available', false)
  return
end
emit('available', true)
emit('name', scene.name)
emit('kind', scene.kind)
emit('transitioning', scene.transitioning)
emit('world_id', scene.world_id)
emit('scene_id', scene.scene_id or scene.id)
emit('region_index', scene.region_index)
emit('region_type_id', scene.region_type_id)
""".strip()
        )
    )


def snapshot_contains_action(snapshot: dict[str, str], action_id: str, surface_id: str) -> bool:
    if snapshot.get("available") != "true" or snapshot.get("surface_id") != surface_id:
        return False
    for index in range(1, 13):
        if snapshot.get(f"element.{index}.action_id") == action_id:
            return True
    return False


def activate_ui_action(action_id: str, surface_id: str) -> None:
    values = parse_key_values(
        run_lua(
            f"""
local ok, req = sd.ui.activate_action({json.dumps(action_id)}, {json.dumps(surface_id)})
print('ok=' .. tostring(ok))
print('request_id=' .. tostring(req))
""".strip()
        )
    )
    if values.get("ok") != "true":
        raise ProbeFailure(f"sd.ui.activate_action failed for {surface_id}:{action_id}: {values}")

    request_id = int_value(values, "request_id")
    deadline = time.time() + 15.0
    while time.time() < deadline:
        dispatch = parse_key_values(
            run_lua(
                f"""
local dispatch = sd.ui.get_action_dispatch({request_id})
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
if type(dispatch) ~= 'table' then
  emit('available', false)
  return
end
emit('available', true)
emit('status', dispatch.status)
emit('error_message', dispatch.error_message)
""".strip()
            )
        )
        if dispatch.get("available") != "true":
            time.sleep(0.1)
            continue

        status = dispatch.get("status", "")
        if status in {"queued", "dispatching"}:
            snapshot = query_ui_snapshot()
            if not snapshot_contains_action(snapshot, action_id, surface_id):
                raise ProbeFailure(
                    f"semantic UI action stale for {surface_id}:{action_id}: "
                    f"current_surface={snapshot.get('surface_id')} "
                    f"generation={snapshot.get('generation')}"
                )
            time.sleep(0.1)
            continue
        if status == "failed":
            raise ProbeFailure(
                f"semantic UI action failed for {surface_id}:{action_id}: "
                f"{dispatch.get('error_message', 'dispatch failed')}"
            )
        if status.startswith("dispatched") or status == "completed":
            return
        time.sleep(0.1)

    raise ProbeFailure(f"Timed out waiting for UI action dispatch: {surface_id}:{action_id}")


def click_create_choice(process_id: int, x: int, y: int) -> None:
    if not ALLOW_MOUSE_UI_AUTOMATION:
        raise ProbeFailure(
            "Mouse UI automation is disabled. "
            "Use semantic sd.ui.activate_action paths or set SD_PROBE_ALLOW_MOUSE=1 for a manual-click probe."
        )
    click_script = to_windows_path(CLICK_WINDOW)
    result = run_powershell(
        f"& py -3 {json.dumps(click_script)} --pid {process_id} --x {x} --y {y} --activate",
        timeout=10.0,
    )
    if result.returncode != 0:
        raise ProbeFailure(f"click_window failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")


def click_snapshot_action(process_id: int, snapshot: dict[str, str], action_id: str) -> bool:
    for index in range(1, 13):
        if snapshot.get(f"element.{index}.action_id") != action_id:
            continue
        try:
            left = float(snapshot[f"element.{index}.left"])
            top = float(snapshot[f"element.{index}.top"])
            right = float(snapshot[f"element.{index}.right"])
            bottom = float(snapshot[f"element.{index}.bottom"])
        except (KeyError, TypeError, ValueError):
            return False
        click_create_choice(process_id, int(round((left + right) * 0.5)), int(round((top + bottom) * 0.5)))
        return True
    return False


def activate_or_click_snapshot_action(
    process_id: int,
    snapshot: dict[str, str],
    action_id: str,
    surface_id: str,
) -> None:
    try:
        activate_ui_action(action_id, surface_id)
        return
    except ProbeFailure as activation_error:
        if ALLOW_MOUSE_UI_AUTOMATION and click_snapshot_action(process_id, snapshot, action_id):
            return
        raise activation_error


def is_stale_ui_action_error(error: BaseException) -> bool:
    message = str(error)
    return (
        "No live snapshot element matched target" in message
        or "surface mismatch" in message
        or "surface changed" in message
        or "semantic UI action stale" in message
        or "Timed out waiting for UI action dispatch" in message
    )


def wait_for_surface(surface_id: str, timeout_s: float = 20.0) -> dict[str, str]:
    deadline = time.time() + timeout_s
    last = {}
    while time.time() < deadline:
        last = query_ui_snapshot()
        if last.get("available") == "true" and last.get("surface_id") == surface_id:
            return last
        time.sleep(0.25)
    raise ProbeFailure(f"Timed out waiting for UI surface {surface_id}. Last snapshot={last}")


def wait_for_scene(scene_name: str, timeout_s: float = 60.0) -> dict[str, str]:
    deadline = time.time() + timeout_s
    last = {}
    while time.time() < deadline:
        last = query_scene_state()
        if (
            last.get("available") == "true"
            and last.get("name") == scene_name
            and last.get("transitioning") == "false"
            and last.get("world_id") not in {"", "0", "0x0", "nil"}
        ):
            return last
        time.sleep(0.25)
    raise ProbeFailure(f"Timed out waiting for scene {scene_name}. Last scene={last}")


def is_settled_scene(scene: dict[str, str], scene_name: str) -> bool:
    return (
        scene.get("available") == "true"
        and scene.get("name") == scene_name
        and scene.get("transitioning") == "false"
        and scene.get("world_id") not in {"", "0", "0x0", "nil"}
    )


def wait_for_any_scene(scene_names: set[str], timeout_s: float = 60.0) -> dict[str, str]:
    deadline = time.time() + timeout_s
    last = {}
    while time.time() < deadline:
        last = query_scene_state()
        for scene_name in scene_names:
            if is_settled_scene(last, scene_name):
                return last
        time.sleep(0.25)
    raise ProbeFailure(f"Timed out waiting for scenes {sorted(scene_names)}. Last scene={last}")


def snapshot_action_ids(snapshot: dict[str, str], *, limit: int = 12) -> set[str]:
    return {
        action_id
        for index in range(1, limit + 1)
        if (action_id := snapshot.get(f"element.{index}.action_id"))
    }


def query_create_selection_readiness(phase: str) -> dict[str, str]:
    if phase == "element":
        enabled_offset = CREATE_OWNER_ELEMENT_ENABLED_BYTE_OFFSET
        selected_offset = CREATE_OWNER_ELEMENT_SELECTED_OFFSET
    elif phase == "discipline":
        enabled_offset = CREATE_OWNER_DISCIPLINE_ENABLED_BYTE_OFFSET
        selected_offset = CREATE_OWNER_DISCIPLINE_SELECTED_OFFSET
    else:
        raise ProbeFailure(f"Unsupported create selection phase: {phase}")

    return parse_key_values(
        run_lua(
            f"""
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
local owner = 0
local snap = sd.ui and sd.ui.get_snapshot and sd.ui.get_snapshot()
if type(snap) == "table" and type(snap.elements) == "table" then
  for _, element in ipairs(snap.elements) do
    if tostring(element.surface_root_id or element.surface_id or "") == "create" then
      owner = tonumber(element.surface_object_ptr) or 0
      if owner ~= 0 then
        break
      end
    end
  end
end
emit("available", owner ~= nil and owner ~= 0)
emit("owner", owner)
if owner == nil or owner == 0 then
  return
end
local enabled = sd.debug.read_u8(owner + {enabled_offset})
local selected = sd.debug.read_u32(owner + {selected_offset})
emit("enabled", enabled)
emit("selected", selected)
emit("ready", enabled ~= nil and enabled ~= 0 and (selected == nil or selected == 0xFFFFFFFF))
""".strip()
        )
    )


def wait_for_create_selection_ready(phase: str, timeout_s: float = 15.0) -> dict[str, str]:
    deadline = time.time() + timeout_s
    last: dict[str, str] = {}
    while time.time() < deadline:
        snapshot = query_ui_snapshot()
        if snapshot.get("available") != "true" or snapshot.get("surface_id") != "create":
            time.sleep(0.1)
            continue
        last = query_create_selection_readiness(phase)
        if last.get("ready") == "true":
            return last
        time.sleep(0.1)
    raise ProbeFailure(f"Timed out waiting for create {phase} selection readiness. Last={last}")


def resolve_new_game_branch_after_activation(process_id: int, actions: list[str], timeout_s: float = 20.0) -> dict[str, str]:
    deadline = time.time() + timeout_s
    last_snapshot: dict[str, str] = {}
    while time.time() < deadline:
        scene = query_scene_state()
        if is_settled_scene(scene, "hub") or is_settled_scene(scene, "testrun"):
            return scene

        snapshot = query_ui_snapshot()
        last_snapshot = snapshot
        surface_id = snapshot.get("surface_id")
        if surface_id == "create":
            return snapshot

        if surface_id == "dialog" and "dialog.primary" in snapshot_action_ids(snapshot, limit=12):
            try:
                activate_or_click_snapshot_action(process_id, snapshot, "dialog.primary", "dialog")
                actions.append("dialog.primary")
            except ProbeFailure as exc:
                if not is_stale_ui_action_error(exc):
                    raise
            time.sleep(0.5)
            continue

        time.sleep(0.1)

    raise ProbeFailure(
        "Timed out resolving NEW GAME branch after activation. "
        f"Last scene={query_scene_state()} last_ui={last_snapshot}"
    )


def choose_create_options(process_id: int, *, element: str, discipline: str) -> None:
    wait_for_create_selection_ready("element")
    try:
        activate_ui_action(f"create.select_element_{element}", "create")
    except ProbeFailure:
        if not ALLOW_MOUSE_UI_AUTOMATION:
            raise
        click_create_choice(process_id, *CREATE_ELEMENT_CENTERS[element])
    wait_for_create_selection_ready("discipline")
    try:
        activate_ui_action(f"create.select_discipline_{discipline}", "create")
    except ProbeFailure:
        if not ALLOW_MOUSE_UI_AUTOMATION:
            raise
        click_create_choice(process_id, *CREATE_DISCIPLINE_CENTERS[discipline])


def drive_hub_flow(
    process_id: int,
    *,
    element: str,
    discipline: str,
    prefer_resume: bool = True,
) -> dict[str, object]:
    play_clicked = False
    resume_clicked = False
    new_game_clicked = False
    create_selected = False
    actions: list[str] = []
    deadline = time.time() + 75.0
    while time.time() < deadline:
        scene = query_scene_state()
        if is_settled_scene(scene, "hub") or is_settled_scene(scene, "testrun"):
            if resume_clicked:
                mode = "resume_last_game"
            elif new_game_clicked:
                mode = "new_game"
            else:
                mode = f"already_{scene.get('name')}"
            return {"mode": mode, "actions": actions, "scene": scene}

        snapshot = query_ui_snapshot()
        surface_id = snapshot.get("surface_id")
        if surface_id == "dialog" and snapshot.get("element.2.action_id") == "dialog.primary":
            try:
                activate_or_click_snapshot_action(process_id, snapshot, "dialog.primary", "dialog")
                actions.append("dialog.primary")
            except ProbeFailure as exc:
                if not is_stale_ui_action_error(exc):
                    raise
            time.sleep(0.75)
            continue

        if surface_id == "main_menu":
            action_ids = snapshot_action_ids(snapshot, limit=12)
            if not play_clicked and "main_menu.play" in action_ids:
                try:
                    activate_or_click_snapshot_action(process_id, snapshot, "main_menu.play", "main_menu")
                    actions.append("main_menu.play")
                    play_clicked = True
                except ProbeFailure as exc:
                    if not is_stale_ui_action_error(exc):
                        raise
                time.sleep(0.75)
                continue
            if prefer_resume and not resume_clicked and "main_menu.resume_last_game" in action_ids:
                try:
                    activate_or_click_snapshot_action(process_id, snapshot, "main_menu.resume_last_game", "main_menu")
                    actions.append("main_menu.resume_last_game")
                    resume_clicked = True
                except ProbeFailure as exc:
                    if not is_stale_ui_action_error(exc):
                        raise
                    time.sleep(0.75)
                    continue
                scene = wait_for_any_scene({"hub", "testrun"}, timeout_s=60.0)
                return {"mode": "resume_last_game", "actions": actions, "scene": scene}
            if not new_game_clicked and "main_menu.new_game" in action_ids:
                try:
                    activate_or_click_snapshot_action(process_id, snapshot, "main_menu.new_game", "main_menu")
                    actions.append("main_menu.new_game")
                    new_game_clicked = True
                except ProbeFailure as exc:
                    if not is_stale_ui_action_error(exc):
                        raise
                    time.sleep(0.75)
                    continue
                branch = resolve_new_game_branch_after_activation(process_id, actions)
                if is_settled_scene(branch, "hub") or is_settled_scene(branch, "testrun"):
                    return {"mode": "new_game", "actions": actions, "scene": branch}
                choose_create_options(process_id, element=element, discipline=discipline)
                actions.extend([
                    f"create.select_element_{element}",
                    f"create.select_discipline_{discipline}",
                ])
                create_selected = True
                scene = wait_for_scene("hub", timeout_s=60.0)
                return {"mode": "new_game", "actions": actions, "scene": scene}

        if surface_id == "create" and not create_selected:
            choose_create_options(process_id, element=element, discipline=discipline)
            actions.extend([
                f"create.select_element_{element}",
                f"create.select_discipline_{discipline}",
            ])
            create_selected = True
            scene = wait_for_scene("hub", timeout_s=60.0)
            return {"mode": "new_game", "actions": actions, "scene": scene}

        time.sleep(0.25)

    raise ProbeFailure(
        "Timed out driving hub flow. "
        f"Last scene={query_scene_state()} last_ui={query_ui_snapshot()} "
        f"play_clicked={play_clicked} resume_clicked={resume_clicked} "
        f"new_game_clicked={new_game_clicked} create_selected={create_selected} "
        f"actions={actions}"
    )


def drive_new_game_flow(process_id: int, *, element: str, discipline: str) -> None:
    play_clicked = False
    new_game_clicked = False
    create_selected = False
    deadline = time.time() + 60.0
    while time.time() < deadline:
        scene = query_scene_state()
        if scene.get("available") == "true" and scene.get("name") == "hub" and scene.get("transitioning") == "false":
            return

        snapshot = query_ui_snapshot()
        surface_id = snapshot.get("surface_id")
        if surface_id == "dialog" and snapshot.get("element.2.action_id") == "dialog.primary":
            activate_or_click_snapshot_action(process_id, snapshot, "dialog.primary", "dialog")
            time.sleep(0.75)
            continue

        if surface_id == "main_menu":
            action_ids = {
                snapshot.get(f"element.{index}.action_id"): index
                for index in range(1, 9)
                if snapshot.get(f"element.{index}.action_id")
            }
            if not play_clicked and "main_menu.play" in action_ids:
                activate_or_click_snapshot_action(process_id, snapshot, "main_menu.play", "main_menu")
                play_clicked = True
                time.sleep(0.75)
                continue
            if not new_game_clicked and "main_menu.new_game" in action_ids:
                activate_or_click_snapshot_action(process_id, snapshot, "main_menu.new_game", "main_menu")
                new_game_clicked = True
                wait_for_surface("create", timeout_s=15.0)
                choose_create_options(process_id, element=element, discipline=discipline)
                create_selected = True
                wait_for_scene("hub", timeout_s=45.0)
                return

        if surface_id == "create" and not create_selected:
            choose_create_options(process_id, element=element, discipline=discipline)
            create_selected = True
            wait_for_scene("hub", timeout_s=45.0)
            return

        time.sleep(0.25)

    raise ProbeFailure(
        "Timed out driving new-game flow. "
        f"Last scene={query_scene_state()} last_ui={query_ui_snapshot()} "
        f"play_clicked={play_clicked} new_game_clicked={new_game_clicked} create_selected={create_selected}"
    )


def start_run_and_waves() -> None:
    scene = query_scene_state()
    if not is_settled_scene(scene, "testrun"):
        values = parse_key_values(run_lua("print('ok='..tostring(sd.hub.start_testrun()))"))
        if values.get("ok") != "true":
            raise ProbeFailure(f"sd.hub.start_testrun failed: {values}")
        wait_for_scene("testrun", timeout_s=45.0)
    values = parse_key_values(run_lua("print('ok='..tostring(sd.gameplay.start_waves()))"))
    if values.get("ok") != "true":
        raise ProbeFailure(f"sd.gameplay.start_waves failed: {values}")


def query_world_state() -> dict[str, str]:
    return parse_key_values(
        run_lua(
            """
local world = sd.world and sd.world.get_state and sd.world.get_state()
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
if type(world) ~= 'table' then
  emit('available', false)
  return
end
emit('available', true)
emit('wave', world.wave)
emit('enemy_count', world.enemy_count)
emit('time_elapsed_ms', world.time_elapsed_ms)
""".strip()
        )
    )


def query_selection_debug_state() -> dict[str, str]:
    return parse_key_values(
        run_lua(
            """
local state = sd.gameplay and sd.gameplay.get_selection_debug_state and sd.gameplay.get_selection_debug_state()
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
if type(state) ~= 'table' then
  emit('available', false)
  return
end
emit('available', true)
emit('player_selection_state_0', state.player_selection_state_0)
emit('player_selection_state_1', state.player_selection_state_1)
if type(state.slot_selection_entries) == 'table' then
  for i = 1, #state.slot_selection_entries do
    emit('slot_selection_entries.' .. i, state.slot_selection_entries[i])
  end
end
""".strip()
        )
    )


def query_player_state() -> dict[str, str]:
    return parse_key_values(
        run_lua(
            """
local player = sd.player and sd.player.get_state and sd.player.get_state()
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
if type(player) ~= 'table' then
  emit('available', false)
  return
end
emit('available', true)
for _, key in ipairs({
  'actor_address','progression_address','progression_handle_address','equip_handle_address',
  'equip_runtime_state_address','actor_slot','hp','max_hp','mp','max_mp','x','y'
}) do
  emit(key, player[key])
end
""".strip()
        )
    )


def query_bot_state(index: int = 1) -> dict[str, str]:
    return parse_key_values(
        run_lua(
            f"""
local bots = sd.bots and sd.bots.get_state and sd.bots.get_state()
local bot = type(bots) == 'table' and bots[{index}] or nil
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
if type(bot) ~= 'table' then
  emit('available', false)
  return
end
emit('available', true)
for _, key in ipairs({{
  'id','actor_address','progression_runtime_state_address','progression_handle_address',
  'equip_handle_address','equip_runtime_state_address','gameplay_slot','actor_slot',
  'hp','max_hp','mp','max_mp','x','y','state'
}}) do
  emit(key, bot[key])
end
""".strip()
        )
    )


def boost_player_survival(min_hp: float = 5000.0) -> None:
    player = query_player_state()
    progression_address = int_value(player, "progression_address")
    if progression_address == 0:
        return

    run_lua(
        f"""
sd.debug.write_float({progression_address + PROGRESSION_HP_OFFSET}, {min_hp})
sd.debug.write_float({progression_address + PROGRESSION_MAX_HP_OFFSET}, {min_hp})
print('ok=true')
""".strip()
    )


def wait_for_materialized_bot(timeout_s: float = 45.0) -> dict[str, str]:
    deadline = time.time() + timeout_s
    last = {}
    while time.time() < deadline:
        last = query_bot_state()
        if last.get("available") == "true" and int_value(last, "actor_address") != 0:
            return last
        time.sleep(0.25)
    raise ProbeFailure(f"Timed out waiting for a materialized bot actor. Last bot={last}")


def query_actor_raw_fields(label: str, actor_address: int) -> dict[str, str]:
    if actor_address == 0:
        return {"available": "false"}

    lines = [
        "local function emit(key, value)",
        "  if value == nil then",
        "    print(key .. '=')",
        "  else",
        "    print(key .. '=' .. tostring(value))",
        "  end",
        "end",
        f"local actor = {actor_address}",
        "emit('available', true)",
    ]
    for name, (kind, offset) in ACTOR_RAW_OFFSETS.items():
        reader = {
            "ptr": "read_ptr",
            "u32": "read_u32",
            "u16": "read_u16",
            "u8": "read_u8",
            "float": "read_float",
        }[kind]
        lines.append(f"emit('{name}', sd.debug.{reader}(actor + {offset}))")
    lines.extend(
        [
            "local profile = sd.debug.read_ptr(actor + 0x200)",
            "emit('profile_ptr', profile)",
            f"if profile and profile ~= 0 then emit('profile_template_id', sd.debug.read_u32(profile + {PROFILE_TEMPLATE_OFFSET})) end",
            "local owner = sd.debug.read_ptr(actor + 0x58)",
            "emit('owner_ptr', owner)",
        ]
    )
    return parse_key_values(run_lua("\n".join(lines)))


def query_slot_profile(scene_address: int, slot_index: int) -> dict[str, str]:
    if scene_address == 0 or slot_index < 0:
        return {"available": "false"}

    return parse_key_values(
        run_lua(
            f"""
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
local gameplay_scene = {scene_address}
local slot_index = {slot_index}
emit('available', true)
emit('slot_index', slot_index)
emit('gameplay_scene', gameplay_scene)
local slot_ptr_ptr = sd.debug.read_ptr(gameplay_scene + {GAMEPLAY_PLAYER_PROGRESSION_HANDLE_OFFSET} + slot_index * {GAMEPLAY_PLAYER_SLOT_STRIDE})
emit('slot_ptr_ptr', slot_ptr_ptr)
local slot_profile = slot_ptr_ptr and slot_ptr_ptr ~= 0 and sd.debug.read_ptr(slot_ptr_ptr) or 0
emit('slot_profile_ptr', slot_profile)
if slot_profile and slot_profile ~= 0 then
  emit('slot_profile_template_id', sd.debug.read_u32(slot_profile + {PROFILE_TEMPLATE_OFFSET}))
end
""".strip()
        )
    )


def wait_for_nearest_enemy(timeout_s: float = 30.0, *, max_gap: float = 5000.0) -> dict[str, str]:
    deadline = time.time() + timeout_s
    last = {}
    while time.time() < deadline:
        last = parse_key_values(
            run_lua(
                f"""
local bots = sd.bots.get_state()
local bot = type(bots) == 'table' and bots[1] or nil
local actors = sd.world.list_actors()
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
if type(bot) ~= 'table' or type(actors) ~= 'table' then
  emit('available', false)
  return
end
local bx = tonumber(bot.x) or 0.0
local by = tonumber(bot.y) or 0.0
local best = nil
local best_gap = math.huge
for _, actor in ipairs(actors) do
  local obj = tonumber(actor.object_type_id) or 0
  local tracked = actor.tracked_enemy == true
  local dead = actor.dead == true
  local hp = tonumber(actor.hp) or 0.0
  local max_hp = tonumber(actor.max_hp) or 0.0
  if (tracked or obj == 1001) and not dead and (max_hp <= 0.0 or hp > 0.0) then
    local ax = tonumber(actor.x) or 0.0
    local ay = tonumber(actor.y) or 0.0
    local dx = ax - bx
    local dy = ay - by
    local gap = math.sqrt(dx * dx + dy * dy)
    if gap > 48.0 and gap < {max_gap} and gap < best_gap then
      best_gap = gap
      best = actor
    end
  end
end
if type(best) ~= 'table' then
  emit('available', false)
  return
end
emit('available', true)
emit('x', best.x)
emit('y', best.y)
emit('gap', best_gap)
emit('object_type_id', best.object_type_id)
emit('actor_address', best.actor_address)
emit('tracked_enemy', best.tracked_enemy)
emit('enemy_type', best.enemy_type)
emit('dead', best.dead)
emit('hp', best.hp)
emit('max_hp', best.max_hp)
""".strip()
            )
        )
        if last.get("available") == "true":
            return last
        time.sleep(0.25)
    raise ProbeFailure(f"Timed out waiting for a nearby enemy. Last={last}")


def query_nearby_actors(center_x: float, center_y: float, radius: float) -> dict[str, str]:
    return parse_key_values(
        run_lua(
            f"""
local actors = sd.world.list_actors()
local cx = {center_x}
local cy = {center_y}
local radius = {radius}
local radius2 = radius * radius
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
if type(actors) ~= 'table' then
  emit('available', false)
  return
end
local rows = {{}}
for _, actor in ipairs(actors) do
  local ax = tonumber(actor.x) or 0.0
  local ay = tonumber(actor.y) or 0.0
  local dx = ax - cx
  local dy = ay - cy
  local dist2 = dx * dx + dy * dy
  if dist2 <= radius2 then
    rows[#rows + 1] = {{
      actor_address = actor.actor_address,
      object_type_id = actor.object_type_id,
      x = actor.x,
      y = actor.y,
      dist2 = dist2,
    }}
  end
end
table.sort(rows, function(a, b) return a.dist2 < b.dist2 end)
emit('available', true)
emit('count', #rows)
for index = 1, math.min(#rows, 24) do
  local row = rows[index]
  emit('actor.' .. index .. '.actor_address', row.actor_address)
  emit('actor.' .. index .. '.object_type_id', row.object_type_id)
  emit('actor.' .. index .. '.x', row.x)
  emit('actor.' .. index .. '.y', row.y)
  emit('actor.' .. index .. '.dist2', row.dist2)
end
""".strip()
        )
    )


def queue_bot_cast(target_x: float, target_y: float, skill_id: int) -> dict[str, str]:
    return parse_key_values(
        run_lua(
            f"""
local bots = sd.bots.get_state()
local bot = type(bots) == 'table' and bots[1] or nil
if type(bot) ~= 'table' then
  print('available=false')
  return
end
print('available=true')
print('bot_id=' .. tostring(bot.id))
print('ok=' .. tostring(sd.bots.cast({{
  id = bot.id,
  kind = 'primary',
  skill_id = {skill_id},
  target = {{ x = {target_x}, y = {target_y} }},
}})))
""".strip()
        )
    )


def press_player_key(binding_name: str) -> dict[str, str]:
    return parse_key_values(
        run_lua(
            f"""
print('ok=' .. tostring(sd.input.press_key({json.dumps(binding_name)})))
""".strip()
        )
    )


def tail_loader_log(limit: int = 120) -> list[str]:
    if not LOADER_LOG.exists():
        return []
    with LOADER_LOG.open("r", encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()
    return [line.rstrip("\n") for line in lines[-limit:]]


def float_value(values: dict[str, str], key: str) -> float:
    value = values.get(key, "")
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def int_value(values: dict[str, str], key: str) -> int:
    value = values.get(key, "")
    try:
        return int(value, 0)
    except (TypeError, ValueError):
        return 0


def collect_snapshot() -> dict[str, object]:
    player = query_player_state()
    bot = query_bot_state()
    player_actor = int_value(player, "actor_address")
    bot_actor = int_value(bot, "actor_address")
    player_slot = int_value(player, "actor_slot")
    bot_slot = int_value(bot, "actor_slot")
    scene = query_scene_state()
    gameplay_scene = int_value(scene, "scene_id")
    return {
        "scene": scene,
        "world": query_world_state(),
        "selection_debug": query_selection_debug_state(),
        "player": player,
        "bot": bot,
        "player_actor_raw": query_actor_raw_fields("player", player_actor),
        "bot_actor_raw": query_actor_raw_fields("bot", bot_actor),
        "player_slot_profile": query_slot_profile(gameplay_scene, player_slot),
        "bot_slot_profile": query_slot_profile(gameplay_scene, bot_slot),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Launch a settled testrun and capture cast-state diagnostics.")
    parser.add_argument("--element", choices=sorted(CREATE_ELEMENT_CENTERS), default=DEFAULT_ELEMENT)
    parser.add_argument("--discipline", choices=sorted(CREATE_DISCIPLINE_CENTERS), default=DEFAULT_DISCIPLINE)
    parser.add_argument("--bot-skill-id", type=lambda v: int(v, 0), default=DEFAULT_BOT_SKILL_ID)
    parser.add_argument("--player-key", default="", help="Optional sd.input.press_key binding to fire after bot cast, e.g. belt_slot_1.")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--keep-running", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result: dict[str, object] = {
        "launcher_freshness": ensure_launcher_bundle_fresh(),
        "navigation": [],
    }

    try:
        stop_game()
        clear_loader_log()

        launch_game()
        process_id = wait_for_game_process()
        result["process_id"] = process_id
        wait_for_lua_pipe()
        result["navigation"].append({"step": "launch", "process_id": process_id})

        hub_flow = drive_hub_flow(process_id, element=args.element, discipline=args.discipline, prefer_resume=True)
        result["navigation"].append(
            {"step": "hub_ready", "flow": hub_flow, "element": args.element, "discipline": args.discipline}
        )

        start_run_and_waves()
        boost_player_survival()
        result["navigation"].append({"step": "testrun_started"})

        wait_for_materialized_bot()
        before = collect_snapshot()
        enemy = wait_for_nearest_enemy()
        before_nearby = query_nearby_actors(target_x := float_value(enemy, "x"), target_y := float_value(enemy, "y"), 450.0)
        result["before"] = before
        result["enemy"] = enemy
        result["before_nearby_actors"] = before_nearby

        bot_cast = queue_bot_cast(target_x, target_y, args.bot_skill_id)
        result["bot_cast"] = bot_cast

        if args.player_key:
            time.sleep(0.5)
            result["player_input"] = press_player_key(args.player_key)
        else:
            result["player_input"] = {}

        time.sleep(4.0)
        after = collect_snapshot()
        after_nearby = query_nearby_actors(target_x, target_y, 450.0)
        result["after"] = after
        result["after_nearby_actors"] = after_nearby
        result["loader_log_tail"] = tail_loader_log()

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except ProbeFailure as exc:
        result["error"] = str(exc)
        result["loader_log_tail"] = tail_loader_log()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1
    finally:
        if not args.keep_running:
            stop_game()


if __name__ == "__main__":
    raise SystemExit(main())
