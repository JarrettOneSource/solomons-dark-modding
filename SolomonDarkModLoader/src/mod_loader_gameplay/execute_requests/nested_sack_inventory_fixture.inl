enum class InventoryRootPointerLookup {
    Absent,
    Present,
    Unknown,
};

InventoryRootPointerLookup FindInventoryRootItemPointer(
    uintptr_t item_list_root,
    uintptr_t item_address) {
    if (item_list_root == 0 || item_address == 0) {
        return InventoryRootPointerLookup::Unknown;
    }

    auto& memory = ProcessMemory::Instance();
    int item_count = 0;
    uintptr_t item_array = 0;
    if (!memory.TryReadField(
            item_list_root,
            kGameplayItemListCountOffset,
            &item_count) ||
        !memory.TryReadField(
            item_list_root,
            kGameplayItemListItemsOffset,
            &item_array) ||
        item_count < 0 || item_count > 4096 ||
        (item_count > 0 &&
         (item_array == 0 ||
          !memory.IsReadableRange(
              item_array,
              static_cast<std::size_t>(item_count) * sizeof(std::uint32_t))))) {
        return InventoryRootPointerLookup::Unknown;
    }

    for (int index = 0; index < item_count; ++index) {
        std::uint32_t candidate = 0;
        if (!memory.TryReadValue(
                item_array +
                    static_cast<std::size_t>(index) * sizeof(std::uint32_t),
                &candidate)) {
            return InventoryRootPointerLookup::Unknown;
        }
        if (static_cast<uintptr_t>(candidate) == item_address) {
            return InventoryRootPointerLookup::Present;
        }
    }
    return InventoryRootPointerLookup::Absent;
}

bool ExecuteNestedSackInventoryFixtureNow(
    const PendingNestedSackInventoryFixture& request,
    std::string* error_message) {
    auto fail = [&](std::string message) {
        if (error_message != nullptr) {
            *error_message = std::move(message);
        }
        return false;
    };
    if (error_message != nullptr) {
        error_message->clear();
    }
    if ((request.potion_slot != 0 && request.potion_slot != 1) ||
        request.stack_count <= 0 || request.stack_count > 99) {
        return fail("Nested sack fixture parameters are invalid.");
    }

    SDModInventoryState inventory;
    if (!TryGetPlayerInventoryState(&inventory) || !inventory.valid ||
        inventory.item_list_root_address == 0) {
        return fail("Local native inventory is not active.");
    }

    auto& memory = ProcessMemory::Instance();
    const auto factory = memory.ResolveGameAddressOrZero(kGameObjectFactory);
    const auto factory_context =
        memory.ResolveGameAddressOrZero(kGameObjectFactoryContextGlobal);
    const auto insert =
        memory.ResolveGameAddressOrZero(kInventoryInsertOrStackItem);
    if (factory == 0 || factory_context == 0 || insert == 0 ||
        kSackItemInventoryRootPointerOffset == 0) {
        return fail("Nested sack fixture native seams are unavailable.");
    }

    DWORD exception_code = 0;
    uintptr_t sack = 0;
    if (!CallGameObjectFactorySafe(
            factory,
            factory_context,
            static_cast<int>(kInventorySackItemTypeId),
            &sack,
            &exception_code) ||
        sack == 0) {
        return fail(
            "Item_Sack construction failed with 0x" +
            HexString(static_cast<uintptr_t>(exception_code)) + ".");
    }

    uintptr_t nested_root = 0;
    if (!memory.TryReadField(
            sack,
            kSackItemInventoryRootPointerOffset,
            &nested_root) ||
        nested_root == 0) {
        DestroyUnownedNativeItem(sack, "nested_sack_fixture_root_missing");
        return fail("Constructed Item_Sack has no nested inventory root.");
    }

    uintptr_t potion = 0;
    exception_code = 0;
    if (!CallGameObjectFactorySafe(
            factory,
            factory_context,
            static_cast<int>(kInventoryPotionItemTypeId),
            &potion,
            &exception_code) ||
        potion == 0) {
        DestroyUnownedNativeItem(sack, "nested_sack_fixture_potion_ctor_failed");
        return fail(
            "Potion construction failed with 0x" +
            HexString(static_cast<uintptr_t>(exception_code)) + ".");
    }
    if (!memory.TryWriteField(potion, kItemSlotOffset, request.potion_slot) ||
        !memory.TryWriteField(
            potion,
            kPotionStackCountOffset,
            request.stack_count)) {
        DestroyUnownedNativeItem(potion, "nested_sack_fixture_potion_seed_failed");
        DestroyUnownedNativeItem(sack, "nested_sack_fixture_potion_seed_failed");
        return fail("Unable to seed the nested potion state.");
    }

    exception_code = 0;
    const bool nested_insert_called = CallInventoryInsertOrStackItemSafe(
        insert,
        nested_root,
        potion,
        &exception_code);
    const auto nested_lookup = FindInventoryRootItemPointer(nested_root, potion);
    if (nested_lookup != InventoryRootPointerLookup::Present) {
        if (nested_lookup == InventoryRootPointerLookup::Absent) {
            DestroyUnownedNativeItem(
                potion,
                "nested_sack_fixture_nested_insert_failed");
            DestroyUnownedNativeItem(
                sack,
                "nested_sack_fixture_nested_insert_failed");
        }
        return fail(
            "Nested potion insertion did not converge. called=" +
            std::to_string(nested_insert_called ? 1 : 0) +
            " seh=0x" + HexString(static_cast<uintptr_t>(exception_code)) + ".");
    }

    exception_code = 0;
    const bool sack_insert_called = CallInventoryInsertOrStackItemSafe(
        insert,
        inventory.item_list_root_address,
        sack,
        &exception_code);
    const auto sack_lookup = FindInventoryRootItemPointer(
        inventory.item_list_root_address,
        sack);
    if (sack_lookup != InventoryRootPointerLookup::Present) {
        if (sack_lookup == InventoryRootPointerLookup::Absent) {
            DestroyUnownedNativeItem(sack, "nested_sack_fixture_owner_insert_failed");
        }
        return fail(
            "Sack insertion did not converge. called=" +
            std::to_string(sack_insert_called ? 1 : 0) +
            " seh=0x" + HexString(static_cast<uintptr_t>(exception_code)) + ".");
    }

    const std::uint8_t dirty = 1;
    (void)memory.TryWriteField(
        inventory.gameplay_scene_address,
        kGameplayInventoryDirtyOffset,
        dirty);
    Log(
        "nested_sack_fixture: inserted owner-native sack=" + HexString(sack) +
        " nested_root=" + HexString(nested_root) +
        " potion=" + HexString(potion) +
        " slot=" + std::to_string(request.potion_slot) +
        " stack=" + std::to_string(request.stack_count));
    return true;
}
