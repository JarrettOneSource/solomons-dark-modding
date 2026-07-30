#include "multiplayer_join_flow.h"

#include "debug_ui_overlay.h"
#include "loading_screen.h"
#include "logger.h"
#include "memory_access.h"
#include "mod_loader.h"
#include "multiplayer_local_transport.h"
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
constexpr char kQuickStartElementEnvironmentVariable[] =
    "SDMOD_MULTIPLAYER_QUICK_START_ELEMENT";
constexpr char kQuickStartDisciplineEnvironmentVariable[] =
    "SDMOD_MULTIPLAYER_QUICK_START_DISCIPLINE";
constexpr char kQuickStartRunEnvironmentVariable[] =
    "SDMOD_MULTIPLAYER_QUICK_START_RUN";
constexpr std::uint64_t kMainMenuDialogWindowMs = 1000;
constexpr std::uint64_t kActionRetryDelayMs = 100;
constexpr std::uint64_t kCreateSurfaceExitStabilityMs = 100;
constexpr std::uint64_t kTransitionPresentationMinimumMs = 750;
constexpr std::uint64_t kReadyStagePresentationMinimumMs = 150;
constexpr std::uint64_t kQuickStartRunMaterializedDelayMs = 12000;
constexpr std::uint64_t kPostRunInputRetryDelayMs = 1000;
constexpr std::size_t kCreateElementEnabledOffset = 0x18C;
constexpr std::size_t kCreateElementSelectedOffset = 0x1A4;
constexpr std::size_t kCreateDisciplineEnabledOffset = 0x228;
constexpr std::size_t kCreateDisciplineSelectedOffset = 0x22C;
constexpr std::uint32_t kCreateSelectionUnset = 0xFFFFFFFFu;

enum class JoinFlowPhase {
    Disabled,
    AdvancingMenus,
    PrivateGameplay,
    AwaitingLoadout,
    SelectingLoadout,
    Connecting,
    Hub,
    LoadingBoneyard,
    Run,
    PostRun,
    Failed,
};

struct JoinFlowState {
    bool enabled = false;
    JoinFlowPhase phase = JoinFlowPhase::Disabled;
    std::uint64_t phase_entered_ms = 0;
    std::uint64_t connection_ready_since_ms = 0;
    std::uint64_t main_menu_first_seen_ms = 0;
    std::uint64_t action_retry_not_before_ms = 0;
    std::uint64_t pending_action_request_id = 0;
    std::uint64_t pending_action_generation = 0;
    std::string pending_action_id;
    std::uintptr_t control_scheme_dispatched_owner_address = 0;
    std::string quick_start_element_action_id;
    std::string quick_start_discipline_action_id;
    std::uint32_t quick_start_element_id = kCreateSelectionUnset;
    bool quick_start_element_dispatched = false;
    bool quick_start_discipline_dispatched = false;
    bool quick_start_loadout_replay_enabled = false;
    bool quick_start_loadout_state_logged = false;
    std::string action_queue_last_error;
    bool quick_start_run = false;
    bool quick_start_run_requested = false;
    std::uint64_t quick_start_run_ready_since_ms = 0;
    std::string quick_start_run_last_error;
    std::uint64_t post_run_menu_retry_not_before_ms = 0;
    bool post_run_menu_request_logged = false;
    std::string post_run_menu_last_error;
    std::uint64_t post_run_hall_of_fame_retry_not_before_ms = 0;
    bool post_run_hall_of_fame_continue_logged = false;
    std::string post_run_hall_of_fame_continue_last_error;
    bool create_scene_valid = false;
    std::uintptr_t create_gameplay_scene_address = 0;
    std::uintptr_t create_world_address = 0;
    std::uint64_t create_surface_absent_since_ms = 0;
    std::mutex mutex;
};

JoinFlowState g_join_flow;

void ClearPendingActionUnlocked();
void SetPhaseUnlocked(JoinFlowPhase phase);
bool IsHostCharacterReady(
    const multiplayer::RuntimeState& runtime);

const char* PhaseLabel(JoinFlowPhase phase) {
    switch (phase) {
    case JoinFlowPhase::AdvancingMenus:
        return "advancing_menus";
    case JoinFlowPhase::PrivateGameplay:
        return "private_gameplay";
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
    case JoinFlowPhase::PostRun:
        return "post_run";
    case JoinFlowPhase::Failed:
        return "failed";
    case JoinFlowPhase::Disabled:
    default:
        return "disabled";
    }
}

