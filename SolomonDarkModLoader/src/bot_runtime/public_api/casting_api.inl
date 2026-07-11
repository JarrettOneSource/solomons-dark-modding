bool QueueBotCast(const BotCastRequest& request) {
    std::scoped_lock lock(g_bot_runtime_mutex);
    if (!g_bot_runtime_initialized) {
        Log(
            "[bots] cast queue rejected; runtime not initialized. bot_id=" +
            std::to_string(request.bot_id) +
            " skill_id=" + std::to_string(request.skill_id) +
            " cast_sequence=" + std::to_string(request.cast_sequence) +
            " remote_input_controlled=" +
            (request.remote_input_controlled ? std::string("1") : std::string("0")));
        return false;
    }
    if (!IsValidCastRequest(request)) {
        Log(
            "[bots] cast queue rejected; invalid request. bot_id=" +
            std::to_string(request.bot_id) +
            " skill_id=" + std::to_string(request.skill_id) +
            " kind=" + (request.kind == BotCastKind::Primary ? std::string("primary") : std::string("secondary")) +
            " slot=" + std::to_string(request.secondary_slot) +
            " cast_sequence=" + std::to_string(request.cast_sequence) +
            " remote_input_controlled=" +
            (request.remote_input_controlled ? std::string("1") : std::string("0")));
        return false;
    }

    const RuntimeState runtime = SnapshotRuntimeState();
    const auto* participant = FindParticipant(runtime, request.bot_id);
    if (participant == nullptr) {
        Log(
            "[bots] cast queue rejected; participant missing. bot_id=" +
            std::to_string(request.bot_id) +
            " skill_id=" + std::to_string(request.skill_id) +
            " cast_sequence=" + std::to_string(request.cast_sequence) +
            " remote_input_controlled=" +
            (request.remote_input_controlled ? std::string("1") : std::string("0")));
        return false;
    }
    if (!IsLuaControlledParticipant(*participant) &&
        !(IsRemoteParticipant(*participant) && IsNativeControlledParticipant(*participant))) {
        Log(
            "[bots] cast queue rejected; participant is not cast controlled. bot_id=" +
            std::to_string(request.bot_id) +
            " kind=" + std::to_string(static_cast<int>(participant->kind)) +
            " controller=" + std::to_string(static_cast<int>(participant->controller_kind)) +
            " skill_id=" + std::to_string(request.skill_id) +
            " cast_sequence=" + std::to_string(request.cast_sequence) +
            " remote_input_controlled=" +
            (request.remote_input_controlled ? std::string("1") : std::string("0")));
        return false;
    }
    if (IsParticipantRuntimeDead(*participant)) {
        ClearDeadBotControlsLocked(*participant);
        RemoveBotCastInput(request.bot_id);
        Log(
            "[bots] cast queue rejected; participant runtime dead. bot_id=" +
            std::to_string(request.bot_id) +
            " skill_id=" + std::to_string(request.skill_id) +
            " cast_sequence=" + std::to_string(request.cast_sequence) +
            " remote_input_controlled=" +
            (request.remote_input_controlled ? std::string("1") : std::string("0")));
        return false;
    }
    const bool remote_native_participant =
        IsRemoteParticipant(*participant) && IsNativeControlledParticipant(*participant);
    const bool remote_native_input_controlled =
        remote_native_participant && request.remote_input_controlled;

    SDModParticipantGameplayState refreshed_gameplay_state{};
    (void)TryRefreshParticipantGameplayState(request.bot_id, &refreshed_gameplay_state);
    BotSnapshot live_snapshot{};
    FillBotSnapshot(*participant, &live_snapshot);
    ApplyGameplayStateToSnapshot(request.bot_id, &live_snapshot);
    if (remote_native_participant) {
        RemoveBotManaReserveState(request.bot_id);
        live_snapshot.mana_reserve_active = false;
    } else {
        ApplyManaReserveStateToSnapshot(&live_snapshot);
    }
    if (live_snapshot.native_action_cooldown_ticks > 0 && !remote_native_participant) {
        Log(
            "[bots] cast rejected for native action cooldown. bot_id=" +
            std::to_string(request.bot_id) +
            " ticks=" + std::to_string(live_snapshot.native_action_cooldown_ticks));
        return false;
    }
    const bool live_progression_available =
        live_snapshot.progression_runtime_state_address != 0;
    auto resolve_rejected_skill_id = [&]() -> std::int32_t {
        std::int32_t rejected_skill_id = request.skill_id;
        if (request.kind == BotCastKind::Primary && rejected_skill_id <= 0) {
            NativePrimarySpellSelection selection{};
            const auto default_entry =
                ResolveNativePrimaryEntryForElement(participant->character_profile.element_id);
            const auto primary_entry =
                participant->character_profile.loadout.primary_entry_index >= 0
                    ? participant->character_profile.loadout.primary_entry_index
                    : default_entry;
            const auto combo_entry =
                participant->character_profile.loadout.primary_combo_entry_index >= 0
                    ? participant->character_profile.loadout.primary_combo_entry_index
                    : primary_entry;
            std::string selection_error;
            if (TryResolveNativePrimarySelectionFromLiveProgression(
                    live_snapshot.progression_runtime_state_address,
                    primary_entry,
                    combo_entry,
                    &selection,
                    &selection_error) ||
                TryResolveNativePrimarySelectionForProfile(
                    participant->character_profile,
                    &selection)) {
                rejected_skill_id = selection.build_skill_id;
            }
        }
        return rejected_skill_id;
    };
    if (live_snapshot.entity_materialized &&
        (live_snapshot.max_mp > 0.0f || live_progression_available) &&
        live_snapshot.mana_reserve_active &&
        !remote_native_input_controlled) {
        Log(
            "[bots] cast rejected for mana reserve. bot_id=" + std::to_string(request.bot_id) +
            " skill_id=" + std::to_string(resolve_rejected_skill_id()) +
            " kind=" + (request.kind == BotCastKind::Primary ? std::string("primary") : std::string("secondary")) +
            " slot=" + std::to_string(request.secondary_slot) +
            " mode=reserve before=" + std::to_string(live_snapshot.mp) +
            " max=" + std::to_string(live_snapshot.max_mp) +
            " enter_ratio=" + std::to_string(kBotManaReserveEnterRatio) +
            " exit_ratio=" + std::to_string(kBotManaReserveExitRatio));
        return false;
    }
    if (live_snapshot.entity_materialized &&
        (live_snapshot.max_mp > 0.0f || live_progression_available) &&
        live_snapshot.mp <= kBotManaReadinessEpsilon &&
        !remote_native_input_controlled) {
        Log(
            "[bots] cast rejected for mana. bot_id=" + std::to_string(request.bot_id) +
            " skill_id=" + std::to_string(resolve_rejected_skill_id()) +
            " kind=" + (request.kind == BotCastKind::Primary ? std::string("primary") : std::string("secondary")) +
            " slot=" + std::to_string(request.secondary_slot) +
            " mode=unavailable before=" + std::to_string(live_snapshot.mp) +
            " max=" + std::to_string(live_snapshot.max_mp));
        return false;
    }

    const auto* previous_intent = FindPendingMovementIntent(request.bot_id);
    const bool have_transform = participant->runtime.transform_valid;
    const float current_x = participant->runtime.position_x;
    const float current_y = participant->runtime.position_y;
    const float current_heading =
        have_transform ? participant->runtime.heading
                       : (previous_intent != nullptr && previous_intent->desired_heading_valid
                              ? previous_intent->desired_heading
                              : 0.0f);
    bool desired_heading_valid =
        previous_intent != nullptr && previous_intent->desired_heading_valid;
    float desired_heading =
        desired_heading_valid ? previous_intent->desired_heading : current_heading;

    if (request.has_aim_target && have_transform) {
        const auto delta_x = request.aim_target_x - current_x;
        const auto delta_y = request.aim_target_y - current_y;
        if ((delta_x * delta_x) + (delta_y * delta_y) > 0.0001f) {
            desired_heading_valid = true;
            desired_heading = NormalizeHeadingDegrees(
                static_cast<float>(
                    std::atan2(delta_y, delta_x) * (180.0 / 3.14159265358979323846) + 90.0));
        }
    } else if (request.has_aim_angle && std::isfinite(request.aim_angle)) {
        desired_heading_valid = true;
        desired_heading = NormalizeHeadingDegrees(request.aim_angle);
    } else if (have_transform) {
        desired_heading_valid = true;
        desired_heading = NormalizeHeadingDegrees(current_heading);
    }

    bool queued = false;
    const auto now_ms = GetTickCount64();
    UpdateRuntimeState([&](RuntimeState& state) {
        const auto* live_participant = FindParticipant(state, request.bot_id);
        if (live_participant == nullptr ||
            (!IsLuaControlledParticipant(*live_participant) &&
             !(IsRemoteParticipant(*live_participant) && IsNativeControlledParticipant(*live_participant)))) {
            return;
        }

        auto* pending_cast = FindPendingCast(request.bot_id);
        if (pending_cast == nullptr) {
            g_pending_casts.push_back(PendingBotCast{});
            pending_cast = &g_pending_casts.back();
            pending_cast->bot_id = request.bot_id;
        }
        pending_cast->kind = request.kind;
        pending_cast->secondary_slot = request.secondary_slot;
        pending_cast->skill_id = request.skill_id;
        pending_cast->cast_sequence = request.cast_sequence;
        pending_cast->remote_input_controlled = request.remote_input_controlled;
        pending_cast->target_actor_address = request.target_actor_address;
        pending_cast->has_origin_transform = request.has_origin_transform;
        pending_cast->origin_position_x = request.origin_position_x;
        pending_cast->origin_position_y = request.origin_position_y;
        pending_cast->has_origin_heading = request.has_origin_heading;
        pending_cast->origin_heading = request.origin_heading;
        pending_cast->has_aim_target = request.has_aim_target;
        pending_cast->aim_target_x = request.aim_target_x;
        pending_cast->aim_target_y = request.aim_target_y;
        pending_cast->has_aim_angle = request.has_aim_angle;
        pending_cast->aim_angle = request.aim_angle;
        pending_cast->queued_cast_count = g_next_cast_sequence++;
        pending_cast->queued_at_ms = now_ms;
        if (request.remote_input_controlled) {
            auto* input = FindBotCastInput(request.bot_id);
            if (input == nullptr) {
                g_bot_cast_inputs.push_back(PendingBotCastInput{});
                input = &g_bot_cast_inputs.back();
                input->bot_id = request.bot_id;
            }
            input->state.bot_id = request.bot_id;
            input->state.active = true;
            input->state.release_requested = false;
            input->state.cast_sequence = request.cast_sequence;
            input->state.last_update_ms = now_ms;
            input->state.has_aim_target = request.has_aim_target;
            input->state.aim_target_x = request.aim_target_x;
            input->state.aim_target_y = request.aim_target_y;
            input->state.has_aim_angle = request.has_aim_angle;
            input->state.aim_angle = request.aim_angle;
            input->state.target_actor_address = request.target_actor_address;
        }
        SetPendingFaceTargetLocked(request.bot_id, request.target_actor_address);
        if (desired_heading_valid) {
            SetPendingFaceHeadingLocked(request.bot_id, true, desired_heading, 0);
        }
        queued = true;
    });

    if (queued) {
        Log(
            "[bots] queued cast for bot id=" + std::to_string(request.bot_id) +
            " facing_preserved=" + std::to_string(desired_heading_valid ? 1 : 0));
    } else {
        Log(
            "[bots] cast queue rejected; participant vanished during state update. bot_id=" +
            std::to_string(request.bot_id) +
            " skill_id=" + std::to_string(request.skill_id) +
            " cast_sequence=" + std::to_string(request.cast_sequence) +
            " remote_input_controlled=" +
            (request.remote_input_controlled ? std::string("1") : std::string("0")));
    }

    return queued;
}

