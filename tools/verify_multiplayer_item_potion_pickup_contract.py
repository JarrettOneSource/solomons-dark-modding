#!/usr/bin/env python3
"""Verify the multiplayer item/potion pickup contract is wired end to end."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


CHECKS = (
    ("protocol version", "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h", "kProtocolVersion = 60"),
    ("drop item type", "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h", "std::uint32_t item_type_id;"),
    ("drop recipe identity", "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h", "std::uint32_t item_recipe_uid;"),
    ("drop wearable color", "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h", "LootDropSnapshotFlagItemColorState"),
    ("drop item slot", "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h", "std::int32_t item_slot;"),
    ("drop stack count", "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h", "std::int32_t stack_count;"),
    ("result inventory revision", "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h", "std::uint32_t inventory_revision;"),
    ("item drop native type", "SolomonDarkModLoader/src/multiplayer_local_transport.cpp", "kItemDropNativeTypeId = 0x07DD"),
    ("potion item type", "SolomonDarkModLoader/src/multiplayer_local_transport.cpp", "kPotionItemTypeId = 0x1B59"),
    ("held item reader", "SolomonDarkModLoader/src/multiplayer_local_transport/loot_snapshot_capture.inl", "TryReadItemDropHeldItemMetadata"),
    ("item snapshot", "SolomonDarkModLoader/src/multiplayer_local_transport/loot_snapshot_capture.inl", "TryPopulateItemLootDropSnapshot"),
    ("host item deactivation queue", "SolomonDarkModLoader/src/multiplayer_local_transport/loot_pickup_authority.inl", "QueueHostLootDropDeactivation("),
    ("host item gameplay-thread deactivation pump", "SolomonDarkModLoader/src/mod_loader_gameplay/host_loot_drop_deactivation.inl", "PumpHostLootDropDeactivation()"),
    ("host item native unregister", "SolomonDarkModLoader/src/mod_loader_gameplay/host_loot_drop_deactivation.inl", "CallActorWorldUnregisterSafe("),
    ("item payload", "SolomonDarkModLoader/src/multiplayer_local_transport/loot_pickup_authority.inl", "TryBuildAcceptedItemLootPickupPayload"),
    ("ledger mutation", "SolomonDarkModLoader/src/multiplayer_local_transport/owned_progression_state.inl", "ApplyOwnedInventoryLootItem"),
    ("host authoritative guard", "SolomonDarkModLoader/src/multiplayer_local_transport/loot_pickup_authority.inl", "inventory_host_authoritative"),
    ("item validation", "SolomonDarkModLoader/src/multiplayer_local_transport/loot_pickup_authority.inl", "drop_kind == LootDropKind::Item"),
    ("potion validation", "SolomonDarkModLoader/src/multiplayer_local_transport/loot_pickup_authority.inl", "drop_kind == LootDropKind::Potion"),
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
    ("potion presentation stack write", "SolomonDarkModLoader/src/mod_loader_gameplay/replicated_loot_reconciliation.inl", "kPotionStackCountOffset"),
    ("item recipe catalog count", "config/binary-layout.ini", "item_recipe_count=0x00B3BD2C"),
    ("item recipe catalog entries", "config/binary-layout.ini", "item_recipe_entries=0x00B3BD38"),
    ("item recipe clone seam", "config/binary-layout.ini", "item_recipe_clone=0x004699B0"),
    ("wearable color layout", "config/binary-layout.ini", "item_wearable_color_state=0x88"),
    ("exact item recipe lookup", "SolomonDarkModLoader/src/mod_loader_gameplay/native_item_materialization.inl", "TryResolveNativeItemRecipe"),
    ("exact item carrier materialization", "SolomonDarkModLoader/src/mod_loader_gameplay/native_item_materialization.inl", "SpawnNativeItemDropFromRecipe"),
    ("item post-register callee cleanup ABI", "SolomonDarkModLoader/src/mod_loader_gameplay/core/native_function_types.inl", "using ItemDropPostRegisterFn = void(__stdcall*)(void* actor);"),
    ("exact item semantic spawn", "SolomonDarkModLoader/src/mod_loader_gameplay/execute_requests/spawn_reward.inl", "ExecuteSpawnItemRewardNow"),
    ("item presentation recipe validation", "SolomonDarkModLoader/src/mod_loader_gameplay/replicated_loot_reconciliation.inl", "held_item_recipe_uid != drop.item_recipe_uid"),
    ("item presentation color write", "SolomonDarkModLoader/src/mod_loader_gameplay/replicated_loot_reconciliation.inl", "kItemWearableColorStateOffset"),
    ("native inventory insertion seam config", "config/binary-layout.ini", "inventory_insert_or_stack_item=0x0055FF20"),
    ("native inventory insertion seam", "SolomonDarkModLoader/src/gameplay_seams.h", "kInventoryInsertOrStackItem"),
    ("native inventory insertion binding", "SolomonDarkModLoader/src/gameplay_seams/state_and_address_bindings.inl", '"inventory_insert_or_stack_item"'),
    ("native inventory insertion ABI", "SolomonDarkModLoader/src/mod_loader_gameplay/core/native_function_types.inl", "InventoryInsertOrStackItemFn"),
    ("native inventory credit queue", "SolomonDarkModLoader/src/mod_loader_gameplay/native_inventory_reconciliation.inl", "QueueNativeInventoryCreditInternal"),
    ("native inventory credit apply", "SolomonDarkModLoader/src/mod_loader_gameplay/native_inventory_reconciliation.inl", "ExecuteNativeInventoryCreditNow"),
    ("native inventory recipe verification", "SolomonDarkModLoader/src/mod_loader_gameplay/native_inventory_reconciliation.inl", "held_item_recipe_uid != request.item_recipe_uid"),
    ("native inventory post-apply verification", "SolomonDarkModLoader/src/mod_loader_gameplay/native_inventory_reconciliation.inl", "expected_quantity_after"),
    ("native inventory convergence", "SolomonDarkModLoader/src/multiplayer_local_transport/public_cast_loot_queue_api.inl", "MarkLocalInventoryNativeConverged"),
    ("native inventory result queueing", "SolomonDarkModLoader/src/multiplayer_local_transport/loot_pickup_authority.inl", "QueueNativeInventoryCredit"),
    ("native inventory gameplay pump", "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_pump_loop.inl", "ExecuteNativeInventoryCreditNow"),
    ("loot lua item type", "SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp", '"item_type_id"'),
    ("loot lua recipe identity", "SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp", '"item_recipe_uid"'),
    ("loot lua color state", "SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp", '"item_color_state_valid"'),
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
