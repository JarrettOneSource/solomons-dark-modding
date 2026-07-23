#include "lua_engine_bindings_internal.h"

#include "lua_time_runtime.h"
#include "multiplayer_local_transport.h"
#include "multiplayer_runtime_state.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <mutex>
#include <string>
#include <unordered_map>
#include <utility>

namespace sdmod {
namespace {

constexpr std::uint64_t kLuaTimeMaximumStepSequence =
    0x7FFFFFFFFFFFFFFFull;

struct LuaTimeRuntimeState {
    std::unordered_map<std::string, std::uint32_t> scale_by_mod;
    std::uint32_t scale_units = kLuaTimeScaleUnitsPerOne;
    std::uint32_t revision = 1;
    std::uint64_t step_sequence = 0;
    std::uint64_t consumed_step_sequence = 0;
    std::uint64_t frame_accumulator = 0;
    std::uint32_t unsent_step_frames = 0;
    std::uint64_t authority_participant_id = 0;
    std::uint32_t run_nonce = 0;
    bool replicated = false;
};

std::mutex g_lua_time_mutex;
LuaTimeRuntimeState g_lua_time;
thread_local std::uint32_t g_lua_time_frame_scope_depth = 0;
thread_local bool g_lua_time_frame_scope_advance = true;

void SetLuaTimeError(std::string* error_message, std::string message) {
    if (error_message != nullptr) {
        *error_message = std::move(message);
    }
}

std::uint32_t NextLuaTimeRevision(std::uint32_t revision) {
    ++revision;
    return revision == 0 ? 1 : revision;
}

bool IsNewerLuaTimeRevision(
    std::uint32_t candidate,
    std::uint32_t current) {
    return candidate != current &&
        static_cast<std::int32_t>(candidate - current) > 0;
}

void ResetFrameAccumulator(LuaTimeRuntimeState* state) {
    if (state == nullptr) return;
    if (state->scale_units == 0 ||
        state->scale_units == kLuaTimeScaleUnitsPerOne) {
        state->frame_accumulator = 0;
        return;
    }
    state->frame_accumulator =
        kLuaTimeScaleUnitsPerOne - state->scale_units;
}

void ApplyEffectiveScaleLocked(std::uint32_t scale_units) {
    if (g_lua_time.scale_units == scale_units) return;
    g_lua_time.scale_units = scale_units;
    g_lua_time.revision = NextLuaTimeRevision(g_lua_time.revision);
    g_lua_time.unsent_step_frames = 0;
    if (scale_units != 0) {
        g_lua_time.consumed_step_sequence = g_lua_time.step_sequence;
    }
    ResetFrameAccumulator(&g_lua_time);
}

void RecomputeEffectiveScaleLocked() {
    std::uint32_t effective = kLuaTimeScaleUnitsPerOne;
    for (const auto& [mod_id, requested] : g_lua_time.scale_by_mod) {
        (void)mod_id;
        effective = (std::min)(effective, requested);
    }
    ApplyEffectiveScaleLocked(effective);
}

void ResetLuaTimeLocked(bool preserve_revision) {
    const auto next_revision = preserve_revision
        ? NextLuaTimeRevision(g_lua_time.revision)
        : 1u;
    g_lua_time = LuaTimeRuntimeState{};
    g_lua_time.revision = next_revision;
}

std::uint64_t PendingStepFramesLocked() {
    return g_lua_time.step_sequence >= g_lua_time.consumed_step_sequence
        ? g_lua_time.step_sequence - g_lua_time.consumed_step_sequence
        : 0;
}

}  // namespace

void InitializeLuaTimeRuntime() {
    std::scoped_lock lock(g_lua_time_mutex);
    ResetLuaTimeLocked(false);
    g_lua_time_frame_scope_depth = 0;
    g_lua_time_frame_scope_advance = true;
}

void ShutdownLuaTimeRuntime() {
    std::scoped_lock lock(g_lua_time_mutex);
    ResetLuaTimeLocked(false);
    g_lua_time_frame_scope_depth = 0;
    g_lua_time_frame_scope_advance = true;
}

void ResetLuaTimeControlForRun() {
    std::scoped_lock lock(g_lua_time_mutex);
    ResetLuaTimeLocked(true);
}

bool SetLuaTimeScaleRequest(
    std::string_view mod_id,
    std::uint32_t scale_units,
    std::string* error_message) {
    if (error_message != nullptr) error_message->clear();
    if (mod_id.empty() || scale_units > kLuaTimeScaleUnitsPerOne) {
        SetLuaTimeError(error_message, "Lua time scale request is invalid");
        return false;
    }

    std::scoped_lock lock(g_lua_time_mutex);
    if (g_lua_time.replicated) {
        SetLuaTimeError(
            error_message,
            "Lua time scale is owned by the multiplayer authority");
        return false;
    }
    const std::string key(mod_id);
    const auto existing = g_lua_time.scale_by_mod.find(key);
    if (scale_units == kLuaTimeScaleUnitsPerOne) {
        if (existing != g_lua_time.scale_by_mod.end()) {
            g_lua_time.scale_by_mod.erase(existing);
            RecomputeEffectiveScaleLocked();
        }
        return true;
    }
    if (existing == g_lua_time.scale_by_mod.end() &&
        g_lua_time.scale_by_mod.size() >=
            kLuaTimeMaximumControllingMods) {
        SetLuaTimeError(error_message, "Lua time controller limit reached");
        return false;
    }
    g_lua_time.scale_by_mod[key] = scale_units;
    RecomputeEffectiveScaleLocked();
    return true;
}

bool QueueLuaTimeStepFrames(
    std::string_view mod_id,
    std::uint32_t frame_count,
    std::uint64_t* step_sequence,
    std::string* error_message) {
    if (step_sequence != nullptr) *step_sequence = 0;
    if (error_message != nullptr) error_message->clear();
    if (mod_id.empty() || frame_count == 0 ||
        frame_count > kLuaTimeMaximumStepFrames) {
        SetLuaTimeError(error_message, "Lua time frame-step count is invalid");
        return false;
    }

    std::scoped_lock lock(g_lua_time_mutex);
    const auto request = g_lua_time.scale_by_mod.find(std::string(mod_id));
    if (g_lua_time.replicated || g_lua_time.scale_units != 0 ||
        request == g_lua_time.scale_by_mod.end() || request->second != 0) {
        SetLuaTimeError(
            error_message,
            "Lua time frame-step requires this mod to hold a zero-scale request");
        return false;
    }
    if (PendingStepFramesLocked() + frame_count >
        kLuaTimeMaximumStepFrames) {
        SetLuaTimeError(error_message, "Lua time frame-step queue is full");
        return false;
    }
    if (g_lua_time.step_sequence >
        kLuaTimeMaximumStepSequence - frame_count) {
        SetLuaTimeError(error_message, "Lua time frame-step sequence is exhausted");
        return false;
    }
    g_lua_time.step_sequence += frame_count;
    if (multiplayer::IsLocalTransportHost()) {
        g_lua_time.unsent_step_frames += frame_count;
    }
    g_lua_time.revision = NextLuaTimeRevision(g_lua_time.revision);
    if (step_sequence != nullptr) {
        *step_sequence = g_lua_time.step_sequence;
    }
    return true;
}

bool TryGetLuaTimeScaleRequest(
    std::string_view mod_id,
    std::uint32_t* scale_units) {
    if (scale_units == nullptr || mod_id.empty()) return false;
    std::scoped_lock lock(g_lua_time_mutex);
    const auto found = g_lua_time.scale_by_mod.find(std::string(mod_id));
    if (found == g_lua_time.scale_by_mod.end()) return false;
    *scale_units = found->second;
    return true;
}

void ClearLuaTimeScaleRequest(std::string_view mod_id) {
    if (mod_id.empty()) return;
    std::scoped_lock lock(g_lua_time_mutex);
    if (g_lua_time.scale_by_mod.erase(std::string(mod_id)) != 0) {
        RecomputeEffectiveScaleLocked();
    }
}

LuaTimeControlSnapshot SnapshotLuaTimeControl() {
    std::scoped_lock lock(g_lua_time_mutex);
    return LuaTimeControlSnapshot{
        g_lua_time.scale_units,
        g_lua_time.revision,
        g_lua_time.step_sequence,
        g_lua_time.consumed_step_sequence,
        g_lua_time.unsent_step_frames,
        g_lua_time.authority_participant_id,
        g_lua_time.run_nonce,
        g_lua_time.replicated,
    };
}

bool ApplyReplicatedLuaTimeControl(
    std::uint64_t authority_participant_id,
    std::uint32_t run_nonce,
    std::uint32_t scale_units,
    std::uint32_t revision,
    std::uint64_t step_sequence,
    std::uint32_t step_frames) {
    if (authority_participant_id == 0 || run_nonce == 0 || revision == 0 ||
        scale_units > kLuaTimeScaleUnitsPerOne ||
        step_frames > kLuaTimeMaximumStepFrames ||
        (step_frames != 0 && scale_units != 0) ||
        step_sequence > kLuaTimeMaximumStepSequence ||
        step_sequence < step_frames) {
        return false;
    }

    std::scoped_lock lock(g_lua_time_mutex);
    const bool identity_changed =
        !g_lua_time.replicated ||
        g_lua_time.authority_participant_id != authority_participant_id ||
        g_lua_time.run_nonce != run_nonce;
    if (!identity_changed && revision != g_lua_time.revision &&
        !IsNewerLuaTimeRevision(revision, g_lua_time.revision)) {
        return false;
    }
    if (!identity_changed && revision == g_lua_time.revision &&
        scale_units != g_lua_time.scale_units) {
        return false;
    }

    const auto previous_scale = g_lua_time.scale_units;
    if (identity_changed || revision != g_lua_time.revision) {
        g_lua_time.scale_by_mod.clear();
        g_lua_time.scale_units = scale_units;
        g_lua_time.revision = revision;
        g_lua_time.unsent_step_frames = 0;
        g_lua_time.authority_participant_id = authority_participant_id;
        g_lua_time.run_nonce = run_nonce;
        g_lua_time.replicated = true;
        if (scale_units != 0) {
            g_lua_time.step_sequence = step_sequence;
            g_lua_time.consumed_step_sequence = step_sequence;
        } else if (identity_changed || previous_scale != 0) {
            g_lua_time.step_sequence = step_sequence;
            g_lua_time.consumed_step_sequence = step_sequence - step_frames;
        }
        ResetFrameAccumulator(&g_lua_time);
    }

    if (step_frames == 0 || scale_units != 0 ||
        step_sequence <= g_lua_time.step_sequence) {
        return true;
    }
    if (step_sequence - g_lua_time.step_sequence > step_frames) {
        g_lua_time.consumed_step_sequence = step_sequence - step_frames;
    }
    g_lua_time.step_sequence = step_sequence;
    const auto pending = PendingStepFramesLocked();
    if (pending > kLuaTimeMaximumStepFrames) {
        g_lua_time.consumed_step_sequence =
            g_lua_time.step_sequence - kLuaTimeMaximumStepFrames;
    }
    return true;
}

void ResetReplicatedLuaTimeControl(
    std::uint64_t authority_participant_id) {
    std::scoped_lock lock(g_lua_time_mutex);
    if (!g_lua_time.replicated ||
        (authority_participant_id != 0 &&
         g_lua_time.authority_participant_id != authority_participant_id)) {
        return;
    }
    ResetLuaTimeLocked(true);
}

void MarkLuaTimeControlUpdateSent(std::uint32_t revision) {
    std::scoped_lock lock(g_lua_time_mutex);
    if (!g_lua_time.replicated && g_lua_time.revision == revision) {
        g_lua_time.unsent_step_frames = 0;
    }
}

bool BeginLuaTimeSimulationFrame(bool external_pause_active) {
    if (g_lua_time_frame_scope_depth++ != 0) {
        return g_lua_time_frame_scope_advance;
    }
    if (external_pause_active) {
        g_lua_time_frame_scope_advance = false;
        return false;
    }

    std::scoped_lock lock(g_lua_time_mutex);
    if (g_lua_time.scale_units == kLuaTimeScaleUnitsPerOne) {
        g_lua_time_frame_scope_advance = true;
        return true;
    }
    if (g_lua_time.scale_units == 0) {
        if (g_lua_time.consumed_step_sequence <
            g_lua_time.step_sequence) {
            ++g_lua_time.consumed_step_sequence;
            g_lua_time_frame_scope_advance = true;
            return true;
        }
        g_lua_time_frame_scope_advance = false;
        return false;
    }
    g_lua_time.frame_accumulator += g_lua_time.scale_units;
    if (g_lua_time.frame_accumulator >= kLuaTimeScaleUnitsPerOne) {
        g_lua_time.frame_accumulator -= kLuaTimeScaleUnitsPerOne;
        g_lua_time_frame_scope_advance = true;
        return true;
    }
    g_lua_time_frame_scope_advance = false;
    return false;
}

void EndLuaTimeSimulationFrame() {
    if (g_lua_time_frame_scope_depth == 0) return;
    --g_lua_time_frame_scope_depth;
    if (g_lua_time_frame_scope_depth == 0) {
        g_lua_time_frame_scope_advance = true;
    }
}

bool ShouldHoldLuaTimeSimulationFrame() {
    if (g_lua_time_frame_scope_depth != 0) {
        return !g_lua_time_frame_scope_advance;
    }
    std::scoped_lock lock(g_lua_time_mutex);
    return g_lua_time.scale_units == 0;
}

}  // namespace sdmod

