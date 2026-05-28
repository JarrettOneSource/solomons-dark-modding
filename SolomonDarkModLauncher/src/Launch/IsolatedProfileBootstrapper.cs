using SolomonDarkModLauncher.Workspace;

namespace SolomonDarkModLauncher.Launch;

internal static class IsolatedProfileBootstrapper
{
    private const string AppDataEnvironmentVariable = "APPDATA";
    private const string LocalAppDataEnvironmentVariable = "LOCALAPPDATA";

    public static LaunchOptions CreateLaunchOptions(
        WorkspacePaths workspace,
        IReadOnlyDictionary<string, string>? existingOverrides = null,
        string? retailGameAppDataPath = null,
        bool temporaryProfile = false)
    {
        var profile = temporaryProfile
            ? PrepareTemporaryProfile(workspace, retailGameAppDataPath)
            : PreparePersistentProfile(workspace, retailGameAppDataPath);

        var environmentOverrides = new Dictionary<string, string>(
            StringComparer.OrdinalIgnoreCase);
        if (existingOverrides is not null)
        {
            foreach (var pair in existingOverrides)
            {
                environmentOverrides[pair.Key] = pair.Value;
            }
        }

        environmentOverrides[AppDataEnvironmentVariable] = profile.RoamingAppDataPath;
        environmentOverrides[LocalAppDataEnvironmentVariable] = profile.LocalAppDataPath;
        return new LaunchOptions(
            environmentOverrides,
            temporaryProfile,
            profile.ProfileRootPath,
            profile.SavegamesRootPath);
    }

    private static ResolvedProfilePaths PreparePersistentProfile(
        WorkspacePaths workspace,
        string? retailGameAppDataPath)
    {
        Directory.CreateDirectory(workspace.ProfileRootPath);
        Directory.CreateDirectory(workspace.RoamingAppDataPath);
        Directory.CreateDirectory(workspace.LocalAppDataPath);

        if (Directory.Exists(workspace.IsolatedGameAppDataPath))
        {
            return ResolvedProfilePaths.FromWorkspace(workspace);
        }

        if (!string.IsNullOrWhiteSpace(retailGameAppDataPath) && Directory.Exists(retailGameAppDataPath))
        {
            CopyDirectory(retailGameAppDataPath, workspace.IsolatedGameAppDataPath);
            return ResolvedProfilePaths.FromWorkspace(workspace);
        }

        Directory.CreateDirectory(workspace.IsolatedGameAppDataPath);
        return ResolvedProfilePaths.FromWorkspace(workspace);
    }

    private static ResolvedProfilePaths PrepareTemporaryProfile(
        WorkspacePaths workspace,
        string? retailGameAppDataPath)
    {
        var profileRootPath = Path.Combine(workspace.RuntimeRootPath, "temporary-client-profile");
        ResetDirectory(profileRootPath);

        var appDataRootPath = Path.Combine(profileRootPath, "AppData");
        var roamingAppDataPath = Path.Combine(appDataRootPath, "Roaming");
        var localAppDataPath = Path.Combine(appDataRootPath, "Local");
        var isolatedGameAppDataPath = Path.Combine(roamingAppDataPath, "solomondark");
        var savegamesRootPath = Path.Combine(profileRootPath, "savegames");

        Directory.CreateDirectory(roamingAppDataPath);
        Directory.CreateDirectory(localAppDataPath);
        Directory.CreateDirectory(savegamesRootPath);
        if (!string.IsNullOrWhiteSpace(retailGameAppDataPath) && Directory.Exists(retailGameAppDataPath))
        {
            CopyDirectory(retailGameAppDataPath, isolatedGameAppDataPath);
        }
        else
        {
            Directory.CreateDirectory(isolatedGameAppDataPath);
        }

        return new ResolvedProfilePaths(
            profileRootPath,
            roamingAppDataPath,
            localAppDataPath,
            isolatedGameAppDataPath,
            savegamesRootPath);
    }

    private static void ResetDirectory(string path)
    {
        if (Directory.Exists(path))
        {
            Directory.Delete(path, recursive: true);
        }
        Directory.CreateDirectory(path);
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

    private sealed record ResolvedProfilePaths(
        string ProfileRootPath,
        string RoamingAppDataPath,
        string LocalAppDataPath,
        string IsolatedGameAppDataPath,
        string SavegamesRootPath)
    {
        public static ResolvedProfilePaths FromWorkspace(WorkspacePaths workspace) =>
            new(
                workspace.ProfileRootPath,
                workspace.RoamingAppDataPath,
                workspace.LocalAppDataPath,
                workspace.IsolatedGameAppDataPath,
                Path.Combine(workspace.StageRootPath, "sandbox", "savegames"));
    }
}
