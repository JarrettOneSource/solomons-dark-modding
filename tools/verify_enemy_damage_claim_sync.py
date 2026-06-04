#!/usr/bin/env python3
"""Verify client-originated enemy damage claims and host rollback corrections."""

from __future__ import annotations

import json
import time

from verify_local_multiplayer_sync import (
    CLIENT_PIPE,
    ROOT,
    HOST_PIPE,
    VerifyFailure,
    disable_bots,
    launch_pair,
    lua,
    parse_key_values,
    place_player,
    start_host_testrun_and_wait_for_clients,
    stop_games,
    wait_for_remote,
    HOST_ID,
    HOST_NAME,
    CLIENT_ID,
    CLIENT_NAME,
)
from verify_run_world_snapshot import start_host_waves, wait_for_run_snapshot
from verify_player_health_death_sync import set_local_player_vitals


TEST_PLAYER_HP = 500.0
HOST_LOG = ROOT / "runtime/instances/local-mp-host/stage/.sdmod/logs/solomondarkmodloader.log"


CLIENT_SELECT_DAMAGE_LUA = r"""
local mode = "__MODE__"
local preferred_network_id = tonumber("__PREFERRED_NETWORK_ID__") or 0
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local replicated = sd.world.get_replicated_actors and sd.world.get_replicated_actors() or nil
if replicated == nil or replicated.actors == nil or replicated.bindings == nil then
  emit("ok", false)
  emit("reason", "replicated_snapshot_missing")
  return
end
local actors = sd.world.list_actors() or {}
local local_by_address = {}
for _, actor in ipairs(actors) do
  local address = tonumber(actor.actor_address) or 0
  if address ~= 0 then
    local_by_address[address] = actor
  end
end
local snapshot_by_id = {}
for _, actor in ipairs(replicated.actors) do
  local id = tonumber(actor.network_actor_id) or 0
  if id ~= 0 then
    snapshot_by_id[id] = actor
  end
end
local hp_offset = sd.debug.layout_offset("enemy_current_hp")
if hp_offset == nil then
  emit("ok", false)
  emit("reason", "hp_offset_missing")
  return
end
local player = sd.player.get_state and sd.player.get_state() or nil
local player_x = player and tonumber(player.x) or 0
local player_y = player and tonumber(player.y) or 0
local best = nil
local best_d2 = nil
for _, binding in ipairs(replicated.bindings) do
  if binding.matched and not binding.parked and not binding.removed then
    local network_id = tonumber(binding.network_actor_id) or 0
    local local_address = tonumber(binding.local_actor_address) or 0
    local snapshot = snapshot_by_id[network_id]
    local local_actor = local_by_address[local_address]
    if snapshot ~= nil and local_actor ~= nil and snapshot.tracked_enemy then
      local hp = tonumber(local_actor.hp) or 0
      local snapshot_hp = tonumber(snapshot.hp) or 0
      local max_hp = tonumber(local_actor.max_hp) or tonumber(snapshot.max_hp) or 0
      if max_hp > 1 and hp > 0.5 and snapshot_hp > 0.5 then
        local x = tonumber(local_actor.x) or tonumber(snapshot.x) or 0
        local y = tonumber(local_actor.y) or tonumber(snapshot.y) or 0
        local dx = x - player_x
        local dy = y - player_y
        local d2 = dx * dx + dy * dy
        if preferred_network_id ~= 0 and network_id == preferred_network_id then
          best = {
            network_id = network_id,
            local_address = local_address,
            object_type_id = tonumber(local_actor.object_type_id) or tonumber(snapshot.native_type_id) or 0,
            x = x,
            y = y,
            before_hp = hp,
            snapshot_hp = snapshot_hp,
            max_hp = max_hp,
          }
          best_d2 = d2
        elseif preferred_network_id == 0 and (best == nil or d2 < best_d2) then
          best = {
            network_id = network_id,
            local_address = local_address,
            object_type_id = tonumber(local_actor.object_type_id) or tonumber(snapshot.native_type_id) or 0,
            x = x,
            y = y,
            before_hp = hp,
            snapshot_hp = snapshot_hp,
            max_hp = max_hp,
          }
          best_d2 = d2
        end
      end
    end
  end
end
if best ~= nil then
  local target_hp = math.max(1.0, math.min(best.before_hp, best.snapshot_hp) * 0.5)
  if mode == "kill" then target_hp = 0.0 end
  emit("ok", true)
  emit("network_actor_id", string.format("%.0f", best.network_id))
  emit("local_actor_address", best.local_address)
  emit("object_type_id", best.object_type_id)
  emit("x", best.x)
  emit("y", best.y)
  emit("before_hp", string.format("%.3f", best.before_hp))
  emit("snapshot_hp", string.format("%.3f", best.snapshot_hp))
  emit("max_hp", string.format("%.3f", best.max_hp))
  emit("target_hp", string.format("%.3f", target_hp))
  emit("distance", string.format("%.3f", math.sqrt(best_d2 or 0)))
  if mode == "select" then
    emit("write_hp", "skipped")
    return
  end
  if mode == "damage_drift" then
    if sd.input == nil or sd.input.queue_local_enemy_damage_claim == nil then
      emit("ok", false)
      emit("reason", "damage_claim_queue_missing")
      return
    end
    emit("queue_claim", sd.input.queue_local_enemy_damage_claim(
      best.network_id,
      0,
      math.min(best.before_hp, best.snapshot_hp),
      target_hp,
      best.max_hp,
      best.x + 1024.0,
      best.y + 1024.0))
  end
  emit("write_hp", sd.debug.write_float(best.local_address + hp_offset, target_hp))
  return
end
emit("ok", false)
emit("reason", "no_live_bound_enemy")
"""


