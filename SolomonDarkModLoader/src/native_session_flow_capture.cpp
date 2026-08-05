#define NOMINMAX
#include "native_session_flow_capture.h"

#include "binary_layout.h"
#include "loading_screen.h"
#include "logger.h"
#include "memory_access.h"
#include "mod_loader.h"
#include "x86_hook.h"

#include <Windows.h>

#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <exception>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <mutex>
#include <sstream>
#include <string>
#include <string_view>
#include <unordered_set>

namespace sdmod {
namespace {

constexpr char kCaptureDirectoryEnvironment[] =
    "SDMOD_NATIVE_SESSION_FLOW_CAPTURE_DIRECTORY";
constexpr char kInstanceEnvironment[] = "SDMOD_LUA_EXEC_PIPE_NAME";
constexpr char kLayoutSection[] = "native_session_flow_capture";
constexpr std::size_t kPreferredImageBase = 0x00400000;

constexpr std::size_t kGameplayPendingRegionOffset = 0x78;
constexpr std::size_t kRegionFadeAlphaOffset = 0x8E48;
constexpr std::size_t kRegionFadeRateOffset = 0x8E4C;
constexpr std::size_t kRegionInitializedOffset = 0x8E6D;

using RegionSlotDetachFn = void(__thiscall*)(void* region, int slot);
using RegionNoArgFn = void(__thiscall*)(void* region);
using GameplayAttachRegionFn =
    void(__thiscall*)(void* gameplay, int target_region);

enum HookIndex : std::size_t {
    kHookRegionSlotDetach = 0,
    kHookRegionSleep,
    kHookRegionWake,
    kHookGameplayAttachRegion,
    kHookSwitchAfterOutgoingUnregister,
    kHookRegionBaseTick,
    kHookArenaStartWaves,
    kHookCount,
};

struct CaptureSnapshot {
    int current_region = -1;
    int pending_region = -1;
    std::uintptr_t gameplay = 0;
    std::uintptr_t active_region = 0;
    bool loading_sealed = false;
};

struct EventDetails {
    int native_argument = -1;
    bool has_fade_values = false;
    float alpha_before = 0.0f;
    float alpha_after = 0.0f;
    float rate_before = 0.0f;
    float rate_after = 0.0f;
};

struct NativeStateDefinition {
    const char* state;
    const char* native_identifier;
    std::uintptr_t primary_address;
    std::uintptr_t vtable_address;
    int native_region_id;
};

struct NativeEdgeDefinition {
    const char* state;
    const char* edge;
    const char* trigger;
    const char* destination;
};

constexpr std::array<NativeStateDefinition, 12> kNativeStates = {{
    {"boot.loader", "MyLoader", 0x005BAB60, 0x00799BDC, -1},
    {"frontend.shell", "MainMenu/front-end installer", 0x005A7F60, 0x007980CC, -1},
    {"gameplay.courtyard", "Courtyard", 0x00506490, 0x00792644, 0},
    {"gameplay.mortuary", "Mortuary/Memoratorium", 0x005090A0, 0x007927DC, 1},
    {"gameplay.library", "Library", 0x0050A360, 0x00792C04, 2},
    {"gameplay.storeroom", "StoreRoom", 0x00509B10, 0x0079294C, 3},
    {"gameplay.office", "Office", 0x00509C70, 0x00792AB4, 4},
    {"gameplay.arena", "Arena", 0x00464EE0, 0x00785934, 5},
    {"overlay.game_over", "GameOver", 0x005CF4F0, 0x0079B0CC, -1},
    {"post_run.mortuary_frontend", "Mortuary plus stock front end", 0x005A7F60, 0x007980CC, 1},
    {"frontend.hall_of_fame", "HallOfFame", 0x00589CD0, 0x00799334, -1},
    {"loading.boneyard", "loader readiness barrier", 0, 0, -1},
}};

constexpr std::array<NativeEdgeDefinition, 23> kNativeEdges = {{
    {"boot.loader", "boot_complete", "loader completion", "frontend.shell"},
    {"frontend.shell", "startup_hub", "new/saved/onboarded gameplay selects region 0", "gameplay.courtyard"},
    {"frontend.shell", "startup_office", "startup pending kind selects region 4", "gameplay.office"},
    {"frontend.shell", "startup_boneyard", "direct Boneyard startup selects region 5", "loading.boneyard"},
    {"loading.boneyard", "arena_materialized", "native region 5 switch plus readiness release", "gameplay.arena"},
    {"gameplay.courtyard", "enter_mortuary", "Mortuary portal collision", "gameplay.mortuary"},
    {"gameplay.mortuary", "return_courtyard", "Mortuary return portal", "gameplay.courtyard"},
    {"gameplay.mortuary", "completed_story_continue", "completed story continuation", "frontend.hall_of_fame"},
    {"gameplay.courtyard", "enter_library", "Library portal collision", "gameplay.library"},
    {"gameplay.library", "return_courtyard", "Library return portal", "gameplay.courtyard"},
    {"gameplay.courtyard", "enter_storeroom", "StoreRoom portal collision", "gameplay.storeroom"},
    {"gameplay.storeroom", "return_courtyard", "StoreRoom return portal", "gameplay.courtyard"},
    {"gameplay.courtyard", "enter_office", "Office portal collision", "gameplay.office"},
    {"gameplay.office", "return_courtyard", "Office return portal", "gameplay.courtyard"},
    {"gameplay.courtyard", "start_run", "accepted MapPicker/start-match action", "loading.boneyard"},
    {"gameplay.courtyard", "leave_game", "stock Pause then Leave Game", "frontend.shell"},
    {"gameplay.arena", "terminal_death", "solo lethal callback or authority all-dead command", "overlay.game_over"},
    {"gameplay.arena", "authority_leave_run", "host stock Leave Game plus authenticated client follow", "frontend.shell"},
    {"overlay.game_over", "story_completion", "normal GameOver close", "gameplay.mortuary"},
    {"overlay.game_over", "boneyard_completion", "tick-1000 input acceptance and stock cleanup", "post_run.mortuary_frontend"},
    {"gameplay.arena", "scripted_terminal_reset", "WIN LEVEL or LOSE LEVEL finish fade", "gameplay.courtyard"},
    {"post_run.mortuary_frontend", "open_hall_of_fame", "stock Menu action", "frontend.hall_of_fame"},
    {"frontend.hall_of_fame", "continue_to_frontend", "accepted continue and HallOfFame fade completion", "frontend.shell"},
}};

struct NativeSessionFlowCaptureState {
    bool requested = false;
    bool initialized = false;
    bool runnable = false;
    std::string status = "unavailable";
    std::string error_message;
    std::string instance;
    std::filesystem::path directory;
    std::filesystem::path events_path;
    std::filesystem::path graph_path;
    std::filesystem::path status_path;
    std::ofstream events;
    std::mutex mutex;
    std::uint64_t next_sequence = 1;
    std::uint64_t next_transition_id = 1;
    std::uint64_t active_transition_id = 0;
    int active_target_region = -1;
    bool waiting_for_unseal = false;
    std::uintptr_t gameplay_global = 0;
    std::uintptr_t region_assignment_array_global = 0;
    std::uintptr_t active_region_global = 0;
    std::array<X86Hook, kHookCount> hooks = {};
};

NativeSessionFlowCaptureState g_capture;
thread_local std::uint64_t g_thread_transition_id = 0;
thread_local int g_thread_target_region = -1;
thread_local std::unordered_set<std::uintptr_t> g_thread_active_fades;
void* g_switch_after_outgoing_unregister_trampoline = nullptr;

#include "native_session_flow_capture/io_and_graph.inl"
#include "native_session_flow_capture/hooks.inl"
}  // namespace

bool IsNativeSessionFlowCaptureRequested() {
    return !ReadEnvironmentValue(kCaptureDirectoryEnvironment).empty();
}

bool InitializeNativeSessionFlowCapture(std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (g_capture.initialized) {
        return true;
    }
    g_capture.requested = IsNativeSessionFlowCaptureRequested();
    if (!g_capture.requested) {
        g_capture.status = "unavailable";
        return true;
    }
    if (error_message == nullptr) {
        return false;
    }
    if (!IsGameplayKeyboardInjectionInitialized()) {
        *error_message =
            "session-flow recorder is broken because the gameplay switch hook is not runnable";
        g_capture.status = "broken";
        g_capture.error_message = *error_message;
        return false;
    }

    try {
        const auto directory_value =
            ReadEnvironmentValue(kCaptureDirectoryEnvironment);
        g_capture.instance = ReadEnvironmentValue(kInstanceEnvironment);
        g_capture.directory =
            std::filesystem::u8path(directory_value);
        std::filesystem::create_directories(g_capture.directory);
        g_capture.events_path =
            g_capture.directory / "session-flow-events.jsonl";
        g_capture.graph_path =
            g_capture.directory / "session-flow-native-graph.json";
        g_capture.status_path =
            g_capture.directory / "session-flow-status.json";

        const std::array<std::filesystem::path, 3> outputs = {{
            g_capture.events_path,
            g_capture.graph_path,
            g_capture.status_path,
        }};
        for (const auto& output : outputs) {
            std::error_code exists_error;
            if (std::filesystem::exists(output, exists_error) ||
                exists_error) {
                *error_message =
                    "session-flow recorder refuses an existing or unreadable output: " +
                    output.string();
                g_capture.status = "broken";
                g_capture.error_message = *error_message;
                return false;
            }
        }

        const auto write_probe =
            g_capture.directory / ".session-flow-write-probe";
        {
            std::ofstream probe(
                write_probe,
                std::ios::binary | std::ios::trunc);
            probe << "session-flow-write-probe\n";
            probe.flush();
            if (!probe) {
                *error_message =
                    "session-flow recorder directory exists but is not writable";
                g_capture.status = "broken";
                g_capture.error_message = *error_message;
                return false;
            }
        }
        std::error_code remove_error;
        if (!std::filesystem::remove(write_probe, remove_error) ||
            remove_error) {
            *error_message =
                "session-flow recorder write probe ran but cleanup failed";
            g_capture.status = "broken";
            g_capture.error_message = *error_message;
            return false;
        }

        if (!ResolveLayoutAddress(
                "gameplay_global",
                &g_capture.gameplay_global,
                error_message) ||
            !ResolveLayoutAddress(
                "region_assignment_array_global",
                &g_capture.region_assignment_array_global,
                error_message) ||
            !ResolveLayoutAddress(
                "active_region_global",
                &g_capture.active_region_global,
                error_message)) {
            g_capture.status = "broken";
            g_capture.error_message = *error_message;
            WriteStatusLocked();
            return false;
        }

        g_capture.events.open(
            g_capture.events_path,
            std::ios::binary | std::ios::out | std::ios::trunc);
        if (!g_capture.events) {
            *error_message =
                "session-flow recorder could not open its event stream";
            g_capture.status = "broken";
            g_capture.error_message = *error_message;
            WriteStatusLocked();
            return false;
        }
        if (!InstallCaptureHooks(error_message)) {
            g_capture.status = "broken";
            g_capture.error_message = *error_message;
            WriteStatusLocked();
            g_capture.events.close();
            return false;
        }
        if (!WriteGraphFile(error_message)) {
            RemoveCaptureHooks();
            g_capture.status = "broken";
            g_capture.error_message = *error_message;
            WriteStatusLocked();
            g_capture.events.close();
            return false;
        }

        g_capture.initialized = true;
        g_capture.runnable = true;
        g_capture.status = "idle";
        g_capture.error_message.clear();
        if (!AppendEventLocked(
                0,
                "capture.ready",
                0,
                EventDetails{})) {
            *error_message = g_capture.error_message.empty()
                ? "session-flow recorder failed its end-to-end event write"
                : g_capture.error_message;
            RemoveCaptureHooks();
            g_capture.initialized = false;
            g_capture.events.close();
            return false;
        }
        WriteStatusLocked();
        Log(
            "Native session-flow capture initialized. directory=" +
            g_capture.directory.string());
        return true;
    } catch (const std::exception& ex) {
        RemoveCaptureHooks();
        *error_message = std::string(
            "session-flow recorder setup is not runnable: ") + ex.what();
        g_capture.status = "broken";
        g_capture.runnable = false;
        g_capture.error_message = *error_message;
        WriteStatusLocked();
        return false;
    }
}

void ShutdownNativeSessionFlowCapture() {
    RemoveCaptureHooks();
    {
        std::scoped_lock lock(g_capture.mutex);
        if (g_capture.initialized && g_capture.events.is_open()) {
            (void)AppendEventLocked(
                0,
                "capture.shutdown",
                0,
                EventDetails{});
        }
        if (g_capture.events.is_open()) {
            g_capture.events.close();
        }
        g_capture.initialized = false;
        g_capture.runnable = false;
        g_capture.requested = false;
        g_capture.status = "unavailable";
        g_capture.error_message.clear();
        g_capture.active_transition_id = 0;
        g_capture.active_target_region = -1;
        g_capture.waiting_for_unseal = false;
        g_capture.gameplay_global = 0;
        g_capture.region_assignment_array_global = 0;
        g_capture.active_region_global = 0;
    }
    g_thread_transition_id = 0;
    g_thread_target_region = -1;
    g_thread_active_fades.clear();
}

void NativeSessionFlowCaptureBeginSwitch(
    void* gameplay,
    int target_region) {
    if (!g_capture.initialized) {
        return;
    }
    std::uint64_t transition_id = 0;
    {
        std::scoped_lock lock(g_capture.mutex);
        transition_id = g_capture.next_transition_id++;
        g_capture.active_transition_id = transition_id;
        g_capture.active_target_region = target_region;
        g_capture.waiting_for_unseal = target_region == 5;
        g_capture.status = "busy";
        WriteStatusLocked();
    }
    g_thread_transition_id = transition_id;
    g_thread_target_region = target_region;
    EventDetails details;
    details.native_argument = target_region;
    AppendEvent(
        transition_id,
        "switch.enter",
        reinterpret_cast<std::uintptr_t>(gameplay),
        details);
}

void NativeSessionFlowCaptureEndSwitch(
    void* gameplay,
    int target_region) {
    if (!g_capture.initialized || g_thread_transition_id == 0) {
        return;
    }
    const auto transition_id = g_thread_transition_id;
    EventDetails details;
    details.native_argument = target_region;
    AppendEvent(
        transition_id,
        "switch.exit",
        reinterpret_cast<std::uintptr_t>(gameplay),
        details);
    {
        std::scoped_lock lock(g_capture.mutex);
        if (!g_capture.waiting_for_unseal) {
            g_capture.status = "idle";
            WriteStatusLocked();
        }
    }
    g_thread_transition_id = 0;
    g_thread_target_region = -1;
}

void NativeSessionFlowCaptureObserveSwitchStep(
    const char* step,
    void* object,
    int native_argument) {
    if (!g_capture.initialized || step == nullptr || *step == '\0') {
        return;
    }
    EventDetails details;
    details.native_argument = native_argument;
    AppendEvent(
        CurrentTransitionId(),
        step,
        reinterpret_cast<std::uintptr_t>(object),
        details);
}

void NativeSessionFlowCaptureObserveInputSeal() {
    if (!g_capture.initialized) {
        return;
    }
    {
        std::scoped_lock lock(g_capture.mutex);
        g_capture.waiting_for_unseal = true;
        g_capture.status = "busy";
        WriteStatusLocked();
    }
    AppendEvent(CurrentTransitionId(), "input.seal");
}

void NativeSessionFlowCaptureObserveInputUnseal(const char* reason) {
    if (!g_capture.initialized) {
        return;
    }
    const auto transition_id = CurrentTransitionId();
    EventDetails details;
    AppendEvent(
        transition_id,
        reason != nullptr && *reason != '\0'
            ? reason
            : "input.unseal",
        0,
        details);
    {
        std::scoped_lock lock(g_capture.mutex);
        g_capture.waiting_for_unseal = false;
        if (g_thread_transition_id == 0) {
            g_capture.status = "idle";
        }
        WriteStatusLocked();
    }
}

void NativeSessionFlowCaptureObserveSessionEvent(
    const char* step,
    void* object,
    int native_argument) {
    if (!g_capture.initialized || step == nullptr || *step == '\0') {
        return;
    }
    EventDetails details;
    details.native_argument = native_argument;
    AppendEvent(
        0,
        step,
        reinterpret_cast<std::uintptr_t>(object),
        details);
}

}  // namespace sdmod
