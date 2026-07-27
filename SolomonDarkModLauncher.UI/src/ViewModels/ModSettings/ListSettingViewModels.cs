using System.Collections.ObjectModel;
using System.Text.RegularExpressions;

namespace SolomonDarkModLauncher.UI.ViewModels.ModSettings;

/// <summary>One row of a list entry: a flat sub-form of scalar field VMs (contract §10).</summary>
internal sealed partial class ListItemViewModel : ViewModelBase
{
    private readonly ListSettingViewModel owner_;
    private bool isExpanded_;

    public ListItemViewModel(
        ListSettingViewModel owner,
        IReadOnlyDictionary<string, object>? values)
    {
        owner_ = owner;
        var fields = new List<SettingEntryViewModel>();
        foreach (ModSettingEntry declared in owner.Entry.ItemFields ?? [])
        {
            // Scope and restart gating are properties of the LIST entry
            // (contract §10); item fields never carry their own badges.
            ModSettingEntry field = declared with
            {
                Scope = ModSettingScope.Local,
                RequiresRestart = false
            };
            SettingEntryViewModel vm = field.Type switch
            {
                ModSettingType.Toggle => new ToggleSettingViewModel(field),
                ModSettingType.Number => new NumberSettingViewModel(field),
                ModSettingType.Text => new TextSettingViewModel(field),
                ModSettingType.Choice => new ChoiceSettingViewModel(field),
                _ => throw new NotSupportedException(
                    $"List item fields cannot be {field.Type}")
            };
            vm.Load(values is not null && values.TryGetValue(field.Key, out object? value)
                ? value
                : null);
            vm.StateChanged += (_, _) =>
            {
                OnPropertyChanged(nameof(HeaderText));
                owner_.OnItemStateChanged();
            };
            fields.Add(vm);
        }

        Fields = fields;
        RemoveCommand = new RelayCommand(_ => owner_.RemoveItem(this), _ => !owner_.IsReadOnly);
        MoveUpCommand = new RelayCommand(_ => owner_.MoveItem(this, -1), _ => owner_.CanMove(this, -1));
        MoveDownCommand = new RelayCommand(_ => owner_.MoveItem(this, +1), _ => owner_.CanMove(this, +1));
        ToggleExpandCommand = new RelayCommand(_ => IsExpanded = !IsExpanded);
    }

    public IReadOnlyList<SettingEntryViewModel> Fields { get; }

    public RelayCommand RemoveCommand { get; }
    public RelayCommand MoveUpCommand { get; }
    public RelayCommand MoveDownCommand { get; }
    public RelayCommand ToggleExpandCommand { get; }

    public bool IsExpanded
    {
        get => isExpanded_;
        set => SetProperty(ref isExpanded_, value);
    }

    public bool HasInvalidField => Fields.Any(field => field.HasValidationError);

    /// <summary>Contract §10 item_label: {field_key} placeholders substitute display values.</summary>
    public string HeaderText
    {
        get
        {
            string? template = owner_.Entry.ItemLabel;
            if (string.IsNullOrEmpty(template))
            {
                return $"Item {owner_.IndexOf(this) + 1}";
            }

            return PlaceholderPattern().Replace(template, match =>
            {
                string key = match.Groups[1].Value;
                SettingEntryViewModel? field = Fields.FirstOrDefault(f => f.Key == key);
                return field switch
                {
                    ChoiceSettingViewModel choice => choice.Selected?.Label ?? string.Empty,
                    ToggleSettingViewModel toggle => toggle.IsOn ? "on" : "off",
                    NumberSettingViewModel number => number.ValueText,
                    TextSettingViewModel text => text.Text,
                    _ => match.Value
                };
            });
        }
    }

    public IReadOnlyDictionary<string, object> CurrentValues()
    {
        var values = new Dictionary<string, object>(Fields.Count);
        foreach (SettingEntryViewModel field in Fields)
        {
            if (field.CurrentValue is { } value)
            {
                values[field.Key] = value;
            }
        }

        return values;
    }

    public void SetReadOnly(bool readOnly)
    {
        foreach (SettingEntryViewModel field in Fields)
        {
            field.IsReadOnly = readOnly;
        }

        RemoveCommand.RaiseCanExecuteChanged();
        MoveUpCommand.RaiseCanExecuteChanged();
        MoveDownCommand.RaiseCanExecuteChanged();
    }

