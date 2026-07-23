void RemoveReplicatedCreatedSharedHubActorsForSceneSwitch(const char* reason) {
    if (g_replicated_created_hub_actors.empty()) {
        return;
    }

    const auto abandoned_count =
        static_cast<std::uint32_t>(g_replicated_created_hub_actors.size());
    // These actors are registered to the native hub world. During region switch
    // the stock scene teardown owns their lifetime; unregistering them here can
    // corrupt the world heap and then fault inside native switch_region.
    ClearReplicatedSharedHubActorBindings();
    g_replicated_created_hub_scene_epoch = 0;
    Log(
        "world_snapshot: abandoned replicated hub actor bindings for scene switch. reason=" +
        std::string(reason != nullptr ? reason : "unknown") +
        " count=" + std::to_string(abandoned_count));
}
std::vector<ReplicatedWorldActorLocalBinding> BuildLocalReplicatedWorldActorBindings(
    multiplayer::ParticipantSceneIntentKind scene_kind) {
    std::vector<SDModSceneActorState> scene_actors;
    if (!TryListSceneActors(&scene_actors)) {
        return {};
    }

    std::unordered_map<std::uint32_t, std::uint32_t> type_ordinals;
    std::vector<ReplicatedWorldActorLocalBinding> bindings;
    bindings.reserve(scene_actors.size());
    if (scene_kind == multiplayer::ParticipantSceneIntentKind::Run) {
        PruneReplicatedRunActorBindings(scene_actors);
    } else if (scene_kind == multiplayer::ParticipantSceneIntentKind::SharedHub) {
        PruneReplicatedSharedHubActorBindings(scene_actors);
    }
    for (const auto& actor : scene_actors) {
        if (!ShouldReconcileLocalWorldActor(actor, scene_kind)) {
            continue;
        }

        ReplicatedWorldActorLocalBinding binding;
        binding.actor = actor;
        if (scene_kind == multiplayer::ParticipantSceneIntentKind::Run) {
            binding.network_actor_id = LookupReplicatedRunActorNetworkId(actor.actor_address);
        } else if (scene_kind == multiplayer::ParticipantSceneIntentKind::SharedHub) {
            binding.network_actor_id = LookupReplicatedSharedHubActorNetworkId(actor.actor_address);
        } else {
            const auto type_ordinal = ++type_ordinals[actor.object_type_id];
            binding.network_actor_id = BuildReplicatedWorldActorNetworkId(actor, type_ordinal);
        }
        bindings.push_back(binding);
    }
    return bindings;
}

bool IsLocalRunCombatAlreadyActive() {
    if (IsRunLifecycleActive() && GetRunLifecycleCurrentWave() > 0) {
        return true;
    }

    SDModGameplayCombatState combat_state;
    if (!TryGetGameplayCombatState(&combat_state) || !combat_state.valid) {
        return false;
    }
    return combat_state.combat_active != 0 ||
           combat_state.combat_started_music != 0 ||
           combat_state.combat_wave_index > 0;
}

bool TryQueueClientRunLifecycle(std::uint64_t now_ms, const char* source_label) {
    if (IsLocalRunCombatAlreadyActive()) {
        return false;
    }

    static std::uint64_t s_last_run_lifecycle_request_ms = 0;
    if (now_ms >= s_last_run_lifecycle_request_ms &&
        now_ms - s_last_run_lifecycle_request_ms < kWorldSnapshotRunLifecycleRequestIntervalMs) {
        return false;
    }
    s_last_run_lifecycle_request_ms = now_ms;

    std::string error_message;
    if (!QueueGameplayStartWaves(&error_message)) {
        Log(
            "world_snapshot: failed to queue client run lifecycle. source=" +
            std::string(source_label != nullptr ? source_label : "unknown") +
            " detail=" + error_message);
        return false;
    }
    Log(
        "world_snapshot: queued client run lifecycle. source=" +
        std::string(source_label != nullptr ? source_label : "unknown"));
    return true;
}

std::uint32_t CountAuthoritativeTrackedRunEnemiesForScene(
    const multiplayer::WorldSnapshotRuntimeInfo& snapshot);

