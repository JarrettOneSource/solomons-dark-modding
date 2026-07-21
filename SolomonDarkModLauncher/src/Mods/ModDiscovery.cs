using System.Text.Json;

namespace SolomonDarkModLauncher.Mods;

internal static class ModDiscovery
{
    private const string ManifestFileName = "manifest.json";

    public static IReadOnlyList<DiscoveredMod> Discover(string modsRootPath)
    {
        var mods = new List<DiscoveredMod>();
        foreach (var directoryPath in Directory.EnumerateDirectories(modsRootPath))
        {
            var mod = TryDiscover(directoryPath);
            if (mod is null)
            {
                continue;
            }
            mods.Add(mod);
        }

        return mods;
    }

    public static DiscoveredMod DiscoverRoot(string modRootPath)
    {
        var normalizedRoot = Path.GetFullPath(modRootPath);
        return TryDiscover(normalizedRoot)
            ?? throw new FileNotFoundException(
                "Mod root does not contain manifest.json.",
                Path.Combine(normalizedRoot, ManifestFileName));
    }

    private static DiscoveredMod? TryDiscover(string directoryPath)
    {
        var manifestPath = Path.Combine(directoryPath, ManifestFileName);
        if (!File.Exists(manifestPath))
        {
            return null;
        }

        var manifest = LoadManifest(manifestPath);
        ModManifestValidator.Validate(manifestPath, manifest);
        return new DiscoveredMod(directoryPath, manifestPath, manifest);
    }

    private static ModManifest LoadManifest(string manifestPath)
    {
        var json = File.ReadAllText(manifestPath);
        var manifest = JsonSerializer.Deserialize<ModManifest>(
            json,
            new JsonSerializerOptions
            {
                PropertyNameCaseInsensitive = true
            });

        if (manifest is null)
        {
            throw new InvalidOperationException($"Failed to deserialize manifest: {manifestPath}");
        }

        return manifest;
    }
}
