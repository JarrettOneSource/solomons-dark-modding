namespace SolomonDarkModLauncher.App;

internal static class LauncherConsole
{
    public static void PrintHelp()
    {
        Console.WriteLine(LauncherOutputFormatter.FormatHelp());
    }

    public static void PrintExecution(LauncherCommandExecution execution)
    {
        Console.WriteLine(LauncherOutputFormatter.FormatExecution(execution));
    }

    public static void PrintError(Exception ex)
    {
        Console.Error.WriteLine(LauncherOutputFormatter.FormatError(ex));
    }
}
