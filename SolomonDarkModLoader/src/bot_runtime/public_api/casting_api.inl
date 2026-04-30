bool QueueBotCast(const BotCastRequest& request) {
    std::scoped_lock lock(g_bot_runtime_mutex);
    if (!g_bot_runtime_initialized || !IsValidCastRequest(request)) {
        return false;
    }

    const RuntimeState runtime = SnapshotRuntimeState();
    const auto* participant = FindBot(runtime, request.bot_id);
    if (participant == nullptr) {
        return false;
    }
    if (IsParticipantRuntimeDead(*participant)) {
        ClearDeadBotControlsLocked(*participant);
        return false;
    }
    const auto mana_cost =
        ResolveBotCastManaCost(
            participant->character_profile,
            request.kind,
            request.secondary_slot,
            request.skill_id);
    if (!mana_cost.resolved) {
        Log(
            "[bots] cast rejected for unknown mana cost. bot_id=" + std::to_string(request.bot_id) +
            " requested_skill_id=" + std::to_string(request.skill_id) +
            " kind=" + (request.kind == BotCastKind::Primary ? std::string("primary") : std::string("secondary")) +
            " slot=" + std::to_string(request.secondary_slot));
        return false;
    }
    if (participant->runtime.mana_max > 0) {
        const float required_mana = ResolveBotManaRequiredToStart(mana_cost);
        if (required_mana > 0.0f &&
            static_cast<float>(participant->runtime.mana_current) + 0.001f < required_mana) {
            Log(
                "[bots] cast rejected for mana. bot_id=" + std::to_string(request.bot_id) +
                " skill_id=" + std::to_string(mana_cost.skill_id) +
                " kind=" + (request.kind == BotCastKind::Primary ? std::string("primary") : std::string("secondary")) +
                " slot=" + std::to_string(request.secondary_slot) +
                " mode=" + BotManaChargeKindLabel(mana_cost.kind) +
                " required=" + std::to_string(required_mana) +
                " current=" + std::to_string(participant->runtime.mana_current));
            return false;
        }
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
        if (FindBot(state, request.bot_id) == nullptr) {
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
        pending_cast->target_actor_address = request.target_actor_address;
        pending_cast->has_aim_target = request.has_aim_target;
        pending_cast->aim_target_x = request.aim_target_x;
        pending_cast->aim_target_y = request.aim_target_y;
        pending_cast->has_aim_angle = request.has_aim_angle;
        pending_cast->aim_angle = request.aim_angle;
        pending_cast->queued_cast_count = g_next_cast_sequence++;
        pending_cast->queued_at_ms = now_ms;
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
    }

    return queued;
}

BotManaCost ResolveBotCastManaCost(
    const MultiplayerCharacterProfile& character_profile,
    BotCastKind kind,
    std::int32_t secondary_slot,
    std::int32_t skill_id) {
    constexpr float kFireMana[] = {
        0.0f, 12.0f, 15.0f, 18.0f, 19.0f, 20.0f, 21.0f, 22.0f, 24.0f,
        25.0f, 26.0f, 28.0f, 30.0f, 32.0f, 36.0f, 40.0f, 44.0f, 48.0f,
        50.0f, 53.0f, 56.0f, 59.0f, 72.0f, 75.0f, 77.0f, 80.0f,
    };
    constexpr float kWaterMana[] = {
        0.0f, 12.5f, 17.5f, 18.5f, 20.0f, 21.0f, 22.5f, 25.0f, 27.5f,
        30.0f, 32.5f, 35.0f, 37.5f, 42.5f, 45.0f, 47.5f, 50.0f, 52.5f,
        55.0f, 57.5f, 60.0f, 62.5f, 64.5f, 66.5f, 68.5f, 70.5f,
    };
    constexpr float kEarthMana[] = {
        0.0f, 12.0f, 13.0f, 14.0f, 15.0f, 16.0f, 17.0f, 18.0f, 19.0f,
        20.0f, 21.0f, 22.0f, 23.0f, 24.0f, 25.0f, 26.0f, 27.0f, 28.0f,
        29.0f, 30.0f, 31.0f, 32.0f, 33.0f, 34.0f, 35.0f, 36.0f,
    };
    constexpr float kAirMana[] = {
        0.0f, 12.0f, 14.0f, 18.0f, 20.0f, 21.0f, 22.0f, 25.0f, 27.0f,
        30.0f, 32.0f, 35.0f, 37.0f, 42.0f, 45.0f, 47.0f, 50.0f, 52.0f,
        55.0f, 57.0f, 62.0f, 67.0f, 72.0f, 77.0f, 82.0f, 87.0f,
    };
    constexpr float kEtherMana[] = {
        0.0f, 6.0f, 9.0f, 12.0f, 15.0f, 18.0f, 21.0f, 24.0f, 27.0f,
        30.0f, 33.0f, 36.0f, 39.0f, 42.0f, 45.0f, 48.0f, 51.0f, 54.0f,
        57.0f, 60.0f, 63.0f, 65.0f, 67.0f, 68.0f, 69.0f, 70.0f,
    };

    struct PrimaryEntryManaTable {
        std::int32_t entry_index;
        std::int32_t skill_id;
        BotManaChargeKind kind;
        const float* values;
        std::size_t count;
    };

    const PrimaryEntryManaTable kPrimaryManaTables[] = {
        {0x10, 0x3F3, BotManaChargeKind::PerCast, kFireMana, sizeof(kFireMana) / sizeof(kFireMana[0])},
        {0x20, 0x3F4, BotManaChargeKind::PerSecond, kWaterMana, sizeof(kWaterMana) / sizeof(kWaterMana[0])},
        {0x28, 0x3F6, BotManaChargeKind::PerSecond, kEarthMana, sizeof(kEarthMana) / sizeof(kEarthMana[0])},
        {0x18, 0x3F5, BotManaChargeKind::PerSecond, kAirMana, sizeof(kAirMana) / sizeof(kAirMana[0])},
        {0x08, 0x3F2, BotManaChargeKind::PerCast, kEtherMana, sizeof(kEtherMana) / sizeof(kEtherMana[0])},
    };

    const auto clamp_level = [](std::int32_t requested_level, std::size_t count) {
        if (requested_level < 1) {
            return 1;
        }
        const auto max_level = static_cast<std::int32_t>(count) - 1;
        return requested_level > max_level ? max_level : requested_level;
    };
    auto resolve_from_table = [&](const PrimaryEntryManaTable& table) {
        BotManaCost cost{};
        cost.resolved = true;
        cost.kind = table.kind;
        cost.statbook_level = clamp_level(character_profile.level, table.count);
        cost.cost = table.values[cost.statbook_level];
        cost.skill_id = table.skill_id;
        return cost;
    };
    auto find_primary_table_by_entry = [&](std::int32_t entry_index) -> const PrimaryEntryManaTable* {
        for (const auto& table : kPrimaryManaTables) {
            if (table.entry_index == entry_index) {
                return &table;
            }
        }
        return nullptr;
    };
    auto find_primary_table_by_skill = [&](std::int32_t value) -> const PrimaryEntryManaTable* {
        for (const auto& table : kPrimaryManaTables) {
            if (table.skill_id == value || table.entry_index == value) {
                return &table;
            }
        }
        return nullptr;
    };
    auto resolve_default_primary_entry = [&]() {
        switch (character_profile.element_id) {
        case 0:
            return 0x10;
        case 1:
            return 0x20;
        case 2:
            return 0x28;
        case 3:
            return 0x18;
        case 4:
            return 0x08;
        default:
            return -1;
        }
    };
    auto resolve_primary_build_skill_id = [](std::int32_t primary_entry, std::int32_t combo_entry) {
        const auto matches = [&](std::int32_t a, std::int32_t b) {
            return primary_entry == a && combo_entry == b;
        };
        if (matches(0x08, 0x10) || matches(0x10, 0x08)) {
            return 1000;
        }
        if (matches(0x08, 0x18) || matches(0x18, 0x08)) {
            return 0x3EA;
        }
        if (matches(0x08, 0x20) || matches(0x20, 0x08)) {
            return 0x3E9;
        }
        if (matches(0x08, 0x28) || matches(0x28, 0x08)) {
            return 0x3EE;
        }
        if (matches(0x10, 0x18) || matches(0x18, 0x10)) {
            return 0x3EB;
        }
        if (matches(0x10, 0x20) || matches(0x20, 0x10)) {
            return 0x3ED;
        }
        if (matches(0x10, 0x28) || matches(0x28, 0x10)) {
            return 0x3EF;
        }
        if (matches(0x18, 0x20) || matches(0x20, 0x18)) {
            return 0x3EC;
        }
        if (matches(0x18, 0x28) || matches(0x28, 0x18)) {
            return 0x3F1;
        }
        if (matches(0x20, 0x28) || matches(0x28, 0x20)) {
            return 0x3F0;
        }
        if (matches(0x08, 0x08)) {
            return 0x3F2;
        }
        if (matches(0x10, 0x10)) {
            return 0x3F3;
        }
        if (matches(0x18, 0x18)) {
            return 0x3F5;
        }
        if (matches(0x20, 0x20)) {
            return 0x3F4;
        }
        if (matches(0x28, 0x28)) {
            return 0x3F6;
        }
        return -1;
    };
    auto resolve_primary_loadout = [&]() {
        auto primary_entry = character_profile.loadout.primary_entry_index;
        if (primary_entry < 0) {
            primary_entry = resolve_default_primary_entry();
        }
        auto combo_entry = character_profile.loadout.primary_combo_entry_index;
        if (combo_entry < 0) {
            combo_entry = primary_entry;
        }
        const auto build_skill_id = resolve_primary_build_skill_id(primary_entry, combo_entry);
        if (build_skill_id <= 0) {
            return BotManaCost{};
        }
        const auto* primary_table = find_primary_table_by_entry(primary_entry);
        const auto* combo_table = find_primary_table_by_entry(combo_entry);
        if (primary_table == nullptr || combo_table == nullptr) {
            return BotManaCost{};
        }
        if (primary_entry == combo_entry) {
            auto cost = resolve_from_table(*primary_table);
            cost.skill_id = build_skill_id;
            return cost;
        }

        const auto primary_cost = resolve_from_table(*primary_table);
        const auto combo_cost = resolve_from_table(*combo_table);
        BotManaCost cost{};
        cost.resolved = true;
        cost.kind =
            (primary_cost.kind == BotManaChargeKind::PerSecond ||
             combo_cost.kind == BotManaChargeKind::PerSecond)
                ? BotManaChargeKind::PerSecond
                : BotManaChargeKind::PerCast;
        cost.statbook_level = primary_cost.statbook_level;
        cost.cost = primary_cost.cost + combo_cost.cost;
        cost.skill_id = build_skill_id;
        return cost;
    };

    if (kind == BotCastKind::Primary) {
        if (const auto* direct_table = find_primary_table_by_skill(skill_id); direct_table != nullptr) {
            return resolve_from_table(*direct_table);
        }
        const auto loadout_cost = resolve_primary_loadout();
        if (skill_id <= 0 || loadout_cost.skill_id == skill_id) {
            return loadout_cost;
        }
        return BotManaCost{};
    }

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
    if (const auto* direct_table = find_primary_table_by_skill(resolved_secondary_skill_id);
        direct_table != nullptr) {
        return resolve_from_table(*direct_table);
    }
    return BotManaCost{};
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
    request->target_actor_address = pending_cast->target_actor_address;
    request->has_aim_target = pending_cast->has_aim_target;
    request->aim_target_x = pending_cast->aim_target_x;
    request->aim_target_y = pending_cast->aim_target_y;
    request->has_aim_angle = pending_cast->has_aim_angle;
    request->aim_angle = pending_cast->aim_angle;
    RemovePendingCast(bot_id);
    return true;
}
