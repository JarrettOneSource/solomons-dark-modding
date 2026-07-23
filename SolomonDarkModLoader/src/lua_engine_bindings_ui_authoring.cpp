#include "lua_engine_bindings_internal.h"

#include "logger.h"
#include "lua_ui_runtime.h"
#include "multiplayer_local_transport.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <initializer_list>
#include <string>
#include <string_view>
#include <utility>

namespace sdmod::detail {
namespace {

LoadedLuaMod* RequireUiMod(lua_State* state, const char* api_name) {
    auto* mod = GetLoadedLuaMod(state);
    if (mod == nullptr) {
        luaL_error(state, "%s is unavailable", api_name);
    }
    return mod;
}

bool IsKnownField(
    std::string_view field,
    std::initializer_list<std::string_view> known) {
    return std::find(known.begin(), known.end(), field) != known.end();
}

void RejectUnknownFields(
    lua_State* state,
    int index,
    const char* api_name,
    std::initializer_list<std::string_view> known) {
    const int absolute = lua_absindex(state, index);
    lua_pushnil(state);
    while (lua_next(state, absolute) != 0) {
        if (lua_type(state, -2) != LUA_TSTRING) {
            lua_pop(state, 2);
            luaL_error(state, "%s options accept only named fields", api_name);
        }
        std::size_t length = 0;
        const auto* field = lua_tolstring(state, -2, &length);
        if (!IsKnownField(std::string_view(field, length), known)) {
            const std::string owned(field, length);
            lua_pop(state, 2);
            luaL_error(
                state, "%s received unknown field '%s'", api_name, owned.c_str());
        }
        lua_pop(state, 1);
    }
}

std::string ReadStringField(
    lua_State* state,
    int table,
    const char* field,
    const char* api_name,
    bool required,
    std::size_t maximum_bytes) {
    lua_getfield(state, table, field);
    if (lua_isnil(state, -1) && !required) {
        lua_pop(state, 1);
        return {};
    }
    if (lua_type(state, -1) != LUA_TSTRING) {
        luaL_error(state, "%s options.%s must be a string", api_name, field);
    }
    std::size_t length = 0;
    const auto* value = lua_tolstring(state, -1, &length);
    if ((required && length == 0) || length > maximum_bytes) {
        luaL_error(
            state,
            "%s options.%s must contain %s through %zu bytes",
            api_name,
            field,
            required ? "1" : "0",
            maximum_bytes);
    }
    std::string result(value, length);
    lua_pop(state, 1);
    return result;
}

float ReadNumberField(
    lua_State* state,
    int table,
    const char* field,
    const char* api_name,
    float default_value) {
    lua_getfield(state, table, field);
    if (lua_isnil(state, -1)) {
        lua_pop(state, 1);
        return default_value;
    }
    if (!lua_isnumber(state, -1)) {
        luaL_error(state, "%s options.%s must be a number", api_name, field);
    }
    const auto value = static_cast<float>(lua_tonumber(state, -1));
    lua_pop(state, 1);
    if (!std::isfinite(value) || value < 0.0f || value > 1.0f) {
        luaL_error(
            state, "%s options.%s must be finite and between 0 and 1", api_name, field);
    }
    return value;
}

bool ReadBooleanField(
    lua_State* state,
    int table,
    const char* field,
    const char* api_name,
    bool default_value) {
    lua_getfield(state, table, field);
    if (lua_isnil(state, -1)) {
        lua_pop(state, 1);
        return default_value;
    }
    if (!lua_isboolean(state, -1)) {
        luaL_error(state, "%s options.%s must be a boolean", api_name, field);
    }
    const bool value = lua_toboolean(state, -1) != 0;
    lua_pop(state, 1);
    return value;
}

LuaUiRect ReadRect(
    lua_State* state,
    int table,
    const char* api_name,
    LuaUiRect default_rect) {
    default_rect.x = ReadNumberField(state, table, "x", api_name, default_rect.x);
    default_rect.y = ReadNumberField(state, table, "y", api_name, default_rect.y);
    default_rect.width = ReadNumberField(
        state, table, "width", api_name, default_rect.width);
    default_rect.height = ReadNumberField(
        state, table, "height", api_name, default_rect.height);
    if (default_rect.width <= 0.0f || default_rect.height <= 0.0f ||
        default_rect.x + default_rect.width > 1.0f ||
        default_rect.y + default_rect.height > 1.0f) {
        luaL_error(
            state, "%s normalized rectangle must have positive size and fit its parent", api_name);
    }
    return default_rect;
}

std::uint64_t ReadHandle(lua_State* state, int index, const char* api_name) {
    if (!lua_isinteger(state, index) || lua_tointeger(state, index) <= 0) {
        luaL_error(state, "%s handle must be a positive integer", api_name);
    }
    return static_cast<std::uint64_t>(lua_tointeger(state, index));
}

void CheckOptionsTable(lua_State* state, int index, const char* api_name) {
    if (!lua_istable(state, index)) {
        luaL_error(state, "%s options must be a table", api_name);
    }
}

int LuaUiCreateSurface(lua_State* state) {
    constexpr const char* kApiName = "sd.ui.create_surface";
    CheckOptionsTable(state, 1, kApiName);
    const int options = lua_absindex(state, 1);
    RejectUnknownFields(
        state, options, kApiName,
        {"id", "title", "x", "y", "width", "height", "modal", "close_on_escape"});
    LuaUiSurfaceDefinition definition;
    definition.id = ReadStringField(
        state, options, "id", kApiName, true, kLuaUiMaximumIdentifierBytes);
    definition.title = ReadStringField(
        state, options, "title", kApiName, false, kLuaUiMaximumTitleBytes);
    definition.rect = ReadRect(state, options, kApiName, definition.rect);
    definition.modal = ReadBooleanField(
        state, options, "modal", kApiName, true);
    definition.close_on_escape = ReadBooleanField(
        state, options, "close_on_escape", kApiName, true);

    auto* mod = RequireUiMod(state, kApiName);
    std::uint64_t handle = 0;
    std::string error;
    if (!CreateLuaUiSurface(
            mod->descriptor.id, std::move(definition), &handle, &error)) {
        return luaL_error(state, "%s: %s", kApiName, error.c_str());
    }
    lua_pushinteger(state, static_cast<lua_Integer>(handle));
    return 1;
}

int CreateElement(lua_State* state, LuaUiElementKind kind) {
    const char* api_name = kind == LuaUiElementKind::Panel
        ? "sd.ui.create_panel"
        : kind == LuaUiElementKind::Label
            ? "sd.ui.create_label"
            : "sd.ui.create_button";
    const auto parent = ReadHandle(state, 1, api_name);
    CheckOptionsTable(state, 2, api_name);
    const int options = lua_absindex(state, 2);
    if (kind == LuaUiElementKind::Panel) {
        RejectUnknownFields(
            state, options, api_name, {"id", "x", "y", "width", "height"});
    } else if (kind == LuaUiElementKind::Label) {
        RejectUnknownFields(
            state, options, api_name,
            {"id", "text", "x", "y", "width", "height"});
    } else {
        RejectUnknownFields(
            state, options, api_name,
            {"id", "label", "x", "y", "width", "height", "on_activate", "execution", "close_on_activate", "enabled"});
    }

    LuaUiElementDefinition definition;
    definition.kind = kind;
    definition.id = ReadStringField(
        state, options, "id", api_name, true, kLuaUiMaximumIdentifierBytes);
    if (kind == LuaUiElementKind::Label) {
        definition.text = ReadStringField(
            state, options, "text", api_name, true, kLuaUiMaximumTextBytes);
        definition.rect = ReadRect(
            state, options, api_name, LuaUiRect{0.05f, 0.1f, 0.9f, 0.1f});
    } else if (kind == LuaUiElementKind::Button) {
        definition.text = ReadStringField(
            state, options, "label", api_name, true, kLuaUiMaximumTextBytes);
        definition.rect = ReadRect(
            state, options, api_name, LuaUiRect{0.1f, 0.1f, 0.8f, 0.12f});
        const auto execution = ReadStringField(
            state, options, "execution", api_name, false, 16);
        if (execution.empty() || execution == "presentation") {
            definition.action_class = LuaUiActionClass::Presentation;
        } else if (execution == "simulation") {
            definition.action_class = LuaUiActionClass::Simulation;
        } else {
            return luaL_error(
                state, "%s options.execution must be 'presentation' or 'simulation'", api_name);
        }
        definition.close_on_activate = ReadBooleanField(
            state, options, "close_on_activate", api_name, false);
        definition.enabled = ReadBooleanField(
            state, options, "enabled", api_name, true);
        lua_getfield(state, options, "on_activate");
        if (!lua_isfunction(state, -1)) {
            return luaL_error(state, "%s options.on_activate must be a function", api_name);
        }
        lua_pop(state, 1);
    } else {
        definition.rect = ReadRect(
            state, options, api_name, LuaUiRect{0.0f, 0.0f, 1.0f, 1.0f});
    }

    auto* mod = RequireUiMod(state, api_name);
    std::uint64_t handle = 0;
    std::uint64_t surface_handle = 0;
    std::string error;
    if (!CreateLuaUiElement(
            mod->descriptor.id,
            parent,
            definition,
            &handle,
            &surface_handle,
            &error)) {
        return luaL_error(state, "%s: %s", api_name, error.c_str());
    }
    if (kind == LuaUiElementKind::Button) {
        lua_getfield(state, options, "on_activate");
        const int reference = luaL_ref(state, LUA_REGISTRYINDEX);
        LuaUiSurfaceSnapshot surface;
        if (!TryGetLuaUiSurfaceSnapshot(
                mod->descriptor.id, surface_handle, &surface)) {
            luaL_unref(state, LUA_REGISTRYINDEX, reference);
            return luaL_error(state, "%s: created surface disappeared", api_name);
        }
        mod->ui_actions.push_back(LuaUiActionRegistration{
            surface_handle,
            handle,
            surface.id,
            definition.id,
            definition.action_class,
            reference,
        });
    }
    lua_pushinteger(state, static_cast<lua_Integer>(handle));
    return 1;
}

int LuaUiCreatePanel(lua_State* state) {
    return CreateElement(state, LuaUiElementKind::Panel);
}

int LuaUiCreateLabel(lua_State* state) {
    return CreateElement(state, LuaUiElementKind::Label);
}

int LuaUiCreateButton(lua_State* state) {
    return CreateElement(state, LuaUiElementKind::Button);
}

int SetSurfaceVisibility(lua_State* state, bool visible) {
    const char* api_name = visible ? "sd.ui.show" : "sd.ui.hide";
    auto* mod = RequireUiMod(state, api_name);
    const auto handle = ReadHandle(state, 1, api_name);
    std::string error;
    if (!SetLuaUiSurfaceVisible(
            mod->descriptor.id, handle, visible, &error)) {
        return luaL_error(state, "%s: %s", api_name, error.c_str());
    }
    lua_pushboolean(state, 1);
    return 1;
}

int LuaUiShow(lua_State* state) { return SetSurfaceVisibility(state, true); }
int LuaUiHide(lua_State* state) { return SetSurfaceVisibility(state, false); }

void ReleaseSurfaceCallbacks(LoadedLuaMod* mod, std::uint64_t surface_handle) {
    if (mod == nullptr) return;
    for (auto it = mod->ui_actions.begin(); it != mod->ui_actions.end();) {
        if (it->surface_handle != surface_handle) {
            ++it;
            continue;
        }
        if (mod->state != nullptr && it->callback_reference != LUA_NOREF) {
            luaL_unref(mod->state, LUA_REGISTRYINDEX, it->callback_reference);
        }
        it = mod->ui_actions.erase(it);
    }
}

int LuaUiDestroy(lua_State* state) {
    constexpr const char* kApiName = "sd.ui.destroy";
    auto* mod = RequireUiMod(state, kApiName);
    const auto handle = ReadHandle(state, 1, kApiName);
    std::string error;
    if (!DestroyLuaUiSurface(mod->descriptor.id, handle, &error)) {
        return luaL_error(state, "%s: %s", kApiName, error.c_str());
    }
    ReleaseSurfaceCallbacks(mod, handle);
    lua_pushboolean(state, 1);
    return 1;
}

int LuaUiSetText(lua_State* state) {
    constexpr const char* kApiName = "sd.ui.set_text";
    auto* mod = RequireUiMod(state, kApiName);
    const auto handle = ReadHandle(state, 1, kApiName);
    std::size_t length = 0;
    const auto* text = luaL_checklstring(state, 2, &length);
    std::string error;
    if (!SetLuaUiElementText(
            mod->descriptor.id, handle, std::string(text, length), &error)) {
        return luaL_error(state, "%s: %s", kApiName, error.c_str());
    }
    lua_pushboolean(state, 1);
    return 1;
}

int LuaUiSetEnabled(lua_State* state) {
    constexpr const char* kApiName = "sd.ui.set_enabled";
    auto* mod = RequireUiMod(state, kApiName);
    const auto handle = ReadHandle(state, 1, kApiName);
    if (!lua_isboolean(state, 2)) {
        return luaL_error(state, "%s enabled must be a boolean", kApiName);
    }
    std::string error;
    if (!SetLuaUiButtonEnabled(
            mod->descriptor.id, handle, lua_toboolean(state, 2) != 0, &error)) {
        return luaL_error(state, "%s: %s", kApiName, error.c_str());
    }
    lua_pushboolean(state, 1);
    return 1;
}

int LuaUiFocus(lua_State* state) {
    constexpr const char* kApiName = "sd.ui.focus";
    auto* mod = RequireUiMod(state, kApiName);
    const auto handle = ReadHandle(state, 1, kApiName);
    std::string error;
    if (!FocusLuaUiButton(mod->descriptor.id, handle, &error)) {
        return luaL_error(state, "%s: %s", kApiName, error.c_str());
    }
    lua_pushboolean(state, 1);
    return 1;
}

void PushElement(lua_State* state, const LuaUiElementSnapshot& element) {
    lua_createtable(state, 0, 12);
    lua_pushinteger(state, static_cast<lua_Integer>(element.handle));
    lua_setfield(state, -2, "handle");
    lua_pushinteger(state, static_cast<lua_Integer>(element.parent_handle));
    lua_setfield(state, -2, "parent_handle");
    const char* kind = element.kind == LuaUiElementKind::Panel
        ? "panel" : element.kind == LuaUiElementKind::Label ? "label" : "button";
    lua_pushstring(state, kind);
    lua_setfield(state, -2, "kind");
    lua_pushlstring(state, element.id.data(), element.id.size());
    lua_setfield(state, -2, "id");
    lua_pushlstring(state, element.text.data(), element.text.size());
    lua_setfield(state, -2, "text");
    lua_pushboolean(state, element.enabled ? 1 : 0);
    lua_setfield(state, -2, "enabled");
    lua_pushboolean(state, element.selected ? 1 : 0);
    lua_setfield(state, -2, "selected");
    lua_pushstring(
        state,
        element.action_class == LuaUiActionClass::Simulation
            ? "simulation" : "presentation");
    lua_setfield(state, -2, "execution");
    lua_pushnumber(state, element.rect.x);
    lua_setfield(state, -2, "x");
    lua_pushnumber(state, element.rect.y);
    lua_setfield(state, -2, "y");
    lua_pushnumber(state, element.rect.width);
    lua_setfield(state, -2, "width");
    lua_pushnumber(state, element.rect.height);
    lua_setfield(state, -2, "height");
}

int LuaUiGetAuthoredState(lua_State* state) {
    constexpr const char* kApiName = "sd.ui.get_authored_state";
    auto* mod = RequireUiMod(state, kApiName);
    const auto handle = ReadHandle(state, 1, kApiName);
    LuaUiSurfaceSnapshot surface;
    if (!TryGetLuaUiSurfaceSnapshot(mod->descriptor.id, handle, &surface)) {
        lua_pushnil(state);
        return 1;
    }
    lua_createtable(state, 0, 13);
    lua_pushinteger(state, static_cast<lua_Integer>(surface.handle));
    lua_setfield(state, -2, "handle");
    lua_pushlstring(state, surface.id.data(), surface.id.size());
    lua_setfield(state, -2, "id");
    lua_pushlstring(state, surface.title.data(), surface.title.size());
    lua_setfield(state, -2, "title");
    lua_pushboolean(state, surface.visible ? 1 : 0);
    lua_setfield(state, -2, "visible");
    lua_pushboolean(state, surface.modal ? 1 : 0);
    lua_setfield(state, -2, "modal");
    lua_pushinteger(state, static_cast<lua_Integer>(surface.focused_button_handle));
    lua_setfield(state, -2, "focused_handle");
    lua_pushnumber(state, surface.rect.x);
    lua_setfield(state, -2, "x");
    lua_pushnumber(state, surface.rect.y);
    lua_setfield(state, -2, "y");
    lua_pushnumber(state, surface.rect.width);
    lua_setfield(state, -2, "width");
    lua_pushnumber(state, surface.rect.height);
    lua_setfield(state, -2, "height");
    lua_createtable(state, static_cast<int>(surface.elements.size()), 0);
    for (std::size_t index = 0; index < surface.elements.size(); ++index) {
        PushElement(state, surface.elements[index]);
        lua_rawseti(state, -2, static_cast<lua_Integer>(index + 1));
    }
    lua_setfield(state, -2, "elements");
    return 1;
}

const LuaUiActionRegistration* FindActionRegistration(
    const LoadedLuaMod& mod,
    const LuaUiPendingAction& action) {
    const auto found = std::find_if(
        mod.ui_actions.begin(), mod.ui_actions.end(),
        [&](const LuaUiActionRegistration& registration) {
            return registration.surface_id == action.surface_id &&
                registration.action_id == action.action_id &&
                registration.action_class == action.action_class;
        });
    return found == mod.ui_actions.end() ? nullptr : &*found;
}

}  // namespace

void RegisterLuaUiAuthoringBindings(lua_State* state) {
    RegisterFunction(state, &LuaUiCreateSurface, "create_surface");
    RegisterFunction(state, &LuaUiCreatePanel, "create_panel");
    RegisterFunction(state, &LuaUiCreateLabel, "create_label");
    RegisterFunction(state, &LuaUiCreateButton, "create_button");
    RegisterFunction(state, &LuaUiShow, "show");
    RegisterFunction(state, &LuaUiHide, "hide");
    RegisterFunction(state, &LuaUiDestroy, "destroy");
    RegisterFunction(state, &LuaUiSetText, "set_text");
    RegisterFunction(state, &LuaUiSetEnabled, "set_enabled");
    RegisterFunction(state, &LuaUiFocus, "focus");
    RegisterFunction(state, &LuaUiGetAuthoredState, "get_authored_state");
}

void ClearLuaUiBindingsForMod(LoadedLuaMod* mod) {
    if (mod == nullptr) return;
    for (auto& action : mod->ui_actions) {
        if (mod->state != nullptr && action.callback_reference != LUA_NOREF) {
            luaL_unref(mod->state, LUA_REGISTRYINDEX, action.callback_reference);
        }
        action.callback_reference = LUA_NOREF;
    }
    mod->ui_actions.clear();
    ClearLuaUiForMod(mod->descriptor.id);
}

void DispatchPendingLuaUiActions() {
    auto actions = TakePendingLuaUiActions();
    for (const auto& action : actions) {
        const auto mod_it = std::find_if(
            LoadedLuaModsStorage().begin(), LoadedLuaModsStorage().end(),
            [&](const auto& candidate) {
                return candidate != nullptr &&
                    candidate->descriptor.id == action.mod_id;
            });
        if (mod_it == LoadedLuaModsStorage().end() ||
            (*mod_it)->state == nullptr) {
            continue;
        }
        auto* mod = mod_it->get();
        const auto* registration = FindActionRegistration(*mod, action);
        if (registration == nullptr ||
            registration->callback_reference == LUA_NOREF) {
            continue;
        }
        if (action.action_class == LuaUiActionClass::Simulation &&
            !action.routed && !multiplayer::IsLuaModSimulationAuthority()) {
            std::string error;
            std::uint64_t routed_request_id = 0;
            if (!multiplayer::QueueLuaUiSimulationAction(
                    action.mod_id,
                    action.surface_id,
                    action.action_id,
                    &routed_request_id,
                    &error)) {
                LogLuaMessage(*mod, "sd.ui simulation action route failed: " + error);
            }
            continue;
        }
        if (action.routed && !multiplayer::IsLuaModSimulationAuthority()) {
            continue;
        }

        lua_rawgeti(
            mod->state, LUA_REGISTRYINDEX, registration->callback_reference);
        if (!lua_isfunction(mod->state, -1)) {
            lua_pop(mod->state, 1);
            continue;
        }
        lua_createtable(mod->state, 0, 7);
        lua_pushlstring(
            mod->state, action.surface_id.data(), action.surface_id.size());
        lua_setfield(mod->state, -2, "surface_id");
        lua_pushlstring(
            mod->state, action.action_id.data(), action.action_id.size());
        lua_setfield(mod->state, -2, "action_id");
        lua_pushstring(
            mod->state,
            action.action_class == LuaUiActionClass::Simulation
                ? "simulation" : "presentation");
        lua_setfield(mod->state, -2, "execution");
        const auto participant_id = action.participant_id != 0
            ? action.participant_id
            : multiplayer::GetLocalTransportParticipantId();
        lua_pushinteger(
            mod->state, static_cast<lua_Integer>(participant_id));
        lua_setfield(mod->state, -2, "participant_id");
        lua_pushinteger(
            mod->state, static_cast<lua_Integer>(action.request_id));
        lua_setfield(mod->state, -2, "request_id");
        lua_pushboolean(mod->state, action.routed ? 1 : 0);
        lua_setfield(mod->state, -2, "routed");
        if (lua_pcall(mod->state, 1, 0, 0) != LUA_OK) {
            const auto* message = lua_tostring(mod->state, -1);
            LogLuaMessage(
                *mod,
                "sd.ui action '" + action.action_id + "' failed: " +
                    (message == nullptr ? "unknown" : message));
            lua_pop(mod->state, 1);
        }
    }
}

}  // namespace sdmod::detail
