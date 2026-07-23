#!/usr/bin/env python3
"""Verify authority-routed Lua scene control across a disposable local pair."""

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
OUTPUT = ROOT / "runtime" / "lua_scene_multiplayer_verification.json"
ACCEPTANCE_MOD_ID = "sample.lua.scene_lab"
PRIVATE_REGION_INDEX = 2
HUB_REGION_INDEX = 0
ARENA_REGION_INDEX = 5


STATE_PROBE = f"""
local mod = assert(sd.runtime.get_mod())
local scene = assert(sd.scene.get_state(), "scene state unavailable")
local host_participant = sd.bots.get_participant_state({HOST_ID})
local multiplayer = assert(sd.runtime.get_multiplayer_state())
local host_runtime = nil
for _, participant in ipairs(multiplayer.participants or {{}}) do
  if tonumber(participant.participant_id) == {HOST_ID} then
    host_runtime = participant
    break
  end
end
local local_host_scene_kind = ""
if scene.kind == "hub" then
  local_host_scene_kind = "SharedHub"
elseif scene.kind == "arena" then
  local_host_scene_kind = "Run"
elseif scene.kind ~= "transition" then
  local_host_scene_kind = "PrivateRegion"
end
local local_host_scene_region_index =
  local_host_scene_kind == "Run" and -1 or scene.region_index
local local_host_scene_region_type_id =
  local_host_scene_kind == "Run" and -1 or scene.region_type_id
local host_scene_kind =
  host_participant and host_participant.scene and
  host_participant.scene.kind or
  host_runtime and host_runtime.scene_kind or local_host_scene_kind
local host_scene_region_index =
  host_participant and host_participant.scene and
  host_participant.scene.region_index or
  sd.state.is_authority() and local_host_scene_region_index or -999
local host_scene_region_type_id =
  host_participant and host_participant.scene and
  host_participant.scene.region_type_id or
  sd.state.is_authority() and local_host_scene_region_type_id or -999
local namespace_count = 0
local namespace_exact = true
for name, value in pairs(sd.scene) do
  namespace_count = namespace_count + 1
  if (name ~= "get_state" and name ~= "switch_region") or
      type(value) ~= "function" then
    namespace_exact = false
  end
end
namespace_exact = namespace_exact and namespace_count == 2
local raw_addresses_absent = true
for _, key in ipairs({{
  "id", "scene_id", "world_id", "arena_id", "region_state_id",
  "gameplay_scene_address", "world_address", "arena_address",
  "region_state_address",
}}) do
  if scene[key] ~= nil then raw_addresses_absent = false end
end
print("mod_id=" .. tostring(mod.id))
print("read_capability=" .. tostring(
  sd.runtime.has_capability("scene.read")))
print("switch_capability=" .. tostring(
  sd.runtime.has_capability("scene.switch.authority")))
print("authority=" .. tostring(sd.state.is_authority()))
print("kind=" .. tostring(scene.kind))
print("name=" .. tostring(scene.name))
print("region_index=" .. tostring(scene.region_index))
print("region_type_id=" .. tostring(scene.region_type_id))
print("transitioning=" .. tostring(scene.transitioning))
print("state_authority=" .. tostring(scene.is_authority))
print("can_switch_region=" .. tostring(scene.can_switch_region))
print("can_enter_run=" .. tostring(scene.can_enter_run))
print("namespace_exact=" .. tostring(namespace_exact))
print("raw_addresses_absent=" .. tostring(raw_addresses_absent))
print("host_runtime_row_found=" .. tostring(host_runtime ~= nil))
print("host_participant_found=" .. tostring(host_participant ~= nil))
print("host_scene_kind=" .. tostring(host_scene_kind))
print("host_scene_region_index=" .. tostring(host_scene_region_index))
print("host_scene_region_type_id=" .. tostring(host_scene_region_type_id))
"""


CLIENT_REJECTION_PROBE = f"""
local ok, error_message = pcall(sd.scene.switch_region, {PRIVATE_REGION_INDEX})
local scene = assert(sd.scene.get_state())
print("rejected=" .. tostring(not ok))
print("authority_error=" .. tostring(
  type(error_message) == "string" and
  string.find(error_message, "simulation authority", 1, true) ~= nil))
print("region_index=" .. tostring(scene.region_index))
print("transitioning=" .. tostring(scene.transitioning))
"""


