#pragma once

#include "multiplayer_runtime_state.h"

#include <cstddef>
#include <cstdint>
#include <string>

namespace sdmod {

struct NativePrimarySpellSelection {
    int primary_entry_index = -1;
    int combo_entry_index = -1;
    int build_skill_id = -1;
    bool pure_primary = false;
    bool per_second_mana = false;
};

struct NativePrimarySpellStats {
    bool resolved = false;
    NativePrimarySpellSelection selection;
    int current_spell_id = -1;
    int progression_level = 1;
    std::size_t output_count = 0;
    uintptr_t output_values_address = 0;
    float damage = 0.0f;
    float secondary_damage = 0.0f;
    bool secondary_damage_available = false;
    float mana_cost = 0.0f;
    bool mana_cost_available = false;
    float mana_spend_cost = 0.0f;
    bool mana_spend_cost_available = false;
    float mana_output_scale = 1.0f;
    bool mana_output_scaled = false;
    std::uint32_t builder_seh_code = 0;
};

int ResolveNativePrimaryEntryForElement(int element_id);
std::uint32_t EncodeSkillsWizardSelectionArg(int selection_value);
bool TryResolveNativePrimaryBuildSkillId(
    int primary_entry_index,
    int combo_entry_index,
    int* skill_id);
bool TryResolveNativePrimarySelectionFromPair(
    int primary_entry_index,
    int combo_entry_index,
    NativePrimarySpellSelection* selection);
bool TryResolveNativePrimarySelectionFromSkillId(
    int skill_id,
    NativePrimarySpellSelection* selection);
bool TryResolveNativePrimarySelectionForProfile(
    const multiplayer::MultiplayerCharacterProfile& character_profile,
    NativePrimarySpellSelection* selection);
bool TryResolveNativePrimarySpellStats(
    uintptr_t progression_runtime_address,
    const NativePrimarySpellSelection& selection,
    NativePrimarySpellStats* stats,
    std::string* error_message = nullptr);

}  // namespace sdmod
