namespace {

bool InventoryItemMatchesPotion(
    const ParticipantInventoryItemState& item,
    const BotPotionInventoryDetails& selected) {
    if (item.type_id != kBotPotionItemTypeId ||
        item.stack_count <= 0) {
        return false;
    }
    if (selected.custom) {
        return selected.content_id != 0 &&
            item.content_id == selected.content_id;
    }
    return item.content_id == 0 &&
        item.slot == selected.stock_subtype;
}

struct ReservedParticipantPotionStack {
    ParticipantInventoryItemState item;
    std::size_t original_index = 0;
    std::uint32_t inventory_revision = 0;
    bool row_removed = false;
};

void RefreshParticipantInventoryCounts(
    ParticipantOwnedProgressionState* progression) {
    if (progression == nullptr) {
        return;
    }
    progression->inventory_item_total_count =
        static_cast<std::uint16_t>((std::min)(
            progression->inventory_items.size(),
            static_cast<std::size_t>(
                (std::numeric_limits<std::uint16_t>::max)())));
    progression->inventory_truncated =
        progression->inventory_items.size() >
            kParticipantInventorySnapshotMaxItems;
}

bool ReserveParticipantPotionStack(
    RuntimeState& state,
    const BotUseConsumableRequest& request,
    const BotPotionInventoryDetails& selected,
    ReservedParticipantPotionStack* reservation) {
    if (reservation == nullptr) {
        return false;
    }
    *reservation = {};
    auto* participant =
        FindParticipant(state, request.participant_id);
    if (participant == nullptr ||
        participant->owned_progression.inventory_revision !=
            request.inventory_revision) {
        return false;
    }

    auto& progression = participant->owned_progression;
    auto item = std::find_if(
        progression.inventory_items.begin(),
        progression.inventory_items.end(),
        [&](const ParticipantInventoryItemState& candidate) {
            return InventoryItemMatchesPotion(
                candidate,
                selected);
        });
    if (item == progression.inventory_items.end()) {
        return false;
    }

    reservation->item = *item;
    reservation->original_index =
        static_cast<std::size_t>(
            std::distance(
                progression.inventory_items.begin(),
                item));
    item->stack_count -= 1;
    if (item->stack_count <= 0) {
        const auto removed_index =
            static_cast<std::int16_t>(
                reservation->original_index);
        progression.inventory_items.erase(item);
        reservation->row_removed = true;
        for (auto& remaining : progression.inventory_items) {
            if (remaining.parent_item_index >
                removed_index) {
                remaining.parent_item_index -= 1;
            }
        }
    }
    RefreshParticipantInventoryCounts(&progression);
    progression.inventory_revision += 1;
    reservation->inventory_revision =
        progression.inventory_revision;
    return true;
}

bool RollBackParticipantPotionReservation(
    RuntimeState& state,
    std::uint64_t participant_id,
    const ReservedParticipantPotionStack& reservation) {
    auto* participant =
        FindParticipant(state, participant_id);
    if (participant == nullptr ||
        participant->owned_progression.inventory_revision !=
            reservation.inventory_revision) {
        return false;
    }
    auto& progression = participant->owned_progression;
    if (!reservation.row_removed) {
        const auto found = std::find_if(
            progression.inventory_items.begin(),
            progression.inventory_items.end(),
            [&](const ParticipantInventoryItemState& item) {
                return item.type_id == reservation.item.type_id &&
                    item.recipe_uid == reservation.item.recipe_uid &&
                    item.content_id == reservation.item.content_id &&
                    item.slot == reservation.item.slot;
            });
        if (found == progression.inventory_items.end()) {
            return false;
        }
        found->stack_count += 1;
    } else {
        const auto insertion_index =
            (std::min)(
                reservation.original_index,
                progression.inventory_items.size());
        for (auto& remaining : progression.inventory_items) {
            if (remaining.parent_item_index >=
                static_cast<std::int16_t>(insertion_index)) {
                remaining.parent_item_index += 1;
            }
        }
        progression.inventory_items.insert(
            progression.inventory_items.begin() +
                static_cast<std::ptrdiff_t>(insertion_index),
            reservation.item);
    }
    RefreshParticipantInventoryCounts(&progression);
    progression.inventory_revision += 1;
    return true;
}

void PublishParticipantConsumableVitals(
    RuntimeState& state,
    std::uint64_t participant_id,
    const SDModParticipantStockConsumableResult& native_result) {
    auto* participant =
        FindParticipant(state, participant_id);
    if (participant == nullptr || !native_result.applied) {
        return;
    }
    participant->runtime.life_current =
        native_result.hp_after;
    participant->runtime.mana_current =
        native_result.mp_after;
}

std::uint64_t AllocateBotConsumableUseIdLocked() {
    if (g_next_consumable_use_id == 0 ||
        g_next_consumable_use_id >
            static_cast<std::uint64_t>(INT64_MAX)) {
        g_next_consumable_use_id = 1;
    }
    return g_next_consumable_use_id++;
}

}  // namespace

