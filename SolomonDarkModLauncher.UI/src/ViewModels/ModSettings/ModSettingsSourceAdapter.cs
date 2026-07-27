using SolomonDarkModLauncher.ModSettings;

namespace SolomonDarkModLauncher.UI.ViewModels.ModSettings;

/// <summary>
/// The thin WPF adapter the contract (§7) plans for: implements the dialog's
/// IModSettingsSource over the #60 backend service layer.
/// </summary>
internal sealed class ModSettingsSourceAdapter : IModSettingsSource
{
    private readonly IModSettingsService service_;

    public ModSettingsSourceAdapter(IModSettingsService service)
    {
        service_ = service;
        service_.InstanceStateChanged += (_, _) =>
            InstanceStateChanged?.Invoke(this, EventArgs.Empty);
    }

    public GameInstanceState InstanceState => service_.InstanceState switch
    {
        ModSettingsGameInstanceState.RunningSolo => GameInstanceState.RunningSolo,
        ModSettingsGameInstanceState.RunningHost => GameInstanceState.RunningHost,
        ModSettingsGameInstanceState.RunningClientInSession => GameInstanceState.RunningClientInSession,
        _ => GameInstanceState.NotRunning
    };

    public event EventHandler? InstanceStateChanged;

    public ModSettingsSchema GetSchema(string modId)
    {
        DiscoveredModSettings mod = service_.GetSchema(modId);
        ModSettingsBlockState state = mod.Validation.Status switch
        {
            ModSettingsManifestStatus.Valid => ModSettingsBlockState.Valid,
            ModSettingsManifestStatus.Invalid => ModSettingsBlockState.Invalid,
            _ => ModSettingsBlockState.None
        };

        IReadOnlyList<ModSettingEntry> entries =
            mod.Validation.Definition?.Entries.Select(Convert).ToArray()
            ?? [];

        return new ModSettingsSchema(
            mod.ModId,
            mod.Name,
            mod.Version.StartsWith('v') ? mod.Version : $"v{mod.Version}",
            state,
            state == ModSettingsBlockState.Invalid ? mod.Validation.Error : null,
            entries);
    }

    public IReadOnlyDictionary<string, object> GetPersistedValues(string modId)
    {
        ModSettingsSnapshot snapshot = service_.GetPersistedValues(modId);
        var values = new Dictionary<string, object>(snapshot.Values.Count);
        foreach ((string key, ModSettingValue value) in snapshot.Values)
        {
            values[key] = ToClr(value);
        }

        return values;
    }

    public async Task<SettingsApplyResult> SaveAsync(
        string modId,
        IReadOnlyDictionary<string, object> values)
    {
        var converted = new Dictionary<string, ModSettingValue>(values.Count);
        foreach ((string key, object value) in values)
        {
            converted[key] = FromClr(value);
        }

        ModSettingsRuntimeResult result =
            await service_.SaveAsync(modId, converted).ConfigureAwait(true);
        return Convert(result);
    }

    public async Task<SettingsApplyResult> InvokeActionAsync(string modId, string entryKey)
    {
        ModSettingsRuntimeResult result =
            await service_.InvokeActionAsync(modId, entryKey).ConfigureAwait(true);
        return Convert(result);
    }

    private static SettingsApplyResult Convert(ModSettingsRuntimeResult result) =>
        new(result.Ok, result.Changed, result.Error.Length == 0 ? null : result.Error);

    private static object ToClr(ModSettingValue value) => value.Type switch
    {
        ModSettingValueType.Boolean => value.BooleanValue,
        ModSettingValueType.Number => value.NumberValue,
        ModSettingValueType.List => (IReadOnlyList<IReadOnlyDictionary<string, object>>)
            value.ListValue
                .Select(row => (IReadOnlyDictionary<string, object>)
                    row.ToDictionary(field => field.Key, field => ToClr(field.Value)))
                .ToArray(),
        _ => value.StringValue
    };

    private static ModSettingValue FromClr(object value) => value switch
    {
        bool b => ModSettingValue.Boolean(b),
        double d => ModSettingValue.Number(d),
        int i => ModSettingValue.Number(i),
        string s => ModSettingValue.String(s),
        IReadOnlyList<IReadOnlyDictionary<string, object>> rows => ModSettingValue.List(
            rows.Select(row => (IReadOnlyDictionary<string, ModSettingValue>)
                row.ToDictionary(field => field.Key, field => FromClr(field.Value)))),
        _ => throw new NotSupportedException(
            $"Unsupported setting value type {value.GetType().Name}")
    };

    private static ModSettingEntry Convert(ModSettingDefinition definition) =>
        new(
            definition.Key,
            (ModSettingType)definition.Type,
            definition.Label,
            definition.Description.Length == 0 ? null : definition.Description,
            definition.Group.Length == 0 ? null : definition.Group,
            definition.Scope == SolomonDarkModLauncher.ModSettings.ModSettingScope.Host
                ? ModSettingScope.Host
                : ModSettingScope.Local,
            definition.RequiresRestart,
            definition.DefaultValue is { } defaultValue ? ToClr(defaultValue) : null,
            Min: definition.Minimum,
            Max: definition.Maximum,
            Step: definition.Step,
            Integer: definition.Integer,
            MaxLength: definition.MaxLength,
            Placeholder: definition.Placeholder.Length == 0 ? null : definition.Placeholder,
            Choices: definition.Choices.Count == 0
                ? null
                : definition.Choices
                    .Select(choice => new ModSettingChoice(choice.Value, choice.Label))
                    .ToArray(),
            Confirm: definition.Confirm,
            MinItems: definition.MinItems,
            MaxItems: definition.MaxItems,
            ItemLabel: definition.ItemLabel.Length == 0 ? null : definition.ItemLabel,
            ItemFields: definition.ItemFields.Count == 0
                ? null
                : definition.ItemFields.Select(Convert).ToArray());
}
