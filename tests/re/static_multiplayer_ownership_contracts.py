"""Runtime tooling, inventory, loot, and ownership contracts."""

from __future__ import annotations

import ast
import hashlib
import json
import math
import re
import struct
import sys
from pathlib import Path

from static_multiplayer_contract_support import (
    ROOT,
    _read,
    _read_many,
    _require_in_order,
    read_source_unit,
)

def test_lua_exec_timeout_cancels_pending_work() -> str:
    engine = read_source_unit("SolomonDarkModLoader/src/lua_engine.cpp")
    engine_header = _read("SolomonDarkModLoader/include/lua_engine.h")
    pipe = _read("SolomonDarkModLoader/src/lua_exec_pipe.cpp")
    bindings = _read("SolomonDarkModLoader/src/lua_engine_bindings.cpp")
    events = _read("SolomonDarkModLoader/src/lua_engine_events.cpp")
    engine_internal = _read("SolomonDarkModLoader/src/lua_engine_internal.h")
    lua_main = _read("mods/lua_bots/scripts/main.lua")
    lua_client = _read("tools/lua-exec.py")
    local_verifier = _read("tools/verify_local_multiplayer_sync.py")
    steam_driver = _read("tools/drive_steam_friend_active_pair.py")
    lua_contract_verifier = _read("tools/verify_lua_runtime_contract.py")
    playtest_guide = _read("docs/networking/steam-friend-playtest.md")
    spell_behavior_verifier = _read(
        "tools/verify_steam_friend_active_pair_spell_behavior.py"
    )

    for token in (
        "LuaExecRequestState::Pending",
        "LuaExecRequestState::Executing",
        "LuaExecRequestState::Canceled",
        "std::shared_ptr<PendingLuaExecRequest>",
        "bool TryCancelLuaExecRequest(",
        "bool TryClaimLuaExecRequest(",
        "std::atomic<std::uint64_t>& LuaExecPumpGeneration()",
        "LuaExecPumpGeneration().fetch_add(1, std::memory_order_release);",
        "pump_generation - pump_generation_at_enqueue >= 2",
    ):
        assert token in engine, f"Lua exec cancellation contract lacks: {token}"

    for token in (
        "const std::atomic<bool>* service_running = nullptr",
        "kLuaExecHangBackstopMs = 30000",
        "&g_pipe_running",
    ):
        assert token in engine_header + pipe, (
            f"Lua exec scene-load/shutdown deadline contract lacks: {token}"
        )

    assert "DEFAULT_WSL_BRIDGE_TIMEOUT_SECONDS = 35.0" in lua_client
    assert "NATIVE_UI_LUA_TIMEOUT_SECONDS = 35.0" in local_verifier
    assert local_verifier.count(
        "timeout=NATIVE_UI_LUA_TIMEOUT_SECONDS"
    ) >= 4
    assert (
        "timeout=local_sync.NATIVE_UI_LUA_TIMEOUT_SECONDS" in steam_driver
    )
    for token in (
        '"--steam-friend"',
        "def run_steam_friend_pair()",
        "SteamFriendActivePair",
        "pair.discover()",
        "pair.lua(endpoint, probe, timeout=12.0)",
        "return pair.redact(result)",
    ):
        assert token in lua_contract_verifier, (
            f"real-Steam Lua runtime contract lacks: {token}"
        )

    required_functions = next(
        ast.literal_eval(node.value)
        for node in ast.parse(lua_contract_verifier).body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "REQUIRED_FUNCTIONS"
    )
    required_function_count = sum(map(len, required_functions.values()))
    assert (
        f"with {len(required_functions)} namespaces and "
        f"{required_function_count} required functions."
    ) in playtest_guide, "playtest guide has a stale Lua runtime contract count"

    _require_in_order(
        engine,
        "LuaExecResult QueueLuaExecRequestAndWait(",
        "TryCancelLuaExecRequest(queued.request)",
        "canceled before gameplay-thread execution",
    )
    _require_in_order(
        engine,
        "void ProcessLuaExecQueueOnMainThread()",
        "if (!TryClaimLuaExecRequest(request))",
        "ExecuteLuaCodeOnLockedState(shared_state, request->code)",
    )

    for unsafe_global in (
        '"debug"',
        '"dofile"',
        '"io"',
        '"loadfile"',
        '"os"',
        '"package"',
        '"require"',
    ):
        assert unsafe_global in engine

    for registration in (
        "RegisterLuaRuntimeBindings",
        "RegisterLuaEventBindings",
        "RegisterLuaBotBindings",
        "RegisterLuaUiBindings",
        "RegisterLuaInputBindings",
        "RegisterLuaGameplayBindings",
        "RegisterLuaHubBindings",
        "RegisterLuaDebugBindings",
    ):
        assert registration in bindings
    assert "lua_createtable(mod->state, 0, 10);" in bindings
    assert "lua_pcall" in events, "Lua event handlers must be fault isolated"

    for token in (
        "using PendingLuaEvent = std::variant<",
        "std::deque<PendingLuaEvent> g_pending_lua_events;",
        "pending.swap(g_pending_lua_events);",
        "void DispatchPendingLuaEventsToLuaMods()",
        "detail::QueueEnemyDeathEvent(enemy_type, x, y, kill_method);",
        "void StartLuaEventQueue();",
        "void StopLuaEventQueue();",
    ):
        assert token in events + engine_internal, (
            f"reentrant Lua event queue contract lacks: {token}"
        )

    enemy_death_dispatch = events[
        events.index("void DispatchLuaEnemyDeath(") :
        events.index("void DispatchLuaEnemySpawned(")
    ]
    assert "LuaEngineMutex" not in enemy_death_dispatch, (
        "a native death reached from lua-exec must enqueue its event instead "
        "of recursively locking the Lua engine"
    )
    _require_in_order(
        engine,
        "detail::StartLuaEventQueue();",
        "detail::LuaEngineInitializedFlag() = true;",
    )
    _require_in_order(
        engine,
        "void ShutdownLuaEngine()",
        "detail::StopLuaEventQueue();",
        "detail::DrainLuaExecQueue();",
    )
    assert engine.count("detail::DispatchPendingLuaEventsToLuaMods();") == 2

    for token in (
        "presenter_log_offsets = capture_log_offsets()",
        'output["post_behavior_cleanup"] = primary.cleanup_live_enemies()',
        "verify_native_death_presenter_results(presenter_log_offsets)",
        "deadline = time.monotonic() + timeout",
        'if result["event_count"] == 0',
        "if not missing:",
        'outcome["called"] != 1 or outcome["seh"] != "0x0"',
    ):
        assert token in spell_behavior_verifier, (
            f"live Lua/death-presenter regression gate lacks: {token}"
        )

    for loader_token in (
        "runtime.get_mod_text_file",
        'load(source, "@" .. normalized, "t", _ENV)',
        "loading_sentinel",
        "pcall(chunk)",
    ):
        assert loader_token in lua_main

    return (
        "pending Lua exec requests are cancelable, stock scene-load stalls fit "
        "inside the hang backstop, pump skips fail by invariant, pipe shutdown "
        "interrupts its wait, hook events are deferred without re-entering the "
        "Lua VM, handlers remain isolated, and all ten current sd namespaces "
        "are registered"
    )


