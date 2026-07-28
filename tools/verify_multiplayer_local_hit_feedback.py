#!/usr/bin/env python3
"""Verify event-owned native hit feedback for the local multiplayer player."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from owned_process_ledger import (
    OWNED_GAME_PROCESSES,
    OwnedProcessError,
    identities_from_launch,
    register_owned_launch,
    stop_owned_game_processes,
)


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = Path("/mnt/d/codex-evidence/hitfx-20260727")
FLOW_ROOT = EVIDENCE_ROOT / "acceptance"
RUNTIME_ROOT = ROOT / "runtime"
GAME_ROOT = Path(
    "/mnt/c/Users/User/Documents/GitHub/SB Modding/"
    "Solomon Dark/SolomonDarkAbandonware"
)

INSTANCE_PREFIX = "hitfx-acceptance-20260727"
HOST_INSTANCE = f"{INSTANCE_PREFIX}-host"
CLIENT_INSTANCE = f"{INSTANCE_PREFIX}-client"
HOST_PORT = 50111
CLIENT_PORT = 50112
HOST_ID_TEXT = "0x2000000000001001"
CLIENT_ID_TEXT = "0x2000000000001002"
HOST_ID = int(HOST_ID_TEXT, 16)
CLIENT_ID = int(CLIENT_ID_TEXT, 16)
HOST_NAME = "Host Player"
CLIENT_NAME = "client B"
HOST_PIPE = f"SolomonDarkModLoader_LuaExec_{HOST_INSTANCE}"
CLIENT_PIPE = f"SolomonDarkModLoader_LuaExec_{CLIENT_INSTANCE}"

FLAT_BONEYARD = ROOT / "tests/fixtures/boneyards/flat_multiplayer_test.boneyard"
ONE_SKELETON_WAVE = (
    ROOT / "tests/fixtures/waves/organic_death_melee_test.txt"
)
CLIENT_TARGET_X = 1850.0
CLIENT_TARGET_Y = 1750.0
HOST_PARK_X = 2350.0
HOST_PARK_Y = 1750.0
CLIENT_TEST_HP = 15.0
CLIENT_TEST_MAX_HP = 50.0
HEALED_HP = 35.0
ARRIVAL_GUARD_HP = 100000.0

FEEDBACK_MARKER = "[hit-feedback]"
AUDIO_MARKER = "[native-audio] event=play"
FIELD_PATTERN = re.compile(r'([a-z_]+)=("[^"]*"|\S+)')
HIT_REACTION_LOG_FIELDS = (
    "hit_primary_alpha",
    "hit_intensity",
    "hit_secondary_alpha",
    "hit_color_red",
    "hit_color_green",
    "hit_color_blue",
    "hit_color_alpha",
)


class VerificationFailure(RuntimeError):
    """Raised when the live hit-feedback contract is not satisfied."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def windows_path(path: Path) -> str:
    completed = subprocess.run(
        ["wslpath", "-w", str(path)],
        cwd=ROOT,
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


def parse_key_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.replace("\r", "").splitlines():
        line = raw_line.strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


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
    last_detail = ""
    for attempt in range(20):
        completed = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout + 8.0,
            check=False,
        )
        if completed.returncode == 0:
            return completed.stdout
        last_detail = (
            completed.stderr.strip()
            or completed.stdout.strip()
            or "Lua exec failed"
        )
        if "Lua engine is busy executing on another thread" not in last_detail:
            break
        if attempt < 19:
            time.sleep(0.1)
    raise VerificationFailure(
        f"Lua exec failed for {pipe_name}: {last_detail}"
    )


def values(pipe_name: str, code: str, timeout: float = 15.0) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, code, timeout))


