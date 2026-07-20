#!/usr/bin/env python3
"""Verify complete Magic Shield state replication in both directions."""

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


ACTIVE_SHIELD = {
    "absorb_remaining": 25.0,
    "absorb_capacity": 25.0,
    "explosion_fraction": 0.5,
    "hit_flash": 0.0,
}
HIT_SHIELD = {
    "absorb_remaining": 5.0,
    "absorb_capacity": 25.0,
    "explosion_fraction": 0.5,
    "hit_flash": 1.0,
}
CLEARED_SHIELD = {
    "absorb_remaining": 0.0,
    "absorb_capacity": 0.0,
    "explosion_fraction": 0.0,
    "hit_flash": 0.0,
}
STATE_TOLERANCE = 0.01


def lua_id(participant_id: int) -> str:
    return f"0x{participant_id:X}"


def set_local_magic_shield_state(
    pipe_name: str,
    state: dict[str, float],
) -> dict[str, str]:
    code = f"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local player = sd.player.get_state()
if player == nil or player.actor_address == nil or player.actor_address == 0 then
  error("player actor unavailable")
end
local actor = tonumber(player.actor_address) or 0
local oremaining = sd.debug.layout_offset("actor_magic_shield_absorb_remaining")
local ocapacity = sd.debug.layout_offset("actor_magic_shield_absorb_capacity")
local oexplosion = sd.debug.layout_offset("actor_magic_shield_explosion_fraction")
local oflash = sd.debug.layout_offset("actor_magic_shield_hit_flash")
emit("write.absorb_remaining", sd.debug.write_float(actor + oremaining, {state['absorb_remaining']}))
emit("write.absorb_capacity", sd.debug.write_float(actor + ocapacity, {state['absorb_capacity']}))
emit("write.explosion_fraction", sd.debug.write_float(actor + oexplosion, {state['explosion_fraction']}))
emit("write.hit_flash", sd.debug.write_float(actor + oflash, {state['hit_flash']}))
emit("absorb_remaining", sd.debug.read_float(actor + oremaining) or 0)
emit("absorb_capacity", sd.debug.read_float(actor + ocapacity) or 0)
emit("explosion_fraction", sd.debug.read_float(actor + oexplosion) or 0)
emit("hit_flash", sd.debug.read_float(actor + oflash) or 0)
"""
    values = parse_key_values(lua(pipe_name, code))
    write_keys = (
        "write.absorb_remaining",
        "write.absorb_capacity",
        "write.explosion_fraction",
        "write.hit_flash",
    )
    if any(values.get(key) != "true" for key in write_keys):
        raise VerifyFailure(f"failed to set local Magic Shield state on {pipe_name}: {values}")
    return values


def query_local_magic_shield_state(pipe_name: str) -> dict[str, str]:
    code = """
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local player = sd.player.get_state()
if player == nil then
  emit("available", false)
  return
end
emit("available", true)
emit("absorb_remaining", player.magic_shield_absorb_remaining or 0)
emit("absorb_capacity", player.magic_shield_absorb_capacity or 0)
emit("explosion_fraction", player.magic_shield_explosion_fraction or 0)
emit("hit_flash", player.magic_shield_hit_flash or 0)
"""
    return parse_key_values(lua(pipe_name, code))


def query_remote_magic_shield_state(
    observer_pipe: str,
    participant_id: int,
) -> dict[str, str]:
    code = f"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local snapshot = sd.bots.get_participant_state({lua_id(participant_id)})
if snapshot == nil then
  emit("available", false)
  return
end
emit("available", snapshot.available)
emit("materialized", snapshot.entity_materialized)
emit("absorb_remaining", snapshot.magic_shield_absorb_remaining or 0)
emit("absorb_capacity", snapshot.magic_shield_absorb_capacity or 0)
emit("explosion_fraction", snapshot.magic_shield_explosion_fraction or 0)
emit("hit_flash", snapshot.magic_shield_hit_flash or 0)
"""
    return parse_key_values(lua(observer_pipe, code))


def number(values: dict[str, str], key: str) -> float:
    try:
        return float(values.get(key, "nan"))
    except ValueError:
        return math.nan


def state_matches(values: dict[str, str], expected: dict[str, float]) -> bool:
    return all(
        math.isclose(number(values, key), value, rel_tol=0.0, abs_tol=STATE_TOLERANCE)
        for key, value in expected.items()
    )


def wait_for_remote_magic_shield_state(
    observer_pipe: str,
    participant_id: int,
    expected: dict[str, float],
    *,
    timeout: float,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = query_remote_magic_shield_state(observer_pipe, participant_id)
        if (
            last.get("available") == "true"
            and last.get("materialized") == "true"
            and state_matches(last, expected)
        ):
            return last
        time.sleep(0.12)
    raise VerifyFailure(
        f"remote Magic Shield state did not converge on {observer_pipe}; "
        f"expected={expected} last={last}"
    )


def verify_one_direction(
    *,
    owner_pipe: str,
    owner_name: str,
    observer_pipe: str,
    participant_id: int,
) -> dict[str, object]:
    observations: dict[str, object] = {"owner": owner_name}
    for label, expected in (
        ("cleared_before", CLEARED_SHIELD),
        ("active", ACTIVE_SHIELD),
        ("hit", HIT_SHIELD),
        ("cleared_after", CLEARED_SHIELD),
    ):
        written = set_local_magic_shield_state(owner_pipe, expected)
        owner_seen = query_local_magic_shield_state(owner_pipe)
        if not state_matches(owner_seen, expected):
            raise VerifyFailure(
                f"local Magic Shield state mismatch on {owner_pipe}; "
                f"expected={expected} actual={owner_seen}"
            )
        remote_seen = wait_for_remote_magic_shield_state(
            observer_pipe,
            participant_id,
            expected,
            timeout=5.0,
        )
        observations[label] = {
            "written": written,
            "owner_seen": owner_seen,
            "remote_seen": remote_seen,
        }
    return observations


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
