namespace SolomonDarkModLauncher.Target;

internal sealed class GameInstallation
{
    public const string DefaultInstallDirectory = @"D:\SteamLibrary\steamapps\common\Solomon Dark Hideous Retro Edition";
    public const string DefaultExecutableName = "SolomonDark.exe";

    public required string InstallDirectory { get; init; }
    public required string ExecutableName { get; init; }

    public static GameInstallation Open(string? installDirectoryOverride, string workspaceRootPath)
    {
        var installDirectory = NormalizeInstallDirectory(
            installDirectoryOverride ?? ResolveDefaultInstallDirectory(workspaceRootPath));

        if (!Directory.Exists(installDirectory))
        {
            throw new DirectoryNotFoundException($"Game directory not found: {installDirectory}");
        }

        var executablePath = Path.Combine(installDirectory, DefaultExecutableName);
        if (!File.Exists(executablePath))
        {
            throw new FileNotFoundException("Game executable not found.", executablePath);
        }

        return new GameInstallation
        {
            InstallDirectory = installDirectory,
            ExecutableName = DefaultExecutableName
        };
    }

    internal static string NormalizeInstallDirectory(string installDirectory)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(installDirectory);

        if (OperatingSystem.IsWindows())
        {
            return Path.GetFullPath(installDirectory);
        }

        if (LooksLikeWindowsDrivePath(installDirectory))
        {
            var driveLetter = char.ToLowerInvariant(installDirectory[0]);
            var relativePath = installDirectory[2..]
                .TrimStart('\\', '/')
                .Replace('\\', '/');
            return Path.GetFullPath($"/mnt/{driveLetter}/{relativePath}");
        }

        return Path.GetFullPath(installDirectory);
    }

    private static string ResolveDefaultInstallDirectory(string workspaceRootPath)
    {
        var localReplicaPath = NormalizeInstallDirectory(Path.Combine(workspaceRootPath, "..", "SolomonDarkAbandonware"));
        var localExecutablePath = Path.Combine(localReplicaPath, DefaultExecutableName);
        if (Directory.Exists(localReplicaPath) && File.Exists(localExecutablePath))
        {
            return localReplicaPath;
        }

        return DefaultInstallDirectory;
    }

    private static bool LooksLikeWindowsDrivePath(string value)
    {
        return value.Length >= 3 &&
               char.IsLetter(value[0]) &&
               value[1] == ':' &&
               (value[2] == '\\' || value[2] == '/');
    }
}
