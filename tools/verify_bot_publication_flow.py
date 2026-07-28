#!/usr/bin/env python3
"""Prove the local website-installed Lua Bots lobby and settings flow."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE_ROOT = Path("/mnt/d/codex-evidence/botpub-20260727")
DEFAULT_DIRECTORY_URL = "http://127.0.0.1:49411"
LOBBY_ID = "76561198000006666"
INSTANCE_PREFIX = "bpub"
HOST_INSTANCE = f"{INSTANCE_PREFIX}-host"
CLIENT_INSTANCE = f"{INSTANCE_PREFIX}-client"
HOST_PORT = 49411
CLIENT_PORT = 49412
HOST_PIPE = f"SolomonDarkModLoader_LuaExec_{HOST_INSTANCE}"
CLIENT_PIPE = f"SolomonDarkModLoader_LuaExec_{CLIENT_INSTANCE}"
MOD_ID = "bot.brain"

INITIAL_ROSTER = [
    {
        "name": "Ember",
        "element": "fire",
        "discipline": "arcane",
        "behavior": "skirmisher",
    },
    {
        "name": "Bastion",
        "element": "earth",
        "discipline": "body",
        "behavior": "guardian",
    },
]
CHANGED_ROSTER = [
    {
        "name": "Gale",
        "element": "air",
        "discipline": "mind",
        "behavior": "striker",
    },
    {
        "name": "Bastion",
        "element": "earth",
        "discipline": "body",
        "behavior": "guardian",
    },
]
CLIENT_LOCAL_ROSTER = [
    {
        "name": "ClientLocalDefault",
        "element": "water",
        "discipline": "arcane",
        "behavior": "striker",
    }
]


class VerificationFailure(RuntimeError):
    """Raised when the publication acceptance contract is not satisfied."""


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
    return completed.stdout.strip()


PROBE = r"""
local function emit(key, value)
  if value == nil then value = "" end
  print(key .. "=" .. tostring(value))
end

