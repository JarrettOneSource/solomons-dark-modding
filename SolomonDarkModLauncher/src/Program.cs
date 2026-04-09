using SolomonDarkModLauncher.App;

namespace SolomonDarkModLauncher;

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        return LauncherApplication.Run(args);
    }
}
