#!/usr/bin/env python3
"""Verify fragmented Lua raw messages across a real local host/client pair."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from multiplayer_lua_probe import (
    DEFAULT_CLIENTS,
    parse_client,
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
    disable_bots,
    game_process_ids,
    launch_pair,
    stop_game_processes,
    wait_for_remote,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_net_multiplayer_verification.json"
ACCEPTANCE_MOD_ID = "sample.lua.authoring_lab"
CHANNEL = "acceptance.raw.fragmented"

REGISTER = f"""
if _G.__lua_net_acceptance_subscription ~= nil then
  pcall(sd.net.off, _G.__lua_net_acceptance_subscription)
end
_G.__lua_net_acceptance_messages = {{}}
_G.__lua_net_acceptance_subscription = sd.net.on(
  {json.dumps(CHANNEL)},
  function(payload, message)
    local first = #payload > 0 and string.byte(payload, 1) or -1
    local last = #payload > 0 and string.byte(payload, #payload) or -1
    local row = table.concat({{
      tostring(message.sender_participant_id),
      tostring(message.target_participant_id),
      message.broadcast and "1" or "0",
      tostring(message.sequence),
      tostring(#payload),
      tostring(first),
      tostring(last),
    }}, ",")
    table.insert(_G.__lua_net_acceptance_messages, row)
  end)
print("registered=true")
"""

READ = """
local rows = {}
for index, row in ipairs(_G.__lua_net_acceptance_messages or {}) do
  rows[index] = row
end
table.sort(rows)
print("count=" .. tostring(#rows))
print("rows=" .. table.concat(rows, ";"))
"""

CLEANUP = """
local removed = false
if _G.__lua_net_acceptance_subscription ~= nil then
  removed = sd.net.off(_G.__lua_net_acceptance_subscription)
end
_G.__lua_net_acceptance_subscription = nil
_G.__lua_net_acceptance_messages = nil
print("removed=" .. tostring(removed))
"""


def _publish_probe(
    *,
    unicast_target: int,
    unicast_first: int,
    unicast_fill: str,
    unicast_fill_bytes: int,
    unicast_last: int,
    broadcast_first: int,
    broadcast_fill: str,
    broadcast_fill_bytes: int,
    broadcast_last: int,
) -> str:
    return f"""
local unicast = string.char({unicast_first}) ..
  string.rep({json.dumps(unicast_fill)}, {unicast_fill_bytes}) ..
  string.char({unicast_last})
local broadcast = string.char({broadcast_first}) ..
  string.rep({json.dumps(broadcast_fill)}, {broadcast_fill_bytes}) ..
  string.char({broadcast_last})
local unicast_sequence = sd.net.send(
  {unicast_target}, {json.dumps(CHANNEL)}, unicast)
local broadcast_sequence = sd.net.broadcast(
  {json.dumps(CHANNEL)}, broadcast)
print("unicast_sequence=" .. tostring(unicast_sequence))
print("broadcast_sequence=" .. tostring(broadcast_sequence))
print("unicast_bytes=" .. tostring(#unicast))
print("broadcast_bytes=" .. tostring(#broadcast))
"""


HOST_PUBLISH = _publish_probe(
    unicast_target=CLIENT_ID,
    unicast_first=72,
    unicast_fill="h",
    unicast_fill_bytes=2048,
    unicast_last=0,
    broadcast_first=65,
    broadcast_fill="a",
    broadcast_fill_bytes=2560,
    broadcast_last=255,
)

CLIENT_PUBLISH = _publish_probe(
    unicast_target=HOST_ID,
    unicast_first=67,
    unicast_fill="c",
    unicast_fill_bytes=3072,
    unicast_last=255,
    broadcast_first=66,
    broadcast_fill="b",
    broadcast_fill_bytes=4096,
    broadcast_last=255,
)


def _failed_exec(result: dict[str, Any]) -> str | None:
    if result.get("returncode") == 0:
        return None
    return str(result.get("stderr") or result.get("stdout") or "Lua exec failed").strip()


def _positive_int(values: dict[str, str], name: str) -> int:
    try:
        value = int(values.get(name, "0"))
    except ValueError as error:
        raise RuntimeError(f"invalid {name}: {values}") from error
    if value <= 0:
        raise RuntimeError(f"invalid {name}: {values}")
    return value


def message_signature(
    *,
    sender: int,
    target: int,
    broadcast: bool,
    sequence: int,
    payload_bytes: int,
    first_byte: int,
    last_byte: int,
) -> str:
    return ",".join(
        (
            str(sender),
            str(target),
            "1" if broadcast else "0",
            str(sequence),
            str(payload_bytes),
            str(first_byte),
            str(last_byte),
        )
    )


def messages_match(values: dict[str, str], expected: list[str]) -> bool:
    return (
        values.get("count") == str(len(expected))
        and values.get("rows") == ";".join(sorted(expected))
    )


def _poll_messages(
    client: tuple[str, str],
    expected: list[str],
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = run_lua_client(client[0], client[1], READ, timeout=12.0)
        values = last.get("values", {})
        if (
            _failed_exec(last) is None
            and isinstance(values, dict)
            and messages_match(values, expected)
        ):
            return last
        time.sleep(0.1)
    raise RuntimeError(
        f"Lua net messages did not converge for {client[0]}: "
        f"expected={sorted(expected)} last={last}"
    )


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
    registrations_attempted = False
    try:
        if launch:
            result["pair"] = launch_pair(
                god_mode=True,
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

        registrations = run_all(clients[:2], REGISTER, timeout=12.0)
        registrations_attempted = True
        result["registrations"] = registrations
        failures = [_failed_exec(peer) for peer in registrations]
        failures = [failure for failure in failures if failure]
        if failures:
            raise RuntimeError("; ".join(failures))
        for peer in registrations:
            if peer.get("values", {}).get("registered") != "true":
                raise RuntimeError(f"Lua net registration failed: {peer}")
        host_publish = run_lua_client(
            host[0],
            host[1],
            HOST_PUBLISH,
            timeout=12.0,
        )
        result["host_publish"] = host_publish
        failure = _failed_exec(host_publish)
        if failure:
            raise RuntimeError(failure)
        host_values = host_publish.get("values", {})
        host_unicast_sequence = _positive_int(
            host_values,
            "unicast_sequence",
        )
        host_broadcast_sequence = _positive_int(
            host_values,
            "broadcast_sequence",
        )

        client_publish = run_lua_client(
            client[0],
            client[1],
            CLIENT_PUBLISH,
            timeout=12.0,
        )
        result["client_publish"] = client_publish
        failure = _failed_exec(client_publish)
        if failure:
            raise RuntimeError(failure)
        client_values = client_publish.get("values", {})
        client_unicast_sequence = _positive_int(
            client_values,
            "unicast_sequence",
        )
        client_broadcast_sequence = _positive_int(
            client_values,
            "broadcast_sequence",
        )

        host_expected = [
            message_signature(
                sender=HOST_ID,
                target=0,
                broadcast=True,
                sequence=host_broadcast_sequence,
                payload_bytes=2562,
                first_byte=65,
                last_byte=255,
            ),
            message_signature(
                sender=CLIENT_ID,
                target=HOST_ID,
                broadcast=False,
                sequence=client_unicast_sequence,
                payload_bytes=3074,
                first_byte=67,
                last_byte=255,
            ),
            message_signature(
                sender=CLIENT_ID,
                target=0,
                broadcast=True,
                sequence=client_broadcast_sequence,
                payload_bytes=4098,
                first_byte=66,
                last_byte=255,
            ),
        ]
        client_expected = [
            message_signature(
                sender=HOST_ID,
                target=CLIENT_ID,
                broadcast=False,
                sequence=host_unicast_sequence,
                payload_bytes=2050,
                first_byte=72,
                last_byte=0,
            ),
            message_signature(
                sender=HOST_ID,
                target=0,
                broadcast=True,
                sequence=host_broadcast_sequence,
                payload_bytes=2562,
                first_byte=65,
                last_byte=255,
            ),
            message_signature(
                sender=CLIENT_ID,
                target=0,
                broadcast=True,
                sequence=client_broadcast_sequence,
                payload_bytes=4098,
                first_byte=66,
                last_byte=255,
            ),
        ]
        result["host_delivery"] = _poll_messages(host, host_expected, timeout)
        result["client_delivery"] = _poll_messages(
            client,
            client_expected,
            timeout,
        )
        result["ok"] = True
        return result
    finally:
        if registrations_attempted:
            result["cleanup"] = run_all(clients[:2], CLEANUP, timeout=12.0)
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
        help="Stage and launch an isolated local pair before verification.",
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    try:
        result = run(
            args.client or list(DEFAULT_CLIENTS),
            launch=args.launch_pair,
            timeout=max(1.0, args.timeout),
        )
        return_code = 0
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
