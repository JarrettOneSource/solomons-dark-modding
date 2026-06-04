namespace {

constexpr std::uint64_t kWorldSnapshotApplyStaleMs = 500;
constexpr std::uint64_t kWorldSnapshotInterpolationDelayMs = 150;
constexpr std::uint64_t kWorldSnapshotRunLifecycleRequestIntervalMs = 1000;
constexpr std::uint64_t kHubAnimationDrivePhaseUnitsPerSecond = 150;
constexpr std::uint64_t kRunEntryAuthoritySnapshotStaleMs = 3000;
constexpr float kWorldSnapshotSettleDistance = 0.05f;
constexpr float kWorldSnapshotParkBase = 100000.0f;
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
}

bool IsReplicatedHubPhaseAdvancingActorSnapshot(
    const multiplayer::WorldActorSnapshot& actor) {
    switch (actor.native_type_id) {
    case 0x138B:
    case 0x138C:
    case 0x138D:
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

void OverlayLatestWorldSnapshotPresentation(
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
        return;
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
        if ((actor.presentation_flags & multiplayer::WorldActorPresentationFlagAnimationDriveWord) != 0 &&
            IsReplicatedHubPhaseAdvancingActorSnapshot(actor)) {
            actor.anim_drive_state_word = AdvanceHubAnimationDrivePhase(
                actor.anim_drive_state_word,
                now_ms - latest_snapshot.received_ms);
            actor.anim_drive_state = static_cast<std::uint8_t>(actor.anim_drive_state_word & 0xFFu);
        }
    }
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
                 actor.object_type_id == kSolomonRunStaticNativeTypeId));
    }

    return scene_kind == multiplayer::ParticipantSceneIntentKind::SharedHub;
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
                 !actor.dead &&
                 std::isfinite(actor.hp) &&
                 std::isfinite(actor.max_hp) &&
                 actor.max_hp > 0.0f &&
                 actor.hp > 0.05f) ||
                (actor.run_static &&
                 (actor.native_type_id == kSolomonDigNativeTypeId ||
                  actor.native_type_id == kSolomonRunStaticNativeTypeId)));
    }

    return scene_kind == multiplayer::ParticipantSceneIntentKind::SharedHub;
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

std::uint64_t BuildReplicatedWorldActorNetworkId(
    const SDModSceneActorState& actor,
    std::uint32_t type_ordinal) {
    return (static_cast<std::uint64_t>(actor.object_type_id) << 32) |
           static_cast<std::uint64_t>(type_ordinal);
}

bool IsParkedReplicatedWorldActor(const SDModSceneActorState& actor) {
    return actor.x >= kWorldSnapshotParkBase * 0.5f &&
           actor.y >= kWorldSnapshotParkBase * 0.5f;
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
    g_replicated_run_bindings_by_network_id.clear();
    g_replicated_run_network_ids_by_actor.clear();
}

void BindReplicatedRunActor(std::uint64_t network_actor_id, uintptr_t actor_address) {
    if (network_actor_id == 0 || actor_address == 0) {
        return;
    }

    const auto previous_by_id = g_replicated_run_bindings_by_network_id.find(network_actor_id);
    if (previous_by_id != g_replicated_run_bindings_by_network_id.end() &&
        previous_by_id->second != actor_address) {
        g_replicated_run_network_ids_by_actor.erase(previous_by_id->second);
    }

    const auto previous_by_actor = g_replicated_run_network_ids_by_actor.find(actor_address);
    if (previous_by_actor != g_replicated_run_network_ids_by_actor.end() &&
        previous_by_actor->second != network_actor_id) {
        g_replicated_run_bindings_by_network_id.erase(previous_by_actor->second);
    }

    g_replicated_run_bindings_by_network_id[network_actor_id] = actor_address;
    g_replicated_run_network_ids_by_actor[actor_address] = network_actor_id;
}