bool ReadEnabledEnvironmentVariable(const char* name) {
    char value[2] = {};
    return GetEnvironmentVariableA(
               name,
               value,
               static_cast<DWORD>(sizeof(value))) == 1 &&
           value[0] == '1';
}

std::string ReadShortEnvironmentVariable(const char* name) {
    char value[16] = {};
    const auto length = GetEnvironmentVariableA(
        name,
        value,
        static_cast<DWORD>(sizeof(value)));
    if (length == 0 || length >= sizeof(value)) {
        return {};
    }
    return std::string(value, length);
}

bool IsSupportedQuickStartElement(std::string_view value) {
    return value == "ether" ||
           value == "fire" ||
           value == "air" ||
           value == "water" ||
           value == "earth";
}

std::uint32_t QuickStartElementId(std::string_view value) {
    if (value == "ether") {
        return 0;
    }
    if (value == "fire") {
        return 1;
    }
    if (value == "air") {
        return 2;
    }
    if (value == "water") {
        return 3;
    }
    if (value == "earth") {
        return 4;
    }
    return kCreateSelectionUnset;
}

std::string ElementActionIdForSelection(std::uint32_t selection) {
    switch (selection) {
    case 0:
        return "create.select_element_ether";
    case 1:
        return "create.select_element_fire";
    case 2:
        return "create.select_element_air";
    case 3:
        return "create.select_element_water";
    case 4:
        return "create.select_element_earth";
    default:
        return {};
    }
}

std::string DisciplineActionIdForSelection(std::uint32_t selection) {
    switch (selection) {
    case 0:
        return "create.select_discipline_mind";
    case 1:
        return "create.select_discipline_body";
    case 2:
        return "create.select_discipline_arcane";
    default:
        return {};
    }
}

bool IsSupportedQuickStartDiscipline(std::string_view value) {
    return value == "mind" ||
           value == "body" ||
           value == "arcane";
}

void ResetStateUnlocked(JoinFlowState* state) {
    state->enabled = false;
    state->phase = JoinFlowPhase::Disabled;
    state->phase_entered_ms = 0;
    state->connection_ready_since_ms = 0;
    state->main_menu_first_seen_ms = 0;
    state->action_retry_not_before_ms = 0;
    state->pending_action_request_id = 0;
    state->pending_action_generation = 0;
    state->pending_action_id.clear();
    state->control_scheme_dispatched_owner_address = 0;
    state->quick_start_element_action_id.clear();
    state->quick_start_discipline_action_id.clear();
    state->quick_start_element_id = kCreateSelectionUnset;
    state->quick_start_element_dispatched = false;
    state->quick_start_discipline_dispatched = false;
    state->quick_start_loadout_replay_enabled = false;
    state->quick_start_loadout_state_logged = false;
    state->action_queue_last_error.clear();
    state->quick_start_run = false;
    state->quick_start_run_requested = false;
    state->quick_start_run_ready_since_ms = 0;
    state->quick_start_run_last_error.clear();
    state->post_run_menu_retry_not_before_ms = 0;
    state->post_run_menu_request_logged = false;
    state->post_run_menu_last_error.clear();
    state->post_run_hall_of_fame_retry_not_before_ms = 0;
    state->post_run_hall_of_fame_continue_logged = false;
    state->post_run_hall_of_fame_continue_last_error.clear();
    state->create_scene_valid = false;
    state->create_gameplay_scene_address = 0;
    state->create_world_address = 0;
    state->create_surface_absent_since_ms = 0;
}

#include "multiplayer_join_flow/loading_screen_progress.inl"

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
    g_join_flow.connection_ready_since_ms = 0;
    UpdateLoadingScreenForPhase(phase);
    if (phase == JoinFlowPhase::PostRun) {
        g_join_flow.post_run_menu_retry_not_before_ms = 0;
        g_join_flow.post_run_menu_request_logged = false;
        g_join_flow.post_run_menu_last_error.clear();
        g_join_flow.post_run_hall_of_fame_retry_not_before_ms = 0;
        g_join_flow.post_run_hall_of_fame_continue_logged = false;
        g_join_flow.post_run_hall_of_fame_continue_last_error.clear();
    }
}

bool IsHubScene(const SDModSceneState& scene) {
    return scene.valid &&
           (scene.kind == "hub" || scene.name == "hub");
}

bool IsBoneyardScene(const SDModSceneState& scene) {
    return scene.valid &&
           (scene.kind == "arena" || scene.name == "testrun");
}

