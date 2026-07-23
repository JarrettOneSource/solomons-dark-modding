#include "lua_engine_internal.h"

#include "logger.h"
#include "lua_engine.h"
#include "lua_engine_values.h"

extern "C" {
#include "lauxlib.h"
#include "lua.h"
}

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <deque>
#include <mutex>
#include <string>
#include <utility>

namespace sdmod::detail {
namespace {

constexpr std::size_t kLuaRegisteredSpellMaximumQueuedCasts = 64;
constexpr std::size_t kLuaRegisteredSpellMaximumRememberedCasts = 1024;
constexpr float kLuaRegisteredSpellMaximumCoordinateMagnitude = 10'000'000.0f;
constexpr float kLuaRegisteredSpellMinimumAimDistance = 0.001f;

struct RememberedSpellCastRequest {
    std::uint64_t authority_participant_id = 0;
    std::uint64_t request_id = 0;
};

std::mutex& RegisteredSpellCastQueueMutex() {
    static std::mutex mutex;
    return mutex;
}

std::deque<LuaRegisteredSpellCastRequest>& RegisteredSpellCastQueue() {
    static std::deque<LuaRegisteredSpellCastRequest> queue;
    return queue;
}

std::deque<RememberedSpellCastRequest>& RememberedSpellCastRequests() {
    static std::deque<RememberedSpellCastRequest> requests;
    return requests;
}

bool SameRememberedRequest(
    const RememberedSpellCastRequest& remembered,
    const LuaRegisteredSpellCastRequest& request) {
    return remembered.authority_participant_id ==
               request.authority_participant_id &&
        remembered.request_id == request.request_id;
}

bool IsValidRegisteredSpellCastRequest(
    const LuaRegisteredSpellCastRequest& request,
    std::string* error_message) {
    const auto fail = [&](const char* message) {
        if (error_message != nullptr) {
            *error_message = message;
        }
        return false;
    };
    if (request.authority_participant_id == 0 ||
        request.owner_participant_id == 0 ||
        request.request_id == 0 ||
        request.content_id == 0 ||
        request.content_id > static_cast<std::uint64_t>(INT64_MAX)) {
        return fail("Registered spell casts require nonzero bounded identities.");
    }
    for (const auto value : {
             request.origin_x,
             request.origin_y,
             request.aim_x,
             request.aim_y,
         }) {
        if (!std::isfinite(value) ||
            std::fabs(value) > kLuaRegisteredSpellMaximumCoordinateMagnitude) {
            return fail("Registered spell cast coordinates are invalid.");
        }
    }
    const auto direction_x = request.aim_x - request.origin_x;
    const auto direction_y = request.aim_y - request.origin_y;
    const auto distance_squared =
        direction_x * direction_x + direction_y * direction_y;
    if (!std::isfinite(distance_squared) ||
        distance_squared <
            kLuaRegisteredSpellMinimumAimDistance *
                kLuaRegisteredSpellMinimumAimDistance) {
        return fail("Registered spell cast origin and aim must differ.");
    }
    return true;
}

std::deque<LuaRegisteredSpellCastRequest>
DrainRegisteredSpellCastQueue() {
    std::lock_guard<std::mutex> lock(RegisteredSpellCastQueueMutex());
    std::deque<LuaRegisteredSpellCastRequest> requests;
    requests.swap(RegisteredSpellCastQueue());
    return requests;
}

bool FindRegisteredSpellDefinition(
    std::uint64_t content_id,
    LoadedLuaMod** owner_mod,
    const LuaSpellDefinition** definition) {
    if (owner_mod == nullptr || definition == nullptr) {
        return false;
    }
    *owner_mod = nullptr;
    *definition = nullptr;
    for (const auto& loaded_mod : LoadedLuaModsStorage()) {
        if (loaded_mod == nullptr || loaded_mod->state == nullptr) {
            continue;
        }
        const auto found = std::find_if(
            loaded_mod->spell_definitions.begin(),
            loaded_mod->spell_definitions.end(),
            [content_id](const LuaSpellDefinition& candidate) {
                return candidate.identity.network_id == content_id;
            });
        if (found == loaded_mod->spell_definitions.end()) {
            continue;
        }
        *owner_mod = loaded_mod.get();
        *definition = &*found;
        return true;
    }
    return false;
}

void PushRegisteredSpellCastContext(
    lua_State* state,
    const LuaSpellDefinition& definition,
    const LuaRegisteredSpellCastRequest& request) {
    const auto delta_x = request.aim_x - request.origin_x;
    const auto delta_y = request.aim_y - request.origin_y;
    const auto distance = std::sqrt(delta_x * delta_x + delta_y * delta_y);
    const auto direction_x = delta_x / distance;
    const auto direction_y = delta_y / distance;

    lua_createtable(state, 0, 16);
    lua_pushinteger(state, static_cast<lua_Integer>(request.request_id));
    lua_setfield(state, -2, "request_id");
    lua_pushinteger(state, static_cast<lua_Integer>(request.content_id));
    lua_setfield(state, -2, "content_id");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(request.authority_participant_id));
    lua_setfield(state, -2, "authority_participant_id");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(request.owner_participant_id));
    lua_setfield(state, -2, "owner_participant_id");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(request.target_network_actor_id));
    lua_setfield(state, -2, "target_network_actor_id");
    lua_pushstring(
        state,
        definition.slot == LuaSpellSlot::Primary ? "primary" : "secondary");
    lua_setfield(state, -2, "slot");
    lua_pushnumber(state, request.origin_x);
    lua_setfield(state, -2, "origin_x");
    lua_pushnumber(state, request.origin_y);
    lua_setfield(state, -2, "origin_y");
    lua_pushnumber(state, request.aim_x);
    lua_setfield(state, -2, "aim_x");
    lua_pushnumber(state, request.aim_y);
    lua_setfield(state, -2, "aim_y");
    lua_pushnumber(state, direction_x);
    lua_setfield(state, -2, "direction_x");
    lua_pushnumber(state, direction_y);
    lua_setfield(state, -2, "direction_y");
    PushLuaModValue(state, definition.config);
    lua_setfield(state, -2, "cfg");
}

