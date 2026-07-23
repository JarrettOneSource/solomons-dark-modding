using System.Diagnostics;

namespace SolomonDarkModLauncher.UI.Infrastructure;

internal static class SteamShortcutChildEnvironment
{
    private static readonly string[] ShortcutVariables =
    {
        "SteamAppId",
        "SteamGameId",
        "SteamOverlayGameId",
        "SteamClientLaunch",
        "SteamEnv",
        "SteamPath"
    };

    public static void RemoveFrom(ProcessStartInfo startInfo)
    {
        foreach (var variableName in ShortcutVariables)
        {
            startInfo.Environment.Remove(variableName);
        }
    }
}
