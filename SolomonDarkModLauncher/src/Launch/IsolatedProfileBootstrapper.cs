using SolomonDarkModLauncher.Workspace;

namespace SolomonDarkModLauncher.Launch;

internal static class IsolatedProfileBootstrapper
{
    private const string AppDataEnvironmentVariable = "APPDATA";
    private const string LocalAppDataEnvironmentVariable = "LOCALAPPDATA";

    public static LaunchOptions CreateLaunchOptions(
        WorkspacePaths workspace,
        IReadOnlyDictionary<string, string>? existingOverrides = null,
        string? retailGameAppDataPath = null)
    {
        SeedProfileIfNeeded(workspace, retailGameAppDataPath);

        var environmentOverrides = new Dictionary<string, string>(
            StringComparer.OrdinalIgnoreCase);
        if (existingOverrides is not null)
        {
            foreach (var pair in existingOverrides)
            {
                environmentOverrides[pair.Key] = pair.Value;
            }
        }

        environmentOverrides[AppDataEnvironmentVariable] = workspace.RoamingAppDataPath;
        environmentOverrides[LocalAppDataEnvironmentVariable] = workspace.LocalAppDataPath;
        return new LaunchOptions(environmentOverrides);
    }

    private static void SeedProfileIfNeeded(
        WorkspacePaths workspace,
        string? retailGameAppDataPath)
    {
        Directory.CreateDirectory(workspace.ProfileRootPath);
        Directory.CreateDirectory(workspace.RoamingAppDataPath);
        Directory.CreateDirectory(workspace.LocalAppDataPath);

        if (Directory.Exists(workspace.IsolatedGameAppDataPath))
        {
            return;
        }

        if (!string.IsNullOrWhiteSpace(retailGameAppDataPath) && Directory.Exists(retailGameAppDataPath))
        {
            CopyDirectory(retailGameAppDataPath, workspace.IsolatedGameAppDataPath);
            return;
        }

        Directory.CreateDirectory(workspace.IsolatedGameAppDataPath);
    }

    private static void CopyDirectory(string sourcePath, string destinationPath)
    {
        Directory.CreateDirectory(destinationPath);

        foreach (var directoryPath in Directory.EnumerateDirectories(sourcePath))
        {
            var directoryName = Path.GetFileName(directoryPath);
            CopyDirectory(directoryPath, Path.Combine(destinationPath, directoryName));
        }

        foreach (var filePath in Directory.EnumerateFiles(sourcePath))
        {
            var fileName = Path.GetFileName(filePath);
            File.Copy(filePath, Path.Combine(destinationPath, fileName), overwrite: true);
        }
    }
}
