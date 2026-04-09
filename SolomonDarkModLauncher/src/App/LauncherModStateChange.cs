namespace SolomonDarkModLauncher.App;

internal sealed record LauncherModStateChange(
    string ModId,
    bool Enabled,
    string StatePath);
