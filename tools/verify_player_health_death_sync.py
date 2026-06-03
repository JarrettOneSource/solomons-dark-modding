#!/usr/bin/env python3
"""Verify player HP, death presentation, inert corpse, and revive sync."""

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
    distance,
    launch_pair,
    lua,
    parse_key_values,
    place_player,
    start_host_testrun_and_wait_for_clients,
    stop_games,
    wait_for_remote,
)


DEAD_CORPSE_DRIVE_STATE = 1
ALIVE_TEST_HP = 375.0
ALIVE_TEST_MAX_HP = 500.0
DEAD_TEST_HP = -50.0
VITAL_SYNC_TOLERANCE = 8.0


def lua_id(participant_id: int) -> str:
    return f"0x{participant_id:X}"


def set_local_player_vitals(pipe_name: str, hp: float, max_hp: float = 50.0) -> dict[str, str]:
    code = f"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local player = sd.player.get_state()
if player == nil or player.actor_address == nil or player.actor_address == 0 then
  error("player actor unavailable")
end
local progression = tonumber(player.progression_address) or 0
if progression == 0 then
  progression = tonumber(sd.debug.read_ptr(player.actor_address + sd.debug.layout_offset("actor_progression_runtime_state"))) or 0
end
if progression == 0 then
  error("player progression unavailable")
end
local ohp = sd.debug.layout_offset("progression_hp")
local omaxhp = sd.debug.layout_offset("progression_max_hp")
local omp = sd.debug.layout_offset("progression_mp")
local omaxmp = sd.debug.layout_offset("progression_max_mp")
emit("actor", player.actor_address)
emit("progression", progression)
emit("before.hp", sd.debug.read_float(progression + ohp))
emit("before.max_hp", sd.debug.read_float(progression + omaxhp))
emit("write.max_hp", sd.debug.write_float(progression + omaxhp, {max_hp}))
emit("write.hp", sd.debug.write_float(progression + ohp, {hp}))
emit("write.max_mp", sd.debug.write_float(progression + omaxmp, {max_hp}))
emit("write.mp", sd.debug.write_float(progression + omp, {max_hp}))
local after = sd.player.get_state()
emit("after.hp", after and after.hp or -1)
emit("after.max_hp", after and after.max_hp or -1)
emit("after.mp", after and after.mp or -1)
emit("after.max_mp", after and after.max_mp or -1)
"""
    values = parse_key_values(lua(pipe_name, code))
    if values.get("write.max_hp") != "true" or values.get("write.hp") != "true":
        raise VerifyFailure(f"failed to set player HP on {pipe_name}: {values}")
    return values


def query_local_player_vitals(pipe_name: str) -> dict[str, str]:
    code = """
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local player = sd.player.get_state()
if player == nil then
  emit("available", false)
  return
end
emit("available", true)
emit("hp", player.hp or 0)
emit("max_hp", player.max_hp or 0)
emit("mp", player.mp or 0)
emit("max_mp", player.max_mp or 0)
emit("actor", player.actor_address or 0)
emit("progression", player.progression_address or 0)
"""
    return parse_key_values(lua(pipe_name, code))


def query_remote_participant(observer_pipe: str, participant_id: int) -> dict[str, str]:
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
emit("x", snapshot.x or 0)
emit("y", snapshot.y or 0)
emit("heading", snapshot.heading or 0)
emit("hp", snapshot.hp or 0)
emit("max_hp", snapshot.max_hp or 0)
emit("mp", snapshot.mp or 0)
emit("max_mp", snapshot.max_mp or 0)
emit("render_drive_effect_timer", snapshot.render_drive_effect_timer or 0)
emit("render_drive_effect_progress", snapshot.render_drive_effect_progress or 0)
emit("render_drive_overlay_alpha", snapshot.render_drive_overlay_alpha or 0)
emit("render_drive_move_blend", snapshot.render_drive_move_blend or 0)
emit("anim_drive_state", snapshot.anim_drive_state or 0)
emit("moving", snapshot.moving)
emit("runtime_valid", snapshot.runtime_valid)
emit("transform_valid", snapshot.transform_valid)
if snapshot.profile then
  emit("profile.element_id", snapshot.profile.element_id)
  emit("profile.discipline_id", snapshot.profile.discipline_id)
  emit("profile.level", snapshot.profile.level)
  emit("profile.experience", snapshot.profile.experience)
end
local runtime = sd.runtime.get_multiplayer_state and sd.runtime.get_multiplayer_state() or nil
if runtime and runtime.participants then
  for _, participant in ipairs(runtime.participants) do
    if participant.participant_id == id then
      emit("runtime.life_current", participant.life_current)
      emit("runtime.life_max", participant.life_max)
      emit("runtime.mana_current", participant.mana_current)
      emit("runtime.mana_max", participant.mana_max)
    end
  end
end
"""
    return parse_key_values(lua(observer_pipe, code))


