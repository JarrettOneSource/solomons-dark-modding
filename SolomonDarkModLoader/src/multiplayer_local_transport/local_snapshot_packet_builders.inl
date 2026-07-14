// Local world/loot snapshot packet construction and run-enemy write support.

bool BuildLocalWorldSnapshotPacket(WorldSnapshotPacket* packet) {
    if (packet == nullptr || !g_local_transport.is_host) {
        return false;
    }

    SDModSceneState scene_state;
    if (!TryGetSceneState(&scene_state) || !scene_state.valid) {
        return false;
    }

    std::vector<SDModSceneActorState> actors;
    if (!TryListSceneActors(&actors)) {
        return false;
    }

    const auto scene_intent = SceneIntentFromLocalScene();
    if (scene_intent.kind != ParticipantSceneIntentKind::SharedHub &&
        scene_intent.kind != ParticipantSceneIntentKind::Run) {
        return false;
    }

    RefreshWorldSceneTracking(scene_state);
    PruneHubWorldActorNetworkIds(actors, scene_intent.kind);
    PruneRunHostLocalWorldActorNetworkIds(actors, scene_intent.kind);

    WorldSnapshotPacket built{};
    built.header = MakePacketHeader(PacketKind::WorldSnapshot, g_local_transport.next_sequence++);
    built.authority_participant_id = g_local_transport.local_peer_id;
    built.scene_epoch = g_local_transport.world_scene_epoch;
    built.scene_kind = static_cast<std::uint8_t>(WorldSceneKindFromSceneIntent(scene_intent));

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local != nullptr) {
        built.run_nonce = local->runtime.run_nonce;
    }

    const bool run_scene = scene_intent.kind == ParticipantSceneIntentKind::Run;
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    if (run_scene) {
        PruneRecentRunEnemyDeathSnapshots(now_ms);
    }
    std::uint32_t valid_recent_death_count = 0;
    if (run_scene) {
        for (const auto& [network_actor_id, death_snapshot] :
             g_local_transport.recent_run_enemy_deaths_by_network_id) {
            if (network_actor_id != 0 &&
                death_snapshot.native_type_id != 0 &&
                std::isfinite(death_snapshot.max_hp) &&
                death_snapshot.max_hp > 0.0f) {
                valid_recent_death_count += 1;
            }
        }
    }
    constexpr std::uint32_t kWorldSnapshotRecentDeathReservedSlots = 16;
    const std::uint32_t reserved_recent_death_slots =
        run_scene
            ? (std::min<std::uint32_t>)(
                  valid_recent_death_count,
                  (std::min<std::uint32_t>)(kWorldSnapshotRecentDeathReservedSlots, kWorldSnapshotMaxActors))
            : 0;
    const std::uint32_t live_actor_snapshot_budget =
        kWorldSnapshotMaxActors > reserved_recent_death_slots
            ? kWorldSnapshotMaxActors - reserved_recent_death_slots
            : 0;
    std::unordered_set<std::uint64_t> included_actor_ids;
    std::uint32_t total_actor_count = 0;
    for (const auto& actor : actors) {
        if (!ShouldReplicateWorldActor(actor, scene_intent.kind)) {
            continue;
        }
        if (run_scene &&
            actor.tracked_enemy &&
            actor.dead &&
            HasRecentRunEnemyDeathSnapshotForActor(actor.actor_address)) {
            continue;
        }
        std::uint64_t network_actor_id = 0;
        if (run_scene) {
            std::uint32_t spawn_serial = 0;
            if (TryGetRunLifecycleEnemySpawnSerial(actor.actor_address, &spawn_serial)) {
                g_local_transport.run_host_local_world_actor_ids_by_address.erase(actor.actor_address);
                network_actor_id = BuildRunWorldActorNetworkId(spawn_serial);
            } else {
                network_actor_id = AllocateRunHostLocalWorldActorNetworkId(actor);
            }
        } else {
            network_actor_id = AllocateHubWorldActorNetworkId(actor);
        }
        if (network_actor_id == 0) {
            continue;
        }
        included_actor_ids.insert(network_actor_id);
        total_actor_count += 1;
        if (built.actor_count >= live_actor_snapshot_budget) {
            continue;
        }

        auto& snapshot = built.actors[built.actor_count];
        snapshot.network_actor_id = network_actor_id;
        snapshot.native_type_id = actor.object_type_id;
        snapshot.enemy_type = actor.enemy_type;
        snapshot.actor_slot = actor.actor_slot;
        snapshot.world_slot = actor.world_slot;
        snapshot.target_actor_slot = -1;
        snapshot.target_world_slot = -1;
        if (run_scene && actor.tracked_enemy) {
            snapshot.flags |= WorldActorSnapshotFlagTargetAuthoritative;
            snapshot.target_participant_id = ResolveRunEnemyTargetParticipantId(actor.actor_address);
            (void)PopulateRunEnemyNativeTargetSnapshot(actor.actor_address, &snapshot);
        }
        snapshot.anim_drive_state = actor.anim_drive_state;
        snapshot.position_x = actor.x;
        snapshot.position_y = actor.y;
        snapshot.radius = actor.radius;
        snapshot.heading = ReadActorHeadingOrZero(actor.actor_address);
        snapshot.hp = std::isfinite(actor.hp) ? actor.hp : 0.0f;
        snapshot.max_hp = std::isfinite(actor.max_hp) ? actor.max_hp : 0.0f;
        PopulateWorldActorPresentationSnapshot(
            actor.actor_address,
            actor.object_type_id,
            scene_intent.kind,
            actor.tracked_enemy,
            &snapshot);
        if (actor.dead) {
            snapshot.flags |= WorldActorSnapshotFlagDead;
        }
        if (actor.tracked_enemy) {
            snapshot.flags |= WorldActorSnapshotFlagTrackedEnemy;
        }
        if (run_scene && IsRunStaticLayoutActor(actor)) {
            snapshot.flags |= WorldActorSnapshotFlagRunStatic;
        }
        if (run_scene &&
            IsReplicatedRunPlayerCreatedActorType(actor.object_type_id)) {
            snapshot.flags |= WorldActorSnapshotFlagPlayerCreated;
        }
        if (run_scene) {
            snapshot.flags |= WorldActorSnapshotFlagLifecycleOwned;
        }
        built.actor_count += 1;
    }
    if (run_scene) {
        for (const auto& [network_actor_id, death_snapshot] :
             g_local_transport.recent_run_enemy_deaths_by_network_id) {
            if (network_actor_id == 0 ||
                included_actor_ids.find(network_actor_id) != included_actor_ids.end() ||
                death_snapshot.native_type_id == 0 ||
                !std::isfinite(death_snapshot.max_hp) ||
                death_snapshot.max_hp <= 0.0f) {
                continue;
            }
            total_actor_count += 1;
            if (built.actor_count >= kWorldSnapshotMaxActors) {
                continue;
            }

            auto& snapshot = built.actors[built.actor_count];
            snapshot.network_actor_id = network_actor_id;
            snapshot.native_type_id = death_snapshot.native_type_id;
            snapshot.enemy_type = death_snapshot.enemy_type;
            snapshot.actor_slot = -1;
            snapshot.world_slot = -1;
            snapshot.target_actor_slot = -1;
            snapshot.target_world_slot = -1;
            snapshot.flags =
                WorldActorSnapshotFlagDead |
                WorldActorSnapshotFlagTrackedEnemy |
                WorldActorSnapshotFlagLifecycleOwned;
            snapshot.position_x = death_snapshot.position_x;
            snapshot.position_y = death_snapshot.position_y;
            snapshot.radius = death_snapshot.radius;
            snapshot.heading = death_snapshot.heading;
            snapshot.hp = 0.0f;
            snapshot.max_hp = death_snapshot.max_hp;
            built.actor_count += 1;
        }
    }
    built.actor_total_count = static_cast<std::uint8_t>((std::min<std::uint32_t>)(total_actor_count, 0xFFu));
    if (total_actor_count > built.actor_count) {
        built.snapshot_flags |= WorldSnapshotFlagTruncated;
    }

    *packet = built;
    return true;
}

