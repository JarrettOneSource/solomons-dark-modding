#!/usr/bin/env python3
"""Verify Lua UI action classes across a local multiplayer pair."""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
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
OUTPUT = ROOT / "runtime" / "lua_ui_multiplayer_verification.json"
ACCEPTANCE_MOD_ID = "sample.lua.ui_authoring_lab"
SURFACE_ID = "acceptance.ui_route"
PRESENTATION_ACTION_ID = "presentation"
SIMULATION_ACTION_ID = "simulation"
STATE_KEY = "acceptance.ui_route.count"

REGISTER = f"""
if type(_G.__lua_ui_mp_surface) == "number" then
  pcall(sd.ui.destroy, _G.__lua_ui_mp_surface)
end
_G.__lua_ui_mp = {{
  presentation_count = 0,
  simulation_count = 0,
}}
_G.__lua_ui_mp_surface = sd.ui.create_surface({{
  id = {json.dumps(SURFACE_ID)},
  title = "Lua UI multiplayer acceptance",
  x = 0.25,
  y = 0.25,
  width = 0.5,
  height = 0.5,
}})
local panel = sd.ui.create_panel(_G.__lua_ui_mp_surface, {{
  id = "panel",
  x = 0.05,
  y = 0.15,
  width = 0.9,
  height = 0.75,
}})
sd.ui.create_button(panel, {{
  id = {json.dumps(PRESENTATION_ACTION_ID)},
  label = "Presentation",
  x = 0.1,
  y = 0.15,
  width = 0.8,
  height = 0.2,
  execution = "presentation",
  on_activate = function(action)
    _G.__lua_ui_mp.presentation_count =
      _G.__lua_ui_mp.presentation_count + 1
    _G.__lua_ui_mp.last_presentation = action
  end,
}})
sd.ui.create_button(panel, {{
  id = {json.dumps(SIMULATION_ACTION_ID)},
  label = "Simulation",
  x = 0.1,
  y = 0.55,
  width = 0.8,
  height = 0.2,
  execution = "simulation",
  on_activate = function(action)
    _G.__lua_ui_mp.simulation_count =
      _G.__lua_ui_mp.simulation_count + 1
    _G.__lua_ui_mp.last_simulation = action
    local value = sd.state.get({json.dumps(STATE_KEY)})
    if type(value) ~= "number" then value = 0 end
    sd.state.set({json.dumps(STATE_KEY)}, value + 1)
  end,
}})
assert(sd.ui.show(_G.__lua_ui_mp_surface))
print("registered=true")
print("authority=" .. tostring(sd.state.is_authority()))
"""

INITIALIZE = f"""
assert(sd.state.is_authority(), "initializer is not the authority")
local revision = sd.state.set({json.dumps(STATE_KEY)}, 0)
print("initialized=true")
print("revision=" .. tostring(revision))
"""

SNAPSHOT = f"""
local record = _G.__lua_ui_mp or {{}}
local presentation = record.last_presentation or {{}}
local simulation = record.last_simulation or {{}}
local shared = sd.state.get({json.dumps(STATE_KEY)})
print("authority=" .. tostring(sd.state.is_authority()))
print("shared_value=" .. tostring(shared))
print("state_revision=" .. tostring(sd.state.get_revision()))
print("presentation_count=" .. tostring(record.presentation_count or -1))
print("simulation_count=" .. tostring(record.simulation_count or -1))
print("presentation_surface=" .. tostring(presentation.surface_id))
print("presentation_action=" .. tostring(presentation.action_id))
print("presentation_execution=" .. tostring(presentation.execution))
print("presentation_participant_id=" .. tostring(presentation.participant_id))
print("presentation_request_id=" .. tostring(presentation.request_id))
print("presentation_routed=" .. tostring(presentation.routed))
print("simulation_surface=" .. tostring(simulation.surface_id))
print("simulation_action=" .. tostring(simulation.action_id))
print("simulation_execution=" .. tostring(simulation.execution))
print("simulation_participant_id=" .. tostring(simulation.participant_id))
print("simulation_request_id=" .. tostring(simulation.request_id))
print("simulation_routed=" .. tostring(simulation.routed))
"""

