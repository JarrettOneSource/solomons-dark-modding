#!/usr/bin/env python3
"""Verify authority-replicated Lua wave intelligence across a local pair."""

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
    start_host_testrun_and_wait_for_clients,
    stop_game_processes,
    wait_for_remote,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_waves_multiplayer_verification.json"
ACCEPTANCE_MOD_ID = "sample.lua.waves_lab"
WAVE_OVERRIDE = ROOT / "tests" / "fixtures" / "waves" / "lua_wave_filter_test.txt"
EXPECTED_FIRST_WAVE_BUDGET = 2
EXPECTED_SECOND_WAVE_BUDGET = 3


REGISTER_PROBE = f"""
local mod = assert(sd.runtime.get_mod())
assert(mod.id == "{ACCEPTANCE_MOD_ID}", "unexpected acceptance mod")
if not _G.__sdmod_waves_acceptance_registered then
  _G.__sdmod_waves_acceptance_event_count = 0
  _G.__sdmod_waves_acceptance_event_wave = 0
  _G.__sdmod_waves_acceptance_event_planned = 0
  _G.__sdmod_waves_acceptance_event_composition = ""
  sd.events.on("wave.started", function(event)
    local rows = {{}}
    for _, row in ipairs(event.composition or {{}}) do
      rows[#rows + 1] =
        tostring(row.enemy_type) .. ":" .. tostring(row.planned)
    end
    _G.__sdmod_waves_acceptance_event_count =
      _G.__sdmod_waves_acceptance_event_count + 1
    _G.__sdmod_waves_acceptance_event_wave = tonumber(event.wave) or 0
    _G.__sdmod_waves_acceptance_event_planned =
      tonumber(event.planned) or 0
    _G.__sdmod_waves_acceptance_event_composition =
      table.concat(rows, ",")
  end)
  _G.__sdmod_waves_acceptance_registered = true
end
print("mod_id=" .. tostring(mod.id))
print("registered=" .. tostring(
  _G.__sdmod_waves_acceptance_registered == true))
print("authority=" .. tostring(sd.state.is_authority()))
print("event_count=" .. tostring(
  _G.__sdmod_waves_acceptance_event_count or 0))
"""


SCHEDULE_PROBE = """
local schedule = sd.waves.get_schedule(2)
local signature = {}
local schedule_valid = type(schedule) == "table" and #schedule == 2
local raw_addresses_absent = true
local previous_wave = 0
for _, entry in ipairs(schedule or {}) do
  local planned = 0
  local previous_type = -1
  local rows = {}
  for _, row in ipairs(entry.composition or {}) do
    if (tonumber(row.enemy_type) or -1) <= previous_type then
      schedule_valid = false
    end
    previous_type = tonumber(row.enemy_type) or -1
    planned = planned + (tonumber(row.planned) or 0)
    rows[#rows + 1] =
      tostring(row.enemy_type) .. ":" .. tostring(row.planned)
    if row.actor_address ~= nil or row.config_address ~= nil then
      raw_addresses_absent = false
    end
  end
  if (tonumber(entry.wave) or 0) <= previous_wave or
      planned ~= (tonumber(entry.spawn_budget) or -1) or
      entry.random_group_projection ~= true then
    schedule_valid = false
  end
  previous_wave = tonumber(entry.wave) or 0
  if entry.spawner_address ~= nil or entry.arena_address ~= nil or
      entry.action_record_address ~= nil then
    raw_addresses_absent = false
  end
  signature[#signature + 1] = table.concat({
    tostring(entry.wave),
    tostring(entry.spawn_budget),
    tostring(entry.spawn_delay_min),
    tostring(entry.spawn_delay_max),
    tostring(entry.wave_delay_min),
    tostring(entry.wave_delay_max),
    tostring(entry.max_enemies),
    tostring(entry.zombie_wave),
    table.concat(rows, ","),
  }, ":")
end
local first = schedule and schedule[1] or nil
local second = schedule and schedule[2] or nil
local namespace_count = 0
local namespace_exact = true
for name, value in pairs(sd.waves) do
  namespace_count = namespace_count + 1
  if (name ~= "get_state" and name ~= "get_schedule") or
      type(value) ~= "function" then
    namespace_exact = false
  end
end
namespace_exact = namespace_exact and namespace_count == 2
local first_planned = 0
for _, row in ipairs(first and first.composition or {}) do
  first_planned = first_planned + (tonumber(row.planned) or 0)
end
local second_planned = 0
for _, row in ipairs(second and second.composition or {}) do
  second_planned = second_planned + (tonumber(row.planned) or 0)
end
print("authority=" .. tostring(sd.state.is_authority()))
print("schedule_rows=" .. tostring(schedule and #schedule or 0))
print("first_wave=" .. tostring(first and first.wave or 0))
print("first_budget=" .. tostring(first and first.spawn_budget or 0))
print("first_planned=" .. tostring(first_planned))
print("second_wave=" .. tostring(second and second.wave or 0))
print("second_budget=" .. tostring(second and second.spawn_budget or 0))
print("second_planned=" .. tostring(second_planned))
print("schedule_valid=" .. tostring(schedule_valid))
print("raw_addresses_absent=" .. tostring(raw_addresses_absent))
print("mutation_surface_absent=" .. tostring(namespace_exact))
print("schedule_signature=" .. table.concat(signature, "|"))
"""


