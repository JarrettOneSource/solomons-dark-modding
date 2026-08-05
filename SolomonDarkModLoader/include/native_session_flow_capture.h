#pragma once

#include <cstdint>
#include <string>

namespace sdmod {

bool IsNativeSessionFlowCaptureRequested();
bool InitializeNativeSessionFlowCapture(std::string* error_message);
void ShutdownNativeSessionFlowCapture();

// These observers are inert unless SDMOD_NATIVE_SESSION_FLOW_CAPTURE_DIRECTORY
// is set. They expose ordering already traversed by stock code; they never
// request or alter a transition.
void NativeSessionFlowCaptureBeginSwitch(void* gameplay, int target_region);
void NativeSessionFlowCaptureEndSwitch(void* gameplay, int target_region);
void NativeSessionFlowCaptureObserveSwitchStep(
    const char* step,
    void* object = nullptr,
    int native_argument = -1);
void NativeSessionFlowCaptureObserveInputSeal();
void NativeSessionFlowCaptureObserveInputUnseal(const char* reason);
void NativeSessionFlowCaptureObserveSessionEvent(
    const char* step,
    void* object = nullptr,
    int native_argument = -1);

}  // namespace sdmod
