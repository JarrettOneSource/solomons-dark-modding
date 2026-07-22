bool ReadOptionalLuaIntegerField(
    lua_State* state,
    int table_index,
    const char* field_name,
    lua_Integer* value) {
    lua_getfield(state, table_index, field_name);
    if (lua_isnil(state, -1)) {
        lua_pop(state, 1);
        return false;
    }
    if (!lua_isinteger(state, -1) && !lua_isnumber(state, -1)) {
        lua_pop(state, 1);
        return false;
    }
    *value = lua_tointeger(state, -1);
    lua_pop(state, 1);
    return true;
}

int LuaRuntimeChooseLevelUpOption(lua_State* state) {
    std::uint64_t offer_id = 0;
    std::int32_t option_index = -1;
    std::int32_t option_id = -1;
    if (lua_istable(state, 1)) {
        lua_Integer value = 0;
        if (ReadOptionalLuaIntegerField(state, 1, "offer_id", &value)) {
            if (value < 0) {
                return luaL_error(state, "sd.runtime.choose_level_up_option offer_id must be non-negative");
            }
            offer_id = static_cast<std::uint64_t>(value);
        }
        if (ReadOptionalLuaIntegerField(state, 1, "option_index", &value) ||
            ReadOptionalLuaIntegerField(state, 1, "index", &value)) {
            option_index = static_cast<std::int32_t>(value);
        }
        if (ReadOptionalLuaIntegerField(state, 1, "option_id", &value) ||
            ReadOptionalLuaIntegerField(state, 1, "choice_id", &value) ||
            ReadOptionalLuaIntegerField(state, 1, "id", &value)) {
            option_id = static_cast<std::int32_t>(value);
        }
    } else {
        if (!lua_isinteger(state, 1) && !lua_isnumber(state, 1)) {
            return luaL_error(state, "sd.runtime.choose_level_up_option expects option_index or a table");
        }
        option_index = static_cast<std::int32_t>(lua_tointeger(state, 1));
        if (lua_gettop(state) >= 2 && !lua_isnil(state, 2)) {
            if (!lua_isinteger(state, 2) && !lua_isnumber(state, 2)) {
                return luaL_error(state, "sd.runtime.choose_level_up_option offer_id must be an integer");
            }
            const auto value = lua_tointeger(state, 2);
            if (value < 0) {
                return luaL_error(state, "sd.runtime.choose_level_up_option offer_id must be non-negative");
            }
            offer_id = static_cast<std::uint64_t>(value);
        }
        if (lua_gettop(state) >= 3 && !lua_isnil(state, 3)) {
            if (!lua_isinteger(state, 3) && !lua_isnumber(state, 3)) {
                return luaL_error(state, "sd.runtime.choose_level_up_option option_id must be an integer");
            }
            option_id = static_cast<std::int32_t>(lua_tointeger(state, 3));
        }
    }

    if (option_index <= 0 && option_id < 0) {
        return luaL_error(state, "sd.runtime.choose_level_up_option requires option_index or option_id");
    }

    std::string error_message;
    if (!multiplayer::QueueLocalLevelUpChoice(
            offer_id,
            option_index,
            option_id,
            &error_message)) {
        return luaL_error(state, "%s", error_message.c_str());
    }

    lua_pushboolean(state, 1);
    return 1;
}

