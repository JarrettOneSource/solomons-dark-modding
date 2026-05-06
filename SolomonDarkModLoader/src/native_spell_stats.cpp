#include "native_spell_stats.h"

#include "gameplay_seams.h"
#include "memory_access.h"

#include <Windows.h>

#include <algorithm>
#include <cmath>
#include <iterator>

namespace sdmod {
namespace {

using SkillsWizardBuildPrimarySpellFn = std::uint32_t(__thiscall*)(
    void* self,
    std::uint32_t primary_entry,
    std::uint32_t combo_entry,
    std::uint32_t reserved0,
    std::uint32_t reserved1,
    std::uint32_t reserved2,
    std::uint32_t reserved3);

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
    std::uint32_t* output_spell_id,
    DWORD* exception_code) {
    auto* build_primary_spell =
        reinterpret_cast<SkillsWizardBuildPrimarySpellFn>(build_address);
    if (output_spell_id != nullptr) {
        *output_spell_id = 0;
    }
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (build_primary_spell == nullptr || progression_address == 0) {
        return false;
    }

    __try {
        const auto spell_id = build_primary_spell(
            reinterpret_cast<void*>(progression_address),
            primary_entry_arg,
            combo_entry_arg,
            0,
            0,
            0,
            0);
        if (output_spell_id != nullptr) {
            *output_spell_id = spell_id;
        }
        return true;
    } __except (CaptureNativeSpellStatsSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

constexpr int kNativePrimaryEntryIndices[] = {
    0x08,
    0x10,
    0x18,
    0x20,
    0x28,
};

bool IsNativePrimaryEntryIndex(int entry_index) {
    return std::find(
               std::begin(kNativePrimaryEntryIndices),
               std::end(kNativePrimaryEntryIndices),
               entry_index) != std::end(kNativePrimaryEntryIndices);
}

bool EntryUsesContinuousMana(int entry_index) {
    return entry_index == 0x18 || entry_index == 0x20 || entry_index == 0x28;
}

bool FillNativePrimarySelection(
    int primary_entry_index,
    int combo_entry_index,
    int build_skill_id,
    NativePrimarySpellSelection* selection) {
    if (selection == nullptr ||
        !IsNativePrimaryEntryIndex(primary_entry_index) ||
        !IsNativePrimaryEntryIndex(combo_entry_index) ||
        build_skill_id == 0) {
        return false;
    }

    *selection = NativePrimarySpellSelection{};
    selection->primary_entry_index = primary_entry_index;
    selection->combo_entry_index = combo_entry_index;
    selection->build_skill_id = build_skill_id;
    selection->pure_primary = primary_entry_index == combo_entry_index;
    selection->per_second_mana =
        EntryUsesContinuousMana(primary_entry_index) ||
        EntryUsesContinuousMana(combo_entry_index);
    return true;
}

bool TryReadProgressionCurrentSpellId(
    uintptr_t progression_runtime_address,
    std::int32_t* spell_id) {
    if (spell_id != nullptr) {
        *spell_id = 0;
    }
    if (progression_runtime_address == 0 ||
        kProgressionCurrentSpellIdOffset == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (!memory.IsReadableRange(
            progression_runtime_address + kProgressionCurrentSpellIdOffset,
            sizeof(std::int32_t))) {
        return false;
    }

    if (spell_id != nullptr) {
        *spell_id =
            memory.ReadFieldOr<std::int32_t>(
                progression_runtime_address,
                kProgressionCurrentSpellIdOffset,
                0);
    }
    return true;
}

void RestoreProgressionCurrentSpellIdIfNeeded(
    uintptr_t progression_runtime_address,
    bool have_previous_spell_id,
    std::int32_t previous_spell_id) {
    if (!have_previous_spell_id ||
        progression_runtime_address == 0 ||
        kProgressionCurrentSpellIdOffset == 0) {
        return;
    }

    (void)ProcessMemory::Instance().TryWriteField<std::int32_t>(
        progression_runtime_address,
        kProgressionCurrentSpellIdOffset,
        previous_spell_id);
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

    double scale = 0.0;
    if (!memory.TryReadValue(scale_address, &scale)) {
        if (error_message != nullptr) {
            *error_message = "native primary mana output scale read failed";
        }
        return false;
    }
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

bool TryResolveNativePrimaryEntryForElement(int element_id, int* primary_entry) {
    if (primary_entry == nullptr) {
        return false;
    }

    *primary_entry = -1;
    switch (element_id) {
    case 0:
        *primary_entry = 0x10;
        return true;
    case 1:
        *primary_entry = 0x20;
        return true;
    case 2:
        *primary_entry = 0x28;
        return true;
    case 3:
        *primary_entry = 0x18;
        return true;
    case 4:
        *primary_entry = 0x08;
        return true;
    default:
        return false;
    }
}

int ResolveNativePrimaryEntryForElement(int element_id) {
    int primary_entry = -1;
    return TryResolveNativePrimaryEntryForElement(element_id, &primary_entry)
        ? primary_entry
        : -1;
}

std::uint32_t EncodeSkillsWizardSelectionArg(int selection_value) {
    return static_cast<std::uint32_t>(selection_value);
}

bool TryResolveNativePrimarySelectionFromPair(
    int primary_entry_index,
    int combo_entry_index,
    NativePrimarySpellSelection* selection) {
    if (selection == nullptr) {
        return false;
    }

    return FillNativePrimarySelection(
        primary_entry_index,
        combo_entry_index,
        -1,
        selection);
}

bool TryResolveNativePrimarySelectionFromSkillId(
    uintptr_t progression_runtime_address,
    int skill_id,
    NativePrimarySpellSelection* selection,
    std::string* error_message) {
    if (selection != nullptr) {
        *selection = NativePrimarySpellSelection{};
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (selection == nullptr || skill_id <= 0) {
        if (error_message != nullptr) {
            *error_message = "native primary skill-id resolution requires a positive skill id";
        }
        return false;
    }
    if (progression_runtime_address == 0) {
        if (error_message != nullptr) {
            *error_message = "native primary skill-id resolution requires a live progression runtime";
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

    std::int32_t previous_current_spell_id = 0;
    const bool have_previous_current_spell_id =
        TryReadProgressionCurrentSpellId(
            progression_runtime_address,
            &previous_current_spell_id);

    DWORD last_exception_code = 0;
    for (std::size_t primary_index = 0;
         primary_index < std::size(kNativePrimaryEntryIndices);
         ++primary_index) {
        for (std::size_t combo_index = primary_index;
             combo_index < std::size(kNativePrimaryEntryIndices);
             ++combo_index) {
            const auto primary_entry = kNativePrimaryEntryIndices[primary_index];
            const auto combo_entry = kNativePrimaryEntryIndices[combo_index];
            std::uint32_t native_spell_id = 0;
            DWORD exception_code = 0;
            if (!CallSkillsWizardBuildPrimarySpellSafe(
                    build_primary_spell_address,
                    progression_runtime_address,
                    EncodeSkillsWizardSelectionArg(primary_entry),
                    EncodeSkillsWizardSelectionArg(combo_entry),
                    &native_spell_id,
                    &exception_code)) {
                last_exception_code = exception_code;
                continue;
            }

            if (native_spell_id == 0) {
                std::int32_t current_spell_id = 0;
                if (TryReadProgressionCurrentSpellId(
                        progression_runtime_address,
                        &current_spell_id)) {
                    native_spell_id = static_cast<std::uint32_t>(current_spell_id);
                }
            }
            if (native_spell_id == static_cast<std::uint32_t>(skill_id) &&
                FillNativePrimarySelection(
                    primary_entry,
                    combo_entry,
                    skill_id,
                    selection)) {
                RestoreProgressionCurrentSpellIdIfNeeded(
                    progression_runtime_address,
                    have_previous_current_spell_id,
                    previous_current_spell_id);
                return true;
            }
        }
    }

    RestoreProgressionCurrentSpellIdIfNeeded(
        progression_runtime_address,
        have_previous_current_spell_id,
        previous_current_spell_id);
    if (error_message != nullptr) {
        *error_message =
            last_exception_code == 0
                ? "Skills_Wizard did not resolve the requested primary skill id"
                : "Skills_Wizard primary skill-id scan failed with 0x" +
                    std::to_string(last_exception_code);
    }
    return false;
}

bool TryResolveNativePrimarySelectionFromLiveProgression(
    uintptr_t progression_runtime_address,
    int primary_entry_index,
    int combo_entry_index,
    NativePrimarySpellSelection* selection,
    std::string* error_message) {
    if (selection != nullptr) {
        *selection = NativePrimarySpellSelection{};
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (selection == nullptr ||
        !IsNativePrimaryEntryIndex(primary_entry_index) ||
        !IsNativePrimaryEntryIndex(combo_entry_index)) {
        if (error_message != nullptr) {
            *error_message = "native primary selection requires valid primary/combo entries";
        }
        return false;
    }
    if (progression_runtime_address == 0) {
        if (error_message != nullptr) {
            *error_message = "native primary selection requires a live progression runtime";
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

    std::int32_t previous_current_spell_id = 0;
    const bool have_previous_current_spell_id =
        TryReadProgressionCurrentSpellId(
            progression_runtime_address,
            &previous_current_spell_id);

    std::uint32_t native_spell_id = 0;
    DWORD exception_code = 0;
    if (!CallSkillsWizardBuildPrimarySpellSafe(
            build_primary_spell_address,
            progression_runtime_address,
            EncodeSkillsWizardSelectionArg(primary_entry_index),
            EncodeSkillsWizardSelectionArg(combo_entry_index),
            &native_spell_id,
            &exception_code)) {
        RestoreProgressionCurrentSpellIdIfNeeded(
            progression_runtime_address,
            have_previous_current_spell_id,
            previous_current_spell_id);
        if (error_message != nullptr) {
            *error_message =
                "Skills_Wizard primary selection failed with 0x" +
                std::to_string(exception_code);
        }
        return false;
    }
    if (native_spell_id == 0 &&
        kProgressionCurrentSpellIdOffset != 0 &&
        memory.IsReadableRange(
            progression_runtime_address + kProgressionCurrentSpellIdOffset,
            sizeof(std::int32_t))) {
        native_spell_id =
            static_cast<std::uint32_t>(
                memory.ReadFieldOr<std::int32_t>(
                    progression_runtime_address,
                    kProgressionCurrentSpellIdOffset,
                    0));
    }
    RestoreProgressionCurrentSpellIdIfNeeded(
        progression_runtime_address,
        have_previous_current_spell_id,
        previous_current_spell_id);

    if (native_spell_id == 0 ||
        !FillNativePrimarySelection(
            primary_entry_index,
            combo_entry_index,
            static_cast<int>(native_spell_id),
            selection)) {
        if (error_message != nullptr) {
            *error_message = "Skills_Wizard primary selection did not produce a spell id";
        }
        return false;
    }
    return true;
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
    if (!IsNativePrimaryEntryIndex(selection.primary_entry_index) ||
        !IsNativePrimaryEntryIndex(selection.combo_entry_index)) {
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

    std::uint32_t native_spell_id = 0;
    DWORD exception_code = 0;
    const bool build_succeeded = CallSkillsWizardBuildPrimarySpellSafe(
        build_primary_spell_address,
        progression_runtime_address,
        EncodeSkillsWizardSelectionArg(selection.primary_entry_index),
        EncodeSkillsWizardSelectionArg(selection.combo_entry_index),
        &native_spell_id,
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
    if (native_spell_id > 0) {
        stats->selection.build_skill_id = static_cast<int>(native_spell_id);
    }

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
    if (!memory.TryReadValue(output_values_address, &stats->damage)) {
        if (error_message != nullptr) {
            *error_message = "native primary damage output read failed";
        }
        return false;
    }
    if (!selection.pure_primary && output_count > 1) {
        if (!memory.TryReadValue(output_values_address + sizeof(float), &stats->secondary_damage)) {
            if (error_message != nullptr) {
                *error_message = "native primary secondary damage output read failed";
            }
            return false;
        }
        stats->secondary_damage_available = true;
    }
    if (!memory.TryReadValue(
            output_values_address + static_cast<std::size_t>(mana_output_index) * sizeof(float),
            &stats->mana_cost)) {
        if (error_message != nullptr) {
            *error_message = "native primary mana output read failed";
        }
        return false;
    }
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
                  stats->selection.build_skill_id)
            : stats->selection.build_skill_id;
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
