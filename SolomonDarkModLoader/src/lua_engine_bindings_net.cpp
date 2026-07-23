#include "lua_engine_bindings_internal.h"

#include "logger.h"
#include "lua_net_runtime.h"
#include "lua_mod_runtime.h"
#include "multiplayer_local_transport.h"

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <mutex>
#include <string>
#include <utility>
#include <vector>

namespace sdmod::detail {
namespace {

std::mutex g_lua_net_delivery_mutex;
std::deque<LuaNetMessage> g_pending_lua_net_deliveries;
std::size_t g_pending_lua_net_delivery_bytes = 0;
bool g_lua_net_delivery_queue_accepting = false;

LoadedLuaMod* RequireNetMod(lua_State* state, const char* api_name) {
    auto* mod = GetLoadedLuaMod(state);
    if (mod == nullptr) {
        luaL_error(state, "%s is unavailable", api_name);
    }
    return mod;
}

std::string ReadNetChannel(
    lua_State* state,
    int index,
    const char* api_name) {
    std::size_t length = 0;
    const auto* text = luaL_checklstring(state, index, &length);
    std::string channel(text, length);
    if (channel.size() > kLuaNetMaximumChannelBytes ||
        !IsValidLuaModIdentifier(channel)) {
        luaL_error(
            state,
            "%s channel must be a 1 through %zu byte identifier",
            api_name,
            kLuaNetMaximumChannelBytes);
    }
    return channel;
}

std::string ReadNetPayload(
    lua_State* state,
    int index,
    const char* api_name) {
    std::size_t length = 0;
    const auto* bytes = luaL_checklstring(state, index, &length);
    if (length > kLuaNetMaximumPayloadBytes) {
        luaL_error(
            state,
            "%s payload exceeds the %zu byte limit",
            api_name,
            kLuaNetMaximumPayloadBytes);
    }
    return std::string(bytes, length);
}

std::uint64_t ReadTargetParticipant(lua_State* state, int index) {
    if (!lua_isinteger(state, index)) {
        luaL_error(
            state,
            "sd.net.send target participant id must be a positive integer");
    }
    const auto value = lua_tointeger(state, index);
    if (value <= 0) {
        luaL_error(
            state,
            "sd.net.send target participant id must be a positive integer");
    }
    return static_cast<std::uint64_t>(value);
}

std::uint64_t ReadNetSubscriptionId(lua_State* state) {
    if (!lua_isinteger(state, 1) || lua_tointeger(state, 1) <= 0) {
        luaL_error(
            state,
            "sd.net.off subscription id must be a positive integer");
    }
    return static_cast<std::uint64_t>(lua_tointeger(state, 1));
}

auto FindNetSubscription(LoadedLuaMod* mod, std::uint64_t id) {
    return std::find_if(
        mod->net_subscriptions.begin(),
        mod->net_subscriptions.end(),
        [id](const LuaNetSubscription& subscription) {
            return subscription.id == id;
        });
}

int LuaNetSend(lua_State* state) {
    constexpr const char* kApiName = "sd.net.send";
    auto* mod = RequireNetMod(state, kApiName);
    const auto target_participant_id = ReadTargetParticipant(state, 1);
    const auto channel = ReadNetChannel(state, 2, kApiName);
    const auto payload = ReadNetPayload(state, 3, kApiName);
    std::uint64_t sequence = 0;
    std::string error_message;
    if (!multiplayer::QueueLuaNetMessage(
            mod->descriptor.id,
            channel,
            payload,
            target_participant_id,
            false,
            &sequence,
            &error_message)) {
        return luaL_error(state, "%s: %s", kApiName, error_message.c_str());
    }
    lua_pushinteger(state, static_cast<lua_Integer>(sequence));
    return 1;
}

int LuaNetBroadcast(lua_State* state) {
    constexpr const char* kApiName = "sd.net.broadcast";
    auto* mod = RequireNetMod(state, kApiName);
    const auto channel = ReadNetChannel(state, 1, kApiName);
    const auto payload = ReadNetPayload(state, 2, kApiName);
    std::uint64_t sequence = 0;
    std::string error_message;
    if (!multiplayer::QueueLuaNetMessage(
            mod->descriptor.id,
            channel,
            payload,
            0,
            true,
            &sequence,
            &error_message)) {
        return luaL_error(state, "%s: %s", kApiName, error_message.c_str());
    }
    lua_pushinteger(state, static_cast<lua_Integer>(sequence));
    return 1;
}

int LuaNetOn(lua_State* state) {
    constexpr const char* kApiName = "sd.net.on";
    auto* mod = RequireNetMod(state, kApiName);
    const auto channel = ReadNetChannel(state, 1, kApiName);
    luaL_checktype(state, 2, LUA_TFUNCTION);
    if (mod->net_subscriptions.size() >=
        kLuaNetMaximumSubscriptionsPerMod) {
        return luaL_error(
            state,
            "%s exceeds the per-mod limit of %zu subscriptions",
            kApiName,
            kLuaNetMaximumSubscriptionsPerMod);
    }
    lua_pushvalue(state, 2);
    const int callback_reference = luaL_ref(state, LUA_REGISTRYINDEX);
    const auto id = mod->next_net_subscription_id++;
    mod->net_subscriptions.push_back(
        LuaNetSubscription{id, channel, callback_reference});
    lua_pushinteger(state, static_cast<lua_Integer>(id));
    return 1;
}

int LuaNetOff(lua_State* state) {
    auto* mod = RequireNetMod(state, "sd.net.off");
    const auto id = ReadNetSubscriptionId(state);
    const auto found = FindNetSubscription(mod, id);
    if (found == mod->net_subscriptions.end()) {
        lua_pushboolean(state, 0);
        return 1;
    }
    luaL_unref(state, LUA_REGISTRYINDEX, found->callback_reference);
    mod->net_subscriptions.erase(found);
    lua_pushboolean(state, 1);
    return 1;
}

int LuaNetGetLimits(lua_State* state) {
    lua_createtable(state, 0, 7);
    lua_pushinteger(state, kLuaNetMaximumChannelBytes);
    lua_setfield(state, -2, "channel_bytes");
    lua_pushinteger(state, kLuaNetMaximumPayloadBytes);
    lua_setfield(state, -2, "payload_bytes");
    lua_pushinteger(state, kLuaNetMaximumSubscriptionsPerMod);
    lua_setfield(state, -2, "subscriptions_per_mod");
    lua_pushinteger(state, kLuaNetMaximumQueuedMessages);
    lua_setfield(state, -2, "queued_messages");
    lua_pushinteger(state, kLuaNetMaximumQueuedBytes);
    lua_setfield(state, -2, "queued_bytes");
    lua_pushinteger(state, kLuaNetMaximumPendingDeliveries);
    lua_setfield(state, -2, "pending_deliveries");
    lua_pushinteger(state, kLuaNetMaximumPendingDeliveryBytes);
    lua_setfield(state, -2, "pending_delivery_bytes");
    return 1;
}

void PushNetMessageMetadata(lua_State* state, const LuaNetMessage& message) {
    lua_createtable(state, 0, 6);
    lua_pushlstring(state, message.channel.data(), message.channel.size());
    lua_setfield(state, -2, "channel");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(message.sender_participant_id));
    lua_setfield(state, -2, "sender_participant_id");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(message.target_participant_id));
    lua_setfield(state, -2, "target_participant_id");
    lua_pushinteger(state, static_cast<lua_Integer>(message.sequence));
    lua_setfield(state, -2, "sequence");
    lua_pushboolean(state, message.broadcast ? 1 : 0);
    lua_setfield(state, -2, "broadcast");
}

