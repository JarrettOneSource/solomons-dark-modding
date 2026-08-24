#!/usr/bin/env python3
"""Record isolated native persistence goldens for the browser rebuild.

The recorder owns only ``sav-*`` instances under ``runtime/savere-captures``.
It derives Git and binary provenance itself, settles each persistence tree for
40 identical Windows-side hash samples spanning at least two seconds, copies
raw files only to the campaign evidence directory, and commits only decoded
trees and field tables.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


WINDOWS_POWERSHELL_DIRECTORY = Path(
    "/mnt/c/Windows/System32/WindowsPowerShell/v1.0"
)
os.environ["PATH"] = (
    str(WINDOWS_POWERSHELL_DIRECTORY)
    + os.pathsep
    + os.environ.get("PATH", "")
)

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from native_save_format import (  # noqa: E402
    DARKDATA_CORE_FIELDS,
    DARKDATA_KEY,
    FRESH_PROFILE_DEFAULTS,
    SYNCBUFFER_ENDIANNESS,
    SYNCBUFFER_MAGIC,
    SYNCBUFFER_VERSION,
    SaveFormatError,
    decode_save_bytes,
)
from owned_process_ledger import (  # noqa: E402
    OWNED_GAME_PROCESSES,
    register_owned_launch,
    stop_owned_process_ids,
)
import verify_local_multiplayer_sync as local_sync  # noqa: E402


POWERSHELL = Path(
    "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
)
LAUNCH_SCRIPT = ROOT / "scripts" / "Launch-LocalSoloSession.ps1"
LAUNCHER = ROOT / "dist" / "launcher" / "SolomonDarkModLauncher.exe"
LOADER = ROOT / "dist" / "launcher" / "SolomonDarkModLoader.dll"
GAME_DIRECTORY = ROOT / "runtime" / "source-game"
RUNTIME_ROOT = ROOT / "runtime" / "savere-captures"
EVIDENCE_ROOT = Path("/mnt/d/codex-evidence/savere-20260806")
RAW_EVIDENCE_ROOT = EVIDENCE_ROOT / "raw"
DEFAULT_OUTPUT = ROOT / "tests" / "fixtures" / "webgame" / "save-format-goldens.json"
EXECUTION_RECORD = EVIDENCE_ROOT / "save-format-recorder-execution.json"

ALLOWED_PORTS = tuple(range(52401, 52409))
SETTLE_SAMPLE_COUNT = 40
SETTLE_MINIMUM_SECONDS = 2.0
SETTLE_TIMEOUT_SECONDS = 45.0
PROFILE_ADDRESS = 0x0081A330
PROFILE_DEFAULTS = 0x005A8390
PROFILE_SAVE = 0x005BE0B0
APPLY_HAGATHA_PERK = 0x0066EF70

SCENARIOS = (
    {
        "id": "fresh_profile",
        "instance": "sav-fresh",
        "local_port": 52401,
        "unused_port": 52402,
    },
    {
        "id": "mid_progression_after_scripted_run",
        "instance": "sav-mid",
        "local_port": 52403,
        "unused_port": 52404,
    },
    {
        "id": "post_unlock",
        "instance": "sav-unlock",
        "local_port": 52405,
        "unused_port": 52406,
    },
)


class CaptureFailure(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CaptureFailure(message)


def as_int(value: object, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(str(value), 0)
    except ValueError:
        return int(float(str(value)))


def git_output(*arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30.0,
        check=False,
    )
    require(
        completed.returncode == 0,
        f"git {' '.join(arguments)} failed: {completed.stdout}",
    )
    return completed.stdout.strip()


def windows_path(path: Path) -> str:
    return local_sync.path_for_powershell(path)


def _ps_literal(value: str) -> str:
    return value.replace("'", "''")


def run_powershell(script: str, *, timeout: float = 60.0) -> str:
    completed = subprocess.run(
        [
            str(POWERSHELL),
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    require(
        completed.returncode == 0,
        f"Windows probe failed ({completed.returncode}): {completed.stdout}",
    )
    return completed.stdout.strip().lstrip("\ufeff")


def windows_sha256(path: Path) -> str:
    literal = _ps_literal(windows_path(path))
    value = run_powershell(
        f"(Get-FileHash -LiteralPath '{literal}' -Algorithm SHA256).Hash.ToLowerInvariant()"
    ).splitlines()[-1]
    require(
        len(value) == 64 and all(character in "0123456789abcdef" for character in value),
        f"Windows did not return a SHA-256 for {path}: {value!r}",
    )
    return value


def snapshot_owned_processes() -> list[dict[str, Any]]:
    root = _ps_literal(windows_path(RUNTIME_ROOT / "instances"))
    script = f"""
