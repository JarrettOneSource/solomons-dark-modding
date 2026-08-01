#pragma once

#include <cstdint>
#include <filesystem>
#include <string>

namespace sdmod {

enum class LoadingScreenFlow {
    SinglePlayer,
    MultiplayerHost,
    MultiplayerJoin,
};

enum class LoadingScreenStage {
    ConnectingTransport,
    CreatingLobby,
    JoiningLobby,
    AuthenticatingSession,
    EstablishingRoute,
    SynchronizingHostSettings,
    ReceivingHostCheckpoint,
    PreparingHost,
    ReceivingRunPlan,
    PreparingBoneyard,
    GeneratingBoneyard,
    SerializingBoneyard,
    ReadingBoneyard,
    MaterializingWorld,
    ReceivingWorldCheckpoint,
    ReceivingWaveCheckpoint,
    MaterializingParticipants,
    WaitingForParticipants,
    ConfirmingParticipants,
    GameplayReady,
};

struct LoadingScreenSnapshot {
    bool active = false;
    bool progress_bar_visible = true;
    LoadingScreenFlow flow = LoadingScreenFlow::SinglePlayer;
    LoadingScreenStage stage = LoadingScreenStage::PreparingBoneyard;
    float progress = 0.0f;
    std::uint64_t sequence = 0;
    std::uint64_t started_ms = 0;
    std::string stage_id;
    std::string label;
};

bool InitializeLoadingScreen(
    std::uintptr_t device_pointer_global,
    const std::filesystem::path& background_path,
    std::string* error_message);
void ShutdownLoadingScreen();

void BeginLoadingScreen(
    LoadingScreenFlow flow,
    LoadingScreenStage stage);
void BeginLoadingScreenBarrier(
    LoadingScreenFlow flow,
    std::string stage_id,
    std::string label);
void BeginBoneyardLoadingScreen();
void AdvanceLoadingScreen(LoadingScreenStage stage);
void NotifyBoneyardGameplayStarted();
void CompleteLoadingScreen();
void CancelLoadingScreen();
LoadingScreenSnapshot GetLoadingScreenSnapshot();

}  // namespace sdmod
