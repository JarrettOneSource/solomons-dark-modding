bool ReconcileReplicatedWebbedPresentation(
    uintptr_t actor_address,
    std::uint8_t desired_flags) {
    constexpr std::uint32_t kWebbedRenderDriveFlag = 0x20u;
    auto& memory = ProcessMemory::Instance();
    std::uint32_t render_drive_flags = 0;
    if (!memory.TryReadField(
            actor_address,
            kActorRenderDriveFlagsOffset,
            &render_drive_flags)) {
        return false;
    }

    const bool desired_webbed =
        (desired_flags &
         multiplayer::ParticipantTransientStatusFlagWebbed) != 0;
    const auto reconciled_flags = desired_webbed
        ? render_drive_flags | kWebbedRenderDriveFlag
        : render_drive_flags & ~kWebbedRenderDriveFlag;
    return reconciled_flags == render_drive_flags ||
           memory.TryWriteField(
               actor_address,
               kActorRenderDriveFlagsOffset,
               reconciled_flags);
}

bool ReconcileNativeRemoteParticipantTransientStatuses(
    ParticipantEntityBinding* binding,
    std::uint64_t now_ms) {
    if (binding == nullptr ||
        binding->actor_address == 0 ||
        binding->bot_id == 0 ||
        !IsNativeRemoteParticipantBinding(binding)) {
        return false;
    }

    const auto runtime = multiplayer::SnapshotRuntimeState();
    const auto* participant =
        multiplayer::FindParticipant(runtime, binding->bot_id);
    if (participant == nullptr) {
        return false;
    }
    const auto desired_flags =
        participant->runtime.transient_status_flags;
    if ((desired_flags &
         multiplayer::ParticipantTransientStatusFlagSnapshotValid) == 0) {
        return false;
    }
    const bool webbed_presentation_reconciled =
        ReconcileReplicatedWebbedPresentation(
            binding->actor_address,
            desired_flags);
    NativeWizardTransientStatusState native_state;
    if (!TryReadWizardActorTransientStatusState(
            binding->actor_address,
            &native_state)) {
        return false;
    }
    const bool desired_webbed =
        (desired_flags &
         multiplayer::ParticipantTransientStatusFlagWebbed) != 0;
    bool webbed_native_reconciled = true;
    if (desired_webbed) {
        binding->native_remote_webbed_authority_pending = false;
        binding->native_remote_webbed_authority_pending_since_ms = 0;
        binding->native_remote_webbed_owner_acknowledged = true;
    } else if (binding->native_remote_webbed_owner_acknowledged) {
        std::string webbed_removal_error;
        webbed_native_reconciled =
            native_state.webbed_modifier_address == 0 ||
            RemoveAllNativeActorModifiersByType(
                binding->actor_address,
                kNativeWebbedModifierTypeId,
                &webbed_removal_error);
        NativeWizardTransientStatusState verified_state;
        webbed_native_reconciled =
            webbed_native_reconciled &&
            TryReadWizardActorTransientStatusState(
                binding->actor_address,
                &verified_state) &&
            verified_state.webbed_modifier_address == 0;
        if (webbed_native_reconciled) {
            binding->native_remote_webbed_owner_acknowledged = false;
            binding->native_remote_webbed_authority_pending = false;
            binding->native_remote_webbed_authority_pending_since_ms = 0;
            native_state = verified_state;
            Log(
                "[bots] remote native Webbed authority state cleared. bot_id=" +
                std::to_string(binding->bot_id) +
                " actor=" + HexString(binding->actor_address));
        } else {
            Log(
                "[bots] remote native Webbed authority state clear failed. "
                "bot_id=" + std::to_string(binding->bot_id) +
                " actor=" + HexString(binding->actor_address) +
                " error=" + webbed_removal_error);
        }
    }
    if (binding->ongoing_cast.active) {
        return webbed_presentation_reconciled &&
               webbed_native_reconciled;
    }

    const auto desired_native_status_values = static_cast<std::uint8_t>(
        desired_flags & kNativeTransientStatusValueMask);
    if (binding->transient_status_reconcile_desired_flags !=
        desired_native_status_values) {
        binding->transient_status_reconcile_desired_flags =
            desired_native_status_values;
        binding->transient_status_reconcile_desired_since_ms = now_ms;
        // Let the matching owner-authored CastPacket replay before repairing
        // packet loss, a frozen remote modifier, or a late-join snapshot.
        binding->transient_status_reconcile_not_before_ms = now_ms + 500;
    }

    const auto native_flags = native_state.flags;
    const auto native_duration = native_state.poison_remaining_ticks;
    const auto poison_modifier = native_state.poison_modifier_address;
    const auto poison_control_block = native_state.poison_control_block_address;

    const auto native_status_values = static_cast<std::uint8_t>(
        native_flags & kNativeTransientStatusValueMask);
    const NativeTransientStatusMapping* status_mismatch = nullptr;
    for (const auto& mapping : kNativeTransientStatusMappings) {
        if ((desired_native_status_values & mapping.flag) !=
            (native_status_values & mapping.flag)) {
            status_mismatch = &mapping;
            break;
        }
    }

    bool native_secondary_status_reconciled = status_mismatch == nullptr;
    if (status_mismatch == nullptr) {
        binding->transient_status_reconcile_not_before_ms = 0;
    } else if (now_ms >=
               binding->transient_status_reconcile_not_before_ms) {
        const bool desired_active =
            (desired_native_status_values & status_mismatch->flag) != 0;
        const bool can_apply =
            (!desired_active &&
             status_mismatch->installed_modifier_type != 0) ||
            RemoteParticipantOwnsSkill(
                binding->bot_id,
                status_mismatch->skill_entry);
        bool applied = false;
        bool invoked = false;
        std::uint8_t native_result = 0;
        std::string action_error;
        std::string progression_owner_context;
        std::string player_actor_owner_context;
        if (can_apply &&
            !desired_active &&
            status_mismatch->installed_modifier_type != 0) {
            applied = RemoveAllNativeActorModifiersByType(
                binding->actor_address,
                status_mismatch->installed_modifier_type,
                &action_error);
        } else if (can_apply) {
            invoked = InvokeNativeRemoteParticipantSecondarySkill(
                binding,
                status_mismatch->skill_entry,
                &native_result,
                &progression_owner_context,
                &player_actor_owner_context);
            applied = invoked;
        } else {
            action_error = "participant does not own required skill";
        }

        NativeWizardTransientStatusState verified_state;
        const bool verified =
            applied &&
            TryReadWizardActorTransientStatusState(
                binding->actor_address,
                &verified_state) &&
            ((verified_state.flags & status_mismatch->flag) ==
             (desired_native_status_values & status_mismatch->flag));
        native_secondary_status_reconciled = verified;
        binding->transient_status_reconcile_not_before_ms =
            now_ms + (verified ? 100 : 1000);
        Log(
            "[bots] remote transient status reconciled. bot_id=" +
            std::to_string(binding->bot_id) +
            " actor=" + HexString(binding->actor_address) +
            " status=" + status_mismatch->label +
            " skill_entry=" +
            std::to_string(status_mismatch->skill_entry) +
            " desired_flags=" + std::to_string(desired_flags) +
            " native_before=" + std::to_string(native_flags) +
            " native_after=" + std::to_string(verified_state.flags) +
            " invoked=" + std::to_string(invoked ? 1 : 0) +
            " native_result=" + std::to_string(native_result) +
            " verified=" + std::to_string(verified ? 1 : 0) +
            " error=" + action_error +
            " progression_owner_context={" +
            progression_owner_context + "}" +
            " player_actor_owner_context={" +
            player_actor_owner_context + "}");
    }

    const bool desired_poisoned =
        participant->runtime.life_current > 0.0f &&
        (desired_flags &
         multiplayer::ParticipantTransientStatusFlagPoisoned) != 0 &&
        participant->runtime.poison_remaining_ticks > 0;
    auto& memory = ProcessMemory::Instance();
    if (!desired_poisoned) {
        if (poison_modifier == 0) {
            return native_secondary_status_reconciled &&
                   webbed_presentation_reconciled &&
                   webbed_native_reconciled;
        }
        const float zero_damage = 0.0f;
        const std::int8_t remote_visual_source_slot = 1;
        const bool neutralized =
            memory.TryWriteField(
                poison_modifier,
                kNativeModifierDurationTicksOffset,
                std::int32_t{0}) &&
            memory.TryWriteField(
                poison_modifier,
                kNativePoisonDamagePerTickOffset,
                zero_damage) &&
            memory.TryWriteField(
                poison_modifier,
                kNativePoisonSourceSlotOffset,
                remote_visual_source_slot);
        const auto modifier_list_address =
            binding->actor_address + kActorModifierListOffset;
        uintptr_t modifier_list_vtable = 0;
        uintptr_t remove_address = 0;
        DWORD exception_code = 0;
        const bool removed =
            neutralized &&
            poison_control_block != 0 &&
            memory.TryReadValue(
                modifier_list_address,
                &modifier_list_vtable) &&
            modifier_list_vtable != 0 &&
            memory.TryReadValue(
                modifier_list_vtable +
                    kPointerListRemoveValueVtableOffset,
                &remove_address) &&
            remove_address != 0 &&
            memory.IsExecutableRange(remove_address, 1) &&
            CallPointerListRemoveValueSafe(
                remove_address,
                modifier_list_address,
                poison_control_block,
                &exception_code);
        NativeWizardTransientStatusState verified_state;
        const bool cleared =
            removed &&
            TryReadWizardActorTransientStatusState(
                binding->actor_address,
                &verified_state) &&
            verified_state.poison_modifier_address == 0;
        if (cleared) {
            Log(
                "[bots] remote transient poison cleared. bot_id=" +
                std::to_string(binding->bot_id) +
                " actor=" + HexString(binding->actor_address));
        } else {
            Log(
                "[bots] remote transient poison clear failed. bot_id=" +
                std::to_string(binding->bot_id) +
                " actor=" + HexString(binding->actor_address) +
                " control=" + HexString(poison_control_block) +
                " seh=0x" + HexString(exception_code));
        }
        return cleared && native_secondary_status_reconciled &&
               webbed_presentation_reconciled &&
               webbed_native_reconciled;
    }

    const auto desired_duration = (std::clamp)(
        participant->runtime.poison_remaining_ticks,
        std::int32_t{1},
        multiplayer::kParticipantPoisonMaxDurationTicks);
    if (poison_modifier == 0) {
        std::string error_message;
        const bool installed = InstallReplicatedPoisonModifier(
            binding->actor_address,
            desired_duration,
            &error_message);
        Log(
            "[bots] remote transient poison install. bot_id=" +
            std::to_string(binding->bot_id) +
            " actor=" + HexString(binding->actor_address) +
            " desired_ticks=" + std::to_string(desired_duration) +
            " installed=" + std::to_string(installed ? 1 : 0) +
            " error=" + error_message);
        return installed && native_secondary_status_reconciled &&
               webbed_presentation_reconciled &&
               webbed_native_reconciled;
    }

    const float zero_damage = 0.0f;
    const std::int8_t remote_visual_source_slot = 1;
    bool reconciled =
        memory.TryWriteField(
            poison_modifier,
            kNativePoisonDamagePerTickOffset,
            zero_damage) &&
        memory.TryWriteField(
            poison_modifier,
            kNativePoisonSourceSlotOffset,
            remote_visual_source_slot);
    constexpr std::int32_t kPoisonDurationDriftToleranceTicks = 20;
    const auto duration_delta =
        static_cast<std::int64_t>(native_duration) -
        static_cast<std::int64_t>(desired_duration);
    if (duration_delta < -kPoisonDurationDriftToleranceTicks ||
        duration_delta > kPoisonDurationDriftToleranceTicks) {
        reconciled =
            memory.TryWriteField(
                poison_modifier,
                kNativeModifierDurationTicksOffset,
                desired_duration) &&
            reconciled;
    }
    return reconciled && native_secondary_status_reconciled &&
           webbed_presentation_reconciled &&
           webbed_native_reconciled;
}
