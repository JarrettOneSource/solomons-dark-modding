#include "lua_engine_bindings_internal.h"

#include "debug_ui_overlay.h"
#include "ui_navigation.h"

#include <algorithm>
#include <cctype>
#include <limits>
#include <string>
#include <string_view>

namespace sdmod::detail {
namespace {

std::string TrimAsciiWhitespaceCopy(std::string_view value) {
    std::size_t start = 0;
    while (start < value.size() && std::isspace(static_cast<unsigned char>(value[start])) != 0) {
        ++start;
    }

    std::size_t end = value.size();
    while (end > start && std::isspace(static_cast<unsigned char>(value[end - 1])) != 0) {
        --end;
    }

    return std::string(value.substr(start, end - start));
}

std::string NormalizeUiQueryToken(std::string_view value) {
    auto normalized = TrimAsciiWhitespaceCopy(value);
    std::transform(normalized.begin(), normalized.end(), normalized.begin(), [](unsigned char character) {
        return static_cast<char>(std::toupper(character));
    });
    return normalized;
}

std::string GetUiSurfaceRootId(std::string_view surface_id) {
    const auto separator_index = surface_id.find('.');
    if (separator_index == std::string_view::npos) {
        return std::string(surface_id);
    }

    return std::string(surface_id.substr(0, separator_index));
}

void PushDebugUiSnapshotElement(lua_State* state, const DebugUiSnapshotElement& element) {
    lua_createtable(state, 0, 14);
    lua_pushstring(state, element.surface_id.c_str());
    lua_setfield(state, -2, "surface_id");

    const auto surface_root_id = GetUiSurfaceRootId(element.surface_id);
    lua_pushstring(state, surface_root_id.c_str());
    lua_setfield(state, -2, "surface_root_id");

    lua_pushstring(state, element.surface_title.c_str());
    lua_setfield(state, -2, "surface_title");
    lua_pushstring(state, element.label.c_str());
    lua_setfield(state, -2, "label");
    lua_pushstring(state, element.action_id.c_str());
    lua_setfield(state, -2, "action_id");
    lua_pushinteger(state, static_cast<lua_Integer>(element.source_object_ptr));
    lua_setfield(state, -2, "source_object_ptr");
    lua_pushinteger(state, static_cast<lua_Integer>(element.surface_object_ptr));
    lua_setfield(state, -2, "surface_object_ptr");
    lua_pushboolean(state, element.show_label ? 1 : 0);
    lua_setfield(state, -2, "show_label");
    lua_pushnumber(state, element.left);
    lua_setfield(state, -2, "left");
    lua_pushnumber(state, element.top);
    lua_setfield(state, -2, "top");
    lua_pushnumber(state, element.right);
    lua_setfield(state, -2, "right");
    lua_pushnumber(state, element.bottom);
    lua_setfield(state, -2, "bottom");
    lua_pushnumber(state, element.right - element.left);
    lua_setfield(state, -2, "width");
    lua_pushnumber(state, element.bottom - element.top);
    lua_setfield(state, -2, "height");
    lua_pushnumber(state, (element.left + element.right) * 0.5f);
    lua_setfield(state, -2, "center_x");
    lua_pushnumber(state, (element.top + element.bottom) * 0.5f);
    lua_setfield(state, -2, "center_y");
}

const DebugUiSnapshotElement* FindBestSnapshotElement(
    const DebugUiSurfaceSnapshot& snapshot,
    std::string_view label,
    std::string_view surface_id) {
    const auto normalized_label = NormalizeUiQueryToken(label);
    if (normalized_label.empty()) {
        return nullptr;
    }

    const auto normalized_surface_id = NormalizeUiQueryToken(surface_id);
    if (!normalized_surface_id.empty() &&
        NormalizeUiQueryToken(snapshot.surface_id) != normalized_surface_id) {
        return nullptr;
    }

    const DebugUiSnapshotElement* best_match = nullptr;
    double best_score = (std::numeric_limits<double>::lowest)();
    for (const auto& element : snapshot.elements) {
        if (NormalizeUiQueryToken(element.label) != normalized_label) {
            continue;
        }

        if (!normalized_surface_id.empty() &&
            NormalizeUiQueryToken(GetUiSurfaceRootId(element.surface_id)) != normalized_surface_id) {
            continue;
        }

        const auto area = static_cast<double>((element.right - element.left) * (element.bottom - element.top));
        auto score = 0.0;
        if (!element.action_id.empty()) {
            score += 1000000.0;
        }
        if (element.show_label) {
            score += 100000.0;
        }
        if (element.surface_id == snapshot.surface_id) {
            score += 10000.0;
        } else if (GetUiSurfaceRootId(element.surface_id) == snapshot.surface_id) {
            score += 1000.0;
        }
        score -= area;

        if (best_match == nullptr || score > best_score) {
            best_match = &element;
            best_score = score;
        }
    }

    return best_match;
}

int LuaUiGetSurfaceId(lua_State* state) {
    DebugUiSurfaceSnapshot snapshot;
    if (!sdmod::TryGetLatestDebugUiSurfaceSnapshot(&snapshot)) {
        lua_pushnil(state);
        return 1;
    }

    lua_pushstring(state, snapshot.surface_id.c_str());
    return 1;
}

int LuaUiGetSnapshot(lua_State* state) {
    DebugUiSurfaceSnapshot snapshot;
    if (!sdmod::TryGetLatestDebugUiSurfaceSnapshot(&snapshot)) {
        lua_pushnil(state);
        return 1;
    }

    lua_createtable(state, 0, 5);
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.generation));
    lua_setfield(state, -2, "generation");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.captured_at_milliseconds));
    lua_setfield(state, -2, "captured_at_milliseconds");
    lua_pushstring(state, snapshot.surface_id.c_str());
    lua_setfield(state, -2, "surface_id");
    lua_pushstring(state, snapshot.surface_title.c_str());
    lua_setfield(state, -2, "surface_title");

    lua_createtable(state, static_cast<int>(snapshot.elements.size()), 0);
    for (std::size_t index = 0; index < snapshot.elements.size(); ++index) {
        PushDebugUiSnapshotElement(state, snapshot.elements[index]);
        lua_rawseti(state, -2, static_cast<lua_Integer>(index + 1));
    }
    lua_setfield(state, -2, "elements");
    return 1;
}

