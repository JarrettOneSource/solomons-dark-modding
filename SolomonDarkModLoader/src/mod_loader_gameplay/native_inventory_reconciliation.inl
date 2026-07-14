enum class NativePotionInventoryCreditOutcome {
    Applied,
    Retry,
    FailedBeforeApply,
    ApplyStateUnknown,
};

void ClearNativeInventoryCreditState() {
    std::lock_guard<std::mutex> lock(
        g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    auto& state = g_gameplay_keyboard_injection;
    state.pending_native_potion_inventory_credits.clear();
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

bool TryGetNativePotionStackTotal(
    const SDModInventoryState& inventory,
    std::int32_t item_slot,
    std::int64_t* stack_total) {
    if (stack_total == nullptr || !inventory.valid || item_slot < 0 || item_slot > 1) {
        return false;
    }

    std::int64_t total = 0;
    for (const auto& item : inventory.items) {
        if (!item.valid ||
            item.type_id != kReplicatedLootPotionItemTypeId ||
            item.slot != item_slot) {
            continue;
        }
        total += (std::max)(item.stack_count, 1);
    }
    *stack_total = total;
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

NativePotionInventoryCreditOutcome ExecuteNativePotionInventoryCreditNow(
    const PendingNativePotionInventoryCredit& request,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    const auto fail = [&](NativePotionInventoryCreditOutcome outcome, std::string message) {
        if (error_message != nullptr) {
            *error_message = std::move(message);
        }
        return outcome;
    };

    if (!multiplayer::IsLocalTransportClient() ||
        request.authority_participant_id == 0 ||
        request.run_nonce == 0 ||
        request.network_drop_id == 0 ||
        request.item_type_id != kReplicatedLootPotionItemTypeId ||
        request.item_slot < 0 ||
        request.item_slot > 1 ||
        request.stack_count <= 0 ||
        request.inventory_revision == 0) {
        return fail(
            NativePotionInventoryCreditOutcome::FailedBeforeApply,
            "native potion inventory credit metadata is invalid");
    }

    const auto runtime_state = multiplayer::SnapshotRuntimeState();
    const auto* local_participant = multiplayer::FindLocalParticipant(runtime_state);
    if (local_participant == nullptr ||
        !local_participant->runtime.valid ||
        !local_participant->runtime.in_run) {
        return fail(
            NativePotionInventoryCreditOutcome::Retry,
            "local multiplayer participant is not ready in a run");
    }
    if (local_participant->runtime.run_nonce != 0 &&
        local_participant->runtime.run_nonce != request.run_nonce) {
        return fail(
            NativePotionInventoryCreditOutcome::FailedBeforeApply,
            "native potion inventory credit belongs to an inactive run");
    }

    SDModSceneState scene_state;
    if (!TryGetSceneState(&scene_state) ||
        !scene_state.valid ||
        (scene_state.kind != "arena" && scene_state.name != "testrun")) {
        return fail(
            NativePotionInventoryCreditOutcome::Retry,
            "native gameplay inventory is not in an arena scene");
    }

    SDModInventoryState inventory_before;
    if (!TryGetPlayerInventoryState(&inventory_before) || !inventory_before.valid) {
        return fail(
            NativePotionInventoryCreditOutcome::Retry,
            "native gameplay inventory root is unavailable");
    }
    std::int64_t stack_before = 0;
    if (!TryGetNativePotionStackTotal(
            inventory_before,
            request.item_slot,
            &stack_before)) {
        return fail(
            NativePotionInventoryCreditOutcome::Retry,
            "native potion stack baseline is unavailable");
    }

    auto& memory = ProcessMemory::Instance();
    const auto insert_function_address =
        memory.ResolveGameAddressOrZero(kInventoryInsertOrStackItem);
    if (insert_function_address == 0) {
        return fail(
            NativePotionInventoryCreditOutcome::FailedBeforeApply,
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
            g_client_non_authoritative_loot_suppressed_actors.erase(it->actor_address);
            g_replicated_loot_presentations.erase(it);
            have_carrier = true;
        }
    }

    if (have_carrier &&
        (carrier_binding.authority_participant_id != request.authority_participant_id ||
         carrier_binding.run_nonce != request.run_nonce ||
         carrier_binding.drop_kind != multiplayer::LootDropKind::Potion ||
         carrier_binding.native_type_id != kReplicatedLootItemDropNativeTypeId ||
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
            held_item_type_id != request.item_type_id) {
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
                NativePotionInventoryCreditOutcome::Retry,
                "local player position is unavailable for potion materialization");
        }

        multiplayer::LootDropSnapshot native_drop;
        native_drop.network_drop_id = request.network_drop_id;
        native_drop.native_type_id = kReplicatedLootItemDropNativeTypeId;
        native_drop.drop_kind = multiplayer::LootDropKind::Potion;
        native_drop.active = true;
        native_drop.item_type_id = request.item_type_id;
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
                NativePotionInventoryCreditOutcome::Retry,
                "unable to materialize native potion carrier: " + spawn_error);
        }

        carrier_binding.network_drop_id = request.network_drop_id;
        carrier_binding.authority_participant_id = request.authority_participant_id;
        carrier_binding.run_nonce = request.run_nonce;
        carrier_binding.native_type_id = kReplicatedLootItemDropNativeTypeId;
        carrier_binding.drop_kind = multiplayer::LootDropKind::Potion;
        carrier_binding.actor_address = carrier_actor_address;
        carrier_binding.active = true;
        carrier_binding.x = player_state.x;
        carrier_binding.y = player_state.y;
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
            held_item_type_id != request.item_type_id) {
            DWORD remove_exception_code = 0;
            (void)RemoveReplicatedLootPresentationActor(
                carrier_binding,
                &remove_exception_code);
            return fail(
                NativePotionInventoryCreditOutcome::Retry,
                "materialized potion carrier did not expose its held item");
        }
    }

    if (!memory.TryWriteField(held_item_address, kItemSlotOffset, request.item_slot) ||
        !memory.TryWriteField(
            held_item_address,
            kPotionStackCountOffset,
            request.stack_count)) {
        DWORD remove_exception_code = 0;
        (void)RemoveReplicatedLootPresentationActor(
            carrier_binding,
            &remove_exception_code);
        return fail(
            NativePotionInventoryCreditOutcome::Retry,
            "unable to seed the authoritative native potion fields");
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
            NativePotionInventoryCreditOutcome::Retry,
            "unable to transfer native potion ownership out of its carrier");
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
            "native_inventory: potion carrier removal failed after ownership transfer. "
            "network_drop_id=" + std::to_string(request.network_drop_id) +
            " actor=" + HexString(carrier_binding.actor_address) +
            " seh=" + HexString(static_cast<uintptr_t>(remove_exception_code)));
    }

    if (!insert_called) {
        return fail(
            NativePotionInventoryCreditOutcome::ApplyStateUnknown,
            "Inventory_InsertOrStackItem raised 0x" +
                HexString(static_cast<uintptr_t>(insert_exception_code)));
    }

    SDModInventoryState inventory_after;
    std::int64_t stack_after = 0;
    if (!TryGetPlayerInventoryState(&inventory_after) ||
        !TryGetNativePotionStackTotal(
            inventory_after,
            request.item_slot,
            &stack_after)) {
        return fail(
            NativePotionInventoryCreditOutcome::ApplyStateUnknown,
            "native potion insertion completed but its result could not be read");
    }

    const auto expected_stack_after =
        stack_before + static_cast<std::int64_t>(request.stack_count);
    if (stack_after < expected_stack_after) {
        return fail(
            NativePotionInventoryCreditOutcome::ApplyStateUnknown,
            "native potion insertion did not increase the requested slot: before=" +
                std::to_string(stack_before) +
                " after=" + std::to_string(stack_after) +
                " expected=" + std::to_string(expected_stack_after));
    }

    const bool ledger_converged =
        multiplayer::MarkLocalInventoryNativeConverged(request.inventory_revision);
    Log(
        "native_inventory: applied authoritative potion pickup. network_drop_id=" +
        std::to_string(request.network_drop_id) +
        " slot=" + std::to_string(request.item_slot) +
        " stack=" + std::to_string(request.stack_count) +
        " native_stack=" + std::to_string(stack_before) + "->" +
        std::to_string(stack_after) +
        " inventory_revision=" + std::to_string(request.inventory_revision) +
        " ledger_converged=" + std::to_string(ledger_converged ? 1 : 0));
    return NativePotionInventoryCreditOutcome::Applied;
}

