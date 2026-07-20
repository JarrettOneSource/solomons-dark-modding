#!/usr/bin/env python3
"""Drive real local mouse input and verify multiplayer spell presentation."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from multiplayer_log_probe import log_after, log_position, read_log
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    CLIENT_PIPE,
    HOST_ID,
    HOST_NAME,
    HOST_PIPE,
    VerifyFailure,
    disable_bots,
    launch_pair,
    parse_key_values,
    start_host_testrun_and_wait_for_clients,
    stop_games,
    wait_for_remote,
)
from verify_player_health_death_sync import set_local_player_vitals


ROOT = Path(__file__).resolve().parent.parent
CLICK_WINDOW = ROOT / "scripts/click_window.py"
HOST_LOG = ROOT / "runtime/instances/local-mp-host/stage/.sdmod/logs/solomondarkmodloader.log"
CLIENT_LOG = ROOT / "runtime/instances/local-mp-client/stage/.sdmod/logs/solomondarkmodloader.log"
TEST_PLAYER_HP = 5000.0
TAP_FRAMES = 12
HOLD_FRAMES = 150


@dataclass(frozen=True)
class Direction:
    name: str
    source_id: int
    source_name: str
    source_pipe: str
    source_log: Path
    source_pid: int
    receiver_pipe: str
    receiver_log: Path


PROJECTILES_LUA = """
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local actors = sd.world.list_actors and sd.world.list_actors() or {}
local fire = {}
local projectile = {}
for _, actor in ipairs(actors) do
  local type_id = tonumber(actor.object_type_id) or 0
  local address = tostring(actor.actor_address or 0)
  if type_id == 0x7D4 or type_id == 0x7D3 or type_id == 0x7D5 then
    projectile[#projectile + 1] = address
  end
  if type_id == 0x7D4 then
    fire[#fire + 1] = address
  end
end
emit("projectile_count", #projectile)
emit("fire_count", #fire)
emit("projectile_addresses", table.concat(projectile, ","))
emit("fire_addresses", table.concat(fire, ","))
"""


COMBAT_STATE_LUA = """
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local state = sd.gameplay and sd.gameplay.get_combat_state and sd.gameplay.get_combat_state() or nil
emit("combat_active", state and state.combat_active or false)
emit("music_started", state and state.music_started or false)
emit("wave_index", state and state.wave_index or 0)
emit("wave_counter", state and state.wave_counter or 0)
"""


def run(args: list[str], *, env: dict[str, str] | None = None, timeout: float = 30.0) -> str:
    completed = subprocess.run(
        args,
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise VerifyFailure(f"command failed ({completed.returncode}): {' '.join(args)}\n{completed.stdout}")
    return completed.stdout


def lua(pipe_name: str, code: str, timeout: float = 5.0) -> str:
    env = os.environ.copy()
    env["SDMOD_LUA_EXEC_PIPE_NAME"] = pipe_name
    return run(["python3", "tools/lua-exec.py", code], env=env, timeout=timeout)


def values(pipe_name: str, code: str, timeout: float = 5.0) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, code, timeout=timeout))


def combat_active(state: dict[str, str]) -> bool:
    return (
        state.get("combat_active") == "true"
        or state.get("music_started") == "true"
        or int(state.get("wave_index", "0") or "0") > 0
    )


def ensure_host_combat_started() -> dict[str, object]:
    before = values(HOST_PIPE, COMBAT_STATE_LUA, timeout=5.0)
    if combat_active(before):
        return {"already_active": True, "before": before}

    start = values(
        HOST_PIPE,
        "print('ok=' .. tostring(sd.gameplay.start_waves()))",
        timeout=5.0,
    )
    if start.get("ok") != "true":
        raise VerifyFailure(f"sd.gameplay.start_waves failed on host: {start}")

    deadline = time.monotonic() + 10.0
    last = before
    while time.monotonic() < deadline:
        last = values(HOST_PIPE, COMBAT_STATE_LUA, timeout=5.0)
        if combat_active(last):
            return {"started": True, "before": before, "after": last}
        time.sleep(0.1)
    raise VerifyFailure(f"host combat did not become active after start_waves: last={last}")


def query_scene(pipe_name: str) -> str:
    return lua(
        pipe_name,
        "local s=sd.world.get_scene(); return tostring(s and (s.name or s.kind) or '')",
    ).strip()


def ensure_testrun() -> dict[str, object]:
    host_scene = query_scene(HOST_PIPE)
    client_scene = query_scene(CLIENT_PIPE)
    if host_scene == "testrun" and client_scene == "testrun":
        return {"already_testrun": True}
    if host_scene != "hub":
        raise VerifyFailure(f"host is not in hub or testrun: {host_scene!r}")
    result = start_host_testrun_and_wait_for_clients()
    wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "testrun")
    wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "testrun")
    return result


def sustain_pair_vitals() -> dict[str, dict[str, str]]:
    return {
        "host": set_local_player_vitals(HOST_PIPE, TEST_PLAYER_HP, TEST_PLAYER_HP),
        "client": set_local_player_vitals(CLIENT_PIPE, TEST_PLAYER_HP, TEST_PLAYER_HP),
    }


def enable_progression_neutral_combat() -> dict[str, object]:
    # The stress harness imports this module's cast-log helpers, so importing its
    # combat bootstrap at module load time would form a cycle. Runtime lookup is
    # safe after this module has finished defining those helpers.
    from verify_multiplayer_primary_kill_stress import enable_manual_stock_spawner_combat

    return enable_manual_stock_spawner_combat()


def detect_instance_pids() -> dict[str, int]:
    output = run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Process -Filter \"Name='SolomonDark.exe'\" | "
            "Select-Object ProcessId,CommandLine | ConvertTo-Json -Depth 3",
        ],
        timeout=10.0,
    )
    parsed = json.loads(output)
    rows = parsed if isinstance(parsed, list) else [parsed]
    result: dict[str, int] = {}
    for row in rows:
        command_line = str(row.get("CommandLine", "")).lower()
        process_id = int(row.get("ProcessId", 0))
        if "local-mp-host" in command_line:
            result["host"] = process_id
        elif "local-mp-client" in command_line:
            result["client"] = process_id
        elif "local-mp-third" in command_line:
            result["third"] = process_id
    if "host" not in result or "client" not in result:
        raise VerifyFailure(f"could not resolve host/client SolomonDark PIDs from {rows}")
    return result


def ensure_instance_pids(result: dict[str, object]) -> dict[str, int]:
    try:
        return detect_instance_pids()
    except Exception:
        result["launch"] = launch_pair()
        return detect_instance_pids()


def ensure_pair_and_testrun(result: dict[str, object]) -> tuple[dict[str, int], dict[str, object]]:
    pids = ensure_instance_pids(result)
    try:
        return pids, ensure_testrun()
    except VerifyFailure as exc:
        result["relaunch_reason"] = str(exc)
        result["launch"] = launch_pair()
        pids = detect_instance_pids()
        return pids, ensure_testrun()


def windows_path(path: Path) -> str:
    return run(["wslpath", "-w", str(path)], timeout=5.0).strip()


def release_global_mouse_button(button: str = "left") -> str:
    if button not in ("left", "right"):
        raise VerifyFailure(f"unsupported mouse button: {button}")
    script = windows_path(CLICK_WINDOW)
    command = f"py -3 {json.dumps(script)} --release-only --button {button}"
    return run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        timeout=5.0,
    ).strip()


def click_process(
    pid: int,
    *,
    hold_ms: int = 90,
    button: str = "left",
) -> subprocess.Popen[str]:
    if button not in ("left", "right"):
        raise VerifyFailure(f"unsupported mouse button: {button}")
    script = windows_path(CLICK_WINDOW)
    command = (
        f"py -3 {json.dumps(script)} --pid {pid} --relative --x 0.72 --y 0.50 "
        f"--activate --activation-delay-ms 250 --post-delay-ms 80 "
        f"--hold-ms {hold_ms} --button {button} --global-only"
    )
    return subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-Command", command],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def wait_click(process: subprocess.Popen[str], timeout: float = 5.0) -> str:
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        output, _ = process.communicate()
        raise VerifyFailure(f"click helper timed out: {output}")
    if process.returncode != 0:
        raise VerifyFailure(f"click helper failed ({process.returncode}): {output}")
    return output


def queue_gameplay_mouse_left(direction: Direction, frames: int) -> dict[str, str]:
    if frames <= 0:
        raise VerifyFailure(f"{direction.name}: frames must be positive")
    result = values(
        direction.source_pipe,
        f"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
if sd.input.clear_mouse_left ~= nil then emit("clear_before", sd.input.clear_mouse_left()) end
local player = sd.player.get_state()
if player == nil or player.actor_address == nil or player.actor_address == 0 then
  error("player actor unavailable")
end
local actor = tonumber(player.actor_address) or 0
local x = sd.debug.read_float(actor + sd.debug.layout_offset("actor_position_x"))
local y = sd.debug.read_float(actor + sd.debug.layout_offset("actor_position_y"))
emit("write.heading", sd.debug.write_float(actor + sd.debug.layout_offset("actor_heading"), 90.0))
emit("write.aim_x", sd.debug.write_float(actor + sd.debug.layout_offset("actor_aim_target_x"), x + 320.0))
emit("write.aim_y", sd.debug.write_float(actor + sd.debug.layout_offset("actor_aim_target_y"), y))
emit("write.aux0", sd.debug.write_u32(actor + sd.debug.layout_offset("actor_aim_target_aux0"), 0))
emit("write.aux1", sd.debug.write_u32(actor + sd.debug.layout_offset("actor_aim_target_aux1"), 0))
emit("mouse_left_frames", sd.input.hold_mouse_left_frames({frames}))
""",
        timeout=5.0,
    )
    required = (
        "write.heading",
        "write.aim_x",
        "write.aim_y",
        "write.aux0",
        "write.aux1",
        "mouse_left_frames",
    )
    if any(result.get(key) != "true" for key in required):
        raise VerifyFailure(f"{direction.name}: failed to aim and queue mouse-left input: {result}")
    return result


def clear_gameplay_mouse_left(direction: Direction) -> dict[str, str]:
    result = values(
        direction.source_pipe,
        "print('cleared=' .. tostring(sd.input.clear_mouse_left()))",
        timeout=5.0,
    )
    if result.get("cleared") != "true":
        raise VerifyFailure(f"{direction.name}: failed to clear mouse-left input: {result}")
    # ClearQueuedGameplayMouseLeft is consumed by the next native input refresh.
    time.sleep(0.25)
    return result


def clear_local_cast_state(direction: Direction) -> dict[str, str]:
    result = values(
        direction.source_pipe,
        "print('cleared=' .. tostring(sd.input.clear_local_cast_state()))",
        timeout=5.0,
    )
    if result.get("cleared") != "true":
        raise VerifyFailure(f"{direction.name}: failed to clear local cast state: {result}")
    time.sleep(0.25)
    return result


def parse_phase_counts(log_text: str, source_id: int) -> dict[str, int]:
    pattern = re.compile(
        rf"Multiplayer local cast sent\. participant_id={source_id} .*?phase=([a-z_]+).*?skill_id=\d+"
    )
    counts: dict[str, int] = {}
    for phase in pattern.findall(log_text):
        counts[phase] = counts.get(phase, 0) + 1
    return counts


def parse_phase_sequences(log_text: str, source_id: int) -> dict[str, list[int]]:
    pattern = re.compile(
        rf"Multiplayer local cast sent\. participant_id={source_id} "
        rf"cast_sequence=(\d+) .*?phase=([a-z_]+).*?skill_id=\d+"
    )
    sequences: dict[str, list[int]] = {}
    for cast_sequence, phase in pattern.findall(log_text):
        sequences.setdefault(phase, []).append(int(cast_sequence))
    return sequences


def parse_unique_fire(values_dict: dict[str, str]) -> set[str]:
    raw = values_dict.get("fire_addresses", "")
    return {item for item in raw.split(",") if item and item != "0"}


def sample_remote_fire(pipe_name: str, duration: float = 2.0) -> set[str]:
    deadline = time.monotonic() + duration
    observed: set[str] = set()
    while time.monotonic() < deadline:
        observed |= parse_unique_fire(values(pipe_name, PROJECTILES_LUA, timeout=3.0))
        time.sleep(0.05)
    return observed


def count_lines(log_text: str, marker: str) -> int:
    return sum(1 for line in log_text.splitlines() if marker in line)


def parse_local_pressed_sequences(log_text: str, source_id: int) -> list[int]:
    return [
        int(cast_sequence)
        for cast_sequence in re.findall(
            rf"Multiplayer local native cast sent\. native_queue_id=\d+ "
            rf"cast_sequence=(\d+) participant_id={source_id}",
            log_text,
        )
    ]


def count_local_native_queues(log_text: str) -> int:
    return len(
        re.findall(
            r"Multiplayer local native cast sent\. native_queue_id=\d+ "
            r"cast_sequence=\d+ participant_id=\d+",
            log_text,
        )
    )


def parse_remote_queue_sequences(log_text: str, source_id: int) -> list[int]:
    pattern = re.compile(
        rf"Multiplayer remote cast queued\. participant_id={source_id} "
        rf"cast_sequence=(\d+) phase=pressed .*?skill_id=\d+"
    )
    return [int(match) for match in pattern.findall(log_text)]


def parse_remote_prep_sequences(log_text: str, source_id: int) -> list[int]:
    sequences: list[int] = []
    marker = f"[bots] wizard cast prepped. bot_id={source_id}"
    for line in log_text.splitlines():
        if marker not in line or "remote_input_controlled=1" not in line:
            continue
        match = re.search(r"remote_cast_sequence=(\d+)", line)
        if match:
            sequences.append(int(match.group(1)))
    return sequences


def parse_remote_settle_sequences(log_text: str, source_id: int, *, observed_only: bool) -> list[int]:
    sequences: list[int] = []
    marker = f"[bots] cast complete (pure_primary_no_handle_settled). bot_id={source_id}"
    for line in log_text.splitlines():
        if marker not in line or "remote_input_controlled=1" not in line:
            continue
        if observed_only and "remote_projectile_observed=1" not in line:
            continue
        match = re.search(r"remote_cast_sequence=(\d+)", line)
        if match:
            sequences.append(int(match.group(1)))
    return sequences


def assert_sequence_counts(
    direction_name: str,
    label: str,
    expected_sequences: list[int],
    actual_sequences: list[int],
) -> list[int]:
    expected = Counter(expected_sequences)
    expected_keys = set(expected)
    actual_for_expected = [sequence for sequence in actual_sequences if sequence in expected_keys]
    actual = Counter(actual_for_expected)
    if actual != expected:
        missing = sorted((expected - actual).elements())
        extra = sorted((actual - expected).elements())
        outside = sorted(sequence for sequence in actual_sequences if sequence not in expected_keys)
        raise VerifyFailure(
            f"{direction_name}: {label} sequence mismatch "
            f"expected={sorted(expected_sequences)} actual={sorted(actual_for_expected)} "
            f"missing={missing} extra={extra} outside_window={outside}"
        )
    return actual_for_expected


def wait_for_source_cast(
    direction: Direction,
    source_offset: int,
    required_counts: dict[str, int],
    timeout: float,
) -> tuple[str, dict[str, int], int]:
    deadline = time.monotonic() + timeout
    last_log = ""
    last_counts: dict[str, int] = {}
    last_native_hook_count = 0
    while time.monotonic() < deadline:
        last_log = log_after(direction.source_log, source_offset)
        last_counts = parse_phase_counts(last_log, direction.source_id)
        last_native_hook_count = count_local_native_queues(last_log)
        if last_native_hook_count >= 1 and all(
            last_counts.get(phase, 0) >= count
            for phase, count in required_counts.items()
        ):
            return last_log, last_counts, last_native_hook_count
        time.sleep(0.05)
    raise VerifyFailure(
        f"{direction.name}: source cast did not reach native hook/phases. "
        f"required={required_counts} native_hooks={last_native_hook_count} phases={last_counts}"
    )


def wait_for_balanced_source_casts(
    direction: Direction,
    source_offset: int,
    timeout: float = 3.0,
    stable_duration: float = 0.25,
) -> tuple[str, dict[str, int], int]:
    deadline = time.monotonic() + timeout
    balanced_since: float | None = None
    balanced_signature: tuple[tuple[tuple[int, int], ...], ...] | None = None
    last_log = ""
    last_counts: dict[str, int] = {}
    last_native_hook_count = 0
    while time.monotonic() < deadline:
        last_log = log_after(direction.source_log, source_offset)
        native_sequences = parse_local_pressed_sequences(last_log, direction.source_id)
        native_counts = Counter(native_sequences)
        expected_sequences = set(native_counts)
        phase_sequences = parse_phase_sequences(last_log, direction.source_id)
        filtered_phase_counts = {
            phase: Counter(
                sequence
                for sequence in sequences
                if sequence in expected_sequences
            )
            for phase, sequences in phase_sequences.items()
        }
        pressed_counts = filtered_phase_counts.get("pressed", Counter())
        released_counts = filtered_phase_counts.get("released", Counter())
        last_counts = {
            phase: sum(counts.values())
            for phase, counts in filtered_phase_counts.items()
        }
        last_native_hook_count = len(native_sequences)
        signature = (
            tuple(sorted(native_counts.items())),
            tuple(sorted(pressed_counts.items())),
            tuple(sorted(released_counts.items())),
        )
        balanced = (
            bool(native_counts)
            and pressed_counts == native_counts
            and released_counts == native_counts
        )
        now = time.monotonic()
        if balanced:
            if signature != balanced_signature:
                balanced_signature = signature
                balanced_since = now
            elif balanced_since is not None and now - balanced_since >= stable_duration:
                return last_log, last_counts, last_native_hook_count
        else:
            balanced_signature = None
            balanced_since = None
        time.sleep(0.05)
    raise VerifyFailure(
        f"{direction.name}: source cast lifecycle did not balance. "
        f"native_hooks={last_native_hook_count} phases={last_counts}"
    )


def verify_single_click(direction: Direction) -> dict[str, object]:
    pre_clear = clear_local_cast_state(direction)
    source_offset = log_position(direction.source_log)
    receiver_offset = log_position(direction.receiver_log)
    before_fire = sample_remote_fire(direction.receiver_pipe, duration=0.15)
    input_output = queue_gameplay_mouse_left(direction, TAP_FRAMES)
    wait_for_source_cast(
        direction,
        source_offset,
        {"pressed": 1, "released": 1},
        timeout=4.0,
    )
    observed_fire = sample_remote_fire(direction.receiver_pipe, duration=2.2)
    source_log, phase_counts, native_hook_count = wait_for_balanced_source_casts(
        direction,
        source_offset,
    )
    receiver_log = log_after(direction.receiver_log, receiver_offset)
    native_sequences = parse_local_pressed_sequences(source_log, direction.source_id)
    remote_queue_sequences = parse_remote_queue_sequences(receiver_log, direction.source_id)
    remote_prep_sequences = parse_remote_prep_sequences(receiver_log, direction.source_id)
    remote_settle_sequences = parse_remote_settle_sequences(
        receiver_log,
        direction.source_id,
        observed_only=False,
    )
    remote_observed_sequences = parse_remote_settle_sequences(
        receiver_log,
        direction.source_id,
        observed_only=True,
    )
    new_fire = observed_fire - before_fire
    if native_hook_count < 1:
        raise VerifyFailure(f"{direction.name}: single click produced no native primary hooks")
    if len(native_sequences) != native_hook_count:
        raise VerifyFailure(
            f"{direction.name}: single-click source sequence/native hook mismatch "
            f"hooks={native_hook_count} sequences={native_sequences}"
        )
    if phase_counts.get("pressed", 0) != native_hook_count or phase_counts.get("released", 0) != native_hook_count:
        raise VerifyFailure(
            f"{direction.name}: single-click phase counts mismatch hooks={native_hook_count} phases={phase_counts}"
        )
    matched_queue_sequences = assert_sequence_counts(
        direction.name,
        "remote queue",
        native_sequences,
        remote_queue_sequences,
    )
    matched_prep_sequences = assert_sequence_counts(
        direction.name,
        "remote prep",
        native_sequences,
        remote_prep_sequences,
    )
    matched_settle_sequences = assert_sequence_counts(
        direction.name,
        "remote settle",
        native_sequences,
        remote_settle_sequences,
    )
    matched_observed_sequences = assert_sequence_counts(
        direction.name,
        "remote projectile observed",
        native_sequences,
        remote_observed_sequences,
    )
    return {
        "pre_clear": pre_clear,
        "input_output": input_output,
        "native_hook_count": native_hook_count,
        "native_sequences": native_sequences,
        "phase_counts": phase_counts,
        "remote_queue_count": len(matched_queue_sequences),
        "remote_prep_count": len(matched_prep_sequences),
        "remote_settle_count": len(matched_settle_sequences),
        "remote_projectile_observed_count": len(matched_observed_sequences),
        "remote_queue_sequences": matched_queue_sequences,
        "remote_prep_sequences": matched_prep_sequences,
        "remote_settle_sequences": matched_settle_sequences,
        "remote_projectile_observed_sequences": matched_observed_sequences,
        "sampled_fire_addresses": sorted(observed_fire),
        "new_fire_addresses": sorted(new_fire),
    }


def verify_rapid_clicks(direction: Direction, click_count: int = 5) -> dict[str, object]:
    pre_clear = clear_local_cast_state(direction)
    source_offset = log_position(direction.source_log)
    receiver_offset = log_position(direction.receiver_log)
    before_fire = sample_remote_fire(direction.receiver_pipe, duration=0.15)
    input_outputs: list[dict[str, str]] = []
    for _ in range(click_count):
        input_outputs.append(queue_gameplay_mouse_left(direction, TAP_FRAMES))
        time.sleep(0.65)
    observed_fire = sample_remote_fire(direction.receiver_pipe, duration=2.5)
    source_log, phase_counts, native_hook_count = wait_for_balanced_source_casts(
        direction,
        source_offset,
    )
    receiver_log = log_after(direction.receiver_log, receiver_offset)
    native_sequences = parse_local_pressed_sequences(source_log, direction.source_id)
    remote_queue_sequences = parse_remote_queue_sequences(receiver_log, direction.source_id)
    remote_settle_sequences = parse_remote_settle_sequences(
        receiver_log,
        direction.source_id,
        observed_only=False,
    )
    remote_observed_sequences = parse_remote_settle_sequences(
        receiver_log,
        direction.source_id,
        observed_only=True,
    )
    new_fire = observed_fire - before_fire
    if native_hook_count < 1:
        raise VerifyFailure(f"{direction.name}: rapid clicks produced no native primary hooks")
    if len(native_sequences) != native_hook_count:
        raise VerifyFailure(
            f"{direction.name}: rapid click source sequence/native hook mismatch "
            f"hooks={native_hook_count} sequences={native_sequences}"
        )
    if phase_counts.get("pressed", 0) != native_hook_count or phase_counts.get("released", 0) != native_hook_count:
        raise VerifyFailure(f"{direction.name}: rapid click phase counts mismatch hooks={native_hook_count} phases={phase_counts}")
    matched_queue_sequences = assert_sequence_counts(
        direction.name,
        "remote queue",
        native_sequences,
        remote_queue_sequences,
    )
    matched_settle_sequences = assert_sequence_counts(
        direction.name,
        "remote settle",
        native_sequences,
        remote_settle_sequences,
    )
    matched_observed_sequences = assert_sequence_counts(
        direction.name,
        "remote projectile observed",
        native_sequences,
        remote_observed_sequences,
    )
    return {
        "pre_clear": pre_clear,
        "input_outputs": input_outputs,
        "native_hook_count": native_hook_count,
        "native_sequences": native_sequences,
        "phase_counts": phase_counts,
        "remote_queue_count": len(matched_queue_sequences),
        "remote_settle_count": len(matched_settle_sequences),
        "remote_projectile_observed_count": len(matched_observed_sequences),
        "remote_queue_sequences": matched_queue_sequences,
        "remote_settle_sequences": matched_settle_sequences,
        "remote_projectile_observed_sequences": matched_observed_sequences,
        "sampled_fire_addresses": sorted(observed_fire),
        "new_fire_addresses": sorted(new_fire),
    }


def verify_hold(direction: Direction) -> dict[str, object]:
    input_attempts: list[dict[str, object]] = []
    for arm_attempt in range(1, 3):
        pre_clear = clear_local_cast_state(direction)
        source_offset = log_position(direction.source_log)
        receiver_offset = log_position(direction.receiver_log)
        before_fire = sample_remote_fire(direction.receiver_pipe, duration=0.15)
        input_output = queue_gameplay_mouse_left(direction, HOLD_FRAMES)
        try:
            wait_for_source_cast(
                direction,
                source_offset,
                {"pressed": 1},
                timeout=1.5,
            )
        except VerifyFailure as exc:
            input_attempts.append({
                "attempt": arm_attempt,
                "input_output": input_output,
                "error": str(exc),
            })
            continue
        input_attempts.append({
            "attempt": arm_attempt,
            "input_output": input_output,
            "armed": True,
        })
        break
    else:
        raise VerifyFailure(
            f"{direction.name}: hold input did not arm a native primary cast: "
            f"attempts={input_attempts}"
        )
    active_seen = False
    held_seen = False
    held_fire: set[str] = set()
    hold_deadline = time.monotonic() + 3.5
    while time.monotonic() < hold_deadline:
        phase_counts = parse_phase_counts(log_after(direction.source_log, source_offset), direction.source_id)
        held_seen = held_seen or phase_counts.get("held", 0) >= 2
        state = values(
            direction.receiver_pipe,
            f"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local bot = sd.bots and sd.bots.get_participant_state and sd.bots.get_participant_state({direction.source_id}) or nil
	emit("found", bot ~= nil)
	emit("cast_active", bot and bot.cast_active or false)
	emit("cast_ticks_waiting", bot and bot.cast_ticks_waiting or 0)
	local actors = sd.world.list_actors and sd.world.list_actors() or {{}}
	local fire = {{}}
	for _, actor in ipairs(actors) do
	  local type_id = tonumber(actor.object_type_id) or 0
	  local address = tostring(actor.actor_address or 0)
	  if type_id == 0x7D4 then
	    fire[#fire + 1] = address
	  end
	end
	emit("fire_addresses", table.concat(fire, ","))
	""",
            timeout=3.0,
        )
        active_seen = active_seen or state.get("cast_active") == "true"
        held_fire |= parse_unique_fire(state)
        if held_seen and active_seen and phase_counts.get("released", 0) >= 1:
            break
        time.sleep(0.05)
    observed_fire = held_fire | sample_remote_fire(direction.receiver_pipe, duration=2.2)
    source_log, phase_counts, native_hook_count = wait_for_balanced_source_casts(
        direction,
        source_offset,
    )
    receiver_log = log_after(direction.receiver_log, receiver_offset)
    native_sequences = parse_local_pressed_sequences(source_log, direction.source_id)
    new_fire = observed_fire - before_fire
    release_count = count_lines(
        receiver_log,
        f"Multiplayer remote cast input release. participant_id={direction.source_id}",
    )
    remote_queue_sequences = parse_remote_queue_sequences(receiver_log, direction.source_id)
    remote_settle_sequences = parse_remote_settle_sequences(
        receiver_log,
        direction.source_id,
        observed_only=False,
    )
    remote_observed_sequences = parse_remote_settle_sequences(
        receiver_log,
        direction.source_id,
        observed_only=True,
    )
    timeout_count = count_lines(receiver_log, "remote_input_timeout")
    if native_hook_count < 1:
        raise VerifyFailure(f"{direction.name}: hold produced no native primary hooks")
    if len(native_sequences) != native_hook_count:
        raise VerifyFailure(
            f"{direction.name}: hold source sequence/native hook mismatch "
            f"hooks={native_hook_count} sequences={native_sequences}"
        )
    if phase_counts.get("pressed", 0) != native_hook_count or phase_counts.get("released", 0) != native_hook_count:
        raise VerifyFailure(
            f"{direction.name}: hold phase counts mismatch hooks={native_hook_count} phases={phase_counts}"
        )
    # A Lua receiver sample can consume the entire short observation window on
    # slower WSL/PowerShell bridges. The final source log is authoritative: it
    # proves the held stream even when the polling loop did not observe it live.
    if phase_counts.get("held", 0) < 2:
        raise VerifyFailure(f"{direction.name}: hold did not stream held packets: {phase_counts}")
    matched_queue_sequences = assert_sequence_counts(
        direction.name,
        "remote queue",
        native_sequences,
        remote_queue_sequences,
    )
    matched_settle_sequences = assert_sequence_counts(
        direction.name,
        "remote settle",
        native_sequences,
        remote_settle_sequences,
    )
    matched_observed_sequences = assert_sequence_counts(
        direction.name,
        "remote projectile observed",
        native_sequences,
        remote_observed_sequences,
    )
    if timeout_count:
        raise VerifyFailure(
            f"{direction.name}: hold remote lifecycle timed out "
            f"release={release_count} hooks={native_hook_count} timeout={timeout_count}"
        )
    return {
        "pre_clear": pre_clear,
        "input_output": input_output,
        "input_attempts": input_attempts,
        "native_hook_count": native_hook_count,
        "native_sequences": native_sequences,
        "phase_counts": phase_counts,
        "remote_queue_count": len(matched_queue_sequences),
        "remote_release_count": release_count,
        "remote_settle_count": len(matched_settle_sequences),
        "remote_projectile_observed_count": len(matched_observed_sequences),
        "remote_queue_sequences": matched_queue_sequences,
        "remote_settle_sequences": matched_settle_sequences,
        "remote_projectile_observed_sequences": matched_observed_sequences,
        "active_seen_during_hold": active_seen,
        "sampled_fire_addresses": sorted(observed_fire),
        "new_fire_addresses": sorted(new_fire),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    result: dict[str, object] = {"ok": False}
    try:
        result["global_mouse_reset"] = release_global_mouse_button()
        pids, run_entry = ensure_pair_and_testrun(result)
        result["pids"] = pids
        result["run_entry"] = run_entry
        disable_bots()
        result["vitals_before_combat"] = sustain_pair_vitals()
        result["combat"] = enable_progression_neutral_combat()
        result["vitals_after_combat"] = sustain_pair_vitals()
        directions = [
            Direction("host_to_client", HOST_ID, HOST_NAME, HOST_PIPE, HOST_LOG, pids["host"], CLIENT_PIPE, CLIENT_LOG),
            Direction("client_to_host", CLIENT_ID, CLIENT_NAME, CLIENT_PIPE, CLIENT_LOG, pids["client"], HOST_PIPE, HOST_LOG),
        ]
        for direction in directions:
            result[f"{direction.name}_vitals_before_single_click"] = sustain_pair_vitals()
            result[f"{direction.name}_single_click"] = verify_single_click(direction)
            time.sleep(1.2)
            result[f"{direction.name}_vitals_before_rapid_clicks"] = sustain_pair_vitals()
            result[f"{direction.name}_rapid_clicks"] = verify_rapid_clicks(direction)
            time.sleep(1.2)
            result[f"{direction.name}_vitals_before_hold"] = sustain_pair_vitals()
            result[f"{direction.name}_hold"] = verify_hold(direction)
            time.sleep(1.2)
        result["ok"] = True
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        result["error"] = str(exc)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1
    finally:
        release_global_mouse_button()
        stop_games()


if __name__ == "__main__":
    raise SystemExit(main())
