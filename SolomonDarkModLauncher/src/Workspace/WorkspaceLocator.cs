using SolomonDarkModding.Distribution;

namespace SolomonDarkModLauncher.Workspace;

internal static class WorkspaceLocator
{
    private const string SolutionFileName = "SolomonDarkModding.sln";

    public static string FindRootPath(string launcherBaseDirectory)
    {
        var current = new DirectoryInfo(Path.GetFullPath(launcherBaseDirectory));
        while (current is not null)
        {
            var portableMarkerPath = Path.Combine(
                current.FullName,
                DistributionLayout.PortableRootMarkerFileName);
            if (File.Exists(portableMarkerPath))
            {
                return current.FullName;
            }

            var solutionPath = Path.Combine(current.FullName, SolutionFileName);
            if (File.Exists(solutionPath))
            {
                return current.FullName;
            }

            current = current.Parent;
        }

        throw new DirectoryNotFoundException(
            $"Could not locate {DistributionLayout.PortableRootMarkerFileName} or " +
            $"{SolutionFileName} by walking up from {launcherBaseDirectory}");
    }
}