namespace sdmod::detail {
namespace {

bool HasActiveLuaTimeRun() {
    const auto runtime = multiplayer::SnapshotRuntimeState();
    const auto* local = multiplayer::FindLocalParticipant(runtime);
    return local != nullptr && local->runtime.in_run &&
        local->runtime.run_nonce != 0;
}

LoadedLuaMod* RequireLuaTimeMod(lua_State* state, const char* api_name) {
    auto* mod = GetLoadedLuaMod(state);
    if (mod == nullptr) luaL_error(state, "%s is unavailable", api_name);
    return mod;
}

void RequireLuaTimeAuthority(lua_State* state, const char* api_name) {
    if (!multiplayer::IsLuaModSimulationAuthority()) {
        luaL_error(
            state,
            "%s may only be called by the simulation authority",
            api_name);
    }
}

lua_Number LuaTimeScaleNumber(std::uint32_t scale_units) {
    return static_cast<lua_Number>(scale_units) /
        static_cast<lua_Number>(kLuaTimeScaleUnitsPerOne);
}

void PushLuaTimeState(lua_State* state, const LoadedLuaMod* mod) {
    const auto snapshot = SnapshotLuaTimeControl();
    const auto runtime = multiplayer::SnapshotRuntimeState();
    const auto* local = multiplayer::FindLocalParticipant(runtime);
    const auto authority_participant_id = snapshot.replicated
        ? snapshot.authority_participant_id
        : multiplayer::GetLocalTransportParticipantId();
    const auto run_nonce = snapshot.replicated
        ? snapshot.run_nonce
        : (local == nullptr ? 0u : local->runtime.run_nonce);
    const auto pending_steps = snapshot.step_sequence >=
            snapshot.consumed_step_sequence
        ? snapshot.step_sequence - snapshot.consumed_step_sequence
        : 0;
    lua_createtable(state, 0, 11);
    lua_pushnumber(state, LuaTimeScaleNumber(snapshot.scale_units));
    lua_setfield(state, -2, "scale");
    lua_pushboolean(state, snapshot.scale_units == 0 ? 1 : 0);
    lua_setfield(state, -2, "paused");
    lua_pushinteger(state, snapshot.revision);
    lua_setfield(state, -2, "revision");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.step_sequence));
    lua_setfield(state, -2, "step_sequence");
    lua_pushinteger(state, static_cast<lua_Integer>(pending_steps));
    lua_setfield(state, -2, "pending_steps");
    lua_pushboolean(state, snapshot.replicated ? 1 : 0);
    lua_setfield(state, -2, "replicated");
    lua_pushinteger(
        state,
        static_cast<lua_Integer>(authority_participant_id));
    lua_setfield(state, -2, "authority_participant_id");
    lua_pushinteger(state, run_nonce);
    lua_setfield(state, -2, "run_nonce");
    lua_pushinteger(state, kLuaTimeMaximumStepFrames);
    lua_setfield(state, -2, "maximum_step_frames");
    lua_pushnumber(
        state,
        1.0 / static_cast<lua_Number>(kLuaTimeScaleUnitsPerOne));
    lua_setfield(state, -2, "scale_resolution");
    std::uint32_t requested_scale = 0;
    if (mod != nullptr && TryGetLuaTimeScaleRequest(
            mod->descriptor.id,
            &requested_scale)) {
        lua_pushnumber(state, LuaTimeScaleNumber(requested_scale));
    } else {
        lua_pushnil(state);
    }
    lua_setfield(state, -2, "requested_scale");
}

