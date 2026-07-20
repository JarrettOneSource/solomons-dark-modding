#!/usr/bin/env python3
"""Verify that a bound client enemy replica never authors native movement."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import verify_local_multiplayer_sync as local_verify
import verify_multiplayer_primary_kill_stress as primary
from steam_friend_active_pair import CLIENT_ENDPOINT, HOST_ENDPOINT, ROOT, SteamFriendActivePair
from steam_friend_behavior_context import configure_behavior_context, reset_quiet_arena
from verify_local_multiplayer_sync import VerifyFailure, parse_key_values


DEFAULT_OUTPUT = ROOT / "runtime/steam_friend_enemy_motion_authority.json"
HOST_POSITION = (650.0, 1750.0)
CLIENT_POSITION = (650.0, 2250.0)
ENEMY_POSITION = (1800.0, 1750.0)
SAMPLE_COUNT = 240
WARMUP_COUNT = 12
MAXIMUM_LOCAL_ERROR = 3.0
MAXIMUM_SNAPSHOT_ERROR = 1.0


ARM_PROBE_LUA = r"""
local network_id = tonumber("__NETWORK_ID__") or 0
local authority_x = tonumber("__AUTHORITY_X__") or 0
local authority_y = tonumber("__AUTHORITY_Y__") or 0
local sample_limit = tonumber("__SAMPLE_COUNT__") or 240
local warmup_limit = tonumber("__WARMUP_COUNT__") or 12
local function distance(x, y)
  local dx = (tonumber(x) or 0) - authority_x
  local dy = (tonumber(y) or 0) - authority_y
  return math.sqrt(dx * dx + dy * dy)
end
local function emit(key, value) print(key .. "=" .. tostring(value)) end

_G.__sdmod_enemy_motion_authority_probe = {
  active = true,
  network_id = network_id,
  authority_x = authority_x,
  authority_y = authority_y,
  sample_limit = sample_limit,
  warmup_limit = warmup_limit,
  warmup_count = 0,
  samples = {},
  actor_address = 0,
  error = "",
}

if not _G.__sdmod_enemy_motion_authority_probe_registered then
  sd.events.on("runtime.tick", function(event)
    local probe = _G.__sdmod_enemy_motion_authority_probe
    if type(probe) ~= "table" or not probe.active then return end

    local replicated = sd.world.get_replicated_actors and
      sd.world.get_replicated_actors() or nil
    local snapshot = nil
    local local_address = 0
    for _, actor in ipairs(replicated and replicated.actors or {}) do
      if tonumber(actor.network_actor_id) == probe.network_id then
        snapshot = actor
        break
      end
    end
    for _, binding in ipairs(replicated and replicated.bindings or {}) do
      if tonumber(binding.network_actor_id) == probe.network_id and
          binding.matched and not binding.parked and not binding.removed then
        local_address = tonumber(binding.local_actor_address) or 0
        break
      end
    end

    local x_offset = sd.debug.layout_offset("actor_position_x")
    local y_offset = sd.debug.layout_offset("actor_position_y")
    if snapshot == nil or local_address == 0 or x_offset == nil or y_offset == nil then
      probe.warmup_count = 0
      return
    end

    local local_x = tonumber(sd.debug.read_float(local_address + x_offset))
    local local_y = tonumber(sd.debug.read_float(local_address + y_offset))
    if local_x == nil or local_y == nil then
      probe.error = "bound client enemy position is unreadable"
      probe.active = false
      return
    end

    local snapshot_error = distance(snapshot.x, snapshot.y)
    local local_error = distance(local_x, local_y)
    if probe.warmup_count < probe.warmup_limit then
      if snapshot_error <= 1.0 and local_error <= 3.0 then
        probe.warmup_count = probe.warmup_count + 1
      else
        probe.warmup_count = 0
      end
      return
    end

    probe.actor_address = local_address
    probe.samples[#probe.samples + 1] = {
      local_x = local_x,
      local_y = local_y,
      local_error = local_error,
      snapshot_x = tonumber(snapshot.x) or 0,
      snapshot_y = tonumber(snapshot.y) or 0,
      snapshot_error = snapshot_error,
      monotonic_ms = tonumber(event and event.monotonic_milliseconds) or 0,
    }
    if #probe.samples >= probe.sample_limit then probe.active = false end
  end)
  _G.__sdmod_enemy_motion_authority_probe_registered = true
end

emit("registered", _G.__sdmod_enemy_motion_authority_probe_registered)
emit("active", _G.__sdmod_enemy_motion_authority_probe.active)
"""


QUERY_PROBE_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local probe = _G.__sdmod_enemy_motion_authority_probe
emit("valid", type(probe) == "table")
if type(probe) ~= "table" then return end
emit("active", probe.active or false)
emit("error", probe.error or "")
emit("warmup_count", probe.warmup_count or 0)
emit("sample_count", #(probe.samples or {}))
for index, sample in ipairs(probe.samples or {}) do
  local prefix = "sample." .. tostring(index) .. "."
  emit(prefix .. "local_x", string.format("%.6f", sample.local_x or 0))
  emit(prefix .. "local_y", string.format("%.6f", sample.local_y or 0))
  emit(prefix .. "local_error", string.format("%.6f", sample.local_error or 0))
  emit(prefix .. "snapshot_x", string.format("%.6f", sample.snapshot_x or 0))
  emit(prefix .. "snapshot_y", string.format("%.6f", sample.snapshot_y or 0))
  emit(prefix .. "snapshot_error", string.format("%.6f", sample.snapshot_error or 0))
  emit(prefix .. "monotonic_ms", sample.monotonic_ms or 0)
end
"""