STATE_PROBE = """
local state = assert(sd.waves.get_state(), "wave state unavailable")
local composition = {}
local planned_composition = {}
local spawned = 0
local alive = 0
local killed = 0
local planned = 0
local previous_type = -1
local composition_sorted = true
local raw_addresses_absent = true
for _, row in ipairs(state.composition or {}) do
  local enemy_type = tonumber(row.enemy_type) or -1
  if enemy_type <= previous_type then composition_sorted = false end
  previous_type = enemy_type
  local row_planned = tonumber(row.planned) or 0
  local row_spawned = tonumber(row.spawned) or 0
  local row_alive = tonumber(row.alive) or 0
  local row_killed = tonumber(row.killed) or 0
  planned = planned + row_planned
  spawned = spawned + row_spawned
  alive = alive + row_alive
  killed = killed + row_killed
  planned_composition[#planned_composition + 1] =
    tostring(enemy_type) .. ":" .. tostring(row_planned)
  composition[#composition + 1] = table.concat({
    tostring(enemy_type),
    tostring(row_planned),
    tostring(row_spawned),
    tostring(row_alive),
    tostring(row_killed),
  }, ":")
  if row.actor_address ~= nil or row.config_address ~= nil then
    raw_addresses_absent = false
  end
end
if state.spawner_address ~= nil or state.arena_address ~= nil or
    state.action_record_address ~= nil or state.world_address ~= nil then
  raw_addresses_absent = false
end
local aggregate_valid =
  planned == (tonumber(state.planned) or -1) and
  spawned == (tonumber(state.spawned) or -1) and
  alive == (tonumber(state.alive) or -1) and
  killed == (tonumber(state.killed) or -1) and
  spawned == alive + killed
print("authority=" .. tostring(sd.state.is_authority()))
print("wave=" .. tostring(state.wave))
print("phase=" .. tostring(state.phase))
print("planned=" .. tostring(state.planned))
print("remaining_to_spawn=" .. tostring(state.remaining_to_spawn))
print("spawned=" .. tostring(state.spawned))
print("alive=" .. tostring(state.alive))
print("killed=" .. tostring(state.killed))
print("composition_rows=" .. tostring(#(state.composition or {})))
print("composition_sorted=" .. tostring(composition_sorted))
print("aggregate_valid=" .. tostring(aggregate_valid))
print("raw_addresses_absent=" .. tostring(raw_addresses_absent))
print("planned_composition_signature=" ..
  table.concat(planned_composition, ","))
print("composition_signature=" .. table.concat(composition, ","))
print("event_count=" .. tostring(
  _G.__sdmod_waves_acceptance_event_count or 0))
print("event_wave=" .. tostring(
  _G.__sdmod_waves_acceptance_event_wave or 0))
print("event_planned=" .. tostring(
  _G.__sdmod_waves_acceptance_event_planned or 0))
print("event_composition_signature=" .. tostring(
  _G.__sdmod_waves_acceptance_event_composition or ""))
"""


