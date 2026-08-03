using System.Buffers.Binary;
using System.Security.Cryptography;
using SolomonDarkModding.IO;
using SolomonDarkModLauncher.Target;

namespace SolomonDarkModLauncher.Mods;

internal sealed partial class HostModTransferClient : IAsyncDisposable
{
    private const int MaximumAttemptsWithoutProgress = 10;
    private static readonly TimeSpan RetryInterval = TimeSpan.FromSeconds(1);
    private readonly IHostModTransferTransport transport_;
    private readonly string logRootPath_;
    private byte[] clientId_ = RandomNumberGenerator.GetBytes(
        HostModTransferProtocol.ClientIdBytes);
    private uint sequence_ = 1;
    private HostModTransferManifest? manifest_;
    private bool transferActive_;
    private bool disposed_;

    private HostModTransferClient(
        IHostModTransferTransport transport,
        string logRootPath)
    {
        transport_ = transport;
        logRootPath_ = logRootPath;
    }

    public HostModTransferCatalog Catalog { get; private set; } =
        HostModTransferCatalog.Unavailable("Host mod transfer was not queried.");

    public static async Task<HostModTransferClient> ConnectAsync(
        LauncherConfiguration configuration,
        ulong lobbyId,
        string? expectedHostFingerprint,
        CancellationToken cancellationToken = default)
    {
        var transport = await HostModTransferTransportFactory.ConnectAsync(
            configuration,
            lobbyId,
            cancellationToken);
        return await ConnectAsync(
            transport,
            configuration.Workspace.RuntimeRootPath,
            expectedHostFingerprint,
            cancellationToken);
    }

    internal static async Task<HostModTransferClient> ConnectAsync(
        IHostModTransferTransport transport,
        string logRootPath,
        string? expectedHostFingerprint,
        CancellationToken cancellationToken = default)
    {
        var client = new HostModTransferClient(
            transport,
            logRootPath);
        try
        {
            await client.QueryAsync(expectedHostFingerprint, cancellationToken);
            return client;
        }
        catch
        {
            await client.DisposeAsync();
            throw;
        }
    }

    public async ValueTask DisposeAsync()
    {
        if (disposed_)
        {
            return;
        }
        disposed_ = true;
        if (transferActive_ && manifest_ is { } manifest)
        {
            await TrySendAbortAsync(
                manifest,
                null,
                HostModTransferAbortReason.Completed,
                CancellationToken.None);
        }
        await transport_.DisposeAsync();
    }

