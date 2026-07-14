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
        if (!File.Exists(settingsPath_))
        {
            return null;
        }

        var document = JsonSerializer.Deserialize<SettingsDocument>(
            File.ReadAllText(settingsPath_),
            JsonOptions);
        return string.IsNullOrWhiteSpace(document?.GameDirectory)
            ? null
            : Path.GetFullPath(document.GameDirectory);
    }

    public void SaveGameDirectory(string gameDirectory)
    {
        var directoryPath = Path.GetDirectoryName(settingsPath_)!;
        Directory.CreateDirectory(directoryPath);
        var temporaryPath = settingsPath_ + ".tmp";
        var document = new SettingsDocument
        {
            GameDirectory = Path.GetFullPath(gameDirectory)
        };
        File.WriteAllText(temporaryPath, JsonSerializer.Serialize(document, JsonOptions));
        File.Move(temporaryPath, settingsPath_, overwrite: true);
    }

    private sealed class SettingsDocument
    {
        public string? GameDirectory { get; init; }
    }
}
