#include "lua_camera_runtime.h"

#include "gameplay_seams.h"
#include "logger.h"
#include "memory_access.h"
#include "mod_loader.h"
#include "x86_hook.h"

#include <Windows.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <mutex>
#include <string>
#include <unordered_map>

namespace sdmod {
namespace {

constexpr std::size_t kRegionTickHookCount = 6;
constexpr std::size_t kRegionTickHookMinimumPatchSize = 5;
constexpr std::size_t kMaximumFocusOwners = 64;
constexpr float kMaximumCoordinateMagnitude = 1000000.0f;

enum RegionTickHookIndex : std::size_t {
    ArenaTick = 0,
    CourtyardTick,
    MortuaryTick,
    StoreRoomTick,
    LibraryTick,
    OfficeTick,
};

struct CameraFocusRequest {
    uintptr_t region_address = 0;
    float world_x = 0.0f;
    float world_y = 0.0f;
    std::uint64_t sequence = 0;
};

struct LuaCameraRuntimeState {
    std::mutex mutex;
    bool initialized = false;
    uintptr_t native_shake_function = 0;
    std::uint64_t next_focus_sequence = 1;
    std::unordered_map<std::string, CameraFocusRequest> focus_requests;
    std::array<X86Hook, kRegionTickHookCount> region_tick_hooks{};
};

LuaCameraRuntimeState& CameraRuntimeState() {
    static LuaCameraRuntimeState state;
    return state;
}

using RegionTickFn = void(__thiscall*)(void* self);
using NativeCameraShakeFn = void(__thiscall*)(void* self, float intensity);

int CaptureLuaCameraSehCode(
    EXCEPTION_POINTERS* exception_pointers,
    DWORD* exception_code) noexcept {
    if (exception_code != nullptr && exception_pointers != nullptr &&
        exception_pointers->ExceptionRecord != nullptr) {
        *exception_code =
            exception_pointers->ExceptionRecord->ExceptionCode;
    }
    return EXCEPTION_EXECUTE_HANDLER;
}

bool InvokeNativeCameraShake(
    uintptr_t function_address,
    uintptr_t region_address,
    float intensity,
    DWORD* exception_code) noexcept {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    __try {
        reinterpret_cast<NativeCameraShakeFn>(function_address)(
            reinterpret_cast<void*>(region_address),
            intensity);
        return true;
    } __except (CaptureLuaCameraSehCode(
        GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool TryReadCameraField(
    uintptr_t region_address,
    std::size_t offset,
    float* value) {
    return offset != 0 && value != nullptr &&
           ProcessMemory::Instance().TryReadField(
               region_address,
               offset,
               value) &&
           std::isfinite(*value);
}

bool TryTranslateCameraRectangles(
    uintptr_t region_address,
    float focus_x,
    float focus_y) {
    const std::array<std::size_t, 3> x_offsets = {
        kActorWorldViewOriginXOffset,
        kActorWorldExpandedViewOriginXOffset,
        kActorWorldCullViewOriginXOffset,
    };
    const std::array<std::size_t, 3> y_offsets = {
        kActorWorldViewOriginYOffset,
        kActorWorldExpandedViewOriginYOffset,
        kActorWorldCullViewOriginYOffset,
    };

    float width = 0.0f;
    float height = 0.0f;
    std::array<float, 3> original_x{};
    std::array<float, 3> original_y{};
    if (!TryReadCameraField(
            region_address,
            kActorWorldViewWidthOffset,
            &width) ||
        !TryReadCameraField(
            region_address,
            kActorWorldViewHeightOffset,
            &height) ||
        width <= 0.0f || height <= 0.0f) {
        return false;
    }
    for (std::size_t index = 0; index < x_offsets.size(); ++index) {
        if (!TryReadCameraField(
                region_address,
                x_offsets[index],
                &original_x[index]) ||
            !TryReadCameraField(
                region_address,
                y_offsets[index],
                &original_y[index])) {
            return false;
        }
    }

    const float desired_origin_x = focus_x - width * 0.5f;
    const float desired_origin_y = focus_y - height * 0.5f;
    const float delta_x = desired_origin_x - original_x.front();
    const float delta_y = desired_origin_y - original_y.front();
    if (!std::isfinite(delta_x) || !std::isfinite(delta_y)) {
        return false;
    }

    std::array<float, 3> translated_x{};
    std::array<float, 3> translated_y{};
    for (std::size_t index = 0; index < x_offsets.size(); ++index) {
        translated_x[index] = original_x[index] + delta_x;
        translated_y[index] = original_y[index] + delta_y;
        if (!std::isfinite(translated_x[index]) ||
            !std::isfinite(translated_y[index]) ||
            std::abs(translated_x[index]) > kMaximumCoordinateMagnitude ||
            std::abs(translated_y[index]) > kMaximumCoordinateMagnitude) {
            return false;
        }
    }

    auto& memory = ProcessMemory::Instance();
    std::size_t written_pairs = 0;
    for (; written_pairs < x_offsets.size(); ++written_pairs) {
        if (!memory.TryWriteField(
                region_address,
                x_offsets[written_pairs],
                translated_x[written_pairs]) ||
            !memory.TryWriteField(
                region_address,
                y_offsets[written_pairs],
                translated_y[written_pairs])) {
            break;
        }
    }
    if (written_pairs == x_offsets.size()) {
        return true;
    }

    for (std::size_t index = 0;
         index <= written_pairs && index < x_offsets.size();
         ++index) {
        (void)memory.TryWriteField(
            region_address,
            x_offsets[index],
            original_x[index]);
        (void)memory.TryWriteField(
            region_address,
            y_offsets[index],
            original_y[index]);
    }
    return false;
}

void ApplyActiveCameraFocus(void* region) {
    const auto region_address = reinterpret_cast<uintptr_t>(region);
    if (region_address == 0) {
        return;
    }

    SDModSceneState scene;
    if (!TryGetSceneState(&scene) || !scene.valid ||
        scene.world_address != region_address) {
        return;
    }

    CameraFocusRequest selected;
    bool have_selected = false;
    {
        auto& state = CameraRuntimeState();
        std::scoped_lock lock(state.mutex);
        if (!state.initialized) {
            return;
        }
        for (auto it = state.focus_requests.begin();
             it != state.focus_requests.end();) {
            if (it->second.region_address != region_address) {
                it = state.focus_requests.erase(it);
                continue;
            }
            if (!have_selected ||
                it->second.sequence > selected.sequence) {
                selected = it->second;
                have_selected = true;
            }
            ++it;
        }
    }
    if (have_selected) {
        (void)TryTranslateCameraRectangles(
            region_address,
            selected.world_x,
            selected.world_y);
    }
}

void InvokeRegionTickAndApplyFocus(
    RegionTickHookIndex index,
    void* self) {
    auto& state = CameraRuntimeState();
    const auto original = GetX86HookTrampoline<RegionTickFn>(
        state.region_tick_hooks[static_cast<std::size_t>(index)]);
    if (original == nullptr) {
        return;
    }
    original(self);
    ApplyActiveCameraFocus(self);
}

void __fastcall HookArenaRegionTick(void* self, void*) {
    InvokeRegionTickAndApplyFocus(ArenaTick, self);
}

void __fastcall HookCourtyardRegionTick(void* self, void*) {
    InvokeRegionTickAndApplyFocus(CourtyardTick, self);
}

void __fastcall HookMortuaryRegionTick(void* self, void*) {
    InvokeRegionTickAndApplyFocus(MortuaryTick, self);
}

void __fastcall HookStoreRoomRegionTick(void* self, void*) {
    InvokeRegionTickAndApplyFocus(StoreRoomTick, self);
}

void __fastcall HookLibraryRegionTick(void* self, void*) {
    InvokeRegionTickAndApplyFocus(LibraryTick, self);
}

void __fastcall HookOfficeRegionTick(void* self, void*) {
    InvokeRegionTickAndApplyFocus(OfficeTick, self);
}

}  // namespace

bool InitializeLuaCameraRuntime(std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }

    auto& state = CameraRuntimeState();
    std::scoped_lock lock(state.mutex);
    if (state.initialized) {
        return true;
    }

    const std::array<uintptr_t, kRegionTickHookCount> configured_ticks = {
        kArenaRegionTick,
        kCourtyardRegionTick,
        kMortuaryRegionTick,
        kStoreRoomRegionTick,
        kLibraryRegionTick,
        kOfficeRegionTick,
    };
    const std::array<void*, kRegionTickHookCount> detours = {
        reinterpret_cast<void*>(&HookArenaRegionTick),
        reinterpret_cast<void*>(&HookCourtyardRegionTick),
        reinterpret_cast<void*>(&HookMortuaryRegionTick),
        reinterpret_cast<void*>(&HookStoreRoomRegionTick),
        reinterpret_cast<void*>(&HookLibraryRegionTick),
        reinterpret_cast<void*>(&HookOfficeRegionTick),
    };

    auto& memory = ProcessMemory::Instance();
    std::array<uintptr_t, kRegionTickHookCount> resolved_ticks{};
    for (std::size_t index = 0; index < configured_ticks.size(); ++index) {
        resolved_ticks[index] =
            memory.ResolveGameAddressOrZero(configured_ticks[index]);
    }
    const auto native_shake_function =
        memory.ResolveGameAddressOrZero(kRegionApplyCameraShake);
    const bool offsets_available =
        kActorWorldViewScaleOffset != 0 &&
        kActorWorldViewOriginXOffset != 0 &&
        kActorWorldViewOriginYOffset != 0 &&
        kActorWorldViewWidthOffset != 0 &&
        kActorWorldViewHeightOffset != 0 &&
        kActorWorldExpandedViewOriginXOffset != 0 &&
        kActorWorldExpandedViewOriginYOffset != 0 &&
        kActorWorldCullViewOriginXOffset != 0 &&
        kActorWorldCullViewOriginYOffset != 0 &&
        kActorWorldCameraShakeMagnitudeOffset != 0 &&
        kActorWorldCameraShakeAccumulatorOffset != 0;
    if (!offsets_available || native_shake_function == 0 ||
        std::any_of(
            resolved_ticks.begin(),
            resolved_ticks.end(),
            [](uintptr_t address) { return address == 0; })) {
        if (error_message != nullptr) {
            *error_message =
                "Lua camera runtime could not resolve its Region tick, view, or shake seams.";
        }
        return false;
    }

    for (std::size_t index = 0; index < resolved_ticks.size(); ++index) {
        std::string hook_error;
        if (!InstallSafeX86Hook(
                reinterpret_cast<void*>(resolved_ticks[index]),
                detours[index],
                kRegionTickHookMinimumPatchSize,
                &state.region_tick_hooks[index],
                &hook_error)) {
            for (std::size_t installed = 0; installed < index; ++installed) {
                RemoveX86Hook(&state.region_tick_hooks[installed]);
            }
            if (error_message != nullptr) {
                *error_message =
                    "Lua camera runtime failed to install Region tick hook " +
                    std::to_string(index) + ": " + hook_error;
            }
            return false;
        }
    }

    state.native_shake_function = native_shake_function;
    state.next_focus_sequence = 1;
    state.focus_requests.clear();
    state.initialized = true;
    Log("Lua camera runtime initialized with six post-Region-tick focus hooks.");
    return true;
}

void ShutdownLuaCameraRuntime() {
    auto& state = CameraRuntimeState();
    {
        std::scoped_lock lock(state.mutex);
        state.initialized = false;
        state.native_shake_function = 0;
        state.focus_requests.clear();
    }
    RemoveHookSet(
        state.region_tick_hooks.data(),
        state.region_tick_hooks.size());
}

bool IsLuaCameraRuntimeAvailable() {
    auto& state = CameraRuntimeState();
    std::scoped_lock lock(state.mutex);
    return state.initialized;
}

void AppendLuaCameraCapabilities(std::vector<std::string>* capabilities) {
    if (capabilities == nullptr || !IsLuaCameraRuntimeAvailable()) {
        return;
    }
    capabilities->emplace_back("camera.local.read");
    capabilities->emplace_back("camera.local.focus");
    capabilities->emplace_back("camera.local.shake");
}

bool TryGetLuaCameraSnapshot(
    std::string_view caller_mod_id,
    LuaCameraSnapshot* snapshot) {
    if (snapshot == nullptr) {
        return false;
    }
    *snapshot = LuaCameraSnapshot{};
    snapshot->runtime_available = IsLuaCameraRuntimeAvailable();
    if (!snapshot->runtime_available) {
        return true;
    }

    SDModSceneState scene;
    if (!TryGetSceneState(&scene) || !scene.valid ||
        scene.world_address == 0) {
        return true;
    }

    if (!TryReadCameraField(
            scene.world_address,
            kActorWorldViewOriginXOffset,
            &snapshot->origin_x) ||
        !TryReadCameraField(
            scene.world_address,
            kActorWorldViewOriginYOffset,
            &snapshot->origin_y) ||
        !TryReadCameraField(
            scene.world_address,
            kActorWorldViewWidthOffset,
            &snapshot->width) ||
        !TryReadCameraField(
            scene.world_address,
            kActorWorldViewHeightOffset,
            &snapshot->height) ||
        !TryReadCameraField(
            scene.world_address,
            kActorWorldViewScaleOffset,
            &snapshot->scale) ||
        !TryReadCameraField(
            scene.world_address,
            kActorWorldCameraShakeMagnitudeOffset,
            &snapshot->shake_magnitude) ||
        !TryReadCameraField(
            scene.world_address,
            kActorWorldCameraShakeAccumulatorOffset,
            &snapshot->shake_accumulator) ||
        snapshot->width <= 0.0f || snapshot->height <= 0.0f ||
        snapshot->scale <= 0.0f) {
        return true;
    }
    snapshot->scene_available = true;
    snapshot->center_x = snapshot->origin_x + snapshot->width * 0.5f;
    snapshot->center_y = snapshot->origin_y + snapshot->height * 0.5f;

    auto& state = CameraRuntimeState();
    std::scoped_lock lock(state.mutex);
    std::uint64_t selected_sequence = 0;
    for (const auto& [owner, request] : state.focus_requests) {
        if (request.region_address != scene.world_address ||
            request.sequence <= selected_sequence) {
            continue;
        }
        selected_sequence = request.sequence;
        snapshot->focus_active = true;
        snapshot->caller_owns_focus = owner == caller_mod_id;
        snapshot->focus_x = request.world_x;
        snapshot->focus_y = request.world_y;
    }
    return true;
}

bool SetLocalCameraFocus(
    std::string_view owner_id,
    float world_x,
    float world_y,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (owner_id.empty() || !std::isfinite(world_x) ||
        !std::isfinite(world_y) ||
        std::abs(world_x) > kMaximumCoordinateMagnitude ||
        std::abs(world_y) > kMaximumCoordinateMagnitude) {
        if (error_message != nullptr) {
            *error_message = "camera focus coordinates are invalid";
        }
        return false;
    }

    SDModSceneState scene;
    if (!TryGetSceneState(&scene) || !scene.valid ||
        scene.world_address == 0) {
        if (error_message != nullptr) {
            *error_message = "no native Region camera is active";
        }
        return false;
    }

    auto& state = CameraRuntimeState();
    std::scoped_lock lock(state.mutex);
    if (!state.initialized) {
        if (error_message != nullptr) {
            *error_message = "local camera runtime is unavailable";
        }
        return false;
    }
    const std::string owner(owner_id);
    if (state.focus_requests.find(owner) == state.focus_requests.end() &&
        state.focus_requests.size() >= kMaximumFocusOwners) {
        if (error_message != nullptr) {
            *error_message = "local camera focus-owner limit reached";
        }
        return false;
    }
    state.focus_requests[owner] = CameraFocusRequest{
        scene.world_address,
        world_x,
        world_y,
        state.next_focus_sequence++,
    };
    return true;
}

bool ClearLocalCameraFocus(std::string_view owner_id) {
    if (owner_id.empty()) {
        return false;
    }
    auto& state = CameraRuntimeState();
    std::scoped_lock lock(state.mutex);
    return state.focus_requests.erase(std::string(owner_id)) != 0;
}

bool SetLuaCameraFocus(
    std::string_view mod_id,
    float world_x,
    float world_y,
    std::string* error_message) {
    return SetLocalCameraFocus(
        mod_id,
        world_x,
        world_y,
        error_message);
}

bool ClearLuaCameraFocus(std::string_view mod_id) {
    return ClearLocalCameraFocus(mod_id);
}

bool ApplyLuaCameraShake(float intensity, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!std::isfinite(intensity) || intensity <= 0.0f ||
        intensity > 1.0f) {
        if (error_message != nullptr) {
            *error_message = "camera shake intensity must be finite, greater than 0, and at most 1";
        }
        return false;
    }

    uintptr_t native_shake_function = 0;
    {
        auto& state = CameraRuntimeState();
        std::scoped_lock lock(state.mutex);
        if (!state.initialized) {
            if (error_message != nullptr) {
                *error_message = "Lua camera runtime is unavailable";
            }
            return false;
        }
        native_shake_function = state.native_shake_function;
    }

    SDModSceneState scene;
    if (!TryGetSceneState(&scene) || !scene.valid ||
        scene.world_address == 0) {
        if (error_message != nullptr) {
            *error_message = "no native Region camera is active";
        }
        return false;
    }

    DWORD exception_code = 0;
    if (!InvokeNativeCameraShake(
            native_shake_function,
            scene.world_address,
            intensity,
            &exception_code)) {
        if (error_message != nullptr) {
            *error_message =
                "native camera shake raised exception " +
                std::to_string(exception_code);
        }
        return false;
    }
    return true;
}

}  // namespace sdmod
