#pragma once

#include "lua_engine_internal.h"

extern "C" {
#include "lua.h"
#include "lauxlib.h"
}

#include <algorithm>
#include <string>

namespace sdmod::detail::parsers {

bool EnsureTable(lua_State* state, int index, const char* api_name, std::string* error_message);
bool ReadOptionalStringField(
    lua_State* state,
    int table_index,
    const char* field_name,
    std::string* value,
    bool* has_value,
    std::string* error_message);
bool ReadOptionalBooleanField(
    lua_State* state,
    int table_index,
    const char* field_name,
    bool* value,
    bool* has_value,
    std::string* error_message);
bool ReadOptionalIntegerField(
    lua_State* state,
    int table_index,
    const char* field_name,
    std::int32_t* value,
    bool* has_value,
    std::string* error_message);
bool ReadOptionalNumberField(
    lua_State* state,
    int table_index,
    const char* field_name,
    float* value,
    bool* has_value,
    std::string* error_message);
bool ReadPositionField(
    lua_State* state,
    int table_index,
    float* position_x,
    float* position_y,
    bool* has_position,
    std::string* error_message);
bool ReadLoadoutField(
    lua_State* state,
    int table_index,
    multiplayer::BotLoadoutInfo* loadout,
    bool* has_loadout,
    std::string* error_message);
void PushSecondaryLoadout(lua_State* state, const multiplayer::BotLoadoutInfo& loadout);
void PushLoadout(lua_State* state, const multiplayer::BotLoadoutInfo& loadout);
bool ReadAppearanceChoicesField(
    lua_State* state,
    int table_index,
    multiplayer::CharacterAppearanceInfo* appearance,
    std::string* error_message);
bool ReadCharacterProfileValue(
    lua_State* state,
    int profile_index,
    multiplayer::MultiplayerCharacterProfile* profile,
    std::string* error_message);
bool ReadCharacterProfileField(
    lua_State* state,
    int table_index,
    multiplayer::MultiplayerCharacterProfile* profile,
    bool* has_profile,
    std::string* error_message);
bool ReadSceneIntentValue(
    lua_State* state,
    int scene_index,
    multiplayer::ParticipantSceneIntent* scene_intent,
    std::string* error_message);
bool ReadSceneIntentField(
    lua_State* state,
    int table_index,
    multiplayer::ParticipantSceneIntent* scene_intent,
    bool* has_scene_intent,
    std::string* error_message);
void PushAppearanceChoices(lua_State* state, const multiplayer::CharacterAppearanceInfo& appearance);
void PushCharacterProfile(lua_State* state, const multiplayer::MultiplayerCharacterProfile& profile);
void PushSceneIntent(lua_State* state, const multiplayer::ParticipantSceneIntent& scene_intent);

}  // namespace sdmod::detail::parsers
