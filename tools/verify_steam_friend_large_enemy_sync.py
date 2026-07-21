#!/usr/bin/env python3
"""Verify more than 64 host-owned enemies over a genuine Steam friend pair."""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import verify_multiplayer_primary_kill_stress as primary
from steam_friend_active_pair import (
    CLIENT_ENDPOINT,
    HOST_ENDPOINT,
    ROOT,
    SteamFriendActivePair,
)
from verify_local_multiplayer_sync import VerifyFailure, parse_key_values


DEFAULT_OUTPUT = ROOT / "runtime/steam_friend_large_enemy_sync.json"
DEFAULT_ENEMY_COUNT = 80
POSITION_TOLERANCE = 16.0
CLIENT_TICK_RATE_SAMPLE_SECONDS = 3.0
MINIMUM_CLIENT_TICK_RATE_HZ = 30.0
MINIMUM_LOADED_TO_BASELINE_TICK_RATE_RATIO = 0.75
MINIMUM_CLIENT_RENDER_FRAME_RATE_HZ = 30.0
MINIMUM_LOADED_TO_BASELINE_RENDER_FRAME_RATE_RATIO = 0.75


HOST_CAPTURE_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local live = 0
local tracked = 0
local unique_addresses = {}
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  local address = tonumber(actor.actor_address) or 0
  local hp = tonumber(actor.hp) or 0
  local max_hp = tonumber(actor.max_hp) or 0
  if actor.tracked_enemy and address ~= 0 then
    tracked = tracked + 1
  end
  if actor.tracked_enemy and not actor.dead and address ~= 0 and max_hp > 0 and hp > 0.05 then
    live = live + 1
    unique_addresses[address] = true
  end
