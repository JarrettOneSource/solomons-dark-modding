#!/usr/bin/env python3
"""Verify an accepted remote potion pickup enters the client's stock inventory."""

from __future__ import annotations

import argparse
import json
import time
from typing import Any

from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_PIPE,
    HOST_PIPE,
    ROOT,
    VerifyFailure,
    parse_int_text,
    stop_games,
)
from verify_multiplayer_gold_pickup_authority import (
    move_client_into_pickup_range,
    move_client_out_of_pickup_range,
    request_pickup,
    select_spawn_point,
)
from verify_multiplayer_inventory_audit import (
    capture as capture_inventory,
    find_participant,
    item_rows,
    participant_rows,
)
from verify_multiplayer_loot_drop_materialization import (
    ITEM_DROP_TYPE_ID,
    POTION_ITEM_TYPE_ID,
    PROBE_POTION_STACK,
    PROBE_POTION_SLOT,
    capture as capture_loot,
    drop_rows,
    require_host_spawn,
    setup_pair,
    values,
    wait_for_materialized_drop,
)


RUNTIME_OUTPUT = ROOT / "runtime" / "multiplayer_native_potion_inventory_sync.json"
CLIENT_LOG = ROOT / "runtime/instances/local-mp-client/stage/.sdmod/logs/solomondarkmodloader.log"


PICKUP_STATE_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value or "")) end
local loot = sd.world and sd.world.get_replicated_loot and sd.world.get_replicated_loot() or nil
local result = loot and loot.last_pickup_result or nil
emit("valid", result ~= nil)
if result then
  emit("network_drop_id", result.network_drop_id or 0)
  emit("request_sequence", result.request_sequence or 0)
  emit("result", result.result or "")
  emit("kind", result.kind or "")
  emit("item_type_id", result.item_type_id or 0)
  emit("item_slot", result.item_slot or -1)
  emit("stack_count", result.stack_count or 0)
  emit("inventory_revision", result.inventory_revision or 0)
