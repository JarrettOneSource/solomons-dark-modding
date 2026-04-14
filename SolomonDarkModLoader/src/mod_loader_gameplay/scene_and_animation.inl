void RecordGameplayMouseLeftEdge() {
    g_gameplay_keyboard_injection.mouse_left_edge_tick_ms.store(
        static_cast<std::uint64_t>(GetTickCount64()),
        std::memory_order_release);
    g_gameplay_keyboard_injection.mouse_left_edge_serial.fetch_add(1, std::memory_order_acq_rel);
}

std::string NormalizeInjectedKeyName(std::string_view value) {
    std::string normalized;
    normalized.reserve(value.size());
    for (char raw : value) {
        const auto ch = static_cast<unsigned char>(raw);
        if (std::isspace(ch) || ch == '_' || ch == '-') {
            continue;
        }
        normalized.push_back(static_cast<char>(std::tolower(ch)));
    }
    return normalized;
}

bool TryResolveInjectedBindingGlobal(std::string_view binding_name, uintptr_t* absolute_global) {
    if (absolute_global == nullptr) {
        return false;
    }

    const auto normalized = NormalizeInjectedKeyName(binding_name);
    if (normalized == "menu" || normalized == "pause" || normalized == "escape") {
        *absolute_global = kMenuKeybindingGlobal;
        return true;
    }
    if (normalized == "inventory" || normalized == "inv") {
        *absolute_global = kInventoryKeybindingGlobal;
        return true;
    }
    if (normalized == "skills" || normalized == "skill") {
        *absolute_global = kSkillsKeybindingGlobal;
        return true;
    }
    if (normalized.size() == 9 && normalized.rfind("beltslot", 0) == 0) {
        const auto slot_char = normalized[8];
        if (slot_char >= '1' && slot_char <= '8') {
            *absolute_global = kBeltSlotKeybindingGlobals[static_cast<std::size_t>(slot_char - '1')];
            return true;
        }
    }
    if (normalized.size() == 5 && normalized.rfind("slot", 0) == 0) {
        const auto slot_char = normalized[4];
        if (slot_char >= '1' && slot_char <= '8') {
            *absolute_global = kBeltSlotKeybindingGlobals[static_cast<std::size_t>(slot_char - '1')];
            return true;
        }
    }

    return false;
}

bool TryReadInjectedBindingCode(uintptr_t absolute_global, std::uint32_t* raw_binding_code) {
    if (raw_binding_code == nullptr) {
        return false;
    }

    const auto resolved = ProcessMemory::Instance().ResolveGameAddressOrZero(absolute_global);
    if (resolved == 0) {
        return false;
    }

    std::uint32_t raw = 0;
    if (!ProcessMemory::Instance().TryReadValue(resolved, &raw)) {
        return false;
    }

    *raw_binding_code = raw;
    return true;
}

bool TryReadResolvedGamePointerAbsolute(uintptr_t absolute_address, uintptr_t* value) {
    if (value == nullptr) {
        return false;
    }

    *value = 0;
    const auto resolved = ProcessMemory::Instance().ResolveGameAddressOrZero(absolute_address);
    return resolved != 0 && ProcessMemory::Instance().TryReadValue(resolved, value);
}

bool TryResolveCurrentGameplayScene(uintptr_t* scene_address) {
    if (scene_address == nullptr) {
        return false;
    }

    *scene_address = 0;
    return TryReadResolvedGamePointerAbsolute(kGameObjectGlobal, scene_address) && *scene_address != 0;
}

bool TryResolveArena(uintptr_t* arena_address) {
    if (arena_address == nullptr) {
        return false;
    }

    *arena_address = 0;
    return TryReadResolvedGamePointerAbsolute(kArenaGlobal, arena_address) && *arena_address != 0;
}

int ReadResolvedGlobalIntOr(uintptr_t absolute_address, int fallback = 0) {
    const auto resolved = ProcessMemory::Instance().ResolveGameAddressOrZero(absolute_address);
    return ProcessMemory::Instance().ReadValueOr<int>(resolved, fallback);
}

bool TryWriteResolvedGlobalInt(uintptr_t absolute_address, int value) {
    const auto resolved = ProcessMemory::Instance().ResolveGameAddressOrZero(absolute_address);
    return resolved != 0 && ProcessMemory::Instance().TryWriteValue(resolved, value);
}

bool TryResolveGameplayIndexState(uintptr_t* table_address, int* entry_count) {
    if (table_address != nullptr) {
        *table_address = 0;
    }
    if (entry_count != nullptr) {
        *entry_count = 0;
    }

    uintptr_t resolved_table_address = 0;
    if (!TryReadResolvedGamePointerAbsolute(kGameplayIndexStateTableGlobal, &resolved_table_address) ||
        resolved_table_address == 0) {
        return false;
    }

    const auto resolved_entry_count = ReadResolvedGlobalIntOr(kGameplayIndexStateCountGlobal, 0);
    if (resolved_entry_count <= 0) {
        return false;
    }

    if (table_address != nullptr) {
        *table_address = resolved_table_address;
    }
    if (entry_count != nullptr) {
        *entry_count = resolved_entry_count;
    }
    return true;
}

