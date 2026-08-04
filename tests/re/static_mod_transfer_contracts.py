"""Host-to-joiner staged mod transfer contracts."""

from __future__ import annotations

from static_multiplayer_contract_support import _read, _require_in_order


def test_mod_transfer_protocol_is_versioned_fixed_width_and_bounded() -> str:
    protocol = _read(
        "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h"
    )
    launcher_protocol = _read(
        "SolomonDarkModLauncher/src/Mods/HostModTransferProtocol.cs"
    )

    for token in (
        "constexpr std::uint16_t kProtocolVersion = 92;",
        "ModTransferManifestRequest = 34",
        "ModTransferManifestResponse = 35",
        "ModTransferDescriptorRequest = 36",
        "ModTransferDescriptorResponse = 37",
        "ModTransferChunkRequest = 38",
        "ModTransferChunkResponse = 39",
        "ModTransferComplete = 40",
        "ModTransferAbort = 41",
        "kModTransferChunkPayloadBytes = 1024",
        "kModTransferMaxPackages = 128",
        "100ull * 1024ull * 1024ull",
        "512ull * 1024ull * 1024ull",
        "sizeof(ModTransferChunkResponsePacket) == 1152",
    ):
        assert token in protocol, f"native mod transfer protocol lacks: {token}"
    for token in (
        "public const ushort Version = 91;",
        "public const int ChunkBytes = 1024;",
        "public const int MaximumPackages = 128;",
        "public const long MaximumPackageBytes = 100L * 1024 * 1024;",
        "public const long MaximumTotalBytes = 512L * 1024 * 1024;",
        "CryptographicOperations.FixedTimeEquals",
        "SHA256.HashData(payload)",
    ):
        assert token in launcher_protocol, (
            f"launcher mod transfer codec lacks: {token}"
        )
    return (
        "protocol 92 reserves one fixed-width, digest-checked packet family "
        "with 1 KiB chunks and explicit package and aggregate bounds"
    )


def test_mod_transfer_file_io_is_worker_owned_and_tick_budgeted() -> str:
    service = _read(
        "SolomonDarkModLoader/src/host_mod_transfer_service.cpp"
    )
    index_loader = _read(
        "SolomonDarkModLoader/src/host_mod_transfer_service/index_loading.inl"
    )
    local_send = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "outgoing_endpoint_send.inl"
    )
    local_tick = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "public_cast_loot_api.inl"
    )

    for token in (
        "constexpr std::size_t kMaximumQueuedRequests = 64;",
        "constexpr std::size_t kMaximumQueuedChunkRequests = 24;",
        "constexpr std::size_t kMaximumChunkRequestsPerTransfer = 8;",
        "kMaximumPreparedResponseBytesPerTransfer = 64 * 1024;",
        "constexpr std::size_t kMaximumPreparedResponseBytes = 192 * 1024;",
        "constexpr std::size_t kMaximumActiveTransfers = 3;",
        "_beginthreadex(",
        "unsigned __stdcall WorkerMain",
        "ProcessRequest(request);",
    ):
        assert token in service, f"worker ownership or bound lacks: {token}"
    assert "std::ifstream" in service + index_loader
    assert "std::ifstream" not in local_send + local_tick
    _require_in_order(
        local_tick,
        "ReceivePackets(now_ms);",
        "DrainLocalHostModTransferResponses();",
        'finish_stage("mod_transfer_send");',
    )
    _require_in_order(
        local_send,
        "TakeHostModTransferResponses(",
        "8,",
        "8);",
        "SendBufferToEndpoint(",
    )
    return (
        "a dedicated worker owns index, package, and hash IO while the game "
        "tick only submits bounded requests and drains eight chunk responses"
    )


