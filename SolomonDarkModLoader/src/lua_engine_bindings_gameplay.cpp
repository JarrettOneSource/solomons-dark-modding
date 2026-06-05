#include "lua_engine_bindings_internal.h"

#include "mod_loader.h"
#include "multiplayer_local_transport.h"
#include "multiplayer_runtime_state.h"
#include "native_enemy_lifecycle.h"

#include <string>

namespace sdmod::detail {
namespace {

void PushPositionTable(lua_State* state, float x, float y) {
    lua_createtable(state, 0, 2);
    lua_pushnumber(state, static_cast<lua_Number>(x));
    lua_setfield(state, -2, "x");
    lua_pushnumber(state, static_cast<lua_Number>(y));
    lua_setfield(state, -2, "y");
}

void PushEquipVisualLaneState(lua_State* state, const SDModEquipVisualLaneState& lane) {
    lua_createtable(state, 0, 6);
    lua_pushinteger(state, static_cast<lua_Integer>(lane.wrapper_address));
    lua_setfield(state, -2, "wrapper_address");
    lua_pushinteger(state, static_cast<lua_Integer>(lane.holder_address));
    lua_setfield(state, -2, "holder_address");
    lua_pushinteger(state, static_cast<lua_Integer>(lane.current_object_address));
    lua_setfield(state, -2, "current_object_address");
    lua_pushinteger(state, static_cast<lua_Integer>(lane.holder_kind));
    lua_setfield(state, -2, "holder_kind");
    lua_pushinteger(state, static_cast<lua_Integer>(lane.current_object_vtable));
    lua_setfield(state, -2, "current_object_vtable");
    lua_pushinteger(state, static_cast<lua_Integer>(lane.current_object_type_id));
    lua_setfield(state, -2, "current_object_type_id");
}

void PushInventoryItemState(lua_State* state, const SDModInventoryItemState& item) {
    lua_createtable(state, 0, 5);
    lua_pushboolean(state, item.valid ? 1 : 0);
    lua_setfield(state, -2, "valid");
    lua_pushinteger(state, static_cast<lua_Integer>(item.item_address));
    lua_setfield(state, -2, "item_address");
    lua_pushinteger(state, static_cast<lua_Integer>(item.type_id));
    lua_setfield(state, -2, "type_id");
    lua_pushinteger(state, static_cast<lua_Integer>(item.slot));
    lua_setfield(state, -2, "slot");
    lua_pushinteger(state, static_cast<lua_Integer>(item.stack_count));
    lua_setfield(state, -2, "stack_count");
}

void PushProgressionBookEntryState(lua_State* state, const SDModProgressionBookEntryState& entry) {
    lua_createtable(state, 0, 9);
    lua_pushboolean(state, entry.valid ? 1 : 0);
    lua_setfield(state, -2, "valid");
    lua_pushinteger(state, static_cast<lua_Integer>(entry.entry_address));
    lua_setfield(state, -2, "entry_address");
    lua_pushinteger(state, static_cast<lua_Integer>(entry.statbook_address));
    lua_setfield(state, -2, "statbook_address");
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

void PushSceneActorState(lua_State* state, const SDModSceneActorState& actor) {
    lua_createtable(state, 0, 20);
    lua_pushinteger(state, static_cast<lua_Integer>(actor.actor_address));
    lua_setfield(state, -2, "actor_address");
    lua_pushinteger(state, static_cast<lua_Integer>(actor.vtable_address));
    lua_setfield(state, -2, "vtable_address");
    lua_pushinteger(state, static_cast<lua_Integer>(actor.first_method_address));
    lua_setfield(state, -2, "first_method_address");
    lua_pushinteger(state, static_cast<lua_Integer>(actor.object_type_id));
    lua_setfield(state, -2, "object_type_id");
    lua_pushinteger(state, static_cast<lua_Integer>(actor.object_header_word));
    lua_setfield(state, -2, "object_header_word");
    lua_pushinteger(state, static_cast<lua_Integer>(actor.owner_address));
    lua_setfield(state, -2, "owner_address");
    lua_pushinteger(state, static_cast<lua_Integer>(actor.actor_slot));
    lua_setfield(state, -2, "actor_slot");
    lua_pushinteger(state, static_cast<lua_Integer>(actor.world_slot));
    lua_setfield(state, -2, "world_slot");
    lua_pushnumber(state, static_cast<lua_Number>(actor.x));
    lua_setfield(state, -2, "x");
    lua_pushnumber(state, static_cast<lua_Number>(actor.y));
    lua_setfield(state, -2, "y");
    lua_pushnumber(state, static_cast<lua_Number>(actor.radius));
    lua_setfield(state, -2, "radius");
    lua_pushinteger(state, static_cast<lua_Integer>(actor.anim_drive_state));
    lua_setfield(state, -2, "anim_drive_state");
    lua_pushinteger(state, static_cast<lua_Integer>(actor.progression_handle_address));
    lua_setfield(state, -2, "progression_handle_address");
    lua_pushinteger(state, static_cast<lua_Integer>(actor.progression_runtime_address));
    lua_setfield(state, -2, "progression_runtime_address");
    lua_pushnumber(state, static_cast<lua_Number>(actor.hp));
    lua_setfield(state, -2, "hp");
    lua_pushnumber(state, static_cast<lua_Number>(actor.max_hp));
    lua_setfield(state, -2, "max_hp");
    lua_pushboolean(state, actor.dead ? 1 : 0);
    lua_setfield(state, -2, "dead");
    lua_pushinteger(state, static_cast<lua_Integer>(actor.equip_handle_address));
    lua_setfield(state, -2, "equip_handle_address");
    lua_pushinteger(state, static_cast<lua_Integer>(actor.animation_state_ptr));
    lua_setfield(state, -2, "animation_state_ptr");
    lua_pushboolean(state, actor.tracked_enemy ? 1 : 0);
    lua_setfield(state, -2, "tracked_enemy");
    lua_pushinteger(state, static_cast<lua_Integer>(actor.enemy_type));
    lua_setfield(state, -2, "enemy_type");
    PushPositionTable(state, actor.x, actor.y);
    lua_setfield(state, -2, "position");
}

void PushReplicatedWorldActor(lua_State* state, const multiplayer::WorldActorSnapshot& actor) {
    lua_createtable(state, 0, 30);
    lua_pushinteger(state, static_cast<lua_Integer>(actor.network_actor_id));
    lua_setfield(state, -2, "network_actor_id");
    lua_pushinteger(state, static_cast<lua_Integer>(actor.native_type_id));
    lua_setfield(state, -2, "object_type_id");
    lua_pushinteger(state, static_cast<lua_Integer>(actor.enemy_type));
    lua_setfield(state, -2, "enemy_type");
    lua_pushinteger(state, static_cast<lua_Integer>(actor.actor_slot));
    lua_setfield(state, -2, "actor_slot");
    lua_pushinteger(state, static_cast<lua_Integer>(actor.world_slot));
    lua_setfield(state, -2, "world_slot");
    lua_pushboolean(state, actor.dead ? 1 : 0);
    lua_setfield(state, -2, "dead");
    lua_pushboolean(state, actor.tracked_enemy ? 1 : 0);
    lua_setfield(state, -2, "tracked_enemy");
    lua_pushboolean(state, actor.lifecycle_owned ? 1 : 0);
    lua_setfield(state, -2, "lifecycle_owned");
    lua_pushboolean(state, actor.run_static ? 1 : 0);
    lua_setfield(state, -2, "run_static");
    lua_pushinteger(state, static_cast<lua_Integer>(actor.anim_drive_state));
    lua_setfield(state, -2, "anim_drive_state");
    lua_pushinteger(state, static_cast<lua_Integer>(actor.presentation_flags));
    lua_setfield(state, -2, "presentation_flags");
    lua_pushinteger(state, static_cast<lua_Integer>(actor.anim_drive_state_word));
    lua_setfield(state, -2, "anim_drive_state_word");
    lua_pushnumber(state, static_cast<lua_Number>(actor.walk_cycle_primary));
    lua_setfield(state, -2, "walk_cycle_primary");
    lua_pushnumber(state, static_cast<lua_Number>(actor.walk_cycle_secondary));
    lua_setfield(state, -2, "walk_cycle_secondary");
    lua_pushinteger(state, static_cast<lua_Integer>(actor.render_variant_primary));
    lua_setfield(state, -2, "render_variant_primary");
    lua_pushinteger(state, static_cast<lua_Integer>(actor.render_variant_secondary));
    lua_setfield(state, -2, "render_variant_secondary");
    lua_pushinteger(state, static_cast<lua_Integer>(actor.render_weapon_type));
    lua_setfield(state, -2, "render_weapon_type");
    lua_pushinteger(state, static_cast<lua_Integer>(actor.render_selection_byte));
    lua_setfield(state, -2, "render_selection_byte");
    lua_pushinteger(state, static_cast<lua_Integer>(actor.render_variant_tertiary));
    lua_setfield(state, -2, "render_variant_tertiary");
    lua_pushnumber(state, static_cast<lua_Number>(actor.position_x));
    lua_setfield(state, -2, "x");
    lua_pushnumber(state, static_cast<lua_Number>(actor.position_y));
    lua_setfield(state, -2, "y");
    lua_pushnumber(state, static_cast<lua_Number>(actor.radius));
    lua_setfield(state, -2, "radius");
    lua_pushnumber(state, static_cast<lua_Number>(actor.heading));
    lua_setfield(state, -2, "heading");
    lua_pushnumber(state, static_cast<lua_Number>(actor.hp));
    lua_setfield(state, -2, "hp");
    lua_pushnumber(state, static_cast<lua_Number>(actor.max_hp));
    lua_setfield(state, -2, "max_hp");
    PushPositionTable(state, actor.position_x, actor.position_y);
    lua_setfield(state, -2, "position");
}

void PushReplicatedLootDrop(lua_State* state, const multiplayer::LootDropSnapshot& drop) {
    lua_createtable(state, 0, 25);
    lua_pushinteger(state, static_cast<lua_Integer>(drop.network_drop_id));
    lua_setfield(state, -2, "network_drop_id");
    lua_pushinteger(state, static_cast<lua_Integer>(drop.native_type_id));
    lua_setfield(state, -2, "object_type_id");
    lua_pushinteger(state, static_cast<lua_Integer>(drop.native_type_id));
    lua_setfield(state, -2, "native_type_id");
    lua_pushinteger(state, static_cast<lua_Integer>(drop.drop_kind));
    lua_setfield(state, -2, "kind_id");
    lua_pushstring(state, multiplayer::LootDropKindLabel(drop.drop_kind));
    lua_setfield(state, -2, "kind");
    lua_pushboolean(state, drop.active ? 1 : 0);
    lua_setfield(state, -2, "active");
    lua_pushinteger(state, static_cast<lua_Integer>(drop.presentation_state));
    lua_setfield(state, -2, "presentation_state");
    lua_pushinteger(state, static_cast<lua_Integer>(drop.amount));
    lua_setfield(state, -2, "amount");
    lua_pushinteger(state, static_cast<lua_Integer>(drop.amount_tier));
    lua_setfield(state, -2, "amount_tier");
    lua_pushinteger(state, static_cast<lua_Integer>(drop.amount_tier));
    lua_setfield(state, -2, "resource_kind");
    lua_pushnumber(state, static_cast<lua_Number>(drop.value));
    lua_setfield(state, -2, "value");
    lua_pushnumber(state, static_cast<lua_Number>(drop.motion));
    lua_setfield(state, -2, "motion");
    lua_pushnumber(state, static_cast<lua_Number>(drop.progress));
    lua_setfield(state, -2, "progress");
    lua_pushinteger(state, static_cast<lua_Integer>(drop.item_type_id));
    lua_setfield(state, -2, "item_type_id");
    lua_pushinteger(state, static_cast<lua_Integer>(drop.item_slot));
    lua_setfield(state, -2, "item_slot");
    lua_pushinteger(state, static_cast<lua_Integer>(drop.stack_count));
    lua_setfield(state, -2, "stack_count");
    lua_pushinteger(state, static_cast<lua_Integer>(drop.actor_slot));
    lua_setfield(state, -2, "actor_slot");
    lua_pushinteger(state, static_cast<lua_Integer>(drop.world_slot));
    lua_setfield(state, -2, "world_slot");
    lua_pushinteger(state, static_cast<lua_Integer>(drop.lifetime));
    lua_setfield(state, -2, "lifetime");
    lua_pushnumber(state, static_cast<lua_Number>(drop.position_x));
    lua_setfield(state, -2, "x");
    lua_pushnumber(state, static_cast<lua_Number>(drop.position_y));
    lua_setfield(state, -2, "y");
    lua_pushnumber(state, static_cast<lua_Number>(drop.radius));
    lua_setfield(state, -2, "radius");
    PushPositionTable(state, drop.position_x, drop.position_y);
    lua_setfield(state, -2, "position");

    SDModReplicatedLootPresentationState presentation;
    const bool materialized = TryGetReplicatedLootPresentationState(drop.network_drop_id, &presentation);
    lua_pushboolean(state, materialized && presentation.actor_address != 0 ? 1 : 0);
    lua_setfield(state, -2, "materialized");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(materialized ? presentation.actor_address : 0));
    lua_setfield(state, -2, "presentation_actor_address");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(materialized ? presentation.actor_address : 0));
    lua_setfield(state, -2, "local_actor_address");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(materialized ? presentation.last_seen_ms : 0));
    lua_setfield(state, -2, "presentation_last_seen_ms");
}

