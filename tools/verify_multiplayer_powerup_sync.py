#!/usr/bin/env python3
"""Verify stock powerup carriers and rewards for both multiplayer owners."""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
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
    place_player,
    start_host_testrun_and_wait_for_clients,
    stop_games,
    wait_for_remote,
)
from verify_multiplayer_all_upgrade_sync import (
    FLAT_BONEYARD,
    enable_quiet_progression_test_mode,
)
from verify_multiplayer_level_up_offer_sync import (
    choose_local_option,
    query_progression_entry,
    wait_for_choice_result,
    wait_for_local_offer,
    wait_for_pair_ready,
    wait_for_waiting_ids,
)


OUTPUT = ROOT / "runtime" / "multiplayer_powerup_sync.json"
POWERUP_TYPE_ID = 0x07F6
BONUS_SKILL = 0
RANDOM_SKILL = 1
DAMAGE_X4 = 2
POWERUP_KINDS = {
    BONUS_SKILL: ("bonus_skill", "BonusSkillPoint"),
    RANDOM_SKILL: ("random_skill", "RandomSkillRank"),
    DAMAGE_X4: ("damage_x4", "DamageX4"),
}
CASE_NAMES = (
    "client_random_skill",
    "host_random_skill",
    "client_damage_x4",
    "host_damage_x4",
    "client_bonus_skill",
    "host_bonus_skill",
)
MASK64 = (1 << 64) - 1
POSITION_TOLERANCE = 0.1
RADIUS_TOLERANCE = 0.25
LIFETIME_TOLERANCE = 12
PHASE_TOLERANCE = 2.0
PARK_DISTANCE = 1200.0
DROP_STEP = 180.0
DROP_BASE_X = 1500.0
DROP_BASE_Y = 800.0


_CAPTURE_HOST_ID_TOKEN = "__SDMOD_HOST_PARTICIPANT_ID__"
_CAPTURE_CLIENT_ID_TOKEN = "__SDMOD_CLIENT_PARTICIPANT_ID__"


CAPTURE_LUA_TEMPLATE = rf"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local function hx(value)
  return string.format("0x%08X", tonumber(value) or 0)
end
local function u8(address)
  return tonumber(sd.debug.read_u8(address)) or 0
end
local function u32(address)
  return tonumber(sd.debug.read_u32(address)) or 0
end
local function f32(address)
  return tonumber(sd.debug.read_float(address)) or 0
end

local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
emit("player.level", player and player.level or 0)
emit("player.x", player and player.x or 0)
emit("player.y", player and player.y or 0)
emit("player.damage_x4_remaining_ticks", player and player.damage_x4_remaining_ticks or 0)
emit("player.transient_status_flags", player and player.transient_status_flags or 0)

local position_x_offset = sd.debug.layout_offset("actor_position_x")
local position_y_offset = sd.debug.layout_offset("actor_position_y")
local radius_offset = sd.debug.layout_offset("actor_collision_radius")
local pending_remove_offset = sd.debug.layout_offset("actor_pending_remove")
local actors = sd.world and sd.world.list_actors and sd.world.list_actors() or {{}}
local actor_count = 0
for _, actor in ipairs(actors) do
  if tonumber(actor.object_type_id) == 0x07F6 then
    local address = tonumber(actor.actor_address) or 0
    if address ~= 0 then
      actor_count = actor_count + 1
      local prefix = "actor." .. tostring(actor_count) .. "."
      emit(prefix .. "address", hx(address))
      emit(prefix .. "kind_id", u8(address + 0x13C))
      emit(prefix .. "pending_remove", u8(address + pending_remove_offset))
      emit(prefix .. "x", f32(address + position_x_offset))
      emit(prefix .. "y", f32(address + position_y_offset))
      emit(prefix .. "radius", f32(address + radius_offset))
      emit(prefix .. "motion", f32(address + 0x150))
      emit(prefix .. "lifetime", u32(address + 0x154))
      emit(prefix .. "progress", f32(address + 0x158))
      emit(prefix .. "value", f32(address + 0x15C))
      emit(prefix .. "auxiliary", f32(address + 0x160))
    end
  end
end
emit("actor.count", actor_count)

local loot = sd.world and sd.world.get_replicated_loot and
  sd.world.get_replicated_loot() or nil
