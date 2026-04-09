namespace SolomonDarkModLauncher.Staging;

internal sealed record StageMirrorResult(
    int CopiedFileCount,
    int SkippedFileCount,
    int DeletedFileCount,
    int CreatedDirectoryCount,
    int DeletedDirectoryCount);
