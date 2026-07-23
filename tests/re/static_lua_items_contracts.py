"""Contracts for deterministic address-free Lua item registration."""

from __future__ import annotations

from static_multiplayer_contract_support import _read, _require_in_order


def test_lua_items_register_stable_identity_and_resolve_peer_local_recipes() -> str:
    bindings = _read("SolomonDarkModLoader/src/lua_engine_bindings_items.cpp")
    root_bindings = _read("SolomonDarkModLoader/src/lua_engine_bindings.cpp")
    engine = _read("SolomonDarkModLoader/src/lua_engine.cpp")
    internal = _read("SolomonDarkModLoader/src/lua_engine_internal.h")
    public_api = _read("SolomonDarkModLoader/include/mod_loader_gameplay_api.inl")
    materialization = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/native_item_materialization.inl"
    )
    layout = _read("config/binary-layout.ini")
    project = _read("SolomonDarkModLoader/SolomonDarkModLoader.vcxproj")
    manifest = _read("mods/lua_items_registry_lab/manifest.json")
    sample = _read("mods/lua_items_registry_lab/scripts/main.lua")
    documentation = _read("docs/lua-items.md")
    roadmap = _read("docs/lua-seam-roadmap.md")
    verifier = _read("tools/verify_lua_items.py")

    assert "RegisterLuaItemBindings(mod->state)" in root_bindings
    assert "lua_engine_bindings_items.cpp" in project
    for capability in ('"items.register"', '"items.read"'):
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
        "RegisterLuaContentIdentityForMod(",
        "LuaContentKind::Item",
        "kLuaMaximumRegisteredItemsPerMod = 256",
        "native recipe is already bound by",
        "TryResolveNativeItemRecipeByName(",
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
        '"id": "sample.lua.items_registry_lab"',
        '"items.register"',
        '"items.read"',
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
    ):
        assert token in documentation, f"item documentation lacks: {token}"
    assert "**Item registration implemented 2026-07-22.**" in roadmap
    for token in (
        "sd.items.list",
        "sd.items.get(expected_id)",
        "stable_id",
        "raw_addresses_absent",
        "late_registration_rejected",
    ):
        assert token in verifier, f"item verifier lacks: {token}"

    return (
        "sd.items registers deterministic content identities, lazily resolves exact "
        "peer-local recipe name/type matches, and exposes address-free descriptors"
    )