bool UpdateBotCastInput(const BotCastInputState& input_state) {
    std::scoped_lock lock(g_bot_runtime_mutex);
    if (!g_bot_runtime_initialized ||
        input_state.bot_id == 0 ||
        input_state.cast_sequence == 0 ||
        (input_state.has_aim_target &&
         (!std::isfinite(input_state.aim_target_x) ||
          !std::isfinite(input_state.aim_target_y))) ||
        (input_state.has_aim_angle && !std::isfinite(input_state.aim_angle))) {
        return false;
    }

    const RuntimeState runtime = SnapshotRuntimeState();
    const auto* participant = FindParticipant(runtime, input_state.bot_id);
    if (participant == nullptr ||
        (!IsLuaControlledParticipant(*participant) &&
         !(IsRemoteParticipant(*participant) && IsNativeControlledParticipant(*participant)))) {
        return false;
    }
    if (IsParticipantRuntimeDead(*participant)) {
        RemoveBotCastInput(input_state.bot_id);
        return false;
    }

    auto* existing = FindBotCastInput(input_state.bot_id);
    if (existing != nullptr &&
        existing->state.cast_sequence != 0 &&
        static_cast<std::int32_t>(input_state.cast_sequence - existing->state.cast_sequence) < 0) {
        return false;
    }
    if (existing == nullptr) {
        g_bot_cast_inputs.push_back(PendingBotCastInput{});
        existing = &g_bot_cast_inputs.back();
        existing->bot_id = input_state.bot_id;
    }

    existing->state = input_state;
    existing->state.bot_id = input_state.bot_id;
    if (existing->state.last_update_ms == 0) {
        existing->state.last_update_ms = GetTickCount64();
    }
    if (existing->state.release_requested) {
        existing->state.active = false;
    }
    SetPendingFaceTargetLocked(input_state.bot_id, input_state.target_actor_address);
    if (input_state.has_aim_angle) {
        SetPendingFaceHeadingLocked(
            input_state.bot_id,
            true,
            NormalizeHeadingDegrees(input_state.aim_angle),
            0);
    }
    return true;
}

