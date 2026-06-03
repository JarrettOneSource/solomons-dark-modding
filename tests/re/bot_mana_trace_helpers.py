#!/usr/bin/env python3
"""Shared live helpers for bot mana-delta RE probes."""

from __future__ import annotations

import json
import math
import re
import struct
import time
from typing import Any

import cast_state_probe as csp
from run_live_native_spell_stats_probe import read_runtime_layout_offset


MANA_PREPARED_RE = re.compile(
    r"\[bots\] mana prepared\. bot_id=(?P<bot_id>\d+) "
    r"skill_id=(?P<skill_id>-?\d+) .*? cost=(?P<cost>-?\d+(?:\.\d+)?) "
)


def read_loader_log_lines() -> list[str]:
    if not csp.LOADER_LOG.exists():
        return []
    with csp.LOADER_LOG.open("r", encoding="utf-8", errors="replace") as handle:
        return [line.rstrip("\n") for line in handle]


def stop_bot(bot_id: int) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
emit('ok', sd.bots.stop({bot_id}))
""".strip()
        )
    )


def query_bot_runtime(bot_id: int) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local bot = sd.bots.get_state({bot_id})
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
if type(bot) ~= 'table' then
  emit('ok', false)
  emit('error', 'bot_not_found')
  return
end
for _, key in ipairs({{
  'id','actor_address','progression_runtime_state_address',
  'progression_handle_address','gameplay_slot','actor_slot','mp','max_mp','x','y','state'
}}) do
  emit(key, bot[key])
end
emit('ok', true)
""".strip()
        )
    )


def capture_gameplay_player_actor() -> dict[str, str]:
    gameplay_player_actor_offset = read_runtime_layout_offset("gameplay_player_actor")
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
local function parse_address(value)
  if type(value) == 'number' then
    return value
  end
  if type(value) ~= 'string' then
    return 0
  end
  local hex = value:match('^0x(.+)$')
  if hex then
    return tonumber(hex, 16) or 0
  end
  return tonumber(value) or 0
end
local scene = sd.world and sd.world.get_scene and sd.world.get_scene()
local gameplay = type(scene) == 'table' and parse_address(scene.scene_id or scene.id) or 0
if gameplay == 0 then
  emit('available', false)
  return
end
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
emit('available', true)
emit('gameplay', gameplay)
emit('gameplay_player_actor', sd.debug.read_ptr(gameplay + {gameplay_player_actor_offset}))
if type(player) == 'table' then
  emit('player_state_actor_address', player.actor_address)
  emit('player_state_progression_runtime_state_address', player.progression_runtime_state_address)
  emit('player_state_mp', player.mp)
  emit('player_state_max_mp', player.max_mp)
end
""".strip()
        )
    )


def assert_gameplay_player_actor_unchanged(
    before: dict[str, str],
    after: dict[str, str],
    label: str,
) -> None:
    if before.get("available") != "true" or after.get("available") != "true":
        raise RuntimeError(
            f"unable to capture gameplay player actor for {label}: before={before} after={after}"
        )
    if before.get("gameplay_player_actor") != after.get("gameplay_player_actor"):
        raise RuntimeError(
            f"gameplay player actor changed during {label}: "
            f"before={before.get('gameplay_player_actor')} "
            f"after={after.get('gameplay_player_actor')}"
        )


def assert_gameplay_player_mana_not_decreased(
    before: dict[str, str],
    after: dict[str, str],
    label: str,
    *,
    tolerance: float = 0.001,
) -> None:
    before_mp = csp.float_value(before, "player_state_mp")
    after_mp = csp.float_value(after, "player_state_mp")
    if before_mp != before_mp or after_mp != after_mp:
        raise RuntimeError(
            f"unable to capture gameplay player MP for {label}: before={before} after={after}"
        )
    player_mp_delta = before_mp - after_mp
    if player_mp_delta > tolerance:
        raise RuntimeError(
            f"gameplay player MP decreased during {label}: "
            f"before={before_mp} after={after_mp} delta={player_mp_delta}"
        )


def arm_native_mana_delta_trace(trace_name: str) -> dict[str, str]:
    trace_address = read_runtime_layout_offset("player_actor_apply_mana_delta")
    return csp.parse_key_values(
        csp.run_lua(
            f"""
