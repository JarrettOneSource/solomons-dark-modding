constexpr float kLuaMaximumPolicyEffectDurationSeconds =
    24.0f * 60.0f * 60.0f;

bool IsConsumablePolicyEffectField(std::string_view field) {
    return field == "synthetic_safe" ||
        field == "restores_hp_fraction" ||
        field == "restores_mana_fraction" ||
        field == "damage_multiplier" ||
        field == "cures_poison" ||
        field == "poison_immunity_duration_seconds" ||
        field == "concentrates_all" ||
        field == "effect_duration_seconds";
}

bool ReadOptionalPolicyBoolean(
    lua_State* state,
    int table_index,
    const char* field,
    bool default_value) {
    lua_getfield(state, table_index, field);
    if (lua_isnil(state, -1)) {
        lua_pop(state, 1);
        return default_value;
    }
    if (!lua_isboolean(state, -1)) {
        luaL_error(
            state,
            "sd.items.register potion policy_effects.%s must be boolean",
            field);
    }
    const bool value = lua_toboolean(state, -1) != 0;
    lua_pop(state, 1);
    return value;
}

float ReadOptionalPolicyNumber(
    lua_State* state,
    int table_index,
    const char* field,
    float default_value,
    float minimum,
    float maximum) {
    lua_getfield(state, table_index, field);
    if (lua_isnil(state, -1)) {
        lua_pop(state, 1);
        return default_value;
    }
    if (lua_type(state, -1) != LUA_TNUMBER) {
        luaL_error(
            state,
            "sd.items.register potion policy_effects.%s must be a number",
            field);
    }
    const auto raw = lua_tonumber(state, -1);
    lua_pop(state, 1);
    if (!std::isfinite(raw) || raw < minimum || raw > maximum) {
        luaL_error(
            state,
            "sd.items.register potion policy_effects.%s must be finite and in %.3f..%.3f",
            field,
            static_cast<double>(minimum),
            static_cast<double>(maximum));
    }
    return static_cast<float>(raw);
}

LuaConsumablePolicyEffects ReadConsumablePolicyEffects(
    lua_State* state,
    int table_index) {
    LuaConsumablePolicyEffects effects;
    lua_getfield(state, table_index, "policy_effects");
    if (lua_isnil(state, -1)) {
        lua_pop(state, 1);
        return effects;
    }
    if (!lua_istable(state, -1)) {
        lua_pop(state, 1);
        luaL_error(
            state,
            "sd.items.register potion policy_effects must be a table");
    }

    const int effects_index = lua_absindex(state, -1);
    lua_pushnil(state);
    while (lua_next(state, effects_index) != 0) {
        if (lua_type(state, -2) != LUA_TSTRING) {
            lua_pop(state, 3);
            luaL_error(
                state,
                "sd.items.register potion policy_effects accepts only named fields");
        }
        std::size_t field_length = 0;
        const auto* field =
            lua_tolstring(state, -2, &field_length);
        const std::string_view field_name(field, field_length);
        lua_pop(state, 1);
        if (!IsConsumablePolicyEffectField(field_name)) {
            const std::string owned_field(field_name);
            lua_pop(state, 2);
            luaL_error(
                state,
                "sd.items.register potion policy_effects received unknown field '%s'",
                owned_field.c_str());
        }
    }

    effects.declared = true;
    effects.synthetic_safe = ReadOptionalPolicyBoolean(
        state,
        effects_index,
        "synthetic_safe",
        false);
    effects.restores_hp_fraction = ReadOptionalPolicyNumber(
        state,
        effects_index,
        "restores_hp_fraction",
        0.0f,
        0.0f,
        1.0f);
    effects.restores_mana_fraction = ReadOptionalPolicyNumber(
        state,
        effects_index,
        "restores_mana_fraction",
        0.0f,
        0.0f,
        1.0f);
    effects.damage_multiplier = ReadOptionalPolicyNumber(
        state,
        effects_index,
        "damage_multiplier",
        1.0f,
        0.0f,
        16.0f);
    effects.cures_poison = ReadOptionalPolicyBoolean(
        state,
        effects_index,
        "cures_poison",
        false);
    effects.poison_immunity_duration_seconds =
        ReadOptionalPolicyNumber(
            state,
            effects_index,
            "poison_immunity_duration_seconds",
            0.0f,
            0.0f,
            kLuaMaximumPolicyEffectDurationSeconds);
    effects.concentrates_all = ReadOptionalPolicyBoolean(
        state,
        effects_index,
        "concentrates_all",
        false);
    effects.effect_duration_seconds = ReadOptionalPolicyNumber(
        state,
        effects_index,
        "effect_duration_seconds",
        0.0f,
        0.0f,
        kLuaMaximumPolicyEffectDurationSeconds);
    lua_pop(state, 1);

    const bool describes_effect =
        effects.restores_hp_fraction > 0.0f ||
        effects.restores_mana_fraction > 0.0f ||
        std::abs(effects.damage_multiplier - 1.0f) > 0.0001f ||
        effects.cures_poison ||
        effects.poison_immunity_duration_seconds > 0.0f ||
        effects.concentrates_all ||
        effects.effect_duration_seconds > 0.0f;
    if (effects.synthetic_safe && !describes_effect) {
        luaL_error(
            state,
            "sd.items.register potion synthetic-safe policy_effects must describe at least one effect");
    }
    return effects;
}
