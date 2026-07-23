#!/usr/bin/env python3
"""Verify authority-owned Lua run seeding across a disposable local pair."""

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
OUTPUT = ROOT / "runtime" / "lua_rng_multiplayer_verification.json"
ACCEPTANCE_MOD_ID = "sample.lua.rng_lab"
ACCEPTANCE_SEED = 0x1234567


INITIAL_PROBE = f"""
local mod = assert(sd.runtime.get_mod())
local namespace_count = 0
local namespace_exact = true
for name, value in pairs(sd.rng) do
  namespace_count = namespace_count + 1
  if (name ~= "get_seed" and name ~= "set_seed") or
      type(value) ~= "function" then
    namespace_exact = false
  end
end
namespace_exact = namespace_exact and namespace_count == 2
print("mod_id=" .. tostring(mod.id))
print("capability=" .. tostring(
  sd.runtime.has_capability("rng.run.seed")))
print("authority=" .. tostring(sd.state.is_authority()))
print("seed_nil=" .. tostring(sd.rng.get_seed() == nil))
print("namespace_exact=" .. tostring(namespace_exact))
"""


CLIENT_REJECTION_PROBE = f"""
local ok, error_message = pcall(sd.rng.set_seed, {ACCEPTANCE_SEED})
print("rejected=" .. tostring(not ok))
print("authority_error=" .. tostring(
  type(error_message) == "string" and
  string.find(error_message, "simulation authority", 1, true) ~= nil))
print("seed_nil=" .. tostring(sd.rng.get_seed() == nil))
"""


HOST_SET_PROBE = f"""
assert(sd.state.is_authority(), "run-seed probe is not the authority")
local accepted = sd.rng.set_seed({ACCEPTANCE_SEED})
local zero_ok = pcall(sd.rng.set_seed, 0)
local large_ok = pcall(sd.rng.set_seed, 0x40000000)
local fraction_ok = pcall(sd.rng.set_seed, 1.5)
print("accepted=" .. tostring(accepted))
print("observed=" .. tostring(sd.rng.get_seed()))
print("zero_rejected=" .. tostring(not zero_ok))
print("large_rejected=" .. tostring(not large_ok))
print("fraction_rejected=" .. tostring(not fraction_ok))
"""


SEED_CONVERGENCE_PROBE = f"""
local multiplayer = assert(sd.runtime.get_multiplayer_state())
local authority_row = nil
for _, participant in ipairs(multiplayer.participants or {{}}) do
  if tonumber(participant.participant_id) == {HOST_ID} then
    authority_row = participant
    break
  end
end
print("authority=" .. tostring(sd.state.is_authority()))
print("local_seed=" .. tostring(sd.rng.get_seed() or 0))
print("authority_row_found=" .. tostring(authority_row ~= nil))
print("authority_run_nonce=" .. tostring(
  authority_row and authority_row.run_nonce or 0))
print("authority_scene_kind=" .. tostring(
  authority_row and authority_row.scene_kind or ""))
"""