bool ReadBotCastInputState(std::uint64_t bot_id, BotCastInputState* input_state) {
    if (input_state == nullptr || bot_id == 0) {
        return false;
    }

    std::scoped_lock lock(g_bot_runtime_mutex);
    if (!g_bot_runtime_initialized) {
        return false;
    }

    const auto* existing = FindBotCastInput(bot_id);
    if (existing == nullptr) {
        return false;
    }
    *input_state = existing->state;
    return true;
}

bool ClearBotCastInput(std::uint64_t bot_id, std::uint32_t cast_sequence) {
    if (bot_id == 0) {
        return false;
    }

    std::scoped_lock lock(g_bot_runtime_mutex);
    if (!g_bot_runtime_initialized) {
        return false;
    }

    const auto* existing = FindBotCastInput(bot_id);
    if (existing == nullptr) {
        return false;
    }
    if (cast_sequence != 0 &&
        existing->state.cast_sequence != 0 &&
        existing->state.cast_sequence != cast_sequence) {
        return false;
    }
    RemoveBotCastInput(bot_id);
    return true;
}

BotManaCost ResolveBotCastManaCost(
    const MultiplayerCharacterProfile& character_profile,
    uintptr_t progression_runtime_address,
    BotCastKind kind,
    std::int32_t secondary_slot,
    std::int32_t skill_id) {
    NativePrimarySpellSelection selection{};
    bool selection_resolved = false;

    if (kind == BotCastKind::Primary) {
        if (skill_id > 0) {
            selection_resolved =
                TryResolveNativePrimarySelectionFromSkillId(
                    progression_runtime_address,
                    skill_id,
                    &selection);
            if (!selection_resolved) {
                selection_resolved =
                    TryResolveNativePrimarySelectionFromPair(
                        skill_id,
                        skill_id,
                        &selection);
            }
        } else {
            const auto default_entry =
                ResolveNativePrimaryEntryForElement(character_profile.element_id);
            const auto primary_entry =
                character_profile.loadout.primary_entry_index >= 0
                    ? character_profile.loadout.primary_entry_index
                    : default_entry;
            const auto combo_entry =
                character_profile.loadout.primary_combo_entry_index >= 0
                    ? character_profile.loadout.primary_combo_entry_index
                    : primary_entry;
            std::string selection_error;
            selection_resolved =
                TryResolveNativePrimarySelectionFromLiveProgression(
                    progression_runtime_address,
                    primary_entry,
                    combo_entry,
                    &selection,
                    &selection_error) ||
                TryResolveNativePrimarySelectionForProfile(character_profile, &selection);
        }
    } else {
        const auto resolved_secondary_skill_id =
            skill_id > 0
                ? skill_id
                : (secondary_slot >= 0 &&
                           secondary_slot <
                               static_cast<std::int32_t>(
                                   character_profile.loadout.secondary_entry_indices.size())
                       ? character_profile.loadout.secondary_entry_indices[
                             static_cast<std::size_t>(secondary_slot)]
                       : -1);
        if (resolved_secondary_skill_id > 0) {
            selection_resolved =
                TryResolveNativePrimarySelectionFromSkillId(
                    progression_runtime_address,
                    resolved_secondary_skill_id,
                    &selection);
        }
    }

    if (!selection_resolved) {
        Log(
            "[bots] cast mana unresolved; spell selection is not a native primary. requested_skill_id=" +
            std::to_string(skill_id) +
            " kind=" + (kind == BotCastKind::Primary ? std::string("primary") : std::string("secondary")) +
            " slot=" + std::to_string(secondary_slot));
        return BotManaCost{};
    }

    NativePrimarySpellStats stats{};
    std::string error_message;
    if (!TryResolveNativePrimarySpellStats(
            progression_runtime_address,
            selection,
            &stats,
            &error_message) ||
        !stats.mana_cost_available ||
        !stats.mana_spend_cost_available) {
        Log(
            "[bots] failed to resolve native spell mana. progression=" +
            HexString(progression_runtime_address) +
            " skill_id=" + std::to_string(selection.build_skill_id) +
            " primary_entry=" + std::to_string(selection.primary_entry_index) +
            " combo_entry=" + std::to_string(selection.combo_entry_index) +
            " error=" + error_message);
        return BotManaCost{};
    }
    if (!std::isfinite(stats.mana_spend_cost) || stats.mana_spend_cost <= 0.0f) {
        Log(
            "[bots] failed to resolve native spell mana. progression=" +
            HexString(progression_runtime_address) +
            " skill_id=" + std::to_string(selection.build_skill_id) +
            " primary_entry=" + std::to_string(selection.primary_entry_index) +
            " combo_entry=" + std::to_string(selection.combo_entry_index) +
            " error=native mana spend cost is not positive; spell is unavailable or unlevelled" +
            " native_stat_cost=" + std::to_string(stats.mana_cost) +
            " native_output_scale=" + std::to_string(stats.mana_output_scale));
        return BotManaCost{};
    }

    BotManaCost cost{};
    cost.resolved = true;
    cost.kind =
        selection.per_second_mana ? BotManaChargeKind::PerSecond : BotManaChargeKind::PerCast;
    cost.cost = stats.mana_spend_cost;
    cost.native_stat_cost = stats.mana_cost;
    cost.native_output_scale = stats.mana_output_scale;
    cost.progression_level = stats.progression_level;
    cost.skill_id = stats.current_spell_id > 0 ? stats.current_spell_id : selection.build_skill_id;
    return cost;
}

