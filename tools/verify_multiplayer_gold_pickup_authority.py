#!/usr/bin/env python3
"""Verify host-authoritative multiplayer gold pickup request/result flow."""

from __future__ import annotations

import argparse
import json
import math
import time
from typing import Any

from probe_run_reward_sync import (
    PROBE_EXPECTED_TIER,
    PROBE_GOLD_AMOUNT,
    capture as reward_capture,
    loot_gold_rows,
    reward_rows,
    spawn_gold,
    wait_for_client_replicated_loot,
    wait_for_spawned_host_reward,
)
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_PIPE,
    HOST_PIPE,
    ROOT,
    VerifyFailure,
    disable_bots,
    launch_pair,
    lua,
    parse_int_text,
    parse_key_values,
    place_player,
    snap_to_nav,
    start_host_testrun_and_wait_for_clients,
    stop_games,
)

RUNTIME_OUTPUT = ROOT / "runtime" / "multiplayer_gold_pickup_authority.json"
POSITION_TOLERANCE = 260.0
MIN_HOST_CLIENT_ANCHOR_DISTANCE = 520.0
GOLD_SPAWN_OFFSET_FROM_CLIENT = 280.0
GOLD_SPAWN_MAX_CLIENT_DISTANCE = 300.0
GOLD_SPAWN_MIN_HOST_DISTANCE = 380.0
STOCK_LOOT_WORLD_UNITS_PER_PICKUP_RANGE = 30.0
PICKUP_RANGE_TEST_MARGIN = 0.95
PICKUP_SUPPRESSION_RADIUS = 335.0
PICKUP_PARKING_MIN_DISTANCE = 520.0
SPAWN_SETTLE_TOLERANCE = 3.0
SPAWN_SETTLE_SECONDS = 0.4
LOCAL_RUNTIME_PARTICIPANT_ID = 1
RUN_SAFE_SPAWN_X = 2350.0
RUN_SAFE_SPAWN_Y = 2850.0


CAPTURE_LUA = r"""
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end

local scene = sd.world and sd.world.get_scene and sd.world.get_scene() or nil
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
emit("scene", scene and (scene.name or scene.kind) or "")
emit("player.gold", player and player.gold or 0)
emit("player.x", player and player.x or 0)
emit("player.y", player and player.y or 0)

local loot = sd.world and sd.world.get_replicated_loot and sd.world.get_replicated_loot() or nil
emit("loot.valid", loot ~= nil)
emit("loot.drop_count", loot and loot.drop_count or 0)
emit("loot.drop_total_count", loot and loot.drop_total_count or 0)
if loot and loot.last_pickup_result then
  local result = loot.last_pickup_result
  emit("pickup.valid", true)
  emit("pickup.authority_participant_id", result.authority_participant_id or 0)
  emit("pickup.participant_id", result.participant_id or 0)
  emit("pickup.request_sequence", result.request_sequence or 0)
  emit("pickup.network_drop_id", result.network_drop_id or 0)
  emit("pickup.result", result.result or "")
  emit("pickup.result_id", result.result_id or 0)
  emit("pickup.kind", result.kind or "")
  emit("pickup.amount", result.amount or 0)
  emit("pickup.resulting_gold", result.resulting_gold or 0)
  emit("pickup.gold_revision", result.gold_revision or 0)
else
  emit("pickup.valid", false)
end

local loot_gold_count = 0
if loot and loot.drops then
  for _, drop in ipairs(loot.drops) do
    local type_id = tonumber(drop.object_type_id or drop.native_type_id) or 0
    if type_id == 0x07DC or drop.kind == "Gold" then
      loot_gold_count = loot_gold_count + 1
      local prefix = "loot_gold." .. tostring(loot_gold_count) .. "."
      emit(prefix .. "network_id", drop.network_drop_id or 0)
      emit(prefix .. "kind", drop.kind or "")
      emit(prefix .. "amount", drop.amount or 0)
      emit(prefix .. "amount_tier", drop.amount_tier or 0)
      emit(prefix .. "active", drop.active and 1 or 0)
      emit(prefix .. "lifetime", drop.lifetime or 0)
      emit(prefix .. "x", string.format("%.3f", tonumber(drop.x) or 0))
      emit(prefix .. "y", string.format("%.3f", tonumber(drop.y) or 0))
    end
  end
end
emit("loot_gold.count", loot_gold_count)

local mp = sd.runtime and sd.runtime.get_multiplayer_state and sd.runtime.get_multiplayer_state() or nil
emit("mp.valid", mp ~= nil)
emit("mp.participant_count", mp and mp.participant_count or 0)
if mp and mp.participants then
  for index, participant in ipairs(mp.participants) do
    local prefix = "participant." .. tostring(index) .. "."
    local owned = participant.owned_progression or {}
    emit(prefix .. "id", participant.participant_id or 0)
    emit(prefix .. "name", participant.name or "")
    emit(prefix .. "kind", participant.kind or "")
    emit(prefix .. "controller", participant.controller_kind or "")
    emit(prefix .. "x", string.format("%.3f", tonumber(participant.x) or 0))
    emit(prefix .. "y", string.format("%.3f", tonumber(participant.y) or 0))
    local derived = owned.derived_stats or {}
    emit(prefix .. "pickup_range", string.format("%.3f", tonumber(derived.pickup_range) or 0))
    emit(prefix .. "gold", owned.gold or 0)
    emit(prefix .. "gold_revision", owned.gold_revision or 0)
  end
end
"""


