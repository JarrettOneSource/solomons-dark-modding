using SolomonDarkModLauncher.Commands;
using SolomonDarkModLauncher.Launch;
using SolomonDarkModLauncher.Manager;
using SolomonDarkModLauncher.Mods;
using SolomonDarkModLauncher.Staging;
using SolomonDarkModLauncher.Steam;
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
        WebsiteModUpdateResult? modUpdate = null;
        if (command.Mode is LauncherMode.ListMods or LauncherMode.Stage or LauncherMode.Launch)
        {
            modUpdate = WebsiteModUpdater.UpdateAsync(
                    configuration,
                    catalog,
                    command.LobbyHost.DirectoryBaseUrl)
                .GetAwaiter()
                .GetResult();
            if (modUpdate.UpdatedModCount > 0)
            {
                catalog = manager.LoadCatalog();
            }
        }

        LobbyModSyncResult? lobbyModSync = null;
        if (command.Mode == LauncherMode.Launch &&
            command.MultiplayerMode == MultiplayerLaunchMode.Join &&
            command.SteamLobbyId is { } lobbyId)
        {
            lobbyModSync = LobbyModSynchronizer.SynchronizeAsync(
                    configuration,
                    catalog,
                    lobbyId,
                    command.LobbyHost.DirectoryBaseUrl,
                    command.LobbyTicket)
                .GetAwaiter()
                .GetResult();
            catalog = lobbyModSync.Catalog;
        }

        return command.Mode switch
        {
            LauncherMode.ListMods => new LauncherCommandExecution(
                command,
                configuration,
                catalog,
                modUpdate),
            LauncherMode.Stage => ExecuteStage(command, configuration, catalog, modUpdate),
            LauncherMode.Launch => ExecuteLaunch(
                command,
                configuration,
                catalog,
                modUpdate,
                lobbyModSync),
            LauncherMode.EnableMod => ExecuteSetEnabled(command, configuration, manager, enabled: true),
            LauncherMode.DisableMod => ExecuteSetEnabled(command, configuration, manager, enabled: false),
            _ => throw new InvalidOperationException($"Unsupported mode: {command.Mode}")
        };
    }

    private static LauncherCommandExecution ExecuteStage(
        LauncherCommand command,
        LauncherConfiguration configuration,
        ModCatalog catalog,
        WebsiteModUpdateResult? modUpdate)
    {
        var stageResult = StageBuilder.Build(configuration, catalog);
        return new LauncherCommandExecution(
            command,
            configuration,
            catalog,
            modUpdate,
            StageResult: stageResult);
    }

    private static LauncherCommandExecution ExecuteLaunch(
        LauncherCommand command,
        LauncherConfiguration configuration,
        ModCatalog catalog,
        WebsiteModUpdateResult? modUpdate,
        LobbyModSyncResult? lobbyModSync)
    {
        var stageResult = StageBuilder.Build(configuration, catalog);
        var multiplayer = MultiplayerLaunchOptions.Create(
            command.MultiplayerMode,
            command.SteamLobbyId,
            command.InviteSteamId,
            command.MultiplayerMaxParticipants,
            command.OpenSteamInviteDialog,
            command.LobbyHost);
        if (multiplayer.Mode is MultiplayerLaunchMode.Host or MultiplayerLaunchMode.Join)
        {
            if (!stageResult.SteamBootstrap.ReadyForInitialization)
            {
                throw new InvalidOperationException(
                    "Steam multiplayer requires an x86 steam_api.dll. Install the Steamworks SDK runtime, " +
                    "place it under assets/steam/win32, or pass --steam-api-dll <path>.");
            }
            SteamLaunchPreflight.EnsureAvailable(stageResult.SteamBootstrap);
        }
        var launchedGame = StagedGameLauncher.Launch(
            stageResult,
            configuration,
            command.TemporaryProfile,
            multiplayer,
            command.SavegamesRootOverride);
        return new LauncherCommandExecution(
            command,
            configuration,
            catalog,
            modUpdate,
            LobbyModSync: lobbyModSync,
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
