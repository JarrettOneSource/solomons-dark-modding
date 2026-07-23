int LuaSpellsSelect(lua_State* state) {
    if (lua_gettop(state) > 2) {
        return luaL_error(
            state,
            "sd.spells.select accepts only a spell and optional belt slot");
    }
    const auto* definition = ResolveSelectableSpell(state, 1);
    if (definition == nullptr) {
        return luaL_error(
            state,
            "sd.spells.select could not resolve a registered spell");
    }

    std::int32_t secondary_slot = -1;
    if (definition->slot == LuaSpellSlot::Primary) {
        if (lua_gettop(state) == 2 && !lua_isnil(state, 2)) {
            return luaL_error(
                state,
                "sd.spells.select primary spells do not accept a belt slot");
        }
    } else {
        if (!lua_isinteger(state, 2)) {
            return luaL_error(
                state,
                "sd.spells.select secondary spells require belt slot 1 through 8");
        }
        const auto lua_slot = lua_tointeger(state, 2);
        if (lua_slot < 1 ||
            lua_slot > static_cast<lua_Integer>(
                kLuaRegisteredSpellSecondaryInputSlotCount)) {
            return luaL_error(
                state,
                "sd.spells.select secondary belt slot must be in the range 1 through 8");
        }
        secondary_slot = static_cast<std::int32_t>(lua_slot - 1);
    }

    std::string selection_error;
    if (!SelectLuaRegisteredSpellForInput(
            *definition,
            secondary_slot,
            &selection_error)) {
        return luaL_error(state, "%s", selection_error.c_str());
    }
    PushSelectedSpellDefinition(state, *definition, secondary_slot);
    return 1;
}

int LuaSpellsClearSelection(lua_State* state) {
    const auto* slot_name = luaL_checkstring(state, 1);
    if (std::string_view(slot_name) == "primary") {
        if (lua_gettop(state) > 2 ||
            (lua_gettop(state) == 2 && !lua_isnil(state, 2))) {
            return luaL_error(
                state,
                "sd.spells.clear_selection primary does not accept a belt slot");
        }
        lua_pushboolean(
            state,
            ClearLuaRegisteredSpellInputSelection(
                LuaSpellSlot::Primary,
                -1));
        return 1;
    }
    if (std::string_view(slot_name) != "secondary") {
        return luaL_error(
            state,
            "sd.spells.clear_selection slot must be primary or secondary");
    }
    if (lua_gettop(state) != 2 || !lua_isinteger(state, 2)) {
        return luaL_error(
            state,
            "sd.spells.clear_selection secondary requires belt slot 1 through 8");
    }
    const auto lua_slot = lua_tointeger(state, 2);
    if (lua_slot < 1 ||
        lua_slot > static_cast<lua_Integer>(
            kLuaRegisteredSpellSecondaryInputSlotCount)) {
        return luaL_error(
            state,
            "sd.spells.clear_selection secondary belt slot must be in the range 1 through 8");
    }
    lua_pushboolean(
        state,
        ClearLuaRegisteredSpellInputSelection(
            LuaSpellSlot::Secondary,
            static_cast<std::int32_t>(lua_slot - 1)));
    return 1;
}

int LuaSpellsGetSelection(lua_State* state) {
    lua_createtable(state, 0, 2);

    LuaRegisteredSpellInputSelection selection;
    if (TryGetSelectedLuaRegisteredPrimarySpell(&selection)) {
        const auto* definition =
            FindSpellDefinitionById(selection.content_id);
        if (definition != nullptr) {
            PushSelectedSpellDefinition(state, *definition, -1);
            lua_setfield(state, -2, "primary");
        }
    }

    lua_createtable(
        state,
        static_cast<int>(kLuaRegisteredSpellSecondaryInputSlotCount),
        0);
    for (std::size_t slot = 0;
         slot < kLuaRegisteredSpellSecondaryInputSlotCount;
         ++slot) {
        if (!TryGetSelectedLuaRegisteredSecondarySpell(slot, &selection)) {
            continue;
        }
        const auto* definition =
            FindSpellDefinitionById(selection.content_id);
        if (definition == nullptr) {
            continue;
        }
        PushSelectedSpellDefinition(
            state,
            *definition,
            static_cast<std::int32_t>(slot));
        lua_seti(state, -2, static_cast<lua_Integer>(slot + 1));
    }
    lua_setfield(state, -2, "secondary");
    return 1;
}