bool TryReadGameplayIndexStateValue(int index, int* value) {
    if (value == nullptr || index < 0) {
        return false;
    }

    *value = 0;
    uintptr_t table_address = 0;
    int entry_count = 0;
    if (!TryResolveGameplayIndexState(&table_address, &entry_count) || table_address == 0 || index >= entry_count) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    return memory.TryReadValue(table_address + static_cast<uintptr_t>(index) * sizeof(int), value);
}

bool TryWriteGameplaySelectionStateForSlot(
    int slot_index,
    int selection_state,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (slot_index < 0 || slot_index >= static_cast<int>(kGameplayPlayerSlotCount)) {
        if (error_message != nullptr) {
            *error_message = "Gameplay selection-state prime received an invalid slot index.";
        }
        return false;
    }

    uintptr_t table_address = 0;
    int entry_count = 0;
    if (!TryResolveGameplayIndexState(&table_address, &entry_count) || table_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Gameplay index-state table is unavailable.";
        }
        return false;
    }

    const auto table_index =
        static_cast<int>(kGameplayIndexStateActorSelectionBaseIndex) + slot_index;
    if (table_index < 0 || table_index >= entry_count) {
        if (error_message != nullptr) {
            *error_message =
                "Gameplay index-state table is too small for slot selection writes.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto table_entry_address =
        table_address + static_cast<uintptr_t>(table_index) * sizeof(std::int32_t);
    if (!memory.TryWriteValue(table_entry_address, static_cast<std::int32_t>(selection_state))) {
        if (error_message != nullptr) {
            *error_message = "Failed to write the slot animation-selection entry.";
        }
        return false;
    }

    uintptr_t selection_global = 0;
    if (slot_index == 0) {
        selection_global = kPlayerSelectionState0Global;
    } else if (slot_index == 1) {
        selection_global = kPlayerSelectionState1Global;
    }

    if (selection_global != 0 &&
        !TryWriteResolvedGlobalInt(selection_global, static_cast<std::int32_t>(selection_state))) {
        if (error_message != nullptr) {
            *error_message = "Failed to write the slot selection-state global.";
        }
        return false;
    }

    return true;
}

bool TryResolveGameplayRegionObject(uintptr_t gameplay_address, int region_index, uintptr_t* region_address) {
    if (region_address == nullptr || gameplay_address == 0 || region_index < 0 ||
        region_index >= static_cast<int>(kGameplayPlayerSlotCount + 2)) {
        return false;
    }

    *region_address = 0;
    auto& memory = ProcessMemory::Instance();
    return memory.TryReadField(
               gameplay_address,
               kGameplayRegionTableOffset + static_cast<std::size_t>(region_index) * kGameplayRegionStride,
               region_address) &&
           *region_address != 0;
}

bool TryReadGameplayRegionTypeId(uintptr_t gameplay_address, int region_index, int* region_type_id) {
    if (region_type_id == nullptr) {
        return false;
    }

    *region_type_id = -1;
    uintptr_t region_address = 0;
    if (!TryResolveGameplayRegionObject(gameplay_address, region_index, &region_address) || region_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    return memory.TryReadField(region_address, kRegionObjectTypeIdOffset, region_type_id);
}

bool IsShopRegionType(int region_type_id) {
    switch (region_type_id) {
    case kSceneTypeMemorator:
    case kSceneTypeDowser:
    case kSceneTypeLibrarian:
    case kSceneTypePolisherArch:
        return true;
    default:
        return false;
    }
}

std::string DescribeRegionNameByType(int region_type_id) {
    switch (region_type_id) {
    case kSceneTypeHub:
        return "hub";
    case kSceneTypeMemorator:
        return "memorator";
    case kSceneTypeDowser:
        return "dowser";
    case kSceneTypeLibrarian:
        return "librarian";
    case kSceneTypePolisherArch:
        return "polisher_arch";
    case kSceneTypeArena:
        return "testrun";
    default:
        return std::string();
    }
}

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

bool HasBotMaterializedSceneChanged(const BotEntityBinding& binding, const SceneContextSnapshot& scene_context) {
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

void UpdateBotHomeScene(BotEntityBinding* binding, const SceneContextSnapshot& scene_context) {
    if (binding == nullptr || scene_context.world_address == 0) {
        return;
    }

    if (scene_context.current_region_index == kArenaRegionIndex || scene_context.region_type_id == kSceneTypeArena) {
        return;
    }

    if (scene_context.current_region_index >= 0) {
        binding->home_region_index = scene_context.current_region_index;
    }
    if (scene_context.region_type_id >= 0) {
        binding->home_region_type_id = scene_context.region_type_id;
    }
}

bool ShouldBotBeMaterializedInScene(const BotEntityBinding& binding, const SceneContextSnapshot& scene_context) {
    if (scene_context.world_address == 0) {
        return false;
    }

    if (scene_context.current_region_index == kArenaRegionIndex || scene_context.region_type_id == kSceneTypeArena) {
        return true;
    }

    const bool have_home_region_index = binding.home_region_index >= 0;
    const bool have_home_region_type_id = binding.home_region_type_id >= 0;
    if (!have_home_region_index && !have_home_region_type_id) {
        return true;
    }

    const bool region_matches =
        have_home_region_index &&
        scene_context.current_region_index >= 0 &&
        binding.home_region_index == scene_context.current_region_index;
    const bool type_matches =
        have_home_region_type_id &&
        scene_context.region_type_id >= 0 &&
        binding.home_region_type_id == scene_context.region_type_id;
    return region_matches || type_matches;
}

int ResolveActorAnimationStateSlotIndex(uintptr_t actor_address) {
    if (actor_address == 0) {
        return -1;
    }

    const auto slot = ProcessMemory::Instance().ReadFieldOr<std::int8_t>(actor_address, kActorSlotOffset, -1);
    if (slot < 0) {
        return -1;
    }

    return static_cast<int>(slot) + kActorAnimationStateSlotBias;
}

bool TryResolveActorAnimationStateSlotAddress(uintptr_t actor_address, uintptr_t* slot_address) {
    if (slot_address == nullptr) {
        return false;
    }

    *slot_address = 0;
    const auto slot_index = ResolveActorAnimationStateSlotIndex(actor_address);
    if (slot_index < 0) {
        return false;
    }

    const auto entry_count = ReadResolvedGlobalIntOr(kGameplayIndexStateCountGlobal, 0);
    if (entry_count <= slot_index) {
        return false;
    }

    const auto table_address =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kGameplayIndexStateTableGlobal);
    if (table_address == 0) {
        return false;
    }

    *slot_address = table_address + static_cast<uintptr_t>(slot_index) * sizeof(int);
    return true;
}

int ResolveActorAnimationStateId(uintptr_t actor_address) {
    if (actor_address == 0) {
        return kUnknownAnimationStateId;
    }

    auto& memory = ProcessMemory::Instance();
    const auto state_pointer = memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0);
    if (state_pointer != 0) {
        return memory.ReadValueOr<int>(state_pointer, kUnknownAnimationStateId);
    }

    uintptr_t slot_address = 0;
    if (!TryResolveActorAnimationStateSlotAddress(actor_address, &slot_address) || slot_address == 0) {
        return kUnknownAnimationStateId;
    }

    return memory.ReadValueOr<int>(slot_address, kUnknownAnimationStateId);
}

bool TryResolvePlayerActorForSlot(uintptr_t gameplay_address, int slot_index, uintptr_t* actor_address);

int ResolveGameplayBaselineAnimationState() {
    uintptr_t gameplay_address = 0;
    uintptr_t local_actor_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) || gameplay_address == 0 ||
        !TryResolvePlayerActorForSlot(gameplay_address, 0, &local_actor_address) ||
        local_actor_address == 0) {
        return 0;
    }

    const auto state_id = ResolveActorAnimationStateId(local_actor_address);
    return state_id == kUnknownAnimationStateId ? 0 : state_id;
}

