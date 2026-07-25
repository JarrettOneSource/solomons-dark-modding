constexpr std::uint32_t kGoodImpHostileTargetTypeId = 0x03ED;
constexpr std::uint32_t kLeviathanHostileTargetTypeId = 0x07F2;
constexpr std::uint32_t kGolemHostileTargetTypeId = 0x07F4;
constexpr std::int32_t kMaximumNativeHostileTargetCandidates = 512;
constexpr std::uint64_t kHostileTargetSidecarRefreshIntervalMs = 100;
constexpr std::uint64_t kHostileTargetNearestMaintenanceIntervalMs = 100;
constexpr std::uint64_t kHostileTargetDeathMaintenanceMaxMs = 30000;
constexpr std::uint64_t kHostileTargetLocalDeathFallbackMs = 1500;

struct HostileTargetSelection {
    bool valid = false;
    uintptr_t actor_address = 0;
    std::uint32_t native_type_id = 0;
    std::int32_t actor_group = -1;
    std::int32_t world_slot = -1;
    float distance_squared = (std::numeric_limits<float>::max)();
};

struct HostileTargetSidecarCache {
    uintptr_t world_address = 0;
    std::uint64_t refresh_not_before_ms = 0;
    std::vector<uintptr_t> actor_addresses;
};

struct HostileTargetDeathMaintenance {
    std::uint64_t expires_at_ms = 0;
    std::uint64_t local_death_fallback_at_ms = 0;
    bool awaiting_local_native_death_transition = false;
    std::unordered_set<uintptr_t> hostile_actor_addresses;
};

HostileTargetSidecarCache g_hostile_target_sidecar_cache;
std::uint64_t g_hostile_target_nearest_maintenance_not_before_ms = 0;
std::unordered_set<uintptr_t> g_hostile_target_dead_participant_actors;
std::unordered_map<uintptr_t, HostileTargetDeathMaintenance>
    g_hostile_target_death_maintenance;
std::unordered_map<uintptr_t, uintptr_t>
    g_last_logged_hostile_target_by_actor;

std::uint64_t ResolveHostileTargetParticipantId(uintptr_t actor_address);

bool IsExplicitPlayerOwnedHostileTargetType(std::uint32_t native_type_id) {
    return native_type_id == kGoodImpHostileTargetTypeId ||
           native_type_id == kLeviathanHostileTargetTypeId ||
           native_type_id == kGolemHostileTargetTypeId;
}

bool IsDeadWizardParticipantActor(uintptr_t actor_address) {
    if (g_hostile_target_dead_participant_actors.find(actor_address) !=
        g_hostile_target_dead_participant_actors.end()) {
        return true;
    }
    std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
    const auto* binding = FindParticipantEntityForActor(actor_address);
    return binding != nullptr &&
           IsWizardParticipantKind(binding->kind) &&
           binding->native_remote_death_epoch_active;
}

bool TryReadNativeHostileTargetCandidateList(
    uintptr_t gameplay_address,
    std::vector<uintptr_t>* actor_addresses) {
    if (gameplay_address == 0 ||
        actor_addresses == nullptr ||
        kGameplayHostileTargetCandidateListOffset == 0 ||
        kPointerListCountOffset == 0 ||
        kPointerListItemsOffset == 0) {
        return false;
    }

    const auto list_address =
        gameplay_address + kGameplayHostileTargetCandidateListOffset;
    auto& memory = ProcessMemory::Instance();
    std::int32_t count = 0;
    uintptr_t items_address = 0;
    if (!memory.TryReadField(
            list_address,
            kPointerListCountOffset,
            &count) ||
        count < 0 ||
        count > kMaximumNativeHostileTargetCandidates ||
        !memory.TryReadField(
            list_address,
            kPointerListItemsOffset,
            &items_address) ||
        (count > 0 &&
         (items_address == 0 ||
          !memory.IsReadableRange(
              items_address,
              static_cast<std::size_t>(count) * sizeof(uintptr_t))))) {
        return false;
    }

    for (std::int32_t index = 0; index < count; ++index) {
        uintptr_t actor_address = 0;
        if (memory.TryReadValue(
                items_address +
                    static_cast<std::size_t>(index) * sizeof(uintptr_t),
                &actor_address) &&
            actor_address != 0) {
            actor_addresses->push_back(actor_address);
        }
    }
    return true;
}

