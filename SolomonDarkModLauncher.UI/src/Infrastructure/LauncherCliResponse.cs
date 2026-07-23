namespace SolomonDarkModLauncher.UI.Infrastructure;

internal sealed class LauncherCliResponse
{
    public bool Success { get; set; }
    public string? Mode { get; set; }
    public string? Transcript { get; set; }
    public string? Error { get; set; }
    public LauncherCliConfiguration? Configuration { get; set; }
    public List<LauncherCliMod> Mods { get; set; } = [];
    public LauncherCliModUpdate? ModUpdate { get; set; }
    public LauncherCliStage? Stage { get; set; }
    public LauncherCliLaunch? Launch { get; set; }
    public LauncherCliModStateChange? ModStateChange { get; set; }
}

internal sealed class LauncherCliModUpdate
{
    public int CheckedModCount { get; set; }
    public int UpdatedModCount { get; set; }
    public string? Error { get; set; }
    public List<LauncherCliUpdatedMod> Updates { get; set; } = [];
}

internal sealed class LauncherCliUpdatedMod
{
    public string Id { get; set; } = string.Empty;
    public string PreviousVersion { get; set; } = string.Empty;
    public string Version { get; set; } = string.Empty;
}

internal sealed class LauncherCliConfiguration
{
    public string WorkspaceRoot { get; set; } = string.Empty;
    public string Instance { get; set; } = string.Empty;
    public string GameDirectory { get; set; } = string.Empty;
    public string ConfigRoot { get; set; } = string.Empty;
    public string ModsRoot { get; set; } = string.Empty;
    public string ModStatePath { get; set; } = string.Empty;
    public string StageRoot { get; set; } = string.Empty;
    public string ProfileRoot { get; set; } = string.Empty;
    public string IsolatedGameAppDataPath { get; set; } = string.Empty;
    public string RuntimeProfile { get; set; } = string.Empty;
    public bool HasRuntimeFlagOverrides { get; set; }
    public bool LoaderDebugUi { get; set; }
    public string SteamAppId { get; set; } = string.Empty;
    public string? SteamApiOverride { get; set; }
}

internal sealed class LauncherCliMod
{
    public string Id { get; set; } = string.Empty;
    public string Name { get; set; } = string.Empty;
    public string Version { get; set; } = string.Empty;
    public int Priority { get; set; }
    public string RuntimeKind { get; set; } = string.Empty;
    public int OverlayCount { get; set; }
    public List<string> RequiredMods { get; set; } = [];
    public string RootPath { get; set; } = string.Empty;
    public string ManifestPath { get; set; } = string.Empty;
    public bool Enabled { get; set; }
}

internal sealed class LauncherCliStage
{
    public string StageRoot { get; set; } = string.Empty;
    public string StageExecutablePath { get; set; } = string.Empty;
    public string StageReportPath { get; set; } = string.Empty;
    public string StageConfigRootPath { get; set; } = string.Empty;
    public string StageBinaryLayoutPath { get; set; } = string.Empty;
    public string StageDebugUiConfigPath { get; set; } = string.Empty;
    public string StageRuntimeRootPath { get; set; } = string.Empty;
    public string StageRuntimeBootstrapPath { get; set; } = string.Empty;
    public string StageRuntimeFlagsPath { get; set; } = string.Empty;
    public int EnabledModCount { get; set; }
    public int AppliedOverlayCount { get; set; }
}

internal sealed class LauncherCliLaunch
{
    public int ProcessId { get; set; }
    public string LaunchToken { get; set; } = string.Empty;
    public DateTimeOffset StartedAtUtc { get; set; }
    public string LoaderPath { get; set; } = string.Empty;
    public string StartupCode { get; set; } = string.Empty;
    public string StartupMessage { get; set; } = string.Empty;
    public string? StartupLogPath { get; set; }
    public string? SavegamesRootPath { get; set; }
    public bool SavegamesUsesDirectoryMirror { get; set; }
    public LauncherCliMultiplayerSession? MultiplayerSession { get; set; }
}

internal sealed class LauncherCliMultiplayerSession
{
    public string LaunchToken { get; set; } = string.Empty;
    public bool Enabled { get; set; }
    public bool IsHost { get; set; }
    public string Phase { get; set; } = string.Empty;
    public string GamePhase { get; set; } = string.Empty;
    public uint AppId { get; set; }
    public ulong LobbyId { get; set; }
    public ulong HostSteamId { get; set; }
    public ulong LocalSteamId { get; set; }
    public string PersonaName { get; set; } = string.Empty;
    public string Privacy { get; set; } = string.Empty;
    public int ProtocolVersion { get; set; }
    public string ManifestSha256 { get; set; } = string.Empty;
    public List<ulong> FriendSteamIds { get; set; } = [];
    public uint MaxParticipants { get; set; }
    public uint AuthenticatedPeerCount { get; set; }
    public bool OverlayEnabled { get; set; }
    public bool InviteDialogOpened { get; set; }
    public bool RouteRelayed { get; set; }
    public int RoutePingMs { get; set; }
    public List<LauncherCliLobbyMember> Members { get; set; } = [];
    public string StatusText { get; set; } = string.Empty;
    public string ErrorText { get; set; } = string.Empty;
}

internal sealed class LauncherCliLobbyMember
{
    public ulong SteamId { get; set; }
    public string Name { get; set; } = string.Empty;
    public bool IsHost { get; set; }
    public bool IsLocal { get; set; }
}

internal sealed class LauncherCliModStateChange
{
    public string ModId { get; set; } = string.Empty;
    public bool Enabled { get; set; }
    public string StatePath { get; set; } = string.Empty;
}