bool TryWriteActorAnimationStateIdDirect(uintptr_t actor_address, int state_id) {
    if (actor_address == 0 || state_id == kUnknownAnimationStateId) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto state_pointer = memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0);
    return state_pointer != 0 && memory.TryWriteValue<int>(state_pointer, state_id);
}

bool CaptureActorAnimationDriveProfile(
    uintptr_t actor_address,
    ObservedActorAnimationDriveProfile* profile) {
    if (actor_address == 0 || profile == nullptr) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (!memory.TryRead(
            actor_address + kActorAnimationConfigBlockOffset,
            profile->config_bytes.data(),
            profile->config_bytes.size())) {
        return false;
    }

    profile->valid = true;
    profile->walk_cycle_primary =
        memory.ReadFieldOr<float>(actor_address, kActorWalkCyclePrimaryOffset, 0.0f);
    profile->walk_cycle_secondary =
        memory.ReadFieldOr<float>(actor_address, kActorWalkCycleSecondaryOffset, 0.0f);
    profile->render_drive_stride =
        memory.ReadFieldOr<float>(actor_address, kActorRenderDriveStrideScaleOffset, 0.0f);
    profile->render_advance_rate =
        memory.ReadFieldOr<float>(actor_address, kActorRenderAdvanceRateOffset, 0.0f);
    return true;
}

