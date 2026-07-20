using System.Security.Cryptography;

namespace SolomonDarkModLauncher.Target;

internal sealed class GameInstallation
{
    public const string LegacyVersionName = "Solomon Dark 0.72.5";
    public const string DefaultExecutableName = "SolomonDark.exe";
    public const string SupportedExecutableSha256 =
        "03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3";

    public required string InstallDirectory { get; init; }
    public required string ExecutableName { get; init; }

    public static GameInstallation Open(string? installDirectoryOverride, string workspaceRootPath)
    {
        var installDirectory = NormalizeInstallDirectory(
            installDirectoryOverride ?? ResolveDefaultInstallDirectory(workspaceRootPath));

        if (!Directory.Exists(installDirectory))
        {
            throw new DirectoryNotFoundException(
                $"{LegacyVersionName} folder not found: {installDirectory}. " +
                "Select the folder that contains SolomonDark.exe.");
        }

        var executablePath = Path.Combine(installDirectory, DefaultExecutableName);
        if (!File.Exists(executablePath))
        {
            var remakeExecutablePath = Path.Combine(installDirectory, "SB.exe");
            if (File.Exists(remakeExecutablePath))
            {
                throw new InvalidOperationException(
                    "The selected folder has the current Solomon's Boneyard remake (SB.exe). " +
                    $"Select the legacy {LegacyVersionName} folder that contains SolomonDark.exe.");
            }

            throw new FileNotFoundException(
                $"{LegacyVersionName} executable not found. Select the folder that contains SolomonDark.exe.",
                executablePath);
        }

        var executableSha256 = HashFile(executablePath);
        if (!string.Equals(
                executableSha256,
                SupportedExecutableSha256,
                StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException(
                $"This beta supports only {LegacyVersionName}. " +
                $"The selected SolomonDark.exe has SHA-256 {executableSha256}. " +
                $"The necessary SHA-256 value is {SupportedExecutableSha256}.");
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

        return Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86),
            LegacyVersionName);
    }

    private static string HashFile(string path)
    {
        using var stream = File.OpenRead(path);
        return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
    }

    private static bool LooksLikeWindowsDrivePath(string value)
    {
        return value.Length >= 3 &&
               char.IsLetter(value[0]) &&
               value[1] == ':' &&
               (value[2] == '\\' || value[2] == '/');
    }
}
