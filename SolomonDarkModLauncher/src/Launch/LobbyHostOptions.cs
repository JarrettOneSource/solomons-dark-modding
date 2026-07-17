using System.Text.RegularExpressions;

namespace SolomonDarkModLauncher.Launch;

internal sealed record LobbyPasswordOptions(string SaltHex, string HashHex)
{
    public const string Algorithm = "pbkdf2-sha256";
    public const int Iterations = 210_000;
}

internal sealed record LobbyGameMetadata(
    string? BoneyardId,
    string? BoneyardName,
    string? BoneyardSha256,
    string Phase,
    int? Wave,
    string? Difficulty,
    int? ElapsedSeconds,
    string? StatusText);

internal sealed record LobbyHostOptions(
    MultiplayerLobbyPrivacy Privacy,
    string DirectoryBaseUrl,
    LobbyPasswordOptions? Password,
    LobbyGameMetadata Game)
{
    public const string DefaultDirectoryBaseUrl = "https://solomon.genericproject.xyz";

    private static readonly Regex HexRegex = new(
        "^[0-9a-f]+$",
        RegexOptions.CultureInvariant | RegexOptions.Compiled);

    public static LobbyHostOptions Create(
        MultiplayerLobbyPrivacy privacy,
        string? directoryBaseUrl,
        string? passwordSaltHex,
        string? passwordHashHex,
        string? boneyardId,
        string? boneyardName,
        string? boneyardSha256,
        string phase,
        int? wave,
        string? difficulty,
        int? elapsedSeconds,
        string? statusText)
    {
        var directoryUrl = NormalizeDirectoryUrl(directoryBaseUrl);
        var password = CreatePassword(privacy, passwordSaltHex, passwordHashHex);
        var game = new LobbyGameMetadata(
            NormalizeOptional(boneyardId, 64, "Boneyard ids"),
            NormalizeOptional(boneyardName, 80, "Boneyard names"),
            NormalizeSha256(boneyardSha256, "Boneyard SHA-256"),
            NormalizePhase(phase),
            NormalizeOptionalRange(wave, 0, 100_000, "Wave"),
            NormalizeOptional(difficulty, 32, "Difficulty names"),
            NormalizeOptionalRange(elapsedSeconds, 0, 7 * 24 * 60 * 60, "Elapsed seconds"),
            NormalizeOptional(statusText, 120, "Lobby status text"));
        return new LobbyHostOptions(privacy, directoryUrl, password, game);
    }

    public static LobbyHostOptions CreateDefault() =>
        Create(
            MultiplayerLobbyPrivacy.FriendsOnly,
            DefaultDirectoryBaseUrl,
            null,
            null,
            null,
            null,
            null,
            "hub",
            null,
            null,
            null,
            null);

    private static LobbyPasswordOptions? CreatePassword(
        MultiplayerLobbyPrivacy privacy,
        string? saltHex,
        string? hashHex)
    {
        saltHex = NormalizeHex(saltHex);
        hashHex = NormalizeHex(hashHex);
        if (privacy != MultiplayerLobbyPrivacy.PasswordProtected)
        {
            if (saltHex is not null || hashHex is not null)
            {
                throw new InvalidOperationException(
                    "Password salt/hash options require --lobby-privacy password.");
            }

            return null;
        }

        if (saltHex is null || saltHex.Length != 32 ||
            hashHex is null || hashHex.Length != 64)
        {
            throw new InvalidOperationException(
                "Password-protected lobbies require a 16-byte lowercase-hex salt and " +
                "32-byte lowercase-hex PBKDF2-SHA256 hash.");
        }

        return new LobbyPasswordOptions(saltHex, hashHex);
    }

    private static string NormalizeDirectoryUrl(string? value)
    {
        value = string.IsNullOrWhiteSpace(value) ? DefaultDirectoryBaseUrl : value.Trim();
        if (!Uri.TryCreate(value, UriKind.Absolute, out var uri) ||
            (!string.Equals(uri.Scheme, Uri.UriSchemeHttps, StringComparison.OrdinalIgnoreCase) &&
             !(string.Equals(uri.Scheme, Uri.UriSchemeHttp, StringComparison.OrdinalIgnoreCase) &&
               uri.IsLoopback)))
        {
            throw new InvalidOperationException(
                "The lobby directory URL must use HTTPS, except localhost development URLs may use HTTP.");
        }

        return uri.GetLeftPart(UriPartial.Authority).TrimEnd('/');
    }

    private static string NormalizePhase(string value) =>
        value.Trim().ToLowerInvariant() switch
        {
            "hub" => "hub",
            "loading" => "loading",
            "session" => "session",
            "results" => "results",
            _ => throw new InvalidOperationException(
                "Lobby phase must be hub, loading, session, or results.")
        };

    private static string? NormalizeSha256(string? value, string label)
    {
        value = NormalizeHex(value);
        if (value is not null && value.Length != 64)
        {
            throw new InvalidOperationException($"{label} must contain 64 lowercase hexadecimal characters.");
        }

        return value;
    }

    private static string? NormalizeHex(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return null;
        }

        value = value.Trim().ToLowerInvariant();
        return HexRegex.IsMatch(value)
            ? value
            : throw new InvalidOperationException("Hexadecimal values may only contain 0-9 and a-f.");
    }

    private static string? NormalizeOptional(string? value, int maxLength, string label)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return null;
        }

        value = value.Trim();
        return value.Length <= maxLength
            ? value
            : throw new InvalidOperationException($"{label} may not exceed {maxLength} characters.");
    }

    private static int? NormalizeOptionalRange(int? value, int minimum, int maximum, string label)
    {
        if (value is null)
        {
            return null;
        }

        return value >= minimum && value <= maximum
            ? value
            : throw new InvalidOperationException($"{label} must be between {minimum} and {maximum}.");
    }
}
