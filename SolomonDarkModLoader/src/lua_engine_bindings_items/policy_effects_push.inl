void PushConsumablePolicyEffects(
    lua_State* state,
    const LuaConsumablePolicyEffects& effects) {
    if (!effects.declared) {
        return;
    }
    lua_createtable(state, 0, 8);
    lua_pushboolean(state, effects.synthetic_safe ? 1 : 0);
    lua_setfield(state, -2, "synthetic_safe");
    lua_pushnumber(state, effects.restores_hp_fraction);
    lua_setfield(state, -2, "restores_hp_fraction");
    lua_pushnumber(state, effects.restores_mana_fraction);
    lua_setfield(state, -2, "restores_mana_fraction");
    lua_pushnumber(state, effects.damage_multiplier);
    lua_setfield(state, -2, "damage_multiplier");
    lua_pushboolean(state, effects.cures_poison ? 1 : 0);
    lua_setfield(state, -2, "cures_poison");
    lua_pushnumber(
        state,
        effects.poison_immunity_duration_seconds);
    lua_setfield(
        state,
        -2,
        "poison_immunity_duration_seconds");
    lua_pushboolean(state, effects.concentrates_all ? 1 : 0);
    lua_setfield(state, -2, "concentrates_all");
    lua_pushnumber(state, effects.effect_duration_seconds);
    lua_setfield(state, -2, "effect_duration_seconds");
    lua_setfield(state, -2, "policy_effects");
}
