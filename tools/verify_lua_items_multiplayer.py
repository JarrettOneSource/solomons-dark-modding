#!/usr/bin/env python3
"""Verify authority-routed Lua item grants across a local multiplayer pair."""

from __future__ import annotations

import argparse
import json
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
OUTPUT = ROOT / "runtime" / "lua_items_multiplayer_verification.json"
ACCEPTANCE_MOD_ID = "sample.lua.items_registry_lab"
EXPECTED_CONTENT_ID = 5785942626980372610
LOCAL_TARGET_ID = 1

ITEM_STATE = f"""
local item = assert(
  sd.items.get({EXPECTED_CONTENT_ID}),
  "Lua item acceptance registration is unavailable")
local inventory = sd.player.get_inventory_state()
local units = 0
local rows = 0
if inventory and inventory.valid then
  for _, row in ipairs(inventory.items or {{}}) do
    if row.valid and row.recipe_uid == item.recipe_uid then
      rows = rows + 1
      local stack = tonumber(row.stack_count) or 1
      units = units + math.max(1, stack)
    end
  end
end
print("authority=" .. tostring(sd.state.is_authority()))
print("content_id=" .. tostring(item.id))
print("available=" .. tostring(item.available))
print("recipe_uid=" .. tostring(item.recipe_uid))
print("inventory_valid=" .. tostring(inventory ~= nil and inventory.valid))
print("unit_count=" .. tostring(units))
print("row_count=" .. tostring(rows))
"""

CLIENT_REJECTION = f"""
local ok, error_message = pcall(sd.items.grant, {EXPECTED_CONTENT_ID})
print("rejected=" .. tostring(not ok))
print("authority_error=" .. tostring(
  type(error_message) == "string" and
  string.find(error_message, "authority", 1, true) ~= nil))
"""

LOCAL_GRANT = f"""
local grant = sd.items.grant({EXPECTED_CONTENT_ID})
print("request_id=" .. tostring(grant.request_id))
print("content_id=" .. tostring(grant.content_id))
print("target_participant_id=" .. tostring(grant.target_participant_id))
print("local_target=" .. tostring(grant.local_target))
"""


