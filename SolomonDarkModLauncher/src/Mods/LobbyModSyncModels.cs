namespace SolomonDarkModLauncher.Mods;

internal sealed record LobbyModSyncResult(
    ModCatalog Catalog,
    int RequiredModCount,
    int ReusedManualModCount,
    int ReusedCachedModCount,
    int DownloadedModCount,
    bool UsedWebsite,
    string? FallbackReason)
{
    public static LobbyModSyncResult Offline(
        ModCatalog localCatalog,
        string reason) =>
        new(localCatalog, 0, 0, 0, 0, UsedWebsite: false, FallbackReason: reason);
}

internal sealed record WebsiteResolvedMod(
    string Id,
    string Version,
    string ContentSha256,
    string PackageSha256,
    string DownloadUrl);
