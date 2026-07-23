#!/usr/bin/env python3
"""Verify connected death, spectator targeting, and wave respawn behavior."""

from __future__ import annotations

import argparse
import json
import math
import os
import socket
import time
from collections.abc import Mapping
from pathlib import Path

from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    HOST_ID,
    HOST_NAME,
    ROOT,
    THIRD_ID,
    THIRD_NAME,
    VerifyFailure,
    game_process_ids,
    launch_pair,
    lua,
    parse_key_values,
    start_testrun,
    stop_game_processes,
    wait_for_remote,
    wait_for_scene,
)
from verify_player_health_death_sync import set_local_player_vitals


POSITION_TOLERANCE = 0.25
VITAL_TOLERANCE = 0.05
OUTPUT = ROOT / "runtime" / "multiplayer_death_spectator_respawn.json"
WAVE_FIXTURE = ROOT / "tests" / "fixtures" / "waves" / "physical_stat_test.txt"


SPECTATOR_STATE_PROBE = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local multiplayer = assert(sd.runtime.get_multiplayer_state())
local spectator = assert(multiplayer.death_spectator)
local player = sd.player.get_state()
local scene = sd.world.get_scene()
local ui = sd.ui and sd.ui.get_snapshot and sd.ui.get_snapshot() or nil
local camera_ok, camera = false, nil
if sd.camera ~= nil and sd.camera.get_state ~= nil then
  camera_ok, camera = pcall(sd.camera.get_state)
end
local target = nil
for _, participant in ipairs(multiplayer.participants or {}) do
  if participant.participant_id == spectator.target_participant_id then
    target = participant
    break
  end
end
local target_gameplay = nil
if spectator.target_participant_id ~= nil and
    spectator.target_participant_id ~= 0 then
  target_gameplay = sd.bots.get_participant_state(
    spectator.target_participant_id)
end
emit("active", spectator.active)
emit("phase", spectator.phase)
emit("death_started_ms", spectator.death_started_ms)
emit("presentation_remaining_ms", spectator.presentation_remaining_ms)
emit("target_participant_id", spectator.target_participant_id)
emit("target_name", spectator.target_name)
emit("waiting_for_alive_target", spectator.waiting_for_alive_target)
emit("last_applied_respawn_epoch", spectator.last_applied_respawn_epoch)
emit("last_applied_respawn_wave", spectator.last_applied_respawn_wave)
emit("last_respawn_x", spectator.last_respawn_x)
emit("last_respawn_y", spectator.last_respawn_y)
emit("display_text", spectator.display_text)
emit("scene", scene and (scene.name or scene.kind) or "")
emit("game_over_surface", ui ~= nil and ui.surface_id == "game_over")
emit("hp", player and player.hp or 0)
emit("max_hp", player and player.max_hp or 0)
emit("mp", player and player.mp or 0)
emit("max_mp", player and player.max_mp or 0)
emit("anim_drive_state", player and player.anim_drive_state or -1)
emit("x", player and player.x or 0)
emit("y", player and player.y or 0)
emit("target_alive", target ~= nil and
  target.life_current > 0 and target.life_max > 0)
emit("target_x", target_gameplay and target_gameplay.x or 0)
emit("target_y", target_gameplay and target_gameplay.y or 0)
emit("camera_focus_active", camera_ok and camera.focus_active or false)
emit("camera_center_x", camera_ok and camera.center_x or 0)
emit("camera_center_y", camera_ok and camera.center_y or 0)
"""


WAVE_STATE_PROBE = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local state = assert(sd.waves.get_state())
emit("wave", state.wave)
emit("phase", state.phase)
emit("remaining_to_spawn", state.remaining_to_spawn)
emit("alive", state.alive)
emit("killed", state.killed)
"""


KILL_LIVE_WAVE_ENEMIES = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local actors = sd.world.list_actors and sd.world.list_actors() or {}
local hp_offset = sd.debug.layout_offset("enemy_current_hp")
local max_hp_offset = sd.debug.layout_offset("enemy_max_hp")
local progression_offset =
  sd.debug.layout_offset("actor_progression_runtime_state")