int LuaTimeGetScale(lua_State* state) {
    lua_pushnumber(
        state,
        LuaTimeScaleNumber(SnapshotLuaTimeControl().scale_units));
    return 1;
}

int LuaTimeGetState(lua_State* state) {
    PushLuaTimeState(state, RequireLuaTimeMod(state, "sd.time.get_state"));
    return 1;
}

int LuaTimeSetScale(lua_State* state) {
    constexpr const char* kApiName = "sd.time.set_scale";
    auto* mod = RequireLuaTimeMod(state, kApiName);
    RequireLuaTimeAuthority(state, kApiName);
    const auto scale = luaL_checknumber(state, 1);
    if (!std::isfinite(scale) || scale < 0.0 || scale > 1.0) {
        return luaL_error(state, "%s scale must be from 0 through 1", kApiName);
    }
    const auto scaled = static_cast<double>(scale) *
        static_cast<double>(kLuaTimeScaleUnitsPerOne);
    const auto scale_units = static_cast<std::uint32_t>(std::llround(scaled));
    if (scale != 0.0 && scale_units == 0) {
        return luaL_error(
            state,
            "%s non-zero scale is below the 0.000001 resolution",
            kApiName);
    }
    if (scale_units != kLuaTimeScaleUnitsPerOne &&
        !HasActiveLuaTimeRun()) {
        return luaL_error(state, "%s requires an active run", kApiName);
    }
    std::string error_message;
    if (!SetLuaTimeScaleRequest(
            mod->descriptor.id,
            scale_units,
            &error_message)) {
        return luaL_error(state, "%s: %s", kApiName, error_message.c_str());
    }
    lua_pushnumber(
        state,
        LuaTimeScaleNumber(SnapshotLuaTimeControl().scale_units));
    return 1;
}

