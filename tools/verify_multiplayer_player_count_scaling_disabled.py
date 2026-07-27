#!/usr/bin/env python3
"""Measure and verify stock enemy balance at one and two players."""

from __future__ import annotations

import argparse
import json
import math
import time
import traceback
from pathlib import Path
from typing import Any

from verify_game_over_session_semantics import (
    _disable_bots,
    _owned_solo_processes,
    _start_testrun_when_ready as _start_solo_testrun_when_ready,
    launch_solo,
    stop_owned_processes,
    validate_owned_processes,
)
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    HOST_NAME,
    ROOT,
    VerifyFailure,
    game_process_ids,
    launch_pair,
    lua,
    parse_key_values,
    place_player,
    stop_exact_game_processes,
    wait_for_remote,
    wait_for_scene,
)
from verify_multiplayer_organic_player_death import (
    ACCEPTANCE_MOD_ID,
    ARM_DAMAGE_PROBE,
    QUERY_DAMAGE_PROBE,
    _arm_enemy_arena,
    _disable_companion_bots,
    _parse_damage_probe,
    _query_live_enemies,
    _set_enemy_attack,
    _start_testrun_when_ready,
    _start_waves,
    _wait_for_new_wave_enemy,
    _wait_for_victim_damage,
)
from verify_player_health_death_sync import set_local_player_vitals


OUTPUT = ROOT / "runtime" / "multiplayer_player_count_scaling.json"
ARTIFACT_ROOT = ROOT / "runtime" / "multiplayer_player_count_scaling"
NORMALIZED_STOCK_ENEMY_HP = 5000.0
FIRST_WAVE_SKELETON_HP = 2.5
NORMALIZED_FUTURE_HP_SCALAR = (
    NORMALIZED_STOCK_ENEMY_HP / FIRST_WAVE_SKELETON_HP
)
ARENA_PLAYER_COUNT_SCALAR_OFFSET = 0x8FE4
ARENA_FUTURE_HP_SCALAR_OFFSET = 0x9008
MEASUREMENT_SECONDS = 5.0
NORMALIZED_STOCK_WAVE = """\
WAVE
\tNEXT:0
\tSPAWN:1
\tSPAWNDELAY:1-1
\tWAVEDELAY:100-100
\tMAXENEMIES:1
\tGROUP
\t\tSKELETON:FLAG_WEAK|FLAG_HPDOWN|FLAG_XPBONUS
\tENDWAVE
"""


ARENA_SCALAR_PROBE_LUA = f"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local world = sd.world and sd.world.get_state and sd.world.get_state() or nil
local arena = tonumber(world and world.arena_address) or 0
emit("arena_address", arena)
emit("player_count_value",
  arena ~= 0 and sd.debug.read_u32(
    arena + {ARENA_PLAYER_COUNT_SCALAR_OFFSET}) or 0)
emit("player_count_value_as_float",
  arena ~= 0 and sd.debug.read_float(
    arena + {ARENA_PLAYER_COUNT_SCALAR_OFFSET}) or 0)
emit("future_hp_scalar",
  arena ~= 0 and sd.debug.read_float(
    arena + {ARENA_FUTURE_HP_SCALAR_OFFSET}) or 0)
"""


SET_NORMALIZED_FUTURE_HP_SCALAR_LUA = f"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local world = assert(sd.world.get_state())
local arena = tonumber(world.arena_address) or 0
if arena == 0 then error("arena unavailable") end
emit("arena_address", arena)
emit("before", sd.debug.read_float(
  arena + {ARENA_FUTURE_HP_SCALAR_OFFSET}))
emit("write", sd.debug.write_float(
  arena + {ARENA_FUTURE_HP_SCALAR_OFFSET},
  {NORMALIZED_FUTURE_HP_SCALAR:.6f}))
emit("after", sd.debug.read_float(
  arena + {ARENA_FUTURE_HP_SCALAR_OFFSET}))
"""


CHALLENGE_PLAYER_COUNT_POLICY_LUA = f"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local world = assert(sd.world.get_state())
local arena = tonumber(world.arena_address) or 0
if arena == 0 then error("arena unavailable") end
emit("before", sd.debug.read_u32(
  arena + {ARENA_PLAYER_COUNT_SCALAR_OFFSET}))
emit("write", sd.debug.write_u32(
  arena + {ARENA_PLAYER_COUNT_SCALAR_OFFSET}, 2))