local progression_hp_offset = sd.debug.layout_offset("progression_hp")
local progression_max_hp_offset =
  sd.debug.layout_offset("progression_max_hp")
local attempted = 0
local triggered = 0
for _, actor in ipairs(actors) do
  local address = tonumber(actor.actor_address) or 0
  local max_hp = tonumber(actor.max_hp) or 0
  if address ~= 0 and actor.tracked_enemy and not actor.dead and max_hp > 0 then
    attempted = attempted + 1
    sd.debug.write_float(address + max_hp_offset, math.max(max_hp, 1))
    sd.debug.write_float(address + hp_offset, 0)
    local progression =
      tonumber(sd.debug.read_ptr(address + progression_offset)) or 0
    if progression ~= 0 then
      sd.debug.write_float(
        progression + progression_max_hp_offset,
        math.max(max_hp, 1))
      sd.debug.write_float(progression + progression_hp_offset, 0)
    end
    local ok = sd.world.trigger_enemy_death(address)
    if ok then triggered = triggered + 1 end
  end
end
emit("attempted", attempted)
emit("triggered", triggered)
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


def spectator_state_matches(values: Mapping[str, str]) -> bool:
    target_id = _integer(values, "target_participant_id")
    center_x = _number(values, "camera_center_x")
    center_y = _number(values, "camera_center_y")
    target_x = _number(values, "target_x")
    target_y = _number(values, "target_y")
    target_name = values.get("target_name", "")
    display_text = values.get("display_text", "")
    return (
        values.get("active") == "true"
        and values.get("phase") == "Spectating"
        and _integer(values, "presentation_remaining_ms") == 0
        and target_id > 0
        and bool(target_name)
        and values.get("waiting_for_alive_target") == "false"
        and values.get("target_alive") == "true"
        and values.get("camera_focus_active") == "true"
        and math.isfinite(center_x)
        and math.isfinite(center_y)
        and math.isfinite(target_x)
        and math.isfinite(target_y)
        and abs(center_x - target_x) <= POSITION_TOLERANCE
        and abs(center_y - target_y) <= POSITION_TOLERANCE
        and display_text
        == f"Spectating {target_name}  |  Left / Right click: next player"
    )


def death_presentation_state_matches(
    values: Mapping[str, str],
) -> bool:
    remaining_ms = _integer(
        values,
        "presentation_remaining_ms",
    )
    hp = _number(values, "hp")
    return (
        values.get("active") == "true"
        and values.get("phase") == "DeathPresentation"
        and 0 < remaining_ms <= 3000
        and values.get("scene") == "testrun"
        and values.get("game_over_surface") == "false"
        and math.isfinite(hp)
        and hp <= 0.0
        and _integer(values, "anim_drive_state") == 1
        and values.get("display_text", "") == ""
    )


def respawn_state_matches(
    values: Mapping[str, str],
    *,
    previous_epoch: int,
    expected_wave: int,
) -> bool:
    epoch = _integer(values, "last_applied_respawn_epoch")
    hp = _number(values, "hp")
    max_hp = _number(values, "max_hp")
    mp = _number(values, "mp")
    max_mp = _number(values, "max_mp")
    x = _number(values, "x")
    y = _number(values, "y")
    respawn_x = _number(values, "last_respawn_x")
    respawn_y = _number(values, "last_respawn_y")
    return (
        values.get("active") == "false"
        and values.get("phase") == "Inactive"
        and epoch > previous_epoch
        and _integer(values, "last_applied_respawn_wave") == expected_wave
        and math.isfinite(hp)
        and math.isfinite(max_hp)
        and max_hp > 0.0
        and abs(hp - max_hp) <= VITAL_TOLERANCE
        and math.isfinite(mp)
        and math.isfinite(max_mp)
        and max_mp > 0.0
        and abs(mp - max_mp) <= VITAL_TOLERANCE
        and _integer(values, "anim_drive_state") == 0
        and math.isfinite(x)
        and math.isfinite(y)
        and math.isfinite(respawn_x)
        and math.isfinite(respawn_y)
        and abs(x - respawn_x) <= POSITION_TOLERANCE
        and abs(y - respawn_y) <= POSITION_TOLERANCE
    )


