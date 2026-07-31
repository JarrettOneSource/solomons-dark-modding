#!/usr/bin/env python3
"""Verify Bot Play For Me through stock solo wave 5 and clean release."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import time
import traceback
from types import SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools._real_flow_e2e.evidence import (  # noqa: E402
    write_json,
    write_manifest,
)
from tools._real_flow_e2e.runtime import (  # noqa: E402
    LuaPipe,
    RuntimeProbeError,
    effective_wave_index,
)
from tools._real_flow_e2e.windows import (  # noqa: E402
    BOT_PLAY_TEAM_ROSTER,
    PowerShell,
    WindowsHarnessError,
    assert_ports_free,
    capture_window,
    port_inventory,
    send_key,
    windows_path,
    windows_processes,
)
from tools.verify_local_multiplayer_sync import (  # noqa: E402
    extract_json,
    parse_key_values,
)
from tools.verify_real_flow_e2e import (  # noqa: E402
    BOT_MOD_ID,
    _assert_clean_release,
    _bot_is_driving,
    _bot_probe,
    _drain_damage_observations,
    _indicator_region_assertion,
    _reset_damage_observations,
    _set_bot_play,
    _udp_exclusion_inventory,
    _visible_living_enemy,
    _wait_for_bot_state,
)


PARTICIPANT_ID = 0x2B00000000000003


class SoloBotPlayFailure(RuntimeError):
    """The isolated solo takeover did not satisfy its live contract."""


def _git_sha() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=15,
        check=False,
    )
    value = completed.stdout.strip().lower()
    if completed.returncode != 0 or len(value) != 40:
        raise SoloBotPlayFailure(
            f"could not resolve source SHA: {completed.stdout.strip()}"
        )
    return value


def _stage_package(
    package_root: Path,
    evidence_root: Path,
) -> Path:
    destination = evidence_root / "staging" / "launcher"
    if destination.exists():
        raise SoloBotPlayFailure(
            f"solo package staging path must be new: {destination}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        package_root,
        destination,
        symlinks=False,
        copy_function=shutil.copy2,
    )
    bot_source = ROOT / "mods" / "bot-brain"
    bot_destination = destination / "mods" / "bot-brain"
    if not (bot_source / "manifest.json").is_file():
        raise SoloBotPlayFailure(
            f"Bot Play For Me source is missing: {bot_source}"
        )
    bot_destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        bot_source,
        bot_destination,
        symlinks=False,
        copy_function=shutil.copy2,
    )
    return destination


def _write_initial_settings(
    evidence_root: Path,
    behavior: str,
    roster: list[dict[str, str]],
) -> Path:
    path = evidence_root / "inputs" / "bot.brain.initial.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "values": {
                    "play_for_me": False,
                    "play_for_me_behavior": behavior,
                    "roster": roster,
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _launch(
    *,
    bundle_root: Path,
    runtime_root: Path,
    game_directory: Path,
    settings_path: Path,
    evidence_root: Path,
    instance: str,
    local_port: int,
    unused_remote_port: int,
    element: str,
    discipline: str,
    max_participants: int,
) -> dict[str, Any]:
    ledger = evidence_root / "safety" / "process-ledger.json"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "powershell.exe",
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        "scripts/Launch-LocalSoloSession.ps1",
        "-Instance",
        instance,
        "-Preset",
        f"map_create_{element}_{discipline}_hub",
        "-RuntimeRoot",
        windows_path(runtime_root),
        "-LocalPort",
        str(local_port),
        "-UnusedRemotePort",
        str(unused_remote_port),
        "-ParticipantId",
        f"0x{PARTICIPANT_ID:X}",
        "-PlayerName",
        "Bply Solo",
        "-GameDirectory",
        windows_path(game_directory),
        "-LauncherPath",
        windows_path(
            bundle_root
            / "launcher"
            / "SolomonDarkModLauncher.exe"
        ),
        "-FreshInstall",
        "-QuickStart",
        "-QuickStartElement",
        element,
        "-QuickStartDiscipline",
        discipline,
        "-ExactModIds",
        BOT_MOD_ID,
        "-BotSettingsPath",
        windows_path(settings_path),
        "-LuaExecTargetModId",
        BOT_MOD_ID,
        "-MaxParticipants",
        str(max_participants),
        "-ProcessIdOutputPath",
        windows_path(ledger),
    ]
    environment = os.environ.copy()
    environment["SDMOD_DISABLE_AUDIO"] = "1"
    environment["SDMOD_ENABLE_AUDIO"] = "0"
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=environment,
        bufsize=1,
    )
    assert process.stdout is not None
    parsed: dict[str, Any] | None = None
    output = ""
    try:
        deadline = time.monotonic() + 120.0
        while time.monotonic() < deadline:
            ready, _, _ = select.select([process.stdout], [], [], 0.1)
            if ready:
                line = process.stdout.readline()
                if line:
                    output += line
                    parsed = extract_json(output)
                    if parsed is not None:
                        break
                elif process.poll() is not None:
                    break
            if process.poll() is not None:
                output += process.stdout.read()
                parsed = extract_json(output)
                break
        if parsed is None or parsed.get("success") is not True:
            raise SoloBotPlayFailure(
                "isolated solo launcher failed: "
                f"exit={process.poll()} output={output}"
            )
        return parsed
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                process.kill()


def _ledger_process_id(path: Path) -> int:
    if not path.is_file():
        return 0
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return 0
    if not isinstance(document, dict):
        return 0
    try:
        return int(document.get("processId", 0))
    except (TypeError, ValueError):
        return 0


def _wait_scene(
    pipe: LuaPipe,
    scene_name: str,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    last_error = ""
    while time.monotonic() < deadline:
        try:
            last = pipe.state()
            last_error = ""
            if last["scene"]["name"] == scene_name:
                return last
        except RuntimeProbeError as exc:
            last_error = str(exc)
        time.sleep(0.2)
    raise SoloBotPlayFailure(
        f"solo did not reach {scene_name}: last={last} "
        f"error={last_error!r}"
    )


def _wait_run_ready(
    pipe: LuaPipe,
    timeout: float,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = parse_key_values(
            pipe.execute(
                """
