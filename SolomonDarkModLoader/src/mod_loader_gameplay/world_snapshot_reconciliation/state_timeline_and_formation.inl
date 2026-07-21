
constexpr std::uint64_t kWorldSnapshotApplyStaleMs = 1200;
constexpr std::uint64_t kWorldSnapshotInterpolationDelayMs = 150;
constexpr std::uint64_t kWorldSnapshotRunLifecycleRequestIntervalMs = 1000;
constexpr std::uint64_t kReplicatedRunEnemyRemoteDeathHoldMs = 1200;
constexpr std::uint64_t kHubAnimationDrivePhaseUnitsPerSecond = 150;
constexpr std::uint64_t kRunEntryAuthoritySnapshotStaleMs = 3000;
constexpr float kWorldSnapshotSettleDistance = 0.5f;
constexpr float kReplicatedRunEnemySoftCorrectionFactor = 0.2f;
constexpr float kReplicatedRunEnemyHardSnapDistance = 192.0f;
constexpr float kReplicatedRunEnemyDeathHpEpsilon = 0.05f;
constexpr float kReplicatedRunEnemyDamageObservationEpsilon = 0.0001f;
// Keep client-authored native hit reactions when they remain close to the
// host snapshot.  Larger presentation drift must not invalidate otherwise
// legitimate damage; fall back to the authoritative position instead.
constexpr float kLocalEnemyDamageClaimPositionPreserveDistance = 96.0f;
constexpr float kRunEntryFormationSpacing = 64.0f;
constexpr float kRunEntryFormationNavSnapMaxDistance = 48.0f;
constexpr float kRunEntryFormationNavSnapMaxAuthorityDistance = 96.0f;
constexpr float kRunEntryFormationReapplyDistance = 32.0f;
constexpr float kRunEntryFormationAuthoritySettleDistance = 8.0f;
constexpr std::uint64_t kRunEntryFormationBootstrapMs = 5000;
constexpr std::uint64_t kRunEntryFormationReapplyIntervalMs = 100;
constexpr std::uint64_t kRunEntryFormationAuthorityStableMs = 500;
constexpr std::uint64_t kRunEntryFormationMinimumSettleMs = 2000;
constexpr std::uint32_t kSolomonDigNativeTypeId = 0x1391;
constexpr std::uint32_t kSolomonRunStaticNativeTypeId = 0x1392;

std::unordered_map<std::uint64_t, uintptr_t> g_replicated_created_hub_actors;
std::unordered_map<std::uint64_t, uintptr_t> g_replicated_hub_bindings_by_network_id;
std::unordered_map<uintptr_t, std::uint64_t> g_replicated_hub_network_ids_by_actor;
std::uint32_t g_replicated_created_hub_scene_epoch = 0;
std::unordered_map<std::uint64_t, uintptr_t> g_replicated_run_bindings_by_network_id;
std::unordered_map<uintptr_t, std::uint64_t> g_replicated_run_network_ids_by_actor;
std::unordered_map<std::uint64_t, multiplayer::WorldActorSnapshot>
    g_latest_run_enemy_snapshots_by_network_id;
multiplayer::ParticipantSceneIntent g_latest_run_enemy_snapshot_scene_intent;
std::uint64_t g_latest_run_enemy_snapshot_authority_participant_id = 0;
std::uint64_t g_latest_run_enemy_snapshot_received_ms = 0;
std::uint32_t g_latest_run_enemy_snapshot_sequence = 0;
std::uint32_t g_latest_run_enemy_snapshot_scene_epoch = 0;
std::uint32_t g_latest_run_enemy_snapshot_run_nonce = 0;
bool g_latest_run_enemy_snapshot_cache_valid = false;
std::unordered_map<std::uint64_t, std::uint64_t> g_replicated_run_pending_enemy_death_until_ms;
std::unordered_set<std::uint64_t> g_replicated_run_enemy_death_hold_started_ids;
std::unordered_map<std::uint64_t, std::uint64_t> g_replicated_run_pending_enemy_materialization_until_ms;
std::uint32_t g_replicated_run_actor_scene_epoch = 0;
uintptr_t g_run_entry_formation_world_address = 0;
std::uint64_t g_run_entry_formation_authority_participant_id = 0;
std::uint32_t g_run_entry_formation_run_nonce = 0;
std::uint64_t g_run_entry_formation_started_ms = 0;
std::uint64_t g_run_entry_formation_last_apply_ms = 0;
float g_run_entry_formation_authority_x = 0.0f;
float g_run_entry_formation_authority_y = 0.0f;
std::uint64_t g_run_entry_formation_authority_stable_since_ms = 0;
bool g_run_entry_formation_have_authority_sample = false;
bool g_run_entry_formation_settled = false;