HOST_ENEMY_BY_ID_LUA = r"""
local target_id = tonumber("__NETWORK_ACTOR_ID__") or 0
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local death_handled_offset = sd.debug.layout_offset("enemy_death_handled")
local function read_death_handled(address)
  if death_handled_offset == nil or address == nil or address == 0 then return 0 end
  local ok, value = pcall(function()
    return sd.debug.read_u8(address + death_handled_offset)
  end)
  if not ok then return 0 end
  return tonumber(value) or 0
end
local replicated = sd.world.get_replicated_actors and sd.world.get_replicated_actors() or nil
if replicated == nil or replicated.actors == nil then
  emit("found", false)
  emit("reason", "replicated_snapshot_missing")
  return
end
local actors = sd.world.list_actors() or {}
local tracked = 0
local live = 0
local dead = 0
for _, actor in ipairs(replicated.actors) do
  if actor.tracked_enemy then
    tracked = tracked + 1
    local hp = tonumber(actor.hp) or 0
    local max_hp = tonumber(actor.max_hp) or 0
    if actor.dead or (max_hp > 0 and hp <= 0) then
      dead = dead + 1
    elseif max_hp > 0 then
      live = live + 1
    end
    if (tonumber(actor.network_actor_id) or 0) == target_id then
      local best_live = nil
      local best_d2 = nil
      local snapshot_x = tonumber(actor.x) or 0
      local snapshot_y = tonumber(actor.y) or 0
      local snapshot_type = tonumber(actor.native_type_id) or 0
      for _, local_actor in ipairs(actors) do
        local local_type = tonumber(local_actor.object_type_id) or 0
        if local_actor.tracked_enemy and local_type == snapshot_type then
          local local_x = tonumber(local_actor.x) or 0
          local local_y = tonumber(local_actor.y) or 0
          local dx = local_x - snapshot_x
          local dy = local_y - snapshot_y
          local d2 = dx * dx + dy * dy
          if best_live == nil or d2 < best_d2 then
            best_live = local_actor
            best_d2 = d2
          end
        end
      end
      if best_live ~= nil and best_d2 ~= nil and best_d2 <= (96.0 * 96.0) then
        hp = tonumber(best_live.hp) or hp
        max_hp = tonumber(best_live.max_hp) or max_hp
        emit("local_actor_address", best_live.actor_address or 0)
        emit("death_handled", read_death_handled(tonumber(best_live.actor_address) or 0))
        if best_live.dead or (max_hp > 0 and hp <= 0) then
          dead = dead + 1
        end
      else
        emit("death_handled", 0)
      end
      emit("tracked", tracked)
      emit("live", live)
      emit("dead", dead)
      emit("found", true)
      emit("network_actor_id", string.format("%.0f", target_id))
      emit("object_type_id", actor.object_type_id or 0)
      emit("hp", string.format("%.3f", hp))
      emit("max_hp", string.format("%.3f", max_hp))
      emit("dead_flag", actor.dead or false)
      emit("x", actor.x or 0)
      emit("y", actor.y or 0)
      return
    end
  end
end
emit("tracked", tracked)
emit("live", live)
emit("dead", dead)
emit("found", false)
"""


