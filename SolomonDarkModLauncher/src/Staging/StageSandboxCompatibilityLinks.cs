using System.Diagnostics;

namespace SolomonDarkModLauncher.Staging;

internal static class StageSandboxCompatibilityLinks
{
    public static void Materialize(string stageRootPath)
    {
        Materialize(stageRootPath, Path.Combine(stageRootPath, "sandbox", "savegames"));
    }

    public static void Materialize(string stageRootPath, string savegamesTargetPath)
    {
        var sandboxSavegamesPath = Path.Combine(stageRootPath, "sandbox", "savegames");
        if (!Directory.Exists(sandboxSavegamesPath))
        {
            Directory.CreateDirectory(sandboxSavegamesPath);
        }
        if (!Directory.Exists(savegamesTargetPath))
        {
            Directory.CreateDirectory(savegamesTargetPath);
        }

        var stageSavegamesPath = Path.Combine(stageRootPath, "savegames");
        RecreateDirectoryJunction(stageSavegamesPath, savegamesTargetPath);
    }

    private static void RecreateDirectoryJunction(string linkPath, string targetPath)
    {
        if (Directory.Exists(linkPath) || File.Exists(linkPath))
        {
            DeleteExistingPath(linkPath);
        }

        if (!OperatingSystem.IsWindows())
        {
            Directory.CreateSymbolicLink(linkPath, targetPath);
            return;
        }

        var startInfo = new ProcessStartInfo
        {
            FileName = "cmd.exe",
            Arguments = $"/c mklink /J \"{linkPath}\" \"{targetPath}\"",
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
        };

        using var process = Process.Start(startInfo);
        if (process is null)
        {
            throw new InvalidOperationException("Failed to create the staged savegames compatibility junction.");
        }

        var standardOutput = process.StandardOutput.ReadToEnd();
        var standardError = process.StandardError.ReadToEnd();
        process.WaitForExit();

        if (process.ExitCode != 0)
        {
            throw new InvalidOperationException(
                "Failed to create the staged savegames compatibility junction." +
                Environment.NewLine +
                standardOutput +
                standardError);
        }
    }

    private static void DeleteExistingPath(string path)
    {
        if (File.Exists(path) && !Directory.Exists(path))
        {
            File.Delete(path);
            return;
        }

        var directoryInfo = new DirectoryInfo(path);
        if (!directoryInfo.Exists)
        {
            return;
        }

        if ((directoryInfo.Attributes & FileAttributes.ReparsePoint) != 0)
        {
            directoryInfo.Delete();
            return;
        }

        directoryInfo.Delete(recursive: true);
    }
}
