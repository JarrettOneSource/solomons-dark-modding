int PushBotOperationError(
    lua_State* state,
    bool nil_result,
    const std::string& error_message) {
    if (nil_result) {
        lua_pushnil(state);
    } else {
        lua_pushboolean(state, 0);
    }
    lua_pushlstring(
        state,
        error_message.data(),
        error_message.size());
    return 2;
}

bool ReadBotHandleId(
    lua_State* state,
    int index,
    std::uint64_t* participant_id,
    std::string* error_message) {
    if (participant_id == nullptr ||
        error_message == nullptr ||
        !lua_istable(state, index)) {
        if (error_message != nullptr) {
            *error_message =
                "bot method receiver must be a bot handle";
        }
        return false;
    }

    const auto table_index =
        lua_absindex(state, index);
    lua_getfield(
        state,
        table_index,
        "_participant_id");
    if (!lua_isinteger(state, -1)) {
        lua_pop(state, 1);
        *error_message =
            "bot handle participant id is unavailable";
        return false;
    }
    const auto value =
        static_cast<std::int64_t>(
            lua_tointeger(state, -1));
    lua_pop(state, 1);
    if (value <= 0) {
        *error_message =
            "bot handle participant id is invalid";
        return false;
    }
    *participant_id =
        static_cast<std::uint64_t>(value);
    return true;
}

bool ReadBotHandleSnapshot(
    lua_State* state,
    std::uint64_t* participant_id,
    multiplayer::BotSnapshot* snapshot,
    std::string* error_message) {
    if (!ReadBotHandleId(
            state,
            1,
            participant_id,
            error_message)) {
        return false;
    }
    if (!multiplayer::ReadBotSnapshot(
            *participant_id,
            snapshot)) {
        *error_message =
            "the bot handle is stale";
        return false;
    }
    return true;
}

bool IsBotMutationAuthorized(
    std::string* error_message) {
    if (multiplayer::IsLocalTransportClient()) {
        if (error_message != nullptr) {
            *error_message =
                "only the multiplayer host can control bots";
        }
        return false;
    }
    return true;
}

int LuaBotHandleDespawn(lua_State* state) {
    std::uint64_t participant_id = 0;
    multiplayer::BotSnapshot snapshot;
    std::string error_message;
    if (!IsBotMutationAuthorized(&error_message) ||
        !ReadBotHandleSnapshot(
            state,
            &participant_id,
            &snapshot,
            &error_message)) {
        return PushBotOperationError(
            state,
            false,
            error_message);
    }
    if (!multiplayer::DestroyBot(participant_id)) {
        return PushBotOperationError(
            state,
            false,
            "the bot could not be despawned");
    }
    lua_pushboolean(state, 1);
    return 1;
}

int LuaBotHandleMoveTo(lua_State* state) {
    std::uint64_t participant_id = 0;
    multiplayer::BotSnapshot snapshot;
    std::string error_message;
    if (!IsBotMutationAuthorized(&error_message) ||
        !ReadBotHandleSnapshot(
            state,
            &participant_id,
            &snapshot,
            &error_message)) {
        return PushBotOperationError(
            state,
            false,
            error_message);
    }
    if (!lua_isnumber(state, 2) ||
        !lua_isnumber(state, 3)) {
        return PushBotOperationError(
            state,
            false,
            "bot:move_to expects x and y numbers");
    }

    multiplayer::BotMoveToRequest request;
    request.bot_id = participant_id;
    request.target_x = static_cast<float>(
        lua_tonumber(state, 2));
    request.target_y = static_cast<float>(
        lua_tonumber(state, 3));
    if (!multiplayer::MoveBotTo(request)) {
        return PushBotOperationError(
            state,
            false,
            "the bot movement request was rejected");
    }
    lua_pushboolean(state, 1);
    return 1;
}

