#include "native_spell_stats.h"

#include "gameplay_seams.h"
#include "memory_access.h"

#include <Windows.h>

#include <algorithm>
#include <cmath>

namespace sdmod {
namespace {

using SkillsWizardBuildPrimarySpellFn = void(__thiscall*)(
    void* self,
    std::uint32_t primary_entry,
    std::uint32_t combo_entry,
    std::uint32_t reserved0,
    std::uint32_t reserved1,
    std::uint32_t reserved2,
    std::uint32_t reserved3);

struct NativePrimarySkillPair {
    int skill_id;
    int primary_entry_index;
    int combo_entry_index;
};

constexpr NativePrimarySkillPair kNativePrimarySkillPairs[] = {
    {1000, 0x08, 0x10},
    {0x3EA, 0x08, 0x18},
    {0x3E9, 0x08, 0x20},
    {0x3EE, 0x08, 0x28},
    {0x3EB, 0x10, 0x18},
    {0x3ED, 0x10, 0x20},
    {0x3EF, 0x10, 0x28},
    {0x3EC, 0x18, 0x20},
    {0x3F1, 0x18, 0x28},
    {0x3F0, 0x20, 0x28},
    {0x3F2, 0x08, 0x08},
    {0x3F3, 0x10, 0x10},
    {0x3F5, 0x18, 0x18},
    {0x3F4, 0x20, 0x20},
    {0x3F6, 0x28, 0x28},
};

int CaptureNativeSpellStatsSehCode(EXCEPTION_POINTERS* exception_info, DWORD* exception_code) {
    if (exception_code != nullptr && exception_info != nullptr && exception_info->ExceptionRecord != nullptr) {
        *exception_code = exception_info->ExceptionRecord->ExceptionCode;
    }
    return EXCEPTION_EXECUTE_HANDLER;
}

bool CallSkillsWizardBuildPrimarySpellSafe(
    uintptr_t build_address,
    uintptr_t progression_address,
    std::uint32_t primary_entry_arg,
    std::uint32_t combo_entry_arg,
    DWORD* exception_code) {
    auto* build_primary_spell =
        reinterpret_cast<SkillsWizardBuildPrimarySpellFn>(build_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (build_primary_spell == nullptr || progression_address == 0) {
        return false;
    }

    __try {
        build_primary_spell(
            reinterpret_cast<void*>(progression_address),
            primary_entry_arg,
            combo_entry_arg,
            0,
            0,
            0,
            0);
        return true;
    } __except (CaptureNativeSpellStatsSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool EntriesMatch(int left_primary, int left_combo, int right_primary, int right_combo) {
    return (left_primary == right_primary && left_combo == right_combo) ||
           (left_primary == right_combo && left_combo == right_primary);
}

bool EntryUsesContinuousMana(int entry_index) {
    return entry_index == 0x18 || entry_index == 0x20 || entry_index == 0x28;
}

bool NativePrimaryManaOutputUsesDisplayScale(const NativePrimarySpellSelection& selection) {
    return selection.pure_primary &&
           selection.primary_entry_index != ResolveNativePrimaryEntryForElement(0);
}

bool TryReadNativePrimaryManaOutputScale(float* output_scale, std::string* error_message) {
    if (output_scale != nullptr) {
        *output_scale = 1.0f;
    }

    auto& memory = ProcessMemory::Instance();
    const auto scale_address =
        memory.ResolveGameAddressOrZero(kActorWalkCyclePrimaryDivisorGlobal);
    if (scale_address == 0 || !memory.IsReadableRange(scale_address, sizeof(double))) {
        if (error_message != nullptr) {
            *error_message = "native primary mana output scale is not readable";
        }
        return false;
    }

    const auto scale = memory.ReadValueOr<double>(scale_address, 0.0);
    if (!std::isfinite(scale) || scale <= 0.0) {
        if (error_message != nullptr) {
            *error_message =
                "native primary mana output scale is invalid: " +
                std::to_string(scale);
        }
        return false;
    }

    if (output_scale != nullptr) {
        *output_scale = static_cast<float>(scale);
    }
    return true;
}

bool TryReadNativePrimaryStatOutputs(
    uintptr_t progression_runtime_address,
    std::size_t minimum_output_count,
    uintptr_t* output_values_address,
    std::size_t* output_count,
    std::string* error_message) {
    auto& memory = ProcessMemory::Instance();
    if (output_values_address != nullptr) {
        *output_values_address = 0;
    }
    if (output_count != nullptr) {
        *output_count = 0;
    }
    if (progression_runtime_address == 0) {
        if (error_message != nullptr) {
            *error_message = "native spell stats require a live progression runtime";
        }
        return false;
    }
    if (kProgressionPrimaryStatValuesOffset == 0 || kProgressionPrimaryStatCountOffset == 0) {
        if (error_message != nullptr) {
            *error_message = "native primary spell stat output offsets are not loaded";
        }
        return false;
    }
    if (!memory.IsReadableRange(
            progression_runtime_address + kProgressionPrimaryStatValuesOffset,
            sizeof(uintptr_t)) ||
        !memory.IsReadableRange(
            progression_runtime_address + kProgressionPrimaryStatCountOffset,
            sizeof(std::int32_t))) {
        if (error_message != nullptr) {
            *error_message = "native primary spell stat output fields are not readable";
        }
        return false;
    }

    const auto values_address =
        memory.ReadFieldOr<uintptr_t>(
            progression_runtime_address,
            kProgressionPrimaryStatValuesOffset,
            0);
    const auto count =
        memory.ReadFieldOr<std::int32_t>(
            progression_runtime_address,
            kProgressionPrimaryStatCountOffset,
            0);
    if (values_address == 0 || count <= 0) {
        if (error_message != nullptr) {
            *error_message = "native primary spell stat output array is empty";
        }
        return false;
    }
    if (static_cast<std::size_t>(count) < minimum_output_count) {
        if (error_message != nullptr) {
            *error_message =
                "native primary spell stat output count " +
                std::to_string(count) +
                " is smaller than required count " +
                std::to_string(minimum_output_count);
        }
        return false;
    }
    const auto byte_count = static_cast<std::size_t>(count) * sizeof(float);
    if (!memory.IsReadableRange(values_address, byte_count)) {
        if (error_message != nullptr) {
            *error_message = "native primary spell stat output array is not readable";
        }
        return false;
    }

    if (output_values_address != nullptr) {
        *output_values_address = values_address;
    }
    if (output_count != nullptr) {
        *output_count = static_cast<std::size_t>(count);
    }
    return true;
}

}  // namespace

int ResolveNativePrimaryEntryForElement(int element_id) {
    switch (element_id) {
    case 0:
        return 0x10;
    case 1:
        return 0x20;
    case 2:
        return 0x28;
    case 3:
        return 0x18;
    case 4:
        return 0x08;
    default:
        return -1;
    }
}

std::uint32_t EncodeSkillsWizardSelectionArg(int selection_value) {
    return static_cast<std::uint32_t>(selection_value);
}

bool TryResolveNativePrimaryBuildSkillId(
    int primary_entry_index,
    int combo_entry_index,
    int* skill_id) {
    if (skill_id == nullptr) {
        return false;
    }

    *skill_id = -1;
    for (const auto& pair : kNativePrimarySkillPairs) {
        if (EntriesMatch(
                primary_entry_index,
                combo_entry_index,
                pair.primary_entry_index,
                pair.combo_entry_index)) {
            *skill_id = pair.skill_id;
            return true;
        }
    }
    return false;
}

bool TryResolveNativePrimarySelectionFromPair(
    int primary_entry_index,
    int combo_entry_index,
    NativePrimarySpellSelection* selection) {
    if (selection == nullptr) {
        return false;
    }

    *selection = NativePrimarySpellSelection{};
    selection->primary_entry_index = primary_entry_index;
    selection->combo_entry_index = combo_entry_index;
    if (!TryResolveNativePrimaryBuildSkillId(
            primary_entry_index,
            combo_entry_index,
            &selection->build_skill_id)) {
        return false;
    }

    selection->pure_primary = primary_entry_index == combo_entry_index;
    selection->per_second_mana =
        EntryUsesContinuousMana(primary_entry_index) ||
        EntryUsesContinuousMana(combo_entry_index);
    return true;
}

bool TryResolveNativePrimarySelectionFromSkillId(
    int skill_id,
    NativePrimarySpellSelection* selection) {
    if (selection == nullptr) {
        return false;
    }

    *selection = NativePrimarySpellSelection{};
    for (const auto& pair : kNativePrimarySkillPairs) {
        if (pair.skill_id == skill_id) {
            return TryResolveNativePrimarySelectionFromPair(
                pair.primary_entry_index,
                pair.combo_entry_index,
                selection);
        }
    }
    return false;
}

bool TryResolveNativePrimarySelectionForProfile(
    const multiplayer::MultiplayerCharacterProfile& character_profile,
    NativePrimarySpellSelection* selection) {
    if (selection == nullptr) {
        return false;
    }

    const auto default_entry = ResolveNativePrimaryEntryForElement(character_profile.element_id);
    const auto primary_entry =
        character_profile.loadout.primary_entry_index >= 0
            ? character_profile.loadout.primary_entry_index
            : default_entry;
    const auto combo_entry =
        character_profile.loadout.primary_combo_entry_index >= 0
            ? character_profile.loadout.primary_combo_entry_index
            : primary_entry;
    return TryResolveNativePrimarySelectionFromPair(primary_entry, combo_entry, selection);
}

bool TryResolveNativePrimarySpellStats(
    uintptr_t progression_runtime_address,
    const NativePrimarySpellSelection& selection,
    NativePrimarySpellStats* stats,
    std::string* error_message) {
    if (stats == nullptr) {
        return false;
    }

    *stats = NativePrimarySpellStats{};
    stats->selection = selection;
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (progression_runtime_address == 0) {
        if (error_message != nullptr) {
            *error_message = "native spell stats require a live progression runtime";
        }
        return false;
    }
    if (selection.primary_entry_index < 0 ||
        selection.combo_entry_index < 0 ||
        selection.build_skill_id <= 0) {
        if (error_message != nullptr) {
            *error_message = "native spell stats received an unresolved primary selection";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto build_primary_spell_address =
        memory.ResolveGameAddressOrZero(kSkillsWizardBuildPrimarySpell);
    if (build_primary_spell_address == 0) {
        if (error_message != nullptr) {
            *error_message = "unable to resolve Skills_Wizard primary spell builder";
        }
        return false;
    }

    DWORD exception_code = 0;
    const bool build_succeeded = CallSkillsWizardBuildPrimarySpellSafe(
        build_primary_spell_address,
        progression_runtime_address,
        EncodeSkillsWizardSelectionArg(selection.primary_entry_index),
        EncodeSkillsWizardSelectionArg(selection.combo_entry_index),
        &exception_code);
    if (!build_succeeded) {
        stats->builder_seh_code = exception_code;
        if (error_message != nullptr) {
            *error_message =
                "Skills_Wizard primary spell builder failed with 0x" +
                std::to_string(exception_code);
        }
        return false;
    }
    stats->builder_seh_code = exception_code;

    const auto mana_output_index = selection.pure_primary ? 1u : 2u;
    uintptr_t output_values_address = 0;
    std::size_t output_count = 0;
    if (!TryReadNativePrimaryStatOutputs(
            progression_runtime_address,
            mana_output_index + 1,
            &output_values_address,
            &output_count,
            error_message)) {
        return false;
    }

    stats->output_values_address = output_values_address;
    stats->output_count = output_count;
    stats->damage = memory.ReadValueOr<float>(output_values_address, 0.0f);
    if (!selection.pure_primary && output_count > 1) {
        stats->secondary_damage = memory.ReadValueOr<float>(
            output_values_address + sizeof(float),
            0.0f);
        stats->secondary_damage_available = true;
    }
    stats->mana_cost = memory.ReadValueOr<float>(
        output_values_address + static_cast<std::size_t>(mana_output_index) * sizeof(float),
        0.0f);
    stats->mana_cost_available = true;
    stats->mana_spend_cost = stats->mana_cost;
    stats->mana_spend_cost_available = true;
    if (NativePrimaryManaOutputUsesDisplayScale(selection)) {
        float mana_output_scale = 1.0f;
        if (!TryReadNativePrimaryManaOutputScale(&mana_output_scale, error_message)) {
            return false;
        }
        stats->mana_output_scaled = true;
        stats->mana_output_scale = mana_output_scale;
        stats->mana_spend_cost = stats->mana_cost / mana_output_scale;
    }
    stats->current_spell_id =
        kProgressionCurrentSpellIdOffset != 0 &&
                memory.IsReadableRange(
                    progression_runtime_address + kProgressionCurrentSpellIdOffset,
                    sizeof(std::int32_t))
            ? memory.ReadFieldOr<std::int32_t>(
                  progression_runtime_address,
                  kProgressionCurrentSpellIdOffset,
                  selection.build_skill_id)
            : selection.build_skill_id;
    stats->progression_level =
        kProgressionLevelOffset != 0 &&
                memory.IsReadableRange(
                    progression_runtime_address + kProgressionLevelOffset,
                    sizeof(std::int32_t))
            ? memory.ReadFieldOr<std::int32_t>(
                  progression_runtime_address,
                  kProgressionLevelOffset,
                  1)
            : 1;
    stats->resolved = true;
    return true;
}

}  // namespace sdmod
