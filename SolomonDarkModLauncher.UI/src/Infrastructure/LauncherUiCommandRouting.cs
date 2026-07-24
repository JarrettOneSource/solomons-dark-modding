namespace SolomonDarkModLauncher.UI.Infrastructure;

internal static class LauncherUiCommandRouting
{
    public static bool LaunchesGame(LauncherUiCommandMode mode) =>
        mode is LauncherUiCommandMode.HostSteam or
            LauncherUiCommandMode.LaunchSteamJoin or
            LauncherUiCommandMode.LaunchSinglePlayer;

    public static string GetModeToken(LauncherUiCommandMode mode) =>
        mode switch
        {
            LauncherUiCommandMode.LaunchSinglePlayer => "launch",
            LauncherUiCommandMode.HostSteam => "launch",
            LauncherUiCommandMode.PrepareSteamJoin => "stage",
            LauncherUiCommandMode.LaunchSteamJoin => "launch",
            LauncherUiCommandMode.JoinPreview => "join-preview",
            LauncherUiCommandMode.Stage => "stage",
            LauncherUiCommandMode.ListMods => "list-mods",
            LauncherUiCommandMode.EnableMod => "enable-mod",
            LauncherUiCommandMode.DisableMod => "disable-mod",
            _ => throw new InvalidOperationException($"Unsupported mode: {mode}")
        };
}
