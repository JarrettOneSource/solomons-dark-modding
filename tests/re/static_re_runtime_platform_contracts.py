"""Runtime platform, progression, reconnect, and package contracts."""

from __future__ import annotations

import ast
import hashlib
import json
import math
import re
import struct
import sys
from pathlib import Path

from static_re_contract_support import (
    ROOT,
    StaticReTestFailure,
    read_multiplayer_transport_source,
    read_source_unit,
    read_text,
)


def test_launcher_multiplayer_quick_start_uses_live_ui_and_scene_readiness() -> str:
    launch_environment_text = read_text(
        ROOT
        / "SolomonDarkModLauncher/src/Launch/MultiplayerLaunchEnvironment.cs"
    )
    flow_header_text = read_text(
        ROOT
        / "SolomonDarkModLoader/include/multiplayer_join_flow.h"
    )
    flow_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_join_flow.cpp"
    )
    transport_header_text = read_text(
        ROOT / "SolomonDarkModLoader/include/multiplayer_local_transport.h"
    )
    transport_api_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "public_cast_loot_api.inl"
    )
    transport_text = read_text(
        ROOT / "SolomonDarkModLoader/src/multiplayer_local_transport.cpp"
    )
    incoming_transport_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "incoming_packet_sync.inl"
    )
    loader_text = read_text(ROOT / "SolomonDarkModLoader/src/mod_loader.cpp")
    app_tick_text = read_text(
        ROOT / "SolomonDarkModLoader/src/background_focus_bypass.cpp"
    )
    render_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/debug_ui_overlay/"
        "label_resolution_surface_registry_and_frame_render.inl"
    )
    run_hooks_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks/"
        "run_transition_hooks.inl"
    )
    project_text = read_text(
        ROOT / "SolomonDarkModLoader/SolomonDarkModLoader.vcxproj"
    )

    required_pairs = (
        (
            launch_environment_text,
            'QuickStartVariable = "SDMOD_MULTIPLAYER_QUICK_START"',
        ),
        (launch_environment_text, "environment[QuickStartVariable] = \"1\";"),
        (
            launch_environment_text,
            "environment[QuickStartVariable] = string.Empty;",
        ),
        (flow_header_text, "void TickMultiplayerJoinFlow();"),
        (flow_header_text, "void NotifyMultiplayerJoinFlowRunStart();"),
        (flow_text, "kMainMenuDialogWindowMs = 1000"),
        (flow_text, "kTransitionPresentationMinimumMs = 750"),
        (flow_text, '"dialog.primary"'),
        (flow_text, '"main_menu.play"'),
        (flow_text, '"main_menu.new_game"'),
        (flow_text, "JoinFlowPhase::SelectingLoadout"),
        (flow_text, "return {true, \"Connecting to match\"};"),
        (flow_text, "return {true, \"Loading Boneyard\"};"),
        (flow_text, "scene.world_address != 0"),
        (flow_text, "scene.arena_address != 0"),
        (flow_text, "runtime.transport_ready"),
        (flow_text, "multiplayer::SessionStatus::Ready"),
        (flow_text, "bool IsHostCharacterReady("),
        (flow_text, "IsHostCharacterReady(runtime)"),
        (
            transport_header_text,
            "std::uint64_t GetLocalTransportAuthorityParticipantId();",
        ),
        (
            transport_api_text,
            "std::uint64_t GetLocalTransportAuthorityParticipantId()",
        ),
        (
            transport_text,
            "std::atomic<std::uint64_t> "
            "g_local_transport_authority_participant_id{0};",
        ),
        (
            transport_text,
            "state.session_is_host = g_local_transport.is_host;",
        ),
        (
            incoming_transport_text,
            "g_local_transport_authority_participant_id.store(",
        ),
        (flow_text, "multiplayer::ParticipantSceneIntentKind::Run"),
        (loader_text, "InitializeMultiplayerJoinFlow();"),
        (loader_text, "!multiplayer_join_flow_enabled"),
        (loader_text, "InitializeDebugUiOverlay(diagnostic_ui_enabled)"),
        (app_tick_text, "TickMultiplayerJoinFlow();"),
        (app_tick_text, "DispatchPendingDebugUiActionOnAppTick();"),
        (render_text, "GetMultiplayerJoinFlowPresentation();"),
        (render_text, "D3DCOLOR_ARGB(255, 0, 0, 0)"),
        (render_text, "DrawMultiplayerJoinFlowPresentation("),
        (run_hooks_text, "NotifyMultiplayerJoinFlowRunStart();"),
        (
            project_text,
            'ClInclude Include="include\\multiplayer_join_flow.h"',
        ),
        (
            project_text,
            'ClCompile Include="src\\multiplayer_join_flow.cpp"',
        ),
    )
    missing = [token for text, token in required_pairs if token not in text]
    if missing:
        raise StaticReTestFailure(
            "multiplayer quick-start contract is missing token(s): "
            + ", ".join(missing)
        )

    host_readiness_start = flow_text.find("bool IsHostCharacterReady(")
    host_readiness_end = flow_text.find(
        "\nbool HasAction(", host_readiness_start
    )
    host_readiness_body = flow_text[
        host_readiness_start:host_readiness_end
    ]
    required_host_readiness = (
        "runtime.session_is_host",
        "TryGetPlayerState(&host_player)",
        "host_player.valid",
        "host_player.actor_address != 0",
        "GetLocalTransportAuthorityParticipantId()",
        "host_participant_id == 0",
        "participant.steam_id == host_participant_id",
        "participant.participant_id == host_participant_id",
        "host_participant->participant_id",
        "TryGetParticipantGameplayState(",
        "host_character.entity_materialized",
        "host_character.actor_address != 0",
    )
    missing_host_readiness = [
        token
        for token in required_host_readiness
        if token not in host_readiness_body
    ]
    if missing_host_readiness:
        raise StaticReTestFailure(
            "multiplayer quick-start host-character readiness is missing "
            "token(s): " + ", ".join(missing_host_readiness)
        )

    authority_resolver_start = transport_api_text.find(
        "std::uint64_t GetLocalTransportAuthorityParticipantId()"
    )
    authority_resolver_end = transport_api_text.find(
        "\nbool IsSteamGameplayTransportEnabled()", authority_resolver_start
    )
    authority_resolver_body = transport_api_text[
        authority_resolver_start:authority_resolver_end
    ]
    required_authority_resolution = (
        "g_local_transport_authority_participant_id.load(",
        "std::memory_order_acquire",
    )
    missing_authority_resolution = [
        token
        for token in required_authority_resolution
        if token not in authority_resolver_body
    ]
    if missing_authority_resolution:
        raise StaticReTestFailure(
            "local UDP quick-start host authority resolution is missing "
            "token(s): " + ", ".join(missing_authority_resolution)
        )
    if "g_local_transport.peers" in authority_resolver_body:
        raise StaticReTestFailure(
            "app-thread host readiness must not read the service-thread peer vector"
        )

    flow_tick = app_tick_text.find("TickMultiplayerJoinFlow();")
    semantic_dispatch = app_tick_text.find(
        "DispatchPendingDebugUiActionOnAppTick();", flow_tick
    )
    stock_tick = app_tick_text.find("original(app, edx);", semantic_dispatch)
    if not 0 <= flow_tick < semantic_dispatch < stock_tick:
        raise StaticReTestFailure(
            "quick-start navigation must queue before semantic UI dispatch and the stock app tick"
        )

    tick_start = flow_text.find("void TickMultiplayerJoinFlow()")
    connecting_phase = flow_text.find(
        "case JoinFlowPhase::Connecting:", tick_start
    )
    hub_phase = flow_text.find(
        "case JoinFlowPhase::Hub:", connecting_phase
    )
    connecting_body = flow_text[connecting_phase:hub_phase]
    readiness_order = (
        connecting_body.find("hub_ready"),
        connecting_body.find("runtime.transport_ready"),
        connecting_body.find("multiplayer::SessionStatus::Ready"),
        connecting_body.find("IsHostCharacterReady(runtime)"),
        connecting_body.find("SetPhaseUnlocked(JoinFlowPhase::Hub)"),
    )
    if any(position == -1 for position in readiness_order) or list(
        readiness_order
    ) != sorted(readiness_order):
        raise StaticReTestFailure(
            "Connecting to match must remain until the live hub, Steam session, "
            "and host character are ready"
        )
    if (
        flow_text.count(
            "g_join_flow.phase_entered_ms +\n"
            "                kTransitionPresentationMinimumMs"
        )
        != 2
    ):
        raise StaticReTestFailure(
            "Connecting and Loading Boneyard must remain visible long enough to read"
        )

    loading_phase = flow_text.find(
        "case JoinFlowPhase::LoadingBoneyard:", tick_start
    )
    run_phase = flow_text.find(
        "case JoinFlowPhase::Run:", loading_phase
    )
    loading_body = flow_text[loading_phase:run_phase]
    if (
        loading_body.find("boneyard_ready") == -1
        or loading_body.find("SetPhaseUnlocked(JoinFlowPhase::Run)")
        < loading_body.find("boneyard_ready")
    ):
        raise StaticReTestFailure(
            "Loading Boneyard must remain until the native arena is ready"
        )

    render_start = render_text.find(
        "const auto join_flow_presentation"
    )
    draw_black = render_text.find(
        "DrawMultiplayerJoinFlowPresentation(", render_start
    )
    transition_return = render_text.find("return;", draw_black)
    diagnostics = render_text.find(
        "if (!diagnostic_visuals_enabled)", transition_return
    )
    if not 0 <= render_start < draw_black < transition_return < diagnostics:
        raise StaticReTestFailure(
            "join-flow presentation must cover the frame before optional diagnostics render"
        )
    diagnostics_end = render_text.find("\n    }", diagnostics)
    diagnostics_body = render_text[diagnostics:diagnostics_end]
    if (
        "render_elements.clear();" not in diagnostics_body
        or "return;" in diagnostics_body
    ):
        raise StaticReTestFailure(
            "quick-start mode must hide diagnostic surfaces without suppressing "
            "functional multiplayer overlays"
        )

    hook_start = run_hooks_text.find("void __fastcall HookStartGame(")
    hook_end = run_hooks_text.find("\n}", hook_start)
    hook_body = run_hooks_text[hook_start:hook_end]
    notify = hook_body.find("NotifyMultiplayerJoinFlowRunStart();")
    stock_start = hook_body.find("original(self, unused_edx);")
    if not 0 <= notify < stock_start:
        raise StaticReTestFailure(
            "Host Start Game must blacken the screen before the stock transition begins"
        )

    return (
        "Host and Join skip to native loadout selection, then gate the "
        "Connecting and Loading Boneyard covers on live Steam, host-character, "
        "and scene readiness"
    )


