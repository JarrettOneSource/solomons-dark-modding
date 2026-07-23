using System.Diagnostics;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;

namespace SolomonDarkModLauncher.UI.Infrastructure;

internal sealed record SteamLinkedWebsiteAccount(
    int Id,
    string Username);

internal sealed record SteamWebsiteSession(
    string Token,
    string SteamId,
    DateTimeOffset ExpiresAtUtc,
    SteamLinkedWebsiteAccount? LinkedAccount);

internal sealed class SteamWebsiteSessionClient
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true
    };

    private readonly SemaphoreSlim authenticationLock_ = new(1, 1);
    private SteamWebsiteSession? cachedSession_;
    private string? cachedDirectoryUrl_;

    public async Task<SteamWebsiteSession> GetAsync(
        string directoryUrl,
        bool forceRefresh = false,
        CancellationToken cancellationToken = default)
    {
        directoryUrl = directoryUrl.TrimEnd('/');
        await authenticationLock_.WaitAsync(cancellationToken);
        try
        {
            if (!forceRefresh &&
                string.Equals(cachedDirectoryUrl_, directoryUrl, StringComparison.OrdinalIgnoreCase) &&
                cachedSession_ is { } cached &&
                cached.ExpiresAtUtc > DateTimeOffset.UtcNow.AddMinutes(1))
            {
                return cached;
            }

            var session = await AuthenticateAsync(directoryUrl, cancellationToken);
            cachedDirectoryUrl_ = directoryUrl;
            cachedSession_ = session;
            return session;
        }
        finally
        {
            authenticationLock_.Release();
        }
    }

    public async Task UnlinkAccountAsync(
        string directoryUrl,
        CancellationToken cancellationToken = default)
    {
        directoryUrl = directoryUrl.TrimEnd('/');
        var session = await GetAsync(directoryUrl, cancellationToken: cancellationToken);
        if (session.LinkedAccount is null)
        {
            return;
        }

        using var client = new HttpClient
        {
            BaseAddress = new Uri(directoryUrl + "/"),
            Timeout = TimeSpan.FromSeconds(30)
        };
        using var request = new HttpRequestMessage(HttpMethod.Delete, "api/auth/steam");
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", session.Token);
        using var response = await client.SendAsync(request, cancellationToken);
        if (!response.IsSuccessStatusCode)
        {
            throw new InvalidOperationException(
                $"The website refused to unlink this Steam account ({(int)response.StatusCode}): " +
                await ReadWebsiteErrorAsync(response, cancellationToken));
        }

        await authenticationLock_.WaitAsync(cancellationToken);
        try
        {
            cachedSession_ = null;
        }
        finally
        {
            authenticationLock_.Release();
        }
    }

    private static async Task<string> ReadWebsiteErrorAsync(
        HttpResponseMessage response,
        CancellationToken cancellationToken)
    {
        try
        {
            var error = await response.Content.ReadFromJsonAsync<LauncherErrorResponse>(
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

    private static async Task<SteamWebsiteSession> AuthenticateAsync(
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
            string.IsNullOrWhiteSpace(envelope.DirectorySession?.Token) ||
            string.IsNullOrWhiteSpace(envelope.DirectorySession.SteamId))
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

    private sealed class DirectoryAuthenticationResponse
    {
        public bool Success { get; set; }
        public SteamWebsiteSession? DirectorySession { get; set; }
    }

    private sealed class LauncherErrorResponse
    {
        public string? Error { get; set; }
    }
}