void ClearLatestRunEnemySnapshotCache() {
    g_latest_run_enemy_snapshots_by_network_id.clear();
    g_latest_run_enemy_snapshot_scene_intent = {};
    g_latest_run_enemy_snapshot_authority_participant_id = 0;
    g_latest_run_enemy_snapshot_received_ms = 0;
    g_latest_run_enemy_snapshot_sequence = 0;
    g_latest_run_enemy_snapshot_scene_epoch = 0;
    g_latest_run_enemy_snapshot_run_nonce = 0;
    g_latest_run_enemy_snapshot_cache_valid = false;
}

struct ReplicatedWorldActorLocalBinding {
    SDModSceneActorState actor;
    std::uint64_t network_actor_id = 0;
    bool matched = false;
    bool parked = false;
};

struct WorldSnapshotApplyCounts {
    std::uint32_t local_actor_count = 0;
    std::uint32_t matched_actor_count = 0;
    std::uint32_t created_actor_count = 0;
    std::uint32_t transform_write_count = 0;
    std::uint32_t presentation_write_count = 0;
    std::uint32_t health_write_count = 0;
    std::uint32_t dead_actor_count = 0;
    std::uint32_t parked_actor_count = 0;
    std::uint32_t removed_actor_count = 0;
    std::uint32_t failed_remove_actor_count = 0;
    std::vector<multiplayer::WorldSnapshotActorBindingRuntimeInfo> actor_bindings;
};

multiplayer::ParticipantSceneIntentKind SceneIntentKindFromSceneState(const SDModSceneState& scene_state) {
    if (scene_state.kind == "arena") {
        return multiplayer::ParticipantSceneIntentKind::Run;
    }
    if (scene_state.kind == "hub") {
        return multiplayer::ParticipantSceneIntentKind::SharedHub;
    }
    return multiplayer::ParticipantSceneIntentKind::PrivateRegion;
}

bool IsReplicatedWorldSnapshotSceneCurrent(
    const SDModSceneState& scene_state,
    const multiplayer::WorldSnapshotRuntimeInfo& snapshot) {
    return snapshot.valid &&
           snapshot.scene_intent.kind == SceneIntentKindFromSceneState(scene_state);
}

bool IsSameWorldSnapshotTimeline(
    const multiplayer::WorldSnapshotRuntimeInfo& left,
    const multiplayer::WorldSnapshotRuntimeInfo& right) {
    return left.valid &&
           right.valid &&
           left.authority_participant_id == right.authority_participant_id &&
           left.scene_epoch == right.scene_epoch &&
           left.run_nonce == right.run_nonce &&
           multiplayer::SameParticipantSceneIntent(left.scene_intent, right.scene_intent);
}

void CopyWorldActorPresentationState(
    multiplayer::WorldActorSnapshot* target,
    const multiplayer::WorldActorSnapshot& source,
    bool copy_locomotion_floats = true) {
    if (target == nullptr ||
        target->network_actor_id != source.network_actor_id ||
        target->native_type_id != source.native_type_id) {
        return;
    }

    target->anim_drive_state = source.anim_drive_state;
    target->presentation_flags = source.presentation_flags;
    target->anim_drive_state_word = source.anim_drive_state_word;
    if (copy_locomotion_floats) {
        target->walk_cycle_primary = source.walk_cycle_primary;
        target->walk_cycle_secondary = source.walk_cycle_secondary;
    }
    target->render_variant_primary = source.render_variant_primary;
    target->render_variant_secondary = source.render_variant_secondary;
    target->render_weapon_type = source.render_weapon_type;
    target->render_selection_byte = source.render_selection_byte;
    target->render_variant_tertiary = source.render_variant_tertiary;
    target->student_visual_state = source.student_visual_state;
    target->student_book_palette_count = source.student_book_palette_count;
    target->student_book_palette = source.student_book_palette;
    target->named_hub_npc = source.named_hub_npc;
}

