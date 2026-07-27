using System.Text;
using System.Text.Json;

namespace SolomonDarkModLauncher.ModSettings;

public sealed record ModSettingsSnapshot
{
    public IReadOnlyDictionary<string, ModSettingValue> Values { get; init; } =
        new Dictionary<string, ModSettingValue>();
    public IReadOnlyList<string> Warnings { get; init; } =
        Array.Empty<string>();
}

public interface IModSettingsStore
{
    ModSettingsSnapshot Load(
        string stageRootPath,
        string modId,
        ModSettingsDefinition definition);
    void Save(
        string stageRootPath,
        string modId,
        ModSettingsDefinition definition,
        IReadOnlyDictionary<string, ModSettingValue> values);
    string GetSettingsPath(string stageRootPath, string modId);
}

public sealed class ModSettingsStore(
    IModSettingsManifestService manifestService) : IModSettingsStore
{
    private static readonly UTF8Encoding StrictUtf8 =
        new(encoderShouldEmitUTF8Identifier: false, throwOnInvalidBytes: true);

    private readonly IModSettingsManifestService _manifestService =
        manifestService ??
        throw new ArgumentNullException(nameof(manifestService));

    public string GetSettingsPath(
        string stageRootPath,
        string modId)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(stageRootPath);
        ValidateModId(modId);
        return Path.Combine(
            Path.GetFullPath(stageRootPath),
            ".sdmod",
            "mod-settings",
            $"{modId}.json");
    }

    public ModSettingsSnapshot Load(
        string stageRootPath,
        string modId,
        ModSettingsDefinition definition)
    {
        ArgumentNullException.ThrowIfNull(definition);
        var values = Defaults(definition);
        var warnings = new List<string>();
        var path = GetSettingsPath(stageRootPath, modId);
        if (!File.Exists(path))
        {
            return new ModSettingsSnapshot { Values = values };
        }

        try
        {
            using var document = JsonDocument.Parse(
                File.ReadAllText(path, StrictUtf8));
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object)
            {
                warnings.Add("persisted settings root must be an object");
                return Snapshot(values, warnings);
            }
            EnsureOnlyFields(
                root,
                "persisted settings",
                "schemaVersion",
                "values");
            if (!TryGetProperty(
                    root,
                    "schemaVersion",
                    out var schemaVersion) ||
                schemaVersion.ValueKind != JsonValueKind.Number ||
                !schemaVersion.TryGetDouble(out var rawVersion) ||
                rawVersion != 1)
            {
                warnings.Add("persisted settings schemaVersion must be 1");
                return Snapshot(values, warnings);
            }
            if (!TryGetProperty(root, "values", out var stored) ||
                stored.ValueKind != JsonValueKind.Object)
            {
                warnings.Add("persisted settings values must be an object");
                return Snapshot(values, warnings);
            }
            EnsureNoDuplicateFields(stored, "persisted settings values");
            foreach (var property in stored.EnumerateObject())
            {
                var entry = definition.Find(property.Name);
                if (entry is null)
                {
                    warnings.Add(
                        $"ignored unknown persisted setting '{property.Name}'");
                    continue;
                }
                if (entry.Type == ModSettingType.Action)
                {
                    warnings.Add(
                        $"ignored persisted action setting '{property.Name}'");
                    continue;
                }
                if (!TryReadValue(property.Value, out var value))
                {
                    warnings.Add(
                        $"ignored persisted setting '{property.Name}': value must be a boolean, number, or string");
                    continue;
                }
                if (!_manifestService.TryValidateValue(
                        entry,
                        value,
                        out var error))
                {
                    warnings.Add(
                        $"ignored persisted setting '{property.Name}': {error}");
                    continue;
                }
                values[property.Name] = value;
            }
        }
        catch (Exception exception) when (
            exception is JsonException or IOException or
            UnauthorizedAccessException or DecoderFallbackException or
            SettingsStoreFormatException)
        {
            warnings.Add(
                $"persisted settings could not be read: {exception.Message}");
        }
        return Snapshot(values, warnings);
    }

    public void Save(
        string stageRootPath,
        string modId,
        ModSettingsDefinition definition,
        IReadOnlyDictionary<string, ModSettingValue> values)
    {
        ArgumentNullException.ThrowIfNull(definition);
        ArgumentNullException.ThrowIfNull(values);
        var normalized =
            new SortedDictionary<string, ModSettingValue>(
                StringComparer.Ordinal);
        foreach (var pair in values)
        {
            var entry = definition.Find(pair.Key) ??
                throw new InvalidOperationException(
                    $"Unknown mod setting '{pair.Key}'.");
            if (entry.Type == ModSettingType.Action)
            {
                throw new InvalidOperationException(
                    $"Action setting '{pair.Key}' cannot be persisted.");
            }
            if (!_manifestService.TryValidateValue(
                    entry,
                    pair.Value,
                    out var error))
            {
                throw new InvalidOperationException(
                    $"Invalid value for setting '{pair.Key}': {error}");
            }
            normalized.Add(pair.Key, pair.Value);
        }

        var path = GetSettingsPath(stageRootPath, modId);
        var directory = Path.GetDirectoryName(path) ??
            throw new InvalidOperationException(
                "Settings path has no parent directory.");
        Directory.CreateDirectory(directory);
        var temporaryPath = Path.Combine(
            directory,
            $".{Path.GetFileName(path)}.{Guid.NewGuid():N}.tmp");
        try
        {
            using (var stream = new FileStream(
                       temporaryPath,
                       FileMode.CreateNew,
                       FileAccess.Write,
                       FileShare.None,
                       4096,
                       FileOptions.WriteThrough))
            {
                using var writer = new Utf8JsonWriter(
                    stream,
                    new JsonWriterOptions { Indented = true });
                writer.WriteStartObject();
                writer.WriteNumber("schemaVersion", 1);
                writer.WritePropertyName("values");
                writer.WriteStartObject();
                foreach (var pair in normalized)
                {
                    WriteValue(writer, pair.Key, pair.Value);
                }
                writer.WriteEndObject();
                writer.WriteEndObject();
                writer.Flush();
                stream.Flush(flushToDisk: true);
            }
            File.Move(temporaryPath, path, overwrite: true);
        }
        finally
        {
            if (File.Exists(temporaryPath))
            {
                File.Delete(temporaryPath);
            }
        }
    }

    private static Dictionary<string, ModSettingValue> Defaults(
        ModSettingsDefinition definition)
    {
        var values = new Dictionary<string, ModSettingValue>(
            StringComparer.Ordinal);
        foreach (var entry in definition.Entries)
        {
            if (entry.Type != ModSettingType.Action &&
                entry.DefaultValue is not null)
            {
                values.Add(entry.Key, entry.DefaultValue);
            }
        }
        return values;
    }

    private static ModSettingsSnapshot Snapshot(
        IReadOnlyDictionary<string, ModSettingValue> values,
        IReadOnlyList<string> warnings) =>
        new() { Values = values, Warnings = warnings };

    private static bool TryReadValue(
        JsonElement source,
        out ModSettingValue value)
    {
        switch (source.ValueKind)
        {
            case JsonValueKind.True:
                value = ModSettingValue.Boolean(true);
                return true;
            case JsonValueKind.False:
                value = ModSettingValue.Boolean(false);
                return true;
            case JsonValueKind.Number
                when source.TryGetDouble(out var number) &&
                     double.IsFinite(number):
                value = ModSettingValue.Number(number);
                return true;
            case JsonValueKind.String:
                value = ModSettingValue.String(
                    source.GetString() ?? string.Empty);
                return true;
            default:
                value = ModSettingValue.Boolean(false);
                return false;
        }
    }

    private static void WriteValue(
        Utf8JsonWriter writer,
        string key,
        ModSettingValue value)
    {
        switch (value.Type)
        {
            case ModSettingValueType.Boolean:
                writer.WriteBoolean(key, value.BooleanValue);
                break;
            case ModSettingValueType.Number:
                writer.WriteNumber(key, value.NumberValue);
                break;
            case ModSettingValueType.String:
                writer.WriteString(key, value.StringValue);
                break;
        }
    }

    private static void EnsureOnlyFields(
        JsonElement element,
        string prefix,
        params string[] allowedFields)
    {
        var allowed = new HashSet<string>(
            allowedFields,
            StringComparer.Ordinal);
        var seen = new HashSet<string>(StringComparer.Ordinal);
        foreach (var property in element.EnumerateObject())
        {
            if (!seen.Add(property.Name))
            {
                throw new SettingsStoreFormatException(
                    $"{prefix} contains duplicate field '{property.Name}'");
            }
            if (!allowed.Contains(property.Name))
            {
                throw new SettingsStoreFormatException(
                    $"{prefix} contains unknown field '{property.Name}'");
            }
        }
    }

    private static void EnsureNoDuplicateFields(
        JsonElement element,
        string prefix)
    {
        var seen = new HashSet<string>(StringComparer.Ordinal);
        foreach (var property in element.EnumerateObject())
        {
            if (!seen.Add(property.Name))
            {
                throw new SettingsStoreFormatException(
                    $"{prefix} contains duplicate field '{property.Name}'");
            }
        }
    }

    private static bool TryGetProperty(
        JsonElement element,
        string propertyName,
        out JsonElement value)
    {
        foreach (var property in element.EnumerateObject())
        {
            if (string.Equals(
                    property.Name,
                    propertyName,
                    StringComparison.Ordinal))
            {
                value = property.Value;
                return true;
            }
        }
        value = default;
        return false;
    }

    private static void ValidateModId(string modId)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(modId);
        if (modId.Length > 128 ||
            modId[0] is '.' or '_' or '-' ||
            modId[^1] is '.' or '_' or '-' ||
            modId.Any(character =>
                !((character >= 'a' && character <= 'z') ||
                  (character >= '0' && character <= '9') ||
                  character is '.' or '_' or '-')))
        {
            throw new ArgumentException(
                $"Invalid mod identifier '{modId}'.",
                nameof(modId));
        }
    }

    private sealed class SettingsStoreFormatException(string message) :
        Exception(message);
}
