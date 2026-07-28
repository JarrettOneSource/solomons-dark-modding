#!/usr/bin/env python3
"""Verify the v1.0.1 bot-polish contracts on one isolated local pair."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = Path("/mnt/d/codex-evidence/botpolish-20260727")
RUNTIME_ROOT = EVIDENCE_ROOT / "runtime"
AFTER_ROOT = EVIDENCE_ROOT / "after"
FLOW_ROOT = EVIDENCE_ROOT / "flow"
GAME_ROOT = Path(
    "/mnt/c/Users/User/Documents/GitHub/SB Modding/"
    "Solomon Dark/SolomonDarkAbandonware"
)

INSTANCE_PREFIX = "botpolish"
HOST_INSTANCE = f"{INSTANCE_PREFIX}-host"
CLIENT_INSTANCE = f"{INSTANCE_PREFIX}-client"
HOST_PORT = 50011
CLIENT_PORT = 50012
HOST_ID_TEXT = "0x200000000000A101"
CLIENT_ID_TEXT = "0x200000000000A102"
HOST_ID = int(HOST_ID_TEXT, 16)
CLIENT_ID = int(CLIENT_ID_TEXT, 16)
HOST_PIPE = f"SolomonDarkModLoader_LuaExec_{HOST_INSTANCE}"
CLIENT_PIPE = f"SolomonDarkModLoader_LuaExec_{CLIENT_INSTANCE}"
HOST_NAME = "Bot polish host"
CLIENT_NAME = "client B"
EXACT_MOD_ID = "bot.brain"
CAPACITY = 4

ROSTER = [
    {
        "name": "Ember",
        "element": "fire",
        "discipline": "arcane",
        "behavior": "skirmisher",
    },
    {
        "name": "Brook",
        "element": "water",
        "discipline": "mind",
        "behavior": "guardian",
    },
]
EXPECTED_BOTS = {
    "Ember": {
        "elementId": 0,
        "disciplineId": 2,
        "disciplineRow": 7,
        "behavior": "skirmisher",
    },
    "Brook": {
        "elementId": 1,
        "disciplineId": 0,
        "disciplineRow": 6,
        "behavior": "guardian",
    },
}


class BotPolishFailure(RuntimeError):
    """Raised when a bot-polish acceptance invariant is not met."""


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
        raise BotPolishFailure(
            f"Could not convert path for Windows: {path}: "
            f"{completed.stderr.strip()}"
        )
    return completed.stdout.replace("\r", "").strip()


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


def stage_root(instance: str) -> Path:
    return RUNTIME_ROOT / "instances" / instance / "stage"


def settings_path(instance: str) -> Path:
    return (
        stage_root(instance)
        / ".sdmod"
        / "mod-settings"
        / f"{EXACT_MOD_ID}.json"
    )


def status_path(instance: str) -> Path:
    return stage_root(instance) / ".sdmod/multiplayer-session-status.json"


def log_path(instance: str) -> Path:
    return stage_root(instance) / ".sdmod/logs/solomondarkmodloader.log"


def read_log_since(path: Path, byte_offset: int) -> str:
    with path.open("rb") as stream:
        stream.seek(byte_offset)
        return stream.read().decode("utf-8", errors="replace")


def write_settings(instance: str, roster: list[dict[str, str]]) -> None:
    atomic_write_json(
        settings_path(instance),
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


def number(
    values: dict[str, str],
    key: str,
    default: float = math.nan,
) -> float:
    try:
        return float(values.get(key, str(default)).strip())
    except ValueError:
        return default


def wait_for(
    operation: Callable[[], Any],
    predicate: Callable[[Any], bool],
    *,
    label: str,
    timeout: float,
    interval: float = 0.25,
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
            BotPolishFailure,
            json.JSONDecodeError,
            OSError,
            ValueError,
            subprocess.SubprocessError,
        ) as error:
            last_error = str(error)
        time.sleep(interval)
    raise BotPolishFailure(
        f"Timed out waiting for {label}; last={last!r}; "
        f"last_error={last_error!r}"
    )


def lua(pipe_name: str, code: str, timeout: float = 15.0) -> str:
    completed = subprocess.run(
        [
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
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout + 8,
        check=False,
    )
    if completed.returncode != 0:
        raise BotPolishFailure(
            f"Lua exec failed for {pipe_name}: "
            f"{(completed.stderr or completed.stdout).strip()}"
        )
    return completed.stdout


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
        raise BotPolishFailure(completed.stderr.strip())
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
        raise BotPolishFailure(
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
        raise BotPolishFailure(
            f"Exact cleanup failed for PID {pid}: "
            f"{(completed.stderr or completed.stdout).strip()}"
        )
    return {
        "pid": pid,
        "executablePath": expected_path,
        "alreadyExited": False,
        "forced": completed.stdout.strip().casefold() != "true",
    }


def stop_exact_game_processes(launch: dict[str, Any]) -> list[dict[str, Any]]:
    stopped: list[dict[str, Any]] = []
    for role in ("host", "client"):
        stopped.append(
            stop_owned_process(
                int(launch[f"{role}ProcessId"]),
                str(launch[f"{role}ExecutablePath"]),
            )
        )
    return stopped


def query_udp_owners() -> str:
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
        raise BotPolishFailure(
            f"Could not inspect pinned ports: {completed.stderr.strip()}"
        )
    return completed.stdout.replace("\r", "").strip()


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
        raise BotPolishFailure(
            f"Could not inspect existing processes: {completed.stderr.strip()}"
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
        raise BotPolishFailure(
            "Pinned bot-polish stages already have live processes; "
            f"nothing was touched: {conflicts}"
        )


def launch_pair(
    *,
    enable_audio=False,
) -> tuple[subprocess.Popen[str], Path]:
    if enable_audio:
        raise BotPolishFailure("Bot-polish acceptance forbids game audio.")
    FLOW_ROOT.mkdir(parents=True, exist_ok=True)
    pid_path = FLOW_ROOT / "pair-processes.json"
    pid_path.unlink(missing_ok=True)
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
        windows_path(ROOT / "dist/launcher/SolomonDarkModLauncher.exe"),
        "-TemporaryHostProfile",
        "-NoLuaAutomation",
        "-NoTileWindows",
        "-QuickStart",
        "-ExactModIds",
        EXACT_MOD_ID,
        "-ProcessIdOutputPath",
        windows_path(pid_path),
    ]
    environment = os.environ.copy()
    environment["SDMOD_DISABLE_AUDIO"] = "1"
    environment["SDMOD_ENABLE_AUDIO"] = "0"
    environment["SDMOD_MULTIPLAYER_MAX_PARTICIPANTS"] = str(CAPACITY)
    stdout_path = FLOW_ROOT / "pair-launch.stdout.log"
    stderr_path = FLOW_ROOT / "pair-launch.stderr.log"
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


def read_launch(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_status(instance: str) -> dict[str, Any]:
    return json.loads(status_path(instance).read_text(encoding="utf-8"))


def full_status(status: dict[str, Any]) -> bool:
    members = status.get("members")
    if (
        status.get("enabled") is not True
        or status.get("maxParticipants") != CAPACITY
        or not isinstance(members, list)
        or len(members) != CAPACITY
    ):
        return False
    bots = [member for member in members if member.get("isBot") is True]
    humans = [member for member in members if member.get("isBot") is not True]
    return (
        len(bots) == 2
        and len(humans) == 2
        and {member.get("name") for member in bots}
        == set(EXPECTED_BOTS)
        and {member.get("participantId") for member in humans}
        == {HOST_ID, CLIENT_ID}
    )


BOT_PROBE = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local function bytes_hex(bytes)
  if type(bytes) ~= "table" then return "" end
  local parts = {}
  for index, value in ipairs(bytes) do
    parts[index] = string.format("%02X", tonumber(value) or 0)
  end
  return table.concat(parts)
end
local function debug_by_id()
  local result = {}
  local debug = rawget(_G, "bot_brain_debug")
  for _, row in ipairs(debug and debug.bots or {}) do
    result[tonumber(row.participant_id) or 0] = row
  end
  return result, debug
end
local debug_rows, debug = debug_by_id()
local handles = sd.bots.list() or {}
local scene = sd.world.get_scene() or {}
emit("scene", scene.name or scene.kind or "")
emit("authority", sd.state.is_authority())
emit("count", #handles)
emit("brain.active", debug and debug.active_bot_count or -1)
emit("brain.desired", debug and debug.desired_bot_count or -1)
local table_base_offset =
  sd.debug.layout_offset("standalone_wizard_progression_table_base")
local table_count_offset =
  sd.debug.layout_offset("standalone_wizard_progression_table_count")
local entry_stride =
  sd.debug.layout_offset("standalone_wizard_progression_entry_stride")
local active_offset =
  sd.debug.layout_offset("standalone_wizard_progression_active_flag")
local effective_offset =
  sd.debug.layout_offset(
    "standalone_wizard_progression_entry_effective_rank")
local selected_offset =
  sd.debug.layout_offset("player_progression_discipline_skill_row")
local gameplay_slot = sd.debug.resolve_game_address(0x0081C264)
local gameplay = gameplay_slot and
  tonumber(sd.debug.read_ptr(gameplay_slot)) or 0
emit("native.gameplay", gameplay)
for _, row in ipairs({5, 6, 7}) do
  emit("native.row." .. row .. ".disabled",
    gameplay > 0 and
    sd.debug.read_u8(gameplay + 0x1668 + row) or -1)
end
for index, handle in ipairs(handles) do
  local id = tonumber(handle:participant_id()) or 0
  local bot = sd.bots.get_participant_state(id)
  local profile = bot and bot.profile or {}
  local primary = bot and bot.primary_visual_lane or {}
  local secondary = bot and bot.secondary_visual_lane or {}
  local attachment = bot and bot.attachment_visual_lane or {}
  local debug_row = debug_rows[id] or {}
  local nameplate = bot and bot.actor_address and
    sd.bots.get_nameplate(bot.actor_address) or {}
  local prefix = "bot." .. index .. "."
  emit(prefix .. "id", id)
  emit(prefix .. "name", bot and bot.name or "")
  emit(prefix .. "element", profile.element_id)
  emit(prefix .. "discipline", profile.discipline_id)
  emit(prefix .. "behavior", debug_row.behavior)
  emit(prefix .. "debug_discipline", debug_row.discipline)
  emit(prefix .. "slot", bot and bot.gameplay_slot or -1)
  emit(prefix .. "materialized",
    bot ~= nil and bot.entity_materialized == true)
  emit(prefix .. "actor", bot and bot.actor_address or 0)
  emit(prefix .. "x", bot and bot.x or 0)
  emit(prefix .. "y", bot and bot.y or 0)
  emit(prefix .. "robe.type", primary.current_object_type_id)
  emit(prefix .. "robe.color_valid",
    primary.current_object_color_state_valid)
  emit(prefix .. "robe.color",
    bytes_hex(primary.current_object_color_state))
  emit(prefix .. "hat.type", secondary.current_object_type_id)
  emit(prefix .. "hat.color_valid",
    secondary.current_object_color_state_valid)
  emit(prefix .. "hat.color",
    bytes_hex(secondary.current_object_color_state))
  emit(prefix .. "staff.type", attachment.current_object_type_id)
  emit(prefix .. "nameplate", nameplate.name)
  local progression =
    tonumber(bot and bot.progression_runtime_state_address) or 0
  emit(prefix .. "progression", progression)
  local table_address =
    progression > 0 and table_base_offset and
    tonumber(sd.debug.read_ptr(progression + table_base_offset)) or 0
  local table_count =
    progression > 0 and table_count_offset and
    tonumber(sd.debug.read_i32(progression + table_count_offset)) or 0
  emit(prefix .. "book.table", table_address)
  emit(prefix .. "book.count", table_count)
  emit(prefix .. "book.selected",
    progression > 0 and selected_offset and
    sd.debug.read_i32(progression + selected_offset) or -1)
  for _, row in ipairs({5, 6, 7}) do
    local entry = table_address > 0 and entry_stride and
      table_address + row * entry_stride or 0
    emit(prefix .. "book." .. row .. ".active",
      entry > 0 and active_offset and
      sd.debug.read_u16(entry + active_offset) or -1)
    emit(prefix .. "book." .. row .. ".effective",
      entry > 0 and effective_offset and
      sd.debug.read_u16(entry + effective_offset) or -1)
    local definition = entry > 0 and
      tonumber(sd.debug.read_ptr(entry + 0x6C)) or 0
    emit(prefix .. "book." .. row .. ".definition", definition)
    emit(prefix .. "book." .. row .. ".maximum",
      definition > 0 and sd.debug.read_i32(definition + 0x5C) or -1)
  end
end
"""


