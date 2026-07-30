#!/usr/bin/env python3
"""Verify living-player preservation and dead-player wave respawn."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import verify_multiplayer_death_spectator_respawn as death
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    HOST_ID,
    HOST_NAME,
    ROOT,
    VerifyFailure,
    game_process_ids,
    launch_pair,
    lua,
    parse_key_values,
    place_player,
    stop_game_processes,
    wait_for_remote,
    wait_for_scene,
)


HOST_PORT = 50911
CLIENT_PORT = 50912
RUN_GENERATION_SEED = 0x2FFE3A50
HOST_TEST_POSITION = (1550.0, 550.0)
CLIENT_TEST_POSITION = (50.0, 350.0)
POSITION_TOLERANCE = 0.25
REMOTE_POSITION_TOLERANCE = 3.0
VITAL_TOLERANCE = 0.05
SPAWN_SEPARATION_MINIMUM = 160.0
OUTPUT = ROOT / "runtime" / "multiplayer_wave_boundary_respawn.json"
SAVE_FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "savegames"
    / "fieldbreak25_existing_wizard"
)
FOCUSED_WAVE_STATE_PROBE = death.WAVE_STATE_PROBE + r"""
local combat = sd.gameplay.get_combat_state()
local world = sd.world.get_state()
print("combat_available=" .. tostring(combat ~= nil))
print("combat_wave=" ..
  tostring(combat and combat.wave_index or 0))
print("combat_wait_ticks=" ..
  tostring(combat and combat.wait_ticks or -1))
print("combat_wave_counter=" ..
  tostring(combat and combat.wave_counter or -1))
print("combat_active=" ..
  tostring(combat and combat.active or false))
print("world_wave=" .. tostring(world and world.wave or 0))
print("world_combat_active=" ..
  tostring(world and world.combat_active or false))
"""
SURVIVAL_HOLD = r"""
local enabled = __ENABLED__
local function sustain()
  if not _G.__fb25_survival_hold_enabled then
    return true
  end
  local player = sd.player.get_state()
  local progression =
    player and tonumber(player.progression_address) or 0
  if progression == 0 then
    return false
  end
  local hp = sd.debug.layout_offset("progression_hp")
  local max_hp = sd.debug.layout_offset("progression_max_hp")
  local mp = sd.debug.layout_offset("progression_mp")
  local max_mp = sd.debug.layout_offset("progression_max_mp")
  local hp_value = tonumber(sd.debug.read_float(progression + max_hp)) or 0
  local mp_value = tonumber(sd.debug.read_float(progression + max_mp)) or 0
  if hp_value <= 0 or mp_value < 0 then
    return false
  end
  return sd.debug.write_float(progression + hp, hp_value) and
    sd.debug.write_float(progression + mp, mp_value)
end
_G.__fb25_survival_hold_enabled = enabled
if not _G.__fb25_survival_hold_registered then
  sd.events.on("runtime.tick", sustain)
  _G.__fb25_survival_hold_registered = true
end
print("registered=" ..
  tostring(_G.__fb25_survival_hold_registered))
print("enabled=" .. tostring(_G.__fb25_survival_hold_enabled))
print("initial_apply=" .. tostring(sustain()))
"""
HOLD_ONE_LIVE_WAVE_ENEMY = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value))
end
local actors = sd.world.list_actors and sd.world.list_actors() or {}
local hp_offset = sd.debug.layout_offset("enemy_current_hp")
local max_hp_offset = sd.debug.layout_offset("enemy_max_hp")
local progression_offset =
  sd.debug.layout_offset("actor_progression_runtime_state")
local progression_hp_offset = sd.debug.layout_offset("progression_hp")
local progression_max_hp_offset =
  sd.debug.layout_offset("progression_max_hp")
local held = tonumber(_G.__fb25_wave_one_survivor) or 0
local live = {}
for _, actor in ipairs(actors) do
  local address = tonumber(actor.actor_address) or 0
  local max_hp = tonumber(actor.max_hp) or 0
  if address ~= 0 and actor.tracked_enemy and not actor.dead and max_hp > 0 then
    table.insert(live, address)
  end
end
table.sort(live)
local held_live = false
for _, address in ipairs(live) do
  if address == held then
    held_live = true
    break
  end
end
if not held_live then
  held = live[1] or 0
  _G.__fb25_wave_one_survivor = held
end
local triggered = 0
for _, address in ipairs(live) do
  if address == held then
    sd.debug.write_float(address + max_hp_offset, 1000000.0)
    sd.debug.write_float(address + hp_offset, 1000000.0)
    local progression =
      tonumber(sd.debug.read_ptr(address + progression_offset)) or 0
    if progression ~= 0 then
      sd.debug.write_float(
        progression + progression_max_hp_offset,
        1000000.0)
      sd.debug.write_float(
        progression + progression_hp_offset,
        1000000.0)
    end
  else
    sd.debug.write_float(address + hp_offset, 0)
    if sd.world.trigger_enemy_death(address) then
      triggered = triggered + 1
    end
  end
end
emit("live_seen", #live)
emit("held_actor", held)
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


def _distance(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> float:
    return math.hypot(x2 - x1, y2 - y1)


def _fixture_manifest() -> dict[str, str]:
    root = SAVE_FIXTURE / "solomondark"
    if not root.is_dir():
        raise VerifyFailure(
            f"existing-wizard save fixture is missing: {root}"
        )
    manifest: dict[str, str] = {}
    files = (
        candidate
        for candidate in root.rglob("*")
        if candidate.is_file()
    )
    for path in sorted(files):
        manifest[path.relative_to(SAVE_FIXTURE).as_posix()] = (
            hashlib.sha256(path.read_bytes()).hexdigest()
        )
    required = {
        "solomondark/darkdata.cfg",
        "solomondark/savegames/ARTORIUS/Region0._cache",
    }
    missing = sorted(required.difference(manifest))
    if missing:
        raise VerifyFailure(
            f"existing-wizard save fixture is incomplete: {missing}"
        )
    return manifest


def _copy_fixture_to_save_root(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    shutil.copytree(
        SAVE_FIXTURE / "solomondark",
        destination / "solomondark",
    )


def _source_sha() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.returncode != 0:
        raise VerifyFailure(
            f"could not resolve source SHA: {completed.stdout.strip()}"
        )
    return completed.stdout.strip()


def _set_run_generation_seed(host_pipe: str) -> dict[str, str]:
    values = parse_key_values(
        lua(
            host_pipe,
            f"""