float ResolveBotManaRequiredToStart(const BotManaCost& cost) {
    switch (cost.kind) {
    case BotManaChargeKind::PerCast:
        return cost.cost;
    case BotManaChargeKind::PerSecond:
        return cost.cost;
    case BotManaChargeKind::None:
    default:
        return 0.0f;
    }
}

bool CanBotManaStartCast(const BotManaCost& cost, float current_mp, float max_mp) {
    if (cost.kind == BotManaChargeKind::None) {
        return true;
    }
    if (!std::isfinite(current_mp) || !std::isfinite(max_mp) || max_mp <= 0.0f) {
        return false;
    }

    switch (cost.kind) {
    case BotManaChargeKind::PerCast:
    case BotManaChargeKind::PerSecond:
        return current_mp + kBotManaReadinessEpsilon >=
               ResolveBotManaRequiredToStart(cost);
    case BotManaChargeKind::None:
    default:
        return true;
    }
}

bool RefreshBotManaReserveState(
    std::uint64_t bot_id,
    float current_mp,
    float max_mp,
    bool* reserve_active) {
    if (reserve_active != nullptr) {
        *reserve_active = false;
    }

    std::scoped_lock lock(g_bot_runtime_mutex);
    if (!g_bot_runtime_initialized || bot_id == 0) {
        return false;
    }

    const bool active = UpdateBotManaReserveStateLocked(bot_id, current_mp, max_mp);
    if (reserve_active != nullptr) {
        *reserve_active = active;
    }
    return true;
}