$root = [IO.Path]::GetFullPath('{root}').TrimEnd('\\') + '\\'
$rows = @(
  Get-CimInstance Win32_Process -Filter "Name = 'SolomonDark.exe'" |
    Where-Object {{
      $_.ExecutablePath -and
      [IO.Path]::GetFullPath($_.ExecutablePath).StartsWith(
        $root, [StringComparison]::OrdinalIgnoreCase)
    }} |
    Select-Object @{{n='process_id';e={{[int]$_.ProcessId}}}},
                  @{{n='executable_path';e={{[string]$_.ExecutablePath}}}}
)
if ($rows.Count -eq 0) {{ '[]' }} else {{ $rows | ConvertTo-Json -Compress }}
"""
    parsed = json.loads(run_powershell(script) or "[]")
    if isinstance(parsed, dict):
        return [parsed]
    require(isinstance(parsed, list), f"unexpected process snapshot: {parsed!r}")
    return parsed


class OwnedSaveSession:
    def __init__(self, instance: str, local_port: int, unused_port: int) -> None:
        require(instance.startswith("sav-"), f"instance is outside sav-* scope: {instance}")
        require(local_port in ALLOWED_PORTS, f"port is outside G10 range: {local_port}")
        require(unused_port in ALLOWED_PORTS, f"port is outside G10 range: {unused_port}")
        require(local_port != unused_port, "local and unused ports must differ")
        self.instance = instance
        self.local_port = local_port
        self.unused_port = unused_port
        self.pipe_name = f"SolomonDarkModLoader_LuaExec_{instance}"
        self.process_ids: list[int] = []
        self.launch_result: dict[str, Any] | None = None

    @property
    def instance_root(self) -> Path:
        return RUNTIME_ROOT / "instances" / self.instance

    @property
    def stage_root(self) -> Path:
        return self.instance_root / "stage"

    @property
    def sandbox_root(self) -> Path:
        return self.stage_root / "sandbox"

    @property
    def expected_executable(self) -> Path:
        return self.stage_root / "SolomonDark.exe"

    def launch(self) -> dict[str, Any]:
        require(self.launch_result is None, "session has already launched")
        for path, consequence in (
            (POWERSHELL, "Windows PowerShell is not runnable"),
            (LAUNCH_SCRIPT, "solo launcher script is missing"),
            (LAUNCHER, "built launcher is missing"),
            (LOADER, "built loader is missing"),
            (GAME_DIRECTORY / "SolomonDark.exe", "isolated game replica is missing"),
        ):
            require(path.is_file(), f"BROKEN: {consequence}: {path}")

        RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
        token = f"{self.instance}-{os.getpid()}"
        ledger_path = RUNTIME_ROOT / f".{token}-ledger.json"
        result_path = RUNTIME_ROOT / f".{token}-result.json"
        output_path = RUNTIME_ROOT / f".{token}-launcher.log"
        arguments = [
            str(POWERSHELL),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            windows_path(LAUNCH_SCRIPT),
            "-Instance",
            self.instance,
            "-Preset",
            "map_create_water_arcane_hub",
            "-RuntimeRoot",
            windows_path(RUNTIME_ROOT),
            "-LocalPort",
            str(self.local_port),
            "-UnusedRemotePort",
            str(self.unused_port),
            "-ParticipantId",
            f"0x200000000000{self.local_port:04X}",
            "-PlayerName",
            f"G10 {self.instance}",
            "-GameDirectory",
            windows_path(GAME_DIRECTORY),
            "-LauncherPath",
            windows_path(LAUNCHER),
            "-FreshInstall",
            "-QuickStart",
            "-QuickStartElement",
            "water",
            "-QuickStartDiscipline",
            "arcane",
            "-Headless",
            "-ExactModIds",
            "sample.lua.ui_sandbox_lab",
            "-LuaExecTargetModId",
            "sample.lua.ui_sandbox_lab",
            "-ProcessIdOutputPath",
            windows_path(ledger_path),
            "-ResultOutputPath",
            windows_path(result_path),
        ]
        environment = os.environ.copy()
        environment["SDMOD_DISABLE_AUDIO"] = "1"
        environment["SDMOD_LUA_BOTS_ACTIVE"] = "none"
        environment.pop("SDMOD_ENABLE_AUDIO", None)
        with output_path.open("w", encoding="utf-8") as output:
            wrapper = subprocess.Popen(
                arguments,
                cwd=ROOT,
                env=environment,
                text=True,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
        try:
            deadline = time.monotonic() + 180.0
            while time.monotonic() < deadline and not result_path.is_file():
                return_code = wrapper.poll()
                if return_code is not None:
                    message = output_path.read_text(encoding="utf-8", errors="replace")
                    raise CaptureFailure(
                        f"BROKEN: launcher exited {return_code} before publishing "
                        f"a result: {message[-4000:]}"
                    )
                time.sleep(0.1)
            require(
                result_path.is_file(),
                "BUSY_TIMEOUT: launcher did not publish its result",
            )
            result = json.loads(result_path.read_text(encoding="utf-8-sig"))
            require(isinstance(result, dict), "BROKEN: launcher result is not an object")
            require(result.get("success") is True, f"BROKEN: launcher failed: {result}")
            require(result.get("audioDisabled") is True, "BROKEN: audio was not disabled")
            require(result.get("headlessEnabled") is True, "BROKEN: launch is not headless")
            require(
                as_int(result.get("localPort")) == self.local_port,
                f"BROKEN: launcher used the wrong UDP port: {result}",
            )
            identities = register_owned_launch(result)
            self.process_ids = [identity.process_id for identity in identities]
            require(
                len(self.process_ids) == 1,
                f"BROKEN: expected exactly one owned process: {identities}",
            )
            self.launch_result = result
            return result
        finally:
            if wrapper.poll() is None:
                wrapper.terminate()
                try:
                    wrapper.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    wrapper.kill()
                    wrapper.wait(timeout=5.0)
            ledger_path.unlink(missing_ok=True)
            result_path.unlink(missing_ok=True)

    def assert_runnable(self) -> None:
        inspections = OWNED_GAME_PROCESSES.inspect()
        ours = [
            row
            for row in inspections
            if as_int(row.get("processId")) in self.process_ids
        ]
        require(
            len(ours) == len(self.process_ids),
            f"BROKEN: owned process disappeared: {inspections}",
        )
        bad = [
            row
            for row in ours
            if row.get("alreadyExited") or not row.get("pathMatched")
        ]
        require(
            not bad,
            f"BROKEN: owned process is not runnable at its staged path: {bad}",
        )

    def lua(self, code: str, *, timeout: float = 20.0) -> str:
        return local_sync.lua(self.pipe_name, code, timeout=timeout)

    def values(self, code: str, *, timeout: float = 20.0) -> dict[str, str]:
        return local_sync.parse_key_values(self.lua(code, timeout=timeout))

    def wait_for_pipe(self) -> None:
        deadline = time.monotonic() + 120.0
        last_busy = ""
        while time.monotonic() < deadline:
            self.assert_runnable()
            try:
                output = self.lua("return 'ready'", timeout=5.0)
                if output.strip() == "ready":
                    return
                last_busy = f"unexpected readiness output: {output!r}"
            except (local_sync.VerifyFailure, subprocess.TimeoutExpired) as error:
                message = str(error)
                if "busy" in message.lower() or "pipe" in message.lower():
                    last_busy = message
                else:
                    raise CaptureFailure(
                        f"BROKEN: Lua exec invocation failed: {message}"
                    ) from error
            time.sleep(0.25)
        raise CaptureFailure(
            f"BUSY_TIMEOUT: Lua pipe never became runnable: {last_busy}"
        )

    def close(self) -> list[dict[str, Any]]:
        process_ids = list(self.process_ids)
        self.process_ids.clear()
        try:
            if not process_ids:
                return []
            return stop_owned_process_ids(process_ids)
        finally:
            local_sync._kill_lua_daemon(self.pipe_name)


RESET_PROFILE_LUA = f"""
local profile = assert(sd.debug.resolve_game_address({PROFILE_ADDRESS}))
local defaults = assert(sd.debug.resolve_game_address({PROFILE_DEFAULTS}))
local save = assert(sd.debug.resolve_game_address({PROFILE_SAVE}))
sd.debug.call_thiscall_ret_u32(defaults, profile)
assert(sd.debug.write_i32(profile + 0x64, 0))
for index = 0, 29 do assert(sd.debug.write_u8(profile + 0x6c + index, 0)) end
assert(sd.debug.write_i32(profile + 0xfc, 0))
assert(sd.debug.write_u8(profile + 0x105, 0))
print('profile=' .. tostring(profile))
print('save=' .. tostring(save))
"""


PROFILE_STATE_LUA = f"""
local profile = assert(sd.debug.resolve_game_address({PROFILE_ADDRESS}))
local rows = {{}}
local function emit(key, value) rows[#rows + 1] = key .. '=' .. tostring(value) end
emit('profile_address', profile)
emit('gold', sd.debug.read_i32(profile + 0x58))
emit('stock_tutorial_pending', sd.debug.read_u8(profile + 0x104))
emit('profile_flag_0x105', sd.debug.read_u8(profile + 0x105))
emit('portrait_age_counter', sd.debug.read_i32(profile + 0xf4))
emit('next_portrait_index', sd.debug.read_i32(profile + 0xf8))
emit('last_portrait_index', sd.debug.read_i32(profile + 0xfc))
emit('shlorio_fee', sd.debug.read_i32(profile + 0x100))
for index = 0, 9 do
  emit('class_available.' .. index, sd.debug.read_u8(profile + 0x90 + index))
  emit('class_enabled.' .. index, sd.debug.read_u8(profile + 0x9a + index))
  emit('memorial_slot_ages.' .. index, sd.debug.read_i32(profile + 0xa4 + index * 4))
  emit('memorial_portrait_ids.' .. index, sd.debug.read_i32(profile + 0xcc + index * 4))
end
for index = 0, 29 do
  emit('hagatha_first_mix.' .. index, sd.debug.read_u8(profile + 0x6c + index))
end
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
local progression = tonumber(player and player.progression_address) or 0
emit('progression_address', progression)
if progression ~= 0 then
  local list_offset = sd.debug.layout_offset('progression_hagatha_perk_list')
  local count_offset = sd.debug.layout_offset('progression_hagatha_perk_count')
  local capacity_offset = sd.debug.layout_offset('progression_hagatha_perk_capacity')
  local list = tonumber(sd.debug.read_ptr(progression + list_offset)) or 0
  local count = tonumber(sd.debug.read_i32(progression + count_offset)) or -1
  emit('progression_perk_count', count)
  emit('progression_perk_capacity', sd.debug.read_i32(progression + capacity_offset))
  if list ~= 0 and count >= 0 and count <= 9 then
    for index = 0, count - 1 do
      emit('progression_perk.' .. index, sd.debug.read_i32(list + index * 4))
    end
  end
end
print(table.concat(rows, string.char(10)))
"""


def wait_for_profile(session: OwnedSaveSession, require_progression: bool) -> None:
    deadline = time.monotonic() + 90.0
    last: dict[str, str] = {}
    last_error = ""
    while time.monotonic() < deadline:
        session.assert_runnable()
        try:
            last = session.values(PROFILE_STATE_LUA, timeout=8.0)
            if as_int(last.get("profile_address")) != 0 and (
                not require_progression
                or as_int(last.get("progression_address")) != 0
            ):
                return
        except (local_sync.VerifyFailure, subprocess.TimeoutExpired) as error:
            last_error = f"{type(error).__name__}: {error}"
        time.sleep(0.2)
    raise CaptureFailure(
        "BUSY_TIMEOUT: live profile did not become ready; "
        f"last={last}; last_error={last_error}"
    )


def record_fresh(session: OwnedSaveSession) -> dict[str, Any]:
    values = session.values(
        RESET_PROFILE_LUA
        + """
local result = sd.debug.call_thiscall_ret_u32(save, profile)
print('save_result=' .. tostring(result))
print('persisted_gold=' .. tostring(sd.debug.read_i32(profile + 0x58)))
print('persisted_first_mix_0=' .. tostring(sd.debug.read_u8(profile + 0x6c)))
"""
    )
    result = as_int(values.get("save_result"), -1)
    require(result == 1, f"BROKEN: native fresh-profile save returned {result}")
    return {
        "driver": "native fresh-profile initializer 0x005A8390 followed by native save 0x005BE0B0",
        "save_result": result,
        "persisted_gold": as_int(values.get("persisted_gold"), -1),
        "persisted_first_mix_0": bool(as_int(values.get("persisted_first_mix_0"))),
    }


def record_mid_progression(session: OwnedSaveSession) -> dict[str, Any]:
    values = session.values(
        RESET_PROFILE_LUA
        + """
print('run_start=' .. tostring(sd.debug.read_i32(profile + 0x58)))
assert(sd.debug.write_i32(profile + 0x58, 625))
print('reward_checkpoint_1=' .. tostring(sd.debug.read_i32(profile + 0x58)))
assert(sd.debug.write_i32(profile + 0x58, 875))
print('run_end=' .. tostring(sd.debug.read_i32(profile + 0x58)))
local result = sd.debug.call_thiscall_ret_u32(save, profile)
print('save_result=' .. tostring(result))
"""
    )
    checkpoints = [
        {"label": "run_start", "profile_gold": as_int(values.get("run_start"), -1)},
        {
            "label": "reward_checkpoint_1",
            "profile_gold": as_int(values.get("reward_checkpoint_1"), -1),
        },
        {"label": "run_end", "profile_gold": as_int(values.get("run_end"), -1)},
    ]
    require(
        [row["profile_gold"] for row in checkpoints] == [500, 625, 875],
        f"BROKEN: scripted run checkpoints changed: {checkpoints}",
    )
    result = as_int(values.get("save_result"), -1)
    require(result == 1, f"BROKEN: native scripted-run save returned {result}")
    return {
        "driver": "three-step live scripted run-reward checkpoint ending in native save 0x005BE0B0",
        "checkpoints": checkpoints,
        "save_result": result,
        "scope_note": "The script drives the recovered profile reward seam; it does not claim a natural enemy/drop replay.",
    }


def record_post_unlock(session: OwnedSaveSession) -> dict[str, Any]:
    before = session.values(PROFILE_STATE_LUA)
    values = session.values(
        RESET_PROFILE_LUA
        + f"""
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
local progression = tonumber(player and player.progression_address) or 0
local count_offset = sd.debug.layout_offset('progression_hagatha_perk_count')
local capacity_offset = sd.debug.layout_offset('progression_hagatha_perk_capacity')
local before_count = progression ~= 0 and (sd.debug.read_i32(progression + count_offset) or -1) or -1
local before_capacity = progression ~= 0 and (sd.debug.read_i32(progression + capacity_offset) or -1) or -1
local apply = assert(sd.debug.resolve_game_address({APPLY_HAGATHA_PERK}))
local applied = progression ~= 0 and before_count >= 0 and before_count < before_capacity and
  sd.debug.call_thiscall_u32(apply, progression, 0) or false
assert(applied)
assert(sd.debug.write_u8(profile + 0x6c, 1))
assert(sd.debug.write_i32(profile + 0x58, 250))
local save_result = sd.debug.call_thiscall_ret_u32(save, profile)
print('applied=' .. tostring(applied))
print('before_count=' .. tostring(before_count))
print('after_count=' .. tostring(sd.debug.read_i32(progression + count_offset)))
print('save_result=' .. tostring(save_result))
"""
    )
    require(values.get("applied") == "true", f"BROKEN: native perk apply failed: {values}")
    require(
        as_int(values.get("after_count")) == as_int(values.get("before_count")) + 1,
        f"BROKEN: native perk count did not advance: {values}",
    )
    result = as_int(values.get("save_result"), -1)
    require(result == 1, f"BROKEN: native post-unlock save returned {result}")
    after = session.values(PROFILE_STATE_LUA)
    return {
        "driver": "native Hagatha perk apply 0x0066EF70 selector 0, matching first-mix flag, gold debit, then native profile save",
        "before_progression_perk_count": as_int(before.get("progression_perk_count"), -1),
        "after_progression_perk_count": as_int(after.get("progression_perk_count"), -1),
        "after_progression_selectors": [
            as_int(after.get(f"progression_perk.{index}"), -1)
            for index in range(max(0, as_int(after.get("progression_perk_count"), 0)))
        ],
        "save_result": result,
    }


def normalized_profile_state(values: dict[str, str]) -> dict[str, Any]:
    perk_count = max(0, as_int(values.get("progression_perk_count"), 0))
    return {
        "profile_address": as_int(values.get("profile_address")),
        "gold": as_int(values.get("gold")),
        "stock_tutorial_pending": bool(as_int(values.get("stock_tutorial_pending"))),
        "profile_flag_0x105": bool(as_int(values.get("profile_flag_0x105"))),
        "portrait_age_counter": as_int(values.get("portrait_age_counter")),
        "next_portrait_index": as_int(values.get("next_portrait_index")),
        "last_portrait_index": as_int(values.get("last_portrait_index")),
        "shlorio_fee": as_int(values.get("shlorio_fee")),
        "class_available": [
            bool(as_int(values.get(f"class_available.{index}")))
            for index in range(10)
        ],
        "class_enabled": [
            bool(as_int(values.get(f"class_enabled.{index}")))
            for index in range(10)
        ],
        "memorial_slot_ages": [
            as_int(values.get(f"memorial_slot_ages.{index}"))
            for index in range(10)
        ],
        "memorial_portrait_ids": [
            as_int(values.get(f"memorial_portrait_ids.{index}"))
            for index in range(10)
        ],
        "hagatha_first_mix_flags": [
            bool(as_int(values.get(f"hagatha_first_mix.{index}")))
            for index in range(30)
        ],
        "progression": {
            "address": as_int(values.get("progression_address")),
            "perk_count": perk_count,
            "perk_capacity": as_int(values.get("progression_perk_capacity"), -1),
            "selectors": [
                as_int(values.get(f"progression_perk.{index}"), -1)
                for index in range(perk_count)
            ],
        },
    }


def settle_persistence(session: OwnedSaveSession) -> dict[str, Any]:
    sandbox = _ps_literal(windows_path(session.sandbox_root))
    executable = _ps_literal(windows_path(session.expected_executable))
    process_id = session.process_ids[0]
    script = f"""
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath('{sandbox}')
$expected = [IO.Path]::GetFullPath('{executable}')
$pidToCheck = {process_id}
$needed = {SETTLE_SAMPLE_COUNT}
$minimumSeconds = {SETTLE_MINIMUM_SECONDS}
$deadline = [DateTime]::UtcNow.AddSeconds({SETTLE_TIMEOUT_SECONDS})
$stable = 0
$stableStart = $null
$last = $null
$samples = 0
do {{
  $process = Get-CimInstance Win32_Process -Filter "ProcessId = $pidToCheck" -ErrorAction SilentlyContinue
  if ($null -eq $process -or -not $process.ExecutablePath -or
      -not [string]::Equals([IO.Path]::GetFullPath($process.ExecutablePath), $expected,
        [StringComparison]::OrdinalIgnoreCase)) {{
    throw "BROKEN: owned game process stopped owning the exact staged executable"
  }}
  $rows = @(
    Get-ChildItem -LiteralPath $root -Recurse -File -ErrorAction Stop |
      Where-Object {{
        $relative = $_.FullName.Substring($root.Length).TrimStart('\\')
        $relative -eq 'settings.txt' -or
        $relative -eq 'playfactor.cfg' -or
        $relative -like 'savegames\\*' -or
        $relative -like 'social\\__achievements.dat' -or
        $relative -like 'Portraits\\portrait*.raw'
      }} |
      Sort-Object FullName |
      ForEach-Object {{
        [ordered]@{{
          relative_path = $_.FullName.Substring($root.Length).TrimStart('\\')
          length = [long]$_.Length
          sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }}
      }}
  )
  if (-not ($rows | Where-Object {{ $_.relative_path -eq 'savegames\\solomondark\\darkdata.cfg' }})) {{
    $stable = 0
    $stableStart = $null
    $last = $null
    Start-Sleep -Milliseconds 50
    continue
  }}
  $json = ConvertTo-Json @($rows) -Compress -Depth 5
  $samples++
  if ($json -ceq $last) {{
    $stable++
  }} else {{
    $stable = 1
    $stableStart = [DateTime]::UtcNow
    $last = $json
  }}
  $elapsed = if ($null -eq $stableStart) {{ 0.0 }} else {{ ([DateTime]::UtcNow - $stableStart).TotalSeconds }}
  if ($stable -ge $needed -and $elapsed -ge $minimumSeconds) {{
    [ordered]@{{
      sample_count = $stable
      total_samples = $samples
      stable_seconds = $elapsed
      animated_elements = @()
      files = @($rows)
    }} | ConvertTo-Json -Compress -Depth 7
    exit 0
  }}
  Start-Sleep -Milliseconds 50
}} while ([DateTime]::UtcNow -lt $deadline)
throw "BUSY_TIMEOUT: persistence files never reached $needed identical samples over $minimumSeconds seconds"
"""
    output = run_powershell(script, timeout=SETTLE_TIMEOUT_SECONDS + 15.0)
    result = json.loads(output.splitlines()[-1])
    require(
        as_int(result.get("sample_count")) >= SETTLE_SAMPLE_COUNT,
        "BROKEN: settle gate returned too few identical samples",
    )
    require(
        float(result.get("stable_seconds", 0.0)) >= SETTLE_MINIMUM_SECONDS,
        "BROKEN: settle gate returned too little stable time",
    )
    files = result.get("files")
    require(isinstance(files, list) and files, "BROKEN: settle gate examined no files")
    require(
        any(row.get("relative_path") == "savegames\\solomondark\\darkdata.cfg" for row in files),
        "BROKEN: settle gate never examined native darkdata.cfg",
    )
    return result


def copy_settled_files(
    session: OwnedSaveSession,
    scenario_id: str,
    settled: dict[str, Any],
) -> list[dict[str, Any]]:
    destination_root = RAW_EVIDENCE_ROOT / scenario_id
    require(
        not destination_root.exists(),
        f"refusing to overwrite existing raw evidence: {destination_root}",
    )
    destination_root.mkdir(parents=True)
    copied: list[dict[str, Any]] = []
    for row in settled["files"]:
        relative_windows = str(row["relative_path"])
        relative = Path(*relative_windows.split("\\"))
        source = session.sandbox_root / relative
        destination = destination_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        source_literal = _ps_literal(windows_path(source))
        destination_literal = _ps_literal(windows_path(destination))
        run_powershell(
            f"Copy-Item -LiteralPath '{source_literal}' -Destination "
            f"'{destination_literal}' -Force"
        )
        copied_hash = windows_sha256(destination)
        expected_hash = str(row["sha256"])
        require(
            copied_hash == expected_hash,
            f"BROKEN: evidence copy changed {relative_windows}: "
            f"{expected_hash} -> {copied_hash}",
        )
        copied.append(
            {
                "relative_path": relative_windows.replace("\\", "/"),
                "evidence_relative_path": str(
                    destination.relative_to(EVIDENCE_ROOT)
                ).replace(os.sep, "/"),
                "length": int(row["length"]),
                "sha256": copied_hash,
                "path": destination,
            }
        )
    return copied


def decode_text_file(data: bytes) -> dict[str, Any]:
    try:
        text = data.decode("utf-8")
        encoding = "utf-8"
    except UnicodeDecodeError:
        text = data.decode("cp1252")
        encoding = "windows-1252"
    if "\r\n" in text and text.replace("\r\n", "").find("\n") == -1:
        newline = "crlf"
    elif "\n" in text and "\r\n" not in text:
        newline = "lf"
    elif "\r" in text and "\n" not in text:
        newline = "cr"
    else:
        newline = "mixed_or_none"
    entries: list[dict[str, str]] = []
    for index, line in enumerate(text.splitlines()):
        if not line or line.startswith("#") or line.startswith(";"):
            entries.append({"line": str(index + 1), "kind": "literal", "text": line})
        elif "=" in line:
            key, value = line.split("=", 1)
            entries.append(
                {"line": str(index + 1), "kind": "setting", "key": key, "value": value}
            )
        else:
            entries.append({"line": str(index + 1), "kind": "literal", "text": line})
    return {
        "codec": {"kind": "key_value_text", "encoding": encoding, "newline": newline},
        "raw_length": len(data),
        "entries": entries,
        "final_newline": text.endswith(("\n", "\r")),
        "round_trip_identical": text.encode(encoding) == data,
    }


def decode_copied_file(row: dict[str, Any]) -> dict[str, Any]:
    path = row.pop("path")
    data = path.read_bytes()
    require(
        len(data) == row["length"],
        f"BROKEN: decoded evidence length changed for {row['relative_path']}",
    )
    relative = str(row["relative_path"]).lower()
    if relative.endswith("darkdata.cfg"):
        decoded = decode_save_bytes(data, "darkdata")
    elif relative.endswith(("gamestate.sav", "halloffame.dat", "._cache")):
        decoded = decode_save_bytes(data, "syncbuffer")
    elif relative.endswith(("settings.txt", "playfactor.cfg")):
        decoded = decode_text_file(data)
        decoded["raw_sha256"] = row["sha256"]
        decoded["round_trip_sha256"] = row["sha256"]
    else:
        decoded = {
            "codec": {"kind": "opaque"},
            "raw_length": len(data),
            "raw_sha256": row["sha256"],
            "round_trip_identical": True,
            "round_trip_sha256": row["sha256"],
            "opaque_hex": data.hex(),
        }
    require(
        decoded.get("raw_sha256") == row["sha256"],
        f"BROKEN: Python decode hash disagrees with Windows for {row['relative_path']}",
    )
    require(
        decoded.get("round_trip_identical") is True,
        f"BROKEN: decode/re-encode changed {row['relative_path']}",
    )
    return {**row, **decoded}


def validate_live_vs_decoded(
    scenario_id: str, live: dict[str, Any], decoded_file: dict[str, Any]
) -> None:
    decoded = decoded_file.get("decoded_fields")
    require(isinstance(decoded, dict), "BROKEN: darkdata fixture has no decoded fields")
    core = {
        row["name"]: row["value"]
        for row in decoded["core_fields"]
    }
    expected_gold = {
        "fresh_profile": 500,
        "mid_progression_after_scripted_run": 875,
        "post_unlock": 250,
    }[scenario_id]
    require(
        core.get("profile_gold") == expected_gold,
        f"BROKEN: decoded profile gold does not pin {scenario_id}",
    )
    require(
        core.get("stock_tutorial_pending") is True,
        f"BROKEN: decoded tutorial default does not survive {scenario_id}",
    )
    expected_mix = [index == 27 for index in range(30)]
    if scenario_id == "post_unlock":
        expected_mix[0] = True
    require(
        decoded.get("hagatha_first_mix_flags") == expected_mix,
        f"BROKEN: decoded first-mix flags do not pin {scenario_id}",
    )
    require(
        decoded.get("shlorio_fee") in range(500, 951, 50),
        f"BROKEN: decoded Shlorio fee left the native default domain in {scenario_id}",
    )


def capture_scenario(spec: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    session = OwnedSaveSession(
        str(spec["instance"]), int(spec["local_port"]), int(spec["unused_port"])
    )
    cleanup: list[dict[str, Any]] = []
    try:
        launch = session.launch()
        session.wait_for_pipe()
        wait_for_profile(session, spec["id"] == "post_unlock")
        if spec["id"] == "fresh_profile":
            trace = record_fresh(session)
        elif spec["id"] == "mid_progression_after_scripted_run":
            trace = record_mid_progression(session)
        elif spec["id"] == "post_unlock":
            trace = record_post_unlock(session)
        else:
            raise AssertionError(f"unknown scenario {spec['id']}")
        live = normalized_profile_state(session.values(PROFILE_STATE_LUA))
        settled = settle_persistence(session)
        copied = copy_settled_files(session, str(spec["id"]), settled)
        files = [decode_copied_file(row) for row in copied]
        darkdata = [
            row
            for row in files
            if row["relative_path"] == "savegames/solomondark/darkdata.cfg"
        ]
        require(
            len(darkdata) == 1,
            f"BROKEN: scenario {spec['id']} captured {len(darkdata)} darkdata files",
        )
        validate_live_vs_decoded(str(spec["id"]), live, darkdata[0])
        return (
            {
                "id": spec["id"],
                "generation": {
                    "instance": spec["instance"],
                    "local_port": spec["local_port"],
                    "unused_remote_port": spec["unused_port"],
                    "headless": True,
                    "audio_disabled": True,
                    "fresh_install": True,
                    "source_game_role": "campaign-owned isolated replica",
                    "native_profile_path_observed": (
                        f"runtime/savere-captures/instances/{spec['instance']}/"
                        "stage/sandbox/savegames/solomondark/"
                    ),
                    "launch_startup_code": launch.get("startupCode"),
                },
                "scenario_trace": trace,
                "live_profile": live,
                "settle_gate": {
                    "sample_count": int(settled["sample_count"]),
                    "total_samples": int(settled["total_samples"]),
                    "stable_seconds": float(settled["stable_seconds"]),
                    "animated_elements": settled["animated_elements"],
                },
                "files": files,
            },
            {"instance": spec["instance"], "process_ids": list(session.process_ids)},
        )
    finally:
        cleanup = session.close()
        if cleanup:
            cleanup_path = EVIDENCE_ROOT / f"{spec['id']}-cleanup.json"
            cleanup_path.write_text(json.dumps(cleanup, indent=2) + "\n", encoding="utf-8")


def validate_capture_set(captures: list[dict[str, Any]]) -> None:
    ids = [capture["id"] for capture in captures]
    expected = [str(spec["id"]) for spec in SCENARIOS]
    require(ids == expected, f"capture ids changed: expected {expected}, got {ids}")
    hashes: list[str] = []
    for capture in captures:
        darkdata = next(
            row
            for row in capture["files"]
            if row["relative_path"] == "savegames/solomondark/darkdata.cfg"
        )
        hashes.append(str(darkdata["sha256"]))
    require(
        len(set(hashes)) == len(hashes),
        f"capture scenarios did not produce three distinct darkdata files: {hashes}",
    )


def record(output: Path) -> dict[str, Any]:
    require(POWERSHELL.is_file(), f"PowerShell is not runnable: {POWERSHELL}")
    require(GAME_DIRECTORY.is_dir(), f"isolated game replica is missing: {GAME_DIRECTORY}")
    require(
        windows_path(GAME_DIRECTORY).lower().startswith("d:\\sd-savere-20260806\\"),
        f"refusing a source game outside the campaign clone: {GAME_DIRECTORY}",
    )
    before = snapshot_owned_processes()
    require(not before, f"BUSY: savere capture processes already exist: {before}")
    require(
        not RAW_EVIDENCE_ROOT.exists(),
        f"refusing to overwrite raw evidence root: {RAW_EVIDENCE_ROOT}",
    )

    source_revision = git_output("rev-parse", "HEAD")
    require(len(source_revision) == 40, f"git returned an invalid revision: {source_revision}")
    provenance = {
        "schema": "solomon-dark-save-format-goldens-v1",
        "source_revision": source_revision,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "retail_executable": {
            "role": "campaign-owned D-drive source-game replica",
            "sha256": windows_sha256(GAME_DIRECTORY / "SolomonDark.exe"),
        },
        "loader": {
            "role": "Release loader injected into each isolated stage",
            "sha256": windows_sha256(LOADER),
        },
        "recorder": "tests/re/record_live_save_format_goldens.py",
        "provenance_policy": "source revision and binary hashes are derived by this recorder; no provenance override arguments exist",
        "capture_contract": {
            "instances": [str(spec["instance"]) for spec in SCENARIOS],
            "allowed_udp_ports": list(ALLOWED_PORTS),
            "audio_disabled": True,
            "owner_saves_opened": False,
            "raw_files_location": "evidence only",
            "settle_samples": SETTLE_SAMPLE_COUNT,
            "settle_minimum_seconds": SETTLE_MINIMUM_SECONDS,
            "settle_payload": "relative path, byte length, and Windows-side SHA-256 for every persistence file",
        },
    }

    captures: list[dict[str, Any]] = []
    launches: list[dict[str, Any]] = []
    try:
        for spec in SCENARIOS:
            capture, launch = capture_scenario(spec)
            captures.append(capture)
            launches.append(launch)
        validate_capture_set(captures)
    finally:
        after = snapshot_owned_processes()
        require(not after, f"BROKEN: savere processes remained after cleanup: {after}")

    document = {
        "provenance": provenance,
        "format_contract": {
            "endianness": SYNCBUFFER_ENDIANNESS,
            "magic": SYNCBUFFER_MAGIC,
            "version": SYNCBUFFER_VERSION,
            "darkdata_xor_key_utf8": DARKDATA_KEY.decode("utf-8"),
            "darkdata_core_fields": [
                {
                    "name": field.name,
                    "payload_offset": field.file_offset,
                    "size": field.size,
                    "type": field.value_type,
                    "runtime_offset": field.runtime_offset,
                }
                for field in DARKDATA_CORE_FIELDS
            ],
        },
        "fresh_profile_defaults": FRESH_PROFILE_DEFAULTS,
        "captures": captures,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    EXECUTION_RECORD.write_text(
        json.dumps(
            {
                "before_processes": before,
                "launches": launches,
                "after_processes": snapshot_owned_processes(),
                "output": str(output),
                "output_sha256_windows": windows_sha256(output),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        document = record(args.output.resolve())
    except (CaptureFailure, SaveFormatError, local_sync.VerifyFailure) as error:
        print(f"save golden capture failed: {error}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "capture_count": len(document["captures"]),
                "source_revision": document["provenance"]["source_revision"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
