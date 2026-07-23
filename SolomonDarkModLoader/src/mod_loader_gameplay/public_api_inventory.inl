bool TryResolveNativeItemRecipeByName(
    std::string_view recipe_name,
    std::uint32_t expected_item_type_id,
    std::uint32_t* recipe_uid,
    std::string* error_message) {
    return TryResolveNativeItemRecipeByNameInternal(
        recipe_name,
        expected_item_type_id,
        recipe_uid,
        error_message);
}

bool QueueLuaItemGrantToLocalInventory(
    std::uint64_t authority_participant_id,
    std::uint64_t request_id,
    std::uint64_t content_id,
    const std::array<std::uint8_t, multiplayer::kParticipantVisualLinkColorBlockBytes>&
        color_state,
    bool color_state_valid,
    std::string* error_message) {
    return QueueLuaItemGrantToLocalInventoryInternal(
        authority_participant_id,
        request_id,
        content_id,
        color_state,
        color_state_valid,
        error_message);
}

bool QueuePlayerInventoryItemEquip(
    std::uint32_t recipe_uid,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    const auto fail = [&](const char* message) {
        if (error_message != nullptr) {
            *error_message = message;
        }
        return false;
    };

    if (!g_gameplay_keyboard_injection.initialized) {
        return fail("Gameplay action pump is not initialized.");
    }
    if (recipe_uid == 0) {
        return fail("An exact nonzero item recipe uid is required.");
    }

    SDModInventoryState inventory;
    if (!TryGetPlayerInventoryState(&inventory) || !inventory.valid) {
        return fail("The local native inventory is unavailable.");
    }
    const auto item = std::find_if(
        inventory.items.begin(),
        inventory.items.end(),
        [&](const SDModInventoryItemState& candidate) {
            return candidate.valid && candidate.recipe_uid == recipe_uid;
        });
    if (item == inventory.items.end()) {
        return fail("The requested item recipe is not in the local native inventory.");
    }
    if (item->type_id != kStandaloneWizardHatVisualTypeId &&
        item->type_id != kStandaloneWizardRobeVisualTypeId &&
        item->type_id != kStandaloneWizardStaffItemTypeId &&
        item->type_id != kStandaloneWizardWandItemTypeId &&
        item->type_id != kStandaloneWizardRingItemTypeId &&
        item->type_id != kStandaloneWizardAmuletItemTypeId) {
        return fail("The requested item is not supported by a native equipment sink.");
    }

    PendingLocalInventoryEquipRequest request;
    request.recipe_uid = recipe_uid;
    request.gameplay_scene_address = inventory.gameplay_scene_address;
    std::lock_guard<std::mutex> lock(
        g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    auto& pending =
        g_gameplay_keyboard_injection.pending_local_inventory_equip_requests;
    if (pending.size() >= kQueuedGameplayWorldActionLimit) {
        return fail("The local native equipment queue is full.");
    }
    const auto duplicate = std::find_if(
        pending.begin(),
        pending.end(),
        [&](const PendingLocalInventoryEquipRequest& existing) {
            return existing.recipe_uid == request.recipe_uid &&
                   existing.gameplay_scene_address ==
                       request.gameplay_scene_address;
        });
    if (duplicate == pending.end()) {
        pending.push_back(request);
    }
    return true;
}
