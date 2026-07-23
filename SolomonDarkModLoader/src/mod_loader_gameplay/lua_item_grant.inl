enum class LuaItemGrantOutcome {
    Applied,
    Retry,
    FailedBeforeApply,
    ApplyStateUnknown,
};

LuaItemGrantOutcome ExecuteLuaItemGrantNow(
    const PendingLuaItemGrant& request,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    const auto fail = [&](LuaItemGrantOutcome outcome, std::string message) {
        if (error_message != nullptr) {
            *error_message = std::move(message);
        }
        return outcome;
    };

    if (request.authority_participant_id == 0 ||
        request.request_id == 0 ||
        request.content_id == 0) {
        return fail(
            LuaItemGrantOutcome::FailedBeforeApply,
            "Lua item grant metadata is invalid.");
    }

    std::uint32_t item_type_id = 0;
    std::uint32_t recipe_uid = 0;
    std::string resolution_error;
    if (!TryResolveLuaItemNativeRecipe(
            request.content_id,
            &item_type_id,
            &recipe_uid,
            &resolution_error)) {
        return fail(
            LuaItemGrantOutcome::Retry,
            "Lua item recipe is not ready: " + resolution_error);
    }

    const bool wearable =
        item_type_id == kStandaloneWizardHatVisualTypeId ||
        item_type_id == kStandaloneWizardRobeVisualTypeId;
    if (request.color_state_valid && !wearable) {
        return fail(
            LuaItemGrantOutcome::FailedBeforeApply,
            "Lua item color state is valid only for hats and robes.");
    }

    SDModInventoryState inventory_before;
    if (!TryGetPlayerInventoryState(&inventory_before) ||
        !inventory_before.valid ||
        inventory_before.gameplay_scene_address == 0 ||
        inventory_before.item_list_root_address == 0) {
        return fail(
            LuaItemGrantOutcome::Retry,
            "Local native inventory is not active.");
    }

    auto& memory = ProcessMemory::Instance();
    const auto insert_address =
        memory.ResolveGameAddressOrZero(kInventoryInsertOrStackItem);
    if (insert_address == 0 || kGameplayInventoryDirtyOffset == 0) {
        return fail(
            LuaItemGrantOutcome::Retry,
            "Stock inventory insertion seams are unavailable.");
    }

    std::int64_t quantity_before = 0;
    if (!TryGetNativeInventoryQuantity(
            inventory_before,
            item_type_id,
            recipe_uid,
            -1,
            &quantity_before)) {
        return fail(
            LuaItemGrantOutcome::Retry,
            "Native inventory baseline is unavailable.");
    }

    uintptr_t item_address = 0;
    std::string clone_error;
    if (!CloneNativeItemFromRecipe(
            recipe_uid,
            item_type_id,
            request.color_state,
            request.color_state_valid,
            &item_address,
            &clone_error) ||
        item_address == 0) {
        return fail(
            LuaItemGrantOutcome::Retry,
            "Native item clone is not ready: " + clone_error);
    }

    DWORD insert_exception = 0;
    const bool insert_called = CallInventoryInsertOrStackItemSafe(
        insert_address,
        inventory_before.item_list_root_address,
        item_address,
        &insert_exception);

    const auto pointer_lookup = FindInventoryRootItemPointer(
        inventory_before.item_list_root_address,
        item_address);
    SDModInventoryState inventory_after;
    std::int64_t quantity_after = 0;
    const bool quantity_available =
        TryGetPlayerInventoryState(&inventory_after) &&
        TryGetNativeInventoryQuantity(
            inventory_after,
            item_type_id,
            recipe_uid,
            -1,
            &quantity_after);
    const bool quantity_advanced =
        quantity_available && quantity_after >= quantity_before + 1;
    if (pointer_lookup != InventoryRootPointerLookup::Present &&
        !quantity_advanced) {
        return fail(
            LuaItemGrantOutcome::ApplyStateUnknown,
            std::string("Stock inventory insertion did not expose the granted item. called=") +
                (insert_called ? "1" : "0") +
                " seh=0x" +
                HexString(static_cast<uintptr_t>(insert_exception)) + ".");
    }

    if (!memory.TryWriteField(
            inventory_before.gameplay_scene_address,
            kGameplayInventoryDirtyOffset,
            static_cast<std::uint8_t>(1))) {
        return fail(
            LuaItemGrantOutcome::ApplyStateUnknown,
            "Granted item is present but inventory replication could not be marked dirty.");
    }

    Log(
        "lua_items: applied authoritative item grant. authority_participant_id=" +
        std::to_string(request.authority_participant_id) +
        " request_id=" + std::to_string(request.request_id) +
        " content_id=" + std::to_string(request.content_id) +
        " item_type_id=" + HexString(static_cast<uintptr_t>(item_type_id)) +
        " recipe_uid=" + std::to_string(recipe_uid) +
        " native_quantity=" +
        (quantity_available
             ? std::to_string(quantity_before) + "->" +
                   std::to_string(quantity_after)
             : "unavailable"));
    return LuaItemGrantOutcome::Applied;
}

