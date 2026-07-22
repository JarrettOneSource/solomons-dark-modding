#!/usr/bin/env python3
"""Verify one Hagatha selector in both directions on an active Steam pair."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Callable

from steam_friend_active_pair import (
    CLIENT_ENDPOINT,
    HOST_ENDPOINT,
    PAIR_BACKEND,
    ROOT,
    SteamFriendActivePair,
)
from verify_local_multiplayer_sync import (
    VerifyFailure,
    parse_int_text,
    parse_key_values,
)


EXPECTED_PERK_COUNT = 28
APPLY_HAGATHA_PERK = 0x0066EF70
TONIC_SELECTOR = 27
DEFAULT_OUTPUT = ROOT / "runtime/steam_hagatha_perk_sync.json"


CAPTURE_LUA = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end

local list_offset = sd.debug.layout_offset("progression_hagatha_perk_list")
local count_offset = sd.debug.layout_offset("progression_hagatha_perk_count")
local capacity_offset = sd.debug.layout_offset("progression_hagatha_perk_capacity")
local charge_offset = sd.debug.layout_offset("progression_cheat_death_charges")
local serendipity_offset = sd.debug.layout_offset("progression_serendipity_active")
local reverie_offset = sd.debug.layout_offset("progression_reverie_active")

local function emit_native(prefix, progression)
  progression = tonumber(progression) or 0
  emit(prefix .. "progression", progression)
  if progression == 0 then
    emit(prefix .. "count", -1)
    return
  end
  local list = tonumber(sd.debug.read_ptr(progression + list_offset)) or 0
  local count = tonumber(sd.debug.read_i32(progression + count_offset)) or -1
  emit(prefix .. "list", list)
  emit(prefix .. "count", count)
  emit(prefix .. "capacity", sd.debug.read_i32(progression + capacity_offset) or -1)
  emit(prefix .. "cheat_death_charges", sd.debug.read_i32(progression + charge_offset) or -1)
  emit(prefix .. "serendipity_active", sd.debug.read_u8(progression + serendipity_offset) or -1)
  emit(prefix .. "reverie_active", sd.debug.read_u8(progression + reverie_offset) or -1)
  if list ~= 0 and count >= 0 and count <= 9 then
    for index = 0, count - 1 do
      emit(prefix .. "selector." .. tostring(index + 1),
        sd.debug.read_i32(list + index * 4) or -1)
    end
  end
end

local scene = sd.world and sd.world.get_scene and sd.world.get_scene() or nil
emit("scene", scene and (scene.name or scene.kind) or "")
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
emit_native("owner.native.", player and player.progression_address or 0)

local multiplayer = sd.runtime and sd.runtime.get_multiplayer_state and
  sd.runtime.get_multiplayer_state() or nil
local participants = multiplayer and multiplayer.participants or {}
emit("participant.count", #participants)
for index, participant in ipairs(participants) do
  local prefix = "participant." .. tostring(index) .. "."
  local owned = participant.owned_progression or {}
  local perks = owned.hagatha_perks or {}
  local selectors = perks.selectors or {}
  emit(prefix .. "id", participant.participant_id or 0)
  emit(prefix .. "revision", owned.hagatha_perk_revision or 0)
  emit(prefix .. "valid", perks.valid or false)
  emit(prefix .. "count", perks.perk_count or -1)
  emit(prefix .. "capacity", perks.perk_capacity or -1)
  emit(prefix .. "cheat_death_charges", perks.cheat_death_charges or -1)
  emit(prefix .. "serendipity_active", perks.serendipity_active or false)
  emit(prefix .. "reverie_active", perks.reverie_active or false)
  for selector_index, selector in ipairs(selectors) do
    emit(prefix .. "selector." .. tostring(selector_index), selector)
  end
  local participant_native = sd.bots and sd.bots.get_participant_state and
    sd.bots.get_participant_state(participant.participant_id) or nil
  emit_native(prefix .. "native.",
    participant_native and participant_native.progression_runtime_state_address or 0)
end
"""


def bool_text(value: str | None) -> bool:
    return value in ("1", "true")


def selector_list(values: dict[str, str], prefix: str, count: int) -> list[int]:
    return [
        parse_int_text(values.get(f"{prefix}selector.{index}"), -1)
        for index in range(1, count + 1)
    ]


