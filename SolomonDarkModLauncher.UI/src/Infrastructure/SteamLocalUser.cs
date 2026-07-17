using Microsoft.Win32;

namespace SolomonDarkModLauncher.UI.Infrastructure;

internal static class SteamLocalUser
{
    private const ulong SteamId64Base = 76561197960265728;

    /// <summary>
    /// SteamID64 of the account signed into the running Steam client, read
    /// from the registry key Steam maintains; null when Steam is closed or
    /// logged out. Used as the lobby directory's viewerSteamId claim.
    /// </summary>
    public static string? GetActiveSteamId()
    {
        var value = Registry.GetValue(
            @"HKEY_CURRENT_USER\Software\Valve\Steam\ActiveProcess",
            "ActiveUser",
            null);
        return value is int accountId && accountId > 0
            ? (SteamId64Base + (uint)accountId).ToString()
            : null;
    }
}
