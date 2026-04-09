namespace SolomonDarkModLauncher.Staging;

internal sealed record RuntimeConfigStageResult(
    string StageConfigRootPath,
    string StageBinaryLayoutPath,
    string StageDebugUiConfigPath);
