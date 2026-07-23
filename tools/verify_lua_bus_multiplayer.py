#!/usr/bin/env python3
"""Verify process-local cross-mod Lua bus behavior across a disposable pair."""

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
OUTPUT = ROOT / "runtime" / "lua_bus_multiplayer_verification.json"
PROVIDER_MOD_ID = "sample.lua.bus_provider_lab"
CONSUMER_MOD_ID = "sample.lua.bus_consumer_lab"
ACCEPTANCE_MOD_IDS = (PROVIDER_MOD_ID, CONSUMER_MOD_ID)
CONTRACT_ID = "sample.bus.echo.v1"
LOCAL_TOPIC = "sample.bus.acceptance.local"
HOST_TOKEN = "host-local-bus"
CLIENT_TOKEN = "client-local-bus"


CONTRACT_PROBE = f"""
local mod = assert(sd.runtime.get_mod())
local multiplayer = assert(sd.runtime.get_multiplayer_state())
local scene = assert(sd.world.get_scene(), "live scene required")
local owner_count = 0
for _, participant in ipairs(multiplayer.participants or {{}}) do
  if participant.is_owner then owner_count = owner_count + 1 end
end

local namespace_count = 0
local namespace_exact = true
for name, value in pairs(sd.bus) do
  namespace_count = namespace_count + 1
  if (name ~= "publish" and name ~= "subscribe" and
      name ~= "unsubscribe" and name ~= "has" and
      name ~= "providers") or type(value) ~= "function" then
    namespace_exact = false
  end
end
namespace_exact = namespace_exact and namespace_count == 5

local providers = sd.bus.providers({json.dumps(CONTRACT_ID)})
local response_count = 0
local response_token = ""
local response_publisher = ""
local request_mod_id = ""
local response_subscription = sd.bus.subscribe(
  "sample.bus.consumer.response",
  function(payload, context)
    response_count = response_count + 1
    response_token = tostring(payload.token)
    request_mod_id = tostring(payload.request_mod_id)
    response_publisher = tostring(context.publisher_mod_id)
  end)
local request_deliveries = sd.bus.publish(
  "sample.bus.consumer.request",
  {{token = "pair-contract"}})
local unsubscribed = sd.bus.unsubscribe(response_subscription)
local unsubscribed_twice = sd.bus.unsubscribe(response_subscription)
local unknown_deliveries = sd.bus.publish(
  "sample.bus.acceptance.unknown", nil)

local cycle = {{}}
cycle.self = cycle
local cycle_ok = pcall(
  sd.bus.publish, "sample.bus.consumer.request", cycle)
local function_ok = pcall(
  sd.bus.publish, "sample.bus.consumer.request", function() end)
local bad_topic_ok = pcall(sd.bus.has, "bad topic")
local bad_callback_ok = pcall(
  sd.bus.subscribe, "sample.bus.acceptance.bad", {{}})
local zero_unsubscribe_ok = pcall(sd.bus.unsubscribe, 0)

print("mod_id=" .. tostring(mod.id))
print("bus_capability=" .. tostring(
  sd.runtime.has_capability("bus.local.contracts")))
print("authority=" .. tostring(sd.state.is_authority()))
print("world_scene=" .. tostring(scene.name or scene.kind))
print("participant_count=" .. tostring(multiplayer.participant_count))
print("participant_rows=" .. tostring(#(multiplayer.participants or {{}})))
print("owner_count=" .. tostring(owner_count))
print("namespace_exact=" .. tostring(namespace_exact))
print("has_provider=" .. tostring(sd.bus.has({json.dumps(CONTRACT_ID)})))
print("provider_count=" .. tostring(#providers))
print("provider_id=" .. tostring(providers[1]))
print("request_deliveries=" .. tostring(request_deliveries))
print("response_count=" .. tostring(response_count))
print("response_token=" .. response_token)
print("response_publisher=" .. response_publisher)
print("request_mod_id=" .. request_mod_id)
print("unsubscribed=" .. tostring(unsubscribed))
print("unsubscribed_twice=" .. tostring(unsubscribed_twice))
print("unknown_deliveries=" .. tostring(unknown_deliveries))
print("cycle_rejected=" .. tostring(not cycle_ok))
print("function_rejected=" .. tostring(not function_ok))
print("bad_topic_rejected=" .. tostring(not bad_topic_ok))
print("bad_callback_rejected=" .. tostring(not bad_callback_ok))
print("zero_unsubscribe_rejected=" .. tostring(not zero_unsubscribe_ok))
"""


