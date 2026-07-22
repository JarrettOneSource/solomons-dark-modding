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

    return (
        "damage filters run synchronously after the owner gate, compose in stable "
        "order, validate patches transactionally, reset on cancellation, and have "
        "docs, an opt-in sample, namespace coverage, and native-hit acceptance"
    )
