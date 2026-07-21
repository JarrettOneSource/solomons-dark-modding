bool ShouldReconcileLocalWorldActor(
    const SDModSceneActorState& actor,
    multiplayer::ParticipantSceneIntentKind scene_kind) {
    if (!actor.valid ||
        actor.actor_address == 0 ||
        actor.owner_address == 0 ||
        actor.object_type_id == 0 ||
        actor.object_type_id == 1 ||
        !std::isfinite(actor.x) ||
        !std::isfinite(actor.y) ||
        !std::isfinite(actor.radius) ||
        actor.radius < 0.0f) {
        return false;
    }

    if (scene_kind == multiplayer::ParticipantSceneIntentKind::Run) {
        return (actor.tracked_enemy &&
                std::isfinite(actor.hp) &&
                std::isfinite(actor.max_hp) &&
                actor.max_hp > 0.0f) ||
               (!actor.tracked_enemy &&
                (actor.object_type_id == kSolomonDigNativeTypeId ||
                 actor.object_type_id == kSolomonRunStaticNativeTypeId ||
                 multiplayer::IsReplicatedRunPlayerCreatedActorType(
                     actor.object_type_id)));
    }

    return scene_kind == multiplayer::ParticipantSceneIntentKind::SharedHub &&
           IsReplicatedSharedHubFactoryActorType(actor.object_type_id);
}

bool ShouldUseAuthoritativeWorldActorForScene(
    const multiplayer::WorldActorSnapshot& actor,
    multiplayer::ParticipantSceneIntentKind scene_kind) {
    if (actor.network_actor_id == 0 ||
        actor.native_type_id == 0) {
        return false;
    }

    if (scene_kind == multiplayer::ParticipantSceneIntentKind::Run) {
        return actor.lifecycle_owned &&
               ((actor.tracked_enemy &&
                 std::isfinite(actor.hp) &&
                 std::isfinite(actor.max_hp) &&
                 actor.max_hp > 0.0f &&
                 (actor.dead || actor.hp > kReplicatedRunEnemyDeathHpEpsilon)) ||
                (actor.run_static &&
                 (actor.native_type_id == kSolomonDigNativeTypeId ||
                  actor.native_type_id == kSolomonRunStaticNativeTypeId)) ||
                (actor.player_created &&
                 multiplayer::IsReplicatedRunPlayerCreatedActorType(
                     actor.native_type_id)));
    }

    return scene_kind == multiplayer::ParticipantSceneIntentKind::SharedHub &&
           IsReplicatedSharedHubFactoryActorType(actor.native_type_id);
}

bool IsSameReplicatedRunEnemyKind(
    const SDModSceneActorState& local_actor,
    const multiplayer::WorldActorSnapshot& authoritative_actor) {
    return local_actor.object_type_id == authoritative_actor.native_type_id;
}

bool IsReplicatedSharedHubFactoryActorType(std::uint32_t native_type_id) {
    switch (native_type_id) {
    case 0x1389:  // PerkWitch
    case 0x138A:  // Student
    case 0x138B:  // Annalist
    case 0x138C:  // PotionGuy
    case 0x138D:  // ItemsGuy
    case 0x138F:  // Tyrannia
    case 0x1390:  // Teacher
        return true;
    default:
        return false;
    }
}

bool IsReplicatedSharedHubLifecycleOwnedActorType(std::uint32_t native_type_id) {
    // Students are stock transient hub actors. Their native update retires and
    // replaces them independently on each machine. Multiplayer owns their
    // transform and presentation only; constructing or unregistering them
    // bypasses the stock spawner and eventually corrupts the hub actor pool.
    return IsReplicatedSharedHubFactoryActorType(native_type_id) &&
           native_type_id != 0x138A;
}

std::uint64_t BuildReplicatedWorldActorNetworkId(
    const SDModSceneActorState& actor,
    std::uint32_t type_ordinal) {
    return (static_cast<std::uint64_t>(actor.object_type_id) << 32) |
           static_cast<std::uint64_t>(type_ordinal);
}

void ClearReplicatedSharedHubActorBindings() {
    g_replicated_created_hub_actors.clear();
    g_replicated_hub_bindings_by_network_id.clear();
    g_replicated_hub_network_ids_by_actor.clear();
}