local scene = sd.world.get_scene()
local combat = sd.gameplay.get_combat_state()
local player = sd.player.get_state()
local runtime = sd.runtime.get_multiplayer_state()
local loading = runtime and runtime.run_loading_barrier or {}
local participant = nil
for _, row in ipairs(runtime and runtime.participants or {}) do
  if row.kind == "LocalHuman" and row.controller_kind == "Native" then
    participant = row
    break
  end
end
print("scene=" .. tostring(scene and scene.name or ""))
print("transitioning=" ..
  tostring(scene and scene.transitioning or false))
print("world_id=" .. tostring(scene and scene.world_id or 0))
print("actor_address=" ..
  tostring(player and player.actor_address or 0))
print("participant_id=" ..
  tostring(participant and participant.participant_id or 0))
print("runtime_valid=" ..
  tostring(participant and participant.runtime_valid or false))
print("in_run=" ..
  tostring(participant and participant.in_run or false))
print("barrier_released=" ..
  tostring(loading and loading.released or false))
print("combat_wave=" ..
  tostring(combat and combat.wave_index or -1))
print("combat_active=" ..
  tostring(combat and combat.active or false))
"""
            )
        )
        try:
            world_id = int(last.get("world_id", "0"), 0)
            actor_address = int(last.get("actor_address", "0"), 0)
            participant_id = int(last.get("participant_id", "0"), 0)
            combat_wave = int(last.get("combat_wave", "-1"), 0)
        except ValueError:
            time.sleep(0.1)
            continue
        if (
            last.get("scene") == "testrun"
            and last.get("transitioning") == "false"
            and world_id > 0
            and actor_address > 0
            and participant_id > 0
            and last.get("runtime_valid") == "true"
            and last.get("in_run") == "true"
            and last.get("barrier_released") == "true"
            and combat_wave == 0
            and last.get("combat_active") == "false"
        ):
            return last
        time.sleep(0.1)
    raise SoloBotPlayFailure(
        "solo run never reached the stock pre-wave start window: "
        f"{last}"
    )


def _wait_run_loading_started(
    pipe: LuaPipe,
    timeout: float,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = parse_key_values(
            pipe.execute(
                """
