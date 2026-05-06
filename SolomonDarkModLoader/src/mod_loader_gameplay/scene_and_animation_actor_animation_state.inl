int ResolveActorAnimationStateSlotIndex(uintptr_t actor_address) {
    if (actor_address == 0) {
        return -1;
    }

    std::int8_t slot = -1;
    if (!ProcessMemory::Instance().TryReadField(actor_address, kActorSlotOffset, &slot)) {
        return -1;
    }
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

    int entry_count = 0;
    if (!TryReadResolvedGlobalInt(kGameplayIndexStateCountGlobal, &entry_count)) {
        return false;
    }
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
    uintptr_t state_pointer = 0;
    if (!memory.TryReadField(actor_address, kActorAnimationSelectionStateOffset, &state_pointer)) {
        return kUnknownAnimationStateId;
    }
    if (state_pointer != 0) {
        int state_id = kUnknownAnimationStateId;
        return memory.TryReadValue(state_pointer, &state_id)
            ? state_id
            : kUnknownAnimationStateId;
    }

    uintptr_t slot_address = 0;
    if (!TryResolveActorAnimationStateSlotAddress(actor_address, &slot_address) || slot_address == 0) {
        return kUnknownAnimationStateId;
    }

    int slot_state_id = kUnknownAnimationStateId;
    return memory.TryReadValue(slot_address, &slot_state_id)
        ? slot_state_id
        : kUnknownAnimationStateId;
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
    uintptr_t state_pointer = 0;
    if (!memory.TryReadField(actor_address, kActorAnimationSelectionStateOffset, &state_pointer)) {
        return false;
    }
    return state_pointer != 0 && memory.TryWriteValue<int>(state_pointer, state_id);
}
