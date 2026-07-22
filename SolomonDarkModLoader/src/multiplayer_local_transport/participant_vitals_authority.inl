constexpr std::uint64_t kParticipantVitalsCorrectionResendMs = 100;
constexpr std::uint64_t kParticipantVitalsCorrectionSendIntervalMs = 50;
constexpr float kParticipantVitalsCorrectionEpsilon = 0.05f;

void QueueHostParticipantVitalsCorrectionInternal(
    std::uint64_t target_participant_id,
    float life_current,
    float life_max,
    std::uint8_t transient_status_flags,
    std::int32_t poison_remaining_ticks,
    float poison_damage_per_tick,
    std::int32_t webbed_remaining_ticks,
    float webbed_strength,
    std::uint8_t correction_flags,
    float magic_shield_absorb_remaining,
    float magic_shield_absorb_capacity,
    float magic_shield_explosion_fraction,
    float magic_shield_hit_flash) {
    if (!g_local_transport.initialized ||
        !g_local_transport.is_host ||
        target_participant_id == 0 ||
        target_participant_id == g_local_transport.local_peer_id ||
        !std::isfinite(life_current) ||
        !std::isfinite(life_max) ||
        life_max <= 0.0f) {
        return;
    }

    QueuedHostParticipantVitalsCorrection queued;
    queued.target_participant_id = target_participant_id;
    queued.life_current = (std::clamp)(life_current, 0.0f, life_max);
    queued.life_max = life_max;
    constexpr std::uint8_t kCorrectableStatusMask =
        ParticipantTransientStatusFlagPoisoned |
        ParticipantTransientStatusFlagWebbed;
    queued.transient_status_flags = static_cast<std::uint8_t>(
        transient_status_flags & kCorrectableStatusMask);
    queued.poison_remaining_ticks =
        (queued.transient_status_flags & ParticipantTransientStatusFlagPoisoned) != 0
            ? (std::clamp)(
                  poison_remaining_ticks,
                  std::int32_t{1},
                  kParticipantPoisonMaxDurationTicks)
            : 0;
    queued.poison_damage_per_tick =
        queued.poison_remaining_ticks > 0 &&
                std::isfinite(poison_damage_per_tick) &&
                poison_damage_per_tick >= 0.0f &&
                poison_damage_per_tick <= 10000.0f
            ? poison_damage_per_tick
            : 0.0f;
    queued.webbed_remaining_ticks =
        (queued.transient_status_flags &
         ParticipantTransientStatusFlagWebbed) != 0
            ? (std::clamp)(
                  webbed_remaining_ticks,
                  std::int32_t{1},
                  kParticipantWebbedMaxDurationTicks)
            : 0;
    queued.webbed_strength =
        queued.webbed_remaining_ticks > 0 &&
                std::isfinite(webbed_strength) &&
                webbed_strength > 0.0f &&
                webbed_strength <= kParticipantWebbedMaxStrength
            ? webbed_strength
            : 0.0f;
    if ((queued.transient_status_flags &
         ParticipantTransientStatusFlagWebbed) != 0 &&
        queued.webbed_strength == 0.0f) {
        queued.transient_status_flags = static_cast<std::uint8_t>(
            queued.transient_status_flags &
            ~ParticipantTransientStatusFlagWebbed);
        queued.webbed_remaining_ticks = 0;
    }
    queued.correction_flags = static_cast<std::uint8_t>(
        correction_flags & kParticipantVitalsCorrectionKnownFlags);
    if ((queued.correction_flags &
         ParticipantVitalsCorrectionFlagMagicShieldState) != 0) {
        const auto shield_state = NormalizeMagicShieldState(
            magic_shield_absorb_remaining,
            magic_shield_absorb_capacity,
            magic_shield_explosion_fraction,
            magic_shield_hit_flash);
        queued.magic_shield_absorb_remaining = shield_state.absorb_remaining;
        queued.magic_shield_absorb_capacity = shield_state.absorb_capacity;
        queued.magic_shield_explosion_fraction =
            shield_state.explosion_fraction;
        queued.magic_shield_hit_flash = shield_state.hit_flash;
    }
    HagathaRuntimeCorrectionState hagatha_runtime;
    if (CaptureAuthoritativeHagathaRuntimeState(
            target_participant_id,
            &hagatha_runtime)) {
        queued.correction_flags |=
            ParticipantVitalsCorrectionFlagHagathaRuntimeState;
        queued.hagatha_cheat_death_charges =
            hagatha_runtime.cheat_death_charges;
        queued.hagatha_serendipity_active =
            hagatha_runtime.serendipity_active;
        queued.hagatha_reverie_active =
            hagatha_runtime.reverie_active;
        queued.hagatha_runtime_valid = true;
        if (hagatha_runtime.cheat_death_consumed &&
            hagatha_runtime.native_life_valid) {
            queued.life_current = hagatha_runtime.life_current;
            queued.life_max = hagatha_runtime.life_max;
        }
    }

    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    g_queued_host_participant_vitals_corrections.push_back(queued);
}

