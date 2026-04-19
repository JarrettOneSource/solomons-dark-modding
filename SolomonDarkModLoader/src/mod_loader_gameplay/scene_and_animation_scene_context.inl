bool TryBuildSceneContextSnapshot(uintptr_t gameplay_address, SceneContextSnapshot* snapshot) {
    if (snapshot == nullptr || gameplay_address == 0) {
        return false;
    }

    *snapshot = SceneContextSnapshot{};
    snapshot->gameplay_scene_address = gameplay_address;
    (void)TryResolveArena(&snapshot->arena_address);
    uintptr_t local_actor_address = 0;
    (void)TryResolveLocalPlayerWorldContext(
        gameplay_address,
        &local_actor_address,
        nullptr,
        &snapshot->world_address);
    (void)TryResolveGameplayIndexState(&snapshot->region_state_address, nullptr);
    (void)TryReadGameplayIndexStateValue(0, &snapshot->current_region_index);
    if (snapshot->current_region_index >= 0) {
        (void)TryReadGameplayRegionTypeId(gameplay_address, snapshot->current_region_index, &snapshot->region_type_id);
    }
    return true;
}

std::string DescribeSceneKind(const SceneContextSnapshot& snapshot) {
    if (snapshot.world_address == 0) {
        return "transition";
    }
    if (snapshot.region_type_id == kSceneTypeHub || snapshot.current_region_index == kHubRegionIndex) {
        return "hub";
    }
    if (snapshot.region_type_id == kSceneTypeArena || snapshot.current_region_index == kArenaRegionIndex) {
        return "arena";
    }
    if (IsShopRegionType(snapshot.region_type_id)) {
        return "shop";
    }
    return "region";
}

std::string DescribeSceneName(const SceneContextSnapshot& snapshot) {
    if (snapshot.world_address == 0) {
        return "transition";
    }

    const auto typed_name = DescribeRegionNameByType(snapshot.region_type_id);
    if (!typed_name.empty()) {
        return typed_name;
    }
    if (snapshot.current_region_index == kHubRegionIndex) {
        return "hub";
    }
    if (snapshot.current_region_index == kArenaRegionIndex) {
        return "testrun";
    }
    if (snapshot.current_region_index >= 0) {
        return "region_" + std::to_string(snapshot.current_region_index);
    }
    return "gameplay";
}

bool HasBotMaterializedSceneChanged(const ParticipantEntityBinding& binding, const SceneContextSnapshot& scene_context) {
    const bool scene_changed =
        binding.materialized_scene_address != 0 &&
        scene_context.gameplay_scene_address != 0 &&
        binding.materialized_scene_address != scene_context.gameplay_scene_address;
    const bool world_changed =
        binding.materialized_world_address != 0 &&
        scene_context.world_address != 0 &&
        binding.materialized_world_address != scene_context.world_address;
    const bool region_changed =
        binding.materialized_region_index >= 0 &&
        scene_context.current_region_index >= 0 &&
        binding.materialized_region_index != scene_context.current_region_index;

    return scene_changed || world_changed || region_changed;
}

bool IsSharedHubSceneContext(const SceneContextSnapshot& scene_context) {
    return scene_context.current_region_index == kHubRegionIndex || scene_context.region_type_id == kSceneTypeHub;
}

bool IsArenaSceneContext(const SceneContextSnapshot& scene_context) {
    return scene_context.current_region_index == kArenaRegionIndex || scene_context.region_type_id == kSceneTypeArena;
}

bool ShouldBotBeMaterializedInScene(const ParticipantEntityBinding& binding, const SceneContextSnapshot& scene_context) {
    if (scene_context.world_address == 0) {
        return false;
    }

    switch (binding.scene_intent.kind) {
    case multiplayer::ParticipantSceneIntentKind::Run:
        return IsArenaSceneContext(scene_context);
    case multiplayer::ParticipantSceneIntentKind::SharedHub:
        return IsSharedHubSceneContext(scene_context);
    case multiplayer::ParticipantSceneIntentKind::PrivateRegion: {
        const bool region_matches =
            binding.scene_intent.region_index >= 0 &&
            scene_context.current_region_index >= 0 &&
            binding.scene_intent.region_index == scene_context.current_region_index;
        const bool type_matches =
            binding.scene_intent.region_type_id >= 0 &&
            scene_context.region_type_id >= 0 &&
            binding.scene_intent.region_type_id == scene_context.region_type_id;
        return region_matches || type_matches;
    }
    }
    return false;
}

