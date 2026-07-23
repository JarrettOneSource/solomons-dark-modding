using System.Diagnostics;
using System.Windows.Forms;
using SolomonDarkLauncherUpdater;

UpdaterArguments? parsedArguments = null;
try
{
    var arguments = UpdaterArguments.Parse(args);
    parsedArguments = arguments;
    WaitForLauncher(arguments.WaitProcessId);
    LauncherUpdateInstaller.Install(arguments.ArchivePath, arguments.TargetPath);

    var restartPath = LauncherUpdateInstaller.ResolvePackagedPath(
        arguments.TargetPath,
        arguments.RestartRelativePath);
    if (!File.Exists(restartPath))
    {
        throw new FileNotFoundException("The updated launcher executable is missing.", restartPath);
    }

    var startInfo = new ProcessStartInfo(restartPath)
    {
        WorkingDirectory = arguments.TargetPath,
        UseShellExecute = true
    };
    if (!string.IsNullOrEmpty(arguments.ActivationArgument))
    {
        startInfo.ArgumentList.Add(arguments.ActivationArgument);
    }
    Process.Start(startInfo);

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

    return 0;
}
catch (Exception exception)
{
    MessageBox.Show(
        $"The launcher update could not be installed.\n\n{exception.Message}",
        "Solomon Dark Revived",
        MessageBoxButtons.OK,
        MessageBoxIcon.Error);
    if (parsedArguments is not null)
    {
        RestartLauncher(parsedArguments);
    }
    return 1;
}

static void WaitForLauncher(int processId)
{
    try
    {
        using var process = Process.GetProcessById(processId);
        if (!process.WaitForExit(120_000))
        {
            throw new InvalidOperationException("The launcher did not close in time.");
        }
    }
    catch (ArgumentException)
    {
    }
}

static void RestartLauncher(UpdaterArguments arguments)
{
    try
    {
        var restartPath = LauncherUpdateInstaller.ResolvePackagedPath(
            arguments.TargetPath,
            arguments.RestartRelativePath);
        if (!File.Exists(restartPath))
        {
            return;
        }

        var startInfo = new ProcessStartInfo(restartPath)
        {
            WorkingDirectory = arguments.TargetPath,
            UseShellExecute = true
        };
        if (!string.IsNullOrEmpty(arguments.ActivationArgument))
        {
            startInfo.ArgumentList.Add(arguments.ActivationArgument);
        }
        Process.Start(startInfo);
    }
    catch
    {
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