void CopyWorldActorTransientStatusState(
    multiplayer::WorldActorSnapshot* target,
    const multiplayer::WorldActorSnapshot& source) {
    if (target == nullptr ||
        target->network_actor_id != source.network_actor_id ||
        target->native_type_id != source.native_type_id) {
        return;
    }

    target->status_flags = source.status_flags;
    target->turn_undead_duration_ticks =
        source.turn_undead_duration_ticks;
    target->turn_undead_flee_heading =
        source.turn_undead_flee_heading;
    target->turn_undead_activation_scalar =
        source.turn_undead_activation_scalar;
}

bool IsReplicatedHubPhaseAdvancingActorSnapshot(
    const multiplayer::WorldActorSnapshot& actor) {
    switch (actor.native_type_id) {
    case 0x138B:
    case 0x138C:
    case 0x138D:
    case 0x138F:
        return true;
    default:
        return false;
    }
}

std::uint32_t AdvanceHubAnimationDrivePhase(
    std::uint32_t drive_word,
    std::uint64_t age_ms) {
    const std::uint64_t phase_delta =
        (age_ms * kHubAnimationDrivePhaseUnitsPerSecond + 500) / 1000;
    const std::uint32_t phase =
        (drive_word + static_cast<std::uint32_t>(phase_delta & 0xFFFFu)) & 0xFFFFu;
    return (drive_word & 0xFFFF0000u) | phase;
}

bool OverlayLatestWorldSnapshotPresentation(
    multiplayer::WorldSnapshotRuntimeInfo* sampled_snapshot,
    const multiplayer::WorldSnapshotRuntimeInfo& latest_snapshot,
    std::uint64_t now_ms) {
    if (sampled_snapshot == nullptr ||
        !sampled_snapshot->valid ||
        !latest_snapshot.valid ||
        latest_snapshot.actors.empty() ||
        now_ms < latest_snapshot.received_ms ||
        now_ms - latest_snapshot.received_ms > kWorldSnapshotApplyStaleMs ||
        !IsSameWorldSnapshotTimeline(*sampled_snapshot, latest_snapshot)) {
        return false;
    }

    std::unordered_map<std::uint64_t, const multiplayer::WorldActorSnapshot*> latest_by_id;
    latest_by_id.reserve(latest_snapshot.actors.size());
    for (const auto& actor : latest_snapshot.actors) {
        if (actor.network_actor_id != 0) {
            latest_by_id.emplace(actor.network_actor_id, &actor);
        }
    }

    for (auto& actor : sampled_snapshot->actors) {
        const auto it = latest_by_id.find(actor.network_actor_id);
        if (it == latest_by_id.end() || it->second == nullptr) {
            continue;
        }
        CopyWorldActorPresentationState(
            &actor,
            *it->second,
            sampled_snapshot->scene_intent.kind != multiplayer::ParticipantSceneIntentKind::Run);
        CopyWorldActorTransientStatusState(&actor, *it->second);
        if (actor.player_created && it->second->player_created) {
            // Player-created autonomous actors continue simulating locally.
            // Interpolating an already-moving remote golem 150 ms behind the
            // authority lets the two AI paths visibly diverge, so consume the
            // freshest authoritative transform for this small explicit class.
            actor.position_x = it->second->position_x;
            actor.position_y = it->second->position_y;
            actor.heading = it->second->heading;
            actor.hp = it->second->hp;
            actor.max_hp = it->second->max_hp;
        }
        if ((actor.presentation_flags & multiplayer::WorldActorPresentationFlagAnimationDriveWord) != 0 &&
            IsReplicatedHubPhaseAdvancingActorSnapshot(actor)) {
            actor.anim_drive_state_word = AdvanceHubAnimationDrivePhase(
                actor.anim_drive_state_word,
                now_ms - latest_snapshot.received_ms);
            actor.anim_drive_state = static_cast<std::uint8_t>(actor.anim_drive_state_word & 0xFFu);
        }
    }
    return true;
}