SETUP_PROBE = f"""
local previous = _G.__sd_bus_multiplayer_acceptance
local preexisting = previous ~= nil
if previous ~= nil and previous.subscription ~= nil then
  sd.bus.unsubscribe(previous.subscription)
end
local acceptance = {{
  count = 0,
  token = "",
  publisher_mod_id = "",
  topic = "",
}}
acceptance.subscription = sd.bus.subscribe(
  {json.dumps(LOCAL_TOPIC)},
  function(payload, context)
    acceptance.count = acceptance.count + 1
    acceptance.token = tostring(payload.token)
    acceptance.publisher_mod_id = tostring(context.publisher_mod_id)
    acceptance.topic = tostring(context.topic)
  end)
_G.__sd_bus_multiplayer_acceptance = acceptance
print("preexisting=" .. tostring(preexisting))
print("subscription_positive=" .. tostring(
  type(acceptance.subscription) == "number" and
  math.type(acceptance.subscription) == "integer" and
  acceptance.subscription > 0))
print("ready=true")
"""


STATE_PROBE = """
local acceptance = _G.__sd_bus_multiplayer_acceptance
print("present=" .. tostring(acceptance ~= nil))
print("count=" .. tostring(acceptance and acceptance.count or 0))
print("token=" .. tostring(acceptance and acceptance.token or ""))
print("publisher_mod_id=" .. tostring(
  acceptance and acceptance.publisher_mod_id or ""))
print("topic=" .. tostring(acceptance and acceptance.topic or ""))
print("subscription_positive=" .. tostring(
  acceptance ~= nil and
  type(acceptance.subscription) == "number" and
  math.type(acceptance.subscription) == "integer" and
  acceptance.subscription > 0))
"""


def _publish_probe(token: str) -> str:
    return f"""
local delivered = sd.bus.publish(
  {json.dumps(LOCAL_TOPIC)},
  {{token = {json.dumps(token)}}})
print("delivered=" .. tostring(delivered))
print("token=" .. tostring({json.dumps(token)}))
"""


CLEANUP_PROBE = """
local acceptance = _G.__sd_bus_multiplayer_acceptance
local present = acceptance ~= nil
local first = false
local second = false
if acceptance ~= nil and acceptance.subscription ~= nil then
  first = sd.bus.unsubscribe(acceptance.subscription)
  second = sd.bus.unsubscribe(acceptance.subscription)
end
_G.__sd_bus_multiplayer_acceptance = nil
print("present=" .. tostring(present))
print("first=" .. tostring(first))
print("second=" .. tostring(second))
print("cleared=" .. tostring(
  _G.__sd_bus_multiplayer_acceptance == nil))
"""