    private async Task QueryAsync(
        string? expectedHostFingerprint,
        CancellationToken cancellationToken)
    {
        byte[] expected;
        try
        {
            expected = string.IsNullOrWhiteSpace(expectedHostFingerprint)
                ? new byte[HostModTransferProtocol.DigestBytes]
                : Convert.FromHexString(expectedHostFingerprint);
        }
        catch (FormatException exception)
        {
            throw new InvalidDataException(
                "The expected host fingerprint is not hexadecimal SHA-256.",
                exception);
        }
        if (expected.Length != HostModTransferProtocol.DigestBytes)
        {
            throw new InvalidDataException("The expected host fingerprint is not SHA-256.");
        }
        HostModTransferManifest manifest = null!;
        for (var attempt = 0; attempt < MaximumAttemptsWithoutProgress; attempt++)
        {
            var responseBytes = await ExchangeAsync(
                HostModTransferProtocol.CreateManifestRequest(
                    NextSequence(),
                    transport_.LobbyId,
                    clientId_,
                    expected),
                HostModTransferPacketKind.ManifestResponse,
                _ => true,
                cancellationToken);
            manifest = HostModTransferProtocol.ParseManifestResponse(
                responseBytes,
                clientId_);
            if (manifest.Status != HostModTransferStatus.Busy ||
                attempt == MaximumAttemptsWithoutProgress - 1)
            {
                break;
            }
            await Task.Delay(RetryInterval, cancellationToken);
        }
        if (manifest.LobbyId != transport_.LobbyId)
        {
            throw new InvalidDataException("The host returned a foreign transfer lobby identity.");
        }
        if (manifest.Status != HostModTransferStatus.Ready)
        {
            Catalog = HostModTransferCatalog.Unavailable(
                DescribeStatus(manifest.Status));
            return;
        }
        if (!expected.All(value => value == 0) &&
            !CryptographicOperations.FixedTimeEquals(expected, manifest.HostManifestSha256))
        {
            throw new InvalidDataException(
                "The direct-transfer host fingerprint differs from the lobby declaration.");
        }
        manifest_ = manifest;
        transferActive_ = true;

        var descriptors = new List<HostModTransferDescriptor>(manifest.PackageCount);
        long checkedTotal = 0;
        for (var index = 0; index < manifest.PackageCount; index++)
        {
            var descriptorBytes = await ExchangeAsync(
                HostModTransferProtocol.CreateDescriptorRequest(
                    NextSequence(),
                    transport_.LobbyId,
                    clientId_,
                    manifest,
                    index),
                HostModTransferPacketKind.DescriptorResponse,
                packet => packet.Length == HostModTransferProtocol.DescriptorResponseBytes &&
                    BinaryPrimitives.ReadUInt32LittleEndian(packet.AsSpan(104, 4)) ==
                        checked((uint)index),
                cancellationToken);
            var descriptor = HostModTransferProtocol.ParseDescriptorResponse(
                descriptorBytes,
                clientId_,
                manifest,
                index);
            RequireReady(descriptor.Status, $"descriptor {index}");
            checkedTotal = checked(checkedTotal + descriptor.PackageBytes);
            descriptors.Add(descriptor);
        }
        if (checkedTotal != manifest.TotalPackageBytes ||
            descriptors.Select(item => item.Id).Distinct(StringComparer.OrdinalIgnoreCase).Count() !=
                descriptors.Count)
        {
            throw new InvalidDataException("The host transfer index is internally inconsistent.");
        }
        Catalog = new HostModTransferCatalog(
            true,
            string.Empty,
            Convert.ToHexString(manifest.HostManifestSha256).ToLowerInvariant(),
            Convert.ToHexString(manifest.IndexSha256).ToLowerInvariant(),
            descriptors);
        LauncherLog.Write(
            "mod-transfer",
            $"Host transfer metadata ready. fingerprint={Catalog.HostManifestSha256} " +
            $"index_sha256={Catalog.IndexSha256} packages={descriptors.Count} " +
            $"total_bytes={manifest.TotalPackageBytes}",
            logRootPath_);
    }

    private async Task<byte[]> ExchangeAsync(
        byte[] request,
        HostModTransferPacketKind responseKind,
        Func<byte[], bool> matches,
        CancellationToken cancellationToken)
    {
        for (var attempt = 0; attempt < MaximumAttemptsWithoutProgress; attempt++)
        {
            await transport_.SendAsync(request, cancellationToken);
            using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            timeout.CancelAfter(RetryInterval);
            try
            {
                while (true)
                {
                    var response = await transport_.ReceiveAsync(timeout.Token);
                    if (HostModTransferProtocol.IsPacketKind(response, responseKind) &&
                        matches(response))
                    {
                        return response;
                    }
                }
            }
            catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
            {
                // Re-send the exact idempotent request.
            }
        }
        throw new TimeoutException(
            $"The host did not answer {responseKind} after {MaximumAttemptsWithoutProgress} attempts.");
    }

    private async Task TrySendAbortAsync(
        HostModTransferManifest manifest,
        HostModTransferDescriptor? descriptor,
        HostModTransferAbortReason reason,
        CancellationToken cancellationToken)
    {
        try
        {
            await transport_.SendAsync(
                HostModTransferProtocol.CreateAbort(
                    NextSequence(),
                    transport_.LobbyId,
                    clientId_,
                    manifest,
                    descriptor,
                    reason),
                cancellationToken);
        }
        catch (Exception exception) when (
            exception is IOException or OperationCanceledException or ObjectDisposedException)
        {
            LauncherLog.Write(
                "mod-transfer",
                $"Could not send transfer abort for {descriptor?.Id ?? "metadata session"}: " +
                exception.Message,
                logRootPath_);
        }
        finally
        {
            transferActive_ = false;
            RotateClientId();
        }
    }