def test_multiplayer_quick_start_keeps_private_gameplay_visible() -> str:
    flow_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_join_flow.cpp"
    )

    required_tokens = (
        "JoinFlowPhase::PrivateGameplay",
        "bool IsPrivateGameplayReady(",
        "scene.valid &&",
        "scene.world_address != 0 &&",
        "!IsHubScene(scene) &&",
        "!IsBoneyardScene(scene)",
        "const bool private_gameplay_ready =",
    )
    missing = [token for token in required_tokens if token not in flow_text]
    if missing:
        raise StaticReTestFailure(
            "private-gameplay quick-start recovery is missing token(s): "
            + ", ".join(missing)
        )

    tick_start = flow_text.find("void TickMultiplayerJoinFlow()")
    advancing_start = flow_text.find(
        "case JoinFlowPhase::AdvancingMenus:", tick_start
    )
    private_start = flow_text.find(
        "case JoinFlowPhase::PrivateGameplay:", advancing_start
    )
    awaiting_start = flow_text.find(
        "case JoinFlowPhase::AwaitingLoadout:", private_start
    )
    selecting_start = flow_text.find(
        "case JoinFlowPhase::SelectingLoadout:", awaiting_start
    )
    connecting_start = flow_text.find(
        "case JoinFlowPhase::Connecting:", selecting_start
    )
    hub_start = flow_text.find(
        "case JoinFlowPhase::Hub:", connecting_start
    )
    phase_order = (
        advancing_start,
        private_start,
        awaiting_start,
        selecting_start,
        connecting_start,
        hub_start,
    )
    if any(position == -1 for position in phase_order) or list(
        phase_order
    ) != sorted(phase_order):
        raise StaticReTestFailure(
            "private gameplay must be an explicit quick-start phase"
        )

    advancing_body = flow_text[advancing_start:private_start]
    private_transition = advancing_body.find(
        "if (private_gameplay_ready)"
    )
    pending_resolution = advancing_body.find(
        "ResolvePendingActionUnlocked"
    )
    if not 0 <= private_transition < pending_resolution:
        raise StaticReTestFailure(
            "active private gameplay must escape the menu cover before "
            "quick-start waits on a menu action"
        )

    private_body = flow_text[private_start:awaiting_start]
    private_requirements = (
        "SetPhaseUnlocked(JoinFlowPhase::Connecting)",
        "SetPhaseUnlocked(JoinFlowPhase::Run)",
        "snapshot->captured_at_milliseconds >",
        "g_join_flow.phase_entered_ms",
        "SetPhaseUnlocked(JoinFlowPhase::AdvancingMenus)",
    )
    missing_private = [
        token for token in private_requirements if token not in private_body
    ]
    if missing_private:
        raise StaticReTestFailure(
            "private gameplay cannot recover into every supported destination: "
            + ", ".join(missing_private)
        )

    selecting_body = flow_text[selecting_start:connecting_start]
    selecting_private = selecting_body.find(
        "if (private_gameplay_ready)"
    )
    loadout_finished = selecting_body.find(
        "HasLoadoutSelectionFinished"
    )
    connecting_transition = selecting_body.find(
        "SetPhaseUnlocked(JoinFlowPhase::Connecting)"
    )
    if not 0 <= loadout_finished < selecting_private < connecting_transition:
        raise StaticReTestFailure(
            "a new-save tutorial reached from loadout selection must stay visible"
        )

    connecting_body = flow_text[connecting_start:hub_start]
    connecting_private = connecting_body.find(
        "if (private_gameplay_ready)"
    )
    transition_delay = connecting_body.find(
        "kTransitionPresentationMinimumMs"
    )
    if not 0 <= connecting_private < transition_delay:
        raise StaticReTestFailure(
            "private gameplay must dismiss the Connecting cover immediately"
        )

    presentation_start = flow_text.find(
        "GetMultiplayerJoinFlowPresentation()"
    )
    presentation_text = flow_text[presentation_start:]
    advancing_presentation = presentation_text.find(
        "case JoinFlowPhase::AdvancingMenus:"
    )
    private_presentation = presentation_text.find(
        "case JoinFlowPhase::PrivateGameplay:"
    )
    awaiting_presentation = presentation_text.find(
        "case JoinFlowPhase::AwaitingLoadout:"
    )
    if not (
        0 <= advancing_presentation <
        private_presentation <
        awaiting_presentation
    ):
        raise StaticReTestFailure(
            "quick-start presentation must distinguish menu discovery, "
            "private gameplay, and loadout transition"
        )

    advancing_presentation_body = presentation_text[
        advancing_presentation:private_presentation
    ]
    if (
        "g_join_flow.main_menu_first_seen_ms != 0"
        not in advancing_presentation_body
    ):
        raise StaticReTestFailure(
            "quick-start must not cover the frame before the main menu is observed"
        )

    private_presentation_body = presentation_text[
        private_presentation:awaiting_presentation
    ]
    if "return {};" not in private_presentation_body:
        raise StaticReTestFailure(
            "active private gameplay must render without a quick-start cover"
        )

    return (
        "Fresh-save tutorial and other private gameplay remain visible, then "
        "resume quick-start only when hub, run, or menu state is live"
    )


