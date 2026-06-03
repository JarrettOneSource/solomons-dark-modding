using System.IO.Compression;

namespace SolomonDarkModLauncher.Staging;

internal static class HudLabelAssetMaterializer
{
    private const int UiBundleRecordSize = 45;
    private const int AllyLabelRecordIndex = 0;
    private const string AllyLabelEnvironmentVariable = "SDMOD_HUD_ALLY_LABEL";
    private const int GeneratedAllyLabelX = 459;
    private const int GeneratedAllyLabelY = 53;
    private const int GeneratedAllyLabelWidth = 96;
    private const int GeneratedAllyLabelHeight = 7;

    public static HudLabelAssetResult Materialize(string stageRootPath)
    {
        var imagesRootPath = Path.Combine(stageRootPath, "images");
        var uiBundlePath = Path.Combine(imagesRootPath, "UI.bundle");
        var uiImagePath = Path.Combine(imagesRootPath, "UI.png");

        if (!File.Exists(uiBundlePath))
        {
            throw new FileNotFoundException("The staged UI.bundle file was not found.", uiBundlePath);
        }

        if (!File.Exists(uiImagePath))
        {
            throw new FileNotFoundException("The staged UI.png file was not found.", uiImagePath);
        }

        var stockRecord = ReadUiSpriteRecord(uiBundlePath, AllyLabelRecordIndex);
        var allyLabel = ResolveAllyLabel();
        if (string.IsNullOrWhiteSpace(allyLabel))
        {
            return new HudLabelAssetResult(
                false,
                string.Empty,
                uiBundlePath,
                uiImagePath,
                AllyLabelRecordIndex,
                stockRecord.X,
                stockRecord.Y,
                stockRecord.Width,
                stockRecord.Height);
        }

        var record = new UiSpriteRecord(
            GeneratedAllyLabelX,
            GeneratedAllyLabelY,
            GeneratedAllyLabelWidth,
            GeneratedAllyLabelHeight);
        if (record.Width <= 0 || record.Height <= 0)
        {
            throw new InvalidOperationException(
                $"UI.bundle record {AllyLabelRecordIndex} has invalid dimensions {record.Width}x{record.Height}.");
        }

        WriteUiSpriteRecord(uiBundlePath, AllyLabelRecordIndex, record);
        RenderLabelIntoUiImage(uiImagePath, record, allyLabel);
        return new HudLabelAssetResult(
            true,
            allyLabel,
            uiBundlePath,
            uiImagePath,
            AllyLabelRecordIndex,
            record.X,
            record.Y,
            record.Width,
            record.Height);
    }

    private static string ResolveAllyLabel()
    {
        return (Environment.GetEnvironmentVariable(AllyLabelEnvironmentVariable) ?? string.Empty).Trim();
    }

    private static UiSpriteRecord ReadUiSpriteRecord(string uiBundlePath, int recordIndex)
    {
        var bytes = File.ReadAllBytes(uiBundlePath);
        var offset = checked(recordIndex * UiBundleRecordSize);
        if (offset + UiBundleRecordSize > bytes.Length)
        {
            throw new InvalidOperationException(
                $"UI.bundle does not contain record {recordIndex}; length={bytes.Length} recordSize={UiBundleRecordSize}.");
        }

        var textureX = ReadSingle(bytes, offset);
        var textureY = ReadSingle(bytes, offset + 4);
        var width = BitConverter.ToInt32(bytes, offset + 16);
        var height = BitConverter.ToInt32(bytes, offset + 20);

        return new UiSpriteRecord(
            CheckedIntegralCoordinate(textureX, "x"),
            CheckedIntegralCoordinate(textureY, "y"),
            width,
            height);
    }

    private static float ReadSingle(byte[] bytes, int offset)
    {
        return BitConverter.ToSingle(bytes, offset);
    }

    private static void WriteUiSpriteRecord(string uiBundlePath, int recordIndex, UiSpriteRecord record)
    {
        var bytes = File.ReadAllBytes(uiBundlePath);
        var offset = checked(recordIndex * UiBundleRecordSize);
        if (offset + UiBundleRecordSize > bytes.Length)
        {
            throw new InvalidOperationException(
                $"UI.bundle does not contain record {recordIndex}; length={bytes.Length} recordSize={UiBundleRecordSize}.");
        }

        WriteSingle(bytes, offset, record.X);
        WriteSingle(bytes, offset + 4, record.Y);
        WriteSingle(bytes, offset + 8, record.Width);
        WriteSingle(bytes, offset + 12, record.Height);
        WriteInt32(bytes, offset + 16, record.Width);
        WriteInt32(bytes, offset + 20, record.Height);
        WriteSingle(bytes, offset + 24, record.Width);
        WriteSingle(bytes, offset + 28, record.Height);
        File.WriteAllBytes(uiBundlePath, bytes);
    }

