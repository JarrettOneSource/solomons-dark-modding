"""Persistent-lobby and run-loading readiness contracts."""

from __future__ import annotations

from pathlib import Path

from static_re_contract_support import ROOT


def _read(relative_path: str) -> str:
    return (ROOT / Path(relative_path)).read_text(encoding="utf-8")


def _require_tokens(source: str, tokens: tuple[str, ...], owner: str) -> None:
    for token in tokens:
        assert token in source, f"{owner} lacks: {token}"


def _require_in_order(source: str, *tokens: str) -> None:
    cursor = -1
    for token in tokens:
        index = source.find(token, cursor + 1)
        assert index >= 0, f"ordered lifecycle contract lacks: {token}"
        cursor = index


def test_match_end_preserves_lobby_and_reports_explicit_activity_state() -> str:
    labels = _read(
        "SolomonDarkModLoader/src/multiplayer_runtime_labels.cpp"
    )
    local_state = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "local_state_packet_sync.inl"
    )
    runtime_state = _read(
        "SolomonDarkModLoader/include/multiplayer_runtime_effect_state.inl"
    )
    transport = _read("SolomonDarkModLoader/src/multiplayer_local_transport.cpp")
    join_flow = _read(
        "SolomonDarkModLoader/src/multiplayer_join_flow/tick_state_machine.inl"
    )
    join_flow_state = _read(
        "SolomonDarkModLoader/src/multiplayer_join_flow.cpp"
    ) + _read(
        "SolomonDarkModLoader/src/multiplayer_join_flow/loadout_picker.inl"
    ) + _read(
        "SolomonDarkModLoader/src/multiplayer_join_flow/phase_state.inl"
    )
    debug_ui_header = _read(
        "SolomonDarkModLoader/include/debug_ui_overlay.h"
    )
    debug_ui_actions = _read(
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "public_api_actions.inl"
    )
    steam_status = _read(
        "SolomonDarkModLoader/src/multiplayer_steam_session/"
        "lobby_and_events.inl"
    )
    startup_status = _read("SolomonDarkModLoader/src/startup_status.cpp")
    launcher_status = _read(
        "SolomonDarkModLauncher/src/Launch/"
        "MultiplayerSessionStatusMonitor.cs"
    )
    launcher_view = _read(
        "SolomonDarkModLauncher.UI/src/ViewModels/MainWindowViewModel.cs"
    )
    directory_publisher = _read(
        "SolomonDarkModLauncher/src/Launch/"
        "LobbyDirectoryPublisher.cs"
    )
    native_note = _read(
        "docs/reverse-engineering/native-game-over-session-semantics.md"
    )
    native_web_combat_note = _read(
        "docs/reverse-engineering/native-web-combat-lifecycle.md"
    )
    native_menu_note = _read(
        "docs/reverse-engineering/native-menus-and-boot.md"
    )
    native_session_note = _read(
        "docs/reverse-engineering/native-session-flow.md"
    )
    binary_layout = _read("config/binary-layout.ini")
    verifier = _read(
        "tools/verify_game_over_session_semantics.py"
    )
    status_verifier = _read(
        "tools/verify_lobby_session_state_transitions.py"
    )
    local_verifier = _read(
        "tools/verify_local_multiplayer_sync.py"
    )
    solo_launcher = _read(
        "scripts/Launch-LocalSoloSession.ps1"
    )
    pair_launcher = _read(
        "scripts/Launch-LocalMultiplayerPair.ps1"
    )
    lua_exec = _read("scripts/Invoke-LuaExec.ps1")

    _require_in_order(
        labels,
        "const char* LobbySessionStateLabel(LobbySessionState state)",
        "case LobbySessionState::NotInGame:",
        'return "not-in-game";',
        "case LobbySessionState::InHub:",
        'return "in-hub";',
        "case LobbySessionState::InBoneyard:",
        'return "in-boneyard";',
    )
    _require_tokens(
        local_state,
        (
            "LobbySessionState DetectLocalLobbySessionState(",
            'scene_state.kind == "hub"',
            "LobbySessionState::InHub",
            'scene_state.kind == "arena"',
            "IsRunLifecycleActive()",
            "LobbySessionState::InBoneyard",
            "return LobbySessionState::NotInGame;",
            "state.run_end_pending_lobby_return = false;",
        ),
        "local activity detector",
    )
    _require_tokens(
        runtime_state,
        (
            "LobbySessionState lobby_session_state",
            "bool run_end_pending_lobby_return",
        ),
        "runtime activity state",
    )
    _require_tokens(
        transport,
        (
            "void NotifyLocalRunStarted()",
            "state.run_end_pending_lobby_return = false;",
            "void NotifyLocalRunEnded(std::string_view reason)",
            "state.run_end_pending_lobby_return = true;",
        ),
        "run lifecycle state",
    )
    _require_tokens(
        join_flow,
        (
            "case JoinFlowPhase::PostRun:",
            'snapshot->surface_id == "main_menu"',
            "SetPhaseUnlocked(JoinFlowPhase::AdvancingMenus);",
            'snapshot->surface_id == "hall_of_fame"',
            "TryContinuePostRunHallOfFame(&error_message)",
            'QueueGameplayKeyPress("menu", &error_message)',
        ),
        "post-run stock reentry",
    )
    assert "QueueGameplaySwitchRegion(" not in join_flow
    _require_tokens(
        join_flow_state + join_flow,
        (
            "kPostRunInputRetryDelayMs = 1000;",
            "post_run_menu_retry_not_before_ms",
            "post_run_hall_of_fame_continue_logged",
            "phase == JoinFlowPhase::PostRun",
            "post_run_hall_of_fame_continue_logged = false;",
            "now_ms + kActionRetryDelayMs;",
            "quick_start_loadout_state_logged",
            "loadout_pick_generation",
            "create_pick_committed",
            "last_committed_element",
            "last_committed_discipline",
            "retained_preselection_active",
            "kCreateDisciplineSelectedOffset = 0x22C;",
            "Multiplayer join flow could not queue semantic UI ",
        ),
        "post-run stock front-end state",
    )
    _require_tokens(
        join_flow_state,
        (
            "void BeginNextLoadoutGenerationUnlocked(",
            'BeginNextLoadoutGenerationUnlocked("game_over")',
            'BeginNextLoadoutGenerationUnlocked(\n            "fresh_create_surface")',
            "void __fastcall HookCreateTick(",
            "void __fastcall HookCreateClick(",
            "kCreateSelectionUnset",
            "preselected_element=",
            "preselected_discipline=",
            "g_join_flow.last_committed_element = element_selected;",
            "g_join_flow.last_committed_discipline = discipline_selected;",
            "TryReadCreatePoint(",
            "ClosestCreatePointDistanceSquared<",
            "discipline_distance_squared <\n"
            "                         element_distance_squared",
            "replay_retained_element",
            "retained_element_x",
            "retained_element_y",
            "kCreateElementEnabledOffset,\n"
            "            std::uint32_t{1}",
            "kCreateDisciplineEnabledOffset,\n"
            "            std::uint32_t{1}",
            "kCreateElementSelectedOffset,\n"
            "                g_join_flow.last_committed_element",
            "kCreateDisciplineSelectedOffset,\n"
            "                g_join_flow.last_committed_discipline",
            "LoadoutPickState::Picking",
            "LoadoutPickState::Picked",
            "LoadoutPickState::WorldReady",
            "JoinFlowPhase::WaitingForHostLoadout",
        ),
        "per-match stock Create repick",
    )
    assert "quick_start_loadout_replay_enabled" not in join_flow_state
    _require_tokens(
        debug_ui_header,
        ("bool TryContinuePostRunHallOfFame(std::string* error_message);",),
        "typed Hall of Fame public seam",
    )
    _require_tokens(
        debug_ui_actions,
        (
            "bool TryContinuePostRunHallOfFame(",
            '"game_over.native"',
            '"application_global"',
            '"application_hall_of_fame_offset"',
            '"hall_of_fame_vftable"',
            '"hall_of_fame_continue"',
            '"hall_of_fame_continue_stack_bytes"',
            "TryReadResolvedGamePointer(",
            "TryResolveOwnerControlActionMethod(",
            "TryCallUiOwnerIgnoredStackArgAction(",
            "UiOwnerIgnoredStackArgActionFn",
        ),
        "validated Hall of Fame native dispatch",
    )
    assert "LeaveSteam" not in join_flow
    assert "ShutdownLocalTransport" not in join_flow

    _require_tokens(
        steam_status,
        (
            "LobbySessionStateLabel(runtime_state.lobby_session_state)",
            "case LobbySessionState::NotInGame:",
            'game_phase = "hub";',
            "runtime_state.run_loading_barrier.released",
            "snapshot.session_state = session_state;",
        ),
        "Steam lobby status",
    )
    assert "sessionState" in startup_status
    assert "string SessionState" in launcher_status
    _require_tokens(
        launcher_view,
        (
            '"in-hub" => "In Hub"',
            '"in-boneyard" => "In Boneyard"',
            '"not-in-game" => "Not In Game"',
        ),
        "launcher lobby card",
    )
    _require_tokens(
        directory_publisher,
        (
            '"not-in-game" or "in-hub" or "in-boneyard"',
            '"picking-loadout" or "hub" or "loading" or "session" or "results"',
            '"picking-loadout" => "Picking Loadout"',
            "status.GamePhase",
        ),
        "website lobby-directory publication",
    )
    _require_tokens(
        native_note,
        (
            "native Game Over completion and multiplayer-session teardown are",
            "independent state machines",
            "Boneyard/survival presentation branch",
            "`DAT_0081A434`",
            "`FUN_005A7F60`",
            "synthesizes acceptance inside `GameOver::Tick`",
            "must send no input while Game Over owns the",
            "Stock post-Boneyard front-end lineage",
            "`0x00799334`",
            "must never issue a raw region switch",
            "must likewise not retire authenticated lobby",
            "without recreating or rejoining the lobby",
        ),
        "native Game Over session documentation",
    )
    _require_tokens(
        native_web_combat_note,
        (
            "`GameOver::Tick` synthesizes acceptance",
            "no mouse, keyboard, controller, or",
            "multiplayer input owns that edge",
            "automatic Game Over completion",
        ),
        "native web combat lifecycle documentation",
    )
    _require_tokens(
        native_menu_note,
        (
            "synthesizes acceptance internally",
            "it does not arm or await user",
            "input. Subsequent Mortuary",
            "Boneyard mode has the",
            "internal tick-1000 edge",
        ),
        "native menu lifecycle documentation",
    )
    _require_tokens(
        native_session_note,
        (
            "automatically accepts at tick 1000",
            "Current acceptance therefore waits without input",
            "Waiting indefinitely at or beyond that edge is a failure",
        ),
        "native session-flow documentation",
    )
    _require_tokens(
        binary_layout,
        (
            "vtable=0x0079B0CC",
            "boneyard_mode=0x0081A434",
            "render=0x005C9030",
            "boneyard_front_end_dispatch=0x005A7F60",
            "application_global=0x00B401A8",
            "application_main_menu_offset=0x0DAC",
            "application_hall_of_fame_offset=0x0DB0",
            "post_run_main_menu=0x005A7D90",
            "hall_of_fame_factory=0x005A7E30",
            "hall_of_fame_vftable=0x00799334",
            "hall_of_fame_tick=0x00589CD0",
            "hall_of_fame_continue=0x00589DB0",
            "hall_of_fame_continue_stack_bytes=0x04",
            "application_cpu_manager=0x44",
            "tick_count=0xAC",
        ),
        "native Game Over layout",
    )
    _require_tokens(
        verifier,
        (
            '"-FreshInstall"',
            '"--launcher-path"',
            "fresh_install=True",
            "quick_start=True",
            "launcher_path=launcher_path",
            '"same_lobby_hub_state"',
            '"same_lobby_hub_relationships"',
            '"second_run_relationships"',
            '"second_run_loading_release"',
            "NATIVE_GAME_OVER_PROBE",
            "native_boneyard_game_over_state_matches",
            'emit("local_native_death_drive"',
            'emit("local_native_death_tick"',
            "allow_boneyard_mode=True",
            "advance_stock_boneyard_game_over(",
            '"game_over_input_count": 0',
            '"passive-game-over-then-stock-create-confirmation"',
            'result["last_player_death_clock"]',
            "_assert_retained_create_selection(",
            "_confirm_retained_create_selection(",
            '"semantic_confirmation_clicks": 1',
            '"staggered-stock-create-with-retained-one-click-confirmation"',
            '"--window-only"',
            "hub_stable_since",
            "now - hub_stable_since >= 3.0",
            'emit("create_action_ids"',
            'emit("create_element_selected"',
            'emit("create_discipline_selected"',
            '"same_process_ids": True',
            '"rejoin_performed": False',
            '"relaunch_performed": False',
        ),
        "same-lobby second-run live gate",
    )
    assert verifier.count("allow_boneyard_mode=True") >= 2
    _require_tokens(
        status_verifier,
        (
            'EXPECTED_STATES = ("not-in-game", "in-hub", "in-boneyard")',
            '"multiplayer-session-status.json"',
            '"members"',
            '"--fresh-install"',
            "ACCEPTANCE_MOD_ID",
            "_prepare_acceptance_mod_state(",
            '"--multiplayer"',
            '"host"',
            "_start_testrun_when_ready(pipe_name)",
            "timeout=60.0",
            "timeout=45.0",
            "_query_exact_process_ids(",
            "stop_owned_processes(owned)",
        ),
        "real Steam session-state transition gate",
    )
    _require_tokens(
        local_verifier,
        (
            "fresh_install: bool = False",
            'args.append("-FreshInstall")',
        ),
        "isolated fresh-install launcher adapter",
    )
    _require_tokens(
        solo_launcher,
        (
            "[switch]$FreshInstall",
            "[switch]$QuickStart",
            '[string]$LauncherPath = ""',
            '$arguments += "--fresh-install"',
            '$arguments += "--temporary-profile"',
            "SDMOD_MULTIPLAYER_QUICK_START",
            "SDMOD_MULTIPLAYER_QUICK_START_ELEMENT",
            "SDMOD_MULTIPLAYER_QUICK_START_DISCIPLINE",
        ),
        "isolated solo fresh-install launcher",
    )
    _require_tokens(
        pair_launcher,
        (
            "[switch]$FreshInstall",
            "function Invoke-InstanceLuaExec",
        ),
        "isolated multiplayer launcher",
    )
    assert "[int]$ResponseTimeoutMilliseconds = 35000" in lua_exec
    assert "-ResponseTimeoutMilliseconds" not in pair_launcher
    return (
        "native Game Over remains stock-owned while the authenticated lobby "
        "survives and publishes exact not-in-game, in-hub, and in-boneyard state"
    )


