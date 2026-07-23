"""Contracts for synchronous owner-side Lua damage filters."""

from __future__ import annotations

from static_multiplayer_contract_support import _read, _require_in_order


def test_lua_damage_filters_are_ordered_owner_side_and_transactional() -> str:
    public_api = _read("SolomonDarkModLoader/include/lua_event_filters.h")
    filters = _read("SolomonDarkModLoader/src/lua_engine_filters.cpp")
    engine = _read("SolomonDarkModLoader/src/lua_engine.cpp")
    binding_root = _read("SolomonDarkModLoader/src/lua_engine_bindings.cpp")
    runtime_bindings = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_runtime/"
        "level_up_and_runtime_api.inl"
    )
    hook = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "player_damage_authority_hook.inl"
    )
    initialization = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "public_api_keyboard_injection.inl"
    )
    project = _read("SolomonDarkModLoader/SolomonDarkModLoader.vcxproj")
    documentation = _read("docs/lua-event-filters.md")
    sample_manifest = _read("mods/lua_damage_filter_lab/manifest.json")
    sample = _read("mods/lua_damage_filter_lab/scripts/main.lua")
    live_verifier = _read("tools/verify_lua_damage_filters.py")
    runtime_verifier = _read("tools/verify_lua_runtime_contract.py")
    pair_manifest = _read("mods/lua_filter_acceptance_lab/manifest.json")
    pair_sample = _read(
        "mods/lua_filter_acceptance_lab/scripts/main.lua"
    )
    pair_verifier = _read("tools/verify_lua_filters_multiplayer.py")
    pair_tests = _read(
        "tests/test_lua_filters_multiplayer_verifier.py"
    )
    workflow = _read(".github/workflows/lua-authoring-contracts.yml")
    roadmap = _read("docs/lua-seam-roadmap.md")

    for token in (
        "kLuaDamageFilterLaneCount = 9",
        "struct LuaDamageFilterContext",
        "source_participant_id",
        "target_participant_id",
        "bool HasLuaDamageFilterHandlers();",
        "bool ApplyLuaDamageFilters(LuaDamageFilterContext* context);",
    ):
        assert token in public_api, f"public damage-filter contract lacks: {token}"

    for token in (
        'filter_name == "damage.dealing"',
        'filter_name == "damage.taken"',
        "kMaximumAbsoluteDamageLane = 1'000'000.0f",
        "std::atomic<std::uint32_t> g_registered_filter_mask",
        "std::try_to_lock",
        "for (const auto& mod : detail::LoadedLuaModsStorage())",
        'RegisterFunction(state, &LuaEventsFilter, "filter")',
        "handler must return nil, a boolean, or a table",
        "filter result ignored",
        "damage filters skipped because the Lua engine is busy",
    ):
        assert token in filters, f"synchronous filter runtime lacks: {token}"
    _require_in_order(
        filters,
        '{"damage.dealing", kDamageDealingFilterMask}',
        '{"damage.taken", kDamageTakenFilterMask}',
    )
    _require_in_order(
        filters,
        '"lanes"',
        '"projectile_damage"',
        '"magic_damage"',
    )

    assert "RegisterLuaEventFilterBinding(state);" in runtime_bindings
    assert "kLuaEventFiltersRegistryKey" in binding_root
    assert '"events.filters.damage"' in engine
    assert "ResetLuaEventFilterRegistrations();" in engine

    for token in (
        "TryCaptureLuaDamageFilterContext(",
        "ResolveLuaDamageFilterParticipantId(",
        "WriteLuaDamageFilterLanes(",
        "LuaDamageLaneWriteResult::RestoredAfterFailure",
        "LuaDamageLaneWriteResult::RestoreFailed",
        "ResetActiveDamageContext();",
    ):
        assert token in hook, f"native damage hook lacks: {token}"
    _require_in_order(
        hook,
        "if (multiplayer::IsLocalTransportClient()",
        "if (HasLuaDamageFilterHandlers())",
        "TryPrepareRemoteMagicShieldDamageAuthority(",
    )
    _require_in_order(
        hook,
        "const auto original_context = filtered_context;",
        "ApplyLuaDamageFilters(&filtered_context)",
        "WriteLuaDamageFilterLanes(",
    )

    for token in (
        "kDamageContextFlagsGlobal",
        "kDamageContextPrimaryGlobal",
        "kDamageContextSecondaryGlobal",
        "damage_context_secondary != damage_context_primary + sizeof(float)",
        "damage_context_primary_address = 0",
    ):
        assert token in initialization, f"damage seam initialization lacks: {token}"

    for source in ("lua_engine_filters.cpp", "lua_event_filters.h"):
        assert source in project, f"native project omits: {source}"

    for token in (
        "## Registration and ordering",
        "## Damage payload",
        "## Handler results",
        "## Owner and multiplayer behavior",
        "fail open",
        "process-local diagnostics",
        "events.filters.damage",
    ):
        assert token in documentation, f"damage-filter documentation lacks: {token}"
    for token in ('"enabled": false', '"events.filters.damage"'):
        assert token in sample_manifest, f"damage-filter sample manifest lacks: {token}"
    for token in (
        'sd.events.filter("damage.taken"',
        "value * 0.75",
        "return {lanes = rewritten_lanes}",
    ):
        assert token in sample, f"damage-filter sample lacks: {token}"

    for token in (
        "invoke_native_magic_hit_trial(",
        "REGISTER_REWRITES",
        "REGISTER_CANCEL",
        "baseline_damage",
        "rewritten_damage",
        "canceled_damage",
        "ordered rewrite",
    ):
        assert token in live_verifier, f"live damage-filter verifier lacks: {token}"
    assert '"events": ("on", "broadcast", "filter")' in runtime_verifier

    for token in (
        '"enabled": false',
        '"events.filters.damage"',
        '"events.filters.enemy_spawn"',
        '"events.filters.drop_roll"',
        '"events.filters.wave_spawn"',
        '"events.filters.spell_cast"',
        '"events.filters.resources"',
    ):
        assert token in pair_manifest, (
            f"filter-pair sample manifest lacks: {token}"
        )
    for token in (
        "type(sd.events.filter)",
        "sd.runtime.has_capability(capability)",
        "filter acceptance lab ready",
    ):
        assert token in pair_sample, f"filter-pair sample lacks: {token}"
    for token in (
        "sample.lua.filter_acceptance_lab",
        "FILTER_NAMES = (",
        '"damage.dealing"',
        '"damage.taken"',
        '"enemy.spawning"',
        '"drop.rolling"',
        '"wave.spawning"',
        '"spell.casting"',
        '"xp.gaining"',
        '"gold.changing"',
        '"mana.changing"',
        "queue_native_experience_gain_probe(0.0, false)",
        "before_xp == after_xp",
        "--confirm-zero-xp-probe",
        "tile_windows=False",
        "kill_existing=False",
        "stop_game_processes(launched_process_ids)",
    ):
        assert token in pair_verifier, (
            f"two-peer filter verifier lacks: {token}"
        )
    for token in (
        "test_confirmation_is_required_before_contact",
        "test_failed_launch_does_not_contact_unowned_lua_pipes",
        "test_incomplete_process_ledger_stops_only_owned_process",
        "test_run_proves_exact_registry_and_owner_local_isolation",
    ):
        assert token in pair_tests, f"filter-pair verifier tests lack: {token}"
    assert (
        "python -m unittest tests.test_lua_filters_multiplayer_verifier"
        in workflow
    )
    for source in (documentation, roadmap):
        for token in (
            "Exact two-peer",
            "zero-delta",
            "owner",
            "process-local",
            "family-specific",
        ):
            assert token in source, (
                f"filter multiplayer documentation lacks: {token}"
            )
    assert (
        "tools/verify_lua_filters_multiplayer.py "
        "--launch-pair --confirm-zero-xp-probe"
        in documentation
    )

    return (
        "damage filters run synchronously after the owner gate, compose in stable "
        "order, validate patches transactionally, reset on cancellation, and have "
        "docs, an opt-in sample, namespace coverage, native-hit acceptance, and "
        "exact-pair registry isolation"
    )