def native_state(values: dict[str, str], prefix: str) -> dict[str, Any]:
    count = parse_int_text(values.get(prefix + "count"), -1)
    return {
        "progression": parse_int_text(values.get(prefix + "progression"), 0),
        "native_selector_list": selector_list(values, prefix, max(count, 0)),
        "count": count,
        "capacity": parse_int_text(values.get(prefix + "capacity"), -1),
        "cheat_death_charges": parse_int_text(
            values.get(prefix + "cheat_death_charges"), -1
        ),
        "serendipity_active": bool_text(
            values.get(prefix + "serendipity_active")
        ),
        "reverie_active": bool_text(values.get(prefix + "reverie_active")),
    }


def capture(pair: SteamFriendActivePair, endpoint: str) -> dict[str, Any]:
    values = parse_key_values(pair.lua(endpoint, CAPTURE_LUA, timeout=10.0))
    participants: dict[int, dict[str, Any]] = {}
    for participant_index in range(
        1, parse_int_text(values.get("participant.count"), 0) + 1
    ):
        prefix = f"participant.{participant_index}."
        participant_id = parse_int_text(values.get(prefix + "id"), 0)
        count = parse_int_text(values.get(prefix + "count"), -1)
        if participant_id <= 1:
            continue
        participants[participant_id] = {
            "revision": parse_int_text(values.get(prefix + "revision"), 0),
            "valid": bool_text(values.get(prefix + "valid")),
            "count": count,
            "capacity": parse_int_text(values.get(prefix + "capacity"), -1),
            "selectors": selector_list(values, prefix, max(count, 0)),
            "cheat_death_charges": parse_int_text(
                values.get(prefix + "cheat_death_charges"), -1
            ),
            "serendipity_active": bool_text(
                values.get(prefix + "serendipity_active")
            ),
            "reverie_active": bool_text(
                values.get(prefix + "reverie_active")
            ),
            "native": native_state(values, prefix + "native."),
        }
    return {
        "scene": values.get("scene", ""),
        "owner_native": native_state(values, "owner.native."),
        "participants": participants,
    }


def apply_selector(
    pair: SteamFriendActivePair,
    endpoint: str,
    selector: int,
) -> None:
    code = f"""
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
local progression = tonumber(player and player.progression_address) or 0
local count_offset = sd.debug.layout_offset("progression_hagatha_perk_count")
local capacity_offset = sd.debug.layout_offset("progression_hagatha_perk_capacity")
local before_count = progression ~= 0 and
  (sd.debug.read_i32(progression + count_offset) or -1) or -1
local before_capacity = progression ~= 0 and
  (sd.debug.read_i32(progression + capacity_offset) or -1) or -1
local apply = sd.debug.resolve_game_address({APPLY_HAGATHA_PERK})
local ok = progression ~= 0 and before_count >= 0 and
  before_count < before_capacity and
  sd.debug.call_thiscall_u32(apply, progression, {selector}) or false
if ok and {selector} == {TONIC_SELECTOR} then
  ok = sd.debug.write_i32(
    progression + capacity_offset, math.min(9, before_capacity + 3))
end
print("applied=" .. tostring(ok))
print("progression=" .. tostring(progression))
print("before_count=" .. tostring(before_count))
print("before_capacity=" .. tostring(before_capacity))
"""
    values = parse_key_values(pair.lua(endpoint, code, timeout=10.0))
    if not bool_text(values.get("applied")):
        raise VerifyFailure(
            "stock Hagatha apply was rejected: "
            f"selector={selector} values={values}"
        )


def wait_until(
    description: str,
    timeout: float,
    sample: Callable[[], tuple[bool, Any]],
) -> Any:
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        ready, last = sample()
        if ready:
            return last
        time.sleep(0.1)
    raise VerifyFailure(f"timed out waiting for {description}: {last}")


