void PrimeGameplaySlotBotActor(
    uintptr_t gameplay_address,
    int slot_index,
    uintptr_t actor_address,
    uintptr_t progression_address,
    float x,
    float y,
    float heading) {
    if (gameplay_address == 0 || actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t local_actor_address = 0;
    uintptr_t local_progression_address = 0;
    (void)TryResolvePlayerActorForSlot(gameplay_address, 0, &local_actor_address);
    (void)TryResolvePlayerProgressionForSlot(gameplay_address, 0, &local_progression_address);
    const auto actor_slot_offset =
        kGameplayPlayerActorOffset + static_cast<std::size_t>(slot_index) * kGameplayPlayerSlotStride;
    const auto progression_slot_offset =
        kGameplayPlayerProgressionHandleOffset + static_cast<std::size_t>(slot_index) * kGameplayPlayerSlotStride;
    const auto log_prime_slot_state = [&](std::string_view label) {
        const auto slot_actor =
            memory.ReadFieldOr<uintptr_t>(gameplay_address, actor_slot_offset, 0);
        const auto slot_progression_wrapper =
            memory.ReadFieldOr<uintptr_t>(gameplay_address, progression_slot_offset, 0);
        const auto slot_progression_inner =
            ReadSmartPointerInnerObject(slot_progression_wrapper);
        const auto local_slot_actor =
            memory.ReadFieldOr<uintptr_t>(gameplay_address, kGameplayPlayerActorOffset, 0);
        const auto local_slot_progression_wrapper =
            memory.ReadFieldOr<uintptr_t>(gameplay_address, kGameplayPlayerProgressionHandleOffset, 0);
        const auto local_slot_progression_inner =
            ReadSmartPointerInnerObject(local_slot_progression_wrapper);
        Log(
            "[bots] prime_slot_actor " + std::string(label) +
            " gameplay=" + HexString(gameplay_address) +
            " slot=" + std::to_string(slot_index) +
            " slot_actor=" + HexString(slot_actor) +
            " slot_prog=" + HexString(slot_progression_wrapper) +
            " slot_prog_inner=" + HexString(slot_progression_inner) +
            " local_actor=" + HexString(local_slot_actor) +
            " local_prog=" + HexString(local_slot_progression_wrapper) +
            " local_prog_inner=" + HexString(local_slot_progression_inner) +
            " actor=" + HexString(actor_address) +
            " progression=" + HexString(progression_address));
    };
    log_prime_slot_state("enter");
    (void)x;
    (void)y;
    (void)heading;
}

int ResolveStandaloneWizardRenderSelectionIndex(int wizard_id) {
    // `actor/source +0x23F` is the coarse selector byte consumed by the stock
    // clone/render bridge:
    //   0 -> 0x08, 1 -> 0x10, 2 -> 0x18, 3 -> 0x20, 4 -> 0x28.
    // Keep the public bot element ids aligned to the user-facing colors:
    //   fire, water, earth, air, ether.
    switch ((std::max)(0, (std::min)(wizard_id, 4))) {
    case 0: // Fire
        return 1;
    case 1: // Water
        return 3;
    case 2: // Earth
        return 4;
    case 3: // Air
        return 2;
    case 4: // Ether
    default:
        return 0;
    }
}

int ResolveStandaloneWizardSelectionState(int wizard_id) {
    // Convert the coarse selector byte back through the stock clone mapping so
    // source-profile staging and concrete actor selection stay on the same
    // element branch.
    switch (ResolveStandaloneWizardRenderSelectionIndex(wizard_id)) {
    case 0:
        return 0x08;
    case 1:
        return 0x10;
    case 2:
        return 0x18;
    case 3:
        return 0x20;
    case 4:
        return 0x28;
    default:
        return kStandaloneWizardHiddenSelectionState;
    }
}

int ResolveProfileSelectionState(const multiplayer::MultiplayerCharacterProfile& character_profile) {
    return ResolveStandaloneWizardSelectionState(ResolveProfileElementId(character_profile));
}
