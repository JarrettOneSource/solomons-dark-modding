using System.Reflection;

namespace SolomonDarkModLauncher.Infrastructure;

internal static class LauncherVersionInfo
{
    public static string Informational { get; } =
        typeof(LauncherVersionInfo).Assembly
            .GetCustomAttribute<AssemblyInformationalVersionAttribute>()?
            .InformationalVersion ?? "unknown";
}