void DispatchRegisteredSpellCast(
    const LuaRegisteredSpellCastRequest& request,
    std::uint64_t now_ms) {
    LoadedLuaMod* owner_mod = nullptr;
    const LuaSpellDefinition* definition = nullptr;
    if (!FindRegisteredSpellDefinition(
            request.content_id,
            &owner_mod,
            &definition)) {
        Log(
            "lua_spells: rejected queued cast for unknown content id " +
            std::to_string(request.content_id));
        return;
    }
    if (definition->on_cast_reference == LUA_NOREF) {
        LogLuaMessage(
            *owner_mod,
            "registered spell has no on_cast callback: " +
                definition->identity.key);
        return;
    }

    auto* state = owner_mod->state;
    const int stack_top = lua_gettop(state);
    lua_rawgeti(
        state,
        LUA_REGISTRYINDEX,
        definition->on_cast_reference);
    if (!lua_isfunction(state, -1)) {
        lua_settop(state, stack_top);
        LogLuaMessage(
            *owner_mod,
            "registered spell on_cast reference is invalid: " +
                definition->identity.key);
        return;
    }
    PushRegisteredSpellCastContext(state, *definition, request);
    if (lua_pcall(state, 1, 1, 0) != LUA_OK) {
        const auto* message = lua_tostring(state, -1);
        LogLuaMessage(
            *owner_mod,
            "registered spell on_cast failed for " +
                definition->identity.key + ": " +
                (message == nullptr ? "unknown" : message));
        lua_settop(state, stack_top);
        return;
    }

    std::string effect_error;
    if (!CreateLuaSpellEffectsFromCallbackResult(
            owner_mod,
            *definition,
            request,
            now_ms,
            -1,
            &effect_error)) {
        LogLuaMessage(
            *owner_mod,
            "registered spell on_cast returned invalid effects for " +
                definition->identity.key + ": " + effect_error);
    }
    lua_settop(state, stack_top);
}

}  // namespace

void ResetLuaRegisteredSpellRuntime() {
    {
        std::lock_guard<std::mutex> lock(RegisteredSpellCastQueueMutex());
        RegisteredSpellCastQueue().clear();
        RememberedSpellCastRequests().clear();
    }
    ResetLuaRegisteredSpellInputSelections();
}

void DispatchPendingLuaRegisteredSpellCasts(
    const SDModRuntimeTickContext& context) {
    auto requests = DrainRegisteredSpellCastQueue();
    for (const auto& request : requests) {
        DispatchRegisteredSpellCast(request, context.monotonic_milliseconds);
    }
}

}  // namespace sdmod::detail

namespace sdmod {

bool QueueLuaRegisteredSpellCastRequest(
    const LuaRegisteredSpellCastRequest& request,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!detail::IsValidRegisteredSpellCastRequest(
            request,
            error_message)) {
        return false;
    }

    std::lock_guard<std::mutex> lock(
        detail::RegisteredSpellCastQueueMutex());
    auto& remembered = detail::RememberedSpellCastRequests();
    if (std::any_of(
            remembered.begin(),
            remembered.end(),
            [&](const detail::RememberedSpellCastRequest& candidate) {
                return detail::SameRememberedRequest(candidate, request);
            })) {
        if (error_message != nullptr) {
            *error_message = "Registered spell cast request is a duplicate.";
        }
        return false;
    }
    auto& queue = detail::RegisteredSpellCastQueue();
    if (queue.size() >=
        detail::kLuaRegisteredSpellMaximumQueuedCasts) {
        if (error_message != nullptr) {
            *error_message = "Registered spell cast queue is full.";
        }
        return false;
    }

    queue.push_back(request);
    remembered.push_back(detail::RememberedSpellCastRequest{
        request.authority_participant_id,
        request.request_id,
    });
    while (remembered.size() >
           detail::kLuaRegisteredSpellMaximumRememberedCasts) {
        remembered.pop_front();
    }
    return true;
}

}  // namespace sdmod