end
local unique_count = 0
for _ in pairs(unique_addresses) do unique_count = unique_count + 1 end
local scene = sd.world.get_scene()
emit("scene", scene and (scene.name or scene.kind) or "")
emit("live", live)
emit("tracked", tracked)
emit("unique_addresses", unique_count)
"""


CLIENT_CAPTURE_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local function finite(value)
  return type(value) == "number" and value == value and
    value ~= math.huge and value ~= -math.huge
end

local local_by_address = {}
local local_live = 0
local local_tracked = 0
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  local address = tonumber(actor.actor_address) or 0
  local hp = tonumber(actor.hp) or 0
  local max_hp = tonumber(actor.max_hp) or 0
  if actor.tracked_enemy and address ~= 0 then
    local_tracked = local_tracked + 1
  end
  if actor.tracked_enemy and not actor.dead and address ~= 0 and
      max_hp > 0 and hp > 0.05 then
    local_live = local_live + 1
    local_by_address[address] = actor
  end
end

local replicated = sd.world.get_replicated_actors and
  sd.world.get_replicated_actors() or nil
local snapshot_by_id = {}
local live_snapshot_by_id = {}
local snapshot_live = 0
local snapshot_unique_ids = 0
local snapshot_tracked = 0
local snapshot_dead_tracked = 0
local snapshot_non_enemy = 0
for _, actor in ipairs(replicated and replicated.actors or {}) do
  local network_id = tonumber(actor.network_actor_id) or 0
  local hp = tonumber(actor.hp) or 0
  local max_hp = tonumber(actor.max_hp) or 0
  if network_id ~= 0 then
    snapshot_by_id[network_id] = actor
  end
  if actor.tracked_enemy then
    snapshot_tracked = snapshot_tracked + 1
    if actor.dead then snapshot_dead_tracked = snapshot_dead_tracked + 1 end
  else
    snapshot_non_enemy = snapshot_non_enemy + 1
  end
  if actor.tracked_enemy and not actor.dead and network_id ~= 0 and
      max_hp > 0 and hp > 0.05 then
    snapshot_live = snapshot_live + 1
    if live_snapshot_by_id[network_id] == nil then
      snapshot_unique_ids = snapshot_unique_ids + 1
    end
    live_snapshot_by_id[network_id] = actor
  end
end

local matched = 0
local unique_binding_ids = {}
local unique_local_addresses = {}
local binding_tracked = 0
local binding_non_enemy = 0
local binding_orphan = 0
local compared = 0
local max_distance = 0.0
for _, binding in ipairs(replicated and replicated.bindings or {}) do
  local network_id = tonumber(binding.network_actor_id) or 0
  local address = tonumber(binding.local_actor_address) or 0
  local authoritative = snapshot_by_id[network_id]
  if authoritative == nil then
    binding_orphan = binding_orphan + 1
  elseif authoritative.tracked_enemy then
    binding_tracked = binding_tracked + 1
  else
    binding_non_enemy = binding_non_enemy + 1
  end
  local snapshot = live_snapshot_by_id[network_id]
  local local_actor = local_by_address[address]
  if binding.matched and not binding.parked and network_id ~= 0 and
      address ~= 0 and snapshot ~= nil and local_actor ~= nil then
    matched = matched + 1
    unique_binding_ids[network_id] = true
    unique_local_addresses[address] = true
    if finite(tonumber(snapshot.x)) and finite(tonumber(snapshot.y)) and
        finite(tonumber(local_actor.x)) and finite(tonumber(local_actor.y)) then
      compared = compared + 1
      local dx = tonumber(local_actor.x) - tonumber(snapshot.x)
      local dy = tonumber(local_actor.y) - tonumber(snapshot.y)
      local distance = math.sqrt(dx * dx + dy * dy)
      if distance > max_distance then max_distance = distance end
    end
  end
end

local unique_binding_id_count = 0
for _ in pairs(unique_binding_ids) do unique_binding_id_count = unique_binding_id_count + 1 end
local unique_local_address_count = 0
for _ in pairs(unique_local_addresses) do unique_local_address_count = unique_local_address_count + 1 end
local scene = sd.world.get_scene()
emit("scene", scene and (scene.name or scene.kind) or "")
emit("snapshot_valid", replicated ~= nil)
emit("snapshot_count", replicated and replicated.actor_count or 0)
emit("snapshot_total_count", replicated and replicated.actor_total_count or 0)
emit("snapshot_live", snapshot_live)
emit("snapshot_unique_ids", snapshot_unique_ids)
emit("snapshot_tracked", snapshot_tracked)
emit("snapshot_dead_tracked", snapshot_dead_tracked)
emit("snapshot_non_enemy", snapshot_non_enemy)
emit("apply_valid", replicated and replicated.apply_valid or false)
emit("binding_count", replicated and replicated.binding_count or 0)
emit("binding_tracked", binding_tracked)
emit("binding_non_enemy", binding_non_enemy)
emit("binding_orphan", binding_orphan)
emit("parked", replicated and replicated.parked_actor_count or 0)
emit("matched", matched)
emit("unique_binding_ids", unique_binding_id_count)
emit("unique_local_addresses", unique_local_address_count)
emit("local_live", local_live)
emit("local_tracked", local_tracked)
emit("compared", compared)
emit("max_distance", string.format("%.3f", max_distance))
emit("failed_remove", replicated and replicated.failed_remove_actor_count or 0)
"""


TRANSPORT_DIAGNOSTICS_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local state = sd.runtime and sd.runtime.get_multiplayer_state and
  sd.runtime.get_multiplayer_state() or nil
emit("valid", state ~= nil)
emit("packets_sent", state and state.transport_packets_sent or 0)
emit("packets_received", state and state.transport_packets_received or 0)
emit("steam_send_failures", state and state.steam_send_failures or 0)
emit("steam_reliable_send_failures", state and state.steam_reliable_send_failures or 0)
emit("last_steam_send_failure_result", state and state.last_steam_send_failure_result or 0)
"""


CLIENT_TICK_RATE_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
emit("valid", player ~= nil)
emit("tick_count", player and player.local_player_tick_count or 0)
emit("observed_ms", player and player.local_player_tick_observed_ms or 0)
"""


CLIENT_RENDER_FRAME_RATE_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local frame = sd.runtime and sd.runtime.get_frame_state and
  sd.runtime.get_frame_state() or nil
