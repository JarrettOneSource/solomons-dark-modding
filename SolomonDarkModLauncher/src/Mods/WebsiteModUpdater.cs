using System.Net.Http.Json;
using System.Text.Json;
using SolomonDarkModding.Versioning;
using SolomonDarkModding.Updates;
using SolomonDarkModLauncher.Target;

namespace SolomonDarkModLauncher.Mods;

internal sealed record ModUpdate(
    string Id,
    string PreviousVersion,
    string Version);

internal sealed record WebsiteModUpdateResult(
    int CheckedModCount,
    IReadOnlyList<ModUpdate> Updates,
    string? Error)
{
    public int UpdatedModCount => Updates.Count;
}

internal static class WebsiteModUpdater
{
    private const string UpdatePrefix = ".sdmod-update-";
    private const string BackupPrefix = ".sdmod-backup-";
    private static readonly TimeSpan UpdateMetadataTimeout = TimeSpan.FromSeconds(5);
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);

    public static async Task<WebsiteModUpdateResult> UpdateAsync(
        LauncherConfiguration configuration,
        ModCatalog catalog,
        string directoryBaseUrl,
        IProgress<UpdateProgress>? progress = null,
        CancellationToken cancellationToken = default)
    {
        using var client = new HttpClient
        {
            BaseAddress = new Uri(directoryBaseUrl.TrimEnd('/') + "/"),
            Timeout = TimeSpan.FromMinutes(5)
        };
        return await UpdateAsync(
            catalog,
            configuration.Workspace.ModsRootPath,
            configuration.Workspace.ModCacheRootPath,
            client,
            progress,
            cancellationToken);
    }

    internal static async Task<WebsiteModUpdateResult> UpdateAsync(
        ModCatalog catalog,
        string modsRootPath,
        string cacheRootPath,
        HttpClient client,
        IProgress<UpdateProgress>? progress = null,
        CancellationToken cancellationToken = default)
    {
        var installed = catalog.DiscoveredMods
            .ToDictionary(mod => mod.Manifest.Id, StringComparer.OrdinalIgnoreCase);
        if (installed.Count == 0)
        {
            return new WebsiteModUpdateResult(0, [], Error: null);
        }

        progress?.Report(new UpdateProgress(
            UpdateProgressPhase.Checking,
            installed.Count == 1
                ? "Checking 1 installed mod for updates…"
                : $"Checking {installed.Count} installed mods for updates…",
            0,
            installed.Count,
            UpdateProgressUnit.Items));
        IReadOnlyList<WebsiteResolvedMod> available;
        try
        {
            available = await FetchUpdatesAsync(client, installed, cancellationToken);
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            var message =
                $"The website did not answer the mod update check within {UpdateMetadataTimeout.TotalSeconds:0} seconds.";
            progress?.Report(new UpdateProgress(
                UpdateProgressPhase.Failed,
                $"Mod update failed: {message}"));
            return new WebsiteModUpdateResult(
                installed.Count,
                [],
                message);
        }
        catch (Exception exception) when (exception is
            HttpRequestException or
            InvalidDataException or
            InvalidOperationException or
            JsonException)
        {
            progress?.Report(new UpdateProgress(
                UpdateProgressPhase.Failed,
                $"Mod update failed: {exception.Message}"));
            return new WebsiteModUpdateResult(installed.Count, [], exception.Message);
        }

        progress?.Report(new UpdateProgress(
            UpdateProgressPhase.Checking,
            available.Count == 0
                ? "Installed mods are up to date."
                : available.Count == 1
                    ? "1 mod update is available."
                    : $"{available.Count} mod updates are available.",
            installed.Count,
            installed.Count,
            UpdateProgressUnit.Items));
        if (available.Count == 0)
        {
            progress?.Report(new UpdateProgress(
                UpdateProgressPhase.Completed,
                "Installed mods are up to date.",
                installed.Count,
                installed.Count,
                UpdateProgressUnit.Items));
            return new WebsiteModUpdateResult(installed.Count, [], Error: null);
        }

        var updates = new List<ModUpdate>();
        for (var index = 0; index < available.Count; index++)
        {
            var resolved = available[index];
            var current = installed[resolved.Id];
            var required = new MultiplayerModDescriptor(
                resolved.Id,
                resolved.Version,
                resolved.ContentSha256);
            try
            {
                var cached = await WebsiteModPackageInstaller.InstallAsync(
                    client,
                    resolved,
                    required,
                    cacheRootPath,
                    cancellationToken,
                    progress);
                progress?.Report(new UpdateProgress(
                    UpdateProgressPhase.Installing,
                    $"Replacing {resolved.Id} v{current.Manifest.Version} with v{resolved.Version}…",
                    index,
                    available.Count,
                    UpdateProgressUnit.Items));
                Promote(cached, current, required, modsRootPath);
                updates.Add(new ModUpdate(
                    resolved.Id,
                    current.Manifest.Version,
                    resolved.Version));
                progress?.Report(new UpdateProgress(
                    UpdateProgressPhase.Installing,
                    $"Installed {resolved.Id} v{resolved.Version}.",
                    index + 1,
                    available.Count,
                    UpdateProgressUnit.Items));
            }
            catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
            {
                var message = $"The website did not finish downloading {resolved.Id}.";
                progress?.Report(new UpdateProgress(
                    UpdateProgressPhase.Failed,
                    $"Mod update failed: {message}"));
                return new WebsiteModUpdateResult(
                    installed.Count,
                    updates,
                    message);
            }
            catch (Exception exception) when (exception is
                HttpRequestException or
                InvalidDataException or
                InvalidOperationException or
                IOException or
                UnauthorizedAccessException or
                JsonException)
            {
                progress?.Report(new UpdateProgress(
                    UpdateProgressPhase.Failed,
                    $"Mod update failed: {exception.Message}"));
                return new WebsiteModUpdateResult(installed.Count, updates, exception.Message);
            }
        }

        progress?.Report(new UpdateProgress(
            UpdateProgressPhase.Completed,
            updates.Count == 1
                ? $"Updated {updates[0].Id} to v{updates[0].Version}."
                : $"Updated {updates.Count} mods.",
            updates.Count,
            updates.Count,
            UpdateProgressUnit.Items));
        return new WebsiteModUpdateResult(installed.Count, updates, Error: null);
    }

    public static void RecoverTransactions(string modsRootPath)
    {
        if (!Directory.Exists(modsRootPath))
        {
            return;
        }

        foreach (var path in Directory.EnumerateDirectories(
                     modsRootPath,
                     $"{UpdatePrefix}*",
                     SearchOption.TopDirectoryOnly))
        {
            Directory.Delete(path, recursive: true);
        }

        foreach (var backupPath in Directory.EnumerateDirectories(
                     modsRootPath,
                     $"{BackupPrefix}*",
                     SearchOption.TopDirectoryOnly))
        {
            var folderName = Path.GetFileName(backupPath)[BackupPrefix.Length..];
            var targetPath = Path.Combine(modsRootPath, folderName);
            if (Directory.Exists(targetPath))
            {
                Directory.Delete(backupPath, recursive: true);
            }
            else
            {
                Directory.Move(backupPath, targetPath);
            }
        }
    }

    private static async Task<IReadOnlyList<WebsiteResolvedMod>> FetchUpdatesAsync(
        HttpClient client,
        IReadOnlyDictionary<string, DiscoveredMod> installed,
        CancellationToken cancellationToken)
    {
        var request = new UpdateRequest(installed.Values
            .Select(mod => new InstalledModRequest(
                mod.Manifest.Id,
                mod.Manifest.Version))
            .ToArray());
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(UpdateMetadataTimeout);
        using var response = await client.PostAsJsonAsync(
            "api/mods/updates",
            request,
            JsonOptions,
            timeout.Token);
        if (!response.IsSuccessStatusCode)
        {
            throw new InvalidOperationException(
                $"The website could not check mod updates (HTTP {(int)response.StatusCode}).");
        }

        var result = await response.Content.ReadFromJsonAsync<UpdateResponse>(
                JsonOptions,
                timeout.Token)
            ?? throw new InvalidDataException("The website returned an empty mod update response.");
        if (result.Updates is null || result.Updates.Length > installed.Count)
        {
            throw new InvalidDataException("The website returned invalid mod update metadata.");
        }

        var updates = new List<WebsiteResolvedMod>(result.Updates.Length);
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var update in result.Updates)
        {
            if (string.IsNullOrWhiteSpace(update.Id) ||
                !installed.TryGetValue(update.Id, out var current) ||
                !seen.Add(update.Id) ||
                !SemanticVersion.TryParse(current.Manifest.Version, out var currentVersion) ||
                !SemanticVersion.TryParse(update.Version, out var availableVersion) ||
                availableVersion!.CompareTo(currentVersion) <= 0 ||
                !IsSha256(update.ContentSha256) ||
                !IsSha256(update.PackageSha256) ||
                string.IsNullOrWhiteSpace(update.DownloadUrl))
            {
                throw new InvalidDataException("The website returned an invalid mod update.");
            }

            updates.Add(new WebsiteResolvedMod(
                update.Id,
                update.Version!,
                update.ContentSha256!.ToLowerInvariant(),
                update.PackageSha256!.ToLowerInvariant(),
                update.DownloadUrl));
        }

        return updates;
    }

    private static void Promote(
        DiscoveredMod cached,
        DiscoveredMod current,
        MultiplayerModDescriptor required,
        string modsRootPath)
    {
        var normalizedModsRoot = Path.GetFullPath(modsRootPath);
        var targetPath = Path.GetFullPath(current.RootPath);
        if (!string.Equals(
                Path.GetDirectoryName(targetPath),
                normalizedModsRoot,
                StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException(
                $"Installed mod is outside the managed mods directory: {current.Manifest.Id}");
        }

        var folderName = Path.GetFileName(targetPath);
        var updatePath = Path.Combine(normalizedModsRoot, UpdatePrefix + folderName);
        var backupPath = Path.Combine(normalizedModsRoot, BackupPrefix + folderName);
        RecoverTransactions(normalizedModsRoot);
        CopyDirectory(cached.RootPath, updatePath);

        try
        {
            var staged = ModDiscovery.DiscoverRoot(updatePath);
            if (!string.Equals(staged.Manifest.Id, required.Id, StringComparison.OrdinalIgnoreCase) ||
                !string.Equals(staged.Manifest.Version, required.Version, StringComparison.Ordinal) ||
                !string.Equals(
                    ModContentHasher.HashDirectory(updatePath),
                    required.ContentSha256,
                    StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidDataException(
                    $"The staged update for {required.Id} did not match the website package.");
            }

            Directory.Move(targetPath, backupPath);
            try
            {
                Directory.Move(updatePath, targetPath);
            }
            catch
            {
                Directory.Move(backupPath, targetPath);
                throw;
            }

            Directory.Delete(backupPath, recursive: true);
        }
        finally
        {
            if (Directory.Exists(updatePath))
            {
                Directory.Delete(updatePath, recursive: true);
            }
        }
    }

    private static void CopyDirectory(string sourcePath, string destinationPath)
    {
        Directory.CreateDirectory(destinationPath);
        foreach (var directoryPath in Directory.EnumerateDirectories(
                     sourcePath,
                     "*",
                     SearchOption.AllDirectories))
        {
            Directory.CreateDirectory(Path.Combine(
                destinationPath,
                Path.GetRelativePath(sourcePath, directoryPath)));
        }
        foreach (var filePath in Directory.EnumerateFiles(
                     sourcePath,
                     "*",
                     SearchOption.AllDirectories))
        {
            var destinationFilePath = Path.Combine(
                destinationPath,
                Path.GetRelativePath(sourcePath, filePath));
            Directory.CreateDirectory(Path.GetDirectoryName(destinationFilePath)!);
            File.Copy(filePath, destinationFilePath);
        }
    }

    private static bool IsSha256(string? value) =>
        value is { Length: 64 } && value.All(character =>
            character is >= '0' and <= '9' or >= 'a' and <= 'f' or >= 'A' and <= 'F');

    private sealed record UpdateRequest(InstalledModRequest[] Mods);
    private sealed record InstalledModRequest(string Id, string Version);
    private sealed record UpdateResponse(UpdateResponseItem[]? Updates);
    private sealed record UpdateResponseItem(
        string? Id,
        string? Version,
        string? ContentSha256,
        string? PackageSha256,
        string? DownloadUrl);
}
