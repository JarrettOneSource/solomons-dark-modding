#!/usr/bin/env python3
"""Verify capacity-backed bot membership on one isolated local pair."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = Path("/mnt/d/codex-evidence/botcap-20260727")
RUNTIME_ROOT = EVIDENCE_ROOT / "runtime"
WEBSITE_ROOT = Path("/mnt/c/sd-botcap-site-20260727")
DOTNET = Path("/home/user/.dotnet/dotnet")
GAME_ROOT = Path(
    "/mnt/c/Users/User/Documents/GitHub/SB Modding/"
    "Solomon Dark/SolomonDarkAbandonware"
)

INSTANCE_PREFIX = "bcap"
HOST_INSTANCE = f"{INSTANCE_PREFIX}-host"
CLIENT_INSTANCE = f"{INSTANCE_PREFIX}-client"
HOST_PORT = 49811
CLIENT_PORT = 49812
HOST_ID_TEXT = "0x2000000000007101"
CLIENT_ID_TEXT = "0x2000000000007102"
HOST_ID = int(HOST_ID_TEXT, 16)
CLIENT_ID = int(CLIENT_ID_TEXT, 16)
HOST_PIPE = f"SolomonDarkModLoader_LuaExec_{HOST_INSTANCE}"
CLIENT_PIPE = f"SolomonDarkModLoader_LuaExec_{CLIENT_INSTANCE}"
HOST_NAME = "Bcap Host"
CLIENT_NAME = "Bcap Client"
MOD_ID = "bot.brain"
CAPACITY = 4

DIRECTORY_URL = f"http://127.0.0.1:{HOST_PORT}"
LOBBY_ID = "76561198000007101"
VIEWER_STEAM_ID = "76561198000007102"
LOBBY_SECRET = "71" * 32
LOBBY_PASSWORD = "capacity-four"
PASSWORD_SALT = "71" * 16
PASSWORD_ITERATIONS = 210_000
JWT_SECRET = "sdr-bcap-local-jwt-secret-20260727-only"

FULL_ROSTER = [
    {"name": "Ember", "element": "fire", "discipline": "skirmisher"},
    {"name": "Bastion", "element": "earth", "discipline": "guardian"},
    {"name": "Gale", "element": "air", "discipline": "striker"},
    {"name": "Tide", "element": "water", "discipline": "skirmisher"},
]
OPEN_SEAT_ROSTER = FULL_ROSTER[:1]


class VerificationFailure(RuntimeError):
    """Raised when the isolated acceptance contract is not satisfied."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def windows_path(path: Path) -> str:
    completed = subprocess.run(
        ["wslpath", "-w", str(path)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if completed.returncode != 0:
        raise VerificationFailure(
            f"Could not convert path for Windows: {path}: "
            f"{completed.stderr.strip()}"
        )
    return completed.stdout.replace("\r", "").strip()


def powershell_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp"
    )
    with temporary.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def write_settings(path: Path, roster: list[dict[str, str]]) -> None:
    atomic_write_json(
        path,
        {
            "schemaVersion": 1,
            "values": {
                "focus_bot_key": "NONE",
                "kite_radius": 340,
                "offense_enabled": True,
                "roster": roster,
                "think_profile": "standard",
            },
        },
    )


def settings_path(instance: str) -> Path:
    return (
        RUNTIME_ROOT
        / "instances"
        / instance
        / "stage"
        / ".sdmod"
        / "mod-settings"
        / f"{MOD_ID}.json"
    )


def stage_root(instance: str) -> Path:
    return RUNTIME_ROOT / "instances" / instance / "stage"


def status_path(instance: str) -> Path:
    return stage_root(instance) / ".sdmod/multiplayer-session-status.json"


def log_path(instance: str) -> Path:
    return stage_root(instance) / ".sdmod/logs/solomondarkmodloader.log"


def parse_key_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.replace("\r", "").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def integer(values: dict[str, str], key: str, default: int = 0) -> int:
    raw = values.get(key, str(default)).strip()
    try:
        return int(raw, 10)
    except ValueError:
        try:
            return int(float(raw))
        except ValueError:
            return default


def lua(pipe_name: str, code: str, timeout: float = 15.0) -> str:
    command = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        windows_path(ROOT / "scripts/Invoke-LuaExec.ps1"),
        "-PipeName",
        pipe_name,
        "-ResponseTimeoutMilliseconds",
        str(int(timeout * 1000)),
        "-Code",
        code,
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout + 8,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise VerificationFailure(
            f"Lua exec failed for {pipe_name}: {detail}"
        )
    return completed.stdout


def wait_for(
    operation: Callable[[], Any],
    predicate: Callable[[Any], bool],
    *,
    label: str,
    timeout: float,
    interval: float = 0.35,
) -> tuple[Any, str]:
    deadline = time.monotonic() + timeout
    last: Any = None
    last_error = ""
    while time.monotonic() < deadline:
        try:
            last = operation()
            last_error = ""
            if predicate(last):
                return last, utc_now()
        except (
            OSError,
            ValueError,
            json.JSONDecodeError,
            subprocess.SubprocessError,
            VerificationFailure,
        ) as exc:
            last_error = str(exc)
        time.sleep(interval)
    raise VerificationFailure(
        f"Timed out waiting for {label}; last={last!r}; "
        f"last_error={last_error!r}"
    )


def query_windows_udp_owners() -> str:
    script = (
        f"$rows=@(Get-NetUDPEndpoint -LocalPort {HOST_PORT},{CLIENT_PORT} "
        "-ErrorAction SilentlyContinue);"
        "$rows | Select-Object LocalAddress,LocalPort,OwningProcess | "
        "ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if completed.returncode != 0:
        raise VerificationFailure(
            f"Could not inspect pinned UDP ports: {completed.stderr.strip()}"
        )
    return completed.stdout.replace("\r", "").strip()


def process_path(pid: int) -> str | None:
    script = (
        f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={pid}';"
        "if ($null -ne $p) { [Console]::Write($p.ExecutablePath) }"
    )
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if completed.returncode != 0:
        raise VerificationFailure(completed.stderr.strip())
    value = completed.stdout.replace("\r", "").strip()
    return value or None


def stop_owned_process(pid: int, expected_path: str) -> dict[str, Any]:
    actual = process_path(pid)
    if actual is None:
        return {
            "pid": pid,
            "executablePath": expected_path,
            "alreadyExited": True,
            "forced": False,
        }
    if actual.casefold() != expected_path.casefold():
        raise VerificationFailure(
            f"Refusing cleanup for PID {pid}: expected {expected_path}, "
            f"found {actual}"
        )
    script = (
        f"$p=Get-Process -Id {pid} -ErrorAction Stop;"
        "$closed=$p.CloseMainWindow();"
        "if ($closed) { "
        "  try { Wait-Process -Id $p.Id -Timeout 8 -ErrorAction Stop } "
        "  catch { Stop-Process -Id $p.Id -Force -ErrorAction Stop }"
        "} else { Stop-Process -Id $p.Id -Force -ErrorAction Stop };"
        "[Console]::Write($closed)"
    )
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if completed.returncode != 0:
        raise VerificationFailure(
            f"Exact cleanup failed for PID {pid}: "
            f"{(completed.stderr or completed.stdout).strip()}"
        )
    return {
        "pid": pid,
        "executablePath": expected_path,
        "alreadyExited": False,
        "forced": completed.stdout.strip().casefold() != "true",
    }


def assert_no_existing_stage_processes() -> None:
    expected = {
        windows_path(stage_root(HOST_INSTANCE) / "SolomonDark.exe").casefold(),
        windows_path(stage_root(CLIENT_INSTANCE) / "SolomonDark.exe").casefold(),
    }
    script = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $null -ne $_.ExecutablePath } | "
        "Select-Object ProcessId,ExecutablePath | ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise VerificationFailure(
            f"Could not inspect existing game processes: "
            f"{completed.stderr.strip()}"
        )
    raw = completed.stdout.replace("\r", "").strip()
    if not raw:
        return
    rows = json.loads(raw)
    if isinstance(rows, dict):
        rows = [rows]
    conflicts = [
        row
        for row in rows
        if str(row.get("ExecutablePath", "")).casefold() in expected
    ]
    if conflicts:
        raise VerificationFailure(
            "Pinned bcap stages already have live processes; no process was "
            f"touched: {conflicts}"
        )


