using System.Diagnostics;
using System.Windows.Forms;
using SolomonDarkModding.Updates;

namespace SolomonDarkLauncherUpdater;

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);

        UpdaterArguments arguments;
        try
        {
            arguments = UpdaterArguments.Parse(args);
        }
        catch (Exception exception)
        {
            MessageBox.Show(
                $"The launcher updater could not start.\n\n{exception.Message}",
                "Solomon Dark Revived",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
            return 1;
        }

        using var form = new UpdateProgressForm();
        form.Shown += async (_, _) => await RunUpdateAsync(form, arguments);
        Application.Run(form);
        return form.ExitCode;
    }

    private static async Task RunUpdateAsync(
        UpdateProgressForm form,
        UpdaterArguments arguments)
    {
        IProgress<UpdateProgress> progress =
            new Progress<UpdateProgress>(form.Report);
        try
        {
            progress.Report(new UpdateProgress(
                UpdateProgressPhase.Installing,
                "Waiting for the launcher to close…"));
            await WaitForLauncherAsync(arguments.WaitProcessId);

            await Task.Run(() => LauncherUpdateInstaller.Install(
                arguments.ArchivePath,
                arguments.TargetPath,
                progress));

            var restartPath = LauncherUpdateInstaller.ResolvePackagedPath(
                arguments.TargetPath,
                arguments.RestartRelativePath);
            if (!File.Exists(restartPath))
            {
                throw new FileNotFoundException(
                    "The updated launcher executable is missing.",
                    restartPath);
            }

            progress.Report(new UpdateProgress(
                UpdateProgressPhase.Restarting,
                "Restarting the updated launcher…",
                1,
                1,
                UpdateProgressUnit.Items));
            StartLauncher(restartPath, arguments);

            try
            {
                File.Delete(arguments.ArchivePath);
            }
            catch (IOException)
            {
            }
            catch (UnauthorizedAccessException)
            {
            }

            progress.Report(new UpdateProgress(
                UpdateProgressPhase.Completed,
                "Update complete. The launcher restarted.",
                1,
                1,
                UpdateProgressUnit.Items));
            await Task.Delay(TimeSpan.FromSeconds(2));
            form.CloseAfterSuccess();
        }
        catch (Exception exception)
        {
            form.ShowFailure(
                $"The launcher update could not be installed.\n{exception.Message}",
                () => RestartLauncher(arguments));
        }
    }

    private static async Task WaitForLauncherAsync(int processId)
    {
        Process process;
        try
        {
            process = Process.GetProcessById(processId);
        }
        catch (ArgumentException)
        {
            return;
        }

        using (process)
        {
            var exited = await Task.Run(() => process.WaitForExit(120_000));
            if (!exited)
            {
                throw new InvalidOperationException("The launcher did not close in time.");
            }
        }
    }

    private static void RestartLauncher(UpdaterArguments arguments)
    {
        var restartPath = LauncherUpdateInstaller.ResolvePackagedPath(
            arguments.TargetPath,
            arguments.RestartRelativePath);
        if (!File.Exists(restartPath))
        {
            throw new FileNotFoundException(
                "The launcher executable is missing.",
                restartPath);
        }
        StartLauncher(restartPath, arguments);
    }

    private static void StartLauncher(
        string restartPath,
        UpdaterArguments arguments)
    {
        var startInfo = new ProcessStartInfo(restartPath)
        {
            WorkingDirectory = arguments.TargetPath,
            UseShellExecute = true
        };
        if (!string.IsNullOrEmpty(arguments.ActivationArgument))
        {
            startInfo.ArgumentList.Add(arguments.ActivationArgument);
        }
        if (Process.Start(startInfo) is null)
        {
            throw new InvalidOperationException("The updated launcher did not start.");
        }
    }
}

internal sealed record UpdaterArguments(
    int WaitProcessId,
    string ArchivePath,
    string TargetPath,
    string RestartRelativePath,
    string ActivationArgument)
{
    public static UpdaterArguments Parse(string[] arguments)
    {
        var values = new Dictionary<string, string>(StringComparer.Ordinal);
        for (var index = 0; index < arguments.Length; index += 2)
        {
            if (index + 1 >= arguments.Length ||
                !arguments[index].StartsWith("--", StringComparison.Ordinal) ||
                !values.TryAdd(arguments[index], arguments[index + 1]))
            {
                throw new ArgumentException("The launcher updater received invalid arguments.");
            }
        }

        var allowedNames = new HashSet<string>(StringComparer.Ordinal)
        {
            "--wait-pid",
            "--archive",
            "--target",
            "--restart",
            "--activation"
        };
        if (values.Keys.Any(name => !allowedNames.Contains(name)) ||
            !values.TryGetValue("--wait-pid", out var waitProcessIdText) ||
            !int.TryParse(waitProcessIdText, out var waitProcessId) ||
            waitProcessId <= 0 ||
            !values.TryGetValue("--archive", out var archivePath) ||
            !values.TryGetValue("--target", out var targetPath) ||
            !values.TryGetValue("--restart", out var restartRelativePath))
        {
            throw new ArgumentException("The launcher updater received invalid arguments.");
        }

        return new UpdaterArguments(
            waitProcessId,
            Path.GetFullPath(archivePath),
            Path.GetFullPath(targetPath),
            restartRelativePath,
            values.GetValueOrDefault("--activation") ?? string.Empty);
    }
}