void PushLootPickupResult(lua_State* state, const multiplayer::LootPickupResultRuntimeInfo& result) {
    lua_createtable(state, 0, 22);
    lua_pushinteger(state, static_cast<lua_Integer>(result.authority_participant_id));
    lua_setfield(state, -2, "authority_participant_id");
    lua_pushinteger(state, static_cast<lua_Integer>(result.participant_id));
    lua_setfield(state, -2, "participant_id");
    lua_pushinteger(state, static_cast<lua_Integer>(result.received_ms));
    lua_setfield(state, -2, "received_ms");
    lua_pushinteger(state, static_cast<lua_Integer>(result.sequence));
    lua_setfield(state, -2, "sequence");
    lua_pushinteger(state, static_cast<lua_Integer>(result.request_sequence));
    lua_setfield(state, -2, "request_sequence");
    lua_pushinteger(state, static_cast<lua_Integer>(result.run_nonce));
    lua_setfield(state, -2, "run_nonce");
    lua_pushinteger(state, static_cast<lua_Integer>(result.network_drop_id));
    lua_setfield(state, -2, "network_drop_id");
    lua_pushstring(state, multiplayer::LootPickupResultCodeLabel(result.result_code));
    lua_setfield(state, -2, "result");
    lua_pushinteger(state, static_cast<lua_Integer>(result.result_code));
    lua_setfield(state, -2, "result_id");
    lua_pushstring(state, multiplayer::LootDropKindLabel(result.drop_kind));
    lua_setfield(state, -2, "kind");
    lua_pushinteger(state, static_cast<lua_Integer>(result.amount));
    lua_setfield(state, -2, "amount");
    lua_pushinteger(state, static_cast<lua_Integer>(result.resulting_gold));
    lua_setfield(state, -2, "resulting_gold");
    lua_pushinteger(state, static_cast<lua_Integer>(result.gold_revision));
    lua_setfield(state, -2, "gold_revision");
    lua_pushinteger(state, static_cast<lua_Integer>(result.resource_kind));
    lua_setfield(state, -2, "resource_kind");
    lua_pushnumber(state, static_cast<lua_Number>(result.resource_delta));
    lua_setfield(state, -2, "resource_delta");
    lua_pushnumber(state, static_cast<lua_Number>(result.resulting_life_current));
    lua_setfield(state, -2, "resulting_life_current");
    lua_pushnumber(state, static_cast<lua_Number>(result.resulting_life_max));
    lua_setfield(state, -2, "resulting_life_max");
    lua_pushnumber(state, static_cast<lua_Number>(result.resulting_mana_current));
    lua_setfield(state, -2, "resulting_mana_current");
    lua_pushnumber(state, static_cast<lua_Number>(result.resulting_mana_max));
    lua_setfield(state, -2, "resulting_mana_max");
    lua_pushinteger(state, static_cast<lua_Integer>(result.item_type_id));
    lua_setfield(state, -2, "item_type_id");
    lua_pushinteger(state, static_cast<lua_Integer>(result.item_slot));
    lua_setfield(state, -2, "item_slot");
    lua_pushinteger(state, static_cast<lua_Integer>(result.stack_count));
    lua_setfield(state, -2, "stack_count");
    lua_pushinteger(state, static_cast<lua_Integer>(result.inventory_revision));
    lua_setfield(state, -2, "inventory_revision");
}

