#!/usr/bin/env python3
"""Verify host-authoritative run enemy snapshot bootstrap and reconciliation."""

from __future__ import annotations

import argparse
import json
import time

from verify_local_multiplayer_sync import (
    CLIENT_PIPE,
    HOST_PIPE,
    ROOT,
    VerifyFailure,
    disable_bots,
    launch_pair,
    lua,
    parse_key_values,
    start_testrun,
    stop_games,
    wait_for_scene,
)

RUNTIME_OUTPUT = ROOT / "runtime" / "run_world_snapshot_verification.json"


HOST_ENEMY_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local scene = sd.world.get_scene()
local actors = sd.world.list_actors() or {}
local tracked = 0
local live = 0
local dead = 0
for _, actor in ipairs(actors) do
  if actor.tracked_enemy then
    tracked = tracked + 1
    local hp = tonumber(actor.hp) or 0
    local max_hp = tonumber(actor.max_hp) or 0
    if actor.dead or (max_hp > 0 and hp <= 0) then
      dead = dead + 1
    elseif max_hp > 0 and hp > 0 then
      live = live + 1
    end
  end
end
emit("scene", scene and (scene.name or scene.kind) or "")
emit("tracked_enemies", tracked)
emit("live_enemies", live)
emit("dead_enemies", dead)
"""


CLIENT_SNAPSHOT_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local function finite(v)
  return type(v) == "number" and v == v and v ~= math.huge and v ~= -math.huge
end
local scene = sd.world.get_scene()
local actors = sd.world.list_actors() or {}
local local_by_address = {}
local local_tracked = 0
for _, actor in ipairs(actors) do
  local type_id = tonumber(actor.object_type_id) or 0
  if actor.tracked_enemy and type_id ~= 0 and type_id ~= 1 and finite(tonumber(actor.x)) and finite(tonumber(actor.y)) then
    local address = tonumber(actor.actor_address) or 0
    if address ~= 0 then
      local_by_address[address] = actor
    end
    local_tracked = local_tracked + 1
  end
end
local replicated = sd.world.get_replicated_actors and sd.world.get_replicated_actors() or nil
local local_by_id = {}
local matched_binding_count = 0
if replicated and replicated.bindings then
  for _, binding in ipairs(replicated.bindings) do
    if binding.matched and not binding.parked then
      local network_id = tonumber(binding.network_actor_id) or 0
      local address = tonumber(binding.local_actor_address) or 0
      local local_actor = local_by_address[address]
      if network_id ~= 0 and local_actor ~= nil then
        local_by_id[network_id] = local_actor
        matched_binding_count = matched_binding_count + 1
      end
    end
  end
end
emit("scene", scene and (scene.name or scene.kind) or "")
emit("local_tracked_enemies", local_tracked)
emit("replicated_valid", replicated ~= nil)
emit("scene_kind", replicated and replicated.scene_kind or "")
emit("actor_count", replicated and replicated.actor_count or 0)
emit("actor_total_count", replicated and replicated.actor_total_count or 0)
emit("truncated", replicated and replicated.truncated or false)
emit("apply_valid", replicated and replicated.apply_valid or false)
emit("apply_local_actor_count", replicated and replicated.local_actor_count or 0)
emit("apply_matched", replicated and replicated.matched_actor_count or 0)
emit("apply_transform_writes", replicated and replicated.transform_write_count or 0)
emit("apply_health_writes", replicated and replicated.health_write_count or 0)
emit("apply_dead_actors", replicated and replicated.dead_actor_count or 0)
emit("apply_parked", replicated and replicated.parked_actor_count or 0)
emit("binding_count", replicated and replicated.binding_count or 0)
emit("matched_binding_count", matched_binding_count)
local tracked = 0
local lifecycle_owned = 0
local live = 0
local dead = 0
local enemy_type_count = 0
local compared = 0
local within_16 = 0
local within_64 = 0
local max_distance = 0.0
local hp_compared = 0
local hp_within_quarter = 0
local max_hp_delta = 0.0
local min_snapshot_hp = nil
local min_local_hp = nil
if replicated and replicated.actors then
  for _, actor in ipairs(replicated.actors) do
    if actor.tracked_enemy then tracked = tracked + 1 end
    if actor.lifecycle_owned then lifecycle_owned = lifecycle_owned + 1 end
    if tonumber(actor.enemy_type) and tonumber(actor.enemy_type) >= 0 then
      enemy_type_count = enemy_type_count + 1
    end
    local hp = tonumber(actor.hp) or 0
    local max_hp = tonumber(actor.max_hp) or 0
    if actor.dead or (max_hp > 0 and hp <= 0) then
      dead = dead + 1
    elseif max_hp > 0 and hp > 0 then
      live = live + 1
    end
    local local_actor = local_by_id[tonumber(actor.network_actor_id)]
    if local_actor ~= nil and finite(tonumber(actor.x)) and finite(tonumber(actor.y)) then
      compared = compared + 1
      local dx = (tonumber(local_actor.x) or 0) - (tonumber(actor.x) or 0)
      local dy = (tonumber(local_actor.y) or 0) - (tonumber(actor.y) or 0)
      local distance = math.sqrt(dx * dx + dy * dy)
      if distance <= 16.0 then within_16 = within_16 + 1 end
      if distance <= 64.0 then within_64 = within_64 + 1 end
      if distance > max_distance then max_distance = distance end
      if finite(tonumber(local_actor.hp)) and finite(tonumber(actor.hp)) then
        hp_compared = hp_compared + 1
        local local_hp = tonumber(local_actor.hp) or 0
        local snapshot_hp = tonumber(actor.hp) or 0
        local hp_delta = math.abs(local_hp - snapshot_hp)
        if hp_delta <= 0.25 then hp_within_quarter = hp_within_quarter + 1 end
        if hp_delta > max_hp_delta then max_hp_delta = hp_delta end
        if min_snapshot_hp == nil or snapshot_hp < min_snapshot_hp then min_snapshot_hp = snapshot_hp end
        if min_local_hp == nil or local_hp < min_local_hp then min_local_hp = local_hp end
      end
    end
  end
end
emit("tracked_snapshot_actors", tracked)
emit("lifecycle_owned_snapshot_actors", lifecycle_owned)
emit("live_snapshot_actors", live)
emit("dead_snapshot_actors", dead)
emit("enemy_type_count", enemy_type_count)
emit("live_compared", compared)
emit("live_within_16", within_16)
emit("live_within_64", within_64)
emit("live_max_distance", string.format("%.3f", max_distance))
emit("hp_compared", hp_compared)
emit("hp_within_quarter", hp_within_quarter)
emit("max_hp_delta", string.format("%.3f", max_hp_delta))
emit("min_snapshot_hp", min_snapshot_hp and string.format("%.3f", min_snapshot_hp) or "")
emit("min_local_hp", min_local_hp and string.format("%.3f", min_local_hp) or "")
"""


