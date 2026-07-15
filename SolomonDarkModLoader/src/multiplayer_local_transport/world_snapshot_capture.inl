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
           native_type_id == kItemDropNativeTypeId;
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
    g_local_transport.last_synced_enemy_hp_by_network_id.clear();
    g_local_transport.last_enemy_claimed_hp_by_network_id.clear();
    g_local_transport.observed_enemy_damage_by_network_id.clear();
    g_local_transport.pending_lethal_enemy_damage_claim_until_ms.clear();
    g_local_transport.rejected_enemy_damage_retry_suppressed_until_ms.clear();
    g_local_transport.next_run_host_local_world_actor_serial = 1;
}

void ClearRunLootDropNetworkIds() {
    g_local_transport.run_loot_drop_ids_by_address.clear();
    g_local_transport.accepted_loot_pickup_drop_ids.clear();
    g_local_transport.next_run_loot_drop_serial = 1;
}

void RefreshWorldSceneTracking(const SDModSceneState& scene_state) {
    const auto scene_key = BuildWorldSceneKey(scene_state);
    if (scene_key == g_local_transport.world_scene_key) {
        return;
    }

    g_local_transport.world_scene_key = scene_key;
    g_local_transport.world_scene_epoch += 1;
    ClearHubWorldActorNetworkIds();
    ClearRunHostLocalWorldActorNetworkIds();
    ClearRunLootDropNetworkIds();
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
        if (live_actor_addresses.find(iterator->first) == live_actor_addresses.end()) {
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
    snapshot.position_x = actor.x;
    snapshot.position_y = actor.y;
    snapshot.radius = actor.radius;
    snapshot.heading = ReadActorHeadingOrZero(actor.actor_address);
    snapshot.max_hp = actor.max_hp;
    snapshot.expires_ms = now_ms + kRecentRunEnemyDeathSnapshotHoldMs;
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

bool IsHubStudentActorType(std::uint32_t native_type_id) {
    return native_type_id == 0x138A;
}

bool IsNamedHubNpcActorType(std::uint32_t native_type_id) {
    switch (native_type_id) {
    case 0x1389: // PerkWitch
    case 0x138B: // Annalist
    case 0x138C: // PotionGuy
    case 0x138D: // ItemsGuy
    case 0x138F: // Tyrannia
    case 0x1390: // Teacher
        return true;
    default:
        return false;
    }
}

bool IsSaneNamedHubNpcPresentationFloat(float value) {
    constexpr float kMaxMagnitude = 65536.0f;
    return std::isfinite(value) && value >= -kMaxMagnitude && value <= kMaxMagnitude;
}

bool PopulateNamedHubNpcIdleAnimatorSnapshot(
    uintptr_t actor_address,
    WorldActorSnapshotPacketState* snapshot) {
    if (actor_address == 0 ||
        snapshot == nullptr ||
        kNamedHubNpcIdleAnimationBlockOffset == 0) {
        return false;
    }

    constexpr std::size_t kActiveOffset = 0x00;
    constexpr std::size_t kPhaseOffset = 0x04;
    constexpr std::size_t kFrameOffset = 0x08;
    constexpr std::size_t kRateOffset = 0x0C;
    constexpr std::size_t kAmplitudeOffset = 0x10;
    constexpr std::size_t kEnabledOffset = 0x14;
    const auto block = actor_address + kNamedHubNpcIdleAnimationBlockOffset;
    auto& state = snapshot->named_hub_npc;
    auto& memory = ProcessMemory::Instance();
    if (!memory.TryReadValue(block + kActiveOffset, &state.idle_active) ||
        !memory.TryReadValue(block + kEnabledOffset, &state.idle_enabled) ||
        !memory.TryReadValue(block + kPhaseOffset, &state.idle_phase) ||
        !memory.TryReadValue(block + kFrameOffset, &state.idle_frame) ||
        !memory.TryReadValue(block + kRateOffset, &state.idle_rate) ||
        !memory.TryReadValue(block + kAmplitudeOffset, &state.idle_amplitude) ||
        state.idle_active > 1 ||
        state.idle_enabled > 1 ||
        !IsSaneNamedHubNpcPresentationFloat(state.idle_phase) ||
        !IsSaneNamedHubNpcPresentationFloat(state.idle_frame) ||
        !IsSaneNamedHubNpcPresentationFloat(state.idle_rate) ||
        !IsSaneNamedHubNpcPresentationFloat(state.idle_amplitude)) {
        return false;
    }

    snapshot->presentation_flags |= WorldActorPresentationFlagNamedHubNpcIdleAnimator;
    return true;
}

void PopulateNamedHubNpcPresentationSnapshot(
    uintptr_t actor_address,
    std::uint32_t native_type_id,
    WorldActorSnapshotPacketState* snapshot) {
    if (actor_address == 0 ||
        snapshot == nullptr ||
        !IsNamedHubNpcActorType(native_type_id) ||
        kNamedHubNpcIdleAnimationBlockOffset == 0) {
        return;
    }

    constexpr std::size_t kPhaseOffset = 0x04;
    constexpr std::size_t kFrameOffset = 0x08;
    constexpr std::size_t kRateOffset = 0x0C;
    const auto idle_block = actor_address + kNamedHubNpcIdleAnimationBlockOffset;
    auto& state = snapshot->named_hub_npc;
    auto& memory = ProcessMemory::Instance();

    switch (native_type_id) {
    case 0x1389: // PerkWitch: +0x144 angle/frame and +0x148 angular rate.
        if (memory.TryReadValue(idle_block + kFrameOffset, &state.idle_frame) &&
            memory.TryReadValue(idle_block + kRateOffset, &state.idle_rate) &&
            IsSaneNamedHubNpcPresentationFloat(state.idle_frame) &&
            IsSaneNamedHubNpcPresentationFloat(state.idle_rate)) {
            snapshot->presentation_flags |= WorldActorPresentationFlagNamedHubNpcWitchOrbit;
        }
        return;
    case 0x138B: // Annalist
    case 0x138D: // ItemsGuy
        (void)PopulateNamedHubNpcIdleAnimatorSnapshot(actor_address, snapshot);
        return;
    case 0x138C: { // PotionGuy
        (void)PopulateNamedHubNpcIdleAnimatorSnapshot(actor_address, snapshot);
        if (kNamedHubNpcTypeSpecificStateBlockOffset == 0) {
            return;
        }
        const auto type_block = actor_address + kNamedHubNpcTypeSpecificStateBlockOffset;
        if (memory.TryReadValue(type_block + 0x00, &state.motion_position) &&
            memory.TryReadValue(type_block + 0x04, &state.motion_direction) &&
            memory.TryReadValue(type_block + 0x08, &state.timer) &&
            IsSaneNamedHubNpcPresentationFloat(state.motion_position) &&
            IsSaneNamedHubNpcPresentationFloat(state.motion_direction) &&
            state.timer >= 0 && state.timer <= 100000) {
            snapshot->presentation_flags |= WorldActorPresentationFlagNamedHubNpcPotionMotion;
        }
        return;
    }
    case 0x138F: { // Tyrannia
        (void)PopulateNamedHubNpcIdleAnimatorSnapshot(actor_address, snapshot);
        if (kNamedHubNpcTypeSpecificStateBlockOffset == 0) {
            return;
        }
        const auto type_block = actor_address + kNamedHubNpcTypeSpecificStateBlockOffset;
        if (memory.TryReadValue(type_block + 0x00, &state.timer) &&
            memory.TryReadValue(type_block + 0x04, &state.pose) &&
            memory.TryReadValue(type_block + 0x08, &state.render_scale) &&
            state.timer >= -1 && state.timer <= 100000 &&
            state.pose >= 0 && state.pose <= 2 &&
            IsSaneNamedHubNpcPresentationFloat(state.render_scale)) {
            snapshot->presentation_flags |= WorldActorPresentationFlagNamedHubNpcTyranniaPose;
        }
        return;
    }
    case 0x1390: // Teacher: dedicated cycle plus one-shot effect latch.
        if (kNamedHubNpcTypeSpecificStateBlockOffset != 0 &&
            memory.TryReadValue(idle_block + kPhaseOffset, &state.idle_phase) &&
            memory.TryReadValue(idle_block + kFrameOffset, &state.idle_frame) &&
            memory.TryReadValue(
                actor_address + kNamedHubNpcTypeSpecificStateBlockOffset,
                &state.type_state_byte) &&
            IsSaneNamedHubNpcPresentationFloat(state.idle_phase) &&
            IsSaneNamedHubNpcPresentationFloat(state.idle_frame) &&
            state.type_state_byte <= 1) {
            snapshot->presentation_flags |= WorldActorPresentationFlagNamedHubNpcTeacherCycle;
        }
        return;
    default:
        return;
    }
}

bool IsSharedHubFactoryActorType(std::uint32_t native_type_id) {
    switch (native_type_id) {
    case 0x1389:
    case 0x138A:
    case 0x138B:
    case 0x138C:
    case 0x138D:
    case 0x138F:
    case 0x1390:
        return true;
    default:
        return false;
    }
}

void PopulateWorldActorPresentationSnapshot(
    uintptr_t actor_address,
    std::uint32_t native_type_id,
    ParticipantSceneIntentKind scene_kind,
    bool tracked_enemy,
    WorldActorSnapshotPacketState* snapshot) {
    if (actor_address == 0 || snapshot == nullptr) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    if (scene_kind == ParticipantSceneIntentKind::Run &&
        tracked_enemy &&
        kActorWalkCyclePrimaryOffset != 0 &&
        kActorWalkCycleSecondaryOffset != 0) {
        auto read_sane_animation_float = [&](std::size_t offset, float* value) -> bool {
            if (value == nullptr ||
                !memory.TryReadField(actor_address, offset, value) ||
                !std::isfinite(*value)) {
                return false;
            }
            constexpr float kMaxSaneRunEnemyLocomotionMagnitude = 4096.0f;
            return *value >= -kMaxSaneRunEnemyLocomotionMagnitude &&
                   *value <= kMaxSaneRunEnemyLocomotionMagnitude;
        };

        float walk_cycle_primary = 0.0f;
        float walk_cycle_secondary = 0.0f;
        if (read_sane_animation_float(kActorWalkCyclePrimaryOffset, &walk_cycle_primary) &&
            read_sane_animation_float(kActorWalkCycleSecondaryOffset, &walk_cycle_secondary)) {
            snapshot->presentation_flags |= WorldActorPresentationFlagLocomotionFloats;
            snapshot->walk_cycle_primary = walk_cycle_primary;
            snapshot->walk_cycle_secondary = walk_cycle_secondary;
        }
    }

    if (scene_kind == ParticipantSceneIntentKind::SharedHub &&
        IsSharedHubFactoryActorType(native_type_id) &&
        kActorAnimationDriveStateByteOffset != 0) {
        std::uint32_t drive_word = 0;
        if (memory.TryReadField(actor_address, kActorAnimationDriveStateByteOffset, &drive_word)) {
            snapshot->presentation_flags |= WorldActorPresentationFlagAnimationDriveWord;
            snapshot->anim_drive_state_word = drive_word;
        }
    }

    if (scene_kind == ParticipantSceneIntentKind::SharedHub &&
        IsNamedHubNpcActorType(native_type_id)) {
        PopulateNamedHubNpcPresentationSnapshot(actor_address, native_type_id, snapshot);
    }

    if (scene_kind != ParticipantSceneIntentKind::SharedHub ||
        !IsHubStudentActorType(native_type_id)) {
        return;
    }

    if (kActorRenderVariantPrimaryOffset != 0 &&
        kActorRenderVariantSecondaryOffset != 0 &&
        kActorRenderWeaponTypeOffset != 0 &&
        kActorRenderSelectionByteOffset != 0 &&
        kActorRenderVariantTertiaryOffset != 0) {
        bool have_variant_bytes = true;
        have_variant_bytes = memory.TryReadField(
            actor_address,
            kActorRenderVariantPrimaryOffset,
            &snapshot->render_variant_primary) && have_variant_bytes;
        have_variant_bytes = memory.TryReadField(
            actor_address,
            kActorRenderVariantSecondaryOffset,
            &snapshot->render_variant_secondary) && have_variant_bytes;
        have_variant_bytes = memory.TryReadField(
            actor_address,
            kActorRenderWeaponTypeOffset,
            &snapshot->render_weapon_type) && have_variant_bytes;
        have_variant_bytes = memory.TryReadField(
            actor_address,
            kActorRenderSelectionByteOffset,
            &snapshot->render_selection_byte) && have_variant_bytes;
        have_variant_bytes = memory.TryReadField(
            actor_address,
            kActorRenderVariantTertiaryOffset,
            &snapshot->render_variant_tertiary) && have_variant_bytes;
        if (have_variant_bytes) {
            snapshot->presentation_flags |= WorldActorPresentationFlagStudentVariantBytes;
        }
    }

    if (kStudentVisualStateBlockOffset != 0 &&
        memory.TryRead(
            actor_address + kStudentVisualStateBlockOffset,
            snapshot->student_visual_state,
            kWorldActorStudentVisualStateBytes)) {
        snapshot->presentation_flags |= WorldActorPresentationFlagStudentVisualState;
    }

    if (kStudentBookPaletteBlockOffset == 0) {
        return;
    }

    constexpr std::size_t kStudentBookPaletteColorsOffset = 0x04;
    constexpr std::size_t kStudentBookPaletteRadialOffsetsOffset = 0x54;
    constexpr std::size_t kStudentBookPaletteAngularOffsetsOffset = 0x68;
    constexpr float kMaxSaneStudentBookPaletteMagnitude = 4096.0f;
    const auto palette_address = actor_address + kStudentBookPaletteBlockOffset;
    std::uint32_t palette_count = 0;
    if (!memory.TryReadValue(palette_address, &palette_count) ||
        palette_count > kWorldActorStudentBookPaletteMaxEntries) {
        return;
    }

    bool palette_valid = true;
    for (std::size_t index = 0; index < palette_count; ++index) {
        auto& entry = snapshot->student_book_palette[index];
        const auto color_address =
            palette_address + kStudentBookPaletteColorsOffset + index * sizeof(float) * 4;
        palette_valid = memory.TryRead(color_address, &entry.red, sizeof(float) * 4) &&
                        memory.TryReadValue(
                            palette_address + kStudentBookPaletteRadialOffsetsOffset +
                                index * sizeof(float),
                            &entry.radial_offset) &&
                        memory.TryReadValue(
                            palette_address + kStudentBookPaletteAngularOffsetsOffset +
                                index * sizeof(float),
                            &entry.angular_offset);
        const float values[] = {
            entry.red,
            entry.green,
            entry.blue,
            entry.alpha,
            entry.radial_offset,
            entry.angular_offset,
        };
        for (const float value : values) {
            palette_valid = palette_valid && std::isfinite(value) &&
                            value >= -kMaxSaneStudentBookPaletteMagnitude &&
                            value <= kMaxSaneStudentBookPaletteMagnitude;
        }
        if (!palette_valid) {
            return;
        }
    }

    snapshot->student_book_palette_count = palette_count;
    snapshot->presentation_flags |= WorldActorPresentationFlagStudentBookPalette;
}

std::int32_t RoundRewardAmountToInt(float amount) {
    if (!std::isfinite(amount) || amount <= 0.0f) {
        return 0;
    }
    if (amount >= static_cast<float>((std::numeric_limits<std::int32_t>::max)())) {
        return (std::numeric_limits<std::int32_t>::max)();
    }
    return static_cast<std::int32_t>(std::lround(amount));
}

bool TryResolveLootOrbResourceKind(std::int32_t resource_kind, LootOrbResourceKind* kind) {
    if (kind == nullptr) {
        return false;
    }
    switch (resource_kind) {
    case static_cast<std::int32_t>(LootOrbResourceKind::Health):
        *kind = LootOrbResourceKind::Health;
        return true;
    case static_cast<std::int32_t>(LootOrbResourceKind::Mana):
        *kind = LootOrbResourceKind::Mana;
        return true;
    default:
        return false;
    }
}

float LootOrbScaleForResourceKind(LootOrbResourceKind kind) {
    return kind == LootOrbResourceKind::Health ? kOrbHealthRewardScale : kOrbManaRewardScale;
}

float ComputeLootOrbResourceDelta(std::int32_t resource_kind, float raw_value) {
    LootOrbResourceKind kind = LootOrbResourceKind::Health;
    if (!TryResolveLootOrbResourceKind(resource_kind, &kind) ||
        !std::isfinite(raw_value) ||
        raw_value <= kLootPickupResourceEpsilon) {
        return 0.0f;
    }
    const float delta = raw_value * LootOrbScaleForResourceKind(kind);
    if (!std::isfinite(delta) || delta <= kLootPickupResourceEpsilon) {
        return 0.0f;
    }
    return (std::min)(delta, kLootPickupMaxResourceDelta);
}
