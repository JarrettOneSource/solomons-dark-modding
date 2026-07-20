#!/usr/bin/env python3
"""Verify loot pickup and native equipment on an active Steam friend pair."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import probe_run_reward_sync as rewards
import verify_local_multiplayer_sync as local_sync
import verify_multiplayer_gold_pickup_authority as gold
import verify_multiplayer_inventory_audit as inventory
import verify_multiplayer_loot_drop_materialization as loot
import verify_multiplayer_native_item_inventory_sync as native_item
import verify_multiplayer_native_potion_inventory_sync as native_potion
import verify_multiplayer_orb_pickup_authority as orb
from steam_friend_active_pair import (
    CLIENT_ENDPOINT,
    HOST_ENDPOINT,
    PAIR_BACKEND,
    ROOT,
    SteamFriendActivePair,
)
from steam_friend_behavior_context import disable_runtime_test_godmode
from verify_local_multiplayer_sync import VerifyFailure
from verify_steam_friend_active_pair_state import configure_modules


DEFAULT_OUTPUT = ROOT / "runtime/steam_friend_native_inventory_sync.json"
HOST_INSTANCE = os.environ.get("SDMOD_STEAM_HOST_INSTANCE", "").strip()
CLIENT_INSTANCE = os.environ.get("SDMOD_STEAM_CLIENT_INSTANCE", "").strip()


def set_if_present(module: Any, name: str, value: Any) -> None:
    if hasattr(module, name):
        setattr(module, name, value)


def configure(pair: SteamFriendActivePair) -> None:
    if not HOST_INSTANCE or not CLIENT_INSTANCE:
        raise VerifyFailure(
            "SDMOD_STEAM_HOST_INSTANCE and SDMOD_STEAM_CLIENT_INSTANCE are required"
        )

    configure_modules(pair)
    host_log = (
        ROOT
        / "runtime/instances"
        / HOST_INSTANCE
        / "stage/.sdmod/logs/solomondarkmodloader.log"
    )
    client_log = (
        ROOT
        / "runtime/instances"
        / CLIENT_INSTANCE
        / "stage/.sdmod/logs/solomondarkmodloader.log"
    )
    replacements = {
        "HOST_ID": pair.host_participant_id,
        "CLIENT_ID": pair.client_participant_id,
        "HOST_PIPE": HOST_ENDPOINT,
        "CLIENT_PIPE": CLIENT_ENDPOINT,
        "HOST_LOG": host_log,
        "CLIENT_LOG": client_log,
        "lua": pair.lua,
    }
    for module in (
        local_sync,
        rewards,
        gold,
        orb,
        inventory,
        loot,
        native_potion,
        native_item,
    ):
        for name, value in replacements.items():
            set_if_present(module, name, value)


def stage(message: str) -> None:
    print(f"[steam-inventory] {message}", flush=True)


def parse_item_type(value: str) -> int:
    item_type = int(value, 0)
    if item_type not in native_item.EQUIPPABLE_TYPE_IDS:
        choices = ", ".join(
            f"0x{candidate:04X}" for candidate in native_item.EQUIPPABLE_TYPE_IDS
        )
        raise argparse.ArgumentTypeError(
            f"unsupported equipment type {value!r}; choose one of {choices}"
        )
    return item_type


def run(
    pair: SteamFriendActivePair,
    timeout: float,
    item_types: tuple[int, ...] = native_item.EQUIPPABLE_TYPE_IDS,
    *,
    equipment_only: bool = False,
) -> dict[str, Any]:
    stage("discovering active friend pair")
    pair_state = pair.discover()
    if any(pair_state[side].get("scene") != "testrun" for side in ("host", "client")):
        raise VerifyFailure(f"Steam friend pair is not in testrun: {pair_state}")
    configure(pair)

    result: dict[str, Any] = {
        "ok": False,
        "transport": "steam_friend",
        "same_machine": PAIR_BACKEND == "wsl",
        "pair": pair_state,
        "test_godmode": disable_runtime_test_godmode(pair),
    }
    shared_args = argparse.Namespace(no_launch=True, attempts=1, timeout=timeout)
    if not equipment_only:
        stage("verifying gold pickup authority")
        result["gold_pickup"] = gold.verify_gold_pickup_authority(shared_args)
        stage("verifying health and mana orb pickup authority")
        result["orb_pickups"] = orb.verify_orb_pickup_authority(shared_args)
        stage("verifying native potion insertion")
        result["native_potion"] = native_potion.run(shared_args)

    result["native_equipment"] = {}
    for item_type in item_types:
        stage(f"verifying native equipment type 0x{item_type:04X}")
        item_args = argparse.Namespace(
            no_launch=True,
            attempts=1,
            timeout=timeout,
            item_type=item_type,
        )
        result["native_equipment"][f"0x{item_type:04X}"] = native_item.run(
            item_args
        )

    if not equipment_only:
        stage("verifying host-authored drop materialization")
        result["loot_materialization"] = loot.run_verifier(shared_args)
    result["ok"] = all(
        row.get("ok") is True
        for row in result["native_equipment"].values()
    )
    if not equipment_only:
        result["ok"] = result["ok"] and all(
            result[key].get("ok") is True
            for key in (
                "gold_pickup",
                "orb_pickups",
                "native_potion",
                "loot_materialization",
            )
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument(
        "--item-type",
        action="append",
        type=parse_item_type,
        help="verify only this equipment type; may be supplied more than once",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    pair = SteamFriendActivePair()
    result: dict[str, Any] = {"ok": False}
    return_code = 1
    try:
        item_types = (
            tuple(args.item_type)
            if args.item_type
            else native_item.EQUIPPABLE_TYPE_IDS
        )
        result = run(
            pair,
            args.timeout,
            item_types,
            equipment_only=bool(args.item_type),
        )
        return_code = 0 if result["ok"] else 1
    except Exception as exc:
        result["error"] = str(exc)
        result["error_type"] = type(exc).__name__
    finally:
        pair.close()

    result = pair.redact(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "ok": result.get("ok", False),
                "error": result.get("error"),
                "gold": result.get("gold_pickup", {}).get("ok"),
                "orbs": result.get("orb_pickups", {}).get("ok"),
                "potion": result.get("native_potion", {}).get("ok"),
                "equipment_types": len(result.get("native_equipment", {})),
                "loot_materialization": result.get(
                    "loot_materialization", {}
                ).get("ok"),
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
