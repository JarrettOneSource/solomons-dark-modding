namespace SolomonDarkModLauncher.Staging;

internal sealed record BoneyardPickerStageEntry(
    string DisplayName,
    string SourceModId,
    string SourceModName,
    string SourceModVersion,
    string SourceModDescription,
    string UpdatedUtc,
    string Filename,
    string SourceRelativePath,
    string ContentSha256,
    string StockRelativePath,
    string StagePath,
    long FileLength,
    int ChunkCount,
    int NamedBufferCount,
    int MaxDepth);
