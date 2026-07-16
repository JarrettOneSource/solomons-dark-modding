namespace {

struct LocalNativeEquipLane {
    SDModEquipVisualLaneState state;
    const char* label = nullptr;
    std::uint32_t expected_holder_kind = 0;
};

bool ResolveLocalNativeEquipLane(
    const SDModInventoryState& inventory,
    std::uint32_t item_type_id,
    LocalNativeEquipLane* lane) {
    if (lane == nullptr) {
        return false;
    }
    *lane = {};
    switch (item_type_id) {
    case kStandaloneWizardHatVisualTypeId:
        lane->state = inventory.primary_visual_lane;
        lane->label = "hat";
        lane->expected_holder_kind = 1;
        return true;
    case kStandaloneWizardRobeVisualTypeId:
        lane->state = inventory.secondary_visual_lane;
        lane->label = "robe";
        lane->expected_holder_kind = 2;
        return true;
    case kStandaloneWizardStaffItemTypeId:
    case kStandaloneWizardWandItemTypeId:
        lane->state = inventory.attachment_visual_lane;
        lane->label = "weapon";
        lane->expected_holder_kind = 4;
        return true;
    case kStandaloneWizardRingItemTypeId: {
        const SDModEquipVisualLaneState* first_ring_lane = nullptr;
        // The third stock ring sink is progression-gated. The semantic API
        // therefore fills/replaces one of the two unconditional slots; native
        // inventory UI can still author and replicate the unlocked third slot.
        for (std::size_t index = 0; index < 2; ++index) {
            const auto& candidate = inventory.ring_lanes[index];
            if (candidate.holder_address == 0 || candidate.holder_kind != 5) {
                continue;
            }
            if (first_ring_lane == nullptr) {
                first_ring_lane = &candidate;
            }
            if (candidate.current_object_address == 0) {
                first_ring_lane = &candidate;
                break;
            }
        }
        if (first_ring_lane == nullptr) {
            return false;
        }
        lane->state = *first_ring_lane;
        lane->label = "ring";
        lane->expected_holder_kind = 5;
        return true;
    }
    case kStandaloneWizardAmuletItemTypeId:
        lane->state = inventory.amulet_lane;
        lane->label = "amulet";
        lane->expected_holder_kind = 6;
        return true;
    default:
        return false;
    }
}

bool ResolveLocalNativeEquipLaneByHolder(
    const SDModInventoryState& inventory,
    std::uint32_t item_type_id,
    uintptr_t holder_address,
    LocalNativeEquipLane* lane) {
    if (lane == nullptr || holder_address == 0) {
        return false;
    }

    const auto accept = [&](const SDModEquipVisualLaneState& candidate,
                            const char* label,
                            std::uint32_t expected_holder_kind) {
        if (candidate.holder_address != holder_address ||
            candidate.holder_kind != expected_holder_kind) {
            return false;
        }
        lane->state = candidate;
        lane->label = label;
        lane->expected_holder_kind = expected_holder_kind;
        return true;
    };

    *lane = {};
    switch (item_type_id) {
    case kStandaloneWizardHatVisualTypeId:
        return accept(inventory.primary_visual_lane, "hat", 1);
    case kStandaloneWizardRobeVisualTypeId:
        return accept(inventory.secondary_visual_lane, "robe", 2);
    case kStandaloneWizardStaffItemTypeId:
    case kStandaloneWizardWandItemTypeId:
        return accept(inventory.attachment_visual_lane, "weapon", 4);
    case kStandaloneWizardRingItemTypeId:
        for (const auto& candidate : inventory.ring_lanes) {
            if (accept(candidate, "ring", 5)) {
                return true;
            }
        }
        return false;
    case kStandaloneWizardAmuletItemTypeId:
        return accept(inventory.amulet_lane, "amulet", 6);
    default:
        return false;
    }
}

bool NativeInventoryContainsAddress(
    const SDModInventoryState& inventory,
    uintptr_t item_address) {
    return std::any_of(
        inventory.items.begin(),
        inventory.items.end(),
        [&](const SDModInventoryItemState& item) {
            return item.valid && item.item_address == item_address;
        });
}

bool RemoveNativeInventoryItemPointer(
    const SDModInventoryState& inventory,
    uintptr_t item_address,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (inventory.item_list_root_address == 0 || item_address == 0 ||
        kGameplayItemListPointerListOffset == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto list_address =
        inventory.item_list_root_address + kGameplayItemListPointerListOffset;
    uintptr_t vtable = 0;
    uintptr_t remove_address = 0;
    return memory.TryReadValue(list_address, &vtable) &&
           vtable != 0 &&
           memory.TryReadValue(
               vtable + kPointerListRemoveValueVtableOffset,
               &remove_address) &&
           remove_address != 0 &&
           memory.IsExecutableRange(remove_address, 1) &&
           CallPointerListRemoveValueSafe(
               remove_address,
               list_address,
               item_address,
               exception_code);
}

bool AttachLocalNativeEquipmentObject(
    const SDModEquipVisualLaneState& lane,
    uintptr_t item_address,
    DWORD* exception_code) {
    const auto attach_address = ProcessMemory::Instance().ResolveGameAddressOrZero(
        kStandaloneWizardVisualLinkAttach);
    return attach_address != 0 &&
           lane.holder_address != 0 &&
           CallStandaloneWizardVisualLinkAttachSafe(
               attach_address,
               lane.holder_address,
               item_address,
               exception_code);
}

bool RestoreLocalNativeEquipTransaction(
    const SDModInventoryState& inventory,
    const LocalNativeEquipLane& lane,
    uintptr_t target_item_address,
    uintptr_t previous_item_address,
    bool previous_item_is_in_inventory,
    uintptr_t player_actor_address,
    uintptr_t refresh_address,
    std::string* error_message) {
    DWORD remove_exception = 0;
    if (previous_item_address != 0 &&
        previous_item_address != target_item_address &&
        previous_item_is_in_inventory &&
        !RemoveNativeInventoryItemPointer(
            inventory,
            previous_item_address,
            &remove_exception)) {
        if (error_message != nullptr) {
            *error_message =
                "Native equipment rollback could not reclaim the previous item from inventory. remove_seh=0x" +
                HexString(static_cast<uintptr_t>(remove_exception));
        }
        return false;
    }

    DWORD attach_exception = 0;
    const bool lane_restored = AttachLocalNativeEquipmentObject(
        lane.state,
        previous_item_address,
        &attach_exception);
    const auto insert_address = ProcessMemory::Instance().ResolveGameAddressOrZero(
        kInventoryInsertOrStackItem);
    DWORD insert_exception = 0;
    const bool inventory_restored =
        insert_address != 0 &&
        CallInventoryInsertOrStackItemSafe(
            insert_address,
            inventory.item_list_root_address,
            target_item_address,
            &insert_exception);
    DWORD refresh_exception = 0;
    const bool progression_restored =
        player_actor_address != 0 &&
        refresh_address != 0 &&
        CallActorProgressionRefreshSafe(
            refresh_address,
            player_actor_address,
            &refresh_exception);
    if (!lane_restored || !inventory_restored || !progression_restored) {
        if (error_message != nullptr) {
            *error_message =
                "Native equipment rollback failed. lane_seh=0x" +
                HexString(static_cast<uintptr_t>(attach_exception)) +
                " inventory_seh=0x" +
                HexString(static_cast<uintptr_t>(insert_exception)) +
                " refresh_seh=0x" +
                HexString(static_cast<uintptr_t>(refresh_exception));
        }
        return false;
    }
    return true;
}

bool ExecuteLocalInventoryEquipNow(
    const PendingLocalInventoryEquipRequest& request,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    const auto fail = [&](std::string message) {
        if (error_message != nullptr) {
            *error_message = std::move(message);
        }
        return false;
    };

    SDModInventoryState inventory_before;
    if (request.recipe_uid == 0 ||
        !TryGetPlayerInventoryState(&inventory_before) ||
        !inventory_before.valid ||
        inventory_before.gameplay_scene_address == 0 ||
        inventory_before.gameplay_scene_address != request.gameplay_scene_address) {
        return fail("The queued native equipment request belongs to an inactive scene.");
    }

    const auto target = std::find_if(
        inventory_before.items.begin(),
        inventory_before.items.end(),
        [&](const SDModInventoryItemState& item) {
            return item.valid && item.recipe_uid == request.recipe_uid;
        });
    if (target == inventory_before.items.end() || target->item_address == 0) {
        return fail("The queued native equipment item is no longer in inventory.");
    }

    LocalNativeEquipLane lane;
    if (!ResolveLocalNativeEquipLane(inventory_before, target->type_id, &lane) ||
        lane.state.holder_address == 0 ||
        lane.state.holder_kind != lane.expected_holder_kind) {
        return fail("The stock native equipment sink does not accept this item type.");
    }

    auto& memory = ProcessMemory::Instance();
    SDModPlayerState player;
    const auto refresh_address = memory.ResolveGameAddressOrZero(
        kActorProgressionRefresh);
    if (kGameplayInventoryDirtyOffset == 0 ||
        !memory.TryWriteField(
            inventory_before.gameplay_scene_address,
            kGameplayInventoryDirtyOffset,
            static_cast<std::uint8_t>(1)) ||
        !TryGetPlayerState(&player) || !player.valid ||
        player.actor_address == 0 || refresh_address == 0 ||
        !memory.IsExecutableRange(refresh_address, 1)) {
        return fail("The local native inventory and progression refresh path is unavailable.");
    }

    const auto target_item_address = target->item_address;
    const auto previous_item_address = lane.state.current_object_address;
    DWORD remove_exception = 0;
    if (!RemoveNativeInventoryItemPointer(
            inventory_before,
            target_item_address,
            &remove_exception)) {
        return fail(
            "Native inventory removal failed with 0x" +
            HexString(static_cast<uintptr_t>(remove_exception)) + ".");
    }

    SDModInventoryState inventory_after_remove;
    if (!TryGetPlayerInventoryState(&inventory_after_remove) ||
        NativeInventoryContainsAddress(
            inventory_after_remove,
            target_item_address)) {
        std::string rollback_error;
        const bool rolled_back = RestoreLocalNativeEquipTransaction(
            inventory_before,
            lane,
            target_item_address,
            previous_item_address,
            false,
            player.actor_address,
            refresh_address,
            &rollback_error);
        return fail(
            "The stock inventory list did not release the requested item" +
            (rolled_back ? std::string(". The equip was rolled back.")
                         : "; " + rollback_error));
    }

    DWORD attach_exception = 0;
    if (!AttachLocalNativeEquipmentObject(
            lane.state,
            target_item_address,
            &attach_exception)) {
        std::string rollback_error;
        (void)RestoreLocalNativeEquipTransaction(
            inventory_before,
            lane,
            target_item_address,
            previous_item_address,
            false,
            player.actor_address,
            refresh_address,
            &rollback_error);
        return fail(
            "Native equipment attach failed with 0x" +
            HexString(static_cast<uintptr_t>(attach_exception)) +
            (rollback_error.empty() ? "." : "; " + rollback_error));
    }

    uintptr_t attached_item_address = 0;
    if (!memory.TryReadField(
            lane.state.holder_address,
            kVisualLaneHolderCurrentObjectOffset,
            &attached_item_address) ||
        attached_item_address != target_item_address) {
        std::string rollback_error;
        (void)RestoreLocalNativeEquipTransaction(
            inventory_before,
            lane,
            target_item_address,
            previous_item_address,
            false,
            player.actor_address,
            refresh_address,
            &rollback_error);
        return fail(
            "The stock equipment sink did not retain the requested item" +
            (rollback_error.empty() ? std::string(".") : "; " + rollback_error));
    }

    if (previous_item_address != 0 &&
        previous_item_address != target_item_address) {
        const auto insert_address = memory.ResolveGameAddressOrZero(
            kInventoryInsertOrStackItem);
        DWORD insert_exception = 0;
        if (insert_address == 0 ||
            !CallInventoryInsertOrStackItemSafe(
                insert_address,
                inventory_before.item_list_root_address,
                previous_item_address,
                &insert_exception)) {
            SDModInventoryState inventory_after_insert_failure;
            const bool previous_item_is_in_inventory =
                TryGetPlayerInventoryState(&inventory_after_insert_failure) &&
                NativeInventoryContainsAddress(
                    inventory_after_insert_failure,
                    previous_item_address);
            std::string rollback_error;
            const bool rolled_back = RestoreLocalNativeEquipTransaction(
                inventory_before,
                lane,
                target_item_address,
                previous_item_address,
                previous_item_is_in_inventory,
                player.actor_address,
                refresh_address,
                &rollback_error);
            return fail(
                "Returning the previous native equipment item to inventory failed with 0x" +
                HexString(static_cast<uintptr_t>(insert_exception)) +
                (rolled_back ? ". The equip was rolled back."
                             : "; " + rollback_error));
        }
    }

    DWORD refresh_exception = 0;
    if (!CallActorProgressionRefreshSafe(
            refresh_address,
            player.actor_address,
            &refresh_exception)) {
        std::string rollback_error;
        const bool rolled_back = RestoreLocalNativeEquipTransaction(
            inventory_before,
            lane,
            target_item_address,
            previous_item_address,
            previous_item_address != 0 &&
                previous_item_address != target_item_address,
            player.actor_address,
            refresh_address,
            &rollback_error);
        return fail(
            "Native progression refresh after equip failed with 0x" +
            HexString(static_cast<uintptr_t>(refresh_exception)) +
            (rolled_back ? ". The equip was rolled back."
                         : "; " + rollback_error));
    }

    SDModInventoryState inventory_after;
    LocalNativeEquipLane lane_after;
    const bool have_inventory_after = TryGetPlayerInventoryState(&inventory_after);
    const bool target_still_in_inventory =
        have_inventory_after &&
        NativeInventoryContainsAddress(inventory_after, target_item_address);
    const bool have_lane_after =
        have_inventory_after &&
        ResolveLocalNativeEquipLaneByHolder(
            inventory_after,
            target->type_id,
            lane.state.holder_address,
            &lane_after);
    if (!have_inventory_after ||
        target_still_in_inventory ||
        !have_lane_after ||
        lane_after.state.current_object_address != target_item_address ||
        lane_after.state.current_object_type_id != target->type_id ||
        lane_after.state.current_object_recipe_uid != request.recipe_uid) {
        std::string rollback_error;
        const bool rolled_back = RestoreLocalNativeEquipTransaction(
            inventory_before,
            lane,
            target_item_address,
            previous_item_address,
            previous_item_address != 0 &&
                previous_item_address != target_item_address,
            player.actor_address,
            refresh_address,
            &rollback_error);
        return fail(
            "Native equipment verification did not converge on the requested identity. "
            "snapshot=" + std::to_string(have_inventory_after ? 1 : 0) +
            " in_inventory=" + std::to_string(target_still_in_inventory ? 1 : 0) +
            " lane=" + std::to_string(have_lane_after ? 1 : 0) +
            " object=" + HexString(lane_after.state.current_object_address) +
            " type=" + HexString(lane_after.state.current_object_type_id) +
            " recipe=" + std::to_string(lane_after.state.current_object_recipe_uid) +
            (rolled_back ? std::string(". The equip was rolled back.")
                         : "; " + rollback_error));
    }

    Log(
        "native_equipment: equipped local inventory item. recipe_uid=" +
        std::to_string(request.recipe_uid) +
        " type_id=" + HexString(static_cast<uintptr_t>(target->type_id)) +
        " lane=" + lane.label +
        " previous=" + HexString(previous_item_address));
    return true;
}

}  // namespace
