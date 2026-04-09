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
            var manifestPath = Path.Combine(directoryPath, ManifestFileName);
            if (!File.Exists(manifestPath))
            {
                continue;
            }

            var manifest = LoadManifest(manifestPath);
            ModManifestValidator.Validate(manifestPath, manifest);

            mods.Add(new DiscoveredMod(directoryPath, manifestPath, manifest));
        }

        return mods;
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
