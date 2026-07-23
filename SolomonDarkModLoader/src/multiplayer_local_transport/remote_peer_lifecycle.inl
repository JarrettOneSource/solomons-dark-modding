void ResetRemoteParticipantSessionEpoch(
    std::uint64_t participant_id,
    bool configured_authority_disconnected,
    bool preserve_session_nonce_history) {
    std::unique_lock<std::recursive_mutex> picker_lock(
        g_local_level_up_picker_mutex,
        std::defer_lock);
    if (configured_authority_disconnected) {
        picker_lock.lock();
    }

    MarkHostLevelUpBarrierParticipantDisconnected(
        participant_id,
        static_cast<std::uint64_t>(GetTickCount64()));
    SDModParticipantGameplayState gameplay_state;
    if (TryGetParticipantGameplayState(participant_id, &gameplay_state) &&
        gameplay_state.entity_materialized) {
        std::string destroy_error;
        if (!QueueParticipantDestroy(participant_id, &destroy_error)) {
            Log(
                "Multiplayer disconnected participant entity destroy could not be queued. "
                "participant_id=" + std::to_string(participant_id) +
                " error=" + destroy_error);
        }
    }

    g_local_transport.last_state_packet_sequence_by_participant.erase(participant_id);
    g_local_transport.last_participant_frame_sequence_by_participant.erase(
        participant_id);
    g_local_transport.last_lua_ui_action_request_by_participant.erase(
        participant_id);
    if (!preserve_session_nonce_history) {
        g_local_transport.session_nonce_by_participant.erase(participant_id);
        g_local_transport.retired_session_nonces_by_participant.erase(participant_id);
    }
    g_local_transport.last_cast_sequence_by_participant.erase(participant_id);
    g_local_transport.last_spell_effect_packet_sequence_by_participant.erase(
        participant_id);
    g_local_transport.last_air_chain_packet_sequence_by_participant.erase(
        participant_id);
    g_local_transport.last_participant_vitals_correction_sequence_by_authority.erase(
        participant_id);
    g_local_transport.pending_participant_vitals_corrections_by_participant.erase(
        participant_id);
    g_local_transport.last_participant_vitals_correction_send_ms_by_participant.erase(
        participant_id);
    g_local_transport.remote_cast_inputs_by_participant.erase(participant_id);
    g_local_transport.last_enemy_claim_sequence_by_participant.erase(participant_id);
    g_local_transport.last_loot_pickup_request_sequence_by_participant.erase(
        participant_id);
    g_local_transport.pending_level_up_offer_targets_by_participant.erase(
        participant_id);
    g_local_transport.native_progression_reconcile_by_participant.erase(
        participant_id);
    g_local_transport.host_menu_pause_requests_by_participant.erase(participant_id);
    g_local_transport.lua_mod_checkpointed_participants.erase(participant_id);

    for (auto it = g_local_transport.issued_level_up_offers_by_id.begin();
         it != g_local_transport.issued_level_up_offers_by_id.end();) {
        if (it->second.target_participant_id != participant_id) {
            ++it;
            continue;
        }
        g_local_transport.native_applied_level_up_result_offer_ids.erase(it->first);
        g_local_transport.confirmed_auto_pick_level_up_offer_ids.erase(it->first);
        it = g_local_transport.issued_level_up_offers_by_id.erase(it);
    }

    {
        std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
        g_queued_host_participant_vitals_corrections.erase(
            std::remove_if(
                g_queued_host_participant_vitals_corrections.begin(),
                g_queued_host_participant_vitals_corrections.end(),
                [&](const QueuedHostParticipantVitalsCorrection& correction) {
                    return correction.target_participant_id == participant_id;
                }),
            g_queued_host_participant_vitals_corrections.end());
        g_queued_authoritative_lua_item_grants.erase(
            std::remove_if(
                g_queued_authoritative_lua_item_grants.begin(),
                g_queued_authoritative_lua_item_grants.end(),
                [&](const QueuedAuthoritativeLuaItemGrant& grant) {
                    return grant.target_participant_id == participant_id;
                }),
            g_queued_authoritative_lua_item_grants.end());
        g_queued_lua_registered_spell_casts.erase(
            std::remove_if(
                g_queued_lua_registered_spell_casts.begin(),
                g_queued_lua_registered_spell_casts.end(),
                [&](const QueuedLuaRegisteredSpellCast& cast) {
                    return cast.request.owner_participant_id == participant_id;
                }),
            g_queued_lua_registered_spell_casts.end());
        if (configured_authority_disconnected) {
            g_queued_local_cast_events.clear();
            g_queued_local_enemy_damage_claims.clear();
            ClearLocalLootPickupRequestStateLocked();
            g_queued_local_level_up_choices.clear();
            g_queued_lua_ui_action_requests.clear();
            g_queued_local_air_chain_frame = QueuedLocalAirChainFrame{};
            g_have_queued_local_air_chain_frame = false;
        }
    }

    if (configured_authority_disconnected) {
        g_local_transport.last_client_host_run_request_ms = 0;
        g_local_transport.last_client_host_region_request_ms = 0;
        g_local_transport.last_applied_participant_vitals_correction_sequence = 0;
        g_local_transport.active_local_cast_input = ActiveLocalCastInput{};
        g_local_transport.pending_air_chain_terminals.clear();
        g_local_transport.local_spell_effects_by_address.clear();
        g_local_transport.local_spell_effect_tombstones.clear();
        g_local_transport.spell_effect_snapshot_had_effects = false;
        g_local_transport.pending_lua_mod_stream_assemblies.clear();
        g_local_transport.completed_lua_mod_stream_messages.clear();
        g_local_transport.last_lua_mod_stream_applied_sequence = 0;
        g_local_transport.received_lua_item_grant_request_ids.clear();
        g_local_transport.received_lua_item_grant_request_order.clear();
        g_local_transport.received_lua_registered_spell_cast_request_ids.clear();
        g_local_transport.received_lua_registered_spell_cast_request_order.clear();
        {
            std::lock_guard<std::mutex> snapshot_lock(
                g_lua_registered_spell_effect_snapshot_mutex);
            g_local_transport
                .pending_lua_registered_spell_effect_snapshots.erase(
                    participant_id);
            g_local_transport
                .completed_lua_registered_spell_effect_snapshots.erase(
                    participant_id);
        }
        ResetLuaModStateStore();
    }

    auto suppressed_participant = participant_id;
    (void)g_remote_native_progression_reconcile_suppressed_for_test
        .compare_exchange_strong(
            suppressed_participant,
            0,
            std::memory_order_acq_rel,
            std::memory_order_acquire);

    {
        std::lock_guard<std::mutex> lock(g_air_chain_runtime_mutex);
        g_replicated_air_chain_snapshots_by_participant.erase(participant_id);
        g_replicated_air_chain_history_runtime.erase(
            std::remove_if(
                g_replicated_air_chain_history_runtime.begin(),
                g_replicated_air_chain_history_runtime.end(),
                [&](const AirChainSnapshotRuntimeInfo& snapshot) {
                    return snapshot.owner_participant_id == participant_id;
                }),
            g_replicated_air_chain_history_runtime.end());
        if (g_air_chain_apply_runtime.owner_participant_id == participant_id) {
            g_air_chain_apply_runtime = AirChainApplyRuntimeInfo{};
        }
    }

    UpdateRuntimeState([&](RuntimeState& state) {
        state.participants.erase(
            std::remove_if(
                state.participants.begin(),
                state.participants.end(),
                [&](const ParticipantInfo& participant) {
                    return participant.participant_id == participant_id &&
                           IsRemoteParticipant(participant);
                }),
            state.participants.end());
        state.spell_effect_snapshots.erase(
            std::remove_if(
                state.spell_effect_snapshots.begin(),
                state.spell_effect_snapshots.end(),
                [&](const SpellEffectSnapshotRuntimeInfo& snapshot) {
                    return snapshot.owner_participant_id == participant_id;
                }),
            state.spell_effect_snapshots.end());
        if (std::any_of(
                state.spell_effect_apply.bindings.begin(),
                state.spell_effect_apply.bindings.end(),
                [&](const SpellEffectBindingRuntimeInfo& binding) {
                    return binding.owner_participant_id == participant_id;
                })) {
            state.spell_effect_apply = SpellEffectApplyRuntimeInfo{};
        }
        state.air_chain_snapshots.erase(
            std::remove_if(
                state.air_chain_snapshots.begin(),
                state.air_chain_snapshots.end(),
                [&](const AirChainSnapshotRuntimeInfo& snapshot) {
                    return snapshot.owner_participant_id == participant_id;
                }),
            state.air_chain_snapshots.end());
        state.air_chain_snapshot_history.erase(
            std::remove_if(
                state.air_chain_snapshot_history.begin(),
                state.air_chain_snapshot_history.end(),
                [&](const AirChainSnapshotRuntimeInfo& snapshot) {
                    return snapshot.owner_participant_id == participant_id;
                }),
            state.air_chain_snapshot_history.end());
        if (state.air_chain_apply.owner_participant_id == participant_id) {
            state.air_chain_apply = AirChainApplyRuntimeInfo{};
        }
        if (state.last_loot_pickup_result.authority_participant_id == participant_id ||
            state.last_loot_pickup_result.participant_id == participant_id) {
            state.last_loot_pickup_result = LootPickupResultRuntimeInfo{};
        }
        if (state.active_level_up_offer.authority_participant_id == participant_id ||
            state.active_level_up_offer.target_participant_id == participant_id) {
            state.active_level_up_offer = LevelUpOfferRuntimeInfo{};
        }
        if (state.last_level_up_choice_result.authority_participant_id == participant_id ||
            state.last_level_up_choice_result.target_participant_id == participant_id) {
            state.last_level_up_choice_result = LevelUpChoiceResultRuntimeInfo{};
        }
        if (state.level_up_wait_status.authority_participant_id == participant_id) {
            state.level_up_wait_status = LevelUpWaitStatusRuntimeInfo{};
        } else {
            auto& waiting = state.level_up_wait_status.waiting_participant_ids;
            waiting.erase(
                std::remove(waiting.begin(), waiting.end(), participant_id),
                waiting.end());
            state.level_up_wait_status.pause_active = !waiting.empty();
        }
        if (configured_authority_disconnected &&
            state.shared_gameplay_pause.authority_participant_id ==
                participant_id) {
            const bool local_request_active =
                state.shared_gameplay_pause.local_request_active;
            const auto local_request_epoch =
                state.shared_gameplay_pause.local_request_epoch;
            state.shared_gameplay_pause = SharedGameplayPauseRuntimeInfo{};
            state.shared_gameplay_pause.local_request_active =
                local_request_active;
            state.shared_gameplay_pause.local_request_epoch =
                local_request_epoch;
        }
        if (state.world_snapshot.authority_participant_id == participant_id) {
            state.world_snapshot = WorldSnapshotRuntimeInfo{};
            state.world_snapshot_history.clear();
            state.world_snapshot_apply = WorldSnapshotApplyRuntimeInfo{};
        }
        if (state.loot_snapshot.authority_participant_id == participant_id) {
            state.loot_snapshot = LootSnapshotRuntimeInfo{};
        }
    });

    Log(
        "Multiplayer transport reset disconnected participant session epoch. "
        "participant_id=" + std::to_string(participant_id));
}