void MaybeQueueRunLifecycleForRemoteAuthority(std::uint64_t now_ms) {
    if (multiplayer::IsLocalTransportClient()) {
        return;
    }

    SDModSceneState scene_state;
    if (!TryGetSceneState(&scene_state) ||
        !scene_state.valid ||
        SceneIntentKindFromSceneState(scene_state) != multiplayer::ParticipantSceneIntentKind::Run) {
        return;
    }

    const auto runtime_state = multiplayer::SnapshotRuntimeState();
    for (const auto& participant : runtime_state.participants) {
        if (!multiplayer::IsRemoteParticipant(participant) ||
            !participant.runtime.valid ||
            !participant.runtime.in_run ||
            participant.runtime.wave <= 0) {
            continue;
        }
        (void)TryQueueClientRunLifecycle(now_ms, "remote_state_wave");
        return;
    }
}

void MaybeQueueRunLifecycleForAuthoritativeSnapshot(
    const multiplayer::WorldSnapshotRuntimeInfo& snapshot,
    std::uint64_t now_ms) {
    if (snapshot.scene_intent.kind != multiplayer::ParticipantSceneIntentKind::Run ||
        snapshot.actors.empty()) {
        return;
    }
    if (CountAuthoritativeTrackedRunEnemiesForScene(snapshot) == 0) {
        return;
    }
    (void)TryQueueClientRunLifecycle(now_ms, "world_snapshot");
}

std::uint32_t CountAuthoritativeTrackedRunEnemiesForScene(
    const multiplayer::WorldSnapshotRuntimeInfo& snapshot) {
    if (snapshot.scene_intent.kind != multiplayer::ParticipantSceneIntentKind::Run) {
        return 0;
    }

    std::uint32_t count = 0;
    for (const auto& authoritative_actor : snapshot.actors) {
        if (authoritative_actor.tracked_enemy &&
            !IsAuthoritativeRunTrackedEnemyDeadSnapshot(authoritative_actor) &&
            ShouldUseAuthoritativeWorldActorForScene(authoritative_actor, snapshot.scene_intent.kind)) {
            count += 1;
        }
    }
    return count;
}

void MaybeCatchUpRunEnemyPoolForAuthoritativeSnapshot(
    const multiplayer::WorldSnapshotRuntimeInfo& snapshot,
    const std::vector<ReplicatedWorldActorLocalBinding>& local_bindings) {
    if (snapshot.scene_intent.kind != multiplayer::ParticipantSceneIntentKind::Run) {
        return;
    }
    if (!IsLocalRunCombatAlreadyActive()) {
        return;
    }
    if (IsRunLifecycleManualEnemySpawnerTestModeEnabled()) {
        return;
    }

    std::unordered_map<int, std::uint32_t> authoritative_counts_by_enemy_type;
    for (const auto& authoritative_actor : snapshot.actors) {
        if (authoritative_actor.enemy_type < 0 ||
            !authoritative_actor.tracked_enemy ||
            !ShouldUseAuthoritativeWorldActorForScene(
                authoritative_actor,
                multiplayer::ParticipantSceneIntentKind::Run) ||
            IsAuthoritativeRunTrackedEnemyDeadSnapshot(authoritative_actor)) {
            continue;
        }
        authoritative_counts_by_enemy_type[authoritative_actor.enemy_type] += 1;
    }

    std::unordered_map<int, std::uint32_t> local_counts_by_enemy_type;
    for (const auto& binding : local_bindings) {
        if (binding.actor.enemy_type < 0 ||
            !binding.actor.tracked_enemy ||
            binding.actor.dead ||
            !std::isfinite(binding.actor.hp) ||
            !std::isfinite(binding.actor.max_hp) ||
            binding.actor.max_hp <= 0.0f ||
            binding.actor.hp <= kReplicatedRunEnemyDeathHpEpsilon ||
            !ShouldReconcileLocalWorldActor(
                binding.actor,
                multiplayer::ParticipantSceneIntentKind::Run)) {
            continue;
        }
        local_counts_by_enemy_type[binding.actor.enemy_type] += 1;
    }

    for (const auto& [enemy_type, authoritative_count] : authoritative_counts_by_enemy_type) {
        const auto local_it = local_counts_by_enemy_type.find(enemy_type);
        const auto local_count =
            local_it != local_counts_by_enemy_type.end() ? local_it->second : 0;
        if (authoritative_count <= local_count) {
            continue;
        }
        (void)TryAccelerateRunLifecycleEnemyPoolForSnapshot(
            enemy_type,
            authoritative_count - local_count);
    }
}

