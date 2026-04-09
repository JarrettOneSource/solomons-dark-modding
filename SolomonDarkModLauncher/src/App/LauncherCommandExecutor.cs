using SolomonDarkModLauncher.Commands;
using SolomonDarkModLauncher.Launch;
using SolomonDarkModLauncher.Manager;
using SolomonDarkModLauncher.Mods;
using SolomonDarkModLauncher.Staging;
using SolomonDarkModLauncher.Target;

namespace SolomonDarkModLauncher.App;

internal static class LauncherCommandExecutor
{
    public static LauncherCommandExecution Execute(LauncherCommand command)
    {
        var configuration = LauncherConfiguration.CreateDefault(
            AppContext.BaseDirectory,
            command.GameDirectoryOverride,
            command.ModsRootOverride,
            command.RuntimeRootOverride,
            command.StageRootOverride,
            command.InstanceName,
            command.RuntimeProfileOverride,
            command.RuntimeFlagOverrides,
            command.SteamAppIdOverride,
            command.SteamApiDllOverride);

        var manager = new ModManagerService(configuration);
        var catalog = manager.LoadCatalog();

        return command.Mode switch
        {
            LauncherMode.ListMods => new LauncherCommandExecution(command, configuration, catalog),
            LauncherMode.Stage => ExecuteStage(command, configuration, catalog),
            LauncherMode.Launch => ExecuteLaunch(command, configuration, catalog),
            LauncherMode.EnableMod => ExecuteSetEnabled(command, configuration, manager, enabled: true),
            LauncherMode.DisableMod => ExecuteSetEnabled(command, configuration, manager, enabled: false),
            _ => throw new InvalidOperationException($"Unsupported mode: {command.Mode}")
        };
    }

    private static LauncherCommandExecution ExecuteStage(
        LauncherCommand command,
        LauncherConfiguration configuration,
        ModCatalog catalog)
    {
        var stageResult = StageBuilder.Build(configuration, catalog);
        return new LauncherCommandExecution(command, configuration, catalog, StageResult: stageResult);
    }

    private static LauncherCommandExecution ExecuteLaunch(
        LauncherCommand command,
        LauncherConfiguration configuration,
        ModCatalog catalog)
    {
        var stageResult = StageBuilder.Build(configuration, catalog);
        var launchedGame = StagedGameLauncher.Launch(stageResult, configuration);
        return new LauncherCommandExecution(
            command,
            configuration,
            catalog,
            StageResult: stageResult,
            LaunchedGame: launchedGame);
    }

    private static LauncherCommandExecution ExecuteSetEnabled(
        LauncherCommand command,
        LauncherConfiguration configuration,
        ModManagerService manager,
        bool enabled)
    {
        if (string.IsNullOrWhiteSpace(command.TargetModId))
        {
            throw new InvalidOperationException("A mod id is required for this command.");
        }

        manager.SetEnabled(command.TargetModId, enabled);
        var catalog = manager.LoadCatalog();
        return new LauncherCommandExecution(
            command,
            configuration,
            catalog,
            ModStateChange: new LauncherModStateChange(command.TargetModId, enabled, manager.StatePath));
    }
}