    private static void WriteSingle(byte[] bytes, int offset, float value)
    {
        BitConverter.GetBytes(value).CopyTo(bytes, offset);
    }

    private static void WriteInt32(byte[] bytes, int offset, int value)
    {
        BitConverter.GetBytes(value).CopyTo(bytes, offset);
    }

    private static int CheckedIntegralCoordinate(float value, string fieldName)
    {
        if (!float.IsFinite(value))
        {
            throw new InvalidOperationException($"UI.bundle record {AllyLabelRecordIndex} has non-finite {fieldName}={value}.");
        }

        var rounded = (int)MathF.Round(value);
        if (MathF.Abs(value - rounded) > 0.01f)
        {
            throw new InvalidOperationException(
                $"UI.bundle record {AllyLabelRecordIndex} has non-integral {fieldName}={value}.");
        }

        return rounded;
    }

    private static void RenderLabelIntoUiImage(string uiImagePath, UiSpriteRecord record, string label)
    {
        var sourceImage = PngRgbaImage.Load(uiImagePath);
        if (record.X < 0 ||
            record.Y < 0 ||
            record.Width <= 0 ||
            record.Height <= 0 ||
            record.X + record.Width > sourceImage.Width ||
            record.Y + record.Height > sourceImage.Height)
        {
            throw new InvalidOperationException(
                $"UI.bundle record {AllyLabelRecordIndex} points outside UI.png: " +
                $"x={record.X} y={record.Y} width={record.Width} height={record.Height} " +
                $"image={sourceImage.Width}x{sourceImage.Height}.");
        }

        var labelPixels = HudLabelSpriteRenderer.Render(label, record.Width, record.Height);
        for (var y = 0; y < record.Height; y++)
        {
            for (var x = 0; x < record.Width; x++)
            {
                sourceImage.SetPixel(record.X + x, record.Y + y, 255, 255, 255, labelPixels[x, y]);
            }
        }

        var tempPath = uiImagePath + ".sdmod.tmp";
        sourceImage.Save(tempPath);
        File.Copy(tempPath, uiImagePath, overwrite: true);
        File.Delete(tempPath);
    }

    private readonly record struct UiSpriteRecord(int X, int Y, int Width, int Height);
}

internal static class HudLabelSpriteRenderer
{
    private static readonly IReadOnlyDictionary<char, string[]> Glyphs = new Dictionary<char, string[]>
    {
        ['A'] = ["0110", "1001", "1111", "1001", "1001"],
        ['B'] = ["1110", "1001", "1110", "1001", "1110"],
        ['C'] = ["111", "100", "100", "100", "111"],
        ['D'] = ["110", "101", "101", "101", "110"],
        ['E'] = ["111", "100", "110", "100", "111"],
        ['F'] = ["1111", "1000", "1110", "1000", "1000"],
        ['G'] = ["0111", "1000", "1011", "1001", "0111"],
        ['H'] = ["1001", "1001", "1111", "1001", "1001"],
        ['I'] = ["111", "010", "010", "010", "111"],
        ['J'] = ["0011", "0001", "0001", "1001", "0110"],
        ['K'] = ["1001", "1010", "1100", "1010", "1001"],
        ['L'] = ["1000", "1000", "1000", "1000", "1111"],
        ['M'] = ["10001", "11011", "10101", "10001", "10001"],
        ['N'] = ["1001", "1101", "1011", "1001", "1001"],
        ['O'] = ["111", "101", "101", "101", "111"],
        ['P'] = ["1110", "1001", "1110", "1000", "1000"],
        ['Q'] = ["0110", "1001", "1001", "1010", "0101"],
        ['R'] = ["1110", "1001", "1110", "1010", "1001"],
        ['S'] = ["0111", "1000", "0110", "0001", "1110"],
        ['T'] = ["11111", "00100", "00100", "00100", "00100"],
        ['U'] = ["1001", "1001", "1001", "1001", "0110"],
        ['V'] = ["1001", "1001", "1001", "0110", "0110"],
        ['W'] = ["10001", "10001", "10101", "11011", "10001"],
        ['X'] = ["101", "101", "010", "101", "101"],
        ['Y'] = ["1001", "1001", "0110", "0010", "0010"],
        ['Z'] = ["1111", "0001", "0010", "0100", "1111"],
        ['0'] = ["0110", "1001", "1001", "1001", "0110"],
        ['1'] = ["010", "110", "010", "010", "111"],
        ['2'] = ["1110", "0001", "0110", "1000", "1111"],
        ['3'] = ["1110", "0001", "0110", "0001", "1110"],
        ['4'] = ["1001", "1001", "1111", "0001", "0001"],
        ['5'] = ["1111", "1000", "1110", "0001", "1110"],
        ['6'] = ["0111", "1000", "1110", "1001", "0110"],
        ['7'] = ["1111", "0001", "0010", "0100", "0100"],
        ['8'] = ["0110", "1001", "0110", "1001", "0110"],
        ['9'] = ["0110", "1001", "0111", "0001", "1110"],
        ['-'] = ["000", "000", "111", "000", "000"],
        ['_'] = ["000", "000", "000", "000", "111"],
        [' '] = ["0", "0", "0", "0", "0"],
    };

