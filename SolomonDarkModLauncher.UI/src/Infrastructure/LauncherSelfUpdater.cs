using System.Diagnostics;
using System.IO.Compression;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text.Json;
using SolomonDarkModding.Distribution;
using SolomonDarkModding.Versioning;

namespace SolomonDarkModLauncher.UI.Infrastructure;

internal static class LauncherSelfUpdater
{
    private const string ReleasesUrl =
        "https://api.github.com/repos/JarrettOneSource/solomons-dark-modding/releases?per_page=100";
    private const long MaximumArchiveBytes = 512L * 1024L * 1024L;

    public static async Task<bool> CheckAndStartAsync(
        string currentVersionText,
        string activationArgument,
        Action<string> updateFound)
    {
        if (!TryFindPortableRoot(out var portableRoot, out var launcherPath) ||
            !SemanticVersion.TryParse(currentVersionText, out var currentVersion))
        {
            return false;
        }

        var updatesRoot = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "SolomonDarkMultiplayerBeta",
            "updates");
        CleanUpdateCache(updatesRoot);

        LauncherRelease? release;
        try
        {
            using var metadataCancellation = new CancellationTokenSource(TimeSpan.FromSeconds(5));
            using var client = CreateClient();
            var json = await client.GetStringAsync(ReleasesUrl, metadataCancellation.Token);
            release = SelectUpdate(json, currentVersion!);
        }
        catch (Exception exception) when (exception is HttpRequestException or
                                          TaskCanceledException or
                                          JsonException)
        {
            return false;
        }

        if (release is null)
        {
            return false;
        }

        updateFound(release.Version.Value);
        var updateDirectory = Path.Combine(updatesRoot, release.Version.Value);
        Directory.CreateDirectory(updateDirectory);

        var archivePath = Path.Combine(updateDirectory, release.AssetName);
        var temporaryUpdaterPath = Path.Combine(
            updateDirectory,
            DistributionLayout.UpdaterExecutableName);
        using (var client = CreateClient())
        using (var downloadCancellation = new CancellationTokenSource(TimeSpan.FromMinutes(10)))
        using (var response = await client.GetAsync(
                   release.DownloadUrl,
                   HttpCompletionOption.ResponseHeadersRead,
                   downloadCancellation.Token))
        {
            response.EnsureSuccessStatusCode();
            if (response.Content.Headers.ContentLength > MaximumArchiveBytes)
            {
                throw new InvalidDataException("The launcher update is larger than expected.");
            }

            await using var input = await response.Content.ReadAsStreamAsync(
                downloadCancellation.Token);
            await using var output = new FileStream(
                archivePath,
                FileMode.Create,
                FileAccess.Write,
                FileShare.None);
            var buffer = new byte[128 * 1024];
            long downloadedBytes = 0;
            while (true)
            {
                var count = await input.ReadAsync(buffer, downloadCancellation.Token);
                if (count == 0)
                {
                    break;
                }
                downloadedBytes += count;
                if (downloadedBytes > MaximumArchiveBytes)
                {
                    throw new InvalidDataException("The launcher update is larger than expected.");
                }
                await output.WriteAsync(buffer.AsMemory(0, count), downloadCancellation.Token);
            }
        }

        using (var archive = ZipFile.OpenRead(archivePath))
        {
            if (archive.Entries.Count == 0)
            {
                throw new InvalidDataException("The downloaded launcher update is empty.");
            }
        }

        var packagedUpdaterPath = Path.Combine(
            portableRoot,
            DistributionLayout.UpdaterExecutableName);
        File.Copy(packagedUpdaterPath, temporaryUpdaterPath, overwrite: true);