local requested = {RUN_GENERATION_SEED}
local accepted = sd.rng.set_seed(requested)
local observed = sd.rng.get_seed()
print("requested=" .. tostring(requested))
print("accepted=" .. tostring(accepted))
print("observed=" .. tostring(observed))
""",
        )
    )
    expected = str(RUN_GENERATION_SEED)
    if (
        values.get("requested") != expected
        or values.get("accepted") != expected
        or values.get("observed") != expected
    ):
        raise VerifyFailure(
            f"host did not accept the pinned run seed: {values}"
        )
    return values


def _query_views(
    *,
    owner_pipe: str,
    observer_pipe: str,
    participant_id: int,
) -> dict[str, dict[str, str]]:
    return {
        "owner": death.query_spectator_state(owner_pipe),
        "observer": death.query_remote_death_state(
            observer_pipe,
            participant_id,
        ),
    }


def _spawn_from_owner(
    values: Mapping[str, str],
    *,
    label: str,
) -> tuple[float, float]:
    spawn_x = _number(values, "player_spawn_x")
    spawn_y = _number(values, "player_spawn_y")
    if (
        values.get("player_spawn_valid") != "true"
        or not math.isfinite(spawn_x)
        or not math.isfinite(spawn_y)
        or _integer(values, "arena_address") == 0
    ):
        raise VerifyFailure(
            f"{label} did not expose its live Arena spawn: {dict(values)}"
        )
    return spawn_x, spawn_y


def _wait_for_local_spawn_ready(
    pipe_name: str,
    *,
    label: str,
    timeout: float = 10.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = death.query_spectator_state(pipe_name)
        try:
            _spawn_from_owner(last, label=label)
        except VerifyFailure:
            time.sleep(0.05)
            continue
        if (
            _integer(last, "actor_address") != 0
            and _number(last, "hp") > VITAL_TOLERANCE
        ):
            return last
        time.sleep(0.05)
    raise VerifyFailure(
        f"{label} did not expose a living actor and finalized spawn: {last}"
    )


def _confirm_position_views(
    *,
    owner_pipe: str,
    observer_pipe: str,
    participant_id: int,
    label: str,
) -> dict[str, dict[str, str]]:
    views = _query_views(
        owner_pipe=owner_pipe,
        observer_pipe=observer_pipe,
        participant_id=participant_id,
    )
    owner = views["owner"]
    observer = views["observer"]
    owner_position = (
        _number(owner, "x"),
        _number(owner, "y"),
    )
    observer_position = (
        _number(observer, "x"),
        _number(observer, "y"),
    )
    spawn = _spawn_from_owner(owner, label=label)
    if (
        _integer(owner, "actor_address") == 0
        or observer.get("materialized") != "true"
        or _integer(observer, "actor_address") == 0
        or _distance(
            *owner_position,
            *observer_position,
        )
        > REMOTE_POSITION_TOLERANCE
        or _distance(
            *owner_position,
            *spawn,
        )
        < SPAWN_SEPARATION_MINIMUM
    ):
        raise VerifyFailure(
            f"{label} did not converge away from spawn after run loading: "
            f"{views}"
        )
    return views


def _preplace_participant_away_from_spawn(
    *,
    pipe_name: str,
    label: str,
    target: tuple[float, float],
    heading: float,
) -> dict[str, Any]:
    before = _wait_for_local_spawn_ready(
        pipe_name,
        label=label,
    )
    spawn_x, spawn_y = _spawn_from_owner(
        before,
        label=label,
    )
    target_x, target_y = target
    separation = _distance(
        spawn_x,
        spawn_y,
        target_x,
        target_y,
    )
    if separation < SPAWN_SEPARATION_MINIMUM:
        raise VerifyFailure(
            f"{label} target remained too close to spawn: "
            f"spawn=({spawn_x},{spawn_y}) target=({target_x},{target_y})"
        )
    placement = place_player(
        pipe_name,
        target_x,
        target_y,
        heading,
    )
    if placement.get("rebind") != "true":
        raise VerifyFailure(
            f"{label} preplacement did not rebind its actor: {placement}"
        )
    return {
        "spawn": {"x": spawn_x, "y": spawn_y},
        "target": {"x": target_x, "y": target_y},
        "separation": separation,
        "placement": placement,
    }


def _wait_for_local_respawn_epoch(
    pipe_name: str,
    *,
    previous_epoch: int,
    expected_wave: int,
    timeout: float = 8.0,
) -> dict[str, str]:
    return death._wait_for_values(
        pipe_name,
        lambda values: (
            _integer(values, "last_applied_respawn_epoch")
            > previous_epoch
            and _integer(values, "last_applied_respawn_wave")
            == expected_wave
        ),
        timeout=timeout,
        description=(
            f"wave-{expected_wave} respawn epoch acknowledgement"
        ),
    )


def _wait_for_remote_respawn_convergence(
    observer_pipe: str,
    *,
    participant_id: int,
    owner_state: Mapping[str, str],
    timeout: float = 5.0,
) -> dict[str, str]:
    spawn_x = _number(owner_state, "last_respawn_x")
    spawn_y = _number(owner_state, "last_respawn_y")
    if not math.isfinite(spawn_x) or not math.isfinite(spawn_y):
        raise VerifyFailure(
            f"dead owner did not expose its respawn command: {owner_state}"
        )
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = death.query_remote_death_state(
            observer_pipe,
            participant_id,
        )
        if (
            last.get("materialized") == "true"
            and _integer(last, "actor_address") != 0
            and _number(last, "hp") > VITAL_TOLERANCE
            and _distance(
                _number(last, "x"),
                _number(last, "y"),
                spawn_x,
                spawn_y,
            )
            <= REMOTE_POSITION_TOLERANCE
            and _distance(
                _number(last, "participant_x"),
                _number(last, "participant_y"),
                spawn_x,
                spawn_y,
            )
            <= REMOTE_POSITION_TOLERANCE
        ):
            return last
        time.sleep(0.05)
    raise VerifyFailure(
        "dead participant did not converge on the observer at its host "
        f"respawn command: {last}"
    )


def _set_survival_hold(
    pipe_name: str,
    *,
    enabled: bool,
) -> dict[str, str]:
    values = parse_key_values(
        lua(
            pipe_name,
            SURVIVAL_HOLD.replace(
                "__ENABLED__",
                "true" if enabled else "false",
            ),
        )
    )
    if (
        values.get("registered") != "true"
        or values.get("enabled")
        != ("true" if enabled else "false")
    ):
        raise VerifyFailure(
            f"could not {'enable' if enabled else 'disable'} focused "
            f"survival hold on {pipe_name}: {values}"
        )
    return values


def assert_living_participant_unchanged(
    *,
    before: Mapping[str, Mapping[str, str]],
    after: Mapping[str, Mapping[str, str]],
    expected_wave: int,
) -> dict[str, Any]:
    before_owner = before["owner"]
    after_owner = after["owner"]
    before_observer = before["observer"]
    after_observer = after["observer"]
    before_hp = _number(before_owner, "hp")
    after_hp = _number(after_owner, "hp")
    before_mp = _number(before_owner, "mp")
    after_mp = _number(after_owner, "mp")
    if (
        not math.isfinite(before_hp)
        or not math.isfinite(after_hp)
        or before_hp <= VITAL_TOLERANCE
        or after_hp <= VITAL_TOLERANCE
    ):
        raise VerifyFailure(
            "living-participant boundary sample was not alive: "
            f"before={dict(before_owner)} after={dict(after_owner)}"
        )

    before_actor = _integer(before_owner, "actor_address")
    after_actor = _integer(after_owner, "actor_address")
    before_remote_actor = _integer(
        before_observer,
        "actor_address",
    )
    after_remote_actor = _integer(
        after_observer,
        "actor_address",
    )
    if (
        before_actor == 0
        or before_actor != after_actor
        or before_remote_actor == 0
        or before_remote_actor != after_remote_actor
    ):
        raise VerifyFailure(
            "living participant changed actor identity across the boundary: "
            f"before={before_actor}/{before_remote_actor} "
            f"after={after_actor}/{after_remote_actor}"
        )

    local_displacement = _distance(
        _number(before_owner, "x"),
        _number(before_owner, "y"),
        _number(after_owner, "x"),
        _number(after_owner, "y"),
    )
    remote_displacement = _distance(
        _number(before_observer, "x"),
        _number(before_observer, "y"),
        _number(after_observer, "x"),
        _number(after_observer, "y"),
    )
    if (
        not math.isfinite(local_displacement)
        or local_displacement > POSITION_TOLERANCE
        or not math.isfinite(remote_displacement)
        or remote_displacement > REMOTE_POSITION_TOLERANCE
    ):
        raise VerifyFailure(
            "living participant moved across the wave boundary: "
            f"local={local_displacement} remote={remote_displacement} "
            f"before={before} after={after}"
        )

    spawn_x, spawn_y = _spawn_from_owner(
        before_owner,
        label="living host",
    )
    before_spawn_separation = _distance(
        _number(before_owner, "x"),
        _number(before_owner, "y"),
        spawn_x,
        spawn_y,
    )
    after_spawn_separation = _distance(
        _number(after_owner, "x"),
        _number(after_owner, "y"),
        spawn_x,
        spawn_y,
    )
    if min(before_spawn_separation, after_spawn_separation) < (
        SPAWN_SEPARATION_MINIMUM
    ):
        raise VerifyFailure(
            "living participant was not kept away from the Arena spawn: "
            f"before={before_spawn_separation} after={after_spawn_separation}"
        )

    if (
        _integer(after_owner, "last_applied_respawn_epoch")
        <= _integer(before_owner, "last_applied_respawn_epoch")
        or _integer(after_owner, "last_applied_respawn_wave")
        != expected_wave
    ):
        raise VerifyFailure(
            "living participant did not acknowledge the completed-wave epoch"
        )
    for key in ("last_respawn_x", "last_respawn_y"):
        if abs(
            _number(after_owner, key)
            - _number(before_owner, key)
        ) > POSITION_TOLERANCE:
            raise VerifyFailure(
                f"living participant rewrote {key} across the boundary"
            )
    if (
        abs(after_hp - before_hp) > VITAL_TOLERANCE
        or not math.isfinite(before_mp)
        or not math.isfinite(after_mp)
        or abs(after_mp - before_mp) > VITAL_TOLERANCE
        or _integer(after_owner, "grid_cell_address")
        != _integer(before_owner, "grid_cell_address")
        or _integer(after_owner, "grid_member_flag") != 1
        or _integer(after_owner, "anim_drive_state")
        != _integer(before_owner, "anim_drive_state")
    ):
        raise VerifyFailure(
            "living participant resources, animation, or grid registration "
            f"changed across the boundary: before={before_owner} "
            f"after={after_owner}"
        )
    return {
        "local_displacement": local_displacement,
        "remote_displacement": remote_displacement,
        "before_spawn_separation": before_spawn_separation,
        "after_spawn_separation": after_spawn_separation,
        "actor_address": before_actor,
        "observer_actor_address": before_remote_actor,
    }


def assert_dead_participant_respawned_same_actor(
    *,
    before_death: Mapping[str, Mapping[str, str]],
    death_presentation: Mapping[str, Mapping[str, str]],
    after_respawn: Mapping[str, Mapping[str, str]],
) -> dict[str, Any]:
    before_owner = before_death["owner"]
    dead_owner = death_presentation["owner"]
    after_owner = after_respawn["owner"]
    before_observer = before_death["observer"]
    after_observer = after_respawn["observer"]
    owner_actors = {
        _integer(before_owner, "actor_address"),
        _integer(dead_owner, "actor_address"),
        _integer(after_owner, "actor_address"),
    }
    observer_actors = {
        _integer(before_observer, "actor_address"),
        _integer(after_observer, "actor_address"),
    }
    if 0 in owner_actors or len(owner_actors) != 1:
        raise VerifyFailure(
            "dead participant did not respawn on the same owner actor: "
            f"{owner_actors}"
        )
    if 0 in observer_actors or len(observer_actors) != 1:
        raise VerifyFailure(
            "dead participant did not retain observer actor identity: "
            f"{observer_actors}"
        )

    spawn_x = _number(after_owner, "last_respawn_x")
    spawn_y = _number(after_owner, "last_respawn_y")
    if (
        not math.isfinite(spawn_x)
        or not math.isfinite(spawn_y)
        or _integer(after_owner, "last_applied_respawn_epoch") <= 0
    ):
        raise VerifyFailure(
            f"dead participant did not expose its host respawn command: "
            f"{after_owner}"
        )
    death_distance = _distance(
        _number(dead_owner, "x"),
        _number(dead_owner, "y"),
        spawn_x,
        spawn_y,
    )
    owner_spawn_delta = _distance(
        _number(after_owner, "x"),
        _number(after_owner, "y"),
        spawn_x,
        spawn_y,
    )
    observer_spawn_delta = _distance(
        _number(after_observer, "x"),
        _number(after_observer, "y"),
        spawn_x,
        spawn_y,
    )
    if death_distance < SPAWN_SEPARATION_MINIMUM:
        raise VerifyFailure(
            "dead participant was not away from spawn before respawn"
        )
    if (
        owner_spawn_delta > POSITION_TOLERANCE
        or observer_spawn_delta > REMOTE_POSITION_TOLERANCE
        or _integer(after_owner, "grid_cell_address") == 0
        or _integer(after_owner, "grid_member_flag") != 1
    ):
        raise VerifyFailure(
            "dead participant did not converge at the live Arena spawn: "
            f"owner_delta={owner_spawn_delta} "
            f"observer_delta={observer_spawn_delta} "
            f"after={after_respawn}"
        )
    return {
        "owner_actor_address": next(iter(owner_actors)),
        "observer_actor_address": next(iter(observer_actors)),
        "death_distance_from_spawn": death_distance,
        "owner_spawn_delta": owner_spawn_delta,
        "observer_spawn_delta": observer_spawn_delta,
    }


def wave_two_samples_converged(
    samples: Mapping[str, Mapping[str, str]],
) -> bool:
    return (
        set(samples) == {"host", "client"}
        and all(
            _integer(values, "wave") == 2
            and _integer(values, "alive") > 0
            and values.get("phase")
            not in ("", "idle", "completed")
            for values in samples.values()
        )
    )


def _wait_for_wave_two_convergence(
    host_pipe: str,
    client_pipe: str,
    *,
    timeout: float = 20.0,
) -> dict[str, dict[str, str]]:
    deadline = time.monotonic() + timeout
    stable_since: float | None = None
    last: dict[str, dict[str, str]] = {}
    while time.monotonic() < deadline:
        last = {
            "host": parse_key_values(
                lua(host_pipe, FOCUSED_WAVE_STATE_PROBE, timeout=8.0)
            ),
            "client": parse_key_values(
                lua(client_pipe, FOCUSED_WAVE_STATE_PROBE, timeout=8.0)
            ),
        }
        if wave_two_samples_converged(last):
            if stable_since is None:
                stable_since = time.monotonic()
            elif time.monotonic() - stable_since >= 0.5:
                return last
        else:
            stable_since = None
        time.sleep(0.1)
    raise VerifyFailure(
        f"host and client did not converge into live wave 2: {last}"
    )


def _wait_for_wave_state(
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
            lua(pipe_name, FOCUSED_WAVE_STATE_PROBE, timeout=8.0)
        )
        if predicate(last):
            return last
        time.sleep(0.1)
    raise VerifyFailure(
        f"timed out waiting for {description}; last={last}"
    )


def _hold_wave_one_on_single_enemy(
    host_pipe: str,
    *,
    timeout: float = 10.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    attempts: list[dict[str, str]] = []
    last: dict[str, str] = {}
    held_actor = 0
    while time.monotonic() < deadline:
        last = parse_key_values(
            lua(host_pipe, death.WAVE_STATE_PROBE, timeout=8.0)
        )
        if _integer(last, "wave") != 1:
            raise VerifyFailure(
                "wave 1 advanced before its single-enemy hold was ready: "
                f"{last}"
            )
        if (
            _integer(last, "remaining_to_spawn") == 0
            and _integer(last, "alive") == 1
            and held_actor != 0
        ):
            return {
                "state": last,
                "held_actor": held_actor,
                "attempts": attempts,
            }
        held = parse_key_values(
            lua(host_pipe, HOLD_ONE_LIVE_WAVE_ENEMY, timeout=8.0)
        )
        attempts.append({**last, **held})
        held_actor = _integer(held, "held_actor")
        time.sleep(0.05)
    raise VerifyFailure(
        "wave 1 did not settle on one held stock enemy: "
        f"state={last} attempts={attempts[-5:]}"
    )


def _trigger_wave_one_completion(
    host_pipe: str,
    *,
    timeout: float = 15.0,
) -> list[dict[str, str]]:
    deadline = time.monotonic() + timeout
    attempts: list[dict[str, str]] = []
    while time.monotonic() < deadline:
        wave = parse_key_values(
            lua(host_pipe, death.WAVE_STATE_PROBE, timeout=8.0)
        )
        wave_index = _integer(wave, "wave")
        if wave_index == 1 and wave.get("phase") == "completed":
            return attempts
        if wave_index >= 2:
            if attempts:
                return attempts
            raise VerifyFailure(
                "wave 1 advanced before the controlled completion trigger"
            )
        killed = parse_key_values(
            lua(
                host_pipe,
                death.KILL_LIVE_WAVE_ENEMIES,
                timeout=8.0,
            )
        )
        attempts.append({**wave, **killed})
        time.sleep(0.1)
    raise VerifyFailure(
        "wave 1 did not complete after native enemy death triggers; "
        f"attempts={attempts[-5:]}"
    )


def _wait_for_run_loading_started(
    host_pipe: str,
    *,
    timeout: float = 20.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = parse_key_values(
            lua(
                host_pipe,
                """