def test_client_run_switch_requires_fresh_authenticated_host_intent() -> str:
    transport_header_text = read_text(
        ROOT / "SolomonDarkModLoader/include/multiplayer_local_transport.h"
    )
    transport_text = read_multiplayer_transport_source()
    public_api_text = read_text(
        ROOT / "SolomonDarkModLoader/src/multiplayer_local_transport/public_cast_loot_api.inl"
    )
    lifecycle_hook_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_actor_lifecycle_hooks.inl"
    )
    arena_hook_text = read_source_unit(
        ROOT / "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks.inl"
    )
    lifecycle_state_text = read_text(
        ROOT / "SolomonDarkModLoader/src/run_lifecycle/state_and_targets.inl"
    )
    lifecycle_install_text = read_text(
        ROOT / "SolomonDarkModLoader/src/run_lifecycle/public_api_and_install.inl"
    )
    seam_binding_text = read_text(
        ROOT / "SolomonDarkModLoader/src/gameplay_seams/state_and_address_bindings.inl"
    )
    binary_layout_text = read_text(ROOT / "config/binary-layout.ini")
    run_seed_api_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_gameplay_action_queues.inl"
    )
    run_seed_helpers_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/core/run_generation_seed_helpers.inl"
    )
    run_reset_text = read_text(
        ROOT / "SolomonDarkModLoader/src/run_lifecycle/enemy_tracking_and_reset.inl"
    )
    active_pair_driver_text = read_text(
        ROOT / "tools/drive_steam_friend_active_pair.py"
    )

    required_pairs = (
        (transport_header_text, "TryAuthorizeLocalClientRunSwitch(std::string* error_message)"),
        (transport_text, "struct ClientHostRunAuthorization"),
        (transport_text, "kClientHostRunAuthorizationFreshnessMs = 3000"),
        (transport_text, "IsAuthoritativeHostParticipantPacket(packet, from)"),
        (transport_text, "Multiplayer cached authenticated host run intent"),
        (public_api_text, "bool TryAuthorizeLocalClientRunSwitch(std::string* error_message)"),
        (public_api_text, "No fresh authenticated host run intent is available."),
        (public_api_text, "authorization.run_nonce == 0"),
        (public_api_text, "SetPendingRunGenerationSeed(authorization.run_nonce"),
        (lifecycle_hook_text, "multiplayer::TryAuthorizeLocalClientRunSwitch(&authorization_error)"),
        (lifecycle_hook_text, "Authorized client run switch_region from fresh authenticated host intent."),
        (arena_hook_text, 'PrepareMultiplayerRunStart("arena_create")'),
        (arena_hook_text, 'PrepareMultiplayerRunStart("start_game")'),
        (arena_hook_text, "HookMainMenuControlAction"),
        (arena_hook_text, "void* /*unused_edx*/, void* control"),
        (arena_hook_text, "kMainMenuModeOffset = 0x3FC"),
        (arena_hook_text, "kMainMenuSavedRunMode = 1"),
        (arena_hook_text, "kMainMenuLastGameControlOffset = 0x78"),
        (arena_hook_text, "kMainMenuNewGameControlOffset = 0x12C"),
        (arena_hook_text, "TryPrepareMainMenuNewGameSaveReset(owner_address, &save_reset_error)"),
        (arena_hook_text, "multiplayer::IsLocalTransportClient() ||"),
        (arena_hook_text, "multiplayer::IsLocalTransportHost()"),
        (arena_hook_text, "dispatched_control = reinterpret_cast<void*>(owner_address + kMainMenuNewGameControlOffset)"),
        (arena_hook_text, "Redirected connected multiplayer Last Game control activation"),
        (arena_hook_text, "the native New Game control path."),
        (arena_hook_text, "Blocked multiplayer run start without a host-authoritative run seed."),
        (lifecycle_state_text, "MainMenuControlActionFn = void(__thiscall*)(void* self, void* control)"),
        (lifecycle_state_text, "kHookMainMenuControlAction"),
        (lifecycle_state_text, "{kMainMenuControlAction, 7}"),
        (lifecycle_install_text, "reinterpret_cast<void*>(&HookMainMenuControlAction)"),
        (seam_binding_text, '"main_menu_control_action", kMainMenuControlAction'),
        (binary_layout_text, "main_menu_control_action=0x0058E600"),
        (active_pair_driver_text, 'action = ("main_menu.new_game", "main_menu")'),
        (active_pair_driver_text, 'action = ("main_menu.resume_last_game", "main_menu")'),
        (active_pair_driver_text, 'parser.add_argument("--exercise-last-game-redirect", action="store_true")'),
        (run_seed_api_text, "bool PrepareArenaRunGenerationSeed(const char* source"),
        (run_seed_api_text, "applied_run_generation_seed.load("),
        (run_seed_api_text, "ApplyPendingRunGenerationSeedForSceneSwitch("),
        (run_seed_helpers_text, "applied_run_generation_seed.store("),
        (run_seed_helpers_text, "local->runtime.run_nonce != 0"),
        (run_reset_text, "ClearLocalRunGenerationSeed();"),
    )
    missing = [token for text, token in required_pairs if token not in text]
    if missing:
        raise StaticReTestFailure(
            "authenticated client run-transition contract is missing token(s): " +
            ", ".join(missing))

    if "ignored host run intent outside hub" in transport_text:
        raise StaticReTestFailure(
            "host run intent still floods once per state packet during a client transition")

    maybe_start = transport_text.find("void MaybeQueueClientHostRunStart(")
    maybe_end = transport_text.find("void ApplyRemoteStatePacket(", maybe_start)
    maybe_body = transport_text[maybe_start:maybe_end]
    authority_check = maybe_body.find("IsAuthoritativeHostParticipantPacket(packet, from)")
    authorization_write = maybe_body.find("g_client_host_run_authorization.valid = true;")
    if (
        maybe_start == -1 or maybe_end == -1 or authority_check == -1 or
        authorization_write == -1 or authority_check > authorization_write
    ):
        raise StaticReTestFailure(
            "host ownership must be validated before caching client run authorization")

    main_menu_hook_start = arena_hook_text.find("void __fastcall HookMainMenuControlAction(")
    main_menu_hook_end = arena_hook_text.find("\n}", main_menu_hook_start)
    main_menu_hook_body = arena_hook_text[main_menu_hook_start:main_menu_hook_end]
    last_game_match = main_menu_hook_body.find(
        "reinterpret_cast<uintptr_t>(control) == owner_address + kMainMenuLastGameControlOffset")
    native_new_game_redirect = main_menu_hook_body.find(
        "dispatched_control = reinterpret_cast<void*>(owner_address + kMainMenuNewGameControlOffset)")
    save_reset = main_menu_hook_body.find(
        "TryPrepareMainMenuNewGameSaveReset(owner_address, &save_reset_error)")
    stock_control_action = main_menu_hook_body.find("original(self, dispatched_control);")
    if (
        main_menu_hook_start == -1 or main_menu_hook_end == -1 or
        last_game_match == -1 or save_reset == -1 or native_new_game_redirect == -1 or
        stock_control_action == -1 or
        last_game_match > save_reset or save_reset > native_new_game_redirect or
        native_new_game_redirect > stock_control_action
    ):
        raise StaticReTestFailure(
            "connected Last Game must substitute the native New Game control before "
            "dispatching the stock MainMenu handler")
    if "PrepareMultiplayerRunStart" in main_menu_hook_body:
        raise StaticReTestFailure(
            "main-menu New Game/character creation must not require a host run nonce")
    forbidden_late_redirect_tokens = (
        "MainMenuRunTransition",
        "main_menu_run_transition",
        "kMainMenuTransitionKindOffset",
        "kMainMenuNewGameTransition",
        "kMainMenuLastGameTransition",
    )
    combined_lifecycle_text = (
        arena_hook_text + lifecycle_state_text + lifecycle_install_text +
        seam_binding_text + binary_layout_text
    )
    stale_redirects = [
        token for token in forbidden_late_redirect_tokens
        if token in combined_lifecycle_text
    ]
    if stale_redirects:
        raise StaticReTestFailure(
            "late MainMenu transition-kind rewrite was not fully removed: " +
            ", ".join(stale_redirects))
    redirect_opt_in = active_pair_driver_text.find("if exercise_last_game_redirect:")
    resume_dispatch = active_pair_driver_text.find(
        'action = ("main_menu.resume_last_game", "main_menu")', redirect_opt_in)
    normal_new_game_dispatch = active_pair_driver_text.find(
        'action = ("main_menu.new_game", "main_menu")', resume_dispatch)
    if not 0 <= redirect_opt_in < resume_dispatch < normal_new_game_dispatch:
        raise StaticReTestFailure(
            "Steam pair onboarding must keep Last Game behind the explicit redirect regression flag")

    hook_start = lifecycle_hook_text.find("void __fastcall HookGameplaySwitchRegion(")
    hook_end = lifecycle_hook_text.find("\n}", hook_start)
    hook_body = lifecycle_hook_text[hook_start:hook_end]
    authorization_check = hook_body.find("TryAuthorizeLocalClientRunSwitch")
    stock_switch = hook_body.find("original(self, region_index);")
    if (
        hook_start == -1 or hook_end == -1 or authorization_check == -1 or
        stock_switch == -1 or authorization_check > stock_switch
    ):
        raise StaticReTestFailure(
            "client arena switch must consume authenticated host authorization before stock dispatch")

    return "connected Last Game redirects at the native control boundary while automation selects New Game directly"