bool ApplyActorAnimationDriveProfile(
    uintptr_t actor_address,
    const ObservedActorAnimationDriveProfile& profile) {
    if (actor_address == 0 || !profile.valid) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto config_written = memory.TryWrite(
        actor_address + kActorAnimationConfigBlockOffset,
        profile.config_bytes.data(),
        profile.config_bytes.size());
    if (!config_written) {
        return false;
    }

    (void)memory.TryWriteField(
        actor_address,
        kActorRenderAdvanceRateOffset,
        profile.render_advance_rate);
    return true;
}

void CaptureObservedPlayerAnimationDriveProfile(uintptr_t actor_address, bool moving_now) {
    ObservedActorAnimationDriveProfile profile;
    if (!CaptureActorAnimationDriveProfile(actor_address, &profile)) {
        return;
    }

    if (moving_now) {
        g_observed_moving_animation_profile = profile;
    } else {
        g_observed_idle_animation_profile = profile;
    }
}

const ObservedActorAnimationDriveProfile* SelectObservedAnimationDriveProfile(bool moving) {
    if (moving && g_observed_moving_animation_profile.valid) {
        return &g_observed_moving_animation_profile;
    }
    if (!moving && g_observed_idle_animation_profile.valid) {
        return &g_observed_idle_animation_profile;
    }
    if (g_observed_idle_animation_profile.valid) {
        return &g_observed_idle_animation_profile;
    }
    if (g_observed_moving_animation_profile.valid) {
        return &g_observed_moving_animation_profile;
    }
    return nullptr;
}

const ObservedActorAnimationDriveProfile* SelectStandaloneWizardAnimationDriveProfile(
    const BotEntityBinding* binding,
    bool moving) {
    if (binding == nullptr) {
        return nullptr;
    }

    const auto* idle_profile = &binding->standalone_idle_animation_drive_profile;
    const auto* moving_profile = &binding->standalone_moving_animation_drive_profile;
    if (moving && moving_profile->valid) {
        return moving_profile;
    }
    if (!moving && idle_profile->valid) {
        return idle_profile;
    }
    if (idle_profile->valid) {
        return idle_profile;
    }
    if (moving_profile->valid) {
        return moving_profile;
    }
    return nullptr;
}

void SeedStandaloneWizardAnimationDriveProfiles(BotEntityBinding* binding, uintptr_t actor_address) {
    if (binding == nullptr) {
        return;
    }

    binding->standalone_idle_animation_drive_profile = ObservedActorAnimationDriveProfile{};
    binding->standalone_moving_animation_drive_profile = ObservedActorAnimationDriveProfile{};

    ObservedActorAnimationDriveProfile actor_profile;
    if (CaptureActorAnimationDriveProfile(actor_address, &actor_profile)) {
        binding->standalone_idle_animation_drive_profile = actor_profile;
    } else if (g_observed_idle_animation_profile.valid) {
        binding->standalone_idle_animation_drive_profile = g_observed_idle_animation_profile;
    }

    if (g_observed_moving_animation_profile.valid) {
        binding->standalone_moving_animation_drive_profile = g_observed_moving_animation_profile;
    } else if (binding->standalone_idle_animation_drive_profile.valid) {
        binding->standalone_moving_animation_drive_profile =
            binding->standalone_idle_animation_drive_profile;
    } else if (g_observed_idle_animation_profile.valid) {
        binding->standalone_moving_animation_drive_profile = g_observed_idle_animation_profile;
    }

    if (!binding->standalone_idle_animation_drive_profile.valid &&
        binding->standalone_moving_animation_drive_profile.valid) {
        binding->standalone_idle_animation_drive_profile =
            binding->standalone_moving_animation_drive_profile;
    }
}

void ApplyStandaloneWizardAnimationDriveProfile(
    const BotEntityBinding* binding,
    uintptr_t actor_address,
    bool moving) {
    if (actor_address == 0) {
        return;
    }

    if (const auto* profile = SelectStandaloneWizardAnimationDriveProfile(binding, moving);
        profile != nullptr) {
        (void)ApplyActorAnimationDriveProfile(actor_address, *profile);
    }
}