int LuaBotHandleStop(lua_State* state) {
    std::uint64_t participant_id = 0;
    multiplayer::BotSnapshot snapshot;
    std::string error_message;
    if (!IsBotMutationAuthorized(&error_message) ||
        !ReadBotHandleSnapshot(
            state,
            &participant_id,
            &snapshot,
            &error_message)) {
        return PushBotOperationError(
            state,
            false,
            error_message);
    }
    if (!multiplayer::StopBot(participant_id)) {
        return PushBotOperationError(
            state,
            false,
            "the bot stop request was rejected");
    }
    lua_pushboolean(state, 1);
    return 1;
}

int LuaBotHandleCast(lua_State* state) {
    std::uint64_t participant_id = 0;
    multiplayer::BotSnapshot snapshot;
    std::string error_message;
    if (!IsBotMutationAuthorized(&error_message) ||
        !ReadBotHandleSnapshot(
            state,
            &participant_id,
            &snapshot,
            &error_message)) {
        return PushBotOperationError(
            state,
            false,
            error_message);
    }
    if ((!lua_isinteger(state, 2) &&
         !lua_isnumber(state, 2)) ||
        !lua_isnumber(state, 3) ||
        !lua_isnumber(state, 4)) {
        return PushBotOperationError(
            state,
            false,
            "bot:cast expects skill_slot, target_x, target_y[, hold_ms]");
    }
    const auto skill_slot =
        static_cast<std::int32_t>(
            lua_tointeger(state, 2));
    const auto target_x =
        static_cast<float>(
            lua_tonumber(state, 3));
    const auto target_y =
        static_cast<float>(
            lua_tonumber(state, 4));
    std::uint32_t hold_ms = 80;
    if (lua_gettop(state) >= 5 &&
        !lua_isnil(state, 5)) {
        if (!lua_isinteger(state, 5) &&
            !lua_isnumber(state, 5)) {
            return PushBotOperationError(
                state,
                false,
                "bot:cast hold_ms must be an integer");
        }
        const auto hold_value =
            static_cast<std::int64_t>(
                lua_tointeger(state, 5));
        if (hold_value < 0 ||
            hold_value > 5000) {
            return PushBotOperationError(
                state,
                false,
                "bot:cast hold_ms must be between 0 and 5000");
        }
        hold_ms =
            static_cast<std::uint32_t>(hold_value);
    }

    if (!multiplayer::QueueSyntheticParticipantCast(
            participant_id,
            skill_slot,
            target_x,
            target_y,
            hold_ms,
            &error_message)) {
        if (error_message.empty()) {
            error_message =
                "the bot cast was rejected";
        }
        return PushBotOperationError(
            state,
            false,
            error_message);
    }
    lua_pushboolean(state, 1);
    return 1;
}

int LuaBotHandlePosition(lua_State* state) {
    std::uint64_t participant_id = 0;
    multiplayer::BotSnapshot snapshot;
    std::string error_message;
    if (!ReadBotHandleSnapshot(
            state,
            &participant_id,
            &snapshot,
            &error_message)) {
        return PushBotOperationError(
            state,
            true,
            error_message);
    }
    if (!snapshot.transform_valid ||
        !std::isfinite(snapshot.position_x) ||
        !std::isfinite(snapshot.position_y)) {
        return PushBotOperationError(
            state,
            true,
            "the bot position is not available yet");
    }
    lua_pushnumber(
        state,
        snapshot.position_x);
    lua_pushnumber(
        state,
        snapshot.position_y);
    return 2;
}

int LuaBotHandleHp(lua_State* state) {
    std::uint64_t participant_id = 0;
    multiplayer::BotSnapshot snapshot;
    std::string error_message;
    if (!ReadBotHandleSnapshot(
            state,
            &participant_id,
            &snapshot,
            &error_message) ||
        !snapshot.runtime_valid ||
        !std::isfinite(snapshot.hp)) {
        if (error_message.empty()) {
            error_message =
                "the bot HP is not available yet";
        }
        return PushBotOperationError(
            state,
            true,
            error_message);
    }
    lua_pushnumber(state, snapshot.hp);
    return 1;
}

