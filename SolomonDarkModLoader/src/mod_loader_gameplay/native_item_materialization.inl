constexpr std::size_t kNativeItemDropCarrierSize = 0x150;
constexpr std::size_t kNativeItemDropPayloadOffset = 0x14C;
constexpr int kNativeItemRecipeCatalogMaxEntries = 16384;

bool TryReadNativeItemRecipeNameEquals(
    uintptr_t recipe_address,
    std::string_view expected_name) {
    if (recipe_address == 0 ||
        expected_name.empty() ||
        expected_name.size() > 128 ||
        kItemRecipeDefinitionNameOffset == 0 ||
        kNativeStringDataOffset == 0 ||
        kNativeStringLengthOffset == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto string_address = recipe_address + kItemRecipeDefinitionNameOffset;
    uintptr_t text_address = 0;
    std::int32_t text_length = 0;
    if (!memory.TryReadField(
            string_address,
            kNativeStringDataOffset,
            &text_address) ||
        !memory.TryReadField(
            string_address,
            kNativeStringLengthOffset,
            &text_length) ||
        text_address == 0 ||
        text_length != static_cast<std::int32_t>(expected_name.size())) {
        return false;
    }

    std::string actual_name;
    return memory.TryReadCString(
               text_address,
               static_cast<std::size_t>(text_length) + 1,
               &actual_name) &&
           actual_name == expected_name;
}

bool CallItemRecipeCloneSafe(
    uintptr_t clone_address,
    uintptr_t recipe_address,
    uintptr_t* item_address,
    DWORD* exception_code) {
    if (item_address != nullptr) {
        *item_address = 0;
    }
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    auto* clone = reinterpret_cast<ItemRecipeCloneFn>(clone_address);
    if (clone == nullptr || recipe_address == 0 || item_address == nullptr) {
        return false;
    }

    __try {
        *item_address = reinterpret_cast<uintptr_t>(
            clone(reinterpret_cast<void*>(recipe_address)));
        return *item_address != 0;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallItemDropCarrierResetSafe(
    uintptr_t reset_address,
    uintptr_t carrier_address,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    auto* reset = reinterpret_cast<ItemDropCarrierResetFn>(reset_address);
    if (reset == nullptr || carrier_address == 0) {
        return false;
    }

    __try {
        reset(reinterpret_cast<void*>(carrier_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallItemDropPostRegisterSafe(
    uintptr_t post_register_address,
    uintptr_t actor_address,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    auto* post_register = reinterpret_cast<ItemDropPostRegisterFn>(post_register_address);
    if (post_register == nullptr || actor_address == 0) {
        return false;
    }

    __try {
        post_register(reinterpret_cast<void*>(actor_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool TryResolveNativeItemRecipe(
    std::uint32_t recipe_uid,
    std::uint32_t expected_item_type_id,
    uintptr_t* recipe_address,
    std::uint32_t* resolved_item_type_id,
    std::string* error_message) {
    if (recipe_address != nullptr) {
        *recipe_address = 0;
    }
    if (resolved_item_type_id != nullptr) {
        *resolved_item_type_id = 0;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (recipe_address == nullptr || recipe_uid == 0) {
        if (error_message != nullptr) {
            *error_message = "Native item recipe lookup requires a non-zero recipe UID.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto count_address = memory.ResolveGameAddressOrZero(kItemRecipeCountGlobal);
    const auto entries_address = memory.ResolveGameAddressOrZero(kItemRecipeEntriesGlobal);
    std::int32_t recipe_count = 0;
    uintptr_t recipe_entries = 0;
    if (count_address == 0 ||
        entries_address == 0 ||
        kItemRecipeDefinitionUidOffset == 0 ||
        kItemRecipeDefinitionTypeIdOffset == 0 ||
        !memory.TryReadValue(count_address, &recipe_count) ||
        !memory.TryReadValue(entries_address, &recipe_entries) ||
        recipe_count <= 0 ||
        recipe_count > kNativeItemRecipeCatalogMaxEntries ||
        recipe_entries == 0 ||
        !memory.IsReadableRange(
            recipe_entries,
            static_cast<std::size_t>(recipe_count) * sizeof(std::uint32_t))) {
        if (error_message != nullptr) {
            *error_message = "The stock item recipe catalog is unavailable.";
        }
        return false;
    }

    for (std::int32_t index = 0; index < recipe_count; ++index) {
        std::uint32_t raw_recipe_address = 0;
        if (!memory.TryReadValue(
                recipe_entries + static_cast<std::size_t>(index) * sizeof(std::uint32_t),
                &raw_recipe_address) ||
            raw_recipe_address == 0) {
            continue;
        }

        const auto candidate = static_cast<uintptr_t>(raw_recipe_address);
        std::uint32_t candidate_uid = 0;
        std::uint32_t candidate_type_id = 0;
        if (!memory.TryReadField(
                candidate,
                kItemRecipeDefinitionUidOffset,
                &candidate_uid) ||
            candidate_uid != recipe_uid ||
            !memory.TryReadField(
                candidate,
                kItemRecipeDefinitionTypeIdOffset,
                &candidate_type_id)) {
            continue;
        }
        if (expected_item_type_id != 0 && candidate_type_id != expected_item_type_id) {
            if (error_message != nullptr) {
                *error_message =
                    "Item recipe UID resolved to type 0x" +
                    HexString(static_cast<uintptr_t>(candidate_type_id)) +
                    " instead of 0x" +
                    HexString(static_cast<uintptr_t>(expected_item_type_id)) + ".";
            }
            return false;
        }

        *recipe_address = candidate;
        if (resolved_item_type_id != nullptr) {
            *resolved_item_type_id = candidate_type_id;
        }
        return true;
    }

    if (error_message != nullptr) {
        *error_message =
            "Item recipe UID " + std::to_string(recipe_uid) +
            " was not present in the stock catalog.";
    }
    return false;
}

bool TryResolveNativeItemRecipeByNameInternal(
    std::string_view recipe_name,
    std::uint32_t expected_item_type_id,
    std::uint32_t* recipe_uid,
    std::string* error_message) {
    if (recipe_uid != nullptr) {
        *recipe_uid = 0;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (recipe_uid == nullptr ||
        recipe_name.empty() ||
        recipe_name.size() > 128 ||
        expected_item_type_id == 0) {
        if (error_message != nullptr) {
            *error_message = "Native item recipe name lookup requires exact name and type identity.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto count_address = memory.ResolveGameAddressOrZero(kItemRecipeCountGlobal);
    const auto entries_address = memory.ResolveGameAddressOrZero(kItemRecipeEntriesGlobal);
    std::int32_t recipe_count = 0;
    uintptr_t recipe_entries = 0;
    if (count_address == 0 ||
        entries_address == 0 ||
        kItemRecipeDefinitionUidOffset == 0 ||
        kItemRecipeDefinitionNameOffset == 0 ||
        kItemRecipeDefinitionTypeIdOffset == 0 ||
        !memory.TryReadValue(count_address, &recipe_count) ||
        !memory.TryReadValue(entries_address, &recipe_entries) ||
        recipe_count <= 0 ||
        recipe_count > kNativeItemRecipeCatalogMaxEntries ||
        recipe_entries == 0 ||
        !memory.IsReadableRange(
            recipe_entries,
            static_cast<std::size_t>(recipe_count) * sizeof(std::uint32_t))) {
        if (error_message != nullptr) {
            *error_message = "The stock item recipe catalog is unavailable.";
        }
        return false;
    }

    std::uint32_t matched_uid = 0;
    for (std::int32_t index = 0; index < recipe_count; ++index) {
        std::uint32_t raw_recipe_address = 0;
        if (!memory.TryReadValue(
                recipe_entries + static_cast<std::size_t>(index) * sizeof(std::uint32_t),
                &raw_recipe_address) ||
            raw_recipe_address == 0) {
            continue;
        }
        const auto candidate = static_cast<uintptr_t>(raw_recipe_address);
        std::uint32_t candidate_type_id = 0;
        std::uint32_t candidate_uid = 0;
        if (!memory.TryReadField(
                candidate,
                kItemRecipeDefinitionTypeIdOffset,
                &candidate_type_id) ||
            candidate_type_id != expected_item_type_id ||
            !TryReadNativeItemRecipeNameEquals(candidate, recipe_name) ||
            !memory.TryReadField(
                candidate,
                kItemRecipeDefinitionUidOffset,
                &candidate_uid) ||
            candidate_uid == 0) {
            continue;
        }
        if (matched_uid != 0) {
            if (error_message != nullptr) {
                *error_message =
                    "The native item recipe name/type identity is ambiguous: " +
                    std::string(recipe_name) + ".";
            }
            return false;
        }
        matched_uid = candidate_uid;
    }

    if (matched_uid == 0) {
        if (error_message != nullptr) {
            *error_message =
                "The native item recipe is not loaded: " + std::string(recipe_name) + ".";
        }
        return false;
    }
    *recipe_uid = matched_uid;
    return true;
}

void DestroyUnownedNativeItem(uintptr_t item_address, std::string_view reason) {
    if (item_address == 0) {
        return;
    }
    DWORD exception_code = 0;
    if (!CallScalarDeletingDestructorSafe(item_address, 1, &exception_code)) {
        Log(
            "native_item: failed to destroy unowned item. reason=" +
            std::string(reason) +
            " item=" + HexString(item_address) +
            " seh=" + HexString(static_cast<uintptr_t>(exception_code)));
    }
}

bool CloneNativeItemFromRecipe(
    std::uint32_t recipe_uid,
    std::uint32_t expected_item_type_id,
    const std::array<std::uint8_t, multiplayer::kParticipantVisualLinkColorBlockBytes>&
        wearable_color_state,
    bool wearable_color_state_valid,
    uintptr_t* item_address,
    std::string* error_message) {
    if (item_address != nullptr) {
        *item_address = 0;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (item_address == nullptr || recipe_uid == 0 || expected_item_type_id == 0) {
        if (error_message != nullptr) {
            *error_message = "Native item cloning requires exact recipe and type identity.";
        }
        return false;
    }

    uintptr_t recipe_address = 0;
    if (!TryResolveNativeItemRecipe(
            recipe_uid,
            expected_item_type_id,
            &recipe_address,
            nullptr,
            error_message)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto clone_address = memory.ResolveGameAddressOrZero(kItemRecipeClone);
    DWORD exception_code = 0;
    uintptr_t built_item_address = 0;
    if (clone_address == 0 ||
        !CallItemRecipeCloneSafe(
            clone_address,
            recipe_address,
            &built_item_address,
            &exception_code) ||
        built_item_address == 0) {
        if (error_message != nullptr) {
            *error_message =
                "ItemRecipe clone failed with 0x" +
                HexString(static_cast<uintptr_t>(exception_code)) + ".";
        }
        return false;
    }

    if (wearable_color_state_valid &&
        (expected_item_type_id == kStandaloneWizardHatVisualTypeId ||
         expected_item_type_id == kStandaloneWizardRobeVisualTypeId) &&
        !memory.TryWrite(
            built_item_address + kItemWearableColorStateOffset,
            wearable_color_state.data(),
            wearable_color_state.size())) {
        DestroyUnownedNativeItem(built_item_address, "wearable_color_seed_failed");
        if (error_message != nullptr) {
            *error_message = "Failed to apply the authoritative wearable color state.";
        }
        return false;
    }

    *item_address = built_item_address;
    return true;
}

bool BuildNativeItemFromLootSnapshot(
    const multiplayer::LootDropSnapshot& drop,
    uintptr_t* item_address,
    std::string* error_message) {
    if (item_address != nullptr) {
        *item_address = 0;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (item_address == nullptr || drop.item_type_id == 0) {
        if (error_message != nullptr) {
            *error_message = "Native item materialization requires an exact item identity.";
        }
        return false;
    }

    if (drop.item_recipe_uid != 0) {
        return CloneNativeItemFromRecipe(
            drop.item_recipe_uid,
            drop.item_type_id,
            drop.item_color_state,
            drop.item_color_state_valid,
            item_address,
            error_message);
    }

    constexpr std::int32_t kNativeMiscItemSubtypeMin = 0;
    constexpr std::int32_t kNativeMiscItemSubtypeMax = 3;
    if (drop.item_type_id != kInventoryMiscItemTypeId ||
        drop.item_slot < kNativeMiscItemSubtypeMin ||
        drop.item_slot > kNativeMiscItemSubtypeMax) {
        if (error_message != nullptr) {
            *error_message = "Unsupported non-recipe native item identity.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto factory_address = memory.ResolveGameAddressOrZero(kGameObjectFactory);
    const auto factory_context_address =
        memory.ResolveGameAddressOrZero(kGameObjectFactoryContextGlobal);
    uintptr_t built_item_address = 0;
    DWORD exception_code = 0;
    if (factory_address == 0 ||
        factory_context_address == 0 ||
        !CallGameObjectFactorySafe(
            factory_address,
            factory_context_address,
            static_cast<int>(kInventoryMiscItemTypeId),
            &built_item_address,
            &exception_code) ||
        built_item_address == 0) {
        if (error_message != nullptr) {
            *error_message =
                "Misc item factory creation failed with 0x" +
                HexString(static_cast<uintptr_t>(exception_code)) + ".";
        }
        return false;
    }

    if (!memory.TryWriteField(
            built_item_address,
            kItemSlotOffset,
            drop.item_slot)) {
        DestroyUnownedNativeItem(built_item_address, "misc_item_slot_seed_failed");
        if (error_message != nullptr) {
            *error_message = "Failed to seed the exact misc item subtype.";
        }
        return false;
    }

    *item_address = built_item_address;
    return true;
}

bool SpawnNativeItemDropFromRecipe(
    const multiplayer::LootDropSnapshot& drop,
    uintptr_t* carrier_address,
    uintptr_t* held_item_address,
    std::string* error_message) {
    if (carrier_address != nullptr) {
        *carrier_address = 0;
    }
    if (held_item_address != nullptr) {
        *held_item_address = 0;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (carrier_address == nullptr ||
        held_item_address == nullptr ||
        drop.drop_kind != multiplayer::LootDropKind::Item ||
        drop.item_type_id == 0 ||
        (drop.item_recipe_uid == 0 &&
         (drop.item_type_id != kInventoryMiscItemTypeId ||
          drop.item_slot < 0 ||
          drop.item_slot > 3)) ||
        !std::isfinite(drop.position_x) ||
        !std::isfinite(drop.position_y)) {
        if (error_message != nullptr) {
            *error_message = "Exact native item materialization metadata is invalid.";
        }
        return false;
    }

    uintptr_t arena_address = 0;
    if (!TryResolveArena(&arena_address) || arena_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Arena is not active.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto allocate_address = memory.ResolveGameAddressOrZero(kObjectAllocate);
    const auto carrier_ctor_address = memory.ResolveGameAddressOrZero(kItemDropCarrierCtor);
    const auto carrier_reset_address = memory.ResolveGameAddressOrZero(kItemDropCarrierReset);
    const auto register_address = memory.ResolveGameAddressOrZero(kActorWorldRegister);
    const auto free_address = memory.ResolveGameAddressOrZero(kGameFree);
    if (allocate_address == 0 ||
        carrier_ctor_address == 0 ||
        carrier_reset_address == 0 ||
        register_address == 0 ||
        free_address == 0 ||
        kItemDropHeldItemOffset == 0) {
        if (error_message != nullptr) {
            *error_message = "Exact native item materialization seams are unavailable.";
        }
        return false;
    }

    uintptr_t item_address = 0;
    if (!BuildNativeItemFromLootSnapshot(
            drop,
            &item_address,
            error_message)) {
        return false;
    }

    DWORD exception_code = 0;

    uintptr_t carrier_memory = 0;
    if (!CallGameObjectAllocateSafe(
            allocate_address,
            kNativeItemDropCarrierSize,
            &carrier_memory,
            &exception_code) ||
        carrier_memory == 0) {
        DestroyUnownedNativeItem(item_address, "carrier_allocate_failed");
        if (error_message != nullptr) {
            *error_message =
                "Item-drop carrier allocation failed with 0x" +
                HexString(static_cast<uintptr_t>(exception_code)) + ".";
        }
        return false;
    }

    uintptr_t built_carrier = 0;
    if (!CallRawObjectCtorSafe(
            carrier_ctor_address,
            reinterpret_cast<void*>(carrier_memory),
            &built_carrier,
            &exception_code) ||
        built_carrier == 0) {
        DWORD free_exception_code = 0;
        (void)CallGameFreeSafe(free_address, carrier_memory, &free_exception_code);
        DestroyUnownedNativeItem(item_address, "carrier_ctor_failed");
        if (error_message != nullptr) {
            *error_message =
                "Item-drop carrier construction failed with 0x" +
                HexString(static_cast<uintptr_t>(exception_code)) + ".";
        }
        return false;
    }

    const bool carrier_owns_item =
        memory.TryWriteField(built_carrier, kItemDropHeldItemOffset, item_address);
    if (!carrier_owns_item) {
        DestroyUnownedNativeItem(built_carrier, "carrier_held_item_seed_failed");
        DestroyUnownedNativeItem(item_address, "carrier_held_item_seed_failed");
        if (error_message != nullptr) {
            *error_message = "Item-drop carrier could not take ownership of the item.";
        }
        return false;
    }

    const std::uint32_t drop_payload = drop.lifetime;
    const bool seeded =
        memory.TryWriteField(built_carrier, kActorPositionXOffset, drop.position_x) &&
        memory.TryWriteField(built_carrier, kActorPositionYOffset, drop.position_y) &&
        memory.TryWriteField(built_carrier, kNativeItemDropPayloadOffset, drop_payload) &&
        CallItemDropCarrierResetSafe(
            carrier_reset_address,
            built_carrier,
            &exception_code);
    if (!seeded ||
        !CallActorWorldRegisterSafe(
            register_address,
            arena_address,
            0,
            built_carrier,
            -1,
            0,
            &exception_code)) {
        DestroyUnownedNativeItem(built_carrier, "carrier_seed_or_register_failed");
        if (error_message != nullptr) {
            *error_message =
                "Item-drop carrier registration failed with 0x" +
                HexString(static_cast<uintptr_t>(exception_code)) + ".";
        }
        return false;
    }

    const auto post_register_address =
        memory.ResolveGameAddressOrZero(kItemDropPostRegister);
    DWORD post_exception_code = 0;
    if (post_register_address != 0 &&
        !CallItemDropPostRegisterSafe(
            post_register_address,
            built_carrier,
            &post_exception_code)) {
        Log(
            "native_item: stock post-register callback failed. actor=" +
            HexString(built_carrier) +
            " seh=" + HexString(static_cast<uintptr_t>(post_exception_code)));
    }

    *carrier_address = built_carrier;
    *held_item_address = item_address;
    return true;
}
