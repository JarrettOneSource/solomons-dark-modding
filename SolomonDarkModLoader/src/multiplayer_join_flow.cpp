#include "multiplayer_join_flow.h"

#include "binary_layout.h"
#include "debug_ui_overlay.h"
#include "loading_screen.h"
#include "logger.h"
#include "memory_access.h"
#include "mod_loader.h"
#include "multiplayer_local_transport.h"
#include "multiplayer_runtime_state.h"
#include "x86_hook.h"

#include <Windows.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <limits>
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
constexpr std::size_t kCreateElementPointListOffset = 0x7C;
constexpr std::size_t kCreateDisciplinePointListOffset = 0xA4;
constexpr std::size_t kCreatePointStride = sizeof(float) * 2;
constexpr std::size_t kCreateElementPointCount = 5;
constexpr std::size_t kCreateDisciplinePointCount = 3;
constexpr float kCreateSelectionRadius = 65.0f;
constexpr std::size_t kCreateHookMinimumPatchSize = 5;

enum class JoinFlowPhase {
    Disabled,
    AdvancingMenus,
    PrivateGameplay,
    AwaitingLoadout,
    SelectingLoadout,
    WaitingForHostLoadout,
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
    bool quick_start_loadout_automation_enabled = false;
    bool quick_start_loadout_automation_consumed = false;
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
    std::uintptr_t active_create_owner_address = 0;
    std::uintptr_t create_vftable_address = 0;
    bool create_pick_committed = false;
    std::uint32_t loadout_pick_generation = 1;
    std::uint32_t observed_authority_loadout_generation = 0;
    X86Hook create_tick_hook;
    X86Hook create_click_hook;
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
    case JoinFlowPhase::WaitingForHostLoadout:
        return "waiting_for_host_loadout";
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
    state->quick_start_loadout_automation_enabled = false;
    state->quick_start_loadout_automation_consumed = false;
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
    state->active_create_owner_address = 0;
    state->create_vftable_address = 0;
    state->create_pick_committed = false;
    state->loadout_pick_generation = 1;
    state->observed_authority_loadout_generation = 0;
    state->create_tick_hook = {};
    state->create_click_hook = {};
}

using CreateTickFn = void(__thiscall*)(void* owner);
using CreateClickFn =
    void(__thiscall*)(void* owner, std::int32_t x, std::int32_t y);

bool IsCreateOwner(std::uintptr_t owner_address) {
    if (owner_address == 0 ||
        g_join_flow.create_vftable_address == 0) {
        return false;
    }
    std::uintptr_t vftable = 0;
    return ProcessMemory::Instance().TryReadField(
               owner_address,
               0,
               &vftable) &&
           vftable == g_join_flow.create_vftable_address;
}

bool TryReadCreateSelections(
    std::uintptr_t owner_address,
    std::uint32_t* element_selected,
    std::uint32_t* discipline_selected) {
    if (element_selected == nullptr ||
        discipline_selected == nullptr ||
        !IsCreateOwner(owner_address)) {
        return false;
    }
    auto& memory = ProcessMemory::Instance();
    return memory.TryReadField(
               owner_address,
               kCreateElementSelectedOffset,
               element_selected) &&
           memory.TryReadField(
               owner_address,
               kCreateDisciplineSelectedOffset,
               discipline_selected);
}

bool IsCompletedCreateSelection(std::uint32_t selection, std::uint32_t count) {
    return selection < count;
}

void SetLocalLoadoutPickStateUnlocked(
    multiplayer::LoadoutPickState pick_state) {
    const auto generation = g_join_flow.loadout_pick_generation;
    multiplayer::UpdateRuntimeState(
        [&](multiplayer::RuntimeState& runtime) {
            auto* local =
                multiplayer::UpsertLocalParticipant(runtime);
            if (local == nullptr) {
                return;
            }
            local->loadout_pick_generation = generation;
            local->loadout_pick_state = pick_state;
        });
}