void PushReplicatedWorldActorBinding(
    lua_State* state,
    const multiplayer::WorldSnapshotActorBindingRuntimeInfo& binding) {
    lua_createtable(state, 0, 7);
    lua_pushinteger(state, static_cast<lua_Integer>(binding.network_actor_id));
    lua_setfield(state, -2, "network_actor_id");
    lua_pushinteger(state, static_cast<lua_Integer>(binding.local_actor_address));
    lua_setfield(state, -2, "local_actor_address");
    lua_pushinteger(state, static_cast<lua_Integer>(binding.native_type_id));
    lua_setfield(state, -2, "object_type_id");
    lua_pushinteger(state, static_cast<lua_Integer>(binding.enemy_type));
    lua_setfield(state, -2, "enemy_type");
    lua_pushboolean(state, binding.matched ? 1 : 0);
    lua_setfield(state, -2, "matched");
    lua_pushboolean(state, binding.parked ? 1 : 0);
    lua_setfield(state, -2, "parked");
    lua_pushboolean(state, binding.removed ? 1 : 0);
    lua_setfield(state, -2, "removed");
}

int LuaGameplayStartWaves(lua_State* state) {
    std::string error_message;
    if (!QueueGameplayStartWaves(&error_message)) {
        return luaL_error(state, "sd.gameplay.start_waves failed: %s", error_message.c_str());
    }

    lua_pushboolean(state, 1);
    return 1;
}

