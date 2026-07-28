#!/usr/bin/env python3
"""Verify native Solomon Dig modal ownership across a multiplayer wave start."""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GAME_DIRECTORY = Path(
    "/mnt/c/Users/User/Documents/GitHub/SB Modding/Solomon Dark/"
    "SolomonDarkAbandonware"
)
INSTANCE_PREFIX = "digfix"
HOST_PORT = 50211
CLIENT_B_PORT = 50212
HOST_PIPE = f"SolomonDarkModLoader_LuaExec_{INSTANCE_PREFIX}-host"
CLIENT_B_PIPE = f"SolomonDarkModLoader_LuaExec_{INSTANCE_PREFIX}-client"
SOLOMON_STATE_2 = 0x0047D450
DIALOG_GATE = 0x005C7300

sys.path.insert(0, str(ROOT / "tools"))
import verify_local_multiplayer_sync as local_sync  # noqa: E402


local_sync.HOST_PIPE = HOST_PIPE
local_sync.CLIENT_PIPE = CLIENT_B_PIPE


STATE_LUA = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local function off(name)
  return tonumber(sd.debug.layout_offset(name)) or 0
end
local function u8(address)
  return address ~= 0 and (tonumber(sd.debug.read_u8(address)) or 0) or 0
end
local function i32(address)
  return address ~= 0 and (tonumber(sd.debug.read_i32(address)) or 0) or 0
end
local function u32(address)
  return address ~= 0 and (tonumber(sd.debug.read_u32(address)) or 0) or 0
end
local function flt(address)
  return address ~= 0 and (tonumber(sd.debug.read_float(address)) or 0) or 0
end
local scene = sd.world.get_scene()
local gameplay = tonumber(scene and scene.id) or 0
local player = sd.player.get_state()
local player_actor = tonumber(player and player.actor_address) or 0
local solomon = 0
for _, candidate in ipairs(sd.world.list_actors() or {}) do
  if tonumber(candidate.object_type_id) == 0x1391 then
    solomon = tonumber(candidate.actor_address) or 0
    break
  end
end
local selection = player_actor ~= 0 and
  (tonumber(sd.debug.read_ptr(
    player_actor + off("actor_animation_selection_state"))) or 0) or 0
local wave = sd.waves.get_state() or {}
emit("scene", scene and (scene.name or scene.kind) or "")
emit("gameplay", gameplay)
emit("player_actor", player_actor)
emit("player_x", player and player.x or 0)
emit("player_y", player and player.y or 0)
emit("loader_intent_x", player and player.movement_intent_x or 0)
emit("loader_intent_y", player and player.movement_intent_y or 0)
emit("gameplay_intent_x", gameplay ~= 0 and flt(
  gameplay + off("gameplay_local_movement_input_x")) or 0)
emit("gameplay_intent_y", gameplay ~= 0 and flt(
  gameplay + off("gameplay_local_movement_input_y")) or 0)
emit("native_vector_x", player_actor ~= 0 and flt(
  player_actor + off("actor_animation_config_block")) or 0)
emit("native_vector_y", player_actor ~= 0 and flt(
  player_actor + off("actor_animation_drive_parameter")) or 0)
emit("control_vector_x", selection ~= 0 and flt(
  selection + off("actor_control_brain_move_input_x")) or 0)
emit("control_vector_y", selection ~= 0 and flt(
  selection + off("actor_control_brain_move_input_y")) or 0)
emit("solomon", solomon)
emit("solomon_x", solomon ~= 0 and flt(
  solomon + off("actor_position_x")) or 0)
emit("solomon_y", solomon ~= 0 and flt(
  solomon + off("actor_position_y")) or 0)
emit("solomon_state", solomon ~= 0 and i32(
  solomon + off("solomon_dig_interaction_state")) or -1)
emit("solomon_acquired", solomon ~= 0 and u8(
  solomon + off("solomon_dig_participant_acquired")) or 0)
emit("solomon_target_slot", solomon ~= 0 and i32(
  solomon + off("solomon_dig_target_gameplay_slot")) or -1)
emit("dialog_block", gameplay ~= 0 and u8(
  gameplay + off("gameplay_cast_ui_block_flag")) or -1)
