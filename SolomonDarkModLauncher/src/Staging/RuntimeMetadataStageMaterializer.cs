using System.Security.Cryptography;
using System.Text;
using SolomonDarkModLauncher.Mods;

namespace SolomonDarkModLauncher.Staging;

internal static class RuntimeMetadataStageMaterializer
{
    private const string RuntimeDirectoryName = "runtime";
    private const string RuntimeModsDirectoryName = "mods";
    private const string RuntimeSandboxDirectoryName = "sandbox";
    private const string RuntimeSandboxModsDirectoryName = "mods";
    private const string SandboxDataDirectoryName = "data";
    private const string SandboxCacheDirectoryName = "cache";
    private const string SandboxTempDirectoryName = "tmp";
    private const string RuntimeBootstrapFileName = "runtime-bootstrap.ini";
    private const string RuntimeFlagsFileName = "runtime-flags.ini";
    private const string CurrentApiVersion = "0.2.0";

    public static RuntimeMetadataStageResult Materialize(
        string stageRootPath,
        IReadOnlyList<DiscoveredMod> enabledMods,
        RuntimeStageOptions stageOptions)
    {
        var flags = RuntimeStageFlags.Create(stageOptions);
        var runtimeRootPath = Path.Combine(stageRootPath, ".sdmod", RuntimeDirectoryName);
        var runtimeModsRootPath = Path.Combine(runtimeRootPath, RuntimeModsDirectoryName);
        var runtimeSandboxRootPath = Path.Combine(runtimeRootPath, RuntimeSandboxDirectoryName);
        var runtimeSandboxModsRootPath = Path.Combine(runtimeSandboxRootPath, RuntimeSandboxModsDirectoryName);
        var runtimeBootstrapPath = Path.Combine(runtimeRootPath, RuntimeBootstrapFileName);
        var runtimeFlagsPath = Path.Combine(runtimeRootPath, RuntimeFlagsFileName);

        Directory.CreateDirectory(runtimeRootPath);
        Directory.CreateDirectory(runtimeModsRootPath);
        Directory.CreateDirectory(runtimeSandboxModsRootPath);

        var stagedRuntimeMods = new List<RuntimeStageManifestEntry>();
        var activeStorageKeys = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var mod in enabledMods)
        {
            if (!flags.ShouldStageRuntimeMod(mod))
            {
                continue;
            }

            var stagedMod = MaterializeMod(runtimeModsRootPath, runtimeSandboxModsRootPath, mod);
            stagedRuntimeMods.Add(stagedMod);
            activeStorageKeys.Add(stagedMod.StorageKey);
        }

        DeleteStaleRuntimeMods(runtimeModsRootPath, activeStorageKeys);
        File.WriteAllText(runtimeFlagsPath, BuildFlagsContent(flags));
        File.WriteAllText(
            runtimeBootstrapPath,
            BuildBootstrapContent(stageRootPath, runtimeRootPath, runtimeSandboxRootPath, stagedRuntimeMods));

