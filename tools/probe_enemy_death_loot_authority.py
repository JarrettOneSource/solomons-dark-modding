#!/usr/bin/env python3
"""Probe loot authority around one direct client-originated enemy kill."""

from __future__ import annotations

import argparse
import json
import time
from typing import Any

from verify_enemy_damage_claim_sync import (
    CLIENT_PIPE,
    HOST_LOG,
    HOST_PIPE,
    TEST_PLAYER_HP,
    VerifyFailure,
    disable_bots,
    launch_pair,
    log_offset,
    move_client_near,
    number,
    read_log_since,
    select_client_enemy,
    set_local_player_vitals,
    start_host_testrun_and_wait_for_clients,
    start_host_waves,
    stop_games,
    values,
    wait_for_client_enemy_death_handled,
    wait_for_host_enemy_killed,
    wait_for_run_snapshot,
)
from verify_local_multiplayer_sync import ROOT


RUNTIME_OUTPUT = ROOT / "runtime" / "enemy_death_loot_authority_probe.json"
CLIENT_LOG = ROOT / "runtime/instances/local-mp-client/stage/.sdmod/logs/solomondarkmodloader.log"
LOOT_TYPES = {0x07DB, 0x07DC, 0x07DD}


LOOT_CAPTURE_LUA = r"""
local cx = tonumber("__X__") or 0
local cy = tonumber("__Y__") or 0
local radius = tonumber("__RADIUS__") or 320
local radius_sq = radius * radius
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local loot_count = 0
local tracked_count = 0
for _, actor in ipairs(sd.world.list_actors() or {}) do
  local type_id = tonumber(actor.object_type_id) or 0
  if actor.tracked_enemy then tracked_count = tracked_count + 1 end
  if type_id == 0x07DB or type_id == 0x07DC or type_id == 0x07DD then
    local x = tonumber(actor.x) or 0
    local y = tonumber(actor.y) or 0
    local dx = x - cx
    local dy = y - cy
    if dx * dx + dy * dy <= radius_sq then
      loot_count = loot_count + 1
      local prefix = "loot." .. tostring(loot_count) .. "."
      emit(prefix .. "address", string.format("0x%08X", tonumber(actor.actor_address) or 0))
      emit(prefix .. "type", type_id)
      emit(prefix .. "x", string.format("%.3f", x))
      emit(prefix .. "y", string.format("%.3f", y))
      emit(prefix .. "distance", string.format("%.3f", math.sqrt(dx * dx + dy * dy)))
    end
  end
end
emit("loot.count", loot_count)
emit("tracked.count", tracked_count)
"""


CLIENT_DIRECT_KILL_LUA = r"""
local network_id = tonumber("__NETWORK_ACTOR_ID__") or 0
local local_address = tonumber("__LOCAL_ACTOR_ADDRESS__") or 0
local before_hp = tonumber("__BEFORE_HP__") or 0
local max_hp = tonumber("__MAX_HP__") or 0
local x = tonumber("__X__") or 0
local y = tonumber("__Y__") or 0
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local hp_offset = sd.debug.layout_offset("enemy_current_hp")
if network_id == 0 or local_address == 0 or hp_offset == nil or max_hp <= 0 then
  emit("ok", false)
  emit("reason", "invalid_target_or_layout")
  return
end
if sd.input == nil or sd.input.queue_local_enemy_damage_claim == nil then
  emit("ok", false)
  emit("reason", "damage_claim_queue_missing")
  return
end
emit("queue_claim", sd.input.queue_local_enemy_damage_claim(network_id, 0, before_hp, 0.0, max_hp, x, y))
emit("write_hp", sd.debug.write_float(local_address + hp_offset, 0.0))
emit("ok", true)
emit("network_actor_id", string.format("%.0f", network_id))
emit("local_actor_address", local_address)
emit("before_hp", string.format("%.3f", before_hp))
emit("max_hp", string.format("%.3f", max_hp))
emit("x", string.format("%.3f", x))
emit("y", string.format("%.3f", y))
"""


def direct_kill_client_enemy(target: dict[str, str]) -> dict[str, str]:
    code = (
        CLIENT_DIRECT_KILL_LUA
        .replace("__NETWORK_ACTOR_ID__", target["network_actor_id"])
        .replace("__LOCAL_ACTOR_ADDRESS__", target["local_actor_address"])
        .replace("__BEFORE_HP__", target["before_hp"])
        .replace("__MAX_HP__", target["max_hp"])
        .replace("__X__", target["x"])
        .replace("__Y__", target["y"])
    )
    result = values(CLIENT_PIPE, code)
    if result.get("ok") != "true" or result.get("queue_claim") != "true" or result.get("write_hp") != "true":
        raise VerifyFailure(f"failed direct client kill: target={target} result={result}")
    return result


