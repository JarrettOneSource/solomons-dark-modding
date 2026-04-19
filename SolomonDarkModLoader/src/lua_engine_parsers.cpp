#include "lua_engine_internal.h"

extern "C" {
#include "lua.h"
#include "lauxlib.h"
}

#include <algorithm>
#include <string>

namespace sdmod::detail {
namespace {

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

}  // namespace

bool ParseBotIdArgument(lua_State* state, int index, std::uint64_t* bot_id, std::string* error_message) {
    if (bot_id == nullptr || error_message == nullptr) {
        return false;
    }

    if (!lua_isinteger(state, index)) {
        *error_message = "bot id must be an integer";
        return false;
    }

    const auto value = static_cast<std::int64_t>(lua_tointeger(state, index));
    if (value <= 0) {
        *error_message = "bot id must be greater than zero";
        return false;
    }

    *bot_id = static_cast<std::uint64_t>(value);
    return true;
}

bool ParseBotCreateRequest(
    lua_State* state,
    int index,
    multiplayer::BotCreateRequest* request,
    std::string* error_message) {
    if (request == nullptr || error_message == nullptr) {
        return false;
    }

    if (!EnsureTable(state, index, "sd.bots.create", error_message)) {
        return false;
    }

    *request = multiplayer::BotCreateRequest{};
    const auto table_index = lua_absindex(state, index);

    bool has_display_name = false;
    if (!ReadOptionalStringField(state, table_index, "name", &request->display_name, &has_display_name, error_message)) {
        return false;
    }

    bool has_profile = false;
    if (!ReadCharacterProfileField(state, table_index, &request->character_profile, &has_profile, error_message)) {
        return false;
    }
    if (!has_profile) {
        *error_message = "sd.bots.create requires profile";
        return false;
    }

    if (!ReadSceneIntentField(
            state,
            table_index,
            &request->scene_intent,
            &request->has_scene_intent,
            error_message)) {
        return false;
    }

    bool has_ready = false;
    if (!ReadOptionalBooleanField(state, table_index, "ready", &request->ready, &has_ready, error_message)) {
        return false;
    }

    if (!ReadPositionField(state, table_index, &request->position_x, &request->position_y, &request->has_transform, error_message)) {
        return false;
    }

    bool has_heading = false;
    if (!ReadOptionalNumberField(state, table_index, "heading", &request->heading, &has_heading, error_message)) {
        return false;
    }
    request->has_heading = has_heading;
    if (has_heading && !request->has_transform) {
        *error_message = "sd.bots.create requires position when heading is provided";
        return false;
    }

    return true;
}

bool ParseBotUpdateRequest(
    lua_State* state,
    int index,
    multiplayer::BotUpdateRequest* request,
    std::string* error_message) {
    if (request == nullptr || error_message == nullptr) {
        return false;
    }

    if (!EnsureTable(state, index, "sd.bots.update", error_message)) {
        return false;
    }

    *request = multiplayer::BotUpdateRequest{};
    const auto table_index = lua_absindex(state, index);

    lua_getfield(state, table_index, "id");
    if (!lua_isinteger(state, -1)) {
        *error_message = "sd.bots.update requires id";
        lua_pop(state, 1);
        return false;
    }
    request->bot_id = static_cast<std::uint64_t>(lua_tointeger(state, -1));
    lua_pop(state, 1);
    if (request->bot_id == 0) {
        *error_message = "sd.bots.update requires id != 0";
        return false;
    }

    if (!ReadOptionalStringField(state, table_index, "name", &request->display_name, &request->has_display_name, error_message) ||
        !ReadOptionalBooleanField(state, table_index, "ready", &request->ready, &request->has_ready, error_message)) {
        return false;
    }

    if (!ReadCharacterProfileField(
            state,
            table_index,
            &request->character_profile,
            &request->has_character_profile,
            error_message)) {
        return false;
    }

    if (!ReadSceneIntentField(
            state,
            table_index,
            &request->scene_intent,
            &request->has_scene_intent,
            error_message)) {
        return false;
    }

    if (!ReadPositionField(state, table_index, &request->position_x, &request->position_y, &request->has_transform, error_message)) {
        return false;
    }

    bool has_heading = false;
    if (!ReadOptionalNumberField(state, table_index, "heading", &request->heading, &has_heading, error_message)) {
        return false;
    }
    request->has_heading = has_heading;
    if (has_heading && !request->has_transform) {
        *error_message = "sd.bots.update requires position when heading is provided";
        return false;
    }

    if (request->has_display_name ||
        request->has_character_profile ||
        request->has_scene_intent ||
        request->has_ready ||
        request->has_transform) {
        return true;
    }

    *error_message = "sd.bots.update requires at least one field to update";
    return false;
}

bool ParseBotCastRequest(
    lua_State* state,
    int index,
    multiplayer::BotCastRequest* request,
    std::string* error_message) {
    if (request == nullptr || error_message == nullptr) {
        return false;
    }

    if (!EnsureTable(state, index, "sd.bots.cast", error_message)) {
        return false;
    }

    *request = multiplayer::BotCastRequest{};
    const auto table_index = lua_absindex(state, index);

    lua_getfield(state, table_index, "id");
    if (!lua_isinteger(state, -1)) {
        *error_message = "sd.bots.cast requires id";
        lua_pop(state, 1);
        return false;
    }
    request->bot_id = static_cast<std::uint64_t>(lua_tointeger(state, -1));
    lua_pop(state, 1);
    if (request->bot_id == 0) {
        *error_message = "sd.bots.cast requires id != 0";
        return false;
    }

    lua_getfield(state, table_index, "kind");
    if (!lua_isstring(state, -1)) {
        *error_message = "sd.bots.cast requires kind";
        lua_pop(state, 1);
        return false;
    }

    const auto cast_kind = std::string(lua_tostring(state, -1));
    lua_pop(state, 1);
    if (cast_kind == "primary") {
        request->kind = multiplayer::BotCastKind::Primary;
        request->secondary_slot = -1;
        return true;
    }

    if (cast_kind != "secondary") {
        *error_message = "sd.bots.cast kind must be primary or secondary";
        return false;
    }

    request->kind = multiplayer::BotCastKind::Secondary;
    lua_getfield(state, table_index, "slot");
    if (!lua_isinteger(state, -1)) {
        *error_message = "sd.bots.cast secondary slot is required";
        lua_pop(state, 1);
        return false;
    }

    request->secondary_slot = static_cast<std::int32_t>(lua_tointeger(state, -1));
    lua_pop(state, 1);
    if (request->secondary_slot < 0 || request->secondary_slot > 2) {
        *error_message = "sd.bots.cast secondary slot must be in range [0, 2]";
        return false;
    }

    return true;
}

void PushBotEquipVisualLaneState(
    lua_State* state,
    const multiplayer::BotEquipVisualLaneState& lane) {
    lua_createtable(state, 0, 6);
    lua_pushinteger(state, static_cast<lua_Integer>(lane.wrapper_address));
    lua_setfield(state, -2, "wrapper_address");
    lua_pushinteger(state, static_cast<lua_Integer>(lane.holder_address));
    lua_setfield(state, -2, "holder_address");
    lua_pushinteger(state, static_cast<lua_Integer>(lane.current_object_address));
    lua_setfield(state, -2, "current_object_address");
    lua_pushinteger(state, static_cast<lua_Integer>(lane.holder_kind));
    lua_setfield(state, -2, "holder_kind");
    lua_pushinteger(state, static_cast<lua_Integer>(lane.current_object_vtable));
    lua_setfield(state, -2, "current_object_vtable");
    lua_pushinteger(state, static_cast<lua_Integer>(lane.current_object_type_id));
    lua_setfield(state, -2, "current_object_type_id");
}

void PushBotSnapshot(lua_State* state, const multiplayer::BotSnapshot& snapshot) {
    lua_createtable(state, 0, 53);
    lua_pushboolean(state, snapshot.available ? 1 : 0);
    lua_setfield(state, -2, "available");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.bot_id));
    lua_setfield(state, -2, "id");
    lua_pushstring(state, snapshot.display_name.c_str());
    lua_setfield(state, -2, "name");
    lua_pushstring(state, multiplayer::ParticipantKindLabel(snapshot.participant_kind));
    lua_setfield(state, -2, "participant_kind");
    lua_pushstring(state, multiplayer::ParticipantControllerKindLabel(snapshot.controller_kind));
    lua_setfield(state, -2, "controller_kind");
    PushCharacterProfile(state, snapshot.character_profile);
    lua_setfield(state, -2, "profile");
    PushSceneIntent(state, snapshot.scene_intent);
    lua_setfield(state, -2, "scene");
    lua_pushboolean(state, snapshot.ready ? 1 : 0);
    lua_setfield(state, -2, "ready");
    lua_pushboolean(state, snapshot.in_run ? 1 : 0);
    lua_setfield(state, -2, "in_run");
    lua_pushboolean(state, snapshot.runtime_valid ? 1 : 0);
    lua_setfield(state, -2, "runtime_valid");
    lua_pushboolean(state, snapshot.transform_valid ? 1 : 0);
    lua_setfield(state, -2, "transform_valid");
    lua_pushboolean(state, snapshot.entity_materialized ? 1 : 0);
    lua_setfield(state, -2, "entity_materialized");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.run_nonce));
    lua_setfield(state, -2, "run_nonce");
    lua_createtable(state, 0, 2);
    lua_pushnumber(state, snapshot.position_x);
    lua_setfield(state, -2, "x");
    lua_pushnumber(state, snapshot.position_y);
    lua_setfield(state, -2, "y");
    lua_setfield(state, -2, "position");
    lua_pushnumber(state, snapshot.position_x);
    lua_setfield(state, -2, "x");
    lua_pushnumber(state, snapshot.position_y);
    lua_setfield(state, -2, "y");
    lua_pushnumber(state, snapshot.heading);
    lua_setfield(state, -2, "heading");
    lua_pushnumber(state, snapshot.hp);
    lua_setfield(state, -2, "hp");
    lua_pushnumber(state, snapshot.max_hp);
    lua_setfield(state, -2, "max_hp");
    lua_pushnumber(state, snapshot.mp);
    lua_setfield(state, -2, "mp");
    lua_pushnumber(state, snapshot.max_mp);
    lua_setfield(state, -2, "max_mp");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.actor_address));
    lua_setfield(state, -2, "actor_address");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.world_address));
    lua_setfield(state, -2, "world_address");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.animation_state_ptr));
    lua_setfield(state, -2, "animation_state_ptr");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.render_frame_table));
    lua_setfield(state, -2, "render_frame_table");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.hub_visual_attachment_ptr));
    lua_setfield(state, -2, "hub_visual_attachment_ptr");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.hub_visual_source_profile_address));
    lua_setfield(state, -2, "hub_visual_source_profile_address");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.hub_visual_descriptor_signature));
    lua_setfield(state, -2, "hub_visual_descriptor_signature");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.hub_visual_proxy_address));
    lua_setfield(state, -2, "hub_visual_proxy_address");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.progression_handle_address));
    lua_setfield(state, -2, "progression_handle_address");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.equip_handle_address));
    lua_setfield(state, -2, "equip_handle_address");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.progression_runtime_state_address));
    lua_setfield(state, -2, "progression_runtime_state_address");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.equip_runtime_state_address));
    lua_setfield(state, -2, "equip_runtime_state_address");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.gameplay_slot));
    lua_setfield(state, -2, "gameplay_slot");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.actor_slot));
    lua_setfield(state, -2, "actor_slot");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.slot_anim_state_index));
    lua_setfield(state, -2, "slot_anim_state_index");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.resolved_animation_state_id));
    lua_setfield(state, -2, "resolved_animation_state_id");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.hub_visual_source_kind));
    lua_setfield(state, -2, "hub_visual_source_kind");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.render_drive_flags));
    lua_setfield(state, -2, "render_drive_flags");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.anim_drive_state));
    lua_setfield(state, -2, "anim_drive_state");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.render_variant_primary));
    lua_setfield(state, -2, "render_variant_primary");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.render_variant_secondary));
    lua_setfield(state, -2, "render_variant_secondary");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.render_weapon_type));
    lua_setfield(state, -2, "render_weapon_type");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.render_selection_byte));
    lua_setfield(state, -2, "render_selection_byte");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.render_variant_tertiary));
    lua_setfield(state, -2, "render_variant_tertiary");
    lua_pushnumber(state, snapshot.walk_cycle_primary);
    lua_setfield(state, -2, "walk_cycle_primary");
    lua_pushnumber(state, snapshot.walk_cycle_secondary);
    lua_setfield(state, -2, "walk_cycle_secondary");
    lua_pushnumber(state, snapshot.render_drive_stride);
    lua_setfield(state, -2, "render_drive_stride");
    lua_pushnumber(state, snapshot.render_advance_rate);
    lua_setfield(state, -2, "render_advance_rate");
    lua_pushnumber(state, snapshot.render_advance_phase);
    lua_setfield(state, -2, "render_advance_phase");
    lua_pushnumber(state, snapshot.render_drive_overlay_alpha);
    lua_setfield(state, -2, "render_drive_overlay_alpha");
    lua_pushnumber(state, snapshot.render_drive_move_blend);
    lua_setfield(state, -2, "render_drive_move_blend");
    PushBotEquipVisualLaneState(state, snapshot.primary_visual_lane);
    lua_setfield(state, -2, "primary_visual_lane");
    PushBotEquipVisualLaneState(state, snapshot.secondary_visual_lane);
    lua_setfield(state, -2, "secondary_visual_lane");
    PushBotEquipVisualLaneState(state, snapshot.attachment_visual_lane);
    lua_setfield(state, -2, "attachment_visual_lane");
    lua_pushboolean(state, snapshot.gameplay_attach_applied ? 1 : 0);
    lua_setfield(state, -2, "gameplay_attach_applied");
    lua_pushstring(state, multiplayer::BotControllerStateLabel(snapshot.state));
    lua_setfield(state, -2, "state");
    lua_pushboolean(state, snapshot.moving ? 1 : 0);
    lua_setfield(state, -2, "moving");
    lua_pushboolean(state, snapshot.has_target ? 1 : 0);
    lua_setfield(state, -2, "has_target");
    if (snapshot.has_target) {
        lua_pushnumber(state, snapshot.target_x);
        lua_setfield(state, -2, "target_x");
        lua_pushnumber(state, snapshot.target_y);
        lua_setfield(state, -2, "target_y");
    } else {
        lua_pushnil(state);
        lua_setfield(state, -2, "target_x");
        lua_pushnil(state);
        lua_setfield(state, -2, "target_y");
    }
    lua_pushnumber(state, snapshot.distance_to_target);
    lua_setfield(state, -2, "distance_to_target");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.queued_cast_count));
    lua_setfield(state, -2, "queued_cast_count");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.last_queued_cast_ms));
    lua_setfield(state, -2, "last_queued_cast_ms");
}

void PushBotSnapshotArray(lua_State* state) {
    const auto count = multiplayer::GetBotCount();
    lua_createtable(state, static_cast<int>(count), 0);
    for (std::uint32_t index = 0; index < count; ++index) {
        multiplayer::BotSnapshot snapshot;
        if (!multiplayer::ReadBotSnapshotByIndex(index, &snapshot)) {
            continue;
        }

        PushBotSnapshot(state, snapshot);
        lua_rawseti(state, -2, static_cast<lua_Integer>(index + 1));
    }
}

}  // namespace sdmod::detail