bool QueueLuaItemGrantToLocalInventoryInternal(
    std::uint64_t authority_participant_id,
    std::uint64_t request_id,
    std::uint64_t content_id,
    const std::array<std::uint8_t, multiplayer::kParticipantVisualLinkColorBlockBytes>&
        color_state,
    bool color_state_valid,
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
    if (authority_participant_id == 0 || request_id == 0 || content_id == 0) {
        return fail("Lua item grant metadata is invalid.");
    }

    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    std::lock_guard<std::mutex> lock(
        g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    auto& pending = g_gameplay_keyboard_injection.pending_lua_item_grants;
    const auto duplicate = std::find_if(
        pending.begin(),
        pending.end(),
        [&](const PendingLuaItemGrant& grant) {
            return grant.authority_participant_id == authority_participant_id &&
                   grant.request_id == request_id;
        });
    if (duplicate != pending.end()) {
        return true;
    }
    if (pending.size() >= kQueuedGameplayWorldActionLimit) {
        return fail("Lua item grant queue is full.");
    }

    PendingLuaItemGrant request;
    request.authority_participant_id = authority_participant_id;
    request.request_id = request_id;
    request.content_id = content_id;
    request.color_state = color_state;
    request.color_state_valid = color_state_valid;
    request.queued_ms = now_ms;
    request.next_attempt_ms = now_ms;
    pending.push_back(request);
    return true;
}

void ProcessPendingLuaItemGrant(std::uint64_t now_ms) {
    PendingLuaItemGrant grant;
    bool have_grant = false;
    {
        std::lock_guard<std::mutex> lock(
            g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
        auto& pending = g_gameplay_keyboard_injection.pending_lua_item_grants;
        const auto pending_count = pending.size();
        for (std::size_t index = 0; index < pending_count; ++index) {
            auto candidate = pending.front();
            pending.pop_front();
            if (!have_grant && candidate.next_attempt_ms <= now_ms) {
                grant = candidate;
                have_grant = true;
                continue;
            }
            pending.push_back(candidate);
        }
    }
    if (!have_grant) {
        return;
    }

    grant.attempts += 1;
    std::string grant_error;
    LuaItemGrantOutcome outcome = LuaItemGrantOutcome::FailedBeforeApply;
    const bool expired_before_attempt =
        grant.attempts > kLuaItemGrantMaxAttempts ||
        now_ms - grant.queued_ms > kLuaItemGrantExpiryMs;
    if (expired_before_attempt) {
        grant_error = "Lua item grant expired before it could be applied.";
    } else {
        outcome = ExecuteLuaItemGrantNow(grant, &grant_error);
    }

    bool requeued = false;
    if (outcome == LuaItemGrantOutcome::Retry &&
        grant.attempts < kLuaItemGrantMaxAttempts &&
        now_ms - grant.queued_ms <= kLuaItemGrantExpiryMs) {
        grant.next_attempt_ms = now_ms + kLuaItemGrantRetryDelayMs;
        std::lock_guard<std::mutex> lock(
            g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
        g_gameplay_keyboard_injection.pending_lua_item_grants.push_back(grant);
        requeued = true;
    }

    if (requeued) {
        if (grant.attempts == 1 || grant.attempts % 10 == 0) {
            Log(
                "lua_items: deferred authoritative item grant. request_id=" +
                std::to_string(grant.request_id) +
                " content_id=" + std::to_string(grant.content_id) +
                " attempt=" + std::to_string(grant.attempts) +
                " error=" + grant_error);
        }
    } else if (outcome != LuaItemGrantOutcome::Applied) {
        Log(
            std::string("lua_items: authoritative item grant ") +
            (outcome == LuaItemGrantOutcome::ApplyStateUnknown
                 ? "ended with unknown native apply state"
                 : "failed before native apply") +
            ". request_id=" + std::to_string(grant.request_id) +
            " content_id=" + std::to_string(grant.content_id) +
            " attempts=" + std::to_string(grant.attempts) +
            " error=" + grant_error);
    }
}
