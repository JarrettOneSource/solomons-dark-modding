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
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = capture(CLIENT_PIPE)
        if (
            last.get("pickup.valid") == "true"
            and parse_int_text(last.get("pickup.network_drop_id"), 0) == network_drop_id
            and parse_int_text(last.get("pickup.request_sequence"), 0) == request_sequence
            and last.get("pickup.result") == expected_result
        ):
            return last
        time.sleep(0.1)
    raise VerifyFailure(
        "client did not receive expected loot pickup result: "
        f"drop={network_drop_id} request={request_sequence} expected={expected_result} last={last}"
    )


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


def wait_for_host_reward_zeroed(address: int, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = reward_capture(HOST_PIPE)
        for row in reward_rows(last):
            if row["address"] == address:
                if row["amount"] == 0:
                    return {
                        "capture": last,
                        "reward": row,
                    }
                break
        time.sleep(0.1)
    raise VerifyFailure(f"host gold reward actor amount did not become zero: address=0x{address:X} last={last}")


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


def select_remote_spawn_anchor(timeout: float) -> dict[str, Any]:
    before = capture_pair()
    client_x = parse_float_text(before["client"].get("player.x"))
    client_y = parse_float_text(before["client"].get("player.y"))
    if not math.isfinite(client_x) or not math.isfinite(client_y):
        raise VerifyFailure(f"client position unavailable: {before['client']}")

    target_x, target_y = snap_to_nav(HOST_PIPE, client_x + 900.0, client_y)
    place = place_player(CLIENT_PIPE, target_x, target_y, 90.0)

    deadline = time.monotonic() + timeout
    last_host: dict[str, str] = {}
    last_row: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        last_host = capture(HOST_PIPE)
        last_row = find_participant(last_host, CLIENT_ID)
        if (
            last_row is not None
            and math.hypot(last_row["x"] - target_x, last_row["y"] - target_y) <= POSITION_TOLERANCE
        ):
            return {
                "before": before,
                "target_x": target_x,
                "target_y": target_y,
                "place": place,
                "host_participant": last_row,
            }
        time.sleep(0.1)
    raise VerifyFailure(f"host did not observe moved client before gold test: row={last_row} capture={last_host}")


def select_spawn_point(timeout: float) -> dict[str, Any]:
    anchor = select_remote_spawn_anchor(timeout)
    requested_x = float(anchor["target_x"]) + 240.0
    requested_y = float(anchor["target_y"])
    snapped_x, snapped_y = snap_to_nav(HOST_PIPE, requested_x, requested_y)
    return {
        "anchor": anchor,
        "client_anchor_x": float(anchor["target_x"]),
        "client_anchor_y": float(anchor["target_y"]),
        "requested_x": requested_x,
        "requested_y": requested_y,
        "snapped_x": snapped_x,
        "snapped_y": snapped_y,
    }


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
    request = request_pickup(network_drop_id)
    request_sequence = parse_int_text(request.get("request_sequence"), 0)
    expected_client_gold = client_gold_before + PROBE_GOLD_AMOUNT
    result["request"] = request
    result["accepted_result"] = wait_for_client_pickup_result(
        network_drop_id=network_drop_id,
        request_sequence=request_sequence,
        expected_result="Accepted",
        timeout=args.timeout,
    )
    result["client_local_gold_after_accept"] = wait_for_client_local_gold(
        expected_gold=expected_client_gold,
        timeout=args.timeout,
    )
    result["host_client_gold_after_accept"] = wait_for_host_client_gold(
        expected_gold=expected_client_gold,
        min_revision=host_client_before["gold_revision"],
        timeout=args.timeout,
    )
    result["host_reward_after_accept"] = wait_for_host_reward_zeroed(
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
        "host_drop_deactivated": result["host_reward_after_accept"]["reward"]["amount"] == 0,
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
