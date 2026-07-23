#include "lua_engine_bindings_internal.h"
#include "lua_engine_parsers_internal.h"

#include "lua_engine.h"

#include "multiplayer_local_transport.h"
#include "multiplayer_runtime_state.h"

#include <algorithm>
#include <array>
#include <cctype>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <string>
#include <string_view>

namespace sdmod::detail {
namespace {

template <std::size_t Size>
void PushByteArray(lua_State* state, const std::array<std::uint8_t, Size>& bytes) {
    lua_createtable(state, static_cast<int>(bytes.size()), 0);
    for (std::size_t index = 0; index < bytes.size(); ++index) {
        lua_pushinteger(state, static_cast<lua_Integer>(bytes[index]));
        lua_rawseti(state, -2, static_cast<lua_Integer>(index + 1));
    }
}

void PushEquippedItemIdentity(
    lua_State* state,
    const multiplayer::ParticipantEquippedItemState& item) {
    lua_createtable(state, 0, 2);
    lua_pushinteger(state, static_cast<lua_Integer>(item.type_id));
    lua_setfield(state, -2, "type_id");
    lua_pushinteger(state, static_cast<lua_Integer>(item.recipe_uid));
    lua_setfield(state, -2, "recipe_uid");
}

void PushEquipmentIdentityState(
    lua_State* state,
    const multiplayer::ParticipantEquipmentState& equipment) {
    lua_createtable(state, 0, 6);
    lua_pushboolean(state, equipment.valid ? 1 : 0);
    lua_setfield(state, -2, "valid");
    PushEquippedItemIdentity(state, equipment.hat);
    lua_setfield(state, -2, "hat");
    PushEquippedItemIdentity(state, equipment.robe);
    lua_setfield(state, -2, "robe");
    PushEquippedItemIdentity(state, equipment.weapon);
    lua_setfield(state, -2, "weapon");
    lua_createtable(state, static_cast<int>(equipment.rings.size()), 0);
    for (std::size_t index = 0; index < equipment.rings.size(); ++index) {
        PushEquippedItemIdentity(state, equipment.rings[index]);
        lua_rawseti(state, -2, static_cast<lua_Integer>(index + 1));
    }
    lua_setfield(state, -2, "rings");
    PushEquippedItemIdentity(state, equipment.amulet);
    lua_setfield(state, -2, "amulet");
}

void PushParticipantEquipmentState(
    lua_State* state,
    const multiplayer::ParticipantRuntimeInfo& runtime,
    const multiplayer::ParticipantOwnedProgressionState& owned_progression) {
    lua_createtable(state, 0, 11);
    lua_pushboolean(
        state,
        owned_progression.equipment.valid ||
            (runtime.presentation_flags &
             multiplayer::ParticipantPresentationFlagEquipmentState) != 0);
    lua_setfield(state, -2, "valid");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(owned_progression.equipment_revision));
    lua_setfield(state, -2, "revision");

    const auto push_wearable = [&](std::uint32_t type_id,
                                   std::uint32_t recipe_uid,
                                   const auto& color_state) {
        lua_createtable(state, 0, 3);
        lua_pushinteger(state, static_cast<lua_Integer>(type_id));
        lua_setfield(state, -2, "type_id");
        lua_pushinteger(state, static_cast<lua_Integer>(recipe_uid));
        lua_setfield(state, -2, "recipe_uid");
        PushByteArray(state, color_state);
        lua_setfield(state, -2, "color_state");
    };
    push_wearable(
        runtime.primary_visual_link_type_id,
        runtime.primary_visual_link_recipe_uid,
        runtime.primary_visual_link_color_block);
    lua_setfield(state, -2, "primary");
    push_wearable(
        runtime.secondary_visual_link_type_id,
        runtime.secondary_visual_link_recipe_uid,
        runtime.secondary_visual_link_color_block);
    lua_setfield(state, -2, "secondary");

    lua_createtable(state, 0, 2);
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(runtime.attachment_visual_link_type_id));
    lua_setfield(state, -2, "type_id");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(runtime.attachment_visual_link_recipe_uid));
    lua_setfield(state, -2, "recipe_uid");
    lua_setfield(state, -2, "attachment");
    PushEquippedItemIdentity(state, owned_progression.equipment.hat);
    lua_setfield(state, -2, "hat");
    PushEquippedItemIdentity(state, owned_progression.equipment.robe);
    lua_setfield(state, -2, "robe");
    PushEquippedItemIdentity(state, owned_progression.equipment.weapon);
    lua_setfield(state, -2, "weapon");
    lua_createtable(
        state,
        static_cast<int>(owned_progression.equipment.rings.size()),
        0);
    for (std::size_t index = 0;
         index < owned_progression.equipment.rings.size();
         ++index) {
        PushEquippedItemIdentity(state, owned_progression.equipment.rings[index]);
        lua_rawseti(state, -2, static_cast<lua_Integer>(index + 1));
    }
    lua_setfield(state, -2, "rings");
    PushEquippedItemIdentity(state, owned_progression.equipment.amulet);
    lua_setfield(state, -2, "amulet");
}

