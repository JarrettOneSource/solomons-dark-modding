namespace SolomonDarkModLauncher.Steam;

internal sealed record SteamDirectorySession(
    string Token,
    string SteamId,
    DateTimeOffset ExpiresAtUtc);