void ApplyStandaloneWizardDynamicAnimationState(
    const BotEntityBinding* binding,
    uintptr_t actor_address) {
    if (binding == nullptr || actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    (void)memory.TryWriteField(actor_address, kActorWalkCyclePrimaryOffset, binding->dynamic_walk_cycle_primary);
    (void)memory.TryWriteField(actor_address, kActorWalkCycleSecondaryOffset, binding->dynamic_walk_cycle_secondary);
}

void SeedBotAnimationDriveProfile(uintptr_t source_actor_address, uintptr_t destination_actor_address) {
    if (source_actor_address == 0 || destination_actor_address == 0) {
        return;
    }

    ObservedActorAnimationDriveProfile profile;
    if (!CaptureActorAnimationDriveProfile(source_actor_address, &profile)) {
        return;
    }

    (void)ApplyActorAnimationDriveProfile(destination_actor_address, profile);
}

void ApplyActorAnimationDriveState(uintptr_t actor_address, bool moving) {
    if (actor_address == 0) {
        return;
    }

    if (const auto* observed_profile = SelectObservedAnimationDriveProfile(moving);
        observed_profile != nullptr) {
        (void)ApplyActorAnimationDriveProfile(actor_address, *observed_profile);
    }

    auto& memory = ProcessMemory::Instance();
    (void)memory.TryWriteField(
        actor_address,
        kActorAnimationDriveStateByteOffset,
        static_cast<std::uint8_t>(moving ? 1 : 0));

    if (!moving) {
        (void)memory.TryWriteField(actor_address, kActorAnimationMoveDurationTicksOffset, 0);
        return;
    }

    auto move_duration =
        memory.ReadFieldOr<std::int32_t>(actor_address, kActorAnimationMoveDurationTicksOffset, 0);
    if (move_duration < 1) {
        move_duration = 1;
    } else if (move_duration < (std::numeric_limits<std::int32_t>::max)()) {
        ++move_duration;
    }
    (void)memory.TryWriteField(actor_address, kActorAnimationMoveDurationTicksOffset, move_duration);
}

void ResetStandaloneWizardControlBrain(uintptr_t actor_address) {
    if (actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    const auto control_brain_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0);
    if (control_brain_address == 0) {
        return;
    }

    (void)memory.TryWriteValue<std::int8_t>(control_brain_address + kActorControlBrainTargetSlotOffset, -1);
    (void)memory.TryWriteValue<std::uint16_t>(
        control_brain_address + kActorControlBrainTargetHandleOffset,
        static_cast<std::uint16_t>(0xFFFF));
    (void)memory.TryWriteValue<int>(control_brain_address + kActorControlBrainRetargetTicksOffset, 0);
    (void)memory.TryWriteValue<int>(control_brain_address + kActorControlBrainActionCooldownTicksOffset, 0);
    (void)memory.TryWriteValue<int>(control_brain_address + kActorControlBrainActionBurstTicksOffset, 0);
    (void)memory.TryWriteValue<int>(control_brain_address + kActorControlBrainHeadingLockTicksOffset, 0);
    (void)memory.TryWriteValue<float>(control_brain_address + kActorControlBrainHeadingAccumulatorOffset, 0.0f);
    (void)memory.TryWriteValue<float>(control_brain_address + kActorControlBrainPursuitRangeOffset, 0.0f);
    (void)memory.TryWriteValue<std::uint8_t>(control_brain_address + kActorControlBrainFollowLeaderOffset, 0);
    (void)memory.TryWriteValue<float>(control_brain_address + kActorControlBrainDesiredFacingOffset, 0.0f);
    (void)memory.TryWriteValue<float>(
        control_brain_address + kActorControlBrainDesiredFacingSmoothedOffset,
        0.0f);
    (void)memory.TryWriteValue<float>(control_brain_address + kActorControlBrainMoveInputXOffset, 0.0f);
    (void)memory.TryWriteValue<float>(control_brain_address + kActorControlBrainMoveInputYOffset, 0.0f);
}

void ApplyStandaloneWizardPuppetDriveState(
    const BotEntityBinding* binding,
    uintptr_t actor_address,
    bool moving) {
    if (actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    const auto control_brain_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0);
    if (!moving) {
        (void)memory.TryWriteField(actor_address, kActorAnimationMoveDurationTicksOffset, 0);
    } else {
        auto move_duration =
            memory.ReadFieldOr<std::int32_t>(actor_address, kActorAnimationMoveDurationTicksOffset, 0);
        if (move_duration < 1) {
            move_duration = 1;
        } else if (move_duration < (std::numeric_limits<std::int32_t>::max)()) {
            ++move_duration;
        }
        (void)memory.TryWriteField(actor_address, kActorAnimationMoveDurationTicksOffset, move_duration);
    }

    ResetStandaloneWizardControlBrain(actor_address);
    if (control_brain_address == 0 || binding == nullptr || !moving) {
        return;
    }

    float move_input_x = binding->direction_x;
    float move_input_y = binding->direction_y;
    const auto magnitude = std::sqrt((move_input_x * move_input_x) + (move_input_y * move_input_y));
    if (magnitude > 0.0001f) {
        move_input_x /= magnitude;
        move_input_y /= magnitude;
    } else {
        move_input_x = 0.0f;
        move_input_y = 0.0f;
    }

    const auto desired_heading =
        binding->desired_heading_valid
            ? binding->desired_heading
            : memory.ReadFieldOr<float>(actor_address, kActorHeadingOffset, 0.0f);
    (void)memory.TryWriteValue<float>(control_brain_address + kActorControlBrainHeadingAccumulatorOffset, desired_heading);
    (void)memory.TryWriteValue<float>(control_brain_address + kActorControlBrainDesiredFacingOffset, desired_heading);
    (void)memory.TryWriteValue<float>(
        control_brain_address + kActorControlBrainDesiredFacingSmoothedOffset,
        desired_heading);
    (void)memory.TryWriteValue<float>(control_brain_address + kActorControlBrainMoveInputXOffset, move_input_x);
    (void)memory.TryWriteValue<float>(control_brain_address + kActorControlBrainMoveInputYOffset, move_input_y);
}

bool TryReadMemoryBlock(uintptr_t address, std::size_t size, std::vector<std::uint8_t>* bytes) {
    if (address == 0 || size == 0 || bytes == nullptr) {
        return false;
    }

    bytes->assign(size, 0);
    if (!ProcessMemory::Instance().TryRead(address, bytes->data(), size)) {
        bytes->clear();
        return false;
    }

    return true;
}

std::uint32_t HashMemoryBlockFNV1a32(uintptr_t address, std::size_t size) {
    if (address == 0 || size == 0) {
        return 0;
    }

    std::vector<std::uint8_t> bytes;
    if (!TryReadMemoryBlock(address, size, &bytes) || bytes.empty()) {
        return 0;
    }

    std::uint32_t hash = 2166136261u;
    for (const auto byte : bytes) {
        hash ^= static_cast<std::uint32_t>(byte);
        hash *= 16777619u;
    }
    return hash;
}

std::uint32_t FloatToBits(float value) {
    std::uint32_t bits = 0;
    std::memcpy(&bits, &value, sizeof(bits));
    return bits;
}

int ReadRoundedXpOrUnknown(uintptr_t progression_address) {
    if (progression_address == 0) {
        return kUnknownXpSentinel;
    }

    const auto xp = ProcessMemory::Instance().ReadFieldOr<float>(
        progression_address,
        kProgressionXpOffset,
        static_cast<float>(kUnknownXpSentinel));
    if (xp < 0.0f) {
        return kUnknownXpSentinel;
    }

    return static_cast<int>(std::lround(xp));
}

bool TryResolvePlayerActorForSlot(uintptr_t gameplay_address, int slot_index, uintptr_t* actor_address) {
    if (actor_address == nullptr || slot_index < 0 || slot_index >= static_cast<int>(kGameplayPlayerSlotCount)) {
        return false;
    }

    *actor_address = ProcessMemory::Instance().ReadFieldOr<uintptr_t>(
        gameplay_address,
        kGameplayPlayerActorOffset + static_cast<std::size_t>(slot_index) * kGameplayPlayerSlotStride,
        0);
    return *actor_address != 0;
}

bool TryResolvePlayerProgressionForSlot(uintptr_t gameplay_address, int slot_index, uintptr_t* progression_address) {
    if (progression_address == nullptr || slot_index < 0 || slot_index >= static_cast<int>(kGameplayPlayerSlotCount)) {
        return false;
    }

    *progression_address = 0;
    const auto handle = ProcessMemory::Instance().ReadFieldOr<uintptr_t>(
        gameplay_address,
        kGameplayPlayerProgressionHandleOffset + static_cast<std::size_t>(slot_index) * kGameplayPlayerSlotStride,
        0);
    if (handle == 0) {
        return false;
    }

    const auto progression = ReadSmartPointerInnerObject(handle);
    if (progression == 0) {
        return false;
    }

    *progression_address = progression;
    return true;
}

bool TryResolvePlayerProgressionHandleForSlot(uintptr_t gameplay_address, int slot_index, uintptr_t* handle_address) {
    if (handle_address == nullptr || slot_index < 0 || slot_index >= static_cast<int>(kGameplayPlayerSlotCount)) {
        return false;
    }

    *handle_address = 0;
    const auto handle = ProcessMemory::Instance().ReadFieldOr<uintptr_t>(
        gameplay_address,
        kGameplayPlayerProgressionHandleOffset + static_cast<std::size_t>(slot_index) * kGameplayPlayerSlotStride,
        0);
    if (handle == 0) {
        return false;
    }

    *handle_address = handle;
    return true;
}

bool TryValidateWizardBotSpawnReadiness(
    uintptr_t gameplay_address,
    SceneContextSnapshot* scene_context,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (scene_context != nullptr) {
        *scene_context = SceneContextSnapshot{};
    }
    if (gameplay_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Gameplay scene is not active.";
        }
        return false;
    }

    SceneContextSnapshot snapshot;
    if (!TryBuildSceneContextSnapshot(gameplay_address, &snapshot)) {
        if (error_message != nullptr) {
            *error_message = "Gameplay scene snapshot is unavailable.";
        }
        return false;
    }
    if (scene_context != nullptr) {
        *scene_context = snapshot;
    }
    if (snapshot.world_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Gameplay scene is transitioning.";
        }
        return false;
    }

    uintptr_t local_actor_address = 0;
    if (!TryResolvePlayerActorForSlot(gameplay_address, 0, &local_actor_address) ||
        local_actor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Local slot-0 player actor is not ready.";
        }
        return false;
    }

    return true;
}

