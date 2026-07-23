namespace SolomonDarkModLauncher.Mods;

internal static class ModManifestValidator
{
    public static void Validate(string manifestPath, ModManifest manifest)
    {
        if (manifest.Overlays is null || manifest.Runtime is null ||
            manifest.RequiredMods is null ||
            manifest.Provides is null ||
            manifest.Requires is null ||
            manifest.Overlays.Any(overlay => overlay is null) ||
            manifest.RequiredMods.Any(required => required is null) ||
            manifest.Provides.Any(contract => contract is null) ||
            manifest.Requires.Any(contract => contract is null) ||
            manifest.Runtime.RequiredCapabilities is null ||
            manifest.Runtime.OptionalCapabilities is null ||
            manifest.Runtime.RequiredCapabilities.Any(capability => capability is null) ||
            manifest.Runtime.OptionalCapabilities.Any(capability => capability is null))
        {
            throw new InvalidOperationException(
                $"Manifest contains null fields or list entries: {manifestPath}");
        }

        if (string.IsNullOrWhiteSpace(manifest.Id))
        {
            throw new InvalidOperationException($"Manifest missing id: {manifestPath}");
        }
        ValidateModIdentifier(manifestPath, manifest.Id, "id");

        if (string.IsNullOrWhiteSpace(manifest.Name))
        {
            throw new InvalidOperationException($"Manifest missing name: {manifestPath}");
        }

        if (string.IsNullOrWhiteSpace(manifest.Version))
        {
            throw new InvalidOperationException($"Manifest missing version: {manifestPath}");
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
        ValidateRuntimeContracts(manifestPath, manifest);
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

    private static void ValidateRuntimeContracts(
        string manifestPath,
        ModManifest manifest)
    {
        if ((manifest.Provides.Count != 0 || manifest.Requires.Count != 0) &&
            !manifest.RequiresLuaRuntime)
        {
            throw new InvalidOperationException(
                $"provides/requires are available only to Lua runtime mods: {manifestPath}");
        }

        ValidateContractList(manifestPath, manifest.Provides, "provides");
        ValidateContractList(manifestPath, manifest.Requires, "requires");
        var provided = new HashSet<string>(manifest.Provides, StringComparer.Ordinal);
        foreach (var requiredContract in manifest.Requires)
        {
            if (provided.Contains(requiredContract))
            {
                throw new InvalidOperationException(
                    $"Mod {manifest.Id} cannot both provide and require '{requiredContract}': {manifestPath}");
            }
        }
    }

    private static void ValidateContractList(
        string manifestPath,
        IReadOnlyList<string> contracts,
        string propertyName)
    {
        var seen = new HashSet<string>(StringComparer.Ordinal);
        foreach (var contract in contracts)
        {
            if (contract.Length == 0 || contract.Length > 128 ||
                contract.Any(character =>
                    !((character >= 'a' && character <= 'z') ||
                      (character >= '0' && character <= '9') ||
                      character is '.' or '_' or '-' or ':')))
            {
                throw new InvalidOperationException(
                    $"Invalid lowercase contract identifier '{contract}' in {propertyName}: {manifestPath}");
            }
            if (!seen.Add(contract))
            {
                throw new InvalidOperationException(
                    $"Duplicate contract '{contract}' in {propertyName}: {manifestPath}");
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

        ValidateBoneyardOverlay(manifestPath, overlay, sourcePath);
    }

    private static void ValidateBoneyardOverlay(
        string manifestPath,
        OverlayDefinition overlay,
        string sourcePath)
    {
        var sourceIsBoneyard = overlay.Source.EndsWith(".boneyard", StringComparison.OrdinalIgnoreCase);
        var targetIsBoneyard = overlay.Target.EndsWith(".boneyard", StringComparison.OrdinalIgnoreCase);
        var formatIsBoneyard = string.Equals(
            overlay.Format,
            "boneyard",
            StringComparison.OrdinalIgnoreCase);
        if (!sourceIsBoneyard && !targetIsBoneyard && !formatIsBoneyard)
        {
            return;
        }

        if (!sourceIsBoneyard || !targetIsBoneyard ||
            (!string.IsNullOrWhiteSpace(overlay.Format) && !formatIsBoneyard))
        {
            throw new InvalidOperationException(
                $"Boneyard overlays must use .boneyard source and target paths and format 'boneyard' when format is present: {manifestPath}");
        }

        var normalizedTarget = overlay.Target.Replace('\\', '/');
        var allowedTarget =
            normalizedTarget.StartsWith("data/levels/", StringComparison.OrdinalIgnoreCase) ||
            normalizedTarget.StartsWith(
                "sandbox/DarkCloud/mylevels/",
                StringComparison.OrdinalIgnoreCase) ||
            string.Equals(
                normalizedTarget,
                "sandbox/play.boneyard",
                StringComparison.OrdinalIgnoreCase) ||
            string.Equals(
                normalizedTarget,
                "sandbox/testrun.boneyard",
                StringComparison.OrdinalIgnoreCase);
        if (!allowedTarget)
        {
            throw new InvalidOperationException(
                $"Boneyard overlay targets must be a stock level, custom level, play, or testrun path: {manifestPath}: {overlay.Target}");
        }

        BoneyardFile.Inspect(sourcePath);
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
            ValidateModIdentifier(manifestPath, requiredModId, "requiredMods");

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

    private static void ValidateModIdentifier(
        string manifestPath,
        string modId,
        string propertyName)
    {
        if (modId.Length > 128 ||
            modId[0] is '.' or '_' or '-' ||
            modId[^1] is '.' or '_' or '-' ||
            modId.Any(character =>
                !((character >= 'a' && character <= 'z') ||
                  (character >= '0' && character <= '9') ||
                  character is '.' or '_' or '-')))
        {
            throw new InvalidOperationException(
                $"Invalid lowercase mod identifier '{modId}' in {propertyName}: {manifestPath}");
        }
    }

    private static void ValidateRelativePath(string manifestPath, string pathValue, string label)
    {
        if (Path.IsPathRooted(pathValue) ||
            pathValue.StartsWith('/') ||
            pathValue.StartsWith('\\') ||
            pathValue.Contains('\\') ||
            pathValue.EndsWith('/') ||
            pathValue.Split('/').Any(segment => segment.Length == 0 || segment is "." or ".."))
        {
            throw new InvalidOperationException(
                $"{label} must be a normalized relative file path in {manifestPath}: {pathValue}");
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