def _remote_grant_probe(participant_id: int) -> str:
    return f"""
local grant = sd.items.grant({EXPECTED_CONTENT_ID}, {{
  participant_id = {participant_id},
}})
print("request_id=" .. tostring(grant.request_id))
print("content_id=" .. tostring(grant.content_id))
print("target_participant_id=" .. tostring(grant.target_participant_id))
print("local_target=" .. tostring(grant.local_target))
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


def item_state_matches(
    values: dict[str, str],
    *,
    authority: bool,
    recipe_uid: int | None = None,
    unit_count: int | None = None,
) -> bool:
    try:
        return (
            values.get("authority") == ("true" if authority else "false")
            and _int_value(values, "content_id") == EXPECTED_CONTENT_ID
            and values.get("available") == "true"
            and _positive_int(values, "recipe_uid") > 0
            and (
                recipe_uid is None
                or _int_value(values, "recipe_uid") == recipe_uid
            )
            and values.get("inventory_valid") == "true"
            and _int_value(values, "unit_count") >= 0
            and (
                unit_count is None
                or _int_value(values, "unit_count") == unit_count
            )
            and _int_value(values, "row_count") >= 0
        )
    except RuntimeError:
        return False


def grant_result_matches(
    values: dict[str, str],
    *,
    target_participant_id: int,
    local_target: bool,
) -> bool:
    try:
        return (
            _positive_int(values, "request_id") > 0
            and _int_value(values, "content_id") == EXPECTED_CONTENT_ID
            and _int_value(values, "target_participant_id")
            == target_participant_id
            and values.get("local_target")
            == ("true" if local_target else "false")
        )
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


def _poll_item_state(
    client: tuple[str, str],
    *,
    authority: bool,
    recipe_uid: int | None,
    unit_count: int | None,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = run_lua_client(client[0], client[1], ITEM_STATE, timeout=12.0)
        values = last.get("values", {})
        if (
            _failed_exec(last) is None
            and isinstance(values, dict)
            and item_state_matches(
                values,
                authority=authority,
                recipe_uid=recipe_uid,
                unit_count=unit_count,
            )
        ):
            return last
        time.sleep(0.1)
    raise RuntimeError(
        f"Lua item inventory did not converge for {client[0]}: "
        f"recipe_uid={recipe_uid} unit_count={unit_count} last={last}"
    )


def _require_grant(
    result: dict[str, Any],
    *,
    target_participant_id: int,
    local_target: bool,
) -> None:
    values = result.get("values", {})
    if not isinstance(values, dict) or not grant_result_matches(
        values,
        target_participant_id=target_participant_id,
        local_target=local_target,
    ):
        raise RuntimeError(f"Lua item grant queue contract differs: {result}")


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
    try:
        if launch:
            result["pair"] = launch_pair(
                god_mode=True,
                tile_windows=False,
                kill_existing=False,
                exact_mod_id=ACCEPTANCE_MOD_ID,
            )
            launched_process_ids.extend(game_process_ids(result["pair"]))
            disable_bots()
            wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "hub")
            wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "hub")
            result["run"] = start_host_testrun_and_wait_for_clients(
                timeout=timeout,
            )

        initial_host = _poll_item_state(
            host,
            authority=True,
            recipe_uid=None,
            unit_count=None,
            timeout=timeout,
        )
        result["initial_host"] = initial_host
        initial_client = _poll_item_state(
            client,
            authority=False,
            recipe_uid=None,
            unit_count=None,
            timeout=timeout,
        )
        result["initial_client"] = initial_client
        host_values = initial_host.get("values", {})
        client_values = initial_client.get("values", {})
        host_recipe_uid = _positive_int(host_values, "recipe_uid")
        client_recipe_uid = _positive_int(client_values, "recipe_uid")
        host_before = _int_value(host_values, "unit_count")
        client_before = _int_value(client_values, "unit_count")

        rejection = _run_probe(client, CLIENT_REJECTION)
        result["client_rejection"] = rejection
        rejection_values = rejection.get("values", {})
        if not (
            rejection_values.get("rejected") == "true"
            and rejection_values.get("authority_error") == "true"
        ):
            raise RuntimeError(
                f"Lua item client grant was not authority-rejected: {rejection}"
            )
        result["client_after_rejection"] = _poll_item_state(
            client,
            authority=False,
            recipe_uid=client_recipe_uid,
            unit_count=client_before,
            timeout=timeout,
        )

        remote_grant = _run_probe(
            host,
            _remote_grant_probe(CLIENT_ID),
        )
        result["remote_grant"] = remote_grant
        _require_grant(
            remote_grant,
            target_participant_id=CLIENT_ID,
            local_target=False,
        )
        result["client_after_remote_grant"] = _poll_item_state(
            client,
            authority=False,
            recipe_uid=client_recipe_uid,
            unit_count=client_before + 1,
            timeout=timeout,
        )
        result["host_after_remote_grant"] = _poll_item_state(
            host,
            authority=True,
            recipe_uid=host_recipe_uid,
            unit_count=host_before,
            timeout=timeout,
        )

        local_grant = _run_probe(host, LOCAL_GRANT)
        result["local_grant"] = local_grant
        _require_grant(
            local_grant,
            target_participant_id=LOCAL_TARGET_ID,
            local_target=True,
        )
        result["host_after_local_grant"] = _poll_item_state(
            host,
            authority=True,
            recipe_uid=host_recipe_uid,
            unit_count=host_before + 1,
            timeout=timeout,
        )
        result["client_final"] = _poll_item_state(
            client,
            authority=False,
            recipe_uid=client_recipe_uid,
            unit_count=client_before + 1,
            timeout=timeout,
        )

        result["recipe_uids"] = {
            "host": host_recipe_uid,
            "client": client_recipe_uid,
        }
        result["unit_counts"] = {
            "host_before": host_before,
            "host_after": host_before + 1,
            "client_before": client_before,
            "client_after": client_before + 1,
        }
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
        help="Stage and launch an isolated local pair before verification.",
    )
    parser.add_argument(
        "--confirm-mutation",
        action="store_true",
        help="confirm that the verifier may grant one item to each participant",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    if not args.confirm_mutation:
        result["error"] = "refusing inventory mutations without --confirm-mutation"
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