int LuaTimeStep(lua_State* state) {
    constexpr const char* kApiName = "sd.time.step";
    auto* mod = RequireLuaTimeMod(state, kApiName);
    RequireLuaTimeAuthority(state, kApiName);
    if (!HasActiveLuaTimeRun()) {
        return luaL_error(state, "%s requires an active run", kApiName);
    }
    const auto frames = luaL_optinteger(state, 1, 1);
    if (frames < 1 || frames > kLuaTimeMaximumStepFrames) {
        return luaL_error(
            state,
            "%s frames must be from 1 through %u",
            kApiName,
            kLuaTimeMaximumStepFrames);
    }
    std::uint64_t sequence = 0;
    std::string error_message;
    if (!QueueLuaTimeStepFrames(
            mod->descriptor.id,
            static_cast<std::uint32_t>(frames),
            &sequence,
            &error_message)) {
        return luaL_error(state, "%s: %s", kApiName, error_message.c_str());
    }
    lua_pushinteger(state, static_cast<lua_Integer>(sequence));
    return 1;
}

}  // namespace

void RegisterLuaTimeBindings(lua_State* state) {
    lua_createtable(state, 0, 4);
    RegisterFunction(state, &LuaTimeGetScale, "get_scale");
    RegisterFunction(state, &LuaTimeGetState, "get_state");
    RegisterFunction(state, &LuaTimeSetScale, "set_scale");
    RegisterFunction(state, &LuaTimeStep, "step");
    lua_setfield(state, -2, "time");
}

}  // namespace sdmod::detail
