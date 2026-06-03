#!/usr/bin/env python3
"""Verify that a client applies host world snapshots to local scene actors."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from multiplayer_lua_probe import DEFAULT_CLIENTS, parse_client, run_all  # noqa: E402
from verify_local_multiplayer_sync import disable_bots, launch_pair, stop_games  # noqa: E402

RUNTIME_OUTPUT = ROOT / "runtime" / "world_snapshot_reconciliation.json"


LUA_VERIFY = r"""
local function emit(k, v)
  print(k .. "=" .. tostring(v))
end

local function scene_name()
  local s = sd.world.get_scene()
  return tostring(s and (s.name or s.kind) or "")
end

local function finite(v)
  return type(v) == "number" and v == v and v ~= math.huge and v ~= -math.huge
end

local function createable_hub_actor_type(type_id)
  return type_id == 0x1389 or type_id == 0x138A or type_id == 0x138B or
         type_id == 0x138C or type_id == 0x138D or type_id == 0x138F or
         type_id == 0x1390
end

local actors = sd.world.list_actors() or {}
local local_by_address = {}
local local_replicable = 0
local local_createable_hub_actors = 0
for _, actor in ipairs(actors) do
  local type_id = tonumber(actor.object_type_id) or 0
  local actor_address = tonumber(actor.actor_address) or 0
  if actor_address ~= 0 and type_id ~= 0 and type_id ~= 1 and finite(tonumber(actor.x)) and finite(tonumber(actor.y)) then
    local_by_address[actor_address] = actor
    local_replicable = local_replicable + 1
    if createable_hub_actor_type(type_id) then
      local_createable_hub_actors = local_createable_hub_actors + 1
    end
  end
end

local replicated = sd.world.get_replicated_actors and sd.world.get_replicated_actors() or nil
local binding_by_id = {}
if replicated ~= nil and replicated.bindings ~= nil then
  for _, binding in ipairs(replicated.bindings) do
    local network_id = tonumber(binding.network_actor_id) or 0
    local actor_address = tonumber(binding.local_actor_address) or 0
    if network_id ~= 0 and actor_address ~= 0 and binding.matched and not binding.parked then
      binding_by_id[network_id] = binding
    end
  end
end
emit("scene", scene_name())
emit("local_replicable", local_replicable)
emit("local_createable_hub_actors", local_createable_hub_actors)
emit("replicated_valid", replicated ~= nil)
emit("replicated_count", replicated and replicated.actor_count or 0)
emit("replicated_total_count", replicated and replicated.actor_total_count or 0)
emit("replicated_truncated", replicated and replicated.truncated or false)
emit("apply_valid", replicated and replicated.apply_valid or false)
emit("apply_matched", replicated and replicated.matched_actor_count or 0)
emit("apply_created", replicated and replicated.created_actor_count or 0)
emit("apply_created_total", replicated and replicated.created_actor_total_count or 0)
emit("apply_transform_writes", replicated and replicated.transform_write_count or 0)
emit("apply_presentation_writes", replicated and replicated.presentation_write_count or 0)
emit("apply_parked", replicated and replicated.parked_actor_count or 0)
emit("apply_removed", replicated and replicated.removed_actor_count or 0)
emit("apply_remove_failed", replicated and replicated.failed_remove_actor_count or 0)
emit("authority", replicated and replicated.authority_participant_id or 0)

local compared = 0
local within_4 = 0
local within_16 = 0
local within_64 = 0
local max_distance = 0.0
local missing_createable_hub_actors = 0
local replicated_createable_hub_actors = 0
if replicated ~= nil and replicated.actors ~= nil then
  for _, actor in ipairs(replicated.actors) do
    local binding = binding_by_id[tonumber(actor.network_actor_id)]
    local local_actor = binding ~= nil and local_by_address[tonumber(binding.local_actor_address) or 0] or nil
    local type_id = tonumber(actor.object_type_id) or 0
    if createable_hub_actor_type(type_id) then
      replicated_createable_hub_actors = replicated_createable_hub_actors + 1
    end
    if local_actor == nil and replicated.scene_kind == "SharedHub" and createable_hub_actor_type(type_id) then
      missing_createable_hub_actors = missing_createable_hub_actors + 1
    end
    if local_actor ~= nil and finite(tonumber(actor.x)) and finite(tonumber(actor.y)) then
      compared = compared + 1
      local dx = (tonumber(local_actor.x) or 0) - (tonumber(actor.x) or 0)
      local dy = (tonumber(local_actor.y) or 0) - (tonumber(actor.y) or 0)
      local distance = math.sqrt(dx * dx + dy * dy)
      if distance <= 4.0 then within_4 = within_4 + 1 end
      if distance <= 16.0 then within_16 = within_16 + 1 end
      if distance <= 64.0 then within_64 = within_64 + 1 end
      if distance > max_distance then max_distance = distance end
    end
  end