def test_remote_windows_lua_bridge_is_persistent_and_framed() -> str:
    pair = _read("tools/steam_friend_active_pair.py")
    primary_kill = _read("tools/verify_steam_friend_primary_kill_stress.py")
    bridge_script = _read("scripts/Invoke-RemoteLuaExecBridge.ps1")
    bridge = pair[
        pair.index("class RemoteWindowsLuaBridge:") :
        pair.index("class RemoteWindowsLogMirror:")
    ]
    mirror = pair[
        pair.index("class RemoteWindowsLogMirror:") :
        pair.index("class SteamFriendActivePair:")
    ]

    for token in (
        "def _encoded_bridge_command(self) -> str:",
        "-ListenPort 0",
        "self._server_process",
        "def _read_line(",
        're.fullmatch(r"SDMOD_BRIDGE_PORT=(\\d+)", line)',
        "stdin=subprocess.PIPE",
        "stdout=subprocess.PIPE",
        "bufsize=0",
        '"-W"',
        'f"127.0.0.1:{remote_port}"',
        'struct.pack("<II", REMOTE_BRIDGE_PING_LENGTH, 100)',
        "if response_size != 0:",
        "def _exchange(",
        "subprocess.Popen(",
        '"-EncodedCommand"',
        '"<II",',
        "response_timeout_milliseconds,",
        "time.monotonic() + response_timeout_seconds + 6.0",
        'response_size = struct.unpack(',
        "with self._lock:",
        "candidate.terminate()",
        'process.stdin.write(struct.pack("<II", 0, 100))',
    ):
        assert token in bridge, f"remote Windows Lua bridge lacks: {token}"
    assert "REMOTE_BRIDGE_PING_LENGTH = 0xFFFFFFFF" in pair
    for forbidden in (
        '"-Daemon"',
        "__SDLUA_EXIT__",
        "RemoteWindowsLuaDaemon",
        "shell=True",
        '"-tt"',
        '"-L"',
        "socket.create_connection(",
        "_remote_bridge_port",
    ):
        assert forbidden not in bridge, (
            "remote Windows Lua bridge retains an unsafe transport path: "
            f"{forbidden}"
        )

    for token in (
        "[ValidateRange(0, 65535)]",
        "[int]$ListenPort = 0",
        "[System.Net.IPAddress]::Loopback",
        "$listener.AcceptTcpClient()",
        'WriteLine("SDMOD_BRIDGE_PORT=$boundPort")',
        "$header = Read-ExactBytes -Stream $stream -Length 8",
        "$requestLength = [System.BitConverter]::ToUInt32($header, 0)",
        "if ($requestLength -eq [uint32]::MaxValue)",
        "$requestTimeoutMilliseconds = [System.BitConverter]::ToUInt32(",
        "-ResponseTimeoutMilliseconds ([int]$requestTimeoutMilliseconds)",
        "$responseHeader = [System.BitConverter]::GetBytes(",
        "$stream.Write($responseHeader, 0, $responseHeader.Length)",
        "[System.IO.Pipes.PipeOptions]::Asynchronous",
        "$pipe.ReadAsync($buffer, 0, $buffer.Length)",
        "$readTask.Wait($remaining)",
        "Timed out waiting for pipe '$PipeName'",
        "catch [System.IO.IOException]",
        "$shutdownRequested = $true",
    ):
        assert token in bridge_script, (
            f"remote Windows bridge lacks bounded framed relay: {token}"
        )
    assert bridge_script.count("while (-not $shutdownRequested)") == 2
    for token in (
        'name="remote-windows-log-mirror"',
        "def _append_available_bytes(self) -> None:",
        'f"$requested=[int64]{requested_offset};"',
        '"$available=[int][Math]::Min([int64]2097152,$length-$offset);"',
        '"[Console]::Out.Write($reset+\'|\'+$offset+\'|\'+($offset+$total)+\'|\'+$payload)"',
        "timeout=10.0",
        "thread.join(timeout=11.0)",
    ):
        assert token in mirror, f"remote log mirror lacks bounded polling: {token}"
    for forbidden in ("subprocess.Popen(", "Get-Content -LiteralPath", "-Wait -Tail 0"):
        assert forbidden not in mirror, f"remote log mirror retains persistent process: {forbidden}"
    assert '"same_machine": PAIR_BACKEND == "wsl"' in primary_kill, (
        "physical Windows-pair evidence must not claim both accounts ran on "
        "one machine"
    )
    for token in (
        'PAIR_BACKEND in ("remote-windows-host", "remote-windows-client")',
        'HOST_ENDPOINT if PAIR_BACKEND == "remote-windows-host" else CLIENT_ENDPOINT',
        "if endpoint == self._remote_windows_endpoint:",
        "if endpoint in (HOST_ENDPOINT, CLIENT_ENDPOINT):",
    ):
        assert token in pair, (
            "physical Windows Lua routing must support either machine owning "
            f"the host role: {token}"
        )
    for wrapper_path in (
        "tools/verify_steam_friend_active_run_reconnect.py",
        "tools/verify_steam_friend_host_loot_deactivation_soak.py",
        "tools/verify_steam_friend_native_inventory_sync.py",
        "tools/verify_steam_friend_powerup_sync.py",
        "tools/verify_steam_friend_world_snapshot_stale_hold.py",
    ):
        wrapper = _read(wrapper_path)
        assert '"same_machine": PAIR_BACKEND == "wsl"' in wrapper, (
            f"remote-capable evidence wrapper mislabels its topology: {wrapper_path}"
        )
        assert '"same_machine": True' not in wrapper, (
            f"remote-capable evidence wrapper hardcodes one-machine topology: {wrapper_path}"
        )

    return (
        "remote Windows Lua uses an OS-assigned loopback port reached by one "
        "persistent SSH stdio tunnel, while logs use finite byte-range polls"
    )


