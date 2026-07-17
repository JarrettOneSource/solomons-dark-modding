using SolomonDarkModLauncher.Commands;
using SolomonDarkModLauncher.Launch;

namespace SolomonDarkModLauncher.App;

internal static class LauncherApplication
{
    public static int Run(string[] args)
    {
        if (LobbyDirectoryPublisher.TryRun(args, out var publisherExitCode))
        {
            return publisherExitCode;
        }

        if (SdrProtocolHandler.TryRunManagement(args, out var protocolExitCode))
        {
            return protocolExitCode;
        }

        var wantsJson = args.Any(arg => string.Equals(arg, "--json", StringComparison.OrdinalIgnoreCase));

        try
        {
            args = SdrProtocolHandler.TranslateOpenUri(args);
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
