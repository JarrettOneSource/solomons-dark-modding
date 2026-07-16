using System.Diagnostics;
using System.Windows.Media;
using SolomonDarkModLauncher.UI.Infrastructure;

namespace SolomonDarkModLauncher.UI.ViewModels;

internal sealed class ModItemViewModel : ViewModelBase
{
    private static readonly Brush LuaChipBackground = Freeze(new SolidColorBrush(Color.FromRgb(0x1E, 0x2C, 0x38)));
    private static readonly Brush LuaChipForeground = Freeze(new SolidColorBrush(Color.FromRgb(0x7F, 0xB4, 0xD9)));
    private static readonly Brush NativeChipBackground = Freeze(new SolidColorBrush(Color.FromRgb(0x33, 0x26, 0x1A)));
    private static readonly Brush NativeChipForeground = Freeze(new SolidColorBrush(Color.FromRgb(0xDF, 0xA9, 0x6B)));
    private static readonly Brush DefaultChipBackground = Freeze(new SolidColorBrush(Color.FromRgb(0x2A, 0x28, 0x30)));
    private static readonly Brush DefaultChipForeground = Freeze(new SolidColorBrush(Color.FromRgb(0xB9, 0xB4, 0xA8)));

    private bool isEnabled_;
    private bool suppressToggleNotification_;

    public ModItemViewModel(LauncherCliMod mod)
    {
        Id = mod.Id;
        Name = string.IsNullOrWhiteSpace(mod.Name) ? mod.Id : mod.Name;
        Version = $"v{mod.Version}";
        RuntimeKind = mod.RuntimeKind;
        RequiresText = mod.RequiredMods.Count == 0
            ? string.Empty
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
    public string RuntimeKind { get; }
    public string RequiresText { get; }
    public string RootPath { get; }
    public string ManifestPath { get; }

    public string RuntimeChipText => RuntimeKind switch
    {
        "native" => "Native",
        "lua" => "Lua",
        _ => "Data"
    };

    public Brush RuntimeChipBackground => RuntimeKind switch
    {
        "native" => NativeChipBackground,
        "lua" => LuaChipBackground,
        _ => DefaultChipBackground
    };

    public Brush RuntimeChipForeground => RuntimeKind switch
    {
        "native" => NativeChipForeground,
        "lua" => LuaChipForeground,
        _ => DefaultChipForeground
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

    private static Brush Freeze(Brush brush)
    {
        brush.Freeze();
        return brush;
    }
}