void BindReplicatedSharedHubActor(std::uint64_t network_actor_id, uintptr_t actor_address) {
    if (network_actor_id == 0 || actor_address == 0) {
        return;
    }

    const auto previous_by_id = g_replicated_hub_bindings_by_network_id.find(network_actor_id);
    if (previous_by_id != g_replicated_hub_bindings_by_network_id.end() &&
        previous_by_id->second != actor_address) {
        g_replicated_hub_network_ids_by_actor.erase(previous_by_id->second);
    }

    const auto previous_by_actor = g_replicated_hub_network_ids_by_actor.find(actor_address);
    if (previous_by_actor != g_replicated_hub_network_ids_by_actor.end() &&
        previous_by_actor->second != network_actor_id) {
        g_replicated_hub_bindings_by_network_id.erase(previous_by_actor->second);
        g_replicated_created_hub_actors.erase(previous_by_actor->second);
    }

    g_replicated_hub_bindings_by_network_id[network_actor_id] = actor_address;
    g_replicated_hub_network_ids_by_actor[actor_address] = network_actor_id;
}

void UnbindReplicatedSharedHubActor(std::uint64_t network_actor_id, uintptr_t actor_address) {
    if (network_actor_id != 0) {
        g_replicated_hub_bindings_by_network_id.erase(network_actor_id);
        g_replicated_created_hub_actors.erase(network_actor_id);
    }
    if (actor_address != 0) {
        g_replicated_hub_network_ids_by_actor.erase(actor_address);
    }
}

std::uint64_t LookupReplicatedSharedHubActorNetworkId(uintptr_t actor_address) {
    if (actor_address == 0) {
        return 0;
    }
    const auto it = g_replicated_hub_network_ids_by_actor.find(actor_address);
    return it != g_replicated_hub_network_ids_by_actor.end() ? it->second : 0;
}

void PruneReplicatedSharedHubActorBindings(const std::vector<SDModSceneActorState>& scene_actors) {
    std::unordered_set<uintptr_t> active_hub_actors;
    active_hub_actors.reserve(scene_actors.size());
    for (const auto& actor : scene_actors) {
        if (ShouldReconcileLocalWorldActor(actor, multiplayer::ParticipantSceneIntentKind::SharedHub)) {
            active_hub_actors.insert(actor.actor_address);
        }
    }

    for (auto it = g_replicated_hub_bindings_by_network_id.begin();
         it != g_replicated_hub_bindings_by_network_id.end();) {
        if (active_hub_actors.find(it->second) == active_hub_actors.end()) {
            g_replicated_hub_network_ids_by_actor.erase(it->second);
            g_replicated_created_hub_actors.erase(it->first);
            it = g_replicated_hub_bindings_by_network_id.erase(it);
            continue;
        }
        ++it;
    }
}

void ClearReplicatedRunActorBindings() {
    for (const auto& binding : g_replicated_run_bindings_by_network_id) {
        multiplayer::ClearReplicatedRunEnemyDamageBaseline(binding.first);
    }
    g_replicated_run_bindings_by_network_id.clear();
    g_replicated_run_network_ids_by_actor.clear();
    ClearLatestRunEnemySnapshotCache();
    g_replicated_run_pending_enemy_death_until_ms.clear();
    g_replicated_run_enemy_death_hold_started_ids.clear();
    g_replicated_run_pending_enemy_materialization_until_ms.clear();
}

void BindReplicatedRunActor(std::uint64_t network_actor_id, uintptr_t actor_address) {
    if (network_actor_id == 0 || actor_address == 0) {
        return;
    }

    multiplayer::ClearReplicatedRunEnemyDamageBaseline(network_actor_id);
    const auto previous_by_id = g_replicated_run_bindings_by_network_id.find(network_actor_id);
    if (previous_by_id != g_replicated_run_bindings_by_network_id.end() &&
        previous_by_id->second != actor_address) {
        g_replicated_run_network_ids_by_actor.erase(previous_by_id->second);
    }

    const auto previous_by_actor = g_replicated_run_network_ids_by_actor.find(actor_address);
    if (previous_by_actor != g_replicated_run_network_ids_by_actor.end() &&
        previous_by_actor->second != network_actor_id) {
        multiplayer::ClearReplicatedRunEnemyDamageBaseline(previous_by_actor->second);
        g_replicated_run_bindings_by_network_id.erase(previous_by_actor->second);
    }

    g_replicated_run_bindings_by_network_id[network_actor_id] = actor_address;
    g_replicated_run_network_ids_by_actor[actor_address] = network_actor_id;
    g_replicated_run_pending_enemy_death_until_ms.erase(network_actor_id);
    g_replicated_run_enemy_death_hold_started_ids.erase(network_actor_id);
    g_replicated_run_pending_enemy_materialization_until_ms.erase(network_actor_id);
    CancelQueuedRunLifecycleReplicatedEnemyCatchupSpawn(network_actor_id);
}

