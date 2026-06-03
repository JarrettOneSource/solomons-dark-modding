#!/usr/bin/env python3
"""Probe mixed Air/Ether run sync under real cast input and sustained combat."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    CLIENT_PIPE,
    HOST_ID,
    HOST_NAME,
    HOST_PIPE,
    ROOT,
    VerifyFailure,
    disable_bots,
    launch_pair,
    lua,
    parse_key_values,
    place_player,
    start_host_testrun_and_wait_for_clients,
    stop_games,
    wait_for_remote,
)
from verify_player_health_death_sync import set_local_player_vitals
from verify_real_input_spell_cast_sync import (
    CLIENT_LOG,
    HOST_LOG,
    Direction,
    detect_instance_pids,
    ensure_host_combat_started,
    log_after,
    parse_phase_counts,
    queue_gameplay_mouse_left,
    read_log,
    sustain_pair_vitals,
    wait_for_source_cast,
)
from verify_run_world_snapshot import (
    CLIENT_SNAPSHOT_LUA,
    HOST_ENEMY_LUA,
    start_host_waves,
    wait_for_run_snapshot,
)


OUTPUT = ROOT / "runtime" / "mixed_air_ether_run_sync_probe.json"
TEST_PLAYER_HP = 5000.0
AIR_HOST_PRESET = "map_create_air_mind_hub"
ETHER_CLIENT_PRESET = "map_create_ether_mind_hub"


def values(pipe_name: str, code: str, timeout: float = 5.0) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, code, timeout=timeout))


def number(row: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key, default))
    except (TypeError, ValueError):
        return default


def sample_remote_participant(pipe_name: str, participant_id: int) -> dict[str, str]:
    code = f"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local bot = sd.bots and sd.bots.get_participant_state and sd.bots.get_participant_state({participant_id}) or nil
emit("available", bot ~= nil)
if bot == nil then return end
local actor = tonumber(bot.actor_address) or 0
emit("name", bot.name or "")
emit("element_id", bot.profile and bot.profile.element_id or -1)
emit("actor_address", actor)
emit("hp", bot.hp or 0)
emit("max_hp", bot.max_hp or 0)
emit("mp", bot.mp or 0)
emit("max_mp", bot.max_mp or 0)
emit("anim_drive_state", bot.anim_drive_state or 0)
emit("resolved_animation_state_id", bot.resolved_animation_state_id or -1)
emit("cast_active", bot.cast_active or false)
emit("cast_pending", bot.cast_pending or false)
emit("cast_skill_id", bot.cast_skill_id or 0)
emit("cast_ticks_waiting", bot.cast_ticks_waiting or 0)
emit("cast_target_actor_address", bot.cast_target_actor_address or 0)
emit("active_cast_group", bot.active_cast_group or 0)
emit("active_cast_slot", bot.active_cast_slot or 0)
emit("active_spell_object_readable", bot.active_spell_object_readable or false)
emit("active_spell_object_type", bot.active_spell_object_type or 0)
emit("active_spell_object_address", bot.active_spell_object_address or 0)
emit("active_spell_object_x", bot.active_spell_object_x or 0)
emit("active_spell_object_y", bot.active_spell_object_y or 0)
if actor ~= 0 then
  local target_offset = sd.debug.layout_offset("actor_current_target_actor")
  local group_offset = sd.debug.layout_offset("actor_spell_target_group_byte")
  local slot_offset = sd.debug.layout_offset("actor_spell_target_slot_short")
  local aim_x_offset = sd.debug.layout_offset("actor_aim_target_x")
  local aim_y_offset = sd.debug.layout_offset("actor_aim_target_y")
  emit("native_current_target", target_offset and (sd.debug.read_ptr(actor + target_offset) or 0) or 0)
  emit("native_target_group", group_offset and (sd.debug.read_u8(actor + group_offset) or 0) or 0)
  emit("native_target_slot", slot_offset and (sd.debug.read_u16(actor + slot_offset) or 0) or 0)
  emit("native_aim_x", aim_x_offset and (sd.debug.read_float(actor + aim_x_offset) or 0) or 0)
  emit("native_aim_y", aim_y_offset and (sd.debug.read_float(actor + aim_y_offset) or 0) or 0)
  local plate = sd.bots.get_nameplate and sd.bots.get_nameplate(actor) or nil
  emit("nameplate", plate and plate.name or "")
else
  emit("native_current_target", 0)
  emit("native_target_group", 0)
  emit("native_target_slot", 0)
  emit("native_aim_x", 0)
  emit("native_aim_y", 0)
  emit("nameplate", "")
end
"""
    return values(pipe_name, code, timeout=5.0)


def sample_local_player(pipe_name: str) -> dict[str, str]:
    return values(
        pipe_name,
        """
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local player = sd.player.get_state and sd.player.get_state() or nil
emit("available", player ~= nil)
if player == nil then return end
emit("actor_address", player.actor_address or 0)
emit("x", player.x or 0)
emit("y", player.y or 0)
emit("heading", player.heading or 0)
emit("hp", player.hp or 0)
emit("max_hp", player.max_hp or 0)
emit("mp", player.mp or 0)
emit("max_mp", player.max_mp or 0)
""",
        timeout=5.0,
    )