def integer(values: dict[str, str], key: str) -> int:
    try:
        return int(float(values.get(key, "0")))
    except (TypeError, ValueError):
        return 0


def floating(values: dict[str, str], key: str) -> float:
    try:
        return float(values.get(key, "nan"))
    except (TypeError, ValueError):
        return math.nan


def wait_for_samples(pair: SteamFriendActivePair, timeout: float) -> list[dict[str, float]]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = parse_key_values(pair.lua(CLIENT_ENDPOINT, QUERY_PROBE_LUA, timeout=12.0))
        if last.get("error"):
            raise VerifyFailure(f"enemy motion authority probe failed: {last['error']}")
        count = integer(last, "sample_count")
        if count >= SAMPLE_COUNT:
            return [
                {
                    field: floating(last, f"sample.{index}.{field}")
                    for field in (
                        "local_x",
                        "local_y",
                        "local_error",
                        "snapshot_x",
                        "snapshot_y",
                        "snapshot_error",
                        "monotonic_ms",
                    )
                }
                for index in range(1, count + 1)
            ]
        time.sleep(0.1)
    raise VerifyFailure(
        "enemy motion authority probe did not finish: "
        f"warmup={integer(last, 'warmup_count')} samples={integer(last, 'sample_count')}"
    )


def run(pair: SteamFriendActivePair, timeout: float) -> dict[str, Any]:
    discovered = pair.discover()
    if discovered["host"]["scene"] != "testrun" or discovered["client"]["scene"] != "testrun":
        raise VerifyFailure(f"Steam friend pair is not in a shared test run: {discovered}")
    configure_behavior_context(pair)

    result: dict[str, Any] = {
        "ok": False,
        "pair": discovered,
        "sample_count": SAMPLE_COUNT,
        "maximum_local_error": MAXIMUM_LOCAL_ERROR,
        "maximum_snapshot_error": MAXIMUM_SNAPSHOT_ERROR,
    }
    result["arena_reset"] = reset_quiet_arena()
    result["placement"] = {
        "host": local_verify.place_player(HOST_ENDPOINT, *HOST_POSITION, 90.0),
        "client": local_verify.place_player(CLIENT_ENDPOINT, *CLIENT_POSITION, 90.0),
    }
    result["placement"]["convergence"] = primary.wait_for_pair_transform_convergence(
        timeout=timeout
    )

    spawn = primary.spawn_one_enemy(*ENEMY_POSITION, setup_hp=50000.0, freeze_on_spawn=True)
    network_id = primary.parse_int(spawn["result"].get("network_actor_id"))
    primary.find_target(
        HOST_ENDPOINT,
        *ENEMY_POSITION,
        network_id,
        timeout,
        require_local_binding=False,
    )
    primary.find_target(CLIENT_ENDPOINT, *ENEMY_POSITION, network_id, timeout)
    result["spawn"] = {
        "type_id": primary.SKELETON_TYPE_ID,
        "x": ENEMY_POSITION[0],
        "y": ENEMY_POSITION[1],
        "hp": 50000.0,
        "host_frozen": True,
    }

    arm = parse_key_values(
        pair.lua(
            CLIENT_ENDPOINT,
            ARM_PROBE_LUA
            .replace("__NETWORK_ID__", str(network_id))
            .replace("__AUTHORITY_X__", f"{ENEMY_POSITION[0]:.3f}")
            .replace("__AUTHORITY_Y__", f"{ENEMY_POSITION[1]:.3f}")
            .replace("__SAMPLE_COUNT__", str(SAMPLE_COUNT))
            .replace("__WARMUP_COUNT__", str(WARMUP_COUNT)),
            timeout=12.0,
        )
    )
    if arm.get("registered") != "true" or arm.get("active") != "true":
        raise VerifyFailure(f"failed to arm enemy motion authority probe: {arm}")

    samples = wait_for_samples(pair, timeout)
    local_errors = [sample["local_error"] for sample in samples]
    snapshot_errors = [sample["snapshot_error"] for sample in samples]
    local_error_rises = [
        local_errors[index] - local_errors[index - 1]
        for index in range(1, len(local_errors))
    ]
    analysis = {
        "sample_count": len(samples),
        "maximum_local_error": max(local_errors, default=math.inf),
        "maximum_snapshot_error": max(snapshot_errors, default=math.inf),
        "maximum_local_error_rise": max(local_error_rises, default=0.0),
        "duration_ms": (
            samples[-1]["monotonic_ms"] - samples[0]["monotonic_ms"]
            if len(samples) >= 2
            else 0.0
        ),
    }
    result["analysis"] = analysis
    result["samples"] = samples
    if analysis["maximum_snapshot_error"] > MAXIMUM_SNAPSHOT_ERROR:
        raise VerifyFailure(f"host enemy authority moved during probe: {analysis}")
    if analysis["maximum_local_error"] > MAXIMUM_LOCAL_ERROR:
        raise VerifyFailure(f"client enemy replica authored native movement: {analysis}")
    result["ok"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    pair = SteamFriendActivePair()
    result: dict[str, Any] = {"ok": False}
    return_code = 1
    try:
        result = run(pair, args.timeout)
        return_code = 0
    except Exception as exc:
        result["error"] = str(exc)
        result["error_type"] = type(exc).__name__
        result["traceback"] = traceback.format_exc()
    finally:
        pair.close()
        result = pair.redact(result)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "ok": result.get("ok", False),
                    "error": result.get("error"),
                    "analysis": result.get("analysis"),
                    "output": str(args.output),
                },
                indent=2,
                sort_keys=True,
            )
        )
    return return_code


if __name__ == "__main__":
    sys.exit(main())
