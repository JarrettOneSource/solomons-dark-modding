namespace {

constexpr std::uint64_t kWorldSnapshotApplyStaleMs = 500;
constexpr std::uint64_t kWorldSnapshotInterpolationDelayMs = 150;
constexpr std::uint64_t kWorldSnapshotRunLifecycleRequestIntervalMs = 1000;
constexpr float kWorldSnapshotSettleDistance = 0.05f;
constexpr float kWorldSnapshotParkBase = 100000.0f;

std::unordered_map<std::uint64_t, uintptr_t> g_replicated_created_hub_actors;
std::unordered_map<std::uint64_t, uintptr_t> g_replicated_hub_bindings_by_network_id;
std::unordered_map<uintptr_t, std::uint64_t> g_replicated_hub_network_ids_by_actor;
std::uint32_t g_replicated_created_hub_scene_epoch = 0;
std::unordered_map<std::uint64_t, uintptr_t> g_replicated_run_bindings_by_network_id;
std::unordered_map<uintptr_t, std::uint64_t> g_replicated_run_network_ids_by_actor;
std::uint32_t g_replicated_run_actor_scene_epoch = 0;

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

bool ShouldReconcileLocalWorldActor(
    const SDModSceneActorState& actor,
    multiplayer::ParticipantSceneIntentKind scene_kind) {
    if (!actor.valid ||
        actor.actor_address == 0 ||
        actor.object_type_id == 0 ||
        actor.object_type_id == 1 ||
        !std::isfinite(actor.x) ||
        !std::isfinite(actor.y) ||
        !std::isfinite(actor.radius) ||
        actor.radius < 0.0f) {
        return false;
    }

    if (scene_kind == multiplayer::ParticipantSceneIntentKind::Run) {
        return actor.tracked_enemy &&
               std::isfinite(actor.hp) &&
               std::isfinite(actor.max_hp) &&
               actor.max_hp > 0.0f;
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
        return actor.tracked_enemy &&
               actor.lifecycle_owned &&
               std::isfinite(actor.hp) &&
               std::isfinite(actor.max_hp) &&
               actor.max_hp > 0.0f;
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

bool ParkReplicatedWorldActor(uintptr_t actor_address, std::uint32_t park_index) {
    if (actor_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const float parked_x = kWorldSnapshotParkBase + static_cast<float>(park_index * 12);
    const float parked_y = kWorldSnapshotParkBase;
    const bool wrote_position =
        memory.TryWriteField(actor_address, kActorPositionXOffset, parked_x) &&
        memory.TryWriteField(actor_address, kActorPositionYOffset, parked_y);
    if (wrote_position) {
        DWORD rebind_exception_code = 0;
        (void)TryRebindActorToOwnerWorld(actor_address, &rebind_exception_code);
    }
    ApplyReplicatedWorldActorDriveState(actor_address, 0);
    return wrote_position;
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

void RemoveReplicatedCreatedSharedHubActorsForSceneSwitch(const char* reason) {
    if (g_replicated_created_hub_actors.empty()) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    std::vector<std::pair<std::uint64_t, uintptr_t>> created_actors;
    created_actors.reserve(g_replicated_created_hub_actors.size());
    for (const auto& entry : g_replicated_created_hub_actors) {
        if (entry.first != 0 && entry.second != 0) {
            created_actors.push_back(entry);
        }
    }

    for (const auto& entry : created_actors) {
        std::uint32_t native_type_id = 0;
        if (!memory.TryReadField(entry.second, kGameObjectTypeIdOffset, &native_type_id) ||
            !IsReplicatedSharedHubFactoryActorType(native_type_id)) {
            UnbindReplicatedSharedHubActor(entry.first, entry.second);
            continue;
        }

        ReplicatedWorldActorLocalBinding binding;
        binding.actor.valid = true;
        binding.actor.actor_address = entry.second;
        binding.actor.object_type_id = native_type_id;
        binding.network_actor_id = entry.first;

        DWORD exception_code = 0;
        if (RemoveReplicatedSharedHubActor(binding, &exception_code)) {
            Log(
                "world_snapshot: unregistered replicated hub actor for scene switch. reason=" +
                std::string(reason != nullptr ? reason : "unknown") +
                " actor=" + HexString(entry.second) +
                " network_actor_id=" + std::to_string(entry.first));
        } else {
            Log(
                "world_snapshot: failed to unregister replicated hub actor for scene switch. reason=" +
                std::string(reason != nullptr ? reason : "unknown") +
                " actor=" + HexString(entry.second) +
                " network_actor_id=" + std::to_string(entry.first) +
                " seh=" + HexString(exception_code));
        }
        UnbindReplicatedSharedHubActor(entry.first, entry.second);
    }

    ClearReplicatedSharedHubActorBindings();
    g_replicated_created_hub_scene_epoch = 0;
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
    return true;
}

void MaybeQueueRunLifecycleForRemoteAuthority(std::uint64_t now_ms) {
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
    (void)TryQueueClientRunLifecycle(now_ms, "world_snapshot");
}

std::uint32_t CountAuthoritativeWorldActorsForScene(
    const multiplayer::WorldSnapshotRuntimeInfo& snapshot) {
    std::uint32_t count = 0;
    for (const auto& authoritative_actor : snapshot.actors) {
        if (ShouldUseAuthoritativeWorldActorForScene(authoritative_actor, snapshot.scene_intent.kind)) {
            count += 1;
        }
    }
    return count;
}

void MaybeCatchUpRunEnemyPoolForAuthoritativeSnapshot(
    const multiplayer::WorldSnapshotRuntimeInfo& snapshot,
    std::uint32_t local_actor_count) {
    if (snapshot.scene_intent.kind != multiplayer::ParticipantSceneIntentKind::Run ||
        snapshot.truncated) {
        return;
    }

    const auto authoritative_actor_count = CountAuthoritativeWorldActorsForScene(snapshot);
    if (authoritative_actor_count <= local_actor_count) {
        return;
    }

    (void)TryAccelerateRunLifecycleEnemyPoolForSnapshot(authoritative_actor_count - local_actor_count);
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

    auto choose_binding = [&](bool require_enemy_type) -> bool {
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
            BindReplicatedRunActor(authoritative_actor.network_actor_id, binding.actor.actor_address);
            binding.network_actor_id = authoritative_actor.network_actor_id;
            if (binding_index_out != nullptr) {
                *binding_index_out = index;
            }
            return true;
        }
        return false;
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
    MaybeCatchUpRunEnemyPoolForAuthoritativeSnapshot(snapshot, counts.local_actor_count);

    std::unordered_map<std::uint64_t, std::size_t> local_by_network_id;
    local_by_network_id.reserve(local_bindings.size());
    for (std::size_t index = 0; index < local_bindings.size(); ++index) {
        if (local_bindings[index].network_actor_id != 0) {
            local_by_network_id.emplace(local_bindings[index].network_actor_id, index);
        }
    }

    std::unordered_map<std::uint32_t, std::uint32_t> authoritative_type_counts;
    std::unordered_set<std::uint64_t> authoritative_ids;
    authoritative_type_counts.reserve(snapshot.actors.size());
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
        authoritative_type_counts[authoritative_actor.native_type_id] += 1;

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
        if (snapshot.scene_intent.kind == multiplayer::ParticipantSceneIntentKind::Run &&
            ApplyReplicatedRunEnemyHealth(binding.actor.actor_address, authoritative_actor)) {
            counts.health_write_count += 1;
        }
        RecordWorldSnapshotBinding(&counts, authoritative_actor, binding.actor.actor_address, true, false);
    }

    if (snapshot_may_be_complete &&
        (snapshot.scene_intent.kind != multiplayer::ParticipantSceneIntentKind::SharedHub ||
         can_mutate_shared_hub_actors)) {
        std::uint32_t park_index = 0;
        for (auto& binding : local_bindings) {
            if (binding.matched) {
                continue;
            }
            if (snapshot.scene_intent.kind == multiplayer::ParticipantSceneIntentKind::Run) {
                const bool bound_to_missing_authority =
                    binding.network_actor_id != 0 &&
                    authoritative_ids.find(binding.network_actor_id) == authoritative_ids.end();
                const bool unbound_extra_for_replicated_type =
                    binding.network_actor_id == 0 &&
                    authoritative_type_counts.find(binding.actor.object_type_id) != authoritative_type_counts.end();
                const bool should_park = bound_to_missing_authority || unbound_extra_for_replicated_type;
                if (!should_park) {
                    continue;
                }
                if (ParkReplicatedWorldActor(binding.actor.actor_address, ++park_index)) {
                    binding.parked = true;
                    counts.parked_actor_count += 1;
                    RecordWorldSnapshotBinding(&counts, binding, false, true);
                    UnbindReplicatedRunActor(binding.network_actor_id, binding.actor.actor_address);
                    binding.network_actor_id = 0;
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
