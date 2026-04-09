#include "d3d9_end_scene_hook.h"

#include "logger.h"
#include "memory_access.h"
#include "mod_loader.h"

#include <Windows.h>
#include <d3d9.h>

namespace sdmod {
namespace {

using EndSceneFn = HRESULT(STDMETHODCALLTYPE*)(IDirect3DDevice9* device);

constexpr size_t kEndSceneVtableIndex = 42;
constexpr DWORD kDeviceAcquireTimeoutMilliseconds = 5000;
constexpr DWORD kDeviceAcquirePollMilliseconds = 50;

D3d9FrameCallback g_callback = nullptr;
D3d9FrameCallback g_post_callback = nullptr;
D3d9FrameActionPump g_action_pump = nullptr;
EndSceneFn g_original_end_scene = nullptr;
void** g_end_scene_slot = nullptr;
IDirect3DDevice9* g_last_seen_device = nullptr;
bool g_hook_installed = false;

HRESULT STDMETHODCALLTYPE HookEndScene(IDirect3DDevice9* device) {
    g_last_seen_device = device;
    const auto result = g_original_end_scene != nullptr ? g_original_end_scene(device) : D3D_OK;
    if (g_action_pump != nullptr) {
        g_action_pump();
    }
    if (g_callback != nullptr) {
        g_callback(device);
    }
    if (g_post_callback != nullptr) {
        g_post_callback(device);
    }

    return result;
}

bool PatchHookSlot(void** slot, void* replacement, std::string* error_message) {
    if (slot == nullptr || replacement == nullptr) {
        if (error_message != nullptr) {
            *error_message = "D3D9 hook slot or replacement was null.";
        }
        return false;
    }

    DWORD old_protection = 0;
    if (!VirtualProtect(slot, sizeof(void*), PAGE_EXECUTE_READWRITE, &old_protection)) {
        if (error_message != nullptr) {
            *error_message = "VirtualProtect failed while patching the D3D9 EndScene slot.";
        }
        return false;
    }

    *slot = replacement;

    DWORD ignored = 0;
    VirtualProtect(slot, sizeof(void*), old_protection, &ignored);
    FlushInstructionCache(GetCurrentProcess(), slot, sizeof(void*));
    return true;
}

bool TryAcquireDevicePointer(uintptr_t device_pointer_global, IDirect3DDevice9** device, std::string* error_message) {
    if (device == nullptr) {
        if (error_message != nullptr) {
            *error_message = "D3D9 device destination was null.";
        }
        return false;
    }

    const auto resolved_global = ProcessMemory::Instance().ResolveGameAddressOrZero(device_pointer_global);
    if (resolved_global == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the configured D3D9 device pointer global.";
        }
        return false;
    }

    const auto deadline = GetTickCount64() + kDeviceAcquireTimeoutMilliseconds;
    while (GetTickCount64() < deadline) {
        std::uint32_t raw_device_pointer = 0;
        if (ProcessMemory::Instance().TryReadValue(resolved_global, &raw_device_pointer) && raw_device_pointer != 0) {
            *device = reinterpret_cast<IDirect3DDevice9*>(static_cast<uintptr_t>(raw_device_pointer));
            Log(
                "Debug UI overlay D3D9 hook: resolved live device pointer from " +
                HexString(device_pointer_global) + " -> " + HexString(raw_device_pointer));
            return true;
        }

        Sleep(kDeviceAcquirePollMilliseconds);
    }

    if (error_message != nullptr) {
        *error_message =
            "Timed out while waiting for the configured D3D9 device pointer global to become non-null.";
    }
    return false;
}

}  // namespace

bool InstallD3d9FrameHook(uintptr_t device_pointer_global, D3d9FrameCallback callback, std::string* error_message) {
    if (callback == nullptr) {
        if (error_message != nullptr) {
            *error_message = "D3D9 frame callback was null.";
        }
        return false;
    }

    if (g_hook_installed) {
        g_callback = callback;
        return true;
    }

    IDirect3DDevice9* device = nullptr;
    if (!TryAcquireDevicePointer(device_pointer_global, &device, error_message)) {
        return false;
    }

    auto** vtable = *reinterpret_cast<void***>(device);
    if (vtable == nullptr) {
        if (error_message != nullptr) {
            *error_message = "The live D3D9 device had a null vtable pointer.";
        }
        return false;
    }

    g_end_scene_slot = &vtable[kEndSceneVtableIndex];
    g_original_end_scene = reinterpret_cast<EndSceneFn>(*g_end_scene_slot);
    g_callback = callback;

    if (!PatchHookSlot(g_end_scene_slot, reinterpret_cast<void*>(&HookEndScene), error_message)) {
        g_callback = nullptr;
        g_original_end_scene = nullptr;
        g_end_scene_slot = nullptr;
        return false;
    }

    g_hook_installed = true;
    Log("Debug UI overlay D3D9 hook: EndScene slot patched on the live device.");
    return true;
}

void SetD3d9FrameActionPump(D3d9FrameActionPump pump) {
    g_action_pump = pump;
}

void SetD3d9PostFrameCallback(D3d9FrameCallback callback) {
    g_post_callback = callback;
}

IDirect3DDevice9* GetLastSeenD3d9Device() {
    return g_last_seen_device;
}

void RemoveD3d9FrameHook() {
    if (!g_hook_installed) {
        return;
    }

    if (g_end_scene_slot != nullptr && g_original_end_scene != nullptr) {
        PatchHookSlot(g_end_scene_slot, reinterpret_cast<void*>(g_original_end_scene), nullptr);
    }

    g_callback = nullptr;
    g_post_callback = nullptr;
    g_original_end_scene = nullptr;
    g_end_scene_slot = nullptr;
    g_last_seen_device = nullptr;
    g_hook_installed = false;
}

}  // namespace sdmod
