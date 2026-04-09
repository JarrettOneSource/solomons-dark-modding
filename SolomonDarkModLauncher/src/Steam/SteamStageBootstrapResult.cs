namespace SolomonDarkModLauncher.Steam;

internal sealed record SteamStageBootstrapResult(
    bool Enabled,
    string AppId,
    string? StageAppIdPath,
    string? StageApiDllPath,
    string? SteamApiSourcePath,
    bool ReadyForInitialization);
