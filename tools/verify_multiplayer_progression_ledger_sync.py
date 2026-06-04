#!/usr/bin/env python3
"""Verify local UDP participant progression ledger replication."""

from __future__ import annotations

import argparse
import json
import time
from typing import Any

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
    parse_int_text,
    parse_key_values,
    stop_games,
    wait_for_both_hub_settled,
)


RUNTIME_OUTPUT = ROOT / "runtime" / "multiplayer_progression_ledger_sync.json"
GOLD_GLOBAL_RVA = 0x0081A388


CAPTURE_LUA = rf"""
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end

local scene = sd.world and sd.world.get_scene and sd.world.get_scene() or nil
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
local gold_address = sd.debug and sd.debug.resolve_game_address and sd.debug.resolve_game_address({GOLD_GLOBAL_RVA}) or 0
emit("scene", scene and (scene.name or scene.kind) or "")
emit("player.gold", player and player.gold or 0)
emit("gold.address", gold_address or 0)
emit("gold.raw", (gold_address ~= nil and gold_address ~= 0 and sd.debug.read_i32(gold_address)) or 0)

local mp = sd.runtime and sd.runtime.get_multiplayer_state and sd.runtime.get_multiplayer_state() or nil
emit("mp.valid", mp ~= nil)
emit("mp.participant_count", mp and mp.participant_count or 0)
if mp and mp.participants then
  for index, participant in ipairs(mp.participants) do
    local prefix = "participant." .. tostring(index) .. "."
    local owned = participant.owned_progression or {{}}
    emit(prefix .. "id", participant.participant_id or 0)
    emit(prefix .. "name", participant.name or "")
    emit(prefix .. "kind", participant.kind or "")
    emit(prefix .. "controller", participant.controller_kind or "")
    emit(prefix .. "connected", participant.transport_connected or false)
    emit(prefix .. "gold", owned.gold or 0)
    emit(prefix .. "gold_revision", owned.gold_revision or 0)
    emit(prefix .. "inventory_revision", owned.inventory_revision or 0)
    emit(prefix .. "spellbook_revision", owned.spellbook_revision or 0)
    emit(prefix .. "statbook_revision", owned.statbook_revision or 0)
    emit(prefix .. "loadout_revision", owned.loadout_revision or 0)
  end
end
"""


def capture(pipe_name: str) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, CAPTURE_LUA, timeout=5.0))


def capture_pair() -> dict[str, dict[str, str]]:
    return {
        "host": capture(HOST_PIPE),
        "client": capture(CLIENT_PIPE),
    }


