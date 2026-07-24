constexpr std::uint32_t kSyntheticWizardSourceActorNativeTypeId = 0x1397;

bool IsSharedHubFactoryActorType(std::uint32_t native_type_id);

bool ShouldReplicateWorldActor(
    const SDModSceneActorState& actor,
    ParticipantSceneIntentKind scene_kind) {
    if (!actor.valid ||
        actor.actor_address == 0 ||
        actor.owner_address == 0 ||
        actor.object_type_id == 0 ||
        actor.object_type_id == 1 ||
        actor.object_type_id == kSyntheticWizardSourceActorNativeTypeId ||
        !std::isfinite(actor.x) ||
        !std::isfinite(actor.y) ||
        !std::isfinite(actor.radius) ||
        actor.radius < 0.0f) {
        return false;
    }

    if (scene_kind == ParticipantSceneIntentKind::Run) {
        return (actor.tracked_enemy &&
                std::isfinite(actor.hp) &&
                std::isfinite(actor.max_hp) &&
                actor.max_hp > 0.0f &&
                (actor.dead || actor.hp > kEnemyDamageClaimHpEpsilon)) ||
               IsRunStaticLayoutActor(actor) ||
               IsReplicatedRunPlayerCreatedActorType(actor.object_type_id);
    }

    // TryListSceneActors also exposes non-actor scene/runtime records. In the
    // hub, notably, the 0xFA1 scene object has finite position-like fields but
    // its first pointer is a map configuration record rather than an actor
    // vtable. Publishing it lets a client bind and mutate that scene object as
    // though it were an actor, after which the stock hub tick executes through
    // configuration floats. Replicate only types the native object factory is
    // known to create and the reconciliation path is prepared to own.
    return scene_kind == ParticipantSceneIntentKind::SharedHub &&
           IsSharedHubFactoryActorType(actor.object_type_id);
}

bool IsReplicatedLootDropNativeType(std::uint32_t native_type_id) {
    return native_type_id == kGoldRewardNativeTypeId ||
           native_type_id == kOrbRewardNativeTypeId ||
           native_type_id == kItemDropNativeTypeId ||
           native_type_id == kPowerupRewardNativeTypeId;
}

bool ShouldReplicateLootDropActor(
    const SDModSceneActorState& actor,
    ParticipantSceneIntentKind scene_kind) {
    return scene_kind == ParticipantSceneIntentKind::Run &&
           actor.valid &&
           actor.actor_address != 0 &&
           IsReplicatedLootDropNativeType(actor.object_type_id) &&
           std::isfinite(actor.x) &&
           std::isfinite(actor.y) &&
           std::isfinite(actor.radius) &&
           actor.radius >= 0.0f;
}

std::uint64_t AllocateHubWorldActorNetworkId(const SDModSceneActorState& actor) {
    if (actor.actor_address == 0 || actor.object_type_id == 0) {
        return 0;
    }

    const auto existing = g_local_transport.hub_world_actor_ids_by_address.find(actor.actor_address);
    if (existing != g_local_transport.hub_world_actor_ids_by_address.end()) {
        return existing->second;
    }

    if (g_local_transport.next_hub_world_actor_serial == 0) {
        g_local_transport.next_hub_world_actor_serial = 1;
    }
    const auto serial = g_local_transport.next_hub_world_actor_serial++;
    const auto network_actor_id =
        (static_cast<std::uint64_t>(actor.object_type_id) << 32) |
        static_cast<std::uint64_t>(serial);
    g_local_transport.hub_world_actor_ids_by_address.emplace(actor.actor_address, network_actor_id);
    return network_actor_id;
}

void ClearHubWorldActorNetworkIds() {
    g_local_transport.hub_world_actor_ids_by_address.clear();
    g_local_transport.next_hub_world_actor_serial = 1;
}

void ClearRunHostLocalWorldActorNetworkIds() {
    g_local_transport.run_host_local_world_actor_ids_by_address.clear();
    g_local_transport.recent_run_enemy_deaths_by_network_id.clear();
    g_local_transport.retained_run_enemy_snapshots_by_network_id.clear();
    g_local_transport.last_synced_enemy_hp_by_network_id.clear();
    g_local_transport.last_enemy_claimed_hp_by_network_id.clear();
    g_local_transport.observed_enemy_damage_by_network_id.clear();
    g_local_transport.pending_lethal_enemy_damage_claim_until_ms.clear();
    g_local_transport.rejected_enemy_damage_retry_suppressed_until_ms.clear();
    ClearLocalEnemyDamageClaimObservationsInternal();
    g_local_transport.next_run_host_local_world_actor_serial = 1;
}

