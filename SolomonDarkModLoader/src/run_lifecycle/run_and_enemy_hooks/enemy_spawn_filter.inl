enum class LuaEnemySpawnConfigWriteResult {
    Applied,
    RestoredAfterFailure,
    RestoreFailed,
};

void LogLuaEnemySpawnFilterHookFailure(
    std::atomic<std::uint32_t>* log_count,
    const std::string& message) {
    if (log_count != nullptr &&
        log_count->fetch_add(1, std::memory_order_relaxed) <
            kMaximumLuaEnemySpawnFilterHookLogCount) {
        Log("[lua] " + message);
    }
}

bool IsValidCapturedEnemySpawnValue(float value) {
    return std::isfinite(value) && value >= 0.0f && value <= 1'000'000.0f;
}

bool TryCaptureLuaEnemySpawnFilterContext(
    uintptr_t arena_address,
    uintptr_t config_address,
    LuaEnemySpawnFilterContext* context) {
    if (arena_address == 0 || config_address == 0 || context == nullptr) {
        return false;
    }

    *context = LuaEnemySpawnFilterContext{};
    context->arena_address = arena_address;
    context->config_address = config_address;
    context->wave_spawner_address = g_current_wave_spawner_tick_address;

    auto& memory = ProcessMemory::Instance();
    bool captured = TryReadEnemyTypeFromConfig(
        config_address,
        &context->native_type_id);
    captured = memory.TryReadField(
        config_address,
        kEnemySpawnConfigHpOffset,
        &context->hp) && captured;
    for (std::size_t index = 0;
         index < context->family_values.size();
         ++index) {
        captured = memory.TryReadField(
            config_address,
            kEnemySpawnConfigFamilyValuesOffset + index * sizeof(float),
            &context->family_values[index]) && captured;
    }
    captured = memory.TryReadField(
        config_address,
        kEnemySpawnConfigChaseSpeedOffset,
        &context->chase_speed) && captured;
    captured = memory.TryReadField(
        config_address,
        kEnemySpawnConfigAttackSpeedOffset,
        &context->attack_speed) && captured;
    captured = memory.TryReadField(
        config_address,
        kEnemySpawnConfigScaleOffset,
        &context->scale) && captured;
    if (!captured || !IsValidCapturedEnemySpawnValue(context->hp) ||
        !IsValidCapturedEnemySpawnValue(context->chase_speed) ||
        !IsValidCapturedEnemySpawnValue(context->attack_speed) ||
        !std::isfinite(context->scale) || context->scale < 0.01f ||
        context->scale > 1'000.0f) {
        return false;
    }
    return std::all_of(
        context->family_values.begin(),
        context->family_values.end(),
        [](float value) { return IsValidCapturedEnemySpawnValue(value); });
}

bool RestoreLuaEnemySpawnFilterConfig(
    const LuaEnemySpawnFilterContext& context) {
    auto& memory = ProcessMemory::Instance();
    bool restored = memory.TryWriteField(
        context.config_address,
        kEnemySpawnConfigHpOffset,
        context.hp);
    for (std::size_t index = 0;
         index < context.family_values.size();
         ++index) {
        restored = memory.TryWriteField(
            context.config_address,
            kEnemySpawnConfigFamilyValuesOffset + index * sizeof(float),
            context.family_values[index]) && restored;
    }
    restored = memory.TryWriteField(
        context.config_address,
        kEnemySpawnConfigChaseSpeedOffset,
        context.chase_speed) && restored;
    restored = memory.TryWriteField(
        context.config_address,
        kEnemySpawnConfigAttackSpeedOffset,
        context.attack_speed) && restored;
    restored = memory.TryWriteField(
        context.config_address,
        kEnemySpawnConfigScaleOffset,
        context.scale) && restored;
    return restored;
}

LuaEnemySpawnConfigWriteResult WriteLuaEnemySpawnFilterConfig(
    const LuaEnemySpawnFilterContext& original,
    const LuaEnemySpawnFilterContext& filtered) {
    auto& memory = ProcessMemory::Instance();
    bool wrote_all = memory.TryWriteField(
        filtered.config_address,
        kEnemySpawnConfigHpOffset,
        filtered.hp);
    for (std::size_t index = 0;
         wrote_all && index < filtered.family_values.size();
         ++index) {
        wrote_all = memory.TryWriteField(
            filtered.config_address,
            kEnemySpawnConfigFamilyValuesOffset + index * sizeof(float),
            filtered.family_values[index]);
    }
    wrote_all = wrote_all && memory.TryWriteField(
        filtered.config_address,
        kEnemySpawnConfigChaseSpeedOffset,
        filtered.chase_speed);
    wrote_all = wrote_all && memory.TryWriteField(
        filtered.config_address,
        kEnemySpawnConfigAttackSpeedOffset,
        filtered.attack_speed);
    wrote_all = wrote_all && memory.TryWriteField(
        filtered.config_address,
        kEnemySpawnConfigScaleOffset,
        filtered.scale);
    if (wrote_all) {
        return LuaEnemySpawnConfigWriteResult::Applied;
    }
    return RestoreLuaEnemySpawnFilterConfig(original)
        ? LuaEnemySpawnConfigWriteResult::RestoredAfterFailure
        : LuaEnemySpawnConfigWriteResult::RestoreFailed;
}

bool LuaEnemySpawnFilterContextChanged(
    const LuaEnemySpawnFilterContext& original,
    const LuaEnemySpawnFilterContext& filtered) {
    return original.hp != filtered.hp ||
        original.family_values != filtered.family_values ||
        original.chase_speed != filtered.chase_speed ||
        original.attack_speed != filtered.attack_speed ||
        original.scale != filtered.scale;
}

void* CanceledEnemySpawnResult() {
    return static_cast<void*>(g_canceled_enemy_spawn_result.data());
}