void DispatchNetMessageToMod(
    LoadedLuaMod* mod,
    const LuaNetMessage& message) {
    if (mod == nullptr || mod->state == nullptr ||
        mod->descriptor.id != message.mod_id) {
        return;
    }
    std::vector<std::uint64_t> subscription_ids;
    for (const auto& subscription : mod->net_subscriptions) {
        if (subscription.channel == message.channel) {
            subscription_ids.push_back(subscription.id);
        }
    }
    for (const auto id : subscription_ids) {
        const auto found = FindNetSubscription(mod, id);
        if (found == mod->net_subscriptions.end() ||
            found->channel != message.channel) {
            continue;
        }
        lua_rawgeti(
            mod->state,
            LUA_REGISTRYINDEX,
            found->callback_reference);
        if (!lua_isfunction(mod->state, -1)) {
            lua_pop(mod->state, 1);
            continue;
        }
        lua_pushlstring(
            mod->state,
            message.payload.data(),
            message.payload.size());
        PushNetMessageMetadata(mod->state, message);
        if (lua_pcall(mod->state, 2, 0, 0) != LUA_OK) {
            const auto* error = lua_tostring(mod->state, -1);
            LogLuaMessage(
                *mod,
                "sd.net channel '" + message.channel +
                    "' handler failed: " +
                    (error == nullptr ? "unknown" : error));
            lua_pop(mod->state, 1);
        }
    }
}

}  // namespace

