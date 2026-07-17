using System.Net.Http;
using System.Net.Http.Json;
using System.Text.Json;

namespace SolomonDarkModLauncher.UI.Infrastructure;

/// <summary>
/// Read-only client for the website lobby directory (backend/LOBBY_API.md in
/// the website repository). The directory is optional by contract — failures
/// here never affect hosting or Steam-invite joins.
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
        CancellationToken cancellationToken)
    {
        var list = await Http.GetFromJsonAsync<DirectoryLobbyList>(
            new Uri($"{directoryUrl.TrimEnd('/')}/api/lobbies", UriKind.Absolute),
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
