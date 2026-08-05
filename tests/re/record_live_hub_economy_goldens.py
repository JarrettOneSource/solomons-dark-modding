#!/usr/bin/env python3
"""Record the retail hub/economy and Solomon Dig webgame goldens.

This recorder launches only isolated ``hub-*`` stages.  Rolled stock is never
seeded through ``sd.rng``: the recorder traces the retail seed and integer
primitives, correlates their ``this`` pointer with the active native stream,
and preserves the complete stream state around every Dowsing roll.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Callable


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

from owned_process_ledger import (  # noqa: E402
    OWNED_GAME_PROCESSES,
    OwnedProcessError,
    register_owned_launch,
    stop_owned_process_ids,
)
import verify_local_multiplayer_sync as local_sync  # noqa: E402


POWERSHELL = Path(
    "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
)
LAUNCH_SCRIPT = ROOT / "scripts" / "Launch-LocalSoloSession.ps1"
LAUNCHER = ROOT / "dist" / "launcher" / "SolomonDarkModLauncher.exe"
GAME_DIRECTORY = Path(
    "/mnt/c/Users/User/Documents/GitHub/SB Modding/"
    "Solomon Dark/SolomonDarkAbandonware"
)
RUNTIME_ROOT = ROOT / "runtime" / "hubre"
RAW_OUTPUT = RUNTIME_ROOT / "hub-economy-live-raw.json"
DEFAULT_OUTPUT = ROOT / "tests" / "fixtures" / "webgame" / "hub-economy-goldens.json"
FACTORY_CATALOG = ROOT / "docs" / "reverse-engineering" / "native-factory-catalog.json"
HAGATHA_CATALOG = ROOT / "docs" / "reverse-engineering" / "native-hagatha-perk-catalog.json"

ALLOWED_PORTS = tuple(range(52311, 52319))
TRIAL_COUNT = 8
TRADER_CAPTURE_COUNT = 3
DOWSING_ROLLS_PER_CAPTURE = 8
APP_TICK_SEED_MULTIPLIER = 0xEF3

NATIVE_RNG_SEED = 0x00401120
NATIVE_RNG_INTEGER = 0x00401170
NATIVE_RNG_FLOAT = 0x00401310
NATIVE_STOCK_GENERATOR = 0x005C8960
NATIVE_HAGATHA_PRICE = 0x005A7CA0
HUB_SERVICE_DISPATCH = 0x00514A20
DOWSING_ACTION = 0x0055FAF0
SHOP_ADD_OFFER = 0x0055ACB0
GAMEPLAY_GLOBAL = 0x0081C264
ACTIVE_RNG_POINTER = 0x00818B08
APP_GLOBAL = 0x00B401A8
PROFILE_POINTER = 0x008199CC
PROFILE_GOLD = 0x0081A388
PROFILE_FIRST_MIXED_FLAGS = 0x0081A39C
DOWSING_COST = 0x0081A430

FOMENTIUS_STOCK_OFFSET = 0x15A4
HAGATHA_STOCK_OFFSET = 0x15FC
PROGRESSION_HANDLE_OFFSET = 0x1654
HUB_SURFACE_OFFSET = 0x15A0
SHLORIO_ACTION_OFFSET = 0x1238
INVENTORY_SCREEN_SHOP_OFFSET = 0x160
DOWSING_BUTTON_OFFSET = 0x290
DOWSING_DONE_OFFSET = 0x1D4
DOWSING_TARGET_OFFSET = 0x344
DOWSING_RESULT_COUNT_OFFSET = 0x350
DOWSING_RESULT_ARRAY_OFFSET = 0x35C

RNG_STOCK_RETURNS = {
    0x005C89B4,
    0x005C8A33,
    0x005C8AB2,
    0x005C8B31,
    0x005C8BA9,
    0x005C8C1A,
    0x005C8C9F,
    0x005C8D24,
    0x005C8D97,
}
DOWSING_INTEGER_RETURNS = {0x00554A94, 0x0055FE2A, 0x0055FE8E}
DOWSING_FLOAT_RETURN = 0x0055FDE9
REWARD_ACTOR_TYPES = {0x7DB, 0x7DC, 0x7DD, 0x7F6}

PROGRESSION_STATES = (
    {
        "id": "fresh",
        "first_mixed_selectors": (),
        "owned_selectors": (),
    },
    {
        "id": "life_charm_previously_mixed",
        "first_mixed_selectors": (0,),
        "owned_selectors": (),
    },
    {
        "id": "last_word_owned",
        "first_mixed_selectors": (12,),
        "owned_selectors": (12,),
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


def as_float(value: object, default: float = math.nan) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def parse_key_values(output: str) -> dict[str, str]:
    return local_sync.parse_key_values(output)


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
    require(completed.returncode == 0, f"git {' '.join(arguments)} failed: {completed.stdout}")
    return completed.stdout.strip()


def windows_path(path: Path) -> str:
    return local_sync.path_for_powershell(path)


def windows_sha256(path: Path) -> str:
    literal_path = windows_path(path).replace("'", "''")
    completed = subprocess.run(
        [
            str(POWERSHELL),
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f"(Get-FileHash -LiteralPath '{literal_path}' -Algorithm SHA256).Hash.ToLowerInvariant()",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30.0,
        check=False,
    )
    value = completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else ""
    require(completed.returncode == 0 and len(value) == 64, f"Windows hash failed for {path}: {completed.stdout}")
    return value


def snapshot_hub_processes() -> list[dict[str, Any]]:
    script = r"""
