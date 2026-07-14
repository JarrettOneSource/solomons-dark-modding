#!/usr/bin/env python3
"""Verify the multiplayer item/potion pickup contract is wired end to end."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


CHECKS = (
    ("protocol version", "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h", "kProtocolVersion = 51"),
    ("drop item type", "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h", "std::uint32_t item_type_id;"),
    ("drop item slot", "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h", "std::int32_t item_slot;"),
    ("drop stack count", "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h", "std::int32_t stack_count;"),
    ("result inventory revision", "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h", "std::uint32_t inventory_revision;"),
    ("item drop native type", "SolomonDarkModLoader/src/multiplayer_local_transport.cpp", "kItemDropNativeTypeId = 0x07DD"),
    ("potion item type", "SolomonDarkModLoader/src/multiplayer_local_transport.cpp", "kPotionItemTypeId = 0x1B59"),
    ("held item reader", "SolomonDarkModLoader/src/multiplayer_local_transport/loot_snapshot_capture.inl", "TryReadItemDropHeldItemMetadata"),
    ("item snapshot", "SolomonDarkModLoader/src/multiplayer_local_transport/loot_snapshot_capture.inl", "TryPopulateItemLootDropSnapshot"),
    ("item deactivate", "SolomonDarkModLoader/src/multiplayer_local_transport/loot_snapshot_capture.inl", "TryDeactivateHostItemLootDrop"),
    ("item payload", "SolomonDarkModLoader/src/multiplayer_local_transport/loot_pickup_authority.inl", "TryBuildAcceptedItemLootPickupPayload"),
    ("ledger mutation", "SolomonDarkModLoader/src/multiplayer_local_transport/owned_progression_state.inl", "ApplyOwnedInventoryLootItem"),
    ("host authoritative guard", "SolomonDarkModLoader/src/multiplayer_local_transport.cpp", "inventory_host_authoritative"),
    ("item validation", "SolomonDarkModLoader/src/multiplayer_local_transport.cpp", "drop_kind == LootDropKind::Item"),
    ("potion validation", "SolomonDarkModLoader/src/multiplayer_local_transport.cpp", "drop_kind == LootDropKind::Potion"),
    ("held item offset config", "config/binary-layout.ini", "item_drop_held_item=0x148"),
    ("held item seam", "SolomonDarkModLoader/src/gameplay_seams.h", "kItemDropHeldItemOffset"),
    ("held item binding", "SolomonDarkModLoader/src/gameplay_seams/size_bindings.inl", "item_drop_held_item"),
    ("item hook state", "SolomonDarkModLoader/src/mod_loader_gameplay/core/runtime_request_state.inl", "item_drop_pickup_hook"),
    ("item hook type", "SolomonDarkModLoader/src/mod_loader_gameplay/core/native_function_types.inl", "ItemDropPickupTickFn"),
    ("item hook install", "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_keyboard_injection.inl", "HookItemDropPickupTick"),
    ("item hook cleanup", "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_keyboard_injection.inl", "item_drop_pickup_hook"),
    ("item hook body", "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/item_drop_pickup_hook.inl", "ShouldSuppressRemoteParticipantItemDropPickup"),
    ("potion presentation type", "SolomonDarkModLoader/src/mod_loader_gameplay/replicated_loot_reconciliation.inl", "kReplicatedLootPotionItemTypeId = 0x1B59"),
    ("potion presentation vfunc", "SolomonDarkModLoader/src/mod_loader_gameplay/replicated_loot_reconciliation.inl", "kArenaSpawnPotionDropVfuncOffset = 0x148"),
    ("potion presentation spawn", "SolomonDarkModLoader/src/mod_loader_gameplay/replicated_loot_reconciliation.inl", "ExecuteSpawnReplicatedPotionDropNow"),
    ("potion native spawn type", "SolomonDarkModLoader/src/mod_loader_gameplay/core/native_function_types.inl", "using SpawnPotionDropFn"),
    ("potion presentation slot write", "SolomonDarkModLoader/src/mod_loader_gameplay/replicated_loot_reconciliation.inl", "memory.TryWriteField(held_item_address, kItemSlotOffset, potion_slot)"),
    ("potion presentation stack write", "SolomonDarkModLoader/src/mod_loader_gameplay/replicated_loot_reconciliation.inl", "memory.TryWriteField(held_item_address, kPotionStackCountOffset, stack_count)"),
    ("loot lua item type", "SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp", '"item_type_id"'),
    ("loot lua item slot", "SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp", '"item_slot"'),
    ("loot lua stack", "SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp", '"stack_count"'),
    ("runtime lua authority flag", "SolomonDarkModLoader/src/lua_engine_bindings_runtime.cpp", '"inventory_host_authoritative"'),
)


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Emit machine-readable result details.")
    args = parser.parse_args()

    failures: list[dict[str, str]] = []
    for label, relative_path, needle in CHECKS:
        text = read_text(relative_path)
        if needle not in text:
            failures.append({
                "label": label,
                "path": relative_path,
                "needle": needle,
            })

    result = {
        "ok": not failures,
        "check_count": len(CHECKS),
        "failure_count": len(failures),
        "failures": failures,
    }
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        if failures:
            print("item/potion pickup contract failed")
            for failure in failures:
                print(f"- {failure['label']}: missing {failure['needle']} in {failure['path']}")
        else:
            print(f"item/potion pickup contract ok ({len(CHECKS)} checks)")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