def test_active_pair_visual_capture_routes_by_pair_backend() -> str:
    import verify_steam_friend_active_pair_visuals as visuals

    calls: list[tuple[str, str, str]] = []
    original_backend = visuals.PAIR_BACKEND
    original_local_capture = visuals.frame_capture.capture_game_backbuffer
    original_remote_capture = visuals.capture_remote_windows_backbuffer
    try:
        visuals.frame_capture.capture_game_backbuffer = (
            lambda endpoint, output_path, **kwargs: calls.append(
                ("local", endpoint, kwargs.get("game_path_kind", "windows"))
            )
            or {"capture": "local"}
        )
        visuals.capture_remote_windows_backbuffer = (
            lambda pair, endpoint, output_path: calls.append(
                ("remote", endpoint, "windows")
            )
            or {"capture": "remote"}
        )

        expected = {
            "wsl": (
                ("local", visuals.HOST_ENDPOINT, "windows"),
                ("local", visuals.CLIENT_ENDPOINT, "proton"),
            ),
            "remote-windows-host": (
                ("remote", visuals.HOST_ENDPOINT, "windows"),
                ("local", visuals.CLIENT_ENDPOINT, "windows"),
            ),
            "remote-windows-client": (
                ("local", visuals.HOST_ENDPOINT, "windows"),
                ("remote", visuals.CLIENT_ENDPOINT, "windows"),
            ),
        }
        for backend, expected_calls in expected.items():
            visuals.PAIR_BACKEND = backend
            calls.clear()
            visuals.capture_participant_backbuffer(
                object(), visuals.HOST_ENDPOINT, visuals.HOST_SCREENSHOT
            )
            visuals.capture_participant_backbuffer(
                object(), visuals.CLIENT_ENDPOINT, visuals.CLIENT_SCREENSHOT
            )
            assert tuple(calls) == expected_calls, (backend, calls)
    finally:
        visuals.PAIR_BACKEND = original_backend
        visuals.frame_capture.capture_game_backbuffer = original_local_capture
        visuals.capture_remote_windows_backbuffer = original_remote_capture

    source = _read("tools/verify_steam_friend_active_pair_visuals.py")
    assert "def capture_remote_host_backbuffer(" not in source
    return "Steam visual captures use the exact local, Proton, or remote Windows path"


def test_steam_pair_recovers_lobby_membership_and_requires_stable_readiness() -> str:
    session = read_source_unit(
        "SolomonDarkModLoader/src/multiplayer_steam_session/lobby_and_events.inl"
    )
    session_lifecycle = _read(
        "SolomonDarkModLoader/src/multiplayer_steam_session/public_lifecycle.inl"
    )
    steam_bootstrap = _read("SolomonDarkModLoader/src/steam_bootstrap.cpp")
    steam_header = _read("SolomonDarkModLoader/include/steam_bootstrap.h")
    pair_tool = _read("tools/steam_friend_active_pair.py")

    _require_in_order(
        session,
        "if (current.find(g_session.local_steam_id) == current.end())",
        "if (!g_session.is_host)",
        "BeginClientLobbyRecovery(",
        'SetError("Local Steam user is no longer a lobby member.", false);',
    )
    for token in (
        "SteamEventKind::SteamServersDisconnected",
        "SteamEventKind::SteamServersConnected",
        "kClientLobbyRecoveryRetryMs",
        "kClientLobbyRecoveryTimeoutMs",
        "void ServiceClientLobbyRecovery(std::uint64_t now_ms)",
        "ServiceClientLobbyRecovery(now_ms);",
        "if (!g_session.steam_servers_connected)",
        "g_session.client_lobby_recovery",
        '"the recovery state machine will retry."',
        '"Steam multiplayer network session failed. steam_id="',
        '" end_reason=" + std::to_string(event.network_status.end_reason)',
        '" debug=" + event.network_status.debug_text',
        "LUA_TRANSITION_TIMEOUT_SECONDS = 35.0",
        "PAIR_DISCOVERY_TIMEOUT_SECONDS = 240.0",
        "PAIR_DISCOVERY_STABLE_SECONDS = 3.0",
        'NO_LOADED_LUA_STATE_TEXT = "No loaded Lua mod state is available."',
        "if NO_LOADED_LUA_STATE_TEXT in last_read_error:",
        "enable sample.lua.ui_sandbox_lab before launch",
        "stable_since: float | None = None",
        "and host_id != client_id",
        "if participant_id > 1",
        "if isinstance(value, bool):",
    ):
        assert token in (
            session + session_lifecycle + steam_bootstrap + steam_header + pair_tool
        ), (
            f"Steam reconnect/readiness contract lacks: {token}"
        )

    import sys

    tools = str(ROOT / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    from steam_friend_active_pair import SteamFriendActivePair

    pair = SteamFriendActivePair.__new__(SteamFriendActivePair)
    pair.host_participant_id = 0
    pair.client_participant_id = 0
    assert pair.redact(False) is False
    assert pair.redact(0) == 0
    assert pair.redact("remote_count=0") == "remote_count=0"

    pair.host_participant_id = 76561190000000001
    pair.client_participant_id = 76561190000000002
    assert pair.redact(76561190000000001) == "host"
    assert pair.redact("id=76561190000000002") == "id=client"
    assert pair.redact("1765611900000000019") == "1765611900000000019"

    return (
        "Steam clients rejoin the authenticated lobby after backend churn, "
        "and live tools require stable two-sided identity without corrupting zero/false"
    )


def test_steam_client_reauthentication_preserves_live_message_session() -> str:
    helpers = _read(
        "SolomonDarkModLoader/src/multiplayer_steam_session/state_and_helpers.inl"
    )
    messages = _read(
        "SolomonDarkModLoader/src/multiplayer_steam_session/network_messages.inl"
    )
    events = _read(
        "SolomonDarkModLoader/src/multiplayer_steam_session/lobby_event_handlers.inl"
    )
    suspend_start = helpers.index("void SuspendPeerForReauthentication(")
    reset_start = helpers.index("void ResetPeerForReauthentication(", suspend_start)
    remove_start = helpers.index("void RemovePeer(", reset_start)
    restart_start = helpers.index("void RestartClientHostHandshake(", remove_start)
    remove_all_start = helpers.index("void RemoveAllPeers()", restart_start)

    suspend_body = helpers[suspend_start:reset_start]
    reset_body = helpers[reset_start:remove_start]
    remove_body = helpers[remove_start:restart_start]
    restart_body = helpers[restart_start:remove_all_start]
    assert (
        "constexpr std::uint64_t kAuthenticatedPeerTimeoutMs = 30000;"
        in helpers
    ), "Steam peer liveness must survive a transient 30-second app-thread stall"
    assert "UnregisterSteamGameplayPeer(steam_id);" in suspend_body
    assert "peer.authenticated = false;" in suspend_body
    assert "g_session.peers.erase" not in suspend_body
    assert "SteamCloseNetworkSession" not in suspend_body
    assert "UnregisterSteamGameplayPeer(steam_id);" in reset_body
    assert "g_session.peers.erase(steam_id);" in reset_body
    assert "SteamCloseNetworkSession" not in reset_body
    assert "ResetPeerForReauthentication(steam_id);" in remove_body
    assert "SteamCloseNetworkSession(steam_id);" in remove_body
    assert "ResetPeerForReauthentication(host_steam_id);" in restart_body
    assert "RemovePeer(host_steam_id);" not in restart_body
    assert "if (reset_failed_route)" in restart_body
    assert "SteamCloseNetworkSession(host_steam_id);" in restart_body
    assert "g_session.last_hello_send_ms = reset_failed_route" in restart_body

    keepalive_start = messages.index("void HandleSessionKeepalive(")
    pump_start = messages.index("void PumpNetworkMessages(", keepalive_start)
    keepalive_body = messages[keepalive_start:pump_start]
    assert "if (!peer.authenticated)" in keepalive_body
    assert "g_session.is_host" in keepalive_body
    assert "peer.rejected" in keepalive_body
    assert "peer.session_nonce == 0" in keepalive_body
    assert "peer.authenticated = true;" in keepalive_body
    assert "RegisterSteamGameplayPeer(message.sender_steam_id, false);" in keepalive_body

    send_keepalive_start = messages.index("void SendSessionKeepalives(", pump_start)
    pump_body = messages[pump_start:send_keepalive_start]
    assert (
        "std::unordered_set<std::uint64_t> handled_session_hello_senders;"
        in pump_body
    )
    _require_in_order(
        pump_body,
        "CopyNetworkPacket(message, &packet)",
        "handled_session_hello_senders.insert(message.sender_steam_id).second",
        "HandleSessionHello(",
    )

    expire_start = messages.index("void ExpireInactivePeers(")
    route_start = messages.index("void RefreshRouteStatus(", expire_start)
    expire_body = messages[expire_start:route_start]
    assert "SuspendPeerForReauthentication(steam_id);" in expire_body
    assert "ResetPeerForReauthentication(steam_id);" not in expire_body
    assert "SteamCloseNetworkSession" not in expire_body
    assert "RemovePeer(steam_id);" not in expire_body
    assert (
        'RestartClientHostHandshake(\n'
        '                steam_id, "authenticated_peer_timeout", false);'
        in expire_body
    )

    failed_event_start = events.index("case SteamEventKind::NetworkSessionFailed:")
    invite_event_start = events.index(
        "case SteamEventKind::LobbyInviteReceived:", failed_event_start
    )
    failed_event_body = events[failed_event_start:invite_event_start]
    assert (
        'RestartClientHostHandshake(\n'
        '                event.user_id, "network_session_failed", true);'
        in failed_event_body
    )

    return (
        "lobby-member reauthentication preserves the live Steam message session "
        "through transient stalls, deduplicates queued hello bursts, and a validated "
        "keepalive repairs an asymmetric host timeout"
    )


def test_transient_status_correction_ack_waits_for_native_application() -> str:
    transport_header = _read(
        "SolomonDarkModLoader/include/multiplayer_local_transport.h"
    )
    transport = _read("SolomonDarkModLoader/src/multiplayer_local_transport.cpp")
    mod_loader_header = _read("SolomonDarkModLoader/include/mod_loader.h")
    requests = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/runtime_request_state.inl"
    )
    queue = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "public_api_gameplay_action_queues.inl"
    )
    action = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "dispatch_and_hooks_participant_vitals_actions.inl"
    )
    authority = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "participant_vitals_authority.inl"
    )
    incoming = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "incoming_packet_sync.inl"
    )

    for text, token in (
        (transport_header, "void ConfirmLocalParticipantVitalsCorrection("),
        (transport, "void ConfirmLocalParticipantVitalsCorrection("),
        (mod_loader_header, "std::uint32_t correction_sequence,"),
        (requests, "std::uint32_t correction_sequence = 0;"),
        (queue, "request.correction_sequence = correction_sequence;"),
        (
            action,
            "multiplayer::ConfirmLocalParticipantVitalsCorrection(\n"
            "                local_player_vitals_correction.correction_sequence);",
        ),
        (
            action,
            "QueueLocalPlayerVitalsCorrection(\n"
            "                    local_player_vitals_correction.correction_sequence,",
        ),
        (
            authority,
            "QueueLocalPlayerVitalsCorrection(\n"
                "                packet.correction_sequence,",
        ),
    ):
        assert token in text, (
            f"transient status correction confirmation lacks: {token}"
        )

    for token in (
        "ApplyLocalPlayerPoisonCorrection(",
        "ApplyLocalPlayerWebbedCorrection(",
        "InstallReplicatedWebbedModifier(",
    ):
        assert token in action, f"native transient correction lacks: {token}"

    normalize_start = incoming.index("NormalizedParticipantFrameState")
    apply_start = incoming.index("void ApplyParticipantFrameToRuntime(")
    normalize_body = incoming[normalize_start:apply_start]
    assert "if (life_acknowledged)" in normalize_body
    assert "status_acknowledged" not in normalize_body

    handler_start = authority.index("void ApplyParticipantVitalsCorrectionPacket(")
    handler_body = authority[handler_start:]
    queue_position = handler_body.index(
        "QueueLocalPlayerVitalsCorrection("
    )
    immediate_ack_position = handler_body.index(
        "last_applied_participant_vitals_correction_sequence ="
    )
    assert immediate_ack_position > queue_position
    assert (
        "if (!poison_active && !webbed_active && !correction_magic_shield)"
        in handler_body[queue_position:immediate_ack_position]
    )

    return (
        "poison and Webbed corrections acknowledge only after native "
        "application, retry a failed gameplay action, and cannot pin a "
        "cleared remote status"
    )


