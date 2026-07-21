bool IsSecondaryCursorWorldPlacementSkill(std::int32_t skill_entry_index) {
    switch (skill_entry_index) {
    case 0x0B:
    case 0x1B:
    case 0x2D:
    case 0x31:
    case 0x32:
    case 0x48:
    case 0x49:
    case 0x4A:
    case 0x4C:
        return true;
    default:
        return false;
    }
}

struct ScopedSecondaryCursorWorldPlacementContext {
    uintptr_t actor_address = 0;
    std::int32_t skill_entry_index = -1;
    bool requested = false;
    float authored_world_x = 0.0f;
    float authored_world_y = 0.0f;
    uintptr_t gameplay_address = 0;
    uintptr_t cursor_secondary_at_mouse_address = 0;
    uintptr_t cursor_screen_position_address = 0;
    std::uint8_t original_cursor_secondary_at_mouse = 0;
    std::uint8_t original_cursor_placement_active = 0;
    std::int32_t original_cursor_screen_x = 0;
    std::int32_t original_cursor_screen_y = 0;
    std::int32_t applied_cursor_screen_x = 0;
    std::int32_t applied_cursor_screen_y = 0;
    bool ready = false;
    bool active = false;
    bool restore_attempted = false;
    bool restored = true;
    std::string status = "not_applied";

    ScopedSecondaryCursorWorldPlacementContext(
        uintptr_t actor_address_in,
        std::int32_t skill_entry_index_in,
        bool requested_in,
        float authored_world_x_in,
        float authored_world_y_in)
        : actor_address(actor_address_in),
          skill_entry_index(skill_entry_index_in),
          requested(requested_in),
          authored_world_x(authored_world_x_in),
          authored_world_y(authored_world_y_in) {
        Apply();
    }

    ScopedSecondaryCursorWorldPlacementContext(
        const ScopedSecondaryCursorWorldPlacementContext&) = delete;
    ScopedSecondaryCursorWorldPlacementContext& operator=(
        const ScopedSecondaryCursorWorldPlacementContext&) = delete;

    ~ScopedSecondaryCursorWorldPlacementContext() {
        Restore();
    }

    void Apply() {
        if (!requested) {
            ready = true;
            status = "not_requested";
            return;
        }
        if (actor_address == 0 ||
            !IsSecondaryCursorWorldPlacementSkill(skill_entry_index) ||
            !std::isfinite(authored_world_x) ||
            !std::isfinite(authored_world_y) ||
            kCursorSecondaryAtMouseGlobal == 0 ||
            kCursorScreenPositionGlobal == 0 ||
            kGameObjectGlobal == 0) {
            status = "invalid_request";
            return;
        }

        auto& memory = ProcessMemory::Instance();
        cursor_secondary_at_mouse_address =
            memory.ResolveGameAddressOrZero(kCursorSecondaryAtMouseGlobal);
        cursor_screen_position_address =
            memory.ResolveGameAddressOrZero(kCursorScreenPositionGlobal);
        const auto game_object_global_address =
            memory.ResolveGameAddressOrZero(kGameObjectGlobal);
        uintptr_t actor_world_address = 0;
        float view_scale = 0.0f;
        float view_origin_x = 0.0f;
        float view_origin_y = 0.0f;
        if (cursor_secondary_at_mouse_address == 0 ||
            cursor_screen_position_address == 0 ||
            game_object_global_address == 0 ||
            !memory.TryReadValue(
                game_object_global_address,
                &gameplay_address) ||
            gameplay_address == 0 ||
            !memory.TryReadValue(
                cursor_secondary_at_mouse_address,
                &original_cursor_secondary_at_mouse) ||
            !memory.TryReadField(
                gameplay_address,
                kGameplayCursorPlacementActiveOffset,
                &original_cursor_placement_active) ||
            !memory.TryReadValue(
                cursor_screen_position_address,
                &original_cursor_screen_x) ||
            !memory.TryReadValue(
                cursor_screen_position_address +
                    sizeof(original_cursor_screen_x),
                &original_cursor_screen_y) ||
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
            status = "stock_context_unreadable";
            return;
        }

        const auto screen_x =
            (authored_world_x - view_origin_x) * view_scale;
        const auto screen_y =
            (authored_world_y - view_origin_y) * view_scale;
        const auto minimum_screen = static_cast<double>(
            (std::numeric_limits<std::int32_t>::min)());
        const auto maximum_screen = static_cast<double>(
            (std::numeric_limits<std::int32_t>::max)());
        if (!std::isfinite(screen_x) ||
            !std::isfinite(screen_y) ||
            static_cast<double>(screen_x) < minimum_screen ||
            static_cast<double>(screen_x) > maximum_screen ||
            static_cast<double>(screen_y) < minimum_screen ||
            static_cast<double>(screen_y) > maximum_screen) {
            status = "screen_projection_out_of_range";
            return;
        }

        applied_cursor_screen_x = static_cast<std::int32_t>(
            std::llround(static_cast<double>(screen_x)));
        applied_cursor_screen_y = static_cast<std::int32_t>(
            std::llround(static_cast<double>(screen_y)));
        active = true;
        restored = false;
        constexpr std::uint8_t kEnabled = 1;
        if (!memory.TryWriteValue(
                cursor_secondary_at_mouse_address,
                kEnabled) ||
            !memory.TryWriteField(
                gameplay_address,
                kGameplayCursorPlacementActiveOffset,
                kEnabled) ||
            !memory.TryWriteValue(
                cursor_screen_position_address,
                applied_cursor_screen_x) ||
            !memory.TryWriteValue(
                cursor_screen_position_address +
                    sizeof(applied_cursor_screen_x),
                applied_cursor_screen_y)) {
            status = "stock_context_write_failed";
            RestoreAfterApplyFailure();
            return;
        }

        std::uint8_t verified_secondary_at_mouse = 0;
        std::uint8_t verified_placement_active = 0;
        std::int32_t verified_screen_x = 0;
        std::int32_t verified_screen_y = 0;
        if (!memory.TryReadValue(
                cursor_secondary_at_mouse_address,
                &verified_secondary_at_mouse) ||
            !memory.TryReadField(
                gameplay_address,
                kGameplayCursorPlacementActiveOffset,
                &verified_placement_active) ||
            !memory.TryReadValue(
                cursor_screen_position_address,
                &verified_screen_x) ||
            !memory.TryReadValue(
                cursor_screen_position_address + sizeof(verified_screen_x),
                &verified_screen_y) ||
            verified_secondary_at_mouse != kEnabled ||
            verified_placement_active != kEnabled ||
            verified_screen_x != applied_cursor_screen_x ||
            verified_screen_y != applied_cursor_screen_y) {
            status = "stock_context_verify_failed";
            RestoreAfterApplyFailure();
            return;
        }

        ready = true;
        status = "active";
    }