int LuaRuntimeDebugPublishLevelUpOffer(lua_State* state) {
    lua_Integer level = 0;
    lua_Integer experience = 0;
    lua_Integer target_participant_id = 0;
    lua_Integer option_id = -1;
    lua_Integer apply_count = 1;
    bool target_self = false;
    bool has_target_participant_id = false;
    bool has_option_id = false;
    if (lua_istable(state, 1)) {
        if (!ReadOptionalLuaIntegerField(state, 1, "level", &level)) {
            return luaL_error(state, "sd.runtime.debug_publish_level_up_offer table requires level");
        }
        if (!ReadOptionalLuaIntegerField(state, 1, "experience", &experience) &&
            !ReadOptionalLuaIntegerField(state, 1, "xp", &experience)) {
            return luaL_error(state, "sd.runtime.debug_publish_level_up_offer table requires experience");
        }
        lua_getfield(state, 1, "target_self");
        if (!lua_isnil(state, -1)) {
            target_self = lua_toboolean(state, -1) != 0;
        }
        lua_pop(state, 1);
        has_target_participant_id = ReadOptionalLuaIntegerField(
            state,
            1,
            "target_participant_id",
            &target_participant_id);
        has_option_id =
            ReadOptionalLuaIntegerField(state, 1, "option_id", &option_id) ||
            ReadOptionalLuaIntegerField(state, 1, "id", &option_id);
        (void)ReadOptionalLuaIntegerField(state, 1, "apply_count", &apply_count);
    } else {
        if ((!lua_isinteger(state, 1) && !lua_isnumber(state, 1)) ||
            (!lua_isinteger(state, 2) && !lua_isnumber(state, 2))) {
            return luaL_error(state, "sd.runtime.debug_publish_level_up_offer expects (level, experience)");
        }
        level = lua_tointeger(state, 1);
        experience = lua_tointeger(state, 2);
    }
    if (level <= 0) {
        return luaL_error(state, "sd.runtime.debug_publish_level_up_offer level must be positive");
    }
    if (experience < 0) {
        return luaL_error(state, "sd.runtime.debug_publish_level_up_offer experience must be non-negative");
    }
    if (!multiplayer::IsLocalTransportHost()) {
        return luaL_error(state, "sd.runtime.debug_publish_level_up_offer requires the local transport host");
    }

    if (has_option_id) {
        if (option_id < 0) {
            return luaL_error(state, "sd.runtime.debug_publish_level_up_offer option_id must be non-negative");
        }
        if (apply_count <= 0 || apply_count > 2) {
            return luaL_error(state, "sd.runtime.debug_publish_level_up_offer apply_count must be 1 or 2");
        }
        if (target_self && has_target_participant_id &&
            static_cast<std::uint64_t>(target_participant_id) !=
                multiplayer::GetLocalTransportParticipantId()) {
            return luaL_error(state, "sd.runtime.debug_publish_level_up_offer target_self conflicts with target_participant_id");
        }
        if (!target_self &&
            (!has_target_participant_id || target_participant_id <= 0)) {
            return luaL_error(state, "sd.runtime.debug_publish_level_up_offer deterministic option requires target_self or target_participant_id");
        }
        const auto target_id = target_self
            ? multiplayer::GetLocalTransportParticipantId()
            : static_cast<std::uint64_t>(target_participant_id);
        std::string error_message;
        if (!multiplayer::DebugPublishHostLevelUpOffer(
                target_id,
                static_cast<std::int32_t>(level),
                static_cast<std::int32_t>(experience),
                static_cast<std::int32_t>(option_id),
                static_cast<std::int32_t>(apply_count),
                &error_message)) {
            return luaL_error(state, "%s", error_message.c_str());
        }
        lua_pushboolean(state, 1);
        return 1;
    }

    if (target_self || has_target_participant_id) {
        if (!target_self && target_participant_id <= 0) {
            return luaL_error(state, "sd.runtime.debug_publish_level_up_offer target must be positive");
        }
        const auto target_id = target_self
            ? multiplayer::GetLocalTransportParticipantId()
            : static_cast<std::uint64_t>(target_participant_id);
        std::string error_message;
        if (!multiplayer::DebugPublishHostNaturalLevelUpOffer(
                target_id,
                static_cast<std::int32_t>(level),
                static_cast<std::int32_t>(experience),
                &error_message)) {
            return luaL_error(state, "%s", error_message.c_str());
        }
    } else {
        multiplayer::PublishHostLevelUpBarrierOffers(
            static_cast<std::int32_t>(level),
            static_cast<std::int32_t>(experience),
            0);
    }
    lua_pushboolean(state, 1);
    return 1;
}

int LuaRuntimeHasCapability(lua_State* state) {
    const auto* mod = GetLoadedLuaMod(state);
    const auto* capability = luaL_checkstring(state, 1);
    if (mod == nullptr || capability == nullptr) {
        lua_pushboolean(state, 0);
        return 1;
    }

    const auto capability_name = std::string(capability);
    const auto found = std::find(mod->capabilities.begin(), mod->capabilities.end(), capability_name);
    lua_pushboolean(state, found != mod->capabilities.end() ? 1 : 0);
    return 1;
}

int LuaRuntimeGetCapabilities(lua_State* state) {
    const auto* mod = GetLoadedLuaMod(state);
    if (mod == nullptr) {
        lua_newtable(state);
        return 1;
    }

    lua_createtable(state, static_cast<int>(mod->capabilities.size()), 0);
    for (std::size_t index = 0; index < mod->capabilities.size(); ++index) {
        lua_pushstring(state, mod->capabilities[index].c_str());
        lua_rawseti(state, -2, static_cast<lua_Integer>(index + 1));
    }
    return 1;
}

int LuaRuntimeGetEnvironmentVariable(lua_State* state) {
    const auto* variable_name = luaL_checkstring(state, 1);
    if (variable_name == nullptr || *variable_name == '\0') {
        lua_pushnil(state);
        return 1;
    }

    char* value = nullptr;
    std::size_t value_length = 0;
    if (_dupenv_s(&value, &value_length, variable_name) != 0 || value == nullptr) {
        lua_pushnil(state);
        return 1;
    }

    lua_pushstring(state, value);
    free(value);
    return 1;
}

bool IsSafeRelativeModPath(const std::filesystem::path& path) {
    if (path.empty() || path.is_absolute() || path.has_root_name() || path.has_root_directory()) {
        return false;
    }

    for (const auto& component : path) {
        if (component == "..") {
            return false;
        }
    }

    return true;
}

