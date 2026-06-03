namespace SolomonDarkModLauncher.Staging;

internal sealed record HudLabelAssetResult(
    bool Applied,
    string Label,
    string UiBundlePath,
    string UiImagePath,
    int RecordIndex,
    int X,
    int Y,
    int Width,
    int Height);