def test_native_item_pickup_converges_into_stock_inventory() -> str:
    gold_authority = _read(
        "tools/verify_multiplayer_gold_pickup_authority.py"
    )
    orb_authority = _read(
        "tools/verify_multiplayer_orb_pickup_authority.py"
    )
    pickup_geometry = _read("tools/multiplayer_pickup_geometry.py")
    native_item_verifier = _read(
        "tools/verify_multiplayer_native_item_inventory_sync.py"
    )
    native_potion_verifier = _read(
        "tools/verify_multiplayer_native_potion_inventory_sync.py"
    )
    loot_materialization = _read(
        "tools/verify_multiplayer_loot_drop_materialization.py"
    )
    native_inventory = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/native_inventory_reconciliation.inl"
    )
    native_item = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/native_item_materialization.inl"
    )
    host_deactivation = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/host_loot_drop_deactivation.inl"
    )
    replicated_loot = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/replicated_loot_reconciliation.inl"
    )
    pump = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_pump_loop.inl"
    )
    dispatch = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks.inl"
    )
    authority = read_source_unit(
        "SolomonDarkModLoader/src/multiplayer_local_transport/loot_pickup_authority.inl"
    )
    transport = _read("SolomonDarkModLoader/src/multiplayer_local_transport.cpp")
    transport_api = _read_many(
        "SolomonDarkModLoader/src/multiplayer_local_transport/public_cast_loot_api.inl",
        "SolomonDarkModLoader/src/multiplayer_local_transport/public_cast_loot_queue_api.inl",
    )
    native_types = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/native_function_types.inl"
    )
    seams = _read("SolomonDarkModLoader/src/gameplay_seams/state_and_address_bindings.inl")
    layout = _read("config/binary-layout.ini")

    assert len(replicated_loot.splitlines()) < 1000
    assert '#include "native_inventory_reconciliation.inl"' in dispatch
    assert "InventoryInsertOrStackItemFn" in native_types
    assert "allow_potion_stacking" in native_types
    assert "remove_placeholder" in native_types
    assert '"inventory_insert_or_stack_item"' in seams
    assert "inventory_insert_or_stack_item=0x0055FF20" in layout
    assert "item_wearable_color_state=0x88" in layout
    assert "TryResolveNativeItemRecipe(" in native_item
    assert "SpawnNativeItemDropFromRecipe(" in native_item
    assert "using ItemDropPostRegisterFn = void(__stdcall*)(void* actor);" in native_types

    _require_in_order(
        authority,
        "QueueHostLootDropDeactivation(",
        "pending_host_loot_pickups_by_drop_id.emplace",
    )
    assert "ProcessCompletedHostLootPickups()" in authority
    assert "PumpHostLootDropDeactivation()" in host_deactivation
    assert "CallActorWorldUnregisterSafe(" not in host_deactivation
    assert host_deactivation.count("CallActorRequestRetirementSafe(") == 1
    assert "ParkReplicatedLootPresentationActor" not in host_deactivation
    assert "ParkReplicatedLootPresentationActor" not in replicated_loot
    assert "g_client_non_authoritative_loot_suppressed_actors" not in replicated_loot
    _require_in_order(
        host_deactivation,
        "request.drop_kind == multiplayer::LootDropKind::Gold",
        "request.drop_kind == multiplayer::LootDropKind::Orb",
        "request.drop_kind == multiplayer::LootDropKind::Powerup",
        "CallActorRequestRetirementSafe(",
    )
    _require_in_order(
        replicated_loot,
        "void RemoveUnboundClientLootActors(",
        "RemoveReplicatedLootPresentationActor(binding, &exception_code)",
    )
    assert "CallActorWorldUnregisterSafe(" not in transport
    assert "def wait_for_host_reward_unregistered(" in gold_authority
    assert '"host_drop_unregistered"' in gold_authority
    assert "wait_for_host_reward_zeroed" not in gold_authority
    assert "host gold reward actor remained registered" in gold_authority
    for token in (
        "STOCK_LOOT_WORLD_UNITS_PER_PICKUP_RANGE = 30.0",
        "PICKUP_RANGE_TEST_MARGIN = 0.95",
        'capture_values.get(prefix + "pickup_range")',
        'local_row["pickup_range"]',
        'host_row["pickup_range"]',
        'last_client.get("pickup.result") == "Accepted"',
        "client proximity hook did not accept the in-range gold pickup",
    ):
        assert token in gold_authority, (
            f"gold verifier does not follow synchronized pickup geometry: {token}"
        )
    for token in (
        "STOCK_ORB_WORLD_UNITS_PER_PICKUP_RANGE = 60.0",
        "PICKUP_RANGE_TEST_MARGIN = 0.95",
        'capture_values.get(row_prefix + "pickup_range")',
        'local_row["pickup_range"]',
        'host_row["pickup_range"]',
        'last_client.get("pickup.result") == "Accepted"',
        "client orb proximity hook did not accept the in-range pickup",
    ):
        assert token in orb_authority, (
            f"orb verifier does not follow synchronized pickup geometry: {token}"
        )
    for verifier in (gold_authority, orb_authority):
        assert "PickupGeometryRuntime(" in verifier
        assert "select_reachable_spawn_point(" in verifier
    for token in (
        '"snapped_x": local_x',
        '"snapped_y": local_y',
        "host_participant = runtime.find_participant(",
        "observer_agrees and separated_from_host and stationary",
    ):
        assert token in pickup_geometry, (
            f"shared pickup geometry does not use settled native position: {token}"
        )
    assert "except Exception" not in pickup_geometry
    assert "RUN_SAFE_SPAWN_X" not in gold_authority + orb_authority
    assert "RUN_SAFE_SPAWN_Y" not in gold_authority + orb_authority
    assert "PICKUP_POSITION_TOLERANCE" not in gold_authority + orb_authority
    assert "request_pickup_when_ready" not in orb_authority
    for verifier in (
        gold_authority,
        native_item_verifier,
        native_potion_verifier,
    ):
        assert "else:\n        request = request_pickup(network_drop_id)" not in verifier
    assert (
        "client item-drop proximity hook did not accept the in-range pickup"
        in native_item_verifier
    )
    for token in (
        "network_id: int | None = None",
        'drop["network_id"] != network_id',
        "local_actor_address: int | None = None",
        "excluded_network_ids: set[int] | None = None",
        'drop["network_id"] in excluded_network_ids',
        "pipe_name: str | None = None",
        "capture(CLIENT_PIPE if pipe_name is None else pipe_name)",
        "def wait_for_drop_metadata(",
    ):
        assert token in loot_materialization, (
            f"materialized-loot selector lacks exact drop correlation: {token}"
        )
    assert "pipe_name: str = CLIENT_PIPE" not in loot_materialization
    for token in (
        "host_drop_ids_before = {",
        "host_actor_addresses_before = {",
        "host_drop = wait_for_drop_metadata(",
        "pipe_name=HOST_PIPE",
        "excluded_network_ids=host_drop_ids_before",
        "excluded_actor_addresses=host_actor_addresses_before",
        'network_id = int(host_drop["network_id"])',
        "network_id=network_id",
    ):
        assert token in native_item_verifier, (
            f"native item verifier lacks exact host/client drop correlation: {token}"
        )
    for token in (
        "host_drop_ids_before = {",
        "host_drop = wait_for_drop_metadata(",
        "pipe_name=HOST_PIPE",
        "excluded_network_ids=host_drop_ids_before",
        'network_drop_id = int(host_drop["network_id"])',
        "network_id=network_drop_id",
    ):
        assert token in native_potion_verifier, (
            f"native potion verifier lacks exact host/client drop correlation: {token}"
        )
    assert (
        "client item-drop proximity hook did not accept the in-range potion pickup"
        in native_potion_verifier
    )
    _require_in_order(
        native_inventory,
        "QueueNativeInventoryCreditInternal(",
        "pending_native_inventory_credit_drop_ids.insert(network_drop_id)",
    )
    _require_in_order(
        native_inventory,
        "ExecuteNativeInventoryCreditNow(",
        "kItemDropHeldItemOffset,",
        "cleared_held_item_address",
        "CallInventoryInsertOrStackItemSafe(",
        "expected_quantity_after",
        "MarkLocalInventoryNativeConverged",
    )
    assert "completed_native_inventory_credit_drop_ids" in native_inventory
    assert "IsNativeInventoryCreditCompleted(snapshot.run_nonce" in replicated_loot
    assert "NativeInventoryCreditOutcome::ApplyStateUnknown" in pump
    assert "pending_native_inventory_credits.push_back" in pump
    _require_in_order(
        transport_api,
        "bool MarkLocalInventoryNativeConverged(",
        "inventory_revision != inventory_revision",
        "inventory_host_authoritative = false",
    )

    return (
        "accepted remote items and potions transfer through the stock insertion ABI, "
        "verify exact native inventory growth, deduplicate by run/drop, and release the ledger guard"
    )


