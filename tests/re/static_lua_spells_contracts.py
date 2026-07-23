"""Contracts for deterministic bounded Lua spell registration."""

from __future__ import annotations

from static_multiplayer_contract_support import _read, _require_in_order


def test_lua_spells_register_stable_metadata_and_owned_callbacks() -> str:
    bindings = _read("SolomonDarkModLoader/src/lua_engine_bindings_spells.cpp")
    root_bindings = _read("SolomonDarkModLoader/src/lua_engine_bindings.cpp")
    engine = _read("SolomonDarkModLoader/src/lua_engine.cpp")
    internal = _read("SolomonDarkModLoader/src/lua_engine_internal.h")
    casts = _read("SolomonDarkModLoader/src/lua_engine_registered_spell_casts.cpp")
    effects = _read("SolomonDarkModLoader/src/lua_engine_registered_spell_effects.cpp")
    transport = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "lua_registered_spell_cast_sync.inl"
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
    roadmap = _read("docs/lua-seam-roadmap.md")
    verifier = _read("tools/verify_lua_spells.py")
    native_test = _read("tests/native/lua_content_registry_tests.cpp")

    assert "RegisterLuaSpellBindings(mod->state)" in root_bindings
    assert "lua_engine_bindings_spells.cpp" in project
    for capability in (
        '"spells.register"',
        '"spells.read"',
        '"spells.cast.owner"',
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
        'RegisterFunction(state, &LuaSpellsCast, "cast")',
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
        "Protocol 77",
        "once for that actor",
        "generic content-ID-based effect snapshot channel",
    ):
        assert token in documentation, f"spell documentation lacks: {token}"
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
        "kMaximumReplicatedEffectDataBytes = 128",
        "TickLuaRegisteredSpellEffects",
        "on_tick_reference",
        "on_hit_reference",
        "hit_actor_addresses.find",
        "SnapshotLocalLuaRegisteredSpellEffects",
    ):
        assert token in effects, f"Lua spell effect lifecycle lacks: {token}"
    for token in (
        "QueueOwnerRoutedLuaRegisteredSpellCastInternal",
        "SendQueuedLuaRegisteredSpellCasts",
        "ApplyLuaRegisteredSpellCastPacket",
        "IsConfiguredRemoteAuthorityEndpoint(from)",
        "received_lua_registered_spell_cast_request_ids",
    ):
        assert token in transport, f"Lua spell owner routing lacks: {token}"
    for token in (
        "constexpr std::uint16_t kProtocolVersion = 77;",
        "LuaRegisteredSpellCast = 23",
        "struct LuaRegisteredSpellCastPacket",
        "static_assert(sizeof(LuaRegisteredSpellCastPacket) == 76",
    ):
        assert token in protocol, f"Lua spell protocol lacks: {token}"
    assert "ApplyLuaRegisteredSpellCastPacket(packet, from, now_ms)" in dispatch
    assert "**Spell catalog and owner runtime implemented 2026-07-22.**" in roadmap
    for token in (
        "sd.spells.list",
        "sd.spells.get(expected_id)",
        "descriptor_copy_isolated",
        "raw_internals_absent",
        "late_registration_rejected",
    ):
        assert token in verifier, f"spell verifier lacks: {token}"

    return (
        "sd.spells owner-routes deterministic casts and runs bounded owner-side "
        "effect callbacks without exposing native IDs, addresses, or functions"
    )
