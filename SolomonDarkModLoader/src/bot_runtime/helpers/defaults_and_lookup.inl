void CopyEquipVisualLaneState(
    const SDModEquipVisualLaneState& source,
    BotEquipVisualLaneState* destination) {
    if (destination == nullptr) {
        return;
    }

    destination->wrapper_address = source.wrapper_address;
    destination->holder_address = source.holder_address;
    destination->current_object_address = source.current_object_address;
    destination->holder_kind = source.holder_kind;
    destination->current_object_vtable = source.current_object_vtable;
    destination->current_object_type_id = source.current_object_type_id;
}

BotLoadoutInfo DefaultBotLoadout() {
    return BotLoadoutInfo{};
}

std::string DefaultBotName(std::uint64_t bot_id) {
    return "Lua Bot " + std::to_string(bot_id - kFirstLuaControlledParticipantId + 1ull);
}

const char* BotControllerStateLabelInternal(BotControllerState state) {
    switch (state) {
        case BotControllerState::Idle:
            return "idle";
        case BotControllerState::Moving:
            return "moving";
        case BotControllerState::Attacking:
            return "attacking";
    }

    return "idle";
}

bool IsParticipantRuntimeDead(const ParticipantInfo& participant) {
    return participant.runtime.life_max > 0 && participant.runtime.life_current <= 0;
}

PendingBotCast* FindPendingCast(std::uint64_t bot_id) {
    const auto it = std::find_if(g_pending_casts.begin(), g_pending_casts.end(), [&](const PendingBotCast& cast) {
        return cast.bot_id == bot_id;
    });
    return it == g_pending_casts.end() ? nullptr : &(*it);
}

void RemovePendingCast(std::uint64_t bot_id) {
    g_pending_casts.erase(
        std::remove_if(g_pending_casts.begin(), g_pending_casts.end(), [&](const PendingBotCast& cast) {
            return cast.bot_id == bot_id;
        }),
        g_pending_casts.end());
}

PendingBotEntitySync* FindPendingEntitySync(std::uint64_t bot_id) {
    const auto it = std::find_if(g_pending_entity_syncs.begin(), g_pending_entity_syncs.end(), [&](const PendingBotEntitySync& sync) {
        return sync.bot_id == bot_id;
    });
    return it == g_pending_entity_syncs.end() ? nullptr : &(*it);
}

void RemovePendingEntitySync(std::uint64_t bot_id) {
    g_pending_entity_syncs.erase(
        std::remove_if(g_pending_entity_syncs.begin(), g_pending_entity_syncs.end(), [&](const PendingBotEntitySync& sync) {
            return sync.bot_id == bot_id;
        }),
        g_pending_entity_syncs.end());
}

PendingBotMovementIntent* FindPendingMovementIntent(std::uint64_t bot_id) {
    const auto it = std::find_if(
        g_bot_movement_intents.begin(),
        g_bot_movement_intents.end(),
        [&](const PendingBotMovementIntent& intent) {
            return intent.bot_id == bot_id;
        });
    return it == g_bot_movement_intents.end() ? nullptr : &(*it);
}

void RemovePendingMovementIntent(std::uint64_t bot_id) {
    g_bot_movement_intents.erase(
        std::remove_if(
            g_bot_movement_intents.begin(),
            g_bot_movement_intents.end(),
            [&](const PendingBotMovementIntent& intent) {
                return intent.bot_id == bot_id;
            }),
        g_bot_movement_intents.end());
}

PendingBotDestroy* FindPendingDestroy(std::uint64_t bot_id) {
    const auto it = std::find_if(
        g_pending_destroys.begin(),
        g_pending_destroys.end(),
        [&](const PendingBotDestroy& pending_destroy) {
            return pending_destroy.bot_id == bot_id;
        });
    return it == g_pending_destroys.end() ? nullptr : &(*it);
}

void RemovePendingDestroy(std::uint64_t bot_id) {
    g_pending_destroys.erase(
        std::remove_if(
            g_pending_destroys.begin(),
            g_pending_destroys.end(),
            [&](const PendingBotDestroy& pending_destroy) {
                return pending_destroy.bot_id == bot_id;
            }),
        g_pending_destroys.end());
}

