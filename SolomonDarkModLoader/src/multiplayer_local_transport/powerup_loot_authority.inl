bool TryResolvePowerupRewardKind(
    std::int32_t value,
    PowerupRewardKind* kind) {
    if (kind == nullptr) {
        return false;
    }
    switch (static_cast<PowerupRewardKind>(value)) {
    case PowerupRewardKind::BonusSkillPoint:
    case PowerupRewardKind::RandomSkillRank:
    case PowerupRewardKind::DamageX4:
        *kind = static_cast<PowerupRewardKind>(value);
        return true;
    }
    return false;
}

bool IsPowerupPreparationPendingMaterializationError(
    const std::string& error_message) {
    return error_message.find("materialized progression") !=
           std::string::npos;
}

bool TryResolveDamageX4DurationTicks(std::int32_t* duration_ticks) {
    if (duration_ticks == nullptr) {
        return false;
    }
    *duration_ticks = 0;
    const auto timing_scale_address =
        ProcessMemory::Instance().ResolveGameAddressOrZero(
            kGameTimingScaleGlobal);
    float timing_scale = 0.0f;
    if (timing_scale_address == 0 ||
        !ProcessMemory::Instance().TryReadValue(
            timing_scale_address,
            &timing_scale) ||
        !std::isfinite(timing_scale) ||
        timing_scale <= 0.0f) {
        return false;
    }

    const auto raw_duration =
        static_cast<std::int32_t>(timing_scale * 15.0f);
    if (raw_duration <= 0 ||
        raw_duration > kParticipantDamageX4MaxDurationTicks) {
        return false;
    }
    *duration_ticks = raw_duration;
    return true;
}

bool TrySelectRandomSkillRankPowerupOption(
    const LootDropSnapshotPacketState& drop,
    const ParticipantInfo& participant,
    BotSkillChoiceOption* option) {
    if (option == nullptr ||
        participant.owned_progression.progression_book_truncated) {
        return false;
    }

    std::vector<std::int32_t> eligible_entry_indices;
    for (const auto& entry :
         participant.owned_progression.progression_book_entries) {
        if (entry.entry_index < 8 ||
            entry.entry_index > 82 ||
            entry.visible == 0 ||
            entry.active == 0 ||
            entry.statbook_max_level <= 0 ||
            entry.active >=
                static_cast<std::uint16_t>(
                    entry.statbook_max_level)) {
            continue;
        }
        eligible_entry_indices.push_back(entry.entry_index);
    }
    if (eligible_entry_indices.empty()) {
        return false;
    }

    std::uint64_t mixed =
        drop.network_drop_id ^
        (participant.participant_id +
         0x9E3779B97F4A7C15ull);
    mixed ^= mixed >> 30;
    mixed *= 0xBF58476D1CE4E5B9ull;
    mixed ^= mixed >> 27;
    mixed *= 0x94D049BB133111EBull;
    mixed ^= mixed >> 31;
    const auto selected_index =
        static_cast<std::size_t>(
            mixed % eligible_entry_indices.size());
    option->option_id =
        eligible_entry_indices[selected_index];
    option->apply_count = 1;
    return true;
}