int LuaUiFindElement(lua_State* state) {
    const auto* label = luaL_checkstring(state, 1);
    const auto* surface_id = lua_gettop(state) >= 2 && !lua_isnil(state, 2) ? luaL_checkstring(state, 2) : nullptr;

    DebugUiSurfaceSnapshot snapshot;
    if (!sdmod::TryGetLatestDebugUiSurfaceSnapshot(&snapshot)) {
        lua_pushnil(state);
        return 1;
    }

    const auto* element = FindBestSnapshotElement(
        snapshot,
        label != nullptr ? label : "",
        surface_id != nullptr ? surface_id : "");
    if (element == nullptr) {
        lua_pushnil(state);
        return 1;
    }

    PushDebugUiSnapshotElement(state, *element);
    return 1;
}

int LuaUiFindAction(lua_State* state) {
    const auto* action_id = luaL_checkstring(state, 1);
    const auto* surface_id = lua_gettop(state) >= 2 && !lua_isnil(state, 2) ? luaL_checkstring(state, 2) : nullptr;

    DebugUiSnapshotElement element;
    if (!sdmod::TryFindDebugUiActionElement(
            action_id != nullptr ? action_id : "",
            surface_id != nullptr ? surface_id : "",
            &element)) {
        lua_pushnil(state);
        return 1;
    }

    PushDebugUiSnapshotElement(state, element);
    return 1;
}

int LuaUiGetActionDispatch(lua_State* state) {
    const auto request_id =
        lua_gettop(state) >= 1 && !lua_isnil(state, 1) ? static_cast<std::uint64_t>(luaL_checkinteger(state, 1)) : 0;

    DebugUiActionDispatchSnapshot snapshot;
    if (!sdmod::TryGetDebugUiActionDispatchSnapshot(request_id, &snapshot)) {
        lua_pushnil(state);
        return 1;
    }

    lua_createtable(state, 0, 13);
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.request_id));
    lua_setfield(state, -2, "request_id");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.queued_at_milliseconds));
    lua_setfield(state, -2, "queued_at_milliseconds");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.started_at_milliseconds));
    lua_setfield(state, -2, "started_at_milliseconds");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.completed_at_milliseconds));
    lua_setfield(state, -2, "completed_at_milliseconds");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.snapshot_generation));
    lua_setfield(state, -2, "snapshot_generation");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.owner_address));
    lua_setfield(state, -2, "owner_address");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.control_address));
    lua_setfield(state, -2, "control_address");
    lua_pushstring(state, snapshot.action_id.c_str());
    lua_setfield(state, -2, "action_id");
    lua_pushstring(state, snapshot.target_label.c_str());
    lua_setfield(state, -2, "target_label");
    lua_pushstring(state, snapshot.surface_id.c_str());
    lua_setfield(state, -2, "surface_id");
    lua_pushstring(state, snapshot.dispatch_kind.c_str());
    lua_setfield(state, -2, "dispatch_kind");
    lua_pushstring(state, snapshot.status.c_str());
    lua_setfield(state, -2, "status");
    lua_pushstring(state, snapshot.error_message.c_str());
    lua_setfield(state, -2, "error_message");
    return 1;
}

