bool IsParticipantPacketFromTerminatedRun(
    std::uint32_t run_nonce) {
    return run_nonce != 0 &&
           run_nonce ==
               g_local_terminated_run_nonce.load(
                   std::memory_order_acquire);
}

template <typename Packet>
bool IsAuthenticatedFreshRunEntryPacket(
    const Packet& packet,
    const ParticipantSceneIntent& scene_intent,
    bool packet_from_configured_authority) {
    return packet_from_configured_authority &&
           packet.ready != 0 &&
           packet.in_run != 0 &&
           packet.run_nonce != 0 &&
           scene_intent.kind ==
               ParticipantSceneIntentKind::Run &&
           packet.run_loading_expected_participant_count !=
               0 &&
           packet.run_loading_expected_participant_set_hash !=
               0 &&
           packet.run_loading_deadline_remaining_ms != 0;
}

void RetireParticipantRunTerminationFenceForNewRun(
    std::uint32_t run_nonce,
    std::string_view source) {
    auto expected = run_nonce;
    if (run_nonce == 0 ||
        !g_local_terminated_run_nonce.compare_exchange_strong(
            expected,
            0,
            std::memory_order_acq_rel)) {
        return;
    }
    Log(
        "Multiplayer retired participant run-termination "
        "fence for authenticated new-run entry. "
        "run_nonce=" + std::to_string(run_nonce) +
        " source=" + std::string(source));
}

template <typename Packet>
bool IsHealthyPostTerminationParticipantFrame(
    const Packet& packet) {
    const auto is_full = [](
        float current,
        float maximum) {
        if (!std::isfinite(current) ||
            !std::isfinite(maximum) ||
            maximum <= 0.0f) {
            return false;
        }
        const auto tolerance =
            (std::max)(0.05f, maximum * 0.001f);
        return std::abs(current - maximum) <=
            tolerance;
    };
    const auto shield_zero = [](
        float value) {
        return std::isfinite(value) &&
               std::abs(value) <= 0.0001f;
    };
    return packet.in_run == 0 &&
           is_full(
               packet.life_current,
               packet.life_max) &&
           is_full(
               packet.mana_current,
               packet.mana_max) &&
           packet.anim_drive_state == 0 &&
           (packet.persistent_status_flags &
            kParticipantPersistentStatusValueMask) == 0 &&
           (packet.transient_status_flags &
            kParticipantTransientStatusValueMask) == 0 &&
           packet.poison_remaining_ticks == 0 &&
           packet.damage_x4_remaining_ticks == 0 &&
           (packet.presentation_flags &
            ParticipantPresentationFlagDeathPresentation) == 0 &&
           packet.death_presentation_tick == 0 &&
           shield_zero(
               packet.magic_shield_absorb_remaining) &&
           shield_zero(
               packet.magic_shield_absorb_capacity) &&
           shield_zero(
               packet.magic_shield_explosion_fraction) &&
           shield_zero(
               packet.magic_shield_hit_flash);
}

void ResetParticipantRuntimeForRunTermination(
    ParticipantInfo* participant_info) {
    if (participant_info == nullptr) {
        return;
    }

    auto& participant = *participant_info;
    auto& runtime = participant.runtime;
    runtime.in_run = false;
    runtime.transform_valid = false;
    runtime.scene_intent = DefaultParticipantSceneIntent();
    runtime.wave = 0;
    if (std::isfinite(runtime.life_max) &&
        runtime.life_max > 0.0f) {
        participant.runtime.life_current =
            participant.runtime.life_max;
    }
    if (std::isfinite(runtime.mana_max) &&
        runtime.mana_max > 0.0f) {
        runtime.mana_current = runtime.mana_max;
    }
    runtime.movement_intent_x = 0.0f;
    runtime.movement_intent_y = 0.0f;
    runtime.anim_drive_state = 0;
    runtime.persistent_status_flags &=
        ParticipantPersistentStatusFlagSnapshotValid;
    runtime.transient_status_flags &=
        ParticipantTransientStatusFlagSnapshotValid;
    runtime.poison_remaining_ticks = 0;
    runtime.damage_x4_remaining_ticks = 0;
    runtime.presentation_flags &=
        ~ParticipantPresentationFlagDeathPresentation;
    runtime.death_presentation_tick = 0;
    runtime.anim_drive_state_word = 0;
    runtime.walk_cycle_primary = 0.0f;
    runtime.walk_cycle_secondary = 0.0f;
    runtime.render_drive_stride = 0.0f;
    runtime.render_advance_rate = 0.0f;
    runtime.render_advance_phase = 0.0f;
    runtime.magic_shield_absorb_remaining = 0.0f;
    runtime.magic_shield_absorb_capacity = 0.0f;
    runtime.magic_shield_explosion_fraction = 0.0f;
    runtime.magic_shield_hit_flash = 0.0f;
    runtime.render_drive_overlay_alpha = 0.0f;
    runtime.render_drive_move_blend = 0.0f;
    participant.transform_history.clear();
}

void ResetParticipantCombatTransportStateForRunTermination() {
    {
        std::lock_guard<std::mutex> lock(
            g_local_transport_event_mutex);
        g_queued_local_cast_events.clear();
        g_queued_local_enemy_damage_claims.clear();
        g_queued_host_participant_vitals_corrections.clear();
        g_queued_local_air_chain_frame =
            QueuedLocalAirChainFrame{};
        g_have_queued_local_air_chain_frame = false;
    }

    g_local_transport
        .last_participant_vitals_correction_sequence_by_authority
        .clear();
    g_local_transport
        .pending_participant_vitals_corrections_by_participant
        .clear();
    g_local_transport
        .last_participant_vitals_correction_send_ms_by_participant
        .clear();
    g_local_transport
        .last_applied_participant_vitals_correction_sequence = 0;
    g_local_transport.active_local_cast_input =
        ActiveLocalCastInput{};
    g_local_transport.remote_cast_inputs_by_participant.clear();
    g_local_transport.local_spell_effects_by_address.clear();
    g_local_transport.local_spell_effect_tombstones.clear();
    g_local_transport
        .next_spell_effect_ordinal_by_cast_type.clear();
    g_local_transport.pending_air_chain_terminals.clear();
    g_local_transport.recent_local_cast_sequence = 0;
    g_local_transport.recent_local_cast_skill_id = -1;
    g_local_transport.recent_local_cast_ms = 0;
    g_local_transport
        .recent_local_cast_target_network_actor_id = 0;
    g_local_transport
        .recent_local_air_chain_target_until_ms.clear();
    g_local_transport.last_local_explode_splash_cast_sequence =
        0;
    g_local_transport.host_local_explode_cast_baseline = {};
    ResetAirChainRuntimeState();
}