local multiplayer = assert(sd.runtime.get_multiplayer_state())
local loading = multiplayer.run_loading_barrier or {}
local local_row = nil
for _, participant in ipairs(multiplayer.participants or {}) do
  if participant.kind == "LocalHuman" then
    local_row = participant
    break
  end
end
print("local_in_run=" ..
  tostring(local_row and local_row.in_run or false))
print("run_nonce=" ..
  tostring(tonumber(local_row and local_row.run_nonce) or 0))
print("active=" .. tostring(loading.active or false))
print("released=" .. tostring(loading.released or false))
""",
            )
        )
        if (
            last.get("local_in_run") == "true"
            and _integer(last, "run_nonce") > 0
            and last.get("active") == "true"
            and last.get("released") == "false"
        ):
            return last
        time.sleep(0.1)
    raise VerifyFailure(
        f"host run-loading barrier never exposed the wave-start window: {last}"
    )


def _start_match_when_ready(
    host_pipe: str,
    *,
    timeout: float = 20.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = parse_key_values(
            lua(
                host_pipe,
                """
local invoked, result = pcall(sd.hub.start_match)
print("invoked=" .. tostring(invoked))
print("queued=" .. tostring(invoked and result == true))
print("detail=" .. tostring(result))
""",
            )
        )
        if (
            last.get("invoked") == "true"
            and last.get("queued") == "true"
        ):
            return last
        time.sleep(0.1)
    raise VerifyFailure(
        f"host could not queue stock Start Match: {last}"
    )


def _queue_stock_wave_start(host_pipe: str) -> dict[str, str]:
    values = parse_key_values(
        lua(
            host_pipe,
            """
