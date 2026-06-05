#!/usr/bin/env python3
"""Probe host-owned run gold reward visibility, fields, and pickup boundaries."""

from __future__ import annotations

import argparse
import json
import math
import time
from typing import Any

from verify_local_multiplayer_sync import (
    CLIENT_PIPE,
    HOST_PIPE,
    ROOT,
    VerifyFailure,
    disable_bots,
    launch_pair,
    lua,
    parse_key_values,
    snap_to_nav,
    start_host_testrun_and_wait_for_clients,
    stop_games,
)
from verify_run_world_snapshot import start_host_waves, wait_for_run_snapshot


RUNTIME_OUTPUT = ROOT / "runtime" / "run_reward_sync_probe.json"
GOLD_REWARD_TYPE_ID = 0x07DC
PROBE_GOLD_AMOUNT = 7
PROBE_EXPECTED_TIER = 2
REWARD_MATCH_RADIUS = 240.0


CAPTURE_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local function hx(v) return string.format("0x%08X", tonumber(v) or 0) end
local function finite(v)
  return type(v) == "number" and v == v and v ~= math.huge and v ~= -math.huge
end
local function u8(address) return tonumber(sd.debug.read_u8(address)) or 0 end
local function u32(address) return tonumber(sd.debug.read_u32(address)) or 0 end
local scene = sd.world.get_scene()
local player = sd.player.get_state()
emit("scene", scene and (scene.name or scene.kind) or "")
emit("player.actor", player and player.actor_address or 0)
emit("player.gold", player and player.gold or 0)
emit("player.x", player and player.x or 0)
emit("player.y", player and player.y or 0)

local actors = sd.world.list_actors() or {}
local reward_count = 0
local tracked_enemy_count = 0
for _, actor in ipairs(actors) do
  local type_id = tonumber(actor.object_type_id) or 0
  if actor.tracked_enemy then
    tracked_enemy_count = tracked_enemy_count + 1
  end
  if type_id == 0x07DC then
    local address = tonumber(actor.actor_address) or 0
    if address ~= 0 and finite(tonumber(actor.x)) and finite(tonumber(actor.y)) then
      reward_count = reward_count + 1
      local prefix = "reward." .. tostring(reward_count) .. "."
      emit(prefix .. "address", hx(address))
      emit(prefix .. "type", type_id)
      emit(prefix .. "x", string.format("%.3f", tonumber(actor.x) or 0))
      emit(prefix .. "y", string.format("%.3f", tonumber(actor.y) or 0))
      emit(prefix .. "amount_tier", u8(address + 0x13C))
      emit(prefix .. "amount", u32(address + 0x140))
      emit(prefix .. "lifetime", u32(address + 0x144))
      emit(prefix .. "active", u8(address + 0x148))
    end
  end
end
emit("reward.count", reward_count)
emit("tracked_enemy.count", tracked_enemy_count)

local replicated = sd.world.get_replicated_actors and sd.world.get_replicated_actors() or nil
emit("rep.valid", replicated ~= nil)
emit("rep.scene_kind", replicated and replicated.scene_kind or "")
emit("rep.actor_count", replicated and replicated.actor_count or 0)
emit("rep.actor_total_count", replicated and replicated.actor_total_count or 0)
emit("rep.truncated", replicated and replicated.truncated or false)
emit("rep.apply_valid", replicated and replicated.apply_valid or false)
local rep_reward_count = 0
local rep_tracked_enemy_count = 0
if replicated and replicated.actors then
  for _, actor in ipairs(replicated.actors) do
    local type_id = tonumber(actor.object_type_id) or 0
    if actor.tracked_enemy then
      rep_tracked_enemy_count = rep_tracked_enemy_count + 1
    end
    if type_id == 0x07DC then
      rep_reward_count = rep_reward_count + 1
      local prefix = "rep_reward." .. tostring(rep_reward_count) .. "."
      emit(prefix .. "network_id", actor.network_actor_id or 0)
      emit(prefix .. "type", type_id)
      emit(prefix .. "x", string.format("%.3f", tonumber(actor.x) or 0))
      emit(prefix .. "y", string.format("%.3f", tonumber(actor.y) or 0))
      emit(prefix .. "tracked_enemy", actor.tracked_enemy and 1 or 0)
      emit(prefix .. "lifecycle_owned", actor.lifecycle_owned and 1 or 0)
    end
  end
