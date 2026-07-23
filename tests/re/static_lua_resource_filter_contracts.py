"""Contracts for synchronous Lua XP and gold resource filters."""

from __future__ import annotations

from static_multiplayer_contract_support import _read, _require_in_order


def test_lua_resource_filters_are_native_ordered_and_authoritative() -> str:
    public_api = _read("SolomonDarkModLoader/include/lua_event_filters.h")
    registration = _read("SolomonDarkModLoader/src/lua_engine_filters.cpp")
    filters = _read("SolomonDarkModLoader/src/lua_engine_resource_filters.cpp")
    hooks = _read(
        "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks/"
        "enemy_death_reward_level_up_hooks.inl"
    )
    targets = _read("SolomonDarkModLoader/src/run_lifecycle/state_and_targets.inl")
    install = _read("SolomonDarkModLoader/src/run_lifecycle/public_api_and_install.inl")
    layout = _read("config/binary-layout.ini")
    gold_pickup = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "gold_pickup_hook.inl"
    )
    mana_hook = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "player_mana_hooks.inl"
    )
    loot_authority = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "loot_pickup_packet_handlers.inl"
    )
    capabilities = _read("SolomonDarkModLoader/src/lua_engine.cpp")
    debug_bindings = _read("SolomonDarkModLoader/src/lua_engine_bindings_debug.cpp")
    xp_probe = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "native_experience_gain_probe.inl"
    )
    native_probe_pump = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "dispatch_and_hooks_native_probe_pump.inl"
    )
    project = _read("SolomonDarkModLoader/SolomonDarkModLoader.vcxproj")
    documentation = _read("docs/lua-resource-filters.md")
    sample_manifest = _read("mods/lua_resource_filter_lab/manifest.json")
    sample = _read("mods/lua_resource_filter_lab/scripts/main.lua")
    live_verifier = _read("tools/verify_lua_resource_filters.py")

    for token in (
        "kLuaXpGainingFilterMask",
        "kLuaGoldChangingFilterMask",
        "kLuaManaChangingFilterMask",
        "struct LuaXpGainFilterContext",
        "struct LuaGoldChangeFilterContext",
        "struct LuaManaChangeFilterContext",
        "ApplyLuaXpGainFilters",
        "ApplyLuaGoldChangeFilters",
        "ApplyLuaManaChangeFilters",
    ):
        assert token in public_api, f"resource-filter public contract lacks: {token}"

    for token in (
        'filter_name == "xp.gaining"',
        'filter_name == "gold.changing"',
        'filter_name == "mana.changing"',
        "ResetLuaResourceFilterDiagnostics",
    ):
        assert token in registration, f"resource-filter registration lacks: {token}"

    for token in (
        'kXpGainingFilterName[] = "xp.gaining"',
        'kGoldChangingFilterName[] = "gold.changing"',
        'lua_setfield(state, -2, "current_xp")',
        'lua_setfield(state, -2, "native_scaling")',
        'lua_setfield(state, -2, "current_gold")',
        'lua_setfield(state, -2, "resulting_gold")',
        'lua_setfield(state, -2, "would_succeed")',
        'kManaChangingFilterName[] = "mana.changing"',
        'lua_setfield(state, -2, "current_mana")',
        'lua_setfield(state, -2, "maximum_mana")',
        "ParseManaChangePatch",
        "ApplyLuaManaChangeFilters",
        "for (const auto& mod : detail::LoadedLuaModsStorage())",
        "std::try_to_lock",
        "filter result ignored",
        "delta would overflow the native gold total",
    ):
        assert token in filters, f"resource-filter runtime lacks: {token}"

    assert "experience_gain=0x00680AD8" in layout
    for token in (
        "using ExperienceGainFn",
        "kHookExperienceGain",
        "targets[kHookExperienceGain] = {kExperienceGain, 5}",
    ):
        assert token in targets, f"XP native target lacks: {token}"
    for token in (
        "reinterpret_cast<void*>(&HookExperienceGain)",
        '"experience.gain"',
    ):
        assert token in install, f"XP hook installation lacks: {token}"

    xp_hook = hooks.split("void __fastcall HookExperienceGain", 1)[1].split(
        "void __fastcall HookDropSpawned", 1
    )[0]
    _require_in_order(
        xp_hook,
        "kProgressionXpOffset",
        "ApplyLuaXpGainFilters(&filter_context)",
        "original(self, amount, apply_native_scaling)",
    )
    gold_hook = hooks.split("int __stdcall HookGoldChanged", 1)[1].split(
        "void __fastcall HookExperienceGain", 1
    )[0]
    _require_in_order(
        gold_hook,
        "TryReadResolvedGlobalInt(kGoldGlobal, &gold_before)",
        "!IsApplyingAcceptedReplicatedGoldPickupFeedback()",
        "ApplyLuaGoldChangeFilters(&filter_context)",
        "original(filtered_delta, allow_negative)",
        "gold - gold_before",
        "DispatchLuaGoldChanged(gold, applied_delta, source)",
    )

    _require_in_order(
        gold_pickup,
        "++g_accepted_replicated_loot_feedback_depth",
        "original(self)",
        "--g_accepted_replicated_loot_feedback_depth",
    )
    _require_in_order(
        mana_hook,
        "TryReadProgressionMana(",
        "ApplyLuaManaChangeFilters(&filtered_context)",
        "delta = filtered_context.delta",
        "return original(self, delta, allow_prompt)",
    )
    _require_in_order(
        loot_authority,
        'filter_context.source = "pickup"',
        "sdmod::ApplyLuaGoldChangeFilters(&filter_context)",
        "QueueHostLootDropDeactivation",
    )
    assert '"queue_native_experience_gain_probe"' in debug_bindings
    assert '"get_native_experience_gain_probe_result"' in debug_bindings
    assert "CallNativeExperienceGainSafe" in xp_probe
    assert "ExecuteNativeExperienceGainProbe" in native_probe_pump

    assert '"events.filters.resources"' in capabilities
    assert "lua_engine_resource_filters.cpp" in project
    for token in (
        "## XP payload",
        "## Gold payload",
        "## Mana payload",
        "## Handler results",
        "## Ownership and replication",
        "accepted feedback replay is explicitly excluded",
        "events.filters.resources",
    ):
        assert token in documentation, f"resource-filter documentation lacks: {token}"
    assert '"enabled": false' in sample_manifest
    assert '"events.filters.resources"' in sample_manifest
    assert 'sd.events.filter("xp.gaining"' in sample
    assert 'sd.events.filter("gold.changing"' in sample
    for token in (
        "xp_ordered_rewrite",
        "xp_cancellation",
        "gold_ordered_rewrite",
        "gold_cancellation",
        "native_experience_gain",
        "native_gold_change",
        "queue_native_experience_gain_probe",
    ):
        assert token in live_verifier, f"resource-filter live verifier lacks: {token}"

    return (
        "XP, gold, and mana filters run in stable Lua order before stock "
        "mutation, preserve owner identity, and exclude accepted client replay"
    )