HOST_DAMAGE_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local actors = sd.world.list_actors() or {}
local hp_offset = sd.debug.layout_offset("enemy_current_hp")
for _, actor in ipairs(actors) do
  local type_id = tonumber(actor.object_type_id) or 0
  if actor.tracked_enemy and type_id ~= 0 and type_id ~= 1 then
    local hp = tonumber(actor.hp) or 0
    local max_hp = tonumber(actor.max_hp) or 0
    if hp_offset ~= nil and max_hp > 2.0 and hp > 1.0 and actor.actor_address ~= nil and actor.actor_address ~= 0 then
      local target_hp = math.max(1.0, max_hp * 0.5)
      emit("selected_actor_address", tostring(actor.actor_address))
      emit("object_type_id", type_id)
      emit("old_hp", string.format("%.3f", hp))
      emit("max_hp", string.format("%.3f", max_hp))
      emit("target_hp", string.format("%.3f", target_hp))
      emit("write_hp", sd.debug.write_float(actor.actor_address + hp_offset, target_hp))
      return
    end
  end
end
emit("write_hp", false)
"""


def values(pipe_name: str, code: str) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, code))


def number(row: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key, default))
    except (TypeError, ValueError):
        return default


def start_host_waves() -> dict[str, str]:
    result = values(HOST_PIPE, "print('ok=' .. tostring(sd.gameplay.start_waves()))")
    if result.get("ok") != "true":
        raise VerifyFailure(f"sd.gameplay.start_waves failed on host: {result}")
    return result


def run_lifecycle_status(host: dict[str, str], client: dict[str, str]) -> dict[str, object]:
    expected_live = min(
        number(host, "tracked_enemies"),
        number(client, "actor_count"),
    )
    compared = number(client, "live_compared")
    local_tracked = number(client, "local_tracked_enemies")
    host_only_snapshot_actors = max(0.0, expected_live - compared)
    extra_client_tracked_enemies = max(0.0, local_tracked - expected_live)
    parked = number(client, "apply_parked")
    extra_unparked_client_tracked_enemies = max(0.0, extra_client_tracked_enemies - parked)
    authoritative_actors_matched = (
        expected_live > 0
        and number(client, "apply_matched") >= expected_live
        and compared >= expected_live
    )
    complete = (
        authoritative_actors_matched
        and int(host_only_snapshot_actors) == 0
        and int(extra_unparked_client_tracked_enemies) == 0
    )
    return {
        "complete": complete,
        "authoritative_actors_matched": authoritative_actors_matched,
        "expected_live_snapshot_actors": int(expected_live),
        "matched_live_snapshot_actors": int(compared),
        "host_only_snapshot_actors": int(host_only_snapshot_actors),
        "extra_client_tracked_enemies": int(extra_client_tracked_enemies),
        "extra_unparked_client_tracked_enemies": int(extra_unparked_client_tracked_enemies),
        "parked_client_tracked_enemies": int(parked),
        "local_tracked_enemies": int(local_tracked),
    }


def wait_for_run_snapshot(
    timeout: float = 45.0,
    max_distance: float = 64.0,
    require_complete_lifecycle: bool = False,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last_host: dict[str, str] = {}
    last_client: dict[str, str] = {}
    while time.monotonic() < deadline:
        last_host = values(HOST_PIPE, HOST_ENEMY_LUA)
        last_client = values(CLIENT_PIPE, CLIENT_SNAPSHOT_LUA)
        lifecycle = run_lifecycle_status(last_host, last_client)
        if (
            last_host.get("scene") == "testrun"
            and number(last_host, "tracked_enemies") > 0
            and last_client.get("scene") == "testrun"
            and last_client.get("replicated_valid") == "true"
            and last_client.get("scene_kind") == "Run"
            and number(last_client, "actor_count") > 0
            and number(last_client, "tracked_snapshot_actors") > 0
            and number(last_client, "lifecycle_owned_snapshot_actors") >= number(last_client, "tracked_snapshot_actors")
            and number(last_client, "enemy_type_count") > 0
            and number(last_client, "local_tracked_enemies") > 0
            and last_client.get("apply_valid") == "true"
            and number(last_client, "apply_matched") > 0
            and number(last_client, "matched_binding_count") > 0
            and number(last_client, "live_compared") > 0
            and number(last_client, "live_max_distance", max_distance + 1.0) <= max_distance
            and (not require_complete_lifecycle or lifecycle["complete"])
        ):
            return {
                "host": last_host,
                "client": last_client,
                "lifecycle": lifecycle,
            }
        time.sleep(0.25)

    raise VerifyFailure(
        "client did not receive a host-authored run enemy snapshot; "
        f"host={last_host} client={last_client}"
    )


def damage_host_enemy() -> dict[str, str]:
    result = values(HOST_PIPE, HOST_DAMAGE_LUA)
    if result.get("write_hp") != "true":
        raise VerifyFailure(f"failed to damage a host enemy: {result}")
    return result


def wait_for_health_convergence(
    target_hp: float,
    timeout: float = 15.0,
    max_distance: float = 64.0,
    require_complete_lifecycle: bool = False,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last_host: dict[str, str] = {}
    last_client: dict[str, str] = {}
    while time.monotonic() < deadline:
        last_host = values(HOST_PIPE, HOST_ENEMY_LUA)
        last_client = values(CLIENT_PIPE, CLIENT_SNAPSHOT_LUA)
        lifecycle = run_lifecycle_status(last_host, last_client)
        if (
            last_client.get("scene") == "testrun"
            and last_client.get("replicated_valid") == "true"
            and last_client.get("scene_kind") == "Run"
            and number(last_client, "lifecycle_owned_snapshot_actors") >= number(last_client, "tracked_snapshot_actors")
            and number(last_client, "live_max_distance", max_distance + 1.0) <= max_distance
            and number(last_client, "hp_compared") > 0
            and number(last_client, "hp_within_quarter") >= number(last_client, "hp_compared")
            and number(last_client, "max_hp_delta", 999.0) <= 0.25
            and number(last_client, "min_snapshot_hp", 999.0) <= target_hp + 0.25
            and number(last_client, "min_local_hp", 999.0) <= target_hp + 0.25
            and (not require_complete_lifecycle or lifecycle["complete"])
        ):
            return {"host": last_host, "client": last_client, "lifecycle": lifecycle, "target_hp": target_hp}
        time.sleep(0.25)

    raise VerifyFailure(
        "client run enemy HP did not converge to host authoritative snapshot; "
        f"target_hp={target_hp:.3f} host={last_host} client={last_client}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-complete-lifecycle", action="store_true")
    args = parser.parse_args()

    result: dict[str, object] = {"ok": False}
    try:
        stop_games()
        result["launch"] = launch_pair()
        disable_bots()
        start_testrun(HOST_PIPE)
        start_testrun(CLIENT_PIPE)
        wait_for_scene(HOST_PIPE, "testrun")
        wait_for_scene(CLIENT_PIPE, "testrun")
        result["start_waves"] = start_host_waves()
        result["snapshot"] = wait_for_run_snapshot(
            require_complete_lifecycle=args.require_complete_lifecycle,
        )
        result["host_damage"] = damage_host_enemy()
        result["health_sync"] = wait_for_health_convergence(
            number(result["host_damage"], "target_hp"),
            require_complete_lifecycle=args.require_complete_lifecycle,
        )
        result["ok"] = True
        RUNTIME_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        result["error"] = str(exc)
        RUNTIME_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1
    finally:
        stop_games()


if __name__ == "__main__":
    raise SystemExit(main())
