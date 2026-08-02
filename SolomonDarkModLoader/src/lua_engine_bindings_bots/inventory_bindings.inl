void PushPotionEffectDetails(
    lua_State* state,
    const multiplayer::BotPotionEffectDetails& effect) {
    lua_pushnumber(state, effect.restores_hp_fraction);
    lua_setfield(state, -2, "restores_hp_fraction");
    lua_pushnumber(state, effect.restores_mana_fraction);
    lua_setfield(state, -2, "restores_mana_fraction");
    lua_pushnumber(state, effect.damage_multiplier);
    lua_setfield(state, -2, "damage_multiplier");
    lua_pushboolean(state, effect.cures_poison ? 1 : 0);
    lua_setfield(state, -2, "cures_poison");
    lua_pushnumber(
        state,
        effect.poison_immunity_duration_seconds);
    lua_setfield(
        state,
        -2,
        "poison_immunity_duration_seconds");
    lua_pushboolean(state, effect.concentrates_all ? 1 : 0);
    lua_setfield(state, -2, "concentrates_all");
    lua_pushnumber(state, effect.effect_duration_seconds);
    lua_setfield(state, -2, "effect_duration_seconds");
}

void PushPotionInventoryDetails(
    lua_State* state,
    const multiplayer::BotPotionInventoryDetails& row) {
    lua_createtable(state, 0, 16);
    lua_pushinteger(state, row.stock_subtype);
    lua_setfield(state, -2, "stock_subtype");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(row.content_id));
    lua_setfield(state, -2, "content_id");
    lua_pushlstring(
        state,
        row.identity_key.data(),
        row.identity_key.size());
    lua_setfield(state, -2, "identity_key");
    lua_pushinteger(state, row.count);
    lua_setfield(state, -2, "count");
    lua_pushboolean(state, row.custom ? 1 : 0);
    lua_setfield(state, -2, "custom");
    lua_pushboolean(state, row.effect_resolved ? 1 : 0);
    lua_setfield(state, -2, "effect_resolved");
    lua_pushboolean(
        state,
        row.synthetic_use_supported ? 1 : 0);
    lua_setfield(state, -2, "synthetic_use_supported");
    PushPotionEffectDetails(state, row.effect);
}

void PushEquippedItemDetails(
    lua_State* state,
    const multiplayer::BotEquippedItemDetails& row) {
    lua_createtable(state, 0, 19);
    lua_pushlstring(
        state,
        row.slot.data(),
        row.slot.size());
    lua_setfield(state, -2, "slot");
    lua_pushboolean(state, row.present ? 1 : 0);
    lua_setfield(state, -2, "present");
    lua_pushlstring(
        state,
        row.identity_key.data(),
        row.identity_key.size());
    lua_setfield(state, -2, "identity_key");
    lua_pushlstring(
        state,
        row.recipe_name.data(),
        row.recipe_name.size());
    lua_setfield(state, -2, "recipe_name");
    lua_pushinteger(state, row.catalog_index);
    lua_setfield(state, -2, "catalog_index");
    lua_pushboolean(state, row.catalog_resolved ? 1 : 0);
    lua_setfield(state, -2, "catalog_resolved");
    lua_pushinteger(state, row.rarity_id);
    lua_setfield(state, -2, "rarity_id");
    lua_pushinteger(state, row.level);
    lua_setfield(state, -2, "level");
    lua_pushboolean(state, row.set_complete ? 1 : 0);
    lua_setfield(state, -2, "set_complete");
    lua_pushnumber(state, row.offense_effect);
    lua_setfield(state, -2, "offense_effect");
    lua_pushnumber(state, row.resource_effect);
    lua_setfield(state, -2, "resource_effect");
    lua_pushnumber(state, row.mobility_effect);
    lua_setfield(state, -2, "mobility_effect");
    lua_pushnumber(state, row.defense_effect);
    lua_setfield(state, -2, "defense_effect");
    lua_pushboolean(
        state,
        row.targeted_effect_present ? 1 : 0);
    lua_setfield(state, -2, "targeted_effect_present");
    lua_pushinteger(state, row.target_kind);
    lua_setfield(state, -2, "target_kind");
    lua_pushinteger(state, row.target_id);
    lua_setfield(state, -2, "target_id");
    lua_pushnumber(state, row.target_magnitude);
    lua_setfield(state, -2, "target_magnitude");
    lua_pushboolean(
        state,
        row.special_feature_present ? 1 : 0);
    lua_setfield(state, -2, "special_feature_present");
}

void PushInventorySummary(
    lua_State* state,
    const multiplayer::BotInventorySummary& summary) {
    lua_createtable(state, 0, 10);
    lua_pushinteger(state, summary.item_total_count);
    lua_setfield(state, -2, "item_total_count");
    lua_pushinteger(state, summary.potion_count);
    lua_setfield(state, -2, "potion_count");
    lua_pushinteger(state, summary.equipment_count);
    lua_setfield(state, -2, "equipment_count");
    lua_pushinteger(state, summary.sack_count);
    lua_setfield(state, -2, "sack_count");
    lua_pushinteger(state, summary.misc_count);
    lua_setfield(state, -2, "misc_count");
    lua_pushinteger(state, summary.perk_count);
    lua_setfield(state, -2, "perk_count");
    lua_pushinteger(state, summary.map_count);
    lua_setfield(state, -2, "map_count");
    lua_pushinteger(state, summary.registered_custom_count);
    lua_setfield(state, -2, "registered_custom_count");
    lua_pushinteger(state, summary.unknown_count);
    lua_setfield(state, -2, "unknown_count");
    lua_pushinteger(state, summary.wizard_key_count);
    lua_setfield(state, -2, "wizard_key_count");
}

