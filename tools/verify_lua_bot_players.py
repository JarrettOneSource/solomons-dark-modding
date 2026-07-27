#!/usr/bin/env python3
"""Live acceptance for host-owned synthetic multiplayer participants."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import multiplayer_frame_capture
import verify_local_multiplayer_sync as local_sync


ROOT = Path(__file__).resolve().parents[1]
GAME_DIRECTORY = Path(
    "/mnt/c/Users/User/Documents/GitHub/SB Modding/"
    "Solomon Dark/SolomonDarkAbandonware"
)
EVIDENCE_ROOT = Path(
    "/mnt/d/codex-evidence/bot-players-20260726"
)
INSTANCE_PREFIX = "bot"
HOST_PORT = 48811
CLIENT_PORT = 48812
HOST_PIPE = "SolomonDarkModLoader_LuaExec_bot-host"
CLIENT_PIPE = "SolomonDarkModLoader_LuaExec_bot-client"
BOT_NAME = "Ember"
BOT_CLASS = "fire"
EXACT_MOD_ID = "sample.lua.ui_sandbox_lab"
SKELETON_TYPE_ID = 1001
FIREBALL_TYPE_ID = 0x7D4
DEATH_PRESENTATION_FLAG = 1 << 6
TERMINAL_CORPSE_TICK = 159


class BotAcceptanceFailure(RuntimeError):
    pass


def _number(values: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        return float(values.get(key, str(default)))
    except (TypeError, ValueError):
        return default


def _integer(values: dict[str, str], key: str, default: int = 0) -> int:
    return int(_number(values, key, float(default)))


def _bot_probe(participant_id: int) -> str:
    return f"""
local participant_id = {participant_id}
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local scene = sd.world.get_scene()
emit("scene", scene and (scene.name or scene.kind) or "")
local bot = sd.bots.get_participant_state(participant_id)
emit("bot.available", bot ~= nil and bot.available)
emit("bot.id", bot and bot.id or 0)
emit("bot.name", bot and bot.name or "")
emit("bot.kind", bot and bot.participant_kind or "")
emit("bot.controller", bot and bot.controller_kind or "")
emit("bot.materialized", bot ~= nil and bot.entity_materialized)
emit("bot.transform", bot ~= nil and bot.transform_valid)
emit("bot.actor", bot and bot.actor_address or 0)
emit("bot.slot", bot and bot.gameplay_slot or -1)
emit("bot.x", bot and bot.x or 0)
emit("bot.y", bot and bot.y or 0)
emit("bot.hp", bot and bot.hp or 0)
emit("bot.max_hp", bot and bot.max_hp or 0)
local nameplate = bot and bot.actor_address and
  sd.bots.get_nameplate(bot.actor_address) or nil
emit("bot.nameplate", nameplate and nameplate.name or "")

local remote_count = 0
local materialized_count = 0
local slot_mask = 0
for _, candidate in ipairs(sd.bots.get_participants() or {{}}) do
  remote_count = remote_count + 1
  if candidate.entity_materialized then
    materialized_count = materialized_count + 1
  end
  local slot = tonumber(candidate.gameplay_slot) or -1
  if slot >= 1 and slot <= 3 then
    slot_mask = slot_mask + 2 ^ slot
  end
end
emit("remote.count", remote_count)
emit("remote.materialized_count", materialized_count)
emit("remote.slot_mask", slot_mask)

local state = sd.runtime.get_multiplayer_state()
local member = nil
for _, candidate in ipairs(state and state.participants or {{}}) do
  if tonumber(candidate.participant_id) == participant_id then
    member = candidate
    break
  end
end
emit("member.found", member ~= nil)
emit("member.name", member and member.name or "")
emit("member.kind", member and member.participant_kind or "")
emit("member.controller", member and member.controller_kind or "")
emit("member.ready", member ~= nil and member.ready)
emit("member.connected", member ~= nil and member.transport_connected)
emit("member.runtime_valid", member ~= nil and member.runtime_valid)
emit("member.in_run", member ~= nil and member.in_run)
emit("member.run_nonce", member and member.run_nonce or 0)
"""


def _enemy_target_probe(participant_id: int) -> str:
    return f"""
local participant_id = {participant_id}
local snapshot = sd.world.get_replicated_actors()
local live = 0
local targeted = 0
local first_id = 0
for _, actor in ipairs(snapshot and snapshot.actors or {{}}) do
  if not actor.dead and (tonumber(actor.hp) or 0) > 0.05 then
    live = live + 1
    if tonumber(actor.target_participant_id) == participant_id then
      targeted = targeted + 1
      if first_id == 0 then
        first_id = tonumber(actor.network_actor_id) or 0
      end
    end
  end
end
print("authority=" .. tostring(sd.state.is_authority()))
print("live=" .. tostring(live))
print("targeted=" .. tostring(targeted))
print("first_id=" .. tostring(first_id))
"""


def _wait(
    probe,
    predicate,
    *,
    timeout: float,
    label: str,
    interval: float = 0.25,
):
    deadline = time.monotonic() + timeout
    last: Any = None
    last_error = ""
    while time.monotonic() < deadline:
        try:
            last = probe()
            last_error = ""
            if predicate(last):
                return last
        except (
            BotAcceptanceFailure,
            local_sync.VerifyFailure,
            TimeoutError,
        ) as exc:
            last_error = str(exc)
        time.sleep(interval)
    detail = f" last={last!r}"
    if last_error:
        detail += f" error={last_error}"
    raise BotAcceptanceFailure(f"{label} timed out.{detail}")


def _query_bot(pipe_name: str, participant_id: int) -> dict[str, str]:
    return local_sync.parse_key_values(
        local_sync.lua(
            pipe_name,
            _bot_probe(participant_id),
            timeout=7.5,
        )
    )


def _bot_is_materialized(values: dict[str, str], scene: str) -> bool:
    slot = _integer(values, "bot.slot", -1)
    return (
        values.get("scene") == scene
        and values.get("bot.available") == "true"
        and values.get("bot.name") == BOT_NAME
        and values.get("bot.kind") == "RemoteParticipant"
        and values.get("bot.controller") == "LuaBrain"
        and values.get("bot.materialized") == "true"
        and values.get("bot.transform") == "true"
        and _integer(values, "bot.actor") > 0
        and 1 <= slot <= 3
        and values.get("bot.nameplate") == BOT_NAME
        and _number(values, "bot.hp") > 0.0
        and _number(values, "bot.max_hp") > 0.0
        and _integer(values, "remote.count") == 2
        and _integer(values, "remote.materialized_count") == 2
        and values.get("member.found") == "true"
        and values.get("member.name") == BOT_NAME
        and values.get("member.controller") == "LuaBrain"
        and values.get("member.ready") == "true"
        and values.get("member.connected") == "true"
        and values.get("member.runtime_valid") == "true"
    )


def _start_testrun() -> None:
    last_error = ""
    for _ in range(60):
        try:
            local_sync.start_testrun(HOST_PIPE)
            return
        except local_sync.VerifyFailure as exc:
            last_error = str(exc)
            if "still settling" not in last_error:
                raise
            time.sleep(0.25)
    raise BotAcceptanceFailure(
        f"host could not enter the test run: {last_error}"
    )


def _wait_for_enemy_target(
    pipe_name: str,
    participant_id: int,
    *,
    expected_authority: bool,
    timeout: float = 25.0,
) -> dict[str, str]:
    expected = "true" if expected_authority else "false"
    return _wait(
        lambda: local_sync.parse_key_values(
            local_sync.lua(
                pipe_name,
                _enemy_target_probe(participant_id),
                timeout=7.5,
            )
        ),
        lambda values: (
            values.get("authority") == expected
            and _integer(values, "live") > 0
            and _integer(values, "targeted") > 0
            and _integer(values, "first_id") > 0
        ),
        timeout=timeout,
        label=f"native enemy targeting on {pipe_name}",
    )


def _wait_for_target_identity(
    pipe_name: str,
    participant_id: int,
    network_actor_id: int,
    *,
    timeout: float = 10.0,
) -> dict[str, str]:
    code = f"""