void AppendWizardParticipantTargetCandidates(
    uintptr_t gameplay_address,
    std::vector<uintptr_t>* actor_addresses) {
    if (gameplay_address == 0 || actor_addresses == nullptr) {
        return;
    }

    uintptr_t local_actor_address = 0;
    if (TryResolvePlayerActorForSlot(
            gameplay_address,
            0,
            &local_actor_address) &&
        local_actor_address != 0) {
        actor_addresses->push_back(local_actor_address);
    }

    std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
    for (const auto& binding : g_participant_entities) {
        if (!IsWizardParticipantKind(binding.kind) ||
            binding.actor_address == 0 ||
            binding.native_remote_death_epoch_active ||
            (binding.materialized_scene_address != 0 &&
             binding.materialized_scene_address != gameplay_address)) {
            continue;
        }
        actor_addresses->push_back(binding.actor_address);
    }
}

void ReplacePlayerOwnedHostileTargetSidecars(
    uintptr_t world_address,
    std::uint64_t now_ms,
    const std::vector<SDModSceneActorState>& actors) {
    HostileTargetSidecarCache next;
    next.world_address = world_address;
    next.refresh_not_before_ms =
        now_ms + kHostileTargetSidecarRefreshIntervalMs;
    for (const auto& actor : actors) {
        if (actor.valid &&
            actor.actor_address != 0 &&
            actor.owner_address == world_address &&
            IsExplicitPlayerOwnedHostileTargetType(actor.object_type_id)) {
            next.actor_addresses.push_back(actor.actor_address);
        }
    }
    g_hostile_target_sidecar_cache = std::move(next);
}

void RefreshPlayerOwnedHostileTargetSidecars(
    uintptr_t world_address,
    std::uint64_t now_ms) {
    if (world_address == 0) {
        g_hostile_target_sidecar_cache = HostileTargetSidecarCache{};
        return;
    }
    if (g_hostile_target_sidecar_cache.world_address == world_address &&
        now_ms < g_hostile_target_sidecar_cache.refresh_not_before_ms) {
        return;
    }

    std::vector<SDModSceneActorState> actors;
    if (!TryListSceneActors(&actors)) {
        if (g_hostile_target_sidecar_cache.world_address != world_address) {
            g_hostile_target_sidecar_cache = HostileTargetSidecarCache{};
        }
        return;
    }
    ReplacePlayerOwnedHostileTargetSidecars(
        world_address,
        now_ms,
        actors);
}