bool QueueNativePotionInventoryCreditInternal(
    std::uint64_t authority_participant_id,
    std::uint32_t run_nonce,
    std::uint64_t network_drop_id,
    std::uint32_t item_type_id,
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
    if (authority_participant_id == 0 ||
        run_nonce == 0 ||
        network_drop_id == 0 ||
        item_type_id != kReplicatedLootPotionItemTypeId ||
        item_slot < 0 ||
        item_slot > 1 ||
        stack_count <= 0 ||
        inventory_revision == 0) {
        return fail("Native potion inventory credit metadata is invalid.");
    }

    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    std::lock_guard<std::mutex> lock(
        g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    auto& state = g_gameplay_keyboard_injection;
    if (state.native_inventory_credit_run_nonce != 0 &&
        state.native_inventory_credit_run_nonce != run_nonce) {
        state.pending_native_potion_inventory_credits.clear();
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
    if (state.pending_native_potion_inventory_credits.size() >=
        kQueuedGameplayWorldActionLimit) {
        return fail("Native potion inventory credit queue is full.");
    }

    PendingNativePotionInventoryCredit request;
    request.authority_participant_id = authority_participant_id;
    request.run_nonce = run_nonce;
    request.network_drop_id = network_drop_id;
    request.item_type_id = item_type_id;
    request.item_slot = item_slot;
    request.stack_count = stack_count;
    request.inventory_revision = inventory_revision;
    request.queued_ms = now_ms;
    request.next_attempt_ms = now_ms;
    state.pending_native_potion_inventory_credits.push_back(request);
    state.pending_native_inventory_credit_drop_ids.insert(network_drop_id);
    return true;
}
