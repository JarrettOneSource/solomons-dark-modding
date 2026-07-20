#!/usr/bin/env python3
"""Verify participant-owned Luthacus storage on an active Steam friend pair."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import verify_local_multiplayer_sync as local_sync
import verify_multiplayer_hub_inventory_shop_sync as hub_inventory
from steam_friend_hub_automation import (
    HubInputTarget,
    drag_hub_stock,
    native_hub_surface_state,
    open_hub_service,
    reset_native_hub_surfaces,
    resolve_hub_input_targets,
)
from steam_friend_active_pair import (
    CLIENT_ENDPOINT,
    HOST_ENDPOINT,
    PAIR_BACKEND,
    ROOT,
    SteamFriendActivePair,
)
from verify_local_multiplayer_sync import VerifyFailure
from verify_steam_friend_active_pair_state import configure_modules


DEFAULT_OUTPUT = ROOT / "runtime/steam_friend_hub_inventory_storage.json"
BACKPACK_FIRST_ITEM_STOCK = (25.6, 288.0)
STORAGE_FIRST_ITEM_STOCK = (230.4, 48.0)
BACKPACK_RETURN_STOCK = (25.6, 292.8)


@dataclass(frozen=True)
class Direction:
    label: str
    owner_endpoint: str
    other_endpoint: str
    owner_local_key: str
    other_local_key: str
    observer_view_owner_key: str
    owner_view_other_key: str
    input_target: HubInputTarget


def configure_hub_inventory(pair: SteamFriendActivePair) -> None:
    hub_inventory.HOST_ID = pair.host_participant_id
    hub_inventory.CLIENT_ID = pair.client_participant_id
    hub_inventory.HOST_PIPE = HOST_ENDPOINT
    hub_inventory.CLIENT_PIPE = CLIENT_ENDPOINT


def wait_for(
    description: str,
    assertion: Callable[[dict[str, Any]], None],
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    last_error = ""
    while time.monotonic() < deadline:
        try:
            last = hub_inventory.snapshot()
            assertion(last)
            return last
        except Exception as exc:
            last_error = str(exc)
        time.sleep(0.2)
    raise VerifyFailure(
        f"{description} did not converge: last_error={last_error} last={last}"
    )


def wait_for_storage_surface(
    direction: Direction, active: bool, timeout: float
) -> None:
    deadline = time.monotonic() + timeout
    stable_since: float | None = None
    while time.monotonic() < deadline:
        storage_active, _ = native_hub_surface_state(
            local_sync.lua, direction.owner_endpoint
        )
        if storage_active == active:
            if active:
                return
            now = time.monotonic()
            if stable_since is None:
                stable_since = now
            if now - stable_since >= 1.0:
                return
        else:
            stable_since = None
        time.sleep(0.1)
    state = "open" if active else "closed"
    raise VerifyFailure(
        f"{direction.label} native storage surface did not become {state}"
    )


def close_luthacus_surface(
    direction: Direction,
    timeout: float,
) -> list[str]:
    return reset_native_hub_surfaces(
        direction.input_target,
        local_sync.lua,
        timeout,
    )


def open_luthacus(direction: Direction) -> dict[str, Any]:
    queued = open_hub_service(
        local_sync.lua,
        direction.owner_endpoint,
        "luthacus_storage",
    )
    wait_for_storage_surface(direction, True, 3.0)
    return {
        "service": "luthacus_storage",
        "queued": queued,
    }


def run_direction(direction: Direction, timeout: float) -> dict[str, Any]:
    baseline = wait_for(
        f"{direction.label} baseline",
        hub_inventory.assert_baseline,
        timeout,
    )
    owner_before = baseline[direction.owner_local_key]
    other_before = baseline[direction.other_local_key]
    owner_view_before = baseline[direction.observer_view_owner_key]
    owner_items_before = owner_before["semantic_items"]
    other_items_before = other_before["semantic_items"]

    opened_actions = open_luthacus(direction)
    wait_for_storage_surface(direction, True, timeout)
    opened = hub_inventory.snapshot()
    opened_raw_item_count = opened[direction.owner_local_key][
        "raw_item_count"
    ]
    outbound_drag = drag_hub_stock(
        direction.input_target,
        *BACKPACK_FIRST_ITEM_STOCK,
        *STORAGE_FIRST_ITEM_STOCK,
    )

    def assert_stored(current: dict[str, Any]) -> None:
        owner = current[direction.owner_local_key]
        other = current[direction.other_local_key]
        observer_view_owner = current[direction.observer_view_owner_key]
        owner_view_other = current[direction.owner_view_other_key]
        hub_inventory.assert_no_placeholders(
            f"{direction.label} owner stored", owner
        )
        if owner["item_count"] != len(owner_items_before) - 1:
            raise VerifyFailure(
                f"{direction.label} item did not enter private storage"
            )
        if other["semantic_items"] != other_items_before:
            raise VerifyFailure(
                f"{direction.label} changed the other player's backpack"
            )
        hub_inventory.assert_ledger_matches_local(
            f"{direction.label} owner stored",
            owner,
            observer_view_owner,
        )
        hub_inventory.assert_ledger_matches_local(
            f"{direction.label} other unchanged",
            other,
            owner_view_other,
        )
        if observer_view_owner["revision"] <= owner_view_before["revision"]:
            raise VerifyFailure(
                f"{direction.label} inventory revision did not advance"
            )

    stored = wait_for(
        f"{direction.label} storage transfer",
        assert_stored,
        timeout,
    )
    stored_revision = stored[direction.observer_view_owner_key]["revision"]
    return_drag = drag_hub_stock(
        direction.input_target,
        *STORAGE_FIRST_ITEM_STOCK,
        *BACKPACK_RETURN_STOCK,
    )

    def assert_restored(current: dict[str, Any]) -> None:
        owner = current[direction.owner_local_key]
        other = current[direction.other_local_key]
        observer_view_owner = current[direction.observer_view_owner_key]
        owner_view_other = current[direction.owner_view_other_key]
        hub_inventory.assert_no_placeholders(
            f"{direction.label} owner restored", owner
        )
        if owner["semantic_items"] != owner_items_before:
            raise VerifyFailure(
                f"{direction.label} did not restore the exact native backpack"
            )
        if owner["raw_item_count"] <= owner["item_count"]:
            raise VerifyFailure(
                f"{direction.label} did not exercise the stock storage grid"
            )
        if other["semantic_items"] != other_items_before:
            raise VerifyFailure(
                f"{direction.label} return changed the other player's backpack"
            )
        hub_inventory.assert_ledger_matches_local(
            f"{direction.label} owner restored",
            owner,
            observer_view_owner,
        )
        hub_inventory.assert_ledger_matches_local(
            f"{direction.label} other restored",
            other,
            owner_view_other,
        )
        if observer_view_owner["revision"] <= stored_revision:
            raise VerifyFailure(
                f"{direction.label} restore revision did not advance"
            )

    restored = wait_for(
        f"{direction.label} storage return",
        assert_restored,
        timeout,
    )
    close = close_luthacus_surface(direction, min(timeout, 5.0))
    return {
        "baseline": {
            "owner_item_count": owner_before["item_count"],
            "other_item_count": other_before["item_count"],
            "owner_revision": owner_view_before["revision"],
        },
        "opened_actions": opened_actions,
        "opened_raw_item_count": opened_raw_item_count,
        "outbound": {
            "drag": outbound_drag,
            "owner_item_count": stored[direction.owner_local_key]["item_count"],
            "other_item_count": stored[direction.other_local_key]["item_count"],
            "owner_revision": stored_revision,
        },
        "restored": {
            "drag": return_drag,
            "close": close,
            "owner_item_count": restored[direction.owner_local_key]["item_count"],
            "other_item_count": restored[direction.other_local_key]["item_count"],
            "owner_revision": restored[direction.observer_view_owner_key][
                "revision"
            ],
            "stock_grid_raw_count": restored[direction.owner_local_key][
                "raw_item_count"
            ],
        },
    }


def run(timeout: float) -> dict[str, Any]:
    pair = SteamFriendActivePair()
    try:
        pair_state = pair.discover()
        names = configure_modules(pair)
        configure_hub_inventory(pair)
        input_targets = resolve_hub_input_targets()
        directions = (
            Direction(
                "host_owner",
                HOST_ENDPOINT,
                CLIENT_ENDPOINT,
                "host_local",
                "client_local",
                "client_view_host",
                "host_view_client",
                input_targets[HOST_ENDPOINT],
            ),
            Direction(
                "client_owner",
                CLIENT_ENDPOINT,
                HOST_ENDPOINT,
                "client_local",
                "host_local",
                "host_view_client",
                "client_view_host",
                input_targets[CLIENT_ENDPOINT],
            ),
        )
        for direction in directions:
            reset_native_hub_surfaces(
                direction.input_target,
                local_sync.lua,
                timeout,
            )
        trials = {
            direction.label: run_direction(direction, timeout)
            for direction in directions
        }
        result: dict[str, Any] = {
            "ok": True,
            "transport": "steam_friend",
            "same_machine": PAIR_BACKEND == "wsl",
            "pair": pair_state,
            "names_available": {key: bool(value) for key, value in names.items()},
            "trials": trials,
            "summary": {
                "native_storage_owners_tested": 2,
                "outbound_transfers": 2,
                "exact_restores": 2,
                "cross_owner_mutations": 0,
                "replicated_revision_advances": 4,
                "placeholder_rows_exposed_as_items": 0,
            },
        }
        return pair.redact(result)
    except Exception as exc:
        raise VerifyFailure(str(pair.redact(str(exc)))) from exc
    finally:
        pair.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    try:
        result = run(args.timeout)
        return_code = 0
    except Exception as exc:
        result["error"] = str(exc)
        return_code = 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "ok": result.get("ok", False),
                "error": result.get("error"),
                "summary": result.get("summary"),
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