int LuaRuntimeGetModTextFile(lua_State* state) {
    const auto* mod = GetLoadedLuaMod(state);
    const auto* relative_path_text = luaL_checkstring(state, 1);
    if (mod == nullptr || relative_path_text == nullptr || *relative_path_text == '\0') {
        lua_pushnil(state);
        return 1;
    }

    const std::filesystem::path relative_path(relative_path_text);
    if (!IsSafeRelativeModPath(relative_path)) {
        lua_pushnil(state);
        return 1;
    }

    const auto file_path = (mod->descriptor.root_path / relative_path).lexically_normal();
    std::ifstream stream(file_path, std::ios::binary);
    if (!stream) {
        lua_pushnil(state);
        return 1;
    }

    std::string contents((std::istreambuf_iterator<char>(stream)), std::istreambuf_iterator<char>());
    lua_pushlstring(state, contents.data(), contents.size());
    return 1;
}

bool IsSupportedLuaEventName(std::string_view event_name) {
    return IsBuiltInLuaEventName(event_name) ||
           IsValidCustomLuaEventName(event_name);
}

void MarkLuaEventRegistered(LoadedLuaMod* mod, std::string_view event_name) {
    if (mod == nullptr) {
        return;
    }

    if (event_name == kRuntimeTickEventName) {
        mod->runtime_tick_registered = true;
    } else if (event_name == kRunStartedEventName) {
        mod->run_started_registered = true;
    } else if (event_name == kRunEndedEventName) {
        mod->run_ended_registered = true;
    } else if (event_name == kWaveStartedEventName) {
        mod->wave_started_registered = true;
    } else if (event_name == kWaveCompletedEventName) {
        mod->wave_completed_registered = true;
    } else if (event_name == kEnemyDeathEventName) {
        mod->enemy_death_registered = true;
    } else if (event_name == kEnemySpawnedEventName) {
        mod->enemy_spawned_registered = true;
    } else if (event_name == kSpellCastEventName) {
        mod->spell_cast_registered = true;
    } else if (event_name == kGoldChangedEventName) {
        mod->gold_changed_registered = true;
    } else if (event_name == kDropSpawnedEventName) {
        mod->drop_spawned_registered = true;
    } else if (event_name == kLevelUpEventName) {
        mod->level_up_registered = true;
    }
}

int LuaEventsOn(lua_State* state) {
    auto* mod = GetLoadedLuaMod(state);
    const auto* event_name = luaL_checkstring(state, 1);
    luaL_checktype(state, 2, LUA_TFUNCTION);
    if (mod == nullptr || event_name == nullptr) {
        return luaL_error(state, "sd.events.on is unavailable");
    }

    const std::string_view event_name_view(event_name);
    if (!IsSupportedLuaEventName(event_name_view)) {
        return luaL_error(state, "unsupported event: %s", event_name);
    }

    lua_getfield(state, LUA_REGISTRYINDEX, kLuaEventHandlersRegistryKey);
    if (!lua_istable(state, -1)) {
        lua_pop(state, 1);
        return luaL_error(state, "event registry is unavailable");
    }

    lua_getfield(state, -1, event_name);
    if (!lua_istable(state, -1)) {
        lua_pop(state, 1);
        lua_createtable(state, 0, 0);
        lua_pushvalue(state, -1);
        lua_setfield(state, -3, event_name);
    }

    const auto next_index = lua_rawlen(state, -1) + 1;
    lua_pushvalue(state, 2);
    lua_rawseti(state, -2, static_cast<lua_Integer>(next_index));
    lua_pop(state, 2);

    MarkLuaEventRegistered(mod, event_name_view);
    lua_pushboolean(state, 1);
    return 1;
}

}  // namespace

void RegisterLuaRuntimeBindings(lua_State* state) {
    lua_createtable(state, 0, 9);
    RegisterFunction(state, &LuaRuntimeGetMod, "get_mod");
    RegisterFunction(state, &LuaRuntimeGetMultiplayerState, "get_multiplayer_state");
    RegisterFunction(state, &LuaRuntimeGetFrameState, "get_frame_state");
    RegisterFunction(state, &LuaRuntimeChooseLevelUpOption, "choose_level_up_option");
    RegisterFunction(state, &LuaRuntimeDebugPublishLevelUpOffer, "debug_publish_level_up_offer");
    RegisterFunction(state, &LuaRuntimeHasCapability, "has_capability");
    RegisterFunction(state, &LuaRuntimeGetCapabilities, "get_capabilities");
    RegisterFunction(state, &LuaRuntimeGetEnvironmentVariable, "get_environment_variable");
    RegisterFunction(state, &LuaRuntimeGetModTextFile, "get_mod_text_file");
    lua_setfield(state, -2, "runtime");
}

void RegisterLuaEventBindings(lua_State* state) {
    lua_createtable(state, 0, 2);
    RegisterFunction(state, &LuaEventsOn, "on");
    RegisterLuaEventBroadcastBinding(state);
    lua_setfield(state, -2, "events");
}

}  // namespace sdmod::detail
