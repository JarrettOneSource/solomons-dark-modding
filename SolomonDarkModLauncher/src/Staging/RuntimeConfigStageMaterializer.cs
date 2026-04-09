using SolomonDarkModLauncher.Target;

namespace SolomonDarkModLauncher.Staging;

internal static class RuntimeConfigStageMaterializer
{
    public static RuntimeConfigStageResult Materialize(LauncherConfiguration configuration)
    {
        var sourceConfigRootPath = configuration.Workspace.ConfigRootPath;
        if (!Directory.Exists(sourceConfigRootPath))
        {
            throw new InvalidOperationException($"Workspace config root was not found: {sourceConfigRootPath}");
        }

        var stageConfigRootPath = Path.Combine(
            configuration.Workspace.StageRootPath,
            ".sdmod",
            "config");
        FileTreeMirror.Synchronize(sourceConfigRootPath, stageConfigRootPath);

        var binaryLayoutPath = Path.Combine(stageConfigRootPath, "binary-layout.ini");
        if (!File.Exists(binaryLayoutPath))
        {
            throw new InvalidOperationException($"Staged binary layout file was not found: {binaryLayoutPath}");
        }

        var debugUiConfigPath = Path.Combine(stageConfigRootPath, "debug-ui.ini");
        if (!File.Exists(debugUiConfigPath))
        {
            throw new InvalidOperationException($"Staged debug UI config file was not found: {debugUiConfigPath}");
        }

        return new RuntimeConfigStageResult(
            stageConfigRootPath,
            binaryLayoutPath,
            debugUiConfigPath);
    }
}
