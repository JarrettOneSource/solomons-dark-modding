namespace SolomonDarkModLauncher.Launch;

internal enum MultiplayerLobbyPrivacy
{
    Public,
    FriendsOnly
}

internal static class MultiplayerLobbyPrivacyTokens
{
    public static MultiplayerLobbyPrivacy Parse(string value) =>
        value.Trim().ToLowerInvariant() switch
        {
            "public" => MultiplayerLobbyPrivacy.Public,
            "friends" or "friendsonly" => MultiplayerLobbyPrivacy.FriendsOnly,
            _ => throw new InvalidOperationException(
                $"Unsupported lobby privacy '{value}'. Expected public or friends.")
        };

    public static string ToApiToken(MultiplayerLobbyPrivacy privacy) =>
        privacy switch
        {
            MultiplayerLobbyPrivacy.Public => "public",
            MultiplayerLobbyPrivacy.FriendsOnly => "friendsOnly",
            _ => throw new InvalidOperationException($"Unsupported lobby privacy: {privacy}")
        };

    public static string ToLauncherToken(MultiplayerLobbyPrivacy privacy) =>
        privacy switch
        {
            MultiplayerLobbyPrivacy.Public => "public",
            MultiplayerLobbyPrivacy.FriendsOnly => "friends",
            _ => throw new InvalidOperationException($"Unsupported lobby privacy: {privacy}")
        };
}
