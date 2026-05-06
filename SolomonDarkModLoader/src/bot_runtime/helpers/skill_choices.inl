struct NativeIntArray {
    uintptr_t vtable = 0;
    std::int32_t* values = nullptr;
    std::int32_t count = 0;
    std::uint16_t flags = 0;
    std::uint16_t padding = 0;
};

static_assert(sizeof(NativeIntArray) == 0x10, "Native int array layout changed");

using NativeSkillOptionRollFn = void(__thiscall*)(void* progression, int desired_count, NativeIntArray* output);
using NativeIntArrayClearFn = void(__thiscall*)(void* array);
using NativeProgressionNoArgFn = void(__thiscall*)(void* progression);
using NativeProgressionIntArgFn = void(__thiscall*)(void* progression, int value);
using NativePlayerAppearanceApplyChoiceFn = void(__thiscall*)(void* progression, int choice_id, int ensure_assets);
using NativeActorProgressionRefreshFn = void(__thiscall*)(void* progression);
using NativeLevelUpFn = void(__fastcall*)(void* progression, void* unused_edx);

constexpr int kBaseLevelUpChoiceCount = 3;
constexpr int kBonusLevelUpChoiceCount = 4;
constexpr int kNativeSkillChoiceMaxCopyCount = 16;

int NativeBonusLevelUpChoiceCountSkillId() {
    return static_cast<int>(kGameplaySkillChoiceBonusChoiceCountSkillId);
}

int NativeSpecialChoiceActivationId() {
    return static_cast<int>(kGameplaySkillChoiceSpecialActivationId);
}

std::string FormatSkillChoiceOptionsForLog(const std::vector<BotSkillChoiceOption>& options) {
    std::string text;
    for (std::size_t index = 0; index < options.size(); ++index) {
        if (index != 0) {
            text += ",";
        }
        text += std::to_string(options[index].option_id);
        if (options[index].apply_count != 1) {
            text += "x" + std::to_string(options[index].apply_count);
        }
    }
    return text;
}

int CaptureBotSkillChoiceSeh(EXCEPTION_POINTERS* exception_pointers, DWORD* exception_code) {
    if (exception_code != nullptr && exception_pointers != nullptr && exception_pointers->ExceptionRecord != nullptr) {
        *exception_code = exception_pointers->ExceptionRecord->ExceptionCode;
    }
    return EXCEPTION_EXECUTE_HANDLER;
}

