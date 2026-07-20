void ApplyLootPickupRequestPacket(
    const LootPickupRequestPacket& packet,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    if (!g_local_transport.is_host ||
        packet.participant_id == 0 ||
        packet.participant_id == g_local_transport.local_peer_id ||
        packet.network_drop_id == 0 ||
        packet.request_sequence == 0) {
        return;
    }

    UpsertPeerEndpoint(from, packet.participant_id, now_ms);
    if (IsLootPickupRequestSequenceDuplicate(packet)) {
        return;
    }

    const auto pending_it =
        g_local_transport.pending_host_loot_pickups_by_drop_id.find(
            packet.network_drop_id);
    if (pending_it != g_local_transport.pending_host_loot_pickups_by_drop_id.end()) {
        RememberLootPickupRequestSequence(packet);
        if (pending_it->second.packet.participant_id == packet.participant_id) {
            if (!pending_it->second.awaiting_powerup_preparation) {
                pending_it->second.packet = packet;
            }
            pending_it->second.endpoint = from;
            Log(
                "Multiplayer coalesced a retry for pending host loot pickup. "
                "participant_id=" + std::to_string(packet.participant_id) +
                " network_drop_id=" + std::to_string(packet.network_drop_id) +
                " request_sequence=" + std::to_string(packet.request_sequence));
            return;
        }

        const auto runtime_state = SnapshotRuntimeState();
        SendLootPickupResult(
            packet,
            from,
            LootPickupResultCode::AlreadyGone,
            pending_it->second.drop_kind,
            BuildLootPickupResultPayloadFromParticipant(
                FindParticipant(runtime_state, packet.participant_id)));
        return;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* participant = FindParticipant(runtime_state, packet.participant_id);

    SDModSceneActorState actor;
    LootDropSnapshotPacketState drop{};
    if (!TryFindHostRunLootDropByNetworkId(packet.network_drop_id, &actor, &drop)) {
        SendLootPickupResult(
            packet,
            from,
            LootPickupResultCode::AlreadyGone,
            LootDropKind::Unknown,
            BuildLootPickupResultPayloadFromParticipant(participant));
        RememberLootPickupRequestSequence(packet);
        Log(
            "Multiplayer loot pickup rejected. reason=drop_not_found participant_id=" +
            std::to_string(packet.participant_id) +
            " network_drop_id=" + std::to_string(packet.network_drop_id));
        return;
    }

    std::string reject_reason;
    LootPickupResultCode result_code = LootPickupResultCode::Rejected;
    if (!ValidateLootPickupRequest(packet, participant, drop, &reject_reason, &result_code)) {
        SendLootPickupResult(
            packet,
            from,
            result_code,
            LootDropKindFromPacketValue(drop.drop_kind),
            BuildLootPickupResultPayloadFromParticipant(participant));
        RememberLootPickupRequestSequence(packet);
        Log(
            "Multiplayer loot pickup rejected. reason=" + reject_reason +
            " participant_id=" + std::to_string(packet.participant_id) +
            " network_drop_id=" + std::to_string(packet.network_drop_id));
        return;
    }

    const auto drop_kind = LootDropKindFromPacketValue(drop.drop_kind);
    LootPickupResultPayload payload = BuildLootPickupResultPayloadFromParticipant(participant);
    PreparedPowerupReward prepared_powerup;
    std::string powerup_prepare_error;
    bool payload_ready = false;
    if (drop_kind == LootDropKind::Gold) {
        payload.amount = drop.amount;
        payload_ready = drop.amount > 0;
    } else if (drop_kind == LootDropKind::Orb) {
        payload_ready = TryBuildAcceptedOrbLootPickupPayload(drop, participant, &payload);
    } else if (drop_kind == LootDropKind::Item || drop_kind == LootDropKind::Potion) {
        payload_ready = TryBuildAcceptedItemLootPickupPayload(drop, participant, &payload);
    } else if (drop_kind == LootDropKind::Powerup) {
        payload_ready =
            participant != nullptr &&
            TryPreparePowerupReward(
                drop,
                *participant,
                packet.participant_id,
                false,
                &prepared_powerup,
                &powerup_prepare_error);
        if (payload_ready) {
            payload.powerup_kind = prepared_powerup.kind;
        }
    }

    if (!payload_ready &&
        drop_kind == LootDropKind::Powerup &&
        IsPowerupPreparationPendingMaterializationError(
            powerup_prepare_error)) {
        PendingHostLootPickup pending;
        pending.packet = packet;
        pending.endpoint = from;
        pending.drop_kind = drop_kind;
        pending.payload = payload;
        pending.actor_address = actor.actor_address;
        pending.queued_ms = now_ms;
        pending.awaiting_powerup_preparation = true;
        g_local_transport.pending_host_loot_pickups_by_drop_id.emplace(
            packet.network_drop_id,
            std::move(pending));
        RememberLootPickupRequestSequence(packet);
        Log(
            "Multiplayer powerup pickup deferred pending participant "
            "progression materialization. participant_id=" +
            std::to_string(packet.participant_id) +
            " network_drop_id=" +
            std::to_string(packet.network_drop_id));
        return;
    }

    if (!payload_ready) {
        SendLootPickupResult(
            packet,
            from,
            LootPickupResultCode::Rejected,
            drop_kind,
            BuildLootPickupResultPayloadFromParticipant(participant));
        RememberLootPickupRequestSequence(packet);
        Log(
            "Multiplayer loot pickup rejected. reason=reward_payload_unavailable "
            "participant_id=" + std::to_string(packet.participant_id) +
            " network_drop_id=" + std::to_string(packet.network_drop_id) +
            (powerup_prepare_error.empty()
                 ? ""
                 : " error=" + powerup_prepare_error));
        return;
    }

    std::string queue_error;
    if (!sdmod::QueueHostLootDropDeactivation(
            packet.run_nonce,
            packet.network_drop_id,
            actor.actor_address,
            drop_kind,
            &queue_error)) {
        SendLootPickupResult(
            packet,
            from,
            LootPickupResultCode::Rejected,
            drop_kind,
            BuildLootPickupResultPayloadFromParticipant(participant));
        RememberLootPickupRequestSequence(packet);
        Log(
            "Multiplayer loot pickup rejected. reason=gameplay_deactivation_queue "
            "participant_id=" + std::to_string(packet.participant_id) +
            " network_drop_id=" + std::to_string(packet.network_drop_id) +
            " error=" + queue_error);
        return;
    }

    PendingHostLootPickup pending;
    pending.packet = packet;
    pending.endpoint = from;
    pending.drop_kind = drop_kind;
    pending.payload = payload;
    pending.powerup = std::move(prepared_powerup);
    pending.actor_address = actor.actor_address;
    pending.queued_ms = now_ms;
    pending.powerup_prepared =
        drop_kind == LootDropKind::Powerup;
    g_local_transport.pending_host_loot_pickups_by_drop_id.emplace(
        packet.network_drop_id,
        std::move(pending));
    RememberLootPickupRequestSequence(packet);
    Log(
        "Multiplayer loot pickup queued for gameplay-thread deactivation. participant_id=" +
        std::to_string(packet.participant_id) +
        " network_drop_id=" + std::to_string(packet.network_drop_id) +
        " kind=" + LootDropKindLabel(drop_kind));
}

void ProcessPendingHostPowerupPreparations(
    std::uint64_t now_ms) {
    if (!g_local_transport.is_host) {
        return;
    }

    std::vector<std::uint64_t> pending_drop_ids;
    for (const auto& entry :
         g_local_transport.pending_host_loot_pickups_by_drop_id) {
        if (entry.second.awaiting_powerup_preparation) {
            pending_drop_ids.push_back(entry.first);
        }
    }

    for (const auto network_drop_id : pending_drop_ids) {
        const auto pending_it =
            g_local_transport.pending_host_loot_pickups_by_drop_id.find(
                network_drop_id);
        if (pending_it ==
                g_local_transport.pending_host_loot_pickups_by_drop_id.end() ||
            !pending_it->second.awaiting_powerup_preparation) {
            continue;
        }
        auto& pending = pending_it->second;
        const bool expired =
            now_ms - pending.queued_ms >=
            kPowerupPreparationMaterializationTimeoutMs;

        const auto runtime_state = SnapshotRuntimeState();
        const auto* participant =
            FindParticipant(
                runtime_state,
                pending.packet.participant_id);
        SDModSceneActorState actor;
        LootDropSnapshotPacketState drop{};
        if (participant == nullptr ||
            !TryFindHostRunLootDropByNetworkId(
                network_drop_id,
                &actor,
                &drop)) {
            if (!expired) {
                continue;
            }
            SendLootPickupResult(
                pending.packet,
                pending.endpoint,
                LootPickupResultCode::AlreadyGone,
                pending.drop_kind,
                BuildLootPickupResultPayloadFromParticipant(
                    participant));
            Log(
                "Multiplayer deferred powerup pickup expired before "
                "materialization. participant_id=" +
                std::to_string(
                    pending.packet.participant_id) +
                " network_drop_id=" +
                std::to_string(network_drop_id));
            g_local_transport.pending_host_loot_pickups_by_drop_id.erase(
                pending_it);
            continue;
        }

        if (!pending.powerup_prepared) {
            PreparedPowerupReward prepared;
            std::string prepare_error;
            if (!TryPreparePowerupReward(
                    drop,
                    *participant,
                    pending.packet.participant_id,
                    false,
                    &prepared,
                    &prepare_error)) {
                if (IsPowerupPreparationPendingMaterializationError(
                        prepare_error) &&
                    !expired) {
                    continue;
                }
                SendLootPickupResult(
                    pending.packet,
                    pending.endpoint,
                    LootPickupResultCode::Rejected,
                    pending.drop_kind,
                    BuildLootPickupResultPayloadFromParticipant(
                        participant));
                Log(
                    "Multiplayer deferred powerup pickup preparation failed. "
                    "participant_id=" +
                    std::to_string(
                        pending.packet.participant_id) +
                    " network_drop_id=" +
                    std::to_string(network_drop_id) +
                    " error=" + prepare_error);
                g_local_transport.pending_host_loot_pickups_by_drop_id.erase(
                    pending_it);
                continue;
            }

            pending.payload =
                BuildLootPickupResultPayloadFromParticipant(
                    participant);
            pending.payload.powerup_kind = prepared.kind;
            pending.powerup = std::move(prepared);
            pending.actor_address = actor.actor_address;
            pending.powerup_prepared = true;
        }

        std::string queue_error;
        if (!sdmod::QueueHostLootDropDeactivation(
                pending.packet.run_nonce,
                network_drop_id,
                actor.actor_address,
                pending.drop_kind,
                &queue_error)) {
            if (!expired) {
                continue;
            }
            SendLootPickupResult(
                pending.packet,
                pending.endpoint,
                LootPickupResultCode::Rejected,
                pending.drop_kind,
                BuildLootPickupResultPayloadFromParticipant(
                    participant));
            Log(
                "Multiplayer "
                "deferred powerup pickup deactivation queue expired. "
                "participant_id=" +
                std::to_string(
                    pending.packet.participant_id) +
                " network_drop_id=" +
                std::to_string(network_drop_id) +
                " error=" + queue_error);
            g_local_transport.pending_host_loot_pickups_by_drop_id.erase(
                pending_it);
            continue;
        }

        pending.awaiting_powerup_preparation = false;
        Log(
            "Multiplayer deferred powerup pickup resumed after participant "
            "progression materialized. participant_id=" +
            std::to_string(pending.packet.participant_id) +
            " network_drop_id=" +
            std::to_string(network_drop_id));
    }
}

void ApplyLootPickupResultPacket(
    const LootPickupResultPacket& packet,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    if (packet.authority_participant_id == 0 ||
        packet.authority_participant_id == g_local_transport.local_peer_id ||
        packet.participant_id == 0 ||
        packet.network_drop_id == 0 ||
        packet.request_sequence == 0) {
        return;
    }

    UpsertPeerEndpoint(from, packet.authority_participant_id, now_ms);
    const auto result_code = LootPickupResultCodeFromPacketValue(packet.result_code);
    const auto drop_kind = LootDropKindFromPacketValue(packet.drop_kind);
    if (result_code == LootPickupResultCode::Accepted &&
        packet.participant_id == g_local_transport.local_peer_id &&
        drop_kind == LootDropKind::Gold) {
        if (!TryWriteLocalGlobalGold(packet.resulting_gold)) {
            Log(
                "Multiplayer loot pickup result accepted but local gold write failed. resulting_gold=" +
                std::to_string(packet.resulting_gold) +
                " network_drop_id=" + std::to_string(packet.network_drop_id));
        }
    }
    if (result_code == LootPickupResultCode::Accepted &&
        packet.participant_id == g_local_transport.local_peer_id &&
        drop_kind == LootDropKind::Orb) {
        if (!TryWriteLocalPlayerOrbResource(
                packet.resource_kind,
                packet.resulting_life_current,
                packet.resulting_life_max,
                packet.resulting_mana_current,
                packet.resulting_mana_max)) {
            Log(
                "Multiplayer loot pickup result accepted but local vitals write failed. resource_delta=" +
                std::to_string(packet.resource_delta) +
                " network_drop_id=" + std::to_string(packet.network_drop_id));
        }
    }
    if (result_code == LootPickupResultCode::Accepted &&
        drop_kind == LootDropKind::Powerup) {
        PowerupRewardKind powerup_kind =
            PowerupRewardKind::BonusSkillPoint;
        const bool duplicate_result =
            g_local_transport
                    .native_applied_powerup_result_drop_ids.find(
                        packet.network_drop_id) !=
                g_local_transport
                    .native_applied_powerup_result_drop_ids.end();
        bool native_apply_complete = duplicate_result;
        std::string powerup_apply_error;
        if (!duplicate_result &&
            TryResolvePowerupRewardKind(
                packet.powerup_kind,
                &powerup_kind)) {
            if (powerup_kind ==
                PowerupRewardKind::BonusSkillPoint) {
                native_apply_complete = true;
            } else if (
                powerup_kind ==
                    PowerupRewardKind::RandomSkillRank &&
                packet.powerup_skill_entry_index >= 0 &&
                packet.powerup_skill_apply_count > 0 &&
                packet.powerup_skill_resulting_active > 0) {
                std::uint16_t native_active = 0;
                native_apply_complete =
                    TryReadParticipantProgressionEntryActive(
                        packet.participant_id,
                        packet.powerup_skill_entry_index,
                        &native_active) &&
                    native_active ==
                        packet.powerup_skill_resulting_active;
                if (!native_apply_complete) {
                    BotSkillChoiceOption option;
                    option.option_id =
                        packet.powerup_skill_entry_index;
                    option.apply_count =
                        packet.powerup_skill_apply_count;
                    const bool applied =
                        packet.participant_id ==
                                g_local_transport.local_peer_id
                            ? ApplyLocalPlayerSkillChoiceOption(
                                  option,
                                  &powerup_apply_error)
                            : HydrateAuthoritativeRemoteProgressionEntryState(
                                  packet.participant_id,
                                  packet.powerup_skill_entry_index,
                                  packet.powerup_skill_resulting_active,
                                  1,
                                  &powerup_apply_error);
                    native_apply_complete =
                        applied &&
                        TryReadParticipantProgressionEntryActive(
                            packet.participant_id,
                            packet.powerup_skill_entry_index,
                            &native_active) &&
                        native_active ==
                            packet.powerup_skill_resulting_active;
                }
            } else if (
                powerup_kind ==
                    PowerupRewardKind::DamageX4 &&
                packet.damage_x4_remaining_ticks > 0) {
                native_apply_complete =
                    TryWriteParticipantDamageX4Ticks(
                        packet.participant_id,
                        packet.participant_id ==
                            g_local_transport.local_peer_id,
                        (std::clamp)(
                            packet.damage_x4_remaining_ticks,
                            std::int32_t{1},
                            kParticipantDamageX4MaxDurationTicks));
                if (!native_apply_complete) {
                    powerup_apply_error =
                        "damage timer write failed";
                }
            }
        }
        if (native_apply_complete) {
            g_local_transport
                .native_applied_powerup_result_drop_ids.insert(
                    packet.network_drop_id);
            if (g_local_transport
                    .native_applied_powerup_result_drop_ids.size() >
                512) {
                g_local_transport
                    .native_applied_powerup_result_drop_ids.clear();
                g_local_transport
                    .native_applied_powerup_result_drop_ids.insert(
                        packet.network_drop_id);
            }
        } else {
            Log(
                "Multiplayer powerup pickup result native apply "
                "deferred to participant state reconciliation. "
                "participant_id=" +
                std::to_string(packet.participant_id) +
                " network_drop_id=" +
                std::to_string(packet.network_drop_id) +
                " error=" + powerup_apply_error);
        }
    }

    PublishLootPickupResultRuntimeInfo(packet, now_ms);
    if (result_code == LootPickupResultCode::Accepted &&
        packet.participant_id == g_local_transport.local_peer_id &&
        (drop_kind == LootDropKind::Item || drop_kind == LootDropKind::Potion)) {
        const bool item_color_state_valid =
            (packet.result_flags & LootPickupResultFlagItemColorState) != 0;
        std::array<std::uint8_t, kParticipantVisualLinkColorBlockBytes>
            item_color_state = {};
        if (item_color_state_valid) {
            std::memcpy(
                item_color_state.data(),
                packet.item_color_state,
                item_color_state.size());
        }
        std::string native_inventory_error;
        if (!QueueNativeInventoryCredit(
                packet.authority_participant_id,
                packet.run_nonce,
                packet.network_drop_id,
                packet.item_type_id,
                packet.item_recipe_uid,
                item_color_state,
                item_color_state_valid,
                packet.item_slot,
                packet.stack_count,
                packet.inventory_revision,
                &native_inventory_error)) {
            Log(
                "Multiplayer item pickup accepted but native inventory credit was not queued. "
                "network_drop_id=" + std::to_string(packet.network_drop_id) +
                " item_type_id=" +
                HexString(static_cast<uintptr_t>(packet.item_type_id)) +
                " item_recipe_uid=" + std::to_string(packet.item_recipe_uid) +
                " inventory_revision=" + std::to_string(packet.inventory_revision) +
                " error=" + native_inventory_error);
        }
    }
    Log(
        "Multiplayer loot pickup result applied. authority_participant_id=" +
        std::to_string(packet.authority_participant_id) +
        " participant_id=" + std::to_string(packet.participant_id) +
        " request_sequence=" + std::to_string(packet.request_sequence) +
        " network_drop_id=" + std::to_string(packet.network_drop_id) +
        " result=" + LootPickupResultCodeLabel(result_code) +
        " kind=" + LootDropKindLabel(drop_kind) +
        " amount=" + std::to_string(packet.amount) +
        " resulting_gold=" + std::to_string(packet.resulting_gold) +
        " gold_revision=" + std::to_string(packet.gold_revision) +
        " resource_kind=" + std::to_string(packet.resource_kind) +
        " resource_delta=" + std::to_string(packet.resource_delta) +
        " item_type_id=" + HexString(static_cast<uintptr_t>(packet.item_type_id)) +
        " item_recipe_uid=" + std::to_string(packet.item_recipe_uid) +
        " item_slot=" + std::to_string(packet.item_slot) +
        " stack_count=" + std::to_string(packet.stack_count) +
        " inventory_revision=" + std::to_string(packet.inventory_revision) +
        " powerup_kind=" +
            std::to_string(packet.powerup_kind) +
        " powerup_skill_entry_index=" +
            std::to_string(
                packet.powerup_skill_entry_index) +
        " powerup_skill_resulting_active=" +
            std::to_string(
                packet.powerup_skill_resulting_active) +
        " damage_x4_remaining_ticks=" +
            std::to_string(
                packet.damage_x4_remaining_ticks));
}