CAPACITY_PROBE = f"""
local handles = {{}}
for index = 1, 127 do
  handles[index] = sd.bus.subscribe(
    "sample.bus.acceptance.capacity",
    function() end)
end
local ids_monotonic = true
for index, handle in ipairs(handles) do
  if type(handle) ~= "number" or math.type(handle) ~= "integer" or
      handle <= 0 or (index > 1 and handle <= handles[index - 1]) then
    ids_monotonic = false
  end
end
local overflow_ok = pcall(
  sd.bus.subscribe,
  "sample.bus.acceptance.capacity",
  function() end)
local removed = 0
for _, handle in ipairs(handles) do
  if sd.bus.unsubscribe(handle) then removed = removed + 1 end
end

local response_count = 0
local response_token = ""
local response_publisher = ""
local request_mod_id = ""
local response_subscription = sd.bus.subscribe(
  "sample.bus.consumer.response",
  function(payload, context)
    response_count = response_count + 1
    response_token = tostring(payload.token)
    request_mod_id = tostring(payload.request_mod_id)
    response_publisher = tostring(context.publisher_mod_id)
  end)
local post_deliveries = sd.bus.publish(
  "sample.bus.consumer.request",
  {{token = "capacity-after"}})
local post_unsubscribed = sd.bus.unsubscribe(response_subscription)
local post_unsubscribed_twice = sd.bus.unsubscribe(response_subscription)

print("created=" .. tostring(#handles))
print("ids_monotonic=" .. tostring(ids_monotonic))
print("overflow_rejected=" .. tostring(not overflow_ok))
print("removed=" .. tostring(removed))
print("post_deliveries=" .. tostring(post_deliveries))
print("post_response_count=" .. tostring(response_count))
print("post_response_token=" .. response_token)
print("post_response_publisher=" .. response_publisher)
print("post_request_mod_id=" .. request_mod_id)
print("post_unsubscribed=" .. tostring(post_unsubscribed))
print("post_unsubscribed_twice=" .. tostring(post_unsubscribed_twice))
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


def contract_matches(
    values: dict[str, str],
    *,
    authority: bool,
) -> bool:
    return (
        values.get("mod_id") == PROVIDER_MOD_ID
        and values.get("bus_capability") == "true"
        and values.get("authority") == ("true" if authority else "false")
        and values.get("world_scene") == "hub"
        and values.get("participant_count") == "2"
        and values.get("participant_rows") == "2"
        and values.get("owner_count") == "1"
        and values.get("namespace_exact") == "true"
        and values.get("has_provider") == "true"
        and values.get("provider_count") == "1"
        and values.get("provider_id") == PROVIDER_MOD_ID
        and values.get("request_deliveries") == "1"
        and values.get("response_count") == "1"
        and values.get("response_token") == "pair-contract"
        and values.get("response_publisher") == CONSUMER_MOD_ID
        and values.get("request_mod_id") == PROVIDER_MOD_ID
        and values.get("unsubscribed") == "true"
        and values.get("unsubscribed_twice") == "false"
        and values.get("unknown_deliveries") == "0"
        and all(
            values.get(name) == "true"
            for name in (
                "cycle_rejected",
                "function_rejected",
                "bad_topic_rejected",
                "bad_callback_rejected",
                "zero_unsubscribe_rejected",
            )
        )
    )


def setup_matches(values: dict[str, str]) -> bool:
    return (
        values.get("preexisting") == "false"
        and values.get("subscription_positive") == "true"
        and values.get("ready") == "true"
    )


def state_matches(
    values: dict[str, str],
    *,
    count: int,
    token: str | None,
) -> bool:
    expected_present = token is not None
    return (
        values.get("present")
        == ("true" if expected_present else "false")
        and values.get("count") == str(count)
        and values.get("token") == (token or "")
        and values.get("publisher_mod_id")
        == (PROVIDER_MOD_ID if count > 0 else "")
        and values.get("topic") == (LOCAL_TOPIC if count > 0 else "")
        and values.get("subscription_positive")
        == ("true" if expected_present else "false")
    )


def publish_matches(values: dict[str, str], *, token: str) -> bool:
    return (
        values.get("delivered") == "1"
        and values.get("token") == token
    )


def cleanup_matches(
    values: dict[str, str],
    *,
    expected_present: bool,
) -> bool:
    return (
        values.get("present")
        == ("true" if expected_present else "false")
        and values.get("first")
        == ("true" if expected_present else "false")
        and values.get("second") == "false"
        and values.get("cleared") == "true"
    )


def capacity_matches(values: dict[str, str]) -> bool:
    return (
        values.get("created") == "127"
        and values.get("ids_monotonic") == "true"
        and values.get("overflow_rejected") == "true"
        and values.get("removed") == "127"
        and values.get("post_deliveries") == "1"
        and values.get("post_response_count") == "1"
        and values.get("post_response_token") == "capacity-after"
        and values.get("post_response_publisher") == CONSUMER_MOD_ID
        and values.get("post_request_mod_id") == PROVIDER_MOD_ID
        and values.get("post_unsubscribed") == "true"
        and values.get("post_unsubscribed_twice") == "false"
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
    count: int,
    token: str | None,
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
            and state_matches(values, count=count, token=token)
        ):
            return last
        time.sleep(0.05)
    raise RuntimeError(
        f"{description} did not converge for {client[0]}: {last}"
    )


def _cleanup_peer(client: tuple[str, str]) -> dict[str, Any]:
    try:
        return run_lua_client(
            client[0],
            client[1],
            CLEANUP_PROBE,
            timeout=5.0,
        )
    except Exception as error:  # noqa: BLE001 - process teardown is final.
        return {"returncode": 1, "error": str(error)}


def run(
    clients: list[tuple[str, str]],
    *,
    launch: bool,
    timeout: float,
) -> dict[str, Any]:
    if not launch:
        raise RuntimeError("Lua bus acceptance requires --launch-pair")
    if len(clients) != 2:
        raise RuntimeError("exactly one host and one client endpoint are required")
    host, client = clients
    result: dict[str, Any] = {
        "ok": False,
        "launched_pair": True,
        "host": host[0],
        "client": client[0],
        "exact_mod_ids": list(ACCEPTANCE_MOD_IDS),
    }
    launched_process_ids: list[int] = []
    pair_ready = False
    try:
        result["pair"] = launch_pair(
            tile_windows=False,
            kill_existing=False,
            exact_mod_ids=ACCEPTANCE_MOD_IDS,
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
        pair_ready = True

        result["contract"] = [
            _require_action(
                peer,
                CONTRACT_PROBE,
                lambda values, authority=index == 0: contract_matches(
                    values,
                    authority=authority,
                ),
                "local cross-mod bus contract",
            )
            for index, peer in enumerate((host, client))
        ]
        result["setup"] = [
            _require_action(
                peer,
                SETUP_PROBE,
                setup_matches,
                "local bus isolation subscription",
            )
            for peer in (host, client)
        ]
        result["initial"] = [
            _poll_state(
                peer,
                count=0,
                token="",
                timeout=timeout,
                description="empty local bus marker",
            )
            for peer in (host, client)
        ]

        result["host_publish"] = _require_action(
            host,
            _publish_probe(HOST_TOKEN),
            lambda values: publish_matches(values, token=HOST_TOKEN),
            "host local bus publish",
        )
        result["host_isolation"] = [
            _poll_state(
                host,
                count=1,
                token=HOST_TOKEN,
                timeout=timeout,
                description="host local bus delivery",
            ),
            _poll_state(
                client,
                count=0,
                token="",
                timeout=timeout,
                description="client isolation from host bus",
            ),
        ]

        result["client_publish"] = _require_action(
            client,
            _publish_probe(CLIENT_TOKEN),
            lambda values: publish_matches(values, token=CLIENT_TOKEN),
            "client local bus publish",
        )
        result["independent_delivery"] = [
            _poll_state(
                host,
                count=1,
                token=HOST_TOKEN,
                timeout=timeout,
                description="host retained local bus marker",
            ),
            _poll_state(
                client,
                count=1,
                token=CLIENT_TOKEN,
                timeout=timeout,
                description="client local bus delivery",
            ),
        ]

        result["host_marker_cleanup"] = _require_action(
            host,
            CLEANUP_PROBE,
            lambda values: cleanup_matches(
                values,
                expected_present=True,
            ),
            "host bus marker cleanup",
        )
        result["host_capacity"] = _require_action(
            host,
            CAPACITY_PROBE,
            capacity_matches,
            "host bus subscription capacity",
        )
        result["capacity_isolation"] = [
            _poll_state(
                host,
                count=0,
                token=None,
                timeout=timeout,
                description="host bus capacity cleanup",
            ),
            _poll_state(
                client,
                count=1,
                token=CLIENT_TOKEN,
                timeout=timeout,
                description="client retained marker during host capacity",
            ),
        ]

        result["client_marker_cleanup"] = _require_action(
            client,
            CLEANUP_PROBE,
            lambda values: cleanup_matches(
                values,
                expected_present=True,
            ),
            "client bus marker cleanup",
        )
        result["released"] = [
            _poll_state(
                peer,
                count=0,
                token=None,
                timeout=timeout,
                description="released local bus marker",
            )
            for peer in (host, client)
        ]
        result["ok"] = True
        return result
    finally:
        if pair_ready:
            result["cleanup"] = [
                _cleanup_peer(peer)
                for peer in (host, client)
            ]
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
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    if not args.launch_pair:
        result["error"] = "Lua bus acceptance requires --launch-pair"
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