pcall(sd.debug.untrace_function, {trace_address})
sd.debug.clear_trace_hits({json.dumps(trace_name)})
print('trace_ok=' .. tostring(sd.debug.trace_function({trace_address}, {json.dumps(trace_name)})))
print('trace_address={trace_address}')
""".strip()
        )
    )


def query_native_mana_delta_trace_hits(trace_name: str, max_hits: int = 96) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local hits = sd.debug.get_trace_hits({json.dumps(trace_name)}) or {{}}
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
emit('count', #hits)
for i = 1, math.min(#hits, {max_hits}) do
  local hit = hits[i]
  for _, key in ipairs({{
    'name','requested_address','resolved_address','thread_id','eflags',
    'edi','esi','ebp','esp_before_pushad','ebx','edx','ecx','eax',
    'ret','arg0','arg1','arg2','arg3','arg4','arg5','arg6','arg7','arg8'
  }}) do
    emit('hit.' .. i .. '.' .. key, hit[key])
  end
end
""".strip()
        )
    )


def clear_native_mana_delta_trace(trace_name: str) -> None:
    trace_address = read_runtime_layout_offset("player_actor_apply_mana_delta")
    csp.run_lua(
        f"""
pcall(sd.debug.untrace_function, {trace_address})
sd.debug.clear_trace_hits({json.dumps(trace_name)})
""".strip()
    )


def find_latest_mana_prepared_cost(
    log_lines: list[str],
    start_index: int,
    bot_id: int,
    skill_id: int,
) -> float:
    for line in reversed(log_lines[start_index:]):
        match = MANA_PREPARED_RE.search(line)
        if match is None:
            continue
        if int(match.group("bot_id")) != bot_id:
            continue
        if int(match.group("skill_id")) != skill_id:
            continue
        return float(match.group("cost"))
    raise RuntimeError(
        f"no mana prepared cost found for bot_id={bot_id} skill_id={skill_id}"
    )


def float_from_u32_bits(value: int) -> float:
    try:
        return struct.unpack("<f", struct.pack("<I", value & 0xFFFFFFFF))[0]
    except struct.error:
        return math.nan


def summarize_native_mana_delta_trace_hits(
    hits: dict[str, str],
    actor_address: int,
    player_actor_address: int = 0,
) -> dict[str, Any]:
    count = csp.int_value(hits, "count")
    rows: list[dict[str, Any]] = []
    bot_actor_hits: list[dict[str, Any]] = []
    player_actor_hits: list[dict[str, Any]] = []
    stored_count = min(count, 96)
    for index in range(1, stored_count + 1):
        ecx = csp.int_value(hits, f"hit.{index}.ecx")
        arg0 = csp.int_value(hits, f"hit.{index}.arg0")
        row = {
            "index": index,
            "requested_address": f"0x{csp.int_value(hits, f'hit.{index}.requested_address'):X}",
            "resolved_address": f"0x{csp.int_value(hits, f'hit.{index}.resolved_address'):X}",
            "ecx": f"0x{ecx:X}",
            "arg0_bits": f"0x{arg0 & 0xFFFFFFFF:X}",
            "arg0_float": float_from_u32_bits(arg0),
            "arg1": csp.int_value(hits, f"hit.{index}.arg1"),
            "ret": f"0x{csp.int_value(hits, f'hit.{index}.ret'):X}",
        }
        rows.append(row)
        if ecx == actor_address:
            bot_actor_hits.append(row)
        if player_actor_address and ecx == player_actor_address:
            player_actor_hits.append(row)
    negative_bot_hits = [hit for hit in bot_actor_hits if hit["arg0_float"] < -0.001]
    negative_player_hits = [hit for hit in player_actor_hits if hit["arg0_float"] < -0.001]
    return {
        "native_total_hit_count": count,
        "stored_hit_count": stored_count,
        "hits": rows,
        "bot_actor_hits": bot_actor_hits,
        "negative_bot_actor_hits": negative_bot_hits,
        "player_actor_hits": player_actor_hits,
        "negative_player_actor_hits": negative_player_hits,
    }


