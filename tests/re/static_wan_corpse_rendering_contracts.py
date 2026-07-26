"""WAN-ordering contracts for death, corpse, and run-loading presentation."""

from __future__ import annotations

from static_multiplayer_contract_support import (
    _read,
    _require_in_order,
    read_source_unit,
)


def test_wan_death_presentation_is_a_convergent_transaction() -> str:
    binding = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/"
        "participant_entity_state.inl"
    )
    remote_vitals = read_source_unit(
        "SolomonDarkModLoader/src/mod_loader_gameplay/bot_movement/"
        "native_remote_vitals_and_playback.inl"
    )
    remote_playback = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/bot_movement/"
        "native_remote_playback.inl"
    )
    calls = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/bot_actor_calls/"
        "actor_world_and_visual_calls.inl"
    )
    lifecycle = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "bot_registry_and_movement_participant_lifecycle.inl"
    )

    assert "native_remote_death_drop_spawned" in binding
    assert "native_remote_death_drop_spawned = false" in remote_vitals
    assert "native_remote_death_drop_spawned = true" in remote_vitals
    assert (
        "!binding->native_remote_death_epoch_active &&\n"
        "        !presentation_committed"
    ) in remote_vitals
    assert (
        "presentation_active ||\n"
        "        participant.runtime.death_presentation_tick != 0"
    ) in remote_vitals
    assert "kNativeDeathPresentationTerminalCorpseTick" in remote_vitals

    _require_in_order(
        remote_vitals,
        "ApplyNativeRemoteParticipantCorpsePresentationState(",
        "TrySpawnNativeRemoteParticipantDeathDrop(",
        "ResolveParticipantDeathPresentationStorageTick(",
        "ReconcileNativeRemoteParticipantEquipmentLane(",
    )
    for token in (
        "ApplyNativeRemoteParticipantProfileRenderSelectors(",
        "ApplyNativeRemoteParticipantEquipmentState(",
        "reconcile_attachment",
    ):
        assert token in remote_playback

    for token in (
        "CallAnimationBouncerVisualResolverSafe(",
        "CallWorldAnimationLaneInsertSafe(",
        "CallAnimationBouncerPostInsertSafe(",
    ):
        assert token in calls

    reset_start = lifecycle.index(
        "void ResetParticipantEntityMaterializationState("
    )
    reset_end = lifecycle.index(
        "void MarkParticipantEntityWorldUnregistered(",
        reset_start,
    )
    assert "native_remote_death_drop_spawned" not in lifecycle[
        reset_start:reset_end
    ]

    return (
        "a committed authoritative death converges after late "
        "materialization, reapplies corpse-safe visuals, and creates one "
        "stock dropped-equipment bouncer"
    )


def test_dead_owner_vitals_are_reasserted_after_the_progression_tick() -> str:
    spectator = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "death_spectator_sync.inl"
    )
    transport = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "public_cast_loot_api.inl"
    )
    config = _read("config/binary-layout.ini")

    assert "player_progression_tick=0x006614D0" in config
    hook_start = spectator.index(
        "void __fastcall HookLocalDeathProgressionTick("
    )
    hook_end = spectator.index(
        "bool InitializeLocalDeathProgressionTickHook(",
        hook_start,
    )
    hook = spectator[hook_start:hook_end]
    _require_in_order(
        hook,
        "original(self);",
        "player.progression_address ==",
        "HoldLocalSpectatorDeathVitals();",
    )
    assert transport.count(
        "InitializeLocalDeathProgressionTickHook("
    ) == 2
    assert "ShutdownLocalDeathProgressionTickHook();" in transport

    return (
        "the multiplayer zero-life invariant is restored after native passive "
        "regeneration on every dead-owner progression tick"
    )


def test_committed_remote_corpses_use_the_stock_local_corpse_light_branch() -> str:
    config = _read("config/binary-layout.ini")
    hooks = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "dispatch_and_hooks_actor_lifecycle_hooks.inl"
    )
    initialization = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "public_api_keyboard_injection.inl"
    )

    assert "player_actor_light_submit=0x005299A0" in config
    hook_start = hooks.index(
        "void __fastcall HookPlayerActorLightSubmit("
    )
    hook_end = hooks.index(
        "bool IsLocalPlayerActorDestructorTarget(",
        hook_start,
    )
    hook = hooks[hook_start:hook_end]
    _require_in_order(
        hook,
        "FindParticipantEntityForActor(actor_address)",
        "IsNativeRemoteParticipantBinding(binding)",
        "binding->native_remote_death_epoch_active",
        "ScopedActorSlotZeroContext slot_context(",
        "original(self);",
    )
    assert "kActorLighting" not in hook
    assert "TryWriteField<float>" not in hook
    assert "InstallSafeX86Hook(" in initialization
    assert "&HookPlayerActorLightSubmit" in initialization
    assert (
        "RemoveX86Hook("
        "&g_gameplay_keyboard_injection.player_actor_light_submit_hook)"
        in initialization.replace("\n", "")
    )

    return (
        "only a committed native remote corpse temporarily takes the stock "
        "slot-zero PlayerActor light path, with its gameplay slot restored "
        "by the scoped context"
    )


def test_authoritative_life_correction_uses_the_recipient_native_maximum() -> str:
    correction = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "participant_vitals_correction.inl"
    )

    assert "authoritative_life" in correction
    assert "(std::min)(packet.life_current, player_state.max_hp)" in correction
    assert (
        "std::fabs(player_state.max_hp - packet.life_max)"
        not in correction
    )
    assert (
        "TryWriteLocalPlayerOrbResource(\n"
        "        static_cast<std::int32_t>(LootOrbResourceKind::Health),\n"
        "        corrected_life,\n"
        "        player_state.max_hp,"
    ) in correction

    return (
        "an authenticated host correction owns current life while the "
        "recipient's current native maximum owns clamping and the write"
    )


def test_loading_boneyard_floor_starts_on_the_first_rendered_frame() -> str:
    header = _read("SolomonDarkModLoader/include/multiplayer_join_flow.h")
    flow = read_source_unit(
        "SolomonDarkModLoader/src/multiplayer_join_flow.cpp"
    )
    state_machine = _read(
        "SolomonDarkModLoader/src/multiplayer_join_flow/"
        "tick_state_machine.inl"
    )
    renderer = _read(
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "label_resolution_surface_registry_and_frame_render.inl"
    )

    notify = "NotifyMultiplayerJoinFlowPresentationRendered"
    assert notify in header
    assert "loading_presentation_first_rendered_ms" in flow
    assert notify in flow
    assert notify in renderer
    loading_start = state_machine.index(
        "case JoinFlowPhase::LoadingBoneyard:"
    )
    run_start = state_machine.index(
        "case JoinFlowPhase::Run:",
        loading_start,
    )
    loading = state_machine[loading_start:run_start]
    assert "loading_presentation_first_rendered_ms == 0" in loading
    assert (
        "loading_presentation_first_rendered_ms +\n"
        "                kTransitionPresentationMinimumMs"
    ) in loading
    assert "phase_entered_ms" not in loading

    return (
        "Loading Boneyard cannot release before one real overlay frame plus "
        "the 750 ms readability floor"
    )
