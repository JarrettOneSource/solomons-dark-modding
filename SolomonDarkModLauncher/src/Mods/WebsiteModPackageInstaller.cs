using System.Buffers;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text.Json;
using SolomonDarkModding.Updates;

namespace SolomonDarkModLauncher.Mods;

internal static class WebsiteModPackageInstaller
{
    private const int MaxEntries = 2048;
    private const long MaxPackageBytes = 100L * 1024 * 1024;
    private const long MaxExpandedBytes = 256L * 1024 * 1024;
    private const int MaxRelativePathLength = 240;

    public static async Task<DiscoveredMod> InstallAsync(
        HttpClient client,
        WebsiteResolvedMod resolved,
        MultiplayerModDescriptor required,
        string cacheRootPath,
        CancellationToken cancellationToken,
        IProgress<UpdateProgress>? progress = null)
    {
        ValidateResolvedIdentity(resolved, required);
        var targetPath = GetCachePath(cacheRootPath, required);
        var existing = TryLoadExact(targetPath, required);
        if (existing is not null)
        {
            return existing;
        }

        var operationRoot = Path.Combine(cacheRootPath, $".install-{Guid.NewGuid():N}");
        var archivePath = Path.Combine(operationRoot, "package.zip");
        var extractedPath = Path.Combine(operationRoot, "content");
        Directory.CreateDirectory(operationRoot);
        try
        {
            await DownloadAsync(
                client,
                resolved,
                archivePath,
                cancellationToken,
                progress);
            await ExtractAsync(
                archivePath,
                extractedPath,
                resolved,
                cancellationToken,
                progress);

            progress?.Report(new UpdateProgress(
                UpdateProgressPhase.Verifying,
                $"Verifying {resolved.Id} v{resolved.Version} content…",
                0,
                1,
                UpdateProgressUnit.Items));
            var installed = ModDiscovery.DiscoverRoot(extractedPath);
            ValidateDownloadedMod(installed, required);
            var contentSha256 = ModContentHasher.HashDirectory(extractedPath);
            if (!string.Equals(
                    contentSha256,
                    required.ContentSha256,
                    StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidDataException(
                    $"Downloaded mod {required.Id} did not match the host content hash.");
            }
            progress?.Report(new UpdateProgress(
                UpdateProgressPhase.Verifying,
                $"Verified {resolved.Id} v{resolved.Version}.",
                1,
                1,
                UpdateProgressUnit.Items));

            progress?.Report(new UpdateProgress(
                UpdateProgressPhase.Installing,
                $"Installing {resolved.Id} v{resolved.Version}…",
                0,
                1,
                UpdateProgressUnit.Items));
            Directory.CreateDirectory(Path.GetDirectoryName(targetPath)!);
            if (Directory.Exists(targetPath))
            {
                Directory.Delete(targetPath, recursive: true);
            }
            Directory.Move(extractedPath, targetPath);
            progress?.Report(new UpdateProgress(
                UpdateProgressPhase.Installing,
                $"Installed {resolved.Id} v{resolved.Version}.",
                1,
                1,
                UpdateProgressUnit.Items));
            return ModDiscovery.DiscoverRoot(targetPath);
        }
        finally
        {
            if (Directory.Exists(operationRoot))
            {
                Directory.Delete(operationRoot, recursive: true);
            }
        }
    }

    public static string GetCachePath(
        string cacheRootPath,
        MultiplayerModDescriptor required) =>
        Path.Combine(
            cacheRootPath,
            ModContentHasher.HashText(required.Id),
            required.ContentSha256.ToLowerInvariant());

    public static DiscoveredMod? TryLoadExact(
        string path,
        MultiplayerModDescriptor required)
    {
        if (!Directory.Exists(path))
        {
            return null;
        }

        try
        {
            var mod = ModDiscovery.DiscoverRoot(path);
            ValidateDownloadedMod(mod, required);
            return string.Equals(
                ModContentHasher.HashDirectory(path),
                required.ContentSha256,
                StringComparison.OrdinalIgnoreCase)
                ? mod
                : null;
        }
        catch (Exception exception) when (exception is IOException or InvalidOperationException or JsonException)
        {
            return null;
        }
    }

    private static async Task DownloadAsync(
        HttpClient client,
        WebsiteResolvedMod resolved,
        string archivePath,
        CancellationToken cancellationToken,
        IProgress<UpdateProgress>? progress)
    {
        if (!Uri.TryCreate(resolved.DownloadUrl, UriKind.Relative, out var relativeUri) ||
            resolved.DownloadUrl.StartsWith("/", StringComparison.Ordinal) ||
            resolved.DownloadUrl.StartsWith("//", StringComparison.Ordinal))
        {
            throw new InvalidDataException(
                $"The website returned an unsafe download URL for {resolved.Id}.");
        }

        var downloadUri = new Uri(client.BaseAddress!, relativeUri);
        if (!IsInsideDirectoryOrigin(client.BaseAddress!, downloadUri))
        {
            throw new InvalidDataException(
                $"The website returned a cross-origin download URL for {resolved.Id}.");
        }

        using var response = await client.GetAsync(
            downloadUri,
            HttpCompletionOption.ResponseHeadersRead,
            cancellationToken);
        if (!response.IsSuccessStatusCode)
        {
            throw new InvalidOperationException(
                $"The website could not download {resolved.Id} {resolved.Version} " +
                $"(HTTP {(int)response.StatusCode}).");
        }

        var expectedBytes =
            response.Content.Headers.ContentLength ?? resolved.FileSizeBytes;
        if (expectedBytes is > MaxPackageBytes)
        {
            throw new InvalidDataException("Downloaded mod packages may not exceed 100 MiB.");
        }

        var downloadStatus = $"Downloading {resolved.Id} v{resolved.Version}…";
        progress?.Report(new UpdateProgress(
            UpdateProgressPhase.Downloading,
            downloadStatus,
            0,
            expectedBytes,
            UpdateProgressUnit.Bytes));
        await using var source = await response.Content.ReadAsStreamAsync(cancellationToken);
        await using var destination = new FileStream(
            archivePath,
            FileMode.CreateNew,
            FileAccess.Write,
            FileShare.None,
            81920,
            FileOptions.Asynchronous);
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        var buffer = ArrayPool<byte>.Shared.Rent(81920);
        long total = 0;
        long lastReported = 0;
        try
        {
            int count;
            while ((count = await source.ReadAsync(
                       buffer.AsMemory(0, buffer.Length),
                       cancellationToken)) > 0)
            {
                total = checked(total + count);
                if (total > MaxPackageBytes)
                {
                    throw new InvalidDataException("Downloaded mod packages may not exceed 100 MiB.");
                }

                hash.AppendData(buffer, 0, count);
                await destination.WriteAsync(buffer.AsMemory(0, count), cancellationToken);
                if (total - lastReported >= 256 * 1024 ||
                    expectedBytes is { } expected && total >= expected)
                {
                    progress?.Report(new UpdateProgress(
                        UpdateProgressPhase.Downloading,
                        downloadStatus,
                        total,
                        expectedBytes,
                        UpdateProgressUnit.Bytes));
                    lastReported = total;
                }
            }
        }
        finally
        {
            ArrayPool<byte>.Shared.Return(buffer);
        }

        progress?.Report(new UpdateProgress(
            UpdateProgressPhase.Downloading,
            downloadStatus,
            total,
            expectedBytes ?? total,
            UpdateProgressUnit.Bytes));
        progress?.Report(new UpdateProgress(
            UpdateProgressPhase.Verifying,
            $"Verifying {resolved.Id} v{resolved.Version} package…",
            total,
            expectedBytes ?? total,
            UpdateProgressUnit.Bytes));
        var packageSha256 = Convert.ToHexString(hash.GetHashAndReset()).ToLowerInvariant();
        if (!string.Equals(
                packageSha256,
                resolved.PackageSha256,
                StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException(
                $"Downloaded mod {resolved.Id} did not match the website package hash.");
        }
    }

    private static async Task ExtractAsync(
        string archivePath,
        string targetPath,
        WebsiteResolvedMod resolved,
        CancellationToken cancellationToken,
        IProgress<UpdateProgress>? progress)
    {
        Directory.CreateDirectory(targetPath);
        using var archive = ZipFile.OpenRead(archivePath);
        if (archive.Entries.Count == 0 || archive.Entries.Count > MaxEntries)
        {
            throw new InvalidDataException(
                $"Downloaded mod archives must contain 1-{MaxEntries} entries.");
        }

        var portablePaths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var validatedEntries = new List<(ZipArchiveEntry Entry, string RelativePath)>();
        long expandedBytes = 0;
        foreach (var entry in archive.Entries)
        {
            var relativePath = ValidateArchiveEntry(entry);
            if (!portablePaths.Add(relativePath.TrimEnd('/')))
            {
                throw new InvalidDataException(
                    $"Downloaded mod archive contains a duplicate path: {relativePath}");
            }

            if (!relativePath.EndsWith("/", StringComparison.Ordinal))
            {
                expandedBytes = checked(expandedBytes + entry.Length);
                if (expandedBytes > MaxExpandedBytes)
                {
                    throw new InvalidDataException(
                        "The expanded downloaded mod may not exceed 256 MiB.");
                }
            }
            validatedEntries.Add((entry, relativePath));
        }

        ValidateArchiveTree(validatedEntries
            .Where(item => !item.RelativePath.EndsWith("/", StringComparison.Ordinal))
            .Select(item => item.RelativePath));
        var installStatus = $"Installing {resolved.Id} v{resolved.Version} files…";
        progress?.Report(new UpdateProgress(
            UpdateProgressPhase.Installing,
            installStatus,
            0,
            expandedBytes,
            UpdateProgressUnit.Bytes));
        long installedBytes = 0;
        foreach (var item in validatedEntries)
        {
            var destinationPath = ResolveInside(targetPath, item.RelativePath);
            if (item.RelativePath.EndsWith("/", StringComparison.Ordinal))
            {
                Directory.CreateDirectory(destinationPath);
                continue;
            }

            Directory.CreateDirectory(Path.GetDirectoryName(destinationPath)!);
            await using var source = item.Entry.Open();
            await using var destination = new FileStream(
                destinationPath,
                FileMode.CreateNew,
                FileAccess.Write,
                FileShare.None,
                81920,
                FileOptions.Asynchronous);
            await source.CopyToAsync(destination, cancellationToken);
            installedBytes = checked(installedBytes + item.Entry.Length);
            progress?.Report(new UpdateProgress(
                UpdateProgressPhase.Installing,
                installStatus,
                installedBytes,
                expandedBytes,
                UpdateProgressUnit.Bytes));
        }
    }

    private static void ValidateArchiveTree(IEnumerable<string> filePaths)
    {
        var files = new HashSet<string>(filePaths, StringComparer.OrdinalIgnoreCase);
        foreach (var path in files)
        {
            var separator = path.IndexOf('/');
            while (separator >= 0)
            {
                if (files.Contains(path[..separator]))
                {
                    throw new InvalidDataException(
                        $"A downloaded archive path is both a file and a directory: {path[..separator]}");
                }
                separator = path.IndexOf('/', separator + 1);
            }
        }
    }

    private static string ValidateArchiveEntry(ZipArchiveEntry entry)
    {
        var path = entry.FullName;
        if (path.Length == 0 || path.Length > MaxRelativePathLength ||
            path.StartsWith("/", StringComparison.Ordinal) ||
            path.Contains('\\') || path.Contains('\0'))
        {
            throw new InvalidDataException($"Downloaded mod archive has an unsafe path: {path}");
        }

        var segments = path.TrimEnd('/').Split('/');
        if (segments.Any(segment => !IsPortablePathSegment(segment)))
        {
            throw new InvalidDataException($"Downloaded mod archive path is not portable: {path}");
        }

        var unixFileType = (entry.ExternalAttributes >> 16) & 0xF000;
        if (unixFileType == 0xA000 ||
            (entry.ExternalAttributes & (int)FileAttributes.ReparsePoint) != 0)
        {
            throw new InvalidDataException($"Downloaded mod archive links are not allowed: {path}");
        }

        if (path.EndsWith("/", StringComparison.Ordinal) && entry.Length != 0)
        {
            throw new InvalidDataException($"Invalid directory entry in downloaded mod: {path}");
        }

        return path;
    }

    private static bool IsPortablePathSegment(string segment)
    {
        if (segment.Length == 0 || segment is "." or ".." ||
            segment.EndsWith(' ') || segment.EndsWith('.'))
        {
            return false;
        }

        if (segment.Any(character =>
                character < 0x20 || character is '<' or '>' or ':' or '"' or '|' or '?' or '*'))
        {
            return false;
        }

        var baseName = segment.Split('.', 2)[0];
        return baseName.ToUpperInvariant() is not
            ("CON" or "PRN" or "AUX" or "NUL" or
             "COM1" or "COM2" or "COM3" or "COM4" or "COM5" or
             "COM6" or "COM7" or "COM8" or "COM9" or
             "LPT1" or "LPT2" or "LPT3" or "LPT4" or "LPT5" or
             "LPT6" or "LPT7" or "LPT8" or "LPT9");
    }

    private static string ResolveInside(string rootPath, string relativePath)
    {
        var normalizedRoot = Path.GetFullPath(rootPath)
            .TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
            + Path.DirectorySeparatorChar;
        var candidate = Path.GetFullPath(Path.Combine(
            rootPath,
            relativePath.Replace('/', Path.DirectorySeparatorChar)));
        if (!candidate.StartsWith(normalizedRoot, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException(
                $"Downloaded mod archive path escapes its package: {relativePath}");
        }
        return candidate;
    }

    private static bool IsInsideDirectoryOrigin(Uri baseAddress, Uri candidate)
    {
        if (!string.Equals(baseAddress.Scheme, candidate.Scheme, StringComparison.OrdinalIgnoreCase) ||
            !string.Equals(baseAddress.Host, candidate.Host, StringComparison.OrdinalIgnoreCase) ||
            baseAddress.Port != candidate.Port)
        {
            return false;
        }

        var basePath = baseAddress.AbsolutePath.TrimEnd('/') + "/";
        return candidate.AbsolutePath.StartsWith(basePath, StringComparison.Ordinal);
    }

    private static void ValidateResolvedIdentity(
        WebsiteResolvedMod resolved,
        MultiplayerModDescriptor required)
    {
        if (!string.Equals(resolved.Id, required.Id, StringComparison.OrdinalIgnoreCase) ||
            !string.Equals(resolved.Version, required.Version, StringComparison.Ordinal) ||
            !string.Equals(
                resolved.ContentSha256,
                required.ContentSha256,
                StringComparison.OrdinalIgnoreCase) ||
            !IsSha256(resolved.PackageSha256))
        {
            throw new InvalidDataException(
                $"The website returned the wrong package identity for {required.Id}.");
        }
    }

    private static void ValidateDownloadedMod(
        DiscoveredMod mod,
        MultiplayerModDescriptor required)
    {
        if (!string.Equals(mod.Manifest.Id, required.Id, StringComparison.OrdinalIgnoreCase) ||
            !string.Equals(mod.Manifest.Version, required.Version, StringComparison.Ordinal))
        {
            throw new InvalidDataException(
                $"Downloaded mod manifest identity does not match {required.Id} {required.Version}.");
        }

        var downloadedDll = Directory.EnumerateFiles(
                mod.RootPath,
                "*",
                SearchOption.AllDirectories)
            .FirstOrDefault(path => path.EndsWith(".dll", StringComparison.OrdinalIgnoreCase));
        if (downloadedDll is not null)
        {
            throw new InvalidDataException(
                "The downloaded archive contains a file type outside the mod package contract.");
        }

        if (mod.RequiresLuaRuntime)
        {
            var entryScript = mod.Manifest.Runtime.EntryScript;
            var script = ResolveModPath(mod, entryScript);
            if (!entryScript.StartsWith("scripts/", StringComparison.Ordinal) ||
                !entryScript.EndsWith(".lua", StringComparison.Ordinal) ||
                !File.Exists(script))
            {
                throw new InvalidDataException(
                    "Website-downloaded Lua mods must contain their scripts/ entry file.");
            }
        }

        foreach (var overlay in mod.Manifest.Overlays)
        {
            if (!overlay.Source.StartsWith("files/", StringComparison.Ordinal))
            {
                throw new InvalidDataException(
                    $"Website-downloaded overlay source is not under files/: {overlay.Source}");
            }

            var target = overlay.Target;
            var allowedStockBoneyard =
                target.StartsWith("data/levels/", StringComparison.Ordinal) &&
                target.EndsWith(".boneyard", StringComparison.Ordinal);
            var allowedImageTarget = target.StartsWith("images/", StringComparison.Ordinal);
            var allowedCustomBoneyard =
                target.StartsWith("sandbox/DarkCloud/mylevels/", StringComparison.Ordinal) &&
                target.EndsWith(".boneyard", StringComparison.Ordinal);
            if (!allowedStockBoneyard && !allowedImageTarget && !allowedCustomBoneyard)
            {
                throw new InvalidDataException(
                    $"Downloaded overlays must target Boneyards under data/levels/ or sandbox/DarkCloud/mylevels/, or art under images/: {overlay.Target}");
            }
        }
    }

    private static string ResolveModPath(DiscoveredMod mod, string relativePath)
    {
        var normalizedRoot = Path.GetFullPath(mod.RootPath)
            .TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
            + Path.DirectorySeparatorChar;
        var candidate = Path.GetFullPath(Path.Combine(
            mod.RootPath,
            relativePath.Replace('/', Path.DirectorySeparatorChar)));
        if (!candidate.StartsWith(normalizedRoot, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException("Website-downloaded runtime path escaped its mod root.");
        }
        return candidate;
    }

    private static bool IsSha256(string? value) =>
        value is { Length: 64 } && value.All(character =>
            character is >= '0' and <= '9' or >= 'a' and <= 'f' or >= 'A' and <= 'F');
}
