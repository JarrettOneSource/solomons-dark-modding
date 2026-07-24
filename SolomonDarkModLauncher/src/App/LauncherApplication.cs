using SolomonDarkModLauncher.Commands;
using SolomonDarkModLauncher.Launch;
using SolomonDarkModLauncher.Steam;
using SolomonDarkModding.Updates;

namespace SolomonDarkModLauncher.App;

internal static class LauncherApplication
{
    public static int Run(string[] args)
    {
        if (SteamInviteListener.TryRun(args, out var inviteListenerExitCode))
        {
            return inviteListenerExitCode;
        }

        if (LobbyDirectoryPublisher.TryRun(args, out var publisherExitCode))
        {
            return publisherExitCode;
        }

        var wantsJson = args.Any(arg => string.Equals(arg, "--json", StringComparison.OrdinalIgnoreCase));
        var wantsProgressJson = args.Any(arg =>
            string.Equals(arg, "--progress-json", StringComparison.OrdinalIgnoreCase));

        try
        {
            var command = LauncherCommandParser.Parse(args);
            if (command.ShowHelp)
            {
                LauncherConsole.PrintHelp();
                return 0;
            }

            if (command.Mode == LauncherMode.AuthenticateDirectory)
            {
                var session = SteamDirectoryAuthenticator.AuthenticateAsync(
                        command.LobbyHost.DirectoryBaseUrl,
                        command.SteamApiDllOverride)
                    .GetAwaiter()
                    .GetResult();
                if (command.JsonOutput)
                {
                    LauncherJsonConsole.PrintDirectorySession(session);
                }
                else
                {
                    LauncherConsole.PrintDirectorySession(session);
                }
                return 0;
            }

            var progress = command.ProgressJson
                ? LauncherJsonConsole.CreateProgressReporter()
                : null;
            var execution = LauncherCommandExecutor.Execute(command, progress);
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
                if (wantsProgressJson)
                {
                    LauncherJsonConsole.PrintProgress(new UpdateProgress(
                        UpdateProgressPhase.Failed,
                        $"Launcher operation failed: {ex.Message}"));
                }
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