local participant_id = {participant_id}
local network_actor_id = {network_actor_id}
local snapshot = sd.world.get_replicated_actors()
local found = false
local target = 0
local dead = false
for _, actor in ipairs(snapshot and snapshot.actors or {{}}) do
  if tonumber(actor.network_actor_id) == network_actor_id then
    found = true
    target = tonumber(actor.target_participant_id) or 0
    dead = actor.dead == true
    break
  end
end
print("found=" .. tostring(found))
print("target=" .. tostring(target))
print("dead=" .. tostring(dead))
"""
    return _wait(
        lambda: local_sync.parse_key_values(
            local_sync.lua(pipe_name, code, timeout=7.5)
        ),
        lambda values: (
            values.get("found") == "true"
            and values.get("dead") == "false"
            and _integer(values, "target") == participant_id
        ),
        timeout=timeout,
        label=f"enemy target identity {network_actor_id} on {pipe_name}",
    )


def _wait_for_despawn(pipe_name: str, participant_id: int) -> dict[str, str]:
    code = f"""
local participant_id = {participant_id}
local found = false
for _, candidate in ipairs(sd.bots.get_participants() or {{}}) do
  if tonumber(candidate.id) == participant_id then
    found = true
    break
  end
end
local member = false
local state = sd.runtime.get_multiplayer_state()
for _, candidate in ipairs(state and state.participants or {{}}) do
  if tonumber(candidate.participant_id) == participant_id then
    member = true
    break
  end
end
local snapshot = sd.bots.get_participant_state(participant_id)
print("found=" .. tostring(found))
print("member=" .. tostring(member))
print("available=" .. tostring(snapshot ~= nil and snapshot.available))
"""
    return _wait(
        lambda: local_sync.parse_key_values(
            local_sync.lua(pipe_name, code, timeout=7.5)
        ),
        lambda values: (
            values.get("found") == "false"
            and values.get("member") == "false"
            and values.get("available") == "false"
        ),
        timeout=12.0,
        label=f"synthetic participant retirement on {pipe_name}",
    )


def _query_handle_contract(
    pipe_name: str,
    participant_id: int,
    *,
    attempt_mutation: bool,
) -> dict[str, str]:
    code = f"""
local wanted = {participant_id}
local list = sd.bots.list()
local bot = nil
for _, candidate in ipairs(list or {{}}) do
  if tonumber(candidate:participant_id()) == wanted then
    bot = candidate
    break
  end