emit("primary_block", gameplay ~= 0 and u8(
  gameplay + off("gameplay_primary_gate_block_flag")) or -1)
emit("dialog_controller_current", gameplay ~= 0 and u32(
  gameplay + 0xF0) or 0)
emit("dialog_controller_saved", gameplay ~= 0 and u32(
  gameplay + 0x224) or 0)
emit("wave", wave.wave or 0)
emit("wave_phase", wave.phase or "")
emit("wave_spawned", wave.spawned or 0)
emit("wave_alive", wave.alive or 0)
"""


def lua(pipe: str, code: str, timeout: float = 8.0) -> str:
    return local_sync.lua(pipe, code, timeout=timeout)


def values(pipe: str, code: str, timeout: float = 8.0) -> dict[str, str]:
    return local_sync.parse_key_values(lua(pipe, code, timeout=timeout))


def state(pipe: str) -> dict[str, str]:
    return values(pipe, STATE_LUA)


def number(row: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key, default))
    except (TypeError, ValueError):
        return default


def integer(row: dict[str, str], key: str, default: int = 0) -> int:
    try:
        return int(row.get(key, default))
    except (TypeError, ValueError):
        return default


def wait_for(
    predicate: Callable[[], Any],
    *,
    timeout: float,
    interval: float = 0.05,
) -> Any:
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(interval)
    raise RuntimeError(f"condition timed out; last={last!r}")


def state_with_solomon(pipe: str) -> dict[str, str] | None:
    row = state(pipe)
    return row if integer(row, "solomon") != 0 else None


def local_modal_state(pipe: str) -> dict[str, str] | None:
    row = state(pipe)
    if (
        integer(row, "solomon") != 0
        and integer(row, "solomon_acquired") != 0
        and integer(row, "solomon_target_slot", -1) == 0
        and integer(row, "dialog_block") == 1
    ):
        return row
    return None


def select_long_native_dialogue(pipe: str) -> dict[str, str]:
    return values(
        pipe,
        r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local scene = sd.world.get_scene()
local gameplay = tonumber(scene and scene.id) or 0
if gameplay == 0 then error("gameplay scene unavailable") end
emit("before", sd.debug.read_i32(gameplay + 0x1CD0))
emit("write", sd.debug.write_u32(gameplay + 0x1CD0, 1))
emit("after", sd.debug.read_i32(gameplay + 0x1CD0))
""",
    )


