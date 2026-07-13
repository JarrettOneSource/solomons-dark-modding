using System.Text;
using System.Reflection.PortableExecutable;
using Microsoft.Win32;
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

        if (IsX86SteamApiDll(stageApiDllPath))
        {
            steamApiSourcePath = stageApiDllPath;
        }
        else
        {
            if (File.Exists(stageApiDllPath))
            {
                File.Delete(stageApiDllPath);
            }
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
            if (IsX86SteamApiDll(normalizedPath))
            {
                return normalizedPath;
            }
            if (string.Equals(
                    normalizedPath,
                    configuration.Steam.ApiDllOverridePath,
                    StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidOperationException(
                    $"Steam API DLL override is not a valid x86 DLL: {normalizedPath}");
            }
        }

        return null;
    }

    private static IEnumerable<string?> EnumerateSteamApiCandidates(LauncherConfiguration configuration)
    {
        yield return configuration.Steam.ApiDllOverridePath;
        yield return Path.Combine(AppContext.BaseDirectory, "assets", "steam", "win32", SteamBootstrapConfiguration.ApiDllFileName);
        yield return Path.Combine(configuration.Workspace.RuntimeRootPath, "steam", "win32", SteamBootstrapConfiguration.ApiDllFileName);
        var sdkRoot = Environment.GetEnvironmentVariable("STEAMWORKS_SDK_PATH");
        if (!string.IsNullOrWhiteSpace(sdkRoot))
        {
            yield return Path.Combine(
                sdkRoot,
                "redistributable_bin",
                SteamBootstrapConfiguration.ApiDllFileName);
        }

        foreach (var steamRoot in EnumerateSteamInstallRoots())
        {
            // SteamVR installs Valve's current 32-bit flat Steamworks runtime and
            // is a useful local development source when the SDK redist is absent.
            yield return Path.Combine(
                steamRoot,
                "steamapps",
                "common",
                "SteamVR",
                "bin",
                "win32",
                SteamBootstrapConfiguration.ApiDllFileName);
        }
    }

    private static IEnumerable<string> EnumerateSteamInstallRoots()
    {
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var candidate in new[]
        {
            Environment.GetEnvironmentVariable("STEAM_PATH"),
            ReadRegistryString(RegistryHive.CurrentUser, RegistryView.Default, @"Software\Valve\Steam", "SteamPath"),
            ReadRegistryString(RegistryHive.LocalMachine, RegistryView.Registry32, @"Software\Valve\Steam", "InstallPath"),
            Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86),
                "Steam")
        })
        {
            if (string.IsNullOrWhiteSpace(candidate))
            {
                continue;
            }
            var normalized = Path.GetFullPath(candidate);
            if (Directory.Exists(normalized) && seen.Add(normalized))
            {
                yield return normalized;
            }
        }
    }

    private static string? ReadRegistryString(
        RegistryHive hive,
        RegistryView view,
        string subKey,
        string valueName)
    {
        try
        {
            using var baseKey = RegistryKey.OpenBaseKey(hive, view);
            using var key = baseKey.OpenSubKey(subKey);
            return key?.GetValue(valueName) as string;
        }
        catch (System.Security.SecurityException)
        {
            return null;
        }
        catch (UnauthorizedAccessException)
        {
            return null;
        }
    }

    private static bool IsX86SteamApiDll(string path)
    {
        if (!File.Exists(path))
        {
            return false;
        }
        try
        {
            using var stream = File.OpenRead(path);
            using var reader = new PEReader(stream);
            return reader.PEHeaders.CoffHeader.Machine == Machine.I386 &&
                   (reader.PEHeaders.CoffHeader.Characteristics & Characteristics.Dll) != 0;
        }
        catch (BadImageFormatException)
        {
            return false;
        }
        catch (IOException)
        {
            return false;
        }
    }
}
