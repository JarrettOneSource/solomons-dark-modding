#include "lua_engine_bindings_internal.h"

#include <Windows.h>

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <string>
#include <utility>
#include <vector>

namespace sdmod::detail {
namespace {

constexpr std::uint32_t kLuaTimerMaximumDelayMs = 24u * 60u * 60u * 1000u;
constexpr std::size_t kLuaTimerMaximumSequenceSteps = 64;
constexpr std::size_t kLuaTimerMaximumScheduledCallbacksPerMod = 256;
constexpr std::size_t kLuaTimerMaximumCallbacksPerTick = 64;

LoadedLuaMod* RequireTimerMod(lua_State* state, const char* api_name) {
    auto* mod = GetLoadedLuaMod(state);
    if (mod == nullptr) {
        luaL_error(state, "%s is unavailable", api_name);
    }
    return mod;
}

std::uint32_t ReadDelayMilliseconds(
    lua_State* state,
    int index,
    const char* api_name,
    bool allow_zero) {
    if (!lua_isinteger(state, index)) {
        luaL_error(state, "%s delay must be an integer number of milliseconds", api_name);
    }
    const auto value = lua_tointeger(state, index);
    if (value < (allow_zero ? 0 : 1) ||
        value > static_cast<lua_Integer>(kLuaTimerMaximumDelayMs)) {
        luaL_error(
            state,
            "%s delay must be between %d and %u milliseconds",
            api_name,
            allow_zero ? 0 : 1,
            kLuaTimerMaximumDelayMs);
    }
    return static_cast<std::uint32_t>(value);
}

std::size_t ScheduledCallbackCount(const LoadedLuaMod& mod) {
    std::size_t count = 0;
    for (const auto& timer : mod.timers) {
        if (timer.kind != LuaTimerKind::Sequence) {
            if (timer.callback_reference != LUA_NOREF) {
                ++count;
            }
            continue;
        }
        for (std::size_t index = timer.sequence_index;
             index < timer.sequence_steps.size();
             ++index) {
            if (timer.sequence_steps[index].callback_reference != LUA_NOREF) {
                ++count;
            }
        }
    }
    return count;
}

void RequireCallbackCapacity(
    lua_State* state,
    const LoadedLuaMod& mod,
    std::size_t additional_count,
    const char* api_name) {
    const auto existing_count = ScheduledCallbackCount(mod);
    if (additional_count > kLuaTimerMaximumScheduledCallbacksPerMod ||
        existing_count >
            kLuaTimerMaximumScheduledCallbacksPerMod - additional_count) {
        luaL_error(
            state,
            "%s exceeds the per-mod limit of %zu scheduled callbacks",
            api_name,
            kLuaTimerMaximumScheduledCallbacksPerMod);
    }
}

std::uint64_t AllocateTimerId(LoadedLuaMod* mod) {
    const auto id = mod->next_timer_id;
    ++mod->next_timer_id;
    return id;
}

void ReleaseTimerReferences(lua_State* state, LuaTimerEntry* timer) {
    if (state == nullptr || timer == nullptr) {
        return;
    }
    if (timer->callback_reference != LUA_NOREF) {
        luaL_unref(state, LUA_REGISTRYINDEX, timer->callback_reference);
        timer->callback_reference = LUA_NOREF;
    }
    for (auto& step : timer->sequence_steps) {
        if (step.callback_reference != LUA_NOREF) {
            luaL_unref(state, LUA_REGISTRYINDEX, step.callback_reference);
            step.callback_reference = LUA_NOREF;
        }
    }
}

auto FindTimer(LoadedLuaMod* mod, std::uint64_t id) {
    return std::find_if(
        mod->timers.begin(),
        mod->timers.end(),
        [id](const LuaTimerEntry& timer) { return timer.id == id; });
}

bool CancelTimerById(LoadedLuaMod* mod, std::uint64_t id) {
    if (mod == nullptr) {
        return false;
    }
    const auto timer = FindTimer(mod, id);
    if (timer == mod->timers.end()) {
        return false;
    }
    ReleaseTimerReferences(mod->state, &*timer);
    mod->timers.erase(timer);
    return true;
}

std::uint64_t ReadTimerId(
    lua_State* state,
    int index,
    const char* api_name) {
    if (!lua_isinteger(state, index)) {
        luaL_error(state, "%s timer id must be a positive integer", api_name);
    }
    const auto value = lua_tointeger(state, index);
    if (value <= 0) {
        luaL_error(state, "%s timer id must be a positive integer", api_name);
    }
    return static_cast<std::uint64_t>(value);
}

int ScheduleSimpleTimer(
    lua_State* state,
    LuaTimerKind kind,
    const char* api_name) {
    auto* mod = RequireTimerMod(state, api_name);
    const bool repeating = kind == LuaTimerKind::Repeating;
    const auto delay_ms = ReadDelayMilliseconds(
        state,
        1,
        api_name,
        !repeating);
    luaL_checktype(state, 2, LUA_TFUNCTION);
    RequireCallbackCapacity(state, *mod, 1, api_name);

    lua_pushvalue(state, 2);
    const int callback_reference = luaL_ref(state, LUA_REGISTRYINDEX);
    LuaTimerEntry timer;
    timer.id = AllocateTimerId(mod);
    timer.due_ms = static_cast<std::uint64_t>(GetTickCount64()) + delay_ms;
    timer.interval_ms = repeating ? delay_ms : 0;
    timer.callback_reference = callback_reference;
    timer.kind = kind;
    const auto id = timer.id;
    mod->timers.push_back(std::move(timer));
    lua_pushinteger(state, static_cast<lua_Integer>(id));
    return 1;
}

int LuaTimerAfter(lua_State* state) {
    return ScheduleSimpleTimer(
        state,
        LuaTimerKind::Once,
        "sd.timer.after");
}

int LuaTimerEvery(lua_State* state) {
    return ScheduleSimpleTimer(
        state,
        LuaTimerKind::Repeating,
        "sd.timer.every");
}

int LuaTimerSequence(lua_State* state) {
    auto* mod = RequireTimerMod(state, "sd.timer.sequence");
    luaL_checktype(state, 1, LUA_TTABLE);
    const auto step_count = static_cast<std::size_t>(lua_rawlen(state, 1));
    if (step_count == 0 || step_count > kLuaTimerMaximumSequenceSteps) {
        return luaL_error(
            state,
            "sd.timer.sequence requires between 1 and %zu steps",
            kLuaTimerMaximumSequenceSteps);
    }
    RequireCallbackCapacity(
        state,
        *mod,
        step_count,
        "sd.timer.sequence");

    std::array<std::uint32_t, kLuaTimerMaximumSequenceSteps> delays{};
    std::uint64_t total_delay_ms = 0;
    for (std::size_t index = 1; index <= step_count; ++index) {
        lua_rawgeti(state, 1, static_cast<lua_Integer>(index));
        if (!lua_istable(state, -1)) {
            return luaL_error(
                state,
                "sd.timer.sequence step %zu must be a table",
                index);
        }
        lua_getfield(state, -1, "delay_ms");
        const auto delay_ms = ReadDelayMilliseconds(
            state,
            -1,
            "sd.timer.sequence",
            true);
        lua_pop(state, 1);
        lua_getfield(state, -1, "callback");
        if (!lua_isfunction(state, -1)) {
            return luaL_error(
                state,
                "sd.timer.sequence step %zu callback must be a function",
                index);
        }
        lua_pop(state, 2);

        total_delay_ms += delay_ms;
        if (total_delay_ms > kLuaTimerMaximumDelayMs) {
            return luaL_error(
                state,
                "sd.timer.sequence cumulative delay exceeds %u milliseconds",
                kLuaTimerMaximumDelayMs);
        }
        delays[index - 1] = delay_ms;
    }

    LuaTimerEntry timer;
    timer.id = AllocateTimerId(mod);
    timer.kind = LuaTimerKind::Sequence;
    timer.sequence_steps.reserve(step_count);
    for (std::size_t index = 1; index <= step_count; ++index) {
        lua_rawgeti(state, 1, static_cast<lua_Integer>(index));
        lua_getfield(state, -1, "callback");
        const int callback_reference = luaL_ref(state, LUA_REGISTRYINDEX);
        lua_pop(state, 1);
        timer.sequence_steps.push_back(
            LuaTimerSequenceStep{delays[index - 1], callback_reference});
    }
    timer.due_ms = static_cast<std::uint64_t>(GetTickCount64()) +
        timer.sequence_steps.front().delay_ms;
    const auto id = timer.id;
    mod->timers.push_back(std::move(timer));
    lua_pushinteger(state, static_cast<lua_Integer>(id));
    return 1;
}

int LuaTimerCancel(lua_State* state) {
    auto* mod = RequireTimerMod(state, "sd.timer.cancel");
    const auto id = ReadTimerId(state, 1, "sd.timer.cancel");
    lua_pushboolean(state, CancelTimerById(mod, id));
    return 1;
}

int LuaTimerClear(lua_State* state) {
    auto* mod = RequireTimerMod(state, "sd.timer.clear");
    const auto count = mod->timers.size();
    ClearLuaTimersForMod(mod);
    lua_pushinteger(state, static_cast<lua_Integer>(count));
    return 1;
}

}  // namespace

bool HasLuaTimers(const LoadedLuaMod* mod) {
    return mod != nullptr && !mod->timers.empty();
}

void DispatchLuaTimersToMod(
    LoadedLuaMod* mod,
    const RuntimeTickContext& context) {
    if (mod == nullptr || mod->state == nullptr || mod->timers.empty()) {
        return;
    }

    std::vector<std::uint64_t> due_ids;
    due_ids.reserve(kLuaTimerMaximumCallbacksPerTick);
    for (const auto& timer : mod->timers) {
        if (timer.due_ms <= context.monotonic_milliseconds) {
            due_ids.push_back(timer.id);
            if (due_ids.size() == kLuaTimerMaximumCallbacksPerTick) {
                break;
            }
        }
    }

    for (const auto id : due_ids) {
        auto timer = FindTimer(mod, id);
        if (timer == mod->timers.end()) {
            continue;
        }

        int callback_reference = LUA_NOREF;
        if (timer->kind == LuaTimerKind::Once) {
            callback_reference = timer->callback_reference;
            timer->callback_reference = LUA_NOREF;
            lua_rawgeti(mod->state, LUA_REGISTRYINDEX, callback_reference);
            luaL_unref(mod->state, LUA_REGISTRYINDEX, callback_reference);
            mod->timers.erase(timer);
        } else if (timer->kind == LuaTimerKind::Repeating) {
            callback_reference = timer->callback_reference;
            timer->due_ms = context.monotonic_milliseconds + timer->interval_ms;
            lua_rawgeti(mod->state, LUA_REGISTRYINDEX, callback_reference);
        } else {
            if (timer->sequence_index >= timer->sequence_steps.size()) {
                CancelTimerById(mod, id);
                continue;
            }
            auto& step = timer->sequence_steps[timer->sequence_index];
            callback_reference = step.callback_reference;
            step.callback_reference = LUA_NOREF;
            lua_rawgeti(mod->state, LUA_REGISTRYINDEX, callback_reference);
            luaL_unref(mod->state, LUA_REGISTRYINDEX, callback_reference);
            ++timer->sequence_index;
            if (timer->sequence_index == timer->sequence_steps.size()) {
                mod->timers.erase(timer);
            } else {
                timer->due_ms = context.monotonic_milliseconds +
                    timer->sequence_steps[timer->sequence_index].delay_ms;
            }
        }

        if (callback_reference == LUA_NOREF ||
            !lua_isfunction(mod->state, -1)) {
            lua_pop(mod->state, 1);
            CancelTimerById(mod, id);
            continue;
        }
        if (lua_pcall(mod->state, 0, 0, 0) != LUA_OK) {
            const auto* message = lua_tostring(mod->state, -1);
            LogLuaMessage(
                *mod,
                "timer callback " + std::to_string(id) + " failed: " +
                    (message == nullptr ? "unknown" : message));
            lua_pop(mod->state, 1);
            CancelTimerById(mod, id);
        }
    }
}

void ClearLuaTimersForMod(LoadedLuaMod* mod) {
    if (mod == nullptr) {
        return;
    }
    for (auto& timer : mod->timers) {
        ReleaseTimerReferences(mod->state, &timer);
    }
    mod->timers.clear();
}

void RegisterLuaTimerBindings(lua_State* state) {
    lua_createtable(state, 0, 5);
    RegisterFunction(state, &LuaTimerAfter, "after");
    RegisterFunction(state, &LuaTimerEvery, "every");
    RegisterFunction(state, &LuaTimerSequence, "sequence");
    RegisterFunction(state, &LuaTimerCancel, "cancel");
    RegisterFunction(state, &LuaTimerClear, "clear");
    lua_setfield(state, -2, "timer");
}

}  // namespace sdmod::detail
