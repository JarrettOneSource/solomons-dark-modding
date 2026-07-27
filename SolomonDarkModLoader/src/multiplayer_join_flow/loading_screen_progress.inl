const multiplayer::ParticipantInfo* FindAuthorityParticipantForLoading(
    const multiplayer::RuntimeState& runtime) {
    if (runtime.session_is_host) {
        return multiplayer::FindLocalParticipant(runtime);
    }
    const auto authority_participant_id =
        runtime.steam_host_id != 0
        ? runtime.steam_host_id
        : multiplayer::GetLocalTransportAuthorityParticipantId();
    if (authority_participant_id == 0) {
        return nullptr;
    }
    const auto authority = std::find_if(
        runtime.participants.begin(),
        runtime.participants.end(),
        [&](const multiplayer::ParticipantInfo& participant) {
            return participant.participant_id ==
                       authority_participant_id ||
                   participant.steam_id ==
                       authority_participant_id;
        });
    return authority == runtime.participants.end()
        ? nullptr
        : &*authority;
}

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
        if (runtime.session_is_host) {
            if (runtime.session_status ==
                multiplayer::SessionStatus::CreatingLobby) {
                AdvanceLoadingScreen(
                    LoadingScreenStage::CreatingLobby);
                return;
            }
            if (runtime.session_status ==
                multiplayer::SessionStatus::Handshaking) {
                AdvanceLoadingScreen(
                    LoadingScreenStage::AuthenticatingSession);
                return;
            }
            if (runtime.session_status !=
                multiplayer::SessionStatus::Ready) {
                return;
            }
            AdvanceLoadingScreen(
                LoadingScreenStage::PreparingHost);
            if (IsHostCharacterReady(runtime)) {
                AdvanceLoadingScreen(
                    LoadingScreenStage::MaterializingParticipants);
            }
            return;
        }

        if (runtime.session_status ==
            multiplayer::SessionStatus::JoiningLobby) {
            AdvanceLoadingScreen(
                LoadingScreenStage::JoiningLobby);
            return;
        }
        if (runtime.session_status ==
            multiplayer::SessionStatus::Handshaking) {
            AdvanceLoadingScreen(
                LoadingScreenStage::AuthenticatingSession);
            return;
        }
        if (runtime.session_status ==
                multiplayer::SessionStatus::Ready) {
            AdvanceLoadingScreen(
                LoadingScreenStage::EstablishingRoute);
        } else {
            return;
        }
        if (!runtime.transport_route_ready) {
            return;
        }
        AdvanceLoadingScreen(
            LoadingScreenStage::SynchronizingHostSettings);
        if (!runtime.host_settings_checkpoint_received) {
            return;
        }
        AdvanceLoadingScreen(
            LoadingScreenStage::ReceivingHostCheckpoint);
        const auto* authority =
            FindAuthorityParticipantForLoading(runtime);
        if (authority == nullptr ||
            !authority->runtime.valid) {
            return;
        }
        if (authority->runtime.scene_intent.kind ==
                multiplayer::ParticipantSceneIntentKind::Run &&
            authority->runtime.run_nonce != 0) {
            AdvanceLoadingScreen(
                LoadingScreenStage::ReceivingRunPlan);
        } else if (IsHostCharacterReady(runtime)) {
            AdvanceLoadingScreen(
                LoadingScreenStage::MaterializingParticipants);
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
    const auto run_nonce =
        local == nullptr ? 0 : local->runtime.run_nonce;
    const bool world_checkpoint_ready =
        !runtime.session_is_host &&
        run_nonce != 0 &&
        runtime.world_snapshot.valid &&
        runtime.world_snapshot.run_nonce == run_nonce;
    if (world_checkpoint_ready) {
        AdvanceLoadingScreen(
            LoadingScreenStage::ReceivingWorldCheckpoint);
    }
    if (world_checkpoint_ready &&
        runtime.host_wave_checkpoint_run_nonce == run_nonce) {
        AdvanceLoadingScreen(
            LoadingScreenStage::ReceivingWaveCheckpoint);
    }
}