bool UseParticipantConsumable(
    const BotUseConsumableRequest& request,
    BotUseConsumableResult* result,
    std::string* error_message) {
    if (result != nullptr) {
        *result = {};
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    const auto fail = [&](const char* message) {
        if (error_message != nullptr) {
            *error_message = message;
        }
        return false;
    };
    if (result == nullptr || error_message == nullptr) {
        return false;
    }
    if (!IsLuaModSimulationAuthority()) {
        return fail(
            "Only the simulation authority may use a participant consumable.");
    }
    if (request.participant_id == 0 ||
        request.potion_slot < 1 ||
        request.potion_slot > 12) {
        return fail(
            "Consumable use requires a participant and potion_slot in 1..12.");
    }

    const auto runtime = SnapshotRuntimeState();
    const auto* participant =
        FindParticipant(runtime, request.participant_id);
    if (participant == nullptr ||
        !IsRemoteParticipant(*participant) ||
        !IsLuaControlledParticipant(*participant) ||
        !participant->runtime.valid ||
        !participant->runtime.in_run ||
        participant->runtime.life_current <= 0.0f) {
        return fail(
            "The target is not a living authority-owned synthetic participant in the active run.");
    }

    BotInventoryDetails details;
    if (!ReadParticipantInventoryDetails(
            request.participant_id,
            &details) ||
        !details.available) {
        return fail(
            "The participant inventory details are unavailable.");
    }
    if (details.run_nonce == 0 ||
        details.run_nonce != participant->runtime.run_nonce) {
        return fail(
            "The consumable selector belongs to a different run.");
    }
    if (details.inventory_revision !=
        request.inventory_revision) {
        return fail(
            "The consumable selector has a stale inventory_revision.");
    }
    if (request.potion_slot >
        static_cast<std::int32_t>(
            details.potions.size())) {
        return fail(
            "The selected ranked potion slot is not occupied.");
    }
    const auto selected =
        details.potions[
            static_cast<std::size_t>(
                request.potion_slot - 1)];
    if (selected.count <= 0 ||
        !selected.synthetic_use_supported) {
        return fail(
            "The selected potion has no proven synthetic-safe effect path.");
    }

    std::uint64_t use_id = 0;
    {
        std::scoped_lock lock(g_bot_runtime_mutex);
        if (!g_bot_runtime_initialized) {
            return fail("The bot framework is unavailable.");
        }
        use_id = AllocateBotConsumableUseIdLocked();
    }

    ReservedParticipantPotionStack reservation;
    bool reserved = false;
    UpdateRuntimeState([&](RuntimeState& state) {
        reserved = ReserveParticipantPotionStack(
            state,
            request,
            selected,
            &reservation);
    });
    if (!reserved) {
        return fail(
            "The authoritative inventory changed before the consumable transaction was reserved.");
    }
    const auto rollback_reservation = [&]() {
        bool rolled_back = false;
        UpdateRuntimeState([&](RuntimeState& state) {
            rolled_back =
                RollBackParticipantPotionReservation(
                    state,
                    request.participant_id,
                    reservation);
        });
        {
            std::scoped_lock lock(g_bot_runtime_mutex);
            InvalidateParticipantInventoryDetailsLocked(
                request.participant_id);
        }
        return rolled_back;
    };

    SDModParticipantStockConsumableResult native_result;
    if (!selected.custom) {
        std::string native_error;
        if (!TryApplyParticipantStockConsumable(
                request.participant_id,
                selected.stock_subtype,
                &native_result,
                &native_error)) {
            const bool rolled_back =
                rollback_reservation();
            if (!rolled_back) {
                Log(
                    "[bots] consumable reservation rollback failed. participant_id=" +
                    std::to_string(request.participant_id) +
                    " use_id=" + std::to_string(use_id));
            }
            if (!native_error.empty()) {
                *error_message = native_error;
            }
            return false;
        }
    } else {
        std::string publish_error;
        if (!PublishAuthoritativeLuaConsumableUse(
                request.participant_id,
                selected.content_id,
                use_id,
                &publish_error)) {
            const bool rolled_back =
                rollback_reservation();
            if (!rolled_back) {
                Log(
                    "[bots] custom consumable reservation rollback failed. participant_id=" +
                    std::to_string(request.participant_id) +
                    " use_id=" + std::to_string(use_id));
            }
            if (!publish_error.empty()) {
                *error_message = publish_error;
            }
            return false;
        }
    }

    if (!selected.custom) {
        UpdateRuntimeState([&](RuntimeState& state) {
            PublishParticipantConsumableVitals(
                state,
                request.participant_id,
                native_result);
        });
    }

    {
        std::scoped_lock lock(g_bot_runtime_mutex);
        InvalidateParticipantInventoryDetailsLocked(
            request.participant_id);
    }
    result->use_id = use_id;
    result->inventory_revision =
        reservation.inventory_revision;
    result->stock_subtype = selected.stock_subtype;
    result->content_id = selected.content_id;
    Log(
        "[bots] consumable applied exactly once. participant_id=" +
        std::to_string(request.participant_id) +
        " use_id=" + std::to_string(use_id) +
        " inventory_revision=" +
        std::to_string(reservation.inventory_revision) +
        " stock_subtype=" +
        std::to_string(selected.stock_subtype) +
        " custom=" +
        std::to_string(selected.custom ? 1 : 0));
    return true;
}
