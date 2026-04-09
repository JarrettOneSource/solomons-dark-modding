#pragma once

#include <cstdint>
#include <string>

struct IDirect3DDevice9;

namespace sdmod {

using D3d9FrameCallback = void(*)(IDirect3DDevice9* device);
using D3d9FrameActionPump = void(*)();

bool InstallD3d9FrameHook(uintptr_t device_pointer_global, D3d9FrameCallback callback, std::string* error_message);
void SetD3d9FrameActionPump(D3d9FrameActionPump pump);
void SetD3d9PostFrameCallback(D3d9FrameCallback callback);
IDirect3DDevice9* GetLastSeenD3d9Device();
void RemoveD3d9FrameHook();

}  // namespace sdmod
