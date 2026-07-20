#!/usr/bin/env python3
"""Exact Windows/Proton input and native hub-surface state for Steam tests."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import math
import os
from pathlib import Path
import subprocess
import threading
import time
from typing import Callable, Literal

import verify_multiplayer_hub_inventory_shop_sync as hub_inventory
from steam_friend_active_pair import (
    CLIENT_ENDPOINT,
    HOST_ENDPOINT,
    PAIR_BACKEND,
    ROOT,
)
from verify_local_multiplayer_sync import VerifyFailure, parse_key_values


LuaExecutor = Callable[[str, str, float], str]
PROTON_CLICK_HOLD_SECONDS = 0.30
HUB_DIALOG_DONE_Y = 388.0
HUB_INVENTORY_DONE_STOCK = (320.0, 205.0)
ACTIVATE_WINDOW = ROOT / "scripts/activate_window.py"
REMOTE_UI_HELPER_FILES = (
    ROOT / "scripts/capture_window.py",
    ROOT / "scripts/click_window.py",
    ROOT / "scripts/send_window_keys.py",
    ROOT / "scripts/activate_window.py",
    ROOT / "scripts/Invoke-InteractiveGameInput.ps1",
)
REMOTE_UI_HELPER_DIRECTORY = os.environ.get(
    "SDMOD_STEAM_REMOTE_UI_HELPER_DIRECTORY",
    r"C:\Users\Public\Documents\SolomonDarkBeta5RemoteTest\ui-test-helpers",
).strip()
REMOTE_GAME_PATH = os.environ.get(
    "SDMOD_STEAM_REMOTE_GAME_PATH",
    r"C:\Users\Public\Documents\SolomonDarkBeta5RemoteTest\physical-host-runtime\stage\SolomonDark.exe",
).strip()
_REMOTE_HELPERS_LOCK = threading.Lock()
_remote_helpers_staged = False


@dataclass(frozen=True)
class HubInputTarget:
    label: str
    owner_endpoint: str
    input_window_pid: int
    pointer_input: Literal["windows", "proton", "remote_windows"]


def local_windows_game_process_id() -> int:
    command = (
        "$matches=@(Get-Process SolomonDark -ErrorAction SilentlyContinue); "
        "if ($matches.Count -ne 1) { exit 1 }; $matches[0].Id"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=10.0,
        check=False,
    )
    value = completed.stdout.strip()
    if completed.returncode != 0 or not value.isdigit() or int(value) <= 0:
        raise VerifyFailure(
            "the hub test requires exactly one local Windows SolomonDark process"
        )
    return int(value)


def resolve_hub_input_targets() -> dict[str, HubInputTarget]:
    if PAIR_BACKEND == "wsl":
        return {
            HOST_ENDPOINT: HubInputTarget(
                "windows",
                HOST_ENDPOINT,
                local_windows_game_process_id(),
                "windows",
            ),
            CLIENT_ENDPOINT: HubInputTarget(
                "proton",
                CLIENT_ENDPOINT,
                proton_input_process_id(),
                "proton",
            ),
        }
    if PAIR_BACKEND == "remote-windows-host":
        return {
            HOST_ENDPOINT: HubInputTarget(
                "remote_windows",
                HOST_ENDPOINT,
                remote_windows_process_id(),
                "remote_windows",
            ),
            CLIENT_ENDPOINT: HubInputTarget(
                "local_windows",
                CLIENT_ENDPOINT,
                local_windows_game_process_id(),
                "windows",
            ),
        }
    raise VerifyFailure(f"unsupported Steam pair backend: {PAIR_BACKEND!r}")


def remote_ssh_settings() -> tuple[str, str, Path]:
    host = os.environ.get("SDMOD_STEAM_REMOTE_SSH_HOST", "").strip()
    user = os.environ.get(
        "SDMOD_STEAM_REMOTE_SSH_USER", "TailscaleToday"
    ).strip()
    key = Path(
        os.environ.get(
            "SDMOD_STEAM_REMOTE_SSH_KEY",
            "~/.ssh/id_ed25519_workstation20_tailscale",
        )
    ).expanduser()
    if not host:
        raise VerifyFailure(
            "SDMOD_STEAM_REMOTE_SSH_HOST is required for remote Windows input"
        )
    if not key.is_file():
        raise VerifyFailure(f"remote Windows SSH key not found: {key}")
    return host, user, key


def run_remote_ssh(arguments: list[str], timeout: float) -> str:
    host, user, key = remote_ssh_settings()
    completed = subprocess.run(
        [
            "ssh",
            "-T",
            "-i",
            str(key),
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            f"{user}@{host}",
            *arguments,
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise VerifyFailure(
            "remote Windows interactive input failed: "
            + completed.stdout.strip()
        )
    return completed.stdout.strip()


def encoded_powershell(command: str) -> list[str]:
    command = "$ProgressPreference='SilentlyContinue';" + command
    encoded = base64.b64encode(command.encode("utf-16le")).decode("ascii")
    return [
        "powershell.exe",
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-OutputFormat",
        "Text",
        "-ExecutionPolicy",
        "Bypass",
        "-EncodedCommand",
        encoded,
    ]


def quote_powershell(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def ensure_remote_windows_ui_helpers() -> None:
    global _remote_helpers_staged
    with _REMOTE_HELPERS_LOCK:
        if _remote_helpers_staged:
            return
        if not REMOTE_UI_HELPER_DIRECTORY:
            raise VerifyFailure("remote Windows UI helper directory is empty")
        missing = [path for path in REMOTE_UI_HELPER_FILES if not path.is_file()]
        if missing:
            raise VerifyFailure(
                "remote Windows UI helper source is missing: "
                + ", ".join(str(path) for path in missing)
            )

        run_remote_ssh(
            encoded_powershell(
                "$ErrorActionPreference='Stop';"
                f"New-Item -ItemType Directory -Force -Path "
                f"{quote_powershell(REMOTE_UI_HELPER_DIRECTORY)} | Out-Null"
            ),
            15.0,
        )
        host, user, key = remote_ssh_settings()
        destination = REMOTE_UI_HELPER_DIRECTORY.replace("\\", "/")
        completed = subprocess.run(
            [
                "scp",
                "-q",
                "-i",
                str(key),
                *(str(path) for path in REMOTE_UI_HELPER_FILES),
                f"{user}@{host}:{destination}/",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=20.0,
            check=False,
        )
        if completed.returncode != 0:
            raise VerifyFailure(
                "failed to stage remote Windows UI helpers: "
                + completed.stdout.strip()
            )
        _remote_helpers_staged = True


def remote_windows_process_id() -> int:
    if not REMOTE_GAME_PATH:
        raise VerifyFailure("SDMOD_STEAM_REMOTE_GAME_PATH is empty")
    command = (
        "$ErrorActionPreference='Stop';"
        f"$path={quote_powershell(REMOTE_GAME_PATH)};"
        "$matches=@(Get-CimInstance Win32_Process | Where-Object {"
        "$_.Name -eq 'SolomonDark.exe' -and "
        "[string]::Equals([string]$_.ExecutablePath,$path,"
        "[System.StringComparison]::OrdinalIgnoreCase)});"
        "if($matches.Count -ne 1){exit 2};"
        "[Console]::Out.Write($matches[0].ProcessId)"
    )
    output = run_remote_ssh(encoded_powershell(command), 15.0)
    if not output.isdigit() or int(output) <= 0:
        raise VerifyFailure(
            "could not resolve the exact remote Windows SolomonDark process"
        )
    return int(output)


def run_remote_windows_input(
    action: Literal[
        "activate", "key", "click", "drag", "release"
    ],
    process_id: int,
    *,
    key: str = "d",
    hold_ms: int = 0,
    x: float = 0.0,
    y: float = 0.0,
    destination_x: float = 0.0,
    destination_y: float = 0.0,
) -> str:
    ensure_remote_windows_ui_helpers()
    if process_id != remote_windows_process_id():
        raise VerifyFailure("remote Windows SolomonDark process changed")
    script = (
        REMOTE_UI_HELPER_DIRECTORY.rstrip("\\/")
        + r"\Invoke-InteractiveGameInput.ps1"
    )
    command = (
        "$ErrorActionPreference='Stop';"
        f"& {quote_powershell(script)} "
        f"-Action {quote_powershell(action)} "
        f"-ProcessId {process_id} "
        f"-Key {quote_powershell(key)} "
        f"-HoldMilliseconds {hold_ms} "
        f"-X {x:.8f} -Y {y:.8f} "
        f"-DestinationX {destination_x:.8f} "
        f"-DestinationY {destination_y:.8f} "
        f"-HelperDirectory {quote_powershell(REMOTE_UI_HELPER_DIRECTORY)} "
        f"-ExpectedExecutablePath {quote_powershell(REMOTE_GAME_PATH)}"
    )
    values = parse_key_values(
        run_remote_ssh(encoded_powershell(command), 30.0)
    )
    if values.get("ok") != "true" or values.get("action") != action:
        raise VerifyFailure(
            f"remote Windows input action did not complete: {values}"
        )
    return values.get("helper_result") or f"performed remote Windows {action} input"


def proton_window() -> tuple[str, int, int]:
    completed = subprocess.run(
        ["xdotool", "search", "--onlyvisible", "--name", "^SolomonDark$"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=5.0,
        check=False,
    )
    window_ids = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if completed.returncode != 0 or len(window_ids) != 1:
        raise VerifyFailure("could not resolve the exact Proton game window")

    geometry = subprocess.run(
        ["xdotool", "getwindowgeometry", "--shell", window_ids[0]],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=5.0,
        check=False,
    )
    values = parse_key_values(geometry.stdout)
    try:
        width = int(values["WIDTH"])
        height = int(values["HEIGHT"])
    except (KeyError, ValueError) as exc:
        raise VerifyFailure("could not read the Proton game-window geometry") from exc
    if geometry.returncode != 0 or width <= 0 or height <= 0:
        raise VerifyFailure("the Proton game window has invalid geometry")
    return window_ids[0], width, height


def proton_input_process_id() -> int:
    proton_window()
    command = (
        "$normal='SolomonDark (Ubuntu)'; "
        "$copy='[WARN:COPY MODE] SolomonDark (Ubuntu)'; "
        "$matches=@(Get-Process msrdc -ErrorAction SilentlyContinue | "
        "Where-Object { $_.MainWindowHandle -ne 0 -and "
        "($_.MainWindowTitle -eq $normal -or $_.MainWindowTitle -eq $copy) }); "
        "if ($matches.Count -ne 1) { exit 1 }; $matches[0].Id"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=10.0,
        check=False,
    )
    value = completed.stdout.strip()
    if completed.returncode != 0 or not value.isdigit() or int(value) <= 0:
        raise VerifyFailure(
            "could not resolve the exact Windows WSLg wrapper for the Proton game"
        )
    return int(value)


def run_xdotool(arguments: list[str]) -> None:
    completed = subprocess.run(
        ["xdotool", *arguments],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=5.0,
        check=False,
    )
    if completed.returncode != 0:
        raise VerifyFailure(
            "Proton game input failed: "
            + (completed.stderr.strip() or completed.stdout.strip())
        )


def activate_proton_window(input_window_pid: int) -> str:
    return hub_inventory.run_windows_python(
        ACTIVATE_WINDOW,
        ["--pid", str(input_window_pid), "--delay-ms", "250"],
    )


def proton_point(x: float, y: float) -> tuple[str, int, int]:
    window_id, width, height = proton_window()
    return (
        window_id,
        max(0, min(width - 1, round(width * x))),
        max(0, min(height - 1, round(height * y))),
    )


def hold_proton_key(
    input_window_pid: int,
    key: str,
    hold_ms: int,
    timeout: float = 10.0,
) -> str:
    if hold_ms < 0 or hold_ms / 1000.0 >= timeout:
        raise VerifyFailure(
            f"invalid Proton key duration: hold_ms={hold_ms} timeout={timeout}"
        )
    return hub_inventory.hold_real_key(
        input_window_pid,
        key,
        hold_ms,
        timeout,
    )


def hold_key(target: HubInputTarget, key: str, hold_ms: int) -> str:
    if target.pointer_input == "windows":
        return hub_inventory.hold_real_key(
            target.input_window_pid,
            key,
            hold_ms,
        )
    if target.pointer_input == "proton":
        return hold_proton_key(target.input_window_pid, key, hold_ms)
    return run_remote_windows_input(
        "key",
        target.input_window_pid,
        key=key,
        hold_ms=hold_ms,
    )


def click_pointer(target: HubInputTarget, x: float, y: float) -> str:
    if target.pointer_input == "windows":
        return hub_inventory.click_relative(target.input_window_pid, x, y)
    if target.pointer_input == "remote_windows":
        return run_remote_windows_input(
            "click",
            target.input_window_pid,
            x=x,
            y=y,
        )
    window_id, point_x, point_y = proton_point(x, y)
    activate_proton_window(target.input_window_pid)
    run_xdotool(
        ["mousemove", "--window", window_id, str(point_x), str(point_y)]
    )
    run_xdotool(["mousedown", "1"])
    time.sleep(PROTON_CLICK_HOLD_SECONDS)
    run_xdotool(["mouseup", "1"])
    time.sleep(0.2)
    return f"clicked Proton game at relative=({x:.3f},{y:.3f})"


def click_centered_top(
    target: HubInputTarget,
    y: float,
    x_offset: float = 0.0,
    minimum_x: float = 0.0,
) -> str:
    if target.pointer_input == "windows":
        return hub_inventory.click_centered_top(
            target.input_window_pid,
            y,
            x_offset,
            minimum_x,
        )
    if target.pointer_input == "proton":
        window_id, width, height = proton_window()
    else:
        width = round(hub_inventory.STOCK_UI_WIDTH)
        height = round(hub_inventory.STOCK_UI_HEIGHT)
    x_fraction, y_fraction = hub_inventory.stock_ui_viewport_point(
        float(width),
        float(height),
        y,
        x_offset,
        minimum_x,
    )
    if target.pointer_input == "remote_windows":
        return run_remote_windows_input(
            "click",
            target.input_window_pid,
            x=x_fraction,
            y=y_fraction,
        )
    point_x = max(0, min(width - 1, round(width * x_fraction)))
    point_y = max(0, min(height - 1, round(height * y_fraction)))
    activate_proton_window(target.input_window_pid)
    run_xdotool(
        ["mousemove", "--window", window_id, str(point_x), str(point_y)]
    )
    run_xdotool(["mousedown", "1"])
    time.sleep(PROTON_CLICK_HOLD_SECONDS)
    run_xdotool(["mouseup", "1"])
    time.sleep(0.2)
    return (
        "clicked Proton game at stock UI "
        f"coordinate=({x_fraction:.4f},{y_fraction:.4f})"
    )


def drag_pointer(
    target: HubInputTarget,
    source_x: float,
    source_y: float,
    destination_x: float,
    destination_y: float,
) -> str:
    if target.pointer_input == "windows":
        return hub_inventory.drag_relative(
            target.input_window_pid,
            source_x,
            source_y,
            destination_x,
            destination_y,
        )

    if target.pointer_input == "remote_windows":
        return run_remote_windows_input(
            "drag",
            target.input_window_pid,
            x=source_x,
            y=source_y,
            destination_x=destination_x,
            destination_y=destination_y,
        )

    window_id, start_x, start_y = proton_point(source_x, source_y)
    destination_window_id, end_x, end_y = proton_point(
        destination_x, destination_y
    )
    if destination_window_id != window_id:
        raise VerifyFailure("the Proton game window changed during a drag")
    activate_proton_window(target.input_window_pid)
    run_xdotool(
        ["mousemove", "--window", window_id, str(start_x), str(start_y)]
    )
    run_xdotool(["mousedown", "1"])
    try:
        time.sleep(0.4)
        for step in range(1, 25):
            fraction = step / 24.0
            point_x = round(start_x + (end_x - start_x) * fraction)
            point_y = round(start_y + (end_y - start_y) * fraction)
            run_xdotool(
                ["mousemove", "--window", window_id, str(point_x), str(point_y)]
            )
            time.sleep(0.04)
        time.sleep(0.4)
    finally:
        run_xdotool(["mouseup", "1"])
    time.sleep(0.5)
    return (
        "dragged Proton game from "
        f"relative=({source_x:.3f},{source_y:.3f}) to "
        f"relative=({destination_x:.3f},{destination_y:.3f})"
    )


def settle_pointer_release(target: HubInputTarget) -> str:
    if target.pointer_input == "windows":
        return hub_inventory.settle_mouse_release()
    if target.pointer_input == "remote_windows":
        result = run_remote_windows_input(
            "release",
            target.input_window_pid,
        )
        time.sleep(1.0)
        return result
    activate_proton_window(target.input_window_pid)
    run_xdotool(["mouseup", "1"])
    time.sleep(1.0)
    return "released Proton game pointer"


def native_hub_surface_state(
    lua: LuaExecutor, endpoint: str
) -> tuple[bool, bool]:
    values = parse_key_values(
        lua(
            endpoint,
            r"""