local runtime = sd.runtime.get_multiplayer_state()
local loading = runtime and runtime.run_loading_barrier or {}
local participant = nil
for _, row in ipairs(runtime and runtime.participants or {}) do
  if row.kind == "LocalHuman" and row.controller_kind == "Native" then
    participant = row
    break
  end
end
print("in_run=" ..
  tostring(participant and participant.in_run or false))
print("run_nonce=" ..
  tostring(participant and participant.run_nonce or 0))
print("active=" .. tostring(loading.active or false))
print("released=" .. tostring(loading.released or false))
"""
            )
        )
        try:
            run_nonce = int(last.get("run_nonce", "0"), 0)
        except ValueError:
            run_nonce = 0
        if (
            last.get("in_run") == "true"
            and run_nonce > 0
            and last.get("active") == "true"
        ):
            return last
        time.sleep(0.05)
    raise SoloBotPlayFailure(
        f"stock solo run loading never started: {last}"
    )


def _wait_live_wave(
    pipe: LuaPipe,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = pipe.state()
        if (
            last["scene"]["name"] == "testrun"
            and effective_wave_index(last) >= 1
            and len(last["nativeEnemies"]) > 0
        ):
            return last
        time.sleep(0.1)
    raise SoloBotPlayFailure(
        f"stock solo wave 1 never became live: {last}"
    )


def _request_until_true(
    pipe: LuaPipe,
    code: str,
    *,
    timeout: float,
    label: str,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        output = pipe.execute(
            f"""
local ok, value = pcall(function()
  return {code}
end)
print("call_ok=" .. tostring(ok))
print("accepted=" .. tostring(ok and value == true))
print("value=" .. tostring(value or ""))
"""
        )
        last = {}
        for line in output.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                last[key.strip()] = value.strip()
        if (
            last.get("call_ok") == "true"
            and last.get("accepted") == "true"
        ):
            return last
        time.sleep(0.25)
    raise SoloBotPlayFailure(
        f"{label} was never accepted: {last}"
    )


def _exact_process(
    ps: PowerShell,
    process_id: int,
    expected_path: str,
) -> dict[str, Any]:
    matching = [
        process
        for process in windows_processes(ps)
        if process.pid == process_id
    ]
    if len(matching) != 1:
        raise SoloBotPlayFailure(
            f"expected one exact solo PID {process_id}: {matching}"
        )
    process = matching[0]
    if process.executable_path.casefold() != expected_path.casefold():
        raise SoloBotPlayFailure(
            "solo PID escaped its staged executable: "
            f"expected={expected_path} actual={process.executable_path}"
        )
    return asdict(process)


def _stop_exact_process(
    ps: PowerShell,
    process_id: int,
    expected_path: str,
) -> dict[str, Any]:
    matching = [
        process
        for process in windows_processes(ps)
        if process.pid == process_id
    ]
    if not matching:
        return {
            "pid": process_id,
            "expectedPath": expected_path,
            "result": "already-exited",
        }
    process = matching[0]
    if process.executable_path.casefold() != expected_path.casefold():
        raise SoloBotPlayFailure(
            "refusing cleanup because the exact PID changed executable: "
            f"pid={process_id} expected={expected_path} "
            f"actual={process.executable_path}"
        )
    ps.run(
        f"""
