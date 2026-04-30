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

constexpr std::size_t kProgressionPreviousXpThresholdOffset = 0x38;
constexpr std::size_t kProgressionNextXpThresholdOffset = 0x3C;
constexpr std::size_t kProgressionSpecialChoiceArgumentOffset = 0x844;
constexpr std::size_t kNativeSkillOptionRollVtableOffset = 0x74;
constexpr std::size_t kNativeSpecialChoicePostRefreshVtableOffset = 0x94;
constexpr std::size_t kNativeSpecialChoiceActivateVtableOffset = 0x9C;
constexpr int kBaseLevelUpChoiceCount = 3;
constexpr int kBonusLevelUpChoiceCount = 4;
constexpr int kNativeSkillChoiceMaxCopyCount = 16;
constexpr int kBonusLevelUpChoiceCountSkillId = 0x3F;
constexpr int kSpecialChoice34Id = 0x34;

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

uintptr_t ReadProgressionVtableSlot(uintptr_t progression_address, std::size_t slot_offset) {
    if (progression_address == 0) {
        return 0;
    }

    auto& memory = ProcessMemory::Instance();
    const auto vtable = memory.ReadValueOr<uintptr_t>(progression_address, 0);
    if (vtable == 0 || !memory.IsReadableRange(vtable + slot_offset, sizeof(uintptr_t))) {
        return 0;
    }

    return memory.ReadValueOr<uintptr_t>(vtable + slot_offset, 0);
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

int ResolveNativeSkillChoiceCount(uintptr_t progression_address) {
    if (progression_address == 0) {
        return kBaseLevelUpChoiceCount;
    }

    auto& memory = ProcessMemory::Instance();
    const auto table_address =
        memory.ReadFieldOr<uintptr_t>(progression_address, kStandaloneWizardProgressionTableBaseOffset, 0);
    const auto table_count =
        memory.ReadFieldOr<std::int32_t>(progression_address, kStandaloneWizardProgressionTableCountOffset, 0);
    if (table_address == 0 || table_count <= kBonusLevelUpChoiceCountSkillId) {
        return kBaseLevelUpChoiceCount;
    }

    const auto visible_offset =
        static_cast<std::size_t>(kBonusLevelUpChoiceCountSkillId) * kStandaloneWizardProgressionEntryStride +
        kStandaloneWizardProgressionVisibleFlagOffset;
    const auto visible = memory.ReadValueOr<std::uint16_t>(table_address + visible_offset, 0);
    return visible > 0 ? kBonusLevelUpChoiceCount : kBaseLevelUpChoiceCount;
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
    const auto desired_count = ResolveNativeSkillChoiceCount(progression_address);
    if (requested_choice_count != nullptr) {
        *requested_choice_count = desired_count;
    }
    const auto array_vtable = memory.ResolveGameAddressOrZero(kNativeIntArrayVtable);
    const auto roll_address = ReadProgressionVtableSlot(progression_address, kNativeSkillOptionRollVtableOffset);
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
    const auto method_address = ReadProgressionVtableSlot(progression_address, vtable_slot_offset);
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
    const auto method_address = ReadProgressionVtableSlot(progression_address, vtable_slot_offset);
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

bool ApplyNativeSpecialChoice34(uintptr_t progression_address, DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (progression_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto table_address =
        memory.ReadFieldOr<uintptr_t>(progression_address, kStandaloneWizardProgressionTableBaseOffset, 0);
    const auto table_count =
        memory.ReadFieldOr<std::int32_t>(progression_address, kStandaloneWizardProgressionTableCountOffset, 0);
    if (table_address == 0 || table_count <= kSpecialChoice34Id) {
        return false;
    }

    const auto entry_active_offset =
        static_cast<std::size_t>(kSpecialChoice34Id) * kStandaloneWizardProgressionEntryStride +
        kStandaloneWizardProgressionActiveFlagOffset;
    const std::uint16_t active = 1;
    (void)memory.TryWriteValue<std::uint16_t>(table_address + entry_active_offset, active);

    const auto special_argument =
        memory.ReadFieldOr<std::int32_t>(progression_address, kProgressionSpecialChoiceArgumentOffset, 0);
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

    if (option.option_id == kSpecialChoice34Id) {
        DWORD special_exception = 0;
        if (!ApplyNativeSpecialChoice34(progression_address, &special_exception)) {
            Log(
                "[bots] native special skill choice 0x34 post-apply path failed progression=" +
                HexString(progression_address) +
                " exception=0x" + HexString(special_exception));
        }
    }

    if (!CallNativeActorProgressionRefresh(progression_address, exception_code)) {
        return false;
    }

    if (option.option_id == kSpecialChoice34Id) {
        DWORD post_exception = 0;
        if (!CallNativeProgressionNoArg(
                progression_address,
                kNativeSpecialChoicePostRefreshVtableOffset,
                &post_exception)) {
            Log(
                "[bots] native special skill choice 0x34 post-refresh path failed progression=" +
                HexString(progression_address) +
                " exception=0x" + HexString(post_exception));
        }
    }

    return true;
}

int ReadProgressionRoundedXpOrFallback(uintptr_t progression_address, int fallback) {
    if (progression_address == 0) {
        return fallback;
    }
    const auto xp = ProcessMemory::Instance().ReadFieldOr<float>(
        progression_address,
        kProgressionXpOffset,
        static_cast<float>(fallback));
    if (xp < 0.0f || xp != xp) {
        return fallback;
    }
    return static_cast<int>(std::lround(xp));
}

int ReadProgressionNextXpOrZero(uintptr_t progression_address) {
    if (progression_address == 0) {
        return 0;
    }
    const auto next_xp = ProcessMemory::Instance().ReadFieldOr<float>(
        progression_address,
        kProgressionNextXpThresholdOffset,
        0.0f);
    if (next_xp < 0.0f || next_xp != next_xp) {
        return 0;
    }
    return static_cast<int>(std::lround(next_xp));
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
    bool wrote_any = false;
    wrote_any |= memory.TryWriteField<std::int32_t>(progression_address, kProgressionLevelOffset, level);
    wrote_any |= memory.TryWriteField<float>(progression_address, kProgressionXpOffset, static_cast<float>(experience));

    if (source_progression_address != 0) {
        const auto previous_threshold = memory.ReadFieldOr<float>(
            source_progression_address,
            kProgressionPreviousXpThresholdOffset,
            -1.0f);
        const auto next_threshold = memory.ReadFieldOr<float>(
            source_progression_address,
            kProgressionNextXpThresholdOffset,
            -1.0f);
        if (previous_threshold >= 0.0f) {
            wrote_any |= memory.TryWriteField<float>(
                progression_address,
                kProgressionPreviousXpThresholdOffset,
                previous_threshold);
        }
        if (next_threshold >= 0.0f) {
            wrote_any |= memory.TryWriteField<float>(
                progression_address,
                kProgressionNextXpThresholdOffset,
                next_threshold);
        }
    }

    const auto max_hp = memory.ReadFieldOr<float>(progression_address, kProgressionMaxHpOffset, 0.0f);
    if (max_hp > 0.0f) {
        wrote_any |= memory.TryWriteField<float>(progression_address, kProgressionHpOffset, max_hp);
    }
    const auto max_mp = memory.ReadFieldOr<float>(progression_address, kProgressionMaxMpOffset, 0.0f);
    if (max_mp > 0.0f) {
        wrote_any |= memory.TryWriteField<float>(progression_address, kProgressionMpOffset, max_mp);
    }

    if (!wrote_any) {
        return false;
    }

    return CallNativeActorProgressionRefresh(progression_address, exception_code);
}
