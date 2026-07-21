#!/usr/bin/env python3
"""Exact native Webbed-state observations for multiplayer regressions."""

from __future__ import annotations

import math
import time
from typing import Any

from verify_local_multiplayer_sync import (
    VerifyFailure,
    lua,
    parse_int_text,
    parse_key_values,
)


MOD_WEBBED_TYPE_ID = 0x1B79
ACTOR_MOD_LIST_COUNT_OFFSET = 0x10C
ACTOR_MOD_LIST_STORAGE_OFFSET = 0x118
MOD_TYPE_ID_OFFSET = 0x08
MOD_DURATION_OFFSET = 0x14
MOD_WEBBED_STRENGTH_OFFSET = 0x1C
MOD_WEBBED_REQUESTED_STRENGTH_OFFSET = 0x20
WEBBED_RENDER_DRIVE_FLAG = 0x20

TRANSIENT_WEBBED = 1 << 4  # ParticipantTransientStatusFlagWebbed
TRANSIENT_SNAPSHOT_VALID = 1 << 7
WEBBED_CLEAR_STABLE_SECONDS = 0.75


def _values(pipe_name: str, code: str, timeout: float = 10.0) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, code, timeout=timeout))


def _float(values: dict[str, str], key: str) -> float:
    try:
        return float(values.get(key, "nan"))
    except ValueError:
        return math.nan


