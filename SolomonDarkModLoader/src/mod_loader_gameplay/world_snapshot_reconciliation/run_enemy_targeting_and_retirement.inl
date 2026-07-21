uintptr_t ResolveReplicatedRunEnemyTargetActor(
    std::uint64_t target_participant_id) {
    if (target_participant_id == 0) {
        return 0;
    }

    if (target_participant_id == multiplayer::GetLocalTransportParticipantId()) {
        SDModPlayerState player_state;
        if (TryGetPlayerState(&player_state) &&
            player_state.valid &&
            player_state.actor_address != 0) {
            return player_state.actor_address;
        }
        return 0;
    }

    SDModParticipantGameplayState gameplay_state;
    if (TryGetParticipantGameplayState(target_participant_id, &gameplay_state) &&
        gameplay_state.available &&
        gameplay_state.entity_materialized &&
        gameplay_state.actor_address != 0) {
        return gameplay_state.actor_address;
    }

    std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
    const auto* binding = FindParticipantEntity(target_participant_id);
    if (binding == nullptr ||
        !IsWizardParticipantKind(binding->kind) ||
        binding->actor_address == 0) {
        return 0;
    }
    return binding->actor_address;
}

uintptr_t ResolveReplicatedRunEnemyNativeTargetActor(
    uintptr_t hostile_actor_address,
    const multiplayer::WorldActorSnapshot& authoritative_actor) {
    if (hostile_actor_address == 0 ||
        authoritative_actor.target_native_type_id == 0 ||
        authoritative_actor.target_actor_slot < 0 ||
        authoritative_actor.target_world_slot < 0) {
        return 0;
    }

    uintptr_t hostile_world = 0;
    std::int32_t hostile_actor_slot = -1;
    std::int32_t hostile_world_slot = -1;
    if (!TryReadActorWorldTargetSlotState(
            hostile_actor_address,
            &hostile_world,
            &hostile_actor_slot,
            &hostile_world_slot) ||
        hostile_world == 0) {
        return 0;
    }

    std::vector<SDModSceneActorState> actors;
    if (!TryListSceneActors(&actors)) {
        return 0;
    }

    for (const auto& actor : actors) {
        if (!actor.valid ||
            actor.actor_address == 0 ||
            actor.actor_address == hostile_actor_address ||
            actor.owner_address != hostile_world ||
            actor.object_type_id != authoritative_actor.target_native_type_id ||
            actor.actor_slot != authoritative_actor.target_actor_slot ||
            actor.world_slot != authoritative_actor.target_world_slot ||
            IsActorRuntimeDead(actor.actor_address)) {
            continue;
        }
        return actor.actor_address;
    }

    return 0;
}