end

emit("live_compared", compared)
emit("live_within_4", within_4)
emit("live_within_16", within_16)
emit("live_within_64", within_64)
emit("live_max_distance", string.format("%.3f", max_distance))
emit("missing_createable_hub_actors", missing_createable_hub_actors)
emit("replicated_createable_hub_actors", replicated_createable_hub_actors)
emit("extra_createable_hub_actors", math.max(0, local_createable_hub_actors - replicated_createable_hub_actors))
"""


def number(values: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        return float(values.get(key, default))
    except (TypeError, ValueError):
        return default


def verify_client(values: dict[str, str], max_distance: float) -> tuple[bool, list[str]]:
    failures: list[str] = []
    if values.get("replicated_valid") != "true":
        failures.append("client has no replicated world snapshot")
    if values.get("apply_valid") != "true":
        failures.append("client has not applied a replicated world snapshot")
    if number(values, "replicated_count") <= 0:
        failures.append("replicated snapshot has no actors")
    if number(values, "apply_matched") <= 0:
        failures.append("no local actors matched the authoritative snapshot")
    if number(values, "live_compared") <= 0:
        failures.append("could not compare replicated actors to live local actors")
    if number(values, "missing_createable_hub_actors") > 0:
        failures.append(
            "client is missing createable authoritative hub actor(s): "
            f"{int(number(values, 'missing_createable_hub_actors'))}"
        )
    if number(values, "apply_remove_failed") > 0:
        failures.append(
            "client failed to remove extra createable hub actor(s): "
            f"{int(number(values, 'apply_remove_failed'))}"
        )
    if number(values, "extra_createable_hub_actors") > 0:
        failures.append(
            "client still has extra createable hub actor(s): "
            f"{int(number(values, 'extra_createable_hub_actors'))}"
        )
    if number(values, "live_max_distance", max_distance + 1.0) > max_distance:
        failures.append(
            f"live actors are farther than {max_distance:g} units from replicated targets "
            f"(max={number(values, 'live_max_distance'):.3f})"
        )
    return not failures, failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--client",
        action="append",
        type=parse_client,
        help="Lua exec endpoint as NAME=PIPE. Defaults to local multiplayer host/client.",
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--attempts", type=int, default=8)
    parser.add_argument("--interval", type=float, default=0.25)
    parser.add_argument("--max-distance", type=float, default=64.0)
    parser.add_argument("--launch-pair", action="store_true", help="Launch and stop the default local host/client pair.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    clients = args.client or list(DEFAULT_CLIENTS)
    last_output: dict[str, object] = {}
    last_failures: list[str] = []
    launch_info: dict[str, object] | None = None
    try:
        if args.launch_pair:
            stop_games()
            launch_info = launch_pair()
            disable_bots()
            time.sleep(0.75)

        for attempt in range(max(args.attempts, 1)):
            results = run_all(clients, LUA_VERIFY, args.timeout)
            by_name = {
                str(result["name"]): {str(key): str(value) for key, value in result.get("values", {}).items()}
                for result in results
            }
            client_values = by_name.get("client", {})
            ok, failures = verify_client(client_values, args.max_distance)
            last_output = {
                "ok": ok,
                "attempt": attempt + 1,
                "clients": by_name,
                "failures": failures,
            }
            if launch_info is not None:
                last_output["launch"] = launch_info
            last_failures = failures
            if ok:
                break
            if attempt + 1 < max(args.attempts, 1):
                time.sleep(max(args.interval, 0.0))
    finally:
        if args.launch_pair:
            stop_games()

    if args.json:
        print(json.dumps(last_output, indent=2, sort_keys=True))
    else:
        print(json.dumps(last_output, indent=2, sort_keys=True))
        if last_failures:
            print("world snapshot reconciliation failed: " + "; ".join(last_failures), file=sys.stderr)

    RUNTIME_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_OUTPUT.write_text(json.dumps(last_output, indent=2, sort_keys=True), encoding="utf-8")

    return 0 if last_output.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
