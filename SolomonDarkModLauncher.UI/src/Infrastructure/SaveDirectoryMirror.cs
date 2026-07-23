namespace SolomonDarkModLauncher.UI.Infrastructure;

internal static class SaveDirectoryMirror
{
    public static void Replace(string sourcePath, string destinationPath)
    {
        sourcePath = Path.GetFullPath(sourcePath);
        destinationPath = Path.GetFullPath(destinationPath);
        if (!Directory.Exists(sourcePath))
        {
            throw new DirectoryNotFoundException($"Save folder not found: {sourcePath}");
        }
        if (PathsOverlap(sourcePath, destinationPath))
        {
            throw new InvalidOperationException(
                "The source and destination save folders must be separate.");
        }

        var parentPath = Path.GetDirectoryName(destinationPath)
            ?? throw new InvalidOperationException("The save destination has no parent folder.");
        Directory.CreateDirectory(parentPath);
        var incomingPath = destinationPath + $".incoming-{Guid.NewGuid():N}";
        var previousPath = destinationPath + $".previous-{Guid.NewGuid():N}";
        try
        {
            CopyDirectory(sourcePath, incomingPath);
            if (Directory.Exists(destinationPath))
            {
                Directory.Move(destinationPath, previousPath);
            }
            Directory.Move(incomingPath, destinationPath);
            if (Directory.Exists(previousPath) && Directory.Exists(destinationPath))
            {
                Directory.Delete(previousPath, recursive: true);
            }
        }
        catch
        {
            if (!Directory.Exists(destinationPath) && Directory.Exists(previousPath))
            {
                Directory.Move(previousPath, destinationPath);
            }
            throw;
        }
        finally
        {
            if (Directory.Exists(incomingPath))
            {
                Directory.Delete(incomingPath, recursive: true);
            }
            if (Directory.Exists(previousPath) && Directory.Exists(destinationPath))
            {
                Directory.Delete(previousPath, recursive: true);
            }
        }
    }

    private static void CopyDirectory(string sourcePath, string destinationPath)
    {
        var source = new DirectoryInfo(sourcePath);
        if ((source.Attributes & FileAttributes.ReparsePoint) != 0)
        {
            throw new InvalidDataException("Save folders cannot contain directory links.");
        }

        Directory.CreateDirectory(destinationPath);
        foreach (var directory in source.EnumerateDirectories())
        {
            CopyDirectory(directory.FullName, Path.Combine(destinationPath, directory.Name));
        }
        foreach (var file in source.EnumerateFiles())
        {
            if ((file.Attributes & FileAttributes.ReparsePoint) != 0)
            {
                throw new InvalidDataException("Save folders cannot contain file links.");
            }
            var destinationFilePath = Path.Combine(destinationPath, file.Name);
            File.Copy(file.FullName, destinationFilePath, overwrite: false);
            File.SetLastWriteTimeUtc(destinationFilePath, file.LastWriteTimeUtc);
        }
    }

    private static bool PathsOverlap(string firstPath, string secondPath)
    {
        var comparison = OperatingSystem.IsWindows()
            ? StringComparison.OrdinalIgnoreCase
            : StringComparison.Ordinal;
        var first = EnsureTrailingSeparator(firstPath);
        var second = EnsureTrailingSeparator(secondPath);
        return first.StartsWith(second, comparison) || second.StartsWith(first, comparison);
    }

    private static string EnsureTrailingSeparator(string path) =>
        path.EndsWith(Path.DirectorySeparatorChar)
            ? path
            : path + Path.DirectorySeparatorChar;
}
