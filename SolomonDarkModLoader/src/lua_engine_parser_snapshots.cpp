#include "lua_engine_parsers_internal.h"

namespace sdmod::detail {
namespace {

void PushBotEquipVisualLaneState(
    lua_State* state,
    const multiplayer::BotEquipVisualLaneState& lane) {
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

}  // namespace

void PushBotSnapshot(lua_State* state, const multiplayer::BotSnapshot& snapshot) {
    using namespace sdmod::detail::parsers;

    lua_createtable(state, 0, 71);
    lua_pushboolean(state, snapshot.available ? 1 : 0);
    lua_setfield(state, -2, "available");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.bot_id));
    lua_setfield(state, -2, "id");
    lua_pushstring(state, snapshot.display_name.c_str());
    lua_setfield(state, -2, "name");
    lua_pushstring(state, multiplayer::ParticipantKindLabel(snapshot.participant_kind));
    lua_setfield(state, -2, "participant_kind");
    lua_pushstring(state, multiplayer::ParticipantControllerKindLabel(snapshot.controller_kind));
    lua_setfield(state, -2, "controller_kind");
    PushCharacterProfile(state, snapshot.character_profile);
    lua_setfield(state, -2, "profile");
    PushSceneIntent(state, snapshot.scene_intent);
    lua_setfield(state, -2, "scene");
    lua_pushboolean(state, snapshot.ready ? 1 : 0);
    lua_setfield(state, -2, "ready");
    lua_pushboolean(state, snapshot.in_run ? 1 : 0);
    lua_setfield(state, -2, "in_run");
    lua_pushboolean(state, snapshot.runtime_valid ? 1 : 0);
    lua_setfield(state, -2, "runtime_valid");
    lua_pushboolean(state, snapshot.transform_valid ? 1 : 0);
    lua_setfield(state, -2, "transform_valid");
    lua_pushboolean(state, snapshot.entity_materialized ? 1 : 0);
    lua_setfield(state, -2, "entity_materialized");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.run_nonce));
    lua_setfield(state, -2, "run_nonce");
    lua_createtable(state, 0, 2);
    lua_pushnumber(state, snapshot.position_x);
    lua_setfield(state, -2, "x");
    lua_pushnumber(state, snapshot.position_y);
    lua_setfield(state, -2, "y");
    lua_setfield(state, -2, "position");
    lua_pushnumber(state, snapshot.position_x);
    lua_setfield(state, -2, "x");
    lua_pushnumber(state, snapshot.position_y);
    lua_setfield(state, -2, "y");
    lua_pushnumber(state, snapshot.heading);
    lua_setfield(state, -2, "heading");
    lua_pushnumber(state, snapshot.hp);
    lua_setfield(state, -2, "hp");
    lua_pushnumber(state, snapshot.max_hp);
    lua_setfield(state, -2, "max_hp");
    lua_pushnumber(state, snapshot.mp);
    lua_setfield(state, -2, "mp");
    lua_pushnumber(state, snapshot.max_mp);
    lua_setfield(state, -2, "max_mp");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.actor_address));
    lua_setfield(state, -2, "actor_address");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.world_address));
    lua_setfield(state, -2, "world_address");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.animation_state_ptr));
    lua_setfield(state, -2, "animation_state_ptr");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.render_frame_table));
    lua_setfield(state, -2, "render_frame_table");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.hub_visual_attachment_ptr));
    lua_setfield(state, -2, "hub_visual_attachment_ptr");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.hub_visual_source_profile_address));
    lua_setfield(state, -2, "hub_visual_source_profile_address");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.hub_visual_descriptor_signature));
    lua_setfield(state, -2, "hub_visual_descriptor_signature");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.hub_visual_proxy_address));
    lua_setfield(state, -2, "hub_visual_proxy_address");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.progression_handle_address));
    lua_setfield(state, -2, "progression_handle_address");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.equip_handle_address));
    lua_setfield(state, -2, "equip_handle_address");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.progression_runtime_state_address));
    lua_setfield(state, -2, "progression_runtime_state_address");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.equip_runtime_state_address));
    lua_setfield(state, -2, "equip_runtime_state_address");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.gameplay_slot));
    lua_setfield(state, -2, "gameplay_slot");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.actor_slot));
    lua_setfield(state, -2, "actor_slot");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.slot_anim_state_index));
    lua_setfield(state, -2, "slot_anim_state_index");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.resolved_animation_state_id));
    lua_setfield(state, -2, "resolved_animation_state_id");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.hub_visual_source_kind));
    lua_setfield(state, -2, "hub_visual_source_kind");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.render_drive_flags));
    lua_setfield(state, -2, "render_drive_flags");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.anim_drive_state));
    lua_setfield(state, -2, "anim_drive_state");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.no_interrupt));
    lua_setfield(state, -2, "no_interrupt");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.active_cast_group));
    lua_setfield(state, -2, "active_cast_group");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.active_cast_slot));
    lua_setfield(state, -2, "active_cast_slot");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.render_variant_primary));
    lua_setfield(state, -2, "render_variant_primary");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.render_variant_secondary));
    lua_setfield(state, -2, "render_variant_secondary");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.render_weapon_type));
    lua_setfield(state, -2, "render_weapon_type");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.render_selection_byte));
    lua_setfield(state, -2, "render_selection_byte");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.render_variant_tertiary));
    lua_setfield(state, -2, "render_variant_tertiary");
    lua_pushboolean(state, snapshot.cast_pending ? 1 : 0);
    lua_setfield(state, -2, "cast_pending");
    lua_pushboolean(state, snapshot.cast_active ? 1 : 0);
    lua_setfield(state, -2, "cast_active");
    lua_pushboolean(state, snapshot.cast_ready ? 1 : 0);
    lua_setfield(state, -2, "cast_ready");
    lua_pushboolean(state, snapshot.cast_startup_in_progress ? 1 : 0);
    lua_setfield(state, -2, "cast_startup_in_progress");
    lua_pushboolean(state, snapshot.cast_saw_activity ? 1 : 0);
    lua_setfield(state, -2, "cast_saw_activity");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.cast_skill_id));
    lua_setfield(state, -2, "cast_skill_id");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.cast_ticks_waiting));
    lua_setfield(state, -2, "cast_ticks_waiting");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.cast_target_actor_address));
    lua_setfield(state, -2, "cast_target_actor_address");
    lua_pushnumber(state, snapshot.walk_cycle_primary);
    lua_setfield(state, -2, "walk_cycle_primary");
    lua_pushnumber(state, snapshot.walk_cycle_secondary);
    lua_setfield(state, -2, "walk_cycle_secondary");
    lua_pushnumber(state, snapshot.render_drive_stride);
    lua_setfield(state, -2, "render_drive_stride");
    lua_pushnumber(state, snapshot.render_advance_rate);
    lua_setfield(state, -2, "render_advance_rate");
    lua_pushnumber(state, snapshot.render_advance_phase);
    lua_setfield(state, -2, "render_advance_phase");
    lua_pushnumber(state, snapshot.render_drive_overlay_alpha);
    lua_setfield(state, -2, "render_drive_overlay_alpha");
    lua_pushnumber(state, snapshot.render_drive_move_blend);
    lua_setfield(state, -2, "render_drive_move_blend");
    PushBotEquipVisualLaneState(state, snapshot.primary_visual_lane);
    lua_setfield(state, -2, "primary_visual_lane");
    PushBotEquipVisualLaneState(state, snapshot.secondary_visual_lane);
    lua_setfield(state, -2, "secondary_visual_lane");
    PushBotEquipVisualLaneState(state, snapshot.attachment_visual_lane);
    lua_setfield(state, -2, "attachment_visual_lane");
    lua_pushboolean(state, snapshot.gameplay_attach_applied ? 1 : 0);
    lua_setfield(state, -2, "gameplay_attach_applied");
    lua_pushstring(state, multiplayer::BotControllerStateLabel(snapshot.state));
    lua_setfield(state, -2, "state");
    lua_pushboolean(state, snapshot.moving ? 1 : 0);
    lua_setfield(state, -2, "moving");
    lua_pushboolean(state, snapshot.has_target ? 1 : 0);
    lua_setfield(state, -2, "has_target");
    if (snapshot.has_target) {
        lua_pushnumber(state, snapshot.target_x);
        lua_setfield(state, -2, "target_x");
        lua_pushnumber(state, snapshot.target_y);
        lua_setfield(state, -2, "target_y");
    } else {
        lua_pushnil(state);
        lua_setfield(state, -2, "target_x");
        lua_pushnil(state);
        lua_setfield(state, -2, "target_y");
    }
    lua_pushnumber(state, snapshot.distance_to_target);
    lua_setfield(state, -2, "distance_to_target");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.queued_cast_count));
    lua_setfield(state, -2, "queued_cast_count");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.last_queued_cast_ms));
    lua_setfield(state, -2, "last_queued_cast_ms");
    lua_pushboolean(state, snapshot.skill_choice_pending ? 1 : 0);
    lua_setfield(state, -2, "skill_choice_pending");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.skill_choice_generation));
    lua_setfield(state, -2, "skill_choice_generation");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.skill_choice_level));
    lua_setfield(state, -2, "skill_choice_level");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.skill_choice_experience));
    lua_setfield(state, -2, "skill_choice_experience");
    lua_createtable(state, static_cast<int>(snapshot.skill_choice_options.size()), 0);
    for (std::size_t index = 0; index < snapshot.skill_choice_options.size(); ++index) {
        const auto& option = snapshot.skill_choice_options[index];
        lua_createtable(state, 0, 2);
        lua_pushinteger(state, static_cast<lua_Integer>(option.option_id));
        lua_setfield(state, -2, "id");
        lua_pushinteger(state, static_cast<lua_Integer>(option.apply_count));
        lua_setfield(state, -2, "apply_count");
        lua_rawseti(state, -2, static_cast<lua_Integer>(index + 1));
    }
    lua_setfield(state, -2, "skill_choice_options");
}

void PushBotSnapshotArray(lua_State* state) {
    const auto count = multiplayer::GetBotCount();
    lua_createtable(state, static_cast<int>(count), 0);
    for (std::uint32_t index = 0; index < count; ++index) {
        multiplayer::BotSnapshot snapshot;
        if (!multiplayer::ReadBotSnapshotByIndex(index, &snapshot)) {
            continue;
        }

        PushBotSnapshot(state, snapshot);
        lua_rawseti(state, -2, static_cast<lua_Integer>(index + 1));
    }
}

}  // namespace sdmod::detail
