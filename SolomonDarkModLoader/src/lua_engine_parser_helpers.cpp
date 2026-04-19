#include "lua_engine_parsers_internal.h"

namespace sdmod::detail::parsers {

bool EnsureTable(lua_State* state, int index, const char* api_name, std::string* error_message) {
    if (error_message == nullptr) {
        return false;
    }

    if (!lua_istable(state, index)) {
        *error_message = std::string(api_name) + " expects a table";
        return false;
    }

    return true;
}

bool ReadOptionalStringField(
    lua_State* state,
    int table_index,
    const char* field_name,
    std::string* value,
    bool* has_value,
    std::string* error_message) {
    if (value == nullptr || has_value == nullptr || error_message == nullptr) {
        return false;
    }

    lua_getfield(state, table_index, field_name);
    if (lua_isnil(state, -1)) {
        lua_pop(state, 1);
        *has_value = false;
        return true;
    }

    if (!lua_isstring(state, -1)) {
        *error_message = std::string(field_name) + " must be a string";
        lua_pop(state, 1);
        return false;
    }

    *value = lua_tostring(state, -1);
    *has_value = true;
    lua_pop(state, 1);
    return true;
}

bool ReadOptionalBooleanField(
    lua_State* state,
    int table_index,
    const char* field_name,
    bool* value,
    bool* has_value,
    std::string* error_message) {
    if (value == nullptr || has_value == nullptr || error_message == nullptr) {
        return false;
    }

    lua_getfield(state, table_index, field_name);
    if (lua_isnil(state, -1)) {
        lua_pop(state, 1);
        *has_value = false;
        return true;
    }

    if (!lua_isboolean(state, -1)) {
        *error_message = std::string(field_name) + " must be a boolean";
        lua_pop(state, 1);
        return false;
    }

    *value = lua_toboolean(state, -1) != 0;
    *has_value = true;
    lua_pop(state, 1);
    return true;
}

bool ReadOptionalIntegerField(
    lua_State* state,
    int table_index,
    const char* field_name,
    std::int32_t* value,
    bool* has_value,
    std::string* error_message) {
    if (value == nullptr || has_value == nullptr || error_message == nullptr) {
        return false;
    }

    lua_getfield(state, table_index, field_name);
    if (lua_isnil(state, -1)) {
        lua_pop(state, 1);
        *has_value = false;
        return true;
    }

    if (!lua_isinteger(state, -1)) {
        *error_message = std::string(field_name) + " must be an integer";
        lua_pop(state, 1);
        return false;
    }

    *value = static_cast<std::int32_t>(lua_tointeger(state, -1));
    *has_value = true;
    lua_pop(state, 1);
    return true;
}

bool ReadOptionalNumberField(
    lua_State* state,
    int table_index,
    const char* field_name,
    float* value,
    bool* has_value,
    std::string* error_message) {
    if (value == nullptr || has_value == nullptr || error_message == nullptr) {
        return false;
    }

    lua_getfield(state, table_index, field_name);
    if (lua_isnil(state, -1)) {
        lua_pop(state, 1);
        *has_value = false;
        return true;
    }

    if (!lua_isnumber(state, -1)) {
        *error_message = std::string(field_name) + " must be a number";
        lua_pop(state, 1);
        return false;
    }

    *value = static_cast<float>(lua_tonumber(state, -1));
    *has_value = true;
    lua_pop(state, 1);
    return true;
}

bool ReadPositionField(
    lua_State* state,
    int table_index,
    float* position_x,
    float* position_y,
    bool* has_position,
    std::string* error_message) {
    if (position_x == nullptr || position_y == nullptr || has_position == nullptr || error_message == nullptr) {
        return false;
    }

    lua_getfield(state, table_index, "position");
    if (lua_isnil(state, -1)) {
        lua_pop(state, 1);
        *has_position = false;
        return true;
    }

    if (!lua_istable(state, -1)) {
        *error_message = "position must be a table";
        lua_pop(state, 1);
        return false;
    }

    lua_getfield(state, -1, "x");
    if (!lua_isnumber(state, -1)) {
        *error_message = "position.x must be a number";
        lua_pop(state, 2);
        return false;
    }
    *position_x = static_cast<float>(lua_tonumber(state, -1));
    lua_pop(state, 1);

    lua_getfield(state, -1, "y");
    if (!lua_isnumber(state, -1)) {
        *error_message = "position.y must be a number";
        lua_pop(state, 2);
        return false;
    }
    *position_y = static_cast<float>(lua_tonumber(state, -1));
    lua_pop(state, 2);
    *has_position = true;
    return true;
}

bool ReadLoadoutField(
    lua_State* state,
    int table_index,
    multiplayer::BotLoadoutInfo* loadout,
    bool* has_loadout,
    std::string* error_message) {
    if (loadout == nullptr || has_loadout == nullptr || error_message == nullptr) {
        return false;
    }

    lua_getfield(state, table_index, "loadout");
    if (lua_isnil(state, -1)) {
        lua_pop(state, 1);
        *has_loadout = false;
        return true;
    }

    if (!lua_istable(state, -1)) {
        *error_message = "loadout must be a table";
        lua_pop(state, 1);
        return false;
    }

    *loadout = multiplayer::BotLoadoutInfo{};

    bool has_primary_skill_id = false;
    if (!ReadOptionalIntegerField(state, lua_gettop(state), "primary_skill_id", &loadout->primary_skill_id, &has_primary_skill_id, error_message)) {
        lua_pop(state, 1);
        return false;
    }

    bool has_primary_combo_id = false;
    if (!ReadOptionalIntegerField(state, lua_gettop(state), "primary_combo_id", &loadout->primary_combo_id, &has_primary_combo_id, error_message)) {
        lua_pop(state, 1);
        return false;
    }

    lua_getfield(state, -1, "secondary_skill_ids");
    if (!lua_isnil(state, -1)) {
        if (!lua_istable(state, -1)) {
            *error_message = "loadout.secondary_skill_ids must be a table";
            lua_pop(state, 2);
            return false;
        }

        const auto length = lua_rawlen(state, -1);
        if (length > loadout->secondary_skill_ids.size()) {
            *error_message = "loadout.secondary_skill_ids supports at most three entries";
            lua_pop(state, 2);
            return false;
        }

        for (lua_Unsigned index = 1; index <= length; ++index) {
            lua_rawgeti(state, -1, static_cast<lua_Integer>(index));
            if (!lua_isinteger(state, -1)) {
                *error_message = "loadout.secondary_skill_ids entries must be integers";
                lua_pop(state, 3);
                return false;
            }

            loadout->secondary_skill_ids[static_cast<std::size_t>(index - 1)] =
                static_cast<std::int32_t>(lua_tointeger(state, -1));
            lua_pop(state, 1);
        }
    }

    lua_pop(state, 2);
    *has_loadout = true;
    return true;
}

void PushSecondaryLoadout(lua_State* state, const multiplayer::BotLoadoutInfo& loadout) {
    lua_createtable(state, static_cast<int>(loadout.secondary_skill_ids.size()), 0);
    for (std::size_t index = 0; index < loadout.secondary_skill_ids.size(); ++index) {
        lua_pushinteger(state, static_cast<lua_Integer>(loadout.secondary_skill_ids[index]));
        lua_rawseti(state, -2, static_cast<lua_Integer>(index + 1));
    }
}

void PushLoadout(lua_State* state, const multiplayer::BotLoadoutInfo& loadout) {
    lua_createtable(state, 0, 3);
    lua_pushinteger(state, static_cast<lua_Integer>(loadout.primary_skill_id));
    lua_setfield(state, -2, "primary_skill_id");
    lua_pushinteger(state, static_cast<lua_Integer>(loadout.primary_combo_id));
    lua_setfield(state, -2, "primary_combo_id");
    PushSecondaryLoadout(state, loadout);
    lua_setfield(state, -2, "secondary_skill_ids");
}

bool ReadAppearanceChoicesField(
    lua_State* state,
    int table_index,
    multiplayer::CharacterAppearanceInfo* appearance,
    std::string* error_message) {
    if (appearance == nullptr || error_message == nullptr) {
        return false;
    }

    lua_getfield(state, table_index, "appearance_choice_ids");
    if (lua_isnil(state, -1)) {
        lua_pop(state, 1);
        return true;
    }

    if (!lua_istable(state, -1)) {
        *error_message = "profile.appearance_choice_ids must be a table";
        lua_pop(state, 1);
        return false;
    }

    const auto length = static_cast<std::size_t>(lua_rawlen(state, -1));
    if (length > appearance->choice_ids.size()) {
        *error_message = "profile.appearance_choice_ids supports at most four entries";
        lua_pop(state, 1);
        return false;
    }

    for (std::size_t index = 0; index < length; ++index) {
        lua_rawgeti(state, -1, static_cast<lua_Integer>(index + 1));
        if (!lua_isinteger(state, -1)) {
            *error_message = "profile.appearance_choice_ids entries must be integers";
            lua_pop(state, 2);
            return false;
        }

        appearance->choice_ids[index] = static_cast<std::int32_t>(lua_tointeger(state, -1));
        lua_pop(state, 1);
    }

    lua_pop(state, 1);
    return true;
}

bool ReadCharacterProfileValue(
    lua_State* state,
    int profile_index,
    multiplayer::MultiplayerCharacterProfile* profile,
    std::string* error_message) {
    if (profile == nullptr || error_message == nullptr) {
        return false;
    }

    if (!EnsureTable(state, profile_index, "profile", error_message)) {
        return false;
    }

    *profile = multiplayer::DefaultCharacterProfile();
    const auto table_index = lua_absindex(state, profile_index);

    bool has_element_id = false;
    if (!ReadOptionalIntegerField(
            state,
            table_index,
            "element_id",
            &profile->element_id,
            &has_element_id,
            error_message)) {
        return false;
    }
    if (!has_element_id) {
        *error_message = "profile.element_id is required";
        return false;
    }

    std::int32_t discipline_id = static_cast<std::int32_t>(profile->discipline_id);
    bool has_discipline_id = false;
    if (!ReadOptionalIntegerField(
            state,
            table_index,
            "discipline_id",
            &discipline_id,
            &has_discipline_id,
            error_message)) {
        return false;
    }
    if (has_discipline_id) {
        profile->discipline_id = static_cast<multiplayer::CharacterDisciplineId>(discipline_id);
    }

    if (!ReadAppearanceChoicesField(state, table_index, &profile->appearance, error_message)) {
        return false;
    }

    bool has_loadout = false;
    if (!ReadLoadoutField(state, table_index, &profile->loadout, &has_loadout, error_message)) {
        return false;
    }

    bool has_level = false;
    if (!ReadOptionalIntegerField(state, table_index, "level", &profile->level, &has_level, error_message)) {
        return false;
    }

    bool has_experience = false;
    if (!ReadOptionalIntegerField(
            state,
            table_index,
            "experience",
            &profile->experience,
            &has_experience,
            error_message)) {
        return false;
    }

    if (!multiplayer::IsValidCharacterProfile(*profile)) {
        *error_message = "profile contains invalid element_id or discipline_id";
        return false;
    }

    return true;
}

bool ReadCharacterProfileField(
    lua_State* state,
    int table_index,
    multiplayer::MultiplayerCharacterProfile* profile,
    bool* has_profile,
    std::string* error_message) {
    if (profile == nullptr || has_profile == nullptr || error_message == nullptr) {
        return false;
    }

    lua_getfield(state, table_index, "profile");
    if (lua_isnil(state, -1)) {
        *has_profile = false;
        lua_pop(state, 1);
        return true;
    }

    const bool ok = ReadCharacterProfileValue(state, -1, profile, error_message);
    lua_pop(state, 1);
    if (!ok) {
        return false;
    }

    *has_profile = true;
    return true;
}

bool ReadSceneIntentValue(
    lua_State* state,
    int scene_index,
    multiplayer::ParticipantSceneIntent* scene_intent,
    std::string* error_message) {
    if (scene_intent == nullptr || error_message == nullptr) {
        return false;
    }

    if (!EnsureTable(state, scene_index, "scene", error_message)) {
        return false;
    }

    *scene_intent = multiplayer::DefaultParticipantSceneIntent();
    const auto table_index = lua_absindex(state, scene_index);

    lua_getfield(state, table_index, "kind");
    if (!lua_isstring(state, -1)) {
        *error_message = "scene.kind is required";
        lua_pop(state, 1);
        return false;
    }

    const auto kind = std::string(lua_tostring(state, -1));
    lua_pop(state, 1);
    if (kind == "shared_hub") {
        scene_intent->kind = multiplayer::ParticipantSceneIntentKind::SharedHub;
    } else if (kind == "private_region") {
        scene_intent->kind = multiplayer::ParticipantSceneIntentKind::PrivateRegion;
    } else if (kind == "run") {
        scene_intent->kind = multiplayer::ParticipantSceneIntentKind::Run;
    } else {
        *error_message = "scene.kind must be shared_hub, private_region, or run";
        return false;
    }

    bool has_region_index = false;
    if (!ReadOptionalIntegerField(
            state,
            table_index,
            "region_index",
            &scene_intent->region_index,
            &has_region_index,
            error_message)) {
        return false;
    }

    bool has_region_type_id = false;
    if (!ReadOptionalIntegerField(
            state,
            table_index,
            "region_type_id",
            &scene_intent->region_type_id,
            &has_region_type_id,
            error_message)) {
        return false;
    }

    if (!multiplayer::IsValidParticipantSceneIntent(*scene_intent)) {
        *error_message = "scene contains invalid kind/region fields";
        return false;
    }

    return true;
}

bool ReadSceneIntentField(
    lua_State* state,
    int table_index,
    multiplayer::ParticipantSceneIntent* scene_intent,
    bool* has_scene_intent,
    std::string* error_message) {
    if (scene_intent == nullptr || has_scene_intent == nullptr || error_message == nullptr) {
        return false;
    }

    lua_getfield(state, table_index, "scene");
    if (lua_isnil(state, -1)) {
        *has_scene_intent = false;
        lua_pop(state, 1);
        return true;
    }

    const bool ok = ReadSceneIntentValue(state, -1, scene_intent, error_message);
    lua_pop(state, 1);
    if (!ok) {
        return false;
    }

    *has_scene_intent = true;
    return true;
}

void PushAppearanceChoices(lua_State* state, const multiplayer::CharacterAppearanceInfo& appearance) {
    lua_createtable(state, static_cast<int>(appearance.choice_ids.size()), 0);
    for (std::size_t index = 0; index < appearance.choice_ids.size(); ++index) {
        lua_pushinteger(state, static_cast<lua_Integer>(appearance.choice_ids[index]));
        lua_rawseti(state, -2, static_cast<lua_Integer>(index + 1));
    }
}

void PushCharacterProfile(lua_State* state, const multiplayer::MultiplayerCharacterProfile& profile) {
    lua_createtable(state, 0, 5);
    lua_pushinteger(state, static_cast<lua_Integer>(profile.element_id));
    lua_setfield(state, -2, "element_id");
    lua_pushinteger(state, static_cast<lua_Integer>(profile.discipline_id));
    lua_setfield(state, -2, "discipline_id");
    PushAppearanceChoices(state, profile.appearance);
    lua_setfield(state, -2, "appearance_choice_ids");
    PushLoadout(state, profile.loadout);
    lua_setfield(state, -2, "loadout");
    lua_pushinteger(state, static_cast<lua_Integer>(profile.level));
    lua_setfield(state, -2, "level");
    lua_pushinteger(state, static_cast<lua_Integer>(profile.experience));
    lua_setfield(state, -2, "experience");
}

void PushSceneIntent(lua_State* state, const multiplayer::ParticipantSceneIntent& scene_intent) {
    lua_createtable(state, 0, 3);
    lua_pushstring(state, multiplayer::ParticipantSceneIntentKindLabel(scene_intent.kind));
    lua_setfield(state, -2, "kind");
    lua_pushinteger(state, static_cast<lua_Integer>(scene_intent.region_index));
    lua_setfield(state, -2, "region_index");
    lua_pushinteger(state, static_cast<lua_Integer>(scene_intent.region_type_id));
    lua_setfield(state, -2, "region_type_id");
}

}  // namespace sdmod::detail::parsers
