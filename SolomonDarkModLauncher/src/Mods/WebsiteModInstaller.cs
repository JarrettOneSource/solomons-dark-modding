using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using SolomonDarkModding.Updates;
using SolomonDarkModding.Versioning;
using SolomonDarkModLauncher.Target;

namespace SolomonDarkModLauncher.Mods;

internal enum WebsiteModInstallDisposition
{
    Install,
    Update,
    Current,
    NewerInstalled
}

internal sealed record WebsiteModInstallPreview(
    string Slug,
    string Id,
    string Name,
    string Version,
    long FileSizeBytes,
    WebsiteModInstallDisposition Disposition,
    string? InstalledVersion,
    WebsiteResolvedMod Package);

internal sealed record WebsiteModInstallResult(
    WebsiteModInstallPreview Preview,
    bool Changed);

internal static class WebsiteModInstaller
{
    private static readonly TimeSpan MetadataTimeout =
        TimeSpan.FromSeconds(5);
    private static readonly JsonSerializerOptions JsonOptions =
        new(JsonSerializerDefaults.Web);

    public static async Task<WebsiteModInstallPreview> PreviewAsync(
        LauncherConfiguration configuration,
        ModCatalog catalog,
        string slug,
        string directoryBaseUrl,
        CancellationToken cancellationToken = default)
    {
        using var client = CreateClient(directoryBaseUrl);
        return await PreviewAsync(
            catalog,
            slug,
            client,
            cancellationToken);
    }

    public static async Task<WebsiteModInstallResult> InstallAsync(
        LauncherConfiguration configuration,
        ModCatalog catalog,
        string slug,
        string directoryBaseUrl,
        IProgress<UpdateProgress>? progress = null,
        CancellationToken cancellationToken = default)
    {
        using var client = CreateClient(directoryBaseUrl);
        return await InstallAsync(
            catalog,
            configuration.Workspace.ModsRootPath,
            configuration.Workspace.ModCacheRootPath,
            slug,
            client,
            progress,
            cancellationToken);
    }

    internal static async Task<WebsiteModInstallResult> InstallAsync(
        ModCatalog catalog,
        string modsRootPath,
        string cacheRootPath,
        string slug,
        HttpClient client,
        IProgress<UpdateProgress>? progress = null,
        CancellationToken cancellationToken = default)
    {
        var preview = await PreviewAsync(
            catalog,
            slug,
            client,
            cancellationToken);
        if (preview.Disposition is
            WebsiteModInstallDisposition.Current or
            WebsiteModInstallDisposition.NewerInstalled)
        {
            progress?.Report(new UpdateProgress(
                UpdateProgressPhase.Completed,
                preview.Disposition ==
                    WebsiteModInstallDisposition.Current
                    ? $"{preview.Name} v{preview.Version} is already installed."
                    : $"{preview.Name} is not changed because v{preview.InstalledVersion} is newer.",
                1,
                1,
                UpdateProgressUnit.Items));
            return new WebsiteModInstallResult(preview, Changed: false);
        }

        var required = new MultiplayerModDescriptor(
            preview.Id,
            preview.Version,
            preview.Package.ContentSha256);
        var cached = await WebsiteModPackageInstaller.InstallAsync(
            client,
            preview.Package,
            required,
            cacheRootPath,
            cancellationToken,
            progress);
        var current = catalog.DiscoveredMods.SingleOrDefault(mod =>
            string.Equals(
                mod.Manifest.Id,
                preview.Id,
                StringComparison.OrdinalIgnoreCase));
        WebsiteModUpdater.Promote(
            cached,
            current,
            required,
            modsRootPath);
        progress?.Report(new UpdateProgress(
            UpdateProgressPhase.Completed,
            preview.Disposition ==
                WebsiteModInstallDisposition.Update
                ? $"Updated {preview.Name} to v{preview.Version}."
                : $"Installed {preview.Name} v{preview.Version}.",
            1,
            1,
            UpdateProgressUnit.Items));
        return new WebsiteModInstallResult(preview, Changed: true);
    }

