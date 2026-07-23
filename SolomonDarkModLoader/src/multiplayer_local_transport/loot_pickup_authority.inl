void PublishLootPickupResultRuntimeInfo(
    const LootPickupResultPacket& packet,
    std::uint64_t now_ms) {
    const auto packet_drop_kind =
        LootDropKindFromPacketValue(packet.drop_kind);
    std::int32_t local_item_slot = packet.item_slot;
    if (packet_drop_kind == LootDropKind::Potion &&
        !TryResolvePotionWireIdentity(
            packet.item_slot,
            packet.item_content_id,
            &local_item_slot)) {
        return;
    }
    if (packet.participant_id == g_local_transport.local_peer_id) {
        CompleteInFlightLocalLootPickupRequest(
            packet.network_drop_id,
            packet.request_sequence);
    }
    UpdateRuntimeState([&](RuntimeState& state) {
        LootPickupResultRuntimeInfo result;
        result.valid = true;
        result.authority_participant_id = packet.authority_participant_id;
        result.participant_id = packet.participant_id;
        result.received_ms = now_ms;
        result.sequence = packet.header.sequence;
        result.request_sequence = packet.request_sequence;
        result.run_nonce = packet.run_nonce;
        result.network_drop_id = packet.network_drop_id;
        result.result_code = LootPickupResultCodeFromPacketValue(packet.result_code);
        result.drop_kind = LootDropKindFromPacketValue(packet.drop_kind);
        result.amount = packet.amount;
        result.resulting_gold = packet.resulting_gold;
        result.gold_revision = packet.gold_revision;
        result.resource_kind = packet.resource_kind;
        result.resource_delta = packet.resource_delta;
        result.resulting_life_current = packet.resulting_life_current;
        result.resulting_life_max = packet.resulting_life_max;
        result.resulting_mana_current = packet.resulting_mana_current;
        result.resulting_mana_max = packet.resulting_mana_max;
        result.item_type_id = packet.item_type_id;
        result.item_recipe_uid = packet.item_recipe_uid;
        result.item_content_id = packet.item_content_id;
        result.item_color_state_valid =
            (packet.result_flags & LootPickupResultFlagItemColorState) != 0;
        if (result.item_color_state_valid) {
            std::memcpy(
                result.item_color_state.data(),
                packet.item_color_state,
                result.item_color_state.size());
        }
        result.item_slot = local_item_slot;
        result.stack_count = packet.stack_count;
        result.inventory_revision = packet.inventory_revision;
        PowerupRewardKind powerup_kind =
            PowerupRewardKind::BonusSkillPoint;
        if (TryResolvePowerupRewardKind(
                packet.powerup_kind,
                &powerup_kind)) {
            result.powerup_kind = powerup_kind;
        }
        result.powerup_skill_entry_index =
            packet.powerup_skill_entry_index;
        result.powerup_skill_apply_count =
            packet.powerup_skill_apply_count;
        result.powerup_skill_resulting_active =
            packet.powerup_skill_resulting_active;
        result.damage_x4_remaining_ticks =
            packet.damage_x4_remaining_ticks;
        result.spellbook_revision =
            packet.spellbook_revision;
        result.statbook_revision =
            packet.statbook_revision;
        state.last_loot_pickup_result = result;

        if (result.result_code != LootPickupResultCode::Accepted) {
            return;
        }

        ParticipantInfo* participant = nullptr;
        if (packet.participant_id == g_local_transport.local_peer_id) {
            participant = FindLocalParticipant(state);
        } else {
            participant = FindParticipant(state, packet.participant_id);
            if (participant == nullptr) {
                participant = UpsertRemoteParticipant(
                    state,
                    packet.participant_id,
                    ParticipantControllerKind::Native);
            }
        }
        if (participant == nullptr) {
            return;
        }

        if (result.drop_kind == LootDropKind::Gold) {
            const bool should_apply =
                !participant->owned_progression.initialized ||
                packet.gold_revision >= participant->owned_progression.gold_revision;
            if (!should_apply) {
                return;
            }
            participant->owned_progression.initialized = true;
            participant->owned_progression.gold = packet.resulting_gold;
            participant->owned_progression.gold_revision = packet.gold_revision;
            return;
        }

        if (result.drop_kind == LootDropKind::Orb) {
            LootOrbResourceKind resource_kind = LootOrbResourceKind::Health;
            if (!TryResolveLootOrbResourceKind(packet.resource_kind, &resource_kind)) {
                return;
            }
            participant->runtime.valid = true;
            if (resource_kind == LootOrbResourceKind::Health &&
                std::isfinite(packet.resulting_life_current) &&
                std::isfinite(packet.resulting_life_max) &&
                packet.resulting_life_max > 0.0f) {
                participant->runtime.life_max = packet.resulting_life_max;
                participant->runtime.life_current =
                    (std::clamp)(packet.resulting_life_current, 0.0f, packet.resulting_life_max);
            } else if (resource_kind == LootOrbResourceKind::Mana &&
                std::isfinite(packet.resulting_mana_current) &&
                std::isfinite(packet.resulting_mana_max) &&
                packet.resulting_mana_max > 0.0f) {
                participant->runtime.mana_max = packet.resulting_mana_max;
                participant->runtime.mana_current =
                    (std::clamp)(packet.resulting_mana_current, 0.0f, packet.resulting_mana_max);
            }
            return;
        }

        if (result.drop_kind == LootDropKind::Item || result.drop_kind == LootDropKind::Potion) {
            if (packet.item_type_id == 0 ||
                packet.inventory_revision <= participant->owned_progression.inventory_revision) {
                return;
            }
            participant->owned_progression.initialized = true;
            participant->owned_progression.inventory_host_authoritative = true;
            if (ApplyOwnedInventoryLootItem(
                    packet.item_type_id,
                    packet.item_recipe_uid,
                    packet.item_content_id,
                    local_item_slot,
                    packet.stack_count,
                    &participant->owned_progression)) {
                participant->owned_progression.inventory_revision =
                    (std::max)(
                        participant->owned_progression.inventory_revision,
                        packet.inventory_revision);
            }
            return;
        }

        if (result.drop_kind == LootDropKind::Powerup) {
            PowerupRewardKind kind =
                PowerupRewardKind::BonusSkillPoint;
            if (!TryResolvePowerupRewardKind(
                    packet.powerup_kind,
                    &kind)) {
                return;
            }
            if (kind == PowerupRewardKind::RandomSkillRank &&
                packet.powerup_skill_entry_index >= 0 &&
                packet.powerup_skill_resulting_active > 0) {
                auto entry = std::find_if(
                    participant->owned_progression
                        .progression_book_entries.begin(),
                    participant->owned_progression
                        .progression_book_entries.end(),
                    [&](const ParticipantProgressionBookEntryState&
                            candidate) {
                        return candidate.entry_index ==
                               packet.powerup_skill_entry_index;
                    });
                if (entry !=
                    participant->owned_progression
                        .progression_book_entries.end()) {
                    entry->active =
                        packet.powerup_skill_resulting_active;
                }
                participant->owned_progression.spellbook_revision =
                    (std::max)(
                        participant->owned_progression
                            .spellbook_revision,
                        packet.spellbook_revision);
                participant->owned_progression.statbook_revision =
                    (std::max)(
                        participant->owned_progression
                            .statbook_revision,
                        packet.statbook_revision);
            } else if (
                kind == PowerupRewardKind::DamageX4 &&
                packet.damage_x4_remaining_ticks > 0) {
                participant->runtime.transient_status_flags |=
                    ParticipantTransientStatusFlagSnapshotValid |
                    ParticipantTransientStatusFlagDamageX4;
                participant->runtime.damage_x4_remaining_ticks =
                    (std::clamp)(
                        packet.damage_x4_remaining_ticks,
                        std::int32_t{1},
                        kParticipantDamageX4MaxDurationTicks);
            }
        }
    });
}

