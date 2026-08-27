using System.Diagnostics;
using SolomonDarkModding.IO;

namespace SolomonDarkModLauncher.Staging;

internal static class StageSandboxCompatibilityLinks
{
    public static void PrepareForStageBuild(string stageRootPath)
    {
        stageRootPath = Path.GetFullPath(stageRootPath);
        if (LauncherPathPolicy.IsDesktopPath(stageRootPath))
        {
            throw new InvalidOperationException(
                "Staged save paths must be outside Desktop.");
        }
        DeleteExistingPath(Path.Combine(stageRootPath, "savegames"));
        DeleteExistingPath(Path.Combine(stageRootPath, "sandbox", "savegames"));
    }

    public static bool Materialize(string stageRootPath)
    {
        return Materialize(stageRootPath, Path.Combine(stageRootPath, "sandbox", "savegames"));
    }

    public static bool Materialize(string stageRootPath, string savegamesTargetPath)
    {
        stageRootPath = Path.GetFullPath(stageRootPath);
        savegamesTargetPath = Path.GetFullPath(savegamesTargetPath);
        if (LauncherPathPolicy.IsDesktopPath(stageRootPath) ||
            LauncherPathPolicy.IsDesktopPath(savegamesTargetPath))
        {
            throw new InvalidOperationException(
                "Staged save paths must be outside Desktop.");
        }

        var sandboxSavegamesPath = Path.Combine(stageRootPath, "sandbox", "savegames");
        var stageSavegamesPath = Path.Combine(stageRootPath, "savegames");
        if (PathsEqual(sandboxSavegamesPath, savegamesTargetPath))
        {
            Directory.CreateDirectory(sandboxSavegamesPath);
            return RecreateDirectoryJunction(stageSavegamesPath, sandboxSavegamesPath);
        }
        if (!Directory.Exists(savegamesTargetPath))
        {
            Directory.CreateDirectory(savegamesTargetPath);
        }

        var usesDirectoryMirror =
            RecreateDirectoryJunction(sandboxSavegamesPath, savegamesTargetPath);
        RecreateDirectoryJunction(stageSavegamesPath, savegamesTargetPath);
        return usesDirectoryMirror;
    }

    private static bool PathsEqual(string first, string second) =>
        string.Equals(
            Path.GetFullPath(first).TrimEnd(Path.DirectorySeparatorChar),
            Path.GetFullPath(second).TrimEnd(Path.DirectorySeparatorChar),
            OperatingSystem.IsWindows()
                ? StringComparison.OrdinalIgnoreCase
                : StringComparison.Ordinal);

    private static bool RecreateDirectoryJunction(string linkPath, string targetPath)
    {
        if (IsWineRuntime())
        {
            RecreateDirectoryMirror(linkPath, targetPath);
            return true;
        }

        if (Directory.Exists(linkPath) || File.Exists(linkPath))
        {
            DeleteExistingPath(linkPath);
        }

        if (!OperatingSystem.IsWindows())
        {
            Directory.CreateSymbolicLink(linkPath, targetPath);
            return false;
        }

        var startInfo = new ProcessStartInfo
        {
            FileName = "cmd.exe",
            Arguments = $"/c mklink /J \"{linkPath}\" \"{targetPath}\"",
            WorkingDirectory =
                Path.GetDirectoryName(linkPath) ??
                throw new InvalidOperationException(
                    "The staged save path has no parent directory."),
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
        return false;
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