int LuaGameplayEnableCombatPrelude(lua_State* state) {
    std::string error_message;
    if (!QueueGameplayEnableCombatPrelude(&error_message)) {
        return luaL_error(state, "sd.gameplay.enable_combat_prelude failed: %s", error_message.c_str());
    }

    lua_pushboolean(state, 1);
    return 1;
}

int LuaGameplayGetCombatState(lua_State* state) {
    SDModGameplayCombatState combat_state;
    if (!TryGetGameplayCombatState(&combat_state) || !combat_state.valid) {
        lua_pushnil(state);
        return 1;
    }

    lua_createtable(state, 0, 11);
    lua_pushstring(state, HexString(combat_state.arena_address).c_str());
    lua_setfield(state, -2, "arena_id");
    lua_pushinteger(state, static_cast<lua_Integer>(combat_state.combat_section_index));
    lua_setfield(state, -2, "section_index");
    lua_pushinteger(state, static_cast<lua_Integer>(combat_state.combat_wave_index));
    lua_setfield(state, -2, "wave_index");
    lua_pushinteger(state, static_cast<lua_Integer>(combat_state.combat_wait_ticks));
    lua_setfield(state, -2, "wait_ticks");
    lua_pushinteger(state, static_cast<lua_Integer>(combat_state.combat_advance_mode));
    lua_setfield(state, -2, "advance_mode");
    lua_pushinteger(state, static_cast<lua_Integer>(combat_state.combat_advance_threshold));
    lua_setfield(state, -2, "advance_threshold");
    lua_pushinteger(state, static_cast<lua_Integer>(combat_state.combat_wave_counter));
    lua_setfield(state, -2, "wave_counter");
    lua_pushboolean(state, combat_state.combat_started_music != 0 ? 1 : 0);
    lua_setfield(state, -2, "started_music");
    lua_pushboolean(state, combat_state.combat_transition_requested != 0 ? 1 : 0);
    lua_setfield(state, -2, "transition_requested");
    lua_pushboolean(state, combat_state.combat_active != 0 ? 1 : 0);
    lua_setfield(state, -2, "active");
    return 1;
}