end
emit("rep_reward.count", rep_reward_count)
emit("rep_tracked_enemy.count", rep_tracked_enemy_count)

local loot = sd.world.get_replicated_loot and sd.world.get_replicated_loot() or nil
emit("loot.valid", loot ~= nil)
emit("loot.scene_kind", loot and loot.scene_kind or "")
emit("loot.drop_count", loot and loot.drop_count or 0)
emit("loot.drop_total_count", loot and loot.drop_total_count or 0)
emit("loot.truncated", loot and loot.truncated or false)
local loot_gold_count = 0
if loot and loot.drops then
  for _, drop in ipairs(loot.drops) do
    local type_id = tonumber(drop.object_type_id or drop.native_type_id) or 0
    if type_id == 0x07DC or drop.kind == "Gold" then
      loot_gold_count = loot_gold_count + 1
      local prefix = "loot_gold." .. tostring(loot_gold_count) .. "."
      emit(prefix .. "network_id", drop.network_drop_id or 0)
      emit(prefix .. "type", type_id)
      emit(prefix .. "kind", drop.kind or "")
      emit(prefix .. "kind_id", drop.kind_id or 0)
      emit(prefix .. "amount", drop.amount or 0)
      emit(prefix .. "amount_tier", drop.amount_tier or 0)
      emit(prefix .. "active", drop.active and 1 or 0)
      emit(prefix .. "lifetime", drop.lifetime or 0)
      emit(prefix .. "materialized", drop.materialized and 1 or 0)
      emit(prefix .. "local_actor_address", string.format("0x%08X", tonumber(drop.local_actor_address) or 0))
      emit(prefix .. "x", string.format("%.3f", tonumber(drop.x) or 0))
      emit(prefix .. "y", string.format("%.3f", tonumber(drop.y) or 0))
    end
  end
end
emit("loot_gold.count", loot_gold_count)

local mp = sd.runtime.get_multiplayer_state and sd.runtime.get_multiplayer_state() or nil
emit("mp.valid", mp ~= nil)
emit("mp.participant_count", mp and mp.participant_count or 0)
if mp and mp.participants then
  for index, participant in ipairs(mp.participants) do
    local prefix = "mp.participant." .. tostring(index) .. "."
    emit(prefix .. "id", participant.participant_id or 0)
    emit(prefix .. "name", participant.name or "")
    emit(prefix .. "kind", participant.kind or "")
    emit(prefix .. "controller", participant.controller_kind or "")
    emit(prefix .. "gold", participant.owned_progression and participant.owned_progression.gold or 0)
    emit(prefix .. "gold_revision", participant.owned_progression and participant.owned_progression.gold_revision or 0)
    emit(prefix .. "inventory_revision", participant.owned_progression and participant.owned_progression.inventory_revision or 0)
    emit(prefix .. "spellbook_revision", participant.owned_progression and participant.owned_progression.spellbook_revision or 0)
    emit(prefix .. "statbook_revision", participant.owned_progression and participant.owned_progression.statbook_revision or 0)
  end