emit("after", sd.debug.read_u32(
  arena + {ARENA_PLAYER_COUNT_SCALAR_OFFSET}))
"""


MEMBERSHIP_PROBE_LUA = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local multiplayer = assert(sd.runtime.get_multiplayer_state())
local connected = 0
local in_run = 0
for _, participant in ipairs(multiplayer.participants or {}) do
  if participant.transport_connected then connected = connected + 1 end
  if participant.transport_connected and participant.in_run then
    in_run = in_run + 1
  end
end
emit("participant_count", multiplayer.participant_count or 0)
emit("connected_count", connected)
emit("in_run_count", in_run)
"""


RUN_MEASUREMENT_LUA = r"""
local state = assert(sd.waves.get_state())
local world = assert(sd.world.get_state())
print("wave=" .. tostring(state.wave or 0))
print("phase=" .. tostring(state.phase or ""))
print("planned=" .. tostring(state.planned or 0))
print("spawned=" .. tostring(state.spawned or 0))
print("alive=" .. tostring(state.alive or 0))
print("killed=" .. tostring(state.killed or 0))
print("remaining_to_spawn=" .. tostring(state.remaining_to_spawn or 0))
print("world_enemy_count=" .. tostring(world.enemy_count or 0))
for _, row in ipairs(state.composition or {}) do
  print(table.concat({
    "C",
    tostring(row.type_id or row.enemy_type or row.name or ""),
    tostring(row.planned or 0),
    tostring(row.spawned or 0),
    tostring(row.alive or 0),
    tostring(row.killed or 0),
  }, "|"))
end
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  if actor.tracked_enemy and not actor.dead and
      (tonumber(actor.hp) or 0) > 0 then
    print(table.concat({
      "E",
      tostring(tonumber(actor.actor_address) or 0),
      tostring(tonumber(actor.object_type_id) or 0),
      tostring(tonumber(actor.enemy_type) or 0),
      string.format("%.6f", tonumber(actor.hp) or 0),
      string.format("%.6f", tonumber(actor.max_hp) or 0),
    }, "|"))
  end
end
"""


def _parse_run_measurement(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "state": parse_key_values(text),
        "composition": [],
        "enemies": [],
    }
    for line in text.splitlines():
        if line.startswith("C|"):
            parts = line.split("|")
            if len(parts) != 6:
                raise VerifyFailure(f"malformed wave composition row: {line}")
            result["composition"].append(
                {
                    "type": parts[1],
                    "planned": int(parts[2]),
                    "spawned": int(parts[3]),
                    "alive": int(parts[4]),
                    "killed": int(parts[5]),
                }
            )
        elif line.startswith("E|"):
            parts = line.split("|")
            if len(parts) != 6:
                raise VerifyFailure(f"malformed enemy row: {line}")
            result["enemies"].append(
                {
                    "actor_address": int(parts[1]),
                    "object_type_id": int(parts[2]),
                    "enemy_type": int(parts[3]),
                    "hp": float(parts[4]),
                    "max_hp": float(parts[5]),
                }
            )
    return result


