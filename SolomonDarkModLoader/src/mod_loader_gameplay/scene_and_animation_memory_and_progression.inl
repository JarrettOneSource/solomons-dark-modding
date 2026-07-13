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

    if (!ProcessMemory::Instance().TryReadField(
            gameplay_address,
            kGameplayPlayerActorOffset + static_cast<std::size_t>(slot_index) * kGameplayPlayerSlotStride,
            actor_address)) {
        *actor_address = 0;
        return false;
    }
    return *actor_address != 0;
}

bool TryResolvePlayerProgressionForSlot(uintptr_t gameplay_address, int slot_index, uintptr_t* progression_address) {
    if (progression_address == nullptr || slot_index < 0 || slot_index >= static_cast<int>(kGameplayPlayerSlotCount)) {
        return false;
    }

    *progression_address = 0;
    uintptr_t handle = 0;
    if (!ProcessMemory::Instance().TryReadField(
            gameplay_address,
            kGameplayPlayerProgressionHandleOffset + static_cast<std::size_t>(slot_index) * kGameplayPlayerSlotStride,
            &handle)) {
        return false;
    }
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
    uintptr_t handle = 0;
    if (!ProcessMemory::Instance().TryReadField(
            gameplay_address,
            kGameplayPlayerProgressionHandleOffset + static_cast<std::size_t>(slot_index) * kGameplayPlayerSlotStride,
            &handle)) {
        return false;
    }
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

    struct StableSceneReadiness {
        uintptr_t gameplay_address = 0;
        uintptr_t world_address = 0;
        int region_index = -1;
        int region_type_id = -1;
        std::uint64_t stable_since_ms = 0;
    };
    static StableSceneReadiness s_stable_scene_readiness;
    const bool scene_identity_changed =
        s_stable_scene_readiness.gameplay_address != snapshot.gameplay_scene_address ||
        s_stable_scene_readiness.world_address != snapshot.world_address ||
        s_stable_scene_readiness.region_index != snapshot.current_region_index ||
        s_stable_scene_readiness.region_type_id != snapshot.region_type_id;
    if (scene_identity_changed) {
        s_stable_scene_readiness.gameplay_address = snapshot.gameplay_scene_address;
        s_stable_scene_readiness.world_address = snapshot.world_address;
        s_stable_scene_readiness.region_index = snapshot.current_region_index;
        s_stable_scene_readiness.region_type_id = snapshot.region_type_id;
        s_stable_scene_readiness.stable_since_ms = now_ms;
        if (error_message != nullptr) {
            *error_message = "Gameplay scene identity is not stable yet.";
        }
        return false;
    }
    const auto required_scene_stable_delay_ms =
        IsSharedHubSceneContext(snapshot)
            ? kRemoteParticipantSpawnHubSceneStableDelayMs
            : kRemoteParticipantSpawnSceneStableDelayMs;
    if (now_ms - s_stable_scene_readiness.stable_since_ms <
        required_scene_stable_delay_ms) {
        if (error_message != nullptr) {
            *error_message = "Gameplay scene identity is still settling.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t local_actor_address = 0;
    if (!TryResolvePlayerActorForSlot(gameplay_address, 0, &local_actor_address) ||
        local_actor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Local slot-0 player actor is not ready.";
        }
        return false;
    }

    std::int8_t local_actor_slot = -1;
    if (!memory.TryReadField(local_actor_address, kActorSlotOffset, &local_actor_slot) ||
        local_actor_slot != 0) {
        if (error_message != nullptr) {
            *error_message =
                "Local slot-0 player actor has unexpected actor slot " +
                std::to_string(static_cast<int>(local_actor_slot)) + ".";
        }
        return false;
    }

    uintptr_t local_actor_world = 0;
    if (!memory.TryReadField(local_actor_address, kActorOwnerOffset, &local_actor_world) ||
        local_actor_world != snapshot.world_address) {
        if (error_message != nullptr) {
            *error_message =
                "Local slot-0 player actor owner does not match scene world. actor_world=" +
                HexString(local_actor_world) + " scene_world=" + HexString(snapshot.world_address) + ".";
        }
        return false;
    }

    float local_x = 0.0f;
    float local_y = 0.0f;
    if (!TryReadFiniteFloatField(local_actor_address, kActorPositionXOffset, &local_x) ||
        !TryReadFiniteFloatField(local_actor_address, kActorPositionYOffset, &local_y)) {
        if (error_message != nullptr) {
            *error_message = "Local slot-0 player actor position is not readable.";
        }
        return false;
    }

    uintptr_t local_progression_address = 0;
    if (!TryResolvePlayerProgressionForSlot(gameplay_address, 0, &local_progression_address) ||
        local_progression_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Local slot-0 progression handle is not ready.";
        }
        return false;
    }

    float hp = 0.0f;
    float max_hp = 0.0f;
    float mp = 0.0f;
    float max_mp = 0.0f;
    if (!TryReadFiniteFloatField(local_progression_address, kProgressionHpOffset, &hp) ||
        !TryReadFiniteFloatField(local_progression_address, kProgressionMaxHpOffset, &max_hp) ||
        !TryReadFiniteFloatField(local_progression_address, kProgressionMpOffset, &mp) ||
        !TryReadFiniteFloatField(local_progression_address, kProgressionMaxMpOffset, &max_mp) ||
        max_hp <= 0.0f ||
        max_mp <= 0.0f ||
        max_hp > 1000000.0f ||
        max_mp > 1000000.0f) {
        if (error_message != nullptr) {
            *error_message =
                "Local slot-0 progression vitals are not stable. progression=" +
                HexString(local_progression_address) +
                " hp=" + std::to_string(hp) +
                " max_hp=" + std::to_string(max_hp) +
                " mp=" + std::to_string(mp) +
                " max_mp=" + std::to_string(max_mp) + ".";
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
    int level = 0;
    float xp = 0.0f;
    float hp = 0.0f;
    float max_hp = 0.0f;
    float mp = 0.0f;
    float max_mp = 0.0f;
    if (!memory.TryReadField(source_progression_address, kProgressionLevelOffset, &level) ||
        !TryReadFiniteFloatField(source_progression_address, kProgressionXpOffset, &xp) ||
        !TryReadFiniteFloatField(source_progression_address, kProgressionHpOffset, &hp) ||
        !TryReadFiniteFloatField(source_progression_address, kProgressionMaxHpOffset, &max_hp) ||
        !TryReadFiniteFloatField(source_progression_address, kProgressionMpOffset, &mp) ||
        !TryReadFiniteFloatField(source_progression_address, kProgressionMaxMpOffset, &max_mp)) {
        return;
    }
    memory.TryWriteField(destination_progression_address, kProgressionLevelOffset, level);
    memory.TryWriteField(destination_progression_address, kProgressionXpOffset, xp);
    memory.TryWriteField(destination_progression_address, kProgressionHpOffset, hp);
    memory.TryWriteField(destination_progression_address, kProgressionMaxHpOffset, max_hp);
    memory.TryWriteField(destination_progression_address, kProgressionMpOffset, mp);
    memory.TryWriteField(destination_progression_address, kProgressionMaxMpOffset, max_mp);
}
