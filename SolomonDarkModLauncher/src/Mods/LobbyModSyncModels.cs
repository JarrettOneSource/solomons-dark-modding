namespace SolomonDarkModLauncher.Mods;

internal sealed record LobbyModSyncResult(
    ModCatalog Catalog,
    int RequiredModCount,
    int ReusedManualModCount,
    int ReusedCachedModCount,
    int DownloadedModCount,
    int HostDownloadedModCount,
    bool UsedWebsite,
    bool UsedHostTransfer,
    string? FallbackReason,
    LobbyBuildDescriptor? HostBuild = null)
{
    public static LobbyModSyncResult Offline(
        ModCatalog localCatalog,
        string reason) =>
        new(
            localCatalog,
            0,
            0,
            0,
            0,
            0,
            UsedWebsite: false,
            UsedHostTransfer: false,
            FallbackReason: reason);
}

internal sealed record LobbyBuildDescriptor(
    int? ProtocolVersion,
    string? ManifestSha256,
    string? LoaderVersion);

internal enum LobbyJoinPreviewModState
{
    Installed,
    Cached,
    NeedsDownload,
    Unavailable
}

internal enum LobbyJoinPreviewDownloadSource
{
    None,
    Website,
    Host
}

internal sealed record LobbyJoinPreviewMod(
    string Id,
    string Version,
    string ContentSha256,
    LobbyJoinPreviewModState State,
    string? Name,
    string? InstalledVersion,
    long? DownloadSizeBytes,
    LobbyJoinPreviewDownloadSource DownloadSource =
        LobbyJoinPreviewDownloadSource.None)
{
    public string DisplayName => string.IsNullOrWhiteSpace(Name) ? Id : Name!;
}

internal sealed record LobbyJoinPreview(
    ulong LobbyId,
    bool UsedWebsite,
    bool UsedHostTransfer,
    string? Error,
    LobbyBuildDescriptor? HostBuild,
    IReadOnlyList<LobbyJoinPreviewMod> Mods)
{
    public int InstalledCount =>
        Mods.Count(mod => mod.State == LobbyJoinPreviewModState.Installed);

    public int CachedCount =>
        Mods.Count(mod => mod.State == LobbyJoinPreviewModState.Cached);

    public int DownloadCount =>
        Mods.Count(mod => mod.State == LobbyJoinPreviewModState.NeedsDownload);

    public int UnavailableCount =>
        Mods.Count(mod => mod.State == LobbyJoinPreviewModState.Unavailable);

    public static LobbyJoinPreview Unavailable(ulong lobbyId, string error) =>
        new(
            lobbyId,
            UsedWebsite: false,
            UsedHostTransfer: false,
            Error: error,
            HostBuild: null,
            Mods: []);

    public int HostDownloadCount => Mods.Count(mod =>
        mod.State == LobbyJoinPreviewModState.NeedsDownload &&
        mod.DownloadSource == LobbyJoinPreviewDownloadSource.Host);

    public int WebsiteDownloadCount => Mods.Count(mod =>
        mod.State == LobbyJoinPreviewModState.NeedsDownload &&
        mod.DownloadSource == LobbyJoinPreviewDownloadSource.Website);
}

internal sealed record WebsiteResolvedMod(
    string Id,
    string Version,
    string ContentSha256,
    string PackageSha256,
    string DownloadUrl,
    string? Name = null,
    long? FileSizeBytes = null,
    string? MinimumLoaderVersion = null);
