"""Contracts for synchronous owner-side Lua enemy-spawn filters."""

from __future__ import annotations

from static_multiplayer_contract_support import _read, _require_in_order


def test_lua_enemy_spawn_filter_preserves_stock_call_shape_and_ownership() -> str:
    public_api = _read("SolomonDarkModLoader/include/lua_event_filters.h")
    registration = _read("SolomonDarkModLoader/src/lua_engine_filters.cpp")
    runtime = _read(
        "SolomonDarkModLoader/src/lua_engine_enemy_spawn_filters.cpp"
    )
    hook = _read(
        "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks/"
        "wave_and_enemy_spawn_hooks.inl"
    )
    native_filter = _read(
        "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks/"
        "enemy_spawn_filter.inl"
    )
    state = _read("SolomonDarkModLoader/src/run_lifecycle/state_and_targets.inl")
    engine = _read("SolomonDarkModLoader/src/lua_engine.cpp")
    project = _read("SolomonDarkModLoader/SolomonDarkModLoader.vcxproj")
    documentation = _read("docs/lua-enemy-spawn-filter.md")
    roadmap = _read("docs/lua-seam-roadmap.md")
    sample_manifest = _read("mods/lua_enemy_spawn_filter_lab/manifest.json")
    sample = _read("mods/lua_enemy_spawn_filter_lab/scripts/main.lua")
    live_verifier = _read("tools/verify_lua_enemy_spawn_filters.py")

    for token in (
        "kLuaEnemySpawningFilterMask",
        "kLuaEnemySpawnFamilyValueCount = 4",
        "struct LuaEnemySpawnFilterContext",
        "native_type_id",
        "wave_spawner_address",
        "bool HasLuaEnemySpawnFilterHandlers();",
        "bool ApplyLuaEnemySpawnFilters(LuaEnemySpawnFilterContext* context);",
    ):
        assert token in public_api, f"public enemy-spawn filter contract lacks: {token}"

    assert 'filter_name == "enemy.spawning"' in registration
    assert "kLuaEnemySpawningFilterMask" in registration

    for token in (
        'kEnemySpawningFilterName[] = "enemy.spawning"',
        '"family_values"',
        '"primary_damage"',
        '"secondary_damage"',
        '"chase_speed"',
        '"attack_speed"',
        '"scale"',
        "std::try_to_lock",
        "for (const auto& mod : detail::LoadedLuaModsStorage())",
        "filter result ignored",
        "enemy spawn filters skipped because the Lua engine is busy",
    ):
        assert token in runtime, f"enemy-spawn filter runtime lacks: {token}"
    _require_in_order(runtime, '"family_values"', '"primary_damage"', '"secondary_damage"')

    for token in (
        "TryCaptureLuaEnemySpawnFilterContext(",
        "WriteLuaEnemySpawnFilterConfig(",
        "RestoreLuaEnemySpawnFilterConfig(",
        "LuaEnemySpawnConfigWriteResult::RestoredAfterFailure",
        "LuaEnemySpawnConfigWriteResult::RestoreFailed",
        "CanceledEnemySpawnResult()",
    ):
        assert token in native_filter, f"native enemy-spawn transaction lacks: {token}"
    assert "return CanceledEnemySpawnResult();" in hook
    _require_in_order(
        hook,
        "!multiplayer::IsLocalTransportClient()",
        "!g_manual_run_enemy_spawner_tick_active",
        "ApplyLuaEnemySpawnFilters(&filtered_context)",
        "original(",
        "RestoreLuaEnemySpawnFilterConfig(original_filter_context)",
        "DispatchLuaEnemySpawned(enemy_type, x, y)",
    )

    for token in (
        "kEnemySpawnConfigHpOffset = 0x58",
        "kEnemySpawnConfigFamilyValuesOffset = 0x5C",
        "kEnemySpawnConfigChaseSpeedOffset = 0x6C",
        "kEnemySpawnConfigAttackSpeedOffset = 0x70",
        "kEnemySpawnConfigScaleOffset = 0x74",
        "kCanceledEnemySpawnResultSize = 0x400",
    ):
        assert token in state, f"enemy-spawn native layout lacks: {token}"

    assert '"events.filters.enemy_spawn"' in engine
    assert "lua_engine_enemy_spawn_filters.cpp" in project
    assert "enemy_spawn_filter.inl" in project

    for token in (
        "## Payload",
        "## Handler results",
        "## Native safety and ownership",
        "loader-owned writable sentinel",
        "events.filters.enemy_spawn",
        "shared config is restored",
    ):
        assert token in documentation, f"enemy-spawn filter documentation lacks: {token}"
    assert "Damage and enemy-spawn slices implemented" in roadmap
    for token in ('"enabled": false', '"events.filters.enemy_spawn"'):
        assert token in sample_manifest, f"enemy-spawn sample manifest lacks: {token}"
    for token in (
        'sd.events.filter("enemy.spawning"',
        "hp = event.hp * 1.5",
        "chase_speed = event.chase_speed * 1.1",
    ):
        assert token in sample, f"enemy-spawn sample lacks: {token}"

    for token in (
        "FIRST_REWRITE_HP",
        "FINAL_REWRITE_HP",
        'sd.events.filter("enemy.spawning"',
        'sd.events.on("enemy.spawned"',
        "second handler did not observe the first ordered rewrite",
        "native actor did not consume the final rewritten max HP",
    ):
        assert token in live_verifier, f"enemy-spawn live verifier lacks: {token}"

    return (
        "enemy.spawning composes bounded config rewrites on the authority, "
        "restores shared native state, cancels through the proven retail return "
        "contract, and has docs, an opt-in sample, and live acceptance coverage"
    )
