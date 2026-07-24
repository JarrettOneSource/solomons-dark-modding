#!/usr/bin/env python3
"""Verify stock Game Over semantics for solo and terminal multiplayer deaths."""

from __future__ import annotations

import argparse
import json
import math
import ntpath
import os
import select
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from PIL import Image

from multiplayer_defense_behavior_harness import invoke_native_magic_hit_trial
from multiplayer_frame_capture import capture_game_backbuffer
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    HOST_ID,
    HOST_NAME,
    ROOT,
    THIRD_ID,
    THIRD_NAME,
    VerifyFailure,
    extract_json,
    game_process_ids,
    launch_pair,
    lua,
    parse_key_values,
    path_for_powershell,
    select_available_windows_udp_ports,
    start_testrun,
    wait_for_remote,
    wait_for_scene,
)
from verify_multiplayer_death_spectator_respawn import (
    death_presentation_state_matches,
    query_spectator_state,
    spectator_state_matches,
)
from verify_player_health_death_sync import set_local_player_vitals


ACCEPTANCE_MOD_ID = "sample.lua.ui_sandbox_lab"
SOLO_PARTICIPANT_ID = 0x2000000000001A01
SOLO_PLAYER_NAME = "Solo Game Over"
OUTPUT = ROOT / "runtime" / "game_over_session_semantics.json"
ARTIFACT_ROOT = ROOT / "runtime" / "game-over-acceptance"
SOLO_LAUNCHER = ROOT / "scripts" / "Launch-LocalSoloSession.ps1"
VITAL_TOLERANCE = 0.05


SESSION_STATE_PROBE = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local multiplayer = assert(sd.runtime.get_multiplayer_state())
local spectator = assert(multiplayer.death_spectator)
local terminal = multiplayer.game_over or {}
local player = sd.player.get_state()
local scene = sd.world.get_scene()
local ui = sd.ui and sd.ui.get_snapshot and sd.ui.get_snapshot() or nil
local local_row = nil
local connected_run_count = 0
local alive_run_count = 0
local remote_peer_count = 0
local run_nonce = 0
for _, participant in ipairs(multiplayer.participants or {}) do
  if participant.kind == "LocalHuman" then
    local_row = participant
    run_nonce = tonumber(participant.run_nonce) or 0
  elseif participant.transport_connected then
    remote_peer_count = remote_peer_count + 1
  end
end
for _, participant in ipairs(multiplayer.participants or {}) do
  if participant.ready and participant.transport_connected and
      participant.runtime_valid and participant.in_run and
      run_nonce ~= 0 and participant.run_nonce == run_nonce then
    connected_run_count = connected_run_count + 1
    local life_current = tonumber(participant.life_current)
    local life_max = tonumber(participant.life_max)
    if life_current ~= nil and life_max ~= nil and
        life_max > 0 and life_current > 0 then
      alive_run_count = alive_run_count + 1
    end
  end
end
emit("scene", scene and (scene.name or scene.kind) or "")
emit("surface", ui and ui.surface_id or "")
emit("participant_count", multiplayer.participant_count or 0)
emit("connected_run_count", connected_run_count)
emit("alive_run_count", alive_run_count)
emit("remote_peer_count", remote_peer_count)
emit("run_nonce", run_nonce)
emit("local_in_run", local_row and local_row.in_run or false)
emit("local_life_current", player and player.hp or
  (local_row and local_row.life_current or 0))
emit("local_life_max", player and player.max_hp or
  (local_row and local_row.life_max or 0))
emit("spectator_active", spectator.active)
emit("spectator_phase", spectator.phase)
emit("spectator_target_participant_id", spectator.target_participant_id)
emit("game_over_command_epoch", terminal.command_epoch or 0)
emit("game_over_accepted_epoch", terminal.accepted_epoch or 0)
emit("game_over_run_nonce", terminal.run_nonce or 0)
emit("game_over_authority_participant_id",
  terminal.authority_participant_id or 0)