REQUEST_PICKUP_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local ok, value = sd.world.request_loot_pickup(%d)
emit("ok", ok)
emit(ok and "request_sequence" or "error", value or "")
"""


def values(pipe_name: str, code: str, timeout: float = 8.0) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, code, timeout=timeout))


def capture(pipe_name: str) -> dict[str, str]:
    return values(pipe_name, CAPTURE_LUA)


def capture_pair() -> dict[str, dict[str, str]]:
    return {
        "host": capture(HOST_PIPE),
        "client": capture(CLIENT_PIPE),
    }


def parse_float_text(value: str | None, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def distance(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(ax - bx, ay - by)


def participant_rows(capture_values: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    count = parse_int_text(capture_values.get("mp.participant_count"), 0)
    for index in range(1, count + 1):
        prefix = f"participant.{index}."
        rows.append({
            "index": index,
            "id": parse_int_text(capture_values.get(prefix + "id"), 0),
            "name": capture_values.get(prefix + "name", ""),
            "kind": capture_values.get(prefix + "kind", ""),
            "controller": capture_values.get(prefix + "controller", ""),
            "x": parse_float_text(capture_values.get(prefix + "x")),
            "y": parse_float_text(capture_values.get(prefix + "y")),
            "pickup_range": parse_float_text(
                capture_values.get(prefix + "pickup_range")
            ),
            "gold": parse_int_text(capture_values.get(prefix + "gold"), 0),
            "gold_revision": parse_int_text(capture_values.get(prefix + "gold_revision"), 0),
        })
    return rows


def find_participant(capture_values: dict[str, str], participant_id: int) -> dict[str, Any] | None:
    for row in participant_rows(capture_values):
        if row["id"] == participant_id:
            return row
    return None


def request_pickup(network_drop_id: int) -> dict[str, str]:
    result = values(CLIENT_PIPE, REQUEST_PICKUP_LUA % network_drop_id)
    if result.get("ok") != "true":
        raise VerifyFailure(f"client request_loot_pickup failed: {result}")
    return result


def wait_for_client_pickup_result(
    *,
    network_drop_id: int,
    request_sequence: int,
    expected_result: str,
    timeout: float,
) -> dict[str, str]:
    accepted = try_wait_for_client_pickup_result(
        network_drop_id=network_drop_id,
        request_sequence=request_sequence,
        expected_result=expected_result,
        timeout=timeout,
    )
    if accepted is not None:
        return accepted
    last = capture(CLIENT_PIPE)
    raise VerifyFailure(
        "client did not receive expected loot pickup result: "
        f"drop={network_drop_id} request={request_sequence} expected={expected_result} last={last}"
    )


def try_wait_for_client_pickup_result(
    *,
    network_drop_id: int,
    request_sequence: int | None,
    expected_result: str,
    timeout: float,
) -> dict[str, str] | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        capture_values = capture(CLIENT_PIPE)
        sequence_matches = (
            request_sequence is None or
            parse_int_text(capture_values.get("pickup.request_sequence"), 0) == request_sequence
        )
        if (
            capture_values.get("pickup.valid") == "true"
            and parse_int_text(capture_values.get("pickup.network_drop_id"), 0) == network_drop_id
            and sequence_matches
            and capture_values.get("pickup.result") == expected_result
        ):
            return capture_values
        time.sleep(0.1)
    return None


def wait_for_host_client_gold(
    *,
    expected_gold: int,
    min_revision: int,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_values: dict[str, str] = {}
    last_row: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        last_values = capture(HOST_PIPE)
        last_row = find_participant(last_values, CLIENT_ID)
        if (
            last_row is not None
            and last_row["gold"] == expected_gold
            and last_row["gold_revision"] > min_revision
        ):
            return {
                "capture": last_values,
                "participant": last_row,
            }
        time.sleep(0.1)
    raise VerifyFailure(
        "host did not credit the client participant-owned gold ledger: "
        f"expected_gold={expected_gold} min_revision={min_revision} "
        f"last_row={last_row} last_values={last_values}"
    )


def wait_for_client_local_gold(
    *,
    expected_gold: int,
    timeout: float,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = capture(CLIENT_PIPE)
        if parse_int_text(last.get("player.gold"), 0) == expected_gold:
            return last
        time.sleep(0.1)
    raise VerifyFailure(f"client local gold did not update to {expected_gold}: {last}")


def wait_for_host_reward_unregistered(address: int, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = reward_capture(HOST_PIPE)
        if all(row["address"] != address for row in reward_rows(last)):
            return {
                "capture": last,
                "actor_address": address,
                "unregistered": True,
            }
        time.sleep(0.1)
    raise VerifyFailure(
        "host gold reward actor remained registered after accepted pickup: "
        f"address=0x{address:X} last={last}"
    )


def wait_for_client_replicated_drop_absent(
    network_drop_id: int,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = capture(CLIENT_PIPE)
        if all(row["network_id"] != network_drop_id for row in loot_gold_rows(last)):
            return {
                "capture": last,
            }
        time.sleep(0.1)
    raise VerifyFailure(f"client replicated drop did not disappear: id={network_drop_id} last={last}")


def setup_live_run_pair_without_waves(max_attempts: int) -> dict[str, Any]:
    last_error = ""
    for attempt in range(1, max_attempts + 1):
        try:
            stop_games()
            launch = launch_pair()
            disable_bots()
            run_entry = start_host_testrun_and_wait_for_clients()
            time.sleep(1.0)
            return {
                "attempt": attempt,
                "launch": launch,
                "run_entry": run_entry,
            }
        except Exception as exc:
            last_error = str(exc)
            stop_games()
            time.sleep(1.0)
    raise VerifyFailure(f"failed to prepare live run pair after {max_attempts} attempts: {last_error}")


def move_client_into_pickup_range(
    *,
    network_drop_id: int,
    drop_x: float,
    drop_y: float,
    timeout: float,
) -> dict[str, Any]:
    place = place_player(CLIENT_PIPE, drop_x, drop_y, 90.0)
    deadline = time.monotonic() + timeout
    next_reposition_at = time.monotonic() + 0.5
    last_client: dict[str, str] = {}
    last_host: dict[str, str] = {}
    local_row: dict[str, Any] | None = None
    host_row: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        last_client = capture(CLIENT_PIPE)
        last_host = capture(HOST_PIPE)
        player_x = parse_float_text(last_client.get("player.x"))
        player_y = parse_float_text(last_client.get("player.y"))
        local_row = find_participant(last_client, LOCAL_RUNTIME_PARTICIPANT_ID)
        host_row = find_participant(last_host, CLIENT_ID)
        local_range_limit = (
            local_row["pickup_range"]
            * STOCK_LOOT_WORLD_UNITS_PER_PICKUP_RANGE
            * PICKUP_RANGE_TEST_MARGIN
            if local_row is not None
            and math.isfinite(local_row["pickup_range"])
            and local_row["pickup_range"] > 0.0
            else 0.0
        )
        host_range_limit = (
            host_row["pickup_range"]
            * STOCK_LOOT_WORLD_UNITS_PER_PICKUP_RANGE
            * PICKUP_RANGE_TEST_MARGIN
            if host_row is not None
            and math.isfinite(host_row["pickup_range"])
            and host_row["pickup_range"] > 0.0
            else 0.0
        )
        player_distance = distance(player_x, player_y, drop_x, drop_y)
        runtime_distance = (
            distance(local_row["x"], local_row["y"], drop_x, drop_y)
            if local_row is not None else math.inf
        )
        authority_distance = (
            distance(host_row["x"], host_row["y"], drop_x, drop_y)
            if host_row is not None else math.inf
        )
        player_in_range = local_range_limit > 0.0 and player_distance <= local_range_limit
        runtime_in_range = (
            local_range_limit > 0.0 and runtime_distance <= local_range_limit
        )
        authority_in_range = (
            host_range_limit > 0.0 and authority_distance <= host_range_limit
        )
        accepted_during_positioning = (
            last_client.get("pickup.valid") == "true"
            and parse_int_text(
                last_client.get("pickup.network_drop_id"), 0
            ) == network_drop_id
            and last_client.get("pickup.result") == "Accepted"
        )
        if (
            accepted_during_positioning
            or (player_in_range and runtime_in_range and authority_in_range)
        ):
            return {
                "place": place,
                "client_capture": last_client,
                "host_capture": last_host,
                "local_participant": local_row,
                "host_participant": host_row,
                "drop_x": drop_x,
                "drop_y": drop_y,
                "client_range_limit": local_range_limit,
                "host_range_limit": host_range_limit,
                "player_distance": player_distance,
                "runtime_distance": runtime_distance,
                "authority_distance": authority_distance,
                "accepted_during_positioning": accepted_during_positioning,
            }
        if (
            not (player_in_range and runtime_in_range and authority_in_range)
            and time.monotonic() >= next_reposition_at
        ):
            place = place_player(CLIENT_PIPE, drop_x, drop_y, 90.0)
            next_reposition_at = time.monotonic() + 0.5
        time.sleep(0.1)
    raise VerifyFailure(
        "client did not settle in gold pickup range before request: "
        f"drop=({drop_x:.3f},{drop_y:.3f}) local_row={local_row} host_row={host_row} "
        f"client={last_client} host={last_host}"
    )


def move_client_out_of_pickup_range(
    *,
    drop_x: float,
    drop_y: float,
    timeout: float,
) -> dict[str, Any]:
    current = capture_pair()
    current_host_row = find_participant(current["host"], CLIENT_ID)
    current_client_distance = distance(
        parse_float_text(current["client"].get("player.x")),
        parse_float_text(current["client"].get("player.y")),
        drop_x,
        drop_y,
    )
    current_host_distance = (
        distance(current_host_row["x"], current_host_row["y"], drop_x, drop_y)
        if current_host_row is not None else 0.0
    )
    if (
        current_client_distance > PICKUP_SUPPRESSION_RADIUS
        and current_host_row is not None
        and current_host_distance > PICKUP_SUPPRESSION_RADIUS
    ):
        return {
            "place": None,
            "client_capture": current["client"],
            "host_capture": current["host"],
            "host_participant": current_host_row,
            "drop_x": drop_x,
            "drop_y": drop_y,
            "parking_x": parse_float_text(current["client"].get("player.x")),
            "parking_y": parse_float_text(current["client"].get("player.y")),
            "client_distance": current_client_distance,
            "host_distance": current_host_distance,
        }

    candidate_targets = [
        (drop_x + 900.0, drop_y + 900.0),
        (drop_x - 900.0, drop_y + 900.0),
        (drop_x + 900.0, drop_y - 900.0),
        (drop_x - 900.0, drop_y - 900.0),
        (drop_x + 1200.0, drop_y),
        (drop_x - 1200.0, drop_y),
    ]
    parking_x = candidate_targets[0][0]
    parking_y = candidate_targets[0][1]
    best_distance = -1.0
    for candidate_x, candidate_y in candidate_targets:
        try:
            snap_x, snap_y = snap_to_nav(CLIENT_PIPE, candidate_x, candidate_y)
        except Exception:
            snap_x, snap_y = candidate_x, candidate_y
        candidate_distance = distance(snap_x, snap_y, drop_x, drop_y)
        if candidate_distance > best_distance:
            best_distance = candidate_distance
            parking_x = snap_x
            parking_y = snap_y
    if best_distance < PICKUP_PARKING_MIN_DISTANCE:
        parking_x = drop_x + PICKUP_PARKING_MIN_DISTANCE + 128.0
        parking_y = drop_y + PICKUP_PARKING_MIN_DISTANCE + 128.0

    place = place_player(CLIENT_PIPE, parking_x, parking_y, 90.0)
    deadline = time.monotonic() + timeout
    last_client: dict[str, str] = {}
    last_host: dict[str, str] = {}
    host_row: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        last_client = capture(CLIENT_PIPE)
        last_host = capture(HOST_PIPE)
        client_distance = distance(
            parse_float_text(last_client.get("player.x")),
            parse_float_text(last_client.get("player.y")),
            drop_x,
            drop_y,
        )
        host_row = find_participant(last_host, CLIENT_ID)
        host_distance = (
            distance(host_row["x"], host_row["y"], drop_x, drop_y)
            if host_row is not None else 0.0
        )
        if (
            client_distance > PICKUP_SUPPRESSION_RADIUS
            and host_row is not None
            and host_distance > PICKUP_SUPPRESSION_RADIUS
        ):
            return {
                "place": place,
                "client_capture": last_client,
                "host_capture": last_host,
                "host_participant": host_row,
                "drop_x": drop_x,
                "drop_y": drop_y,
                "parking_x": parking_x,
                "parking_y": parking_y,
                "client_distance": client_distance,
                "host_distance": host_distance,
            }
        time.sleep(0.1)
    raise VerifyFailure(
        "client did not settle out of gold pickup range before spawn: "
        f"drop=({drop_x:.3f},{drop_y:.3f}) host_row={host_row} "
        f"client={last_client} host={last_host}"
    )


def select_remote_spawn_anchor(timeout: float) -> dict[str, Any]:
    before = capture_pair()
    client_x = parse_float_text(before["client"].get("player.x"))
    client_y = parse_float_text(before["client"].get("player.y"))
    host_x = parse_float_text(before["host"].get("player.x"))
    host_y = parse_float_text(before["host"].get("player.y"))
    if (
        not math.isfinite(client_x)
        or not math.isfinite(client_y)
        or not math.isfinite(host_x)
        or not math.isfinite(host_y)
    ):
        raise VerifyFailure(f"player positions unavailable: before={before}")

    candidate_offsets = (
        (900.0, 0.0),
        (-900.0, 0.0),
        (0.0, 900.0),
        (0.0, -900.0),
        (700.0, 700.0),
        (-700.0, 700.0),
        (700.0, -700.0),
        (-700.0, -700.0),
        (1200.0, 0.0),
        (-1200.0, 0.0),
    )
    attempts: list[dict[str, Any]] = []
    deadline = time.monotonic() + timeout
    for offset_x, offset_y in candidate_offsets:
        if time.monotonic() >= deadline:
            break
        requested_x = host_x + offset_x
        requested_y = host_y + offset_y
        try:
            target_x, target_y = snap_to_nav(CLIENT_PIPE, requested_x, requested_y)
        except Exception:
            target_x, target_y = requested_x, requested_y
        place = place_player(CLIENT_PIPE, target_x, target_y, 90.0)

        settle_deadline = min(deadline, time.monotonic() + 4.0)
        last_host: dict[str, str] = {}
        last_row: dict[str, Any] | None = None
        while time.monotonic() < settle_deadline:
            last_host = capture(HOST_PIPE)
            last_row = find_participant(last_host, CLIENT_ID)
            if last_row is not None:
                host_distance = math.hypot(last_row["x"] - host_x, last_row["y"] - host_y)
                target_distance = math.hypot(last_row["x"] - target_x, last_row["y"] - target_y)
                if (
                    host_distance >= MIN_HOST_CLIENT_ANCHOR_DISTANCE
                    and target_distance <= POSITION_TOLERANCE
                ):
                    return {
                        "before": before,
                        "host_x": host_x,
                        "host_y": host_y,
                        "requested_x": requested_x,
                        "requested_y": requested_y,
                        "snapped_x": target_x,
                        "snapped_y": target_y,
                        "target_x": last_row["x"],
                        "target_y": last_row["y"],
                        "place": place,
                        "host_participant": last_row,
                        "host_distance": host_distance,
                        "target_distance": target_distance,
                    }
            time.sleep(0.1)
        attempts.append({
            "requested_x": requested_x,
            "requested_y": requested_y,
            "snapped_x": target_x,
            "snapped_y": target_y,
            "last_row": last_row,
            "last_host": last_host,
        })

    raise VerifyFailure(f"host did not observe a separated moved client before gold test: attempts={attempts}")


def settle_reachable_spawn_candidate(
    *,
    requested_x: float,
    requested_y: float,
    nav_x: float,
    nav_y: float,
    host_x: float,
    host_y: float,
    timeout: float,
) -> dict[str, Any] | None:
    place = place_player(CLIENT_PIPE, nav_x, nav_y, 90.0)
    deadline = time.monotonic() + timeout
    stable_since: float | None = None
    previous_position: tuple[float, float] | None = None
    last_pair: dict[str, dict[str, str]] = {}
    last_host_row: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        last_pair = capture_pair()
        local_x = parse_float_text(last_pair["client"].get("player.x"))
        local_y = parse_float_text(last_pair["client"].get("player.y"))
        last_host_row = find_participant(last_pair["host"], CLIENT_ID)
        finite = math.isfinite(local_x) and math.isfinite(local_y)
        observer_agrees = (
            finite
            and last_host_row is not None
            and distance(
                local_x,
                local_y,
                last_host_row["x"],
                last_host_row["y"],
            ) <= SPAWN_SETTLE_TOLERANCE
        )
        separated_from_host = (
            finite
            and distance(local_x, local_y, host_x, host_y)
            > PICKUP_SUPPRESSION_RADIUS + 20.0
        )
        stationary = (
            finite
            and previous_position is not None
            and distance(local_x, local_y, *previous_position)
            <= SPAWN_SETTLE_TOLERANCE
        )
        if observer_agrees and separated_from_host and stationary:
            now = time.monotonic()
            if stable_since is None:
                stable_since = now
            elif now - stable_since >= SPAWN_SETTLE_SECONDS:
                return {
                    "requested_x": requested_x,
                    "requested_y": requested_y,
                    "nav_x": nav_x,
                    "nav_y": nav_y,
                    "snapped_x": local_x,
                    "snapped_y": local_y,
                    "place": place,
                    "client_capture": last_pair["client"],
                    "host_capture": last_pair["host"],
                    "host_participant": last_host_row,
                }
        else:
            stable_since = None
        if finite:
            previous_position = (local_x, local_y)
        time.sleep(0.1)
    return None


def select_spawn_point(timeout: float) -> dict[str, Any]:
    before = capture_pair()
    client_x = parse_float_text(before["client"].get("player.x"))
    client_y = parse_float_text(before["client"].get("player.y"))
    host_x = parse_float_text(before["host"].get("player.x"))
    host_y = parse_float_text(before["host"].get("player.y"))
    away_x = client_x - host_x
    away_y = client_y - host_y
    away_length = math.hypot(away_x, away_y)
    if away_length < 1.0:
        away_x, away_y, away_length = 1.0, 0.0, 1.0
    away_x /= away_length
    away_y /= away_length
    directions = (
        (away_x, away_y),
        (-away_y, away_x),
        (away_y, -away_x),
        (-away_x, -away_y),
    )
    attempts: list[dict[str, Any]] = []
    deadline = time.monotonic() + timeout
    for radius in (440.0, 520.0, 600.0):
        for direction_x, direction_y in directions:
            if time.monotonic() >= deadline:
                break
            requested_x = client_x + direction_x * radius
            requested_y = client_y + direction_y * radius
            nav_x, nav_y = snap_to_nav(CLIENT_PIPE, requested_x, requested_y)
            candidate = settle_reachable_spawn_candidate(
                requested_x=requested_x,
                requested_y=requested_y,
                nav_x=nav_x,
                nav_y=nav_y,
                host_x=host_x,
                host_y=host_y,
                timeout=min(4.0, max(0.0, deadline - time.monotonic())),
            )
            if candidate is not None:
                candidate["client_distance"] = distance(
                    client_x,
                    client_y,
                    candidate["snapped_x"],
                    candidate["snapped_y"],
                )
                candidate["host_distance"] = distance(
                    host_x,
                    host_y,
                    candidate["snapped_x"],
                    candidate["snapped_y"],
                )
                return {
                    "before": before,
                    **candidate,
                }
            attempts.append(
                {
                    "requested_x": requested_x,
                    "requested_y": requested_y,
                    "nav_x": nav_x,
                    "nav_y": nav_y,
                }
            )
    raise VerifyFailure(
        f"no stable reachable gold spawn point separated from the host: {attempts}"
    )


def verify_gold_pickup_authority(args: argparse.Namespace) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": False}
    if not args.no_launch:
        result["setup"] = setup_live_run_pair_without_waves(max_attempts=args.attempts)

    before_pair = capture_pair()
    result["before"] = before_pair
    host_client_before = find_participant(before_pair["host"], CLIENT_ID)
    if host_client_before is None:
        raise VerifyFailure(f"host does not have client participant before pickup: {before_pair['host']}")

    client_gold_before = parse_int_text(before_pair["client"].get("player.gold"), 0)
    host_gold_before = parse_int_text(before_pair["host"].get("player.gold"), 0)
    before_addresses = {row["address"] for row in reward_rows(reward_capture(HOST_PIPE))}
    spawn_point = select_spawn_point(timeout=args.timeout)
    result["spawn_point"] = spawn_point

    spawn_x = float(spawn_point["snapped_x"])
    spawn_y = float(spawn_point["snapped_y"])
    result["client_pre_spawn_parking"] = move_client_out_of_pickup_range(
        drop_x=spawn_x,
        drop_y=spawn_y,
        timeout=args.timeout,
    )
    result["spawn"] = spawn_gold(
        HOST_PIPE,
        amount=PROBE_GOLD_AMOUNT,
        x=spawn_x,
        y=spawn_y,
    )
    spawned = wait_for_spawned_host_reward(
        before_addresses=before_addresses,
        amount=PROBE_GOLD_AMOUNT,
        x=spawn_x,
        y=spawn_y,
        timeout=args.timeout,
    )
    replicated = wait_for_client_replicated_loot(
        amount=PROBE_GOLD_AMOUNT,
        x=spawn_x,
        y=spawn_y,
        timeout=args.timeout,
    )
    network_drop_id = int(replicated["drop"]["network_id"])
    expected_client_gold = client_gold_before + PROBE_GOLD_AMOUNT
    result["client_pickup_position"] = move_client_into_pickup_range(
        network_drop_id=network_drop_id,
        drop_x=float(replicated["drop"]["x"]),
        drop_y=float(replicated["drop"]["y"]),
        timeout=args.timeout,
    )
    accepted = try_wait_for_client_pickup_result(
        network_drop_id=network_drop_id,
        request_sequence=None,
        expected_result="Accepted",
        timeout=min(5.0, args.timeout),
    )
    if accepted is None:
        raise VerifyFailure(
            "client proximity hook did not accept the in-range gold pickup"
        )
    request_sequence = parse_int_text(accepted.get("pickup.request_sequence"), 0)
    result["request"] = {
        "ok": "true",
        "path": "client_proximity_hook",
        "request_sequence": str(request_sequence),
    }
    result["accepted_result"] = accepted
    result["client_local_gold_after_accept"] = wait_for_client_local_gold(
        expected_gold=expected_client_gold,
        timeout=args.timeout,
    )
    result["host_client_gold_after_accept"] = wait_for_host_client_gold(
        expected_gold=expected_client_gold,
        min_revision=host_client_before["gold_revision"],
        timeout=args.timeout,
    )
    result["host_reward_after_accept"] = wait_for_host_reward_unregistered(
        spawned["reward"]["address"],
        timeout=args.timeout,
    )
    result["client_drop_after_accept"] = wait_for_client_replicated_drop_absent(
        network_drop_id,
        timeout=args.timeout,
    )

    duplicate_request = request_pickup(network_drop_id)
    duplicate_sequence = parse_int_text(duplicate_request.get("request_sequence"), 0)
    result["duplicate_request"] = duplicate_request
    result["duplicate_result"] = wait_for_client_pickup_result(
        network_drop_id=network_drop_id,
        request_sequence=duplicate_sequence,
        expected_result="AlreadyGone",
        timeout=args.timeout,
    )
    result["after_duplicate_pair"] = capture_pair()

    client_gold_after_duplicate = parse_int_text(
        result["after_duplicate_pair"]["client"].get("player.gold"),
        0,
    )
    host_client_after_duplicate = find_participant(
        result["after_duplicate_pair"]["host"],
        CLIENT_ID,
    )
    host_gold_after_duplicate = parse_int_text(
        result["after_duplicate_pair"]["host"].get("player.gold"),
        0,
    )

    result["conclusion"] = {
        "host_gold_unchanged": host_gold_after_duplicate == host_gold_before,
        "client_gold_incremented_once": client_gold_after_duplicate == expected_client_gold,
        "host_client_ledger_incremented_once": (
            host_client_after_duplicate is not None
            and host_client_after_duplicate["gold"] == expected_client_gold
        ),
        "accepted_amount_matches": parse_int_text(result["accepted_result"].get("pickup.amount"), 0)
        == PROBE_GOLD_AMOUNT,
        "accepted_tier_matched_before_pickup": replicated["drop"]["amount_tier"] == PROBE_EXPECTED_TIER,
        "host_drop_unregistered": result["host_reward_after_accept"]["unregistered"] is True,
        "client_metadata_deactivated": True,
        "duplicate_rejected_without_second_credit": (
            result["duplicate_result"].get("pickup.result") == "AlreadyGone"
            and client_gold_after_duplicate == expected_client_gold
            and host_client_after_duplicate is not None
            and host_client_after_duplicate["gold"] == expected_client_gold
        ),
    }
    result["ok"] = all(result["conclusion"].values())
    if not result["ok"]:
        raise VerifyFailure(f"gold pickup authority conclusion failed: {result['conclusion']}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-launch", action="store_true")
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=12.0)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    try:
        result = verify_gold_pickup_authority(args)
        RUNTIME_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({
            "ok": result["ok"],
            "conclusion": result.get("conclusion", {}),
            "output": str(RUNTIME_OUTPUT),
        }, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        result["error"] = str(exc)
        RUNTIME_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({
            "ok": False,
            "error": str(exc),
            "output": str(RUNTIME_OUTPUT),
        }, indent=2, sort_keys=True))
        return 1
    finally:
        if not args.no_launch:
            stop_games()


if __name__ == "__main__":
    raise SystemExit(main())
