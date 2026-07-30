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

    lua_createtable(state, 0, 30);
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
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(damage.native_contact_count));
    lua_setfield(state, -2, "damage_native_contact_count");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(damage.native_contact_skill_id));
    lua_setfield(state, -2, "damage_native_contact_skill_id");
    lua_pushboolean(
        state,
        damage.native_contact_skill_consistent ? 1 : 0);
    lua_setfield(
        state,
        -2,
        "damage_native_contact_skill_consistent");
    lua_pushnumber(
        state,
        static_cast<lua_Number>(
            damage.native_contact_damage_total));
    lua_setfield(state, -2, "damage_native_contact_total");
    lua_pushnumber(
        state,
        static_cast<lua_Number>(
            damage.minimum_native_contact_damage));
    lua_setfield(state, -2, "damage_native_contact_minimum");
    lua_pushnumber(
        state,
        static_cast<lua_Number>(
            damage.maximum_native_contact_damage));
    lua_setfield(state, -2, "damage_native_contact_maximum");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(
            damage.native_contact_sample_count));
    lua_setfield(
        state,
        -2,
        "damage_native_contact_sample_count");
    lua_createtable(
        state,
        static_cast<int>(
            damage.native_contact_sample_count),
        0);
    for (std::size_t index = 0;
         index < damage.native_contact_sample_count;
         ++index) {
        lua_pushnumber(
            state,
            static_cast<lua_Number>(
                damage.native_contact_damage_samples[index]));
        lua_rawseti(
            state,
            -2,
            static_cast<lua_Integer>(index + 1));
    }
    lua_setfield(state, -2, "damage_native_contact_samples");
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

// sd.debug.reset_earth_boulder_damage_observations() -> boolean
int LuaDebugResetEarthBoulderDamageObservations(lua_State* state) {
    ResetEarthBoulderDamageObservations();
    lua_pushboolean(state, 1);
    return 1;
}

// sd.debug.take_earth_boulder_damage_observations() -> array
int LuaDebugTakeEarthBoulderDamageObservations(lua_State* state) {
    std::vector<SDModEarthBoulderDamageObservation> observations;
    (void)TakeEarthBoulderDamageObservations(&observations);

    lua_createtable(state, static_cast<int>(observations.size()), 0);
    for (std::size_t index = 0; index < observations.size(); ++index) {
        const auto& observation = observations[index];
        lua_createtable(state, 0, 72);
        const auto set_integer =
            [&](const char* name, lua_Integer value) {
                lua_pushinteger(state, value);
                lua_setfield(state, -2, name);
            };
        const auto set_float =
            [&](const char* name, float value) {
                lua_pushnumber(state, static_cast<lua_Number>(value));
                lua_setfield(state, -2, name);
                const std::string bits_name =
                    std::string(name) + "_bits";
                std::uint32_t bits = 0;
                std::memcpy(&bits, &value, sizeof(bits));
                lua_pushinteger(
                    state,
                    static_cast<lua_Integer>(bits));
                lua_setfield(state, -2, bits_name.c_str());
            };

        lua_pushboolean(state, observation.valid ? 1 : 0);
        lua_setfield(state, -2, "valid");
        set_integer(
            "sequence",
            static_cast<lua_Integer>(observation.sequence));
        set_integer(
            "source_participant_id",
            static_cast<lua_Integer>(
                observation.source_participant_id));
        set_integer(
            "source_actor_address",
            static_cast<lua_Integer>(
                observation.source_actor_address));
        set_integer(
            "owner_actor_address",
            static_cast<lua_Integer>(
                observation.owner_actor_address));
        set_integer(
            "progression_address",
            static_cast<lua_Integer>(
                observation.progression_address));
        set_integer(
            "target_actor_address",
            static_cast<lua_Integer>(
                observation.target_actor_address));
        set_integer(
            "source_native_type_id",
            static_cast<lua_Integer>(
                observation.source_native_type_id));
        set_integer(
            "source_gameplay_slot",
            static_cast<lua_Integer>(
                observation.source_gameplay_slot));
        set_integer(
            "progression_level",
            static_cast<lua_Integer>(
                observation.progression_level));
        set_integer(
            "effective_rank",
            static_cast<lua_Integer>(
                observation.effective_rank));
        set_float(
            "progression_base_additive",
            observation.progression_base_additive);
        set_float(
            "configured_rank_damage",
            observation.configured_rank_damage);
        set_float(
            "progression_global_flat",
            observation.progression_global_flat);
        set_float(
            "progression_spell_flat",
            observation.progression_spell_flat);
        set_float(
            "progression_class_flat",
            observation.progression_class_flat);
        set_float(
            "progression_global_multiplier",
            observation.progression_global_multiplier);
        set_float(
            "progression_spell_multiplier",
            observation.progression_spell_multiplier);
        set_float(
            "progression_class_multiplier",
            observation.progression_class_multiplier);
        set_float(
            "progression_siege_multiplier",
            observation.progression_siege_multiplier);
        set_float(
            "actor_stat_damage",
            observation.actor_stat_damage);
        set_float("charge", observation.charge);
        set_float("growth_rate", observation.growth_rate);
        set_float("release_charge", observation.release_charge);
        set_float(
            "release_damage_pool",
            observation.release_damage_pool);
        set_float(
            "release_base_damage",
            observation.release_base_damage);
        set_float("maximum_charge", observation.maximum_charge);
        set_float("toughness", observation.toughness);
        set_float(
            "damage_lane_primary",
            observation.damage_lane_primary);
        set_float(
            "damage_lane_secondary",
            observation.damage_lane_secondary);
        set_float(
            "target_hp_before",
            observation.target_hp_before);
        set_float(
            "target_hp_after",
            observation.target_hp_after);
        set_float("target_max_hp", observation.target_max_hp);
        set_float("hp_delta", observation.hp_delta);
        lua_rawseti(
            state,
            -2,
            static_cast<lua_Integer>(index + 1));
    }
    return 1;
}