local drop_count = 0
if loot and loot.drops then
  for _, drop in ipairs(loot.drops) do
    if tonumber(drop.native_type_id or drop.object_type_id) == 0x07F6 then
      drop_count = drop_count + 1
      local prefix = "drop." .. tostring(drop_count) .. "."
      emit(prefix .. "network_id", drop.network_drop_id or 0)
      emit(prefix .. "active", drop.active or false)
      emit(prefix .. "kind", drop.kind or "")
      emit(prefix .. "kind_id", drop.kind_id or 0)
      emit(prefix .. "powerup_kind", drop.powerup_kind or "")
      emit(prefix .. "powerup_kind_id", drop.powerup_kind_id or -1)
      emit(prefix .. "x", drop.x or 0)
      emit(prefix .. "y", drop.y or 0)
      emit(prefix .. "radius", drop.radius or 0)
      emit(prefix .. "motion", drop.motion or 0)
      emit(prefix .. "lifetime", drop.lifetime or 0)
      emit(prefix .. "progress", drop.progress or 0)
      emit(prefix .. "value", drop.value or 0)
      emit(prefix .. "auxiliary", drop.auxiliary or 0)
      emit(prefix .. "materialized", drop.materialized or false)
      emit(prefix .. "local_actor_address", hx(drop.local_actor_address or 0))
    end
  end
end
emit("drop.count", drop_count)

local pickup = loot and loot.last_pickup_result or nil
emit("pickup.valid", pickup ~= nil)
emit("pickup.participant_id", pickup and pickup.participant_id or 0)
emit("pickup.network_drop_id", pickup and pickup.network_drop_id or 0)
emit("pickup.request_sequence", pickup and pickup.request_sequence or 0)
emit("pickup.result", pickup and pickup.result or "")
emit("pickup.kind", pickup and pickup.kind or "")
emit("pickup.powerup_kind", pickup and pickup.powerup_kind or "")
emit("pickup.powerup_kind_id", pickup and pickup.powerup_kind_id or -1)
emit("pickup.skill_entry_index", pickup and pickup.powerup_skill_entry_index or -1)
emit("pickup.skill_apply_count", pickup and pickup.powerup_skill_apply_count or 0)
emit("pickup.skill_resulting_active", pickup and pickup.powerup_skill_resulting_active or 0)
emit("pickup.damage_x4_remaining_ticks", pickup and pickup.damage_x4_remaining_ticks or 0)
emit("pickup.spellbook_revision", pickup and pickup.spellbook_revision or 0)
emit("pickup.statbook_revision", pickup and pickup.statbook_revision or 0)

local mp = sd.runtime and sd.runtime.get_multiplayer_state and
  sd.runtime.get_multiplayer_state() or nil
emit("mp.participant_count", mp and mp.participant_count or 0)
if mp and mp.participants then
  for index, participant in ipairs(mp.participants) do
    local prefix = "participant." .. tostring(index) .. "."
    local owned = participant.owned_progression or {{}}
    emit(prefix .. "id", participant.participant_id or 0)
    emit(prefix .. "level", participant.level or 0)
    emit(prefix .. "damage_x4_remaining_ticks", participant.damage_x4_remaining_ticks or 0)
    emit(prefix .. "transient_status_flags", participant.transient_status_flags or 0)
    emit(prefix .. "spellbook_revision", owned.spellbook_revision or 0)
    emit(prefix .. "statbook_revision", owned.statbook_revision or 0)
  end
end

for _, participant_id in ipairs({{{_CAPTURE_HOST_ID_TOKEN}, {_CAPTURE_CLIENT_ID_TOKEN}}}) do
  local bot = sd.bots and sd.bots.get_participant_state and
    sd.bots.get_participant_state(participant_id) or nil
  local prefix = "bot." .. tostring(participant_id) .. "."
  emit(prefix .. "available", bot and bot.available or false)
  emit(prefix .. "replicated_damage_x4_remaining_ticks",
    bot and bot.replicated_damage_x4_remaining_ticks or 0)
  emit(prefix .. "native_damage_x4_remaining_ticks",
    bot and bot.native_damage_x4_remaining_ticks or 0)
  emit(prefix .. "replicated_transient_status_flags",
    bot and bot.replicated_transient_status_flags or 0)
  emit(prefix .. "native_transient_status_flags",
    bot and bot.native_transient_status_flags or 0)
end
"""


BOOK_LUA = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local book = sd.player and sd.player.get_progression_book_state and
  sd.player.get_progression_book_state() or nil
emit("valid", book ~= nil and book.valid or false)
emit("count", book and #(book.entries or {}) or 0)
if book and book.entries then
  for index, entry in ipairs(book.entries) do
    local prefix = "entry." .. tostring(index) .. "."
    emit(prefix .. "entry_index", entry.entry_index or -1)
    emit(prefix .. "active", entry.active or 0)
    emit(prefix .. "visible", entry.visible or 0)
    emit(prefix .. "max_level", entry.statbook_max_level or 0)
  end
end
"""


def capture_lua() -> str:
    return (
        CAPTURE_LUA_TEMPLATE.replace(_CAPTURE_HOST_ID_TOKEN, str(HOST_ID))
        .replace(_CAPTURE_CLIENT_ID_TOKEN, str(CLIENT_ID))
    )


def values(
    pipe_name: str,
    code: str | None = None,
    timeout: float = 8.0,
) -> dict[str, str]:
    if code is None:
        code = capture_lua()
    return parse_key_values(lua(pipe_name, code, timeout=timeout))