def test_run_loading_waits_for_every_peer_visibility_and_is_bounded() -> str:
    protocol = _read(
        "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h"
    )
    barrier = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "run_loading_barrier_sync.inl"
    ) + _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "run_loading_visibility.inl"
    )
    transport_tick = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "public_cast_loot_api.inl"
    )
    outgoing = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "outgoing_packet_sync.inl"
    )
    join_flow = _read(
        "SolomonDarkModLoader/src/multiplayer_join_flow/tick_state_machine.inl"
    )
    presentation = _read(
        "SolomonDarkModLoader/src/multiplayer_join_flow.cpp"
    )
    lua_runtime = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_runtime.cpp"
    )
    verifier = _read(
        "tools/verify_game_over_session_semantics.py"
    )

    assert "kProtocolVersion = 92" in protocol
    for field in (
        "run_loading_ack_nonce",
        "run_loading_release_nonce",
        "run_loading_deadline_remaining_ms",
        "run_loading_visible_participant_set_hash",
        "run_loading_expected_participant_set_hash",
        "run_loading_visible_participant_count",
        "run_loading_expected_participant_count",
        "run_loading_ready_participant_count",
        "run_loading_release_reason",
    ):
        assert protocol.count(field) == 2, (
            f"{field} must exist in both reliable state and participant frame"
        )
    assert "sizeof(StatePacket) == 709" in protocol
    assert "sizeof(ParticipantFramePacket) == 426" in protocol

    _require_tokens(
        barrier,
        (
            "kRunLoadingBarrierTimeoutMs = 25000",
            "kRunLoadingMaterializationStableMs = 250",
            "local_visibility_stable_since_ms",
            "BuildHostRunLoadingExpectedParticipantIds(",
            "participant.loadout_pick_generation !=",
            "participant.loadout_pick_state !=",
            "LoadoutPickState::WorldReady",
            "RunLoadingParticipantSetHash(",
            "BuildLocallyVisibleRunParticipantIds(",
            "HostHasLocalMutualRunVisibility(",
            "raw_local_mutual_visibility",
            "now_ms -",
            "kRunLoadingMaterializationStableMs",
            ".visible_participant_count ==",
            ".visible_participant_set_hash ==",
            ".authoritative_expected_participant_set_hash",
            "packet.run_loading_ack_nonce !=",
            "packet.run_loading_visible_participant_set_hash !=",
            "packet.run_loading_expected_participant_set_hash !=",
            "packet_from_configured_authority",
            "AllParticipantsReady",
            '"host_deadline"',
            '"client_fallback_deadline"',
            '"authenticated_host_release"',
        ),
        "run-loading barrier",
    )
    _require_in_order(
        transport_tick,
        "ReceivePackets(now_ms);",
        "ServiceRunLoadingBarrier(now_ms);",
        "SendLocalState(now_ms);",
        "SendLocalParticipantFrame(now_ms);",
    )
    assert outgoing.count("!HasRunLoadingBarrierPacketWork(packet)") == 2
    assert "SteamNetworkSendMode::ReliableNoNagle" in outgoing

    _require_tokens(
        join_flow,
        (
            "case JoinFlowPhase::LoadingBoneyard:",
            "IsRunLoadingBarrierReleased(runtime)",
            "HasLocalRunTerminated(runtime)",
        ),
        "run-entry presentation gate",
    )
    _require_tokens(
        presentation,
        (
            "NotifyMultiplayerJoinFlowRunStart()",
            "JoinFlowPhase::Hub",
            'return {true, "Loading Boneyard"};',
        ),
        "host and client loading presentation",
    )
    _require_tokens(
        lua_runtime,
        (
            '"run_loading_barrier"',
            '"local_mutual_visibility"',
            '"expected_participant_ids"',
            '"ready_participant_ids"',
            '"waiting_participant_ids"',
            '"release_reason"',
        ),
        "barrier observability",
    )
    _require_tokens(
        verifier,
        (
            "capture_loading_presentations(",
            "classify_loading_boneyard_image(",
            "minimum_unique_colors=20",
            "maximum_dominant_fraction=0.9999",
            '"center_light_fraction"',
            "healthy_loading_barrier_state_matches(",
            "run_loading_timeout_verification(",
            "stop_owned_processes(client_owned)",
            '"host-loading-after-peer-kill.png"',
            'expected_reason="timeout"',
            "timeout=35.0",
            '"host-proceeded-after-timeout.png"',
            '_path_for_local_python(str(launch["hostLog"]))',
        ),
        "bounded loading-barrier live gate",
    )
    return (
        "all participants keep Loading Boneyard until every peer acks the same "
        "materialized actor set, with authenticated host release and bounded fallbacks"
    )