def query_webbed_status(
    pipe_name: str,
    *,
    participant_id: int | None = None,
) -> dict[str, Any]:
    participant_selector = "nil" if participant_id is None else str(participant_id)
    code = f"""
local function emit(key, value)
  if value == nil then value = '<nil>' end
  print(key .. '=' .. tostring(value))
end
local requested = {participant_selector}
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
local bot = requested ~= nil and sd.bots and sd.bots.get_participant_state and
  sd.bots.get_participant_state(requested) or nil
local actor = requested == nil and tonumber(player and player.actor_address) or
  tonumber(bot and bot.actor_address)
actor = actor or 0
local mp = sd.runtime and sd.runtime.get_multiplayer_state and
  sd.runtime.get_multiplayer_state() or nil
local runtime = nil
if mp and mp.participants then
  for _, participant in ipairs(mp.participants) do
    if (requested == nil and participant.is_owner) or
       (requested ~= nil and tonumber(participant.participant_id) == requested) then
      runtime = participant
      break
    end
  end
end

local count = actor ~= 0 and
  (tonumber(sd.debug.read_i32(actor + 0x{ACTOR_MOD_LIST_COUNT_OFFSET:X})) or 0) or 0
local storage = actor ~= 0 and
  (tonumber(sd.debug.read_ptr(actor + 0x{ACTOR_MOD_LIST_STORAGE_OFFSET:X})) or 0) or 0
local webbed_count = 0
local webbed = 0
local control = 0
if count > 0 and count < 512 and storage ~= 0 then
  for index = 0, count - 1 do
    local candidate_control = tonumber(sd.debug.read_ptr(storage + index * 4)) or 0
    local candidate = candidate_control ~= 0 and
      (tonumber(sd.debug.read_ptr(candidate_control)) or 0) or 0
    local type_id = candidate ~= 0 and
      (tonumber(sd.debug.read_u32(candidate + 0x{MOD_TYPE_ID_OFFSET:X})) or 0) or 0
    if type_id == 0x{MOD_WEBBED_TYPE_ID:X} then
      webbed_count = webbed_count + 1
      if webbed == 0 then
        webbed = candidate
        control = candidate_control
      end
    end
  end
end

local render_offset = sd.debug.layout_offset('actor_render_drive_flags')
local actor_render_drive_flags = actor ~= 0 and render_offset ~= nil and
  (tonumber(sd.debug.read_u32(actor + render_offset)) or 0) or 0
local local_flags = player and tonumber(player.transient_status_flags) or 0
local local_ticks = player and tonumber(player.webbed_remaining_ticks) or 0
local local_strength = player and tonumber(player.webbed_strength) or 0
emit('actor', actor)
emit('local_flags', requested == nil and local_flags or 0)
emit('local_ticks', requested == nil and local_ticks or 0)
emit('local_strength', requested == nil and local_strength or 0)
emit('local_movement_x', requested == nil and
  tonumber(player and player.movement_intent_x) or 0)
emit('local_movement_y', requested == nil and
  tonumber(player and player.movement_intent_y) or 0)
emit('runtime_flags', runtime and runtime.transient_status_flags or 0)
emit('runtime_movement_x', runtime and runtime.movement_intent_x or 0)
emit('runtime_movement_y', runtime and runtime.movement_intent_y or 0)
emit('replicated_flags', bot and bot.replicated_transient_status_flags or local_flags)
emit('native_flags', bot and bot.native_transient_status_flags or local_flags)
emit('native_ticks', bot and bot.native_webbed_remaining_ticks or local_ticks)
emit('native_strength', bot and bot.native_webbed_strength or local_strength)
emit('actor_render_drive_flags', actor_render_drive_flags)
emit('modifier_list_count', count)
emit('webbed_count', webbed_count)
emit('webbed', webbed)
emit('control', control)
emit('control_refs', control ~= 0 and sd.debug.read_i32(control + 4) or -1)
emit('modifier_ticks', webbed ~= 0 and
  sd.debug.read_i32(webbed + 0x{MOD_DURATION_OFFSET:X}) or 0)
emit('modifier_strength', webbed ~= 0 and
  sd.debug.read_float(webbed + 0x{MOD_WEBBED_STRENGTH_OFFSET:X}) or 0)
emit('requested_strength', webbed ~= 0 and
  sd.debug.read_float(webbed + 0x{MOD_WEBBED_REQUESTED_STRENGTH_OFFSET:X}) or 0)
emit('ok', actor ~= 0 and runtime ~= nil)
"""
    raw = _values(pipe_name, code)
    if raw.get("ok") != "true":
        raise VerifyFailure(
            f"Webbed status unavailable pipe={pipe_name} "
            f"participant={participant_id}: {raw}"
        )
    return {
        "participant_id": participant_id,
        "actor_address": parse_int_text(raw.get("actor"), 0),
        "local_flags": parse_int_text(raw.get("local_flags"), 0),
        "local_ticks": parse_int_text(raw.get("local_ticks"), 0),
        "local_strength": _float(raw, "local_strength"),
        "local_movement_x": _float(raw, "local_movement_x"),
        "local_movement_y": _float(raw, "local_movement_y"),
        "runtime_flags": parse_int_text(raw.get("runtime_flags"), 0),
        "runtime_movement_x": _float(raw, "runtime_movement_x"),
        "runtime_movement_y": _float(raw, "runtime_movement_y"),
        "replicated_flags": parse_int_text(raw.get("replicated_flags"), 0),
        "native_flags": parse_int_text(raw.get("native_flags"), 0),
        "native_ticks": parse_int_text(raw.get("native_ticks"), 0),
        "native_strength": _float(raw, "native_strength"),
        "actor_render_drive_flags": parse_int_text(
            raw.get("actor_render_drive_flags"), 0
        ),
        "modifier_list_count": parse_int_text(
            raw.get("modifier_list_count"), 0
        ),
        "webbed_count": parse_int_text(raw.get("webbed_count"), 0),
        "modifier_address": parse_int_text(raw.get("webbed"), 0),
        "control_block_address": parse_int_text(raw.get("control"), 0),
        "control_refs": parse_int_text(raw.get("control_refs"), -1),
        "modifier_ticks": parse_int_text(raw.get("modifier_ticks"), 0),
        "modifier_strength": _float(raw, "modifier_strength"),
        "requested_strength": _float(raw, "requested_strength"),
        "raw": raw,
    }


