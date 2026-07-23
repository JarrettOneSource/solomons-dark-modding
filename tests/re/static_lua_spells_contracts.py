"""Contracts for deterministic bounded Lua spell registration."""

from __future__ import annotations

from static_multiplayer_contract_support import (
    _read,
    _require_in_order,
    read_source_unit,
)


def test_lua_spells_register_stable_metadata_and_owned_callbacks() -> str:
    bindings = read_source_unit(
        "SolomonDarkModLoader/src/lua_engine_bindings_spells.cpp"
    )
    root_bindings = _read("SolomonDarkModLoader/src/lua_engine_bindings.cpp")
    engine = _read("SolomonDarkModLoader/src/lua_engine.cpp")
    internal = _read("SolomonDarkModLoader/src/lua_engine_internal.h")
    casts = _read("SolomonDarkModLoader/src/lua_engine_registered_spell_casts.cpp")
    selection = _read(
        "SolomonDarkModLoader/src/lua_engine_registered_spell_selection.cpp"
    )
    effects = _read("SolomonDarkModLoader/src/lua_engine_registered_spell_effects.cpp")
    player_cast_hooks = read_source_unit(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "player_cast_hooks.inl"
    )
    input_hooks = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/input_hooks.inl"
    )
    transport = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "lua_registered_spell_cast_sync.inl"
    )
    effect_transport = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "lua_registered_spell_effect_sync.inl"
    )
    dispatch = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "incoming_packet_dispatch.inl"
    )
    protocol = _read("SolomonDarkModLoader/include/multiplayer_runtime_protocol.h")
    project = _read("SolomonDarkModLoader/SolomonDarkModLoader.vcxproj")
    manifest = _read("mods/lua_spells_registry_lab/manifest.json")
    sample = _read("mods/lua_spells_registry_lab/scripts/main.lua")
    documentation = _read("docs/lua-spells.md")
    picker_documentation = _read("docs/spell-picker-re.md")
    roadmap = _read("docs/lua-seam-roadmap.md")
    verifier = _read("tools/verify_lua_spells.py")
    native_test = _read("tests/native/lua_content_registry_tests.cpp")

    assert "RegisterLuaSpellBindings(mod->state)" in root_bindings
    assert "lua_engine_bindings_spells.cpp" in project
    for capability in (
        '"spells.register"',
        '"spells.read"',
        '"spells.cast.owner"',
        '"spells.effects.read"',
        '"spells.select.local"',
    ):
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
        "struct LuaSpellEffectInstance",
        "std::vector<LuaSpellEffectInstance> spell_effects",
    ):
        assert token in internal, f"spell lifecycle lacks: {token}"
    assert "mod->spell_definitions.clear();" in engine

    for token in (
        'RegisterFunction(state, &LuaSpellsRegister, "register")',
        'RegisterFunction(state, &LuaSpellsGet, "get")',
        'RegisterFunction(state, &LuaSpellsList, "list")',
        'RegisterFunction(state, &LuaSpellsSelect, "select")',
        'RegisterFunction(state, &LuaSpellsClearSelection, "clear_selection")',
        'RegisterFunction(state, &LuaSpellsGetSelection, "get_selection")',
        'RegisterFunction(state, &LuaSpellsCast, "cast")',
        'RegisterFunction(state, &LuaSpellsGetEffects, "get_effects")',
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
        '"spells.cast.owner"',
    ):
        assert token in manifest, f"spell sample manifest lacks: {token}"
    for token in (
        'key = "gravity_well"',
        'slot = "secondary"',
        "on_cast = function",
        "on_tick = function",
        "on_hit = function",
        'key = "gravity_well_field"',
        "lifetime_ms = context.cfg.duration_ms",
        "8348995147374483494",
    ):
        assert token in sample, f"spell sample lacks: {token}"
    assert "8348995147374483494ull" in native_test

    for token in (
        "shared `sd.content.v1` identity",
        "copied into the loader's bounded Lua value representation",
        "no Lua registry index",
        "Owner-routed casting",
        "Protocol 79",
        "once for that actor",
        "generic content-ID-based effect snapshot channel",
        "four effects per fragment",
        "retirement snapshot removes",
        "callbacks continue to run only",
        "simulation owner; remote peers",
        "Local selection and native input",
        "never writes stock unlock bytes",
        "native player mana writer",
        "does not yet render a player-facing catalog chooser",
    ):
        assert token in documentation, f"spell documentation lacks: {token}"
    for token in (
        "0x004F8480",
        "0x004F90C0",
        "0x00B3BDD8..0x00B3BDDF",
        "acquisition dialog, not a runtime loadout picker",
    ):
        assert token in picker_documentation, (
            f"native spell-picker boundary lacks: {token}"
        )
    for token in (
        "QueueLuaRegisteredSpellCastRequest",
        "kLuaRegisteredSpellMaximumRememberedCasts = 1024",
        "CreateLuaSpellEffectsFromCallbackResult",
        "lua_pcall(state, 1, 1, 0)",
    ):
        assert token in casts, f"Lua spell cast dispatch lacks: {token}"
    for token in (
        "kMaximumEffectsPerCast = 16",
        "kMaximumEffectsPerMod = 128",
        "kMaximumEffectsAcrossRuntime = 256",
        "kMaximumReplicatedEffectDataBytes = 128",
        "TickLuaRegisteredSpellEffects",
        "on_tick_reference",
        "on_hit_reference",
        "hit_actor_addresses.find",
        "SnapshotLocalLuaRegisteredSpellEffects",
    ):
        assert token in effects, f"Lua spell effect lifecycle lacks: {token}"
    for token in (
        "struct RegisteredSpellInputSelectionState",
        "kLuaRegisteredSpellSecondaryInputSlotCount",
        "SelectLuaRegisteredSpellForInput",
        "ClearLuaRegisteredSpellInputSelection",
        "ClearLuaRegisteredSpellInputSelectionsForMod",
        "TryGetSelectedLuaRegisteredPrimarySpell",
        "TryGetSelectedLuaRegisteredSecondarySpell",
        "TryGetLuaRegisteredSpellInputCooldownRemaining",
        "CommitLuaRegisteredSpellInputCast",
        'ReadConfigNumber(definition.config, "mana_cost", 0.0)',
        'ReadConfigNumber(definition.config, "cooldown_ms", 0.0)',
    ):
        assert token in selection, f"Lua spell input selection lacks: {token}"
    for token in (
        "TryDispatchSelectedLuaRegisteredPrimarySpell",
        "TryDispatchSelectedLuaRegisteredSecondarySpell",
        "TrySpendLocalRegisteredSpellMana",
        "QueueOwnerRoutedLuaRegisteredSpellCast",
        "CommitLuaRegisteredSpellInputCast",
        "GetLocalRunEnemyNetworkActorId",
    ):
        assert token in player_cast_hooks, (
            f"Lua spell native input routing lacks: {token}"
        )
    assert "TryDispatchSelectedLuaRegisteredSecondaryBeltInput" in input_hooks
    assert "lua_engine_registered_spell_selection.cpp" in project
    for token in (
        "QueueOwnerRoutedLuaRegisteredSpellCastInternal",
        "SendQueuedLuaRegisteredSpellCasts",
        "ApplyLuaRegisteredSpellCastPacket",
        "IsConfiguredRemoteAuthorityEndpoint(from)",
        "received_lua_registered_spell_cast_request_ids",
    ):
        assert token in transport, f"Lua spell owner routing lacks: {token}"
    for token in (
        "SendLuaRegisteredSpellEffectSnapshots",
        "SendLuaRegisteredSpellEffectSnapshotForOwner",
        "ValidateLuaRegisteredSpellEffectSnapshotEnvelope",
        "ApplyLuaRegisteredSpellEffectSnapshotPacket",
        "RelayPacketBufferToPeers",
        "pending_lua_registered_spell_effect_snapshots",
        "completed_lua_registered_spell_effect_snapshots",
        "SnapshotLocalLuaRegisteredSpellEffects",
        "local_lua_registered_spell_effect_snapshot_owners",
        "BandwidthLimitedSnapshotIntervalMs",
        "kLuaRegisteredSpellEffectSnapshotBudgetBytesPerSecond",
        "const auto completed_it",
        "std::set<std::pair<std::uint64_t, std::uint64_t>> effect_ids",
    ):
        assert token in effect_transport, (
            f"Lua spell effect replication lacks: {token}"
        )
    _require_in_order(
        effect_transport,
        "const auto completed_it",
        "assembly.received_fragments[packet.fragment_index] = 1",
        "RelayPacketBufferToPeers",
    )
    for token in (
        "constexpr std::uint16_t kProtocolVersion = 79;",
        "LuaRegisteredSpellCast = 23",
        "struct LuaRegisteredSpellCastPacket",
        "static_assert(sizeof(LuaRegisteredSpellCastPacket) == 76",
        "LuaRegisteredSpellEffectSnapshot = 24",
        "kLuaRegisteredSpellEffectMaxLogicalEffects = 256",
        "kLuaRegisteredSpellEffectStatesPerFragment = 4",
        "struct LuaRegisteredSpellEffectPacketState",
        "struct LuaRegisteredSpellEffectSnapshotPacket",
        "static_assert(sizeof(LuaRegisteredSpellEffectPacketState) == 248",
        "kLuaRegisteredSpellEffectSnapshotPacketPrefixBytes == 44",
        "sizeof(LuaRegisteredSpellEffectSnapshotPacket) == 1036",
    ):
        assert token in protocol, f"Lua spell protocol lacks: {token}"
    assert "ApplyLuaRegisteredSpellCastPacket(packet, from, now_ms)" in dispatch
    assert "ApplyLuaRegisteredSpellEffectSnapshotPacket(" in dispatch
    assert (
        "**Spell catalog, input selection, owner runtime, and generic effect replication implemented\n"
        "2026-07-22.**" in roadmap
    )
    for token in (
        "sd.spells.list",
        "sd.spells.get(expected_id)",
        'sd.runtime.has_capability("spells.effects.read")',
        "sd.spells.get_effects()",
        "effect_snapshot_schema_valid",
        "descriptor_copy_isolated",
        "raw_internals_absent",
        "late_registration_rejected",
        "selection_round_trip",
    ):
        assert token in verifier, f"spell verifier lacks: {token}"

    return (
        "sd.spells owner-routes deterministic casts, runs bounded owner-side "
        "callbacks, and replicates generic effect snapshots without exposing "
        "native IDs, addresses, or functions"
    )