def test_run_termination_resets_every_participant_without_retiring_wan_death_durability() -> str:
    runtime_state = _read(
        "SolomonDarkModLoader/include/multiplayer_runtime_effect_state.inl"
    )
    transport = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport.cpp"
    )
    transport_reset = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "participant_run_termination.inl"
    )
    incoming = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "incoming_packet_sync.inl"
    )
    lifecycle = _read(
        "SolomonDarkModLoader/src/run_lifecycle/"
        "enemy_tracking_and_reset.inl"
    )
    gameplay_api = _read(
        "SolomonDarkModLoader/include/mod_loader_gameplay_api.inl"
    )
    gameplay_public = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/public_api.inl"
    )
    gameplay_reset = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "public_api_participant_run_termination.inl"
    )
    materialization = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "bot_registry_and_movement_participant_lifecycle.inl"
    )
    verifier = _read("tools/verify_game_over_session_semantics.py")

    _require_tokens(
        runtime_state,
        ("std::uint32_t last_terminated_run_nonce = 0;",),
        "runtime run-generation fence",
    )
    _require_tokens(
        transport_reset,
        (
            "bool IsAuthenticatedFreshRunEntryPacket(",
            "run_loading_deadline_remaining_ms != 0;",
            "void RetireParticipantRunTerminationFenceForNewRun(",
            "void ResetParticipantRuntimeForRunTermination(",
            "runtime.transform_valid = false;",
            "participant.transform_history.clear();",
            "participant.runtime.life_current =",
            "participant.runtime.life_max;",
            "ParticipantPresentationFlagDeathPresentation",
        ),
        "transport participant run reset",
    )
    for forbidden in (
        "preserve_transition_transform",
        "transition_transform",
        "participant.transform_history.push_back(",
    ):
        assert forbidden not in transport_reset, (
            "run presentation leaked into the replacement hub timeline: "
            + forbidden
        )
    _require_tokens(
        transport,
        (
            "state.last_terminated_run_nonce = 0;",
            "for (auto& participant : state.participants)",
            "ResetParticipantRuntimeForRunTermination(",
            "g_local_terminated_run_nonce.store(",
        ),
        "transport participant run reset",
    )
    _require_tokens(
        incoming,
        (
            "IsParticipantPacketFromTerminatedRun(",
            "packet.run_nonce",
            "ResetParticipantRuntimeForRunTermination(",
            "participant);",
        ),
        "late old-run packet fence",
    )
    _require_tokens(
        _read(
            "SolomonDarkModLoader/src/multiplayer_local_transport/"
            "incoming_participant_state_sync.inl"
        ),
        (
            "IsAuthenticatedFreshRunEntryPacket(",
            "RetireParticipantRunTerminationFenceForNewRun(",
            '"state_packet"',
            '"participant_frame"',
        ),
        "authenticated next-run fence retirement",
    )
    _require_tokens(
        gameplay_api,
        ("void ResetParticipantEntitiesForRunTermination(",),
        "native participant reset API",
    )
    assert (
        '#include "public_api_participant_run_termination.inl"'
        in gameplay_public
    )
    _require_tokens(
        gameplay_reset,
        (
            "void ResetParticipantEntitiesForRunTermination(",
            "for (auto& binding : g_participant_entities)",
            "binding.native_remote_death_epoch_active = false;",
            "binding.native_remote_death_attachment_actor_address",
            "binding.native_remote_death_drop_spawned = false;",
            "binding.ongoing_cast =",
            "ParticipantEntityBinding::OngoingCastState{};",
        ),
        "native participant run reset",
    )
    _require_in_order(
        lifecycle,
        "multiplayer::NotifyLocalRunEnded(reason);",
        "ResetParticipantEntitiesForRunTermination(reason);",
        "ResetRunLifecycleBookkeeping(clear_enemy_tracking);",
    )

    materialization_reset = materialization[
        materialization.index(
            "void ResetParticipantEntityMaterializationState("
        ):
        materialization.index(
            "void MarkParticipantEntityWorldUnregistered("
        )
    ]
    _require_tokens(
        materialization_reset,
        (
            "ResetParticipantEntityActorPresentationState(binding);",
            "materialized_presentation_scene_epoch = 0;",
        ),
        "complete actor-local presentation reset",
    )
    actor_presentation_reset = materialization[
        materialization.index(
            "void ResetParticipantEntityActorPresentationState("
        ):
        materialization.index("void RememberParticipantEntity(")
    ]
    for token in (
        "replicated_transform_valid = false;",
        "replicated_presentation_valid = false;",
        "replicated_attachment_visual_link_type_id = 0;",
        "equipment_reconcile_not_before_ms = 0;",
        "native_remote_death_epoch_active = false;",
        "native_remote_death_attachment_actor_address = 0;",
        "native_remote_death_drop_spawned = false;",
        "ongoing_cast = ParticipantEntityBinding::OngoingCastState{};",
    ):
        assert token in actor_presentation_reset, (
            "actor-local presentation reset lacks: " + token
        )

    for token in (
        "host_first_hub_before_client_return",
        "same_lobby_hub_vitality",
        "second_run_vitality",
        '"host_first_hub_before_client_return": (',
        'f"hub_{label}"',
        'f"run2_{label}"',
        "run_boundary_vitality_reset_matches(",
    ):
        assert token in verifier, (
            "Game Over next-run verifier lacks: " + token
        )

    return (
        "the common run-termination seam clears all participant combat, "
        "vitality, transform history, and native death-epoch state, retains "
        "no outgoing run pose for hub materialization, and leaves durable "
        "participant identity available while replacement actors materialize"
    )
