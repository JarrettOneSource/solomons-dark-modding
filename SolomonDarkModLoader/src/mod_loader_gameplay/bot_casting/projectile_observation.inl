bool IsPurePrimaryProjectileActorType(std::uint32_t object_type_id) {
    switch (object_type_id) {
    case 0x7D3:
    case 0x7D4:
    case 0x7D5:
        return true;
    default:
        return false;
    }
}

std::uint32_t ExpectedPurePrimaryProjectileTypeForSelectionState(int selection_state) {
    switch (selection_state) {
    case 0x08:
        return 0x7D3;
    case 0x10:
        return 0x7D4;
    case 0x28:
        return 0x7D5;
    default:
        return 0;
    }
}

bool TryListPurePrimaryProjectileActorAddressesInScene(
    std::uint32_t expected_object_type_id,
    std::vector<uintptr_t>* addresses) {
    if (addresses == nullptr) {
        return false;
    }
    addresses->clear();

    std::vector<SDModSceneActorState> actors;
    if (!TryListSceneActors(&actors)) {
        return false;
    }

    for (const auto& actor : actors) {
        const bool matches_expected_type =
            expected_object_type_id == 0 ||
            actor.object_type_id == expected_object_type_id;
        if (matches_expected_type &&
            IsPurePrimaryProjectileActorType(actor.object_type_id) &&
            actor.actor_address != 0) {
            addresses->push_back(actor.actor_address);
        }
    }
    return true;
}

std::vector<uintptr_t> ListPurePrimaryProjectileActorAddressesInScene(
    std::uint32_t expected_object_type_id = 0) {
    std::vector<uintptr_t> addresses;
    (void)TryListPurePrimaryProjectileActorAddressesInScene(
        expected_object_type_id,
        &addresses);
    return addresses;
}

int CountPurePrimaryProjectileActorsInScene(std::uint32_t expected_object_type_id = 0) {
    std::vector<uintptr_t> addresses;
    if (!TryListPurePrimaryProjectileActorAddressesInScene(
            expected_object_type_id,
            &addresses)) {
        return -1;
    }
    return static_cast<int>(addresses.size());
}

bool ContainsProjectileActorAddress(
    const std::vector<uintptr_t>& addresses,
    uintptr_t address) {
    for (const auto candidate : addresses) {
        if (candidate == address) {
            return true;
        }
    }
    return false;
}

bool TryFindNewPurePrimaryProjectileActorInScene(
    std::uint32_t expected_object_type_id,
    const std::vector<uintptr_t>& baseline_addresses,
    uintptr_t* new_actor_address) {
    if (new_actor_address != nullptr) {
        *new_actor_address = 0;
    }

    const auto current_addresses =
        ListPurePrimaryProjectileActorAddressesInScene(expected_object_type_id);
    for (const auto address : current_addresses) {
        if (!ContainsProjectileActorAddress(baseline_addresses, address)) {
            if (new_actor_address != nullptr) {
                *new_actor_address = address;
            }
            return true;
        }
    }
    return false;
}
