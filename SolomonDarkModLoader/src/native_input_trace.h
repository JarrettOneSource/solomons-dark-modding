#pragma once

#include <Windows.h>

#include <cstdint>
#include <string>
#include <string_view>

namespace sdmod {

struct NativeInputActiveSpellObservation {
    bool readable = false;
    std::uintptr_t object_address = 0;
    std::uint32_t object_type = 0;
    std::uint32_t phase = 0;
    std::uint32_t release_timer = 0;
    float charge = 0.0f;
    float growth_rate = 0.0f;
    float max_charge = 0.0f;
};

// Read-only, bounded instrumentation for the native-input contract goldens.
// These observers never write game memory and are inert unless a trace is
// explicitly armed through sd.debug.
void ObserveNativeInputWindowMessage(
    HWND window,
    UINT message,
    WPARAM wparam,
    LPARAM lparam,
    bool forwarded_to_stock,
    std::string_view route_owner);
void ObserveNativeInputRefresh(
    std::uintptr_t input_state_address,
    std::string_view stage);
void ObserveNativeInputActorPostTick(
    std::uintptr_t gameplay_address,
    std::uintptr_t actor_address,
    const NativeInputActiveSpellObservation& active_spell);

bool StartNativeInputTrace(
    std::string_view label,
    std::string* error_message);
std::string SnapshotNativeInputTraceJson();
std::string StopNativeInputTraceJson();
bool IsNativeInputTraceActive();

}  // namespace sdmod