def _measure_run(
    pipe_name: str,
    *,
    expected_participant_count: int,
    challenge_player_count_policy: bool,
) -> dict[str, Any]:
    membership = parse_key_values(lua(pipe_name, MEMBERSHIP_PROBE_LUA))
    if int(membership.get("participant_count", "0")) != expected_participant_count:
        raise VerifyFailure(
            "measurement participant count differs: "
            f"expected={expected_participant_count} actual={membership}"
        )
    set_local_player_vitals(
        pipe_name,
        NORMALIZED_STOCK_ENEMY_HP,
        NORMALIZED_STOCK_ENEMY_HP,
    )
    place_player(pipe_name, 1850.0, 1750.0, 180.0)
    pre_wave_addresses = {
        int(actor["actor_address"])
        for actor in _query_live_enemies(pipe_name)
    }
    arena = _arm_enemy_arena(pipe_name, 1850.0, 1750.0)
    damage_probe = parse_key_values(lua(pipe_name, ARM_DAMAGE_PROBE))
    if damage_probe.get("registered") != "true":
        raise VerifyFailure(f"damage probe did not register: {damage_probe}")
    scalar_before = parse_key_values(lua(pipe_name, ARENA_SCALAR_PROBE_LUA))
    normalized = parse_key_values(
        lua(pipe_name, SET_NORMALIZED_FUTURE_HP_SCALAR_LUA)
    )
    if (
        normalized.get("write") != "true"
        or not math.isclose(
            float(normalized.get("after", "nan")),
            NORMALIZED_FUTURE_HP_SCALAR,
            rel_tol=0.0,
            abs_tol=0.001,
        )
    ):
        raise VerifyFailure(
            f"could not normalize native future enemy HP: {normalized}"
        )
    policy_challenge = None
    if challenge_player_count_policy:
        policy_challenge = parse_key_values(
            lua(pipe_name, CHALLENGE_PLAYER_COUNT_POLICY_LUA)
        )
        if (
            policy_challenge.get("write") != "true"
            or policy_challenge.get("after") != "2"
        ):
            raise VerifyFailure(
                "could not challenge the player-count scaling policy: "
                f"{policy_challenge}"
            )
    wave_start = _start_waves(pipe_name)
    selected = _wait_for_new_wave_enemy(
        pipe_name,
        pre_wave_actor_addresses=pre_wave_addresses,
        timeout=60.0,
    )
    time.sleep(MEASUREMENT_SECONDS)
    measured = _parse_run_measurement(
        lua(pipe_name, RUN_MEASUREMENT_LUA)
    )
    measured["enemies"] = [
        enemy
        for enemy in measured["enemies"]
        if int(enemy["actor_address"]) not in pre_wave_addresses
    ]
    selected_measurement = next(
        (
            enemy
            for enemy in measured["enemies"]
            if int(enemy["actor_address"]) == int(selected["actor_address"])
        ),
        None,
    )
    if selected_measurement is None:
        raise VerifyFailure(
            "selected stock enemy left the normalized census: "
            f"selected={selected} measured={measured}"
        )
    scalar_after_spawn = parse_key_values(
        lua(pipe_name, ARENA_SCALAR_PROBE_LUA)
    )
    attack = _set_enemy_attack(
        pipe_name,
        target_x=1850.0,
        target_y=1750.0,
        target_participant_id=0,
        enemy_actor_address=int(selected["actor_address"]),
        attack_distance=-64.0,
    )
    damage_observed = _wait_for_victim_damage(
        pipe_name,
        baseline_hp=NORMALIZED_STOCK_ENEMY_HP,
        timeout=18.0,
    )
    time.sleep(2.0)
    damage_events = _parse_damage_probe(lua(pipe_name, QUERY_DAMAGE_PROBE))
    local_damage = [
        event
        for event in damage_events
        if int(event["target_participant_id"]) == 0
        and float(event["total_damage"]) > 0
    ]
    observed_damage = float(damage_observed["damage"])
    return {
        "membership": membership,
        "pre_wave_enemy_count": len(pre_wave_addresses),
        "arena": arena,
        "damage_probe": damage_probe,
        "scalar_before": scalar_before,
        "normalized_future_hp_scalar": normalized,
        "player_count_policy_challenge": policy_challenge,
        "wave_start": wave_start,
        "selected_before_measurement": selected,
        "measurement_seconds": MEASUREMENT_SECONDS,
        "wave_measurement": measured,
        "selected_measurement": selected_measurement,
        "scalar_after_spawn": scalar_after_spawn,
        "attack": attack,
        "damage_observed": damage_observed,
        "damage_events": local_damage,
        "damage_summary": {
            "observed_hp_delta": observed_damage,
            "event_count": len(local_damage),
            "event_totals": [
                float(event["total_damage"]) for event in local_damage
            ],
        },
    }


def _run_solo(
    *,
    instance_prefix: str,
    ports: list[int],
    game_directory: Path,
    launcher_path: Path,
    wave_override: Path,
    challenge_player_count_policy: bool,
) -> dict[str, Any]:
    instance = f"{instance_prefix}-solo"
    launch = launch_solo(
        instance=instance,
        local_port=ports[0],
        unused_remote_port=ports[1],
        game_directory=game_directory,
        launcher_path=launcher_path,
        test_blank_boneyard=False,
        test_wave_override=wave_override,
        quick_start=False,
        fresh_install=False,
    )
    owned = _owned_solo_processes(launch)
    result: dict[str, Any] = {
        "launch": launch,
        "owned_processes": validate_owned_processes(owned),
    }
    if launch.get("audioDisabled") is not True:
        stop_owned_processes(owned)
        raise VerifyFailure(f"solo audio was not disabled: {launch}")
    pipe_name = str(launch["luaPipe"])
    try:
        wait_for_scene(pipe_name, "hub", 45.0)
        result["bots_disabled"] = _disable_bots([pipe_name])
        _start_solo_testrun_when_ready(pipe_name)
        wait_for_scene(pipe_name, "testrun", 45.0)
        time.sleep(3.0)
        result["measurement"] = _measure_run(
            pipe_name,
            expected_participant_count=1,
            challenge_player_count_policy=challenge_player_count_policy,
        )
        return result
    finally:
        result["cleanup"] = stop_owned_processes(owned)


