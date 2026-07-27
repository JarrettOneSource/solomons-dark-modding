using SolomonDarkModding.Versioning;
using SolomonDarkModLauncher.Infrastructure;

namespace SolomonDarkModLauncher.Mods;

internal static class ModCompatibility
{
    public static bool IsLoaderCompatible(
        ModManifest manifest,
        string? loaderVersion = null)
    {
        if (string.IsNullOrWhiteSpace(manifest.MinimumLoaderVersion))
        {
            return true;
        }

        var currentText = loaderVersion ?? LauncherVersionInfo.Informational;
        return SemanticVersion.TryParse(currentText, out var current) &&
               SemanticVersion.TryParse(manifest.MinimumLoaderVersion, out var minimum) &&
               current!.CompareTo(minimum) >= 0;
    }

    public static void EnsureLoaderCompatible(
        ModManifest manifest,
        string? loaderVersion = null)
    {
        if (IsLoaderCompatible(manifest, loaderVersion))
        {
            return;
        }

        throw new InvalidOperationException(
            $"{manifest.Name} requires Solomon Dark Mod Loader " +
            $"{manifest.MinimumLoaderVersion} or newer.");
    }
}
