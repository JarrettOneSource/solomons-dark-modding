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
#include <utility>
#include <vector>

namespace sdmod::detail {
namespace {

constexpr wchar_t kCaptureDirectoryEnvironment[] =
    L"SDMOD_LOADING_SCREEN_CAPTURE_DIRECTORY";
constexpr wchar_t kLuaPipeEnvironment[] =
    L"SDMOD_LUA_EXEC_PIPE_NAME";

thread_local bool g_presenting_loading_frame = false;
std::atomic_bool g_presentation_failure_logged{false};

struct LoadingEvidenceSample {
    std::uint64_t elapsed_milliseconds = 0;
    std::string reference_capture;
    std::string semantic_json;
};

struct ProcessClientViewport {
    DWORD process_id = 0;
    std::uint32_t width = 0;
    std::uint32_t height = 0;
};

BOOL CALLBACK FindProcessClientViewport(
    HWND window,
    LPARAM parameter) {
    auto* target = reinterpret_cast<ProcessClientViewport*>(parameter);
    DWORD process_id = 0;
    GetWindowThreadProcessId(window, &process_id);
    if (process_id != target->process_id || !IsWindowVisible(window)) {
        return TRUE;
    }
    RECT client{};
    if (!GetClientRect(window, &client)) {
        return TRUE;
    }
    const auto width = client.right - client.left;
    const auto height = client.bottom - client.top;
    if (width <= 0 || height <= 0) {
        return TRUE;
    }
    target->width = static_cast<std::uint32_t>(width);
    target->height = static_cast<std::uint32_t>(height);
    return FALSE;
}

bool IsProcessClientPresentationViewport(
    const LoadingScreenRenderLayout& layout) {
    ProcessClientViewport viewport;
    viewport.process_id = GetCurrentProcessId();
    EnumWindows(
        &FindProcessClientViewport,
        reinterpret_cast<LPARAM>(&viewport));
    return viewport.width > 0 && viewport.height > 0 &&
        layout.viewport_width == viewport.width &&
        layout.viewport_height == viewport.height;
}

std::uint64_t g_loading_capture_sequence = 0;
std::uint64_t g_loading_capture_started_at = 0;
std::uint64_t g_loading_stable_started_at = 0;
std::size_t g_loading_stable_sample_count = 0;
bool g_loading_capture_settled = false;
std::string g_loading_stable_semantic;
std::vector<LoadingEvidenceSample> g_loading_capture_samples;

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

std::string SerializeLoadingLayout(
    const LoadingScreenSnapshot& snapshot,
    const LoadingScreenRenderLayout& layout,
    const std::wstring& instance) {
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

    return json.str();
}

std::string SerializeLoadingStructure(
    const LoadingScreenSnapshot& snapshot,
    const LoadingScreenRenderLayout& layout,
    const std::wstring& instance) {
    std::ostringstream json;
    json << std::fixed << std::setprecision(4)
         << "{\"instance\":\""
         << EscapeJson(NarrowSafeFileToken(instance))
         << "\",\"pid\":" << GetCurrentProcessId()
         << ",\"screen_id\":\"loading_"
         << EscapeJson(snapshot.stage_id)
         << "\",\"sequence\":" << snapshot.sequence
         << ",\"stage_id\":\"" << EscapeJson(snapshot.stage_id)
         << "\",\"progress\":" << snapshot.progress
         << ",\"viewport\":[" << layout.viewport_x << ','
         << layout.viewport_y << ',' << layout.viewport_width << ','
         << layout.viewport_height << "]"
         << ",\"source_crop\":[" << layout.crop_u0 << ','
         << layout.crop_v0 << ',' << layout.crop_u1 << ','
         << layout.crop_v1 << "]"
         << ",\"background_art_id\":\""
         << EscapeJson(layout.background_art_id)
         << "\",\"background_size\":[" << layout.background_width << ','
         << layout.background_height << "]"
         << ",\"progress_bar_visible\":"
         << (layout.progress_bar_visible ? "true" : "false")
         << ",\"label\":\"" << EscapeJson(layout.label)
         << "\",\"text_scale\":" << layout.text_scale << '}';
    return json.str();
}

bool WriteTextAtomically(
    const std::filesystem::path& output_path,
    std::string_view text,
    std::string* error_message) {
    const auto temporary_path = output_path.wstring() + L".tmp";
    std::ofstream output(
        std::filesystem::path(temporary_path),
        std::ios::binary | std::ios::trunc);
    if (!output) {
        *error_message = "could not open temporary JSON recording";
        return false;
    }
    output << text;
    output.close();
    if (!output) {
        *error_message = "could not write temporary JSON recording";
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

bool WriteLoadingCaptureJson(
    const std::filesystem::path& output_path,
    const std::wstring& instance,
    std::string* error_message) {
    std::ostringstream json;
    json << "{\n"
         << "  \"schema\": \"solomon-dark-native-loading-capture-v1\",\n"
         << "  \"header\": {\n"
         << "    \"instance\": \""
         << EscapeJson(NarrowSafeFileToken(instance)) << "\",\n"
         << "    \"pid\": " << GetCurrentProcessId() << ",\n"
         << "    \"capture_method\": \"live D3D9 render geometry and backbuffer capture\"\n"
         << "  },\n"
         << "  \"samples\": [\n";
    for (std::size_t index = 0;
         index < g_loading_capture_samples.size();
         ++index) {
        const auto& sample = g_loading_capture_samples[index];
        json << "    {\"elapsed_milliseconds\":"
             << sample.elapsed_milliseconds
             << ",\"reference_capture\":\""
             << EscapeJson(sample.reference_capture)
             << "\",\"layout\":" << sample.semantic_json << '}';
        if (index + 1 != g_loading_capture_samples.size()) {
            json << ',';
        }
        json << '\n';
    }
    const auto stable_span = g_loading_capture_samples.empty()
        ? 0
        : g_loading_capture_samples.back().elapsed_milliseconds -
            g_loading_stable_started_at;
    json << "  ],\n"
         << "  \"settlement\": {\n"
         << "    \"criterion\": \"at least 40 consecutive samples spanning at least 2 seconds with byte-identical structural payloads; animated geometry is measured by the importer\",\n"
         << "    \"settled\": "
         << (g_loading_capture_settled ? "true" : "false") << ",\n"
         << "    \"settle_latency_milliseconds\": ";
    if (g_loading_capture_settled && !g_loading_capture_samples.empty()) {
        json << g_loading_capture_samples.back().elapsed_milliseconds;
    } else {
        json << "null";
    }
    json << ",\n"
         << "    \"stable_span_milliseconds\": " << stable_span << ",\n"
         << "    \"consecutive_structural_samples\": "
         << g_loading_stable_sample_count << ",\n"
         << "    \"total_semantic_samples\": "
         << g_loading_capture_samples.size() << "\n"
         << "  }\n"
         << "}\n";
    return WriteTextAtomically(
        output_path,
        json.str(),
        error_message);
}

void CaptureLoadingScreenEvidenceFrameInternal(
    const LoadingScreenSnapshot& snapshot,
    const LoadingScreenRenderLayout& layout) {
    const auto directory_text =
        ReadEnvironmentVariable(
            kCaptureDirectoryEnvironment);
    if (directory_text.empty()) {
        return;
    }
    if (!IsProcessClientPresentationViewport(layout)) {
        return;
    }

    if (g_loading_capture_sequence != snapshot.sequence) {
        g_loading_capture_sequence = snapshot.sequence;
        g_loading_capture_started_at = GetTickCount64();
        g_loading_stable_started_at = 0;
        g_loading_stable_sample_count = 0;
        g_loading_capture_settled = false;
        g_loading_stable_semantic.clear();
        g_loading_capture_samples.clear();
    }
    if (g_loading_capture_settled) {
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
    LoadingEvidenceSample sample;
    sample.elapsed_milliseconds =
        GetTickCount64() - g_loading_capture_started_at;
    sample.semantic_json = SerializeLoadingLayout(
        snapshot,
        layout,
        instance);
    const auto structure_json = SerializeLoadingStructure(
        snapshot,
        layout,
        instance);
    const auto semantic_changed =
        structure_json != g_loading_stable_semantic;
    if (semantic_changed) {
        g_loading_stable_semantic = structure_json;
        g_loading_stable_sample_count = 1;
        g_loading_stable_started_at = sample.elapsed_milliseconds;
        constexpr wchar_t reference_name[] =
            L"loading-screen-settled-candidate.bmp";
        const auto reference_path = directory / reference_name;
        std::string capture_error;
        if (!CaptureD3d9BackBufferBmp(
                reference_path.wstring(),
                &capture_error)) {
            Log(
                "Loading screen evidence capture failed. path=" +
                reference_path.string() +
                " error=" + capture_error);
            return;
        }
        sample.reference_capture = "loading-screen-settled-candidate.bmp";
    } else {
        ++g_loading_stable_sample_count;
    }
    const auto stable_span =
        sample.elapsed_milliseconds - g_loading_stable_started_at;
    g_loading_capture_settled =
        g_loading_stable_sample_count >= 40 && stable_span >= 2000;
    g_loading_capture_samples.push_back(std::move(sample));

    const auto recording_path = directory / "native-loading-layout.json";
    std::string recording_error;
    if (!WriteLoadingCaptureJson(
            recording_path,
            instance,
            &recording_error)) {
        Log(
            "Loading screen layout recording failed. path=" +
            recording_path.string() +
            " error=" + recording_error);
        return;
    }

    if (semantic_changed || g_loading_capture_settled) {
        Log(
            "Loading screen evidence sampled. sequence=" +
            std::to_string(snapshot.sequence) +
            " stage=" + snapshot.stage_id +
            " samples=" +
            std::to_string(g_loading_capture_samples.size()) +
            " stable=" +
            std::to_string(g_loading_stable_sample_count) +
            " settled=" +
            (g_loading_capture_settled ? "true" : "false") +
            " recording=" + recording_path.string());
    }
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
