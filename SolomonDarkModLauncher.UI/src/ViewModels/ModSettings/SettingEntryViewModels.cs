using System.Text;
using SolomonDarkModLauncher.UI.Infrastructure;

namespace SolomonDarkModLauncher.UI.ViewModels.ModSettings;

internal abstract class SettingEntryViewModel : ViewModelBase
{
    private string? validationError_;
    private bool isReadOnly_;

    protected SettingEntryViewModel(ModSettingEntry entry)
    {
        Entry = entry;
    }

    public ModSettingEntry Entry { get; }

    public string Key => Entry.Key;
    public string Label => Entry.Label;
    public string Description => Entry.Description ?? string.Empty;
    public bool HasDescription => !string.IsNullOrEmpty(Entry.Description);
    public bool IsHostScope => Entry.Scope == ModSettingScope.Host;
    public bool RequiresRestart => Entry.RequiresRestart;

    public string? ValidationError
    {
        get => validationError_;
        protected set
        {
            if (SetProperty(ref validationError_, value))
            {
                OnPropertyChanged(nameof(HasValidationError));
            }
        }
    }

    public bool HasValidationError => validationError_ is not null;

    /// <summary>Host-scope entries lock while this machine is an in-session client.</summary>
    public virtual bool IsReadOnly
    {
        get => isReadOnly_;
        set => SetProperty(ref isReadOnly_, value);
    }

    public bool IsDirty => !ValuesEqual(CurrentValue, LoadedValue);

    protected object? LoadedValue { get; private set; }

    public abstract object? CurrentValue { get; }

    public event EventHandler? StateChanged;

    public void Load(object? persisted)
    {
        object? effective = persisted ?? Entry.Default;
        LoadedValue = CoerceOrDefault(effective);
        ApplyValue(LoadedValue);
        ValidationError = null;
        RaiseStateChanged();
    }

    public void MarkSaved()
    {
        LoadedValue = CurrentValue;
        RaiseStateChanged();
    }

    public void ResetToDefault()
    {
        if (!IsReadOnly)
        {
            ApplyValue(CoerceOrDefault(Entry.Default));
            RaiseStateChanged();
        }
    }

    protected abstract void ApplyValue(object? value);

    /// <summary>Returns a value guaranteed valid for this entry, falling back to the manifest default.</summary>
    protected abstract object? CoerceOrDefault(object? value);

    protected void RaiseStateChanged()
    {
        OnPropertyChanged(nameof(IsDirty));
        StateChanged?.Invoke(this, EventArgs.Empty);
    }

    private static bool ValuesEqual(object? a, object? b)
    {
        if (a is double da && b is double db)
        {
            return da.Equals(db);
        }

        return Equals(a, b);
    }
}

internal sealed class ToggleSettingViewModel : SettingEntryViewModel
{
    private bool isOn_;

    public ToggleSettingViewModel(ModSettingEntry entry)
        : base(entry)
    {
    }

    public bool IsOn
    {
        get => isOn_;
        set
        {
            if (SetProperty(ref isOn_, value))
            {
                RaiseStateChanged();
            }
        }
    }

    public override object? CurrentValue => isOn_;

    protected override void ApplyValue(object? value) => IsOn = value is true;

    protected override object? CoerceOrDefault(object? value) =>
        value is bool b ? b : Entry.Default is true;
}

internal sealed class NumberSettingViewModel : SettingEntryViewModel
{
    private double value_;
    private string valueText_ = string.Empty;
    private bool syncingText_;

    public NumberSettingViewModel(ModSettingEntry entry)
        : base(entry)
    {
        Min = entry.Min ?? 0;
        Max = entry.Max ?? 100;
        Step = entry.Step > 0 ? entry.Step : 1;
    }

    public double Min { get; }
    public double Max { get; }
    public double Step { get; }
    public bool IsInteger => Entry.Integer;

    public string RangeText => IsInteger
        ? $"{(int)Min}–{(int)Max}"
        : $"{Min}–{Max}";

    public double Value
    {
        get => value_;
        set
        {
            double snapped = Snap(value);
            if (SetProperty(ref value_, snapped))
            {
                if (!syncingText_)
                {
                    syncingText_ = true;
                    ValueText = Format(snapped);
                    syncingText_ = false;
                }

                ValidationError = null;
                RaiseStateChanged();
            }
        }
    }