int LuaPlayerGetState(lua_State* state) {
    SDModPlayerState player_state;
    if (!TryGetPlayerState(&player_state) || !player_state.valid) {
        lua_pushnil(state);
        return 1;
    }

    lua_createtable(state, 0, 58);
    lua_pushnumber(state, static_cast<lua_Number>(player_state.hp));
    lua_setfield(state, -2, "hp");
    lua_pushnumber(state, static_cast<lua_Number>(player_state.max_hp));
    lua_setfield(state, -2, "max_hp");
    lua_pushnumber(state, static_cast<lua_Number>(player_state.mp));
    lua_setfield(state, -2, "mp");
    lua_pushnumber(state, static_cast<lua_Number>(player_state.max_mp));
    lua_setfield(state, -2, "max_mp");
    lua_pushinteger(state, static_cast<lua_Integer>(player_state.xp));
    lua_setfield(state, -2, "xp");
    lua_pushinteger(state, static_cast<lua_Integer>(player_state.level));
    lua_setfield(state, -2, "level");
    lua_pushinteger(state, static_cast<lua_Integer>(player_state.gold));
    lua_setfield(state, -2, "gold");
    lua_pushnumber(state, static_cast<lua_Number>(player_state.x));
    lua_setfield(state, -2, "x");
    lua_pushnumber(state, static_cast<lua_Number>(player_state.y));
    lua_setfield(state, -2, "y");
    lua_pushnumber(state, static_cast<lua_Number>(player_state.heading));
    lua_setfield(state, -2, "heading");
    lua_pushinteger(state, static_cast<lua_Integer>(player_state.actor_address));
    lua_setfield(state, -2, "actor_address");
    lua_pushinteger(state, static_cast<lua_Integer>(player_state.render_subject_address));
    lua_setfield(state, -2, "render_subject_address");
    lua_pushinteger(state, static_cast<lua_Integer>(player_state.world_address));
    lua_setfield(state, -2, "world_address");
    lua_pushinteger(state, static_cast<lua_Integer>(player_state.progression_address));
    lua_setfield(state, -2, "progression_address");
    lua_pushinteger(state, static_cast<lua_Integer>(player_state.animation_state_ptr));
    lua_setfield(state, -2, "animation_state_ptr");
    lua_pushinteger(state, static_cast<lua_Integer>(player_state.render_frame_table));
    lua_setfield(state, -2, "render_frame_table");
    lua_pushinteger(state, static_cast<lua_Integer>(player_state.hub_visual_attachment_ptr));
    lua_setfield(state, -2, "hub_visual_attachment_ptr");
    lua_pushinteger(state, static_cast<lua_Integer>(player_state.hub_visual_source_profile_address));
    lua_setfield(state, -2, "hub_visual_source_profile_address");
    lua_pushinteger(state, static_cast<lua_Integer>(player_state.hub_visual_descriptor_signature));
    lua_setfield(state, -2, "hub_visual_descriptor_signature");
    lua_pushinteger(state, static_cast<lua_Integer>(player_state.render_subject_animation_state_ptr));
    lua_setfield(state, -2, "render_subject_animation_state_ptr");
    lua_pushinteger(state, static_cast<lua_Integer>(player_state.render_subject_frame_table));
    lua_setfield(state, -2, "render_subject_frame_table");
    lua_pushinteger(state, static_cast<lua_Integer>(player_state.render_subject_hub_visual_attachment_ptr));
    lua_setfield(state, -2, "render_subject_hub_visual_attachment_ptr");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(player_state.render_subject_hub_visual_source_profile_address));
    lua_setfield(state, -2, "render_subject_hub_visual_source_profile_address");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(player_state.render_subject_hub_visual_descriptor_signature));
    lua_setfield(state, -2, "render_subject_hub_visual_descriptor_signature");
    lua_pushinteger(state, static_cast<lua_Integer>(player_state.progression_handle_address));
    lua_setfield(state, -2, "progression_handle_address");
    lua_pushinteger(state, static_cast<lua_Integer>(player_state.equip_handle_address));
    lua_setfield(state, -2, "equip_handle_address");
    lua_pushinteger(state, static_cast<lua_Integer>(player_state.equip_runtime_state_address));
    lua_setfield(state, -2, "equip_runtime_state_address");
    lua_pushinteger(state, static_cast<lua_Integer>(player_state.actor_slot));
    lua_setfield(state, -2, "actor_slot");
    lua_pushinteger(state, static_cast<lua_Integer>(player_state.resolved_animation_state_id));
    lua_setfield(state, -2, "resolved_animation_state_id");
    lua_pushinteger(state, static_cast<lua_Integer>(player_state.hub_visual_source_kind));
    lua_setfield(state, -2, "hub_visual_source_kind");
    lua_pushinteger(state, static_cast<lua_Integer>(player_state.render_subject_hub_visual_source_kind));
    lua_setfield(state, -2, "render_subject_hub_visual_source_kind");
    lua_pushinteger(state, static_cast<lua_Integer>(player_state.render_drive_flags));
    lua_setfield(state, -2, "render_drive_flags");
    lua_pushinteger(state, static_cast<lua_Integer>(player_state.render_subject_drive_flags));
    lua_setfield(state, -2, "render_subject_drive_flags");
    lua_pushinteger(state, static_cast<lua_Integer>(player_state.anim_drive_state));
    lua_setfield(state, -2, "anim_drive_state");
    lua_pushinteger(state, static_cast<lua_Integer>(player_state.anim_drive_state_word));
    lua_setfield(state, -2, "anim_drive_state_word");
    lua_pushinteger(state, static_cast<lua_Integer>(player_state.render_subject_anim_drive_state));
    lua_setfield(state, -2, "render_subject_anim_drive_state");
    lua_pushinteger(state, static_cast<lua_Integer>(player_state.render_variant_primary));
    lua_setfield(state, -2, "render_variant_primary");
    lua_pushinteger(state, static_cast<lua_Integer>(player_state.render_variant_secondary));
    lua_setfield(state, -2, "render_variant_secondary");
    lua_pushinteger(state, static_cast<lua_Integer>(player_state.render_weapon_type));
    lua_setfield(state, -2, "render_weapon_type");
    lua_pushinteger(state, static_cast<lua_Integer>(player_state.render_selection_byte));
    lua_setfield(state, -2, "render_selection_byte");
    lua_pushinteger(state, static_cast<lua_Integer>(player_state.render_variant_tertiary));
    lua_setfield(state, -2, "render_variant_tertiary");
    lua_pushinteger(state, static_cast<lua_Integer>(player_state.render_subject_variant_primary));
    lua_setfield(state, -2, "render_subject_variant_primary");
    lua_pushinteger(state, static_cast<lua_Integer>(player_state.render_subject_variant_secondary));
    lua_setfield(state, -2, "render_subject_variant_secondary");
    lua_pushinteger(state, static_cast<lua_Integer>(player_state.render_subject_weapon_type));
    lua_setfield(state, -2, "render_subject_weapon_type");
    lua_pushinteger(state, static_cast<lua_Integer>(player_state.render_subject_selection_byte));
    lua_setfield(state, -2, "render_subject_selection_byte");
    lua_pushinteger(state, static_cast<lua_Integer>(player_state.render_subject_variant_tertiary));
    lua_setfield(state, -2, "render_subject_variant_tertiary");
    lua_pushnumber(state, static_cast<lua_Number>(player_state.walk_cycle_primary));
    lua_setfield(state, -2, "walk_cycle_primary");
    lua_pushnumber(state, static_cast<lua_Number>(player_state.walk_cycle_secondary));
    lua_setfield(state, -2, "walk_cycle_secondary");
    lua_pushnumber(state, static_cast<lua_Number>(player_state.render_drive_stride));
    lua_setfield(state, -2, "render_drive_stride");
    lua_pushnumber(state, static_cast<lua_Number>(player_state.render_advance_rate));
    lua_setfield(state, -2, "render_advance_rate");
    lua_pushnumber(state, static_cast<lua_Number>(player_state.render_advance_phase));
    lua_setfield(state, -2, "render_advance_phase");
    lua_pushnumber(state, static_cast<lua_Number>(player_state.render_drive_effect_timer));
    lua_setfield(state, -2, "render_drive_effect_timer");
    lua_pushnumber(state, static_cast<lua_Number>(player_state.render_drive_effect_progress));
    lua_setfield(state, -2, "render_drive_effect_progress");
    lua_pushnumber(state, static_cast<lua_Number>(player_state.render_drive_overlay_alpha));
    lua_setfield(state, -2, "render_drive_overlay_alpha");
    lua_pushnumber(state, static_cast<lua_Number>(player_state.render_drive_move_blend));
    lua_setfield(state, -2, "render_drive_move_blend");
    lua_pushboolean(state, player_state.gameplay_attach_applied ? 1 : 0);
    lua_setfield(state, -2, "gameplay_attach_applied");
    PushEquipVisualLaneState(state, player_state.primary_visual_lane);
    lua_setfield(state, -2, "primary_visual_lane");
    PushEquipVisualLaneState(state, player_state.secondary_visual_lane);
    lua_setfield(state, -2, "secondary_visual_lane");
    PushEquipVisualLaneState(state, player_state.attachment_visual_lane);
    lua_setfield(state, -2, "attachment_visual_lane");
    PushPositionTable(state, player_state.x, player_state.y);
    lua_setfield(state, -2, "position");
    return 1;
}