    public static byte[,] Render(string label, int width, int height)
    {
        if (width <= 0 || height <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(width), "Label render target dimensions must be positive.");
        }

        var normalizedLabel = NormalizeLabel(label);
        var glyphRuns = BuildGlyphRuns(normalizedLabel, width);
        var pixels = new byte[width, height];
        var totalWidth = MeasureGlyphRuns(glyphRuns);
        var left = Math.Max(0, (width - totalWidth) / 2);
        var top = Math.Max(0, (height - 5) / 2);

        var cursorX = left;
        foreach (var glyph in glyphRuns)
        {
            for (var gy = 0; gy < glyph.Length && top + gy < height; gy++)
            {
                var row = glyph[gy];
                for (var gx = 0; gx < row.Length && cursorX + gx < width; gx++)
                {
                    if (row[gx] == '1')
                    {
                        pixels[cursorX + gx, top + gy] = 255;
                    }
                }
            }

            cursorX += glyph[0].Length + 1;
        }

        return pixels;
    }

    private static string NormalizeLabel(string label)
    {
        var chars = new List<char>(label.Length);
        foreach (var ch in label.ToUpperInvariant())
        {
            chars.Add(Glyphs.ContainsKey(ch) ? ch : '_');
        }

        return new string(chars.ToArray()).Trim();
    }

    private static List<string[]> BuildGlyphRuns(string label, int maxWidth)
    {
        var glyphRuns = new List<string[]>();
        foreach (var ch in label)
        {
            glyphRuns.Add(Glyphs[ch]);
            if (MeasureGlyphRuns(glyphRuns) > maxWidth)
            {
                glyphRuns.RemoveAt(glyphRuns.Count - 1);
                break;
            }
        }

        return glyphRuns;
    }

    private static int MeasureGlyphRuns(IReadOnlyList<string[]> glyphRuns)
    {
        if (glyphRuns.Count == 0)
        {
            return 0;
        }

        var width = glyphRuns.Count - 1;
        foreach (var glyph in glyphRuns)
        {
            width += glyph[0].Length;
        }

        return width;
    }

    private static void AddSoftEdge(byte[,] pixels, int width, int height)
    {
        var edgePixels = new List<(int X, int Y)>();
        for (var y = 0; y < height; y++)
        {
            for (var x = 0; x < width; x++)
            {
                if (pixels[x, y] == 0)
                {
                    continue;
                }

                TryAddEdgePixel(edgePixels, pixels, width, height, x - 1, y);
                TryAddEdgePixel(edgePixels, pixels, width, height, x + 1, y);
                TryAddEdgePixel(edgePixels, pixels, width, height, x, y - 1);
                TryAddEdgePixel(edgePixels, pixels, width, height, x, y + 1);
            }
        }

        foreach (var (x, y) in edgePixels)
        {
            pixels[x, y] = Math.Max(pixels[x, y], (byte)64);
        }
    }

    private static void TryAddEdgePixel(
        List<(int X, int Y)> edgePixels,
        byte[,] pixels,
        int width,
        int height,
        int x,
        int y)
    {
        if (x < 0 || y < 0 || x >= width || y >= height || pixels[x, y] != 0)
        {
            return;
        }

        edgePixels.Add((x, y));
    }
}

