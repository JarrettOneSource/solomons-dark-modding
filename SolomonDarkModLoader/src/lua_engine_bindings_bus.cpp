#include "lua_engine_bindings_internal.h"

#include "lua_engine_values.h"

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace sdmod::detail {
namespace {

constexpr std::size_t kLuaBusMaximumSubscriptionsPerMod = 128;
constexpr std::size_t kLuaBusMaximumDeliveriesPerPublish = 256;
constexpr std::size_t kLuaBusMaximumDispatchDepth = 16;

thread_local std::size_t g_lua_bus_dispatch_depth = 0;

struct LuaBusDispatchTarget {
    LoadedLuaMod* mod = nullptr;
    std::uint64_t subscription_id = 0;
};

LoadedLuaMod* RequireBusMod(lua_State* state, const char* api_name) {
    auto* mod = GetLoadedLuaMod(state);
    if (mod == nullptr) {
        luaL_error(state, "%s is unavailable", api_name);
    }
    return mod;
}

std::string ReadBusIdentifier(
    lua_State* state,
    int index,
    const char* api_name,
    const char* label) {
    std::size_t length = 0;
    const char* text = luaL_checklstring(state, index, &length);
    std::string value(text, length);
    if (!IsValidLuaModIdentifier(value)) {
        luaL_error(
            state,
            "%s %s must be a nonempty bounded identifier",
            api_name,
            label);
    }
    return value;
}

auto FindSubscription(LoadedLuaMod* mod, std::uint64_t id) {
    return std::find_if(
        mod->bus_subscriptions.begin(),
        mod->bus_subscriptions.end(),
        [id](const LuaBusSubscription& subscription) {
            return subscription.id == id;
        });
}

std::uint64_t ReadSubscriptionId(lua_State* state) {
    if (!lua_isinteger(state, 1)) {
        luaL_error(
            state,
            "sd.bus.unsubscribe subscription id must be a positive integer");
    }
    const auto value = lua_tointeger(state, 1);
    if (value <= 0) {
        luaL_error(
            state,
            "sd.bus.unsubscribe subscription id must be a positive integer");
    }
    return static_cast<std::uint64_t>(value);
}

bool ModProvidesContract(
    const LoadedLuaMod& mod,
    const std::string& contract) {
    return std::find(
        mod.descriptor.provides.begin(),
        mod.descriptor.provides.end(),
        contract) != mod.descriptor.provides.end();
}

std::vector<LoadedLuaMod*> SnapshotDispatchMods(LoadedLuaMod* publisher) {
    std::vector<LoadedLuaMod*> mods;
    auto& loaded_mods = LoadedLuaModsStorage();
    mods.reserve(loaded_mods.size() + 1);
    bool publisher_present = false;
    for (const auto& loaded_mod : loaded_mods) {
        if (loaded_mod == nullptr || loaded_mod->state == nullptr) {
            continue;
        }
        mods.push_back(loaded_mod.get());
        publisher_present = publisher_present || loaded_mod.get() == publisher;
    }
    if (!publisher_present && publisher != nullptr && publisher->state != nullptr) {
        mods.push_back(publisher);
    }
    return mods;
}

int LuaBusSubscribe(lua_State* state) {
    auto* mod = RequireBusMod(state, "sd.bus.subscribe");
    const auto topic = ReadBusIdentifier(
        state,
        1,
        "sd.bus.subscribe",
        "topic");
    luaL_checktype(state, 2, LUA_TFUNCTION);
    if (mod->bus_subscriptions.size() >= kLuaBusMaximumSubscriptionsPerMod) {
        return luaL_error(
            state,
            "sd.bus.subscribe exceeds the per-mod limit of %zu subscriptions",
            kLuaBusMaximumSubscriptionsPerMod);
    }

    lua_pushvalue(state, 2);
    const int callback_reference = luaL_ref(state, LUA_REGISTRYINDEX);
    const auto id = mod->next_bus_subscription_id++;
    mod->bus_subscriptions.push_back(
        LuaBusSubscription{id, topic, callback_reference});
    lua_pushinteger(state, static_cast<lua_Integer>(id));
    return 1;
}

int LuaBusUnsubscribe(lua_State* state) {
    auto* mod = RequireBusMod(state, "sd.bus.unsubscribe");
    const auto id = ReadSubscriptionId(state);
    const auto subscription = FindSubscription(mod, id);
    if (subscription == mod->bus_subscriptions.end()) {
        lua_pushboolean(state, 0);
        return 1;
    }
    luaL_unref(
        state,
        LUA_REGISTRYINDEX,
        subscription->callback_reference);
    mod->bus_subscriptions.erase(subscription);
    lua_pushboolean(state, 1);
    return 1;
}

int LuaBusPublish(lua_State* state) {
    auto* publisher = RequireBusMod(state, "sd.bus.publish");
    const auto topic = ReadBusIdentifier(
        state,
        1,
        "sd.bus.publish",
        "topic");
    LuaModValue payload;
    if (lua_gettop(state) >= 2) {
        std::string error_message;
        if (!ReadLuaModValue(state, 2, &payload, &error_message)) {
            return luaL_error(state, "%s", error_message.c_str());
        }
    }

    if (g_lua_bus_dispatch_depth >= kLuaBusMaximumDispatchDepth) {
        return luaL_error(
            state,
            "sd.bus.publish exceeds the maximum nested dispatch depth of %zu",
            kLuaBusMaximumDispatchDepth);
    }

    std::vector<LuaBusDispatchTarget> targets;
    for (auto* mod : SnapshotDispatchMods(publisher)) {
        for (const auto& subscription : mod->bus_subscriptions) {
            if (subscription.topic != topic) {
                continue;
            }
            if (targets.size() == kLuaBusMaximumDeliveriesPerPublish) {
                return luaL_error(
                    state,
                    "sd.bus.publish exceeds the limit of %zu matching subscriptions",
                    kLuaBusMaximumDeliveriesPerPublish);
            }
            targets.push_back({mod, subscription.id});
        }
    }

    ++g_lua_bus_dispatch_depth;
    std::size_t delivered = 0;
    for (const auto& target : targets) {
        const auto subscription = FindSubscription(
            target.mod,
            target.subscription_id);
        if (subscription == target.mod->bus_subscriptions.end() ||
            subscription->topic != topic) {
            continue;
        }

        lua_rawgeti(
            target.mod->state,
            LUA_REGISTRYINDEX,
            subscription->callback_reference);
        if (!lua_isfunction(target.mod->state, -1)) {
            lua_pop(target.mod->state, 1);
            continue;
        }
        PushLuaModValue(target.mod->state, payload);
        lua_createtable(target.mod->state, 0, 2);
        lua_pushlstring(target.mod->state, topic.data(), topic.size());
        lua_setfield(target.mod->state, -2, "topic");
        lua_pushlstring(
            target.mod->state,
            publisher->descriptor.id.data(),
            publisher->descriptor.id.size());
        lua_setfield(target.mod->state, -2, "publisher_mod_id");
        ++delivered;
        if (lua_pcall(target.mod->state, 2, 0, 0) != LUA_OK) {
            const auto* message = lua_tostring(target.mod->state, -1);
            LogLuaMessage(
                *target.mod,
                "bus topic " + topic + " handler failed: " +
                    (message == nullptr ? "unknown" : message));
            lua_pop(target.mod->state, 1);
        }
    }
    --g_lua_bus_dispatch_depth;
    lua_pushinteger(state, static_cast<lua_Integer>(delivered));
    return 1;
}

int LuaBusHas(lua_State* state) {
    auto* requester = RequireBusMod(state, "sd.bus.has");
    const auto contract = ReadBusIdentifier(
        state,
        1,
        "sd.bus.has",
        "contract");
    bool found = false;
    for (const auto* mod : SnapshotDispatchMods(requester)) {
        if (ModProvidesContract(*mod, contract)) {
            found = true;
            break;
        }
    }
    lua_pushboolean(state, found ? 1 : 0);
    return 1;
}

int LuaBusProviders(lua_State* state) {
    auto* requester = RequireBusMod(state, "sd.bus.providers");
    const auto contract = ReadBusIdentifier(
        state,
        1,
        "sd.bus.providers",
        "contract");
    lua_createtable(state, 0, 0);
    lua_Integer index = 1;
    for (const auto* mod : SnapshotDispatchMods(requester)) {
        if (!ModProvidesContract(*mod, contract)) {
            continue;
        }
        lua_pushlstring(
            state,
            mod->descriptor.id.data(),
            mod->descriptor.id.size());
        lua_rawseti(state, -2, index++);
    }
    return 1;
}

}  // namespace

void ClearLuaBusSubscriptionsForMod(LoadedLuaMod* mod) {
    if (mod == nullptr) {
        return;
    }
    if (mod->state != nullptr) {
        for (auto& subscription : mod->bus_subscriptions) {
            if (subscription.callback_reference != LUA_NOREF) {
                luaL_unref(
                    mod->state,
                    LUA_REGISTRYINDEX,
                    subscription.callback_reference);
                subscription.callback_reference = LUA_NOREF;
            }
        }
    }
    mod->bus_subscriptions.clear();
}

void RegisterLuaBusBindings(lua_State* state) {
    lua_createtable(state, 0, 5);
    RegisterFunction(state, &LuaBusPublish, "publish");
    RegisterFunction(state, &LuaBusSubscribe, "subscribe");
    RegisterFunction(state, &LuaBusUnsubscribe, "unsubscribe");
    RegisterFunction(state, &LuaBusHas, "has");
    RegisterFunction(state, &LuaBusProviders, "providers");
    lua_setfield(state, -2, "bus");
}

}  // namespace sdmod::detail
