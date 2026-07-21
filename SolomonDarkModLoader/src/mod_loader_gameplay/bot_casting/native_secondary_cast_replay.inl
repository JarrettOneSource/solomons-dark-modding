bool IsRemoteNativeSecondaryToggleSkill(std::int32_t skill_entry_index) {
    return skill_entry_index == 0x17 ||
           skill_entry_index == 0x4E ||
           skill_entry_index == 0x4F;
}

bool RequiresStockSecondaryActorSlotZero(std::int32_t skill_entry_index) {
    // The row-0x1E dispatcher passes actor+0x5C to the stock routine. That
    // routine uses it to select gameplay's player actor and explicitly skips
    // its target modifier branch when the byte is nonzero. The surrounding
    // gameplay-player context already publishes this actor in table slot 0.
    // Other secondaries may persist the source slot into spawned actors, so
    // this stock single-player assumption must not be applied globally.
    return skill_entry_index == 0x1E;
}

template <typename InvokeFn>
bool InvokeWithStockSecondaryActorSlotZeroContext(
    uintptr_t actor_address,
    std::int32_t skill_entry_index,
    InvokeFn&& invoke,
    std::string* context_description = nullptr) {
    return InvokeWithActorSlotZeroContext(
        actor_address,
        RequiresStockSecondaryActorSlotZero(skill_entry_index),
        std::forward<InvokeFn>(invoke),
        context_description);
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

bool RemoteParticipantOwnsSkill(
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

bool InvokeNativeRemoteParticipantSecondarySkill(
    ParticipantEntityBinding* binding,
    std::int32_t skill_entry,
    std::uint8_t* native_result,
    std::string* progression_owner_context,
    std::string* player_actor_owner_context) {
    if (native_result != nullptr) {
        *native_result = 0;
    }
    if (progression_owner_context != nullptr) {
        progression_owner_context->clear();
    }
    if (player_actor_owner_context != nullptr) {
        player_actor_owner_context->clear();
    }
    if (binding == nullptr ||
        binding->actor_address == 0 ||
        skill_entry < 0) {
        return false;
    }

    bool invoked = false;
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
                                skill_entry,
                                native_result);
                        },
                        player_actor_owner_context);
                },
                progression_owner_context);
        },
        nullptr);
    return invoked;
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
        !RemoteParticipantOwnsSkill(
            binding->bot_id,
            mismatch->skill_entry)) {
        binding->persistent_status_reconcile_not_before_ms = now_ms + 1000;
        return false;
    }

    std::uint8_t native_result = 0;
    std::string progression_owner_context;
    std::string player_actor_owner_context;
    const bool invoked = InvokeNativeRemoteParticipantSecondarySkill(
        binding,
        mismatch->skill_entry,
        &native_result,
        &progression_owner_context,
        &player_actor_owner_context);

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
        request.skill_id < 0 ||
        !request.has_origin_transform ||
        !std::isfinite(request.origin_position_x) ||
        !std::isfinite(request.origin_position_y) ||
        !request.has_aim_angle ||
        !std::isfinite(request.aim_angle) ||
        !request.has_aim_target ||
        !std::isfinite(request.aim_target_x) ||
        !std::isfinite(request.aim_target_y) ||
        (request.has_cursor_world_placement &&
         (!IsSecondaryCursorWorldPlacementSkill(request.skill_id) ||
          !std::isfinite(request.cursor_world_x) ||
          !std::isfinite(request.cursor_world_y)))) {
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
    const auto aim_heading =
        NormalizeWizardActorHeadingForWrite(request.aim_angle);
    ApplyWizardActorFacingState(actor_address, aim_heading);
    binding->facing_heading_value = aim_heading;
    binding->facing_heading_valid = true;
    (void)memory.TryWriteField(
        actor_address,
        kActorAimTargetXOffset,
        request.aim_target_x);
    (void)memory.TryWriteField(
        actor_address,
        kActorAimTargetYOffset,
        request.aim_target_y);
    (void)memory.TryWriteField<std::uint32_t>(
        actor_address,
        kActorAimTargetAux0Offset,
        0);
    (void)memory.TryWriteField<std::uint32_t>(
        actor_address,
        kActorAimTargetAux1Offset,
        0);
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
    std::string stock_slot_context;
    std::string cast_origin_context;
    std::string cursor_world_placement_context;
    bool stock_slot_context_ok = false;
    bool cast_origin_context_ok = false;
    bool cursor_world_placement_context_ok = false;
    const auto turn_undead_precast_state =
        CaptureAuthoritativeTurnUndeadPrecastState(
            actor_address,
            request.skill_id);
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
                            stock_slot_context_ok =
                                InvokeWithStockSecondaryActorSlotZeroContext(
                                    actor_address,
                                    request.skill_id,
                                    [&] {
                                        cast_origin_context_ok =
                                            InvokeWithActorCastOriginContext(
                                                actor_address,
                                                request.origin_position_x,
                                                request.origin_position_y,
                                                [&] {
                                                    cursor_world_placement_context_ok =
                                                        InvokeWithSecondaryCursorWorldPlacementContext(
                                                            actor_address,
                                                            request.skill_id,
                                                            request.has_cursor_world_placement,
                                                            request.cursor_world_x,
                                                            request.cursor_world_y,
                                                            [&] {
                                                                invoked =
                                                                    InvokeOriginalPlayerActorSecondarySpellCast(
                                                                        actor_address,
                                                                        request.skill_id,
                                                                        &native_result);
                                                            },
                                                            &cursor_world_placement_context);
                                                },
                                                &cast_origin_context);
                                    },
                                    &stock_slot_context);
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

    const bool stock_effect_verification_required =
        RequiresStockSecondaryActorSlotZero(request.skill_id) &&
        request.target_actor_address != 0;
    bool stock_effect_verified = !stock_effect_verification_required;
    if (stock_effect_verification_required) {
        std::vector<SDModNativeModifierState> target_modifiers;
        stock_effect_verified =
            TryListNativeActorModifiers(
                request.target_actor_address,
                &target_modifiers) &&
            std::any_of(
                target_modifiers.begin(),
                target_modifiers.end(),
                [](const SDModNativeModifierState& modifier) {
                    return modifier.type_id ==
                               kNativePrismaticModifierTypeId &&
                           modifier.duration_ticks > 0;
                });
    }

    binding->ongoing_cast = ParticipantEntityBinding::OngoingCastState{};
    const bool native_success =
        invoked &&
        stock_slot_context_ok &&
        cast_origin_context_ok &&
        cursor_world_placement_context_ok &&
        stock_effect_verified &&
        (native_result != 0 ||
         IsRemoteNativeSecondaryToggleSkill(request.skill_id));
    RegisterAuthoritativeTurnUndeadCasterTargets(
        actor_address,
        binding->bot_id,
        turn_undead_precast_state,
        native_success);
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
        " stock_slot_context_ok=" +
            std::to_string(stock_slot_context_ok ? 1 : 0) +
        " stock_slot_context={" + stock_slot_context + "}" +
        " cast_origin_context_ok=" +
            std::to_string(cast_origin_context_ok ? 1 : 0) +
        " cast_origin_context={" + cast_origin_context + "}" +
        " cursor_world_placement_context_ok=" +
            std::to_string(cursor_world_placement_context_ok ? 1 : 0) +
        " cursor_world_placement_context={" +
            cursor_world_placement_context + "}" +
        " stock_effect_verification_required=" +
            std::to_string(stock_effect_verification_required ? 1 : 0) +
        " stock_effect_verified=" +
            std::to_string(stock_effect_verified ? 1 : 0) +
        " progression_owner_context={" + progression_owner_context + "}" +
        " player_actor_owner_context={" + player_actor_owner_context + "}");

    if (!native_success && error_message != nullptr) {
        if (!cast_origin_context_ok) {
            *error_message =
                "native remote secondary cast origin transaction failed";
        } else if (!cursor_world_placement_context_ok) {
            *error_message =
                "native remote secondary cursor-placement transaction failed";
        } else if (invoked && !stock_effect_verified) {
            *error_message =
                "native remote secondary cast did not apply its target modifier";
        } else {
            *error_message =
                invoked
                    ? "native remote secondary dispatcher rejected the cast"
                    : "native remote secondary dispatcher trampoline unavailable";
        }
    }
    return native_success;
}