void PushOwnedProgressionBookEntry(
    lua_State* state,
    const multiplayer::ParticipantProgressionBookEntryState& entry) {
    lua_createtable(state, 0, 6);
    lua_pushinteger(state, static_cast<lua_Integer>(entry.entry_index));
    lua_setfield(state, -2, "entry_index");
    lua_pushinteger(state, static_cast<lua_Integer>(entry.internal_id));
    lua_setfield(state, -2, "internal_id");
    lua_pushinteger(state, static_cast<lua_Integer>(entry.active));
    lua_setfield(state, -2, "active");
    lua_pushinteger(state, static_cast<lua_Integer>(entry.visible));
    lua_setfield(state, -2, "visible");
    lua_pushinteger(state, static_cast<lua_Integer>(entry.category));
    lua_setfield(state, -2, "category");
    lua_pushinteger(state, static_cast<lua_Integer>(entry.statbook_max_level));
    lua_setfield(state, -2, "statbook_max_level");
}

void PushOwnedProgressionBookEntries(
    lua_State* state,
    const std::vector<multiplayer::ParticipantProgressionBookEntryState>& entries) {
    lua_createtable(state, static_cast<int>(entries.size()), 0);
    int lua_index = 1;
    for (const auto& entry : entries) {
        PushOwnedProgressionBookEntry(state, entry);
        lua_rawseti(state, -2, static_cast<lua_Integer>(lua_index));
        ++lua_index;
    }
}

int LuaRuntimeGetMod(lua_State* state) {
    const auto* mod = GetLoadedLuaMod(state);
    if (mod == nullptr) {
        lua_pushnil(state);
        return 1;
    }

    lua_createtable(state, 0, 11);
    lua_pushstring(state, mod->descriptor.id.c_str());
    lua_setfield(state, -2, "id");
    lua_pushstring(state, mod->descriptor.name.c_str());
    lua_setfield(state, -2, "name");
    lua_pushstring(state, mod->descriptor.version.c_str());
    lua_setfield(state, -2, "version");
    lua_pushstring(state, mod->descriptor.api_version.c_str());
    lua_setfield(state, -2, "api_version");
    lua_pushstring(state, mod->descriptor.runtime_kind.c_str());
    lua_setfield(state, -2, "runtime_kind");
    lua_pushstring(state, mod->descriptor.storage_key.c_str());
    lua_setfield(state, -2, "storage_key");
    lua_pushstring(state, mod->descriptor.root_path.string().c_str());
    lua_setfield(state, -2, "root_path");
    lua_pushstring(state, mod->descriptor.entry_script_path.string().c_str());
    lua_setfield(state, -2, "entry_script_path");
    lua_pushboolean(state, mod->descriptor.hot_reload ? 1 : 0);
    lua_setfield(state, -2, "hot_reload");
    lua_pushstring(state, mod->descriptor.data_root_path.string().c_str());
    lua_setfield(state, -2, "data_root_path");
    lua_pushstring(state, mod->descriptor.temp_root_path.string().c_str());
    lua_setfield(state, -2, "temp_root_path");
    return 1;
}

