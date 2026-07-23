#!/usr/bin/env python3
"""Verify authority-owned Lua state, ordered events, and late-join sync live."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from multiplayer_lua_probe import (
    DEFAULT_CLIENTS,
    parse_client,
    parse_key_values,
    run_all,
    run_lua_client,
)
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    CLIENT_PIPE,
    HOST_ID,
    HOST_NAME,
    HOST_PIPE,
    THIRD_ID,
    THIRD_NAME,
    THIRD_PIPE,
    complete_native_create,
    disable_bots,
    game_process_ids,
    launch_additional_client,
    launch_pair,
    stop_game_processes,
    wait_for_remote,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_mod_replication_acceptance.json"
EVENT_NAME = "acceptance.lua_mod_stream"

REGISTER_HANDLER = f"""
_G.__lua_mod_acceptance_events = {{}}
_G.__lua_mod_acceptance_state_tokens = {{}}
sd.events.on({json.dumps(EVENT_NAME)}, function(payload, context)
  local index = #_G.__lua_mod_acceptance_events + 1
  _G.__lua_mod_acceptance_events[index] = tonumber(payload.ordinal) or -1
  local current = sd.state.get('acceptance')
  _G.__lua_mod_acceptance_state_tokens[index] =
    type(current) == 'table' and tostring(current.token) or ''
end)
print('authority=' .. tostring(sd.state.is_authority()))
"""

PUBLISH = f"""
assert(sd.state.is_authority(), 'publisher is not the simulation authority')
sd.state.clear()
local revision = sd.state.set('acceptance', {{
  token = 'host-state-v1',
  count = 42,
  flags = {{ready = true, mode = 'co-op'}},
  order = {{'alpha', 'beta', 'gamma'}},
}})
local first = sd.events.broadcast({json.dumps(EVENT_NAME)}, {{ordinal = 1}})
local second = sd.events.broadcast({json.dumps(EVENT_NAME)}, {{ordinal = 2}})
print('revision=' .. tostring(revision))
print('first_sequence=' .. tostring(first))
print('second_sequence=' .. tostring(second))
"""

READ_CONVERGENCE = """
local value = sd.state.get('acceptance')
local events = _G.__lua_mod_acceptance_events or {}
local tokens = _G.__lua_mod_acceptance_state_tokens or {}
print('authority=' .. tostring(sd.state.is_authority()))
print('token=' .. tostring(type(value) == 'table' and value.token or ''))
print('count=' .. tostring(type(value) == 'table' and value.count or ''))
print('nested=' .. tostring(
  type(value) == 'table' and
  type(value.flags) == 'table' and
  value.flags.ready == true and
  value.flags.mode == 'co-op'))
print('array=' .. tostring(
  type(value) == 'table' and
  type(value.order) == 'table' and
  table.concat(value.order, ',') or ''))
print('events=' .. table.concat(events, ','))
print('event_state_tokens=' .. table.concat(tokens, ','))
print('revision=' .. tostring(sd.state.get_revision()))
"""

READ_LATE_JOIN = """
local value = sd.state.get('acceptance')
print('authority=' .. tostring(sd.state.is_authority()))
print('token=' .. tostring(type(value) == 'table' and value.token or ''))
print('count=' .. tostring(type(value) == 'table' and value.count or ''))
print('nested=' .. tostring(
  type(value) == 'table' and
  type(value.flags) == 'table' and
  value.flags.ready == true and
  value.flags.mode == 'co-op'))
print('array=' .. tostring(
  type(value) == 'table' and
  type(value.order) == 'table' and
  table.concat(value.order, ',') or ''))
