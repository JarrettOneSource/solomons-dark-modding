#!/usr/bin/env python3
"""Opt-in live verification of one authoritative local Lua item grant."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from verify_local_multiplayer_sync import VerifyFailure, lua, parse_key_values


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_item_grant_verification.json"
DEFAULT_PIPE = "SolomonDarkModLoader_LuaExec"
EXPECTED_CONTENT_ID = 5785942626980372610


QUEUE_GRANT = r'''
assert(sd.runtime.has_capability("items.grant.authority"))
assert(sd.state.is_authority(), "item grants require the offline or host authority")
local item = assert(
  sd.items.get(5785942626980372610),
  "enable the Lua Items Registry Lab mod before verification"
)
assert(item.available and item.recipe_uid > 0, item.unavailable_reason or "recipe unavailable")

local function count_recipe(recipe_uid)
  local inventory = assert(sd.player.get_inventory_state(), "inventory state unavailable")
  assert(inventory.valid, "enter an active gameplay scene before verification")
  local count = 0
  for _, row in ipairs(inventory.items or {}) do
    if row.valid and row.recipe_uid == recipe_uid then count = count + 1 end
  end
  return count
end

local before = count_recipe(item.recipe_uid)
local queued = sd.items.grant(item.id)
assert(queued.content_id == item.id, "queued content id differs")
assert(queued.request_id > 0, "grant request id is missing")
assert(queued.target_participant_id == 1, "local target id differs")
assert(queued.local_target, "grant was not queued for the local owner")

print("content_id=" .. tostring(item.id))
print("recipe_uid=" .. tostring(item.recipe_uid))
print("request_id=" .. tostring(queued.request_id))
print("before_count=" .. tostring(before))
'''


def inventory_count_probe(recipe_uid: int) -> str:
    return f'''
local inventory = assert(sd.player.get_inventory_state(), "inventory state unavailable")
assert(inventory.valid, "inventory is not active")
local count = 0
for _, row in ipairs(inventory.items or {{}}) do
  if row.valid and row.recipe_uid == {recipe_uid} then count = count + 1 end
end
print("after_count=" .. tostring(count))
'''


def integer(values: dict[str, str], field: str) -> int:
    try:
        return int(values[field], 0)
    except (KeyError, ValueError) as error:
        raise VerifyFailure(f"item grant probe lacks integer {field}: {values}") from error


def run(pipe_name: str, timeout_seconds: float) -> dict[str, Any]:
    queued = parse_key_values(lua(pipe_name, QUEUE_GRANT, timeout=12.0))
    content_id = integer(queued, "content_id")
    recipe_uid = integer(queued, "recipe_uid")
    request_id = integer(queued, "request_id")
    before_count = integer(queued, "before_count")
    if content_id != EXPECTED_CONTENT_ID or recipe_uid <= 0 or request_id <= 0:
        raise VerifyFailure(f"item grant queue contract differs: {queued}")

    deadline = time.monotonic() + timeout_seconds
    after_count = before_count
    while True:
        observed = parse_key_values(
            lua(pipe_name, inventory_count_probe(recipe_uid), timeout=5.0)
        )
        after_count = integer(observed, "after_count")
        if after_count >= before_count + 1:
            break
        if time.monotonic() >= deadline:
            raise VerifyFailure(
                "authoritative item grant did not increase the local recipe count: "
                f"before={before_count} after={after_count} request_id={request_id}"
            )
        time.sleep(0.2)

    return {
        "ok": True,
        "pipe": pipe_name,
        "content_id": content_id,
        "recipe_uid": recipe_uid,
        "request_id": request_id,
        "before_count": before_count,
        "after_count": after_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipe", default=DEFAULT_PIPE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument(
        "--confirm-mutation",
        action="store_true",
        help="confirm that the verifier may add one Pentaclostic Ring",
    )
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False, "pipe": args.pipe}
    if not args.confirm_mutation:
        result["error"] = "refusing inventory mutation without --confirm-mutation"
        return_code = 2
    elif args.timeout_seconds <= 0 or args.timeout_seconds > 60:
        result["error"] = "--timeout-seconds must be greater than 0 and at most 60"
        return_code = 2
    else:
        try:
            result = run(args.pipe, args.timeout_seconds)
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