def test_loot_deactivation_uses_stock_deferred_retirement() -> str:
    host_deactivation = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/host_loot_drop_deactivation.inl"
    )
    replicated_loot = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/replicated_loot_reconciliation.inl"
    )
    generic_pump = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_pump_loop.inl"
    )
    post_tick_pump = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_main_thread_pump.inl"
    )
    app_tick = _read("SolomonDarkModLoader/src/background_focus_bypass.cpp")
    internal_api = _read("SolomonDarkModLoader/src/mod_loader_internal.h")
    steam_soak = _read(
        "tools/verify_steam_friend_host_loot_deactivation_soak.py"
    )

    assert "void PumpGameplayPostStockTickWork();" in internal_api
    assert "void PumpGameplayPostStockTickWork()" in post_tick_pump
    assert "PumpHostLootDropDeactivation();" in post_tick_pump
    assert "PumpHostLootDropDeactivation();" not in generic_pump
    assert "stock deferred-retirement request" in host_deactivation
    assert "CallActorWorldUnregisterSafe(" not in host_deactivation
    assert "CallActorWorldUnregisterSafe(" not in replicated_loot
    assert host_deactivation.count("CallActorRequestRetirementSafe(") == 1
    assert replicated_loot.count("CallActorRequestRetirementSafe(") == 1

    stock_tick = app_tick.find("original(app, edx);")
    post_tick = app_tick.find("PumpGameplayPostStockTickWork();", stock_tick)
    lifecycle_log = app_tick.find("LogCpuLifecycleGuardActivity();", stock_tick)
    assert 0 <= stock_tick < post_tick < lifecycle_log

    for token in (
        "DEFAULT_ITERATIONS = 64",
        "args.iterations <= 37",
        'pickup_owner = "client"',
        "pickup_pipe=CLIENT_ENDPOINT",
        "require_deferred_retirement_log(",
        'drop["host_native_actor_absent_after_pickup"]',
        'drop["client_native_actor_absent_after_pickup"]',
        'result["host_crash_delta"] or result["client_crash_delta"]',
    ):
        assert token in steam_soak, f"Steam loot-retirement soak lacks: {token}"

    return (
        "accepted host and replicated client loot use the stock deferred-retirement "
        "lifecycle from the app thread, with a 64-pickup two-account Steam soak"
    )