CLIENT_BOUND_ENEMY_BY_ID_LUA = r"""
local target_id = tonumber("__NETWORK_ACTOR_ID__") or 0
local target_address = tonumber("__LOCAL_ACTOR_ADDRESS__") or 0
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local actors = sd.world.list_actors() or {}
local local_by_address = {}
for _, actor in ipairs(actors) do
  local address = tonumber(actor.actor_address) or 0
  if address ~= 0 then local_by_address[address] = actor end
end
local death_handled_offset = sd.debug.layout_offset("enemy_death_handled")
local function read_death_handled(address)
  if death_handled_offset == nil or address == 0 then return 0 end
  local ok, value = pcall(function()
    return sd.debug.read_u8(address + death_handled_offset)
  end)
  if not ok then return 0 end
  return tonumber(value) or 0
end
local replicated = sd.world.get_replicated_actors and sd.world.get_replicated_actors() or nil
if replicated == nil or replicated.bindings == nil then
  local fallback_death = read_death_handled(target_address)
  emit("found", fallback_death ~= 0)
  emit("binding_found", false)
  emit("address_fallback", target_address ~= 0)
  emit("death_handled", fallback_death)
  return
end
for _, binding in ipairs(replicated.bindings) do
  local id = tonumber(binding.network_actor_id) or 0
  if id == target_id then
    local actor = local_by_address[tonumber(binding.local_actor_address) or 0]
    if actor == nil then
      emit("found", false)
      emit("binding_found", false)
      return
    end
    emit("found", true)
    emit("binding_found", true)
    emit("hp", string.format("%.3f", tonumber(actor.hp) or 0))
    emit("max_hp", string.format("%.3f", tonumber(actor.max_hp) or 0))
    emit("dead", actor.dead or false)
    emit("death_handled", read_death_handled(tonumber(actor.actor_address) or 0))
    emit("x", actor.x or 0)
    emit("y", actor.y or 0)
    return
  end
end
local fallback_death = read_death_handled(target_address)
if fallback_death ~= 0 then
  emit("found", true)
  emit("binding_found", false)
  emit("address_fallback", true)
  emit("local_actor_address", target_address)
  emit("death_handled", fallback_death)
  return
end
emit("found", false)
emit("binding_found", false)
"""


def values(pipe_name: str, code: str) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, code))


def number(row: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key, default))
    except (TypeError, ValueError):
        return default


