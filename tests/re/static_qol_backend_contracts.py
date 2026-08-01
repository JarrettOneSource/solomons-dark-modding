"""Owner QoL backend contracts for session teardown and retail close behavior."""

from __future__ import annotations

import struct
from pathlib import Path

from static_re_contract_support import (
    ABANDONWARE_BINARY,
    BINARY_LAYOUT,
    MOD_LOADER_PROJECT,
    MOD_LOADER_PROJECT_FILTERS,
    ROOT,
    StaticReTestFailure,
    read_text,
    sha256,
)


EXPECTED_BINARY_SHA256 = (
    "03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3"
)


def _mapped_bytes(
    path: Path,
    virtual_address: int,
    size: int,
) -> bytes:
    data = path.read_bytes()
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise StaticReTestFailure(f"not a PE image: {path}")
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe_offset:pe_offset + 4] != b"PE\0\0":
        raise StaticReTestFailure(f"missing PE signature: {path}")
    section_count = struct.unpack_from("<H", data, pe_offset + 6)[0]
    optional_size = struct.unpack_from("<H", data, pe_offset + 20)[0]
    optional = pe_offset + 24
    image_base = struct.unpack_from("<I", data, optional + 28)[0]
    rva = virtual_address - image_base
    section_table = optional + optional_size
    for index in range(section_count):
        section = section_table + index * 40
        virtual_size, section_rva, raw_size, raw_offset = struct.unpack_from(
            "<IIII",
            data,
            section + 8,
        )
        if section_rva <= rva and rva + size <= section_rva + max(
            virtual_size,
            raw_size,
        ):
            offset = raw_offset + rva - section_rva
            return data[offset:offset + size]
    raise StaticReTestFailure(
        f"virtual range 0x{virtual_address:X}+{size} is not mapped"
    )


def test_live_session_leave_acks_before_canonical_teardown() -> str:
    binding = read_text(
        ROOT / "SolomonDarkModLoader/src/lua_engine_bindings_session.cpp"
    )
    pipe = read_text(
        ROOT / "SolomonDarkModLoader/src/lua_exec_pipe.cpp"
    )
    coordinator = read_text(
        ROOT / "SolomonDarkModLoader/src/multiplayer_session_teardown.cpp"
    )
    control_state = read_text(
        ROOT / "SolomonDarkModLoader/src/lua_exec_control_state.cpp"
    )

    required = (
        (binding, '"sd.__session_leave"'),
        (binding, "RequestSessionLeaveAfterPipeAck(&error)"),
        (binding, '"__session_leave"'),
        (control_state, "InitializeLuaExecControlState"),
        (control_state, 'lua_setglobal(state, "sd")'),
        (coordinator, "LeavePipeState::AwaitingResponse"),
        (coordinator, "LeavePipeState::Armed"),
        (coordinator, "TickSessionTeardownOnAppThread"),
        (coordinator, "BeginSessionTeardown("),
        (coordinator, "PostGracefulGameClose();"),
    )
    missing = [token for text, token in required if token not in text]
    if missing:
        raise StaticReTestFailure(
            "live-session leave seam is incomplete: " + ", ".join(missing)
        )

    write = pipe.find("const bool delivered = WritePipeMessage(pipe, payload);")
    arm = pipe.find(
        "multiplayer::ResolveSessionLeavePipeResponse(delivered);"
    )
    if not 0 <= write < arm:
        raise StaticReTestFailure(
            "the exec pipe arms teardown before writing and flushing its ACK"
        )
    if "FlushFileBuffers(pipe)" not in pipe[:write]:
        raise StaticReTestFailure(
            "the leave ACK is not flushed before teardown is armed"
        )
    return (
        "the privileged zero-mod Lua control state returns the standard pipe "
        "response before arming canonical teardown on the next app tick"
    )


