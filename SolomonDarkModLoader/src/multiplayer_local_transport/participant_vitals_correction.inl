void ApplyParticipantVitalsCorrectionPacket(
    const ParticipantVitalsCorrectionPacket& packet,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    const auto allowed_transient_flags = static_cast<std::uint8_t>(
        ParticipantTransientStatusFlagPoisoned |
        ParticipantTransientStatusFlagWebbed |
        ParticipantTransientStatusFlagSnapshotValid);
    const bool transient_snapshot_valid =
        (packet.transient_status_flags &
         ParticipantTransientStatusFlagSnapshotValid) != 0;
    const bool poison_active =
        (packet.transient_status_flags &
         ParticipantTransientStatusFlagPoisoned) != 0;
    const bool poison_payload_valid = poison_active
        ? packet.poison_remaining_ticks > 0 &&
              packet.poison_remaining_ticks <=
                  kParticipantPoisonMaxDurationTicks &&
              std::isfinite(packet.poison_damage_per_tick) &&
              packet.poison_damage_per_tick >= 0.0f &&
              packet.poison_damage_per_tick <= 10000.0f
        : packet.poison_remaining_ticks == 0 &&
              packet.poison_damage_per_tick == 0.0f;
    const bool webbed_active =
        (packet.transient_status_flags &
         ParticipantTransientStatusFlagWebbed) != 0;
    const bool webbed_payload_valid = webbed_active
        ? packet.webbed_remaining_ticks > 0 &&
              packet.webbed_remaining_ticks <=
                  kParticipantWebbedMaxDurationTicks &&
              std::isfinite(packet.webbed_strength) &&
              packet.webbed_strength > 0.0f &&
              packet.webbed_strength <= kParticipantWebbedMaxStrength
        : packet.webbed_remaining_ticks == 0 &&
              packet.webbed_strength == 0.0f;
    const bool correction_magic_shield =
        (packet.correction_flags &
         ParticipantVitalsCorrectionFlagMagicShieldState) != 0;
    const bool magic_shield_payload_zero =
        packet.magic_shield_absorb_remaining == 0.0f &&
        packet.magic_shield_absorb_capacity == 0.0f &&
        packet.magic_shield_explosion_fraction == 0.0f &&
        packet.magic_shield_hit_flash == 0.0f;
    const bool magic_shield_payload_active =
        std::isfinite(packet.magic_shield_absorb_remaining) &&
        std::isfinite(packet.magic_shield_absorb_capacity) &&
        std::isfinite(packet.magic_shield_explosion_fraction) &&
        std::isfinite(packet.magic_shield_hit_flash) &&
        packet.magic_shield_absorb_remaining > kMagicShieldAbsorbEpsilon &&
        packet.magic_shield_absorb_remaining <= kMagicShieldMaximumAbsorb &&
        packet.magic_shield_absorb_capacity >=
            packet.magic_shield_absorb_remaining &&
        packet.magic_shield_absorb_capacity <= kMagicShieldMaximumAbsorb &&
        packet.magic_shield_explosion_fraction >= 0.0f &&
        packet.magic_shield_explosion_fraction <=
            kMagicShieldMaximumExplosionFraction &&
        packet.magic_shield_hit_flash >= 0.0f &&
        packet.magic_shield_hit_flash <= 1.0f;
    const bool magic_shield_payload_valid = correction_magic_shield
        ? magic_shield_payload_zero || magic_shield_payload_active
        : magic_shield_payload_zero;
    const bool correction_hagatha_runtime =
        (packet.correction_flags &
         ParticipantVitalsCorrectionFlagHagathaRuntimeState) != 0;
    const bool hagatha_runtime_payload_zero =
        packet.hagatha_cheat_death_charges == 0 &&
        packet.hagatha_serendipity_active == 0 &&
        packet.hagatha_reverie_active == 0 &&
        packet.hagatha_runtime_valid == 0;
    const bool hagatha_runtime_payload_valid = correction_hagatha_runtime
        ? packet.hagatha_runtime_valid != 0 &&
              packet.hagatha_cheat_death_charges >= 0 &&
              packet.hagatha_cheat_death_charges <= 1 &&
              packet.hagatha_serendipity_active <= 1 &&
              packet.hagatha_reverie_active <= 1
        : hagatha_runtime_payload_zero;
    if (!IsLocalTransportClient() ||
        !IsConfiguredRemoteAuthorityEndpoint(from) ||
        packet.authority_participant_id == 0 ||
        packet.authority_participant_id == g_local_transport.local_peer_id ||
        packet.target_participant_id != g_local_transport.local_peer_id ||
        packet.correction_sequence == 0 ||
        !std::isfinite(packet.life_current) ||
        !std::isfinite(packet.life_max) ||
        packet.life_max <= 0.0f ||
        packet.life_current < 0.0f ||
        packet.life_current > packet.life_max ||
        !transient_snapshot_valid ||
        (packet.transient_status_flags & ~allowed_transient_flags) != 0 ||
        (packet.correction_flags &
         ~kParticipantVitalsCorrectionKnownFlags) != 0 ||
        !poison_payload_valid ||
        !webbed_payload_valid ||
        !magic_shield_payload_valid ||
        !hagatha_runtime_payload_valid) {
        return;
    }

    const auto last_it =
        g_local_transport.last_participant_vitals_correction_sequence_by_authority.find(
            packet.authority_participant_id);
    if (last_it !=
            g_local_transport.last_participant_vitals_correction_sequence_by_authority.end() &&
        !IsPacketSequenceNewer(packet.correction_sequence, last_it->second)) {
        return;
    }

    SDModPlayerState player_state;
    if (!TryGetPlayerState(&player_state) ||
        !player_state.valid ||
        !std::isfinite(player_state.hp) ||
        !std::isfinite(player_state.max_hp) ||
        player_state.max_hp <= 0.0f ||
        std::fabs(player_state.max_hp - packet.life_max) >
            (std::max)(1.0f, player_state.max_hp * 0.1f)) {
        return;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local == nullptr ||
        (packet.run_nonce != 0 &&
         local->runtime.run_nonce != 0 &&
         packet.run_nonce != local->runtime.run_nonce)) {
        return;
    }

    const bool cheat_death_consumed =
        correction_hagatha_runtime &&
        packet.hagatha_runtime_valid != 0 &&
        local->owned_progression.hagatha_perks.valid &&
        packet.hagatha_cheat_death_charges <
            local->owned_progression.hagatha_perks.cheat_death_charges;
    const float corrected_life =
        cheat_death_consumed
            ? packet.life_current
            : (std::min)(player_state.hp, packet.life_current);
    if (correction_hagatha_runtime &&
        !ApplyAuthoritativeHagathaRuntimeCorrection(
            player_state.progression_address,
            packet)) {
        return;
    }
    if (corrected_life <= 0.0f) {
        std::string death_error;
        if (!TryApplyAuthoritativeLocalPlayerDeath(
                &death_error)) {
            Log(
                "Multiplayer authoritative local death replay is pending. "
                "authority_participant_id=" +
                std::to_string(packet.authority_participant_id) +
                " target_participant_id=" +
                std::to_string(packet.target_participant_id) +
                " correction_sequence=" +
                std::to_string(packet.correction_sequence) +
                " error=" + death_error);
            return;
        }
    }
    const bool wrote = TryWriteLocalPlayerOrbResource(
        static_cast<std::int32_t>(LootOrbResourceKind::Health),
        corrected_life,
        player_state.max_hp,
        player_state.mp,
        player_state.max_mp);
    if (!wrote) {
        return;
    }

    if (poison_active || webbed_active || correction_magic_shield) {
        std::string correction_error;
        const auto correctable_status_flags = static_cast<std::uint8_t>(
            packet.transient_status_flags &
            (ParticipantTransientStatusFlagPoisoned |
             ParticipantTransientStatusFlagWebbed));
        if (!QueueLocalPlayerVitalsCorrection(
                packet.correction_sequence,
                correctable_status_flags,
                packet.poison_remaining_ticks,
                packet.poison_damage_per_tick,
                packet.webbed_remaining_ticks,
                packet.webbed_strength,
                static_cast<std::uint8_t>(
                    packet.correction_flags &
                    ParticipantVitalsCorrectionFlagMagicShieldState),
                packet.magic_shield_absorb_remaining,
                packet.magic_shield_absorb_capacity,
                packet.magic_shield_explosion_fraction,
                packet.magic_shield_hit_flash,
                &correction_error)) {
            Log(
                "Multiplayer participant native vitals correction queue failed. "
                "authority_participant_id=" +
                std::to_string(packet.authority_participant_id) +
                " target_participant_id=" +
                std::to_string(packet.target_participant_id) +
                " correction_sequence=" +
                std::to_string(packet.correction_sequence) +
                " error=" + correction_error);
            return;
        }
    }

    g_local_transport.last_participant_vitals_correction_sequence_by_authority[
        packet.authority_participant_id] = packet.correction_sequence;
    if (!poison_active && !webbed_active && !correction_magic_shield) {
        g_local_transport.last_applied_participant_vitals_correction_sequence =
            packet.correction_sequence;
    }
    UpdateRuntimeState([&](RuntimeState& state) {
        auto* mutable_local = FindLocalParticipant(state);
        if (mutable_local == nullptr) {
            return;
        }
        mutable_local->runtime.life_current = corrected_life;
        mutable_local->runtime.life_max = player_state.max_hp;
        if (poison_active || webbed_active) {
            mutable_local->runtime.transient_status_flags =
                packet.transient_status_flags;
        }
        if (poison_active) {
            mutable_local->runtime.poison_remaining_ticks =
                packet.poison_remaining_ticks;
        }
        if (correction_magic_shield) {
            mutable_local->runtime.magic_shield_absorb_remaining =
                packet.magic_shield_absorb_remaining;
            mutable_local->runtime.magic_shield_absorb_capacity =
                packet.magic_shield_absorb_capacity;
            mutable_local->runtime.magic_shield_explosion_fraction =
                packet.magic_shield_explosion_fraction;
            mutable_local->runtime.magic_shield_hit_flash =
                packet.magic_shield_hit_flash;
        }
    });
    UpsertPeerEndpoint(from, packet.authority_participant_id, now_ms);
    Log(
        "Multiplayer participant damage correction applied. authority_participant_id=" +
        std::to_string(packet.authority_participant_id) +
        " target_participant_id=" +
        std::to_string(packet.target_participant_id) +
        " correction_sequence=" +
        std::to_string(packet.correction_sequence) +
        " life=" + std::to_string(corrected_life) + "/" +
        std::to_string(player_state.max_hp) +
        " transient_flags=" +
        std::to_string(packet.transient_status_flags) +
        " poison_ticks=" +
        std::to_string(packet.poison_remaining_ticks) +
        " poison_damage=" +
        std::to_string(packet.poison_damage_per_tick) +
        " webbed_ticks=" +
        std::to_string(packet.webbed_remaining_ticks) +
        " webbed_strength=" +
        std::to_string(packet.webbed_strength) +
        " correction_flags=" +
        std::to_string(packet.correction_flags) +
        " magic_shield=" +
        std::to_string(packet.magic_shield_absorb_remaining) + "/" +
        std::to_string(packet.magic_shield_absorb_capacity));
}
