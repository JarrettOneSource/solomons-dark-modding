namespace SolomonDarkModLauncher.Staging;

internal sealed record MultiplayerCompatibilityStageResult(
    string ManifestPath,
    string FingerprintSha256,
    int ProtocolVersion);
