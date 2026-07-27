using System.Text.Json;

namespace SolomonDarkModLauncher.ModSettings;

public sealed record DiscoveredModSettings
{
    public required string ModId { get; init; }
    public required string Name { get; init; }
    public required string Version { get; init; }
    public required string RootPath { get; init; }
    public required string ManifestPath { get; init; }
    public required ModSettingsManifestValidation Validation { get; init; }
}

public interface IModSettingsDiscoveryService
{
    IReadOnlyList<DiscoveredModSettings> Discover(string modsRootPath);
}

public sealed class ModSettingsDiscoveryService(
    IModSettingsManifestService manifestService) :
    IModSettingsDiscoveryService
{
    private readonly IModSettingsManifestService _manifestService =
        manifestService ??
        throw new ArgumentNullException(nameof(manifestService));

    public IReadOnlyList<DiscoveredModSettings> Discover(
        string modsRootPath)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(modsRootPath);
        var discovered = new List<DiscoveredModSettings>();
        if (!Directory.Exists(modsRootPath))
        {
            return discovered;
        }
        foreach (var directory in Directory.EnumerateDirectories(
                     modsRootPath)
                 .OrderBy(path => path, StringComparer.OrdinalIgnoreCase))
        {
            if (Path.GetFileName(directory).StartsWith(
                    ".sdmod-",
                    StringComparison.Ordinal))
            {
                continue;
            }
            var manifestPath = Path.Combine(directory, "manifest.json");
            if (!File.Exists(manifestPath))
            {
                continue;
            }
            var validation =
                _manifestService.ValidateFile(manifestPath);
            if (validation.Status == ModSettingsManifestStatus.None)
            {
                continue;
            }
            var metadata = ReadMetadata(manifestPath);
            discovered.Add(new DiscoveredModSettings
            {
                ModId = metadata.Id,
                Name = metadata.Name,
                Version = metadata.Version,
                RootPath = directory,
                ManifestPath = manifestPath,
                Validation = validation
            });
        }
        return discovered;
    }

    private static (string Id, string Name, string Version) ReadMetadata(
        string manifestPath)
    {
        try
        {
            using var document = JsonDocument.Parse(
                File.ReadAllText(manifestPath));
            var root = document.RootElement;
            return (
                ReadString(root, "id"),
                ReadString(root, "name"),
                ReadString(root, "version"));
        }
        catch (Exception exception) when (
            exception is JsonException or IOException or
            UnauthorizedAccessException)
        {
            return (
                Path.GetFileName(
                    Path.GetDirectoryName(manifestPath)) ??
                    string.Empty,
                string.Empty,
                string.Empty);
        }
    }

    private static string ReadString(
        JsonElement root,
        string propertyName)
    {
        if (root.ValueKind != JsonValueKind.Object)
        {
            return string.Empty;
        }
        foreach (var property in root.EnumerateObject())
        {
            if (string.Equals(
                    property.Name,
                    propertyName,
                    StringComparison.Ordinal) &&
                property.Value.ValueKind == JsonValueKind.String)
            {
                return property.Value.GetString() ?? string.Empty;
            }
        }
        return string.Empty;
    }
}
