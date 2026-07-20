bool TryReadActorWorldTargetSlotState(
    uintptr_t actor_address,
    uintptr_t* world_address,
    std::int32_t* actor_slot,
    std::int32_t* world_slot) {
    if (world_address != nullptr) {
        *world_address = 0;
    }
    if (actor_slot != nullptr) {
        *actor_slot = -1;
    }
    if (world_slot != nullptr) {
        *world_slot = -1;
    }
    if (actor_address == 0 ||
        world_address == nullptr ||
        actor_slot == nullptr ||
        world_slot == nullptr ||
        kActorOwnerOffset == 0 ||
        kActorSlotOffset == 0 ||
        kActorWorldSlotOffset == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t read_world_address = 0;
    std::int8_t read_actor_slot = -1;
    std::int16_t read_world_slot = -1;
    if (!memory.TryReadField(
            actor_address,
            kActorOwnerOffset,
            &read_world_address) ||
        read_world_address == 0 ||
        !memory.TryReadField(
            actor_address,
            kActorSlotOffset,
            &read_actor_slot) ||
        read_actor_slot < 0 ||
        !memory.TryReadField(
            actor_address,
            kActorWorldSlotOffset,
            &read_world_slot) ||
        read_world_slot < 0) {
        return false;
    }

    *world_address = read_world_address;
    *actor_slot = static_cast<std::int32_t>(read_actor_slot);
    *world_slot = static_cast<std::int32_t>(read_world_slot);
    return true;
}
