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
        if (!TryResolveActorProgressionRuntime(resolved_actor_address, progression_address) ||
            *progression_address == 0) {
            if (!TryResolvePlayerProgressionForSlot(gameplay_address, 0, progression_address) ||
                *progression_address == 0) {
                return false;
            }
        }
    }

    return true;
}

bool ReserveRemoteParticipantGameplaySlot(std::uint64_t participant_id, int* slot_index) {
    if (slot_index == nullptr) {
        return false;
    }

    std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
    *slot_index = -1;
    if (auto* binding = FindParticipantEntity(participant_id); binding != nullptr && binding->gameplay_slot >= kFirstWizardBotSlot) {
        *slot_index = binding->gameplay_slot;
        return true;
    }

    for (int candidate = kFirstWizardBotSlot; candidate < static_cast<int>(kGameplayPlayerSlotCount); ++candidate) {
        if (FindParticipantEntityForGameplaySlot(candidate) == nullptr) {
            *slot_index = candidate;
            return true;
        }
    }

    return false;
}
