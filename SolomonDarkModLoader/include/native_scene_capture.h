#pragma once

#include <cstdint>
#include <string>
#include <string_view>

namespace sdmod {

struct NativeSceneCaptureStatus {
    bool requested = false;
    bool initialized = false;
    std::string state;
    std::string label;
    std::string output_path;
    std::string error_message;
    std::uint32_t draw_count = 0;
};

bool IsNativeSceneCaptureRequested();
bool InitializeNativeSceneCapture(std::string* error_message);
void ShutdownNativeSceneCapture();
bool QueueNativeSceneCapture(
    std::string_view label,
    std::string* error_message);
bool TryGetNativeSceneCaptureStatus(NativeSceneCaptureStatus* status);

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

}  // namespace sdmod
