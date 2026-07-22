bool TryReadRollbackAimTargetFloat(
    uintptr_t actor_address,
    std::size_t offset,
    float fallback_value,
    float* value) {
    if (value == nullptr) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    float raw = 0.0f;
    if (actor_address == 0 ||
        !memory.TryReadField(actor_address, offset, &raw)) {
        *value = 0.0f;
        return false;
    }

    *value = std::isfinite(raw) ? raw : fallback_value;
    if (!std::isfinite(raw)) {
        (void)memory.TryWriteField(actor_address, offset, *value);
    }
    return true;
}

bool PreparePendingWizardBotCast(ParticipantEntityBinding* binding, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (binding == nullptr || binding->actor_address == 0 || binding->bot_id == 0 ||
        (!IsGameplaySlotWizardKind(binding->kind) &&
         !IsStandaloneWizardKind(binding->kind))) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto actor_address = binding->actor_address;
    constexpr float kRadiansToDegrees = 57.2957795130823208767981548141051703f;
    constexpr std::uint8_t kActorActiveCastGroupSentinel = 0xFF;
    const auto finish_attack_idle = [&]() {
        float heading = 0.0f;
        const bool heading_readable =
            TryReadFiniteFloatField(actor_address, kActorHeadingOffset, &heading);
        (void)multiplayer::FinishBotAttack(
            binding->bot_id,
            heading_readable,
            heading,
            true);
    };
    uintptr_t resolved_progression_runtime_address = 0;
    (void)TryResolveActorProgressionRuntime(
        actor_address,
        &resolved_progression_runtime_address);

    auto ApplyPreparedState = [&](ParticipantEntityBinding::OngoingCastState* ongoing) {
        if (ongoing == nullptr) {
            return;
        }

        if (ongoing->gameplay_selection_state_override_active &&
            binding->gameplay_slot >= 0) {
            const auto combat_selection_state = ResolveOngoingCastSelectionState(*ongoing);
            if (combat_selection_state >= 0) {
                std::string selection_error;
                (void)TryWriteActorAnimationStateIdDirect(actor_address, combat_selection_state);
                (void)TryWriteGameplaySelectionStateForSlot(
                    binding->gameplay_slot,
                    combat_selection_state,
                    &selection_error);
            }
        }
        if (ongoing->progression_spell_id_override_active && ongoing->progression_runtime_address != 0) {
            (void)memory.TryWriteField<std::int32_t>(
                ongoing->progression_runtime_address,
                kProgressionCurrentSpellIdOffset,
                ongoing->skill_id);
        }
        if (ongoing->have_aim_heading) {
            ApplyWizardActorFacingState(actor_address, ongoing->aim_heading);
        }
        if (ongoing->have_aim_target) {
            (void)memory.TryWriteField(actor_address, kActorAimTargetXOffset, ongoing->aim_target_x);
            (void)memory.TryWriteField(actor_address, kActorAimTargetYOffset, ongoing->aim_target_y);
            (void)memory.TryWriteField<std::uint32_t>(actor_address, kActorAimTargetAux0Offset, 0);
            (void)memory.TryWriteField<std::uint32_t>(actor_address, kActorAimTargetAux1Offset, 0);
        }
        (void)memory.TryWriteField<std::uint8_t>(actor_address, kActorCastSpreadModeByteOffset, 0);
        (void)memory.TryWriteField<std::int32_t>(
            actor_address,
            kActorPrimarySkillIdOffset,
            ongoing->uses_dispatcher_skill_id ? ongoing->dispatcher_skill_id : 0);
        (void)memory.TryWriteField<std::int32_t>(actor_address, kActorPreviousSkillIdOffset, 0);
    };

    auto RollbackPreparedStartup = [&](ParticipantEntityBinding::OngoingCastState* ongoing) {
        if (ongoing == nullptr) {
            return;
        }

        RestoreSelectionStateObjectAfterCast(*ongoing);
        RestoreSelectionBrainAfterCast(*ongoing);
        ClearSelectionBrainTarget(ongoing->selection_state_pointer);
        RestoreOngoingCastNativeTargetActor(actor_address, *ongoing);
        (void)memory.TryWriteField<float>(
            actor_address,
            kActorAimTargetXOffset,
            ongoing->aim_x_before);
        (void)memory.TryWriteField<float>(
            actor_address,
            kActorAimTargetYOffset,
            ongoing->aim_y_before);
        (void)memory.TryWriteField<std::uint32_t>(
            actor_address,
            kActorAimTargetAux0Offset,
            ongoing->aim_aux0_before);
        (void)memory.TryWriteField<std::uint32_t>(
            actor_address,
            kActorAimTargetAux1Offset,
            ongoing->aim_aux1_before);
        (void)memory.TryWriteField<std::uint8_t>(
            actor_address,
            kActorCastSpreadModeByteOffset,
            ongoing->spread_before);
        (void)memory.TryWriteField<std::int32_t>(
            actor_address,
            kActorPrimarySkillIdOffset,
            ongoing->primary_skill_id_before);
        (void)memory.TryWriteField<std::int32_t>(
            actor_address,
            kActorPreviousSkillIdOffset,
            ongoing->previous_skill_id_before);
        (void)memory.TryWriteField<std::uint32_t>(
            actor_address,
            kActorPrimaryActionLatchE4Offset,
            ongoing->primary_action_latch_e4_before);
        (void)memory.TryWriteField<std::uint32_t>(
            actor_address,
            kActorPrimaryActionLatchE8Offset,
            ongoing->primary_action_latch_e8_before);
        (void)memory.TryWriteField<std::uint8_t>(
            actor_address,
            kActorPostGateActiveByteOffset,
            ongoing->post_gate_active_before);
        binding->facing_target_actor_address = 0;
        if (ongoing->gameplay_selection_state_override_active &&
            binding->gameplay_slot >= 0 &&
            ongoing->gameplay_selection_state_before != kUnknownAnimationStateId) {
            std::string selection_error;
            if (ongoing->lane != ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary) {
                (void)TryWriteActorAnimationStateIdDirect(
                    actor_address,
                    ongoing->gameplay_selection_state_before);
            }
            (void)TryWriteGameplaySelectionStateForSlot(
                binding->gameplay_slot,
                ongoing->gameplay_selection_state_before,
                &selection_error);
        }
        if (ongoing->progression_spell_id_override_active &&
            ongoing->progression_runtime_address != 0) {
            (void)memory.TryWriteField<std::int32_t>(
                ongoing->progression_runtime_address,
                kProgressionCurrentSpellIdOffset,
                ongoing->progression_spell_id_before);
        }
        *ongoing = ParticipantEntityBinding::OngoingCastState{};
    };

    multiplayer::BotCastRequest request{};
    if (!multiplayer::ConsumePendingBotCast(binding->bot_id, &request)) {
        return false;
    }
    if (request.kind == multiplayer::BotCastKind::Secondary &&
        request.remote_input_controlled &&
        IsNativeRemoteParticipantBinding(binding)) {
        return ReplayPendingNativeSecondaryCast(
            binding,
            request,
            error_message);
    }
    const auto queued_target_actor_address = request.target_actor_address;
    if (request.has_origin_transform) {
        if (!std::isfinite(request.origin_position_x) ||
            !std::isfinite(request.origin_position_y) ||
            !memory.TryWriteField(actor_address, kActorPositionXOffset, request.origin_position_x) ||
            !memory.TryWriteField(actor_address, kActorPositionYOffset, request.origin_position_y)) {
            finish_attack_idle();
            if (error_message != nullptr) {
                *error_message = "origin transform write failed for bot cast";
            }
            return false;
        }

        DWORD rebind_exception_code = 0;
        if (!TryRebindActorToOwnerWorld(actor_address, &rebind_exception_code)) {
            Log(
                "[bots] cast origin rebind failed. bot_id=" +
                std::to_string(binding->bot_id) +
                " actor=" + HexString(actor_address) +
                " exception=" + HexString(rebind_exception_code));
        }
    }
    if (request.has_origin_heading && std::isfinite(request.origin_heading)) {
        ApplyWizardActorFacingState(actor_address, request.origin_heading);
    }
    int requested_skill_id = request.skill_id;
    ResolvedPrimaryCastDescriptor primary_descriptor{};
    bool have_primary_descriptor = false;
    if (request.kind == multiplayer::BotCastKind::Primary) {
        if (requested_skill_id <= 0) {
            if (!TryResolveProfilePrimaryCastDescriptor(
                    binding->character_profile,
                    resolved_progression_runtime_address,
                    &primary_descriptor)) {
                finish_attack_idle();
                if (error_message != nullptr) {
                    *error_message =
                        "primary cast has no stock loadout pair. primary=" +
                        std::to_string(primary_descriptor.primary_entry_index) +
                        " combo=" + std::to_string(primary_descriptor.combo_entry_index);
                }
                return false;
            }
            have_primary_descriptor = true;
            requested_skill_id =
                primary_descriptor.dispatcher_skill_id > 0
                    ? primary_descriptor.dispatcher_skill_id
                    : primary_descriptor.build_skill_id;
        } else if (TryResolvePrimaryCastDescriptorFromSkillId(
                       resolved_progression_runtime_address,
                       requested_skill_id,
                       &primary_descriptor)) {
            have_primary_descriptor = true;
            requested_skill_id =
                primary_descriptor.dispatcher_skill_id > 0
                    ? primary_descriptor.dispatcher_skill_id
                    : primary_descriptor.build_skill_id;
        }
    }
    if (requested_skill_id <= 0 &&
        (!have_primary_descriptor ||
         primary_descriptor.lane ==
             ParticipantEntityBinding::OngoingCastState::Lane::Dispatcher)) {
        finish_attack_idle();
        if (error_message != nullptr) {
            *error_message = "cast has no resolvable skill_id";
        }
        return false;
    }
    const auto combat_selection_state =
        have_primary_descriptor ? primary_descriptor.selection_state : -1;
    if (combat_selection_state < 0) {
        finish_attack_idle();
        if (error_message != nullptr) {
            *error_message = "unsupported gameplay-slot stock cast skill_id=" + std::to_string(requested_skill_id);
        }
        return false;
    }

    float aim_heading = 0.0f;
    bool have_aim_heading = false;
    float aim_target_x = 0.0f;
    float aim_target_y = 0.0f;
    bool have_aim_target = false;
    if (request.has_aim_target) {
        float actor_x = 0.0f;
        float actor_y = 0.0f;
        if (!TryReadFiniteFloatField(actor_address, kActorPositionXOffset, &actor_x) ||
            !TryReadFiniteFloatField(actor_address, kActorPositionYOffset, &actor_y)) {
            finish_attack_idle();
            if (error_message != nullptr) {
                *error_message = "actor position unreadable for bot cast aim";
            }
            return false;
        }
        const auto dx = request.aim_target_x - actor_x;
        const auto dy = request.aim_target_y - actor_y;
        if ((dx * dx) + (dy * dy) > 0.0001f) {
            aim_heading = std::atan2(dy, dx) * kRadiansToDegrees + 90.0f;
            if (aim_heading < 0.0f) {
                aim_heading += 360.0f;
            } else if (aim_heading >= 360.0f) {
                aim_heading -= 360.0f;
            }
            have_aim_heading = true;
        }
        aim_target_x = request.aim_target_x;
        aim_target_y = request.aim_target_y;
        have_aim_target = true;
    } else if (request.has_aim_angle && std::isfinite(request.aim_angle)) {
        aim_heading = request.aim_angle;
        have_aim_heading = true;
    }
    auto effective_target_actor_address =
        queued_target_actor_address != 0
            ? queued_target_actor_address
            : (request.remote_input_controlled ? 0 : binding->facing_target_actor_address);
    if (request.remote_input_controlled && queued_target_actor_address == 0) {
        binding->facing_target_actor_address = 0;
    }
    if (effective_target_actor_address != 0) {
        float live_target_x = 0.0f;
        float live_target_y = 0.0f;
        float live_target_heading = 0.0f;
        if (TryComputeActorAimTowardTarget(
                actor_address,
                effective_target_actor_address,
                &live_target_heading,
                &live_target_x,
                &live_target_y)) {
            binding->facing_target_actor_address = effective_target_actor_address;
            aim_heading = live_target_heading;
            have_aim_heading = true;
            aim_target_x = live_target_x;
            aim_target_y = live_target_y;
            have_aim_target = true;
        } else if (effective_target_actor_address != binding->facing_target_actor_address &&
                   binding->facing_target_actor_address != 0 &&
                   TryComputeActorAimTowardTarget(
                       actor_address,
                       binding->facing_target_actor_address,
                       &live_target_heading,
                       &live_target_x,
                       &live_target_y)) {
            effective_target_actor_address = binding->facing_target_actor_address;
            binding->facing_target_actor_address = effective_target_actor_address;
            aim_heading = live_target_heading;
            have_aim_heading = true;
            aim_target_x = live_target_x;
            aim_target_y = live_target_y;
            have_aim_target = true;
        }
    }

    if (!IsNativeRemoteParticipantBinding(binding) &&
        HasLuaSpellCastFilterHandlers()) {
        auto filter_context = CaptureLuaSpellCastFilterContext(
            actor_address,
            binding->bot_id,
            request.kind == multiplayer::BotCastKind::Primary
                ? LuaSpellCastKind::Primary
                : LuaSpellCastKind::Secondary,
            requested_skill_id,
            request.kind == multiplayer::BotCastKind::Secondary
                ? request.secondary_slot
                : -1);
        ApplyLuaSpellCastAimOverrides(
            have_aim_heading,
            aim_heading,
            have_aim_target,
            aim_target_x,
            aim_target_y,
            effective_target_actor_address,
            &filter_context);
        if (!ApplyLuaSpellCastFilters(filter_context)) {
            Log(
                "[lua] canceled owner-side bot spell cast. participant_id=" +
                std::to_string(binding->bot_id) +
                " actor=" + HexString(actor_address) +
                " skill_id=" + std::to_string(requested_skill_id));
            RetireCanceledOwnerBotSpellCast(binding);
            return true;
        }
    }

    auto& ongoing = binding->ongoing_cast;
    ongoing = ParticipantEntityBinding::OngoingCastState{};
    ongoing.active = true;
    ongoing.lane =
        have_primary_descriptor
            ? primary_descriptor.lane
            : ParticipantEntityBinding::OngoingCastState::Lane::Dispatcher;
    ongoing.remote_input_controlled = request.remote_input_controlled;
    ongoing.remote_input_cast_sequence = request.cast_sequence;
    ongoing.skill_id =
        have_primary_descriptor && primary_descriptor.build_skill_id > 0
            ? primary_descriptor.build_skill_id
            : requested_skill_id;
    ongoing.dispatcher_skill_id = requested_skill_id;
    ongoing.selection_state_target = combat_selection_state;
    ongoing.uses_dispatcher_skill_id =
        ongoing.lane == ParticipantEntityBinding::OngoingCastState::Lane::Dispatcher &&
        ongoing.dispatcher_skill_id > 0;
    ongoing.have_aim_heading = have_aim_heading;
    ongoing.aim_heading = aim_heading;
    ongoing.have_aim_target = have_aim_target;
    ongoing.aim_target_x = aim_target_x;
    ongoing.aim_target_y = aim_target_y;
    ongoing.target_actor_address = effective_target_actor_address;
    if (have_aim_heading) {
        binding->facing_heading_value = aim_heading;
        binding->facing_heading_valid = true;
    }
    float aim_x_fallback = have_aim_target && std::isfinite(aim_target_x) ? aim_target_x : 0.0f;
    float aim_y_fallback = have_aim_target && std::isfinite(aim_target_y) ? aim_target_y : 0.0f;
    float actor_x_for_rollback_aim = 0.0f;
    float actor_y_for_rollback_aim = 0.0f;
    if (TryReadFiniteFloatField(actor_address, kActorPositionXOffset, &actor_x_for_rollback_aim) &&
        TryReadFiniteFloatField(actor_address, kActorPositionYOffset, &actor_y_for_rollback_aim)) {
        aim_x_fallback = actor_x_for_rollback_aim;
        aim_y_fallback = actor_y_for_rollback_aim;
    }
    if (!TryReadFiniteFloatField(actor_address, kActorHeadingOffset, &ongoing.heading_before) ||
        !TryReadRollbackAimTargetFloat(
            actor_address,
            kActorAimTargetXOffset,
            aim_x_fallback,
            &ongoing.aim_x_before) ||
        !TryReadRollbackAimTargetFloat(
            actor_address,
            kActorAimTargetYOffset,
            aim_y_fallback,
            &ongoing.aim_y_before) ||
        !memory.TryReadField(actor_address, kActorAimTargetAux0Offset, &ongoing.aim_aux0_before) ||
        !memory.TryReadField(actor_address, kActorAimTargetAux1Offset, &ongoing.aim_aux1_before) ||
        !memory.TryReadField(actor_address, kActorCastSpreadModeByteOffset, &ongoing.spread_before) ||
        !memory.TryReadField(actor_address, kActorPrimarySkillIdOffset, &ongoing.primary_skill_id_before) ||
        !memory.TryReadField(actor_address, kActorPreviousSkillIdOffset, &ongoing.previous_skill_id_before) ||
        !memory.TryReadField(actor_address, kActorPrimaryActionLatchE4Offset, &ongoing.primary_action_latch_e4_before) ||
        !memory.TryReadField(actor_address, kActorPrimaryActionLatchE8Offset, &ongoing.primary_action_latch_e8_before) ||
        !memory.TryReadField(actor_address, kActorPostGateActiveByteOffset, &ongoing.post_gate_active_before) ||
        !memory.TryReadField(actor_address, kActorAnimationSelectionStateOffset, &ongoing.selection_state_pointer)) {
        ongoing = ParticipantEntityBinding::OngoingCastState{};
        finish_attack_idle();
        if (error_message != nullptr) {
            *error_message = "actor cast startup state unreadable";
        }
        return false;
    }
    if (ongoing.lane == ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary &&
        ongoing.selection_state_pointer != 0 &&
        memory.IsReadableRange(
            ongoing.selection_state_pointer,
            ongoing.selection_state_object_snapshot.size()) &&
        memory.TryRead(
            ongoing.selection_state_pointer,
            ongoing.selection_state_object_snapshot.data(),
            ongoing.selection_state_object_snapshot.size())) {
        ongoing.selection_state_object_snapshot_valid = true;
    }
    if (ongoing.selection_state_pointer != 0) {
        PrimeSelectionBrainForCastStartup(
            actor_address,
            ongoing.selection_state_pointer,
            effective_target_actor_address,
            &ongoing);
    }
    ongoing.selection_state_before = ResolveActorAnimationStateId(actor_address);
    if (binding->gameplay_slot >= 0 && ongoing.selection_state_before != kUnknownAnimationStateId) {
        ongoing.gameplay_selection_state_before = ongoing.selection_state_before;
        std::string selection_error;
        if (ongoing.lane != ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary) {
            (void)TryWriteActorAnimationStateIdDirect(actor_address, combat_selection_state);
        }
        ongoing.gameplay_selection_state_override_active =
            TryWriteGameplaySelectionStateForSlot(
                binding->gameplay_slot,
                combat_selection_state,
                &selection_error);
    }

    ongoing.progression_runtime_address = resolved_progression_runtime_address;
    if ((ongoing.progression_runtime_address != 0 ||
         TryResolveActorProgressionRuntime(actor_address, &ongoing.progression_runtime_address)) &&
        ongoing.progression_runtime_address != 0) {
        if (!memory.TryReadField(
                ongoing.progression_runtime_address,
                kProgressionCurrentSpellIdOffset,
                &ongoing.progression_spell_id_before)) {
            RollbackPreparedStartup(&ongoing);
            finish_attack_idle();
            if (error_message != nullptr) {
                *error_message = "progression spell id unreadable before bot cast";
            }
            return false;
        }
        if (request.kind == multiplayer::BotCastKind::Primary && request.skill_id <= 0) {
            int resolved_primary_skill_id = -1;
            std::string loadout_error;
            if (!ApplyProfilePrimaryLoadoutToSkillsWizard(
                    ongoing.progression_runtime_address,
                    binding->character_profile,
                    &resolved_primary_skill_id,
                    &loadout_error)) {
                RollbackPreparedStartup(&ongoing);
                finish_attack_idle();
                if (error_message != nullptr) {
                    *error_message = std::move(loadout_error);
                }
                return false;
            }
            const auto refresh_progression_address =
                memory.ResolveGameAddressOrZero(kActorProgressionRefresh);
            DWORD refresh_exception_code = 0;
            const bool refresh_succeeded =
                refresh_progression_address != 0 &&
                CallActorProgressionRefreshSafe(
                    refresh_progression_address,
                    actor_address,
                    &refresh_exception_code);
            if (!refresh_succeeded) {
                RollbackPreparedStartup(&ongoing);
                finish_attack_idle();
                if (error_message != nullptr) {
                    *error_message =
                        refresh_progression_address == 0
                            ? "Unable to resolve ActorProgressionRefresh."
                            : "Actor progression refresh (post primary build) failed with 0x" +
                                HexString(refresh_exception_code) + ".";
                }
                return false;
            }
            if (resolved_primary_skill_id > 0) {
                ongoing.skill_id = resolved_primary_skill_id;
            }
            if (ongoing.lane == ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary) {
                ongoing.progression_spell_id_override_active =
                    memory.TryWriteField<std::int32_t>(
                        ongoing.progression_runtime_address,
                        kProgressionCurrentSpellIdOffset,
                        ongoing.skill_id);
            }
        } else {
            ongoing.progression_spell_id_override_active =
                memory.TryWriteField<std::int32_t>(
                    ongoing.progression_runtime_address,
                    kProgressionCurrentSpellIdOffset,
                    ongoing.skill_id);
        }
    }
    const auto cast_mana =
        multiplayer::ResolveBotCastManaCost(
            binding->character_profile,
            ongoing.progression_runtime_address,
            request.kind,
            request.secondary_slot,
            ongoing.skill_id);
    if (!cast_mana.resolved) {
        Log(
            "[bots] mana rejected. bot_id=" + std::to_string(binding->bot_id) +
            " skill_id=" + std::to_string(ongoing.skill_id) +
            " kind=" + (request.kind == multiplayer::BotCastKind::Primary ? std::string("primary") : std::string("secondary")) +
            " slot=" + std::to_string(request.secondary_slot) +
            " mode=unknown");
        RollbackPreparedStartup(&ongoing);
        finish_attack_idle();
        if (error_message != nullptr) {
            *error_message = "unknown mana cost for bot cast";
        }
        return false;
    }
    ongoing.mana_charge_kind = cast_mana.kind;
    ongoing.mana_cost = cast_mana.cost;
    ongoing.mana_progression_level = cast_mana.progression_level;
    const bool remote_native_input_controlled =
        ongoing.remote_input_controlled && IsNativeRemoteParticipantBinding(binding);
    if (ongoing.remote_input_controlled &&
        ongoing.lane == ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary &&
        ongoing.mana_charge_kind == multiplayer::BotManaChargeKind::PerCast) {
        ongoing.remote_per_cast_projectile_expected_type =
            ExpectedPurePrimaryProjectileTypeForSelectionState(ongoing.selection_state_target);
        if (TryListPurePrimaryProjectileActorAddressesInScene(
                ongoing.remote_per_cast_projectile_expected_type,
                &ongoing.remote_per_cast_projectile_addresses_before)) {
            ongoing.remote_per_cast_projectile_baseline_valid = true;
            ongoing.remote_per_cast_projectile_count_before =
                static_cast<int>(ongoing.remote_per_cast_projectile_addresses_before.size());
        }
    }
    if (NativeManaRateConfigRequiredForOngoingCast(ongoing)) {
        ongoing.native_mana_rate_config_invalidated =
            ClearNativeManaRateConfigForOngoingCast(actor_address, ongoing);
    }
    Log(
        "[bots] mana prepared. bot_id=" + std::to_string(binding->bot_id) +
        " skill_id=" + std::to_string(ongoing.skill_id) +
        " kind=" + multiplayer::BotManaChargeKindLabel(cast_mana.kind) +
        " progression_level=" + std::to_string(cast_mana.progression_level) +
        " cost=" + std::to_string(cast_mana.cost) +
        " native_stat_cost=" + std::to_string(cast_mana.native_stat_cost) +
        " native_output_scale=" + std::to_string(cast_mana.native_output_scale) +
        " native_rate_config_invalidated=" +
            std::to_string(ongoing.native_mana_rate_config_invalidated ? 1 : 0) +
        " progression_runtime=" + HexString(ongoing.progression_runtime_address));
    if (cast_mana.kind != multiplayer::BotManaChargeKind::None) {
        if (ongoing.progression_runtime_address == 0) {
            RollbackPreparedStartup(&ongoing);
            finish_attack_idle();
            if (error_message != nullptr) {
                *error_message = "bot cast requires mana but has no progression runtime";
            }
            return false;
        }

        if (cast_mana.kind == multiplayer::BotManaChargeKind::PerCast && !remote_native_input_controlled) {
            float current_mp = 0.0f;
            float max_mp = 0.0f;
            bool mana_reserve_active = false;
            const bool mana_read =
                TryReadProgressionMana(ongoing.progression_runtime_address, &current_mp, &max_mp);
            const bool mana_reserve_refreshed =
                mana_read &&
                multiplayer::RefreshBotManaReserveState(
                    binding->bot_id,
                    current_mp,
                    max_mp,
                    &mana_reserve_active);
            if (!mana_read ||
                !mana_reserve_refreshed ||
                mana_reserve_active ||
                !multiplayer::CanBotManaStartCast(cast_mana, current_mp, max_mp)) {
                const std::string rejection_mode =
                    mana_reserve_active ? std::string("reserve") : std::string("per_cast");
                Log(
                    "[bots] mana rejected. bot_id=" + std::to_string(binding->bot_id) +
                    " skill_id=" + std::to_string(ongoing.skill_id) +
                    " kind=" + (request.kind == multiplayer::BotCastKind::Primary ? std::string("primary") : std::string("secondary")) +
                    " slot=" + std::to_string(request.secondary_slot) +
                    " mode=" + rejection_mode +
                    " cost=" + std::to_string(cast_mana.cost) +
                    " before=" + std::to_string(current_mp) +
                    " max=" + std::to_string(max_mp) +
                    " enter_ratio=" + std::to_string(multiplayer::kBotManaReserveEnterRatio) +
                    " exit_ratio=" + std::to_string(multiplayer::kBotManaReserveExitRatio));
                RollbackPreparedStartup(&ongoing);
                finish_attack_idle();
                if (error_message != nullptr) {
                    *error_message = "insufficient mana for bot cast";
                }
                return false;
            }
        } else if (!remote_native_input_controlled) {
            float current_mp = 0.0f;
            float max_mp = 0.0f;
            const float required_mana =
                multiplayer::ResolveBotManaRequiredToStart(cast_mana);
            bool mana_reserve_active = false;
            const bool mana_read =
                TryReadProgressionMana(ongoing.progression_runtime_address, &current_mp, &max_mp);
            const bool mana_reserve_refreshed =
                mana_read &&
                multiplayer::RefreshBotManaReserveState(
                    binding->bot_id,
                    current_mp,
                    max_mp,
                    &mana_reserve_active);
            if (!mana_read ||
                !mana_reserve_refreshed ||
                mana_reserve_active ||
                !multiplayer::CanBotManaStartCast(cast_mana, current_mp, max_mp)) {
                const std::string rejection_mode =
                    mana_reserve_active ? std::string("reserve") : std::string("per_second");
                Log(
                    "[bots] mana rejected. bot_id=" + std::to_string(binding->bot_id) +
                    " skill_id=" + std::to_string(ongoing.skill_id) +
                    " kind=" + (request.kind == multiplayer::BotCastKind::Primary ? std::string("primary") : std::string("secondary")) +
                    " slot=" + std::to_string(request.secondary_slot) +
                    " mode=" + rejection_mode +
                    " rate=" + std::to_string(cast_mana.cost) +
                    " required=" + std::to_string(required_mana) +
                    " before=" + std::to_string(current_mp) +
                    " max=" + std::to_string(max_mp) +
                    " enter_ratio=" + std::to_string(multiplayer::kBotManaReserveEnterRatio) +
                    " exit_ratio=" + std::to_string(multiplayer::kBotManaReserveExitRatio));
                RollbackPreparedStartup(&ongoing);
                finish_attack_idle();
                if (error_message != nullptr) {
                    *error_message = "insufficient mana for held bot cast";
                }
                return false;
            }
        }
    }
    ongoing.startup_in_progress = true;
    ongoing.startup_ticks_waiting = 0;
    if (ongoing.target_actor_address != 0) {
        (void)WriteOngoingCastNativeTargetActor(
            actor_address,
            &ongoing,
            ongoing.target_actor_address);
    }

    const auto cleanup_address = memory.ResolveGameAddressOrZero(kCastActiveHandleCleanup);
    std::uint8_t active_cast_group_before = kActorActiveCastGroupSentinel;
    if (!memory.TryReadField(actor_address, kActorActiveCastGroupByteOffset, &active_cast_group_before)) {
        RollbackPreparedStartup(&ongoing);
        finish_attack_idle();
        if (error_message != nullptr) {
            *error_message = "native active-cast group unreadable before bot cast";
        }
        return false;
    }
    if (cleanup_address != 0 && active_cast_group_before != kActorActiveCastGroupSentinel) {
        DWORD cleanup_exception_code = 0;
        bool cleanup_ok = false;
        std::string cleanup_owner_context;
        InvokeWithBotProgressionSlotOwnerContext(
            actor_address,
            true,
            [&] {
                cleanup_ok =
                    CallCastActiveHandleCleanupSafe(cleanup_address, actor_address, &cleanup_exception_code);
            },
            &cleanup_owner_context);
        if (!cleanup_ok) {
            RollbackPreparedStartup(&ongoing);
            finish_attack_idle();
            if (error_message != nullptr) {
                *error_message =
                    "prior native active-handle cleanup failed with " +
                    HexString(cleanup_exception_code);
            }
            return false;
        }
        Log(
            "[bots] pre-start native cleanup owner context. bot_id=" +
            std::to_string(binding->bot_id) +
            " actor=" + HexString(actor_address) +
            " standalone_slot_owner_context={" + cleanup_owner_context + "}");
    }

    ApplyPreparedState(&ongoing);
    bool pure_primary_primer_called = false;
    DWORD pure_primary_primer_exception = 0;
    const bool dispatcher_primary_uses_primer =
        have_primary_descriptor &&
        ongoing.uses_dispatcher_skill_id &&
        !OngoingCastRequiresBoundedHeldCastInputDuringNativeTick(ongoing);
    const bool should_run_primary_damage_primer =
        request.kind == multiplayer::BotCastKind::Primary &&
        (ongoing.lane == ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary ||
         dispatcher_primary_uses_primer);
    if (should_run_primary_damage_primer) {
        const auto pure_primary_start_address =
            memory.ResolveGameAddressOrZero(kSpellCastPurePrimary);
        if (pure_primary_start_address != 0) {
            std::string primer_owner_context;
            const bool pure_primary_bot_owner_context =
                ongoing.lane == ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary ||
                IsStandaloneWizardKind(binding->kind);
            InvokeWithBotProgressionSlotOwnerContext(
                actor_address,
                pure_primary_bot_owner_context,
                [&] {
                    pure_primary_primer_called =
                        CallPurePrimarySpellStartSafe(
                            pure_primary_start_address,
                            actor_address,
                            &pure_primary_primer_exception);
                },
                &primer_owner_context);
            Log(
                "[bots] pure primary primer owner context. bot_id=" +
                std::to_string(binding->bot_id) +
                " actor=" + HexString(actor_address) +
                " standalone_slot_owner_context={" + primer_owner_context + "}");
        }
        if (pure_primary_primer_called && ongoing.uses_dispatcher_skill_id) {
            PrimeGameplaySlotPostGateDispatchState(actor_address, ongoing);
            if (ongoing.target_actor_address != 0) {
                (void)WriteOngoingCastNativeTargetActor(
                    actor_address,
                    &ongoing,
                    ongoing.target_actor_address);
            }
            ReapplyOngoingCastSelectionState(binding, actor_address, ongoing, true);
        }
    }
    if constexpr (kEnableWizardBotHotPathDiagnostics) {
        g_gameplay_slot_hud_probe_actor = actor_address;
        g_gameplay_slot_hud_probe_until_ms = static_cast<std::uint64_t>(GetTickCount64()) + 400;
    }
    std::int32_t progression_spell_id_for_log = 0;
    const auto progression_spell_id_text =
        ongoing.progression_runtime_address != 0 &&
                memory.TryReadField(
                    ongoing.progression_runtime_address,
                    kProgressionCurrentSpellIdOffset,
                    &progression_spell_id_for_log)
            ? std::to_string(progression_spell_id_for_log)
            : std::string("unreadable");
    Log(
        "[bots] wizard cast prepped. bot_id=" + std::to_string(binding->bot_id) +
        " kind=" +
            (IsGameplaySlotWizardKind(binding->kind)
                 ? std::string("gameplay_slot")
                 : std::string("standalone")) +
        " gameplay_slot=" + std::to_string(binding->gameplay_slot) +
        " skill_id=" + std::to_string(ongoing.skill_id) +
        " remote_input_controlled=" +
            (ongoing.remote_input_controlled ? std::string("1") : std::string("0")) +
        " remote_cast_sequence=" + std::to_string(ongoing.remote_input_cast_sequence) +
        " dispatcher_skill_id=" + std::to_string(ongoing.dispatcher_skill_id) +
        " lane=" +
            (ongoing.lane == ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary
                 ? std::string("pure_primary")
                 : std::string("dispatcher")) +
        " selection_state=" + std::to_string(combat_selection_state) +
        " progression_runtime=" + HexString(ongoing.progression_runtime_address) +
        " progression_spell_id=" + progression_spell_id_text +
        " pure_primary_primer=" + std::to_string(pure_primary_primer_called ? 1 : 0) +
        " pure_primary_primer_seh=" + HexString(pure_primary_primer_exception) +
        " selection_ptr=" + HexString(ongoing.selection_state_pointer) +
        " startup={" + DescribeGameplaySlotCastStartupWindow(actor_address) + "}");
    return true;
}

