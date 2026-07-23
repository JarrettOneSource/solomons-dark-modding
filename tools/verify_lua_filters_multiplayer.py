#!/usr/bin/env python3
"""Verify the complete Lua filter registry is process-local across a pair."""

from __future__ import annotations

import argparse
import json
import math
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
OUTPUT = ROOT / "runtime" / "lua_filters_multiplayer_verification.json"
ACCEPTANCE_MOD_ID = "sample.lua.filter_acceptance_lab"
FILTER_NAMES = (
    "damage.dealing",
    "damage.taken",
    "enemy.spawning",
    "drop.rolling",
    "wave.spawning",
    "spell.casting",
    "xp.gaining",
    "gold.changing",
)
FILTER_KEYS = {
    "damage.dealing": "damage_dealing_count",
    "damage.taken": "damage_taken_count",
    "enemy.spawning": "enemy_spawning_count",
    "drop.rolling": "drop_rolling_count",
    "wave.spawning": "wave_spawning_count",
    "spell.casting": "spell_casting_count",
    "xp.gaining": "xp_gaining_count",
    "gold.changing": "gold_changing_count",
}


CONTRACT_PROBE = r"""
if _G.__sd_filter_multiplayer_acceptance ~= nil then
  error("filter acceptance is already registered; restart the disposable process")
end

local mod = assert(sd.runtime.get_mod())
local multiplayer = assert(sd.runtime.get_multiplayer_state())
local scene = assert(sd.world.get_scene(), "live scene required")
local owner_count = 0
local owner_participant_id = ""
for _, participant in ipairs(multiplayer.participants or {}) do
  if participant.is_owner then
    owner_count = owner_count + 1
    owner_participant_id = tostring(participant.participant_id or "")
  end
end

local unsupported_ok = pcall(
  sd.events.filter, "sample.unsupported", function() end)
local empty_name_ok = pcall(
  sd.events.filter, "", function() end)
local nonfunction_ok = pcall(
  sd.events.filter, "damage.dealing", {})

local filter_names = {
  "damage.dealing",
  "damage.taken",
  "enemy.spawning",
  "drop.rolling",
  "wave.spawning",
  "spell.casting",
  "xp.gaining",
  "gold.changing",
}
local acceptance = {
  counts = {},
  total = 0,
  trace = {},
  xp_event = "",
  xp_participant_id = "",
  xp_amount = 0,
  xp_current = -1,
  xp_source = "",
  xp_native_scaling = false,
}
for _, name in ipairs(filter_names) do
  acceptance.counts[name] = 0
  local captured_name = name
  assert(sd.events.filter(captured_name, function(event)
    acceptance.counts[captured_name] =
      acceptance.counts[captured_name] + 1
    acceptance.total = acceptance.total + 1
    acceptance.trace[#acceptance.trace + 1] = captured_name
    if captured_name == "xp.gaining" then
      acceptance.xp_event = tostring(event.event or "")
      acceptance.xp_participant_id =
        tostring(event.participant_id or "")
      acceptance.xp_amount = tonumber(event.amount) or 0
      acceptance.xp_current = tonumber(event.current_xp) or -1
      acceptance.xp_source = tostring(event.source or "")
      acceptance.xp_native_scaling =
        event.native_scaling == true
    end
    return nil
  end))
end
_G.__sd_filter_multiplayer_acceptance = acceptance

print("mod_id=" .. tostring(mod.id))
print("filter_function=" .. tostring(type(sd.events.filter) == "function"))
print("damage_capability=" .. tostring(
  sd.runtime.has_capability("events.filters.damage")))
print("enemy_spawn_capability=" .. tostring(
  sd.runtime.has_capability("events.filters.enemy_spawn")))
print("drop_roll_capability=" .. tostring(
  sd.runtime.has_capability("events.filters.drop_roll")))
print("wave_spawn_capability=" .. tostring(
  sd.runtime.has_capability("events.filters.wave_spawn")))
print("spell_cast_capability=" .. tostring(
  sd.runtime.has_capability("events.filters.spell_cast")))
print("resources_capability=" .. tostring(
  sd.runtime.has_capability("events.filters.resources")))
print("transport_enabled=" .. tostring(multiplayer.transport_enabled))
print("transport_ready=" .. tostring(multiplayer.transport_ready))
print("authority=" .. tostring(sd.state.is_authority()))
print("world_scene=" .. tostring(scene.name or scene.kind))
print("participant_count=" .. tostring(multiplayer.participant_count))
print("participant_rows=" .. tostring(#(multiplayer.participants or {})))
print("owner_count=" .. tostring(owner_count))
print("owner_participant_id=" .. owner_participant_id)
print("registered_count=" .. tostring(#filter_names))
print("registered_names=" .. table.concat(filter_names, ","))
print("initial_total=" .. tostring(acceptance.total))
print("unsupported_rejected=" .. tostring(not unsupported_ok))
print("empty_name_rejected=" .. tostring(not empty_name_ok))
print("nonfunction_rejected=" .. tostring(not nonfunction_ok))
"""