$root = [System.IO.Path]::GetFullPath('C:\sd-hubre-20260805\runtime\hubre\instances\')
$rows = @(
  Get-CimInstance Win32_Process -Filter "Name = 'SolomonDark.exe'" |
    Where-Object {
      $_.ExecutablePath -and
      [System.IO.Path]::GetFullPath($_.ExecutablePath).StartsWith(
        $root, [System.StringComparison]::OrdinalIgnoreCase)
    } |
    Select-Object @{n='process_id';e={[int]$_.ProcessId}},
                  @{n='executable_path';e={[string]$_.ExecutablePath}}
)
if ($rows.Count -eq 0) { '[]' } else { $rows | ConvertTo-Json -Compress }
"""
    completed = subprocess.run(
        [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30.0,
        check=False,
    )
    require(completed.returncode == 0, f"process snapshot failed: {completed.stdout}")
    parsed = json.loads(completed.stdout.strip().lstrip("\ufeff") or "[]")
    if isinstance(parsed, dict):
        return [parsed]
    require(isinstance(parsed, list), f"unexpected process snapshot: {parsed!r}")
    return parsed


def load_type_names() -> dict[int, str]:
    document = json.loads(FACTORY_CATALOG.read_text(encoding="utf-8"))
    rows = document.get("types")
    require(isinstance(rows, list) and rows, "factory catalog contains no types")
    result: dict[int, str] = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("type_id"), int):
            result[int(row["type_id"])] = str(row.get("class") or "Unknown")
    for witness in (1, 5001, 5009, 5010):
        require(witness in result, f"factory catalog is missing type {witness}")
    return result


def wait_until(
    description: str,
    producer: Callable[[], Any],
    predicate: Callable[[Any], bool],
    *,
    timeout: float,
    interval: float = 0.1,
) -> Any:
    deadline = time.monotonic() + timeout
    last: Any = None
    last_error = ""
    while time.monotonic() < deadline:
        try:
            last = producer()
            if predicate(last):
                return last
        except Exception as exc:  # surfaced with the last busy/readiness reason
            last_error = f"{type(exc).__name__}: {exc}"
        time.sleep(interval)
    raise CaptureFailure(
        f"BUSY_TIMEOUT: {description}; last={last!r}; last_error={last_error}"
    )


class OwnedSoloSession:
    def __init__(self, instance: str, local_port: int, unused_port: int) -> None:
        require(instance.startswith("hub-"), f"instance is outside hub-* scope: {instance}")
        require(local_port in ALLOWED_PORTS, f"local port is outside G8 range: {local_port}")
        require(unused_port in ALLOWED_PORTS, f"remote port is outside G8 range: {unused_port}")
        require(local_port != unused_port, "local and unused ports must differ")
        self.instance = instance
        self.local_port = local_port
        self.unused_port = unused_port
        self.pipe_name = f"SolomonDarkModLoader_LuaExec_{instance}"
        self.process_ids: list[int] = []
        self.launch_result: dict[str, Any] | None = None

    @property
    def instance_root(self) -> Path:
        return RUNTIME_ROOT / "instances" / self.instance.lower()

    @property
    def stage_root(self) -> Path:
        return self.instance_root / "stage"

    @property
    def loader_log(self) -> Path:
        return self.stage_root / ".sdmod" / "logs" / "solomondarkmodloader.log"

    def launch(self, *, quick_start: bool) -> dict[str, Any]:
        require(self.launch_result is None, "session has already launched")
        require(POWERSHELL.is_file(), f"PowerShell is not runnable: {POWERSHELL}")
        require(LAUNCH_SCRIPT.is_file(), f"solo launcher script is missing: {LAUNCH_SCRIPT}")
        require(LAUNCHER.is_file(), f"built launcher is missing: {LAUNCHER}")
        require(GAME_DIRECTORY.is_dir(), f"retail game directory is missing: {GAME_DIRECTORY}")

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
            f"0x200000000000{self.local_port & 0xFFFF:04X}",
            "-PlayerName",
            f"G8 {self.instance}",
            "-GameDirectory",
            windows_path(GAME_DIRECTORY),
            "-LauncherPath",
            windows_path(LAUNCHER),
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
        if quick_start:
            arguments.extend(
                [
                    "-QuickStart",
                    "-QuickStartElement",
                    "water",
                    "-QuickStartDiscipline",
                    "arcane",
                ]
            )

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
                        f"BROKEN: launcher exited {return_code} before publishing a result: {message[-4000:]}"
                    )
                time.sleep(0.1)
            require(result_path.is_file(), "BUSY_TIMEOUT: launcher did not publish its result")
            result = json.loads(result_path.read_text(encoding="utf-8-sig"))
            require(isinstance(result, dict), "BROKEN: launcher result is not an object")
            require(result.get("success") is True, f"BROKEN: launcher failed: {result}")
            require(result.get("audioDisabled") is True, f"BROKEN: audio was not disabled: {result}")
            require(result.get("headlessEnabled") is True, f"BROKEN: launch is not headless: {result}")
            require(as_int(result.get("localPort")) == self.local_port, f"BROKEN: wrong UDP port: {result}")
            identities = register_owned_launch(result)
            self.process_ids = [identity.process_id for identity in identities]
            require(len(self.process_ids) == 1, f"BROKEN: expected one owned process: {identities}")
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

    def assert_process_runnable(self) -> None:
        inspections = OWNED_GAME_PROCESSES.inspect()
        ours = [row for row in inspections if as_int(row.get("processId")) in self.process_ids]
        require(len(ours) == len(self.process_ids), f"BROKEN: owned process disappeared: {inspections}")
        bad = [
            row
            for row in ours
            if row.get("alreadyExited") or not row.get("pathMatched")
        ]
        require(not bad, f"BROKEN: owned process is not runnable at its staged path: {bad}")

    def wait_for_pipe(self, timeout: float = 120.0) -> None:
        deadline = time.monotonic() + timeout
        last_busy = ""
        while time.monotonic() < deadline:
            self.assert_process_runnable()
            try:
                output = self.lua("return 'ready'", timeout=5.0)
                if output.strip() == "ready":
                    return
                last_busy = f"unexpected readiness output: {output!r}"
            except (local_sync.VerifyFailure, subprocess.TimeoutExpired) as exc:
                message = str(exc)
                if "busy" in message.lower() or "pipe" in message.lower():
                    last_busy = message
                else:
                    raise CaptureFailure(f"BROKEN: Lua exec invocation failed: {message}") from exc
            time.sleep(0.25)
        raise CaptureFailure(f"BUSY_TIMEOUT: Lua pipe never became runnable: {last_busy}")

    def lua(self, code: str, *, timeout: float = 15.0) -> str:
        return local_sync.lua(self.pipe_name, code, timeout=timeout)

    def values(self, code: str, *, timeout: float = 15.0) -> dict[str, str]:
        return parse_key_values(self.lua(code, timeout=timeout))

    def close(self) -> list[dict[str, Any]]:
        process_ids = list(self.process_ids)
        self.process_ids.clear()
        try:
            if not process_ids:
                return []
            return stop_owned_process_ids(process_ids)
        finally:
            local_sync._kill_lua_daemon(self.pipe_name)

    def tail_log(self, limit: int = 160) -> list[str]:
        if not self.loader_log.is_file():
            return []
        return self.loader_log.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]


def surface_state(session: OwnedSoloSession) -> dict[str, str]:
    return session.values(
        r"""
local scene = sd.world and sd.world.get_scene and sd.world.get_scene() or {}
local snap = sd.ui and sd.ui.get_snapshot and sd.ui.get_snapshot() or {}
local rows = {
  'scene=' .. tostring(scene.name or scene.kind or ''),
  'transitioning=' .. tostring(scene.transitioning or false),
  'region_index=' .. tostring(scene.region_index or -1),
  'region_type_id=' .. tostring(scene.region_type_id or -1),
  'surface=' .. tostring(snap.surface_id or ''),
  'player_available=' .. tostring(
    sd.player and sd.player.get_state and sd.player.get_state() ~= nil or false),
}
return table.concat(rows, '\n')
"""
    )


def wait_for_surface(session: OwnedSoloSession, names: set[str], timeout: float) -> dict[str, str]:
    return wait_until(
        f"surface {sorted(names)}",
        lambda: surface_state(session),
        lambda row: row.get("surface") in names,
        timeout=timeout,
        interval=0.1,
    )


def wait_for_hub(session: OwnedSoloSession, timeout: float = 180.0) -> dict[str, str]:
    return wait_until(
        "settled hub",
        lambda: surface_state(session),
        lambda row: (
            row.get("scene") == "hub"
            and row.get("transitioning") == "false"
            and row.get("player_available") == "true"
        ),
        timeout=timeout,
        interval=0.15,
    )


def activate_action(session: OwnedSoloSession, action: str, surface: str) -> dict[str, str]:
    values = session.values(
        f"""
local ok, result = sd.ui.activate_action({json.dumps(action)}, {json.dumps(surface)})
print('ok=' .. tostring(ok))
print('result=' .. tostring(result))
"""
    )
    require(values.get("ok") == "true", f"semantic UI action failed: {surface}:{action}: {values}")
    return values


def dismiss_startup_dialogs(session: OwnedSoloSession) -> None:
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        state = surface_state(session)
        if state.get("surface") == "main_menu":
            return
        if state.get("surface") == "control_scheme_picker":
            activate_action(
                session,
                "control_scheme_picker.select_wasd",
                "control_scheme_picker",
            )
        elif state.get("surface") == "dialog":
            activate_action(session, "dialog.primary", "dialog")
        else:
            time.sleep(0.1)
    raise CaptureFailure(f"BUSY_TIMEOUT: startup did not reach main_menu: {surface_state(session)}")


def arm_stock_traces(session: OwnedSoloSession) -> dict[str, str]:
    values = session.values(
        f"""
local targets = {{
  {{{NATIVE_RNG_SEED}, 'g8_seed'}},
  {{{NATIVE_RNG_INTEGER}, 'g8_integer'}},
  {{{NATIVE_STOCK_GENERATOR}, 'g8_stock'}},
}}
for _, target in ipairs(targets) do
  pcall(sd.debug.untrace_function, target[1])
  sd.debug.clear_trace_hits(target[2])
end
for _, target in ipairs(targets) do
  local ok = sd.debug.trace_function(target[1], target[2])
  print(target[2] .. '=' .. tostring(ok))
  print(target[2] .. '_error=' .. tostring(sd.debug.get_last_error() or ''))
end
"""
    )
    for name in ("g8_seed", "g8_integer", "g8_stock"):
        require(values.get(name) == "true", f"BROKEN: could not arm {name}: {values}")
    return values


def trace_count(session: OwnedSoloSession, name: str) -> int:
    return as_int(
        session.values(
            f"local h=sd.debug.get_trace_hits({json.dumps(name)}) or {{}}; print('count='..tostring(#h))"
        ).get("count")
    )


def rng_snapshot_lua(prefix: str) -> str:
    return f"""
local active_slot = sd.debug.resolve_game_address({ACTIVE_RNG_POINTER}) or 0
local stream = active_slot ~= 0 and (sd.debug.read_ptr(active_slot) or 0) or 0
local words = {{}}
if stream ~= 0 then
  for index = 0, 54 do
    words[#words + 1] = tostring(sd.debug.read_u32(stream + 8 + index * 4) or 0)
  end
end
print('{prefix}.stream=' .. tostring(stream))
print('{prefix}.index_a=' .. tostring(stream ~= 0 and (sd.debug.read_i32(stream) or -1) or -1))
print('{prefix}.index_b=' .. tostring(stream ~= 0 and (sd.debug.read_i32(stream + 4) or -1) or -1))
print('{prefix}.divisor=' .. tostring(stream ~= 0 and (sd.debug.read_u32(stream + 0xE4) or 0) or 0))
print('{prefix}.words=' .. table.concat(words, ','))
"""


def parse_rng(values: dict[str, str], prefix: str) -> dict[str, Any]:
    words_text = values.get(f"{prefix}.words", "")
    words = [as_int(piece) for piece in words_text.split(",") if piece != ""]
    require(len(words) == 55, f"{prefix} did not expose all 55 RNG words: {values}")
    result = {
        "stream": as_int(values.get(f"{prefix}.stream")),
        "index_a": as_int(values.get(f"{prefix}.index_a"), -1),
        "index_b": as_int(values.get(f"{prefix}.index_b"), -1),
        "divisor": as_int(values.get(f"{prefix}.divisor")),
        "state_words": words,
    }
    require(result["stream"] != 0, f"{prefix} active stream is null")
    require(result["divisor"] == 100000, f"{prefix} RNG divisor is not native 100000: {result}")
    return result


def pre_generation_state(session: OwnedSoloSession) -> dict[str, Any]:
    values = session.values(
        rng_snapshot_lua("rng")
        + f"""
local app_slot = sd.debug.resolve_game_address({APP_GLOBAL}) or 0
local app = app_slot ~= 0 and (sd.debug.read_ptr(app_slot) or 0) or 0
print('app_ticks=' .. tostring(app ~= 0 and (sd.debug.read_u32(app + 0x28) or 0) or 0))
"""
    )
    return {"rng": parse_rng(values, "rng"), "app_ticks": as_int(values.get("app_ticks"))}


def apply_progression_state(
    session: OwnedSoloSession,
    progression_state: dict[str, Any],
) -> dict[str, Any]:
    first_mixed = set(int(value) for value in progression_state["first_mixed_selectors"])
    owned = set(int(value) for value in progression_state["owned_selectors"])
    first_mixed_literal = "{" + ",".join(f"[{value}]=true" for value in sorted(first_mixed)) + "}"
    owned_literal = "{" + ",".join(f"[{value}]=true" for value in sorted(owned)) + "}"
    output = session.values(
        f"""
local first_mixed = {first_mixed_literal}
local owned = {owned_literal}
local profile_flags = sd.debug.resolve_game_address({PROFILE_FIRST_MIXED_FLAGS}) or 0
local game_slot = sd.debug.resolve_game_address({GAMEPLAY_GLOBAL}) or 0
local game = game_slot ~= 0 and (sd.debug.read_ptr(game_slot) or 0) or 0
local progression_handle = game ~= 0 and (sd.debug.read_ptr(game + {PROGRESSION_HANDLE_OFFSET}) or 0) or 0
local progression = progression_handle ~= 0 and (sd.debug.read_ptr(progression_handle) or 0) or 0
print('game=' .. tostring(game))
print('progression=' .. tostring(progression))
print('profile_flags=' .. tostring(profile_flags))
local ok = profile_flags ~= 0 and progression ~= 0
for selector = 0, 27 do
  ok = sd.debug.write_u8(profile_flags + selector, first_mixed[selector] and 1 or 0) and ok
  ok = sd.debug.write_u8(progression + 0x7CC + selector, owned[selector] and 1 or 0) and ok
end
print('write_ok=' .. tostring(ok))
local profile_slot = sd.debug.resolve_game_address({PROFILE_POINTER}) or 0
local profile = profile_slot ~= 0 and (sd.debug.read_ptr(profile_slot) or 0) or 0
print('profile=' .. tostring(profile))
print('perk_catalog_limit=' .. tostring(profile ~= 0 and (sd.debug.read_i32(profile + 0xF0C) or 0) or 0))
local mixed_rows = {{}}
local owned_rows = {{}}
for selector = 0, 27 do
  if sd.debug.read_u8(profile_flags + selector) == 1 then mixed_rows[#mixed_rows + 1] = tostring(selector) end
  if sd.debug.read_u8(progression + 0x7CC + selector) == 1 then owned_rows[#owned_rows + 1] = tostring(selector) end
end
print('first_mixed=' .. table.concat(mixed_rows, ','))
print('owned=' .. table.concat(owned_rows, ','))
"""
    )
    require(output.get("write_ok") == "true", f"controlled progression setup failed: {output}")
    require(as_int(output.get("profile")) != 0, f"profile pointer did not resolve: {output}")
    catalog_limit = as_int(output.get("perk_catalog_limit"))
    require(2 <= catalog_limit <= 29, f"native perk catalog limit is out of range: {output}")
    observed_mixed = tuple(as_int(value) for value in output.get("first_mixed", "").split(",") if value)
    observed_owned = tuple(as_int(value) for value in output.get("owned", "").split(",") if value)
    require(observed_mixed == tuple(sorted(first_mixed)), f"first-mixed setup did not stick: {output}")
    require(observed_owned == tuple(sorted(owned)), f"owned setup did not stick: {output}")
    return {
        "id": progression_state["id"],
        "perk_catalog_limit": catalog_limit,
        "first_mixed_selectors": list(observed_mixed),
        "owned_selectors": list(observed_owned),
    }


def drive_new_game(
    session: OwnedSoloSession,
    progression_state: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    deadline = time.monotonic() + 180.0
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = surface_state(session)
        if (
            last.get("scene") == "hub"
            and last.get("transitioning") == "false"
            and last.get("player_available") == "true"
        ):
            break
        if last.get("surface") == "control_scheme_picker":
            activate_action(
                session,
                "control_scheme_picker.select_wasd",
                "control_scheme_picker",
            )
        time.sleep(0.1)
    else:
        raise CaptureFailure(f"BUSY_TIMEOUT: UI sandbox did not reach a settled hub: {last}")
    applied = apply_progression_state(session, progression_state)
    time.sleep(0.5)
    arm_stock_traces(session)
    before = pre_generation_state(session)
    replay = session.values(
        f"""
local slot=sd.debug.resolve_game_address({GAMEPLAY_GLOBAL}) or 0
local game=slot~=0 and (sd.debug.read_ptr(slot) or 0) or 0
local target=sd.debug.resolve_game_address({NATIVE_STOCK_GENERATOR}) or 0
local result=game~=0 and target~=0 and sd.debug.call_thiscall_ret_u32(target, game) or nil
print('game='..tostring(game))
print('target='..tostring(target))
print('called='..tostring(result~=nil))
print('result='..tostring(result))
""",
        timeout=20.0,
    )
    require(replay.get("called") == "true", f"native stock generator replay was not callable: {replay}")
    require(trace_count(session, "g8_stock") == 1, "native stock generator replay did not produce exactly one entry trace")
    trace_values = collect_stock_traces(session)
    trace_values["capture_replay"] = "existing sd.debug.call_thiscall_ret_u32 against live Game"
    return applied, before, trace_values


def collect_stock_traces(session: OwnedSoloSession) -> dict[str, str]:
    return session.values(
        f"""
local base = sd.debug.resolve_game_address(0x00400000) or 0x00400000
local delta = base - 0x00400000
local active_slot = sd.debug.resolve_game_address({ACTIVE_RNG_POINTER}) or 0
local active = active_slot ~= 0 and (sd.debug.read_ptr(active_slot) or 0) or 0
print('active_stream=' .. tostring(active))
local names = {{'g8_seed', 'g8_integer', 'g8_stock'}}
for _, name in ipairs(names) do
  local hits = sd.debug.get_trace_hits(name) or {{}}
  print(name .. '.count=' .. tostring(#hits))
  for index, hit in ipairs(hits) do
    local prefix = name .. '.' .. tostring(index) .. '.'
    print(prefix .. 'ecx=' .. tostring(hit.ecx or 0))
    print(prefix .. 'arg0=' .. tostring(hit.arg0 or 0))
    print(prefix .. 'arg1=' .. tostring(hit.arg1 or 0))
    print(prefix .. 'ret=' .. tostring((hit.ret or 0) - delta))
  end
end
pcall(sd.debug.untrace_function, {NATIVE_RNG_SEED})
pcall(sd.debug.untrace_function, {NATIVE_RNG_INTEGER})
pcall(sd.debug.untrace_function, {NATIVE_STOCK_GENERATOR})
"""
    )


def parse_trace_hits(values: dict[str, str], name: str) -> list[dict[str, int]]:
    count = as_int(values.get(f"{name}.count"))
    return [
        {
            "ecx": as_int(values.get(f"{name}.{index}.ecx")),
            "arg0": as_int(values.get(f"{name}.{index}.arg0")),
            "arg1": as_int(values.get(f"{name}.{index}.arg1")),
            "return_address": as_int(values.get(f"{name}.{index}.ret")),
        }
        for index in range(1, count + 1)
    ]


def normalized_rng(rng: dict[str, Any]) -> dict[str, Any]:
    return {
        "index_a": rng["index_a"],
        "index_b": rng["index_b"],
        "divisor": rng["divisor"],
        "state_words": rng["state_words"],
    }


def stock_seed_evidence(
    trace_values: dict[str, str],
    before: dict[str, Any],
) -> dict[str, Any]:
    active_stream = as_int(trace_values.get("active_stream"))
    require(active_stream == before["rng"]["stream"], "stock generator changed active RNG stream before its nine rolls")
    integer_hits = [
        hit
        for hit in parse_trace_hits(trace_values, "g8_integer")
        if hit["return_address"] in RNG_STOCK_RETURNS
    ]
    require(len(integer_hits) == 9, f"Fomentius generation did not consume exactly nine identified Integer calls: {integer_hits}")
    require(
        all(hit["ecx"] == active_stream for hit in integer_hits),
        f"Fomentius generation consumed a stream other than the active native stream: {integer_hits}",
    )
    seed_hits = [
        hit
        for hit in parse_trace_hits(trace_values, "g8_seed")
        if hit["ecx"] == active_stream
    ]
    matching = [
        hit
        for hit in seed_hits
        if hit["arg0"] % APP_TICK_SEED_MULTIPLIER == 0
    ]
    construction_tick = (
        matching[-1]["arg0"] // APP_TICK_SEED_MULTIPLIER
        if matching
        else None
    )
    portable_state = normalized_rng(before["rng"])
    state_sha256 = hashlib.sha256(
        json.dumps(portable_state, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "stream_identity_proven": True,
        "integer_call_count": len(integer_hits),
        "integer_return_addresses": [
            f"0x{hit['return_address']:08X}" for hit in integer_hits
        ],
        "integer_requests": [hit["arg0"] for hit in integer_hits],
        "seed_trace_hit_count_for_active_stream": len(seed_hits),
        "construction_seed": matching[-1]["arg0"] if matching else None,
        "construction_app_tick": construction_tick,
        "construction_seed_matches_tick_times_0xEF3": bool(matching),
        "portable_from_seed_alone": bool(matching),
        "app_ticks_immediately_before_generation": before["app_ticks"],
        "state_immediately_before_generation": portable_state,
        "state_sha256": state_sha256,
    }


def parse_item_rows(
    values: dict[str, str],
    prefix: str,
    *,
    include_type_specific: bool = False,
) -> list[dict[str, int]]:
    count = as_int(values.get(f"{prefix}.count"))
    rows: list[dict[str, int]] = []
    for index in range(1, count + 1):
        row_prefix = f"{prefix}.{index}"
        row = {
            "type_id": as_int(values.get(f"{row_prefix}.type_id")),
            "recipe_uid": as_int(values.get(f"{row_prefix}.recipe_uid")),
            "variant_id": as_int(values.get(f"{row_prefix}.variant_id"), -1),
            "price": as_int(values.get(f"{row_prefix}.price")),
            "_runtime_pointer": as_int(values.get(f"{row_prefix}.pointer")),
        }
        if include_type_specific:
            row["type_specific_0x88"] = as_int(
                values.get(f"{row_prefix}.type_specific_0x88")
            )
        rows.append(row)
    return rows


def aggregate_stock_rows(rows: list[dict[str, int]]) -> list[dict[str, int]]:
    grouped: dict[tuple[int, int, int, int], dict[str, int]] = {}
    for row in rows:
        key = (
            row["type_id"],
            row["recipe_uid"],
            row["variant_id"],
            row["price"],
        )
        grouped.setdefault(
            key,
            {
                "type_id": row["type_id"],
                "recipe_uid": row["recipe_uid"],
                "variant_id": row["variant_id"],
                "price": row["price"],
                "quantity": 0,
            },
        )["quantity"] += 1
    return list(grouped.values())


def summarize_hagatha_rows(rows: list[dict[str, int]]) -> dict[str, Any]:
    visible: list[dict[str, int]] = []
    placeholder_count = 0
    for row in rows:
        if row["type_id"] == 7000:
            placeholder_count += 1
            continue
        require(
            row["type_id"] == 7009,
            f"Hagatha stock contained neither a perk nor an owned-offer placeholder: {row}",
        )
        visible.append(
            {
                "selector": row["type_specific_0x88"],
                "price": row["price"],
                "quantity": 1,
                "type_id": row["type_id"],
            }
        )
    selectors = [row["selector"] for row in visible]
    require(
        len(selectors) == len(set(selectors)),
        f"Hagatha stock exposed duplicate perk selectors: {selectors}",
    )
    return {
        "stock_count": len(rows),
        "visible_offer_count": len(visible),
        "owned_offer_placeholder_count": placeholder_count,
        "offers": sorted(visible, key=lambda row: row["selector"]),
    }


def assert_hagatha_prices(
    summary: dict[str, Any],
    progression: dict[str, Any],
) -> None:
    catalog = json.loads(HAGATHA_CATALOG.read_text(encoding="utf-8"))
    base_prices = {int(row["selector"]): int(row["price"]) for row in catalog["perks"]}
    first_mixed = set(progression["first_mixed_selectors"])
    for offer in summary["offers"]:
        selector = offer["selector"]
        require(selector in base_prices, f"Hagatha live selector {selector} is absent from the static perk catalog")
        expected = base_prices[selector] if selector in first_mixed else base_prices[selector] * 3
        require(
            offer["price"] == expected,
            f"Hagatha selector {selector} live price {offer['price']} did not match the native first-mix formula {expected}",
        )


def capture_trader_stock(
    session: OwnedSoloSession,
    progression: dict[str, Any],
    before: dict[str, Any],
    trace_values: dict[str, str],
) -> dict[str, Any]:
    values = session.values(
        rng_snapshot_lua("rng_after")
        + f"""
local game_slot = sd.debug.resolve_game_address({GAMEPLAY_GLOBAL}) or 0
local game = game_slot ~= 0 and (sd.debug.read_ptr(game_slot) or 0) or 0
local price_function = sd.debug.resolve_game_address({NATIVE_HAGATHA_PRICE}) or 0
local progression_handle = game ~= 0 and (sd.debug.read_ptr(game + {PROGRESSION_HANDLE_OFFSET}) or 0) or 0
local progression = progression_handle ~= 0 and (sd.debug.read_ptr(progression_handle) or 0) or 0
local price_tier = progression ~= 0 and ((sd.debug.read_i32(progression + 0x7C4) or 0) + 1) or 1
local function emit_inventory(prefix, root, native_perk_prices)
  local count = root ~= 0 and (sd.debug.read_i32(root + 0x14) or 0) or 0
  local array = root ~= 0 and (sd.debug.read_ptr(root + 0x20) or 0) or 0
  print(prefix .. '.count=' .. tostring(count))
  print(prefix .. '.array=' .. tostring(array))
  for index = 0, count - 1 do
    local item = array ~= 0 and (sd.debug.read_ptr(array + index * 4) or 0) or 0
    local key = prefix .. '.' .. tostring(index + 1)
    print(key .. '.type_id=' .. tostring(item ~= 0 and (sd.debug.read_i32(item + 0x08) or 0) or 0))
    print(key .. '.recipe_uid=' .. tostring(item ~= 0 and (sd.debug.read_i32(item + 0x18) or 0) or 0))
    print(key .. '.variant_id=' .. tostring(item ~= 0 and (sd.debug.read_i32(item + 0x1C) or -1) or -1))
    local type_id = item ~= 0 and (sd.debug.read_i32(item + 0x08) or 0) or 0
    local type_specific = item ~= 0 and (sd.debug.read_i32(item + 0x88) or 0) or 0
    local price = item ~= 0 and (sd.debug.read_i32(item + 0x5C) or 0) or 0
    if native_perk_prices and type_id == 7009 then
      price = sd.debug.call_stdcall_u32_u32_ret_u32(price_function, type_specific, price_tier)
    end
    print(key .. '.price=' .. tostring(price or -1))
    print(key .. '.type_specific_0x88=' .. tostring(type_specific))
  end
end
emit_inventory('fomentius', game ~= 0 and game + {FOMENTIUS_STOCK_OFFSET} or 0, false)
emit_inventory('hagatha', game ~= 0 and game + {HAGATHA_STOCK_OFFSET} or 0, true)
local app_slot = sd.debug.resolve_game_address({APP_GLOBAL}) or 0
local app = app_slot ~= 0 and (sd.debug.read_ptr(app_slot) or 0) or 0
print('app_ticks_after=' .. tostring(app ~= 0 and (sd.debug.read_u32(app + 0x28) or 0) or 0))
print('gold=' .. tostring(sd.debug.read_i32(sd.debug.resolve_game_address({PROFILE_GOLD}) or 0) or 0))
print('dowsing_cost=' .. tostring(sd.debug.read_i32(sd.debug.resolve_game_address({DOWSING_COST}) or 0) or 0))
"""
    )
    rng_after = parse_rng(values, "rng_after")
    fomentius = parse_item_rows(values, "fomentius", include_type_specific=True)
    hagatha = parse_item_rows(values, "hagatha", include_type_specific=True)
    require(len(fomentius) >= 6, f"Fomentius stock was unexpectedly sparse: {fomentius}")
    require(len(hagatha) >= 20, f"Hagatha catalog was unexpectedly sparse: {len(hagatha)}")
    hagatha_summary = summarize_hagatha_rows(hagatha)
    assert_hagatha_prices(hagatha_summary, progression)
    return {
        "progression_state": progression,
        "profile_gold": as_int(values.get("gold")),
        "dowsing_cost_before_first_roll": as_int(values.get("dowsing_cost")),
        "seed_evidence": stock_seed_evidence(trace_values, before),
        "rng_state_after_generation": normalized_rng(rng_after),
        "app_ticks_after_capture": as_int(values.get("app_ticks_after")),
        "fomentius": {
            "stock_count": len(fomentius),
            "offers": aggregate_stock_rows(fomentius),
        },
        "hagatha": {
            **hagatha_summary,
            "price_source_function": "0x005A7CA0",
            "price_capture_seam": "sd.debug.call_stdcall_u32_u32_ret_u32",
        },
    }


REGION_NAMES = {
    0: "Courtyard",
    1: "Mortuary",
    2: "Library",
    3: "StoreRoom",
    4: "Office",
}
REGION_TYPE_IDS = {0: 4001, 1: 4002, 2: 4004, 3: 4003, 4: 4005}


def switch_region(session: OwnedSoloSession, region_index: int) -> None:
    values = session.values(
        f"print('ok=' .. tostring(sd.scene.switch_region({region_index})))"
    )
    require(values.get("ok") == "true", f"region {region_index} switch was rejected: {values}")
    wait_until(
        f"hub region {region_index}",
        lambda: surface_state(session),
        lambda row: (
            row.get("transitioning") == "false"
            and as_int(row.get("region_index"), -1) == region_index
        ),
        timeout=45.0,
        interval=0.1,
    )
    time.sleep(1.0)


def capture_region_census(
    session: OwnedSoloSession,
    region_index: int,
    type_names: dict[int, str],
) -> dict[str, Any]:
    switch_region(session, region_index)
    values = session.values(
        r"""
local scene = sd.world.get_scene() or {}
local actors = sd.world.list_actors() or {}
print('region_index=' .. tostring(scene.region_index or -1))
print('region_type_id=' .. tostring(scene.region_type_id or -1))
print('actor_count=' .. tostring(#actors))
for index, actor in ipairs(actors) do
  local key = 'actor.' .. tostring(index)
  print(key .. '.type_id=' .. tostring(actor.object_type_id or 0))
  print(key .. '.world_slot=' .. tostring(actor.world_slot or -1))
  print(key .. '.x=' .. string.format('%.3f', tonumber(actor.x) or 0))
  print(key .. '.y=' .. string.format('%.3f', tonumber(actor.y) or 0))
  print(key .. '.radius=' .. string.format('%.3f', tonumber(actor.radius) or 0))
  if actor.object_type_id == 5018 then
    local address = tonumber(actor.actor_address) or 0
    print(key .. '.eulogy_index=' .. tostring(address ~= 0 and (sd.debug.read_i32(address + 0x174) or -1) or -1))
  end
end
"""
    )
    actor_count = as_int(values.get("actor_count"))
    actors: list[dict[str, Any]] = []
    for index in range(1, actor_count + 1):
        prefix = f"actor.{index}"
        type_id = as_int(values.get(f"{prefix}.type_id"))
        actor = {
            "type_id": type_id,
            "class": type_names.get(type_id, "Unknown"),
            "world_slot": as_int(values.get(f"{prefix}.world_slot"), -1),
            "x": round(as_float(values.get(f"{prefix}.x"), 0.0), 3),
            "y": round(as_float(values.get(f"{prefix}.y"), 0.0), 3),
            "radius": round(as_float(values.get(f"{prefix}.radius"), 0.0), 3),
        }
        if type_id == 5018:
            actor["eulogy_index"] = as_int(values.get(f"{prefix}.eulogy_index"), -1)
        actors.append(actor)
    counts = Counter(actor["type_id"] for actor in actors)
    region_type_id = as_int(values.get("region_type_id"), -1)
    require(
        region_type_id == REGION_TYPE_IDS[region_index],
        f"hub region {region_index} resolved to type {region_type_id}, not {REGION_TYPE_IDS[region_index]}",
    )
    return {
        "region_index": region_index,
        "region_type_id": region_type_id,
        "name": REGION_NAMES[region_index],
        "actor_count": actor_count,
        "type_counts": {
            str(type_id): {
                "class": type_names.get(type_id, "Unknown"),
                "count": count,
            }
            for type_id, count in sorted(counts.items())
        },
        "actors": actors,
    }


def capture_hub_census(
    session: OwnedSoloSession,
    type_names: dict[int, str],
) -> dict[str, Any]:
    regions = [capture_region_census(session, index, type_names) for index in REGION_NAMES]
    return {
        "capture_method": "sd.scene.switch_region plus sd.world.list_actors live retail snapshots",
        "regions": regions,
    }


def open_dowsing_surface(session: OwnedSoloSession) -> dict[str, int]:
    switch_region(session, 0)
    values = session.values(
        f"""
local surface = sd.hub.get_surface_state()
local dispatch = sd.debug.resolve_game_address({HUB_SERVICE_DISPATCH}) or 0
local gameplay = tonumber(surface and surface.gameplay_address) or 0
local courtyard = tonumber(surface and surface.courtyard_address) or 0
local result = nil
if dispatch ~= 0 and gameplay ~= 0 and courtyard ~= 0 then
  result = sd.debug.call_thiscall_u32(dispatch, courtyard, gameplay + {SHLORIO_ACTION_OFFSET})
end
print('dispatch=' .. tostring(dispatch))
print('gameplay=' .. tostring(gameplay))
print('courtyard=' .. tostring(courtyard))
print('called=' .. tostring(result ~= nil))
"""
    )
    require(values.get("called") == "true", f"native Shlorio dispatcher was not callable: {values}")
    state = wait_until(
        "Shlorio inventory surface",
        lambda: session.values(
            r"""
local s=sd.hub.get_surface_state()
print('active='..tostring(s and s.surface_active or false))
print('inventory='..tostring(s and s.inventory_screen_active or false))
print('shop_active='..tostring(s and s.inventory_shop_active or false))
print('shop='..tostring(s and s.shop_address or 0))
"""
        ),
        lambda row: (
            row.get("active") == "true"
            and row.get("inventory") == "true"
            and as_int(row.get("shop")) != 0
        ),
        timeout=15.0,
        interval=0.05,
    )
    return {
        "gameplay": as_int(values.get("gameplay")),
        "courtyard": as_int(values.get("courtyard")),
        "shop": as_int(state.get("shop")),
    }


def capture_dowsing_roll(
    session: OwnedSoloSession,
    shop: int,
    roll_index: int,
) -> dict[str, Any]:
    values = session.values(
        f"""
local integer_address = sd.debug.resolve_game_address({NATIVE_RNG_INTEGER}) or 0
local float_address = sd.debug.resolve_game_address({NATIVE_RNG_FLOAT}) or 0
pcall(sd.debug.untrace_function, {NATIVE_RNG_INTEGER})
pcall(sd.debug.untrace_function, {NATIVE_RNG_FLOAT})
pcall(sd.debug.untrace_function, {SHOP_ADD_OFFER})
sd.debug.clear_trace_hits('g8_dowse_integer')
sd.debug.clear_trace_hits('g8_dowse_float')
sd.debug.clear_trace_hits('g8_dowse_add_offer')
local integer_armed = sd.debug.trace_function({NATIVE_RNG_INTEGER}, 'g8_dowse_integer')
local float_armed = sd.debug.trace_function({NATIVE_RNG_FLOAT}, 'g8_dowse_float')
local add_offer_armed = sd.debug.trace_function({SHOP_ADD_OFFER}, 'g8_dowse_add_offer')
print('integer_armed=' .. tostring(integer_armed))
print('float_armed=' .. tostring(float_armed))
print('add_offer_armed=' .. tostring(add_offer_armed))
local active_slot = sd.debug.resolve_game_address({ACTIVE_RNG_POINTER}) or 0
local stream = active_slot ~= 0 and (sd.debug.read_ptr(active_slot) or 0) or 0
local words_before = {{}}
for index = 0, 54 do
  words_before[#words_before + 1] = tostring(sd.debug.read_u32(stream + 8 + index * 4) or 0)
end
print('before.stream=' .. tostring(stream))
print('before.index_a=' .. tostring(sd.debug.read_i32(stream) or -1))
print('before.index_b=' .. tostring(sd.debug.read_i32(stream + 4) or -1))
print('before.divisor=' .. tostring(sd.debug.read_u32(stream + 0xE4) or 0))
print('before.words=' .. table.concat(words_before, ','))
local gold_address = sd.debug.resolve_game_address({PROFILE_GOLD}) or 0
local fee_address = sd.debug.resolve_game_address({DOWSING_COST}) or 0
print('gold_before=' .. tostring(sd.debug.read_i32(gold_address) or 0))
print('fee_before=' .. tostring(sd.debug.read_i32(fee_address) or 0))
local cleared = sd.debug.write_ptr({shop} + {DOWSING_TARGET_OFFSET}, 0)
local action = sd.debug.resolve_game_address({DOWSING_ACTION}) or 0
local called = action ~= 0 and sd.debug.call_thiscall_u32(action, {shop}, {shop} + {DOWSING_BUTTON_OFFSET}) or nil
print('target_cleared=' .. tostring(cleared))
print('called=' .. tostring(called ~= nil))
local count = sd.debug.read_i32({shop} + {DOWSING_RESULT_COUNT_OFFSET}) or 0
local array = sd.debug.read_ptr({shop} + {DOWSING_RESULT_ARRAY_OFFSET}) or 0
print('offers.count=' .. tostring(count))
for index = 0, count - 1 do
  local item = array ~= 0 and (sd.debug.read_ptr(array + index * 4) or 0) or 0
  local key = 'offers.' .. tostring(index + 1)
  print(key .. '.pointer=' .. tostring(item))
  print(key .. '.type_id=' .. tostring(item ~= 0 and (sd.debug.read_i32(item + 0x08) or 0) or 0))
  print(key .. '.recipe_uid=' .. tostring(item ~= 0 and (sd.debug.read_i32(item + 0x18) or 0) or 0))
  print(key .. '.variant_id=' .. tostring(item ~= 0 and (sd.debug.read_i32(item + 0x1C) or -1) or -1))
  print(key .. '.price=' .. tostring(item ~= 0 and (sd.debug.read_i32(item + 0x5C) or 0) or 0))
end
print('gold_after=' .. tostring(sd.debug.read_i32(gold_address) or 0))
print('fee_after=' .. tostring(sd.debug.read_i32(fee_address) or 0))
local words_after = {{}}
for index = 0, 54 do
  words_after[#words_after + 1] = tostring(sd.debug.read_u32(stream + 8 + index * 4) or 0)
end
print('after.stream=' .. tostring(stream))
print('after.index_a=' .. tostring(sd.debug.read_i32(stream) or -1))
print('after.index_b=' .. tostring(sd.debug.read_i32(stream + 4) or -1))
print('after.divisor=' .. tostring(sd.debug.read_u32(stream + 0xE4) or 0))
print('after.words=' .. table.concat(words_after, ','))
local base = sd.debug.resolve_game_address(0x00400000) or 0x00400000
local delta = base - 0x00400000
for _, spec in ipairs({{{{'g8_dowse_integer', 'integer'}}, {{'g8_dowse_float', 'float'}}, {{'g8_dowse_add_offer', 'add_offer'}}}}) do
  local hits = sd.debug.get_trace_hits(spec[1]) or {{}}
  print(spec[2] .. '.count=' .. tostring(#hits))
  for index, hit in ipairs(hits) do
    local key = spec[2] .. '.' .. tostring(index)
    print(key .. '.ecx=' .. tostring(hit.ecx or 0))
    print(key .. '.arg0=' .. tostring(hit.arg0 or 0))
    print(key .. '.arg1=' .. tostring(hit.arg1 or 0))
    print(key .. '.ret=' .. tostring((hit.ret or 0) - delta))
  end
end
pcall(sd.debug.untrace_function, {NATIVE_RNG_INTEGER})
pcall(sd.debug.untrace_function, {NATIVE_RNG_FLOAT})
pcall(sd.debug.untrace_function, {SHOP_ADD_OFFER})
""",
        timeout=20.0,
    )
    require(values.get("integer_armed") == "true", f"Dowsing Integer trace did not arm: {values}")
    require(values.get("float_armed") == "true", f"Dowsing Float trace did not arm: {values}")
    require(values.get("add_offer_armed") == "true", f"Dowsing price-binding trace did not arm: {values}")
    require(values.get("target_cleared") == "true", f"Dowsing target could not be cleared: {values}")
    require(values.get("called") == "true", f"Dowsing callback was not callable: {values}")
    before = parse_rng(values, "before")
    after = parse_rng(values, "after")
    offers = parse_item_rows(values, "offers")
    require(len(offers) in (3, 4), f"Dowsing returned neither three nor four offers: {offers}")
    add_offer_hits = [
        hit
        for hit in parse_trace_hits(values, "add_offer")
        if hit["ecx"] == shop
    ]
    price_by_pointer = {hit["arg0"]: hit["arg1"] for hit in add_offer_hits}
    require(
        len(add_offer_hits) == len(offers) and len(price_by_pointer) == len(offers),
        f"Dowsing did not bind one unambiguous price to every generated offer: hits={add_offer_hits} offers={offers}",
    )
    for offer in offers:
        pointer = offer.pop("_runtime_pointer")
        require(pointer in price_by_pointer, f"Dowsing price trace did not name generated offer pointer {pointer}")
        offer["price"] = price_by_pointer[pointer]
    require(
        all(5000 <= row["price"] <= 5700 and row["price"] % 50 == 0 for row in offers),
        f"Dowsing offer escaped the native 5000..5700 by 50 price ladder: {offers}",
    )
    all_integer_hits = parse_trace_hits(values, "integer")
    all_float_hits = parse_trace_hits(values, "float")
    integer_hits = [
        hit for hit in all_integer_hits
        if hit["return_address"] in DOWSING_INTEGER_RETURNS
    ]
    float_hits = [
        hit for hit in all_float_hits
        if hit["return_address"] == DOWSING_FLOAT_RETURN
    ]
    require(integer_hits, f"Dowsing consumed no identified native Integer calls: {values}")
    require(len(float_hits) == 1, f"Dowsing did not consume exactly one Float call at 0x0055FDE9: {float_hits}")
    count_hits = [hit for hit in integer_hits if hit["return_address"] == 0x0055FE2A]
    price_hits = [hit for hit in integer_hits if hit["return_address"] == 0x0055FE8E]
    selector_hits = [hit for hit in integer_hits if hit["return_address"] == 0x00554A94]
    require(
        len(count_hits) == 1 and count_hits[0]["arg0"] == 2,
        f"Dowsing offer-count roll was not the identified Integer(2) call: {count_hits}",
    )
    require(
        len(price_hits) == len(offers) and all(hit["arg0"] == 15 for hit in price_hits),
        f"Dowsing did not issue one identified Integer(15) price roll per offer: prices={price_hits} offers={offers}",
    )
    require(
        len(selector_hits) >= len(offers) and all(hit["arg0"] == 47 for hit in selector_hits),
        f"Dowsing item selection did not use the identified Integer(47) retry path: selectors={selector_hits} offers={offers}",
    )
    require(
        all(hit["ecx"] == before["stream"] for hit in integer_hits + float_hits),
        f"Dowsing roll escaped the captured active native stream: integers={integer_hits} floats={float_hits}",
    )
    return {
        "roll_index": roll_index,
        "gold_before": as_int(values.get("gold_before")),
        "gold_after": as_int(values.get("gold_after")),
        "reroll_fee_before": as_int(values.get("fee_before")),
        "reroll_fee_after": as_int(values.get("fee_after")),
        "offers": offers,
        "rng_before": normalized_rng(before),
        "rng_after": normalized_rng(after),
        "integer_requests": [hit["arg0"] for hit in integer_hits],
        "integer_return_addresses": [
            f"0x{hit['return_address']:08X}" for hit in integer_hits
        ],
        "float_requests": [
            {"scaled_range_bits": hit["arg0"], "signed": bool(hit["arg1"])}
            for hit in float_hits
        ],
        "float_return_addresses": [
            f"0x{hit['return_address']:08X}" for hit in float_hits
        ],
        "incidental_active_stream_trace": {
            "integer_calls": [
                {
                    "request": hit["arg0"],
                    "return_address": f"0x{hit['return_address']:08X}",
                }
                for hit in all_integer_hits
                if hit not in integer_hits
            ],
            "float_calls": [
                {
                    "scaled_range_bits": hit["arg0"],
                    "signed": bool(hit["arg1"]),
                    "return_address": f"0x{hit['return_address']:08X}",
                }
                for hit in all_float_hits
                if hit not in float_hits
            ],
        },
        "price_binding_function": "0x0055ACB0",
        "all_calls_used_active_stream": True,
    }


def capture_dowsing_rolls(
    session: OwnedSoloSession,
    count: int,
) -> list[dict[str, Any]]:
    gold_values = session.values(
        f"""
local address=sd.debug.resolve_game_address({PROFILE_GOLD}) or 0
print('before='..tostring(sd.debug.read_i32(address) or 0))
print('write='..tostring(sd.debug.write_u32(address, 1000000)))
print('after='..tostring(sd.debug.read_i32(address) or 0))
"""
    )
    require(gold_values.get("write") == "true" and as_int(gold_values.get("after")) == 1000000, f"controlled Dowsing balance setup failed: {gold_values}")
    rolls: list[dict[str, Any]] = []
    for index in range(count):
        surface = open_dowsing_surface(session)
        rolls.append(capture_dowsing_roll(session, surface["shop"], index + 1))
        close_values = session.values(
            f"""
local action=sd.debug.resolve_game_address({DOWSING_ACTION}) or 0
local result=action~=0 and sd.debug.call_thiscall_u32(action, {surface['shop']}, {surface['shop']}+{DOWSING_DONE_OFFSET}) or nil
print('called='..tostring(result~=nil))
"""
        )
        require(close_values.get("called") == "true", f"Dowsing Done callback was not callable: {close_values}")
        wait_until(
            "Dowsing surface close",
            lambda: session.values("local s=sd.hub.get_surface_state(); print('active='..tostring(s and s.surface_active or false))"),
            lambda row: row.get("active") == "false",
            timeout=15.0,
        )
    return rolls


def parse_inventory_signature(values: dict[str, str]) -> list[dict[str, int]]:
    count = as_int(values.get("inventory.count"))
    rows = [
        {
            "type_id": as_int(values.get(f"inventory.{index}.type_id")),
            "recipe_uid": as_int(values.get(f"inventory.{index}.recipe_uid")),
            "stack_count": as_int(values.get(f"inventory.{index}.stack_count")),
            "container_depth": as_int(values.get(f"inventory.{index}.container_depth")),
        }
        for index in range(1, count + 1)
    ]
    return sorted(
        rows,
        key=lambda row: (
            row["container_depth"],
            row["type_id"],
            row["recipe_uid"],
            row["stack_count"],
        ),
    )


def dig_snapshot(session: OwnedSoloSession) -> dict[str, Any]:
    values = session.values(
        f"""
local function emit(key, value) print(key .. '=' .. tostring(value == nil and '' or value)) end
local ok, dig = pcall(sd.hub.get_solomon_dig_state)
local player = sd.player.get_state() or {{}}
local inventory = sd.player.get_inventory_state() or {{items={{}}}}
local wave = sd.waves.get_state() or {{}}
local scene = sd.world.get_scene() or {{}}
local ui = sd.ui.get_snapshot() or {{}}
local app_slot = sd.debug.resolve_game_address({APP_GLOBAL}) or 0
local app = app_slot ~= 0 and (sd.debug.read_ptr(app_slot) or 0) or 0
local arena = tonumber(scene.arena_id) or 0
emit('scene', scene.name or scene.kind or '')
emit('surface', ui.surface_id or '')
emit('app_ticks', app ~= 0 and (sd.debug.read_u32(app + 0x28) or 0) or 0)
emit('dig.available', ok and dig ~= nil)
emit('dig.x', ok and dig and dig.x or 0)
emit('dig.y', ok and dig and dig.y or 0)
emit('dig.state', ok and dig and dig.interaction_state or -1)
emit('dig.acquired', ok and dig and dig.participant_acquired or false)
emit('dig.target_slot', ok and dig and dig.target_gameplay_slot or -1)
emit('player.x', player.x or 0)
emit('player.y', player.y or 0)
emit('wave.number', wave.wave or 0)
emit('wave.phase', wave.phase or '')
emit('wave.spawned', wave.spawned or 0)
emit('wave.alive', wave.alive or 0)
emit('arena.dig_complete', arena ~= 0 and (sd.debug.read_u8(arena + 0x902A) or 0) or -1)
local gold_address = sd.debug.resolve_game_address({PROFILE_GOLD}) or 0
emit('gold', sd.debug.read_i32(gold_address) or 0)
emit('inventory.count', #(inventory.items or {{}}))
for index, item in ipairs(inventory.items or {{}}) do
  local key='inventory.'..tostring(index)
  emit(key..'.type_id', item.type_id or 0)
  emit(key..'.recipe_uid', item.recipe_uid or 0)
  emit(key..'.stack_count', item.stack_count or 0)
  emit(key..'.container_depth', item.container_depth or 0)
end
local rewards={{}}
for _, actor in ipairs(sd.world.list_actors() or {{}}) do
  local type_id=tonumber(actor.object_type_id) or 0
  if type_id==0x7DB or type_id==0x7DC or type_id==0x7DD or type_id==0x7F6 then
    rewards[type_id]=(rewards[type_id] or 0)+1
  end
end
for _, type_id in ipairs({{{', '.join(str(value) for value in sorted(REWARD_ACTOR_TYPES))}}}) do
  emit('reward.'..tostring(type_id), rewards[type_id] or 0)
end
"""
    )
    return {
        "scene": values.get("scene", ""),
        "surface": values.get("surface", ""),
        "app_ticks": as_int(values.get("app_ticks")),
        "dig_available": values.get("dig.available") == "true",
        "dig_x": round(as_float(values.get("dig.x"), 0.0), 3),
        "dig_y": round(as_float(values.get("dig.y"), 0.0), 3),
        "dig_state": as_int(values.get("dig.state"), -1),
        "participant_acquired": values.get("dig.acquired") == "true",
        "target_gameplay_slot": as_int(values.get("dig.target_slot"), -1),
        "player_x": round(as_float(values.get("player.x"), 0.0), 3),
        "player_y": round(as_float(values.get("player.y"), 0.0), 3),
        "arena_dig_complete": as_int(values.get("arena.dig_complete"), -1),
        "wave": as_int(values.get("wave.number")),
        "wave_phase": values.get("wave.phase", ""),
        "wave_spawned": as_int(values.get("wave.spawned")),
        "wave_alive": as_int(values.get("wave.alive")),
        "gold": as_int(values.get("gold")),
        "inventory": parse_inventory_signature(values),
        "reward_actor_counts": {
            str(type_id): as_int(values.get(f"reward.{type_id}"))
            for type_id in sorted(REWARD_ACTOR_TYPES)
        },
    }


def compact_dig_sample(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        key: snapshot[key]
        for key in (
            "app_ticks",
            "surface",
            "dig_available",
            "dig_x",
            "dig_y",
            "dig_state",
            "participant_acquired",
            "target_gameplay_slot",
            "player_x",
            "player_y",
            "arena_dig_complete",
            "wave",
            "wave_phase",
            "wave_spawned",
            "wave_alive",
        )
    }


def capture_dig_trial(session: OwnedSoloSession, trial_index: int) -> dict[str, Any]:
    switch_region(session, 0)
    deadline = time.monotonic() + 20.0
    last_busy = ""
    while time.monotonic() < deadline:
        session.assert_process_runnable()
        try:
            local_sync.start_testrun(session.pipe_name)
            break
        except local_sync.VerifyFailure as exc:
            detail = str(exc)
            retryable = (
                "churn is still in flight" in detail
                or "scene identity is not stable yet" in detail
                or "scene identity is still settling" in detail
            )
            if not retryable:
                raise CaptureFailure(f"BROKEN: testrun start failed: {exc}") from exc
            last_busy = detail
            time.sleep(0.1)
    else:
        raise CaptureFailure(f"BUSY_TIMEOUT: hub never became ready for testrun: {last_busy}")
    local_sync.wait_for_scene(session.pipe_name, "testrun", timeout=45.0)
    initial = wait_until(
        "live Solomon Dig actor",
        lambda: dig_snapshot(session),
        lambda row: row["dig_available"] and row["dig_state"] == 0,
        timeout=30.0,
        interval=0.05,
    )
    baseline = initial
    parked_x = initial["dig_x"] + 64.0
    parked_y = initial["dig_y"]
    placed = local_sync.place_player(
        session.pipe_name,
        parked_x,
        parked_y,
        0.0,
    )
    require(
        placed.get("write.x") == "true"
        and placed.get("write.y") == "true"
        and placed.get("write.heading") == "true",
        f"could not place the player at Solomon Dig: {placed}",
    )

    samples = [compact_dig_sample(initial)]
    actions: list[dict[str, Any]] = []
    semantic_keys = (
        "surface",
        "dig_available",
        "dig_state",
        "participant_acquired",
        "target_gameplay_slot",
        "arena_dig_complete",
        "wave",
        "wave_phase",
        "wave_spawned",
        "wave_alive",
    )
    last_signature = tuple(samples[-1][key] for key in semantic_keys)
    last_parked = time.monotonic()
    deadline = time.monotonic() + 75.0
    completed: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        current = dig_snapshot(session)
        compact = compact_dig_sample(current)
        signature = tuple(compact[key] for key in semantic_keys)
        if signature != last_signature:
            samples.append(compact)
            last_signature = signature
        if current["surface"] == "dialog":
            activate_action(session, "dialog.primary", "dialog")
            actions.append(
                {
                    "verb": "menu_nav",
                    "action": "confirm",
                    "surface": "dialog",
                    "app_ticks": current["app_ticks"],
                }
            )
            time.sleep(0.05)
            continue
        if current["dig_state"] <= 1 and time.monotonic() - last_parked >= 0.5:
            parked = local_sync.place_player(session.pipe_name, parked_x, parked_y, 0.0)
            require(
                parked.get("write.x") == "true"
                and parked.get("write.y") == "true"
                and parked.get("write.heading") == "true",
                f"could not keep the player parked for Solomon Dig: {parked}",
            )
            last_parked = time.monotonic()
        if (
            current["participant_acquired"]
            and current["target_gameplay_slot"] == 0
            and current["dig_state"] >= 3
            and current["arena_dig_complete"] == 1
        ):
            completed = current
            break
        if not current["dig_available"] and current["dig_state"] < 3:
            raise CaptureFailure(f"BROKEN: Solomon Dig disappeared before completing: {current}")
        time.sleep(0.05)
    require(completed is not None, f"BUSY_TIMEOUT: Solomon Dig did not complete trial {trial_index}; samples={samples}")
    require(completed["gold"] == baseline["gold"], f"Dig directly changed gold in trial {trial_index}: {baseline['gold']} -> {completed['gold']}")
    require(completed["inventory"] == baseline["inventory"], f"Dig directly changed inventory in trial {trial_index}")
    require(
        completed["reward_actor_counts"] == baseline["reward_actor_counts"],
        f"Dig directly materialized a reward actor in trial {trial_index}: {baseline['reward_actor_counts']} -> {completed['reward_actor_counts']}",
    )
    return {
        "trial_index": trial_index,
        "trigger": {
            "mechanism": "participant proximity to live type 5009 actor",
            "position": {"x": initial["dig_x"], "y": initial["dig_y"]},
            "g14_intents_used": ["menu_nav.confirm"],
        },
        "before": {
            "app_ticks": baseline["app_ticks"],
            "gold": baseline["gold"],
            "inventory": baseline["inventory"],
            "reward_actor_counts": baseline["reward_actor_counts"],
        },
        "after_native_completion": {
            "app_ticks": completed["app_ticks"],
            "gold": completed["gold"],
            "inventory": completed["inventory"],
            "reward_actor_counts": completed["reward_actor_counts"],
            "dig_state": completed["dig_state"],
            "participant_acquired": completed["participant_acquired"],
            "target_gameplay_slot": completed["target_gameplay_slot"],
            "arena_dig_complete": completed["arena_dig_complete"],
            "wave": completed["wave"],
            "wave_phase": completed["wave_phase"],
        },
        "dialog_actions": actions,
        "state_transitions": samples,
        "consumed_gold": 0,
        "consumed_inventory_items": [],
        "direct_yield": [],
        "direct_reward_actor_delta": {
            key: completed["reward_actor_counts"][key] - baseline["reward_actor_counts"][key]
            for key in baseline["reward_actor_counts"]
        },
    }


def fixture_header(
    session: OwnedSoloSession,
    source_revision: str,
    *,
    method: str,
    trial_count: int,
) -> dict[str, Any]:
    require(session.launch_result is not None, "fixture header requires a completed launch")
    executable = Path(str(session.launch_result["executablePath"]).replace("\\", "/").replace("C:/", "/mnt/c/"))
    if not executable.is_file():
        executable = session.stage_root / "SolomonDark.exe"
    loader = ROOT / "dist" / "launcher" / "SolomonDarkModLoader.dll"
    require(executable.is_file(), f"staged retail executable is missing: {executable}")
    require(loader.is_file(), f"Release loader used for injection is missing: {loader}")
    return {
        "instance": session.instance,
        "source_revision": source_revision,
        "retail_executable_sha256": windows_sha256(executable),
        "loader_sha256": windows_sha256(loader),
        "capture_method": method,
        "trial_count": trial_count,
    }


def assert_clean_loader_log(session: OwnedSoloSession) -> None:
    fatal_tokens = ("[fatal]", "unhandled exception", "access violation", "crash dump")
    fatal = [line for line in session.tail_log(400) if any(token in line.lower() for token in fatal_tokens)]
    require(not fatal, f"BROKEN: loader log contains a fatal signature: {fatal}")


def write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_capture(*, smoke: bool, output: Path, raw_output: Path) -> dict[str, Any]:
    source_revision = git_output("rev-parse", "HEAD")
    require(source_revision == git_output("rev-parse", "acc4ef5^{commit}"), f"capture checkout moved away from dispatched base acc4ef5: {source_revision}")
    before_processes = snapshot_hub_processes()
    require(not before_processes, f"BROKEN: pre-existing hub-* target processes would make ownership ambiguous: {before_processes}")
    type_names = load_type_names()
    session_count = 1 if smoke else TRIAL_COUNT
    trader_count = 1 if smoke else TRADER_CAPTURE_COUNT
    dowsing_count = 1 if smoke else DOWSING_ROLLS_PER_CAPTURE
    raw: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "source_revision": source_revision,
        "processes_before": before_processes,
        "sessions": [],
    }
    trader_captures: list[dict[str, Any]] = []
    dig_trials: list[dict[str, Any]] = []
    census: dict[str, Any] | None = None
    try:
        for index in range(session_count):
            instance = f"hub-g8-{'smoke' if smoke else 'capture'}-{index + 1:02d}"
            local_port = ALLOWED_PORTS[index]
            unused_port = ALLOWED_PORTS[(index + 1) % len(ALLOWED_PORTS)]
            session = OwnedSoloSession(instance, local_port, unused_port)
            session_raw: dict[str, Any] = {"instance": instance}
            raw["sessions"].append(session_raw)
            print(f"[hub-economy] launch {instance} UDP {local_port}", flush=True)
            try:
                launch = session.launch(quick_start=False)
                session_raw["launch"] = launch
                session.wait_for_pipe()
                session.assert_process_runnable()
                progression_state = PROGRESSION_STATES[index] if index < trader_count else PROGRESSION_STATES[0]
                applied, rng_before, traces = drive_new_game(session, progression_state)
                session_raw["stock_trace"] = traces
                stock = capture_trader_stock(session, applied, rng_before, traces)
                if census is None:
                    print(f"[hub-economy] census five hub regions {instance}", flush=True)
                    census = capture_hub_census(session, type_names)
                    census["header"] = fixture_header(
                        session,
                        source_revision,
                        method=census["capture_method"],
                        trial_count=5,
                    )
                if index < trader_count:
                    print(f"[hub-economy] capture traders {instance}", flush=True)
                    rolls = capture_dowsing_rolls(session, dowsing_count)
                    header = fixture_header(
                        session,
                        source_revision,
                        method="live retail Lua exec plus native function tracing and full active RNG snapshots",
                        trial_count=dowsing_count,
                    )
                    trader_captures.append(
                        {
                            "header": header,
                            **stock,
                            "shlorio_dowsing_rolls": rolls,
                        }
                    )
                print(f"[hub-economy] Dig trial {index + 1}/{session_count} {instance}", flush=True)
                dig = capture_dig_trial(session, index + 1)
                dig["header"] = fixture_header(
                    session,
                    source_revision,
                    method="live retail proximity/dialog drive with before/after currency, inventory, reward-actor and arena-state snapshots",
                    trial_count=1,
                )
                dig_trials.append(dig)
                assert_clean_loader_log(session)
                session_raw["completed"] = True
            finally:
                session_raw["cleanup"] = session.close()
                print(f"[hub-economy] stopped owned process for {instance}", flush=True)
                write_json(raw_output, raw)
        require(census is not None, "live capture produced no hub census")
        state_ids = [capture["seed_evidence"]["state_sha256"] for capture in trader_captures]
        if not smoke:
            require(len(trader_captures) >= 3, "fewer than three trader captures reached the fixture")
            require(len(set(state_ids)) == len(state_ids), f"trader captures did not use distinct captured RNG states: {state_ids}")
            require(len(dig_trials) >= 8, "fewer than eight independent Dig trials reached the fixture")
        document = {
            "schema": "solomon-dark-native-hub-economy-goldens-v1",
            "recorded_live": True,
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "source_revision": source_revision,
            "capture_contract": {
                "instances": session_count,
                "trader_progression_states": trader_count,
                "dowsing_rolls_per_trader_capture": dowsing_count,
                "dig_trials": session_count,
                "allowed_instance_prefix": "hub-*",
                "allowed_udp_ports": list(ALLOWED_PORTS),
                "audio_disabled": True,
                "sd_rng_set_seed_used": False,
            },
            "hub_entity_census": census,
            "trader_captures": trader_captures,
            "dig_trials": dig_trials,
            "observed_dig_distribution": {
                "trial_count": len(dig_trials),
                "direct_yield_counts": [len(trial["direct_yield"]) for trial in dig_trials],
                "gold_deltas": [trial["after_native_completion"]["gold"] - trial["before"]["gold"] for trial in dig_trials],
                "inventory_changed": [trial["after_native_completion"]["inventory"] != trial["before"]["inventory"] for trial in dig_trials],
                "reward_actor_deltas": [trial["direct_reward_actor_delta"] for trial in dig_trials],
            },
        }
        write_json(output, document)
        return document
    finally:
        raw["finished_at"] = datetime.now(timezone.utc).isoformat()
        raw["processes_after"] = snapshot_hub_processes()
        write_json(raw_output, raw)
        require(not raw["processes_after"], f"BROKEN: launched hub processes survived cleanup: {raw['processes_after']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true", help="capture one session/roll/trial into runtime only")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--raw-output", type=Path, default=RAW_OUTPUT)
    arguments = parser.parse_args()
    output = arguments.output
    if arguments.smoke and output == DEFAULT_OUTPUT:
        output = RUNTIME_ROOT / "hub-economy-smoke.json"
    document = run_capture(smoke=arguments.smoke, output=output, raw_output=arguments.raw_output)
    print(
        json.dumps(
            {
                "ok": True,
                "output": str(output),
                "trader_captures": len(document["trader_captures"]),
                "dig_trials": len(document["dig_trials"]),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