int LuaPlayerGetInventoryState(lua_State* state) {
    SDModInventoryState inventory_state;
    if (!TryGetPlayerInventoryState(&inventory_state) || !inventory_state.valid) {
        lua_pushnil(state);
        return 1;
    }

    lua_createtable(state, 0, 12);
    lua_pushboolean(state, inventory_state.valid ? 1 : 0);
    lua_setfield(state, -2, "valid");
    lua_pushinteger(state, static_cast<lua_Integer>(inventory_state.gameplay_scene_address));
    lua_setfield(state, -2, "gameplay_scene_address");
    lua_pushinteger(state, static_cast<lua_Integer>(inventory_state.item_list_root_address));
    lua_setfield(state, -2, "item_list_root_address");
    lua_pushinteger(state, static_cast<lua_Integer>(inventory_state.item_array_address));
    lua_setfield(state, -2, "item_array_address");
    lua_pushinteger(state, static_cast<lua_Integer>(inventory_state.item_count));
    lua_setfield(state, -2, "item_count");
    lua_pushinteger(state, static_cast<lua_Integer>(inventory_state.enumerated_item_count));
    lua_setfield(state, -2, "enumerated_item_count");
    lua_pushboolean(state, inventory_state.truncated ? 1 : 0);
    lua_setfield(state, -2, "truncated");

    lua_createtable(state, static_cast<int>(inventory_state.items.size()), 0);
    int lua_index = 1;
    for (const auto& item : inventory_state.items) {
        PushInventoryItemState(state, item);
        lua_rawseti(state, -2, static_cast<lua_Integer>(lua_index));
        ++lua_index;
    }
    lua_setfield(state, -2, "items");

    PushEquipVisualLaneState(state, inventory_state.primary_visual_lane);
    lua_setfield(state, -2, "primary_visual_lane");
    PushEquipVisualLaneState(state, inventory_state.secondary_visual_lane);
    lua_setfield(state, -2, "secondary_visual_lane");
    PushEquipVisualLaneState(state, inventory_state.attachment_visual_lane);
    lua_setfield(state, -2, "attachment_visual_lane");
    return 1;
}

int LuaPlayerGetProgressionBookState(lua_State* state) {
    SDModProgressionBookState book_state;
    if (!TryGetPlayerProgressionBookState(&book_state) || !book_state.valid) {
        lua_pushnil(state);
        return 1;
    }

    lua_createtable(state, 0, 7);
    lua_pushboolean(state, book_state.valid ? 1 : 0);
    lua_setfield(state, -2, "valid");
    lua_pushinteger(state, static_cast<lua_Integer>(book_state.progression_address));
    lua_setfield(state, -2, "progression_address");
    lua_pushinteger(state, static_cast<lua_Integer>(book_state.entry_table_address));
    lua_setfield(state, -2, "entry_table_address");
    lua_pushinteger(state, static_cast<lua_Integer>(book_state.entry_count));
    lua_setfield(state, -2, "entry_count");
    lua_pushinteger(state, static_cast<lua_Integer>(book_state.enumerated_entry_count));
    lua_setfield(state, -2, "enumerated_entry_count");
    lua_pushboolean(state, book_state.truncated ? 1 : 0);
    lua_setfield(state, -2, "truncated");

    lua_createtable(state, static_cast<int>(book_state.entries.size()), 0);
    int lua_index = 1;
    for (const auto& entry : book_state.entries) {
        PushProgressionBookEntryState(state, entry);
        lua_rawseti(state, -2, static_cast<lua_Integer>(lua_index));
        ++lua_index;
    }
    lua_setfield(state, -2, "entries");
    return 1;
}

int LuaWorldGetState(lua_State* state) {
    SDModWorldState world_state;
    if (!TryGetWorldState(&world_state) || !world_state.valid) {
        lua_pushnil(state);
        return 1;
    }

    lua_createtable(state, 0, 4);
    lua_pushinteger(state, static_cast<lua_Integer>(world_state.wave));
    lua_setfield(state, -2, "wave");
    lua_pushinteger(state, static_cast<lua_Integer>(world_state.enemy_count));
    lua_setfield(state, -2, "enemy_count");
    lua_pushinteger(state, static_cast<lua_Integer>(world_state.time_elapsed_ms));
    lua_setfield(state, -2, "time_elapsed_ms");
    lua_pushnumber(state, static_cast<lua_Number>(world_state.time_elapsed_ms) / 1000.0);
    lua_setfield(state, -2, "time_elapsed");
    return 1;
}

int LuaWorldGetScene(lua_State* state) {
    SDModSceneState scene_state;
    if (!TryGetSceneState(&scene_state) || !scene_state.valid) {
        lua_pushnil(state);
        return 1;
    }

    lua_createtable(state, 0, 16);
    lua_pushstring(state, scene_state.kind.c_str());
    lua_setfield(state, -2, "kind");
    lua_pushstring(state, scene_state.name.c_str());
    lua_setfield(state, -2, "name");
    lua_pushstring(state, scene_state.name.c_str());
    lua_setfield(state, -2, "scene_key");
    lua_pushstring(state, HexString(scene_state.gameplay_scene_address).c_str());
    lua_setfield(state, -2, "id");
    lua_pushstring(state, HexString(scene_state.gameplay_scene_address).c_str());
    lua_setfield(state, -2, "scene_id");
    lua_pushstring(state, HexString(scene_state.world_address).c_str());
    lua_setfield(state, -2, "world_id");
    lua_pushstring(state, HexString(scene_state.arena_address).c_str());
    lua_setfield(state, -2, "arena_id");
    lua_pushstring(state, HexString(scene_state.region_state_address).c_str());
    lua_setfield(state, -2, "region_state_id");
    lua_pushinteger(state, static_cast<lua_Integer>(scene_state.current_region_index));
    lua_setfield(state, -2, "region_index");
    lua_pushinteger(state, static_cast<lua_Integer>(scene_state.current_region_index));
    lua_setfield(state, -2, "scene_index");
    lua_pushinteger(state, static_cast<lua_Integer>(scene_state.region_type_id));
    lua_setfield(state, -2, "region_type_id");
    lua_pushinteger(state, static_cast<lua_Integer>(scene_state.region_type_id));
    lua_setfield(state, -2, "scene_type_id");
    lua_pushinteger(state, static_cast<lua_Integer>(scene_state.pending_level_kind));
    lua_setfield(state, -2, "pending_level_kind");
    lua_pushinteger(state, static_cast<lua_Integer>(scene_state.transition_target_a));
    lua_setfield(state, -2, "transition_target_a");
    lua_pushinteger(state, static_cast<lua_Integer>(scene_state.transition_target_b));
    lua_setfield(state, -2, "transition_target_b");
    lua_pushboolean(state, scene_state.world_address == 0 ? 1 : 0);
    lua_setfield(state, -2, "transitioning");
    return 1;
}