bool TryPreparePowerupReward(
    const LootDropSnapshotPacketState& drop,
    const ParticipantInfo& participant,
    bool host_self,
    PreparedPowerupReward* prepared,
    std::string* error_message) {
    if (prepared == nullptr) {
        return false;
    }
    *prepared = {};

    PowerupRewardKind kind =
        PowerupRewardKind::BonusSkillPoint;
    if (!TryResolvePowerupRewardKind(
            drop.amount_tier,
            &kind)) {
        if (error_message != nullptr) {
            *error_message = "unsupported_powerup_kind";
        }
        return false;
    }
    prepared->kind = kind;

    if (kind == PowerupRewardKind::BonusSkillPoint) {
        if (HasUnresolvedIssuedLevelUpOfferForParticipant(
                participant.participant_id)) {
            if (error_message != nullptr) {
                *error_message =
                    "participant_level_up_offer_already_active";
            }
            return false;
        }

        std::string roll_error;
        const bool rolled = host_self
            ? RollLocalPlayerSkillChoiceOptions(
                  &prepared->skill_choice_options,
                  &roll_error)
            : RollParticipantSkillChoiceOptions(
                  participant.participant_id,
                  &prepared->skill_choice_options,
                  &roll_error);
        if (!rolled ||
            prepared->skill_choice_options.empty()) {
            if (error_message != nullptr) {
                *error_message =
                    "powerup_skill_choice_roll_failed: " +
                    roll_error;
            }
            return false;
        }
        return true;
    }

    if (kind == PowerupRewardKind::RandomSkillRank) {
        if (!TrySelectRandomSkillRankPowerupOption(
                drop,
                participant,
                &prepared->skill_rank_option)) {
            if (error_message != nullptr) {
                *error_message =
                    "powerup_has_no_eligible_skill_rank";
            }
            return false;
        }
        const auto selected_entry = std::find_if(
            participant.owned_progression
                .progression_book_entries.begin(),
            participant.owned_progression
                .progression_book_entries.end(),
            [&](const ParticipantProgressionBookEntryState& entry) {
                return entry.entry_index ==
                       prepared->skill_rank_option.option_id;
            });
        if (selected_entry ==
                participant.owned_progression
                    .progression_book_entries.end() ||
            selected_entry->active == 0 ||
            selected_entry->statbook_max_level <= 0) {
            if (error_message != nullptr) {
                *error_message =
                    "powerup_selected_skill_rank_unavailable";
            }
            return false;
        }
        prepared->skill_rank_resulting_active =
            static_cast<std::uint16_t>(
                (std::min)(
                    static_cast<std::int32_t>(
                        selected_entry->active) +
                        prepared->skill_rank_option.apply_count,
                    selected_entry->statbook_max_level));
        if (prepared->skill_rank_resulting_active <=
            selected_entry->active) {
            if (error_message != nullptr) {
                *error_message =
                    "powerup_selected_skill_rank_is_maxed";
            }
            return false;
        }
        return true;
    }

    if (!TryResolveDamageX4DurationTicks(
            &prepared->damage_x4_duration_ticks)) {
        if (error_message != nullptr) {
            *error_message =
                "powerup_damage_duration_unavailable";
        }
        return false;
    }
    return true;
}

bool TryWriteParticipantDamageX4Ticks(
    std::uint64_t participant_id,
    bool host_self,
    std::int32_t duration_ticks) {
    if (participant_id == 0 ||
        duration_ticks <= 0 ||
        kProgressionDamageX4RemainingTicksOffset == 0) {
        return false;
    }

    uintptr_t progression_address = 0;
    if (host_self) {
        SDModPlayerState player_state;
        if (!TryGetPlayerState(&player_state) ||
            !player_state.valid) {
            return false;
        }
        progression_address =
            player_state.progression_address;
    } else {
        SDModParticipantGameplayState gameplay_state;
        if (!TryGetParticipantGameplayState(
                participant_id,
                &gameplay_state) ||
            !gameplay_state.available) {
            return false;
        }
        progression_address =
            gameplay_state.progression_runtime_state_address;
    }
    return progression_address != 0 &&
           ProcessMemory::Instance().TryWriteField(
               progression_address,
               kProgressionDamageX4RemainingTicksOffset,
               duration_ticks);
}

void ApplyPowerupSkillRankToOwnedProgression(
    std::uint64_t participant_id,
    std::int32_t entry_index,
    std::uint16_t resulting_active,
    LootPickupResultPayload* payload) {
    UpdateRuntimeState([&](RuntimeState& state) {
        auto* participant =
            participant_id == g_local_transport.local_peer_id
                ? FindLocalParticipant(state)
                : FindParticipant(state, participant_id);
        if (participant == nullptr) {
            return;
        }

        auto entry = std::find_if(
            participant->owned_progression
                .progression_book_entries.begin(),
            participant->owned_progression
                .progression_book_entries.end(),
            [&](const ParticipantProgressionBookEntryState&
                    candidate) {
                return candidate.entry_index == entry_index;
            });
        if (entry ==
            participant->owned_progression
                .progression_book_entries.end()) {
            return;
        }
        if (entry->active != resulting_active) {
            entry->active = resulting_active;
            participant->owned_progression
                .spellbook_revision += 1;
            participant->owned_progression
                .statbook_revision += 1;
        }
        if (payload != nullptr) {
            payload->spellbook_revision =
                participant->owned_progression
                    .spellbook_revision;
            payload->statbook_revision =
                participant->owned_progression
                    .statbook_revision;
        }
    });
}

