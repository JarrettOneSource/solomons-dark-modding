using System.Reflection;

namespace SolomonDarkModLauncher.UI.Infrastructure;

internal static class LauncherExecutableResolver
{
    public static string Resolve()
    {
        var uiBaseDirectory = AppContext.BaseDirectory;
        var workspaceRoot = WorkspaceRootLocator.FindRootPath(uiBaseDirectory);
        var configuration = Assembly.GetEntryAssembly()?
            .GetCustomAttribute<AssemblyConfigurationAttribute>()?
            .Configuration ?? "Debug";

        var candidates = new[]
        {
            Path.Combine(workspaceRoot, "SolomonDarkModLauncher", "bin", configuration, "net8.0-windows", "SolomonDarkModLauncher.exe"),
            Path.Combine(workspaceRoot, "SolomonDarkModLauncher", "bin", configuration, "net8.0-windows", "win-x86", "SolomonDarkModLauncher.exe"),
            Path.Combine(workspaceRoot, "dist", "launcher", "SolomonDarkModLauncher.exe")
        };

        foreach (var candidate in candidates)
        {
            if (IsRunnableLauncher(candidate))
            {
                return candidate;
            }
        }

        throw new FileNotFoundException(
            "Could not locate SolomonDarkModLauncher.exe. Build the launcher project first.",
            candidates.Last());
    }

    private static bool IsRunnableLauncher(string executablePath)
    {
        if (!File.Exists(executablePath))
        {
            return false;
        }

        var directory = Path.GetDirectoryName(executablePath);
        var baseName = Path.GetFileNameWithoutExtension(executablePath);
        if (string.IsNullOrWhiteSpace(directory) || string.IsNullOrWhiteSpace(baseName))
        {
            return false;
        }

        var managedDllPath = Path.Combine(directory, $"{baseName}.dll");
        var runtimeConfigPath = Path.Combine(directory, $"{baseName}.runtimeconfig.json");
        var depsPath = Path.Combine(directory, $"{baseName}.deps.json");
        return File.Exists(managedDllPath) &&
               File.Exists(runtimeConfigPath) &&
               File.Exists(depsPath);
    }
}