def sample_world() -> dict[str, object]:
    host = values(HOST_PIPE, HOST_ENEMY_LUA, timeout=5.0)
    client = values(CLIENT_PIPE, CLIENT_SNAPSHOT_LUA, timeout=5.0)
    return {
        "host": host,
        "client": client,
        "summary": {
            "host_live": int(number(host, "live_enemies")),
            "host_dead": int(number(host, "dead_enemies")),
            "client_snapshot_live": int(number(client, "live_snapshot_actors")),
            "client_local_live": int(number(client, "local_live_tracked_enemies")),
            "client_apply_matched": int(number(client, "apply_matched")),
            "client_live_compared": int(number(client, "live_compared")),
            "client_live_max_distance": number(client, "live_max_distance"),
            "client_max_hp_delta": number(client, "max_hp_delta"),
            "client_truncated": client.get("truncated") == "true",
            "client_actor_count": int(number(client, "actor_count")),
            "client_actor_total_count": int(number(client, "actor_total_count")),
        },
    }


def parse_remote_cast_queues(log_text: str, participant_id: int) -> list[dict[str, object]]:
    pattern = re.compile(
        rf"Multiplayer remote cast queued\. participant_id={participant_id} "
        rf"cast_sequence=(\d+) phase=([a-z_]+) skill_id=(\d+) "
        rf"target_network_actor_id=(\d+) target_actor=([0-9A-Fa-fx]+) "
        rf"target_source=([a-z_]+)"
    )
    return [
        {
            "cast_sequence": int(sequence),
            "phase": phase,
            "skill_id": int(skill_id),
            "target_network_actor_id": int(target_id),
            "target_actor": target_actor,
            "target_source": target_source,
        }
        for sequence, phase, skill_id, target_id, target_actor, target_source
        in pattern.findall(log_text)
    ]


def parse_local_cast_sends(log_text: str, participant_id: int) -> list[dict[str, object]]:
    pattern = re.compile(
        rf"Multiplayer local cast sent\. participant_id={participant_id} "
        rf"cast_sequence=(\d+) phase=([a-z_]+) skill_id=(\d+) "
        rf"target_network_actor_id=(\d+)"
    )
    return [
        {
            "cast_sequence": int(sequence),
            "phase": phase,
            "skill_id": int(skill_id),
            "target_network_actor_id": int(target_id),
        }
        for sequence, phase, skill_id, target_id in pattern.findall(log_text)
    ]


def drive_and_sample_cast(
    direction: Direction,
    *,
    label: str,
    frames: int,
    sample_seconds: float = 3.0,
) -> dict[str, object]:
    source_offset = len(read_log(direction.source_log))
    receiver_offset = len(read_log(direction.receiver_log))
    before = sample_remote_participant(direction.receiver_pipe, direction.source_id)
    input_result = queue_gameplay_mouse_left(direction, frames)
    source_wait: dict[str, object] = {}
    try:
        source_log, phase_counts, native_hook_count = wait_for_source_cast(
            direction,
            source_offset,
            {"pressed": 1},
            timeout=5.0,
        )
        source_wait = {
            "phase_counts_at_wait": phase_counts,
            "native_hook_count_at_wait": native_hook_count,
            "source_log_size_at_wait": len(source_log),
        }
    except Exception as exc:
        source_wait = {"error": str(exc)}

    samples: list[dict[str, str]] = []
    active_seen = False
    target_seen = False
    deadline = time.monotonic() + sample_seconds
    while time.monotonic() < deadline:
        sample = sample_remote_participant(direction.receiver_pipe, direction.source_id)
        samples.append(sample)
        active_seen = active_seen or sample.get("cast_active") == "true"
        target_seen = target_seen or int(number(sample, "cast_target_actor_address")) != 0
        time.sleep(0.08)

    source_log = log_after(direction.source_log, source_offset)
    receiver_log = log_after(direction.receiver_log, receiver_offset)
    return {
        "label": label,
        "input": input_result,
        "source_wait": source_wait,
        "before": before,
        "after": samples[-1] if samples else {},
        "sample_count": len(samples),
        "active_seen": active_seen,
        "target_seen": target_seen,
        "phase_counts": parse_phase_counts(source_log, direction.source_id),
        "local_cast_sends": parse_local_cast_sends(source_log, direction.source_id),
        "remote_cast_queues": parse_remote_cast_queues(receiver_log, direction.source_id),
    }


def place_players_for_away_cast() -> dict[str, object]:
    host_player = sample_local_player(HOST_PIPE)
    client_player = sample_local_player(CLIENT_PIPE)
    host_x = number(host_player, "x")
    host_y = number(host_player, "y")
    return {
        "host_before": host_player,
        "client_before": client_player,
        "host_place": place_player(HOST_PIPE, host_x - 180.0, host_y - 80.0, 270.0),
        "client_place": place_player(CLIENT_PIPE, host_x + 180.0, host_y - 80.0, 90.0),
    }


