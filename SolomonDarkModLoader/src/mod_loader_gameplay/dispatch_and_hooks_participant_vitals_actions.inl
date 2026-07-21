bool ApplyLocalPlayerPoisonCorrection(
    uintptr_t actor_address,
    const PendingLocalPlayerVitalsCorrection& correction,
    std::string* error_message) {
    NativeWizardTransientStatusState transient_state;
    const bool poison_active =
        TryReadWizardActorTransientStatusState(
            actor_address,
            &transient_state) &&
        (transient_state.flags &
         multiplayer::ParticipantTransientStatusFlagPoisoned) != 0 &&
        transient_state.poison_modifier_address != 0;
    if (!poison_active) {
        return InstallReplicatedPoisonModifier(
            actor_address,
            correction.poison_remaining_ticks,
            error_message,
            correction.poison_damage_per_tick,
            0);
    }

    auto& memory = ProcessMemory::Instance();
    float current_damage_per_tick = 0.0f;
    if (!memory.TryReadField(
            transient_state.poison_modifier_address,
            kNativePoisonDamagePerTickOffset,
            &current_damage_per_tick) ||
        !std::isfinite(current_damage_per_tick) ||
        current_damage_per_tick < 0.0f) {
        current_damage_per_tick = 0.0f;
    }
    const auto corrected_duration = (std::max)(
        transient_state.poison_remaining_ticks,
        correction.poison_remaining_ticks);
    const auto corrected_damage = (std::max)(
        current_damage_per_tick,
        correction.poison_damage_per_tick);
    const bool refreshed =
        memory.TryWriteField(
            transient_state.poison_modifier_address,
            kNativeModifierDurationTicksOffset,
            corrected_duration) &&
        memory.TryWriteField(
            transient_state.poison_modifier_address,
            kNativePoisonDamagePerTickOffset,
            corrected_damage);
    if (!refreshed && error_message != nullptr) {
        *error_message = "failed to refresh native poison modifier";
    }
    return refreshed;
}

bool ApplyLocalPlayerWebbedCorrection(
    uintptr_t actor_address,
    const PendingLocalPlayerVitalsCorrection& correction,
    std::string* error_message) {
    NativeWizardTransientStatusState transient_state;
    const bool webbed_active =
        TryReadWizardActorTransientStatusState(
            actor_address,
            &transient_state) &&
        (transient_state.flags &
         multiplayer::ParticipantTransientStatusFlagWebbed) != 0 &&
        transient_state.webbed_modifier_address != 0;
    if (!webbed_active) {
        return InstallReplicatedWebbedModifier(
            actor_address,
            correction.webbed_remaining_ticks,
            correction.webbed_strength,
            error_message);
    }

    // The native Apply callback has already multiplied movement speed by this
    // modifier's strength. Preserve that paired value so stock expiration can
    // undo it correctly; only extend the remaining authoritative duration.
    const auto corrected_duration = (std::max)(
        transient_state.webbed_remaining_ticks,
        correction.webbed_remaining_ticks);
    const bool refreshed = ProcessMemory::Instance().TryWriteField(
        transient_state.webbed_modifier_address,
        kNativeModifierDurationTicksOffset,
        corrected_duration);
    if (!refreshed && error_message != nullptr) {
        *error_message = "failed to refresh native Webbed modifier";
    }
    return refreshed;
}

bool ApplyLocalPlayerMagicShieldCorrection(
    uintptr_t actor_address,
    const PendingLocalPlayerVitalsCorrection& correction,
    std::string* error_message) {
    const bool wrote =
        ProcessMemory::Instance().TryWriteField(
            actor_address,
            kActorMagicShieldAbsorbRemainingOffset,
            correction.magic_shield_absorb_remaining) &&
        ProcessMemory::Instance().TryWriteField(
            actor_address,
            kActorMagicShieldAbsorbCapacityOffset,
            correction.magic_shield_absorb_capacity) &&
        ProcessMemory::Instance().TryWriteField(
            actor_address,
            kActorMagicShieldExplosionFractionOffset,
            correction.magic_shield_explosion_fraction) &&
        ProcessMemory::Instance().TryWriteField(
            actor_address,
            kActorMagicShieldHitFlashOffset,
            correction.magic_shield_hit_flash);
    if (!wrote && error_message != nullptr) {
        *error_message = "failed to write native Magic Shield state";
    }
    return wrote;
}

