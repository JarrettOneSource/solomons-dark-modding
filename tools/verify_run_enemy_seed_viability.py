#!/usr/bin/env python3
"""Verify whether stock run enemies stay deterministic across two local clients."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from multiplayer_lua_probe import DEFAULT_CLIENTS, run_all  # noqa: E402
from verify_hub_student_seed_viability import (  # noqa: E402
    CLIENT_PIPE,
    HOST_PIPE,
    VerifyFailure,
    disable_bots,
    launch_isolated_pair,
    stop_games,
)
from verify_local_multiplayer_sync import lua, parse_key_values, wait_for_scene  # noqa: E402


RUNTIME_OUTPUT = ROOT / "runtime" / "run_enemy_seed_viability.json"


LUA_CAPTURE = r"""
local function emit(k, v)
  print(k .. "=" .. tostring(v))
end

local function hx(v)
  return string.format("0x%08X", tonumber(v) or 0)
end

local function f(v)
  if v == nil then return "nil" end
  return string.format("%.3f", tonumber(v) or 0)
end

local function u32(address)
  return tonumber(sd.debug.read_u32(address)) or 0
end

local scene = sd.world.get_scene()
local world = sd.world.get_state and sd.world.get_state() or nil
emit("scene.kind", scene and scene.kind or "")
emit("scene.name", scene and scene.name or "")
emit("scene.world", scene and hx(scene.world_address) or "0x00000000")
emit("world.wave", world and (world.wave or 0) or 0)
emit("rng.global_818b08", hx(u32(0x00818B08)))