void CopyPlayerProgressionVitals(uintptr_t source_progression_address, uintptr_t destination_progression_address) {
    if (source_progression_address == 0 || destination_progression_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    memory.TryWriteField(
        destination_progression_address,
        kProgressionLevelOffset,
        memory.ReadFieldOr<int>(source_progression_address, kProgressionLevelOffset, 0));
    memory.TryWriteField(
        destination_progression_address,
        kProgressionXpOffset,
        memory.ReadFieldOr<float>(source_progression_address, kProgressionXpOffset, 0.0f));
    memory.TryWriteField(
        destination_progression_address,
        kProgressionHpOffset,
        memory.ReadFieldOr<float>(source_progression_address, kProgressionHpOffset, 0.0f));
    memory.TryWriteField(
        destination_progression_address,
        kProgressionMaxHpOffset,
        memory.ReadFieldOr<float>(source_progression_address, kProgressionMaxHpOffset, 0.0f));
    memory.TryWriteField(
        destination_progression_address,
        kProgressionMpOffset,
        memory.ReadFieldOr<float>(source_progression_address, kProgressionMpOffset, 0.0f));
    memory.TryWriteField(
        destination_progression_address,
        kProgressionMaxMpOffset,
        memory.ReadFieldOr<float>(source_progression_address, kProgressionMaxMpOffset, 0.0f));
}

bool TryResolveActorProgressionRuntime(uintptr_t actor_address, uintptr_t* progression_address) {
    if (progression_address == nullptr) {
        return false;
    }

    *progression_address = 0;
    if (actor_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    auto resolved_progression_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionRuntimeStateOffset, 0);
    if (resolved_progression_address == 0) {
        const auto progression_handle =
            memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionHandleOffset, 0);
        if (progression_handle != 0) {
            resolved_progression_address = ReadSmartPointerInnerObject(progression_handle);
        }
    }

    if (resolved_progression_address == 0) {
        return false;
    }

    *progression_address = resolved_progression_address;
    return true;
}

