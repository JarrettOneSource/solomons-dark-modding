"""Steam session, protocol, and application identity contracts."""

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
    MULTIPLAYER_PROTOCOL,
    ROOT,
    StaticReTestFailure,
    WORLD_SNAPSHOT_FRAGMENTATION,
    WORLD_SNAPSHOT_RECONCILIATION,
    read_multiplayer_runtime_state_source,
    read_multiplayer_transport_source,
    read_source_unit,
    read_text,
)

def test_world_snapshots_are_complete_mtu_sized_generations() -> str:
    protocol_text = read_text(MULTIPLAYER_PROTOCOL)
    transport_text = read_multiplayer_transport_source()
    steam_gameplay_queue_text = read_text(
        ROOT / "SolomonDarkModLoader/src/multiplayer_steam_gameplay_queue.cpp"
    )
    fragmentation_text = read_text(WORLD_SNAPSHOT_FRAGMENTATION)
    reconciliation_text = read_source_unit(WORLD_SNAPSHOT_RECONCILIATION)
    run_lifecycle_text = read_source_unit(
        ROOT / "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks.inl"
    )

    required_tokens = (
        (protocol_text, "constexpr std::uint16_t kProtocolVersion = 77;"),
        (protocol_text, "constexpr std::uint32_t kWorldSnapshotActorsPerFragment = 3;"),
        (protocol_text, "constexpr std::uint32_t kWorldSnapshotMaxLogicalActors = 512;"),
        (protocol_text, "std::uint32_t snapshot_id;"),
        (protocol_text, "std::uint16_t fragment_index;"),
        (protocol_text, "std::uint16_t fragment_count;"),
        (protocol_text, "std::uint16_t actor_start_index;"),
        (protocol_text, "std::uint16_t actor_count;"),
        (protocol_text, "std::uint32_t actor_total_count;"),
        (
            protocol_text,
            "WorldActorSnapshotPacketState actors[kWorldSnapshotActorsPerFragment];",
        ),
        (protocol_text, "static_assert(sizeof(WorldSnapshotPacket) == 1032"),
        (fragmentation_text, "struct CompleteWorldSnapshotPacketState"),
        (fragmentation_text, "struct PendingWorldSnapshotAssembly"),
        (fragmentation_text, "struct PendingWorldSnapshotAssemblies"),
        (
            fragmentation_text,
            "constexpr std::size_t kPendingWorldSnapshotAssemblyLimit = 8;",
        ),
        (
            fragmentation_text,
            "constexpr std::uint64_t kPendingWorldSnapshotAssemblyMaxAgeMs = 500;",
        ),
        (fragmentation_text, "std::deque<PendingWorldSnapshotAssembly> assemblies;"),
        (fragmentation_text, "PrunePendingWorldSnapshotAssemblies("),
        (fragmentation_text, "bool TryAcceptWorldSnapshotFragment("),
        (
            fragmentation_text,
            "assembly->received_fragment_count == assembly->fragment_count",
        ),
        (transport_text, "BuildLocalWorldSnapshot("),
        (transport_text, "BuildWorldSnapshotFragmentPackets("),
        (transport_text, "for (const auto& packet : packets)"),
        (transport_text, "TryAcceptWorldSnapshotFragment("),
        (
            transport_text,
            "PublishWorldSnapshotRuntimeInfo(complete_snapshot, now_ms)",
        ),
        (
            transport_text,
            "kLocalTransportWorldSnapshotReliableCheckpointIntervalMs = 1000",
        ),
        (reconciliation_text, "kWorldSnapshotApplyStaleMs = 1200"),
        (transport_text, "last_world_snapshot_reliable_checkpoint_ms"),
        (transport_text, "const bool reliable_checkpoint ="),
        (transport_text, "SteamNetworkSendMode::ReliableNoNagle"),
        (steam_gameplay_queue_text, "Steam gameplay send rejected."),
        (transport_text, "steam_reliable_send_failures"),
    )
    missing = [token for text, token in required_tokens if token not in text]
    if missing:
        raise StaticReTestFailure(
            "complete fragmented world snapshot contract is incomplete: "
            + ", ".join(missing)
        )

    forbidden_tokens = (
        (protocol_text, "kWorldSnapshotMaxActors"),
        (protocol_text, "WorldSnapshotFlagTruncated"),
        (transport_text, "BuildLocalWorldSnapshotPacket"),
        (transport_text, "WorldSnapshotFlagTruncated"),
        (reconciliation_text, "snapshot.truncated"),
        (run_lifecycle_text, "snapshot.truncated"),
        (transport_text, "PendingWorldSnapshotAssembly pending_world_snapshot;"),
    )
    present = [token for text, token in forbidden_tokens if token in text]
    if present:
        raise StaticReTestFailure(
            "partial world snapshot fallback remains active: " + ", ".join(present)
        )

    actors_per_fragment_match = re.search(
        r"kWorldSnapshotActorsPerFragment\s*=\s*(\d+)", protocol_text
    )
    maximum_actor_match = re.search(
        r"kWorldSnapshotMaxLogicalActors\s*=\s*(\d+)", protocol_text
    )
    packet_size_match = re.search(
        r"sizeof\(WorldSnapshotPacket\)\s*==\s*(\d+)", protocol_text
    )
    if (
        not actors_per_fragment_match
        or not maximum_actor_match
        or not packet_size_match
    ):
        raise StaticReTestFailure(
            "world snapshot fragment constants are not statically measurable"
        )

    actors_per_fragment = int(actors_per_fragment_match.group(1))
    maximum_actors = int(maximum_actor_match.group(1))
    packet_size = int(packet_size_match.group(1))
    retail_wave_actor_count = 80
    if maximum_actors < retail_wave_actor_count:
        raise StaticReTestFailure(
            f"logical world snapshots cannot represent a retail {retail_wave_actor_count}-enemy wave"
        )
    if packet_size > 1280:
        raise StaticReTestFailure(
            f"world snapshot fragment is {packet_size} bytes instead of staying below 1280 bytes"
        )
    expected_fragments = math.ceil(
        retail_wave_actor_count / actors_per_fragment
    )
    if expected_fragments != 27:
        raise StaticReTestFailure(
            f"retail 80-enemy generation should be 27 fragments, got {expected_fragments}"
        )

    return (
        "world snapshots publish only complete generations across "
        f"{expected_fragments} MTU-sized fragments for an 80-enemy retail wave, "
        "retain bounded interleaved assemblies, and send reliable convergence checkpoints"
    )


