using System.Buffers.Binary;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using SolomonDarkModLauncher.Mods;

namespace SolomonDarkModLauncher.Staging;

internal static class HostModTransferPackageMaterializer
{
    public const int SchemaVersion = 1;
    public const int HeaderBytes = 96;
    public const int EntryBytes = 264;
    public const string TransferDirectoryName = "mod-transfer";
    public const string IndexFileName = "index.bin";
    private const int ModIdBytes = 128;
    private const int VersionBytes = 64;
    private static readonly DateTimeOffset ArchiveTimestamp =
        new(1980, 1, 1, 0, 0, 0, TimeSpan.Zero);

    public static HostModTransferStageResult Materialize(
        string stageRootPath,
        IReadOnlyList<DiscoveredMod> enabledMods,
        MultiplayerCompatibilityStageResult compatibility,
        bool enabled)
    {
        var transferRoot = Path.Combine(
            stageRootPath,
            ".sdmod",
            TransferDirectoryName);
        if (Directory.Exists(transferRoot))
        {
            Directory.Delete(transferRoot, recursive: true);
        }
        if (!enabled)
        {
            return HostModTransferStageResult.Disabled(transferRoot);
        }
        if (enabledMods.Count > HostModTransferProtocol.MaximumPackages)
        {
            throw new InvalidDataException(
                $"Host stages may transfer at most {HostModTransferProtocol.MaximumPackages} mods.");
        }

        var packageRoot = Path.Combine(transferRoot, "packages");
        Directory.CreateDirectory(packageRoot);
        var contentById = compatibility.EnabledMods.ToDictionary(
            mod => mod.Id,
            mod => mod.ContentSha256,
            StringComparer.OrdinalIgnoreCase);
        var packages = new List<HostModTransferStagePackage>(enabledMods.Count);
        long totalBytes = 0;
        foreach (var mod in enabledMods.OrderBy(
                     item => item.Manifest.Id,
                     StringComparer.Ordinal))
        {
            if (!contentById.TryGetValue(mod.Manifest.Id, out var contentSha256))
            {
                throw new InvalidDataException(
                    $"The staged transfer package has no compatibility identity: {mod.Manifest.Id}");
            }
            var files = WebsiteModPackageInstaller.ValidatePackageableSource(mod);
            var temporaryArchive = Path.Combine(
                transferRoot,
                $".package-{Guid.NewGuid():N}.tmp");
            CreateDeterministicArchive(temporaryArchive, files);
            var packageBytes = new FileInfo(temporaryArchive).Length;
            if (packageBytes <= 0 || packageBytes > HostModTransferProtocol.MaximumPackageBytes)
            {
                File.Delete(temporaryArchive);
                throw new InvalidDataException(
                    $"Staged mod package {mod.Manifest.Id} must be 1-100 MiB.");
            }
            totalBytes = checked(totalBytes + packageBytes);
            if (totalBytes > HostModTransferProtocol.MaximumTotalBytes)
            {
                File.Delete(temporaryArchive);
                throw new InvalidDataException(
                    "The host's staged mod packages may not exceed 512 MiB total.");
            }
            string packageSha256;
            using (var archive = new FileStream(
                temporaryArchive,
                FileMode.Open,
                FileAccess.Read,
                FileShare.Read,
                81920,
                FileOptions.SequentialScan))
            {
                packageSha256 = Convert.ToHexString(SHA256.HashData(archive))
                    .ToLowerInvariant();
            }
            var packagePath = Path.Combine(packageRoot, $"{packageSha256}.zip");
            if (File.Exists(packagePath))
            {
                File.Delete(temporaryArchive);
            }
            else
            {
                File.Move(temporaryArchive, packagePath);
            }
            packages.Add(new HostModTransferStagePackage(
                mod.Manifest.Id,
                mod.Manifest.Version,
                contentSha256.ToLowerInvariant(),
                packageSha256,
                packageBytes,
                packagePath));
        }

        var entries = SerializeEntries(packages);
        var indexSha256 = SHA256.HashData(entries);
        var indexBytes = SerializeIndex(
            compatibility.FingerprintSha256,
            indexSha256,
            packages,
            totalBytes,
            entries);
        var indexPath = Path.Combine(transferRoot, IndexFileName);
        File.WriteAllBytes(indexPath, indexBytes);
        var reportPath = Path.Combine(transferRoot, "index.json");
        File.WriteAllText(
            reportPath,
            JsonSerializer.Serialize(
                new
                {
                    schemaVersion = SchemaVersion,
                    protocolVersion = HostModTransferProtocol.Version,
                    hostManifestSha256 = compatibility.FingerprintSha256,
                    indexSha256 = Convert.ToHexString(indexSha256).ToLowerInvariant(),
                    totalPackageBytes = totalBytes,
                    packages = packages.Select(package => new
                    {
                        package.Id,
                        package.Version,
                        package.ContentSha256,
                        package.PackageSha256,
                        package.PackageBytes,
                        fileName = Path.GetFileName(package.PackagePath)
                    })
                },
                new JsonSerializerOptions { WriteIndented = true }),
            new UTF8Encoding(false));
        return new HostModTransferStageResult(
            true,
            transferRoot,
            indexPath,
            reportPath,
            Convert.ToHexString(indexSha256).ToLowerInvariant(),
            totalBytes,
            packages);
    }