end
"""


def values(pipe_name: str, code: str, timeout: float = 10.0) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, code, timeout=timeout))


def parse_int(value: str | None, default: int = 0) -> int:
    if value is None:
        return default
    try:
        if value.startswith(("0x", "0X")):
            return int(value, 16)
        return int(float(value))
    except (TypeError, ValueError):
        return default


def parse_float(value: str | None, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def capture(pipe_name: str) -> dict[str, str]:
    return values(pipe_name, CAPTURE_LUA)


def capture_pair() -> dict[str, dict[str, str]]:
    return {
        "host": capture(HOST_PIPE),
        "client": capture(CLIENT_PIPE),
    }


def reward_rows(capture_values: dict[str, str], prefix: str = "reward.") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    count = parse_int(capture_values.get(prefix + "count"))
    for index in range(1, count + 1):
        row_prefix = f"{prefix}{index}."
        rows.append({
            "address": parse_int(capture_values.get(row_prefix + "address")),
            "type": parse_int(capture_values.get(row_prefix + "type")),
            "x": parse_float(capture_values.get(row_prefix + "x")),
            "y": parse_float(capture_values.get(row_prefix + "y")),
            "amount_tier": parse_int(capture_values.get(row_prefix + "amount_tier")),
            "amount": parse_int(capture_values.get(row_prefix + "amount")),
            "lifetime": parse_int(capture_values.get(row_prefix + "lifetime")),
            "active": parse_int(capture_values.get(row_prefix + "active")),
        })
    return rows


def rep_reward_rows(capture_values: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    count = parse_int(capture_values.get("rep_reward.count"))
    for index in range(1, count + 1):
        row_prefix = f"rep_reward.{index}."
        rows.append({
            "network_id": parse_int(capture_values.get(row_prefix + "network_id")),
            "type": parse_int(capture_values.get(row_prefix + "type")),
            "x": parse_float(capture_values.get(row_prefix + "x")),
            "y": parse_float(capture_values.get(row_prefix + "y")),
            "tracked_enemy": parse_int(capture_values.get(row_prefix + "tracked_enemy")),
            "lifecycle_owned": parse_int(capture_values.get(row_prefix + "lifecycle_owned")),
        })
    return rows


def loot_gold_rows(capture_values: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    count = parse_int(capture_values.get("loot_gold.count"))
    for index in range(1, count + 1):
        row_prefix = f"loot_gold.{index}."
        rows.append({
            "network_id": parse_int(capture_values.get(row_prefix + "network_id")),
            "type": parse_int(capture_values.get(row_prefix + "type")),
            "kind": capture_values.get(row_prefix + "kind", ""),
            "kind_id": parse_int(capture_values.get(row_prefix + "kind_id")),
            "amount": parse_int(capture_values.get(row_prefix + "amount")),
            "amount_tier": parse_int(capture_values.get(row_prefix + "amount_tier")),
            "active": parse_int(capture_values.get(row_prefix + "active")),
            "lifetime": parse_int(capture_values.get(row_prefix + "lifetime")),
            "materialized": parse_int(capture_values.get(row_prefix + "materialized")),
            "local_actor_address": parse_int(capture_values.get(row_prefix + "local_actor_address")),
            "x": parse_float(capture_values.get(row_prefix + "x")),
            "y": parse_float(capture_values.get(row_prefix + "y")),
        })
    return rows


def distance(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(ax - bx, ay - by)


def select_spawned_reward(
    capture_values: dict[str, str],
    *,
    before_addresses: set[int],
    amount: int,
    x: float,
    y: float,
) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for row in reward_rows(capture_values):
        if row["address"] in before_addresses:
            continue
        if row["type"] != GOLD_REWARD_TYPE_ID:
            continue
        if row["amount"] != amount:
            continue
        row = dict(row)
        row["distance"] = round(distance(row["x"], row["y"], x, y), 3)
        if row["distance"] <= REWARD_MATCH_RADIUS:
            candidates.append(row)
    if not candidates:
        return None
    candidates.sort(key=lambda row: row["distance"])
    return candidates[0]


def spawn_gold(pipe_name: str, *, amount: int, x: float, y: float) -> dict[str, str]:
    code = f"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local ok, err = sd.world.spawn_reward({{kind="gold", amount={amount}, x={x:.3f}, y={y:.3f}}})
emit("ok", ok)
emit("err", err or "")
emit("amount", {amount})
emit("x", string.format("%.3f", {x:.3f}))
emit("y", string.format("%.3f", {y:.3f}))
"""
    result = values(pipe_name, code)
    if result.get("ok") != "true":
        raise VerifyFailure(f"spawn_reward failed on {pipe_name}: {result}")
    return result