bool TryReadProgressionVtableSlot(uintptr_t progression_address, std::size_t slot_offset, uintptr_t* method_address) {
    if (method_address == nullptr) {
        return false;
    }

    *method_address = 0;
    if (progression_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t vtable = 0;
    if (!memory.TryReadValue(progression_address, &vtable)) {
        return false;
    }
    if (vtable == 0 || !memory.IsReadableRange(vtable + slot_offset, sizeof(uintptr_t))) {
        return false;
    }

    return memory.TryReadValue(vtable + slot_offset, method_address) && *method_address != 0;
}

bool CallNativeIntArrayClear(NativeIntArray* array, DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    const auto clear_address = ProcessMemory::Instance().ResolveGameAddressOrZero(kNativeIntArrayClear);
    auto* clear_array = reinterpret_cast<NativeIntArrayClearFn>(clear_address);
    if (clear_array == nullptr || array == nullptr) {
        return false;
    }

    __try {
        clear_array(array);
        return true;
    } __except (CaptureBotSkillChoiceSeh(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallNativeSkillOptionRoll(
    NativeSkillOptionRollFn roll_options,
    uintptr_t progression_address,
    int desired_count,
    NativeIntArray* native_options,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (roll_options == nullptr || progression_address == 0 || native_options == nullptr) {
        return false;
    }

    __try {
        roll_options(
            reinterpret_cast<void*>(progression_address),
            std::clamp(desired_count, 1, kNativeSkillChoiceMaxCopyCount),
            native_options);
        return true;
    } __except (CaptureBotSkillChoiceSeh(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool TryResolveNativeSkillChoiceCount(uintptr_t progression_address, int* choice_count) {
    if (choice_count == nullptr) {
        return false;
    }

    *choice_count = 0;
    if (progression_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t table_address = 0;
    std::int32_t table_count = 0;
    if (!memory.TryReadField(progression_address, kStandaloneWizardProgressionTableBaseOffset, &table_address) ||
        !memory.TryReadField(progression_address, kStandaloneWizardProgressionTableCountOffset, &table_count)) {
        return false;
    }
    const auto bonus_choice_skill_id = NativeBonusLevelUpChoiceCountSkillId();
    if (table_address == 0 || table_count <= bonus_choice_skill_id) {
        return false;
    }

    const auto visible_offset =
        static_cast<std::size_t>(bonus_choice_skill_id) * kStandaloneWizardProgressionEntryStride +
        kStandaloneWizardProgressionVisibleFlagOffset;
    std::uint16_t visible = 0;
    if (!memory.TryReadValue(table_address + visible_offset, &visible)) {
        return false;
    }

    *choice_count = visible > 0 ? kBonusLevelUpChoiceCount : kBaseLevelUpChoiceCount;
    return true;
}

bool RollNativeSkillChoiceOptions(
    uintptr_t progression_address,
    std::vector<BotSkillChoiceOption>* options,
    DWORD* exception_code,
    int* requested_choice_count = nullptr) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (options == nullptr) {
        return false;
    }
    options->clear();
    if (progression_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    int desired_count = 0;
    if (!TryResolveNativeSkillChoiceCount(progression_address, &desired_count)) {
        return false;
    }
    if (requested_choice_count != nullptr) {
        *requested_choice_count = desired_count;
    }
    const auto array_vtable = memory.ResolveGameAddressOrZero(kNativeIntArrayVtable);
    uintptr_t roll_address = 0;
    (void)TryReadProgressionVtableSlot(progression_address, kNativeSkillOptionRollVtableOffset, &roll_address);
    auto* roll_options = reinterpret_cast<NativeSkillOptionRollFn>(roll_address);
    if (array_vtable == 0 || roll_options == nullptr) {
        return false;
    }

    NativeIntArray native_options{};
    native_options.vtable = array_vtable;
    const bool rolled = CallNativeSkillOptionRoll(
        roll_options,
        progression_address,
        desired_count,
        &native_options,
        exception_code);

    if (rolled) {
        const auto count = std::clamp(native_options.count, 0, kNativeSkillChoiceMaxCopyCount);
        if (count > 0 && native_options.values != nullptr) {
            const auto values_address = reinterpret_cast<uintptr_t>(native_options.values);
            if (memory.IsReadableRange(values_address, static_cast<std::size_t>(count) * sizeof(std::int32_t))) {
                for (int index = 0; index < count; ++index) {
                    std::int32_t option_id = -1;
                    if (!memory.TryReadValue(values_address + static_cast<std::size_t>(index) * sizeof(std::int32_t), &option_id)) {
                        continue;
                    }
                    if (option_id >= 0) {
                        options->push_back(BotSkillChoiceOption{option_id, 1});
                    }
                }
            }
        }
    }

    if (native_options.values != nullptr) {
        DWORD clear_exception = 0;
        if (!CallNativeIntArrayClear(&native_options, &clear_exception)) {
            Log(
                "[bots] native skill option array cleanup failed progression=" +
                HexString(progression_address) +
                " exception=0x" + HexString(clear_exception));
        }
    }

    return rolled && !options->empty();
}

bool CallNativeProgressionNoArg(
    uintptr_t progression_address,
    std::size_t vtable_slot_offset,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    uintptr_t method_address = 0;
    (void)TryReadProgressionVtableSlot(progression_address, vtable_slot_offset, &method_address);
    auto* method = reinterpret_cast<NativeProgressionNoArgFn>(method_address);
    if (method == nullptr || progression_address == 0) {
        return false;
    }

    __try {
        method(reinterpret_cast<void*>(progression_address));
        return true;
    } __except (CaptureBotSkillChoiceSeh(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallNativeProgressionIntArg(
    uintptr_t progression_address,
    std::size_t vtable_slot_offset,
    int value,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    uintptr_t method_address = 0;
    (void)TryReadProgressionVtableSlot(progression_address, vtable_slot_offset, &method_address);
    auto* method = reinterpret_cast<NativeProgressionIntArgFn>(method_address);
    if (method == nullptr || progression_address == 0) {
        return false;
    }

    __try {
        method(reinterpret_cast<void*>(progression_address), value);
        return true;
    } __except (CaptureBotSkillChoiceSeh(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallNativePlayerAppearanceApplyChoice(
    uintptr_t progression_address,
    int choice_id,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    const auto apply_choice_address = ProcessMemory::Instance().ResolveGameAddressOrZero(kPlayerAppearanceApplyChoice);
    auto* apply_choice = reinterpret_cast<NativePlayerAppearanceApplyChoiceFn>(apply_choice_address);
    if (apply_choice == nullptr || progression_address == 0 || choice_id < 0) {
        return false;
    }

    __try {
        apply_choice(reinterpret_cast<void*>(progression_address), choice_id, 1);
        return true;
    } __except (CaptureBotSkillChoiceSeh(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallNativeActorProgressionRefresh(uintptr_t progression_address, DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    const auto refresh_address = ProcessMemory::Instance().ResolveGameAddressOrZero(kActorProgressionRefresh);
    auto* refresh_progression = reinterpret_cast<NativeActorProgressionRefreshFn>(refresh_address);
    if (refresh_progression == nullptr || progression_address == 0) {
        return false;
    }

    __try {
        refresh_progression(reinterpret_cast<void*>(progression_address));
        return true;
    } __except (CaptureBotSkillChoiceSeh(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool EnsureBotOwnedProgressionMode(uintptr_t progression_address) {
    if (progression_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    std::uint8_t previous_mode = kProgressionLocalPlayerModeValue;
    const bool read_previous = memory.TryReadField<std::uint8_t>(
        progression_address,
        kProgressionNonLocalModeFlagOffset,
        &previous_mode);
    if (read_previous && previous_mode == kProgressionNonLocalModeValue) {
        return true;
    }

    if (!memory.TryWriteField<std::uint8_t>(
            progression_address,
            kProgressionNonLocalModeFlagOffset,
            kProgressionNonLocalModeValue)) {
        Log(
            "[bots] bot-owned progression mode failed before native level_up. progression=" +
            HexString(progression_address));
        return false;
    }

    Log(
        "[bots] bot-owned progression mode set before native level_up. progression=" +
        HexString(progression_address) +
        " previous_mode=" + (read_previous ? std::to_string(previous_mode) : "unreadable") +
        " mode=" + std::to_string(kProgressionNonLocalModeValue));
    return true;
}

bool CallNativeLevelUpSafe(uintptr_t progression_address, DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    const auto level_up_address = ProcessMemory::Instance().ResolveGameAddressOrZero(kLevelUp);
    auto* level_up = reinterpret_cast<NativeLevelUpFn>(level_up_address);
    if (level_up == nullptr || progression_address == 0) {
        return false;
    }

    __try {
        // This intentionally calls the game's native level_up entrypoint. When
        // the run-lifecycle hook is installed, the patched entrypoint still
        // reaches the original through the hook trampoline and preserves the
        // non-local picker guard used for bot progressions.
        level_up(reinterpret_cast<void*>(progression_address), nullptr);
        return true;
    } __except (CaptureBotSkillChoiceSeh(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool ApplyNativeSpecialChoice(uintptr_t progression_address, DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (progression_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t table_address = 0;
    std::int32_t table_count = 0;
    if (!memory.TryReadField(progression_address, kStandaloneWizardProgressionTableBaseOffset, &table_address) ||
        !memory.TryReadField(progression_address, kStandaloneWizardProgressionTableCountOffset, &table_count)) {
        return false;
    }
    const auto special_choice_id = NativeSpecialChoiceActivationId();
    if (table_address == 0 || table_count <= special_choice_id) {
        return false;
    }

    const auto entry_active_offset =
        static_cast<std::size_t>(special_choice_id) * kStandaloneWizardProgressionEntryStride +
        kStandaloneWizardProgressionActiveFlagOffset;
    const std::uint16_t active = 1;
    if (!memory.TryWriteValue<std::uint16_t>(table_address + entry_active_offset, active)) {
        return false;
    }

    std::int32_t special_argument = 0;
    if (!memory.TryReadField(progression_address, kProgressionSpecialChoiceArgumentOffset, &special_argument)) {
        return false;
    }
    return CallNativeProgressionIntArg(
        progression_address,
        kNativeSpecialChoiceActivateVtableOffset,
        special_argument,
        exception_code);
}

bool ApplyNativeSkillChoiceToProgression(
    uintptr_t progression_address,
    const BotSkillChoiceOption& option,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (progression_address == 0 || option.option_id < 0) {
        return false;
    }

    const auto apply_count = std::clamp(option.apply_count, 1, 2);
    for (int apply_index = 0; apply_index < apply_count; ++apply_index) {
        if (!CallNativePlayerAppearanceApplyChoice(progression_address, option.option_id, exception_code)) {
            return false;
        }
    }

    const auto special_choice_id = NativeSpecialChoiceActivationId();
    if (option.option_id == special_choice_id) {
        DWORD special_exception = 0;
        if (!ApplyNativeSpecialChoice(progression_address, &special_exception)) {
            Log(
                "[bots] native special skill choice post-apply path failed progression=" +
                HexString(progression_address) +
                " choice_id=" + std::to_string(special_choice_id) +
                " exception=0x" + HexString(special_exception));
        }
    }

    if (!CallNativeActorProgressionRefresh(progression_address, exception_code)) {
        return false;
    }

    if (option.option_id == special_choice_id) {
        DWORD post_exception = 0;
        if (!CallNativeProgressionNoArg(
                progression_address,
                kNativeSpecialChoicePostRefreshVtableOffset,
                &post_exception)) {
            Log(
                "[bots] native special skill choice post-refresh path failed progression=" +
                HexString(progression_address) +
                " choice_id=" + std::to_string(special_choice_id) +
                " exception=0x" + HexString(post_exception));
        }
    }

    return true;
}

bool TryReadProgressionRoundedXp(uintptr_t progression_address, int* experience) {
    if (experience == nullptr) {
        return false;
    }

    *experience = -1;
    if (progression_address == 0) {
        return false;
    }

    float xp = 0.0f;
    if (!ProcessMemory::Instance().TryReadField(progression_address, kProgressionXpOffset, &xp) ||
        !std::isfinite(xp) ||
        xp < 0.0f) {
        return false;
    }

    *experience = static_cast<int>(std::lround(xp));
    return true;
}

bool TryReadProgressionNextXp(uintptr_t progression_address, int* next_experience) {
    if (next_experience == nullptr) {
        return false;
    }

    *next_experience = 0;
    if (progression_address == 0) {
        return false;
    }

    float next_xp = 0.0f;
    if (!ProcessMemory::Instance().TryReadField(
            progression_address,
            kProgressionNextXpThresholdOffset,
            &next_xp) ||
        !std::isfinite(next_xp) ||
        next_xp < 0.0f) {
        return false;
    }

    *next_experience = static_cast<int>(std::lround(next_xp));
    return true;
}

void UpdateBotLevelProfileState(
    std::uint64_t bot_id,
    int level,
    int experience,
    int next_experience) {
    UpdateRuntimeState([&](RuntimeState& state) {
        auto* participant = FindBot(state, bot_id);
        if (participant == nullptr) {
            return;
        }
        participant->character_profile.level = level;
        participant->character_profile.experience = experience;
        participant->runtime.level = level;
        participant->runtime.experience_current = experience;
        if (next_experience > 0) {
            participant->runtime.experience_next = next_experience;
        }
    });
}

bool SyncNativeBotProgressionLevel(
    uintptr_t progression_address,
    uintptr_t source_progression_address,
    int level,
    int experience,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (progression_address == 0 || level <= 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (!EnsureBotOwnedProgressionMode(progression_address)) {
        return false;
    }

    std::int32_t level_before = 0;
    float xp_before = 0.0f;
    if (!memory.TryReadField(progression_address, kProgressionLevelOffset, &level_before) ||
        !memory.TryReadField(progression_address, kProgressionXpOffset, &xp_before) ||
        !std::isfinite(xp_before)) {
        return false;
    }

    float target_xp = static_cast<float>(experience);
    if (source_progression_address != 0) {
        float source_xp = 0.0f;
        if (!memory.TryReadField(source_progression_address, kProgressionXpOffset, &source_xp) ||
            !std::isfinite(source_xp)) {
            return false;
        }
        if (source_xp >= 0.0f && source_xp > target_xp) {
            target_xp = source_xp;
        }
    }

    if (experience >= 0 && target_xp >= 0.0f) {
        (void)memory.TryWriteField<float>(progression_address, kProgressionXpOffset, target_xp);
    }

    if (level_before >= level) {
        Log(
            "[bots] native level_up sync skipped; progression already at target. progression=" +
            HexString(progression_address) +
            " level_before=" + std::to_string(level_before) +
            " target_level=" + std::to_string(level) +
            " xp_before=" + std::to_string(xp_before) +
            " target_xp=" + std::to_string(target_xp));
        return true;
    }

    constexpr int kMaxNativeLevelUpCalls = 256;
    int level_after = level_before;
    int calls = 0;
    while (level_after < level && calls < kMaxNativeLevelUpCalls) {
        const auto previous_level = level_after;
        if (!CallNativeLevelUpSafe(progression_address, exception_code)) {
            return false;
        }

        ++calls;
        if (!memory.TryReadField(progression_address, kProgressionLevelOffset, &level_after)) {
            return false;
        }
        if (level_after <= previous_level) {
            break;
        }
    }

    float xp_after = 0.0f;
    float previous_threshold = 0.0f;
    float next_threshold = 0.0f;
    if (!memory.TryReadField(progression_address, kProgressionXpOffset, &xp_after) ||
        !memory.TryReadField(progression_address, kProgressionPreviousXpThresholdOffset, &previous_threshold) ||
        !memory.TryReadField(progression_address, kProgressionNextXpThresholdOffset, &next_threshold) ||
        !std::isfinite(xp_after) ||
        !std::isfinite(previous_threshold) ||
        !std::isfinite(next_threshold)) {
        return false;
    }
    const bool synced = level_after >= level;
    Log(
        "[bots] native level_up sync. progression=" + HexString(progression_address) +
        " level_before=" + std::to_string(level_before) +
        " level_after=" + std::to_string(level_after) +
        " target_level=" + std::to_string(level) +
        " calls=" + std::to_string(calls) +
        " xp_before=" + std::to_string(xp_before) +
        " xp_after=" + std::to_string(xp_after) +
        " previous_threshold=" + std::to_string(previous_threshold) +
        " next_threshold=" + std::to_string(next_threshold) +
        " synced=" + std::to_string(synced ? 1 : 0));
    return synced;
}
