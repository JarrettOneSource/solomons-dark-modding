#!/usr/bin/env python3
"""Verify that moderate client enemy drift is reconciled without a hard visual snap."""

from __future__ import annotations

import argparse
import json
import math
import time
import traceback
from pathlib import Path
from typing import Any

from verify_local_multiplayer_sync import (
    CLIENT_PIPE,
    HOST_PIPE,
    VerifyFailure,
    place_player,
    stop_games,
)
from verify_multiplayer_fireball_explode_effect_sync import launch_pair_ready
from verify_multiplayer_primary_kill_stress import (
    cleanup_live_enemies,
    find_target,
    parse_int,
    spawn_one_enemy,
    values,
    wait_for_pair_transform_convergence,
)


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "runtime/multiplayer_enemy_soft_reconciliation.json"
ENEMY_POSITION = (1800.0, 1750.0)
HOST_POSITION = (650.0, 1750.0)
CLIENT_POSITION = (650.0, 2250.0)
INJECTED_DRIFT = 96.0
SAMPLE_COUNT = 24
MAX_CORRECTION_STEP = 48.0
CONVERGED_ERROR = 6.0


ARM_PROBE_LUA = r"""
local network_id = tonumber("__NETWORK_ID__") or 0
local authority_x = tonumber("__AUTHORITY_X__") or 0
local authority_y = tonumber("__AUTHORITY_Y__") or 0
local injected_drift = tonumber("__INJECTED_DRIFT__") or 0
local sample_limit = tonumber("__SAMPLE_COUNT__") or 24
local function emit(key, value) print(key .. "=" .. tostring(value)) end
_G.__sdmod_enemy_reconcile_probe = {
  active = true,
  network_id = network_id,
  authority_x = authority_x,
  authority_y = authority_y,
  injected_drift = injected_drift,
  sample_limit = sample_limit,
  samples = {},
  injected = false,
  actor_address = 0,
  error = "",
}
if not _G.__sdmod_enemy_reconcile_probe_registered then
  sd.events.on("runtime.tick", function(event)
    local probe = _G.__sdmod_enemy_reconcile_probe
    if type(probe) ~= "table" or not probe.active then return end
    local actor = sd.world.get_run_enemy_by_network_id and
      sd.world.get_run_enemy_by_network_id(probe.network_id) or nil
    local actor_address = tonumber(actor and actor.actor_address) or 0
    local x_offset = sd.debug.layout_offset("actor_position_x")
    local y_offset = sd.debug.layout_offset("actor_position_y")
    local target_offset = sd.debug.layout_offset("actor_current_target_actor")
    if actor_address == 0 or x_offset == nil or y_offset == nil then
      probe.error = "replicated enemy binding unavailable"
      return
    end
    probe.actor_address = actor_address
    if not probe.injected then
      local wrote_x = sd.debug.write_float(
        actor_address + x_offset,
        probe.authority_x + probe.injected_drift)
      local wrote_y = sd.debug.write_float(actor_address + y_offset, probe.authority_y)
      if not wrote_x or not wrote_y then
        probe.error = "failed to inject client transform drift"
        probe.active = false
        return
      end
      probe.injected = true
    end
    if target_offset ~= nil then
      sd.debug.write_ptr(actor_address + target_offset, 0)
    end
    local x = tonumber(sd.debug.read_float(actor_address + x_offset)) or 0
    local y = tonumber(sd.debug.read_float(actor_address + y_offset)) or 0
    local dx = x - probe.authority_x
    local dy = y - probe.authority_y
    probe.samples[#probe.samples + 1] = {
      x = x,
      y = y,
      error = math.sqrt(dx * dx + dy * dy),
      monotonic_ms = tonumber(event and event.monotonic_milliseconds) or 0,
    }
    if #probe.samples >= probe.sample_limit then probe.active = false end
  end)
  _G.__sdmod_enemy_reconcile_probe_registered = true
end
emit("registered", _G.__sdmod_enemy_reconcile_probe_registered)
emit("network_id", string.format("%.0f", network_id))
emit("active", _G.__sdmod_enemy_reconcile_probe.active)
"""


