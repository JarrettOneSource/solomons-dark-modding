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
    public int StagedRuntimeModCount => StagedRuntimeMods.Count;

    public int StagedLuaModCount => StagedRuntimeMods.Count(
        mod => string.Equals(mod.RuntimeKind, "lua", StringComparison.OrdinalIgnoreCase) ||
               string.Equals(mod.RuntimeKind, "hybrid", StringComparison.OrdinalIgnoreCase));

    public int StagedNativeModCount => StagedRuntimeMods.Count(
        mod => string.Equals(mod.RuntimeKind, "native", StringComparison.OrdinalIgnoreCase) ||
               string.Equals(mod.RuntimeKind, "hybrid", StringComparison.OrdinalIgnoreCase));
}
