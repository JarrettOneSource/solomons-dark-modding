#!/usr/bin/env python3
"""Verify typed local inventory/equip audit coverage for a multiplayer pair."""

from __future__ import annotations

import argparse
import json
import time
from typing import Any

from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_PIPE,
    HOST_ID,
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


RUNTIME_OUTPUT = ROOT / "runtime" / "multiplayer_inventory_audit.json"
POTION_TYPE_ID = 0x1B59
HAT_HELPER_TYPE_ID = 0x1B5D
ROBE_HELPER_TYPE_ID = 0x1B5E
STAFF_HELPER_TYPE_ID = 0x1B5C


CAPTURE_LUA = r"""
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end

local function bytes_hex(address, count)
  if address == 0 then return "" end
  local parts = {}
  for offset = 0, count - 1 do
    local value = sd.debug.read_u8(address + offset)
    if value == nil then return "" end
    parts[#parts + 1] = string.format("%02x", value)
  end
  return table.concat(parts)
end

local scene = sd.world and sd.world.get_scene and sd.world.get_scene() or nil
local inventory = sd.player and sd.player.get_inventory_state and sd.player.get_inventory_state() or nil
emit("scene", scene and (scene.name or scene.kind) or "")
emit("inventory.valid", inventory ~= nil and inventory.valid or false)
emit("inventory.scene", inventory and inventory.gameplay_scene_address or 0)
emit("inventory.root", inventory and inventory.item_list_root_address or 0)
emit("inventory.items_address", inventory and inventory.item_array_address or 0)
emit("inventory.raw_item_count", inventory and inventory.raw_item_count or 0)
emit("inventory.item_count", inventory and inventory.item_count or 0)
emit("inventory.enumerated_item_count", inventory and inventory.enumerated_item_count or 0)
emit("inventory.truncated", inventory and inventory.truncated or false)
local items = inventory and inventory.items or {}
local wearable_color_offset = sd.debug.layout_offset("item_wearable_color_state")
emit("item.row_count", #items)
for index, item in ipairs(items) do
  local prefix = "item." .. tostring(index) .. "."
  emit(prefix .. "valid", item.valid or false)
  emit(prefix .. "address", item.item_address or 0)
  emit(prefix .. "type_id", item.type_id or 0)
  emit(prefix .. "recipe_uid", item.recipe_uid or 0)
  emit(prefix .. "slot", item.slot or -1)
  emit(prefix .. "stack_count", item.stack_count or 0)
  local wearable = item.type_id == 0x1B5D or item.type_id == 0x1B5E
  local color_state = wearable and wearable_color_offset ~= nil
    and bytes_hex((item.item_address or 0) + wearable_color_offset, 32) or ""
  emit(prefix .. "color_state_valid", #color_state == 64)
  emit(prefix .. "color_state", color_state)
end
local primary = inventory and inventory.primary_visual_lane or {}
local secondary = inventory and inventory.secondary_visual_lane or {}
local attachment = inventory and inventory.attachment_visual_lane or {}
emit("visual.primary.type_id", primary.current_object_type_id or 0)
emit("visual.primary.recipe_uid", primary.current_object_recipe_uid or 0)
emit("visual.primary.object", primary.current_object_address or 0)
emit("visual.secondary.type_id", secondary.current_object_type_id or 0)
emit("visual.secondary.recipe_uid", secondary.current_object_recipe_uid or 0)
emit("visual.secondary.object", secondary.current_object_address or 0)
emit("visual.attachment.type_id", attachment.current_object_type_id or 0)
emit("visual.attachment.recipe_uid", attachment.current_object_recipe_uid or 0)
emit("visual.attachment.object", attachment.current_object_address or 0)

local book = sd.player and sd.player.get_progression_book_state and sd.player.get_progression_book_state() or nil
emit("book.valid", book ~= nil and book.valid or false)
emit("book.progression", book and book.progression_address or 0)
emit("book.table", book and book.entry_table_address or 0)
emit("book.entry_count", book and book.entry_count or 0)
emit("book.enumerated_entry_count", book and book.enumerated_entry_count or 0)
emit("book.truncated", book and book.truncated or false)
local book_entries = book and book.entries or {}
emit("book.row_count", #book_entries)
for index, entry in ipairs(book_entries) do
  local prefix = "book.entry." .. tostring(index) .. "."
  emit(prefix .. "valid", entry.valid or false)
  emit(prefix .. "entry_index", entry.entry_index or -1)
  emit(prefix .. "internal_id", entry.internal_id or -1)
  emit(prefix .. "active", entry.active or 0)
  emit(prefix .. "visible", entry.visible or 0)
  emit(prefix .. "category", entry.category or 0)
  emit(prefix .. "statbook_max_level", entry.statbook_max_level or -1)
end

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
    emit(prefix .. "connected", participant.transport_connected or false)
    emit(prefix .. "gold", owned.gold or 0)
    emit(prefix .. "gold_revision", owned.gold_revision or 0)
    emit(prefix .. "inventory_revision", owned.inventory_revision or 0)
    emit(prefix .. "spellbook_revision", owned.spellbook_revision or 0)
    emit(prefix .. "statbook_revision", owned.statbook_revision or 0)
    emit(prefix .. "loadout_revision", owned.loadout_revision or 0)
    emit(prefix .. "inventory_host_authoritative", owned.inventory_host_authoritative or false)
    emit(prefix .. "has_inventory_items", owned.inventory_items ~= nil)
    emit(prefix .. "inventory_item_count", owned.inventory_item_count or 0)
    emit(prefix .. "inventory_item_total_count", owned.inventory_item_total_count or 0)
    emit(prefix .. "inventory_truncated", owned.inventory_truncated or false)
    if owned.inventory_items then
      for item_index, item in ipairs(owned.inventory_items) do
        local item_prefix = prefix .. "inventory_item." .. tostring(item_index) .. "."
        emit(item_prefix .. "type_id", item.type_id or 0)
        emit(item_prefix .. "recipe_uid", item.recipe_uid or 0)
        emit(item_prefix .. "slot", item.slot or -1)
        emit(item_prefix .. "stack_count", item.stack_count or 0)
      end
    end
    emit(prefix .. "progression_book_entry_count", owned.progression_book_entry_count or 0)
    emit(prefix .. "progression_book_entry_total_count", owned.progression_book_entry_total_count or 0)
    emit(prefix .. "progression_book_truncated", owned.progression_book_truncated or false)
    local statbook_entries = owned.statbook_entries or {}
    emit(prefix .. "statbook_entry_count", #statbook_entries)
    for entry_index, entry in ipairs(statbook_entries) do
      local entry_prefix = prefix .. "statbook_entry." .. tostring(entry_index) .. "."
      emit(entry_prefix .. "entry_index", entry.entry_index or -1)
      emit(entry_prefix .. "internal_id", entry.internal_id or -1)
      emit(entry_prefix .. "active", entry.active or 0)
      emit(entry_prefix .. "visible", entry.visible or 0)
      emit(entry_prefix .. "category", entry.category or 0)
      emit(entry_prefix .. "statbook_max_level", entry.statbook_max_level or -1)
    end
    local skillbook_entries = owned.skillbook_entries or {}
    emit(prefix .. "skillbook_entry_count", #skillbook_entries)
    emit(prefix .. "skillbook_entry_total_count", owned.skillbook_entry_total_count or 0)
    emit(prefix .. "skillbook_truncated", owned.skillbook_truncated or false)
    local spellbook_entries = owned.spellbook_entries or {}
    emit(prefix .. "spellbook_entry_count", #spellbook_entries)
    emit(prefix .. "spellbook_entry_total_count", owned.spellbook_entry_total_count or 0)
    emit(prefix .. "spellbook_truncated", owned.spellbook_truncated or false)
    emit(prefix .. "has_skillbook_entries", owned.skillbook_entries ~= nil)
    emit(prefix .. "has_spellbook_entries", owned.spellbook_entries ~= nil)
    emit(prefix .. "has_statbook_entries", owned.statbook_entries ~= nil)
    emit(prefix .. "has_ability_loadout", owned.ability_loadout ~= nil)
    local ability = owned.ability_loadout or {}
    emit(prefix .. "ability.primary_entry_index", ability.primary_entry_index or -1)
    emit(prefix .. "ability.primary_combo_entry_index", ability.primary_combo_entry_index or -1)
    local secondaries = ability.secondary_entry_indices or {}
    for slot = 1, 8 do
      emit(
        prefix .. "ability.secondary_entry_index_" .. tostring(slot),
        secondaries[slot] or -1)
    end
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


def bool_text(value: str | None) -> bool:
    return value == "true" or value == "1"


def item_rows(values: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    count = parse_int_text(values.get("item.row_count"), 0)
    for index in range(1, count + 1):
        prefix = f"item.{index}."
        rows.append({
            "index": index,
            "valid": bool_text(values.get(prefix + "valid")),
            "address": parse_int_text(values.get(prefix + "address"), 0),
            "type_id": parse_int_text(values.get(prefix + "type_id"), 0),
            "recipe_uid": parse_int_text(values.get(prefix + "recipe_uid"), 0),
            "slot": parse_int_text(values.get(prefix + "slot"), -1),
            "stack_count": parse_int_text(values.get(prefix + "stack_count"), 0),
            "color_state_valid": bool_text(values.get(prefix + "color_state_valid")),
            "color_state": values.get(prefix + "color_state", ""),
        })
    return rows


def book_rows(values: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    count = parse_int_text(values.get("book.row_count"), 0)
    for index in range(1, count + 1):
        prefix = f"book.entry.{index}."
        rows.append({
            "index": index,
            "valid": bool_text(values.get(prefix + "valid")),
            "entry_index": parse_int_text(values.get(prefix + "entry_index"), -1),
            "internal_id": parse_int_text(values.get(prefix + "internal_id"), -1),
            "active": parse_int_text(values.get(prefix + "active"), 0),
            "visible": parse_int_text(values.get(prefix + "visible"), 0),
            "category": parse_int_text(values.get(prefix + "category"), 0),
            "statbook_max_level": parse_int_text(values.get(prefix + "statbook_max_level"), -1),
        })
    return rows


def participant_rows(values: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    count = parse_int_text(values.get("mp.participant_count"), 0)
    for index in range(1, count + 1):
        prefix = f"participant.{index}."
        inventory_count = parse_int_text(values.get(prefix + "inventory_item_count"), 0)
        inventory_items: list[dict[str, Any]] = []
        for item_index in range(1, inventory_count + 1):
            item_prefix = f"{prefix}inventory_item.{item_index}."
            inventory_items.append({
                "index": item_index,
                "type_id": parse_int_text(values.get(item_prefix + "type_id"), 0),
                "recipe_uid": parse_int_text(values.get(item_prefix + "recipe_uid"), 0),
                "slot": parse_int_text(values.get(item_prefix + "slot"), -1),
                "stack_count": parse_int_text(values.get(item_prefix + "stack_count"), 0),
            })
        statbook_count = parse_int_text(values.get(prefix + "statbook_entry_count"), 0)
        statbook_entries: list[dict[str, Any]] = []
        for entry_index in range(1, statbook_count + 1):
            entry_prefix = f"{prefix}statbook_entry.{entry_index}."
            statbook_entries.append({
                "index": entry_index,
                "entry_index": parse_int_text(values.get(entry_prefix + "entry_index"), -1),
                "internal_id": parse_int_text(values.get(entry_prefix + "internal_id"), -1),
                "active": parse_int_text(values.get(entry_prefix + "active"), 0),
                "visible": parse_int_text(values.get(entry_prefix + "visible"), 0),
                "category": parse_int_text(values.get(entry_prefix + "category"), 0),
                "statbook_max_level": parse_int_text(values.get(entry_prefix + "statbook_max_level"), -1),
            })
        rows.append({
            "index": index,
            "id": parse_int_text(values.get(prefix + "id"), 0),
            "name": values.get(prefix + "name", ""),
            "kind": values.get(prefix + "kind", ""),
            "controller": values.get(prefix + "controller", ""),
            "connected": bool_text(values.get(prefix + "connected")),
            "gold": parse_int_text(values.get(prefix + "gold"), 0),
            "gold_revision": parse_int_text(values.get(prefix + "gold_revision"), 0),
            "inventory_revision": parse_int_text(values.get(prefix + "inventory_revision"), 0),
            "spellbook_revision": parse_int_text(values.get(prefix + "spellbook_revision"), 0),
            "statbook_revision": parse_int_text(values.get(prefix + "statbook_revision"), 0),
            "loadout_revision": parse_int_text(values.get(prefix + "loadout_revision"), 0),
            "inventory_host_authoritative": bool_text(values.get(prefix + "inventory_host_authoritative")),
            "has_inventory_items": bool_text(values.get(prefix + "has_inventory_items")),
            "inventory_item_count": inventory_count,
            "inventory_item_total_count": parse_int_text(values.get(prefix + "inventory_item_total_count"), 0),
            "inventory_truncated": bool_text(values.get(prefix + "inventory_truncated")),
            "inventory_items": inventory_items,
            "progression_book_entry_count": parse_int_text(values.get(prefix + "progression_book_entry_count"), 0),
            "progression_book_entry_total_count": parse_int_text(
                values.get(prefix + "progression_book_entry_total_count"),
                0,
            ),
            "progression_book_truncated": bool_text(values.get(prefix + "progression_book_truncated")),
            "statbook_entry_count": statbook_count,
            "statbook_entries": statbook_entries,
            "skillbook_entry_count": parse_int_text(values.get(prefix + "skillbook_entry_count"), 0),
            "skillbook_entry_total_count": parse_int_text(values.get(prefix + "skillbook_entry_total_count"), 0),
            "skillbook_truncated": bool_text(values.get(prefix + "skillbook_truncated")),
            "spellbook_entry_count": parse_int_text(values.get(prefix + "spellbook_entry_count"), 0),
            "spellbook_entry_total_count": parse_int_text(values.get(prefix + "spellbook_entry_total_count"), 0),
            "spellbook_truncated": bool_text(values.get(prefix + "spellbook_truncated")),
            "has_skillbook_entries": bool_text(values.get(prefix + "has_skillbook_entries")),
            "has_spellbook_entries": bool_text(values.get(prefix + "has_spellbook_entries")),
            "has_statbook_entries": bool_text(values.get(prefix + "has_statbook_entries")),
            "has_ability_loadout": bool_text(values.get(prefix + "has_ability_loadout")),
            "ability_loadout": {
                "primary_entry_index": parse_int_text(values.get(prefix + "ability.primary_entry_index"), -1),
                "primary_combo_entry_index": parse_int_text(
                    values.get(prefix + "ability.primary_combo_entry_index"),
                    -1,
                ),
                "secondary_entry_indices": [
                    parse_int_text(
                        values.get(
                            prefix + f"ability.secondary_entry_index_{slot}"
                        ),
                        -1,
                    )
                    for slot in range(1, 9)
                ],
            },
        })
    return rows


def find_participant(values: dict[str, str], participant_id: int) -> dict[str, Any] | None:
    for row in participant_rows(values):
        if row["id"] == participant_id:
            return row
    return None


def assert_owned_inventory_rows(label: str, row: dict[str, Any]) -> None:
    if row["inventory_truncated"]:
        raise VerifyFailure(f"{label} owned inventory unexpectedly truncated: {row}")
    if row["inventory_item_total_count"] < 2 or row["inventory_item_count"] < 2:
        raise VerifyFailure(f"{label} owned inventory missing starter rows: {row}")
    potion_slots = {
        item["slot"]: item
        for item in row["inventory_items"]
        if item["type_id"] == POTION_TYPE_ID and item["stack_count"] >= 1
    }
    missing_slots = [slot for slot in (0, 1) if slot not in potion_slots]
    if missing_slots:
        raise VerifyFailure(f"{label} owned inventory missing potion slots {missing_slots}: {row}")


def assert_owned_progression_rows(label: str, row: dict[str, Any]) -> None:
    if row["progression_book_entry_total_count"] <= 0 or row["statbook_entry_count"] <= 0:
        raise VerifyFailure(f"{label} owned progression book missing rows: {row}")
    if row["progression_book_truncated"] or row["skillbook_truncated"] or row["spellbook_truncated"]:
        raise VerifyFailure(f"{label} owned progression book unexpectedly truncated: {row}")
    if row["progression_book_entry_total_count"] != row["statbook_entry_count"]:
        raise VerifyFailure(f"{label} owned progression book count mismatch: {row}")
    if row["skillbook_entry_total_count"] != row["progression_book_entry_total_count"]:
        raise VerifyFailure(f"{label} owned skillbook total mismatch: {row}")
    if row["skillbook_entry_count"] != row["progression_book_entry_count"]:
        raise VerifyFailure(f"{label} owned skillbook row mismatch: {row}")
    if row["spellbook_entry_total_count"] != row["progression_book_entry_total_count"]:
        raise VerifyFailure(f"{label} owned spellbook total mismatch: {row}")
    if row["spellbook_entry_count"] != row["progression_book_entry_count"]:
        raise VerifyFailure(f"{label} owned spellbook row mismatch: {row}")
    if not row["has_statbook_entries"]:
        raise VerifyFailure(f"{label} owned progression does not expose statbook_entries: {row}")
    if not row["has_skillbook_entries"]:
        raise VerifyFailure(f"{label} owned progression does not expose skillbook_entries: {row}")
    if not row["has_spellbook_entries"]:
        raise VerifyFailure(f"{label} owned progression does not expose spellbook_entries: {row}")
    if row["spellbook_revision"] != row["statbook_revision"]:
        raise VerifyFailure(f"{label} skill/stat book revisions diverged: {row}")
    if not row["has_ability_loadout"]:
        raise VerifyFailure(f"{label} owned progression missing ability_loadout: {row}")
    ability = row["ability_loadout"]
    if ability["primary_entry_index"] < 0 or ability["primary_combo_entry_index"] < 0:
        raise VerifyFailure(f"{label} ability loadout did not replicate primary entries: {row}")


def assert_progression_book_shape(label: str, values: dict[str, str]) -> dict[str, Any]:
    if not bool_text(values.get("book.valid")):
        raise VerifyFailure(f"{label} progression book API returned invalid: {values}")

    entry_count = parse_int_text(values.get("book.entry_count"), 0)
    enumerated_count = parse_int_text(values.get("book.enumerated_entry_count"), 0)
    rows = book_rows(values)
    if entry_count <= 0 or len(rows) <= 0:
        raise VerifyFailure(f"{label} progression book did not expose native rows: {rows}")
    if bool_text(values.get("book.truncated")):
        if entry_count <= enumerated_count:
            raise VerifyFailure(f"{label} progression book has inconsistent truncation metadata: {values}")
    elif entry_count != enumerated_count:
        raise VerifyFailure(f"{label} progression book count mismatch: {values}")
    indexed_rows = [row for row in rows if row["valid"] and row["entry_index"] >= 0]
    if not indexed_rows:
        raise VerifyFailure(f"{label} progression book rows had no valid entry indices: {rows}")
    return {
        "entry_count": entry_count,
        "enumerated_entry_count": enumerated_count,
        "truncated": bool_text(values.get("book.truncated")),
        "entries": rows,
    }


def assert_inventory_shape(label: str, values: dict[str, str]) -> dict[str, Any]:
    if values.get("scene") != "hub":
        raise VerifyFailure(f"{label} is not in hub: {values.get('scene')}")
    if not bool_text(values.get("inventory.valid")):
        raise VerifyFailure(f"{label} inventory API returned invalid: {values}")
    if bool_text(values.get("inventory.truncated")):
        raise VerifyFailure(f"{label} inventory audit unexpectedly truncated: {values}")

    item_count = parse_int_text(values.get("inventory.item_count"), 0)
    rows = item_rows(values)
    if item_count < 2 or len(rows) < 2:
        raise VerifyFailure(f"{label} inventory did not expose starter item rows: {rows}")

    potion_slots = {
        row["slot"]: row
        for row in rows
        if row["valid"] and row["type_id"] == POTION_TYPE_ID and row["stack_count"] >= 1
    }
    missing_slots = [slot for slot in (0, 1) if slot not in potion_slots]
    if missing_slots:
        raise VerifyFailure(f"{label} missing starter potion slots {missing_slots}: {rows}")

    primary_type = parse_int_text(values.get("visual.primary.type_id"), 0)
    secondary_type = parse_int_text(values.get("visual.secondary.type_id"), 0)
    attachment_type = parse_int_text(values.get("visual.attachment.type_id"), 0)
    expected_visuals = {
        "primary": HAT_HELPER_TYPE_ID,
        "secondary": ROBE_HELPER_TYPE_ID,
        "attachment": STAFF_HELPER_TYPE_ID,
    }
    actual_visuals = {
        "primary": primary_type,
        "secondary": secondary_type,
        "attachment": attachment_type,
    }
    for lane, expected in expected_visuals.items():
        actual = actual_visuals[lane]
        if actual != expected:
            raise VerifyFailure(
                f"{label} {lane} visual lane type mismatch: "
                f"expected=0x{expected:X} actual=0x{actual:X}"
            )

    return {
        "raw_item_count": parse_int_text(values.get("inventory.raw_item_count"), 0),
        "item_count": item_count,
        "enumerated_item_count": parse_int_text(values.get("inventory.enumerated_item_count"), 0),
        "items": rows,
        "potion_slots": potion_slots,
        "visuals": actual_visuals,
        "progression_book": assert_progression_book_shape(label, values),
    }


def assert_multiplayer_boundary(host: dict[str, str], client: dict[str, str]) -> dict[str, Any]:
    host_view_client = find_participant(host, CLIENT_ID)
    client_view_host = find_participant(client, HOST_ID)
    if host_view_client is None or client_view_host is None:
        raise VerifyFailure(
            "participant ledgers did not expose both peers: "
            f"host={participant_rows(host)} client={participant_rows(client)}"
        )

    rows = {
        "host_view_client": host_view_client,
        "client_view_host": client_view_host,
    }
    for label, row in rows.items():
        assert_owned_inventory_rows(label, row)
        assert_owned_progression_rows(label, row)
        if not row["has_inventory_items"]:
            raise VerifyFailure(f"{label} has wrong owned-content exposure boundary: {row}")
    return rows


def wait_for_pair_inventory(timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last = capture_pair()
    last_failure = ""
    while time.monotonic() < deadline:
        last = capture_pair()
        try:
            host_inventory = assert_inventory_shape("host", last["host"])
            client_inventory = assert_inventory_shape("client", last["client"])
            boundary = assert_multiplayer_boundary(last["host"], last["client"])
            return {
                "host": host_inventory,
                "client": client_inventory,
                "multiplayer_boundary": boundary,
                "raw": last,
            }
        except VerifyFailure as exc:
            last_failure = str(exc)
            time.sleep(0.2)
    raise VerifyFailure(
        f"inventory audit did not settle before timeout: last_failure={last_failure} last={last}"
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": False}
    if not args.no_launch:
        stop_games()
        result["launch"] = launch_pair()
        disable_bots()
        wait_for_both_hub_settled()
    result["inventory_audit"] = wait_for_pair_inventory(args.timeout)
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
            "host_items": result["inventory_audit"]["host"]["items"],
            "client_items": result["inventory_audit"]["client"]["items"],
            "boundary": result["inventory_audit"]["multiplayer_boundary"],
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