void BeginNextLoadoutGenerationUnlocked(std::string_view source) {
    if (g_join_flow.loadout_pick_generation ==
        (std::numeric_limits<std::uint32_t>::max)()) {
        g_join_flow.loadout_pick_generation = 1;
    } else {
        ++g_join_flow.loadout_pick_generation;
    }
    g_join_flow.create_pick_committed = false;
    g_join_flow.active_create_owner_address = 0;
    g_join_flow.quick_start_element_dispatched = false;
    g_join_flow.quick_start_discipline_dispatched = false;
    g_join_flow.quick_start_loadout_automation_enabled = false;
    SetLocalLoadoutPickStateUnlocked(
        multiplayer::LoadoutPickState::Picking);
    Log(
        "Multiplayer loadout generation advanced. generation=" +
        std::to_string(g_join_flow.loadout_pick_generation) +
        " source=" + std::string(source));
}

const multiplayer::ParticipantInfo* FindAuthorityLoadoutParticipant(
    const multiplayer::RuntimeState& runtime) {
    if (runtime.session_is_host ||
        multiplayer::IsLocalTransportHost()) {
        return multiplayer::FindLocalParticipant(runtime);
    }
    const auto authority_id =
        runtime.steam_host_id != 0
        ? runtime.steam_host_id
        : multiplayer::GetLocalTransportAuthorityParticipantId();
    if (authority_id == 0) {
        return nullptr;
    }
    const auto authority = std::find_if(
        runtime.participants.begin(),
        runtime.participants.end(),
        [&](const multiplayer::ParticipantInfo& participant) {
            return participant.participant_id == authority_id ||
                   participant.steam_id == authority_id;
        });
    return authority == runtime.participants.end()
        ? nullptr
        : &*authority;
}

bool IsAuthorityWorldReadyForCurrentLoadout(
    const multiplayer::RuntimeState& runtime) {
    if (runtime.session_is_host ||
        multiplayer::IsLocalTransportHost()) {
        return true;
    }
    const auto* authority =
        FindAuthorityLoadoutParticipant(runtime);
    return authority != nullptr &&
           authority->loadout_pick_generation ==
               g_join_flow.loadout_pick_generation &&
           authority->loadout_pick_state ==
               multiplayer::LoadoutPickState::WorldReady;
}

void ReconcileAuthorityLoadoutGenerationUnlocked(
    const multiplayer::RuntimeState& runtime) {
    if (runtime.session_is_host ||
        multiplayer::IsLocalTransportHost()) {
        return;
    }
    const auto* authority =
        FindAuthorityLoadoutParticipant(runtime);
    if (authority == nullptr ||
        authority->loadout_pick_generation == 0) {
        return;
    }
    const auto authority_generation =
        authority->loadout_pick_generation;
    if (g_join_flow.observed_authority_loadout_generation == 0) {
        g_join_flow.observed_authority_loadout_generation =
            authority_generation;
        if (authority_generation !=
            g_join_flow.loadout_pick_generation) {
            g_join_flow.loadout_pick_generation =
                authority_generation;
            SetLocalLoadoutPickStateUnlocked(
                g_join_flow.create_pick_committed
                    ? multiplayer::LoadoutPickState::Picked
                    : multiplayer::LoadoutPickState::Picking);
        }
        return;
    }
    if (authority_generation ==
        g_join_flow.observed_authority_loadout_generation) {
        return;
    }

    g_join_flow.observed_authority_loadout_generation =
        authority_generation;
    g_join_flow.loadout_pick_generation = authority_generation;
    g_join_flow.create_pick_committed = false;
    g_join_flow.quick_start_element_dispatched = false;
    g_join_flow.quick_start_discipline_dispatched = false;
    g_join_flow.quick_start_loadout_automation_enabled = false;
    SetLocalLoadoutPickStateUnlocked(
        multiplayer::LoadoutPickState::Picking);
    CancelLoadingScreen();
    Log(
        "Multiplayer client adopted the host's next loadout generation. "
        "generation=" +
        std::to_string(authority_generation));
}