emit("valid", frame ~= nil)
emit("frame_count", frame and frame.frame_count or 0)
emit("observed_ms", frame and frame.observed_ms or 0)
"""


HOST_REMOVE_SUBSET_LUA = r"""
local requested = tonumber("__COUNT__") or 0
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local hp_offset = sd.debug.layout_offset("enemy_current_hp")
local live = {}
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  local address = tonumber(actor.actor_address) or 0
  local hp = tonumber(actor.hp) or 0
  local max_hp = tonumber(actor.max_hp) or 0
  if actor.tracked_enemy and not actor.dead and address ~= 0 and
      max_hp > 0 and hp > 0.05 then
    table.insert(live, {
      address = address,
      x = tonumber(actor.x) or 0,
      y = tonumber(actor.y) or 0,
    })
  end
end
table.sort(live, function(left, right)
  if left.y ~= right.y then return left.y < right.y end
  if left.x ~= right.x then return left.x < right.x end
  return left.address < right.address
end)
local selected = math.min(requested, #live)
local hp_writes = 0
local deaths_triggered = 0
for index = 1, selected do
  local address = live[index].address
  if hp_offset ~= nil and sd.debug.write_float(address + hp_offset, 0.0) then
    hp_writes = hp_writes + 1
  end
  if sd.world.trigger_enemy_death ~= nil then
    local ok = sd.world.trigger_enemy_death(address)
    if ok then deaths_triggered = deaths_triggered + 1 end
  end
end
emit("available", #live)
emit("selected", selected)
emit("hp_writes", hp_writes)
emit("deaths_triggered", deaths_triggered)
"""


def integer(values: dict[str, str], key: str) -> int:
    try:
        return int(float(values.get(key, "0")))
    except (TypeError, ValueError):
        return 0


def floating(values: dict[str, str], key: str) -> float:
    try:
        return float(values.get(key, "nan"))
    except (TypeError, ValueError):
        return float("nan")


def configure(pair: SteamFriendActivePair) -> None:
    primary.lua = pair.lua
    primary.HOST_PIPE = HOST_ENDPOINT
    primary.CLIENT_PIPE = CLIENT_ENDPOINT


def capture_transport_diagnostics(pair: SteamFriendActivePair) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for side, endpoint in (("host", HOST_ENDPOINT), ("client", CLIENT_ENDPOINT)):
        values = parse_key_values(pair.lua(endpoint, TRANSPORT_DIAGNOSTICS_LUA, timeout=12.0))
        if values.get("valid") != "true":
            raise VerifyFailure(f"{side} transport diagnostics are unavailable")
        result[side] = {
            "packets_sent": integer(values, "packets_sent"),
            "packets_received": integer(values, "packets_received"),
            "steam_send_failures": integer(values, "steam_send_failures"),
            "steam_reliable_send_failures": integer(
                values, "steam_reliable_send_failures"
            ),
            "last_steam_send_failure_result": integer(
                values, "last_steam_send_failure_result"
            ),
        }
    return result


def capture_client_tick_counter(pair: SteamFriendActivePair) -> dict[str, int]:
    values = parse_key_values(
        pair.lua(CLIENT_ENDPOINT, CLIENT_TICK_RATE_LUA, timeout=12.0)
    )
    if values.get("valid") != "true":
        raise VerifyFailure("client player tick counter is unavailable")
    return {
        "tick_count": integer(values, "tick_count"),
        "observed_ms": integer(values, "observed_ms"),
    }


def measure_client_tick_rate(
    pair: SteamFriendActivePair,
    sample_seconds: float = CLIENT_TICK_RATE_SAMPLE_SECONDS,
) -> dict[str, Any]:
    before = capture_client_tick_counter(pair)
    time.sleep(sample_seconds)
    after = capture_client_tick_counter(pair)
    tick_delta = after["tick_count"] - before["tick_count"]
    observed_ms_delta = after["observed_ms"] - before["observed_ms"]
    if tick_delta <= 0 or observed_ms_delta <= 0:
        raise VerifyFailure(
            "client player ticks did not advance during the load sample: "
            f"before={before} after={after}"
        )
    return {
        "before": before,
        "after": after,
        "tick_delta": tick_delta,
        "observed_ms_delta": observed_ms_delta,
        "tick_rate_hz": tick_delta * 1000.0 / observed_ms_delta,
    }


def capture_client_render_frame_counter(
    pair: SteamFriendActivePair,
) -> dict[str, int]:
    values = parse_key_values(
        pair.lua(CLIENT_ENDPOINT, CLIENT_RENDER_FRAME_RATE_LUA, timeout=12.0)
    )
    if values.get("valid") != "true":
        raise VerifyFailure("client render frame counter is unavailable")
    return {
        "frame_count": integer(values, "frame_count"),
        "observed_ms": integer(values, "observed_ms"),
    }


def measure_client_render_frame_rate(
    pair: SteamFriendActivePair,
    sample_seconds: float = CLIENT_TICK_RATE_SAMPLE_SECONDS,
) -> dict[str, Any]:
    before = capture_client_render_frame_counter(pair)
    time.sleep(sample_seconds)
    after = capture_client_render_frame_counter(pair)
    frame_delta = after["frame_count"] - before["frame_count"]
    observed_ms_delta = after["observed_ms"] - before["observed_ms"]
    if frame_delta <= 0 or observed_ms_delta <= 0:
        raise VerifyFailure(
            "client D3D frames did not advance during the load sample: "
            f"before={before} after={after}"
        )
    return {
        "before": before,
        "after": after,
        "frame_delta": frame_delta,
        "observed_ms_delta": observed_ms_delta,
        "frame_rate_hz": frame_delta * 1000.0 / observed_ms_delta,
    }


def transport_deltas(
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for side in ("host", "client"):
        result[side] = {
            key: after[side][key] - before[side][key]
            for key in (
                "packets_sent",
                "packets_received",
                "steam_send_failures",
                "steam_reliable_send_failures",
            )
        }
        result[side]["last_steam_send_failure_result"] = after[side][
            "last_steam_send_failure_result"
        ]
    return result


def capture(pair: SteamFriendActivePair) -> dict[str, Any]:
    host = parse_key_values(pair.lua(HOST_ENDPOINT, HOST_CAPTURE_LUA, timeout=12.0))
    client = parse_key_values(pair.lua(CLIENT_ENDPOINT, CLIENT_CAPTURE_LUA, timeout=12.0))
    return {
        "host": host,
        "client": client,
        "summary": {
            "host_live": integer(host, "live"),
            "host_tracked": integer(host, "tracked"),
            "host_unique_addresses": integer(host, "unique_addresses"),
            "client_snapshot_count": integer(client, "snapshot_count"),
            "client_snapshot_total_count": integer(client, "snapshot_total_count"),
            "client_snapshot_live": integer(client, "snapshot_live"),
            "client_snapshot_unique_ids": integer(client, "snapshot_unique_ids"),
            "client_snapshot_tracked": integer(client, "snapshot_tracked"),
            "client_snapshot_dead_tracked": integer(
                client, "snapshot_dead_tracked"
            ),
            "client_snapshot_non_enemy": integer(client, "snapshot_non_enemy"),
            "client_binding_count": integer(client, "binding_count"),
            "client_binding_tracked": integer(client, "binding_tracked"),
            "client_binding_non_enemy": integer(client, "binding_non_enemy"),
            "client_binding_orphan": integer(client, "binding_orphan"),
            "client_parked": integer(client, "parked"),
            "client_matched": integer(client, "matched"),
            "client_unique_binding_ids": integer(client, "unique_binding_ids"),
            "client_unique_local_addresses": integer(client, "unique_local_addresses"),
            "client_local_live": integer(client, "local_live"),
            "client_local_tracked": integer(client, "local_tracked"),
            "client_compared": integer(client, "compared"),
            "client_max_distance": floating(client, "max_distance"),
            "client_failed_remove": integer(client, "failed_remove"),
        },
    }


def static_world_baseline(sample: dict[str, Any]) -> dict[str, int]:
    summary = sample["summary"]
    return {
        "snapshot_non_enemy": summary["client_snapshot_non_enemy"],
        "binding_non_enemy": summary["client_binding_non_enemy"],
    }


def is_exact_parity(
    sample: dict[str, Any],
    expected_count: int,
    baseline: dict[str, int],
) -> bool:
    summary = sample["summary"]
    expected_snapshot_count = expected_count + baseline["snapshot_non_enemy"]
    expected_binding_count = expected_count + baseline["binding_non_enemy"]
    return (
        sample["host"].get("scene") == "testrun"
        and sample["client"].get("scene") == "testrun"
        and sample["client"].get("snapshot_valid") == "true"
        and sample["client"].get("apply_valid") == "true"
        and summary["host_live"] == expected_count
        and summary["host_tracked"] == expected_count
        and summary["host_unique_addresses"] == expected_count
        and summary["client_snapshot_count"] == expected_snapshot_count
        and summary["client_snapshot_total_count"] == expected_snapshot_count
        and summary["client_snapshot_live"] == expected_count
        and summary["client_snapshot_unique_ids"] == expected_count
        and summary["client_snapshot_tracked"] == expected_count
        and summary["client_snapshot_dead_tracked"] == 0
        and summary["client_snapshot_non_enemy"] == baseline["snapshot_non_enemy"]
        and summary["client_binding_count"] == expected_binding_count
        and summary["client_binding_tracked"] == expected_count
        and summary["client_binding_non_enemy"] == baseline["binding_non_enemy"]
        and summary["client_binding_orphan"] == 0
        and summary["client_parked"] == 0
        and summary["client_matched"] == expected_count
        and summary["client_unique_binding_ids"] == expected_count
        and summary["client_unique_local_addresses"] == expected_count
        and summary["client_local_live"] == expected_count
        and summary["client_local_tracked"] == expected_count
        and summary["client_compared"] == expected_count
        and summary["client_max_distance"] <= POSITION_TOLERANCE
        and summary["client_failed_remove"] == 0
    )


def is_zero_state(sample: dict[str, Any]) -> bool:
    summary = sample["summary"]
    return (
        sample["host"].get("scene") == "testrun"
        and sample["client"].get("scene") == "testrun"
        and sample["client"].get("snapshot_valid") == "true"
        and sample["client"].get("apply_valid") == "true"
        and summary["host_live"] == 0
        and summary["host_tracked"] == 0
        and summary["client_snapshot_count"]
        == summary["client_snapshot_non_enemy"]
        and summary["client_snapshot_total_count"]
        == summary["client_snapshot_non_enemy"]
        and summary["client_snapshot_live"] == 0
        and summary["client_snapshot_unique_ids"] == 0
        and summary["client_snapshot_tracked"] == 0
        and summary["client_snapshot_dead_tracked"] == 0
        and summary["client_binding_count"]
        == summary["client_binding_non_enemy"]
        and summary["client_binding_tracked"] == 0
        and summary["client_binding_orphan"] == 0
        and summary["client_parked"] == 0
        and summary["client_matched"] == 0
        and summary["client_local_live"] == 0
        and summary["client_local_tracked"] == 0
        and summary["client_failed_remove"] == 0
    )


def wait_for_zero(
    pair: SteamFriendActivePair,
    timeout: float,
    baseline: dict[str, int] | None = None,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = capture(pair)
        if is_zero_state(last) and (
            baseline is None or static_world_baseline(last) == baseline
        ):
            return last
        time.sleep(0.15)
    raise VerifyFailure(f"enemy cleanup did not converge to zero: {last}")


def remove_host_enemy_subset(
    pair: SteamFriendActivePair,
    count: int,
) -> dict[str, str]:
    values = parse_key_values(
        pair.lua(
            HOST_ENDPOINT,
            HOST_REMOVE_SUBSET_LUA.replace("__COUNT__", str(count)),
            timeout=12.0,
        )
    )
    if (
        integer(values, "selected") != count
        or integer(values, "hp_writes") != count
        or integer(values, "deaths_triggered") != count
    ):
        raise VerifyFailure(f"host did not authoritatively remove {count} enemies: {values}")
    return values


def wait_for_stable_parity(
    pair: SteamFriendActivePair,
    expected_count: int,
    baseline: dict[str, int],
    timeout: float,
    stable_seconds: float,
    samples: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    deadline = time.monotonic() + timeout
    stable_since: float | None = None
    if samples is None:
        samples = []
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = capture(pair)
        samples.append(
            {
                "elapsed": round(timeout - max(0.0, deadline - time.monotonic()), 3),
                **last["summary"],
            }
        )
        if is_exact_parity(last, expected_count, baseline):
            now = time.monotonic()
            if stable_since is None:
                stable_since = now
            if now - stable_since >= stable_seconds:
                return last, samples
        else:
            stable_since = None
        time.sleep(0.15)
    raise VerifyFailure(
        f"{expected_count}-enemy Steam parity did not become stable: {last}"
    )


def run(
    pair: SteamFriendActivePair,
    enemy_count: int,
    timeout: float,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if enemy_count <= 64:
        raise VerifyFailure("large-world regression must exercise more than 64 enemies")

    discovered = pair.discover()
    if discovered["host"]["scene"] != "testrun" or discovered["client"]["scene"] != "testrun":
        raise VerifyFailure(f"Steam friend pair is not in a shared test run: {discovered}")
    configure(pair)

    if result is None:
        result = {}
    result.update(
        {
            "pair": discovered,
            "enemy_count": enemy_count,
            "position_tolerance": POSITION_TOLERANCE,
        }
    )
    result["transport_before"] = capture_transport_diagnostics(pair)
    result["manual_mode"] = {
        "host": primary.set_manual_spawner_test_mode(HOST_ENDPOINT, True),
        "client": primary.set_manual_spawner_test_mode(CLIENT_ENDPOINT, True),
    }
    for side, state in result["manual_mode"].items():
        if state.get("ok") != "true" or state.get("active") != "true":
            raise VerifyFailure(f"failed to enable manual spawner mode on {side}: {state}")

    result["spawner_ready"] = {
        "host": primary.wait_for_manual_spawner_ready(HOST_ENDPOINT, timeout=timeout),
        "client": primary.wait_for_manual_spawner_ready(CLIENT_ENDPOINT, timeout=timeout),
    }
    result["cleanup"] = primary.cleanup_live_enemies()
    result["zero_state"] = wait_for_zero(pair, timeout)
    result["static_world_baseline"] = static_world_baseline(result["zero_state"])
    result["client_tick_rate_baseline"] = measure_client_tick_rate(pair)
    result["client_render_frame_rate_baseline"] = measure_client_render_frame_rate(pair)

    spawns: list[dict[str, Any]] = []
    for index in range(enemy_count):
        column = index % 10
        row = index // 10
        x = 900.0 + column * 105.0
        y = 2050.0 + row * 90.0
        spawned = primary.spawn_one_enemy(
            x,
            y,
            setup_hp=50000.0,
            freeze_on_spawn=False,
        )
        spawns.append(
            {
                "index": index + 1,
                "actor_address": spawned["actor_address"],
                "network_actor_id": primary.parse_int(
                    spawned["result"].get("network_actor_id")
                ),
                "x": x,
                "y": y,
            }
        )
    result["spawns"] = spawns
    if len({row["network_actor_id"] for row in spawns}) != enemy_count:
        raise VerifyFailure("manual host spawns did not receive unique network actor IDs")

    result["samples"] = []
    final, samples = wait_for_stable_parity(
        pair,
        enemy_count,
        result["static_world_baseline"],
        timeout,
        stable_seconds=2.0,
        samples=result["samples"],
    )
    result["final"] = final
    result["client_tick_rate_loaded"] = measure_client_tick_rate(pair)
    result["client_render_frame_rate_loaded"] = measure_client_render_frame_rate(pair)
    baseline_tick_rate = result["client_tick_rate_baseline"]["tick_rate_hz"]
    loaded_tick_rate = result["client_tick_rate_loaded"]["tick_rate_hz"]
    loaded_to_baseline_ratio = (
        loaded_tick_rate / baseline_tick_rate if baseline_tick_rate > 0.0 else 0.0
    )
    result["client_tick_rate_loaded_to_baseline_ratio"] = loaded_to_baseline_ratio
    if loaded_tick_rate < MINIMUM_CLIENT_TICK_RATE_HZ:
        raise VerifyFailure(
            "client tick rate fell below the loaded-run floor: "
            f"loaded={loaded_tick_rate:.2f}Hz "
            f"minimum={MINIMUM_CLIENT_TICK_RATE_HZ:.2f}Hz"
        )
    if loaded_to_baseline_ratio < MINIMUM_LOADED_TO_BASELINE_TICK_RATE_RATIO:
        raise VerifyFailure(
            "client tick rate regressed under the 80-enemy load: "
            f"baseline={baseline_tick_rate:.2f}Hz loaded={loaded_tick_rate:.2f}Hz "
            f"ratio={loaded_to_baseline_ratio:.3f} "
            f"minimum_ratio={MINIMUM_LOADED_TO_BASELINE_TICK_RATE_RATIO:.3f}"
        )
    baseline_render_frame_rate = result["client_render_frame_rate_baseline"][
        "frame_rate_hz"
    ]
    loaded_render_frame_rate = result["client_render_frame_rate_loaded"][
        "frame_rate_hz"
    ]
    loaded_to_baseline_render_frame_ratio = (
        loaded_render_frame_rate / baseline_render_frame_rate
        if baseline_render_frame_rate > 0.0
        else 0.0
    )
    result["client_render_frame_rate_loaded_to_baseline_ratio"] = (
        loaded_to_baseline_render_frame_ratio
    )
    if loaded_render_frame_rate < MINIMUM_CLIENT_RENDER_FRAME_RATE_HZ:
        raise VerifyFailure(
            "client render frame rate fell below the loaded-run floor: "
            f"loaded={loaded_render_frame_rate:.2f}Hz "
            f"minimum={MINIMUM_CLIENT_RENDER_FRAME_RATE_HZ:.2f}Hz"
        )
    if (
        loaded_to_baseline_render_frame_ratio
        < MINIMUM_LOADED_TO_BASELINE_RENDER_FRAME_RATE_RATIO
    ):
        raise VerifyFailure(
            "client render frame rate regressed under the active 80-enemy load: "
            f"baseline={baseline_render_frame_rate:.2f}Hz "
            f"loaded={loaded_render_frame_rate:.2f}Hz "
            f"ratio={loaded_to_baseline_render_frame_ratio:.3f} "
            "minimum_ratio="
            f"{MINIMUM_LOADED_TO_BASELINE_RENDER_FRAME_RATE_RATIO:.3f}"
        )
    partial_count = enemy_count // 2
    result["cleanup_after_parity"] = remove_host_enemy_subset(pair, partial_count)
    result["partial_samples"] = []
    partial, partial_samples = wait_for_stable_parity(
        pair,
        enemy_count - partial_count,
        result["static_world_baseline"],
        timeout,
        stable_seconds=2.0,
        samples=result["partial_samples"],
    )
    result["partial_expected_count"] = enemy_count - partial_count
    result["partial"] = partial
    result["cleanup_after_partial"] = primary.cleanup_live_enemies()
    result["zero_after_cleanup"] = wait_for_zero(
        pair,
        timeout,
        result["static_world_baseline"],
    )
    result["transport_after"] = capture_transport_diagnostics(pair)
    result["transport_delta"] = transport_deltas(
        result["transport_before"], result["transport_after"]
    )
    for side in ("host", "client"):
        diagnostics = result["transport_delta"][side]
        if diagnostics["steam_send_failures"] != 0:
            raise VerifyFailure(
                f"{side} Steam transport rejected packets during the large-world cycle: "
                f"{diagnostics}"
            )
    result["ok"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enemy-count", type=int, default=DEFAULT_ENEMY_COUNT)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    pair = SteamFriendActivePair()
    result: dict[str, Any] = {"ok": False}
    return_code = 1
    try:
        run(pair, args.enemy_count, args.timeout, result)
        return_code = 0
    except Exception as exc:
        result["error"] = str(exc)
        result["error_type"] = type(exc).__name__
        result["traceback"] = traceback.format_exc()
    finally:
        pair.close()
        result = pair.redact(result)
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
                    "enemy_count": args.enemy_count,
                    "final": result.get("final", {}).get("summary"),
                    "output": str(args.output),
                },
                indent=2,
                sort_keys=True,
            )
        )
    return return_code


if __name__ == "__main__":
    sys.exit(main())
