using System.IO.Compression;
using System.Text.Json;
using SolomonDarkModding.Distribution;
using SolomonDarkModding.Updates;

namespace SolomonDarkLauncherUpdater;

internal static class LauncherUpdateInstaller
{
    private const long MaximumExpandedBytes = 1024L * 1024L * 1024L;
    private const int MaximumEntries = 20_000;

    public static void Install(
        string archivePath,
        string targetPath,
        IProgress<UpdateProgress>? progress = null)
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
            var extractedPackagePath = ExtractPackage(
                archivePath,
                stagingPath,
                progress);
            ValidateDistribution(extractedPackagePath, progress);
            var oldOwnedFiles = ReadOwnedFiles(targetPath);

            progress?.Report(new UpdateProgress(
                UpdateProgressPhase.Installing,
                "Replacing launcher files…"));
            Directory.Move(targetPath, backupPath);
            targetMoved = true;
            Directory.Move(extractedPackagePath, targetPath);
            PreserveUserFiles(
                backupPath,
                targetPath,
                oldOwnedFiles,
                progress);

            progress?.Report(new UpdateProgress(
                UpdateProgressPhase.Installing,
                "Finishing launcher installation…",
                0,
                1,
                UpdateProgressUnit.Items));
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
            progress?.Report(new UpdateProgress(
                UpdateProgressPhase.Installing,
                "Launcher files installed.",
                1,
                1,
                UpdateProgressUnit.Items));
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

    private static string ExtractPackage(
        string archivePath,
        string stagingPath,
        IProgress<UpdateProgress>? progress)
    {
        Directory.CreateDirectory(stagingPath);
        using var archive = ZipFile.OpenRead(archivePath);
        if (archive.Entries.Count > MaximumEntries)
        {
            throw new InvalidDataException("The launcher update contains too many files.");
        }

        long totalExpandedBytes = 0;
        foreach (var entry in archive.Entries)
        {
            if (entry.FullName.EndsWith('/') || entry.FullName.EndsWith('\\'))
            {
                continue;
            }
            totalExpandedBytes = checked(totalExpandedBytes + entry.Length);
            if (totalExpandedBytes > MaximumExpandedBytes)
            {
                throw new InvalidDataException("The launcher update is too large when extracted.");
            }
        }

        const string extractionStatus = "Installing launcher update files…";
        progress?.Report(new UpdateProgress(
            UpdateProgressPhase.Installing,
            extractionStatus,
            0,
            totalExpandedBytes,
            UpdateProgressUnit.Bytes));
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
            progress?.Report(new UpdateProgress(
                UpdateProgressPhase.Installing,
                extractionStatus,
                expandedBytes,
                totalExpandedBytes,
                UpdateProgressUnit.Bytes));
        }

        if (packageDirectoryName is null)
        {
            throw new InvalidDataException("The launcher update is empty.");
        }
        return ResolvePackagedPath(stagingPath, packageDirectoryName);
    }

    private static void ValidateDistribution(
        string packagePath,
        IProgress<UpdateProgress>? progress)
    {
        progress?.Report(new UpdateProgress(
            UpdateProgressPhase.Verifying,
            "Verifying launcher package…",
            0,
            1,
            UpdateProgressUnit.Items));
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
        progress?.Report(new UpdateProgress(
            UpdateProgressPhase.Verifying,
            "Launcher package verified.",
            actualFiles.Count,
            actualFiles.Count,
            UpdateProgressUnit.Items));
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
        HashSet<string> oldOwnedFiles,
        IProgress<UpdateProgress>? progress)
    {
        var sourcePaths = Directory.EnumerateFiles(
                backupPath,
                "*",
                SearchOption.AllDirectories)
            .ToArray();
        const string status = "Preserving your mods and other files…";
        progress?.Report(new UpdateProgress(
            UpdateProgressPhase.Installing,
            status,
            0,
            sourcePaths.Length,
            UpdateProgressUnit.Items));
        for (var index = 0; index < sourcePaths.Length; index++)
        {
            var sourcePath = sourcePaths[index];
            var relativePath = Path.GetRelativePath(backupPath, sourcePath).Replace('\\', '/');
            if (oldOwnedFiles.Contains(relativePath))
            {
                progress?.Report(new UpdateProgress(
                    UpdateProgressPhase.Installing,
                    status,
                    index + 1,
                    sourcePaths.Length,
                    UpdateProgressUnit.Items));
                continue;
            }

            var destinationPath = ResolvePackagedPath(targetPath, relativePath);
            if (File.Exists(destinationPath) || Directory.Exists(destinationPath))
            {
                progress?.Report(new UpdateProgress(
                    UpdateProgressPhase.Installing,
                    status,
                    index + 1,
                    sourcePaths.Length,
                    UpdateProgressUnit.Items));
                continue;
            }

            var destinationDirectory = Path.GetDirectoryName(destinationPath)!;
            if (File.Exists(destinationDirectory))
            {
                progress?.Report(new UpdateProgress(
                    UpdateProgressPhase.Installing,
                    status,
                    index + 1,
                    sourcePaths.Length,
                    UpdateProgressUnit.Items));
                continue;
            }
            Directory.CreateDirectory(destinationDirectory);
            File.Copy(sourcePath, destinationPath);
            progress?.Report(new UpdateProgress(
                UpdateProgressPhase.Installing,
                status,
                index + 1,
                sourcePaths.Length,
                UpdateProgressUnit.Items));
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