bool IsTutorialReady(const SDModSceneState& scene) {
    return scene.valid &&
           scene.world_address != 0 &&
           (scene.kind == "tutorial" || scene.name == "tutorial");
}

bool IsHubReady(const SDModSceneState& scene) {
    return IsHubScene(scene) &&
           scene.world_address != 0;
}

bool IsBoneyardReady(const SDModSceneState& scene) {
    return IsBoneyardScene(scene) &&
           scene.world_address != 0 &&
           scene.arena_address != 0;
}

bool IsHostCharacterReady(const multiplayer::RuntimeState& runtime) {
    if (runtime.session_is_host) {
        SDModPlayerState host_player;
        return TryGetPlayerState(&host_player) &&
               host_player.valid &&
               host_player.actor_address != 0;
    }
    const auto host_participant_id =
        runtime.steam_host_id != 0
        ? runtime.steam_host_id
        : multiplayer::GetLocalTransportAuthorityParticipantId();
    if (host_participant_id == 0) {
        return false;
    }

    const auto host_participant = std::find_if(
        runtime.participants.begin(),
        runtime.participants.end(),
        [&](const multiplayer::ParticipantInfo& participant) {
            return participant.steam_id == host_participant_id ||
                   participant.participant_id == host_participant_id;
        });
    if (host_participant == runtime.participants.end()) {
        return false;
    }

    SDModParticipantGameplayState host_character;
    return TryGetParticipantGameplayState(
               host_participant->participant_id,
               &host_character) &&
           host_character.entity_materialized &&
           host_character.actor_address != 0;
}

bool HasMaterializedRemoteCharacter(
    const multiplayer::RuntimeState& runtime) {
    return std::any_of(
        runtime.participants.begin(),
        runtime.participants.end(),
        [](const multiplayer::ParticipantInfo& participant) {
            if (participant.kind !=
                    multiplayer::ParticipantKind::RemoteParticipant ||
                !participant.transport_connected) {
                return false;
            }
            SDModParticipantGameplayState character;
            return TryGetParticipantGameplayState(
                       participant.participant_id,
                       &character) &&
                   character.entity_materialized &&
                   character.actor_address != 0;
        });
}

bool IsPrivateGameplayReady(const SDModSceneState& scene) {
    return scene.valid &&
           scene.world_address != 0 &&
           !IsHubScene(scene) &&
           !IsTutorialReady(scene) &&
           !IsBoneyardScene(scene);
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

bool TryReadCreateSelectionState(
    const DebugUiSurfaceSnapshot* snapshot,
    std::uint32_t* element_enabled,
    std::uint32_t* element_selected,
    std::uint32_t* discipline_enabled,
    std::uint32_t* discipline_selected) {
    if (snapshot == nullptr ||
        snapshot->surface_id != "create" ||
        snapshot->elements.empty() ||
        element_enabled == nullptr ||
        element_selected == nullptr ||
        discipline_enabled == nullptr ||
        discipline_selected == nullptr) {
        return false;
    }

    const auto owner = snapshot->elements.front().surface_object_ptr;
    auto& memory = ProcessMemory::Instance();
    return owner != 0 &&
           memory.TryReadField(
               owner,
               kCreateElementEnabledOffset,
               element_enabled) &&
           memory.TryReadField(
               owner,
               kCreateElementSelectedOffset,
               element_selected) &&
           memory.TryReadField(
               owner,
               kCreateDisciplineEnabledOffset,
               discipline_enabled) &&
           memory.TryReadField(
               owner,
               kCreateDisciplineSelectedOffset,
               discipline_selected);
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
        if (error_message !=
            g_join_flow.action_queue_last_error) {
            g_join_flow.action_queue_last_error =
                error_message;
            Log(
                "Multiplayer join flow could not queue semantic UI "
                "action '" +
                std::string(action_id) + "'. error=" +
                error_message);
        }
        return false;
    }

    g_join_flow.action_queue_last_error.clear();
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
        if (g_join_flow.pending_action_id ==
            "control_scheme_picker.select_wasd") {
            g_join_flow.control_scheme_dispatched_owner_address = 0;
        }
        ClearPendingActionUnlocked();
        g_join_flow.action_retry_not_before_ms =
            now_ms + kActionRetryDelayMs;
        return false;
    }

    if (dispatch.status == "failed") {
        if (g_join_flow.pending_action_id ==
            "control_scheme_picker.select_wasd") {
            g_join_flow.control_scheme_dispatched_owner_address = 0;
        }
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

    const bool dispatched_quick_start_loadout_action =
        g_join_flow.phase == JoinFlowPhase::SelectingLoadout &&
        (g_join_flow.pending_action_id ==
             g_join_flow.quick_start_element_action_id ||
         g_join_flow.pending_action_id ==
             g_join_flow.quick_start_discipline_action_id);
    if (!dispatched_quick_start_loadout_action &&
        snapshot != nullptr &&
        snapshot->generation == g_join_flow.pending_action_generation) {
        return false;
    }

    const auto dispatched_action_id = g_join_flow.pending_action_id;
    ClearPendingActionUnlocked();
    if (g_join_flow.phase == JoinFlowPhase::SelectingLoadout) {
        if (dispatched_action_id ==
            g_join_flow.quick_start_element_action_id) {
            g_join_flow.quick_start_element_dispatched = true;
        } else if (
            dispatched_action_id ==
            g_join_flow.quick_start_discipline_action_id) {
            g_join_flow.quick_start_discipline_dispatched = true;
        }
    }
    return true;
}

