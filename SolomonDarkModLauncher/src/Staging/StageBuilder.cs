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
        var hudLabels = HudLabelAssetMaterializer.Materialize(configuration.Workspace.StageRootPath);
        var runtimeConfig = RuntimeConfigStageMaterializer.Materialize(configuration);
        var runtimeMetadata = RuntimeMetadataStageMaterializer.Materialize(
            configuration.Workspace.StageRootPath,
            catalog.EnabledMods,
            configuration.Runtime);
        var steamBootstrap = SteamBootstrapMaterializer.Materialize(configuration);
        var stageExecutablePath = Path.Combine(
            configuration.Workspace.StageRootPath,
            configuration.Game.ExecutableName);
        var multiplayerCompatibility = MultiplayerCompatibilityMaterializer.Materialize(
            configuration.Workspace.StageRootPath,
            stageExecutablePath,
            runtimeConfig.StageBinaryLayoutPath,
            runtimeMetadata,
            catalog.EnabledMods,
            Path.Combine(AppContext.BaseDirectory, "SolomonDarkModLoader.dll"));

        var reportPath = StageReportWriter.Write(
            configuration.Workspace.StageRootPath,
            configuration.Game.InstallDirectory,
            stageMirror,
            catalog.EnabledMods,
            appliedOverlayCount,
            hudLabels,
            runtimeMetadata,
            multiplayerCompatibility,
            steamBootstrap);

        return new StageBuildResult(
            configuration.Workspace.StageRootPath,
            stageExecutablePath,
            reportPath,
            runtimeConfig.StageConfigRootPath,
            runtimeConfig.StageBinaryLayoutPath,
            runtimeConfig.StageDebugUiConfigPath,
            runtimeMetadata.RuntimeRootPath,
            runtimeMetadata.RuntimeBootstrapPath,
            runtimeMetadata.RuntimeFlagsPath,
            stageMirror,
            runtimeMetadata,
            multiplayerCompatibility,
            steamBootstrap,
            hudLabels,
            catalog.EnabledMods.Count,
            appliedOverlayCount);
    }
}