    private static void CreateDeterministicArchive(
        string archivePath,
        IReadOnlyList<(string FullPath, string RelativePath)> files)
    {
        using var output = new FileStream(
            archivePath,
            FileMode.CreateNew,
            FileAccess.ReadWrite,
            FileShare.None);
        using var archive = new ZipArchive(output, ZipArchiveMode.Create, leaveOpen: false);
        foreach (var file in files)
        {
            var entry = archive.CreateEntry(file.RelativePath, CompressionLevel.Optimal);
            entry.LastWriteTime = ArchiveTimestamp;
            entry.ExternalAttributes = 0;
            using var source = new FileStream(
                file.FullPath,
                FileMode.Open,
                FileAccess.Read,
                FileShare.Read,
                81920,
                FileOptions.SequentialScan);
            using var destination = entry.Open();
            source.CopyTo(destination);
        }
    }

    private static byte[] SerializeEntries(
        IReadOnlyList<HostModTransferStagePackage> packages)
    {
        var bytes = new byte[checked(packages.Count * EntryBytes)];
        for (var index = 0; index < packages.Count; index++)
        {
            var entry = bytes.AsSpan(index * EntryBytes, EntryBytes);
            var package = packages[index];
            WriteFixedUtf8(entry[..ModIdBytes], package.Id, "mod id");
            WriteFixedUtf8(entry.Slice(128, VersionBytes), package.Version, "mod version");
            Convert.FromHexString(package.ContentSha256).CopyTo(entry.Slice(192, 32));
            Convert.FromHexString(package.PackageSha256).CopyTo(entry.Slice(224, 32));
            BinaryPrimitives.WriteUInt64LittleEndian(
                entry.Slice(256, 8),
                checked((ulong)package.PackageBytes));
        }
        return bytes;
    }

    private static byte[] SerializeIndex(
        string hostManifestSha256,
        ReadOnlySpan<byte> indexSha256,
        IReadOnlyList<HostModTransferStagePackage> packages,
        long totalBytes,
        ReadOnlySpan<byte> entries)
    {
        var bytes = new byte[checked(HeaderBytes + entries.Length)];
        "SDMXFER\0"u8.CopyTo(bytes);
        BinaryPrimitives.WriteUInt16LittleEndian(bytes.AsSpan(8, 2), SchemaVersion);
        BinaryPrimitives.WriteUInt16LittleEndian(
            bytes.AsSpan(10, 2),
            HostModTransferProtocol.Version);
        BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(12, 4), HeaderBytes);
        BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(16, 4), EntryBytes);
        BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(20, 4), checked((uint)packages.Count));
        BinaryPrimitives.WriteUInt64LittleEndian(bytes.AsSpan(24, 8), checked((ulong)totalBytes));
        Convert.FromHexString(hostManifestSha256).CopyTo(bytes.AsSpan(32, 32));
        indexSha256.CopyTo(bytes.AsSpan(64, 32));
        entries.CopyTo(bytes.AsSpan(HeaderBytes));
        return bytes;
    }

    private static void WriteFixedUtf8(Span<byte> target, string value, string label)
    {
        var byteCount = Encoding.UTF8.GetByteCount(value);
        if (byteCount <= 0 || byteCount >= target.Length)
        {
            throw new InvalidDataException(
                $"The {label} is too long for host mod transfer: {value}");
        }
        Encoding.UTF8.GetBytes(value, target);
    }
}

internal sealed record HostModTransferStageResult(
    bool Enabled,
    string RootPath,
    string? IndexPath,
    string? ReportPath,
    string? IndexSha256,
    long TotalPackageBytes,
    IReadOnlyList<HostModTransferStagePackage> Packages)
{
    public static HostModTransferStageResult Disabled(string rootPath) =>
        new(false, rootPath, null, null, null, 0, []);
}

internal sealed record HostModTransferStagePackage(
    string Id,
    string Version,
    string ContentSha256,
    string PackageSha256,
    long PackageBytes,
    string PackagePath);
