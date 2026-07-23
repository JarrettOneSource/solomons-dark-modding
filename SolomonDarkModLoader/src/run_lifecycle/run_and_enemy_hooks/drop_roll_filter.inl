enum class LuaDropRollConfigWriteResult {
    Applied,
    RestoredAfterFailure,
    RestoreFailed,
};

constexpr std::size_t kDropSelectorBaseOffset = 0xCC;
constexpr std::size_t kDropArenaDisableMaskOffset = 0x8F04;
constexpr std::uint8_t kDropForcedSelectorValue = 3;
constexpr std::uint32_t kDropArenaCategoryMask = 0x3F;

void LogLuaDropRollFilterHookFailure(
    std::atomic<std::uint32_t>* log_count,
    const std::string& message) {
    if (log_count != nullptr &&
        log_count->fetch_add(1, std::memory_order_relaxed) <
            kMaximumLuaDropRollFilterHookLogCount) {
        Log("[lua] " + message);
    }
}

bool TryCaptureLuaDropRollFilterContext(
    uintptr_t enemy_address,
    LuaDropRollFilterContext* context) {
    if (enemy_address == 0 || context == nullptr) {
        return false;
    }

    *context = LuaDropRollFilterContext{};
    context->enemy_address = enemy_address;

    auto& memory = ProcessMemory::Instance();
    bool captured = memory.TryReadField(
        enemy_address,
        kActorOwnerOffset,
        &context->arena_address);
    captured = memory.TryReadField(
        enemy_address,
        kEnemyConfigOffset,
        &context->config_address) && captured;
    captured = TryReadEnemyTypeFromActor(
        enemy_address,
        &context->native_type_id) && captured;
    captured = memory.TryReadField(
        enemy_address,
        kActorPositionXOffset,
        &context->x) && captured;
    captured = memory.TryReadField(
        enemy_address,
        kActorPositionYOffset,
        &context->y) && captured;
    if (!captured || context->arena_address == 0 || context->config_address == 0 ||
        !std::isfinite(context->x) || !std::isfinite(context->y)) {
        return false;
    }

    for (std::size_t index = 0; index < context->selectors.size(); ++index) {
        if (!memory.TryReadField(
                context->config_address,
                kDropSelectorBaseOffset + index,
                &context->selectors[index]) ||
            context->selectors[index] > 5) {
            return false;
        }
    }
    return memory.TryReadField(
        context->arena_address,
        kDropArenaDisableMaskOffset,
        &context->arena_disable_mask);
}

bool TryGetForcedDropArenaBit(
    LuaDropForcedKind kind,
    std::uint32_t* arena_bit) {
    if (arena_bit == nullptr) {
        return false;
    }
    switch (kind) {
    case LuaDropForcedKind::Orb:
        *arena_bit = 3;
        return true;
    case LuaDropForcedKind::Gold:
        *arena_bit = 0;
        return true;
    case LuaDropForcedKind::Item:
        *arena_bit = 5;
        return true;
    case LuaDropForcedKind::Powerup:
        *arena_bit = 2;
        return true;
    case LuaDropForcedKind::Potion:
        *arena_bit = 1;
        return true;
    case LuaDropForcedKind::None:
    case LuaDropForcedKind::Stock:
        return false;
    }
    return false;
}

void BuildLuaDropRollNativePatch(
    const LuaDropRollFilterContext& original,
    const LuaDropRollFilterContext& filtered,
    std::array<std::uint8_t, kLuaDropSelectorCount>* selectors,
    std::uint32_t* arena_disable_mask) {
    *selectors = filtered.selectors;
    *arena_disable_mask = original.arena_disable_mask;
    if (filtered.forced_kind == LuaDropForcedKind::Stock) {
        return;
    }

    std::uint32_t allowed_arena_bit = 0;
    if (!TryGetForcedDropArenaBit(
            filtered.forced_kind,
            &allowed_arena_bit)) {
        return;
    }

    selectors->fill(kDropForcedSelectorValue);
    *arena_disable_mask =
        (original.arena_disable_mask | kDropArenaCategoryMask) &
        ~(1u << allowed_arena_bit);
}

bool RestoreLuaDropRollFilterState(
    const LuaDropRollFilterContext& context) {
    auto& memory = ProcessMemory::Instance();
    bool restored = true;
    for (std::size_t index = 0; index < context.selectors.size(); ++index) {
        restored = memory.TryWriteField(
            context.config_address,
            kDropSelectorBaseOffset + index,
            context.selectors[index]) && restored;
    }
    restored = memory.TryWriteField(
        context.arena_address,
        kDropArenaDisableMaskOffset,
        context.arena_disable_mask) && restored;
    return restored;
}

