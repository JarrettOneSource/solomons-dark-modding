using System.Net.Http;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;

namespace SolomonDarkModLauncher.UI.Infrastructure;

/// <summary>
/// Authenticated read client for the website lobby directory. The directory
/// discovers Steam lobbies; it is never part of the gameplay transport.
/// </summary>
internal static class LobbyDirectoryClient
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

    public static async Task<DirectoryLobbyList> ListAsync(
        string directoryUrl,
        string bearerToken,
        CancellationToken cancellationToken)
    {
        var url = $"{directoryUrl.TrimEnd('/')}/api/lobbies";
        using var request = new HttpRequestMessage(HttpMethod.Get, new Uri(url, UriKind.Absolute));
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", bearerToken);
        using var response = await Http.SendAsync(request, cancellationToken);
        response.EnsureSuccessStatusCode();
        var list = await response.Content.ReadFromJsonAsync<DirectoryLobbyList>(
            JsonOptions,
            cancellationToken);
        return list ?? new DirectoryLobbyList();
    }
}

internal sealed class DirectoryLobbyList
{
    public List<DirectoryLobby> Items { get; set; } = [];
    public int PlayerCount { get; set; }
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
