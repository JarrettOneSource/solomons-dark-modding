using SolomonDarkModLauncher.Steam;

namespace SolomonDarkModLauncher.Staging;

internal sealed record StageBuildResult(
    string StageRootPath,
    string StageExecutablePath,
    string StageReportPath,
    string StageConfigRootPath,
    string StageBinaryLayoutPath,
    string StageDebugUiConfigPath,
    string StageRuntimeRootPath,
    string StageRuntimeBootstrapPath,
    string StageRuntimeFlagsPath,
    StageMirrorResult StageMirror,
    RuntimeMetadataStageResult RuntimeMetadata,
    MultiplayerCompatibilityStageResult MultiplayerCompatibility,
    SteamStageBootstrapResult SteamBootstrap,
    HudLabelAssetResult HudLabels,
    int EnabledModCount,
    int AppliedOverlayCount);
