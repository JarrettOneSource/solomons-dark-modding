#!/usr/bin/env python3
"""Verify an exact recipe-backed item pickup enters a remote stock inventory."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_PIPE,
    HOST_PIPE,
    ROOT,
    VerifyFailure,
    parse_int_text,
    stop_games,
)
from verify_multiplayer_gold_pickup_authority import (
    move_client_into_pickup_range,
    move_client_out_of_pickup_range,
    request_pickup,
    select_spawn_point,
)
from verify_multiplayer_inventory_audit import (
    capture as capture_inventory,
    find_participant,
    item_rows,
    participant_rows,
)
from verify_multiplayer_loot_drop_materialization import (
    HAT_HELPER_TYPE_ID,
    ITEM_DROP_TYPE_ID,
    POTION_ITEM_TYPE_ID,
    ROBE_HELPER_TYPE_ID,
    actor_rows,
    capture as capture_loot,
    field_comparison,
    require_host_spawn,
    select_actor,
    setup_pair,
    values,
    wait_for_materialized_drop,
)
from verify_multiplayer_native_potion_inventory_sync import (
    client_native_apply_log_lines,
    find_local_participant,
    wait_for_client_presentation_absent,
)


RUNTIME_OUTPUT = ROOT / "runtime" / "multiplayer_native_item_inventory_sync.json"
WEARABLE_TYPE_IDS = (HAT_HELPER_TYPE_ID, ROBE_HELPER_TYPE_ID)
STAFF_HELPER_TYPE_ID = 0x1B5C
WAND_HELPER_TYPE_ID = 0x1B63
RING_ITEM_TYPE_ID = 0x1B5A
AMULET_ITEM_TYPE_ID = 0x1B5B
VISIBLE_EQUIPMENT_TYPE_IDS = (*WEARABLE_TYPE_IDS, STAFF_HELPER_TYPE_ID, WAND_HELPER_TYPE_ID)
EQUIPPABLE_TYPE_IDS = (
    RING_ITEM_TYPE_ID,
    AMULET_ITEM_TYPE_ID,
    *VISIBLE_EQUIPMENT_TYPE_IDS,
)


RECIPE_CATALOG_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value or "")) end
local count_game = sd.debug.layout_offset("item_recipe_count", "gameplay.globals")
local entries_game = sd.debug.layout_offset("item_recipe_entries", "gameplay.globals")
local uid_offset = sd.debug.layout_offset("item_recipe_definition_uid")
local type_offset = sd.debug.layout_offset("item_recipe_definition_type_id")
local count_address = count_game and sd.debug.resolve_game_address(count_game) or 0
local entries_address = entries_game and sd.debug.resolve_game_address(entries_game) or 0
local count = count_address ~= 0 and (sd.debug.read_i32(count_address) or 0) or 0
local entries = entries_address ~= 0 and (sd.debug.read_u32(entries_address) or 0) or 0
emit("catalog.count", count)
emit("catalog.entries", entries)
local row = 0
if count > 0 and count <= 16384 and entries ~= 0 and uid_offset and type_offset then
  for index = 0, count - 1 do
    local recipe = sd.debug.read_u32(entries + index * 4) or 0
    if recipe ~= 0 then
      local uid = sd.debug.read_u32(recipe + uid_offset) or 0
      local item_type = sd.debug.read_u32(recipe + type_offset) or 0
      if uid ~= 0 and item_type ~= 0 and item_type ~= 0x1B59 then
        row = row + 1
        local prefix = "recipe." .. tostring(row) .. "."
        emit(prefix .. "index", index)
        emit(prefix .. "address", recipe)
        emit(prefix .. "uid", uid)
        emit(prefix .. "type_id", item_type)
      end
    end
  end
end
emit("recipe.row_count", row)
"""