LootPickupResultPayload BuildLootPickupResultPayloadFromParticipant(const ParticipantInfo* participant) {
    LootPickupResultPayload payload;
    if (participant == nullptr) {
        return payload;
    }
    payload.resulting_gold = participant->owned_progression.gold;
    payload.gold_revision = participant->owned_progression.gold_revision;
    payload.resulting_life_current = participant->runtime.life_current;
    payload.resulting_life_max = participant->runtime.life_max;
    payload.resulting_mana_current = participant->runtime.mana_current;
    payload.resulting_mana_max = participant->runtime.mana_max;
    payload.inventory_revision = participant->owned_progression.inventory_revision;
    payload.damage_x4_remaining_ticks =
        participant->runtime.damage_x4_remaining_ticks;
    payload.spellbook_revision =
        participant->owned_progression.spellbook_revision;
    payload.statbook_revision =
        participant->owned_progression.statbook_revision;
    return payload;
}

bool TryBuildAcceptedOrbLootPickupPayload(
    const LootDropSnapshotPacketState& drop,
    const ParticipantInfo* participant,
    LootPickupResultPayload* payload) {
    if (participant == nullptr || payload == nullptr) {
        return false;
    }

    LootOrbResourceKind resource_kind = LootOrbResourceKind::Health;
    if (!TryResolveLootOrbResourceKind(drop.amount_tier, &resource_kind) ||
        !participant->runtime.valid ||
        !std::isfinite(participant->runtime.life_current) ||
        !std::isfinite(participant->runtime.life_max) ||
        !std::isfinite(participant->runtime.mana_current) ||
        !std::isfinite(participant->runtime.mana_max) ||
        participant->runtime.life_max <= 0.0f ||
        participant->runtime.mana_max <= 0.0f) {
        return false;
    }

    const float resource_delta = ComputeLootOrbResourceDelta(drop.amount_tier, drop.value);
    if (resource_delta <= kLootPickupResourceEpsilon) {
        return false;
    }

    *payload = BuildLootPickupResultPayloadFromParticipant(participant);
    payload->amount = RoundRewardAmountToInt(resource_delta);
    payload->resource_kind = drop.amount_tier;
    payload->resource_delta = resource_delta;
    if (resource_kind == LootOrbResourceKind::Health) {
        payload->resulting_life_current =
            (std::min)(participant->runtime.life_current + resource_delta, participant->runtime.life_max);
    } else {
        payload->resulting_mana_current =
            (std::min)(participant->runtime.mana_current + resource_delta, participant->runtime.mana_max);
    }
    return true;
}

