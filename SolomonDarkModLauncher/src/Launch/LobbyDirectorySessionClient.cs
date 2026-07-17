using System.Net.Http.Json;

namespace SolomonDarkModLauncher.Launch;

internal sealed record LobbyDirectorySession(
    string Token,
    string SteamId,
    DateTime ExpiresAtUtc);

internal static class LobbyDirectorySessionClient
{
    private static readonly HttpClient Http = new()
    {
        Timeout = TimeSpan.FromSeconds(10)
    };

    public static async Task<LobbyDirectorySession> ExchangeAsync(
        string directoryBaseUrl,
        string ticket,
        CancellationToken cancellationToken)
    {
        var endpoint = new Uri(
            $"{directoryBaseUrl.TrimEnd('/')}/api/auth/steam/session",
            UriKind.Absolute);
        using var response = await Http.PostAsJsonAsync(
            endpoint,
            new SteamSessionRequest(ticket),
            cancellationToken);
        if (!response.IsSuccessStatusCode)
        {
            var error = await response.Content.ReadFromJsonAsync<ErrorResponse>(
                cancellationToken);
            throw new InvalidOperationException(
                error?.Error ?? $"The lobby directory rejected Steam authentication ({(int)response.StatusCode}).");
        }

        var session = await response.Content.ReadFromJsonAsync<LobbyDirectorySession>(
            cancellationToken);
        if (session is null ||
            string.IsNullOrWhiteSpace(session.Token) ||
            !ulong.TryParse(session.SteamId, out var steamId) ||
            steamId == 0 ||
            session.ExpiresAtUtc <= DateTime.UtcNow)
        {
            throw new InvalidOperationException(
                "The lobby directory returned an invalid Steam session.");
        }

        return session;
    }

    private sealed record SteamSessionRequest(string Ticket);
    private sealed record ErrorResponse(string? Error);
}
