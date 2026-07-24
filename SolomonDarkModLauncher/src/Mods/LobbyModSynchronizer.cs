using System.Net.Http.Json;
using System.Text.Json;
using SolomonDarkModding.Updates;
using SolomonDarkModLauncher.Target;

namespace SolomonDarkModLauncher.Mods;

internal static class LobbyModSynchronizer
{
    private static readonly TimeSpan JoinManifestTimeout = TimeSpan.FromSeconds(5);
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);

    public static async Task<LobbyModSyncResult> SynchronizeAsync(
        LauncherConfiguration configuration,
        ModCatalog localCatalog,
        ulong lobbyId,
        string directoryBaseUrl,
        string? ticket,
        IProgress<UpdateProgress>? progress = null,
        CancellationToken cancellationToken = default)
    {
        using var client = CreateClient(directoryBaseUrl);
        return await SynchronizeAsync(
            localCatalog,
            lobbyId,
            ticket,
            configuration.Workspace.ModCacheRootPath,
            client,
            progress,
            cancellationToken);
    }

    internal static async Task<LobbyModSyncResult> SynchronizeAsync(
        ModCatalog localCatalog,
        ulong lobbyId,
        string? ticket,
        string cacheRootPath,
        HttpClient client,
        IProgress<UpdateProgress>? progress = null,
        CancellationToken cancellationToken = default)
    {
        progress?.Report(new UpdateProgress(
            UpdateProgressPhase.Checking,
            "Checking the host's mod packages…"));
        var manifest = await TryFetchJoinManifestAsync(
            client,
            lobbyId,
            ticket,
            cancellationToken);
        if (manifest.Mods is null)
        {
            progress?.Report(new UpdateProgress(
                UpdateProgressPhase.Failed,
                $"Host mod sync failed: {manifest.Error}"));
            return LobbyModSyncResult.Offline(localCatalog, manifest.Error!);
        }

        var required = manifest.Mods;
        progress?.Report(new UpdateProgress(
            UpdateProgressPhase.Checking,
            required.Count == 1
                ? "Checking 1 required host mod…"
                : $"Checking {required.Count} required host mods…",
            0,
            required.Count,
            UpdateProgressUnit.Items));
        var exactMods = new Dictionary<string, DiscoveredMod>(StringComparer.OrdinalIgnoreCase);
        var reusedManual = 0;
        var reusedCached = 0;
        var downloaded = 0;

        foreach (var requirement in required)
        {
            var manual = FindExact(localCatalog.DiscoveredMods, requirement);
            if (manual is not null)
            {
                exactMods.Add(requirement.Id, manual);
                reusedManual++;
                continue;
            }

            var cachePath = WebsiteModPackageInstaller.GetCachePath(
                cacheRootPath,
                requirement);
            var cached = WebsiteModPackageInstaller.TryLoadExact(cachePath, requirement);
            if (cached is not null)
            {
                exactMods.Add(requirement.Id, cached);
                reusedCached++;
            }
        }

        var missing = required
            .Where(requirement => !exactMods.ContainsKey(requirement.Id))
            .ToArray();
        if (missing.Length > 0)
        {
            var resolved = await ResolveAsync(client, missing, cancellationToken);
            var unavailable = missing
                .Where(requirement => !resolved.ContainsKey(requirement.Id))
                .ToArray();
            if (unavailable.Length > 0)
            {
                progress?.Report(new UpdateProgress(
                    UpdateProgressPhase.Failed,
                    "Host mod sync failed because a required package is unavailable."));
                throw new InvalidOperationException(
                    "Mod list mismatch that cannot be repaired automatically: the host has " +
                    $"{Describe(unavailable)} enabled, but " +
                    (unavailable.Length == 1 ? "that exact version is" : "those exact versions are") +
                    " not installed locally and not available from the website. " +
                    "Ask the host to publish the missing mods or disable them before you join.");
            }

            for (var index = 0; index < missing.Length; index++)
            {
                var requirement = missing[index];
                var installed = await WebsiteModPackageInstaller.InstallAsync(
                    client,
                    resolved[requirement.Id],
                    requirement,
                    cacheRootPath,
                    cancellationToken,
                    progress);
                exactMods.Add(requirement.Id, installed);
                downloaded++;
                progress?.Report(new UpdateProgress(
                    UpdateProgressPhase.Installing,
                    $"Prepared {requirement.Id} v{requirement.Version} for this session.",
                    index + 1,
                    missing.Length,
                    UpdateProgressUnit.Items));
            }
        }

        var ordered = required.Select(requirement => exactMods[requirement.Id]).ToArray();
        progress?.Report(new UpdateProgress(
            UpdateProgressPhase.Completed,
            downloaded == 0
                ? "Host mods are already available."
                : downloaded == 1
                    ? "Downloaded and verified 1 host mod."
                    : $"Downloaded and verified {downloaded} host mods.",
            required.Count,
            required.Count,
            UpdateProgressUnit.Items));
        return new LobbyModSyncResult(
            ModCatalog.CreateExact(ordered),
            required.Count,
            reusedManual,
            reusedCached,
            downloaded,
            UsedWebsite: true,
            FallbackReason: null,
            HostBuild: manifest.Build);
    }

    public static async Task<LobbyJoinPreview> PreviewAsync(
        LauncherConfiguration configuration,
        ModCatalog localCatalog,
        ulong lobbyId,
        string directoryBaseUrl,
        string? ticket,
        CancellationToken cancellationToken = default)
    {
        using var client = CreateClient(directoryBaseUrl);
        return await PreviewAsync(
            localCatalog,
            lobbyId,
            ticket,
            configuration.Workspace.ModCacheRootPath,
            client,
            cancellationToken);
    }

    internal static async Task<LobbyJoinPreview> PreviewAsync(
        ModCatalog localCatalog,
        ulong lobbyId,
        string? ticket,
        string cacheRootPath,
        HttpClient client,
        CancellationToken cancellationToken = default)
    {
        var manifest = await TryFetchJoinManifestAsync(
            client,
            lobbyId,
            ticket,
            cancellationToken);
        if (manifest.Mods is null)
        {
            return LobbyJoinPreview.Unavailable(lobbyId, manifest.Error!);
        }

        var classified = new List<LobbyJoinPreviewMod>(manifest.Mods.Count);
        var missing = new List<MultiplayerModDescriptor>();
        foreach (var requirement in manifest.Mods)
        {
            var installedDifferently = localCatalog.DiscoveredMods.FirstOrDefault(mod =>
                string.Equals(mod.Manifest.Id, requirement.Id, StringComparison.OrdinalIgnoreCase));
            var installedVersion = installedDifferently?.Manifest.Version;

            var manual = FindExact(localCatalog.DiscoveredMods, requirement);
            if (manual is not null)
            {
                classified.Add(new LobbyJoinPreviewMod(
                    requirement.Id,
                    requirement.Version,
                    requirement.ContentSha256,
                    LobbyJoinPreviewModState.Installed,
                    manual.Manifest.Name,
                    InstalledVersion: null,
                    DownloadSizeBytes: null));
                continue;
            }

            var cachePath = WebsiteModPackageInstaller.GetCachePath(cacheRootPath, requirement);
            var cached = WebsiteModPackageInstaller.TryLoadExact(cachePath, requirement);
            if (cached is not null)
            {
                classified.Add(new LobbyJoinPreviewMod(
                    requirement.Id,
                    requirement.Version,
                    requirement.ContentSha256,
                    LobbyJoinPreviewModState.Cached,
                    cached.Manifest.Name,
                    InstalledVersion: null,
                    DownloadSizeBytes: null));
                continue;
            }

            classified.Add(new LobbyJoinPreviewMod(
                requirement.Id,
                requirement.Version,
                requirement.ContentSha256,
                LobbyJoinPreviewModState.NeedsDownload,
                installedDifferently?.Manifest.Name,
                installedVersion,
                DownloadSizeBytes: null));
            missing.Add(requirement);
        }

        if (missing.Count > 0)
        {
            IReadOnlyDictionary<string, WebsiteResolvedMod> resolved;
            try
            {
                resolved = await ResolveAsync(client, missing, cancellationToken);
            }
            catch (Exception exception) when (exception is
                HttpRequestException or
                InvalidDataException or
                InvalidOperationException or
                JsonException or
                TaskCanceledException)
            {
                return LobbyJoinPreview.Unavailable(lobbyId, exception.Message);
            }

            for (var index = 0; index < classified.Count; index++)
            {
                var mod = classified[index];
                if (mod.State != LobbyJoinPreviewModState.NeedsDownload)
                {
                    continue;
                }

                classified[index] = resolved.TryGetValue(mod.Id, out var package)
                    ? mod with
                    {
                        Name = string.IsNullOrWhiteSpace(package.Name) ? mod.Name : package.Name,
                        DownloadSizeBytes = package.FileSizeBytes
                    }
                    : mod with { State = LobbyJoinPreviewModState.Unavailable };
            }
        }

        return new LobbyJoinPreview(
            lobbyId,
            UsedWebsite: true,
            Error: null,
            manifest.Build,
            classified);
    }

    private static HttpClient CreateClient(string directoryBaseUrl) => new()
    {
        BaseAddress = new Uri(directoryBaseUrl.TrimEnd('/') + "/"),
        Timeout = TimeSpan.FromMinutes(5)
    };

    private static string Describe(IReadOnlyList<MultiplayerModDescriptor> mods) =>
        string.Join(", ", mods.Select(mod => $"{mod.Id} {mod.Version}"));

    private static async Task<JoinManifestFetchResult> TryFetchJoinManifestAsync(
        HttpClient client,
        ulong lobbyId,
        string? ticket,
        CancellationToken cancellationToken)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(JoinManifestTimeout);
        try
        {
            return await FetchJoinManifestAsync(
                client,
                lobbyId,
                ticket,
                timeout.Token);
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            return new JoinManifestFetchResult(
                Mods: null,
                Build: null,
                $"The website did not provide lobby metadata within {JoinManifestTimeout.TotalSeconds:0} seconds.");
        }
        catch (Exception exception) when (exception is
            HttpRequestException or
            InvalidDataException or
            InvalidOperationException or
            JsonException)
        {
            return new JoinManifestFetchResult(Mods: null, Build: null, exception.Message);
        }
    }

    private static async Task<JoinManifestFetchResult> FetchJoinManifestAsync(
        HttpClient client,
        ulong lobbyId,
        string? ticket,
        CancellationToken cancellationToken)
    {
        var path = $"api/lobbies/{lobbyId}/join-manifest";
        if (!string.IsNullOrWhiteSpace(ticket))
        {
            path += $"?ticket={Uri.EscapeDataString(ticket)}";
        }

        using var response = await client.GetAsync(path, cancellationToken);
        if (!response.IsSuccessStatusCode)
        {
            throw new InvalidOperationException(
                $"Could not read the website mod list for lobby {lobbyId} " +
                $"(HTTP {(int)response.StatusCode}).");
        }

        var manifest = await response.Content.ReadFromJsonAsync<JoinManifestResponse>(
                JsonOptions,
                cancellationToken)
            ?? throw new InvalidDataException("The website returned an empty lobby join manifest.");
        if (!string.Equals(manifest.LobbyId, lobbyId.ToString(), StringComparison.Ordinal) ||
            manifest.Mods is null || manifest.Mods.Length > 128)
        {
            throw new InvalidDataException("The website returned an invalid lobby join manifest.");
        }

        var ids = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var required = new List<MultiplayerModDescriptor>(manifest.Mods.Length);
        foreach (var mod in manifest.Mods)
        {
            if (!IsValidModId(mod.Id) ||
                !IsValidVersion(mod.Version) ||
                !IsSha256(mod.ContentSha256) ||
                !ids.Add(mod.Id!))
            {
                throw new InvalidDataException(
                    "The website returned invalid or duplicate host mod metadata.");
            }

            required.Add(new MultiplayerModDescriptor(
                mod.Id!,
                mod.Version!,
                mod.ContentSha256!.ToLowerInvariant()));
        }

        var build = manifest.Build is null
            ? null
            : new LobbyBuildDescriptor(
                manifest.Build.ProtocolVersion,
                IsSha256(manifest.Build.ManifestSha256)
                    ? manifest.Build.ManifestSha256!.ToLowerInvariant()
                    : null,
                string.IsNullOrWhiteSpace(manifest.Build.LoaderVersion)
                    ? null
                    : manifest.Build.LoaderVersion);

        return new JoinManifestFetchResult(required, build, Error: null);
    }

    private static DiscoveredMod? FindExact(
        IReadOnlyList<DiscoveredMod> candidates,
        MultiplayerModDescriptor required)
    {
        var candidate = candidates.SingleOrDefault(mod =>
            string.Equals(mod.Manifest.Id, required.Id, StringComparison.OrdinalIgnoreCase) &&
            string.Equals(mod.Manifest.Version, required.Version, StringComparison.Ordinal));
        if (candidate is null)
        {
            return null;
        }

        return string.Equals(
            ModContentHasher.HashDirectory(candidate.RootPath),
            required.ContentSha256,
            StringComparison.OrdinalIgnoreCase)
            ? candidate
            : null;
    }

    private static async Task<IReadOnlyDictionary<string, WebsiteResolvedMod>> ResolveAsync(
        HttpClient client,
        IReadOnlyList<MultiplayerModDescriptor> missing,
        CancellationToken cancellationToken)
    {
        var body = new ResolveRequest(missing.Select(mod => new ResolveModRequest(
            mod.Id,
            mod.Version,
            mod.ContentSha256)).ToArray());
        using var response = await client.PostAsJsonAsync(
            "api/mods/resolve",
            body,
            JsonOptions,
            cancellationToken);
        if (!response.IsSuccessStatusCode)
        {
            throw new InvalidOperationException(
                $"The website could not resolve the host's mod packages " +
                $"(HTTP {(int)response.StatusCode}).");
        }

        var result = await response.Content.ReadFromJsonAsync<ResolveResponse>(
                JsonOptions,
                cancellationToken)
            ?? throw new InvalidDataException("The website returned an empty mod resolution response.");
        if (result.Mods is null || result.Missing is null)
        {
            throw new InvalidDataException("The website returned invalid mod resolution metadata.");
        }

        var resolved = new Dictionary<string, WebsiteResolvedMod>(StringComparer.OrdinalIgnoreCase);
        foreach (var mod in result.Mods)
        {
            if (!IsValidModId(mod.Id) ||
                !IsValidVersion(mod.Version) ||
                !IsSha256(mod.ContentSha256) ||
                !IsSha256(mod.PackageSha256) ||
                string.IsNullOrWhiteSpace(mod.DownloadUrl) ||
                !resolved.TryAdd(
                    mod.Id!,
                    new WebsiteResolvedMod(
                        mod.Id!,
                        mod.Version!,
                        mod.ContentSha256!.ToLowerInvariant(),
                        mod.PackageSha256!.ToLowerInvariant(),
                        mod.DownloadUrl,
                        mod.Name,
                        mod.FileSize)))
            {
                throw new InvalidDataException("The website returned invalid resolved mod metadata.");
            }
        }

        return resolved;
    }

    private static bool IsValidModId(string? value) =>
        value is { Length: >= 1 and <= 128 } &&
        char.IsAsciiLetterOrDigit(value[0]) &&
        value.All(character => char.IsAsciiLetterOrDigit(character) || character is '.' or '_' or '-');

    private static bool IsValidVersion(string? value) =>
        value is { Length: >= 1 and <= 64 } &&
        char.IsAsciiLetterOrDigit(value[0]) &&
        value.All(character => char.IsAsciiLetterOrDigit(character) || character is '.' or '_' or '+' or '-');

    private static bool IsSha256(string? value) =>
        value is { Length: 64 } && value.All(character =>
            character is >= '0' and <= '9' or >= 'a' and <= 'f' or >= 'A' and <= 'F');

    private sealed record JoinManifestResponse(
        string? LobbyId,
        ApiModDescriptor[]? Mods,
        ApiBuildDescriptor? Build);
    private sealed record JoinManifestFetchResult(
        IReadOnlyList<MultiplayerModDescriptor>? Mods,
        LobbyBuildDescriptor? Build,
        string? Error);
    private sealed record ApiModDescriptor(string? Id, string? Version, string? ContentSha256);
    private sealed record ApiBuildDescriptor(
        int? ProtocolVersion,
        string? ManifestSha256,
        string? LoaderVersion);
    private sealed record ResolveRequest(ResolveModRequest[] Mods);
    private sealed record ResolveModRequest(string Id, string Version, string ContentSha256);
    private sealed record ResolveResponse(ResolvedModResponse[]? Mods, ApiModDescriptor[]? Missing);
    private sealed record ResolvedModResponse(
        string? Id,
        string? Version,
        string? ContentSha256,
        string? PackageSha256,
        string? DownloadUrl,
        string? Name,
        long? FileSize);
}