local invoked, result = pcall(sd.gameplay.start_waves)
print("invoked=" .. tostring(invoked))
print("queued=" .. tostring(invoked and result == true))
print("detail=" .. tostring(result))
""",
        )
    )
    if (
        values.get("invoked") != "true"
        or values.get("queued") != "true"
    ):
        raise VerifyFailure(
            f"host could not queue stock ArenaStartWaves: {values}"
        )
    return values


def _wait_for_solomon_materialized_during_run_loading(
    host_pipe: str,
    *,
    timeout: float = 5.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = parse_key_values(
            lua(
                host_pipe,
                """
local ok, state = pcall(sd.hub.get_solomon_dig_state)
print("ok=" .. tostring(ok))
print("valid=" .. tostring(ok and state and state.valid or false))
print("actor_address=" ..
  tostring(ok and state and state.actor_address or 0))
""",
            )
        )
        if (
            last.get("ok") == "true"
            and last.get("valid") == "true"
            and _integer(last, "actor_address") > 0
        ):
            return last
        time.sleep(0.05)
    raise VerifyFailure(
        f"stock Solomon actor did not materialize during loading: {last}"
    )


def _wait_for_run_loading_barrier(
    pipe_name: str,
    *,
    timeout: float = 20.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = parse_key_values(
            lua(
                pipe_name,
                """