bool HasRetainedRunEnemySnapshotForActor(uintptr_t actor_address) {
    if (actor_address == 0) {
        return false;
    }
    for (const auto& [ignored_network_actor_id, retained] :
         g_local_transport.retained_run_enemy_snapshots_by_network_id) {
        (void)ignored_network_actor_id;
        if (retained.actor_address == actor_address) {
            return true;
        }
    }
    return false;
}

void ForgetRetainedRunEnemySnapshotForActor(uintptr_t actor_address) {
    if (actor_address == 0) {
        return;
    }
    for (auto it =
             g_local_transport.retained_run_enemy_snapshots_by_network_id.begin();
         it !=
             g_local_transport.retained_run_enemy_snapshots_by_network_id.end();) {
        if (it->second.actor_address == actor_address) {
            it = g_local_transport.retained_run_enemy_snapshots_by_network_id.erase(it);
        } else {
            ++it;
        }
    }
}

void ClearRunLootDropNetworkIds() {
    g_local_transport.run_loot_drop_ids_by_address.clear();
    g_local_transport.accepted_loot_pickup_drop_ids.clear();
    g_local_transport.native_applied_powerup_result_drop_ids.clear();
    g_local_transport.pending_host_loot_pickups_by_drop_id.clear();
    {
        std::lock_guard<std::mutex> lock(
            g_local_transport_event_mutex);
        g_queued_local_host_powerup_pickups.clear();
    }
    sdmod::ClearHostLootDropDeactivationState();
    g_local_transport.next_run_loot_drop_serial = 1;
}

void RefreshWorldSceneTracking(
    const SDModSceneState& scene_state,
    ParticipantSceneIntentKind scene_kind) {
    const auto scene_key =
        BuildWorldSceneKey(scene_state, scene_kind);
    if (scene_key == g_local_transport.world_scene_key) {
        return;
    }

    g_local_transport.world_scene_key = scene_key;
    g_local_transport.world_scene_epoch += 1;
    ClearHubWorldActorNetworkIds();
    ClearRunHostLocalWorldActorNetworkIds();
    ClearRunLootDropNetworkIds();
    {
        std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
        ClearLocalLootPickupRequestStateLocked();
    }
    g_local_transport.local_spell_effects_by_address.clear();
    g_local_transport.local_spell_effect_tombstones.clear();
    g_local_transport.next_spell_effect_ordinal_by_cast_type.clear();
    g_local_transport.last_air_chain_packet_sequence_by_participant.clear();
    g_local_transport.pending_air_chain_terminals.clear();
    g_local_transport.recent_local_cast_sequence = 0;
    g_local_transport.recent_local_cast_skill_id = -1;
    g_local_transport.recent_local_cast_ms = 0;
    g_local_transport.recent_local_cast_target_network_actor_id = 0;
    g_local_transport.recent_local_air_chain_target_until_ms.clear();
    g_local_transport.last_local_explode_splash_cast_sequence = 0;
    g_local_transport.host_local_explode_cast_baseline = {};
    {
        std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
        g_queued_local_air_chain_frame = QueuedLocalAirChainFrame{};
        g_have_queued_local_air_chain_frame = false;
    }
    ResetAirChainRuntimeState();
}

void PruneHubWorldActorNetworkIds(
    const std::vector<SDModSceneActorState>& actors,
    ParticipantSceneIntentKind scene_kind) {
    if (scene_kind != ParticipantSceneIntentKind::SharedHub) {
        ClearHubWorldActorNetworkIds();
        return;
    }

    std::unordered_set<uintptr_t> live_actor_addresses;
    for (const auto& actor : actors) {
        if (ShouldReplicateWorldActor(actor, scene_kind)) {
            live_actor_addresses.insert(actor.actor_address);
        }
    }

    for (auto iterator = g_local_transport.hub_world_actor_ids_by_address.begin();
         iterator != g_local_transport.hub_world_actor_ids_by_address.end();) {
        if (live_actor_addresses.find(iterator->first) == live_actor_addresses.end()) {
            iterator = g_local_transport.hub_world_actor_ids_by_address.erase(iterator);
        } else {
            ++iterator;
        }
    }
}