    public void RefreshMoveStates()
    {
        MoveUpCommand.RaiseCanExecuteChanged();
        MoveDownCommand.RaiseCanExecuteChanged();
        OnPropertyChanged(nameof(HeaderText));
    }

    [GeneratedRegex("\\{([a-z0-9_]+)\\}")]
    private static partial Regex PlaceholderPattern();
}

/// <summary>A structured list entry (contract §10): ordered rows of composite items.</summary>
internal sealed class ListSettingViewModel : SettingEntryViewModel
{
    public ListSettingViewModel(ModSettingEntry entry)
        : base(entry)
    {
        AddCommand = new RelayCommand(_ => AddItem(), _ => CanAdd);
    }

    public ObservableCollection<ListItemViewModel> Items { get; } = [];

    public RelayCommand AddCommand { get; }

    public override bool IsReadOnly
    {
        get => base.IsReadOnly;
        set
        {
            base.IsReadOnly = value;
            foreach (ListItemViewModel item in Items)
            {
                item.SetReadOnly(value);
            }

            AddCommand.RaiseCanExecuteChanged();
            OnPropertyChanged(nameof(CanAdd));
        }
    }

    public int MinItems => Entry.MinItems;
    public int MaxItems => Entry.MaxItems;
    public string CountText => $"{Items.Count} of {MaxItems}";
    public bool CanAdd => !IsReadOnly && Items.Count < MaxItems;
    public bool IsEmpty => Items.Count == 0;

    public int IndexOf(ListItemViewModel item) => Items.IndexOf(item);

    public bool CanMove(ListItemViewModel item, int delta)
    {
        if (IsReadOnly)
        {
            return false;
        }

        int target = Items.IndexOf(item) + delta;
        return target >= 0 && target < Items.Count;
    }

    public override object? CurrentValue
    {
        get
        {
            if (HasValidationError || Items.Any(item => item.HasInvalidField))
            {
                return null;
            }

            return (IReadOnlyList<IReadOnlyDictionary<string, object>>)
                Items.Select(item => item.CurrentValues()).ToArray();
        }
    }

    public void OnItemStateChanged()
    {
        RevalidateCount();
        RaiseStateChanged();
    }

    internal void AddItem()
    {
        if (!CanAdd)
        {
            return;
        }

        var item = new ListItemViewModel(this, values: null) { IsExpanded = true };
        Items.Add(item);
        AfterStructuralChange();
    }

    internal void RemoveItem(ListItemViewModel item)
    {
        if (!IsReadOnly && Items.Remove(item))
        {
            AfterStructuralChange();
        }
    }

    internal void MoveItem(ListItemViewModel item, int delta)
    {
        int index = Items.IndexOf(item);
        int target = index + delta;
        if (index >= 0 && target >= 0 && target < Items.Count)
        {
            Items.Move(index, target);
            AfterStructuralChange();
        }
    }

    protected override void ApplyValue(object? value)
    {
        Items.Clear();
        if (value is IReadOnlyList<IReadOnlyDictionary<string, object>> rows)
        {
            foreach (IReadOnlyDictionary<string, object> row in rows)
            {
                Items.Add(new ListItemViewModel(this, row));
            }
        }

        RevalidateCount();
        AfterStructuralChange(raiseState: false);
    }

    protected override object? CoerceOrDefault(object? value) =>
        value is IReadOnlyList<IReadOnlyDictionary<string, object>> rows
        && rows.Count >= Entry.MinItems
        && rows.Count <= Entry.MaxItems
            ? rows
            : Entry.Default;

    private void AfterStructuralChange(bool raiseState = true)
    {
        foreach (ListItemViewModel item in Items)
        {
            item.RefreshMoveStates();
        }

        RevalidateCount();
        AddCommand.RaiseCanExecuteChanged();
        OnPropertyChanged(nameof(CountText));
        OnPropertyChanged(nameof(IsEmpty));
        OnPropertyChanged(nameof(CanAdd));
        if (raiseState)
        {
            RaiseStateChanged();
        }
    }

    private void RevalidateCount()
    {
        ValidationError = Items.Count < MinItems
            ? $"At least {MinItems} item{(MinItems == 1 ? "" : "s")} required."
            : Items.Count > MaxItems
                ? $"At most {MaxItems} item{(MaxItems == 1 ? "" : "s")} allowed."
                : Items.Any(item => item.HasInvalidField)
                    ? "Fix the highlighted item fields."
                    : null;
    }
}
