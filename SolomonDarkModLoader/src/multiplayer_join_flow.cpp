#include "multiplayer_join_flow.h"

#include "debug_ui_overlay.h"
#include "logger.h"
#include "mod_loader.h"
#include "multiplayer_runtime_state.h"

#include <Windows.h>

#include <algorithm>
#include <cstdint>
#include <mutex>
#include <string>
#include <string_view>

namespace sdmod {
namespace {

constexpr char kQuickStartEnvironmentVariable[] =
    "SDMOD_MULTIPLAYER_QUICK_START";
constexpr std::uint64_t kMainMenuDialogWindowMs = 1000;
constexpr std::uint64_t kActionRetryDelayMs = 100;
constexpr std::uint64_t kCreateSurfaceExitStabilityMs = 100;
constexpr std::uint64_t kTransitionPresentationMinimumMs = 750;

enum class JoinFlowPhase {
    Disabled,
    AdvancingMenus,
    AwaitingLoadout,
    SelectingLoadout,
    Connecting,
    Hub,
    LoadingBoneyard,
    Run,
    Failed,
};

struct JoinFlowState {
    bool enabled = false;
    JoinFlowPhase phase = JoinFlowPhase::Disabled;
    std::uint64_t phase_entered_ms = 0;
    std::uint64_t main_menu_first_seen_ms = 0;
    std::uint64_t action_retry_not_before_ms = 0;
    std::uint64_t pending_action_request_id = 0;
    std::uint64_t pending_action_generation = 0;
    std::string pending_action_id;
    bool create_scene_valid = false;
    std::uintptr_t create_gameplay_scene_address = 0;
    std::uintptr_t create_world_address = 0;
    std::uint64_t create_surface_absent_since_ms = 0;
    std::mutex mutex;
};

JoinFlowState g_join_flow;

const char* PhaseLabel(JoinFlowPhase phase) {
    switch (phase) {
    case JoinFlowPhase::AdvancingMenus:
        return "advancing_menus";
    case JoinFlowPhase::AwaitingLoadout:
        return "awaiting_loadout";
    case JoinFlowPhase::SelectingLoadout:
        return "selecting_loadout";
    case JoinFlowPhase::Connecting:
        return "connecting";
    case JoinFlowPhase::Hub:
        return "hub";
    case JoinFlowPhase::LoadingBoneyard:
        return "loading_boneyard";
    case JoinFlowPhase::Run:
        return "run";
    case JoinFlowPhase::Failed:
        return "failed";
    case JoinFlowPhase::Disabled:
    default:
        return "disabled";
    }
}

bool ReadQuickStartEnvironment() {
    char value[2] = {};
    return GetEnvironmentVariableA(
               kQuickStartEnvironmentVariable,
               value,
               static_cast<DWORD>(sizeof(value))) == 1 &&
           value[0] == '1';
}

void ResetStateUnlocked(JoinFlowState* state) {
    state->enabled = false;
    state->phase = JoinFlowPhase::Disabled;
    state->phase_entered_ms = 0;
    state->main_menu_first_seen_ms = 0;
    state->action_retry_not_before_ms = 0;
    state->pending_action_request_id = 0;
    state->pending_action_generation = 0;
    state->pending_action_id.clear();
    state->create_scene_valid = false;
    state->create_gameplay_scene_address = 0;
    state->create_world_address = 0;
    state->create_surface_absent_since_ms = 0;
}

void SetPhaseUnlocked(JoinFlowPhase phase) {
    if (g_join_flow.phase == phase) {
        return;
    }
    Log(
        "Multiplayer join flow: " +
        std::string(PhaseLabel(g_join_flow.phase)) + " -> " +
        PhaseLabel(phase));
    g_join_flow.phase = phase;
    g_join_flow.phase_entered_ms =
        static_cast<std::uint64_t>(GetTickCount64());
}

bool IsHubReady(const SDModSceneState& scene) {
    return scene.valid &&
           (scene.kind == "hub" || scene.name == "hub") &&
           scene.world_address != 0;
}

bool IsBoneyardReady(const SDModSceneState& scene) {
    return scene.valid &&
           (scene.kind == "arena" || scene.name == "testrun") &&
           scene.world_address != 0 &&
           scene.arena_address != 0;
}

bool HasAction(
    const DebugUiSurfaceSnapshot& snapshot,
    std::string_view action_id) {
    return std::any_of(
        snapshot.elements.begin(),
        snapshot.elements.end(),
        [&](const DebugUiSnapshotElement& element) {
            return element.action_id == action_id;
        });
}

void ClearPendingActionUnlocked() {
    g_join_flow.pending_action_request_id = 0;
    g_join_flow.pending_action_generation = 0;
    g_join_flow.pending_action_id.clear();
}

bool QueueActionUnlocked(
    const DebugUiSurfaceSnapshot& snapshot,
    std::string_view action_id,
    std::uint64_t now_ms) {
    std::uint64_t request_id = 0;
    std::string error_message;
    if (!TryActivateDebugUiAction(
            action_id,
            snapshot.surface_id,
            &request_id,
            &error_message)) {
        g_join_flow.action_retry_not_before_ms =
            now_ms + kActionRetryDelayMs;
        return false;
    }

    g_join_flow.pending_action_request_id = request_id;
    g_join_flow.pending_action_generation = snapshot.generation;
    g_join_flow.pending_action_id = action_id;
    return true;
}

bool ResolvePendingActionUnlocked(
    const DebugUiSurfaceSnapshot* snapshot,
    std::uint64_t now_ms) {
    if (g_join_flow.pending_action_request_id == 0) {
        return true;
    }

    DebugUiActionDispatchSnapshot dispatch;
    if (!TryGetDebugUiActionDispatchSnapshot(
            g_join_flow.pending_action_request_id,
            &dispatch)) {
        ClearPendingActionUnlocked();
        g_join_flow.action_retry_not_before_ms =
            now_ms + kActionRetryDelayMs;
        return false;
    }

    if (dispatch.status == "failed") {
        ClearPendingActionUnlocked();
        g_join_flow.action_retry_not_before_ms =
            now_ms + kActionRetryDelayMs;
        return false;
    }
    if (dispatch.status != "dispatched") {
        return false;
    }

    if (g_join_flow.pending_action_id == "main_menu.new_game") {
        ClearPendingActionUnlocked();
        SetPhaseUnlocked(JoinFlowPhase::AwaitingLoadout);
        return false;
    }

    if (snapshot != nullptr &&
        snapshot->generation == g_join_flow.pending_action_generation) {
        return false;
    }

    ClearPendingActionUnlocked();
    return true;
}

void EnterLoadoutSelectionUnlocked(const SDModSceneState& scene) {
    ClearPendingActionUnlocked();
    g_join_flow.create_scene_valid = scene.valid;
    g_join_flow.create_gameplay_scene_address =
        scene.gameplay_scene_address;
    g_join_flow.create_world_address = scene.world_address;
    g_join_flow.create_surface_absent_since_ms = 0;
    SetPhaseUnlocked(JoinFlowPhase::SelectingLoadout);
}

bool HasLoadoutSelectionFinished(
    const SDModSceneState& scene,
    std::uint64_t now_ms) {
    if (g_join_flow.create_surface_absent_since_ms != 0 &&
        now_ms >=
            g_join_flow.create_surface_absent_since_ms +
                kCreateSurfaceExitStabilityMs) {
        return true;
    }
    if (!g_join_flow.create_scene_valid) {
        return scene.valid;
    }
    return scene.valid &&
           ((g_join_flow.create_gameplay_scene_address != 0 &&
             scene.gameplay_scene_address !=
                 g_join_flow.create_gameplay_scene_address) ||
            scene.world_address !=
                g_join_flow.create_world_address);
}

bool IsRunRequested(const multiplayer::RuntimeState& runtime) {
    if (IsRunLifecycleActive()) {
        return true;
    }
    if (runtime.session_is_host || runtime.steam_host_id == 0) {
        return false;
    }

    return std::any_of(
        runtime.participants.begin(),
        runtime.participants.end(),
        [&](const multiplayer::ParticipantInfo& participant) {
            const bool is_host =
                participant.steam_id == runtime.steam_host_id ||
                participant.participant_id == runtime.steam_host_id;
            return is_host &&
                   participant.runtime.valid &&
                   participant.runtime.run_nonce != 0 &&
                   participant.runtime.scene_intent.kind ==
                       multiplayer::ParticipantSceneIntentKind::Run;
        });
}

}  // namespace

bool InitializeMultiplayerJoinFlow() {
    std::scoped_lock lock(g_join_flow.mutex);
    ResetStateUnlocked(&g_join_flow);
    if (!ReadQuickStartEnvironment()) {
        return false;
    }

    g_join_flow.enabled = true;
    g_join_flow.phase = JoinFlowPhase::AdvancingMenus;
    g_join_flow.phase_entered_ms =
        static_cast<std::uint64_t>(GetTickCount64());
    Log("Multiplayer join flow enabled.");
    return true;
}

void ShutdownMultiplayerJoinFlow() {
    std::scoped_lock lock(g_join_flow.mutex);
    const bool was_enabled = g_join_flow.enabled;
    ResetStateUnlocked(&g_join_flow);
    if (was_enabled) {
        Log("Multiplayer join flow shut down.");
    }
}

void TickMultiplayerJoinFlow() {
    std::scoped_lock lock(g_join_flow.mutex);
    if (!g_join_flow.enabled) {
        return;
    }

    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    const auto runtime = multiplayer::SnapshotRuntimeState();
    if (runtime.session_status == multiplayer::SessionStatus::Error) {
        SetPhaseUnlocked(JoinFlowPhase::Failed);
        return;
    }

    SDModSceneState scene;
    (void)TryGetSceneState(&scene);
    const bool hub_ready = IsHubReady(scene);
    const bool boneyard_ready = IsBoneyardReady(scene);

    DebugUiSurfaceSnapshot current_snapshot;
    const bool snapshot_available =
        TryGetLatestDebugUiSurfaceSnapshot(&current_snapshot);
    const auto* snapshot =
        snapshot_available ? &current_snapshot : nullptr;

    switch (g_join_flow.phase) {
    case JoinFlowPhase::AdvancingMenus:
        if (!ResolvePendingActionUnlocked(snapshot, now_ms)) {
            return;
        }
        if (snapshot == nullptr) {
            return;
        }
        if (snapshot->surface_id == "create") {
            EnterLoadoutSelectionUnlocked(scene);
            return;
        }
        if (snapshot->surface_id == "dialog" &&
            HasAction(*snapshot, "dialog.primary")) {
            (void)QueueActionUnlocked(
                *snapshot,
                "dialog.primary",
                now_ms);
            return;
        }
        if (snapshot->surface_id != "main_menu") {
            return;
        }
        if (g_join_flow.main_menu_first_seen_ms == 0) {
            g_join_flow.main_menu_first_seen_ms = now_ms;
        }
        if (now_ms <
            g_join_flow.main_menu_first_seen_ms +
                kMainMenuDialogWindowMs) {
            return;
        }
        if (now_ms < g_join_flow.action_retry_not_before_ms) {
            return;
        }
        if (HasAction(*snapshot, "main_menu.play")) {
            (void)QueueActionUnlocked(
                *snapshot,
                "main_menu.play",
                now_ms);
        } else if (HasAction(*snapshot, "main_menu.new_game")) {
            (void)QueueActionUnlocked(
                *snapshot,
                "main_menu.new_game",
                now_ms);
        }
        return;

    case JoinFlowPhase::AwaitingLoadout:
        if (snapshot != nullptr &&
            snapshot->surface_id == "create") {
            EnterLoadoutSelectionUnlocked(scene);
        } else if (hub_ready) {
            SetPhaseUnlocked(JoinFlowPhase::Connecting);
        } else if (boneyard_ready) {
            SetPhaseUnlocked(JoinFlowPhase::Run);
        }
        return;

    case JoinFlowPhase::SelectingLoadout:
        if (HasLoadoutSelectionFinished(scene, now_ms)) {
            SetPhaseUnlocked(JoinFlowPhase::Connecting);
        }
        return;

    case JoinFlowPhase::Connecting:
        if (now_ms <
            g_join_flow.phase_entered_ms +
                kTransitionPresentationMinimumMs) {
            return;
        }
        if (boneyard_ready) {
            SetPhaseUnlocked(JoinFlowPhase::Run);
        } else if (
            hub_ready &&
            runtime.transport_ready &&
            runtime.session_status ==
                multiplayer::SessionStatus::Ready) {
            SetPhaseUnlocked(JoinFlowPhase::Hub);
        }
        return;

    case JoinFlowPhase::Hub:
        if (boneyard_ready) {
            SetPhaseUnlocked(JoinFlowPhase::Run);
        } else if (IsRunRequested(runtime)) {
            SetPhaseUnlocked(JoinFlowPhase::LoadingBoneyard);
        }
        return;

    case JoinFlowPhase::LoadingBoneyard:
        if (now_ms <
            g_join_flow.phase_entered_ms +
                kTransitionPresentationMinimumMs) {
            return;
        }
        if (boneyard_ready) {
            SetPhaseUnlocked(JoinFlowPhase::Run);
        } else if (hub_ready && !IsRunRequested(runtime)) {
            SetPhaseUnlocked(JoinFlowPhase::Hub);
        }
        return;

    case JoinFlowPhase::Run:
        if (hub_ready) {
            SetPhaseUnlocked(JoinFlowPhase::Hub);
        }
        return;

    case JoinFlowPhase::Failed:
    case JoinFlowPhase::Disabled:
    default:
        return;
    }
}

void ObserveMultiplayerJoinFlowSurface(
    std::string_view surface_id) {
    std::scoped_lock lock(g_join_flow.mutex);
    if (!g_join_flow.enabled ||
        g_join_flow.phase != JoinFlowPhase::SelectingLoadout) {
        return;
    }

    if (surface_id == "create") {
        g_join_flow.create_surface_absent_since_ms = 0;
    } else if (g_join_flow.create_surface_absent_since_ms == 0) {
        g_join_flow.create_surface_absent_since_ms =
            static_cast<std::uint64_t>(GetTickCount64());
    }
}

void NotifyMultiplayerJoinFlowRunStart() {
    std::scoped_lock lock(g_join_flow.mutex);
    if (g_join_flow.enabled &&
        (g_join_flow.phase == JoinFlowPhase::Hub ||
         g_join_flow.phase == JoinFlowPhase::Run)) {
        SetPhaseUnlocked(JoinFlowPhase::LoadingBoneyard);
    }
}

MultiplayerJoinFlowPresentation
GetMultiplayerJoinFlowPresentation() {
    std::scoped_lock lock(g_join_flow.mutex);
    switch (g_join_flow.phase) {
    case JoinFlowPhase::AdvancingMenus:
    case JoinFlowPhase::AwaitingLoadout:
        return {true, {}};
    case JoinFlowPhase::Connecting:
        return {true, "Connecting to match"};
    case JoinFlowPhase::LoadingBoneyard:
        return {true, "Loading Boneyard"};
    default:
        return {};
    }
}

}  // namespace sdmod
