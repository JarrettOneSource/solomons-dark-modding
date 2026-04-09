using System.Text;
using SolomonDarkModLauncher.Target;

namespace SolomonDarkModLauncher.Steam;

internal static class SteamBootstrapMaterializer
{
    public static SteamStageBootstrapResult Materialize(LauncherConfiguration configuration)
    {
        if (!configuration.Steam.Enabled)
        {
            return new SteamStageBootstrapResult(
                false,
                configuration.Steam.AppId,
                null,
                null,
                null,
                false);
        }

        var stageRootPath = configuration.Workspace.StageRootPath;
        Directory.CreateDirectory(stageRootPath);

        var stageAppIdPath = Path.Combine(stageRootPath, SteamBootstrapConfiguration.AppIdFileName);
        File.WriteAllText(stageAppIdPath, configuration.Steam.AppId + Environment.NewLine, new UTF8Encoding(false));

        var stageApiDllPath = Path.Combine(stageRootPath, SteamBootstrapConfiguration.ApiDllFileName);
        string? steamApiSourcePath = null;

        if (File.Exists(stageApiDllPath))
        {
            steamApiSourcePath = stageApiDllPath;
        }
        else
        {
            steamApiSourcePath = ResolveSteamApiSourcePath(configuration);
            if (!string.IsNullOrWhiteSpace(steamApiSourcePath))
            {
                Directory.CreateDirectory(Path.GetDirectoryName(stageApiDllPath)!);
                File.Copy(steamApiSourcePath, stageApiDllPath, overwrite: true);
            }
        }

        return new SteamStageBootstrapResult(
            true,
            configuration.Steam.AppId,
            stageAppIdPath,
            File.Exists(stageApiDllPath) ? stageApiDllPath : null,
            steamApiSourcePath,
            File.Exists(stageApiDllPath));
    }

    private static string? ResolveSteamApiSourcePath(LauncherConfiguration configuration)
    {
        foreach (var candidate in EnumerateSteamApiCandidates(configuration))
        {
            if (string.IsNullOrWhiteSpace(candidate))
            {
                continue;
            }

            var normalizedPath = Path.GetFullPath(candidate);
            if (File.Exists(normalizedPath))
            {
                return normalizedPath;
            }
        }

        return null;
    }

    private static IEnumerable<string?> EnumerateSteamApiCandidates(LauncherConfiguration configuration)
    {
        yield return configuration.Steam.ApiDllOverridePath;
        yield return Path.Combine(AppContext.BaseDirectory, "assets", "steam", "win32", SteamBootstrapConfiguration.ApiDllFileName);
        yield return Path.Combine(configuration.Workspace.RuntimeRootPath, "steam", "win32", SteamBootstrapConfiguration.ApiDllFileName);
    }
}