const char* BotManaChargeKindLabel(BotManaChargeKind kind) {
    switch (kind) {
    case BotManaChargeKind::PerCast:
        return "per_cast";
    case BotManaChargeKind::PerSecond:
        return "per_second";
    case BotManaChargeKind::None:
    default:
        return "none";
    }
}

bool FinishBotAttack(
    std::uint64_t bot_id,
    bool desired_heading_valid,
    float desired_heading,
    bool clear_face_target) {
    std::scoped_lock lock(g_bot_runtime_mutex);
    if (!g_bot_runtime_initialized || bot_id == 0) {
        return false;
    }

    bool bot_exists = false;
    UpdateRuntimeState([&](RuntimeState& state) {
        bot_exists = FindBot(state, bot_id) != nullptr;
    });
    if (!bot_exists) {
        return false;
    }

    const auto* previous_intent = FindPendingMovementIntent(bot_id);
    if (!desired_heading_valid &&
        previous_intent != nullptr &&
        previous_intent->desired_heading_valid) {
        desired_heading_valid = true;
        desired_heading = previous_intent->desired_heading;
    }
    if (desired_heading_valid) {
        desired_heading = NormalizeHeadingDegrees(desired_heading);
    }
    if (clear_face_target) {
        SetPendingFaceTargetLocked(bot_id, 0);
    }

    if (previous_intent != nullptr &&
        previous_intent->state == BotControllerState::Moving &&
        previous_intent->has_target) {
        if (desired_heading_valid) {
            SetPendingFaceHeadingLocked(bot_id, true, desired_heading, 0);
        }
        Log(
            "[bots] settled attack controller id=" + std::to_string(bot_id) +
            " movement_preserved=1 heading_valid=" + std::to_string(desired_heading_valid ? 1 : 0) +
            (desired_heading_valid ? " heading=" + std::to_string(desired_heading) : std::string("")));
        return true;
    }

    const bool changed =
        previous_intent == nullptr ||
        previous_intent->state != BotControllerState::Idle ||
        previous_intent->has_target ||
        previous_intent->desired_heading_valid != desired_heading_valid ||
        (desired_heading_valid &&
         (!previous_intent->desired_heading_valid ||
          std::fabs(previous_intent->desired_heading - desired_heading) > 0.01f));
    SchedulePendingMovementIntentLocked(
        bot_id,
        BotControllerState::Idle,
        false,
        0.0f,
        0.0f,
        desired_heading_valid,
        desired_heading);
    if (changed) {
        Log(
            "[bots] settled attack controller id=" + std::to_string(bot_id) +
            " state=idle heading_valid=" + std::to_string(desired_heading_valid ? 1 : 0) +
            (desired_heading_valid ? " heading=" + std::to_string(desired_heading) : std::string("")));
    }
    return true;
}

