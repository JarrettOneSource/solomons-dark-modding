namespace SolomonDarkModLauncher.Mods;

internal sealed class ModCatalog
{
    public required IReadOnlyList<DiscoveredMod> DiscoveredMods { get; init; }
    public required IReadOnlyList<DiscoveredMod> EnabledMods { get; init; }
    public required IReadOnlySet<string> EnabledModIds { get; init; }

    public static ModCatalog Load(string modsRootPath, ModStateStore stateStore)
    {
        Directory.CreateDirectory(modsRootPath);

        var discovered = ModDiscovery.Discover(modsRootPath)
            .OrderBy(mod => mod.Manifest.Priority)
            .ThenBy(mod => mod.Manifest.Id, StringComparer.OrdinalIgnoreCase)
            .ToArray();

        EnsureUniqueIds(discovered);

        var discoveredById = discovered.ToDictionary(
            mod => mod.Manifest.Id,
            StringComparer.OrdinalIgnoreCase);
        var explicitlyEnabledMods = discovered
            .Where(mod => stateStore.IsEnabled(mod.Manifest.Id))
            .ToArray();
        var resolvedEnabledIds = ResolveEnabledModIds(explicitlyEnabledMods, discoveredById);
        var enabledMods = discovered
            .Where(mod => resolvedEnabledIds.Contains(mod.Manifest.Id))
            .ToArray();
        var enabledIds = new HashSet<string>(
            enabledMods.Select(mod => mod.Manifest.Id),
            StringComparer.OrdinalIgnoreCase);

        return new ModCatalog
        {
            DiscoveredMods = discovered,
            EnabledMods = enabledMods,
            EnabledModIds = enabledIds
        };
    }

    public bool IsEnabled(DiscoveredMod mod)
    {
        return IsEnabled(mod.Manifest.Id);
    }

    public bool IsEnabled(string modId)
    {
        return EnabledModIds.Contains(modId);
    }

    public DiscoveredMod? FindById(string modId)
    {
        return DiscoveredMods.FirstOrDefault(
            mod => string.Equals(mod.Manifest.Id, modId, StringComparison.OrdinalIgnoreCase));
    }

    private static void EnsureUniqueIds(IEnumerable<DiscoveredMod> discoveredMods)
    {
        var ids = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var mod in discoveredMods)
        {
            if (!ids.Add(mod.Manifest.Id))
            {
                throw new InvalidOperationException($"Duplicate mod id detected: {mod.Manifest.Id}");
            }
        }
    }

    private static HashSet<string> ResolveEnabledModIds(
        IReadOnlyList<DiscoveredMod> explicitlyEnabledMods,
        IReadOnlyDictionary<string, DiscoveredMod> discoveredById)
    {
        var resolved = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var visiting = new List<string>();

        foreach (var mod in explicitlyEnabledMods)
        {
            ResolveEnabledMod(mod.Manifest.Id, discoveredById, resolved, visiting);
        }

        return resolved;
    }

    private static void ResolveEnabledMod(
        string modId,
        IReadOnlyDictionary<string, DiscoveredMod> discoveredById,
        HashSet<string> resolved,
        List<string> visiting)
    {
        if (resolved.Contains(modId))
        {
            return;
        }

        var cycleStart = visiting.FindIndex(
            visitingModId => string.Equals(visitingModId, modId, StringComparison.OrdinalIgnoreCase));
        if (cycleStart >= 0)
        {
            var cycle = visiting.Skip(cycleStart).Append(modId);
            throw new InvalidOperationException(
                $"Mod dependency cycle detected: {string.Join(" -> ", cycle)}");
        }

        if (!discoveredById.TryGetValue(modId, out var mod))
        {
            throw new InvalidOperationException($"Required mod not found: {modId}");
        }

        visiting.Add(mod.Manifest.Id);
        foreach (var requiredModId in mod.Manifest.RequiredMods)
        {
            if (!discoveredById.ContainsKey(requiredModId))
            {
                throw new InvalidOperationException(
                    $"Mod {mod.Manifest.Id} requires missing mod: {requiredModId}");
            }

            ResolveEnabledMod(requiredModId, discoveredById, resolved, visiting);
        }

        visiting.RemoveAt(visiting.Count - 1);
        resolved.Add(mod.Manifest.Id);
    }
}
