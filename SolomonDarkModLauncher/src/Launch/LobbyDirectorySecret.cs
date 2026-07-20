using System.Security.Cryptography;

namespace SolomonDarkModLauncher.Launch;

internal static class LobbyDirectorySecret
{
    public const int HexLength = 64;

    public static string Create() =>
        Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant();

    public static bool IsValid(string? value) =>
        value is { Length: HexLength } && value.All(character =>
            character is >= '0' and <= '9' or >= 'a' and <= 'f');
}
