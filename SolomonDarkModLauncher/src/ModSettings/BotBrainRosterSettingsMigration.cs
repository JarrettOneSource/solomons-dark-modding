using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace SolomonDarkModLauncher.ModSettings;

public static class BotBrainRosterSettingsMigration
{
    public const string ModId = "bot.brain";

    private static readonly HashSet<string> LegacyBehaviorValues =
        new(StringComparer.Ordinal)
        {
            "skirmisher",
            "guardian",
            "striker"
        };

    private static readonly UTF8Encoding StrictUtf8 =
        new(encoderShouldEmitUTF8Identifier: false, throwOnInvalidBytes: true);

    public static bool TryMigrateStage(string stageRootPath)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(stageRootPath);
        return TryMigrateFile(Path.Combine(
            Path.GetFullPath(stageRootPath),
            ".sdmod",
            "mod-settings",
            $"{ModId}.json"));
    }

    public static bool TryMigrateFile(string settingsPath)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(settingsPath);
        if (!File.Exists(settingsPath))
        {
            return false;
        }

        try
        {
            var source = File.ReadAllText(settingsPath, StrictUtf8);
            using (var document = JsonDocument.Parse(source))
            {
                if (!HasMigrationShape(document.RootElement))
                {
                    return false;
                }
            }

            var root = JsonNode.Parse(source) as JsonObject;
            var roster = root?["values"]?["roster"] as JsonArray;
            if (root is null || roster is null)
            {
                return false;
            }

            var changed = false;
            foreach (var item in roster)
            {
                if (item is not JsonObject row ||
                    row.ContainsKey("behavior") ||
                    row["discipline"] is not JsonValue legacyValue ||
                    !legacyValue.TryGetValue<string>(out var legacyBehavior) ||
                    !LegacyBehaviorValues.Contains(legacyBehavior))
                {
                    continue;
                }

                row["behavior"] = legacyBehavior;
                row["discipline"] = "arcane";
                changed = true;
            }
            if (!changed)
            {
                return false;
            }

            WriteAtomically(settingsPath, root);
            return true;
        }
        catch (Exception exception) when (
            exception is JsonException or IOException or
            UnauthorizedAccessException or DecoderFallbackException)
        {
            return false;
        }
    }

    private static bool HasMigrationShape(JsonElement root)
    {
        if (root.ValueKind != JsonValueKind.Object ||
            HasDuplicateProperties(root) ||
            !root.TryGetProperty("schemaVersion", out var schemaVersion) ||
            schemaVersion.ValueKind != JsonValueKind.Number ||
            !schemaVersion.TryGetInt32(out var version) ||
            version != 1 ||
            !root.TryGetProperty("values", out var values) ||
            values.ValueKind != JsonValueKind.Object ||
            HasDuplicateProperties(values) ||
            !values.TryGetProperty("roster", out var roster) ||
            roster.ValueKind != JsonValueKind.Array)
        {
            return false;
        }

        foreach (var item in roster.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.Object ||
                HasDuplicateProperties(item))
            {
                return false;
            }
        }
        return true;
    }

    private static bool HasDuplicateProperties(JsonElement value)
    {
        var names = new HashSet<string>(StringComparer.Ordinal);
        return value.EnumerateObject().Any(
            property => !names.Add(property.Name));
    }

    private static void WriteAtomically(
        string settingsPath,
        JsonObject root)
    {
        var directory = Path.GetDirectoryName(settingsPath) ??
            throw new InvalidOperationException(
                "Bot-brain settings path has no parent directory.");
        var temporaryPath = Path.Combine(
            directory,
            $".{Path.GetFileName(settingsPath)}.{Guid.NewGuid():N}.tmp");
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
                root.WriteTo(writer);
                writer.Flush();
                stream.Flush(flushToDisk: true);
            }
            File.Move(temporaryPath, settingsPath, overwrite: true);
        }
        finally
        {
            if (File.Exists(temporaryPath))
            {
                File.Delete(temporaryPath);
            }
        }
    }
}
