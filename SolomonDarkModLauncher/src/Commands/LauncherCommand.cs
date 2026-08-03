using SolomonDarkModLauncher.Launch;

namespace SolomonDarkModLauncher.Commands;

internal sealed record LauncherCommand(
    LauncherMode Mode,
    bool ShowHelp,
    bool JsonOutput,
    bool ProgressJson,
    string? InstanceName,
    string? GameDirectoryOverride,
    string? ModsRootOverride,
    string? RuntimeRootOverride,
    string? StageRootOverride,
    string? SavegamesRootOverride,
    string? TargetModId,
    string? RuntimeProfileOverride,
    IReadOnlyList<string> RuntimeFlagOverrides,
    bool TemporaryProfile,
    bool FreshInstall,
    bool ShowStockTutorial,
    bool DisableAudio,
    bool Headless,
    string? SteamAppIdOverride,
    string? SteamApiDllOverride,
    MultiplayerLaunchMode MultiplayerMode,
    ulong? SteamLobbyId,
    ulong? InviteSteamId,
    int MultiplayerMaxParticipants,
    bool OpenSteamInviteDialog,
    string? LobbyTicket,
    bool AllowHostModTransfer,
    LobbyHostOptions LobbyHost);