end
"""


def pickup_state() -> dict[str, str]:
    return values(CLIENT_PIPE, PICKUP_STATE_LUA)


def wait_for_pickup_result(
    network_drop_id: int,
    expected_result: str,
    timeout: float,
    request_sequence: int | None = None,
) -> dict[str, str] | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = pickup_state()
        if (
            state.get("valid") == "true"
            and parse_int_text(state.get("network_drop_id"), 0) == network_drop_id
            and state.get("result") == expected_result
            and (
                request_sequence is None
                or parse_int_text(state.get("request_sequence"), 0) == request_sequence
            )
        ):
            return state
        time.sleep(0.1)
    return None


def native_potion_stack(capture: dict[str, str], slot: int) -> int:
    return sum(
        max(row["stack_count"], 1)
        for row in item_rows(capture)
        if row["valid"] and row["type_id"] == POTION_ITEM_TYPE_ID and row["slot"] == slot
    )


def owned_potion_stack(participant: dict[str, Any] | None, slot: int) -> int:
    if participant is None:
        return -1
    return sum(
        max(item["stack_count"], 1)
        for item in participant["inventory_items"]
        if item["type_id"] == POTION_ITEM_TYPE_ID and item["slot"] == slot
    )


def find_local_participant(capture: dict[str, str]) -> dict[str, Any] | None:
    return next(
        (row for row in participant_rows(capture) if row["kind"] == "LocalHuman"),
        None,
    )


def wait_for_native_convergence(
    *,
    expected_stack: int,
    accepted_revision: int,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        client = capture_inventory(CLIENT_PIPE)
        host = capture_inventory(HOST_PIPE)
        client_local = find_local_participant(client)
        host_client = find_participant(host, CLIENT_ID)
        last = {
            "client_native_stack": native_potion_stack(client, PROBE_POTION_SLOT),
            "client_owned_stack": owned_potion_stack(client_local, PROBE_POTION_SLOT),
            "host_owned_client_stack": owned_potion_stack(host_client, PROBE_POTION_SLOT),
            "client_inventory_revision": (
                client_local["inventory_revision"] if client_local is not None else -1
            ),
            "host_inventory_revision": (
                host_client["inventory_revision"] if host_client is not None else -1
            ),
            "client_inventory_host_authoritative": (
                client_local["inventory_host_authoritative"]
                if client_local is not None
                else None
            ),
        }
        if (
            last["client_native_stack"] == expected_stack
            and last["client_owned_stack"] == expected_stack
            and last["host_owned_client_stack"] == expected_stack
            and last["client_inventory_revision"] >= accepted_revision
            and last["host_inventory_revision"] >= accepted_revision
            and last["client_inventory_host_authoritative"] is False
        ):
            return last
        if last["client_native_stack"] > expected_stack:
            raise VerifyFailure(f"native potion stack was credited more than once: {last}")
        time.sleep(0.1)
    raise VerifyFailure(f"native potion inventory did not converge: {last}")


def wait_for_client_presentation_absent(network_drop_id: int, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_rows: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        last_rows = [
            row
            for row in drop_rows(capture_loot(CLIENT_PIPE))
            if row["network_id"] == network_drop_id
        ]
        if not last_rows or all(
            row["materialized"] == 0 and row["local_actor_address"] == 0
            for row in last_rows
        ):
            return {"absent": True, "metadata_rows": last_rows}
        time.sleep(0.1)
    raise VerifyFailure(
        f"consumed potion presentation remained materialized: drop={network_drop_id} rows={last_rows}"
    )


def client_native_apply_log_lines(network_drop_id: int) -> list[str]:
    try:
        lines = CLIENT_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    needle = f"network_drop_id={network_drop_id}"
    return [
        line
        for line in lines
        if "native_inventory:" in line and needle in line
    ][-20:]


def run(args: argparse.Namespace) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": False}
    if not args.no_launch:
        result["setup"] = setup_pair(args.attempts)

    client_before = capture_inventory(CLIENT_PIPE)
    stack_before = native_potion_stack(client_before, PROBE_POTION_SLOT)
    if stack_before < 1:
        raise VerifyFailure(f"client has no native starter potion stack: {item_rows(client_before)}")

    spawn_point = select_spawn_point(args.timeout)
    potion_x = float(spawn_point["snapped_x"])
    potion_y = float(spawn_point["snapped_y"])
    result["spawn_point"] = spawn_point
    result["client_pre_spawn_parking"] = move_client_out_of_pickup_range(
        drop_x=potion_x,
        drop_y=potion_y,
        timeout=args.timeout,
    )
    result["spawn"] = require_host_spawn(
        "mana_potion",
        PROBE_POTION_SLOT,
        potion_x,
        potion_y,
    )
    materialized = wait_for_materialized_drop(
        type_id=ITEM_DROP_TYPE_ID,
        item_type_id=POTION_ITEM_TYPE_ID,
        item_slot=PROBE_POTION_SLOT,
        stack_count=PROBE_POTION_STACK,
        x=potion_x,
        y=potion_y,
        timeout=args.timeout,
    )["drop"]
    network_drop_id = int(materialized["network_id"])
    result["materialized"] = materialized

    result["client_pickup_position"] = move_client_into_pickup_range(
        drop_x=float(materialized["x"]),
        drop_y=float(materialized["y"]),
        timeout=args.timeout,
    )
    accepted = wait_for_pickup_result(
        network_drop_id,
        "Accepted",
        min(1.5, args.timeout),
    )
    if accepted is None:
        request = request_pickup(network_drop_id)
        request_sequence = parse_int_text(request.get("request_sequence"), 0)
        accepted = wait_for_pickup_result(
            network_drop_id,
            "Accepted",
            args.timeout,
            request_sequence,
        )
        result["request"] = request
    else:
        result["request"] = {"path": "client_proximity_hook"}
    if accepted is None:
        raise VerifyFailure(f"client did not receive Accepted for potion drop {network_drop_id}")

    result["accepted_result"] = accepted
    accepted_revision = parse_int_text(accepted.get("inventory_revision"), 0)
    if (
        accepted.get("kind") != "Potion"
        or parse_int_text(accepted.get("item_type_id"), 0) != POTION_ITEM_TYPE_ID
        or parse_int_text(accepted.get("item_slot"), -1) != PROBE_POTION_SLOT
        or parse_int_text(accepted.get("stack_count"), 0) != PROBE_POTION_STACK
        or accepted_revision <= 0
    ):
        raise VerifyFailure(f"accepted potion result metadata is invalid: {accepted}")

    expected_stack = stack_before + PROBE_POTION_STACK
    result["convergence"] = wait_for_native_convergence(
        expected_stack=expected_stack,
        accepted_revision=accepted_revision,
        timeout=args.timeout,
    )
    result["client_presentation"] = wait_for_client_presentation_absent(
        network_drop_id,
        args.timeout,
    )

    duplicate = request_pickup(network_drop_id)
    duplicate_sequence = parse_int_text(duplicate.get("request_sequence"), 0)
    duplicate_result = wait_for_pickup_result(
        network_drop_id,
        "AlreadyGone",
        args.timeout,
        duplicate_sequence,
    )
    if duplicate_result is None:
        raise VerifyFailure(f"duplicate potion pickup did not return AlreadyGone: {duplicate}")
    result["duplicate"] = {"request": duplicate, "result": duplicate_result}
    time.sleep(0.5)
    final_stack = native_potion_stack(capture_inventory(CLIENT_PIPE), PROBE_POTION_SLOT)
    if final_stack != expected_stack:
        raise VerifyFailure(
            f"duplicate potion request changed native stack: expected={expected_stack} actual={final_stack}"
        )
    result["native_apply_log"] = client_native_apply_log_lines(network_drop_id)
    if not any("applied authoritative item pickup" in line for line in result["native_apply_log"]):
        raise VerifyFailure(
            f"client log lacks native inventory apply evidence for drop {network_drop_id}: "
            f"{result['native_apply_log']}"
        )
    result["stack"] = {
        "before": stack_before,
        "credited": PROBE_POTION_STACK,
        "after": final_stack,
    }
    result["ok"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-launch", action="store_true")
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=12.0)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    try:
        result = run(args)
        RUNTIME_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({
            "ok": result["ok"],
            "stack": result.get("stack"),
            "convergence": result.get("convergence"),
            "output": str(RUNTIME_OUTPUT),
        }, indent=2, sort_keys=True))
        return 0 if result["ok"] else 1
    except Exception as exc:
        result["error"] = str(exc)
        RUNTIME_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1
    finally:
        if not args.no_launch:
            stop_games()


if __name__ == "__main__":
    raise SystemExit(main())