bool HasPendingReplicatedRunEnemyMaterialization(std::uint64_t network_actor_id, std::uint64_t now_ms) {
    if (network_actor_id == 0) {
        return false;
    }
    const auto pending_it = g_replicated_run_pending_enemy_materialization_until_ms.find(network_actor_id);
    if (pending_it == g_replicated_run_pending_enemy_materialization_until_ms.end()) {
        return false;
    }
    if (now_ms < pending_it->second) {
        return true;
    }
    g_replicated_run_pending_enemy_materialization_until_ms.erase(pending_it);
    return false;
}

bool QueueReplicatedManualRunEnemyMaterialization(
    const multiplayer::WorldActorSnapshot& authoritative_actor,
    std::uint64_t now_ms) {
    if (!multiplayer::IsLocalTransportClient() ||
        authoritative_actor.network_actor_id == 0 ||
        !authoritative_actor.lifecycle_owned ||
        !authoritative_actor.tracked_enemy ||
        authoritative_actor.enemy_type < 0 ||
        IsAuthoritativeRunTrackedEnemyDeadSnapshot(authoritative_actor) ||
        HasReplicatedRunEnemyDeathPresentationStarted(authoritative_actor.network_actor_id) ||
        multiplayer::HasLocalPendingLethalEnemyDamageClaim(authoritative_actor.network_actor_id, now_ms) ||
        !std::isfinite(authoritative_actor.position_x) ||
        !std::isfinite(authoritative_actor.position_y) ||
        HasPendingReplicatedRunEnemyMaterialization(authoritative_actor.network_actor_id, now_ms)) {
        return false;
    }

    std::string error_message;
    std::uint64_t request_id = 0;
    SDModLuaEnemySpawnConfig lua_config;
    lua_config.content_id = authoritative_actor.lua_content_id;
    lua_config.hp_valid =
        (authoritative_actor.lua_enemy_spawn_flags &
         multiplayer::LuaEnemySpawnSnapshotFlagHp) != 0;
    lua_config.hp = authoritative_actor.lua_spawn_hp;
    lua_config.chase_speed_valid =
        (authoritative_actor.lua_enemy_spawn_flags &
         multiplayer::LuaEnemySpawnSnapshotFlagChaseSpeed) != 0;
    lua_config.chase_speed = authoritative_actor.lua_spawn_chase_speed;
    lua_config.attack_speed_valid =
        (authoritative_actor.lua_enemy_spawn_flags &
         multiplayer::LuaEnemySpawnSnapshotFlagAttackSpeed) != 0;
    lua_config.attack_speed = authoritative_actor.lua_spawn_attack_speed;
    lua_config.scale_valid =
        (authoritative_actor.lua_enemy_spawn_flags &
         multiplayer::LuaEnemySpawnSnapshotFlagScale) != 0;
    lua_config.scale = authoritative_actor.lua_spawn_scale;
    const bool queued = QueueRunLifecycleReplicatedEnemyCatchupSpawn(
        authoritative_actor.network_actor_id,
        lua_config,
        static_cast<int>(authoritative_actor.native_type_id),
        authoritative_actor.position_x,
        authoritative_actor.position_y,
        &error_message,
        &request_id);
    g_replicated_run_pending_enemy_materialization_until_ms[authoritative_actor.network_actor_id] =
        now_ms + (queued ? 1500u : 250u);
    if (queued) {
        Log(
            "world_snapshot: queued replicated manual run enemy materialization. network_actor_id=" +
                std::to_string(authoritative_actor.network_actor_id) +
                " request_id=" + std::to_string(request_id) +
                " content_id=" + std::to_string(lua_config.content_id) +
                " native_type=" + std::to_string(authoritative_actor.native_type_id) +
                " pos=(" + std::to_string(authoritative_actor.position_x) + "," +
                std::to_string(authoritative_actor.position_y) + ")");
    } else {
        static std::uint64_t s_last_replicated_manual_materialization_fail_log_ms = 0;
        if (now_ms - s_last_replicated_manual_materialization_fail_log_ms >= 1000) {
            s_last_replicated_manual_materialization_fail_log_ms = now_ms;
            Log(
                "world_snapshot: failed to queue replicated manual run enemy materialization. network_actor_id=" +
                std::to_string(authoritative_actor.network_actor_id) +
                " native_type=" + std::to_string(authoritative_actor.native_type_id) +
                " detail=\"" + error_message + "\"");
        }
    }
    return queued;
}

