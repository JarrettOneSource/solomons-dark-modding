using System.Buffers.Binary;
using System.Security.Cryptography;
using System.Text.Json;
using SolomonDarkModding.IO;
using SolomonDarkModding.Updates;

namespace SolomonDarkModLauncher.Mods;

internal sealed partial class HostModTransferClient
{
    private const int ChunkWindow = 8;

    public async Task<DiscoveredMod> DownloadAndInstallAsync(
        HostModTransferDescriptor descriptor,
        string cacheRootPath,
        CancellationToken cancellationToken,
        IProgress<UpdateProgress>? progress = null)
    {
        var manifest = manifest_ ??
            throw new InvalidOperationException("Host mod transfer metadata was not initialized.");
        if (!Catalog.Descriptors.Contains(descriptor))
        {
            throw new InvalidOperationException("The requested package is not in the host transfer index.");
        }
        var required = new MultiplayerModDescriptor(
            descriptor.Id,
            descriptor.Version,
            descriptor.ContentSha256);
        var existingPath = WebsiteModPackageInstaller.GetCachePath(cacheRootPath, required);
        var existing = WebsiteModPackageInstaller.TryLoadExact(existingPath, required);
        if (existing is not null)
        {
            return existing;
        }
        await EnsureTransferActiveAsync(manifest, cancellationToken);

        var operationRoot = Path.Combine(
            cacheRootPath,
            ".host-transfer",
            descriptor.PackageSha256);
        var archivePath = Path.Combine(operationRoot, "package.partial");
        var receiptPath = Path.Combine(operationRoot, "receipt.json");
        Directory.CreateDirectory(operationRoot);
        var offset = LoadResumeOffset(
            receiptPath,
            archivePath,
            manifest,
            descriptor,
            logRootPath_);
        try
        {
            await using (var archive = new FileStream(
                archivePath,
                FileMode.OpenOrCreate,
                FileAccess.ReadWrite,
                FileShare.None,
                81920,
                FileOptions.Asynchronous | FileOptions.SequentialScan))
            {
                if (archive.Length != offset)
                {
                    archive.SetLength(offset);
                }
                archive.Position = offset;
                while (offset < descriptor.PackageBytes)
                {
                    var chunks = await ReceiveChunkWindowAsync(
                        manifest,
                        descriptor,
                        offset,
                        cancellationToken);
                    foreach (var chunk in chunks)
                    {
                        await archive.WriteAsync(chunk.Payload, cancellationToken);
                        offset = checked(offset + chunk.Payload.Length);
                        progress?.Report(new UpdateProgress(
                            UpdateProgressPhase.Downloading,
                            $"Downloading {descriptor.Id} v{descriptor.Version} directly from host…",
                            offset,
                            descriptor.PackageBytes,
                            UpdateProgressUnit.Bytes));
                    }
                    await WriteReceiptAsync(
                        receiptPath,
                        manifest,
                        descriptor,
                        offset,
                        cancellationToken);
                }
                await archive.FlushAsync(cancellationToken);
                archive.Position = 0;
                var actualPackageSha256 = Convert.ToHexString(
                    await SHA256.HashDataAsync(archive, cancellationToken))
                    .ToLowerInvariant();
                if (!string.Equals(
                        actualPackageSha256,
                        descriptor.PackageSha256,
                        StringComparison.OrdinalIgnoreCase))
                {
                    throw new HostModTransferIntegrityException(
                        HostModTransferAbortReason.PackageDigestMismatch,
                        $"Host package digest mismatch for {descriptor.Id}: " +
                        $"expected {descriptor.PackageSha256}, got {actualPackageSha256}.");
                }
            }

            LauncherLog.Write(
                "mod-transfer",
                $"Host package digest matched. mod={descriptor.Id} " +
                $"package_sha256={descriptor.PackageSha256} bytes={descriptor.PackageBytes}",
                logRootPath_);
            DiscoveredMod installed;
            try
            {
                installed = await WebsiteModPackageInstaller.InstallArchiveAsync(
                    archivePath,
                    descriptor.PackageSha256,
                    required,
                    cacheRootPath,
                    cancellationToken,
                    progress);
            }
            catch (InvalidDataException exception)
            {
                throw new HostModTransferIntegrityException(
                    HostModTransferAbortReason.ContentDigestMismatch,
                    exception.Message,
                    exception);
            }
            LauncherLog.Write(
                "mod-transfer",
                "Host content digest matched and package staged through the shared installer. " +
                $"mod={descriptor.Id} content_sha256={descriptor.ContentSha256}",
                logRootPath_);
            await transport_.SendAsync(
                HostModTransferProtocol.CreateComplete(
                    NextSequence(),
                    transport_.LobbyId,
                    clientId_,
                    manifest,
                    descriptor),
                cancellationToken);
            transferActive_ = false;
            RotateClientId();
            DeleteOperation(operationRoot);
            return installed;
        }
        catch (TimeoutException)
        {
            await TrySendAbortAsync(
                manifest,
                descriptor,
                HostModTransferAbortReason.TransportTimeout,
                cancellationToken);
            throw;
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            await TrySendAbortAsync(
                manifest,
                descriptor,
                HostModTransferAbortReason.Canceled,
                CancellationToken.None);
            DeleteOperation(operationRoot);
            throw;
        }
        catch (Exception exception) when (
            exception is InvalidDataException or
            InvalidOperationException or
            CryptographicException or
            IOException)
        {
            var reason = exception is HostModTransferIntegrityException integrity
                ? integrity.Reason
                : HostModTransferAbortReason.IdentityMismatch;
            await TrySendAbortAsync(manifest, descriptor, reason, cancellationToken);
            DeleteOperation(operationRoot);
            throw;
        }
    }

