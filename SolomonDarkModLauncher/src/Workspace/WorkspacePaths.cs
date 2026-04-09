namespace SolomonDarkModLauncher.Workspace;

internal sealed class WorkspacePaths
{
    public required string RootPath { get; init; }
    public required string InstanceName { get; init; }
    public required string ConfigRootPath { get; init; }
    public required string ModsRootPath { get; init; }
    public required string RuntimeRootPath { get; init; }
    public required string ModStatePath { get; init; }
    public required string StageRootPath { get; init; }
    public required string ProfileRootPath { get; init; }
    public required string RoamingAppDataPath { get; init; }
    public required string LocalAppDataPath { get; init; }
    public required string IsolatedGameAppDataPath { get; init; }

    public static WorkspacePaths Create(
        string rootPath,
        string? modsRootOverride,
        string? runtimeRootOverride,
        string? stageRootOverride,
        string? instanceName = null)
    {
        var normalizedRootPath = Path.GetFullPath(rootPath);
        var normalizedInstanceName = LauncherInstance.Normalize(instanceName);
        var configRootPath = Path.Combine(normalizedRootPath, "config");
        var runtimeBaseRootPath = ResolveRuntimeBaseRoot(normalizedRootPath, runtimeRootOverride);
        var runtimeRootPath = ResolveRuntimeRoot(normalizedRootPath, runtimeRootOverride, normalizedInstanceName);
        var modsRootPath = modsRootOverride is null
            ? Path.Combine(normalizedRootPath, "mods")
            : Path.GetFullPath(modsRootOverride);
        var stageRootPath = stageRootOverride is null
            ? Path.Combine(runtimeRootPath, "stage")
            : Path.GetFullPath(stageRootOverride);
        var modStatePath = Path.Combine(runtimeRootPath, "mod-manager-state.json");
        var profileRootPath = Path.Combine(runtimeRootPath, "profile");
        var appDataRootPath = Path.Combine(profileRootPath, "AppData");
        var roamingAppDataPath = Path.Combine(appDataRootPath, "Roaming");
        var localAppDataPath = Path.Combine(appDataRootPath, "Local");
        var isolatedGameAppDataPath = Path.Combine(roamingAppDataPath, "solomondark");

        Directory.CreateDirectory(modsRootPath);
        Directory.CreateDirectory(configRootPath);
        Directory.CreateDirectory(runtimeBaseRootPath);
        Directory.CreateDirectory(runtimeRootPath);
        Directory.CreateDirectory(profileRootPath);
        Directory.CreateDirectory(roamingAppDataPath);
        Directory.CreateDirectory(localAppDataPath);
        SeedNamedInstanceModStateIfNeeded(
            runtimeBaseRootPath,
            runtimeRootOverride,
            normalizedInstanceName,
            modStatePath);

        return new WorkspacePaths
        {
            RootPath = normalizedRootPath,
            InstanceName = normalizedInstanceName,
            ConfigRootPath = configRootPath,
            ModsRootPath = modsRootPath,
            RuntimeRootPath = runtimeRootPath,
            ModStatePath = modStatePath,
            StageRootPath = stageRootPath,
            ProfileRootPath = profileRootPath,
            RoamingAppDataPath = roamingAppDataPath,
            LocalAppDataPath = localAppDataPath,
            IsolatedGameAppDataPath = isolatedGameAppDataPath
        };
    }

    public static string ResolveRuntimeBaseRoot(string rootPath, string? runtimeRootOverride)
    {
        var normalizedRootPath = Path.GetFullPath(rootPath);
        return runtimeRootOverride is null
            ? Path.Combine(normalizedRootPath, "runtime")
            : Path.GetFullPath(runtimeRootOverride);
    }

    public static string ResolveRuntimeRoot(string rootPath, string? runtimeRootOverride, string? instanceName)
    {
        var runtimeBaseRootPath = ResolveRuntimeBaseRoot(rootPath, runtimeRootOverride);
        var normalizedInstanceName = LauncherInstance.Normalize(instanceName);
        if (LauncherInstance.IsDefault(normalizedInstanceName))
        {
            return runtimeBaseRootPath;
        }

        return Path.Combine(runtimeBaseRootPath, "instances", normalizedInstanceName);
    }

    public static IReadOnlyList<string> EnumerateKnownInstances(string rootPath, string? runtimeRootOverride)
    {
        var runtimeBaseRootPath = ResolveRuntimeBaseRoot(rootPath, runtimeRootOverride);
        var instances = new SortedSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            LauncherInstance.DefaultName
        };

        var instancesRootPath = Path.Combine(runtimeBaseRootPath, "instances");
        if (!Directory.Exists(instancesRootPath))
        {
            return instances.ToArray();
        }

        foreach (var instanceRootPath in Directory.EnumerateDirectories(instancesRootPath))
        {
            var candidateName = Path.GetFileName(instanceRootPath);
            if (LauncherInstance.TryNormalize(candidateName, out var normalizedInstanceName))
            {
                instances.Add(normalizedInstanceName);
            }
        }

        return instances.ToArray();
    }

    private static void SeedNamedInstanceModStateIfNeeded(
        string runtimeBaseRootPath,
        string? runtimeRootOverride,
        string normalizedInstanceName,
        string modStatePath)
    {
        if (!string.IsNullOrWhiteSpace(runtimeRootOverride) ||
            LauncherInstance.IsDefault(normalizedInstanceName) ||
            File.Exists(modStatePath))
        {
            return;
        }

        var defaultModStatePath = Path.Combine(runtimeBaseRootPath, "mod-manager-state.json");
        if (!File.Exists(defaultModStatePath))
        {
            return;
        }

        File.Copy(defaultModStatePath, modStatePath, overwrite: false);
    }
}
