#!/usr/bin/env python3
"""Drive and inspect the stock equipped-weapon predicate for Bare Hands."""

from __future__ import annotations

import time
from typing import Any

from steam_friend_active_pair import SteamFriendActivePair
from verify_local_multiplayer_sync import (
    VerifyFailure,
    parse_int_text,
    parse_key_values,
)


BARE_HANDS_REFRESH = 0x0065F9A0
LOADOUT_TABLE = 0x0081C264


def _bool_text(value: str | None) -> bool:
    return value in {"1", "true"}


def query_local_weapon_binding(
    pair: SteamFriendActivePair,
    endpoint: str,
) -> dict[str, Any]:
    """Resolve the exact stock pointer tested by progression refresh."""

    values = parse_key_values(
        pair.lua(
            endpoint,
            f"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local player = sd.player.get_state()
local scene = sd.world.get_scene()
local progression = tonumber(player and player.progression_address) or 0
local actor = tonumber(player and player.actor_address) or 0
local loadout_index = progression ~= 0 and
  (sd.debug.read_i32(progression + 0x14) or -1) or -1
local loadout_table_address = sd.debug.resolve_game_address({LOADOUT_TABLE}) or 0
local loadout_base = loadout_table_address ~= 0 and
  (sd.debug.read_ptr(loadout_table_address) or 0) or 0
local loadout_entry = loadout_base ~= 0 and loadout_index >= 0 and
  (loadout_base + loadout_index * 0x64 + 0x1440) or 0
local weapon_owner_link = loadout_entry ~= 0 and
  (sd.debug.read_ptr(loadout_entry) or 0) or 0
local weapon_holder = weapon_owner_link ~= 0 and
  (sd.debug.read_ptr(weapon_owner_link) or 0) or 0
local weapon_slot = weapon_holder ~= 0 and weapon_holder + 4 or 0
local weapon = weapon_slot ~= 0 and (sd.debug.read_ptr(weapon_slot) or 0) or 0
local lane = player and player.attachment_visual_lane or nil
emit("scene", scene and (scene.kind or scene.name) or "")
emit("progression", progression)
emit("actor", actor)
emit("loadout_index", loadout_index)
emit("loadout_table_address", loadout_table_address)
emit("loadout_base", loadout_base)
emit("loadout_entry", loadout_entry)
emit("weapon_owner_link", weapon_owner_link)
emit("weapon_holder", weapon_holder)
emit("weapon_slot", weapon_slot)
emit("weapon", weapon)
emit("lane_holder", lane and lane.holder_address or 0)
emit("lane_object", lane and lane.current_object_address or 0)
emit("lane_type", lane and lane.current_object_type_id or 0)
emit("lane_recipe", lane and lane.current_object_recipe_uid or 0)
""",
            timeout=10.0,
        )
    )
    result = {
        "scene": values.get("scene", ""),
        "progression": parse_int_text(values.get("progression"), 0),
        "actor": parse_int_text(values.get("actor"), 0),
        "loadout_index": parse_int_text(values.get("loadout_index"), -1),
        "loadout_table_address": parse_int_text(
            values.get("loadout_table_address"), 0
        ),
        "loadout_base": parse_int_text(values.get("loadout_base"), 0),
        "loadout_entry": parse_int_text(values.get("loadout_entry"), 0),
        "weapon_owner_link": parse_int_text(
            values.get("weapon_owner_link"), 0
        ),
        "weapon_holder": parse_int_text(values.get("weapon_holder"), 0),
        "weapon_slot": parse_int_text(values.get("weapon_slot"), 0),
        "weapon": parse_int_text(values.get("weapon"), 0),
        "lane_holder": parse_int_text(values.get("lane_holder"), 0),
        "lane_object": parse_int_text(values.get("lane_object"), 0),
        "lane_type": parse_int_text(values.get("lane_type"), 0),
        "lane_recipe": parse_int_text(values.get("lane_recipe"), 0),
    }
    if result["scene"] != "hub":
        raise VerifyFailure(
            f"Bare Hands weapon fixture requires the hub: {result}"
        )
    required = (
        "progression",
        "actor",
        "loadout_table_address",
        "loadout_base",
        "loadout_entry",
        "weapon_owner_link",
        "weapon_holder",
        "weapon_slot",
        "lane_holder",
    )
    if result["loadout_index"] < 0 or any(result[key] == 0 for key in required):
        raise VerifyFailure(f"stock weapon binding is unavailable: {result}")
    if result["weapon"] != result["lane_object"]:
        raise VerifyFailure(
            f"stock weapon predicate and semantic equipment lane disagree: {result}"
        )
    return result


def query_remote_weapon_binding(
    pair: SteamFriendActivePair,
    endpoint: str,
    participant_id: int,
) -> dict[str, Any]:
    values = parse_key_values(
        pair.lua(
            endpoint,
            f"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local target = {participant_id}
local runtime = sd.runtime.get_multiplayer_state()
local participant = nil
for _, candidate in ipairs(runtime and runtime.participants or {{}}) do
  if (candidate.participant_id or 0) == target then
    participant = candidate
    break
  end
end
local equipment = participant and participant.equipment or nil
local weapon = equipment and equipment.weapon or nil
local bot = sd.bots.get_participant_state(target)
local lane = bot and bot.attachment_visual_lane or nil
emit("participant_found", participant ~= nil)
emit("equipment_valid", equipment and equipment.valid or false)
emit("ledger_type", weapon and weapon.type_id or 0)
emit("ledger_recipe", weapon and weapon.recipe_uid or 0)
emit("bot_object", lane and lane.current_object_address or 0)
emit("bot_type", lane and lane.current_object_type_id or 0)
emit("bot_recipe", lane and lane.current_object_recipe_uid or 0)
""",
            timeout=10.0,
        )
    )
    return {
        "participant_found": _bool_text(values.get("participant_found")),
        "equipment_valid": _bool_text(values.get("equipment_valid")),
        "ledger_type": parse_int_text(values.get("ledger_type"), 0),
        "ledger_recipe": parse_int_text(values.get("ledger_recipe"), 0),
        "bot_object": parse_int_text(values.get("bot_object"), 0),
        "bot_type": parse_int_text(values.get("bot_type"), 0),
        "bot_recipe": parse_int_text(values.get("bot_recipe"), 0),
    }


