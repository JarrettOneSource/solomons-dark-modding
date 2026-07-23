using System.Diagnostics;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;

namespace SolomonDarkModLauncher.UI.Infrastructure;

internal sealed record CrashReportSubmissionResult(
    string ReportId,
    DateTimeOffset SubmittedAtUtc);

internal sealed class CrashReportSubmissionClient
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true
    };

    public async Task<CrashReportSubmissionResult> SubmitAsync(
        CrashReportCapture capture,
        string directoryUrl,
        CancellationToken cancellationToken = default)
    {
        var session = await AuthenticateAsync(directoryUrl, cancellationToken);
        var archivePath = CrashReportArchiveBuilder.Build(capture);
        try
        {
            using var client = new HttpClient
            {
                BaseAddress = new Uri(directoryUrl.TrimEnd('/') + "/"),
                Timeout = TimeSpan.FromMinutes(3)
            };
            using var request = new HttpRequestMessage(HttpMethod.Post, "api/crash-reports");
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", session.Token);
            using var form = new MultipartFormDataContent();
            form.Add(
                new StringContent(
                    JsonSerializer.Serialize(capture.Metadata, JsonOptions),
                    Encoding.UTF8,
                    "application/json"),
                "metadata");
            var archiveStream = File.OpenRead(archivePath);
            var archiveContent = new StreamContent(archiveStream);
            archiveContent.Headers.ContentType = new MediaTypeHeaderValue("application/zip");
            form.Add(archiveContent, "archive", "crash-report.zip");
            request.Content = form;

            using var response = await client.SendAsync(
                request,
                HttpCompletionOption.ResponseHeadersRead,
                cancellationToken);
            if (!response.IsSuccessStatusCode)
            {
                throw new InvalidOperationException(
                    $"The website rejected the crash report ({(int)response.StatusCode}): " +
                    await ReadErrorAsync(response, cancellationToken));
            }

            return await response.Content.ReadFromJsonAsync<CrashReportSubmissionResult>(
                       JsonOptions,
                       cancellationToken)
                   ?? throw new InvalidOperationException(
                       "The website returned an incomplete crash-report receipt.");
        }
        finally
        {
            File.Delete(archivePath);
        }
    }

    private static async Task<SteamSessionEnvelope> AuthenticateAsync(
        string directoryUrl,
        CancellationToken cancellationToken)
    {
        var startInfo = new ProcessStartInfo(LauncherExecutableResolver.Resolve())
        {
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true
        };
        foreach (var argument in new[]
                 {
                     "directory-auth",
                     "--json",
                     "--directory-url",
                     directoryUrl
                 })
        {
            startInfo.ArgumentList.Add(argument);
        }

        using var process = new Process { StartInfo = startInfo };
        process.Start();
        var standardOutput = process.StandardOutput.ReadToEndAsync(cancellationToken);
        var standardError = process.StandardError.ReadToEndAsync(cancellationToken);
        await process.WaitForExitAsync(cancellationToken);
        var output = await standardOutput;
        var error = await standardError;
        if (process.ExitCode != 0)
        {
            throw new InvalidOperationException(
                ReadLauncherError(error) ??
                "Steam authentication failed. Make sure Steam is running and logged in.");
        }

        var envelope = JsonSerializer.Deserialize<DirectoryAuthenticationResponse>(
            output,
            JsonOptions);
        if (envelope?.Success != true ||
            string.IsNullOrWhiteSpace(envelope.DirectorySession?.Token))
        {
            throw new InvalidOperationException(
                "The launcher returned an incomplete Steam website session.");
        }
        return envelope.DirectorySession;
    }

    private static string? ReadLauncherError(string payload)
    {
        try
        {
            return JsonSerializer.Deserialize<LauncherErrorResponse>(payload, JsonOptions)?.Error;
        }
        catch (JsonException)
        {
            return string.IsNullOrWhiteSpace(payload) ? null : payload.Trim();
        }
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

    private sealed class DirectoryAuthenticationResponse
    {
        public bool Success { get; set; }
        public SteamSessionEnvelope? DirectorySession { get; set; }
    }

    private sealed class SteamSessionEnvelope
    {
        public string Token { get; set; } = string.Empty;
    }

    private sealed class LauncherErrorResponse
    {
        public string? Error { get; set; }
    }

    private sealed class WebsiteErrorResponse
    {
        public string? Error { get; set; }
    }
}
