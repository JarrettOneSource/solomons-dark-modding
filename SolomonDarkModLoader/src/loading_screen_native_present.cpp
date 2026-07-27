#include "loading_screen_internal.h"

#include "d3d9_end_scene_hook.h"
#include "loading_screen.h"
#include "logger.h"
#include "mod_loader.h"

#include <Windows.h>
#include <d3d9.h>

#include <atomic>
#include <cstdint>
#include <filesystem>
#include <string>

namespace sdmod::detail {
namespace {

constexpr wchar_t kCaptureDirectoryEnvironment[] =
    L"SDMOD_LOADING_SCREEN_CAPTURE_DIRECTORY";
constexpr wchar_t kLuaPipeEnvironment[] =
    L"SDMOD_LUA_EXEC_PIPE_NAME";

thread_local bool g_presenting_loading_frame = false;
std::atomic_bool g_presentation_failure_logged{false};
std::uint64_t g_captured_sequence = 0;
LoadingScreenStage g_captured_stage =
    LoadingScreenStage::PreparingBoneyard;

std::wstring ReadEnvironmentVariable(const wchar_t* name) {
    const DWORD required =
        GetEnvironmentVariableW(name, nullptr, 0);
    if (required == 0) {
        return {};
    }
    std::wstring value(required, L'\0');
    const DWORD written =
        GetEnvironmentVariableW(
            name,
            value.data(),
            required);
    if (written == 0 || written >= required) {
        return {};
    }
    value.resize(written);
    return value;
}

std::wstring SafeFileToken(std::wstring value) {
    for (auto& ch : value) {
        const bool safe =
            (ch >= L'a' && ch <= L'z') ||
            (ch >= L'A' && ch <= L'Z') ||
            (ch >= L'0' && ch <= L'9') ||
            ch == L'-' ||
            ch == L'_';
        if (!safe) {
            ch = L'_';
        }
    }
    return value;
}

void CaptureLoadingScreenEvidenceFrameInternal(
    const LoadingScreenSnapshot& snapshot) {
    const auto directory_text =
        ReadEnvironmentVariable(
            kCaptureDirectoryEnvironment);
    if (directory_text.empty() ||
        (g_captured_sequence == snapshot.sequence &&
         g_captured_stage == snapshot.stage)) {
        return;
    }

    std::error_code directory_error;
    const std::filesystem::path directory(directory_text);
    std::filesystem::create_directories(
        directory,
        directory_error);
    if (directory_error) {
        Log(
            "Loading screen evidence directory unavailable. path=" +
            directory.string() +
            " error=" + directory_error.message());
        return;
    }

    auto instance =
        SafeFileToken(
            ReadEnvironmentVariable(kLuaPipeEnvironment));
    if (instance.empty()) {
        instance =
            L"pid-" +
            std::to_wstring(GetCurrentProcessId());
    }
    const auto output_path =
        directory /
        (instance +
         L"-sequence-" +
         std::to_wstring(snapshot.sequence) +
         L"-" +
         std::wstring(
             snapshot.stage_id.begin(),
             snapshot.stage_id.end()) +
         L".bmp");
    std::string capture_error;
    if (!CaptureD3d9BackBufferBmp(
            output_path.wstring(),
            &capture_error)) {
        Log(
            "Loading screen evidence capture failed. path=" +
            output_path.string() +
            " error=" + capture_error);
        return;
    }

    g_captured_sequence = snapshot.sequence;
    g_captured_stage = snapshot.stage;
    Log(
        "Loading screen evidence captured. sequence=" +
        std::to_string(snapshot.sequence) +
        " stage=" + snapshot.stage_id +
        " path=" + output_path.string());
}

void LogPresentationFailure(
    const char* operation,
    HRESULT result) {
    if (g_presentation_failure_logged.exchange(true)) {
        return;
    }
    Log(
        "Loading screen native-stage presentation failed. operation=" +
        std::string(operation) +
        " hresult=" +
        HexString(static_cast<std::uint32_t>(result)));
}

}  // namespace

void CaptureLoadingScreenEvidenceFrame(
    const LoadingScreenSnapshot& snapshot) {
    CaptureLoadingScreenEvidenceFrameInternal(snapshot);
}

void PresentLoadingScreenFrame() {
    const auto snapshot = GetLoadingScreenSnapshot();
    const auto now_ms =
        static_cast<std::uint64_t>(GetTickCount64());
    if (!snapshot.active ||
        now_ms < snapshot.started_ms ||
        now_ms - snapshot.started_ms <
            kLoadingScreenPresentationDelayMs ||
        g_presenting_loading_frame) {
        return;
    }

    auto* device = GetLastSeenD3d9Device();
    if (device == nullptr) {
        return;
    }

    g_presenting_loading_frame = true;
    const HRESULT begin_result = device->BeginScene();
    if (FAILED(begin_result)) {
        g_presenting_loading_frame = false;
        LogPresentationFailure("BeginScene", begin_result);
        return;
    }

    const HRESULT end_result = device->EndScene();
    if (FAILED(end_result)) {
        g_presenting_loading_frame = false;
        LogPresentationFailure("EndScene", end_result);
        return;
    }

    CaptureLoadingScreenEvidenceFrame(snapshot);
    const HRESULT present_result =
        device->Present(nullptr, nullptr, nullptr, nullptr);
    g_presenting_loading_frame = false;
    if (FAILED(present_result)) {
        LogPresentationFailure("Present", present_result);
        return;
    }

    g_presentation_failure_logged.store(false);
    Log(
        "Loading screen native-stage frame presented. sequence=" +
        std::to_string(snapshot.sequence) +
        " stage=" + snapshot.stage_id +
        " progress=" + std::to_string(snapshot.progress));
}

}  // namespace sdmod::detail
