namespace SolomonDarkModLauncher.Launch;

internal sealed record InjectedGame(
    int ProcessId,
    string LoaderPath,
    LoaderStartupStatus StartupStatus);
