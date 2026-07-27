namespace SolomonDarkModLauncher.UI.ViewModels.ModSettings;

/// <summary>
/// Development stand-in for the #60 service layer, active only when
/// SDMOD_UI_SETTINGS_STUB=1. Serves the bot-brain dogfood schema from the
/// contract (§1) with in-memory persistence so the dialog is fully exercisable
/// (idle/live/host/client states via SDMOD_UI_SETTINGS_STUB_STATE) before the
/// backend lands. Replaced by the production adapter during #60/#61 integration.
/// </summary>
internal sealed class StubModSettingsSource : IModSettingsSource
{
    private readonly Dictionary<string, Dictionary<string, object>> persisted_ = [];

    public static bool Enabled =>
        Environment.GetEnvironmentVariable("SDMOD_UI_SETTINGS_STUB") == "1";

    public GameInstanceState InstanceState =>
        Environment.GetEnvironmentVariable("SDMOD_UI_SETTINGS_STUB_STATE") switch
        {
            "solo" => GameInstanceState.RunningSolo,
            "host" => GameInstanceState.RunningHost,
            "client" => GameInstanceState.RunningClientInSession,
            _ => GameInstanceState.NotRunning
        };

    public event EventHandler? InstanceStateChanged
    {
        add { }
        remove { }
    }

    public ModSettingsSchema GetSchema(string modId)
    {
        // One deliberately-invalid row so the warning affordance is visible in
        // stub-mode screenshots.
        if (modId == "sample.story.custom_intro")
        {
            return new ModSettingsSchema(
                modId, "Story Custom Intro", "v0.1.0",
                ModSettingsBlockState.Invalid,
                "settings.entries[0]: duplicate key 'intro_text'",
                []);
        }

        return new ModSettingsSchema(
            modId,
            "Bot Brain",
            "v0.1.0",
            ModSettingsBlockState.Valid,
            null,
            [
            new ModSettingEntry(
                "kite_radius", ModSettingType.Number, "Kite radius",
                "Threat sampling distance in world units.", "Combat",
                ModSettingScope.Host, false, 340.0, Min: 100, Max: 900, Step: 10, Integer: true),
            new ModSettingEntry(
                "offense_enabled", ModSettingType.Toggle, "Cast at enemies",
                null, "Combat", ModSettingScope.Host, false, true),
            new ModSettingEntry(
                "respawn_bot", ModSettingType.Action, "Respawn bot",
                "Despawns and respawns the bot at the arena center.", "Combat",
                ModSettingScope.Host, false, null, Confirm: true),
            new ModSettingEntry(
                "persona_name", ModSettingType.Text, "Bot name",
                "Member-list persona for the synthetic participant.", "Identity",
                ModSettingScope.Host, true, "Ember", MaxLength: 31),
            new ModSettingEntry(
                "think_profile", ModSettingType.Choice, "Think cadence",
                null, "Identity", ModSettingScope.Local, false, "standard",
                Choices:
                [
                    new ModSettingChoice("standard", "Standard (250 ms)"),
                    new ModSettingChoice("relaxed", "Relaxed (400 ms)")
                ]),
            new ModSettingEntry(
                "focus_bot_key", ModSettingType.Keybind, "Focus camera on bot",
                "Hold to center the camera on the bot.", "Identity",
                ModSettingScope.Local, false, "NONE")
        ]);
    }

    public IReadOnlyDictionary<string, object> GetPersistedValues(string modId) =>
        persisted_.TryGetValue(modId, out Dictionary<string, object>? values)
            ? values
            : new Dictionary<string, object>();

    public Task<SettingsApplyResult> SaveAsync(string modId, IReadOnlyDictionary<string, object> values)
    {
        persisted_[modId] = new Dictionary<string, object>(values);
        return Task.FromResult(new SettingsApplyResult(true, [.. values.Keys], null));
    }

    public Task<SettingsApplyResult> InvokeActionAsync(string modId, string entryKey) =>
        Task.FromResult(InstanceState == GameInstanceState.NotRunning
            ? new SettingsApplyResult(false, [], "No running game instance.")
            : new SettingsApplyResult(true, [], null));
}