        return new RuntimeMetadataStageResult(
            runtimeRootPath,
            runtimeModsRootPath,
            runtimeSandboxRootPath,
            runtimeBootstrapPath,
            runtimeFlagsPath,
            flags.ProfileName,
            flags.AsDictionary(),
            stagedRuntimeMods);
    }

    private static RuntimeStageManifestEntry MaterializeMod(
        string runtimeModsRootPath,
        string runtimeSandboxModsRootPath,
        DiscoveredMod mod)
    {
        var storageKey = ComputeStorageKey(mod.Manifest.Id);
        var stagedModRootPath = Path.Combine(runtimeModsRootPath, storageKey);
        var stagedSandboxRootPath = Path.Combine(runtimeSandboxModsRootPath, storageKey);
        var stagedDataRootPath = Path.Combine(stagedSandboxRootPath, SandboxDataDirectoryName);
        var stagedCacheRootPath = Path.Combine(stagedSandboxRootPath, SandboxCacheDirectoryName);
        var stagedTempRootPath = Path.Combine(stagedSandboxRootPath, SandboxTempDirectoryName);

        FileTreeMirror.Synchronize(mod.RootPath, stagedModRootPath);
        Directory.CreateDirectory(stagedSandboxRootPath);
        Directory.CreateDirectory(stagedDataRootPath);
        Directory.CreateDirectory(stagedCacheRootPath);
        Directory.CreateDirectory(stagedTempRootPath);

        return new RuntimeStageManifestEntry(
            mod.Manifest.Id,
            storageKey,
            mod.Manifest.Name,
            mod.Manifest.Version,
            mod.Manifest.Runtime.ApiVersion,
            mod.Manifest.RuntimeKind,
            stagedModRootPath,
            Path.Combine(stagedModRootPath, "manifest.json"),
            stagedSandboxRootPath,
            stagedDataRootPath,
            stagedCacheRootPath,
            stagedTempRootPath,
            mod.RequiresLuaRuntime
                ? Path.Combine(stagedModRootPath, NormalizeRelativePath(mod.Manifest.Runtime.EntryScript))
                : null,
            mod.RequiresNativeRuntime
                ? Path.Combine(stagedModRootPath, NormalizeRelativePath(mod.Manifest.Runtime.EntryDll))
                : null,
            mod.Manifest.Runtime.RequiredCapabilities.ToArray(),
            mod.Manifest.Runtime.OptionalCapabilities.ToArray());
    }

    private static string NormalizeRelativePath(string relativePath)
    {
        return relativePath.Replace('/', Path.DirectorySeparatorChar).Replace('\\', Path.DirectorySeparatorChar);
    }

    private static void DeleteStaleRuntimeMods(
        string runtimeModsRootPath,
        IReadOnlySet<string> activeStorageKeys)
    {
        foreach (var directoryPath in Directory.EnumerateDirectories(runtimeModsRootPath))
        {
            var directoryName = Path.GetFileName(directoryPath);
            if (activeStorageKeys.Contains(directoryName))
            {
                continue;
            }

            Directory.Delete(directoryPath, recursive: true);
        }
    }

    private static string BuildFlagsContent(RuntimeStageFlags flags)
    {
        var builder = new StringBuilder();
        builder.AppendLine("# Solomon Dark runtime feature flags");
        builder.Append("profile=").AppendLine(flags.ProfileName);
        foreach (var pair in flags.AsDictionary())
        {
            builder.Append(pair.Key)
                .Append('=')
                .AppendLine(pair.Value ? "true" : "false");
        }

        return builder.ToString();
    }

    private static string BuildBootstrapContent(
        string stageRootPath,
        string runtimeRootPath,
        string runtimeSandboxRootPath,
        IReadOnlyList<RuntimeStageManifestEntry> stagedRuntimeMods)
    {
        var builder = new StringBuilder();
        builder.AppendLine("# Solomon Dark runtime bootstrap manifest");
        builder.AppendLine("[runtime]");
        builder.Append("api_version=").AppendLine(CurrentApiVersion);
        builder.Append("stage_root_path=").AppendLine(EscapeIniValue(stageRootPath));
        builder.Append("runtime_root_path=").AppendLine(EscapeIniValue(runtimeRootPath));
        builder.Append("mods_root_path=").AppendLine(EscapeIniValue(Path.Combine(runtimeRootPath, RuntimeModsDirectoryName)));
        builder.Append("sandbox_root_path=").AppendLine(EscapeIniValue(runtimeSandboxRootPath));
        builder.Append("mod_count=").AppendLine(stagedRuntimeMods.Count.ToString());

        for (var index = 0; index < stagedRuntimeMods.Count; index++)
        {
            var mod = stagedRuntimeMods[index];
            builder.AppendLine();
            builder.Append('[').Append("mod.").Append(index).AppendLine("]");
            builder.Append("id=").AppendLine(EscapeIniValue(mod.Id));
            builder.Append("storage_key=").AppendLine(EscapeIniValue(mod.StorageKey));
            builder.Append("name=").AppendLine(EscapeIniValue(mod.Name));
            builder.Append("version=").AppendLine(EscapeIniValue(mod.Version));
            builder.Append("api_version=").AppendLine(EscapeIniValue(mod.ApiVersion));
            builder.Append("runtime_kind=").AppendLine(EscapeIniValue(mod.RuntimeKind));
            builder.Append("root_path=").AppendLine(EscapeIniValue(mod.StageModRootPath));
            builder.Append("manifest_path=").AppendLine(EscapeIniValue(mod.StageManifestPath));
            builder.Append("sandbox_root_path=").AppendLine(EscapeIniValue(mod.StageSandboxRootPath));
            builder.Append("data_root_path=").AppendLine(EscapeIniValue(mod.StageDataRootPath));
            builder.Append("cache_root_path=").AppendLine(EscapeIniValue(mod.StageCacheRootPath));
            builder.Append("temp_root_path=").AppendLine(EscapeIniValue(mod.StageTempRootPath));
            builder.Append("entry_script_path=").AppendLine(EscapeIniValue(mod.StageEntryScriptPath));
            builder.Append("entry_dll_path=").AppendLine(EscapeIniValue(mod.StageEntryDllPath));
            builder.Append("required_capabilities=").AppendLine(EscapeIniValue(string.Join(",", mod.RequiredCapabilities)));
            builder.Append("optional_capabilities=").AppendLine(EscapeIniValue(string.Join(",", mod.OptionalCapabilities)));
        }

        return builder.ToString();
    }

    private static string EscapeIniValue(string? value)
    {
        return (value ?? string.Empty)
            .Replace("\r", string.Empty, StringComparison.Ordinal)
            .Replace("\n", " ", StringComparison.Ordinal);
    }

    private static string ComputeStorageKey(string modId)
    {
        var bytes = SHA256.HashData(Encoding.UTF8.GetBytes(modId));
        return Convert.ToHexString(bytes).ToLowerInvariant();
    }
}