bool TryApplyPreparedPowerupReward(
    PendingHostLootPickup* pending,
    std::string* error_message) {
    if (pending == nullptr ||
        pending->drop_kind != LootDropKind::Powerup) {
        return false;
    }

    auto& payload = pending->payload;
    payload.powerup_kind = pending->powerup.kind;
    if (pending->powerup.kind ==
        PowerupRewardKind::BonusSkillPoint) {
        const auto runtime_state = SnapshotRuntimeState();
        const auto* participant =
            pending->host_self
                ? FindLocalParticipant(runtime_state)
                : FindParticipant(
                      runtime_state,
                      pending->packet.participant_id);
        if (participant == nullptr) {
            if (error_message != nullptr) {
                *error_message =
                    "powerup_participant_missing";
            }
            return false;
        }

        if (pending->host_self) {
            return IssueLocalHostSelfLevelUpOffer(
                participant->runtime.level,
                participant->runtime.experience_current,
                pending->powerup.skill_choice_options,
                false,
                error_message);
        }
        const bool issued =
            IssueHostLevelUpOfferForParticipant(
                pending->packet.participant_id,
                pending->packet.run_nonce,
                participant->runtime.level,
                participant->runtime.experience_current,
                pending->powerup.skill_choice_options,
                false);
        if (!issued && error_message != nullptr) {
            *error_message =
                "powerup_level_up_offer_issue_failed";
        }
        return issued;
    }

    if (pending->powerup.kind ==
        PowerupRewardKind::RandomSkillRank) {
        std::string apply_error;
        const bool applied =
            pending->host_self
                ? ApplyLocalPlayerSkillChoiceOption(
                      pending->powerup.skill_rank_option,
                      &apply_error)
                : ApplyParticipantSkillChoiceOption(
                      pending->packet.participant_id,
                      pending->powerup.skill_rank_option,
                      &apply_error);
        if (pending->host_self) {
            std::uint16_t native_active = 0;
            if (!applied ||
                !TryReadParticipantProgressionEntryActive(
                    pending->packet.participant_id,
                    pending->powerup.skill_rank_option.option_id,
                    &native_active) ||
                native_active !=
                    pending->powerup.skill_rank_resulting_active) {
                if (error_message != nullptr) {
                    *error_message =
                        "powerup_skill_rank_apply_failed: " +
                        apply_error;
                }
                return false;
            }
        } else if (!applied) {
            Log(
                "Multiplayer remote powerup skill rank native apply "
                "deferred to progression reconciliation. participant_id=" +
                std::to_string(pending->packet.participant_id) +
                " entry_index=" +
                std::to_string(
                    pending->powerup.skill_rank_option.option_id) +
                " expected_active=" +
                std::to_string(
                    pending->powerup.skill_rank_resulting_active) +
                " error=" + apply_error);
        }
        payload.powerup_skill_entry_index =
            pending->powerup.skill_rank_option.option_id;
        payload.powerup_skill_apply_count =
            pending->powerup.skill_rank_option.apply_count;
        payload.powerup_skill_resulting_active =
            pending->powerup.skill_rank_resulting_active;
        ApplyPowerupSkillRankToOwnedProgression(
            pending->packet.participant_id,
            payload.powerup_skill_entry_index,
            payload.powerup_skill_resulting_active,
            &payload);
        return true;
    }

    const bool native_damage_timer_written =
        TryWriteParticipantDamageX4Ticks(
            pending->packet.participant_id,
            pending->host_self,
            pending->powerup.damage_x4_duration_ticks);
    if (pending->host_self &&
        !native_damage_timer_written) {
        if (error_message != nullptr) {
            *error_message =
                "powerup_damage_timer_write_failed";
        }
        return false;
    }
    if (!pending->host_self &&
        !native_damage_timer_written) {
        Log(
            "Multiplayer remote DamageX4 native timer write "
            "deferred to progression reconciliation. participant_id=" +
            std::to_string(pending->packet.participant_id) +
            " duration_ticks=" +
            std::to_string(
                pending->powerup.damage_x4_duration_ticks));
    }

    payload.damage_x4_remaining_ticks =
        pending->powerup.damage_x4_duration_ticks;
    UpdateRuntimeState([&](RuntimeState& state) {
        auto* participant =
            pending->host_self
                ? FindLocalParticipant(state)
                : FindParticipant(
                      state,
                      pending->packet.participant_id);
        if (participant == nullptr) {
            return;
        }
        participant->runtime.transient_status_flags |=
            ParticipantTransientStatusFlagSnapshotValid |
            ParticipantTransientStatusFlagDamageX4;
        participant->runtime.damage_x4_remaining_ticks =
            pending->powerup.damage_x4_duration_ticks;
    });
    return true;
}

std::vector<QueuedLocalHostPowerupPickup>
TakeQueuedLocalHostPowerupPickups() {
    std::lock_guard<std::mutex> lock(
        g_local_transport_event_mutex);
    std::vector<QueuedLocalHostPowerupPickup> pickups;
    pickups.swap(g_queued_local_host_powerup_pickups);
    return pickups;
}