int LuaGameplayGetSelectionDebugState(lua_State* state) {
    SDModGameplaySelectionDebugState debug_state;
    if (!TryGetGameplaySelectionDebugState(&debug_state) || !debug_state.valid) {
        lua_pushnil(state);
        return 1;
    }

    lua_createtable(state, 0, 5);
    lua_pushinteger(state, static_cast<lua_Integer>(debug_state.table_address));
    lua_setfield(state, -2, "table_address");
    lua_pushinteger(state, static_cast<lua_Integer>(debug_state.entry_count));
    lua_setfield(state, -2, "entry_count");
    lua_pushinteger(state, static_cast<lua_Integer>(debug_state.player_selection_state_0));
    lua_setfield(state, -2, "player_selection_state_0");
    lua_pushinteger(state, static_cast<lua_Integer>(debug_state.player_selection_state_1));
    lua_setfield(state, -2, "player_selection_state_1");
    lua_createtable(state, 4, 0);
    for (int slot_index = 0; slot_index < 4; ++slot_index) {
        lua_pushinteger(state, static_cast<lua_Integer>(debug_state.slot_selection_entries[slot_index]));
        lua_rawseti(state, -2, static_cast<lua_Integer>(slot_index + 1));
    }
    lua_setfield(state, -2, "slot_selection_entries");
    return 1;
}

int LuaWorldListActors(lua_State* state) {
    std::vector<SDModSceneActorState> actors;
    if (!TryListSceneActors(&actors)) {
        lua_pushnil(state);
        return 1;
    }

    lua_createtable(state, static_cast<int>(actors.size()), 0);
    int lua_index = 1;
    for (const auto& actor : actors) {
        PushSceneActorState(state, actor);
        lua_rawseti(state, -2, static_cast<lua_Integer>(lua_index));
        ++lua_index;
    }
    return 1;
}

int LuaWorldGetReplicatedActors(lua_State* state) {
    const auto runtime = multiplayer::SnapshotRuntimeState();
    const auto& snapshot = runtime.world_snapshot;
    if (!snapshot.valid) {
        lua_pushnil(state);
        return 1;
    }

    lua_createtable(state, 0, 17);
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.authority_participant_id));
    lua_setfield(state, -2, "authority_participant_id");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.received_ms));
    lua_setfield(state, -2, "received_ms");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.sequence));
    lua_setfield(state, -2, "sequence");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.scene_epoch));
    lua_setfield(state, -2, "scene_epoch");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.run_nonce));
    lua_setfield(state, -2, "run_nonce");
    lua_pushstring(state, multiplayer::ParticipantSceneIntentKindLabel(snapshot.scene_intent.kind));
    lua_setfield(state, -2, "scene_kind");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.actors.size()));
    lua_setfield(state, -2, "actor_count");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.actor_total_count));
    lua_setfield(state, -2, "actor_total_count");
    lua_pushboolean(state, snapshot.truncated ? 1 : 0);
    lua_setfield(state, -2, "truncated");
    lua_pushboolean(state, runtime.world_snapshot_apply.valid ? 1 : 0);
    lua_setfield(state, -2, "apply_valid");
    lua_pushinteger(state, static_cast<lua_Integer>(runtime.world_snapshot_apply.applied_ms));
    lua_setfield(state, -2, "applied_ms");
    lua_pushinteger(state, static_cast<lua_Integer>(runtime.world_snapshot_apply.local_actor_count));
    lua_setfield(state, -2, "local_actor_count");
    lua_pushinteger(state, static_cast<lua_Integer>(runtime.world_snapshot_apply.matched_actor_count));
    lua_setfield(state, -2, "matched_actor_count");
    lua_pushinteger(state, static_cast<lua_Integer>(runtime.world_snapshot_apply.created_actor_count));
    lua_setfield(state, -2, "created_actor_count");
    lua_pushinteger(state, static_cast<lua_Integer>(runtime.world_snapshot_apply.created_actor_total_count));
    lua_setfield(state, -2, "created_actor_total_count");
    lua_pushinteger(state, static_cast<lua_Integer>(runtime.world_snapshot_apply.transform_write_count));
    lua_setfield(state, -2, "transform_write_count");
    lua_pushinteger(state, static_cast<lua_Integer>(runtime.world_snapshot_apply.presentation_write_count));
    lua_setfield(state, -2, "presentation_write_count");
    lua_pushinteger(state, static_cast<lua_Integer>(runtime.world_snapshot_apply.health_write_count));
    lua_setfield(state, -2, "health_write_count");
    lua_pushinteger(state, static_cast<lua_Integer>(runtime.world_snapshot_apply.dead_actor_count));
    lua_setfield(state, -2, "dead_actor_count");
    lua_pushinteger(state, static_cast<lua_Integer>(runtime.world_snapshot_apply.parked_actor_count));
    lua_setfield(state, -2, "parked_actor_count");
    lua_pushinteger(state, static_cast<lua_Integer>(runtime.world_snapshot_apply.removed_actor_count));
    lua_setfield(state, -2, "removed_actor_count");
    lua_pushinteger(state, static_cast<lua_Integer>(runtime.world_snapshot_apply.failed_remove_actor_count));
    lua_setfield(state, -2, "failed_remove_actor_count");
    lua_pushinteger(state, static_cast<lua_Integer>(runtime.world_snapshot_apply.actor_bindings.size()));
    lua_setfield(state, -2, "binding_count");

    lua_createtable(state, static_cast<int>(snapshot.actors.size()), 0);
    int lua_index = 1;
    for (const auto& actor : snapshot.actors) {
        PushReplicatedWorldActor(state, actor);
        lua_rawseti(state, -2, static_cast<lua_Integer>(lua_index));
        ++lua_index;
    }
    lua_setfield(state, -2, "actors");

    lua_createtable(state, static_cast<int>(runtime.world_snapshot_apply.actor_bindings.size()), 0);
    lua_index = 1;
    for (const auto& binding : runtime.world_snapshot_apply.actor_bindings) {
        PushReplicatedWorldActorBinding(state, binding);
        lua_rawseti(state, -2, static_cast<lua_Integer>(lua_index));
        ++lua_index;
    }
    lua_setfield(state, -2, "bindings");
    return 1;
}

