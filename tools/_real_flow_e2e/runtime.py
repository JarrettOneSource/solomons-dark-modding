from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import json
import math
from pathlib import Path
import subprocess
import time
from typing import Any, Callable

from .config import InputAction
from .windows import (
    WindowsPeer,
    click as local_click,
    send_key as local_send_key,
)


class RuntimeProbeError(RuntimeError):
    """A read-only runtime probe or real-input assertion failed."""


def _send_key(
    source_root: Path,
    peer: WindowsPeer,
    key: str,
    hold_ms: int,
) -> str:
    remote = getattr(peer, "send_key", None)
    if callable(remote):
        return str(remote(key, hold_ms))
    return local_send_key(source_root, peer, key, hold_ms)


def _click(
    source_root: Path,
    peer: WindowsPeer,
    x: float,
    y: float,
    hold_ms: int,
) -> str:
    remote = getattr(peer, "click", None)
    if callable(remote):
        return str(remote(x, y, hold_ms))
    return local_click(source_root, peer, x, y, hold_ms)


STATE_LUA = r"""
local output = {}
local function emit(key, value)
  if value == nil then value = "" end
  output[#output + 1] = key .. "=" .. tostring(value)
end
local function safe_call(fn)
  if type(fn) ~= "function" then return nil end
  local ok, value = pcall(fn)
  if not ok then return nil end
  return value
end
local function emit_actor(prefix, actor)
  emit(prefix .. ".address", actor.actor_address or 0)
  emit(prefix .. ".network_id", actor.network_actor_id or 0)
  emit(prefix .. ".type", actor.object_type_id or actor.native_type_id or 0)
  emit(prefix .. ".enemy_type", actor.enemy_type or 0)
  emit(prefix .. ".tracked_enemy", actor.tracked_enemy or false)
  emit(prefix .. ".dead", actor.dead or false)
  emit(prefix .. ".x", actor.x or actor.position_x or 0)
  emit(prefix .. ".y", actor.y or actor.position_y or 0)
  emit(prefix .. ".heading", actor.heading or 0)
  emit(prefix .. ".hp", actor.hp or 0)
  emit(prefix .. ".max_hp", actor.max_hp or 0)
  emit(prefix .. ".anim", actor.anim_drive_state or 0)
  if sd.draw and sd.draw.world_to_screen then
    local projected = sd.draw.world_to_screen(
      actor.x or actor.position_x or 0,
      actor.y or actor.position_y or 0)
    emit(prefix .. ".screen_valid",
      projected ~= nil and projected.visible == true)
    emit(prefix .. ".screen_x", projected and projected.x or 0)
    emit(prefix .. ".screen_y", projected and projected.y or 0)
  end
end

local scene = safe_call(sd.world and sd.world.get_scene)
local world = safe_call(sd.world and sd.world.get_state)
local player = safe_call(sd.player and sd.player.get_state)
local wave = safe_call(sd.waves and sd.waves.get_state)
local combat = safe_call(
  sd.gameplay and sd.gameplay.get_combat_state)
local mp = safe_call(
  sd.runtime and sd.runtime.get_multiplayer_state)
local replicated = safe_call(
  sd.world and sd.world.get_replicated_actors)
local solomon = safe_call(
  sd.hub and sd.hub.get_solomon_dig_state)
local camera = safe_call(sd.camera and sd.camera.get_state)
local viewport = safe_call(sd.draw and sd.draw.get_viewport)
local actors = safe_call(sd.world and sd.world.list_actors) or {}

emit("scene.name", scene and (scene.name or scene.kind) or "")
emit("scene.kind", scene and scene.kind or "")
emit("scene.id", scene and scene.id or 0)
emit("world.run_active", world and world.run_active or false)
emit("world.combat_active", world and world.combat_active or false)
emit("world.wave_index", world and world.wave_index or 0)
emit("world.wave_counter", world and world.wave_counter or 0)
emit("viewport.width", viewport and viewport.width or 0)
emit("viewport.height", viewport and viewport.height or 0)
emit("camera.available", camera and camera.available or false)
emit(
  "camera.scene_available",
  camera and camera.scene_available or false)
emit("camera.origin_x", camera and camera.origin_x or 0)
emit("camera.origin_y", camera and camera.origin_y or 0)
emit("camera.width", camera and camera.width or 0)
emit("camera.height", camera and camera.height or 0)
emit("camera.center_x", camera and camera.center_x or 0)
emit("camera.center_y", camera and camera.center_y or 0)
emit("camera.scale", camera and camera.scale or 0)

emit("player.valid", player ~= nil)
emit("player.address", player and player.actor_address or 0)
emit("player.x", player and player.x or 0)
emit("player.y", player and player.y or 0)
emit("player.heading", player and player.heading or 0)
emit("player.hp", player and player.hp or 0)
emit("player.max_hp", player and player.max_hp or 0)

emit("wave.valid", wave ~= nil)
emit("wave.index", wave and wave.wave or 0)
emit("wave.phase", wave and wave.phase or "")
emit("wave.remaining", wave and wave.remaining_to_spawn or 0)
emit("wave.spawned", wave and wave.spawned or 0)
emit("wave.alive", wave and wave.alive or 0)
emit("wave.killed", wave and wave.killed or 0)
emit("wave.planned", wave and wave.planned or 0)
emit("combat.valid", combat ~= nil)
emit("combat.section", combat and combat.section_index or 0)
emit("combat.wave_index", combat and combat.wave_index or 0)
emit("combat.wave_counter", combat and combat.wave_counter or 0)
emit("combat.wait_ticks", combat and combat.wait_ticks or 0)
emit("combat.transition_requested",
  combat and combat.transition_requested or false)
emit("combat.active", combat and combat.active or false)

emit("mp.valid", mp ~= nil)
emit("mp.foundation_ready", mp and mp.foundation_ready or false)
emit("mp.transport_ready", mp and mp.transport_ready or false)
emit("mp.session_status", mp and mp.session_status or "")
emit("mp.session_transport", mp and mp.session_transport or "")
emit("mp.session_state", mp and mp.session_state or "")
emit("mp.local_steam_id", mp and mp.local_steam_id or 0)
emit("mp.participant_count", mp and mp.participant_count or 0)
emit("mp.packets_sent", mp and mp.transport_packets_sent or 0)
emit("mp.packets_received", mp and mp.transport_packets_received or 0)
emit("mp.steam_send_failures", mp and mp.steam_send_failures or 0)
emit("mp.steam_reliable_send_failures",
  mp and mp.steam_reliable_send_failures or 0)
emit("mp.last_steam_send_failure_result",
  mp and mp.last_steam_send_failure_result or 0)
local loading = mp and mp.loading_screen or nil
emit("loading.active", loading and loading.active or false)
emit("loading.flow", loading and loading.flow or 0)
emit("loading.stage", loading and loading.stage or 0)
emit("loading.progress", loading and loading.progress or 0)
emit("loading.sequence", loading and loading.sequence or 0)
emit("loading.stage_id", loading and loading.stage_id or "")
emit("loading.label", loading and loading.label or "")
for index, participant in ipairs(mp and mp.participants or {}) do
  if index > 8 then break end
  local prefix = "participant." .. tostring(index)
  emit(prefix .. ".id", participant.participant_id or 0)
  emit(prefix .. ".name", participant.name or "")
  emit(prefix .. ".owner", participant.is_owner or false)
  emit(prefix .. ".ready", participant.ready or false)
  emit(prefix .. ".connected", participant.transport_connected or false)
  emit(prefix .. ".runtime_valid", participant.runtime_valid or false)
  emit(prefix .. ".in_run", participant.in_run or false)
  emit(prefix .. ".run_nonce", participant.run_nonce or 0)
  emit(prefix .. ".wave", participant.wave or 0)
  emit(prefix .. ".scene_kind", participant.scene_kind or "")
  emit(prefix .. ".x", participant.x or 0)
  emit(prefix .. ".y", participant.y or 0)
  emit(prefix .. ".hp", participant.life_current or 0)
end

emit("solomon.valid", solomon and solomon.valid or false)
emit("solomon.address", solomon and solomon.actor_address or 0)
emit("solomon.x", solomon and solomon.x or 0)
emit("solomon.y", solomon and solomon.y or 0)
emit("solomon.state", solomon and solomon.interaction_state or -1)
emit("solomon.acquired", solomon and solomon.participant_acquired or false)
emit("solomon.target_slot", solomon and solomon.target_gameplay_slot or -1)

emit("replicated.valid", replicated ~= nil)
emit("replicated.authority_id",
  replicated and replicated.authority_participant_id or 0)
emit("replicated.received_ms", replicated and replicated.received_ms or 0)
emit("replicated.sequence", replicated and replicated.sequence or 0)
emit("replicated.scene_epoch", replicated and replicated.scene_epoch or 0)
emit("replicated.run_nonce", replicated and replicated.run_nonce or 0)
emit("replicated.scene_kind", replicated and replicated.scene_kind or "")
emit("replicated.actor_count", replicated and replicated.actor_count or 0)
emit("replicated.actor_total_count",
  replicated and replicated.actor_total_count or 0)
emit("replicated.apply_valid", replicated and replicated.apply_valid or false)
emit("replicated.apply_sequence",
  replicated and replicated.apply_sequence or 0)
emit("replicated.apply_scene_epoch",
  replicated and replicated.apply_scene_epoch or 0)
emit("replicated.apply_holding_stale",
  replicated and replicated.apply_holding_stale_snapshot or false)
emit("replicated.local_actor_count",
  replicated and replicated.local_actor_count or 0)
emit("replicated.matched_actor_count",
  replicated and replicated.matched_actor_count or 0)
emit("replicated.created_actor_count",
  replicated and replicated.created_actor_count or 0)
emit("replicated.parked_actor_count",
  replicated and replicated.parked_actor_count or 0)
emit("replicated.binding_count",
  replicated and replicated.binding_count or 0)

local replicated_enemy_count = 0
local replicated_enemy_ids = {}
for _, actor in ipairs(replicated and replicated.actors or {}) do
  if actor.tracked_enemy then
    replicated_enemy_count = replicated_enemy_count + 1
    replicated_enemy_ids[tonumber(actor.network_actor_id or 0)] = true
    if replicated_enemy_count <= 64 then
      emit_actor(
        "replicated_enemy." .. tostring(replicated_enemy_count),
        actor)
    end
  end
end
emit("replicated_enemy.count", replicated_enemy_count)

local matched_enemy_count = 0
local network_id_by_native_address = {}
for _, binding in ipairs(replicated and replicated.bindings or {}) do
  local network_id = tonumber(binding.network_actor_id or 0)
  if replicated_enemy_ids[network_id] then
    matched_enemy_count = matched_enemy_count + 1
    local local_address = tonumber(binding.local_actor_address or 0)
    if local_address ~= 0 then
      network_id_by_native_address[local_address] = network_id
    end
    if matched_enemy_count <= 64 then
      local prefix = "binding_enemy." .. tostring(matched_enemy_count)
      emit(prefix .. ".network_id", network_id)
      emit(prefix .. ".address", local_address)
      emit(prefix .. ".type", binding.object_type_id or 0)
      emit(prefix .. ".enemy_type", binding.enemy_type or 0)
      emit(prefix .. ".matched", binding.matched or false)
      emit(prefix .. ".parked", binding.parked or false)
      emit(prefix .. ".removed", binding.removed or false)
      emit(prefix .. ".x", binding.sampled_position_x or 0)
      emit(prefix .. ".y", binding.sampled_position_y or 0)
    end
  end
end
emit("binding_enemy.count", matched_enemy_count)

local native_enemy_count = 0
for _, actor in ipairs(actors) do
  if actor.tracked_enemy then
    native_enemy_count = native_enemy_count + 1
    if native_enemy_count <= 64 then
      local prefix = "native_enemy." .. tostring(native_enemy_count)
      emit_actor(prefix, actor)
      emit(
        prefix .. ".network_id",
        network_id_by_native_address[
          tonumber(actor.actor_address or 0)] or 0)
    end
  end
end
emit("native_enemy.count", native_enemy_count)
return table.concat(output, "\n")
"""