void ProcessQueuedLocalHostPowerupPickups(
    std::uint64_t now_ms) {
    if (!IsLocalTransportHost()) {
        return;
    }

    const auto pickups =
        TakeQueuedLocalHostPowerupPickups();
    if (pickups.empty()) {
        return;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local == nullptr ||
        !local->runtime.valid ||
        !local->runtime.in_run ||
        local->runtime.scene_intent.kind !=
            ParticipantSceneIntentKind::Run ||
        !local->owned_progression.derived_stats.valid) {
        return;
    }

    std::vector<SDModSceneActorState> actors;
    if (!TryListSceneActors(&actors)) {
        return;
    }

    for (const auto& queued : pickups) {
        const auto actor = std::find_if(
            actors.begin(),
            actors.end(),
            [&](const SDModSceneActorState& candidate) {
                return candidate.valid &&
                       candidate.actor_address ==
                           queued.actor_address &&
                       candidate.object_type_id ==
                           kPowerupRewardNativeTypeId;
            });
        if (actor == actors.end()) {
            continue;
        }

        const auto network_drop_id =
            AllocateRunLootDropNetworkId(*actor);
        if (network_drop_id == 0 ||
            g_local_transport
                    .accepted_loot_pickup_drop_ids.find(
                        network_drop_id) !=
                g_local_transport
                    .accepted_loot_pickup_drop_ids.end() ||
            g_local_transport
                    .pending_host_loot_pickups_by_drop_id.find(
                        network_drop_id) !=
                g_local_transport
                    .pending_host_loot_pickups_by_drop_id.end()) {
            continue;
        }

        LootDropSnapshotPacketState drop{};
        if (!TryPopulatePowerupLootDropSnapshot(
                *actor,
                network_drop_id,
                &drop) ||
            (drop.flags &
             LootDropSnapshotFlagActive) == 0) {
            continue;
        }

        const auto pickup_range =
            StockLootBehaviorDistance(
                LootDropKind::Powerup,
                local->owned_progression
                    .derived_stats.pickup_range);
        const bool captured_positions =
            queued.capture.valid &&
            std::isfinite(
                queued.capture.requester_position_x) &&
            std::isfinite(
                queued.capture.requester_position_y) &&
            std::isfinite(
                queued.capture.drop_position_x) &&
            std::isfinite(
                queued.capture.drop_position_y) &&
            DistanceSquared(
                queued.capture.drop_position_x,
                queued.capture.drop_position_y,
                drop.position_x,
                drop.position_y) <=
                kLootPickupDropDriftMaxDistance *
                kLootPickupDropDriftMaxDistance;
        const float requester_x =
            captured_positions
                ? queued.capture.requester_position_x
                : local->runtime.position_x;
        const float requester_y =
            captured_positions
                ? queued.capture.requester_position_y
                : local->runtime.position_y;
        if (!std::isfinite(pickup_range) ||
            pickup_range <= 0.0f ||
            DistanceSquared(
                requester_x,
                requester_y,
                drop.position_x,
                drop.position_y) >
                pickup_range * pickup_range) {
            continue;
        }

        PreparedPowerupReward prepared;
        std::string prepare_error;
        if (!TryPreparePowerupReward(
                drop,
                *local,
                true,
                &prepared,
                &prepare_error)) {
            Log(
                "Multiplayer host-self powerup pickup "
                "preparation failed. network_drop_id=" +
                std::to_string(network_drop_id) +
                " error=" + prepare_error);
            continue;
        }

        LootPickupRequestPacket request{};
        request.participant_id =
            g_local_transport.local_peer_id;
        request.request_sequence =
            g_next_local_loot_pickup_request_sequence++;
        if (g_next_local_loot_pickup_request_sequence == 0) {
            g_next_local_loot_pickup_request_sequence = 1;
        }
        request.run_nonce = local->runtime.run_nonce;
        request.network_drop_id = network_drop_id;
        request.requester_position_x =
            requester_x;
        request.requester_position_y =
            requester_y;
        request.drop_position_x = drop.position_x;
        request.drop_position_y = drop.position_y;

        std::string queue_error;
        if (!sdmod::QueueHostLootDropDeactivation(
                request.run_nonce,
                network_drop_id,
                actor->actor_address,
                LootDropKind::Powerup,
                &queue_error)) {
            Log(
                "Multiplayer host-self powerup "
                "deactivation queue failed. network_drop_id=" +
                std::to_string(network_drop_id) +
                " error=" + queue_error);
            continue;
        }

        PendingHostLootPickup pending;
        pending.packet = request;
        pending.drop_kind = LootDropKind::Powerup;
        pending.payload =
            BuildLootPickupResultPayloadFromParticipant(local);
        pending.powerup = std::move(prepared);
        pending.actor_address = actor->actor_address;
        pending.queued_ms = now_ms;
        pending.host_self = true;
        pending.powerup_prepared = true;
        g_local_transport
            .pending_host_loot_pickups_by_drop_id.emplace(
                network_drop_id,
                std::move(pending));
    }
}