void PruneRunHostLocalWorldActorNetworkIds(
    const std::vector<SDModSceneActorState>& actors,
    ParticipantSceneIntentKind scene_kind) {
    if (scene_kind != ParticipantSceneIntentKind::Run) {
        ClearRunHostLocalWorldActorNetworkIds();
        return;
    }

    std::unordered_set<uintptr_t> live_actor_addresses;
    for (const auto& actor : actors) {
        if (ShouldReplicateWorldActor(actor, scene_kind)) {
            live_actor_addresses.insert(actor.actor_address);
        }
    }

    for (auto iterator = g_local_transport.run_host_local_world_actor_ids_by_address.begin();
         iterator != g_local_transport.run_host_local_world_actor_ids_by_address.end();) {
        if (live_actor_addresses.find(iterator->first) == live_actor_addresses.end() &&
            !HasRetainedRunEnemySnapshotForActor(iterator->first)) {
            iterator = g_local_transport.run_host_local_world_actor_ids_by_address.erase(iterator);
        } else {
            ++iterator;
        }
    }
}

void PruneRunLootDropNetworkIds(
    const std::vector<SDModSceneActorState>& actors,
    ParticipantSceneIntentKind scene_kind) {
    if (scene_kind != ParticipantSceneIntentKind::Run) {
        ClearRunLootDropNetworkIds();
        return;
    }

    std::unordered_set<uintptr_t> live_actor_addresses;
    for (const auto& actor : actors) {
        if (ShouldReplicateLootDropActor(actor, scene_kind)) {
            live_actor_addresses.insert(actor.actor_address);
        }
    }

    for (auto iterator = g_local_transport.run_loot_drop_ids_by_address.begin();
         iterator != g_local_transport.run_loot_drop_ids_by_address.end();) {
        if (live_actor_addresses.find(iterator->first) == live_actor_addresses.end()) {
            iterator = g_local_transport.run_loot_drop_ids_by_address.erase(iterator);
        } else {
            ++iterator;
        }
    }
}

float ReadActorHeadingOrZero(uintptr_t actor_address) {
    if (actor_address == 0 || kActorHeadingOffset == 0) {
        return 0.0f;
    }

    float heading = 0.0f;
    if (!ProcessMemory::Instance().TryReadField(actor_address, kActorHeadingOffset, &heading) ||
        !std::isfinite(heading)) {
        return 0.0f;
    }
    return heading;
}

std::uint64_t ResolveRunEnemyTargetParticipantId(uintptr_t actor_address) {
    if (actor_address == 0 || kActorCurrentTargetActorOffset == 0) {
        return 0;
    }

    uintptr_t target_actor_address = 0;
    if (!ProcessMemory::Instance().TryReadField(
            actor_address,
            kActorCurrentTargetActorOffset,
            &target_actor_address) ||
        target_actor_address == 0) {
        return 0;
    }

    SDModPlayerState local_player;
    if (TryGetPlayerState(&local_player) &&
        local_player.actor_address == target_actor_address &&
        g_local_transport.local_peer_id != 0) {
        return g_local_transport.local_peer_id;
    }

    if (g_local_transport.local_peer_id != 0 &&
        kGameObjectTypeIdOffset != 0 &&
        kActorSlotOffset != 0 &&
        ProcessMemory::Instance().IsReadableRange(
            target_actor_address + kGameObjectTypeIdOffset,
            sizeof(std::uint32_t))) {
        std::uint32_t target_native_type_id = 0;
        std::int8_t target_actor_slot = -1;
        if (ProcessMemory::Instance().TryReadField(
                target_actor_address,
                kGameObjectTypeIdOffset,
                &target_native_type_id) &&
            target_native_type_id == 1 &&
            ProcessMemory::Instance().TryReadField(
                target_actor_address,
                kActorSlotOffset,
                &target_actor_slot) &&
            target_actor_slot == 0) {
            return g_local_transport.local_peer_id;
        }
    }

    std::string ignored_display_name;
    std::uint64_t target_participant_id = 0;
    if (TryGetGameplayHudParticipantDisplayNameForActor(
            target_actor_address,
            &ignored_display_name,
            &target_participant_id) &&
        target_participant_id != 0) {
        return target_participant_id;
    }

    const auto runtime_state = SnapshotRuntimeState();
    for (const auto& participant : runtime_state.participants) {
        if (!IsRemoteParticipant(participant)) {
            continue;
        }
        SDModParticipantGameplayState gameplay_state;
        if (TryGetParticipantGameplayState(participant.participant_id, &gameplay_state) &&
            gameplay_state.entity_materialized &&
            gameplay_state.actor_address == target_actor_address) {
            return participant.participant_id;
        }
    }

    return 0;
}