void RegisterLuaNetBindings(lua_State* state) {
    lua_createtable(state, 0, 5);
    RegisterFunction(state, &LuaNetSend, "send");
    RegisterFunction(state, &LuaNetBroadcast, "broadcast");
    RegisterFunction(state, &LuaNetOn, "on");
    RegisterFunction(state, &LuaNetOff, "off");
    RegisterFunction(state, &LuaNetGetLimits, "get_limits");
    lua_setfield(state, -2, "net");
}

void ClearLuaNetSubscriptionsForMod(LoadedLuaMod* mod) {
    if (mod == nullptr) return;
    if (mod->state != nullptr) {
        for (auto& subscription : mod->net_subscriptions) {
            if (subscription.callback_reference != LUA_NOREF) {
                luaL_unref(
                    mod->state,
                    LUA_REGISTRYINDEX,
                    subscription.callback_reference);
                subscription.callback_reference = LUA_NOREF;
            }
        }
    }
    mod->net_subscriptions.clear();
}

void StartLuaNetDeliveryQueue() {
    std::scoped_lock lock(g_lua_net_delivery_mutex);
    g_pending_lua_net_deliveries.clear();
    g_pending_lua_net_delivery_bytes = 0;
    g_lua_net_delivery_queue_accepting = true;
}

void StopLuaNetDeliveryQueue() {
    std::scoped_lock lock(g_lua_net_delivery_mutex);
    g_lua_net_delivery_queue_accepting = false;
    g_pending_lua_net_deliveries.clear();
    g_pending_lua_net_delivery_bytes = 0;
}

void DispatchPendingLuaNetMessages() {
    std::deque<LuaNetMessage> pending;
    {
        std::scoped_lock lock(g_lua_net_delivery_mutex);
        pending.swap(g_pending_lua_net_deliveries);
        g_pending_lua_net_delivery_bytes = 0;
    }
    for (const auto& message : pending) {
        for (const auto& mod : LoadedLuaModsStorage()) {
            DispatchNetMessageToMod(mod.get(), message);
        }
    }
}

}  // namespace sdmod::detail

namespace sdmod {

bool QueueLuaNetMessageDelivery(LuaNetMessage message) {
    if (message.mod_id.empty() || message.channel.empty() ||
        message.channel.size() > kLuaNetMaximumChannelBytes ||
        message.payload.size() > kLuaNetMaximumPayloadBytes ||
        message.sequence == 0) {
        return false;
    }
    std::scoped_lock lock(detail::g_lua_net_delivery_mutex);
    if (!detail::g_lua_net_delivery_queue_accepting ||
        detail::g_pending_lua_net_deliveries.size() >=
            kLuaNetMaximumPendingDeliveries ||
        detail::g_pending_lua_net_delivery_bytes + message.payload.size() >
            kLuaNetMaximumPendingDeliveryBytes) {
        return false;
    }
    detail::g_pending_lua_net_delivery_bytes += message.payload.size();
    detail::g_pending_lua_net_deliveries.push_back(std::move(message));
    return true;
}

}  // namespace sdmod