emit("game_over_pending_dispatch", terminal.pending_dispatch or false)
emit("game_over_dispatch_count", terminal.dispatch_count or 0)
"""


def _number(values: Mapping[str, str], key: str) -> float:
    try:
        value = float(values.get(key, "nan"))
    except (TypeError, ValueError):
        return math.nan
    return value if math.isfinite(value) else math.nan


def _integer(values: Mapping[str, str], key: str) -> int:
    raw = values.get(key, "")
    try:
        return int(raw, 0)
    except (TypeError, ValueError):
        try:
            return int(float(raw))
        except (TypeError, ValueError, OverflowError):
            return -1


def _default_instance_prefix() -> str:
    return f"go-{os.getpid():x}-{time.time_ns() & 0xFFFF:04x}"


def _resolve_udp_ports(explicit: list[int | None]) -> list[int]:
    if all(port is None for port in explicit):
        return select_available_windows_udp_ports(5)
    if any(port is None for port in explicit):
        raise ValueError("all five ports must be provided together")
    ports = [int(port) for port in explicit if port is not None]
    if any(port < 1 or port > 0xFFFF for port in ports):
        raise ValueError("explicit UDP ports must be between 1 and 65535")
    if len(set(ports)) != 5:
        raise ValueError("explicit UDP ports must be distinct")
    return ports


def _windows_path_equal(left: str, right: str) -> bool:
    return ntpath.normcase(ntpath.normpath(left)) == ntpath.normcase(
        ntpath.normpath(right)
    )


def _powershell_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _query_process_executable(process_id: int) -> str | None:
    command = (
        f'$p=Get-CimInstance Win32_Process -Filter "ProcessId = {process_id}" '
        "-ErrorAction SilentlyContinue; "
        'if ($null -eq $p) { [Console]::Write("null"); exit 0 }; '
        "[Console]::Write(($p.ExecutablePath | ConvertTo-Json -Compress))"
    )
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10.0,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise VerifyFailure(
            f"could not resolve executable ownership for PID {process_id}: {detail}"
        )
    raw = completed.stdout.strip().lstrip("\ufeff")
    if raw == "null":
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise VerifyFailure(
            f"invalid executable ownership response for PID {process_id}: {raw!r}"
        ) from exc
    if not isinstance(value, str) or not value:
        raise VerifyFailure(
            f"missing executable ownership response for PID {process_id}: {value!r}"
        )
    return value


def validate_owned_processes(
    expected_paths: Mapping[int, str],
) -> dict[int, str]:
    validated: dict[int, str] = {}
    for process_id, expected_path in expected_paths.items():
        actual_path = _query_process_executable(process_id)
        if actual_path is None:
            raise VerifyFailure(
                f"owned game PID {process_id} exited before validation"
            )
        if not _windows_path_equal(actual_path, expected_path):
            raise VerifyFailure(
                "game process ownership mismatch: "
                f"pid={process_id} expected={expected_path!r} "
                f"actual={actual_path!r}"
            )
        validated[process_id] = actual_path
    return validated


def stop_owned_processes(expected_paths: Mapping[int, str]) -> None:
    """Stop only PIDs whose live executable still matches their instance stage."""

    for process_id, expected_path in expected_paths.items():
        command = (
            f'$p=Get-CimInstance Win32_Process -Filter "ProcessId = {process_id}" '
            "-ErrorAction SilentlyContinue; "
            "if ($null -eq $p) { exit 0 }; "
            f"$expected={_powershell_literal(expected_path)}; "
            "if (-not [string]::Equals("
            "$p.ExecutablePath,$expected,"
            "[System.StringComparison]::OrdinalIgnoreCase)) { "
            'throw "Executable ownership mismatch for exact PID." }; '
            f"Stop-Process -Id {process_id} -Force"
        )
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                command,
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10.0,
            check=False,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise VerifyFailure(
                f"exact cleanup failed for PID {process_id}: {detail}"
            )


def _expected_instance_executable(
    runtime_root: str,
    instance: str,
) -> str:
    return ntpath.join(
        runtime_root,
        "instances",
        instance.lower(),
        "stage",
        "SolomonDark.exe",
    )


def _read_process_ledger(path: Path) -> list[int]:
    if not path.is_file():
        return []
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    return game_process_ids(document) if isinstance(document, dict) else []


def launch_solo(
    *,
    instance: str,
    local_port: int,
    unused_remote_port: int,
    game_directory: Path,
) -> dict[str, object]:
    ledger = ROOT / "runtime" / f".game-over-solo-{os.getpid()}-{time.time_ns()}.json"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    args = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SOLO_LAUNCHER.relative_to(ROOT)).replace("/", "\\"),
        "-Instance",
        instance,
        "-Preset",
        "map_create_fire_mind_hub",
        "-LocalPort",
        str(local_port),
        "-UnusedRemotePort",
        str(unused_remote_port),
        "-ParticipantId",
        f"0x{SOLO_PARTICIPANT_ID:X}",
        "-PlayerName",
        SOLO_PLAYER_NAME,
        "-GameDirectory",
        path_for_powershell(game_directory),
        "-ExactModIds",
        ACCEPTANCE_MOD_ID,
        "-ProcessIdOutputPath",
        path_for_powershell(ledger),
    ]
    process = subprocess.Popen(
        args,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    assert process.stdout is not None
    parsed: dict[str, object] | None = None
    output = ""
    try:
        deadline = time.monotonic() + 90.0
        while time.monotonic() < deadline:
            ready, _, _ = select.select([process.stdout], [], [], 0.1)
            if ready:
                line = process.stdout.readline()
                if line:
                    output += line
                    parsed = extract_json(output)
                    if parsed is not None:
                        return parsed
                elif process.poll() is not None:
                    break
            if process.poll() is not None:
                output += process.stdout.read()
                parsed = extract_json(output)
                if parsed is not None:
                    return parsed
                break
        raise VerifyFailure(f"solo launcher did not return JSON:\n{output}")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                process.kill()
        if parsed is None:
            runtime_root = path_for_powershell(ROOT / "runtime")
            expected_path = _expected_instance_executable(
                runtime_root,
                instance,
            )
            for process_id in _read_process_ledger(ledger):
                stop_owned_processes({process_id: expected_path})
        ledger.unlink(missing_ok=True)


def query_session_state(pipe_name: str) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, SESSION_STATE_PROBE, timeout=8.0))


def _wait_for_state(
    pipe_name: str,
    predicate,
    *,
    timeout: float,
    description: str,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    last_error = ""
    while time.monotonic() < deadline:
        try:
            last = query_session_state(pipe_name)
            last_error = ""
            if predicate(last):
                return last
        except Exception as exc:  # noqa: BLE001 - retain live failure evidence.
            last_error = str(exc)
        time.sleep(0.05)
    error_suffix = f" last_error={last_error}" if last_error else ""
    raise VerifyFailure(
        f"timed out waiting for {description} on {pipe_name}; "
        f"last={last}.{error_suffix}"
    )


def _wait_for_spectator_state(
    pipe_name: str,
    predicate,
    *,
    timeout: float,
    description: str,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = query_spectator_state(pipe_name)
        if predicate(last):
            return last
        time.sleep(0.05)
    raise VerifyFailure(
        f"timed out waiting for {description} on {pipe_name}; last={last}"
    )


def _start_testrun_when_ready(
    host_pipe: str,
    *,
    timeout: float = 25.0,
) -> None:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            start_testrun(host_pipe)
            return
        except VerifyFailure as exc:
            last_error = str(exc)
        time.sleep(0.25)
    raise VerifyFailure(
        "testrun request never reached stable scene identity: "
        f"{last_error}"
    )


def _disable_bots(pipe_names: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for pipe_name in pipe_names:
        raw = lua(
            pipe_name,
            "lua_bots_disable_tick = true; sd.bots.clear(); "
            "return tostring(sd.bots.get_count())",
        ).strip()
        try:
            count = int(raw)
        except ValueError as exc:
            raise VerifyFailure(
                f"invalid bot count on {pipe_name}: {raw!r}"
            ) from exc
        if count != 0:
            raise VerifyFailure(
                f"bots remained active on {pipe_name}: {count}"
            )
        counts[pipe_name] = count
    return counts


def solo_terminal_state_matches(values: Mapping[str, str]) -> bool:
    hp = _number(values, "local_life_current")
    return (
        values.get("scene") == "testrun"
        and _integer(values, "participant_count") == 1
        and _integer(values, "remote_peer_count") == 0
        and values.get("spectator_active") == "false"
        and values.get("spectator_phase") == "Inactive"
        and math.isfinite(hp)
        and hp <= VITAL_TOLERANCE
    )


def terminal_game_over_state_matches(
    values: Mapping[str, str],
) -> bool:
    command_epoch = _integer(values, "game_over_command_epoch")
    return (
        command_epoch > 0
        and _integer(values, "game_over_accepted_epoch") == command_epoch
        and _integer(values, "game_over_run_nonce") > 0
        and _integer(values, "game_over_authority_participant_id") > 0
        and values.get("game_over_pending_dispatch") == "false"
        and _integer(values, "game_over_dispatch_count") == 1
        and values.get("spectator_active") == "false"
        and values.get("spectator_phase") == "Inactive"
    )


def _zone_pixels(
    image: Image.Image,
    bounds: tuple[float, float, float, float],
) -> list[tuple[int, int, int]]:
    width, height = image.size
    left, top, right, bottom = bounds
    crop = image.crop(
        (
            int(width * left),
            int(height * top),
            int(width * right),
            int(height * bottom),
        )
    ).convert("RGB")
    channel_bytes = crop.tobytes()
    return list(
        zip(
            channel_bytes[0::3],
            channel_bytes[1::3],
            channel_bytes[2::3],
            strict=True,
        )
    )


def classify_native_game_over_image(path: Path) -> dict[str, object]:
    """Recognize the stock three-line GAME / OVER / CLICK composition."""

    with Image.open(path) as source:
        image = source.convert("RGB")
    if image.width < 640 or image.height < 360:
        raise VerifyFailure(
            f"Game Over frame is too small for acceptance: {image.size}"
        )

    zones = {
        "game": (0.39, 0.21, 0.62, 0.39),
        "over": (0.39, 0.54, 0.62, 0.72),
        "continue": (0.38, 0.90, 0.63, 0.98),
    }
    gold_fractions: dict[str, float] = {}
    for label, bounds in zones.items():
        pixels = _zone_pixels(image, bounds)
        gold_count = sum(
            red >= 170 and green >= 130 and blue <= 130
            for red, green, blue in pixels
        )
        gold_fractions[label] = gold_count / float(len(pixels))

    all_pixels = _zone_pixels(image, (0.0, 0.0, 1.0, 1.0))
    dark_fraction = sum(
        max(pixel) < 20 for pixel in all_pixels
    ) / float(len(all_pixels))
    matched = (
        gold_fractions["game"] >= 0.01
        and gold_fractions["over"] >= 0.01
        and gold_fractions["continue"] >= 0.005
        and dark_fraction >= 0.70
    )
    return {
        "matched": matched,
        "width": image.width,
        "height": image.height,
        "gold_fractions": gold_fractions,
        "dark_fraction": dark_fraction,
    }


def capture_native_game_over(
    pipe_name: str,
    output_path: Path,
    *,
    timeout: float = 10.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last_error = ""
    last_classification: dict[str, object] = {}
    while time.monotonic() < deadline:
        try:
            capture = capture_game_backbuffer(pipe_name, output_path)
            classification = classify_native_game_over_image(output_path)
            last_classification = classification
            if classification["matched"]:
                return {
                    "capture": capture,
                    "classification": classification,
                }
        except Exception as exc:  # noqa: BLE001 - retry through native fade.
            last_error = str(exc)
        time.sleep(0.2)
    raise VerifyFailure(
        "full native Game Over frame did not become visible on "
        f"{pipe_name}; classification={last_classification} "
        f"last_error={last_error}"
    )


def _click(pipe_name: str, x: float, y: float) -> None:
    accepted = lua(
        pipe_name,
        f"return tostring(sd.input.click_normalized({x}, {y}))",
    ).strip()
    if accepted != "true":
        raise VerifyFailure(
            f"stock input click was not accepted on {pipe_name}: {accepted!r}"
        )


def _drive_stock_click_until(
    pipe_name: str,
    x: float,
    y: float,
    predicate,
    *,
    timeout: float,
    description: str,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    next_click_at = 0.0
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        now = time.monotonic()
        if now >= next_click_at:
            _click(pipe_name, x, y)
            next_click_at = now + 0.5
        last = query_session_state(pipe_name)
        if predicate(last):
            return last
        time.sleep(0.05)
    raise VerifyFailure(
        f"stock click did not reach {description} on {pipe_name}; last={last}"
    )


def advance_stock_post_game_over(
    pipe_names: list[str],
) -> dict[str, object]:
    mortuary = {
        pipe_name: _drive_stock_click_until(
            pipe_name,
            0.5,
            0.5,
            lambda values: values.get("scene") == "memorator",
            timeout=15.0,
            description="native Mortuary",
        )
        for pipe_name in pipe_names
    }

    hall_of_fame = {
        pipe_name: _drive_stock_click_until(
            pipe_name,
            0.5,
            0.5,
            lambda values: values.get("surface") == "hall_of_fame",
            timeout=15.0,
            description="native Hall of Fame",
        )
        for pipe_name in pipe_names
    }

    main_menu = {
        pipe_name: _drive_stock_click_until(
            pipe_name,
            0.5,
            0.95,
            lambda values: values.get("surface") == "main_menu",
            timeout=15.0,
            description="stock main menu",
        )
        for pipe_name in pipe_names
    }
    return {
        "mortuary": mortuary,
        "hall_of_fame": hall_of_fame,
        "main_menu": main_menu,
    }


def _apply_authoritative_remote_lethal_hit(
    host_pipe: str,
    target_participant_id: int,
    label: str,
) -> dict[str, object]:
    trial = invoke_native_magic_hit_trial(
        host_pipe,
        projectile_damage=0.0,
        magic_damage=1000.0,
        attempts=2,
        label=label,
        timeout=8.0,
        target_participant_id=target_participant_id,
    )
    hp_after = float(trial["hp_after"])
    if not math.isfinite(hp_after) or hp_after > VITAL_TOLERANCE:
        raise VerifyFailure(
            f"{label} did not reach terminal life: {trial}"
        )
    return trial


def _owned_solo_processes(
    launch: Mapping[str, object],
) -> dict[int, str]:
    process_ids = game_process_ids(dict(launch))
    executable = launch.get("executablePath")
    if len(process_ids) != 1 or not isinstance(executable, str):
        raise VerifyFailure(
            f"solo launcher did not report exact process ownership: {launch}"
        )
    return {process_ids[0]: executable}


def _owned_trio_processes(
    launch: Mapping[str, object],
) -> dict[int, str]:
    process_ids = {
        key: int(value)
        for key, value in (
            ("host", launch.get("hostProcessId")),
            ("client", launch.get("clientProcessId")),
            ("third", launch.get("thirdProcessId")),
        )
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
    }
    runtime_root = launch.get("runtimeRoot")
    instance_prefix = launch.get("instancePrefix")
    if (
        len(process_ids) != 3
        or not isinstance(runtime_root, str)
        or not isinstance(instance_prefix, str)
    ):
        raise VerifyFailure(
            f"trio launcher did not report exact process ownership: {launch}"
        )
    return {
        process_id: _expected_instance_executable(
            runtime_root,
            f"{instance_prefix}-{role}",
        )
        for role, process_id in process_ids.items()
    }


def run_solo_verification(
    *,
    instance_prefix: str,
    ports: list[int],
    game_directory: Path,
) -> dict[str, object]:
    instance = f"{instance_prefix}-solo"
    launch = launch_solo(
        instance=instance,
        local_port=ports[0],
        unused_remote_port=ports[1],
        game_directory=game_directory,
    )
    owned = _owned_solo_processes(launch)
    result: dict[str, object] = {
        "launch": launch,
        "owned_processes": validate_owned_processes(owned),
    }
    pipe_name = str(launch["luaPipe"])
    artifact_directory = ARTIFACT_ROOT / instance_prefix / "solo"
    try:
        wait_for_scene(pipe_name, "hub", 30.0)
        result["bots_disabled"] = _disable_bots([pipe_name])
        _start_testrun_when_ready(pipe_name)
        wait_for_scene(pipe_name, "testrun", 30.0)
        result["membership"] = _wait_for_state(
            pipe_name,
            lambda values: (
                _integer(values, "participant_count") == 1
                and _integer(values, "remote_peer_count") == 0
                and _integer(values, "connected_run_count") == 1
            ),
            timeout=10.0,
            description="one-participant run membership",
        )
        result["primed_vitals"] = set_local_player_vitals(
            pipe_name,
            1.0,
            25.0,
        )
        result["lethal_hit"] = invoke_native_magic_hit_trial(
            pipe_name,
            projectile_damage=0.0,
            magic_damage=1000.0,
            attempts=2,
            label="solo native Game Over",
            timeout=8.0,
        )

        samples: list[dict[str, str]] = []
        sample_deadline = time.monotonic() + 2.0
        while time.monotonic() < sample_deadline:
            sample = query_session_state(pipe_name)
            samples.append(sample)
            if not solo_terminal_state_matches(sample):
                raise VerifyFailure(
                    "solo death entered spectator state or left stock terminal "
                    f"ownership: {sample}"
                )
            time.sleep(0.05)
        result["post_death_samples"] = samples

        screenshot = artifact_directory / "game-over.png"
        result["game_over"] = capture_native_game_over(
            pipe_name,
            screenshot,
        )
        result["post_game_over"] = advance_stock_post_game_over(
            [pipe_name]
        )
        result["ok"] = True
        return result
    finally:
        stop_owned_processes(owned)


def run_trio_verification(
    *,
    instance_prefix: str,
    ports: list[int],
    game_directory: Path,
) -> dict[str, object]:
    trio_prefix = f"{instance_prefix}-mp"
    launch = launch_pair(
        host_preset="map_create_fire_mind_hub",
        client_preset="map_create_water_body_hub",
        third_preset="map_create_earth_arcane_hub",
        temporary_host_profile=True,
        tile_windows=False,
        third_player=True,
        kill_existing=False,
        instance_prefix=trio_prefix,
        host_port=ports[2],
        client_port=ports[3],
        third_port=ports[4],
        game_directory=game_directory,
        exact_mod_id=ACCEPTANCE_MOD_ID,
    )
    owned = _owned_trio_processes(launch)
    result: dict[str, object] = {
        "launch": launch,
        "owned_processes": validate_owned_processes(owned),
    }
    host_pipe = str(launch["hostLuaPipe"])
    client_pipe = str(launch["clientLuaPipe"])
    third_pipe = str(launch["thirdLuaPipe"])
    pipes = [host_pipe, client_pipe, third_pipe]
    artifact_directory = ARTIFACT_ROOT / instance_prefix / "trio"
    try:
        result["bots_disabled"] = _disable_bots(pipes)
        _start_testrun_when_ready(host_pipe)
        for pipe_name in pipes:
            wait_for_scene(pipe_name, "testrun", 45.0)

        participants = (
            (host_pipe, HOST_ID, HOST_NAME),
            (client_pipe, CLIENT_ID, CLIENT_NAME),
            (third_pipe, THIRD_ID, THIRD_NAME),
        )
        relationships: dict[str, dict[str, str]] = {}
        for observer_pipe, observer_id, _ in participants:
            for _, owner_id, owner_name in participants:
                if owner_id == observer_id:
                    continue
                key = f"{observer_id:x}_observes_{owner_id:x}"
                relationships[key] = wait_for_remote(
                    observer_pipe,
                    owner_id,
                    owner_name,
                    "testrun",
                    45.0,
                )
        result["relationships"] = relationships

        result["first_death"] = _apply_authoritative_remote_lethal_hit(
            host_pipe,
            CLIENT_ID,
            "first trio participant death",
        )
        result["first_death_presentation"] = _wait_for_spectator_state(
            client_pipe,
            death_presentation_state_matches,
            timeout=5.0,
            description="first native death presentation",
        )
        result["first_spectating"] = _wait_for_spectator_state(
            client_pipe,
            spectator_state_matches,
            timeout=6.0,
            description="first dead participant spectating",
        )
        result["first_spectator_frame"] = capture_game_backbuffer(
            client_pipe,
            artifact_directory / "first-death-spectator.png",
        )

        result["second_death"] = _apply_authoritative_remote_lethal_hit(
            host_pipe,
            THIRD_ID,
            "second trio participant death",
        )
        result["second_death_presentation"] = _wait_for_spectator_state(
            third_pipe,
            death_presentation_state_matches,
            timeout=5.0,
            description="second native death presentation",
        )
        result["second_spectating"] = _wait_for_spectator_state(
            third_pipe,
            spectator_state_matches,
            timeout=6.0,
            description="second dead participant spectating",
        )
        result["first_still_spectating"] = _wait_for_spectator_state(
            client_pipe,
            spectator_state_matches,
            timeout=3.0,
            description="first participant still spectating the host",
        )
        result["second_spectator_frame"] = capture_game_backbuffer(
            third_pipe,
            artifact_directory / "second-death-spectator.png",
        )

        result["host_primed_vitals"] = set_local_player_vitals(
            host_pipe,
            1.0,
            25.0,
        )
        result["last_death"] = invoke_native_magic_hit_trial(
            host_pipe,
            projectile_damage=0.0,
            magic_damage=1000.0,
            attempts=2,
            label="last trio participant death",
            timeout=8.0,
        )

        terminal_states = {
            pipe_name: _wait_for_state(
                pipe_name,
                terminal_game_over_state_matches,
                timeout=12.0,
                description="authority-scoped native Game Over dispatch",
            )
            for pipe_name in pipes
        }
        epochs = {
            _integer(values, "game_over_command_epoch")
            for values in terminal_states.values()
        }
        nonces = {
            _integer(values, "game_over_run_nonce")
            for values in terminal_states.values()
        }
        if len(epochs) != 1 or len(nonces) != 1:
            raise VerifyFailure(
                "participants did not consume one shared terminal command: "
                f"states={terminal_states}"
            )
        result["terminal_states"] = terminal_states

        result["game_over"] = {
            label: capture_native_game_over(
                pipe_name,
                artifact_directory / f"{label}-game-over.png",
            )
            for label, pipe_name in (
                ("host", host_pipe),
                ("client", client_pipe),
                ("third", third_pipe),
            )
        }
        result["post_game_over"] = advance_stock_post_game_over(pipes)
        result["ok"] = True
        return result
    finally:
        stop_owned_processes(owned)


def run_live_verification(
    *,
    instance_prefix: str,
    ports: list[int],
    game_directory: Path,
) -> dict[str, object]:
    return {
        "instance_prefix": instance_prefix,
        "ports": ports,
        "solo": run_solo_verification(
            instance_prefix=instance_prefix,
            ports=ports,
            game_directory=game_directory,
        ),
        "trio": run_trio_verification(
            instance_prefix=instance_prefix,
            ports=ports,
            game_directory=game_directory,
        ),
        "ok": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--instance-prefix",
        default="",
        help="Unique launcher group prefix (generated by default).",
    )
    parser.add_argument(
        "--game-dir",
        type=Path,
        required=True,
        help="Retail game directory used by isolated worktrees.",
    )
    parser.add_argument("--solo-port", type=int, default=None)
    parser.add_argument("--solo-unused-port", type=int, default=None)
    parser.add_argument("--host-port", type=int, default=None)
    parser.add_argument("--client-port", type=int, default=None)
    parser.add_argument("--third-port", type=int, default=None)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    instance_prefix = args.instance_prefix or _default_instance_prefix()
    result: dict[str, object] = {
        "ok": False,
        "instance_prefix": instance_prefix,
    }
    try:
        result = run_live_verification(
            instance_prefix=instance_prefix,
            ports=_resolve_udp_ports(
                [
                    args.solo_port,
                    args.solo_unused_port,
                    args.host_port,
                    args.client_port,
                    args.third_port,
                ]
            ),
            game_directory=args.game_dir,
        )
        exit_code = 0
    except Exception as exc:  # noqa: BLE001 - preserve full verifier failure.
        result["error"] = str(exc)
        exit_code = 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