NAV_GRID_LUA = r"""
local output = {}
local function emit(key, value)
  output[#output + 1] = key .. "=" .. tostring(value)
end
local grid = sd.nav and sd.nav.get_grid and sd.nav.get_grid(2) or nil
emit("valid", grid ~= nil)
if grid ~= nil then
  emit("width", grid.width or 0)
  emit("height", grid.height or 0)
  emit("cell_width", grid.cell_width or 0)
  emit("cell_height", grid.cell_height or 0)
  emit("subdivisions", grid.subdivisions or 0)
  emit("requested_subdivisions", grid.requested_subdivisions or 0)
  emit("refresh_pending", grid.refresh_pending or false)
  local subdivisions = tonumber(grid.subdivisions) or 1
  for _, cell in ipairs(grid.cells or {}) do
    for _, sample in ipairs(cell.samples or {}) do
      if sample.traversable then
        local node_x =
          (tonumber(cell.grid_y) or 0) * subdivisions +
          (tonumber(sample.sample_y) or 0)
        local node_y =
          (tonumber(cell.grid_x) or 0) * subdivisions +
          (tonumber(sample.sample_x) or 0)
        output[#output + 1] = string.format(
          "node=%d,%d,%.6f,%.6f",
          node_x,
          node_y,
          tonumber(sample.world_x) or 0,
          tonumber(sample.world_y) or 0)
      end
    end
  end
end
return table.concat(output, "\n")
"""

OPENABLES_LUA = r"""
local output = {}
local function emit(key, value)
  output[#output + 1] = key .. "=" .. tostring(value)
end
local obstacles =
  sd.debug and sd.debug.list_openable_path_obstacles and
  sd.debug.list_openable_path_obstacles() or {}
emit("count", #obstacles)
for index, obstacle in ipairs(obstacles) do
  output[#output + 1] = string.format(
    "obstacle=%d,%d,%.6f,%.6f,%.6f,%.6f",
    tonumber(obstacle.object_address) or 0,
    tonumber(obstacle.collision_record_address) or 0,
    tonumber(obstacle.start_x) or 0,
    tonumber(obstacle.start_y) or 0,
    tonumber(obstacle.end_x) or 0,
    tonumber(obstacle.end_y) or 0)
end
return table.concat(output, "\n")
"""


