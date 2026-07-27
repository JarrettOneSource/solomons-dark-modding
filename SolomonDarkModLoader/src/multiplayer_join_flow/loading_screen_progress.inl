void UpdateLoadingScreenForPhase(JoinFlowPhase phase) {
    switch (phase) {
    case JoinFlowPhase::Connecting:
        BeginLoadingScreen(
            multiplayer::IsLocalTransportHost()
                ? LoadingScreenFlow::MultiplayerHost
                : LoadingScreenFlow::MultiplayerJoin,
            LoadingScreenStage::ConnectingTransport);
        break;
    case JoinFlowPhase::LoadingBoneyard:
        BeginLoadingScreen(
            multiplayer::IsLocalTransportHost()
                ? LoadingScreenFlow::MultiplayerHost
                : LoadingScreenFlow::MultiplayerJoin,
            LoadingScreenStage::ReceivingRunPlan);
        break;
    case JoinFlowPhase::Hub:
    case JoinFlowPhase::Run:
    case JoinFlowPhase::PrivateGameplay:
        CompleteLoadingScreen();
        break;
    case JoinFlowPhase::Failed:
    case JoinFlowPhase::PostRun:
        CancelLoadingScreen();
        break;
    default:
        break;
    }
}

void UpdateLoadingScreenForRuntime(
    JoinFlowPhase phase,
    const multiplayer::RuntimeState& runtime) {
    if (phase == JoinFlowPhase::Connecting) {
        if (runtime.transport_ready) {
            AdvanceLoadingScreen(
                LoadingScreenStage::EstablishingSession);
        }
        if (runtime.session_status ==
            multiplayer::SessionStatus::Ready) {
            AdvanceLoadingScreen(
                LoadingScreenStage::WaitingForHost);
        }
        return;
    }
    if (phase != JoinFlowPhase::LoadingBoneyard) {
        return;
    }

    const auto* local =
        multiplayer::FindLocalParticipant(runtime);
    if (local != nullptr && local->runtime.run_nonce != 0) {
        AdvanceLoadingScreen(
            LoadingScreenStage::ReceivingRunPlan);
    }
    if (runtime.run_loading_barrier.active) {
        AdvanceLoadingScreen(
            LoadingScreenStage::WaitingForParticipants);
    }
    if (runtime.run_loading_barrier.local_mutual_visibility) {
        AdvanceLoadingScreen(
            LoadingScreenStage::ConfirmingParticipants);
    }
}