bool PopulateRunEnemyNativeTargetSnapshot(
    uintptr_t actor_address,
    WorldActorSnapshotPacketState* snapshot) {
    if (actor_address == 0 ||
        snapshot == nullptr ||
        kActorCurrentTargetActorOffset == 0 ||
        kActorCurrentTargetBucketDeltaOffset == 0 ||
        kGameObjectTypeIdOffset == 0 ||
        kActorSlotOffset == 0 ||
        kActorWorldSlotOffset == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t target_actor_address = 0;
    if (!memory.TryReadField(
            actor_address,
            kActorCurrentTargetActorOffset,
            &target_actor_address) ||
        target_actor_address == 0 ||
        !memory.IsReadableRange(target_actor_address + kGameObjectTypeIdOffset, sizeof(std::uint32_t))) {
        return false;
    }

    std::uint32_t target_native_type_id = 0;
    std::int8_t target_actor_slot = -1;
    std::int16_t target_world_slot = -1;
    std::int32_t target_bucket_delta = 0;
    if (!memory.TryReadField(target_actor_address, kGameObjectTypeIdOffset, &target_native_type_id) ||
        target_native_type_id == 0 ||
        !memory.TryReadField(target_actor_address, kActorSlotOffset, &target_actor_slot) ||
        target_actor_slot < 0 ||
        !memory.TryReadField(target_actor_address, kActorWorldSlotOffset, &target_world_slot) ||
        target_world_slot < 0) {
        return false;
    }
    (void)memory.TryReadField(actor_address, kActorCurrentTargetBucketDeltaOffset, &target_bucket_delta);

    snapshot->target_native_type_id = target_native_type_id;
    snapshot->target_actor_slot = static_cast<std::int32_t>(target_actor_slot);
    snapshot->target_world_slot = static_cast<std::int32_t>(target_world_slot);
    snapshot->target_bucket_delta = target_bucket_delta;
    return true;
}

bool PopulateRunEnemyTransientStatusSnapshot(
    uintptr_t actor_address,
    std::uint32_t native_type_id,
    WorldActorSnapshotPacketState* snapshot) {
    if (actor_address == 0 ||
        snapshot == nullptr ||
        !IsTurnUndeadEligibleRunEnemyType(native_type_id) ||
        kActorTurnUndeadFleeHeadingOffset == 0 ||
        kActorTurnUndeadActivationScalarOffset == 0 ||
        kActorTurnUndeadDurationTicksOffset == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    std::int32_t duration_ticks = 0;
    float flee_heading = 0.0f;
    float activation_scalar = 0.0f;
    if (!memory.TryReadField(
            actor_address,
            kActorTurnUndeadDurationTicksOffset,
            &duration_ticks) ||
        !memory.TryReadField(
            actor_address,
            kActorTurnUndeadFleeHeadingOffset,
            &flee_heading) ||
        !memory.TryReadField(
            actor_address,
            kActorTurnUndeadActivationScalarOffset,
            &activation_scalar) ||
        duration_ticks > 100000 ||
        !std::isfinite(flee_heading) ||
        std::abs(flee_heading) > 36000.0f ||
        !std::isfinite(activation_scalar) ||
        activation_scalar < 0.0f ||
        activation_scalar > 65536.0f) {
        return false;
    }

    snapshot->status_flags |= WorldActorStatusFlagTurnUndeadStateValid;
    snapshot->turn_undead_duration_ticks =
        (std::max<std::int32_t>)(duration_ticks, 0);
    snapshot->turn_undead_flee_heading = flee_heading;
    snapshot->turn_undead_activation_scalar = activation_scalar;
    if (duration_ticks > 0) {
        snapshot->status_flags |= WorldActorStatusFlagTurnUndeadActive;
    }
    return true;
}

void PruneRecentRunEnemyDeathSnapshots(std::uint64_t now_ms) {
    for (auto it = g_local_transport.recent_run_enemy_deaths_by_network_id.begin();
         it != g_local_transport.recent_run_enemy_deaths_by_network_id.end();) {
        if (it->second.expires_ms <= now_ms) {
            it = g_local_transport.recent_run_enemy_deaths_by_network_id.erase(it);
            continue;
        }
        ++it;
    }
}

void RecordRecentRunEnemyDeathSnapshot(
    std::uint64_t network_actor_id,
    const SDModSceneActorState& actor,
    std::uint64_t now_ms) {
    if (network_actor_id == 0 ||
        !actor.tracked_enemy ||
        actor.actor_address == 0 ||
        actor.object_type_id == 0 ||
        !std::isfinite(actor.x) ||
        !std::isfinite(actor.y) ||
        !std::isfinite(actor.radius) ||
        !std::isfinite(actor.max_hp) ||
        actor.max_hp <= 0.0f) {
        return;
    }

    RecentRunEnemyDeathSnapshot snapshot;
    snapshot.network_actor_id = network_actor_id;
    snapshot.actor_address = actor.actor_address;
    snapshot.native_type_id = actor.object_type_id;
    snapshot.enemy_type = actor.enemy_type;
    SDModLuaEnemySpawnConfig lua_enemy_config;
    if (TryGetRunLifecycleLuaEnemySpawnConfig(
            actor.actor_address,
            &lua_enemy_config)) {
        snapshot.lua_content_id = lua_enemy_config.content_id;
        if (lua_enemy_config.hp_valid) {
            snapshot.lua_enemy_spawn_flags |= LuaEnemySpawnSnapshotFlagHp;
            snapshot.lua_spawn_hp = lua_enemy_config.hp;
        }
        if (lua_enemy_config.chase_speed_valid) {
            snapshot.lua_enemy_spawn_flags |=
                LuaEnemySpawnSnapshotFlagChaseSpeed;
            snapshot.lua_spawn_chase_speed = lua_enemy_config.chase_speed;
        }
        if (lua_enemy_config.attack_speed_valid) {
            snapshot.lua_enemy_spawn_flags |=
                LuaEnemySpawnSnapshotFlagAttackSpeed;
            snapshot.lua_spawn_attack_speed = lua_enemy_config.attack_speed;
        }
        if (lua_enemy_config.scale_valid) {
            snapshot.lua_enemy_spawn_flags |=
                LuaEnemySpawnSnapshotFlagScale;
            snapshot.lua_spawn_scale = lua_enemy_config.scale;
        }
    } else {
        const auto existing =
            g_local_transport.recent_run_enemy_deaths_by_network_id.find(
                network_actor_id);
        if (existing !=
            g_local_transport.recent_run_enemy_deaths_by_network_id.end()) {
            snapshot.lua_content_id = existing->second.lua_content_id;
            snapshot.lua_enemy_spawn_flags =
                existing->second.lua_enemy_spawn_flags;
            snapshot.lua_spawn_hp = existing->second.lua_spawn_hp;
            snapshot.lua_spawn_chase_speed =
                existing->second.lua_spawn_chase_speed;
            snapshot.lua_spawn_attack_speed =
                existing->second.lua_spawn_attack_speed;
            snapshot.lua_spawn_scale = existing->second.lua_spawn_scale;
        }
    }
    if (snapshot.lua_content_id == 0) {
        const auto retained =
            g_local_transport.retained_run_enemy_snapshots_by_network_id.find(
                network_actor_id);
        if (retained !=
            g_local_transport.retained_run_enemy_snapshots_by_network_id.end()) {
            snapshot.lua_content_id = retained->second.packet.lua_content_id;
            snapshot.lua_enemy_spawn_flags =
                retained->second.packet.lua_enemy_spawn_flags;
            snapshot.lua_spawn_hp = retained->second.packet.lua_spawn_hp;
            snapshot.lua_spawn_chase_speed =
                retained->second.packet.lua_spawn_chase_speed;
            snapshot.lua_spawn_attack_speed =
                retained->second.packet.lua_spawn_attack_speed;
            snapshot.lua_spawn_scale =
                retained->second.packet.lua_spawn_scale;
        }
    }
    snapshot.position_x = actor.x;
    snapshot.position_y = actor.y;
    snapshot.radius = actor.radius;
    snapshot.heading = ReadActorHeadingOrZero(actor.actor_address);
    snapshot.max_hp = actor.max_hp;
    snapshot.expires_ms = now_ms + kRecentRunEnemyDeathSnapshotHoldMs;
    g_local_transport.retained_run_enemy_snapshots_by_network_id.erase(
        network_actor_id);
    g_local_transport.recent_run_enemy_deaths_by_network_id[network_actor_id] = snapshot;
}

bool HasRecentRunEnemyDeathSnapshotForActor(uintptr_t actor_address) {
    if (actor_address == 0) {
        return false;
    }
    for (const auto& [ignored_network_actor_id, death_snapshot] :
         g_local_transport.recent_run_enemy_deaths_by_network_id) {
        (void)ignored_network_actor_id;
        if (death_snapshot.actor_address == actor_address) {
            return true;
        }
    }
    return false;
}

#include "world_snapshot_hub_presentation_and_loot_helpers.inl"
