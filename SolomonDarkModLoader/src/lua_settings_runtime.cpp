#include "lua_engine_internal.h"

#include "logger.h"
#include "multiplayer_local_transport.h"

extern "C" {
#include "lauxlib.h"
#include "lua.h"
}

#include <algorithm>
#include <filesystem>
#include <string>
#include <utility>
#include <vector>

namespace sdmod::detail {
namespace {

constexpr char kReplicatedSettingsModId[] = "SDMOD:settings";

thread_local lua_State* g_privileged_settings_exec_state = nullptr;

class ScopedSuspendedSettingsPrivilege final {
public:
    explicit ScopedSuspendedSettingsPrivilege(lua_State* callback_state)
        : callback_state_(callback_state),
          privileged_state_(g_privileged_settings_exec_state) {
        g_privileged_settings_exec_state = nullptr;
        if (callback_state_ == privileged_state_) {
            RemoveLuaSettingsPrivilegedBindings(callback_state_);
        }
    }

    ~ScopedSuspendedSettingsPrivilege() {
        if (callback_state_ == privileged_state_) {
            InstallLuaSettingsPrivilegedBindings(callback_state_);
        }
        g_privileged_settings_exec_state = privileged_state_;
    }

private:
    lua_State* callback_state_ = nullptr;
    lua_State* privileged_state_ = nullptr;
};

std::string JsonEscape(std::string_view value) {
    std::string escaped;
    for (const auto raw : value) {
        const auto character = static_cast<unsigned char>(raw);
        switch (character) {
        case '"':
            escaped.append("\\\"");
            break;
        case '\\':
            escaped.append("\\\\");
            break;
        case '\n':
            escaped.append("\\n");
            break;
        case '\r':
            escaped.append("\\r");
            break;
        case '\t':
            escaped.append("\\t");
            break;
        default:
            if (character >= 0x20) {
                escaped.push_back(static_cast<char>(character));
            }
            break;
        }
    }
    return escaped;
}

void LogSettingsError(
    std::string_view event,
    const LoadedLuaMod& mod,
    std::string_view error) {
    Log(
        "[mod-settings] {\"event\":\"" + JsonEscape(event) +
        "\",\"mod_id\":\"" + JsonEscape(mod.descriptor.id) +
        "\",\"error\":\"" + JsonEscape(error) + "\"}");
}

std::filesystem::path SettingsPathForMod(const LoadedLuaMod& mod) {
    return LuaRuntimeBootstrapStorage().stage_root /
        ".sdmod" /
        "mod-settings" /
        (mod.descriptor.id + ".json");
}

bool HasSettingsCapability(const LoadedLuaMod& mod) {
    return std::find(
        mod.descriptor.required_capabilities.begin(),
        mod.descriptor.required_capabilities.end(),
        "settings.self") != mod.descriptor.required_capabilities.end();
}

bool IsActiveClientSession() {
    return multiplayer::IsLocalTransportClient() &&
        multiplayer::GetLocalTransportAuthorityParticipantId() != 0;
}

LuaModValue ToReplicatedValue(const ModSettingValue& source) {
    LuaModValue value;
    switch (source.type) {
    case ModSettingValueType::Boolean:
        value.type = LuaModValueType::Boolean;
        value.boolean_value = source.boolean_value;
        break;
    case ModSettingValueType::Number:
        value.type = LuaModValueType::Number;
        value.number_value = source.number_value;
        break;
    case ModSettingValueType::String:
        value.type = LuaModValueType::String;
        value.string_value = source.string_value;
        break;
    }
    return value;
}

bool FromReplicatedValue(
    const LuaModValue& source,
    ModSettingValue* value) {
    switch (source.type) {
    case LuaModValueType::Boolean:
        *value = ModSettingValue::Boolean(source.boolean_value);
        return true;
    case LuaModValueType::Integer:
        *value = ModSettingValue::Number(
            static_cast<double>(source.integer_value));
        return true;
    case LuaModValueType::Number:
        *value = ModSettingValue::Number(source.number_value);
        return true;
    case LuaModValueType::String:
        *value = ModSettingValue::String(source.string_value);
        return true;
    default:
        return false;
    }
}

std::string ReplicatedKey(
    const LoadedLuaMod& mod,
    std::string_view setting_key) {
    return mod.descriptor.storage_key + "." +
        std::string(setting_key);
}

bool TryGetReplicatedValue(
    const LoadedLuaMod& mod,
    const ModSettingEntry& entry,
    ModSettingValue* value) {
    LuaModValue replicated;
    if (!TryGetLuaModStateValue(
            kReplicatedSettingsModId,
            ReplicatedKey(mod, entry.key),
            &replicated) ||
        !FromReplicatedValue(replicated, value)) {
        return false;
    }
    std::string validation_error;
    return ValidateModSettingValue(
        entry,
        *value,
        &validation_error);
}

bool PublishHostValue(
    const LoadedLuaMod& mod,
    const ModSettingEntry& entry,
    const ModSettingValue& value) {
    if (!multiplayer::IsLocalTransportHost() ||
        entry.scope != ModSettingScope::Host) {
        return true;
    }
    const auto key = ReplicatedKey(mod, entry.key);
    const auto replicated = ToReplicatedValue(value);
    std::uint64_t revision = 0;
    std::string error;
    if (!SetLuaModStateValue(
            kReplicatedSettingsModId,
            key,
            replicated,
            &revision,
            &error)) {
        LogSettingsError("replication_store_failed", mod, error);
        return false;
    }
    std::uint64_t stream_sequence = 0;
    if (!multiplayer::PublishAuthoritativeLuaModStateSet(
            kReplicatedSettingsModId,
            key,
            replicated,
            revision,
            &stream_sequence,
            &error)) {
        LogSettingsError("replication_publish_failed", mod, error);
        return false;
    }
    return true;
}

bool ReadLocalValues(
    LoadedLuaMod* mod,
    ModSettingValues* values,
    std::string* error_message) {
    values->clear();
    error_message->clear();
    for (const auto& entry : mod->settings_declaration.entries) {
        if (entry.type != ModSettingType::Action &&
            entry.has_default) {
            values->emplace(entry.key, entry.default_value);
        }
    }

    ModSettingsValuesResult persisted;
    bool file_found = false;
    std::string read_error;
    if (!LoadPersistedModSettings(
            SettingsPathForMod(*mod),
            mod->settings_declaration,
            &persisted,
            &file_found,
            &read_error)) {
        LogSettingsError(
            "persisted_read_failed",
            *mod,
            read_error);
        *error_message = read_error;
        return false;
    }
    if (file_found && !persisted.valid) {
        LogSettingsError(
            "persisted_schema_invalid",
            *mod,
            persisted.error);
        *error_message = persisted.error;
        return false;
    }
    for (const auto& warning : persisted.warnings) {
        LogSettingsError(
            "persisted_value_ignored",
            *mod,
            warning);
    }
    for (auto& [key, value] : persisted.values) {
        (*values)[key] = std::move(value);
    }
    return true;
}

void PushSettingValue(
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

void DispatchChanged(
    LoadedLuaMod* mod,
    const std::string& key,
    const ModSettingValue& next,
    const ModSettingValue& previous) {
    if (mod == nullptr || mod->state == nullptr) {
        return;
    }
    const auto callbacks = mod->settings_changed_callbacks;
    ScopedSuspendedSettingsPrivilege suspended_privilege(mod->state);
    for (const auto reference : callbacks) {
        lua_rawgeti(mod->state, LUA_REGISTRYINDEX, reference);
        lua_pushlstring(mod->state, key.data(), key.size());
        PushSettingValue(mod->state, next);
        PushSettingValue(mod->state, previous);
        if (lua_pcall(mod->state, 3, 0, 0) != LUA_OK) {
            const auto* error = lua_tostring(mod->state, -1);
            LogLuaMessage(
                *mod,
                "settings on_changed callback failed: " +
                    std::string(
                        error == nullptr
                            ? "unknown Lua error"
                            : error));
            lua_pop(mod->state, 1);
        }
    }
}

void ApplyEffectiveChange(
    LoadedLuaMod* mod,
    const ModSettingEntry& entry,
    const ModSettingValue& next,
    std::vector<std::string>* changed,
    bool notify) {
    const auto found =
        mod->effective_settings_values.find(entry.key);
    if (found != mod->effective_settings_values.end() &&
        found->second == next) {
        return;
    }
    const auto previous =
        found == mod->effective_settings_values.end()
            ? entry.default_value
            : found->second;
    mod->effective_settings_values[entry.key] = next;
    if (changed != nullptr) {
        changed->push_back(entry.key);
    }
    if (notify) {
        DispatchChanged(mod, entry.key, next, previous);
    }
}

LoadedLuaMod* FindLoadedSettingsMod(std::string_view mod_id) {
    const auto& mods = LoadedLuaModsStorage();
    const auto found = std::find_if(
        mods.begin(),
        mods.end(),
        [&](const std::unique_ptr<LoadedLuaMod>& mod) {
            return mod != nullptr &&
                mod->descriptor.id == mod_id;
        });
    return found == mods.end() ? nullptr : found->get();
}

}  // namespace

bool InitializeLuaSettingsForMod(
    LoadedLuaMod* mod,
    std::string* error_message) {
    if (mod == nullptr || error_message == nullptr) {
        return false;
    }
    const bool reinitializing = mod->settings_available;
    const auto launch_local_values = mod->local_settings_values;
    error_message->clear();
    mod->settings_available = false;
    mod->settings_declaration = ModSettingsDeclaration{};
    mod->local_settings_values.clear();
    mod->effective_settings_values.clear();

    ModSettingsManifestResult parsed;
    std::string read_error;
    if (!LoadModSettingsManifest(
            mod->descriptor.manifest_path,
            &parsed,
            &read_error)) {
        if (!mod->settings_validation_logged) {
            LogSettingsError(
                "manifest_read_failed",
                *mod,
                read_error);
            mod->settings_validation_logged = true;
        }
        return true;
    }
    if (!parsed.has_settings) {
        return true;
    }
    if (!parsed.valid) {
        if (!mod->settings_validation_logged) {
            LogSettingsError(
                "manifest_validation_failed",
                *mod,
                parsed.error);
            mod->settings_validation_logged = true;
        }
        return true;
    }

    mod->settings_available = true;
    mod->settings_declaration = std::move(parsed.declaration);
    std::string persisted_error;
    ReadLocalValues(
        mod,
        &mod->local_settings_values,
        &persisted_error);
    if (reinitializing) {
        for (const auto& entry :
             mod->settings_declaration.entries) {
            if (!entry.requires_restart ||
                entry.type == ModSettingType::Action) {
                continue;
            }
            const auto launch_value =
                launch_local_values.find(entry.key);
            if (launch_value == launch_local_values.end()) {
                continue;
            }
            std::string validation_error;
            if (ValidateModSettingValue(
                    entry,
                    launch_value->second,
                    &validation_error)) {
                mod->local_settings_values[entry.key] =
                    launch_value->second;
            }
        }
    }
    mod->effective_settings_values = mod->local_settings_values;
    if (IsActiveClientSession()) {
        for (const auto& entry :
             mod->settings_declaration.entries) {
            if (entry.type == ModSettingType::Action ||
                entry.scope != ModSettingScope::Host) {
                continue;
            }
            ModSettingValue replicated;
            if (TryGetReplicatedValue(*mod, entry, &replicated)) {
                mod->effective_settings_values[entry.key] =
                    std::move(replicated);
            }
        }
    } else {
        for (const auto& entry :
             mod->settings_declaration.entries) {
            const auto value =
                mod->effective_settings_values.find(entry.key);
            if (entry.type != ModSettingType::Action &&
                value != mod->effective_settings_values.end()) {
                PublishHostValue(*mod, entry, value->second);
            }
        }
    }
    return true;
}

void ClearLuaSettingsCallbacks(LoadedLuaMod* mod) {
    if (mod == nullptr) {
        return;
    }
    mod->settings_changed_callbacks.clear();
    mod->settings_action_callbacks.clear();
}

void PollLuaSettingsReplicationChanges() {
    const bool active_client_session = IsActiveClientSession();
    for (const auto& loaded : LoadedLuaModsStorage()) {
        auto* mod = loaded.get();
        if (mod == nullptr || !mod->settings_available) {
            continue;
        }
        for (const auto& entry :
             mod->settings_declaration.entries) {
            if (entry.type == ModSettingType::Action ||
                entry.scope != ModSettingScope::Host) {
                continue;
            }
            ModSettingValue next;
            bool have_next = false;
            if (active_client_session) {
                have_next =
                    TryGetReplicatedValue(*mod, entry, &next);
            } else {
                const auto local =
                    mod->local_settings_values.find(entry.key);
                if (local != mod->local_settings_values.end()) {
                    next = local->second;
                    have_next = true;
                }
            }
            if (have_next) {
                ApplyEffectiveChange(
                    mod,
                    entry,
                    next,
                    nullptr,
                    !entry.requires_restart);
            }
        }
    }
}

LuaSettingsOperationResult ReloadLuaSettings(
    std::string_view mod_id) {
    LuaSettingsOperationResult result;
    auto* mod = FindLoadedSettingsMod(mod_id);
    if (mod == nullptr) {
        result.error = "mod is not loaded";
        return result;
    }
    if (!mod->settings_available) {
        result.error = "mod has no valid settings declaration";
        return result;
    }
    if (!HasSettingsCapability(*mod)) {
        result.error = "mod does not declare settings.self";
        return result;
    }

    ModSettingValues next_local;
    std::string read_error;
    if (!ReadLocalValues(mod, &next_local, &read_error)) {
        result.error =
            "failed to reload persisted settings: " + read_error;
        return result;
    }
    for (const auto& entry : mod->settings_declaration.entries) {
        if (entry.type == ModSettingType::Action ||
            entry.requires_restart) {
            continue;
        }
        const auto value = next_local.find(entry.key);
        if (value != next_local.end()) {
            mod->local_settings_values[entry.key] = value->second;
        }
    }
    for (const auto& entry : mod->settings_declaration.entries) {
        if (entry.type == ModSettingType::Action ||
            entry.requires_restart) {
            continue;
        }
        const auto local = next_local.find(entry.key);
        if (local == next_local.end()) {
            continue;
        }
        if (entry.scope == ModSettingScope::Host &&
            IsActiveClientSession()) {
            continue;
        }
        const auto previous =
            mod->effective_settings_values.find(entry.key);
        const bool changed =
            previous == mod->effective_settings_values.end() ||
            previous->second != local->second;
        ApplyEffectiveChange(
            mod,
            entry,
            local->second,
            &result.changed,
            true);
        if (changed &&
            !PublishHostValue(*mod, entry, local->second)) {
            result.error =
                "failed to replicate host setting '" +
                entry.key + "'";
            return result;
        }
    }
    result.ok = true;
    return result;
}

LuaSettingsOperationResult InvokeLuaSettingsAction(
    std::string_view mod_id,
    std::string_view key) {
    LuaSettingsOperationResult result;
    auto* mod = FindLoadedSettingsMod(mod_id);
    if (mod == nullptr) {
        result.error = "mod is not loaded";
        return result;
    }
    if (!mod->settings_available || !HasSettingsCapability(*mod)) {
        result.error = "mod settings are unavailable";
        return result;
    }
    const auto* entry = mod->settings_declaration.Find(key);
    if (entry == nullptr || entry->type != ModSettingType::Action) {
        result.error = "unknown action setting";
        return result;
    }
    if (entry->scope == ModSettingScope::Host &&
        multiplayer::IsLocalTransportClient()) {
        result.error = "host-scope action requires session authority";
        return result;
    }
    const auto callback =
        mod->settings_action_callbacks.find(std::string(key));
    if (callback == mod->settings_action_callbacks.end()) {
        result.error = "action has no registered handler";
        LogSettingsError(
            "action_handler_missing",
            *mod,
            std::string(key));
        return result;
    }

    ScopedSuspendedSettingsPrivilege suspended_privilege(mod->state);
    lua_rawgeti(
        mod->state,
        LUA_REGISTRYINDEX,
        callback->second);
    if (lua_pcall(mod->state, 0, 0, 0) != LUA_OK) {
        const auto* error = lua_tostring(mod->state, -1);
        result.error =
            error == nullptr
                ? "action handler failed"
                : error;
        lua_pop(mod->state, 1);
        LogSettingsError(
            "action_handler_failed",
            *mod,
            result.error);
        return result;
    }
    result.ok = true;
    return result;
}

lua_State* GetLuaSettingsPrivilegedExecState() {
    return g_privileged_settings_exec_state;
}

void SetLuaSettingsPrivilegedExecState(lua_State* state) {
    g_privileged_settings_exec_state = state;
}

}  // namespace sdmod::detail
