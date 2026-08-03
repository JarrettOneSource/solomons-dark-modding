using System.Buffers.Binary;
using System.Security.Cryptography;
using System.Text;

namespace SolomonDarkModLauncher.Mods;

internal static class HostModTransferProtocol
{
    public const ushort Version = 91;
    public const int DigestBytes = 32;
    public const int ClientIdBytes = 16;
    public const int ModIdBytes = 128;
    public const int VersionBytes = 64;
    public const int ChunkBytes = 1024;
    public const int MaximumPackages = 128;
    public const long MaximumPackageBytes = 100L * 1024 * 1024;
    public const long MaximumTotalBytes = 512L * 1024 * 1024;

    public const int ManifestRequestBytes = 68;
    public const int ManifestResponseBytes = 116;
    public const int DescriptorRequestBytes = 104;
    public const int DescriptorResponseBytes = 372;
    public const int ChunkRequestBytes = 156;
    public const int ChunkResponsePrefixBytes = 128;
    public const int CompleteBytes = 132;
    public const int AbortBytes = 104;

    private const int HeaderBytes = 12;
    private static ReadOnlySpan<byte> Magic => "SDMP"u8;

    public static byte[] CreateManifestRequest(
        uint sequence,
        ulong lobbyId,
        ReadOnlySpan<byte> clientId,
        ReadOnlySpan<byte> expectedManifest)
    {
        RequireLength(clientId, ClientIdBytes, nameof(clientId));
        RequireLength(expectedManifest, DigestBytes, nameof(expectedManifest));
        var packet = new byte[ManifestRequestBytes];
        WriteHeader(packet, HostModTransferPacketKind.ManifestRequest, sequence);
        BinaryPrimitives.WriteUInt64LittleEndian(packet.AsSpan(12, 8), lobbyId);
        clientId.CopyTo(packet.AsSpan(20, ClientIdBytes));
        expectedManifest.CopyTo(packet.AsSpan(36, DigestBytes));
        return packet;
    }

    public static HostModTransferManifest ParseManifestResponse(
        ReadOnlySpan<byte> packet,
        ReadOnlySpan<byte> expectedClientId)
    {
        ValidatePacket(packet, ManifestResponseBytes, HostModTransferPacketKind.ManifestResponse);
        RequireClientId(packet.Slice(20, ClientIdBytes), expectedClientId);
        var packageCount = BinaryPrimitives.ReadUInt32LittleEndian(packet.Slice(104, 4));
        var totalBytes = BinaryPrimitives.ReadUInt64LittleEndian(packet.Slice(108, 8));
        if (packageCount > MaximumPackages || totalBytes > MaximumTotalBytes)
        {
            throw new InvalidDataException("The host advertised an out-of-bounds mod transfer index.");
        }
        return new HostModTransferManifest(
            (HostModTransferStatus)packet[36],
            BinaryPrimitives.ReadUInt64LittleEndian(packet.Slice(12, 8)),
            packet.Slice(40, DigestBytes).ToArray(),
            packet.Slice(72, DigestBytes).ToArray(),
            checked((int)packageCount),
            checked((long)totalBytes));
    }

    public static byte[] CreateDescriptorRequest(
        uint sequence,
        ulong lobbyId,
        ReadOnlySpan<byte> clientId,
        HostModTransferManifest manifest,
        int descriptorIndex)
    {
        if (descriptorIndex < 0 || descriptorIndex >= manifest.PackageCount)
        {
            throw new ArgumentOutOfRangeException(nameof(descriptorIndex));
        }
        RequireLength(clientId, ClientIdBytes, nameof(clientId));
        var packet = new byte[DescriptorRequestBytes];
        WriteHeader(packet, HostModTransferPacketKind.DescriptorRequest, sequence);
        BinaryPrimitives.WriteUInt64LittleEndian(packet.AsSpan(12, 8), lobbyId);
        clientId.CopyTo(packet.AsSpan(20, ClientIdBytes));
        manifest.HostManifestSha256.CopyTo(packet.AsSpan(36, DigestBytes));
        manifest.IndexSha256.CopyTo(packet.AsSpan(68, DigestBytes));
        BinaryPrimitives.WriteUInt32LittleEndian(
            packet.AsSpan(100, 4),
            checked((uint)descriptorIndex));
        return packet;
    }

