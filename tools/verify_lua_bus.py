#!/usr/bin/env python3
"""Exercise provider discovery and nested cross-state Lua bus dispatch live."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from verify_local_multiplayer_sync import VerifyFailure, lua, parse_key_values


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_bus_verification.json"
DEFAULT_PIPE = "SolomonDarkModLoader_LuaExec"


PROBE = r'''
assert(sd.runtime.has_capability("bus.local.contracts"))
local providers = sd.bus.providers("sample.bus.echo.v1")
print("has_provider=" .. tostring(sd.bus.has("sample.bus.echo.v1")))
print("provider_count=" .. tostring(#providers))
print("provider_id=" .. tostring(providers[1]))

local response_count = 0
local response_token = ""
local response_publisher = ""
local request_mod_id = ""
local subscription
subscription = sd.bus.subscribe("sample.bus.consumer.response", function(payload, context)
  response_count = response_count + 1
  response_token = tostring(payload.token)
  request_mod_id = tostring(payload.request_mod_id)
  response_publisher = tostring(context.publisher_mod_id)
end)

local delivered = sd.bus.publish("sample.bus.consumer.request", {
  token = "live-cross-state",
})
print("request_deliveries=" .. tostring(delivered))
print("response_count=" .. tostring(response_count))
print("response_token=" .. response_token)
print("response_publisher=" .. response_publisher)
print("request_mod_id=" .. request_mod_id)
print("unsubscribed=" .. tostring(sd.bus.unsubscribe(subscription)))
print("unsubscribed_twice=" .. tostring(sd.bus.unsubscribe(subscription)))
print("unknown_deliveries=" .. tostring(sd.bus.publish("sample.bus.unknown", nil)))

local cycle = {}; cycle.self = cycle
local cycle_ok = pcall(sd.bus.publish, "sample.bus.consumer.request", cycle)
print("cycle_rejected=" .. tostring(not cycle_ok))
'''


def run(pipe_name: str) -> dict[str, Any]:
    values = parse_key_values(lua(pipe_name, PROBE, timeout=12.0))
    if values.get("has_provider") != "true":
        raise VerifyFailure(f"provider contract unavailable: {values}")
    if values.get("provider_count") != "1" or values.get("provider_id") != (
        "sample.lua.bus_provider_lab"
    ):
        raise VerifyFailure(f"provider discovery mismatch: {values}")
    if values.get("request_deliveries") != "1":
        raise VerifyFailure(f"cross-mod request delivery mismatch: {values}")
    if values.get("response_count") != "1":
        raise VerifyFailure(f"cross-mod response count mismatch: {values}")
    if values.get("response_token") != "live-cross-state":
        raise VerifyFailure(f"cross-mod payload mismatch: {values}")
    if values.get("response_publisher") != "sample.lua.bus_consumer_lab":
        raise VerifyFailure(f"publisher_mod_id mismatch: {values}")
    if values.get("request_mod_id") != "sample.lua.bus_provider_lab":
        raise VerifyFailure(f"request context mismatch: {values}")
    if values.get("unsubscribed") != "true" or values.get("unsubscribed_twice") != "false":
        raise VerifyFailure(f"subscription lifecycle mismatch: {values}")
    if values.get("unknown_deliveries") != "0":
        raise VerifyFailure(f"unknown topic unexpectedly delivered: {values}")
    if values.get("cycle_rejected") != "true":
        raise VerifyFailure(f"cyclic payload was accepted: {values}")
    return {"ok": True, "pipe": pipe_name, "values": values}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipe", default=DEFAULT_PIPE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False, "pipe": args.pipe}
    try:
        result = run(args.pipe)
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