def wait_for(
    operation: Callable[[], Any],
    predicate: Callable[[Any], bool],
    *,
    label: str,
    timeout: float,
    interval: float = 0.15,
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


def stage_root(instance: str) -> Path:
    return RUNTIME_ROOT / "instances" / instance / "stage"


def log_path(instance: str) -> Path:
    return stage_root(instance) / ".sdmod/logs/solomondarkmodloader.log"


def read_log(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def log_offset(path: Path) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def log_since(path: Path, offset: int) -> str:
    try:
        with path.open("rb") as stream:
            stream.seek(offset)
            return stream.read().decode("utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def parse_fields(line: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for key, value in FIELD_PATTERN.findall(line):
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        fields[key] = value
    return fields


def parse_hit_feedback_log(
    text: str,
    *,
    event: str | None = None,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        if FEEDBACK_MARKER not in line:
            continue
        fields = parse_fields(line)
        if event is not None and fields.get("event") != event:
            continue
        fields["_line"] = line
        rows.append(fields)
    return rows


def parse_ouch_audio_log(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        if AUDIO_MARKER not in line or "owner=player.hit" not in line:
            continue
        fields = parse_fields(line)
        fields["_line"] = line
        rows.append(fields)
    return rows


def feedback_key(row: dict[str, str]) -> tuple[int, int, int]:
    try:
        return (
            int(row["target_participant_id"], 10),
            int(row["run_nonce"], 10),
            int(row["event_sequence"], 10),
        )
    except (KeyError, ValueError) as exc:
        raise VerificationFailure(
            f"Malformed hit-feedback row: {row}"
        ) from exc


def assert_exactly_once(
    authority_text: str,
    owner_text: str,
    *,
    target_participant_id: int = CLIENT_ID,
) -> dict[str, Any]:
    captures = [
        row
        for row in parse_hit_feedback_log(
            authority_text,
            event="authority_capture",
        )
        if int(row.get("target_participant_id", "0"), 10)
        == target_participant_id
    ]
    replays = [
        row
        for row in parse_hit_feedback_log(owner_text, event="replay")
        if int(row.get("target_participant_id", "0"), 10)
        == target_participant_id
    ]
    if not captures:
        raise VerificationFailure(
            "The stock enemy never produced an authority hit event for "
            f"participant {target_participant_id}."
        )

    capture_counts = Counter(feedback_key(row) for row in captures)
    replay_counts = Counter(feedback_key(row) for row in replays)
    duplicate_captures = {
        key: count
        for key, count in capture_counts.items()
        if count != 1
    }
    duplicate_replays = {
        key: count
        for key, count in replay_counts.items()
        if count != 1
    }
    if duplicate_captures or duplicate_replays:
        raise VerificationFailure(
            "Hit feedback was not exactly once per event: "
            f"capture_counts={capture_counts} replay_counts={replay_counts}"
        )
    if set(capture_counts) != set(replay_counts):
        raise VerificationFailure(
            "Authority hit events and owner replays do not match: "
            f"captures={sorted(capture_counts)} "
            f"replays={sorted(replay_counts)}"
        )
    if any(row.get("actor_live") != "1" for row in replays):
        raise VerificationFailure(
            f"Owner replay ran without a live local actor: {replays}"
        )
    if any(
        row.get("actor_reaction_written") != "1"
        for row in replays
    ):
        raise VerificationFailure(
            "Owner replay did not write the native Actor hit reaction: "
            f"{replays}"
        )
    captures_by_key = {
        feedback_key(row): row
        for row in captures
    }
    replays_by_key = {
        feedback_key(row): row
        for row in replays
    }
    for key, capture in captures_by_key.items():
        replay = replays_by_key[key]
        for field in HIT_REACTION_LOG_FIELDS:
            try:
                authority_value = float(capture[field])
                owner_value = float(replay[field])
            except (KeyError, ValueError) as exc:
                raise VerificationFailure(
                    "Malformed Actor hit-reaction fields for "
                    f"event {key}: capture={capture} replay={replay}"
                ) from exc
            if (
                not math.isfinite(authority_value)
                or not math.isfinite(owner_value)
                or not math.isclose(
                    authority_value,
                    owner_value,
                    rel_tol=0.0,
                    abs_tol=1e-6,
                )
            ):
                raise VerificationFailure(
                    "Owner Actor hit reaction differs from authority "
                    f"for event {key} field={field}: "
                    f"authority={authority_value} owner={owner_value}"
                )
        if float(replay["hit_primary_alpha"]) <= 0.0:
            raise VerificationFailure(
                f"Owner Actor hit latch was not armed for event {key}."
            )
    if not any(row.get("red_written") == "1" for row in replays):
        raise VerificationFailure(
            f"No replicated hit wrote the stock red effect: {replays}"
        )

    requested_ouch_count = sum(
        row.get("ouch_requested") == "1" for row in replays
    )
    audio_rows = parse_ouch_audio_log(owner_text)
    if len(audio_rows) != requested_ouch_count:
        raise VerificationFailure(
            "Audio-disabled observer did not match native Ouch requests: "
            f"requested={requested_ouch_count} observed={audio_rows}"
        )

    return {
        "eventKeys": [list(key) for key in sorted(capture_counts)],
        "eventCount": len(capture_counts),
        "ouchRequestCount": requested_ouch_count,
        "ouchRows": audio_rows,
        "redReplayCount": sum(
            row.get("red_written") == "1" for row in replays
        ),
        "actorReactionReplayCount": sum(
            row.get("actor_reaction_written") == "1"
            for row in replays
        ),
        "captures": captures,
        "replays": replays,
    }


def _assert_phase_has_no_feedback(
    authority_text: str,
    owner_text: str,
    *,
    label: str,
) -> dict[str, Any]:
    captures = parse_hit_feedback_log(
        authority_text,
        event="authority_capture",
    )
    replays = parse_hit_feedback_log(owner_text, event="replay")
    audio = parse_ouch_audio_log(owner_text)
    if captures or replays or audio:
        raise VerificationFailure(
            f"{label} emitted hit feedback: captures={captures} "
            f"replays={replays} audio={audio}"
        )
    return {
        "authorityCaptureCount": 0,
        "ownerReplayCount": 0,
        "ownerOuchRequestCount": 0,
    }


def assert_no_feedback_on_heal(
    authority_text: str,
    owner_text: str,
) -> dict[str, Any]:
    return _assert_phase_has_no_feedback(
        authority_text,
        owner_text,
        label="healing",
    )


def assert_no_feedback_on_snapshot_reapply(
    authority_text: str,
    owner_text: str,
) -> dict[str, Any]:
    return _assert_phase_has_no_feedback(
        authority_text,
        owner_text,
        label="periodic vitals snapshot re-apply",
    )


def assert_no_feedback_for_other_participant(
    owner_text: str,
) -> dict[str, Any]:
    replays = parse_hit_feedback_log(owner_text, event="replay")
    audio = parse_ouch_audio_log(owner_text)
    if replays or audio:
        raise VerificationFailure(
            "Damage to the other participant leaked feedback to client B: "
            f"replays={replays} audio={audio}"
        )
    return {"ownerReplayCount": 0, "ownerOuchRequestCount": 0}


def assert_host_native_feedback_unchanged(
    host_text: str,
    *,
    red_value: float,
    actor_reaction_value: float,
    hp_before: float,
    hp_after: float,
) -> dict[str, Any]:
    framework_rows = parse_hit_feedback_log(host_text)
    audio = parse_ouch_audio_log(host_text)
    if framework_rows:
        raise VerificationFailure(
            "The framework replay path contributed to the host-local hit: "
            f"{framework_rows}"
        )
    if not math.isfinite(hp_before) or not math.isfinite(hp_after):
        raise VerificationFailure(
            f"Host-native hit returned invalid HP: {hp_before}->{hp_after}"
        )
    if hp_after >= hp_before:
        raise VerificationFailure(
            f"Host-native hit did not damage the host: {hp_before}->{hp_after}"
        )
    if not math.isfinite(red_value) or red_value <= 0.0:
        raise VerificationFailure(
            f"Host-native hit did not write the stock red field: {red_value}"
        )
    if (
        not math.isfinite(actor_reaction_value)
        or actor_reaction_value <= 0.0
    ):
        raise VerificationFailure(
            "Host-native hit did not arm the stock Actor reaction: "
            f"{actor_reaction_value}"
        )
    if len(audio) != 1:
        raise VerificationFailure(
            "Host-native hit did not make exactly one observed Ouch request: "
            f"{audio}"
        )
    return {
        "hpBefore": hp_before,
        "hpAfter": hp_after,
        "redValue": red_value,
        "actorReactionValue": actor_reaction_value,
        "nativeOuchRows": audio,
        "frameworkRowCount": 0,
    }


def assert_ports_are_free() -> str:
    script = (
        f"$rows=@(Get-NetUDPEndpoint -LocalPort "
        f"{HOST_PORT},{CLIENT_PORT} -ErrorAction SilentlyContinue);"
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
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if completed.returncode != 0:
        raise VerificationFailure(
            "Could not inspect pinned ports: "
            f"{completed.stderr.strip()}"
        )
    output = completed.stdout.replace("\r", "").strip()
    if output and output not in {"[]", "null"}:
        raise VerificationFailure(
            "Ports 50111/50112 are already owned; no process was touched: "
            f"{output}"
        )
    return output or "[]"


def assert_no_existing_stage_processes() -> None:
    expected = {
        windows_path(stage_root(HOST_INSTANCE) / "SolomonDark.exe").casefold(),
        windows_path(
            stage_root(CLIENT_INSTANCE) / "SolomonDark.exe"
        ).casefold(),
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
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise VerificationFailure(
            "Could not inspect acceptance-stage processes: "
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
            "Acceptance stages already have live processes; no process was "
            f"touched: {conflicts}"
        )


def acquire_live_launcher_identities(launch: dict[str, Any]) -> None:
    for identity in identities_from_launch(launch):
        try:
            OWNED_GAME_PROCESSES.acquire([identity])
        except OwnedProcessError as exc:
            if "exited before ownership acquisition" not in str(exc):
                raise


def reconcile_process_ledger(path: Path) -> None:
    if not path.is_file():
        return
    try:
        launch = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return
    if isinstance(launch, dict):
        acquire_live_launcher_identities(launch)


def read_pair_launch_result(path: Path) -> dict[str, Any] | None:
    try:
        lines = [
            line.strip()
            for line in path.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines()
            if line.strip()
        ]
    except OSError:
        return None
    for line in reversed(lines):
        try:
            result = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(result, dict)
            and isinstance(result.get("hostProcessId"), int)
            and isinstance(result.get("clientProcessId"), int)
            and result.get("hostExecutablePath")
            and result.get("clientExecutablePath")
        ):
            return result
    return None


def launch_pair(timeout: float) -> dict[str, Any]:
    FLOW_ROOT.mkdir(parents=True, exist_ok=True)
    pid_path = FLOW_ROOT / "pair-processes.json"
    pid_path.unlink(missing_ok=True)
    stdout_path = FLOW_ROOT / "pair-launch.stdout.log"
    stderr_path = FLOW_ROOT / "pair-launch.stderr.log"
    command = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        windows_path(ROOT / "scripts/Launch-LocalMultiplayerPair.ps1"),
        "-Preset",
        "map_create_fire_arcane_hub",
        "-HostPreset",
        "map_create_fire_arcane_hub",
        "-ClientPreset",
        "map_create_fire_arcane_hub",
        "-HostPort",
        str(HOST_PORT),
        "-ClientPort",
        str(CLIENT_PORT),
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
        "-ExactModIds",
        "sample.lua.ui_sandbox_lab",
        "-NoTileWindows",
        "-QuickStart",
        "-TestSurvivalBoneyardOverride",
        windows_path(FLAT_BONEYARD),
        "-TestBlankBoneyard",
        "-TestWaveOverride",
        windows_path(ONE_SKELETON_WAVE),
        "-ProcessIdOutputPath",
        windows_path(pid_path),
    ]
    environment = os.environ.copy()
    environment["SDMOD_DISABLE_AUDIO"] = "1"
    environment["SDMOD_ENABLE_AUDIO"] = "0"
    with stdout_path.open(
        "w",
        encoding="utf-8",
        newline="\n",
    ) as stdout, stderr_path.open(
        "w",
        encoding="utf-8",
        newline="\n",
    ) as stderr:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=environment,
            stdout=stdout,
            stderr=stderr,
            text=True,
        )

    deadline = time.monotonic() + timeout
    last_ledger = ""
    result: dict[str, Any] | None = None
    while process.poll() is None and time.monotonic() < deadline:
        if pid_path.is_file():
            try:
                raw = pid_path.read_text(encoding="utf-8-sig")
                launch = json.loads(raw)
            except (OSError, json.JSONDecodeError):
                launch = None
            if isinstance(launch, dict) and raw != last_ledger:
                acquire_live_launcher_identities(launch)
                last_ledger = raw
        result = read_pair_launch_result(stdout_path)
        if result is not None:
            break
        time.sleep(0.2)
    if result is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    elif process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        raise VerificationFailure(
            f"Pair launcher exceeded {timeout:.1f} seconds."
        )
    if pid_path.is_file():
        reconcile_process_ledger(pid_path)
    if result is None and process.returncode != 0:
        raise VerificationFailure(
            f"Pair launcher failed with exit code {process.returncode}: "
            f"{stderr_path.read_text(encoding='utf-8', errors='replace')}"
        )

    if result is None:
        result = read_pair_launch_result(stdout_path)
    if result is None:
        raise VerificationFailure("Pair launcher returned no result JSON.")
    register_owned_launch(result)
    if result.get("hostPort") != HOST_PORT or result.get(
        "clientPort"
    ) != CLIENT_PORT:
        raise VerificationFailure(f"Launcher drifted pinned ports: {result}")
    if result.get("clientName") != CLIENT_NAME:
        raise VerificationFailure(f"Launcher drifted client name: {result}")
    if result.get("audioDisabled") is not True:
        raise VerificationFailure(
            f"Pair was not launched with audio disabled: {result}"
        )
    atomic_write_json(FLOW_ROOT / "pair-launch.json", result)
    return result


def query_scene(pipe_name: str) -> dict[str, str]:
    return values(
        pipe_name,
        r"""
local scene = sd.world and sd.world.get_scene and sd.world.get_scene()
print("scene=" .. tostring(scene and (scene.name or scene.kind) or ""))
print("transitioning=" .. tostring(scene and scene.transitioning or false))
""",
    )


def wait_for_scene(pipe_name: str, scene_name: str) -> dict[str, str]:
    result, _ = wait_for(
        lambda: query_scene(pipe_name),
        lambda row: (
            row.get("scene") == scene_name
            and row.get("transitioning") != "true"
        ),
        label=f"{pipe_name} scene={scene_name}",
        timeout=45.0,
        interval=0.25,
    )
    return result


ARRIVAL_GUARD_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local function protect(actor, x, y, hp)
  actor = tonumber(actor) or 0
  if actor == 0 then return false end
  local progression_offset =
    sd.debug.layout_offset("actor_progression_runtime_state")
  local progression =
    tonumber(sd.debug.read_ptr(actor + progression_offset)) or 0
  if progression == 0 then return false end
  local ox = sd.debug.layout_offset("actor_position_x")
  local oy = sd.debug.layout_offset("actor_position_y")
  local hp_offset = sd.debug.layout_offset("progression_hp")
  local max_hp_offset = sd.debug.layout_offset("progression_max_hp")
  sd.debug.write_float(actor + ox, x)
  sd.debug.write_float(actor + oy, y)
  sd.debug.write_float(progression + max_hp_offset, hp)
  sd.debug.write_float(progression + hp_offset, hp)
  return true
end
local function guard()
  local state = _G.__sdmod_hitfx_arrival_guard
  if type(state) ~= "table" or not state.active then return false end
  sd.gameplay.set_manual_enemy_spawner_test_mode(true)
  local player = sd.player and sd.player.get_state and sd.player.get_state()
  local actor = tonumber(player and player.actor_address) or 0
  local local_protected = protect(actor, state.x, state.y, state.hp)
  if state.remote_participant_id ~= 0 then
    local remote = sd.bots and sd.bots.get_participant_state and
      sd.bots.get_participant_state(state.remote_participant_id)
    protect(
      remote and remote.actor_address or 0,
      state.remote_x,
      state.remote_y,
      state.hp)
  end
  return local_protected
end
_G.__sdmod_hitfx_arrival_guard = {
  active = true,
  x = __X__,
  y = __Y__,
  hp = __HP__,
  remote_participant_id = __REMOTE_PARTICIPANT_ID__,
  remote_x = __REMOTE_X__,
  remote_y = __REMOTE_Y__,
}
if not _G.__sdmod_hitfx_arrival_guard_registered then
  sd.events.on("runtime.tick", guard)
  _G.__sdmod_hitfx_arrival_guard_registered = true
end
emit("registered", _G.__sdmod_hitfx_arrival_guard_registered)
emit("active", _G.__sdmod_hitfx_arrival_guard.active)
emit("applied", guard())
"""


def arm_arrival_guard(
    pipe_name: str,
    x: float,
    y: float,
    *,
    remote_participant_id: int = 0,
    remote_x: float = 0.0,
    remote_y: float = 0.0,
) -> dict[str, str]:
    result = values(
        pipe_name,
        ARRIVAL_GUARD_LUA.replace("__X__", f"{x:.6f}")
        .replace("__Y__", f"{y:.6f}")
        .replace("__HP__", f"{ARRIVAL_GUARD_HP:.6f}")
        .replace(
            "__REMOTE_PARTICIPANT_ID__",
            str(remote_participant_id),
        )
        .replace("__REMOTE_X__", f"{remote_x:.6f}")
        .replace("__REMOTE_Y__", f"{remote_y:.6f}"),
    )
    if (
        result.get("registered") != "true"
        or result.get("active") != "true"
    ):
        raise VerificationFailure(
            f"Could not arm testrun arrival guard on {pipe_name}: {result}"
        )
    return result


def release_arrival_guard(pipe_name: str) -> dict[str, str]:
    result = values(
        pipe_name,
        """
local state = _G.__sdmod_hitfx_arrival_guard
if type(state) == "table" then state.active = false end
print("active=" .. tostring(state and state.active or false))
""",
    )
    if result.get("active") != "false":
        raise VerificationFailure(
            f"Could not release testrun arrival guard on {pipe_name}: "
            f"{result}"
        )
    return result


def start_testrun() -> dict[str, Any]:
    requested = values(
        HOST_PIPE,
        'print("ok=" .. tostring(sd.hub.start_testrun()))',
    )
    if requested.get("ok") != "true":
        raise VerificationFailure(
            f"Host could not start the acceptance testrun: {requested}"
        )
    return {
        "requested": requested,
        "host": wait_for_scene(HOST_PIPE, "testrun"),
        "client": wait_for_scene(CLIENT_PIPE, "testrun"),
    }


HOLD_PLAYER_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local x = __X__
local y = __Y__
local function hold()
  local player = sd.player and sd.player.get_state and sd.player.get_state()
  local actor = tonumber(player and player.actor_address) or 0
  local ox = sd.debug.layout_offset("actor_position_x")
  local oy = sd.debug.layout_offset("actor_position_y")
  if actor == 0 or ox == nil or oy == nil then return false end
  sd.debug.write_float(actor + ox, x)
  sd.debug.write_float(actor + oy, y)
  return true
end
_G.__sdmod_hitfx_hold = {x=x, y=y}
if not _G.__sdmod_hitfx_hold_registered then
  sd.events.on("runtime.tick", hold)
  _G.__sdmod_hitfx_hold_registered = true
end
emit("registered", _G.__sdmod_hitfx_hold_registered)
emit("applied", hold())
"""


def hold_player(pipe_name: str, x: float, y: float) -> dict[str, str]:
    result = values(
        pipe_name,
        HOLD_PLAYER_LUA.replace("__X__", f"{x:.6f}").replace(
            "__Y__",
            f"{y:.6f}",
        ),
    )
    if result.get("registered") != "true" or result.get("applied") != "true":
        raise VerificationFailure(
            f"Could not hold player position on {pipe_name}: {result}"
        )
    return result


SET_VITALS_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local player = sd.player and sd.player.get_state and sd.player.get_state()
local actor = tonumber(player and player.actor_address) or 0
local progression = tonumber(player and player.progression_address) or 0
if progression == 0 and actor ~= 0 then
  local offset = sd.debug.layout_offset("actor_progression_runtime_state")
  progression = tonumber(sd.debug.read_ptr(actor + offset)) or 0
end
if progression == 0 then emit("ok", false); return end
local hp_offset = sd.debug.layout_offset("progression_hp")
local max_hp_offset = sd.debug.layout_offset("progression_max_hp")
emit("before_hp", sd.debug.read_float(progression + hp_offset))
emit("before_max_hp", sd.debug.read_float(progression + max_hp_offset))
local wrote_max = sd.debug.write_float(
  progression + max_hp_offset, __MAX_HP__)
local wrote_hp = sd.debug.write_float(progression + hp_offset, __HP__)
local after = sd.player.get_state()
emit("wrote_max", wrote_max)
emit("wrote_hp", wrote_hp)
emit("after_hp", after and after.hp or -1)
emit("after_max_hp", after and after.max_hp or -1)
emit("ok", wrote_max and wrote_hp)
"""


def set_local_vitals(
    pipe_name: str,
    hp: float,
    maximum: float,
) -> dict[str, str]:
    result = values(
        pipe_name,
        SET_VITALS_LUA.replace("__HP__", f"{hp:.6f}").replace(
            "__MAX_HP__",
            f"{maximum:.6f}",
        ),
    )
    if result.get("ok") != "true":
        raise VerificationFailure(
            f"Could not set local vitals on {pipe_name}: {result}"
        )
    return result


def query_remote_client() -> dict[str, str]:
    return values(
        HOST_PIPE,
        f"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local state = sd.bots.get_participant_state({CLIENT_ID})
emit("available", state ~= nil and state.available == true)
emit("materialized", state ~= nil and state.entity_materialized == true)
emit("actor", state and state.actor_address or 0)
emit("x", state and state.x or 0)
emit("y", state and state.y or 0)
emit("hp", state and state.hp or 0)
emit("max_hp", state and state.max_hp or 0)
""",
    )


def wait_for_remote_client_hp(expected: float) -> dict[str, str]:
    result, _ = wait_for(
        query_remote_client,
        lambda row: (
            row.get("available") == "true"
            and row.get("materialized") == "true"
            and expected - 0.25
            <= float(row.get("hp", "nan"))
            <= expected + 2.5
        ),
        label=(
            "host authority clone low-HP sync "
            f"[{expected - 0.25:.3f}, {expected + 2.5:.3f}]"
        ),
        timeout=15.0,
    )
    return result


ARM_ENEMY_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
_G.__sdmod_hitfx_enemy = _G.__sdmod_hitfx_enemy or {
  mode = "park",
  target_x = __TARGET_X__,
  target_y = __TARGET_Y__,
  actor_address = __ACTOR_ADDRESS__,
  target_actor = 0,
}
local function drive(arena, rebind)
  local ox = sd.debug.layout_offset("actor_position_x")
  local oy = sd.debug.layout_offset("actor_position_y")
  local ot = sd.debug.layout_offset("actor_current_target_actor")
  local ob = sd.debug.layout_offset("actor_current_target_bucket_delta")
  local bucket_stride = sd.debug.layout_offset("actor_world_bucket_stride")
  local oas = sd.debug.layout_offset("actor_slot")
  local ows = sd.debug.layout_offset("actor_world_slot")
  local os = sd.debug.layout_offset("actor_animation_selection_state")
  local ots = sd.debug.layout_offset("actor_control_brain_target_slot")
  local oth = sd.debug.layout_offset("actor_control_brain_target_handle")
  local ort = sd.debug.layout_offset("actor_control_brain_retarget_ticks")
  local otc = sd.debug.layout_offset(
    "actor_control_brain_target_cooldown_ticks")
  local oac = sd.debug.layout_offset(
    "actor_control_brain_action_cooldown_ticks")
  local actors = sd.world and sd.world.list_actors and
    sd.world.list_actors() or {}
  local selected = nil
  for _, actor in ipairs(actors) do
    local address = tonumber(actor.actor_address) or 0
    local hp = tonumber(actor.hp) or 0
    if address ~= 0 and actor.tracked_enemy and not actor.dead and hp > 0 then
      if arena.actor_address == 0 or address == arena.actor_address then
        selected = actor
        arena.actor_address = address
        break
      end
    end
  end
  if selected == nil then arena.actor_address = 0; return false end
  local address = arena.actor_address
  local attacking = arena.mode == "attack" and arena.target_actor ~= 0
  local x = attacking and arena.target_x + 96.0 or 7000.0
  local y = attacking and arena.target_y or 7000.0
  if not attacking or rebind then
    if ox ~= nil then sd.debug.write_float(address + ox, x) end
    if oy ~= nil then sd.debug.write_float(address + oy, y) end
  end
  local target_slot = attacking and oas ~= nil and
    (tonumber(sd.debug.read_i8(arena.target_actor + oas)) or -1) or -1
  local target_handle = attacking and ows ~= nil and
    (tonumber(sd.debug.read_i16(arena.target_actor + ows)) or -1) or -1
  if ot ~= nil then
    sd.debug.write_ptr(address + ot, attacking and arena.target_actor or 0)
  end
  if ob ~= nil then
    local hostile_slot = oas ~= nil and
      (tonumber(sd.debug.read_i8(address + oas)) or -1) or -1
    local bucket_delta = 0
    if attacking and bucket_stride ~= nil and hostile_slot >= 0 and
        target_slot >= 0 and target_handle >= 0 then
      bucket_delta = target_slot * bucket_stride + target_handle -
        hostile_slot * bucket_stride
    end
    sd.debug.write_i32(address + ob, bucket_delta)
  end
  if attacking and os ~= nil then
    local brain = tonumber(sd.debug.read_ptr(address + os)) or 0
    if brain ~= 0 then
      if ots ~= nil then sd.debug.write_u8(brain + ots, target_slot) end
      if oth ~= nil then sd.debug.write_u16(brain + oth, target_handle) end
      if rebind then
        if ort ~= nil then sd.debug.write_u32(brain + ort, 0) end
        if otc ~= nil then sd.debug.write_u32(brain + otc, 0) end
        if oac ~= nil then sd.debug.write_u32(brain + oac, 0) end
      end
    end
  end
  if rebind and sd.world and sd.world.rebind_actor then
    sd.world.rebind_actor(address)
  end
  return true
end
_G.__sdmod_hitfx_enemy_drive = drive
if not _G.__sdmod_hitfx_enemy_registered then
  sd.events.on("runtime.tick", function()
    local arena = _G.__sdmod_hitfx_enemy
    if type(arena) == "table" then drive(arena, false) end
  end)
  _G.__sdmod_hitfx_enemy_registered = true
end
emit("ok", drive(_G.__sdmod_hitfx_enemy, true))
emit("actor", _G.__sdmod_hitfx_enemy.actor_address)
emit("mode", _G.__sdmod_hitfx_enemy.mode)
"""


SET_ENEMY_MODE_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local arena = _G.__sdmod_hitfx_enemy
if type(arena) ~= "table" then emit("ok", false); return end
arena.mode = "__MODE__"
arena.target_x = __TARGET_X__
arena.target_y = __TARGET_Y__
local target = sd.bots.get_participant_state(__TARGET_PARTICIPANT_ID__)
arena.target_actor = tonumber(target and target.actor_address) or 0
local thawed = true
if arena.mode == "attack" then
  thawed = sd.gameplay.clear_manual_run_enemy_freeze(
    arena.actor_address)
end
local ok = type(_G.__sdmod_hitfx_enemy_drive) == "function" and
  _G.__sdmod_hitfx_enemy_drive(arena, true)
emit("ok", ok)
emit("thawed", thawed)
emit("actor", arena.actor_address)
emit("target_actor", arena.target_actor)
emit("mode", arena.mode)
"""


def start_one_skeleton_wave() -> dict[str, Any]:
    state_code = """
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local state = sd.gameplay.get_manual_enemy_spawner_state()
emit("manual_mode", state and state.manual_mode or false)
emit("has_spawner", state and state.has_spawner or false)
emit("spawner_address", state and state.spawner_address or 0)
"""
    manual: dict[str, dict[str, str]] = {}
    for label, pipe_name in (("host", HOST_PIPE), ("client", CLIENT_PIPE)):
        manual[label], _ = wait_for(
            lambda pipe_name=pipe_name: values(pipe_name, state_code),
            lambda row: (
                row.get("manual_mode") == "true"
                and row.get("has_spawner") == "true"
            ),
            label=f"{label} suppressed native wave spawner",
            timeout=15.0,
        )
    count_code = """
local count = 0
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  if actor.tracked_enemy and not actor.dead and
      (tonumber(actor.hp) or 0) > 0.05 then
    count = count + 1
  end
end
print("count=" .. tostring(count))
"""
    suppressed_enemy_counts = {
        "host": values(HOST_PIPE, count_code),
        "client": values(CLIENT_PIPE, count_code),
    }
    if any(
        int(row.get("count", "-1"), 10) != 0
        for row in suppressed_enemy_counts.values()
    ):
        raise VerificationFailure(
            "Pre-run wave suppression leaked a stock enemy before "
            f"participant convergence: {suppressed_enemy_counts}"
        )

    spawn = values(
        HOST_PIPE,
        """
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local ok, err, request_id = sd.gameplay.spawn_manual_run_enemy({
  type_id = 1001,
  x = 7000.0,
  y = 7000.0,
  freeze_on_spawn = true
})
emit("ok", ok)
emit("error", err or "")
emit("request_id", request_id or 0)
""",
    )
    request_id = int(spawn.get("request_id", "0"), 10)
    if spawn.get("ok") != "true" or request_id == 0:
        raise VerificationFailure(
            f"Could not queue one native skeleton: {spawn}"
        )
    spawn_result_code = f"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local result = sd.gameplay.get_last_manual_run_enemy_spawn({request_id})
emit("present", result ~= nil)
if result == nil then return end
emit("ok", result.ok or false)
emit("request_id", result.request_id or 0)
emit("type_id", result.type_id or 0)
emit("actor_address", result.actor_address or 0)
emit("network_actor_id", string.format("%.0f",
  tonumber(result.network_actor_id) or 0))
emit("error", result.error or "")
"""
    spawn_result, _ = wait_for(
        lambda: values(HOST_PIPE, spawn_result_code),
        lambda row: (
            row.get("present") == "true"
            and row.get("ok") == "true"
            and int(row.get("actor_address", "0"), 10) != 0
        ),
        label="one frozen native skeleton",
        timeout=15.0,
    )
    actor_address = int(spawn_result["actor_address"], 10)
    arm_code = ARM_ENEMY_LUA.replace(
        "__TARGET_X__",
        f"{CLIENT_TARGET_X:.6f}",
    ).replace(
        "__TARGET_Y__",
        f"{CLIENT_TARGET_Y:.6f}",
    ).replace("__ACTOR_ADDRESS__", str(actor_address))
    armed, observed = wait_for(
        lambda: values(HOST_PIPE, arm_code),
        lambda row: row.get("ok") == "true"
        and int(row.get("actor", "0"), 10) != 0,
        label="one live stock skeleton",
        timeout=20.0,
    )
    return {
        "manualSpawner": manual,
        "suppressedEnemyCounts": suppressed_enemy_counts,
        "spawn": spawn,
        "spawnResult": spawn_result,
        "armed": armed,
        "observedUtc": observed,
    }


def set_manual_spawner_mode(
    pipe_name: str,
    enabled: bool,
) -> dict[str, str]:
    result = values(
        pipe_name,
        f"""
local ok, active = sd.gameplay.set_manual_enemy_spawner_test_mode(
  {"true" if enabled else "false"})
print("ok=" .. tostring(ok))
print("active=" .. tostring(active))
""",
    )
    expected = "true" if enabled else "false"
    if result.get("ok") != "true" or result.get("active") != expected:
        raise VerificationFailure(
            f"Could not set manual spawner mode={expected} on "
            f"{pipe_name}: {result}"
        )
    return result


def set_enemy_mode(mode: str) -> dict[str, str]:
    if mode not in {"park", "attack"}:
        raise ValueError(f"Unsupported enemy mode: {mode}")
    code = (
        SET_ENEMY_MODE_LUA.replace("__MODE__", mode)
        .replace("__TARGET_X__", f"{CLIENT_TARGET_X:.6f}")
        .replace("__TARGET_Y__", f"{CLIENT_TARGET_Y:.6f}")
        .replace("__TARGET_PARTICIPANT_ID__", str(CLIENT_ID))
    )
    result = values(HOST_PIPE, code)
    if (
        result.get("ok") != "true"
        or result.get("thawed") != "true"
        or int(result.get("actor", "0"), 10) == 0
        or (
            mode == "attack"
            and int(result.get("target_actor", "0"), 10) == 0
        )
    ):
        raise VerificationFailure(
            f"Could not set stock skeleton mode={mode}: {result}"
        )
    return result


def convert_backbuffer_capture(
    raw_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    with Image.open(raw_path) as raw:
        image = raw.convert("RGB")
        colors = image.getcolors(
            maxcolors=image.width * image.height
        )
        unique_colors = (
            len(colors)
            if colors is not None
            else image.width * image.height
        )
        dominant_fraction = (
            max(count for count, _ in colors)
            / float(image.width * image.height)
            if colors
            else 0.0
        )
        if unique_colors < 1000 or dominant_fraction >= 0.85:
            raise VerificationFailure(
                "D3D9 backbuffer capture was blank or low-information: "
                f"unique_colors={unique_colors} "
                f"dominant_fraction={dominant_fraction:.4f}"
            )
        image.save(output_path)
        width = image.width
        height = image.height

    raw_size = raw_path.stat().st_size
    raw_path.unlink()
    return {
        "path": str(output_path),
        "captureMethod": "d3d9_backbuffer",
        "width": width,
        "height": height,
        "uniqueColors": unique_colors,
        "dominantFraction": dominant_fraction,
        "rawBmpBytes": raw_size,
        "pngBytes": output_path.stat().st_size,
    }


def capture_game_backbuffer(
    pipe_name: str,
    output_path: Path,
) -> dict[str, Any]:
    raw_path = output_path.with_name(
        f"{output_path.stem}-backbuffer.bmp"
    )
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.unlink(missing_ok=True)
    output_path.unlink(missing_ok=True)
    capture = values(
        pipe_name,
        f"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local ok, err = sd.debug.capture_backbuffer(
  {json.dumps(windows_path(raw_path))})
emit("ok", ok)
emit("error", err or "")
""",
        timeout=20.0,
    )
    if capture.get("ok") != "true" or not raw_path.is_file():
        raise VerificationFailure(
            "Could not capture the D3D9 backbuffer: "
            f"{capture} path={raw_path}"
        )
    return convert_backbuffer_capture(raw_path, output_path)


def probe_hit_feedback_arena_identity(
    pipe_name: str,
) -> dict[str, str]:
    result = values(
        pipe_name,
        r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local player = sd.player and sd.player.get_state and
  sd.player.get_state() or nil
local world = sd.world and sd.world.get_state and
  sd.world.get_state() or nil
local actor = tonumber(player and player.actor_address) or 0
local owner_offset = sd.debug.layout_offset("actor_owner")
local hit_primary_offset = sd.debug.layout_offset(
  "actor_hit_reaction_primary_alpha")
local hit_intensity_offset = sd.debug.layout_offset(
  "actor_hit_reaction_intensity")
local hit_secondary_offset = sd.debug.layout_offset(
  "actor_hit_reaction_secondary_alpha")
local alpha_offset = sd.debug.layout_offset(
  "arena_hit_feedback_alpha")
local actor_owner = actor ~= 0 and owner_offset ~= nil and
  (tonumber(sd.debug.read_ptr(actor + owner_offset)) or 0) or 0
local render_arena = tonumber(world and world.arena_address) or 0
emit("actor", actor)
emit("actor_owner", actor_owner)
emit("render_arena", render_arena)
emit("same_arena", actor_owner ~= 0 and actor_owner == render_arena)
emit("actor_hit_primary_alpha",
  actor ~= 0 and hit_primary_offset ~= nil and
    sd.debug.read_float(actor + hit_primary_offset) or 0)
emit("actor_hit_intensity",
  actor ~= 0 and hit_intensity_offset ~= nil and
    sd.debug.read_float(actor + hit_intensity_offset) or 0)
emit("actor_hit_secondary_alpha",
  actor ~= 0 and hit_secondary_offset ~= nil and
    sd.debug.read_float(actor + hit_secondary_offset) or 0)
emit("actor_owner_alpha",
  actor_owner ~= 0 and alpha_offset ~= nil and
    sd.debug.read_float(actor_owner + alpha_offset) or 0)
emit("render_arena_alpha",
  render_arena ~= 0 and alpha_offset ~= nil and
    sd.debug.read_float(render_arena + alpha_offset) or 0)
""",
    )
    if (
        int(result.get("actor", "0"), 10) == 0
        or int(result.get("actor_owner", "0"), 10) == 0
        or int(result.get("render_arena", "0"), 10) == 0
    ):
        raise VerificationFailure(
            f"Could not resolve hit-feedback Arena identities: {result}"
        )
    return result


def arm_red_frame_capture(
    pipe_name: str,
    output_path: Path,
    *,
    minimum_alpha: float,
) -> dict[str, str]:
    raw_path = output_path.with_name(
        f"{output_path.stem}-backbuffer.bmp"
    )
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.unlink(missing_ok=True)
    output_path.unlink(missing_ok=True)
    result = values(
        pipe_name,
        f"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
_G.__sdmod_hitfx_frame_capture = {{
  armed = true,
  positive_ticks = 0,
  maximum_alpha = 0.0,
  maximum_actor_alpha = 0.0,
  start_frame_count = -1,
  captured_frame_count = -1,
  minimum_alpha = {minimum_alpha:.6f},
  path = {json.dumps(windows_path(raw_path))},
  completed = false,
  success = false,
  error = "",
  captured_alpha = 0.0,
  captured_actor_alpha = 0.0,
}}
if not _G.__sdmod_hitfx_frame_capture_registered then
  sd.events.on("runtime.tick", function()
    local capture = _G.__sdmod_hitfx_frame_capture
    if type(capture) ~= "table" or not capture.armed then return end
    local player = sd.player and sd.player.get_state and
      sd.player.get_state() or nil
    local actor = tonumber(player and player.actor_address) or 0
    local owner_offset = sd.debug.layout_offset("actor_owner")
    local actor_alpha_offset = sd.debug.layout_offset(
      "actor_hit_reaction_primary_alpha")
    local alpha_offset = sd.debug.layout_offset(
      "arena_hit_feedback_alpha")
    local arena = actor ~= 0 and owner_offset ~= nil and
      (tonumber(sd.debug.read_ptr(actor + owner_offset)) or 0) or 0
    local alpha = arena ~= 0 and alpha_offset ~= nil and
      tonumber(sd.debug.read_float(arena + alpha_offset)) or 0.0
    local actor_alpha = actor ~= 0 and actor_alpha_offset ~= nil and
      tonumber(sd.debug.read_float(actor + actor_alpha_offset)) or 0.0
    local frame = sd.runtime and sd.runtime.get_frame_state and
      sd.runtime.get_frame_state() or nil
    local frame_count = tonumber(frame and frame.frame_count) or 0
    if alpha >= capture.minimum_alpha and actor_alpha > 0.0 then
      capture.positive_ticks = capture.positive_ticks + 1
      if capture.start_frame_count < 0 then
        capture.start_frame_count = frame_count
      end
    end
    if alpha > capture.maximum_alpha then
      capture.maximum_alpha = alpha
    end
    if actor_alpha > capture.maximum_actor_alpha then
      capture.maximum_actor_alpha = actor_alpha
    end
    if capture.start_frame_count < 0 or
       frame_count < capture.start_frame_count + 2 then return end
    local ok, err = sd.debug.capture_backbuffer(capture.path)
    capture.armed = false
    capture.completed = true
    capture.success = ok == true
    capture.error = err or ""
    capture.captured_alpha = alpha
    capture.captured_actor_alpha = actor_alpha
    capture.captured_frame_count = frame_count
  end)
  _G.__sdmod_hitfx_frame_capture_registered = true
end
emit("registered", _G.__sdmod_hitfx_frame_capture_registered)
emit("armed", _G.__sdmod_hitfx_frame_capture.armed)
emit("raw_path", _G.__sdmod_hitfx_frame_capture.path)
""",
    )
    if (
        result.get("registered") != "true"
        or result.get("armed") != "true"
    ):
        raise VerificationFailure(
            f"Could not arm stock red-frame capture: {result}"
        )
    return result


def finish_red_frame_capture(
    pipe_name: str,
    output_path: Path,
    *,
    timeout: float = 20.0,
) -> dict[str, Any]:
    raw_path = output_path.with_name(
        f"{output_path.stem}-backbuffer.bmp"
    )
    state, observed = wait_for(
        lambda: values(
            pipe_name,
            r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local capture = _G.__sdmod_hitfx_frame_capture
emit("available", type(capture) == "table")
emit("completed", capture and capture.completed or false)
emit("success", capture and capture.success or false)
emit("error", capture and capture.error or "")
emit("positive_ticks", capture and capture.positive_ticks or 0)
emit("maximum_alpha", capture and capture.maximum_alpha or 0)
emit("maximum_actor_alpha",
  capture and capture.maximum_actor_alpha or 0)
emit("captured_alpha", capture and capture.captured_alpha or 0)
emit("captured_actor_alpha",
  capture and capture.captured_actor_alpha or 0)
emit("start_frame_count", capture and capture.start_frame_count or -1)
emit("captured_frame_count",
  capture and capture.captured_frame_count or -1)
""",
        ),
        lambda row: row.get("completed") == "true",
        label=f"rendered stock red frame on {pipe_name}",
        timeout=timeout,
        interval=0.02,
    )
    if state.get("success") != "true" or not raw_path.is_file():
        raise VerificationFailure(
            "In-process D3D9 red-frame capture failed: "
            f"{state} path={raw_path}"
        )
    if float(state["captured_actor_alpha"]) <= 0.0:
        raise VerificationFailure(
            "Captured red frame had no native Actor hit latch: "
            f"{state}"
        )
    return {
        **convert_backbuffer_capture(raw_path, output_path),
        "capturedAlpha": float(state["captured_alpha"]),
        "maximumAlpha": float(state["maximum_alpha"]),
        "capturedActorAlpha": float(
            state["captured_actor_alpha"]
        ),
        "maximumActorAlpha": float(
            state["maximum_actor_alpha"]
        ),
        "positiveTicks": int(state["positive_ticks"], 10),
        "startFrameCount": int(state["start_frame_count"], 10),
        "capturedFrameCount": int(
            state["captured_frame_count"],
            10,
        ),
        "observedUtc": observed,
    }


def capture_red_feedback_frame(
    client_log_path: Path,
    client_log_offset: int,
    output_path: Path,
    *,
    timeout: float = 20.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    replay_line = ""
    while time.monotonic() < deadline:
        for row in parse_hit_feedback_log(
            log_since(client_log_path, client_log_offset),
            event="replay",
        ):
            if (
                row.get("target_participant_id") == str(CLIENT_ID)
                and row.get("red_written") == "1"
            ):
                replay_line = row["_line"]
                break
        if replay_line:
            break
        time.sleep(0.02)
    if not replay_line:
        raise VerificationFailure(
            "Timed out waiting for client B's stock red effect write."
        )

    enemy_parked = set_enemy_mode("park")
    capture = finish_red_frame_capture(CLIENT_PIPE, output_path)
    return {
        **capture,
        "replayLine": replay_line,
        "enemyParked": enemy_parked,
    }


def wait_for_feedback_stable(
    host_path: Path,
    client_path: Path,
    host_offset: int,
    client_offset: int,
) -> tuple[str, str]:
    deadline = time.monotonic() + 10.0
    stable_since: float | None = None
    last_counts = (-1, -1)
    last_text = ("", "")
    while time.monotonic() < deadline:
        host_text = log_since(host_path, host_offset)
        client_text = log_since(client_path, client_offset)
        counts = (
            len(
                parse_hit_feedback_log(
                    host_text,
                    event="authority_capture",
                )
            ),
            len(parse_hit_feedback_log(client_text, event="replay")),
        )
        if counts[0] > 0 and counts[0] == counts[1]:
            if counts != last_counts:
                stable_since = time.monotonic()
            elif stable_since is not None and (
                time.monotonic() - stable_since >= 1.0
            ):
                return host_text, client_text
        else:
            stable_since = None
        last_counts = counts
        last_text = (host_text, client_text)
        time.sleep(0.1)
    raise VerificationFailure(
        "Authority captures and owner replays did not settle: "
        f"host={parse_hit_feedback_log(last_text[0])} "
        f"client={parse_hit_feedback_log(last_text[1])}"
    )


def queue_native_magic_hit(
    pipe_name: str,
    *,
    target_participant_id: int,
    damage: float,
) -> dict[str, Any]:
    queued = values(
        pipe_name,
        f"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local ok, err, serial = sd.debug.queue_native_magic_hit_behavior_probe(
  0.0, {damage:.6f}, 1, {target_participant_id}, 0.0)
emit("ok", ok)
emit("error", err or "")
emit("serial", serial or 0)
""",
    )
    try:
        serial = int(queued.get("serial", "0"), 10)
    except ValueError:
        serial = 0
    if queued.get("ok") != "true" or serial == 0:
        raise VerificationFailure(
            f"Could not queue host-native damage probe: {queued}"
        )

    result, observed = wait_for(
        lambda: values(
            pipe_name,
            f"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local completed, success, before, after, err =
  sd.debug.get_native_magic_hit_behavior_probe_result({serial})
emit("completed", completed)
emit("success", success)
emit("before", before)
emit("after", after)
emit("error", err or "")
""",
        ),
        lambda row: row.get("completed") == "true",
        label=f"native magic-hit probe serial={serial}",
        timeout=10.0,
        interval=0.02,
    )
    if result.get("success") != "true":
        raise VerificationFailure(
            f"Host-native damage probe failed: {queued=} {result=}"
        )
    return {
        "serial": serial,
        "queued": queued,
        "result": result,
        "observedUtc": observed,
        "hpBefore": float(result["before"]),
        "hpAfter": float(result["after"]),
    }


def arm_red_field_observer(pipe_name: str) -> dict[str, str]:
    result = values(
        pipe_name,
        r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
_G.__sdmod_hitfx_red_observer = {
  maximum = 0.0,
  current = 0.0,
  actor_maximum = 0.0,
  actor_current = 0.0,
  samples = 0,
}
if not _G.__sdmod_hitfx_red_observer_registered then
  sd.events.on("runtime.tick", function()
    local observer = _G.__sdmod_hitfx_red_observer
    if type(observer) ~= "table" then return end
    local player = sd.player and sd.player.get_state and
      sd.player.get_state() or nil
    local actor = tonumber(player and player.actor_address) or 0
    local owner_offset = sd.debug.layout_offset("actor_owner")
    local actor_alpha_offset = sd.debug.layout_offset(
      "actor_hit_reaction_primary_alpha")
    local alpha_offset = sd.debug.layout_offset(
      "arena_hit_feedback_alpha")
    local arena = actor ~= 0 and owner_offset ~= nil and
      (tonumber(sd.debug.read_ptr(actor + owner_offset)) or 0) or 0
    local alpha = arena ~= 0 and alpha_offset ~= nil and
      tonumber(sd.debug.read_float(arena + alpha_offset)) or 0.0
    local actor_alpha = actor ~= 0 and actor_alpha_offset ~= nil and
      tonumber(sd.debug.read_float(actor + actor_alpha_offset)) or 0.0
    observer.current = alpha
    observer.actor_current = actor_alpha
    observer.samples = observer.samples + 1
    if alpha > observer.maximum then observer.maximum = alpha end
    if actor_alpha > observer.actor_maximum then
      observer.actor_maximum = actor_alpha
    end
  end)
  _G.__sdmod_hitfx_red_observer_registered = true
end
emit("registered", _G.__sdmod_hitfx_red_observer_registered)
emit("armed", true)
""",
    )
    if (
        result.get("registered") != "true"
        or result.get("armed") != "true"
    ):
        raise VerificationFailure(
            f"Could not arm stock red-field observer: {result}"
        )
    return result


def query_red_field_observer(pipe_name: str) -> dict[str, str]:
    result = values(
        pipe_name,
        r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local observer = _G.__sdmod_hitfx_red_observer
emit("available", type(observer) == "table")
emit("maximum", observer and observer.maximum or -1)
emit("current", observer and observer.current or -1)
emit("actor_maximum", observer and observer.actor_maximum or -1)
emit("actor_current", observer and observer.actor_current or -1)
emit("samples", observer and observer.samples or 0)
""",
    )
    if result.get("available") != "true":
        raise VerificationFailure(
            f"Stock red-field observer disappeared: {result}"
        )
    return result


def copy_runtime_evidence() -> dict[str, str]:
    output = FLOW_ROOT / "runtime-evidence"
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


def verify(timeout: float) -> dict[str, Any]:
    started_at = time.time()
    result: dict[str, Any] = {
        "success": False,
        "startedUtc": utc_now(),
        "ports": {"host": HOST_PORT, "client": CLIENT_PORT},
        "clientName": CLIENT_NAME,
        "audioEnvironment": {
            "SDMOD_DISABLE_AUDIO": "1",
            "SDMOD_ENABLE_AUDIO": "0",
        },
    }
    failure: BaseException | None = None
    host_log = log_path(HOST_INSTANCE)
    client_log = log_path(CLIENT_INSTANCE)
    try:
        FLOW_ROOT.mkdir(parents=True, exist_ok=True)
        result["portPreflight"] = assert_ports_are_free()
        assert_no_existing_stage_processes()
        result["launch"] = launch_pair(timeout)
        result["ownedProcesses"] = OWNED_GAME_PROCESSES.as_json()
        result["arrivalGuards"] = {
            "host": arm_arrival_guard(
                HOST_PIPE,
                HOST_PARK_X,
                HOST_PARK_Y,
                remote_participant_id=CLIENT_ID,
                remote_x=CLIENT_TARGET_X,
                remote_y=CLIENT_TARGET_Y,
            ),
            "client": arm_arrival_guard(
                CLIENT_PIPE,
                CLIENT_TARGET_X,
                CLIENT_TARGET_Y,
            ),
        }
        result["run"] = start_testrun()
        result["positionHolds"] = {
            "host": hold_player(HOST_PIPE, HOST_PARK_X, HOST_PARK_Y),
            "client": hold_player(
                CLIENT_PIPE,
                CLIENT_TARGET_X,
                CLIENT_TARGET_Y,
            ),
        }
        result["wave"] = start_one_skeleton_wave()
        result["enemyParked"] = set_enemy_mode("park")
        result["arrivalGuardsReleased"] = {
            "host": release_arrival_guard(HOST_PIPE),
            "client": release_arrival_guard(CLIENT_PIPE),
        }
        result["clientEnemyMaterializerReleased"] = (
            set_manual_spawner_mode(CLIENT_PIPE, False)
        )
        result["initialVitals"] = {
            "host": set_local_vitals(
                HOST_PIPE,
                CLIENT_TEST_MAX_HP,
                CLIENT_TEST_MAX_HP,
            ),
            "client": set_local_vitals(
                CLIENT_PIPE,
                CLIENT_TEST_MAX_HP,
                CLIENT_TEST_MAX_HP,
            ),
        }
        result["clientArmed"] = set_local_vitals(
            CLIENT_PIPE,
            CLIENT_TEST_HP,
            CLIENT_TEST_MAX_HP,
        )
        result["authorityClientArmed"] = wait_for_remote_client_hp(
            CLIENT_TEST_HP
        )
        result["arenaIdentity"] = {
            "host": probe_hit_feedback_arena_identity(HOST_PIPE),
            "client": probe_hit_feedback_arena_identity(CLIENT_PIPE),
        }
        time.sleep(1.25)
        result["silentBeforeHitFrame"] = capture_game_backbuffer(
            CLIENT_PIPE,
            FLOW_ROOT / "client-b-silent-before-hit.png",
        )

        natural_host_offset = log_offset(host_log)
        natural_client_offset = log_offset(client_log)
        result["redFrameCaptureArmed"] = arm_red_frame_capture(
            CLIENT_PIPE,
            FLOW_ROOT / "client-b-red-hit-feedback.png",
            minimum_alpha=0.40,
        )
        result["enemyAttacking"] = set_enemy_mode("attack")
        result["redFrame"] = capture_red_feedback_frame(
            client_log,
            natural_client_offset,
            FLOW_ROOT / "client-b-red-hit-feedback.png",
        )
        result["enemyReparked"] = set_enemy_mode("park")
        natural_host_text, natural_client_text = wait_for_feedback_stable(
            host_log,
            client_log,
            natural_host_offset,
            natural_client_offset,
        )
        result["naturalEnemyHit"] = assert_exactly_once(
            natural_host_text,
            natural_client_text,
        )
        (FLOW_ROOT / "natural-host-feedback.log").write_text(
            natural_host_text,
            encoding="utf-8",
        )
        (FLOW_ROOT / "natural-client-feedback.log").write_text(
            natural_client_text,
            encoding="utf-8",
        )

        snapshot_host_offset = log_offset(host_log)
        snapshot_client_offset = log_offset(client_log)
        time.sleep(2.0)
        result["snapshotReapply"] = assert_no_feedback_on_snapshot_reapply(
            log_since(host_log, snapshot_host_offset),
            log_since(client_log, snapshot_client_offset),
        )

        heal_host_offset = log_offset(host_log)
        heal_client_offset = log_offset(client_log)
        result["healWrite"] = set_local_vitals(
            CLIENT_PIPE,
            HEALED_HP,
            CLIENT_TEST_MAX_HP,
        )
        result["healAuthorityObserved"] = wait_for_remote_client_hp(HEALED_HP)
        time.sleep(1.0)
        result["heal"] = assert_no_feedback_on_heal(
            log_since(host_log, heal_host_offset),
            log_since(client_log, heal_client_offset),
        )

        host_phase_host_offset = log_offset(host_log)
        host_phase_client_offset = log_offset(client_log)
        result["hostArmed"] = set_local_vitals(
            HOST_PIPE,
            CLIENT_TEST_HP,
            CLIENT_TEST_MAX_HP,
        )
        result["hostNativeRedObserverArmed"] = (
            arm_red_field_observer(HOST_PIPE)
        )
        result["hostNativeRedFrameCaptureArmed"] = arm_red_frame_capture(
            HOST_PIPE,
            FLOW_ROOT / "host-native-red-hit-feedback.png",
            minimum_alpha=0.40,
        )
        time.sleep(1.25)
        host_hit = queue_native_magic_hit(
            HOST_PIPE,
            target_participant_id=0,
            damage=3.0,
        )
        host_red_observer = query_red_field_observer(HOST_PIPE)
        host_red = float(host_red_observer["maximum"])
        host_actor_reaction = float(
            host_red_observer["actor_maximum"]
        )
        result["hostNativeProbe"] = host_hit
        result["hostNativeRedObserver"] = host_red_observer
        result["hostNativeRedFrame"] = finish_red_frame_capture(
            HOST_PIPE,
            FLOW_ROOT / "host-native-red-hit-feedback.png",
        )
        time.sleep(0.5)
        host_phase_text = log_since(host_log, host_phase_host_offset)
        client_host_phase_text = log_since(
            client_log,
            host_phase_client_offset,
        )
        result["otherParticipant"] = (
            assert_no_feedback_for_other_participant(
                client_host_phase_text,
            )
        )
        result["hostNative"] = assert_host_native_feedback_unchanged(
            host_phase_text,
            red_value=host_red,
            actor_reaction_value=host_actor_reaction,
            hp_before=host_hit["hpBefore"],
            hp_after=host_hit["hpAfter"],
        )

        result["success"] = True
    except BaseException as exc:
        failure = exc
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        cleanup: list[dict[str, Any]] = []
        try:
            reconcile_process_ledger(FLOW_ROOT / "pair-processes.json")
            cleanup = stop_owned_game_processes()
        except BaseException as cleanup_error:
            cleanup.append(
                {
                    "error": (
                        f"{type(cleanup_error).__name__}: {cleanup_error}"
                    )
                }
            )
            if failure is None:
                failure = cleanup_error
                result["success"] = False
                result["error"] = (
                    f"{type(cleanup_error).__name__}: {cleanup_error}"
                )
        result["cleanup"] = cleanup
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
        atomic_write_json(FLOW_ROOT / "result.json", result)
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
        default=150.0,
    )
    args = parser.parse_args()
    if args.evidence_root.resolve() != EVIDENCE_ROOT.resolve():
        parser.error(
            "this verifier is pinned to the hitfx evidence directory"
        )
    try:
        verify(args.timeout_seconds)
    except BaseException as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