START_WAVES_PROBE = """
assert(sd.state.is_authority(), "only the authority may start acceptance waves")
print("started=" .. tostring(sd.gameplay.start_waves()))
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


def registration_matches(values: dict[str, str], *, authority: bool) -> bool:
    try:
        return (
            values.get("mod_id") == ACCEPTANCE_MOD_ID
            and values.get("registered") == "true"
            and values.get("authority") == ("true" if authority else "false")
            and _int_value(values, "event_count") == 0
        )
    except RuntimeError:
        return False


def schedule_matches(values: dict[str, str], *, authority: bool) -> bool:
    try:
        return (
            values.get("authority") == ("true" if authority else "false")
            and _int_value(values, "schedule_rows") == 2
            and _int_value(values, "first_wave") == 1
            and _int_value(values, "first_budget")
            == EXPECTED_FIRST_WAVE_BUDGET
            and _int_value(values, "first_planned")
            == EXPECTED_FIRST_WAVE_BUDGET
            and _int_value(values, "second_wave") == 2
            and _int_value(values, "second_budget")
            == EXPECTED_SECOND_WAVE_BUDGET
            and _int_value(values, "second_planned")
            == EXPECTED_SECOND_WAVE_BUDGET
            and values.get("schedule_valid") == "true"
            and values.get("raw_addresses_absent") == "true"
            and values.get("mutation_surface_absent") == "true"
            and bool(values.get("schedule_signature"))
        )
    except RuntimeError:
        return False


def prestart_state_matches(
    values: dict[str, str],
    *,
    authority: bool,
) -> bool:
    try:
        return (
            values.get("authority") == ("true" if authority else "false")
            and _int_value(values, "wave") == 0
            and values.get("phase") == "idle"
            and _int_value(values, "planned") == 0
            and _int_value(values, "remaining_to_spawn") == 0
            and _int_value(values, "spawned") == 0
            and _int_value(values, "alive") == 0
            and _int_value(values, "killed") == 0
            and _int_value(values, "composition_rows") == 0
            and values.get("composition_sorted") == "true"
            and values.get("aggregate_valid") == "true"
            and values.get("raw_addresses_absent") == "true"
            and _int_value(values, "event_count") == 0
        )
    except RuntimeError:
        return False


def active_wave_matches(
    values: dict[str, str],
    *,
    authority: bool,
    composition_signature: str | None = None,
) -> bool:
    try:
        actual_signature = values.get("composition_signature", "")
        planned_signature = values.get(
            "planned_composition_signature",
            "",
        )
        return (
            values.get("authority") == ("true" if authority else "false")
            and _int_value(values, "wave") == 1
            and values.get("phase") == "clearing"
            and _int_value(values, "planned") == EXPECTED_FIRST_WAVE_BUDGET
            and _int_value(values, "remaining_to_spawn") == 0
            and _int_value(values, "spawned") == EXPECTED_FIRST_WAVE_BUDGET
            and _int_value(values, "alive") == EXPECTED_FIRST_WAVE_BUDGET
            and _int_value(values, "killed") == 0
            and _int_value(values, "composition_rows") == 1
            and values.get("composition_sorted") == "true"
            and values.get("aggregate_valid") == "true"
            and values.get("raw_addresses_absent") == "true"
            and bool(actual_signature)
            and (
                composition_signature is None
                or actual_signature == composition_signature
            )
            and _int_value(values, "event_count") == 1
            and _int_value(values, "event_wave") == 1
            and _int_value(values, "event_planned")
            == EXPECTED_FIRST_WAVE_BUDGET
            and values.get("event_composition_signature")
            == planned_signature
        )
    except RuntimeError:
        return False


def _run_probe(client: tuple[str, str], code: str) -> dict[str, Any]:
    result = run_lua_client(client[0], client[1], code, timeout=12.0)
    failure = _failed_exec(result)
    if failure:
        raise RuntimeError(failure)
    return result


def _poll_probe(
    client: tuple[str, str],
    code: str,
    predicate: Callable[[dict[str, str]], bool],
    *,
    timeout: float,
    description: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = run_lua_client(client[0], client[1], code, timeout=12.0)
        values = last.get("values", {})
        if (
            _failed_exec(last) is None
            and isinstance(values, dict)
            and predicate(values)
        ):
            return last
        time.sleep(0.1)
    raise RuntimeError(f"{description} did not converge for {client[0]}: {last}")


def run(
    clients: list[tuple[str, str]],
    *,
    launch: bool,
    timeout: float,
) -> dict[str, Any]:
    if not launch:
        raise RuntimeError("Lua wave acceptance requires --launch-pair")
    if len(clients) < 2:
        raise RuntimeError("at least a host and client Lua endpoint are required")
    host = clients[0]
    client = clients[1]
    peers = [host, client]
    result: dict[str, Any] = {
        "ok": False,
        "launched_pair": True,
        "host": host[0],
        "client": client[0],
        "wave_override": str(WAVE_OVERRIDE),
    }
    launched_process_ids: list[int] = []
    try:
        result["pair"] = launch_pair(
            god_mode=True,
            tile_windows=False,
            test_wave_override=WAVE_OVERRIDE,
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
        result["run"] = start_host_testrun_and_wait_for_clients(
            timeout=timeout,
        )
        wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "testrun")
        wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "testrun")

        result["registrations"] = [
            _run_probe(peer, REGISTER_PROBE) for peer in peers
        ]
        for index, probe in enumerate(result["registrations"]):
            if not registration_matches(
                _values(probe),
                authority=index == 0,
            ):
                raise RuntimeError(
                    f"Lua wave event registration differs: {probe}"
                )

        result["schedules"] = [
            _poll_probe(
                peer,
                SCHEDULE_PROBE,
                lambda values, authority=index == 0: schedule_matches(
                    values,
                    authority=authority,
                ),
                timeout=timeout,
                description="controlled Lua wave schedule",
            )
            for index, peer in enumerate(peers)
        ]
        host_schedule = _values(result["schedules"][0])
        client_schedule = _values(result["schedules"][1])
        if (
            host_schedule.get("schedule_signature")
            != client_schedule.get("schedule_signature")
        ):
            raise RuntimeError(
                "Lua wave schedules differ between peers: "
                f"host={host_schedule} client={client_schedule}"
            )

        result["prestart"] = [
            _poll_probe(
                peer,
                STATE_PROBE,
                lambda values, authority=index == 0: prestart_state_matches(
                    values,
                    authority=authority,
                ),
                timeout=timeout,
                description="clean pre-wave state",
            )
            for index, peer in enumerate(peers)
        ]

        start = _run_probe(host, START_WAVES_PROBE)
        result["start"] = start
        if _values(start).get("started") != "true":
            raise RuntimeError(f"stock waves did not start: {start}")

        host_active = _poll_probe(
            host,
            STATE_PROBE,
            lambda values: active_wave_matches(values, authority=True),
            timeout=timeout,
            description="authority wave summary",
        )
        result["host_active"] = host_active
        host_signature = _values(host_active).get(
            "composition_signature",
            "",
        )
        result["client_active"] = _poll_probe(
            client,
            STATE_PROBE,
            lambda values: active_wave_matches(
                values,
                authority=False,
                composition_signature=host_signature,
            ),
            timeout=timeout,
            description="replicated client wave summary",
        )
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
        help="Lua endpoint as NAME=PIPE; order must be host then client.",
    )
    parser.add_argument(
        "--launch-pair",
        action="store_true",
        help="stage and launch the disposable local pair required by this verifier",
    )
    parser.add_argument(
        "--confirm-mutation",
        action="store_true",
        help="confirm that the verifier may start one controlled stock wave",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    if not args.confirm_mutation:
        result["error"] = "refusing wave mutations without --confirm-mutation"
        return_code = 2
    elif not args.launch_pair:
        result["error"] = "Lua wave acceptance requires --launch-pair"
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
