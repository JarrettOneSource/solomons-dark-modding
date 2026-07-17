using System.ComponentModel;
using System.Net;
using System.Net.Http;
using System.Net.Http.Json;
using System.Net.Http.Headers;
using System.Text.Json;

namespace SolomonDarkModLauncher.UI.Infrastructure;

/// <summary>
/// Read-only client for the optional website lobby directory. Directory
/// failures never affect hosting or Steam-invite joins.
/// </summary>
internal sealed class LobbyDirectoryClient(LauncherUiCommandClient launcher)
{
    public const string DefaultDirectoryUrl = "https://solomon.genericproject.xyz";

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true
    };

    private static readonly HttpClient Http = new()
    {
        Timeout = TimeSpan.FromSeconds(5)
    };

    private readonly SemaphoreSlim sessionGate_ = new(1, 1);
    private LauncherCliDirectorySession? session_;
    private string? sessionDirectoryUrl_;
    private DateTime nextAuthenticationAttemptUtc_;

    public async Task<DirectoryLobbyList> ListAsync(
        CancellationToken cancellationToken)
    {
        var directoryUrl = launcher.DirectoryUrl;
        var token = await GetSessionTokenAsync(directoryUrl, cancellationToken);
        var response = await SendListRequestAsync(directoryUrl, token, cancellationToken);
        if (response.StatusCode == HttpStatusCode.Unauthorized && token is not null)
        {
            InvalidateSession();
            token = await GetSessionTokenAsync(directoryUrl, cancellationToken);
            response.Dispose();
            response = await SendListRequestAsync(directoryUrl, token, cancellationToken);
        }

        using (response)
        {
            response.EnsureSuccessStatusCode();
            var list = await response.Content.ReadFromJsonAsync<DirectoryLobbyList>(
                JsonOptions,
                cancellationToken) ?? new DirectoryLobbyList();
            list.SteamAuthenticated = token is not null;
            return list;
        }
    }

    private static async Task<HttpResponseMessage> SendListRequestAsync(
        string directoryUrl,
        string? token,
        CancellationToken cancellationToken)
    {
        var url = $"{directoryUrl.TrimEnd('/')}/api/lobbies";
        using var request = new HttpRequestMessage(
            HttpMethod.Get,
            new Uri(url, UriKind.Absolute));
        if (token is not null)
        {
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
        }

        return await Http.SendAsync(request, cancellationToken);
    }

    private async Task<string?> GetSessionTokenAsync(
        string directoryUrl,
        CancellationToken cancellationToken)
    {
        if (IsCurrentSession(directoryUrl))
        {
            return session_!.Token;
        }
        if (DateTime.UtcNow < nextAuthenticationAttemptUtc_)
        {
            return null;
        }

        await sessionGate_.WaitAsync(cancellationToken);
        try
        {
            if (IsCurrentSession(directoryUrl))
            {
                return session_!.Token;
            }
            if (DateTime.UtcNow < nextAuthenticationAttemptUtc_)
            {
                return null;
            }

            LauncherUiInvocationResult invocation;
            try
            {
                invocation = await launcher.InvokeAsync(
                    LauncherUiCommandMode.DirectoryAuth,
                    cancellationToken: cancellationToken);
            }
            catch (Exception exception) when (
                exception is FileNotFoundException or Win32Exception)
            {
                nextAuthenticationAttemptUtc_ = DateTime.UtcNow.AddMinutes(1);
                return null;
            }

            var received = invocation.Response?.DirectorySession;
            if (invocation.ErrorMessage is not null ||
                received is null ||
                string.IsNullOrWhiteSpace(received.Token) ||
                received.ExpiresAtUtc <= DateTime.UtcNow.AddMinutes(1))
            {
                nextAuthenticationAttemptUtc_ = DateTime.UtcNow.AddMinutes(1);
                return null;
            }

            session_ = received;
            sessionDirectoryUrl_ = directoryUrl;
            nextAuthenticationAttemptUtc_ = DateTime.MinValue;
            return received.Token;
        }
        finally
        {
            sessionGate_.Release();
        }
    }

    private bool IsCurrentSession(string directoryUrl) =>
        session_ is not null &&
        session_.ExpiresAtUtc > DateTime.UtcNow.AddMinutes(1) &&
        string.Equals(sessionDirectoryUrl_, directoryUrl, StringComparison.OrdinalIgnoreCase);

    private void InvalidateSession()
    {
        session_ = null;
        sessionDirectoryUrl_ = null;
        nextAuthenticationAttemptUtc_ = DateTime.MinValue;
    }
}

internal sealed class DirectoryLobbyList
{
    public List<DirectoryLobby> Items { get; set; } = [];
    public int PlayerCount { get; set; }
    public bool SteamAuthenticated { get; set; }
}

internal sealed class DirectoryLobby
{
    public int Id { get; set; }
    public string HostPlayer { get; set; } = string.Empty;
    public string HostSteamId { get; set; } = string.Empty;
    public string Privacy { get; set; } = string.Empty;
    public string Access { get; set; } = string.Empty;
    public int Players { get; set; }
    public int MaxPlayers { get; set; }
    public DirectoryLobbyGame Game { get; set; } = new();
    public DirectoryLobbyJoin? Join { get; set; }
}

internal sealed class DirectoryLobbyGame
{
    public string Phase { get; set; } = string.Empty;
    public string? BoneyardName { get; set; }
    public int? Wave { get; set; }
    public string? Difficulty { get; set; }
    public int? ElapsedSeconds { get; set; }
    public string? StatusText { get; set; }
}

internal sealed class DirectoryLobbyJoin
{
    public string LobbyId { get; set; } = string.Empty;
    public string LaunchUri { get; set; } = string.Empty;
}
