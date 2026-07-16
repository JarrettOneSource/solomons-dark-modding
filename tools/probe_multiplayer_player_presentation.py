#!/usr/bin/env python3
"""Probe remote player presentation state in hub/run before and after casts."""

from __future__ import annotations

import json
import time
from pathlib import Path

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
from verify_real_input_spell_cast_sync import (
    CLIENT_LOG,
    HOST_LOG,
    Direction,
    detect_instance_pids,
    ensure_host_combat_started,
    queue_gameplay_mouse_left,
    read_log,
    sustain_pair_vitals,
)
from verify_real_input_spell_cast_sync import lua as real_input_lua


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = ROOT / "runtime" / "multiplayer_player_presentation_probe.json"
TAP_FRAMES = 12


SNAPSHOT_LUA_TEMPLATE = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local function num(value, default)
  local n = tonumber(value)
  if n == nil or n ~= n or n == math.huge or n == -math.huge then
    return default or 0
  end
  return n
end
local function emit_num(key, value) emit(key, string.format("%.3f", num(value, 0))) end
local function emit_hex(key, value) emit(key, string.format("0x%X", num(value, 0))) end

local peer_id = __PEER_ID__
local scene = sd.world.get_scene and sd.world.get_scene() or nil
emit("scene", scene and (scene.name or scene.kind) or "")
emit("scene.kind", scene and scene.kind or "")

local player = sd.player.get_state and sd.player.get_state() or nil
emit("player.valid", player ~= nil)
emit_hex("player.actor", player and player.actor_address or 0)
emit_num("player.hp", player and player.hp or 0)
emit_num("player.max_hp", player and player.max_hp or 0)
emit_num("player.mp", player and player.mp or 0)
emit_num("player.max_mp", player and player.max_mp or 0)
emit_num("player.overlay_alpha", player and player.render_drive_overlay_alpha or 0)
emit_num("player.move_blend", player and player.render_drive_move_blend or 0)

local peer = sd.bots.get_participant_state and sd.bots.get_participant_state(peer_id) or nil
emit("peer.available", peer ~= nil and peer.available or false)
emit("peer.materialized", peer ~= nil and peer.entity_materialized or false)
emit("peer.kind", peer and peer.participant_kind or "")
emit("peer.controller", peer and peer.controller_kind or "")
emit("peer.transform_valid", peer and peer.transform_valid or false)
emit_hex("peer.actor", peer and peer.actor_address or 0)
emit_num("peer.x", peer and peer.x or 0)
emit_num("peer.y", peer and peer.y or 0)
emit_num("peer.heading", peer and peer.heading or 0)
emit_num("peer.hp", peer and peer.hp or 0)
emit_num("peer.max_hp", peer and peer.max_hp or 0)
emit_num("peer.mp", peer and peer.mp or 0)
emit_num("peer.max_mp", peer and peer.max_mp or 0)
emit("peer.cast_active", peer and peer.cast_active or false)
emit("peer.anim_drive_state", peer and peer.anim_drive_state or 0)
emit_num("peer.overlay_alpha", peer and peer.render_drive_overlay_alpha or 0)
emit_num("peer.move_blend", peer and peer.render_drive_move_blend or 0)
emit_num("peer.effect_timer", peer and peer.render_drive_effect_timer or 0)
emit_num("peer.effect_progress", peer and peer.render_drive_effect_progress or 0)

local actor = peer and tonumber(peer.actor_address) or 0
if actor ~= 0 then
  local nameplate = sd.bots.get_nameplate(actor)
  emit("nameplate.available", nameplate ~= nil)
  emit("nameplate.name", nameplate and nameplate.name or "")
  emit("nameplate.id", nameplate and nameplate.id or 0)

  local function off(name) return sd.debug.layout_offset(name) end
  local slot = off("actor_slot")
  local progression_runtime = off("actor_progression_runtime_state")
  local equip_runtime = off("actor_equip_runtime_state")
  local progression_handle = off("actor_progression_handle")
  local equip_handle = off("actor_equip_handle")
  local continuous_mode = off("actor_continuous_primary_mode")
  local continuous_active = off("actor_continuous_primary_active")
  local heading = off("actor_heading")
  local overlay = off("actor_render_drive_overlay_alpha")
  local move_blend = off("actor_render_drive_move_blend")
  local effect_timer = off("actor_render_drive_effect_timer")
  local effect_progress = off("actor_render_drive_effect_progress")

  emit("actor.slot", sd.debug.read_i8(actor + slot) or -1)
  emit_hex("actor.progression_runtime", sd.debug.read_ptr(actor + progression_runtime) or 0)
  emit_hex("actor.equip_runtime", sd.debug.read_ptr(actor + equip_runtime) or 0)
  emit_hex("actor.progression_handle", sd.debug.read_ptr(actor + progression_handle) or 0)
  emit_hex("actor.equip_handle", sd.debug.read_ptr(actor + equip_handle) or 0)
  emit_hex("actor.continuous_active", sd.debug.read_ptr(actor + continuous_active) or 0)
  emit("actor.continuous_mode", sd.debug.read_u32(actor + continuous_mode) or 0)
  emit_num("actor.heading", sd.debug.read_float(actor + heading) or 0)
  emit_num("actor.overlay_alpha", sd.debug.read_float(actor + overlay) or 0)
  emit_num("actor.move_blend", sd.debug.read_float(actor + move_blend) or 0)
  emit_num("actor.effect_timer", sd.debug.read_float(actor + effect_timer) or 0)
  emit_num("actor.effect_progress", sd.debug.read_float(actor + effect_progress) or 0)