    public static HostModTransferDescriptor ParseDescriptorResponse(
        ReadOnlySpan<byte> packet,
        ReadOnlySpan<byte> expectedClientId,
        HostModTransferManifest manifest,
        int expectedIndex)
    {
        ValidatePacket(packet, DescriptorResponseBytes, HostModTransferPacketKind.DescriptorResponse);
        RequireClientId(packet.Slice(20, ClientIdBytes), expectedClientId);
        var status = (HostModTransferStatus)packet[36];
        if (status != HostModTransferStatus.Ready)
        {
            return new HostModTransferDescriptor(
                status,
                expectedIndex,
                string.Empty,
                string.Empty,
                string.Empty,
                string.Empty,
                0);
        }
        RequireDigest(packet.Slice(40, DigestBytes), manifest.HostManifestSha256, "host fingerprint");
        RequireDigest(packet.Slice(72, DigestBytes), manifest.IndexSha256, "transfer index");
        var descriptorIndex = checked((int)BinaryPrimitives.ReadUInt32LittleEndian(packet.Slice(104, 4)));
        if (descriptorIndex != expectedIndex)
        {
            throw new InvalidDataException("The host returned the wrong mod transfer descriptor.");
        }
        var packageBytes = checked((long)BinaryPrimitives.ReadUInt64LittleEndian(packet.Slice(364, 8)));
        if (packageBytes <= 0 || packageBytes > MaximumPackageBytes)
        {
            throw new InvalidDataException("The host advertised an out-of-bounds mod package.");
        }
        return new HostModTransferDescriptor(
            status,
            descriptorIndex,
            ReadFixedUtf8(packet.Slice(108, ModIdBytes), "mod id"),
            ReadFixedUtf8(packet.Slice(236, VersionBytes), "mod version"),
            Convert.ToHexString(packet.Slice(300, DigestBytes)).ToLowerInvariant(),
            Convert.ToHexString(packet.Slice(332, DigestBytes)).ToLowerInvariant(),
            packageBytes);
    }

    public static byte[] CreateChunkRequest(
        uint sequence,
        ulong lobbyId,
        ReadOnlySpan<byte> clientId,
        HostModTransferManifest manifest,
        HostModTransferDescriptor descriptor,
        long offset,
        int requestedBytes)
    {
        if (offset < 0 || offset >= descriptor.PackageBytes ||
            offset % ChunkBytes != 0 ||
            requestedBytes <= 0 || requestedBytes > ChunkBytes ||
            offset + requestedBytes > descriptor.PackageBytes)
        {
            throw new ArgumentOutOfRangeException(nameof(offset));
        }
        var packet = new byte[ChunkRequestBytes];
        WriteHeader(packet, HostModTransferPacketKind.ChunkRequest, sequence);
        BinaryPrimitives.WriteUInt64LittleEndian(packet.AsSpan(12, 8), lobbyId);
        clientId.CopyTo(packet.AsSpan(20, ClientIdBytes));
        manifest.HostManifestSha256.CopyTo(packet.AsSpan(36, DigestBytes));
        manifest.IndexSha256.CopyTo(packet.AsSpan(68, DigestBytes));
        BinaryPrimitives.WriteUInt32LittleEndian(packet.AsSpan(100, 4), checked((uint)descriptor.Index));
        Convert.FromHexString(descriptor.PackageSha256).CopyTo(packet.AsSpan(104, DigestBytes));
        BinaryPrimitives.WriteUInt64LittleEndian(packet.AsSpan(136, 8), checked((ulong)descriptor.PackageBytes));
        BinaryPrimitives.WriteUInt64LittleEndian(packet.AsSpan(144, 8), checked((ulong)offset));
        BinaryPrimitives.WriteUInt16LittleEndian(packet.AsSpan(152, 2), checked((ushort)requestedBytes));
        return packet;
    }