// Cast architecture (standalone verified 2026-04-20; gameplay-slot fix 2026-04-21):
//
//   * Player flow: input sets actor+0x270 (primary skill id); PlayerActorTick
//     (0x00548B00) calls FUN_00548A00 every gameplay tick; FUN_00548A00 routes
//     by actor+0x270 to the selected per-spell handler.
//     The handler owns a cached spell-object handle stored at actor+0x27C
//     (group byte) + actor+0x27E (world slot short). It latches cast-active
//     state via actor+0x160 (animation_drive_state) and actor+0x1EC
//     (mNoInterrupt). When the handler decides the cast is done it clears
//     both latch fields. PlayerActorTick's skill-transition block
//     (0x5496e5..0x5497ac) then calls FUN_0052F3B0 on skill change to release
//     the spell-object handle (sets +0x27C=0xFF, +0x27E=0xFFFF).
//
//   * Per-spell handler init gate: `(actor+0x5C == 0) && (actor+0x27C == 0xFF)`.
//     FUN_0052F3B0 cleanup shares the slot==0 early-out. Standalone clone-rail
//     bots inherit slot 0 from the source player actor so the gate passes
//     naturally; gameplay-slot bots carry their true slot (1/2/3) in
    //     actor+0x5C. The loader now unlocks the recovered native branch gates,
    //     so the handlers keep actor+0x5C pointed at the real gameplay slot and
    //     read that slot's live progression handle.
//
//   * Bot flow (this function): PlayerActorTick still runs for the bot actor
//     via `original(self)` in the tick hook, so FUN_00548A00 keeps driving
//     the per-spell handler natively. Our job is (a) initiate the cast by
//     setting aim + actor+0x270 + a primer dispatch; (b) each subsequent tick
    //     keeps stock input held only for native-held primaries; (c) bounded held
    //     primaries release synthetic input when native charge reaches the chosen
    //     release point, let the live world object update, then invoke the stock
    //     active-handle cleanup so native damage/effect code remains authoritative.
    //     kMaxTicksWaiting is a safety cap against unexpected latch states, not a
