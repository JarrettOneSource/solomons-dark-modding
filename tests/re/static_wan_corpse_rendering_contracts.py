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


def test_driven_remote_players_use_the_stock_light_branch_skipped_by_their_slot() -> str:
    config = _read("config/binary-layout.ini")
    remote_vitals = read_source_unit(
        "SolomonDarkModLoader/src/mod_loader_gameplay/bot_movement/"
        "native_remote_vitals_and_playback.inl"
    )
    hooks = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "dispatch_and_hooks_actor_lifecycle_hooks.inl"
    )
    initialization = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "public_api_keyboard_injection.inl"
    )
    scene_tick = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "bot_movement_tick/participant_scene_binding_ticks.inl"
    )

    assert "player_actor_light_submit=0x005299A0" in config
    assert "arena_light_collection_finalize=0x0057D5E0" in config
    submit_start = remote_vitals.index(
        "bool SubmitMissingNativeRemoteParticipantLight("
    )
    submit_end = remote_vitals.index(
        "bool ApplyNativeRemoteParticipantDeathPresentationState(",
        submit_start,
    )
    submit = remote_vitals[submit_start:submit_end]
    _require_in_order(
        submit,
        "IsPacketDrivenRemoteParticipantBinding(binding)",
        "kActorAnimationDriveStateByteOffset",
        "actor_slot <= 0",
        "animation_drive_state == 0",
        "ScopedActorSlotZeroContext slot_context(",
        "CallPlayerActorLightSubmitSafe(",
        "slot_context.Restore();",
    )
    assert "kActorLighting" not in submit
    assert "TryWriteField<float>" not in submit
    assert (
        "void SubmitMissingNativeRemoteParticipantLightsForCurrentFrame()"
        in remote_vitals
    )
    assert "SubmitMissingNativeRemoteParticipantLight(" not in scene_tick

    hook_start = hooks.index(
        "void __cdecl HookArenaLightCollectionFinalize()"
    )
    hook_end = hooks.index(
        "bool IsLocalPlayerActorDestructorTarget(",
        hook_start,
    )
    hook = hooks[hook_start:hook_end]
    _require_in_order(
        hook,
        "SubmitMissingNativeRemoteParticipantLightsForCurrentFrame();",
        "original();",
    )
    assert "&HookArenaLightCollectionFinalize" in initialization
    assert (
        "RemoveX86Hook("
        "&g_gameplay_keyboard_injection"
        ".arena_light_collection_finalize_hook)"
        in initialization.replace("\n", "").replace(" ", "")
    )

    return (
        "the arena pre-finalize seam submits each driven native remote player "
        "after the per-frame light reset through the stock slot-zero PlayerActor "
        "path, with idle native-lit actors untouched and gameplay slots restored"
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