internal sealed class PngRgbaImage
{
    private static readonly byte[] PngSignature = [137, 80, 78, 71, 13, 10, 26, 10];
    private const int BytesPerPixel = 4;

    private readonly byte[] pixels_;

    private PngRgbaImage(int width, int height, byte[] pixels)
    {
        Width = width;
        Height = height;
        pixels_ = pixels;
    }

    public int Width { get; }
    public int Height { get; }

    public static PngRgbaImage Load(string path)
    {
        var bytes = File.ReadAllBytes(path);
        if (bytes.Length < PngSignature.Length || !bytes.AsSpan(0, PngSignature.Length).SequenceEqual(PngSignature))
        {
            throw new InvalidOperationException($"Unsupported PNG signature: {path}");
        }

        var width = 0;
        var height = 0;
        var idat = new MemoryStream();
        var offset = PngSignature.Length;
        while (offset < bytes.Length)
        {
            var length = ReadBigEndianInt32(bytes, offset);
            offset += 4;
            var chunkType = GetAscii(bytes, offset, 4);
            offset += 4;
            if (offset + length + 4 > bytes.Length)
            {
                throw new InvalidOperationException($"Malformed PNG chunk {chunkType} in {path}.");
            }

            var chunkDataOffset = offset;
            offset += length;
            offset += 4; // CRC

            if (chunkType == "IHDR")
            {
                width = ReadBigEndianInt32(bytes, chunkDataOffset);
                height = ReadBigEndianInt32(bytes, chunkDataOffset + 4);
                var bitDepth = bytes[chunkDataOffset + 8];
                var colorType = bytes[chunkDataOffset + 9];
                var compression = bytes[chunkDataOffset + 10];
                var filter = bytes[chunkDataOffset + 11];
                var interlace = bytes[chunkDataOffset + 12];
                if (bitDepth != 8 || colorType != 6 || compression != 0 || filter != 0 || interlace != 0)
                {
                    throw new InvalidOperationException(
                        $"Unsupported PNG format for {path}: bitDepth={bitDepth} colorType={colorType} " +
                        $"compression={compression} filter={filter} interlace={interlace}.");
                }
            }
            else if (chunkType == "IDAT")
            {
                idat.Write(bytes, chunkDataOffset, length);
            }
            else if (chunkType == "IEND")
            {
                break;
            }
        }

        if (width <= 0 || height <= 0)
        {
            throw new InvalidOperationException($"PNG did not contain a valid IHDR: {path}");
        }

        idat.Position = 0;
        using var decompressed = new MemoryStream();
        using (var zlib = new ZLibStream(idat, CompressionMode.Decompress))
        {
            zlib.CopyTo(decompressed);
        }

        var raw = decompressed.ToArray();
        var stride = checked(width * BytesPerPixel);
        var expectedRawLength = checked((stride + 1) * height);
        if (raw.Length != expectedRawLength)
        {
            throw new InvalidOperationException(
                $"Unexpected PNG data size for {path}: actual={raw.Length} expected={expectedRawLength}.");
        }

        var pixels = DecodeScanlines(raw, width, height, stride);
        return new PngRgbaImage(width, height, pixels);
    }

    public void SetPixel(int x, int y, byte red, byte green, byte blue, byte alpha)
    {
        var offset = checked(((y * Width) + x) * BytesPerPixel);
        pixels_[offset] = red;
        pixels_[offset + 1] = green;
        pixels_[offset + 2] = blue;
        pixels_[offset + 3] = alpha;
    }

    public void Save(string path)
    {
        var stride = checked(Width * BytesPerPixel);
        var raw = new byte[checked((stride + 1) * Height)];
        var rawOffset = 0;
        for (var y = 0; y < Height; y++)
        {
            raw[rawOffset++] = 0;
            Buffer.BlockCopy(pixels_, y * stride, raw, rawOffset, stride);
            rawOffset += stride;
        }

        byte[] compressed;
        using (var compressedStream = new MemoryStream())
        {
            using (var zlib = new ZLibStream(compressedStream, CompressionLevel.SmallestSize, leaveOpen: true))
            {
                zlib.Write(raw, 0, raw.Length);
            }

            compressed = compressedStream.ToArray();
        }

        using var output = new FileStream(path, FileMode.Create, FileAccess.Write, FileShare.None);
        output.Write(PngSignature);
        WriteChunk(output, "IHDR", BuildIhdrChunk(Width, Height));
        WriteChunk(output, "IDAT", compressed);
        WriteChunk(output, "IEND", []);
    }

