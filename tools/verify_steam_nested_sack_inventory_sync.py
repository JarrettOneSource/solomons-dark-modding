#!/usr/bin/env python3
"""Verify participant-owned nested sacks on an active two-account Steam pair."""

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


SACK_TYPE_ID = 0x1B60
POTION_TYPE_ID = 0x1B59
INVENTORY_FIND_ITEM_BY_TYPE_RECURSIVE = 0x00552650
DEFAULT_OUTPUT = ROOT / "runtime/steam_nested_sack_inventory_sync.json"


CAPTURE_LUA = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end

local scene = sd.world and sd.world.get_scene and sd.world.get_scene() or nil
local inventory = sd.player and sd.player.get_inventory_state and
  sd.player.get_inventory_state() or nil
emit("scene", scene and (scene.name or scene.kind) or "")
emit("native.valid", inventory and inventory.valid or false)
emit("native.root", inventory and inventory.item_list_root_address or 0)
emit("native.item_count", inventory and inventory.item_count or 0)
emit("native.enumerated_item_count", inventory and inventory.enumerated_item_count or 0)
emit("native.truncated", inventory and inventory.truncated or false)

local sack_root_offset = sd.debug and sd.debug.layout_offset and
  sd.debug.layout_offset("sack_item_inventory_root_pointer") or nil
