bool SetLuaEnemyAiTargetOverride(
    std::string_view owner_mod_id,
    std::uint64_t network_actor_id,
    std::uint64_t content_id,
    std::uint32_t spawn_serial,
    uintptr_t actor_address,
    SDModLuaEnemyAiTargetMode target_mode,
    std::uint64_t target_participant_id,
    std::string* error_message) {
    return SetLuaEnemyAiTargetOverrideInternal(
        owner_mod_id,
        network_actor_id,
        content_id,
        spawn_serial,
        actor_address,
        target_mode,
        target_participant_id,
        error_message);
}

bool SetLuaEnemyAiMoveGoal(
    std::string_view owner_mod_id,
    std::uint64_t network_actor_id,
    std::uint64_t content_id,
    std::uint32_t spawn_serial,
    uintptr_t actor_address,
    float x,
    float y,
    float stop_distance,
    std::string* error_message) {
    return SetLuaEnemyAiMoveGoalInternal(
        owner_mod_id,
        network_actor_id,
        content_id,
        spawn_serial,
        actor_address,
        x,
        y,
        stop_distance,
        error_message);
}

bool StopLuaEnemyAiMoveGoal(
    std::string_view owner_mod_id,
    std::uint64_t network_actor_id) {
    return StopLuaEnemyAiMoveGoalInternal(owner_mod_id, network_actor_id);
}

bool ClearLuaEnemyAiOverrides(
    std::string_view owner_mod_id,
    std::uint64_t network_actor_id) {
    return ClearLuaEnemyAiOverridesInternal(owner_mod_id, network_actor_id);
}

bool TryGetLuaEnemyAiCommandState(
    std::string_view owner_mod_id,
    std::uint64_t network_actor_id,
    SDModLuaEnemyAiCommandState* state) {
    return TryGetLuaEnemyAiCommandStateInternal(
        owner_mod_id,
        network_actor_id,
        state);
}

void ClearLuaEnemyAiOverridesForMod(std::string_view owner_mod_id) {
    ClearLuaEnemyAiOverridesForModInternal(owner_mod_id);
}

void ResetLuaEnemyAiOverrides() {
    ResetLuaEnemyAiOverridesInternal();
}
