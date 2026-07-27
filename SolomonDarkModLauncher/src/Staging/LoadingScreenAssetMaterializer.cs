namespace SolomonDarkModLauncher.Staging;

internal static class LoadingScreenAssetMaterializer
{
    internal const string BackgroundFileName = "Wizards_dire_BG.png";

    public static string Materialize(string workspaceRootPath, string stageRootPath)
    {
        var sourceAssetsRootPath = Path.Combine(workspaceRootPath, "assets");
        var sourceBackgroundPath = Path.Combine(
            sourceAssetsRootPath,
            "loading",
            BackgroundFileName);
        if (!File.Exists(sourceBackgroundPath))
        {
            throw new FileNotFoundException(
                "The loading-screen background was not found.",
                sourceBackgroundPath);
        }

        var stageAssetsRootPath = Path.Combine(
            stageRootPath,
            ".sdmod",
            "assets");
        FileTreeMirror.Synchronize(
            sourceAssetsRootPath,
            stageAssetsRootPath);

        var stageBackgroundPath = Path.Combine(
            stageAssetsRootPath,
            "loading",
            BackgroundFileName);
        if (!File.Exists(stageBackgroundPath))
        {
            throw new InvalidOperationException(
                $"The staged loading-screen background was not found: {stageBackgroundPath}");
        }
        return stageBackgroundPath;
    }
}
