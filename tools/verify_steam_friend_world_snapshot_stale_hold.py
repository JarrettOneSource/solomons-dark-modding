#!/usr/bin/env python3
"""Verify last-authority enemy hold across a real Steam host stall."""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import time
import traceback
from pathlib import Path
from typing import Any

import verify_multiplayer_primary_kill_stress as primary
from steam_friend_active_pair import (
    CLIENT_ENDPOINT,
    PAIR_BACKEND,
    ROOT,
    SteamFriendActivePair,
)
from steam_friend_hub_automation import (
    REMOTE_GAME_PATH,
    encoded_powershell,
    quote_powershell,
    remote_ssh_settings,
    remote_windows_process_id,
)
from verify_local_multiplayer_sync import VerifyFailure
from verify_steam_friend_primary_kill_stress import configure


DEFAULT_OUTPUT = ROOT / "runtime/steam_friend_world_snapshot_stale_hold.json"
HOST_INSTANCE = os.environ.get(
    "SDMOD_STEAM_HOST_INSTANCE",
    "steam-host-regression-v60-manual",
)


def parse_float(value: str | None, default: float = math.nan) -> float:
    try:
        return float(value) if value is not None else default
    except ValueError:
        return default


def parse_int(value: str | None, default: int = 0) -> int:
    try:
        return int(value, 0) if value is not None else default
    except ValueError:
        return default


PROCESS_CONTROL_TYPE_DEFINITION = r"""
using System;
using System.Runtime.InteropServices;
public static class SdmodNativeProcessControl {
    [DllImport("ntdll.dll")]
    public static extern int NtSuspendProcess(IntPtr processHandle);
    [DllImport("ntdll.dll")]
    public static extern int NtResumeProcess(IntPtr processHandle);
}
"""


def find_local_windows_host_pid() -> int:
    escaped_instance = HOST_INSTANCE.replace("'", "''")
    command = (
        "$instance='" + escaped_instance + "';"
        "$suffix='\\runtime\\instances\\'+$instance+'\\stage\\SolomonDark.exe';"
        "$match=Get-CimInstance Win32_Process -Filter \"Name='SolomonDark.exe'\" | "
        "Where-Object { $_.ExecutablePath -and $_.ExecutablePath.EndsWith($suffix, "
        "[System.StringComparison]::OrdinalIgnoreCase) };"
        "if (@($match).Count -ne 1) { exit 3 };"
        "[Console]::Write(@($match)[0].ProcessId)"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15.0,
        check=False,
    )
    if completed.returncode != 0:
        raise VerifyFailure(
            "could not identify the exact Windows Steam host game process"
        )
    try:
        pid = int(completed.stdout.strip())
    except ValueError as exc:
        raise VerifyFailure("Windows Steam host PID was malformed") from exc
    if pid <= 0:
        raise VerifyFailure("Windows Steam host PID was invalid")
    return pid


def require_suspension_started(
    process: subprocess.Popen[str],
    label: str,
) -> subprocess.Popen[str]:
    assert process.stdout is not None
    marker = process.stdout.readline().strip()
    if marker != "suspended":
        stderr = process.stderr.read().strip() if process.stderr is not None else ""
        process.wait(timeout=5.0)
        raise VerifyFailure(
            f"{label} suspension did not start: marker={marker!r} detail={stderr}"
        )
    return process