def verify_direction(
    pair: SteamFriendActivePair,
    *,
    owner_label: str,
    owner_endpoint: str,
    owner_participant_id: int,
    observer_endpoint: str,
    observer_participant_id: int,
    selector: int,
    timeout: float,
) -> dict[str, Any]:
    baseline_owner = capture(pair, owner_endpoint)
    baseline_observer = capture(pair, observer_endpoint)
    if baseline_owner["scene"] != "hub" or baseline_observer["scene"] != "hub":
        raise VerifyFailure("Hagatha synchronization requires both players in the hub")
    owner_native = baseline_owner["owner_native"]
    observer_ledger = baseline_observer["participants"].get(owner_participant_id)
    if owner_native["count"] < 0 or owner_native["count"] >= owner_native["capacity"]:
        raise VerifyFailure(f"{owner_label} has no open Hagatha perk slot")
    if observer_ledger is None:
        raise VerifyFailure(f"{owner_label} is absent from the observer ledger")

    expected_selectors = owner_native["native_selector_list"] + [selector]
    expected_capacity = owner_native["capacity"]
    if selector == TONIC_SELECTOR:
        expected_capacity = min(9, expected_capacity + 3)
    baseline_revision = observer_ledger["revision"]
    observer_own_native_before = baseline_observer["owner_native"]
    apply_selector(pair, owner_endpoint, selector)

    def sample() -> tuple[bool, dict[str, Any]]:
        owner = capture(pair, owner_endpoint)
        observer = capture(pair, observer_endpoint)
        ledger = observer["participants"].get(owner_participant_id)
        native = ledger and ledger["native"]
        ready = (
            owner["owner_native"]["native_selector_list"] == expected_selectors
            and owner["owner_native"]["capacity"] == expected_capacity
            and ledger is not None
            and ledger["valid"]
            and ledger["revision"] > baseline_revision
            and ledger["selectors"] == expected_selectors
            and ledger["capacity"] == expected_capacity
            and native is not None
            and native["native_selector_list"] == expected_selectors
            and native["capacity"] == expected_capacity
        )
        return ready, {"owner": owner, "observer": observer, "ledger": ledger}

    converged = wait_until(
        f"{owner_label} selector {selector} native replication",
        timeout,
        sample,
    )
    final_observer = converged["observer"]
    if final_observer["owner_native"] != observer_own_native_before:
        raise VerifyFailure(
            f"{owner_label} selector mutated observer {observer_participant_id} ownership"
        )

    final_ledger = converged["ledger"]
    return {
        "ok": True,
        "owner": owner_label,
        "owner_participant_id": owner_participant_id,
        "observer_participant_id": observer_participant_id,
        "selector": selector,
        "expected_selectors": expected_selectors,
        "observer_revision_delta": final_ledger["revision"] - baseline_revision,
        "hagatha_perks": final_ledger,
        "observer_owner_state_unchanged": True,
    }


def run(
    pair: SteamFriendActivePair,
    selector: int,
    timeout: float,
) -> dict[str, Any]:
    if selector < 0 or selector >= EXPECTED_PERK_COUNT:
        raise VerifyFailure(f"selector must be in 0..{EXPECTED_PERK_COUNT - 1}")
    pair_state = pair.discover()
    host_to_client = verify_direction(
        pair,
        owner_label="host",
        owner_endpoint=HOST_ENDPOINT,
        owner_participant_id=pair.host_participant_id,
        observer_endpoint=CLIENT_ENDPOINT,
        observer_participant_id=pair.client_participant_id,
        selector=selector,
        timeout=timeout,
    )
    client_to_host = verify_direction(
        pair,
        owner_label="client",
        owner_endpoint=CLIENT_ENDPOINT,
        owner_participant_id=pair.client_participant_id,
        observer_endpoint=HOST_ENDPOINT,
        observer_participant_id=pair.host_participant_id,
        selector=selector,
        timeout=timeout,
    )
    return {
        "ok": host_to_client["ok"] and client_to_host["ok"],
        "transport": "steam_friend",
        "pair_backend": PAIR_BACKEND,
        "pair": pair_state,
        "selector": selector,
        "directions": {
            "host_to_client": host_to_client,
            "client_to_host": client_to_host,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selector", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    pair = SteamFriendActivePair()
    result: dict[str, Any] = {"ok": False}
    try:
        result = run(pair, args.selector, args.timeout)
    except Exception as exc:
        result["error"] = str(exc)
        result["error_type"] = type(exc).__name__
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
                "selector": args.selector,
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
