#!/usr/bin/env python3
"""Verify that native skill-picker visuals are built from the authoritative offer IDs."""

from __future__ import annotations

import argparse
import json
import time
import traceback
from pathlib import Path
from typing import Any

from verify_local_multiplayer_sync import CLIENT_PIPE, VerifyFailure, stop_games
from verify_multiplayer_fireball_explode_effect_sync import launch_pair_ready
from verify_multiplayer_level_up_offer_sync import (
    choose_client_option,
    publish_offer,
    query_progression_stats,
    wait_for_choice_result,
    wait_for_client_offer,
)
from verify_multiplayer_primary_kill_stress import parse_int, values


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "runtime/multiplayer_skill_picker_visual_identity.json"
SKILL_VISUAL_IDENTITY_BUILDER = 0x00657C00
SKILL_VISUAL_IDENTITY_RETURN = 0x0066FE0E
TRACE_NAME = "multiplayer.skill_picker.visual_identity"


ARM_TRACE_LUA = f"""
pcall(sd.debug.untrace_function, {SKILL_VISUAL_IDENTITY_BUILDER})
sd.debug.clear_trace_hits({json.dumps(TRACE_NAME)})
local ok = sd.debug.trace_function(
  {SKILL_VISUAL_IDENTITY_BUILDER},
  {json.dumps(TRACE_NAME)})
print("ok=" .. tostring(ok))
print("error=" .. tostring(sd.debug.get_last_error and sd.debug.get_last_error() or ""))
"""


QUERY_TRACE_LUA = f"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local expected_return = sd.debug.resolve_game_address({SKILL_VISUAL_IDENTITY_RETURN}) or 0
local hits = sd.debug.get_trace_hits({json.dumps(TRACE_NAME)}) or {{}}
local count = 0
emit("resolved_return", expected_return)
emit("total_hit_count", #hits)
for _, hit in ipairs(hits) do
  if (tonumber(hit.ret) or 0) == expected_return then
    count = count + 1
    -- FUN_00657C00 is cdecl(out_string, option_id). The screen's return
    -- address proves this ID was consumed while building a visible option.
    emit("visual." .. tostring(count) .. ".option_id", tonumber(hit.arg1) or -1)
    emit("visual." .. tostring(count) .. ".return", tonumber(hit.ret) or 0)
  end
end
emit("visual_count", count)
"""


CLEAR_TRACE_LUA = f"""
local ok = sd.debug.untrace_function({SKILL_VISUAL_IDENTITY_BUILDER})
sd.debug.clear_trace_hits({json.dumps(TRACE_NAME)})
print("ok=" .. tostring(ok))
"""


def wait_for_visual_ids(expected_count: int, timeout: float) -> tuple[dict[str, str], list[int]]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = values(CLIENT_PIPE, QUERY_TRACE_LUA)
        visual_count = parse_int(last.get("visual_count"))
        if visual_count >= expected_count:
            visual_ids = [
                parse_int(last.get(f"visual.{index}.option_id"), -1)
                for index in range(1, visual_count + 1)
            ]
            return last, visual_ids[-expected_count:]
        time.sleep(0.05)
    raise VerifyFailure(
        "native skill-picker visual builder did not consume the offered option count: "
        f"expected={expected_count} last={last}"
    )


def run_verifier(timeout: float) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": False}
    result["startup"] = launch_pair_ready(timeout, manual_combat=False)
    client_stats = query_progression_stats(CLIENT_PIPE)
    if not client_stats["available"]:
        raise VerifyFailure(f"client progression unavailable: {client_stats}")
    target_level = client_stats["level"] + 1
    target_experience = int(max(client_stats["next_xp_threshold"], 125.0) + 10.0)
    result["target"] = {
        "level": target_level,
        "experience": target_experience,
        "client_before": client_stats,
    }

    result["trace_arm"] = values(CLIENT_PIPE, ARM_TRACE_LUA)
    if result["trace_arm"].get("ok") != "true":
        raise VerifyFailure(f"failed to arm picker visual identity trace: {result['trace_arm']}")

    result["publish"] = publish_offer(target_level, target_experience)
    result["offer"] = wait_for_client_offer(target_level, timeout)
    offered_ids = [int(option_id) for option_id in result["offer"]["option_ids"]]
    result["trace"], result["visual_option_ids"] = wait_for_visual_ids(
        len(offered_ids), timeout
    )
    result["offered_option_ids"] = offered_ids
    result["picker_option_ids"] = [
        parse_int(
            result["offer"]["raw"].get(f"picker.option.{index}.id"),
            -1,
        )
        for index in range(1, len(offered_ids) + 1)
    ]

    if result["picker_option_ids"] != offered_ids:
        raise VerifyFailure(
            "pinned picker selection IDs differ from the authoritative offer: "
            f"offer={offered_ids} picker={result['picker_option_ids']}"
        )
    if result["visual_option_ids"] != offered_ids:
        raise VerifyFailure(
            "native picker visuals were built from different skill IDs than the authoritative offer: "
            f"offer={offered_ids} visuals={result['visual_option_ids']} "
            f"pinned_picker={result['picker_option_ids']}"
        )

    result["choice"] = choose_client_option(result["offer"]["offer_id"], 1)
    result["choice_result"] = wait_for_choice_result(
        result["offer"]["offer_id"],
        target_level,
        timeout,
    )
    if result["choice_result"]["result_option_id"] != offered_ids[0]:
        raise VerifyFailure(
            "accepted picker choice did not apply the visualized authoritative option: "
            f"expected={offered_ids[0]} result={result['choice_result']}"
        )
    if result["choice_result"]["local_picker_screen"] != 0:
        raise VerifyFailure(
            "accepted authoritative choice left the native picker open: "
            f"result={result['choice_result']}"
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
        try:
            result["trace_clear"] = values(CLIENT_PIPE, CLEAR_TRACE_LUA, timeout=3.0)
        except Exception as exc:
            result["trace_clear"] = {"error": str(exc)}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))
        if not args.keep_open:
            stop_games()
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
