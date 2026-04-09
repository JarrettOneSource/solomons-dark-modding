using System.Diagnostics;

namespace SolomonDarkModLauncher.Staging;

internal static class StageRootProcessCleaner
{
    public static void TerminateProcessesUsingStage(string stageRootPath)
    {
        if (string.IsNullOrWhiteSpace(stageRootPath))
        {
            return;
        }

        var normalizedStageRoot = NormalizeDirectoryPath(stageRootPath);
        foreach (var process in Process.GetProcesses())
        {
            try
            {
                var processPath = process.MainModule?.FileName;
                if (string.IsNullOrWhiteSpace(processPath))
                {
                    continue;
                }

                var normalizedProcessPath = Path.GetFullPath(processPath);
                if (!normalizedProcessPath.StartsWith(normalizedStageRoot, StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                process.Kill(entireProcessTree: true);
                process.WaitForExit(5000);
            }
            catch (InvalidOperationException)
            {
            }
            catch (NotSupportedException)
            {
            }
            catch (System.ComponentModel.Win32Exception)
            {
            }
            finally
            {
                process.Dispose();
            }
        }
    }

    private static string NormalizeDirectoryPath(string path)
    {
        var fullPath = Path.GetFullPath(path);
        if (!fullPath.EndsWith(Path.DirectorySeparatorChar) && !fullPath.EndsWith(Path.AltDirectorySeparatorChar))
        {
            fullPath += Path.DirectorySeparatorChar;
        }

        return fullPath;
    }
}
