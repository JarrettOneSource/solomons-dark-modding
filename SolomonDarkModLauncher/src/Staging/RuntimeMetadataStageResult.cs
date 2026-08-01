namespace SolomonDarkModLauncher.Staging;

internal sealed record RuntimeMetadataStageResult(
    string RuntimeRootPath,
    string RuntimeModsRootPath,
    string RuntimeSandboxRootPath,
    string RuntimeBootstrapPath,
    string RuntimeFlagsPath,
    string RuntimeProfileName,
    IReadOnlyDictionary<string, bool> FlagValues,
    IReadOnlyList<RuntimeStageManifestEntry> StagedRuntimeMods)
{
    public IReadOnlyList<BoneyardPickerStageEntry> StagedBoneyards { get; init; } =
        Array.Empty<BoneyardPickerStageEntry>();

    public int StagedRuntimeModCount => StagedRuntimeMods.Count;

    public int StagedLuaModCount => StagedRuntimeMods.Count;

    public int StagedBoneyardCount => StagedBoneyards.Count;
}
