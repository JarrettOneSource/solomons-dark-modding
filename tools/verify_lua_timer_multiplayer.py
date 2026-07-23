#!/usr/bin/env python3
"""Verify presentation-local Lua timers across a disposable pair."""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from multiplayer_lua_probe import DEFAULT_CLIENTS, parse_client, run_lua_client
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    CLIENT_PIPE,
    HOST_ID,
    HOST_NAME,
    HOST_PIPE,
    disable_bots,
    game_process_ids,
    launch_pair,
    stop_game_processes,
    wait_for_remote,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_timer_multiplayer_verification.json"
ACCEPTANCE_MOD_ID = "sample.lua.timer_lab"
HOST_LABEL = "host-timer-state"
CLIENT_LABEL = "client-timer-state"


STATE_PROBE = """
local mod = assert(sd.runtime.get_mod())
local multiplayer = assert(sd.runtime.get_multiplayer_state())
local scene = assert(sd.world.get_scene(), "live scene required")
local owner_count = 0
for _, participant in ipairs(multiplayer.participants or {}) do
  if participant.is_owner then owner_count = owner_count + 1 end
end
local namespace_count = 0
local namespace_exact = true
for name, value in pairs(sd.timer) do
  namespace_count = namespace_count + 1
  if (name ~= "after" and name ~= "every" and name ~= "sequence" and
      name ~= "cancel" and name ~= "clear") or
      type(value) ~= "function" then
    namespace_exact = false
  end
end
namespace_exact = namespace_exact and namespace_count == 5
local state = _G.__sd_timer_multiplayer_acceptance
print("mod_id=" .. tostring(mod.id))
print("timer_capability=" .. tostring(
  sd.runtime.has_capability("timer.local.scheduler")))
print("authority=" .. tostring(sd.state.is_authority()))
print("world_scene=" .. tostring(scene.name or scene.kind))
print("participant_count=" .. tostring(multiplayer.participant_count))
print("participant_rows=" .. tostring(#(multiplayer.participants or {})))
print("owner_count=" .. tostring(owner_count))
print("namespace_exact=" .. tostring(namespace_exact))
print("ready=" .. tostring(type(state) == "table"))
print("label=" .. tostring(state and state.label or ""))
print("after_count=" .. tostring(state and state.after_count or -1))
print("repeating_count=" .. tostring(
  state and state.repeating_count or -1))
print("sequence_order=" .. tostring(
  state and state.sequence_order or ""))
print("cancelled_count=" .. tostring(
  state and state.cancelled_count or -1))
print("error_count=" .. tostring(state and state.error_count or -1))
print("spawned_count=" .. tostring(state and state.spawned_count or -1))
print("hold_count=" .. tostring(state and state.hold_count or -1))
print("released=" .. tostring(state and state.released or false))
print("clear_count=" .. tostring(state and state.clear_count or -1))
"""


RESET_PROBE = """
local cleared = sd.timer.clear()
_G.__sd_timer_multiplayer_acceptance = nil
print("reset=true")
print("cleared=" .. tostring(cleared))
"""


RELEASE_PROBE = """
local state = assert(_G.__sd_timer_multiplayer_acceptance)
local first = sd.timer.clear()
local second = sd.timer.clear()
state.released = true
state.clear_count = first
print("first=" .. tostring(first))
print("second=" .. tostring(second))
print("released=" .. tostring(state.released))
"""


CAPACITY_PROBE = """
sd.timer.clear()
local handles = {}
for index = 1, 256 do
  handles[index] = sd.timer.after(86400000, function() end)
end
local overflow_ok = pcall(
  sd.timer.after, 86400000, function() end)
local ids_valid = true
for index, handle in ipairs(handles) do
  if type(handle) ~= "number" or math.type(handle) ~= "integer" or
      handle <= 0 or (index > 1 and handle <= handles[index - 1]) then
    ids_valid = false
  end
end
local cleared = sd.timer.clear()
print("overflow_rejected=" .. tostring(not overflow_ok))
print("ids_valid=" .. tostring(ids_valid))
print("cleared=" .. tostring(cleared))
"""


