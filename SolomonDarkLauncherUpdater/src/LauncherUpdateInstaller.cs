using System.IO.Compression;
using System.Text.Json;
using SolomonDarkModding.Distribution;

namespace SolomonDarkLauncherUpdater;

internal static class LauncherUpdateInstaller
{
    private const long MaximumExpandedBytes = 1024L * 1024L * 1024L;
    private const int MaximumEntries = 20_000;

    public static void Install(string archivePath, string targetPath)
    {
        archivePath = Path.GetFullPath(archivePath);
        targetPath = Path.TrimEndingDirectorySeparator(Path.GetFullPath(targetPath));
        if (!File.Exists(archivePath))
        {
            throw new FileNotFoundException("The downloaded launcher update is missing.", archivePath);
        }
        if (!Directory.Exists(targetPath))
        {
            throw new DirectoryNotFoundException($"The launcher folder is missing: {targetPath}");
        }

        var parentPath = Directory.GetParent(targetPath)?.FullName;
        if (parentPath is null)
        {
            throw new InvalidOperationException("The launcher cannot update a drive root.");
        }

        var transactionId = Guid.NewGuid().ToString("N");
        var stagingPath = Path.Combine(parentPath, $".solomon-dark-update-new-{transactionId}");
        var backupPath = Path.Combine(parentPath, $".solomon-dark-update-backup-{transactionId}");
        var targetMoved = false;

        try
        {
            var extractedPackagePath = ExtractPackage(archivePath, stagingPath);
            ValidateDistribution(extractedPackagePath);
            var oldOwnedFiles = ReadOwnedFiles(targetPath);

            Directory.Move(targetPath, backupPath);
            targetMoved = true;
            Directory.Move(extractedPackagePath, targetPath);
            PreserveUserFiles(backupPath, targetPath, oldOwnedFiles);

            try
            {
                Directory.Delete(backupPath, recursive: true);
            }
            catch (IOException)
            {
            }
            catch (UnauthorizedAccessException)
            {
            }
        }
        catch
        {
            if (targetMoved && Directory.Exists(backupPath))
            {
                if (Directory.Exists(targetPath))
                {
                    Directory.Delete(targetPath, recursive: true);
                }
                Directory.Move(backupPath, targetPath);
            }
            throw;
        }
        finally
        {
            if (Directory.Exists(stagingPath))
            {
                Directory.Delete(stagingPath, recursive: true);
            }
        }
    }

    public static string ResolvePackagedPath(string rootPath, string relativePath)
    {
        rootPath = Path.TrimEndingDirectorySeparator(Path.GetFullPath(rootPath));
        var normalized = NormalizeRelativePath(relativePath);
        var fullPath = Path.GetFullPath(
            Path.Combine(rootPath, normalized.Replace('/', Path.DirectorySeparatorChar)));
        var rootPrefix = rootPath + Path.DirectorySeparatorChar;
        if (!fullPath.StartsWith(rootPrefix, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException($"Package path escapes its root: {relativePath}");
        }
        return fullPath;
    }

    private static string ExtractPackage(string archivePath, string stagingPath)
    {
        Directory.CreateDirectory(stagingPath);
        using var archive = ZipFile.OpenRead(archivePath);
        if (archive.Entries.Count > MaximumEntries)
        {
            throw new InvalidDataException("The launcher update contains too many files.");
        }

        string? packageDirectoryName = null;
        long expandedBytes = 0;
        var extractedPaths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var entry in archive.Entries)
        {
            var normalized = NormalizeArchivePath(entry.FullName);
            var parts = normalized.Split('/');
            packageDirectoryName ??= parts[0];
            if (!string.Equals(packageDirectoryName, parts[0], StringComparison.Ordinal))
            {
                throw new InvalidDataException("The launcher update must contain one top-level folder.");
            }
            if (IsSymbolicLink(entry))
            {
                throw new InvalidDataException($"The launcher update contains a link: {entry.FullName}");
            }

            var destinationPath = ResolvePackagedPath(stagingPath, normalized);
            var isDirectory = entry.FullName.EndsWith('/') || entry.FullName.EndsWith('\\');
            if (isDirectory)
            {
                Directory.CreateDirectory(destinationPath);
                continue;
            }
            if (parts.Length < 2)
            {
                throw new InvalidDataException("The launcher update has a file outside its package folder.");
            }
            if (!extractedPaths.Add(destinationPath))
            {
                throw new InvalidDataException($"The launcher update repeats a file: {entry.FullName}");
            }

            expandedBytes = checked(expandedBytes + entry.Length);
            if (expandedBytes > MaximumExpandedBytes)
            {
                throw new InvalidDataException("The launcher update is too large when extracted.");
            }

            Directory.CreateDirectory(Path.GetDirectoryName(destinationPath)!);
            using var input = entry.Open();
            using var output = new FileStream(
                destinationPath,
                FileMode.CreateNew,
                FileAccess.Write,
                FileShare.None);
            input.CopyTo(output);
        }

        if (packageDirectoryName is null)
        {
            throw new InvalidDataException("The launcher update is empty.");
        }
        return ResolvePackagedPath(stagingPath, packageDirectoryName);
    }