int LuaSpellsCast(lua_State* state) {
    auto* mod = GetLoadedLuaMod(state);
    if (mod == nullptr) {
        return luaL_error(state, "sd.spells.cast requires an owning Lua mod");
    }
    const LuaSpellDefinition* definition = nullptr;
    if (lua_type(state, 1) == LUA_TSTRING) {
        std::size_t key_length = 0;
        const auto* key = lua_tolstring(state, 1, &key_length);
        definition = FindOwnedSpellDefinitionByKey(
            *mod,
            std::string_view(key, key_length));
    } else if (lua_isinteger(state, 1) && lua_tointeger(state, 1) > 0) {
        definition = FindSpellDefinitionById(
            static_cast<std::uint64_t>(lua_tointeger(state, 1)));
        if (definition != nullptr &&
            definition->identity.mod_id != mod->descriptor.id) {
            definition = nullptr;
        }
    } else {
        return luaL_error(
            state,
            "sd.spells.cast expects an owned content key or content id");
    }
    if (definition == nullptr) {
        return luaL_error(state, "sd.spells.cast could not resolve an owned spell");
    }

    luaL_checktype(state, 2, LUA_TTABLE);
    RejectUnknownSpellCastOptions(state, 2);
    const auto requested_owner = ReadOptionalPositiveSpellCastInteger(
        state,
        2,
        "participant_id");
    const auto target_network_actor_id =
        ReadOptionalPositiveSpellCastInteger(
            state,
            2,
            "target_network_actor_id");
    const auto origin_x = ReadRequiredSpellCastCoordinate(
        state,
        2,
        "origin_x");
    const auto origin_y = ReadRequiredSpellCastCoordinate(
        state,
        2,
        "origin_y");
    const auto aim_x = ReadRequiredSpellCastCoordinate(state, 2, "aim_x");
    const auto aim_y = ReadRequiredSpellCastCoordinate(state, 2, "aim_y");

    std::uint64_t request_id = 0;
    std::uint64_t owner_participant_id = 0;
    bool local_owner = false;
    std::string cast_error;
    if (!multiplayer::QueueOwnerRoutedLuaRegisteredSpellCast(
            definition->identity.network_id,
            requested_owner,
            target_network_actor_id,
            origin_x,
            origin_y,
            aim_x,
            aim_y,
            &request_id,
            &owner_participant_id,
            &local_owner,
            &cast_error)) {
        return luaL_error(state, "%s", cast_error.c_str());
    }

    lua_createtable(state, 0, 4);
    lua_pushinteger(state, static_cast<lua_Integer>(request_id));
    lua_setfield(state, -2, "request_id");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(definition->identity.network_id));
    lua_setfield(state, -2, "content_id");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(owner_participant_id));
    lua_setfield(state, -2, "owner_participant_id");
    lua_pushboolean(state, local_owner ? 1 : 0);
    lua_setfield(state, -2, "local_owner");
    return 1;
}

int LuaSpellsGetEffects(lua_State* state) {
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    std::vector<LuaRegisteredSpellEffectState> local_effects;
    for (const auto& loaded_mod : LoadedLuaModsStorage()) {
        if (loaded_mod == nullptr) {
            continue;
        }
        for (const auto& effect : loaded_mod->spell_effects) {
            LuaRegisteredSpellEffectState state_value;
            state_value.owner_participant_id = effect.owner_participant_id;
            state_value.cast_request_id = effect.cast_request_id;
            state_value.content_id = effect.content_id;
            state_value.effect_id = effect.effect_id;
            state_value.key = effect.key;
            state_value.x = effect.x;
            state_value.y = effect.y;
            state_value.velocity_x = effect.velocity_x;
            state_value.velocity_y = effect.velocity_y;
            state_value.radius = effect.radius;
            state_value.age_ms = static_cast<std::uint32_t>((std::min)(
                now_ms > effect.created_ms ? now_ms - effect.created_ms : 0,
                std::uint64_t{0xFFFFFFFFu}));
            state_value.remaining_ms = static_cast<std::uint32_t>((std::min)(
                effect.expires_ms > now_ms ? effect.expires_ms - now_ms : 0,
                std::uint64_t{0xFFFFFFFFu}));
            state_value.data = effect.data;
            local_effects.push_back(std::move(state_value));
        }
    }
    auto replicated_effects =
        multiplayer::SnapshotReplicatedLuaRegisteredSpellEffects();
    lua_createtable(
        state,
        static_cast<int>(local_effects.size() + replicated_effects.size()),
        0);
    lua_Integer output_index = 1;
    for (const auto& effect : local_effects) {
        PushSpellEffectState(state, effect, true);
        lua_seti(state, -2, output_index++);
    }
    for (const auto& effect : replicated_effects) {
        PushSpellEffectState(state, effect, false);
        lua_seti(state, -2, output_index++);
    }
    return 1;
}