void UnbindReplicatedRunActor(std::uint64_t network_actor_id, uintptr_t actor_address) {
    if (network_actor_id != 0) {
        multiplayer::ClearReplicatedRunEnemyDamageBaseline(network_actor_id);
        g_replicated_run_bindings_by_network_id.erase(network_actor_id);
        g_replicated_run_pending_enemy_death_until_ms.erase(network_actor_id);
        g_replicated_run_enemy_death_hold_started_ids.erase(network_actor_id);
        g_replicated_run_pending_enemy_materialization_until_ms.erase(network_actor_id);
        CancelQueuedRunLifecycleReplicatedEnemyCatchupSpawn(network_actor_id);
    }
    if (actor_address != 0) {
        g_replicated_run_network_ids_by_actor.erase(actor_address);
    }
}

std::uint64_t LookupReplicatedRunActorNetworkId(uintptr_t actor_address) {
    if (actor_address == 0) {
        return 0;
    }
    const auto it = g_replicated_run_network_ids_by_actor.find(actor_address);
    return it != g_replicated_run_network_ids_by_actor.end() ? it->second : 0;
}

void PruneReplicatedRunActorBindings(const std::vector<SDModSceneActorState>& scene_actors) {
    std::unordered_set<uintptr_t> active_run_actors;
    active_run_actors.reserve(scene_actors.size());
    for (const auto& actor : scene_actors) {
        if (ShouldReconcileLocalWorldActor(actor, multiplayer::ParticipantSceneIntentKind::Run)) {
            active_run_actors.insert(actor.actor_address);
        }
    }

    for (auto it = g_replicated_run_bindings_by_network_id.begin();
         it != g_replicated_run_bindings_by_network_id.end();) {
        if (active_run_actors.find(it->second) == active_run_actors.end()) {
            multiplayer::ClearReplicatedRunEnemyDamageBaseline(it->first);
            g_replicated_run_network_ids_by_actor.erase(it->second);
            it = g_replicated_run_bindings_by_network_id.erase(it);
            continue;
        }
        ++it;
    }
}

void RecordWorldSnapshotBinding(
    WorldSnapshotApplyCounts* counts,
    const multiplayer::WorldActorSnapshot& authoritative_actor,
    uintptr_t local_actor_address,
    bool matched,
    bool parked,
    bool removed = false) {
    if (counts == nullptr || authoritative_actor.network_actor_id == 0 || local_actor_address == 0) {
        return;
    }

    multiplayer::WorldSnapshotActorBindingRuntimeInfo binding;
    binding.network_actor_id = authoritative_actor.network_actor_id;
    binding.local_actor_address = local_actor_address;
    binding.native_type_id = authoritative_actor.native_type_id;
    binding.enemy_type = authoritative_actor.enemy_type;
    binding.sampled_transform_valid =
        std::isfinite(authoritative_actor.position_x) &&
        std::isfinite(authoritative_actor.position_y);
    if (binding.sampled_transform_valid) {
        binding.sampled_position_x = authoritative_actor.position_x;
        binding.sampled_position_y = authoritative_actor.position_y;
    }
    binding.matched = matched;
    binding.parked = parked;
    binding.removed = removed;
    counts->actor_bindings.push_back(binding);
}