// sd.debug.reset_enemy_damage_observations() -> boolean
int LuaDebugResetEnemyDamageObservations(lua_State* state) {
    ResetEnemyDamageObservations();
    lua_pushboolean(state, 1);
    return 1;
}

// sd.debug.take_enemy_damage_observations() -> array
int LuaDebugTakeEnemyDamageObservations(lua_State* state) {
    std::vector<SDModEnemyDamageObservation> observations;
    (void)TakeEnemyDamageObservations(&observations);

    lua_createtable(state, static_cast<int>(observations.size()), 0);
    for (std::size_t index = 0; index < observations.size(); ++index) {
        const auto& observation = observations[index];
        lua_createtable(state, 0, 18);
        const auto set_integer =
            [&](const char* name, lua_Integer value) {
                lua_pushinteger(state, value);
                lua_setfield(state, -2, name);
            };
        const auto set_float =
            [&](const char* name, float value) {
                lua_pushnumber(state, static_cast<lua_Number>(value));
                lua_setfield(state, -2, name);
            };
        set_integer("sequence", static_cast<lua_Integer>(observation.sequence));
        set_integer(
            "monotonic_ms",
            static_cast<lua_Integer>(observation.monotonic_ms));
        set_integer(
            "source_participant_id",
            static_cast<lua_Integer>(observation.source_participant_id));
        set_integer(
            "source_actor_address",
            static_cast<lua_Integer>(observation.source_actor_address));
        set_integer(
            "source_owner_actor_address",
            static_cast<lua_Integer>(
                observation.source_owner_actor_address));
        set_integer(
            "target_actor_address",
            static_cast<lua_Integer>(observation.target_actor_address));
        set_integer(
            "target_network_actor_id",
            static_cast<lua_Integer>(
                observation.target_network_actor_id));
        set_integer(
            "source_native_type_id",
            static_cast<lua_Integer>(
                observation.source_native_type_id));
        set_integer(
            "source_owner_native_type_id",
            static_cast<lua_Integer>(
                observation.source_owner_native_type_id));
        set_integer(
            "target_native_type_id",
            static_cast<lua_Integer>(
                observation.target_native_type_id));
        set_integer(
            "source_gameplay_slot",
            static_cast<lua_Integer>(
                observation.source_gameplay_slot));
        set_float("target_hp_before", observation.target_hp_before);
        set_float("target_hp_after", observation.target_hp_after);
        set_float("target_max_hp", observation.target_max_hp);
        set_float("hp_delta", observation.hp_delta);
        lua_rawseti(
            state,
            -2,
            static_cast<lua_Integer>(index + 1));
    }
    return 1;
}

// sd.debug.reset_player_damage_observations() -> boolean
int LuaDebugResetPlayerDamageObservations(lua_State* state) {
    ResetPlayerDamageObservations();
    lua_pushboolean(state, 1);
    return 1;
}

// sd.debug.take_player_damage_observations() -> array
int LuaDebugTakePlayerDamageObservations(lua_State* state) {
    std::vector<SDModPlayerDamageObservation> observations;
    (void)TakePlayerDamageObservations(&observations);

    lua_createtable(state, static_cast<int>(observations.size()), 0);
    for (std::size_t index = 0; index < observations.size(); ++index) {
        const auto& observation = observations[index];
        lua_createtable(state, 0, 16);
        const auto set_integer =
            [&](const char* name, lua_Integer value) {
                lua_pushinteger(state, value);
                lua_setfield(state, -2, name);
            };
        const auto set_float =
            [&](const char* name, float value) {
                lua_pushnumber(state, static_cast<lua_Number>(value));
                lua_setfield(state, -2, name);
            };
        set_integer("sequence", static_cast<lua_Integer>(observation.sequence));
        set_integer(
            "monotonic_ms",
            static_cast<lua_Integer>(observation.monotonic_ms));
        set_integer(
            "target_participant_id",
            static_cast<lua_Integer>(observation.target_participant_id));
        set_integer(
            "target_actor_address",
            static_cast<lua_Integer>(observation.target_actor_address));
        set_integer(
            "source_actor_address",
            static_cast<lua_Integer>(observation.source_actor_address));
        set_integer(
            "target_native_type_id",
            static_cast<lua_Integer>(
                observation.target_native_type_id));
        set_integer(
            "source_native_type_id",
            static_cast<lua_Integer>(
                observation.source_native_type_id));
        set_integer(
            "target_gameplay_slot",
            static_cast<lua_Integer>(
                observation.target_gameplay_slot));
        set_float("target_hp_before", observation.target_hp_before);
        set_float("target_hp_after", observation.target_hp_after);
        set_float("target_max_hp", observation.target_max_hp);
        set_float("hp_delta", observation.hp_delta);
        lua_rawseti(
            state,
            -2,
            static_cast<lua_Integer>(index + 1));
    }
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
