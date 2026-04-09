namespace SolomonDarkModLauncher.Launch;

internal sealed record LaunchOptions(
    IReadOnlyDictionary<string, string>? EnvironmentOverrides = null);