def _run_pair(
    *,
    instance_prefix: str,
    ports: list[int],
    game_directory: Path,
    launcher_path: Path,
    wave_override: Path,
    challenge_player_count_policy: bool,
) -> dict[str, Any]:
    launch = launch_pair(
        host_preset="map_create_fire_mind_hub",
        client_preset="map_create_air_mind_hub",
        temporary_host_profile=True,
        tile_windows=False,
        test_blank_boneyard=False,
        test_wave_override=wave_override,
        use_sandbox_preset_flow=True,
        kill_existing=False,
        instance_prefix=instance_prefix,
        host_port=ports[0],
        client_port=ports[1],
        game_directory=game_directory,
        launcher_path=launcher_path,
        exact_mod_id=ACCEPTANCE_MOD_ID,
        enable_audio=False,
    )
    result: dict[str, Any] = {
        "launch": launch,
        "process_ids": game_process_ids(launch),
    }
    if launch.get("audioDisabled") is not True:
        result["cleanup"] = stop_exact_game_processes(launch)
        raise VerifyFailure(f"pair audio was not disabled: {launch}")
    if len(result["process_ids"]) != 2:
        result["cleanup"] = stop_exact_game_processes(launch)
        raise VerifyFailure(f"pair launch omitted exact PIDs: {launch}")
    host_pipe = str(launch["hostLuaPipe"])
    client_pipe = str(launch["clientLuaPipe"])
    try:
        _disable_companion_bots([host_pipe, client_pipe])
        _start_testrun_when_ready(host_pipe)
        wait_for_scene(host_pipe, "testrun", 45.0)
        wait_for_scene(client_pipe, "testrun", 45.0)
        result["relationships"] = {
            "host_observes_client": wait_for_remote(
                host_pipe, CLIENT_ID, CLIENT_NAME, "testrun", 45.0
            ),
            "client_observes_host": wait_for_remote(
                client_pipe, 0x2000000000001001, HOST_NAME, "testrun", 45.0
            ),
        }
        set_local_player_vitals(
            client_pipe,
            NORMALIZED_STOCK_ENEMY_HP,
            NORMALIZED_STOCK_ENEMY_HP,
        )
        place_player(client_pipe, 2350.0, 1750.0, 0.0)
        result["measurement"] = _measure_run(
            host_pipe,
            expected_participant_count=2,
            challenge_player_count_policy=challenge_player_count_policy,
        )
        return result
    finally:
        result["cleanup"] = stop_exact_game_processes(launch)


