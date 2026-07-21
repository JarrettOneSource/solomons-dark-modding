using System.Net.Http.Json;
using System.Text.Json;
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
        CancellationToken cancellationToken = default)
    {
        using var client = new HttpClient
        {
            BaseAddress = new Uri(directoryBaseUrl.TrimEnd('/') + "/"),
            Timeout = TimeSpan.FromMinutes(5)
        };

        return await SynchronizeAsync(
            localCatalog,
            lobbyId,
            ticket,
            configuration.Workspace.ModCacheRootPath,
            client,
            cancellationToken);
    }

    internal static async Task<LobbyModSyncResult> SynchronizeAsync(
        ModCatalog localCatalog,
        ulong lobbyId,
        string? ticket,
        string cacheRootPath,
        HttpClient client,
        CancellationToken cancellationToken = default)
    {

        var manifest = await TryFetchRequiredModsAsync(
            client,
            lobbyId,
            ticket,
            cancellationToken);
        if (manifest.Mods is null)
        {
            return LobbyModSyncResult.Offline(localCatalog, manifest.Error!);
        }

        var required = manifest.Mods;
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
            foreach (var requirement in missing)
            {
                if (!resolved.TryGetValue(requirement.Id, out var package))
                {
                    throw new InvalidOperationException(
                        $"Host mod {requirement.Id} {requirement.Version} is not installed locally " +
                        "and that exact version is not available from the website.");
                }

                var installed = await WebsiteModPackageInstaller.InstallAsync(
                    client,
                    package,
                    requirement,
                    cacheRootPath,
                    cancellationToken);
                exactMods.Add(requirement.Id, installed);
                downloaded++;
            }
        }

        var ordered = required.Select(requirement => exactMods[requirement.Id]).ToArray();
        return new LobbyModSyncResult(
            ModCatalog.CreateExact(ordered),
            required.Count,
            reusedManual,
            reusedCached,
            downloaded,
            UsedWebsite: true,
            FallbackReason: null);
    }

    private static async Task<JoinManifestFetchResult> TryFetchRequiredModsAsync(
        HttpClient client,
        ulong lobbyId,
        string? ticket,
        CancellationToken cancellationToken)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(JoinManifestTimeout);
        try
        {
            var mods = await FetchRequiredModsAsync(
                client,
                lobbyId,
                ticket,
                timeout.Token);
            return new JoinManifestFetchResult(mods, Error: null);
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            return new JoinManifestFetchResult(
                Mods: null,
                $"The website did not provide lobby metadata within {JoinManifestTimeout.TotalSeconds:0} seconds.");
        }
        catch (Exception exception) when (exception is
            HttpRequestException or
            InvalidDataException or
            InvalidOperationException or
            JsonException)
        {
            return new JoinManifestFetchResult(Mods: null, exception.Message);
        }
    }

    private static async Task<IReadOnlyList<MultiplayerModDescriptor>> FetchRequiredModsAsync(
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

        return required;
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
                        mod.DownloadUrl)))
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

    private sealed record JoinManifestResponse(string? LobbyId, ApiModDescriptor[]? Mods);
    private sealed record JoinManifestFetchResult(
        IReadOnlyList<MultiplayerModDescriptor>? Mods,
        string? Error);
    private sealed record ApiModDescriptor(string? Id, string? Version, string? ContentSha256);
    private sealed record ResolveRequest(ResolveModRequest[] Mods);
    private sealed record ResolveModRequest(string Id, string Version, string ContentSha256);
    private sealed record ResolveResponse(ResolvedModResponse[]? Mods, ApiModDescriptor[]? Missing);
    private sealed record ResolvedModResponse(
        string? Id,
        string? Version,
        string? ContentSha256,
        string? PackageSha256,
        string? DownloadUrl);
}
