#include "lua_draw_internal.h"

#include <Windows.h>
#include <d3d9.h>
#include <objbase.h>
#include <wincodec.h>

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>
#include <string>
#include <vector>

#pragma comment(lib, "windowscodecs.lib")

namespace sdmod::detail {
namespace {

constexpr std::uint32_t kMaximumLuaDrawTextureDimension = 8192;
constexpr std::size_t kMaximumLuaDrawTextureBytes = 256 * 1024 * 1024;

std::string DescribeHresult(const char* operation, HRESULT result) {
    char buffer[32]{};
    std::snprintf(
        buffer,
        sizeof(buffer),
        "0x%08lX",
        static_cast<unsigned long>(result));
    return std::string(operation) + " failed with HRESULT " + buffer + ".";
}

template <typename Interface>
void ReleaseComObject(Interface** object) {
    if (object != nullptr && *object != nullptr) {
        (*object)->Release();
        *object = nullptr;
    }
}

}  // namespace

bool LoadLuaDrawTexture(
    IDirect3DDevice9* device,
    const std::filesystem::path& path,
    IDirect3DTexture9** texture,
    std::uint32_t* width,
    std::uint32_t* height,
    std::string* error_message) {
    if (texture != nullptr) {
        *texture = nullptr;
    }
    if (width != nullptr) {
        *width = 0;
    }
    if (height != nullptr) {
        *height = 0;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (device == nullptr ||
        texture == nullptr ||
        width == nullptr ||
        height == nullptr ||
        error_message == nullptr ||
        path.empty()) {
        return false;
    }

    const HRESULT apartment_result =
        CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    const bool uninitialize_apartment = SUCCEEDED(apartment_result);
    if (FAILED(apartment_result) &&
        apartment_result != RPC_E_CHANGED_MODE) {
        *error_message = DescribeHresult("CoInitializeEx", apartment_result);
        return false;
    }

    IWICImagingFactory* factory = nullptr;
    IWICBitmapDecoder* decoder = nullptr;
    IWICBitmapFrameDecode* frame = nullptr;
    IWICFormatConverter* converter = nullptr;
    auto Cleanup = [&]() {
        ReleaseComObject(&converter);
        ReleaseComObject(&frame);
        ReleaseComObject(&decoder);
        ReleaseComObject(&factory);
        if (uninitialize_apartment) {
            CoUninitialize();
        }
    };
    auto Fail = [&](const std::string& message) {
        Cleanup();
        *error_message = message;
        return false;
    };

    HRESULT result = CoCreateInstance(
        CLSID_WICImagingFactory,
        nullptr,
        CLSCTX_INPROC_SERVER,
        IID_PPV_ARGS(&factory));
    if (FAILED(result) || factory == nullptr) {
        return Fail(DescribeHresult("WIC factory creation", result));
    }
    result = factory->CreateDecoderFromFilename(
        path.c_str(),
        nullptr,
        GENERIC_READ,
        WICDecodeMetadataCacheOnLoad,
        &decoder);
    if (FAILED(result) || decoder == nullptr) {
        return Fail(
            DescribeHresult("WIC PNG decoder creation", result) +
            " path=" + path.string());
    }
    result = decoder->GetFrame(0, &frame);
    if (FAILED(result) || frame == nullptr) {
        return Fail(DescribeHresult("WIC frame decode", result));
    }

    UINT decoded_width = 0;
    UINT decoded_height = 0;
    result = frame->GetSize(&decoded_width, &decoded_height);
    if (FAILED(result) ||
        decoded_width == 0 ||
        decoded_height == 0 ||
        decoded_width > kMaximumLuaDrawTextureDimension ||
        decoded_height > kMaximumLuaDrawTextureDimension) {
        return Fail(
            FAILED(result)
                ? DescribeHresult("WIC frame size query", result)
                : "WIC image dimensions are empty or exceed the Lua draw bound.");
    }
    const std::size_t stride =
        static_cast<std::size_t>(decoded_width) * 4;
    if (stride > (std::numeric_limits<UINT>::max)() ||
        decoded_height > kMaximumLuaDrawTextureBytes / stride) {
        return Fail("WIC image byte size exceeds the Lua draw bound.");
    }
    const std::size_t pixel_bytes =
        stride * static_cast<std::size_t>(decoded_height);

    result = factory->CreateFormatConverter(&converter);
    if (FAILED(result) || converter == nullptr) {
        return Fail(DescribeHresult("WIC converter creation", result));
    }
    result = converter->Initialize(
        frame,
        GUID_WICPixelFormat32bppBGRA,
        WICBitmapDitherTypeNone,
        nullptr,
        0.0,
        WICBitmapPaletteTypeCustom);
    if (FAILED(result)) {
        return Fail(DescribeHresult("WIC BGRA conversion", result));
    }

    std::vector<std::uint8_t> pixels(pixel_bytes);
    result = converter->CopyPixels(
        nullptr,
        static_cast<UINT>(stride),
        static_cast<UINT>(pixel_bytes),
        pixels.data());
    if (FAILED(result)) {
        return Fail(DescribeHresult("WIC pixel copy", result));
    }

    IDirect3DTexture9* created_texture = nullptr;
    result = device->CreateTexture(
        decoded_width,
        decoded_height,
        1,
        0,
        D3DFMT_A8R8G8B8,
        D3DPOOL_MANAGED,
        &created_texture,
        nullptr);
    if (FAILED(result) || created_texture == nullptr) {
        return Fail(DescribeHresult("D3D9 texture creation", result));
    }
    D3DLOCKED_RECT locked{};
    result = created_texture->LockRect(0, &locked, nullptr, 0);
    if (FAILED(result)) {
        created_texture->Release();
        return Fail(DescribeHresult("D3D9 texture lock", result));
    }
    for (UINT row = 0; row < decoded_height; ++row) {
        std::memcpy(
            static_cast<std::uint8_t*>(locked.pBits) +
                static_cast<std::size_t>(row) * locked.Pitch,
            pixels.data() + static_cast<std::size_t>(row) * stride,
            stride);
    }
    created_texture->UnlockRect(0);

    Cleanup();
    *texture = created_texture;
    *width = decoded_width;
    *height = decoded_height;
    return true;
}

}  // namespace sdmod::detail