bool TryResolveLocalPlayerWorldContext(
    uintptr_t gameplay_address,
    uintptr_t* actor_address,
    uintptr_t* progression_address,
    uintptr_t* world_address) {
    if (actor_address != nullptr) {
        *actor_address = 0;
    }
    if (progression_address != nullptr) {
        *progression_address = 0;
    }
    if (world_address != nullptr) {
        *world_address = 0;
    }
    if (gameplay_address == 0) {
        return false;
    }

    uintptr_t resolved_actor_address = 0;
    if (!TryResolvePlayerActorForSlot(gameplay_address, 0, &resolved_actor_address) || resolved_actor_address == 0) {
        (void)TryReadResolvedGamePointerAbsolute(kLocalPlayerActorGlobal, &resolved_actor_address);
        if (resolved_actor_address == 0) {
            return false;
        }
    }

    const auto resolved_world_address =
        ProcessMemory::Instance().ReadFieldOr<uintptr_t>(resolved_actor_address, kActorOwnerOffset, 0);
    if (resolved_world_address == 0) {
        return false;
    }

    if (actor_address != nullptr) {
        *actor_address = resolved_actor_address;
    }
    if (world_address != nullptr) {
        *world_address = resolved_world_address;
    }
    if (progression_address != nullptr) {
        if (!TryResolvePlayerProgressionForSlot(gameplay_address, 0, progression_address) ||
            *progression_address == 0) {
            if (!TryResolveActorProgressionRuntime(resolved_actor_address, progression_address)) {
                *progression_address = 0;
                return false;
            }
        }
    }

    return true;
}

bool ReserveWizardBotGameplaySlot(std::uint64_t bot_id, int* slot_index) {
    if (slot_index == nullptr) {
        return false;
    }

    std::lock_guard<std::recursive_mutex> lock(g_bot_entities_mutex);
    *slot_index = -1;
    if (auto* binding = FindBotEntity(bot_id); binding != nullptr && binding->gameplay_slot >= kFirstWizardBotSlot) {
        *slot_index = binding->gameplay_slot;
        return true;
    }

    for (int candidate = kFirstWizardBotSlot; candidate < static_cast<int>(kGameplayPlayerSlotCount); ++candidate) {
        if (FindBotEntityForGameplaySlot(candidate) == nullptr) {
            *slot_index = candidate;
            return true;
        }
    }

    return false;
}

