#!/usr/bin/env python3
"""Verify the address-free sd.net contract on an already-running loader."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from verify_local_multiplayer_sync import VerifyFailure, lua, parse_key_values


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_net_verification.json"
DEFAULT_PIPE = "SolomonDarkModLoader_LuaExec"


SETUP_PROBE = r'''
assert(type(sd.net) == "table", "missing sd.net")
for _, name in ipairs({"send", "broadcast", "on", "off", "get_limits"}) do
  assert(type(sd.net[name]) == "function", "missing sd.net." .. name)
end
assert(sd.runtime.has_capability("net.raw.fragmented"))
assert(sd.runtime.has_capability("net.participant.unicast"))
assert(sd.runtime.has_capability("net.participant.broadcast"))

local limits = sd.net.get_limits()
assert(limits.channel_bytes == 64)
assert(limits.payload_bytes == 60 * 1024)
assert(limits.subscriptions_per_mod == 64)
assert(limits.queued_messages == 16)
assert(limits.queued_bytes == 256 * 1024)
assert(limits.pending_deliveries == 64)
assert(limits.pending_delivery_bytes == 512 * 1024)

net_verify_count = 0
net_verify_payload = nil
net_verify_message = nil
net_verify_subscription = sd.net.on("verify.raw", function(payload, message)
  net_verify_count = net_verify_count + 1
  net_verify_payload = payload
  net_verify_message = message
end)
net_verify_expected = "binary\0payload\255"
local sequence = sd.net.broadcast("verify.raw", net_verify_expected)
assert(type(sequence) == "number" and sequence > 0)

local bad_channel_ok = pcall(sd.net.broadcast, "bad channel", "payload")
local oversized_ok = pcall(
  sd.net.broadcast, "verify.raw", string.rep("x", limits.payload_bytes + 1))
local offline_unicast_ok = pcall(sd.net.send, 1, "verify.raw", "payload")
print("namespace_valid=true")
print("limits_valid=true")
print("bad_channel_rejected=" .. tostring(not bad_channel_ok))
print("oversized_rejected=" .. tostring(not oversized_ok))
print("offline_unicast_rejected=" .. tostring(not offline_unicast_ok))
'''


RESULT_PROBE = r'''
local callback_valid = net_verify_count == 1 and
  net_verify_payload == net_verify_expected and
  net_verify_message.channel == "verify.raw" and
  net_verify_message.sender_participant_id == 0 and
  net_verify_message.target_participant_id == 0 and
  net_verify_message.broadcast == true and
  type(net_verify_message.sequence) == "number"
local removed = sd.net.off(net_verify_subscription)
local absent = not sd.net.off(net_verify_subscription)
net_verify_count = nil
net_verify_payload = nil
net_verify_message = nil
net_verify_subscription = nil
net_verify_expected = nil
print("callback_valid=" .. tostring(callback_valid))
print("subscription_lifetime_valid=" .. tostring(removed and absent))
'''


def _require_true(values: dict[str, str], *names: str) -> None:
    for name in names:
        if values.get(name) != "true":
            raise VerifyFailure(f"Lua net contract failed {name}: {values}")


def run(pipe_name: str) -> dict[str, Any]:
    setup = parse_key_values(lua(pipe_name, SETUP_PROBE, timeout=12.0))
    _require_true(
        setup,
        "namespace_valid",
        "limits_valid",
        "bad_channel_rejected",
        "oversized_rejected",
        "offline_unicast_rejected",
    )
    result = parse_key_values(lua(pipe_name, RESULT_PROBE, timeout=12.0))
    _require_true(result, "callback_valid", "subscription_lifetime_valid")
    return {"ok": True, "pipe": pipe_name, "setup": setup, "result": result}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipe", default=DEFAULT_PIPE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    try:
        result: dict[str, Any] = run(args.pipe)
        return_code = 0
    except Exception as error:  # noqa: BLE001 - preserve exact live evidence.
        result = {"ok": False, "pipe": args.pipe, "error": str(error)}
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
