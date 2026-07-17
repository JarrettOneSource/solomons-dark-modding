namespace SolomonDarkModLauncher.UI.Infrastructure;

/// <summary>
/// Non-default host lobby settings passed through to the CLI's
/// --lobby-privacy / --lobby-password-* contract (protocol 60). Null options
/// mean the contract default: a Friends Only lobby with no extra arguments.
/// Password material is already PBKDF2-derived — never the plaintext.
/// </summary>
internal sealed record LauncherHostOptions(
    string Privacy,
    string? PasswordSaltHex,
    string? PasswordHashHex);
