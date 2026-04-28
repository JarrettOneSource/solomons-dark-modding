#include "lua_engine_bindings_internal.h"

#include "mod_loader.h"

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

void PushSceneActorState(lua_State* state, const SDModSceneActorState& actor) {
    lua_createtable(state, 0, 19);
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

void PushEnemySpawnResult(lua_State* state, const SDModEnemySpawnResult& result) {
    lua_createtable(state, 0, 15);
    lua_pushboolean(state, result.valid ? 1 : 0);
    lua_setfield(state, -2, "valid");
    lua_pushboolean(state, result.ok ? 1 : 0);
    lua_setfield(state, -2, "ok");
    lua_pushinteger(state, static_cast<lua_Integer>(result.request_id));
    lua_setfield(state, -2, "request_id");
    lua_pushinteger(state, static_cast<lua_Integer>(result.type_id));
    lua_setfield(state, -2, "type_id");
    lua_pushinteger(state, static_cast<lua_Integer>(result.actor_address));
    lua_setfield(state, -2, "actor_address");
    lua_pushnumber(state, static_cast<lua_Number>(result.requested_x));
    lua_setfield(state, -2, "requested_x");
    lua_pushnumber(state, static_cast<lua_Number>(result.requested_y));
    lua_setfield(state, -2, "requested_y");
    lua_pushnumber(state, static_cast<lua_Number>(result.x));
    lua_setfield(state, -2, "x");
    lua_pushnumber(state, static_cast<lua_Number>(result.y));
    lua_setfield(state, -2, "y");
    lua_pushboolean(state, result.wrote_x ? 1 : 0);
    lua_setfield(state, -2, "wrote_x");
    lua_pushboolean(state, result.wrote_y ? 1 : 0);
    lua_setfield(state, -2, "wrote_y");
    lua_pushboolean(state, result.rebind_ok ? 1 : 0);
    lua_setfield(state, -2, "rebind_ok");
    lua_pushinteger(state, static_cast<lua_Integer>(result.rebind_exception_code));
    lua_setfield(state, -2, "rebind_exception_code");
    lua_pushinteger(state, static_cast<lua_Integer>(result.completed_tick_ms));
    lua_setfield(state, -2, "completed_tick_ms");
    lua_pushstring(state, result.error_message.c_str());
    lua_setfield(state, -2, "error_message");
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

    lua_createtable(state, 0, 10);
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

    lua_createtable(state, 0, 55);
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

int LuaWorldSpawnEnemy(lua_State* state) {
    luaL_checktype(state, 1, LUA_TTABLE);
    lua_getfield(state, 1, "type_id");
    const auto type_id = static_cast<int>(luaL_checkinteger(state, -1));
    lua_pop(state, 1);
    lua_getfield(state, 1, "x");
    const auto x = static_cast<float>(luaL_checknumber(state, -1));
    lua_pop(state, 1);
    lua_getfield(state, 1, "y");
    const auto y = static_cast<float>(luaL_checknumber(state, -1));
    lua_pop(state, 1);

    std::string error_message;
    std::uint64_t request_id = 0;
    if (!SpawnEnemyByType(type_id, x, y, &error_message, &request_id)) {
        lua_pushboolean(state, 0);
        lua_pushstring(state, error_message.c_str());
        return 2;
    }

    lua_pushboolean(state, 1);
    lua_pushnil(state);
    lua_pushinteger(state, static_cast<lua_Integer>(request_id));
    return 3;
}

int LuaWorldGetLastSpawnedEnemy(lua_State* state) {
    std::uint64_t request_id = 0;
    if (lua_gettop(state) >= 1 && !lua_isnil(state, 1)) {
        request_id = static_cast<std::uint64_t>(luaL_checkinteger(state, 1));
    }

    SDModEnemySpawnResult result;
    if (!TryGetLastEnemySpawnResult(&result, request_id)) {
        lua_pushnil(state);
        return 1;
    }

    PushEnemySpawnResult(state, result);
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

}  // namespace

void RegisterLuaGameplayBindings(lua_State* state) {
    lua_createtable(state, 0, 4);
    RegisterFunction(state, &LuaGameplayStartWaves, "start_waves");
    RegisterFunction(state, &LuaGameplayEnableCombatPrelude, "enable_combat_prelude");
    RegisterFunction(state, &LuaGameplayGetCombatState, "get_combat_state");
    RegisterFunction(state, &LuaGameplayGetSelectionDebugState, "get_selection_debug_state");
    lua_setfield(state, -2, "gameplay");

    lua_createtable(state, 0, 1);
    RegisterFunction(state, &LuaPlayerGetState, "get_state");
    lua_setfield(state, -2, "player");

    lua_createtable(state, 0, 5);
    RegisterFunction(state, &LuaWorldGetState, "get_state");
    RegisterFunction(state, &LuaWorldGetScene, "get_scene");
    RegisterFunction(state, &LuaWorldListActors, "list_actors");
    RegisterFunction(state, &LuaWorldSpawnEnemy, "spawn_enemy");
    RegisterFunction(state, &LuaWorldGetLastSpawnedEnemy, "get_last_spawned_enemy");
    RegisterFunction(state, &LuaWorldRebindActor, "rebind_actor");
    RegisterFunction(state, &LuaWorldSpawnReward, "spawn_reward");
    lua_setfield(state, -2, "world");
}

}  // namespace sdmod::detail
