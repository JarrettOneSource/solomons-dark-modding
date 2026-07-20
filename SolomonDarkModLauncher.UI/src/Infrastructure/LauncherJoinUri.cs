namespace SolomonDarkModLauncher.UI.Infrastructure;

internal static class LauncherJoinUri
{
    private const string Scheme = "solomondarkrevived";

    public static bool TryParse(string? value, out ulong lobbyId)
    {
        lobbyId = 0;
        if (!Uri.TryCreate(value, UriKind.Absolute, out var uri) ||
            !string.Equals(uri.Scheme, Scheme, StringComparison.OrdinalIgnoreCase) ||
            !string.Equals(uri.Host, "join", StringComparison.Ordinal) ||
            uri.Port != -1 ||
            uri.UserInfo.Length != 0 ||
            uri.Query.Length != 0 ||
            uri.Fragment.Length != 0 ||
            uri.AbsolutePath.Length < 2 ||
            uri.AbsolutePath[0] != '/' ||
            uri.AbsolutePath.IndexOf('/', 1) >= 0)
        {
            return false;
        }

        return ulong.TryParse(uri.AbsolutePath.AsSpan(1), out lobbyId) && lobbyId != 0;
    }
}