def test_packet_send_mode_dispatch_is_type_safe() -> str:
    outgoing_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/outgoing_packet_sync.inl"
    )
    required_tokens = (
        "SteamNetworkSendMode SteamSendModeForPacket(const CastPacket& packet)",
        "template <typename Packet>\nSteamNetworkSendMode SteamSendModeForPacket(const Packet& packet)",
        "case PacketKind::WorldSnapshot:\n        // Ordinary generations are disposable visual updates.",
        "return SteamNetworkSendMode::UnreliableNoDelay;",
        "SteamSendModeForPacket(packet));",
    )
    missing = [token for token in required_tokens if token not in outgoing_text]
    if missing:
        raise StaticReTestFailure(
            "typed Steam send-mode dispatch is incomplete: " + ", ".join(missing)
        )

    forbidden_tokens = (
        "SteamSendModeForPacket(const void*",
        "std::memcpy(&cast, packet, sizeof(cast))",
    )
    present = [token for token in forbidden_tokens if token in outgoing_text]
    if present:
        raise StaticReTestFailure(
            "raw packet send-mode inspection can read beyond the concrete packet: "
            + ", ".join(present)
        )

    world_case = outgoing_text.find("case PacketKind::WorldSnapshot:")
    no_delay = outgoing_text.find(
        "return SteamNetworkSendMode::UnreliableNoDelay;", world_case
    )
    switch_end = outgoing_text.find("default:", world_case)
    if not 0 <= world_case < no_delay < switch_end:
        raise StaticReTestFailure(
            "ordinary fragmented world generations must be disposable NoDelay updates"
        )

    return "Steam send-mode selection is type-safe, keeps ordinary world generations disposable, and uses bounded reliable convergence checkpoints"