void RecordWorldSnapshotBinding(
    WorldSnapshotApplyCounts* counts,
    const ReplicatedWorldActorLocalBinding& local_binding,
    bool matched,
    bool parked,
    bool removed = false) {
    if (counts == nullptr || local_binding.network_actor_id == 0 || local_binding.actor.actor_address == 0) {
        return;
    }

    multiplayer::WorldSnapshotActorBindingRuntimeInfo binding;
    binding.network_actor_id = local_binding.network_actor_id;
    binding.local_actor_address = local_binding.actor.actor_address;
    binding.native_type_id = local_binding.actor.object_type_id;
    binding.enemy_type = local_binding.actor.enemy_type;
    binding.matched = matched;
    binding.parked = parked;
    binding.removed = removed;
    counts->actor_bindings.push_back(binding);
}

void ApplyReplicatedWorldActorDriveState(uintptr_t actor_address, std::uint8_t drive_state) {
    if (actor_address == 0 || kActorAnimationDriveStateByteOffset == 0) {
        return;
    }
    (void)ProcessMemory::Instance().TryWriteField(actor_address, kActorAnimationDriveStateByteOffset, drive_state);
}

bool IsReplicatedHubStudentSnapshot(const multiplayer::WorldActorSnapshot& authoritative_actor) {
    return authoritative_actor.native_type_id == 0x138A;
}