bool BuildLocalLootSnapshotPacket(LootSnapshotPacket* packet) {
    if (packet == nullptr || !g_local_transport.is_host) {
        return false;
    }

    SDModSceneState scene_state;
    if (!TryGetSceneState(&scene_state) || !scene_state.valid) {
        return false;
    }

    std::vector<SDModSceneActorState> actors;
    if (!TryListSceneActors(&actors)) {
        return false;
    }

    const auto scene_intent = SceneIntentFromLocalScene();
    if (scene_intent.kind != ParticipantSceneIntentKind::Run) {
        PruneRunLootDropNetworkIds(actors, scene_intent.kind);
        return false;
    }

    RefreshWorldSceneTracking(scene_state);
    PruneRunLootDropNetworkIds(actors, scene_intent.kind);

    LootSnapshotPacket built{};
    built.header = MakePacketHeader(PacketKind::LootSnapshot, g_local_transport.next_sequence++);
    built.authority_participant_id = g_local_transport.local_peer_id;
    built.scene_epoch = g_local_transport.world_scene_epoch;
    built.scene_kind = static_cast<std::uint8_t>(WorldSceneKindFromSceneIntent(scene_intent));

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local != nullptr) {
        built.run_nonce = local->runtime.run_nonce;
    }

    std::uint32_t total_drop_count = 0;
    for (const auto& actor : actors) {
        if (!ShouldReplicateLootDropActor(actor, scene_intent.kind)) {
            continue;
        }

        const auto network_drop_id = AllocateRunLootDropNetworkId(actor);
        if (network_drop_id == 0) {
            continue;
        }
        if (g_local_transport.accepted_loot_pickup_drop_ids.find(network_drop_id) !=
            g_local_transport.accepted_loot_pickup_drop_ids.end()) {
            continue;
        }

        LootDropSnapshotPacketState snapshot{};
        if (!TryPopulateLootDropSnapshot(actor, network_drop_id, &snapshot)) {
            continue;
        }
        if ((snapshot.flags & LootDropSnapshotFlagActive) == 0) {
            continue;
        }

        total_drop_count += 1;
        if (built.drop_count >= kLootSnapshotMaxDrops) {
            continue;
        }

        built.drops[built.drop_count] = snapshot;
        built.drop_count += 1;
    }

    built.drop_total_count = static_cast<std::uint8_t>((std::min<std::uint32_t>)(total_drop_count, 0xFFu));
    if (total_drop_count > built.drop_count) {
        built.snapshot_flags |= LootSnapshotFlagTruncated;
    }

    *packet = built;
    return true;
}

