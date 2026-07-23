namespace SolomonDarkModLauncher.App;

using SolomonDarkModLauncher.Steam;

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

    public static void PrintDirectorySession(SteamDirectorySession session)
    {
        var account = session.LinkedAccount is null
            ? "no linked SDR account"
            : $"SDR account {session.LinkedAccount.Username}";
        Console.WriteLine(
            $"Steam directory session ready for {session.SteamId} ({account}) until {session.ExpiresAtUtc:O}.");
    }
}
