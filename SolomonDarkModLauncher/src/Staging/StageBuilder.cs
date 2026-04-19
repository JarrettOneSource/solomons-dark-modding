using SolomonDarkModLauncher.Mods;
using SolomonDarkModLauncher.Steam;
using SolomonDarkModLauncher.Target;

namespace SolomonDarkModLauncher.Staging;

internal static class StageBuilder
{
    public static StageBuildResult Build(
        LauncherConfiguration configuration,
        ModCatalog catalog)
    {
        StageRootProcessCleaner.TerminateProcessesUsingStage(configuration.Workspace.StageRootPath);
        var stageMirror = FileTreeMirror.Synchronize(
            configuration.Game.InstallDirectory,
            configuration.Workspace.StageRootPath);
        StageSandboxCompatibilityLinks.Materialize(configuration.Workspace.StageRootPath);

        var appliedOverlayCount = OverlayStageMaterializer.Materialize(
            configuration.Workspace.StageRootPath,
            catalog.EnabledMods);
        var runtimeConfig = RuntimeConfigStageMaterializer.Materialize(configuration);
        var runtimeMetadata = RuntimeMetadataStageMaterializer.Materialize(
            configuration.Workspace.StageRootPath,
            catalog.EnabledMods,
            configuration.Runtime);
        var steamBootstrap = SteamBootstrapMaterializer.Materialize(configuration);

        var reportPath = StageReportWriter.Write(
            configuration.Workspace.StageRootPath,
            configuration.Game.InstallDirectory,
            stageMirror,
            catalog.EnabledMods,
            appliedOverlayCount,
            runtimeMetadata,
            steamBootstrap);

        return new StageBuildResult(
            configuration.Workspace.StageRootPath,
            Path.Combine(configuration.Workspace.StageRootPath, configuration.Game.ExecutableName),
            reportPath,
            runtimeConfig.StageConfigRootPath,
            runtimeConfig.StageBinaryLayoutPath,
            runtimeConfig.StageDebugUiConfigPath,
            runtimeMetadata.RuntimeRootPath,
            runtimeMetadata.RuntimeBootstrapPath,
            runtimeMetadata.RuntimeFlagsPath,
            stageMirror,
            runtimeMetadata,
            steamBootstrap,
            catalog.EnabledMods.Count,
            appliedOverlayCount);
    }
}