def participant_rows(values: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    count = parse_int_text(values.get("mp.participant_count"), 0)
    for index in range(1, count + 1):
        prefix = f"participant.{index}."
        rows.append({
            "index": index,
            "id": parse_int_text(values.get(prefix + "id"), 0),
            "name": values.get(prefix + "name", ""),
            "kind": values.get(prefix + "kind", ""),
            "controller": values.get(prefix + "controller", ""),
            "connected": values.get(prefix + "connected", ""),
            "gold": parse_int_text(values.get(prefix + "gold"), 0),
            "gold_revision": parse_int_text(values.get(prefix + "gold_revision"), 0),
            "inventory_revision": parse_int_text(values.get(prefix + "inventory_revision"), 0),
            "spellbook_revision": parse_int_text(values.get(prefix + "spellbook_revision"), 0),
            "statbook_revision": parse_int_text(values.get(prefix + "statbook_revision"), 0),
            "loadout_revision": parse_int_text(values.get(prefix + "loadout_revision"), 0),
        })
    return rows


def find_participant(values: dict[str, str], participant_id: int) -> dict[str, Any] | None:
    for row in participant_rows(values):
        if row["id"] == participant_id:
            return row
    return None


def set_gold(pipe_name: str, value: int) -> dict[str, str]:
    code = rf"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local address = sd.debug.resolve_game_address({GOLD_GLOBAL_RVA}) or 0
emit("address", address)
emit("before", address ~= 0 and sd.debug.read_i32(address) or 0)
emit("write", address ~= 0 and sd.debug.write_i32(address, {value}) or false)
emit("after", address ~= 0 and sd.debug.read_i32(address) or 0)
"""
    result = parse_key_values(lua(pipe_name, code, timeout=5.0))
    if result.get("write") != "true" or parse_int_text(result.get("after"), -1) != value:
        raise VerifyFailure(f"failed to write gold={value} on {pipe_name}: {result}")
    return result


def wait_for_participant_gold(
    observer_pipe: str,
    participant_id: int,
    expected_gold: int,
    *,
    min_revision: int,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_values: dict[str, str] = {}
    last_row: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        last_values = capture(observer_pipe)
        last_row = find_participant(last_values, participant_id)
        if (
            last_row is not None
            and last_row["gold"] == expected_gold
            and last_row["gold_revision"] > min_revision
        ):
            return {
                "observer_pipe": observer_pipe,
                "participant": last_row,
            }
        time.sleep(0.1)
    raise VerifyFailure(
        "participant-owned gold did not replicate: "
        f"observer={observer_pipe} participant=0x{participant_id:X} "
        f"expected_gold={expected_gold} min_revision={min_revision} "
        f"last_row={last_row} last_values={last_values}"
    )


def wait_for_pair_ready(timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last = capture_pair()
    while time.monotonic() < deadline:
        last = capture_pair()
        host_client = find_participant(last["host"], CLIENT_ID)
        client_host = find_participant(last["client"], HOST_ID)
        if (
            last["host"].get("scene") == "hub"
            and last["client"].get("scene") == "hub"
            and host_client is not None
            and client_host is not None
        ):
            return {
                "host_observes_client": host_client,
                "client_observes_host": client_host,
            }
        time.sleep(0.2)
    raise VerifyFailure(f"multiplayer pair did not expose both participant ledgers: {last}")


def verify_bidirectional_gold_ledger(timeout: float) -> dict[str, Any]:
    ready = wait_for_pair_ready(timeout)
    before = capture_pair()
    host_start = parse_int_text(before["host"].get("player.gold"), 0)
    client_start = parse_int_text(before["client"].get("player.gold"), 0)
    client_view_host = find_participant(before["client"], HOST_ID)
    host_view_client = find_participant(before["host"], CLIENT_ID)
    if client_view_host is None or host_view_client is None:
        raise VerifyFailure(f"missing remote participants in baseline capture: {before}")

    host_target_gold = host_start + 37
    client_target_gold = client_start + 53
    host_set = set_gold(HOST_PIPE, host_target_gold)
    client_observed_host = wait_for_participant_gold(
        CLIENT_PIPE,
        HOST_ID,
        host_target_gold,
        min_revision=client_view_host["gold_revision"],
        timeout=timeout,
    )
    client_set = set_gold(CLIENT_PIPE, client_target_gold)
    host_observed_client = wait_for_participant_gold(
        HOST_PIPE,
        CLIENT_ID,
        client_target_gold,
        min_revision=host_view_client["gold_revision"],
        timeout=timeout,
    )

    restore = {
        "host": set_gold(HOST_PIPE, host_start),
        "client": set_gold(CLIENT_PIPE, client_start),
    }
    after_restore = capture_pair()
    return {
        "ready": ready,
        "baseline": {
            "host_gold": host_start,
            "client_gold": client_start,
            "client_view_host": client_view_host,
            "host_view_client": host_view_client,
        },
        "host_gold_write": host_set,
        "client_observed_host": client_observed_host,
        "client_gold_write": client_set,
        "host_observed_client": host_observed_client,
        "restore": restore,
        "after_restore": after_restore,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": False}
    if not args.no_launch:
        stop_games()
        result["launch"] = launch_pair()
        disable_bots()
        wait_for_both_hub_settled()
    result["ledger"] = verify_bidirectional_gold_ledger(timeout=args.timeout)
    result["ok"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-launch", action="store_true")
    parser.add_argument("--timeout", type=float, default=12.0)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    try:
        result = run(args)
        RUNTIME_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({
            "ok": result["ok"],
            "ledger": result.get("ledger"),
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
