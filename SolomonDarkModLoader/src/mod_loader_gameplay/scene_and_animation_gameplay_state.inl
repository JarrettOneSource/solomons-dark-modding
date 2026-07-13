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

bool TryReadResolvedGlobalInt(uintptr_t absolute_address, int* value) {
    if (value == nullptr) {
        return false;
    }

    *value = 0;
    const auto resolved = ProcessMemory::Instance().ResolveGameAddressOrZero(absolute_address);
    return resolved != 0 && ProcessMemory::Instance().TryReadValue(resolved, value);
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

    int resolved_entry_count = 0;
    if (!TryReadResolvedGlobalInt(kGameplayIndexStateCountGlobal, &resolved_entry_count)) {
        return false;
    }
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

bool TryWriteGameplayIndexStateValue(
    int index,
    std::int32_t value,
    std::string_view description,
    std::string* error_message) {
    if (index < 0) {
        if (error_message != nullptr) {
            *error_message = "Gameplay index-state write received an invalid index.";
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
    if (index >= entry_count) {
        if (error_message != nullptr) {
            *error_message =
                "Gameplay index-state table is too small for " +
                std::string(description) + ".";
        }
        return false;
    }

    const auto address =
        table_address + static_cast<uintptr_t>(index) * sizeof(std::int32_t);
    if (!ProcessMemory::Instance().TryWriteValue(address, value)) {
        if (error_message != nullptr) {
            *error_message = "Failed to write " + std::string(description) + ".";
        }
        return false;
    }
    return true;
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

    const auto table_index =
        static_cast<int>(kGameplayIndexStateActorSelectionBaseIndex) + slot_index;
    return TryWriteGameplayIndexStateValue(
        table_index,
        static_cast<std::int32_t>(selection_state),
        "the slot animation-selection entry",
        error_message);
}

bool TryWriteGameplayConcentrationState(
    std::int32_t entry_a,
    std::int32_t entry_b,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    const auto index_a = static_cast<int>(kGameplayIndexStateConcentrationAIndex);
    const auto index_b = static_cast<int>(kGameplayIndexStateConcentrationBIndex);
    int previous_a = -1;
    int previous_b = -1;
    if (!TryReadGameplayIndexStateValue(index_a, &previous_a) ||
        !TryReadGameplayIndexStateValue(index_b, &previous_b)) {
        if (error_message != nullptr) {
            *error_message = "Unable to read the existing process Concentrate selections.";
        }
        return false;
    }
    if (previous_a == entry_a && previous_b == entry_b) {
        return true;
    }

    if (!TryWriteGameplayIndexStateValue(
            index_a,
            entry_a,
            "the process Concentrate-A entry",
            error_message)) {
        return false;
    }
    if (!TryWriteGameplayIndexStateValue(
            index_b,
            entry_b,
            "the process Concentrate-B entry",
            error_message)) {
        (void)TryWriteGameplayIndexStateValue(
            index_a,
            static_cast<std::int32_t>(previous_a),
            "the previous process Concentrate-A entry",
            nullptr);
        return false;
    }
    return true;
}

bool TryReadGameplayConcentrationStateForSlot(
    int gameplay_slot,
    std::int32_t* entry_a,
    std::int32_t* entry_b) {
    if (entry_a == nullptr || entry_b == nullptr ||
        gameplay_slot < 0 ||
        gameplay_slot >= static_cast<int>(kGameplayPlayerSlotCount)) {
        return false;
    }
    int value_a = -1;
    int value_b = -1;
    if (!TryReadGameplayIndexStateValue(
            static_cast<int>(kGameplayIndexStateConcentrationAIndex) + gameplay_slot,
            &value_a) ||
        !TryReadGameplayIndexStateValue(
            static_cast<int>(kGameplayIndexStateConcentrationBIndex) + gameplay_slot,
            &value_b)) {
        return false;
    }
    *entry_a = static_cast<std::int32_t>(value_a);
    *entry_b = static_cast<std::int32_t>(value_b);
    return true;
}

bool TryWriteGameplayConcentrationStateForSlot(
    int gameplay_slot,
    std::int32_t entry_a,
    std::int32_t entry_b,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (gameplay_slot < 0 ||
        gameplay_slot >= static_cast<int>(kGameplayPlayerSlotCount)) {
        if (error_message != nullptr) {
            *error_message = "Concentrate runtime-lane write received an invalid gameplay slot.";
        }
        return false;
    }

    std::int32_t previous_a = -1;
    std::int32_t previous_b = -1;
    if (!TryReadGameplayConcentrationStateForSlot(
            gameplay_slot,
            &previous_a,
            &previous_b)) {
        if (error_message != nullptr) {
            *error_message = "Unable to read the gameplay-slot Concentrate runtime lanes.";
        }
        return false;
    }
    if (previous_a == entry_a && previous_b == entry_b) {
        return true;
    }

    const auto index_a =
        static_cast<int>(kGameplayIndexStateConcentrationAIndex) + gameplay_slot;
    const auto index_b =
        static_cast<int>(kGameplayIndexStateConcentrationBIndex) + gameplay_slot;
    if (!TryWriteGameplayIndexStateValue(
            index_a,
            entry_a,
            "the gameplay-slot Concentrate-A runtime lane",
            error_message)) {
        return false;
    }
    if (!TryWriteGameplayIndexStateValue(
            index_b,
            entry_b,
            "the gameplay-slot Concentrate-B runtime lane",
            error_message)) {
        (void)TryWriteGameplayIndexStateValue(
            index_a,
            previous_a,
            "the previous gameplay-slot Concentrate-A runtime lane",
            nullptr);
        return false;
    }

    std::int32_t verified_a = -1;
    std::int32_t verified_b = -1;
    if (!TryReadGameplayConcentrationStateForSlot(
            gameplay_slot,
            &verified_a,
            &verified_b) ||
        verified_a != entry_a || verified_b != entry_b) {
        if (error_message != nullptr) {
            *error_message = "Gameplay-slot Concentrate runtime-lane verification failed.";
        }
        return false;
    }
    return true;
}

class ScopedParticipantConcentrationSamplingSuppression {
public:
    ScopedParticipantConcentrationSamplingSuppression()
        : lock_(g_participant_concentration_context_mutex) {
        g_participant_concentration_context_depth.fetch_add(
            1,
            std::memory_order_acq_rel);
    }

    ScopedParticipantConcentrationSamplingSuppression(
        const ScopedParticipantConcentrationSamplingSuppression&) = delete;
    ScopedParticipantConcentrationSamplingSuppression& operator=(
        const ScopedParticipantConcentrationSamplingSuppression&) = delete;

    ~ScopedParticipantConcentrationSamplingSuppression() {
        g_participant_concentration_context_depth.fetch_sub(
            1,
            std::memory_order_acq_rel);
    }

private:
    std::unique_lock<std::recursive_mutex> lock_;
};

struct ScopedParticipantConcentrationContext {
    const ParticipantEntityBinding* binding = nullptr;
    bool requested = false;
    bool active = false;
    bool restore_attempted = false;
    bool restored = true;
    std::int32_t previous_entry_a = -1;
    std::int32_t previous_entry_b = -1;
    std::string status = "not_requested";
    std::unique_ptr<ScopedParticipantConcentrationSamplingSuppression>
        sampling_suppression;

    explicit ScopedParticipantConcentrationContext(
        const ParticipantEntityBinding* binding_in)
        : binding(binding_in),
          requested(
              binding_in != nullptr &&
              binding_in->concentration_selection_valid &&
              binding_in->controller_kind ==
                  multiplayer::ParticipantControllerKind::Native) {
        if (!requested) {
            return;
        }
        Apply();
    }

    ScopedParticipantConcentrationContext(
        const ScopedParticipantConcentrationContext&) = delete;
    ScopedParticipantConcentrationContext& operator=(
        const ScopedParticipantConcentrationContext&) = delete;

    ~ScopedParticipantConcentrationContext() {
        Restore();
    }

    void Apply() {
        const auto index_a =
            static_cast<int>(kGameplayIndexStateConcentrationAIndex);
        const auto index_b =
            static_cast<int>(kGameplayIndexStateConcentrationBIndex);
        sampling_suppression =
            std::make_unique<ScopedParticipantConcentrationSamplingSuppression>();
        int previous_a = -1;
        int previous_b = -1;
        if (!TryReadGameplayIndexStateValue(index_a, &previous_a) ||
            !TryReadGameplayIndexStateValue(index_b, &previous_b)) {
            status = "snapshot_failed";
            sampling_suppression.reset();
            return;
        }
        previous_entry_a = static_cast<std::int32_t>(previous_a);
        previous_entry_b = static_cast<std::int32_t>(previous_b);

        std::string error_message;
        if (!TryWriteGameplayConcentrationState(
                binding->concentration_entry_a,
                binding->concentration_entry_b,
                &error_message)) {
            status = "apply_failed:" + error_message;
            sampling_suppression.reset();
            return;
        }
        active = true;
        restored = false;
        status = "active";
    }

    void Restore() {
        if (!active || restore_attempted) {
            return;
        }
        restore_attempted = true;
        active = false;
        std::string error_message;
        restored = TryWriteGameplayConcentrationState(
            previous_entry_a,
            previous_entry_b,
            &error_message);
        sampling_suppression.reset();
        status = restored ? "restored" : "restore_failed:" + error_message;
        if (!restored) {
            Log(
                "[bots] participant Concentrate context restore failed. bot_id=" +
                std::to_string(binding != nullptr ? binding->bot_id : 0) +
                " revision=" +
                std::to_string(
                    binding != nullptr ? binding->concentration_revision : 0) +
                " previous_a=" + std::to_string(previous_entry_a) +
                " previous_b=" + std::to_string(previous_entry_b) +
                " error=" + error_message);
        }
    }

    std::string Describe() const {
        return
            "requested=" + std::to_string(requested ? 1 : 0) +
            " status=" + status +
            " bot_id=" +
                std::to_string(binding != nullptr ? binding->bot_id : 0) +
            " revision=" +
                std::to_string(
                    binding != nullptr ? binding->concentration_revision : 0) +
            " desired_a=" +
                std::to_string(
                    binding != nullptr ? binding->concentration_entry_a : -1) +
            " desired_b=" +
                std::to_string(
                    binding != nullptr ? binding->concentration_entry_b : -1) +
            " previous_a=" + std::to_string(previous_entry_a) +
            " previous_b=" + std::to_string(previous_entry_b) +
            " restore_attempted=" +
                std::to_string(restore_attempted ? 1 : 0) +
            " restored=" + std::to_string(restored ? 1 : 0);
    }
};

template <typename InvokeFn>
void InvokeWithParticipantConcentrationContext(
    const ParticipantEntityBinding* binding,
    InvokeFn&& invoke,
    std::string* context_description = nullptr) {
    ScopedParticipantConcentrationContext concentration_context(binding);
    invoke();
    concentration_context.Restore();
    if (context_description != nullptr) {
        *context_description = concentration_context.Describe();
    }
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
