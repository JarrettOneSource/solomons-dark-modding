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
    string? StageEntryScriptPath,
    string? StageEntryDllPath,
    IReadOnlyList<string> RequiredCapabilities,
    IReadOnlyList<string> OptionalCapabilities);