void UnbindReplicatedRunActor(std::uint64_t network_actor_id, uintptr_t actor_address) {
    if (network_actor_id != 0) {
        g_replicated_run_bindings_by_network_id.erase(network_actor_id);
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

bool ApplyReplicatedWorldActorPresentation(
    uintptr_t actor_address,
    const multiplayer::WorldActorSnapshot& authoritative_actor) {
    if (actor_address == 0 || authoritative_actor.presentation_flags == 0) {
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

bool ApplyReplicatedWorldActorTransform(
    uintptr_t actor_address,
    const multiplayer::WorldActorSnapshot& authoritative_actor,
    bool force_write) {
    if (actor_address == 0 ||
        !std::isfinite(authoritative_actor.position_x) ||
        !std::isfinite(authoritative_actor.position_y) ||
        !std::isfinite(authoritative_actor.heading)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    float current_x = 0.0f;
    float current_y = 0.0f;
    const bool have_current_position =
        TryReadFiniteFloatField(actor_address, kActorPositionXOffset, &current_x) &&
        TryReadFiniteFloatField(actor_address, kActorPositionYOffset, &current_y);
    const float dx = have_current_position ? authoritative_actor.position_x - current_x : 0.0f;
    const float dy = have_current_position ? authoritative_actor.position_y - current_y : 0.0f;
    const bool position_changed =
        force_write ||
        !have_current_position ||
        dx * dx + dy * dy > kWorldSnapshotSettleDistance * kWorldSnapshotSettleDistance;

    bool wrote_position = false;
    if (position_changed) {
        wrote_position =
            memory.TryWriteField(actor_address, kActorPositionXOffset, authoritative_actor.position_x) &&
            memory.TryWriteField(actor_address, kActorPositionYOffset, authoritative_actor.position_y);
        if (wrote_position) {
            DWORD rebind_exception_code = 0;
            (void)TryRebindActorToOwnerWorld(actor_address, &rebind_exception_code);
        }
    }

    (void)memory.TryWriteField(actor_address, kActorHeadingOffset, authoritative_actor.heading);
    ApplyReplicatedWorldActorDriveState(actor_address, authoritative_actor.anim_drive_state);
    return wrote_position;
}

bool TryCreateReplicatedSharedHubActor(
    uintptr_t world_address,
    const multiplayer::WorldActorSnapshot& authoritative_actor,
    uintptr_t* actor_address_out) {
    if (actor_address_out != nullptr) {
        *actor_address_out = 0;
    }
    if (world_address == 0 ||
        !IsReplicatedSharedHubFactoryActorType(authoritative_actor.native_type_id) ||
        !std::isfinite(authoritative_actor.position_x) ||
        !std::isfinite(authoritative_actor.position_y)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto factory_address = memory.ResolveGameAddressOrZero(kGameObjectFactory);
    const auto factory_context_address = memory.ResolveGameAddressOrZero(kGameObjectFactoryContextGlobal);
    const auto register_address = memory.ResolveGameAddressOrZero(kActorWorldRegister);
    if (factory_address == 0 || factory_context_address == 0 || register_address == 0) {
        return false;
    }

    uintptr_t actor_address = 0;
    DWORD exception_code = 0;
    if (!CallGameObjectFactorySafe(
            factory_address,
            factory_context_address,
            static_cast<int>(authoritative_actor.native_type_id),
            &actor_address,
            &exception_code) ||
        actor_address == 0) {
        Log(
            "world_snapshot: factory create failed. type=0x" +
            HexString(static_cast<uintptr_t>(authoritative_actor.native_type_id)) +
            " seh=" + HexString(exception_code));
        return false;
    }

    (void)memory.TryWriteField(actor_address, kActorPositionXOffset, authoritative_actor.position_x);
    (void)memory.TryWriteField(actor_address, kActorPositionYOffset, authoritative_actor.position_y);
    if (std::isfinite(authoritative_actor.heading)) {
        (void)memory.TryWriteField(actor_address, kActorHeadingOffset, authoritative_actor.heading);
    }

    exception_code = 0;
    if (!CallActorWorldRegisterSafe(
            register_address,
            world_address,
            0,
            actor_address,
            -1,
            0,
            &exception_code)) {
        const auto object_delete_address = memory.ResolveGameAddressOrZero(kObjectDelete);
        DWORD delete_exception_code = 0;
        if (object_delete_address != 0) {
            (void)CallObjectDeleteSafe(object_delete_address, actor_address, &delete_exception_code);
        }
        Log(
            "world_snapshot: actor register failed. type=0x" +
            HexString(static_cast<uintptr_t>(authoritative_actor.native_type_id)) +
            " actor=" + HexString(actor_address) +
            " seh=" + HexString(exception_code) +
            " delete_seh=" + HexString(delete_exception_code));
        return false;
    }

    (void)ApplyReplicatedWorldActorTransform(actor_address, authoritative_actor, true);
    Log(
        "world_snapshot: created replicated hub actor. type=0x" +
        HexString(static_cast<uintptr_t>(authoritative_actor.native_type_id)) +
        " actor=" + HexString(actor_address) +
        " network_actor_id=" + std::to_string(authoritative_actor.network_actor_id));
    if (actor_address_out != nullptr) {
        *actor_address_out = actor_address;
    }
    return true;
}

bool TryFindCreatedReplicatedSharedHubActor(
    const multiplayer::WorldActorSnapshot& authoritative_actor,
    uintptr_t* actor_address_out) {
    if (actor_address_out != nullptr) {
        *actor_address_out = 0;
    }

    const auto it = g_replicated_created_hub_actors.find(authoritative_actor.network_actor_id);
    if (it == g_replicated_created_hub_actors.end()) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    std::uint32_t native_type_id = 0;
    if (it->second == 0 ||
        !memory.TryReadField(it->second, kGameObjectTypeIdOffset, &native_type_id) ||
        native_type_id != authoritative_actor.native_type_id) {
        g_replicated_created_hub_actors.erase(it);
        return false;
    }

    if (actor_address_out != nullptr) {
        *actor_address_out = it->second;
    }
    BindReplicatedSharedHubActor(authoritative_actor.network_actor_id, it->second);
    return true;
}

bool ApplyReplicatedRunEnemyHealth(
    uintptr_t actor_address,
    const multiplayer::WorldActorSnapshot& authoritative_actor) {
    if (actor_address == 0 ||
        !authoritative_actor.tracked_enemy ||
        !std::isfinite(authoritative_actor.hp) ||
        !std::isfinite(authoritative_actor.max_hp) ||
        authoritative_actor.max_hp <= 0.0f) {
        return false;
    }

    ActorHealthRuntime local_health;
    if (!TryReadArenaEnemyActorHealth(actor_address, &local_health)) {
        return false;
    }

    const float authoritative_max_hp = authoritative_actor.max_hp;
    const float authoritative_hp = (std::max)(0.0f, (std::min)(authoritative_actor.hp, authoritative_max_hp));
    const bool hp_changed = std::fabs(local_health.hp - authoritative_hp) > 0.01f;
    const bool max_hp_changed = std::fabs(local_health.max_hp - authoritative_max_hp) > 0.01f;
    if (!hp_changed && !max_hp_changed) {
        return false;
    }

    if (multiplayer::IsLocalTransportClient() &&
        authoritative_actor.network_actor_id != 0 &&
        local_health.hp + 0.05f < authoritative_hp) {
        multiplayer::QueueLocalEnemyDamageClaim(
            authoritative_actor.network_actor_id,
            0,
            authoritative_hp,
            local_health.hp,
            authoritative_max_hp,
            authoritative_actor.position_x,
            authoritative_actor.position_y);
    }

    auto& memory = ProcessMemory::Instance();
    bool wrote = true;
    if (max_hp_changed) {
        wrote = memory.TryWriteField(actor_address, kEnemyMaxHpOffset, authoritative_max_hp) && wrote;
    }
    if (hp_changed) {
        wrote = memory.TryWriteField(actor_address, kEnemyCurrentHpOffset, authoritative_hp) && wrote;
    }
    return wrote;
}

bool RemoveReplicatedSharedHubActor(
    const ReplicatedWorldActorLocalBinding& binding,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (binding.actor.actor_address == 0 ||
        !IsReplicatedSharedHubFactoryActorType(binding.actor.object_type_id)) {
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

bool ParkReplicatedRunActor(const ReplicatedWorldActorLocalBinding& binding) {
    if (binding.actor.actor_address == 0 ||
        !binding.actor.tracked_enemy ||
        !ShouldReconcileLocalWorldActor(binding.actor, multiplayer::ParticipantSceneIntentKind::Run)) {
        return false;
    }

    const auto actor_address = binding.actor.actor_address;
    const float address_jitter_x = static_cast<float>((actor_address >> 4) & 0x3FFu);
    const float address_jitter_y = static_cast<float>((actor_address >> 14) & 0x3FFu);
    const float park_x = kWorldSnapshotParkBase + address_jitter_x * 8.0f;
    const float park_y = kWorldSnapshotParkBase + address_jitter_y * 8.0f;

    auto& memory = ProcessMemory::Instance();
    bool wrote =
        memory.TryWriteField(actor_address, kActorPositionXOffset, park_x) &&
        memory.TryWriteField(actor_address, kActorPositionYOffset, park_y);
    if (std::isfinite(binding.actor.max_hp) && binding.actor.max_hp > 0.0f) {
        wrote = memory.TryWriteField(actor_address, kEnemyCurrentHpOffset, binding.actor.max_hp) && wrote;
        wrote = memory.TryWriteField(actor_address, kEnemyMaxHpOffset, binding.actor.max_hp) && wrote;
    }

    DWORD rebind_exception_code = 0;
    (void)TryRebindActorToOwnerWorld(actor_address, &rebind_exception_code);
    return wrote;
}

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
            ShouldUseAuthoritativeWorldActorForScene(authoritative_actor, snapshot.scene_intent.kind)) {
            count += 1;
        }
    }
    return count;
}

std::uint32_t CountLocalTrackedRunEnemyBindings(
    const std::vector<ReplicatedWorldActorLocalBinding>& local_bindings) {
    std::uint32_t count = 0;
    for (const auto& binding : local_bindings) {
        if (binding.actor.tracked_enemy &&
            ShouldReconcileLocalWorldActor(binding.actor, multiplayer::ParticipantSceneIntentKind::Run)) {
            count += 1;
        }
    }
    return count;
}

void MaybeCatchUpRunEnemyPoolForAuthoritativeSnapshot(
    const multiplayer::WorldSnapshotRuntimeInfo& snapshot,
    std::uint32_t local_tracked_enemy_count) {
    if (snapshot.scene_intent.kind != multiplayer::ParticipantSceneIntentKind::Run ||
        snapshot.truncated) {
        return;
    }
    if (!IsLocalRunCombatAlreadyActive()) {
        return;
    }

    const auto authoritative_tracked_enemy_count = CountAuthoritativeTrackedRunEnemiesForScene(snapshot);
    if (authoritative_tracked_enemy_count <= local_tracked_enemy_count) {
        return;
    }

    (void)TryAccelerateRunLifecycleEnemyPoolForSnapshot(
        authoritative_tracked_enemy_count - local_tracked_enemy_count);
}

bool TryBindAuthoritativeRunActorToLocalPool(
    const multiplayer::WorldActorSnapshot& authoritative_actor,
    std::vector<ReplicatedWorldActorLocalBinding>* local_bindings,
    std::size_t* binding_index_out) {
    if (binding_index_out != nullptr) {
        *binding_index_out = 0;
    }
    if (local_bindings == nullptr ||
        authoritative_actor.network_actor_id == 0 ||
        authoritative_actor.native_type_id == 0) {
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
                binding.network_actor_id != 0 ||
                binding.actor.object_type_id != authoritative_actor.native_type_id) {
                continue;
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
        BindReplicatedRunActor(authoritative_actor.network_actor_id, binding.actor.actor_address);
        binding.network_actor_id = authoritative_actor.network_actor_id;
        if (binding_index_out != nullptr) {
            *binding_index_out = best_index;
        }
        return true;
    };

    const bool prefer_nearest = authoritative_actor.run_static;
    return choose_binding(true, prefer_nearest) || choose_binding(false, prefer_nearest);
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
        authoritative_actor.native_type_id == 0) {
        return false;
    }

    auto choose_binding = [&](bool allow_parked) -> bool {
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
            if (!allow_parked && IsParkedReplicatedWorldActor(binding.actor)) {
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

    return choose_binding(false) || choose_binding(true);
}

void PublishWorldSnapshotApplyCounts(
    const multiplayer::WorldSnapshotRuntimeInfo& snapshot,
    const WorldSnapshotApplyCounts& counts,
    std::uint64_t now_ms) {
    multiplayer::UpdateRuntimeState([&](multiplayer::RuntimeState& state) {
        state.world_snapshot_apply.valid = true;
        state.world_snapshot_apply.applied_ms = now_ms;
        state.world_snapshot_apply.sequence = snapshot.sequence;
        state.world_snapshot_apply.scene_epoch = snapshot.scene_epoch;
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
        state.world_snapshot_apply.failed_remove_actor_count = counts.failed_remove_actor_count;
        state.world_snapshot_apply.actor_bindings = counts.actor_bindings;
    });
}

void ClearWorldSnapshotApplyState(std::uint64_t now_ms) {
    multiplayer::UpdateRuntimeState([&](multiplayer::RuntimeState& state) {
        state.world_snapshot_apply = multiplayer::WorldSnapshotApplyRuntimeInfo{};
        state.world_snapshot_apply.applied_ms = now_ms;
    });
}

void ApplyReplicatedWorldSnapshotIfActive(uintptr_t /*gameplay_address*/, std::uint64_t now_ms) {
    MaybeQueueRunLifecycleForRemoteAuthority(now_ms);

    const auto runtime_state = multiplayer::SnapshotRuntimeState();
    ApplyHostAuthoritativeRunEntryFormationIfNeeded(runtime_state, now_ms);
    multiplayer::WorldSnapshotRuntimeInfo snapshot;
    const bool have_snapshot = multiplayer::TrySampleWorldSnapshot(
        runtime_state,
        now_ms,
        kWorldSnapshotInterpolationDelayMs,
        &snapshot);
    if (!have_snapshot ||
        !snapshot.valid ||
        snapshot.actors.empty() ||
        now_ms < snapshot.received_ms ||
        now_ms - snapshot.received_ms > kWorldSnapshotApplyStaleMs) {
        if (runtime_state.world_snapshot_apply.valid) {
            ClearWorldSnapshotApplyState(now_ms);
        }
        return;
    }
    const auto local_transport_participant_id = multiplayer::GetLocalTransportParticipantId();
    if (local_transport_participant_id != 0 &&
        snapshot.authority_participant_id == local_transport_participant_id) {
        if (runtime_state.world_snapshot_apply.valid) {
            ClearWorldSnapshotApplyState(now_ms);
        }
        return;
    }
    OverlayLatestWorldSnapshotPresentation(&snapshot, runtime_state.world_snapshot, now_ms);
    if (snapshot.scene_intent.kind != multiplayer::ParticipantSceneIntentKind::SharedHub &&
        snapshot.scene_intent.kind != multiplayer::ParticipantSceneIntentKind::Run) {
        if (runtime_state.world_snapshot_apply.valid) {
            ClearWorldSnapshotApplyState(now_ms);
        }
        return;
    }

    SDModSceneState scene_state;
    if (!TryGetSceneState(&scene_state) || !scene_state.valid ||
        !IsReplicatedWorldSnapshotSceneCurrent(scene_state, snapshot)) {
        return;
    }
    if (IsReplicatedWorldSnapshotSceneChurnInFlight(now_ms)) {
        return;
    }

    MaybeQueueRunLifecycleForAuthoritativeSnapshot(snapshot, now_ms);
    if (snapshot.scene_intent.kind == multiplayer::ParticipantSceneIntentKind::SharedHub &&
        g_replicated_created_hub_scene_epoch != snapshot.scene_epoch) {
        ClearReplicatedSharedHubActorBindings();
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
    MaybeCatchUpRunEnemyPoolForAuthoritativeSnapshot(
        snapshot,
        CountLocalTrackedRunEnemyBindings(local_bindings));

    std::unordered_set<std::uint64_t> authoritative_ids;
    authoritative_ids.reserve(snapshot.actors.size());
    const bool snapshot_may_be_complete = !snapshot.truncated &&
        (snapshot.scene_intent.kind == multiplayer::ParticipantSceneIntentKind::SharedHub ||
         snapshot.scene_intent.kind == multiplayer::ParticipantSceneIntentKind::Run);
    const bool can_mutate_shared_hub_actors = CanMutateReplicatedSharedHubActors(snapshot, now_ms);
    for (const auto& authoritative_actor : snapshot.actors) {
        if (!ShouldUseAuthoritativeWorldActorForScene(authoritative_actor, snapshot.scene_intent.kind)) {
            continue;
        }
        authoritative_ids.insert(authoritative_actor.network_actor_id);
    }

    if (snapshot_may_be_complete &&
        snapshot.scene_intent.kind == multiplayer::ParticipantSceneIntentKind::Run) {
        for (auto& binding : local_bindings) {
            if (binding.network_actor_id != 0 &&
                authoritative_ids.find(binding.network_actor_id) == authoritative_ids.end()) {
                UnbindReplicatedRunActor(binding.network_actor_id, binding.actor.actor_address);
                binding.network_actor_id = 0;
            }
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
            snapshot.scene_intent.kind == multiplayer::ParticipantSceneIntentKind::SharedHub) {
            std::size_t binding_index = 0;
            if (TryBindAuthoritativeSharedHubActorToLocalPool(authoritative_actor, &local_bindings, &binding_index)) {
                local_by_network_id.emplace(authoritative_actor.network_actor_id, binding_index);
                local_it = local_by_network_id.find(authoritative_actor.network_actor_id);
            }
        }
        if (local_it == local_by_network_id.end() &&
            snapshot.scene_intent.kind == multiplayer::ParticipantSceneIntentKind::Run &&
            authoritative_actor.lifecycle_owned) {
            std::size_t binding_index = 0;
            if (TryBindAuthoritativeRunActorToLocalPool(authoritative_actor, &local_bindings, &binding_index)) {
                local_by_network_id.emplace(authoritative_actor.network_actor_id, binding_index);
                local_it = local_by_network_id.find(authoritative_actor.network_actor_id);
            }
        }
        if (local_it == local_by_network_id.end()) {
            uintptr_t created_actor_address = 0;
            if (snapshot.scene_intent.kind == multiplayer::ParticipantSceneIntentKind::SharedHub &&
                snapshot_may_be_complete &&
                can_mutate_shared_hub_actors &&
                IsReplicatedSharedHubFactoryActorType(authoritative_actor.native_type_id)) {
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
                if (ApplyReplicatedWorldActorTransform(created_actor_address, authoritative_actor, true)) {
                    counts.transform_write_count += 1;
                }
                if (ApplyReplicatedWorldActorPresentation(created_actor_address, authoritative_actor)) {
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
        if (ApplyReplicatedWorldActorTransform(binding.actor.actor_address, authoritative_actor, false)) {
            counts.transform_write_count += 1;
        }
        if (ApplyReplicatedWorldActorPresentation(binding.actor.actor_address, authoritative_actor)) {
            counts.presentation_write_count += 1;
        }
        if (snapshot.scene_intent.kind == multiplayer::ParticipantSceneIntentKind::Run &&
            authoritative_actor.tracked_enemy &&
            ApplyReplicatedRunEnemyHealth(binding.actor.actor_address, authoritative_actor)) {
            counts.health_write_count += 1;
        }
        RecordWorldSnapshotBinding(&counts, authoritative_actor, binding.actor.actor_address, true, false);
    }

    if (snapshot_may_be_complete &&
        (snapshot.scene_intent.kind != multiplayer::ParticipantSceneIntentKind::SharedHub ||
         can_mutate_shared_hub_actors)) {
        for (auto& binding : local_bindings) {
            if (binding.matched) {
                continue;
            }
            if (snapshot.scene_intent.kind == multiplayer::ParticipantSceneIntentKind::Run) {
                const auto removed_network_actor_id = binding.network_actor_id;
                if (binding.network_actor_id != 0 &&
                    authoritative_ids.find(binding.network_actor_id) == authoritative_ids.end()) {
                    UnbindReplicatedRunActor(binding.network_actor_id, binding.actor.actor_address);
                    binding.network_actor_id = 0;
                }
                DWORD exception_code = 0;
                const auto removed_actor_address = binding.actor.actor_address;
                if (binding.actor.tracked_enemy && ParkReplicatedRunActor(binding)) {
                    counts.parked_actor_count += 1;
                    if (removed_network_actor_id != 0) {
                        auto removed_binding = binding;
                        removed_binding.network_actor_id = removed_network_actor_id;
                        RecordWorldSnapshotBinding(&counts, removed_binding, false, true, true);
                        UnbindReplicatedRunActor(removed_network_actor_id, removed_actor_address);
                    }
                    Log(
                        "world_snapshot: parked extra run actor. actor=" +
                        HexString(removed_actor_address) +
                        " type=" + HexString(static_cast<uintptr_t>(binding.actor.object_type_id)) +
                        " network_actor_id=" + std::to_string(removed_network_actor_id));
                    continue;
                }
                if (RemoveReplicatedRunActor(binding, &exception_code)) {
                    counts.removed_actor_count += 1;
                    if (removed_network_actor_id != 0) {
                        auto removed_binding = binding;
                        removed_binding.network_actor_id = removed_network_actor_id;
                        RecordWorldSnapshotBinding(&counts, removed_binding, false, false, true);
                        UnbindReplicatedRunActor(removed_network_actor_id, removed_actor_address);
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
                !IsReplicatedSharedHubFactoryActorType(binding.actor.object_type_id) ||
                authoritative_ids.find(binding.network_actor_id) != authoritative_ids.end()) {
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

    PublishWorldSnapshotApplyCounts(snapshot, counts, now_ms);
}

}  // namespace
