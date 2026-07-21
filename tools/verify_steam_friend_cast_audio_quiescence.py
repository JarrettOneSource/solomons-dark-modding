#!/usr/bin/env python3
"""Verify that idle remote participants do not restart native cast audio."""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from collections import Counter
from pathlib import Path
from typing import Any

import verify_multiplayer_primary_kill_stress as primary
from steam_friend_active_pair import (
    CLIENT_ENDPOINT,
    HOST_ENDPOINT,
    ROOT,
    SteamFriendActivePair,
)
from verify_local_multiplayer_sync import VerifyFailure, parse_key_values
from verify_steam_friend_active_pair_spell_behavior import (
    configure_behavior_modules,
    verify_targetless_air,
)


DEFAULT_OUTPUT = ROOT / "runtime/steam_friend_cast_audio_quiescence.json"
NATIVE_SOUND_START_ADDRESS = 0x00407B70
TRACE_NAME = "multiplayer_idle_remote_sound_start"


def values(
    pair: SteamFriendActivePair,
    endpoint: str,
    code: str,
    *,
    timeout: float = 8.0,
) -> dict[str, str]:
    return parse_key_values(pair.lua(endpoint, code, timeout=timeout))


def remote_idle_state(
    pair: SteamFriendActivePair,
    endpoint: str,
    participant_id: int,
) -> dict[str, str]:
    state = values(
        pair,
        endpoint,
        f"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local bot = sd.bots and sd.bots.get_participant_state and
  sd.bots.get_participant_state({participant_id}) or nil
local input = sd.input and sd.input.get_mouse_left_state and
  sd.input.get_mouse_left_state() or nil
emit("found", bot ~= nil)
emit("actor", bot and bot.actor_address or 0)
emit("cast_pending", bot and bot.cast_pending or false)
emit("cast_active", bot and bot.cast_active or false)
emit("cast_skill_id", bot and bot.cast_skill_id or 0)
emit("input_down", input and input.down or false)
""",
    )
    if state.get("found") != "true" or int(state.get("actor", "0"), 0) == 0:
        raise VerifyFailure(
            f"remote participant {participant_id} is not materialized: {state}"
        )
    if state.get("cast_pending") == "true" or state.get("cast_active") == "true":
        raise VerifyFailure(
            f"remote participant {participant_id} is not idle: {state}"
        )
    if state.get("input_down") == "true":
        raise VerifyFailure(f"local primary input is still down: {state}")
    return state


def arm_trace(pair: SteamFriendActivePair, endpoint: str) -> dict[str, str]:
    result = values(
        pair,
        endpoint,
        f"""
pcall(sd.debug.untrace_function, {NATIVE_SOUND_START_ADDRESS})
pcall(sd.debug.clear_trace_hits, "{TRACE_NAME}")
local ok = sd.debug.trace_function({NATIVE_SOUND_START_ADDRESS}, "{TRACE_NAME}")
print("ok=" .. tostring(ok))
print("error=" .. tostring(sd.debug.get_last_error and sd.debug.get_last_error() or ""))
""",
    )
    if result.get("ok") != "true":
        raise VerifyFailure(f"failed to arm native sound-start trace: {result}")
    return result


def disarm_trace(pair: SteamFriendActivePair, endpoint: str) -> None:
    pair.lua(
        endpoint,
        f"sd.debug.untrace_function({NATIVE_SOUND_START_ADDRESS})",
        timeout=8.0,
    )


def trace_summary(
    pair: SteamFriendActivePair,
    endpoint: str,
    remote_actor: int,
) -> dict[str, Any]:
    raw = pair.lua(
        endpoint,
        f"""
local hits = sd.debug.get_trace_hits("{TRACE_NAME}") or {{}}
print("count=" .. tostring(#hits))
for index, hit in ipairs(hits) do
  print("hit." .. index .. ".actor=" .. tostring(hit.esi or 0))
  print("hit." .. index .. ".caller=" .. tostring(hit.ret or 0))
end
""",
        timeout=8.0,
    )
    parsed = parse_key_values(raw)
    count = int(parsed.get("count", "0"), 0)
    callers: Counter[int] = Counter()
    remote_hits = 0
    for index in range(1, count + 1):
        actor = int(parsed.get(f"hit.{index}.actor", "0"), 0)
        caller = int(parsed.get(f"hit.{index}.caller", "0"), 0)
        if actor == remote_actor:
            remote_hits += 1
            callers[caller] += 1
    return {
        "total_sound_start_calls": count,
        "remote_actor_sound_start_calls": remote_hits,
        "remote_actor_callers": {
            f"0x{caller:08X}": hit_count
            for caller, hit_count in sorted(callers.items())
        },
    }


def run(pair: SteamFriendActivePair, idle_seconds: float) -> dict[str, Any]:
    discovered = pair.discover()
    if (
        discovered["host"]["scene"] != "testrun"
        or discovered["client"]["scene"] != "testrun"
    ):
        raise VerifyFailure(
            f"Steam friend pair is not in a shared test run: {discovered}"
        )
    configure_behavior_modules(pair)

    result: dict[str, Any] = {
        "ok": False,
        "pair": discovered,
        "idle_seconds": idle_seconds,
        "native_sound_start_address": f"0x{NATIVE_SOUND_START_ADDRESS:08X}",
    }
    result["arena_cleanup"] = primary.cleanup_live_enemies()
    result["input_quiescence"] = primary.quiesce_gameplay_primary_input(
        "steam_friend_cast_audio_quiescence"
    )

    observers = {
        "host_observes_client": (
            HOST_ENDPOINT,
            pair.client_participant_id,
        ),
        "client_observes_host": (
            CLIENT_ENDPOINT,
            pair.host_participant_id,
        ),
    }
    armed_endpoints: list[str] = []
    try:
        result["before"] = {}
        for label, (endpoint, participant_id) in observers.items():
            state = remote_idle_state(pair, endpoint, participant_id)
            result["before"][label] = state
            result.setdefault("trace_arm", {})[label] = arm_trace(pair, endpoint)
            armed_endpoints.append(endpoint)

        time.sleep(idle_seconds)

        result["idle_window"] = {}
        failures: dict[str, dict[str, Any]] = {}
        for label, (endpoint, participant_id) in observers.items():
            remote_actor = int(result["before"][label]["actor"], 0)
            summary = trace_summary(pair, endpoint, remote_actor)
            summary["remote_state_after"] = remote_idle_state(
                pair,
                endpoint,
                participant_id,
            )
            result["idle_window"][label] = summary
            if summary["remote_actor_sound_start_calls"] != 0:
                failures[label] = summary

        if failures:
            raise VerifyFailure(
                "idle remote participants restarted native cast audio: "
                f"{failures}"
            )
    finally:
        for endpoint in armed_endpoints:
            try:
                disarm_trace(pair, endpoint)
            except Exception:
                pass

    result["ok"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--idle-seconds", type=float, default=2.0)
    parser.add_argument(
        "--exercise-client-targetless-air",
        action="store_true",
        help="verify idle audio before and after one native client Air cast",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.idle_seconds <= 0.0 or args.idle_seconds > 5.0:
        parser.error("--idle-seconds must be greater than 0 and at most 5")

    pair = SteamFriendActivePair()
    result: dict[str, Any] = {"ok": False}
    return_code = 1
    try:
        if args.exercise_client_targetless_air:
            result["initial_idle"] = run(pair, args.idle_seconds)
            result["targetless_air"] = verify_targetless_air(
                pair,
                owner="client",
            )
            result["post_targetless_air_idle"] = run(pair, args.idle_seconds)
            result["ok"] = True
        else:
            result = run(pair, args.idle_seconds)
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
                    "idle_window": result.get("idle_window"),
                    "initial_idle_window": result.get("initial_idle", {}).get(
                        "idle_window"
                    ),
                    "post_targetless_air_idle_window": result.get(
                        "post_targetless_air_idle", {}
                    ).get("idle_window"),
                    "output": str(args.output),
                },
                indent=2,
                sort_keys=True,
            )
        )
    return return_code


if __name__ == "__main__":
    sys.exit(main())
