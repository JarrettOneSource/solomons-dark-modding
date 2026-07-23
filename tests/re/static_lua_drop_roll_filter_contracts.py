"""Contracts for owner-side Lua drop-roll filters."""

from __future__ import annotations

from static_multiplayer_contract_support import _read


def test_lua_drop_roll_filters_are_owner_side_transactional_and_stock_preserving() -> str:
    required_snippets = (
        (
            "SolomonDarkModLoader/include/lua_event_filters.h",
            "kLuaDropRollingFilterMask = 1u << 3",
        ),
        (
            "SolomonDarkModLoader/src/lua_engine_filters.cpp",
            'filter_name == "drop.rolling"',
        ),
        (
            "SolomonDarkModLoader/src/lua_engine_drop_filters.cpp",
            "ApplyLuaDropRollFilters",
        ),
        (
            "SolomonDarkModLoader/src/lua_engine.cpp",
            '"events.filters.drop_roll"',
        ),
        (
            "SolomonDarkModLoader/src/gameplay_seams/state_and_address_bindings.inl",
            '"enemy_drop_selector", kEnemyDropSelector',
        ),
        (
            "config/binary-layout.ini",
            "enemy_drop_selector=0x0047C070",
        ),
        (
            "SolomonDarkModLoader/src/run_lifecycle/state_and_targets.inl",
            "targets[kHookDropSelector] = {kEnemyDropSelector, 7}",
        ),
        (
            "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks/"
            "drop_roll_filter.inl",
            "multiplayer::IsLocalTransportClient()",
        ),
        (
            "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks/"
            "drop_roll_filter.inl",
            "RestoreLuaDropRollFilterState(original_filter_context)",
        ),
        (
            "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks/"
            "drop_roll_filter.inl",
            "selectors->fill(kDropForcedSelectorValue)",
        ),
        (
            "SolomonDarkModLoader/SolomonDarkModLoader.vcxproj",
            'ClCompile Include="src\\lua_engine_drop_filters.cpp"',
        ),
        (
            "docs/lua-drop-roll-filter.md",
            'sd.events.filter("drop.rolling", handler)',
        ),
        (
            "mods/lua_drop_roll_filter_lab/manifest.json",
            '"events.filters.drop_roll"',
        ),
    )

    for relative_path, snippet in required_snippets:
        assert snippet in _read(relative_path), (
            f"Lua drop-roll filter contract lacks {snippet!r} in {relative_path}"
        )

    return (
        "drop rolls execute only on the simulation owner, preserve the stock "
        "selector, and restore native policy after each filter transaction"
    )
