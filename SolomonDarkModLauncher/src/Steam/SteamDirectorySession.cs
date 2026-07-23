namespace SolomonDarkModLauncher.Steam;

internal sealed record SteamDirectorySession(
    string Token,
    string SteamId,
    DateTimeOffset ExpiresAtUtc,
    SteamLinkedAccount? LinkedAccount);

internal sealed record SteamLinkedAccount(
    int Id,
    string Username);