    internal static async Task<WebsiteModInstallPreview> PreviewAsync(
        ModCatalog catalog,
        string slug,
        HttpClient client,
        CancellationToken cancellationToken = default)
    {
        if (!IsSafeSlug(slug))
        {
            throw new InvalidOperationException(
                "The install-mod slug is not valid.");
        }

        using var timeout =
            CancellationTokenSource.CreateLinkedTokenSource(
                cancellationToken);
        timeout.CancelAfter(MetadataTimeout);
        HttpResponseMessage response;
        try
        {
            response = await client.GetAsync(
                $"api/mods/{Uri.EscapeDataString(slug)}",
                timeout.Token);
        }
        catch (OperationCanceledException)
            when (!cancellationToken.IsCancellationRequested)
        {
            throw new InvalidOperationException(
                $"The website did not answer the request for '{slug}' within {MetadataTimeout.TotalSeconds:0} seconds.");
        }
        using var responseScope = response;
        if (response.StatusCode == HttpStatusCode.NotFound)
        {
            throw new InvalidOperationException(
                $"The website does not know a mod named '{slug}'.");
        }
        if (!response.IsSuccessStatusCode)
        {
            throw new InvalidOperationException(
                $"The website could not resolve '{slug}' " +
                $"(HTTP {(int)response.StatusCode}).");
        }

        var detail = await response.Content.ReadFromJsonAsync<ModDetail>(
                JsonOptions,
                timeout.Token)
            ?? throw new InvalidDataException(
                "The website returned an empty mod record.");
        if (!string.Equals(
                detail.Slug,
                slug,
                StringComparison.Ordinal) ||
            string.IsNullOrWhiteSpace(detail.Name) ||
            !IsValidModId(detail.LauncherModId) ||
            detail.Versions is null)
        {
            throw new InvalidDataException(
                "The website returned invalid mod metadata.");
        }

        ModVersion? selected = null;
        SemanticVersion? selectedVersion = null;
        foreach (var candidate in detail.Versions)
        {
            if (candidate.Id <= 0 ||
                !SemanticVersion.TryParse(
                    candidate.ManifestVersion,
                    out var version) ||
                !IsSha256(candidate.ContentSha256) ||
                !IsSha256(candidate.PackageSha256) ||
                candidate.FileSize is < 1 or > 100L * 1024 * 1024)
            {
                continue;
            }
            if (selectedVersion is null ||
                version!.CompareTo(selectedVersion) > 0 ||
                version.CompareTo(selectedVersion) == 0 &&
                candidate.Id > selected!.Id)
            {
                selected = candidate;
                selectedVersion = version;
            }
        }
        if (selected is null)
        {
            throw new InvalidOperationException(
                $"{detail.Name} has no launcher-compatible package.");
        }

        var id = detail.LauncherModId!;
        var installed = catalog.DiscoveredMods.SingleOrDefault(mod =>
            string.Equals(
                mod.Manifest.Id,
                id,
                StringComparison.OrdinalIgnoreCase));
        var disposition = WebsiteModInstallDisposition.Install;
        if (installed is not null)
        {
            if (!SemanticVersion.TryParse(
                    installed.Manifest.Version,
                    out var installedVersion))
            {
                throw new InvalidOperationException(
                    $"Installed mod {id} has a non-semantic version.");
            }
            var comparison =
                installedVersion!.CompareTo(selectedVersion);
            disposition = comparison > 0
                ? WebsiteModInstallDisposition.NewerInstalled
                : comparison < 0
                    ? WebsiteModInstallDisposition.Update
                    : string.Equals(
                        ModContentHasher.HashDirectory(
                            installed.RootPath),
                        selected.ContentSha256,
                        StringComparison.OrdinalIgnoreCase)
                        ? WebsiteModInstallDisposition.Current
                        : WebsiteModInstallDisposition.Update;
        }

        var resolved = new WebsiteResolvedMod(
            id,
            selected.ManifestVersion!,
            selected.ContentSha256!.ToLowerInvariant(),
            selected.PackageSha256!.ToLowerInvariant(),
            $"api/mods/{Uri.EscapeDataString(slug)}/versions/{selected.Id}/download",
            detail.Name,
            selected.FileSize);
        return new WebsiteModInstallPreview(
            slug,
            id,
            detail.Name,
            selected.ManifestVersion!,
            selected.FileSize,
            disposition,
            installed?.Manifest.Version,
            resolved);
    }

    private static HttpClient CreateClient(string directoryBaseUrl) =>
        new()
        {
            BaseAddress = new Uri(
                directoryBaseUrl.TrimEnd('/') + "/"),
            Timeout = TimeSpan.FromMinutes(5)
        };

    private static bool IsSafeSlug(string value) =>
        value.Length is >= 1 and <= 80 &&
        value[0] is >= 'a' and <= 'z' or >= '0' and <= '9' &&
        value[^1] is >= 'a' and <= 'z' or >= '0' and <= '9' &&
        !value.Contains("--", StringComparison.Ordinal) &&
        value.All(character =>
            character is >= 'a' and <= 'z' or
                >= '0' and <= '9' or '-');

    private static bool IsValidModId(string? value) =>
        value is { Length: >= 1 and <= 128 } &&
        char.IsAsciiLetterOrDigit(value[0]) &&
        value.All(character =>
            char.IsAsciiLetterOrDigit(character) ||
            character is '.' or '_' or '-');

    private static bool IsSha256(string? value) =>
        value is { Length: 64 } &&
        value.All(character =>
            character is >= '0' and <= '9' or
                >= 'a' and <= 'f' or
                >= 'A' and <= 'F');

    private sealed record ModDetail(
        string? Slug,
        string? Name,
        string? LauncherModId,
        ModVersion[]? Versions);

    private sealed record ModVersion(
        int Id,
        string? ManifestVersion,
        string? PackageSha256,
        string? ContentSha256,
        long FileSize);
}
