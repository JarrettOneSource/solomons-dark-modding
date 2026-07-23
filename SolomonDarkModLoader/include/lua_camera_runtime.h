#pragma once

#include <string>
#include <string_view>
#include <vector>

namespace sdmod {

struct LuaCameraSnapshot {
    bool runtime_available = false;
    bool scene_available = false;
    bool focus_active = false;
    bool caller_owns_focus = false;
    float origin_x = 0.0f;
    float origin_y = 0.0f;
    float width = 0.0f;
    float height = 0.0f;
    float center_x = 0.0f;
    float center_y = 0.0f;
    float scale = 0.0f;
    float shake_magnitude = 0.0f;
    float shake_accumulator = 0.0f;
    float focus_x = 0.0f;
    float focus_y = 0.0f;
};

bool InitializeLuaCameraRuntime(std::string* error_message);
void ShutdownLuaCameraRuntime();
bool IsLuaCameraRuntimeAvailable();
void AppendLuaCameraCapabilities(std::vector<std::string>* capabilities);

bool TryGetLuaCameraSnapshot(
    std::string_view caller_mod_id,
    LuaCameraSnapshot* snapshot);
bool SetLocalCameraFocus(
    std::string_view owner_id,
    float world_x,
    float world_y,
    std::string* error_message);
bool ClearLocalCameraFocus(std::string_view owner_id);
bool SetLuaCameraFocus(
    std::string_view mod_id,
    float world_x,
    float world_y,
    std::string* error_message);
bool ClearLuaCameraFocus(std::string_view mod_id);
bool ApplyLuaCameraShake(float intensity, std::string* error_message);

}  // namespace sdmod