local native_items = inventory and inventory.items or {}
emit("native.row_count", #native_items)
for index, item in ipairs(native_items) do
  local prefix = "native.row." .. tostring(index) .. "."
  local container_root = 0
  if item.type_id == 0x1B60 and sack_root_offset ~= nil then
    container_root = sd.debug.read_ptr(
      (item.item_address or 0) + sack_root_offset) or 0
  end
  emit(prefix .. "address", item.item_address or 0)
  emit(prefix .. "type_id", item.type_id or 0)
  emit(prefix .. "recipe_uid", item.recipe_uid or 0)
  emit(prefix .. "slot", item.slot or -1)
  emit(prefix .. "stack_count", item.stack_count or 0)
  emit(prefix .. "parent_item_index", item.parent_item_index or -1)
  emit(prefix .. "container_depth", item.container_depth or 0)
  emit(prefix .. "container_inventory_root", container_root)
end

local multiplayer = sd.runtime and sd.runtime.get_multiplayer_state and
  sd.runtime.get_multiplayer_state() or nil
local participants = multiplayer and multiplayer.participants or {}
emit("participant.count", #participants)
for participant_index, participant in ipairs(participants) do
  local prefix = "participant." .. tostring(participant_index) .. "."
  local owned = participant.owned_progression or {}
  local items = owned.inventory_items or {}
  emit(prefix .. "id", participant.participant_id or 0)
  emit(prefix .. "revision", owned.inventory_revision or 0)
  emit(prefix .. "item_count", #items)
  emit(prefix .. "total_count", owned.inventory_item_total_count or 0)
  emit(prefix .. "truncated", owned.inventory_truncated or false)
  for item_index, item in ipairs(items) do
    local item_prefix = prefix .. "row." .. tostring(item_index) .. "."
    emit(item_prefix .. "type_id", item.type_id or 0)
    emit(item_prefix .. "recipe_uid", item.recipe_uid or 0)
    emit(item_prefix .. "slot", item.slot or -1)
    emit(item_prefix .. "stack_count", item.stack_count or 0)
    emit(item_prefix .. "parent_item_index", item.parent_item_index or -1)
    emit(item_prefix .. "container_depth", item.container_depth or 0)
  end
end
"""


def bool_text(value: str | None) -> bool:
    return value in ("1", "true")


def native_rows(values: dict[str, str]) -> list[dict[str, int]]:
    rows: list[dict[str, int]] = []
    count = parse_int_text(values.get("native.row_count"), 0)
    for lua_index in range(1, count + 1):
        prefix = f"native.row.{lua_index}."
        rows.append(
            {
                "index": lua_index - 1,
                "address": parse_int_text(values.get(prefix + "address"), 0),
                "type_id": parse_int_text(values.get(prefix + "type_id"), 0),
                "recipe_uid": parse_int_text(
                    values.get(prefix + "recipe_uid"), 0
                ),
                "slot": parse_int_text(values.get(prefix + "slot"), -1),
                "stack_count": parse_int_text(
                    values.get(prefix + "stack_count"), 0
                ),
                "parent_item_index": parse_int_text(
                    values.get(prefix + "parent_item_index"), -1
                ),
                "container_depth": parse_int_text(
                    values.get(prefix + "container_depth"), 0
                ),
                "container_inventory_root": parse_int_text(
                    values.get(prefix + "container_inventory_root"), 0
                ),
            }
        )
    return rows


def participant_rows(values: dict[str, str]) -> dict[int, dict[str, Any]]:
    participants: dict[int, dict[str, Any]] = {}
    count = parse_int_text(values.get("participant.count"), 0)
    for participant_index in range(1, count + 1):
        prefix = f"participant.{participant_index}."
        participant_id = parse_int_text(values.get(prefix + "id"), 0)
        item_count = parse_int_text(values.get(prefix + "item_count"), 0)
        rows: list[dict[str, int]] = []
        for lua_index in range(1, item_count + 1):
            item_prefix = f"{prefix}row.{lua_index}."
            rows.append(
                {
                    "index": lua_index - 1,
                    "type_id": parse_int_text(
                        values.get(item_prefix + "type_id"), 0
                    ),
                    "recipe_uid": parse_int_text(
                        values.get(item_prefix + "recipe_uid"), 0
                    ),
                    "slot": parse_int_text(
                        values.get(item_prefix + "slot"), -1
                    ),
                    "stack_count": parse_int_text(
                        values.get(item_prefix + "stack_count"), 0
                    ),
                    "parent_item_index": parse_int_text(
                        values.get(item_prefix + "parent_item_index"), -1
                    ),
                    "container_depth": parse_int_text(
                        values.get(item_prefix + "container_depth"), 0
                    ),
                }
            )
        if participant_id > 1:
            participants[participant_id] = {
                "revision": parse_int_text(values.get(prefix + "revision"), 0),
                "item_count": item_count,
                "total_count": parse_int_text(
                    values.get(prefix + "total_count"), 0
                ),
                "truncated": bool_text(values.get(prefix + "truncated")),
                "rows": rows,
            }
    return participants


def capture(pair: SteamFriendActivePair, endpoint: str) -> dict[str, Any]:
    values = parse_key_values(pair.lua(endpoint, CAPTURE_LUA, timeout=10.0))
    return {
        "scene": values.get("scene", ""),
        "native_valid": bool_text(values.get("native.valid")),
        "native_root": parse_int_text(values.get("native.root"), 0),
        "native_item_count": parse_int_text(values.get("native.item_count"), 0),
        "native_enumerated_item_count": parse_int_text(
            values.get("native.enumerated_item_count"), 0
        ),
        "native_truncated": bool_text(values.get("native.truncated")),
        "native_rows": native_rows(values),
        "participants": participant_rows(values),
    }


def semantic_rows(rows: list[dict[str, int]]) -> list[dict[str, int]]:
    fields = (
        "index",
        "type_id",
        "recipe_uid",
        "slot",
        "stack_count",
        "parent_item_index",
        "container_depth",
    )
    return [{field: row[field] for field in fields} for row in rows]


def native_snapshot_identity(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "valid": snapshot["native_valid"],
        "root": snapshot["native_root"],
        "item_count": snapshot["native_item_count"],
        "enumerated_item_count": snapshot["native_enumerated_item_count"],
        "truncated": snapshot["native_truncated"],
        "rows": snapshot["native_rows"],
    }


def queue_fixture(
    pair: SteamFriendActivePair,
    endpoint: str,
    potion_slot: int,
    stack_count: int,
) -> None:
    code = f"""
local ok, err = sd.debug.queue_nested_sack_inventory_fixture(
  {potion_slot}, {stack_count})
print("queued=" .. tostring(ok))
print("error=" .. tostring(err or ""))
"""
    values = parse_key_values(pair.lua(endpoint, code, timeout=10.0))
    if not bool_text(values.get("queued")):
        raise VerifyFailure(
            "nested-sack fixture was rejected: " + values.get("error", "")
        )


def stock_recursive_find(
    pair: SteamFriendActivePair,
    endpoint: str,
    container_inventory_root: int,
) -> int:
    code = f"""
local fn = sd.debug.resolve_game_address(
  {INVENTORY_FIND_ITEM_BY_TYPE_RECURSIVE})
local found = sd.debug.call_thiscall_u32_ret_u32(
  fn, {container_inventory_root}, {POTION_TYPE_ID})
print("found=" .. tostring(found or 0))
"""
    values = parse_key_values(pair.lua(endpoint, code, timeout=10.0))
    return parse_int_text(values.get("found"), 0)


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
    owner_id: int,
    observer_endpoint: str,
    potion_slot: int,
    stack_count: int,
    timeout: float,
) -> dict[str, Any]:
    baseline_owner = capture(pair, owner_endpoint)
    baseline_observer = capture(pair, observer_endpoint)
    if not baseline_owner["native_valid"] or baseline_owner["native_truncated"]:
        raise VerifyFailure(f"{owner_label} native inventory is not auditable")
    if owner_id not in baseline_observer["participants"]:
        raise VerifyFailure(f"{owner_label} observer ledger is missing")

    baseline_owner_addresses = {
        row["address"] for row in baseline_owner["native_rows"]
    }
    baseline_owner_rows = {
        row["address"]: row for row in baseline_owner["native_rows"]
    }
    baseline_observer_revision = baseline_observer["participants"][owner_id][
        "revision"
    ]
    baseline_observer_native = native_snapshot_identity(baseline_observer)

    queue_fixture(pair, owner_endpoint, potion_slot, stack_count)

    def sample() -> tuple[bool, dict[str, Any]]:
        owner = capture(pair, owner_endpoint)
        observer = capture(pair, observer_endpoint)
        new_rows = [
            row
            for row in owner["native_rows"]
            if row["address"] not in baseline_owner_addresses
        ]
        sacks = [row for row in new_rows if row["type_id"] == SACK_TYPE_ID]
        nested_potions: list[dict[str, int]] = []
        if len(sacks) == 1:
            sack = sacks[0]
            nested_potions = [
                row
                for row in new_rows
                if row["type_id"] == POTION_TYPE_ID
                and row["slot"] == potion_slot
                and row["stack_count"] == stack_count
                and row["parent_item_index"] == sack["index"]
                and row["container_depth"] == sack["container_depth"] + 1
            ]
        observer_ledger = observer["participants"].get(owner_id)
        owner_semantic = semantic_rows(owner["native_rows"])
        ready = (
            owner["native_valid"]
            and not owner["native_truncated"]
            and len(new_rows) == 2
            and len(sacks) == 1
            and sacks[0]["container_inventory_root"] != 0
            and len(nested_potions) == 1
            and observer_ledger is not None
            and observer_ledger["revision"] > baseline_observer_revision
            and not observer_ledger["truncated"]
            and observer_ledger["total_count"] == owner["native_item_count"]
            and observer_ledger["rows"] == owner_semantic
        )
        return ready, {
            "owner": owner,
            "observer": observer,
            "new_rows": new_rows,
            "sacks": sacks,
            "nested_potions": nested_potions,
        }

    converged = wait_until(
        f"{owner_label} nested inventory replication", timeout, sample
    )
    final_owner = converged["owner"]
    final_observer = converged["observer"]
    sack = converged["sacks"][0]
    nested_potion = converged["nested_potions"][0]

    final_rows_by_address = {
        row["address"]: row for row in final_owner["native_rows"]
    }
    owner_native_inventory_unchanged_outside_fixture = all(
        final_rows_by_address.get(address) == row
        for address, row in baseline_owner_rows.items()
    )
    observer_native_inventory_unchanged = (
        native_snapshot_identity(final_observer) == baseline_observer_native
    )
    if not owner_native_inventory_unchanged_outside_fixture:
        raise VerifyFailure(f"{owner_label} existing native inventory changed")
    if not observer_native_inventory_unchanged:
        raise VerifyFailure(f"{owner_label} fixture mutated the observer inventory")

    recursive_match = stock_recursive_find(
        pair,
        owner_endpoint,
        sack["container_inventory_root"],
    )
    if recursive_match != nested_potion["address"]:
        raise VerifyFailure(
            f"{owner_label} stock recursive finder did not return the nested potion"
        )

    return {
        "ok": True,
        "owner": owner_label,
        "potion_slot": potion_slot,
        "stack_count": stack_count,
        "container_inventory_root": sack["container_inventory_root"],
        "sack": sack,
        "nested_potion": nested_potion,
        "stock_recursive_find_match": True,
        "owner_native_inventory_unchanged_outside_fixture": (
            owner_native_inventory_unchanged_outside_fixture
        ),
        "observer_native_inventory_unchanged": (
            observer_native_inventory_unchanged
        ),
        "observer_inventory_revision_delta": (
            final_observer["participants"][owner_id]["revision"]
            - baseline_observer_revision
        ),
        "owner_item_count_delta": (
            final_owner["native_item_count"]
            - baseline_owner["native_item_count"]
        ),
    }


def run(pair: SteamFriendActivePair, timeout: float) -> dict[str, Any]:
    pair_state = pair.discover()
    scenes = {pair_state[side].get("scene") for side in ("host", "client")}
    if not scenes.issubset({"hub", "testrun"}):
        raise VerifyFailure(f"Steam friend pair has no active inventory scene: {pair_state}")

    host_owner = verify_direction(
        pair,
        owner_label="host",
        owner_endpoint=HOST_ENDPOINT,
        owner_id=pair.host_participant_id,
        observer_endpoint=CLIENT_ENDPOINT,
        potion_slot=0,
        stack_count=37,
        timeout=timeout,
    )
    client_owner = verify_direction(
        pair,
        owner_label="client",
        owner_endpoint=CLIENT_ENDPOINT,
        owner_id=pair.client_participant_id,
        observer_endpoint=HOST_ENDPOINT,
        potion_slot=1,
        stack_count=41,
        timeout=timeout,
    )
    return {
        "ok": host_owner["ok"] and client_owner["ok"],
        "transport": "steam_friend",
        "pair_backend": PAIR_BACKEND,
        "pair": pair_state,
        "directions": {
            "host_owner": host_owner,
            "client_owner": client_owner,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    pair = SteamFriendActivePair()
    result: dict[str, Any] = {"ok": False}
    try:
        result = run(pair, args.timeout)
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
                "directions": sorted(result.get("directions", {})),
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