def _setup_probe(label: str) -> str:
    return f"""
local precleared = sd.timer.clear()
local state = {{
  label = {json.dumps(label)},
  after_count = 0,
  repeating_count = 0,
  sequence_order = "",
  cancelled_count = 0,
  error_count = 0,
  spawned_count = 0,
  hold_count = 0,
  released = false,
  clear_count = -1,
}}
_G.__sd_timer_multiplayer_acceptance = state

local after_id = sd.timer.after(80, function()
  state.after_count = state.after_count + 1
  sd.timer.after(0, function()
    state.spawned_count = state.spawned_count + 1
  end)
end)

local repeating_id
repeating_id = sd.timer.every(40, function()
  state.repeating_count = state.repeating_count + 1
  if state.repeating_count == 3 then
    assert(sd.timer.cancel(repeating_id))
  end
end)

local sequence_id = sd.timer.sequence({{
  {{ delay_ms = 25, callback = function()
      state.sequence_order = state.sequence_order .. "A"
    end }},
  {{ delay_ms = 25, callback = function()
      state.sequence_order = state.sequence_order .. "B"
    end }},
  {{ delay_ms = 25, callback = function()
      state.sequence_order = state.sequence_order .. "C"
    end }},
}})

local cancelled_id = sd.timer.after(75, function()
  state.cancelled_count = state.cancelled_count + 1
end)
local cancel_first = sd.timer.cancel(cancelled_id)
local cancel_second = sd.timer.cancel(cancelled_id)

local error_id = sd.timer.every(20, function()
  state.error_count = state.error_count + 1
  error("expected multiplayer timer acceptance failure")
end)
local hold_id = sd.timer.every(86400000, function()
  state.hold_count = state.hold_count + 1
end)

local empty_sequence_ok = pcall(sd.timer.sequence, {{}})
local zero_every_ok = pcall(sd.timer.every, 0, function() end)
local negative_after_ok = pcall(sd.timer.after, -1, function() end)
local fractional_after_ok = pcall(sd.timer.after, 1.5, function() end)
local bad_callback_ok = pcall(sd.timer.after, 1, true)
local bad_cancel_ok = pcall(sd.timer.cancel, 0)
local too_many = {{}}
for index = 1, 65 do
  too_many[index] = {{delay_ms = 0, callback = function() end}}
end
local too_many_ok = pcall(sd.timer.sequence, too_many)
local cumulative_ok = pcall(sd.timer.sequence, {{
  {{delay_ms = 43200001, callback = function() end}},
  {{delay_ms = 43200001, callback = function() end}},
}})

local ids = {{
  after_id, repeating_id, sequence_id, cancelled_id, error_id, hold_id,
}}
local ids_valid = true
for index, handle in ipairs(ids) do
  if type(handle) ~= "number" or math.type(handle) ~= "integer" or
      handle <= 0 or (index > 1 and handle <= ids[index - 1]) then
    ids_valid = false
  end
end

print("scheduled=true")
print("label=" .. tostring(state.label))
print("precleared=" .. tostring(precleared))
print("ids_valid=" .. tostring(ids_valid))
print("cancel_first=" .. tostring(cancel_first))
print("cancel_second=" .. tostring(cancel_second))
print("empty_sequence_rejected=" .. tostring(not empty_sequence_ok))
print("zero_every_rejected=" .. tostring(not zero_every_ok))
print("negative_after_rejected=" .. tostring(not negative_after_ok))
print("fractional_after_rejected=" .. tostring(not fractional_after_ok))
print("bad_callback_rejected=" .. tostring(not bad_callback_ok))
print("bad_cancel_rejected=" .. tostring(not bad_cancel_ok))
print("too_many_rejected=" .. tostring(not too_many_ok))
print("cumulative_rejected=" .. tostring(not cumulative_ok))
"""


def _failed_exec(result: dict[str, Any]) -> str | None:
    if result.get("returncode") == 0:
        return None
    return str(
        result.get("stderr") or result.get("stdout") or "Lua exec failed"
    ).strip()


def _values(result: dict[str, Any]) -> dict[str, str]:
    values = result.get("values", {})
    if not isinstance(values, dict):
        raise RuntimeError(f"Lua probe returned invalid values: {result}")
    return values


def _int_value(values: dict[str, str], name: str) -> int:
    try:
        return int(values.get(name, ""))
    except ValueError as error:
        raise RuntimeError(f"invalid {name}: {values}") from error