else
  emit("nameplate.available", false)
end

local mp = sd.runtime.get_multiplayer_state and sd.runtime.get_multiplayer_state() or nil
emit("mp.valid", mp ~= nil)
if mp and mp.participants then
  for _, participant in ipairs(mp.participants) do
    if participant.participant_id == peer_id then
      emit("runtime.name", participant.name or "")
      emit("runtime.controller", participant.controller_kind or "")
      emit("runtime.in_run", participant.in_run or false)
      emit("runtime.scene_kind", participant.scene_kind or "")
      emit_num("runtime.life_current", participant.life_current or 0)
      emit_num("runtime.life_max", participant.life_max or 0)
      emit_num("runtime.mana_current", participant.mana_current or 0)
      emit_num("runtime.mana_max", participant.mana_max or 0)
    end
  end
end
"""


def values(pipe_name: str, code: str, timeout: float = 5.0) -> dict[str, str]:
    return parse_key_values(real_input_lua(pipe_name, code, timeout=timeout))


def snapshot(observer_pipe: str, peer_id: int, label: str) -> dict[str, str]:
    code = SNAPSHOT_LUA_TEMPLATE.replace("__PEER_ID__", f"0x{peer_id:X}")
    row = values(observer_pipe, code, timeout=5.0)
    row["label"] = label
    row["observer_pipe"] = observer_pipe
    row["peer_id"] = f"0x{peer_id:X}"
    return row


def direction_snapshot(direction: Direction, label: str) -> dict[str, str]:
    return snapshot(direction.receiver_pipe, direction.source_id, f"{direction.name}.{label}")


def cast_and_sample(direction: Direction) -> dict[str, object]:
    source_log_offset = len(read_log(direction.source_log))
    receiver_log_offset = len(read_log(direction.receiver_log))
    before = direction_snapshot(direction, "before_cast")
    input_result = queue_gameplay_mouse_left(direction, TAP_FRAMES)
    samples: list[dict[str, str]] = []
    deadline = time.monotonic() + 2.5
    while time.monotonic() < deadline:
        samples.append(direction_snapshot(direction, "during_or_after_cast"))
        time.sleep(0.15)
    after = direction_snapshot(direction, "after_cast")
    source_log = read_log(direction.source_log)[source_log_offset:]
    receiver_log = read_log(direction.receiver_log)[receiver_log_offset:]
    return {
        "input": input_result,
        "before": before,
        "samples": samples,
        "after": after,
        "source_cast_lines": [
            line for line in source_log.splitlines()
            if "Multiplayer local" in line or "native cast" in line
        ],
        "receiver_cast_lines": [
            line for line in receiver_log.splitlines()
            if "remote cast" in line or "cast complete" in line or "native-remote" in line
        ],
    }


def main() -> int:
    result: dict[str, object] = {"ok": False}
    try:
        stop_games()
        result["launch"] = launch_pair(preset="map_create_fire_mind_hub")
        wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "hub")
        wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "hub")
        result["hub"] = {
            "host_observes_client": snapshot(HOST_PIPE, CLIENT_ID, "hub.host_observes_client"),
            "client_observes_host": snapshot(CLIENT_PIPE, HOST_ID, "hub.client_observes_host"),
        }
        result["run_entry"] = start_host_testrun_and_wait_for_clients()
        wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "testrun")
        wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "testrun")
        disable_bots()
        result["vitals"] = sustain_pair_vitals()
        result["combat"] = ensure_host_combat_started()
        result["pids"] = detect_instance_pids()
        result["run_before_cast"] = {
            "host_observes_client": snapshot(HOST_PIPE, CLIENT_ID, "run.host_observes_client"),
            "client_observes_host": snapshot(CLIENT_PIPE, HOST_ID, "run.client_observes_host"),
        }
        directions = [
            Direction("host_to_client", HOST_ID, HOST_NAME, HOST_PIPE, HOST_LOG, result["pids"]["host"], CLIENT_PIPE, CLIENT_LOG),
            Direction("client_to_host", CLIENT_ID, CLIENT_NAME, CLIENT_PIPE, CLIENT_LOG, result["pids"]["client"], HOST_PIPE, HOST_LOG),
        ]
        result["casts"] = {
            direction.name: cast_and_sample(direction)
            for direction in directions
        }
        result["ok"] = True
        return 0
    except Exception as exc:
        result["error"] = str(exc)
        return 1
    finally:
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
        stop_games()


if __name__ == "__main__":
    raise SystemExit(main())
