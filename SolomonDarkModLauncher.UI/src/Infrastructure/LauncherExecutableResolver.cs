using System.Reflection;
using SolomonDarkModding.Distribution;

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
            Path.Combine(uiBaseDirectory, DistributionLayout.LauncherDirectoryName, "SolomonDarkModLauncher.exe"),
            Path.Combine(workspaceRoot, DistributionLayout.LauncherDirectoryName, "SolomonDarkModLauncher.exe"),
            Path.Combine(workspaceRoot, "SolomonDarkModLauncher", "bin", configuration, "net8.0-windows", "SolomonDarkModLauncher.exe"),
            Path.Combine(workspaceRoot, "SolomonDarkModLauncher", "bin", configuration, "net8.0-windows", "win-x86", "SolomonDarkModLauncher.exe"),
            Path.Combine(workspaceRoot, "dist", "launcher", "SolomonDarkModLauncher.exe")
        };

        foreach (var candidate in candidates)
        {
            if (File.Exists(candidate))
            {
                return candidate;
            }
        }

        throw new FileNotFoundException(
            "SolomonDarkModLauncher.exe is not in the beta package. Extract the complete beta package again.",
            candidates[0]);
    }
}
