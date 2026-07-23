"""Contracts for deterministic address-free Lua item registration and grants."""

from __future__ import annotations

from static_multiplayer_contract_support import _read, _require_in_order


def test_lua_items_register_stable_identity_and_resolve_peer_local_recipes() -> str:
    bindings = _read("SolomonDarkModLoader/src/lua_engine_bindings_items.cpp")
    root_bindings = _read("SolomonDarkModLoader/src/lua_engine_bindings.cpp")
    engine = _read("SolomonDarkModLoader/src/lua_engine.cpp")
    internal = _read("SolomonDarkModLoader/src/lua_engine_internal.h")
    public_api = _read("SolomonDarkModLoader/include/mod_loader_gameplay_api.inl")
    transport_api = _read(
        "SolomonDarkModLoader/include/multiplayer_local_transport.h"
    )
    protocol = _read("SolomonDarkModLoader/include/multiplayer_runtime_protocol.h")
    transport = _read("SolomonDarkModLoader/src/multiplayer_local_transport.cpp")
    transport_public = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/public_cast_loot_api.inl"
    )
    grant_transport = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/lua_item_grant_sync.inl"
    )
    packet_dispatch = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/incoming_packet_dispatch.inl"
    )
    materialization = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/native_item_materialization.inl"
    )
    grant_gameplay = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/lua_item_grant.inl"
    )
    gameplay_pump = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_pump_loop.inl"
    )
    layout = _read("config/binary-layout.ini")
    project = _read("SolomonDarkModLoader/SolomonDarkModLoader.vcxproj")
    compatibility = _read(
        "SolomonDarkModLauncher/src/Staging/MultiplayerCompatibilityMaterializer.cs"
    )
    manifest = _read("mods/lua_items_registry_lab/manifest.json")
    sample = _read("mods/lua_items_registry_lab/scripts/main.lua")
    documentation = _read("docs/lua-items.md")
    roadmap = _read("docs/lua-seam-roadmap.md")
    verifier = _read("tools/verify_lua_items.py")
    grant_verifier = _read("tools/verify_lua_item_grant.py")

    assert "RegisterLuaItemBindings(mod->state)" in root_bindings
    assert "lua_engine_bindings_items.cpp" in project
    for capability in (
        '"items.register"',
        '"items.read"',
        '"items.grant.authority"',
    ):
        assert capability in engine
    for token in (
        "struct LuaItemDefinition",
        "LuaContentIdentity identity",
        "std::vector<LuaItemDefinition> item_definitions",
    ):
        assert token in internal, f"item lifecycle lacks: {token}"
    for token in (
        'RegisterFunction(state, &LuaItemsRegister, "register")',
        'RegisterFunction(state, &LuaItemsGet, "get")',
        'RegisterFunction(state, &LuaItemsList, "list")',
        'RegisterFunction(state, &LuaItemsGrant, "grant")',
        "RegisterLuaContentIdentityForMod(",
        "LuaContentKind::Item",
        "kLuaMaximumRegisteredItemsPerMod = 256",
        "native recipe is already bound by",
        "TryResolveNativeItemRecipeByName(",
        "QueueAuthoritativeLuaItemGrant(",
        "sd.items.grant may only be called by the simulation authority",
        "definition->identity.network_id",
    ):
        assert token in bindings, f"Lua item binding lacks: {token}"
    _require_in_order(
        bindings,
        "RegisterLuaContentIdentityForMod(",
        "mod->item_definitions.push_back",
        "PushItemDefinition(state, mod->item_definitions.back())",
    )
    for forbidden in (
        'lua_getfield(state, 1, "recipe_uid")',
        'lua_getfield(state, 1, "address")',
        'lua_setfield(state, -2, "address")',
        'lua_setfield(state, -2, "recipe_address")',
        'lua_setfield(state, -2, "catalog_address")',
    ):
        assert forbidden not in bindings, f"item API exposes native identity: {forbidden}"

    assert "TryResolveNativeItemRecipeByName" in public_api
    for token in (
        "kNativeItemRecipeCatalogMaxEntries = 16384",
        "TryReadNativeItemRecipeNameEquals",
        "candidate_type_id != expected_item_type_id",
        "native item recipe name/type identity is ambiguous",
        "The native item recipe is not loaded",
    ):
        assert token in materialization, f"native item lookup lacks: {token}"
    assert "item_recipe_definition_name=0x34" in layout

    for token in (
        "QueueLuaItemGrantToLocalInventory",
        "QueueAuthoritativeLuaItemGrant",
    ):
        assert token in public_api + transport_api, f"item grant API lacks: {token}"
    for token in (
        "constexpr std::uint16_t kProtocolVersion = 78;",
        "LuaItemGrant = 22",
        "struct LuaItemGrantPacket",
        "std::uint64_t content_id",
        "static_assert(sizeof(LuaItemGrantPacket) == 84",
    ):
        assert token in protocol, f"item grant protocol lacks: {token}"
    grant_packet = protocol.split("struct LuaItemGrantPacket", 1)[1].split("};", 1)[0]
    assert "recipe_uid" not in grant_packet
    assert "CurrentProtocolVersion = 77;" in compatibility
    for token in (
        "SendQueuedAuthoritativeLuaItemGrants",
        "SendPacketToParticipantOrPeers(packet, grant.target_participant_id)",
        "IsConfiguredRemoteAuthorityEndpoint(from)",
        "packet.target_participant_id != g_local_transport.local_peer_id",
        "received_lua_item_grant_request_ids",
        "QueueLuaItemGrantToLocalInventory",
        "LuaItemGrantFlagColorState",
    ):
        assert token in grant_transport, f"item grant transport lacks: {token}"
    assert "PacketKind::LuaItemGrant" in packet_dispatch
    for token in (
        '"multiplayer_local_transport/lua_item_grant_sync.inl"',
        "g_queued_authoritative_lua_item_grants.clear()",
        "SendQueuedAuthoritativeLuaItemGrants()",
    ):
        assert token in transport + transport_public, (
            f"item grant transport integration lacks: {token}"
        )
    for token in (
        "TryResolveLuaItemNativeRecipe",
        "CloneNativeItemFromRecipe",
        "CallInventoryInsertOrStackItemSafe",
        "FindInventoryRootItemPointer",
        "quantity_after >= quantity_before + 1",
        "kGameplayInventoryDirtyOffset",
    ):
        assert token in grant_gameplay, f"native item grant lacks: {token}"
    _require_in_order(
        grant_gameplay,
        "TryResolveLuaItemNativeRecipe(",
        "CloneNativeItemFromRecipe(",
        "CallInventoryInsertOrStackItemSafe(",
    )
    for token in (
        "ExecuteLuaItemGrantNow",
        "kLuaItemGrantRetryDelayMs",
        "kLuaItemGrantExpiryMs",
    ):
        assert token in grant_gameplay, f"item grant gameplay service lacks: {token}"
    assert "ProcessPendingLuaItemGrant(now_ms)" in gameplay_pump

    for token in (
        '"id": "sample.lua.items_registry_lab"',
        '"items.register"',
        '"items.read"',
        '"items.grant.authority"',
    ):
        assert token in manifest, f"item sample manifest lacks: {token}"
    for token in (
        'key = "pentaclostic_ring"',
        'name = "Pentaclostic Ring"',
        'type = "ring"',
        "5785942626980372610",
    ):
        assert token in sample, f"item sample lacks: {token}"
    for token in (
        "numeric recipe UID. The registry rejects",
        "Peer-local runtime UID",
        "stable `id` and resolve the receiving peer's UID",
        "Descriptors never include recipe pointers",
        "Only the offline or host simulation authority may grant an item",
        "Protocol 78",
        "recipe UIDs and native addresses never cross the wire",
        "exactly 32 integer bytes",
    ):
        assert token in documentation, f"item documentation lacks: {token}"
    assert "**Item registration and grants implemented 2026-07-22.**" in roadmap
    for token in (
        "sd.items.list",
        "sd.items.get(expected_id)",
        "stable_id",
        "raw_addresses_absent",
        "late_registration_rejected",
    ):
        assert token in verifier, f"item verifier lacks: {token}"
    for token in (
        "--confirm-mutation",
        "sd.items.grant(item.id)",
        "before_count",
        "after_count",
        "refusing inventory mutation",
    ):
        assert token in grant_verifier, f"item grant verifier lacks: {token}"

    return (
        "sd.items registers deterministic identities and authority-routes stable IDs "
        "to verified peer-local stock inventory insertion without wire recipe UIDs"
    )
