enum class NativeInventoryCreditOutcome {
    Applied,
    Retry,
    FailedBeforeApply,
    ApplyStateUnknown,
};

void ClearNativeInventoryCreditState() {
    std::lock_guard<std::mutex> lock(
        g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    auto& state = g_gameplay_keyboard_injection;
    state.pending_native_inventory_credits.clear();
    state.pending_native_inventory_credit_drop_ids.clear();
    state.completed_native_inventory_credit_drop_ids.clear();
    state.native_inventory_credit_run_nonce = 0;
}

bool CallInventoryInsertOrStackItemSafe(
    uintptr_t function_address,
    uintptr_t inventory_root_address,
    uintptr_t item_address,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    auto* insert_item = reinterpret_cast<InventoryInsertOrStackItemFn>(function_address);
    if (insert_item == nullptr || inventory_root_address == 0 || item_address == 0) {
        return false;
    }

    __try {
        // The verified stock pickup call at 0x005E6D80 supplies both flags.
        // The first enables same-slot potion stacking; the second removes the
        // starter placeholder item when necessary.
        insert_item(
            reinterpret_cast<void*>(inventory_root_address),
            reinterpret_cast<void*>(item_address),
            1,
            1);
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool TryGetNativeInventoryQuantity(
    const SDModInventoryState& inventory,
    std::uint32_t item_type_id,
    std::uint32_t item_recipe_uid,
    std::int32_t item_slot,
    std::int64_t* quantity) {
    if (quantity == nullptr || !inventory.valid || item_type_id == 0) {
        return false;
    }

    const bool is_potion = item_type_id == kReplicatedLootPotionItemTypeId;
    if ((is_potion && (item_slot < 0 || item_slot > 1)) ||
        (!is_potion && item_recipe_uid == 0)) {
        return false;
    }

    std::int64_t total = 0;
    for (const auto& item : inventory.items) {
        if (!item.valid || item.type_id != item_type_id) {
            continue;
        }
        if (is_potion) {
            if (item.slot != item_slot) {
                continue;
            }
            total += (std::max)(item.stack_count, 1);
        } else if (item.recipe_uid == item_recipe_uid) {
            ++total;
        }
    }
    *quantity = total;
    return true;
}

bool IsNativeInventoryCreditCompleted(
    std::uint32_t run_nonce,
    std::uint64_t network_drop_id) {
    if (run_nonce == 0 || network_drop_id == 0) {
        return false;
    }
    std::lock_guard<std::mutex> lock(
        g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    return g_gameplay_keyboard_injection.native_inventory_credit_run_nonce == run_nonce &&
           g_gameplay_keyboard_injection.completed_native_inventory_credit_drop_ids.find(
               network_drop_id) !=
           g_gameplay_keyboard_injection.completed_native_inventory_credit_drop_ids.end();
}

NativeInventoryCreditOutcome ExecuteNativeInventoryCreditNow(
    const PendingNativeInventoryCredit& request,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    const auto fail = [&](NativeInventoryCreditOutcome outcome, std::string message) {
        if (error_message != nullptr) {
            *error_message = std::move(message);
        }
        return outcome;
    };

    const bool is_potion =
        request.item_type_id == kReplicatedLootPotionItemTypeId;
    const bool is_recipe_item =
        request.item_type_id != 0 &&
        !is_potion &&
        request.item_recipe_uid != 0;
    if (!multiplayer::IsLocalTransportClient() ||
        request.authority_participant_id == 0 ||
        request.run_nonce == 0 ||
        request.network_drop_id == 0 ||
        (!is_potion && !is_recipe_item) ||
        (is_potion && (request.item_slot < 0 || request.item_slot > 1)) ||
        request.stack_count <= 0 ||
        request.inventory_revision == 0) {
        return fail(
            NativeInventoryCreditOutcome::FailedBeforeApply,
            "native inventory credit metadata is invalid");
    }

    const auto runtime_state = multiplayer::SnapshotRuntimeState();
    const auto* local_participant = multiplayer::FindLocalParticipant(runtime_state);
    if (local_participant == nullptr ||
        !local_participant->runtime.valid ||
        !local_participant->runtime.in_run) {
        return fail(
            NativeInventoryCreditOutcome::Retry,
            "local multiplayer participant is not ready in a run");
    }
    if (local_participant->runtime.run_nonce != 0 &&
        local_participant->runtime.run_nonce != request.run_nonce) {
        return fail(
            NativeInventoryCreditOutcome::FailedBeforeApply,
            "native inventory credit belongs to an inactive run");
    }

    SDModSceneState scene_state;
    if (!TryGetSceneState(&scene_state) ||
        !scene_state.valid ||
        (scene_state.kind != "arena" && scene_state.name != "testrun")) {
        return fail(
            NativeInventoryCreditOutcome::Retry,
            "native gameplay inventory is not in an arena scene");
    }

    SDModInventoryState inventory_before;
    if (!TryGetPlayerInventoryState(&inventory_before) || !inventory_before.valid) {
        return fail(
            NativeInventoryCreditOutcome::Retry,
            "native gameplay inventory root is unavailable");
    }
    std::int64_t quantity_before = 0;
    if (!TryGetNativeInventoryQuantity(
            inventory_before,
            request.item_type_id,
            request.item_recipe_uid,
            request.item_slot,
            &quantity_before)) {
        return fail(
            NativeInventoryCreditOutcome::Retry,
            "native inventory baseline is unavailable");
    }

    auto& memory = ProcessMemory::Instance();
    const auto insert_function_address =
        memory.ResolveGameAddressOrZero(kInventoryInsertOrStackItem);
    if (insert_function_address == 0) {
        return fail(
            NativeInventoryCreditOutcome::FailedBeforeApply,
            "Inventory_InsertOrStackItem seam is unavailable");
    }

    ReplicatedLootPresentationBinding carrier_binding;
    bool have_carrier = false;
    {
        std::lock_guard<std::mutex> lock(g_replicated_loot_presentation_mutex);
        const auto it = std::find_if(
            g_replicated_loot_presentations.begin(),
            g_replicated_loot_presentations.end(),
            [&](const ReplicatedLootPresentationBinding& binding) {
                return binding.network_drop_id == request.network_drop_id;
            });
        if (it != g_replicated_loot_presentations.end()) {
            carrier_binding = *it;
            g_replicated_loot_presentations.erase(it);
            have_carrier = true;
        }
    }

    const auto expected_drop_kind = is_potion
        ? multiplayer::LootDropKind::Potion
        : multiplayer::LootDropKind::Item;
    if (have_carrier &&
        (carrier_binding.authority_participant_id != request.authority_participant_id ||
         carrier_binding.run_nonce != request.run_nonce ||
         carrier_binding.drop_kind != expected_drop_kind ||
         carrier_binding.native_type_id != kReplicatedLootItemDropNativeTypeId ||
         carrier_binding.item_type_id != request.item_type_id ||
         (!is_potion && carrier_binding.item_recipe_uid != request.item_recipe_uid) ||
         !IsSceneActorAddressPresent(carrier_binding.actor_address))) {
        if (carrier_binding.actor_address != 0 &&
            IsSceneActorAddressPresent(carrier_binding.actor_address)) {
            DWORD remove_exception_code = 0;
            (void)RemoveReplicatedLootPresentationActor(
                carrier_binding,
                &remove_exception_code);
        }
        carrier_binding = {};
        have_carrier = false;
    }

    uintptr_t held_item_address = 0;
    std::uint32_t held_item_type_id = 0;
    std::uint32_t held_item_recipe_uid = 0;
    if (have_carrier) {
        if (!memory.TryReadField(
                carrier_binding.actor_address,
                kItemDropHeldItemOffset,
                &held_item_address) ||
            held_item_address == 0 ||
            !memory.TryReadField(
                held_item_address,
                kGameObjectTypeIdOffset,
                &held_item_type_id) ||
            held_item_type_id != request.item_type_id ||
            (!is_potion &&
             (!memory.TryReadField(
                  held_item_address,
                  kItemInstanceRecipeUidOffset,
                  &held_item_recipe_uid) ||
              held_item_recipe_uid != request.item_recipe_uid))) {
            DWORD remove_exception_code = 0;
            (void)RemoveReplicatedLootPresentationActor(
                carrier_binding,
                &remove_exception_code);
            carrier_binding = {};
            have_carrier = false;
            held_item_address = 0;
        }
    }

    if (!have_carrier) {
        SDModPlayerState player_state;
        if (!TryGetPlayerState(&player_state) ||
            !player_state.valid ||
            !std::isfinite(player_state.x) ||
            !std::isfinite(player_state.y)) {
            return fail(
                NativeInventoryCreditOutcome::Retry,
                "local player position is unavailable for item materialization");
        }

        multiplayer::LootDropSnapshot native_drop;
        native_drop.network_drop_id = request.network_drop_id;
        native_drop.native_type_id = kReplicatedLootItemDropNativeTypeId;
        native_drop.drop_kind = expected_drop_kind;
        native_drop.active = true;
        native_drop.item_type_id = request.item_type_id;
        native_drop.item_recipe_uid = request.item_recipe_uid;
        native_drop.item_color_state_valid = request.item_color_state_valid;
        native_drop.item_color_state = request.item_color_state;
        native_drop.item_slot = request.item_slot;
        native_drop.stack_count = request.stack_count;
        native_drop.amount = request.stack_count;
        native_drop.amount_tier = request.item_slot;
        native_drop.position_x = player_state.x;
        native_drop.position_y = player_state.y;

        uintptr_t carrier_actor_address = 0;
        std::string spawn_error;
        if (!SpawnReplicatedLootPresentationActor(
                native_drop,
                &carrier_actor_address,
                &spawn_error) ||
            carrier_actor_address == 0) {
            return fail(
                NativeInventoryCreditOutcome::Retry,
                "unable to materialize native item carrier: " + spawn_error);
        }

        carrier_binding.network_drop_id = request.network_drop_id;
        carrier_binding.authority_participant_id = request.authority_participant_id;
        carrier_binding.run_nonce = request.run_nonce;
        carrier_binding.native_type_id = kReplicatedLootItemDropNativeTypeId;
        carrier_binding.drop_kind = expected_drop_kind;
        carrier_binding.actor_address = carrier_actor_address;
        carrier_binding.active = true;
        carrier_binding.x = player_state.x;
        carrier_binding.y = player_state.y;
        carrier_binding.item_type_id = request.item_type_id;
        carrier_binding.item_recipe_uid = request.item_recipe_uid;
        have_carrier = true;

        if (!memory.TryReadField(
                carrier_actor_address,
                kItemDropHeldItemOffset,
                &held_item_address) ||
            held_item_address == 0 ||
            !memory.TryReadField(
                held_item_address,
                kGameObjectTypeIdOffset,
                &held_item_type_id) ||
            held_item_type_id != request.item_type_id ||
            (!is_potion &&
             (!memory.TryReadField(
                  held_item_address,
                  kItemInstanceRecipeUidOffset,
                  &held_item_recipe_uid) ||
              held_item_recipe_uid != request.item_recipe_uid))) {
            DWORD remove_exception_code = 0;
            (void)RemoveReplicatedLootPresentationActor(
                carrier_binding,
                &remove_exception_code);
            return fail(
                NativeInventoryCreditOutcome::Retry,
                "materialized item carrier did not expose the expected held item");
        }
    }

    bool authoritative_fields_seeded = true;
    if (is_potion) {
        authoritative_fields_seeded =
            memory.TryWriteField(held_item_address, kItemSlotOffset, request.item_slot) &&
            memory.TryWriteField(
                held_item_address,
                kPotionStackCountOffset,
                request.stack_count);
    } else if (request.item_color_state_valid &&
               (request.item_type_id == kStandaloneWizardHatVisualTypeId ||
                request.item_type_id == kStandaloneWizardRobeVisualTypeId)) {
        authoritative_fields_seeded = memory.TryWrite(
            held_item_address + kItemWearableColorStateOffset,
            request.item_color_state.data(),
            request.item_color_state.size());
    }
    if (!authoritative_fields_seeded) {
        DWORD remove_exception_code = 0;
        (void)RemoveReplicatedLootPresentationActor(
            carrier_binding,
            &remove_exception_code);
        return fail(
            NativeInventoryCreditOutcome::Retry,
            "unable to seed the authoritative native item fields");
    }

    const uintptr_t cleared_held_item_address = 0;
    if (!memory.TryWriteField(
            carrier_binding.actor_address,
            kItemDropHeldItemOffset,
            cleared_held_item_address)) {
        DWORD remove_exception_code = 0;
        (void)RemoveReplicatedLootPresentationActor(
            carrier_binding,
            &remove_exception_code);
        return fail(
            NativeInventoryCreditOutcome::Retry,
            "unable to transfer native item ownership out of its carrier");
    }

    DWORD insert_exception_code = 0;
    const bool insert_called = CallInventoryInsertOrStackItemSafe(
        insert_function_address,
        inventory_before.item_list_root_address,
        held_item_address,
        &insert_exception_code);

    DWORD remove_exception_code = 0;
    const bool carrier_removed = RemoveReplicatedLootPresentationActor(
        carrier_binding,
        &remove_exception_code);
    if (!carrier_removed) {
        Log(
            "native_inventory: item carrier removal failed after ownership transfer. "
            "network_drop_id=" + std::to_string(request.network_drop_id) +
            " actor=" + HexString(carrier_binding.actor_address) +
            " seh=" + HexString(static_cast<uintptr_t>(remove_exception_code)));
    }

    if (!insert_called) {
        return fail(
            NativeInventoryCreditOutcome::ApplyStateUnknown,
            "Inventory_InsertOrStackItem raised 0x" +
                HexString(static_cast<uintptr_t>(insert_exception_code)));
    }

    SDModInventoryState inventory_after;
    std::int64_t quantity_after = 0;
    if (!TryGetPlayerInventoryState(&inventory_after) ||
        !TryGetNativeInventoryQuantity(
            inventory_after,
            request.item_type_id,
            request.item_recipe_uid,
            request.item_slot,
            &quantity_after)) {
        return fail(
            NativeInventoryCreditOutcome::ApplyStateUnknown,
            "native item insertion completed but its result could not be read");
    }

    const auto expected_quantity_after =
        quantity_before + static_cast<std::int64_t>(is_potion ? request.stack_count : 1);
    if (quantity_after < expected_quantity_after) {
        return fail(
            NativeInventoryCreditOutcome::ApplyStateUnknown,
            "native item insertion did not increase the requested inventory identity: before=" +
                std::to_string(quantity_before) +
                " after=" + std::to_string(quantity_after) +
                " expected=" + std::to_string(expected_quantity_after));
    }

    const bool ledger_converged =
        multiplayer::MarkLocalInventoryNativeConverged(request.inventory_revision);
    Log(
        "native_inventory: applied authoritative item pickup. network_drop_id=" +
        std::to_string(request.network_drop_id) +
        " item_type_id=" + HexString(static_cast<uintptr_t>(request.item_type_id)) +
        " item_recipe_uid=" + std::to_string(request.item_recipe_uid) +
        " slot=" + std::to_string(request.item_slot) +
        " stack=" + std::to_string(request.stack_count) +
        " native_quantity=" + std::to_string(quantity_before) + "->" +
        std::to_string(quantity_after) +
        " inventory_revision=" + std::to_string(request.inventory_revision) +
        " ledger_converged=" + std::to_string(ledger_converged ? 1 : 0));
    return NativeInventoryCreditOutcome::Applied;
}

bool QueueNativeInventoryCreditInternal(
    std::uint64_t authority_participant_id,
    std::uint32_t run_nonce,
    std::uint64_t network_drop_id,
    std::uint32_t item_type_id,
    std::uint32_t item_recipe_uid,
    const std::array<std::uint8_t, multiplayer::kParticipantVisualLinkColorBlockBytes>&
        item_color_state,
    bool item_color_state_valid,
    std::int32_t item_slot,
    std::int32_t stack_count,
    std::uint32_t inventory_revision,
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
    if (!multiplayer::IsLocalTransportClient()) {
        return fail("Native remote-authority inventory credit is client-only.");
    }
    const bool is_potion = item_type_id == kReplicatedLootPotionItemTypeId;
    const bool is_recipe_item = item_type_id != 0 && !is_potion && item_recipe_uid != 0;
    if (authority_participant_id == 0 ||
        run_nonce == 0 ||
        network_drop_id == 0 ||
        (!is_potion && !is_recipe_item) ||
        (is_potion && (item_slot < 0 || item_slot > 1)) ||
        stack_count <= 0 ||
        inventory_revision == 0) {
        return fail("Native inventory credit metadata is invalid.");
    }

    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    std::lock_guard<std::mutex> lock(
        g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    auto& state = g_gameplay_keyboard_injection;
    if (state.native_inventory_credit_run_nonce != 0 &&
        state.native_inventory_credit_run_nonce != run_nonce) {
        state.pending_native_inventory_credits.clear();
        state.pending_native_inventory_credit_drop_ids.clear();
        state.completed_native_inventory_credit_drop_ids.clear();
    }
    state.native_inventory_credit_run_nonce = run_nonce;

    if (state.pending_native_inventory_credit_drop_ids.find(network_drop_id) !=
            state.pending_native_inventory_credit_drop_ids.end() ||
        state.completed_native_inventory_credit_drop_ids.find(network_drop_id) !=
            state.completed_native_inventory_credit_drop_ids.end()) {
        return true;
    }
    if (state.pending_native_inventory_credits.size() >=
        kQueuedGameplayWorldActionLimit) {
        return fail("Native inventory credit queue is full.");
    }

    PendingNativeInventoryCredit request;
    request.authority_participant_id = authority_participant_id;
    request.run_nonce = run_nonce;
    request.network_drop_id = network_drop_id;
    request.item_type_id = item_type_id;
    request.item_recipe_uid = item_recipe_uid;
    request.item_color_state_valid = item_color_state_valid;
    request.item_color_state = item_color_state;
    request.item_slot = item_slot;
    request.stack_count = stack_count;
    request.inventory_revision = inventory_revision;
    request.queued_ms = now_ms;
    request.next_attempt_ms = now_ms;
    state.pending_native_inventory_credits.push_back(request);
    state.pending_native_inventory_credit_drop_ids.insert(network_drop_id);
    return true;
}