bool TryBindAuthoritativeRunActorToLocalPool(
    const multiplayer::WorldActorSnapshot& authoritative_actor,
    const std::unordered_set<std::uint64_t>& authoritative_ids,
    std::vector<ReplicatedWorldActorLocalBinding>* local_bindings,
    std::uint64_t now_ms,
    std::size_t* binding_index_out) {
    if (binding_index_out != nullptr) {
        *binding_index_out = 0;
    }
    if (local_bindings == nullptr ||
        authoritative_actor.network_actor_id == 0 ||
        authoritative_actor.native_type_id == 0) {
        return false;
    }
    if (multiplayer::IsLocalTransportClient() &&
        HasReplicatedRunEnemyDeathPresentationStarted(authoritative_actor.network_actor_id)) {
        return false;
    }

    auto choose_binding = [&](bool require_enemy_type, bool prefer_nearest) -> bool {
        float best_distance_sq = (std::numeric_limits<float>::max)();
        std::size_t best_index = 0;
        bool found = false;
        for (std::size_t index = 0; index < local_bindings->size(); ++index) {
            auto& binding = (*local_bindings)[index];
            if (binding.matched ||
                binding.actor.actor_address == 0 ||
                !IsSameReplicatedRunEnemyKind(binding.actor, authoritative_actor)) {
                continue;
            }
            if (binding.network_actor_id != 0 &&
                binding.network_actor_id != authoritative_actor.network_actor_id) {
                if (authoritative_ids.find(binding.network_actor_id) != authoritative_ids.end() ||
                    IsReplicatedRunEnemyDeathPending(binding.network_actor_id, now_ms) ||
                    IsRunEnemyNativeDeathHandled(binding.actor.actor_address)) {
                    continue;
                }
                const auto stale_network_actor_id = binding.network_actor_id;
                UnbindReplicatedRunActor(stale_network_actor_id, binding.actor.actor_address);
                binding.network_actor_id = 0;
                Log(
                    "world_snapshot: recycling stale local run enemy binding. actor=" +
                    HexString(binding.actor.actor_address) +
                    " stale_network_actor_id=" + std::to_string(stale_network_actor_id) +
                    " replacement_network_actor_id=" +
                    std::to_string(authoritative_actor.network_actor_id));
            }
            if (require_enemy_type &&
                authoritative_actor.enemy_type >= 0 &&
                binding.actor.enemy_type >= 0 &&
                binding.actor.enemy_type != authoritative_actor.enemy_type) {
                continue;
            }

            if (prefer_nearest) {
                const float dx = authoritative_actor.position_x - binding.actor.x;
                const float dy = authoritative_actor.position_y - binding.actor.y;
                const float distance_sq = dx * dx + dy * dy;
                if (!found || distance_sq < best_distance_sq) {
                    found = true;
                    best_index = index;
                    best_distance_sq = distance_sq;
                }
                continue;
            }

            found = true;
            best_index = index;
            break;
        }

        if (!found) {
            return false;
        }
        auto& binding = (*local_bindings)[best_index];
        const auto previous_network_actor_id = binding.network_actor_id;
        if (previous_network_actor_id != 0 &&
            previous_network_actor_id != authoritative_actor.network_actor_id) {
            UnbindReplicatedRunActor(previous_network_actor_id, binding.actor.actor_address);
        }
        BindReplicatedRunActor(authoritative_actor.network_actor_id, binding.actor.actor_address);
        binding.network_actor_id = authoritative_actor.network_actor_id;
        if (binding_index_out != nullptr) {
            *binding_index_out = best_index;
        }
        return true;
    };

    const bool prefer_nearest =
        authoritative_actor.run_static ||
        authoritative_actor.tracked_enemy ||
        authoritative_actor.player_created;
    return choose_binding(true, prefer_nearest) || choose_binding(false, prefer_nearest);
}

