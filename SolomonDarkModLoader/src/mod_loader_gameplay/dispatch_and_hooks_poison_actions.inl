void ExecuteQueuedPoisonActions(
    bool have_local_player_poison_correction,
    const PendingLocalPlayerPoisonCorrection& local_player_poison_correction,
    const std::vector<PendingNativePoisonBehaviorProbe>& native_poison_behavior_probes) {
    if (have_local_player_poison_correction) {
        SDModPlayerState player_state;
        std::string poison_error;
        bool applied = false;
        if (!TryGetPlayerState(&player_state) ||
            !player_state.valid ||
            player_state.actor_address == 0) {
            poison_error = "local player actor is unavailable";
        } else {
            std::uint8_t transient_flags = 0;
            std::int32_t current_duration_ticks = 0;
            uintptr_t poison_modifier = 0;
            const bool have_transient_state =
                TryReadWizardActorTransientStatusState(
                    player_state.actor_address,
                    &transient_flags,
                    &current_duration_ticks,
                    &poison_modifier);
            const bool poison_active =
                have_transient_state &&
                (transient_flags &
                 multiplayer::ParticipantTransientStatusFlagPoisoned) != 0 &&
                poison_modifier != 0;
            if (poison_active) {
                auto& memory = ProcessMemory::Instance();
                float current_damage_per_tick = 0.0f;
                if (!memory.TryReadField(
                        poison_modifier,
                        kNativePoisonDamagePerTickOffset,
                        &current_damage_per_tick) ||
                    !std::isfinite(current_damage_per_tick) ||
                    current_damage_per_tick < 0.0f) {
                    current_damage_per_tick = 0.0f;
                }
                const auto corrected_duration =
                    (std::max)(
                        current_duration_ticks,
                        local_player_poison_correction.duration_ticks);
                const auto corrected_damage =
                    (std::max)(
                        current_damage_per_tick,
                        local_player_poison_correction.damage_per_tick);
                applied =
                    memory.TryWriteField(
                        poison_modifier,
                        kNativeModifierDurationTicksOffset,
                        corrected_duration) &&
                    memory.TryWriteField(
                        poison_modifier,
                        kNativePoisonDamagePerTickOffset,
                        corrected_damage);
                if (!applied) {
                    poison_error = "failed to refresh native poison modifier";
                }
            } else {
                applied = InstallReplicatedPoisonModifier(
                    player_state.actor_address,
                    local_player_poison_correction.duration_ticks,
                    &poison_error,
                    local_player_poison_correction.damage_per_tick,
                    0);
            }
        }

        if (applied) {
            multiplayer::ConfirmLocalParticipantVitalsCorrection(
                local_player_poison_correction.correction_sequence);
            Log(
                "Multiplayer owner poison correction applied. duration_ticks=" +
                std::to_string(local_player_poison_correction.duration_ticks) +
                " damage_per_tick=" +
                std::to_string(local_player_poison_correction.damage_per_tick));
        } else {
            std::string requeue_error;
            const bool retry_queued = QueueLocalPlayerPoisonCorrection(
                local_player_poison_correction.correction_sequence,
                local_player_poison_correction.duration_ticks,
                local_player_poison_correction.damage_per_tick,
                &requeue_error);
            Log(
                "Multiplayer owner poison correction failed. duration_ticks=" +
                std::to_string(local_player_poison_correction.duration_ticks) +
                " damage_per_tick=" +
                std::to_string(local_player_poison_correction.damage_per_tick) +
                " retry_queued=" + (retry_queued ? "1" : "0") +
                " error=" + poison_error +
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
            (poison_error.empty() ? std::string{} : " error=" + poison_error));
    }
}