def test_steam_pair_driver_rejects_ended_runs_before_client_navigation() -> str:
    query_text = read_text(ROOT / "tools/verify_local_multiplayer_sync.py")
    driver_text = read_text(ROOT / "tools/drive_steam_friend_active_pair.py")

    required_query_tokens = (
        "if participant.is_owner then",
        'emit("local.in_run", local_participant and local_participant.in_run or false)',
    )
    missing_query = [
        token for token in required_query_tokens if token not in query_text
    ]
    if missing_query:
        raise StaticReTestFailure(
            "Steam pair query does not expose authoritative local run ownership: "
            + ", ".join(missing_query)
        )

    required_driver_tokens = (
        'parser.add_argument("--test-godmode", action="store_true")',
        'parser.add_argument("--test-manual-enemy-mode", action="store_true")',
        "sd.events.on('runtime.tick', sustain)",
        "if not local_participant_in_run() then",
        "sd.gameplay.get_manual_enemy_spawner_state()",
        "if state and state.manual_mode then",
        "sd.gameplay.set_manual_enemy_spawner_test_mode(true)",
        'host_view_before_client.get("local.in_run") != "true"',
        "host is still presenting an ended run; refusing to start a competing client scene load",
        'host_view.get("local.in_run") == "true"',
    )
    missing_driver = [
        token for token in required_driver_tokens if token not in driver_text
    ]
    if missing_driver:
        raise StaticReTestFailure(
            "Steam pair ended-run safety is incomplete: "
            + ", ".join(missing_driver)
        )

    host_query = driver_text.find("host_view_before_client = local_sync.query(HOST_ENDPOINT)")
    ended_run_guard = driver_text.find(
        'host_view_before_client.get("local.in_run") != "true"', host_query
    )
    client_navigation = driver_text.find(
        'output["client"] = drive_one_to_hub(', ended_run_guard
    )
    arm_host = driver_text.find(
        '"host": arm_test_godmode(pair, HOST_ENDPOINT)', client_navigation
    )
    arm_client = driver_text.find(
        '"client": arm_test_godmode(pair, CLIENT_ENDPOINT)', arm_host
    )
    arm_manual_host = driver_text.find(
        '"host": arm_test_manual_enemy_mode(pair, HOST_ENDPOINT)', arm_client
    )
    arm_manual_client = driver_text.find(
        '"client": arm_test_manual_enemy_mode(pair, CLIENT_ENDPOINT)',
        arm_manual_host,
    )
    run_start = driver_text.find("if args.start_run:", arm_manual_client)
    if not (
        0 <= host_query < ended_run_guard < client_navigation
        < arm_host < arm_client < arm_manual_host < arm_manual_client < run_start
    ):
        raise StaticReTestFailure(
            "Steam pair driver must reject an ended host run before client navigation "
            "and arm both test-safety callbacks on both peers before run start"
        )

    return "Steam pair onboarding refuses stale ended runs before client navigation and arms semantic test safety before run start"


def test_manual_enemy_test_mode_logging_is_transition_only() -> str:
    lifecycle_text = read_text(
        ROOT / "SolomonDarkModLoader/src/run_lifecycle/public_api_and_install.inl"
    )
    setter_start = lifecycle_text.find(
        "void SetRunLifecycleManualEnemySpawnerTestMode(bool enabled)"
    )
    setter_end = lifecycle_text.find(
        "bool IsRunLifecycleManualEnemySpawnerTestModeEnabled()", setter_start
    )
    body = lifecycle_text[setter_start:setter_end]
    required = (
        "manual_enemy_spawner_test_mode.exchange(",
        "if (previous == enabled)",
        "return;",
        'Log(\n        "manual run enemy spawn: stock-spawner test mode "',
    )
    missing = [token for token in required if token not in body]
    if setter_start == -1 or setter_end == -1 or missing:
        raise StaticReTestFailure(
            "manual enemy test-mode setter must log only actual state transitions: "
            + ", ".join(missing)
        )
    if not (
        body.find("manual_enemy_spawner_test_mode.exchange(")
        < body.find("if (previous == enabled)")
        < body.find("return;")
        < body.find("Log(")
    ):
        raise StaticReTestFailure(
            "manual enemy test-mode transition guard must precede logging"
        )
    return "manual enemy test mode is idempotent and logs only real state transitions"