int LuaUiActivateAction(lua_State* state) {
    const auto* action_id = luaL_checkstring(state, 1);
    const auto* surface_id = lua_gettop(state) >= 2 && !lua_isnil(state, 2) ? luaL_checkstring(state, 2) : nullptr;

    std::string error_message;
    std::uint64_t request_id = 0;
    if (!sdmod::TryActivateDebugUiAction(
            action_id != nullptr ? action_id : "",
            surface_id != nullptr ? surface_id : "",
            &request_id,
            &error_message)) {
        lua_pushboolean(state, 0);
        lua_pushstring(state, error_message.c_str());
        return 2;
    }

    lua_pushboolean(state, 1);
    lua_pushinteger(state, static_cast<lua_Integer>(request_id));
    return 2;
}

int LuaUiActivateElement(lua_State* state) {
    const auto* label = luaL_checkstring(state, 1);
    const auto* surface_id = lua_gettop(state) >= 2 && !lua_isnil(state, 2) ? luaL_checkstring(state, 2) : nullptr;

    std::string error_message;
    std::uint64_t request_id = 0;
    if (!sdmod::TryActivateDebugUiElement(
            label != nullptr ? label : "",
            surface_id != nullptr ? surface_id : "",
            &request_id,
            &error_message)) {
        lua_pushboolean(state, 0);
        lua_pushstring(state, error_message.c_str());
        return 2;
    }

    lua_pushboolean(state, 1);
    lua_pushinteger(state, static_cast<lua_Integer>(request_id));
    return 2;
}

void PushUiPropertySnapshotTable(lua_State* state, const sdmod::UiPropertySnapshot& prop) {
    lua_createtable(state, 0, 3);
    lua_pushstring(state, prop.name.c_str());
    lua_setfield(state, -2, "name");

    switch (prop.kind) {
        case sdmod::UiPropertyKind::String:
            lua_pushstring(state, prop.string_value.c_str());
            lua_setfield(state, -2, "value");
            lua_pushstring(state, "string");
            lua_setfield(state, -2, "kind");
            break;
        case sdmod::UiPropertyKind::Integer:
            lua_pushinteger(state, prop.integer_value);
            lua_setfield(state, -2, "value");
            lua_pushstring(state, "integer");
            lua_setfield(state, -2, "kind");
            break;
        case sdmod::UiPropertyKind::Number:
            lua_pushnumber(state, prop.number_value);
            lua_setfield(state, -2, "value");
            lua_pushstring(state, "number");
            lua_setfield(state, -2, "kind");
            break;
        case sdmod::UiPropertyKind::Boolean:
            lua_pushboolean(state, prop.boolean_value ? 1 : 0);
            lua_setfield(state, -2, "value");
            lua_pushstring(state, "boolean");
            lua_setfield(state, -2, "kind");
            break;
    }
}

void PushUiActionSnapshotTable(lua_State* state, const sdmod::UiActionSnapshot& action) {
    lua_createtable(state, 0, 4);
    lua_pushstring(state, action.id.c_str());
    lua_setfield(state, -2, "id");
    lua_pushstring(state, action.label.c_str());
    lua_setfield(state, -2, "label");
    lua_pushstring(state, action.element_id.c_str());
    lua_setfield(state, -2, "element_id");
    lua_pushboolean(state, action.enabled ? 1 : 0);
    lua_setfield(state, -2, "enabled");
}

void PushUiElementSnapshotTable(lua_State* state, const sdmod::UiElementSnapshot& element) {
    lua_createtable(state, 0, 11);
    lua_pushstring(state, element.id.c_str());
    lua_setfield(state, -2, "id");
    lua_pushstring(state, element.kind.c_str());
    lua_setfield(state, -2, "kind");
    lua_pushstring(state, element.label.c_str());
    lua_setfield(state, -2, "label");
    lua_pushstring(state, element.text.c_str());
    lua_setfield(state, -2, "text");
    lua_pushboolean(state, element.visible ? 1 : 0);
    lua_setfield(state, -2, "visible");
    lua_pushboolean(state, element.interactive ? 1 : 0);
    lua_setfield(state, -2, "interactive");
    lua_pushboolean(state, element.enabled ? 1 : 0);
    lua_setfield(state, -2, "enabled");
    lua_pushboolean(state, element.selected ? 1 : 0);
    lua_setfield(state, -2, "selected");

    if (!element.state.empty()) {
        lua_createtable(state, static_cast<int>(element.state.size()), 0);
        for (std::size_t i = 0; i < element.state.size(); ++i) {
            PushUiPropertySnapshotTable(state, element.state[i]);
            lua_rawseti(state, -2, static_cast<lua_Integer>(i + 1));
        }
        lua_setfield(state, -2, "state");
    }

    if (!element.actions.empty()) {
        lua_createtable(state, static_cast<int>(element.actions.size()), 0);
        for (std::size_t i = 0; i < element.actions.size(); ++i) {
            PushUiActionSnapshotTable(state, element.actions[i]);
            lua_rawseti(state, -2, static_cast<lua_Integer>(i + 1));
        }
        lua_setfield(state, -2, "actions");
    }

    if (!element.children.empty()) {
        lua_createtable(state, static_cast<int>(element.children.size()), 0);
        for (std::size_t i = 0; i < element.children.size(); ++i) {
            PushUiElementSnapshotTable(state, element.children[i]);
            lua_rawseti(state, -2, static_cast<lua_Integer>(i + 1));
        }
        lua_setfield(state, -2, "children");
    }
}