def timer_state_matches(
    values: dict[str, str],
    *,
    authority: bool,
    label: str | None,
    released: bool,
) -> bool:
    try:
        base_matches = (
            values.get("mod_id") == ACCEPTANCE_MOD_ID
            and values.get("timer_capability") == "true"
            and values.get("authority") == ("true" if authority else "false")
            and values.get("world_scene") == "hub"
            and _int_value(values, "participant_count") == 2
            and _int_value(values, "participant_rows") == 2
            and _int_value(values, "owner_count") == 1
            and values.get("namespace_exact") == "true"
        )
        if label is None:
            return (
                base_matches
                and values.get("ready") == "false"
                and values.get("label") == ""
                and values.get("released") == "false"
            )
        return (
            base_matches
            and values.get("ready") == "true"
            and values.get("label") == label
            and _int_value(values, "after_count") == 1
            and _int_value(values, "repeating_count") == 3
            and values.get("sequence_order") == "ABC"
            and _int_value(values, "cancelled_count") == 0
            and _int_value(values, "error_count") == 1
            and _int_value(values, "spawned_count") == 1
            and _int_value(values, "hold_count") == 0
            and values.get("released") == (
                "true" if released else "false"
            )
            and _int_value(values, "clear_count")
            == (1 if released else -1)
        )
    except RuntimeError:
        return False


def reset_matches(values: dict[str, str]) -> bool:
    try:
        return (
            values.get("reset") == "true"
            and _int_value(values, "cleared") >= 0
        )
    except RuntimeError:
        return False


def setup_matches(values: dict[str, str], *, label: str) -> bool:
    return (
        values.get("scheduled") == "true"
        and values.get("label") == label
        and values.get("precleared") == "0"
        and all(
            values.get(name) == "true"
            for name in (
                "ids_valid",
                "cancel_first",
                "empty_sequence_rejected",
                "zero_every_rejected",
                "negative_after_rejected",
                "fractional_after_rejected",
                "bad_callback_rejected",
                "bad_cancel_rejected",
                "too_many_rejected",
                "cumulative_rejected",
            )
        )
        and values.get("cancel_second") == "false"
    )


def release_matches(values: dict[str, str]) -> bool:
    return (
        values.get("first") == "1"
        and values.get("second") == "0"
        and values.get("released") == "true"
    )


def capacity_matches(values: dict[str, str]) -> bool:
    return (
        values.get("overflow_rejected") == "true"
        and values.get("ids_valid") == "true"
        and values.get("cleared") == "256"
    )


def _run_probe(
    client: tuple[str, str],
    code: str,
) -> dict[str, Any]:
    result = run_lua_client(client[0], client[1], code, timeout=12.0)
    failure = _failed_exec(result)
    if failure:
        raise RuntimeError(failure)
    return result


def _require_action(
    client: tuple[str, str],
    code: str,
    predicate: Callable[[dict[str, str]], bool],
    description: str,
) -> dict[str, Any]:
    result = _run_probe(client, code)
    if not predicate(_values(result)):
        raise RuntimeError(f"{description} failed: {result}")
    return result