bool TryBindAuthoritativeDeadRunEnemyToLocalPool(
    const multiplayer::WorldActorSnapshot& authoritative_actor,
    const std::unordered_set<std::uint64_t>& authoritative_ids,
    std::vector<ReplicatedWorldActorLocalBinding>* local_bindings,
    std::size_t* binding_index_out) {
    if (binding_index_out != nullptr) {
        *binding_index_out = 0;
    }
    if (local_bindings == nullptr ||
        authoritative_actor.network_actor_id == 0 ||
        authoritative_actor.native_type_id == 0 ||
        !authoritative_actor.lifecycle_owned ||
        !IsAuthoritativeRunTrackedEnemyDeadSnapshot(authoritative_actor)) {
        return false;
    }
    if (HasReplicatedRunEnemyDeathPresentationStarted(authoritative_actor.network_actor_id)) {
        return false;
    }

    auto choose_binding = [&](bool require_enemy_type) -> bool {
        float best_distance_sq = (std::numeric_limits<float>::max)();
        std::size_t best_index = 0;
        bool found = false;
        for (std::size_t index = 0; index < local_bindings->size(); ++index) {
            auto& binding = (*local_bindings)[index];
            if (binding.matched ||
                binding.actor.actor_address == 0 ||
                !binding.actor.tracked_enemy ||
                !IsSameReplicatedRunEnemyKind(binding.actor, authoritative_actor) ||
                !ShouldReconcileLocalWorldActor(binding.actor, multiplayer::ParticipantSceneIntentKind::Run)) {
                continue;
            }
            if (binding.network_actor_id != 0 &&
                binding.network_actor_id != authoritative_actor.network_actor_id &&
                authoritative_ids.find(binding.network_actor_id) != authoritative_ids.end()) {
                continue;
            }
            if (require_enemy_type &&
                authoritative_actor.enemy_type >= 0 &&
                binding.actor.enemy_type >= 0 &&
                binding.actor.enemy_type != authoritative_actor.enemy_type) {
                continue;
            }

            const float dx = authoritative_actor.position_x - binding.actor.x;
            const float dy = authoritative_actor.position_y - binding.actor.y;
            const float distance_sq = dx * dx + dy * dy;
            if (!found || distance_sq < best_distance_sq) {
                found = true;
                best_index = index;
                best_distance_sq = distance_sq;
            }
        }
        if (!found) {
            return false;
        }

        auto& binding = (*local_bindings)[best_index];
        const auto previous_network_actor_id = binding.network_actor_id;
        if (previous_network_actor_id != 0 &&
            previous_network_actor_id != authoritative_actor.network_actor_id) {
            UnbindReplicatedRunActor(previous_network_actor_id, binding.actor.actor_address);
        }
        BindReplicatedRunActor(authoritative_actor.network_actor_id, binding.actor.actor_address);
        binding.network_actor_id = authoritative_actor.network_actor_id;
        if (binding_index_out != nullptr) {
            *binding_index_out = best_index;
        }
        Log(
            "world_snapshot: bound authoritative dead run enemy snapshot to local actor. actor=" +
            HexString(binding.actor.actor_address) +
            " network_actor_id=" + std::to_string(authoritative_actor.network_actor_id) +
            " previous_network_actor_id=" + std::to_string(previous_network_actor_id) +
            " type=" + HexString(static_cast<uintptr_t>(authoritative_actor.native_type_id)) +
            " enemy_type=" + std::to_string(authoritative_actor.enemy_type) +
            " distance_sq=" + std::to_string(best_distance_sq));
        return true;
    };

    return choose_binding(true) || choose_binding(false);
}