bool IsReplicatedWorldSnapshotSceneChurnInFlight(std::uint64_t now_ms) {
    const auto scene_churn_until =
        g_gameplay_keyboard_injection.scene_churn_not_before_ms.load(std::memory_order_acquire);
    return now_ms < scene_churn_until;
}

bool HasPendingParticipantWorldMutation(std::uint64_t now_ms) {
    const auto participant_sync_not_before =
        g_gameplay_keyboard_injection.wizard_bot_sync_not_before_ms.load(std::memory_order_acquire);
    if (now_ms < participant_sync_not_before) {
        return true;
    }

    std::lock_guard<std::mutex> lock(g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    return !g_gameplay_keyboard_injection.pending_participant_sync_requests.empty() ||
           !g_gameplay_keyboard_injection.pending_participant_destroy_requests.empty();
}

bool RemoteNativeParticipantsSettledForScene(
    const multiplayer::ParticipantSceneIntent& scene_intent,
    std::uint64_t now_ms) {
    const auto runtime_state = multiplayer::SnapshotRuntimeState();
    for (const auto& participant : runtime_state.participants) {
        if (!multiplayer::IsRemoteParticipant(participant) ||
            participant.controller_kind != multiplayer::ParticipantControllerKind::Native ||
            !participant.transport_connected ||
            !participant.runtime.valid ||
            !participant.runtime.transform_valid ||
            !multiplayer::SameParticipantSceneIntent(participant.runtime.scene_intent, scene_intent)) {
            continue;
        }

        if (participant.last_packet_ms != 0 && now_ms > participant.last_packet_ms + 3000) {
            continue;
        }

        SDModParticipantGameplayState gameplay_state;
        if (!TryGetParticipantGameplayState(participant.participant_id, &gameplay_state) ||
            !gameplay_state.available ||
            !gameplay_state.entity_materialized ||
            gameplay_state.actor_address == 0 ||
            gameplay_state.world_address == 0 ||
            !multiplayer::SameParticipantSceneIntent(gameplay_state.scene_intent, scene_intent)) {
            return false;
        }
    }
    return true;
}

bool CanMutateReplicatedSharedHubActors(
    const multiplayer::WorldSnapshotRuntimeInfo& snapshot,
    std::uint64_t now_ms) {
    if (snapshot.scene_intent.kind != multiplayer::ParticipantSceneIntentKind::SharedHub) {
        return true;
    }

    return !HasPendingParticipantWorldMutation(now_ms) &&
           RemoteNativeParticipantsSettledForScene(snapshot.scene_intent, now_ms);
}

void ResetHostAuthoritativeRunEntryFormation() {
    g_run_entry_formation_world_address = 0;
    g_run_entry_formation_authority_participant_id = 0;
    g_run_entry_formation_run_nonce = 0;
    g_run_entry_formation_started_ms = 0;
    g_run_entry_formation_last_apply_ms = 0;
    g_run_entry_formation_authority_x = 0.0f;
    g_run_entry_formation_authority_y = 0.0f;
    g_run_entry_formation_authority_stable_since_ms = 0;
    g_run_entry_formation_have_authority_sample = false;
    g_run_entry_formation_settled = false;
}

bool IsFreshRunEntryAuthoritySnapshot(
    const multiplayer::WorldSnapshotRuntimeInfo& snapshot,
    std::uint64_t now_ms) {
    return snapshot.valid &&
           snapshot.scene_intent.kind == multiplayer::ParticipantSceneIntentKind::Run &&
           snapshot.authority_participant_id != 0 &&
           now_ms >= snapshot.received_ms &&
           now_ms - snapshot.received_ms <= kRunEntryAuthoritySnapshotStaleMs;
}

const multiplayer::ParticipantInfo* FindRunEntryAuthorityParticipant(
    const multiplayer::RuntimeState& runtime_state,
    std::uint64_t now_ms) {
    if (!IsFreshRunEntryAuthoritySnapshot(runtime_state.world_snapshot, now_ms)) {
        return nullptr;
    }

    const auto* authority = multiplayer::FindParticipant(
        runtime_state,
        runtime_state.world_snapshot.authority_participant_id);
    if (authority == nullptr ||
        !multiplayer::IsRemoteParticipant(*authority) ||
        authority->controller_kind != multiplayer::ParticipantControllerKind::Native ||
        !authority->transport_connected ||
        !authority->runtime.valid ||
        !authority->runtime.transform_valid ||
        !authority->runtime.in_run ||
        authority->runtime.scene_intent.kind != multiplayer::ParticipantSceneIntentKind::Run ||
        !std::isfinite(authority->runtime.position_x) ||
        !std::isfinite(authority->runtime.position_y) ||
        !std::isfinite(authority->runtime.heading)) {
        return nullptr;
    }
    if (authority->last_packet_ms != 0 && now_ms > authority->last_packet_ms + kRunEntryAuthoritySnapshotStaleMs) {
        return nullptr;
    }
    return authority;
}

std::uint32_t ResolveRunEntryFormationSlot(
    const multiplayer::RuntimeState& runtime_state,
    std::uint64_t authority_participant_id,
    std::uint64_t local_transport_participant_id) {
    if (local_transport_participant_id == 0 ||
        local_transport_participant_id == authority_participant_id) {
        return 1;
    }

    std::uint32_t slot = 1;
    for (const auto& participant : runtime_state.participants) {
        if (participant.participant_id == 0 ||
            participant.participant_id == authority_participant_id ||
            participant.participant_id == local_transport_participant_id ||
            participant.participant_id > local_transport_participant_id ||
            !multiplayer::IsRemoteParticipant(participant) ||
            !participant.transport_connected ||
            !participant.runtime.valid ||
            participant.runtime.scene_intent.kind != multiplayer::ParticipantSceneIntentKind::Run) {
            continue;
        }
        slot += 1;
    }
    return slot;
}

void ResolveRunEntryFormationOffset(std::uint32_t slot, float* offset_x, float* offset_y) {
    if (offset_x == nullptr || offset_y == nullptr) {
        return;
    }

    if (slot == 0) {
        slot = 1;
    }
    const std::uint32_t ring = (slot - 1) / 8 + 1;
    switch ((slot - 1) % 8) {
    case 0:
        *offset_x = kRunEntryFormationSpacing * static_cast<float>(ring);
        *offset_y = 0.0f;
        break;
    case 1:
        *offset_x = -kRunEntryFormationSpacing * static_cast<float>(ring);
        *offset_y = 0.0f;
        break;
    case 2:
        *offset_x = 0.0f;
        *offset_y = kRunEntryFormationSpacing * static_cast<float>(ring);
        break;
    case 3:
        *offset_x = 0.0f;
        *offset_y = -kRunEntryFormationSpacing * static_cast<float>(ring);
        break;
    case 4:
        *offset_x = kRunEntryFormationSpacing * static_cast<float>(ring);
        *offset_y = kRunEntryFormationSpacing * static_cast<float>(ring);
        break;
    case 5:
        *offset_x = -kRunEntryFormationSpacing * static_cast<float>(ring);
        *offset_y = kRunEntryFormationSpacing * static_cast<float>(ring);
        break;
    case 6:
        *offset_x = kRunEntryFormationSpacing * static_cast<float>(ring);
        *offset_y = -kRunEntryFormationSpacing * static_cast<float>(ring);
        break;
    default:
        *offset_x = -kRunEntryFormationSpacing * static_cast<float>(ring);
        *offset_y = -kRunEntryFormationSpacing * static_cast<float>(ring);
        break;
    }
}

bool TrySnapRunEntryFormationTargetToNav(
    float desired_x,
    float desired_y,
    float authority_x,
    float authority_y,
    float* target_x,
    float* target_y) {
    if (target_x == nullptr || target_y == nullptr) {
        return false;
    }

    SDModGameplayNavGridState nav_grid;
    if (!TryGetGameplayNavGridState(&nav_grid, 1) || !nav_grid.valid) {
        return false;
    }

    const float max_distance2 =
        kRunEntryFormationNavSnapMaxDistance * kRunEntryFormationNavSnapMaxDistance;
    const float max_authority_distance2 =
        kRunEntryFormationNavSnapMaxAuthorityDistance * kRunEntryFormationNavSnapMaxAuthorityDistance;
    float best_distance2 = max_distance2;
    bool found = false;
    for (const auto& cell : nav_grid.cells) {
        for (const auto& sample : cell.samples) {
            if (!sample.traversable ||
                !std::isfinite(sample.world_x) ||
                !std::isfinite(sample.world_y)) {
                continue;
            }
            const float dx = sample.world_x - desired_x;
            const float dy = sample.world_y - desired_y;
            const float distance2 = dx * dx + dy * dy;
            const float authority_dx = sample.world_x - authority_x;
            const float authority_dy = sample.world_y - authority_y;
            const float authority_distance2 = authority_dx * authority_dx + authority_dy * authority_dy;
            if (authority_distance2 > max_authority_distance2) {
                continue;
            }
            if (distance2 <= best_distance2) {
                best_distance2 = distance2;
                *target_x = sample.world_x;
                *target_y = sample.world_y;
                found = true;
            }
        }
    }
    return found;
}

void ApplyHostAuthoritativeRunEntryFormationIfNeeded(
    const multiplayer::RuntimeState& runtime_state,
    std::uint64_t now_ms) {
    if (!multiplayer::IsLocalTransportClient()) {
        return;
    }

    SDModSceneState scene_state;
    if (!TryGetSceneState(&scene_state) ||
        !scene_state.valid ||
        SceneIntentKindFromSceneState(scene_state) != multiplayer::ParticipantSceneIntentKind::Run) {
        ResetHostAuthoritativeRunEntryFormation();
        return;
    }
    if (IsReplicatedWorldSnapshotSceneChurnInFlight(now_ms)) {
        return;
    }

    const auto* authority = FindRunEntryAuthorityParticipant(runtime_state, now_ms);
    if (authority == nullptr) {
        return;
    }

    SDModPlayerState player_state;
    if (!TryGetPlayerState(&player_state) ||
        !player_state.valid ||
        player_state.actor_address == 0 ||
        player_state.world_address == 0) {
        return;
    }

    const auto authority_id = authority->participant_id;
    const auto run_nonce = runtime_state.world_snapshot.run_nonce;
    const bool same_formation =
        g_run_entry_formation_world_address == player_state.world_address &&
        g_run_entry_formation_authority_participant_id == authority_id &&
        g_run_entry_formation_run_nonce == run_nonce;
    if (!same_formation) {
        g_run_entry_formation_world_address = player_state.world_address;
        g_run_entry_formation_authority_participant_id = authority_id;
        g_run_entry_formation_run_nonce = run_nonce;
        g_run_entry_formation_started_ms = now_ms;
        g_run_entry_formation_last_apply_ms = 0;
        g_run_entry_formation_authority_x = 0.0f;
        g_run_entry_formation_authority_y = 0.0f;
        g_run_entry_formation_authority_stable_since_ms = 0;
        g_run_entry_formation_have_authority_sample = false;
        g_run_entry_formation_settled = false;
    }
    if (same_formation && g_run_entry_formation_settled) {
        return;
    }

    const float authority_sample_dx =
        g_run_entry_formation_have_authority_sample
            ? authority->runtime.position_x - g_run_entry_formation_authority_x
            : 0.0f;
    const float authority_sample_dy =
        g_run_entry_formation_have_authority_sample
            ? authority->runtime.position_y - g_run_entry_formation_authority_y
            : 0.0f;
    const bool authority_sample_changed =
        !g_run_entry_formation_have_authority_sample ||
        authority_sample_dx * authority_sample_dx + authority_sample_dy * authority_sample_dy >
            kRunEntryFormationAuthoritySettleDistance * kRunEntryFormationAuthoritySettleDistance;
    if (authority_sample_changed) {
        g_run_entry_formation_authority_x = authority->runtime.position_x;
        g_run_entry_formation_authority_y = authority->runtime.position_y;
        g_run_entry_formation_authority_stable_since_ms = now_ms;
        g_run_entry_formation_have_authority_sample = true;
        g_run_entry_formation_settled = false;
    }

    if (g_run_entry_formation_started_ms != 0 &&
        now_ms - g_run_entry_formation_started_ms > kRunEntryFormationBootstrapMs) {
        return;
    }
    if (!g_run_entry_formation_have_authority_sample ||
        g_run_entry_formation_authority_stable_since_ms == 0 ||
        now_ms - g_run_entry_formation_authority_stable_since_ms < kRunEntryFormationAuthorityStableMs) {
        return;
    }

    const auto local_transport_participant_id = multiplayer::GetLocalTransportParticipantId();
    const auto slot = ResolveRunEntryFormationSlot(
        runtime_state,
        authority_id,
        local_transport_participant_id);
    float offset_x = 0.0f;
    float offset_y = 0.0f;
    ResolveRunEntryFormationOffset(slot, &offset_x, &offset_y);

    const float desired_x = authority->runtime.position_x + offset_x;
    const float desired_y = authority->runtime.position_y + offset_y;
    if (!std::isfinite(desired_x) || !std::isfinite(desired_y)) {
        return;
    }

    float target_x = desired_x;
    float target_y = desired_y;
    const bool nav_snapped = TrySnapRunEntryFormationTargetToNav(
        desired_x,
        desired_y,
        authority->runtime.position_x,
        authority->runtime.position_y,
        &target_x,
        &target_y);
    const float current_target_dx = player_state.x - target_x;
    const float current_target_dy = player_state.y - target_y;
    const float current_target_distance2 =
        current_target_dx * current_target_dx + current_target_dy * current_target_dy;
    if (same_formation &&
        current_target_distance2 <= kRunEntryFormationReapplyDistance * kRunEntryFormationReapplyDistance) {
        if (g_run_entry_formation_started_ms != 0 &&
            now_ms - g_run_entry_formation_started_ms >= kRunEntryFormationMinimumSettleMs) {
            g_run_entry_formation_settled = true;
        }
        return;
    }
    if (same_formation &&
        g_run_entry_formation_last_apply_ms != 0 &&
        now_ms - g_run_entry_formation_last_apply_ms < kRunEntryFormationReapplyIntervalMs) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    const bool wrote_position =
        memory.TryWriteField(player_state.actor_address, kActorPositionXOffset, target_x) &&
        memory.TryWriteField(player_state.actor_address, kActorPositionYOffset, target_y);
    if (!wrote_position) {
        return;
    }

    ApplyWizardActorFacingState(player_state.actor_address, authority->runtime.heading);
    std::string rebind_error;
    const bool rebound = RebindSceneActorCell(player_state.actor_address, &rebind_error);
    g_run_entry_formation_last_apply_ms = now_ms;

    Log(
        "world_snapshot: applied host-authoritative run entry formation. authority=" +
        std::to_string(authority_id) +
        " local=" + std::to_string(local_transport_participant_id) +
        " slot=" + std::to_string(slot) +
        " target=(" + std::to_string(target_x) + "," + std::to_string(target_y) + ")" +
        " anchor=(" + std::to_string(authority->runtime.position_x) + "," +
        std::to_string(authority->runtime.position_y) + ")" +
        " reapply=" + (same_formation ? "true" : "false") +
        " nav_snapped=" + (nav_snapped ? "true" : "false") +
        " rebound=" + (rebound ? "true" : "false") +
        (rebound ? "" : " rebind_error=" + rebind_error));
}

bool IsReplicatedSharedHubFactoryActorType(std::uint32_t native_type_id);