def suspend_local_windows_game(
    pid: int,
    duration_ms: int,
) -> subprocess.Popen[str]:
    escaped_type = PROCESS_CONTROL_TYPE_DEFINITION.replace("'", "''")
    command = (
        "$ErrorActionPreference='Stop';"
        "Add-Type -TypeDefinition '" + escaped_type + "';"
        f"$process=Get-Process -Id {pid} -ErrorAction Stop;"
        "$suspended=$false;"
        "try {"
        "$status=[SdmodNativeProcessControl]::NtSuspendProcess($process.Handle);"
        "if ($status -ne 0) { throw \"NtSuspendProcess failed: $status\" };"
        "$suspended=$true;"
        "[Console]::Out.WriteLine('suspended');[Console]::Out.Flush();"
        f"Start-Sleep -Milliseconds {duration_ms};"
        "} finally {"
        "if ($suspended) {"
        "$status=[SdmodNativeProcessControl]::NtResumeProcess($process.Handle);"
        "if ($status -ne 0) { throw \"NtResumeProcess failed: $status\" };"
        "[Console]::Out.WriteLine('resumed');[Console]::Out.Flush();"
        "}"
        "}"
    )
    process = subprocess.Popen(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    return require_suspension_started(process, "local Windows host")


def suspend_remote_windows_game(
    pid: int,
    duration_ms: int,
) -> subprocess.Popen[str]:
    if not REMOTE_GAME_PATH:
        raise VerifyFailure("SDMOD_STEAM_REMOTE_GAME_PATH is empty")
    escaped_type = PROCESS_CONTROL_TYPE_DEFINITION.replace("'", "''")
    command = (
        "$ErrorActionPreference='Stop';"
        f"$path={quote_powershell(REMOTE_GAME_PATH)};"
        f"$cim=Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\";"
        "if($null -eq $cim -or "
        "-not [string]::Equals([string]$cim.ExecutablePath,$path,"
        "[System.StringComparison]::OrdinalIgnoreCase)){"
        "throw 'remote host process identity changed'};"
        "Add-Type -TypeDefinition '" + escaped_type + "';"
        f"$process=Get-Process -Id {pid} -ErrorAction Stop;"
        "$suspended=$false;"
        "try {"
        "$status=[SdmodNativeProcessControl]::NtSuspendProcess($process.Handle);"
        "if ($status -ne 0) { throw \"NtSuspendProcess failed: $status\" };"
        "$suspended=$true;"
        "[Console]::Out.WriteLine('suspended');[Console]::Out.Flush();"
        f"Start-Sleep -Milliseconds {duration_ms};"
        "} finally {"
        "if ($suspended) {"
        "$status=[SdmodNativeProcessControl]::NtResumeProcess($process.Handle);"
        "if ($status -ne 0) { throw \"NtResumeProcess failed: $status\" };"
        "[Console]::Out.WriteLine('resumed');[Console]::Out.Flush();"
        "}"
        "}"
    )
    host, user, key = remote_ssh_settings()
    process = subprocess.Popen(
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
            *encoded_powershell(command),
        ],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    return require_suspension_started(process, "remote Windows host")


def find_host_pid() -> int:
    if PAIR_BACKEND == "remote-windows-host":
        return remote_windows_process_id()
    return find_local_windows_host_pid()


def suspend_host_game(pid: int, duration_ms: int) -> subprocess.Popen[str]:
    if PAIR_BACKEND == "remote-windows-host":
        return suspend_remote_windows_game(pid, duration_ms)
    return suspend_local_windows_game(pid, duration_ms)


def compact_sample(values: dict[str, str]) -> dict[str, Any]:
    return {
        "apply_valid": values.get("rep.apply_valid") == "true",
        "holding_stale_snapshot":
            values.get("rep.apply_holding_stale_snapshot") == "true",
        "source_snapshot_age_ms": parse_int(
            values.get("rep.apply_source_snapshot_age_ms")
        ),
        "binding_count": parse_int(values.get("rep.binding_count")),
        "matched_actor_count": parse_int(values.get("rep.matched_actor_count")),
        "local_found": values.get("local.found") == "true",
        "snapshot_hp": parse_float(values.get("snapshot.hp")),
        "local_hp": parse_float(values.get("local.hp")),
        "snapshot_x": parse_float(values.get("snapshot.x")),
        "snapshot_y": parse_float(values.get("snapshot.y")),
        "local_x": parse_float(values.get("local.x")),
        "local_y": parse_float(values.get("local.y")),
    }


def assert_held_sample(sample: dict[str, Any]) -> None:
    if not sample["apply_valid"] or not sample["holding_stale_snapshot"]:
        raise VerifyFailure(f"client never entered stale-authority hold: {sample}")
    if sample["binding_count"] < 1 or not sample["local_found"]:
        raise VerifyFailure(f"stale hold lost the native enemy binding: {sample}")
    if abs(sample["snapshot_hp"] - sample["local_hp"]) > 0.05:
        raise VerifyFailure(f"stale hold did not preserve authoritative enemy HP: {sample}")
    drift = math.hypot(
        sample["snapshot_x"] - sample["local_x"],
        sample["snapshot_y"] - sample["local_y"],
    )
    if not math.isfinite(drift) or drift > 8.0:
        raise VerifyFailure(
            f"stale hold allowed egregious native enemy position drift: drift={drift} sample={sample}"
        )


def verify_spawned_enemy_stale_hold(
    suspend_ms: int,
    manual_prelude: dict[str, Any],
    spawn: dict[str, Any],
) -> dict[str, Any]:
    network_id = int(spawn["network_actor_id"])
    primary.find_target(
        primary.HOST_PIPE,
        1800.0,
        1750.0,
        network_id,
        timeout=8.0,
        require_local_binding=False,
    )
    before = compact_sample(
        primary.find_target(
            CLIENT_ENDPOINT,
            1800.0,
            1750.0,
            network_id,
            timeout=8.0,
        )
    )
    if not before["apply_valid"] or before["binding_count"] < 1:
        raise VerifyFailure(f"client enemy binding was not ready before suspension: {before}")

    host_pid = find_host_pid()
    suspension = suspend_host_game(host_pid, suspend_ms)
    held_samples: list[dict[str, Any]] = []
    try:
        deadline = time.monotonic() + suspend_ms / 1000.0 - 0.2
        while time.monotonic() < deadline:
            sample = compact_sample(
                primary.find_target_or_last(
                    CLIENT_ENDPOINT,
                    1800.0,
                    1750.0,
                    network_id,
                )
            )
            held_samples.append(sample)
            time.sleep(0.12)
    finally:
        try:
            suspension.wait(timeout=max(10.0, suspend_ms / 1000.0 + 5.0))
        except subprocess.TimeoutExpired:
            suspension.kill()
            suspension.wait(timeout=2.0)
            raise VerifyFailure("Windows host suspension helper did not resume on time")
    stderr = suspension.stderr.read().strip() if suspension.stderr is not None else ""
    if suspension.returncode != 0:
        raise VerifyFailure(f"Windows host suspension helper failed: {stderr}")

    held = next(
        (sample for sample in held_samples if sample["holding_stale_snapshot"]),
        None,
    )
    if held is None:
        raise VerifyFailure(
            f"client did not expose a stale-authority hold during {suspend_ms}ms host stall: "
            f"samples={held_samples}"
        )
    assert_held_sample(held)

    resume_deadline = time.monotonic() + 12.0
    resumed: dict[str, Any] = {}
    while time.monotonic() < resume_deadline:
        resumed = compact_sample(
            primary.find_target_or_last(
                CLIENT_ENDPOINT,
                1800.0,
                1750.0,
                network_id,
            )
        )
        if (
            resumed["apply_valid"]
            and not resumed["holding_stale_snapshot"]
            and resumed["source_snapshot_age_ms"] < 800
            and resumed["local_found"]
        ):
            break
        time.sleep(0.12)
    else:
        raise VerifyFailure(f"fresh world snapshots did not resume: {resumed}")

    return {
        "ok": True,
        "transport": "steam_friend",
        "same_machine": PAIR_BACKEND == "wsl",
        "suspend_ms": suspend_ms,
        "manual_prelude": manual_prelude,
        "before": before,
        "held": held,
        "held_sample_count": len(held_samples),
        "max_observed_source_snapshot_age_ms": max(
            sample["source_snapshot_age_ms"] for sample in held_samples
        ),
        "resumed": resumed,
        "spawn": {
            "setup_hp": spawn["setup_hp"],
            "freeze_on_spawn": spawn["freeze_on_spawn"],
        },
    }


def run(pair: SteamFriendActivePair, suspend_ms: int) -> dict[str, Any]:
    pair_state = pair.discover()
    if any(pair_state[side].get("scene") != "testrun" for side in ("host", "client")):
        raise VerifyFailure(f"Steam friend pair is not in testrun: {pair_state}")
    configure(pair)
    primary.cleanup_live_enemies()
    manual_prelude = primary.enable_manual_stock_spawner_combat()
    primary.cleanup_live_enemies()
    spawn = primary.spawn_one_enemy(
        1800.0,
        1750.0,
        primary.SETUP_TARGET_HP,
        freeze_on_spawn=True,
    )
    try:
        return verify_spawned_enemy_stale_hold(
            suspend_ms,
            manual_prelude,
            spawn,
        )
    finally:
        primary.cleanup_live_enemies()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suspend-ms", type=int, default=4000)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.suspend_ms < 1800 or args.suspend_ms > 10000:
        raise SystemExit("--suspend-ms must be between 1800 and 10000")

    pair = SteamFriendActivePair()
    result: dict[str, Any]
    return_code = 1
    try:
        result = run(pair, args.suspend_ms)
        return_code = 0
    except Exception as exc:
        result = {
            "ok": False,
            "error": str(exc),
            "error_type": type(exc).__name__,
            "traceback": traceback.format_exc(),
        }
    finally:
        pair.close()
    result = pair.redact(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "ok": result.get("ok", False),
                "error": result.get("error"),
                "held": result.get("held"),
                "resumed": result.get("resumed"),
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