def parse_key_values(output: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _integer(values: dict[str, str], key: str) -> int:
    try:
        return int(float(values.get(key, "0")))
    except (TypeError, ValueError):
        return 0


def _number(values: dict[str, str], key: str) -> float:
    try:
        value = float(values.get(key, "nan"))
    except (TypeError, ValueError):
        return math.nan
    return value if math.isfinite(value) else math.nan


def _boolean(values: dict[str, str], key: str) -> bool:
    return values.get(key, "").casefold() == "true"


def _rows(
    values: dict[str, str],
    prefix: str,
    count_key: str,
    fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index in range(1, _integer(values, count_key) + 1):
        row: dict[str, Any] = {}
        for field in fields:
            value = values.get(f"{prefix}.{index}.{field}", "")
            if field in {
                "tracked_enemy",
                "dead",
                "screen_valid",
                "owner",
                "ready",
                "connected",
                "runtime_valid",
                "in_run",
                "matched",
                "parked",
                "removed",
            }:
                row[field] = value.casefold() == "true"
            elif field in {"name", "scene_kind"}:
                row[field] = value
            elif field in {
                "x",
                "y",
                "heading",
                "hp",
                "max_hp",
                "screen_x",
                "screen_y",
            }:
                try:
                    row[field] = float(value or 0)
                except ValueError:
                    row[field] = 0.0
            else:
                try:
                    row[field] = int(float(value or 0))
                except ValueError:
                    row[field] = 0
        rows.append(row)
    return rows


def normalize_state(values: dict[str, str]) -> dict[str, Any]:
    actor_fields = (
        "address",
        "network_id",
        "type",
        "enemy_type",
        "tracked_enemy",
        "dead",
        "x",
        "y",
        "heading",
        "hp",
        "max_hp",
        "anim",
        "screen_valid",
        "screen_x",
        "screen_y",
    )
    participant_fields = (
        "id",
        "name",
        "owner",
        "ready",
        "connected",
        "runtime_valid",
        "in_run",
        "run_nonce",
        "wave",
        "scene_kind",
        "x",
        "y",
        "hp",
    )
    binding_fields = (
        "network_id",
        "address",
        "type",
        "enemy_type",
        "matched",
        "parked",
        "removed",
        "x",
        "y",
    )
    return {
        "scene": {
            "name": values.get("scene.name", ""),
            "kind": values.get("scene.kind", ""),
            "id": _integer(values, "scene.id"),
        },
        "world": {
            "runActive": _boolean(values, "world.run_active"),
            "combatActive": _boolean(values, "world.combat_active"),
            "waveIndex": _integer(values, "world.wave_index"),
            "waveCounter": _integer(values, "world.wave_counter"),
        },
        "viewport": {
            "width": _integer(values, "viewport.width"),
            "height": _integer(values, "viewport.height"),
        },
        "camera": {
            "available": _boolean(values, "camera.available"),
            "sceneAvailable": _boolean(
                values, "camera.scene_available"
            ),
            "originX": _number(values, "camera.origin_x"),
            "originY": _number(values, "camera.origin_y"),
            "width": _number(values, "camera.width"),
            "height": _number(values, "camera.height"),
            "centerX": _number(values, "camera.center_x"),
            "centerY": _number(values, "camera.center_y"),
            "scale": _number(values, "camera.scale"),
        },
        "player": {
            "valid": _boolean(values, "player.valid"),
            "address": _integer(values, "player.address"),
            "x": _number(values, "player.x"),
            "y": _number(values, "player.y"),
            "heading": _number(values, "player.heading"),
            "hp": _number(values, "player.hp"),
            "maxHp": _number(values, "player.max_hp"),
        },
        "wave": {
            "valid": _boolean(values, "wave.valid"),
            "index": _integer(values, "wave.index"),
            "phase": values.get("wave.phase", ""),
            "remaining": _integer(values, "wave.remaining"),
            "spawned": _integer(values, "wave.spawned"),
            "alive": _integer(values, "wave.alive"),
            "killed": _integer(values, "wave.killed"),
            "planned": _integer(values, "wave.planned"),
        },
        "combat": {
            "valid": _boolean(values, "combat.valid"),
            "section": _integer(values, "combat.section"),
            "waveIndex": _integer(values, "combat.wave_index"),
            "waveCounter": _integer(values, "combat.wave_counter"),
            "waitTicks": _integer(values, "combat.wait_ticks"),
            "transitionRequested": _boolean(
                values, "combat.transition_requested"
            ),
            "active": _boolean(values, "combat.active"),
        },
        "multiplayer": {
            "valid": _boolean(values, "mp.valid"),
            "foundationReady": _boolean(values, "mp.foundation_ready"),
            "transportReady": _boolean(values, "mp.transport_ready"),
            "sessionStatus": values.get("mp.session_status", ""),
            "sessionTransport": values.get("mp.session_transport", ""),
            "sessionState": values.get("mp.session_state", ""),
            "localSteamId": _integer(values, "mp.local_steam_id"),
            "participantCount": _integer(values, "mp.participant_count"),
            "packetsSent": _integer(values, "mp.packets_sent"),
            "packetsReceived": _integer(values, "mp.packets_received"),
            "steamSendFailures": _integer(
                values, "mp.steam_send_failures"
            ),
            "steamReliableSendFailures": _integer(
                values, "mp.steam_reliable_send_failures"
            ),
            "lastSteamSendFailureResult": _integer(
                values, "mp.last_steam_send_failure_result"
            ),
            "participants": _rows(
                values,
                "participant",
                "mp.participant_count",
                participant_fields,
            ),
        },
        "loadingScreen": {
            "active": _boolean(values, "loading.active"),
            "flow": _integer(values, "loading.flow"),
            "stage": _integer(values, "loading.stage"),
            "progress": _number(values, "loading.progress"),
            "sequence": _integer(values, "loading.sequence"),
            "stageId": values.get("loading.stage_id", ""),
            "label": values.get("loading.label", ""),
        },
        "solomon": {
            "valid": _boolean(values, "solomon.valid"),
            "address": _integer(values, "solomon.address"),
            "x": _number(values, "solomon.x"),
            "y": _number(values, "solomon.y"),
            "state": _integer(values, "solomon.state"),
            "acquired": _boolean(values, "solomon.acquired"),
            "targetSlot": _integer(values, "solomon.target_slot"),
        },
        "replicated": {
            "valid": _boolean(values, "replicated.valid"),
            "authorityId": _integer(values, "replicated.authority_id"),
            "receivedMs": _integer(values, "replicated.received_ms"),
            "sequence": _integer(values, "replicated.sequence"),
            "sceneEpoch": _integer(values, "replicated.scene_epoch"),
            "runNonce": _integer(values, "replicated.run_nonce"),
            "sceneKind": values.get("replicated.scene_kind", ""),
            "actorCount": _integer(values, "replicated.actor_count"),
            "actorTotalCount": _integer(
                values, "replicated.actor_total_count"
            ),
            "applyValid": _boolean(values, "replicated.apply_valid"),
            "applySequence": _integer(
                values, "replicated.apply_sequence"
            ),
            "applySceneEpoch": _integer(
                values, "replicated.apply_scene_epoch"
            ),
            "holdingStale": _boolean(
                values, "replicated.apply_holding_stale"
            ),
            "localActorCount": _integer(
                values, "replicated.local_actor_count"
            ),
            "matchedActorCount": _integer(
                values, "replicated.matched_actor_count"
            ),
            "createdActorCount": _integer(
                values, "replicated.created_actor_count"
            ),
            "parkedActorCount": _integer(
                values, "replicated.parked_actor_count"
            ),
            "bindingCount": _integer(values, "replicated.binding_count"),
        },
        "nativeEnemies": _rows(
            values,
            "native_enemy",
            "native_enemy.count",
            actor_fields,
        ),
        "replicatedEnemies": _rows(
            values,
            "replicated_enemy",
            "replicated_enemy.count",
            actor_fields,
        ),
        "enemyBindings": _rows(
            values,
            "binding_enemy",
            "binding_enemy.count",
            binding_fields,
        ),
    }


@dataclass
class LuaPipe:
    source_root: Path
    name: str
    timeout_seconds: float = 8.0

    def execute(self, code: str) -> str:
        try:
            completed = subprocess.run(
                [
                    "powershell.exe",
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    "scripts/Invoke-LuaExec.ps1",
                    "-PipeName",
                    self.name,
                    "-ResponseTimeoutMilliseconds",
                    str(max(100, round(self.timeout_seconds * 1000))),
                ],
                input=code,
                cwd=self.source_root,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=self.timeout_seconds + 7.0,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeProbeError(
                f"Lua pipe {self.name} bridge timed out after "
                f"{self.timeout_seconds + 7.0:.1f}s"
            ) from exc
        if completed.returncode != 0:
            raise RuntimeProbeError(
                f"Lua pipe {self.name} failed ({completed.returncode}): "
                f"{completed.stdout.strip()}"
            )
        return completed.stdout

    def state(self) -> dict[str, Any]:
        return normalize_state(parse_key_values(self.execute(STATE_LUA)))

    def reset_local_cast_observation(self, network_actor_id: int) -> bool:
        if network_actor_id <= 0:
            raise RuntimeProbeError(
                "local cast observation requires a nonzero network actor ID"
            )
        output = self.execute(
            "local armed = "
            "sd.debug.reset_local_cast_observation("
            f"{network_actor_id})\n"
            'return "armed=" .. tostring(armed)'
        )
        return _boolean(parse_key_values(output), "armed")

    def take_local_cast_observation(
        self,
        network_actor_id: int,
    ) -> dict[str, Any]:
        if network_actor_id <= 0:
            raise RuntimeProbeError(
                "local cast observation requires a nonzero network actor ID"
            )
        output = self.execute(
            "local observation = "
            "sd.debug.get_local_cast_observation("
            f"{network_actor_id})\n"
            "local output = {}\n"
            "local function emit(key, value)\n"
            "  output[#output + 1] = key .. '=' .. tostring(value)\n"
            "end\n"
            "for key, value in pairs(observation) do\n"
            "  if type(value) ~= 'table' then emit(key, value) end\n"
            "end\n"
            "for index, value in ipairs("
            "observation.damage_native_contact_samples or {}) do\n"
            "  emit('native_sample.' .. tostring(index), value)\n"
            "end\n"
            "for index, value in ipairs("
            "observation.damage_claim_samples or {}) do\n"
            "  emit('claim_sample.' .. tostring(index), value)\n"
            "end\n"
            "return table.concat(output, '\\n')"
        )
        values = parse_key_values(output)
        native_sample_count = _integer(
            values,
            "damage_native_contact_sample_count",
        )
        claim_sample_count = _integer(
            values,
            "damage_claim_sample_count",
        )
        return {
            "manaValid": _boolean(values, "mana_valid"),
            "manaSpentTotal": _number(values, "mana_spent_total"),
            "damageClaimValid": _boolean(
                values,
                "damage_claim_valid",
            ),
            "nativeContactCount": _integer(
                values,
                "damage_native_contact_count",
            ),
            "nativeContactSkillId": _integer(
                values,
                "damage_native_contact_skill_id",
            ),
            "nativeContactSkillConsistent": _boolean(
                values,
                "damage_native_contact_skill_consistent",
            ),
            "nativeContactTotal": _number(
                values,
                "damage_native_contact_total",
            ),
            "nativeContactMinimum": _number(
                values,
                "damage_native_contact_minimum",
            ),
            "nativeContactMaximum": _number(
                values,
                "damage_native_contact_maximum",
            ),
            "nativeContactSamples": [
                _number(values, f"native_sample.{index}")
                for index in range(1, native_sample_count + 1)
            ],
            "claimCount": _integer(values, "damage_claim_count"),
            "associatedClaimCount": _integer(
                values,
                "damage_associated_claim_count",
            ),
            "unassociatedClaimCount": _integer(
                values,
                "damage_unassociated_claim_count",
            ),
            "associatedSkillId": _integer(
                values,
                "damage_associated_skill_id",
            ),
            "associatedSkillConsistent": _boolean(
                values,
                "damage_associated_skill_consistent",
            ),
            "claimedTotal": _number(
                values,
                "damage_claimed_total",
            ),
            "claimedMinimum": _number(
                values,
                "damage_claimed_minimum",
            ),
            "claimedMaximum": _number(
                values,
                "damage_claimed_maximum",
            ),
            "claimSamples": [
                _number(values, f"claim_sample.{index}")
                for index in range(1, claim_sample_count + 1)
            ],
        }

    def navigation_grid(self, *, timeout: float = 8.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        last: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            output = self.execute(NAV_GRID_LUA)
            values = parse_key_values(output)
            nodes: dict[tuple[int, int], tuple[float, float]] = {}
            for line in output.splitlines():
                if not line.startswith("node="):
                    continue
                parts = line[5:].split(",")
                if len(parts) != 4:
                    continue
                try:
                    key = (int(parts[0]), int(parts[1]))
                    nodes[key] = (float(parts[2]), float(parts[3]))
                except ValueError:
                    continue
            last = {
                "valid": _boolean(values, "valid"),
                "width": _integer(values, "width"),
                "height": _integer(values, "height"),
                "cellWidth": _number(values, "cell_width"),
                "cellHeight": _number(values, "cell_height"),
                "subdivisions": _integer(values, "subdivisions"),
                "requestedSubdivisions": _integer(
                    values,
                    "requested_subdivisions",
                ),
                "refreshPending": _boolean(values, "refresh_pending"),
                "nodes": nodes,
            }
            if (
                last["valid"]
                and not last["refreshPending"]
                and last["subdivisions"] == 2
                and nodes
            ):
                return last
            time.sleep(0.15)
        raise RuntimeProbeError(
            f"native navigation grid did not settle: {last}"
        )

    def openable_path_obstacles(self) -> list[dict[str, Any]]:
        output = self.execute(OPENABLES_LUA)
        obstacles: list[dict[str, Any]] = []
        for line in output.splitlines():
            if not line.startswith("obstacle="):
                continue
            parts = line[9:].split(",")
            if len(parts) != 6:
                continue
            try:
                obstacles.append(
                    {
                        "object": int(parts[0]),
                        "record": int(parts[1]),
                        "start": (float(parts[2]), float(parts[3])),
                        "end": (float(parts[4]), float(parts[5])),
                    }
                )
            except ValueError:
                continue
        return obstacles


def wait_for_state(
    pipe: LuaPipe,
    predicate: Callable[[dict[str, Any]], bool],
    *,
    timeout: float,
    interval: float = 0.2,
    label: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    last_error = ""
    while time.monotonic() < deadline:
        try:
            last = pipe.state()
            if predicate(last):
                return last
        except RuntimeProbeError as exc:
            last_error = str(exc)
        time.sleep(interval)
    raise RuntimeProbeError(
        f"{label} timed out; last={json.dumps(last, sort_keys=True)} "
        f"error={last_error!r}"
    )


def wait_shared_hub(
    host_pipe: LuaPipe,
    client_pipe: LuaPipe,
    *,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    converged_since: float | None = None
    while time.monotonic() < deadline:
        try:
            host = host_pipe.state()
            client = client_pipe.state()
            last = {"host": host, "clientB": client}
            if shared_hub_views_converged(host, client):
                now = time.monotonic()
                if converged_since is None:
                    converged_since = now
                elif now - converged_since >= 2.0:
                    return last
            else:
                converged_since = None
        except RuntimeProbeError:
            converged_since = None
        time.sleep(0.2)
    raise RuntimeProbeError(
        "both real launcher peers did not materialize in the shared hub: "
        + json.dumps(last, sort_keys=True)
    )


def shared_hub_views_converged(
    host: dict[str, Any],
    client: dict[str, Any],
) -> bool:
    states = (host, client)
    if any(
        state["scene"]["kind"] != "hub"
        or state["loadingScreen"]["active"]
        or state["multiplayer"]["sessionState"] != "in-hub"
        or state["multiplayer"]["sessionStatus"] != "Ready"
        or state["multiplayer"]["participantCount"] < 2
        for state in states
    ):
        return False

    participant_views: list[dict[str, dict[str, Any]]] = []
    for state in states:
        participants = {
            str(participant["name"]): participant
            for participant in state["multiplayer"]["participants"]
        }
        if (
            len(participants) < 2
            or any(
                not participant["connected"]
                or not participant["ready"]
                or participant["in_run"]
                or participant["scene_kind"] != "SharedHub"
                for participant in participants.values()
            )
        ):
            return False
        participant_views.append(participants)

    if participant_views[0].keys() != participant_views[1].keys():
        return False
    return all(
        _distance(
            float(participant_views[0][participant_name]["x"]),
            float(participant_views[0][participant_name]["y"]),
            float(participant_views[1][participant_name]["x"]),
            float(participant_views[1][participant_name]["y"]),
        )
        <= 4.0
        for participant_name in participant_views[0]
    )


def execute_actions(
    source_root: Path,
    peer: WindowsPeer,
    pipe: LuaPipe,
    actions: tuple[InputAction, ...],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for index, action in enumerate(actions):
        started = time.time_ns()
        if action.kind == "key":
            detail = _send_key(
                source_root,
                peer,
                action.key,
                action.hold_ms,
            )
        elif action.kind == "click":
            detail = _click(
                source_root,
                peer,
                action.x,
                action.y,
                action.hold_ms,
            )
        elif action.kind == "walk_to":
            detail = navigate_to(
                source_root,
                peer,
                pipe,
                action.target_x,
                action.target_y,
                tolerance=action.tolerance,
                timeout=action.timeout_seconds,
            )
        else:
            detail = wait_for_state(
                pipe,
                lambda state, scene=action.scene: (
                    state["scene"]["name"] == scene
                    or state["scene"]["kind"] == scene
                ),
                timeout=action.timeout_seconds,
                label=f"wait_scene {action.scene}",
            )
        results.append(
            {
                "index": index,
                "kind": action.kind,
                "startedUtcNanoseconds": started,
                "endedUtcNanoseconds": time.time_ns(),
                "detail": detail,
            }
        )
    return results


def _distance(
    first_x: float,
    first_y: float,
    second_x: float,
    second_y: float,
) -> float:
    return math.hypot(first_x - second_x, first_y - second_y)


def navigate_to(
    source_root: Path,
    peer: WindowsPeer,
    pipe: LuaPipe,
    target_x: float,
    target_y: float,
    *,
    tolerance: float,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    samples: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        state = pipe.state()
        player = state["player"]
        distance = _distance(
            player["x"],
            player["y"],
            target_x,
            target_y,
        )
        samples.append(
            {
                "x": player["x"],
                "y": player["y"],
                "distance": distance,
            }
        )
        if distance <= tolerance:
            return {
                "target": [target_x, target_y],
                "tolerance": tolerance,
                "samples": samples,
            }
        dx = target_x - player["x"]
        dy = target_y - player["y"]
        if abs(dx) >= abs(dy):
            key = "d" if dx > 0 else "a"
            component = abs(dx)
        else:
            key = "s" if dy > 0 else "w"
            component = abs(dy)
        hold_ms = max(80, min(700, round(component * 1.4)))
        _send_key(source_root, peer, key, hold_ms)
    raise RuntimeProbeError(
        f"real-input navigation did not reach {target_x},{target_y}; "
        f"last={samples[-1] if samples else None}"
    )


def plan_navigation_path(
    grid: dict[str, Any],
    start_x: float,
    start_y: float,
    target_x: float,
    target_y: float,
) -> dict[str, Any]:
    nodes: dict[tuple[int, int], tuple[float, float]] = grid["nodes"]
    start = min(
        nodes,
        key=lambda key: _distance(
            start_x,
            start_y,
            nodes[key][0],
            nodes[key][1],
        ),
    )
    queue: deque[tuple[int, int]] = deque([start])
    parent: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    while queue:
        current = queue.popleft()
        for delta_x, delta_y in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            neighbor = (current[0] + delta_x, current[1] + delta_y)
            if neighbor in nodes and neighbor not in parent:
                parent[neighbor] = current
                queue.append(neighbor)
    goal = min(
        parent,
        key=lambda key: _distance(
            target_x,
            target_y,
            nodes[key][0],
            nodes[key][1],
        ),
    )
    goal_distance = _distance(
        target_x,
        target_y,
        nodes[goal][0],
        nodes[goal][1],
    )
    if goal_distance > max(grid["cellWidth"], grid["cellHeight"]) * 2.5:
        raise RuntimeProbeError(
            "native navigation grid has no reachable Solomon approach: "
            f"closestDistance={goal_distance:.3f}"
        )
    keys: list[tuple[int, int]] = []
    current: tuple[int, int] | None = goal
    while current is not None:
        keys.append(current)
        current = parent[current]
    keys.reverse()
    waypoint_indices = {len(keys) - 1}
    waypoint_indices.update(range(2, len(keys), 2))
    for index, key in enumerate(keys):
        if index == 0 or index == len(keys) - 1:
            continue
        previous = keys[index - 1]
        following = keys[index + 1]
        before = (key[0] - previous[0], key[1] - previous[1])
        after = (following[0] - key[0], following[1] - key[1])
        if before != after:
            waypoint_indices.add(index)
    return {
        "startNode": list(start),
        "goalNode": list(goal),
        "goalDistance": goal_distance,
        "visitedNodeCount": len(parent),
        "nodeCount": len(nodes),
        "pathNodeCount": len(keys),
        "waypoints": [
            {
                "node": list(key),
                "x": nodes[key][0],
                "y": nodes[key][1],
            }
            for index, key in enumerate(keys)
            if index in waypoint_indices and index > 0
        ],
    }


def plan_openable_gate_route(
    obstacles: list[dict[str, Any]],
    start_x: float,
    start_y: float,
    target_x: float,
    target_y: float,
) -> dict[str, Any] | None:
    route_dx = target_x - start_x
    route_dy = target_y - start_y
    route_length = math.hypot(route_dx, route_dy)
    if route_length <= 0.001:
        return None
    route_x = route_dx / route_length
    route_y = route_dy / route_length
    candidates: list[tuple[float, float, dict[str, Any]]] = []
    for obstacle in obstacles:
        midpoint = (
            (obstacle["start"][0] + obstacle["end"][0]) * 0.5,
            (obstacle["start"][1] + obstacle["end"][1]) * 0.5,
        )
        relative_x = midpoint[0] - start_x
        relative_y = midpoint[1] - start_y
        projection = relative_x * route_x + relative_y * route_y
        perpendicular = abs(
            relative_x * -route_y + relative_y * route_x
        )
        if 40.0 < projection < route_length - 80.0:
            candidates.append((perpendicular, projection, obstacle))
    if not candidates:
        return None
    candidates.sort(key=lambda row: (row[0], row[1]))
    anchor = candidates[0][2]
    anchor_midpoint = (
        (anchor["start"][0] + anchor["end"][0]) * 0.5,
        (anchor["start"][1] + anchor["end"][1]) * 0.5,
    )
    cluster = [
        obstacle
        for _, _, obstacle in candidates
        if _distance(
            anchor_midpoint[0],
            anchor_midpoint[1],
            (obstacle["start"][0] + obstacle["end"][0]) * 0.5,
            (obstacle["start"][1] + obstacle["end"][1]) * 0.5,
        )
        <= 140.0
    ]
    endpoints = [
        point
        for obstacle in cluster
        for point in (obstacle["start"], obstacle["end"])
    ]
    midpoint = (
        sum(point[0] for point in endpoints) / len(endpoints),
        sum(point[1] for point in endpoints) / len(endpoints),
    )
    reference = max(
        (
            (
                obstacle["end"][0] - obstacle["start"][0],
                obstacle["end"][1] - obstacle["start"][1],
            )
            for obstacle in cluster
        ),
        key=lambda vector: math.hypot(vector[0], vector[1]),
    )
    reference_length = math.hypot(reference[0], reference[1])
    reference_x = reference[0] / reference_length
    reference_y = reference[1] / reference_length
    tangent_x = 0.0
    tangent_y = 0.0
    for obstacle in cluster:
        vector_x = obstacle["end"][0] - obstacle["start"][0]
        vector_y = obstacle["end"][1] - obstacle["start"][1]
        vector_length = math.hypot(vector_x, vector_y)
        unit_x = vector_x / vector_length
        unit_y = vector_y / vector_length
        if unit_x * reference_x + unit_y * reference_y < 0.0:
            unit_x = -unit_x
            unit_y = -unit_y
        tangent_x += unit_x * vector_length
        tangent_y += unit_y * vector_length
    tangent_length = math.hypot(tangent_x, tangent_y)
    tangent_x /= tangent_length
    tangent_y /= tangent_length
    transit_x = -tangent_y
    transit_y = tangent_x
    if (
        (target_x - midpoint[0]) * transit_x
        + (target_y - midpoint[1]) * transit_y
        < 0.0
    ):
        transit_x = -transit_x
        transit_y = -transit_y
    approach_distance = 110.0
    exit_distance = 130.0
    waypoints = [
        {
            "kind": "gate-approach",
            "x": midpoint[0] - transit_x * approach_distance,
            "y": midpoint[1] - transit_y * approach_distance,
        },
        {
            "kind": "gate-crossing",
            "x": midpoint[0] + transit_x * exit_distance,
            "y": midpoint[1] + transit_y * exit_distance,
        },
        {
            "kind": "solomon-approach",
            "x": target_x - transit_x * 110.0,
            "y": target_y - transit_y * 110.0,
        },
    ]
    return {
        "kind": "native-openable-gate",
        "candidateCount": len(candidates),
        "clusterCount": len(cluster),
        "midpoint": list(midpoint),
        "transitUnit": [transit_x, transit_y],
        "segments": [
            {
                "object": obstacle["object"],
                "record": obstacle["record"],
                "start": list(obstacle["start"]),
                "end": list(obstacle["end"]),
            }
            for obstacle in cluster
        ],
        "waypoints": waypoints,
    }


def approach_solomon_and_complete_dialogue(
    source_root: Path,
    peer: WindowsPeer,
    pipe: LuaPipe,
    *,
    authority_pipe: LuaPipe | None = None,
    timeout: float,
) -> dict[str, Any]:
    target_pipe = authority_pipe or pipe
    target_initial = wait_for_state(
        target_pipe,
        lambda state: state["solomon"]["valid"],
        timeout=timeout,
        label="stock Solomon Dig actor",
    )
    local_initial = wait_for_state(
        pipe,
        lambda state: (
            state["scene"]["name"] == "testrun"
            and state["player"]["valid"]
        ),
        timeout=timeout,
        label="local Solomon Dig interactor",
    )
    initial = _merge_solomon_authority_state(
        local_initial,
        target_initial,
    )
    obstacles = pipe.openable_path_obstacles()
    gate_route = plan_openable_gate_route(
        obstacles,
        initial["player"]["x"],
        initial["player"]["y"],
        initial["solomon"]["x"],
        initial["solomon"]["y"],
    )
    grid: dict[str, Any] | None = None
    if gate_route is not None:
        path = gate_route
    else:
        grid = pipe.navigation_grid(timeout=min(15.0, timeout))
        path = plan_navigation_path(
            grid,
            initial["player"]["x"],
            initial["player"]["y"],
            initial["solomon"]["x"],
            initial["solomon"]["y"],
        )
    waypoints = list(path["waypoints"])
    waypoint_index = 0
    navigation_samples: list[dict[str, Any]] = []
    deadline = time.monotonic() + timeout
    acquired: dict[str, Any] | None = None
    best_distance = math.inf
    stalled_samples = 0
    detour_count = 0
    while time.monotonic() < deadline:
        local_state = pipe.state()
        authority_state = (
            local_state if target_pipe is pipe else target_pipe.state()
        )
        state = _merge_solomon_authority_state(
            local_state,
            authority_state,
        )
        solomon = state["solomon"]
        if (
            solomon["acquired"]
            or solomon["state"] >= 1
            or not solomon["valid"]
            or state["wave"]["index"] > 0
        ):
            acquired = state
            break
        player = state["player"]
        dx = solomon["x"] - player["x"]
        dy = solomon["y"] - player["y"]
        distance = math.hypot(dx, dy)
        waypoint = (
            waypoints[waypoint_index]
            if waypoint_index < len(waypoints)
            else None
        )
        navigation_samples.append(
            {
                "x": player["x"],
                "y": player["y"],
                "solomonX": solomon["x"],
                "solomonY": solomon["y"],
                "distance": distance,
                "waypointIndex": waypoint_index,
                "waypoint": waypoint,
            }
        )
        if waypoint is not None:
            waypoint_dx = waypoint["x"] - player["x"]
            waypoint_dy = waypoint["y"] - player["y"]
            waypoint_distance = math.hypot(waypoint_dx, waypoint_dy)
            waypoint_tolerance = max(
                35.0,
                (
                    min(grid["cellWidth"], grid["cellHeight"]) * 0.40
                    if grid is not None
                    else 45.0
                ),
            )
            if waypoint_distance <= waypoint_tolerance:
                waypoint_index += 1
                best_distance = math.inf
                stalled_samples = 0
                continue
            dx = waypoint_dx
            dy = waypoint_dy
            component = max(abs(dx), abs(dy))
            if abs(dx) >= abs(dy):
                key = "d" if dx > 0 else "a"
            else:
                key = "s" if dy > 0 else "w"
            _send_key(
                source_root,
                peer,
                key,
                max(80, min(2500, round(component * 10.0))),
            )
            continue
        if distance < best_distance - 2.0:
            best_distance = distance
            stalled_samples = 0
        else:
            stalled_samples += 1
        if stalled_samples >= 4:
            if abs(dx) >= abs(dy):
                detour_keys = ("w", "s") if dy > 0 else ("s", "w")
            else:
                detour_keys = ("a", "d") if dx > 0 else ("d", "a")
            _send_key(
                source_root,
                peer,
                detour_keys[detour_count % 2],
                1200,
            )
            detour_count += 1
            stalled_samples = 0
            best_distance = math.inf
            continue
        if abs(dx) >= abs(dy):
            key = "d" if dx > 0 else "a"
            component = abs(dx)
        else:
            key = "s" if dy > 0 else "w"
            component = abs(dy)
        _send_key(
            source_root,
            peer,
            key,
            max(50, min(1200, round(component * 2.0))),
        )
    if acquired is None:
        raise RuntimeProbeError(
            "host physical Solomon proximity timed out; "
            f"last={navigation_samples[-1] if navigation_samples else None}"
        )
    navigation = {
        "target": [initial["solomon"]["x"], initial["solomon"]["y"]],
        "nativeGrid": {
            key: value
            for key, value in (grid or {}).items()
            if key != "nodes"
        },
        "openableObstacleCount": len(obstacles),
        "plannedPath": path,
        "samples": navigation_samples,
        "detourCount": detour_count,
    }
    dialogue_samples: list[dict[str, Any]] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        local_state = pipe.state()
        authority_state = (
            local_state if target_pipe is pipe else target_pipe.state()
        )
        state = _merge_solomon_authority_state(
            local_state,
            authority_state,
        )
        dialogue_samples.append(
            {
                "timeUtcNanoseconds": time.time_ns(),
                "scene": state["scene"],
                "solomon": state["solomon"],
                "combat": state["combat"],
                "wave": state["wave"],
            }
        )
        if (
            not state["solomon"]["valid"]
            or state["wave"]["index"] > 0
            or state["combat"]["waveIndex"] > 0
        ):
            return {
                "initial": initial,
                "navigation": navigation,
                "acquired": acquired,
                "dialogueSamples": dialogue_samples,
                "completion": state,
            }
        # Stock narration uses the centered Done/continue surface at y=388
        # in the 640x480 logical viewport. This is real pointer input.
        if state["solomon"]["state"] <= 2:
            _click(source_root, peer, 0.5, 388.0 / 480.0, 300)
        time.sleep(0.35)
    raise RuntimeProbeError(
        "host stock Solomon dialogue did not reach native completion; "
        f"last={dialogue_samples[-1] if dialogue_samples else None}"
    )


def _merge_solomon_authority_state(
    local_state: dict[str, Any],
    authority_state: dict[str, Any],
) -> dict[str, Any]:
    if local_state is authority_state:
        return local_state
    return {
        **local_state,
        "solomon": authority_state["solomon"],
        "combat": authority_state["combat"],
        "wave": authority_state["wave"],
        "world": authority_state["world"],
    }


def enemy_motion_assertion(
    samples: list[dict[str, Any]],
) -> dict[str, Any]:
    by_id: dict[int, list[tuple[float, float, float, int]]] = {}
    for sample in samples:
        elapsed = float(sample["elapsedSeconds"])
        state = sample["clientB"]
        for enemy in state["replicatedEnemies"]:
            network_id = int(enemy["network_id"])
            if network_id:
                by_id.setdefault(network_id, []).append(
                    (
                        elapsed,
                        float(enemy["x"]),
                        float(enemy["y"]),
                        int(enemy["anim"]),
                    )
                )
    movement: list[dict[str, Any]] = []
    for network_id, rows in sorted(by_id.items()):
        if len(rows) < 2:
            continue
        first = rows[0]
        maximum = max(
            _distance(first[1], first[2], row[1], row[2])
            for row in rows[1:]
        )
        animation_states = sorted({row[3] for row in rows})
        movement.append(
            {
                "networkActorId": network_id,
                "sampleCount": len(rows),
                "maximumDisplacement": maximum,
                "animationStates": animation_states,
            }
        )
    accepted = [
        row
        for row in movement
        if row["maximumDisplacement"] >= 4.0
    ]
    if not accepted:
        raise RuntimeProbeError(
            "client B replicas did not move: "
            + json.dumps(movement, sort_keys=True)
        )
    return {"observed": movement, "accepted": accepted}


def enemy_attack_assertion(
    samples: list[dict[str, Any]],
) -> dict[str, Any]:
    combat_samples = [
        {
            "elapsedSeconds": float(sample["elapsedSeconds"]),
            "hp": float(sample["clientB"]["player"]["hp"]),
            "enemyAnimations": sorted(
                {
                    int(enemy["anim"])
                    for enemy in sample["clientB"]["replicatedEnemies"]
                    if not enemy["dead"]
                }
            ),
        }
        for sample in samples
        if sample["phase"] in {
            "first-enemy-spawn",
            "paired-render-capture",
            "client-real-damage",
            "enemy-motion",
        }
        and sample["clientB"]["player"]["valid"]
        and sample["clientB"]["replicatedEnemies"]
    ]
    if len(combat_samples) < 2:
        raise RuntimeProbeError(
            "client B had too few combat samples to prove enemy attacks"
        )
    hp_before = combat_samples[0]["hp"]
    hp_after = min(sample["hp"] for sample in combat_samples[1:])
    animation_states = sorted(
        {
            animation
            for sample in combat_samples
            for animation in sample["enemyAnimations"]
        }
    )
    if hp_after >= hp_before - 0.01:
        raise RuntimeProbeError(
            "client B took no replicated enemy damage during the combat "
            f"window: hpBefore={hp_before} hpAfter={hp_after} "
            f"enemyAnimations={animation_states}"
        )
    return {
        "hpBefore": hp_before,
        "hpAfter": hp_after,
        "damage": hp_before - hp_after,
        "enemyAnimationStates": animation_states,
        "samples": combat_samples,
    }


def damage_click_targets(
    candidates: list[dict[str, Any]],
    player: dict[str, Any],
    viewport: dict[str, Any],
    camera: dict[str, Any],
) -> list[tuple[float, float]]:
    interior: list[tuple[float, float]] = []
    edge: list[tuple[float, float]] = []
    viewport_width = float(viewport["width"])
    viewport_height = float(viewport["height"])
    if viewport_width <= 0.0 or viewport_height <= 0.0:
        return []
    camera_scale = float(camera.get("scale", math.nan))
    camera_projection_available = (
        bool(camera.get("sceneAvailable"))
        and math.isfinite(camera_scale)
        and camera_scale > 0.0001
        and math.isfinite(float(camera.get("originX", math.nan)))
        and math.isfinite(float(camera.get("originY", math.nan)))
    )
    minimum_x = viewport_width * 0.01
    maximum_x = viewport_width * 0.99
    minimum_y = viewport_height * 0.01
    maximum_y = viewport_height * 0.99
    interior_minimum_x = viewport_width * 0.08
    interior_maximum_x = viewport_width * 0.92
    interior_minimum_y = viewport_height * 0.08
    interior_maximum_y = viewport_height * 0.92
    player_screen_x = math.nan
    player_screen_y = math.nan
    if camera_projection_available:
        player_screen_x = (
            float(player["x"]) - float(camera["originX"])
        ) * camera_scale
        player_screen_y = (
            float(player["y"]) - float(camera["originY"])
        ) * camera_scale
    for enemy in sorted(
        candidates,
        key=lambda row: _distance(
            player["x"],
            player["y"],
            row["x"],
            row["y"],
        ),
    ):
        if camera_projection_available:
            screen_x = (
                float(enemy["x"]) - float(camera["originX"])
            ) * camera_scale
            screen_y = (
                float(enemy["y"]) - float(camera["originY"])
            ) * camera_scale
            if not (
                math.isfinite(screen_x)
                and math.isfinite(screen_y)
                and minimum_x <= player_screen_x <= maximum_x
                and minimum_y <= player_screen_y <= maximum_y
            ):
                continue
            ray_scale = 1.0
            for start, end, lower, upper in (
                (player_screen_x, screen_x, minimum_x, maximum_x),
                (player_screen_y, screen_y, minimum_y, maximum_y),
            ):
                if end < lower:
                    ray_scale = min(
                        ray_scale,
                        (lower - start) / (end - start),
                    )
                elif end > upper:
                    ray_scale = min(
                        ray_scale,
                        (upper - start) / (end - start),
                    )
            if not 0.0 < ray_scale <= 1.0:
                continue
            screen_x = player_screen_x + (
                screen_x - player_screen_x
            ) * ray_scale
            screen_y = player_screen_y + (
                screen_y - player_screen_y
            ) * ray_scale
        else:
            if not enemy["screen_valid"]:
                continue
            screen_x = float(enemy["screen_x"])
            screen_y = float(enemy["screen_y"])
        x = screen_x / viewport_width
        y = screen_y / viewport_height
        # Physical input is converted back through this camera. When the actor
        # center is offscreen, the clipped point preserves the exact aim ray.
        target = (
            max(0.01, min(0.99, x)),
            max(0.01, min(0.99, y)),
        )
        if target in interior or target in edge:
            continue
        if (
            interior_minimum_x <= screen_x <= interior_maximum_x
            and interior_minimum_y <= screen_y <= interior_maximum_y
        ):
            interior.append(target)
        else:
            edge.append(target)
    return interior + edge


def damage_enemy_with_real_input(
    source_root: Path,
    peer: WindowsPeer,
    pipe: LuaPipe,
    *,
    timeout: float,
) -> dict[str, Any]:
    def live_candidates(state: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            enemy
            for enemy in state["replicatedEnemies"]
            if not enemy["dead"] and enemy["hp"] > 0
        ]

    before = wait_for_state(
        pipe,
        lambda state: (
            state["scene"]["name"] == "testrun"
            and state["player"]["valid"]
            and state["player"]["hp"] > 0
            and bool(
                damage_click_targets(
                    live_candidates(state),
                    state["player"],
                    state["viewport"],
                    state["camera"],
                )
            )
        ),
        timeout=timeout,
        label="client B native-camera-aimable replicated enemy for damage",
    )
    viewport = before["viewport"]
    if viewport["width"] <= 0 or viewport["height"] <= 0:
        raise RuntimeProbeError(f"invalid client viewport: {viewport}")
    candidates = live_candidates(before)
    hp_before_by_id = {
        int(enemy["network_id"]): float(enemy["hp"])
        for enemy in candidates
    }
    actions: list[dict[str, Any]] = []
    deadline = time.monotonic() + min(timeout, 45.0)
    last = before
    while time.monotonic() < deadline and len(actions) < 8:
        live_scene = (
            last["scene"]["name"] == "testrun"
            and last["player"]["valid"]
        )
        current_by_id = {
            int(enemy["network_id"]): enemy
            for enemy in last["replicatedEnemies"]
        }
        for network_id, hp_before in hp_before_by_id.items():
            current = current_by_id.get(network_id)
            if current is None and not live_scene:
                continue
            hp_after = 0.0 if current is None or current["dead"] else float(
                current["hp"]
            )
            if hp_after < hp_before - 0.01:
                return {
                    "networkActorId": network_id,
                    "hpBefore": hp_before,
                    "hpAfter": hp_after,
                    "actions": actions,
                    "before": before,
                    "after": last,
                }
        if (
            not live_scene
            or last["player"]["hp"] <= 0
        ):
            raise RuntimeProbeError(
                "client B left live combat before physical input damaged "
                f"an enemy; actions={actions}"
            )
        current_candidates = live_candidates(last)
        click_targets = damage_click_targets(
            current_candidates,
            last["player"],
            last["viewport"],
            last["camera"],
        )
        if not click_targets:
            time.sleep(0.1)
            last = pipe.state()
            continue
        target_index = len(actions) % len(click_targets)
        x, y = click_targets[target_index]
        remote_burst = getattr(peer, "click_sequence", None)
        if callable(remote_burst):
            burst_targets = [(x, y)] * 5
            detail = str(remote_burst(burst_targets, 90, 450))
            physical_input_count = len(burst_targets)
        else:
            detail = _click(source_root, peer, x, y, 90)
            physical_input_count = 1
        actions.append(
            {
                "timeUtcNanoseconds": time.time_ns(),
                "screenFraction": [x, y],
                "result": detail,
                "playerHp": float(last["player"]["hp"]),
                "candidateCount": len(current_candidates),
                "physicalInputCount": physical_input_count,
            }
        )
        time.sleep(0.1)
        last = pipe.state()
    raise RuntimeProbeError(
        "client B real input did not damage any replicated enemy; "
        f"baseline={hp_before_by_id}; actions={actions}; "
        f"lastScene={last['scene']['name']!r}; "
        f"lastPlayerHp={last['player']['hp']}"
    )


def observe_water_cast_with_real_input(
    source_root: Path,
    peer: WindowsPeer,
    client_pipe: LuaPipe,
    host_pipe: LuaPipe,
    *,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    selected: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        client_before = client_pipe.state()
        host_before = host_pipe.state()
        host_enemies = {
            int(enemy["network_id"]): enemy
            for enemy in host_before["nativeEnemies"]
            if (
                int(enemy["network_id"]) != 0
                and not enemy["dead"]
                and float(enemy["hp"]) > 0.5
            )
        }
        if (
            client_before["scene"]["name"] == "testrun"
            and client_before["player"]["valid"]
            and client_before["player"]["hp"] > 0
        ):
            for enemy in client_before["replicatedEnemies"]:
                network_actor_id = int(enemy["network_id"])
                if (
                    network_actor_id not in host_enemies
                    or enemy["dead"]
                    or float(enemy["hp"]) <= 0
                ):
                    continue
                targets = damage_click_targets(
                    [enemy],
                    client_before["player"],
                    client_before["viewport"],
                    client_before["camera"],
                )
                if targets:
                    selected = {
                        "networkActorId": network_actor_id,
                        "screenFraction": list(targets[0]),
                        "clientBefore": client_before,
                        "hostBefore": host_before,
                        "hostHpBefore": float(
                            host_enemies[network_actor_id]["hp"]
                        ),
                    }
                    break
        if selected is not None:
            break
        time.sleep(0.1)
    if selected is None:
        raise RuntimeProbeError(
            "client B could not acquire an aligned, native-camera-aimable "
            "enemy for the isolated Water cast"
        )

    network_actor_id = int(selected["networkActorId"])
    if not client_pipe.reset_local_cast_observation(network_actor_id):
        raise RuntimeProbeError(
            "client B could not arm the native Water cast observation"
        )
    x, y = selected["screenFraction"]
    action = {
        "timeUtcNanoseconds": time.time_ns(),
        "screenFraction": [x, y],
        "result": _click(source_root, peer, x, y, 90),
        "physicalInputCount": 1,
    }

    host_after: dict[str, Any] | None = None
    client_after: dict[str, Any] | None = None
    host_hp_after = selected["hostHpBefore"]
    damage_deadline = min(deadline, time.monotonic() + 15.0)
    while time.monotonic() < damage_deadline:
        host_after = host_pipe.state()
        client_after = client_pipe.state()
        current = next(
            (
                enemy
                for enemy in host_after["nativeEnemies"]
                if int(enemy["network_id"]) == network_actor_id
            ),
            None,
        )
        host_hp_after = (
            0.0
            if current is None or current["dead"]
            else float(current["hp"])
        )
        if host_hp_after < float(selected["hostHpBefore"]) - 0.001:
            break
        time.sleep(0.08)
    else:
        raise RuntimeProbeError(
            "the isolated client Water input produced no authoritative host "
            f"damage for enemy {network_actor_id}"
        )

    # Let the final contact/claim generated by the physical key-up drain
    # before consuming the one-shot observation.
    time.sleep(0.25)
    observation = client_pipe.take_local_cast_observation(network_actor_id)
    host_after = host_pipe.state()
    current = next(
        (
            enemy
            for enemy in host_after["nativeEnemies"]
            if int(enemy["network_id"]) == network_actor_id
        ),
        None,
    )
    host_hp_after = (
        0.0
        if current is None or current["dead"]
        else float(current["hp"])
    )
    convergence_deadline = time.monotonic() + 3.0
    while True:
        client_after = client_pipe.state()
        client_current = next(
            (
                enemy
                for enemy in client_after["replicatedEnemies"]
                if int(enemy["network_id"]) == network_actor_id
            ),
            None,
        )
        client_hp_after = (
            0.0
            if client_current is None or client_current["dead"]
            else float(client_current["hp"])
        )
        if math.isclose(
            client_hp_after,
            host_hp_after,
            rel_tol=0.0,
            abs_tol=0.0005,
        ):
            break
        if time.monotonic() >= convergence_deadline:
            break
        time.sleep(0.08)
    return {
        **selected,
        "hostHpAfter": host_hp_after,
        "hostDamage": float(selected["hostHpBefore"]) - host_hp_after,
        "clientAfter": client_after,
        "hostAfter": host_after,
        "observation": observation,
        "action": action,
    }


def effective_wave_index(state: dict[str, Any]) -> int:
    return max(
        int(state["wave"]["index"]),
        int(state["combat"]["waveIndex"]),
        int(state["world"]["waveIndex"]),
    )


def drive_combat_to_wave_with_real_input(
    source_root: Path,
    peer: WindowsPeer,
    client_pipe: LuaPipe,
    host_pipe: LuaPipe,
    *,
    target_wave: int,
    timeout: float,
    sample: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if target_wave < 2:
        raise RuntimeProbeError("combat wave target must be at least wave 2")
    deadline = time.monotonic() + timeout
    actions: list[dict[str, Any]] = []
    last: dict[str, Any] = {}
    idle_samples = 0
    while time.monotonic() < deadline:
        host_state = host_pipe.state()
        client_state = client_pipe.state()
        last = {"host": host_state, "clientB": client_state}
        if sample is not None:
            sample("wave-clear")
        host_wave = effective_wave_index(host_state)
        client_wave = effective_wave_index(client_state)
        if host_wave >= target_wave and client_wave >= target_wave:
            return {
                "targetWave": target_wave,
                "hostWave": host_wave,
                "clientBWave": client_wave,
                "actions": actions,
                "completion": last,
            }
        for role, state in (
            ("host", host_state),
            ("client B", client_state),
        ):
            if (
                state["scene"]["name"] != "testrun"
                or not state["player"]["valid"]
                or float(state["player"]["hp"]) <= 0.0
            ):
                raise RuntimeProbeError(
                    f"{role} stopped being a living testrun participant "
                    f"before wave {target_wave}: {state['player']}"
                )

        live_enemies = [
            enemy
            for enemy in client_state["replicatedEnemies"]
            if not enemy["dead"] and float(enemy["hp"]) > 0
        ]
        targets = damage_click_targets(
            live_enemies,
            client_state["player"],
            client_state["viewport"],
            client_state["camera"],
        )
        if not targets:
            idle_samples += 1
            time.sleep(0.1)
            continue
        idle_samples = 0
        x, y = targets[len(actions) % len(targets)]
        actions.append(
            {
                "timeUtcNanoseconds": time.time_ns(),
                "screenFraction": [x, y],
                "result": _click(source_root, peer, x, y, 180),
                "hostWave": host_wave,
                "clientBWave": client_wave,
                "liveEnemyCount": len(live_enemies),
            }
        )
        time.sleep(0.06)
    raise RuntimeProbeError(
        f"client B physical Water input did not reach wave {target_wave}; "
        f"actions={len(actions)} idleSamples={idle_samples} "
        f"last={json.dumps(last, sort_keys=True)}"
    )
