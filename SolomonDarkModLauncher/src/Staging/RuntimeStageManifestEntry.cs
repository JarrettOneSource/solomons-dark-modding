namespace SolomonDarkModLauncher.Staging;

internal sealed record RuntimeStageManifestEntry(
    string Id,
    string StorageKey,
    string Name,
    string Version,
    string ApiVersion,
    string RuntimeKind,
    string StageModRootPath,
    string StageManifestPath,
    string StageSandboxRootPath,
    string StageDataRootPath,
    string StageCacheRootPath,
    string StageTempRootPath,
    bool HotReload,
    string SourceModRootPath,
    string? SourceEntryScriptPath,
    string? StageEntryScriptPath,
    IReadOnlyList<string> RequiredCapabilities,
    IReadOnlyList<string> OptionalCapabilities,
    IReadOnlyList<string> Provides,
    IReadOnlyList<string> Requires);
