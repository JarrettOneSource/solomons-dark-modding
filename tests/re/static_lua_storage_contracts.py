"""Contracts for scoped local Lua profile storage."""

from __future__ import annotations

from static_multiplayer_contract_support import _read, _require_in_order


def test_lua_storage_is_scoped_bounded_and_transactional() -> str:
    bindings = _read("SolomonDarkModLoader/src/lua_engine_bindings.cpp")
    storage = _read("SolomonDarkModLoader/src/lua_engine_bindings_storage.cpp")
    internal = _read("SolomonDarkModLoader/src/lua_engine_internal.h")
    engine = _read("SolomonDarkModLoader/src/lua_engine.cpp")
    project = _read("SolomonDarkModLoader/SolomonDarkModLoader.vcxproj")
    documentation = _read("docs/lua-storage.md")
    roadmap = _read("docs/lua-seam-roadmap.md")
    manifest = _read("mods/lua_storage_lab/manifest.json")
    sample = _read("mods/lua_storage_lab/scripts/main.lua")
    verifier = _read("tools/verify_lua_storage.py")

    assert "RegisterLuaStorageBindings(mod->state)" in bindings
    assert "lua_createtable(mod->state, 0, 22);" in bindings
    assert "LuaModStateValues profile_storage_values" in internal
    assert '"storage.profile.local"' in engine
    assert "lua_engine_bindings_storage.cpp" in project

    for token in (
        'kProfileStorageFileName[] = L"profile-storage.bin"',
        "mod.descriptor.data_root_path / kProfileStorageFileName",
        "EncodeLuaModStateSnapshot",
        "DecodeLuaModStateSnapshot",
        "kLuaModMaxStateSnapshotBytes",
        "MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH",
        "auto next = mod->profile_storage_values",
        "PersistProfileStorage(*mod, next",
        "mod->profile_storage_values = std::move(next)",
        'RegisterFunction(state, &LuaStorageGet, "get")',
        'RegisterFunction(state, &LuaStorageSet, "set")',
        'RegisterFunction(state, &LuaStorageDelete, "delete")',
        'RegisterFunction(state, &LuaStorageClear, "clear")',
        'RegisterFunction(state, &LuaStorageSnapshot, "snapshot")',
    ):
        assert token in storage, f"Lua storage implementation lacks: {token}"
    _require_in_order(
        storage,
        "auto next = mod->profile_storage_values",
        "PersistProfileStorage(*mod, next",
        "mod->profile_storage_values = std::move(next)",
    )
    assert "io." not in sample
    assert '"enabled": false' in manifest
    assert '"storage.profile.local"' in manifest
    assert "sd.storage.get" in sample and "sd.storage.set" in sample

    for token in (
        "## API",
        "## Multiplayer",
        "never replicated",
        "replace-and-flush",
        "storage.profile.local",
    ):
        assert token in documentation, f"Lua storage documentation lacks: {token}"
    assert "**Implemented 2026-07-22.** `sd.storage`" in roadmap
    for token in (
        'choices=("write", "read", "clear")',
        'sd.storage.set("acceptance"',
        'sd.storage.get("acceptance")',
        "cyclic value was accepted",
        "persisted token mismatch",
        "sd.storage.clear()",
    ):
        assert token in verifier, f"Lua storage verifier lacks: {token}"

    return (
        "sd.storage isolates bounded values per mod and launcher profile, "
        "publishes writes transactionally, and stays local in multiplayer"
    )