void MarkLocalLoadoutWorldReadyUnlocked() {
    const auto runtime = multiplayer::SnapshotRuntimeState();
    const auto* local =
        multiplayer::FindLocalParticipant(runtime);
    if (local != nullptr &&
        local->loadout_pick_generation ==
            g_join_flow.loadout_pick_generation &&
        local->loadout_pick_state ==
            multiplayer::LoadoutPickState::WorldReady) {
        return;
    }
    SetLocalLoadoutPickStateUnlocked(
        multiplayer::LoadoutPickState::WorldReady);
    Log(
        "Multiplayer loadout world is ready. generation=" +
        std::to_string(g_join_flow.loadout_pick_generation));
}

void ObserveCreateOwnerUnlocked(std::uintptr_t owner_address) {
    if (!IsCreateOwner(owner_address) ||
        owner_address ==
            g_join_flow.active_create_owner_address) {
        return;
    }

    const auto runtime = multiplayer::SnapshotRuntimeState();
    const auto* local =
        multiplayer::FindLocalParticipant(runtime);
    if (local != nullptr &&
        local->loadout_pick_generation ==
            g_join_flow.loadout_pick_generation &&
        local->loadout_pick_state ==
            multiplayer::LoadoutPickState::WorldReady) {
        BeginNextLoadoutGenerationUnlocked(
            "fresh_create_surface");
    }

    g_join_flow.active_create_owner_address = owner_address;
    g_join_flow.create_pick_committed = false;
    g_join_flow.quick_start_element_dispatched = false;
    g_join_flow.quick_start_discipline_dispatched = false;
    g_join_flow.quick_start_loadout_automation_enabled =
        !g_join_flow.quick_start_loadout_automation_consumed &&
        g_join_flow.loadout_pick_generation == 1 &&
        !g_join_flow.quick_start_element_action_id.empty() &&
        !g_join_flow.quick_start_discipline_action_id.empty();
    SetLocalLoadoutPickStateUnlocked(
        multiplayer::LoadoutPickState::Picking);

    std::uint32_t element_selected = kCreateSelectionUnset;
    std::uint32_t discipline_selected = kCreateSelectionUnset;
    if (TryReadCreateSelections(
            owner_address,
            &element_selected,
            &discipline_selected)) {
        Log(
            "Multiplayer loadout picker entered. generation=" +
            std::to_string(g_join_flow.loadout_pick_generation) +
            " preselected_element=" +
            std::to_string(element_selected) +
            " preselected_discipline=" +
            std::to_string(discipline_selected));
    }
}

template <std::size_t PointCount>
bool IsCreatePointHit(
    std::uintptr_t owner_address,
    std::size_t point_list_offset,
    std::int32_t x,
    std::int32_t y) {
    auto& memory = ProcessMemory::Instance();
    for (std::size_t index = 0; index < PointCount; ++index) {
        const auto point_address =
            owner_address + point_list_offset +
            index * kCreatePointStride;
        float point_x = 0.0f;
        float point_y = 0.0f;
        if (!memory.TryReadValue(point_address, &point_x) ||
            !memory.TryReadValue(
                point_address + sizeof(float),
                &point_y) ||
            !std::isfinite(point_x) ||
            !std::isfinite(point_y)) {
            continue;
        }
        const auto delta_x =
            static_cast<float>(x) - point_x;
        const auto delta_y =
            static_cast<float>(y) - point_y;
        if (delta_x * delta_x + delta_y * delta_y <=
            kCreateSelectionRadius * kCreateSelectionRadius) {
            return true;
        }
    }
    return false;
}

void __fastcall HookCreateTick(
    void* owner,
    void* /*unused_edx*/) {
    const auto original = GetX86HookTrampoline<CreateTickFn>(
        g_join_flow.create_tick_hook);
    if (original == nullptr) {
        return;
    }

    const auto owner_address =
        reinterpret_cast<std::uintptr_t>(owner);
    bool discipline_masked = false;
    std::uint32_t retained_discipline =
        kCreateSelectionUnset;
    {
        std::scoped_lock lock(g_join_flow.mutex);
        if (g_join_flow.enabled &&
            IsCreateOwner(owner_address)) {
            ObserveCreateOwnerUnlocked(owner_address);
            const auto runtime =
                multiplayer::SnapshotRuntimeState();
            ReconcileAuthorityLoadoutGenerationUnlocked(runtime);
            const bool gate_world_creation =
                !g_join_flow.create_pick_committed ||
                !IsAuthorityWorldReadyForCurrentLoadout(runtime);
            if (gate_world_creation &&
                ProcessMemory::Instance().TryReadField(
                    owner_address,
                    kCreateDisciplineSelectedOffset,
                    &retained_discipline) &&
                retained_discipline != kCreateSelectionUnset) {
                discipline_masked =
                    ProcessMemory::Instance().TryWriteField(
                        owner_address,
                        kCreateDisciplineSelectedOffset,
                        kCreateSelectionUnset);
            }
        }
    }

    original(owner);

    if (discipline_masked) {
        (void)ProcessMemory::Instance().TryWriteField(
            owner_address,
            kCreateDisciplineSelectedOffset,
            retained_discipline);
    }
}