def bot_probe(pipe_name: str) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, BOT_PROBE))


def bot_rows(values: dict[str, str]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for index in range(1, integer(values, "count") + 1):
        prefix = f"bot.{index}."
        name = values.get(prefix + "name", "")
        rows[name] = {
            "id": integer(values, prefix + "id"),
            "elementId": integer(values, prefix + "element", -1),
            "disciplineId": integer(
                values, prefix + "discipline", -1
            ),
            "behavior": values.get(prefix + "behavior", ""),
            "debugDiscipline": values.get(
                prefix + "debug_discipline", ""
            ),
            "slot": integer(values, prefix + "slot", -1),
            "materialized":
                values.get(prefix + "materialized") == "true",
            "actor": integer(values, prefix + "actor"),
            "x": number(values, prefix + "x"),
            "y": number(values, prefix + "y"),
            "robeType": integer(values, prefix + "robe.type"),
            "robeColorValid":
                values.get(prefix + "robe.color_valid") == "true",
            "robeColor": values.get(prefix + "robe.color", ""),
            "hatType": integer(values, prefix + "hat.type"),
            "hatColorValid":
                values.get(prefix + "hat.color_valid") == "true",
            "hatColor": values.get(prefix + "hat.color", ""),
            "staffType": integer(values, prefix + "staff.type"),
            "nameplate": values.get(prefix + "nameplate", ""),
            "progression": integer(values, prefix + "progression"),
            "bookTable": integer(values, prefix + "book.table"),
            "bookCount": integer(values, prefix + "book.count"),
            "selectedRow": integer(values, prefix + "book.selected", -1),
            "book": {
                str(row): {
                    "active": integer(
                        values,
                        prefix + f"book.{row}.active",
                        -1,
                    ),
                    "effective": integer(
                        values,
                        prefix + f"book.{row}.effective",
                        -1,
                    ),
                    "definition": integer(
                        values,
                        prefix + f"book.{row}.definition",
                    ),
                    "maximum": integer(
                        values,
                        prefix + f"book.{row}.maximum",
                        -1,
                    ),
                }
                for row in (5, 6, 7)
            },
        }
    return rows


def valid_bot_probe(values: dict[str, str]) -> bool:
    if (
        values.get("scene") != "hub"
        or integer(values, "count", -1) != 2
        or integer(values, "brain.active", -1) != 2
        or integer(values, "brain.desired", -1) != 2
    ):
        return False
    rows = bot_rows(values)
    if set(rows) != set(EXPECTED_BOTS):
        return False
    colors: set[str] = set()
    for name, expected in EXPECTED_BOTS.items():
        row = rows[name]
        if (
            row["id"] <= 0
            or row["elementId"] != expected["elementId"]
            or row["disciplineId"] != expected["disciplineId"]
            or row["behavior"] != expected["behavior"]
            or row["debugDiscipline"]
            != ROSTER[list(EXPECTED_BOTS).index(name)]["discipline"]
            or not 1 <= row["slot"] <= 3
            or not row["materialized"]
            or row["actor"] <= 0
            or row["robeType"] != 0x1B5E
            or row["hatType"] != 0x1B5D
            or row["staffType"] != 0x1B5C
            or not row["robeColorValid"]
            or not row["hatColorValid"]
            or not row["robeColor"]
            or set(row["robeColor"]) == {"0"}
            or row["nameplate"] != name
            or row["progression"] <= 0
            or row["bookTable"] <= 0
            or row["bookCount"] <= expected["disciplineRow"]
            or row["selectedRow"] != expected["disciplineRow"]
            or any(
                row["book"][str(base_row)]["active"] != 1
                or row["book"][str(base_row)]["effective"] != 1
                or row["book"][str(base_row)]["definition"] <= 0
                or row["book"][str(base_row)]["maximum"] < 1
                for base_row in (5, 6, 7)
            )
        ):
            return False
        colors.add(row["robeColor"])
    return len(colors) == len(EXPECTED_BOTS)


def assert_peer_visual_agreement(
    host: dict[str, str],
    client_b: dict[str, str],
) -> dict[str, Any]:
    host_rows = bot_rows(host)
    client_rows = bot_rows(client_b)
    if set(host_rows) != set(client_rows):
        raise BotPolishFailure(
            f"Host/client B bot names disagree: {host_rows} {client_rows}"
        )
    for name in host_rows:
        left = host_rows[name]
        right = client_rows[name]
        for key in (
            "id",
            "elementId",
            "disciplineId",
            "behavior",
            "debugDiscipline",
            "robeType",
            "robeColor",
            "hatType",
            "hatColor",
            "staffType",
            "nameplate",
            "selectedRow",
        ):
            if left[key] != right[key]:
                raise BotPolishFailure(
                    f"Host/client B {name} mismatch for {key}: "
                    f"{left[key]!r} != {right[key]!r}"
                )
        for base_row in ("5", "6", "7"):
            for field in ("active", "effective", "maximum"):
                if left["book"][base_row][field] != right["book"][base_row][field]:
                    raise BotPolishFailure(
                        f"Host/client B {name} Discipline book mismatch "
                        f"for row {base_row} {field}: "
                        f"{left['book'][base_row][field]} != "
                        f"{right['book'][base_row][field]}"
                    )
    return {"host": host_rows, "clientB": client_rows}


def capture_window(pid: int, output: Path) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    completed = subprocess.run(
        [
            "py.exe",
            windows_path(ROOT / "scripts/capture_window.py"),
            "--pid",
            str(pid),
            "--output",
            windows_path(output),
            "--method",
            "window",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if (
        completed.returncode != 0
        or not output.is_file()
        or output.stat().st_size < 10_000
    ):
        raise BotPolishFailure(
            f"Window capture failed for PID {pid}: "
            f"{(completed.stderr or completed.stdout).strip()}"
        )
    return {
        "path": str(output),
        "bytes": output.stat().st_size,
        "foregroundActivation": False,
    }


def reload_roster(roster: list[dict[str, str]]) -> dict[str, str]:
    write_settings(HOST_INSTANCE, roster)
    return parse_key_values(
        lua(
            HOST_PIPE,
            f"""
local result = sd.__settings_reload("{EXACT_MOD_ID}")
print("ok=" .. tostring(result.ok))
print("changed=" .. table.concat(result.changed or {{}}, ","))
print("error=" .. tostring(result.error or ""))
""",
        )
    )


def start_testrun() -> dict[str, str]:
    code = """
local ok, result = sd.hub.start_testrun()
print("ok=" .. tostring(ok))
print("result=" .. tostring(result or ""))
"""
    last: dict[str, str] = {}
    for _ in range(80):
        last = parse_key_values(lua(HOST_PIPE, code))
        if last.get("ok") == "true":
            return last
        if "settling" not in last.get("result", "").casefold():
            raise BotPolishFailure(
                f"Host could not enter the test run: {last}"
            )
        time.sleep(0.25)
    raise BotPolishFailure(
        f"Host test-run transition did not settle: {last}"
    )


def arm_survival_guard(
    pipe_name: str,
    bot_id: int | None = None,
) -> dict[str, str]:
    guarded_bot_id = bot_id or 0
    values = parse_key_values(
        lua(
            pipe_name,
            f"""
local guarded_bot_id = {guarded_bot_id}
local hp_offset = sd.debug.layout_offset("progression_hp")
local max_hp_offset = sd.debug.layout_offset("progression_max_hp")
local function refill(progression)
  progression = tonumber(progression) or 0
  if progression <= 0 or hp_offset == nil or max_hp_offset == nil then
    return false
  end
  local maximum =
    tonumber(sd.debug.read_float(progression + max_hp_offset)) or 0
  return maximum > 0 and
    sd.debug.write_float(progression + hp_offset, maximum) or false
end
local function sustain()
  if _G.__botpolish_survival_guard ~= true then
    return
  end
  local player = sd.player.get_state()
  refill(player and player.progression_address)
  if guarded_bot_id > 0 then
    local bot = sd.bots.get_participant_state(guarded_bot_id)
    refill(bot and bot.progression_runtime_state_address)
  end
end
if _G.__botpolish_survival_guard ~= true then
  _G.__botpolish_survival_guard = true
  sd.events.on("runtime.tick", sustain)
end
sustain()
local player = sd.player.get_state()
local bot = guarded_bot_id > 0 and
  sd.bots.get_participant_state(guarded_bot_id) or nil
print("registered=" .. tostring(
  _G.__botpolish_survival_guard == true))
print("player=" .. tostring(
  player ~= nil and
  (tonumber(player.progression_address) or 0) > 0))
print("bot=" .. tostring(
  guarded_bot_id == 0 or
  (bot ~= nil and
    (tonumber(bot.progression_runtime_state_address) or 0) > 0)))
""",
        )
    )
    if (
        values.get("registered") != "true"
        or values.get("player") != "true"
        or values.get("bot") != "true"
    ):
        raise BotPolishFailure(
            f"Could not arm the isolated survival guard: {values}"
        )
    return values


def scene(pipe_name: str) -> str:
    return lua(
        pipe_name,
        """
local value = sd.world.get_scene()
return tostring(value and (value.name or value.kind) or "")
""",
    ).strip()


def spawn_direct_bot() -> tuple[int, dict[str, str]]:
    values = parse_key_values(
        lua(
            HOST_PIPE,
            """
local bot, err = sd.bots.spawn({
  name = "Pathfinder",
  class = "earth",
  discipline = "body",
})
print("created=" .. tostring(bot ~= nil))
print("error=" .. tostring(err or ""))
print("id=" .. tostring(bot and bot:participant_id() or 0))
""",
        )
    )
    bot_id = integer(values, "id")
    if values.get("created") != "true" or bot_id <= 0:
        raise BotPolishFailure(f"Direct bot creation failed: {values}")
    return bot_id, values


def bot_motion(pipe_name: str, bot_id: int) -> dict[str, str]:
    return parse_key_values(
        lua(
            pipe_name,
            f"""
local bot = sd.bots.get_participant_state({bot_id})
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
emit("present", bot ~= nil)
emit("materialized", bot and bot.entity_materialized or false)
emit("x", bot and bot.x or 0)
emit("y", bot and bot.y or 0)
emit("state", bot and bot.state or "")
emit("moving", bot and bot.moving or false)
emit("has_target", bot and bot.has_target or false)
emit("target_x", bot and bot.target_x or 0)
emit("target_y", bot and bot.target_y or 0)
emit("distance", bot and bot.distance_to_target or 0)
emit("actor", bot and bot.actor_address or 0)
emit("vector_x", bot and bot.actor_address and
  sd.debug.read_float(bot.actor_address + 0x158) or 0)
emit("vector_y", bot and bot.actor_address and
  sd.debug.read_float(bot.actor_address + 0x15C) or 0)
""",
        )
    )


def choose_blocked_target(bot_id: int) -> dict[str, str]:
    code = f"""
local bot = sd.bots.get_participant_state({bot_id})
local grid = sd.nav.get_grid(2)
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
if bot == nil or grid == nil or grid.refresh_pending then
  emit("ready", false)
  return
end
local cells = {{}}
for _, cell in ipairs(grid.cells or {{}}) do
  cells[tostring(cell.grid_x) .. ":" .. tostring(cell.grid_y)] = cell
end
local host = sd.player.get_state()
local client = sd.bots.get_participant_state({CLIENT_ID})
local function clears_participant(state, x, y)
  if state == nil or state.x == nil or state.y == nil then
    return false
  end
  local dx = x - state.x
  local dy = y - state.y
  return dx * dx + dy * dy >= 250 * 250
end
local best = nil
for _, target in ipairs(grid.cells or {{}}) do
  local participant_clear =
    clears_participant(host, target.center_x, target.center_y) and
    clears_participant(client, target.center_x, target.center_y) and
    clears_participant(bot, target.center_x, target.center_y)
  if target.path_traversable ~= true and participant_clear then
    local target_ok, target_placement = pcall(
      sd.debug.test_native_movement_collision,
      target.center_x,
      target.center_y,
      nil,
      1,
      0)
    if target_ok and target_placement.ok and target_placement.blocked then
      for dx = -1, 1 do
        for dy = -1, 1 do
          if dx ~= 0 or dy ~= 0 then
            local stage = cells[
              tostring(target.grid_x + dx) .. ":" ..
                tostring(target.grid_y + dy)]
            if stage ~= nil and stage.path_traversable == true then
              local stage_ok, stage_placement = pcall(
                sd.debug.test_native_movement_collision,
                stage.center_x,
                stage.center_y,
                nil,
                1,
                0)
              local wall_ok, wall_clear = pcall(
                sd.nav.test_segment,
                stage.center_x,
                stage.center_y,
                target.center_x,
                target.center_y)
              local stage_dx = stage.center_x - bot.x
              local stage_dy = stage.center_y - bot.y
              local stage_distance =
                math.sqrt(stage_dx * stage_dx + stage_dy * stage_dy)
              local wall_dx = target.center_x - stage.center_x
              local wall_dy = target.center_y - stage.center_y
              local wall_distance =
                math.sqrt(wall_dx * wall_dx + wall_dy * wall_dy)
              if stage_ok and stage_placement.ok and
                  not stage_placement.blocked and
                  wall_ok and not wall_clear and
                  wall_distance >= 80 and wall_distance <= 180 and
                  (best == nil or
                    stage_distance < best.stage_distance) then
                best = {{
                  x = target.center_x,
                  y = target.center_y,
                  grid_x = target.grid_x,
                  grid_y = target.grid_y,
                  native_result = target_placement.native_result,
                  radius = target_placement.radius,
                  placement_mode = target_placement.mode,
                  stage_x = stage.center_x,
                  stage_y = stage.center_y,
                  stage_grid_x = stage.grid_x,
                  stage_grid_y = stage.grid_y,
                  stage_distance = stage_distance,
                  wall_distance = wall_distance,
                }}
              end
            end
          end
        end
      end
    end
  end
end
emit("ready", best ~= nil)
emit("x", best and best.x or 0)
emit("y", best and best.y or 0)
emit("grid_x", best and best.grid_x or -1)
emit("grid_y", best and best.grid_y or -1)
emit("native_result", best and best.native_result or 0)
emit("radius", best and best.radius or 0)
emit("placement_mode", best and best.placement_mode or "")
emit("stage_x", best and best.stage_x or 0)
emit("stage_y", best and best.stage_y or 0)
emit("stage_grid_x", best and best.stage_grid_x or -1)
emit("stage_grid_y", best and best.stage_grid_y or -1)
emit("stage_distance", best and best.stage_distance or 0)
emit("wall_distance", best and best.wall_distance or 0)
emit("stagePlacementClear", best ~= nil)
emit("stageCellTraversable", best ~= nil)
emit("participantClear", best ~= nil)
emit("obstacleCellTarget", best ~= nil)
emit("targetPlacementBlocked", best ~= nil)
emit("pathBlocked", best ~= nil)
"""
    values, _ = wait_for(
        lambda: parse_key_values(lua(HOST_PIPE, code)),
        lambda row: row.get("ready") == "true",
        label="a native-blocked procedural wall fixture",
        timeout=20,
        interval=0.5,
    )
    return values


def choose_reachable_target(bot_id: int) -> dict[str, str]:
    code = f"""
local bot = sd.bots.get_participant_state({bot_id})
local grid = sd.nav.get_grid(2)
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
if bot == nil or grid == nil or grid.refresh_pending then
  emit("ready", false)
  return
end
local best = nil
for _, cell in ipairs(grid.cells or {{}}) do
  if cell.path_traversable == true then
    local ok, clear = pcall(
      sd.nav.test_segment,
      bot.x,
      bot.y,
      cell.center_x,
      cell.center_y)
    local dx = cell.center_x - bot.x
    local dy = cell.center_y - bot.y
    local distance = math.sqrt(dx * dx + dy * dy)
    if ok and clear and distance >= 180 and distance <= 700 and
        (best == nil or distance > best.distance) then
      best = {{
        x = cell.center_x,
        y = cell.center_y,
        distance = distance,
      }}
    end
  end
end
emit("ready", best ~= nil)
emit("x", best and best.x or 0)
emit("y", best and best.y or 0)
emit("distance", best and best.distance or 0)
"""
    values, _ = wait_for(
        lambda: parse_key_values(lua(HOST_PIPE, code)),
        lambda row: row.get("ready") == "true",
        label="a long directly reachable movement target",
        timeout=20,
        interval=0.5,
    )
    return values


def issue_move(bot_id: int, target: dict[str, str]) -> dict[str, str]:
    values = parse_key_values(
        lua(
            HOST_PIPE,
            "print('ok=' .. tostring(sd.bots.move_to("
            f"{bot_id}, {number(target, 'x'):.9f}, "
            f"{number(target, 'y'):.9f})))",
        )
    )
    if values.get("ok") != "true":
        raise BotPolishFailure(f"Bot move command failed: {values}")
    return values


def stop_bot(bot_id: int) -> dict[str, str]:
    values = parse_key_values(
        lua(
            HOST_PIPE,
            f"print('ok=' .. tostring(sd.bots.stop({bot_id})))",
        )
    )
    if values.get("ok") != "true":
        raise BotPolishFailure(f"Bot stop command failed: {values}")
    return values


def staged_wall_probe(
    bot_id: int,
    target: dict[str, str],
) -> dict[str, str]:
    return parse_key_values(
        lua(
            HOST_PIPE,
            f"""
local bot = sd.bots.get_participant_state({bot_id})
local ok, clear = pcall(
  sd.nav.test_segment,
  bot.x,
  bot.y,
  {number(target, "x"):.9f},
  {number(target, "y"):.9f})
local dx = {number(target, "x"):.9f} - bot.x
local dy = {number(target, "y"):.9f} - bot.y
print("ok=" .. tostring(ok))
print("blocked=" .. tostring(ok and not clear))
print("distance=" .. tostring(math.sqrt(dx * dx + dy * dy)))
""",
        )
    )


STUCK_LINE = re.compile(
    r"\[bots\] stuck teleport\. "
    r"bot_id=(?P<bot_id>\d+).*?"
    r"target=\((?P<target_x>-?[0-9.]+), "
    r"(?P<target_y>-?[0-9.]+)\).*?"
    r"landing=\((?P<landing_x>-?[0-9.]+), "
    r"(?P<landing_y>-?[0-9.]+)\).*?"
    r"window_ms=(?P<window_ms>\d+).*?"
    r"search_distance=(?P<search_distance>[0-9.]+)"
)


def stuck_rows(text: str, bot_id: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for match in STUCK_LINE.finditer(text):
        if int(match.group("bot_id")) != bot_id:
            continue
        rows.append(
            {
                "botId": bot_id,
                "targetX": float(match.group("target_x")),
                "targetY": float(match.group("target_y")),
                "landingX": float(match.group("landing_x")),
                "landingY": float(match.group("landing_y")),
                "windowMs": int(match.group("window_ms")),
                "searchDistance": float(
                    match.group("search_distance")
                ),
                "line": match.group(0),
            }
        )
    return rows


def accepted_stuck_placement(
    text: str,
    bot_id: int,
) -> dict[str, Any] | None:
    marker = "[bots] native spawn placement accepted."
    candidates: list[dict[str, str]] = []
    for line in text.splitlines():
        if marker not in line:
            continue
        fields = dict(
            re.findall(
                r"([a-z_]+)=([^ ]+)",
                line.split(marker, 1)[1],
            )
        )
        if (
            fields.get("bot_id") == str(bot_id)
            and fields.get("phase") == "stuck_teleport"
        ):
            candidates.append(fields)
    if not candidates:
        return None
    fields = candidates[-1]
    return {
        "anchorX": float(fields["anchor_x"]),
        "anchorY": float(fields["anchor_y"]),
        "resolvedX": float(fields["resolved_x"]),
        "resolvedY": float(fields["resolved_y"]),
        "radius": float(fields["radius"]),
        "probeCount": int(fields["probe_count"]),
        "searchDistance": float(fields["search_distance"]),
        "searchBound": float(fields["search_bound"]),
        "basicResult": int(fields["basic_result"]),
        "extendedResult": int(fields["extended_result"]),
    }


def verify_stuck_teleport(bot_id: int) -> dict[str, Any]:
    target = choose_blocked_target(bot_id)
    stage_target = {
        "x": target["stage_x"],
        "y": target["stage_y"],
    }
    log_file = log_path(HOST_INSTANCE)
    stage_log_offset = log_file.stat().st_size
    stage_move = issue_move(bot_id, stage_target)
    staged, staged_utc = wait_for(
        lambda: bot_motion(HOST_PIPE, bot_id),
        lambda row: (
            math.hypot(
                number(row, "x") - number(target, "stage_x"),
                number(row, "y") - number(target, "stage_y"),
            )
            <= 18
            or (
                row.get("has_target") == "false"
                and math.hypot(
                    number(row, "x") - number(target, "stage_x"),
                    number(row, "y") - number(target, "stage_y"),
                )
                <= 300
            )
        ),
        label="bot staged beside the blocked target",
        timeout=90,
        interval=0.1,
    )
    stage_stop = stop_bot(bot_id)
    stopped, stopped_utc = wait_for(
        lambda: bot_motion(HOST_PIPE, bot_id),
        lambda row: (
            row.get("has_target") == "false"
            and abs(number(row, "vector_x")) <= 0.001
            and abs(number(row, "vector_y")) <= 0.001
        ),
        label="staged bot with cleared movement intent",
        timeout=10,
        interval=0.1,
    )
    stage_recovery_rows = stuck_rows(
        read_log_since(log_file, stage_log_offset),
        bot_id,
    )
    if len(stage_recovery_rows) > 1:
        raise BotPolishFailure(
            "Staging required more than one recovery teleport: "
            f"{stage_recovery_rows}"
        )
    if stage_recovery_rows:
        time.sleep(10.5)
    wall_probe = staged_wall_probe(bot_id, target)
    if (
        target.get("stagePlacementClear") != "true"
        or target.get("stageCellTraversable") != "true"
        or target.get("participantClear") != "true"
        or target.get("obstacleCellTarget") != "true"
        or wall_probe.get("ok") != "true"
        or wall_probe.get("blocked") != "true"
        or number(wall_probe, "distance") > 225
    ):
        raise BotPolishFailure(
            "Bot was not staged immediately behind the selected wall: "
            f"target={target} staged={staged} stopped={stopped} "
            f"wall={wall_probe}"
        )

    log_offset = log_file.stat().st_size
    move = issue_move(bot_id, target)
    issued_at = time.monotonic()

    def inspect() -> dict[str, Any]:
        text = read_log_since(log_file, log_offset)
        rows = stuck_rows(text, bot_id)
        placement = accepted_stuck_placement(text, bot_id)
        return {
            "rows": rows,
            "placement": placement,
        }

    try:
        observed, observed_utc = wait_for(
            inspect,
            lambda value: len(value["rows"]) == 1
            and value["placement"] is not None,
            label="one authority-owned stuck teleport",
            timeout=100,
            interval=0.2,
        )
    except BotPolishFailure as error:
        raise BotPolishFailure(
            f"{error}; target={target}; "
            f"final_host={bot_motion(HOST_PIPE, bot_id)}; "
            f"final_client_b={bot_motion(CLIENT_PIPE, bot_id)}"
        ) from error
    elapsed_ms = int((time.monotonic() - issued_at) * 1000)
    row = observed["rows"][0]
    placement = observed["placement"]
    assert placement is not None
    if not 29_000 <= elapsed_ms <= 130_000:
        raise BotPolishFailure(
            f"Stuck teleport command-to-recovery time was implausible: "
            f"{elapsed_ms} ms"
        )
    if not 29_900 <= row["windowMs"] <= 31_500:
        raise BotPolishFailure(
            f"Native stuck window was not approximately 30 seconds: {row}"
        )
    if (
        target.get("targetPlacementBlocked") != "true"
        or target.get("pathBlocked") != "true"
        or integer(target, "native_result") == 0
        or number(target, "radius") <= 0
        or target.get("placement_mode") not in ("basic", "extended")
        or placement["probeCount"] < 1
        or placement["searchDistance"] < 0
        or placement["searchDistance"] > placement["searchBound"]
        or placement["basicResult"] != 0
        or placement["extendedResult"] != 0
        or abs(placement["radius"] - number(target, "radius")) > 0.05
        or abs(placement["anchorX"] - number(target, "x")) > 0.05
        or abs(placement["anchorY"] - number(target, "y")) > 0.05
        or abs(placement["resolvedX"] - row["landingX"]) > 0.05
        or abs(placement["resolvedY"] - row["landingY"]) > 0.05
    ):
        raise BotPolishFailure(
            f"Teleport did not use the bounded native placement search: "
            f"target={target} row={row} placement={placement}"
        )

    converged, convergence_utc = wait_for(
        lambda: {
            "host": bot_motion(HOST_PIPE, bot_id),
            "clientB": bot_motion(CLIENT_PIPE, bot_id),
        },
        lambda value: (
            math.hypot(
                number(value["host"], "x") - row["landingX"],
                number(value["host"], "y") - row["landingY"],
            )
            <= 1.5
            and math.hypot(
                number(value["clientB"], "x") - row["landingX"],
                number(value["clientB"], "y") - row["landingY"],
            )
            <= 3.0
            and abs(number(value["host"], "vector_x")) <= 0.001
            and abs(number(value["host"], "vector_y")) <= 0.001
        ),
        label="replicated landing and cleared stock walk vector",
        timeout=10,
        interval=0.1,
    )
    return {
        "target": target,
        "stageMove": stage_move,
        "stagedUtc": staged_utc,
        "staged": staged,
        "stageStop": stage_stop,
        "stoppedUtc": stopped_utc,
        "stopped": stopped,
        "stageRecovery": stage_recovery_rows,
        "wallProbe": wall_probe,
        "move": move,
        "observedUtc": observed_utc,
        "convergedUtc": convergence_utc,
        "stuckTeleportElapsedMs": row["windowMs"],
        "commandToTeleportElapsedMs": elapsed_ms,
        "stuckTeleportPlacementValidated": True,
        "teleport": row,
        "placement": placement,
        "positions": converged,
    }


def set_progression_speed(bot_id: int, speed: float) -> dict[str, str]:
    values = parse_key_values(
        lua(
            HOST_PIPE,
            f"""
local bot = sd.bots.get_participant_state({bot_id})
local progression =
  tonumber(bot and bot.progression_runtime_state_address) or 0
local offset = sd.debug.layout_offset("progression_move_speed")
print("progression=" .. tostring(progression))
print("before=" .. tostring(
  progression > 0 and offset and
  sd.debug.read_float(progression + offset) or 0))
print("write=" .. tostring(
  progression > 0 and offset and
  sd.debug.write_float(progression + offset, {speed:.9f}) or false))
print("after=" .. tostring(
  progression > 0 and offset and
  sd.debug.read_float(progression + offset) or 0))
""",
        )
    )
    if (
        integer(values, "progression") <= 0
        or values.get("write") != "true"
        or abs(number(values, "after") - speed) > 0.001
    ):
        raise BotPolishFailure(
            f"Could not configure the disposable slow bot: {values}"
        )
    return values


def verify_slow_reachable(bot_id: int) -> dict[str, Any]:
    time.sleep(10.5)
    target = choose_reachable_target(bot_id)
    speed = set_progression_speed(bot_id, 0.10)
    log_file = log_path(HOST_INSTANCE)
    log_offset = log_file.stat().st_size
    issue = issue_move(bot_id, target)
    start, start_utc = wait_for(
        lambda: bot_motion(HOST_PIPE, bot_id),
        lambda row: (
            row.get("has_target") == "true"
            and abs(number(row, "target_x") - number(target, "x")) <= 0.05
            and abs(number(row, "target_y") - number(target, "y")) <= 0.05
        ),
        label="active slow reachable move target",
        timeout=10,
        interval=0.1,
    )
    samples: list[dict[str, Any]] = []
    deadline = time.monotonic() + 32.0
    while time.monotonic() < deadline:
        sample = bot_motion(HOST_PIPE, bot_id)
        samples.append(
            {
                "elapsedMs": int(
                    (32.0 - max(0.0, deadline - time.monotonic()))
                    * 1000
                ),
                "x": number(sample, "x"),
                "y": number(sample, "y"),
                "distance": number(sample, "distance"),
                "hasTarget": sample.get("has_target") == "true",
            }
        )
        time.sleep(0.5)
    final = bot_motion(HOST_PIPE, bot_id)
    text = read_log_since(log_file, log_offset)
    teleports = stuck_rows(text, bot_id)
    displacement = math.hypot(
        number(final, "x") - number(start, "x"),
        number(final, "y") - number(start, "y"),
    )
    distance_progress = (
        number(start, "distance") - number(final, "distance")
    )
    if teleports:
        raise BotPolishFailure(
            f"Slow reachable movement triggered recovery: {teleports}"
        )
    if (
        displacement < 0.5
        or distance_progress < 0.5
        or final.get("has_target") != "true"
    ):
        raise BotPolishFailure(
            "The slow reachable trial did not remain an active, progressing "
            f"approach for the full window: start={start} final={final} "
            f"displacement={displacement} progress={distance_progress}"
        )
    return {
        "target": target,
        "speed": speed,
        "issue": issue,
        "startObservedUtc": start_utc,
        "durationMs": 32_000,
        "displacement": displacement,
        "distanceProgress": distance_progress,
        "slowReachableTeleportCount": len(teleports),
        "sampleCount": len(samples),
        "firstSample": samples[0],
        "lastSample": samples[-1],
    }


def verify_human_click_untouched(bot_id: int) -> dict[str, Any]:
    lua(HOST_PIPE, f"return tostring(sd.bots.stop({bot_id}))")
    time.sleep(0.5)
    log_file = log_path(HOST_INSTANCE)
    log_offset = log_file.stat().st_size
    before = parse_key_values(
        lua(
            HOST_PIPE,
            """
local player = sd.player.get_state()
print("x=" .. tostring(player and player.x or 0))
print("y=" .. tostring(player and player.y or 0))
""",
        )
    )
    injected = lua(
        HOST_PIPE,
        "return tostring(sd.input.hold_mouse_right_frames(1))",
    ).strip()
    time.sleep(1.0)
    cleared = lua(
        HOST_PIPE,
        "return tostring(sd.input.clear_mouse_right())",
    ).strip()
    time.sleep(4.0)
    after = parse_key_values(
        lua(
            HOST_PIPE,
            """
local player = sd.player.get_state()
print("x=" .. tostring(player and player.x or 0))
print("y=" .. tostring(player and player.y or 0))
""",
        )
    )
    text = read_log_since(log_file, log_offset)
    teleports = stuck_rows(text, bot_id)
    if injected != "true" or teleports:
        raise BotPolishFailure(
            f"Human click-to-move regression failed: injected={injected} "
            f"teleports={teleports}"
        )
    return {
        "inputAccepted": True,
        "clearResult": cleared,
        "before": before,
        "after": after,
        "humanClickTeleportCount": len(teleports),
    }


def copy_runtime_evidence() -> dict[str, str]:
    output = EVIDENCE_ROOT / "runtime-evidence"
    output.mkdir(parents=True, exist_ok=True)
    copied: dict[str, str] = {}
    for label, instance in (
        ("host", HOST_INSTANCE),
        ("client-b", CLIENT_INSTANCE),
    ):
        for relative, name in (
            (
                Path(".sdmod/logs/solomondarkmodloader.log"),
                f"{label}-loader.log",
            ),
            (
                Path(".sdmod/loader-startup-status.json"),
                f"{label}-startup-status.json",
            ),
            (
                Path(".sdmod/multiplayer-session-status.json"),
                f"{label}-session-status.json",
            ),
            (
                Path(f".sdmod/mod-settings/{EXACT_MOD_ID}.json"),
                f"{label}-settings.json",
            ),
            (
                Path(".sdmod/stage-report.json"),
                f"{label}-stage-report.json",
            ),
        ):
            source = stage_root(instance) / relative
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
    if ROOT.resolve() != Path("/mnt/c/sd-botpolish-20260727").resolve():
        raise BotPolishFailure(
            "This verifier is pinned to /mnt/c/sd-botpolish-20260727."
        )
    if not GAME_ROOT.is_dir():
        raise BotPolishFailure(f"Game directory is missing: {GAME_ROOT}")
    if not (
        ROOT / "dist/launcher/SolomonDarkModLauncher.exe"
    ).is_file():
        raise BotPolishFailure("Release launcher is missing.")
    udp_owners = query_udp_owners()
    if udp_owners and udp_owners not in ("null", "[]"):
        raise BotPolishFailure(
            f"Pinned UDP ports are already owned: {udp_owners}"
        )
    assert_no_existing_stage_processes()

    AFTER_ROOT.mkdir(parents=True, exist_ok=True)
    write_settings(HOST_INSTANCE, ROSTER)
    write_settings(CLIENT_INSTANCE, [])
    started_at = time.time()
    result: dict[str, Any] = {
        "contract": "bot-polish-v1.0.1",
        "success": False,
        "startedUtc": utc_now(),
        "instancePrefix": INSTANCE_PREFIX,
        "ports": {"host": HOST_PORT, "clientB": CLIENT_PORT},
        "exactModId": EXACT_MOD_ID,
        "audioDisabled": True,
        "productionTouched": False,
        "stagingOnly": True,
        "stuckTeleportElapsedMs": None,
        "stuckTeleportPlacementValidated": False,
        "slowReachableTeleportCount": None,
        "humanClickTeleportCount": None,
    }
    pair_process: subprocess.Popen[str] | None = None
    launch: dict[str, Any] | None = None
    failure: BaseException | None = None
    try:
        pair_process, pid_path = launch_pair(enable_audio=False)
        launch, launch_utc = wait_for(
            lambda: read_launch(pid_path),
            lambda value: (
                value.get("hostProcessId") is not None
                and value.get("clientProcessId") is not None
            ),
            label="both exact bot-polish process IDs",
            timeout=180,
            interval=0.2,
        )
        result["launch"] = {**launch, "observedUtc": launch_utc}
        for role in ("host", "client"):
            pid = int(launch[f"{role}ProcessId"])
            expected = str(launch[f"{role}ExecutablePath"])
            actual = process_path(pid)
            if actual is None or actual.casefold() != expected.casefold():
                raise BotPolishFailure(
                    f"{role} PID {pid} escaped its exact stage: "
                    f"expected={expected} actual={actual}"
                )

        lobby, lobby_utc = wait_for(
            lambda: {
                "hostProbe": bot_probe(HOST_PIPE),
                "clientBProbe": bot_probe(CLIENT_PIPE),
                "hostStatus": read_status(HOST_INSTANCE),
                "clientBStatus": read_status(CLIENT_INSTANCE),
            },
            lambda value: (
                valid_bot_probe(value["hostProbe"])
                and valid_bot_probe(value["clientBProbe"])
                and full_status(value["hostStatus"])
                and full_status(value["clientBStatus"])
            ),
            label=(
                "a replicated four-slot lobby with native bot cosmetics "
                "and Discipline books"
            ),
            timeout=timeout_seconds,
            interval=0.5,
        )
        result["fourSlotLobby"] = {
            "observedUtc": lobby_utc,
            "status": {
                "host": lobby["hostStatus"],
                "clientB": lobby["clientBStatus"],
            },
            "bots": assert_peer_visual_agreement(
                lobby["hostProbe"],
                lobby["clientBProbe"],
            ),
        }
        result["screenshots"] = {
            "host": capture_window(
                int(launch["hostProcessId"]),
                AFTER_ROOT / "host-four-slot-lobby.png",
            ),
            "clientB": capture_window(
                int(launch["clientProcessId"]),
                AFTER_ROOT / "client-b-four-slot-lobby.png",
            ),
        }

        reload_result = reload_roster([])
        if (
            reload_result.get("ok") != "true"
            or "roster"
            not in reload_result.get("changed", "").split(",")
        ):
            raise BotPolishFailure(
                f"Could not clear the bot-brain roster: {reload_result}"
            )
        _, empty_utc = wait_for(
            lambda: {
                "host": bot_probe(HOST_PIPE),
                "clientB": bot_probe(CLIENT_PIPE),
            },
            lambda value: (
                integer(value["host"], "count", -1) == 0
                and integer(value["clientB"], "count", -1) == 0
            ),
            label="empty bot-brain roster",
            timeout=20,
        )
        result["directHarness"] = {
            "rosterClearedUtc": empty_utc,
            "reload": reload_result,
        }
        bot_id, spawn = spawn_direct_bot()
        result["directHarness"]["spawn"] = spawn
        result["directHarness"]["botId"] = bot_id
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
            label="client B test run",
            timeout=45,
        )
        _, bot_run_utc = wait_for(
            lambda: {
                "host": bot_motion(HOST_PIPE, bot_id),
                "clientB": bot_motion(CLIENT_PIPE, bot_id),
            },
            lambda value: all(
                peer.get("materialized") == "true"
                for peer in value.values()
            ),
            label="direct bot materialized on both machines",
            timeout=45,
        )
        result["runObservedUtc"] = {
            "host": host_run_utc,
            "clientB": client_run_utc,
            "bot": bot_run_utc,
        }
        result["survivalGuard"] = {
            "host": arm_survival_guard(HOST_PIPE, bot_id),
            "clientB": arm_survival_guard(CLIENT_PIPE),
            "scope": "HP only; movement and waves unchanged",
        }

        stuck = verify_stuck_teleport(bot_id)
        result["stuckTeleport"] = stuck
        result["stuckTeleportElapsedMs"] = stuck[
            "stuckTeleportElapsedMs"
        ]
        result["stuckTeleportPlacementValidated"] = stuck[
            "stuckTeleportPlacementValidated"
        ]
        slow = verify_slow_reachable(bot_id)
        result["slowReachable"] = slow
        result["slowReachableTeleportCount"] = slow[
            "slowReachableTeleportCount"
        ]
        human = verify_human_click_untouched(bot_id)
        result["humanClickToMove"] = human
        result["humanClickTeleportCount"] = human[
            "humanClickTeleportCount"
        ]
        crashes = fresh_crash_artifacts(started_at)
        if crashes:
            raise BotPolishFailure(
                f"Fresh nonempty crash artifacts were produced: {crashes}"
            )
        result["freshNonemptyCrashArtifacts"] = crashes
        result["runtimeEvidence"] = copy_runtime_evidence()
        result["success"] = True
    except BaseException as error:
        failure = error
        result["failure"] = f"{type(error).__name__}: {error}"
        if launch is not None:
            try:
                result["runtimeEvidence"] = copy_runtime_evidence()
            except BaseException as copy_error:
                result["evidenceCopyFailure"] = (
                    f"{type(copy_error).__name__}: {copy_error}"
                )
    finally:
        if launch is not None:
            try:
                result["cleanup"] = stop_exact_game_processes(launch)
            except BaseException as cleanup_error:
                result["cleanupFailure"] = (
                    f"{type(cleanup_error).__name__}: {cleanup_error}"
                )
                if failure is None:
                    failure = cleanup_error
                    result["success"] = False
        if pair_process is not None:
            try:
                pair_process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                pair_process.terminate()
                pair_process.wait(timeout=5)
        result["finishedUtc"] = utc_now()
        atomic_write_json(AFTER_ROOT / "bot-polish-result.json", result)
    if failure is not None:
        raise failure
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=120.0,
        help="Lobby convergence timeout.",
    )
    args = parser.parse_args()
    try:
        result = verify(args.timeout_seconds)
    except BaseException as error:
        print(f"FAIL: {type(error).__name__}: {error}", flush=True)
        return 1
    print(
        json.dumps(
            {
                "success": result["success"],
                "result": str(AFTER_ROOT / "bot-polish-result.json"),
                "stuckTeleportElapsedMs":
                    result["stuckTeleportElapsedMs"],
                "slowReachableTeleportCount":
                    result["slowReachableTeleportCount"],
                "humanClickTeleportCount":
                    result["humanClickTeleportCount"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
