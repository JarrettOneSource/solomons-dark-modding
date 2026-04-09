namespace SolomonDarkModLauncher.Mods;

internal static class ModManifestValidator
{
    public static void Validate(string manifestPath, ModManifest manifest)
    {
        if (string.IsNullOrWhiteSpace(manifest.Id))
        {
            throw new InvalidOperationException($"Manifest missing id: {manifestPath}");
        }

        if (string.IsNullOrWhiteSpace(manifest.Name))
        {
            throw new InvalidOperationException($"Manifest missing name: {manifestPath}");
        }

        if (manifest.Overlays.Count == 0 && !manifest.RequiresRuntime)
        {
            throw new InvalidOperationException(
                $"Mods must define at least one overlay or one runtime entry point: {manifestPath}");
        }

        foreach (var overlay in manifest.Overlays)
        {
            ValidateOverlay(manifestPath, overlay);
        }

        if (manifest.RequiresRuntime)
        {
            ValidateRuntime(manifestPath, manifest);
        }

        ValidateRequiredMods(manifestPath, manifest.Id, manifest.RequiredMods);
    }

    private static void ValidateRuntime(string manifestPath, ModManifest manifest)
    {
        if (string.IsNullOrWhiteSpace(manifest.Runtime.ApiVersion))
        {
            throw new InvalidOperationException($"Runtime mods must define runtime.apiVersion: {manifestPath}");
        }

        if (manifest.RequiresLuaRuntime)
        {
            ValidateRuntimeEntryPath(
                manifestPath,
                manifest.Runtime.EntryScript,
                "Runtime entryScript",
                "scripts/");
        }

        if (manifest.RequiresNativeRuntime)
        {
            ValidateRuntimeEntryPath(
                manifestPath,
                manifest.Runtime.EntryDll,
                "Runtime entryDll",
                "native/");
        }

        ValidateCapabilities(manifestPath, manifest.Runtime.RequiredCapabilities, "runtime.requiredCapabilities");
        ValidateCapabilities(manifestPath, manifest.Runtime.OptionalCapabilities, "runtime.optionalCapabilities");
    }

    private static void ValidateRuntimeEntryPath(
        string manifestPath,
        string relativePath,
        string label,
        string requiredRootPrefix)
    {
        ValidateRelativePath(manifestPath, relativePath, label);

        var normalizedRelativePath = relativePath.Replace('\\', '/');
        if (!normalizedRelativePath.StartsWith(requiredRootPrefix, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException(
                $"{label} must live under {requiredRootPrefix} in {manifestPath}: {relativePath}");
        }

        var manifestDirectory = Path.GetDirectoryName(manifestPath)
            ?? throw new InvalidOperationException($"Manifest directory missing: {manifestPath}");
        var candidatePath = Path.GetFullPath(Path.Combine(manifestDirectory, relativePath));
        EnsureInsideDirectory(manifestDirectory, candidatePath, label);
    }

    private static void ValidateCapabilities(
        string manifestPath,
        IReadOnlyList<string> capabilities,
        string propertyName)
    {
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var capability in capabilities)
        {
            if (string.IsNullOrWhiteSpace(capability))
            {
                throw new InvalidOperationException($"Blank capability in {propertyName}: {manifestPath}");
            }

            if (!seen.Add(capability))
            {
                throw new InvalidOperationException(
                    $"Duplicate capability '{capability}' in {propertyName}: {manifestPath}");
            }
        }
    }

    private static void ValidateOverlay(string manifestPath, OverlayDefinition overlay)
    {
        if (string.IsNullOrWhiteSpace(overlay.Target))
        {
            throw new InvalidOperationException($"Overlay target is required: {manifestPath}");
        }

        if (string.IsNullOrWhiteSpace(overlay.Source))
        {
            throw new InvalidOperationException($"Overlay source is required: {manifestPath}");
        }

        ValidateRelativePath(manifestPath, overlay.Target, "Overlay target");
        ValidateRelativePath(manifestPath, overlay.Source, "Overlay source");

        var normalizedSource = overlay.Source.Replace('\\', '/');
        if (!normalizedSource.StartsWith("files/", StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException($"Overlay source must live under files/ in {manifestPath}: {overlay.Source}");
        }

        var manifestDirectory = Path.GetDirectoryName(manifestPath)
            ?? throw new InvalidOperationException($"Manifest directory missing: {manifestPath}");
        var sourcePath = Path.GetFullPath(Path.Combine(manifestDirectory, overlay.Source));
        EnsureInsideDirectory(manifestDirectory, sourcePath, "Overlay source");
        if (!File.Exists(sourcePath))
        {
            throw new FileNotFoundException("Overlay source file not found.", sourcePath);
        }
    }

    private static void ValidateRequiredMods(
        string manifestPath,
        string modId,
        IReadOnlyList<string> requiredMods)
    {
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var requiredModId in requiredMods)
        {
            if (string.IsNullOrWhiteSpace(requiredModId))
            {
                throw new InvalidOperationException($"Blank mod id in requiredMods: {manifestPath}");
            }

            if (string.Equals(requiredModId, modId, StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidOperationException(
                    $"Mod {modId} cannot list itself in requiredMods: {manifestPath}");
            }

            if (!seen.Add(requiredModId))
            {
                throw new InvalidOperationException(
                    $"Duplicate mod id '{requiredModId}' in requiredMods: {manifestPath}");
            }
        }
    }

    private static void ValidateRelativePath(string manifestPath, string pathValue, string label)
    {
        if (Path.IsPathRooted(pathValue) || pathValue.StartsWith('/') || pathValue.StartsWith('\\'))
        {
            throw new InvalidOperationException($"{label} must be relative in {manifestPath}: {pathValue}");
        }
    }

    private static void EnsureInsideDirectory(string rootPath, string candidatePath, string label)
    {
        var normalizedRoot = Path.GetFullPath(rootPath)
            .TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
            + Path.DirectorySeparatorChar;

        if (!candidatePath.StartsWith(normalizedRoot, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException($"{label} escapes the mod root: {candidatePath}");
        }
    }
}