def run_sustained_combat_window(
    directions: list[Direction],
    *,
    duration_seconds: float,
) -> dict[str, object]:
    samples: list[dict[str, object]] = []
    cast_results: list[dict[str, object]] = []
    next_cast_at = time.monotonic()
    next_sample_at = time.monotonic()
    deadline = time.monotonic() + duration_seconds
    cast_index = 0
    while time.monotonic() < deadline:
        now = time.monotonic()
        if now >= next_cast_at:
            direction = directions[cast_index % len(directions)]
            cast_results.append(
                drive_and_sample_cast(
                    direction,
                    label=f"sustain_{cast_index}_{direction.name}",
                    frames=36,
                    sample_seconds=0.5,
                )
            )
            cast_index += 1
            next_cast_at = time.monotonic() + 1.5
        if now >= next_sample_at:
            samples.append(
                {
                    "elapsed": duration_seconds - max(0.0, deadline - time.monotonic()),
                    "world": sample_world(),
                    "client_observes_host": sample_remote_participant(CLIENT_PIPE, HOST_ID),
                    "host_observes_client": sample_remote_participant(HOST_PIPE, CLIENT_ID),
                }
            )
            next_sample_at = time.monotonic() + 5.0
        time.sleep(0.05)

    if not samples:
        samples.append({"elapsed": duration_seconds, "world": sample_world()})

    max_distance = max(
        number(sample["world"]["client"], "live_max_distance")
        for sample in samples
        if "world" in sample
    )
    max_hp_delta = max(
        number(sample["world"]["client"], "max_hp_delta")
        for sample in samples
        if "world" in sample
    )
    truncated_seen = any(
        sample["world"]["client"].get("truncated") == "true"
        for sample in samples
        if "world" in sample
    )
    return {
        "duration_seconds": duration_seconds,
        "sample_count": len(samples),
        "samples": samples,
        "cast_count": len(cast_results),
        "casts": cast_results,
        "max_client_live_distance": max_distance,
        "max_client_hp_delta": max_hp_delta,
        "truncated_seen": truncated_seen,
    }


def main() -> int:
    result: dict[str, object] = {"ok": False}
    try:
        stop_games()
        result["launch"] = launch_pair(
            host_preset=AIR_HOST_PRESET,
            client_preset=ETHER_CLIENT_PRESET,
        )
        pids = detect_instance_pids()
        result["pids"] = pids
        wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "hub")
        wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "hub")
        result["hub_remote_state"] = {
            "client_observes_host": sample_remote_participant(CLIENT_PIPE, HOST_ID),
            "host_observes_client": sample_remote_participant(HOST_PIPE, CLIENT_ID),
        }

        result["run_entry"] = start_host_testrun_and_wait_for_clients()
        wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "testrun")
        wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "testrun")
        disable_bots()
        result["vitals"] = sustain_pair_vitals()
        result["pre_wave_remote_state"] = {
            "client_observes_host": sample_remote_participant(CLIENT_PIPE, HOST_ID),
            "host_observes_client": sample_remote_participant(HOST_PIPE, CLIENT_ID),
        }

        directions = [
            Direction(
                "host_air_to_client",
                HOST_ID,
                HOST_NAME,
                HOST_PIPE,
                HOST_LOG,
                pids["host"],
                CLIENT_PIPE,
                CLIENT_LOG,
            ),
            Direction(
                "client_ether_to_host",
                CLIENT_ID,
                CLIENT_NAME,
                CLIENT_PIPE,
                CLIENT_LOG,
                pids["client"],
                HOST_PIPE,
                HOST_LOG,
            ),
        ]

        result["pre_wave_casts"] = [
            drive_and_sample_cast(directions[0], label="pre_wave_host_air_empty", frames=120),
            drive_and_sample_cast(directions[1], label="pre_wave_client_ether_empty", frames=20),
        ]
        result["start_waves"] = start_host_waves()
        result["wave_vitals"] = {
            "host": set_local_player_vitals(HOST_PIPE, TEST_PLAYER_HP, TEST_PLAYER_HP),
            "client": set_local_player_vitals(CLIENT_PIPE, TEST_PLAYER_HP, TEST_PLAYER_HP),
        }
        result["initial_snapshot"] = wait_for_run_snapshot(require_complete_lifecycle=True)
        result["place_for_away_cast"] = place_players_for_away_cast()
        time.sleep(0.75)
        result["post_wave_casts"] = [
            drive_and_sample_cast(directions[0], label="post_wave_host_air_away", frames=150),
            drive_and_sample_cast(directions[1], label="post_wave_client_ether", frames=20),
        ]
        result["sustained"] = run_sustained_combat_window(
            directions,
            duration_seconds=70.0,
        )
        result["final_world"] = sample_world()
        result["final_remote_state"] = {
            "client_observes_host": sample_remote_participant(CLIENT_PIPE, HOST_ID),
            "host_observes_client": sample_remote_participant(HOST_PIPE, CLIENT_ID),
        }
        result["ok"] = True
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        result["error"] = str(exc)
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1
    finally:
        stop_games()


if __name__ == "__main__":
    raise SystemExit(main())