def test_steam_friend_multiplayer_contract_is_wired() -> str:
    protocol_text = read_text(
        ROOT / "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h"
    )
    bootstrap_api_text = read_text(
        ROOT / "SolomonDarkModLoader/src/steam_bootstrap_api.cpp"
    )
    bootstrap_text = read_text(
        ROOT / "SolomonDarkModLoader/src/steam_bootstrap.cpp"
    )
    steam_abi_text = read_text(
        ROOT / "SolomonDarkModLoader/include/steamworks_abi.h"
    )
    steam_bridge_text = read_text(
        ROOT / "SolomonDarkModLoader/src/steam_api_bridge.cpp"
    )
    session_root = ROOT / "SolomonDarkModLoader/src/multiplayer_steam_session"
    session_text = "\n".join(
        [
            read_text(
                ROOT / "SolomonDarkModLoader/src/multiplayer_steam_session.cpp"
            ),
            *(read_text(path) for path in sorted(session_root.glob("*.inl"))),
        ]
    )
    gameplay_transport_text = read_multiplayer_transport_source()
    launch_environment_text = read_text(
        ROOT / "SolomonDarkModLauncher/src/Launch/MultiplayerLaunchEnvironment.cs"
    )
    launch_options_text = read_text(
        ROOT / "SolomonDarkModLauncher/src/Launch/MultiplayerLaunchOptions.cs"
    )
    command_parser_text = read_text(
        ROOT / "SolomonDarkModLauncher/src/Commands/LauncherCommandParser.cs"
    )
    launch_executor_text = read_text(
        ROOT / "SolomonDarkModLauncher/src/App/LauncherCommandExecutor.cs"
    )
    steam_materializer_text = read_text(
        ROOT / "SolomonDarkModLauncher/src/Steam/SteamBootstrapMaterializer.cs"
    )
    steam_configuration_text = read_text(
        ROOT / "SolomonDarkModLauncher/src/Steam/SteamBootstrapConfiguration.cs"
    )
    compatibility_materializer_text = read_text(
        ROOT / "SolomonDarkModLauncher/src/Staging/MultiplayerCompatibilityMaterializer.cs"
    )
    startup_status_text = read_text(
        ROOT / "SolomonDarkModLoader/src/startup_status.cpp"
    )
    session_monitor_text = read_text(
        ROOT / "SolomonDarkModLauncher/src/Launch/MultiplayerSessionStatusMonitor.cs"
    )
    launcher_json_text = read_text(
        ROOT / "SolomonDarkModLauncher/src/App/LauncherJsonConsole.cs"
    )
    launcher_output_text = read_text(
        ROOT / "SolomonDarkModLauncher/src/App/LauncherOutputFormatter.cs"
    )
    ui_response_text = read_text(
        ROOT / "SolomonDarkModLauncher.UI/src/Infrastructure/LauncherCliResponse.cs"
    )
    ui_view_model_text = read_text(
        ROOT / "SolomonDarkModLauncher.UI/src/ViewModels/MainWindowViewModel.cs"
    )
    ui_command_client_text = read_text(
        ROOT / "SolomonDarkModLauncher.UI/src/Infrastructure/LauncherUiCommandClient.cs"
    )
    ui_response_reader_text = read_text(
        ROOT / "SolomonDarkModLauncher.UI/src/Infrastructure/LauncherJsonResponseReader.cs"
    )
    ui_session_status_reader_text = read_text(
        ROOT / "SolomonDarkModLauncher.UI/src/Infrastructure/"
        "LauncherMultiplayerSessionStatusReader.cs"
    )
    ui_xaml_text = read_text(
        ROOT / "SolomonDarkModLauncher.UI/src/Views/MainWindow.xaml"
    )
    wsl_steam_client_text = read_text(
        ROOT / "scripts/Launch-WslSteamMultiplayerClient.sh"
    )
    wsl_lua_client_text = read_text(
        ROOT / "scripts/Invoke-WslLuaExec.sh"
    )
    win32_lua_client_text = read_text(
        ROOT / "tools/win32_lua_exec_client.cpp"
    )

    required_pairs = (
        (protocol_text, "constexpr std::uint16_t kProtocolVersion = 77;"),
        (compatibility_materializer_text, "CurrentProtocolVersion = 77;"),
        (protocol_text, "SessionCapabilityHostAuthority"),
        (protocol_text, "struct SessionHelloPacket"),
        (protocol_text, "struct SessionHelloAckPacket"),
        (protocol_text, "struct SessionGoodbyePacket"),
        (protocol_text, "SessionKeepalive = 18"),
        (protocol_text, "struct SessionKeepalivePacket"),
        (steam_abi_text, "struct LobbyCreatedSmall"),
        (steam_abi_text, "struct LobbyEnterSmall"),
        (steam_abi_text, "small-pack LobbyEnter_t ABI changed"),
        (bootstrap_text, "DecodeLobbyCreatedPayload"),
        (bootstrap_text, "DecodeLobbyEnterPayload"),
        (bootstrap_api_text, '"SteamAPI_ManualDispatch_RunFrame"'),
        (bootstrap_api_text, '"SteamAPI_SteamNetworkingMessages_SteamAPI_v002"'),
        (bootstrap_api_text, '"SteamAPI_ISteamNetworkingMessages_SendMessageToUser"'),
        (bootstrap_api_text, '"SteamAPI_ISteamNetworkingMessages_ReceiveMessagesOnChannel"'),
        (bootstrap_api_text, '"SteamAPI_ISteamMatchmaking_InviteUserToLobby"'),
        (steam_bridge_text, "steamabi::kLobbyTypeFriendsOnly"),
        (steam_bridge_text, "SteamInviteUserToLobby"),
        (session_text, "SteamCreateLobby("),
        (session_text, "g_session.lobby_visibility"),
        (session_text, 'LobbyPrivacyToken(g_session.lobby_visibility)'),
        (session_text, "SteamInviteUserToLobby(lobby_id, g_session.invite_steam_id)"),
        (session_text, "g_session.phase == SteamSessionPhase::Error &&"),
        (session_text, "g_session.lobby_id == 0"),
        (session_text, 'SteamSetRichPresence("connect", connect.c_str())'),
        (session_text, "TryParseLobbyIdFromConnectString"),
        (session_text, "IsLobbyMember(message.sender_steam_id)"),
        (session_text, "packet.session_nonce == 0"),
        (session_text, "kRequiredSessionCapabilities"),
        (session_text, "RegisterSteamGameplayPeer(message.sender_steam_id, false)"),
        (session_text, "SendGoodbyeToAuthenticatedPeers"),
        (session_text, "kAuthenticatedPeerTimeoutMs"),
        (session_text, "kKeepaliveIntervalMs"),
        (session_text, "HandleSessionKeepalive"),
        (session_text, "SendSessionKeepalives(now_ms)"),
        (session_text, "packet.session_nonce != peer_it->second.session_nonce"),
        (session_text, "ExpireInactivePeers(now_ms)"),
        (session_text, "RestartClientHostHandshake"),
        (gameplay_transport_text, "IsAuthorizedSteamGameplayPacket"),
        (gameplay_transport_text, "packet.owner_participant_id;"),
        (gameplay_transport_text, "configured_remote.steam_id == sender_steam_id"),
        (launch_environment_text, 'environment[TransportVariable] = "steam";'),
        (launch_environment_text, 'InviteSteamIdVariable = "SDMOD_STEAM_INVITE_STEAM_ID"'),
        (launch_options_text, "InviteSteamId"),
        (command_parser_text, 'arg == "--invite-steam-id"'),
        (steam_configuration_text, 'public const string DefaultAppId = "3362180";'),
        (steam_materializer_text, "reader.PEHeaders.CoffHeader.Machine == Machine.I386"),
        (startup_status_text, 'L"multiplayer-session-status.json"'),
        (startup_status_text, '"  \\"inviteSent\\": "'),
        (session_text, "WriteMultiplayerSessionStatus("),
        (session_text, "g_session.overlay_enabled = SteamIsOverlayEnabled()"),
        (session_monitor_text, "WaitForHostReady("),
        (session_monitor_text, "WaitForConnectedJoin("),
        (session_monitor_text, "expectedLaunchToken"),
        (launcher_json_text, "MultiplayerSession ="),
        (launcher_json_text, "LaunchToken = session.LaunchToken"),
        (launcher_output_text, "Steam lobby id:"),
        (ui_response_text, "LauncherCliMultiplayerSession"),
        (ui_response_text, "public string LaunchToken"),
        (ui_view_model_text, "LobbyId = multiplayer.LobbyId.ToString();"),
        (ui_view_model_text, "StartSteamSessionMonitoring("),
        (ui_view_model_text, 'status.Phase == "Connected"'),
        (ui_view_model_text, "DescribeLobbyConnection(status)"),
        (ui_view_model_text, 'connection += $" · {status.RoutePingMs} ms"'),
        (ui_session_status_reader_text, "FileShare.ReadWrite | FileShare.Delete"),
        (ui_session_status_reader_text, "expectedLaunchToken"),
        (ui_xaml_text, 'Text="{Binding LobbyConnectionDetailsText}"'),
        (ui_command_client_text, "LauncherJsonResponseReader.ReadAsync("),
        (ui_response_reader_text, "ReadLineAsync(cancellationToken)"),
        (ui_response_reader_text, 'TryGetProperty("success"'),
        (wsl_steam_client_text, "--self-contained true"),
        (wsl_steam_client_text, "STEAM_COMPAT_DATA_PATH"),
        (wsl_steam_client_text, "SteamAppId=3362180"),
        (wsl_steam_client_text, "SteamGameId=3362180"),
        (wsl_steam_client_text, "--multiplayer join"),
        (wsl_steam_client_text, "--steam-api-dll"),
        (wsl_lua_client_text, "win32_lua_exec_client.exe"),
        (wsl_lua_client_text, 'export WINEPREFIX="$compat_data/pfx"'),
        (win32_lua_client_text, "PIPE_READMODE_MESSAGE"),
        (win32_lua_client_text, "GENERIC_READ | GENERIC_WRITE"),
        (win32_lua_client_text, "constexpr DWORD kPipeTimeoutMs = 20000;"),
    )
    missing = [token for text, token in required_pairs if token not in text]
    if missing:
        raise StaticReTestFailure(
            "Steam friend multiplayer contract is missing token(s): " +
            ", ".join(missing)
        )

    if "ReadToEndAsync" in ui_command_client_text:
        raise StaticReTestFailure(
            "WPF launcher still waits for inherited game pipe EOF instead of the CLI JSON response"
        )
    for removed_status in (
        "Steam invites ready",
        "HasSteamActivity",
        "IsSteamFriendConnected",
        "SteamConnectionText",
    ):
        if removed_status in ui_view_model_text or removed_status in ui_xaml_text:
            raise StaticReTestFailure(
                "WPF launcher retains the global Steam status: " + removed_status
            )
    return (
        "Steam friends-only lobby, authenticated v65 handshake, idle keepalive, owner-checked gameplay "
        "routing, Solomon Dark AppID launch, x86 runtime staging, and a live launch-token-bound "
        "lobby connection panel are wired"
    )