def launch_pair() -> tuple[subprocess.Popen[str], Path]:
    flow = EVIDENCE_ROOT / "flow"
    flow.mkdir(parents=True, exist_ok=True)
    pid_path = flow / "pair-processes.json"
    pid_path.unlink(missing_ok=True)
    stdout_path = flow / "pair-launch.stdout.log"
    stderr_path = flow / "pair-launch.stderr.log"
    command = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        windows_path(ROOT / "scripts/Launch-LocalMultiplayerPair.ps1"),
        "-Preset",
        "map_create_fire_mind_hub",
        "-HostPort",
        str(HOST_PORT),
        "-ClientPort",
        str(CLIENT_PORT),
        "-MaxParticipants",
        str(CAPACITY),
        "-HostParticipantId",
        HOST_ID_TEXT,
        "-ClientParticipantId",
        CLIENT_ID_TEXT,
        "-HostName",
        HOST_NAME,
        "-ClientName",
        CLIENT_NAME,
        "-InstancePrefix",
        INSTANCE_PREFIX,
        "-GameDirectory",
        windows_path(GAME_ROOT),
        "-RuntimeRoot",
        windows_path(RUNTIME_ROOT),
        "-LauncherPath",
        windows_path(
            ROOT / "dist/launcher/SolomonDarkModLauncher.exe"
        ),
        "-TemporaryHostProfile",
        "-NoLuaAutomation",
        "-NoTileWindows",
        "-QuickStart",
        "-ExactModIds",
        MOD_ID,
        "-ProcessIdOutputPath",
        windows_path(pid_path),
    ]
    environment = os.environ.copy()
    environment["SDMOD_DISABLE_AUDIO"] = "1"
    environment["SDMOD_ENABLE_AUDIO"] = "0"
    environment["SDMOD_MULTIPLAYER_MAX_PARTICIPANTS"] = str(CAPACITY)
    stdout = stdout_path.open("w", encoding="utf-8", newline="\n")
    stderr = stderr_path.open("w", encoding="utf-8", newline="\n")
    try:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=environment,
            stdout=stdout,
            stderr=stderr,
            text=True,
        )
    finally:
        stdout.close()
        stderr.close()
    return process, pid_path


def read_launch(pid_path: Path) -> dict[str, Any]:
    return json.loads(pid_path.read_text(encoding="utf-8"))


BRAIN_PROBE = r"""
local function emit(key, value)
  if value == nil then value = "" end
  print(key .. "=" .. tostring(value))
end
local scene = sd.world.get_scene()
local debug = rawget(_G, "bot_brain_debug")
local handles = sd.bots.list() or {}
emit("scene", scene and (scene.name or scene.kind) or "")
emit("authority", sd.state.is_authority())
emit("actual.count", #handles)
for index, handle in ipairs(handles) do
  local participant_id = tonumber(handle:participant_id()) or 0
  local state = sd.bots.get_participant_state(participant_id)
  emit("actual." .. index .. ".id", participant_id)
  emit("actual." .. index .. ".name", state and state.name or "")
  emit("actual." .. index .. ".slot", state and state.gameplay_slot or -1)
  emit(
    "actual." .. index .. ".materialized",
    state ~= nil and state.entity_materialized == true)
end
emit("brain.present", debug ~= nil)
emit("brain.desired", debug and debug.desired_bot_count or -1)
emit("brain.active", debug and debug.active_bot_count or -1)
emit("brain.refused", debug and debug.capacity_refused_count or -1)
emit("brain.status", debug and debug.status or "")
emit(
  "brain.status_exact",
  debug ~= nil and
  debug.status == "2 of 4 bots active — lobby full")
emit(
  "brain.reconciliation_errors",
  debug and debug.reconciliation_error_count or -1)
"""


