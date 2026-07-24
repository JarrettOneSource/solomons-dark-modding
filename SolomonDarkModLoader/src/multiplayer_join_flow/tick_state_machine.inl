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
    const bool tutorial_ready = IsTutorialReady(scene);
    const bool boneyard_ready = IsBoneyardReady(scene);
    const bool private_gameplay_ready =
        IsPrivateGameplayReady(scene);

    DebugUiSurfaceSnapshot current_snapshot;
    const bool snapshot_available =
        TryGetLatestDebugUiSurfaceSnapshot(&current_snapshot);
    const auto* snapshot =
        snapshot_available ? &current_snapshot : nullptr;

    switch (g_join_flow.phase) {
    case JoinFlowPhase::AdvancingMenus:
        if (boneyard_ready) {
            ClearPendingActionUnlocked();
            SetPhaseUnlocked(JoinFlowPhase::Run);
            return;
        }
        if (hub_ready) {
            ClearPendingActionUnlocked();
            SetPhaseUnlocked(JoinFlowPhase::Connecting);
            return;
        }
        if (private_gameplay_ready) {
            ClearPendingActionUnlocked();
            SetPhaseUnlocked(JoinFlowPhase::PrivateGameplay);
            return;
        }
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
        if (snapshot->surface_id == "control_scheme_picker" &&
            HasAction(
                *snapshot,
                "control_scheme_picker.select_wasd")) {
            (void)QueueActionUnlocked(
                *snapshot,
                "control_scheme_picker.select_wasd",
                now_ms);
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

    case JoinFlowPhase::BypassingTutorial:
        if (hub_ready) {
            SetPhaseUnlocked(JoinFlowPhase::Connecting);
        } else if (boneyard_ready) {
            SetPhaseUnlocked(JoinFlowPhase::Run);
        } else if (private_gameplay_ready) {
            SetPhaseUnlocked(JoinFlowPhase::PrivateGameplay);
        } else if (
            !tutorial_ready &&
            snapshot != nullptr &&
            snapshot->surface_id != "control_scheme_picker" &&
            snapshot->captured_at_milliseconds >
                g_join_flow.phase_entered_ms) {
            g_join_flow.main_menu_first_seen_ms = 0;
            SetPhaseUnlocked(JoinFlowPhase::AdvancingMenus);
        }
        return;

    case JoinFlowPhase::PrivateGameplay:
        if (boneyard_ready) {
            SetPhaseUnlocked(JoinFlowPhase::Run);
        } else if (hub_ready) {
            SetPhaseUnlocked(JoinFlowPhase::Connecting);
        } else if (
            !private_gameplay_ready &&
            snapshot != nullptr &&
            snapshot->captured_at_milliseconds >
                g_join_flow.phase_entered_ms) {
            g_join_flow.main_menu_first_seen_ms = 0;
            g_join_flow.action_retry_not_before_ms = 0;
            SetPhaseUnlocked(JoinFlowPhase::AdvancingMenus);
        }
        return;

    case JoinFlowPhase::AwaitingLoadout:
        if (snapshot != nullptr &&
            snapshot->surface_id == "create") {
            EnterLoadoutSelectionUnlocked(scene);
        } else if (private_gameplay_ready) {
            SetPhaseUnlocked(JoinFlowPhase::PrivateGameplay);
        } else if (hub_ready) {
            SetPhaseUnlocked(JoinFlowPhase::Connecting);
        } else if (boneyard_ready) {
            SetPhaseUnlocked(JoinFlowPhase::Run);
        }
        return;

    case JoinFlowPhase::SelectingLoadout:
        if (!HasLoadoutSelectionFinished(scene, now_ms)) {
            if (!ResolvePendingActionUnlocked(snapshot, now_ms)) {
                return;
            }
            if (snapshot == nullptr ||
                snapshot->surface_id != "create" ||
                g_join_flow.quick_start_element_action_id.empty() ||
                g_join_flow.quick_start_discipline_action_id.empty()) {
                return;
            }
            std::uint32_t element_enabled = 0;
            std::uint32_t element_selected = kCreateSelectionUnset;
            std::uint32_t discipline_enabled = 0;
            std::uint32_t discipline_selected = kCreateSelectionUnset;
            if (!TryReadCreateSelectionState(
                    snapshot,
                    &element_enabled,
                    &element_selected,
                    &discipline_enabled,
                    &discipline_selected)) {
                return;
            }
            if (!g_join_flow.quick_start_element_dispatched) {
                if ((element_enabled & 0xFFu) != 0 &&
                    element_selected == kCreateSelectionUnset &&
                    HasAction(
                        *snapshot,
                        g_join_flow.quick_start_element_action_id)) {
                    (void)QueueActionUnlocked(
                        *snapshot,
                        g_join_flow.quick_start_element_action_id,
                        now_ms);
                }
                return;
            }
            if (!g_join_flow.quick_start_discipline_dispatched &&
                (discipline_enabled & 0xFFu) != 0 &&
                element_selected == g_join_flow.quick_start_element_id &&
                discipline_selected == kCreateSelectionUnset &&
                HasAction(
                    *snapshot,
                    g_join_flow.quick_start_discipline_action_id)) {
                (void)QueueActionUnlocked(
                    *snapshot,
                    g_join_flow.quick_start_discipline_action_id,
                    now_ms);
            }
            return;
        }
        if (private_gameplay_ready) {
            SetPhaseUnlocked(JoinFlowPhase::PrivateGameplay);
        } else {
            SetPhaseUnlocked(JoinFlowPhase::Connecting);
        }
        return;

    case JoinFlowPhase::Connecting:
        if (private_gameplay_ready) {
            SetPhaseUnlocked(JoinFlowPhase::PrivateGameplay);
            return;
        }
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
                multiplayer::SessionStatus::Ready &&
            IsHostCharacterReady(runtime)) {
            SetPhaseUnlocked(JoinFlowPhase::Hub);
        }
        return;

    case JoinFlowPhase::Hub:
        if (boneyard_ready) {
            SetPhaseUnlocked(JoinFlowPhase::Run);
        } else if (IsRunRequested(runtime)) {
            SetPhaseUnlocked(JoinFlowPhase::LoadingBoneyard);
        } else if (
            g_join_flow.quick_start_run &&
            !g_join_flow.quick_start_run_requested &&
            runtime.session_is_host &&
            HasMaterializedRemoteCharacter(runtime)) {
            if (g_join_flow.quick_start_run_ready_since_ms == 0) {
                g_join_flow.quick_start_run_ready_since_ms = now_ms;
                Log(
                    "Multiplayer join flow armed the native quick-start "
                    "run after remote-player materialization.");
                return;
            }
            if (now_ms <
                g_join_flow.quick_start_run_ready_since_ms +
                    kQuickStartRunMaterializedDelayMs) {
                return;
            }

            std::string error_message;
            if (QueueHubStartTestrun(&error_message)) {
                g_join_flow.quick_start_run_requested = true;
                g_join_flow.quick_start_run_last_error.clear();
                Log(
                    "Multiplayer join flow requested the native "
                    "quick-start run.");
            } else if (
                error_message !=
                g_join_flow.quick_start_run_last_error) {
                g_join_flow.quick_start_run_last_error =
                    error_message;
                Log(
                    "Multiplayer join flow is waiting to request the "
                    "native quick-start run. error=" +
                    error_message);
            }
        } else if (
            g_join_flow.quick_start_run &&
            !g_join_flow.quick_start_run_requested) {
            g_join_flow.quick_start_run_ready_since_ms = 0;
            g_join_flow.quick_start_run_last_error.clear();
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