    private async Task EnsureTransferActiveAsync(
        HostModTransferManifest expectedManifest,
        CancellationToken cancellationToken)
    {
        if (transferActive_)
        {
            return;
        }
        var responseBytes = await ExchangeAsync(
            HostModTransferProtocol.CreateManifestRequest(
                NextSequence(),
                transport_.LobbyId,
                clientId_,
                expectedManifest.HostManifestSha256),
            HostModTransferPacketKind.ManifestResponse,
            _ => true,
            cancellationToken);
        var current = HostModTransferProtocol.ParseManifestResponse(
            responseBytes,
            clientId_);
        RequireReady(current.Status, "resume");
        transferActive_ = true;
        if (current.LobbyId != expectedManifest.LobbyId ||
            current.PackageCount != expectedManifest.PackageCount ||
            current.TotalPackageBytes != expectedManifest.TotalPackageBytes ||
            !CryptographicOperations.FixedTimeEquals(
                current.HostManifestSha256,
                expectedManifest.HostManifestSha256) ||
            !CryptographicOperations.FixedTimeEquals(
                current.IndexSha256,
                expectedManifest.IndexSha256))
        {
            throw new InvalidDataException(
                "The host transfer index changed between package downloads.");
        }
    }

    private static void RequireReady(HostModTransferStatus status, string operation)
    {
        if (status != HostModTransferStatus.Ready)
        {
            throw new InvalidOperationException(
                $"The host rejected mod transfer {operation}: {DescribeStatus(status)}");
        }
    }

    private static string DescribeStatus(HostModTransferStatus status) =>
        status switch
        {
            HostModTransferStatus.Busy => "the host transfer service is busy",
            HostModTransferStatus.Unavailable => "the host has no valid staged transfer packages",
            HostModTransferStatus.NotHost => "the selected peer is not the host",
            HostModTransferStatus.FingerprintMismatch => "the declared host fingerprint changed",
            HostModTransferStatus.BoundsRejected => "the requested package exceeded transfer bounds",
            HostModTransferStatus.StaleIndex => "the host transfer index changed",
            HostModTransferStatus.InvalidRequest => "the host rejected an invalid request",
            _ => $"status {(byte)status}"
        };

    private uint NextSequence()
    {
        var current = sequence_++;
        if (sequence_ == 0) sequence_ = 1;
        return current;
    }

    private void RotateClientId()
    {
        CryptographicOperations.ZeroMemory(clientId_);
        clientId_ = RandomNumberGenerator.GetBytes(
            HostModTransferProtocol.ClientIdBytes);
    }
}

internal sealed record HostModTransferCatalog(
    bool Available,
    string Error,
    string? HostManifestSha256,
    string? IndexSha256,
    IReadOnlyList<HostModTransferDescriptor> Descriptors)
{
    public static HostModTransferCatalog Unavailable(string error) =>
        new(false, error, null, null, []);

    public HostModTransferDescriptor? Find(MultiplayerModDescriptor required) =>
        Descriptors.FirstOrDefault(descriptor =>
            string.Equals(descriptor.Id, required.Id, StringComparison.OrdinalIgnoreCase) &&
            string.Equals(descriptor.Version, required.Version, StringComparison.Ordinal) &&
            string.Equals(
                descriptor.ContentSha256,
                required.ContentSha256,
                StringComparison.OrdinalIgnoreCase));
}

internal sealed record HostModTransferReceipt(
    string HostManifestSha256,
    string IndexSha256,
    string PackageSha256,
    long PackageBytes,
    long ContiguousBytes);

internal sealed class HostModTransferIntegrityException(
    HostModTransferAbortReason reason,
    string message,
    Exception? innerException = null) : IOException(message, innerException)
{
    public HostModTransferAbortReason Reason { get; } = reason;
}