void PushBotInventoryDetails(
    lua_State* state,
    const multiplayer::BotInventoryDetails& details) {
    lua_createtable(state, 0, 13);
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(details.participant_id));
    lua_setfield(state, -2, "participant_id");
    lua_pushinteger(state, details.run_nonce);
    lua_setfield(state, -2, "run_nonce");
    lua_pushinteger(state, details.inventory_revision);
    lua_setfield(state, -2, "inventory_revision");
    lua_pushinteger(state, details.equipment_revision);
    lua_setfield(state, -2, "equipment_revision");
    lua_pushboolean(
        state,
        details.descriptors_resolved ? 1 : 0);
    lua_setfield(state, -2, "descriptors_resolved");
    lua_pushnumber(
        state,
        details.damage_x4_remaining_seconds);
    lua_setfield(
        state,
        -2,
        "damage_x4_remaining_seconds");
    lua_pushnumber(
        state,
        details.poison_immunity_remaining_seconds);
    lua_setfield(
        state,
        -2,
        "poison_immunity_remaining_seconds");
    lua_pushnumber(
        state,
        details.all_concentration_remaining_seconds);
    lua_setfield(
        state,
        -2,
        "all_concentration_remaining_seconds");
    lua_pushboolean(state, details.timers_resolved ? 1 : 0);
    lua_setfield(state, -2, "timers_resolved");

    lua_createtable(
        state,
        static_cast<int>(details.potions.size()),
        0);
    for (std::size_t index = 0;
         index < details.potions.size();
         ++index) {
        PushPotionInventoryDetails(
            state,
            details.potions[index]);
        lua_rawseti(
            state,
            -2,
            static_cast<lua_Integer>(index + 1));
    }
    lua_setfield(state, -2, "potions");

    lua_createtable(
        state,
        static_cast<int>(details.equipped.size()),
        0);
    for (std::size_t index = 0;
         index < details.equipped.size();
         ++index) {
        PushEquippedItemDetails(
            state,
            details.equipped[index]);
        lua_rawseti(
            state,
            -2,
            static_cast<lua_Integer>(index + 1));
    }
    lua_setfield(state, -2, "equipped");
    PushInventorySummary(state, details.summary);
    lua_setfield(state, -2, "summary");
}

int LuaBotsGetInventoryDetails(lua_State* state) {
    std::uint64_t participant_id = 0;
    std::string error_message;
    if (!ParseBotIdArgument(
            state,
            1,
            &participant_id,
            &error_message)) {
        return luaL_error(
            state,
            "%s",
            error_message.c_str());
    }
    multiplayer::BotInventoryDetails details;
    if (!multiplayer::ReadParticipantInventoryDetails(
            participant_id,
            &details)) {
        lua_pushnil(state);
        return 1;
    }
    PushBotInventoryDetails(state, details);
    return 1;
}

int LuaBotsUseConsumable(lua_State* state) {
    std::uint64_t participant_id = 0;
    std::string error_message;
    if (!ParseBotIdArgument(
            state,
            1,
            &participant_id,
            &error_message)) {
        return luaL_error(
            state,
            "%s",
            error_message.c_str());
    }
    luaL_checktype(state, 2, LUA_TTABLE);
    const int selector_index = lua_absindex(state, 2);
    lua_pushnil(state);
    while (lua_next(state, selector_index) != 0) {
        if (lua_type(state, -2) != LUA_TSTRING) {
            lua_pop(state, 2);
            return luaL_error(
                state,
                "sd.bots.use_consumable selector accepts only named fields");
        }
        std::size_t length = 0;
        const auto* field =
            lua_tolstring(state, -2, &length);
        const std::string_view name(field, length);
        lua_pop(state, 1);
        if (name != "potion_slot" &&
            name != "inventory_revision") {
            lua_pop(state, 1);
            return luaL_error(
                state,
                "sd.bots.use_consumable selector received an unknown field");
        }
    }

    multiplayer::BotUseConsumableRequest request;
    request.participant_id = participant_id;
    lua_getfield(state, selector_index, "potion_slot");
    if (!lua_isinteger(state, -1)) {
        lua_pop(state, 1);
        return luaL_error(
            state,
            "sd.bots.use_consumable potion_slot must be an integer");
    }
    request.potion_slot =
        static_cast<std::int32_t>(lua_tointeger(state, -1));
    lua_pop(state, 1);
    lua_getfield(
        state,
        selector_index,
        "inventory_revision");
    if (!lua_isinteger(state, -1) ||
        lua_tointeger(state, -1) < 0 ||
        static_cast<std::uint64_t>(
            lua_tointeger(state, -1)) >
            (std::numeric_limits<std::uint32_t>::max)()) {
        lua_pop(state, 1);
        return luaL_error(
            state,
            "sd.bots.use_consumable inventory_revision must be a uint32 integer");
    }
    request.inventory_revision =
        static_cast<std::uint32_t>(
            lua_tointeger(state, -1));
    lua_pop(state, 1);

    multiplayer::BotUseConsumableResult result;
    if (!multiplayer::UseParticipantConsumable(
            request,
            &result,
            &error_message)) {
        lua_pushboolean(state, 0);
        lua_pushlstring(
            state,
            error_message.data(),
            error_message.size());
        return 2;
    }

    lua_pushboolean(state, 1);
    lua_createtable(state, 0, 4);
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(result.use_id));
    lua_setfield(state, -2, "use_id");
    lua_pushinteger(state, result.inventory_revision);
    lua_setfield(state, -2, "inventory_revision");
    lua_pushinteger(state, result.stock_subtype);
    lua_setfield(state, -2, "stock_subtype");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(result.content_id));
    lua_setfield(state, -2, "content_id");
    return 2;
}
