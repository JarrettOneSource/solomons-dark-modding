// Local world/loot snapshot packet construction and run-enemy write support.

bool BuildLocalWorldSnapshot(
    CompleteWorldSnapshotPacketState* complete_snapshot) {
    if (complete_snapshot == nullptr || !g_local_transport.is_host) {
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

    CompleteWorldSnapshotPacketState built;
    built.authority_participant_id = g_local_transport.local_peer_id;
    built.scene_epoch = g_local_transport.world_scene_epoch;
    built.scene_kind = WorldSceneKindFromSceneIntent(scene_intent);

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
    std::unordered_set<std::uint64_t> included_actor_ids;
    built.actors.reserve(
        (std::min<std::size_t>)(
            actors.size() +
                g_local_transport
                    .recent_run_enemy_deaths_by_network_id.size(),
            kWorldSnapshotMaxLogicalActors));
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
        if (built.actors.size() >=
            kWorldSnapshotMaxLogicalActors) {
            Log(
                "Multiplayer world snapshot rejected because the logical actor count exceeded " +
                std::to_string(kWorldSnapshotMaxLogicalActors) + ".");
            return false;
        }

        WorldActorSnapshotPacketState snapshot{};
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
            (void)PopulateRunEnemyTransientStatusSnapshot(
                actor.actor_address,
                actor.object_type_id,
                &snapshot);
        }
        snapshot.anim_drive_state = actor.anim_drive_state;
        snapshot.position_x = actor.x;
        snapshot.position_y = actor.y;
        snapshot.radius = actor.radius;
        snapshot.heading = ReadActorHeadingOrZero(actor.actor_address);
        snapshot.hp = std::isfinite(actor.hp) ? actor.hp : 0.0f;
        snapshot.max_hp = std::isfinite(actor.max_hp) ? actor.max_hp : 0.0f;
        SDModLuaEnemySpawnConfig lua_enemy_config;
        if (run_scene &&
            actor.tracked_enemy &&
            TryGetRunLifecycleLuaEnemySpawnConfig(
                actor.actor_address,
                &lua_enemy_config)) {
            snapshot.lua_content_id = lua_enemy_config.content_id;
            if (lua_enemy_config.hp_valid) {
                snapshot.lua_enemy_spawn_flags |=
                    LuaEnemySpawnSnapshotFlagHp;
                snapshot.lua_spawn_hp = lua_enemy_config.hp;
            }
            if (lua_enemy_config.chase_speed_valid) {
                snapshot.lua_enemy_spawn_flags |=
                    LuaEnemySpawnSnapshotFlagChaseSpeed;
                snapshot.lua_spawn_chase_speed =
                    lua_enemy_config.chase_speed;
            }
            if (lua_enemy_config.attack_speed_valid) {
                snapshot.lua_enemy_spawn_flags |=
                    LuaEnemySpawnSnapshotFlagAttackSpeed;
                snapshot.lua_spawn_attack_speed =
                    lua_enemy_config.attack_speed;
            }
            if (lua_enemy_config.scale_valid) {
                snapshot.lua_enemy_spawn_flags |=
                    LuaEnemySpawnSnapshotFlagScale;
                snapshot.lua_spawn_scale = lua_enemy_config.scale;
            }
        }
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
        built.actors.push_back(snapshot);
        if (run_scene && actor.tracked_enemy) {
            RetainedRunEnemySnapshot retained;
            retained.actor_address = actor.actor_address;
            retained.packet = snapshot;
            g_local_transport.retained_run_enemy_snapshots_by_network_id[
                network_actor_id] = retained;
        }
    }
    if (run_scene) {
        // Native enemy health can cross zero just before the stock death hook
        // runs. During that narrow interval TryListSceneActors may omit the
        // enemy even though its authoritative death tombstone has not been
        // recorded yet. Keep publishing the last complete tracked-enemy state
        // until either the death hook replaces it with a tombstone or the
        // native unregister hook explicitly retires the actor. An omission is
        // therefore never allowed to overtake the authoritative death effect.
        for (const auto& [network_actor_id, retained] :
             g_local_transport.retained_run_enemy_snapshots_by_network_id) {
            if (network_actor_id == 0 ||
                included_actor_ids.find(network_actor_id) !=
                    included_actor_ids.end() ||
                g_local_transport.recent_run_enemy_deaths_by_network_id.find(
                    network_actor_id) !=
                    g_local_transport.recent_run_enemy_deaths_by_network_id.end() ||
                retained.actor_address == 0 ||
                retained.packet.network_actor_id != network_actor_id ||
                (retained.packet.flags & WorldActorSnapshotFlagTrackedEnemy) == 0 ||
                (retained.packet.flags & WorldActorSnapshotFlagLifecycleOwned) == 0) {
                continue;
            }
            if (built.actors.size() >= kWorldSnapshotMaxLogicalActors) {
                Log(
                    "Multiplayer world snapshot rejected because retained tracked enemies exceeded " +
                    std::to_string(kWorldSnapshotMaxLogicalActors) + ".");
                return false;
            }
            built.actors.push_back(retained.packet);
            included_actor_ids.insert(network_actor_id);
        }
        for (const auto& [network_actor_id, death_snapshot] :
             g_local_transport.recent_run_enemy_deaths_by_network_id) {
            if (network_actor_id == 0 ||
                included_actor_ids.find(network_actor_id) != included_actor_ids.end() ||
                death_snapshot.native_type_id == 0 ||
                !std::isfinite(death_snapshot.max_hp) ||
                death_snapshot.max_hp <= 0.0f) {
                continue;
            }
            if (built.actors.size() >=
                kWorldSnapshotMaxLogicalActors) {
                Log(
                    "Multiplayer world snapshot rejected because live actors and death tombstones exceeded " +
                    std::to_string(kWorldSnapshotMaxLogicalActors) + ".");
                return false;
            }

            WorldActorSnapshotPacketState snapshot{};
            snapshot.network_actor_id = network_actor_id;
            snapshot.native_type_id = death_snapshot.native_type_id;
            snapshot.enemy_type = death_snapshot.enemy_type;
            snapshot.lua_content_id = death_snapshot.lua_content_id;
            snapshot.lua_enemy_spawn_flags =
                death_snapshot.lua_enemy_spawn_flags;
            snapshot.lua_spawn_hp = death_snapshot.lua_spawn_hp;
            snapshot.lua_spawn_chase_speed =
                death_snapshot.lua_spawn_chase_speed;
            snapshot.lua_spawn_attack_speed =
                death_snapshot.lua_spawn_attack_speed;
            snapshot.lua_spawn_scale = death_snapshot.lua_spawn_scale;
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
            built.actors.push_back(snapshot);
        }
    }
    built.snapshot_id =
        g_local_transport.next_world_snapshot_id++;
    *complete_snapshot = std::move(built);
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
    bool has_animated_drop = false;
    for (std::size_t index = 0; index < packet.drop_count; ++index) {
        const auto& drop = packet.drops[index];
        const auto drop_kind = LootDropKindFromPacketValue(drop.drop_kind);
        const bool active = (drop.flags & LootDropSnapshotFlagActive) != 0;
        if (!active) {
            continue;
        }
        if (drop_kind == LootDropKind::Gold ||
            drop_kind == LootDropKind::Orb ||
            drop_kind == LootDropKind::Powerup) {
            has_animated_drop = true;
            break;
        }
    }
    return BandwidthLimitedSnapshotIntervalMs(
        LootSnapshotPacketWireSize(packet.drop_count),
        has_animated_drop
            ? kLocalTransportAnimatedLootSnapshotIntervalMs
            : kLocalTransportLootSnapshotIntervalMs);
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
