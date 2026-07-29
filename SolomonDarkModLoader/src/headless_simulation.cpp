#include "headless_simulation.h"

#include "binary_layout.h"
#include "logger.h"
#include "memory_access.h"

#include <Windows.h>

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <string>

namespace sdmod {
namespace {

constexpr char kHeadlessEnvironmentVariable[] = "SDMOD_HEADLESS";
constexpr int kInitialSimulationBatchSize = 64;
constexpr int kMinimumSimulationBatchSize = 1;
constexpr int kMaximumSimulationBatchSize = 262144;
constexpr double kTargetBatchDurationMilliseconds = 250.0;
constexpr double kMinimumMeasuredDurationMilliseconds = 0.01;
constexpr double kThroughputReportIntervalSeconds = 2.0;

using TimeGetTimeFn = DWORD(WINAPI*)();

struct HeadlessSimulationState {
    bool initialized = false;
    bool enabled = false;
    bool runtime_failure_logged = false;
    bool original_fields_captured = false;
    bool timing_sample_active = false;
    bool window_hidden_logged = false;
    bool rendering_suppressed = false;
    std::size_t scheduler_baseline_offset = 0;
    std::size_t scheduler_tick_offset = 0;
    std::size_t render_skip_offset = 0;
    std::size_t simulation_batch_offset = 0;
    int simulation_batch_size = kInitialSimulationBatchSize;
    int prepared_batch_size = 0;
    int original_simulation_batch_size = 1;
    int original_render_skip_count = 0;
    uintptr_t last_app_address = 0;
    HWND game_window = nullptr;
    TimeGetTimeFn time_get_time = nullptr;
    LARGE_INTEGER performance_frequency = {};
    LARGE_INTEGER batch_started = {};
    LARGE_INTEGER report_started = {};
    std::uint64_t reported_simulation_steps = 0;
} g_headless_simulation;

bool IsHeadlessRequested() {
    char value[2] = {};
    return GetEnvironmentVariableA(
               kHeadlessEnvironmentVariable,
               value,
               static_cast<DWORD>(sizeof(value))) == 1 &&
           value[0] == '1';
}

bool TryReadFieldOffset(
    const char* key,
    std::size_t* offset) {
    uintptr_t configured_offset = 0;
    if (offset == nullptr ||
        !TryGetBinaryLayoutNumericValue(
            "headless.fields",
            key,
            &configured_offset) ||
        configured_offset == 0 ||
        configured_offset > 0xffff) {
        return false;
    }

    *offset = static_cast<std::size_t>(configured_offset);
    return true;
}

TimeGetTimeFn ResolveTimeGetTime() {
    auto winmm = GetModuleHandleW(L"winmm.dll");
    if (winmm == nullptr) {
        winmm = LoadLibraryW(L"winmm.dll");
    }
    if (winmm == nullptr) {
        return nullptr;
    }

    return reinterpret_cast<TimeGetTimeFn>(
        GetProcAddress(winmm, "timeGetTime"));
}

BOOL CALLBACK FindCurrentProcessWindowProc(
    HWND hwnd,
    LPARAM lparam) {
    auto* const result = reinterpret_cast<HWND*>(lparam);
    if (result == nullptr || *result != nullptr) {
        return FALSE;
    }

    DWORD process_id = 0;
    GetWindowThreadProcessId(hwnd, &process_id);
    if (process_id != GetCurrentProcessId() ||
        GetWindow(hwnd, GW_OWNER) != nullptr ||
        !IsWindowVisible(hwnd)) {
        return TRUE;
    }

    *result = hwnd;
    return FALSE;
}

HWND FindCurrentProcessMainWindow() {
    HWND hwnd = nullptr;
    EnumWindows(
        &FindCurrentProcessWindowProc,
        reinterpret_cast<LPARAM>(&hwnd));
    return hwnd;
}

void HideGameWindow() {
    auto& state = g_headless_simulation;
    if (state.game_window == nullptr ||
        !IsWindow(state.game_window)) {
        state.game_window = FindCurrentProcessMainWindow();
    }
    if (state.game_window == nullptr ||
        !IsWindowVisible(state.game_window)) {
        return;
    }

    ShowWindow(state.game_window, SW_HIDE);
    SetWindowPos(
        state.game_window,
        nullptr,
        0,
        0,
        0,
        0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER |
            SWP_NOACTIVATE | SWP_HIDEWINDOW);
    if (!state.window_hidden_logged) {
        state.window_hidden_logged = true;
        Log("Headless simulation hid the Solomon Dark window.");
    }
}

void DisableAfterRuntimeFailure(const std::string& message) {
    auto& state = g_headless_simulation;
    state.enabled = false;
    state.timing_sample_active = false;
    if (!state.runtime_failure_logged) {
        state.runtime_failure_logged = true;
        Log("Headless simulation disabled: " + message);
    }
}

bool CaptureOriginalFields(uintptr_t app_address) {
    auto& state = g_headless_simulation;
    if (state.original_fields_captured) {
        return true;
    }

    auto& memory = ProcessMemory::Instance();
    if (!memory.TryReadField(
            app_address,
            state.simulation_batch_offset,
            &state.original_simulation_batch_size) ||
        !memory.TryReadField(
            app_address,
            state.render_skip_offset,
            &state.original_render_skip_count)) {
        return false;
    }

    state.original_fields_captured = true;
    return true;
}

int CalculateNextBatchSize(
    int current_batch_size,
    double elapsed_milliseconds) {
    const auto safe_elapsed = (std::max)(
        elapsed_milliseconds,
        kMinimumMeasuredDurationMilliseconds);
    const auto desired = static_cast<double>(current_batch_size) *
        kTargetBatchDurationMilliseconds / safe_elapsed;
    const auto lower_bound = (std::max)(
        kMinimumSimulationBatchSize,
        current_batch_size / 4);
    const auto upper_bound = (std::min)(
        kMaximumSimulationBatchSize,
        current_batch_size * 4);
    const auto bounded = (std::clamp)(
        desired,
        static_cast<double>(lower_bound),
        static_cast<double>(upper_bound));
    const auto candidate = (std::clamp)(
        static_cast<int>(std::lround(bounded)),
        kMinimumSimulationBatchSize,
        kMaximumSimulationBatchSize);
    const auto minimum_change = (std::max)(
        1,
        current_batch_size / 20);
    return std::abs(candidate - current_batch_size) < minimum_change
        ? current_batch_size
        : candidate;
}

double PerformanceSeconds(
    const LARGE_INTEGER& start,
    const LARGE_INTEGER& end) {
    const auto frequency =
        g_headless_simulation.performance_frequency.QuadPart;
    if (frequency <= 0 || end.QuadPart <= start.QuadPart) {
        return 0.0;
    }
    return static_cast<double>(end.QuadPart - start.QuadPart) /
        static_cast<double>(frequency);
}

void MaybeReportThroughput(
    const LARGE_INTEGER& now,
    int actual_simulation_steps) {
    auto& state = g_headless_simulation;
    if (state.report_started.QuadPart == 0) {
        state.report_started = now;
    }
    if (actual_simulation_steps > 0) {
        state.reported_simulation_steps +=
            static_cast<std::uint64_t>(actual_simulation_steps);
    }

    const auto elapsed_seconds =
        PerformanceSeconds(state.report_started, now);
    if (elapsed_seconds < kThroughputReportIntervalSeconds) {
        return;
    }

    const auto steps_per_second =
        static_cast<double>(state.reported_simulation_steps) /
        elapsed_seconds;
    Log(
        "Headless simulation throughput=" +
        std::to_string(
            static_cast<std::uint64_t>(
                std::llround(steps_per_second))) +
        " fixed_steps_per_second batch=" +
        std::to_string(state.simulation_batch_size) +
        " stock_step_hz=100 precision=unchanged.");
    state.report_started = now;
    state.reported_simulation_steps = 0;
}

}  // namespace

bool InitializeHeadlessSimulation(std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    auto& state = g_headless_simulation;
    if (state.initialized) {
        return true;
    }

    state.initialized = true;
    if (!IsHeadlessRequested()) {
        return true;
    }

    if (!TryReadFieldOffset(
            "scheduler_baseline",
            &state.scheduler_baseline_offset) ||
        !TryReadFieldOffset(
            "scheduler_tick",
            &state.scheduler_tick_offset) ||
        !TryReadFieldOffset(
            "render_skip",
            &state.render_skip_offset) ||
        !TryReadFieldOffset(
            "simulation_batch",
            &state.simulation_batch_offset)) {
        if (error_message != nullptr) {
            *error_message =
                "Headless simulation could not resolve its MyApp field layout.";
        }
        return false;
    }

    state.time_get_time = ResolveTimeGetTime();
    if (state.time_get_time == nullptr ||
        !QueryPerformanceFrequency(&state.performance_frequency) ||
        state.performance_frequency.QuadPart <= 0) {
        if (error_message != nullptr) {
            *error_message =
                "Headless simulation could not initialize its scheduler clocks.";
        }
        return false;
    }

    state.enabled = true;
    state.simulation_batch_size = kInitialSimulationBatchSize;
    QueryPerformanceCounter(&state.report_started);
    Log(
        "Headless simulation enabled: window hidden, audio disabled, "
        "hidden bootstrap rendering retained, active-scene rendering "
        "suppressed, adaptive stock fixed-step batching active. "
        "stock_step_hz=100 precision=unchanged.");
    return true;
}

void ObserveHeadlessSimulationWindow(void* window) {
    auto& state = g_headless_simulation;
    if (state.enabled && window != nullptr) {
        state.game_window = reinterpret_cast<HWND>(window);
    }
}

void PrepareHeadlessSimulationTick(
    void* app,
    bool simulation_scene_active) {
    auto& state = g_headless_simulation;
    if (!state.enabled || app == nullptr) {
        return;
    }

    HideGameWindow();

    const auto app_address = reinterpret_cast<uintptr_t>(app);
    state.last_app_address = app_address;
    if (!CaptureOriginalFields(app_address)) {
        DisableAfterRuntimeFailure(
            "could not read the original MyApp scheduler fields.");
        return;
    }

    auto& memory = ProcessMemory::Instance();
    if (!simulation_scene_active) {
        state.timing_sample_active = false;
        if (!state.rendering_suppressed) {
            return;
        }

        const std::uint32_t scheduler_baseline =
            state.time_get_time();
        if (!memory.TryWriteField(
                app_address,
                state.render_skip_offset,
                state.original_render_skip_count) ||
            !memory.TryWriteField(
                app_address,
                state.simulation_batch_offset,
                state.original_simulation_batch_size) ||
            !memory.TryWriteField(
                app_address,
                state.scheduler_baseline_offset,
                scheduler_baseline) ||
            !memory.TryWriteField(
                app_address,
                state.scheduler_tick_offset,
                std::int32_t{0})) {
            DisableAfterRuntimeFailure(
                "could not restore the stock MyApp scheduler fields.");
            return;
        }

        state.rendering_suppressed = false;
        state.simulation_batch_size = kInitialSimulationBatchSize;
        state.prepared_batch_size = 0;
        state.reported_simulation_steps = 0;
        QueryPerformanceCounter(&state.report_started);
        Log(
            "Headless simulation left the gameplay scene; "
            "hidden bootstrap rendering and stock pacing are restored.");
        return;
    }

    const std::int32_t scheduler_tick = -1;
    const std::uint32_t scheduler_baseline =
        state.time_get_time();
    const std::int32_t batch_size =
        state.simulation_batch_size;
    if (!memory.TryWriteField(
            app_address,
            state.render_skip_offset,
            std::int32_t{1}) ||
        !memory.TryWriteField(
            app_address,
            state.scheduler_baseline_offset,
            scheduler_baseline) ||
        !memory.TryWriteField(
            app_address,
            state.scheduler_tick_offset,
            scheduler_tick) ||
        !memory.TryWriteField(
            app_address,
            state.simulation_batch_offset,
            batch_size)) {
        DisableAfterRuntimeFailure(
            "could not write the MyApp scheduler fields.");
        return;
    }

    if (!state.rendering_suppressed) {
        state.reported_simulation_steps = 0;
        QueryPerformanceCounter(&state.report_started);
        Log(
            "Headless simulation entered a gameplay scene; "
            "stock rendering is now suppressed.");
    }
    state.rendering_suppressed = true;
    state.prepared_batch_size = batch_size;
    state.timing_sample_active =
        QueryPerformanceCounter(&state.batch_started) != FALSE;
}

void FinishHeadlessSimulationTick(void* app) {
    auto& state = g_headless_simulation;
    if (!state.enabled ||
        !state.timing_sample_active ||
        app == nullptr) {
        return;
    }
    state.timing_sample_active = false;

    LARGE_INTEGER now = {};
    if (!QueryPerformanceCounter(&now)) {
        return;
    }

    std::int32_t scheduler_tick = -1;
    const auto app_address = reinterpret_cast<uintptr_t>(app);
    if (!ProcessMemory::Instance().TryReadField(
            app_address,
            state.scheduler_tick_offset,
            &scheduler_tick)) {
        DisableAfterRuntimeFailure(
            "could not read the completed MyApp scheduler tick.");
        return;
    }

    const auto actual_simulation_steps = (std::clamp)(
        scheduler_tick + 1,
        0,
        state.prepared_batch_size);
    const auto elapsed_milliseconds =
        PerformanceSeconds(state.batch_started, now) * 1000.0;
    if (actual_simulation_steps == state.prepared_batch_size &&
        elapsed_milliseconds > 0.0) {
        state.simulation_batch_size = CalculateNextBatchSize(
            state.prepared_batch_size,
            elapsed_milliseconds);
    }
    MaybeReportThroughput(now, actual_simulation_steps);
}

bool IsHeadlessSimulationEnabled() {
    return g_headless_simulation.enabled;
}

void ShutdownHeadlessSimulation() {
    auto& state = g_headless_simulation;
    if (state.original_fields_captured &&
        state.last_app_address != 0) {
        auto& memory = ProcessMemory::Instance();
        const std::int32_t scheduler_tick = 0;
        const std::uint32_t scheduler_baseline =
            state.time_get_time == nullptr
                ? GetTickCount()
                : state.time_get_time();
        (void)memory.TryWriteField(
            state.last_app_address,
            state.render_skip_offset,
            state.original_render_skip_count);
        (void)memory.TryWriteField(
            state.last_app_address,
            state.simulation_batch_offset,
            state.original_simulation_batch_size);
        (void)memory.TryWriteField(
            state.last_app_address,
            state.scheduler_baseline_offset,
            scheduler_baseline);
        (void)memory.TryWriteField(
            state.last_app_address,
            state.scheduler_tick_offset,
            scheduler_tick);
    }

    state = {};
}

}  // namespace sdmod
