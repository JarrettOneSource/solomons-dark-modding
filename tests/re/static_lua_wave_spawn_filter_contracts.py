"""Contracts for owner-side Lua wave-spawn filters."""

from __future__ import annotations

from static_multiplayer_contract_support import _read


def test_lua_wave_spawn_filters_are_owner_side_transactional_and_stock_preserving() -> str:
    required_snippets = (
        (
            "SolomonDarkModLoader/include/lua_event_filters.h",
            "kLuaWaveSpawningFilterMask",
        ),
        (
            "SolomonDarkModLoader/src/lua_engine_filters.cpp",
            'filter_name == "wave.spawning"',
        ),
        (
            "SolomonDarkModLoader/src/lua_engine_wave_spawn_filters.cpp",
            "ApplyLuaWaveSpawnFilters",
        ),
        (
            "SolomonDarkModLoader/src/lua_engine_wave_spawn_filters.cpp",
            '"count"',
        ),
        (
            "SolomonDarkModLoader/src/lua_engine.cpp",
            '"events.filters.wave_spawn"',
        ),
        (
            "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks/"
            "wave_spawn_filter.inl",
            "ClaimLuaWaveSpawnFilterInstance",
        ),
        (
            "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks/"
            "wave_spawn_filter.inl",
            "FinishLuaWaveSpawnFilterTick",
        ),
        (
            "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks/"
            "wave_spawn_filter.inl",
            "multiplayer::IsLocalTransportClient()",
        ),
        (
            "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks/"
            "wave_spawn_filter.inl",
            "RestoreLuaWaveSpawnFilterState(original)",
        ),
        (
            "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks/"
            "wave_spawn_filter.inl",
            "context.count = 0",
        ),
        (
            "SolomonDarkModLoader/SolomonDarkModLoader.vcxproj",
            'ClCompile Include="src\\lua_engine_wave_spawn_filters.cpp"',
        ),
        (
            "docs/lua-wave-spawn-filter.md",
            'sd.events.filter("wave.spawning", handler)',
        ),
        (
            "mods/lua_wave_spawn_filter_lab/manifest.json",
            '"events.filters.wave_spawn"',
        ),
        (
            "tests/fixtures/waves/lua_wave_filter_test.txt",
            "SPAWN:2",
        ),
    )

    for relative_path, snippet in required_snippets:
        assert snippet in _read(relative_path), (
            f"Lua wave-spawn filter contract lacks {snippet!r} in {relative_path}"
        )

    return (
        "wave spawn actions execute once on the simulation owner, preserve stock "
        "bookkeeping, and restore native state after each filter transaction"
    )