def test_client_loot_pickup_requests_are_single_flight_per_drop() -> str:
    transport = _read("SolomonDarkModLoader/src/multiplayer_local_transport.cpp")
    queue = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "public_cast_loot_queue_api.inl"
    )
    outgoing = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "outgoing_packet_sync.inl"
    )
    authority = read_source_unit(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "loot_pickup_authority.inl"
    )

    for token in (
        "struct InFlightLocalLootPickupRequest",
        "g_in_flight_local_loot_pickup_requests_by_drop_id",
        "kLocalLootPickupRequestRetryMs",
        "void ClearLocalLootPickupRequestStateLocked()",
    ):
        assert token in transport, f"loot single-flight state lacks: {token}"
    _require_in_order(
        queue,
        "const auto queued_request_it = std::find_if(",
        "const auto in_flight_it =",
        "g_next_local_loot_pickup_request_sequence++",
        "g_queued_local_loot_pickup_requests.push_back(request)",
    )
    _require_in_order(
        outgoing,
        "requests.swap(g_queued_local_loot_pickup_requests)",
        "g_in_flight_local_loot_pickup_requests_by_drop_id[",
        "SendPacketToEndpoint(packet, endpoint)",
    )
    _require_in_order(
        authority,
        "CompleteInFlightLocalLootPickupRequest(",
        "UpdateRuntimeState([&](RuntimeState& state)",
    )

    return (
        "client loot pickup RPCs coalesce queued and in-flight requests by drop, "
        "retry only after a bounded timeout, and retire only their matching result sequence"
    )


def test_native_unregister_retires_address_bound_network_identity() -> str:
    header = _read(
        "SolomonDarkModLoader/include/multiplayer_local_transport.h"
    )
    transport_api = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "public_cast_loot_api.inl"
    )
    actor_lifecycle = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "dispatch_and_hooks_actor_lifecycle_hooks.inl"
    )

    assert "void NotifyLocalWorldActorUnregistered(uintptr_t actor_address);" in header
    _require_in_order(
        transport_api,
        "void NotifyLocalWorldActorUnregistered(uintptr_t actor_address)",
        "hub_world_actor_ids_by_address.erase(actor_address)",
        "run_host_local_world_actor_ids_by_address.erase(",
        "run_loot_drop_ids_by_address.erase(actor_address)",
    )
    _require_in_order(
        actor_lifecycle,
        "ForgetAuthoritativeTurnUndeadTargetLocksForActor(actor_address)",
        "multiplayer::NotifyLocalWorldActorUnregistered(actor_address)",
        "original(self, actor, remove_from_container)",
    )
    assert "remove_from_container == 1" in actor_lifecycle

    return (
        "the exact native unregister boundary retires host address-bound world and loot "
        "identities before the allocator can recycle that address for a different actor"
    )