def brain_probe(pipe_name: str) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, BRAIN_PROBE))


def bot_ids(values: dict[str, str]) -> list[int]:
    result = [
        integer(values, f"actual.{index}.id")
        for index in range(1, integer(values, "actual.count") + 1)
    ]
    return sorted(value for value in result if value > 0)


def reload_host_settings() -> dict[str, str]:
    return parse_key_values(
        lua(
            HOST_PIPE,
            f"""
local result = sd.__settings_reload("{MOD_ID}")
print("ok=" .. tostring(result.ok))
print("changed=" .. table.concat(result.changed or {{}}, ","))
print("error=" .. tostring(result.error or ""))
""",
        )
    )


def read_status(instance: str) -> dict[str, Any]:
    return json.loads(status_path(instance).read_text(encoding="utf-8"))


def valid_full_status(status: dict[str, Any]) -> bool:
    members = status.get("members")
    if (
        status.get("enabled") is not True
        or status.get("maxParticipants") != CAPACITY
        or not isinstance(members, list)
        or len(members) != CAPACITY
    ):
        return False
    bots = [member for member in members if member.get("isBot") is True]
    humans = [member for member in members if "isBot" not in member]
    return (
        len(bots) == 2
        and len(humans) == 2
        and all(member.get("isSynthetic") is True for member in bots)
        and all(member.get("participantId", 0) > 0 for member in bots)
        and all(1 <= member.get("gameplaySlot", -1) <= 3 for member in bots)
        and {member.get("participantId") for member in humans}
        == {HOST_ID, CLIENT_ID}
    )


def capture_roster(
    status_file: Path,
    label: str,
    output_path: Path,
) -> dict[str, Any]:
    output_path.unlink(missing_ok=True)
    exe = windows_path(
        ROOT / "dist/ui/SolomonDarkMultiplayerBeta.exe"
    )
    script = (
        "$env:SDMOD_UI_LOBBY_PREVIEW_STATUS="
        f"{powershell_literal(windows_path(status_file))};"
        "$env:SDMOD_UI_LOBBY_PREVIEW_LABEL="
        f"{powershell_literal(label)};"
        "$env:SDMOD_UI_LOBBY_PREVIEW_RTB="
        f"{powershell_literal(windows_path(output_path))};"
        f"$p=Start-Process -FilePath {powershell_literal(exe)} -PassThru;"
        "$p.WaitForExit();exit $p.ExitCode"
    )
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        timeout=40,
        check=False,
    )
    if completed.returncode != 0 or not output_path.is_file():
        raise VerificationFailure(
            f"Roster RenderTargetBitmap failed for {label}: "
            f"{(completed.stderr or completed.stdout).strip()}"
        )
    if output_path.stat().st_size < 10_000:
        raise VerificationFailure(
            f"Roster RenderTargetBitmap was unexpectedly small: {output_path}"
        )
    return {
        "path": str(output_path),
        "bytes": output_path.stat().st_size,
        "renderMechanism": "WPF RenderTargetBitmap in launcher process",
    }


def http_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        url,
        data=(
            json.dumps(payload).encode("utf-8")
            if payload is not None
            else None
        ),
        headers={
            **({"Content-Type": "application/json"} if payload is not None else {}),
            **(headers or {}),
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read()
            return response.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as error:
        body = error.read()
        return error.code, json.loads(body) if body else {}


def start_website() -> tuple[subprocess.Popen[str], Any, Any]:
    website_dir = EVIDENCE_ROOT / "website"
    website_dir.mkdir(parents=True, exist_ok=True)
    stdout = (website_dir / "server.stdout.log").open(
        "w", encoding="utf-8", newline="\n"
    )
    stderr = (website_dir / "server.stderr.log").open(
        "w", encoding="utf-8", newline="\n"
    )
    environment = os.environ.copy()
    environment["ASPNETCORE_ENVIRONMENT"] = "Development"
    environment["ASPNETCORE_URLS"] = DIRECTORY_URL
    environment["Storage__Root"] = str(website_dir / "storage")
    environment["Jwt__Secret"] = JWT_SECRET
    process = subprocess.Popen(
        [
            str(DOTNET),
            str(
                WEBSITE_ROOT
                / "backend/bin/Release/net10.0/Server.dll"
            ),
        ],
        cwd=WEBSITE_ROOT / "backend",
        env=environment,
        stdout=stdout,
        stderr=stderr,
        text=True,
    )
    return process, stdout, stderr


def stop_website(
    process: subprocess.Popen[str],
    stdout: Any,
    stderr: Any,
) -> dict[str, Any]:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    stdout.close()
    stderr.close()
    return {"pid": process.pid, "exitCode": process.returncode}


def compatibility() -> dict[str, Any]:
    return json.loads(
        (
            stage_root(HOST_INSTANCE)
            / ".sdmod/multiplayer-compatibility.json"
        ).read_text(encoding="utf-8")
    )


def password_hash() -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        LOBBY_PASSWORD.encode("utf-8"),
        bytes.fromhex(PASSWORD_SALT),
        PASSWORD_ITERATIONS,
    ).hex()


