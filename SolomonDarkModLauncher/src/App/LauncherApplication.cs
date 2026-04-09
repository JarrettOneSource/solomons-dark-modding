using SolomonDarkModLauncher.Commands;

namespace SolomonDarkModLauncher.App;

internal static class LauncherApplication
{
    public static int Run(string[] args)
    {
        var wantsJson = args.Any(arg => string.Equals(arg, "--json", StringComparison.OrdinalIgnoreCase));

        try
        {
            var command = LauncherCommandParser.Parse(args);
            if (command.ShowHelp)
            {
                LauncherConsole.PrintHelp();
                return 0;
            }

            var execution = LauncherCommandExecutor.Execute(command);
            if (command.JsonOutput)
            {
                LauncherJsonConsole.PrintExecution(execution);
            }
            else
            {
                LauncherConsole.PrintExecution(execution);
            }

            return 0;
        }
        catch (Exception ex)
        {
            if (wantsJson)
            {
                LauncherJsonConsole.PrintError(ex);
            }
            else
            {
                LauncherConsole.PrintError(ex);
            }

            return 1;
        }
    }
}
