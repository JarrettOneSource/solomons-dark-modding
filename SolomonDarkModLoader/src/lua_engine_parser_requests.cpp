#include "lua_engine_parsers_internal.h"

namespace sdmod::detail {

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
    using namespace sdmod::detail::parsers;

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
    using namespace sdmod::detail::parsers;

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
    using namespace sdmod::detail::parsers;

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

}  // namespace sdmod::detail
