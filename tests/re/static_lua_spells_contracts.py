"""Contracts for deterministic bounded Lua spell registration."""

from __future__ import annotations

from static_multiplayer_contract_support import _read, _require_in_order


def test_lua_spells_register_stable_metadata_and_owned_callbacks() -> str:
    bindings = _read("SolomonDarkModLoader/src/lua_engine_bindings_spells.cpp")
    root_bindings = _read("SolomonDarkModLoader/src/lua_engine_bindings.cpp")
    engine = _read("SolomonDarkModLoader/src/lua_engine.cpp")
    internal = _read("SolomonDarkModLoader/src/lua_engine_internal.h")
    project = _read("SolomonDarkModLoader/SolomonDarkModLoader.vcxproj")
    manifest = _read("mods/lua_spells_registry_lab/manifest.json")
    sample = _read("mods/lua_spells_registry_lab/scripts/main.lua")
    documentation = _read("docs/lua-spells.md")
    roadmap = _read("docs/lua-seam-roadmap.md")
    verifier = _read("tools/verify_lua_spells.py")
    native_test = _read("tests/native/lua_content_registry_tests.cpp")

    assert "RegisterLuaSpellBindings(mod->state)" in root_bindings
    assert "lua_engine_bindings_spells.cpp" in project
    for capability in ('"spells.register"', '"spells.read"'):
        assert capability in engine, f"spell capability lacks: {capability}"
    for token in (
        "enum class LuaSpellSlot",
        "struct LuaSpellDefinition",
        "LuaContentIdentity identity",
        "LuaModValue config",
        "int on_cast_reference",
        "int on_tick_reference",
        "int on_hit_reference",
        "std::vector<LuaSpellDefinition> spell_definitions",
    ):
        assert token in internal, f"spell lifecycle lacks: {token}"
    assert "mod->spell_definitions.clear();" in engine

    for token in (
        'RegisterFunction(state, &LuaSpellsRegister, "register")',
        'RegisterFunction(state, &LuaSpellsGet, "get")',
        'RegisterFunction(state, &LuaSpellsList, "list")',
        "RegisterLuaContentIdentityForMod(",
        "LuaContentKind::Spell",
        "kLuaMaximumRegisteredSpellsPerMod = 256",
        "ReadLuaModValue(state, -1, &config",
        "ValidateSpellConfig(config",
        "CaptureSpellCallbackReference(state, 1, \"on_cast\")",
        "PushLuaModValue(state, definition.config)",
        "sd.spells.register on_cast must be a function",
        "sd.spells.register slot must be primary or secondary",
    ):
        assert token in bindings, f"Lua spell binding lacks: {token}"
    _require_in_order(
        bindings,
        "RegisterLuaContentIdentityForMod(",
        "CaptureSpellCallbackReference(state, 1, \"on_cast\")",
        "mod->spell_definitions.push_back",
        "PushSpellDefinition(state, mod->spell_definitions.back())",
    )
    for forbidden in (
        'lua_getfield(state, 1, "native_skill_id")',
        'lua_getfield(state, 1, "address")',
        'lua_setfield(state, -2, "callback_reference")',
        'lua_setfield(state, -2, "config_address")',
        'lua_setfield(state, -2, "actor_address")',
    ):
        assert forbidden not in bindings, f"spell API exposes native internals: {forbidden}"

    for token in (
        '"id": "sample.lua.spells_registry_lab"',
        '"spells.register"',
        '"spells.read"',
    ):
        assert token in manifest, f"spell sample manifest lacks: {token}"
    for token in (
        'key = "gravity_well"',
        'slot = "secondary"',
        "on_cast = function",
        "on_tick = function",
        "on_hit = function",
        "8348995147374483494",
    ):
        assert token in sample, f"spell sample lacks: {token}"
    assert "8348995147374483494ull" in native_test

    for token in (
        "shared `sd.content.v1` identity",
        "copied into the loader's bounded Lua value representation",
        "no Lua registry index",
        "This checkpoint does not yet make the definition selectable",
        "generic content-ID-based effect lifecycle",
    ):
        assert token in documentation, f"spell documentation lacks: {token}"
    assert "**Spell catalog foundation implemented 2026-07-22.**" in roadmap
    for token in (
        "sd.spells.list",
        "sd.spells.get(expected_id)",
        "descriptor_copy_isolated",
        "raw_internals_absent",
        "late_registration_rejected",
    ):
        assert token in verifier, f"spell verifier lacks: {token}"

    return (
        "sd.spells registers deterministic bounded metadata and owner-state callbacks "
        "without exposing native IDs, addresses, registry references, or functions"
    )
