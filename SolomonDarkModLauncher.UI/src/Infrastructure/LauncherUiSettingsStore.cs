using System.Text.Json;
using SolomonDarkModding.IO;

namespace SolomonDarkModLauncher.UI.Infrastructure;

internal sealed class LauncherUiSettingsStore
{
    private const string SettingsDirectoryName = "SolomonDarkMultiplayerBeta";

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = true
    };

    private readonly string settingsPath_;

    public LauncherUiSettingsStore(string? settingsRootOverride = null)
    {
        SettingsRoot = string.IsNullOrWhiteSpace(settingsRootOverride)
            ? ResolveDefaultSettingsRoot()
            : Path.GetFullPath(settingsRootOverride, AppContext.BaseDirectory);
        settingsPath_ = Path.Combine(SettingsRoot, "settings.json");
        RuntimeRoot = Path.Combine(SettingsRoot, "runtime");
        SavesRoot = Path.Combine(SettingsRoot, "saves");
    }

    public string SettingsRoot { get; }
    public string RuntimeRoot { get; }
    public string SavesRoot { get; }

    internal static string ResolveDefaultSettingsRoot()
    {
        var rejectedPaths = new List<string>();
        var root = LauncherPathPolicy.ResolveApplicationDataRoot(
            rejectedPaths.Add,
            applicationDirectoryName: SettingsDirectoryName);
        foreach (var message in rejectedPaths)
        {
            LauncherLog.Write("paths", message, root);
        }
        return root;
    }

    public string? LoadGameDirectory()
    {
        var gameDirectory = Load().GameDirectory;
        if (string.IsNullOrWhiteSpace(gameDirectory))
        {
            return null;
        }

        var normalizedPath = Path.GetFullPath(
            gameDirectory,
            AppContext.BaseDirectory);
        if (!LauncherPathPolicy.IsDesktopPath(normalizedPath))
        {
            return normalizedPath;
        }

        LauncherLog.Write(
            "paths",
            $"Ignored a saved Desktop game directory: {normalizedPath}",
            SettingsRoot);
        return null;
    }

    public void SaveGameDirectory(string gameDirectory)
    {
        var normalizedPath = Path.GetFullPath(
            gameDirectory,
            AppContext.BaseDirectory);
        if (LauncherPathPolicy.IsDesktopPath(normalizedPath))
        {
            throw new InvalidOperationException(
                "Choose a game folder outside Desktop.");
        }

        Save(Load() with { GameDirectory = normalizedPath });
    }

    public string? LoadDirectoryUrl()
    {
        var directoryUrl = Load().DirectoryUrl;
        return string.IsNullOrWhiteSpace(directoryUrl) ? null : directoryUrl.Trim();
    }

    public void SaveDirectoryUrl(string? directoryUrl)
    {
        Save(Load() with
        {
            DirectoryUrl = string.IsNullOrWhiteSpace(directoryUrl) ? null : directoryUrl.Trim()
        });
    }

    public bool LoadShowStockTutorial() => Load().ShowStockTutorial;

    public void SaveShowStockTutorial(bool showStockTutorial)
    {
        Save(Load() with { ShowStockTutorial = showStockTutorial });
    }

    public bool LoadDisableAudio() => Load().DisableAudio;

    public void SaveDisableAudio(bool disableAudio)
    {
        Save(Load() with { DisableAudio = disableAudio });
    }

    public bool LoadHeadless() => Load().Headless;

    public void SaveHeadless(bool headless)
    {
        Save(Load() with { Headless = headless });
    }

    public int LoadActiveSaveSlot()
    {
        var slot = Load().ActiveSaveSlot;
        return slot is >= 0 and < LocalSaveCatalog.SlotCount ? slot : 0;
    }

    public void SaveActiveSaveSlot(int slot)
    {
        if (slot is < 0 or >= LocalSaveCatalog.SlotCount)
        {
            throw new ArgumentOutOfRangeException(nameof(slot));
        }
        Save(Load() with { ActiveSaveSlot = slot });
    }

    private SettingsDocument Load()
    {
        if (!File.Exists(settingsPath_))
        {
            return new SettingsDocument();
        }

        return JsonSerializer.Deserialize<SettingsDocument>(
            File.ReadAllText(settingsPath_),
            JsonOptions) ?? new SettingsDocument();
    }

    private void Save(SettingsDocument document)
    {
        var directoryPath = Path.GetDirectoryName(settingsPath_)!;
        Directory.CreateDirectory(directoryPath);
        var temporaryPath = settingsPath_ + ".tmp";
        File.WriteAllText(temporaryPath, JsonSerializer.Serialize(document, JsonOptions));
        File.Move(temporaryPath, settingsPath_, overwrite: true);
    }

    private sealed record SettingsDocument
    {
        public string? GameDirectory { get; init; }
        public string? DirectoryUrl { get; init; }
        public int ActiveSaveSlot { get; init; }
        public bool ShowStockTutorial { get; init; }
        public bool DisableAudio { get; init; }
        public bool Headless { get; init; }
    }
}