def wait_for_spawned_host_reward(
    *,
    before_addresses: set[int],
    amount: int,
    x: float,
    y: float,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = capture(HOST_PIPE)
        selected = select_spawned_reward(
            last,
            before_addresses=before_addresses,
            amount=amount,
            x=x,
            y=y,
        )
        if selected is not None:
            return {
                "capture": last,
                "reward": selected,
            }
        time.sleep(0.1)
    raise VerifyFailure(
        "host did not expose queued gold reward through sd.world.list_actors; "
        f"amount={amount} x={x:.3f} y={y:.3f} last={last}"
    )


def select_replicated_loot_gold(
    capture_values: dict[str, str],
    *,
    amount: int,
    x: float,
    y: float,
) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for row in loot_gold_rows(capture_values):
        if row["network_id"] == 0:
            continue
        if row["type"] != GOLD_REWARD_TYPE_ID:
            continue
        if row["amount"] != amount:
            continue
        row = dict(row)
        row["distance"] = round(distance(row["x"], row["y"], x, y), 3)
        if row["distance"] <= REWARD_MATCH_RADIUS:
            candidates.append(row)
    if not candidates:
        return None
    candidates.sort(key=lambda row: row["distance"])
    return candidates[0]


def wait_for_client_replicated_loot(
    *,
    amount: int,
    x: float,
    y: float,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = capture(CLIENT_PIPE)
        selected = select_replicated_loot_gold(
            last,
            amount=amount,
            x=x,
            y=y,
        )
        if selected is not None:
            return {
                "capture": last,
                "drop": selected,
            }
        time.sleep(0.1)
    raise VerifyFailure(
        "client did not receive host-owned replicated loot metadata; "
        f"amount={amount} x={x:.3f} y={y:.3f} last={last}"
    )


def wait_for_host_gold_delta(before_gold: int, amount: int, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = capture(HOST_PIPE)
        current_gold = parse_int(last.get("player.gold"))
        delta = current_gold - before_gold
        if delta >= amount:
            return {
                "capture": last,
                "before_gold": before_gold,
                "after_gold": current_gold,
                "delta": delta,
            }
        time.sleep(0.1)
    current_gold = parse_int(last.get("player.gold"))
    raise VerifyFailure(
        "host gold did not change after spawning a pickup-range reward; "
        f"before={before_gold} after={current_gold} amount={amount} last={last}"
    )


def summarize_reward_boundary(
    before_pair: dict[str, dict[str, str]],
    after_pair: dict[str, dict[str, str]],
    selected_reward: dict[str, Any],
    selected_replicated_loot: dict[str, Any],
) -> dict[str, Any]:
    host_rewards = reward_rows(after_pair["host"])
    client_rewards = reward_rows(after_pair["client"])
    client_rep_rewards = rep_reward_rows(after_pair["client"])
    client_loot_gold = loot_gold_rows(after_pair["client"])
    host_reward_addresses = {row["address"] for row in host_rewards}
    before_host_reward_addresses = {
        row["address"] for row in reward_rows(before_pair["host"])
    }
    new_host_reward_addresses = sorted(host_reward_addresses - before_host_reward_addresses)
    return {
        "host_scene": after_pair["host"].get("scene", ""),
        "client_scene": after_pair["client"].get("scene", ""),
        "host_reward_count_before": parse_int(before_pair["host"].get("reward.count")),
        "host_reward_count_after": len(host_rewards),
        "client_reward_count_after": len(client_rewards),
        "client_replicated_reward_count_after": len(client_rep_rewards),
        "client_replicated_loot_count_after": len(client_loot_gold),
        "host_new_reward_addresses": [f"0x{address:08X}" for address in new_host_reward_addresses],
        "host_selected_reward": selected_reward,
        "client_selected_replicated_loot": selected_replicated_loot,
        "host_amount_matches": selected_reward.get("amount") == PROBE_GOLD_AMOUNT,
        "host_tier_matches": selected_reward.get("amount_tier") == PROBE_EXPECTED_TIER,
        "host_reward_active_observed": selected_reward.get("active") != 0,
        "client_has_local_gold_reward": len(client_rewards) > 0,
        "client_has_replicated_gold_reward": len(client_rep_rewards) > 0,
        "client_has_world_snapshot_gold_reward": len(client_rep_rewards) > 0,
        "client_has_replicated_loot_gold": len(client_loot_gold) > 0,
        "client_materialized_replicated_loot_gold": (
            selected_replicated_loot.get("materialized") == 1 and
            selected_replicated_loot.get("local_actor_address", 0) != 0
        ),
        "client_replicated_loot_amount_matches": (
            selected_replicated_loot.get("amount") == PROBE_GOLD_AMOUNT
        ),
        "client_replicated_loot_tier_matches": (
            selected_replicated_loot.get("amount_tier") == PROBE_EXPECTED_TIER
        ),
        "client_snapshot_actor_count": parse_int(after_pair["client"].get("rep.actor_count")),
        "client_snapshot_tracked_enemy_count": parse_int(
            after_pair["client"].get("rep_tracked_enemy.count")
        ),
        "client_loot_snapshot_drop_count": parse_int(after_pair["client"].get("loot.drop_count")),
        "client_loot_snapshot_total_drop_count": parse_int(
            after_pair["client"].get("loot.drop_total_count")
        ),
    }


def setup_live_run_pair(max_attempts: int = 3) -> dict[str, Any]:
    last_error = ""
    for attempt in range(1, max_attempts + 1):
        try:
            stop_games()
            launch = launch_pair()
            disable_bots()
            host_run_entry = start_host_testrun_and_wait_for_clients()
            start_waves = start_host_waves()
            snapshot_ready = wait_for_run_snapshot(require_complete_lifecycle=True)
            return {
                "attempt": attempt,
                "launch": launch,
                "host_run_entry": host_run_entry,
                "start_waves": start_waves,
                "snapshot_ready": snapshot_ready,
            }
        except Exception as exc:
            last_error = str(exc)
            stop_games()
            time.sleep(1.0)
    raise VerifyFailure(f"failed to prepare live run pair after {max_attempts} attempts: {last_error}")


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": False}
    if not args.no_launch:
        result["setup"] = setup_live_run_pair(max_attempts=args.attempts)

    before_pair = capture_pair()
    result["before"] = before_pair
    before_addresses = {row["address"] for row in reward_rows(before_pair["host"])}
    player_x = parse_float(before_pair["host"].get("player.x"))
    player_y = parse_float(before_pair["host"].get("player.y"))

    requested_stationary_x = player_x + args.spawn_offset_x
    requested_stationary_y = player_y + args.spawn_offset_y
    stationary_x, stationary_y = snap_to_nav(
        HOST_PIPE,
        requested_stationary_x,
        requested_stationary_y,
    )
    result["stationary_spawn_request"] = {
        "requested_x": requested_stationary_x,
        "requested_y": requested_stationary_y,
        "snapped_x": stationary_x,
        "snapped_y": stationary_y,
    }
    result["stationary_spawn"] = spawn_gold(
        HOST_PIPE,
        amount=PROBE_GOLD_AMOUNT,
        x=stationary_x,
        y=stationary_y,
    )
    spawned = wait_for_spawned_host_reward(
        before_addresses=before_addresses,
        amount=PROBE_GOLD_AMOUNT,
        x=stationary_x,
        y=stationary_y,
        timeout=args.spawn_timeout,
    )
    replicated_loot = wait_for_client_replicated_loot(
        amount=PROBE_GOLD_AMOUNT,
        x=stationary_x,
        y=stationary_y,
        timeout=args.loot_timeout,
    )
    result["client_replicated_loot"] = replicated_loot
    time.sleep(args.post_spawn_settle)
    after_pair = capture_pair()
    result["after_stationary_spawn"] = after_pair
    reward_boundary = summarize_reward_boundary(
        before_pair,
        after_pair,
        spawned["reward"],
        replicated_loot["drop"],
    )
    result["reward_boundary"] = reward_boundary

    before_pickup = capture(HOST_PIPE)
    before_gold = parse_int(before_pickup.get("player.gold"))
    pickup_x = parse_float(before_pickup.get("player.x"))
    pickup_y = parse_float(before_pickup.get("player.y"))
    result["pickup_spawn"] = spawn_gold(
        HOST_PIPE,
        amount=PROBE_GOLD_AMOUNT,
        x=pickup_x,
        y=pickup_y,
    )
    result["pickup"] = wait_for_host_gold_delta(
        before_gold,
        PROBE_GOLD_AMOUNT,
        timeout=args.pickup_timeout,
    )
    result["after_pickup_pair"] = capture_pair()

    result["ok"] = (
        reward_boundary["host_amount_matches"]
        and reward_boundary["host_tier_matches"]
        and reward_boundary["client_has_local_gold_reward"]
        and not reward_boundary["client_has_world_snapshot_gold_reward"]
        and reward_boundary["client_has_replicated_loot_gold"]
        and reward_boundary["client_materialized_replicated_loot_gold"]
        and reward_boundary["client_replicated_loot_amount_matches"]
        and reward_boundary["client_replicated_loot_tier_matches"]
        and result["pickup"]["delta"] >= PROBE_GOLD_AMOUNT
    )
    result["conclusion"] = {
        "host_gold_drop_fields_verified": (
            reward_boundary["host_amount_matches"]
            and reward_boundary["host_tier_matches"]
        ),
        "host_reward_active_observed": reward_boundary["host_reward_active_observed"],
        "current_world_snapshot_excludes_gold_drops": (
            not reward_boundary["client_has_world_snapshot_gold_reward"]
        ),
        "client_receives_host_loot_metadata": (
            reward_boundary["client_has_replicated_loot_gold"]
            and reward_boundary["client_replicated_loot_amount_matches"]
            and reward_boundary["client_replicated_loot_tier_matches"]
        ),
        "client_materializes_host_loot_actor": (
            reward_boundary["client_has_local_gold_reward"]
            and reward_boundary["client_materialized_replicated_loot_gold"]
        ),
        "stock_pickup_mutates_host_global_gold": result["pickup"]["delta"] >= PROBE_GOLD_AMOUNT,
        "replication_safe_without_pickup_hook": False,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-launch", action="store_true")
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--spawn-timeout", type=float, default=8.0)
    parser.add_argument("--loot-timeout", type=float, default=8.0)
    parser.add_argument("--pickup-timeout", type=float, default=8.0)
    parser.add_argument("--post-spawn-settle", type=float, default=0.6)
    parser.add_argument("--spawn-offset-x", type=float, default=180.0)
    parser.add_argument("--spawn-offset-y", type=float, default=0.0)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    try:
        result = run_probe(args)
        RUNTIME_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({
            "ok": result["ok"],
            "reward_boundary": result.get("reward_boundary"),
            "pickup": result.get("pickup"),
            "conclusion": result.get("conclusion"),
            "output": str(RUNTIME_OUTPUT),
        }, indent=2, sort_keys=True))
        return 0 if result["ok"] else 1
    except Exception as exc:
        result["error"] = str(exc)
        RUNTIME_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1
    finally:
        if not args.no_launch:
            stop_games()


if __name__ == "__main__":
    raise SystemExit(main())