void PushOwnedProgressionState(
    lua_State* state,
    const multiplayer::ParticipantOwnedProgressionState& progression) {
    lua_createtable(state, 0, 34);
    lua_pushboolean(state, progression.initialized ? 1 : 0);
    lua_setfield(state, -2, "initialized");
    lua_pushinteger(state, static_cast<lua_Integer>(progression.gold));
    lua_setfield(state, -2, "gold");
    lua_pushinteger(state, static_cast<lua_Integer>(progression.gold_revision));
    lua_setfield(state, -2, "gold_revision");
    lua_pushinteger(state, static_cast<lua_Integer>(progression.inventory_revision));
    lua_setfield(state, -2, "inventory_revision");
    lua_pushinteger(state, static_cast<lua_Integer>(progression.equipment_revision));
    lua_setfield(state, -2, "equipment_revision");
    lua_pushinteger(state, static_cast<lua_Integer>(progression.spellbook_revision));
    lua_setfield(state, -2, "spellbook_revision");
    lua_pushinteger(state, static_cast<lua_Integer>(progression.statbook_revision));
    lua_setfield(state, -2, "statbook_revision");
    lua_pushinteger(state, static_cast<lua_Integer>(progression.loadout_revision));
    lua_setfield(state, -2, "loadout_revision");
    lua_pushinteger(state, static_cast<lua_Integer>(progression.concentration_revision));
    lua_setfield(state, -2, "concentration_revision");
    lua_pushboolean(state, progression.concentration_selection_valid ? 1 : 0);
    lua_setfield(state, -2, "concentration_selection_valid");
    lua_pushinteger(state, static_cast<lua_Integer>(progression.concentration_entry_a));
    lua_setfield(state, -2, "concentration_entry_a");
    lua_pushinteger(state, static_cast<lua_Integer>(progression.concentration_entry_b));
    lua_setfield(state, -2, "concentration_entry_b");
    lua_pushinteger(state, static_cast<lua_Integer>(progression.derived_stat_revision));
    lua_setfield(state, -2, "derived_stat_revision");
    if (progression.derived_stats.valid) {
        const auto& derived = progression.derived_stats;
        lua_createtable(state, 0, 15);
        lua_pushnumber(state, static_cast<lua_Number>(derived.cast_speed_multiplier));
        lua_setfield(state, -2, "cast_speed_multiplier");
        lua_pushnumber(state, static_cast<lua_Number>(derived.mana_recovery_multiplier));
        lua_setfield(state, -2, "mana_recovery_multiplier");
        lua_pushnumber(state, static_cast<lua_Number>(derived.resist_magic_fraction));
        lua_setfield(state, -2, "resist_magic_fraction");
        lua_pushnumber(state, static_cast<lua_Number>(derived.resist_poison_fraction));
        lua_setfield(state, -2, "resist_poison_fraction");
        lua_pushnumber(state, static_cast<lua_Number>(derived.deflect_chance));
        lua_setfield(state, -2, "deflect_chance");
        lua_pushnumber(state, static_cast<lua_Number>(derived.staff_melee_damage_a));
        lua_setfield(state, -2, "staff_melee_damage_a");
        lua_pushnumber(state, static_cast<lua_Number>(derived.staff_melee_damage_b));
        lua_setfield(state, -2, "staff_melee_damage_b");
        lua_pushnumber(state, static_cast<lua_Number>(derived.pickup_range));
        lua_setfield(state, -2, "pickup_range");
        lua_pushnumber(state, static_cast<lua_Number>(derived.secondary_recharge_multiplier));
        lua_setfield(state, -2, "secondary_recharge_multiplier");
        lua_pushnumber(state, static_cast<lua_Number>(derived.offensive_damage_multiplier));
        lua_setfield(state, -2, "offensive_damage_multiplier");
        lua_pushnumber(state, static_cast<lua_Number>(derived.offensive_mana_multiplier));
        lua_setfield(state, -2, "offensive_mana_multiplier");
        lua_pushnumber(state, static_cast<lua_Number>(derived.melee_damage_multiplier));
        lua_setfield(state, -2, "melee_damage_multiplier");
        lua_pushnumber(state, static_cast<lua_Number>(derived.push_strength));
        lua_setfield(state, -2, "push_strength");
        lua_pushnumber(state, static_cast<lua_Number>(derived.meditation_recovery_bonus));
        lua_setfield(state, -2, "meditation_recovery_bonus");
        lua_pushinteger(state, static_cast<lua_Integer>(derived.meditation_idle_ticks));
        lua_setfield(state, -2, "meditation_idle_ticks");
        lua_setfield(state, -2, "derived_stats");
    }
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(progression.hagatha_perk_revision));
    lua_setfield(state, -2, "hagatha_perk_revision");
    if (progression.hagatha_perks.valid) {
        const auto& perks = progression.hagatha_perks;
        lua_createtable(state, 0, 7);
        lua_pushinteger(state, static_cast<lua_Integer>(perks.perk_count));
        lua_setfield(state, -2, "perk_count");
        lua_pushinteger(state, static_cast<lua_Integer>(perks.perk_capacity));
        lua_setfield(state, -2, "perk_capacity");
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(perks.cheat_death_charges));
        lua_setfield(state, -2, "cheat_death_charges");
        lua_pushboolean(state, perks.serendipity_active ? 1 : 0);
        lua_setfield(state, -2, "serendipity_active");
        lua_pushboolean(state, perks.reverie_active ? 1 : 0);
        lua_setfield(state, -2, "reverie_active");
        lua_createtable(state, static_cast<int>(perks.perk_count), 0);
        for (std::size_t index = 0; index < perks.perk_count; ++index) {
            lua_pushinteger(
                state,
                static_cast<lua_Integer>(perks.perk_selectors[index]));
            lua_rawseti(
                state,
                -2,
                static_cast<lua_Integer>(index + 1));
        }
        lua_setfield(state, -2, "selectors");
        lua_pushboolean(state, 1);
        lua_setfield(state, -2, "valid");
        lua_setfield(state, -2, "hagatha_perks");
    }
    lua_pushboolean(state, progression.inventory_host_authoritative ? 1 : 0);
    lua_setfield(state, -2, "inventory_host_authoritative");
    lua_pushinteger(state, static_cast<lua_Integer>(progression.inventory_item_total_count));
    lua_setfield(state, -2, "inventory_item_total_count");
    lua_pushinteger(state, static_cast<lua_Integer>(progression.inventory_items.size()));
    lua_setfield(state, -2, "inventory_item_count");
    lua_pushboolean(state, progression.inventory_truncated ? 1 : 0);
    lua_setfield(state, -2, "inventory_truncated");

    lua_createtable(state, static_cast<int>(progression.inventory_items.size()), 0);
    int lua_index = 1;
    for (const auto& item : progression.inventory_items) {
        lua_createtable(state, 0, 6);
        lua_pushinteger(state, static_cast<lua_Integer>(item.type_id));
        lua_setfield(state, -2, "type_id");
        lua_pushinteger(state, static_cast<lua_Integer>(item.recipe_uid));
        lua_setfield(state, -2, "recipe_uid");
        lua_pushinteger(state, static_cast<lua_Integer>(item.slot));
        lua_setfield(state, -2, "slot");
        lua_pushinteger(state, static_cast<lua_Integer>(item.stack_count));
        lua_setfield(state, -2, "stack_count");
        lua_pushinteger(state, static_cast<lua_Integer>(item.parent_item_index));
        lua_setfield(state, -2, "parent_item_index");
        lua_pushinteger(state, static_cast<lua_Integer>(item.container_depth));
        lua_setfield(state, -2, "container_depth");
        lua_rawseti(state, -2, static_cast<lua_Integer>(lua_index));
        ++lua_index;
    }
    lua_setfield(state, -2, "inventory_items");
    PushEquipmentIdentityState(state, progression.equipment);
    lua_setfield(state, -2, "equipment");

    lua_pushinteger(state, static_cast<lua_Integer>(progression.progression_book_entry_total_count));
    lua_setfield(state, -2, "progression_book_entry_total_count");
    lua_pushinteger(state, static_cast<lua_Integer>(progression.progression_book_entries.size()));
    lua_setfield(state, -2, "progression_book_entry_count");
    lua_pushboolean(state, progression.progression_book_truncated ? 1 : 0);
    lua_setfield(state, -2, "progression_book_truncated");
    PushOwnedProgressionBookEntries(state, progression.progression_book_entries);
    lua_setfield(state, -2, "progression_book_entries");
    lua_pushinteger(state, static_cast<lua_Integer>(progression.progression_book_entries.size()));
    lua_setfield(state, -2, "statbook_entry_count");
    PushOwnedProgressionBookEntries(state, progression.progression_book_entries);
    lua_setfield(state, -2, "statbook_entries");
    lua_pushinteger(state, static_cast<lua_Integer>(progression.progression_book_entry_total_count));
    lua_setfield(state, -2, "skillbook_entry_total_count");
    lua_pushinteger(state, static_cast<lua_Integer>(progression.progression_book_entries.size()));
    lua_setfield(state, -2, "skillbook_entry_count");
    lua_pushboolean(state, progression.progression_book_truncated ? 1 : 0);
    lua_setfield(state, -2, "skillbook_truncated");
    PushOwnedProgressionBookEntries(state, progression.progression_book_entries);
    lua_setfield(state, -2, "skillbook_entries");
    lua_pushinteger(state, static_cast<lua_Integer>(progression.progression_book_entry_total_count));
    lua_setfield(state, -2, "spellbook_entry_total_count");
    lua_pushinteger(state, static_cast<lua_Integer>(progression.progression_book_entries.size()));
    lua_setfield(state, -2, "spellbook_entry_count");
    lua_pushboolean(state, progression.progression_book_truncated ? 1 : 0);
    lua_setfield(state, -2, "spellbook_truncated");
    PushOwnedProgressionBookEntries(state, progression.progression_book_entries);
    lua_setfield(state, -2, "spellbook_entries");

    if (progression.ability_loadout_valid) {
        parsers::PushLoadout(state, progression.ability_loadout);
        lua_setfield(state, -2, "ability_loadout");
    }
}