bool ClearRunEnemyNativeTargetFields(uintptr_t actor_address) {
    if (actor_address == 0 ||
        kActorCurrentTargetActorOffset == 0 ||
        kHostileTargetBucketDeltaOffset == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t current_target_actor = 0;
    std::int32_t current_bucket_delta = 0;
    (void)memory.TryReadField(actor_address, kActorCurrentTargetActorOffset, &current_target_actor);
    (void)memory.TryReadField(actor_address, kHostileTargetBucketDeltaOffset, &current_bucket_delta);

    bool wrote = false;
    if (current_target_actor != 0) {
        wrote = memory.TryWriteField<uintptr_t>(
            actor_address,
            kActorCurrentTargetActorOffset,
            0) || wrote;
    }
    if (current_bucket_delta != 0) {
        wrote = memory.TryWriteField<std::int32_t>(
            actor_address,
            kHostileTargetBucketDeltaOffset,
            0) || wrote;
    }
    return wrote;
}

bool ApplyReplicatedRunEnemyTarget(
    uintptr_t actor_address,
    const multiplayer::WorldActorSnapshot& authoritative_actor,
    const multiplayer::ParticipantSceneIntent& scene_intent) {
    if (actor_address == 0 ||
        scene_intent.kind != multiplayer::ParticipantSceneIntentKind::Run ||
        !authoritative_actor.tracked_enemy ||
        !authoritative_actor.target_authoritative ||
        kActorCurrentTargetActorOffset == 0 ||
        kHostileTargetBucketDeltaOffset == 0 ||
        kActorWorldBucketStride == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t current_target_actor = 0;
    std::int32_t current_bucket_delta = 0;
    (void)memory.TryReadField(actor_address, kActorCurrentTargetActorOffset, &current_target_actor);
    (void)memory.TryReadField(actor_address, kHostileTargetBucketDeltaOffset, &current_bucket_delta);

    const uintptr_t target_actor =
        authoritative_actor.target_participant_id != 0
            ? ResolveReplicatedRunEnemyTargetActor(authoritative_actor.target_participant_id)
            : ResolveReplicatedRunEnemyNativeTargetActor(actor_address, authoritative_actor);
    if (target_actor == 0 || IsActorRuntimeDead(target_actor)) {
        return multiplayer::IsLocalTransportClient() ? ClearRunEnemyNativeTargetFields(actor_address) : false;
    }

    uintptr_t hostile_world = 0;
    std::int32_t hostile_actor_slot = -1;
    std::int32_t hostile_world_slot = -1;
    uintptr_t target_world = 0;
    std::int32_t target_actor_slot = -1;
    std::int32_t target_world_slot = -1;
    if (!TryReadActorWorldTargetSlotState(
            actor_address,
            &hostile_world,
            &hostile_actor_slot,
            &hostile_world_slot) ||
        !TryReadActorWorldTargetSlotState(
            target_actor,
            &target_world,
            &target_actor_slot,
            &target_world_slot) ||
        hostile_world != target_world) {
        return multiplayer::IsLocalTransportClient() ? ClearRunEnemyNativeTargetFields(actor_address) : false;
    }

    const auto target_bucket_delta =
        target_actor_slot * static_cast<std::int32_t>(kActorWorldBucketStride) + target_world_slot -
        hostile_actor_slot * static_cast<std::int32_t>(kActorWorldBucketStride);
    bool wrote = false;
    if (current_target_actor != target_actor) {
        wrote = memory.TryWriteField<uintptr_t>(
            actor_address,
            kActorCurrentTargetActorOffset,
            target_actor) || wrote;
    }
    if (current_bucket_delta != target_bucket_delta) {
        wrote = memory.TryWriteField<std::int32_t>(
            actor_address,
            kHostileTargetBucketDeltaOffset,
            target_bucket_delta) || wrote;
    }
    return wrote;
}

void RefreshLatestRunEnemySnapshotCache(
    const multiplayer::WorldSnapshotRuntimeInfo& snapshot,
    std::uint64_t now_ms) {
    const bool usable =
        multiplayer::IsLocalTransportClient() &&
        snapshot.valid &&
        snapshot.scene_intent.kind == multiplayer::ParticipantSceneIntentKind::Run &&
        now_ms >= snapshot.received_ms &&
        now_ms - snapshot.received_ms <= kWorldSnapshotApplyStaleMs;
    if (!usable) {
        ClearLatestRunEnemySnapshotCache();
        return;
    }

    if (g_latest_run_enemy_snapshot_cache_valid &&
        g_latest_run_enemy_snapshot_authority_participant_id ==
            snapshot.authority_participant_id &&
        g_latest_run_enemy_snapshot_received_ms == snapshot.received_ms &&
        g_latest_run_enemy_snapshot_sequence == snapshot.sequence &&
        g_latest_run_enemy_snapshot_scene_epoch == snapshot.scene_epoch &&
        g_latest_run_enemy_snapshot_run_nonce == snapshot.run_nonce) {
        return;
    }

    g_latest_run_enemy_snapshots_by_network_id.clear();
    g_latest_run_enemy_snapshots_by_network_id.reserve(snapshot.actors.size());
    for (const auto& actor : snapshot.actors) {
        if (actor.network_actor_id == 0 || !actor.tracked_enemy) {
            continue;
        }
        g_latest_run_enemy_snapshots_by_network_id.insert_or_assign(
            actor.network_actor_id,
            actor);
    }
    g_latest_run_enemy_snapshot_scene_intent = snapshot.scene_intent;
    g_latest_run_enemy_snapshot_authority_participant_id =
        snapshot.authority_participant_id;
    g_latest_run_enemy_snapshot_received_ms = snapshot.received_ms;
    g_latest_run_enemy_snapshot_sequence = snapshot.sequence;
    g_latest_run_enemy_snapshot_scene_epoch = snapshot.scene_epoch;
    g_latest_run_enemy_snapshot_run_nonce = snapshot.run_nonce;
    g_latest_run_enemy_snapshot_cache_valid = true;
}

bool ApplyLatestReplicatedRunEnemyTargetForLocalActor(uintptr_t actor_address, bool clear_unbound) {
    if (actor_address == 0 || !multiplayer::IsLocalTransportClient()) {
        return false;
    }

    const auto network_it = g_replicated_run_network_ids_by_actor.find(actor_address);
    if (network_it == g_replicated_run_network_ids_by_actor.end() || network_it->second == 0) {
        return clear_unbound ? ClearRunEnemyNativeTargetFields(actor_address) : false;
    }

    if (!g_latest_run_enemy_snapshot_cache_valid) {
        return ClearRunEnemyNativeTargetFields(actor_address);
    }

    const auto actor_it =
        g_latest_run_enemy_snapshots_by_network_id.find(network_it->second);
    if (actor_it == g_latest_run_enemy_snapshots_by_network_id.end()) {
        return ClearRunEnemyNativeTargetFields(actor_address);
    }

    return ApplyReplicatedRunEnemyTarget(
        actor_address,
        actor_it->second,
        g_latest_run_enemy_snapshot_scene_intent);
}

bool IsBoundReplicatedRunEnemyActorForLocalClient(uintptr_t actor_address) {
    if (actor_address == 0 || !multiplayer::IsLocalTransportClient()) {
        return false;
    }
    const auto network_it = g_replicated_run_network_ids_by_actor.find(actor_address);
    if (network_it == g_replicated_run_network_ids_by_actor.end() || network_it->second == 0) {
        return false;
    }

    if (!g_latest_run_enemy_snapshot_cache_valid) {
        return false;
    }

    return g_latest_run_enemy_snapshots_by_network_id.find(network_it->second) !=
           g_latest_run_enemy_snapshots_by_network_id.end();
}

bool NeutralizeReplicatedRunEnemyActor(uintptr_t actor_address) {
    if (actor_address == 0) {
        return false;
    }

    bool wrote = ClearRunEnemyNativeTargetFields(actor_address);
    auto& memory = ProcessMemory::Instance();
    if (kActorAnimationDriveStateByteOffset != 0) {
        wrote = memory.TryWriteField<std::uint8_t>(
            actor_address,
            kActorAnimationDriveStateByteOffset,
            0) || wrote;
    }
    if (kActorAnimationMoveDurationTicksOffset != 0) {
        wrote = memory.TryWriteField<std::int32_t>(
            actor_address,
            kActorAnimationMoveDurationTicksOffset,
            0) || wrote;
    }

    uintptr_t control_brain_address = 0;
    if (kActorAnimationSelectionStateOffset == 0 ||
        !memory.TryReadField(
            actor_address,
            kActorAnimationSelectionStateOffset,
            &control_brain_address) ||
        control_brain_address == 0) {
        return wrote;
    }

    if (kActorControlBrainStateIdOffset != 0) {
        wrote = memory.TryWriteValue<std::int32_t>(
            control_brain_address + kActorControlBrainStateIdOffset,
            0) || wrote;
    }
    if (kActorControlBrainTargetSlotOffset != 0) {
        wrote = memory.TryWriteValue<std::int8_t>(
            control_brain_address + kActorControlBrainTargetSlotOffset,
            0) || wrote;
    }
    if (kActorControlBrainTargetHandleOffset != 0) {
        wrote = memory.TryWriteValue<std::int16_t>(
            control_brain_address + kActorControlBrainTargetHandleOffset,
            0) || wrote;
    }
    if (kActorControlBrainRetargetTicksOffset != 0) {
        wrote = memory.TryWriteValue<std::int32_t>(
            control_brain_address + kActorControlBrainRetargetTicksOffset,
            0) || wrote;
    }
    if (kActorControlBrainTargetCooldownTicksOffset != 0) {
        wrote = memory.TryWriteValue<std::int32_t>(
            control_brain_address + kActorControlBrainTargetCooldownTicksOffset,
            0) || wrote;
    }
    if (kActorControlBrainActionCooldownTicksOffset != 0) {
        wrote = memory.TryWriteValue<std::int32_t>(
            control_brain_address + kActorControlBrainActionCooldownTicksOffset,
            0) || wrote;
    }
    if (kActorControlBrainActionBurstTicksOffset != 0) {
        wrote = memory.TryWriteValue<std::int32_t>(
            control_brain_address + kActorControlBrainActionBurstTicksOffset,
            0) || wrote;
    }
    if (kActorControlBrainHeadingLockTicksOffset != 0) {
        wrote = memory.TryWriteValue<std::int32_t>(
            control_brain_address + kActorControlBrainHeadingLockTicksOffset,
            0) || wrote;
    }
    if (kActorControlBrainMoveInputXOffset != 0) {
        wrote = memory.TryWriteValue<float>(
            control_brain_address + kActorControlBrainMoveInputXOffset,
            0.0f) || wrote;
    }
    if (kActorControlBrainMoveInputYOffset != 0) {
        wrote = memory.TryWriteValue<float>(
            control_brain_address + kActorControlBrainMoveInputYOffset,
            0.0f) || wrote;
    }
    return wrote;
}

std::uint32_t ApplyLatestRunEnemyTargetsFromRuntimeSnapshot(
    const multiplayer::WorldSnapshotRuntimeInfo& latest_snapshot,
    std::uint64_t now_ms) {
    if (!multiplayer::IsLocalTransportClient() ||
        latest_snapshot.scene_intent.kind != multiplayer::ParticipantSceneIntentKind::Run) {
        return 0;
    }

    if (!latest_snapshot.valid ||
        latest_snapshot.actors.empty() ||
        now_ms < latest_snapshot.received_ms ||
        now_ms - latest_snapshot.received_ms > kWorldSnapshotApplyStaleMs) {
        return 0;
    }

    std::uint32_t write_count = 0;
    for (const auto& actor : latest_snapshot.actors) {
        if (actor.network_actor_id == 0 ||
            !actor.tracked_enemy ||
            !actor.target_authoritative) {
            continue;
        }

        const auto binding_it = g_replicated_run_bindings_by_network_id.find(actor.network_actor_id);
        if (binding_it == g_replicated_run_bindings_by_network_id.end() ||
            binding_it->second == 0) {
            continue;
        }
        if (ApplyReplicatedRunEnemyTarget(
                binding_it->second,
                actor,
                latest_snapshot.scene_intent)) {
            write_count += 1;
        }
    }
    return write_count;
}

bool RemoveReplicatedSharedHubActor(
    const ReplicatedWorldActorLocalBinding& binding,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (binding.actor.actor_address == 0 ||
        !IsReplicatedSharedHubLifecycleOwnedActorType(binding.actor.object_type_id)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t world_address = 0;
    if (!memory.TryReadField(binding.actor.actor_address, kActorOwnerOffset, &world_address) ||
        world_address == 0) {
        return false;
    }

    const auto unregister_address = memory.ResolveGameAddressOrZero(kActorWorldUnregister);
    if (unregister_address == 0) {
        return false;
    }

    return CallActorWorldUnregisterSafe(
        unregister_address,
        world_address,
        binding.actor.actor_address,
        1,
        exception_code);
}

bool RemoveReplicatedRunActor(
    const ReplicatedWorldActorLocalBinding& binding,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (binding.actor.actor_address == 0 ||
        !ShouldReconcileLocalWorldActor(binding.actor, multiplayer::ParticipantSceneIntentKind::Run)) {
        return false;
    }

    if (binding.actor.tracked_enemy) {
        ClearManualRunEnemyFreeze(binding.actor.actor_address);
        (void)NeutralizeReplicatedRunEnemyActor(binding.actor.actor_address);
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t world_address = 0;
    if (!memory.TryReadField(binding.actor.actor_address, kActorOwnerOffset, &world_address) ||
        world_address == 0) {
        return false;
    }

    const auto unregister_address = memory.ResolveGameAddressOrZero(kActorWorldUnregister);
    if (unregister_address == 0) {
        return false;
    }

    return CallActorWorldUnregisterSafe(
        unregister_address,
        world_address,
        binding.actor.actor_address,
        1,
        exception_code);
}