bool TryBuildAcceptedItemLootPickupPayload(
    const LootDropSnapshotPacketState& drop,
    const ParticipantInfo* participant,
    LootPickupResultPayload* payload) {
    if (participant == nullptr || payload == nullptr || drop.item_type_id == 0) {
        return false;
    }

    *payload = BuildLootPickupResultPayloadFromParticipant(participant);
    payload->amount = drop.item_type_id == kPotionItemTypeId
        ? (std::max)(drop.stack_count, 1)
        : 1;
    payload->item_type_id = drop.item_type_id;
    payload->item_recipe_uid = drop.item_recipe_uid;
    payload->item_content_id = drop.item_content_id;
    payload->item_color_state_valid =
        (drop.flags & LootDropSnapshotFlagItemColorState) != 0;
    if (payload->item_color_state_valid) {
        std::memcpy(
            payload->item_color_state.data(),
            drop.item_color_state,
            payload->item_color_state.size());
    }
    payload->item_slot = drop.item_slot;
    payload->stack_count = NormalizeInventoryLootStackCount(drop.item_type_id, drop.stack_count);
    return true;
}

void SendLootPickupResult(
    const LootPickupRequestPacket& request,
    const TransportPeerEndpoint& endpoint,
    LootPickupResultCode result_code,
    LootDropKind drop_kind,
    const LootPickupResultPayload& payload,
    bool host_self = false) {
    LootPickupResultPacket result{};
    result.header = MakePacketHeader(PacketKind::LootPickupResult, g_local_transport.next_sequence++);
    result.authority_participant_id = g_local_transport.local_peer_id;
    result.participant_id = request.participant_id;
    result.request_sequence = request.request_sequence;
    result.run_nonce = request.run_nonce;
    result.network_drop_id = request.network_drop_id;
    result.result_code = static_cast<std::uint8_t>(result_code);
    result.drop_kind = static_cast<std::uint8_t>(drop_kind);
    result.amount = payload.amount;
    result.resulting_gold = payload.resulting_gold;
    result.gold_revision = payload.gold_revision;
    result.resource_kind = payload.resource_kind;
    result.resource_delta = payload.resource_delta;
    result.resulting_life_current = payload.resulting_life_current;
    result.resulting_life_max = payload.resulting_life_max;
    result.resulting_mana_current = payload.resulting_mana_current;
    result.resulting_mana_max = payload.resulting_mana_max;
    result.item_type_id = payload.item_type_id;
    result.item_recipe_uid = payload.item_recipe_uid;
    result.item_content_id = payload.item_content_id;
    if (payload.item_color_state_valid) {
        result.result_flags |= LootPickupResultFlagItemColorState;
        std::memcpy(
            result.item_color_state,
            payload.item_color_state.data(),
            payload.item_color_state.size());
    }
    result.item_slot = payload.item_slot;
    result.stack_count = payload.stack_count;
    result.inventory_revision = payload.inventory_revision;
    result.powerup_kind =
        static_cast<std::int32_t>(payload.powerup_kind);
    result.powerup_skill_entry_index =
        payload.powerup_skill_entry_index;
    result.powerup_skill_apply_count =
        payload.powerup_skill_apply_count;
    result.powerup_skill_resulting_active =
        payload.powerup_skill_resulting_active;
    result.damage_x4_remaining_ticks =
        payload.damage_x4_remaining_ticks;
    result.spellbook_revision =
        payload.spellbook_revision;
    result.statbook_revision =
        payload.statbook_revision;

    if (host_self) {
        SendPacketToParticipantOrPeers(
            result,
            request.participant_id);
    } else {
        SendPacketToEndpoint(result, endpoint);
        RelayPacketToPeers(result, endpoint);
    }
    PublishLootPickupResultRuntimeInfo(
        result,
        static_cast<std::uint64_t>(GetTickCount64()));
}