void PushLevelUpOptionState(
    lua_State* state,
    const multiplayer::LevelUpChoiceOptionState& option) {
    lua_createtable(state, 0, 3);
    lua_pushinteger(state, static_cast<lua_Integer>(option.option_id));
    lua_setfield(state, -2, "id");
    lua_pushinteger(state, static_cast<lua_Integer>(option.option_id));
    lua_setfield(state, -2, "option_id");
    lua_pushinteger(state, static_cast<lua_Integer>(option.apply_count));
    lua_setfield(state, -2, "apply_count");
}

void PushLevelUpOfferRuntimeInfo(
    lua_State* state,
    const multiplayer::LevelUpOfferRuntimeInfo& offer) {
    lua_createtable(state, 0, 17);
    lua_pushboolean(state, offer.valid ? 1 : 0);
    lua_setfield(state, -2, "valid");
    lua_pushboolean(state, offer.selection_submitted ? 1 : 0);
    lua_setfield(state, -2, "selection_submitted");
    lua_pushboolean(state, offer.native_picker_presented ? 1 : 0);
    lua_setfield(state, -2, "native_picker_presented");
    lua_pushboolean(state, offer.native_picker_options_pinned ? 1 : 0);
    lua_setfield(state, -2, "native_picker_options_pinned");
    lua_pushboolean(state, offer.native_picker_local_apply_observed ? 1 : 0);
    lua_setfield(state, -2, "native_picker_local_apply_observed");
    lua_pushboolean(state, offer.suppress_native_picker ? 1 : 0);
    lua_setfield(state, -2, "suppress_native_picker");
    lua_pushinteger(state, static_cast<lua_Integer>(offer.authority_participant_id));
    lua_setfield(state, -2, "authority_participant_id");
    lua_pushinteger(state, static_cast<lua_Integer>(offer.target_participant_id));
    lua_setfield(state, -2, "target_participant_id");
    lua_pushinteger(state, static_cast<lua_Integer>(offer.offer_id));
    lua_setfield(state, -2, "offer_id");
    lua_pushinteger(state, static_cast<lua_Integer>(offer.run_nonce));
    lua_setfield(state, -2, "run_nonce");
    lua_pushinteger(state, static_cast<lua_Integer>(offer.received_ms));
    lua_setfield(state, -2, "received_ms");
    lua_pushinteger(state, static_cast<lua_Integer>(offer.level));
    lua_setfield(state, -2, "level");
    lua_pushinteger(state, static_cast<lua_Integer>(offer.experience));
    lua_setfield(state, -2, "experience");
    lua_pushinteger(state, static_cast<lua_Integer>(offer.selected_option_index));
    lua_setfield(state, -2, "selected_option_index");
    lua_pushinteger(state, static_cast<lua_Integer>(offer.selected_option_id));
    lua_setfield(state, -2, "selected_option_id");
    lua_pushinteger(state, static_cast<lua_Integer>(offer.options.size()));
    lua_setfield(state, -2, "option_count");

    lua_createtable(state, static_cast<int>(offer.options.size()), 0);
    for (std::size_t index = 0; index < offer.options.size(); ++index) {
        PushLevelUpOptionState(state, offer.options[index]);
        lua_rawseti(state, -2, static_cast<lua_Integer>(index + 1));
    }
    lua_setfield(state, -2, "options");
}

