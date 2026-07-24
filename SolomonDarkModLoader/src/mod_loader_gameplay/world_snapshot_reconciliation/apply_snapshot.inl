void ApplyReplicatedWorldSnapshotIfActive(uintptr_t /*gameplay_address*/, std::uint64_t now_ms) {
    MaybeQueueRunLifecycleForRemoteAuthority(now_ms);

    const auto runtime_state = multiplayer::SnapshotRuntimeState();
    RefreshLatestRunEnemySnapshotCache(runtime_state.world_snapshot, now_ms);
    ApplyHostAuthoritativeRunEntryFormationIfNeeded(runtime_state, now_ms);

    const auto local_transport_participant_id = multiplayer::GetLocalTransportParticipantId();
    SDModSceneState scene_state;
    const bool have_current_scene =
        TryGetSceneState(&scene_state) &&
        scene_state.valid;
    const bool can_apply_latest_targets =
        have_current_scene &&
        runtime_state.world_snapshot.valid &&
        runtime_state.world_snapshot.authority_participant_id != local_transport_participant_id &&
        IsReplicatedWorldSnapshotSceneCurrent(scene_state, runtime_state.world_snapshot) &&
        !IsReplicatedWorldSnapshotSceneChurnInFlight(now_ms);
    const auto latest_target_write_count =
        can_apply_latest_targets
            ? ApplyLatestRunEnemyTargetsFromRuntimeSnapshot(runtime_state.world_snapshot, now_ms)
            : 0;

    multiplayer::WorldSnapshotRuntimeInfo snapshot;
    const bool have_snapshot = multiplayer::TrySampleWorldSnapshot(
        runtime_state,
        now_ms,
        multiplayer::RecommendedWorldSnapshotInterpolationDelayMs(
            runtime_state),
        &snapshot);
    if (!have_snapshot || !snapshot.valid || now_ms < snapshot.received_ms) {
        if (runtime_state.world_snapshot_apply.valid) {
            ClearWorldSnapshotApplyState(
                now_ms,
                !have_snapshot
                    ? "sample_unavailable"
                    : (!snapshot.valid ? "sample_invalid" : "sample_clock_invalid"));
        }
        return;
    }
    if (local_transport_participant_id != 0 &&
        snapshot.authority_participant_id == local_transport_participant_id) {
        if (runtime_state.world_snapshot_apply.valid) {
            ClearWorldSnapshotApplyState(now_ms, "local_authority");
        }
        return;
    }

    const auto sampled_snapshot_age_ms = now_ms - snapshot.received_ms;
    bool authority_participant_present = false;
    for (const auto& participant : runtime_state.participants) {
        if (participant.participant_id == snapshot.authority_participant_id &&
            multiplayer::IsRemoteParticipant(participant)) {
            authority_participant_present = true;
            break;
        }
    }
    const bool holding_stale_snapshot =
        sampled_snapshot_age_ms > kWorldSnapshotApplyStaleMs &&
        runtime_state.session_status == multiplayer::SessionStatus::Ready &&
        authority_participant_present &&
        runtime_state.world_snapshot.valid &&
        IsSameWorldSnapshotTimeline(snapshot, runtime_state.world_snapshot) &&
        have_current_scene &&
        IsReplicatedWorldSnapshotSceneCurrent(
            scene_state,
            runtime_state.world_snapshot) &&
        !IsReplicatedWorldSnapshotSceneChurnInFlight(now_ms);
    if (sampled_snapshot_age_ms > kWorldSnapshotApplyStaleMs &&
        !holding_stale_snapshot) {
        if (runtime_state.world_snapshot_apply.valid) {
            ClearWorldSnapshotApplyState(now_ms, "stale_without_live_authority");
        }
        return;
    }
    if (holding_stale_snapshot) {
        snapshot = runtime_state.world_snapshot;
        if (!runtime_state.world_snapshot_apply.holding_stale_snapshot) {
            Log(
                "world_snapshot: holding last authoritative actor state during "
                "transient snapshot stall. sequence=" +
                std::to_string(snapshot.sequence) +
                " scene_epoch=" + std::to_string(snapshot.scene_epoch) +
                " age_ms=" + std::to_string(sampled_snapshot_age_ms));
        }
    } else if (runtime_state.world_snapshot_apply.holding_stale_snapshot) {
        Log(
            "world_snapshot: fresh authoritative actor state resumed. sequence=" +
            std::to_string(snapshot.sequence) +
            " scene_epoch=" + std::to_string(snapshot.scene_epoch));
    }
    const auto used_latest_presentation =
        OverlayLatestWorldSnapshotPresentation(&snapshot, runtime_state.world_snapshot, now_ms);
    const auto& presentation_snapshot =
        used_latest_presentation ? runtime_state.world_snapshot : snapshot;
    if (snapshot.scene_intent.kind != multiplayer::ParticipantSceneIntentKind::SharedHub &&
        snapshot.scene_intent.kind != multiplayer::ParticipantSceneIntentKind::Run) {
        if (runtime_state.world_snapshot_apply.valid) {
            ClearWorldSnapshotApplyState(now_ms, "unsupported_scene_kind");
        }
        return;
    }

    if (!have_current_scene ||
        !IsReplicatedWorldSnapshotSceneCurrent(scene_state, snapshot)) {
        return;
    }
    if (IsReplicatedWorldSnapshotSceneChurnInFlight(now_ms)) {
        return;
    }

    const bool allow_structural_reconciliation = !holding_stale_snapshot;
    if (allow_structural_reconciliation) {
        MaybeQueueRunLifecycleForAuthoritativeSnapshot(snapshot, now_ms);
    }
    if (snapshot.scene_intent.kind == multiplayer::ParticipantSceneIntentKind::SharedHub &&
        g_replicated_created_hub_scene_epoch != snapshot.scene_epoch) {
        if (g_replicated_created_hub_scene_epoch != 0 &&
            !g_replicated_created_hub_actors.empty()) {
            Log(
                "world_snapshot: retained replicated hub actors across authority epoch change. old_epoch=" +
                std::to_string(g_replicated_created_hub_scene_epoch) +
                " new_epoch=" + std::to_string(snapshot.scene_epoch) +
                " count=" + std::to_string(g_replicated_created_hub_actors.size()));
        }
        g_replicated_created_hub_scene_epoch = snapshot.scene_epoch;
    }
    if (snapshot.scene_intent.kind == multiplayer::ParticipantSceneIntentKind::Run &&
        g_replicated_run_actor_scene_epoch != snapshot.scene_epoch) {
        ClearReplicatedRunActorBindings();
        g_replicated_run_actor_scene_epoch = snapshot.scene_epoch;
    }

    auto local_bindings = BuildLocalReplicatedWorldActorBindings(snapshot.scene_intent.kind);
    WorldSnapshotApplyCounts counts;
    counts.local_actor_count = static_cast<std::uint32_t>(local_bindings.size());
    if (allow_structural_reconciliation) {
        MaybeCatchUpRunEnemyPoolForAuthoritativeSnapshot(snapshot, local_bindings);
    }

    std::unordered_set<std::uint64_t> authoritative_ids;
    authoritative_ids.reserve(snapshot.actors.size());
    std::size_t authoritative_student_count = 0;
    const bool snapshot_may_be_complete =
        snapshot.scene_intent.kind == multiplayer::ParticipantSceneIntentKind::SharedHub ||
        snapshot.scene_intent.kind == multiplayer::ParticipantSceneIntentKind::Run;
    const bool can_mutate_shared_hub_actors = CanMutateReplicatedSharedHubActors(snapshot, now_ms);
    for (const auto& authoritative_actor : snapshot.actors) {
        if (!ShouldUseAuthoritativeWorldActorForScene(authoritative_actor, snapshot.scene_intent.kind)) {
            continue;
        }
        authoritative_ids.insert(authoritative_actor.network_actor_id);
        if (snapshot.scene_intent.kind ==
                multiplayer::ParticipantSceneIntentKind::SharedHub &&
            authoritative_actor.native_type_id == 0x138A) {
            authoritative_student_count += 1;
        }
    }

    std::unordered_map<std::uint64_t, std::size_t> local_by_network_id;
    local_by_network_id.reserve(local_bindings.size());
    for (std::size_t index = 0; index < local_bindings.size(); ++index) {
        if (local_bindings[index].network_actor_id != 0) {
            local_by_network_id.emplace(local_bindings[index].network_actor_id, index);
        }
    }

    for (const auto& authoritative_actor : snapshot.actors) {
        if (!ShouldUseAuthoritativeWorldActorForScene(authoritative_actor, snapshot.scene_intent.kind)) {
            continue;
        }
        auto local_it = local_by_network_id.find(authoritative_actor.network_actor_id);
        if (local_it == local_by_network_id.end() &&
            allow_structural_reconciliation &&
            snapshot.scene_intent.kind == multiplayer::ParticipantSceneIntentKind::SharedHub) {
            std::size_t binding_index = 0;
            if (TryBindAuthoritativeSharedHubActorToLocalPool(authoritative_actor, &local_bindings, &binding_index)) {
                local_by_network_id.emplace(authoritative_actor.network_actor_id, binding_index);
                local_it = local_by_network_id.find(authoritative_actor.network_actor_id);
            }
        }
        if (local_it == local_by_network_id.end() &&
            allow_structural_reconciliation &&
            snapshot.scene_intent.kind == multiplayer::ParticipantSceneIntentKind::Run &&
            authoritative_actor.lifecycle_owned &&
            !IsAuthoritativeRunTrackedEnemyDeadSnapshot(authoritative_actor)) {
            std::size_t binding_index = 0;
            if (TryBindAuthoritativeRunActorToLocalPool(
                    authoritative_actor,
                    authoritative_ids,
                    &local_bindings,
                    now_ms,
                    &binding_index)) {
                local_by_network_id.emplace(authoritative_actor.network_actor_id, binding_index);
                local_it = local_by_network_id.find(authoritative_actor.network_actor_id);
            } else {
                (void)QueueReplicatedManualRunEnemyMaterialization(authoritative_actor, now_ms);
            }
        }
        if (local_it == local_by_network_id.end() &&
            allow_structural_reconciliation &&
            snapshot.scene_intent.kind == multiplayer::ParticipantSceneIntentKind::Run &&
            authoritative_actor.lifecycle_owned &&
            IsAuthoritativeRunTrackedEnemyDeadSnapshot(authoritative_actor)) {
            std::size_t binding_index = 0;
            if (TryBindAuthoritativeDeadRunEnemyToLocalPool(
                    authoritative_actor,
                    authoritative_ids,
                    &local_bindings,
                    &binding_index)) {
                local_by_network_id.emplace(authoritative_actor.network_actor_id, binding_index);
                local_it = local_by_network_id.find(authoritative_actor.network_actor_id);
            }
        }
        if (local_it == local_by_network_id.end()) {
            uintptr_t created_actor_address = 0;
            if (allow_structural_reconciliation &&
                snapshot.scene_intent.kind == multiplayer::ParticipantSceneIntentKind::SharedHub &&
                snapshot_may_be_complete &&
                can_mutate_shared_hub_actors &&
                IsReplicatedSharedHubLifecycleOwnedActorType(
                    authoritative_actor.native_type_id)) {
                bool newly_created = false;
                if (!TryFindCreatedReplicatedSharedHubActor(authoritative_actor, &created_actor_address) &&
                    TryCreateReplicatedSharedHubActor(
                        scene_state.world_address,
                        authoritative_actor,
                        &created_actor_address)) {
                    g_replicated_created_hub_actors[authoritative_actor.network_actor_id] = created_actor_address;
                    BindReplicatedSharedHubActor(authoritative_actor.network_actor_id, created_actor_address);
                    newly_created = true;
                }
                if (created_actor_address == 0) {
                    continue;
                }
                counts.matched_actor_count += 1;
                if (newly_created) {
                    counts.created_actor_count += 1;
                }
                if (ApplyReplicatedWorldActorTransform(
                        created_actor_address,
                        authoritative_actor.native_type_id,
                        authoritative_actor,
                        true)) {
                    counts.transform_write_count += 1;
                }
                if (ApplyReplicatedWorldActorPresentation(
                        created_actor_address,
                        authoritative_actor.native_type_id,
                        authoritative_actor)) {
                    counts.presentation_write_count += 1;
                }
                RecordWorldSnapshotBinding(
                    &counts,
                    authoritative_actor,
                    created_actor_address,
                    true,
                    false);
            }
            continue;
        }

        auto& binding = local_bindings[local_it->second];
        binding.matched = true;
        counts.matched_actor_count += 1;
        if (authoritative_actor.dead) {
            counts.dead_actor_count += 1;
        }
        // Sample client-owned native damage and its post-hit target position
        // before applying the authoritative transform. ApplyReplicatedRunEnemyHealth
        // queues a validated damage claim; the host then rebroadcasts the
        // accepted position in its next world snapshot.
        if (snapshot.scene_intent.kind == multiplayer::ParticipantSceneIntentKind::Run &&
            authoritative_actor.tracked_enemy &&
            ApplyReplicatedRunEnemyHealth(binding.actor.actor_address, authoritative_actor, now_ms)) {
            counts.health_write_count += 1;
        }
        if (ApplyReplicatedWorldActorTransform(
                binding.actor.actor_address,
                binding.actor.object_type_id,
                authoritative_actor,
                false)) {
            counts.transform_write_count += 1;
        }
        if (snapshot.scene_intent.kind == multiplayer::ParticipantSceneIntentKind::Run &&
            authoritative_actor.tracked_enemy) {
            (void)ApplyReplicatedRunEnemyTransientStatus(
                binding.actor.actor_address,
                authoritative_actor);
        }
        if (ApplyReplicatedWorldActorPresentation(
                binding.actor.actor_address,
                binding.actor.object_type_id,
                authoritative_actor)) {
            counts.presentation_write_count += 1;
        }
        if (snapshot.scene_intent.kind == multiplayer::ParticipantSceneIntentKind::Run &&
            authoritative_actor.tracked_enemy &&
            ApplyReplicatedRunEnemyTarget(
                binding.actor.actor_address,
                authoritative_actor,
                snapshot.scene_intent)) {
            counts.presentation_write_count += 1;
        }
        RecordWorldSnapshotBinding(&counts, authoritative_actor, binding.actor.actor_address, true, false);
    }

    if (allow_structural_reconciliation &&
        snapshot_may_be_complete &&
        (snapshot.scene_intent.kind != multiplayer::ParticipantSceneIntentKind::SharedHub ||
         can_mutate_shared_hub_actors)) {
        std::size_t local_student_count = 0;
        if (snapshot.scene_intent.kind ==
            multiplayer::ParticipantSceneIntentKind::SharedHub) {
            for (const auto& binding : local_bindings) {
                if (binding.actor.object_type_id == 0x138A) {
                    local_student_count += 1;
                }
            }
        }
        std::size_t student_retire_budget =
            local_student_count > authoritative_student_count
                ? local_student_count - authoritative_student_count
                : 0;

        for (auto& binding : local_bindings) {
            if (binding.matched) {
                continue;
            }
            if (snapshot.scene_intent.kind == multiplayer::ParticipantSceneIntentKind::Run) {
                const auto removed_network_actor_id = binding.network_actor_id;
                if (multiplayer::IsReplicatedRunPlayerCreatedActorType(
                        binding.actor.object_type_id)) {
                    // Summons are owned by the stock spell implementation on
                    // every machine. Reconciliation may align and bind them,
                    // but must never unregister one: doing so bypasses the
                    // summon's native teardown and can leave its AI/effect
                    // owners with a dangling actor pointer. Once authority no
                    // longer publishes the summon, release only our network
                    // identity and let the matching stock lifetime finish.
                    if (removed_network_actor_id != 0 &&
                        authoritative_ids.find(removed_network_actor_id) == authoritative_ids.end()) {
                        UnbindReplicatedRunActor(
                            removed_network_actor_id,
                            binding.actor.actor_address);
                        binding.network_actor_id = 0;
                    }
                    RecordWorldSnapshotBinding(&counts, binding, false, false, false);
                    continue;
                }
                if (removed_network_actor_id != 0 &&
                    authoritative_ids.find(removed_network_actor_id) == authoritative_ids.end() &&
                    IsReplicatedRunEnemyDeathPending(removed_network_actor_id, now_ms)) {
                    RecordWorldSnapshotBinding(&counts, binding, false, false, false);
                    continue;
                }
                if (removed_network_actor_id != 0 &&
                    authoritative_ids.find(removed_network_actor_id) == authoritative_ids.end() &&
                    binding.actor.tracked_enemy &&
                    IsRunEnemyNativeDeathHandled(binding.actor.actor_address) &&
                    TryBeginReplicatedRunEnemyDeathHold(removed_network_actor_id, now_ms)) {
                    RecordWorldSnapshotBinding(&counts, binding, false, false, false);
                    Log(
                        "world_snapshot: holding local replicated run enemy death presentation. actor=" +
                        HexString(binding.actor.actor_address) +
                        " type=" + HexString(static_cast<uintptr_t>(binding.actor.object_type_id)) +
                        " network_actor_id=" + std::to_string(removed_network_actor_id));
                    continue;
                }
                DWORD exception_code = 0;
                const auto removed_actor_address = binding.actor.actor_address;
                if (RemoveReplicatedRunActor(binding, &exception_code)) {
                    counts.removed_actor_count += 1;
                    if (removed_network_actor_id != 0) {
                        auto removed_binding = binding;
                        removed_binding.network_actor_id = removed_network_actor_id;
                        RecordWorldSnapshotBinding(&counts, removed_binding, false, false, true);
                        UnbindReplicatedRunActor(removed_network_actor_id, removed_actor_address);
                        binding.network_actor_id = 0;
                    }
                    Log(
                        "world_snapshot: unregistered extra run actor. actor=" +
                        HexString(removed_actor_address) +
                        " type=" + HexString(static_cast<uintptr_t>(binding.actor.object_type_id)) +
                        " network_actor_id=" + std::to_string(removed_network_actor_id));
                } else {
                    counts.failed_remove_actor_count += 1;
                    Log(
                        "world_snapshot: failed to unregister extra run actor. actor=" +
                        HexString(removed_actor_address) +
                        " type=" + HexString(static_cast<uintptr_t>(binding.actor.object_type_id)) +
                        " network_actor_id=" + std::to_string(removed_network_actor_id) +
                        " seh=" + HexString(exception_code));
                }
                continue;
            }

            if (snapshot.scene_intent.kind != multiplayer::ParticipantSceneIntentKind::SharedHub ||
                !IsReplicatedSharedHubFactoryActorType(binding.actor.object_type_id)) {
                continue;
            }

            if (binding.actor.object_type_id == 0x138A) {
                const bool stale_authority_student =
                    binding.network_actor_id != 0 &&
                    authoritative_ids.find(binding.network_actor_id) ==
                        authoritative_ids.end();
                if (student_retire_budget == 0) {
                    if (stale_authority_student) {
                        RecordWorldSnapshotBinding(
                            &counts,
                            binding,
                            false,
                            false,
                            false);
                        UnbindReplicatedSharedHubActor(
                            binding.network_actor_id,
                            binding.actor.actor_address);
                        binding.network_actor_id = 0;
                    }
                    continue;
                }

                DWORD exception_code = 0;
                const auto retired_network_actor_id =
                    binding.network_actor_id;
                const auto retired_actor_address =
                    binding.actor.actor_address;
                if (TryRequestReplicatedHubStudentRetirement(
                        binding,
                        &exception_code)) {
                    counts.removed_actor_count += 1;
                    if (retired_network_actor_id != 0) {
                        RecordWorldSnapshotBinding(
                            &counts,
                            binding,
                            false,
                            false,
                            true);
                        UnbindReplicatedSharedHubActor(
                            retired_network_actor_id,
                            retired_actor_address);
                        binding.network_actor_id = 0;
                    }
                    student_retire_budget -= 1;
                    Log(
                        "world_snapshot: requested stock Student retirement. actor=" +
                        HexString(retired_actor_address) +
                        " network_actor_id=" +
                        std::to_string(retired_network_actor_id) +
                        " reason=" +
                        (stale_authority_student
                             ? "surplus_retired_authority"
                             : "surplus_local"));
                } else {
                    counts.failed_remove_actor_count += 1;
                    Log(
                        "world_snapshot: failed to request stock Student retirement. actor=" +
                        HexString(retired_actor_address) +
                        " network_actor_id=" +
                        std::to_string(retired_network_actor_id) +
                        " seh=" + HexString(exception_code));
                }
                continue;
            }

            if (authoritative_ids.find(binding.network_actor_id) !=
                authoritative_ids.end()) {
                continue;
            }

            if (!IsReplicatedSharedHubLifecycleOwnedActorType(
                    binding.actor.object_type_id)) {
                continue;
            }

            DWORD exception_code = 0;
            if (RemoveReplicatedSharedHubActor(binding, &exception_code)) {
                counts.removed_actor_count += 1;
                RecordWorldSnapshotBinding(&counts, binding, false, false, true);
                UnbindReplicatedSharedHubActor(binding.network_actor_id, binding.actor.actor_address);
                binding.network_actor_id = 0;
            } else {
                counts.failed_remove_actor_count += 1;
                Log(
                    "world_snapshot: failed to unregister extra hub actor. actor=" +
                    HexString(binding.actor.actor_address) +
                    " type=0x" + HexString(static_cast<uintptr_t>(binding.actor.object_type_id)) +
                    " network_actor_id=" + std::to_string(binding.network_actor_id) +
                    " seh=" + HexString(exception_code));
            }
        }
    }

    counts.presentation_write_count += latest_target_write_count;

    PublishWorldSnapshotApplyCounts(
        snapshot,
        presentation_snapshot,
        counts,
        now_ms,
        holding_stale_snapshot,
        holding_stale_snapshot
            ? sampled_snapshot_age_ms
            : now_ms - snapshot.received_ms);
}
