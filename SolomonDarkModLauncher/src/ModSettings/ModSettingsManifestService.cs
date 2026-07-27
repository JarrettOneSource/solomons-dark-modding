using System.Buffers;
using System.Globalization;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace SolomonDarkModLauncher.ModSettings;

public sealed partial class ModSettingsManifestService :
    IModSettingsManifestService
{
    private static readonly string[] KeybindNames =
    [
        "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L",
        "M", "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X",
        "Y", "Z",
        "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
        "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10",
        "F11", "F12", "F13", "F14", "F15", "F16", "F17", "F18",
        "F19", "F20", "F21", "F22", "F23", "F24",
        "SPACE", "TAB", "ENTER", "SHIFT", "CTRL", "ALT",
        "UP", "DOWN", "LEFT", "RIGHT",
        "MOUSE3", "MOUSE4", "MOUSE5", "NONE"
    ];

    private static readonly HashSet<string> KeybindNameSet =
        new(KeybindNames, StringComparer.Ordinal);

    private static readonly UTF8Encoding StrictUtf8 =
        new(encoderShouldEmitUTF8Identifier: false, throwOnInvalidBytes: true);

    private static readonly HashSet<string> CommonFields =
        new(
        [
            "key", "type", "label", "description", "group", "scope",
            "requires_restart", "default"
        ],
        StringComparer.Ordinal);

    public IReadOnlyList<string> CanonicalKeybindNames => KeybindNames;

    public ModSettingsManifestValidation ValidateFile(string manifestPath)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(manifestPath);
        try
        {
            return ValidateJson(
                File.ReadAllText(manifestPath, StrictUtf8));
        }
        catch (Exception exception) when (
            exception is IOException or UnauthorizedAccessException or
            DecoderFallbackException)
        {
            return ModSettingsManifestValidation.Invalid(
                $"unable to read manifest: {exception.Message}");
        }
    }

    public ModSettingsManifestValidation ValidateJson(string manifestJson)
    {
        ArgumentNullException.ThrowIfNull(manifestJson);
        try
        {
            using var document = JsonDocument.Parse(manifestJson);
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object)
            {
                return ModSettingsManifestValidation.Invalid(
                    "manifest root must be an object");
            }
            EnsureNoDuplicateProperties(root, "manifest");
            if (!TryGetProperty(root, "settings", out var settings))
            {
                return ModSettingsManifestValidation.None();
            }
            return ModSettingsManifestValidation.Valid(
                ParseSettings(settings));
        }
        catch (JsonException exception)
        {
            return ModSettingsManifestValidation.Invalid(
                $"manifest JSON is invalid: {exception.Message}");
        }
        catch (InvalidOperationException exception)
        {
            return ModSettingsManifestValidation.Invalid(
                $"manifest JSON contains invalid UTF-8 text: {exception.Message}");
        }
        catch (SettingsValidationException exception)
        {
            return ModSettingsManifestValidation.Invalid(exception.Message);
        }
    }

    public bool TryValidateValue(
        ModSettingDefinition entry,
        ModSettingValue value,
        out string error) =>
        TryNormalizeValue(entry, value, out _, out error);

    public bool TryNormalizeValue(
        ModSettingDefinition entry,
        ModSettingValue value,
        out ModSettingValue normalized,
        out string error)
    {
        ArgumentNullException.ThrowIfNull(entry);
        ArgumentNullException.ThrowIfNull(value);
        normalized = value;
        error = string.Empty;
        switch (entry.Type)
        {
            case ModSettingType.Toggle:
                if (value.Type != ModSettingValueType.Boolean)
                {
                    error = "value must be a boolean";
                    return false;
                }
                return true;
            case ModSettingType.Number:
                if (value.Type != ModSettingValueType.Number ||
                    !double.IsFinite(value.NumberValue))
                {
                    error = "value must be a finite number";
                    return false;
                }
                if (value.NumberValue < entry.Minimum ||
                    value.NumberValue > entry.Maximum)
                {
                    error = "value is outside min and max";
                    return false;
                }
                if (entry.Integer && !IsIntegral(value.NumberValue))
                {
                    error = "value must be integral when integer is true";
                    return false;
                }
                return true;
            case ModSettingType.Text:
                if (value.Type != ModSettingValueType.String)
                {
                    error = "value must be a string";
                    return false;
                }
                int byteCount;
                try
                {
                    byteCount = StrictUtf8.GetByteCount(value.StringValue);
                }
                catch (EncoderFallbackException)
                {
                    error = "value must be valid UTF-8";
                    return false;
                }
                if (value.StringValue.Contains('\r') ||
                    value.StringValue.Contains('\n'))
                {
                    error = "value must be a single line";
                    return false;
                }
                if (byteCount > entry.MaxLength)
                {
                    error = "value exceeds max_length UTF-8 bytes";
                    return false;
                }
                return true;
            case ModSettingType.Choice:
                if (value.Type != ModSettingValueType.String)
                {
                    error = "value must be a string";
                    return false;
                }
                if (!entry.Choices.Any(choice =>
                        string.Equals(
                            choice.Value,
                            value.StringValue,
                            StringComparison.Ordinal)))
                {
                    error = "value is not a declared choice";
                    return false;
                }
                return true;
            case ModSettingType.Keybind:
                if (value.Type != ModSettingValueType.String ||
                    !KeybindNameSet.Contains(value.StringValue))
                {
                    error = "value is not a canonical keybind name";
                    return false;
                }
                return true;
            case ModSettingType.Action:
                error = "action entries do not have values";
                return false;
            case ModSettingType.List:
                return TryNormalizeListValue(
                    entry,
                    value,
                    out normalized,
                    out error);
            default:
                error = "setting type is invalid";
                return false;
        }
    }

    private ModSettingsDefinition ParseSettings(JsonElement settings)
    {
        RequireKind(settings, JsonValueKind.Object, "settings must be an object");
        EnsureOnlyFields(settings, "settings", "version", "entries");
        var version = RequireNumber(settings, "version", "settings");
        if (version != 1)
        {
            throw new SettingsValidationException(
                "settings.version must be 1");
        }
        var entriesElement = RequireProperty(
            settings,
            "entries",
            JsonValueKind.Array,
            "settings");
        var entries = new List<ModSettingDefinition>();
        var keys = new HashSet<string>(StringComparer.Ordinal);
        var index = 0;
        foreach (var entry in entriesElement.EnumerateArray())
        {
            var parsed = ParseEntry(entry, index);
            if (!keys.Add(parsed.Key))
            {
                throw new SettingsValidationException(
                    $"settings.entries contains duplicate key '{parsed.Key}'");
            }
            entries.Add(parsed);
            index++;
        }
        return new ModSettingsDefinition { Entries = entries };
    }

    private ModSettingDefinition ParseEntry(
        JsonElement element,
        int index)
    {
        var prefix = $"settings.entries[{index}]";
        RequireKind(
            element,
            JsonValueKind.Object,
            $"{prefix} must be an object");
        EnsureNoDuplicateProperties(element, prefix);

        var key = RequireString(element, "key", prefix);
        if (!SettingKeyRegex().IsMatch(key))
        {
            throw new SettingsValidationException(
                $"{prefix}.key must match ^[a-z0-9_]{{1,48}}$");
        }
        var typeName = RequireString(element, "type", prefix);
        var type = typeName switch
        {
            "toggle" => ModSettingType.Toggle,
            "number" => ModSettingType.Number,
            "text" => ModSettingType.Text,
            "choice" => ModSettingType.Choice,
            "keybind" => ModSettingType.Keybind,
            "action" => ModSettingType.Action,
            "list" => ModSettingType.List,
            _ => throw new SettingsValidationException(
                $"{prefix}.type is not a supported settings type")
        };
        EnsureOnlyFields(
            element,
            prefix,
            AllowedFieldsForType(type).ToArray());

        var label = RequireString(element, "label", prefix);
        ValidateCharacterCount(label, 1, 64, $"{prefix}.label");
        var description = OptionalString(
            element,
            "description",
            prefix);
        ValidateCharacterCount(
            description,
            0,
            256,
            $"{prefix}.description");
        var group = OptionalString(element, "group", prefix);
        ValidateCharacterCount(group, 0, 32, $"{prefix}.group");
        var scope = ParseScope(element, prefix);
        var requiresRestart = OptionalBoolean(
            element,
            "requires_restart",
            prefix);

        var minimum = 0d;
        var maximum = 0d;
        var step = 1d;
        var integer = false;
        var maxLength = 256;
        var placeholder = string.Empty;
        IReadOnlyList<ModSettingChoice> choices =
            Array.Empty<ModSettingChoice>();
        var confirm = false;
        ParsedListSchema? listSchema = null;

        if (type == ModSettingType.Number)
        {
            minimum = RequireNumber(element, "min", prefix);
            maximum = RequireNumber(element, "max", prefix);
            if (!(minimum < maximum))
            {
                throw new SettingsValidationException(
                    $"{prefix}.min must be less than max");
            }
            step = OptionalNumber(element, "step", prefix, 1);
            if (!(step > 0))
            {
                throw new SettingsValidationException(
                    $"{prefix}.step must be a number greater than zero");
            }
            integer = OptionalBoolean(element, "integer", prefix);
            if (integer &&
                (!IsIntegral(minimum) ||
                 !IsIntegral(maximum) ||
                 !IsIntegral(step)))
            {
                throw new SettingsValidationException(
                    $"{prefix}.min, max, and step must be integral when integer is true");
            }
        }
        else if (type == ModSettingType.Text)
        {
            var rawMaxLength = OptionalNumber(
                element,
                "max_length",
                prefix,
                256);
            if (!IsIntegral(rawMaxLength) ||
                rawMaxLength < 1 ||
                rawMaxLength > 1024)
            {
                throw new SettingsValidationException(
                    $"{prefix}.max_length must be an integer from 1 through 1024");
            }
            maxLength = checked((int)rawMaxLength);
            placeholder = OptionalString(
                element,
                "placeholder",
                prefix);
            ValidateUnicode(
                placeholder,
                $"{prefix}.placeholder");
        }
        else if (type == ModSettingType.Choice)
        {
            choices = ParseChoices(element, prefix);
        }
        else if (type == ModSettingType.Action)
        {
            if (TryGetProperty(element, "default", out _))
            {
                throw new SettingsValidationException(
                    $"{prefix}.default is forbidden for action entries");
            }
            confirm = OptionalBoolean(element, "confirm", prefix);
        }
        else if (type == ModSettingType.List)
        {
            listSchema = ParseListSchema(element, prefix);
        }

        ModSettingValue? defaultValue = null;
        if (type != ModSettingType.Action)
        {
            if (!TryGetProperty(element, "default", out var defaultElement))
            {
                throw new SettingsValidationException(
                    $"{prefix}.default is required for non-action entries");
            }
            defaultValue = type == ModSettingType.List
                ? ReadListValue(defaultElement, $"{prefix}.default")
                : ReadValue(defaultElement, $"{prefix}.default");
        }

        var result = new ModSettingDefinition
        {
            Key = key,
            Type = type,
            Label = label,
            Description = description,
            Group = group,
            Scope = scope,
            RequiresRestart = requiresRestart,
            DefaultValue = defaultValue,
            Minimum = minimum,
            Maximum = maximum,
            Step = step,
            Integer = integer,
            MaxLength = maxLength,
            Placeholder = placeholder,
            Choices = choices,
            Confirm = confirm,
            MinItems = listSchema?.MinItems ?? 0,
            MaxItems = listSchema?.MaxItems ?? 0,
            ItemLabel = listSchema?.ItemLabel ?? string.Empty,
            ItemFields = listSchema?.ItemFields ??
                Array.Empty<ModSettingDefinition>()
        };
        if (defaultValue is null)
        {
            return result;
        }
        if (!TryNormalizeValue(
                result,
                defaultValue,
                out var normalizedDefault,
                out var valueError))
        {
            throw new SettingsValidationException(
                $"{prefix}.default is invalid: {valueError}");
        }
        return result with { DefaultValue = normalizedDefault };
    }

    private static IReadOnlyList<ModSettingChoice> ParseChoices(
        JsonElement entry,
        string prefix)
    {
        var source = RequireProperty(
            entry,
            "choices",
            JsonValueKind.Array,
            prefix);
        var count = source.GetArrayLength();
        if (count < 2 || count > 32)
        {
            throw new SettingsValidationException(
                $"{prefix}.choices must be an array containing 2-32 choices");
        }
        var choices = new List<ModSettingChoice>();
        var values = new HashSet<string>(StringComparer.Ordinal);
        var index = 0;
        foreach (var choice in source.EnumerateArray())
        {
            var choicePrefix = $"{prefix}.choices[{index}]";
            RequireKind(
                choice,
                JsonValueKind.Object,
                $"{choicePrefix} must be an object");
            EnsureOnlyFields(choice, choicePrefix, "value", "label");
            var value = RequireString(choice, "value", choicePrefix);
            ValidateCharacterCount(
                value,
                1,
                64,
                $"{choicePrefix}.value");
            var label = RequireString(choice, "label", choicePrefix);
            ValidateUnicode(label, $"{choicePrefix}.label");
            if (!values.Add(value))
            {
                throw new SettingsValidationException(
                    $"{prefix}.choices contains duplicate value '{value}'");
            }
            choices.Add(new ModSettingChoice(value, label));
            index++;
        }
        return choices;
    }

    private static ModSettingScope ParseScope(
        JsonElement entry,
        string prefix)
    {
        if (!TryGetProperty(entry, "scope", out var scope))
        {
            return ModSettingScope.Local;
        }
        if (scope.ValueKind != JsonValueKind.String)
        {
            throw new SettingsValidationException(
                $"{prefix}.scope must be 'local' or 'host'");
        }
        return scope.GetString() switch
        {
            "local" => ModSettingScope.Local,
            "host" => ModSettingScope.Host,
            _ => throw new SettingsValidationException(
                $"{prefix}.scope must be 'local' or 'host'")
        };
    }

    private static ModSettingValue ReadValue(
        JsonElement value,
        string prefix) =>
        value.ValueKind switch
        {
            JsonValueKind.True => ModSettingValue.Boolean(true),
            JsonValueKind.False => ModSettingValue.Boolean(false),
            JsonValueKind.Number when value.TryGetDouble(out var number) &&
                                      double.IsFinite(number) =>
                ModSettingValue.Number(number),
            JsonValueKind.String =>
                ModSettingValue.String(value.GetString() ?? string.Empty),
            _ => throw new SettingsValidationException(
                $"{prefix} setting value must be a boolean, number, or string")
        };

    private static HashSet<string> AllowedFieldsForType(
        ModSettingType type)
    {
        var fields = new HashSet<string>(CommonFields, StringComparer.Ordinal);
        switch (type)
        {
            case ModSettingType.Number:
                fields.UnionWith(["min", "max", "step", "integer"]);
                break;
            case ModSettingType.Text:
                fields.UnionWith(["max_length", "placeholder"]);
                break;
            case ModSettingType.Choice:
                fields.Add("choices");
                break;
            case ModSettingType.Action:
                fields.Add("confirm");
                break;
            case ModSettingType.List:
                fields.UnionWith(
                    ["min_items", "max_items", "item_label", "item"]);
                break;
        }
        return fields;
    }

    private static string RequireString(
        JsonElement element,
        string propertyName,
        string prefix)
    {
        var property = RequireProperty(
            element,
            propertyName,
            JsonValueKind.String,
            prefix);
        return property.GetString() ?? string.Empty;
    }

    private static string OptionalString(
        JsonElement element,
        string propertyName,
        string prefix)
    {
        if (!TryGetProperty(element, propertyName, out var property))
        {
            return string.Empty;
        }
        if (property.ValueKind != JsonValueKind.String)
        {
            throw new SettingsValidationException(
                $"{prefix}.{propertyName} must be a string");
        }
        return property.GetString() ?? string.Empty;
    }

    private static double RequireNumber(
        JsonElement element,
        string propertyName,
        string prefix)
    {
        var property = RequireProperty(
            element,
            propertyName,
            JsonValueKind.Number,
            prefix);
        if (!property.TryGetDouble(out var value) ||
            !double.IsFinite(value))
        {
            throw new SettingsValidationException(
                $"{prefix}.{propertyName} must be a number");
        }
        return value;
    }

    private static double OptionalNumber(
        JsonElement element,
        string propertyName,
        string prefix,
        double defaultValue)
    {
        if (!TryGetProperty(element, propertyName, out var property))
        {
            return defaultValue;
        }
        if (property.ValueKind != JsonValueKind.Number ||
            !property.TryGetDouble(out var value) ||
            !double.IsFinite(value))
        {
            throw new SettingsValidationException(
                $"{prefix}.{propertyName} must be a number");
        }
        return value;
    }

    private static bool OptionalBoolean(
        JsonElement element,
        string propertyName,
        string prefix)
    {
        if (!TryGetProperty(element, propertyName, out var property))
        {
            return false;
        }
        if (property.ValueKind is not
            (JsonValueKind.True or JsonValueKind.False))
        {
            throw new SettingsValidationException(
                $"{prefix}.{propertyName} must be a boolean");
        }
        return property.GetBoolean();
    }

    private static JsonElement RequireProperty(
        JsonElement element,
        string propertyName,
        JsonValueKind kind,
        string prefix)
    {
        if (!TryGetProperty(element, propertyName, out var property) ||
            property.ValueKind != kind)
        {
            var typeName = kind switch
            {
                JsonValueKind.Array => "an array",
                JsonValueKind.Object => "an object",
                JsonValueKind.String => "a string",
                JsonValueKind.Number => "a number",
                _ => kind.ToString().ToLowerInvariant()
            };
            throw new SettingsValidationException(
                $"{prefix}.{propertyName} must be {typeName}");
        }
        return property;
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
                throw new SettingsValidationException(
                    $"{prefix} contains duplicate field '{property.Name}'");
            }
            if (!allowed.Contains(property.Name))
            {
                throw new SettingsValidationException(
                    $"{prefix} contains unknown field '{property.Name}'");
            }
        }
    }

    private static void EnsureNoDuplicateProperties(
        JsonElement element,
        string prefix)
    {
        var seen = new HashSet<string>(StringComparer.Ordinal);
        foreach (var property in element.EnumerateObject())
        {
            if (!seen.Add(property.Name))
            {
                throw new SettingsValidationException(
                    $"{prefix} contains duplicate field '{property.Name}'");
            }
        }
    }

    private static void RequireKind(
        JsonElement element,
        JsonValueKind kind,
        string error)
    {
        if (element.ValueKind != kind)
        {
            throw new SettingsValidationException(error);
        }
    }

    private static void ValidateCharacterCount(
        string value,
        int minimum,
        int maximum,
        string field)
    {
        ValidateUnicode(value, field);
        var count = value.EnumerateRunes().Count();
        if (count < minimum || count > maximum)
        {
            throw new SettingsValidationException(
                $"{field} must contain {minimum}-{maximum} characters");
        }
    }

    private static void ValidateUnicode(string value, string field)
    {
        try
        {
            _ = StrictUtf8.GetByteCount(value);
        }
        catch (EncoderFallbackException)
        {
            throw new SettingsValidationException(
                $"{field} must be valid UTF-8");
        }
    }

    public const int MaximumSerializedListValueBytes = 8192;

    private sealed record ParsedListSchema(
        int MinItems,
        int MaxItems,
        string ItemLabel,
        IReadOnlyList<ModSettingDefinition> ItemFields);

    private ParsedListSchema ParseListSchema(
        JsonElement element,
        string prefix)
    {
        var rawMaxItems = RequireNumber(element, "max_items", prefix);
        if (!IsIntegral(rawMaxItems) ||
            rawMaxItems < 1 ||
            rawMaxItems > 32)
        {
            throw new SettingsValidationException(
                $"{prefix}.max_items must be an integer from 1 through 32");
        }
        var maxItems = checked((int)rawMaxItems);
        var rawMinItems = OptionalNumber(
            element,
            "min_items",
            prefix,
            0);
        if (!IsIntegral(rawMinItems) ||
            rawMinItems < 0 ||
            rawMinItems > maxItems)
        {
            throw new SettingsValidationException(
                $"{prefix}.min_items must be an integer from 0 through max_items");
        }
        var minItems = checked((int)rawMinItems);

        var itemLabel = OptionalString(element, "item_label", prefix);
        ValidateCharacterCount(
            itemLabel,
            0,
            64,
            $"{prefix}.item_label");
        var item = RequireProperty(
            element,
            "item",
            JsonValueKind.Object,
            prefix);
        EnsureOnlyFields(item, $"{prefix}.item", "fields");
        var fieldsElement = RequireProperty(
            item,
            "fields",
            JsonValueKind.Array,
            $"{prefix}.item");
        if (fieldsElement.GetArrayLength() is < 1 or > 12)
        {
            throw new SettingsValidationException(
                $"{prefix}.item.fields must contain 1-12 fields");
        }

        var fields = new List<ModSettingDefinition>();
        var keys = new HashSet<string>(StringComparer.Ordinal);
        var index = 0;
        foreach (var fieldElement in fieldsElement.EnumerateArray())
        {
            var field = ParseListItemField(
                fieldElement,
                $"{prefix}.item.fields[{index}]");
            if (!keys.Add(field.Key))
            {
                throw new SettingsValidationException(
                    $"{prefix}.item.fields contains duplicate key '{field.Key}'");
            }
            fields.Add(field);
            index++;
        }
        ValidateItemLabel(itemLabel, fields, prefix);
        return new ParsedListSchema(
            minItems,
            maxItems,
            itemLabel,
            fields);
    }

    private ModSettingDefinition ParseListItemField(
        JsonElement element,
        string prefix)
    {
        RequireKind(
            element,
            JsonValueKind.Object,
            $"{prefix} must be an object");
        EnsureNoDuplicateProperties(element, prefix);
        var key = RequireString(element, "key", prefix);
        if (!SettingKeyRegex().IsMatch(key))
        {
            throw new SettingsValidationException(
                $"{prefix}.key must match ^[a-z0-9_]{{1,48}}$");
        }
        var typeName = RequireString(element, "type", prefix);
        var type = typeName switch
        {
            "toggle" => ModSettingType.Toggle,
            "number" => ModSettingType.Number,
            "text" => ModSettingType.Text,
            "choice" => ModSettingType.Choice,
            _ => throw new SettingsValidationException(
                $"{prefix}.type must be toggle, number, text, or choice")
        };
        EnsureOnlyFields(
            element,
            prefix,
            AllowedListItemFields(type).ToArray());

        var label = RequireString(element, "label", prefix);
        ValidateCharacterCount(label, 1, 64, $"{prefix}.label");
        var description = OptionalString(
            element,
            "description",
            prefix);
        ValidateCharacterCount(
            description,
            0,
            256,
            $"{prefix}.description");

        var minimum = 0d;
        var maximum = 0d;
        var step = 1d;
        var integer = false;
        var maxLength = 256;
        var placeholder = string.Empty;
        IReadOnlyList<ModSettingChoice> choices =
            Array.Empty<ModSettingChoice>();
        if (type == ModSettingType.Number)
        {
            minimum = RequireNumber(element, "min", prefix);
            maximum = RequireNumber(element, "max", prefix);
            if (!(minimum < maximum))
            {
                throw new SettingsValidationException(
                    $"{prefix}.min must be less than max");
            }
            step = OptionalNumber(element, "step", prefix, 1);
            if (!(step > 0))
            {
                throw new SettingsValidationException(
                    $"{prefix}.step must be a number greater than zero");
            }
            integer = OptionalBoolean(element, "integer", prefix);
            if (integer &&
                (!IsIntegral(minimum) ||
                 !IsIntegral(maximum) ||
                 !IsIntegral(step)))
            {
                throw new SettingsValidationException(
                    $"{prefix}.min, max, and step must be integral when integer is true");
            }
        }
        else if (type == ModSettingType.Text)
        {
            var rawMaxLength = OptionalNumber(
                element,
                "max_length",
                prefix,
                256);
            if (!IsIntegral(rawMaxLength) ||
                rawMaxLength < 1 ||
                rawMaxLength > 1024)
            {
                throw new SettingsValidationException(
                    $"{prefix}.max_length must be an integer from 1 through 1024");
            }
            maxLength = checked((int)rawMaxLength);
            placeholder = OptionalString(
                element,
                "placeholder",
                prefix);
            ValidateUnicode(placeholder, $"{prefix}.placeholder");
        }
        else if (type == ModSettingType.Choice)
        {
            choices = ParseChoices(element, prefix);
        }

        if (!TryGetProperty(element, "default", out var defaultElement))
        {
            throw new SettingsValidationException(
                $"{prefix}.default is required");
        }
        var defaultValue = ReadValue(
            defaultElement,
            $"{prefix}.default");
        var result = new ModSettingDefinition
        {
            Key = key,
            Type = type,
            Label = label,
            Description = description,
            DefaultValue = defaultValue,
            Minimum = minimum,
            Maximum = maximum,
            Step = step,
            Integer = integer,
            MaxLength = maxLength,
            Placeholder = placeholder,
            Choices = choices
        };
        if (!TryNormalizeValue(
                result,
                defaultValue,
                out var normalizedDefault,
                out var valueError))
        {
            throw new SettingsValidationException(
                $"{prefix}.default is invalid: {valueError}");
        }
        return result with { DefaultValue = normalizedDefault };
    }

    private static HashSet<string> AllowedListItemFields(
        ModSettingType type)
    {
        var fields = new HashSet<string>(
            ["key", "type", "label", "description", "default"],
            StringComparer.Ordinal);
        switch (type)
        {
            case ModSettingType.Number:
                fields.UnionWith(["min", "max", "step", "integer"]);
                break;
            case ModSettingType.Text:
                fields.UnionWith(["max_length", "placeholder"]);
                break;
            case ModSettingType.Choice:
                fields.Add("choices");
                break;
        }
        return fields;
    }

    private static ModSettingValue ReadListValue(
        JsonElement source,
        string prefix)
    {
        RequireKind(
            source,
            JsonValueKind.Array,
            $"{prefix} value must be an array");
        var items =
            new List<IReadOnlyDictionary<string, ModSettingValue>>();
        var index = 0;
        foreach (var itemElement in source.EnumerateArray())
        {
            var itemPrefix = $"{prefix}[{index}]";
            RequireKind(
                itemElement,
                JsonValueKind.Object,
                $"{itemPrefix} must be an object");
            EnsureNoDuplicateProperties(itemElement, itemPrefix);
            var item = new SortedDictionary<string, ModSettingValue>(
                StringComparer.Ordinal);
            foreach (var property in itemElement.EnumerateObject())
            {
                item.Add(
                    property.Name,
                    ReadValue(
                        property.Value,
                        $"{itemPrefix}.{property.Name}"));
            }
            items.Add(item);
            index++;
        }
        return ModSettingValue.List(items);
    }

    private static void ValidateItemLabel(
        string itemLabel,
        IReadOnlyList<ModSettingDefinition> fields,
        string prefix)
    {
        var position = 0;
        while (position < itemLabel.Length)
        {
            if (itemLabel[position] == '}')
            {
                throw new SettingsValidationException(
                    $"{prefix}.item_label contains an unmatched '}}'");
            }
            if (itemLabel[position] != '{')
            {
                position++;
                continue;
            }
            var close = itemLabel.IndexOf('}', position + 1);
            if (close < 0)
            {
                throw new SettingsValidationException(
                    $"{prefix}.item_label contains an unclosed placeholder");
            }
            var key = itemLabel[(position + 1)..close];
            if (!SettingKeyRegex().IsMatch(key) ||
                !fields.Any(field =>
                    string.Equals(
                        field.Key,
                        key,
                        StringComparison.Ordinal)))
            {
                throw new SettingsValidationException(
                    $"{prefix}.item_label references unknown field '{{{key}}}'");
            }
            position = close + 1;
        }
    }

    private bool TryNormalizeListValue(
        ModSettingDefinition entry,
        ModSettingValue value,
        out ModSettingValue normalized,
        out string error)
    {
        normalized = value;
        if (value.Type != ModSettingValueType.List)
        {
            error = "value must be an array";
            return false;
        }
        if (value.ListValue.Count < entry.MinItems ||
            value.ListValue.Count > entry.MaxItems)
        {
            error =
                "list value count is outside min_items and max_items";
            return false;
        }

        var normalizedItems =
            new List<IReadOnlyDictionary<string, ModSettingValue>>();
        for (var itemIndex = 0;
             itemIndex < value.ListValue.Count;
             itemIndex++)
        {
            var item = value.ListValue[itemIndex];
            foreach (var key in item.Keys)
            {
                if (entry.FindItemField(key) is null)
                {
                    error =
                        $"list item {itemIndex + 1} contains unknown field '{key}'";
                    return false;
                }
            }

            var normalizedItem =
                new SortedDictionary<string, ModSettingValue>(
                    StringComparer.Ordinal);
            foreach (var field in entry.ItemFields)
            {
                var source = item.TryGetValue(field.Key, out var found)
                    ? found
                    : field.DefaultValue!;
                if (!TryNormalizeValue(
                        field,
                        source,
                        out var normalizedField,
                        out var fieldError))
                {
                    error =
                        $"list item {itemIndex + 1} field '{field.Key}' is invalid: {fieldError}";
                    return false;
                }
                normalizedItem.Add(field.Key, normalizedField);
            }
            normalizedItems.Add(normalizedItem);
        }

        normalized = ModSettingValue.List(normalizedItems);
        if (SerializedListValueBytes(normalized) >
            MaximumSerializedListValueBytes)
        {
            error = "serialized list value exceeds 8192 UTF-8 bytes";
            return false;
        }
        error = string.Empty;
        return true;
    }

    private static int SerializedListValueBytes(ModSettingValue value)
    {
        var buffer = new ArrayBufferWriter<byte>();
        using var writer = new Utf8JsonWriter(
            buffer,
            new JsonWriterOptions
            {
                Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping
            });
        WriteCompactValue(writer, value);
        writer.Flush();
        return buffer.WrittenCount;
    }

    private static void WriteCompactValue(
        Utf8JsonWriter writer,
        ModSettingValue value)
    {
        switch (value.Type)
        {
            case ModSettingValueType.Boolean:
                writer.WriteBooleanValue(value.BooleanValue);
                break;
            case ModSettingValueType.Number:
                writer.WriteRawValue(
                    value.NumberValue.ToString(
                        "G17",
                        CultureInfo.InvariantCulture),
                    skipInputValidation: true);
                break;
            case ModSettingValueType.String:
                writer.WriteStringValue(value.StringValue);
                break;
            case ModSettingValueType.List:
                writer.WriteStartArray();
                foreach (var item in value.ListValue)
                {
                    writer.WriteStartObject();
                    foreach (var field in item.OrderBy(
                                 pair => pair.Key,
                                 StringComparer.Ordinal))
                    {
                        writer.WritePropertyName(field.Key);
                        WriteCompactValue(writer, field.Value);
                    }
                    writer.WriteEndObject();
                }
                writer.WriteEndArray();
                break;
        }
    }

    private static bool IsIntegral(double value) =>
        double.IsFinite(value) && Math.Floor(value) == value;

    [GeneratedRegex("^[a-z0-9_]{1,48}$", RegexOptions.CultureInvariant)]
    private static partial Regex SettingKeyRegex();

    private sealed class SettingsValidationException(string message) :
        Exception(message);
}
