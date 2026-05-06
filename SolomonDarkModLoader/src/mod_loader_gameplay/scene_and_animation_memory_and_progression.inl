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

bool TryReadFiniteFloatField(uintptr_t address, std::size_t offset, float* value) {
    if (value == nullptr) {
        return false;
    }

    *value = 0.0f;
    return address != 0 &&
           ProcessMemory::Instance().TryReadField(address, offset, value) &&
           std::isfinite(*value);
}

bool TryReadPlayerRoundedXp(uintptr_t progression_address, int* experience) {
    if (experience == nullptr) {
        return false;
    }

    *experience = 0;
    float xp = 0.0f;
    if (!TryReadFiniteFloatField(progression_address, kProgressionXpOffset, &xp) ||
        xp < 0.0f) {
        return false;
    }

    *experience = static_cast<int>(std::lround(xp));
    return true;
}

bool EnsureBotOwnedProgressionMode(uintptr_t progression_address, const char* stage) {
    if (progression_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    std::uint8_t previous_mode = kProgressionLocalPlayerModeValue;
    const bool read_previous = memory.TryReadField<std::uint8_t>(
        progression_address,
        kProgressionNonLocalModeFlagOffset,
        &previous_mode);
    if (read_previous && previous_mode == kProgressionNonLocalModeValue) {
        return true;
    }

    if (!memory.TryWriteField<std::uint8_t>(
            progression_address,
            kProgressionNonLocalModeFlagOffset,
            kProgressionNonLocalModeValue)) {
        Log(
            "[bots] bot-owned progression mode failed. stage=" +
            std::string(stage != nullptr ? stage : "unknown") +
            " progression=" + HexString(progression_address));
        return false;
    }

    Log(
        "[bots] bot-owned progression mode set. stage=" +
        std::string(stage != nullptr ? stage : "unknown") +
        " progression=" + HexString(progression_address) +
        " previous_mode=" + (read_previous ? std::to_string(previous_mode) : "unreadable") +
        " mode=" + std::to_string(kProgressionNonLocalModeValue));
    return true;
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

bool TryValidateRemoteParticipantSpawnReadiness(
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

    const auto now_ms = static_cast<std::uint64_t>(::GetTickCount64());
    const auto churn_until =
        g_gameplay_keyboard_injection.scene_churn_not_before_ms.load(std::memory_order_acquire);
    if (now_ms < churn_until) {
        if (error_message != nullptr) {
            *error_message = "Gameplay scene churn is still in flight.";
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