def test_wsl_lua_bridge_bootstraps_from_clean_worktree() -> str:
    bridge_text = read_text(ROOT / "scripts/Invoke-WslLuaExec.sh")
    converted_build_script = (
        'build_script_win="$(wslpath -w '
        '"$root/scripts/Build-Win32LuaExecClient.ps1")"'
    )

    if converted_build_script not in bridge_text:
        raise StaticReTestFailure(
            "WSL Lua bridge does not convert its clean-worktree bootstrap script "
            "path before invoking Windows PowerShell"
        )
    if '-File "$root/scripts/Build-Win32LuaExecClient.ps1"' in bridge_text:
        raise StaticReTestFailure(
            "WSL Lua bridge still passes a Linux path to Windows PowerShell"
        )
    if '-File "$build_script_win"' not in bridge_text:
        raise StaticReTestFailure(
            "WSL Lua bridge does not invoke the converted bootstrap script path"
        )

    return "WSL Lua bridge bootstraps its Win32 client from a clean worktree"


def test_solomon_dark_steam_app_id_is_consistent() -> str:
    source_contracts = {
        "bootstrap configuration": (
            ROOT / "SolomonDarkModLauncher/src/Steam/SteamBootstrapConfiguration.cs",
            ('public const string DefaultAppId = "3362180";',),
        ),
        "launch routing": (
            ROOT / "SolomonDarkModLauncher/src/App/LauncherCommandExecutor.cs",
            ("command.SteamAppIdOverride",),
        ),
        "manual dispatch": (
            ROOT / "SolomonDarkModLauncher/src/Steam/SteamManualDispatchSession.cs",
            (
                "SteamManualDispatchSession(string steamApiPath, string appId)",
                'Environment.SetEnvironmentVariable("SteamAppId", appId);',
                'Environment.SetEnvironmentVariable("SteamGameId", appId);',
            ),
        ),
        "launch preflight": (
            ROOT / "SolomonDarkModLauncher/src/Steam/SteamLaunchPreflight.cs",
            ("new SteamManualDispatchSession(steamApiPath, bootstrap.AppId)",),
        ),
        "invite listener": (
            ROOT / "SolomonDarkModLauncher/src/Steam/SteamInviteListener.cs",
            (
                "SteamBootstrapConfiguration.CreateDefault(",
                "new SteamManualDispatchSession(steamApiPath, steamConfiguration.AppId)",
            ),
        ),
        "directory authentication": (
            ROOT / "SolomonDarkModLauncher/src/Steam/SteamDirectoryAuthenticator.cs",
            (
                "new SteamWebApiTicketSession(steamApiPath, steamConfiguration.AppId)",
                "new SteamManualDispatchSession(steamApiPath, appId)",
            ),
        ),
        "WSL Steam launch": (
            ROOT / "scripts/Launch-WslSteamMultiplayerClient.sh",
            (
                "compatdata/3362180",
                "--steam-appid 3362180",
                "SteamAppId=3362180",
                "SteamGameId=3362180",
            ),
        ),
        "WSL Lua bridge": (
            ROOT / "scripts/Invoke-WslLuaExec.sh",
            ("compatdata/3362180",),
        ),
        "package builder": (
            ROOT / "scripts/New-BetaReleasePackage.ps1",
            ("steamAppId = 3362180",),
        ),
        "package smoke": (
            ROOT / "scripts/Test-BetaReleasePackage.ps1",
            ('$result.steamAppId -ne "3362180"',),
        ),
        "artifact verifier": (
            ROOT / "tools/verify_beta_release_artifact.py",
            (
                "EXPECTED_STEAM_APP_ID = 3362180",
                '"steamAppId": EXPECTED_STEAM_APP_ID',
            ),
        ),
    }

    missing: list[str] = []
    for label, (path, tokens) in source_contracts.items():
        text = read_text(path)
        missing.extend(
            f"{label}: {token}"
            for token in tokens
            if token not in text
        )
    if missing:
        raise StaticReTestFailure(
            "Steam AppID 3362180 cutover is incomplete: " + ", ".join(missing)
        )

    retired_paths = (
        ROOT / "README.md",
        ROOT / "SolomonDarkModLauncher/assets/steam/README.txt",
        ROOT / "SolomonDarkModLauncher/src",
        ROOT / "docs/networking",
        ROOT / "release/THIRD-PARTY-NOTICES.txt",
        ROOT / "scripts/Launch-WslSteamMultiplayerClient.sh",
        ROOT / "scripts/Invoke-WslLuaExec.sh",
        ROOT / "scripts/New-BetaReleasePackage.ps1",
        ROOT / "scripts/Test-BetaReleasePackage.ps1",
        ROOT / "tools/verify_beta_release_artifact.py",
    )
    retired_hits: list[str] = []
    for path in retired_paths:
        files = path.rglob("*") if path.is_dir() else (path,)
        for file_path in files:
            if not file_path.is_file() or file_path.suffix in {".dll", ".exe", ".pdb"}:
                continue
            text = read_text(file_path)
            if "Spacewar" in text or "SpacewarDevelopmentAppId" in text:
                retired_hits.append(str(file_path.relative_to(ROOT)))
    if retired_hits:
        raise StaticReTestFailure(
            "retired Spacewar path remains active in: " +
            ", ".join(sorted(set(retired_hits)))
        )

    return "launcher, runtime helpers, packages, and docs use Steam AppID 3362180"