void EnterLoadoutSelectionUnlocked(const SDModSceneState& scene) {
    ClearPendingActionUnlocked();
    g_join_flow.create_scene_valid = scene.valid;
    g_join_flow.create_gameplay_scene_address =
        scene.gameplay_scene_address;
    g_join_flow.create_world_address = scene.world_address;
    g_join_flow.create_surface_absent_since_ms = 0;
    g_join_flow.quick_start_element_dispatched = false;
    g_join_flow.quick_start_discipline_dispatched = false;
    g_join_flow.quick_start_loadout_replay_enabled =
        !g_join_flow.quick_start_element_action_id.empty() &&
        !g_join_flow.quick_start_discipline_action_id.empty();
    g_join_flow.quick_start_loadout_state_logged = false;
    g_join_flow.action_queue_last_error.clear();
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

bool IsRunLoadingBarrierReleased(
    const multiplayer::RuntimeState& runtime) {
    const auto* local =
        multiplayer::FindLocalParticipant(runtime);
    return local != nullptr &&
           local->runtime.run_nonce != 0 &&
           runtime.run_loading_barrier.active &&
           runtime.run_loading_barrier.released &&
           runtime.run_loading_barrier.run_nonce ==
               local->runtime.run_nonce &&
           runtime.run_loading_barrier.release_nonce ==
               local->runtime.run_nonce;
}

bool HasLocalRunTerminated(
    const multiplayer::RuntimeState& runtime) {
    return runtime.game_over.accepted_epoch != 0 ||
           runtime.run_end_pending_lobby_return;
}

}  // namespace

bool InitializeMultiplayerJoinFlow() {
    std::scoped_lock lock(g_join_flow.mutex);
    ResetStateUnlocked(&g_join_flow);
    if (!ReadEnabledEnvironmentVariable(
            kQuickStartEnvironmentVariable)) {
        return false;
    }

    const auto quick_start_element =
        ReadShortEnvironmentVariable(
            kQuickStartElementEnvironmentVariable);
    const auto quick_start_discipline =
        ReadShortEnvironmentVariable(
            kQuickStartDisciplineEnvironmentVariable);
    if (IsSupportedQuickStartElement(quick_start_element) &&
        IsSupportedQuickStartDiscipline(quick_start_discipline)) {
        g_join_flow.quick_start_element_action_id =
            "create.select_element_" + quick_start_element;
        g_join_flow.quick_start_discipline_action_id =
            "create.select_discipline_" + quick_start_discipline;
        g_join_flow.quick_start_element_id =
            QuickStartElementId(quick_start_element);
        Log(
            "Multiplayer join flow configured stock quick-start loadout. "
            "element=" +
            quick_start_element +
            " discipline=" +
            quick_start_discipline);
    } else if (
        !quick_start_element.empty() ||
        !quick_start_discipline.empty()) {
        Log(
            "Multiplayer join flow ignored an incomplete or unsupported "
            "quick-start loadout.");
    }
    g_join_flow.quick_start_run =
        ReadEnabledEnvironmentVariable(
            kQuickStartRunEnvironmentVariable);
    if (g_join_flow.quick_start_run) {
        Log(
            "Multiplayer join flow configured a native quick-start run "
            "after remote-player materialization.");
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

#include "multiplayer_join_flow/tick_state_machine.inl"

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
        return {
            g_join_flow.main_menu_first_seen_ms != 0,
            {},
        };
    case JoinFlowPhase::PrivateGameplay:
        return {};
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