LuaDropRollConfigWriteResult WriteLuaDropRollFilterState(
    const LuaDropRollFilterContext& original,
    const LuaDropRollFilterContext& filtered) {
    std::array<std::uint8_t, kLuaDropSelectorCount> selectors{};
    std::uint32_t arena_disable_mask = 0;
    BuildLuaDropRollNativePatch(
        original,
        filtered,
        &selectors,
        &arena_disable_mask);

    auto& memory = ProcessMemory::Instance();
    bool wrote_all = true;
    for (std::size_t index = 0;
         wrote_all && index < selectors.size();
         ++index) {
        wrote_all = memory.TryWriteField(
            filtered.config_address,
            kDropSelectorBaseOffset + index,
            selectors[index]);
    }
    wrote_all = wrote_all && memory.TryWriteField(
        filtered.arena_address,
        kDropArenaDisableMaskOffset,
        arena_disable_mask);
    if (wrote_all) {
        return LuaDropRollConfigWriteResult::Applied;
    }
    return RestoreLuaDropRollFilterState(original)
        ? LuaDropRollConfigWriteResult::RestoredAfterFailure
        : LuaDropRollConfigWriteResult::RestoreFailed;
}

bool LuaDropRollFilterContextChanged(
    const LuaDropRollFilterContext& original,
    const LuaDropRollFilterContext& filtered) {
    return original.selectors != filtered.selectors ||
        filtered.forced_kind != LuaDropForcedKind::Stock;
}

void __fastcall HookDropSelector(void* self, void* unused_edx) {
    const auto original =
        GetX86HookTrampoline<DropSelectorFn>(g_state.hooks[kHookDropSelector]);
    if (original == nullptr) {
        return;
    }

    if (multiplayer::IsLocalTransportClient()) {
        original(self, unused_edx);
        return;
    }

    SDModLuaEnemySpawnConfig registered_config;
    const bool have_registered_policy =
        LookupLuaEnemySpawnConfig(
            reinterpret_cast<uintptr_t>(self),
            &registered_config) &&
        registered_config.loot_policy != SDModLuaEnemyLootPolicy::Stock;
    if (!HasLuaDropRollFilterHandlers() && !have_registered_policy) {
        original(self, unused_edx);
        return;
    }

    LuaDropRollFilterContext original_filter_context;
    LuaDropRollFilterContext filtered_context;
    if (!TryCaptureLuaDropRollFilterContext(
            reinterpret_cast<uintptr_t>(self),
            &filtered_context)) {
        LogLuaDropRollFilterHookFailure(
            &g_lua_drop_roll_filter_capture_log_count,
            "drop.rolling skipped because the stock selector state could not "
            "be captured. enemy=" +
                HexString(reinterpret_cast<uintptr_t>(self)));
        original(self, unused_edx);
        return;
    }
    original_filter_context = filtered_context;

    if (have_registered_policy) {
        switch (registered_config.loot_policy) {
        case SDModLuaEnemyLootPolicy::None:
            filtered_context.forced_kind = LuaDropForcedKind::None;
            break;
        case SDModLuaEnemyLootPolicy::Orb:
            filtered_context.forced_kind = LuaDropForcedKind::Orb;
            break;
        case SDModLuaEnemyLootPolicy::Gold:
            filtered_context.forced_kind = LuaDropForcedKind::Gold;
            break;
        case SDModLuaEnemyLootPolicy::Item:
            filtered_context.forced_kind = LuaDropForcedKind::Item;
            break;
        case SDModLuaEnemyLootPolicy::Powerup:
            filtered_context.forced_kind = LuaDropForcedKind::Powerup;
            break;
        case SDModLuaEnemyLootPolicy::Potion:
            filtered_context.forced_kind = LuaDropForcedKind::Potion;
            break;
        case SDModLuaEnemyLootPolicy::Stock:
            break;
        }
    }

    if (HasLuaDropRollFilterHandlers() &&
        !ApplyLuaDropRollFilters(&filtered_context)) {
        return;
    }
    if (filtered_context.forced_kind == LuaDropForcedKind::None) {
        return;
    }

    bool restore_filter_context = false;
    if (LuaDropRollFilterContextChanged(
            original_filter_context,
            filtered_context)) {
        const auto write_result = WriteLuaDropRollFilterState(
            original_filter_context,
            filtered_context);
        restore_filter_context =
            write_result == LuaDropRollConfigWriteResult::Applied;
        if (write_result != LuaDropRollConfigWriteResult::Applied) {
            LogLuaDropRollFilterHookFailure(
                &g_lua_drop_roll_filter_write_log_count,
                "drop.rolling rewrite failed. config=" +
                    HexString(filtered_context.config_address) +
                    " arena=" + HexString(filtered_context.arena_address) +
                    " restored=" +
                    (write_result ==
                             LuaDropRollConfigWriteResult::RestoredAfterFailure
                         ? "1"
                         : "0"));
            if (write_result == LuaDropRollConfigWriteResult::RestoreFailed) {
                return;
            }
        }
    }

    original(self, unused_edx);
    if (restore_filter_context &&
        !RestoreLuaDropRollFilterState(original_filter_context)) {
        LogLuaDropRollFilterHookFailure(
            &g_lua_drop_roll_filter_write_log_count,
            "drop.rolling stock selector restore failed after native roll. "
            "config=" + HexString(original_filter_context.config_address) +
                " arena=" + HexString(original_filter_context.arena_address));
    }
}