STATE_PROBE = r"""
local acceptance = _G.__sd_filter_multiplayer_acceptance
local multiplayer = assert(sd.runtime.get_multiplayer_state())
local scene = assert(sd.world.get_scene(), "live scene required")
local owner_count = 0
local owner_participant_id = ""
for _, participant in ipairs(multiplayer.participants or {}) do
  if participant.is_owner then
    owner_count = owner_count + 1
    owner_participant_id = tostring(participant.participant_id or "")
  end
end

print("present=" .. tostring(acceptance ~= nil))
print("authority=" .. tostring(sd.state.is_authority()))
print("world_scene=" .. tostring(scene.name or scene.kind))
print("participant_count=" .. tostring(multiplayer.participant_count))
print("participant_rows=" .. tostring(#(multiplayer.participants or {})))
print("owner_count=" .. tostring(owner_count))
print("owner_participant_id=" .. owner_participant_id)
print("damage_dealing_count=" .. tostring(
  acceptance and acceptance.counts["damage.dealing"] or 0))
print("damage_taken_count=" .. tostring(
  acceptance and acceptance.counts["damage.taken"] or 0))
print("enemy_spawning_count=" .. tostring(
  acceptance and acceptance.counts["enemy.spawning"] or 0))
print("drop_rolling_count=" .. tostring(
  acceptance and acceptance.counts["drop.rolling"] or 0))
print("wave_spawning_count=" .. tostring(
  acceptance and acceptance.counts["wave.spawning"] or 0))
print("spell_casting_count=" .. tostring(
  acceptance and acceptance.counts["spell.casting"] or 0))
print("xp_gaining_count=" .. tostring(
  acceptance and acceptance.counts["xp.gaining"] or 0))
print("gold_changing_count=" .. tostring(
  acceptance and acceptance.counts["gold.changing"] or 0))
print("total=" .. tostring(acceptance and acceptance.total or 0))
print("trace=" .. tostring(
  acceptance and table.concat(acceptance.trace, ",") or ""))
print("xp_event=" .. tostring(acceptance and acceptance.xp_event or ""))
print("xp_participant_id=" .. tostring(
  acceptance and acceptance.xp_participant_id or ""))
print("xp_amount=" .. tostring(acceptance and acceptance.xp_amount or 0))
print("xp_current=" .. tostring(acceptance and acceptance.xp_current or -1))
print("xp_source=" .. tostring(acceptance and acceptance.xp_source or ""))
print("xp_native_scaling=" .. tostring(
  acceptance and acceptance.xp_native_scaling or false))
"""


QUEUE_ZERO_XP_PROBE = r"""
local queued, err, serial =
  sd.debug.queue_native_experience_gain_probe(0.0, false)
print("queued=" .. tostring(queued))
print("error=" .. tostring(err or ""))
print("serial=" .. tostring(serial or 0))
"""