def _comparison(solo: dict[str, Any], pair: dict[str, Any]) -> dict[str, Any]:
    solo_measurement = solo["measurement"]
    pair_measurement = pair["measurement"]
    solo_enemy = solo_measurement["selected_measurement"]
    pair_enemy = pair_measurement["selected_measurement"]
    solo_wave = solo_measurement["wave_measurement"]
    pair_wave = pair_measurement["wave_measurement"]
    solo_scalar = float(
        solo_measurement["scalar_after_spawn"]["player_count_value"]
    )
    pair_scalar = float(
        pair_measurement["scalar_after_spawn"]["player_count_value"]
    )
    hp_matches = (
        math.isclose(
            float(solo_enemy["hp"]),
            NORMALIZED_STOCK_ENEMY_HP,
            rel_tol=0.0,
            abs_tol=0.01,
        )
        and math.isclose(
            float(pair_enemy["hp"]),
            float(solo_enemy["hp"]),
            rel_tol=0.0,
            abs_tol=0.01,
        )
        and math.isclose(
            float(pair_enemy["max_hp"]),
            float(solo_enemy["max_hp"]),
            rel_tol=0.0,
            abs_tol=0.01,
        )
    )
    damage_matches = math.isclose(
        float(pair_measurement["damage_summary"]["observed_hp_delta"]),
        float(solo_measurement["damage_summary"]["observed_hp_delta"]),
        rel_tol=0.0,
        abs_tol=0.01,
    )
    spawn_count_matches = (
        int(pair_wave["state"]["planned"]) ==
            int(solo_wave["state"]["planned"])
        and int(pair_wave["state"]["spawned"]) ==
            int(solo_wave["state"]["spawned"])
    )
    composition_matches = (
        pair_wave["composition"] == solo_wave["composition"]
    )
    scalar_matches = (
        math.isclose(solo_scalar, 1.0, rel_tol=0.0, abs_tol=0.001)
        and math.isclose(pair_scalar, 1.0, rel_tol=0.0, abs_tol=0.001)
    )
    challenges = [
        solo_measurement["player_count_policy_challenge"],
        pair_measurement["player_count_policy_challenge"],
    ]
    policy_challenge_corrected = all(
        challenge is None
        or (
            challenge.get("write") == "true"
            and challenge.get("after") == "2"
        )
        for challenge in challenges
    ) and scalar_matches
    return {
        "normalized_stock_enemy_hp": NORMALIZED_STOCK_ENEMY_HP,
        "solo_player_count_scalar": solo_scalar,
        "pair_player_count_scalar": pair_scalar,
        "solo_enemy": solo_enemy,
        "pair_enemy": pair_enemy,
        "solo_planned_spawn_count": int(solo_wave["state"]["planned"]),
        "pair_planned_spawn_count": int(pair_wave["state"]["planned"]),
        "solo_observed_spawn_count": int(solo_wave["state"]["spawned"]),
        "pair_observed_spawn_count": int(pair_wave["state"]["spawned"]),
        "solo_composition": solo_wave["composition"],
        "pair_composition": pair_wave["composition"],
        "solo_damage": solo_measurement["damage_summary"][
            "observed_hp_delta"
        ],
        "pair_damage": pair_measurement["damage_summary"][
            "observed_hp_delta"
        ],
        "scalar_matches": scalar_matches,
        "player_count_policy_challenge_corrected":
            policy_challenge_corrected,
        "hp_matches": hp_matches,
        "damage_matches": damage_matches,
        "spawn_count_matches": spawn_count_matches,
        "composition_matches": composition_matches,
        "passed": (
            scalar_matches
            and policy_challenge_corrected
            and hp_matches
            and damage_matches
            and spawn_count_matches
            and composition_matches
        ),
    }


def run_live_verification(
    *,
    instance_prefix: str,
    ports: list[int],
    game_directory: Path,
    launcher_path: Path,
    artifact_root: Path,
    measure_only: bool,
) -> dict[str, Any]:
    artifact_root.mkdir(parents=True, exist_ok=True)
    wave_override = artifact_root / "normalized-stock-wave.txt"
    wave_override.write_text(NORMALIZED_STOCK_WAVE, encoding="utf-8")
    result: dict[str, Any] = {
        "ok": False,
        "measure_only": measure_only,
        "instance_prefix": instance_prefix,
        "ports": ports,
        "wave_override": str(wave_override),
    }
    try:
        result["solo"] = _run_solo(
            instance_prefix=instance_prefix,
            ports=ports,
            game_directory=game_directory,
            launcher_path=launcher_path,
            wave_override=wave_override,
            challenge_player_count_policy=not measure_only,
        )
        result["pair"] = _run_pair(
            instance_prefix=instance_prefix,
            ports=ports,
            game_directory=game_directory,
            launcher_path=launcher_path,
            wave_override=wave_override,
            challenge_player_count_policy=not measure_only,
        )
        result["comparison"] = _comparison(
            result["solo"],
            result["pair"],
        )
        result["ok"] = measure_only or result["comparison"]["passed"]
        return result
    except Exception as exc:
        result["error"] = str(exc)
        result["error_type"] = type(exc).__name__
        result["traceback"] = traceback.format_exc()
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance-prefix", required=True)
    parser.add_argument("--host-port", type=int, required=True)
    parser.add_argument("--client-port", type=int, required=True)
    parser.add_argument("--game-dir", type=Path, required=True)
    parser.add_argument("--launcher-path", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, default=ARTIFACT_ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--measure-only", action="store_true")
    args = parser.parse_args()
    result = run_live_verification(
        instance_prefix=args.instance_prefix,
        ports=[args.host_port, args.client_port],
        game_directory=args.game_dir,
        launcher_path=args.launcher_path,
        artifact_root=args.artifact_root,
        measure_only=args.measure_only,
    )
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
                "comparison": result.get("comparison"),
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