int LuaWorldGetReplicatedLoot(lua_State* state) {
    const auto runtime = multiplayer::SnapshotRuntimeState();
    const auto& snapshot = runtime.loot_snapshot;
    if (!snapshot.valid) {
        lua_pushnil(state);
        return 1;
    }

    lua_createtable(state, 0, 10);
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.authority_participant_id));
    lua_setfield(state, -2, "authority_participant_id");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.received_ms));
    lua_setfield(state, -2, "received_ms");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.sequence));
    lua_setfield(state, -2, "sequence");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.scene_epoch));
    lua_setfield(state, -2, "scene_epoch");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.run_nonce));
    lua_setfield(state, -2, "run_nonce");
    lua_pushstring(state, multiplayer::ParticipantSceneIntentKindLabel(snapshot.scene_intent.kind));
    lua_setfield(state, -2, "scene_kind");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.drops.size()));
    lua_setfield(state, -2, "drop_count");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.drop_total_count));
    lua_setfield(state, -2, "drop_total_count");
    lua_pushboolean(state, snapshot.truncated ? 1 : 0);
    lua_setfield(state, -2, "truncated");

    lua_createtable(state, static_cast<int>(snapshot.drops.size()), 0);
    int lua_index = 1;
    for (const auto& drop : snapshot.drops) {
        PushReplicatedLootDrop(state, drop);
        lua_rawseti(state, -2, static_cast<lua_Integer>(lua_index));
        ++lua_index;
    }
    lua_setfield(state, -2, "drops");
    if (runtime.last_loot_pickup_result.valid) {
        PushLootPickupResult(state, runtime.last_loot_pickup_result);
        lua_setfield(state, -2, "last_pickup_result");
    }
    return 1;
}

int LuaWorldRebindActor(lua_State* state) {
    const auto actor_address = static_cast<uintptr_t>(luaL_checkinteger(state, 1));
    std::string error_message;
    if (!RebindSceneActorCell(actor_address, &error_message)) {
        lua_pushboolean(state, 0);
        lua_pushstring(state, error_message.c_str());
        return 2;
    }

    lua_pushboolean(state, 1);
    return 1;
}

int LuaWorldSpawnReward(lua_State* state) {
    luaL_checktype(state, 1, LUA_TTABLE);
    lua_getfield(state, 1, "kind");
    const auto* kind = luaL_checkstring(state, -1);
    const std::string kind_value = kind == nullptr ? std::string() : std::string(kind);
    lua_pop(state, 1);
    lua_getfield(state, 1, "amount");
    const auto amount = static_cast<int>(luaL_checkinteger(state, -1));
    lua_pop(state, 1);
    lua_getfield(state, 1, "x");
    const auto x = static_cast<float>(luaL_checknumber(state, -1));
    lua_pop(state, 1);
    lua_getfield(state, 1, "y");
    const auto y = static_cast<float>(luaL_checknumber(state, -1));
    lua_pop(state, 1);

    std::string error_message;
    if (!SpawnReward(kind_value, amount, x, y, &error_message)) {
        lua_pushboolean(state, 0);
        lua_pushstring(state, error_message.c_str());
        return 2;
    }

    lua_pushboolean(state, 1);
    return 1;
}

int LuaWorldRequestLootPickup(lua_State* state) {
    const auto network_drop_id = static_cast<std::uint64_t>(luaL_checkinteger(state, 1));
    std::uint32_t request_sequence = 0;
    std::string error_message;
    if (!multiplayer::QueueLocalLootPickupRequest(
            network_drop_id,
            &request_sequence,
            &error_message)) {
        lua_pushboolean(state, 0);
        lua_pushstring(state, error_message.c_str());
        return 2;
    }

    lua_pushboolean(state, 1);
    lua_pushinteger(state, static_cast<lua_Integer>(request_sequence));
    return 2;
}

int LuaWorldTriggerEnemyDeath(lua_State* state) {
    const auto actor_address = static_cast<uintptr_t>(luaL_checkinteger(state, 1));
    std::uint32_t exception_code = 0;
    const bool triggered = sdmod::TryTriggerRunEnemyDeath(actor_address, &exception_code);
    lua_pushboolean(state, triggered ? 1 : 0);
    lua_pushinteger(state, static_cast<lua_Integer>(exception_code));
    return 2;
}

}  // namespace

void RegisterLuaGameplayBindings(lua_State* state) {
    lua_createtable(state, 0, 4);
    RegisterFunction(state, &LuaGameplayStartWaves, "start_waves");
    RegisterFunction(state, &LuaGameplayEnableCombatPrelude, "enable_combat_prelude");
    RegisterFunction(state, &LuaGameplayGetCombatState, "get_combat_state");
    RegisterFunction(state, &LuaGameplayGetSelectionDebugState, "get_selection_debug_state");
    lua_setfield(state, -2, "gameplay");

    lua_createtable(state, 0, 3);
    RegisterFunction(state, &LuaPlayerGetState, "get_state");
    RegisterFunction(state, &LuaPlayerGetInventoryState, "get_inventory_state");
    RegisterFunction(state, &LuaPlayerGetProgressionBookState, "get_progression_book_state");
    lua_setfield(state, -2, "player");

    lua_createtable(state, 0, 9);
    RegisterFunction(state, &LuaWorldGetState, "get_state");
    RegisterFunction(state, &LuaWorldGetScene, "get_scene");
    RegisterFunction(state, &LuaWorldListActors, "list_actors");
    RegisterFunction(state, &LuaWorldGetReplicatedActors, "get_replicated_actors");
    RegisterFunction(state, &LuaWorldGetReplicatedLoot, "get_replicated_loot");
    RegisterFunction(state, &LuaWorldRequestLootPickup, "request_loot_pickup");
    RegisterFunction(state, &LuaWorldRebindActor, "rebind_actor");
    RegisterFunction(state, &LuaWorldSpawnReward, "spawn_reward");
    RegisterFunction(state, &LuaWorldTriggerEnemyDeath, "trigger_enemy_death");
    lua_setfield(state, -2, "world");
}

}  // namespace sdmod::detail
