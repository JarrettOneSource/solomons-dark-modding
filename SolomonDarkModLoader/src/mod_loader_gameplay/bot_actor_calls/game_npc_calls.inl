bool CallGameNpcSetMoveGoalSafe(
    uintptr_t set_move_goal_address,
    uintptr_t npc_address,
    std::uint8_t mode,
    int follow_flag,
    float x,
    float y,
    float extra_scalar,
    DWORD* exception_code,
    SehExceptionDetails* exception_details) {
    auto* set_move_goal = reinterpret_cast<GameNpcSetMoveGoalFn>(set_move_goal_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (exception_details != nullptr) {
        *exception_details = {};
    }
    if (set_move_goal == nullptr || npc_address == 0) {
        return false;
    }

    __try {
        set_move_goal(reinterpret_cast<void*>(npc_address), mode, follow_flag, x, y, extra_scalar);
        return true;
    } __except (
        exception_details != nullptr
            ? CaptureSehDetails(GetExceptionInformation(), exception_details)
            : CaptureSehCode(GetExceptionInformation(), exception_code)) {
        if (exception_code != nullptr && exception_details != nullptr) {
            *exception_code = exception_details->code;
        }
        return false;
    }
}

bool CallGameNpcSetTrackedSlotAssistSafe(
    uintptr_t set_tracked_slot_assist_address,
    uintptr_t npc_address,
    int slot_index,
    int require_callback,
    DWORD* exception_code,
    SehExceptionDetails* exception_details) {
    auto* set_tracked_slot_assist =
        reinterpret_cast<GameNpcSetTrackedSlotAssistFn>(set_tracked_slot_assist_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (exception_details != nullptr) {
        *exception_details = {};
    }
    if (set_tracked_slot_assist == nullptr || npc_address == 0 || slot_index < 0) {
        return false;
    }

    __try {
        set_tracked_slot_assist(reinterpret_cast<void*>(npc_address), slot_index, require_callback);
        return true;
    } __except (
        exception_details != nullptr
            ? CaptureSehDetails(GetExceptionInformation(), exception_details)
            : CaptureSehCode(GetExceptionInformation(), exception_code)) {
        if (exception_code != nullptr && exception_details != nullptr) {
            *exception_code = exception_details->code;
        }
        return false;
    }
}