QUERY_PROBE_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local probe = _G.__sdmod_enemy_reconcile_probe
emit("valid", type(probe) == "table")
if type(probe) ~= "table" then return end
emit("active", probe.active or false)
emit("injected", probe.injected or false)
emit("actor_address", string.format("0x%08X", tonumber(probe.actor_address) or 0))
emit("error", probe.error or "")
emit("sample_count", #(probe.samples or {}))
for index, sample in ipairs(probe.samples or {}) do
  local prefix = "sample." .. tostring(index) .. "."
  emit(prefix .. "x", string.format("%.6f", tonumber(sample.x) or 0))
  emit(prefix .. "y", string.format("%.6f", tonumber(sample.y) or 0))
  emit(prefix .. "error", string.format("%.6f", tonumber(sample.error) or 0))
  emit(prefix .. "monotonic_ms", tonumber(sample.monotonic_ms) or 0)
end
"""


def parse_float(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def wait_for_samples(timeout: float) -> tuple[dict[str, str], list[dict[str, float]]]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = values(CLIENT_PIPE, QUERY_PROBE_LUA)
        if last.get("error"):
            raise VerifyFailure(f"enemy reconciliation probe failed: {last}")
        count = parse_int(last.get("sample_count"))
        if count >= SAMPLE_COUNT:
            samples = [
                {
                    "x": parse_float(last.get(f"sample.{index}.x")),
                    "y": parse_float(last.get(f"sample.{index}.y")),
                    "error": parse_float(last.get(f"sample.{index}.error")),
                    "monotonic_ms": parse_float(last.get(f"sample.{index}.monotonic_ms")),
                }
                for index in range(1, count + 1)
            ]
            return last, samples
        time.sleep(0.05)
    raise VerifyFailure(f"enemy reconciliation probe did not finish: {last}")


def analyze_samples(samples: list[dict[str, float]]) -> dict[str, Any]:
    errors = [sample["error"] for sample in samples]
    correction_steps = [abs(errors[index] - errors[index - 1]) for index in range(1, len(errors))]
    decreasing_steps = sum(
        1 for index in range(1, len(errors)) if errors[index] <= errors[index - 1] + 1.0
    )
    return {
        "initial_error": errors[0] if errors else math.inf,
        "final_error": errors[-1] if errors else math.inf,
        "max_correction_step": max(correction_steps, default=math.inf),
        "correction_step_count": sum(1 for step in correction_steps if step > 0.5),
        "mostly_monotonic": decreasing_steps >= max(1, len(errors) - 3),
        "correction_steps": correction_steps,
    }


def run_verifier(timeout: float) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": False}
    result["startup"] = launch_pair_ready(timeout, god_mode=False, manual_combat=True)
    result["cleanup"] = cleanup_live_enemies()
    result["placement"] = {
        "host": place_player(HOST_PIPE, *HOST_POSITION, 90.0),
        "client": place_player(CLIENT_PIPE, *CLIENT_POSITION, 90.0),
    }
    result["placement"]["convergence"] = wait_for_pair_transform_convergence(timeout=timeout)

    result["spawn"] = spawn_one_enemy(*ENEMY_POSITION, setup_hp=50000.0)
    network_id = parse_int(result["spawn"]["result"].get("network_actor_id"))
    if network_id == 0:
        raise VerifyFailure(f"manual enemy has no network id: {result['spawn']}")
    result["network_actor_id"] = network_id
    result["host_ready"] = find_target(
        HOST_PIPE,
        *ENEMY_POSITION,
        network_id,
        timeout,
        require_local_binding=False,
    )
    result["client_ready"] = find_target(CLIENT_PIPE, *ENEMY_POSITION, network_id, timeout)

    result["arm"] = values(
        CLIENT_PIPE,
        ARM_PROBE_LUA
        .replace("__NETWORK_ID__", str(network_id))
        .replace("__AUTHORITY_X__", f"{ENEMY_POSITION[0]:.3f}")
        .replace("__AUTHORITY_Y__", f"{ENEMY_POSITION[1]:.3f}")
        .replace("__INJECTED_DRIFT__", f"{INJECTED_DRIFT:.3f}")
        .replace("__SAMPLE_COUNT__", str(SAMPLE_COUNT)),
    )
    if result["arm"].get("registered") != "true":
        raise VerifyFailure(f"failed to arm enemy reconciliation probe: {result['arm']}")

    result["probe"], result["samples"] = wait_for_samples(timeout)
    result["analysis"] = analyze_samples(result["samples"])
    analysis = result["analysis"]
    if analysis["initial_error"] < INJECTED_DRIFT - 2.0:
        raise VerifyFailure(f"probe did not observe injected drift: {analysis}")
    if analysis["max_correction_step"] > MAX_CORRECTION_STEP:
        raise VerifyFailure(
            "replicated enemy used a visible hard correction: "
            f"limit={MAX_CORRECTION_STEP:.1f} analysis={analysis}"
        )
    if analysis["correction_step_count"] < 3:
        raise VerifyFailure(f"replicated enemy did not use multiple correction steps: {analysis}")
    if not analysis["mostly_monotonic"]:
        raise VerifyFailure(f"replicated enemy correction oscillated: {analysis}")
    if analysis["final_error"] > CONVERGED_ERROR:
        raise VerifyFailure(
            f"replicated enemy did not converge within {CONVERGED_ERROR:.1f} units: {analysis}"
        )
    result["ok"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=24.0)
    parser.add_argument("--keep-open", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    return_code = 1
    try:
        stop_games()
        result = run_verifier(args.timeout)
        return_code = 0
    except Exception as exc:
        result["error"] = str(exc)
        result["error_type"] = type(exc).__name__
        result["traceback"] = traceback.format_exc()
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))
        if not args.keep_open:
            stop_games()
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