    private static byte[] DecodeScanlines(byte[] raw, int width, int height, int stride)
    {
        var pixels = new byte[checked(stride * height)];
        var rawOffset = 0;
        var previousRow = new byte[stride];
        var currentRow = new byte[stride];

        for (var y = 0; y < height; y++)
        {
            var filterType = raw[rawOffset++];
            for (var x = 0; x < stride; x++)
            {
                var encoded = raw[rawOffset++];
                var left = x >= BytesPerPixel ? currentRow[x - BytesPerPixel] : (byte)0;
                var up = previousRow[x];
                var upperLeft = x >= BytesPerPixel ? previousRow[x - BytesPerPixel] : (byte)0;
                var predictor = filterType switch
                {
                    0 => 0,
                    1 => left,
                    2 => up,
                    3 => (left + up) / 2,
                    4 => PaethPredictor(left, up, upperLeft),
                    _ => throw new InvalidOperationException($"Unsupported PNG filter type {filterType}.")
                };
                currentRow[x] = unchecked((byte)(encoded + predictor));
            }

            Buffer.BlockCopy(currentRow, 0, pixels, y * stride, stride);
            (previousRow, currentRow) = (currentRow, previousRow);
            Array.Clear(currentRow);
        }

        return pixels;
    }

    private static int PaethPredictor(int left, int up, int upperLeft)
    {
        var estimate = left + up - upperLeft;
        var leftDistance = Math.Abs(estimate - left);
        var upDistance = Math.Abs(estimate - up);
        var upperLeftDistance = Math.Abs(estimate - upperLeft);

        if (leftDistance <= upDistance && leftDistance <= upperLeftDistance)
        {
            return left;
        }

        return upDistance <= upperLeftDistance ? up : upperLeft;
    }

    private static byte[] BuildIhdrChunk(int width, int height)
    {
        var data = new byte[13];
        WriteBigEndianInt32(data, 0, width);
        WriteBigEndianInt32(data, 4, height);
        data[8] = 8;
        data[9] = 6;
        data[10] = 0;
        data[11] = 0;
        data[12] = 0;
        return data;
    }

    private static void WriteChunk(Stream output, string chunkType, byte[] data)
    {
        var typeBytes = System.Text.Encoding.ASCII.GetBytes(chunkType);
        var length = new byte[4];
        WriteBigEndianInt32(length, 0, data.Length);
        output.Write(length);
        output.Write(typeBytes);
        output.Write(data);

        var crc = Crc32.Compute(typeBytes, data);
        var crcBytes = new byte[4];
        WriteBigEndianInt32(crcBytes, 0, unchecked((int)crc));
        output.Write(crcBytes);
    }

    private static int ReadBigEndianInt32(byte[] bytes, int offset)
    {
        return (bytes[offset] << 24) |
               (bytes[offset + 1] << 16) |
               (bytes[offset + 2] << 8) |
               bytes[offset + 3];
    }

    private static void WriteBigEndianInt32(byte[] bytes, int offset, int value)
    {
        bytes[offset] = (byte)((value >> 24) & 0xff);
        bytes[offset + 1] = (byte)((value >> 16) & 0xff);
        bytes[offset + 2] = (byte)((value >> 8) & 0xff);
        bytes[offset + 3] = (byte)(value & 0xff);
    }

    private static string GetAscii(byte[] bytes, int offset, int length)
    {
        return System.Text.Encoding.ASCII.GetString(bytes, offset, length);
    }
}

internal static class Crc32
{
    private static readonly uint[] Table = BuildTable();

    public static uint Compute(byte[] chunkType, byte[] data)
    {
        var crc = 0xffffffffu;
        foreach (var value in chunkType)
        {
            crc = Table[(crc ^ value) & 0xff] ^ (crc >> 8);
        }

        foreach (var value in data)
        {
            crc = Table[(crc ^ value) & 0xff] ^ (crc >> 8);
        }

        return crc ^ 0xffffffffu;
    }

    private static uint[] BuildTable()
    {
        var table = new uint[256];
        for (var i = 0u; i < table.Length; i++)
        {
            var value = i;
            for (var bit = 0; bit < 8; bit++)
            {
                value = (value & 1) != 0 ? 0xedb88320u ^ (value >> 1) : value >> 1;
            }

            table[i] = value;
        }

        return table;
    }
}
