using System.IO.Compression;
using System.Security.Cryptography;
using System.Text.Json;

namespace SolomonDarkModLauncher.UI.Infrastructure;

internal sealed record CloudSaveArchivePayload(
    byte[] Bytes,
    string Sha256,
    int FileCount,
    long UncompressedSize);

internal static class CloudSaveArchive
{
    public const int FormatVersion = 1;
    public const int MaxArchiveBytes = 16 * 1024 * 1024;
    public const long MaxUncompressedBytes = 64L * 1024 * 1024;
    public const int MaxFiles = 256;

    private const int MaxManifestBytes = 128 * 1024;
    private static readonly DateTimeOffset StableZipTimestamp =
        new(2000, 1, 1, 0, 0, 0, TimeSpan.Zero);
    private static readonly JsonSerializerOptions JsonOptions =
        new(JsonSerializerDefaults.Web);

    public static CloudSaveArchivePayload Build(LocalSaveSlot save)
    {
        var files = EnumerateFiles(save.SavegamesRootPath);
        if (files.Count == 0)
        {
            throw new InvalidOperationException("This save has no local files to back up.");
        }
        if (files.Count > MaxFiles)
        {
            throw new InvalidDataException("Cloud saves may contain at most 256 files.");
        }

        using var output = new MemoryStream();
        var manifestFiles = new List<ArchiveFile>(files.Count);
        long totalBytes = 0;
        using (var archive = new ZipArchive(output, ZipArchiveMode.Create, leaveOpen: true))
        {
            foreach (var source in files)
            {
                var relativePath = NormalizeRelativePath(
                    Path.GetRelativePath(save.SavegamesRootPath, source.FullName)
                        .Replace(Path.DirectorySeparatorChar, '/'));
                var entry = archive.CreateEntry(
                    $"savegames/{relativePath}",
                    CompressionLevel.Optimal);
                entry.LastWriteTime = StableZipTimestamp;

                using var sourceStream = new FileStream(
                    source.FullName,
                    FileMode.Open,
                    FileAccess.Read,
                    FileShare.ReadWrite | FileShare.Delete);
                using var destinationStream = entry.Open();
                using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
                var buffer = new byte[64 * 1024];
                long fileBytes = 0;
                while (true)
                {
                    var read = sourceStream.Read(buffer, 0, buffer.Length);
                    if (read == 0)
                    {
                        break;
                    }
                    fileBytes += read;
                    totalBytes = checked(totalBytes + read);
                    if (totalBytes > MaxUncompressedBytes)
                    {
                        throw new InvalidDataException(
                            "Cloud saves may not expand beyond 64 MiB.");
                    }
                    hash.AppendData(buffer, 0, read);
                    destinationStream.Write(buffer, 0, read);
                }
                manifestFiles.Add(new ArchiveFile(
                    relativePath,
                    fileBytes,
                    Convert.ToHexString(hash.GetHashAndReset()).ToLowerInvariant()));
            }

            var manifestEntry = archive.CreateEntry("manifest.json", CompressionLevel.Optimal);
            manifestEntry.LastWriteTime = StableZipTimestamp;
            using var manifestStream = manifestEntry.Open();
            JsonSerializer.Serialize(
                manifestStream,
                new ArchiveManifest(
                    FormatVersion,
                    save.Slot,
                    save.Name,
                    manifestFiles),
                JsonOptions);
        }

        var bytes = output.ToArray();
        if (bytes.Length > MaxArchiveBytes)
        {
            throw new InvalidDataException(
                "This save compresses to more than the 16 MiB cloud limit.");
        }
        return new CloudSaveArchivePayload(
            bytes,
            Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant(),
            manifestFiles.Count,
            totalBytes);
    }