def test_steam_friend_hub_lifecycle_soak_is_wired() -> str:
    runtime_state_text = read_multiplayer_runtime_state_source()
    reconciliation_text = read_source_unit(WORLD_SNAPSHOT_RECONCILIATION)
    lua_gameplay_text = read_text(
        ROOT / "SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp"
    )
    presentation_probe_text = read_text(
        ROOT / "tools/probe_hub_npc_presentation_sync.py"
    )
    soak_text = read_text(
        ROOT / "tools/verify_steam_friend_hub_soak.py"
    )

    required_pairs = (
        (runtime_state_text, "std::uint32_t removed_actor_total_count = 0;"),
        (
            runtime_state_text,
            "std::uint32_t failed_remove_actor_total_count = 0;",
        ),
        (
            reconciliation_text,
            "state.world_snapshot_apply.removed_actor_total_count +=",
        ),
        (
            reconciliation_text,
            "state.world_snapshot_apply.failed_remove_actor_total_count +=",
        ),
        (lua_gameplay_text, '"removed_actor_total_count"'),
        (lua_gameplay_text, '"failed_remove_actor_total_count"'),
        (lua_gameplay_text, '"apply_sequence"'),
        (lua_gameplay_text, '"apply_scene_epoch"'),
        (lua_gameplay_text, '"apply_presentation_sequence"'),
        (lua_gameplay_text, '"apply_presentation_scene_epoch"'),
        (lua_gameplay_text, '"apply_presentation_received_ms"'),
        (lua_gameplay_text, '"apply_presentation_available"'),
        (lua_gameplay_text, '"apply_presentation_actors"'),
        (lua_gameplay_text, '"apply_actors_available"'),
        (lua_gameplay_text, '"apply_actors"'),
        (
            lua_gameplay_text,
            "candidate.sequence == runtime.world_snapshot_apply.sequence",
        ),
        (
            reconciliation_text,
            "state.world_snapshot_apply.presentation_sequence = presentation_snapshot.sequence;",
        ),
        (
            presentation_probe_text,
            '"replicated.failed_remove_actor_total_count"',
        ),
        (
            presentation_probe_text,
            'client["replicated_applied_ms"]\n        - client["replicated_apply_presentation_received_ms"]',
        ),
        (presentation_probe_text, '"applyactor"'),
        (
            presentation_probe_text,
            'for apply_actor in client["applyactors"]:',
        ),
        (presentation_probe_text, 'binding.get("removed") != "true"'),
        (presentation_probe_text, '"client_apply_presentation_available"'),
        (soak_text, '"same_machine": PAIR_BACKEND == "wsl"'),
        (
            soak_text,
            'applied_authoritative = hub_records(client_values, "applyactor")',
        ),
        (soak_text, "def convergence_errors("),
        (soak_text, "ThreadPoolExecutor(max_workers=2)"),
        (soak_text, "host_future = executor.submit("),
        (soak_text, "client_future = executor.submit("),
        (soak_text, '"latest authoritative hub actor IDs are not unique"'),
        (soak_text, '"applied authoritative hub actor IDs are not unique"'),
        (soak_text, '"retired hub IDs remain bound"'),
        (soak_text, '"a persistent named hub NPC remains unbound"'),
        (soak_text, '"applied hub presentation source is unavailable"'),
        (soak_text, "failed_remove_totals[-1] != failed_remove_totals[0]"),
        (soak_text, "created_totals[-1] != created_totals[0]"),
        (soak_text, "removed_totals[-1] != removed_totals[0]"),
        (soak_text, "if lifecycle_change_count == 0:"),
        (soak_text, '"final_pair_responsive": True'),
        (soak_text, '"student_book_palette_mismatches"'),
        (soak_text, '"named_drive_phase_out_of_tolerance"'),
    )
    missing = [
        token
        for text, token in required_pairs
        if token not in text
    ]
    if missing:
        raise StaticReTestFailure(
            "same-machine Steam hub lifecycle soak is incomplete: "
            + ", ".join(missing)
        )

    forbidden_tokens = (
        "stable slot identity",
        "allow_failed_remove",
        "ignore_extra_actor",
        "sample_delta_ms = (",
        "sample_time_adjusted_host_drive",
    )
    present = [
        token
        for token in forbidden_tokens
        if token in soak_text or token in presentation_probe_text
    ]
    if present:
        raise StaticReTestFailure(
            "hub soak contains a slot-identity, divergence, or cross-process-clock escape path: "
            + ", ".join(present)
        )

    for forbidden in (
        'if PAIR_BACKEND != "wsl":',
        "hub soak requires the same-machine Windows plus WSL Steam pair",
    ):
        if forbidden in soak_text:
            raise StaticReTestFailure(
                "hub soak still rejects a genuine remote Windows Steam pair: "
                + forbidden
            )

    if re.search(
        r'client\["replicated_sampled_ms"\]\s*-\s*host\["replicated_sampled_ms"\]',
        presentation_probe_text,
    ):
        raise StaticReTestFailure(
            "hub presentation verification subtracts process-local Windows and Proton clocks"
        )

    return (
        "Steam hub soak supports both physical-Windows and same-machine test "
        "topologies while requiring one-to-one named NPC convergence, local-stock "
        "Student presentation sync, and zero multiplayer hub lifecycle mutation"
    )