print('revision=' .. tostring(sd.state.get_revision()))
"""


def _failed_exec(result: dict[str, Any]) -> str | None:
    if result.get("returncode") == 0:
        return None
    return str(result.get("stderr") or result.get("stdout") or "Lua exec failed").strip()


def _is_converged(values: dict[str, str]) -> bool:
    return (
        values.get("authority") == "false"
        and values.get("token") == "host-state-v1"
        and values.get("count") == "42"
        and values.get("nested") == "true"
        and values.get("array") == "alpha,beta,gamma"
        and values.get("events") == "1,2"
        and values.get("event_state_tokens") == "host-state-v1,host-state-v1"
        and int(values.get("revision", "0")) > 0
    )


def _has_checkpoint(values: dict[str, str]) -> bool:
    return (
        values.get("authority") == "false"
        and values.get("token") == "host-state-v1"
        and values.get("count") == "42"
        and values.get("nested") == "true"
        and values.get("array") == "alpha,beta,gamma"
        and int(values.get("revision", "0")) > 0
    )


def _poll(
    client: tuple[str, str],
    code: str,
    predicate: Any,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = run_lua_client(client[0], client[1], code, timeout=12.0)
        if _failed_exec(last) is None and predicate(last.get("values", {})):
            return last
        time.sleep(0.1)
    raise RuntimeError(f"Lua mod replication did not converge: {last}")


def run(
    clients: list[tuple[str, str]],
    *,
    launch: bool,
    timeout: float,
) -> dict[str, Any]:
    if len(clients) < 2:
        raise RuntimeError("at least a host and client Lua endpoint are required")
    host = clients[0]
    client = clients[1]
    result: dict[str, Any] = {
        "ok": False,
        "launched_pair": launch,
        "host": host[0],
        "client": client[0],
    }
    launched_process_ids: list[int] = []
    try:
        if launch:
            result["pair"] = launch_pair(
                god_mode=True,
                kill_existing=False,
            )
            launched_process_ids.extend(game_process_ids(result["pair"]))
            disable_bots()
            wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "hub")
            wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "hub")

        registrations = run_all(clients[:2], REGISTER_HANDLER, timeout=12.0)
        result["registrations"] = registrations
        failures = [_failed_exec(peer) for peer in registrations]
        failures = [failure for failure in failures if failure]
        if failures:
            raise RuntimeError("; ".join(failures))
        roles = [peer.get("values", {}).get("authority") for peer in registrations]
        if roles != ["true", "false"]:
            raise RuntimeError(f"unexpected authority roles: {roles}")

        publication = run_lua_client(host[0], host[1], PUBLISH, timeout=12.0)
        result["publication"] = publication
        publication_failure = _failed_exec(publication)
        if publication_failure:
            raise RuntimeError(publication_failure)
        published = publication.get("values", {})
        if not (
            int(published.get("revision", "0")) > 0
            and int(published.get("first_sequence", "0")) > 0
            and int(published.get("second_sequence", "0"))
            == int(published.get("first_sequence", "0")) + 1
        ):
            raise RuntimeError(
                f"publisher returned invalid revisions/sequences: {published}"
            )

        result["client_convergence"] = _poll(
            client,
            READ_CONVERGENCE,
            _is_converged,
            timeout,
        )

        if launch:
            result["late_join_launch"] = launch_additional_client(
                preset="create_manual",
                god_mode=True,
            )
            launched_process_ids.extend(
                game_process_ids(result["late_join_launch"])
            )
            result["late_join_create"] = complete_native_create(
                THIRD_PIPE,
                element="fire",
                discipline="mind",
                timeout=timeout,
            )
            wait_for_remote(HOST_PIPE, THIRD_ID, THIRD_NAME, "hub")
            wait_for_remote(THIRD_PIPE, HOST_ID, HOST_NAME, "hub")
            result["late_join_checkpoint"] = _poll(
                ("late_join", THIRD_PIPE),
                READ_LATE_JOIN,
                _has_checkpoint,
                timeout,
            )
        else:
            result["late_join_checkpoint"] = {"skipped": True}

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
        help="Lua endpoint as NAME=PIPE; order must be authority then client.",
    )
    parser.add_argument(
        "--launch-pair",
        action="store_true",
        help="Launch a local pair and a late-joining third client.",
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    try:
        result = run(
            args.client or list(DEFAULT_CLIENTS),
            launch=args.launch_pair,
            timeout=args.timeout,
        )
        return_code = 0
    except Exception as exc:  # noqa: BLE001 - preserve verifier evidence.
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
