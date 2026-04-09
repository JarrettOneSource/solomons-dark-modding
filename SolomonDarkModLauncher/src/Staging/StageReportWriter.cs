using System.Text.Json;
using SolomonDarkModLauncher.Mods;
using SolomonDarkModLauncher.Steam;

namespace SolomonDarkModLauncher.Staging;

internal static class StageReportWriter
{
    public static string Write(
        string stageRootPath,
        string retailGamePath,
        StageMirrorResult stageMirror,
        IReadOnlyList<DiscoveredMod> enabledMods,
        int appliedOverlayCount,
        RuntimeMetadataStageResult runtimeMetadata,
        SteamStageBootstrapResult steamBootstrap)
    {
        var reportDirectory = Path.Combine(stageRootPath, ".sdmod");
        Directory.CreateDirectory(reportDirectory);

        var reportPath = Path.Combine(reportDirectory, "stage-report.json");
        var report = new
        {
            builtAtUtc = DateTime.UtcNow,
            retailGamePath,
            stageRootPath,
            enabledModCount = enabledMods.Count,
            appliedOverlayCount,
            stageMirror = new
            {
                copiedFileCount = stageMirror.CopiedFileCount,
                skippedFileCount = stageMirror.SkippedFileCount,
                deletedFileCount = stageMirror.DeletedFileCount,
                createdDirectoryCount = stageMirror.CreatedDirectoryCount,
                deletedDirectoryCount = stageMirror.DeletedDirectoryCount
            },
            steamBootstrap = new
            {
                enabled = steamBootstrap.Enabled,
                appId = steamBootstrap.AppId,
                stageAppIdPath = steamBootstrap.StageAppIdPath,
                stageApiDllPath = steamBootstrap.StageApiDllPath,
                steamApiSourcePath = steamBootstrap.SteamApiSourcePath,
                readyForInitialization = steamBootstrap.ReadyForInitialization
            },
            runtimeMetadata = new
            {
                runtimeRootPath = runtimeMetadata.RuntimeRootPath,
                runtimeModsRootPath = runtimeMetadata.RuntimeModsRootPath,
                runtimeSandboxRootPath = runtimeMetadata.RuntimeSandboxRootPath,
                runtimeBootstrapPath = runtimeMetadata.RuntimeBootstrapPath,
                runtimeFlagsPath = runtimeMetadata.RuntimeFlagsPath,
                runtimeProfile = runtimeMetadata.RuntimeProfileName,
                runtimeFlags = runtimeMetadata.FlagValues,
                stagedRuntimeModCount = runtimeMetadata.StagedRuntimeModCount,
                stagedLuaModCount = runtimeMetadata.StagedLuaModCount,
                stagedNativeModCount = runtimeMetadata.StagedNativeModCount,
                stagedRuntimeMods = runtimeMetadata.StagedRuntimeMods.Select(mod => new
                {
                    mod.Id,
                    mod.StorageKey,
                    mod.RuntimeKind,
                    mod.ApiVersion,
                    mod.StageModRootPath,
                    mod.StageManifestPath,
                    mod.StageSandboxRootPath,
                    mod.StageEntryScriptPath,
                    mod.StageEntryDllPath,
                    mod.RequiredCapabilities,
                    mod.OptionalCapabilities
                })
            },
            enabledMods = enabledMods.Select(mod => new
            {
                mod.Manifest.Id,
                mod.Manifest.Name,
                mod.Manifest.Version,
                mod.Manifest.Priority,
                mod.Manifest.RequiredMods,
                requiresRuntime = mod.RequiresRuntime,
                runtimeKind = mod.Manifest.RuntimeKind,
                runtime = mod.RequiresRuntime
                    ? new
                    {
                        mod.Manifest.Runtime.ApiVersion,
                        mod.Manifest.Runtime.EntryScript,
                        mod.Manifest.Runtime.EntryDll,
                        mod.Manifest.Runtime.RequiredCapabilities,
                        mod.Manifest.Runtime.OptionalCapabilities
                    }
                    : null,
                overlays = mod.Manifest.Overlays.Select(overlay => new
                {
                    overlay.Target,
                    overlay.Source,
                    overlay.Format
                })
            })
        };

        var json = JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true });
        File.WriteAllText(reportPath, json);
        return reportPath;
    }
}
