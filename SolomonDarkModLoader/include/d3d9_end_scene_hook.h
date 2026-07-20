#pragma once

#include <cstdint>
#include <string>

struct IDirect3DDevice9;

namespace sdmod {

using D3d9FrameCallback = void(*)(IDirect3DDevice9* device);

bool InstallD3d9FrameHook(uintptr_t device_pointer_global, D3d9FrameCallback callback, std::string* error_message);
void SetD3d9PostFrameCallback(D3d9FrameCallback callback);
IDirect3DDevice9* GetLastSeenD3d9Device();
bool CaptureD3d9BackBufferBmp(
    const std::wstring& output_path,
    std::string* error_message = nullptr);
void RemoveD3d9FrameHook();

}  // namespace sdmod