bool ValidateLootPickupRequest(
    const LootPickupRequestPacket& packet,
    const ParticipantInfo* participant,
    const LootDropSnapshotPacketState& drop,
    std::string* reject_reason,
    LootPickupResultCode* result_code) {
    auto reject = [&](const char* reason, LootPickupResultCode code) {
        if (reject_reason != nullptr) {
            *reject_reason = reason;
        }
        if (result_code != nullptr) {
            *result_code = code;
        }
        return false;
    };

    if (participant == nullptr ||
        !IsRemoteParticipant(*participant) ||
        !IsNativeControlledParticipant(*participant) ||
        !participant->runtime.valid ||
        !participant->runtime.in_run ||
        participant->runtime.scene_intent.kind != ParticipantSceneIntentKind::Run) {
        return reject("participant_not_active_run", LootPickupResultCode::Rejected);
    }
    if (packet.run_nonce != 0 &&
        participant->runtime.run_nonce != 0 &&
        packet.run_nonce != participant->runtime.run_nonce) {
        return reject("participant_run_nonce_mismatch", LootPickupResultCode::WrongRun);
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local == nullptr ||
        !local->runtime.valid ||
        !local->runtime.in_run ||
        local->runtime.scene_intent.kind != ParticipantSceneIntentKind::Run) {
        return reject("host_not_active_run", LootPickupResultCode::WrongRun);
    }
    if (packet.run_nonce != 0 &&
        local->runtime.run_nonce != 0 &&
        packet.run_nonce != local->runtime.run_nonce) {
        return reject("host_run_nonce_mismatch", LootPickupResultCode::WrongRun);
    }

    const auto drop_kind = LootDropKindFromPacketValue(drop.drop_kind);
    if (drop_kind != LootDropKind::Gold &&
        drop_kind != LootDropKind::Orb &&
        drop_kind != LootDropKind::Item &&
        drop_kind != LootDropKind::Potion &&
        drop_kind != LootDropKind::Powerup) {
        return reject("unsupported_drop_kind", LootPickupResultCode::Unsupported);
    }
    if (g_local_transport.accepted_loot_pickup_drop_ids.find(packet.network_drop_id) !=
        g_local_transport.accepted_loot_pickup_drop_ids.end()) {
        return reject("drop_already_gone", LootPickupResultCode::AlreadyGone);
    }
    if ((drop.flags & LootDropSnapshotFlagActive) == 0) {
        return reject("drop_inactive", LootPickupResultCode::AlreadyGone);
    }
    if (drop_kind == LootDropKind::Gold && drop.amount <= 0) {
        return reject("drop_empty", LootPickupResultCode::AlreadyGone);
    }
    if (drop_kind == LootDropKind::Orb) {
        LootOrbResourceKind resource_kind = LootOrbResourceKind::Health;
        if (!TryResolveLootOrbResourceKind(drop.amount_tier, &resource_kind)) {
            return reject("unsupported_orb_resource_kind", LootPickupResultCode::Unsupported);
        }
        if (ComputeLootOrbResourceDelta(drop.amount_tier, drop.value) <= kLootPickupResourceEpsilon) {
            return reject("orb_empty", LootPickupResultCode::AlreadyGone);
        }
    }
    if (drop_kind == LootDropKind::Item || drop_kind == LootDropKind::Potion) {
        if (drop.item_type_id == 0) {
            return reject("item_missing_type", LootPickupResultCode::AlreadyGone);
        }
        if (drop_kind == LootDropKind::Potion && drop.item_type_id != kPotionItemTypeId) {
            return reject("potion_type_mismatch", LootPickupResultCode::Rejected);
        }
        std::int32_t local_potion_slot = -1;
        if (drop_kind == LootDropKind::Potion &&
            !TryResolvePotionWireIdentity(
                drop.item_slot,
                drop.item_content_id,
                &local_potion_slot)) {
            return reject("unsupported_potion_subtype", LootPickupResultCode::Unsupported);
        }
        if (drop_kind != LootDropKind::Potion &&
            drop.item_content_id != 0) {
            return reject(
                "unexpected_item_content_id",
                LootPickupResultCode::Rejected);
        }
        if (drop_kind == LootDropKind::Item && drop.item_type_id == kPotionItemTypeId) {
            return reject("item_type_mismatch", LootPickupResultCode::Rejected);
        }
        if (drop_kind == LootDropKind::Item &&
            drop.item_recipe_uid == 0 &&
            !IsSupportedNonRecipeLootItem(
                drop.item_type_id,
                drop.item_recipe_uid,
                drop.item_slot)) {
            return reject("item_missing_recipe_uid", LootPickupResultCode::Rejected);
        }
    }
    if (drop_kind == LootDropKind::Powerup) {
        PowerupRewardKind powerup_kind =
            PowerupRewardKind::BonusSkillPoint;
        if (drop.native_type_id !=
                kPowerupRewardNativeTypeId ||
            !TryResolvePowerupRewardKind(
                drop.amount_tier,
                &powerup_kind)) {
            return reject(
                "unsupported_powerup_kind",
                LootPickupResultCode::Unsupported);
        }
        if (drop.lifetime == 0) {
            return reject(
                "powerup_expired",
                LootPickupResultCode::AlreadyGone);
        }
    }
    if (!std::isfinite(packet.requester_position_x) ||
        !std::isfinite(packet.requester_position_y) ||
        !std::isfinite(packet.drop_position_x) ||
        !std::isfinite(packet.drop_position_y) ||
        !std::isfinite(drop.position_x) ||
        !std::isfinite(drop.position_y) ||
        (drop_kind == LootDropKind::Orb && !std::isfinite(drop.value))) {
        return reject("invalid_positions", LootPickupResultCode::Rejected);
    }

    const auto& derived_stats = participant->owned_progression.derived_stats;
    if (!derived_stats.valid ||
        !std::isfinite(derived_stats.pickup_range) ||
        derived_stats.pickup_range <= 0.0f) {
        return reject("participant_pickup_range_unavailable", LootPickupResultCode::Rejected);
    }
    const float range_limit =
        StockLootBehaviorDistance(drop_kind, derived_stats.pickup_range);
    if (!std::isfinite(range_limit) || range_limit <= 0.0f) {
        return reject("participant_pickup_range_invalid", LootPickupResultCode::Rejected);
    }
    const float range_limit_sq = range_limit * range_limit;
    const bool client_position_in_range =
        DistanceSquared(
            packet.requester_position_x,
            packet.requester_position_y,
            drop.position_x,
            drop.position_y) <= range_limit_sq;
    const bool host_observed_position_in_range =
        DistanceSquared(
            participant->runtime.position_x,
            participant->runtime.position_y,
            drop.position_x,
            drop.position_y) <= range_limit_sq;
    if (!client_position_in_range && !host_observed_position_in_range) {
        if (reject_reason != nullptr) {
            const float packet_distance = std::sqrt(DistanceSquared(
                packet.requester_position_x,
                packet.requester_position_y,
                drop.position_x,
                drop.position_y));
            const float host_observed_distance = std::sqrt(DistanceSquared(
                participant->runtime.position_x,
                participant->runtime.position_y,
                drop.position_x,
                drop.position_y));
            std::ostringstream reason;
            reason << "distance_sanity"
                   << " packet_requester=(" << packet.requester_position_x << ","
                   << packet.requester_position_y << ")"
                   << " host_observed=(" << participant->runtime.position_x << ","
                   << participant->runtime.position_y << ")"
                   << " drop=(" << drop.position_x << "," << drop.position_y << ")"
                   << " packet_distance=" << packet_distance
                   << " host_observed_distance=" << host_observed_distance
                   << " range_limit=" << range_limit;
            *reject_reason = reason.str();
        }
        if (result_code != nullptr) {
            *result_code = LootPickupResultCode::OutOfRange;
        }
        return false;
    }

    const float drift_limit_sq = kLootPickupDropDriftMaxDistance * kLootPickupDropDriftMaxDistance;
    if (DistanceSquared(
            packet.drop_position_x,
            packet.drop_position_y,
            drop.position_x,
            drop.position_y) > drift_limit_sq) {
        return reject("drop_position_drift", LootPickupResultCode::Rejected);
    }

    if (result_code != nullptr) {
        *result_code = LootPickupResultCode::Accepted;
    }
    return true;
}