void __fastcall HookCreateClick(
    void* owner,
    void* /*unused_edx*/,
    std::int32_t x,
    std::int32_t y) {
    const auto original = GetX86HookTrampoline<CreateClickFn>(
        g_join_flow.create_click_hook);
    if (original == nullptr) {
        return;
    }

    const auto owner_address =
        reinterpret_cast<std::uintptr_t>(owner);
    bool valid_selection_attempt = false;
    {
        std::scoped_lock lock(g_join_flow.mutex);
        if (g_join_flow.enabled &&
            IsCreateOwner(owner_address)) {
            ObserveCreateOwnerUnlocked(owner_address);
            std::uint32_t element_selected =
                kCreateSelectionUnset;
            std::uint32_t discipline_selected =
                kCreateSelectionUnset;
            if (TryReadCreateSelections(
                    owner_address,
                    &element_selected,
                    &discipline_selected) &&
                IsCompletedCreateSelection(
                    element_selected,
                    kCreateElementPointCount) &&
                IsCompletedCreateSelection(
                    discipline_selected,
                    kCreateDisciplinePointCount)) {
                if (IsCreatePointHit<kCreateElementPointCount>(
                        owner_address,
                        kCreateElementPointListOffset,
                        x,
                        y)) {
                    valid_selection_attempt =
                        ProcessMemory::Instance().TryWriteField(
                            owner_address,
                            kCreateElementSelectedOffset,
                            kCreateSelectionUnset);
                } else if (
                    IsCreatePointHit<kCreateDisciplinePointCount>(
                        owner_address,
                        kCreateDisciplinePointListOffset,
                        x,
                        y)) {
                    valid_selection_attempt =
                        ProcessMemory::Instance().TryWriteField(
                            owner_address,
                            kCreateDisciplineSelectedOffset,
                            kCreateSelectionUnset);
                }
            } else {
                valid_selection_attempt = true;
            }
        }
    }

    original(owner, x, y);

    std::scoped_lock lock(g_join_flow.mutex);
    if (!g_join_flow.enabled ||
        !valid_selection_attempt ||
        !IsCreateOwner(owner_address)) {
        return;
    }
    std::uint32_t element_selected = kCreateSelectionUnset;
    std::uint32_t discipline_selected = kCreateSelectionUnset;
    if (!TryReadCreateSelections(
            owner_address,
            &element_selected,
            &discipline_selected) ||
        !IsCompletedCreateSelection(
            element_selected,
            kCreateElementPointCount) ||
        !IsCompletedCreateSelection(
            discipline_selected,
            kCreateDisciplinePointCount)) {
        return;
    }

    g_join_flow.create_pick_committed = true;
    g_join_flow.quick_start_loadout_automation_consumed = true;
    g_join_flow.quick_start_loadout_automation_enabled = false;
    SetLocalLoadoutPickStateUnlocked(
        multiplayer::LoadoutPickState::Picked);
    const auto runtime = multiplayer::SnapshotRuntimeState();
    Log(
        "Multiplayer loadout pick committed. generation=" +
        std::to_string(g_join_flow.loadout_pick_generation) +
        " element=" + std::to_string(element_selected) +
        " discipline=" +
        std::to_string(discipline_selected));
    if (!IsAuthorityWorldReadyForCurrentLoadout(runtime)) {
        SetPhaseUnlocked(
            JoinFlowPhase::WaitingForHostLoadout);
    }
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
    if (phase == JoinFlowPhase::PostRun) {
        const auto runtime =
            multiplayer::SnapshotRuntimeState();
        const auto* local =
            multiplayer::FindLocalParticipant(runtime);
        const bool already_entered_next_generation =
            local != nullptr &&
            local->loadout_pick_generation ==
                g_join_flow.loadout_pick_generation &&
            local->loadout_pick_state ==
                multiplayer::LoadoutPickState::Picking;
        if (!already_entered_next_generation) {
            BeginNextLoadoutGenerationUnlocked("game_over");
        }
    }
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
            &dispatch) ||
        dispatch.status == "failed") {
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
    g_join_flow.quick_start_loadout_automation_enabled =
        !g_join_flow.quick_start_loadout_automation_consumed &&
        g_join_flow.loadout_pick_generation == 1 &&
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

bool ResolveJoinFlowAddress(
    const char* key,
    std::uintptr_t* resolved,
    std::string* error_message) {
    std::uintptr_t configured = 0;
    if (resolved == nullptr ||
        !TryGetBinaryLayoutNumericValue(
            "multiplayer.join_flow",
            key,
            &configured) ||
        configured == 0 ||
        !ProcessMemory::Instance().TryResolveGameAddress(
            configured,
            resolved)) {
        if (error_message != nullptr) {
            *error_message =
                "Multiplayer join flow could not resolve [multiplayer.join_flow]." +
                std::string(key) + ".";
        }
        return false;
    }
    return true;
}

}  // namespace

