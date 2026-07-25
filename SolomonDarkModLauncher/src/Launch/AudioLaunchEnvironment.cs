namespace SolomonDarkModLauncher.Launch;

internal static class AudioLaunchEnvironment
{
    public const string DisableAudioVariable = "SDMOD_DISABLE_AUDIO";

    public static LaunchOptions Apply(
        LaunchOptions options,
        bool disableAudio)
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

        environment[DisableAudioVariable] =
            disableAudio ? "1" : string.Empty;
        return options with { EnvironmentOverrides = environment };
    }
}