NATIVE_XP_RESULT_PROBE = r"""
local completed, success, before_xp, after_xp, seh, err =
  sd.debug.get_native_experience_gain_probe_result(%d)
print("completed=" .. tostring(completed))
print("success=" .. tostring(success))
print("before_xp=" .. tostring(before_xp or 0))
print("after_xp=" .. tostring(after_xp or 0))
print("seh=" .. tostring(seh or 0))
print("error=" .. tostring(err or ""))
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


def _finite_number(values: dict[str, str], name: str) -> float:
    try:
        value = float(values.get(name, "nan"))
    except ValueError as error:
        raise RuntimeError(
            f"Lua probe returned non-numeric {name}: {values.get(name)!r}"
        ) from error
    if not math.isfinite(value):
        raise RuntimeError(
            f"Lua probe returned non-finite {name}: {values.get(name)!r}"
        )
    return value


def contract_matches(
    values: dict[str, str],
    *,
    authority: bool,
    participant_id: int,
) -> bool:
    return (
        values.get("mod_id") == ACCEPTANCE_MOD_ID
        and all(
            values.get(name) == "true"
            for name in (
                "filter_function",
                "damage_capability",
                "enemy_spawn_capability",
                "drop_roll_capability",
                "wave_spawn_capability",
                "spell_cast_capability",
                "resources_capability",
                "transport_enabled",
                "transport_ready",
            )
        )
        and values.get("authority") == ("true" if authority else "false")
        and values.get("world_scene") == "hub"
        and values.get("participant_count") == "2"
        and values.get("participant_rows") == "2"
        and values.get("owner_count") == "1"
        and values.get("owner_participant_id") == str(participant_id)
        and values.get("registered_count") == str(len(FILTER_NAMES))
        and values.get("registered_names") == ",".join(FILTER_NAMES)
        and values.get("initial_total") == "0"
        and values.get("unsupported_rejected") == "true"
        and values.get("empty_name_rejected") == "true"
        and values.get("nonfunction_rejected") == "true"
    )


def state_matches(
    values: dict[str, str],
    *,
    authority: bool,
    participant_id: int,
    xp_count: int,
) -> bool:
    try:
        if (
            values.get("present") != "true"
            or values.get("authority")
            != ("true" if authority else "false")
            or values.get("world_scene") != "hub"
            or values.get("participant_count") != "2"
            or values.get("participant_rows") != "2"
            or values.get("owner_count") != "1"
            or values.get("owner_participant_id") != str(participant_id)
            or values.get("total") != str(xp_count)
            or values.get("trace")
            != ("xp.gaining" if xp_count == 1 else "")
        ):
            return False
        for filter_name, key in FILTER_KEYS.items():
            expected = xp_count if filter_name == "xp.gaining" else 0
            if values.get(key) != str(expected):
                return False
        if xp_count == 0:
            return (
                values.get("xp_event") == ""
                and values.get("xp_participant_id") == ""
                and _finite_number(values, "xp_amount") == 0.0
                and _finite_number(values, "xp_current") == -1.0
                and values.get("xp_source") == ""
                and values.get("xp_native_scaling") == "false"
            )
        return (
            xp_count == 1
            and values.get("xp_event") == "xp.gaining"
            and values.get("xp_participant_id") == str(participant_id)
            and _finite_number(values, "xp_amount") == 0.0
            and _finite_number(values, "xp_current") >= 0.0
            and values.get("xp_source") == "script"
            and values.get("xp_native_scaling") == "false"
        )
    except RuntimeError:
        return False


def queue_matches(values: dict[str, str]) -> bool:
    try:
        serial = int(values.get("serial", "0"))
    except ValueError:
        return False
    return (
        values.get("queued") == "true"
        and values.get("error") == ""
        and serial > 0
    )


def native_result_matches(values: dict[str, str]) -> bool:
    try:
        before_xp = _finite_number(values, "before_xp")
        after_xp = _finite_number(values, "after_xp")
    except RuntimeError:
        return False
    return (
        values.get("completed") == "true"
        and values.get("success") == "true"
        and values.get("seh") == "0"
        and values.get("error") == ""
        and before_xp == after_xp
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
    participant_id: int,
    xp_count: int,
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
            and state_matches(
                values,
                authority=authority,
                participant_id=participant_id,
                xp_count=xp_count,
            )
        ):
            return last
        time.sleep(0.05)
    raise RuntimeError(
        f"{description} did not converge for {client[0]}: {last}"
    )


def _queue_zero_xp(
    client: tuple[str, str],
    *,
    timeout: float,
) -> dict[str, Any]:
    queued = _require_action(
        client,
        QUEUE_ZERO_XP_PROBE,
        queue_matches,
        "zero-delta native XP queue",
    )
    serial = int(_values(queued)["serial"])
    deadline = time.monotonic() + timeout
    result: dict[str, Any] = {}
    while time.monotonic() < deadline:
        result = _run_probe(client, NATIVE_XP_RESULT_PROBE % serial)
        values = _values(result)
        if values.get("completed") == "true":
            if not native_result_matches(values):
                raise RuntimeError(
                    "zero-delta native XP result failed: "
                    f"queue={queued} result={result}"
                )
            return {"queue": queued, "result": result}
        time.sleep(0.02)
    raise RuntimeError(
        "zero-delta native XP result did not complete: "
        f"queue={queued} result={result}"
    )


def run(
    clients: list[tuple[str, str]],
    *,
    launch: bool,
    confirm_zero_xp_probe: bool,
    timeout: float,
) -> dict[str, Any]:
    if not launch:
        raise RuntimeError("Lua filter acceptance requires --launch-pair")
    if not confirm_zero_xp_probe:
        raise RuntimeError(
            "Lua filter acceptance requires --confirm-zero-xp-probe"
        )
    if len(clients) != 2:
        raise RuntimeError("exactly one host and one client endpoint are required")
    host, client = clients
    result: dict[str, Any] = {
        "ok": False,
        "launched_pair": True,
        "neutral_probe_confirmed": True,
        "host": host[0],
        "client": client[0],
        "exact_mod_id": ACCEPTANCE_MOD_ID,
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

        result["contract"] = [
            _require_action(
                host,
                CONTRACT_PROBE,
                lambda values: contract_matches(
                    values,
                    authority=True,
                    participant_id=HOST_ID,
                ),
                "host filter registry contract",
            ),
            _require_action(
                client,
                CONTRACT_PROBE,
                lambda values: contract_matches(
                    values,
                    authority=False,
                    participant_id=CLIENT_ID,
                ),
                "client filter registry contract",
            ),
        ]
        result["initial"] = [
            _poll_state(
                host,
                authority=True,
                participant_id=HOST_ID,
                xp_count=0,
                timeout=timeout,
                description="host empty filter registry counters",
            ),
            _poll_state(
                client,
                authority=False,
                participant_id=CLIENT_ID,
                xp_count=0,
                timeout=timeout,
                description="client empty filter registry counters",
            ),
        ]

        result["host_zero_xp"] = _queue_zero_xp(host, timeout=timeout)
        result["host_only"] = [
            _poll_state(
                host,
                authority=True,
                participant_id=HOST_ID,
                xp_count=1,
                timeout=timeout,
                description="host owner-local XP filter callback",
            ),
            _poll_state(
                client,
                authority=False,
                participant_id=CLIENT_ID,
                xp_count=0,
                timeout=timeout,
                description="client isolation from host XP filter callback",
            ),
        ]

        result["client_zero_xp"] = _queue_zero_xp(client, timeout=timeout)
        result["independent_owner_callbacks"] = [
            _poll_state(
                host,
                authority=True,
                participant_id=HOST_ID,
                xp_count=1,
                timeout=timeout,
                description="host retained one local XP filter callback",
            ),
            _poll_state(
                client,
                authority=False,
                participant_id=CLIENT_ID,
                xp_count=1,
                timeout=timeout,
                description="client owner-local XP filter callback",
            ),
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
        "--confirm-zero-xp-probe",
        action="store_true",
        help="confirm a zero-delta native XP call on each disposable peer",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    if not args.launch_pair:
        result["error"] = "Lua filter acceptance requires --launch-pair"
        return_code = 2
    elif not args.confirm_zero_xp_probe:
        result["error"] = (
            "Lua filter acceptance requires --confirm-zero-xp-probe"
        )
        return_code = 2
    else:
        try:
            result = run(
                args.client or list(DEFAULT_CLIENTS),
                launch=True,
                confirm_zero_xp_probe=True,
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
