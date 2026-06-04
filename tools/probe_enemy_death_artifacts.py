#!/usr/bin/env python3
"""Probe local actor artifacts around a real client-originated enemy kill."""

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
    damage_client_enemy,
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
    wait_for_host_enemy_hp,
    wait_for_run_snapshot,
)
from verify_local_multiplayer_sync import ROOT


RUNTIME_OUTPUT = ROOT / "runtime" / "enemy_death_artifacts_probe.json"


NEARBY_ACTORS_LUA = r"""
local cx = tonumber("__X__") or 0
local cy = tonumber("__Y__") or 0
local radius = tonumber("__RADIUS__") or 192
local radius_sq = radius * radius
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local death_handled_offset = sd.debug.layout_offset("enemy_death_handled")
local function death_handled(address)
  if death_handled_offset == nil or address == nil or address == 0 then return 0 end
  local ok, value = pcall(function()
    return sd.debug.read_u8(address + death_handled_offset)
  end)
  if not ok then return 0 end
  return tonumber(value) or 0
end
local rows = {}
for _, actor in ipairs(sd.world.list_actors() or {}) do
  local x = tonumber(actor.x) or 0
  local y = tonumber(actor.y) or 0
  local dx = x - cx
  local dy = y - cy
  local d2 = dx * dx + dy * dy
  local address = tonumber(actor.actor_address) or 0
  if address ~= 0 and d2 <= radius_sq then
    rows[#rows + 1] = {
      actor = actor,
      address = address,
      distance = math.sqrt(d2),
      x = x,
      y = y,
    }
  end
end
table.sort(rows, function(a, b) return a.distance < b.distance end)
emit("count", #rows)
for index, row in ipairs(rows) do
  local actor = row.actor
  local prefix = "actor." .. tostring(index)
  emit(prefix .. ".address", string.format("0x%08X", row.address))
  emit(prefix .. ".type", actor.object_type_id or 0)
  emit(prefix .. ".enemy_type", actor.enemy_type or -1)
  emit(prefix .. ".tracked_enemy", actor.tracked_enemy and 1 or 0)
  emit(prefix .. ".dead", actor.dead and 1 or 0)
  emit(prefix .. ".hp", string.format("%.3f", tonumber(actor.hp) or 0))
  emit(prefix .. ".max_hp", string.format("%.3f", tonumber(actor.max_hp) or 0))
  emit(prefix .. ".anim_drive_state", actor.anim_drive_state or 0)
  emit(prefix .. ".death_handled", death_handled(row.address))
  emit(prefix .. ".x", string.format("%.3f", row.x))
  emit(prefix .. ".y", string.format("%.3f", row.y))
  emit(prefix .. ".distance", string.format("%.3f", row.distance))
end
"""


def parse_actor_rows(raw: dict[str, str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    count = int(number(raw, "count"))
    for index in range(1, count + 1):
        prefix = f"actor.{index}."
        row = {
            key[len(prefix):]: value
            for key, value in raw.items()
            if key.startswith(prefix)
        }
        if row:
            rows.append(row)
    return rows


def nearby_actors(pipe_name: str, x: float, y: float, radius: float) -> dict[str, Any]:
    raw = values(
        pipe_name,
        NEARBY_ACTORS_LUA
        .replace("__X__", f"{x:.6f}")
        .replace("__Y__", f"{y:.6f}")
        .replace("__RADIUS__", f"{radius:.6f}"),
    )
    return {
        "count": int(number(raw, "count")),
        "actors": parse_actor_rows(raw),
    }


def capture_pair(label: str, x: float, y: float, radius: float) -> dict[str, Any]:
    return {
        "label": label,
        "host": nearby_actors(HOST_PIPE, x, y, radius),
        "client": nearby_actors(CLIENT_PIPE, x, y, radius),
    }


def run_probe(radius: float, keep_open: bool) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": False}
    try:
        stop_games()
        result["launch"] = launch_pair()
        disable_bots()
        result["run_entry"] = start_host_testrun_and_wait_for_clients()
        result["start_waves"] = start_host_waves()
        result["snapshot"] = wait_for_run_snapshot(require_complete_lifecycle=True)
        result["initial_host_vitals"] = set_local_player_vitals(HOST_PIPE, TEST_PLAYER_HP, TEST_PLAYER_HP)
        result["initial_client_vitals"] = set_local_player_vitals(CLIENT_PIPE, TEST_PLAYER_HP, TEST_PLAYER_HP)

        result["damage"] = damage_client_enemy("damage")
        result["host_damage_accept"] = wait_for_host_enemy_hp(
            result["damage"],
            number(result["damage"], "target_hp"),
        )

        target = select_client_enemy(result["damage"]["network_actor_id"])
        result["selected_target"] = target
        result["move_client_near"] = move_client_near(target)
        time.sleep(0.6)

        x = number(target, "x")
        y = number(target, "y")
        samples = [capture_pair("before_kill", x, y, radius)]
        host_log_before = log_offset(HOST_LOG)
        result["kill"] = damage_client_enemy("kill", target["network_actor_id"])
        result["client_death_handled"] = wait_for_client_enemy_death_handled(
            result["kill"]["network_actor_id"],
            result["kill"]["local_actor_address"],
            timeout=4.0,
        )

        for delay in (0.05, 0.15, 0.35, 0.75, 1.25, 2.0):
            time.sleep(delay)
            samples.append(capture_pair(f"after_{delay:.2f}s", x, y, radius))
        result["samples"] = samples
        result["host_log_after_kill"] = read_log_since(HOST_LOG, host_log_before)
        result["ok"] = True
        return result
    finally:
        if not keep_open:
            stop_games()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--radius", type=float, default=192.0)
    parser.add_argument("--keep-open", action="store_true")
    args = parser.parse_args()

    result: dict[str, Any]
    try:
        result = run_probe(args.radius, args.keep_open)
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
        if not args.keep_open:
            stop_games()

    RUNTIME_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "ok": result.get("ok", False),
        "output": str(RUNTIME_OUTPUT),
        "selected_target": result.get("selected_target"),
        "kill": result.get("kill"),
        "client_death_handled": result.get("client_death_handled"),
        "sample_labels": [sample.get("label") for sample in result.get("samples", [])],
        "error": result.get("error"),
    }, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