def test_wine_stage_savegames_uses_directory_mirror() -> str:
    stage_links_text = read_text(
        ROOT / "SolomonDarkModLauncher/src/Staging/StageSandboxCompatibilityLinks.cs"
    )
    required_tokens = (
        "if (IsWineRuntime())",
        "RecreateDirectoryMirror(linkPath, targetPath);",
        'Environment.GetEnvironmentVariable("WINEPREFIX")',
        'var malformedWineJunctionPath = directoryPath + "?";',
        "DeleteExistingPath(malformedWineJunctionPath);",
        "CopyDirectoryContents(sourcePath, directoryPath);",
    )
    missing = [token for token in required_tokens if token not in stage_links_text]
    if missing:
        raise StaticReTestFailure(
            "Wine savegames materialization is missing token(s): " +
            ", ".join(missing))
    return "Wine/Proton stages a real savegames directory and removes malformed junction residue"


def test_launcher_saves_are_isolated_link_gated_and_proton_persisted() -> str:
    command_client_text = read_text(
        ROOT / "SolomonDarkModLauncher.UI/src/Infrastructure/LauncherUiCommandClient.cs"
    )
    settings_text = read_text(
        ROOT / "SolomonDarkModLauncher.UI/src/Infrastructure/LauncherUiSettingsStore.cs"
    )
    session_text = read_text(
        ROOT / "SolomonDarkModLauncher.UI/src/Infrastructure/SteamWebsiteSessionClient.cs"
    )
    cloud_text = read_text(
        ROOT / "SolomonDarkModLauncher.UI/src/Infrastructure/CloudSaveClient.cs"
    )
    backup_text = read_text(
        ROOT / "SolomonDarkModLauncher.UI/src/Infrastructure/CloudSaveBackupCoordinator.cs"
    )
    main_window_text = read_text(
        ROOT / "SolomonDarkModLauncher.UI/src/ViewModels/MainWindowViewModel.cs"
    )

    required_pairs = (
        (settings_text, '"SolomonDarkMultiplayerBeta"'),
        (settings_text, 'SavesRoot = Path.Combine(SettingsRoot, "saves");'),
        (command_client_text, 'arguments.Add("--savegames-root");'),
        (command_client_text, "arguments.Add(saveCatalog_.Active.SavegamesRootPath);"),
        (command_client_text, 'arguments.Add("--no-invite-dialog");'),
        (session_text, '"directory-auth"'),
        (session_text, "SteamLinkedWebsiteAccount? LinkedAccount"),
        (cloud_text, "if (session.LinkedAccount is null)"),
        (cloud_text, "CloudBackupDisposition.NotLinked"),
        (backup_text, "if (usesDirectoryMirror_)"),
        (backup_text, "SaveDirectoryMirror.Replace("),
        (backup_text, "await BackupCoreAsync(cancellationToken);"),
        (main_window_text, "public bool CanCloseLauncher()"),
        (main_window_text, "The launcher stays open while the game runs"),
    )
    missing = [token for text, token in required_pairs if token not in text]
    if missing:
        raise StaticReTestFailure(
            "launcher save isolation or cloud backup contract is missing token(s): " +
            ", ".join(missing))

    save_argument = command_client_text.find('arguments.Add("--savegames-root");')
    launch_mode_switch = command_client_text.find("switch (mode)", save_argument)
    if save_argument == -1 or launch_mode_switch == -1 or save_argument > launch_mode_switch:
        raise StaticReTestFailure(
            "selected launcher save must be applied before every launch-mode branch")

    host_start = command_client_text.find("case LauncherUiCommandMode.HostSteam:")
    host_end = command_client_text.find(
        "case LauncherUiCommandMode.PrepareSteamJoin:", host_start)
    host_body = command_client_text[host_start:host_end]
    if host_start == -1 or host_end == -1 or '"--no-invite-dialog"' not in host_body:
        raise StaticReTestFailure(
            "Host Game must suppress only the automatic Steam invite picker")

    mirror_copyback = backup_text.find("SaveDirectoryMirror.Replace(")
    final_backup = backup_text.find(
        "await BackupCoreAsync(cancellationToken);", mirror_copyback)
    if mirror_copyback == -1 or final_backup == -1 or mirror_copyback > final_backup:
        raise StaticReTestFailure(
            "Proton save mirror must copy back locally before cloud backup")

    session_lookup = cloud_text.find(
        "var session = await sessionClient_.GetAsync(", cloud_text.find("BackupAsync("))
    link_gate = cloud_text.find(
        "if (session.LinkedAccount is null)", session_lookup)
    archive_build = cloud_text.find("CloudSaveArchive.Build(save)", link_gate)
    upload = cloud_text.find("HttpMethod.Put", link_gate)
    if not 0 <= session_lookup < link_gate < archive_build < upload:
        raise StaticReTestFailure(
            "cloud backup must verify the active Steam account link before snapshot or upload")

    return (
        "launcher saves remain local and isolated, Host avoids the invite picker, "
        "Steam linkage gates cloud backup, and Proton mirrors copy back before upload"
    )


def test_wsl_steam_launcher_applies_test_boneyard_before_process_start() -> str:
    launch_text = read_text(ROOT / "scripts/Launch-WslSteamMultiplayerClient.sh")
    required_tokens = (
        'test_boneyard_override="${SDMOD_TEST_SURVIVAL_BONEYARD_OVERRIDE:-}"',
        '[[ -f "$test_boneyard_override" ]]',
        '"SDMOD_TEST_SURVIVAL_BONEYARD_OVERRIDE=$(proton_path "$test_boneyard_override")"',
        'test_environment+=("SDMOD_TEST_BLANK_BONEYARD=1")',
        '"${test_environment[@]}"',
    )
    missing = [token for token in required_tokens if token not in launch_text]
    if missing:
        raise StaticReTestFailure(
            "WSL Steam test Boneyard launch contract is missing token(s): "
            + ", ".join(missing)
        )
    staging_environment = launch_text.find('"${test_environment[@]}"')
    proton_process = launch_text.find('"$proton" run "${args[@]}"')
    if staging_environment == -1 or proton_process == -1 or staging_environment > proton_process:
        raise StaticReTestFailure(
            "WSL Steam test Boneyard environment must be applied before Proton starts"
        )
    return "WSL Steam applies translated flat-Boneyard test inputs before Proton starts"


