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
        "        !presentation_active"
    ) not in remote_vitals
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
        "authoritative death converges after late materialization, reapplies "
        "corpse-safe visuals, and creates one stock dropped-equipment bouncer"
    )


def test_dead_owner_vitals_are_reasserted_after_the_stock_tick() -> str:
    transport_header = _read(
        "SolomonDarkModLoader/include/multiplayer_local_transport.h"
    )
    spectator_public = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "death_spectator_public.inl"
    )
    player_tick = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "actor_tick/player_actor_tick_hook.inl"
    )

    token = "ReassertLocalDeathSpectatorVitalsAfterStockTick"
    assert token in transport_header
    assert token in spectator_public
    local_start = player_tick.index("if (local_player_actor) {")
    local_tick = player_tick.index("original(self);", local_start)
    reassert = player_tick.index(token, local_tick)
    assert local_tick < reassert

    return (
        "the multiplayer zero-life invariant is restored after native passive "
        "regeneration on every dead-owner player tick"
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
