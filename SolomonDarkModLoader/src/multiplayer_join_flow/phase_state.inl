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