def wait_for_remote_matches_owner_health(
    owner_pipe: str,
    observer_pipe: str,
    participant_id: int,
    expected_max_hp: float,
    *,
    expect_dead: bool,
    tolerance: float = VITAL_SYNC_TOLERANCE,
    timeout: float = 8.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    last_owner: dict[str, str] = {}
    while time.monotonic() < deadline:
        last_owner = query_local_player_vitals(owner_pipe)
        last = query_remote_participant(observer_pipe, participant_id)
        try:
            owner_hp = float(last_owner.get("hp", "nan"))
            owner_max_hp = float(last_owner.get("max_hp", "nan"))
            hp = float(last.get("hp", "nan"))
            max_hp = float(last.get("max_hp", "nan"))
            runtime_hp = float(last.get("runtime.life_current", "nan"))
            anim_drive_state = int(float(last.get("anim_drive_state", "0")))
        except ValueError:
            time.sleep(0.15)
            continue
        max_hp_ok = (
            math.isclose(max_hp, expected_max_hp, rel_tol=0.0, abs_tol=0.01)
            and math.isclose(owner_max_hp, expected_max_hp, rel_tol=0.0, abs_tol=0.01)
        )
        if expect_dead:
            health_ok = hp <= 0.001 and runtime_hp <= 0.001
            state_ok = anim_drive_state == DEAD_CORPSE_DRIVE_STATE
        else:
            health_ok = (
                owner_hp > 0.001
                and hp > 0.001
                and runtime_hp > 0.001
                and abs(hp - owner_hp) <= tolerance
                and abs(runtime_hp - owner_hp) <= tolerance
            )
            state_ok = anim_drive_state != DEAD_CORPSE_DRIVE_STATE
        if (
            last.get("available") == "true"
            and last.get("materialized") == "true"
            and max_hp_ok
            and health_ok
            and state_ok
        ):
            return last
        time.sleep(0.15)
    raise VerifyFailure(
        f"remote participant {participant_id} did not match owner health "
        f"max_hp={expected_max_hp} dead={expect_dead} on {observer_pipe}; "
        f"owner={last_owner} last={last}"
    )


def assert_dead_remote_ignores_transform(
    owner_pipe: str,
    observer_pipe: str,
    participant_id: int,
) -> dict[str, object]:
    before = query_remote_participant(observer_pipe, participant_id)
    before_xy = (float(before["x"]), float(before["y"]))
    place_player(owner_pipe, before_xy[0] + 96.0, before_xy[1] + 48.0, 90.0)
    time.sleep(1.0)
    after = query_remote_participant(observer_pipe, participant_id)
    after_xy = (float(after["x"]), float(after["y"]))
    moved = distance(before_xy[0], before_xy[1], after_xy[0], after_xy[1])
    if moved > 3.0:
        raise VerifyFailure(
            f"dead remote participant {participant_id} moved {moved:.3f} after owner transform update; "
            f"before={before} after={after}"
        )
    return {
        "before": list(before_xy),
        "after": list(after_xy),
        "moved": moved,
    }


def assert_restored_remote_follows_transform(
    owner_pipe: str,
    observer_pipe: str,
    participant_id: int,
) -> dict[str, object]:
    before = query_remote_participant(observer_pipe, participant_id)
    before_xy = (float(before["x"]), float(before["y"]))
    target_xy = (before_xy[0] + 72.0, before_xy[1])
    place_player(owner_pipe, target_xy[0], target_xy[1], 180.0)

    deadline = time.monotonic() + 8.0
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = query_remote_participant(observer_pipe, participant_id)
        after_xy = (float(last.get("x", "nan")), float(last.get("y", "nan")))
        hp = float(last.get("hp", "nan"))
        if hp > 0.001 and distance(before_xy[0], before_xy[1], after_xy[0], after_xy[1]) >= 12.0:
            return {
                "before": list(before_xy),
                "after": list(after_xy),
                "target": list(target_xy),
                "moved": distance(before_xy[0], before_xy[1], after_xy[0], after_xy[1]),
            }
        time.sleep(0.15)

    raise VerifyFailure(
        f"restored remote participant {participant_id} did not resume transform playback; "
        f"before={before} last={last}"
    )


def verify_one_direction(
    *,
    owner_pipe: str,
    owner_name: str,
    observer_pipe: str,
    participant_id: int,
) -> dict[str, object]:
    alive = set_local_player_vitals(owner_pipe, ALIVE_TEST_HP, ALIVE_TEST_MAX_HP)
    alive_seen = wait_for_remote_matches_owner_health(
        owner_pipe,
        observer_pipe,
        participant_id,
        ALIVE_TEST_MAX_HP,
        expect_dead=False,
    )

    dead = set_local_player_vitals(owner_pipe, DEAD_TEST_HP, ALIVE_TEST_MAX_HP)
    dead_seen = wait_for_remote_matches_owner_health(
        owner_pipe,
        observer_pipe,
        participant_id,
        ALIVE_TEST_MAX_HP,
        expect_dead=True,
    )
    inert = assert_dead_remote_ignores_transform(owner_pipe, observer_pipe, participant_id)

    restored = set_local_player_vitals(owner_pipe, ALIVE_TEST_MAX_HP, ALIVE_TEST_MAX_HP)
    restored_seen = wait_for_remote_matches_owner_health(
        owner_pipe,
        observer_pipe,
        participant_id,
        ALIVE_TEST_MAX_HP,
        expect_dead=False,
    )
    restored_motion = assert_restored_remote_follows_transform(
        owner_pipe,
        observer_pipe,
        participant_id,
    )

    return {
        "owner": owner_name,
        "alive_write": alive,
        "alive_seen": alive_seen,
        "dead_write": dead,
        "dead_seen": dead_seen,
        "dead_inert": inert,
        "restored_write": restored,
        "restored_seen": restored_seen,
        "restored_motion": restored_motion,
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