$target=Get-CimInstance Win32_Process -Filter 'ProcessId={process_id}'
if($null -eq $target){{return}}
if(-not [string]::Equals(
    [string]$target.ExecutablePath,
    '{expected_path.replace("'", "''")}',
    [System.StringComparison]::OrdinalIgnoreCase)){{
  throw 'exact staged executable changed before cleanup'
}}
Stop-Process -Id {process_id} -Force
""",
        timeout=15,
    )
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if not any(
            process.pid == process_id
            for process in windows_processes(ps)
        ):
            return {
                "pid": process_id,
                "expectedPath": expected_path,
                "result": "stopped",
            }
        time.sleep(0.2)
    raise SoloBotPlayFailure(
        f"exact solo PID remained after cleanup: {process_id}"
    )


def _copy_runtime_artifacts(
    runtime_root: Path,
    instance: str,
    evidence_root: Path,
) -> dict[str, str]:
    stage = (
        runtime_root
        / "instances"
        / instance
        / "stage"
    )
    output = evidence_root / "runtime"
    output.mkdir(parents=True, exist_ok=True)
    copied: dict[str, str] = {}
    for relative in (
        Path(".sdmod/logs"),
        Path(".sdmod/startup-status.json"),
        Path(".sdmod/multiplayer-session-status.json"),
        Path(".sdmod/mod-settings/bot.brain.json"),
    ):
        source = stage / relative
        if not source.exists():
            continue
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)
        copied[relative.as_posix()] = str(destination)
    return copied


def run(args: argparse.Namespace) -> dict[str, Any]:
    actual_sha = _git_sha()
    if actual_sha != args.expected_source_sha.lower():
        raise SoloBotPlayFailure(
            "source SHA changed: "
            f"expected={args.expected_source_sha} actual={actual_sha}"
        )
    if not args.instance.startswith("bply"):
        raise SoloBotPlayFailure("solo instance must use bply prefix")
    if args.evidence_root.exists():
        raise SoloBotPlayFailure(
            f"solo evidence root must be new: {args.evidence_root}"
        )
    args.evidence_root.mkdir(parents=True, exist_ok=False)
    write_json(
        args.evidence_root / "source.json",
        {
            "expectedSha": args.expected_source_sha,
            "actualSha": actual_sha,
            "sourceRoot": str(ROOT),
        },
    )

    ps = PowerShell(ROOT)
    ports = {args.local_port, args.unused_remote_port}
    exclusions = _udp_exclusion_inventory(ps, ports)
    assert_ports_free(ps, ports)
    before = {
        "utcNanoseconds": time.time_ns(),
        "udpExclusions": exclusions,
        "reservedPorts": port_inventory(ps, ports),
        "processes": [asdict(row) for row in windows_processes(ps)],
    }
    write_json(args.evidence_root / "safety" / "before.json", before)

    bundle_root = _stage_package(
        args.package_root,
        args.evidence_root,
    )
    runtime_root = args.evidence_root / "staging" / "runtime"
    settings_path = _write_initial_settings(
        args.evidence_root,
        args.behavior,
        BOT_PLAY_TEAM_ROSTER[:args.bot_teammates],
    )
    launch: dict[str, Any] = {}
    process_id = 0
    expected_executable = windows_path(
        runtime_root
        / "instances"
        / args.instance
        / "stage"
        / "SolomonDark.exe"
    )
    peer: Any = None
    primary_error: BaseException | None = None
    result: dict[str, Any] = {
        "schemaVersion": 1,
        "ok": False,
        "sourceSha": actual_sha,
        "instance": args.instance,
        "ports": [args.local_port, args.unused_remote_port],
        "participantId": PARTICIPANT_ID,
        "audioDisabledRequired": True,
        "behavior": args.behavior,
        "element": args.element,
        "discipline": args.discipline,
        "runSeed": args.run_seed,
        "maxParticipants": max(2, 1 + args.bot_teammates),
        "syntheticTeamRoster": (
            BOT_PLAY_TEAM_ROSTER[:args.bot_teammates]
        ),
        "targetWaveAlive": args.target_wave,
    }
    cleanup: dict[str, Any] = {}
    try:
        launch = _launch(
            bundle_root=bundle_root,
            runtime_root=runtime_root,
            game_directory=args.game_directory,
            settings_path=settings_path,
            evidence_root=args.evidence_root,
            instance=args.instance,
            local_port=args.local_port,
            unused_remote_port=args.unused_remote_port,
            element=args.element,
            discipline=args.discipline,
            max_participants=max(2, 1 + args.bot_teammates),
        )
        result["launch"] = launch
        if launch.get("audioDisabled") is not True:
            raise SoloBotPlayFailure(
                f"solo launch did not disable audio: {launch}"
            )
        process_id = int(launch["processId"])
        result["ownedProcess"] = _exact_process(
            ps,
            process_id,
            expected_executable,
        )
        pipe = LuaPipe(ROOT, str(launch["luaPipe"]))
        peer = SimpleNamespace(
            runtime_root=runtime_root,
            config=SimpleNamespace(instance=args.instance),
            game_pid=process_id,
        )

        result["hub"] = _wait_scene(pipe, "hub", 45.0)
        initial_bot = _bot_probe(pipe)
        if (
            initial_bot.get("loaded") is not True
            or initial_bot.get("desired") is not False
            or initial_bot.get("active") is not False
        ):
            raise SoloBotPlayFailure(
                "solo bot mod did not load disabled for the mid-session "
                f"takeover: {initial_bot}"
            )
        result["initialBot"] = initial_bot
        result["runSeedRequest"] = _request_until_true(
            pipe,
            (
                f"sd.rng.set_seed({args.run_seed}) == "
                f"{args.run_seed}"
            ),
            timeout=10.0,
            label="deterministic stock run seed",
        )
        result["startRun"] = _request_until_true(
            pipe,
            "sd.hub.start_match()",
            timeout=30.0,
            label="stock solo Start Match request",
        )
        result["runLoadingStarted"] = _wait_run_loading_started(
            pipe,
            20.0,
        )
        result["runMaterialized"] = _wait_scene(
            pipe,
            "testrun",
            45.0,
        )
        result["runReady"] = _wait_run_ready(pipe, 45.0)
        result["waveStart"] = _request_until_true(
            pipe,
            "sd.gameplay.start_waves()",
            timeout=20.0,
            label="stock wave start request",
        )
        result["stockWaveBeforeTakeover"] = _wait_live_wave(
            pipe,
            30.0,
        )
        result["toggleOnRequest"] = _set_bot_play(
            peer,
            pipe,
            enabled=True,
            behavior=args.behavior,
            roster=BOT_PLAY_TEAM_ROSTER[:args.bot_teammates],
        )
        active_bot = _wait_for_bot_state(
            pipe,
            lambda state: (
                state.get("loaded") is True
                and state.get("desired") is True
                and state.get("active") is True
                and state.get("takeover.active") is True
                and int(state.get("participant_id", 0)) > 0
            ),
            timeout=10.0,
            label="solo mid-session takeover",
        )
        runtime_participant_id = int(active_bot["participant_id"])
        result["activeBot"] = active_bot
        result["runtimeParticipantId"] = runtime_participant_id
        result["transportParticipantId"] = PARTICIPANT_ID
        result["damageObserversReset"] = (
            _reset_damage_observations(
                pipe,
                target_mod_id=BOT_MOD_ID,
            )
        )

        enemy_rows: list[dict[str, Any]] = []
        player_rows: list[dict[str, Any]] = []
        samples: list[dict[str, Any]] = []
        result["samples"] = samples
        screenshot: dict[str, Any] | None = None
        final_state: dict[str, Any] | None = None
        final_bot: dict[str, Any] | None = None
        death_events: list[dict[str, Any]] = []
        respawn_events: list[dict[str, Any]] = []
        was_alive = True
        deadline = time.monotonic() + args.timeout_seconds
        while time.monotonic() < deadline:
            state = pipe.state()
            bot = _bot_probe(pipe)
            _drain_damage_observations(
                pipe,
                enemy_rows,
                player_rows,
                target_mod_id=BOT_MOD_ID,
            )
            wave = effective_wave_index(state)
            sample = {
                "utcNanoseconds": time.time_ns(),
                "wave": wave,
                "phase": state["wave"]["phase"],
                "hp": state["player"]["hp"],
                "maxHp": state["player"]["maxHp"],
                "enemyCount": len(state["nativeEnemies"]),
                "botMode": bot.get("brain.mode"),
                "botThinkCount": bot.get("brain.think_count"),
                "botMoveAccepted": bot.get("brain.move_accepted"),
                "botCastIssued": bot.get("brain.cast_issued"),
                "botCastAccepted": bot.get("brain.cast_accepted"),
                "botLiveEnemies": bot.get("brain.live_enemy_count"),
                "botAttackWindowMax": bot.get(
                    "brain.attack_window_max"
                ),
                "botNearestEnemyDistance": bot.get(
                    "brain.nearest_enemy_distance"
                ),
                "botTargetDistance": bot.get(
                    "brain.target_distance"
                ),
                "botHpRatio": bot.get("brain.hp_ratio"),
                "x": state["player"]["x"],
                "y": state["player"]["y"],
                "damageEdges": len(enemy_rows),
            }
            samples.append(sample)
            alive = float(state["player"]["hp"]) > 0.0
            if was_alive and not alive:
                death_events.append(sample)
            elif not was_alive and alive:
                respawn_events.append(sample)
            was_alive = alive
            if (
                screenshot is None
                and wave >= 2
                and int(bot.get("brain.cast_accepted", 0)) > 0
                and _visible_living_enemy(state)
            ):
                capture_path = (
                    args.evidence_root
                    / "screenshots"
                    / f"solo-bot-fighting-wave-{wave}.png"
                )
                screenshot = capture_window(
                    ROOT,
                    peer,
                    capture_path,
                )
                screenshot["indicator"] = (
                    _indicator_region_assertion(capture_path)
                )
                screenshot["visibleLivingEnemy"] = True
                screenshot["botState"] = bot
            if state["scene"]["name"] != "testrun":
                raise SoloBotPlayFailure(
                    "solo bot party left the run before wave "
                    f"{args.target_wave}: {sample}"
                )
            if (
                wave >= args.target_wave
                and alive
                and _bot_is_driving(bot, runtime_participant_id)
                and int(bot.get("brain.move_accepted", 0)) > 0
                and int(bot.get("brain.cast_accepted", 0)) > 0
                and any(
                    row["sourceParticipantId"] == PARTICIPANT_ID
                    and row["damage"] > 0.0
                    for row in enemy_rows
                )
            ):
                final_state = state
                final_bot = bot
                break
            time.sleep(0.25)
        result["stockLifecycle"] = {
            "deathEvents": death_events,
            "respawnEvents": respawn_events,
        }
        if final_state is None or final_bot is None:
            raise SoloBotPlayFailure(
                "solo takeover did not reach wave "
                f"{args.target_wave} alive: "
                f"{samples[-1] if samples else {}}"
            )
        if screenshot is None:
            raise SoloBotPlayFailure(
                "solo bot never produced an indicator-and-fighting capture"
            )
        result["finalState"] = final_state
        result["finalBot"] = final_bot
        result["fightingCapture"] = screenshot
        result["damageMetrics"] = {
            "runtimeSlotId": runtime_participant_id,
            "transportParticipantId": PARTICIPANT_ID,
            "damageDealt": sum(
                row["damage"]
                for row in enemy_rows
                if row["sourceParticipantId"] == PARTICIPANT_ID
            ),
            "damageDealtEdges": len(
                [
                    row
                    for row in enemy_rows
                    if row["sourceParticipantId"]
                    == PARTICIPANT_ID
                    and row["damage"] > 0.0
                ]
            ),
            "damageTaken": sum(
                row["damage"]
                for row in player_rows
                if row["targetParticipantId"] == PARTICIPANT_ID
            ),
            "damageTakenEdges": len(
                [
                    row
                    for row in player_rows
                    if row["targetParticipantId"] == PARTICIPANT_ID
                    and row["damage"] > 0.0
                ]
            ),
            "enemyRows": enemy_rows,
            "playerRows": player_rows,
        }

        result["toggleOffRequest"] = _set_bot_play(
            peer,
            pipe,
            enabled=False,
            behavior=args.behavior,
            roster=BOT_PLAY_TEAM_ROSTER[:args.bot_teammates],
        )
        released = _wait_for_bot_state(
            pipe,
            lambda state: (
                state.get("desired") is False
                and state.get("active") is False
                and state.get("takeover.active") is False
                and state.get("takeover.clean") is True
            ),
            timeout=5.0,
            label="solo clean takeover release",
        )
        result["cleanRelease"] = _assert_clean_release(released)

        movement_attempts: list[dict[str, Any]] = []
        for key in ("d", "w", "a", "s"):
            before_input = pipe.state()
            helper = send_key(ROOT, peer, key, 600)
            input_deadline = time.monotonic() + 3.0
            after_input = before_input
            while time.monotonic() < input_deadline:
                after_input = pipe.state()
                displacement = math.dist(
                    (
                        float(before_input["player"]["x"]),
                        float(before_input["player"]["y"]),
                    ),
                    (
                        float(after_input["player"]["x"]),
                        float(after_input["player"]["y"]),
                    ),
                )
                if displacement >= 4.0:
                    break
                time.sleep(0.1)
            displacement = math.dist(
                (
                    float(before_input["player"]["x"]),
                    float(before_input["player"]["y"]),
                ),
                (
                    float(after_input["player"]["x"]),
                    float(after_input["player"]["y"]),
                ),
            )
            movement_attempts.append(
                {
                    "key": key,
                    "helper": helper,
                    "before": before_input["player"],
                    "after": after_input["player"],
                    "displacement": displacement,
                }
            )
            if displacement >= 4.0:
                break
        if not any(
            row["displacement"] >= 4.0
            for row in movement_attempts
        ):
            raise SoloBotPlayFailure(
                "human physical control did not resume after clean release: "
                f"{movement_attempts}"
            )
        result["humanControlProof"] = {
            "method": "physical-window-key-after-clean-release",
            "attempts": movement_attempts,
            "takeoverStillClean": _assert_clean_release(
                _bot_probe(pipe)
            ),
        }
        result["ok"] = True
        return result
    except BaseException as exc:
        primary_error = exc
        result["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        return result
    finally:
        if process_id <= 0:
            process_id = _ledger_process_id(
                args.evidence_root / "safety" / "process-ledger.json"
            )
            if process_id > 0:
                cleanup["recoveredProcessId"] = process_id
        if process_id > 0 and expected_executable:
            try:
                cleanup["processStop"] = _stop_exact_process(
                    ps,
                    process_id,
                    expected_executable,
                )
            except BaseException as exc:
                cleanup["processStopError"] = (
                    f"{type(exc).__name__}: {exc}"
                )
                result["ok"] = False
        try:
            cleanup["runtimeArtifacts"] = _copy_runtime_artifacts(
                runtime_root,
                args.instance,
                args.evidence_root,
            )
        except BaseException as exc:
            cleanup["artifactError"] = f"{type(exc).__name__}: {exc}"
            result["ok"] = False
        try:
            staging_root = args.evidence_root / "staging"
            if staging_root.is_dir():
                shutil.rmtree(staging_root)
                cleanup["stagingDeleted"] = str(staging_root)
        except BaseException as exc:
            cleanup["stagingDeleteError"] = (
                f"{type(exc).__name__}: {exc}"
            )
            result["ok"] = False
        try:
            after_ports = port_inventory(ps, ports)
            write_json(
                args.evidence_root / "safety" / "after.json",
                {
                    "utcNanoseconds": time.time_ns(),
                    "reservedPorts": after_ports,
                    "ownedProcess": (
                        [
                            asdict(row)
                            for row in windows_processes(ps)
                            if row.pid == process_id
                        ]
                        if process_id > 0
                        else []
                    ),
                },
            )
            if after_ports:
                cleanup["residualPorts"] = after_ports
                result["ok"] = False
        except BaseException as exc:
            cleanup["afterInventoryError"] = (
                f"{type(exc).__name__}: {exc}"
            )
            result["ok"] = False
        result["cleanup"] = cleanup
        if primary_error is None and not result["ok"]:
            result.setdefault(
                "error",
                {
                    "type": "CleanupFailure",
                    "message": "solo acceptance passed but cleanup failed",
                },
            )
        write_json(args.evidence_root / "result.json", result)
        write_manifest(args.evidence_root)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--package-root",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--game-directory",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--evidence-root",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--expected-source-sha",
        required=True,
    )
    parser.add_argument("--instance", default="bply-solo")
    parser.add_argument("--local-port", type=int, default=51411)
    parser.add_argument(
        "--unused-remote-port",
        type=int,
        default=51412,
    )
    parser.add_argument("--target-wave", type=int, default=5)
    parser.add_argument(
        "--behavior",
        choices=("skirmisher", "guardian", "striker", "learned"),
        default="skirmisher",
        help="existing bot-brain policy used for the acceptance run",
    )
    parser.add_argument(
        "--element",
        choices=("fire", "water", "earth", "air", "ether"),
        default="air",
    )
    parser.add_argument(
        "--discipline",
        choices=("mind", "body", "arcane"),
        default="mind",
    )
    parser.add_argument(
        "--bot-teammates",
        type=int,
        choices=range(0, 4),
        default=3,
        help=(
            "existing synthetic teammates used by the solo wave gate; "
            "defaults to the proven three-bot roster"
        ),
    )
    parser.add_argument(
        "--run-seed",
        type=lambda value: int(value, 0),
        default=0x0AD0633B,
        help=(
            "authority-owned native run-generation seed; defaults to the "
            "recorded wave-21 acceptance layout"
        ),
    )
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    args = parser.parse_args()
    args.package_root = args.package_root.resolve()
    args.game_directory = args.game_directory.resolve()
    args.evidence_root = args.evidence_root.resolve()
    if not (args.package_root / "SolomonDarkMultiplayerBeta.exe").is_file():
        parser.error("package root is missing the desktop launcher")
    if not (
        args.package_root
        / "launcher"
        / "SolomonDarkModLauncher.exe"
    ).is_file():
        parser.error("package root is missing the CLI launcher")
    if not (args.game_directory / "SolomonDark.exe").is_file():
        parser.error("game directory is missing SolomonDark.exe")
    if (
        args.local_port == args.unused_remote_port
        or min(args.local_port, args.unused_remote_port) < 51400
    ):
        parser.error("solo ports must be distinct and at or above 51400")
    if args.target_wave < 5:
        parser.error("target wave must be at least 5")
    if not 1 <= args.run_seed <= 0x3FFFFFFF:
        parser.error("run seed must be in the range 1..0x3fffffff")
    return args


def main() -> int:
    args = parse_args()
    try:
        result = run(args)
    except (
        OSError,
        RuntimeError,
        SoloBotPlayFailure,
        WindowsHarnessError,
    ) as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if result.get("ok") is not True:
        print(
            "FAIL: " + json.dumps(result.get("error", {}), sort_keys=True),
            file=sys.stderr,
        )
        return 1
    print(
        "PASS: "
        + json.dumps(
            {
                "evidenceRoot": str(args.evidence_root),
                "sourceSha": result["sourceSha"],
                "targetWaveAlive": result["targetWaveAlive"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