    public static string? Restore(
        LocalSaveCatalog catalog,
        int slot,
        ReadOnlyMemory<byte> bytes)
    {
        if (bytes.Length is <= 0 or > MaxArchiveBytes)
        {
            throw new InvalidDataException("The cloud save archive has an invalid size.");
        }

        var restoreRoot = Path.Combine(
            catalog.SavesRoot,
            $".restore-{Guid.NewGuid():N}");
        var savegamesRoot = Path.Combine(restoreRoot, "savegames");
        Directory.CreateDirectory(savegamesRoot);
        try
        {
            var name = ValidateAndExtract(bytes, slot, savegamesRoot);
            catalog.ReplaceFromRestore(slot, savegamesRoot);
            if (!string.IsNullOrWhiteSpace(name))
            {
                catalog.Rename(slot, name);
            }
            return name;
        }
        finally
        {
            if (Directory.Exists(restoreRoot))
            {
                Directory.Delete(restoreRoot, recursive: true);
            }
        }
    }

    private static string? ValidateAndExtract(
        ReadOnlyMemory<byte> bytes,
        int expectedSlot,
        string destinationRoot)
    {
        using var stream = new MemoryStream(bytes.ToArray(), writable: false);
        using var archive = new ZipArchive(stream, ZipArchiveMode.Read, leaveOpen: false);
        var entries = new Dictionary<string, ZipArchiveEntry>(StringComparer.OrdinalIgnoreCase);
        foreach (var entry in archive.Entries)
        {
            if (!entries.TryAdd(entry.FullName, entry))
            {
                throw new InvalidDataException("Cloud save archives contain duplicate paths.");
            }
            if (entry.FullName.Contains('\\') ||
                IsUnsafePath(entry.FullName) ||
                IsSymbolicLink(entry))
            {
                throw new InvalidDataException("The cloud save archive contains an unsafe path.");
            }
        }
        if (entries.Count > MaxFiles + 1)
        {
            throw new InvalidDataException("The cloud save archive contains too many entries.");
        }

        if (!entries.TryGetValue("manifest.json", out var manifestEntry) ||
            manifestEntry.Length is <= 0 or > MaxManifestBytes)
        {
            throw new InvalidDataException("The cloud save archive has no valid manifest.");
        }

        ArchiveManifest? manifest;
        using (var manifestStream = manifestEntry.Open())
        {
            manifest = JsonSerializer.Deserialize<ArchiveManifest>(manifestStream, JsonOptions);
        }
        if (manifest is null ||
            manifest.SchemaVersion != FormatVersion ||
            manifest.Slot != expectedSlot ||
            manifest.Name is { } name &&
                (name.Length > 40 || name.Any(char.IsControl)) ||
            manifest.Files is null ||
            manifest.Files.Count is <= 0 or > MaxFiles)
        {
            throw new InvalidDataException("The cloud save manifest is invalid.");
        }

        var actualFiles = entries
            .Where(pair =>
                !string.Equals(pair.Key, "manifest.json", StringComparison.OrdinalIgnoreCase) &&
                !pair.Key.EndsWith('/'))
            .ToDictionary(
                pair => NormalizeArchivePath(pair.Key),
                pair => pair.Value,
                StringComparer.OrdinalIgnoreCase);
        if (actualFiles.Count != manifest.Files.Count)
        {
            throw new InvalidDataException("The cloud save manifest does not match its files.");
        }

        var destinationPrefix = EnsureTrailingSeparator(Path.GetFullPath(destinationRoot));
        var manifestPaths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        long totalBytes = 0;
        foreach (var file in manifest.Files)
        {
            var path = NormalizeRelativePath(file.Path);
            if (!manifestPaths.Add(path) ||
                !actualFiles.TryGetValue(path, out var entry) ||
                entry.Length != file.Size ||
                !IsSha256(file.Sha256))
            {
                throw new InvalidDataException("The cloud save manifest does not match its files.");
            }

            if (entry.Length > MaxUncompressedBytes - totalBytes)
            {
                throw new InvalidDataException("Cloud saves may not expand beyond 64 MiB.");
            }
            totalBytes += entry.Length;

            var destinationPath = Path.GetFullPath(
                Path.Combine(destinationRoot, path.Replace('/', Path.DirectorySeparatorChar)));
            if (!destinationPath.StartsWith(
                    destinationPrefix,
                    OperatingSystem.IsWindows()
                        ? StringComparison.OrdinalIgnoreCase
                        : StringComparison.Ordinal))
            {
                throw new InvalidDataException("The cloud save archive contains an unsafe path.");
            }
            Directory.CreateDirectory(Path.GetDirectoryName(destinationPath)!);

            using var source = entry.Open();
            using var destination = new FileStream(
                destinationPath,
                FileMode.CreateNew,
                FileAccess.Write,
                FileShare.None);
            using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
            var buffer = new byte[64 * 1024];
            while (true)
            {
                var read = source.Read(buffer, 0, buffer.Length);
                if (read == 0)
                {
                    break;
                }
                hash.AppendData(buffer, 0, read);
                destination.Write(buffer, 0, read);
            }
            var sha256 = Convert.ToHexString(hash.GetHashAndReset()).ToLowerInvariant();
            if (!string.Equals(sha256, file.Sha256, StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidDataException(
                    "A cloud save file failed its integrity check.");
            }
        }

        return string.IsNullOrWhiteSpace(manifest.Name) ? null : manifest.Name.Trim();
    }

    private static IReadOnlyList<FileInfo> EnumerateFiles(string savegamesRootPath)
    {
        var root = new DirectoryInfo(savegamesRootPath);
        if (!root.Exists)
        {
            return [];
        }
        if ((root.Attributes & FileAttributes.ReparsePoint) != 0)
        {
            throw new InvalidDataException("The selected save folder cannot be a link.");
        }

        var files = new List<FileInfo>();
        EnumerateDirectory(root, files);
        return files
            .OrderBy(file => file.FullName, StringComparer.OrdinalIgnoreCase)
            .ToArray();
    }

    private static void EnumerateDirectory(DirectoryInfo directory, List<FileInfo> files)
    {
        foreach (var child in directory.EnumerateDirectories())
        {
            if ((child.Attributes & FileAttributes.ReparsePoint) != 0)
            {
                throw new InvalidDataException("Save folders cannot contain directory links.");
            }
            EnumerateDirectory(child, files);
        }
        foreach (var file in directory.EnumerateFiles())
        {
            if ((file.Attributes & FileAttributes.ReparsePoint) != 0)
            {
                throw new InvalidDataException("Save folders cannot contain file links.");
            }
            files.Add(file);
        }
    }

    private static string NormalizeArchivePath(string path)
    {
        const string prefix = "savegames/";
        if (!path.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException(
                "Cloud save archives may contain only savegame files.");
        }
        return NormalizeRelativePath(path[prefix.Length..]);
    }

    private static string NormalizeRelativePath(string? path)
    {
        path = path?.Trim();
        if (string.IsNullOrEmpty(path) ||
            path.Length > 240 ||
            path.Contains('\\') ||
            IsUnsafePath(path) ||
            !path.StartsWith("solomondark/", StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException("The cloud save contains an unsafe file path.");
        }
        return path;
    }

    private static bool IsUnsafePath(string path) =>
        path.StartsWith('/') ||
        path.Contains(':') ||
        path.Split('/').Any(part => part is "" or "." or "..");

    private static bool IsSymbolicLink(ZipArchiveEntry entry)
    {
        const int unixFileTypeMask = 0xF000;
        const int unixSymbolicLink = 0xA000;
        return ((entry.ExternalAttributes >> 16) & unixFileTypeMask) == unixSymbolicLink;
    }

    private static bool IsSha256(string? value) =>
        value is { Length: 64 } &&
        value.All(character =>
            character is >= '0' and <= '9' or
            >= 'a' and <= 'f' or
            >= 'A' and <= 'F');

    private static string EnsureTrailingSeparator(string path) =>
        path.EndsWith(Path.DirectorySeparatorChar)
            ? path
            : path + Path.DirectorySeparatorChar;

    private sealed record ArchiveManifest(
        int SchemaVersion,
        int Slot,
        string? Name,
        List<ArchiveFile>? Files);

    private sealed record ArchiveFile(
        string? Path,
        long Size,
        string? Sha256);
}
