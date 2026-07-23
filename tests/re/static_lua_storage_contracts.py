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
    multiplayer_verifier = _read(
        "tools/verify_lua_storage_multiplayer.py"
    )
    multiplayer_verifier_tests = _read(
        "tests/test_lua_storage_multiplayer_verifier.py"
    )
    workflow = _read(".github/workflows/lua-authoring-contracts.yml")

    assert "RegisterLuaStorageBindings(mod->state)" in bindings
    assert "lua_createtable(mod->state, 0, 30);" in bindings
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
    for token in (
        'ACCEPTANCE_MOD_ID = "sample.lua.storage_lab"',
        "_preserve_profile_storage",
        "_atomic_restore",
        "STATE_PROBE",
        "CLEAR_PROBE",
        "DELETE_PROBE",
        "_write_probe",
        "storage_state_matches",
        "_storage_file_evidence",
        "--confirm-profile-mutation",
        "temporary_host_profile=True",
        "tile_windows=False",
        "kill_existing=False",
        "exact_mod_id=ACCEPTANCE_MOD_ID",
        "stop_game_processes(launched_process_ids)",
    ):
        assert token in multiplayer_verifier, (
            f"Lua storage multiplayer verifier lacks: {token}"
        )
    for token in (
        "test_state_matcher_requires_exact_local_value",
        "test_profile_files_are_preserved_and_generated_files_removed",
        "test_durable_file_evidence_requires_distinct_bounded_files",
        "test_mutation_confirmation_is_required_before_contact",
        "test_disposable_pair_is_required_before_contact",
        "test_failed_launch_does_not_contact_unowned_lua_pipes",
        "test_incomplete_process_ledger_stops_only_owned_process",
        "test_run_proves_local_persistence_and_restores_profiles",
    ):
        assert token in multiplayer_verifier_tests, (
            f"Lua storage multiplayer verifier tests lack: {token}"
        )
    assert (
        "python -m unittest tests.test_lua_storage_multiplayer_verifier"
        in workflow
    )

    return (
        "sd.storage isolates bounded values per mod and launcher profile, "
        "publishes writes transactionally, and has exact restart-persistent "
        "two-peer isolation acceptance"
    )