void ApplyAcceptedHostLootPickupState(PendingHostLootPickup* pending) {
    if (pending == nullptr) {
        return;
    }
    UpdateRuntimeState([&](RuntimeState& state) {
        auto* participant = pending->host_self
            ? FindLocalParticipant(state)
            : FindParticipant(
                  state,
                  pending->packet.participant_id);
        if (participant == nullptr) {
            return;
        }

        auto& payload = pending->payload;
        if (pending->drop_kind == LootDropKind::Gold) {
            participant->owned_progression.initialized = true;
            participant->owned_progression.gold += payload.amount;
            participant->owned_progression.gold_revision += 1;
            payload.resulting_gold = participant->owned_progression.gold;
            payload.gold_revision = participant->owned_progression.gold_revision;
            return;
        }

        if (pending->drop_kind == LootDropKind::Orb) {
            LootOrbResourceKind resource_kind = LootOrbResourceKind::Health;
            if (!TryResolveLootOrbResourceKind(payload.resource_kind, &resource_kind)) {
                return;
            }
            participant->runtime.valid = true;
            if (resource_kind == LootOrbResourceKind::Health) {
                participant->runtime.life_current = payload.resulting_life_current;
                participant->runtime.life_max = payload.resulting_life_max;
            } else {
                participant->runtime.mana_current = payload.resulting_mana_current;
                participant->runtime.mana_max = payload.resulting_mana_max;
            }
            return;
        }

        if (pending->drop_kind == LootDropKind::Item ||
            pending->drop_kind == LootDropKind::Potion) {
            participant->owned_progression.initialized = true;
            participant->owned_progression.inventory_host_authoritative = true;
            if (ApplyOwnedInventoryLootItem(
                    payload.item_type_id,
                    payload.item_recipe_uid,
                    payload.item_content_id,
                    payload.item_slot,
                    payload.stack_count,
                    &participant->owned_progression)) {
                payload.inventory_revision =
                    participant->owned_progression.inventory_revision;
            }
        }
    });
}

