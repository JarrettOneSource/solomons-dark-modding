#!/usr/bin/env python3
"""Verify Lua damage rewrites and cancellation through the retail hit handler."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from multiplayer_defense_behavior_harness import invoke_native_magic_hit_trial
from verify_local_multiplayer_sync import VerifyFailure, lua, parse_key_values


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_damage_filter_verification.json"
DEFAULT_PIPE = "SolomonDarkModLoader_LuaExec"
DAMAGE = 12.0

REGISTER_REWRITES = r"""
if __lua_damage_filter_acceptance_registered == true then
  error("damage filter acceptance is already registered; restart the disposable process")
end

__lua_damage_filter_acceptance_registered = true
__lua_damage_filter_dealing_count = 0
__lua_damage_filter_taken_count = 0
__lua_damage_filter_cancel_count = 0
__lua_damage_filter_trace = {}
__lua_damage_filter_dealing_input = 0
__lua_damage_filter_taken_input = 0
__lua_damage_filter_taken_total = 0

sd.events.filter("damage.dealing", function(event)
  __lua_damage_filter_dealing_count = __lua_damage_filter_dealing_count + 1
  __lua_damage_filter_trace[#__lua_damage_filter_trace + 1] = event.event
  __lua_damage_filter_dealing_input = event.projectile_damage
  return {lanes = {[1] = event.lanes[1] * 0.75}}
end)

sd.events.filter("damage.taken", function(event)
  __lua_damage_filter_taken_count = __lua_damage_filter_taken_count + 1
  __lua_damage_filter_trace[#__lua_damage_filter_trace + 1] = event.event
  __lua_damage_filter_taken_input = event.projectile_damage
  __lua_damage_filter_taken_total = event.total_damage
  return {projectile_damage = event.projectile_damage * (2.0 / 3.0)}
end)

print("registered=true")
print("capability=" .. tostring(sd.runtime.has_capability("events.filters.damage")))
"""

REGISTER_CANCEL = r"""
sd.events.filter("damage.taken", function(event)
  __lua_damage_filter_cancel_count = __lua_damage_filter_cancel_count + 1
  __lua_damage_filter_trace[#__lua_damage_filter_trace + 1] = "cancel"
  return false
end)
print("cancel_registered=true")
"""

RESET_TRACE = r"""
__lua_damage_filter_trace = {}
__lua_damage_filter_dealing_count = 0
__lua_damage_filter_taken_count = 0
__lua_damage_filter_cancel_count = 0
return true
"""

STATUS = r"""
print("dealing_count=" .. tostring(__lua_damage_filter_dealing_count or 0))
print("taken_count=" .. tostring(__lua_damage_filter_taken_count or 0))
print("cancel_count=" .. tostring(__lua_damage_filter_cancel_count or 0))
print("dealing_input=" .. tostring(__lua_damage_filter_dealing_input or 0))
print("taken_input=" .. tostring(__lua_damage_filter_taken_input or 0))
print("taken_total=" .. tostring(__lua_damage_filter_taken_total or 0))
print("trace=" .. table.concat(__lua_damage_filter_trace or {}, ","))
"""


def _float(values: dict[str, str], name: str) -> float:
    try:
        value = float(values.get(name, "nan"))
    except ValueError as exc:
        raise VerifyFailure(
            f"damage filter returned non-numeric {name}: {values.get(name)!r}"
        ) from exc
    if not math.isfinite(value):
        raise VerifyFailure(
            f"damage filter returned non-finite {name}: {values.get(name)!r}"
        )
    return value


def _require_near(actual: float, expected: float, label: str) -> None:
    if abs(actual - expected) > 0.001:
        raise VerifyFailure(
            f"damage filter {label} mismatch: expected={expected} actual={actual}"
        )


def _native_trial(
    pipe_name: str,
    label: str,
    *,
    require_life_loss: bool,
    timeout: float,
) -> dict[str, Any]:
    return invoke_native_magic_hit_trial(
        pipe_name,
        projectile_damage=DAMAGE,
        magic_damage=0.0,
        attempts=1,
        label=label,
        timeout=timeout,
        require_life_loss=require_life_loss,
    )


def run(pipe_name: str, timeout: float) -> dict[str, Any]:
    warmup_damage = _native_trial(
        pipe_name,
        "native defense warmup",
        require_life_loss=False,
        timeout=timeout,
    )
    baseline_damage = _native_trial(
        pipe_name,
        "unfiltered baseline",
        require_life_loss=True,
        timeout=timeout,
    )

    registration = parse_key_values(
        lua(pipe_name, REGISTER_REWRITES, timeout=12.0)
    )
    if registration.get("registered") != "true" or registration.get(
        "capability"
    ) != "true":
        raise VerifyFailure(f"damage filters failed to register: {registration}")

    lua(pipe_name, RESET_TRACE, timeout=8.0)
    rewritten_damage = _native_trial(
        pipe_name,
        "ordered rewrite",
        require_life_loss=True,
        timeout=timeout,
    )
    rewrite_status = parse_key_values(lua(pipe_name, STATUS, timeout=8.0))
    expected_rewrite_status = {
        "dealing_count": "1",
        "taken_count": "1",
        "cancel_count": "0",
        "trace": "damage.dealing,damage.taken",
    }
    mismatches = {
        key: {"expected": expected, "actual": rewrite_status.get(key)}
        for key, expected in expected_rewrite_status.items()
        if rewrite_status.get(key) != expected
    }
    if mismatches:
        raise VerifyFailure(f"damage filter ordered rewrite mismatch: {mismatches}")
    _require_near(_float(rewrite_status, "dealing_input"), DAMAGE, "dealing input")
    _require_near(
        _float(rewrite_status, "taken_input"),
        DAMAGE * 0.75,
        "taken chained input",
    )
    _require_near(
        _float(rewrite_status, "taken_total"),
        DAMAGE * 0.75,
        "taken chained total",
    )
    if rewritten_damage["hp_delta"] >= baseline_damage["hp_delta"] - 0.05:
        raise VerifyFailure(
            "ordered rewrite did not reduce actual native HP loss: "
            f"baseline={baseline_damage['hp_delta']} "
            f"rewritten={rewritten_damage['hp_delta']}"
        )

    cancel_registration = parse_key_values(
        lua(pipe_name, REGISTER_CANCEL, timeout=8.0)
    )
    if cancel_registration.get("cancel_registered") != "true":
        raise VerifyFailure(
            f"damage cancellation failed to register: {cancel_registration}"
        )
    lua(pipe_name, RESET_TRACE, timeout=8.0)
    canceled_damage = _native_trial(
        pipe_name,
        "cancellation",
        require_life_loss=False,
        timeout=timeout,
    )
    cancel_status = parse_key_values(lua(pipe_name, STATUS, timeout=8.0))
    expected_cancel_status = {
        "dealing_count": "1",
        "taken_count": "1",
        "cancel_count": "1",
        "trace": "damage.dealing,damage.taken,cancel",
    }
    mismatches = {
        key: {"expected": expected, "actual": cancel_status.get(key)}
        for key, expected in expected_cancel_status.items()
        if cancel_status.get(key) != expected
    }
    if mismatches:
        raise VerifyFailure(f"damage filter cancellation mismatch: {mismatches}")
    if abs(canceled_damage["hp_delta"]) > 0.001:
        raise VerifyFailure(
            "canceled native hit changed HP: "
            f"delta={canceled_damage['hp_delta']}"
        )

    return {
        "ok": True,
        "pipe": pipe_name,
        "input_damage": DAMAGE,
        "warmup_damage": warmup_damage,
        "registration": registration,
        "baseline_damage": baseline_damage,
        "rewritten_damage": rewritten_damage,
        "rewrite_status": rewrite_status,
        "cancel_registration": cancel_registration,
        "canceled_damage": canceled_damage,
        "cancel_status": cancel_status,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipe", default=DEFAULT_PIPE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False, "pipe": args.pipe}
    try:
        result = run(args.pipe, args.timeout)
        return_code = 0
    except Exception as exc:  # noqa: BLE001 - persist exact live evidence.
        result["error"] = str(exc)
        return_code = 1

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
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
