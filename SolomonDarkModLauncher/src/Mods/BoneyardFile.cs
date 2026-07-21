using System.Buffers.Binary;

namespace SolomonDarkModLauncher.Mods;

internal readonly record struct BoneyardFileSummary(
    long Length,
    int ChunkCount,
    int NamedBufferCount,
    int MaxDepth);

internal static class BoneyardFile
{
    private const long MaxFileBytes = 256L * 1024 * 1024;
    private const int MaxChunks = 1_000_000;
    private const int MaxNamedBuffers = 65_536;
    private const int MaxNameBytes = 1024 * 1024;
    private const int MaxDepth = 512;
    private const uint ArenaSectionCount = 13;
    private const uint RegionLayoutSectionCount = 14;

    public static BoneyardFileSummary Inspect(string path)
    {
        using var stream = File.OpenRead(path);
        return Inspect(stream, path);
    }

    public static BoneyardFileSummary Inspect(Stream stream, string label)
    {
        var reader = new CountingReader(stream);
        var state = new ParseState();
        try
        {
            var root = ReadChunkHeader(reader, state, depth: 0);
            if (root.PayloadLength != 0 || root.ChildCount != 1)
            {
                throw Invalid(
                    label,
                    reader.Offset,
                    "the root chunk must contain exactly one Arena chunk");
            }

            var arena = ReadChunkHeader(reader, state, depth: 1);
            if (arena.PayloadLength != 0 || arena.ChildCount != ArenaSectionCount)
            {
                throw Invalid(
                    label,
                    reader.Offset,
                    $"the arena chunk must contain exactly {ArenaSectionCount} sections");
            }

            for (var index = 0U; index < ArenaSectionCount - 1; index++)
            {
                ReadChunk(reader, state, depth: 2);
            }

            var region = ReadChunkHeader(reader, state, depth: 2);
            if (region.PayloadLength != 0 || region.ChildCount != 1)
            {
                throw Invalid(
                    label,
                    reader.Offset,
                    "the Arena Region section must contain exactly one RegionLayout chunk");
            }

            var regionLayout = ReadChunkHeader(reader, state, depth: 3);
            if (regionLayout.PayloadLength != 0 ||
                regionLayout.ChildCount != RegionLayoutSectionCount)
            {
                throw Invalid(
                    label,
                    reader.Offset,
                    $"the RegionLayout chunk must contain exactly {RegionLayoutSectionCount} sections");
            }

            for (var index = 0U; index < regionLayout.ChildCount; index++)
            {
                ReadChunk(reader, state, depth: 4);
            }

            ReadNamedBuffers(reader, state, depth: 1, label);
            if (reader.ReadByte() != -1)
            {
                throw Invalid(label, reader.Offset - 1, "trailing data follows the SyncBuffer");
            }

            return new BoneyardFileSummary(
                reader.Offset,
                state.ChunkCount,
                state.NamedBufferCount,
                state.MaxDepth);
        }
        catch (InvalidDataException)
        {
            throw;
        }
        catch (EndOfStreamException exception)
        {
            throw Invalid(label, reader.Offset, "the SyncBuffer is truncated", exception);
        }
        catch (OverflowException exception)
        {
            throw Invalid(label, reader.Offset, "a SyncBuffer length overflows", exception);
        }
    }

    private static void ReadBuffer(
        CountingReader reader,
        ParseState state,
        int depth,
        string label)
    {
        ReadChunk(reader, state, depth);
        ReadNamedBuffers(reader, state, depth, label);
    }