def test_wsl_steam_launcher_isolates_build_artifacts_from_live_host() -> str:
    launch_text = read_text(ROOT / "scripts/Launch-WslSteamMultiplayerClient.sh")
    required_tokens = (
        'build_artifacts="$root/runtime/wsl-steam-build-artifacts"',
        'mkdir -p "$build_artifacts"',
        '--artifacts-path "$build_artifacts"',
    )
    missing = [token for token in required_tokens if token not in launch_text]
    if missing:
        raise StaticReTestFailure(
            "WSL Steam launcher build can overwrite a live Windows host artifact: "
            + ", ".join(missing)
        )
    return "WSL Steam builds into isolated artifacts while the Windows host DLL is mapped"


def test_remote_progression_preserves_local_concentration_context() -> str:
    gameplay_api_text = read_text(
        ROOT / "SolomonDarkModLoader/include/mod_loader_gameplay_api.inl"
    )
    concentration_api_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_debug_and_spawn.inl"
    )
    skill_choices_text = read_source_unit(
        ROOT / "SolomonDarkModLoader/src/bot_runtime/public_api/skill_choices_api.inl"
    )

    required_pairs = (
        (gameplay_api_text, "bool RunWithParticipantConcentrationContext("),
        (concentration_api_text, "ScopedParticipantConcentrationContext context(binding);"),
        (concentration_api_text, "const bool operation_succeeded = operation();"),
        (concentration_api_text, "context.Restore();"),
        (concentration_api_text, "if (!context.restored)"),
    )
    missing = [token for text, token in required_pairs if token not in text]
    if missing:
        raise StaticReTestFailure(
            "remote progression Concentrate isolation is missing token(s): " +
            ", ".join(missing))

    protected_operations = (
        (
            "bool SyncParticipantProgressionToSharedLevelUp(",
            "bool SyncParticipantProgressionToSharedLevelUpAndRollChoices(",
            "SyncNativeBotProgressionLevel(",
        ),
        (
            "bool ApplyParticipantSkillChoiceOption(",
            "bool ApplyLocalPlayerSkillChoiceOption(",
            "ApplyNativeSkillChoiceToProgression(",
        ),
    )
    for start_token, end_token, native_call in protected_operations:
        start = skill_choices_text.find(start_token)
        end = skill_choices_text.find(end_token, start)
        body = skill_choices_text[start:end]
        context_call = body.find("RunWithParticipantConcentrationContext(")
        operation_call = body.find(native_call)
        if (
            start == -1 or end == -1 or context_call == -1 or
            operation_call == -1 or context_call > operation_call
        ):
            raise StaticReTestFailure(
                f"{start_token} does not protect {native_call} with participant Concentrate context")

    context_start = concentration_api_text.find(
        "bool RunWithParticipantConcentrationContext(")
    context_end = concentration_api_text.find(
        "bool TryReconcileParticipantConcentrationRuntimeSelections(",
        context_start,
    )
    context_body = concentration_api_text[context_start:context_end]
    install = context_body.find("ScopedParticipantConcentrationContext context(binding);")
    operation = context_body.find("operation();")
    restore = context_body.find("context.Restore();")
    if (
        context_start == -1 or context_end == -1 or install == -1 or
        operation == -1 or restore == -1 or not install < operation < restore
    ):
        raise StaticReTestFailure(
            "participant Concentrate guard must install, invoke, and restore in that order")

    return "remote native level and skill mutations restore the local player's Concentrate lanes"


def test_remote_progression_uses_passive_authoritative_hydration() -> str:
    native_sync_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/native_progression_sync.inl"
    )
    level_handlers_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/level_up_packet_handlers.inl"
    )
    barrier_authority_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/level_up_barrier_authority.inl"
    )
    powerup_authority_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/powerup_loot_authority.inl"
    )
    loot_result_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/loot_pickup_packet_handlers.inl"
    )

    required_pairs = (
        (native_sync_text, "bool HydrateAuthoritativeRemoteProgressionEntryState("),
        (native_sync_text, "participant_id == g_local_transport.local_peer_id"),
        (native_sync_text, "kStandaloneWizardProgressionActiveFlagOffset,"),
        (native_sync_text, "kStandaloneWizardProgressionVisibleFlagOffset,"),
        (native_sync_text, "verified.active != resulting_active"),
        (native_sync_text, "verified.visible != resulting_visible"),
        (native_sync_text, "kNativeProgressionReconcileMaxEntryWritesPerTick"),
        (native_sync_text, "desired.active,\n                            desired.visible,"),
        (native_sync_text, "TryReconcileParticipantConcentrationRuntimeSelections("),
        (level_handlers_text, "ApplyAuthoritativeRemoteSkillRankDelta("),
        (
            level_handlers_text,
            "packet.resulting_active,\n                    1,\n                    &error_message",
        ),
        (barrier_authority_text, "ApplyAuthoritativeRemoteSkillRankDelta("),
        (
            powerup_authority_text,
            "pending->powerup.skill_rank_resulting_active,\n                  1,",
        ),
        (
            loot_result_text,
            "packet.powerup_skill_resulting_active,\n                                  1,",
        ),
    )
    missing = [token for text, token in required_pairs if token not in text]
    if missing:
        raise StaticReTestFailure(
            "passive authoritative remote progression hydration is missing token(s): "
            + ", ".join(missing)
        )

    observer_paths = (
        native_sync_text,
        level_handlers_text,
        barrier_authority_text,
        powerup_authority_text,
        loot_result_text,
    )
    if any("ApplyParticipantSkillChoiceOption(" in text for text in observer_paths):
        raise StaticReTestFailure(
            "observer-owned progression must not execute the stock skill-choice path"
        )

    helper_start = native_sync_text.find(
        "bool HydrateAuthoritativeRemoteProgressionEntryState("
    )
    helper_end = native_sync_text.find(
        "bool ApplyAuthoritativeRemoteSkillRankDelta(", helper_start
    )
    helper_body = native_sync_text[helper_start:helper_end]
    forbidden_helper_calls = (
        "ApplyParticipantSkillChoiceOption(",
        "ApplyNativeSkillChoiceToProgression(",
        "CallNativeActorProgressionRefresh(",
        "RefreshParticipantNativeProgression(",
    )
    present = [token for token in forbidden_helper_calls if token in helper_body]
    if helper_start == -1 or helper_end == -1 or present:
        raise StaticReTestFailure(
            "authoritative remote hydration must remain a verified field-only operation: "
            + ", ".join(present)
        )
    if "TryApplyParticipantConcentrationSelections(" in native_sync_text:
        raise StaticReTestFailure(
            "remote progression reconciliation must not invoke stock Concentrate refresh"
        )

    return "remote skillbook, level-up, and powerup state use exact passive hydration without observer-side stock callbacks"