def test_powerup_rewards_are_authoritative_and_native() -> str:
    protocol = _read(
        "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h"
    )
    capture = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/loot_snapshot_capture.inl"
    )
    authority = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/powerup_loot_authority.inl"
    )
    pickup_authority = read_source_unit(
        "SolomonDarkModLoader/src/multiplayer_local_transport/loot_pickup_authority.inl"
    )
    hook = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/powerup_pickup_hook.inl"
    )
    reconciliation = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/replicated_loot_reconciliation.inl"
    )
    deactivation = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/host_loot_drop_deactivation.inl"
    )
    native_progression = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/native_progression_sync.inl"
    )
    local_state = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/local_state_packet_sync.inl"
    )
    incoming_state = read_source_unit(
        "SolomonDarkModLoader/src/multiplayer_local_transport/incoming_packet_sync.inl"
    )
    lua_gameplay = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp"
    )
    lua_runtime = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_runtime.cpp"
    )
    layout = _read("config/binary-layout.ini")
    verifier = _read("tools/verify_multiplayer_powerup_sync.py")
    steam_verifier = _read("tools/verify_steam_friend_powerup_sync.py")
    bonus_skill_verifier = verifier[
        verifier.index("def verify_bonus_skill("):
        verifier.index("\ndef run_cases(", verifier.index("def verify_bonus_skill("))
    ]

    for token in (
        "constexpr std::uint16_t kProtocolVersion = 70;",
        "Powerup = 5",
        "enum class PowerupRewardKind",
        "BonusSkillPoint = 0",
        "RandomSkillRank = 1",
        "DamageX4 = 2",
        "ParticipantTransientStatusFlagDamageX4",
        "std::int32_t damage_x4_remaining_ticks;",
        "std::int32_t powerup_kind;",
        "std::int32_t powerup_skill_entry_index;",
        "std::uint16_t powerup_skill_resulting_active;",
        "static_assert(sizeof(StatePacket) == 4488",
        "static_assert(sizeof(LootDropSnapshotPacketState) == 112",
        "static_assert(sizeof(LootSnapshotPacket) == 7200",
        "static_assert(sizeof(LootPickupResultPacket) == 164",
    ):
        assert token in protocol, f"powerup protocol lacks: {token}"

    for token in (
        "kPowerupRewardNativeTypeId",
        "TryPopulatePowerupLootDropSnapshot",
        "kPowerupRewardKindOffset",
        "kPowerupRewardMotionOffset",
        "kPowerupRewardLifetimeOffset",
        "kPowerupRewardProgressOffset",
        "kPowerupRewardValueOffset",
        "kPowerupRewardAuxiliaryOffset",
    ):
        assert token in capture, f"powerup carrier capture lacks: {token}"

    for token in (
        "TrySelectRandomSkillRankPowerupOption",
        "std::uint64_t owner_participant_id",
        "(owner_participant_id +",
        "g_local_transport.local_peer_id,\n                true,",
        "entry.active == 0",
        "TryResolveDamageX4DurationTicks",
        "RollParticipantSkillChoiceOptions",
        "IssueHostLevelUpOfferForParticipant",
        "IssueLocalHostSelfLevelUpOffer",
        "HydrateAuthoritativeRemoteProgressionEntryState",
        "ApplyLocalPlayerSkillChoiceOption",
        "TryWriteParticipantDamageX4Ticks",
        "ProcessQueuedLocalHostPowerupPickups",
        "queued.capture.requester_position_x",
        "captured_positions",
    ):
        assert token in authority, f"powerup authority lacks: {token}"
    assert "ApplyParticipantSkillChoiceOption(" not in authority, (
        "remote powerup replication must not execute stock skill-choice side effects"
    )

    for token in (
        "TryPreparePowerupReward",
        "packet.participant_id,\n                false,",
        "pending.packet.participant_id,\n                    false,",
        "TryApplyPreparedPowerupReward",
        "ProcessPendingHostPowerupPreparations",
        "awaiting_powerup_preparation",
        "powerup_prepared",
        "deferred powerup pickup deactivation queue expired",
        "IsPowerupPreparationPendingMaterializationError",
        "native_applied_powerup_result_drop_ids",
        "powerup_skill_resulting_active",
        "damage_x4_remaining_ticks",
    ):
        assert token in pickup_authority, f"powerup result flow lacks: {token}"

    assert "QueueLocalHostPowerupPickup" in hook
    assert "TryQueueReplicatedLootPickupRequest" in hook
    assert "QueueClientLocalLootSuppressionInternal" in hook
    assert "ParkReplicatedLootPresentationActor" not in reconciliation
    assert "ParkReplicatedLootPresentationActor" not in deactivation
    assert "CallActorWorldUnregisterSafe(" not in reconciliation
    assert "CallActorWorldUnregisterSafe(" not in deactivation
    assert "CallActorRequestRetirementSafe(" in reconciliation
    assert "CallActorRequestRetirementSafe(" in deactivation
    assert "actor_request_retirement_vfunc=0x18" in layout
    assert "kReplicatedLootPowerupNativeTypeId = 0x07F6" in reconciliation
    assert 'spawn_kind = "bonus_skill"' in reconciliation
    assert 'spawn_kind = "random_skill"' in reconciliation
    assert 'spawn_kind = "damage_x4"' in reconciliation
    assert "ReconcileRemoteParticipantDamageX4State" in native_progression
    assert "packet->damage_x4_remaining_ticks" in local_state
    assert "normalized.damage_x4_remaining_ticks" in incoming_state
    assert '"damage_x4_remaining_ticks"' in lua_gameplay
    assert '"damage_x4_remaining_ticks"' in lua_runtime
    assert "powerup_pickup=0x006039C0" in layout
    assert "game_timing_scale=0x00820230" in layout
    assert "progression_damage_x4_remaining_ticks=0x824" in layout

    for token in (
        "verify_random_skill",
        "verify_damage_x4",
        "verify_bonus_skill",
        "wait_for_carrier_retirement_requested",
        "wait_for_carrier_unregistered",
        'layout_offset("actor_pending_remove")',
        "run_cases",
        "wait_for_entry_parity",
        "wait_for_damage_x4_parity",
        "Waiting on 1 player",
        "client_random_skill",
        "host_random_skill",
        "client_damage_x4",
        "host_damage_x4",
        "client_bonus_skill",
        "host_bonus_skill",
    ):
        assert token in verifier, f"powerup live verifier lacks: {token}"

    _require_in_order(
        bonus_skill_verifier,
        "accepted = wait_for_accepted_pickup(",
        "retirement_requested = wait_for_carrier_retirement_requested(",
        "offer = wait_for_local_offer(",
        "choice = choose_local_option(",
        "cleared = wait_for_waiting_ids(",
        "cleanup = wait_for_carrier_unregistered(",
    )

    for token in (
        "SteamFriendActivePair",
        "require_shared_test_run",
        "SDMOD_STEAM_HOST_INSTANCE",
        "SDMOD_STEAM_CLIENT_INSTANCE",
        "powerups.run_cases",
        "find_new_crash_artifacts",
    ):
        assert token in steam_verifier, f"Steam powerup verifier lacks: {token}"

    return (
        "stock bonus-skill, learned-skill-rank, and DamageX4 rewards use host "
        "pickup authority, exact native owner/observer application, and a two-owner live matrix"
    )