PendingBotSkillChoice* FindPendingSkillChoice(std::uint64_t bot_id) {
    const auto it = std::find_if(
        g_pending_skill_choices.begin(),
        g_pending_skill_choices.end(),
        [&](const PendingBotSkillChoice& pending_choice) {
            return pending_choice.bot_id == bot_id;
        });
    return it == g_pending_skill_choices.end() ? nullptr : &(*it);
}

const PendingBotSkillChoice* FindPendingSkillChoiceConst(std::uint64_t bot_id) {
    const auto it = std::find_if(
        g_pending_skill_choices.begin(),
        g_pending_skill_choices.end(),
        [&](const PendingBotSkillChoice& pending_choice) {
            return pending_choice.bot_id == bot_id;
        });
    return it == g_pending_skill_choices.end() ? nullptr : &(*it);
}

BotManaReserveState* FindBotManaReserveState(std::uint64_t bot_id) {
    const auto it = std::find_if(
        g_bot_mana_reserves.begin(),
        g_bot_mana_reserves.end(),
        [&](const BotManaReserveState& state) {
            return state.bot_id == bot_id;
        });
    return it == g_bot_mana_reserves.end() ? nullptr : &(*it);
}

void RemoveBotManaReserveState(std::uint64_t bot_id) {
    g_bot_mana_reserves.erase(
        std::remove_if(
            g_bot_mana_reserves.begin(),
            g_bot_mana_reserves.end(),
            [&](const BotManaReserveState& state) {
                return state.bot_id == bot_id;
            }),
        g_bot_mana_reserves.end());
}

bool TryResolveBotManaRatio(float current_mp, float max_mp, float* ratio) {
    if (ratio != nullptr) {
        *ratio = 0.0f;
    }
    if (!std::isfinite(current_mp) || !std::isfinite(max_mp) || max_mp <= 0.0f) {
        return false;
    }

    const auto resolved_ratio = current_mp / max_mp;
    if (!std::isfinite(resolved_ratio)) {
        return false;
    }
    if (ratio != nullptr) {
        *ratio = resolved_ratio;
    }
    return true;
}

bool UpdateBotManaReserveStateLocked(std::uint64_t bot_id, float current_mp, float max_mp) {
    if (bot_id == 0) {
        return false;
    }

    float ratio = 0.0f;
    if (!TryResolveBotManaRatio(current_mp, max_mp, &ratio)) {
        const auto* existing = FindBotManaReserveState(bot_id);
        return existing != nullptr && existing->active;
    }

    auto* state = FindBotManaReserveState(bot_id);
    if (state == nullptr) {
        g_bot_mana_reserves.push_back(BotManaReserveState{});
        state = &g_bot_mana_reserves.back();
        state->bot_id = bot_id;
    }

    const bool was_active = state->active;
    if (ratio < kBotManaReserveEnterRatio) {
        state->active = true;
    } else if (ratio > kBotManaReserveExitRatio) {
        state->active = false;
    }
    state->last_ratio = ratio;

    if (state->active != was_active) {
        Log(
            std::string("[bots] mana reserve ") +
            (state->active ? "entered" : "exited") +
            ". bot_id=" + std::to_string(bot_id) +
            " mp=" + std::to_string(current_mp) +
            " max=" + std::to_string(max_mp) +
            " ratio=" + std::to_string(ratio) +
            " enter_ratio=" + std::to_string(kBotManaReserveEnterRatio) +
            " exit_ratio=" + std::to_string(kBotManaReserveExitRatio));
    }

    return state->active;
}

void RemovePendingSkillChoice(std::uint64_t bot_id) {
    g_pending_skill_choices.erase(
        std::remove_if(
            g_pending_skill_choices.begin(),
            g_pending_skill_choices.end(),
            [&](const PendingBotSkillChoice& pending_choice) {
                return pending_choice.bot_id == bot_id;
            }),
        g_pending_skill_choices.end());
}

ParticipantInfo* FindBot(RuntimeState& state, std::uint64_t bot_id) {
    auto* participant = FindParticipant(state, bot_id);
    return participant != nullptr && IsLuaControlledParticipant(*participant) ? participant : nullptr;
}

const ParticipantInfo* FindBot(const RuntimeState& state, std::uint64_t bot_id) {
    const auto* participant = FindParticipant(state, bot_id);
    return participant != nullptr && IsLuaControlledParticipant(*participant) ? participant : nullptr;
}