PICKUP_STATE_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value or "")) end
local function bytes_hex(bytes)
  if type(bytes) ~= "table" then return "" end
  local parts = {}
  for index = 1, 32 do
    local value = tonumber(bytes[index])
    if value == nil then return "" end
    parts[#parts + 1] = string.format("%02x", value)
  end
  return table.concat(parts)
end
local loot = sd.world and sd.world.get_replicated_loot and sd.world.get_replicated_loot() or nil
local result = loot and loot.last_pickup_result or nil
emit("valid", result ~= nil)
if result then
  emit("network_drop_id", result.network_drop_id or 0)
  emit("request_sequence", result.request_sequence or 0)
  emit("result", result.result or "")
  emit("kind", result.kind or "")
  emit("item_type_id", result.item_type_id or 0)
  emit("item_recipe_uid", result.item_recipe_uid or 0)
  emit("item_color_state_valid", result.item_color_state_valid or false)
  emit("item_color_state", bytes_hex(result.item_color_state))
  emit("item_slot", result.item_slot or -1)
  emit("stack_count", result.stack_count or 0)
  emit("inventory_revision", result.inventory_revision or 0)
end
"""


EQUIP_REQUEST_LUA = r"""
local ok, err = sd.player.equip_inventory_item(__RECIPE_UID__)
print("queued=" .. tostring(ok or false))
print("error=" .. tostring(err or ""))
"""


EQUIPMENT_CAPTURE_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value or "")) end
local function bytes_hex(bytes)
  if type(bytes) ~= "table" then return "" end
  local parts = {}
  for index = 1, 32 do
    local value = tonumber(bytes[index])
    if value == nil then return "" end
    parts[#parts + 1] = string.format("%02x", value)
  end
  return table.concat(parts)
end
local target_type = __ITEM_TYPE_ID__
local target_participant = __PARTICIPANT_ID__
local select_local_owner = __SELECT_LOCAL_OWNER__
local function inventory_lane(inventory)
  if not inventory then return nil end
  local lanes = {
    inventory.primary_visual_lane,
    inventory.secondary_visual_lane,
    inventory.attachment_visual_lane,
  }
  for _, lane in ipairs(inventory.ring_lanes or {}) do
    lanes[#lanes + 1] = lane
  end
  lanes[#lanes + 1] = inventory.amulet_lane
  for _, lane in ipairs(lanes) do
    if lane and (lane.current_object_type_id or 0) == target_type then return lane end
  end
  return nil
end
local function runtime_lane(equipment)
  if not equipment then return nil end
  local lanes = {
    equipment.primary,
    equipment.secondary,
    equipment.attachment,
    equipment.hat,
    equipment.robe,
    equipment.weapon,
  }
  for _, lane in ipairs(equipment.rings or {}) do
    lanes[#lanes + 1] = lane
  end
  lanes[#lanes + 1] = equipment.amulet
  for _, lane in ipairs(lanes) do
    if lane and (lane.type_id or 0) == target_type then return lane end
  end
  return nil
end
local function bot_lane(bot)
  if not bot then return nil end
  local lanes = {
    bot.primary_visual_lane,
    bot.secondary_visual_lane,
    bot.attachment_visual_lane,
  }
  for _, lane in ipairs(lanes) do
    if lane and (lane.current_object_type_id or 0) == target_type then return lane end
  end
  return nil
end

local inventory = sd.player.get_inventory_state()
local local_lane = inventory_lane(inventory)
emit("local.valid", local_lane ~= nil)
emit("local.type_id", local_lane and local_lane.current_object_type_id or 0)
emit("local.recipe_uid", local_lane and local_lane.current_object_recipe_uid or 0)
emit("local.object", local_lane and local_lane.current_object_address or 0)
emit("local.color_valid", local_lane and local_lane.current_object_color_state_valid or false)
emit("local.color", bytes_hex(local_lane and local_lane.current_object_color_state or nil))

local multiplayer = sd.runtime.get_multiplayer_state()
local participant = nil
for _, candidate in ipairs(multiplayer and multiplayer.participants or {}) do
  if (select_local_owner and candidate.is_owner)
      or ((not select_local_owner)
          and (candidate.participant_id or 0) == target_participant) then
    participant = candidate
    break
  end
end
local equipment = participant and participant.equipment or nil
local runtime_lane_value = runtime_lane(equipment)
emit("runtime.valid", equipment and equipment.valid or false)
emit("runtime.type_id", runtime_lane_value and runtime_lane_value.type_id or 0)
emit("runtime.recipe_uid", runtime_lane_value and runtime_lane_value.recipe_uid or 0)
emit("runtime.color", bytes_hex(runtime_lane_value and runtime_lane_value.color_state or nil))

local bot = sd.bots.get_participant_state(target_participant)
local bot_lane_value = bot_lane(bot)
emit("bot.valid", bot_lane_value ~= nil)
emit("bot.type_id", bot_lane_value and bot_lane_value.current_object_type_id or 0)
emit("bot.recipe_uid", bot_lane_value and bot_lane_value.current_object_recipe_uid or 0)
emit("bot.object", bot_lane_value and bot_lane_value.current_object_address or 0)
emit("bot.color_valid", bot_lane_value and bot_lane_value.current_object_color_state_valid or false)
emit("bot.color", bytes_hex(bot_lane_value and bot_lane_value.current_object_color_state or nil))
"""


def recipe_rows(capture: dict[str, str]) -> list[dict[str, int]]:
    rows: list[dict[str, int]] = []
    for row_index in range(1, parse_int_text(capture.get("recipe.row_count"), 0) + 1):
        prefix = f"recipe.{row_index}."
        rows.append({
            "index": parse_int_text(capture.get(prefix + "index"), -1),
            "address": parse_int_text(capture.get(prefix + "address"), 0),
            "uid": parse_int_text(capture.get(prefix + "uid"), 0),
            "type_id": parse_int_text(capture.get(prefix + "type_id"), 0),
        })
    return rows


def select_recipe(
    client_inventory: dict[str, str],
    preferred_type_id: int | None = None,
) -> dict[str, Any]:
    capture = values(HOST_PIPE, RECIPE_CATALOG_LUA, timeout=8.0)
    rows = recipe_rows(capture)
    if not rows:
        raise VerifyFailure(f"stock item recipe catalog is empty or unavailable: {capture}")

    owned_identities = {
        (item["type_id"], item["recipe_uid"])
        for item in item_rows(client_inventory)
        if item["valid"]
    }
    type_preference = (
        (preferred_type_id,)
        if preferred_type_id is not None
        else EQUIPPABLE_TYPE_IDS
    )
    for preferred_type in type_preference:
        for row in rows:
            if (
                row["type_id"] == preferred_type
                and (row["type_id"], row["uid"]) not in owned_identities
            ):
                return {
                    **row,
                    "wearable": row["type_id"] in WEARABLE_TYPE_IDS,
                    "catalog_count": parse_int_text(capture.get("catalog.count"), 0),
                }
    if preferred_type_id is not None:
        raise VerifyFailure(
            f"no unowned stock recipe exists for item type 0x{preferred_type_id:04X}"
        )
    for row in rows:
        if (row["type_id"], row["uid"]) not in owned_identities:
            return {
                **row,
                "wearable": row["type_id"] in WEARABLE_TYPE_IDS,
                "catalog_count": parse_int_text(capture.get("catalog.count"), 0),
            }
    raise VerifyFailure("no stock recipe absent from the client inventory was available")


def pickup_state() -> dict[str, str]:
    return values(CLIENT_PIPE, PICKUP_STATE_LUA)


def wait_for_pickup_result(
    network_drop_id: int,
    expected_result: str,
    timeout: float,
    request_sequence: int | None = None,
) -> dict[str, str] | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = pickup_state()
        if (
            state.get("valid") == "true"
            and parse_int_text(state.get("network_drop_id"), 0) == network_drop_id
            and state.get("result") == expected_result
            and (
                request_sequence is None
                or parse_int_text(state.get("request_sequence"), 0) == request_sequence
            )
        ):
            return state
        time.sleep(0.1)
    return None


def exact_native_rows(
    capture: dict[str, str],
    item_type_id: int,
    recipe_uid: int,
) -> list[dict[str, Any]]:
    return [
        row
        for row in item_rows(capture)
        if row["valid"]
        and row["type_id"] == item_type_id
        and row["recipe_uid"] == recipe_uid
    ]


def exact_owned_count(
    participant: dict[str, Any] | None,
    item_type_id: int,
    recipe_uid: int,
) -> int:
    if participant is None:
        return -1
    return sum(
        1
        for item in participant["inventory_items"]
        if item["type_id"] == item_type_id and item["recipe_uid"] == recipe_uid
    )


def normalized_hex_bytes(value: str | None) -> str:
    return (value or "").strip().lower()


def capture_equipment(
    pipe_name: str,
    item_type_id: int,
    *,
    select_local_owner: bool = False,
) -> dict[str, str]:
    script = (
        EQUIPMENT_CAPTURE_LUA
        .replace("__ITEM_TYPE_ID__", str(item_type_id))
        .replace("__PARTICIPANT_ID__", str(CLIENT_ID))
        .replace("__SELECT_LOCAL_OWNER__", "true" if select_local_owner else "false")
    )
    return values(pipe_name, script, timeout=8.0)


def queue_client_equip(recipe_uid: int) -> dict[str, str]:
    return values(
        CLIENT_PIPE,
        EQUIP_REQUEST_LUA.replace("__RECIPE_UID__", str(recipe_uid)),
        timeout=8.0,
    )


def wait_for_host_actor(
    *,
    item_type_id: int,
    recipe_uid: int,
    x: float,
    y: float,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = capture_loot(HOST_PIPE)
        selected = select_actor(
            actor_rows(last),
            type_id=ITEM_DROP_TYPE_ID,
            amount=None,
            resource_kind=None,
            raw_value=None,
            item_type_id=item_type_id,
            item_recipe_uid=recipe_uid,
            x=x,
            y=y,
        )
        if selected is not None:
            return selected
        time.sleep(0.1)
    raise VerifyFailure(
        f"host did not materialize recipe-backed item type=0x{item_type_id:04X} "
        f"recipe={recipe_uid}: {last}"
    )


def wait_for_native_convergence(
    *,
    item_type_id: int,
    recipe_uid: int,
    expected_count: int,
    accepted_revision: int,
    expected_color_state: str,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        client = capture_inventory(CLIENT_PIPE)
        host = capture_inventory(HOST_PIPE)
        client_local = find_local_participant(client)
        host_client = find_participant(host, CLIENT_ID)
        native_rows = exact_native_rows(client, item_type_id, recipe_uid)
        colors_match = not expected_color_state or any(
            row["color_state_valid"]
            and normalized_hex_bytes(row["color_state"]) == expected_color_state
            for row in native_rows
        )
        last = {
            "client_native_count": len(native_rows),
            "client_native_rows": native_rows,
            "client_owned_count": exact_owned_count(client_local, item_type_id, recipe_uid),
            "host_owned_client_count": exact_owned_count(host_client, item_type_id, recipe_uid),
            "client_inventory_revision": (
                client_local["inventory_revision"] if client_local is not None else -1
            ),
            "host_inventory_revision": (
                host_client["inventory_revision"] if host_client is not None else -1
            ),
            "client_inventory_host_authoritative": (
                client_local["inventory_host_authoritative"]
                if client_local is not None
                else None
            ),
            "wearable_color_matches": colors_match,
        }
        if (
            last["client_native_count"] == expected_count
            and last["client_owned_count"] == expected_count
            and last["host_owned_client_count"] == expected_count
            and last["client_inventory_revision"] >= accepted_revision
            and last["host_inventory_revision"] >= accepted_revision
            and last["client_inventory_host_authoritative"] is False
            and colors_match
        ):
            return last
        if last["client_native_count"] > expected_count:
            raise VerifyFailure(f"native item was credited more than once: {last}")
        time.sleep(0.1)
    raise VerifyFailure(f"native item inventory did not converge: {last}")


def wait_for_equipment_convergence(
    *,
    item_type_id: int,
    recipe_uid: int,
    accepted_revision: int,
    expected_color_state: str,
    previous_item_address: int,
    timeout: float,
) -> dict[str, Any]:
    visible_equipment = item_type_id in VISIBLE_EQUIPMENT_TYPE_IDS
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        client = capture_inventory(CLIENT_PIPE)
        host = capture_inventory(HOST_PIPE)
        client_equipment = capture_equipment(
            CLIENT_PIPE,
            item_type_id,
            select_local_owner=True,
        )
        host_equipment = capture_equipment(HOST_PIPE, item_type_id)
        client_local = find_local_participant(client)
        host_client = find_participant(host, CLIENT_ID)
        client_rows = item_rows(client)
        target_rows = exact_native_rows(client, item_type_id, recipe_uid)
        previous_item_returned = previous_item_address == 0 or any(
            row["valid"] and row["address"] == previous_item_address
            for row in client_rows
        )

        expected_color = normalized_hex_bytes(expected_color_state)
        client_local_color_matches = (
            not expected_color
            or (
                client_equipment.get("local.color_valid") == "true"
                and normalized_hex_bytes(client_equipment.get("local.color"))
                == expected_color
            )
        )
        client_runtime_color_matches = (
            not expected_color
            or normalized_hex_bytes(client_equipment.get("runtime.color"))
            == expected_color
        )
        host_runtime_color_matches = (
            not expected_color
            or normalized_hex_bytes(host_equipment.get("runtime.color"))
            == expected_color
        )
        host_bot_color_matches = (
            not expected_color
            or (
                host_equipment.get("bot.color_valid") == "true"
                and normalized_hex_bytes(host_equipment.get("bot.color"))
                == expected_color
            )
        )
        last = {
            "client_native_inventory_target_count": len(target_rows),
            "client_owned_target_count": exact_owned_count(
                client_local, item_type_id, recipe_uid
            ),
            "host_owned_client_target_count": exact_owned_count(
                host_client, item_type_id, recipe_uid
            ),
            "client_inventory_revision": (
                client_local["inventory_revision"] if client_local is not None else -1
            ),
            "host_inventory_revision": (
                host_client["inventory_revision"] if host_client is not None else -1
            ),
            "previous_item_returned": previous_item_returned,
            "client_local_equipment": client_equipment,
            "client_runtime_equipment": {
                key: value
                for key, value in client_equipment.items()
                if key.startswith("runtime.")
            },
            "host_runtime_equipment": {
                key: value
                for key, value in host_equipment.items()
                if key.startswith("runtime.")
            },
            "host_native_remote_equipment": {
                key: value
                for key, value in host_equipment.items()
                if key.startswith("bot.")
            },
            "color_matches": {
                "client_local": client_local_color_matches,
                "client_runtime": client_runtime_color_matches,
                "host_runtime": host_runtime_color_matches,
                "host_native_remote": host_bot_color_matches,
            },
        }
        owner_and_runtime_identity = (
            client_equipment.get("local.valid") == "true"
            and parse_int_text(client_equipment.get("local.type_id"), 0)
            == item_type_id
            and parse_int_text(client_equipment.get("local.recipe_uid"), 0)
            == recipe_uid
            and client_equipment.get("runtime.valid") == "true"
            and parse_int_text(client_equipment.get("runtime.type_id"), 0)
            == item_type_id
            and parse_int_text(client_equipment.get("runtime.recipe_uid"), 0)
            == recipe_uid
            and host_equipment.get("runtime.valid") == "true"
            and parse_int_text(host_equipment.get("runtime.type_id"), 0)
            == item_type_id
            and parse_int_text(host_equipment.get("runtime.recipe_uid"), 0)
            == recipe_uid
        )
        native_remote_identity = (
            not visible_equipment
            or (
                host_equipment.get("bot.valid") == "true"
                and parse_int_text(host_equipment.get("bot.type_id"), 0)
                == item_type_id
                and parse_int_text(host_equipment.get("bot.recipe_uid"), 0)
                == recipe_uid
            )
        )
        if (
            len(target_rows) == 0
            and last["client_owned_target_count"] == 0
            and last["host_owned_client_target_count"] == 0
            and last["client_inventory_revision"] > accepted_revision
            and last["host_inventory_revision"] > accepted_revision
            and previous_item_returned
            and owner_and_runtime_identity
            and native_remote_identity
            and all(last["color_matches"].values())
        ):
            return last
        time.sleep(0.1)
    raise VerifyFailure(f"native equipment did not converge: {last}")


def run(args: argparse.Namespace) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": False}
    if not args.no_launch:
        result["setup"] = setup_pair(args.attempts)

    client_before = capture_inventory(CLIENT_PIPE)
    recipe = select_recipe(client_before, args.item_type)
    result["recipe"] = recipe
    count_before = len(exact_native_rows(client_before, recipe["type_id"], recipe["uid"]))

    spawn_point = select_spawn_point(args.timeout)
    item_x = float(spawn_point["snapped_x"])
    item_y = float(spawn_point["snapped_y"])
    result["spawn_point"] = spawn_point
    result["client_pre_spawn_parking"] = move_client_out_of_pickup_range(
        drop_x=item_x,
        drop_y=item_y,
        timeout=args.timeout,
    )
    result["spawn"] = require_host_spawn("item", recipe["uid"], item_x, item_y)

    host_actor = wait_for_host_actor(
        item_type_id=recipe["type_id"],
        recipe_uid=recipe["uid"],
        x=item_x,
        y=item_y,
        timeout=args.timeout,
    )
    materialized = wait_for_materialized_drop(
        type_id=ITEM_DROP_TYPE_ID,
        item_type_id=recipe["type_id"],
        item_recipe_uid=recipe["uid"],
        stack_count=1,
        x=item_x,
        y=item_y,
        timeout=args.timeout,
    )["drop"]
    comparison = field_comparison("recipe_item", host_actor, materialized)
    if not comparison["ok"]:
        raise VerifyFailure(f"recipe-backed item presentation mismatch: {comparison}")
    result["materialization"] = comparison

    network_drop_id = int(materialized["network_id"])
    expected_color_state = (
        normalized_hex_bytes(host_actor["item_color_state"])
        if recipe["wearable"]
        else ""
    )
    result["client_pickup_position"] = move_client_into_pickup_range(
        drop_x=float(materialized["x"]),
        drop_y=float(materialized["y"]),
        timeout=args.timeout,
    )
    accepted = wait_for_pickup_result(
        network_drop_id,
        "Accepted",
        min(1.5, args.timeout),
    )
    if accepted is None:
        request = request_pickup(network_drop_id)
        request_sequence = parse_int_text(request.get("request_sequence"), 0)
        accepted = wait_for_pickup_result(
            network_drop_id,
            "Accepted",
            args.timeout,
            request_sequence,
        )
        result["request"] = request
    else:
        result["request"] = {"path": "client_proximity_hook"}
    if accepted is None:
        raise VerifyFailure(f"client did not receive Accepted for item drop {network_drop_id}")

    accepted_revision = parse_int_text(accepted.get("inventory_revision"), 0)
    if (
        accepted.get("kind") != "Item"
        or parse_int_text(accepted.get("item_type_id"), 0) != recipe["type_id"]
        or parse_int_text(accepted.get("item_recipe_uid"), 0) != recipe["uid"]
        or parse_int_text(accepted.get("stack_count"), 0) != 1
        or accepted_revision <= 0
    ):
        raise VerifyFailure(f"accepted item result metadata is invalid: {accepted}")
    if recipe["wearable"] and (
        accepted.get("item_color_state_valid") != "true"
        or normalized_hex_bytes(accepted.get("item_color_state")) != expected_color_state
    ):
        raise VerifyFailure(
            f"accepted wearable color state differs from the host item: "
            f"host={expected_color_state} accepted={accepted}"
        )
    result["accepted_result"] = accepted

    expected_count = count_before + 1
    result["convergence"] = wait_for_native_convergence(
        item_type_id=recipe["type_id"],
        recipe_uid=recipe["uid"],
        expected_count=expected_count,
        accepted_revision=accepted_revision,
        expected_color_state=expected_color_state,
        timeout=args.timeout,
    )
    result["client_presentation"] = wait_for_client_presentation_absent(
        network_drop_id,
        args.timeout,
    )

    if recipe["type_id"] not in EQUIPPABLE_TYPE_IDS:
        raise VerifyFailure(
            f"selected stock item is not equippable by the focused verifier: {recipe}"
        )
    equipment_before = capture_equipment(
        CLIENT_PIPE,
        recipe["type_id"],
        select_local_owner=True,
    )
    previous_item_address = parse_int_text(equipment_before.get("local.object"), 0)
    equip_request = queue_client_equip(recipe["uid"])
    if equip_request.get("queued") != "true":
        raise VerifyFailure(f"client rejected native equipment request: {equip_request}")
    result["equipment"] = {
        "before": equipment_before,
        "request": equip_request,
        "convergence": wait_for_equipment_convergence(
            item_type_id=recipe["type_id"],
            recipe_uid=recipe["uid"],
            accepted_revision=accepted_revision,
            expected_color_state=expected_color_state,
            previous_item_address=previous_item_address,
            timeout=args.timeout,
        ),
    }

    duplicate = request_pickup(network_drop_id)
    duplicate_sequence = parse_int_text(duplicate.get("request_sequence"), 0)
    duplicate_result = wait_for_pickup_result(
        network_drop_id,
        "AlreadyGone",
        args.timeout,
        duplicate_sequence,
    )
    if duplicate_result is None:
        raise VerifyFailure(f"duplicate item pickup did not return AlreadyGone: {duplicate}")
    result["duplicate"] = {"request": duplicate, "result": duplicate_result}
    time.sleep(0.5)

    final_rows = exact_native_rows(
        capture_inventory(CLIENT_PIPE),
        recipe["type_id"],
        recipe["uid"],
    )
    if final_rows:
        raise VerifyFailure(
            f"duplicate item request returned equipped item to native inventory: {final_rows}"
        )
    result["native_apply_log"] = client_native_apply_log_lines(network_drop_id)
    if not any("applied authoritative item pickup" in line for line in result["native_apply_log"]):
        raise VerifyFailure(
            f"client log lacks native inventory apply evidence for drop {network_drop_id}: "
            f"{result['native_apply_log']}"
        )

    result["responsiveness"] = {
        "host": capture_inventory(HOST_PIPE).get("inventory.valid") == "true",
        "client": capture_inventory(CLIENT_PIPE).get("inventory.valid") == "true",
    }
    if not all(result["responsiveness"].values()):
        raise VerifyFailure(f"a multiplayer instance stopped responding: {result['responsiveness']}")
    result["count"] = {
        "before": count_before,
        "credited": 1,
        "equipped_inventory_count": len(final_rows),
    }
    result["ok"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-launch", action="store_true")
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument(
        "--item-type",
        type=lambda value: int(value, 0),
        choices=EQUIPPABLE_TYPE_IDS,
        help="Verify one exact native equipment type (decimal or 0x-prefixed).",
    )
    parser.add_argument("--output", type=Path, default=RUNTIME_OUTPUT)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    try:
        result = run(args)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({
            "ok": result["ok"],
            "recipe": result.get("recipe"),
            "count": result.get("count"),
            "convergence": result.get("convergence"),
            "output": str(args.output),
        }, indent=2, sort_keys=True))
        return 0 if result["ok"] else 1
    except Exception as exc:
        result["error"] = str(exc)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1
    finally:
        if not args.no_launch:
            stop_games()


if __name__ == "__main__":
    raise SystemExit(main())