std::uint64_t LootSnapshotIntervalForPacket(const LootSnapshotPacket& packet) {
    for (std::size_t index = 0; index < packet.drop_count; ++index) {
        const auto& drop = packet.drops[index];
        const auto drop_kind = LootDropKindFromPacketValue(drop.drop_kind);
        const bool active = (drop.flags & LootDropSnapshotFlagActive) != 0;
        if (!active) {
            continue;
        }
        if (drop_kind == LootDropKind::Gold || drop_kind == LootDropKind::Orb) {
            return kLocalTransportAnimatedLootSnapshotIntervalMs;
        }
    }
    return kLocalTransportLootSnapshotIntervalMs;
}

float ClampEnemyHp(float hp, float max_hp) {
    if (!std::isfinite(hp)) {
        return 0.0f;
    }
    if (hp < 0.0f) {
        return 0.0f;
    }
    if (std::isfinite(max_hp) && max_hp > 0.0f && hp > max_hp) {
        return max_hp;
    }
    return hp;
}

float DistanceSquared(float ax, float ay, float bx, float by) {
    const float dx = ax - bx;
    const float dy = ay - by;
    return dx * dx + dy * dy;
}

bool TryWriteRunEnemyHealth(uintptr_t actor_address, float hp, float max_hp) {
    if (actor_address == 0 ||
        kEnemyCurrentHpOffset == 0 ||
        kEnemyMaxHpOffset == 0 ||
        !std::isfinite(max_hp) ||
        max_hp <= 0.0f) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const float clamped_hp = ClampEnemyHp(hp, max_hp);
    // Run enemies own health directly on their arena-actor object.  Do not
    // probe the wizard-only actor+0x200 progression seam here: on stock enemy
    // classes that field has unrelated meaning, and a readable pointer is not
    // proof that it names a progression object.  Writing HP through that
    // pointer corrupted native callbacks/heap metadata with values such as
    // 0x42200000 (40.0f) during clustered spell tests.
    return
        memory.TryWriteField(actor_address, kEnemyMaxHpOffset, max_hp) &&
        memory.TryWriteField(actor_address, kEnemyCurrentHpOffset, clamped_hp);
}
