using System.Text.Json;

namespace SolomonDarkModLauncher.UI.Infrastructure;

internal sealed class LauncherUiSettingsStore
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = true
    };

    private readonly string settingsPath_;

    public LauncherUiSettingsStore()
    {
        var settingsRoot = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "SolomonDarkMultiplayerBeta");
        settingsPath_ = Path.Combine(settingsRoot, "settings.json");
        RuntimeRoot = Path.Combine(settingsRoot, "runtime");
    }

    public string RuntimeRoot { get; }

    public string? LoadGameDirectory()
    {
        var gameDirectory = Load().GameDirectory;
        return string.IsNullOrWhiteSpace(gameDirectory)
            ? null
            : Path.GetFullPath(gameDirectory);
    }

    public void SaveGameDirectory(string gameDirectory)
    {
        Save(Load() with { GameDirectory = Path.GetFullPath(gameDirectory) });
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
    }
}