    public string ValueText
    {
        get => valueText_;
        set
        {
            if (!SetProperty(ref valueText_, value) || syncingText_)
            {
                return;
            }

            if (double.TryParse(value, out double parsed))
            {
                if (parsed < Min || parsed > Max)
                {
                    ValidationError = $"Must be between {Format(Min)} and {Format(Max)}.";
                }
                else
                {
                    syncingText_ = true;
                    Value = parsed;
                    syncingText_ = false;
                    ValidationError = null;
                }
            }
            else
            {
                ValidationError = IsInteger ? "Enter a whole number." : "Enter a number.";
            }

            RaiseStateChanged();
        }
    }

    public override object? CurrentValue => HasValidationError ? null : value_;

    protected override void ApplyValue(object? value)
    {
        syncingText_ = true;
        value_ = value is double d ? Snap(d) : Snap(Min);
        valueText_ = Format(value_);
        syncingText_ = false;
        ValidationError = null;
        OnPropertyChanged(nameof(Value));
        OnPropertyChanged(nameof(ValueText));
    }

    protected override object? CoerceOrDefault(object? value)
    {
        double candidate = value switch
        {
            double d => d,
            int i => i,
            long l => l,
            string s when double.TryParse(s, out double p) => p,
            _ => Entry.Default is double dd ? dd : Min
        };

        return Snap(candidate);
    }

    private double Snap(double raw)
    {
        double clamped = Math.Clamp(raw, Min, Max);
        double stepped = Min + Math.Round((clamped - Min) / Step) * Step;
        stepped = Math.Clamp(stepped, Min, Max);
        return IsInteger ? Math.Round(stepped) : stepped;
    }

    private string Format(double value) =>
        IsInteger ? ((long)Math.Round(value)).ToString() : value.ToString("0.###");
}

internal sealed class TextSettingViewModel : SettingEntryViewModel
{
    private string text_ = string.Empty;

    public TextSettingViewModel(ModSettingEntry entry)
        : base(entry)
    {
    }

    public string Placeholder => Entry.Placeholder ?? string.Empty;
    public int MaxLength => Entry.MaxLength;

    public string Text
    {
        get => text_;
        set
        {
            if (SetProperty(ref text_, value))
            {
                // Contract §1: max_length limits UTF-8 bytes, not chars.
                ValidationError = Encoding.UTF8.GetByteCount(value) > Entry.MaxLength
                    ? $"Too long — up to {Entry.MaxLength} bytes."
                    : null;
                RaiseStateChanged();
            }
        }
    }

    public override object? CurrentValue => HasValidationError ? null : text_;

    protected override void ApplyValue(object? value)
    {
        text_ = value as string ?? string.Empty;
        ValidationError = null;
        OnPropertyChanged(nameof(Text));
    }

    protected override object? CoerceOrDefault(object? value) =>
        value is string s && Encoding.UTF8.GetByteCount(s) <= Entry.MaxLength
            ? s
            : Entry.Default as string ?? string.Empty;
}

internal sealed class ChoiceSettingViewModel : SettingEntryViewModel
{
    private ModSettingChoice? selected_;

    public ChoiceSettingViewModel(ModSettingEntry entry)
        : base(entry)
    {
        Choices = entry.Choices ?? [];
    }

    public IReadOnlyList<ModSettingChoice> Choices { get; }

    public ModSettingChoice? Selected
    {
        get => selected_;
        set
        {
            if (SetProperty(ref selected_, value))
            {
                RaiseStateChanged();
            }
        }
    }

    public override object? CurrentValue => selected_?.Value;

    protected override void ApplyValue(object? value)
    {
        string? target = value as string;
        Selected = Choices.FirstOrDefault(c => c.Value == target) ?? Choices.FirstOrDefault();
    }

    protected override object? CoerceOrDefault(object? value) =>
        value is string s && Choices.Any(c => c.Value == s)
            ? s
            : Entry.Default as string;
}

internal sealed class KeybindSettingViewModel : SettingEntryViewModel
{
    private string keyName_ = CanonicalKeys.None;
    private bool isCapturing_;

