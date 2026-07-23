"""Contracts for deterministic cross-type Lua content identity."""

from __future__ import annotations

from static_multiplayer_contract_support import _read, _require_in_order


def test_lua_content_ids_are_canonical_deterministic_and_load_scoped() -> str:
    header = _read("SolomonDarkModLoader/include/lua_content_registry.h")
    registry = _read("SolomonDarkModLoader/src/lua_content_registry.cpp")
    internal = _read("SolomonDarkModLoader/src/lua_engine_internal.h")
    loading = _read("SolomonDarkModLoader/src/lua_engine_mod_loading.cpp")
    engine = _read("SolomonDarkModLoader/src/lua_engine.cpp")
    project = _read("SolomonDarkModLoader/SolomonDarkModLoader.vcxproj")
    validator = _read("SolomonDarkModLauncher/src/Mods/ModManifestValidator.cs")
    launcher_tests = _read("tests/launcher-contracts/Program.cs")
    native_test = _read("tests/native/lua_content_registry_tests.cpp")
    documentation = _read("docs/lua-content-identity.md")
    roadmap = _read("docs/lua-seam-roadmap.md")

    for token in (
        "enum class LuaContentKind",
        "Spell,",
        "Enemy,",
        "Item,",
        "ComputeLuaContentNetworkId",
        "RegisterLuaContentIdentity",
        "FindLuaContentIdentity",
        "UnregisterLuaContentIdentitiesForMod",
    ):
        assert token in header, f"content identity header lacks: {token}"
    assert "lua_content_registry.cpp" in project

    for token in (
        "kFnv1aOffsetBasis = 14695981039346656037ull",
        "kFnv1aPrime = 1099511628211ull",
        "kLuaContentNamespaceBit = 0x4000000000000000ull",
        "kLuaContentHashMask = 0x3FFFFFFFFFFFFFFFull",
        "kLuaContentHashDomain",
        "HashLength(value.size(), hash)",
        "duplicate Lua ",
        "already registered as ",
        "network ID collision between ",
    ):
        assert token in registry, f"content identity implementation lacks: {token}"
    assert "LuaContentKind" not in registry.split(
        "std::uint64_t ComputeLuaContentNetworkId", 1
    )[1].split("bool RegisterLuaContentIdentity", 1)[0]

    assert "bool content_registration_open = false" in internal
    assert "RegisterLuaContentIdentityForMod" in internal
    for token in (
        "!mod->content_registration_open",
        "only while the owning entry script loads",
        "RegisterLuaContentIdentity(",
    ):
        assert token in loading, f"content load boundary lacks: {token}"
    _require_in_order(
        engine,
        "mod->content_registration_open = true",
        "ExecuteEntryScript(mod, error_message)",
        "mod->content_registration_open = false",
    )
    _require_in_order(
        engine,
        "UnregisterLuaContentIdentitiesForMod(mod->descriptor.id)",
        "lua_close(mod->state)",
    )
    assert engine.count("ResetLuaContentRegistry();") >= 3

    for token in (
        "ValidateModIdentifier(manifestPath, manifest.Id, \"id\")",
        "Invalid lowercase mod identifier",
        "modId.Length > 128",
        "ValidateModIdentifier(manifestPath, requiredModId, \"requiredMods\")",
    ):
        assert token in validator, f"canonical manifest identity lacks: {token}"
    for token in (
        '"canonical mod identifiers"',
        '"Tests.Uppercase"',
        '"Tests.Dependency"',
        "manifest accepted a non-canonical mod id",
    ):
        assert token in launcher_tests, f"launcher identity test lacks: {token}"

    for value in (
        "8108516122269430198ull",
        "6415373166652859851ull",
        "7260085584278011992ull",
        "8726222830294414077ull",
        "cross-kind key reuse was accepted",
        "mod unload left content registered",
    ):
        assert value in native_test, f"native content registry test lacks: {value}"
    for token in (
        "sd.content.v1",
        "little-endian 32-bit byte length",
        "content kind is deliberately not part of the hash",
        "Registration is open only while that mod's entry script is loading",
        "exact enabled manifest/content hash",
    ):
        assert token in documentation, f"content identity documentation lacks: {token}"
    assert "**Identity foundation implemented 2026-07-22.**" in roadmap

    return (
        "Lua content IDs use one canonical load-scoped hash registry with fixed vectors, "
        "collision rejection, manifest validation, and deterministic unload cleanup"
    )