local function emit_roster(prefix, rows)
  rows = type(rows) == "table" and rows or {}
  emit(prefix .. ".count", #rows)
  for index = 1, 3 do
    local row = rows[index] or {}
    emit(prefix .. "." .. index .. ".name", row.name or "")
    emit(prefix .. "." .. index .. ".element", row.element or "")
    emit(prefix .. "." .. index .. ".discipline", row.discipline or "")
    emit(prefix .. "." .. index .. ".behavior", row.behavior or "")
  end
end

local scene = sd.world.get_scene()
emit("scene", scene and (scene.name or scene.kind) or "")
emit("authority", sd.state.is_authority())
emit("setting.kite_radius", sd.settings.get("kite_radius"))
emit("setting.offense_enabled", sd.settings.get("offense_enabled"))
emit("setting.think_profile", sd.settings.get("think_profile"))
emit_roster("setting.roster", sd.settings.get("roster"))

local handles = sd.bots.list() or {}
local participant_ids = {}
emit("actual.count", #handles)
for index, handle in ipairs(handles) do
  local participant_id = tonumber(handle:participant_id()) or 0
  local snapshot = sd.bots.get_participant_state(participant_id)
  participant_ids[#participant_ids + 1] = tostring(participant_id)
  emit("actual." .. index .. ".participant_id", participant_id)
  emit("actual." .. index .. ".name", snapshot and snapshot.name or "")
  emit(
    "actual." .. index .. ".element_id",
    snapshot and snapshot.profile and snapshot.profile.element_id or -1)
end
emit("actual.participant_ids", table.concat(participant_ids, ","))

local debug = rawget(_G, "bot_brain_debug")
emit("brain.present", debug ~= nil)
emit("brain.startup_apply_count", debug and debug.startup_apply_count or -1)
emit("brain.settings_change_count", debug and debug.settings_change_count or -1)
emit(
  "brain.last_settings_change_key",
  debug and debug.last_settings_change_key or "")
emit(
  "brain.last_roster_new_size",
  debug and debug.last_roster_new_size or -1)
emit("brain.roster_size", debug and debug.roster_size or -1)
emit_roster(
  "brain.startup_roster",
  debug and debug.startup_roster or {})
emit_roster(
  "brain.last_roster_new_value",
  debug and debug.last_roster_new_value or {})
for index = 1, 3 do
  local item = debug and debug.bots and debug.bots[index] or {}
  emit("brain.bot." .. index .. ".name", item.name)
  emit("brain.bot." .. index .. ".element", item.element)
  emit("brain.bot." .. index .. ".discipline", item.discipline)
  emit("brain.bot." .. index .. ".behavior", item.behavior)
  emit("brain.bot." .. index .. ".participant_id", item.participant_id)
end
"""


def parse_key_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.replace("\r", "").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def lua(pipe_name: str, code: str, timeout: float = 15.0) -> str:
    command = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        windows_path(ROOT / "scripts" / "Invoke-LuaExec.ps1"),
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


def probe(pipe_name: str) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, PROBE))


def wait_for(
    operation: Callable[[], Any],
    predicate: Callable[[Any], bool],
    *,
    label: str,
    timeout: float,
    interval: float = 0.4,
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
        except (OSError, subprocess.SubprocessError, VerificationFailure) as exc:
            last_error = str(exc)
        time.sleep(interval)
    raise VerificationFailure(
        f"Timed out waiting for {label}; last={last!r}; "
        f"last_error={last_error!r}"
    )


def roster_from(values: dict[str, str], prefix: str) -> list[dict[str, str]]:
    try:
        count = int(float(values.get(f"{prefix}.count", "0")))
    except ValueError:
        count = 0
    return [
        {
            "name": values.get(f"{prefix}.{index}.name", ""),
            "element": values.get(f"{prefix}.{index}.element", ""),
            "discipline": values.get(
                f"{prefix}.{index}.discipline",
                "",
            ),
            "behavior": values.get(
                f"{prefix}.{index}.behavior",
                "",
            ),
        }
        for index in range(1, count + 1)
    ]


def integer(values: dict[str, str], key: str, default: int = 0) -> int:
    try:
        return int(float(values.get(key, str(default))))
    except ValueError:
        return default


def participant_ids(values: dict[str, str]) -> set[int]:
    result: set[int] = set()
    for raw in values.get("actual.participant_ids", "").split(","):
        try:
            value = int(raw, 10)
        except ValueError:
            continue
        if value > 0:
            result.add(value)
    return result


def bots_match(
    values: dict[str, str],
    expected: list[dict[str, str]],
) -> bool:
    if integer(values, "brain.roster_size", -1) != len(expected):
        return False
    for index, row in enumerate(expected, start=1):
        for key, expected_value in row.items():
            if values.get(f"brain.bot.{index}.{key}") != expected_value:
                return False
    return True


def full_host_scope_matches(
    host: dict[str, str],
    client: dict[str, str],
    expected_roster: list[dict[str, str]],
) -> bool:
    return (
        roster_from(host, "setting.roster") == expected_roster
        and roster_from(client, "setting.roster") == expected_roster
        and host.get("setting.kite_radius") == client.get("setting.kite_radius")
        and float(host.get("setting.kite_radius", "nan")) == 340.0
        and host.get("setting.offense_enabled") == "true"
        and client.get("setting.offense_enabled") == "true"
    )


def initial_converged(views: dict[str, dict[str, str]]) -> bool:
    host = views["host"]
    client = views["client"]
    host_ids = participant_ids(host)
    client_ids = participant_ids(client)
    return (
        host.get("scene") == "hub"
        and client.get("scene") == "hub"
        and host.get("authority") == "true"
        and client.get("authority") == "false"
        and full_host_scope_matches(host, client, INITIAL_ROSTER)
        and roster_from(host, "brain.startup_roster") == INITIAL_ROSTER
        and roster_from(client, "brain.startup_roster") == INITIAL_ROSTER
        and roster_from(client, "brain.startup_roster")
        != CLIENT_LOCAL_ROSTER
        and integer(host, "brain.startup_apply_count", -1) == 1
        and integer(client, "brain.startup_apply_count", -1) == 1
        and integer(client, "brain.settings_change_count", -1) == 0
        and bots_match(host, INITIAL_ROSTER)
        and bots_match(client, INITIAL_ROSTER)
        and integer(host, "actual.count", -1) == 2
        and integer(client, "actual.count", -1) == 2
        and len(host_ids) == 2
        and client_ids == host_ids
    )


def changed_converged(views: dict[str, dict[str, str]]) -> bool:
    host = views["host"]
    client = views["client"]
    return (
        full_host_scope_matches(host, client, CHANGED_ROSTER)
        and bots_match(host, CHANGED_ROSTER)
        and bots_match(client, CHANGED_ROSTER)
        and roster_from(client, "brain.last_roster_new_value")
        == CHANGED_ROSTER
        and integer(client, "brain.settings_change_count", -1) == 1
        and client.get("brain.last_settings_change_key") == "roster"
        and integer(client, "actual.count", -1) == 2
        and participant_ids(client) == participant_ids(host)
    )


def post_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def launch_pair(
    evidence_root: Path,
    directory_url: str,
) -> tuple[dict[str, Any], subprocess.Popen[str]]:
    stdout_path = evidence_root / "flow" / "pair-launch.stdout.log"
    stderr_path = evidence_root / "flow" / "pair-launch.stderr.log"
    result_path = evidence_root / "flow" / "pair-launch.json"
    result_path.unlink(missing_ok=True)
    command = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        windows_path(ROOT / "scripts" / "Launch-BotPublicationPair.ps1"),
        "-EvidenceRoot",
        r"D:\codex-evidence\botpub-20260727",
        "-DirectoryUrl",
        directory_url,
        "-LobbyId",
        LOBBY_ID,
        "-ResultPath",
        windows_path(result_path),
    ]
    stdout = stdout_path.open("w", encoding="utf-8", newline="\n")
    stderr = stderr_path.open("w", encoding="utf-8", newline="\n")
    try:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=stdout,
            stderr=stderr,
            text=True,
        )
    finally:
        stdout.close()
        stderr.close()

    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if result_path.is_file():
            parsed = json.loads(result_path.read_text(encoding="utf-8"))
            return parsed, process
        return_code = process.poll()
        if return_code is not None:
            stdout_text = stdout_path.read_text(
                encoding="utf-8",
                errors="replace",
            )
            stderr_text = stderr_path.read_text(
                encoding="utf-8",
                errors="replace",
            )
            raise VerificationFailure(
                f"Publication pair launch exited {return_code}: "
                + (stderr_text or stdout_text).strip()
            )
        time.sleep(0.2)
    raise VerificationFailure(
        "Publication pair launch did not publish its result within 180 seconds."
    )


def atomic_write_settings(
    path: Path,
    roster: list[dict[str, str]],
) -> None:
    payload = {
        "schemaVersion": 1,
        "values": {
            "focus_bot_key": "NONE",
            "kite_radius": 340,
            "offense_enabled": True,
            "roster": roster,
            "think_profile": "standard",
        },
    }
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


def reload_host_settings() -> dict[str, str]:
    code = f"""
local result = sd.__settings_reload("{MOD_ID}")
print("ok=" .. tostring(result.ok))
print("changed=" .. table.concat(result.changed or {{}}, ","))
print("error=" .. tostring(result.error or ""))
for key, message in pairs(result.entry_errors or {{}}) do
  print("entry_error." .. key .. "=" .. tostring(message))
end
"""
    return parse_key_values(lua(HOST_PIPE, code))


def process_path(pid: int) -> str | None:
    command = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        (
            f"$p=Get-CimInstance Win32_Process -Filter "
            f"'ProcessId={pid}'; if ($null -ne $p) "
            "{ [Console]::Write($p.ExecutablePath) }"
        ),
    ]
    completed = subprocess.run(
        command,
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
        f"Wait-Process -Id {pid} -Timeout 10 -ErrorAction SilentlyContinue "
        "};"
        f"$remaining=Get-Process -Id {pid} -ErrorAction SilentlyContinue;"
        "$forced=$false;"
        "if ($null -ne $remaining) { "
        f"Stop-Process -Id {pid} -Force -ErrorAction Stop;"
        f"Wait-Process -Id {pid} -Timeout 10 -ErrorAction SilentlyContinue;"
        "$forced=$true };"
        "[pscustomobject]@{closed=$closed;forced=$forced}"
        "|ConvertTo-Json -Compress"
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
        timeout=35,
        check=False,
    )
    if completed.returncode != 0:
        raise VerificationFailure(
            f"Exact cleanup failed for PID {pid}: {completed.stderr.strip()}"
        )
    detail = json.loads(completed.stdout.replace("\r", "").strip())
    return {
        "pid": pid,
        "executablePath": actual,
        "alreadyExited": False,
        **detail,
    }


def inspect_client_entry_order(log_text: str) -> dict[str, Any]:
    waiting_text = (
        "entry script waiting for the authoritative host-settings checkpoint."
    )
    ready_pattern = re.compile(
        r"authoritative host settings ready before entry script; "
        r"monotonic_ms=(\d+)"
    )
    started_pattern = re.compile(
        r"started deferred entry script after host settings; "
        r"monotonic_ms=(\d+)"
    )
    waiting_index = log_text.find(waiting_text)
    ready = ready_pattern.search(log_text)
    started = started_pattern.search(log_text)
    if waiting_index < 0 or ready is None or started is None:
        raise VerificationFailure(
            "Client log lacks the explicit wait -> authoritative settings "
            "-> entry-script ordering evidence."
        )
    ready_ms = int(ready.group(1))
    started_ms = int(started.group(1))
    if not (
        waiting_index < ready.start() < started.start()
        and ready_ms <= started_ms
    ):
        raise VerificationFailure(
            "Client entry ordering markers are not monotonic."
        )
    return {
        "waitingLogOffset": waiting_index,
        "authoritativeReadyLogOffset": ready.start(),
        "entryStartedLogOffset": started.start(),
        "authoritativeReadyMonotonicMs": ready_ms,
        "entryStartedMonotonicMs": started_ms,
        "ordered": True,
    }


def copy_runtime_evidence(
    evidence_root: Path,
    runtime_root: Path,
) -> dict[str, str]:
    copied: dict[str, str] = {}
    output = evidence_root / "flow"
    for role, instance in (
        ("host", HOST_INSTANCE),
        ("client", CLIENT_INSTANCE),
    ):
        stage = runtime_root / "instances" / instance / "stage"
        for relative, name in (
            (
                Path(".sdmod/logs/solomondarkmodloader.log"),
                f"{role}-solomondarkmodloader.log",
            ),
            (
                Path(".sdmod/startup-status.json"),
                f"{role}-startup-status.json",
            ),
            (
                Path(".sdmod/multiplayer-session-status.json"),
                f"{role}-multiplayer-session-status.json",
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
            source = stage / relative
            if not source.is_file():
                continue
            destination = output / name
            shutil.copy2(source, destination)
            copied[name] = str(destination)
    return copied


def crash_artifacts(runtime_root: Path, started_at: float) -> list[str]:
    artifacts: list[str] = []
    for instance in (HOST_INSTANCE, CLIENT_INSTANCE):
        log_root = (
            runtime_root
            / "instances"
            / instance
            / "stage"
            / ".sdmod"
            / "logs"
        )
        if not log_root.is_dir():
            continue
        for path in log_root.glob("*crash*"):
            stat = path.stat()
            if stat.st_size > 0 and stat.st_mtime >= started_at:
                artifacts.append(str(path))
    return artifacts


def verify(
    evidence_root: Path,
    directory_url: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    flow_dir = evidence_root / "flow"
    flow_dir.mkdir(parents=True, exist_ok=True)
    runtime_root = evidence_root / "launcher" / "runtime"
    announce_request_path = (
        evidence_root / "website" / "lobby-announce-request.json"
    )
    if not announce_request_path.is_file():
        raise VerificationFailure(
            f"Missing local lobby request: {announce_request_path}"
        )
    announce_request = json.loads(
        announce_request_path.read_text(encoding="utf-8")
    )
    client_initial_path = (
        runtime_root
        / "instances"
        / CLIENT_INSTANCE
        / "stage"
        / ".sdmod"
        / "mod-settings"
        / f"{MOD_ID}.json"
    )
    client_persisted = json.loads(
        client_initial_path.read_text(encoding="utf-8")
    )
    if client_persisted["values"]["roster"] != CLIENT_LOCAL_ROSTER:
        raise VerificationFailure(
            "The deliberately divergent client local default was not seeded."
        )
    shutil.copy2(client_initial_path, flow_dir / "client-settings-before-join.json")

    result: dict[str, Any] = {
        "contract": "lua-bots-publication-flow-v1",
        "success": False,
        "startedUtc": utc_now(),
        "instancePrefix": INSTANCE_PREFIX,
        "ports": {"host": HOST_PORT, "client": CLIENT_PORT},
        "directoryUrl": directory_url,
        "lobbyId": LOBBY_ID,
        "audioDisabled": True,
        "productionTouched": False,
    }
    started_at = time.time()
    launch: dict[str, Any] | None = None
    launch_proxy: subprocess.Popen[str] | None = None
    failure: BaseException | None = None
    try:
        result["lobbyAnnouncement"] = post_json(
            f"{directory_url}/api/lobbies/announce",
            announce_request,
            {
                "X-SDR-Lobby-Secret":
                    "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
                    "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            },
        )
        result["lobbyAnnouncementUtc"] = utc_now()

        launch, launch_proxy = launch_pair(evidence_root, directory_url)
        result["launch"] = launch
        client_sync = launch["client"]["launcher"].get("lobbyModSync")
        if (
            not isinstance(client_sync, dict)
            or client_sync.get("downloadedModCount") != 1
            or client_sync.get("requiredModCount") != 1
        ):
            raise VerificationFailure(
                f"Client did not download the join-preview mod: {client_sync}"
            )
        if any((evidence_root / "launcher" / "client-mods").iterdir()):
            raise VerificationFailure(
                "Client source mods root is no longer empty; website sync was "
                "not isolated to the managed cache."
            )

        initial_views, initial_utc = wait_for(
            lambda: {
                "host": probe(HOST_PIPE),
                "client": probe(CLIENT_PIPE),
            },
            initial_converged,
            label=(
                "host/client hub convergence with two website-installed bots "
                "and authoritative startup settings"
            ),
            timeout=timeout_seconds,
        )
        result["initialConvergence"] = {
            "observedUtc": initial_utc,
            "host": initial_views["host"],
            "client": initial_views["client"],
            "hostScopeEqual": True,
            "clientStartupRosterEqualsHost": True,
            "clientStartupRosterWasNotLocalDefault": True,
            "clientOnChangedCount": 0,
            "replicatedBotCount": 2,
        }

        client_log_path = (
            runtime_root
            / "instances"
            / CLIENT_INSTANCE
            / "stage"
            / ".sdmod"
            / "logs"
            / "solomondarkmodloader.log"
        )
        client_log = client_log_path.read_text(
            encoding="utf-8",
            errors="replace",
        )
        result["clientEntryOrdering"] = inspect_client_entry_order(client_log)
        result["clientEntryOrdering"]["provedUtc"] = utc_now()

        host_settings_path = (
            runtime_root
            / "instances"
            / HOST_INSTANCE
            / "stage"
            / ".sdmod"
            / "mod-settings"
            / f"{MOD_ID}.json"
        )
        atomic_write_settings(host_settings_path, CHANGED_ROSTER)
        shutil.copy2(
            host_settings_path,
            flow_dir / "host-settings-mid-session.json",
        )
        result["hostRosterChangedUtc"] = utc_now()
        reload_result = reload_host_settings()
        result["hostReload"] = reload_result
        if (
            reload_result.get("ok") != "true"
            or "roster" not in reload_result.get("changed", "").split(",")
        ):
            raise VerificationFailure(
                f"Host roster reload failed: {reload_result}"
            )

        changed_views, changed_utc = wait_for(
            lambda: {
                "host": probe(HOST_PIPE),
                "client": probe(CLIENT_PIPE),
            },
            changed_converged,
            label="one-callback mid-session roster convergence",
            timeout=timeout_seconds,
        )
        time.sleep(2)
        stable_client = probe(CLIENT_PIPE)
        if (
            integer(stable_client, "brain.settings_change_count", -1) != 1
            or roster_from(stable_client, "setting.roster")
            != CHANGED_ROSTER
        ):
            raise VerificationFailure(
                "Client roster did not remain stable at exactly one "
                "on_changed callback."
            )
        result["midSessionConvergence"] = {
            "observedUtc": changed_utc,
            "host": changed_views["host"],
            "client": changed_views["client"],
            "stableClient": stable_client,
            "hostScopeEqual": True,
            "clientOnChangedCount": 1,
            "lastNewValueEqualsHostRoster": True,
            "replicatedBotCount": 2,
        }
        persisted_after = json.loads(
            client_initial_path.read_text(encoding="utf-8")
        )
        if persisted_after["values"]["roster"] != CLIENT_LOCAL_ROSTER:
            raise VerificationFailure(
                "Host replication overwrote the client's persisted local "
                "fixture instead of only changing effective host scope."
            )
        result["clientPersistedLocalDefaultUnchanged"] = True
        result["success"] = True
    except BaseException as exc:  # Preserve evidence before re-raising.
        failure = exc
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        cleanup: list[dict[str, Any]] = []
        if launch is not None:
            for role in ("client", "host"):
                process = launch[role]["process"]
                try:
                    cleanup.append(
                        {
                            "role": role,
                            **stop_owned_process(
                                int(process["processId"]),
                                str(process["executablePath"]),
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
        if launch_proxy is not None:
            try:
                result["launchProxyExitCode"] = launch_proxy.wait(timeout=20)
            except subprocess.TimeoutExpired:
                launch_proxy.terminate()
                try:
                    result["launchProxyExitCode"] = launch_proxy.wait(
                        timeout=10
                    )
                except subprocess.TimeoutExpired:
                    result["launchProxyExitCode"] = None
                    result["launchProxyCleanupError"] = (
                        "WSL Windows-process proxy did not exit after owned "
                        "game cleanup."
                    )
        result["evidenceFiles"] = copy_runtime_evidence(
            evidence_root,
            runtime_root,
        )
        crashes = crash_artifacts(runtime_root, started_at)
        result["nonemptyCrashArtifacts"] = crashes
        if crashes and failure is None:
            failure = VerificationFailure(
                f"Fresh nonempty crash artifacts found: {crashes}"
            )
            result["success"] = False
            result["error"] = str(failure)
        result["finishedUtc"] = utc_now()
        result_path = flow_dir / "result.json"
        result_path.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(result, indent=2, sort_keys=True))
    if failure is not None:
        raise failure
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=DEFAULT_EVIDENCE_ROOT,
    )
    parser.add_argument(
        "--directory-url",
        default=DEFAULT_DIRECTORY_URL,
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=90.0,
    )
    args = parser.parse_args()
    if args.evidence_root.resolve() != DEFAULT_EVIDENCE_ROOT.resolve():
        parser.error(
            "this verifier is intentionally pinned to the bpub evidence root"
        )
    if args.directory_url != DEFAULT_DIRECTORY_URL:
        parser.error(
            "this verifier is intentionally pinned to the local website"
        )
    try:
        verify(
            args.evidence_root.resolve(),
            args.directory_url,
            args.timeout_seconds,
        )
    except BaseException as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