def wait_for_owner_webbed(pipe_name: str, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = query_webbed_status(pipe_name)
        if (
            last["runtime_flags"] & TRANSIENT_SNAPSHOT_VALID
            and last["runtime_flags"] & TRANSIENT_WEBBED
            and last["native_flags"] & TRANSIENT_WEBBED
            and last["webbed_count"] == 1
            and last["modifier_ticks"] > 0
            and math.isfinite(last["modifier_strength"])
            and last["modifier_strength"] > 0.0
        ):
            return last
        time.sleep(0.05)
    raise VerifyFailure(f"local owner did not receive native Webbed: {last}")


def wait_for_host_webbed_before_client_owner(
    host_pipe_name: str,
    client_pipe_name: str,
    participant_id: int,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_host: dict[str, Any] = {}
    last_client: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last_host = query_webbed_status(
            host_pipe_name,
            participant_id=participant_id,
        )
        if (
            last_host["native_flags"] & TRANSIENT_WEBBED
            and last_host["webbed_count"] == 1
            and last_host["modifier_ticks"] > 0
            and math.isfinite(last_host["modifier_strength"])
            and last_host["modifier_strength"] > 0.0
        ):
            return last_host

        last_client = query_webbed_status(client_pipe_name)
        if (
            last_client["native_flags"] & TRANSIENT_WEBBED
            or last_client["webbed_count"] != 0
        ):
            raise VerifyFailure(
                "client Spider replica authored Webbed before the host mirror: "
                f"host={last_host} client={last_client}"
            )
        time.sleep(0.05)

    raise VerifyFailure(
        "host mirror did not author client Webbed before timeout: "
        f"host={last_host} client={last_client}"
    )


def wait_for_observer_webbed(
    pipe_name: str,
    participant_id: int,
    *,
    require_native_modifier: bool,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = query_webbed_status(pipe_name, participant_id=participant_id)
        protocol_active = (
            last["runtime_flags"] & TRANSIENT_SNAPSHOT_VALID
            and last["runtime_flags"] & TRANSIENT_WEBBED
            and last["replicated_flags"] & TRANSIENT_WEBBED
        )
        presentation_active = (
            last["actor_render_drive_flags"] & WEBBED_RENDER_DRIVE_FLAG
        ) != 0
        native_matches = (
            last["webbed_count"] == 1
            and last["native_flags"] & TRANSIENT_WEBBED
            and last["modifier_ticks"] > 0
            and last["modifier_strength"] > 0.0
            if require_native_modifier
            else last["webbed_count"] == 0
            and not (last["native_flags"] & TRANSIENT_WEBBED)
        )
        if protocol_active and presentation_active and native_matches:
            return last
        time.sleep(0.05)
    raise VerifyFailure(
        "remote Webbed presentation did not converge: "
        f"participant={participant_id} native={require_native_modifier} last={last}"
    )


def start_stock_web_escape(pipe_name: str) -> dict[str, str]:
    code = """
local function emit(key, value) print(key .. '=' .. tostring(value)) end
_G.__sdmod_webbed_escape_active = true
if not _G.__sdmod_webbed_escape_registered then
  sd.events.on('runtime.tick', function()
    if not _G.__sdmod_webbed_escape_active then return end
    if sd.input and sd.input.hold_movement_frames then
      pcall(sd.input.hold_movement_frames, 1.0, 0.0, 1)
    end
  end)
  _G.__sdmod_webbed_escape_registered = true
end
emit('ok', true)
emit('registered', _G.__sdmod_webbed_escape_registered)
"""
    result = _values(pipe_name, code)
    if result.get("ok") != "true":
        raise VerifyFailure(f"failed to start stock Webbed escape: {result}")
    return result


def stop_stock_web_escape(pipe_name: str) -> dict[str, str]:
    result = _values(
        pipe_name,
        "_G.__sdmod_webbed_escape_active = false; print('ok=true')",
    )
    if result.get("ok") != "true":
        raise VerifyFailure(f"failed to stop stock Webbed escape: {result}")
    return result


def wait_for_webbed_clear(
    pipe_name: str,
    *,
    participant_id: int | None,
    timeout: float,
    stable_seconds: float = WEBBED_CLEAR_STABLE_SECONDS,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    stable_since: float | None = None
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = query_webbed_status(pipe_name, participant_id=participant_id)
        clear = (
            last["runtime_flags"] & TRANSIENT_SNAPSHOT_VALID
            and not (last["runtime_flags"] & TRANSIENT_WEBBED)
            and not (last["native_flags"] & TRANSIENT_WEBBED)
            and last["webbed_count"] == 0
            and not (
                last["actor_render_drive_flags"] & WEBBED_RENDER_DRIVE_FLAG
            )
        )
        if clear:
            if stable_since is None:
                stable_since = time.monotonic()
            if time.monotonic() - stable_since >= stable_seconds:
                return last
        else:
            stable_since = None
        time.sleep(0.05)
    raise VerifyFailure(
        f"Webbed state did not clear pipe={pipe_name} "
        f"participant={participant_id}: {last}"
    )