def arm_dialog_trace(pipe: str, trace_name: str) -> dict[str, str]:
    return values(
        pipe,
        f"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
pcall(sd.debug.untrace_function, {DIALOG_GATE})
sd.debug.clear_trace_hits({json.dumps(trace_name)})
emit("armed", sd.debug.trace_function(
  {DIALOG_GATE}, {json.dumps(trace_name)}))
emit("error", sd.debug.get_last_error())
""",
    )


def dialog_trace_summary(pipe: str, trace_name: str) -> dict[str, str]:
    return values(
        pipe,
        f"""
local hits = sd.debug.get_trace_hits({json.dumps(trace_name)}) or {{}}
local lock_count = 0
local unlock_count = 0
for _, hit in ipairs(hits) do
  if tonumber(hit.arg0) == 1 then lock_count = lock_count + 1 end
  if tonumber(hit.arg0) == 0 then unlock_count = unlock_count + 1 end
end
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
emit("count", #hits)
emit("lock_count", lock_count)
emit("unlock_count", unlock_count)
""",
    )


def completion_target(
    pipe: str,
    launch: dict[str, object],
    role: str,
) -> dict[str, object]:
    resolved = values(
        pipe,
        f"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local address = tonumber(sd.debug.resolve_game_address(
  {SOLOMON_STATE_2})) or 0
emit("address", address)
emit("byte", address ~= 0 and sd.debug.read_u8(address) or -1)
""",
    )
    address = int(resolved.get("address", "0") or 0)
    if address == 0 or resolved.get("byte") != "86":
        raise RuntimeError(f"unexpected Solomon state-2 target: {resolved}")
    key_prefix = "host" if role == "host" else "client"
    return {
        "pid": int(launch[f"{key_prefix}ProcessId"]),
        "expectedPath": str(launch[f"{key_prefix}ExecutablePath"]),
        "address": address,
        "role": role,
    }


def set_completion_delay(
    target: dict[str, object],
    enabled: bool,
) -> dict[str, object]:
    expected = 0x56 if enabled else 0xC3
    replacement = 0xC3 if enabled else 0x56
    expected_path = str(target["expectedPath"]).replace("'", "''")
    role = str(target["role"]).replace("'", "''")
    script = f"""
$ErrorActionPreference = 'Stop'
$targetPid = {int(target["pid"])}
$expectedPath = '{expected_path}'
$role = '{role}'
$address = [IntPtr]([Int64]{int(target["address"])})
$process = Get-CimInstance Win32_Process -Filter (
  'ProcessId = ' + $targetPid)
if ($null -eq $process) {{
  throw ($role + ' process is not running')
}}
if (-not [string]::Equals(
  $process.ExecutablePath,
  $expectedPath,
  [System.StringComparison]::OrdinalIgnoreCase)) {{
  throw ($role + ' executable path mismatch: ' + $process.ExecutablePath)
}}
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class DigNpcCompletionMemory {{
  [DllImport("kernel32.dll", SetLastError = true)]
  public static extern IntPtr OpenProcess(
    uint access, bool inheritHandle, uint processId);
  [DllImport("kernel32.dll", SetLastError = true)]
  [return: MarshalAs(UnmanagedType.Bool)]
  public static extern bool ReadProcessMemory(
    IntPtr process, IntPtr address, byte[] buffer,
    UIntPtr size, out UIntPtr read);
  [DllImport("kernel32.dll", SetLastError = true)]
  [return: MarshalAs(UnmanagedType.Bool)]
  public static extern bool WriteProcessMemory(
    IntPtr process, IntPtr address, byte[] buffer,
    UIntPtr size, out UIntPtr written);
  [DllImport("kernel32.dll", SetLastError = true)]
  [return: MarshalAs(UnmanagedType.Bool)]
  public static extern bool VirtualProtectEx(
    IntPtr process, IntPtr address, UIntPtr size,
    uint newProtection, out uint oldProtection);
  [DllImport("kernel32.dll", SetLastError = true)]
  [return: MarshalAs(UnmanagedType.Bool)]
  public static extern bool FlushInstructionCache(
    IntPtr process, IntPtr address, UIntPtr size);
  [DllImport("kernel32.dll", SetLastError = true)]
  [return: MarshalAs(UnmanagedType.Bool)]
  public static extern bool CloseHandle(IntPtr handle);
}}
'@
$handle = [DigNpcCompletionMemory]::OpenProcess(
  0x1038, $false, [uint32]$targetPid)
if ($handle -eq [IntPtr]::Zero) {{
  throw ('OpenProcess failed: ' +
    [Runtime.InteropServices.Marshal]::GetLastWin32Error())
}}
$one = [UIntPtr]::new([UInt64]1)
$oldProtection = 0
$protectionChanged = $false
try {{
  $before = [byte[]]::new(1)
  $read = [UIntPtr]::Zero
  if (-not [DigNpcCompletionMemory]::ReadProcessMemory(
    $handle, $address, $before, $one, [ref]$read)) {{
    throw ('ReadProcessMemory failed: ' +
      [Runtime.InteropServices.Marshal]::GetLastWin32Error())
  }}
  if ($before[0] -ne {expected}) {{
    throw ('unexpected Solomon state-2 first byte: ' + $before[0])
  }}
  if (-not [DigNpcCompletionMemory]::VirtualProtectEx(
    $handle, $address, $one, 0x40, [ref]$oldProtection)) {{
    throw ('VirtualProtectEx failed: ' +
      [Runtime.InteropServices.Marshal]::GetLastWin32Error())
  }}
  $protectionChanged = $true
  $value = [byte[]]@({replacement})
  $written = [UIntPtr]::Zero
  if (-not [DigNpcCompletionMemory]::WriteProcessMemory(
    $handle, $address, $value, $one, [ref]$written)) {{
    throw ('WriteProcessMemory failed: ' +
      [Runtime.InteropServices.Marshal]::GetLastWin32Error())
  }}
  if (-not [DigNpcCompletionMemory]::FlushInstructionCache(
    $handle, $address, $one)) {{
    throw ('FlushInstructionCache failed: ' +
      [Runtime.InteropServices.Marshal]::GetLastWin32Error())
  }}
}} finally {{
  if ($protectionChanged) {{
    $ignoredProtection = 0
    [void][DigNpcCompletionMemory]::VirtualProtectEx(
      $handle, $address, $one,
      $oldProtection, [ref]$ignoredProtection)
  }}
}}
$after = [byte[]]::new(1)
$afterRead = [UIntPtr]::Zero
if (-not [DigNpcCompletionMemory]::ReadProcessMemory(
  $handle, $address, $after, $one, [ref]$afterRead)) {{
  throw ('post-write ReadProcessMemory failed: ' +
    [Runtime.InteropServices.Marshal]::GetLastWin32Error())
}}
[void][DigNpcCompletionMemory]::CloseHandle($handle)
[pscustomobject]@{{
  processId = $targetPid
  executablePath = $process.ExecutablePath
  address = $address.ToInt64()
  before = [int]$before[0]
  after = [int]$after[0]
  oldProtection = [int]$oldProtection
  pathMatched = $true
}} | ConvertTo-Json -Compress
"""
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            encoded,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=20.0,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "native completion delay write failed: "
            f"stdout={completed.stdout!r} stderr={completed.stderr!r}"
        )
    output_lines = [
        line.strip()
        for line in completed.stdout.splitlines()
        if line.strip().startswith("{")
    ]
    if not output_lines:
        raise RuntimeError(
            "native completion delay write returned no JSON: "
            f"{completed.stdout!r}"
        )
    result = json.loads(output_lines[-1])
    if result.get("after") != replacement or result.get("pathMatched") is not True:
        raise RuntimeError(f"native completion delay write did not stick: {result}")
    return result


