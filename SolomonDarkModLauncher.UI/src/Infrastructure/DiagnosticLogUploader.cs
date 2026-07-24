using System.IO.Compression;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace SolomonDarkModLauncher.UI.Infrastructure;

internal sealed record DiagnosticLogMetadata(
    Guid ClientLogId,
    DateTimeOffset CapturedAtUtc,
    string LauncherVersion,
    string OperatingSystem,
    string ProcessArchitecture,
    string DotnetRuntime,
    string? LaunchToken,
    IReadOnlyList<string> Artifacts);

internal sealed record DiagnosticLogSubmissionResult(
    string LogId,
    DateTimeOffset SubmittedAtUtc);

internal sealed class DiagnosticLogUploader
{
    public const long MaximumArchiveBytes = 128L * 1024 * 1024;

    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true
    };

    private readonly SteamWebsiteSessionClient sessionClient_;

    public DiagnosticLogUploader(SteamWebsiteSessionClient sessionClient)
    {
        sessionClient_ = sessionClient;
    }

    public async Task<DiagnosticLogSubmissionResult> SubmitAsync(
        LauncherCliResponse? lastResponse,
        string transcriptText,
        string launcherVersion,
        string directoryUrl,
        CancellationToken cancellationToken = default)
    {
        var session = await sessionClient_.GetAsync(
            directoryUrl,
            cancellationToken: cancellationToken);
        var artifacts = CaptureArtifacts(lastResponse);
        var metadata = new DiagnosticLogMetadata(
            Guid.NewGuid(),
            DateTimeOffset.UtcNow,
            launcherVersion,
            RuntimeInformation.OSDescription,
            RuntimeInformation.ProcessArchitecture.ToString(),
            RuntimeInformation.FrameworkDescription,
            lastResponse?.Launch?.LaunchToken,
            artifacts.Select(artifact => artifact.ArchivePath)
                .Append("launcher/transcript.log")
                .ToArray());
        var archivePath = BuildArchive(metadata, artifacts, transcriptText);
        try
        {
            using var client = new HttpClient
            {
                BaseAddress = new Uri(directoryUrl.TrimEnd('/') + "/"),
                Timeout = TimeSpan.FromMinutes(3)
            };
            using var request = new HttpRequestMessage(HttpMethod.Post, "api/diagnostics/logs");
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", session.Token);
            using var form = new MultipartFormDataContent();
            form.Add(
                new StringContent(
                    JsonSerializer.Serialize(metadata, JsonOptions),
                    Encoding.UTF8,
                    "application/json"),
                "metadata");
            var archiveStream = File.OpenRead(archivePath);
            var archiveContent = new StreamContent(archiveStream);
            archiveContent.Headers.ContentType = new MediaTypeHeaderValue("application/zip");
            form.Add(archiveContent, "archive", "diagnostic-logs.zip");
            request.Content = form;

            using var response = await client.SendAsync(
                request,
                HttpCompletionOption.ResponseHeadersRead,
                cancellationToken);
            if (!response.IsSuccessStatusCode)
            {
                throw new InvalidOperationException(
                    $"The website rejected the log upload ({(int)response.StatusCode}): " +
                    await ReadErrorAsync(response, cancellationToken));
            }

            return await response.Content.ReadFromJsonAsync<DiagnosticLogSubmissionResult>(
                       JsonOptions,
                       cancellationToken)
                   ?? throw new InvalidOperationException(
                       "The website returned an incomplete log-upload receipt.");
        }
        finally
        {
            File.Delete(archivePath);
        }
    }

    private static IReadOnlyList<CrashReportArtifact> CaptureArtifacts(
        LauncherCliResponse? response)
    {
        var artifacts = new List<CrashReportArtifact>();
        var stage = response?.Stage;
        if (stage is null)
        {
            return artifacts;
        }

        var logsRoot = Path.Combine(
            Path.GetFullPath(stage.StageRoot),
            ".sdmod",
            "logs");
        AddArtifact(
            artifacts,
            Path.Combine(logsRoot, "solomondarkmodloader.log"),
            "logs/loader.log");
        AddArtifact(
            artifacts,
            Path.Combine(logsRoot, "solomondarkmodloader.crash.log"),
            "logs/crash.log");
        AddArtifact(artifacts, stage.StageReportPath, "diagnostics/stage-report.json");
        AddArtifact(
            artifacts,
            Path.Combine(stage.StageRoot, ".sdmod", "startup-status.json"),
            "diagnostics/startup-status.json");
        AddArtifact(
            artifacts,
            Path.Combine(stage.StageRoot, ".sdmod", "multiplayer-session-status.json"),
            "diagnostics/multiplayer-session-status.json");
        AddArtifact(
            artifacts,
            Path.Combine(stage.StageRoot, ".sdmod", "lobby-directory.log"),
            "diagnostics/lobby-directory.log");
        AddArtifact(
            artifacts,
            stage.StageRuntimeBootstrapPath,
            "configuration/runtime-bootstrap.json");
        AddArtifact(artifacts, stage.StageRuntimeFlagsPath, "configuration/runtime-flags.ini");
        AddArtifact(artifacts, stage.StageDebugUiConfigPath, "configuration/debug-ui.ini");
        return artifacts;
    }

    private static void AddArtifact(
        ICollection<CrashReportArtifact> artifacts,
        string? sourcePath,
        string archivePath)
    {
        if (string.IsNullOrWhiteSpace(sourcePath))
        {
            return;
        }

        var fullPath = Path.GetFullPath(sourcePath);
        if (File.Exists(fullPath) && new FileInfo(fullPath).Length > 0)
        {
            artifacts.Add(new CrashReportArtifact(fullPath, archivePath));
        }
    }

    private static string BuildArchive(
        DiagnosticLogMetadata metadata,
        IReadOnlyList<CrashReportArtifact> artifacts,
        string transcriptText)
    {
        var archivePath = Path.Combine(
            Path.GetTempPath(),
            $"solomon-dark-logs-{metadata.ClientLogId:N}.zip");
        var temporaryPath = archivePath + ".tmp";
        File.Delete(temporaryPath);
        File.Delete(archivePath);

        try
        {
            using (var stream = new FileStream(
                       temporaryPath,
                       FileMode.CreateNew,
                       FileAccess.Write,
                       FileShare.None))
            using (var archive = new ZipArchive(stream, ZipArchiveMode.Create, leaveOpen: false))
            {
                var manifestEntry = archive.CreateEntry("logs.json", CompressionLevel.Optimal);
                using (var manifestStream = manifestEntry.Open())
                {
                    JsonSerializer.Serialize(
                        manifestStream,
                        new DiagnosticLogArchiveManifest(
                            metadata,
                            artifacts
                                .Select(artifact => new DiagnosticLogArtifactDetails(
                                    artifact.ArchivePath,
                                    new FileInfo(artifact.SourcePath).Length,
                                    Sha256File(artifact.SourcePath)))
                                .ToArray()),
                        JsonOptions);
                }

                var transcriptEntry = archive.CreateEntry(
                    "launcher/transcript.log",
                    CompressionLevel.Optimal);
                using (var transcriptStream = transcriptEntry.Open())
                {
                    transcriptStream.Write(Encoding.UTF8.GetBytes(transcriptText));
                }

                foreach (var artifact in artifacts)
                {
                    var entry = archive.CreateEntry(
                        artifact.ArchivePath,
                        CompressionLevel.Optimal);
                    using var source = new FileStream(
                        artifact.SourcePath,
                        FileMode.Open,
                        FileAccess.Read,
                        FileShare.ReadWrite | FileShare.Delete);
                    using var destination = entry.Open();
                    source.CopyTo(destination);
                }
            }

            if (new FileInfo(temporaryPath).Length > MaximumArchiveBytes)
            {
                throw new InvalidDataException(
                    "The captured logs exceed the 128 MiB upload limit.");
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
        using var stream = new FileStream(
            path,
            FileMode.Open,
            FileAccess.Read,
            FileShare.ReadWrite | FileShare.Delete);
        return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
    }

    private static async Task<string> ReadErrorAsync(
        HttpResponseMessage response,
        CancellationToken cancellationToken)
    {
        try
        {
            var error = await response.Content.ReadFromJsonAsync<WebsiteErrorResponse>(
                JsonOptions,
                cancellationToken);
            return string.IsNullOrWhiteSpace(error?.Error)
                ? response.ReasonPhrase ?? "request failed"
                : error.Error;
        }
        catch (JsonException)
        {
            return response.ReasonPhrase ?? "request failed";
        }
    }

    private sealed record DiagnosticLogArchiveManifest(
        DiagnosticLogMetadata Logs,
        IReadOnlyList<DiagnosticLogArtifactDetails> ArtifactDetails);

    private sealed record DiagnosticLogArtifactDetails(
        string Path,
        long Size,
        string Sha256);

    private sealed class WebsiteErrorResponse
    {
        public string? Error { get; set; }
    }
}
