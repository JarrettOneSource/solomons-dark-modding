using System.Text.Json;
using SolomonDarkModLauncher.Commands;
using SolomonDarkModLauncher.Infrastructure;
using SolomonDarkModLauncher.Mods;
using SolomonDarkModLauncher.Staging;
using SolomonDarkModLauncher.Steam;

namespace SolomonDarkModLauncher.App;

internal static class LauncherJsonConsole
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase
    };

    public static void PrintExecution(LauncherCommandExecution execution)
    {
        var runtimeFlags = RuntimeStageFlags.Create(execution.Configuration.Runtime);

        var response = new LauncherJsonResponse
        {
            Success = true,
            Mode = GetModeToken(execution.Command.Mode),
            Transcript = LauncherOutputFormatter.FormatExecution(execution),
            Error = null,
            Configuration = new LauncherJsonConfiguration
            {
                WorkspaceRoot = execution.Configuration.Workspace.RootPath,
                Instance = execution.Configuration.Workspace.InstanceName,
                GameDirectory = execution.Configuration.Game.InstallDirectory,
                ConfigRoot = execution.Configuration.Workspace.ConfigRootPath,
                ModsRoot = execution.Configuration.Workspace.ModsRootPath,
                ModCacheRoot = execution.Configuration.Workspace.ModCacheRootPath,
                ModStatePath = execution.Configuration.Workspace.ModStatePath,
                StageRoot = execution.Configuration.Workspace.StageRootPath,
                ProfileRoot = execution.Configuration.Workspace.ProfileRootPath,
                IsolatedGameAppDataPath = execution.Configuration.Workspace.IsolatedGameAppDataPath,
                RuntimeProfile = SolomonDarkModLauncher.Staging.RuntimeStageFlags.ToProfileName(execution.Configuration.Runtime.Profile),
                HasRuntimeFlagOverrides = execution.Configuration.Runtime.HasOverrides,
                TemporaryProfile = execution.Command.TemporaryProfile,
                LoaderDebugUi = runtimeFlags.LoaderDebugUi,
                SteamAppId = execution.Configuration.Steam.AppId,
                SteamApiOverride = execution.Configuration.Steam.ApiDllOverridePath
            },
            Mods = execution.Catalog.DiscoveredMods.Select(
                mod => new LauncherJsonMod
                {
                    Id = mod.Manifest.Id,
                    Name = mod.Manifest.Name,
                    Version = mod.Manifest.Version,
                    Priority = mod.Manifest.Priority,
                    RuntimeKind = mod.Manifest.RuntimeKind,
                    OverlayCount = mod.Manifest.Overlays.Count,
                    RequiredMods = mod.Manifest.RequiredMods.ToArray(),
                    RootPath = mod.RootPath,
                    ManifestPath = mod.ManifestPath,
                    Enabled = execution.Catalog.IsEnabled(mod)
                }).ToArray(),
            LobbyModSync = execution.LobbyModSync is null
                ? null
                : new LauncherJsonLobbyModSync
                {
                    UsedWebsite = execution.LobbyModSync.UsedWebsite,
                    FallbackReason = execution.LobbyModSync.FallbackReason,
                    RequiredModCount = execution.LobbyModSync.RequiredModCount,
                    ReusedManualModCount = execution.LobbyModSync.ReusedManualModCount,
                    ReusedCachedModCount = execution.LobbyModSync.ReusedCachedModCount,
                    DownloadedModCount = execution.LobbyModSync.DownloadedModCount
                },
            JoinPreview = execution.JoinPreview is null
                ? null
                : new LauncherJsonJoinPreview
                {
                    LobbyId = execution.JoinPreview.LobbyId,
                    UsedWebsite = execution.JoinPreview.UsedWebsite,
                    Error = execution.JoinPreview.Error,
                    HostProtocolVersion = execution.JoinPreview.HostBuild?.ProtocolVersion,
                    HostLoaderVersion = execution.JoinPreview.HostBuild?.LoaderVersion,
                    HostManifestSha256 = execution.JoinPreview.HostBuild?.ManifestSha256,
                    LocalProtocolVersion = MultiplayerCompatibilityMaterializer.CurrentProtocolVersion,
                    LocalLoaderVersion = LauncherVersionInfo.Informational,
                    InstalledCount = execution.JoinPreview.InstalledCount,
                    CachedCount = execution.JoinPreview.CachedCount,
                    DownloadCount = execution.JoinPreview.DownloadCount,
                    UnavailableCount = execution.JoinPreview.UnavailableCount,
                    Mods = execution.JoinPreview.Mods.Select(mod => new LauncherJsonJoinPreviewMod
                    {
                        Id = mod.Id,
                        Version = mod.Version,
                        Name = mod.Name,
                        State = mod.State switch
                        {
                            LobbyJoinPreviewModState.Installed => "installed",
                            LobbyJoinPreviewModState.Cached => "cached",
                            LobbyJoinPreviewModState.NeedsDownload => "needsDownload",
                            LobbyJoinPreviewModState.Unavailable => "unavailable",
                            _ => "unknown"
                        },
                        InstalledVersion = mod.InstalledVersion,
                        DownloadSizeBytes = mod.DownloadSizeBytes
                    }).ToArray()
                },
            Stage = execution.StageResult is null
                ? null
                : new LauncherJsonStage
                {
                    StageRoot = execution.StageResult.StageRootPath,
                    StageExecutablePath = execution.StageResult.StageExecutablePath,
                    StageReportPath = execution.StageResult.StageReportPath,
                    StageConfigRootPath = execution.StageResult.StageConfigRootPath,
                    StageBinaryLayoutPath = execution.StageResult.StageBinaryLayoutPath,
                    StageDebugUiConfigPath = execution.StageResult.StageDebugUiConfigPath,
                    StageRuntimeRootPath = execution.StageResult.StageRuntimeRootPath,
                    StageRuntimeBootstrapPath = execution.StageResult.StageRuntimeBootstrapPath,
                    StageRuntimeFlagsPath = execution.StageResult.StageRuntimeFlagsPath,
                    EnabledModCount = execution.StageResult.EnabledModCount,
                    AppliedOverlayCount = execution.StageResult.AppliedOverlayCount,
                    HudLabel = execution.StageResult.HudLabels.Label,
                    HudLabelApplied = execution.StageResult.HudLabels.Applied,
                    HudLabelRecordIndex = execution.StageResult.HudLabels.RecordIndex
                },
            Launch = execution.LaunchedGame is null
                ? null
                : new LauncherJsonLaunch
                {
                    ProcessId = execution.LaunchedGame.ProcessId,
                    LaunchToken = execution.LaunchedGame.LaunchToken,
                    StartedAtUtc = execution.LaunchedGame.StartedAtUtc,
                    LoaderPath = execution.LaunchedGame.LoaderPath,
                    StartupCode = execution.LaunchedGame.StartupStatus.Code,
                    StartupMessage = execution.LaunchedGame.StartupStatus.Message,
                    StartupLogPath = execution.LaunchedGame.StartupStatus.LogPath,
                    MultiplayerSession = execution.LaunchedGame.MultiplayerSessionStatus is { } session
                        ? new LauncherJsonMultiplayerSession
                        {
                            LaunchToken = session.LaunchToken,
                            Enabled = session.Enabled,
                            IsHost = session.IsHost,
                            Phase = session.Phase,
                            GamePhase = session.GamePhase,
                            AppId = session.AppId,
                            LobbyId = session.LobbyId,
                            HostSteamId = session.HostSteamId,
                            LocalSteamId = session.LocalSteamId,
                            PersonaName = session.PersonaName,
                            Privacy = session.Privacy,
                            ProtocolVersion = session.ProtocolVersion,
                            ManifestSha256 = session.ManifestSha256,
                            FriendSteamIds = session.FriendSteamIds,
                            MaxParticipants = session.MaxParticipants,
                            AuthenticatedPeerCount = session.AuthenticatedPeerCount,
                            OverlayEnabled = session.OverlayEnabled,
                            InviteDialogOpened = session.InviteDialogOpened,
                            InviteSent = session.InviteSent,
                            RouteRelayed = session.RouteRelayed,
                            RoutePingMs = session.RoutePingMs,
                            Members = session.Members.Select(member =>
                                new LauncherJsonLobbyMember
                                {
                                    SteamId = member.SteamId,
                                    Name = member.Name,
                                    IsHost = member.IsHost,
                                    IsLocal = member.IsLocal
                                }).ToArray(),
                            StatusText = session.StatusText,
                            ErrorText = session.ErrorText
                        }
                        : null
                },
            ModStateChange = execution.ModStateChange is null
                ? null
                : new LauncherJsonModStateChange
                {
                    ModId = execution.ModStateChange.ModId,
                    Enabled = execution.ModStateChange.Enabled,
                    StatePath = execution.ModStateChange.StatePath
                }
        };

        Console.WriteLine(JsonSerializer.Serialize(response, JsonOptions));
    }

    public static void PrintError(Exception ex)
    {
        var response = new LauncherJsonResponse
        {
            Success = false,
            Mode = null,
            Transcript = null,
            Error = ex.Message,
            Configuration = null,
            Mods = [],
            LobbyModSync = null,
            JoinPreview = null,
            Stage = null,
            Launch = null,
            ModStateChange = null
        };

        Console.Error.WriteLine(JsonSerializer.Serialize(response, JsonOptions));
    }

    public static void PrintDirectorySession(SteamDirectorySession session)
    {
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            success = true,
            mode = "directory-auth",
            directorySession = session
        }, JsonOptions));
    }

    private static string GetModeToken(LauncherMode mode)
    {
        return mode switch
        {
            LauncherMode.Launch => "launch",
            LauncherMode.Stage => "stage",
            LauncherMode.ListMods => "list-mods",
            LauncherMode.EnableMod => "enable-mod",
            LauncherMode.DisableMod => "disable-mod",
            LauncherMode.JoinPreview => "join-preview",
            _ => throw new InvalidOperationException($"Unsupported mode: {mode}")
        };
    }

    private sealed class LauncherJsonResponse
    {
        public required bool Success { get; init; }
        public required string? Mode { get; init; }
        public required string? Transcript { get; init; }
        public required string? Error { get; init; }
        public required LauncherJsonConfiguration? Configuration { get; init; }
        public required IReadOnlyList<LauncherJsonMod> Mods { get; init; }
        public required LauncherJsonLobbyModSync? LobbyModSync { get; init; }
        public required LauncherJsonJoinPreview? JoinPreview { get; init; }
        public required LauncherJsonStage? Stage { get; init; }
        public required LauncherJsonLaunch? Launch { get; init; }
        public required LauncherJsonModStateChange? ModStateChange { get; init; }
    }

    private sealed class LauncherJsonLobbyModSync
    {
        public required bool UsedWebsite { get; init; }
        public required string? FallbackReason { get; init; }
        public required int RequiredModCount { get; init; }
        public required int ReusedManualModCount { get; init; }
        public required int ReusedCachedModCount { get; init; }
        public required int DownloadedModCount { get; init; }
    }

    private sealed class LauncherJsonJoinPreview
    {
        public required ulong LobbyId { get; init; }
        public required bool UsedWebsite { get; init; }
        public required string? Error { get; init; }
        public required int? HostProtocolVersion { get; init; }
        public required string? HostLoaderVersion { get; init; }
        public required string? HostManifestSha256 { get; init; }
        public required int LocalProtocolVersion { get; init; }
        public required string LocalLoaderVersion { get; init; }
        public required int InstalledCount { get; init; }
        public required int CachedCount { get; init; }
        public required int DownloadCount { get; init; }
        public required int UnavailableCount { get; init; }
        public required IReadOnlyList<LauncherJsonJoinPreviewMod> Mods { get; init; }
    }

    private sealed class LauncherJsonJoinPreviewMod
    {
        public required string Id { get; init; }
        public required string Version { get; init; }
        public required string? Name { get; init; }
        public required string State { get; init; }
        public required string? InstalledVersion { get; init; }
        public required long? DownloadSizeBytes { get; init; }
    }

    private sealed class LauncherJsonConfiguration
    {
        public required string WorkspaceRoot { get; init; }
        public required string Instance { get; init; }
        public required string GameDirectory { get; init; }
        public required string ConfigRoot { get; init; }
        public required string ModsRoot { get; init; }
        public required string ModCacheRoot { get; init; }
        public required string ModStatePath { get; init; }
        public required string StageRoot { get; init; }
        public required string ProfileRoot { get; init; }
        public required string IsolatedGameAppDataPath { get; init; }
        public required string RuntimeProfile { get; init; }
        public required bool HasRuntimeFlagOverrides { get; init; }
        public required bool TemporaryProfile { get; init; }
        public required bool LoaderDebugUi { get; init; }
        public required string SteamAppId { get; init; }
        public required string? SteamApiOverride { get; init; }
    }

    private sealed class LauncherJsonMod
    {
        public required string Id { get; init; }
        public required string Name { get; init; }
        public required string Version { get; init; }
        public required int Priority { get; init; }
        public required string RuntimeKind { get; init; }
        public required int OverlayCount { get; init; }
        public required IReadOnlyList<string> RequiredMods { get; init; }
        public required string RootPath { get; init; }
        public required string ManifestPath { get; init; }
        public required bool Enabled { get; init; }
    }

    private sealed class LauncherJsonStage
    {
        public required string StageRoot { get; init; }
        public required string StageExecutablePath { get; init; }
        public required string StageReportPath { get; init; }
        public required string StageConfigRootPath { get; init; }
        public required string StageBinaryLayoutPath { get; init; }
        public required string StageDebugUiConfigPath { get; init; }
        public required string StageRuntimeRootPath { get; init; }
        public required string StageRuntimeBootstrapPath { get; init; }
        public required string StageRuntimeFlagsPath { get; init; }
        public required int EnabledModCount { get; init; }
        public required int AppliedOverlayCount { get; init; }
        public required string HudLabel { get; init; }
        public required bool HudLabelApplied { get; init; }
        public required int HudLabelRecordIndex { get; init; }
    }

    private sealed class LauncherJsonLaunch
    {
        public required int ProcessId { get; init; }
        public required string LaunchToken { get; init; }
        public required DateTimeOffset StartedAtUtc { get; init; }
        public required string LoaderPath { get; init; }
        public required string StartupCode { get; init; }
        public required string StartupMessage { get; init; }
        public required string? StartupLogPath { get; init; }
        public required LauncherJsonMultiplayerSession? MultiplayerSession { get; init; }
    }

    private sealed class LauncherJsonMultiplayerSession
    {
        public required string LaunchToken { get; init; }
        public required bool Enabled { get; init; }
        public required bool IsHost { get; init; }
        public required string Phase { get; init; }
        public required string GamePhase { get; init; }
        public required uint AppId { get; init; }
        public required ulong LobbyId { get; init; }
        public required ulong HostSteamId { get; init; }
        public required ulong LocalSteamId { get; init; }
        public required string PersonaName { get; init; }
        public required string Privacy { get; init; }
        public required int ProtocolVersion { get; init; }
        public required string ManifestSha256 { get; init; }
        public required IReadOnlyList<ulong> FriendSteamIds { get; init; }
        public required uint MaxParticipants { get; init; }
        public required uint AuthenticatedPeerCount { get; init; }
        public required bool OverlayEnabled { get; init; }
        public required bool InviteDialogOpened { get; init; }
        public required bool InviteSent { get; init; }
        public required bool RouteRelayed { get; init; }
        public required int RoutePingMs { get; init; }
        public required IReadOnlyList<LauncherJsonLobbyMember> Members { get; init; }
        public required string StatusText { get; init; }
        public required string ErrorText { get; init; }
    }

    private sealed class LauncherJsonLobbyMember
    {
        public required ulong SteamId { get; init; }
        public required string Name { get; init; }
        public required bool IsHost { get; init; }
        public required bool IsLocal { get; init; }
    }

    private sealed class LauncherJsonModStateChange
    {
        public required string ModId { get; init; }
        public required bool Enabled { get; init; }
        public required string StatePath { get; init; }
    }
}
