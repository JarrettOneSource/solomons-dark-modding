namespace SolomonDarkModLauncher.Commands;

internal sealed record LauncherCommand(
    LauncherMode Mode,
    bool ShowHelp,
    bool JsonOutput,
    string? InstanceName,
    string? GameDirectoryOverride,
    string? ModsRootOverride,
    string? RuntimeRootOverride,
    string? StageRootOverride,
    string? TargetModId,
    string? RuntimeProfileOverride,
    IReadOnlyList<string> RuntimeFlagOverrides,
    string? SteamAppIdOverride,
    string? SteamApiDllOverride);