int LuaUiGetState(lua_State* state) {
    auto snapshot = sdmod::BuildRuntimeUiStateSnapshot();
    if (!snapshot.available) {
        lua_pushnil(state);
        return 1;
    }

    lua_createtable(state, 0, 7);

    lua_pushboolean(state, 1);
    lua_setfield(state, -2, "available");

    lua_pushstring(state, snapshot.scene.c_str());
    lua_setfield(state, -2, "scene");

    lua_pushstring(state, snapshot.surface.c_str());
    lua_setfield(state, -2, "surface");

    lua_pushstring(state, snapshot.surface_title.c_str());
    lua_setfield(state, -2, "surface_title");

    if (!snapshot.details.empty()) {
        lua_createtable(state, static_cast<int>(snapshot.details.size()), 0);
        for (std::size_t i = 0; i < snapshot.details.size(); ++i) {
            PushUiPropertySnapshotTable(state, snapshot.details[i]);
            lua_rawseti(state, -2, static_cast<lua_Integer>(i + 1));
        }
        lua_setfield(state, -2, "details");
    }

    if (!snapshot.actions.empty()) {
        lua_createtable(state, static_cast<int>(snapshot.actions.size()), 0);
        for (std::size_t i = 0; i < snapshot.actions.size(); ++i) {
            PushUiActionSnapshotTable(state, snapshot.actions[i]);
            lua_rawseti(state, -2, static_cast<lua_Integer>(i + 1));
        }
        lua_setfield(state, -2, "actions");
    }

    lua_createtable(state, static_cast<int>(snapshot.elements.size()), 0);
    for (std::size_t i = 0; i < snapshot.elements.size(); ++i) {
        PushUiElementSnapshotTable(state, snapshot.elements[i]);
        lua_rawseti(state, -2, static_cast<lua_Integer>(i + 1));
    }
    lua_setfield(state, -2, "elements");

    return 1;
}

int LuaUiPerform(lua_State* state) {
    sdmod::UiActionRequest request;

    if (lua_isstring(state, 1)) {
        request.action_id = lua_tostring(state, 1);
    } else if (lua_istable(state, 1)) {
        lua_getfield(state, 1, "action_id");
        if (lua_isstring(state, -1)) {
            request.action_id = lua_tostring(state, -1);
        }
        lua_pop(state, 1);

        lua_getfield(state, 1, "element_id");
        if (lua_isstring(state, -1)) {
            request.element_id = lua_tostring(state, -1);
        }
        lua_pop(state, 1);

        lua_getfield(state, 1, "value");
        if (lua_isstring(state, -1)) {
            request.value = lua_tostring(state, -1);
        }
        lua_pop(state, 1);
    } else {
        lua_pushboolean(state, 0);
        lua_pushstring(state, "expected string or table argument");
        return 2;
    }

    std::string status_message;
    if (sdmod::ExecuteRuntimeUiAction(request, &status_message)) {
        lua_pushboolean(state, 1);
        lua_pushstring(state, status_message.c_str());
        return 2;
    }

    lua_pushboolean(state, 0);
    lua_pushstring(state, status_message.c_str());
    return 2;
}

}  // namespace

void RegisterLuaUiBindings(lua_State* state) {
    lua_createtable(state, 0, 9);
    RegisterFunction(state, &LuaUiGetSurfaceId, "get_surface_id");
    RegisterFunction(state, &LuaUiGetSnapshot, "get_snapshot");
    RegisterFunction(state, &LuaUiFindElement, "find_element");
    RegisterFunction(state, &LuaUiFindAction, "find_action");
    RegisterFunction(state, &LuaUiGetActionDispatch, "get_action_dispatch");
    RegisterFunction(state, &LuaUiActivateAction, "activate_action");
    RegisterFunction(state, &LuaUiActivateElement, "activate_element");
    RegisterFunction(state, &LuaUiGetState, "get_state");
    RegisterFunction(state, &LuaUiPerform, "perform");
    lua_setfield(state, -2, "ui");
}

}  // namespace sdmod::detail