    public KeybindSettingViewModel(ModSettingEntry entry)
        : base(entry)
    {
        ToggleCaptureCommand = new RelayCommand(_ =>
        {
            if (!IsReadOnly)
            {
                IsCapturing = !IsCapturing;
            }
        });
    }

    public string KeyName
    {
        get => keyName_;
        private set
        {
            if (SetProperty(ref keyName_, value))
            {
                OnPropertyChanged(nameof(DisplayText));
                RaiseStateChanged();
            }
        }
    }

    public bool IsCapturing
    {
        get => isCapturing_;
        private set
        {
            if (SetProperty(ref isCapturing_, value))
            {
                OnPropertyChanged(nameof(DisplayText));
            }
        }
    }

    public string DisplayText => IsCapturing
        ? "Press a key…"
        : CanonicalKeys.DisplayText(keyName_);

    public RelayCommand ToggleCaptureCommand { get; }

    /// <summary>The window forwards raw input here while capturing. Returns true when consumed.</summary>
    public bool TryComplete(string? canonicalName)
    {
        if (!IsCapturing)
        {
            return false;
        }

        if (canonicalName is not null && CanonicalKeys.IsValid(canonicalName))
        {
            KeyName = canonicalName;
        }

        IsCapturing = false;
        return true;
    }

    public bool CancelCapture()
    {
        if (!IsCapturing)
        {
            return false;
        }

        IsCapturing = false;
        return true;
    }

    public bool ClearBinding()
    {
        if (!IsCapturing)
        {
            return false;
        }

        KeyName = CanonicalKeys.None;
        IsCapturing = false;
        return true;
    }

    public override object? CurrentValue => keyName_;

    protected override void ApplyValue(object? value)
    {
        IsCapturing = false;
        KeyName = value as string ?? CanonicalKeys.None;
    }

    protected override object? CoerceOrDefault(object? value) =>
        value is string s && CanonicalKeys.IsValid(s)
            ? s
            : Entry.Default as string ?? CanonicalKeys.None;
}

internal sealed class ActionSettingViewModel : SettingEntryViewModel
{
    private readonly Func<string, Task<SettingsApplyResult>> invoke_;
    private readonly Func<bool> canInvoke_;
    private bool isInvoking_;
    private string? feedback_;
    private bool feedbackIsError_;

    public ActionSettingViewModel(
        ModSettingEntry entry,
        Func<string, Task<SettingsApplyResult>> invoke,
        Func<bool> canInvoke)
        : base(entry)
    {
        invoke_ = invoke;
        canInvoke_ = canInvoke;
        InvokeCommand = new RelayCommand(async _ => await InvokeAsync(), _ => CanInvoke);
    }

    public bool Confirm => Entry.Confirm;

    public RelayCommand InvokeCommand { get; }

    public bool CanInvoke => !isInvoking_ && canInvoke_();

    public string? Feedback
    {
        get => feedback_;
        private set
        {
            if (SetProperty(ref feedback_, value))
            {
                OnPropertyChanged(nameof(HasFeedback));
            }
        }
    }

    public bool HasFeedback => feedback_ is not null;

    public bool FeedbackIsError
    {
        get => feedbackIsError_;
        private set => SetProperty(ref feedbackIsError_, value);
    }

    public void RefreshAvailability()
    {
        OnPropertyChanged(nameof(CanInvoke));
        InvokeCommand.RaiseCanExecuteChanged();
    }

    public override object? CurrentValue => null;

    protected override void ApplyValue(object? value)
    {
    }

    protected override object? CoerceOrDefault(object? value) => null;

    private async Task InvokeAsync()
    {
        isInvoking_ = true;
        RefreshAvailability();
        Feedback = null;

        try
        {
            SettingsApplyResult result = await invoke_(Key);
            FeedbackIsError = !result.Ok;
            Feedback = result.Ok ? "Done." : result.Error ?? "Action failed.";
        }
        catch (Exception ex)
        {
            FeedbackIsError = true;
            Feedback = ex.Message;
        }
        finally
        {
            isInvoking_ = false;
            RefreshAvailability();
        }
    }
}
