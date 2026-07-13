bool IsRemoteNativeSecondaryToggleSkill(std::int32_t skill_entry_index) {
    return skill_entry_index == 0x17 ||
           skill_entry_index == 0x4E ||
           skill_entry_index == 0x4F;
}

struct PersistentStatusToggleMapping {
    std::uint8_t flag = 0;
    std::int32_t skill_entry = -1;
    const char* label = "unknown";
};

constexpr std::array<PersistentStatusToggleMapping, 3>
    kPersistentStatusToggleMappings = {{
        {multiplayer::ParticipantPersistentStatusFlagFirewalker, 0x17, "firewalker"},
        {multiplayer::ParticipantPersistentStatusFlagMindstar, 0x4E, "mindstar"},
        {multiplayer::ParticipantPersistentStatusFlagRegenerate, 0x4F, "regenerate"},
    }};

bool RemoteParticipantOwnsPersistentStatusSkill(
    std::uint64_t participant_id,
    std::int32_t skill_entry) {
    const auto runtime = multiplayer::SnapshotRuntimeState();
    const auto* participant =
        multiplayer::FindParticipant(runtime, participant_id);
    if (participant == nullptr ||
        !participant->owned_progression.initialized) {
        return false;
    }
    for (const auto& entry :
         participant->owned_progression.progression_book_entries) {
        if (entry.entry_index == skill_entry) {
            return entry.active != 0;
        }
    }
    return false;
}

bool ReconcileNativeRemoteParticipantPersistentStatuses(
    ParticipantEntityBinding* binding,
    std::uint64_t now_ms) {
    if (binding == nullptr ||
        binding->actor_address == 0 ||
        binding->bot_id == 0 ||
        !IsNativeRemoteParticipantBinding(binding) ||
        binding->ongoing_cast.active) {
        return false;
    }

    const auto runtime = multiplayer::SnapshotRuntimeState();
    const auto* participant =
        multiplayer::FindParticipant(runtime, binding->bot_id);
    if (participant == nullptr) {
        return false;
    }
    const auto desired_flags =
        participant->runtime.persistent_status_flags;
    if ((desired_flags &
         multiplayer::ParticipantPersistentStatusFlagSnapshotValid) == 0) {
        return false;
    }

    if (binding->persistent_status_reconcile_desired_flags != desired_flags) {
        binding->persistent_status_reconcile_desired_flags = desired_flags;
        binding->persistent_status_reconcile_desired_since_ms = now_ms;
        // Give the matching CastPacket ample time to arrive and replay first.
        // This path is for packet loss and late-join catch-up, not normal casts.
        binding->persistent_status_reconcile_not_before_ms = now_ms + 500;
        return false;
    }

    std::uint8_t native_flags = 0;
    if (!TryReadWizardActorPersistentStatusFlags(
            binding->actor_address,
            &native_flags)) {
        return false;
    }
    const auto desired_values =
        desired_flags & multiplayer::kParticipantPersistentStatusValueMask;
    const auto native_values =
        native_flags & multiplayer::kParticipantPersistentStatusValueMask;
    if (desired_values == native_values) {
        binding->persistent_status_reconcile_not_before_ms = 0;
        return true;
    }
    if (now_ms < binding->persistent_status_reconcile_not_before_ms) {
        return false;
    }

    const PersistentStatusToggleMapping* mismatch = nullptr;
    for (const auto& mapping : kPersistentStatusToggleMappings) {
        if ((desired_values & mapping.flag) !=
            (native_values & mapping.flag)) {
            mismatch = &mapping;
            break;
        }
    }
    if (mismatch == nullptr ||
        !RemoteParticipantOwnsPersistentStatusSkill(
            binding->bot_id,
            mismatch->skill_entry)) {
        binding->persistent_status_reconcile_not_before_ms = now_ms + 1000;
        return false;
    }

    bool invoked = false;
    std::uint8_t native_result = 0;
    std::string progression_owner_context;
    std::string player_actor_owner_context;
    InvokeWithParticipantConcentrationContext(
        binding,
        [&] {
            InvokeWithBotProgressionSlotOwnerContext(
                binding->actor_address,
                true,
                [&] {
                    InvokeWithGameplayPlayerActorSlotContext(
                        binding->actor_address,
                        true,
                        [&] {
                            invoked = InvokeOriginalPlayerActorSecondarySpellCast(
                                binding->actor_address,
                                mismatch->skill_entry,
                                &native_result);
                        },
                        &player_actor_owner_context);
                },
                &progression_owner_context);
        },
        nullptr);

    std::uint8_t verified_flags = 0;
    const bool verified =
        invoked &&
        TryReadWizardActorPersistentStatusFlags(
            binding->actor_address,
            &verified_flags) &&
        ((verified_flags & mismatch->flag) ==
         (desired_values & mismatch->flag));
    binding->persistent_status_reconcile_not_before_ms =
        now_ms + (verified ? 100 : 1000);
    Log(
        "[bots] remote persistent status reconciled. bot_id=" +
        std::to_string(binding->bot_id) +
        " actor=" + HexString(binding->actor_address) +
        " status=" + mismatch->label +
        " skill_entry=" + std::to_string(mismatch->skill_entry) +
        " desired_flags=" + std::to_string(desired_flags) +
        " native_before=" + std::to_string(native_flags) +
        " native_after=" + std::to_string(verified_flags) +
        " invoked=" + std::to_string(invoked ? 1 : 0) +
        " native_result=" + std::to_string(native_result) +
        " verified=" + std::to_string(verified ? 1 : 0) +
        " progression_owner_context={" + progression_owner_context + "}" +
        " player_actor_owner_context={" + player_actor_owner_context + "}");
    return verified;
}