def test_exact_native_equipment_identity_and_color_replicate() -> str:
    protocol = _read("SolomonDarkModLoader/include/multiplayer_runtime_protocol.h")
    local_state = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/local_state_packet_sync.inl"
    )
    incoming_state = read_source_unit(
        "SolomonDarkModLoader/src/multiplayer_local_transport/incoming_packet_sync.inl"
    )
    remote_playback = read_source_unit(
        "SolomonDarkModLoader/src/mod_loader_gameplay/bot_movement/native_remote_playback.inl"
    )
    local_equip = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/local_player_native_equipment.inl"
    )
    inventory_getter = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_state_getters.inl"
    )
    gameplay_constants = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/gameplay_constants.inl"
    )
    runtime_state = _read("SolomonDarkModLoader/include/multiplayer_runtime_state.h")
    lua_runtime = _read("SolomonDarkModLoader/src/lua_engine_bindings_runtime.cpp")
    binary_layout = _read("config/binary-layout.ini")
    public_equip = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_inventory.inl"
    )
    public_header = _read(
        "SolomonDarkModLoader/include/mod_loader_gameplay_api.inl"
    )
    lua_gameplay = _read("SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp")
    pump = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_pump_loop.inl"
    )
    verifier = _read("tools/verify_multiplayer_native_item_inventory_sync.py")

    for token in (
        "constexpr std::uint16_t kProtocolVersion = 70;",
        "ParticipantPresentationFlagEquipmentState = 1 << 5",
        "std::uint32_t primary_visual_link_recipe_uid;",
        "std::uint32_t secondary_visual_link_recipe_uid;",
        "std::uint32_t attachment_visual_link_recipe_uid;",
        "constexpr std::uint32_t kParticipantRingSlotCount = 3;",
        "struct ParticipantEquippedItemPacketState",
        "std::uint32_t equipment_revision;",
        "ParticipantEquippedItemPacketState equipped_rings[kParticipantRingSlotCount];",
        "ParticipantEquippedItemPacketState equipped_amulet;",
        "static_assert(sizeof(StatePacket) == 4488",
    ):
        assert token in protocol, f"exact equipment packet contract lacks: {token}"

    _require_in_order(
        local_state,
        "TryReadVisualLinkColorBlock(",
        "ParticipantPresentationFlagEquipmentState",
        "local->runtime.primary_visual_link_recipe_uid = primary_visual_recipe_uid;",
        "local->runtime.attachment_visual_link_recipe_uid =",
        "packet->primary_visual_link_recipe_uid =",
        "packet->attachment_visual_link_recipe_uid =",
    )
    _require_in_order(
        incoming_state,
        "void ApplyParticipantFrameToRuntime(",
        "participant->runtime.primary_visual_link_recipe_uid =",
        "participant->runtime.attachment_visual_link_recipe_uid =",
        "sample.primary_visual_link_recipe_uid =",
        "sample.attachment_visual_link_recipe_uid =",
    )
    _require_in_order(
        incoming_state,
        "equipment_packet_is_sane",
        "packet.equipped_rings",
        "participant->owned_progression.equipment_revision =",
    )

    for token in (
        "ApplyNativeRemoteParticipantEquipmentState(",
        "desired_type_id == 0",
        "SetEquipVisualLaneObject(",
        "CloneNativeItemFromRecipe(",
        "TryApplyNativeRemoteParticipantWearableColor(",
        "current.current_object_recipe_uid == desired_recipe_uid",
        "RefreshParticipantNativeProgression(",
        "equipment_reconcile_not_before_ms",
    ):
        assert token in remote_playback, f"remote native equipment reconciliation lacks: {token}"

    for token in (
        "RemoveNativeInventoryItemPointer(",
        "CallPointerListRemoveValueSafe(",
        "AttachLocalNativeEquipmentObject(",
        "ResolveLocalNativeEquipLaneByHolder(",
        "CallInventoryInsertOrStackItemSafe(",
        "RestoreLocalNativeEquipTransaction(",
        "CallActorProgressionRefreshSafe(",
        "current_object_recipe_uid != request.recipe_uid",
        "kStandaloneWizardRingItemTypeId",
        "kStandaloneWizardAmuletItemTypeId",
        "inventory.ring_lanes[index]",
        "inventory.amulet_lane",
    ):
        assert token in local_equip, f"local native equip transaction lacks: {token}"
    assert "kInventoryPlaceholderItemTypeId" in gameplay_constants
    inventory_snapshot_tree = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/inventory_snapshot_tree.inl"
    )
    inventory_snapshot_sources = inventory_getter + inventory_snapshot_tree
    for token in (
        "state->raw_item_count = raw_item_count;",
        "for (int index = 0; index < raw_item_count; ++index)",
        "item_type_id == kInventoryPlaceholderItemTypeId",
        "++walk->snapshot->item_count;",
    ):
        assert token in inventory_snapshot_sources, (
            f"native inventory placeholder filtering lacks: {token}"
        )
    assert 'lua_setfield(state, -2, "raw_item_count")' in lua_gameplay
    _require_in_order(
        local_equip,
        "kGameplayInventoryDirtyOffset",
        "RemoveNativeInventoryItemPointer(",
        "AttachLocalNativeEquipmentObject(",
        "CallActorProgressionRefreshSafe(",
        "Native equipment verification did not converge",
    )

    for token in (
        "ParticipantEquipmentState",
        "std::uint32_t equipment_revision = 0;",
        "std::array<ParticipantEquippedItemState, kParticipantRingSlotCount> rings;",
    ):
        assert token in runtime_state, f"owned equipment state lacks: {token}"
    for token in (
        "RefreshOwnedEquipmentFromSnapshot(inventory_state",
        "packet.equipment_revision = local->owned_progression.equipment_revision;",
        "packet.equipped_rings[index]",
        "packet.equipped_amulet",
    ):
        assert token in local_state, f"owner equipment packet authoring lacks: {token}"
    for token in (
        "kGameplayEquipmentRing0Offset",
        "kGameplayEquipmentRing1Offset",
        "kGameplayEquipmentRing2Offset",
        "kGameplayEquipmentAmuletOffset",
        "state->ring_lanes[0]",
        "state->amulet_lane",
    ):
        assert token in inventory_getter, f"native ring/amulet capture lacks: {token}"
    for token in (
        "gameplay_equipment_ring_0=0x1430",
        "gameplay_equipment_ring_1=0x1434",
        "gameplay_equipment_ring_2=0x1438",
        "gameplay_equipment_amulet=0x143C",
    ):
        assert token in binary_layout, f"native equipment layout lacks: {token}"
    for token in (
        "PushEquipmentIdentityState",
        'lua_setfield(state, -2, "rings")',
        'lua_setfield(state, -2, "amulet")',
        'lua_setfield(state, -2, "equipment_revision")',
    ):
        assert token in lua_runtime, f"Lua equipment audit surface lacks: {token}"

    assert "bool QueuePlayerInventoryItemEquip(" in public_header
    assert "pending_local_inventory_equip_requests" in public_equip
    assert "ExecuteLocalInventoryEquipNow(" in pump
    assert "QueuePlayerInventoryItemEquip(" in lua_gameplay
    assert 'RegisterFunction(state, &LuaPlayerEquipInventoryItem, "equip_inventory_item")' in lua_gameplay

    for token in (
        "sd.player.equip_inventory_item",
        "previous_item_returned",
        "host_native_remote_equipment",
        "host_bot_color_matches",
        'last["client_inventory_revision"] > accepted_revision',
        'last["host_inventory_revision"] > accepted_revision',
        'all(last["color_matches"].values())',
    ):
        assert token in verifier, f"native equipment live verifier lacks: {token}"

    return (
        "exact hat/robe/staff-or-wand presentation plus all three ring slots and the amulet "
        "flow from stock local ownership through protocol v65; visible lanes self-correct natively"
    )