void PushLevelUpChoiceResultRuntimeInfo(
    lua_State* state,
    const multiplayer::LevelUpChoiceResultRuntimeInfo& result) {
    lua_createtable(state, 0, 15);
    lua_pushboolean(state, result.valid ? 1 : 0);
    lua_setfield(state, -2, "valid");
    lua_pushinteger(state, static_cast<lua_Integer>(result.authority_participant_id));
    lua_setfield(state, -2, "authority_participant_id");
    lua_pushinteger(state, static_cast<lua_Integer>(result.target_participant_id));
    lua_setfield(state, -2, "target_participant_id");
    lua_pushinteger(state, static_cast<lua_Integer>(result.offer_id));
    lua_setfield(state, -2, "offer_id");
    lua_pushinteger(state, static_cast<lua_Integer>(result.run_nonce));
    lua_setfield(state, -2, "run_nonce");
    lua_pushinteger(state, static_cast<lua_Integer>(result.received_ms));
    lua_setfield(state, -2, "received_ms");
    lua_pushinteger(state, static_cast<lua_Integer>(result.level));
    lua_setfield(state, -2, "level");
    lua_pushinteger(state, static_cast<lua_Integer>(result.experience));
    lua_setfield(state, -2, "experience");
    lua_pushinteger(state, static_cast<lua_Integer>(result.option_index));
    lua_setfield(state, -2, "option_index");
    lua_pushinteger(state, static_cast<lua_Integer>(result.option_id));
    lua_setfield(state, -2, "option_id");
    lua_pushinteger(state, static_cast<lua_Integer>(result.apply_count));
    lua_setfield(state, -2, "apply_count");
    lua_pushinteger(state, static_cast<lua_Integer>(result.resulting_active));
    lua_setfield(state, -2, "resulting_active");
    lua_pushboolean(state, result.auto_picked ? 1 : 0);
    lua_setfield(state, -2, "auto_picked");
    lua_pushinteger(state, static_cast<lua_Integer>(result.result_code));
    lua_setfield(state, -2, "result_code");
}