    public static HostModTransferChunk ParseChunkResponse(
        ReadOnlySpan<byte> packet,
        ReadOnlySpan<byte> expectedClientId,
        HostModTransferDescriptor descriptor)
    {
        if (packet.Length < ChunkResponsePrefixBytes || packet.Length > ChunkResponsePrefixBytes + ChunkBytes)
        {
            throw new InvalidDataException("The host returned a malformed mod transfer chunk.");
        }
        ValidateHeader(packet, HostModTransferPacketKind.ChunkResponse);
        RequireClientId(packet.Slice(20, ClientIdBytes), expectedClientId);
        var status = (HostModTransferStatus)packet[36];
        var payloadBytes = BinaryPrimitives.ReadUInt16LittleEndian(packet.Slice(92, 2));
        if (status != HostModTransferStatus.Ready)
        {
            if (payloadBytes != 0 || packet.Length != ChunkResponsePrefixBytes)
            {
                throw new InvalidDataException("The host returned an invalid failed chunk response.");
            }
            return new HostModTransferChunk(status, descriptor.Index, 0, []);
        }
        if (payloadBytes == 0 || payloadBytes > ChunkBytes || packet.Length != ChunkResponsePrefixBytes + payloadBytes)
        {
            throw new InvalidDataException("The host returned an invalid mod transfer chunk length.");
        }
        var descriptorIndex = checked((int)BinaryPrimitives.ReadUInt32LittleEndian(packet.Slice(40, 4)));
        var packageBytes = checked((long)BinaryPrimitives.ReadUInt64LittleEndian(packet.Slice(76, 8)));
        var offset = checked((long)BinaryPrimitives.ReadUInt64LittleEndian(packet.Slice(84, 8)));
        if (descriptorIndex != descriptor.Index || packageBytes != descriptor.PackageBytes)
        {
            throw new InvalidDataException("The host changed mod package identity during transfer.");
        }
        RequireDigest(packet.Slice(44, DigestBytes), Convert.FromHexString(descriptor.PackageSha256), "package");
        var payload = packet.Slice(ChunkResponsePrefixBytes, payloadBytes).ToArray();
        if (!CryptographicOperations.FixedTimeEquals(
                packet.Slice(96, DigestBytes),
                SHA256.HashData(payload)))
        {
            throw new CryptographicException(
                "The host transfer chunk failed its SHA-256 integrity check.");
        }
        return new HostModTransferChunk(
            status,
            descriptorIndex,
            offset,
            payload);
    }

    public static byte[] CreateComplete(
        uint sequence,
        ulong lobbyId,
        ReadOnlySpan<byte> clientId,
        HostModTransferManifest manifest,
        HostModTransferDescriptor descriptor) =>
        CreateTerminalPacket(
            CompleteBytes,
            HostModTransferPacketKind.Complete,
            sequence,
            lobbyId,
            clientId,
            manifest,
            descriptor);

    public static byte[] CreateAbort(
        uint sequence,
        ulong lobbyId,
        ReadOnlySpan<byte> clientId,
        HostModTransferManifest? manifest,
        HostModTransferDescriptor? descriptor,
        HostModTransferAbortReason reason)
    {
        var packet = new byte[AbortBytes];
        WriteHeader(packet, HostModTransferPacketKind.Abort, sequence);
        BinaryPrimitives.WriteUInt64LittleEndian(packet.AsSpan(12, 8), lobbyId);
        clientId.CopyTo(packet.AsSpan(20, ClientIdBytes));
        packet[36] = (byte)reason;
        manifest?.HostManifestSha256.CopyTo(packet.AsSpan(40, DigestBytes));
        if (descriptor is not null)
        {
            Convert.FromHexString(descriptor.PackageSha256).CopyTo(packet.AsSpan(72, DigestBytes));
        }
        return packet;
    }

    public static bool IsPacketKind(ReadOnlySpan<byte> packet, HostModTransferPacketKind kind) =>
        packet.Length >= HeaderBytes &&
        packet[..4].SequenceEqual(Magic) &&
        BinaryPrimitives.ReadUInt16LittleEndian(packet.Slice(4, 2)) == Version &&
        BinaryPrimitives.ReadUInt16LittleEndian(packet.Slice(6, 2)) == (ushort)kind;

    private static byte[] CreateTerminalPacket(
        int length,
        HostModTransferPacketKind kind,
        uint sequence,
        ulong lobbyId,
        ReadOnlySpan<byte> clientId,
        HostModTransferManifest manifest,
        HostModTransferDescriptor descriptor)
    {
        var packet = new byte[length];
        WriteHeader(packet, kind, sequence);
        BinaryPrimitives.WriteUInt64LittleEndian(packet.AsSpan(12, 8), lobbyId);
        clientId.CopyTo(packet.AsSpan(20, ClientIdBytes));
        manifest.HostManifestSha256.CopyTo(packet.AsSpan(36, DigestBytes));
        manifest.IndexSha256.CopyTo(packet.AsSpan(68, DigestBytes));
        Convert.FromHexString(descriptor.PackageSha256).CopyTo(packet.AsSpan(100, DigestBytes));
        return packet;
    }

