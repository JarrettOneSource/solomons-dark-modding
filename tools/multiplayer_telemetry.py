#!/usr/bin/env python3
"""Structured host/client telemetry for local multiplayer verification harnesses."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from verify_local_multiplayer_sync import CLIENT_PIPE, HOST_PIPE, lua, parse_key_values


ROOT = Path(__file__).resolve().parent.parent


SNAPSHOT_LUA = r"""
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
local function num(value, default)
  local n = tonumber(value)
  if n == nil or n ~= n or n == math.huge or n == -math.huge then
    return default or 0
  end
  return n
end
local function emit_num(key, value)
  emit(key, string.format("%.3f", num(value, 0)))
end
local function actor_radius(address)
  local offset = sd.debug and sd.debug.layout_offset and sd.debug.layout_offset("actor_collision_radius") or nil
  if address == nil or tonumber(address) == 0 or offset == nil then return 0 end
  return sd.debug.read_float(tonumber(address) + offset) or 0
end
local scene = sd.world and sd.world.get_scene and sd.world.get_scene() or nil
local world = sd.world and sd.world.get_state and sd.world.get_state() or nil
emit("scene.name", scene and (scene.name or scene.kind) or "")
emit("scene.kind", scene and scene.kind or "")
emit("world.valid", world ~= nil)
emit("world.run_active", world and world.run_active or false)
emit("world.combat_active", world and world.combat_active or false)
emit("world.wave_index", world and world.wave_index or 0)
emit("world.wave_counter", world and world.wave_counter or 0)

local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
emit("player.valid", player ~= nil)
emit("player.actor", player and player.actor_address or 0)
emit_num("player.x", player and player.x or 0)
emit_num("player.y", player and player.y or 0)
emit_num("player.heading", player and player.heading or 0)
emit_num("player.hp", player and player.hp or 0)
emit_num("player.max_hp", player and player.max_hp or 0)
emit_num("player.mp", player and player.mp or 0)
emit_num("player.max_mp", player and player.max_mp or 0)
emit("player.anim_drive_state", player and player.anim_drive_state or 0)
emit("player.anim_drive_state_word", player and player.anim_drive_state_word or 0)
emit_num("player.walk_cycle_primary", player and player.walk_cycle_primary or 0)
emit_num("player.walk_cycle_secondary", player and player.walk_cycle_secondary or 0)
emit_num("player.render_advance_phase", player and player.render_advance_phase or 0)
emit_num("player.magic_shield_absorb_remaining", player and player.magic_shield_absorb_remaining or 0)
emit_num("player.magic_shield_absorb_capacity", player and player.magic_shield_absorb_capacity or 0)
emit_num("player.magic_shield_explosion_fraction", player and player.magic_shield_explosion_fraction or 0)
emit_num("player.magic_shield_hit_flash", player and player.magic_shield_hit_flash or 0)
emit_num("player.render_drive_move_blend", player and player.render_drive_move_blend or 0)
emit_num("player.render_drive_overlay_alpha", player and player.render_drive_overlay_alpha or 0)
emit_num("player.radius", player and actor_radius(player.actor_address) or 0)

local mp = sd.runtime and sd.runtime.get_multiplayer_state and sd.runtime.get_multiplayer_state() or nil
emit("mp.valid", mp ~= nil)
emit("mp.foundation_ready", mp and mp.foundation_ready or false)
emit("mp.transport_ready", mp and mp.transport_ready or false)
emit("mp.session_status", mp and mp.session_status or "")
emit("mp.session_transport", mp and mp.session_transport or "")
emit("mp.participant_count", mp and mp.participant_count or 0)
if mp and mp.participants then
  for index, participant in ipairs(mp.participants) do
    if index > 4 then break end
    local prefix = "mp.participant." .. tostring(index) .. "."
    emit(prefix .. "id", participant.participant_id or 0)
    emit(prefix .. "name", participant.name or "")
    emit(prefix .. "kind", participant.kind or "")
    emit(prefix .. "controller", participant.controller_kind or "")
    emit(prefix .. "connected", participant.transport_connected or false)
    emit(prefix .. "runtime_valid", participant.runtime_valid or false)
    emit(prefix .. "in_run", participant.in_run or false)
    emit(prefix .. "run_nonce", participant.run_nonce or 0)
    emit(prefix .. "scene_kind", participant.scene_kind or "")
    emit_num(prefix .. "life_current", participant.life_current or 0)
    emit_num(prefix .. "life_max", participant.life_max or 0)
    emit_num(prefix .. "mana_current", participant.mana_current or 0)
    emit_num(prefix .. "mana_max", participant.mana_max or 0)
    local owned = participant.owned_progression
    emit(prefix .. "gold", owned and owned.gold or 0)
    emit(prefix .. "gold_revision", owned and owned.gold_revision or 0)
    emit(prefix .. "inventory_revision", owned and owned.inventory_revision or 0)
    emit(prefix .. "spellbook_revision", owned and owned.spellbook_revision or 0)
    emit(prefix .. "statbook_revision", owned and owned.statbook_revision or 0)
  end