PRIVATE_SWITCH_PROBE = f"""
assert(sd.state.is_authority(), "scene switch probe is not the authority")
local fraction_ok = pcall(sd.scene.switch_region, 1.5)
local negative_ok = pcall(sd.scene.switch_region, -1)
local too_large_ok = pcall(sd.scene.switch_region, 6)
local queued = sd.scene.switch_region({PRIVATE_REGION_INDEX})
print("queued=" .. tostring(queued))
print("fraction_rejected=" .. tostring(not fraction_ok))
print("negative_rejected=" .. tostring(not negative_ok))
print("too_large_rejected=" .. tostring(not too_large_ok))
"""


HUB_SWITCH_PROBE = f"""
assert(sd.state.is_authority(), "hub switch probe is not the authority")
print("queued=" .. tostring(sd.scene.switch_region({HUB_REGION_INDEX})))
"""


RUN_SWITCH_PROBE = f"""
assert(sd.state.is_authority(), "run switch probe is not the authority")
print("queued=" .. tostring(sd.scene.switch_region({ARENA_REGION_INDEX})))
"""


ARENA_EXIT_REJECTION_PROBE = f"""
local ok, error_message = pcall(sd.scene.switch_region, {HUB_REGION_INDEX})
local scene = assert(sd.scene.get_state())
print("authority=" .. tostring(sd.state.is_authority()))
print("rejected=" .. tostring(not ok))
print("authority_error=" .. tostring(
  type(error_message) == "string" and
  string.find(error_message, "simulation authority", 1, true) ~= nil))
print("stock_leave_error=" .. tostring(
  type(error_message) == "string" and
  string.find(error_message, "stock UI Leave Game", 1, true) ~= nil))
print("kind=" .. tostring(scene.kind))
print("region_index=" .. tostring(scene.region_index))
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


def _base_state_matches(
    values: dict[str, str],
    *,
    authority: bool,
) -> bool:
    return (
        values.get("mod_id") == ACCEPTANCE_MOD_ID
        and values.get("read_capability") == "true"
        and values.get("switch_capability") == "true"
        and values.get("authority") == ("true" if authority else "false")
        and values.get("state_authority")
        == ("true" if authority else "false")
        and values.get("transitioning") == "false"
        and values.get("namespace_exact") == "true"
        and values.get("raw_addresses_absent") == "true"
        and values.get("host_runtime_row_found") == "true"
        and values.get("host_participant_found")
        == ("false" if authority else "true")
    )


def hub_state_matches(
    values: dict[str, str],
    *,
    authority: bool,
) -> bool:
    try:
        return (
            _base_state_matches(values, authority=authority)
            and values.get("kind") == "hub"
            and values.get("name") == "hub"
            and _int_value(values, "region_index") == HUB_REGION_INDEX
            and values.get("can_switch_region")
            == ("true" if authority else "false")
            and values.get("can_enter_run")
            == ("true" if authority else "false")
            and values.get("host_scene_kind") == "SharedHub"
            and _int_value(values, "host_scene_region_index")
            == HUB_REGION_INDEX
        )
    except RuntimeError:
        return False


def private_state_matches(
    values: dict[str, str],
    *,
    authority: bool,
) -> bool:
    try:
        return (
            _base_state_matches(values, authority=authority)
            and values.get("kind") in ("region", "shop")
            and bool(values.get("name"))
            and values.get("name") != "transition"
            and _int_value(values, "region_index") == PRIVATE_REGION_INDEX
            and values.get("can_switch_region")
            == ("true" if authority else "false")
            and values.get("can_enter_run") == "false"
            and values.get("host_scene_kind") == "PrivateRegion"
            and _int_value(values, "host_scene_region_index")
            == PRIVATE_REGION_INDEX
        )
    except RuntimeError:
        return False


def arena_state_matches(
    values: dict[str, str],
    *,
    authority: bool,
) -> bool:
    try:
        return (
            _base_state_matches(values, authority=authority)
            and values.get("kind") == "arena"
            and values.get("name") == "testrun"
            and _int_value(values, "region_index") == ARENA_REGION_INDEX
            and values.get("can_switch_region") == "false"
            and values.get("can_enter_run") == "false"
            and values.get("host_scene_kind") == "Run"
            and _int_value(values, "host_scene_region_index") == -1
        )
    except RuntimeError:
        return False


def switch_request_matches(
    values: dict[str, str],
    *,
    validate_range: bool = False,
) -> bool:
    if values.get("queued") != "true":
        return False
    if not validate_range:
        return True
    return all(
        values.get(name) == "true"
        for name in (
            "fraction_rejected",
            "negative_rejected",
            "too_large_rejected",
        )
    )


def arena_exit_rejection_matches(
    values: dict[str, str],
    *,
    authority: bool,
) -> bool:
    try:
        return (
            values.get("authority") == ("true" if authority else "false")
            and values.get("rejected") == "true"
            and values.get("authority_error")
            == ("false" if authority else "true")
            and values.get("stock_leave_error")
            == ("true" if authority else "false")
            and values.get("kind") == "arena"
            and _int_value(values, "region_index") == ARENA_REGION_INDEX
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


def _poll_states(
    peers: list[tuple[str, str]],
    predicate: Callable[..., bool],
    *,
    timeout: float,
    description: str,
) -> list[dict[str, Any]]:
    return [
        _poll_probe(
            peer,
            STATE_PROBE,
            lambda values, authority=index == 0: predicate(
                values,
                authority=authority,
            ),
            timeout=timeout,
            description=description,
        )
        for index, peer in enumerate(peers)
    ]


def run(
    clients: list[tuple[str, str]],
    *,
    launch: bool,
    timeout: float,
) -> dict[str, Any]:
    if not launch:
        raise RuntimeError("Lua scene acceptance requires --launch-pair")
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
    }
    launched_process_ids: list[int] = []
    try:
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

        result["initial_hub"] = _poll_states(
            peers,
            hub_state_matches,
            timeout=timeout,
            description="initial shared hub scene",
        )

        client_rejection = _run_probe(client, CLIENT_REJECTION_PROBE)
        result["client_rejection"] = client_rejection
        rejection_values = _values(client_rejection)
        if not (
            rejection_values.get("rejected") == "true"
            and rejection_values.get("authority_error") == "true"
            and _int_value(rejection_values, "region_index")
            == HUB_REGION_INDEX
            and rejection_values.get("transitioning") == "false"
        ):
            raise RuntimeError(
                "client scene mutation was not authority-rejected: "
                f"{client_rejection}"
            )

        private_request = _run_probe(host, PRIVATE_SWITCH_PROBE)
        result["private_request"] = private_request
        if not switch_request_matches(
            _values(private_request),
            validate_range=True,
        ):
            raise RuntimeError(
                f"authority private-region request failed: {private_request}"
            )
        result["private_region"] = _poll_states(
            peers,
            private_state_matches,
            timeout=timeout,
            description="authenticated private-region convergence",
        )

        hub_request = _run_probe(host, HUB_SWITCH_PROBE)
        result["hub_request"] = hub_request
        if not switch_request_matches(_values(hub_request)):
            raise RuntimeError(
                f"authority shared-hub request failed: {hub_request}"
            )
        result["returned_hub"] = _poll_states(
            peers,
            hub_state_matches,
            timeout=timeout,
            description="authenticated shared-hub convergence",
        )

        run_request = _run_probe(host, RUN_SWITCH_PROBE)
        result["run_request"] = run_request
        if not switch_request_matches(_values(run_request)):
            raise RuntimeError(
                f"authority run-entry request failed: {run_request}"
            )
        result["arena"] = _poll_states(
            peers,
            arena_state_matches,
            timeout=timeout,
            description="authenticated arena convergence",
        )
        wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "testrun")
        wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "testrun")

        result["arena_exit_rejections"] = [
            _run_probe(peer, ARENA_EXIT_REJECTION_PROBE) for peer in peers
        ]
        for index, rejection in enumerate(result["arena_exit_rejections"]):
            if not arena_exit_rejection_matches(
                _values(rejection),
                authority=index == 0,
            ):
                raise RuntimeError(
                    f"raw arena exit was not rejected: {rejection}"
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
        help="confirm that the verifier may switch scenes in one isolated pair",
    )
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    if not args.confirm_mutation:
        result["error"] = "refusing scene mutations without --confirm-mutation"
        return_code = 2
    elif not args.launch_pair:
        result["error"] = "Lua scene acceptance requires --launch-pair"
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
