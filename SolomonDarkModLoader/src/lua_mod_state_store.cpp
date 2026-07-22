#include "lua_mod_runtime.h"

#include <mutex>
#include <utility>
#include <vector>

namespace sdmod {
namespace {

struct LuaModStateStore {
    std::uint64_t revision = 0;
    LuaModStateSnapshot values;
};

std::mutex g_lua_mod_state_mutex;
LuaModStateStore g_lua_mod_state;

void SetError(std::string* error_message, const char* message) {
    if (error_message != nullptr) {
        *error_message = message;
    }
}

bool ContainsNilValue(const LuaModValue& value) {
    if (value.type == LuaModValueType::Nil) {
        return true;
    }
    if (value.type == LuaModValueType::Array) {
        for (const auto& element : value.array_value) {
            if (ContainsNilValue(element)) {
                return true;
            }
        }
    } else if (value.type == LuaModValueType::Object) {
        for (const auto& [key, field_value] : value.object_value) {
            (void)key;
            if (ContainsNilValue(field_value)) {
                return true;
            }
        }
    }
    return false;
}

bool ValidateStateSnapshot(
    const LuaModStateSnapshot& snapshot,
    std::string* error_message) {
    for (const auto& [mod_id, values] : snapshot) {
        (void)mod_id;
        for (const auto& [key, value] : values) {
            (void)key;
            if (ContainsNilValue(value)) {
                SetError(
                    error_message,
                    "Lua mod state values cannot be nil; delete the key instead");
                return false;
            }
        }
    }
    std::vector<std::uint8_t> encoded;
    return EncodeLuaModStateSnapshot(snapshot, &encoded, error_message);
}

std::uint64_t NextRevision(std::uint64_t revision) {
    ++revision;
    return revision == 0 ? 1 : revision;
}

template <typename Mutation>
bool ApplyReplicatedMutation(
    std::uint64_t revision,
    Mutation&& mutation,
    std::string* error_message) {
    if (revision == 0) {
        SetError(error_message, "replicated Lua mod state revision must be nonzero");
        return false;
    }
    std::scoped_lock lock(g_lua_mod_state_mutex);
    if (revision <= g_lua_mod_state.revision) {
        return true;
    }
    auto next = g_lua_mod_state.values;
    mutation(next);
    if (!ValidateStateSnapshot(next, error_message)) {
        return false;
    }
    g_lua_mod_state.values = std::move(next);
    g_lua_mod_state.revision = revision;
    return true;
}

}  // namespace

void ResetLuaModStateStore() {
    std::scoped_lock lock(g_lua_mod_state_mutex);
    g_lua_mod_state = LuaModStateStore{};
}

std::uint64_t GetLuaModStateRevision() {
    std::scoped_lock lock(g_lua_mod_state_mutex);
    return g_lua_mod_state.revision;
}

LuaModStateSnapshot SnapshotLuaModState() {
    return SnapshotLuaModState(nullptr);
}

LuaModStateSnapshot SnapshotLuaModState(std::uint64_t* revision) {
    std::scoped_lock lock(g_lua_mod_state_mutex);
    if (revision != nullptr) {
        *revision = g_lua_mod_state.revision;
    }
    return g_lua_mod_state.values;
}

bool TryGetLuaModStateValue(
    const std::string& mod_id,
    const std::string& key,
    LuaModValue* value) {
    if (value == nullptr) {
        return false;
    }
    std::scoped_lock lock(g_lua_mod_state_mutex);
    const auto mod = g_lua_mod_state.values.find(mod_id);
    if (mod == g_lua_mod_state.values.end()) {
        return false;
    }
    const auto entry = mod->second.find(key);
    if (entry == mod->second.end()) {
        return false;
    }
    *value = entry->second;
    return true;
}

bool SetLuaModStateValue(
    const std::string& mod_id,
    const std::string& key,
    LuaModValue value,
    std::uint64_t* revision,
    std::string* error_message) {
    if (!IsValidLuaModIdentifier(mod_id) || !IsValidLuaModStateKey(key)) {
        SetError(error_message, "Lua mod state id or key is invalid");
        return false;
    }
    if (ContainsNilValue(value)) {
        SetError(
            error_message,
            "Lua mod state values cannot be nil; delete the key instead");
        return false;
    }
    std::vector<std::uint8_t> encoded_value;
    if (!EncodeLuaModValue(value, &encoded_value, error_message)) {
        return false;
    }
    std::scoped_lock lock(g_lua_mod_state_mutex);
    auto next = g_lua_mod_state.values;
    next[mod_id][key] = std::move(value);
    if (!ValidateStateSnapshot(next, error_message)) {
        return false;
    }
    g_lua_mod_state.values = std::move(next);
    g_lua_mod_state.revision = NextRevision(g_lua_mod_state.revision);
    if (revision != nullptr) {
        *revision = g_lua_mod_state.revision;
    }
    return true;
}

bool DeleteLuaModStateValue(
    const std::string& mod_id,
    const std::string& key,
    bool* deleted,
    std::uint64_t* revision,
    std::string* error_message) {
    if (deleted != nullptr) {
        *deleted = false;
    }
    if (!IsValidLuaModIdentifier(mod_id) || !IsValidLuaModStateKey(key)) {
        SetError(error_message, "Lua mod state id or key is invalid");
        return false;
    }
    std::scoped_lock lock(g_lua_mod_state_mutex);
    const auto mod = g_lua_mod_state.values.find(mod_id);
    if (mod == g_lua_mod_state.values.end() ||
        mod->second.find(key) == mod->second.end()) {
        if (revision != nullptr) {
            *revision = g_lua_mod_state.revision;
        }
        return true;
    }
    mod->second.erase(key);
    if (mod->second.empty()) {
        g_lua_mod_state.values.erase(mod);
    }
    g_lua_mod_state.revision = NextRevision(g_lua_mod_state.revision);
    if (deleted != nullptr) {
        *deleted = true;
    }
    if (revision != nullptr) {
        *revision = g_lua_mod_state.revision;
    }
    return true;
}

bool ClearLuaModStateValues(
    const std::string& mod_id,
    bool* cleared,
    std::uint64_t* revision,
    std::string* error_message) {
    if (cleared != nullptr) {
        *cleared = false;
    }
    if (!IsValidLuaModIdentifier(mod_id)) {
        SetError(error_message, "Lua mod state id is invalid");
        return false;
    }
    std::scoped_lock lock(g_lua_mod_state_mutex);
    const auto erased = g_lua_mod_state.values.erase(mod_id);
    if (erased != 0) {
        g_lua_mod_state.revision = NextRevision(g_lua_mod_state.revision);
        if (cleared != nullptr) {
            *cleared = true;
        }
    }
    if (revision != nullptr) {
        *revision = g_lua_mod_state.revision;
    }
    return true;
}

bool ApplyReplicatedLuaModStateSet(
    const std::string& mod_id,
    const std::string& key,
    LuaModValue value,
    std::uint64_t revision,
    std::string* error_message) {
    if (!IsValidLuaModIdentifier(mod_id) || !IsValidLuaModStateKey(key)) {
        SetError(error_message, "replicated Lua mod state id or key is invalid");
        return false;
    }
    if (ContainsNilValue(value)) {
        SetError(
            error_message,
            "replicated Lua mod state values cannot be nil");
        return false;
    }
    return ApplyReplicatedMutation(
        revision,
        [&](LuaModStateSnapshot& next) {
            next[mod_id][key] = std::move(value);
        },
        error_message);
}

bool ApplyReplicatedLuaModStateDelete(
    const std::string& mod_id,
    const std::string& key,
    std::uint64_t revision,
    std::string* error_message) {
    if (!IsValidLuaModIdentifier(mod_id) || !IsValidLuaModStateKey(key)) {
        SetError(error_message, "replicated Lua mod state id or key is invalid");
        return false;
    }
    return ApplyReplicatedMutation(
        revision,
        [&](LuaModStateSnapshot& next) {
            const auto mod = next.find(mod_id);
            if (mod == next.end()) {
                return;
            }
            mod->second.erase(key);
            if (mod->second.empty()) {
                next.erase(mod);
            }
        },
        error_message);
}

bool ApplyReplicatedLuaModStateClear(
    const std::string& mod_id,
    std::uint64_t revision,
    std::string* error_message) {
    if (!IsValidLuaModIdentifier(mod_id)) {
        SetError(error_message, "replicated Lua mod state id is invalid");
        return false;
    }
    return ApplyReplicatedMutation(
        revision,
        [&](LuaModStateSnapshot& next) { next.erase(mod_id); },
        error_message);
}

bool ApplyReplicatedLuaModStateSnapshot(
    LuaModStateSnapshot snapshot,
    std::uint64_t revision,
    std::string* error_message) {
    if (!ValidateStateSnapshot(snapshot, error_message)) {
        return false;
    }
    std::scoped_lock lock(g_lua_mod_state_mutex);
    if (revision < g_lua_mod_state.revision) {
        return true;
    }
    g_lua_mod_state.values = std::move(snapshot);
    g_lua_mod_state.revision = revision;
    return true;
}

}  // namespace sdmod
