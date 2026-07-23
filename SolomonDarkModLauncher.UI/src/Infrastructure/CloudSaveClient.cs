using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;

namespace SolomonDarkModLauncher.UI.Infrastructure;

internal sealed record CloudSaveRemoteSlot(
    int Slot,
    string? Name,
    long Size,
    long UncompressedSize,
    int FileCount,
    int FormatVersion,
    string Sha256,
    DateTimeOffset UpdatedAtUtc);

internal sealed record CloudSaveAccountState(
    string SteamId,
    SteamLinkedWebsiteAccount? LinkedAccount,
    IReadOnlyList<CloudSaveRemoteSlot> Saves);

internal enum CloudBackupDisposition
{
    Uploaded,
    Unchanged,
    NotLinked,
    Empty
}

internal sealed record CloudBackupResult(
    CloudBackupDisposition Disposition,
    CloudSaveRemoteSlot? RemoteSave);

internal sealed class CloudSaveClient
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true
    };

    private readonly SteamWebsiteSessionClient sessionClient_;
    private readonly LocalSaveCatalog catalog_;

    public CloudSaveClient(
        SteamWebsiteSessionClient sessionClient,
        LocalSaveCatalog catalog)
    {
        sessionClient_ = sessionClient;
        catalog_ = catalog;
    }

    public async Task<CloudSaveAccountState> GetAccountStateAsync(
        string directoryUrl,
        bool forceRefresh = false,
        CancellationToken cancellationToken = default)
    {
        var session = await sessionClient_.GetAsync(
            directoryUrl,
            forceRefresh,
            cancellationToken);
        if (session.LinkedAccount is null)
        {
            return new CloudSaveAccountState(session.SteamId, null, []);
        }

        using var response = await SendAsync(
            directoryUrl,
            session,
            HttpMethod.Get,
            "api/saves",
            content: null,
            cancellationToken);
        var saves = await response.Content.ReadFromJsonAsync<List<CloudSaveRemoteSlot>>(
                        JsonOptions,
                        cancellationToken) ??
                    throw new InvalidOperationException(
                        "The website returned an incomplete cloud-save list.");
        return new CloudSaveAccountState(session.SteamId, session.LinkedAccount, saves);
    }

    public async Task<CloudBackupResult> BackupAsync(
        string directoryUrl,
        int slot,
        CancellationToken cancellationToken = default)
    {
        var save = catalog_.Get(slot);
        if (!save.HasLocalData)
        {
            return new CloudBackupResult(CloudBackupDisposition.Empty, null);
        }

        var session = await sessionClient_.GetAsync(
            directoryUrl,
            cancellationToken: cancellationToken);
        if (session.LinkedAccount is null)
        {
            return new CloudBackupResult(CloudBackupDisposition.NotLinked, null);
        }

        var archive = CloudSaveArchive.Build(save);
        if (string.Equals(
                save.LastBackupFingerprint,
                archive.Sha256,
                StringComparison.OrdinalIgnoreCase))
        {
            return new CloudBackupResult(CloudBackupDisposition.Unchanged, null);
        }

        using var content = new ByteArrayContent(archive.Bytes);
        content.Headers.ContentType = new MediaTypeHeaderValue("application/zip");
        using var response = await SendAsync(
            directoryUrl,
            session,
            HttpMethod.Put,
            $"api/saves/{slot}",
            content,
            cancellationToken);
        var remote = await response.Content.ReadFromJsonAsync<CloudSaveRemoteSlot>(
                         JsonOptions,
                         cancellationToken) ??
                     throw new InvalidOperationException(
                         "The website returned an incomplete cloud-save receipt.");
        if (!string.Equals(remote.Sha256, archive.Sha256, StringComparison.OrdinalIgnoreCase) ||
            remote.FormatVersion != CloudSaveArchive.FormatVersion ||
            remote.FileCount != archive.FileCount ||
            remote.UncompressedSize != archive.UncompressedSize)
        {
            throw new InvalidDataException(
                "The website cloud-save receipt did not match the uploaded snapshot.");
        }

        catalog_.MarkBackedUp(slot, archive.Sha256, remote.UpdatedAtUtc);
        return new CloudBackupResult(CloudBackupDisposition.Uploaded, remote);
    }

    public async Task RestoreAsync(
        string directoryUrl,
        int slot,
        CancellationToken cancellationToken = default)
    {
        var session = await sessionClient_.GetAsync(
            directoryUrl,
            cancellationToken: cancellationToken);
        if (session.LinkedAccount is null)
        {
            throw new InvalidOperationException(
                "Link this Steam account on the website before restoring cloud saves.");
        }

        using var response = await SendAsync(
            directoryUrl,
            session,
            HttpMethod.Get,
            $"api/saves/{slot}",
            content: null,
            cancellationToken);
        var bytes = await ReadArchiveAsync(response.Content, cancellationToken);
        CloudSaveArchive.Restore(catalog_, slot, bytes);
    }

    public async Task DeleteAsync(
        string directoryUrl,
        int slot,
        CancellationToken cancellationToken = default)
    {
        var session = await sessionClient_.GetAsync(
            directoryUrl,
            cancellationToken: cancellationToken);
        if (session.LinkedAccount is null)
        {
            throw new InvalidOperationException(
                "Link this Steam account on the website before changing cloud saves.");
        }
        using var response = await SendAsync(
            directoryUrl,
            session,
            HttpMethod.Delete,
            $"api/saves/{slot}",
            content: null,
            cancellationToken);
    }

    private static async Task<HttpResponseMessage> SendAsync(
        string directoryUrl,
        SteamWebsiteSession session,
        HttpMethod method,
        string path,
        HttpContent? content,
        CancellationToken cancellationToken)
    {
        using var client = new HttpClient
        {
            BaseAddress = new Uri(directoryUrl.TrimEnd('/') + "/"),
            Timeout = TimeSpan.FromSeconds(30)
        };
        using var request = new HttpRequestMessage(method, path)
        {
            Content = content
        };
        request.Headers.Authorization = new AuthenticationHeaderValue(
            "Bearer",
            session.Token);
        var response = await client.SendAsync(
            request,
            HttpCompletionOption.ResponseHeadersRead,
            cancellationToken);
        if (response.IsSuccessStatusCode)
        {
            return response;
        }

        var error = await ReadErrorAsync(response, cancellationToken);
        var statusCode = response.StatusCode;
        response.Dispose();
        if (statusCode is HttpStatusCode.Unauthorized or HttpStatusCode.Forbidden)
        {
            throw new InvalidOperationException(
                "Cloud saves are disabled until this Steam account is linked on the website.");
        }
        throw new InvalidOperationException(
            $"The website rejected the cloud-save request ({(int)statusCode}): {error}");
    }

    private static async Task<string> ReadErrorAsync(
        HttpResponseMessage response,
        CancellationToken cancellationToken)
    {
        try
        {
            var payload = await response.Content.ReadFromJsonAsync<WebsiteError>(
                JsonOptions,
                cancellationToken);
            return string.IsNullOrWhiteSpace(payload?.Error)
                ? response.ReasonPhrase ?? "request failed"
                : payload.Error;
        }
        catch (JsonException)
        {
            return response.ReasonPhrase ?? "request failed";
        }
    }

    private static async Task<byte[]> ReadArchiveAsync(
        HttpContent content,
        CancellationToken cancellationToken)
    {
        if (content.Headers.ContentLength is > CloudSaveArchive.MaxArchiveBytes)
        {
            throw new InvalidDataException(
                "The website returned a cloud save larger than 16 MiB.");
        }

        await using var source = await content.ReadAsStreamAsync(cancellationToken);
        using var destination = new MemoryStream();
        var buffer = new byte[64 * 1024];
        while (true)
        {
            var read = await source.ReadAsync(buffer, cancellationToken);
            if (read == 0)
            {
                break;
            }
            if (destination.Length + read > CloudSaveArchive.MaxArchiveBytes)
            {
                throw new InvalidDataException(
                    "The website returned a cloud save larger than 16 MiB.");
            }
            await destination.WriteAsync(buffer.AsMemory(0, read), cancellationToken);
        }
        return destination.ToArray();
    }

    private sealed class WebsiteError
    {
        public string? Error { get; set; }
    }
}
