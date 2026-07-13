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
using SkillsWizardGetSecondaryManaCostFn = float(__thiscall*)(
    void* self,
    int entry_index,
    int level_override);
using StatBookComputeCostFn = float(__thiscall*)(
    void* self,
    float base_value,
    int entry_index,
    char apply_modifier);

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

bool CallSkillsWizardGetSecondaryManaCostSafe(
    uintptr_t resolver_address,
    uintptr_t progression_address,
    int entry_index,
    float* output_cost,
    DWORD* exception_code) {
    auto* resolve_secondary_mana =
        reinterpret_cast<SkillsWizardGetSecondaryManaCostFn>(resolver_address);
    if (output_cost != nullptr) {
        *output_cost = 0.0f;
    }
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (resolve_secondary_mana == nullptr ||
        progression_address == 0 ||
        entry_index < 0) {
        return false;
    }

    __try {
        const auto cost = resolve_secondary_mana(
            reinterpret_cast<void*>(progression_address),
            entry_index,
            -1);
        if (output_cost != nullptr) {
            *output_cost = cost;
        }
        return true;
    } __except (CaptureNativeSpellStatsSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallStatBookComputeCostSafe(
    uintptr_t compute_address,
    uintptr_t progression_address,
    float base_cost,
    int entry_index,
    float* output_cost,
    DWORD* exception_code) {
    auto* compute_cost = reinterpret_cast<StatBookComputeCostFn>(compute_address);
    if (output_cost != nullptr) {
        *output_cost = 0.0f;
    }
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (compute_cost == nullptr || progression_address == 0) {
        return false;
    }

    __try {
        const auto cost = compute_cost(
            reinterpret_cast<void*>(progression_address),
            base_cost,
            entry_index,
            0);
        if (output_cost != nullptr) {
            *output_cost = cost;
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
    const bool entry_pair_is_pure_projectile =
        primary_entry_index == combo_entry_index &&
        !EntryUsesContinuousMana(primary_entry_index);
    selection->pure_primary = entry_pair_is_pure_projectile;
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

    std::int32_t resolved_spell_id = 0;
    if (!memory.TryReadField(
            progression_runtime_address,
            kProgressionCurrentSpellIdOffset,
            &resolved_spell_id)) {
        return false;
    }

    if (spell_id != nullptr) {
        *spell_id = resolved_spell_id;
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

constexpr std::size_t kMinimumNativePrimaryStatOutputCount = 2;

std::size_t ResolveNativePrimaryManaOutputIndex(
    const NativePrimarySpellSelection& selection) {
    // Skills_Wizard emits the base spell's mStats fields first, followed by
    // fields contributed by active upgrades. Every stock pure primary,
    // including Ether/Magic Missile, exposes damage then mana. Mixed primaries
    // expose two damage channels before mana. Upgrade fields therefore must
    // not move the mana index merely because they grow the output array.
    return selection.primary_entry_index == selection.combo_entry_index ? 1u : 2u;
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

    uintptr_t values_address = 0;
    std::int32_t count = 0;
    if (!memory.TryReadField(
            progression_runtime_address,
            kProgressionPrimaryStatValuesOffset,
            &values_address) ||
        !memory.TryReadField(
            progression_runtime_address,
            kProgressionPrimaryStatCountOffset,
            &count)) {
        if (error_message != nullptr) {
            *error_message = "native primary spell stat output fields became unreadable";
        }
        return false;
    }
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

#include "native_spell_stats/primary_and_secondary_resolution.inl"