def test_player_state_exports_native_heading_for_bot_spawn() -> str:
    header_text = read_text(ROOT / "SolomonDarkModLoader/include/mod_loader.h")
    state_getters_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_state_getters.inl"
    )
    lua_binding_text = read_text(ROOT / "SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp")
    lua_scene_text = read_text(ROOT / "mods/lua_bots/scripts/lib/lua_bots/scene.lua")
    lua_follow_text = read_text(ROOT / "mods/lua_bots/scripts/lib/lua_bots/follow.lua")

    required_tokens = {
        "player state struct": (header_text, "float heading = 0.0f;"),
        "native heading read": (
            state_getters_text,
            "TryReadFiniteFloatField(actor_address, kActorHeadingOffset, &heading)",
        ),
        "player heading assignment": (state_getters_text, "state->heading = heading;"),
        "Lua player heading publish": (lua_binding_text, "player_state.heading"),
        "Lua player heading field": (lua_binding_text, '"heading"'),
        "Lua bot spawn requires heading": (lua_scene_text, "local heading = tonumber(player.heading)"),
        "Lua bot request top-level heading": (lua_scene_text, "heading = spawn.heading,\n        position = {"),
        "Lua follow request top-level heading": (lua_follow_text, "update.heading = tonumber(bot.heading)"),
    }
    missing = [
        label
        for label, (text, token) in required_tokens.items()
        if token not in text
    ]
    if missing:
        raise StaticReTestFailure("player heading live-state coverage missing: " + ", ".join(missing))

    if "local heading = tonumber(player.heading) or" in lua_scene_text:
        raise StaticReTestFailure("Lua bot spawn heading reintroduced a default instead of requiring live player heading")
    if re.search(r"position\s*=\s*\{[^}]*\bheading\b", lua_scene_text, re.S):
        raise StaticReTestFailure("Lua bot spawn/update nested heading inside position instead of using request heading")
    if "update.position.heading" in lua_follow_text:
        raise StaticReTestFailure("Lua follow nested heading inside position instead of using request heading")

    return "bot spawn heading comes from live actor state and is sent through the native request heading field"
