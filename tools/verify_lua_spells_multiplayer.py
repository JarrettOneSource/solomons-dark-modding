#!/usr/bin/env python3
"""Verify registered Lua spell ownership and effects across a local pair."""

from __future__ import annotations

import argparse
import json
import math
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
OUTPUT = ROOT / "runtime" / "lua_spells_multiplayer_verification.json"
ACCEPTANCE_MOD_ID = "sample.lua.spells_registry_lab"
EXPECTED_CONTENT_ID = 8348995147374483494
EXPECTED_KEY = "gravity_well_field"
EXPECTED_RADIUS = 180.0
EXPECTED_DURATION_MS = 2400
MAX_REMOTE_RETIREMENT_SECONDS = 1.0


REGISTRY_STATUS = f"""
local mod = assert(sd.runtime.get_mod())
local spell = assert(
  sd.spells.get({EXPECTED_CONTENT_ID}),
  "Lua spell acceptance registration is unavailable")
local selection = sd.spells.get_selection()
local effects = sd.spells.get_effects()
print("mod_id=" .. tostring(mod.id))
print("authority=" .. tostring(sd.state.is_authority()))
print("content_id=" .. tostring(spell.id))
print("slot=" .. tostring(spell.slot))
print("has_on_cast=" .. tostring(spell.has_on_cast))
print("has_on_tick=" .. tostring(spell.has_on_tick))
print("has_on_hit=" .. tostring(spell.has_on_hit))
print("slot1_selected=" .. tostring(selection.secondary[1] ~= nil))
print("effect_count=" .. tostring(#effects))
"""

CLEAR_SELECTION = """
local selected = sd.spells.get_selection().secondary[1]
if selected ~= nil then
  assert(sd.spells.clear_selection("secondary", 1))
end
print("slot1_selected=" .. tostring(
  sd.spells.get_selection().secondary[1] ~= nil))
"""

SELECT_SLOT_ONE = f"""
local selected = sd.spells.select({EXPECTED_CONTENT_ID}, 1)
print("selected=" .. tostring(selected.selected))
print("content_id=" .. tostring(selected.id))
print("belt_slot=" .. tostring(selected.belt_slot))
"""

SELECTION_STATUS = f"""
local selected = sd.spells.get_selection().secondary[1]
print("slot1_selected=" .. tostring(selected ~= nil))
print("content_id=" .. tostring(selected and selected.id or 0))
"""

CLIENT_REMOTE_REJECTION = f"""
local before = #sd.spells.get_effects()
local ok, error_message = pcall(sd.spells.cast, {EXPECTED_CONTENT_ID}, {{
  participant_id = {HOST_ID},
  origin_x = 3000000,
  origin_y = 3000000,
  aim_x = 3000200,
  aim_y = 3000000,
}})
local after = #sd.spells.get_effects()
print("rejected=" .. tostring(not ok))
print("remote_owner_error=" .. tostring(
  type(error_message) == "string" and
  string.find(error_message, "connected remote participant", 1, true) ~= nil))
print("effect_count_unchanged=" .. tostring(before == after))
"""


def _cast_probe(owner_participant_id: int, origin_x: float, origin_y: float) -> str:
    aim_x = origin_x + 200.0
    return f"""
local cast = sd.spells.cast({EXPECTED_CONTENT_ID}, {{
  participant_id = {owner_participant_id},
  origin_x = {origin_x},
  origin_y = {origin_y},
  aim_x = {aim_x},
  aim_y = {origin_y},
}})
print("request_id=" .. tostring(cast.request_id))
print("content_id=" .. tostring(cast.content_id))
print("owner_participant_id=" .. tostring(cast.owner_participant_id))
print("local_owner=" .. tostring(cast.local_owner))
print("aim_x=" .. tostring({aim_x}))
print("aim_y=" .. tostring({origin_y}))
"""


def _effect_probe(request_id: int, owner_participant_id: int) -> str:
    return f"""
local effects = sd.spells.get_effects()
local row = nil
local matching = 0
for _, effect in ipairs(effects) do
  if tonumber(effect.request_id) == {request_id} and
      tonumber(effect.owner_participant_id) == {owner_participant_id} and
      tonumber(effect.content_id) == {EXPECTED_CONTENT_ID} then
    matching = matching + 1
    row = effect
  end
end
local raw_internals_absent = row ~= nil and
  row.actor_address == nil and row.config_address == nil and
  row.native_skill_id == nil and row.callback_reference == nil
print("effect_count=" .. tostring(#effects))
print("matching_count=" .. tostring(matching))
print("effect_id=" .. tostring(row and row.effect_id or 0))
print("request_id=" .. tostring(row and row.request_id or 0))
print("content_id=" .. tostring(row and row.content_id or 0))
print("owner_participant_id=" .. tostring(
  row and row.owner_participant_id or 0))
print("key=" .. tostring(row and row.key or ""))
print("x=" .. tostring(row and row.x or 0))
print("y=" .. tostring(row and row.y or 0))
print("velocity_x=" .. tostring(row and row.velocity_x or 0))
print("velocity_y=" .. tostring(row and row.velocity_y or 0))
print("radius=" .. tostring(row and row.radius or 0))
print("age_ms=" .. tostring(row and row.age_ms or 0))
print("remaining_ms=" .. tostring(row and row.remaining_ms or 0))
print("data_hits=" .. tostring(
  row and type(row.data) == "table" and row.data.hits or -1))
print("local_owner=" .. tostring(row ~= nil and row.local_owner))
print("raw_internals_absent=" .. tostring(raw_internals_absent))
"""