def parse_float(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except ValueError:
        return default


def parse_address(value: str | None) -> int:
    return parse_int_text(value, 0)


def capture(pipe_name: str) -> dict[str, str]:
    return values(pipe_name)


def actor_rows(raw: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index in range(1, parse_int_text(raw.get("actor.count"), 0) + 1):
        prefix = f"actor.{index}."
        rows.append({
            "address": parse_address(raw.get(prefix + "address")),
            "kind_id": parse_int_text(raw.get(prefix + "kind_id"), -1),
            "pending_remove": parse_int_text(
                raw.get(prefix + "pending_remove"), 0
            ),
            "x": parse_float(raw.get(prefix + "x")),
            "y": parse_float(raw.get(prefix + "y")),
            "radius": parse_float(raw.get(prefix + "radius")),
            "motion": parse_float(raw.get(prefix + "motion")),
            "lifetime": parse_int_text(raw.get(prefix + "lifetime"), 0),
            "progress": parse_float(raw.get(prefix + "progress")),
            "value": parse_float(raw.get(prefix + "value")),
            "auxiliary": parse_float(raw.get(prefix + "auxiliary")),
        })
    return rows


def drop_rows(raw: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index in range(1, parse_int_text(raw.get("drop.count"), 0) + 1):
        prefix = f"drop.{index}."
        rows.append({
            "network_id": parse_int_text(raw.get(prefix + "network_id"), 0),
            "active": raw.get(prefix + "active") == "true",
            "kind": raw.get(prefix + "kind", ""),
            "powerup_kind": raw.get(prefix + "powerup_kind", ""),
            "powerup_kind_id": parse_int_text(raw.get(prefix + "powerup_kind_id"), -1),
            "x": parse_float(raw.get(prefix + "x")),
            "y": parse_float(raw.get(prefix + "y")),
            "radius": parse_float(raw.get(prefix + "radius")),
            "motion": parse_float(raw.get(prefix + "motion")),
            "lifetime": parse_int_text(raw.get(prefix + "lifetime"), 0),
            "progress": parse_float(raw.get(prefix + "progress")),
            "value": parse_float(raw.get(prefix + "value")),
            "auxiliary": parse_float(raw.get(prefix + "auxiliary")),
            "materialized": raw.get(prefix + "materialized") == "true",
            "local_actor_address": parse_address(
                raw.get(prefix + "local_actor_address")
            ),
        })
    return rows


def participant_row(raw: dict[str, str], participant_id: int) -> dict[str, int] | None:
    for index in range(1, parse_int_text(raw.get("mp.participant_count"), 0) + 1):
        prefix = f"participant.{index}."
        if parse_int_text(raw.get(prefix + "id"), 0) != participant_id:
            continue
        return {
            "level": parse_int_text(raw.get(prefix + "level"), 0),
            "damage_x4_remaining_ticks": parse_int_text(
                raw.get(prefix + "damage_x4_remaining_ticks"), 0
            ),
            "transient_status_flags": parse_int_text(
                raw.get(prefix + "transient_status_flags"), 0
            ),
            "spellbook_revision": parse_int_text(
                raw.get(prefix + "spellbook_revision"), 0
            ),
            "statbook_revision": parse_int_text(
                raw.get(prefix + "statbook_revision"), 0
            ),
        }
    return None


def capture_book(pipe_name: str) -> list[dict[str, int]]:
    raw = values(pipe_name, BOOK_LUA)
    if raw.get("valid") != "true":
        raise VerifyFailure(f"local progression book unavailable on {pipe_name}: {raw}")
    rows: list[dict[str, int]] = []
    for index in range(1, parse_int_text(raw.get("count"), 0) + 1):
        prefix = f"entry.{index}."
        rows.append({
            "entry_index": parse_int_text(raw.get(prefix + "entry_index"), -1),
            "active": parse_int_text(raw.get(prefix + "active"), 0),
            "visible": parse_int_text(raw.get(prefix + "visible"), 0),
            "max_level": parse_int_text(raw.get(prefix + "max_level"), 0),
        })
    return rows


def distance(left: dict[str, Any], x: float, y: float) -> float:
    return math.hypot(float(left["x"]) - x, float(left["y"]) - y)


def spawn_powerup(kind_id: int, x: float, y: float) -> dict[str, str]:
    kind, _ = POWERUP_KINDS[kind_id]
    code = f"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local ok, err = sd.world.spawn_reward({{
  kind="{kind}", amount=1, x={x:.3f}, y={y:.3f}
}})
emit("ok", ok)
emit("error", err or "")
"""
    result = values(HOST_PIPE, code)
    if result.get("ok") != "true":
        raise VerifyFailure(f"spawn_reward({kind}) failed: {result}")
    return result


def park_players(drop_x: float, drop_y: float) -> dict[str, dict[str, str]]:
    result = {
        "host": place_player(
            HOST_PIPE,
            drop_x - PARK_DISTANCE,
            drop_y + PARK_DISTANCE * 0.25,
            0.0,
        ),
        "client": place_player(
            CLIENT_PIPE,
            drop_x - PARK_DISTANCE,
            drop_y - PARK_DISTANCE * 0.25,
            0.0,
        ),
    }
    time.sleep(0.4)
    return result


def wait_for_carrier(
    kind_id: int,
    x: float,
    y: float,
    before_host_addresses: set[int],
    before_drop_ids: set[int],
    timeout: float,
) -> dict[str, Any]:
    _, expected_label = POWERUP_KINDS[kind_id]
    deadline = time.monotonic() + timeout
    last_host: dict[str, str] = {}
    last_client: dict[str, str] = {}
    while time.monotonic() < deadline:
        last_host = capture(HOST_PIPE)
        last_client = capture(CLIENT_PIPE)
        client_drop = next(
            (
                row
                for row in drop_rows(last_client)
                if row["network_id"] not in before_drop_ids
                and row["active"]
                and row["kind"] == "Powerup"
                and row["powerup_kind_id"] == kind_id
                and row["powerup_kind"] == expected_label
                and row["materialized"]
                and row["local_actor_address"] != 0
                and distance(row, x, y) <= POSITION_TOLERANCE
            ),
            None,
        )
        if client_drop is None:
            time.sleep(0.1)
            continue
        client_actor = next(
            (
                row
                for row in actor_rows(last_client)
                if row["address"] == client_drop["local_actor_address"]
            ),
            None,
        )
        host_actor = next(
            (
                row
                for row in actor_rows(last_host)
                if row["address"] not in before_host_addresses
                and row["kind_id"] == kind_id
                and distance(row, x, y) <= POSITION_TOLERANCE
            ),
            None,
        )
        if client_actor is None or host_actor is None:
            time.sleep(0.1)
            continue

        failures: list[str] = []
        if client_actor["kind_id"] != kind_id:
            failures.append("client native kind")
        if distance(client_actor, x, y) > POSITION_TOLERANCE:
            failures.append("client native position")
        if abs(client_actor["radius"] - client_drop["radius"]) > RADIUS_TOLERANCE:
            failures.append("client native radius")
        if abs(client_actor["lifetime"] - client_drop["lifetime"]) > LIFETIME_TOLERANCE:
            failures.append("client native lifetime")
        for field in ("motion", "progress", "value", "auxiliary"):
            if (
                not math.isfinite(float(client_actor[field]))
                or not math.isfinite(float(client_drop[field]))
                or abs(float(client_actor[field]) - float(client_drop[field]))
                > PHASE_TOLERANCE
            ):
                failures.append(f"client native {field}")
        if failures:
            raise VerifyFailure(
                f"powerup carrier fields diverged for {expected_label}: "
                f"failures={failures} drop={client_drop} actor={client_actor}"
            )
        return {
            "network_drop_id": client_drop["network_id"],
            "host_actor": host_actor,
            "client_drop": client_drop,
            "client_actor": client_actor,
            "field_failures": failures,
        }
    raise VerifyFailure(
        f"powerup carrier did not materialize: kind={expected_label} "
        f"host={last_host} client={last_client}"
    )


def create_carrier(
    kind_id: int,
    x: float,
    y: float,
    timeout: float,
) -> dict[str, Any]:
    parking = park_players(x, y)
    host_before = capture(HOST_PIPE)
    client_before = capture(CLIENT_PIPE)
    before_host_addresses = {row["address"] for row in actor_rows(host_before)}
    before_drop_ids = {row["network_id"] for row in drop_rows(client_before)}
    spawn = spawn_powerup(kind_id, x, y)
    carrier = wait_for_carrier(
        kind_id,
        x,
        y,
        before_host_addresses,
        before_drop_ids,
        timeout,
    )
    return {
        "parking": parking,
        "spawn": spawn,
        **carrier,
    }


def move_owner_to_drop(
    owner_id: int,
    x: float,
    y: float,
) -> dict[str, dict[str, str]]:
    owner_pipe = HOST_PIPE if owner_id == HOST_ID else CLIENT_PIPE
    observer_pipe = CLIENT_PIPE if owner_id == HOST_ID else HOST_PIPE
    return {
        "observer": place_player(
            observer_pipe,
            x - PARK_DISTANCE,
            y,
            180.0,
        ),
        "owner": place_player(owner_pipe, x, y, 0.0),
    }


def pickup_snapshot(raw: dict[str, str]) -> dict[str, Any]:
    return {
        "valid": raw.get("pickup.valid") == "true",
        "participant_id": parse_int_text(raw.get("pickup.participant_id"), 0),
        "network_drop_id": parse_int_text(raw.get("pickup.network_drop_id"), 0),
        "request_sequence": parse_int_text(raw.get("pickup.request_sequence"), 0),
        "result": raw.get("pickup.result", ""),
        "kind": raw.get("pickup.kind", ""),
        "powerup_kind": raw.get("pickup.powerup_kind", ""),
        "powerup_kind_id": parse_int_text(raw.get("pickup.powerup_kind_id"), -1),
        "skill_entry_index": parse_int_text(raw.get("pickup.skill_entry_index"), -1),
        "skill_apply_count": parse_int_text(raw.get("pickup.skill_apply_count"), 0),
        "skill_resulting_active": parse_int_text(
            raw.get("pickup.skill_resulting_active"), 0
        ),
        "damage_x4_remaining_ticks": parse_int_text(
            raw.get("pickup.damage_x4_remaining_ticks"), 0
        ),
        "spellbook_revision": parse_int_text(
            raw.get("pickup.spellbook_revision"), 0
        ),
        "statbook_revision": parse_int_text(raw.get("pickup.statbook_revision"), 0),
    }


def wait_for_accepted_pickup(
    owner_id: int,
    kind_id: int,
    network_drop_id: int,
    timeout: float,
) -> dict[str, Any]:
    _, expected_label = POWERUP_KINDS[kind_id]
    deadline = time.monotonic() + timeout
    last_host: dict[str, str] = {}
    last_client: dict[str, str] = {}
    while time.monotonic() < deadline:
        last_host = capture(HOST_PIPE)
        last_client = capture(CLIENT_PIPE)
        host_pickup = pickup_snapshot(last_host)
        client_pickup = pickup_snapshot(last_client)
        if all(
            row["valid"]
            and row["participant_id"] == owner_id
            and row["network_drop_id"] == network_drop_id
            and row["result"] == "Accepted"
            and row["kind"] == "Powerup"
            and row["powerup_kind_id"] == kind_id
            and row["powerup_kind"] == expected_label
            for row in (host_pickup, client_pickup)
        ):
            return {
                "host": host_pickup,
                "client": client_pickup,
                "host_raw": last_host,
                "client_raw": last_client,
            }
        time.sleep(0.1)
    raise VerifyFailure(
        f"accepted powerup pickup did not converge: owner={owner_id} "
        f"kind={expected_label} drop={network_drop_id} "
        f"host={last_host} client={last_client}"
    )


def wait_for_carrier_unregistered(
    carrier: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    network_drop_id = int(carrier["network_drop_id"])
    host_actor_address = int(carrier["host_actor"]["address"])
    client_actor_address = int(carrier["client_actor"]["address"])
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        host = capture(HOST_PIPE)
        client = capture(CLIENT_PIPE)
        host_actor_present = any(
            row["address"] == host_actor_address for row in actor_rows(host)
        )
        client_actor_present = any(
            row["address"] == client_actor_address for row in actor_rows(client)
        )
        host_drop_active = any(
            row["network_id"] == network_drop_id and row["active"]
            for row in drop_rows(host)
        )
        client_drop_active = any(
            row["network_id"] == network_drop_id and row["active"]
            for row in drop_rows(client)
        )
        last = {
            "network_drop_id": network_drop_id,
            "host_actor_address": host_actor_address,
            "client_actor_address": client_actor_address,
            "host_actor_present": host_actor_present,
            "client_actor_present": client_actor_present,
            "host_drop_active": host_drop_active,
            "client_drop_active": client_drop_active,
        }
        if not any(
            (
                host_actor_present,
                client_actor_present,
                host_drop_active,
                client_drop_active,
            )
        ):
            return last
        time.sleep(0.1)
    raise VerifyFailure(f"accepted powerup carrier was not unregistered: {last}")


def wait_for_carrier_retirement_requested(
    carrier: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    network_drop_id = int(carrier["network_drop_id"])
    host_actor_address = int(carrier["host_actor"]["address"])
    client_actor_address = int(carrier["client_actor"]["address"])
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        host = capture(HOST_PIPE)
        client = capture(CLIENT_PIPE)
        host_actor = next(
            (
                row
                for row in actor_rows(host)
                if row["address"] == host_actor_address
            ),
            None,
        )
        client_actor = next(
            (
                row
                for row in actor_rows(client)
                if row["address"] == client_actor_address
            ),
            None,
        )
        host_drop_active = any(
            row["network_id"] == network_drop_id and row["active"]
            for row in drop_rows(host)
        )
        client_drop_active = any(
            row["network_id"] == network_drop_id and row["active"]
            for row in drop_rows(client)
        )
        last = {
            "network_drop_id": network_drop_id,
            "host_actor_address": host_actor_address,
            "client_actor_address": client_actor_address,
            "host_actor_present": host_actor is not None,
            "client_actor_present": client_actor is not None,
            "host_actor_pending_remove": (
                int(host_actor["pending_remove"])
                if host_actor is not None
                else None
            ),
            "client_actor_pending_remove": (
                int(client_actor["pending_remove"])
                if client_actor is not None
                else None
            ),
            "host_drop_active": host_drop_active,
            "client_drop_active": client_drop_active,
        }
        if (
            not host_drop_active
            and not client_drop_active
            and (host_actor is None or host_actor["pending_remove"] != 0)
            and (client_actor is None or client_actor["pending_remove"] != 0)
        ):
            return last
        time.sleep(0.1)
    raise VerifyFailure(
        f"accepted powerup carrier retirement was not requested: {last}"
    )


def owner_context(owner_id: int) -> tuple[str, str, int]:
    if owner_id == HOST_ID:
        return HOST_PIPE, CLIENT_PIPE, CLIENT_ID
    return CLIENT_PIPE, HOST_PIPE, HOST_ID


def wait_for_entry_parity(
    owner_id: int,
    entry_index: int,
    expected_active: int,
    timeout: float,
) -> dict[str, Any]:
    owner_pipe, observer_pipe, _ = owner_context(owner_id)
    deadline = time.monotonic() + timeout
    last_owner: dict[str, Any] = {}
    last_observer: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last_owner = query_progression_entry(
            owner_pipe,
            option_id=entry_index,
        )
        last_observer = query_progression_entry(
            observer_pipe,
            option_id=entry_index,
            participant_id=owner_id,
        )
        if (
            last_owner.get("available")
            and last_observer.get("available")
            and int(last_owner.get("active", -1)) == expected_active
            and int(last_observer.get("active", -1)) == expected_active
        ):
            return {
                "owner_native": last_owner,
                "observer_native": last_observer,
            }
        time.sleep(0.1)
    raise VerifyFailure(
        f"powerup skill entry did not converge: owner={owner_id} "
        f"entry={entry_index} expected={expected_active} "
        f"owner_native={last_owner} observer_native={last_observer}"
    )


def splitmix64(value: int) -> int:
    value &= MASK64
    value ^= value >> 30
    value = (value * 0xBF58476D1CE4E5B9) & MASK64
    value ^= value >> 27
    value = (value * 0x94D049BB133111EB) & MASK64
    value ^= value >> 31
    return value & MASK64


def expected_random_skill_entry(
    network_drop_id: int,
    owner_id: int,
    book: list[dict[str, int]],
) -> dict[str, int]:
    eligible = [
        row
        for row in book
        if 8 <= row["entry_index"] <= 82
        and row["visible"] != 0
        and row["active"] > 0
        and row["max_level"] > row["active"]
    ]
    if not eligible:
        raise VerifyFailure(f"no stock-eligible random-skill entries: {book}")
    mixed = splitmix64(
        network_drop_id ^ ((owner_id + 0x9E3779B97F4A7C15) & MASK64)
    )
    return eligible[mixed % len(eligible)]


def verify_random_skill(
    owner_id: int,
    x: float,
    y: float,
    timeout: float,
) -> dict[str, Any]:
    owner_pipe, observer_pipe, _ = owner_context(owner_id)
    book_before = capture_book(owner_pipe)
    carrier = create_carrier(RANDOM_SKILL, x, y, timeout)
    selected = expected_random_skill_entry(
        carrier["network_drop_id"],
        owner_id,
        book_before,
    )
    owner_before = query_progression_entry(
        owner_pipe,
        option_id=selected["entry_index"],
    )
    observer_before = query_progression_entry(
        observer_pipe,
        option_id=selected["entry_index"],
        participant_id=owner_id,
    )
    movement = move_owner_to_drop(owner_id, x, y)
    accepted = wait_for_accepted_pickup(
        owner_id,
        RANDOM_SKILL,
        carrier["network_drop_id"],
        timeout,
    )
    cleanup = wait_for_carrier_unregistered(carrier, timeout)
    result = accepted["host"]
    expected_active = selected["active"] + 1
    if (
        result["skill_entry_index"] != selected["entry_index"]
        or result["skill_apply_count"] != 1
        or result["skill_resulting_active"] != expected_active
    ):
        raise VerifyFailure(
            f"random-skill authoritative result diverged: selected={selected} "
            f"result={result}"
        )
    parity = wait_for_entry_parity(
        owner_id,
        selected["entry_index"],
        expected_active,
        timeout,
    )
    return {
        "owner_id": owner_id,
        "carrier": carrier,
        "selected_entry": selected,
        "before": {
            "owner_native": owner_before,
            "observer_native": observer_before,
        },
        "movement": movement,
        "accepted": accepted,
        "cleanup": cleanup,
        "parity": parity,
    }


def wait_for_damage_x4_parity(
    owner_id: int,
    result_ticks: int,
    timeout: float,
) -> dict[str, Any]:
    owner_pipe, observer_pipe, _ = owner_context(owner_id)
    deadline = time.monotonic() + timeout
    last_owner: dict[str, str] = {}
    last_observer: dict[str, str] = {}
    bot_prefix = f"bot.{owner_id}."
    while time.monotonic() < deadline:
        last_owner = capture(owner_pipe)
        last_observer = capture(observer_pipe)
        owner_ticks = parse_int_text(
            last_owner.get("player.damage_x4_remaining_ticks"), 0
        )
        observer_participant = participant_row(last_observer, owner_id)
        replicated_ticks = parse_int_text(
            last_observer.get(
                bot_prefix + "replicated_damage_x4_remaining_ticks"
            ),
            0,
        )
        native_ticks = parse_int_text(
            last_observer.get(bot_prefix + "native_damage_x4_remaining_ticks"),
            0,
        )
        owner_flags = parse_int_text(
            last_owner.get("player.transient_status_flags"), 0
        )
        replicated_flags = parse_int_text(
            last_observer.get(
                bot_prefix + "replicated_transient_status_flags"
            ),
            0,
        )
        native_flags = parse_int_text(
            last_observer.get(bot_prefix + "native_transient_status_flags"),
            0,
        )
        if (
            owner_ticks > 0
            and observer_participant is not None
            and observer_participant["damage_x4_remaining_ticks"] > 0
            and replicated_ticks > 0
            and native_ticks > 0
            and 0 <= result_ticks - owner_ticks <= 180
            and abs(owner_ticks - replicated_ticks) <= 30
            and abs(replicated_ticks - native_ticks) <= 8
            and owner_flags & 0x02
            and observer_participant["transient_status_flags"] & 0x02
            and replicated_flags & 0x02
            and native_flags & 0x02
        ):
            return {
                "result_ticks": result_ticks,
                "owner_ticks": owner_ticks,
                "observer_participant": observer_participant,
                "observer_replicated_ticks": replicated_ticks,
                "observer_native_ticks": native_ticks,
                "owner_flags": owner_flags,
                "observer_replicated_flags": replicated_flags,
                "observer_native_flags": native_flags,
            }
        time.sleep(0.1)
    raise VerifyFailure(
        f"DamageX4 status did not converge: owner={owner_id} "
        f"result_ticks={result_ticks} owner={last_owner} observer={last_observer}"
    )


def verify_damage_x4(
    owner_id: int,
    x: float,
    y: float,
    timeout: float,
) -> dict[str, Any]:
    carrier = create_carrier(DAMAGE_X4, x, y, timeout)
    movement = move_owner_to_drop(owner_id, x, y)
    accepted = wait_for_accepted_pickup(
        owner_id,
        DAMAGE_X4,
        carrier["network_drop_id"],
        timeout,
    )
    cleanup = wait_for_carrier_unregistered(carrier, timeout)
    result_ticks = accepted["host"]["damage_x4_remaining_ticks"]
    if result_ticks <= 0:
        raise VerifyFailure(f"DamageX4 result did not carry a duration: {accepted}")
    parity = wait_for_damage_x4_parity(owner_id, result_ticks, timeout)
    return {
        "owner_id": owner_id,
        "carrier": carrier,
        "movement": movement,
        "accepted": accepted,
        "cleanup": cleanup,
        "parity": parity,
    }


def verify_bonus_skill(
    owner_id: int,
    x: float,
    y: float,
    timeout: float,
) -> dict[str, Any]:
    owner_pipe, observer_pipe, _ = owner_context(owner_id)
    owner_before_capture = capture(owner_pipe)
    owner_level = parse_int_text(owner_before_capture.get("player.level"), 0)
    if owner_level <= 0:
        raise VerifyFailure(f"owner level unavailable before bonus skill: {owner_before_capture}")

    carrier = create_carrier(BONUS_SKILL, x, y, timeout)
    movement = move_owner_to_drop(owner_id, x, y)
    accepted = wait_for_accepted_pickup(
        owner_id,
        BONUS_SKILL,
        carrier["network_drop_id"],
        timeout,
    )
    retirement_requested = wait_for_carrier_retirement_requested(carrier, timeout)
    offer = wait_for_local_offer(
        owner_pipe,
        owner_id,
        owner_level,
        timeout,
    )
    waiting = wait_for_waiting_ids(
        {owner_id},
        timeout,
        host_display_text=(
            "Choose your skill upgrade"
            if owner_id == HOST_ID
            else "Waiting on 1 player"
        ),
        client_display_text=(
            "Choose your skill upgrade"
            if owner_id == CLIENT_ID
            else "Waiting on 1 player"
        ),
        require_timed_out=False,
    )
    selected_entry = offer["first_option_id"]
    apply_count = parse_int_text(
        offer["raw"].get("offer.option.1.apply_count"), 1
    )
    owner_entry_before = query_progression_entry(
        owner_pipe,
        option_id=selected_entry,
    )
    observer_entry_before = query_progression_entry(
        observer_pipe,
        option_id=selected_entry,
        participant_id=owner_id,
    )
    choice = choose_local_option(owner_pipe, offer["offer_id"], 1)
    choice_result = wait_for_choice_result(
        offer["offer_id"],
        owner_level,
        timeout,
        target_participant_id=owner_id,
    )
    cleared = wait_for_waiting_ids(
        set(),
        timeout,
        require_timed_out=False,
    )
    cleanup = wait_for_carrier_unregistered(carrier, timeout)
    expected_active = choice_result["resulting_active"]
    if (
        choice_result["result_option_id"] != selected_entry
        or expected_active <= 0
    ):
        raise VerifyFailure(
            f"bonus-skill choice result diverged: offer={offer} result={choice_result}"
        )
    parity = wait_for_entry_parity(
        owner_id,
        selected_entry,
        expected_active,
        timeout,
    )
    return {
        "owner_id": owner_id,
        "carrier": carrier,
        "movement": movement,
        "accepted": accepted,
        "retirement_requested": retirement_requested,
        "cleanup": cleanup,
        "offer": {
            "offer_id": offer["offer_id"],
            "option_ids": offer["option_ids"],
            "selected_entry": selected_entry,
            "apply_count": apply_count,
            "picker_screen": offer["picker_screen"],
        },
        "waiting": {
            "host_text": waiting["host"].get("wait.display_text"),
            "client_text": waiting["client"].get("wait.display_text"),
            "host_waiting_count": parse_int_text(
                waiting["host"].get("wait.waiting_count"), 0
            ),
            "client_waiting_count": parse_int_text(
                waiting["client"].get("wait.waiting_count"), 0
            ),
        },
        "before": {
            "owner_native": owner_entry_before,
            "observer_native": observer_entry_before,
        },
        "choice": choice,
        "choice_result": choice_result,
        "cleared": {
            "host_waiting_count": parse_int_text(
                cleared["host"].get("wait.waiting_count"), 0
            ),
            "client_waiting_count": parse_int_text(
                cleared["client"].get("wait.waiting_count"), 0
            ),
        },
        "parity": parity,
    }


def run_cases(
    timeout: float,
    selected_cases: set[str] | None = None,
) -> dict[str, Any]:
    base_x = DROP_BASE_X
    base_y = DROP_BASE_Y
    cases: dict[str, Any] = {}

    requested = selected_cases or set(CASE_NAMES)
    if "client_random_skill" in requested:
        cases["client_random_skill"] = verify_random_skill(
            CLIENT_ID, base_x, base_y, timeout
        )
    if "host_random_skill" in requested:
        cases["host_random_skill"] = verify_random_skill(
            HOST_ID, base_x, base_y + DROP_STEP, timeout
        )
    if "client_damage_x4" in requested:
        cases["client_damage_x4"] = verify_damage_x4(
            CLIENT_ID, base_x, base_y + DROP_STEP * 2.0, timeout
        )
    if "host_damage_x4" in requested:
        cases["host_damage_x4"] = verify_damage_x4(
            HOST_ID, base_x, base_y + DROP_STEP * 3.0, timeout
        )
    if "client_bonus_skill" in requested:
        cases["client_bonus_skill"] = verify_bonus_skill(
            CLIENT_ID, base_x, base_y + DROP_STEP * 4.0, timeout
        )
    if "host_bonus_skill" in requested:
        cases["host_bonus_skill"] = verify_bonus_skill(
            HOST_ID, base_x, base_y + DROP_STEP * 5.0, timeout
        )

    return cases


def run_verifier(
    timeout: float,
    selected_cases: set[str] | None = None,
) -> dict[str, Any]:
    output: dict[str, Any] = {"ok": False}
    output["launch"] = launch_pair(
        god_mode=True,
        test_survival_boneyard_override=FLAT_BONEYARD,
        test_blank_boneyard=True,
    )
    disable_bots()
    output["hub_ready"] = {
        "host": wait_for_remote(
            HOST_PIPE, CLIENT_ID, CLIENT_NAME, "hub", timeout
        ),
        "client": wait_for_remote(
            CLIENT_PIPE, HOST_ID, HOST_NAME, "hub", timeout
        ),
    }
    output["quiet_mode"] = enable_quiet_progression_test_mode()
    output["run_entry"] = start_host_testrun_and_wait_for_clients(timeout=timeout)
    output["pair_ready"] = wait_for_pair_ready(timeout)
    output["cases"] = run_cases(timeout, selected_cases)

    output["ok"] = True
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--keep-open", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument(
        "--case",
        action="append",
        choices=CASE_NAMES,
        dest="selected_cases",
        help="Run only the named case; may be repeated.",
    )
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    try:
        stop_games()
        result = run_verifier(
            args.timeout,
            set(args.selected_cases) if args.selected_cases else None,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(json.dumps({
            "ok": result["ok"],
            "cases": sorted(result.get("cases", {})),
            "output": str(args.output),
        }, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        result["error"] = str(exc)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1
    finally:
        if not args.keep_open:
            stop_games()


if __name__ == "__main__":
    raise SystemExit(main())