    void RestoreAfterApplyFailure() {
        const auto apply_failure = status;
        Restore();
        if (restored) {
            status = apply_failure + "_restored";
        }
    }

    void Restore() {
        if (!active || restore_attempted) {
            return;
        }
        restore_attempted = true;
        active = false;

        auto& memory = ProcessMemory::Instance();
        restored =
            memory.TryWriteValue(
                cursor_secondary_at_mouse_address,
                original_cursor_secondary_at_mouse) &&
            memory.TryWriteField(
                gameplay_address,
                kGameplayCursorPlacementActiveOffset,
                original_cursor_placement_active) &&
            memory.TryWriteValue(
                cursor_screen_position_address,
                original_cursor_screen_x) &&
            memory.TryWriteValue(
                cursor_screen_position_address +
                    sizeof(original_cursor_screen_x),
                original_cursor_screen_y);
        status = restored
                     ? (ready ? "restored" : status)
                     : "restore_failed";
        if (!restored) {
            Log(
                "[gameplay] secondary cursor-placement restore failed. actor=" +
                HexString(actor_address) +
                " skill_entry=" + std::to_string(skill_entry_index));
        }
    }

    std::string Describe() const {
        return
            "requested=" + std::to_string(requested ? 1 : 0) +
            " ready=" + std::to_string(ready ? 1 : 0) +
            " status=" + status +
            " authored_world=(" + std::to_string(authored_world_x) + "," +
                std::to_string(authored_world_y) + ")" +
            " applied_screen=(" +
                std::to_string(applied_cursor_screen_x) + "," +
                std::to_string(applied_cursor_screen_y) + ")" +
            " restore_attempted=" +
                std::to_string(restore_attempted ? 1 : 0) +
            " restored=" + std::to_string(restored ? 1 : 0);
    }
};

template <typename InvokeFn>
bool InvokeWithSecondaryCursorWorldPlacementContext(
    uintptr_t actor_address,
    std::int32_t skill_entry_index,
    bool requested,
    float authored_world_x,
    float authored_world_y,
    InvokeFn&& invoke,
    std::string* context_description = nullptr) {
    ScopedSecondaryCursorWorldPlacementContext cursor_context(
        actor_address,
        skill_entry_index,
        requested,
        authored_world_x,
        authored_world_y);
    if (cursor_context.ready) {
        invoke();
    }
    cursor_context.Restore();
    if (context_description != nullptr) {
        *context_description = cursor_context.Describe();
    }
    return cursor_context.ready && cursor_context.restored;
}