RUN_STATE_PROBE = f"""
local multiplayer = assert(sd.runtime.get_multiplayer_state())
local owner = nil
local owner_count = 0
for _, participant in ipairs(multiplayer.participants or {{}}) do
  if participant.is_owner then
    owner = participant
    owner_count = owner_count + 1
  end
end
local scene = sd.world.get_scene()
local set_ok, set_error = pcall(sd.rng.set_seed, {ACCEPTANCE_SEED + 1})
print("authority=" .. tostring(sd.state.is_authority()))
print("seed=" .. tostring(sd.rng.get_seed() or 0))
print("owner_count=" .. tostring(owner_count))
print("runtime_valid=" .. tostring(owner ~= nil and owner.runtime_valid))
print("in_run=" .. tostring(owner ~= nil and owner.in_run))
print("run_nonce=" .. tostring(owner and owner.run_nonce or 0))
print("participant_scene_kind=" .. tostring(
  owner and owner.scene_kind or ""))
print("world_scene=" .. tostring(
  scene and (scene.name or scene.kind) or ""))
print("set_rejected=" .. tostring(not set_ok))
print("authority_error=" .. tostring(
  type(set_error) == "string" and
  string.find(set_error, "simulation authority", 1, true) ~= nil))
print("in_run_error=" .. tostring(
  type(set_error) == "string" and
  string.find(set_error, "before entering a run", 1, true) ~= nil))
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


def initial_state_matches(
    values: dict[str, str],
    *,
    authority: bool,
) -> bool:
    return (
        values.get("mod_id") == ACCEPTANCE_MOD_ID
        and values.get("capability") == "true"
        and values.get("authority") == ("true" if authority else "false")
        and values.get("seed_nil") == "true"
        and values.get("namespace_exact") == "true"
    )


def seed_converged(
    values: dict[str, str],
    *,
    authority: bool,
) -> bool:
    try:
        expected_local_seed = ACCEPTANCE_SEED if authority else 0
        return (
            values.get("authority") == ("true" if authority else "false")
            and _int_value(values, "local_seed") == expected_local_seed
            and values.get("authority_row_found") == "true"
            and _int_value(values, "authority_run_nonce")
            == ACCEPTANCE_SEED
            and values.get("authority_scene_kind") == "SharedHub"
        )
    except RuntimeError:
        return False


def run_state_matches(
    values: dict[str, str],
    *,
    authority: bool,
) -> bool:
    try:
        expected_authority_error = "false" if authority else "true"
        expected_in_run_error = "true" if authority else "false"
        return (
            values.get("authority") == ("true" if authority else "false")
            and _int_value(values, "seed") == ACCEPTANCE_SEED
            and _int_value(values, "owner_count") == 1
            and values.get("runtime_valid") == "true"
            and values.get("in_run") == "true"
            and _int_value(values, "run_nonce") == ACCEPTANCE_SEED
            and values.get("participant_scene_kind") == "Run"
            and values.get("world_scene") == "testrun"
            and values.get("set_rejected") == "true"
            and values.get("authority_error") == expected_authority_error
            and values.get("in_run_error") == expected_in_run_error
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
        raise RuntimeError("Lua RNG acceptance requires --launch-pair")
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
        "seed": ACCEPTANCE_SEED,
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

        result["initial"] = [
            _poll_probe(
                peer,
                INITIAL_PROBE,
                lambda values, authority=index == 0: initial_state_matches(
                    values,
                    authority=authority,
                ),
                timeout=timeout,
                description="fresh Lua run-seed state",
            )
            for index, peer in enumerate(peers)
        ]

        client_rejection = _run_probe(client, CLIENT_REJECTION_PROBE)
        result["client_rejection"] = client_rejection
        rejection_values = _values(client_rejection)
        if not (
            rejection_values.get("rejected") == "true"
            and rejection_values.get("authority_error") == "true"
            and rejection_values.get("seed_nil") == "true"
        ):
            raise RuntimeError(
                "client replaced or accepted the host run seed: "
                f"{client_rejection}"
            )

        host_set = _run_probe(host, HOST_SET_PROBE)
        result["host_set"] = host_set
        host_set_values = _values(host_set)
        if not (
            _int_value(host_set_values, "accepted") == ACCEPTANCE_SEED
            and _int_value(host_set_values, "observed") == ACCEPTANCE_SEED
            and host_set_values.get("zero_rejected") == "true"
            and host_set_values.get("large_rejected") == "true"
            and host_set_values.get("fraction_rejected") == "true"
        ):
            raise RuntimeError(f"host run-seed validation differs: {host_set}")

        result["pre_run_convergence"] = [
            _poll_probe(
                peer,
                SEED_CONVERGENCE_PROBE,
                lambda values, authority=index == 0: seed_converged(
                    values,
                    authority=authority,
                ),
                timeout=timeout,
                description="authenticated pre-run seed publication",
            )
            for index, peer in enumerate(peers)
        ]

        result["run"] = start_host_testrun_and_wait_for_clients(
            timeout=timeout,
        )
        wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "testrun")
        wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "testrun")

        result["applied"] = [
            _poll_probe(
                peer,
                RUN_STATE_PROBE,
                lambda values, authority=index == 0: run_state_matches(
                    values,
                    authority=authority,
                ),
                timeout=timeout,
                description="native-applied run seed",
            )
            for index, peer in enumerate(peers)
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
        help="confirm that the verifier may seed and start one isolated run",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    if not args.confirm_mutation:
        result["error"] = "refusing run-seed mutations without --confirm-mutation"
        return_code = 2
    elif not args.launch_pair:
        result["error"] = "Lua RNG acceptance requires --launch-pair"
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