bool IsReplicatedNamedHubNpcSnapshot(
    const multiplayer::WorldActorSnapshot& authoritative_actor) {
    switch (authoritative_actor.native_type_id) {
    case 0x1389:
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

bool IsSaneReplicatedNamedHubNpcFloat(float value) {
    constexpr float kMaxMagnitude = 65536.0f;
    return std::isfinite(value) && value >= -kMaxMagnitude && value <= kMaxMagnitude;
}

bool ApplyReplicatedNamedHubNpcPresentation(
    uintptr_t actor_address,
    const multiplayer::WorldActorSnapshot& authoritative_actor) {
    if (actor_address == 0 ||
        !IsReplicatedNamedHubNpcSnapshot(authoritative_actor) ||
        kNamedHubNpcIdleAnimationBlockOffset == 0) {
        return false;
    }

    constexpr std::size_t kActiveOffset = 0x00;
    constexpr std::size_t kPhaseOffset = 0x04;
    constexpr std::size_t kFrameOffset = 0x08;
    constexpr std::size_t kRateOffset = 0x0C;
    constexpr std::size_t kAmplitudeOffset = 0x10;
    constexpr std::size_t kEnabledOffset = 0x14;
    const auto idle_block = actor_address + kNamedHubNpcIdleAnimationBlockOffset;
    const auto& state = authoritative_actor.named_hub_npc;
    auto& memory = ProcessMemory::Instance();
    bool wrote = false;

    const bool idle_animator_type =
        authoritative_actor.native_type_id == 0x138B ||
        authoritative_actor.native_type_id == 0x138C ||
        authoritative_actor.native_type_id == 0x138D ||
        authoritative_actor.native_type_id == 0x138F;
    if ((authoritative_actor.presentation_flags &
         multiplayer::WorldActorPresentationFlagNamedHubNpcIdleAnimator) != 0 &&
        idle_animator_type &&
        state.idle_active <= 1 &&
        state.idle_enabled <= 1 &&
        IsSaneReplicatedNamedHubNpcFloat(state.idle_phase) &&
        IsSaneReplicatedNamedHubNpcFloat(state.idle_frame) &&
        IsSaneReplicatedNamedHubNpcFloat(state.idle_rate) &&
        IsSaneReplicatedNamedHubNpcFloat(state.idle_amplitude)) {
        wrote = memory.TryWriteValue(idle_block + kActiveOffset, state.idle_active) || wrote;
        wrote = memory.TryWriteValue(idle_block + kPhaseOffset, state.idle_phase) || wrote;
        wrote = memory.TryWriteValue(idle_block + kFrameOffset, state.idle_frame) || wrote;
        wrote = memory.TryWriteValue(idle_block + kRateOffset, state.idle_rate) || wrote;
        wrote = memory.TryWriteValue(idle_block + kAmplitudeOffset, state.idle_amplitude) || wrote;
        wrote = memory.TryWriteValue(idle_block + kEnabledOffset, state.idle_enabled) || wrote;
    }

    if ((authoritative_actor.presentation_flags &
         multiplayer::WorldActorPresentationFlagNamedHubNpcWitchOrbit) != 0 &&
        authoritative_actor.native_type_id == 0x1389 &&
        IsSaneReplicatedNamedHubNpcFloat(state.idle_frame) &&
        IsSaneReplicatedNamedHubNpcFloat(state.idle_rate)) {
        wrote = memory.TryWriteValue(idle_block + kFrameOffset, state.idle_frame) || wrote;
        wrote = memory.TryWriteValue(idle_block + kRateOffset, state.idle_rate) || wrote;
    }

    if (kNamedHubNpcTypeSpecificStateBlockOffset == 0) {
        return wrote;
    }
    const auto type_block = actor_address + kNamedHubNpcTypeSpecificStateBlockOffset;

    if ((authoritative_actor.presentation_flags &
         multiplayer::WorldActorPresentationFlagNamedHubNpcPotionMotion) != 0 &&
        authoritative_actor.native_type_id == 0x138C &&
        IsSaneReplicatedNamedHubNpcFloat(state.motion_position) &&
        IsSaneReplicatedNamedHubNpcFloat(state.motion_direction) &&
        state.timer >= 0 &&
        state.timer <= 100000) {
        wrote = memory.TryWriteValue(type_block + 0x00, state.motion_position) || wrote;
        wrote = memory.TryWriteValue(type_block + 0x04, state.motion_direction) || wrote;
        wrote = memory.TryWriteValue(type_block + 0x08, state.timer) || wrote;
    }

    if ((authoritative_actor.presentation_flags &
         multiplayer::WorldActorPresentationFlagNamedHubNpcTyranniaPose) != 0 &&
        authoritative_actor.native_type_id == 0x138F &&
        state.timer >= -1 &&
        state.timer <= 100000 &&
        state.pose >= 0 &&
        state.pose <= 2 &&
        IsSaneReplicatedNamedHubNpcFloat(state.render_scale)) {
        wrote = memory.TryWriteValue(type_block + 0x00, state.timer) || wrote;
        wrote = memory.TryWriteValue(type_block + 0x04, state.pose) || wrote;
        wrote = memory.TryWriteValue(type_block + 0x08, state.render_scale) || wrote;
    }

    if ((authoritative_actor.presentation_flags &
         multiplayer::WorldActorPresentationFlagNamedHubNpcTeacherCycle) != 0 &&
        authoritative_actor.native_type_id == 0x1390 &&
        state.type_state_byte <= 1 &&
        IsSaneReplicatedNamedHubNpcFloat(state.idle_phase) &&
        IsSaneReplicatedNamedHubNpcFloat(state.idle_frame)) {
        wrote = memory.TryWriteValue(idle_block + kPhaseOffset, state.idle_phase) || wrote;
        wrote = memory.TryWriteValue(idle_block + kFrameOffset, state.idle_frame) || wrote;
        wrote = memory.TryWriteValue(type_block, state.type_state_byte) || wrote;
    }

    return wrote;
}

bool ApplyReplicatedWorldActorPresentation(
    uintptr_t actor_address,
    std::uint32_t local_native_type_id,
    const multiplayer::WorldActorSnapshot& authoritative_actor) {
    if (actor_address == 0 ||
        local_native_type_id == 0 ||
        local_native_type_id != authoritative_actor.native_type_id ||
        authoritative_actor.presentation_flags == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    bool wrote = false;
    if ((authoritative_actor.presentation_flags &
         multiplayer::WorldActorPresentationFlagAnimationDriveWord) != 0 &&
        kActorAnimationDriveStateByteOffset != 0) {
        wrote = memory.TryWriteField(
            actor_address,
            kActorAnimationDriveStateByteOffset,
            authoritative_actor.anim_drive_state_word) || wrote;
    }

    if (IsReplicatedNamedHubNpcSnapshot(authoritative_actor)) {
        wrote = ApplyReplicatedNamedHubNpcPresentation(
            actor_address,
            authoritative_actor) || wrote;
        return wrote;
    }

    if (!IsReplicatedHubStudentSnapshot(authoritative_actor)) {
        if ((authoritative_actor.presentation_flags &
             multiplayer::WorldActorPresentationFlagLocomotionFloats) != 0) {
            if (kActorWalkCyclePrimaryOffset != 0 && std::isfinite(authoritative_actor.walk_cycle_primary)) {
                wrote = memory.TryWriteField(
                    actor_address,
                    kActorWalkCyclePrimaryOffset,
                    authoritative_actor.walk_cycle_primary) || wrote;
            }
            if (kActorWalkCycleSecondaryOffset != 0 && std::isfinite(authoritative_actor.walk_cycle_secondary)) {
                wrote = memory.TryWriteField(
                    actor_address,
                    kActorWalkCycleSecondaryOffset,
                    authoritative_actor.walk_cycle_secondary) || wrote;
            }
        }
        return wrote;
    }

    if ((authoritative_actor.presentation_flags &
         multiplayer::WorldActorPresentationFlagStudentVisualState) != 0 &&
        kStudentVisualStateBlockOffset != 0) {
        wrote = memory.TryWrite(
            actor_address + kStudentVisualStateBlockOffset,
            authoritative_actor.student_visual_state.data(),
            authoritative_actor.student_visual_state.size()) || wrote;
    }

    if ((authoritative_actor.presentation_flags &
         multiplayer::WorldActorPresentationFlagStudentBookPalette) != 0 &&
        kStudentBookPaletteBlockOffset != 0 &&
        authoritative_actor.student_book_palette_count <=
            multiplayer::kWorldActorStudentBookPaletteMaxEntries) {
        constexpr std::size_t kStudentBookPaletteColorsOffset = 0x04;
        constexpr std::size_t kStudentBookPaletteRadialOffsetsOffset = 0x54;
        constexpr std::size_t kStudentBookPaletteAngularOffsetsOffset = 0x68;
        const auto palette_address = actor_address + kStudentBookPaletteBlockOffset;
        bool palette_valid = true;
        for (std::size_t index = 0;
             index < authoritative_actor.student_book_palette_count;
             ++index) {
            const auto& entry = authoritative_actor.student_book_palette[index];
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
                                value >= -4096.0f && value <= 4096.0f;
            }
        }
        if (palette_valid) {
            bool palette_written = true;
            for (std::size_t index = 0;
                 index < authoritative_actor.student_book_palette_count;
                 ++index) {
                const auto& entry = authoritative_actor.student_book_palette[index];
                palette_written = memory.TryWrite(
                    palette_address + kStudentBookPaletteColorsOffset + index * sizeof(float) * 4,
                    &entry.red,
                    sizeof(float) * 4) && palette_written;
                palette_written = memory.TryWriteValue(
                    palette_address + kStudentBookPaletteRadialOffsetsOffset + index * sizeof(float),
                    entry.radial_offset) && palette_written;
                palette_written = memory.TryWriteValue(
                    palette_address + kStudentBookPaletteAngularOffsetsOffset + index * sizeof(float),
                    entry.angular_offset) && palette_written;
            }
            if (palette_written) {
                palette_written = memory.TryWriteValue(
                    palette_address,
                    authoritative_actor.student_book_palette_count);
            }
            wrote = palette_written || wrote;
        }
    }

    if ((authoritative_actor.presentation_flags &
         multiplayer::WorldActorPresentationFlagStudentVariantBytes) != 0 &&
        kActorRenderVariantPrimaryOffset != 0 &&
        kActorRenderVariantSecondaryOffset != 0 &&
        kActorRenderWeaponTypeOffset != 0 &&
        kActorRenderSelectionByteOffset != 0 &&
        kActorRenderVariantTertiaryOffset != 0) {
        wrote = memory.TryWriteField(
            actor_address,
            kActorRenderVariantPrimaryOffset,
            authoritative_actor.render_variant_primary) || wrote;
        wrote = memory.TryWriteField(
            actor_address,
            kActorRenderVariantSecondaryOffset,
            authoritative_actor.render_variant_secondary) || wrote;
        wrote = memory.TryWriteField(
            actor_address,
            kActorRenderWeaponTypeOffset,
            authoritative_actor.render_weapon_type) || wrote;
        wrote = memory.TryWriteField(
            actor_address,
            kActorRenderSelectionByteOffset,
            authoritative_actor.render_selection_byte) || wrote;
        wrote = memory.TryWriteField(
            actor_address,
            kActorRenderVariantTertiaryOffset,
            authoritative_actor.render_variant_tertiary) || wrote;
    }

    return wrote;
}