bool ConsumePendingBotCast(std::uint64_t bot_id, BotCastRequest* request) {
    if (request == nullptr || bot_id == 0) {
        return false;
    }

    std::scoped_lock lock(g_bot_runtime_mutex);
    if (!g_bot_runtime_initialized) {
        return false;
    }

    auto* pending_cast = FindPendingCast(bot_id);
    if (pending_cast == nullptr) {
        return false;
    }

    *request = BotCastRequest{};
    request->bot_id = pending_cast->bot_id;
    request->kind = pending_cast->kind;
    request->secondary_slot = pending_cast->secondary_slot;
    request->skill_id = pending_cast->skill_id;
    request->cast_sequence = pending_cast->cast_sequence;
    request->remote_input_controlled = pending_cast->remote_input_controlled;
    request->target_actor_address = pending_cast->target_actor_address;
    request->has_origin_transform = pending_cast->has_origin_transform;
    request->origin_position_x = pending_cast->origin_position_x;
    request->origin_position_y = pending_cast->origin_position_y;
    request->has_origin_heading = pending_cast->has_origin_heading;
    request->origin_heading = pending_cast->origin_heading;
    request->has_aim_target = pending_cast->has_aim_target;
    request->aim_target_x = pending_cast->aim_target_x;
    request->aim_target_y = pending_cast->aim_target_y;
    request->has_aim_angle = pending_cast->has_aim_angle;
    request->aim_angle = pending_cast->aim_angle;
    RemovePendingCast(bot_id);
    return true;
}