def test_mod_transfer_uses_one_session_service_for_udp_and_steam() -> str:
    service_loop = _read(
        "SolomonDarkModLoader/src/multiplayer_service_loop.cpp"
    )
    local_receive = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "incoming_packet_dispatch.inl"
    )
    local_receive += _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "host_mod_transfer_dispatch.inl"
    )
    local_send = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "outgoing_endpoint_send.inl"
    )
    steam = _read(
        "SolomonDarkModLoader/src/multiplayer_steam_session/"
        "network_messages.inl"
    )

    assert "IsLocalTransportHost() || IsSteamSessionHost()" in service_loop
    for source, backend in (
        (local_receive, "HostModTransferBackend::LocalUdp"),
        (steam, "HostModTransferBackend::Steam"),
    ):
        assert backend in source
        assert "SubmitHostModTransferPacket(" in source
    assert "TakeHostModTransferResponses(" in local_send
    assert "TakeHostModTransferResponses(" in steam
    for token in (
        "IsLobbyMember(message.sender_steam_id)",
        "lobby_id == g_session.lobby_id",
        "SteamNetworkSendMode::ReliableNoNagle",
    ):
        assert token in steam, f"Steam transfer routing lacks: {token}"
    return (
        "local UDP and Steam authenticate their own routes but submit into and "
        "drain from the same transport-agnostic session transfer service"
    )


def test_mod_transfer_consent_reuses_the_existing_join_prompt() -> str:
    view_model = _read(
        "SolomonDarkModLauncher.UI/src/ViewModels/MainWindowViewModel.cs"
    )
    synchronizer = _read(
        "SolomonDarkModLauncher/src/Mods/LobbyModSynchronizer.cs"
    )
    parser = _read(
        "SolomonDarkModLauncher/src/Commands/LauncherCommandParser.cs"
    )

    for token in (
        'ModDownloadPromptTitle = "This lobby uses mods";',
        'ModDownloadConfirmText = "Download and join";',
        'ModDownloadDeclineText = "Cancel";',
        'StatusText = "Join canceled - nothing was downloaded.";',
        '" (directly from host)"',
        "allowHostModTransfer: true",
    ):
        assert token in view_model, f"join consent path lacks: {token}"
    _require_in_order(
        synchronizer,
        "var direct = allowHostModTransfer",
        "await GetHostTransferAsync()",
        "direct?.Catalog.Find(requirement)",
        "DownloadAndInstallAsync(",
    )
    assert 'if (arg == "--allow-host-mod-transfer")' in parser
    assert (
        "--allow-host-mod-transfer requires stage or launch with "
        "--multiplayer join and --lobby-id."
    ) in parser
    return (
        "the existing download-and-join prompt alone grants host-byte transfer, "
        "while decline keeps the established clean cancel path"
    )


def test_mod_transfer_reuses_package_integrity_and_atomic_staging() -> str:
    client = _read(
        "SolomonDarkModLauncher/src/Mods/HostModTransferClient.cs"
    )
    client += _read(
        "SolomonDarkModLauncher/src/Mods/HostModTransferClient.Download.cs"
    )
    installer = _read(
        "SolomonDarkModLauncher/src/Mods/WebsiteModPackageInstaller.cs"
    )
    materializer = _read(
        "SolomonDarkModLauncher/src/Staging/"
        "HostModTransferPackageMaterializer.cs"
    )
    stage_builder = _read(
        "SolomonDarkModLauncher/src/Staging/StageBuilder.cs"
    )

    _require_in_order(
        client,
        "SHA256.HashDataAsync(archive, cancellationToken)",
        "Host package digest matched.",
        "WebsiteModPackageInstaller.InstallArchiveAsync(",
        "Host content digest matched",
        "HostModTransferProtocol.CreateComplete(",
        "DeleteOperation(operationRoot);",
    )
    for token in (
        "HostModTransferAbortReason.PackageDigestMismatch",
        "HostModTransferAbortReason.ContentDigestMismatch",
        "WriteReceiptAsync(",
        "File.Move(temporaryPath, receiptPath, overwrite: true);",
        "private const int ChunkWindow = 8;",
    ):
        assert token in client, f"resume or integrity behavior lacks: {token}"
    _require_in_order(
        installer,
        "actualPackageSha256",
        "ExtractAsync(",
        "ModContentHasher.HashDirectory(extractedPath)",
        "Directory.Move(extractedPath, targetPath);",
    )
    for token in (
        "ValidatePackageableSource(mod)",
        "CreateDeterministicArchive",
        '"SDMXFER\\0"u8',
        "compatibility.FingerprintSha256",
    ):
        assert token in materializer, (
            f"host package staging lacks: {token}"
        )
    _require_in_order(
        stage_builder,
        "MultiplayerCompatibilityMaterializer.Materialize(",
        "HostModTransferPackageMaterializer.Materialize(",
        "hostModTransfer);",
    )
    return (
        "only host-staged deterministic mod archives transfer; package and "
        "content digests pass through the website installer's atomic promotion"
    )