end
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
emit("count", #(list or {{}}))
emit("found", bot ~= nil)
if bot == nil then return end
local x, y = bot:position()
emit("participant_id", bot:participant_id())
emit("slot", bot:slot())
emit("x", x)
emit("y", y)
emit("hp", bot:hp())
emit("max_hp", bot:max_hp())
emit("alive", bot:alive())
for _, method in ipairs({{
  "despawn", "move_to", "stop", "cast", "position", "hp", "max_hp",
  "alive", "slot", "participant_id"
}}) do
  emit("method." .. method, type(bot[method]))
end
if {str(attempt_mutation).lower()} then
  local ok, err = bot:stop()
  emit("mutation_ok", ok)
  emit("mutation_error", err or "")
end
"""
    return local_sync.parse_key_values(
        local_sync.lua(pipe_name, code, timeout=7.5)
    )


def _handle_contract_is_valid(
    values: dict[str, str],
    participant_id: int,
) -> bool:
    return (
        values.get("found") == "true"
        and _integer(values, "count") == 1
        and _integer(values, "participant_id") == participant_id
        and 1 <= _integer(values, "slot", -1) <= 3
        and math.isfinite(_number(values, "x", math.nan))
        and math.isfinite(_number(values, "y", math.nan))
        and _number(values, "hp") > 0.0
        and _number(values, "max_hp") > 0.0
        and values.get("alive") == "true"
        and all(
            values.get(f"method.{method}") == "function"
            for method in (
                "despawn",
                "move_to",
                "stop",
                "cast",
                "position",
                "hp",
                "max_hp",
                "alive",
                "slot",
                "participant_id",
            )
        )
    )


def _choose_nav_target(
    pipe_name: str,
    participant_id: int,
    *,
    minimum_distance: float,
    maximum_distance: float,
) -> dict[str, str]:
    code = f"""
local bot = sd.bots.get_participant_state({participant_id})
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
if bot == nil or not bot.transform_valid then
  emit("ready", false)
  emit("reason", "bot_transform")
  return
end
local distances = {{
  {minimum_distance:.3f},
  {(minimum_distance + maximum_distance) * 0.5:.3f},
  {maximum_distance:.3f}
}}
local best = nil
for _, distance in ipairs(distances) do
  for index = 0, 15 do
    local radians = index * math.pi / 8
    local x = bot.x + math.cos(radians) * distance
    local y = bot.y + math.sin(radians) * distance
    local ok, traversable = pcall(
      sd.nav.test_segment, bot.x, bot.y, x, y)
    if ok and traversable then
      best = {{x=x, y=y, distance=distance}}
      break
    end
  end
  if best ~= nil then break end
end
emit("ready", best ~= nil)
emit("x", best and best.x or 0)
emit("y", best and best.y or 0)
emit("distance", best and best.distance or 0)
emit("start_x", bot.x)
emit("start_y", bot.y)
"""
    return _wait(
        lambda: local_sync.parse_key_values(
            local_sync.lua(pipe_name, code, timeout=7.5)
        ),
        lambda values: (
            values.get("ready") == "true"
            and math.isfinite(_number(values, "x", math.nan))
            and math.isfinite(_number(values, "y", math.nan))
        ),
        timeout=12.0,
        label=f"native traversable bot target on {pipe_name}",
    )


def _choose_fire_contact_target(
    pipe_name: str,
    participant_id: int,
) -> dict[str, str]:
    code = f"""
local bot = sd.bots.get_participant_state({participant_id})
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
if bot == nil or not bot.transform_valid then
  emit("ready", false)
  emit("reason", "bot_transform")
  return
end
-- Fireball's native candidate query checks only its current spatial cell.
-- Keep the target well inside a 50-unit row, avoiding the known boundary
-- fixture where a valid trajectory passes the enemy in the adjacent row.
local lane_y = math.floor(bot.y / 50) * 50 + 24
local candidates = {{
  {{x=bot.x + 120, y=lane_y}},
  {{x=bot.x - 120, y=lane_y}},
  {{x=bot.x + 140, y=lane_y}},
  {{x=bot.x - 140, y=lane_y}}
}}
local best = nil
for _, candidate in ipairs(candidates) do
  local ok, traversable = pcall(
    sd.nav.test_segment, bot.x, bot.y, candidate.x, candidate.y)
  if ok and traversable then
    best = candidate
    break
  end
end
emit("ready", best ~= nil)
emit("x", best and best.x or 0)
emit("y", best and best.y or 0)
emit("start_x", bot.x)
emit("start_y", bot.y)
emit("row_phase", best and (best.y % 50) or -1)
"""
    return _wait(
        lambda: local_sync.parse_key_values(
            local_sync.lua(pipe_name, code, timeout=7.5)
        ),
        lambda values: (
            values.get("ready") == "true"
            and abs(_number(values, "row_phase") - 24.0) <= 0.01
        ),
        timeout=12.0,
        label=f"native Fire contact lane on {pipe_name}",
    )


def _issue_handle_move(
    participant_id: int,
    x: float,
    y: float,
) -> dict[str, str]:
    code = f"""
local bot = nil
for _, candidate in ipairs(sd.bots.list() or {{}}) do
  if tonumber(candidate:participant_id()) == {participant_id} then
    bot = candidate
    break
  end
end
local ok, err = false, "missing_handle"
if bot ~= nil then ok, err = bot:move_to({x:.9f}, {y:.9f}) end
print("ok=" .. tostring(ok))
print("error=" .. tostring(err or ""))
print("x={x:.9f}")
print("y={y:.9f}")
"""
    return local_sync.parse_key_values(
        local_sync.lua(HOST_PIPE, code, timeout=7.5)
    )


def _issue_handle_stop(participant_id: int) -> dict[str, str]:
    code = f"""
local bot = nil
for _, candidate in ipairs(sd.bots.list() or {{}}) do
  if tonumber(candidate:participant_id()) == {participant_id} then
    bot = candidate
    break
  end
end
local ok, err = false, "missing_handle"
if bot ~= nil then ok, err = bot:stop() end
print("ok=" .. tostring(ok))
print("error=" .. tostring(err or ""))
"""
    return local_sync.parse_key_values(
        local_sync.lua(HOST_PIPE, code, timeout=7.5)
    )


def _position(values: dict[str, str]) -> tuple[float, float]:
    return (
        _number(values, "bot.x", math.nan),
        _number(values, "bot.y", math.nan),
    )


def _distance(
    first: tuple[float, float],
    second: tuple[float, float],
) -> float:
    return math.hypot(
        first[0] - second[0],
        first[1] - second[1],
    )


def _wait_for_bot_position(
    participant_id: int,
    x: float,
    y: float,
    start: tuple[float, float],
    *,
    timeout: float,
) -> dict[str, Any]:
    target = (x, y)
    initial_gap = _distance(start, target)

    def probe() -> dict[str, dict[str, str]]:
        return {
            "host": _query_bot(HOST_PIPE, participant_id),
            "client": _query_bot(CLIENT_PIPE, participant_id),
        }

    views = _wait(
        probe,
        lambda values: (
            _distance(_position(values["host"]), start) >= 40.0
            and _distance(_position(values["host"]), target)
                <= min(70.0, initial_gap - 40.0)
            and _distance(
                _position(values["host"]),
                _position(values["client"]),
            ) <= 8.0
        ),
        timeout=timeout,
        label="bot movement convergence",
        interval=0.15,
    )
    host_position = _position(views["host"])
    client_position = _position(views["client"])
    return {
        "views": views,
        "start": {"x": start[0], "y": start[1]},
        "target": {"x": x, "y": y},
        "initialTargetGap": initial_gap,
        "hostDistanceMoved": _distance(host_position, start),
        "hostTargetGap": _distance(host_position, target),
        "clientTargetGap": _distance(client_position, target),
        "crossPeerDistance": _distance(host_position, client_position),
    }


def _wait_for_bot_motion(
    participant_id: int,
    start: tuple[float, float],
) -> dict[str, dict[str, str]]:
    return _wait(
        lambda: {
            "host": _query_bot(HOST_PIPE, participant_id),
            "client": _query_bot(CLIENT_PIPE, participant_id),
        },
        lambda values: (
            _distance(_position(values["host"]), start) >= 12.0
            and _distance(
                _position(values["host"]),
                _position(values["client"]),
            ) <= 10.0
        ),
        timeout=8.0,
        label="bot movement start",
        interval=0.1,
    )


def _wait_for_stopped_bot(
    participant_id: int,
) -> dict[str, Any]:
    return _wait_for_bot_settle(participant_id, timeout=8.0)


def _wait_for_bot_settle(
    participant_id: int,
    *,
    timeout: float,
) -> dict[str, Any]:
    last: dict[str, dict[str, str]] | None = None
    stable_since: float | None = None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = {
            "host": _query_bot(HOST_PIPE, participant_id),
            "client": _query_bot(CLIENT_PIPE, participant_id),
        }
        if last is not None:
            host_drift = _distance(
                _position(last["host"]),
                _position(current["host"]),
            )
            client_drift = _distance(
                _position(last["client"]),
                _position(current["client"]),
            )
            parity = _distance(
                _position(current["host"]),
                _position(current["client"]),
            )
            if host_drift <= 0.75 and client_drift <= 1.25 and parity <= 8.0:
                if stable_since is None:
                    stable_since = time.monotonic()
                if time.monotonic() - stable_since >= 1.0:
                    return {
                        "previous": last,
                        "current": current,
                        "hostDrift": host_drift,
                        "clientDrift": client_drift,
                        "crossPeerDistance": parity,
                    }
            else:
                stable_since = None
        last = current
        time.sleep(0.2)
    raise BotAcceptanceFailure(
        "bot did not settle after the stock run entrance; "
        f"last={last!r}"
    )


def _set_manual_spawner_mode(
    pipe_name: str,
    enabled: bool,
) -> dict[str, str]:
    return local_sync.parse_key_values(
        local_sync.lua(
            pipe_name,
            f"""
local ok, active =
  sd.gameplay.set_manual_enemy_spawner_test_mode(
    {str(enabled).lower()})
print("ok=" .. tostring(ok))
print("active=" .. tostring(active))
""",
            timeout=7.5,
        )
    )


def _wait_for_combat_prelude_ready(
    pipe_name: str,
) -> dict[str, str]:
    code = """
local state = sd.gameplay.get_combat_state()
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
emit("available", state ~= nil)
emit("wave", state and state.wave_index or 0)
emit("active", state ~= nil and state.active)
emit("transition_requested", state ~= nil and state.transition_requested)
"""
    return _wait(
        lambda: local_sync.parse_key_values(
            local_sync.lua(pipe_name, code, timeout=7.5)
        ),
        lambda values: (
            values.get("available") == "true"
            and _integer(values, "wave") == 0
            and values.get("active") == "true"
            and values.get("transition_requested") == "true"
        ),
        timeout=10.0,
        label="stock combat prelude readiness",
        interval=0.1,
    )


def _wait_for_manual_spawner(
    pipe_name: str,
) -> dict[str, str]:
    code = """
local state = sd.gameplay.get_manual_enemy_spawner_state()
print("manual_mode=" ..
  tostring(state ~= nil and state.manual_mode))
print("has_spawner=" ..
  tostring(state ~= nil and state.has_spawner))
print("spawner_address=" ..
  tostring(state and state.spawner_address or 0))
print("spawner_id=" .. tostring(state and state.spawner_id or ""))
"""
    return _wait(
        lambda: local_sync.parse_key_values(
            local_sync.lua(pipe_name, code, timeout=7.5)
        ),
        lambda values: (
            values.get("manual_mode") == "true"
            and values.get("has_spawner") == "true"
            and _integer(values, "spawner_address") > 0
        ),
        timeout=10.0,
        label=f"native manual spawner on {pipe_name}",
        interval=0.1,
    )


def _spawn_frozen_enemy(
    x: float,
    y: float,
    *,
    hp: float,
) -> dict[str, Any]:
    request = local_sync.parse_key_values(
        local_sync.lua(
            HOST_PIPE,
            f"""
local ok, err, request_id = sd.gameplay.spawn_manual_run_enemy{{
  type_id={SKELETON_TYPE_ID},
  x={x:.9f},
  y={y:.9f},
  freeze_on_spawn=true
}}
print("ok=" .. tostring(ok))
print("error=" .. tostring(err or ""))
print("request_id=" .. tostring(request_id or 0))
""",
            timeout=7.5,
        )
    )
    request_id = _integer(request, "request_id")
    if request.get("ok") != "true" or request_id <= 0:
        raise BotAcceptanceFailure(
            f"frozen enemy spawn was rejected: {request}"
        )

    result = _wait(
        lambda: local_sync.parse_key_values(
            local_sync.lua(
                HOST_PIPE,
                f"""
local result = sd.gameplay.get_last_manual_run_enemy_spawn({request_id})
print("present=" .. tostring(result ~= nil))
print("ok=" .. tostring(result ~= nil and result.ok))
print("actor=" .. tostring(result and result.actor_address or 0))
print("network_id=" ..
  string.format("%.0f", tonumber(result and result.network_actor_id) or 0))
print("error=" .. tostring(result and result.error or ""))
""",
                timeout=7.5,
            )
        ),
        lambda values: (
            values.get("present") == "true"
            and values.get("ok") == "true"
            and _integer(values, "actor") > 0
            and _integer(values, "network_id") > 0
        ),
        timeout=20.0,
        label="frozen enemy materialization",
    )
    actor = _integer(result, "actor")
    network_id = _integer(result, "network_id")
    configure = local_sync.parse_key_values(
        local_sync.lua(
            HOST_PIPE,
            f"""
local actor = {actor}
local x_offset = sd.debug.layout_offset("actor_position_x")
local y_offset = sd.debug.layout_offset("actor_position_y")
local target_offset = sd.debug.layout_offset("actor_current_target_actor")
local bucket_offset =
  sd.debug.layout_offset("actor_current_target_bucket_delta")
print("health=" ..
  tostring(sd.gameplay.set_run_enemy_health(actor, {hp:.9f}, {hp:.9f})))
print("x=" ..
  tostring(x_offset ~= nil and
    sd.debug.write_float(actor + x_offset, {x:.9f})))
print("y=" ..
  tostring(y_offset ~= nil and
    sd.debug.write_float(actor + y_offset, {y:.9f})))
if target_offset ~= nil then
  print("target=" ..
    tostring(sd.debug.write_ptr(actor + target_offset, 0)))
end
if bucket_offset ~= nil then
  print("bucket=" ..
    tostring(sd.debug.write_i32(actor + bucket_offset, 0)))
end
local rebind, err = sd.world.rebind_actor(actor)
print("rebind=" .. tostring(rebind))
print("rebind_error=" .. tostring(err or ""))
""",
            timeout=7.5,
        )
    )
    if (
        configure.get("health") != "true"
        or configure.get("x") != "true"
        or configure.get("y") != "true"
        or configure.get("rebind") != "true"
    ):
        raise BotAcceptanceFailure(
            f"frozen enemy setup failed: {configure}"
        )
    return {
        "request": request,
        "result": result,
        "configure": configure,
        "actor": actor,
        "networkId": network_id,
        "x": x,
        "y": y,
        "hp": hp,
    }


def _query_enemy(
    pipe_name: str,
    network_id: int,
) -> dict[str, str]:
    code = f"""
local wanted = {network_id}
local local_actor =
  sd.world.get_run_enemy_by_network_id(wanted)
local replicated = nil
for _, actor in ipairs(
    (sd.world.get_replicated_actors() or {{}}).actors or {{}}) do
  if tonumber(actor.network_actor_id) == wanted then
    replicated = actor
    break
  end
end
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
emit("local.found", local_actor ~= nil)
emit("local.actor", local_actor and local_actor.actor_address or 0)
emit("local.hp", local_actor and local_actor.hp or 0)
emit("local.max_hp", local_actor and local_actor.max_hp or 0)
emit("local.dead", local_actor ~= nil and local_actor.dead)
emit("rep.found", replicated ~= nil)
emit("rep.hp", replicated and replicated.hp or 0)
emit("rep.max_hp", replicated and replicated.max_hp or 0)
emit("rep.dead", replicated ~= nil and replicated.dead)
emit("rep.target", replicated and replicated.target_participant_id or 0)
emit("rep.type", replicated and replicated.object_type_id or 0)
"""
    return local_sync.parse_key_values(
        local_sync.lua(pipe_name, code, timeout=7.5)
    )


def _wait_for_enemy_on_both(
    network_id: int,
    *,
    minimum_hp: float,
) -> dict[str, dict[str, str]]:
    return _wait(
        lambda: {
            "host": _query_enemy(HOST_PIPE, network_id),
            "client": _query_enemy(CLIENT_PIPE, network_id),
        },
        lambda values: all(
            peer.get("local.found") == "true"
            and peer.get("rep.found") == "true"
            and _number(peer, "local.hp") >= minimum_hp - 0.1
            and _number(peer, "rep.hp") >= minimum_hp - 0.1
            for peer in values.values()
        ),
        timeout=10.0,
        label=f"enemy {network_id} cross-peer materialization",
    )


def _issue_handle_cast(
    participant_id: int,
    target_x: float,
    target_y: float,
    *,
    hold_ms: int = 80,
) -> dict[str, str]:
    code = f"""
local bot = nil
for _, candidate in ipairs(sd.bots.list() or {{}}) do
  if tonumber(candidate:participant_id()) == {participant_id} then
    bot = candidate
    break
  end
end
local ok, err = false, "missing_handle"
if bot ~= nil then
  ok, err = bot:cast(
    0, {target_x:.9f}, {target_y:.9f}, {hold_ms})
end
print("ok=" .. tostring(ok))
print("error=" .. tostring(err or ""))
"""
    return local_sync.parse_key_values(
        local_sync.lua(HOST_PIPE, code, timeout=7.5)
    )


def _loader_log_path(role: str) -> Path:
    return (
        ROOT
        / "runtime"
        / "instances"
        / f"{INSTANCE_PREFIX}-{role}"
        / "stage"
        / ".sdmod"
        / "logs"
        / "solomondarkmodloader.log"
    )


def _read_log_after(path: Path, offset: int) -> str:
    if not path.is_file():
        return ""
    with path.open("rb") as stream:
        stream.seek(offset)
        return stream.read().decode("utf-8", errors="replace")


def _wait_for_cast_effect_logs(
    participant_id: int,
    offsets: dict[str, int],
) -> dict[str, str]:
    def probe() -> dict[str, str]:
        return {
            role: _read_log_after(_loader_log_path(role), offset)
            for role, offset in offsets.items()
        }

    evidence = _wait(
        probe,
        lambda logs: all(
            f"bot_id={participant_id}" in text
            and "remote_input_controlled=1" in text
            and "remote_projectile_expected_type=0x7D4" in text
            and "remote_projectile_observed=1" in text
            and "remote_projectile_trajectory_valid=1" in text
            for text in logs.values()
        ),
        timeout=8.0,
        label="native Fire projectile lifecycle on both peers",
        interval=0.1,
    )
    return {
        role: "\n".join(
            line
            for line in text.splitlines()
            if (
                f"bot_id={participant_id}" in line
                and (
                    "cast complete" in line
                    or "remote cast queued" in line
                    or "synthetic cast injected" in line
                )
            )
        )
        for role, text in evidence.items()
    }


def _queue_native_magic_hit(
    participant_id: int,
    *,
    damage: float,
) -> dict[str, Any]:
    queued = local_sync.parse_key_values(
        local_sync.lua(
            HOST_PIPE,
            f"""
local ok, err, serial =
  sd.debug.queue_native_magic_hit_behavior_probe(
    {damage:.9f}, 0.0, 1, {participant_id}, 0.0)
print("ok=" .. tostring(ok))
print("error=" .. tostring(err or ""))
print("serial=" .. tostring(serial or 0))
""",
            timeout=7.5,
        )
    )
    serial = _integer(queued, "serial")
    if queued.get("ok") != "true" or serial <= 0:
        raise BotAcceptanceFailure(
            f"native participant hit did not queue: {queued}"
        )
    completed = _wait(
        lambda: local_sync.parse_key_values(
            local_sync.lua(
                HOST_PIPE,
                f"""
local completed, success, hp_before, hp_after, err =
  sd.debug.get_native_magic_hit_behavior_probe_result({serial})
print("completed=" .. tostring(completed))
print("success=" .. tostring(success))
print("hp_before=" .. tostring(hp_before))
print("hp_after=" .. tostring(hp_after))
print("error=" .. tostring(err or ""))
""",
                timeout=7.5,
            )
        ),
        lambda values: values.get("completed") == "true",
        timeout=8.0,
        label=f"native participant hit {serial}",
        interval=0.05,
    )
    if completed.get("success") != "true":
        raise BotAcceptanceFailure(
            f"native participant hit failed: {completed}"
        )
    return {
        "queue": queued,
        "result": completed,
        "damage": damage,
        "hpBefore": _number(completed, "hp_before"),
        "hpAfter": _number(completed, "hp_after"),
    }


def _wait_for_bot_hp(
    participant_id: int,
    expected_hp: float,
    *,
    timeout: float = 8.0,
) -> dict[str, dict[str, str]]:
    return _wait(
        lambda: {
            "host": _query_bot(HOST_PIPE, participant_id),
            "client": _query_bot(CLIENT_PIPE, participant_id),
        },
        lambda values: all(
            abs(_number(peer, "bot.hp", math.nan) - expected_hp) <= 0.25
            for peer in values.values()
        ),
        timeout=timeout,
        label=f"bot HP convergence to {expected_hp:.3f}",
        interval=0.1,
    )


def _query_death_state(
    pipe_name: str,
    participant_id: int,
) -> dict[str, str]:
    code = f"""
local participant_id = {participant_id}
local multiplayer = sd.runtime.get_multiplayer_state()
local participant = nil
for _, candidate in ipairs(multiplayer and multiplayer.participants or {{}}) do
  if tonumber(candidate.participant_id) == participant_id then
    participant = candidate
    break
  end
end
local gameplay = sd.bots.get_participant_state(participant_id)
local actor = gameplay and tonumber(gameplay.actor_address) or 0
local function read_u8(offset_name)
  local offset = sd.debug.layout_offset(offset_name)
  if actor == 0 or offset == nil then return 0 end
  return sd.debug.read_u8(actor + offset) or 0
end
local function read_u32(offset_name)
  local offset = sd.debug.layout_offset(offset_name)
  if actor == 0 or offset == nil then return 0 end
  return sd.debug.read_u32(actor + offset) or 0
end
local flags = tonumber(participant and participant.presentation_flags) or 0
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
emit("found", participant ~= nil and gameplay ~= nil)
emit("actor", actor)
emit("materialized",
  gameplay ~= nil and gameplay.entity_materialized and actor ~= 0)
emit("hp", gameplay and gameplay.hp or
  (participant and participant.life_current or 0))
emit("max_hp", gameplay and gameplay.max_hp or
  (participant and participant.life_max or 0))
emit("x", gameplay and gameplay.x or 0)
emit("y", gameplay and gameplay.y or 0)
emit("runtime_tick",
  participant and participant.death_presentation_tick or 0)
emit("presentation_flags", flags)
emit("presentation_active",
  math.floor(flags / {DEATH_PRESENTATION_FLAG}) % 2 == 1)
emit("drive", read_u8("actor_animation_drive_state_byte"))
emit("raw_tick", read_u32("actor_animation_move_duration_ticks"))
emit("terminal_pending", read_u8("actor_terminal_dispatch_pending"))
emit("terminal_countdown",
  read_u32("actor_terminal_dispatch_countdown"))
"""
    return local_sync.parse_key_values(
        local_sync.lua(pipe_name, code, timeout=7.5)
    )


def _death_started(values: dict[str, str]) -> bool:
    return (
        values.get("found") == "true"
        and values.get("materialized") == "true"
        and _number(values, "max_hp") > 0.0
        and _number(values, "hp") <= 0.0
        and _integer(values, "drive") == 1
        and (
            values.get("presentation_active") == "true"
            or _integer(values, "runtime_tick") > 0
        )
        and (
            _integer(values, "runtime_tick") > 0
            or _integer(values, "raw_tick") > 0
        )
    )


def _terminal_corpse(values: dict[str, str]) -> bool:
    return (
        values.get("found") == "true"
        and values.get("materialized") == "true"
        and _number(values, "hp") <= 0.0
        and _integer(values, "drive") == 1
        and (
            _integer(values, "runtime_tick") == TERMINAL_CORPSE_TICK
            or _integer(values, "raw_tick") == 150
        )
        and _integer(values, "terminal_pending") == 0
        and _integer(values, "terminal_countdown") == 0
    )


def _query_target_identity(
    pipe_name: str,
    network_actor_id: int,
) -> dict[str, str]:
    code = f"""
local wanted = {network_actor_id}
local found = nil
for _, actor in ipairs(
    (sd.world.get_replicated_actors() or {{}}).actors or {{}}) do
  if tonumber(actor.network_actor_id) == wanted then
    found = actor
    break
  end
end
print("found=" .. tostring(found ~= nil))
print("dead=" .. tostring(found ~= nil and found.dead))
print("target=" ..
  tostring(found and found.target_participant_id or 0))
"""
    return local_sync.parse_key_values(
        local_sync.lua(pipe_name, code, timeout=7.5)
    )


def _wait_for_survivor_retarget(
    network_actor_id: int,
    dead_participant_id: int,
) -> dict[str, dict[str, str]]:
    return _wait(
        lambda: {
            "host": _query_target_identity(
                HOST_PIPE,
                network_actor_id,
            ),
            "client": _query_target_identity(
                CLIENT_PIPE,
                network_actor_id,
            ),
        },
        lambda values: (
            values["host"].get("found") == "true"
            and values["client"].get("found") == "true"
            and values["host"].get("dead") == "false"
            and values["client"].get("dead") == "false"
            and _integer(values["host"], "target") > 0
            and _integer(values["host"], "target") != dead_participant_id
            and _integer(values["host"], "target")
                == _integer(values["client"], "target")
        ),
        timeout=12.0,
        label=f"enemy {network_actor_id} retarget to a surviving participant",
        interval=0.15,
    )


def _copy_runtime_evidence(
    launch: dict[str, object],
    output_directory: Path,
) -> dict[str, str]:
    copied: dict[str, str] = {}
    for role in ("host", "client"):
        executable = launch.get(f"{role}ExecutablePath")
        if not isinstance(executable, str) or not executable:
            continue
        stage_path = (
            ROOT
            / "runtime"
            / "instances"
            / f"{INSTANCE_PREFIX}-{role}"
            / "stage"
        )
        for relative, label in (
            (
                Path(".sdmod/logs/solomondarkmodloader.log"),
                f"{role}-solomondarkmodloader.log",
            ),
            (
                Path(".sdmod/startup-status.json"),
                f"{role}-startup-status.json",
            ),
            (
                Path(".sdmod/multiplayer-session-status.json"),
                f"{role}-multiplayer-session-status.json",
            ),
        ):
            source = stage_path / relative
            if not source.is_file():
                continue
            destination = output_directory / label
            shutil.copy2(source, destination)
            copied[label] = str(destination)
    return copied


def verify_lifecycle(
    *,
    game_directory: Path,
    evidence_directory: Path,
    launcher_path: Path,
) -> dict[str, Any]:
    evidence_directory.mkdir(parents=True, exist_ok=True)
    launch: dict[str, object] = {}
    result: dict[str, Any] = {
        "phase": "participant_lifecycle",
        "instancePrefix": INSTANCE_PREFIX,
        "ports": {"host": HOST_PORT, "client": CLIENT_PORT},
        "audioExpectedDisabled": True,
    }
    failure: BaseException | None = None
    try:
        launch = local_sync.launch_pair(
            instance_prefix=INSTANCE_PREFIX,
            host_port=HOST_PORT,
            client_port=CLIENT_PORT,
            temporary_host_profile=True,
            kill_existing=False,
            god_mode=True,
            exact_mod_id=EXACT_MOD_ID,
            launcher_path=launcher_path,
            game_directory=game_directory,
            enable_audio=False,
        )
        result["launch"] = launch
        if launch.get("audioDisabled") is not True:
            raise BotAcceptanceFailure(
                f"pair did not launch with audio disabled: {launch}"
            )
        if (
            int(launch.get("hostPort", 0)) != HOST_PORT
            or int(launch.get("clientPort", 0)) != CLIENT_PORT
        ):
            raise BotAcceptanceFailure(
                f"pair launched on unexpected ports: {launch}"
            )

        time.sleep(2.0)
        spawn = local_sync.parse_key_values(
            local_sync.lua(
                HOST_PIPE,
                f"""
_G.bot_acceptance = assert(
  sd.bots.spawn{{name={json.dumps(BOT_NAME)}, class={json.dumps(BOT_CLASS)}}})
print("participant_id=" ..
  tostring(_G.bot_acceptance:participant_id()))
""",
                timeout=10.0,
            )
        )
        participant_id = _integer(spawn, "participant_id")
        if participant_id <= 0:
            raise BotAcceptanceFailure(
                f"spawn did not return a participant handle: {spawn}"
            )
        result["spawn"] = {
            "name": BOT_NAME,
            "class": BOT_CLASS,
            "participantId": participant_id,
        }

        hub_host = _wait(
            lambda: _query_bot(HOST_PIPE, participant_id),
            lambda values: _bot_is_materialized(values, "hub"),
            timeout=15.0,
            label="host hub synthetic participant",
        )
        hub_client = _wait(
            lambda: _query_bot(CLIENT_PIPE, participant_id),
            lambda values: _bot_is_materialized(values, "hub"),
            timeout=15.0,
            label="client hub synthetic participant",
        )
        result["hub"] = {
            "host": hub_host,
            "client": hub_client,
        }

        _start_testrun()
        local_sync.wait_for_scene(HOST_PIPE, "testrun", timeout=45.0)
        local_sync.wait_for_scene(CLIENT_PIPE, "testrun", timeout=45.0)
        run_host = _wait(
            lambda: _query_bot(HOST_PIPE, participant_id),
            lambda values: _bot_is_materialized(values, "testrun"),
            timeout=20.0,
            label="host run synthetic participant",
        )
        run_client = _wait(
            lambda: _query_bot(CLIENT_PIPE, participant_id),
            lambda values: _bot_is_materialized(values, "testrun"),
            timeout=20.0,
            label="client run synthetic participant",
        )
        result["run"] = {
            "host": run_host,
            "client": run_client,
            "slotPolicy": (
                "peer-local stock slot allocation; each synthetic avatar "
                "occupies one ordinary remote slot in 1..3"
            ),
        }

        wave_start = local_sync.parse_key_values(
            local_sync.lua(
                HOST_PIPE,
                """
print("prelude=" ..
  tostring(sd.gameplay.enable_combat_prelude()))
print("waves=" .. tostring(sd.gameplay.start_waves()))
""",
                timeout=10.0,
            )
        )
        if (
            wave_start.get("prelude") != "true"
            or wave_start.get("waves") != "true"
        ):
            raise BotAcceptanceFailure(
                f"stock waves did not start: {wave_start}"
            )
        host_target = _wait_for_enemy_target(
            HOST_PIPE,
            participant_id,
            expected_authority=True,
        )
        target_network_actor_id = _integer(
            host_target,
            "first_id",
        )
        client_target = _wait_for_target_identity(
            CLIENT_PIPE,
            participant_id,
            target_network_actor_id,
        )
        result["nativeTargeting"] = {
            "host": host_target,
            "client": client_target,
            "networkActorId": target_network_actor_id,
        }

        screenshots = {
            "host": multiplayer_frame_capture.capture_game_backbuffer(
                HOST_PIPE,
                evidence_directory / "host-bot-mid-fight.png",
            ),
            "client": multiplayer_frame_capture.capture_game_backbuffer(
                CLIENT_PIPE,
                evidence_directory / "client-bot-mid-fight.png",
            ),
        }
        result["screenshots"] = screenshots

        despawn = local_sync.parse_key_values(
            local_sync.lua(
                HOST_PIPE,
                """
local ok, err = _G.bot_acceptance:despawn()
print("ok=" .. tostring(ok))
print("error=" .. tostring(err or ""))
""",
                timeout=10.0,
            )
        )
        if despawn.get("ok") != "true":
            raise BotAcceptanceFailure(
                f"host bot handle did not despawn cleanly: {despawn}"
            )
        result["despawn"] = {
            "request": despawn,
            "host": _wait_for_despawn(
                HOST_PIPE,
                participant_id,
            ),
            "client": _wait_for_despawn(
                CLIENT_PIPE,
                participant_id,
            ),
        }
        result["success"] = True
    except BaseException as exc:
        result["success"] = False
        result["error"] = f"{type(exc).__name__}: {exc}"
        failure = exc
    finally:
        if launch:
            try:
                result["runtimeEvidence"] = _copy_runtime_evidence(
                    launch,
                    evidence_directory,
                )
            except BaseException as copy_error:
                result["evidenceCopyError"] = (
                    f"{type(copy_error).__name__}: {copy_error}"
                )
            try:
                result["cleanup"] = (
                    local_sync.stop_exact_game_processes(launch)
                )
            except BaseException as cleanup_error:
                result["cleanupError"] = (
                    f"{type(cleanup_error).__name__}: {cleanup_error}"
                )
                if failure is None:
                    failure = cleanup_error
                    result["success"] = False

        result_path = evidence_directory / "result.json"
        result_path.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        print(f"RESULT={result_path}")

    if failure is not None:
        raise failure
    return result


def verify_control(
    *,
    game_directory: Path,
    evidence_directory: Path,
    launcher_path: Path,
) -> dict[str, Any]:
    evidence_directory.mkdir(parents=True, exist_ok=True)
    launch: dict[str, object] = {}
    result: dict[str, Any] = {
        "phase": "control_and_death",
        "instancePrefix": INSTANCE_PREFIX,
        "ports": {"host": HOST_PORT, "client": CLIENT_PORT},
        "audioExpectedDisabled": True,
    }
    failure: BaseException | None = None
    try:
        launch = local_sync.launch_pair(
            instance_prefix=INSTANCE_PREFIX,
            host_port=HOST_PORT,
            client_port=CLIENT_PORT,
            temporary_host_profile=True,
            kill_existing=False,
            god_mode=True,
            exact_mod_id=EXACT_MOD_ID,
            launcher_path=launcher_path,
            game_directory=game_directory,
            enable_audio=False,
        )
        result["launch"] = launch
        if (
            launch.get("audioDisabled") is not True
            or int(launch.get("hostPort", 0)) != HOST_PORT
            or int(launch.get("clientPort", 0)) != CLIENT_PORT
        ):
            raise BotAcceptanceFailure(
                f"isolated audio-off pair contract failed: {launch}"
            )

        time.sleep(2.0)
        spawn = local_sync.parse_key_values(
            local_sync.lua(
                HOST_PIPE,
                f"""
_G.bot_acceptance = assert(
  sd.bots.spawn{{name={json.dumps(BOT_NAME)}, class={json.dumps(BOT_CLASS)}}})
print("participant_id=" ..
  tostring(_G.bot_acceptance:participant_id()))
""",
                timeout=10.0,
            )
        )
        participant_id = _integer(spawn, "participant_id")
        if participant_id <= 0:
            raise BotAcceptanceFailure(
                f"spawn did not return a participant handle: {spawn}"
            )
        result["spawn"] = {
            "name": BOT_NAME,
            "class": BOT_CLASS,
            "participantId": participant_id,
        }

        _wait(
            lambda: _query_bot(HOST_PIPE, participant_id),
            lambda values: _bot_is_materialized(values, "hub"),
            timeout=15.0,
            label="host hub bot before control acceptance",
        )
        _wait(
            lambda: _query_bot(CLIENT_PIPE, participant_id),
            lambda values: _bot_is_materialized(values, "hub"),
            timeout=15.0,
            label="client hub bot before control acceptance",
        )
        _start_testrun()
        local_sync.wait_for_scene(HOST_PIPE, "testrun", timeout=45.0)
        local_sync.wait_for_scene(CLIENT_PIPE, "testrun", timeout=45.0)
        _wait(
            lambda: _query_bot(HOST_PIPE, participant_id),
            lambda values: _bot_is_materialized(values, "testrun"),
            timeout=20.0,
            label="host run bot before control acceptance",
        )
        _wait(
            lambda: _query_bot(CLIENT_PIPE, participant_id),
            lambda values: _bot_is_materialized(values, "testrun"),
            timeout=20.0,
            label="client run bot before control acceptance",
        )

        entrance_stop = _issue_handle_stop(participant_id)
        if entrance_stop.get("ok") != "true":
            raise BotAcceptanceFailure(
                f"bot stop before run-entrance settle failed: {entrance_stop}"
            )
        entrance_settle = _wait_for_bot_settle(
            participant_id,
            timeout=25.0,
        )
        result["runEntranceSettle"] = {
            "stop": entrance_stop,
            "settle": entrance_settle,
        }

        manual_modes = {
            "host": _set_manual_spawner_mode(HOST_PIPE, True),
            "client": _set_manual_spawner_mode(CLIENT_PIPE, True),
        }
        if any(
            values.get("ok") != "true"
            or values.get("active") != "true"
            for values in manual_modes.values()
        ):
            raise BotAcceptanceFailure(
                f"manual spawner test mode did not enable: {manual_modes}"
            )
        preludes = {
            role: local_sync.parse_key_values(
                local_sync.lua(
                    pipe_name,
                    """
print("ok=" ..
  tostring(sd.gameplay.enable_combat_prelude()))
""",
                    timeout=7.5,
                )
            )
            for role, pipe_name in (
                ("host", HOST_PIPE),
                ("client", CLIENT_PIPE),
            )
        }
        if any(
            values.get("ok") != "true"
            for values in preludes.values()
        ):
            raise BotAcceptanceFailure(
                f"combat prelude did not enable: {preludes}"
            )
        prelude_states = {
            "host": _wait_for_combat_prelude_ready(HOST_PIPE),
            "client": _wait_for_combat_prelude_ready(CLIENT_PIPE),
        }
        prelude_settle = _wait_for_bot_settle(
            participant_id,
            timeout=25.0,
        )
        prime_waves = {
            role: local_sync.parse_key_values(
                local_sync.lua(
                    pipe_name,
                    """
print("ok=" .. tostring(sd.gameplay.start_waves()))
""",
                    timeout=7.5,
                )
            )
            for role, pipe_name in (
                ("host", HOST_PIPE),
                ("client", CLIENT_PIPE),
            )
        }
        if any(
            values.get("ok") != "true"
            for values in prime_waves.values()
        ):
            raise BotAcceptanceFailure(
                f"native spawner priming failed: {prime_waves}"
            )
        manual_spawners = {
            "host": _wait_for_manual_spawner(HOST_PIPE),
            "client": _wait_for_manual_spawner(CLIENT_PIPE),
        }
        result["combatPrelude"] = {
            "manualModes": manual_modes,
            "requests": preludes,
            "states": prelude_states,
            "settle": prelude_settle,
            "primeWaves": prime_waves,
            "spawners": manual_spawners,
        }

        handle_host = _wait(
            lambda: _query_handle_contract(
                HOST_PIPE,
                participant_id,
                attempt_mutation=False,
            ),
            lambda values: _handle_contract_is_valid(
                values,
                participant_id,
            ),
            timeout=10.0,
            label="host sd.bots handle contract",
        )
        handle_client = _wait(
            lambda: _query_handle_contract(
                CLIENT_PIPE,
                participant_id,
                attempt_mutation=True,
            ),
            lambda values: (
                _handle_contract_is_valid(values, participant_id)
                and values.get("mutation_ok") == "false"
                and "only the multiplayer host" in
                    values.get("mutation_error", "")
            ),
            timeout=10.0,
            label="client read-only sd.bots handle contract",
        )
        result["apiContract"] = {
            "host": handle_host,
            "client": handle_client,
        }

        movement_target = _choose_nav_target(
            HOST_PIPE,
            participant_id,
            minimum_distance=140.0,
            maximum_distance=220.0,
        )
        move_request = _issue_handle_move(
            participant_id,
            _number(movement_target, "x"),
            _number(movement_target, "y"),
        )
        if move_request.get("ok") != "true":
            raise BotAcceptanceFailure(
                f"bot:move_to was rejected: {move_request}"
            )
        movement_convergence = _wait_for_bot_position(
            participant_id,
            _number(movement_target, "x"),
            _number(movement_target, "y"),
            (
                _number(movement_target, "start_x"),
                _number(movement_target, "start_y"),
            ),
            timeout=15.0,
        )
        result["move"] = {
            "nativeTarget": movement_target,
            "request": move_request,
            "convergence": movement_convergence,
        }

        stop_target = _choose_nav_target(
            HOST_PIPE,
            participant_id,
            minimum_distance=320.0,
            maximum_distance=520.0,
        )
        stop_start = _position(
            _query_bot(HOST_PIPE, participant_id)
        )
        moving_request = _issue_handle_move(
            participant_id,
            _number(stop_target, "x"),
            _number(stop_target, "y"),
        )
        if moving_request.get("ok") != "true":
            raise BotAcceptanceFailure(
                f"pre-stop movement was rejected: {moving_request}"
            )
        moving = _wait_for_bot_motion(
            participant_id,
            stop_start,
        )
        stop_request = _issue_handle_stop(participant_id)
        if stop_request.get("ok") != "true":
            raise BotAcceptanceFailure(
                f"bot:stop was rejected: {stop_request}"
            )
        stopped = _wait_for_stopped_bot(participant_id)
        result["stop"] = {
            "nativeTarget": stop_target,
            "moveRequest": moving_request,
            "moving": moving,
            "stopRequest": stop_request,
            "settled": stopped,
        }

        cast_origin = _position(
            _query_bot(HOST_PIPE, participant_id)
        )
        cast_target = _choose_fire_contact_target(
            HOST_PIPE,
            participant_id,
        )
        enemy = _spawn_frozen_enemy(
            _number(cast_target, "x"),
            _number(cast_target, "y"),
            hp=500.0,
        )
        enemy_before = _wait_for_enemy_on_both(
            int(enemy["networkId"]),
            minimum_hp=500.0,
        )
        log_offsets = {
            role: (
                _loader_log_path(role).stat().st_size
                if _loader_log_path(role).is_file()
                else 0
            )
            for role in ("host", "client")
        }
        cast_requests: list[dict[str, str]] = []
        cast_damage: dict[str, dict[str, str]] | None = None
        cast_failures: list[str] = []
        for _ in range(3):
            cast_request = _issue_handle_cast(
                participant_id,
                float(enemy["x"]),
                float(enemy["y"]),
            )
            cast_requests.append(cast_request)
            if cast_request.get("ok") != "true":
                cast_failures.append(
                    f"request rejected: {cast_request}"
                )
                time.sleep(0.4)
                continue
            try:
                cast_damage = _wait(
                    lambda: {
                        "host": _query_enemy(
                            HOST_PIPE,
                            int(enemy["networkId"]),
                        ),
                        "client": _query_enemy(
                            CLIENT_PIPE,
                            int(enemy["networkId"]),
                        ),
                    },
                    lambda values: (
                        0.0 < _number(values["host"], "local.hp") < 499.95
                        and 0.0 < _number(values["client"], "local.hp") < 499.95
                        and abs(
                            _number(values["host"], "local.hp")
                            - _number(values["client"], "local.hp")
                        ) <= 0.25
                        and abs(
                            _number(values["host"], "rep.hp")
                            - _number(values["client"], "rep.hp")
                        ) <= 0.25
                    ),
                    timeout=4.0,
                    label="bot Fire damage convergence",
                    interval=0.08,
                )
                break
            except BotAcceptanceFailure as exc:
                cast_failures.append(str(exc))
                time.sleep(0.5)
        if cast_damage is None:
            raise BotAcceptanceFailure(
                "bot primary casts did not damage the frozen native enemy: "
                f"requests={cast_requests} failures={cast_failures}"
            )
        cast_effect_logs = _wait_for_cast_effect_logs(
            participant_id,
            log_offsets,
        )
        result["cast"] = {
            "origin": {"x": cast_origin[0], "y": cast_origin[1]},
            "target": cast_target,
            "enemy": enemy,
            "before": enemy_before,
            "requests": cast_requests,
            "damageConvergence": cast_damage,
            "effectLogs": cast_effect_logs,
            "failedAttempts": cast_failures,
            "nativeProjectileType": FIREBALL_TYPE_ID,
        }

        nonlethal_hit = _queue_native_magic_hit(
            participant_id,
            damage=25.0,
        )
        if nonlethal_hit["hpAfter"] >= nonlethal_hit["hpBefore"]:
            raise BotAcceptanceFailure(
                f"native nonlethal hit caused no damage: {nonlethal_hit}"
            )
        nonlethal_convergence = _wait_for_bot_hp(
            participant_id,
            float(nonlethal_hit["hpAfter"]),
        )
        result["damageIn"] = {
            "nativeHit": nonlethal_hit,
            "convergence": nonlethal_convergence,
        }

        unfreeze = local_sync.parse_key_values(
            local_sync.lua(
                HOST_PIPE,
                f"""
print("unfreeze=" ..
  tostring(sd.gameplay.clear_manual_run_enemy_freeze(
    {int(enemy["actor"])})))
""",
                timeout=10.0,
            )
        )
        manual_mode_disable = {
            "host": _set_manual_spawner_mode(HOST_PIPE, False),
            "client": _set_manual_spawner_mode(CLIENT_PIPE, False),
        }
        waves = local_sync.parse_key_values(
            local_sync.lua(
                HOST_PIPE,
                """
print("ok=" .. tostring(sd.gameplay.start_waves()))
""",
                timeout=10.0,
            )
        )
        if unfreeze.get("unfreeze") != "true" or waves.get("ok") != "true":
            raise BotAcceptanceFailure(
                "stock waves did not start for death acceptance: "
                f"unfreeze={unfreeze} disable={manual_mode_disable} "
                f"waves={waves}"
            )
        result["deathCombatStart"] = {
            "unfreeze": unfreeze,
            "manualModeDisable": manual_mode_disable,
            "waves": waves,
        }
        target_before_death = _wait_for_enemy_target(
            HOST_PIPE,
            participant_id,
            expected_authority=True,
            timeout=30.0,
        )
        targeted_network_id = _integer(
            target_before_death,
            "first_id",
        )
        target_before_client = _wait_for_target_identity(
            CLIENT_PIPE,
            participant_id,
            targeted_network_id,
        )
        result["deathTargetBefore"] = {
            "host": target_before_death,
            "client": target_before_client,
            "networkActorId": targeted_network_id,
        }

        lethal_hit = _queue_native_magic_hit(
            participant_id,
            damage=10000.0,
        )
        if lethal_hit["hpAfter"] > 0.0:
            raise BotAcceptanceFailure(
                f"native lethal hit did not reach zero HP: {lethal_hit}"
            )
        death_started = _wait(
            lambda: {
                "host": _query_death_state(
                    HOST_PIPE,
                    participant_id,
                ),
                "client": _query_death_state(
                    CLIENT_PIPE,
                    participant_id,
                ),
            },
            lambda values: all(
                _death_started(peer)
                for peer in values.values()
            ),
            timeout=8.0,
            label="standard bot death presentation on both peers",
            interval=0.1,
        )
        result["deathStarted"] = {
            "nativeHit": lethal_hit,
            "views": death_started,
            "screenshots": {
                "host": multiplayer_frame_capture.capture_game_backbuffer(
                    HOST_PIPE,
                    evidence_directory
                    / "host-bot-death-presentation.png",
                ),
                "client":
                    multiplayer_frame_capture.capture_game_backbuffer(
                        CLIENT_PIPE,
                        evidence_directory
                        / "client-bot-death-presentation.png",
                    ),
            },
        }

        retarget = _wait_for_survivor_retarget(
            targeted_network_id,
            participant_id,
        )
        result["retarget"] = retarget

        terminal = _wait(
            lambda: {
                "host": _query_death_state(
                    HOST_PIPE,
                    participant_id,
                ),
                "client": _query_death_state(
                    CLIENT_PIPE,
                    participant_id,
                ),
            },
            lambda values: all(
                _terminal_corpse(peer)
                for peer in values.values()
            ),
            timeout=12.0,
            label="standard terminal bot corpse on both peers",
            interval=0.2,
        )
        for role in ("host", "client"):
            if _distance(
                (
                    _number(death_started[role], "x"),
                    _number(death_started[role], "y"),
                ),
                (
                    _number(terminal[role], "x"),
                    _number(terminal[role], "y"),
                ),
            ) > 1.0:
                raise BotAcceptanceFailure(
                    f"{role} bot corpse moved after death: "
                    f"start={death_started[role]} terminal={terminal[role]}"
                )
        post_death_handle = local_sync.parse_key_values(
            local_sync.lua(
                HOST_PIPE,
                f"""
local bot = nil
for _, candidate in ipairs(sd.bots.list() or {{}}) do
  if tonumber(candidate:participant_id()) == {participant_id} then
    bot = candidate
    break
  end
end
print("found=" .. tostring(bot ~= nil))
print("alive=" .. tostring(bot ~= nil and bot:alive()))
local move_ok, move_err = false, "missing"
local cast_ok, cast_err = false, "missing"
if bot ~= nil then
  local x, y = bot:position()
  move_ok, move_err = bot:move_to(x + 100, y)
  cast_ok, cast_err = bot:cast(0, x + 100, y, 80)
end
print("move_ok=" .. tostring(move_ok))
print("move_error=" .. tostring(move_err or ""))
print("cast_ok=" .. tostring(cast_ok))
print("cast_error=" .. tostring(cast_err or ""))
""",
                timeout=10.0,
            )
        )
        if (
            post_death_handle.get("found") != "true"
            or post_death_handle.get("alive") != "false"
            or post_death_handle.get("move_ok") != "false"
            or post_death_handle.get("cast_ok") != "false"
        ):
            raise BotAcceptanceFailure(
                f"dead bot handle remained actionable: {post_death_handle}"
            )
        result["terminalCorpse"] = {
            "views": terminal,
            "handle": post_death_handle,
            "screenshots": {
                "host": multiplayer_frame_capture.capture_game_backbuffer(
                    HOST_PIPE,
                    evidence_directory / "host-bot-terminal-corpse.png",
                ),
                "client":
                    multiplayer_frame_capture.capture_game_backbuffer(
                        CLIENT_PIPE,
                        evidence_directory
                        / "client-bot-terminal-corpse.png",
                    ),
            },
        }

        client_death_log = _read_log_after(
            _loader_log_path("client"),
            0,
        )
        death_marker = (
            "[bots] native remote death epoch started. "
            f"participant_id={participant_id}"
        )
        if death_marker not in client_death_log:
            raise BotAcceptanceFailure(
                "client did not record the packet-driven death epoch"
            )
        result["deathEpochLog"] = death_marker
        result["success"] = True
    except BaseException as exc:
        result["success"] = False
        result["error"] = f"{type(exc).__name__}: {exc}"
        failure = exc
    finally:
        if launch:
            try:
                result["runtimeEvidence"] = _copy_runtime_evidence(
                    launch,
                    evidence_directory,
                )
            except BaseException as copy_error:
                result["evidenceCopyError"] = (
                    f"{type(copy_error).__name__}: {copy_error}"
                )
            try:
                result["cleanup"] = (
                    local_sync.stop_exact_game_processes(launch)
                )
            except BaseException as cleanup_error:
                result["cleanupError"] = (
                    f"{type(cleanup_error).__name__}: {cleanup_error}"
                )
                if failure is None:
                    failure = cleanup_error
                    result["success"] = False

        result_path = evidence_directory / "result.json"
        result_path.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        print(f"RESULT={result_path}")

    if failure is not None:
        raise failure
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--phase",
        choices=("lifecycle", "control"),
        default="lifecycle",
    )
    parser.add_argument(
        "--game-dir",
        type=Path,
        default=GAME_DIRECTORY,
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--launcher",
        type=Path,
        default=ROOT / "dist/launcher/SolomonDarkModLauncher.exe",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if not (args.game_dir / "SolomonDark.exe").is_file():
        raise SystemExit(
            f"source game directory is invalid: {args.game_dir}"
        )
    if not args.launcher.is_file():
        raise SystemExit(f"launcher does not exist: {args.launcher}")
    evidence_directory = args.evidence_dir
    if evidence_directory is None:
        evidence_directory = EVIDENCE_ROOT / (
            "phase1" if args.phase == "lifecycle" else "phase2"
        )
    verifier = (
        verify_lifecycle
        if args.phase == "lifecycle"
        else verify_control
    )
    verifier(
        game_directory=args.game_dir.resolve(),
        evidence_directory=evidence_directory.resolve(),
        launcher_path=args.launcher.resolve(),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
