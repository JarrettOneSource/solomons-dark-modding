bool EnterLocalPlayerCastShim(
    const ParticipantEntityBinding* binding,
    LocalPlayerCastShimState* state) {
    if (state == nullptr) {
        return false;
    }

    *state = LocalPlayerCastShimState{};
    if (binding == nullptr ||
        binding->actor_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    state->actor_address = binding->actor_address;
    state->saved_actor_slot = memory.ReadFieldOr<std::uint8_t>(
        binding->actor_address,
        kActorSlotOffset,
        static_cast<std::uint8_t>(0));
    uintptr_t gameplay_address = 0;
    const auto bot_progression_handle =
        memory.ReadFieldOr<uintptr_t>(
            binding->actor_address,
            kActorProgressionHandleOffset,
            0);
    if (bot_progression_handle != 0 &&
        TryResolveCurrentGameplayScene(&gameplay_address) &&
        gameplay_address != 0) {
        const auto local_progression_slot_offset = kGameplayPlayerProgressionHandleOffset;
        const auto saved_local_progression_handle =
            memory.ReadFieldOr<uintptr_t>(
                gameplay_address,
                local_progression_slot_offset,
                0);
        state->gameplay_address = gameplay_address;
        state->local_progression_slot_offset = local_progression_slot_offset;
        state->saved_local_progression_handle = saved_local_progression_handle;
        state->redirected_progression_handle = bot_progression_handle;

        if (saved_local_progression_handle == bot_progression_handle) {
            state->progression_slot_redirected = true;
        } else if (memory.TryWriteField<uintptr_t>(
                       gameplay_address,
                       local_progression_slot_offset,
                       bot_progression_handle)) {
            state->progression_slot_redirected = true;
            state->progression_slot_restore_needed = true;
        }
    }

    if (!memory.TryWriteField<std::uint8_t>(
            binding->actor_address,
            kActorSlotOffset,
            static_cast<std::uint8_t>(0))) {
        if (state->progression_slot_restore_needed &&
            state->gameplay_address != 0 &&
            state->local_progression_slot_offset != 0) {
            (void)memory.TryWriteField<uintptr_t>(
                state->gameplay_address,
                state->local_progression_slot_offset,
                state->saved_local_progression_handle);
        }
        *state = LocalPlayerCastShimState{};
        return false;
    }

    state->active = true;
    return true;
}

void LeaveLocalPlayerCastShim(const LocalPlayerCastShimState& state) {
    if (!state.active) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    (void)memory.TryWriteField<std::uint8_t>(
        state.actor_address,
        kActorSlotOffset,
        state.saved_actor_slot);
    if (state.progression_slot_restore_needed &&
        state.gameplay_address != 0 &&
        state.local_progression_slot_offset != 0) {
        (void)memory.TryWriteField<uintptr_t>(
            state.gameplay_address,
            state.local_progression_slot_offset,
            state.saved_local_progression_handle);
    }
}
