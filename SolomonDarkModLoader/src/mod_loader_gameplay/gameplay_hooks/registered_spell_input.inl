bool TryCaptureLocalRegisteredSpellCursorWorldAim(
    uintptr_t actor_address,
    LocalSecondaryCastCapture* capture) {
    if (actor_address == 0 || capture == nullptr ||
        kCursorScreenPositionGlobal == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto cursor_address =
        memory.ResolveGameAddressOrZero(kCursorScreenPositionGlobal);
    uintptr_t actor_world_address = 0;
    std::int32_t cursor_x = 0;
    std::int32_t cursor_y = 0;
    float view_scale = 0.0f;
    float view_origin_x = 0.0f;
    float view_origin_y = 0.0f;
    if (cursor_address == 0 ||
        !memory.TryReadValue(cursor_address, &cursor_x) ||
        !memory.TryReadValue(
            cursor_address + sizeof(cursor_x),
            &cursor_y) ||
        !memory.TryReadField(
            actor_address,
            kActorOwnerOffset,
            &actor_world_address) ||
        actor_world_address == 0 ||
        !memory.TryReadField(
            actor_world_address,
            kActorWorldViewScaleOffset,
            &view_scale) ||
        !memory.TryReadField(
            actor_world_address,
            kActorWorldViewOriginXOffset,
            &view_origin_x) ||
        !memory.TryReadField(
            actor_world_address,
            kActorWorldViewOriginYOffset,
            &view_origin_y) ||
        !std::isfinite(view_scale) ||
        std::abs(view_scale) <= 0.0001f ||
        !std::isfinite(view_origin_x) ||
        !std::isfinite(view_origin_y)) {
        return false;
    }

    const auto world_x =
        view_origin_x + static_cast<float>(cursor_x) / view_scale;
    const auto world_y =
        view_origin_y + static_cast<float>(cursor_y) / view_scale;
    if (!IsUsableSpellCastAimTarget(
            capture->position_x,
            capture->position_y,
            world_x,
            world_y)) {
        return false;
    }
    capture->has_cursor_world_placement = true;
    capture->cursor_world_x = world_x;
    capture->cursor_world_y = world_y;
    return true;
}

enum class LuaRegisteredSpellInputDispatchResult {
    NotSelected,
    Rejected,
    Queued,
};

bool TryApplyLocalRegisteredSpellManaDelta(
    uintptr_t actor_address,
    float delta) {
    const auto original =
        GetX86HookTrampoline<PlayerActorApplyManaDeltaFn>(
            g_gameplay_keyboard_injection.player_actor_apply_mana_delta_hook);
    if (actor_address == 0 || original == nullptr ||
        !std::isfinite(delta)) {
        return false;
    }
    (void)original(
        reinterpret_cast<void*>(actor_address),
        delta,
        0);
    return true;
}

bool TrySpendLocalRegisteredSpellMana(
    uintptr_t actor_address,
    float mana_cost,
    float* spent_mana,
    std::string* error_message) {
    if (spent_mana != nullptr) {
        *spent_mana = 0.0f;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!std::isfinite(mana_cost) || mana_cost < 0.0f) {
        if (error_message != nullptr) {
            *error_message = "registered spell mana cost is invalid";
        }
        return false;
    }
    if (mana_cost == 0.0f) {
        return true;
    }

    uintptr_t progression_address = 0;
    float mana_before = 0.0f;
    float maximum_mana = 0.0f;
    if (!TryResolveActorProgressionRuntime(
            actor_address,
            &progression_address) ||
        !TryReadProgressionMana(
            progression_address,
            &mana_before,
            &maximum_mana)) {
        if (error_message != nullptr) {
            *error_message = "local player mana is unavailable";
        }
        return false;
    }
    constexpr float kManaCostEpsilon = 0.001f;
    if (mana_before + kManaCostEpsilon < mana_cost) {
        if (error_message != nullptr) {
            *error_message = "insufficient mana";
        }
        return false;
    }
    if (!TryApplyLocalRegisteredSpellManaDelta(
            actor_address,
            -mana_cost)) {
        if (error_message != nullptr) {
            *error_message = "native mana writer is unavailable";
        }
        return false;
    }

    float mana_after = mana_before;
    float maximum_mana_after = maximum_mana;
    if (!TryReadProgressionMana(
            progression_address,
            &mana_after,
            &maximum_mana_after)) {
        (void)TryApplyLocalRegisteredSpellManaDelta(
            actor_address,
            mana_cost);
        if (error_message != nullptr) {
            *error_message = "local player mana could not be verified";
        }
        return false;
    }
    const auto applied_cost = mana_before - mana_after;
    if (!std::isfinite(applied_cost) ||
        applied_cost + kManaCostEpsilon < mana_cost) {
        if (applied_cost > 0.0f) {
            (void)TryApplyLocalRegisteredSpellManaDelta(
                actor_address,
                applied_cost);
        }
        if (error_message != nullptr) {
            *error_message = "native mana writer rejected the configured cost";
        }
        return false;
    }
    if (spent_mana != nullptr) {
        *spent_mana = applied_cost;
    }
    return true;
}

LuaRegisteredSpellInputDispatchResult DispatchSelectedLuaRegisteredSpell(
    uintptr_t actor_address,
    const LuaRegisteredSpellInputSelection& selection,
    const LocalSecondaryCastCapture& capture) {
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    std::uint32_t cooldown_remaining_ms = 0;
    if (!TryGetLuaRegisteredSpellInputCooldownRemaining(
            selection.content_id,
            now_ms,
            &cooldown_remaining_ms)) {
        return LuaRegisteredSpellInputDispatchResult::Rejected;
    }
    if (cooldown_remaining_ms != 0) {
        Log(
            "lua_spells: rejected selected input cast during cooldown. "
            "content_id=" + std::to_string(selection.content_id) +
            " remaining_ms=" + std::to_string(cooldown_remaining_ms));
        return LuaRegisteredSpellInputDispatchResult::Rejected;
    }

    const auto direction_length = std::sqrt(
        capture.direction_x * capture.direction_x +
        capture.direction_y * capture.direction_y);
    if (!std::isfinite(capture.position_x) ||
        !std::isfinite(capture.position_y) ||
        !std::isfinite(direction_length) ||
        direction_length < 0.001f) {
        Log(
            "lua_spells: rejected selected input cast because local aim is unavailable. "
            "content_id=" + std::to_string(selection.content_id));
        return LuaRegisteredSpellInputDispatchResult::Rejected;
    }

    const auto direction_x = capture.direction_x / direction_length;
    const auto direction_y = capture.direction_y / direction_length;
    float aim_x = capture.position_x + direction_x * selection.cast_range;
    float aim_y = capture.position_y + direction_y * selection.cast_range;
    if (capture.has_cursor_world_placement &&
        IsUsableSpellCastAimTarget(
            capture.position_x,
            capture.position_y,
            capture.cursor_world_x,
            capture.cursor_world_y)) {
        aim_x = capture.cursor_world_x;
        aim_y = capture.cursor_world_y;
    } else if (capture.has_aim_target) {
        aim_x = capture.aim_target_x;
        aim_y = capture.aim_target_y;
    }

    float spent_mana = 0.0f;
    std::string mana_error;
    if (!TrySpendLocalRegisteredSpellMana(
            actor_address,
            selection.mana_cost,
            &spent_mana,
            &mana_error)) {
        Log(
            "lua_spells: rejected selected input cast. content_id=" +
            std::to_string(selection.content_id) +
            " error=" + mana_error);
        return LuaRegisteredSpellInputDispatchResult::Rejected;
    }

    const auto target_network_actor_id =
        multiplayer::GetLocalRunEnemyNetworkActorId(
            capture.target_actor_address);
    std::uint64_t request_id = 0;
    std::uint64_t owner_participant_id = 0;
    bool local_owner = false;
    std::string cast_error;
    if (!multiplayer::QueueOwnerRoutedLuaRegisteredSpellCast(
            selection.content_id,
            0,
            target_network_actor_id,
            capture.position_x,
            capture.position_y,
            aim_x,
            aim_y,
            &request_id,
            &owner_participant_id,
            &local_owner,
            &cast_error)) {
        if (spent_mana > 0.0f) {
            (void)TryApplyLocalRegisteredSpellManaDelta(
                actor_address,
                spent_mana);
        }
        Log(
            "lua_spells: rejected selected input cast. content_id=" +
            std::to_string(selection.content_id) +
            " error=" + cast_error);
        return LuaRegisteredSpellInputDispatchResult::Rejected;
    }

    CommitLuaRegisteredSpellInputCast(selection.content_id, now_ms);
    Log(
        "lua_spells: queued selected input cast. content_id=" +
        std::to_string(selection.content_id) +
        " request_id=" + std::to_string(request_id) +
        " owner_participant_id=" + std::to_string(owner_participant_id) +
        " local_owner=" + std::to_string(local_owner ? 1 : 0) +
        " lane=" + (selection.primary ? std::string("primary") : std::string("secondary")) +
        " belt_slot=" + std::to_string(selection.secondary_slot + 1) +
        " mana_cost=" + std::to_string(spent_mana) +
        " origin=(" + std::to_string(capture.position_x) + "," +
            std::to_string(capture.position_y) + ")" +
        " aim=(" + std::to_string(aim_x) + "," +
            std::to_string(aim_y) + ")");
    return LuaRegisteredSpellInputDispatchResult::Queued;
}

LuaRegisteredSpellInputDispatchResult
TryDispatchSelectedLuaRegisteredPrimarySpell(uintptr_t actor_address) {
    LuaRegisteredSpellInputSelection selection;
    if (!IsActorCurrentLocalPlayerSlotZero(actor_address) ||
        IsRunLifecycleManualEnemySpawnerTestModeEnabled() ||
        !TryGetSelectedLuaRegisteredPrimarySpell(&selection)) {
        return LuaRegisteredSpellInputDispatchResult::NotSelected;
    }

    constexpr std::uint64_t kRegisteredPrimaryInputEdgeWindowMs = 500;
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    const auto edge_serial = GetGameplayMouseLeftEdgeSerial();
    const auto edge_tick_ms = GetGameplayMouseLeftEdgeTickMs();
    if (edge_serial == 0 || edge_tick_ms == 0 || now_ms < edge_tick_ms ||
        now_ms - edge_tick_ms > kRegisteredPrimaryInputEdgeWindowMs ||
        !TryClaimGameplayMouseLeftPrimaryCastEdge(edge_serial)) {
        return LuaRegisteredSpellInputDispatchResult::Rejected;
    }

    LocalSecondaryCastCapture capture;
    if (!TryCaptureLocalSecondaryCastOrigin(actor_address, &capture) ||
        !TryRefreshLocalSecondaryCastAim(actor_address, &capture)) {
        return LuaRegisteredSpellInputDispatchResult::Rejected;
    }
    capture.valid = true;
    return DispatchSelectedLuaRegisteredSpell(
        actor_address,
        selection,
        capture);
}

LuaRegisteredSpellInputDispatchResult
TryDispatchSelectedLuaRegisteredSecondarySpell(
    uintptr_t actor_address,
    std::int32_t belt_slot,
    const LocalSecondaryCastCapture* existing_capture = nullptr) {
    if (belt_slot < 0 ||
        belt_slot >= static_cast<std::int32_t>(
            kLuaRegisteredSpellSecondaryInputSlotCount)) {
        return LuaRegisteredSpellInputDispatchResult::NotSelected;
    }
    LuaRegisteredSpellInputSelection selection;
    if (!TryGetSelectedLuaRegisteredSecondarySpell(
            static_cast<std::size_t>(belt_slot),
            &selection)) {
        return LuaRegisteredSpellInputDispatchResult::NotSelected;
    }

    LocalSecondaryCastCapture capture;
    if (existing_capture != nullptr) {
        capture = *existing_capture;
    } else if (!TryCaptureLocalSecondaryCastOrigin(
                   actor_address,
                   &capture) ||
               !TryRefreshLocalSecondaryCastAim(actor_address, &capture)) {
        return LuaRegisteredSpellInputDispatchResult::Rejected;
    }
    (void)TryCaptureLocalRegisteredSpellCursorWorldAim(
        actor_address,
        &capture);
    capture.valid = true;
    capture.belt_slot = belt_slot;
    return DispatchSelectedLuaRegisteredSpell(
        actor_address,
        selection,
        capture);
}

LuaRegisteredSpellInputDispatchResult
TryDispatchSelectedLuaRegisteredSecondaryBeltInput(
    std::int32_t belt_slot) {
    static std::array<
        std::atomic<std::uint64_t>,
        kLuaRegisteredSpellSecondaryInputSlotCount>
        last_dispatch_ms{};
    if (belt_slot < 0 ||
        belt_slot >= static_cast<std::int32_t>(last_dispatch_ms.size())) {
        return LuaRegisteredSpellInputDispatchResult::NotSelected;
    }

    LuaRegisteredSpellInputSelection selection;
    if (!TryGetSelectedLuaRegisteredSecondarySpell(
            static_cast<std::size_t>(belt_slot),
            &selection)) {
        return LuaRegisteredSpellInputDispatchResult::NotSelected;
    }
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    auto& last = last_dispatch_ms[static_cast<std::size_t>(belt_slot)];
    const auto previous_ms = last.exchange(now_ms, std::memory_order_acq_rel);
    constexpr std::uint64_t kDuplicateBeltEdgeWindowMs = 25;
    if (previous_ms != 0 && now_ms >= previous_ms &&
        now_ms - previous_ms <= kDuplicateBeltEdgeWindowMs) {
        return LuaRegisteredSpellInputDispatchResult::Rejected;
    }

    uintptr_t gameplay_address = 0;
    uintptr_t actor_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) ||
        gameplay_address == 0 ||
        !TryResolvePlayerActorForSlot(
            gameplay_address,
            0,
            &actor_address) ||
        actor_address == 0) {
        return LuaRegisteredSpellInputDispatchResult::Rejected;
    }
    return TryDispatchSelectedLuaRegisteredSecondarySpell(
        actor_address,
        belt_slot);
}
