#!/usr/bin/env python3
"""Verify authority-owned Lua time control across a local multiplayer pair."""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any

from multiplayer_lua_probe import (
    DEFAULT_CLIENTS,
    parse_client,
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
    start_host_testrun_and_wait_for_clients,
    stop_game_processes,
    wait_for_remote,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_time_multiplayer_verification.json"
ACCEPTANCE_MOD_ID = "sample.lua.time_lab"

SNAPSHOT = """
local state = assert(sd.time.get_state())
print("scale=" .. tostring(state.scale))
print("paused=" .. tostring(state.paused))
print("revision=" .. tostring(state.revision))
print("step_sequence=" .. tostring(state.step_sequence))
print("pending_steps=" .. tostring(state.pending_steps))
print("replicated=" .. tostring(state.replicated))
print("authority_participant_id=" .. tostring(state.authority_participant_id))
print("run_nonce=" .. tostring(state.run_nonce))
print("requested_scale=" .. tostring(state.requested_scale))
"""

CLIENT_MUTATION_REJECTION = """
local before = assert(sd.time.get_state())
local set_ok, set_error = pcall(sd.time.set_scale, 0.25)
local step_ok, step_error = pcall(sd.time.step, 1)
local after = assert(sd.time.get_state())
print("set_rejected=" .. tostring(not set_ok))
print("step_rejected=" .. tostring(not step_ok))
print("set_authority_error=" .. tostring(
  type(set_error) == "string" and string.find(set_error, "authority", 1, true) ~= nil))
print("step_authority_error=" .. tostring(
  type(step_error) == "string" and string.find(step_error, "authority", 1, true) ~= nil))
print("unchanged=" .. tostring(
  before.revision == after.revision and
  before.scale == after.scale and
  before.step_sequence == after.step_sequence))
"""

STEP = """
local sequence = sd.time.step(3)
local state = assert(sd.time.get_state())
print("returned_step_sequence=" .. tostring(sequence))
print("scale=" .. tostring(state.scale))
print("paused=" .. tostring(state.paused))
print("revision=" .. tostring(state.revision))
print("step_sequence=" .. tostring(state.step_sequence))
print("pending_steps=" .. tostring(state.pending_steps))
print("replicated=" .. tostring(state.replicated))
print("authority_participant_id=" .. tostring(state.authority_participant_id))
print("run_nonce=" .. tostring(state.run_nonce))
print("requested_scale=" .. tostring(state.requested_scale))
"""

RELEASE = """
local ok, value = pcall(sd.time.set_scale, 1)
print("released=" .. tostring(ok and value == 1))
"""


def _set_scale_probe(scale: float) -> str:
    return f"""
local effective = sd.time.set_scale({scale})
local state = assert(sd.time.get_state())
print("effective=" .. tostring(effective))
print("scale=" .. tostring(state.scale))
print("paused=" .. tostring(state.paused))
print("revision=" .. tostring(state.revision))
print("step_sequence=" .. tostring(state.step_sequence))
print("pending_steps=" .. tostring(state.pending_steps))
print("replicated=" .. tostring(state.replicated))
print("authority_participant_id=" .. tostring(state.authority_participant_id))
print("run_nonce=" .. tostring(state.run_nonce))
print("requested_scale=" .. tostring(state.requested_scale))
"""


def _failed_exec(result: dict[str, Any]) -> str | None:
    if result.get("returncode") == 0:
        return None
    return str(
        result.get("stderr") or result.get("stdout") or "Lua exec failed"
    ).strip()


def _int_value(values: dict[str, str], name: str) -> int:
    try:
        return int(values.get(name, ""))
    except ValueError as error:
        raise RuntimeError(f"invalid {name}: {values}") from error


def _float_value(values: dict[str, str], name: str) -> float:
    try:
        value = float(values.get(name, ""))
    except ValueError as error:
        raise RuntimeError(f"invalid {name}: {values}") from error
    if not math.isfinite(value):
        raise RuntimeError(f"invalid {name}: {values}")
    return value


def state_matches(
    values: dict[str, str],
    *,
    scale: float,
    revision: int,
    step_sequence: int | None,
    replicated: bool,
    run_nonce: int,
    requested_scale: float | None,
) -> bool:
    try:
        requested_value = values.get("requested_scale")
        requested_matches = (
            requested_value == "nil"
            if requested_scale is None
            else math.isclose(
                float(requested_value or ""),
                requested_scale,
                rel_tol=0.0,
                abs_tol=0.000001,
            )
        )
        return (
            math.isclose(
                _float_value(values, "scale"),
                scale,
                rel_tol=0.0,
                abs_tol=0.000001,
            )
            and _int_value(values, "revision") == revision
            and (
                step_sequence is None
                or _int_value(values, "step_sequence") == step_sequence
            )
            and values.get("replicated") == ("true" if replicated else "false")
            and _int_value(values, "authority_participant_id") == HOST_ID
            and _int_value(values, "run_nonce") == run_nonce
            and requested_matches
        )
    except (RuntimeError, ValueError):
        return False


def _run_probe(
    client: tuple[str, str],
    code: str,
) -> dict[str, Any]:
    result = run_lua_client(client[0], client[1], code, timeout=12.0)
    failure = _failed_exec(result)
    if failure:
        raise RuntimeError(failure)
    return result


def _poll_state(
    client: tuple[str, str],
    *,
    scale: float,
    revision: int,
    step_sequence: int | None,
    replicated: bool,
    run_nonce: int,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = run_lua_client(client[0], client[1], SNAPSHOT, timeout=12.0)
        values = last.get("values", {})
        if (
            _failed_exec(last) is None
            and isinstance(values, dict)
            and state_matches(
                values,
                scale=scale,
                revision=revision,
                step_sequence=step_sequence,
                replicated=replicated,
                run_nonce=run_nonce,
                requested_scale=None,
            )
        ):
            return last
        time.sleep(0.1)
    raise RuntimeError(
        f"Lua time state did not converge for {client[0]}: "
        f"scale={scale} revision={revision} step_sequence={step_sequence} "
        f"last={last}"
    )


def _require_host_state(
    result: dict[str, Any],
    *,
    scale: float,
    minimum_revision: int,
    run_nonce: int,
) -> tuple[int, int]:
    values = result.get("values", {})
    if not isinstance(values, dict):
        raise RuntimeError(f"Lua time host state is malformed: {result}")
    revision = _int_value(values, "revision")
    step_sequence = _int_value(values, "step_sequence")
    if revision <= minimum_revision:
        raise RuntimeError(
            f"Lua time host revision did not advance past {minimum_revision}: {values}"
        )
    if not state_matches(
        values,
        scale=scale,
        revision=revision,
        step_sequence=step_sequence,
        replicated=False,
        run_nonce=run_nonce,
        requested_scale=None if scale == 1.0 else scale,
    ):
        raise RuntimeError(f"Lua time host state mismatch: {values}")
    return revision, step_sequence


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
    host_time_touched = False
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
            result["run"] = start_host_testrun_and_wait_for_clients(
                timeout=timeout,
            )

        initial_host = _run_probe(host, SNAPSHOT)
        result["initial_host"] = initial_host
        host_values = initial_host.get("values", {})
        if not isinstance(host_values, dict):
            raise RuntimeError(f"Lua time initial host state is malformed: {initial_host}")
        initial_revision = _int_value(host_values, "revision")
        initial_step_sequence = _int_value(host_values, "step_sequence")
        run_nonce = _int_value(host_values, "run_nonce")
        if run_nonce <= 0 or not state_matches(
            host_values,
            scale=1.0,
            revision=initial_revision,
            step_sequence=initial_step_sequence,
            replicated=False,
            run_nonce=run_nonce,
            requested_scale=None,
        ):
            raise RuntimeError(f"Lua time initial host state mismatch: {host_values}")

        result["initial_client"] = _poll_state(
            client,
            scale=1.0,
            revision=initial_revision,
            step_sequence=initial_step_sequence,
            replicated=True,
            run_nonce=run_nonce,
            timeout=timeout,
        )

        client_rejection = _run_probe(client, CLIENT_MUTATION_REJECTION)
        result["client_mutation_rejection"] = client_rejection
        rejection_values = client_rejection.get("values", {})
        for name in (
            "set_rejected",
            "step_rejected",
            "set_authority_error",
            "step_authority_error",
            "unchanged",
        ):
            if rejection_values.get(name) != "true":
                raise RuntimeError(
                    f"Lua time client mutation was not rejected by authority: "
                    f"{rejection_values}"
                )

        host_time_touched = True
        slow = _run_probe(host, _set_scale_probe(0.5))
        result["host_slow"] = slow
        slow_revision, slow_step_sequence = _require_host_state(
            slow,
            scale=0.5,
            minimum_revision=initial_revision,
            run_nonce=run_nonce,
        )
        result["client_slow"] = _poll_state(
            client,
            scale=0.5,
            revision=slow_revision,
            step_sequence=slow_step_sequence,
            replicated=True,
            run_nonce=run_nonce,
            timeout=timeout,
        )

        paused = _run_probe(host, _set_scale_probe(0.0))
        result["host_paused"] = paused
        pause_revision, pause_step_sequence = _require_host_state(
            paused,
            scale=0.0,
            minimum_revision=slow_revision,
            run_nonce=run_nonce,
        )
        result["client_paused"] = _poll_state(
            client,
            scale=0.0,
            revision=pause_revision,
            step_sequence=pause_step_sequence,
            replicated=True,
            run_nonce=run_nonce,
            timeout=timeout,
        )

        stepped = _run_probe(host, STEP)
        result["host_stepped"] = stepped
        step_revision, step_sequence = _require_host_state(
            stepped,
            scale=0.0,
            minimum_revision=pause_revision,
            run_nonce=run_nonce,
        )
        stepped_values = stepped.get("values", {})
        if (
            step_sequence != pause_step_sequence + 3
            or _int_value(stepped_values, "returned_step_sequence")
            != step_sequence
        ):
            raise RuntimeError(f"Lua time host step sequence mismatch: {stepped_values}")
        result["client_stepped"] = _poll_state(
            client,
            scale=0.0,
            revision=step_revision,
            step_sequence=step_sequence,
            replicated=True,
            run_nonce=run_nonce,
            timeout=timeout,
        )

        resumed = _run_probe(host, _set_scale_probe(1.0))
        result["host_resumed"] = resumed
        resume_revision, _ = _require_host_state(
            resumed,
            scale=1.0,
            minimum_revision=step_revision,
            run_nonce=run_nonce,
        )
        result["client_resumed"] = _poll_state(
            client,
            scale=1.0,
            revision=resume_revision,
            # A normal authority snapshot can establish the resume revision
            # before the prompt control packet. Normal snapshots intentionally
            # omit cumulative steps, so exact sequence is proved above while
            # paused and is not a valid post-resume convergence requirement.
            step_sequence=None,
            replicated=True,
            run_nonce=run_nonce,
            timeout=timeout,
        )

        result["ok"] = True
        return result
    finally:
        if host_time_touched:
            try:
                result["release"] = _run_probe(host, RELEASE)
                if result["release"].get("values", {}).get("released") != "true":
                    result["ok"] = False
                    result["release_error"] = (
                        "Lua time cleanup did not restore normal speed: "
                        f"{result['release']}"
                    )
            except Exception as error:  # noqa: BLE001 - preserve cleanup evidence.
                result["ok"] = False
                result["release_error"] = str(error)
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
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    try:
        result = run(
            args.client or list(DEFAULT_CLIENTS),
            launch=args.launch_pair,
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
