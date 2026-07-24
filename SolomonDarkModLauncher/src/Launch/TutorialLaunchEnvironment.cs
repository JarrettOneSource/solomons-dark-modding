namespace SolomonDarkModLauncher.Launch;

internal static class TutorialLaunchEnvironment
{
    public const string SkipFreshSaveTutorialVariable =
        "SDMOD_SKIP_FRESH_SAVE_TUTORIAL";

    public static LaunchOptions Apply(
        LaunchOptions options,
        bool showStockTutorial)
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

        environment[SkipFreshSaveTutorialVariable] =
            showStockTutorial ? string.Empty : "1";
        return options with { EnvironmentOverrides = environment };
    }
}