void PushLevelUpWaitStatusRuntimeInfo(
    lua_State* state,
    const multiplayer::LevelUpWaitStatusRuntimeInfo& status) {
    lua_createtable(state, 0, 13);
    lua_pushboolean(state, status.valid ? 1 : 0);
    lua_setfield(state, -2, "valid");
    lua_pushboolean(state, status.pause_active ? 1 : 0);
    lua_setfield(state, -2, "pause_active");
    lua_pushboolean(state, status.timed_out ? 1 : 0);
    lua_setfield(state, -2, "timed_out");
    lua_pushinteger(state, static_cast<lua_Integer>(status.authority_participant_id));
    lua_setfield(state, -2, "authority_participant_id");
    lua_pushinteger(state, static_cast<lua_Integer>(status.barrier_id));
    lua_setfield(state, -2, "barrier_id");
    lua_pushinteger(state, static_cast<lua_Integer>(status.revision));
    lua_setfield(state, -2, "revision");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(status.deadline_remaining_ms));
    lua_setfield(state, -2, "deadline_remaining_ms");
    lua_pushinteger(state, static_cast<lua_Integer>(status.received_ms));
    lua_setfield(state, -2, "received_ms");
    lua_pushinteger(state, static_cast<lua_Integer>(status.waiting_participant_ids.size()));
    lua_setfield(state, -2, "waiting_count");

    std::string display_text;
    (void)multiplayer::TryBuildLevelUpWaitStatusText(&display_text);
    lua_pushlstring(state, display_text.data(), display_text.size());
    lua_setfield(state, -2, "display_text");

    lua_createtable(state, static_cast<int>(status.waiting_participant_ids.size()), 0);
    for (std::size_t index = 0; index < status.waiting_participant_ids.size(); ++index) {
        lua_pushinteger(state, static_cast<lua_Integer>(status.waiting_participant_ids[index]));
        lua_rawseti(state, -2, static_cast<lua_Integer>(index + 1));
    }
    lua_setfield(state, -2, "waiting_participant_ids");
}

void PushSharedGameplayPauseRuntimeInfo(
    lua_State* state,
    const multiplayer::SharedGameplayPauseRuntimeInfo& pause) {
    lua_createtable(state, 0, 10);
    lua_pushboolean(state, pause.valid ? 1 : 0);
    lua_setfield(state, -2, "valid");
    lua_pushboolean(state, pause.pause_active ? 1 : 0);
    lua_setfield(state, -2, "pause_active");
    lua_pushboolean(state, pause.timed_out ? 1 : 0);
    lua_setfield(state, -2, "timed_out");
    lua_pushboolean(state, pause.local_request_active ? 1 : 0);
    lua_setfield(state, -2, "local_request_active");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(pause.local_request_epoch));
    lua_setfield(state, -2, "local_request_epoch");
    lua_pushinteger(state, static_cast<lua_Integer>(pause.run_nonce));
    lua_setfield(state, -2, "run_nonce");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(pause.deadline_remaining_ms));
    lua_setfield(state, -2, "deadline_remaining_ms");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(pause.authority_participant_id));
    lua_setfield(state, -2, "authority_participant_id");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(pause.origin_participant_id));
    lua_setfield(state, -2, "origin_participant_id");
    lua_pushinteger(state, static_cast<lua_Integer>(pause.received_ms));
    lua_setfield(state, -2, "received_ms");
}