    private static void WriteHeader(Span<byte> packet, HostModTransferPacketKind kind, uint sequence)
    {
        Magic.CopyTo(packet);
        BinaryPrimitives.WriteUInt16LittleEndian(packet.Slice(4, 2), Version);
        BinaryPrimitives.WriteUInt16LittleEndian(packet.Slice(6, 2), (ushort)kind);
        BinaryPrimitives.WriteUInt32LittleEndian(packet.Slice(8, 4), sequence);
    }

    private static void ValidatePacket(ReadOnlySpan<byte> packet, int length, HostModTransferPacketKind kind)
    {
        if (packet.Length != length)
        {
            throw new InvalidDataException($"The host returned a malformed {kind} packet.");
        }
        ValidateHeader(packet, kind);
    }

    private static void ValidateHeader(ReadOnlySpan<byte> packet, HostModTransferPacketKind kind)
    {
        if (!IsPacketKind(packet, kind))
        {
            throw new InvalidDataException($"The host returned an invalid {kind} packet header.");
        }
    }

    private static void RequireClientId(ReadOnlySpan<byte> actual, ReadOnlySpan<byte> expected)
    {
        RequireLength(expected, ClientIdBytes, nameof(expected));
        if (!CryptographicOperations.FixedTimeEquals(actual, expected))
        {
            throw new InvalidDataException("The host returned a foreign mod transfer response.");
        }
    }

    private static void RequireDigest(ReadOnlySpan<byte> actual, ReadOnlySpan<byte> expected, string label)
    {
        RequireLength(expected, DigestBytes, nameof(expected));
        if (!CryptographicOperations.FixedTimeEquals(actual, expected))
        {
            throw new InvalidDataException($"The host changed the {label} digest during mod transfer.");
        }
    }

    private static void RequireLength(ReadOnlySpan<byte> value, int length, string parameter)
    {
        if (value.Length != length)
        {
            throw new ArgumentException($"Expected {length} bytes.", parameter);
        }
    }

    private static string ReadFixedUtf8(ReadOnlySpan<byte> bytes, string label)
    {
        var terminator = bytes.IndexOf((byte)0);
        if (terminator <= 0 || bytes[(terminator + 1)..].ContainsAnyExcept((byte)0))
        {
            throw new InvalidDataException($"The host returned an invalid {label}.");
        }
        try
        {
            return new UTF8Encoding(false, true).GetString(bytes[..terminator]);
        }
        catch (DecoderFallbackException exception)
        {
            throw new InvalidDataException($"The host returned invalid UTF-8 in the {label}.", exception);
        }
    }
}

internal enum HostModTransferPacketKind : ushort
{
    ManifestRequest = 34,
    ManifestResponse = 35,
    DescriptorRequest = 36,
    DescriptorResponse = 37,
    ChunkRequest = 38,
    ChunkResponse = 39,
    Complete = 40,
    Abort = 41
}

internal enum HostModTransferStatus : byte
{
    Ready = 1,
    Busy = 2,
    Unavailable = 3,
    NotHost = 4,
    FingerprintMismatch = 5,
    BoundsRejected = 6,
    StaleIndex = 7,
    InvalidRequest = 8
}

internal enum HostModTransferAbortReason : byte
{
    Completed = 1,
    Canceled = 2,
    TransportTimeout = 3,
    ProtocolMismatch = 4,
    IdentityMismatch = 5,
    ChunkDigestMismatch = 6,
    PackageDigestMismatch = 7,
    ContentDigestMismatch = 8,
    BoundsRejected = 9,
    HostUnavailable = 10
}

internal sealed record HostModTransferManifest(
    HostModTransferStatus Status,
    ulong LobbyId,
    byte[] HostManifestSha256,
    byte[] IndexSha256,
    int PackageCount,
    long TotalPackageBytes);

internal sealed record HostModTransferDescriptor(
    HostModTransferStatus Status,
    int Index,
    string Id,
    string Version,
    string ContentSha256,
    string PackageSha256,
    long PackageBytes);

internal sealed record HostModTransferChunk(
    HostModTransferStatus Status,
    int DescriptorIndex,
    long Offset,
    byte[] Payload);
