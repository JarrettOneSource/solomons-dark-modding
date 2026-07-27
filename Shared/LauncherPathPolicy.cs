using System.IO;

namespace SolomonDarkModding.IO;

internal static class LauncherPathPolicy
{
    public const string ApplicationDataDirectoryName = "SolomonDarkMultiplayerBeta";
    public const string TestApplicationDataRootEnvironmentVariable =
        "SDMOD_TEST_APPLICATION_DATA_ROOT";

    public static string? TryGetKnownFolder(
        Environment.SpecialFolder folder,
        Action<string>? rejectedPath = null)
    {
        try
        {
            var path = Environment.GetFolderPath(
                folder,
                Environment.SpecialFolderOption.DoNotVerify);
            var normalized = NormalizeAbsolutePath(path);
            if (normalized is null || !IsDesktopPath(normalized))
            {
                return normalized;
            }

            rejectedPath?.Invoke(
                $"Known folder resolved through Desktop; using a safe fallback: {normalized}");
            return null;
        }
        catch (Exception exception) when (
            exception is ArgumentException or
            NotSupportedException or
            System.Security.SecurityException)
        {
            return null;
        }
    }

    public static string ResolveApplicationDataRoot(
        Action<string>? rejectedPath = null,
        string? localApplicationDataPath = null,
        string? temporaryPath = null,
        Func<string, bool>? canWriteDirectory = null,
        string applicationDirectoryName = ApplicationDataDirectoryName)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(applicationDirectoryName);
        if (Path.GetFileName(applicationDirectoryName) != applicationDirectoryName)
        {
            throw new ArgumentException(
                "Application data directory name must be one path segment.",
                nameof(applicationDirectoryName));
        }

        canWriteDirectory ??= CanWriteDirectory;
        if (localApplicationDataPath is null)
        {
            var testRoot = Environment.GetEnvironmentVariable(
                TestApplicationDataRootEnvironmentVariable);
            if (!string.IsNullOrWhiteSpace(testRoot))
            {
                var normalizedTestRoot =
                    NormalizeAbsolutePath(testRoot);
                if (normalizedTestRoot is null)
                {
                    throw new IOException(
                        "The isolated launcher data root is not an absolute path.");
                }
                var isolatedApplicationRoot = Path.Combine(
                    normalizedTestRoot,
                    applicationDirectoryName);
                if (IsDesktopPath(isolatedApplicationRoot) ||
                    !canWriteDirectory(isolatedApplicationRoot))
                {
                    throw new IOException(
                        "The isolated launcher data root is not writable.");
                }
                return isolatedApplicationRoot;
            }
        }
        var candidates = new[]
        {
            localApplicationDataPath ??
                TryGetKnownFolder(
                    Environment.SpecialFolder.LocalApplicationData,
                    rejectedPath),
            temporaryPath ?? TryGetTemporaryPath(),
            AppContext.BaseDirectory
        };

        foreach (var candidate in candidates)
        {
            var normalizedRoot = NormalizeAbsolutePath(candidate);
            if (normalizedRoot is null)
            {
                continue;
            }

            var applicationRoot = Path.Combine(
                normalizedRoot,
                applicationDirectoryName);
            if (IsDesktopPath(applicationRoot))
            {
                rejectedPath?.Invoke(
                    $"Desktop paths are not used; using a safe fallback: {applicationRoot}");
                continue;
            }

            if (canWriteDirectory(applicationRoot))
            {
                return applicationRoot;
            }

            rejectedPath?.Invoke(
                $"Launcher data directory is unavailable: {applicationRoot}");
        }

        throw new IOException(
            "The launcher could not find a writable application-data directory.");
    }

    public static string? ResolveReadableDirectory(
        IEnumerable<string?> candidates,
        Action<string>? rejectedPath = null,
        Func<string, bool>? canReadDirectory = null)
    {
        canReadDirectory ??= CanReadDirectory;
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var candidate in candidates)
        {
            var normalized = NormalizeAbsolutePath(candidate);
            if (normalized is null || !seen.Add(normalized))
            {
                continue;
            }

            if (IsDesktopPath(normalized))
            {
                rejectedPath?.Invoke(
                    $"Desktop paths are not used; using a safe fallback: {normalized}");
                continue;
            }

            if (canReadDirectory(normalized))
            {
                return normalized;
            }

            rejectedPath?.Invoke(
                $"Folder is unavailable; using a safe fallback: {normalized}");
        }

        return null;
    }

    public static bool IsDesktopPath(string path)
    {
        var normalized = NormalizeAbsolutePath(path);
        return normalized is not null &&
               normalized
                   .Split(
                       [Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar],
                       StringSplitOptions.RemoveEmptyEntries)
                   .Any(part => string.Equals(
                       part,
                       "Desktop",
                       StringComparison.OrdinalIgnoreCase));
    }

    internal static string? NormalizeAbsolutePath(string? path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return null;
        }

        try
        {
            var normalized = Path.GetFullPath(path.Trim(), AppContext.BaseDirectory);
            return Path.IsPathFullyQualified(normalized)
                ? Path.TrimEndingDirectorySeparator(normalized)
                : null;
        }
        catch (Exception exception) when (
            exception is ArgumentException or
            NotSupportedException or
            PathTooLongException)
        {
            return null;
        }
    }

    private static string? TryGetTemporaryPath()
    {
        try
        {
            return NormalizeAbsolutePath(Path.GetTempPath());
        }
        catch (Exception exception) when (
            exception is IOException or
            System.Security.SecurityException)
        {
            return null;
        }
    }

    private static bool CanReadDirectory(string path)
    {
        try
        {
            if (!Directory.Exists(path))
            {
                return false;
            }

            using var enumerator = Directory
                .EnumerateFileSystemEntries(path)
                .GetEnumerator();
            _ = enumerator.MoveNext();
            return true;
        }
        catch (Exception exception) when (
            exception is IOException or
            UnauthorizedAccessException or
            System.Security.SecurityException)
        {
            return false;
        }
    }

    private static bool CanWriteDirectory(string path)
    {
        try
        {
            Directory.CreateDirectory(path);
            var probePath = Path.Combine(
                path,
                $".launcher-write-probe-{Guid.NewGuid():N}.tmp");
            using var probe = new FileStream(
                probePath,
                FileMode.CreateNew,
                FileAccess.Write,
                FileShare.None,
                1,
                FileOptions.DeleteOnClose);
            return true;
        }
        catch (Exception exception) when (
            exception is IOException or
            UnauthorizedAccessException or
            System.Security.SecurityException)
        {
            return false;
        }
    }
}