void PushDeathSpectatorRuntimeInfo(
    lua_State* state,
    const multiplayer::DeathSpectatorRuntimeInfo& spectator) {
    lua_createtable(state, 0, 14);
    lua_pushboolean(state, spectator.active ? 1 : 0);
    lua_setfield(state, -2, "active");
    lua_pushstring(
        state,
        multiplayer::DeathSpectatorPhaseLabel(spectator.phase));
    lua_setfield(state, -2, "phase");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(spectator.death_started_ms));
    lua_setfield(state, -2, "death_started_ms");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(
            spectator.presentation_remaining_ms));
    lua_setfield(state, -2, "presentation_remaining_ms");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(
            spectator.target_participant_id));
    lua_setfield(state, -2, "target_participant_id");
    lua_pushlstring(
        state,
        spectator.target_name.data(),
        spectator.target_name.size());
    lua_setfield(state, -2, "target_name");
    lua_pushboolean(
        state,
        spectator.waiting_for_alive_target ? 1 : 0);
    lua_setfield(state, -2, "waiting_for_alive_target");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(
            spectator.last_applied_respawn_epoch));
    lua_setfield(state, -2, "last_applied_respawn_epoch");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(
            spectator.last_applied_respawn_wave));
    lua_setfield(state, -2, "last_applied_respawn_wave");
    lua_pushnumber(
        state,
        static_cast<lua_Number>(spectator.last_respawn_x));
    lua_setfield(state, -2, "last_respawn_x");
    lua_pushnumber(
        state,
        static_cast<lua_Number>(spectator.last_respawn_y));
    lua_setfield(state, -2, "last_respawn_y");
    std::string display_text;
    (void)multiplayer::TryBuildDeathSpectatorStatusText(
        &display_text);
    lua_pushlstring(
        state,
        display_text.data(),
        display_text.size());
    lua_setfield(state, -2, "display_text");
}

