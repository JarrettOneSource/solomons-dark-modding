namespace SolomonDarkModLauncher.Launch;

internal sealed record LaunchOptions(
    IReadOnlyDictionary<string, string>? EnvironmentOverrides = null,
    bool TemporaryProfile = false,
    string? ProfileRootPath = null,
    string? SavegamesRootPath = null);
