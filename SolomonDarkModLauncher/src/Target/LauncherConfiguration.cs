using SolomonDarkModLauncher.Steam;
using SolomonDarkModLauncher.Staging;
using SolomonDarkModLauncher.Workspace;

namespace SolomonDarkModLauncher.Target;

internal sealed class LauncherConfiguration
{
    public required GameInstallation Game { get; init; }
    public required WorkspacePaths Workspace { get; init; }
    public required RuntimeStageOptions Runtime { get; init; }
    public required SteamBootstrapConfiguration Steam { get; init; }

    public static LauncherConfiguration CreateDefault(
        string launcherBaseDirectory,
        string? gameDirectoryOverride,
        string? modsRootOverride,
        string? runtimeRootOverride,
        string? stageRootOverride,
        string? instanceName,
        string? runtimeProfileOverride,
        IReadOnlyList<string>? runtimeFlagOverrides,
        string? steamAppIdOverride,
        string? steamApiDllOverride)
    {
        var workspaceRootPath = WorkspaceLocator.FindRootPath(launcherBaseDirectory);
        var workspace = WorkspacePaths.Create(
            workspaceRootPath,
            modsRootOverride,
            runtimeRootOverride,
            stageRootOverride,
            instanceName);
        var game = GameInstallation.Open(gameDirectoryOverride, workspaceRootPath);
        var runtime = RuntimeStageOptions.Create(runtimeProfileOverride, runtimeFlagOverrides);
        var steam = SteamBootstrapConfiguration.CreateDefault(
            steamAppIdOverride,
            steamApiDllOverride);

        return new LauncherConfiguration
        {
            Game = game,
            Workspace = workspace,
            Runtime = runtime,
            Steam = steam
        };
    }
}