def capture_loot(pipe_name: str, x: float, y: float, radius: float) -> dict[str, Any]:
    raw = values(
        pipe_name,
        LOOT_CAPTURE_LUA
        .replace("__X__", f"{x:.6f}")
        .replace("__Y__", f"{y:.6f}")
        .replace("__RADIUS__", f"{radius:.6f}"),
    )
    rows: list[dict[str, str]] = []
    for index in range(1, int(number(raw, "loot.count")) + 1):
        prefix = f"loot.{index}."
        row = {
            key[len(prefix):]: value
            for key, value in raw.items()
            if key.startswith(prefix)
        }
        if row:
            rows.append(row)
    return {
        "loot_count": int(number(raw, "loot.count")),
        "tracked_count": int(number(raw, "tracked.count")),
        "loot": rows,
    }


def capture_loot_pair(label: str, x: float, y: float, radius: float) -> dict[str, Any]:
    return {
        "label": label,
        "host": capture_loot(HOST_PIPE, x, y, radius),
        "client": capture_loot(CLIENT_PIPE, x, y, radius),
    }


def loot_rows(sample_side: dict[str, Any]) -> list[dict[str, str]]:
    rows = []
    for actor in sample_side.get("loot", []):
        try:
            native_type = int(float(actor.get("type", "0")))
        except ValueError:
            native_type = 0
        if native_type in LOOT_TYPES:
            rows.append(actor)
    return rows


def summarize_samples(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries = []
    for sample in samples:
        host_loot = loot_rows(sample["host"])
        client_loot = loot_rows(sample["client"])
        summaries.append({
            "label": sample["label"],
            "host_loot_count": len(host_loot),
            "client_loot_count": len(client_loot),
            "host_loot_types": [row.get("type") for row in host_loot],
            "client_loot_types": [row.get("type") for row in client_loot],
        })
    return summaries


def run_probe_once(radius: float, keep_open: bool) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": False}
    try:
        stop_games()
        result["launch"] = launch_pair()
        disable_bots()
        result["run_entry"] = start_host_testrun_and_wait_for_clients(timeout=45.0)
        result["start_waves"] = start_host_waves()
        result["snapshot"] = wait_for_run_snapshot(require_complete_lifecycle=True)
        result["initial_host_vitals"] = set_local_player_vitals(HOST_PIPE, TEST_PLAYER_HP, TEST_PLAYER_HP)
        result["initial_client_vitals"] = set_local_player_vitals(CLIENT_PIPE, TEST_PLAYER_HP, TEST_PLAYER_HP)

        target = select_client_enemy()
        result["selected_target"] = target
        result["move_client_near"] = move_client_near(target)
        time.sleep(0.5)

        x = number(target, "x")
        y = number(target, "y")
        samples = [capture_loot_pair("before_kill", x, y, radius)]
        host_log_before = log_offset(HOST_LOG)
        client_log_before = log_offset(CLIENT_LOG)
        result["kill"] = direct_kill_client_enemy(target)
        result["host_killed"] = wait_for_host_enemy_killed(target, timeout=8.0)
        result["client_death_handled"] = wait_for_client_enemy_death_handled(
            target["network_actor_id"],
            target["local_actor_address"],
            timeout=4.0,
        )

        for delay in (0.05, 0.15, 0.35, 0.75, 1.25, 2.0):
            time.sleep(delay)
            samples.append(capture_loot_pair(f"after_{delay:.2f}s", x, y, radius))
        result["samples"] = samples
        result["loot_summary"] = summarize_samples(samples)
        result["host_log_after_kill"] = read_log_since(HOST_LOG, host_log_before)
        result["client_log_after_kill"] = read_log_since(CLIENT_LOG, client_log_before)
        client_only_samples = [
            sample for sample in result["loot_summary"]
            if sample["client_loot_count"] > sample["host_loot_count"]
        ]
        if client_only_samples:
            raise VerifyFailure(f"sample has client-only loot: {client_only_samples[0]}")
        final = result["loot_summary"][-1]
        if final["client_loot_count"] > final["host_loot_count"]:
            raise VerifyFailure(f"final sample has client-only loot: {final}")
        result["ok"] = True
        return result
    finally:
        if not keep_open:
            stop_games()


def run_probe(radius: float, keep_open: bool, attempts: int) -> dict[str, Any]:
    last_error = ""
    attempt_results: list[dict[str, Any]] = []
    for attempt in range(1, attempts + 1):
        try:
            result = run_probe_once(radius, keep_open)
            result["attempt"] = attempt
            result["attempt_results"] = attempt_results
            return result
        except Exception as exc:
            last_error = str(exc)
            attempt_results.append({"attempt": attempt, "error": last_error})
            if keep_open:
                raise
            stop_games()
            time.sleep(1.0)
    return {
        "ok": False,
        "error": f"failed after {attempts} attempts: {last_error}",
        "attempt_results": attempt_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--radius", type=float, default=320.0)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--keep-open", action="store_true")
    args = parser.parse_args()

    try:
        result = run_probe(args.radius, args.keep_open, args.attempts)
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
        if not args.keep_open:
            stop_games()

    RUNTIME_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "ok": result.get("ok", False),
        "selected_target": result.get("selected_target"),
        "kill": result.get("kill"),
        "host_killed": result.get("host_killed"),
        "client_death_handled": result.get("client_death_handled"),
        "loot_summary": result.get("loot_summary"),
        "error": result.get("error"),
        "output": str(RUNTIME_OUTPUT),
    }, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
