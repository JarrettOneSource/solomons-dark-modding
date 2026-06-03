bool EnsureStandaloneWizardWorldOwner(
    uintptr_t actor_address,
    uintptr_t world_address,
    std::string_view stage,
    std::string* error_message) {
    if (actor_address == 0 || world_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Standalone owner repair requires live actor and world addresses.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t current_owner = 0;
    if (!memory.TryReadField(actor_address, kActorOwnerOffset, &current_owner)) {
        if (error_message != nullptr) {
            *error_message =
                "Standalone actor owner is unreadable before " + std::string(stage) + ".";
        }
        return false;
    }
    if (current_owner == world_address) {
        return true;
    }

    if (!memory.TryWriteField<uintptr_t>(actor_address, kActorOwnerOffset, world_address)) {
        if (error_message != nullptr) {
            *error_message =
                "Failed to restore standalone actor owner after " + std::string(stage) + ".";
        }
        return false;
    }

    uintptr_t repaired_owner = 0;
    if (!memory.TryReadField(actor_address, kActorOwnerOffset, &repaired_owner)) {
        if (error_message != nullptr) {
            *error_message =
                "Standalone actor owner is unreadable after " + std::string(stage) + ".";
        }
        return false;
    }
    if (repaired_owner != world_address) {
        if (error_message != nullptr) {
            *error_message =
                "Standalone actor owner repair did not stick after " + std::string(stage) + ".";
        }
        return false;
    }

    Log(
        "[bots] restored standalone owner after " + std::string(stage) +
        ". actor=" + HexString(actor_address) +
        " old_owner=" + HexString(current_owner) +
        " world=" + HexString(world_address));
    return true;
}