bool SyncActorRegisteredSlotMirrorsFromCurrentIdentity(
    uintptr_t actor_address,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (actor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Actor registered-slot mirror sync requires a live actor.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (!memory.TryWriteField(
            actor_address,
            kActorRegisteredSlotMirrorOffset,
            static_cast<std::uint32_t>(0xFFFF00FF))) {
        if (error_message != nullptr) {
            *error_message = "Failed to clear actor registered-slot mirrors to the stock gameplay-slot sentinel.";
        }
        return false;
    }

    return true;
}

void PrimeGameplaySlotBotActor(
    uintptr_t gameplay_address,
    int slot_index,
    uintptr_t actor_address,
    uintptr_t progression_address,
    float x,
    float y,
    float heading) {
    if (gameplay_address == 0 || actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t local_actor_address = 0;
    uintptr_t local_progression_address = 0;
    (void)TryResolvePlayerActorForSlot(gameplay_address, 0, &local_actor_address);
    (void)TryResolvePlayerProgressionForSlot(gameplay_address, 0, &local_progression_address);
    const auto actor_slot_offset =
        kGameplayPlayerActorOffset + static_cast<std::size_t>(slot_index) * kGameplayPlayerSlotStride;
    const auto progression_slot_offset =
        kGameplayPlayerProgressionHandleOffset + static_cast<std::size_t>(slot_index) * kGameplayPlayerSlotStride;
    const auto log_prime_slot_state = [&](std::string_view label) {
        const auto slot_actor =
            memory.ReadFieldOr<uintptr_t>(gameplay_address, actor_slot_offset, 0);
        const auto slot_progression_wrapper =
            memory.ReadFieldOr<uintptr_t>(gameplay_address, progression_slot_offset, 0);
        const auto slot_progression_inner =
            ReadSmartPointerInnerObject(slot_progression_wrapper);
        const auto local_slot_actor =
            memory.ReadFieldOr<uintptr_t>(gameplay_address, kGameplayPlayerActorOffset, 0);
        const auto local_slot_progression_wrapper =
            memory.ReadFieldOr<uintptr_t>(gameplay_address, kGameplayPlayerProgressionHandleOffset, 0);
        const auto local_slot_progression_inner =
            ReadSmartPointerInnerObject(local_slot_progression_wrapper);
        Log(
            "[bots] prime_slot_actor " + std::string(label) +
            " gameplay=" + HexString(gameplay_address) +
            " slot=" + std::to_string(slot_index) +
            " slot_actor=" + HexString(slot_actor) +
            " slot_prog=" + HexString(slot_progression_wrapper) +
            " slot_prog_inner=" + HexString(slot_progression_inner) +
            " local_actor=" + HexString(local_slot_actor) +
            " local_prog=" + HexString(local_slot_progression_wrapper) +
            " local_prog_inner=" + HexString(local_slot_progression_inner) +
            " actor=" + HexString(actor_address) +
            " progression=" + HexString(progression_address));
    };
    log_prime_slot_state("enter");

    (void)memory.TryWriteField(actor_address, kActorPositionXOffset, x);
    (void)memory.TryWriteField(actor_address, kActorPositionYOffset, y);
    (void)memory.TryWriteField(actor_address, kActorHeadingOffset, heading);
    log_prime_slot_state("after_transform");

    if (local_actor_address != 0) {
        SeedBotAnimationDriveProfile(local_actor_address, actor_address);
        log_prime_slot_state("after_animation_seed");
    }

    if (local_progression_address != 0 && progression_address != 0) {
        CopyPlayerProgressionVitals(local_progression_address, progression_address);
        log_prime_slot_state("after_copy_vitals");
    }

    ApplyActorAnimationDriveState(actor_address, false);
    log_prime_slot_state("after_apply_anim_state");
}

int ResolveStandaloneWizardRenderSelectionIndex(int wizard_id) {
    return (std::max)(0, (std::min)(wizard_id, 4));
}

int ResolveStandaloneWizardSelectionState(int wizard_id) {
    // Stock create-screen point indices were originally labeled in the wrong
    // semantic order. The public wizard ids intentionally follow the user-
    // facing colors:
    //   fire=0x10, water=0x20, earth=0x28, air=0x18, ether=0x08.
    switch (ResolveStandaloneWizardRenderSelectionIndex(wizard_id)) {
    case 0:
        return 0x10;
    case 1:
        return 0x20;
    case 2:
        return 0x28;
    case 3:
        return 0x18;
    case 4:
        return 0x08;
    default:
        return kStandaloneWizardHiddenSelectionState;
    }
}

int ResolveProfileSelectionState(const multiplayer::MultiplayerCharacterProfile& character_profile) {
    return ResolveStandaloneWizardSelectionState(ResolveProfileElementId(character_profile));
}