local actors = sd.world.list_actors() or {}
emit("actors.total", #actors)

local tracked = {}
for _, actor in ipairs(actors) do
  local type_id = tonumber(actor.object_type_id) or 0
  local hp = tonumber(actor.hp) or 0
  local max_hp = tonumber(actor.max_hp) or 0
  if actor.tracked_enemy and type_id ~= 0 and type_id ~= 1 and max_hp > 0 then
    table.insert(tracked, actor)
  end
end

table.sort(tracked, function(a, b)
  local ax = tonumber(a.x) or 0
  local bx = tonumber(b.x) or 0
  if math.abs(ax - bx) > 0.001 then return ax < bx end
  local ay = tonumber(a.y) or 0
  local by = tonumber(b.y) or 0
  if math.abs(ay - by) > 0.001 then return ay < by end
  return (tonumber(a.actor_address) or 0) < (tonumber(b.actor_address) or 0)
end)

local live = 0
local dead = 0
local counts = {}
for index, actor in ipairs(tracked) do
  local type_id = tonumber(actor.object_type_id) or 0
  local hp = tonumber(actor.hp) or 0
  local max_hp = tonumber(actor.max_hp) or 0
  counts[type_id] = (counts[type_id] or 0) + 1
  if actor.dead or hp <= 0 then
    dead = dead + 1
  else
    live = live + 1
  end
  if index <= 12 then
    local prefix = "enemy." .. tostring(index)
    emit(prefix .. ".type", type_id)
    emit(prefix .. ".enemy_type", actor.enemy_type)
    emit(prefix .. ".slot", actor.world_slot)
    emit(prefix .. ".x", f(actor.x))
    emit(prefix .. ".y", f(actor.y))
    emit(prefix .. ".heading", f(actor.heading))
    emit(prefix .. ".drive", actor.anim_drive_state)
    emit(prefix .. ".hp", f(hp))
    emit(prefix .. ".max_hp", f(max_hp))
    emit(prefix .. ".dead", actor.dead)
  end
end

for type_id, count in pairs(counts) do
  emit("count.type." .. tostring(type_id), count)
end
emit("tracked.total", #tracked)
emit("tracked.live", live)
emit("tracked.dead", dead)
"""


def parallel_values(code: str, timeout: float = 10.0) -> dict[str, dict[str, str]]:
    results = run_all(list(DEFAULT_CLIENTS), code, timeout)
    failures = [
        f"{result['name']} rc={result['returncode']} stderr={result['stderr']}"
        for result in results
        if int(result["returncode"]) != 0
    ]
    if failures:
        raise VerifyFailure("parallel Lua command failed: " + "; ".join(failures))
    return {
        str(result["name"]): {str(k): str(v) for k, v in dict(result["values"]).items()}
        for result in results
    }


def require_parallel_ok(step: str, code: str, timeout: float = 10.0) -> dict[str, dict[str, str]]:
    values_by_client = parallel_values(code, timeout)
    bad = {
        name: values
        for name, values in values_by_client.items()
        if values.get("ok") != "true"
    }
    if bad:
        raise VerifyFailure(f"{step} failed: {bad}")
    return values_by_client


def wait_for_tracked_enemies(timeout: float) -> dict[str, dict[str, str]]:
    deadline = time.monotonic() + timeout
    last: dict[str, dict[str, str]] = {}
    while time.monotonic() < deadline:
        last = parallel_values(LUA_CAPTURE, timeout=10.0)
        if all(int(float(values.get("tracked.total", "0") or "0")) > 0 for values in last.values()):
            return last
        time.sleep(0.25)
    raise VerifyFailure(f"timed out waiting for both clients to create tracked run enemies: {last}")


def collect_samples(samples: int, interval: float, timeout: float) -> list[dict[str, object]]:
    collected: list[dict[str, object]] = []
    for index in range(max(samples, 1)):
        values_by_client = parallel_values(LUA_CAPTURE, timeout)
        collected.append(
            {
                "index": index,
                "clients": [
                    {"name": name, "values": values}
                    for name, values in sorted(values_by_client.items())
                ],
            }
        )
        if index + 1 < samples:
            time.sleep(max(interval, 0.0))
    return collected


def integer(values: dict[str, str], key: str, default: int = 0) -> int:
    try:
        return int(float(values.get(key, default)))
    except (TypeError, ValueError):
        return default


def first_sample_values(samples: list[dict[str, object]]) -> dict[str, dict[str, str]]:
    if not samples:
        return {}
    clients = samples[0].get("clients")
    if not isinstance(clients, list):
        return {}
    by_name: dict[str, dict[str, str]] = {}
    for client in clients:
        if not isinstance(client, dict):
            continue
        name = str(client.get("name", ""))
        values = client.get("values")
        if name and isinstance(values, dict):
            by_name[name] = {str(k): str(v) for k, v in values.items()}
    return by_name


def client_sample_series(samples: list[dict[str, object]], key: str) -> dict[str, list[str]]:
    series: dict[str, list[str]] = {}
    for sample in samples:
        clients = sample.get("clients")
        if not isinstance(clients, list):
            continue
        for client in clients:
            if not isinstance(client, dict):
                continue
            name = str(client.get("name", ""))
            values = client.get("values")
            if name and isinstance(values, dict):
                series.setdefault(name, []).append(str(values.get(key, "")))
    return series


def enemy_signature(values: dict[str, str], limit: int = 8) -> list[dict[str, str]]:
    count = min(integer(values, "tracked.total"), limit)
    return [
        {
            "type": values.get(f"enemy.{index}.type", ""),
            "x": values.get(f"enemy.{index}.x", ""),
            "y": values.get(f"enemy.{index}.y", ""),
            "heading": values.get(f"enemy.{index}.heading", ""),
            "drive": values.get(f"enemy.{index}.drive", ""),
            "hp": values.get(f"enemy.{index}.hp", ""),
            "max_hp": values.get(f"enemy.{index}.max_hp", ""),
        }
        for index in range(1, count + 1)
    ]


def evaluate(samples: list[dict[str, object]]) -> dict[str, object]:
    first = first_sample_values(samples)
    host = first.get("host", {})
    client = first.get("client", {})

    rng_host = host.get("rng.global_818b08", "")
    rng_client = client.get("rng.global_818b08", "")
    rng_diverged = bool(rng_host and rng_client and rng_host != rng_client)
    tracked_count_diverged = host.get("tracked.total", "") != client.get("tracked.total", "")
    live_count_diverged = host.get("tracked.live", "") != client.get("tracked.live", "")

    signatures = {
        "host": enemy_signature(host),
        "client": enemy_signature(client),
    }
    enemy_signature_diverged = json.dumps(signatures["host"], sort_keys=True) != json.dumps(
        signatures["client"],
        sort_keys=True,
    )
    tracked_series = client_sample_series(samples, "tracked.total")
    live_series = client_sample_series(samples, "tracked.live")
    count_sequence_diverged = len({json.dumps(values) for values in tracked_series.values()}) > 1
    live_sequence_diverged = len({json.dumps(values) for values in live_series.values()}) > 1
    divergent = (
        rng_diverged or
        tracked_count_diverged or
        live_count_diverged or
        enemy_signature_diverged or
        count_sequence_diverged or
        live_sequence_diverged
    )

    return {
        "stock_run_enemy_lockstep_viable": not divergent,
        "global_seed_as_primary_sync_recommended": False,
        "divergent": divergent,
        "reasons": {
            "rng_global_818b08_diverged": rng_diverged,
            "tracked_count_diverged": tracked_count_diverged,
            "live_count_diverged": live_count_diverged,
            "enemy_signature_diverged": enemy_signature_diverged,
            "tracked_count_sequence_diverged": count_sequence_diverged,
            "live_count_sequence_diverged": live_sequence_diverged,
        },
        "first_sample": {
            "host_rng_global_818b08": rng_host,
            "client_rng_global_818b08": rng_client,
            "host_tracked_enemies": host.get("tracked.total", ""),
            "client_tracked_enemies": client.get("tracked.total", ""),
            "host_live_enemies": host.get("tracked.live", ""),
            "client_live_enemies": client.get("tracked.live", ""),
            "host_wave": host.get("world.wave", ""),
            "client_wave": client.get("world.wave", ""),
        },
        "tracked_count_series": tracked_series,
        "live_count_series": live_series,
        "first_enemy_signatures": signatures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=6)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--lua-timeout", type=float, default=10.0)
    parser.add_argument("--launch-timeout", type=float, default=240.0)
    parser.add_argument("--enemy-timeout", type=float, default=45.0)
    parser.add_argument("--preset", default="map_create_fire_mind_hub")
    parser.add_argument("--skip-launch", action="store_true")
    parser.add_argument("--keep-running", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    output: dict[str, object] = {"ok": False}
    try:
        if not args.skip_launch:
            output["launch"] = launch_isolated_pair(args.preset, args.launch_timeout)
        output["bots_disabled"] = disable_bots()
        output["start_testrun"] = require_parallel_ok(
            "start_testrun",
            "print('ok=' .. tostring(sd.hub.start_testrun()))",
            timeout=args.lua_timeout,
        )
        wait_for_scene(HOST_PIPE, "testrun")
        wait_for_scene(CLIENT_PIPE, "testrun")
        output["start_waves"] = require_parallel_ok(
            "start_waves",
            "print('ok=' .. tostring(sd.gameplay.start_waves()))",
            timeout=args.lua_timeout,
        )
        output["enemy_ready"] = wait_for_tracked_enemies(args.enemy_timeout)
        samples = collect_samples(args.samples, args.interval, args.lua_timeout)
        decision = evaluate(samples)
        output = {
            "ok": True,
            "decision": decision,
            "samples": samples,
        }
        RUNTIME_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_OUTPUT.write_text(json.dumps(output, indent=2, sort_keys=True), encoding="utf-8")
        if args.json:
            print(json.dumps(output, indent=2, sort_keys=True))
        else:
            print(json.dumps({"ok": output["ok"], "decision": decision}, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        output["error"] = str(exc)
        RUNTIME_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_OUTPUT.write_text(json.dumps(output, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(output, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    finally:
        if not args.keep_running:
            stop_games()


if __name__ == "__main__":
    raise SystemExit(main())
