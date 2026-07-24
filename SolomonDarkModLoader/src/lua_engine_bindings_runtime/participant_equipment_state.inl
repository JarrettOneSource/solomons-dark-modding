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
