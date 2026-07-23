using System.IO.Compression;
using System.Security.Cryptography;
using System.Text.Json;

namespace SolomonDarkModLauncher.UI.Infrastructure;

internal static class CrashReportArchiveBuilder
{
    public const long MaximumArchiveBytes = 128L * 1024 * 1024;

    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        WriteIndented = true
    };

    public static string Build(CrashReportCapture capture)
    {
        var archivePath = Path.Combine(
            Path.GetTempPath(),
            $"solomon-dark-crash-{capture.Metadata.ClientReportId:N}.zip");
        var temporaryPath = archivePath + ".tmp";
        File.Delete(temporaryPath);
        File.Delete(archivePath);

        try
        {
            var artifactDetails = capture.Artifacts
                .Select(artifact => new CrashReportArtifactDetails(
                    artifact.ArchivePath,
                    new FileInfo(artifact.SourcePath).Length,
                    Sha256File(artifact.SourcePath)))
                .ToArray();

            using (var stream = new FileStream(
                       temporaryPath,
                       FileMode.CreateNew,
                       FileAccess.Write,
                       FileShare.None))
            using (var archive = new ZipArchive(stream, ZipArchiveMode.Create, leaveOpen: false))
            {
                var manifestEntry = archive.CreateEntry("report.json", CompressionLevel.Optimal);
                using (var manifestStream = manifestEntry.Open())
                {
                    JsonSerializer.Serialize(
                        manifestStream,
                        new CrashReportArchiveManifest(capture.Metadata, artifactDetails),
                        JsonOptions);
                }

                foreach (var artifact in capture.Artifacts)
                {
                    var entry = archive.CreateEntry(
                        artifact.ArchivePath,
                        CompressionLevel.Optimal);
                    using var source = File.OpenRead(artifact.SourcePath);
                    using var destination = entry.Open();
                    source.CopyTo(destination);
                }
            }

            if (new FileInfo(temporaryPath).Length > MaximumArchiveBytes)
            {
                throw new InvalidDataException(
                    "The captured diagnostics exceed the 128 MiB crash-report limit.");
            }

            File.Move(temporaryPath, archivePath);
            return archivePath;
        }
        catch
        {
            File.Delete(temporaryPath);
            File.Delete(archivePath);
            throw;
        }
    }

    private static string Sha256File(string path)
    {
        using var stream = File.OpenRead(path);
        return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
    }

    private sealed record CrashReportArchiveManifest(
        CrashReportMetadata Report,
        IReadOnlyList<CrashReportArtifactDetails> ArtifactDetails);

    private sealed record CrashReportArtifactDetails(
        string Path,
        long Size,
        string Sha256);
}
