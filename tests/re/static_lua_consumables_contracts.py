"""Contracts for Lua-authored consumables, loot, and native multiplayer use."""

from __future__ import annotations

import struct

from static_multiplayer_contract_support import ROOT, _read, _require_in_order


def _require(label: str, text: str, tokens: tuple[str, ...]) -> None:
    missing = [token for token in tokens if token not in text]
    assert not missing, f"{label} lacks: {', '.join(missing)}"


def test_lua_consumables_are_native_stable_and_owner_executed() -> str:
    runtime_header = _read("SolomonDarkModLoader/include/lua_item_runtime.h")
    runtime = _read("SolomonDarkModLoader/src/lua_item_runtime.cpp")
    consumables = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_consumables.cpp"
    )
    loot = _read("SolomonDarkModLoader/src/lua_engine_bindings_loot.cpp")
    enemy_types = _read("SolomonDarkModLoader/include/native_enemy_types.h")
    drop_hook = _read(
        "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks/drop_roll_filter.inl"
    )
    protocol = _read(
        "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h"
    )
    transport = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport.cpp"
    )
    use_sync = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/lua_consumable_use_sync.inl"
    )
    inventory_sync = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/owned_progression_state.inl"
    )
    loot_capture = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/loot_snapshot_capture.inl"
    )
    loot_receive = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/incoming_snapshot_packet_sync.inl"
    )
    native_loot = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/replicated_loot_reconciliation.inl"
    )
    native_inventory = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/native_inventory_reconciliation.inl"
    )
    events = _read("SolomonDarkModLoader/src/lua_engine_events.cpp")
    event_header = _read("SolomonDarkModLoader/src/lua_engine_internal.h")
    event_runtime = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_runtime/level_up_and_runtime_api.inl"
    )
    native_hooks = _read("SolomonDarkModLoader/src/lua_item_native_hooks.cpp")
    gameplay_pump = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_pump_loop.inl"
    )
    gameplay_api = _read(
        "SolomonDarkModLoader/include/mod_loader_gameplay_api.inl"
    )
    gameplay_actions = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_debug_and_spawn.inl"
    )
    gameplay_bindings = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp"
    )
    engine = _read("SolomonDarkModLoader/src/lua_engine.cpp")
    damage_hook = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "player_damage_authority_hook.inl"
    )
    layout = _read("config/binary-layout.ini")
    project = _read("SolomonDarkModLoader/SolomonDarkModLoader.vcxproj")
    canary_manifest = _read(
        "mods/lua_invincibility_potion_canary/manifest.json"
    )
    canary = _read(
        "mods/lua_invincibility_potion_canary/scripts/main.lua"
    )
    canary_sprite = _read(
        "mods/lua_invincibility_potion_canary/sprites/"
        "invincibility_potion.json"
    )
    canary_readme = _read(
        "mods/lua_invincibility_potion_canary/README.md"
    )

    _require(
        "bounded consumable registry",
        runtime_header + runtime + consumables,
        (
            "kLuaMaximumRegisteredConsumables = 256",
            "kLuaMaximumConsumableDurationMs",
            "RegisterLuaConsumableDefinition",
            "reserved_subtype_by_content",
            "ReadConsumableIcon",
            "duration_ms",
            "on_consume",
            "consume_vfx",
            "LuaConsumableVfxKind::SpellGlow",
            "ClearLuaItemRuntimeForMod",
        ),
    )
    _require(
        "central additive loot pool",
        runtime_header + runtime + loot + drop_hook,
        (
            "RegisterLuaLootPoolEntry",
            "normal_chance",
            "boss_chance",
            "LuaLootRollSucceeds",
            "unit_roll < chance",
            "RollLuaLootPool(context.is_boss)",
            "QueueLuaConsumableDrop",
        ),
    )
    _require(
        "semantic stock boss classifier",
        enemy_types + drop_hook,
        (
            "kDemonSkullNativeTypeId = 0x3F0",
            "kDemonNativeTypeId = 0x3F1",
            "kDireFacultyNativeTypeId = 0x3F2",
            "kHeartmongerNativeTypeId = 0x3F3",
            "IsStockBossEnemyNativeType",
            "context.is_boss",
        ),
    )

    _require(
        "stable custom-potion wire identity",
        protocol + inventory_sync + loot_capture + loot_receive,
        (
            "constexpr std::uint16_t kProtocolVersion = 81;",
            "std::uint64_t content_id;",
            "std::uint64_t item_content_id;",
            "static_assert(sizeof(ParticipantInventoryItemPacketState) == 28",
            "static_assert(sizeof(LootDropSnapshotPacketState) == 120",
            "FindLuaConsumableDefinitionByNativeSubtype",
            "TryResolvePotionWireIdentity",
        ),
    )
    _require(
        "custom-potion native client convergence",
        native_loot + native_inventory,
        (
            "IsSupportedReplicatedPotionSubtype",
            "FindLuaConsumableDefinitionByNativeSubtype(item_slot)",
            "drop.item_slot",
            "request.item_slot",
            "CallAcceptedItemDropPickupTickSafe",
            "CallInventoryInsertOrStackItemSafe",
        ),
    )

    _require(
        "reliable authenticated consumption event",
        protocol + transport + use_sync,
        (
            "LuaConsumableUse = 28",
            "struct LuaConsumableUsePacket",
            "static_assert(sizeof(LuaConsumableUsePacket) == 56",
            "QueueLocalLuaConsumableUseInternal",
            "participant_session_nonce",
            "RememberLuaConsumableUse",
            "IsConfiguredRemoteAuthorityEndpoint",
            "RelayPacketToPeers(packet, from)",
            "DispatchLuaConsumableUse",
        ),
    )
    _require(
        "owner-only callback and peer event",
        event_header + events + event_runtime,
        (
            '"item.consumed"',
            "item_consumed_registered = true",
            'lua_setfield(state, -2, "local_owner")',
            "for (const auto& mod : LoadedLuaModsStorage())",
            "if (!local_owner ||",
            "definition->on_consume_reference",
        ),
    )
    _require_in_order(
        events,
        "for (const auto& mod : LoadedLuaModsStorage())",
        "DispatchConsumableUseToMod(",
        "if (!local_owner ||",
        "definition->on_consume_reference",
        "lua_pcall(owner->state, 1, 0, 0)",
    )

    _require(
        "stock potion presentation and use",
        native_hooks + layout,
        (
            "HookSpriteDrawAtPosition",
            "HookSpriteDrawTransformed",
            "HookItemDisplayName",
            "HookPotionHelp",
            "HookInventoryUseItem",
            "QueueLocalLuaConsumableUse",
            "inventory_use_item=0x0056D1B0",
            "inventory_find_item_by_uid=0x005521C0",
            "item_display_name=0x00571980",
            "potion_help=0x00571C80",
        ),
    )
    _require(
        "stock SpellGlow consume VFX",
        runtime + gameplay_pump + layout,
        (
            "SpawnSpellGlowForParticipant",
            "allocate(0x38)",
            "QueueLuaConsumableNativeVfx",
            "PumpLuaConsumableNativeVfx();",
            "spell_glow_ctor=0x00454AD0",
            "actor_world_register_animation=0x0063E5E0",
        ),
    )
    _require(
        "owner-local semantic mana restoration",
        gameplay_api + gameplay_actions + gameplay_bindings + engine,
        (
            "RestoreLocalPlayerMana",
            "GetX86HookTrampoline<PlayerActorApplyManaDeltaFn>",
            "maximum_mana - current_mana",
            'RegisterFunction(state, &LuaPlayerRestoreMana, "restore_mana")',
            '"player.resources.owner"',
        ),
    )
    assert "participant_id == 0 ? 1 : participant_id" in damage_hook

    _require(
        "complex invincibility-potion canary",
        canary_manifest + canary + canary_sprite + canary_readme,
        (
            '"id": "canary.lua.invincibility_potion"',
            '"items.consumables.register"',
            '"loot.register"',
            '"player.resources.owner"',
            "local DURATION_MS = 3 * 60 * 1000",
            'type = "potion"',
            'kind = "spell_glow"',
            "chance = 0.5",
            "boss_chance = 1.0",
            "sd.player.restore_mana()",
            'sd.events.on("item.consumed"',
            'sd.events.filter("damage.taken"',
            'sd.events.filter("mana.changing"',
            "return {delta = 0}",
            "sd.timer.after(event.duration_ms",
            "manually recolored derivative",
            '"width": 53',
            '"height": 50',
        ),
    )
    icon = (
        ROOT
        / "mods/lua_invincibility_potion_canary/sprites/"
        "invincibility_potion.png"
    ).read_bytes()
    assert icon[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", icon[16:24]) == (53, 50)
    bundle = (
        ROOT
        / "mods/lua_invincibility_potion_canary/sprites/"
        "invincibility_potion.bundle"
    ).read_bytes()
    assert len(bundle) == 45
    for item in (
        r"include\lua_item_runtime.h",
        r"src\lua_item_runtime.cpp",
        r"src\lua_item_native_hooks.cpp",
        r"src\lua_engine_bindings_consumables.cpp",
        r"src\lua_engine_bindings_loot.cpp",
    ):
        assert item in project, f"native project omits: {item}"

    return (
        "Lua consumables register bounded stable identities, roll additive "
        "normal/boss loot, materialize through stock potion inventory paths, "
        "replicate by content ID, execute owner-local resource effects, and ship "
        "a baked-green three-minute invincibility canary"
    )