int LuaBotHandleMaxHp(lua_State* state) {
    std::uint64_t participant_id = 0;
    multiplayer::BotSnapshot snapshot;
    std::string error_message;
    if (!ReadBotHandleSnapshot(
            state,
            &participant_id,
            &snapshot,
            &error_message) ||
        !snapshot.runtime_valid ||
        !std::isfinite(snapshot.max_hp) ||
        snapshot.max_hp <= 0.0f) {
        if (error_message.empty()) {
            error_message =
                "the bot maximum HP is not available yet";
        }
        return PushBotOperationError(
            state,
            true,
            error_message);
    }
    lua_pushnumber(state, snapshot.max_hp);
    return 1;
}

int LuaBotHandleAlive(lua_State* state) {
    std::uint64_t participant_id = 0;
    multiplayer::BotSnapshot snapshot;
    std::string error_message;
    if (!ReadBotHandleSnapshot(
            state,
            &participant_id,
            &snapshot,
            &error_message)) {
        return PushBotOperationError(
            state,
            true,
            error_message);
    }
    lua_pushboolean(
        state,
        snapshot.runtime_valid &&
                snapshot.entity_materialized &&
                snapshot.max_hp > 0.0f &&
                snapshot.hp > 0.0f
            ? 1
            : 0);
    return 1;
}

int LuaBotHandleSlot(lua_State* state) {
    std::uint64_t participant_id = 0;
    multiplayer::BotSnapshot snapshot;
    std::string error_message;
    if (!ReadBotHandleSnapshot(
            state,
            &participant_id,
            &snapshot,
            &error_message)) {
        return PushBotOperationError(
            state,
            true,
            error_message);
    }
    if (!snapshot.entity_materialized ||
        snapshot.gameplay_slot < 1 ||
        snapshot.gameplay_slot > 3) {
        lua_pushnil(state);
        return 1;
    }
    lua_pushinteger(
        state,
        snapshot.gameplay_slot);
    return 1;
}

int LuaBotHandleParticipantId(lua_State* state) {
    std::uint64_t participant_id = 0;
    std::string error_message;
    if (!ReadBotHandleId(
            state,
            1,
            &participant_id,
            &error_message)) {
        return PushBotOperationError(
            state,
            true,
            error_message);
    }
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(
            participant_id));
    return 1;
}

void PushBotHandle(
    lua_State* state,
    std::uint64_t participant_id) {
    lua_createtable(state, 0, 10);
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(
            participant_id));
    lua_setfield(
        state,
        -2,
        "_participant_id");
    RegisterFunction(
        state,
        &LuaBotHandleDespawn,
        "despawn");
    RegisterFunction(
        state,
        &LuaBotHandleMoveTo,
        "move_to");
    RegisterFunction(
        state,
        &LuaBotHandleStop,
        "stop");
    RegisterFunction(
        state,
        &LuaBotHandleCast,
        "cast");
    RegisterFunction(
        state,
        &LuaBotHandlePosition,
        "position");
    RegisterFunction(
        state,
        &LuaBotHandleHp,
        "hp");
    RegisterFunction(
        state,
        &LuaBotHandleMaxHp,
        "max_hp");
    RegisterFunction(
        state,
        &LuaBotHandleAlive,
        "alive");
    RegisterFunction(
        state,
        &LuaBotHandleSlot,
        "slot");
    RegisterFunction(
        state,
        &LuaBotHandleParticipantId,
        "participant_id");
}