void FinalizeHostLootPickup(
    PendingHostLootPickup pending,
    const SDModHostLootDropDeactivationResult& deactivation) {
    const bool deactivated =
        deactivation.deactivated &&
        deactivation.run_nonce == pending.packet.run_nonce &&
        deactivation.network_drop_id == pending.packet.network_drop_id &&
        deactivation.actor_address == pending.actor_address &&
        deactivation.drop_kind == pending.drop_kind;

    bool reward_applied = deactivated;
    std::string powerup_apply_error;
    if (deactivated &&
        pending.drop_kind == LootDropKind::Powerup) {
        reward_applied = TryApplyPreparedPowerupReward(
            &pending,
            &powerup_apply_error);
    }

    if (deactivated) {
        g_local_transport.accepted_loot_pickup_drop_ids.insert(
            pending.packet.network_drop_id);
    }
    if (reward_applied) {
        ApplyAcceptedHostLootPickupState(&pending);
    }

    LootPickupResultPayload result_payload = pending.payload;
    if (!reward_applied) {
        const auto runtime_state = SnapshotRuntimeState();
        result_payload = BuildLootPickupResultPayloadFromParticipant(
            pending.host_self
                ? FindLocalParticipant(runtime_state)
                : FindParticipant(
                      runtime_state,
                      pending.packet.participant_id));
    }
    SendLootPickupResult(
        pending.packet,
        pending.endpoint,
        reward_applied
            ? LootPickupResultCode::Accepted
            : LootPickupResultCode::Rejected,
        pending.drop_kind,
        result_payload,
        pending.host_self);

    Log(
        "Multiplayer loot pickup " +
        std::string(reward_applied ? "accepted" : "rejected") +
        ". participant_id=" + std::to_string(pending.packet.participant_id) +
        " network_drop_id=" + std::to_string(pending.packet.network_drop_id) +
        " kind=" + LootDropKindLabel(pending.drop_kind) +
        " amount=" + std::to_string(deactivated ? result_payload.amount : 0) +
        " resulting_gold=" + std::to_string(result_payload.resulting_gold) +
        " gold_revision=" + std::to_string(result_payload.gold_revision) +
        " resource_kind=" + std::to_string(result_payload.resource_kind) +
        " resource_delta=" +
            std::to_string(deactivated ? result_payload.resource_delta : 0.0f) +
        " resulting_life=" + std::to_string(result_payload.resulting_life_current) + "/" +
        std::to_string(result_payload.resulting_life_max) +
        " resulting_mana=" + std::to_string(result_payload.resulting_mana_current) + "/" +
        std::to_string(result_payload.resulting_mana_max) +
        " item_type_id=" +
            HexString(static_cast<uintptr_t>(result_payload.item_type_id)) +
        " item_recipe_uid=" + std::to_string(result_payload.item_recipe_uid) +
        " item_slot=" + std::to_string(result_payload.item_slot) +
        " stack_count=" + std::to_string(result_payload.stack_count) +
        " inventory_revision=" + std::to_string(result_payload.inventory_revision) +
        " powerup_kind=" +
            std::to_string(
                static_cast<std::int32_t>(
                    result_payload.powerup_kind)) +
        " powerup_skill_entry_index=" +
            std::to_string(
                result_payload.powerup_skill_entry_index) +
        " powerup_skill_resulting_active=" +
            std::to_string(
                result_payload.powerup_skill_resulting_active) +
        " damage_x4_remaining_ticks=" +
            std::to_string(
                result_payload.damage_x4_remaining_ticks) +
        " deactivated=" + std::to_string(deactivated ? 1 : 0) +
        (powerup_apply_error.empty()
             ? ""
             : " powerup_error=" + powerup_apply_error) +
        " gameplay_thread=1" +
        " seh=" + HexString(static_cast<uintptr_t>(deactivation.exception_code)));
}

#include "completed_host_loot_pickups.inl"

#include "loot_pickup_packet_handlers.inl"
