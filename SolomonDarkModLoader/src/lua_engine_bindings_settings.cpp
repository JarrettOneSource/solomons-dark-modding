#include "lua_engine_bindings_internal.h"

#include <Windows.h>

#include <algorithm>
#include <string>
#include <string_view>

namespace sdmod::detail {
namespace {

bool DeclaresSettingsCapability(const LoadedLuaMod& mod) {
    return std::find(
        mod.descriptor.required_capabilities.begin(),
        mod.descriptor.required_capabilities.end(),
        "settings.self") != mod.descriptor.required_capabilities.end();
}

LoadedLuaMod* RequireSettingsMod(
    lua_State* state,
    const char* api_name) {
    auto* mod = GetLoadedLuaMod(state);
    if (mod == nullptr ||
        !DeclaresSettingsCapability(*mod) ||
        !mod->settings_available) {
        luaL_error(
            state,
            "%s requires a valid settings declaration and settings.self",
            api_name);
    }
    return mod;
}

void RequireArgumentCount(
    lua_State* state,
    int expected,
    const char* api_name) {
    if (lua_gettop(state) != expected) {
        luaL_error(
            state,
            "%s expects exactly %d argument%s",
            api_name,
            expected,
            expected == 1 ? "" : "s");
    }
}

void PushValue(
    lua_State* state,
    const ModSettingValue& value) {
    switch (value.type) {
    case ModSettingValueType::Boolean:
        lua_pushboolean(state, value.boolean_value ? 1 : 0);
        break;
    case ModSettingValueType::Number:
        lua_pushnumber(
            state,
            static_cast<lua_Number>(value.number_value));
        break;
    case ModSettingValueType::String:
        lua_pushlstring(
            state,
            value.string_value.data(),
            value.string_value.size());
        break;
    }
}

int PushLookupError(
    lua_State* state,
    std::string_view key,
    const char* reason) {
    lua_pushnil(state);
    const auto message =
        "setting '" + std::string(key) + "' " + reason;
    lua_pushlstring(state, message.data(), message.size());
    return 2;
}

const ModSettingEntry* FindValueEntry(
    LoadedLuaMod* mod,
    std::string_view key,
    const ModSettingValue** value) {
    const auto* entry = mod->settings_declaration.Find(key);
    if (entry == nullptr || entry->type == ModSettingType::Action) {
        return nullptr;
    }
    const auto found = mod->effective_settings_values.find(
        std::string(key));
    if (found == mod->effective_settings_values.end()) {
        return nullptr;
    }
    *value = &found->second;
    return entry;
}

int LuaSettingsGet(lua_State* state) {
    constexpr const char* kApiName = "sd.settings.get";
    RequireArgumentCount(state, 1, kApiName);
    auto* mod = RequireSettingsMod(state, kApiName);
    size_t key_size = 0;
    const auto* key = luaL_checklstring(state, 1, &key_size);
    const std::string_view key_view(key, key_size);
    const ModSettingValue* value = nullptr;
    if (FindValueEntry(mod, key_view, &value) == nullptr) {
        return PushLookupError(
            state,
            key_view,
            "is unknown or has no value");
    }
    PushValue(state, *value);
    return 1;
}

int LuaSettingsGetAll(lua_State* state) {
    constexpr const char* kApiName = "sd.settings.get_all";
    RequireArgumentCount(state, 0, kApiName);
    auto* mod = RequireSettingsMod(state, kApiName);
    lua_createtable(
        state,
        0,
        static_cast<int>(mod->effective_settings_values.size()));
    for (const auto& [key, value] :
         mod->effective_settings_values) {
        PushValue(state, value);
        lua_setfield(state, -2, key.c_str());
    }
    return 1;
}

int LuaSettingsOnChanged(lua_State* state) {
    constexpr const char* kApiName = "sd.settings.on_changed";
    RequireArgumentCount(state, 1, kApiName);
    auto* mod = RequireSettingsMod(state, kApiName);
    luaL_checktype(state, 1, LUA_TFUNCTION);
    lua_pushvalue(state, 1);
    mod->settings_changed_callbacks.push_back(
        luaL_ref(state, LUA_REGISTRYINDEX));
    lua_pushboolean(state, 1);
    return 1;
}

int LuaSettingsOnAction(lua_State* state) {
    constexpr const char* kApiName = "sd.settings.on_action";
    RequireArgumentCount(state, 2, kApiName);
    auto* mod = RequireSettingsMod(state, kApiName);
    size_t key_size = 0;
    const auto* key = luaL_checklstring(state, 1, &key_size);
    luaL_checktype(state, 2, LUA_TFUNCTION);
    const std::string key_value(key, key_size);
    const auto* entry = mod->settings_declaration.Find(key_value);
    if (entry == nullptr || entry->type != ModSettingType::Action) {
        return PushLookupError(
            state,
            key_value,
            "is unknown or is not an action");
    }

    const auto existing =
        mod->settings_action_callbacks.find(key_value);
    if (existing != mod->settings_action_callbacks.end()) {
        luaL_unref(
            state,
            LUA_REGISTRYINDEX,
            existing->second);
    }
    lua_pushvalue(state, 2);
    mod->settings_action_callbacks[key_value] =
        luaL_ref(state, LUA_REGISTRYINDEX);
    lua_pushboolean(state, 1);
    return 1;
}

bool IsGameProcessForeground() {
    const auto foreground = GetForegroundWindow();
    if (foreground == nullptr) {
        return false;
    }
    DWORD process_id = 0;
    GetWindowThreadProcessId(foreground, &process_id);
    return process_id == GetCurrentProcessId();
}

bool TryMapKeybind(
    std::string_view keybind,
    int* virtual_key) {
    if (keybind.size() == 1 &&
        ((keybind[0] >= 'A' && keybind[0] <= 'Z') ||
         (keybind[0] >= '0' && keybind[0] <= '9'))) {
        *virtual_key = static_cast<unsigned char>(keybind[0]);
        return true;
    }
    if (keybind.size() >= 2 &&
        keybind.size() <= 3 &&
        keybind[0] == 'F') {
        if (keybind.size() == 3 && keybind[1] == '0') {
            return false;
        }
        int number = 0;
        for (std::size_t index = 1;
             index < keybind.size();
             ++index) {
            if (keybind[index] < '0' || keybind[index] > '9') {
                return false;
            }
            number = number * 10 + (keybind[index] - '0');
        }
        if (number >= 1 && number <= 24) {
            *virtual_key = VK_F1 + number - 1;
            return true;
        }
    }
    struct NamedKey {
        std::string_view name;
        int virtual_key;
    };
    static constexpr NamedKey kNamedKeys[] = {
        {"SPACE", VK_SPACE},
        {"TAB", VK_TAB},
        {"ENTER", VK_RETURN},
        {"SHIFT", VK_SHIFT},
        {"CTRL", VK_CONTROL},
        {"ALT", VK_MENU},
        {"UP", VK_UP},
        {"DOWN", VK_DOWN},
        {"LEFT", VK_LEFT},
        {"RIGHT", VK_RIGHT},
        {"MOUSE3", VK_MBUTTON},
        {"MOUSE4", VK_XBUTTON1},
        {"MOUSE5", VK_XBUTTON2},
    };
    const auto found = std::find_if(
        std::begin(kNamedKeys),
        std::end(kNamedKeys),
        [&](const NamedKey& named) {
            return named.name == keybind;
        });
    if (found == std::end(kNamedKeys)) {
        return false;
    }
    *virtual_key = found->virtual_key;
    return true;
}

int LuaSettingsIsKeybindDown(lua_State* state) {
    constexpr const char* kApiName =
        "sd.settings.is_keybind_down";
    RequireArgumentCount(state, 1, kApiName);
    auto* mod = RequireSettingsMod(state, kApiName);
    size_t key_size = 0;
    const auto* key = luaL_checklstring(state, 1, &key_size);
    const std::string_view key_view(key, key_size);
    const ModSettingValue* value = nullptr;
    const auto* entry =
        FindValueEntry(mod, key_view, &value);
    if (entry == nullptr ||
        entry->type != ModSettingType::Keybind) {
        return PushLookupError(
            state,
            key_view,
            "is unknown or is not a keybind");
    }
    if (value->string_value == "NONE" ||
        !IsGameProcessForeground()) {
        lua_pushboolean(state, 0);
        return 1;
    }
    int virtual_key = 0;
    if (!TryMapKeybind(value->string_value, &virtual_key)) {
        return PushLookupError(
            state,
            key_view,
            "has an invalid keybind value");
    }
    lua_pushboolean(
        state,
        (GetAsyncKeyState(virtual_key) & 0x8000) != 0);
    return 1;
}

void PushOperationResult(
    lua_State* state,
    const LuaSettingsOperationResult& result,
    bool include_changed) {
    lua_createtable(state, 0, include_changed ? 3 : 2);
    lua_pushboolean(state, result.ok ? 1 : 0);
    lua_setfield(state, -2, "ok");
    lua_pushlstring(
        state,
        result.error.data(),
        result.error.size());
    lua_setfield(state, -2, "error");
    if (include_changed) {
        lua_createtable(
            state,
            static_cast<int>(result.changed.size()),
            0);
        for (std::size_t index = 0;
             index < result.changed.size();
             ++index) {
            lua_pushlstring(
                state,
                result.changed[index].data(),
                result.changed[index].size());
            lua_rawseti(
                state,
                -2,
                static_cast<lua_Integer>(index + 1));
        }
        lua_setfield(state, -2, "changed");
    }
}

void RequirePrivileged(lua_State* state, const char* api_name) {
    if (GetLuaSettingsPrivilegedExecState() != state) {
        luaL_error(
            state,
            "%s is available only to the launcher exec pipe",
            api_name);
    }
}

int LuaPrivilegedSettingsReload(lua_State* state) {
    constexpr const char* kApiName = "sd.__settings_reload";
    RequirePrivileged(state, kApiName);
    RequireArgumentCount(state, 1, kApiName);
    size_t mod_id_size = 0;
    const auto* mod_id =
        luaL_checklstring(state, 1, &mod_id_size);
    const auto result = ReloadLuaSettings(
        std::string_view(mod_id, mod_id_size));
    PushOperationResult(state, result, true);
    return 1;
}

int LuaPrivilegedSettingsInvokeAction(lua_State* state) {
    constexpr const char* kApiName =
        "sd.__settings_invoke_action";
    RequirePrivileged(state, kApiName);
    RequireArgumentCount(state, 2, kApiName);
    size_t mod_id_size = 0;
    size_t key_size = 0;
    const auto* mod_id =
        luaL_checklstring(state, 1, &mod_id_size);
    const auto* key =
        luaL_checklstring(state, 2, &key_size);
    const auto result = InvokeLuaSettingsAction(
        std::string_view(mod_id, mod_id_size),
        std::string_view(key, key_size));
    PushOperationResult(state, result, false);
    return 1;
}

}  // namespace

void RegisterLuaSettingsBindings(lua_State* state) {
    lua_createtable(state, 0, 5);
    RegisterFunction(state, &LuaSettingsGet, "get");
    RegisterFunction(state, &LuaSettingsGetAll, "get_all");
    RegisterFunction(state, &LuaSettingsOnChanged, "on_changed");
    RegisterFunction(state, &LuaSettingsOnAction, "on_action");
    RegisterFunction(
        state,
        &LuaSettingsIsKeybindDown,
        "is_keybind_down");
    lua_setfield(state, -2, "settings");
}

void InstallLuaSettingsPrivilegedBindings(lua_State* state) {
    lua_getglobal(state, "sd");
    if (!lua_istable(state, -1)) {
        lua_pop(state, 1);
        return;
    }
    RegisterFunction(
        state,
        &LuaPrivilegedSettingsReload,
        "__settings_reload");
    RegisterFunction(
        state,
        &LuaPrivilegedSettingsInvokeAction,
        "__settings_invoke_action");
    lua_pop(state, 1);
}

void RemoveLuaSettingsPrivilegedBindings(lua_State* state) {
    lua_getglobal(state, "sd");
    if (!lua_istable(state, -1)) {
        lua_pop(state, 1);
        return;
    }
    lua_pushnil(state);
    lua_setfield(state, -2, "__settings_reload");
    lua_pushnil(state);
    lua_setfield(state, -2, "__settings_invoke_action");
    lua_pop(state, 1);
}

}  // namespace sdmod::detail
