void ResetParticipantEntitiesForRunTermination(
    std::string_view reason) {
    const auto runtime_state =
        multiplayer::SnapshotRuntimeState();
    std::size_t reset_count = 0;
    std::size_t death_epoch_count = 0;

    std::lock_guard<std::recursive_mutex> lock(
        g_participant_entities_mutex);
    for (auto& binding : g_participant_entities) {
        if (!IsWizardParticipantKind(binding.kind)) {
            continue;
        }

        ++reset_count;
        if (binding.native_remote_death_epoch_active) {
            ++death_epoch_count;
        }

        QuiesceDeadWizardBinding(&binding);
        binding.ongoing_cast =
            ParticipantEntityBinding::OngoingCastState{};
        binding.replicated_movement_intent_x = 0.0f;
        binding.replicated_movement_intent_y = 0.0f;
        binding.replicated_anim_drive_state = 0;
        binding.replicated_presentation_flags &=
            ~multiplayer::
                ParticipantPresentationFlagDeathPresentation;
        binding.replicated_anim_drive_state_word = 0;
        binding.replicated_walk_cycle_primary = 0.0f;
        binding.replicated_walk_cycle_secondary = 0.0f;
        binding.replicated_render_drive_stride = 0.0f;
        binding.replicated_render_advance_rate = 0.0f;
        binding.replicated_render_advance_phase = 0.0f;
        binding.replicated_magic_shield_absorb_remaining =
            0.0f;
        binding.replicated_magic_shield_absorb_capacity =
            0.0f;
        binding.replicated_magic_shield_explosion_fraction =
            0.0f;
        binding.replicated_magic_shield_hit_flash = 0.0f;
        binding.death_transition_stock_tick_seen = false;
        binding.local_death_presentation_started_ms = 0;
        binding.native_remote_death_epoch_active = false;
        binding.native_remote_death_attachment_actor_address =
            0;
        binding.native_remote_death_drop_spawned = false;
        binding.native_remote_vital_baseline_valid = false;
        binding.native_remote_last_written_hp = 0.0f;
        binding.native_remote_last_written_max_hp = 0.0f;
        binding.native_remote_webbed_authority_pending = false;
        binding.native_remote_webbed_authority_pending_since_ms =
            0;
        binding.native_remote_webbed_owner_acknowledged = false;
        binding.persistent_status_reconcile_desired_flags = 0;
        binding.persistent_status_reconcile_desired_since_ms = 0;
        binding.persistent_status_reconcile_not_before_ms = 0;
        binding.transient_status_reconcile_desired_flags = 0;
        binding.transient_status_reconcile_desired_since_ms = 0;
        binding.transient_status_reconcile_not_before_ms = 0;
        binding.mana_recovery_not_before_ms = 0;
        binding.last_mana_recovery_log_ms = 0;
        binding.last_mana_reserve_cleanup_log_ms = 0;

        if (binding.actor_address == 0 ||
            !IsParticipantActorMemoryFreshWritable(
                binding.actor_address)) {
            continue;
        }

        std::string cast_error;
        (void)ClearWizardActorGameplayCastState(
            binding.actor_address,
            &cast_error);
        ClearWizardBotLocomotionInputs(
            binding.actor_address);

        auto& memory = ProcessMemory::Instance();
        (void)memory.TryWriteField<std::uint8_t>(
            binding.actor_address,
            kActorTerminalDispatchPendingOffset,
            0);
        (void)memory.TryWriteField<std::int32_t>(
            binding.actor_address,
            kActorTerminalDispatchCountdownOffset,
            0);
        (void)memory.TryWriteField<std::int32_t>(
            binding.actor_address,
            kActorAnimationMoveDurationTicksOffset,
            0);
        ClearLiveWizardActorAnimationDriveState(
            binding.actor_address);
        (void)RestoreWizardActorAliveRegistrationState(
            binding.actor_address);
        (void)memory.TryWriteField<float>(
            binding.actor_address,
            kActorMagicShieldAbsorbRemainingOffset,
            0.0f);
        (void)memory.TryWriteField<float>(
            binding.actor_address,
            kActorMagicShieldAbsorbCapacityOffset,
            0.0f);
        (void)memory.TryWriteField<float>(
            binding.actor_address,
            kActorMagicShieldExplosionFractionOffset,
            0.0f);
        (void)memory.TryWriteField<float>(
            binding.actor_address,
            kActorMagicShieldHitFlashOffset,
            0.0f);
        (void)ReconcileReplicatedWebbedPresentation(
            binding.actor_address,
            multiplayer::
                ParticipantTransientStatusFlagSnapshotValid);

        const auto* participant =
            multiplayer::FindParticipant(
                runtime_state,
                binding.bot_id);
        uintptr_t progression_address = 0;
        if (participant == nullptr ||
            !TryResolveActorProgressionRuntime(
                binding.actor_address,
                &progression_address) ||
            progression_address == 0) {
            continue;
        }
        if (std::isfinite(
                participant->runtime.life_max) &&
            participant->runtime.life_max > 0.0f) {
            (void)memory.TryWriteField(
                progression_address,
                kProgressionHpOffset,
                participant->runtime.life_max);
        }
        if (std::isfinite(
                participant->runtime.mana_max) &&
            participant->runtime.mana_max > 0.0f) {
            (void)memory.TryWriteField(
                progression_address,
                kProgressionMpOffset,
                participant->runtime.mana_max);
        }
    }

    Log(
        "[bots] participant run-termination state reset. "
        "participants=" + std::to_string(reset_count) +
        " retired_death_epochs=" +
        std::to_string(death_epoch_count) +
        " reason=" + std::string(reason));
}