def _poll_state(
    client: tuple[str, str],
    *,
    authority: bool,
    label: str | None,
    released: bool,
    timeout: float,
    description: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = run_lua_client(
            client[0],
            client[1],
            STATE_PROBE,
            timeout=12.0,
        )
        values = last.get("values", {})
        if (
            _failed_exec(last) is None
            and isinstance(values, dict)
            and timer_state_matches(
                values,
                authority=authority,
                label=label,
                released=released,
            )
        ):
            return last
        time.sleep(0.05)
    raise RuntimeError(
        f"{description} did not converge for {client[0]}: {last}"
    )


def run(
    clients: list[tuple[str, str]],
    *,
    launch: bool,
    timeout: float,
) -> dict[str, Any]:
    if not launch:
        raise RuntimeError("Lua timer acceptance requires --launch-pair")
    if len(clients) != 2:
        raise RuntimeError("exactly one host and one client endpoint are required")
    host, client = clients
    result: dict[str, Any] = {
        "ok": False,
        "launched_pair": True,
        "host": host[0],
        "client": client[0],
    }
    launched_process_ids: list[int] = []
    try:
        result["pair"] = launch_pair(
            tile_windows=False,
            kill_existing=False,
            exact_mod_id=ACCEPTANCE_MOD_ID,
        )
        launched_process_ids.extend(game_process_ids(result["pair"]))
        if len(set(launched_process_ids)) != 2:
            raise RuntimeError(
                "local pair did not report two exact process IDs: "
                f"{launched_process_ids}"
            )
        disable_bots()
        wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "hub")
        wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "hub")

        result["reset"] = [
            _require_action(
                peer,
                RESET_PROBE,
                reset_matches,
                "local timer reset",
            )
            for peer in (host, client)
        ]
        result["idle"] = [
            _poll_state(
                peer,
                authority=index == 0,
                label=None,
                released=False,
                timeout=timeout,
                description="empty local timer state",
            )
            for index, peer in enumerate((host, client))
        ]

        result["host_setup"] = _require_action(
            host,
            _setup_probe(HOST_LABEL),
            lambda values: setup_matches(values, label=HOST_LABEL),
            "host timer setup",
        )
        result["host_completion_isolation"] = [
            _poll_state(
                host,
                authority=True,
                label=HOST_LABEL,
                released=False,
                timeout=timeout,
                description="host timer completion",
            ),
            _poll_state(
                client,
                authority=False,
                label=None,
                released=False,
                timeout=timeout,
                description="client isolation from host timers",
            ),
        ]

        result["client_setup"] = _require_action(
            client,
            _setup_probe(CLIENT_LABEL),
            lambda values: setup_matches(values, label=CLIENT_LABEL),
            "client timer setup",
        )
        result["independent_completion"] = [
            _poll_state(
                host,
                authority=True,
                label=HOST_LABEL,
                released=False,
                timeout=timeout,
                description="host retained timer result",
            ),
            _poll_state(
                client,
                authority=False,
                label=CLIENT_LABEL,
                released=False,
                timeout=timeout,
                description="client timer completion",
            ),
        ]

        result["host_release"] = _require_action(
            host,
            RELEASE_PROBE,
            release_matches,
            "host timer release",
        )
        result["host_release_isolation"] = [
            _poll_state(
                host,
                authority=True,
                label=HOST_LABEL,
                released=True,
                timeout=timeout,
                description="host released timer state",
            ),
            _poll_state(
                client,
                authority=False,
                label=CLIENT_LABEL,
                released=False,
                timeout=timeout,
                description="client timer retained after host release",
            ),
        ]

        result["host_capacity"] = _require_action(
            host,
            CAPACITY_PROBE,
            capacity_matches,
            "host timer capacity",
        )
        result["capacity_isolation"] = [
            _poll_state(
                host,
                authority=True,
                label=HOST_LABEL,
                released=True,
                timeout=timeout,
                description="host timer state after capacity check",
            ),
            _poll_state(
                client,
                authority=False,
                label=CLIENT_LABEL,
                released=False,
                timeout=timeout,
                description="client timer retained during host capacity check",
            ),
        ]

        result["client_release"] = _require_action(
            client,
            RELEASE_PROBE,
            release_matches,
            "client timer release",
        )
        result["released"] = [
            _poll_state(
                peer,
                authority=index == 0,
                label=HOST_LABEL if index == 0 else CLIENT_LABEL,
                released=True,
                timeout=timeout,
                description="released local timer state",
            )
            for index, peer in enumerate((host, client))
        ]
        result["ok"] = True
        return result
    finally:
        stop_game_processes(launched_process_ids)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--client",
        action="append",
        type=parse_client,
        help="Lua endpoint as NAME=PIPE; provide exactly host then client.",
    )
    parser.add_argument(
        "--launch-pair",
        action="store_true",
        help="stage and launch the disposable local pair required by this verifier",
    )
    parser.add_argument(
        "--confirm-scheduling",
        action="store_true",
        help="confirm temporary local timer scheduling on the isolated pair",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    if not args.confirm_scheduling:
        result["error"] = (
            "refusing timer scheduling without --confirm-scheduling"
        )
        return_code = 2
    elif not args.launch_pair:
        result["error"] = "Lua timer acceptance requires --launch-pair"
        return_code = 2
    else:
        try:
            result = run(
                args.client or list(DEFAULT_CLIENTS),
                launch=True,
                timeout=max(1.0, args.timeout),
            )
            return_code = 0 if result.get("ok") else 1
        except Exception as error:  # noqa: BLE001 - preserve exact live evidence.
            result["error"] = str(error)
            return_code = 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
