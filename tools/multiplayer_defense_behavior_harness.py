#!/usr/bin/env python3
"""Safe exact-native helpers for multiplayer defense-stat verification."""

from __future__ import annotations

import math
import time
from typing import Any

from multiplayer_progression_probe import query_progression_snapshot
from verify_local_multiplayer_sync import (
    VerifyFailure,
    lua,
    parse_int_text,
    parse_key_values,
)


def invoke_native_magic_hit_trial(
    pipe_name: str,
    *,
    projectile_damage: float,
    magic_damage: float,
    attempts: int,
    label: str,
    timeout: float,
    require_life_loss: bool = True,
) -> dict[str, Any]:
    """Queue the retail PlayerActor magic-hit handler after Lua returns."""

    if not math.isfinite(projectile_damage) or projectile_damage < 0.0:
        raise ValueError(
            f"projectile_damage must be finite and non-negative, got {projectile_damage}"
        )
    if not math.isfinite(magic_damage) or magic_damage < 0.0:
        raise ValueError(
            f"magic_damage must be finite and non-negative, got {magic_damage}"
        )
    if projectile_damage <= 0.0 and magic_damage <= 0.0:
        raise ValueError("at least one native magic-hit damage lane must be positive")
    if attempts < 1 or attempts > 1000:
        raise ValueError(f"attempts must be in [1,1000], got {attempts}")

    code = f"""
local function emit(key, value)
  if value == nil then value = '<nil>' end
  print(key .. '=' .. tostring(value))
end
local queued, err, serial = sd.debug.queue_native_magic_hit_behavior_probe(
  {projectile_damage:.9f}, {magic_damage:.9f}, {attempts})
emit('queued', queued)
emit('error', err or '')
emit('serial', serial or 0)
emit('ok', queued == true)
"""
    raw = parse_key_values(lua(pipe_name, code, timeout=15.0))
    request_serial = parse_int_text(raw.get("serial"), 0)
    if raw.get("ok") != "true" or request_serial == 0:
        raise VerifyFailure(f"native magic-damage trial failed to queue {label}: {raw}")

    deadline = time.monotonic() + timeout
    result: dict[str, str] = {}
    while time.monotonic() < deadline:
        result_code = f"""
local function emit(key, value)
  if value == nil then value = '<nil>' end
  print(key .. '=' .. tostring(value))
end
local completed, success, hp_before, hp_after, err =
  sd.debug.get_native_magic_hit_behavior_probe_result({request_serial})
emit('completed', completed)
emit('success', success)
emit('hp_before', hp_before)
emit('hp_after', hp_after)
emit('error', err or '')
"""
        result = parse_key_values(lua(pipe_name, result_code, timeout=15.0))
        if result.get("completed") == "true":
            break
        time.sleep(0.02)
    else:
        raise VerifyFailure(
            f"native magic-hit trial did not complete {label}: "
            f"serial={request_serial} result={result} queue={raw}"
        )
    if result.get("success") != "true":
        raise VerifyFailure(
            f"native magic-hit trial failed {label}: "
            f"serial={request_serial} result={result} queue={raw}"
        )
    try:
        before = float(result.get("hp_before", "nan"))
        after = float(result.get("hp_after", "nan"))
    except ValueError:
        before = math.nan
        after = math.nan
    invalid_life = (
        not math.isfinite(before)
        or not math.isfinite(after)
        or after > before
        or (require_life_loss and after >= before)
    )
    if invalid_life:
        raise VerifyFailure(
            f"native magic-hit trial returned invalid life {label}: {result}"
        )

    return {
        "label": label,
        "request_serial": request_serial,
        "projectile_damage": projectile_damage,
        "magic_damage": magic_damage,
        "attempts": attempts,
        "require_life_loss": require_life_loss,
        "hp_before": before,
        "hp_after": after,
        "hp_delta": before - after,
        "queue_raw": raw,
        "result_raw": result,
    }


def wait_for_observer_life(
    observer_pipe: str,
    participant_id: int,
    expected: float,
    timeout: float,
    tolerance: float = 0.1,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = query_progression_snapshot(observer_pipe, participant_id=participant_id)
        actual = float(last["runtime"]["life_current"])
        if math.isfinite(actual) and abs(actual - expected) <= tolerance:
            return {
                "expected": expected,
                "actual": actual,
                "life_max": float(last["runtime"]["life_max"]),
                "error": abs(actual - expected),
            }
        time.sleep(0.05)
    raise VerifyFailure(
        f"observer life did not converge participant={participant_id} "
        f"expected={expected:.3f}: {last}"
    )
