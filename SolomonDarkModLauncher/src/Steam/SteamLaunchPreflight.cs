namespace SolomonDarkModLauncher.Steam;

internal static class SteamLaunchPreflight
{
    public static void EnsureAvailable(SteamStageBootstrapResult bootstrap)
    {
        var steamApiPath = bootstrap.StageApiDllPath;
        if (!bootstrap.ReadyForInitialization || string.IsNullOrWhiteSpace(steamApiPath))
        {
            throw new InvalidOperationException(
                "Steam multiplayer requires the packaged x86 steam_api.dll.");
        }

        try
        {
            using var session = new SteamManualDispatchSession(steamApiPath, bootstrap.AppId);
        }
        catch (Exception exception) when (
            exception is InvalidOperationException or
                         DllNotFoundException or
                         BadImageFormatException or
                         EntryPointNotFoundException)
        {
            throw new InvalidOperationException(
                "Steam is not ready. Open Steam, sign in, and wait until Steam is online. " +
                "Run Steam and this launcher with the same administrator setting. Then try again.",
                exception);
        }
    }
}