local multiplayer = assert(sd.runtime.get_multiplayer_state())
local loading = multiplayer.run_loading_barrier or {}
local local_row = nil
for _, participant in ipairs(multiplayer.participants or {}) do
  if participant.kind == "LocalHuman" then
    local_row = participant
    break
  end
end
local run_nonce = tonumber(local_row and local_row.run_nonce) or 0
print("local_in_run=" ..
  tostring(local_row and local_row.in_run or false))
print("run_nonce=" .. tostring(run_nonce))
print("active=" .. tostring(loading.active or false))
print("released=" .. tostring(loading.released or false))
print("release_nonce=" ..
  tostring(tonumber(loading.release_nonce) or 0))
print("reason=" .. tostring(loading.release_reason or ""))
""",
            )
        )
        run_nonce = _integer(last, "run_nonce")
        if (
            last.get("local_in_run") == "true"
            and run_nonce > 0
            and last.get("active") == "true"
            and last.get("released") == "true"
            and _integer(last, "release_nonce") == run_nonce
            and last.get("reason") == "all-participants-ready"
        ):
            return last
        time.sleep(0.1)
    raise VerifyFailure(
        f"run-loading barrier did not release on {pipe_name}: {last}"
    )


def run_live_verification(
    *,
    instance_prefix: str,
    game_directory: Path | None,
    launcher_path: Path | None,
    runtime_root: Path | None,
) -> dict[str, Any]:
    fixture_manifest = _fixture_manifest()
    runtime_parent = ROOT / "runtime"
    runtime_parent.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "ok": False,
        "source_sha": _source_sha(),
        "instance_prefix": instance_prefix,
        "ports": [HOST_PORT, CLIENT_PORT],
        "save_fixture_sha256": fixture_manifest,
    }
    with tempfile.TemporaryDirectory(
        prefix=f"{instance_prefix}-save-",
        dir=runtime_parent,
    ) as temporary_root_text:
        temporary_root = Path(temporary_root_text)
        host_savegames = temporary_root / "host"
        client_savegames = temporary_root / "client"
        _copy_fixture_to_save_root(host_savegames)
        _copy_fixture_to_save_root(client_savegames)
        result["save_staging"] = {
            "mode": "copied_existing_wizard_per_peer",
            "host_root": str(host_savegames),
            "client_root": str(client_savegames),
        }

        launch = launch_pair(
            preset="map_create_air_mind_hub",
            host_preset="map_create_air_mind_hub",
            client_preset="map_create_water_body_hub",
            temporary_host_profile=False,
            fresh_install=False,
            god_mode=False,
            tile_windows=False,
            test_wave_override=None,
            third_player=False,
            allow_focus_steal=False,
            kill_existing=False,
            instance_prefix=instance_prefix,
            host_port=HOST_PORT,
            client_port=CLIENT_PORT,
            third_port=CLIENT_PORT,
            game_directory=game_directory,
            launcher_path=launcher_path,
            runtime_root=runtime_root,
            exact_mod_id=death.ACCEPTANCE_MOD_ID,
            quick_start=True,
            no_lua_automation=True,
            host_savegames_root=host_savegames,
            client_savegames_root=client_savegames,
            enable_audio=False,
        )
        process_ids = game_process_ids(launch)
        result["launch"] = launch
        result["process_ids"] = process_ids
        if len(process_ids) != 2:
            stop_game_processes(process_ids)
            raise VerifyFailure(
                "isolated staged-save pair did not report exactly two "
                f"process IDs: {launch}"
            )

        host_pipe = str(launch["hostLuaPipe"])
        client_pipe = str(launch["clientLuaPipe"])
        pipe_names = [host_pipe, client_pipe]
        try:
            if launch.get("audioDisabled") is not True:
                raise VerifyFailure(
                    f"targeted pair did not disable audio: {launch}"
                )
            if launch.get("noLuaAutomation") is not True:
                raise VerifyFailure(
                    "targeted pair did not use native quick-start"
                )
            if launch.get("quickStartEnabled") is not True:
                raise VerifyFailure(
                    f"targeted pair did not enable quick-start: {launch}"
                )

            result["bots_disabled"] = death._disable_bots(pipe_names)
            result["survival_hold_enabled"] = {
                "host": _set_survival_hold(
                    host_pipe,
                    enabled=True,
                ),
                "client": _set_survival_hold(
                    client_pipe,
                    enabled=True,
                ),
            }
            result["run_generation_seed"] = (
                _set_run_generation_seed(host_pipe)
            )
            result["start_match_request"] = (
                _start_match_when_ready(host_pipe)
            )
            result["run_loading_started"] = (
                _wait_for_run_loading_started(host_pipe)
            )
            result["solomon_materialized"] = (
                _wait_for_solomon_materialized_during_run_loading(
                    host_pipe
                )
            )
            for pipe_name in pipe_names:
                wait_for_scene(pipe_name, "testrun", 45.0)
            result["host_placement"] = (
                _preplace_participant_away_from_spawn(
                    pipe_name=host_pipe,
                    label="host",
                    target=HOST_TEST_POSITION,
                    heading=90.0,
                )
            )
            result["client_placement"] = (
                _preplace_participant_away_from_spawn(
                    pipe_name=client_pipe,
                    label="client",
                    target=CLIENT_TEST_POSITION,
                    heading=270.0,
                )
            )
            result["run_loading_barrier"] = {
                "host": _wait_for_run_loading_barrier(host_pipe),
                "client": _wait_for_run_loading_barrier(client_pipe),
            }
            result["relationships"] = {
                "host_observes_client": wait_for_remote(
                    host_pipe,
                    CLIENT_ID,
                    CLIENT_NAME,
                    "testrun",
                    45.0,
                ),
                "client_observes_host": wait_for_remote(
                    client_pipe,
                    HOST_ID,
                    HOST_NAME,
                    "testrun",
                    45.0,
                ),
            }
            result["host_placement"]["views"] = (
                _confirm_position_views(
                    owner_pipe=host_pipe,
                    observer_pipe=client_pipe,
                    participant_id=HOST_ID,
                    label="host",
                )
            )
            result["client_placement"]["views"] = (
                _confirm_position_views(
                    owner_pipe=client_pipe,
                    observer_pipe=host_pipe,
                    participant_id=CLIENT_ID,
                    label="client",
                )
            )
            result["stock_wave_start_request"] = (
                _queue_stock_wave_start(host_pipe)
            )
            result["wave_one_active"] = {
                "host": _wait_for_wave_state(
                    host_pipe,
                    lambda values: (
                        _integer(values, "wave") == 1
                        and _integer(values, "alive") > 0
                        and values.get("phase")
                        not in ("", "idle", "completed")
                    ),
                    timeout=10.0,
                    description="host live stock wave 1",
                ),
                "client": _wait_for_wave_state(
                    client_pipe,
                    lambda values: (
                        _integer(values, "wave") == 1
                        and _integer(values, "alive") > 0
                        and values.get("phase")
                        not in ("", "idle", "completed")
                    ),
                    timeout=10.0,
                    description="client live stock wave 1",
                ),
            }
            result["wave_one_single_enemy_hold"] = (
                _hold_wave_one_on_single_enemy(
                    host_pipe,
                )
            )
            client_before_death = _query_views(
                owner_pipe=client_pipe,
                observer_pipe=host_pipe,
                participant_id=CLIENT_ID,
            )

            result["client_survival_hold_disabled"] = (
                _set_survival_hold(
                    client_pipe,
                    enabled=False,
                )
            )
            result["client_lethal_precondition"] = (
                death._establish_local_lethal_precondition(
                    client_pipe,
                    "client",
                )
            )
            death_started_at = time.monotonic()
            result["client_lethal_hit"] = (
                death._apply_authoritative_client_lethal_hit(
                    host_pipe
                )
            )
            client_death_owner = death._wait_for_values(
                client_pipe,
                death.death_presentation_state_matches,
                timeout=5.0,
                description="focused client death presentation",
            )
            client_death_views = {
                "owner": client_death_owner,
                "observer": death.query_remote_death_state(
                    host_pipe,
                    CLIENT_ID,
                ),
            }
            result["client_death_presentation"] = (
                client_death_views
            )

            living_before = _query_views(
                owner_pipe=host_pipe,
                observer_pipe=client_pipe,
                participant_id=HOST_ID,
            )
            previous_host_epoch = _integer(
                living_before["owner"],
                "last_applied_respawn_epoch",
            )
            previous_client_epoch = _integer(
                client_death_owner,
                "last_applied_respawn_epoch",
            )
            result["boundary_before"] = {
                "living_host": living_before,
                "dead_client": client_death_views,
            }

            result["wave_one_enemy_death_triggers"] = (
                _trigger_wave_one_completion(
                    host_pipe,
                )
            )
            host_after_owner = _wait_for_local_respawn_epoch(
                host_pipe,
                previous_epoch=previous_host_epoch,
                expected_wave=1,
            )
            client_after_owner = death._wait_for_values(
                client_pipe,
                lambda values: death.respawn_state_matches(
                    values,
                    previous_epoch=previous_client_epoch,
                    expected_wave=1,
                ),
                timeout=8.0,
                description="dead client wave-1 respawn",
            )
            living_after = {
                "owner": host_after_owner,
                "observer": death.query_remote_death_state(
                    client_pipe,
                    HOST_ID,
                ),
            }
            dead_after = {
                "owner": client_after_owner,
                "observer": _wait_for_remote_respawn_convergence(
                    host_pipe,
                    participant_id=CLIENT_ID,
                    owner_state=client_after_owner,
                ),
            }
            result["boundary_after"] = {
                "living_host": living_after,
                "dead_client": dead_after,
            }
            result["wave_completed_after_death_seconds"] = (
                time.monotonic() - death_started_at
            )
            result["living_host_unchanged"] = (
                assert_living_participant_unchanged(
                    before=living_before,
                    after=living_after,
                    expected_wave=1,
                )
            )
            result["dead_client_same_actor_respawn"] = (
                assert_dead_participant_respawned_same_actor(
                    before_death=client_before_death,
                    death_presentation=client_death_views,
                    after_respawn=dead_after,
                )
            )
            result["wave_two_convergence"] = (
                _wait_for_wave_two_convergence(
                    host_pipe,
                    client_pipe,
                )
            )
            result["ok"] = True
            return result
        finally:
            stop_game_processes(process_ids)


def _default_instance_prefix() -> str:
    return (
        f"fb25-wb-{os.getpid():x}-"
        f"{time.time_ns() & 0xFFFF:04x}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--instance-prefix",
        default="",
        help="Unique fb25 launcher instance prefix.",
    )
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument(
        "--game-dir",
        type=Path,
        default=None,
        help="Retail game directory override.",
    )
    parser.add_argument(
        "--launcher-path",
        type=Path,
        default=None,
        help="Built launcher executable override.",
    )
    parser.add_argument(
        "--runtime-root",
        type=Path,
        default=None,
        help="Isolated launcher runtime root override.",
    )
    args = parser.parse_args()

    instance_prefix = (
        args.instance_prefix or _default_instance_prefix()
    )
    result: dict[str, Any] = {
        "ok": False,
        "instance_prefix": instance_prefix,
        "ports": [HOST_PORT, CLIENT_PORT],
    }
    exit_code = 0
    try:
        result = run_live_verification(
            instance_prefix=instance_prefix,
            game_directory=args.game_dir,
            launcher_path=args.launcher_path,
            runtime_root=args.runtime_root,
        )
    except Exception as exc:  # noqa: BLE001 - persist exact live failure.
        result["error"] = str(exc)
        result["error_type"] = type(exc).__name__
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