bool TryValidateHostileTargetCandidate(
    uintptr_t hostile_actor_address,
    uintptr_t hostile_world_address,
    float hostile_x,
    float hostile_y,
    uintptr_t candidate_actor_address,
    uintptr_t excluded_actor_address,
    HostileTargetSelection* selection) {
    if (selection == nullptr ||
        candidate_actor_address == 0 ||
        candidate_actor_address == hostile_actor_address ||
        candidate_actor_address == excluded_actor_address ||
        hostile_world_address == 0 ||
        kActorHostileTargetIneligibleStateOffset == 0 ||
        kActorWorldRegionIndexOffset == 0 ||
        kActorWorldBucketTableOffset == 0 ||
        kActorWorldBucketStride == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    std::uint8_t ineligible_state = 0;
    if (!memory.TryReadField(
            candidate_actor_address,
            kActorHostileTargetIneligibleStateOffset,
            &ineligible_state) ||
        ineligible_state != 0 ||
        IsActorRuntimeDead(candidate_actor_address) ||
        IsDeadWizardParticipantActor(candidate_actor_address)) {
        return false;
    }

    uintptr_t candidate_world_address = 0;
    std::int32_t candidate_actor_group = -1;
    std::int32_t candidate_world_slot = -1;
    if (!TryReadActorWorldTargetSlotState(
            candidate_actor_address,
            &candidate_world_address,
            &candidate_actor_group,
            &candidate_world_slot) ||
        candidate_world_address != hostile_world_address) {
        return false;
    }

    const auto bucket_index =
        static_cast<std::uint64_t>(candidate_actor_group) *
            static_cast<std::uint64_t>(kActorWorldBucketStride) +
        static_cast<std::uint64_t>(candidate_world_slot);
    if (bucket_index >
        ((std::numeric_limits<uintptr_t>::max)() -
         hostile_world_address -
         kActorWorldBucketTableOffset) /
            sizeof(uintptr_t)) {
        return false;
    }

    uintptr_t bucket_actor_address = 0;
    const auto bucket_address =
        hostile_world_address +
        kActorWorldBucketTableOffset +
        static_cast<uintptr_t>(bucket_index) * sizeof(uintptr_t);
    if (!memory.TryReadValue(bucket_address, &bucket_actor_address) ||
        bucket_actor_address != candidate_actor_address) {
        return false;
    }

    std::uint32_t native_type_id = 0;
    (void)memory.TryReadField(
        candidate_actor_address,
        kGameObjectTypeIdOffset,
        &native_type_id);
    const bool extended_slot_or_ally_candidate =
        ResolveHostileTargetParticipantId(candidate_actor_address) != 0 ||
        IsExplicitPlayerOwnedHostileTargetType(native_type_id);
    std::int16_t world_region_index = -1;
    int mapped_region_index = -1;
    if (!memory.TryReadField(
            hostile_world_address,
            kActorWorldRegionIndexOffset,
            &world_region_index) ||
        !TryReadGameplayIndexStateValue(
            candidate_actor_group,
            &mapped_region_index)) {
        return false;
    }
    if (mapped_region_index != static_cast<int>(world_region_index) &&
        !extended_slot_or_ally_candidate) {
        return false;
    }

    float candidate_x = 0.0f;
    float candidate_y = 0.0f;
    if (!TryReadFiniteFloatField(
            candidate_actor_address,
            kActorPositionXOffset,
            &candidate_x) ||
        !TryReadFiniteFloatField(
            candidate_actor_address,
            kActorPositionYOffset,
            &candidate_y)) {
        return false;
    }
    const float delta_x = hostile_x - candidate_x;
    const float delta_y = hostile_y - candidate_y;
    const float distance_squared =
        delta_x * delta_x + delta_y * delta_y;
    if (!std::isfinite(distance_squared)) {
        return false;
    }

    selection->valid = true;
    selection->actor_address = candidate_actor_address;
    selection->native_type_id = native_type_id;
    selection->actor_group = candidate_actor_group;
    selection->world_slot = candidate_world_slot;
    selection->distance_squared = distance_squared;
    return true;
}

bool IsPreferredHostileTargetCandidate(
    const HostileTargetSelection& candidate,
    const HostileTargetSelection& current) {
    if (!candidate.valid) {
        return false;
    }
    if (!current.valid ||
        candidate.distance_squared < current.distance_squared) {
        return true;
    }
    if (candidate.distance_squared != current.distance_squared) {
        return false;
    }
    if (candidate.actor_group != current.actor_group) {
        return candidate.actor_group < current.actor_group;
    }
    if (candidate.world_slot != current.world_slot) {
        return candidate.world_slot < current.world_slot;
    }
    return candidate.native_type_id < current.native_type_id;
}

void LogRejectedExtendedHostileTargetCandidate(
    uintptr_t hostile_actor_address,
    uintptr_t hostile_world_address,
    uintptr_t candidate_actor_address) {
    static std::uint64_t s_last_diagnostic_ms = 0;
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    if (now_ms - s_last_diagnostic_ms < 250) {
        return;
    }

    if (candidate_actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    std::uint32_t native_type_id = 0;
    const bool have_native_type = memory.TryReadField(
        candidate_actor_address,
        kGameObjectTypeIdOffset,
        &native_type_id);
    const auto participant_id =
        ResolveHostileTargetParticipantId(candidate_actor_address);
    if (participant_id == 0 &&
        (!have_native_type ||
         !IsExplicitPlayerOwnedHostileTargetType(native_type_id))) {
        return;
    }
    s_last_diagnostic_ms = now_ms;

    std::uint8_t ineligible_state = 0xFF;
    const bool have_ineligible_state = memory.TryReadField(
        candidate_actor_address,
        kActorHostileTargetIneligibleStateOffset,
        &ineligible_state);
    uintptr_t candidate_world_address = 0;
    std::int32_t candidate_actor_group = -1;
    std::int32_t candidate_world_slot = -1;
    const bool have_target_slot_state =
        TryReadActorWorldTargetSlotState(
            candidate_actor_address,
            &candidate_world_address,
            &candidate_actor_group,
            &candidate_world_slot);

    uintptr_t bucket_actor_address = 0;
    bool have_bucket_actor = false;
    if (have_target_slot_state &&
        candidate_actor_group >= 0 &&
        candidate_world_slot >= 0) {
        const auto bucket_index =
            static_cast<std::uint64_t>(candidate_actor_group) *
                static_cast<std::uint64_t>(kActorWorldBucketStride) +
            static_cast<std::uint64_t>(candidate_world_slot);
        have_bucket_actor = memory.TryReadValue(
            candidate_world_address +
                kActorWorldBucketTableOffset +
                static_cast<uintptr_t>(bucket_index) * sizeof(uintptr_t),
            &bucket_actor_address);
    }

    std::int16_t world_region_index = -1;
    int mapped_region_index = -1;
    const bool have_world_region = memory.TryReadField(
        hostile_world_address,
        kActorWorldRegionIndexOffset,
        &world_region_index);
    const bool have_mapped_region =
        candidate_actor_group >= 0 &&
        TryReadGameplayIndexStateValue(
            candidate_actor_group,
            &mapped_region_index);
    Log(
        std::string("[hostile_ai] rejected extended target candidate") +
        ". hostile=" + HexString(hostile_actor_address) +
        " hostile_world=" + HexString(hostile_world_address) +
        " candidate=" + HexString(candidate_actor_address) +
        " participant_id=" + std::to_string(participant_id) +
        " native_type_id=" +
            (have_native_type
                 ? std::to_string(native_type_id)
                 : UnreadableMemoryFieldText()) +
        " candidate_world=" + HexString(candidate_world_address) +
        " group=" + std::to_string(candidate_actor_group) +
        " world_slot=" + std::to_string(candidate_world_slot) +
        " target_slot_state_ok=" +
            std::to_string(have_target_slot_state ? 1 : 0) +
        " ineligible=" +
            (have_ineligible_state
                 ? std::to_string(ineligible_state)
                 : UnreadableMemoryFieldText()) +
        " runtime_dead=" +
            std::to_string(
                IsActorRuntimeDead(candidate_actor_address) ? 1 : 0) +
        " participant_dead=" +
            std::to_string(
                IsDeadWizardParticipantActor(candidate_actor_address)
                    ? 1
                    : 0) +
        " bucket=" +
            (have_bucket_actor
                 ? HexString(bucket_actor_address)
                 : UnreadableMemoryFieldText()) +
        " bucket_match=" +
            std::to_string(
                have_bucket_actor &&
                bucket_actor_address == candidate_actor_address
                    ? 1
                    : 0) +
        " world_region=" +
            (have_world_region
                 ? std::to_string(world_region_index)
                 : UnreadableMemoryFieldText()) +
        " mapped_region=" +
            (have_mapped_region
                 ? std::to_string(mapped_region_index)
                 : UnreadableMemoryFieldText()));
}

bool TrySelectNearestValidHostileTarget(
    uintptr_t hostile_actor_address,
    uintptr_t excluded_actor_address,
    HostileTargetSelection* selection) {
    if (selection == nullptr || hostile_actor_address == 0) {
        return false;
    }
    *selection = HostileTargetSelection{};

    uintptr_t gameplay_address = 0;
    uintptr_t hostile_world_address = 0;
    std::int32_t hostile_actor_group = -1;
    std::int32_t hostile_world_slot = -1;
    float hostile_x = 0.0f;
    float hostile_y = 0.0f;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) ||
        gameplay_address == 0 ||
        !TryReadActorWorldTargetSlotState(
            hostile_actor_address,
            &hostile_world_address,
            &hostile_actor_group,
            &hostile_world_slot) ||
        !TryReadFiniteFloatField(
            hostile_actor_address,
            kActorPositionXOffset,
            &hostile_x) ||
        !TryReadFiniteFloatField(
            hostile_actor_address,
            kActorPositionYOffset,
            &hostile_y)) {
        return false;
    }
    (void)hostile_actor_group;
    (void)hostile_world_slot;

    std::vector<uintptr_t> candidate_actor_addresses;
    candidate_actor_addresses.reserve(32);
    if (!TryReadNativeHostileTargetCandidateList(
            gameplay_address,
            &candidate_actor_addresses)) {
        return false;
    }
    AppendWizardParticipantTargetCandidates(
        gameplay_address,
        &candidate_actor_addresses);
    RefreshPlayerOwnedHostileTargetSidecars(
        hostile_world_address,
        static_cast<std::uint64_t>(GetTickCount64()));
    if (g_hostile_target_sidecar_cache.world_address ==
        hostile_world_address) {
        candidate_actor_addresses.insert(
            candidate_actor_addresses.end(),
            g_hostile_target_sidecar_cache.actor_addresses.begin(),
            g_hostile_target_sidecar_cache.actor_addresses.end());
    }

    std::unordered_set<uintptr_t> seen;
    for (const auto candidate_actor_address : candidate_actor_addresses) {
        if (!seen.insert(candidate_actor_address).second) {
            continue;
        }
        HostileTargetSelection candidate;
        const bool valid = TryValidateHostileTargetCandidate(
                hostile_actor_address,
                hostile_world_address,
                hostile_x,
                hostile_y,
                candidate_actor_address,
                excluded_actor_address,
                &candidate);
        if (!valid) {
            LogRejectedExtendedHostileTargetCandidate(
                hostile_actor_address,
                hostile_world_address,
                candidate_actor_address);
        } else if (IsPreferredHostileTargetCandidate(candidate, *selection)) {
            *selection = candidate;
        }
    }
    return true;
}

