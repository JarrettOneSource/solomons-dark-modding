#include "loading_screen.h"

#include "binary_layout.h"
#include "gameplay_seams.h"
#include "loading_screen_internal.h"
#include "logger.h"
#include "memory_access.h"
#include "mod_loader.h"
#include "multiplayer_local_transport.h"
#include "x86_hook.h"

#include <Windows.h>

#include <array>
#include <cstdint>
#include <mutex>
#include <sstream>
#include <string>

namespace sdmod {
namespace {

struct StageDefinition {
    LoadingScreenStage stage;
    const char* id;
    const char* label;
    float progress;
};

constexpr std::array<StageDefinition, 20> kStageDefinitions = {{
    {LoadingScreenStage::ConnectingTransport,
     "connecting_transport", "Waking the multiplayer transport...", 0.44f},
    {LoadingScreenStage::CreatingLobby,
     "creating_lobby", "Opening the coven...", 0.48f},
    {LoadingScreenStage::JoiningLobby,
     "joining_lobby", "Entering the Steam lobby...", 0.48f},
    {LoadingScreenStage::AuthenticatingSession,
     "authenticating_session", "Proving your sigil to the host...", 0.52f},
    {LoadingScreenStage::EstablishingRoute,
     "establishing_route", "Opening the route...", 0.56f},
    {LoadingScreenStage::SynchronizingHostSettings,
     "synchronizing_host_settings", "Receiving the host's settings...", 0.60f},
    {LoadingScreenStage::ReceivingHostCheckpoint,
     "receiving_host_checkpoint", "Receiving the host's checkpoint...", 0.66f},
    {LoadingScreenStage::PreparingHost,
     "preparing_host", "Preparing the host...", 0.66f},
    {LoadingScreenStage::ReceivingRunPlan,
     "receiving_run_plan", "Receiving the host's boneyard...", 0.70f},
    {LoadingScreenStage::PreparingBoneyard,
     "preparing_boneyard", "Preparing the boneyard...", 0.73f},
    {LoadingScreenStage::GeneratingBoneyard,
     "generating_boneyard", "Raising the boneyard...", 0.77f},
    {LoadingScreenStage::SerializingBoneyard,
     "serializing_boneyard", "Sealing the boneyard...", 0.80f},
    {LoadingScreenStage::ReadingBoneyard,
     "reading_boneyard", "Loading the boneyard...", 0.83f},
    {LoadingScreenStage::MaterializingWorld,
     "materializing_world", "Awakening the world...", 0.87f},
    {LoadingScreenStage::ReceivingWorldCheckpoint,
     "receiving_world_checkpoint", "Receiving the living world...", 0.90f},
    {LoadingScreenStage::ReceivingWaveCheckpoint,
     "receiving_wave_checkpoint", "Aligning the host's wave...", 0.91f},
    {LoadingScreenStage::MaterializingParticipants,
     "materializing_participants", "Gathering the coven...", 0.92f},
    {LoadingScreenStage::WaitingForParticipants,
     "waiting_for_participants", "Waiting for the coven...", 0.95f},
    {LoadingScreenStage::ConfirmingParticipants,
     "confirming_participants", "Binding the coven...", 0.98f},
    {LoadingScreenStage::GameplayReady,
     "gameplay_ready", "Entering the boneyard...", 1.0f},
}};

constexpr std::size_t kArenaStartHook = 0;
constexpr std::size_t kBoneyardLoaderHook = 1;
constexpr std::size_t kProceduralCreateSaveHook = 2;
constexpr std::size_t kBoneyardGeneratorHook = 3;
constexpr std::size_t kBoneyardMaterializeHook = 4;
constexpr std::size_t kNativeStageHookCount = 5;
constexpr std::int16_t kArenaRegionIndex = 5;

struct LoadingScreenState {
    std::mutex mutex;
    LoadingScreenSnapshot snapshot;
    std::array<X86Hook, kNativeStageHookCount> hooks{};
    bool initialized = false;
};

LoadingScreenState g_loading_screen;
thread_local std::uint32_t g_generator_hook_depth = 0;
std::uintptr_t g_pending_level_kind_address = 0;

const StageDefinition& DefinitionFor(LoadingScreenStage stage) {
    for (const auto& definition : kStageDefinitions) {
        if (definition.stage == stage) {
            return definition;
        }
    }
    return kStageDefinitions[0];
}

const char* FlowId(LoadingScreenFlow flow) {
    switch (flow) {
    case LoadingScreenFlow::MultiplayerHost:
        return "multiplayer_host";
    case LoadingScreenFlow::MultiplayerJoin:
        return "multiplayer_join";
    case LoadingScreenFlow::SinglePlayer:
    default:
        return "single_player";
    }
}

LoadingScreenFlow CurrentFlow() {
    if (multiplayer::IsLocalTransportHost()) {
        return LoadingScreenFlow::MultiplayerHost;
    }
    if (multiplayer::IsLocalTransportClient()) {
        return LoadingScreenFlow::MultiplayerJoin;
    }
    return LoadingScreenFlow::SinglePlayer;
}

using ArenaStartFn = void(__fastcall*)(void* arena);
using BoneyardLoaderFn =
    void(__thiscall*)(
        void* arena,
        std::uintptr_t path_word_0,
        std::uintptr_t path_word_1,
        std::uintptr_t path_word_2,
        std::uintptr_t path_word_3,
        std::uintptr_t path_word_4,
        std::uintptr_t path_word_5,
        std::uintptr_t path_word_6);
using ProceduralCreateSaveFn =
    void(__thiscall*)(
        void* arena,
        std::uintptr_t path_word_0,
        std::uintptr_t path_word_1,
        std::uintptr_t path_word_2,
        std::uintptr_t path_word_3,
        std::uintptr_t path_word_4,
        std::uintptr_t path_word_5,
        std::uintptr_t path_word_6);
using BoneyardGeneratorFn =
    void(__thiscall*)(void* generator, void* arena);
using BoneyardMaterializeFn =
    void(__fastcall*)(void* region_layout);

bool IsArenaRegion(void* region) {
    std::int16_t region_index = -1;
    return region != nullptr &&
        kActorWorldRegionIndexOffset != 0 &&
        ProcessMemory::Instance().TryReadField(
            reinterpret_cast<std::uintptr_t>(region),
            kActorWorldRegionIndexOffset,
            &region_index) &&
        region_index == kArenaRegionIndex;
}

void __fastcall HookArenaStart(
    void* arena,
    void* /*unused_edx*/) {
    const auto original = GetX86HookTrampoline<ArenaStartFn>(
        g_loading_screen.hooks[kArenaStartHook]);
    if (original == nullptr) {
        return;
    }

    const bool is_boneyard = IsArenaRegion(arena);
    if (is_boneyard) {
        BeginBoneyardLoadingScreen();
    }
    original(arena);
    if (is_boneyard) {
        NotifyBoneyardGameplayStarted();
    }
}

void __fastcall HookBoneyardLoader(
    void* arena,
    void* /*unused_edx*/,
    std::uintptr_t path_word_0,
    std::uintptr_t path_word_1,
    std::uintptr_t path_word_2,
    std::uintptr_t path_word_3,
    std::uintptr_t path_word_4,
    std::uintptr_t path_word_5,
    std::uintptr_t path_word_6) {
    const auto original =
        GetX86HookTrampoline<BoneyardLoaderFn>(
            g_loading_screen.hooks[kBoneyardLoaderHook]);
    if (original == nullptr) {
        return;
    }

    std::int32_t pending_level_kind = 0;
    if (g_pending_level_kind_address == 0 ||
        !ProcessMemory::Instance().TryReadValue(
            g_pending_level_kind_address,
            &pending_level_kind) ||
        pending_level_kind != 1) {
        AdvanceLoadingScreen(LoadingScreenStage::ReadingBoneyard);
    }
    detail::PresentLoadingScreenFrame();
    original(
        arena,
        path_word_0,
        path_word_1,
        path_word_2,
        path_word_3,
        path_word_4,
        path_word_5,
        path_word_6);
}

void __fastcall HookProceduralCreateSave(
    void* arena,
    void* /*unused_edx*/,
    std::uintptr_t path_word_0,
    std::uintptr_t path_word_1,
    std::uintptr_t path_word_2,
    std::uintptr_t path_word_3,
    std::uintptr_t path_word_4,
    std::uintptr_t path_word_5,
    std::uintptr_t path_word_6) {
    const auto original =
        GetX86HookTrampoline<ProceduralCreateSaveFn>(
            g_loading_screen.hooks[kProceduralCreateSaveHook]);
    if (original == nullptr) {
        return;
    }

    BeginBoneyardLoadingScreen();
    AdvanceLoadingScreen(LoadingScreenStage::GeneratingBoneyard);
    detail::PresentLoadingScreenFrame();
    original(
        arena,
        path_word_0,
        path_word_1,
        path_word_2,
        path_word_3,
        path_word_4,
        path_word_5,
        path_word_6);
    AdvanceLoadingScreen(LoadingScreenStage::ReadingBoneyard);
    detail::PresentLoadingScreenFrame();
}

void __fastcall HookBoneyardGenerator(
    void* generator,
    void* /*unused_edx*/,
    void* arena) {
    const auto original =
        GetX86HookTrampoline<BoneyardGeneratorFn>(
            g_loading_screen.hooks[kBoneyardGeneratorHook]);
    if (original == nullptr) {
        return;
    }

    const bool outermost = g_generator_hook_depth++ == 0;
    if (outermost) {
        AdvanceLoadingScreen(LoadingScreenStage::GeneratingBoneyard);
        detail::PresentLoadingScreenFrame();
    }
    original(generator, arena);
    if (--g_generator_hook_depth == 0) {
        AdvanceLoadingScreen(LoadingScreenStage::SerializingBoneyard);
        detail::PresentLoadingScreenFrame();
    }
}

void __fastcall HookBoneyardMaterialize(
    void* region_layout,
    void* /*unused_edx*/) {
    const auto original =
        GetX86HookTrampoline<BoneyardMaterializeFn>(
            g_loading_screen.hooks[kBoneyardMaterializeHook]);
    if (original == nullptr) {
        return;
    }

    AdvanceLoadingScreen(LoadingScreenStage::MaterializingWorld);
    detail::PresentLoadingScreenFrame();
    original(region_layout);
    if (!multiplayer::IsLocalTransportClient()) {
        AdvanceLoadingScreen(
            LoadingScreenStage::MaterializingParticipants);
        detail::PresentLoadingScreenFrame();
    }
}

bool ResolveLayoutAddress(
    const char* section,
    const char* key,
    std::uintptr_t* resolved,
    std::string* error_message) {
    std::uintptr_t configured = 0;
    if (!TryGetBinaryLayoutNumericValue(
            section,
            key,
            &configured) ||
        configured == 0) {
        *error_message =
            "Binary layout is missing [" +
            std::string(section) + "]." +
            std::string(key) + ".";
        return false;
    }

    *resolved =
        ProcessMemory::Instance().ResolveGameAddressOrZero(configured);
    if (*resolved == 0) {
        *error_message =
            "Could not resolve loading-screen address " +
            std::string(key) + " at " + HexString(configured) + ".";
        return false;
    }
    return true;
}

}  // namespace

bool InitializeLoadingScreen(
    std::uintptr_t device_pointer_global,
    const std::filesystem::path& background_path,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (error_message == nullptr) {
        return false;
    }
    {
        std::scoped_lock lock(g_loading_screen.mutex);
        if (g_loading_screen.initialized) {
            return true;
        }
    }

    std::array<std::uintptr_t, kNativeStageHookCount> targets{};
    const std::array<const char*, kNativeStageHookCount> keys = {
        "arena_start_run_dispatch",
        "boneyard_loader",
        "boneyard_procedural_create_save",
        "boneyard_generator",
        "boneyard_materialize",
    };
    for (std::size_t index = 0; index < keys.size(); ++index) {
        if (!ResolveLayoutAddress(
                "gameplay.hooks",
                keys[index],
                &targets[index],
                error_message)) {
            return false;
        }
    }
    if (!ResolveLayoutAddress(
            "gameplay.globals",
            "pending_level_kind",
            &g_pending_level_kind_address,
            error_message)) {
        return false;
    }

    const std::array<void*, kNativeStageHookCount> detours = {
        reinterpret_cast<void*>(&HookArenaStart),
        reinterpret_cast<void*>(&HookBoneyardLoader),
        reinterpret_cast<void*>(&HookProceduralCreateSave),
        reinterpret_cast<void*>(&HookBoneyardGenerator),
        reinterpret_cast<void*>(&HookBoneyardMaterialize),
    };
    const std::array<std::size_t, kNativeStageHookCount> patch_sizes = {
        7, 7, 7, 6, 7,
    };
    std::array<HookSpec, kNativeStageHookCount> specs{};
    for (std::size_t index = 0; index < specs.size(); ++index) {
        specs[index] = {
            reinterpret_cast<void*>(targets[index]),
            patch_sizes[index],
            detours[index],
            keys[index],
        };
    }
    if (!InstallHookSet(
            specs.data(),
            specs.size(),
            g_loading_screen.hooks.data(),
            error_message)) {
        g_pending_level_kind_address = 0;
        return false;
    }

    if (!detail::StartLoadingScreenRenderer(
            device_pointer_global,
            background_path,
            error_message)) {
        RemoveHookSet(
            g_loading_screen.hooks.data(),
            g_loading_screen.hooks.size());
        g_pending_level_kind_address = 0;
        return false;
    }

    {
        std::scoped_lock lock(g_loading_screen.mutex);
        g_loading_screen.initialized = true;
    }
    std::ostringstream line;
    line << "Loading screen initialized. background="
         << background_path.string();
    for (std::size_t index = 0; index < keys.size(); ++index) {
        line << ' ' << keys[index] << '=' << HexString(targets[index]);
    }
    Log(line.str());
    return true;
}

void ShutdownLoadingScreen() {
    detail::StopLoadingScreenRenderer();
    RemoveHookSet(
        g_loading_screen.hooks.data(),
        g_loading_screen.hooks.size());
    std::scoped_lock lock(g_loading_screen.mutex);
    g_loading_screen.snapshot = {};
    g_loading_screen.initialized = false;
    g_pending_level_kind_address = 0;
}

void BeginLoadingScreen(
    LoadingScreenFlow flow,
    LoadingScreenStage stage) {
    const auto& definition = DefinitionFor(stage);
    bool started = false;
    bool advanced = false;
    LoadingScreenSnapshot snapshot;
    {
        std::scoped_lock lock(g_loading_screen.mutex);
        auto& current = g_loading_screen.snapshot;
        if (!current.active) {
            current.active = true;
            current.flow = flow;
            current.progress = 0.0f;
            current.sequence += 1;
            current.started_ms =
                static_cast<std::uint64_t>(GetTickCount64());
            started = true;
        }
        if (current.stage_id.empty() ||
            definition.progress > current.progress) {
            current.stage = stage;
            current.progress = definition.progress;
            current.stage_id = definition.id;
            current.label = definition.label;
            advanced = true;
        }
        snapshot = current;
    }

    if (started) {
        Log(
            "Loading screen started. sequence=" +
            std::to_string(snapshot.sequence) +
            " flow=" + FlowId(snapshot.flow));
    }
    if (advanced) {
        Log(
            "Loading screen stage. sequence=" +
            std::to_string(snapshot.sequence) +
            " stage=" + snapshot.stage_id +
            " progress=" +
            std::to_string(snapshot.progress));
    }
}

void BeginBoneyardLoadingScreen() {
    BeginLoadingScreen(
        CurrentFlow(),
        LoadingScreenStage::PreparingBoneyard);
}

void AdvanceLoadingScreen(LoadingScreenStage stage) {
    const auto snapshot = GetLoadingScreenSnapshot();
    if (!snapshot.active) {
        return;
    }
    BeginLoadingScreen(snapshot.flow, stage);
}

void NotifyBoneyardGameplayStarted() {
    if (!multiplayer::IsLocalTransportClient()) {
        AdvanceLoadingScreen(
            LoadingScreenStage::MaterializingParticipants);
    }
    if (!multiplayer::IsLocalTransportHost() &&
        !multiplayer::IsLocalTransportClient()) {
        CompleteLoadingScreen();
    }
}

void CompleteLoadingScreen() {
    LoadingScreenSnapshot completed;
    {
        std::scoped_lock lock(g_loading_screen.mutex);
        if (!g_loading_screen.snapshot.active) {
            return;
        }
        const auto& definition =
            DefinitionFor(LoadingScreenStage::GameplayReady);
        g_loading_screen.snapshot.stage =
            LoadingScreenStage::GameplayReady;
        g_loading_screen.snapshot.progress = definition.progress;
        g_loading_screen.snapshot.stage_id = definition.id;
        g_loading_screen.snapshot.label = definition.label;
        completed = g_loading_screen.snapshot;
        g_loading_screen.snapshot.active = false;
    }
    const auto elapsed_ms =
        static_cast<std::uint64_t>(GetTickCount64()) -
        completed.started_ms;
    Log(
        "Loading screen completed. sequence=" +
        std::to_string(completed.sequence) +
        " elapsed_ms=" + std::to_string(elapsed_ms));
}

void CancelLoadingScreen() {
    LoadingScreenSnapshot canceled;
    {
        std::scoped_lock lock(g_loading_screen.mutex);
        if (!g_loading_screen.snapshot.active) {
            return;
        }
        canceled = g_loading_screen.snapshot;
        g_loading_screen.snapshot.active = false;
    }
    Log(
        "Loading screen canceled. sequence=" +
        std::to_string(canceled.sequence) +
        " stage=" + canceled.stage_id);
}

LoadingScreenSnapshot GetLoadingScreenSnapshot() {
    std::scoped_lock lock(g_loading_screen.mutex);
    return g_loading_screen.snapshot;
}

}  // namespace sdmod
