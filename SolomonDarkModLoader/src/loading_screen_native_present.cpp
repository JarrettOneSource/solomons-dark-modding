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
#include <fstream>
#include <iomanip>
#include <sstream>
#include <string>
#include <string_view>

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

std::string NarrowSafeFileToken(const std::wstring& value) {
    std::string narrowed;
    narrowed.reserve(value.size());
    for (const wchar_t ch : value) {
        narrowed.push_back(
            ch >= 0 && ch <= 0x7f
                ? static_cast<char>(ch)
                : '_');
    }
    return narrowed;
}

std::string EscapeJson(std::string_view value) {
    std::string escaped;
    escaped.reserve(value.size());
    for (const unsigned char ch : value) {
        switch (ch) {
        case '\\':
            escaped += "\\\\";
            break;
        case '"':
            escaped += "\\\"";
            break;
        case '\n':
            escaped += "\\n";
            break;
        case '\r':
            escaped += "\\r";
            break;
        case '\t':
            escaped += "\\t";
            break;
        default:
            if (ch >= 0x20) {
                escaped.push_back(static_cast<char>(ch));
            }
            break;
        }
    }
    return escaped;
}

void WriteRect(
    std::ostringstream* json,
    const LoadingScreenRect& rect) {
    *json << '[' << rect.left << ',' << rect.top << ','
          << rect.right << ',' << rect.bottom << ']';
}

bool WriteLoadingLayoutSidecar(
    const std::filesystem::path& output_path,
    const LoadingScreenSnapshot& snapshot,
    const LoadingScreenRenderLayout& layout,
    const std::wstring& instance,
    std::string* error_message) {
    std::ostringstream json;
    json << std::fixed << std::setprecision(4);
    json << "{\n"
         << "  \"schema\": \"native-loading-layout/v1\",\n"
         << "  \"header\": {\n"
         << "    \"instance\": \""
         << EscapeJson(NarrowSafeFileToken(instance))
         << "\",\n"
         << "    \"pid\": " << GetCurrentProcessId() << ",\n"
         << "    \"capture_method\": \"live D3D9 render geometry and backbuffer capture\"\n"
         << "  },\n"
         << "  \"screen_id\": \"loading_"
         << EscapeJson(snapshot.stage_id) << "\",\n"
         << "  \"sequence\": " << snapshot.sequence << ",\n"
         << "  \"stage_id\": \""
         << EscapeJson(snapshot.stage_id) << "\",\n"
         << "  \"progress\": " << snapshot.progress << ",\n"
         << "  \"viewport\": [" << layout.viewport_x << ','
         << layout.viewport_y << ',' << layout.viewport_width
         << ',' << layout.viewport_height << "],\n"
         << "  \"source_crop\": [" << layout.crop_u0 << ','
         << layout.crop_v0 << ',' << layout.crop_u1 << ','
         << layout.crop_v1 << "],\n"
         << "  \"elements\": [\n"
         << "    {\"id\":\"background\",\"kind\":\"art\",\"art_id\":\""
         << EscapeJson(layout.background_art_id) << "\",\"rect\":";
    WriteRect(&json, layout.background);
    json << ",\"source_size\":[" << layout.background_width << ','
         << layout.background_height << "]},\n"
         << "    {\"id\":\"bottom_scrim\",\"kind\":\"gradient_scrim\",\"rect\":";
    WriteRect(&json, layout.bottom_scrim);
    json << ",\"color_top\":\"#00000000\",\"color_bottom\":\"#B3000000\"}";
    if (layout.progress_bar_visible) {
        json << ",\n    {\"id\":\"progress_border\",\"kind\":\"progress_border\",\"rect\":";
        WriteRect(&json, layout.progress_border);
        json << ",\"color\":\"#E669522A\"},\n"
             << "    {\"id\":\"progress_track\",\"kind\":\"progress_track\",\"rect\":";
        WriteRect(&json, layout.progress_track);
        json << ",\"color\":\"#EB14110D\"},\n"
             << "    {\"id\":\"progress_fill\",\"kind\":\"progress_fill\",\"rect\":";
        WriteRect(&json, layout.progress_fill);
        json << ",\"color\":\"#FFCAA14D\"}";
    }
    json << ",\n    {\"id\":\"loading_label\",\"kind\":\"text\",\"text\":\""
         << EscapeJson(layout.label) << "\",\"rect\":";
    WriteRect(&json, layout.label_rect);
    json << ",\"font\":\"Segoe UI\",\"font_height\":-24,\"font_weight\":600,\"scale\":"
         << layout.text_scale << ",\"color\":\"#FFF2E5C7\"}\n"
         << "  ]\n"
         << "}\n";

    const auto temporary_path = output_path.wstring() + L".tmp";
    std::ofstream output(
        std::filesystem::path(temporary_path),
        std::ios::binary | std::ios::trunc);
    if (!output) {
        *error_message = "could not open JSON sidecar";
        return false;
    }
    output << json.str();
    output.close();
    if (!output) {
        *error_message = "could not write JSON sidecar";
        std::error_code ignored;
        std::filesystem::remove(temporary_path, ignored);
        return false;
    }
    std::error_code replace_error;
    std::filesystem::remove(output_path, replace_error);
    replace_error.clear();
    std::filesystem::rename(
        temporary_path,
        output_path,
        replace_error);
    if (replace_error) {
        *error_message = replace_error.message();
        std::error_code ignored;
        std::filesystem::remove(temporary_path, ignored);
        return false;
    }
    return true;
}

void CaptureLoadingScreenEvidenceFrameInternal(
    const LoadingScreenSnapshot& snapshot,
    const LoadingScreenRenderLayout& layout) {
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

    auto sidecar_path = output_path;
    sidecar_path.replace_extension(L".json");
    std::string sidecar_error;
    if (!WriteLoadingLayoutSidecar(
            sidecar_path,
            snapshot,
            layout,
            instance,
            &sidecar_error)) {
        Log(
            "Loading screen layout sidecar failed. path=" +
            sidecar_path.string() +
            " error=" + sidecar_error);
        return;
    }

    g_captured_sequence = snapshot.sequence;
    g_captured_stage = snapshot.stage;
    Log(
        "Loading screen evidence captured. sequence=" +
        std::to_string(snapshot.sequence) +
        " stage=" + snapshot.stage_id +
        " path=" + output_path.string() +
        " layout=" + sidecar_path.string());
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
    const LoadingScreenSnapshot& snapshot,
    const LoadingScreenRenderLayout* layout) {
    LoadingScreenRenderLayout current_layout;
    if (layout == nullptr) {
        if (!TryGetLastLoadingScreenRenderLayout(
                &current_layout) ||
            current_layout.sequence != snapshot.sequence ||
            current_layout.stage_id != snapshot.stage_id) {
            return;
        }
        layout = &current_layout;
    }
    CaptureLoadingScreenEvidenceFrameInternal(
        snapshot,
        *layout);
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
