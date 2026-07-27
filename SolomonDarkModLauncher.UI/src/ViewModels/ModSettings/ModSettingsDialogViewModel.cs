using System.Collections.ObjectModel;

namespace SolomonDarkModLauncher.UI.ViewModels.ModSettings;

internal sealed class SettingGroupViewModel
{
    public SettingGroupViewModel(string name, IReadOnlyList<SettingEntryViewModel> entries)
    {
        Name = name;
        Entries = entries;
    }

    public string Name { get; }
    public bool HasName => Name.Length > 0;
    public IReadOnlyList<SettingEntryViewModel> Entries { get; }
}

internal sealed class ModSettingsDialogViewModel : ViewModelBase
{
    private readonly IModSettingsSource source_;
    private readonly string modId_;
    private string? banner_;
    private bool bannerIsError_;
    private bool isSaving_;

    public ModSettingsDialogViewModel(IModSettingsSource source, string modId)
    {
        source_ = source;
        modId_ = modId;

        ModSettingsSchema schema = source.GetSchema(modId);
        Title = schema.ModName;
        Subtitle = $"{schema.ModVersion} · Mod Settings";

        IReadOnlyDictionary<string, object> persisted = source.GetPersistedValues(modId);
        var groups = new List<SettingGroupViewModel>();
        var currentEntries = new List<SettingEntryViewModel>();
        string currentGroup = schema.Entries.Count > 0 ? schema.Entries[0].Group ?? string.Empty : string.Empty;

        foreach (ModSettingEntry entry in schema.Entries)
        {
            string group = entry.Group ?? string.Empty;
            if (group != currentGroup)
            {
                groups.Add(new SettingGroupViewModel(currentGroup, currentEntries));
                currentEntries = [];
                currentGroup = group;
            }

            SettingEntryViewModel vm = Create(entry);
            vm.Load(persisted.TryGetValue(entry.Key, out object? value) ? value : null);
            vm.StateChanged += (_, _) => RefreshDirtyState();
            currentEntries.Add(vm);
        }

        if (currentEntries.Count > 0 || groups.Count == 0)
        {
            groups.Add(new SettingGroupViewModel(currentGroup, currentEntries));
        }

        Groups = new ObservableCollection<SettingGroupViewModel>(groups);

        SaveCommand = new RelayCommand(async _ => await SaveAsync(), _ => CanSave);
        ResetCommand = new RelayCommand(_ => ResetAll());

        source_.InstanceStateChanged += (_, _) => OnInstanceStateChanged();
        OnInstanceStateChanged();
    }

    public string Title { get; }
    public string Subtitle { get; }

    public ObservableCollection<SettingGroupViewModel> Groups { get; }

    public IEnumerable<SettingEntryViewModel> AllEntries => Groups.SelectMany(g => g.Entries);

    public RelayCommand SaveCommand { get; }
    public RelayCommand ResetCommand { get; }

    public bool CanSave =>
        !isSaving_
        && AllEntries.Any(e => e.IsDirty)
        && AllEntries.All(e => !e.HasValidationError);

    public bool HasRestartPending => AllEntries.Any(e => e is { RequiresRestart: true, IsDirty: true });

    public string LiveBadgeText => source_.InstanceState switch
    {
        GameInstanceState.NotRunning => "Game not running — changes apply on next launch",
        GameInstanceState.RunningClientInSession => "Live · in session as client",
        GameInstanceState.RunningHost => "Live · hosting",
        _ => "Live"
    };

    public bool IsLive => source_.InstanceState != GameInstanceState.NotRunning;

    public string? Banner
    {
        get => banner_;
        private set
        {
            if (SetProperty(ref banner_, value))
            {
                OnPropertyChanged(nameof(HasBanner));
            }
        }
    }

    public bool HasBanner => banner_ is not null;

    public bool BannerIsError
    {
        get => bannerIsError_;
        private set => SetProperty(ref bannerIsError_, value);
    }

    public bool TryHandleCaptureKey(string? canonicalName, bool isEscape, bool isClear)
    {
        foreach (SettingEntryViewModel entry in AllEntries)
        {
            if (entry is KeybindSettingViewModel keybind && keybind.IsCapturing)
            {
                if (isEscape)
                {
                    return keybind.CancelCapture();
                }

                if (isClear)
                {
                    return keybind.ClearBinding();
                }

                return keybind.TryComplete(canonicalName);
            }
        }

        return false;
    }

    private SettingEntryViewModel Create(ModSettingEntry entry) => entry.Type switch
    {
        ModSettingType.Toggle => new ToggleSettingViewModel(entry),
        ModSettingType.Number => new NumberSettingViewModel(entry),
        ModSettingType.Text => new TextSettingViewModel(entry),
        ModSettingType.Choice => new ChoiceSettingViewModel(entry),
        ModSettingType.Keybind => new KeybindSettingViewModel(entry),
        ModSettingType.Action => new ActionSettingViewModel(
            entry,
            key => source_.InvokeActionAsync(modId_, key),
            () => ActionAvailable(entry)),
        _ => throw new NotSupportedException($"Unknown setting type {entry.Type}")
    };

    private bool ActionAvailable(ModSettingEntry entry)
    {
        return source_.InstanceState switch
        {
            GameInstanceState.NotRunning => false,
            GameInstanceState.RunningClientInSession => entry.Scope != ModSettingScope.Host,
            _ => true
        };
    }

    private void OnInstanceStateChanged()
    {
        bool clientLocked = source_.InstanceState == GameInstanceState.RunningClientInSession;
        foreach (SettingEntryViewModel entry in AllEntries)
        {
            entry.IsReadOnly = clientLocked && entry.IsHostScope;
            if (entry is ActionSettingViewModel action)
            {
                action.RefreshAvailability();
            }
        }

        OnPropertyChanged(nameof(LiveBadgeText));
        OnPropertyChanged(nameof(IsLive));
    }

    private void RefreshDirtyState()
    {
        OnPropertyChanged(nameof(CanSave));
        OnPropertyChanged(nameof(HasRestartPending));
        SaveCommand.RaiseCanExecuteChanged();
    }

    private void ResetAll()
    {
        foreach (SettingEntryViewModel entry in AllEntries)
        {
            entry.ResetToDefault();
        }

        Banner = null;
    }

    private async Task SaveAsync()
    {
        isSaving_ = true;
        RefreshDirtyState();
        Banner = null;

        try
        {
            var values = new Dictionary<string, object>();
            foreach (SettingEntryViewModel entry in AllEntries)
            {
                if (entry.Entry.Type != ModSettingType.Action && entry.CurrentValue is { } value)
                {
                    values[entry.Key] = value;
                }
            }

            SettingsApplyResult result = await source_.SaveAsync(modId_, values);
            if (result.Ok)
            {
                bool restartPending = HasRestartPending;
                foreach (SettingEntryViewModel entry in AllEntries)
                {
                    entry.MarkSaved();
                }

                BannerIsError = false;
                Banner = restartPending
                    ? "Saved. Marked settings apply on next launch."
                    : IsLive ? "Saved and applied to the running game." : "Saved.";
            }
            else
            {
                BannerIsError = true;
                Banner = result.Error ?? "Save failed.";
            }
        }
        catch (Exception ex)
        {
            BannerIsError = true;
            Banner = ex.Message;
        }
        finally
        {
            isSaving_ = false;
            RefreshDirtyState();
        }
    }
}