void ExecuteQueuedParticipantVitalsActions(
    bool have_local_player_vitals_correction,
    const PendingLocalPlayerVitalsCorrection& local_player_vitals_correction,
    const std::vector<PendingNativePoisonBehaviorProbe>&
        native_poison_behavior_probes) {
    if (have_local_player_vitals_correction) {
        SDModPlayerState player_state;
        std::string correction_error;
        bool applied = false;
        if (!TryGetPlayerState(&player_state) ||
            !player_state.valid ||
            player_state.actor_address == 0) {
            correction_error = "local player actor is unavailable";
        } else {
            applied = true;
            if ((local_player_vitals_correction.transient_status_flags &
                 multiplayer::ParticipantTransientStatusFlagPoisoned) != 0) {
                applied = ApplyLocalPlayerPoisonCorrection(
                    player_state.actor_address,
                    local_player_vitals_correction,
                    &correction_error);
            }
            if (applied &&
                (local_player_vitals_correction.transient_status_flags &
                 multiplayer::ParticipantTransientStatusFlagWebbed) != 0) {
                applied = ApplyLocalPlayerWebbedCorrection(
                    player_state.actor_address,
                    local_player_vitals_correction,
                    &correction_error);
            }
            if (applied &&
                (local_player_vitals_correction.correction_flags &
                 multiplayer::
                     ParticipantVitalsCorrectionFlagMagicShieldState) != 0) {
                applied = ApplyLocalPlayerMagicShieldCorrection(
                    player_state.actor_address,
                    local_player_vitals_correction,
                    &correction_error);
            }
        }

        if (applied) {
            multiplayer::ConfirmLocalParticipantVitalsCorrection(
                local_player_vitals_correction.correction_sequence);
            Log(
                "Multiplayer owner native vitals correction applied. "
                "transient_flags=" +
                std::to_string(
                    local_player_vitals_correction.transient_status_flags) +
                " poison_ticks=" +
                std::to_string(
                    local_player_vitals_correction.poison_remaining_ticks) +
                " poison_damage=" +
                std::to_string(
                    local_player_vitals_correction.poison_damage_per_tick) +
                " webbed_ticks=" +
                std::to_string(
                    local_player_vitals_correction.webbed_remaining_ticks) +
                " webbed_strength=" +
                std::to_string(local_player_vitals_correction.webbed_strength) +
                " correction_flags=" +
                std::to_string(local_player_vitals_correction.correction_flags) +
                " magic_shield=" +
                std::to_string(
                    local_player_vitals_correction
                        .magic_shield_absorb_remaining) +
                "/" +
                std::to_string(
                    local_player_vitals_correction
                        .magic_shield_absorb_capacity));
        } else {
            std::string requeue_error;
            const bool retry_queued =
                QueueLocalPlayerVitalsCorrection(
                    local_player_vitals_correction.correction_sequence,
                    local_player_vitals_correction.transient_status_flags,
                    local_player_vitals_correction.poison_remaining_ticks,
                    local_player_vitals_correction.poison_damage_per_tick,
                    local_player_vitals_correction.webbed_remaining_ticks,
                    local_player_vitals_correction.webbed_strength,
                    local_player_vitals_correction.correction_flags,
                    local_player_vitals_correction
                        .magic_shield_absorb_remaining,
                    local_player_vitals_correction
                        .magic_shield_absorb_capacity,
                    local_player_vitals_correction
                        .magic_shield_explosion_fraction,
                    local_player_vitals_correction.magic_shield_hit_flash,
                    &requeue_error);
            Log(
                "Multiplayer owner native vitals correction failed. flags=" +
                std::to_string(
                    local_player_vitals_correction.transient_status_flags) +
                " retry_queued=" + (retry_queued ? "1" : "0") +
                " error=" + correction_error +
                (requeue_error.empty()
                     ? std::string{}
                     : " retry_error=" + requeue_error));
        }
    }

    for (const auto& request : native_poison_behavior_probes) {
        uintptr_t actor_address = 0;
        if (request.target_participant_id == 0) {
            SDModPlayerState player_state;
            if (TryGetPlayerState(&player_state) && player_state.valid) {
                actor_address = player_state.actor_address;
            }
        } else {
            const auto* binding =
                FindParticipantEntity(request.target_participant_id);
            if (binding != nullptr) {
                actor_address = binding->actor_address;
            }
        }

        std::string poison_error;
        const bool applied =
            actor_address != 0 &&
            InstallReplicatedPoisonModifier(
                actor_address,
                request.duration_ticks,
                &poison_error,
                request.damage_per_tick,
                request.source_slot,
                false);
        Log(
            std::string("Native poison behavior probe ") +
            (applied ? "applied" : "failed") +
            ". target_participant_id=" +
            std::to_string(request.target_participant_id) +
            " actor=" + HexString(actor_address) +
            " duration_ticks=" +
            std::to_string(request.duration_ticks) +
            " damage_per_tick=" +
            std::to_string(request.damage_per_tick) +
            " source_slot=" +
            std::to_string(static_cast<int>(request.source_slot)) +
            (poison_error.empty()
                 ? std::string{}
                 : " error=" + poison_error));
    }
}
