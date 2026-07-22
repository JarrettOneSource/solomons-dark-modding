"""Contracts for synchronous owner-side Lua spell-cast filters."""

from __future__ import annotations

from static_multiplayer_contract_support import _read, _require_in_order


def test_lua_spell_filter_is_owner_side_precast_and_once_per_attempt() -> str:
    public_api = _read("SolomonDarkModLoader/include/lua_event_filters.h")
    filters = _read("SolomonDarkModLoader/src/lua_engine_spell_cast_filters.cpp")
    registration = _read("SolomonDarkModLoader/src/lua_engine_filters.cpp")
    player_hooks = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "player_cast_hooks.inl"
    )
    dispatcher_hook = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "player_cast_hooks_effect_and_dispatch.inl"
    )
    hook_installation = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "public_api_keyboard_injection.inl"
    )
    bot_prepare = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/"
        "pending_cast_preparation.inl"
    )
    bot_start = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/"
        "new_request_startup.inl"
    )
    bot_filter_helpers = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/lua_spell_cast_filter.inl"
    )
    participant_state = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/"
        "participant_entity_state.inl"
    )
    actor_tick = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/actor_tick/"
        "player_actor_tick_hook.inl"
    )
    project = _read("SolomonDarkModLoader/SolomonDarkModLoader.vcxproj")
    documentation = _read("docs/lua-spell-cast-filter.md")
    sample_manifest = _read("mods/lua_spell_cast_filter_lab/manifest.json")
    sample = _read("mods/lua_spell_cast_filter_lab/scripts/main.lua")
    live_verifier = _read("tools/verify_lua_spell_cast_filters.py")

    for token in (
        "kLuaSpellCastingFilterMask",
        "enum class LuaSpellCastKind",
        "struct LuaSpellCastFilterContext",
        "caster_participant_id",
        "bool ApplyLuaSpellCastFilters(const LuaSpellCastFilterContext& context);",
    ):
        assert token in public_api, f"public spell-filter contract lacks: {token}"

    for token in (
        'kSpellCastingFilterName[] = "spell.casting"',
        '"primary" : "secondary"',
        '"caster_participant_id"',
        '"skill_id"',
        '"secondary_slot"',
        "for (const auto& mod : detail::LoadedLuaModsStorage())",
        "std::try_to_lock",
        "handler must return nil, a boolean, or a table",
        "filter result ignored",
    ):
        assert token in filters, f"spell-filter runtime lacks: {token}"
    assert 'filter_name == "spell.casting"' in registration

    for token in (
        "LocalPrimarySpellFilterState",
        "GetGameplayMouseLeftEdgeSerial()",
        "GetGameplayMouseLeftEdgeTickMs()",
        "previous.allowed",
        "TryResolveLocalPlayerPrimarySpellFilterSkillId",
        "kGameplayIndexStateActorSelectionBaseIndex",
        "TryResolveNativePrimarySelectionFromLiveProgression",
        "g_remote_secondary_spell_dispatch_depth == 0",
    ):
        assert token in player_hooks, f"player cast identity gate lacks: {token}"
    spell_dispatcher = dispatcher_hook.split(
        "void __fastcall HookSpellCastDispatcher", 1
    )[1].split("void __fastcall HookSpellActionBuilder", 1)[0]
    pure_primary_gate = dispatcher_hook.split(
        "void __fastcall HookPlayerActorPurePrimaryGate", 1
    )[1].split("using PlayerControlBrainUpdateFn", 1)[0]
    _require_in_order(
        spell_dispatcher,
        "TryResolveLocalPlayerPrimarySpellFilterSkillId(",
        "ApplyLocalPlayerPrimarySpellFilter(actor_address, skill_id)",
        "original(self);",
    )
    assert "ApplyLocalPlayerPrimarySpellFilter" not in pure_primary_gate
    _require_in_order(
        hook_installation,
        "player_actor_pure_primary_gate != spell_cast_dispatcher",
        "pure-primary gate hook disabled because it aliases spell_dispatcher",
        "reinterpret_cast<void*>(spell_cast_dispatcher)",
        "reinterpret_cast<void*>(&HookSpellCastDispatcher)",
    )
    _require_in_order(
        player_hooks,
        "ApplyLuaSpellCastFilters(filter_context)",
        "native_result = original(self, skill_entry_index);",
    )

    for source in (bot_prepare, bot_start):
        _require_in_order(
            source,
            "!IsNativeRemoteParticipantBinding(binding)",
            "ApplyLuaSpellCastFilters(filter_context)",
            "RetireCanceledOwnerBotSpellCast(binding)",
            "kActorPrimarySkillIdOffset",
        )

    for token in (
        "void RetireCanceledOwnerBotSpellCast(ParticipantEntityBinding* binding)",
        "multiplayer::FinishBotAttack(",
        "multiplayer::FaceBotTarget(binding->bot_id, 0, false, 0.0f)",
        "binding->facing_heading_valid = false",
        "kActorPrimarySkillIdOffset",
        "kActorPreviousSkillIdOffset",
        "kActorPrimaryActionLatchE4Offset",
        "kActorPrimaryActionLatchE8Offset",
        "kActorPostGateActiveByteOffset",
        "kActorSpellTargetGroupByteOffset",
        "kActorSpellTargetSlotShortOffset",
        "IsUsableSpellCastAimTarget",
        "ResetStandaloneWizardControlBrain(actor_address)",
        "suppress_next_stock_tick_after_spell_filter_cancel = true",
    ):
        assert token in bot_filter_helpers, f"bot cast retirement lacks: {token}"
    assert "suppress_next_stock_tick_after_spell_filter_cancel" in participant_state
    _require_in_order(
        actor_tick,
        "if (binding->suppress_next_stock_tick_after_spell_filter_cancel)",
        "binding->suppress_next_stock_tick_after_spell_filter_cancel = false",
        "return;",
        "const bool native_remote_binding",
    )
    local_stock_tick = actor_tick.split(
        "    if (local_player_actor) {\n"
        "        MaybeLogLocalPlayerCastProbe(gameplay_address_for_pump, actor_address, false);",
        1,
    )[1].split("    } else {", 1)[0]
    _require_in_order(
        local_stock_tick,
        "HasLuaSpellCastFilterHandlers()",
        "TryResolveLocalPlayerPrimarySpellFilterSkillId(",
        "!ApplyLocalPlayerPrimarySpellFilter(actor_address, skill_id)",
        "kGameplayCastIntentOffset",
        "live_mouse_left_offset",
        "original(self);",
        "if (cast_intent_masked)",
        "if (mouse_left_masked)",
    )

    assert "lua_engine_spell_cast_filters.cpp" in project
    for token in (
        "## Payload",
        "## Handler results",
        "## Cast identity and native behavior",
        "## Multiplayer ownership",
        "Native remote replay is explicitly excluded",
        "events.filters.spell_cast",
    ):
        assert token in documentation, f"spell-filter documentation lacks: {token}"
    assert '"enabled": false' in sample_manifest
    assert '"events.filters.spell_cast"' in sample_manifest
    assert 'sd.events.filter("spell.casting"' in sample
    assert "return false" in sample
    for token in (
        "cancel_settle",
        "local_acceptance = _run_local_acceptance(",
        '"local": local_acceptance',
        '"primary_latch_e4": "0"',
        '"target_slot": "65535"',
        "native_mana_decreased",
        "native_fireball_observed",
    ):
        assert token in live_verifier, f"spell-filter live verifier lacks: {token}"

    return (
        "spell filters execute once before owner-side native primary and secondary "
        "casts, retire canceled bot requests before their stock tick, and exclude "
        "native remote replay"
    )