int LuaRuntimeGetMultiplayerState(lua_State* state) {
    const auto runtime = multiplayer::SnapshotRuntimeState();

    lua_createtable(state, 0, 19);
    lua_pushboolean(state, runtime.foundation_ready ? 1 : 0);
    lua_setfield(state, -2, "foundation_ready");
    lua_pushboolean(state, multiplayer::IsLocalTransportEnabled() ? 1 : 0);
    lua_setfield(state, -2, "transport_enabled");
    lua_pushboolean(state, runtime.transport_ready ? 1 : 0);
    lua_setfield(state, -2, "transport_ready");
    lua_pushstring(state, multiplayer::SessionStatusLabel(runtime.session_status));
    lua_setfield(state, -2, "session_status");
    lua_pushstring(state, multiplayer::SessionTransportLabel(runtime.session_transport));
    lua_setfield(state, -2, "session_transport");
    lua_pushinteger(state, static_cast<lua_Integer>(runtime.local_steam_id));
    lua_setfield(state, -2, "local_steam_id");
    lua_pushinteger(state, static_cast<lua_Integer>(runtime.participants.size()));
    lua_setfield(state, -2, "participant_count");
    lua_pushinteger(state, static_cast<lua_Integer>(runtime.transport_packets_sent));
    lua_setfield(state, -2, "transport_packets_sent");
    lua_pushinteger(state, static_cast<lua_Integer>(runtime.transport_packets_received));
    lua_setfield(state, -2, "transport_packets_received");
    lua_pushinteger(state, static_cast<lua_Integer>(runtime.steam_send_failures));
    lua_setfield(state, -2, "steam_send_failures");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(runtime.steam_reliable_send_failures));
    lua_setfield(state, -2, "steam_reliable_send_failures");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(runtime.last_steam_send_failure_result));
    lua_setfield(state, -2, "last_steam_send_failure_result");

    lua_createtable(state, static_cast<int>(runtime.participants.size()), 0);
    int lua_index = 1;
    for (const auto& participant : runtime.participants) {
        lua_createtable(state, 0, 27);
        lua_pushinteger(state, static_cast<lua_Integer>(participant.participant_id));
        lua_setfield(state, -2, "participant_id");
        lua_pushinteger(state, static_cast<lua_Integer>(participant.steam_id));
        lua_setfield(state, -2, "steam_id");
        lua_pushstring(state, participant.name.c_str());
        lua_setfield(state, -2, "name");
        lua_pushstring(state, multiplayer::ParticipantKindLabel(participant.kind));
        lua_setfield(state, -2, "kind");
        lua_pushstring(state, multiplayer::ParticipantControllerKindLabel(participant.controller_kind));
        lua_setfield(state, -2, "controller_kind");
        lua_pushboolean(state, participant.ready ? 1 : 0);
        lua_setfield(state, -2, "ready");
        lua_pushboolean(state, participant.is_owner ? 1 : 0);
        lua_setfield(state, -2, "is_owner");
        lua_pushboolean(state, participant.transport_connected ? 1 : 0);
        lua_setfield(state, -2, "transport_connected");
        lua_pushboolean(state, participant.transport_using_relay ? 1 : 0);
        lua_setfield(state, -2, "transport_using_relay");
        lua_pushinteger(state, static_cast<lua_Integer>(participant.last_packet_ms));
        lua_setfield(state, -2, "last_packet_ms");
        lua_pushboolean(state, participant.runtime.valid ? 1 : 0);
        lua_setfield(state, -2, "runtime_valid");
        lua_pushboolean(state, participant.runtime.in_run ? 1 : 0);
        lua_setfield(state, -2, "in_run");
        lua_pushinteger(state, static_cast<lua_Integer>(participant.runtime.run_nonce));
        lua_setfield(state, -2, "run_nonce");
        lua_pushinteger(state, static_cast<lua_Integer>(participant.runtime.level));
        lua_setfield(state, -2, "level");
        lua_pushinteger(state, static_cast<lua_Integer>(participant.runtime.wave));
        lua_setfield(state, -2, "wave");
        lua_pushinteger(state, static_cast<lua_Integer>(participant.runtime.experience_current));
        lua_setfield(state, -2, "experience_current");
        lua_pushinteger(state, static_cast<lua_Integer>(participant.runtime.experience_next));
        lua_setfield(state, -2, "experience_next");
        lua_pushstring(state, multiplayer::ParticipantSceneIntentKindLabel(participant.runtime.scene_intent.kind));
        lua_setfield(state, -2, "scene_kind");
        lua_pushnumber(state, static_cast<lua_Number>(participant.runtime.life_current));
        lua_setfield(state, -2, "life_current");
        lua_pushnumber(state, static_cast<lua_Number>(participant.runtime.life_max));
        lua_setfield(state, -2, "life_max");
        lua_pushnumber(state, static_cast<lua_Number>(participant.runtime.mana_current));
        lua_setfield(state, -2, "mana_current");
        lua_pushnumber(state, static_cast<lua_Number>(participant.runtime.mana_max));
        lua_setfield(state, -2, "mana_max");
        lua_pushnumber(state, static_cast<lua_Number>(participant.runtime.move_speed));
        lua_setfield(state, -2, "move_speed");
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(
                participant.runtime.persistent_status_flags));
        lua_setfield(state, -2, "persistent_status_flags");
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(
                participant.runtime.transient_status_flags));
        lua_setfield(state, -2, "transient_status_flags");
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(
                participant.runtime.poison_remaining_ticks));
        lua_setfield(state, -2, "poison_remaining_ticks");
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(
                participant.runtime.damage_x4_remaining_ticks));
        lua_setfield(
            state,
            -2,
            "damage_x4_remaining_ticks");
        lua_pushnumber(state, static_cast<lua_Number>(participant.runtime.position_x));
        lua_setfield(state, -2, "x");
        lua_pushnumber(state, static_cast<lua_Number>(participant.runtime.position_y));
        lua_setfield(state, -2, "y");
        lua_pushnumber(state, static_cast<lua_Number>(participant.runtime.heading));
        lua_setfield(state, -2, "heading");
        lua_pushnumber(
            state,
            static_cast<lua_Number>(participant.runtime.movement_intent_x));
        lua_setfield(state, -2, "movement_intent_x");
        lua_pushnumber(
            state,
            static_cast<lua_Number>(participant.runtime.movement_intent_y));
        lua_setfield(state, -2, "movement_intent_y");
        PushParticipantEquipmentState(
            state,
            participant.runtime,
            participant.owned_progression);
        lua_setfield(state, -2, "equipment");
        PushOwnedProgressionState(state, participant.owned_progression);
        lua_setfield(state, -2, "owned_progression");
        lua_rawseti(state, -2, static_cast<lua_Integer>(lua_index));
        ++lua_index;
    }
    lua_setfield(state, -2, "participants");
    PushLevelUpOfferRuntimeInfo(state, runtime.active_level_up_offer);
    lua_setfield(state, -2, "active_level_up_offer");
    PushLevelUpChoiceResultRuntimeInfo(state, runtime.last_level_up_choice_result);
    lua_setfield(state, -2, "last_level_up_choice_result");
    PushLevelUpWaitStatusRuntimeInfo(state, runtime.level_up_wait_status);
    lua_setfield(state, -2, "level_up_wait_status");
    PushSharedGameplayPauseRuntimeInfo(
        state,
        runtime.shared_gameplay_pause);
    lua_setfield(state, -2, "shared_gameplay_pause_status");
    PushDeathSpectatorRuntimeInfo(
        state,
        runtime.death_spectator);
    lua_setfield(state, -2, "death_spectator");

    return 1;
}

int LuaRuntimeGetFrameState(lua_State* state) {
    lua_createtable(state, 0, 2);
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(
            lua_exec_diag::g_endscene_generation.load(std::memory_order_acquire)));
    lua_setfield(state, -2, "frame_count");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(
            lua_exec_diag::g_last_endscene_ms.load(std::memory_order_acquire)));
    lua_setfield(state, -2, "observed_ms");
    return 1;
}

#include "lua_engine_bindings_runtime/level_up_and_runtime_api.inl"