    private async Task<IReadOnlyList<HostModTransferChunk>> ReceiveChunkWindowAsync(
        HostModTransferManifest manifest,
        HostModTransferDescriptor descriptor,
        long firstOffset,
        CancellationToken cancellationToken)
    {
        var requests = new Dictionary<long, PendingChunk>();
        var nextOffset = firstOffset;
        while (requests.Count < ChunkWindow && nextOffset < descriptor.PackageBytes)
        {
            var requestedBytes = checked((int)Math.Min(
                HostModTransferProtocol.ChunkBytes,
                descriptor.PackageBytes - nextOffset));
            requests.Add(nextOffset, new PendingChunk(
                requestedBytes,
                HostModTransferProtocol.CreateChunkRequest(
                    NextSequence(),
                    transport_.LobbyId,
                    clientId_,
                    manifest,
                    descriptor,
                    nextOffset,
                    requestedBytes)));
            nextOffset = checked(nextOffset + requestedBytes);
        }

        var received = new Dictionary<long, HostModTransferChunk>();
        var attemptsWithoutProgress = 0;
        while (received.Count < requests.Count &&
               attemptsWithoutProgress < MaximumAttemptsWithoutProgress)
        {
            foreach (var request in requests.Where(item => !received.ContainsKey(item.Key)))
            {
                await transport_.SendAsync(request.Value.Bytes, cancellationToken);
            }
            var countBeforeAttempt = received.Count;
            using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            timeout.CancelAfter(RetryInterval);
            try
            {
                while (received.Count < requests.Count)
                {
                    var packet = await transport_.ReceiveAsync(timeout.Token);
                    if (!HostModTransferProtocol.IsPacketKind(
                            packet,
                            HostModTransferPacketKind.ChunkResponse) ||
                        packet.Length < HostModTransferProtocol.ChunkResponsePrefixBytes)
                    {
                        continue;
                    }
                    var wireOffset = BinaryPrimitives.ReadUInt64LittleEndian(
                        packet.AsSpan(84, 8));
                    if (wireOffset > long.MaxValue ||
                        !requests.TryGetValue(checked((long)wireOffset), out var request) ||
                        received.ContainsKey(checked((long)wireOffset)))
                    {
                        continue;
                    }
                    HostModTransferChunk chunk;
                    try
                    {
                        chunk = HostModTransferProtocol.ParseChunkResponse(
                            packet,
                            clientId_,
                            descriptor);
                    }
                    catch (CryptographicException exception)
                    {
                        throw new HostModTransferIntegrityException(
                            HostModTransferAbortReason.ChunkDigestMismatch,
                            exception.Message,
                            exception);
                    }
                    RequireReady(chunk.Status, $"chunk for {descriptor.Id}");
                    if (chunk.Payload.Length != request.Length ||
                        chunk.Offset != checked((long)wireOffset))
                    {
                        throw new InvalidDataException(
                            $"The host returned a noncontiguous package chunk for {descriptor.Id}.");
                    }
                    received.Add(
                        chunk.Offset,
                        chunk);
                }
            }
            catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
            {
                attemptsWithoutProgress = received.Count == countBeforeAttempt
                    ? attemptsWithoutProgress + 1
                    : 0;
            }
        }
        if (received.Count != requests.Count)
        {
            throw new TimeoutException(
                $"The host mod transfer made no progress after " +
                $"{MaximumAttemptsWithoutProgress} attempts.");
        }
        return received
            .OrderBy(item => item.Key)
            .Select(item => item.Value)
            .ToArray();
    }

