namespace SolomonDarkModLauncher.ModSettings;

public enum ModSettingType
{
    Toggle,
    Number,
    Text,
    Choice,
    Keybind,
    Action,
    List
}

public enum ModSettingScope
{
    Local,
    Host
}

public enum ModSettingValueType
{
    Boolean,
    Number,
    String,
    List
}

public sealed record ModSettingValue
{
    private ModSettingValue(
        ModSettingValueType type,
        bool booleanValue,
        double numberValue,
        string stringValue,
        IReadOnlyList<IReadOnlyDictionary<string, ModSettingValue>> listValue)
    {
        Type = type;
        BooleanValue = booleanValue;
        NumberValue = numberValue;
        StringValue = stringValue;
        ListValue = listValue;
    }

    public ModSettingValueType Type { get; }
    public bool BooleanValue { get; }
    public double NumberValue { get; }
    public string StringValue { get; }
    public IReadOnlyList<IReadOnlyDictionary<string, ModSettingValue>>
        ListValue { get; }

    public static ModSettingValue Boolean(bool value) =>
        new(
            ModSettingValueType.Boolean,
            value,
            0,
            string.Empty,
            Array.Empty<IReadOnlyDictionary<string, ModSettingValue>>());

    public static ModSettingValue Number(double value) =>
        new(
            ModSettingValueType.Number,
            false,
            value,
            string.Empty,
            Array.Empty<IReadOnlyDictionary<string, ModSettingValue>>());

    public static ModSettingValue String(string value) =>
        new(
            ModSettingValueType.String,
            false,
            0,
            value ?? throw new ArgumentNullException(nameof(value)),
            Array.Empty<IReadOnlyDictionary<string, ModSettingValue>>());

    public static ModSettingValue List(
        IEnumerable<IReadOnlyDictionary<string, ModSettingValue>> value)
    {
        ArgumentNullException.ThrowIfNull(value);
        var items = value
            .Select(item =>
            {
                ArgumentNullException.ThrowIfNull(item);
                var copy =
                    new SortedDictionary<string, ModSettingValue>(
                        StringComparer.Ordinal);
                foreach (var pair in item)
                {
                    copy.Add(
                        pair.Key,
                        pair.Value ??
                            throw new ArgumentException(
                                "List values cannot contain null fields.",
                                nameof(value)));
                }
                return (IReadOnlyDictionary<string, ModSettingValue>)
                    new System.Collections.ObjectModel.ReadOnlyDictionary<
                        string,
                        ModSettingValue>(copy);
            })
            .ToArray();
        return new(
            ModSettingValueType.List,
            false,
            0,
            string.Empty,
            Array.AsReadOnly(items));
    }
}

public sealed record ModSettingChoice(string Value, string Label);

public sealed record ModSettingDefinition
{
    public required string Key { get; init; }
    public required ModSettingType Type { get; init; }
    public required string Label { get; init; }
    public string Description { get; init; } = string.Empty;
    public string Group { get; init; } = string.Empty;
    public ModSettingScope Scope { get; init; } = ModSettingScope.Local;
    public bool RequiresRestart { get; init; }
    public ModSettingValue? DefaultValue { get; init; }
    public double Minimum { get; init; }
    public double Maximum { get; init; }
    public double Step { get; init; } = 1;
    public bool Integer { get; init; }
    public int MaxLength { get; init; } = 256;
    public string Placeholder { get; init; } = string.Empty;
    public IReadOnlyList<ModSettingChoice> Choices { get; init; } =
        Array.Empty<ModSettingChoice>();
    public bool Confirm { get; init; }
    public int MinItems { get; init; }
    public int MaxItems { get; init; }
    public string ItemLabel { get; init; } = string.Empty;
    public IReadOnlyList<ModSettingDefinition> ItemFields { get; init; } =
        Array.Empty<ModSettingDefinition>();

    public ModSettingDefinition? FindItemField(string key) =>
        ItemFields.FirstOrDefault(field =>
            string.Equals(field.Key, key, StringComparison.Ordinal));
}

public sealed record ModSettingsDefinition
{
    public int Version { get; init; } = 1;
    public IReadOnlyList<ModSettingDefinition> Entries { get; init; } =
        Array.Empty<ModSettingDefinition>();

    public ModSettingDefinition? Find(string key) =>
        Entries.FirstOrDefault(entry =>
            string.Equals(entry.Key, key, StringComparison.Ordinal));
}

public enum ModSettingsManifestStatus
{
    None,
    Valid,
    Invalid
}

public sealed record ModSettingsManifestValidation
{
    public required ModSettingsManifestStatus Status { get; init; }
    public ModSettingsDefinition? Definition { get; init; }
    public string Error { get; init; } = string.Empty;

    public static ModSettingsManifestValidation None() =>
        new() { Status = ModSettingsManifestStatus.None };

    public static ModSettingsManifestValidation Valid(
        ModSettingsDefinition definition) =>
        new()
        {
            Status = ModSettingsManifestStatus.Valid,
            Definition = definition
        };

    public static ModSettingsManifestValidation Invalid(string error) =>
        new()
        {
            Status = ModSettingsManifestStatus.Invalid,
            Error = error
        };
}

public interface IModSettingsManifestService
{
    IReadOnlyList<string> CanonicalKeybindNames { get; }
    ModSettingsManifestValidation ValidateFile(string manifestPath);
    ModSettingsManifestValidation ValidateJson(string manifestJson);
    bool TryValidateValue(
        ModSettingDefinition entry,
        ModSettingValue value,
        out string error);
    bool TryNormalizeValue(
        ModSettingDefinition entry,
        ModSettingValue value,
        out ModSettingValue normalized,
        out string error);
}
