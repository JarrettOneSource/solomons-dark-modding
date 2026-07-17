namespace SolomonDarkModLauncher.Launch;

internal enum MultiplayerLobbyPrivacy
{
    Public,
    PasswordProtected,
    FriendsOnly
}

internal static class MultiplayerLobbyPrivacyTokens
{
    public static MultiplayerLobbyPrivacy Parse(string value) =>
        value.Trim().ToLowerInvariant() switch
        {
            "public" => MultiplayerLobbyPrivacy.Public,
            "password" or "passwordprotected" or "private" =>
                MultiplayerLobbyPrivacy.PasswordProtected,
            "friends" or "friendsonly" => MultiplayerLobbyPrivacy.FriendsOnly,
            _ => throw new InvalidOperationException(
                $"Unsupported lobby privacy '{value}'. Expected public, password, or friends.")
        };

    public static string ToApiToken(MultiplayerLobbyPrivacy privacy) =>
        privacy switch
        {
            MultiplayerLobbyPrivacy.Public => "public",
            MultiplayerLobbyPrivacy.PasswordProtected => "passwordProtected",
            MultiplayerLobbyPrivacy.FriendsOnly => "friendsOnly",
            _ => throw new InvalidOperationException($"Unsupported lobby privacy: {privacy}")
        };
}