bool TryBindAuthoritativeSharedHubActorToLocalPool(
    const multiplayer::WorldActorSnapshot& authoritative_actor,
    std::vector<ReplicatedWorldActorLocalBinding>* local_bindings,
    std::size_t* binding_index_out) {
    if (binding_index_out != nullptr) {
        *binding_index_out = 0;
    }
    if (local_bindings == nullptr ||
        authoritative_actor.network_actor_id == 0 ||
        !IsReplicatedSharedHubFactoryActorType(
            authoritative_actor.native_type_id)) {
        return false;
    }

    auto choose_binding = [&]() -> bool {
        float best_distance_sq = (std::numeric_limits<float>::max)();
        std::size_t best_index = 0;
        bool found = false;
        for (std::size_t index = 0; index < local_bindings->size(); ++index) {
            auto& binding = (*local_bindings)[index];
            if (binding.matched ||
                binding.actor.actor_address == 0 ||
                binding.network_actor_id != 0 ||
                binding.actor.object_type_id != authoritative_actor.native_type_id) {
                continue;
            }
            const float dx = authoritative_actor.position_x - binding.actor.x;
            const float dy = authoritative_actor.position_y - binding.actor.y;
            const float distance_sq = dx * dx + dy * dy;
            if (!found || distance_sq < best_distance_sq) {
                found = true;
                best_index = index;
                best_distance_sq = distance_sq;
            }
        }
        if (!found) {
            return false;
        }

        auto& binding = (*local_bindings)[best_index];
        BindReplicatedSharedHubActor(authoritative_actor.network_actor_id, binding.actor.actor_address);
        binding.network_actor_id = authoritative_actor.network_actor_id;
        if (binding_index_out != nullptr) {
            *binding_index_out = best_index;
        }
        return true;
    };

    return choose_binding();
}

void PublishWorldSnapshotApplyCounts(
    const multiplayer::WorldSnapshotRuntimeInfo& snapshot,
    const multiplayer::WorldSnapshotRuntimeInfo& presentation_snapshot,
    const WorldSnapshotApplyCounts& counts,
    std::uint64_t now_ms,
    bool holding_stale_snapshot,
    std::uint64_t source_snapshot_age_ms) {
    multiplayer::UpdateRuntimeState([&](multiplayer::RuntimeState& state) {
        state.world_snapshot_apply.valid = true;
        state.world_snapshot_apply.holding_stale_snapshot =
            holding_stale_snapshot;
        state.world_snapshot_apply.applied_ms = now_ms;
        state.world_snapshot_apply.source_snapshot_age_ms =
            source_snapshot_age_ms;
        state.world_snapshot_apply.sequence = snapshot.sequence;
        state.world_snapshot_apply.scene_epoch = snapshot.scene_epoch;
        state.world_snapshot_apply.presentation_sequence = presentation_snapshot.sequence;
        state.world_snapshot_apply.presentation_scene_epoch = presentation_snapshot.scene_epoch;
        state.world_snapshot_apply.presentation_received_ms = presentation_snapshot.received_ms;
        state.world_snapshot_apply.local_actor_count = counts.local_actor_count;
        state.world_snapshot_apply.matched_actor_count = counts.matched_actor_count;
        state.world_snapshot_apply.created_actor_count = counts.created_actor_count;
        state.world_snapshot_apply.created_actor_total_count += counts.created_actor_count;
        state.world_snapshot_apply.transform_write_count = counts.transform_write_count;
        state.world_snapshot_apply.presentation_write_count = counts.presentation_write_count;
        state.world_snapshot_apply.health_write_count = counts.health_write_count;
        state.world_snapshot_apply.dead_actor_count = counts.dead_actor_count;
        state.world_snapshot_apply.parked_actor_count = counts.parked_actor_count;
        state.world_snapshot_apply.removed_actor_count = counts.removed_actor_count;
        state.world_snapshot_apply.removed_actor_total_count +=
            counts.removed_actor_count;
        state.world_snapshot_apply.failed_remove_actor_count = counts.failed_remove_actor_count;
        state.world_snapshot_apply.failed_remove_actor_total_count +=
            counts.failed_remove_actor_count;
        state.world_snapshot_apply.actor_bindings = counts.actor_bindings;
    });
}

void ClearWorldSnapshotApplyState(std::uint64_t now_ms, const char* reason) {
    multiplayer::UpdateRuntimeState([&](multiplayer::RuntimeState& state) {
        state.world_snapshot_apply = multiplayer::WorldSnapshotApplyRuntimeInfo{};
        state.world_snapshot_apply.applied_ms = now_ms;
    });
    Log(
        "world_snapshot: cleared apply state. reason=" +
        std::string(reason != nullptr ? reason : "unknown"));
}