def configure_drive(
    pipe: str,
    x: float,
    y: float,
    frames: int,
) -> dict[str, str]:
    return values(
        pipe,
        f"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
if not _G.__dig_npc_drive_registered then
  sd.events.on("runtime.tick", function()
    local drive = _G.__dig_npc_drive
    if type(drive) ~= "table" or drive.remaining <= 0 then return end
    local ok, result = pcall(
      sd.input.hold_movement_frames, drive.x, drive.y, 1)
    if not ok or result ~= true then
      drive.error = tostring(result)
      drive.remaining = 0
      return
    end
    drive.applied = drive.applied + 1
    drive.remaining = drive.remaining - 1
  end)
  _G.__dig_npc_drive_registered = true
end
local allowance_ok, allowance = pcall(
  sd.input.set_native_control_allowance_frames, {frames + 120})
_G.__dig_npc_drive = {{
  x = {x:.9f},
  y = {y:.9f},
  remaining = {frames},
  applied = 0,
  error = "",
}}
emit("registered", _G.__dig_npc_drive_registered)
emit("allowance", allowance_ok and allowance == true)
""",
    )


def drive_status(pipe: str) -> dict[str, str]:
    return values(
        pipe,
        r"""
local drive = _G.__dig_npc_drive or {}
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
emit("remaining", drive.remaining or 0)
emit("applied", drive.applied or 0)
emit("error", drive.error or "")
""",
    )


def measure_drive(
    pipe: str,
    *,
    frames: int,
    x: float = 1.0,
    y: float = 0.0,
) -> dict[str, object]:
    before = state(pipe)
    arm = configure_drive(pipe, x, y, frames)
    samples: list[dict[str, str]] = []
    deadline = time.monotonic() + max(5.0, frames / 30.0)
    status: dict[str, str] = {}
    while time.monotonic() < deadline:
        samples.append(state(pipe))
        status = drive_status(pipe)
        if integer(status, "remaining") <= 0:
            break
        time.sleep(0.04)
    if not samples:
        raise RuntimeError("movement drive produced no native samples")
    after = samples[-1]
    displacement = math.hypot(
        number(after, "player_x") - number(before, "player_x"),
        number(after, "player_y") - number(before, "player_y"),
    )
    peak_loader_intent = max(
        math.hypot(
            number(sample, "loader_intent_x"),
            number(sample, "loader_intent_y"),
        )
        for sample in samples
    )
    peak_gameplay_intent = max(
        math.hypot(
            number(sample, "gameplay_intent_x"),
            number(sample, "gameplay_intent_y"),
        )
        for sample in samples
    )
    peak_native_vector = max(
        math.hypot(
            number(sample, "native_vector_x"),
            number(sample, "native_vector_y"),
        )
        for sample in samples
    )
    return {
        "arm": arm,
        "status": status,
        "requestedInputIntent": {
            "x": x,
            "y": y,
            "magnitude": math.hypot(x, y),
        },
        "appliedInputIntentFrames": integer(status, "applied"),
        "before": before,
        "after": after,
        "sampleCount": len(samples),
        "displacement": displacement,
        "peakLoaderIntent": peak_loader_intent,
        "peakGameplayIntent": peak_gameplay_intent,
        "peakNativeVector": peak_native_vector,
    }


def require_locked_motion(result: dict[str, object], label: str) -> None:
    if int(result["status"].get("applied", "0") or 0) < 30:
        raise RuntimeError(f"{label} modal drive did not reach the input seam")
    if float(result["displacement"]) >= 1.0:
        raise RuntimeError(f"{label} moved while the native modal was open: {result}")
    if float(result["peakNativeVector"]) >= 0.05:
        raise RuntimeError(
            f"{label} reached a native movement vector while modal: {result}"
        )


def require_working_motion(result: dict[str, object], label: str) -> None:
    if int(result["status"].get("applied", "0") or 0) < 60:
        raise RuntimeError(f"{label} movement drive did not reach the input seam")
    requested_intent = result["requestedInputIntent"]
    if float(requested_intent["magnitude"]) <= 0.9:
        raise RuntimeError(f"{label} did not request movement intent: {result}")
    if float(result["peakNativeVector"]) <= 0.1:
        raise RuntimeError(f"{label} native movement vector remained zero: {result}")
    if float(result["displacement"]) <= 5.0:
        raise RuntimeError(f"{label} did not displace in the world: {result}")


def measure_working_motion(
    pipe: str,
    *,
    frames: int,
) -> dict[str, object]:
    attempts: list[dict[str, object]] = []
    for x, y in ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0)):
        result = measure_drive(pipe, frames=frames, x=x, y=y)
        attempts.append(result)
        if (
            int(result["status"].get("applied", "0") or 0) >= 60
            and float(result["peakNativeVector"]) > 0.1
            and float(result["displacement"]) > 5.0
        ):
            result["directionAttempts"] = [
                {
                    "requestedInputIntent": attempt["requestedInputIntent"],
                    "appliedInputIntentFrames": attempt[
                        "appliedInputIntentFrames"
                    ],
                    "peakNativeVector": attempt["peakNativeVector"],
                    "displacement": attempt["displacement"],
                }
                for attempt in attempts
            ]
            return result
    raise RuntimeError(
        "all four native movement directions were physically blocked: "
        f"{attempts}"
    )


def launch_pair(game_directory: Path) -> dict[str, object]:
    launch = local_sync.launch_pair(
        instance_prefix=INSTANCE_PREFIX,
        host_port=HOST_PORT,
        client_port=CLIENT_B_PORT,
        temporary_host_profile=True,
        kill_existing=False,
        god_mode=True,
        exact_mod_id="sample.lua.ui_sandbox_lab",
        use_sandbox_preset_flow=True,
        tile_windows=False,
        game_directory=game_directory,
        enable_audio=False,
    )
    if launch.get("audioDisabled") is not True:
        raise RuntimeError(f"audio was not disabled: {launch}")
    return launch


def enter_run() -> None:
    local_sync.start_host_testrun_and_wait_for_clients(timeout=45.0)
    local_sync.wait_for_remote(
        HOST_PIPE,
        local_sync.CLIENT_ID,
        local_sync.CLIENT_NAME,
        "testrun",
    )
    local_sync.wait_for_remote(
        CLIENT_B_PIPE,
        local_sync.HOST_ID,
        local_sync.HOST_NAME,
        "testrun",
    )
    local_sync.verify_run_entry_bootstrap(timeout=20.0)
    time.sleep(6.0)
    wait_for(lambda: state_with_solomon(HOST_PIPE), timeout=20.0, interval=0.2)
    wait_for(lambda: state_with_solomon(CLIENT_B_PIPE), timeout=20.0, interval=0.2)


def launch_summary(launch: dict[str, object]) -> dict[str, object]:
    return {
        "hostProcessId": launch.get("hostProcessId"),
        "clientBProcessId": launch.get("clientProcessId"),
        "hostExecutablePath": launch.get("hostExecutablePath"),
        "clientBExecutablePath": launch.get("clientExecutablePath"),
        "audioDisabled": launch.get("audioDisabled"),
    }


def copy_scenario_logs(label: str, output_directory: Path) -> None:
    for role, destination_role in (("host", "host"), ("client", "client-b")):
        source = (
            ROOT
            / "runtime"
            / "instances"
            / f"{INSTANCE_PREFIX}-{role}"
            / "stage"
            / ".sdmod"
            / "logs"
            / "solomondarkmodloader.log"
        )
        if source.is_file():
            shutil.copy2(
                source,
                output_directory / f"{label}-{destination_role}.log",
            )


def run_real_npc_scenario(
    initiator: str,
    game_directory: Path,
    output_directory: Path,
) -> dict[str, object]:
    if initiator not in {"host", "client_b"}:
        raise ValueError(f"unsupported NPC initiator: {initiator}")
    label = "host-npc" if initiator == "host" else "client-b-npc"
    initiator_pipe = HOST_PIPE if initiator == "host" else CLIENT_B_PIPE
    other_pipe = CLIENT_B_PIPE if initiator == "host" else HOST_PIPE
    target_role = "host" if initiator == "host" else "client_b"
    launch: dict[str, object] = {}
    target: dict[str, object] | None = None
    delay_active = False
    record: dict[str, object] = {
        "scenario": label,
        "realNpcPath": True,
        "luaStartWavesUsed": False,
        "ok": False,
    }
    try:
        launch = launch_pair(game_directory)
        record["launch"] = launch_summary(launch)
        enter_run()
        before = {
            "host": state(HOST_PIPE),
            "clientB": state(CLIENT_B_PIPE),
        }
        record["before"] = before
        if initiator == "client_b":
            dialogue = select_long_native_dialogue(CLIENT_B_PIPE)
            record["clientBLongDialogueSelection"] = dialogue
            if dialogue.get("write") != "true" or dialogue.get("after") != "1":
                raise RuntimeError(
                    "could not select client B's native long-dialogue branch"
                )

        trace_name = f"dig_npc_{label.replace('-', '_')}"
        trace_arm = arm_dialog_trace(initiator_pipe, trace_name)
        record["dialogTraceArm"] = trace_arm
        if trace_arm.get("armed") != "true":
            raise RuntimeError(f"could not arm native dialog trace: {trace_arm}")

        target = completion_target(initiator_pipe, launch, target_role)
        record["completionDelayArm"] = set_completion_delay(target, True)
        delay_active = True

        solomon = state_with_solomon(initiator_pipe)
        if solomon is None:
            raise RuntimeError("initiating machine has no Solomon_Dig actor")
        record["placement"] = local_sync.place_player(
            initiator_pipe,
            number(solomon, "solomon_x"),
            number(solomon, "solomon_y"),
            0.0,
        )
        modal = wait_for(
            lambda: local_modal_state(initiator_pipe),
            timeout=12.0,
        )
        record["modalOpened"] = modal

        modal_motion = measure_drive(initiator_pipe, frames=90)
        record["modalMotion"] = modal_motion
        require_locked_motion(modal_motion, label)

        other_motion = measure_working_motion(other_pipe, frames=120)
        record["nonInitiatorMotionDuringModal"] = other_motion
        require_working_motion(other_motion, f"{label} non-initiator")
        other_state = state(other_pipe)
        if integer(other_state, "dialog_block") != 0:
            raise RuntimeError(
                f"{label} asserted a local modal on the non-initiator: {other_state}"
            )
        record["nonInitiatorDuringModal"] = other_state

        if initiator == "client_b":
            def authority_advanced_while_owner_remains() -> dict[str, object] | None:
                host_row = state(HOST_PIPE)
                client_b_row = state(CLIENT_B_PIPE)
                if (
                    integer(host_row, "wave") > 0
                    and integer(client_b_row, "wave") > 0
                    and integer(client_b_row, "solomon") != 0
                    and integer(client_b_row, "solomon_state", -1) < 3
                ):
                    return {"host": host_row, "clientB": client_b_row}
                return None

            retained = wait_for(
                authority_advanced_while_owner_remains,
                timeout=90.0,
                interval=0.1,
            )
            time.sleep(1.0)
            retained_after_snapshot_cycles = state(CLIENT_B_PIPE)
            if (
                integer(retained_after_snapshot_cycles, "solomon") == 0
                or integer(
                    retained_after_snapshot_cycles,
                    "solomon_state",
                    -1,
                ) >= 3
            ):
                raise RuntimeError(
                    "client B native completion owner retired before release: "
                    f"{retained_after_snapshot_cycles}"
                )
            record["authorityAdvancedWhileLocalOwnerRetained"] = retained
            record["localOwnerAfterSnapshotCycles"] = (
                retained_after_snapshot_cycles
            )
            trace_before_release = dialog_trace_summary(
                initiator_pipe,
                trace_name,
            )
            record["dialogTraceBeforeRelease"] = trace_before_release
            if (
                integer(trace_before_release, "lock_count") < 1
                or integer(trace_before_release, "unlock_count") != 0
            ):
                raise RuntimeError(
                    "client B did not remain at the native lock boundary: "
                    f"{trace_before_release}"
                )

        record["completionDelayRelease"] = set_completion_delay(target, False)
        delay_active = False

        trace_after_release = wait_for(
            lambda: (
                summary
                if integer(summary := dialog_trace_summary(
                    initiator_pipe,
                    trace_name,
                ), "unlock_count") >= 1
                else None
            ),
            timeout=12.0,
            interval=0.1,
        )
        record["dialogTraceAfterRelease"] = trace_after_release

        waves = wait_for(
            lambda: (
                {"host": host_row, "clientB": client_b_row}
                if integer(host_row := state(HOST_PIPE), "wave") > 0
                and integer(
                    client_b_row := state(CLIENT_B_PIPE),
                    "wave",
                ) > 0
                else None
            ),
            timeout=45.0,
            interval=0.1,
        )
        record["authorityWaveReplicated"] = waves

        completion = wait_for(
            lambda: (
                row
                if integer(row := state(initiator_pipe), "solomon") == 0
                or integer(row, "solomon_state", -1) >= 3
                else None
            ),
            timeout=15.0,
            interval=0.1,
        )
        record["nativeCompletionBoundary"] = completion
        if initiator == "client_b":
            record["retiredAfterNativeCompletion"] = wait_for(
                lambda: (
                    row
                    if integer(row := state(CLIENT_B_PIPE), "solomon") == 0
                    else None
                ),
                timeout=20.0,
                interval=0.1,
            )

        record["postCompletionOpenPlacement"] = {
            "host": local_sync.place_player(
                HOST_PIPE,
                number(before["host"], "player_x"),
                number(before["host"], "player_y"),
                0.0,
            ),
            "clientB": local_sync.place_player(
                CLIENT_B_PIPE,
                number(before["clientB"], "player_x"),
                number(before["clientB"], "player_y"),
                0.0,
            ),
        }
        initiator_motion = measure_working_motion(
            initiator_pipe,
            frames=180,
        )
        other_post_motion = measure_working_motion(
            other_pipe,
            frames=180,
        )
        record["initiatorMotionAfterCompletion"] = initiator_motion
        record["nonInitiatorMotionAfterCompletion"] = other_post_motion
        require_working_motion(initiator_motion, f"{label} initiator")
        require_working_motion(other_post_motion, f"{label} non-initiator")
        record["ok"] = True
        return record
    except BaseException as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
        return record
    finally:
        if delay_active and target is not None:
            try:
                record["completionDelayEmergencyRelease"] = set_completion_delay(
                    target,
                    False,
                )
            except BaseException as exc:
                record["completionDelayEmergencyReleaseError"] = (
                    f"{type(exc).__name__}: {exc}"
                )
        if launch:
            try:
                record["cleanup"] = local_sync.stop_game_processes(
                    local_sync.game_process_ids(launch)
                )
            except BaseException as exc:
                record["cleanupError"] = f"{type(exc).__name__}: {exc}"
                record["ok"] = False
        try:
            copy_scenario_logs(label, output_directory)
        except BaseException as exc:
            record["logCopyError"] = f"{type(exc).__name__}: {exc}"
            record["ok"] = False


def run_lua_wave_regression(
    game_directory: Path,
    output_directory: Path,
) -> dict[str, object]:
    label = "lua-wave-regression"
    launch: dict[str, object] = {}
    record: dict[str, object] = {
        "scenario": label,
        "realNpcPath": False,
        "luaStartWavesUsed": True,
        "ok": False,
    }
    try:
        launch = launch_pair(game_directory)
        record["launch"] = launch_summary(launch)
        enter_run()
        before = {
            "host": state(HOST_PIPE),
            "clientB": state(CLIENT_B_PIPE),
        }
        record["before"] = before
        for machine, row in before.items():
            if integer(row, "dialog_block") != 0:
                raise RuntimeError(
                    f"{machine} began Lua regression inside a native modal: {row}"
                )
        record["startWaves"] = values(
            HOST_PIPE,
            r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local ok, result = pcall(sd.gameplay.start_waves)
emit("ok", ok)
emit("result", result)
""",
        )
        if record["startWaves"].get("ok") != "true":
            raise RuntimeError(f"Lua wave start failed: {record['startWaves']}")
        record["authorityWaveReplicated"] = wait_for(
            lambda: (
                {"host": host_row, "clientB": client_b_row}
                if integer(host_row := state(HOST_PIPE), "wave") > 0
                and integer(
                    client_b_row := state(CLIENT_B_PIPE),
                    "wave",
                ) > 0
                else None
            ),
            timeout=45.0,
            interval=0.1,
        )
        host_motion = measure_working_motion(HOST_PIPE, frames=180)
        client_b_motion = measure_working_motion(
            CLIENT_B_PIPE,
            frames=180,
        )
        record["hostMotion"] = host_motion
        record["clientBMotion"] = client_b_motion
        require_working_motion(host_motion, "Lua-wave host")
        require_working_motion(client_b_motion, "Lua-wave client B")
        after = {
            "host": state(HOST_PIPE),
            "clientB": state(CLIENT_B_PIPE),
        }
        record["after"] = after
        for machine, row in after.items():
            if integer(row, "dialog_block") != 0:
                raise RuntimeError(
                    f"{machine} acquired a stranded modal on Lua wave start: {row}"
                )
        record["ok"] = True
        return record
    except BaseException as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
        return record
    finally:
        if launch:
            try:
                record["cleanup"] = local_sync.stop_game_processes(
                    local_sync.game_process_ids(launch)
                )
            except BaseException as exc:
                record["cleanupError"] = f"{type(exc).__name__}: {exc}"
                record["ok"] = False
        try:
            copy_scenario_logs(label, output_directory)
        except BaseException as exc:
            record["logCopyError"] = f"{type(exc).__name__}: {exc}"
            record["ok"] = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--game-directory",
        type=Path,
        default=DEFAULT_GAME_DIRECTORY,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            ROOT
            / "runtime"
            / "verification"
            / "multiplayer-dig-npc-movement-unlock.json"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    os.environ["SDMOD_DISABLE_AUDIO"] = "1"
    result: dict[str, object] = {
        "instancePrefix": INSTANCE_PREFIX,
        "ports": {"host": HOST_PORT, "clientB": CLIENT_B_PORT},
        "audioDisabled": True,
        "scenarios": [],
        "ok": False,
    }
    exit_code = 1
    try:
        scenarios = []
        scenarios.append(
            run_real_npc_scenario(
                "client_b",
                args.game_directory,
                output.parent,
            )
        )
        time.sleep(3.0)
        scenarios.append(
            run_real_npc_scenario(
                "host",
                args.game_directory,
                output.parent,
            )
        )
        time.sleep(3.0)
        scenarios.append(
            run_lua_wave_regression(
                args.game_directory,
                output.parent,
            )
        )
        result["scenarios"] = scenarios
        result["ok"] = all(bool(scenario.get("ok")) for scenario in scenarios)
        exit_code = 0 if result["ok"] else 2
    except BaseException as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        output.write_text(
            json.dumps(result, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(json.dumps(result, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