std::uint64_t ResolveHostileTargetParticipantId(uintptr_t actor_address) {
    {
        std::lock_guard<std::recursive_mutex> lock(
            g_participant_entities_mutex);
        const auto* binding = FindParticipantEntityForActor(actor_address);
        if (binding != nullptr && IsWizardParticipantKind(binding->kind)) {
            return binding->bot_id;
        }
    }

    uintptr_t gameplay_address = 0;
    uintptr_t local_actor_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) ||
        !TryResolvePlayerActorForSlot(
            gameplay_address,
            0,
            &local_actor_address) ||
        local_actor_address == 0 ||
        local_actor_address != actor_address) {
        return 0;
    }

    const auto transport_participant_id =
        multiplayer::GetLocalTransportParticipantId();
    return transport_participant_id != 0
        ? transport_participant_id
        : multiplayer::kLocalParticipantId;
}

bool ApplyNearestValidHostileTarget(
    uintptr_t hostile_actor_address,
    uintptr_t excluded_actor_address,
    std::string_view reason) {
    HostileTargetSelection selection;
    if (!TrySelectNearestValidHostileTarget(
            hostile_actor_address,
            excluded_actor_address,
            &selection)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t hostile_world_address = 0;
    std::int32_t hostile_actor_group = -1;
    std::int32_t hostile_world_slot = -1;
    if (!TryReadActorWorldTargetSlotState(
            hostile_actor_address,
            &hostile_world_address,
            &hostile_actor_group,
            &hostile_world_slot)) {
        return false;
    }
    (void)hostile_world_address;
    (void)hostile_world_slot;

    std::int32_t desired_bucket_delta = 0;
    if (selection.valid) {
        const auto bucket_delta =
            static_cast<std::int64_t>(selection.actor_group) *
                static_cast<std::int64_t>(kActorWorldBucketStride) +
            static_cast<std::int64_t>(selection.world_slot) -
            static_cast<std::int64_t>(hostile_actor_group) *
                static_cast<std::int64_t>(kActorWorldBucketStride);
        if (bucket_delta < (std::numeric_limits<std::int32_t>::min)() ||
            bucket_delta > (std::numeric_limits<std::int32_t>::max)()) {
            return false;
        }
        desired_bucket_delta = static_cast<std::int32_t>(bucket_delta);
    }

    uintptr_t previous_target_actor_address = 0;
    std::int32_t previous_bucket_delta = 0;
    if (!memory.TryReadField(
            hostile_actor_address,
            kActorCurrentTargetActorOffset,
            &previous_target_actor_address) ||
        !memory.TryReadField(
            hostile_actor_address,
            kHostileTargetBucketDeltaOffset,
            &previous_bucket_delta)) {
        return false;
    }

    const auto desired_target_actor_address =
        selection.valid ? selection.actor_address : 0;
    bool success = true;
    if (previous_target_actor_address != desired_target_actor_address) {
        success =
            memory.TryWriteField(
                hostile_actor_address,
                kActorCurrentTargetActorOffset,
                desired_target_actor_address) &&
            success;
    }
    if (previous_bucket_delta != desired_bucket_delta) {
        success =
            memory.TryWriteField(
                hostile_actor_address,
                kHostileTargetBucketDeltaOffset,
                desired_bucket_delta) &&
            success;
    }
    if (!success) {
        return false;
    }

    const auto [logged_target_iterator, inserted_logged_target] =
        g_last_logged_hostile_target_by_actor.try_emplace(
            hostile_actor_address,
            desired_target_actor_address);
    const bool semantic_target_change =
        inserted_logged_target ||
        logged_target_iterator->second != desired_target_actor_address;
    if (semantic_target_change && !inserted_logged_target) {
        logged_target_iterator->second = desired_target_actor_address;
    }
    if (semantic_target_change &&
        (previous_target_actor_address != desired_target_actor_address ||
         previous_bucket_delta != desired_bucket_delta)) {
        Log(
            std::string("[hostile_ai] authoritative nearest target applied") +
            ". reason=" + std::string(reason) +
            " hostile=" + HexString(hostile_actor_address) +
            " previous_target=" +
                HexString(previous_target_actor_address) +
            " target=" + HexString(desired_target_actor_address) +
            " target_participant_id=" +
                std::to_string(
                    ResolveHostileTargetParticipantId(
                        desired_target_actor_address)) +
            " target_native_type_id=" +
                std::to_string(selection.native_type_id) +
            " target_group=" +
                std::to_string(selection.actor_group) +
            " target_world_slot=" +
                std::to_string(selection.world_slot) +
            " target_bucket_delta=" +
                std::to_string(desired_bucket_delta));
    }
    return true;
}
