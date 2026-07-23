using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using SolomonDarkModLauncher.Mods;

namespace SolomonDarkModLauncher.Staging;

internal static class MultiplayerCompatibilityMaterializer
{
    public const int CurrentProtocolVersion = 81;
    public const string FingerprintEnvironmentVariable = "SDMOD_MULTIPLAYER_MANIFEST_SHA256";
    private const int SchemaVersion = 1;
    private const string ManifestFileName = "multiplayer-compatibility.json";

    private static readonly JsonSerializerOptions CanonicalJsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = false
    };

    private static readonly JsonSerializerOptions ReportJsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = true
    };

    public static MultiplayerCompatibilityStageResult Materialize(
        string stageRootPath,
        string stageExecutablePath,
        string stageBinaryLayoutPath,
        RuntimeMetadataStageResult runtimeMetadata,
        IReadOnlyList<DiscoveredMod> enabledMods,
        string loaderPath)
    {
        var compatibility = new CompatibilityDocument(
            SchemaVersion,
            CurrentProtocolVersion,
            HashRequiredFile(stageExecutablePath),
            HashOptionalFile(loaderPath),
            HashRequiredFile(stageBinaryLayoutPath),
            runtimeMetadata.FlagValues
                .OrderBy(pair => pair.Key, StringComparer.Ordinal)
                .Select(pair => new CompatibilityFlag(pair.Key, pair.Value))
                .ToArray(),
            enabledMods
                .OrderBy(mod => mod.Manifest.Id, StringComparer.Ordinal)
                .Select(BuildModIdentity)
                .ToArray());

        var canonicalBytes = JsonSerializer.SerializeToUtf8Bytes(
            compatibility,
            CanonicalJsonOptions);
        var fingerprint = Convert.ToHexString(SHA256.HashData(canonicalBytes))
            .ToLowerInvariant();
        var manifest = new CompatibilityManifest(fingerprint, compatibility);
        var manifestPath = Path.Combine(stageRootPath, ".sdmod", ManifestFileName);
        Directory.CreateDirectory(Path.GetDirectoryName(manifestPath)!);
        File.WriteAllText(
            manifestPath,
            JsonSerializer.Serialize(manifest, ReportJsonOptions),
            new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));

        return new MultiplayerCompatibilityStageResult(
            manifestPath,
            fingerprint,
            CurrentProtocolVersion,
            compatibility.EnabledMods
                .Select(mod => new MultiplayerModDescriptor(
                    mod.Id,
                    mod.Version,
                    mod.ContentSha256))
                .ToArray());
    }

    private static CompatibilityMod BuildModIdentity(DiscoveredMod mod)
    {
        return new CompatibilityMod(
            mod.Manifest.Id,
            mod.Manifest.Version,
            mod.Manifest.Priority,
            mod.Manifest.RuntimeKind,
            mod.Manifest.Runtime.ApiVersion,
            ModContentHasher.HashDirectory(mod.RootPath));
    }

    private static CompatibilityFile HashRequiredFile(string path)
    {
        if (!File.Exists(path))
        {
            throw new FileNotFoundException(
                "Required multiplayer compatibility input was not found.",
                path);
        }
        return new CompatibilityFile(
            Path.GetFileName(path),
            ModContentHasher.HashFile(path));
    }

    private static CompatibilityFile HashOptionalFile(string path)
    {
        return File.Exists(path)
            ? new CompatibilityFile(Path.GetFileName(path), ModContentHasher.HashFile(path))
            : new CompatibilityFile(Path.GetFileName(path), "missing");
    }

    private sealed record CompatibilityManifest(
        string FingerprintSha256,
        CompatibilityDocument Compatibility);

    private sealed record CompatibilityDocument(
        int SchemaVersion,
        int ProtocolVersion,
        CompatibilityFile GameExecutable,
        CompatibilityFile Loader,
        CompatibilityFile BinaryLayout,
        IReadOnlyList<CompatibilityFlag> RuntimeFlags,
        IReadOnlyList<CompatibilityMod> EnabledMods);

    private sealed record CompatibilityFile(string Name, string Sha256);

    private sealed record CompatibilityFlag(string Key, bool Enabled);

    private sealed record CompatibilityMod(
        string Id,
        string Version,
        int Priority,
        string RuntimeKind,
        string ApiVersion,
        string ContentSha256);
}
