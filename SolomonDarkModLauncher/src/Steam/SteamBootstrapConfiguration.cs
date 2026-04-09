namespace SolomonDarkModLauncher.Steam;

internal sealed class SteamBootstrapConfiguration
{
    public const string DefaultAppId = "3362180";
    public const string AppIdFileName = "steam_appid.txt";
    public const string ApiDllFileName = "steam_api.dll";
    public const string EnableEnvironmentVariable = "SDMOD_STEAM_BOOTSTRAP";
    public const string AppIdEnvironmentVariable = "SDMOD_STEAM_APP_ID";
    public const string AppIdPathEnvironmentVariable = "SDMOD_STEAM_APP_ID_PATH";
    public const string ApiDllPathEnvironmentVariable = "SDMOD_STEAM_API_DLL";
    public const string AllowRestartEnvironmentVariable = "SDMOD_STEAM_ALLOW_RESTART";

    public required bool Enabled { get; init; }
    public required string AppId { get; init; }
    public required bool AllowRestartIfNecessary { get; init; }
    public string? ApiDllOverridePath { get; init; }

    public static SteamBootstrapConfiguration CreateDefault(
        string? appIdOverride,
        string? apiDllOverridePath)
    {
        string? normalizedApiDllOverride = null;
        if (!string.IsNullOrWhiteSpace(apiDllOverridePath))
        {
            normalizedApiDllOverride = Path.GetFullPath(apiDllOverridePath);
            if (!File.Exists(normalizedApiDllOverride))
            {
                throw new FileNotFoundException("Steam API DLL override was not found.", normalizedApiDllOverride);
            }
        }

        return new SteamBootstrapConfiguration
        {
            Enabled = true,
            AppId = NormalizeAppId(appIdOverride ?? DefaultAppId),
            AllowRestartIfNecessary = false,
            ApiDllOverridePath = normalizedApiDllOverride
        };
    }

    private static string NormalizeAppId(string value)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(value);

        var trimmed = value.Trim();
        if (!trimmed.All(char.IsDigit))
        {
            throw new InvalidOperationException($"Steam AppID must be numeric: {value}");
        }

        return trimmed;
    }
}