def _effect_absence_probe(request_id: int, owner_participant_id: int) -> str:
    return f"""
local effects = sd.spells.get_effects()
local matching = 0
for _, effect in ipairs(effects) do
  if tonumber(effect.request_id) == {request_id} and
      tonumber(effect.owner_participant_id) == {owner_participant_id} and
      tonumber(effect.content_id) == {EXPECTED_CONTENT_ID} then
    matching = matching + 1
  end
end
print("effect_count=" .. tostring(#effects))
print("matching_count=" .. tostring(matching))
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


def _positive_int(values: dict[str, str], name: str) -> int:
    value = _int_value(values, name)
    if value <= 0:
        raise RuntimeError(f"invalid {name}: {values}")
    return value


def _number_value(values: dict[str, str], name: str) -> float:
    try:
        value = float(values.get(name, ""))
    except ValueError as error:
        raise RuntimeError(f"invalid {name}: {values}") from error
    if not math.isfinite(value):
        raise RuntimeError(f"non-finite {name}: {values}")
    return value


def registry_matches(values: dict[str, str], *, authority: bool) -> bool:
    try:
        return (
            values.get("mod_id") == ACCEPTANCE_MOD_ID
            and values.get("authority") == ("true" if authority else "false")
            and _int_value(values, "content_id") == EXPECTED_CONTENT_ID
            and values.get("slot") == "secondary"
            and values.get("has_on_cast") == "true"
            and values.get("has_on_tick") == "true"
            and values.get("has_on_hit") == "true"
            and values.get("slot1_selected") == "false"
            and _int_value(values, "effect_count") == 0
        )
    except RuntimeError:
        return False


def cast_result_matches(
    values: dict[str, str],
    *,
    owner_participant_id: int,
    local_owner: bool,
) -> bool:
    try:
        return (
            _positive_int(values, "request_id") > 0
            and _int_value(values, "content_id") == EXPECTED_CONTENT_ID
            and _int_value(values, "owner_participant_id")
            == owner_participant_id
            and values.get("local_owner")
            == ("true" if local_owner else "false")
            and math.isfinite(_number_value(values, "aim_x"))
            and math.isfinite(_number_value(values, "aim_y"))
        )
    except RuntimeError:
        return False


def effect_matches(
    values: dict[str, str],
    *,
    request_id: int,
    owner_participant_id: int,
    local_owner: bool,
    aim_x: float,
    aim_y: float,
    effect_id: int | None = None,
    minimum_age_ms: int = 1,
    maximum_remaining_ms: int = EXPECTED_DURATION_MS,
) -> bool:
    try:
        observed_effect_id = _positive_int(values, "effect_id")
        return (
            _int_value(values, "effect_count") == 1
            and _int_value(values, "matching_count") == 1
            and (effect_id is None or observed_effect_id == effect_id)
            and _int_value(values, "request_id") == request_id
            and _int_value(values, "content_id") == EXPECTED_CONTENT_ID
            and _int_value(values, "owner_participant_id")
            == owner_participant_id
            and values.get("key") == EXPECTED_KEY
            and abs(_number_value(values, "x") - aim_x) <= 0.01
            and abs(_number_value(values, "y") - aim_y) <= 0.01
            and abs(_number_value(values, "velocity_x")) <= 0.001
            and abs(_number_value(values, "velocity_y")) <= 0.001
            and 0.0 < _number_value(values, "radius") < EXPECTED_RADIUS
            and minimum_age_ms
            <= _int_value(values, "age_ms")
            < EXPECTED_DURATION_MS
            and 0
            < _int_value(values, "remaining_ms")
            <= maximum_remaining_ms
            and _int_value(values, "data_hits") == 0
            and values.get("local_owner")
            == ("true" if local_owner else "false")
            and values.get("raw_internals_absent") == "true"
        )
    except RuntimeError:
        return False


def effect_absent(values: dict[str, str]) -> bool:
    try:
        return (
            _int_value(values, "effect_count") == 0
            and _int_value(values, "matching_count") == 0
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
        time.sleep(0.05)
    raise RuntimeError(f"{description} did not converge for {client[0]}: {last}")


def _poll_selection(
    client: tuple[str, str],
    *,
    selected: bool,
    timeout: float,
) -> dict[str, Any]:
    return _poll_probe(
        client,
        SELECTION_STATUS,
        lambda values: (
            values.get("slot1_selected") == ("true" if selected else "false")
            and _int_value(values, "content_id")
            == (EXPECTED_CONTENT_ID if selected else 0)
        ),
        timeout=timeout,
        description=f"local spell selection selected={selected}",
    )


def _poll_effect(
    client: tuple[str, str],
    *,
    request_id: int,
    owner_participant_id: int,
    local_owner: bool,
    aim_x: float,
    aim_y: float,
    effect_id: int | None,
    timeout: float,
    minimum_age_ms: int = 1,
    maximum_remaining_ms: int = EXPECTED_DURATION_MS,
) -> dict[str, Any]:
    return _poll_probe(
        client,
        _effect_probe(request_id, owner_participant_id),
        lambda values: effect_matches(
            values,
            request_id=request_id,
            owner_participant_id=owner_participant_id,
            local_owner=local_owner,
            aim_x=aim_x,
            aim_y=aim_y,
            effect_id=effect_id,
            minimum_age_ms=minimum_age_ms,
            maximum_remaining_ms=maximum_remaining_ms,
        ),
        timeout=timeout,
        description=(
            f"Lua spell effect request={request_id} owner={owner_participant_id}"
        ),
    )


def _poll_effect_absent(
    client: tuple[str, str],
    *,
    request_id: int,
    owner_participant_id: int,
    timeout: float,
    stable_seconds: float = 0.15,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    stable_since: float | None = None
    last: dict[str, Any] = {}
    code = _effect_absence_probe(request_id, owner_participant_id)
    while time.monotonic() < deadline:
        last = run_lua_client(client[0], client[1], code, timeout=12.0)
        values = last.get("values", {})
        absent = (
            _failed_exec(last) is None
            and isinstance(values, dict)
            and effect_absent(values)
        )
        now = time.monotonic()
        if absent:
            if stable_since is None:
                stable_since = now
            elif now - stable_since >= stable_seconds:
                return last
        else:
            stable_since = None
        time.sleep(0.05)
    raise RuntimeError(
        f"Lua spell effect did not retire for {client[0]}: {last}"
    )


def _normalize_selections(
    peers: list[tuple[str, str]],
    *,
    timeout: float,
) -> list[dict[str, Any]]:
    for peer in peers:
        cleared = _run_probe(peer, CLEAR_SELECTION)
        if _values(cleared).get("slot1_selected") != "false":
            raise RuntimeError(f"Lua spell selection did not clear: {cleared}")
    return [
        _poll_selection(peer, selected=False, timeout=timeout)
        for peer in peers
    ]


def _verify_selection_is_local(
    host: tuple[str, str],
    client: tuple[str, str],
    *,
    timeout: float,
) -> dict[str, Any]:
    selected = _run_probe(host, SELECT_SLOT_ONE)
    selected_values = _values(selected)
    if not (
        selected_values.get("selected") == "true"
        and _int_value(selected_values, "content_id") == EXPECTED_CONTENT_ID
        and _int_value(selected_values, "belt_slot") == 1
    ):
        raise RuntimeError(f"Lua spell selection result differs: {selected}")
    try:
        return {
            "selected": selected,
            "host": _poll_selection(host, selected=True, timeout=timeout),
            "client": _poll_selection(client, selected=False, timeout=timeout),
        }
    finally:
        _run_probe(host, CLEAR_SELECTION)


def _exercise_cast(
    command_peer: tuple[str, str],
    owner_peer: tuple[str, str],
    observer_peer: tuple[str, str],
    *,
    owner_participant_id: int,
    command_is_local_owner: bool,
    origin_x: float,
    origin_y: float,
    timeout: float,
) -> dict[str, Any]:
    cast = _run_probe(
        command_peer,
        _cast_probe(owner_participant_id, origin_x, origin_y),
    )
    cast_values = _values(cast)
    if not cast_result_matches(
        cast_values,
        owner_participant_id=owner_participant_id,
        local_owner=command_is_local_owner,
    ):
        raise RuntimeError(f"Lua spell cast route differs: {cast}")
    request_id = _positive_int(cast_values, "request_id")
    aim_x = _number_value(cast_values, "aim_x")
    aim_y = _number_value(cast_values, "aim_y")

    owner_effect = _poll_effect(
        owner_peer,
        request_id=request_id,
        owner_participant_id=owner_participant_id,
        local_owner=True,
        aim_x=aim_x,
        aim_y=aim_y,
        effect_id=None,
        timeout=timeout,
    )
    effect_id = _positive_int(_values(owner_effect), "effect_id")
    observer_effect = _poll_effect(
        observer_peer,
        request_id=request_id,
        owner_participant_id=owner_participant_id,
        local_owner=False,
        aim_x=aim_x,
        aim_y=aim_y,
        effect_id=effect_id,
        timeout=timeout,
    )
    observer_effect_near_retirement = _poll_effect(
        observer_peer,
        request_id=request_id,
        owner_participant_id=owner_participant_id,
        local_owner=False,
        aim_x=aim_x,
        aim_y=aim_y,
        effect_id=effect_id,
        timeout=timeout,
        minimum_age_ms=EXPECTED_DURATION_MS - 300,
        maximum_remaining_ms=300,
    )

    owner_retired = _poll_effect_absent(
        owner_peer,
        request_id=request_id,
        owner_participant_id=owner_participant_id,
        timeout=max(timeout, EXPECTED_DURATION_MS / 1000.0 + 1.0),
    )
    remote_retirement_started = time.monotonic()
    observer_retired = _poll_effect_absent(
        observer_peer,
        request_id=request_id,
        owner_participant_id=owner_participant_id,
        timeout=MAX_REMOTE_RETIREMENT_SECONDS,
    )
    remote_retirement_seconds = time.monotonic() - remote_retirement_started
    if remote_retirement_seconds >= MAX_REMOTE_RETIREMENT_SECONDS:
        raise RuntimeError(
            "Lua spell remote effect retired only at or beyond the expiry "
            f"boundary: {remote_retirement_seconds:.3f}s"
        )

    return {
        "cast": cast,
        "request_id": request_id,
        "effect_id": effect_id,
        "owner_effect": owner_effect,
        "observer_effect": observer_effect,
        "observer_effect_near_retirement": observer_effect_near_retirement,
        "owner_retired": owner_retired,
        "observer_retired": observer_retired,
        "remote_retirement_seconds": round(remote_retirement_seconds, 3),
    }


def _best_effort_clear_selection(peers: list[tuple[str, str]]) -> None:
    for peer in peers:
        try:
            run_lua_client(peer[0], peer[1], CLEAR_SELECTION, timeout=5.0)
        except Exception:
            pass


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
    peers = [host, client]
    result: dict[str, Any] = {
        "ok": False,
        "launched_pair": launch,
        "host": host[0],
        "client": client[0],
    }
    launched_process_ids: list[int] = []
    selection_touched = not launch
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
            wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "testrun")
            wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "testrun")

        selection_touched = True
        result["selection_cleanup"] = _normalize_selections(
            peers,
            timeout=timeout,
        )
        result["registries"] = [
            _poll_probe(
                peer,
                REGISTRY_STATUS,
                lambda values, authority=index == 0: registry_matches(
                    values,
                    authority=authority,
                ),
                timeout=timeout,
                description="Lua spell registry and empty effect state",
            )
            for index, peer in enumerate(peers)
        ]
        result["local_selection"] = _verify_selection_is_local(
            host,
            client,
            timeout=timeout,
        )
        result["selection_after_clear"] = [
            _poll_selection(peer, selected=False, timeout=timeout)
            for peer in peers
        ]

        rejection = _run_probe(client, CLIENT_REMOTE_REJECTION)
        result["client_remote_rejection"] = rejection
        rejection_values = _values(rejection)
        if not (
            rejection_values.get("rejected") == "true"
            and rejection_values.get("remote_owner_error") == "true"
            and rejection_values.get("effect_count_unchanged") == "true"
        ):
            raise RuntimeError(
                f"Lua spell client remote-owner cast was not rejected: {rejection}"
            )

        result["host_owned"] = _exercise_cast(
            host,
            host,
            client,
            owner_participant_id=HOST_ID,
            command_is_local_owner=True,
            origin_x=1_000_000.0,
            origin_y=1_000_000.0,
            timeout=timeout,
        )
        result["client_owned_from_host"] = _exercise_cast(
            host,
            client,
            host,
            owner_participant_id=CLIENT_ID,
            command_is_local_owner=False,
            origin_x=2_000_000.0,
            origin_y=2_000_000.0,
            timeout=timeout,
        )
        result["ok"] = True
        return result
    finally:
        if selection_touched:
            _best_effort_clear_selection(peers)
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
    parser.add_argument(
        "--confirm-mutation",
        action="store_true",
        help="confirm that the verifier may dispatch bounded scripted effects",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    if not args.confirm_mutation:
        result["error"] = (
            "refusing scripted spell mutations without --confirm-mutation"
        )
        return_code = 2
    else:
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