def log_offset(path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def read_log_since(path, offset: int) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(offset)
            return handle.read()
    except OSError:
        return ""


def damage_client_enemy(mode: str, preferred_network_id: str = "0") -> dict[str, str]:
    result = values(
        CLIENT_PIPE,
        CLIENT_SELECT_DAMAGE_LUA
        .replace("__MODE__", mode)
        .replace("__PREFERRED_NETWORK_ID__", preferred_network_id),
    )
    if result.get("ok") != "true" or result.get("write_hp") != "true":
        raise VerifyFailure(f"failed to damage a client enemy mode={mode}: {result}")
    return result


def select_client_enemy(preferred_network_id: str = "0") -> dict[str, str]:
    result = values(
        CLIENT_PIPE,
        CLIENT_SELECT_DAMAGE_LUA
        .replace("__MODE__", "select")
        .replace("__PREFERRED_NETWORK_ID__", preferred_network_id),
    )
    if result.get("ok") != "true" or result.get("write_hp") != "skipped":
        raise VerifyFailure(f"failed to select a client enemy: {result}")
    return result


def host_enemy_by_id(network_actor_id: str) -> dict[str, str]:
    return values(
        HOST_PIPE,
        HOST_ENEMY_BY_ID_LUA.replace("__NETWORK_ACTOR_ID__", network_actor_id),
    )


def wait_for_host_enemy_hp(target: dict[str, str], expected_hp: float, timeout: float = 10.0) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = host_enemy_by_id(target["network_actor_id"])
        if (
            last.get("found") == "true"
            and abs(number(last, "hp") - expected_hp) <= 0.1
        ):
            return last
        time.sleep(0.15)
    raise VerifyFailure(f"host enemy did not reach expected hp={expected_hp:.3f}; target={target} last={last}")


def wait_for_host_enemy_killed(target: dict[str, str], timeout: float = 12.0) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = host_enemy_by_id(target["network_actor_id"])
        if last.get("found") == "true":
            hp = number(last, "hp")
            dead_flag = last.get("dead_flag") == "true"
            death_handled = int(number(last, "death_handled"))
            if (dead_flag or hp <= 0.25) and death_handled != 0:
                return last
        elif last.get("reason") != "replicated_snapshot_missing" and int(number(last, "tracked")) > 0:
            last["removed_after_kill"] = "true"
            return last
        time.sleep(0.15)
    raise VerifyFailure(f"host enemy did not die from client claim; target={target} last={last}")


def wait_for_host_enemy_native_death_log(
    target: dict[str, str],
    start_offset: int,
    timeout: float = 4.0,
) -> dict[str, str]:
    target_id = target["network_actor_id"]
    deadline = time.monotonic() + timeout
    last_text = ""
    while time.monotonic() < deadline:
        last_text = read_log_since(HOST_LOG, start_offset)
        if (
            "native enemy death presenter invoked." in last_text
            and f"target_network_actor_id={target_id}" in last_text
            and "lethal=1 death_called=1" in last_text
        ):
            return {
                "presenter_invoked": "true",
                "target_network_actor_id": target_id,
            }
        time.sleep(0.1)
    raise VerifyFailure(
        f"host accepted lethal client claim but did not log native death presentation; "
        f"target={target} log_tail={last_text[-800:]}"
    )


def client_bound_enemy_query(network_actor_id: str, local_actor_address: str = "0") -> dict[str, str]:
    return values(
        CLIENT_PIPE,
        CLIENT_BOUND_ENEMY_BY_ID_LUA
        .replace("__NETWORK_ACTOR_ID__", network_actor_id)
        .replace("__LOCAL_ACTOR_ADDRESS__", local_actor_address),
    )


def wait_for_client_rollback(network_actor_id: str, expected_hp: float, timeout: float = 8.0) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = client_bound_enemy_query(network_actor_id)
        if last.get("found") == "true" and abs(number(last, "hp") - expected_hp) <= 0.1:
            return last
        time.sleep(0.15)
    raise VerifyFailure(
        f"client enemy claim was not rolled back to expected hp={expected_hp:.3f}; "
        f"network_actor_id={network_actor_id} last={last}"
    )


def wait_for_client_enemy_removed(network_actor_id: str, timeout: float = 10.0) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = client_bound_enemy_query(network_actor_id)
        if last.get("found") != "true" or last.get("binding_found") != "true":
            return {"found": "false", "network_actor_id": network_actor_id}
        time.sleep(0.15)
    raise VerifyFailure(
        f"client still has the killed enemy bound after host accepted death; "
        f"network_actor_id={network_actor_id} last={last}"
    )


def wait_for_client_enemy_death_handled(
    network_actor_id: str,
    local_actor_address: str = "0",
    timeout: float = 8.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = client_bound_enemy_query(network_actor_id, local_actor_address)
        if (
            last.get("found") == "true"
            and int(number(last, "death_handled")) != 0
        ):
            return last
        time.sleep(0.15)
    raise VerifyFailure(
        f"client replicated enemy never ran native death handling after host accepted death; "
        f"network_actor_id={network_actor_id} last={last}"
    )


def move_client_near(target: dict[str, str]) -> dict[str, str]:
    return place_player(
        CLIENT_PIPE,
        number(target, "x") + 32.0,
        number(target, "y") + 32.0,
        180.0,
    )


def main() -> int:
    result: dict[str, object] = {"ok": False}
    try:
        stop_games()
        result["launch"] = launch_pair()
        disable_bots()
        result["run_entry"] = start_host_testrun_and_wait_for_clients()
        wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "testrun")
        wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "testrun")
        result["initial_host_vitals"] = set_local_player_vitals(HOST_PIPE, TEST_PLAYER_HP, TEST_PLAYER_HP)
        result["initial_client_vitals"] = set_local_player_vitals(CLIENT_PIPE, TEST_PLAYER_HP, TEST_PLAYER_HP)
        result["start_waves"] = start_host_waves()
        result["wave_host_vitals"] = set_local_player_vitals(HOST_PIPE, TEST_PLAYER_HP, TEST_PLAYER_HP)
        result["wave_client_vitals"] = set_local_player_vitals(CLIENT_PIPE, TEST_PLAYER_HP, TEST_PLAYER_HP)
        result["snapshot"] = wait_for_run_snapshot(require_complete_lifecycle=True)

        result["client_damage"] = damage_client_enemy("damage")
        damage_target = result["client_damage"]
        result["host_damage_accept"] = wait_for_host_enemy_hp(
            damage_target,
            number(damage_target, "target_hp"),
        )

        result["rejected_target_seed"] = select_client_enemy()
        result["far_client_vitals"] = set_local_player_vitals(CLIENT_PIPE, TEST_PLAYER_HP, TEST_PLAYER_HP)
        result["client_rejected_damage"] = damage_client_enemy(
            "damage_drift",
            result["rejected_target_seed"]["network_actor_id"],
        )
        rejected_target = result["client_rejected_damage"]
        result["client_rollback"] = wait_for_client_rollback(
            rejected_target["network_actor_id"],
            number(rejected_target, "snapshot_hp"),
        )
        result["host_rejected_target_before_kill"] = wait_for_host_enemy_hp(
            rejected_target,
            number(rejected_target, "snapshot_hp"),
        )

        result["move_client_near_for_kill"] = move_client_near(rejected_target)
        time.sleep(0.6)
        host_log_before_kill = log_offset(HOST_LOG)
        result["client_kill"] = damage_client_enemy("kill", rejected_target["network_actor_id"])
        result["client_kill_predicted_death_handled"] = wait_for_client_enemy_death_handled(
            result["client_kill"]["network_actor_id"],
            result["client_kill"]["local_actor_address"],
            timeout=3.0,
        )
        result["host_kill_accept"] = wait_for_host_enemy_killed(result["client_kill"])
        result["host_kill_native_death_presentation_log"] = wait_for_host_enemy_native_death_log(
            result["client_kill"],
            host_log_before_kill,
        )
        result["client_kill_death_handled"] = wait_for_client_enemy_death_handled(
            result["client_kill"]["network_actor_id"],
            result["client_kill"]["local_actor_address"],
        )
        result["post_kill_snapshot"] = wait_for_run_snapshot(
            require_complete_lifecycle=True,
            stable_seconds=2.0,
        )
        result["client_kill_removed"] = wait_for_client_enemy_removed(
            result["client_kill"]["network_actor_id"],
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
