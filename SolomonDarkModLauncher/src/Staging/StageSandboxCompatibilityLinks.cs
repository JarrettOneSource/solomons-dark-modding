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
        if (IsWineRuntime())
        {
            RecreateDirectoryMirror(linkPath, targetPath);
            return;
        }

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

    private static bool IsWineRuntime() =>
        OperatingSystem.IsWindows() &&
        (!string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable("WINEPREFIX")) ||
         !string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable("WINELOADERNOEXEC")));

    private static void RecreateDirectoryMirror(string directoryPath, string sourcePath)
    {
        DeleteExistingPath(directoryPath);

        // Wine's `mklink /J` implementation on a DrvFs workspace materializes
        // this malformed sibling instead of a usable Windows junction.
        var malformedWineJunctionPath = directoryPath + "?";
        DeleteExistingPath(malformedWineJunctionPath);

        Directory.CreateDirectory(directoryPath);
        CopyDirectoryContents(sourcePath, directoryPath);
    }

    private static void CopyDirectoryContents(string sourcePath, string destinationPath)
    {
        foreach (var sourceDirectoryPath in Directory.EnumerateDirectories(sourcePath))
        {
            var destinationDirectoryPath = Path.Combine(
                destinationPath,
                Path.GetFileName(sourceDirectoryPath));
            Directory.CreateDirectory(destinationDirectoryPath);
            CopyDirectoryContents(sourceDirectoryPath, destinationDirectoryPath);
        }

        foreach (var sourceFilePath in Directory.EnumerateFiles(sourcePath))
        {
            File.Copy(
                sourceFilePath,
                Path.Combine(destinationPath, Path.GetFileName(sourceFilePath)),
                overwrite: true);
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
