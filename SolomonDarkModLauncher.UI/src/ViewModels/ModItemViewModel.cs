using System.Diagnostics;
using System.Windows.Media;
using SolomonDarkModLauncher.UI.Infrastructure;

namespace SolomonDarkModLauncher.UI.ViewModels;

internal sealed class ModItemViewModel : ViewModelBase
{
    private bool isEnabled_;
    private bool suppressToggleNotification_;

    public ModItemViewModel(LauncherCliMod mod)
    {
        Id = mod.Id;
        Name = string.IsNullOrWhiteSpace(mod.Name) ? mod.Id : mod.Name;
        Version = $"v{mod.Version}";
        Priority = mod.Priority;
        RuntimeKind = mod.RuntimeKind;
        RuntimeKindUpper = RuntimeKind.ToUpperInvariant();
        OverlaySummary = mod.OverlayCount == 0
            ? "No overlay files"
            : $"{mod.OverlayCount} overlay file{(mod.OverlayCount == 1 ? string.Empty : "s")}";
        DependencySummary = mod.RequiredMods.Count == 0
            ? "Standalone"
            : $"Requires {string.Join(", ", mod.RequiredMods)}";
        RootPath = mod.RootPath;
        ManifestPath = mod.ManifestPath;
        isEnabled_ = mod.Enabled;

        OpenFolderCommand = new RelayCommand(_ =>
            Process.Start(new ProcessStartInfo(RootPath) { UseShellExecute = true }));
        ViewManifestCommand = new RelayCommand(_ =>
            Process.Start(new ProcessStartInfo("notepad.exe", $"\"{ManifestPath}\"")));
    }

    public string Id { get; }
    public string Name { get; }
    public string Version { get; }
    public int Priority { get; }
    public string RuntimeKind { get; }
    public string RuntimeKindUpper { get; }
    public string OverlaySummary { get; }
    public string DependencySummary { get; }
    public string RootPath { get; }
    public string ManifestPath { get; }

    public string PriorityText => $"Priority {Priority}";

    public Brush RuntimeBadgeBackground => RuntimeKind switch
    {
        "native" => new SolidColorBrush(Color.FromRgb(0x43, 0x1F, 0x12)),
        "lua" => new SolidColorBrush(Color.FromRgb(0x1D, 0x29, 0x3B)),
        _ => new SolidColorBrush(Color.FromRgb(0x24, 0x24, 0x24))
    };

    public Brush RuntimeBadgeForeground => RuntimeKind switch
    {
        "native" => new SolidColorBrush(Color.FromRgb(0xF7, 0xB2, 0x68)),
        "lua" => new SolidColorBrush(Color.FromRgb(0x8E, 0xC5, 0xFF)),
        _ => Brushes.Gainsboro
    };

    public bool IsEnabled
    {
        get => isEnabled_;
        set
        {
            if (SetProperty(ref isEnabled_, value) && !suppressToggleNotification_)
            {
                ToggleRequested?.Invoke(this);
            }
        }
    }

    public event Action<ModItemViewModel>? ToggleRequested;

    public RelayCommand OpenFolderCommand { get; }
    public RelayCommand ViewManifestCommand { get; }

    public void SetEnabledSilently(bool value)
    {
        suppressToggleNotification_ = true;
        IsEnabled = value;
        suppressToggleNotification_ = false;
    }
}
