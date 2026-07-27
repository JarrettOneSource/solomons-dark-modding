namespace SolomonDarkModLauncher.UI.ViewModels.ModSettings;

// View-facing shapes of the mod settings contract
// (docs/design/mod-settings-2026-07-27.md §1/§2/§5). The backend service layer
// (#60) is the authority for parsing, validation, persistence, and IPC; these
// types are the seam the dialog consumes, adapted onto those services.

internal enum ModSettingType
{
    Toggle,
    Number,
    Text,
    Choice,
    Keybind,
    Action
}

internal enum ModSettingScope
{
    Local,
    Host
}

internal sealed record ModSettingChoice(string Value, string Label);

internal sealed record ModSettingEntry(
    string Key,
    ModSettingType Type,
    string Label,
    string? Description,
    string? Group,
    ModSettingScope Scope,
    bool RequiresRestart,
    object? Default,
    double? Min = null,
    double? Max = null,
    double Step = 1,
    bool Integer = false,
    int MaxLength = 256,
    string? Placeholder = null,
    IReadOnlyList<ModSettingChoice>? Choices = null,
    bool Confirm = false);

internal enum ModSettingsBlockState
{
    None,
    Valid,
    Invalid
}

internal sealed record ModSettingsSchema(
    string ModId,
    string ModName,
    string ModVersion,
    ModSettingsBlockState State,
    string? ValidationError,
    IReadOnlyList<ModSettingEntry> Entries);

internal enum GameInstanceState
{
    NotRunning,
    RunningSolo,
    RunningHost,
    RunningClientInSession
}

internal sealed record SettingsApplyResult(
    bool Ok,
    IReadOnlyList<string> ChangedKeys,
    string? Error);

/// <summary>
/// The dialog's data source. The production implementation adapts the #60
/// launcher service layer (settings store + exec-pipe client); the stub serves
/// development and visual acceptance before that lands.
/// </summary>
internal interface IModSettingsSource
{
    ModSettingsSchema GetSchema(string modId);

    IReadOnlyDictionary<string, object> GetPersistedValues(string modId);

    Task<SettingsApplyResult> SaveAsync(string modId, IReadOnlyDictionary<string, object> values);

    Task<SettingsApplyResult> InvokeActionAsync(string modId, string entryKey);

    GameInstanceState InstanceState { get; }

    event EventHandler? InstanceStateChanged;
}
