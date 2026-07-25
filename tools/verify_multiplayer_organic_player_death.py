#!/usr/bin/env python3
"""Verify player death from stock enemy damage in connected multiplayer."""

from __future__ import annotations

import argparse
import json
import math
import os
import time
import traceback
import uuid
from pathlib import Path
from typing import Any

from multiplayer_frame_capture import capture_game_backbuffer
from multiplayer_log_probe import log_position
from multiplayer_natural_defense_harness import (
    ARM_ENEMY_ARENA_LUA,
    SET_ENEMY_MODE_LUA,
)
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
    select_available_windows_udp_ports,
    start_testrun,
    stop_game_processes,
    wait_for_remote,
    wait_for_scene,
)
from verify_multiplayer_death_spectator_respawn import (
    _arm_death_traces,
    _disarm_death_traces,
    query_remote_death_state,
    query_spectator_state,
)
from verify_player_health_death_sync import set_local_player_vitals
from verify_real_input_spell_cast_sync import (
    Direction,
    clear_gameplay_mouse_left,
    queue_gameplay_mouse_left,
    wait_for_source_cast,
)


OUTPUT = ROOT / "runtime" / "multiplayer_organic_player_death.json"
SCREENSHOT_ROOT = ROOT / "runtime" / "multiplayer_organic_player_death"
ACCEPTANCE_MOD_ID = "sample.lua.ui_sandbox_lab"
SURVIVOR_HP = 5000.0
VICTIM_ARMING_HP = 0.1
VICTIM_MAX_HP = 50.0
CAST_HOLD_FRAMES = 1200
PRESENTATION_PHASE_SYNC_TOLERANCE_TICKS = 12.0

WAVE_FIXTURES = {
    "melee": (
        ROOT / "tests" / "fixtures" / "waves"
        / "organic_death_melee_test.txt"
    ),
    "projectile": (
        ROOT / "tests" / "fixtures" / "waves"
        / "organic_death_projectile_test.txt"
    ),
    "poison": (
        ROOT / "tests" / "fixtures" / "waves"
        / "organic_death_poison_test.txt"
    ),
}


