#include "d3d9_end_scene_hook.h"

#include "logger.h"
#include "lua_engine.h"
#include "memory_access.h"
#include "mod_loader.h"

#include <Windows.h>
#include <d3d9.h>

#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <system_error>
#include <vector>

namespace sdmod {
namespace {

using EndSceneFn = HRESULT(STDMETHODCALLTYPE*)(IDirect3DDevice9* device);

constexpr size_t kEndSceneVtableIndex = 42;
constexpr DWORD kDeviceAcquireTimeoutMilliseconds = 5000;
constexpr DWORD kDeviceAcquirePollMilliseconds = 50;

D3d9FrameCallback g_callback = nullptr;
D3d9FrameCallback g_post_callback = nullptr;
EndSceneFn g_original_end_scene = nullptr;
void** g_end_scene_slot = nullptr;
IDirect3DDevice9* g_last_seen_device = nullptr;
bool g_hook_installed = false;

std::string D3d9CaptureHresult(const char* operation, HRESULT result) {
    return std::string(operation) + " failed with HRESULT " +
           HexString(static_cast<uintptr_t>(static_cast<std::uint32_t>(result)));
}

bool CopyD3d9PixelToBgr(
    D3DFORMAT format,
    const std::uint8_t* source,
    std::uint8_t* destination) {
    if (source == nullptr || destination == nullptr) {
        return false;
    }

    switch (format) {
    case D3DFMT_A8R8G8B8:
    case D3DFMT_X8R8G8B8:
        destination[0] = source[0];
        destination[1] = source[1];
        destination[2] = source[2];
        return true;
    case D3DFMT_A8B8G8R8:
    case D3DFMT_X8B8G8R8:
        destination[0] = source[2];
        destination[1] = source[1];
        destination[2] = source[0];
        return true;
    case D3DFMT_A2R10G10B10: {
        std::uint32_t pixel = 0;
        std::memcpy(&pixel, source, sizeof(pixel));
        destination[0] = static_cast<std::uint8_t>((pixel & 0x3FFu) * 255u / 1023u);
        destination[1] = static_cast<std::uint8_t>(((pixel >> 10u) & 0x3FFu) * 255u / 1023u);
        destination[2] = static_cast<std::uint8_t>(((pixel >> 20u) & 0x3FFu) * 255u / 1023u);
        return true;
    }
    case D3DFMT_A2B10G10R10: {
        std::uint32_t pixel = 0;
        std::memcpy(&pixel, source, sizeof(pixel));
        destination[0] = static_cast<std::uint8_t>(((pixel >> 20u) & 0x3FFu) * 255u / 1023u);
        destination[1] = static_cast<std::uint8_t>(((pixel >> 10u) & 0x3FFu) * 255u / 1023u);
        destination[2] = static_cast<std::uint8_t>((pixel & 0x3FFu) * 255u / 1023u);
        return true;
    }
    case D3DFMT_R5G6B5: {
        const auto pixel = *reinterpret_cast<const std::uint16_t*>(source);
        destination[0] = static_cast<std::uint8_t>((pixel & 0x1Fu) * 255u / 31u);
        destination[1] = static_cast<std::uint8_t>(((pixel >> 5u) & 0x3Fu) * 255u / 63u);
        destination[2] = static_cast<std::uint8_t>(((pixel >> 11u) & 0x1Fu) * 255u / 31u);
        return true;
    }
    case D3DFMT_A1R5G5B5:
    case D3DFMT_X1R5G5B5: {
        const auto pixel = *reinterpret_cast<const std::uint16_t*>(source);
        destination[0] = static_cast<std::uint8_t>((pixel & 0x1Fu) * 255u / 31u);
        destination[1] = static_cast<std::uint8_t>(((pixel >> 5u) & 0x1Fu) * 255u / 31u);
        destination[2] = static_cast<std::uint8_t>(((pixel >> 10u) & 0x1Fu) * 255u / 31u);
        return true;
    }
    default:
        return false;
    }
}

std::size_t D3d9CaptureBytesPerPixel(D3DFORMAT format) {
    switch (format) {
    case D3DFMT_A8R8G8B8:
    case D3DFMT_X8R8G8B8:
    case D3DFMT_A8B8G8R8:
    case D3DFMT_X8B8G8R8:
    case D3DFMT_A2R10G10B10:
    case D3DFMT_A2B10G10R10:
        return 4;
    case D3DFMT_R5G6B5:
    case D3DFMT_A1R5G5B5:
    case D3DFMT_X1R5G5B5:
        return 2;
    default:
        return 0;
    }
}

HRESULT STDMETHODCALLTYPE HookEndScene(IDirect3DDevice9* device) {
    g_last_seen_device = device;
    lua_exec_diag::g_last_endscene_ms.store(
        static_cast<std::uint64_t>(GetTickCount64()),
        std::memory_order_release);
    lua_exec_diag::g_endscene_generation.fetch_add(
        1,
        std::memory_order_release);
    const auto result = g_original_end_scene != nullptr ? g_original_end_scene(device) : D3D_OK;
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

void SetD3d9PostFrameCallback(D3d9FrameCallback callback) {
    g_post_callback = callback;
}

IDirect3DDevice9* GetLastSeenD3d9Device() {
    return g_last_seen_device;
}

bool CaptureD3d9BackBufferBmp(
    const std::wstring& output_path,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (output_path.empty()) {
        if (error_message != nullptr) {
            *error_message = "Backbuffer capture output path was empty.";
        }
        return false;
    }

    auto* device = GetLastSeenD3d9Device();
    if (device == nullptr) {
        if (error_message != nullptr) {
            *error_message = "No D3D9 device has reached EndScene yet.";
        }
        return false;
    }

    IDirect3DSurface9* back_buffer = nullptr;
    IDirect3DSurface9* resolved_surface = nullptr;
    IDirect3DSurface9* system_surface = nullptr;
    bool system_surface_locked = false;
    D3DLOCKED_RECT locked{};
    auto ReleaseSurfaces = [&]() {
        if (system_surface_locked && system_surface != nullptr) {
            system_surface->UnlockRect();
            system_surface_locked = false;
        }
        if (system_surface != nullptr) {
            system_surface->Release();
            system_surface = nullptr;
        }
        if (resolved_surface != nullptr) {
            resolved_surface->Release();
            resolved_surface = nullptr;
        }
        if (back_buffer != nullptr) {
            back_buffer->Release();
            back_buffer = nullptr;
        }
    };
    auto Fail = [&](const std::string& message) {
        ReleaseSurfaces();
        if (error_message != nullptr) {
            *error_message = message;
        }
        return false;
    };

    HRESULT result = device->GetBackBuffer(
        0,
        0,
        D3DBACKBUFFER_TYPE_MONO,
        &back_buffer);
    if (FAILED(result) || back_buffer == nullptr) {
        return Fail(D3d9CaptureHresult("IDirect3DDevice9::GetBackBuffer", result));
    }

    D3DSURFACE_DESC description{};
    result = back_buffer->GetDesc(&description);
    if (FAILED(result) || description.Width == 0 || description.Height == 0) {
        return Fail(D3d9CaptureHresult("IDirect3DSurface9::GetDesc", result));
    }
    const auto bytes_per_pixel = D3d9CaptureBytesPerPixel(description.Format);
    if (bytes_per_pixel == 0) {
        return Fail(
            "Backbuffer capture does not support D3D format " +
            std::to_string(static_cast<int>(description.Format)) + ".");
    }

    IDirect3DSurface9* capture_source = back_buffer;
    if (description.MultiSampleType != D3DMULTISAMPLE_NONE) {
        result = device->CreateRenderTarget(
            description.Width,
            description.Height,
            description.Format,
            D3DMULTISAMPLE_NONE,
            0,
            FALSE,
            &resolved_surface,
            nullptr);
        if (FAILED(result) || resolved_surface == nullptr) {
            return Fail(D3d9CaptureHresult("IDirect3DDevice9::CreateRenderTarget", result));
        }
        result = device->StretchRect(
            back_buffer,
            nullptr,
            resolved_surface,
            nullptr,
            D3DTEXF_NONE);
        if (FAILED(result)) {
            return Fail(D3d9CaptureHresult("IDirect3DDevice9::StretchRect", result));
        }
        capture_source = resolved_surface;
    }

    result = device->CreateOffscreenPlainSurface(
        description.Width,
        description.Height,
        description.Format,
        D3DPOOL_SYSTEMMEM,
        &system_surface,
        nullptr);
    if (FAILED(result) || system_surface == nullptr) {
        return Fail(
            D3d9CaptureHresult("IDirect3DDevice9::CreateOffscreenPlainSurface", result));
    }
    result = device->GetRenderTargetData(capture_source, system_surface);
    if (FAILED(result)) {
        return Fail(D3d9CaptureHresult("IDirect3DDevice9::GetRenderTargetData", result));
    }
    result = system_surface->LockRect(&locked, nullptr, D3DLOCK_READONLY);
    if (FAILED(result) || locked.pBits == nullptr || locked.Pitch <= 0) {
        return Fail(D3d9CaptureHresult("IDirect3DSurface9::LockRect", result));
    }
    system_surface_locked = true;

    const std::size_t bmp_row_bytes =
        (static_cast<std::size_t>(description.Width) * 3u + 3u) & ~3u;
    const std::size_t pixel_bytes =
        bmp_row_bytes * static_cast<std::size_t>(description.Height);
    std::vector<std::uint8_t> pixels(pixel_bytes, 0);
    const auto* source_base = static_cast<const std::uint8_t*>(locked.pBits);
    for (std::uint32_t output_y = 0; output_y < description.Height; ++output_y) {
        const auto source_y = description.Height - 1u - output_y;
        const auto* source_row =
            source_base + static_cast<std::size_t>(source_y) * locked.Pitch;
        auto* output_row = pixels.data() + static_cast<std::size_t>(output_y) * bmp_row_bytes;
        for (std::uint32_t x = 0; x < description.Width; ++x) {
            if (!CopyD3d9PixelToBgr(
                    description.Format,
                    source_row + static_cast<std::size_t>(x) * bytes_per_pixel,
                    output_row + static_cast<std::size_t>(x) * 3u)) {
                return Fail("Backbuffer pixel conversion failed.");
            }
        }
    }
    system_surface->UnlockRect();
    system_surface_locked = false;

    BITMAPFILEHEADER file_header{};
    BITMAPINFOHEADER info_header{};
    file_header.bfType = 0x4D42u;
    file_header.bfOffBits = sizeof(BITMAPFILEHEADER) + sizeof(BITMAPINFOHEADER);
    file_header.bfSize =
        file_header.bfOffBits + static_cast<DWORD>(pixels.size());
    info_header.biSize = sizeof(BITMAPINFOHEADER);
    info_header.biWidth = static_cast<LONG>(description.Width);
    info_header.biHeight = static_cast<LONG>(description.Height);
    info_header.biPlanes = 1;
    info_header.biBitCount = 24;
    info_header.biCompression = BI_RGB;
    info_header.biSizeImage = static_cast<DWORD>(pixels.size());

    const std::filesystem::path path(output_path);
    std::error_code directory_error;
    if (!path.parent_path().empty()) {
        std::filesystem::create_directories(path.parent_path(), directory_error);
    }
    if (directory_error) {
        return Fail(
            "Could not create backbuffer capture directory: " +
            directory_error.message());
    }

    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output) {
        return Fail("Could not open the backbuffer capture output file.");
    }
    output.write(
        reinterpret_cast<const char*>(&file_header),
        sizeof(file_header));
    output.write(
        reinterpret_cast<const char*>(&info_header),
        sizeof(info_header));
    output.write(
        reinterpret_cast<const char*>(pixels.data()),
        static_cast<std::streamsize>(pixels.size()));
    output.flush();
    const bool write_succeeded = output.good();
    output.close();
    ReleaseSurfaces();
    if (!write_succeeded) {
        if (error_message != nullptr) {
            *error_message = "Backbuffer capture file write failed.";
        }
        return false;
    }

    Log(
        "D3D9 backbuffer captured. path=" + path.string() +
        " width=" + std::to_string(description.Width) +
        " height=" + std::to_string(description.Height) +
        " format=" + std::to_string(static_cast<int>(description.Format)));
    return true;
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