def set_local_weapon_presence(
    pair: SteamFriendActivePair,
    endpoint: str,
    *,
    expected_weapon: int,
    target_weapon: int,
) -> dict[str, Any]:
    """Change the stock loadout weapon pointer and invoke its normal refresh."""

    binding = query_local_weapon_binding(pair, endpoint)
    if binding["weapon"] != expected_weapon:
        raise VerifyFailure(
            "stock weapon changed before the fixture mutation: "
            f"expected={expected_weapon} binding={binding}"
        )
    values = parse_key_values(
        pair.lua(
            endpoint,
            f"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local player = sd.player.get_state()
local progression = tonumber(player and player.progression_address) or 0
local weapon_slot = {binding['weapon_slot']}
local current = weapon_slot ~= 0 and
  (sd.debug.read_ptr(weapon_slot) or 0) or 0
local wrote = current == {expected_weapon} and
  sd.debug.write_ptr(weapon_slot, {target_weapon}) or false
local refresh = sd.debug.resolve_game_address({BARE_HANDS_REFRESH})
local refresh_result = wrote and progression ~= 0 and refresh ~= 0 and
  sd.debug.call_thiscall_ret_u32(refresh, progression) or nil
local refreshed = refresh_result ~= nil
emit("current", current)
emit("wrote", wrote)
emit("refresh", refresh)
emit("refresh_result", refresh_result)
emit("refreshed", refreshed)
emit("after", weapon_slot ~= 0 and
  (sd.debug.read_ptr(weapon_slot) or 0) or 0)
""",
            timeout=10.0,
        )
    )
    mutation = {
        "current": parse_int_text(values.get("current"), 0),
        "wrote": _bool_text(values.get("wrote")),
        "refresh": parse_int_text(values.get("refresh"), 0),
        "refresh_result": parse_int_text(values.get("refresh_result"), 0),
        "refreshed": _bool_text(values.get("refreshed")),
        "after": parse_int_text(values.get("after"), 0),
    }
    if (
        not mutation["wrote"]
        or not mutation["refreshed"]
        or mutation["after"] != target_weapon
    ):
        raise VerifyFailure(f"stock weapon fixture mutation failed: {mutation}")
    return {
        "before": binding,
        "mutation": mutation,
        "after": query_local_weapon_binding(pair, endpoint),
    }


def wait_for_weapon_presence(
    pair: SteamFriendActivePair,
    *,
    owner_endpoint: str,
    observer_endpoint: str,
    owner_participant_id: int,
    expected_present: bool,
    expected_type: int,
    expected_recipe: int,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        try:
            owner = query_local_weapon_binding(pair, owner_endpoint)
            observer = query_remote_weapon_binding(
                pair,
                observer_endpoint,
                owner_participant_id,
            )
            if expected_present:
                ready = (
                    owner["weapon"] != 0
                    and owner["lane_object"] == owner["weapon"]
                    and owner["lane_type"] == expected_type
                    and owner["lane_recipe"] == expected_recipe
                    and observer["participant_found"]
                    and observer["equipment_valid"]
                    and observer["ledger_type"] == expected_type
                    and observer["ledger_recipe"] == expected_recipe
                    and observer["bot_object"] != 0
                    and observer["bot_type"] == expected_type
                    and observer["bot_recipe"] == expected_recipe
                )
            else:
                ready = (
                    owner["weapon"] == 0
                    and owner["lane_object"] == 0
                    and observer["participant_found"]
                    and observer["equipment_valid"]
                    and observer["ledger_type"] == 0
                    and observer["ledger_recipe"] == 0
                    and observer["bot_object"] == 0
                    and observer["bot_type"] == 0
                    and observer["bot_recipe"] == 0
                )
            last = {"owner": owner, "observer": observer}
            if ready:
                return last
        except (KeyError, TypeError, ValueError, VerifyFailure) as exc:
            last = {"error": str(exc), "error_type": type(exc).__name__}
        time.sleep(0.1)
    state = "armed" if expected_present else "unarmed"
    raise VerifyFailure(
        f"timed out waiting for {state} weapon convergence: {last}"
    )
