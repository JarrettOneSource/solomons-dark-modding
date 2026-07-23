namespace SolomonDarkModLauncher.Launch;

internal sealed record InjectedGame(
    int ProcessId,
    string LaunchToken,
    DateTimeOffset StartedAtUtc,
    string LoaderPath,
    LoaderStartupStatus StartupStatus,
    MultiplayerSessionStatus? MultiplayerSessionStatus,
    string? SavegamesRootPath,
    bool SavegamesUsesDirectoryMirror);
