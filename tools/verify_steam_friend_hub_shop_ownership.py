#!/usr/bin/env python3
"""Verify two-owner native hub purchases on an active Steam friend pair."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import verify_local_multiplayer_sync as local_sync
import verify_multiplayer_hub_inventory_shop_sync as hub_inventory
import verify_multiplayer_hub_shop_ownership as shop
import verify_multiplayer_progression_ledger_sync as progression
from steam_friend_active_pair import (
    CLIENT_ENDPOINT,
    HOST_ENDPOINT,
    PAIR_BACKEND,
    ROOT,
    SteamFriendActivePair,
)
from steam_friend_hub_automation import (
    HubInputTarget,
    click_hub_stock,
    close_native_hub_surface,
    native_hub_surface_state,
    open_hub_service,
    reset_native_hub_surfaces,
    resolve_hub_input_targets,
)
from verify_local_multiplayer_sync import VerifyFailure
from verify_steam_friend_active_pair_state import configure_modules


DEFAULT_OUTPUT = ROOT / "runtime/steam_friend_hub_shop_ownership.json"
TEST_GOLD = 1200
FOMENTIUS_HEALTH_STOCK = (232.0, 50.0)
HAGATHA_LIFE_CHARM_STOCK = (232.0, 50.0)
SHOP_OPEN_SETTLE_SECONDS = 2.0


@dataclass(frozen=True)
class Direction:
    label: str
    owner_endpoint: str
    other_endpoint: str
    owner_runtime_key: str
    other_runtime_key: str
    owner_inventory_key: str
    other_inventory_key: str
    observer_view_owner_key: str
    observer_gold_key: str
    input_target: HubInputTarget


def configure_shop(pair: SteamFriendActivePair) -> None:
    replacements = {
        "HOST_ID": pair.host_participant_id,
        "CLIENT_ID": pair.client_participant_id,
        "HOST_PIPE": HOST_ENDPOINT,
        "CLIENT_PIPE": CLIENT_ENDPOINT,
        "lua": pair.lua,
    }
    for module in (shop, progression):
        for name, value in replacements.items():
            if hasattr(module, name):
                setattr(module, name, value)


def require_shop_surface_closed(direction: Direction) -> None:
    surface_active, chat_active = native_hub_surface_state(
        local_sync.lua,
        direction.owner_endpoint,
    )
    if surface_active or chat_active:
        raise VerifyFailure(
            f"{direction.label} must begin with native hub surfaces closed"
        )


def wait_for_shop_surface_closed(direction: Direction, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    stable_since: float | None = None
    while time.monotonic() < deadline:
        surface_active, chat_active = native_hub_surface_state(
            local_sync.lua,
            direction.owner_endpoint,
        )
        if not surface_active and not chat_active:
            now = time.monotonic()
            if stable_since is None:
                stable_since = now
            elif now - stable_since >= 0.5:
                return
        else:
            stable_since = None
        time.sleep(0.1)
    raise VerifyFailure(f"{direction.label} native shop surface did not close")


def close_shop_surface(
    direction: Direction,
    timeout: float,
) -> str:
    surface_active, chat_active = native_hub_surface_state(
        local_sync.lua,
        direction.owner_endpoint,
    )
    queued = close_native_hub_surface(
        direction.input_target,
        surface_active,
        chat_active,
    )
    wait_for_shop_surface_closed(direction, timeout)
    return queued


def concise_runtime(runtime: dict[str, Any]) -> dict[str, Any]:
    return {
        "gold": runtime["gold"],
        "hp": runtime["hp"],
        "max_hp": runtime["max_hp"],
        "mp": runtime["mp"],
        "max_mp": runtime["max_mp"],
    }


def wait_for_surface(direction: Direction, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        surface_active, chat_active = native_hub_surface_state(
            local_sync.lua, direction.owner_endpoint
        )
        if surface_active:
            return "shop"
        if chat_active:
            return "chat"
        time.sleep(0.1)
    return ""


def open_vendor(
    direction: Direction,
    service_name: Literal["fomentius", "hagatha"],
) -> dict[str, Any]:
    queued = open_hub_service(
        local_sync.lua,
        direction.owner_endpoint,
        service_name,
    )
    if wait_for_surface(direction, 3.0) != "shop":
        raise VerifyFailure(
            f"{direction.label} native {service_name} shop did not open"
        )
    time.sleep(SHOP_OPEN_SETTLE_SECONDS)
    return {
        "service": service_name,
        "queued": queued,
    }


def purchase_item(
    direction: Direction,
    stock_x: float,
    stock_y: float,
    selection_settle_seconds: float,
) -> dict[str, str]:
    selected = click_hub_stock(
        direction.input_target,
        stock_x,
        stock_y,
    )
    time.sleep(selection_settle_seconds)
    purchased = click_hub_stock(
        direction.input_target,
        stock_x,
        stock_y,
    )
    return {
        "selected": selected,
        "purchased": purchased,
    }


def verify_fomentius(direction: Direction, timeout: float) -> dict[str, Any]:
    baseline = shop.wait_for("Fomentius baseline", shop.assert_baseline, timeout)
    owner_before = baseline[direction.owner_runtime_key]["local"]
    other_before = baseline[direction.other_runtime_key]["local"]
    owner_inventory_before = baseline[direction.owner_inventory_key]
    other_inventory_before = baseline[direction.other_inventory_key]
    owner_stack_before = shop.total_potion_stack(owner_inventory_before, 0)
    gold_revision_before = baseline[direction.observer_gold_key]["revision"]
    inventory_revision_before = baseline[direction.observer_view_owner_key][
        "revision"
    ]

    opened = open_vendor(direction, "fomentius")
    purchase = purchase_item(
        direction,
        *FOMENTIUS_HEALTH_STOCK,
        1.0,
    )

    def assert_purchased(state: dict[str, Any]) -> None:
        owner = state[direction.owner_runtime_key]["local"]
        other = state[direction.other_runtime_key]["local"]
        owner_inventory = state[direction.owner_inventory_key]
        other_inventory = state[direction.other_inventory_key]
        observer_gold = state[direction.observer_gold_key]
        observer_inventory = state[direction.observer_view_owner_key]
        price = owner_before["gold"] - owner["gold"]
        if price <= 0:
            raise VerifyFailure(f"{direction.label} did not spend native gold")
        if other != other_before:
            raise VerifyFailure(
                f"{direction.label} Fomentius purchase changed the other owner"
            )
        if other_inventory["semantic_items"] != other_inventory_before["semantic_items"]:
            raise VerifyFailure(
                f"{direction.label} Fomentius purchase changed the other backpack"
            )
        if shop.total_potion_stack(owner_inventory, 0) != owner_stack_before + 1:
            raise VerifyFailure(
                f"{direction.label} health potion did not stack in the owner backpack"
            )
        if observer_gold["value"] != owner["gold"]:
            raise VerifyFailure(
                f"{direction.label} purchased gold did not replicate exactly"
            )
        if observer_gold["revision"] <= gold_revision_before:
            raise VerifyFailure(
                f"{direction.label} purchased gold revision did not advance"
            )
        if observer_inventory["revision"] <= inventory_revision_before:
            raise VerifyFailure(
                f"{direction.label} purchased inventory revision did not advance"
            )
        if observer_inventory["semantic_items"] != owner_inventory["semantic_items"]:
            raise VerifyFailure(
                f"{direction.label} purchased backpack did not replicate exactly"
            )

    purchased = shop.wait_for(
        f"{direction.label} Fomentius purchase", assert_purchased, timeout
    )
    owner_after = purchased[direction.owner_runtime_key]["local"]
    closed = close_shop_surface(direction, timeout)
    result = {
        "opened": opened,
        "purchase": purchase,
        "closed": closed,
        "owner_gold_before": owner_before["gold"],
        "owner_gold_after": owner_after["gold"],
        "price_paid": owner_before["gold"] - owner_after["gold"],
        "owner_potion_stack_before": owner_stack_before,
        "owner_potion_stack_after": shop.total_potion_stack(
            purchased[direction.owner_inventory_key], 0
        ),
        "other_gold": other_before["gold"],
        "observer_gold_revision": purchased[direction.observer_gold_key][
            "revision"
        ],
        "observer_inventory_revision": purchased[
            direction.observer_view_owner_key
        ]["revision"],
    }
    return result


def verify_hagatha(direction: Direction, timeout: float) -> dict[str, Any]:
    baseline = shop.wait_for("Hagatha baseline", shop.assert_baseline, timeout)
    owner_before = baseline[direction.owner_runtime_key]["local"]
    other_before = baseline[direction.other_runtime_key]["local"]
    owner_inventory_before = baseline[direction.owner_inventory_key][
        "semantic_items"
    ]
    other_inventory_before = baseline[direction.other_inventory_key][
        "semantic_items"
    ]
    gold_revision_before = baseline[direction.observer_gold_key]["revision"]
    if owner_before["gold"] <= 0:
        raise VerifyFailure(
            f"{direction.label} lacks native gold for Life Charm"
        )

    opened = open_vendor(direction, "hagatha")
    purchase = purchase_item(
        direction,
        *HAGATHA_LIFE_CHARM_STOCK,
        2.0,
    )

    def assert_purchased(state: dict[str, Any]) -> None:
        owner = state[direction.owner_runtime_key]["local"]
        other = state[direction.other_runtime_key]["local"]
        remote_owner = state[direction.other_runtime_key]["remote"]
        price_paid = owner_before["gold"] - owner["gold"]
        if price_paid <= 0 or price_paid > owner_before["gold"]:
            raise VerifyFailure(
                f"{direction.label} Life Charm did not spend native gold"
            )
        expected_max_hp = owner_before["max_hp"] * 1.25
        if abs(owner["max_hp"] - expected_max_hp) > 0.01:
            raise VerifyFailure(
                f"{direction.label} Life Charm did not raise max HP by 25%"
            )
        if abs(owner["hp"] - owner["max_hp"]) > 0.01:
            raise VerifyFailure(
                f"{direction.label} Life Charm did not preserve full HP"
            )
        if (
            abs(owner["mp"] - owner_before["mp"]) > 0.01
            or abs(owner["max_mp"] - owner_before["max_mp"]) > 0.01
        ):
            raise VerifyFailure(
                f"{direction.label} Life Charm changed owner mana"
            )
        if other != other_before:
            raise VerifyFailure(
                f"{direction.label} Life Charm changed the other owner"
            )
        if state[direction.owner_inventory_key]["semantic_items"] != owner_inventory_before:
            raise VerifyFailure(
                f"{direction.label} Life Charm entered the owner backpack"
            )
        if state[direction.other_inventory_key]["semantic_items"] != other_inventory_before:
            raise VerifyFailure(
                f"{direction.label} Life Charm changed the other backpack"
            )
        if abs(remote_owner["life_max"] - owner["max_hp"]) > 0.01:
            raise VerifyFailure(
                f"{direction.label} Life Charm max HP did not replicate exactly"
            )
        if abs(remote_owner["life_current"] - owner["hp"]) > 0.01:
            raise VerifyFailure(
                f"{direction.label} Life Charm current HP did not replicate exactly"
            )
        observer_gold = state[direction.observer_gold_key]
        if observer_gold["value"] != owner["gold"]:
            raise VerifyFailure(
                f"{direction.label} Life Charm gold did not replicate exactly"
            )
        if observer_gold["revision"] <= gold_revision_before:
            raise VerifyFailure(
                f"{direction.label} Life Charm gold revision did not advance"
            )

    purchased = shop.wait_for(
        f"{direction.label} Hagatha purchase", assert_purchased, timeout
    )
    owner_after = purchased[direction.owner_runtime_key]["local"]
    closed = close_shop_surface(direction, timeout)
    result = {
        "opened": opened,
        "purchase": purchase,
        "closed": closed,
        "owner_before": concise_runtime(owner_before),
        "owner_after": concise_runtime(owner_after),
        "price_paid": owner_before["gold"] - owner_after["gold"],
        "other_unchanged": True,
        "observer_life_current": purchased[direction.other_runtime_key][
            "remote"
        ]["life_current"],
        "observer_life_max": purchased[direction.other_runtime_key]["remote"][
            "life_max"
        ],
        "observer_gold_revision": purchased[direction.observer_gold_key][
            "revision"
        ],
    }
    return result


def wait_for_gold_setup(timeout: float) -> dict[str, Any]:
    def assert_gold(state: dict[str, Any]) -> None:
        shop.assert_baseline(state)
        if state["host_runtime"]["local"]["gold"] != TEST_GOLD:
            raise VerifyFailure("host test gold did not settle")
        if state["client_runtime"]["local"]["gold"] != TEST_GOLD:
            raise VerifyFailure("client test gold did not settle")

    state = shop.wait_for("two-owner test gold", assert_gold, timeout)
    return {
        "host": state["host_runtime"]["local"]["gold"],
        "client": state["client_runtime"]["local"]["gold"],
        "host_observer_revision": state["client_view_host_gold"]["revision"],
        "client_observer_revision": state["host_view_client_gold"]["revision"],
    }


def run(timeout: float) -> dict[str, Any]:
    pair = SteamFriendActivePair()
    try:
        pair_state = pair.discover()
        names = configure_modules(pair)
        configure_shop(pair)
        input_targets = resolve_hub_input_targets()
        directions = (
            Direction(
                "host_owner",
                HOST_ENDPOINT,
                CLIENT_ENDPOINT,
                "host_runtime",
                "client_runtime",
                "host_local_inventory",
                "client_local_inventory",
                "client_view_host",
                "client_view_host_gold",
                input_targets[HOST_ENDPOINT],
            ),
            Direction(
                "client_owner",
                CLIENT_ENDPOINT,
                HOST_ENDPOINT,
                "client_runtime",
                "host_runtime",
                "client_local_inventory",
                "host_local_inventory",
                "host_view_client",
                "host_view_client_gold",
                input_targets[CLIENT_ENDPOINT],
            ),
        )
        for direction in directions:
            reset_native_hub_surfaces(
                direction.input_target,
                local_sync.lua,
                timeout,
            )

        initial = shop.wait_for("initial hub shop state", shop.assert_baseline, timeout)
        original_gold = {
            HOST_ENDPOINT: initial["host_runtime"]["local"]["gold"],
            CLIENT_ENDPOINT: initial["client_runtime"]["local"]["gold"],
        }
        gold_writes = {
            "windows": progression.set_gold(HOST_ENDPOINT, TEST_GOLD),
            "proton": progression.set_gold(CLIENT_ENDPOINT, TEST_GOLD),
        }
        gold_setup = wait_for_gold_setup(timeout)

        trials: dict[str, Any] = {}
        for direction in directions:
            fomentius = verify_fomentius(direction, timeout)
            for target in directions:
                require_shop_surface_closed(target)
            hagatha = verify_hagatha(direction, timeout)
            for target in directions:
                require_shop_surface_closed(target)
            trials[direction.label] = {
                "fomentius": fomentius,
                "hagatha": hagatha,
            }

        restoration_writes = {
            "windows": progression.set_gold(
                HOST_ENDPOINT, original_gold[HOST_ENDPOINT]
            ),
            "proton": progression.set_gold(
                CLIENT_ENDPOINT, original_gold[CLIENT_ENDPOINT]
            ),
        }

        result: dict[str, Any] = {
            "ok": True,
            "transport": "steam_friend",
            "same_machine": PAIR_BACKEND == "wsl",
            "pair": pair_state,
            "names_available": {key: bool(value) for key, value in names.items()},
            "gold_setup": {
                "writes_succeeded": all(
                    row.get("write") == "true" for row in gold_writes.values()
                ),
                "converged": gold_setup,
            },
            "trials": trials,
            "gold_restoration": {
                "writes_succeeded": all(
                    row.get("write") == "true"
                    for row in restoration_writes.values()
                ),
                "restored_values": {
                    "host": original_gold[HOST_ENDPOINT],
                    "client": original_gold[CLIENT_ENDPOINT],
                },
            },
            "summary": {
                "native_shop_owners_tested": 2,
                "fomentius_purchases": 2,
                "hagatha_life_charms": 2,
                "cross_owner_mutations": 0,
                "exact_gold_replications": 4,
                "exact_inventory_replications": 2,
                "exact_vital_replications": 2,
            },
        }
        return pair.redact(result)
    except Exception as exc:
        raise VerifyFailure(str(pair.redact(str(exc)))) from exc
    finally:
        pair.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=25.0)
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
