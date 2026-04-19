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

