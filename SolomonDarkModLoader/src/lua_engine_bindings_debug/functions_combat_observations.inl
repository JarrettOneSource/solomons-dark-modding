// sd.debug.reset_local_cast_observation(network_actor_id) -> boolean
int LuaDebugResetLocalCastObservation(lua_State* state) {
    const auto network_actor_id =
        CheckLuaUnsignedInteger<std::uint64_t>(state, 1, "network_actor_id");
    if (network_actor_id == 0) {
        lua_pushboolean(state, 0);
        return 1;
    }

    const bool armed = ResetLocalPlayerManaDeltaObservation();
    if (armed) {
        multiplayer::ResetLocalEnemyDamageClaimObservation(network_actor_id);
    }
    lua_pushboolean(state, armed ? 1 : 0);
    return 1;
}

// sd.debug.get_local_cast_observation(network_actor_id) -> table
int LuaDebugGetLocalCastObservation(lua_State* state) {
    const auto network_actor_id =
        CheckLuaUnsignedInteger<std::uint64_t>(state, 1, "network_actor_id");

    SDModLocalManaDeltaObservation mana;
    const bool mana_valid = TakeLocalPlayerManaDeltaObservation(&mana);
    multiplayer::LocalEnemyDamageClaimObservation damage;
    const bool damage_valid =
        multiplayer::TakeLocalEnemyDamageClaimObservation(
            network_actor_id,
            &damage);

    lua_createtable(state, 0, 20);
    lua_pushboolean(state, mana_valid ? 1 : 0);
    lua_setfield(state, -2, "mana_valid");
    lua_pushinteger(state, static_cast<lua_Integer>(mana.actor_address));
    lua_setfield(state, -2, "mana_actor_address");
    lua_pushinteger(state, static_cast<lua_Integer>(mana.call_count));
    lua_setfield(state, -2, "mana_call_count");
    lua_pushinteger(state, static_cast<lua_Integer>(mana.spend_call_count));
    lua_setfield(state, -2, "mana_spend_call_count");
    lua_pushinteger(state, static_cast<lua_Integer>(mana.recovery_call_count));
    lua_setfield(state, -2, "mana_recovery_call_count");
    lua_pushnumber(state, static_cast<lua_Number>(mana.spent_total));
    lua_setfield(state, -2, "mana_spent_total");
    lua_pushnumber(state, static_cast<lua_Number>(mana.recovered_total));
    lua_setfield(state, -2, "mana_recovered_total");
    lua_pushnumber(state, static_cast<lua_Number>(mana.last_delta));
    lua_setfield(state, -2, "mana_last_delta");

    lua_pushboolean(state, damage_valid ? 1 : 0);
    lua_setfield(state, -2, "damage_claim_valid");
    lua_pushinteger(state, static_cast<lua_Integer>(damage.claim_count));
    lua_setfield(state, -2, "damage_claim_count");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(damage.associated_claim_count));
    lua_setfield(state, -2, "damage_associated_claim_count");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(damage.unassociated_claim_count));
    lua_setfield(state, -2, "damage_unassociated_claim_count");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(damage.associated_skill_id));
    lua_setfield(state, -2, "damage_associated_skill_id");
    lua_pushboolean(state, damage.associated_skill_consistent ? 1 : 0);
    lua_setfield(state, -2, "damage_associated_skill_consistent");
    lua_pushnumber(state, static_cast<lua_Number>(damage.claimed_damage_total));
    lua_setfield(state, -2, "damage_claimed_total");
    lua_pushnumber(state, static_cast<lua_Number>(damage.minimum_claimed_damage));
    lua_setfield(state, -2, "damage_claimed_minimum");
    lua_pushnumber(state, static_cast<lua_Number>(damage.maximum_claimed_damage));
    lua_setfield(state, -2, "damage_claimed_maximum");
    lua_pushinteger(state, static_cast<lua_Integer>(damage.sample_count));
    lua_setfield(state, -2, "damage_claim_sample_count");
    lua_createtable(state, static_cast<int>(damage.sample_count), 0);
    for (std::size_t index = 0; index < damage.sample_count; ++index) {
        lua_pushnumber(
            state,
            static_cast<lua_Number>(damage.claimed_damage_samples[index]));
        lua_rawseti(state, -2, static_cast<lua_Integer>(index + 1));
    }
    lua_setfield(state, -2, "damage_claim_samples");
    return 1;
}

// sd.debug.get_actor_modifiers(actor_address) -> array|nil
int LuaDebugGetActorModifiers(lua_State* state) {
    const auto actor_address =
        CheckLuaUnsignedInteger<uintptr_t>(state, 1, "actor_address");
    std::vector<SDModNativeModifierState> modifiers;
    if (!TryListNativeActorModifiers(actor_address, &modifiers)) {
        lua_pushnil(state);
        return 1;
    }

    lua_createtable(state, static_cast<int>(modifiers.size()), 0);
    for (std::size_t index = 0; index < modifiers.size(); ++index) {
        lua_createtable(state, 0, 2);
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(modifiers[index].type_id));
        lua_setfield(state, -2, "type_id");
        lua_pushinteger(
            state,
            static_cast<lua_Integer>(modifiers[index].duration_ticks));
        lua_setfield(state, -2, "duration_ticks");
        lua_rawseti(state, -2, static_cast<lua_Integer>(index + 1));
    }
    return 1;
}
