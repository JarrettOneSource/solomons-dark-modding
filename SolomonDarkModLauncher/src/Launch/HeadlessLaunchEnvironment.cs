namespace SolomonDarkModLauncher.Launch;

internal static class HeadlessLaunchEnvironment
{
    public const string EnabledVariable = "SDMOD_HEADLESS";

    public static LaunchOptions Apply(
        LaunchOptions options,
        bool enabled)
    {
        var environment = new Dictionary<string, string>(
            StringComparer.OrdinalIgnoreCase);
        if (options.EnvironmentOverrides is not null)
        {
            foreach (var pair in options.EnvironmentOverrides)
            {
                environment[pair.Key] = pair.Value;
            }
        }

        environment[EnabledVariable] = enabled ? "1" : string.Empty;
        return options with { EnvironmentOverrides = environment };
    }
}