def test_steam_peer_disconnect_resets_remote_session_epoch() -> str:
    lifecycle_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/remote_peer_lifecycle.inl"
    )
    public_api_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/public_cast_loot_api.inl"
    )
    transport_text = read_text(
        ROOT / "SolomonDarkModLoader/src/multiplayer_local_transport.cpp"
    )
    steam_session_text = read_source_unit(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_steam_session/lobby_and_events.inl"
    )

    required_pairs = (
        (transport_text, '#include "multiplayer_local_transport/remote_peer_lifecycle.inl"'),
        (public_api_text, "ResetRemoteParticipantSessionEpoch("),
        (lifecycle_text, "QueueParticipantDestroy(participant_id"),
        (lifecycle_text, "last_cast_sequence_by_participant.erase(participant_id)"),
        (
            lifecycle_text,
            "last_spell_effect_packet_sequence_by_participant.erase(\n"
            "        participant_id)",
        ),
        (
            lifecycle_text,
            "last_air_chain_packet_sequence_by_participant.erase(\n"
            "        participant_id)",
        ),
        (
            lifecycle_text,
            "native_progression_reconcile_by_participant.erase(\n"
            "        participant_id)",
        ),
        (lifecycle_text, "issued_level_up_offers_by_id.erase(it)"),
        (lifecycle_text, "state.participants.erase("),
        (lifecycle_text, "state.spell_effect_snapshots.erase("),
        (lifecycle_text, "state.world_snapshot = WorldSnapshotRuntimeInfo{}"),
        (lifecycle_text, "state.loot_snapshot = LootSnapshotRuntimeInfo{}"),
        (
            steam_session_text,
            "if (participant == nullptr && peer.authenticated)",
        ),
        (
            steam_session_text,
            "participant = UpsertRemoteParticipant(",
        ),
    )
    missing = [token for text, token in required_pairs if token not in text]
    if missing:
        raise StaticReTestFailure(
            "Steam reconnect epoch reset is missing token(s): " + ", ".join(missing)
        )

    unregister_start = public_api_text.find("void UnregisterSteamGameplayPeer(")
    unregister_end = public_api_text.find(
        "bool SubmitSteamGameplayPacket(", unregister_start
    )
    unregister_body = public_api_text[unregister_start:unregister_end]
    reset = unregister_body.find("ResetRemoteParticipantSessionEpoch(")
    clear_authority = unregister_body.find(
        "g_local_transport.configured_remote = TransportPeerEndpoint{}"
    )
    if (
        unregister_start == -1
        or unregister_end == -1
        or reset == -1
        or clear_authority == -1
        or reset > clear_authority
    ):
        raise StaticReTestFailure(
            "Steam peer unregister must reset participant-owned state before "
            "clearing the configured authority"
        )
    if "participant->transport_connected = false" in unregister_body:
        raise StaticReTestFailure(
            "Steam disconnect must remove the stale participant epoch, not retain "
            "its monotonic progression revisions"
        )

    return "Steam disconnect destroys the native proxy and removes every participant-owned replication epoch before authenticated re-upsert"


def test_steam_spell_behavior_verifiers_use_real_upgrades_and_wait_for_delivery() -> str:
    behavior_text = read_text(
        ROOT / "tools/verify_steam_friend_active_pair_spell_behavior.py"
    )
    explode_text = read_text(
        ROOT / "tools/verify_multiplayer_fireball_explode_effect_sync.py"
    )

    required_pairs = (
        (behavior_text, 'os.environ.get("SDMOD_STEAM_HOST_INSTANCE", "").strip()'),
        (behavior_text, 'os.environ.get("SDMOD_STEAM_CLIENT_INSTANCE", "").strip()'),
        (behavior_text, "both Steam instance environment variables are required"),
        (behavior_text, "Steam behavior log does not exist"),
        (behavior_text, '"--owners"'),
        (behavior_text, 'if args.owners != "both":'),
        (behavior_text, "def select_matching_owners("),
        (behavior_text, 'output["owner_primary_spells"] = primary_spell_ids'),
        (behavior_text, "for label, owner in fire_owner_labels:"),
        (behavior_text, "for label, owner in air_owner_labels:"),
        (behavior_text, "def ensure_upgrade_rank("),
        (behavior_text, "def owner_context("),
        (behavior_text, "def require_primary_spell("),
        (behavior_text, "FIRE_PRIMARY_SPELL_ID = 1011"),
        (behavior_text, "AIR_PRIMARY_SPELL_ID = 1013"),
        (behavior_text, "rank_setup = ensure_upgrade_rank("),
        (behavior_text, "explode_rank_setup = ensure_upgrade_rank("),
        (behavior_text, "embers_rank_setup = ensure_upgrade_rank("),
        (behavior_text, '"explode": explode_rank_setup'),
        (behavior_text, '"embers": embers_rank_setup'),
        (
            behavior_text,
            'owner_labels = (("host_owned", "host"), ("client_owned", "client"))',
        ),
        (behavior_text, "verify_explode(pair, owner=owner)"),
        (behavior_text, "verify_embers(pair, owner=owner)"),
        (behavior_text, "owner=owner,"),
        (explode_text, "delivery_deadline = time.monotonic() + 8.0"),
        (explode_text, "if receiver_cast_queued and receiver_cast_prepped:"),
        (explode_text, "time.sleep(0.05)"),
    )
    missing = [token for text, token in required_pairs if token not in text]
    if missing:
        raise StaticReTestFailure(
            "Steam spell behavior verification is missing token(s): "
            + ", ".join(missing)
        )
    for stale_default in ("steam-host-gameplay10", "wsl-steam-gameplay10"):
        if stale_default in behavior_text:
            raise StaticReTestFailure(
                "Steam spell behavior verification must not silently read a "
                f"stale default instance log: {stale_default}"
            )

    explode_start = behavior_text.find("def verify_explode(")
    embers_start = behavior_text.find("def verify_embers(", explode_start)
    chaining_start = behavior_text.find("def positive_chaining_evidence(", embers_start)
    explode_body = behavior_text[explode_start:embers_start]
    embers_body = behavior_text[embers_start:chaining_start]
    if (
        explode_start == -1
        or embers_start == -1
        or chaining_start == -1
        or "desired_rank=1" not in explode_body
        or explode_body.find("ensure_upgrade_rank(")
        > explode_body.find("find_upgraded_explode_offset(")
    ):
        raise StaticReTestFailure(
            "Steam Explode verification must acquire rank one authoritatively "
            "before searching upgraded impact geometry"
        )
    first_embers_upgrade = embers_body.find("explode_rank_setup = ensure_upgrade_rank(")
    second_embers_upgrade = embers_body.find("embers_rank_setup = ensure_upgrade_rank(")
    fragment_phase = embers_body.find("run_fragment_phase_with_impact_retry(")
    if not 0 <= first_embers_upgrade < second_embers_upgrade < fragment_phase:
        raise StaticReTestFailure(
            "Steam Embers verification must acquire Explode then Embers through "
            "validated level-up offers before casting"
        )

    source_cast = explode_text.find("post_source_cast =")
    delivery_wait = explode_text.find("delivery_deadline =", source_cast)
    damage_observation = explode_text.find("damage = observe_pair_damage(", delivery_wait)
    if not 0 <= source_cast < delivery_wait < damage_observation:
        raise StaticReTestFailure(
            "Steam Explode verification must wait for receiver cast preparation "
            "between the source cast and damage observation"
        )

    return "Steam spell behavior tests use authoritative prerequisite upgrades and bounded receiver-delivery polling"


