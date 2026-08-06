#pragma once

#include <cstdint>
#include <string>
#include <string_view>

namespace sdmod {

struct NativeSceneCaptureStatus {
    bool requested = false;
    bool initialized = false;
    std::string state;
    std::string surface;
    std::string label;
    std::string output_path;
    std::string error_message;
    std::uint32_t draw_count = 0;
    std::uint32_t requested_frame_count = 0;
    std::uint32_t captured_frame_count = 0;
};

bool IsNativeSceneCaptureRequested();
bool InitializeNativeSceneCapture(std::string* error_message);
void ShutdownNativeSceneCapture();
bool QueueNativeSceneCapture(
    std::string_view label,
    std::string* error_message);
bool QueueNativeSceneCaptureSequence(
    std::string_view label,
    std::uint32_t frame_count,
    std::string* error_message);
bool TryGetNativeSceneCaptureStatus(NativeSceneCaptureStatus* status);
void NativeSceneCaptureObservePlayerFixedTick(
    std::uintptr_t actor_address,
    std::uint64_t simulation_tick);

void NativeSceneCaptureBeginFrame(void* region, const char* scene_kind);
void NativeSceneCaptureEndFrame(void* region);
void NativeSceneCaptureBeginSortedQueue(void* queue, int pass);
void NativeSceneCaptureEndSortedQueue(void* queue, int pass);
void NativeSceneCaptureBeginWorldObject(void* object);
void NativeSceneCaptureEndWorldObject(void* object);

void NativeSceneCapturePushCaller(std::uintptr_t caller_address);
void NativeSceneCapturePopCaller();
void NativeSceneCaptureBeginSpriteDraw(
    void* sprite,
    const char* draw_kind,
    float x,
    float y,
    const float* transform,
    std::uintptr_t caller_address);
void NativeSceneCaptureObserveTexturedQuad(
    const float* destination_vertices,
    const float* texture_vertices,
    std::uintptr_t caller_address);
void NativeSceneCaptureEndSpriteDraw();
void NativeSceneCaptureBeginExactText(
    std::string_view text,
    std::uintptr_t caller_address);
void NativeSceneCaptureEndExactText();

}  // namespace sdmod
