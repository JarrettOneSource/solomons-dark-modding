namespace SolomonDarkModLauncher.UI.Infrastructure;

internal static class LauncherJoinUri
{
    private const string Scheme = "solomondarkrevived";

    public static bool TryParse(string? value, out LauncherJoinActivation activation)
    {
        activation = null!;
        if (!Uri.TryCreate(value, UriKind.Absolute, out var uri) ||
            !string.Equals(uri.Scheme, Scheme, StringComparison.OrdinalIgnoreCase) ||
            !string.Equals(uri.Host, "join", StringComparison.Ordinal) ||
            uri.Port != -1 ||
            uri.UserInfo.Length != 0 ||
            uri.Fragment.Length != 0 ||
            uri.AbsolutePath.Length < 2 ||
            uri.AbsolutePath[0] != '/' ||
            uri.AbsolutePath.IndexOf('/', 1) >= 0)
        {
            return false;
        }

        if (!ulong.TryParse(uri.AbsolutePath.AsSpan(1), out var lobbyId) || lobbyId == 0 ||
            !TryParseQuery(uri.Query, out var directoryBaseUrl, out var ticket))
        {
            return false;
        }

        activation = new LauncherJoinActivation(lobbyId, directoryBaseUrl, ticket);
        return true;
    }

    private static bool TryParseQuery(
        string query,
        out string directoryBaseUrl,
        out string? ticket)
    {
        directoryBaseUrl = string.Empty;
        ticket = null;
        if (query.Length < 2)
        {
            return false;
        }

        var values = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var pair in query[1..].Split('&', StringSplitOptions.RemoveEmptyEntries))
        {
            var equalsIndex = pair.IndexOf('=');
            if (equalsIndex <= 0)
            {
                return false;
            }

            string key;
            string value;
            try
            {
                key = Uri.UnescapeDataString(pair[..equalsIndex]);
                value = Uri.UnescapeDataString(pair[(equalsIndex + 1)..]);
            }
            catch (UriFormatException)
            {
                return false;
            }

            if (key is not ("directory" or "ticket") || !values.TryAdd(key, value))
            {
                return false;
            }
        }

        if (!values.TryGetValue("directory", out var parsedDirectoryBaseUrl) ||
            !IsSafeDirectoryUrl(parsedDirectoryBaseUrl))
        {
            return false;
        }
        directoryBaseUrl = parsedDirectoryBaseUrl;

        if (values.TryGetValue("ticket", out var parsedTicket))
        {
            if (parsedTicket.Length is < 1 or > 512 || parsedTicket.Any(char.IsControl))
            {
                return false;
            }
            ticket = parsedTicket;
        }

        directoryBaseUrl = directoryBaseUrl.TrimEnd('/');
        return true;
    }

    private static bool IsSafeDirectoryUrl(string value) =>
        Uri.TryCreate(value, UriKind.Absolute, out var uri) &&
        (string.Equals(uri.Scheme, Uri.UriSchemeHttps, StringComparison.OrdinalIgnoreCase) ||
         (string.Equals(uri.Scheme, Uri.UriSchemeHttp, StringComparison.OrdinalIgnoreCase) &&
          uri.IsLoopback)) &&
        uri.UserInfo.Length == 0 &&
        uri.Query.Length == 0 &&
        uri.Fragment.Length == 0;
}

internal sealed record LauncherJoinActivation(
    ulong LobbyId,
    string DirectoryBaseUrl,
    string? Ticket);
