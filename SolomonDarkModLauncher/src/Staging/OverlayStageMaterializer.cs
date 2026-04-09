using SolomonDarkModLauncher.Mods;

namespace SolomonDarkModLauncher.Staging;

internal static class OverlayStageMaterializer
{
    public static int Materialize(string stageRootPath, IReadOnlyList<DiscoveredMod> enabledMods)
    {
        var appliedOverlayCount = 0;

        foreach (var mod in enabledMods)
        {
            foreach (var overlay in mod.Manifest.Overlays)
            {
                ApplyOverlay(stageRootPath, mod, overlay);
                appliedOverlayCount++;
            }
        }

        return appliedOverlayCount;
    }

    private static void ApplyOverlay(
        string stageRootPath,
        DiscoveredMod mod,
        OverlayDefinition overlay)
    {
        var sourcePath = ResolveInsideRoot(
            mod.RootPath,
            overlay.Source,
            mod.ManifestPath,
            "Overlay source");
        if (!File.Exists(sourcePath))
        {
            throw new FileNotFoundException("Overlay source file not found.", sourcePath);
        }

        var targetPath = ResolveInsideRoot(
            stageRootPath,
            overlay.Target,
            mod.ManifestPath,
            "Overlay target");
        var targetDirectory = Path.GetDirectoryName(targetPath);
        if (!string.IsNullOrWhiteSpace(targetDirectory))
        {
            Directory.CreateDirectory(targetDirectory);
        }

        File.Copy(sourcePath, targetPath, overwrite: true);
    }

    private static string ResolveInsideRoot(
        string rootPath,
        string relativePath,
        string manifestPath,
        string label)
    {
        if (string.IsNullOrWhiteSpace(relativePath))
        {
            throw new InvalidOperationException($"{label} is required in {manifestPath}");
        }

        var candidatePath = Path.GetFullPath(Path.Combine(rootPath, relativePath));
        var normalizedRoot = Path.GetFullPath(rootPath)
            .TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
            + Path.DirectorySeparatorChar;
        if (!candidatePath.StartsWith(normalizedRoot, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException($"{label} escapes the root in {manifestPath}: {relativePath}");
        }

        return candidatePath;
    }
}