        var startInfo = new ProcessStartInfo(temporaryUpdaterPath)
        {
            WorkingDirectory = updateDirectory,
            UseShellExecute = false,
            CreateNoWindow = true
        };
        startInfo.ArgumentList.Add("--wait-pid");
        startInfo.ArgumentList.Add(Environment.ProcessId.ToString());
        startInfo.ArgumentList.Add("--archive");
        startInfo.ArgumentList.Add(archivePath);
        startInfo.ArgumentList.Add("--target");
        startInfo.ArgumentList.Add(portableRoot);
        startInfo.ArgumentList.Add("--restart");
        startInfo.ArgumentList.Add(Path.GetFileName(launcherPath));
        if (!string.IsNullOrEmpty(activationArgument))
        {
            startInfo.ArgumentList.Add("--activation");
            startInfo.ArgumentList.Add(activationArgument);
        }

        if (Process.Start(startInfo) is null)
        {
            throw new InvalidOperationException("The launcher updater did not start.");
        }
        return true;
    }

    internal static LauncherRelease? SelectUpdate(
        string releasesJson,
        SemanticVersion currentVersion)
    {
        using var document = JsonDocument.Parse(releasesJson);
        LauncherRelease? selected = null;
        foreach (var releaseElement in document.RootElement.EnumerateArray())
        {
            if (releaseElement.GetProperty("draft").GetBoolean())
            {
                continue;
            }

            var tagName = releaseElement.GetProperty("tag_name").GetString();
            if (tagName is null ||
                !tagName.StartsWith('v') ||
                !SemanticVersion.TryParse(tagName[1..], out var version) ||
                version!.CompareTo(currentVersion) <= 0)
            {
                continue;
            }

            var expectedAssetName =
                $"SolomonDarkMultiplayerBeta-v{version.Value}.zip";
            foreach (var assetElement in releaseElement.GetProperty("assets").EnumerateArray())
            {
                if (!string.Equals(
                        assetElement.GetProperty("name").GetString(),
                        expectedAssetName,
                        StringComparison.Ordinal))
                {
                    continue;
                }

                var downloadUrl = assetElement
                    .GetProperty("browser_download_url")
                    .GetString();
                if (!Uri.TryCreate(downloadUrl, UriKind.Absolute, out var uri) ||
                    uri.Scheme != Uri.UriSchemeHttps)
                {
                    continue;
                }

                var candidate = new LauncherRelease(
                    version,
                    expectedAssetName,
                    uri.AbsoluteUri);
                if (selected is null ||
                    candidate.Version.CompareTo(selected.Version) > 0)
                {
                    selected = candidate;
                }
            }
        }
        return selected;
    }

    private static bool TryFindPortableRoot(
        out string portableRoot,
        out string launcherPath)
    {
        launcherPath = Environment.ProcessPath ?? string.Empty;
        portableRoot = Path.GetDirectoryName(launcherPath) ?? string.Empty;
        return launcherPath.Length > 0 &&
               File.Exists(Path.Combine(
                   portableRoot,
                   DistributionLayout.PortableRootMarkerFileName)) &&
               File.Exists(Path.Combine(
                   portableRoot,
                   DistributionLayout.DistributionFilesManifestFileName)) &&
               File.Exists(Path.Combine(
                   portableRoot,
                   DistributionLayout.UpdaterExecutableName));
    }

    private static HttpClient CreateClient()
    {
        var client = new HttpClient();
        client.DefaultRequestHeaders.UserAgent.Add(
            new ProductInfoHeaderValue("SolomonDarkMultiplayerBeta", "1"));
        client.DefaultRequestHeaders.Accept.Add(
            new MediaTypeWithQualityHeaderValue("application/vnd.github+json"));
        client.DefaultRequestHeaders.Add("X-GitHub-Api-Version", "2022-11-28");
        return client;
    }

    private static void CleanUpdateCache(string updatesRoot)
    {
        if (!Directory.Exists(updatesRoot))
        {
            return;
        }

        foreach (var directory in Directory.EnumerateDirectories(updatesRoot))
        {
            try
            {
                Directory.Delete(directory, recursive: true);
            }
            catch (IOException)
            {
            }
            catch (UnauthorizedAccessException)
            {
            }
        }
    }
}

internal sealed record LauncherRelease(
    SemanticVersion Version,
    string AssetName,
    string DownloadUrl);