bool InitializeMultiplayerJoinFlow(std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    std::scoped_lock lock(g_join_flow.mutex);
    ResetStateUnlocked(&g_join_flow);
    if (!ReadEnabledEnvironmentVariable(
            kQuickStartEnvironmentVariable)) {
        return true;
    }

    std::uintptr_t create_tick_address = 0;
    std::uintptr_t create_click_address = 0;
    if (!ResolveJoinFlowAddress(
            "create_tick",
            &create_tick_address,
            error_message) ||
        !ResolveJoinFlowAddress(
            "create_click",
            &create_click_address,
            error_message) ||
        !ResolveJoinFlowAddress(
            "create_vftable",
            &g_join_flow.create_vftable_address,
            error_message)) {
        return false;
    }

    std::string hook_error;
    if (!InstallSafeX86Hook(
            reinterpret_cast<void*>(create_tick_address),
            reinterpret_cast<void*>(&HookCreateTick),
            kCreateHookMinimumPatchSize,
            &g_join_flow.create_tick_hook,
            &hook_error)) {
        if (error_message != nullptr) {
            *error_message =
                "Multiplayer join flow could not install the stock Create "
                "tick gate. error=" + hook_error;
        }
        return false;
    }
    if (!InstallSafeX86Hook(
            reinterpret_cast<void*>(create_click_address),
            reinterpret_cast<void*>(&HookCreateClick),
            kCreateHookMinimumPatchSize,
            &g_join_flow.create_click_hook,
            &hook_error)) {
        RemoveX86Hook(&g_join_flow.create_tick_hook);
        if (error_message != nullptr) {
            *error_message =
                "Multiplayer join flow could not install the stock Create "
                "click gate. error=" + hook_error;
        }
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
    SetLocalLoadoutPickStateUnlocked(
        multiplayer::LoadoutPickState::Picking);
    Log("Multiplayer join flow enabled.");
    return true;
}

bool IsMultiplayerJoinFlowEnabled() {
    std::scoped_lock lock(g_join_flow.mutex);
    return g_join_flow.enabled;
}

void ShutdownMultiplayerJoinFlow() {
    bool was_enabled = false;
    {
        std::scoped_lock lock(g_join_flow.mutex);
        was_enabled = g_join_flow.enabled;
        g_join_flow.enabled = false;
    }
    RemoveX86Hook(&g_join_flow.create_click_hook);
    RemoveX86Hook(&g_join_flow.create_tick_hook);
    {
        std::scoped_lock lock(g_join_flow.mutex);
        ResetStateUnlocked(&g_join_flow);
    }
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