std::vector<QueuedHostParticipantVitalsCorrection>
TakeQueuedHostParticipantVitalsCorrections() {
    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    std::vector<QueuedHostParticipantVitalsCorrection> queued;
    queued.swap(g_queued_host_participant_vitals_corrections);
    return queued;
}

void SendQueuedHostParticipantVitalsCorrections(std::uint64_t now_ms) {
    if (!g_local_transport.is_host) {
        (void)TakeQueuedHostParticipantVitalsCorrections();
        return;
    }

    const auto queued = TakeQueuedHostParticipantVitalsCorrections();
    std::unordered_map<std::uint64_t, QueuedHostParticipantVitalsCorrection>
        strongest_by_participant;
    for (const auto& correction : queued) {
        auto [it, inserted] = strongest_by_participant.emplace(
            correction.target_participant_id,
            correction);
        if (!inserted) {
            const bool correction_hagatha_runtime =
                (correction.correction_flags &
                 ParticipantVitalsCorrectionFlagHagathaRuntimeState) != 0 &&
                correction.hagatha_runtime_valid;
            const bool accumulated_hagatha_runtime =
                (it->second.correction_flags &
                 ParticipantVitalsCorrectionFlagHagathaRuntimeState) != 0 &&
                it->second.hagatha_runtime_valid;
            const bool correction_consumed_cheat_death =
                correction_hagatha_runtime && accumulated_hagatha_runtime &&
                correction.hagatha_cheat_death_charges <
                    it->second.hagatha_cheat_death_charges;
            const bool accumulated_consumed_cheat_death =
                correction_hagatha_runtime && accumulated_hagatha_runtime &&
                it->second.hagatha_cheat_death_charges <
                    correction.hagatha_cheat_death_charges;
            if (correction_consumed_cheat_death) {
                it->second.life_current = correction.life_current;
            } else if (!accumulated_consumed_cheat_death) {
                it->second.life_current = (std::min)(
                    it->second.life_current,
                    correction.life_current);
            }
            const bool correction_poisoned =
                (correction.transient_status_flags &
                 ParticipantTransientStatusFlagPoisoned) != 0;
            if (correction_poisoned) {
                it->second.transient_status_flags |=
                    ParticipantTransientStatusFlagPoisoned;
                it->second.poison_remaining_ticks =
                    (std::max)(
                        it->second.poison_remaining_ticks,
                        correction.poison_remaining_ticks);
                it->second.poison_damage_per_tick =
                    (std::max)(
                        it->second.poison_damage_per_tick,
                        correction.poison_damage_per_tick);
            }
            const bool correction_webbed =
                (correction.transient_status_flags &
                 ParticipantTransientStatusFlagWebbed) != 0;
            if (correction_webbed) {
                it->second.transient_status_flags |=
                    ParticipantTransientStatusFlagWebbed;
                it->second.webbed_remaining_ticks =
                    (std::max)(
                        it->second.webbed_remaining_ticks,
                        correction.webbed_remaining_ticks);
                it->second.webbed_strength =
                    (std::max)(
                        it->second.webbed_strength,
                        correction.webbed_strength);
            }
            const bool correction_magic_shield =
                (correction.correction_flags &
                 ParticipantVitalsCorrectionFlagMagicShieldState) != 0;
            const bool accumulated_magic_shield =
                (it->second.correction_flags &
                 ParticipantVitalsCorrectionFlagMagicShieldState) != 0;
            if (correction_magic_shield &&
                (!accumulated_magic_shield ||
                 correction.magic_shield_absorb_remaining +
                         kParticipantVitalsCorrectionEpsilon <
                     it->second.magic_shield_absorb_remaining)) {
                it->second.correction_flags |=
                    ParticipantVitalsCorrectionFlagMagicShieldState;
                it->second.magic_shield_absorb_remaining =
                    correction.magic_shield_absorb_remaining;
                it->second.magic_shield_absorb_capacity =
                    correction.magic_shield_absorb_capacity;
                it->second.magic_shield_explosion_fraction =
                    correction.magic_shield_explosion_fraction;
                it->second.magic_shield_hit_flash =
                    correction.magic_shield_hit_flash;
            } else if (correction_magic_shield &&
                       accumulated_magic_shield) {
                it->second.magic_shield_hit_flash = (std::max)(
                    it->second.magic_shield_hit_flash,
                    correction.magic_shield_hit_flash);
            }
            if (correction_hagatha_runtime) {
                it->second.correction_flags |=
                    ParticipantVitalsCorrectionFlagHagathaRuntimeState;
                it->second.hagatha_runtime_valid = true;
                if (accumulated_hagatha_runtime) {
                    it->second.hagatha_cheat_death_charges = (std::min)(
                        it->second.hagatha_cheat_death_charges,
                        correction.hagatha_cheat_death_charges);
                    it->second.hagatha_serendipity_active =
                        it->second.hagatha_serendipity_active &&
                        correction.hagatha_serendipity_active;
                    it->second.hagatha_reverie_active =
                        it->second.hagatha_reverie_active &&
                        correction.hagatha_reverie_active;
                } else {
                    it->second.hagatha_cheat_death_charges =
                        correction.hagatha_cheat_death_charges;
                    it->second.hagatha_serendipity_active =
                        correction.hagatha_serendipity_active;
                    it->second.hagatha_reverie_active =
                        correction.hagatha_reverie_active;
                }
            }
        }
    }
    for (const auto& [target_participant_id, correction] :
         strongest_by_participant) {
        (void)target_participant_id;
        const auto runtime_state = SnapshotRuntimeState();
        const auto* participant =
            FindParticipant(runtime_state, correction.target_participant_id);
        if (participant == nullptr ||
            !IsRemoteParticipant(*participant) ||
            !participant->runtime.valid ||
            !participant->runtime.in_run ||
            (participant->runtime.life_max > 0.0f &&
             std::fabs(participant->runtime.life_max - correction.life_max) >
                 (std::max)(1.0f, participant->runtime.life_max * 0.1f))) {
            continue;
        }
        const bool pending_cheat_death_consumed =
            (correction.correction_flags &
             ParticipantVitalsCorrectionFlagHagathaRuntimeState) != 0 &&
            correction.hagatha_runtime_valid &&
            participant->owned_progression.hagatha_perks.valid &&
            correction.hagatha_cheat_death_charges <
                participant->owned_progression.hagatha_perks
                    .cheat_death_charges;

        auto pending_it =
            g_local_transport.pending_participant_vitals_corrections_by_participant.find(
                correction.target_participant_id);
        const bool poison_active =
            (correction.transient_status_flags &
             ParticipantTransientStatusFlagPoisoned) != 0;
        const bool have_stronger_correction =
            pending_it ==
                g_local_transport.pending_participant_vitals_corrections_by_participant.end() ||
            correction.life_current + kParticipantVitalsCorrectionEpsilon <
                pending_it->second.packet.life_current ||
            (poison_active &&
             (pending_it->second.packet.transient_status_flags &
              ParticipantTransientStatusFlagPoisoned) == 0) ||
            (poison_active &&
             (correction.poison_remaining_ticks >
                  pending_it->second.packet.poison_remaining_ticks ||
              correction.poison_damage_per_tick >
                  pending_it->second.packet.poison_damage_per_tick));
        const bool webbed_active =
            (correction.transient_status_flags &
             ParticipantTransientStatusFlagWebbed) != 0;
        const bool have_stronger_status_correction =
            have_stronger_correction ||
            (webbed_active &&
             ((pending_it ==
               g_local_transport
                   .pending_participant_vitals_corrections_by_participant.end()) ||
              (pending_it->second.packet.transient_status_flags &
               ParticipantTransientStatusFlagWebbed) == 0 ||
              correction.webbed_remaining_ticks >
                  pending_it->second.packet.webbed_remaining_ticks ||
                  correction.webbed_strength >
                      pending_it->second.packet.webbed_strength));
        const bool correction_magic_shield =
            (correction.correction_flags &
             ParticipantVitalsCorrectionFlagMagicShieldState) != 0;
        const bool have_stronger_magic_shield_correction =
            correction_magic_shield &&
            (pending_it ==
                 g_local_transport
                     .pending_participant_vitals_corrections_by_participant.end() ||
             (pending_it->second.packet.correction_flags &
              ParticipantVitalsCorrectionFlagMagicShieldState) == 0 ||
             correction.magic_shield_absorb_remaining +
                     kParticipantVitalsCorrectionEpsilon <
                 pending_it->second.packet.magic_shield_absorb_remaining);
        const bool correction_hagatha_runtime =
            (correction.correction_flags &
             ParticipantVitalsCorrectionFlagHagathaRuntimeState) != 0 &&
            correction.hagatha_runtime_valid;
        const bool have_stronger_hagatha_correction =
            correction_hagatha_runtime &&
            (pending_it ==
                 g_local_transport
                     .pending_participant_vitals_corrections_by_participant.end() ||
             (pending_it->second.packet.correction_flags &
              ParticipantVitalsCorrectionFlagHagathaRuntimeState) == 0 ||
             correction.hagatha_cheat_death_charges <
                 pending_it->second.packet.hagatha_cheat_death_charges ||
             (!correction.hagatha_serendipity_active &&
              pending_it->second.packet.hagatha_serendipity_active != 0) ||
             (!correction.hagatha_reverie_active &&
              pending_it->second.packet.hagatha_reverie_active != 0));
        if (!have_stronger_status_correction &&
            !have_stronger_magic_shield_correction &&
            !have_stronger_hagatha_correction) {
            continue;
        }

        auto effective_life_current = correction.life_current;
        auto effective_status_flags = correction.transient_status_flags;
        auto effective_poison_ticks = correction.poison_remaining_ticks;
        auto effective_poison_damage = correction.poison_damage_per_tick;
        auto effective_webbed_ticks = correction.webbed_remaining_ticks;
        auto effective_webbed_strength = correction.webbed_strength;
        auto effective_correction_flags = correction.correction_flags;
        auto effective_magic_shield_absorb_remaining =
            correction.magic_shield_absorb_remaining;
        auto effective_magic_shield_absorb_capacity =
            correction.magic_shield_absorb_capacity;
        auto effective_magic_shield_explosion_fraction =
            correction.magic_shield_explosion_fraction;
        auto effective_magic_shield_hit_flash =
            correction.magic_shield_hit_flash;
        auto effective_hagatha_cheat_death_charges =
            correction.hagatha_cheat_death_charges;
        auto effective_hagatha_serendipity_active =
            correction.hagatha_serendipity_active;
        auto effective_hagatha_reverie_active =
            correction.hagatha_reverie_active;
        auto effective_hagatha_runtime_valid =
            correction.hagatha_runtime_valid;
        if (pending_it !=
            g_local_transport
                .pending_participant_vitals_corrections_by_participant.end()) {
            const auto& previous = pending_it->second.packet;
            const bool previous_hagatha_runtime =
                (previous.correction_flags &
                 ParticipantVitalsCorrectionFlagHagathaRuntimeState) != 0 &&
                previous.hagatha_runtime_valid != 0;
            const bool new_hagatha_runtime =
                (effective_correction_flags &
                 ParticipantVitalsCorrectionFlagHagathaRuntimeState) != 0 &&
                effective_hagatha_runtime_valid;
            const bool correction_consumed_cheat_death =
                new_hagatha_runtime && previous_hagatha_runtime &&
                effective_hagatha_cheat_death_charges <
                    previous.hagatha_cheat_death_charges;
            const bool previous_consumed_cheat_death =
                new_hagatha_runtime && previous_hagatha_runtime &&
                previous.hagatha_cheat_death_charges <
                    effective_hagatha_cheat_death_charges;
            if (previous_consumed_cheat_death) {
                effective_life_current = previous.life_current;
            } else if (!correction_consumed_cheat_death) {
                effective_life_current = (std::min)(
                    effective_life_current,
                    previous.life_current);
            }
            effective_status_flags = static_cast<std::uint8_t>(
                effective_status_flags |
                (previous.transient_status_flags &
                 (ParticipantTransientStatusFlagPoisoned |
                  ParticipantTransientStatusFlagWebbed)));
            effective_poison_ticks = (std::max)(
                effective_poison_ticks,
                previous.poison_remaining_ticks);
            effective_poison_damage = (std::max)(
                effective_poison_damage,
                previous.poison_damage_per_tick);
            effective_webbed_ticks = (std::max)(
                effective_webbed_ticks,
                previous.webbed_remaining_ticks);
            effective_webbed_strength = (std::max)(
                effective_webbed_strength,
                previous.webbed_strength);
            const bool previous_magic_shield =
                (previous.correction_flags &
                 ParticipantVitalsCorrectionFlagMagicShieldState) != 0;
            const bool new_magic_shield =
                (effective_correction_flags &
                 ParticipantVitalsCorrectionFlagMagicShieldState) != 0;
            if (previous_magic_shield &&
                (!new_magic_shield ||
                 previous.magic_shield_absorb_remaining <=
                     effective_magic_shield_absorb_remaining +
                         kParticipantVitalsCorrectionEpsilon)) {
                effective_correction_flags |=
                    ParticipantVitalsCorrectionFlagMagicShieldState;
                effective_magic_shield_absorb_remaining =
                    previous.magic_shield_absorb_remaining;
                effective_magic_shield_absorb_capacity =
                    previous.magic_shield_absorb_capacity;
                effective_magic_shield_explosion_fraction =
                    previous.magic_shield_explosion_fraction;
                effective_magic_shield_hit_flash = (std::max)(
                    effective_magic_shield_hit_flash,
                    previous.magic_shield_hit_flash);
            }
            if (previous_hagatha_runtime) {
                effective_correction_flags |=
                    ParticipantVitalsCorrectionFlagHagathaRuntimeState;
                if (new_hagatha_runtime) {
                    effective_hagatha_cheat_death_charges = (std::min)(
                        effective_hagatha_cheat_death_charges,
                        previous.hagatha_cheat_death_charges);
                    effective_hagatha_serendipity_active =
                        effective_hagatha_serendipity_active &&
                        previous.hagatha_serendipity_active != 0;
                    effective_hagatha_reverie_active =
                        effective_hagatha_reverie_active &&
                        previous.hagatha_reverie_active != 0;
                } else {
                    effective_hagatha_cheat_death_charges =
                        previous.hagatha_cheat_death_charges;
                    effective_hagatha_serendipity_active =
                        previous.hagatha_serendipity_active != 0;
                    effective_hagatha_reverie_active =
                        previous.hagatha_reverie_active != 0;
                }
                effective_hagatha_runtime_valid = true;
            }
        }

        PendingParticipantVitalsCorrection pending;
        pending.packet.header = MakePacketHeader(
            PacketKind::ParticipantVitalsCorrection,
            g_local_transport.next_sequence++);
        pending.packet.authority_participant_id = g_local_transport.local_peer_id;
        pending.packet.target_participant_id = correction.target_participant_id;
        pending.packet.correction_sequence =
            g_local_transport.next_participant_vitals_correction_sequence++;
        if (g_local_transport.next_participant_vitals_correction_sequence == 0) {
            g_local_transport.next_participant_vitals_correction_sequence = 1;
        }
        pending.packet.run_nonce = participant->runtime.run_nonce;
        pending.packet.life_current = effective_life_current;
        pending.packet.life_max = correction.life_max;
        pending.packet.transient_status_flags = static_cast<std::uint8_t>(
            ParticipantTransientStatusFlagSnapshotValid |
            effective_status_flags);
        pending.packet.poison_remaining_ticks =
            effective_poison_ticks;
        pending.packet.poison_damage_per_tick =
            effective_poison_damage;
        pending.packet.webbed_remaining_ticks =
            effective_webbed_ticks;
        pending.packet.webbed_strength = effective_webbed_strength;
        pending.packet.correction_flags = effective_correction_flags;
        pending.packet.hagatha_cheat_death_charges =
            effective_hagatha_cheat_death_charges;
        pending.packet.hagatha_serendipity_active =
            effective_hagatha_serendipity_active ? 1 : 0;
        pending.packet.hagatha_reverie_active =
            effective_hagatha_reverie_active ? 1 : 0;
        pending.packet.hagatha_runtime_valid =
            effective_hagatha_runtime_valid ? 1 : 0;
        pending.packet.magic_shield_absorb_remaining =
            effective_magic_shield_absorb_remaining;
        pending.packet.magic_shield_absorb_capacity =
            effective_magic_shield_absorb_capacity;
        pending.packet.magic_shield_explosion_fraction =
            effective_magic_shield_explosion_fraction;
        pending.packet.magic_shield_hit_flash =
            effective_magic_shield_hit_flash;
        pending.last_sent_ms = 0;
        g_local_transport.pending_participant_vitals_corrections_by_participant[
            correction.target_participant_id] = pending;

        UpdateRuntimeState([&](RuntimeState& state) {
            auto* mutable_participant =
                FindParticipant(state, correction.target_participant_id);
            if (mutable_participant == nullptr) {
                return;
            }
            mutable_participant->runtime.life_current =
                pending_cheat_death_consumed
                    ? pending.packet.life_current
                    : (std::min)(
                          mutable_participant->runtime.life_current,
                          pending.packet.life_current);
            if ((pending.packet.transient_status_flags &
                 (ParticipantTransientStatusFlagPoisoned |
                  ParticipantTransientStatusFlagWebbed)) != 0) {
                mutable_participant->runtime.transient_status_flags =
                    pending.packet.transient_status_flags;
            }
            if ((pending.packet.transient_status_flags &
                 ParticipantTransientStatusFlagPoisoned) != 0) {
                mutable_participant->runtime.poison_remaining_ticks =
                    pending.packet.poison_remaining_ticks;
            }
            if ((pending.packet.correction_flags &
                 ParticipantVitalsCorrectionFlagMagicShieldState) != 0) {
                mutable_participant->runtime.magic_shield_absorb_remaining =
                    pending.packet.magic_shield_absorb_remaining;
                mutable_participant->runtime.magic_shield_absorb_capacity =
                    pending.packet.magic_shield_absorb_capacity;
                mutable_participant->runtime.magic_shield_explosion_fraction =
                    pending.packet.magic_shield_explosion_fraction;
                mutable_participant->runtime.magic_shield_hit_flash =
                    pending.packet.magic_shield_hit_flash;
            }
            if ((pending.packet.correction_flags &
                 ParticipantVitalsCorrectionFlagHagathaRuntimeState) != 0 &&
                pending.packet.hagatha_runtime_valid != 0 &&
                mutable_participant->owned_progression.hagatha_perks.valid) {
                auto& perks =
                    mutable_participant->owned_progression.hagatha_perks;
                const bool changed =
                    perks.cheat_death_charges !=
                        pending.packet.hagatha_cheat_death_charges ||
                    perks.serendipity_active !=
                        (pending.packet.hagatha_serendipity_active != 0) ||
                    perks.reverie_active !=
                        (pending.packet.hagatha_reverie_active != 0);
                perks.cheat_death_charges =
                    pending.packet.hagatha_cheat_death_charges;
                perks.serendipity_active =
                    pending.packet.hagatha_serendipity_active != 0;
                perks.reverie_active =
                    pending.packet.hagatha_reverie_active != 0;
                if (changed) {
                    mutable_participant->owned_progression
                        .hagatha_perk_revision += 1;
                }
            }
        });

        Log(
            "Multiplayer host captured remote participant damage. target_participant_id=" +
            std::to_string(correction.target_participant_id) +
            " correction_sequence=" +
            std::to_string(pending.packet.correction_sequence) +
            " life=" + std::to_string(pending.packet.life_current) + "/" +
            std::to_string(correction.life_max) +
            " transient_flags=" +
            std::to_string(pending.packet.transient_status_flags) +
            " poison_ticks=" +
            std::to_string(pending.packet.poison_remaining_ticks) +
            " poison_damage=" +
            std::to_string(pending.packet.poison_damage_per_tick) +
            " webbed_ticks=" +
            std::to_string(pending.packet.webbed_remaining_ticks) +
            " webbed_strength=" +
            std::to_string(pending.packet.webbed_strength) +
            " correction_flags=" +
            std::to_string(pending.packet.correction_flags) +
            " magic_shield=" +
            std::to_string(pending.packet.magic_shield_absorb_remaining) +
            "/" +
            std::to_string(pending.packet.magic_shield_absorb_capacity));
    }

    for (auto& [participant_id, pending] :
         g_local_transport.pending_participant_vitals_corrections_by_participant) {
        const auto last_send_it =
            g_local_transport.last_participant_vitals_correction_send_ms_by_participant.find(
                participant_id);
        if (last_send_it !=
                g_local_transport.last_participant_vitals_correction_send_ms_by_participant.end() &&
            now_ms - last_send_it->second <
                kParticipantVitalsCorrectionSendIntervalMs) {
            continue;
        }
        if (pending.last_sent_ms != 0 &&
            now_ms - pending.last_sent_ms <
                kParticipantVitalsCorrectionResendMs) {
            continue;
        }
        pending.packet.header.sequence = g_local_transport.next_sequence++;
        SendPacketToParticipantOrPeers(pending.packet, participant_id);
        pending.last_sent_ms = now_ms;
        g_local_transport.last_participant_vitals_correction_send_ms_by_participant[
            participant_id] = now_ms;
    }
}

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