bool ReplayPendingNativeSecondaryCast(
    ParticipantEntityBinding* binding,
    const multiplayer::BotCastRequest& request,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (binding == nullptr ||
        binding->actor_address == 0 ||
        binding->bot_id == 0 ||
        request.kind != multiplayer::BotCastKind::Secondary ||
        !request.remote_input_controlled ||
        !IsNativeRemoteParticipantBinding(binding) ||
        request.secondary_slot < 0 ||
        request.secondary_slot >=
            static_cast<std::int32_t>(
                binding->character_profile.loadout.secondary_entry_indices.size()) ||
        request.skill_id < 0) {
        if (error_message != nullptr) {
            *error_message = "invalid remote native secondary cast request";
        }
        return false;
    }

    const auto slot = static_cast<std::size_t>(request.secondary_slot);
    const auto binding_profile_skill =
        binding->character_profile.loadout.secondary_entry_indices[slot];
    const bool binding_profile_lagged =
        binding_profile_skill != request.skill_id;

    auto& memory = ProcessMemory::Instance();
    const auto actor_address = binding->actor_address;
    float aim_heading = 0.0f;
    bool have_aim_heading = false;
    float aim_target_x = request.aim_target_x;
    float aim_target_y = request.aim_target_y;
    bool have_aim_target =
        request.has_aim_target &&
        std::isfinite(aim_target_x) &&
        std::isfinite(aim_target_y);

    if (request.target_actor_address != 0) {
        float target_heading = 0.0f;
        float target_x = 0.0f;
        float target_y = 0.0f;
        if (TryComputeActorAimTowardTarget(
                actor_address,
                request.target_actor_address,
                &target_heading,
                &target_x,
                &target_y)) {
            aim_heading = target_heading;
            have_aim_heading = true;
            aim_target_x = target_x;
            aim_target_y = target_y;
            have_aim_target = true;
        }
    }
    if (!have_aim_heading && have_aim_target) {
        float actor_x = 0.0f;
        float actor_y = 0.0f;
        if (TryReadFiniteFloatField(actor_address, kActorPositionXOffset, &actor_x) &&
            TryReadFiniteFloatField(actor_address, kActorPositionYOffset, &actor_y)) {
            const auto dx = aim_target_x - actor_x;
            const auto dy = aim_target_y - actor_y;
            if (dx * dx + dy * dy > 0.0001f) {
                aim_heading = NormalizeWizardActorHeadingForWrite(
                    static_cast<float>(
                        std::atan2(dy, dx) * kWizardHeadingRadiansToDegrees +
                        90.0));
                have_aim_heading = true;
            }
        }
    }
    if (!have_aim_heading &&
        request.has_aim_angle &&
        std::isfinite(request.aim_angle)) {
        aim_heading = NormalizeWizardActorHeadingForWrite(request.aim_angle);
        have_aim_heading = true;
    }
    if (have_aim_heading) {
        ApplyWizardActorFacingState(actor_address, aim_heading);
        binding->facing_heading_value = aim_heading;
        binding->facing_heading_valid = true;
    }
    if (have_aim_target) {
        (void)memory.TryWriteField(actor_address, kActorAimTargetXOffset, aim_target_x);
        (void)memory.TryWriteField(actor_address, kActorAimTargetYOffset, aim_target_y);
        (void)memory.TryWriteField<std::uint32_t>(
            actor_address,
            kActorAimTargetAux0Offset,
            0);
        (void)memory.TryWriteField<std::uint32_t>(
            actor_address,
            kActorAimTargetAux1Offset,
            0);
    }
    binding->facing_target_actor_address = request.target_actor_address;
    (void)memory.TryWriteField<uintptr_t>(
        actor_address,
        kActorCurrentTargetActorOffset,
        request.target_actor_address);

    std::uint8_t native_result = 0;
    bool invoked = false;
    uintptr_t replay_progression = 0;
    float replay_mana_before = 0.0f;
    float replay_mana_max = 0.0f;
    bool replay_mana_snapshot_valid =
        memory.TryReadField(
            actor_address,
            kActorProgressionRuntimeStateOffset,
            &replay_progression) &&
        replay_progression != 0 &&
        TryReadFiniteFloatField(
            replay_progression,
            kProgressionMpOffset,
            &replay_mana_before) &&
        TryReadFiniteFloatField(
            replay_progression,
            kProgressionMaxMpOffset,
            &replay_mana_max) &&
        replay_mana_max >= 0.0f;
    bool replay_mana_primed = false;
    if (replay_mana_snapshot_valid) {
        // The owner's post-cast state packet can beat its CastPacket. Native
        // observer replay must still enter the stock spell branch, but the
        // observer must never spend that participant's authoritative mana a
        // second time. Prime with the replicated maximum for dispatch and
        // restore the exact pre-replay value immediately afterward.
        replay_mana_primed = memory.TryWriteField(
            replay_progression,
            kProgressionMpOffset,
            replay_mana_max);
    }
    std::string progression_owner_context;
    std::string player_actor_owner_context;
    InvokeWithParticipantConcentrationContext(
        binding,
        [&] {
            InvokeWithBotProgressionSlotOwnerContext(
                actor_address,
                true,
                [&] {
                    InvokeWithGameplayPlayerActorSlotContext(
                        actor_address,
                        true,
                        [&] {
                            invoked = InvokeOriginalPlayerActorSecondarySpellCast(
                                actor_address,
                                request.skill_id,
                                &native_result);
                        },
                        &player_actor_owner_context);
                },
                &progression_owner_context);
        },
        nullptr);
    bool replay_mana_restored = false;
    if (replay_mana_snapshot_valid && replay_mana_primed) {
        replay_mana_restored = memory.TryWriteField(
            replay_progression,
            kProgressionMpOffset,
            replay_mana_before);
    }

    binding->ongoing_cast = ParticipantEntityBinding::OngoingCastState{};
    const bool native_success =
        invoked &&
        (native_result != 0 ||
         IsRemoteNativeSecondaryToggleSkill(request.skill_id));
    if (native_success && IsRemoteNativeSecondaryToggleSkill(request.skill_id)) {
        // Cast packets normally arrive before the owner's next state packet.
        // Do not let the still-old persistent snapshot immediately undo a
        // successful native toggle and then toggle it back again.
        binding->persistent_status_reconcile_not_before_ms =
            static_cast<std::uint64_t>(GetTickCount64()) + 500;
    }
    float heading = 0.0f;
    const bool heading_readable =
        TryReadFiniteFloatField(actor_address, kActorHeadingOffset, &heading);
    (void)multiplayer::FinishBotAttack(
        binding->bot_id,
        heading_readable,
        heading,
        true);

    Log(
        "[bots] remote native secondary cast replayed. bot_id=" +
        std::to_string(binding->bot_id) +
        " actor=" + HexString(actor_address) +
        " cast_sequence=" + std::to_string(request.cast_sequence) +
        " skill_entry=" + std::to_string(request.skill_id) +
        " belt_slot=" + std::to_string(request.secondary_slot) +
        " invoked=" + std::to_string(invoked ? 1 : 0) +
        " native_result=" + std::to_string(native_result) +
        " success=" + std::to_string(native_success ? 1 : 0) +
        " binding_profile_skill=" + std::to_string(binding_profile_skill) +
        " binding_profile_lagged=" +
            std::to_string(binding_profile_lagged ? 1 : 0) +
        " replay_mana_before=" + std::to_string(replay_mana_before) +
        " replay_mana_max=" + std::to_string(replay_mana_max) +
        " replay_mana_primed=" + std::to_string(replay_mana_primed ? 1 : 0) +
        " replay_mana_restored=" +
            std::to_string(replay_mana_restored ? 1 : 0) +
        " progression_owner_context={" + progression_owner_context + "}" +
        " player_actor_owner_context={" + player_actor_owner_context + "}");

    if (!native_success && error_message != nullptr) {
        *error_message =
            invoked
                ? "native remote secondary dispatcher rejected the cast"
                : "native remote secondary dispatcher trampoline unavailable";
    }
    return native_success;
}
