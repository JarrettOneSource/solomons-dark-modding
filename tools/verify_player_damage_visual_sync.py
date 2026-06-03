#!/usr/bin/env python3
"""Verify remote-player damage flash presentation syncs and clears."""

from __future__ import annotations

import json
import math
import time

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
    lua,
    parse_key_values,
    start_host_testrun_and_wait_for_clients,
    stop_games,
    wait_for_remote,
)


PULSE_TIMER = 18.0
PULSE_PROGRESS = 1.0
VISUAL_EPSILON = 0.01


def lua_id(participant_id: int) -> str:
    return f"0x{participant_id:X}"


def set_local_damage_visual(pipe_name: str, timer: float, progress: float) -> dict[str, str]:
    code = f"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local player = sd.player.get_state()
if player == nil or player.actor_address == nil or player.actor_address == 0 then
  error("player actor unavailable")
end
local actor = tonumber(player.actor_address) or 0
local otimer = sd.debug.layout_offset("actor_render_drive_effect_timer")
local oprogress = sd.debug.layout_offset("actor_render_drive_effect_progress")
emit("actor", actor)
emit("write.effect_timer", sd.debug.write_float(actor + otimer, {timer}))
emit("write.effect_progress", sd.debug.write_float(actor + oprogress, {progress}))
emit("effect_timer", sd.debug.read_float(actor + otimer) or 0)
emit("effect_progress", sd.debug.read_float(actor + oprogress) or 0)
"""
    values = parse_key_values(lua(pipe_name, code))
    if values.get("write.effect_timer") != "true" or values.get("write.effect_progress") != "true":
        raise VerifyFailure(f"failed to set local damage visual on {pipe_name}: {values}")
    return values


def query_local_damage_visual(pipe_name: str) -> dict[str, str]:
    code = """
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local player = sd.player.get_state()
if player == nil or player.actor_address == nil or player.actor_address == 0 then
  emit("available", false)
  return
end
local actor = tonumber(player.actor_address) or 0
local otimer = sd.debug.layout_offset("actor_render_drive_effect_timer")
local oprogress = sd.debug.layout_offset("actor_render_drive_effect_progress")
local ooverlay = sd.debug.layout_offset("actor_render_drive_overlay_alpha")
local ophase = sd.debug.layout_offset("actor_render_drive_move_blend")
emit("available", true)
emit("actor", actor)
emit("effect_timer", sd.debug.read_float(actor + otimer) or 0)
emit("effect_progress", sd.debug.read_float(actor + oprogress) or 0)
emit("overlay_alpha", sd.debug.read_float(actor + ooverlay) or 0)
emit("overlay_phase", sd.debug.read_float(actor + ophase) or 0)
"""
    return parse_key_values(lua(pipe_name, code))


def query_remote_damage_visual(observer_pipe: str, participant_id: int) -> dict[str, str]:
    code = f"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local id = {lua_id(participant_id)}
local snapshot = sd.bots.get_participant_state(id)
if snapshot == nil then
  emit("available", false)
  return
end
emit("available", snapshot.available)
emit("materialized", snapshot.entity_materialized)
emit("actor", snapshot.actor_address or 0)
emit("hp", snapshot.hp or 0)
emit("max_hp", snapshot.max_hp or 0)
local actor = tonumber(snapshot.actor_address) or 0
if actor == 0 then
  emit("effect_timer", 0)
  emit("effect_progress", 0)
  emit("overlay_alpha", 0)
  emit("overlay_phase", 0)
  return
end
local otimer = sd.debug.layout_offset("actor_render_drive_effect_timer")
local oprogress = sd.debug.layout_offset("actor_render_drive_effect_progress")
local ooverlay = sd.debug.layout_offset("actor_render_drive_overlay_alpha")
local ophase = sd.debug.layout_offset("actor_render_drive_move_blend")
emit("effect_timer", sd.debug.read_float(actor + otimer) or 0)
emit("effect_progress", sd.debug.read_float(actor + oprogress) or 0)
emit("overlay_alpha", sd.debug.read_float(actor + ooverlay) or 0)
emit("overlay_phase", sd.debug.read_float(actor + ophase) or 0)
"""
    return parse_key_values(lua(observer_pipe, code))


def number(values: dict[str, str], key: str) -> float:
    try:
        value = float(values.get(key, "nan"))
    except ValueError:
        return math.nan
    return value


def visual_active(values: dict[str, str]) -> bool:
    return (
        number(values, "effect_timer") > VISUAL_EPSILON
        or number(values, "effect_progress") > VISUAL_EPSILON
    )


def wait_for_remote_visual_state(
    observer_pipe: str,
    participant_id: int,
    *,
    expect_active: bool,
    timeout: float,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = query_remote_damage_visual(observer_pipe, participant_id)
        if (
            last.get("available") == "true"
            and last.get("materialized") == "true"
            and visual_active(last) == expect_active
        ):
            return last
        time.sleep(0.12)
    raise VerifyFailure(
        f"remote participant {participant_id:#x} damage visual did not reach "
        f"active={expect_active} on {observer_pipe}; last={last}"
    )


def verify_one_direction(
    *,
    owner_pipe: str,
    owner_name: str,
    observer_pipe: str,
    participant_id: int,
) -> dict[str, object]:
    clear_before = set_local_damage_visual(owner_pipe, 0.0, 0.0)
    owner_clear_seen = query_local_damage_visual(owner_pipe)
    remote_clear_seen = wait_for_remote_visual_state(
        observer_pipe,
        participant_id,
        expect_active=False,
        timeout=3.0,
    )

    pulse = set_local_damage_visual(owner_pipe, PULSE_TIMER, PULSE_PROGRESS)
    owner_pulse_seen = query_local_damage_visual(owner_pipe)
    remote_pulse_seen = wait_for_remote_visual_state(
        observer_pipe,
        participant_id,
        expect_active=True,
        timeout=5.0,
    )

    cleared = set_local_damage_visual(owner_pipe, 0.0, 0.0)
    owner_cleared_seen = query_local_damage_visual(owner_pipe)
    remote_cleared_seen = wait_for_remote_visual_state(
        observer_pipe,
        participant_id,
        expect_active=False,
        timeout=5.0,
    )

    return {
        "owner": owner_name,
        "clear_before": clear_before,
        "owner_clear_seen": owner_clear_seen,
        "remote_clear_seen": remote_clear_seen,
        "pulse": pulse,
        "owner_pulse_seen": owner_pulse_seen,
        "remote_pulse_seen": remote_pulse_seen,
        "cleared": cleared,
        "owner_cleared_seen": owner_cleared_seen,
        "remote_cleared_seen": remote_cleared_seen,
    }


def main() -> int:
    result: dict[str, object] = {"ok": False}
    try:
        stop_games()
        result["launch"] = launch_pair()
        disable_bots()
        result["host_run_entry"] = start_host_testrun_and_wait_for_clients()
        wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "testrun")
        wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "testrun")

        result["host_to_client"] = verify_one_direction(
            owner_pipe=HOST_PIPE,
            owner_name=HOST_NAME,
            observer_pipe=CLIENT_PIPE,
            participant_id=HOST_ID,
        )
        result["client_to_host"] = verify_one_direction(
            owner_pipe=CLIENT_PIPE,
            owner_name=CLIENT_NAME,
            observer_pipe=HOST_PIPE,
            participant_id=CLIENT_ID,
        )

        result["ok"] = True
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        result["error"] = str(exc)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1
    finally:
        stop_games()


if __name__ == "__main__":
    raise SystemExit(main())