    private static void ReadNamedBuffers(
        CountingReader reader,
        ParseState state,
        int depth,
        string label)
    {
        var count = reader.ReadUInt32();
        if (count > (uint)(MaxNamedBuffers - state.NamedBufferCount))
        {
            throw Invalid(label, reader.Offset - sizeof(uint), "too many named SyncBuffers");
        }

        for (var index = 0U; index < count; index++)
        {
            state.NamedBufferCount++;
            var nameLength = reader.ReadUInt32();
            if (nameLength is 0 or > MaxNameBytes)
            {
                throw Invalid(label, reader.Offset - sizeof(uint), "invalid named-buffer string length");
            }

            for (var byteIndex = 0U; byteIndex < nameLength; byteIndex++)
            {
                var value = reader.ReadRequiredByte();
                var isTerminator = byteIndex == nameLength - 1;
                if ((isTerminator && value != 0) || (!isTerminator && value == 0))
                {
                    throw Invalid(
                        label,
                        reader.Offset - 1,
                        "named-buffer strings must have one terminal NUL byte");
                }
            }

            ReadBuffer(reader, state, checked(depth + 1), label);
        }
    }

    private static void ReadChunk(CountingReader reader, ParseState state, int depth)
    {
        var header = ReadChunkHeader(reader, state, depth);
        for (var index = 0U; index < header.ChildCount; index++)
        {
            ReadChunk(reader, state, checked(depth + 1));
        }
    }

    private static ChunkHeader ReadChunkHeader(
        CountingReader reader,
        ParseState state,
        int depth)
    {
        if (depth > MaxDepth)
        {
            throw new InvalidDataException($"Boneyard SyncBuffer nesting exceeds {MaxDepth} levels.");
        }

        if (state.ChunkCount == MaxChunks)
        {
            throw new InvalidDataException($"Boneyard SyncBuffer contains more than {MaxChunks} chunks.");
        }

        state.ChunkCount++;
        state.MaxDepth = Math.Max(state.MaxDepth, depth);
        var payloadLength = reader.ReadUInt32();
        reader.Skip(payloadLength);
        var childCount = reader.ReadUInt32();
        if (childCount > (uint)(MaxChunks - state.ChunkCount))
        {
            throw new InvalidDataException($"Boneyard SyncBuffer contains more than {MaxChunks} chunks.");
        }

        return new ChunkHeader(payloadLength, childCount);
    }

    private static InvalidDataException Invalid(
        string label,
        long offset,
        string reason,
        Exception? innerException = null) =>
        new($"Boneyard '{label}' is invalid at byte {offset}: {reason}.", innerException);

    private readonly record struct ChunkHeader(uint PayloadLength, uint ChildCount);

    private sealed class ParseState
    {
        public int ChunkCount { get; set; }
        public int NamedBufferCount { get; set; }
        public int MaxDepth { get; set; }
    }

    private sealed class CountingReader(Stream stream)
    {
        private readonly byte[] _scratch = new byte[81920];

        public long Offset { get; private set; }

        public uint ReadUInt32()
        {
            Span<byte> bytes = stackalloc byte[sizeof(uint)];
            ReadExactly(bytes);
            return BinaryPrimitives.ReadUInt32LittleEndian(bytes);
        }

        public int ReadByte()
        {
            var value = stream.ReadByte();
            if (value >= 0)
            {
                Offset = checked(Offset + 1);
                EnsureFileLimit();
            }
            return value;
        }

        public byte ReadRequiredByte()
        {
            var value = ReadByte();
            return value >= 0 ? (byte)value : throw new EndOfStreamException();
        }

        public void Skip(uint count)
        {
            var remaining = (long)count;
            while (remaining > 0)
            {
                var requested = (int)Math.Min(remaining, _scratch.Length);
                var read = stream.Read(_scratch, 0, requested);
                if (read == 0)
                {
                    throw new EndOfStreamException();
                }
                Offset = checked(Offset + read);
                EnsureFileLimit();
                remaining -= read;
            }
        }

        private void ReadExactly(Span<byte> destination)
        {
            while (!destination.IsEmpty)
            {
                var read = stream.Read(destination);
                if (read == 0)
                {
                    throw new EndOfStreamException();
                }
                Offset = checked(Offset + read);
                EnsureFileLimit();
                destination = destination[read..];
            }
        }

        private void EnsureFileLimit()
        {
            if (Offset > MaxFileBytes)
            {
                throw new InvalidDataException("Boneyard files may not exceed 256 MiB.");
            }
        }
    }
}