def test_steam_combat_stat_profiles_isolate_concentration() -> str:
    verifier_text = read_text(
        ROOT / "tools/verify_steam_friend_active_pair_combat_stats.py"
    )
    context_text = read_text(
        ROOT / "tools/steam_friend_behavior_context.py"
    )
    required_tokens = (
        "PROFILE_SUITES = {",
        '"meditation": ("meditation",)',
        '"faster-caster": ("faster_caster",)',
        '"faster-caster-air": ("faster_caster_air",)',
        "def assert_concentrated_row(",
        "def require_fresh_combat_profile(",
        'output["initial_profile_state"] = require_fresh_combat_profile(pair)',
        "launch a fresh run for each",
        '"owner_process"',
        '"observer_slot"',
        "requires a pristine profile with row",
        'choices=tuple(PROFILE_SUITES)',
        "suites = PROFILE_SUITES[args.profile]",
    )
    missing = [token for token in required_tokens if token not in verifier_text]
    if missing:
        raise StaticReTestFailure(
            "Steam combat-stat profile isolation is missing token(s): "
            + ", ".join(missing)
        )
    context_tokens = (
        "config_root = steam_skill_config_root()",
        "upgrades.load_skill_configs(config_root)",
        "config_root=config_root",
    )
    missing_context = [
        token for token in context_tokens if token not in context_text
    ]
    if missing_context:
        raise StaticReTestFailure(
            "Steam combat-stat behavior reads non-Steam config state: "
            + ", ".join(missing_context)
        )
    if '"--start-at"' in verifier_text:
        raise StaticReTestFailure(
            "Steam combat-stat verification must not resume on a contaminated "
            "monotonic-progression pair"
        )

    general_start = verifier_text.find('"general": (')
    general_end = verifier_text.find('),', general_start)
    general_profile = verifier_text[general_start:general_end]
    ordered_suites = (
        '"transient_status"',
        '"mindstar"',
        '"battle_siege"',
        '"telekinesis"',
        '"focus"',
    )
    positions = [general_profile.find(suite) for suite in ordered_suites]
    if any(position == -1 for position in positions) or positions != sorted(positions):
        raise StaticReTestFailure(
            "the general Steam combat-stat profile must run strict Mindstar before "
            "remote Fireball trials and omit concentration-sensitive suites"
        )
    if (
        '"meditation"' in general_profile
        or '"faster_caster"' in general_profile
        or '"faster_caster_air"' in general_profile
    ):
        raise StaticReTestFailure(
            "Meditation and both Faster Caster modalities require their own "
            "pristine Steam pairs"
        )

    mindstar_text = read_text(
        ROOT / "tools/verify_multiplayer_mindstar_behavior_sync.py"
    )
    mindstar_direction_start = mindstar_text.find("def run_direction(")
    mindstar_direction_end = mindstar_text.find(
        "\ndef main()", mindstar_direction_start
    )
    mindstar_direction = mindstar_text[
        mindstar_direction_start:mindstar_direction_end
    ]
    pre_prime_cleanup = mindstar_direction.find(
        "pre_prime_cleanup = cleanup_live_enemies()"
    )
    spawner_prime = mindstar_direction.find(
        "manual_spawner_prime = enable_manual_stock_spawner_combat()"
    )
    baseline_cast = mindstar_direction.find(
        "baseline_cast = run_fireball_trial("
    )
    if not 0 <= pre_prime_cleanup < spawner_prime < baseline_cast:
        raise StaticReTestFailure(
            "Mindstar must remove the previous owner's targets, establish the "
            "exact stock arena spawner, then begin its manual-target Fireball trial"
        )
    mindstar_damage_tokens = (
        "before_source_cast=lambda: reset_local_cast_observation(",
        "cast_observation = read_local_cast_observation(",
        "def measure_primary_damage_trial(",
        '"method": "single_fire_projectile_authoritative_damage"',
        '"method": "client_air_damage_claim_quantum"',
        'observation["damage_claim_samples"]',
        "authoritative_damage=authoritative_damage",
        "if primary_entry == FIRE_PRIMARY_ENTRY:",
        'damage["primary_damaged"] and not damage["secondary_damaged"]',
        "elif primary_entry == AIR_PRIMARY_ENTRY:",
        'expected_geometry = "selected-target Air damage"',
        "receiver_log_offset = log_position(cast_direction.receiver_log)",
        'float(active_measurement["quantum"])',
        '/ float(baseline_measurement["quantum"])',
    )
    missing_mindstar_damage = [
        token for token in mindstar_damage_tokens if token not in mindstar_text
    ]
    if missing_mindstar_damage:
        raise StaticReTestFailure(
            "Mindstar mixed Fire/Air behavior verification is missing semantic "
            "per-hit measurement token(s): " + ", ".join(missing_mindstar_damage)
        )

    log_probe_text = read_text(ROOT / "tools/multiplayer_log_probe.py")
    spell_cast_text = read_text(ROOT / "tools/verify_spell_cast_sync.py")
    log_probe_tokens = (
        'with path.open("rb") as stream:',
        "stream.seek(offset)",
        "return path.stat().st_size",
        "exc.errno != errno.ENODATA",
        "from multiplayer_log_probe import log_after, log_position, read_log",
    )
    combined_log_text = log_probe_text + "\n" + spell_cast_text
    missing_log_probe = [
        token for token in log_probe_tokens if token not in combined_log_text
    ]
    if missing_log_probe or "len(read_log(direction." in spell_cast_text:
        raise StaticReTestFailure(
            "multiplayer cast evidence must use byte-positioned cross-variant "
            "log reads: " + ", ".join(missing_log_probe)
        )
    for behavior_path in (
        ROOT / "tools/verify_multiplayer_focus_behavior_sync.py",
        ROOT / "tools/verify_multiplayer_meditation_behavior_sync.py",
        ROOT / "tools/verify_multiplayer_faster_caster_behavior_sync.py",
    ):
        behavior_log_text = read_text(behavior_path)
        if "len(read_log(direction." in behavior_log_text:
            raise StaticReTestFailure(
                f"{behavior_path.name} retained character-positioned log offsets"
            )
        if "log_position(direction." not in behavior_log_text:
            raise StaticReTestFailure(
                f"{behavior_path.name} does not use byte-positioned log offsets"
            )
    faster_caster_text = read_text(
        ROOT / "tools/verify_multiplayer_faster_caster_behavior_sync.py"
    )
    faster_claim_tokens = (
        "CONTINUOUS_PRIMARY_ENTRIES = frozenset((AIR_PRIMARY_ENTRY,))",
        "if direction.source_pipe == CLIENT_PIPE:",
        'observation["damage_associated_skill_id"] != primary_entry',
        'f"{direction.name} continuous Air damage claims were not "',
    )
    missing_faster_claims = [
        token for token in faster_claim_tokens if token not in faster_caster_text
    ]
    if missing_faster_claims:
        raise StaticReTestFailure(
            "continuous Faster Caster must stay scoped to its exact Air claim path: "
            + ", ".join(missing_faster_claims)
        )

    all_stats_text = read_text(ROOT / "tools/verify_multiplayer_all_stat_sync.py")
    steam_progression_text = read_text(
        ROOT / "tools/verify_steam_friend_active_pair_progression.py"
    )
    mana_probe_tokens = (
        "def query_mana_observation(",
        "def set_runtime_test_godmode_enabled(",
        "previous_godmode = set_runtime_test_godmode_enabled(target_pipe, False)",
        "return _sample_mana_recovery_while_godmode_suspended(target_id, duration)",
        "finally:\n        set_runtime_test_godmode_enabled(target_pipe, previous_godmode)",
        "local runtime_before = tonumber(before and before.mana_current) or -1",
        "local native = progression ~= 0 and sd.debug.read_float(",
        "local runtime_after = tonumber(after and after.mana_current) or -1",
        "def distance_from_runtime_bracket(",
        "def distance_from_runtime_replication_window(",
        '"owner_runtime_bracket_error": distance_from_runtime_bracket(owner)',
        '"observer_runtime_bracket_error": distance_from_runtime_bracket(',
        '"owner_runtime_window_error": owner_runtime_window_error',
        '"observer_runtime_window_error": observer_runtime_window_error',
        "previous_owner_observation: dict[str, float] | None = owner",
        "previous_observer_observation: dict[str, float] | None = observer",
        'precondition_mp = float(before["native"]["mp"])',
        "settle_ceiling = max(5.0, min(100.0, precondition_mp * 0.5))",
        'float(sample["observer_runtime_window_error"])',
        "owner_gain / sampled_duration",
        "replication_tolerance = max(1.0, observed_rate * 1.1)",
        "stable_set_result = set_local_mana(target_pipe, stable_target)",
        "stable_deadline = time.monotonic() + 2.0",
        '"observer_native_mp": stable_observer["native"]',
        '"observer_runtime_before_mp": stable_observer["runtime_before"]',
        '"observer_runtime_after_mp": stable_observer["runtime_after"]',
    )
    missing_mana_probe = [
        token for token in mana_probe_tokens if token not in all_stats_text
    ]
    if missing_mana_probe:
        raise StaticReTestFailure(
            "live mana recovery must use adjacent runtime/native/runtime samples: "
            + ", ".join(missing_mana_probe)
        )
    stat_finalize_tokens = (
        "def run_stats_finalize_phase(",
        'choices=("catalog", "upgrades", "stats", "stats-finalize")',
        '"--resume-output"',
        'completed_step_count != len(steps)',
        'for direction in ("host_owned", "client_owned")',
        'output["final"] = stats.verify_final_maxima(',
        'output["final_ranked_property_matrix"]',
        'output["final_mana_recovery"]',
        'final_gain <= baseline_gain + 0.5',
    )
    missing_stat_finalize = [
        token for token in stat_finalize_tokens if token not in steam_progression_text
    ]
    if missing_stat_finalize:
        raise StaticReTestFailure(
            "Steam stat finalization must validate a complete matrix before "
            "measuring max-rank behavior: " + ", ".join(missing_stat_finalize)
        )

    mindstar_semantic_tokens = (
        "def compact_native_output_buffer(",
        '"semantic_exact_match": True',
        '"native_output_buffer_diagnostic": {',
        'stable_shape_fields = (\n        "progression_level",',
        '"count": spell["raw_output_count"]',
        '"outputs": spell["raw_outputs"]',
        '"mana_spend_cost_available": spell["mana_spend_cost_available"]',
        '"builder_seh_code": spell["builder_seh_code"]',
        "def ensure_mindstar_inactive(",
        "finally:\n        deactivated = ensure_mindstar_inactive(",
        "finally:\n        final_deactivated = ensure_mindstar_inactive(",
    )
    missing_mindstar_semantics = [
        token for token in mindstar_semantic_tokens if token not in mindstar_text
    ]
    if missing_mindstar_semantics:
        raise StaticReTestFailure(
            "Mindstar must compare semantic spell state and retain the stock "
            "high-water output buffer only as diagnostics: "
            + ", ".join(missing_mindstar_semantics)
        )

    transient_status_text = read_text(
        ROOT / "tools/verify_multiplayer_transient_status_sync.py"
    )
    transient_timing_tokens = (
        "POISON_REPLICATION_MAX_TICK_DRIFT * POISON_DAMAGE_PER_TICK",
        "last_owner_before_observer = query_poison_status(direction.owner_pipe)",
        '>= last_owner["hp"] - POISON_HP_QUANTIZATION_TOLERANCE',
        '<= last_owner_before_observer["hp"] + maximum_hp_drift',
        "maximum_tick_drift=POISON_REPLICATION_MAX_TICK_DRIFT",
        "def wait_for_observer_duration_advance(",
        'last["modifier_ticks"] < active_modifier_ticks',
        "duration_drift <= POISON_REPLICATION_MAX_TICK_DRIFT",
        "2 * POISON_REPLICATION_MAX_TICK_DRIFT",
        "owner_ticks > injected_ticks",
        "injected_ticks - owner_ticks > POISON_OWNER_CORRECTION_MAX_TICK_DRIFT",
    )
    missing_transient_timing = [
        token for token in transient_timing_tokens if token not in transient_status_text
    ]
    if missing_transient_timing:
        raise StaticReTestFailure(
            "transient poison HP parity must use bracketed samples and the same "
            "native-tick drift bound as duration replication: "
            + ", ".join(missing_transient_timing)
        )
    invalid_post_observer_hp_comparison = (
        'abs(last_observer["hp"] - last_owner["hp"]) <= maximum_hp_drift'
    )
    if invalid_post_observer_hp_comparison in transient_status_text:
        raise StaticReTestFailure(
            "transient poison HP parity must not compare an observer sample "
            "to a later owner sample without accounting for owner damage "
            "during the probe interval"
        )
    compact_start = mindstar_text.find("def compact_spell(")
    compact_end = mindstar_text.find(
        "\ndef compact_native_output_buffer(", compact_start
    )
    compact_spell = mindstar_text[compact_start:compact_end]
    forbidden_compact_fields = (
        'spell["raw_output_count"]',
        'spell["raw_outputs"]',
    )
    present_compact_fields = [
        field for field in forbidden_compact_fields if field in compact_spell
    ]
    if present_compact_fields:
        raise StaticReTestFailure(
            "Mindstar semantic parity must not treat the stock grow-only output "
            "buffer as replicated progression state: "
            + ", ".join(present_compact_fields)
        )

    battle_siege_text = read_text(
        ROOT / "tools/verify_multiplayer_battle_siege_behavior_sync.py"
    )
    battle_siege_tokens = (
        "def reset_local_cast_observation(",
        "sd.debug.reset_local_cast_observation(",
        "def read_local_cast_observation(",
        "sd.debug.get_local_cast_observation(",
        "def estimate_fundamental_damage_quantum(",
        "    wait_for_cast_runtime_ready,",
        '"mana_spent_total"',
        '"client_air_damage_claim_quantum"',
        "authoritative_damage=damage",
        '"single_fire_projectile_authoritative_damage"',
        '"host_primary_entry"] == FIRE_PRIMARY_ENTRY',
        '"client_primary_entry"] == AIR_PRIMARY_ENTRY',
        'expected_battle_ratio = (',
        'actual_battle_ratio = battle_trial["mana_spend"] / base["mana_spend"]',
        'expected_siege_ratio = (',
        'siege_trial["native_damage_quantum"]',
        '/ base["native_damage_quantum"]',
        'for field in ("battle_actual_mana_ratio", "siege_actual_damage_ratio")',
    )
    missing_battle_siege = [
        token for token in battle_siege_tokens if token not in battle_siege_text
    ]
    if missing_battle_siege:
        raise StaticReTestFailure(
            "mixed-element Battle/Siege behavior verification is missing token(s): "
            + ", ".join(missing_battle_siege)
        )
    forbidden_battle_siege_tokens = (
        "sd.debug.watch_write(",
        "sd.debug.get_write_hits(",
        "sd.events.on('runtime.tick'",
        "arm_mana_write_watch",
        "arm_damage_write_watch",
        "native_damage_per_write",
    )
    present_forbidden = [
        token
        for token in forbidden_battle_siege_tokens
        if token in battle_siege_text
    ]
    if present_forbidden:
        raise StaticReTestFailure(
            "Battle/Siege must use bounded semantic cast observations, not hot-page "
            "write watches or net resource sampling: "
            + ", ".join(present_forbidden)
        )
    cast_trial_start = battle_siege_text.find("def run_cast_trial(")
    cast_trial_end = battle_siege_text.find(
        "\ndef verify_behavior_contracts(", cast_trial_start
    )
    cast_trial = battle_siege_text[cast_trial_start:cast_trial_end]
    if cast_trial.count("cast_fireball_pair(") != 1:
        raise StaticReTestFailure(
            "Battle/Siege must measure mana, damage, and replication from one "
            "non-intrusively observed native cast"
        )
    semantic_observation_sources = (
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/player_mana_hooks.inl",
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/client_enemy_damage_sync.inl",
        ROOT
        / "SolomonDarkModLoader/src/lua_engine_bindings_debug/functions_combat_observations.inl",
    )
    semantic_observation_text = "\n".join(
        read_text(path) for path in semantic_observation_sources
    )
    semantic_observation_tokens = (
        "g_local_mana_delta_observation_mutex",
        "observation.spent_total -= applied_delta",
        "RecordLocalEnemyDamageClaimObservationInternal(",
        "if (!force_resend)",
        "const bool armed = ResetLocalPlayerManaDeltaObservation();",
        "TakeLocalPlayerManaDeltaObservation(&mana)",
        "multiplayer::ResetLocalEnemyDamageClaimObservation(network_actor_id);",
        "multiplayer::TakeLocalEnemyDamageClaimObservation(",
        "damage.claimed_damage_samples[index]",
    )
    missing_semantic_observation = [
        token
        for token in semantic_observation_tokens
        if token not in semantic_observation_text
    ]
    if missing_semantic_observation:
        raise StaticReTestFailure(
            "bounded semantic Battle/Siege observation is missing token(s): "
            + ", ".join(missing_semantic_observation)
        )

    fireball_cast_text = read_text(
        ROOT / "tools/verify_multiplayer_fireball_explode_effect_sync.py"
    )
    if fireball_cast_text.count(
        'hp=float(pair.get("target_hp", TARGET_HP))'
    ) < 2:
        raise StaticReTestFailure(
            "shared primary-cast fixtures must preserve the requested target HP "
            "through their final stock spatial-index refresh"
        )

    return (
        "Steam combat-stat behavior runs in concentration-safe pristine-pair "
        "profiles, primes the exact stock arena spawner, and measures mixed-element "
        "Battle/Siege behavior through bounded semantic observations and normalized ratios"
    )