def assert_native_mana_delta_matches_prepared_rate(
    mana_delta: dict[str, Any],
    prepared_rate: float,
    label: str,
    *,
    max_rate_multiplier: float = 4.0,
) -> None:
    if not math.isfinite(prepared_rate) or prepared_rate <= 0.0:
        raise RuntimeError(f"{label}: invalid prepared native mana rate {prepared_rate}")

    summary = mana_delta.get("trace_hit_summary", {})
    negative_hits = summary.get("negative_bot_actor_hits", [])
    if not negative_hits:
        raise RuntimeError(f"{label}: no negative native mana-delta hit for bot actor")

    largest_delta = max(abs(float(hit.get("arg0_float", math.nan))) for hit in negative_hits)
    max_allowed = max(prepared_rate + 0.001, prepared_rate * max_rate_multiplier)
    if not math.isfinite(largest_delta) or largest_delta > max_allowed:
        raise RuntimeError(
            f"{label}: native mana delta magnitude is not plausible for prepared "
            f"rate; largest={largest_delta} prepared_rate={prepared_rate} "
            f"max_allowed={max_allowed} hits={negative_hits}"
        )


def wait_for_bot_native_mana_delta(
    bot_id: int,
    actor_address: int,
    before_mp: float,
    trace_name: str,
    timeout_s: float,
    *,
    min_delta: float = 0.001,
    player_actor_address: int = 0,
    gameplay_player_before: dict[str, str] | None = None,
) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last_bot: dict[str, str] = {}
    last_hits: dict[str, str] = {}
    last_summary: dict[str, Any] = {}
    while time.time() < deadline:
        last_bot = query_bot_runtime(bot_id)
        after_mp = csp.float_value(last_bot, "mp")
        last_hits = query_native_mana_delta_trace_hits(trace_name)
        last_summary = summarize_native_mana_delta_trace_hits(
            last_hits,
            actor_address,
            player_actor_address,
        )
        if last_summary["negative_player_actor_hits"]:
            raise RuntimeError(
                "stock native mana delta hit the gameplay player actor during bot cast: "
                f"summary={last_summary}"
            )
        if (
            after_mp == after_mp
            and before_mp - after_mp >= min_delta
            and last_summary["negative_bot_actor_hits"]
        ):
            gameplay_player_after: dict[str, str] | None = None
            player_mp_delta = math.nan
            if gameplay_player_before is not None:
                gameplay_player_after = capture_gameplay_player_actor()
                assert_gameplay_player_actor_unchanged(
                    gameplay_player_before,
                    gameplay_player_after,
                    "stock native bot mana delta",
                )
                assert_gameplay_player_mana_not_decreased(
                    gameplay_player_before,
                    gameplay_player_after,
                    "stock native bot mana delta",
                )
                before_player_mp = csp.float_value(gameplay_player_before, "player_state_mp")
                after_player_mp = csp.float_value(gameplay_player_after, "player_state_mp")
                player_mp_delta = before_player_mp - after_player_mp
            return {
                "bot_after": last_bot,
                "trace_hits": last_hits,
                "trace_hit_summary": last_summary,
                "mp_delta": before_mp - after_mp,
                "gameplay_player_after": gameplay_player_after,
                "player_mp_delta": player_mp_delta,
            }
        time.sleep(0.2)

    raise RuntimeError(
        "timed out waiting for stock native bot mana delta; "
        f"before_mp={before_mp} last_bot={last_bot} summary={last_summary}"
    )