CLEANUP = f"""
local destroyed = true
if type(_G.__lua_ui_mp_surface) == "number" then
  destroyed = sd.ui.destroy(_G.__lua_ui_mp_surface)
end
_G.__lua_ui_mp_surface = nil
_G.__lua_ui_mp = nil
if sd.state.is_authority() then
  pcall(sd.state.delete, {json.dumps(STATE_KEY)})
end
print("cleaned=" .. tostring(destroyed))
"""


def _activation_probe(action_id: str) -> str:
    return f"""
local queued, request_id = sd.ui.perform({{
  surface_id = {json.dumps(SURFACE_ID)},
  action_id = {json.dumps(action_id)},
}})
print("queued=" .. tostring(queued))
print("request_id=" .. tostring(request_id))
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


def _positive_int(values: dict[str, str], name: str) -> int:
    value = _int_value(values, name)
    if value <= 0:
        raise RuntimeError(f"invalid {name}: {values}")
    return value


def snapshot_matches(
    values: dict[str, str],
    *,
    authority: bool,
    shared_value: int,
    presentation_count: int,
    simulation_count: int,
    presentation_participant_id: int | None = None,
    simulation_participant_id: int | None = None,
    simulation_routed: bool | None = None,
) -> bool:
    try:
        matches = (
            values.get("authority") == ("true" if authority else "false")
            and _int_value(values, "shared_value") == shared_value
            and _positive_int(values, "state_revision") > 0
            and _int_value(values, "presentation_count")
            == presentation_count
            and _int_value(values, "simulation_count") == simulation_count
        )
        if presentation_participant_id is not None:
            matches = matches and (
                values.get("presentation_surface") == SURFACE_ID
                and values.get("presentation_action")
                == PRESENTATION_ACTION_ID
                and values.get("presentation_execution") == "presentation"
                and _int_value(values, "presentation_participant_id")
                == presentation_participant_id
                and _positive_int(values, "presentation_request_id") > 0
                and values.get("presentation_routed") == "false"
            )
        if simulation_participant_id is not None:
            matches = matches and (
                simulation_routed is not None
                and values.get("simulation_surface") == SURFACE_ID
                and values.get("simulation_action") == SIMULATION_ACTION_ID
                and values.get("simulation_execution") == "simulation"
                and _int_value(values, "simulation_participant_id")
                == simulation_participant_id
                and _positive_int(values, "simulation_request_id") > 0
                and values.get("simulation_routed")
                == ("true" if simulation_routed else "false")
            )
        return matches
    except RuntimeError:
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


def _poll_snapshot(
    client: tuple[str, str],
    predicate: Callable[[dict[str, str]], bool],
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
            and predicate(values)
        ):
            return last
        time.sleep(0.1)
    raise RuntimeError(
        f"Lua UI multiplayer state did not converge for {client[0]}: {last}"
    )


def _activate(
    client: tuple[str, str],
    action_id: str,
) -> dict[str, Any]:
    result = _run_probe(client, _activation_probe(action_id))
    values = result.get("values", {})
    if not isinstance(values, dict) or values.get("queued") != "true":
        raise RuntimeError(f"Lua UI action was not queued: {result}")
    _positive_int(values, "request_id")
    return result


def _cleanup_succeeded(results: list[dict[str, Any]]) -> bool:
    return len(results) == 2 and all(
        _failed_exec(result) is None
        and result.get("values", {}).get("cleaned") == "true"
        for result in results
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
    registration_attempted = False
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

        registration_attempted = True
        registrations = run_all(clients[:2], REGISTER, timeout=12.0)
        result["registrations"] = registrations
        failures = [_failed_exec(peer) for peer in registrations]
        failures = [failure for failure in failures if failure]
        if failures:
            raise RuntimeError("; ".join(failures))
        roles = [
            peer.get("values", {}).get("authority")
            for peer in registrations
        ]
        if roles != ["true", "false"]:
            raise RuntimeError(f"unexpected authority roles: {roles}")
        if any(
            peer.get("values", {}).get("registered") != "true"
            for peer in registrations
        ):
            raise RuntimeError(f"Lua UI registration failed: {registrations}")

        initialization = _run_probe(host, INITIALIZE)
        result["initialization"] = initialization
        initialized = initialization.get("values", {})
        if initialized.get("initialized") != "true":
            raise RuntimeError(
                f"Lua UI shared-state initialization failed: {initialization}"
            )
        _positive_int(initialized, "revision")

        result["initial_host"] = _poll_snapshot(
            host,
            lambda values: snapshot_matches(
                values,
                authority=True,
                shared_value=0,
                presentation_count=0,
                simulation_count=0,
            ),
            timeout,
        )
        result["initial_client"] = _poll_snapshot(
            client,
            lambda values: snapshot_matches(
                values,
                authority=False,
                shared_value=0,
                presentation_count=0,
                simulation_count=0,
            ),
            timeout,
        )

        result["client_presentation_request"] = _activate(
            client,
            PRESENTATION_ACTION_ID,
        )
        result["client_presentation"] = _poll_snapshot(
            client,
            lambda values: snapshot_matches(
                values,
                authority=False,
                shared_value=0,
                presentation_count=1,
                simulation_count=0,
                presentation_participant_id=CLIENT_ID,
            ),
            timeout,
        )
        result["host_after_client_presentation"] = _poll_snapshot(
            host,
            lambda values: snapshot_matches(
                values,
                authority=True,
                shared_value=0,
                presentation_count=0,
                simulation_count=0,
            ),
            timeout,
        )

        result["client_simulation_request"] = _activate(
            client,
            SIMULATION_ACTION_ID,
        )
        result["host_routed_simulation"] = _poll_snapshot(
            host,
            lambda values: snapshot_matches(
                values,
                authority=True,
                shared_value=1,
                presentation_count=0,
                simulation_count=1,
                simulation_participant_id=CLIENT_ID,
                simulation_routed=True,
            ),
            timeout,
        )
        result["client_after_routed_simulation"] = _poll_snapshot(
            client,
            lambda values: snapshot_matches(
                values,
                authority=False,
                shared_value=1,
                presentation_count=1,
                simulation_count=0,
                presentation_participant_id=CLIENT_ID,
            ),
            timeout,
        )

        result["host_simulation_request"] = _activate(
            host,
            SIMULATION_ACTION_ID,
        )
        result["host_local_simulation"] = _poll_snapshot(
            host,
            lambda values: snapshot_matches(
                values,
                authority=True,
                shared_value=2,
                presentation_count=0,
                simulation_count=2,
                simulation_participant_id=HOST_ID,
                simulation_routed=False,
            ),
            timeout,
        )
        result["client_after_host_simulation"] = _poll_snapshot(
            client,
            lambda values: snapshot_matches(
                values,
                authority=False,
                shared_value=2,
                presentation_count=1,
                simulation_count=0,
                presentation_participant_id=CLIENT_ID,
            ),
            timeout,
        )

        result["ok"] = True
        return result
    finally:
        if registration_attempted:
            try:
                cleanup = run_all(clients[:2], CLEANUP, timeout=12.0)
                result["cleanup"] = cleanup
                if not _cleanup_succeeded(cleanup):
                    result["ok"] = False
                    result["cleanup_error"] = (
                        f"Lua UI multiplayer cleanup failed: {cleanup}"
                    )
            except Exception as error:  # noqa: BLE001 - preserve cleanup evidence.
                result["ok"] = False
                result["cleanup_error"] = str(error)
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