def _reserve_udp_ports(count: int) -> list[int]:
    sockets: list[socket.socket] = []
    try:
        for _ in range(count):
            handle = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            handle.bind(("127.0.0.1", 0))
            sockets.append(handle)
        return [
            int(handle.getsockname()[1])
            for handle in sockets
        ]
    finally:
        for handle in sockets:
            handle.close()


def query_spectator_state(pipe_name: str) -> dict[str, str]:
    return parse_key_values(
        lua(pipe_name, SPECTATOR_STATE_PROBE, timeout=8.0)
    )


def _wait_for_values(
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
            last = query_spectator_state(pipe_name)
            last_error = ""
            if predicate(last):
                return last
        except Exception as exc:  # noqa: BLE001 - preserve probe evidence.
            last_error = str(exc)
        time.sleep(0.05)
    suffix = f" last_error={last_error}" if last_error else ""
    raise VerifyFailure(
        f"timed out waiting for {description} on {pipe_name}; "
        f"last={last}.{suffix}"
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


def _wait_for_wave(
    pipe_name: str,
    predicate,
    *,
    timeout: float,
    description: str,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = parse_key_values(
            lua(pipe_name, WAVE_STATE_PROBE, timeout=8.0)
        )
        if predicate(last):
            return last
        time.sleep(0.1)
    raise VerifyFailure(
        f"timed out waiting for {description}; last={last}"
    )


def _trigger_all_live_wave_enemy_deaths(
    host_pipe: str,
    *,
    timeout: float = 15.0,
) -> list[dict[str, str]]:
    deadline = time.monotonic() + timeout
    attempts: list[dict[str, str]] = []
    while time.monotonic() < deadline:
        wave = parse_key_values(
            lua(host_pipe, WAVE_STATE_PROBE, timeout=8.0)
        )
        if (
            wave.get("phase") == "completed"
            and int(wave.get("wave", "0")) > 0
        ):
            return attempts
        result = parse_key_values(
            lua(host_pipe, KILL_LIVE_WAVE_ENEMIES, timeout=8.0)
        )
        attempts.append(result)
        time.sleep(0.1)
    raise VerifyFailure(
        "host wave did not complete after native enemy death triggers; "
        f"attempts={attempts[-5:]}"
    )


def _cycle_spectator_target(
    pipe_name: str,
    *,
    previous_target_id: int,
    input_code: str,
    description: str,
) -> dict[str, str]:
    accepted = lua(pipe_name, input_code).strip()
    if accepted != "true":
        raise VerifyFailure(
            f"{description} input was not accepted: {accepted!r}"
        )
    return _wait_for_values(
        pipe_name,
        lambda values: spectator_state_matches(values)
        and _integer(values, "target_participant_id")
        != previous_target_id,
        timeout=3.0,
        description=description,
    )


def run_live_verification(
    *,
    instance_prefix: str,
    ports: list[int],
) -> dict[str, object]:
    launch = launch_pair(
        host_preset="map_create_fire_mind_hub",
        client_preset="map_create_water_body_hub",
        third_preset="map_create_earth_arcane_hub",
        temporary_host_profile=True,
        tile_windows=False,
        test_wave_override=WAVE_FIXTURE,
        third_player=True,
        kill_existing=False,
        instance_prefix=instance_prefix,
        host_port=ports[0],
        client_port=ports[1],
        third_port=ports[2],
    )
    process_ids = game_process_ids(launch)
    if len(process_ids) != 3:
        stop_game_processes(process_ids)
        raise VerifyFailure(
            f"isolated trio did not report three process IDs: {launch}"
        )

    host_pipe = str(launch["hostLuaPipe"])
    client_pipe = str(launch["clientLuaPipe"])
    third_pipe = str(launch["thirdLuaPipe"])
    pipe_names = [host_pipe, client_pipe, third_pipe]
    result: dict[str, object] = {
        "launch": launch,
        "process_ids": process_ids,
        "instance_prefix": instance_prefix,
        "ports": ports,
    }
    try:
        result["bots_disabled"] = _disable_bots(pipe_names)
        start_testrun(host_pipe)
        for pipe_name in pipe_names:
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

        set_local_player_vitals(
            client_pipe,
            375.0,
            500.0,
            mp=300.0,
            max_mp=300.0,
        )
        death_written_at = time.monotonic()
        set_local_player_vitals(
            client_pipe,
            -50.0,
            500.0,
            mp=300.0,
            max_mp=300.0,
        )
        death_presentation = _wait_for_values(
            client_pipe,
            death_presentation_state_matches,
            timeout=2.5,
            description="native death presentation without Game Over",
        )
        result["death_presentation"] = death_presentation

        spectating = _wait_for_values(
            client_pipe,
            spectator_state_matches,
            timeout=5.0,
            description="spectator mode with a live target",
        )
        spectator_delay = time.monotonic() - death_written_at
        if spectator_delay < 2.8:
            raise VerifyFailure(
                "spectator mode started before the three-second native "
                f"death presentation elapsed: {spectator_delay:.3f}s"
            )
        result["spectator_delay_seconds"] = spectator_delay
        result["spectating_initial"] = spectating

        initial_target = _integer(
            spectating,
            "target_participant_id",
        )
        after_left = _cycle_spectator_target(
            client_pipe,
            previous_target_id=initial_target,
            input_code=(
                "return tostring(sd.input.click_normalized(0.5, 0.5))"
            ),
            description="left-click spectator cycle",
        )
        result["spectating_after_left"] = after_left
        time.sleep(0.25)
        after_right = _cycle_spectator_target(
            client_pipe,
            previous_target_id=_integer(
                after_left,
                "target_participant_id",
            ),
            input_code=(
                "return tostring(sd.input.hold_mouse_right_frames(1))"
            ),
            description="right-click spectator cycle",
        )
        result["spectating_after_right"] = after_right

        previous_epochs = {
            pipe_name: _integer(
                query_spectator_state(pipe_name),
                "last_applied_respawn_epoch",
            )
            for pipe_name in pipe_names
        }
        start_values = parse_key_values(
            lua(
                host_pipe,
                "print('ok=' .. tostring(sd.gameplay.start_waves()))",
            )
        )
        if start_values.get("ok") != "true":
            raise VerifyFailure(
                f"host could not start the respawn wave: {start_values}"
            )
        result["wave_spawning"] = _wait_for_wave(
            host_pipe,
            lambda values: int(values.get("alive", "0")) > 0,
            timeout=15.0,
            description="wave enemy spawn",
        )
        result["enemy_death_triggers"] = (
            _trigger_all_live_wave_enemy_deaths(host_pipe)
        )
        completed = _wait_for_wave(
            host_pipe,
            lambda values: values.get("phase") == "completed"
            and int(values.get("wave", "0")) > 0,
            timeout=8.0,
            description="wave completion",
        )
        completed_wave = int(completed["wave"])
        result["wave_completed"] = completed

        respawned: dict[str, dict[str, str]] = {}
        for pipe_name in pipe_names:
            respawned[pipe_name] = _wait_for_values(
                pipe_name,
                lambda values, pipe=pipe_name: respawn_state_matches(
                    values,
                    previous_epoch=previous_epochs[pipe],
                    expected_wave=completed_wave,
                ),
                timeout=8.0,
                description=(
                    f"wave-{completed_wave} owner-local respawn"
                ),
            )
        result["respawned"] = respawned
        result["ok"] = True
        return result
    finally:
        stop_game_processes(process_ids)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--instance-prefix",
        default="",
        help="Unique launcher instance prefix (generated by default).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT,
    )
    args = parser.parse_args()

    instance_prefix = args.instance_prefix or (
        f"death-spec-{os.getpid()}-{int(time.time())}"
    )
    result: dict[str, object] = {"ok": False}
    try:
        result = run_live_verification(
            instance_prefix=instance_prefix,
            ports=_reserve_udp_ports(3),
        )
        exit_code = 0
    except Exception as exc:  # noqa: BLE001 - emit full verifier failure.
        result["error"] = str(exc)
        result["instance_prefix"] = instance_prefix
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