int LuaBotsSpawn(lua_State* state) {
    if (!lua_istable(state, 1)) {
        return PushBotOperationError(
            state,
            true,
            "sd.bots.spawn expects a table");
    }
    std::string error_message;
    if (!IsBotMutationAuthorized(&error_message)) {
        return PushBotOperationError(
            state,
            true,
            error_message);
    }

    const auto table_index =
        lua_absindex(state, 1);
    lua_getfield(state, table_index, "name");
    if (!lua_isstring(state, -1)) {
        lua_pop(state, 1);
        return PushBotOperationError(
            state,
            true,
            "sd.bots.spawn requires a name");
    }
    std::size_t name_size = 0;
    const auto* name =
        lua_tolstring(state, -1, &name_size);
    std::string display_name(
        name != nullptr ? name : "",
        name_size);
    lua_pop(state, 1);
    if (display_name.empty() ||
        display_name.size() >=
            multiplayer::kParticipantDisplayNameBytes) {
        return PushBotOperationError(
            state,
            true,
            "bot name must contain 1 to 31 bytes");
    }

    lua_getfield(state, table_index, "class");
    if (!lua_isstring(state, -1)) {
        lua_pop(state, 1);
        return PushBotOperationError(
            state,
            true,
            "sd.bots.spawn requires a class");
    }
    const auto* class_name =
        lua_tostring(state, -1);
    const std::string class_text =
        class_name != nullptr ? class_name : "";
    lua_pop(state, 1);
    int element_id = -1;
    if (class_text == "fire") {
        element_id = 0;
    } else if (class_text == "water") {
        element_id = 1;
    } else if (class_text == "earth") {
        element_id = 2;
    } else if (class_text == "air") {
        element_id = 3;
    } else if (class_text == "ether") {
        element_id = 4;
    } else {
        return PushBotOperationError(
            state,
            true,
            "bot class must be fire, water, earth, air, or ether");
    }

    auto discipline_id =
        multiplayer::CharacterDisciplineId::Arcane;
    lua_getfield(state, table_index, "discipline");
    if (!lua_isnil(state, -1)) {
        if (!lua_isstring(state, -1)) {
            lua_pop(state, 1);
            return PushBotOperationError(
                state,
                true,
                "bot discipline must be mind, body, or arcane");
        }
        const auto* discipline_name =
            lua_tostring(state, -1);
        const std::string discipline_text =
            discipline_name != nullptr ? discipline_name : "";
        if (discipline_text == "mind") {
            discipline_id =
                multiplayer::CharacterDisciplineId::Mind;
        } else if (discipline_text == "body") {
            discipline_id =
                multiplayer::CharacterDisciplineId::Body;
        } else if (discipline_text != "arcane") {
            lua_pop(state, 1);
            return PushBotOperationError(
                state,
                true,
                "bot discipline must be mind, body, or arcane");
        }
    }
    lua_pop(state, 1);

    multiplayer::BotCreateRequest request;
    request.display_name = display_name;
    request.ready = true;
    request.character_profile =
        multiplayer::DefaultCharacterProfile();
    request.character_profile.element_id =
        element_id;
    request.character_profile.discipline_id =
        discipline_id;
    request.character_profile.level = 1;
    const auto primary_entry =
        ResolveNativePrimaryEntryForElement(
            element_id);
    request.character_profile.loadout
        .primary_entry_index = primary_entry;
    request.character_profile.loadout
        .primary_combo_entry_index = primary_entry;

    std::uint64_t participant_id = 0;
    if (!multiplayer::CreateBot(
            request,
            &participant_id,
            &error_message) ||
        participant_id == 0) {
        if (error_message.empty()) {
            error_message =
                "the bot could not claim a multiplayer participant slot";
        }
        return PushBotOperationError(
            state,
            true,
            error_message);
    }
    PushBotHandle(state, participant_id);
    return 1;
}

int LuaBotsList(lua_State* state) {
    const auto runtime =
        multiplayer::SnapshotRuntimeState();
    std::vector<std::uint64_t> participant_ids;
    for (const auto& participant :
         runtime.participants) {
        if (multiplayer::IsLuaControlledParticipant(
                participant)) {
            participant_ids.push_back(
                participant.participant_id);
        }
    }
    std::sort(
        participant_ids.begin(),
        participant_ids.end());
    lua_createtable(
        state,
        static_cast<int>(
            participant_ids.size()),
        0);
    for (std::size_t index = 0;
         index < participant_ids.size();
         ++index) {
        PushBotHandle(
            state,
            participant_ids[index]);
        lua_rawseti(
            state,
            -2,
            static_cast<lua_Integer>(
                index + 1));
    }
    return 1;
}