end

local peers = sd.bots and sd.bots.get_participants and sd.bots.get_participants() or {}
emit("peer.count", #peers)
for index, peer in ipairs(peers) do
  if index > 4 then break end
  local prefix = "peer." .. tostring(index) .. "."
  emit(prefix .. "id", peer.id or 0)
  emit(prefix .. "name", peer.name or "")
  emit(prefix .. "kind", peer.participant_kind or "")
  emit(prefix .. "controller", peer.controller_kind or "")
  emit(prefix .. "materialized", peer.entity_materialized or false)
  emit(prefix .. "transform_valid", peer.transform_valid or false)
  emit(prefix .. "actor", peer.actor_address or 0)
  emit_num(prefix .. "x", peer.x or 0)
  emit_num(prefix .. "y", peer.y or 0)
  emit_num(prefix .. "heading", peer.heading or 0)
  emit_num(prefix .. "hp", peer.hp or 0)
  emit_num(prefix .. "max_hp", peer.max_hp or 0)
  emit_num(prefix .. "mp", peer.mp or 0)
  emit_num(prefix .. "max_mp", peer.max_mp or 0)
  emit_num(prefix .. "magic_shield_absorb_remaining", peer.magic_shield_absorb_remaining or 0)
  emit_num(prefix .. "magic_shield_absorb_capacity", peer.magic_shield_absorb_capacity or 0)
  emit_num(prefix .. "magic_shield_explosion_fraction", peer.magic_shield_explosion_fraction or 0)
  emit_num(prefix .. "magic_shield_hit_flash", peer.magic_shield_hit_flash or 0)
  emit_num(prefix .. "render_drive_overlay_alpha", peer.render_drive_overlay_alpha or 0)
  emit_num(prefix .. "render_drive_move_blend", peer.render_drive_move_blend or 0)
  local actor = tonumber(peer.actor_address) or 0
  if actor ~= 0 and sd.debug and sd.debug.layout_offset then
    local oremaining = sd.debug.layout_offset("actor_magic_shield_absorb_remaining")
    local ocapacity = sd.debug.layout_offset("actor_magic_shield_absorb_capacity")
    local oexplosion = sd.debug.layout_offset("actor_magic_shield_explosion_fraction")
    local oflash = sd.debug.layout_offset("actor_magic_shield_hit_flash")
    local ooverlay = sd.debug.layout_offset("actor_render_drive_overlay_alpha")
    local ophase = sd.debug.layout_offset("actor_render_drive_move_blend")
    emit_num(prefix .. "actor_magic_shield_absorb_remaining", sd.debug.read_float(actor + oremaining) or 0)
    emit_num(prefix .. "actor_magic_shield_absorb_capacity", sd.debug.read_float(actor + ocapacity) or 0)
    emit_num(prefix .. "actor_magic_shield_explosion_fraction", sd.debug.read_float(actor + oexplosion) or 0)
    emit_num(prefix .. "actor_magic_shield_hit_flash", sd.debug.read_float(actor + oflash) or 0)
    emit_num(prefix .. "actor_overlay_alpha", sd.debug.read_float(actor + ooverlay) or 0)
    emit_num(prefix .. "actor_overlay_phase", sd.debug.read_float(actor + ophase) or 0)
  end
  emit("peer." .. tostring(peer.id or index) .. ".index", index)
end

local actors = sd.world and sd.world.list_actors and sd.world.list_actors() or {}
local replicated = sd.world and sd.world.get_replicated_actors and sd.world.get_replicated_actors() or nil
local network_by_local = {}
if replicated and replicated.bindings then
  for _, binding in ipairs(replicated.bindings) do
    local local_address = tonumber(binding.local_actor_address) or 0
    local network_id = tonumber(binding.network_actor_id) or 0
    if local_address ~= 0 and network_id ~= 0 then
      network_by_local[local_address] = network_id
    end
  end
end

emit("actors.count", #actors)
local enemy_count = 0
local live_enemy_count = 0
local projectile_count = 0
local projectile_types = {[0x7D3] = true, [0x7D4] = true, [0x7D5] = true}
for _, actor in ipairs(actors) do
  local type_id = tonumber(actor.object_type_id) or 0
  local address = tonumber(actor.actor_address) or 0
  if actor.tracked_enemy then
    enemy_count = enemy_count + 1
    if not actor.dead and num(actor.hp, 0) > 0 then live_enemy_count = live_enemy_count + 1 end
    if enemy_count <= 16 then
      local prefix = "enemy." .. tostring(enemy_count) .. "."
      emit(prefix .. "actor", address)
      emit(prefix .. "network_id", network_by_local[address] or 0)
      emit(prefix .. "type", type_id)
      emit(prefix .. "enemy_type", actor.enemy_type or 0)
      emit(prefix .. "dead", actor.dead or false)
      emit_num(prefix .. "x", actor.x or 0)
      emit_num(prefix .. "y", actor.y or 0)
      emit_num(prefix .. "heading", actor.heading or 0)
      emit_num(prefix .. "hp", actor.hp or 0)
      emit_num(prefix .. "max_hp", actor.max_hp or 0)
      emit_num(prefix .. "radius", actor.radius or 0)
      emit(prefix .. "anim_drive_state", actor.anim_drive_state or 0)
    end
  end
  if projectile_types[type_id] then
    projectile_count = projectile_count + 1
    if projectile_count <= 16 then
      local prefix = "projectile." .. tostring(projectile_count) .. "."
      emit(prefix .. "actor", address)
      emit(prefix .. "type", type_id)
      emit_num(prefix .. "x", actor.x or 0)
      emit_num(prefix .. "y", actor.y or 0)
      emit_num(prefix .. "heading", actor.heading or 0)
      emit_num(prefix .. "radius", actor.radius or 0)
      emit_num(prefix .. "hp", actor.hp or 0)
      emit_num(prefix .. "max_hp", actor.max_hp or 0)
    end
  end
end
emit("enemy.count", enemy_count)
emit("enemy.live_count", live_enemy_count)
emit("projectile.count", projectile_count)

emit("replicated.valid", replicated ~= nil)
emit("replicated.scene_kind", replicated and replicated.scene_kind or "")
emit("replicated.sequence", replicated and replicated.sequence or 0)
emit("replicated.run_nonce", replicated and replicated.run_nonce or 0)
emit("replicated.actor_count", replicated and replicated.actor_count or 0)
emit("replicated.actor_total_count", replicated and replicated.actor_total_count or 0)
emit("replicated.truncated", replicated and replicated.truncated or false)
emit("replicated.apply_valid", replicated and replicated.apply_valid or false)
emit("replicated.local_actor_count", replicated and replicated.local_actor_count or 0)
emit("replicated.matched_actor_count", replicated and replicated.matched_actor_count or 0)
emit("replicated.created_actor_count", replicated and replicated.created_actor_count or 0)
emit("replicated.parked_actor_count", replicated and replicated.parked_actor_count or 0)
emit("replicated.dead_actor_count", replicated and replicated.dead_actor_count or 0)
if replicated and replicated.actors then
  local rep_enemy_count = 0
  for _, actor in ipairs(replicated.actors) do
    if actor.tracked_enemy then
      rep_enemy_count = rep_enemy_count + 1
      if rep_enemy_count <= 16 then
        local prefix = "rep_enemy." .. tostring(rep_enemy_count) .. "."
        emit(prefix .. "network_id", actor.network_actor_id or 0)
        emit(prefix .. "type", actor.native_type_id or actor.object_type_id or 0)
        emit(prefix .. "dead", actor.dead or false)
        emit_num(prefix .. "x", actor.x or actor.position_x or 0)
        emit_num(prefix .. "y", actor.y or actor.position_y or 0)
        emit_num(prefix .. "heading", actor.heading or 0)
        emit_num(prefix .. "hp", actor.hp or 0)
        emit_num(prefix .. "max_hp", actor.max_hp or 0)
      end
    end
  end
  emit("rep_enemy.count", rep_enemy_count)
else
  emit("rep_enemy.count", 0)
end
"""


class MultiplayerTelemetryRecorder:
    def __init__(
        self,
        path: str | Path,
        *,
        host_pipe: str = HOST_PIPE,
        client_pipe: str = CLIENT_PIPE,
        enabled: bool = True,
        lua_timeout: float = 2.5,
    ) -> None:
        self.path = Path(path)
        self.host_pipe = host_pipe
        self.client_pipe = client_pipe
        self.enabled = enabled
        self.lua_timeout = lua_timeout
        self.started_monotonic = time.monotonic()
        if self.enabled:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("", encoding="utf-8")

    def _sample_pipe(self, pipe_name: str) -> dict[str, Any]:
        try:
            raw = lua(pipe_name, SNAPSHOT_LUA, timeout=self.lua_timeout)
            return {"ok": True, "state": parse_key_values(raw)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def record(self, label: str, **extra: Any) -> None:
        if not self.enabled:
            return
        event = {
            "time": time.time(),
            "elapsed": time.monotonic() - self.started_monotonic,
            "label": label,
            "extra": extra,
            "instances": {
                "host": self._sample_pipe(self.host_pipe),
                "client": self._sample_pipe(self.client_pipe),
            },
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")

    def sample_window(
        self,
        label: str,
        *,
        duration: float,
        interval: float = 0.2,
        **extra: Any,
    ) -> None:
        if not self.enabled:
            return
        deadline = time.monotonic() + duration
        index = 0
        while True:
            self.record(label, sample_index=index, **extra)
            index += 1
            if time.monotonic() >= deadline:
                break
            time.sleep(interval)