class OrganicDeathFailure(VerifyFailure):
    """Live verifier failure that retains the evidence captured so far."""

    def __init__(self, message: str, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


ARM_DAMAGE_PROBE = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
_G.__sdmod_organic_death_damage_probe = {
  events = {},
  limit = 128,
}
if not _G.__sdmod_organic_death_damage_probe_registered then
  sd.events.filter("damage.taken", function(event)
    local probe = _G.__sdmod_organic_death_damage_probe
    if type(probe) == "table" and #probe.events < probe.limit then
      probe.events[#probe.events + 1] = {
        target = tonumber(event.target_participant_id) or 0,
        source = tonumber(event.source_participant_id) or 0,
        target_actor = tonumber(event.target_actor_address) or 0,
        source_actor = tonumber(event.source_actor_address) or 0,
        flags = tonumber(event.flags) or 0,
        projectile = tonumber(event.projectile_damage) or 0,
        magic = tonumber(event.magic_damage) or 0,
        total = tonumber(event.total_damage) or 0,
      }
    end
    return nil
  end)
  _G.__sdmod_organic_death_damage_probe_registered = true
end
emit("registered", _G.__sdmod_organic_death_damage_probe_registered)
emit("count", #_G.__sdmod_organic_death_damage_probe.events)
"""


QUERY_DAMAGE_PROBE = r"""
local probe = _G.__sdmod_organic_death_damage_probe
if type(probe) ~= "table" then error("organic death damage probe unavailable") end
for index, event in ipairs(probe.events or {}) do
  print(table.concat({
    "D",
    tostring(index),
    tostring(event.target or 0),
    tostring(event.source or 0),
    tostring(event.target_actor or 0),
    tostring(event.source_actor or 0),
    tostring(event.flags or 0),
    string.format("%.6f", event.projectile or 0),
    string.format("%.6f", event.magic or 0),
    string.format("%.6f", event.total or 0),
  }, "|"))
end
"""


LIVE_ENEMY_PROBE = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local selected = nil
local count = 0
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  if actor.tracked_enemy and not actor.dead and
      (tonumber(actor.hp) or 0) > 0 then
    count = count + 1
    if selected == nil then selected = actor end
  end
end
emit("count", count)
emit("actor_address", selected and selected.actor_address or 0)
emit("object_type_id", selected and selected.object_type_id or 0)
emit("x", selected and selected.x or 0)
emit("y", selected and selected.y or 0)
emit("hp", selected and selected.hp or 0)
"""


KILL_LIVE_WAVE_ENEMIES = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local attempted = 0
local accepted = 0
local hp_offset = sd.debug.layout_offset("enemy_current_hp")
local max_hp_offset = sd.debug.layout_offset("enemy_max_hp")
local progression_offset =
  sd.debug.layout_offset("actor_progression_runtime_state")
local progression_hp_offset = sd.debug.layout_offset("progression_hp")
local progression_max_hp_offset =
  sd.debug.layout_offset("progression_max_hp")
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  if actor.tracked_enemy and not actor.dead and
      (tonumber(actor.hp) or 0) > 0 then
    attempted = attempted + 1
    local address = tonumber(actor.actor_address) or 0
    local max_hp = tonumber(actor.max_hp) or 1
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
    if sd.world.trigger_enemy_death(actor.actor_address) then
      accepted = accepted + 1
    end
  end
end
emit("attempted", attempted)
emit("accepted", accepted)
"""


WAVE_STATE_PROBE = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local state = assert(sd.waves.get_state())
emit("phase", state and state.phase or "")
emit("wave", state and state.wave or 0)
emit("alive", state and state.alive or 0)
"""


def _default_instance_prefix() -> str:
    return f"orgd-{os.getpid():x}-{uuid.uuid4().hex[:4]}"


def _start_testrun_when_ready(host_pipe: str, timeout: float = 30.0) -> None:
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
        f"host testrun request never reached spawn readiness: {last_error}"
    )


def _disable_companion_bots(pipe_names: list[str]) -> None:
    code = (
        "lua_bots_disable_tick = true; sd.bots.clear(); "
        "return tostring(sd.bots.get_count())"
    )
    for pipe_name in pipe_names:
        if lua(pipe_name, code).strip() != "0":
            raise VerifyFailure(
                f"failed to disable companion bots on {pipe_name}"
            )


def _start_waves(host_pipe: str) -> dict[str, str]:
    values = parse_key_values(
        lua(
            host_pipe,
            "print('ok=' .. tostring(sd.gameplay.start_waves()))",
        )
    )
    if values.get("ok") != "true":
        raise VerifyFailure(f"host could not start organic combat: {values}")
    return values


def _wait_for_enemy(host_pipe: str, timeout: float = 20.0) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = parse_key_values(lua(host_pipe, LIVE_ENEMY_PROBE))
        if int(float(last.get("count", "0"))) >= 1:
            return last
        time.sleep(0.1)
    raise VerifyFailure(f"stock wave did not produce a live enemy: {last}")


def _arm_enemy_arena(
    host_pipe: str,
    target_x: float,
    target_y: float,
) -> dict[str, str]:
    code = (
        ARM_ENEMY_ARENA_LUA
        .replace("__TARGET_X__", f"{target_x:.6f}")
        .replace("__TARGET_Y__", f"{target_y:.6f}")
    )
    values = parse_key_values(lua(host_pipe, code, timeout=10.0))
    if values.get("ok") != "true":
        raise VerifyFailure(f"failed to arm organic enemy arena: {values}")
    return values


def _set_enemy_attack(
    host_pipe: str,
    *,
    target_x: float,
    target_y: float,
    target_participant_id: int,
    enemy_actor_address: int,
    attack_distance: float,
    timeout: float = 10.0,
) -> dict[str, str]:
    code = (
        SET_ENEMY_MODE_LUA
        .replace("__MODE__", "attack")
        .replace("__TARGET_X__", f"{target_x:.6f}")
        .replace("__TARGET_Y__", f"{target_y:.6f}")
        .replace("__ATTACK_DISTANCE__", f"{attack_distance:.6f}")
        .replace("__ENEMY_ACTOR_ADDRESS__", str(enemy_actor_address))
        .replace("__TARGET_PARTICIPANT_ID__", str(target_participant_id))
    )
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = parse_key_values(lua(host_pipe, code, timeout=10.0))
        if (
            last.get("ok") == "true"
            and int(last.get("count", "0")) >= 1
            and int(last.get("target_actor", "0")) != 0
        ):
            return last
        time.sleep(0.1)
    raise VerifyFailure(f"organic enemy could not target victim: {last}")


def _parse_damage_probe(text: str) -> list[dict[str, int | float]]:
    events: list[dict[str, int | float]] = []
    for line in text.splitlines():
        if not line.startswith("D|"):
            continue
        parts = line.split("|")
        if len(parts) != 10:
            raise VerifyFailure(f"malformed damage probe record: {line!r}")
        events.append(
            {
                "index": int(parts[1]),
                "target_participant_id": int(parts[2]),
                "source_participant_id": int(parts[3]),
                "target_actor_address": int(parts[4]),
                "source_actor_address": int(parts[5]),
                "flags": int(parts[6]),
                "projectile_damage": float(parts[7]),
                "magic_damage": float(parts[8]),
                "total_damage": float(parts[9]),
            }
        )
    return events


def _small_state(values: dict[str, str]) -> dict[str, str]:
    keys = (
        "active",
        "phase",
        "hp",
        "max_hp",
        "death_drive_state",
        "death_presentation_ticks",
        "terminal_pending",
        "terminal_countdown",
        "red_effect_active",
        "death_transition_hits",
        "staff_drop_hits",
        "presentation_active",
        "presentation_flags",
        "authoritative_death_presentation_ticks",
        "anim_drive_state",
        "grid_member_flag",
        "render_sort_bias",
        "x",
        "y",
    )
    return {key: values[key] for key in keys if key in values}


def _sample_lifecycle(
    *,
    victim_pipe: str,
    observer_pipe: str,
    victim_id: int,
    timeout: float,
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    deadline = time.monotonic() + timeout
    started = time.monotonic()
    samples: list[dict[str, Any]] = []
    milestones: dict[str, float] = {}
    while time.monotonic() < deadline:
        elapsed = time.monotonic() - started
        owner = query_spectator_state(victim_pipe)
        observer = query_remote_death_state(observer_pipe, victim_id)
        sample = {
            "elapsed_seconds": round(elapsed, 6),
            "owner": _small_state(owner),
            "observer": _small_state(observer),
        }
        samples.append(sample)
        owner_hp = float(owner.get("hp", "0"))
        if owner_hp <= 0.0:
            milestones.setdefault("hp_zero_seconds", elapsed)
        if float(observer.get("hp", "0")) <= 0.0:
            milestones.setdefault("observer_hp_zero_seconds", elapsed)
        if int(observer.get("death_drive_state", "0")) != 0:
            milestones.setdefault("observer_death_drive_seconds", elapsed)
        if int(owner.get("death_drive_state", "0")) != 0:
            milestones.setdefault("owner_death_drive_seconds", elapsed)
        if owner.get("phase") == "DeathPresentation":
            milestones.setdefault("presentation_seconds", elapsed)
        if (
            observer.get("presentation_active") == "true"
            and "observer_presentation_seconds" not in milestones
        ):
            milestones["observer_presentation_seconds"] = elapsed
            milestones["owner_presentation_tick_at_observer_start"] = float(
                int(owner.get("death_presentation_ticks", "0"))
            )
            milestones["observer_presentation_tick_at_start"] = float(
                int(observer.get("death_presentation_ticks", "0"))
            )
        if int(owner.get("death_transition_hits", "0")) > 0:
            milestones.setdefault("death_transition_seconds", elapsed)
        if int(owner.get("staff_drop_hits", "0")) > 0:
            milestones.setdefault("staff_drop_seconds", elapsed)
        if (
            owner.get("red_effect_active") == "true"
            and observer.get("red_effect_active") == "true"
        ):
            milestones.setdefault("red_effect_seconds", elapsed)
        if owner.get("phase") == "Spectating":
            milestones.setdefault("spectator_seconds", elapsed)
        if (
            "spectator_seconds" in milestones
            and owner.get("red_effect_active") == "false"
            and observer.get("red_effect_active") == "false"
        ):
            milestones.setdefault("red_cleared_seconds", elapsed)
            return samples, milestones
        time.sleep(0.02)
    return samples, milestones


def _assert_lifecycle(
    lifecycle: list[dict[str, Any]],
    milestones: dict[str, float],
) -> float:
    required = (
        "hp_zero_seconds",
        "presentation_seconds",
        "observer_presentation_seconds",
        "owner_presentation_tick_at_observer_start",
        "observer_presentation_tick_at_start",
        "death_transition_seconds",
        "staff_drop_seconds",
        "red_effect_seconds",
        "spectator_seconds",
        "red_cleared_seconds",
    )
    missing = [key for key in required if key not in milestones]
    if missing:
        raise VerifyFailure(
            "organic player death lifecycle diverged before "
            f"{missing}; milestones={milestones}"
        )
    grace_seconds = (
        milestones["spectator_seconds"]
        - milestones["presentation_seconds"]
    )
    if grace_seconds < 2.75 or grace_seconds > 4.25:
        raise VerifyFailure(
            "organic death presentation did not hold for three seconds: "
            f"{grace_seconds:.3f}s milestones={milestones}"
        )
    if (
        milestones.get("observer_death_drive_seconds", math.inf)
        + 0.08
        < milestones["presentation_seconds"]
    ):
        raise VerifyFailure(
            "observer entered the death animation before the owner "
            f"started death presentation: {milestones}"
        )
    presentation_delivery_skew = abs(
        milestones["observer_presentation_seconds"]
        - milestones["presentation_seconds"]
    )
    presentation_phase_skew = abs(
        milestones["observer_presentation_tick_at_start"]
        - milestones["owner_presentation_tick_at_observer_start"]
    )
    milestones["presentation_delivery_skew_seconds"] = (
        presentation_delivery_skew
    )
    milestones["presentation_phase_skew_ticks"] = presentation_phase_skew
    # A stalled peer cannot render while its app thread is stopped. The
    # replicated bounded clock and packet-age extrapolation are what keep the
    # first frame it can render aligned with the owner, so assert that native
    # phase directly instead of packet-observation wall time.
    if presentation_phase_skew > PRESENTATION_PHASE_SYNC_TOLERANCE_TICKS:
        raise VerifyFailure(
            "owner and observer death presentation phase diverged by "
            f"{presentation_phase_skew:.0f} ticks: {milestones}"
        )

    final_owner = lifecycle[-1]["owner"]
    final_observer = lifecycle[-1]["observer"]
    if int(final_owner.get("death_transition_hits", "0")) != 1:
        raise VerifyFailure(
            "owner organic death transition trace was not 1: "
            f"{final_owner}"
        )
    if int(final_owner.get("staff_drop_hits", "0")) != 1:
        raise VerifyFailure(
            f"owner organic staff drop trace was not 1: {final_owner}"
        )
    if int(final_observer.get("death_transition_hits", "0")) != 0:
        raise VerifyFailure(
            "observer executed owner-only organic death transition: "
            f"{final_observer}"
        )
    if int(final_observer.get("staff_drop_hits", "0")) != 0:
        raise VerifyFailure(
            "observer executed owner-only organic staff drop: "
            f"{final_observer}"
        )
    return grace_seconds


def _wait_for_respawn(
    victim_pipe: str,
    *,
    timeout: float = 10.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = query_spectator_state(victim_pipe)
        if (
            last.get("active") == "false"
            and float(last.get("hp", "0")) > 0.0
            and int(last.get("death_drive_state", "0")) == 0
        ):
            return last
        time.sleep(0.05)
    raise VerifyFailure(f"organic victim did not respawn cleanly: {last}")


def _finish_wave(host_pipe: str, timeout: float = 15.0) -> list[dict[str, str]]:
    deadline = time.monotonic() + timeout
    attempts: list[dict[str, str]] = []
    while time.monotonic() < deadline:
        wave = parse_key_values(lua(host_pipe, WAVE_STATE_PROBE))
        if wave.get("phase") == "completed":
            return attempts
        attempts.append(
            parse_key_values(lua(host_pipe, KILL_LIVE_WAVE_ENEMIES))
        )
        time.sleep(0.1)
    raise VerifyFailure(f"organic wave did not complete: {attempts[-5:]}")


def run_live_verification(
    *,
    instance_prefix: str,
    ports: list[int],
    game_directory: Path | None,
    launcher_path: Path | None,
    kill_type: str,
    victim_role: str,
    activity: str,
) -> dict[str, Any]:
    fixture = WAVE_FIXTURES[kill_type]
    launch = launch_pair(
        host_preset="map_create_fire_mind_hub",
        client_preset="map_create_air_mind_hub",
        temporary_host_profile=True,
        tile_windows=False,
        test_blank_boneyard=True,
        test_wave_override=fixture,
        kill_existing=False,
        instance_prefix=instance_prefix,
        host_port=ports[0],
        client_port=ports[1],
        game_directory=game_directory,
        launcher_path=launcher_path,
        exact_mod_id=ACCEPTANCE_MOD_ID,
    )
    process_ids = game_process_ids(launch)
    if len(process_ids) != 2:
        stop_game_processes(process_ids)
        raise VerifyFailure(
            f"isolated pair did not report two process IDs: {launch}"
        )
    host_pipe = str(launch["hostLuaPipe"])
    client_pipe = str(launch["clientLuaPipe"])
    pipes = [host_pipe, client_pipe]
    if victim_role == "host":
        victim_pipe = host_pipe
        observer_pipe = client_pipe
        victim_id = HOST_ID
    else:
        victim_pipe = client_pipe
        observer_pipe = host_pipe
        victim_id = CLIENT_ID

    result: dict[str, Any] = {
        "launch": launch,
        "process_ids": process_ids,
        "instance_prefix": instance_prefix,
        "ports": ports,
        "kill_type": kill_type,
        "victim_role": victim_role,
        "activity": activity,
        "wave_fixture": str(fixture),
    }
    try:
        _disable_companion_bots(pipes)
        _start_testrun_when_ready(host_pipe)
        wait_for_scene(host_pipe, "testrun", 45.0)
        host_safe = set_local_player_vitals(
            host_pipe,
            SURVIVOR_HP,
            SURVIVOR_HP,
        )
        wait_for_scene(client_pipe, "testrun", 45.0)
        client_safe = set_local_player_vitals(
            client_pipe,
            SURVIVOR_HP,
            SURVIVOR_HP,
        )
        result["vitals_safe"] = {
            "host": host_safe,
            "client": client_safe,
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
        result["alive_precondition"] = {
            "host": _small_state(query_spectator_state(host_pipe)),
            "client": _small_state(query_spectator_state(client_pipe)),
        }
        for role, state in result["alive_precondition"].items():
            if (
                state.get("active") != "false"
                or float(state.get("hp", "0")) <= 0.0
                or int(state.get("death_drive_state", "0")) != 0
            ):
                raise VerifyFailure(
                    f"{role} was already dead before organic trial: {state}"
                )
        result["death_traces_armed"] = _arm_death_traces(pipes)
        result["damage_probes_armed"] = {}
        for role, pipe_name in (("host", host_pipe), ("client", client_pipe)):
            armed = parse_key_values(lua(pipe_name, ARM_DAMAGE_PROBE))
            if armed.get("registered") != "true":
                raise VerifyFailure(
                    f"{role} organic damage probe failed to arm: {armed}"
                )
            result["damage_probes_armed"][role] = armed

        result["wave_start"] = _start_waves(host_pipe)
        enemy = _wait_for_enemy(host_pipe)
        result["enemy"] = enemy
        victim_before = query_spectator_state(victim_pipe)
        victim_x = float(victim_before["x"])
        victim_y = float(victim_before["y"])
        result["victim_before_attack"] = _small_state(victim_before)
        result["enemy_arena"] = _arm_enemy_arena(
            host_pipe,
            victim_x,
            victim_y,
        )
        if activity == "casting":
            victim_log = (
                ROOT
                / "runtime"
                / "instances"
                / f"{instance_prefix}-{victim_role}"
                / "stage"
                / ".sdmod"
                / "logs"
                / "solomondarkmodloader.log"
            )
            direction = Direction(
                name=f"{victim_role}_organic_death_cast",
                source_id=victim_id,
                source_name=HOST_NAME if victim_role == "host" else CLIENT_NAME,
                source_pipe=victim_pipe,
                source_log=victim_log,
                source_pid=int(launch[f"{victim_role}ProcessId"]),
                receiver_pipe=observer_pipe,
                receiver_log=(
                    ROOT
                    / "runtime"
                    / "instances"
                    / f"{instance_prefix}-"
                    f"{'client' if victim_role == 'host' else 'host'}"
                    / "stage"
                    / ".sdmod"
                    / "logs"
                    / "solomondarkmodloader.log"
                ),
            )
            source_log_offset = log_position(victim_log)
            result["cast_input"] = queue_gameplay_mouse_left(
                direction,
                CAST_HOLD_FRAMES,
            )
            _, phase_counts, native_hook_count = wait_for_source_cast(
                direction,
                source_log_offset,
                {"pressed": 1, "held": 1},
                3.0,
            )
            result["cast_started"] = {
                "phase_counts": phase_counts,
                "native_hook_count": native_hook_count,
            }
        else:
            direction = None
            result["idle_input"] = parse_key_values(
                lua(
                    victim_pipe,
                    "print('cleared=' .. "
                    "tostring(sd.input.clear_mouse_left()))",
                )
            )

        result["victim_armed"] = set_local_player_vitals(
            victim_pipe,
            VICTIM_ARMING_HP,
            VICTIM_MAX_HP,
        )
        result["enemy_attack"] = _set_enemy_attack(
            host_pipe,
            target_x=victim_x,
            target_y=victim_y,
            target_participant_id=(
                0 if victim_role == "host" else victim_id
            ),
            enemy_actor_address=(
                int(enemy["actor_address"])
                if victim_role == "host"
                else 0
            ),
            attack_distance=(
                64.0 if kill_type == "melee" else 240.0
            ),
        )
        lifecycle, milestones = _sample_lifecycle(
            victim_pipe=victim_pipe,
            observer_pipe=observer_pipe,
            victim_id=victim_id,
            timeout=18.0,
        )
        result["lifecycle_samples"] = lifecycle
        result["milestones"] = milestones
        result["damage_events"] = {
            "host": _parse_damage_probe(lua(host_pipe, QUERY_DAMAGE_PROBE)),
            "client": _parse_damage_probe(lua(client_pipe, QUERY_DAMAGE_PROBE)),
        }
        if direction is not None:
            try:
                result["cast_clear"] = clear_gameplay_mouse_left(direction)
            except VerifyFailure as exc:
                result["cast_clear_error"] = str(exc)

        result["grace_seconds"] = _assert_lifecycle(
            lifecycle,
            milestones,
        )

        screenshot_directory = SCREENSHOT_ROOT / instance_prefix
        result["screenshots"] = {
            "victim_spectator": capture_game_backbuffer(
                victim_pipe,
                screenshot_directory / "victim-spectator.png",
            ),
            "observer_death_location": capture_game_backbuffer(
                observer_pipe,
                screenshot_directory / "observer-death-location.png",
            ),
        }
        result["wave_finish"] = _finish_wave(host_pipe)
        result["respawned"] = _wait_for_respawn(victim_pipe)
        result["ok"] = True
        return result
    except Exception as exc:
        result["error"] = str(exc)
        result["error_type"] = type(exc).__name__
        raise OrganicDeathFailure(str(exc), result) from exc
    finally:
        _disarm_death_traces(pipes)
        stop_game_processes(process_ids)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--instance-prefix",
        default="",
        help="Unique launcher instance prefix (generated by default).",
    )
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument(
        "--game-dir",
        type=Path,
        default=None,
        help="Retail game directory override for isolated worktrees.",
    )
    parser.add_argument(
        "--launcher-path",
        type=Path,
        default=None,
        help="Launcher build to stage.",
    )
    parser.add_argument(
        "--kill-type",
        choices=tuple(WAVE_FIXTURES),
        default="melee",
    )
    parser.add_argument(
        "--victim",
        choices=("host", "client"),
        default="host",
    )
    parser.add_argument(
        "--activity",
        choices=("idle", "casting"),
        default="idle",
    )
    parser.add_argument("--host-port", type=int, default=None)
    parser.add_argument("--client-port", type=int, default=None)
    args = parser.parse_args()

    if (args.host_port is None) != (args.client_port is None):
        parser.error("--host-port and --client-port must be supplied together")
    ports = (
        [args.host_port, args.client_port]
        if args.host_port is not None
        else select_available_windows_udp_ports(2)
    )
    instance_prefix = args.instance_prefix or _default_instance_prefix()
    result: dict[str, Any] = {"ok": False}
    exit_code = 1
    try:
        result = run_live_verification(
            instance_prefix=instance_prefix,
            ports=[int(port) for port in ports],
            game_directory=args.game_dir,
            launcher_path=args.launcher_path,
            kill_type=args.kill_type,
            victim_role=args.victim,
            activity=args.activity,
        )
        exit_code = 0
    except Exception as exc:  # noqa: BLE001 - persist exact live evidence.
        if isinstance(exc, OrganicDeathFailure):
            result = exc.evidence
        result["error"] = str(exc)
        result["error_type"] = type(exc).__name__
        result["traceback"] = traceback.format_exc()
        result["instance_prefix"] = instance_prefix
        result["kill_type"] = args.kill_type
        result["victim_role"] = args.victim
        result["activity"] = args.activity
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
                "kill_type": args.kill_type,
                "victim_role": args.victim,
                "activity": args.activity,
                "milestones": result.get("milestones"),
                "damage_events": result.get("damage_events"),
                "instance_prefix": instance_prefix,
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