    private static void ValidateDistribution(string packagePath)
    {
        foreach (var requiredFile in new[]
                 {
                     DistributionLayout.DesktopLauncherExecutableName,
                     DistributionLayout.UpdaterExecutableName,
                     DistributionLayout.PortableRootMarkerFileName,
                     DistributionLayout.DistributionFilesManifestFileName
                 })
        {
            if (!File.Exists(ResolvePackagedPath(packagePath, requiredFile)))
            {
                throw new InvalidDataException($"The launcher update is missing {requiredFile}.");
            }
        }

        var declaredFiles = ReadOwnedFiles(packagePath);
        var actualFiles = Directory.EnumerateFiles(packagePath, "*", SearchOption.AllDirectories)
            .Select(path => Path.GetRelativePath(packagePath, path).Replace('\\', '/'))
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        if (!declaredFiles.SetEquals(actualFiles))
        {
            throw new InvalidDataException("The launcher update file list does not match its contents.");
        }
    }

    private static HashSet<string> ReadOwnedFiles(string rootPath)
    {
        var manifestPath = ResolvePackagedPath(
            rootPath,
            DistributionLayout.DistributionFilesManifestFileName);
        if (!File.Exists(manifestPath))
        {
            throw new InvalidDataException(
                $"The launcher folder is missing {DistributionLayout.DistributionFilesManifestFileName}.");
        }

        using var document = JsonDocument.Parse(File.ReadAllBytes(manifestPath));
        var root = document.RootElement;
        if (!root.TryGetProperty("schemaVersion", out var schemaVersion) ||
            schemaVersion.GetInt32() != 1 ||
            !root.TryGetProperty("files", out var files) ||
            files.ValueKind != JsonValueKind.Array)
        {
            throw new InvalidDataException("The launcher file list is invalid.");
        }

        var result = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var element in files.EnumerateArray())
        {
            if (element.ValueKind != JsonValueKind.String)
            {
                throw new InvalidDataException("The launcher file list contains a non-text path.");
            }
            var relativePath = NormalizeRelativePath(element.GetString()!);
            if (!result.Add(relativePath))
            {
                throw new InvalidDataException($"The launcher file list repeats {relativePath}.");
            }
        }

        if (!result.Contains(DistributionLayout.DistributionFilesManifestFileName))
        {
            throw new InvalidDataException("The launcher file list does not include itself.");
        }
        return result;
    }

    private static void PreserveUserFiles(
        string backupPath,
        string targetPath,
        HashSet<string> oldOwnedFiles)
    {
        foreach (var sourcePath in Directory.EnumerateFiles(
                     backupPath,
                     "*",
                     SearchOption.AllDirectories))
        {
            var relativePath = Path.GetRelativePath(backupPath, sourcePath).Replace('\\', '/');
            if (oldOwnedFiles.Contains(relativePath))
            {
                continue;
            }

            var destinationPath = ResolvePackagedPath(targetPath, relativePath);
            if (File.Exists(destinationPath) || Directory.Exists(destinationPath))
            {
                continue;
            }

            var destinationDirectory = Path.GetDirectoryName(destinationPath)!;
            if (File.Exists(destinationDirectory))
            {
                continue;
            }
            Directory.CreateDirectory(destinationDirectory);
            File.Copy(sourcePath, destinationPath);
        }
    }

    private static string NormalizeArchivePath(string value)
    {
        var normalized = value.Replace('\\', '/').TrimEnd('/');
        return NormalizeRelativePath(normalized);
    }

    private static string NormalizeRelativePath(string value)
    {
        if (string.IsNullOrWhiteSpace(value) ||
            value.StartsWith('/') ||
            value.Contains(':') ||
            value.Any(char.IsControl))
        {
            throw new InvalidDataException($"Invalid package path: {value}");
        }

        var parts = value.Replace('\\', '/').Split('/');
        if (parts.Any(part => part.Length == 0 || part is "." or ".."))
        {
            throw new InvalidDataException($"Invalid package path: {value}");
        }
        return string.Join('/', parts);
    }

    private static bool IsSymbolicLink(ZipArchiveEntry entry)
    {
        const int unixFileTypeMask = 0xF000;
        const int unixSymbolicLink = 0xA000;
        return ((entry.ExternalAttributes >> 16) & unixFileTypeMask) == unixSymbolicLink;
    }
}