    private static long LoadResumeOffset(
        string receiptPath,
        string archivePath,
        HostModTransferManifest manifest,
        HostModTransferDescriptor descriptor,
        string logRootPath)
    {
        try
        {
            if (!File.Exists(receiptPath) || !File.Exists(archivePath))
            {
                return 0;
            }
            var receipt = JsonSerializer.Deserialize<HostModTransferReceipt>(
                File.ReadAllText(receiptPath));
            var archiveBytes = new FileInfo(archivePath).Length;
            var valid = receipt is not null &&
                string.Equals(receipt.HostManifestSha256,
                    Convert.ToHexString(manifest.HostManifestSha256),
                    StringComparison.OrdinalIgnoreCase) &&
                string.Equals(receipt.IndexSha256,
                    Convert.ToHexString(manifest.IndexSha256),
                    StringComparison.OrdinalIgnoreCase) &&
                string.Equals(receipt.PackageSha256,
                    descriptor.PackageSha256,
                    StringComparison.OrdinalIgnoreCase) &&
                receipt.PackageBytes == descriptor.PackageBytes &&
                receipt.ContiguousBytes >= 0 &&
                receipt.ContiguousBytes <= archiveBytes &&
                archiveBytes <= descriptor.PackageBytes &&
                (receipt.ContiguousBytes == descriptor.PackageBytes ||
                 receipt.ContiguousBytes % HostModTransferProtocol.ChunkBytes == 0);
            if (valid)
            {
                return receipt!.ContiguousBytes;
            }
        }
        catch (Exception exception) when (
            exception is IOException or JsonException or UnauthorizedAccessException)
        {
            LauncherLog.Write(
                "mod-transfer",
                $"Discarding an invalid resume receipt: {exception.Message}",
                logRootPath);
        }
        if (File.Exists(receiptPath)) File.Delete(receiptPath);
        if (File.Exists(archivePath)) File.Delete(archivePath);
        return 0;
    }

    private static async Task WriteReceiptAsync(
        string receiptPath,
        HostModTransferManifest manifest,
        HostModTransferDescriptor descriptor,
        long contiguousBytes,
        CancellationToken cancellationToken)
    {
        var receipt = new HostModTransferReceipt(
            Convert.ToHexString(manifest.HostManifestSha256).ToLowerInvariant(),
            Convert.ToHexString(manifest.IndexSha256).ToLowerInvariant(),
            descriptor.PackageSha256,
            descriptor.PackageBytes,
            contiguousBytes);
        var temporaryPath = receiptPath + ".tmp";
        await File.WriteAllTextAsync(
            temporaryPath,
            JsonSerializer.Serialize(receipt),
            cancellationToken);
        File.Move(temporaryPath, receiptPath, overwrite: true);
    }

    private static void DeleteOperation(string operationRoot)
    {
        if (Directory.Exists(operationRoot))
        {
            Directory.Delete(operationRoot, recursive: true);
        }
    }

    private sealed record PendingChunk(int Length, byte[] Bytes);
}