def announce_payload(status: dict[str, Any]) -> dict[str, Any]:
    contract = compatibility()
    enabled_mods = contract["compatibility"]["enabledMods"]
    return {
        "lobbyId": LOBBY_ID,
        "hostSteamId": str(HOST_ID),
        "hostPlayer": HOST_NAME,
        "privacy": "passwordProtected",
        "password": {
            "algorithm": "pbkdf2-sha256",
            "iterations": PASSWORD_ITERATIONS,
            "salt": PASSWORD_SALT,
            "hash": password_hash(),
        },
        "friendSteamIds": [],
        "players": len(status["members"]),
        "maxPlayers": CAPACITY,
        "build": {
            "appId": 3362180,
            "protocolVersion": status["protocolVersion"],
            "manifestSha256": contract["fingerprintSha256"],
            "loaderVersion": "0.1.0-beta.21",
        },
        "game": {
            "phase": status["gamePhase"],
            "boneyardId": None,
            "boneyardName": None,
            "boneyardSha256": None,
            "wave": None,
            "difficulty": None,
            "elapsedSeconds": None,
            "statusText": (
                "Bots count as lobby members — "
                f"{len(status['members'])}/{CAPACITY}"
            ),
        },
        "mods": [
            {
                "id": mod["id"],
                "version": mod["version"],
                "contentSha256": mod["contentSha256"],
            }
            for mod in enabled_mods
        ],
    }


def base64url(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def viewer_token() -> str:
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": f"steam:{VIEWER_STEAM_ID}",
        "jti": uuid.uuid4().hex,
        "sdr_token_type": "steam-directory",
        "steam_id": VIEWER_STEAM_ID,
        "steam_appid": "3362180",
        "nbf": now - 5,
        "exp": now + 900,
    }
    encoded_header = base64url(
        json.dumps(header, separators=(",", ":")).encode("utf-8")
    )
    encoded_payload = base64url(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    )
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    signature = base64url(
        hmac.new(
            JWT_SECRET.encode("utf-8"),
            signing_input,
            hashlib.sha256,
        ).digest()
    )
    return f"{encoded_header}.{encoded_payload}.{signature}"


def announce(status: dict[str, Any], name: str) -> dict[str, Any]:
    payload = announce_payload(status)
    request_path = EVIDENCE_ROOT / "website" / f"{name}-announce-request.json"
    atomic_write_json(request_path, payload)
    code, body = http_json(
        "POST",
        f"{DIRECTORY_URL}/api/lobbies/announce",
        payload=payload,
        headers={"X-SDR-Lobby-Secret": LOBBY_SECRET},
    )
    if code != 200:
        raise VerificationFailure(
            f"Local website announcement failed ({code}): {body}"
        )
    atomic_write_json(
        EVIDENCE_ROOT / "website" / f"{name}-announce-response.json",
        body,
    )
    return body


