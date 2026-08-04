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
    destination->current_object_recipe_uid = source.current_object_recipe_uid;
    destination->current_object_color_state_valid =
        source.current_object_color_state_valid;
    destination->current_object_color_state = source.current_object_color_state;
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

PendingBotCastInput* FindBotCastInput(std::uint64_t bot_id) {
    const auto it = std::find_if(
        g_bot_cast_inputs.begin(),
        g_bot_cast_inputs.end(),
        [&](const PendingBotCastInput& input) {
            return input.bot_id == bot_id;
        });
    return it == g_bot_cast_inputs.end() ? nullptr : &(*it);
}

void RemovePendingCast(std::uint64_t bot_id) {
    g_pending_casts.erase(
        std::remove_if(g_pending_casts.begin(), g_pending_casts.end(), [&](const PendingBotCast& cast) {
            return cast.bot_id == bot_id;
        }),
        g_pending_casts.end());
}

void RemoveBotCastInput(std::uint64_t bot_id) {
    g_bot_cast_inputs.erase(
        std::remove_if(
            g_bot_cast_inputs.begin(),
            g_bot_cast_inputs.end(),
            [&](const PendingBotCastInput& input) {
                return input.bot_id == bot_id;
            }),
        g_bot_cast_inputs.end());
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

bool BotLoadoutRevisionTuplesEqual(
    const BotLoadoutRevisionTuple& left,
    const BotLoadoutRevisionTuple& right) {
    return left.loadout_revision == right.loadout_revision &&
           left.spellbook_revision == right.spellbook_revision &&
           left.statbook_revision == right.statbook_revision &&
           left.derived_stat_revision == right.derived_stat_revision;
}

CachedParticipantLoadoutDetails* FindCachedParticipantLoadoutDetails(
    std::uint64_t participant_id) {
    const auto it = std::find_if(
        g_loadout_details_cache.begin(),
        g_loadout_details_cache.end(),
        [&](const CachedParticipantLoadoutDetails& cached) {
            return cached.participant_id == participant_id;
        });
    return it == g_loadout_details_cache.end() ? nullptr : &(*it);
}

ActiveBotWeldBuild* FindActiveBotWeldBuild(
    std::uint64_t participant_id) {
    const auto it = std::find_if(
        g_active_bot_weld_builds.begin(),
        g_active_bot_weld_builds.end(),
        [&](const ActiveBotWeldBuild& active) {
            return active.participant_id == participant_id;
        });
    return it == g_active_bot_weld_builds.end() ? nullptr : &(*it);
}

void InvalidateParticipantLoadoutDetailsLocked(
    std::uint64_t participant_id) {
    g_loadout_details_cache.erase(
        std::remove_if(
            g_loadout_details_cache.begin(),
            g_loadout_details_cache.end(),
            [&](const CachedParticipantLoadoutDetails& cached) {
                return cached.participant_id == participant_id;
            }),
        g_loadout_details_cache.end());
}

void RemoveParticipantLoadoutStateLocked(
    std::uint64_t participant_id) {
    InvalidateParticipantLoadoutDetailsLocked(participant_id);
    g_active_bot_weld_builds.erase(
        std::remove_if(
            g_active_bot_weld_builds.begin(),
            g_active_bot_weld_builds.end(),
            [&](const ActiveBotWeldBuild& active) {
                return active.participant_id == participant_id;
            }),
        g_active_bot_weld_builds.end());
}

bool PromoteActiveBotWeldBuildLocked(
    std::uint64_t participant_id,
    std::uint64_t generation,
    std::int32_t build_id) {
    if (participant_id == 0 ||
        generation == 0 ||
        !IsNativeWeldBuildId(build_id)) {
        return false;
    }

    auto* active = FindActiveBotWeldBuild(participant_id);
    if (active == nullptr) {
        g_active_bot_weld_builds.push_back(ActiveBotWeldBuild{});
        active = &g_active_bot_weld_builds.back();
    }
    active->participant_id = participant_id;
    active->applied_generation = generation;
    active->build_id = build_id;
    InvalidateParticipantLoadoutDetailsLocked(participant_id);
    return true;
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

bool UpdateBotManaReserveStateLocked(
    std::uint64_t bot_id,
    float current_mp,
    float max_mp,
    const float* native_attainable_max_mp = nullptr) {
    if (bot_id == 0) {
        return false;
    }

    float nominal_ratio = 0.0f;
    if (!TryResolveBotManaRatio(current_mp, max_mp, &nominal_ratio)) {
        const auto* existing = FindBotManaReserveState(bot_id);
        return existing != nullptr && existing->active;
    }

    auto* state = FindBotManaReserveState(bot_id);
    if (state == nullptr) {
        g_bot_mana_reserves.push_back(BotManaReserveState{});
        state = &g_bot_mana_reserves.back();
        state->bot_id = bot_id;
    }

    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    const float progress_epsilon =
        (std::max)(0.001f, max_mp * 0.001f);
    const bool nominal_max_changed =
        !std::isfinite(state->nominal_max_mp) ||
        std::fabs(state->nominal_max_mp - max_mp) > progress_epsilon;
    if (nominal_max_changed) {
        state->nominal_max_mp = max_mp;
        if (!state->attainable_cap_detected ||
            !std::isfinite(state->attainable_max_mp) ||
            state->attainable_max_mp <= 0.0f) {
            state->attainable_max_mp = max_mp;
        } else {
            state->attainable_max_mp = std::clamp(
                state->attainable_max_mp,
                progress_epsilon,
                max_mp);
        }
        if (state->active) {
            state->recovery_peak_mp = current_mp;
            state->last_progress_ms = now_ms;
        }
    }

    const bool native_attainable_available =
        native_attainable_max_mp != nullptr &&
        std::isfinite(*native_attainable_max_mp) &&
        *native_attainable_max_mp > progress_epsilon &&
        *native_attainable_max_mp <= max_mp + progress_epsilon;
    if (native_attainable_available) {
        const float resolved_native_attainable_max_mp = std::clamp(
            *native_attainable_max_mp,
            progress_epsilon,
            max_mp);
        const bool native_cap_active =
            resolved_native_attainable_max_mp <
            max_mp - progress_epsilon;
        if (native_cap_active) {
            const bool native_cap_changed =
                !state->native_attainable_cap ||
                std::fabs(
                    state->attainable_max_mp -
                    resolved_native_attainable_max_mp) >
                    progress_epsilon;
            state->native_attainable_cap = true;
            state->attainable_cap_detected = true;
            state->attainable_max_mp =
                resolved_native_attainable_max_mp;
            if (native_cap_changed) {
                state->recovery_peak_mp =
                    (std::min)(current_mp, state->attainable_max_mp);
                state->last_progress_ms = now_ms;
                Log(
                    "[bots] native mana attainable cap refreshed. bot_id=" +
                    std::to_string(bot_id) +
                    " mp=" + std::to_string(current_mp) +
                    " nominal_max=" + std::to_string(max_mp) +
                    " attainable_max=" +
                        std::to_string(state->attainable_max_mp));
            }
        } else if (state->native_attainable_cap) {
            state->native_attainable_cap = false;
            state->attainable_cap_detected = false;
            state->attainable_max_mp = max_mp;
            state->recovery_peak_mp = current_mp;
            state->last_progress_ms = now_ms;
            Log(
                "[bots] native mana attainable cap cleared. bot_id=" +
                std::to_string(bot_id) +
                " mp=" + std::to_string(current_mp) +
                " nominal_max=" + std::to_string(max_mp));
        }
    }

    if (!state->attainable_cap_detected) {
        state->attainable_max_mp = max_mp;
    } else if (
        !state->native_attainable_cap &&
        current_mp > state->attainable_max_mp + progress_epsilon) {
        state->attainable_max_mp = (std::min)(current_mp, max_mp);
        if (state->attainable_max_mp >= max_mp - progress_epsilon) {
            state->attainable_cap_detected = false;
            state->attainable_max_mp = max_mp;
        }
    }
    state->resume_threshold_mp =
        state->attainable_max_mp * kBotManaReserveExitRatio;

    float ratio = 0.0f;
    if (!TryResolveBotManaRatio(
            current_mp,
            state->attainable_max_mp,
            &ratio)) {
        return state->active;
    }

    const bool was_active = state->active;
    if (state->active) {
        if (current_mp > state->recovery_peak_mp + progress_epsilon) {
            state->recovery_peak_mp = current_mp;
            state->last_progress_ms = now_ms;
        }
        if (ratio >= kBotManaReserveExitRatio) {
            state->active = false;
        } else if (
            !state->native_attainable_cap &&
            now_ms - state->last_progress_ms >=
            kBotManaReserveAttainablePlateauMs) {
            const float detected_attainable_max_mp = std::clamp(
                current_mp,
                progress_epsilon,
                max_mp);
            const bool cap_changed =
                !state->attainable_cap_detected ||
                std::fabs(
                    state->attainable_max_mp -
                    detected_attainable_max_mp) > progress_epsilon;
            state->attainable_cap_detected = true;
            state->native_attainable_cap = false;
            state->attainable_max_mp = detected_attainable_max_mp;
            state->resume_threshold_mp =
                state->attainable_max_mp * kBotManaReserveExitRatio;
            (void)TryResolveBotManaRatio(
                current_mp,
                state->attainable_max_mp,
                &ratio);
            if (cap_changed) {
                Log(
                    "[bots] mana attainable cap detected. bot_id=" +
                    std::to_string(bot_id) +
                    " mp=" + std::to_string(current_mp) +
                    " nominal_max=" + std::to_string(max_mp) +
                    " attainable_max=" +
                        std::to_string(state->attainable_max_mp) +
                    " resume_threshold=" +
                        std::to_string(state->resume_threshold_mp) +
                    " plateau_ms=" +
                        std::to_string(
                            kBotManaReserveAttainablePlateauMs));
            }
            if (ratio >= kBotManaReserveExitRatio) {
                state->active = false;
            }
        }
    } else if (
        nominal_ratio <= kBotManaReserveEnterRatio &&
        (!state->attainable_cap_detected ||
         ratio < kBotManaReserveExitRatio)) {
        state->active = true;
        state->recovery_peak_mp = current_mp;
        state->last_progress_ms = now_ms;
    }
    state->last_ratio = ratio;

    if (state->active != was_active) {
        Log(
            std::string("[bots] mana reserve ") +
            (state->active ? "entered" : "exited") +
            ". bot_id=" + std::to_string(bot_id) +
            " mp=" + std::to_string(current_mp) +
            " nominal_max=" + std::to_string(max_mp) +
            " attainable_max=" +
                std::to_string(state->attainable_max_mp) +
            " resume_threshold=" +
                std::to_string(state->resume_threshold_mp) +
            " attainable_cap_detected=" +
                std::to_string(
                    state->attainable_cap_detected ? 1 : 0) +
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