local surface = sd.hub.get_surface_state()
print('surface_active=' .. tostring(surface.surface_active))
print('chat_active=' .. tostring(surface.chat_active))
print('inventory_screen_active=' .. tostring(surface.inventory_screen_active))
print('inventory_shop_active=' .. tostring(surface.inventory_shop_active))
""",
            5.0,
        )
    )
    return (
        values.get("surface_active") == "true",
        values.get("chat_active") == "true",
    )


def open_hub_service(
    lua: LuaExecutor,
    endpoint: str,
    service_name: Literal["luthacus_storage", "fomentius", "hagatha"],
) -> str:
    return lua(
        endpoint,
        "assert(sd.hub.open_service(" + repr(service_name) + "))\n"
        "print('queued=true')",
        5.0,
    ).strip()


def click_hub_stock(
    target: HubInputTarget,
    stock_x: float,
    stock_y: float,
) -> str:
    x, y = normalized_stock_point(stock_x, stock_y)
    return click_pointer(target, x, y)


def drag_hub_stock(
    target: HubInputTarget,
    source_stock_x: float,
    source_stock_y: float,
    destination_stock_x: float,
    destination_stock_y: float,
) -> str:
    source_x, source_y = normalized_stock_point(
        source_stock_x,
        source_stock_y,
    )
    destination_x, destination_y = normalized_stock_point(
        destination_stock_x,
        destination_stock_y,
    )
    return drag_pointer(
        target,
        source_x,
        source_y,
        destination_x,
        destination_y,
    )


def normalized_stock_point(stock_x: float, stock_y: float) -> tuple[float, float]:
    width = hub_inventory.STOCK_UI_WIDTH
    height = hub_inventory.STOCK_UI_HEIGHT
    if (
        not math.isfinite(stock_x)
        or not math.isfinite(stock_y)
        or stock_x < 0.0
        or stock_x >= width
        or stock_y < 0.0
        or stock_y >= height
    ):
        raise VerifyFailure(
            f"stock coordinate is outside the {width:g}x{height:g} logical UI: "
            f"({stock_x}, {stock_y})"
        )
    return stock_x / width, stock_y / height


def close_native_hub_surface(
    target: HubInputTarget,
    surface_active: bool,
    chat_active: bool,
) -> str:
    if surface_active:
        return click_hub_stock(target, *HUB_INVENTORY_DONE_STOCK)
    if chat_active:
        return click_centered_top(target, HUB_DIALOG_DONE_Y)
    raise VerifyFailure(f"{target.label} has no native hub surface to close")


def reset_native_hub_surfaces(
    target: HubInputTarget, lua: LuaExecutor, timeout: float
) -> list[str]:
    deadline = time.monotonic() + timeout
    stable_since: float | None = None
    actions: list[str] = []
    while time.monotonic() < deadline:
        surface_active, chat_active = native_hub_surface_state(
            lua, target.owner_endpoint
        )
        if not surface_active and not chat_active:
            now = time.monotonic()
            if stable_since is None:
                stable_since = now
            if now - stable_since >= 2.0:
                return actions
            time.sleep(0.1)
            continue
        stable_since = None
        actions.append(
            close_native_hub_surface(
                target,
                surface_active,
                chat_active,
            )
        )
        time.sleep(0.5)
    raise VerifyFailure(
        f"{target.label} could not close its pre-existing native hub surface"
    )
