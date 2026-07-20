namespace SolomonDarkModLauncher.Launch;

internal sealed record LobbyHostOptions(
    MultiplayerLobbyPrivacy Privacy,
    string DirectoryBaseUrl)
{
    public const string DefaultDirectoryBaseUrl = "https://solomon.genericproject.xyz";

    public static LobbyHostOptions Create(
        MultiplayerLobbyPrivacy privacy,
        string? directoryBaseUrl) =>
        new(privacy, NormalizeDirectoryUrl(directoryBaseUrl));

    public static LobbyHostOptions CreateDefault() =>
        Create(MultiplayerLobbyPrivacy.FriendsOnly, null);

    private static string NormalizeDirectoryUrl(string? value)
    {
        value = string.IsNullOrWhiteSpace(value) ? DefaultDirectoryBaseUrl : value.Trim();
        if (!Uri.TryCreate(value, UriKind.Absolute, out var uri) ||
            (!string.Equals(uri.Scheme, Uri.UriSchemeHttps, StringComparison.OrdinalIgnoreCase) &&
             !(string.Equals(uri.Scheme, Uri.UriSchemeHttp, StringComparison.OrdinalIgnoreCase) &&
               uri.IsLoopback)))
        {
            throw new InvalidOperationException(
                "The lobby directory URL must use HTTPS; loopback development URLs may use HTTP.");
        }

        return uri.GetLeftPart(UriPartial.Authority).TrimEnd('/');
    }
}