def capture_website_row(output_path: Path) -> dict[str, Any]:
    output_path.unlink(missing_ok=True)
    profile = (
        EVIDENCE_ROOT
        / "website"
        / f"chrome-profile-{time.monotonic_ns()}"
    )
    profile.mkdir(parents=True, exist_ok=True)
    chrome_candidates = [
        Path("/mnt/c/Program Files/Google/Chrome/Application/chrome.exe"),
        Path("/mnt/c/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
    ]
    chrome = next(
        (candidate for candidate in chrome_candidates if candidate.is_file()),
        None,
    )
    if chrome is None:
        raise VerificationFailure("Google Chrome was not found for website proof.")
    arguments = [
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--window-size=1440,1000",
        "--force-device-scale-factor=1",
        f"--user-data-dir={windows_path(profile)}",
        f"--screenshot={windows_path(output_path)}",
        f"{DIRECTORY_URL}/classes",
    ]
    try:
        completed = subprocess.run(
            [str(chrome), *arguments],
            capture_output=True,
            text=True,
            timeout=35,
            check=False,
        )
        detail = (completed.stderr or completed.stdout).strip()
        failed = completed.returncode != 0
    except subprocess.TimeoutExpired as exc:
        # Chrome's headless parent can remain attached after the DevTools
        # renderer has produced the requested bitmap. subprocess.run kills
        # and reaps that exact parent on timeout; accept only a complete
        # screenshot rather than letting the browser's shutdown timing turn
        # a rendered acceptance artifact into a false failure.
        detail = str(exc)
        failed = False
        deadline = time.monotonic() + 15
        while not output_path.is_file() and time.monotonic() < deadline:
            time.sleep(0.1)
    if failed or not output_path.is_file():
        raise VerificationFailure(
            f"Local website screenshot failed: {detail}"
        )
    if output_path.stat().st_size < 20_000:
        raise VerificationFailure(
            f"Local website screenshot was unexpectedly small: {output_path}"
        )
    return {
        "path": str(output_path),
        "bytes": output_path.stat().st_size,
        "url": f"{DIRECTORY_URL}/classes",
        "productionTouched": False,
    }


def start_testrun() -> dict[str, str]:
    code = """
local ok, result = sd.hub.start_testrun()
print("ok=" .. tostring(ok))
print("result=" .. tostring(result or ""))
"""
    last: dict[str, str] = {}
    for _ in range(60):
        last = parse_key_values(lua(HOST_PIPE, code))
        if last.get("ok") == "true":
            return last
        if "settling" not in last.get("result", "").casefold():
            raise VerificationFailure(
                f"Host could not enter the test run: {last}"
            )
        time.sleep(0.25)
    raise VerificationFailure(
        f"Host test-run transition did not settle: {last}"
    )


def scene(pipe_name: str) -> str:
    return lua(
        pipe_name,
        """
local value = sd.world.get_scene()
return tostring(value and (value.name or value.kind) or "")
""",
    ).strip()


def target_probe(participant_ids: list[int]) -> dict[str, str]:
    wanted = ",".join(str(value) for value in participant_ids)
    code = f"""
local wanted = {{{wanted}}}
local counts = {{}}
local first = {{}}
for _, participant_id in ipairs(wanted) do
  counts[participant_id] = 0
  first[participant_id] = 0
end
local snapshot = sd.world.get_replicated_actors()
local live = 0
for _, actor in ipairs(snapshot and snapshot.actors or {{}}) do
  if not actor.dead and (tonumber(actor.hp) or 0) > 0.05 then
    live = live + 1
    local target = tonumber(actor.target_participant_id) or 0
    if counts[target] ~= nil then
      counts[target] = counts[target] + 1
      if first[target] == 0 then
        first[target] = tonumber(actor.network_actor_id) or 0
      end
    end
  end
end
print("live=" .. tostring(live))
for index, participant_id in ipairs(wanted) do
  print("bot." .. index .. ".id=" .. tostring(participant_id))
  print("bot." .. index .. ".count=" .. tostring(counts[participant_id]))
  print("bot." .. index .. ".first=" .. tostring(first[participant_id]))
end
"""
    return parse_key_values(lua(HOST_PIPE, code))


def target_identity(
    pipe_name: str,
    participant_id: int,
    network_actor_id: int,
) -> dict[str, str]:
    code = f"""
local found = nil
for _, actor in ipairs(
    (sd.world.get_replicated_actors() or {{}}).actors or {{}}) do
  if tonumber(actor.network_actor_id) == {network_actor_id} then
    found = actor
    break
  end
end
print("found=" .. tostring(found ~= nil))
print("dead=" .. tostring(found ~= nil and found.dead))
print("target=" .. tostring(found and found.target_participant_id or 0))
print("expected=" .. tostring({participant_id}))
"""
    return parse_key_values(lua(pipe_name, code))


def verify_native_targeting(bot_participant_ids: list[int]) -> dict[str, Any]:
    wave_start = parse_key_values(
        lua(
            HOST_PIPE,
            """
print("prelude=" ..
  tostring(sd.gameplay.enable_combat_prelude()))
print("waves=" .. tostring(sd.gameplay.start_waves()))
""",
        )
    )
    if (
        wave_start.get("prelude") != "true"
        or wave_start.get("waves") != "true"
    ):
        raise VerificationFailure(
            f"Stock waves did not start: {wave_start}"
        )

    observations: dict[str, Any] = {"waveStart": wave_start, "bots": {}}
    for participant_id in bot_participant_ids:
        index = bot_participant_ids.index(participant_id) + 1
        def inspect_target_pair() -> dict[str, Any]:
            host = target_probe(bot_participant_ids)
            network_actor_id = integer(host, f"bot.{index}.first")
            client = (
                target_identity(
                    CLIENT_PIPE,
                    participant_id,
                    network_actor_id,
                )
                if network_actor_id > 0
                else {}
            )
            return {
                "host": host,
                "client": client,
                "networkActorId": network_actor_id,
            }

        pair, observed_utc = wait_for(
            inspect_target_pair,
            lambda values, row=index: (
                integer(values["host"], "live") > 0
                and integer(values["host"], f"bot.{row}.count") > 0
                and values["networkActorId"] > 0
                and values["client"].get("found") == "true"
                and values["client"].get("dead") == "false"
                and integer(values["client"], "target")
                == participant_id
            ),
            label=f"native hostile targeting bot {participant_id}",
            timeout=60,
            interval=0.15,
        )
        observations["bots"][str(participant_id)] = {
            "host": pair["host"],
            "client": pair["client"],
            "networkActorId": pair["networkActorId"],
            "observedUtc": observed_utc,
        }
    return observations


def wait_for_ally_hud_rows(
    bot_participant_ids: list[int],
    bot_names: dict[int, str],
) -> dict[str, Any]:
    def inspect() -> dict[str, Any]:
        rows: dict[str, Any] = {}
        for role, instance in (
            ("host", HOST_INSTANCE),
            ("client", CLIENT_INSTANCE),
        ):
            text = log_path(instance).read_text(
                encoding="utf-8",
                errors="replace",
            )
            role_rows: dict[str, str] = {}
            for participant_id in bot_participant_ids:
                tokens = (
                    "source=ally_healthbar",
                    f"participant={participant_id}",
                    f"name={bot_names[participant_id]}",
                    "ok=1",
                    "stock_label=0",
                    "layout_ok=1",
                )
                matching = [
                    line
                    for line in text.splitlines()
                    if all(token in line for token in tokens)
                ]
                if matching:
                    role_rows[str(participant_id)] = matching[-1]
            rows[role] = role_rows
        return rows

    rows, observed_utc = wait_for(
        inspect,
        lambda values: all(
            len(values[role]) == len(bot_participant_ids)
            for role in ("host", "client")
        ),
        label="named ally HUD rows for every active bot on both peers",
        timeout=45,
        interval=0.5,
    )
    return {"observedUtc": observed_utc, "rows": rows}


def copy_runtime_evidence() -> dict[str, str]:
    output = EVIDENCE_ROOT / "runtime-evidence"
    output.mkdir(parents=True, exist_ok=True)
    copied: dict[str, str] = {}
    for role, instance in (
        ("host", HOST_INSTANCE),
        ("client", CLIENT_INSTANCE),
    ):
        root = stage_root(instance)
        for relative, name in (
            (
                Path(".sdmod/logs/solomondarkmodloader.log"),
                f"{role}-loader.log",
            ),
            (
                Path(".sdmod/loader-startup-status.json"),
                f"{role}-startup-status.json",
            ),
            (
                Path(".sdmod/multiplayer-session-status.json"),
                f"{role}-multiplayer-session-status-final.json",
            ),
            (
                Path(".sdmod/multiplayer-compatibility.json"),
                f"{role}-multiplayer-compatibility.json",
            ),
            (
                Path(f".sdmod/mod-settings/{MOD_ID}.json"),
                f"{role}-settings-final.json",
            ),
            (
                Path(".sdmod/stage-report.json"),
                f"{role}-stage-report.json",
            ),
        ):
            source = root / relative
            if not source.is_file():
                continue
            destination = output / name
            shutil.copy2(source, destination)
            copied[name] = str(destination)
    return copied


def fresh_crash_artifacts(started_at: float) -> list[str]:
    result: list[str] = []
    for instance in (HOST_INSTANCE, CLIENT_INSTANCE):
        root = stage_root(instance) / ".sdmod/logs"
        if not root.is_dir():
            continue
        for path in root.glob("*crash*"):
            stat = path.stat()
            if stat.st_size > 0 and stat.st_mtime >= started_at:
                result.append(str(path))
    return result


def verify(timeout_seconds: float) -> dict[str, Any]:
    if ROOT.resolve() != Path("/mnt/c/sd-botcap-20260727").resolve():
        raise VerificationFailure(
            "This verifier is pinned to /mnt/c/sd-botcap-20260727."
        )
    if not WEBSITE_ROOT.is_dir():
        raise VerificationFailure(
            f"Isolated website worktree is missing: {WEBSITE_ROOT}"
        )
    if not DOTNET.is_file():
        raise VerificationFailure(f"Pinned .NET host is missing: {DOTNET}")
    if not GAME_ROOT.is_dir():
        raise VerificationFailure(f"Game source is missing: {GAME_ROOT}")
    if not (
        ROOT / "dist/launcher/SolomonDarkModLauncher.exe"
    ).is_file():
        raise VerificationFailure("Release launcher has not been published.")
    if not (
        ROOT / "dist/ui/SolomonDarkMultiplayerBeta.exe"
    ).is_file():
        raise VerificationFailure("Release launcher UI has not been published.")
    if not (
        WEBSITE_ROOT / "backend/bin/Release/net10.0/Server.dll"
    ).is_file():
        raise VerificationFailure("Local website backend has not been built.")
    if not (WEBSITE_ROOT / "backend/wwwroot/index.html").is_file():
        raise VerificationFailure("Local website frontend has not been built.")

    udp_owners = query_windows_udp_owners()
    if udp_owners and udp_owners not in ("null", "[]"):
        raise VerificationFailure(
            "Pinned UDP port already owned; no process was touched: "
            f"{udp_owners}"
        )
    assert_no_existing_stage_processes()

    flow = EVIDENCE_ROOT / "flow"
    flow.mkdir(parents=True, exist_ok=True)
    write_settings(settings_path(HOST_INSTANCE), [])
    write_settings(settings_path(CLIENT_INSTANCE), [])
    result: dict[str, Any] = {
        "contract": "bot-capacity-membership-v1",
        "success": False,
        "startedUtc": utc_now(),
        "instancePrefix": INSTANCE_PREFIX,
        "ports": {"host": HOST_PORT, "client": CLIENT_PORT},
        "capacity": CAPACITY,
        "audioDisabled": True,
        "productionWebsiteTouched": False,
        "website": {"url": DIRECTORY_URL, "localOnly": True},
    }
    started_at = time.time()
    pair_process: subprocess.Popen[str] | None = None
    launch: dict[str, Any] | None = None
    website_process: subprocess.Popen[str] | None = None
    website_stdout: Any = None
    website_stderr: Any = None
    failure: BaseException | None = None
    try:
        pair_process, pid_path = launch_pair()
        launch, launch_utc = wait_for(
            lambda: read_launch(pid_path),
            lambda value: (
                value.get("hostProcessId") is not None
                and value.get("clientProcessId") is not None
            ),
            label="both exact bcap process ids",
            timeout=180,
            interval=0.2,
        )
        result["launch"] = {**launch, "observedUtc": launch_utc}
        for role in ("host", "client"):
            pid = int(launch[f"{role}ProcessId"])
            expected_path = str(launch[f"{role}ExecutablePath"])
            actual_path = process_path(pid)
            if (
                actual_path is None
                or actual_path.casefold() != expected_path.casefold()
            ):
                raise VerificationFailure(
                    f"{role} PID {pid} escaped its exact stage: "
                    f"expected={expected_path} actual={actual_path}"
                )

        initial, initial_utc = wait_for(
            lambda: {
                "host": brain_probe(HOST_PIPE),
                "client": brain_probe(CLIENT_PIPE),
                "hostStatus": read_status(HOST_INSTANCE),
                "clientStatus": read_status(CLIENT_INSTANCE),
            },
            lambda value: (
                value["host"].get("scene") == "hub"
                and value["client"].get("scene") == "hub"
                and integer(value["host"], "actual.count", -1) == 0
                and integer(value["client"], "actual.count", -1) == 0
                and len(value["hostStatus"].get("members", [])) == 2
                and len(value["clientStatus"].get("members", [])) == 2
            ),
            label="host and one human client in the hub before bots",
            timeout=timeout_seconds,
        )
        result["initialHumans"] = {
            "observedUtc": initial_utc,
            **initial,
        }

        write_settings(settings_path(HOST_INSTANCE), FULL_ROSTER)
        reload_result = reload_host_settings()
        if (
            reload_result.get("ok") != "true"
            or "roster"
            not in reload_result.get("changed", "").split(",")
        ):
            raise VerificationFailure(
                f"Host roster reload failed: {reload_result}"
            )
        result["hostRosterReload"] = reload_result

        full, full_utc = wait_for(
            lambda: {
                "host": brain_probe(HOST_PIPE),
                "client": brain_probe(CLIENT_PIPE),
                "hostStatus": read_status(HOST_INSTANCE),
                "clientStatus": read_status(CLIENT_INSTANCE),
            },
            lambda value: (
                integer(value["host"], "brain.desired", -1) == 4
                and integer(value["host"], "brain.active", -1) == 2
                and integer(value["host"], "brain.refused", -1) == 2
                and value["host"].get("brain.status_exact") == "true"
                and integer(
                    value["host"],
                    "brain.reconciliation_errors",
                    -1,
                )
                == 0
                and integer(value["client"], "brain.desired", -1) == 4
                and integer(value["client"], "brain.active", -1) == 2
                and bot_ids(value["host"]) == bot_ids(value["client"])
                and len(bot_ids(value["host"])) == 2
                and valid_full_status(value["hostStatus"])
                and valid_full_status(value["clientStatus"])
            ),
            label=(
                "two humans plus two bots at 4/4 with graceful "
                "capacity-refused desired rows"
            ),
            timeout=timeout_seconds,
        )
        active_bot_ids = bot_ids(full["host"])
        active_bot_names = {
            integer(full["host"], f"actual.{index}.id"):
                full["host"].get(f"actual.{index}.name", "")
            for index in range(
                1,
                integer(full["host"], "actual.count") + 1,
            )
        }
        if sorted(active_bot_names.values()) != ["Bastion", "Ember"]:
            raise VerificationFailure(
                f"Unexpected active bot identities: {active_bot_names}"
            )
        result["capacityFull"] = {
            "observedUtc": full_utc,
            "activeBotIds": active_bot_ids,
            "hostBrain": full["host"],
            "clientBrain": full["client"],
            "hostStatus": full["hostStatus"],
            "clientStatus": full["clientStatus"],
            "aggregateStatus": "2 of 4 bots active — lobby full",
        }
        atomic_write_json(
            flow / "host-status-full.json",
            full["hostStatus"],
        )
        atomic_write_json(
            flow / "client-status-full.json",
            full["clientStatus"],
        )

        overflow = parse_key_values(
            lua(
                HOST_PIPE,
                """
local bot, err = sd.bots.spawn({
  name = "Overflow",
  class = "ether",
})
print("created=" .. tostring(bot ~= nil))
print("error=" .. tostring(err or ""))
print("count=" .. tostring(#(sd.bots.list() or {})))
""",
            )
        )
        if (
            overflow.get("created") != "false"
            or overflow.get("error") != "lobby full"
            or integer(overflow, "count") != 2
        ):
            raise VerificationFailure(
                f"Beyond-capacity bot spawn was not cleanly refused: {overflow}"
            )
        result["overflowBotSpawn"] = {
            **overflow,
            "structuredLuaResult": [None, "lobby full"],
        }

        roster_dir = EVIDENCE_ROOT / "launcher-rosters"
        roster_dir.mkdir(parents=True, exist_ok=True)
        result["launcherRosterRenders"] = {
            "host": capture_roster(
                flow / "host-status-full.json",
                "HOST · live 4/4 session",
                roster_dir / "host-roster-4-of-4.png",
            ),
            "client": capture_roster(
                flow / "client-status-full.json",
                "CLIENT · live 4/4 session",
                roster_dir / "client-roster-4-of-4.png",
            ),
        }

        website_process, website_stdout, website_stderr = start_website()
        _, website_ready_utc = wait_for(
            lambda: http_json("GET", f"{DIRECTORY_URL}/api/lobbies"),
            lambda value: value[0] == 200,
            label="local development website on TCP 49811",
            timeout=45,
        )
        result["website"]["readyUtc"] = website_ready_utc
        announce(full["hostStatus"], "full")
        listing_code, listing = http_json(
            "GET",
            f"{DIRECTORY_URL}/api/lobbies",
        )
        if listing_code != 200:
            raise VerificationFailure(
                f"Local website listing failed ({listing_code}): {listing}"
            )
        matching = [
            row
            for row in listing.get("items", [])
            if row.get("hostPlayer") == HOST_NAME
        ]
        if (
            len(matching) != 1
            or matching[0].get("players") != 4
            or matching[0].get("maxPlayers") != 4
            or listing.get("playerCount") != 4
        ):
            raise VerificationFailure(
                f"Local website did not list the bot-filled lobby as 4/4: "
                f"{listing}"
            )
        atomic_write_json(
            EVIDENCE_ROOT / "website/lobbies-full.json",
            listing,
        )
        result["website"]["fullListing"] = listing
        result["website"]["fullRowScreenshot"] = capture_website_row(
            EVIDENCE_ROOT / "website/lobby-row-4-of-4.png"
        )

        authorization_headers = {
            "Authorization": f"Bearer {viewer_token()}"
        }
        full_auth_code, full_auth = http_json(
            "POST",
            (
                f"{DIRECTORY_URL}/api/lobbies/"
                f"{matching[0]['id']}/authorize"
            ),
            payload={"passwordHash": password_hash()},
            headers=authorization_headers,
        )
        if (
            full_auth_code != 409
            or full_auth.get("error") != "That lobby is full."
        ):
            raise VerificationFailure(
                "Full-lobby join did not return the standard refusal: "
                f"status={full_auth_code} body={full_auth}"
            )
        result["website"]["fullJoinAttempt"] = {
            "statusCode": full_auth_code,
            "body": full_auth,
            "frontendMessage":
                "The class is full — every seat is taken.",
        }
        atomic_write_json(
            EVIDENCE_ROOT / "website/full-join-refusal.json",
            result["website"]["fullJoinAttempt"],
        )

        result["runStart"] = start_testrun()
        _, host_run_utc = wait_for(
            lambda: scene(HOST_PIPE),
            lambda value: value == "testrun",
            label="host test run",
            timeout=45,
        )
        _, client_run_utc = wait_for(
            lambda: scene(CLIENT_PIPE),
            lambda value: value == "testrun",
            label="client test run",
            timeout=45,
        )
        run_bots, run_bots_utc = wait_for(
            lambda: {
                "host": brain_probe(HOST_PIPE),
                "client": brain_probe(CLIENT_PIPE),
            },
            lambda value: all(
                integer(value[role], "actual.count", -1) == 2
                and all(
                    value[role].get(
                        f"actual.{index}.materialized"
                    )
                    == "true"
                    and 1
                    <= integer(
                        value[role],
                        f"actual.{index}.slot",
                        -1,
                    )
                    <= 3
                    for index in (1, 2)
                )
                for role in ("host", "client")
            ),
            label="all capacity-bounded bots materialized in native slots",
            timeout=30,
        )
        result["runMaterialization"] = {
            "hostSceneUtc": host_run_utc,
            "clientSceneUtc": client_run_utc,
            "observedUtc": run_bots_utc,
            **run_bots,
        }
        result["nativeEnemyTargeting"] = verify_native_targeting(
            active_bot_ids
        )
        result["allyHudNames"] = wait_for_ally_hud_rows(
            active_bot_ids,
            active_bot_names,
        )

        write_settings(
            settings_path(HOST_INSTANCE),
            OPEN_SEAT_ROSTER,
        )
        open_reload = reload_host_settings()
        if (
            open_reload.get("ok") != "true"
            or "roster"
            not in open_reload.get("changed", "").split(",")
        ):
            raise VerificationFailure(
                f"Open-seat roster reload failed: {open_reload}"
            )
        open_seat, open_seat_utc = wait_for(
            lambda: {
                "host": brain_probe(HOST_PIPE),
                "client": brain_probe(CLIENT_PIPE),
                "hostStatus": read_status(HOST_INSTANCE),
                "clientStatus": read_status(CLIENT_INSTANCE),
            },
            lambda value: (
                integer(value["host"], "brain.desired", -1) == 1
                and integer(value["host"], "brain.active", -1) == 1
                and integer(value["host"], "brain.refused", -1) == 0
                and integer(value["client"], "brain.desired", -1) == 1
                and integer(value["client"], "brain.active", -1) == 1
                and len(value["hostStatus"].get("members", [])) == 3
                and len(value["clientStatus"].get("members", [])) == 3
                and active_bot_ids[1]
                not in {
                    member.get("participantId")
                    for member in value["hostStatus"]["members"]
                }
            ),
            label="bot despawn frees one membership seat",
            timeout=30,
        )
        result["openSeat"] = {
            "observedUtc": open_seat_utc,
            "reload": open_reload,
            **open_seat,
        }
        announce(open_seat["hostStatus"], "open-seat")
        open_listing_code, open_listing = http_json(
            "GET",
            f"{DIRECTORY_URL}/api/lobbies",
        )
        if (
            open_listing_code != 200
            or len(open_listing.get("items", [])) != 1
            or open_listing["items"][0].get("players") != 3
            or open_listing["items"][0].get("maxPlayers") != 4
        ):
            raise VerificationFailure(
                f"Open-seat website listing was not 3/4: {open_listing}"
            )
        open_auth_code, open_auth = http_json(
            "POST",
            (
                f"{DIRECTORY_URL}/api/lobbies/"
                f"{matching[0]['id']}/authorize"
            ),
            payload={"passwordHash": password_hash()},
            headers=authorization_headers,
        )
        if (
            open_auth_code != 200
            or open_auth.get("lobbyId") != LOBBY_ID
            or not open_auth.get("ticket")
        ):
            raise VerificationFailure(
                "Join did not succeed after the bot freed a seat: "
                f"status={open_auth_code} body={open_auth}"
            )
        result["website"]["openSeatListing"] = open_listing
        result["website"]["joinAfterBotDespawn"] = {
            "statusCode": open_auth_code,
            "lobbyId": open_auth["lobbyId"],
            "steamId": open_auth["steamId"],
            "ticketIssued": True,
            "launchUriScheme": str(
                open_auth.get("launchUri", "")
            ).split(":", 1)[0],
        }
        atomic_write_json(
            EVIDENCE_ROOT / "website/open-seat-join-success.json",
            result["website"]["joinAfterBotDespawn"],
        )

        result["success"] = True
    except BaseException as exc:
        failure = exc
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if website_process is not None:
            result["websiteCleanup"] = stop_website(
                website_process,
                website_stdout,
                website_stderr,
            )
        cleanup: list[dict[str, Any]] = []
        if launch is not None:
            for role in ("client", "host"):
                pid_value = launch.get(f"{role}ProcessId")
                path_value = launch.get(f"{role}ExecutablePath")
                if pid_value is None or path_value is None:
                    continue
                try:
                    cleanup.append(
                        {
                            "role": role,
                            **stop_owned_process(
                                int(pid_value),
                                str(path_value),
                            ),
                        }
                    )
                except BaseException as cleanup_error:
                    cleanup.append(
                        {
                            "role": role,
                            "error": (
                                f"{type(cleanup_error).__name__}: "
                                f"{cleanup_error}"
                            ),
                        }
                    )
                    if failure is None:
                        failure = cleanup_error
                        result["success"] = False
                        result["error"] = (
                            f"{type(cleanup_error).__name__}: "
                            f"{cleanup_error}"
                        )
        result["cleanup"] = cleanup
        if pair_process is not None:
            try:
                result["pairLauncherExitCode"] = pair_process.wait(
                    timeout=20
                )
            except subprocess.TimeoutExpired:
                pair_process.terminate()
                try:
                    result["pairLauncherExitCode"] = pair_process.wait(
                        timeout=10
                    )
                except subprocess.TimeoutExpired:
                    pair_process.kill()
                    result["pairLauncherExitCode"] = pair_process.wait(
                        timeout=5
                    )
        result["runtimeEvidence"] = copy_runtime_evidence()
        crashes = fresh_crash_artifacts(started_at)
        result["nonemptyCrashArtifacts"] = crashes
        if crashes and failure is None:
            failure = VerificationFailure(
                f"Fresh nonempty crash artifacts found: {crashes}"
            )
            result["success"] = False
            result["error"] = str(failure)
        result["finishedUtc"] = utc_now()
        atomic_write_json(flow / "result.json", result)
        print(json.dumps(result, indent=2, sort_keys=True))
    if failure is not None:
        raise failure
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=EVIDENCE_ROOT,
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=120.0,
    )
    args = parser.parse_args()
    if args.evidence_root.resolve() != EVIDENCE_ROOT.resolve():
        parser.error(
            "this verifier is intentionally pinned to the bcap evidence root"
        )
    try:
        verify(args.timeout_seconds)
    except BaseException as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