def test_all_session_end_paths_share_provider_and_directory_teardown() -> str:
    coordinator = read_text(
        ROOT / "SolomonDarkModLoader/src/multiplayer_session_teardown.cpp"
    )
    steam = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_steam_session/public_lifecycle.inl"
    )
    steam_lobby = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_steam_session/lobby_and_events.inl"
    )
    local = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/session_teardown_sync.inl"
    )
    foundation = read_text(
        ROOT / "SolomonDarkModLoader/src/multiplayer_foundation.cpp"
    )
    publisher = read_text(
        ROOT
        / "SolomonDarkModLauncher/src/Launch/LobbyDirectoryPublisher.cs"
    )
    view_model = read_text(
        ROOT
        / "SolomonDarkModLauncher.UI/src/ViewModels/MainWindowViewModel.cs"
    )
    staged_launcher = read_text(
        ROOT
        / "SolomonDarkModLauncher/src/Launch/StagedGameLauncher.cs"
    )

    required = (
        (coordinator, '"explicit_leave"'),
        (coordinator, '"host_closed"'),
        (coordinator, '"authority_lost"'),
        (coordinator, '"process_exit"'),
        (coordinator, "RequestDirectoryDelist("),
        (coordinator, "RequestSteamSessionTeardown("),
        (coordinator, "RequestLocalTransportTeardown("),
        (foundation, "PrepareSessionTeardownForProcessExit();"),
        (steam, "SendGoodbyeToAuthenticatedPeers(reason);"),
        (steam, "BeginSteamSessionTeardown("),
        (steam, "kSteamTeardownGoodbyeGraceMs"),
        (steam, "SteamSetLobbyJoinable(g_session.lobby_id, false);"),
        (steam, "SteamLeaveLobby(g_session.lobby_id);"),
        (
            steam_lobby,
            "Steam client lobby recovery expired; ending the session through",
        ),
        (steam_lobby, "NotifySessionAuthorityLost();"),
        (local, "kLocalTeardownSendCount = 3"),
        (local, "NotifyRemoteHostSessionClosed();"),
        (local, "NotifySessionAuthorityLost();"),
        (publisher, "HasValidTeardownRequest(configuration)"),
        (publisher, "await TryDelistAsync("),
        (publisher, "if (!teardownRequested &&"),
        (view_model, "liveSessionClient_.LeaveAsync("),
        (view_model, "TimeSpan.FromMilliseconds(4000)"),
        (view_model, "TryOpenOwnedStagedProcess("),
        (view_model, "IsLocalUdpDevelopmentLaunch()"),
        (view_model, "LauncherUiCommandMode.LaunchSteamJoin"),
        (
            staged_launcher,
            'environmentOverrides["SDMOD_LUA_EXEC_PIPE_NAME"] =',
        ),
        (
            staged_launcher,
            "SolomonDarkModLoader_LuaExec_"
            "{configuration.Workspace.InstanceName}",
        ),
    )
    missing = [token for text, token in required if token not in text]
    if missing:
        raise StaticReTestFailure(
            "canonical teardown ownership is incomplete: "
            + ", ".join(missing)
        )
    return (
        "explicit leave, launcher close, normal exit, clean host close, and "
        "authority loss converge on provider teardown and host directory delist"
    )


def test_raptisoft_close_url_call_is_runtime_nopped() -> str:
    if not ABANDONWARE_BINARY.is_file():
        raise StaticReTestFailure(
            f"missing analyzed SolomonDark.exe: {ABANDONWARE_BINARY}"
        )
    observed_hash = sha256(ABANDONWARE_BINARY)
    if observed_hash != EXPECTED_BINARY_SHA256:
        raise StaticReTestFailure(
            "Raptisoft RE binary identity mismatch: "
            f"expected={EXPECTED_BINARY_SHA256} actual={observed_hash}"
        )
    original = _mapped_bytes(ABANDONWARE_BINARY, 0x005B65DE, 5)
    if original != bytes.fromhex("E8 CD D5 E6 FF"):
        raise StaticReTestFailure(
            "retail close-URL call bytes changed: "
            + original.hex(" ")
        )

    layout = read_text(BINARY_LAYOUT)
    patch = read_text(
        ROOT / "SolomonDarkModLoader/src/native_close_url_patch.cpp"
    )
    loader = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader.cpp"
    ) + read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader/initialize.inl"
    )
    project = read_text(MOD_LOADER_PROJECT)
    filters = read_text(MOD_LOADER_PROJECT_FILTERS)
    required = (
        (layout, "[native.runtime_patches]"),
        (layout, "raptisoft_close_url_launch_call=0x005B65DE"),
        (patch, "0xE8, 0xCD, 0xD5, 0xE6, 0xFF"),
        (patch, "0x90, 0x90, 0x90, 0x90, 0x90"),
        (patch, "observed != kOriginalCall"),
        (patch, "memory.TryWrite("),
        (patch, "Keep the close-path call disabled"),
        (loader, "InitializeNativeCloseUrlPatch("),
        (project, r"src\native_close_url_patch.cpp"),
        (filters, r"src\native_close_url_patch.cpp"),
    )
    missing = [token for text, token in required if token not in text]
    if missing:
        raise StaticReTestFailure(
            "Raptisoft runtime NOP is incomplete: " + ", ".join(missing)
        )
    shutdown_start = patch.find("void ShutdownNativeCloseUrlPatch()")
    if shutdown_start < 0 or "TryWrite(" in patch[shutdown_start:]:
        raise StaticReTestFailure(
            "close-path teardown can restore the URL-launch call before the "
            "retail application destructor runs"
        )
    return (
        "the supported retail CALL at 0x005B65DE is byte-validated and NOPed "
        "in process until Windows discards the image"
    )
