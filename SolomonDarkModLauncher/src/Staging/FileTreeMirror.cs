using System.Diagnostics;
using System.IO;
using System.Security.Principal;

namespace SolomonDarkModLauncher.Staging;

internal static class FileTreeMirror
{
    private const string PreservedStageMetadataDirectoryName = ".sdmod";

    public static StageMirrorResult Synchronize(string sourceRootPath, string destinationRootPath)
    {
        var sourceRoot = new DirectoryInfo(sourceRootPath);
        if (!sourceRoot.Exists)
        {
            throw new DirectoryNotFoundException($"The launcher could not find the Solomon Dark install directory: {sourceRootPath}");
        }

        var destinationRoot = new DirectoryInfo(destinationRootPath);
        var counters = new MirrorCounters();
        SynchronizeDirectory(sourceRoot, destinationRoot, preserveMetadataDirectory: true, counters);
        return counters.ToResult();
    }

    private static void SynchronizeDirectory(
        DirectoryInfo sourceDirectory,
        DirectoryInfo destinationDirectory,
        bool preserveMetadataDirectory,
        MirrorCounters counters)
    {
        if (!destinationDirectory.Exists)
        {
            destinationDirectory.Create();
            counters.CreatedDirectoryCount++;
        }

        var sourceDirectories = EnumerateDirectories(sourceDirectory)
            .ToDictionary(directory => directory.Name, StringComparer.OrdinalIgnoreCase);
        var sourceFiles = EnumerateFiles(sourceDirectory)
            .ToDictionary(file => file.Name, StringComparer.OrdinalIgnoreCase);

        foreach (var destinationSubdirectory in EnumerateDirectories(destinationDirectory))
        {
            if (sourceDirectories.ContainsKey(destinationSubdirectory.Name))
            {
                continue;
            }

            if (preserveMetadataDirectory &&
                string.Equals(destinationSubdirectory.Name, PreservedStageMetadataDirectoryName, StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            DeleteDirectoryTree(destinationSubdirectory, counters);
        }

        foreach (var destinationFile in EnumerateFiles(destinationDirectory))
        {
            if (sourceFiles.ContainsKey(destinationFile.Name))
            {
                continue;
            }

            DeleteFile(destinationFile, counters);
        }

        foreach (var sourceSubdirectory in sourceDirectories.Values)
        {
            var synchronizedDirectory = new DirectoryInfo(Path.Combine(destinationDirectory.FullName, sourceSubdirectory.Name));
            SynchronizeDirectory(sourceSubdirectory, synchronizedDirectory, preserveMetadataDirectory: false, counters);
        }

        foreach (var sourceFile in sourceFiles.Values)
        {
            SynchronizeFile(sourceFile, destinationDirectory.FullName, counters);
        }
    }

    private static void SynchronizeFile(FileInfo sourceFile, string destinationDirectoryPath, MirrorCounters counters)
    {
        var destinationPath = Path.Combine(destinationDirectoryPath, sourceFile.Name);
        var destinationFile = new FileInfo(destinationPath);
        if (destinationFile.Exists && FilesMatch(sourceFile, destinationFile))
        {
            counters.SkippedFileCount++;
            return;
        }

        if (destinationFile.Exists)
        {
            ClearRestrictedAttributes(destinationFile);
        }

        File.Copy(sourceFile.FullName, destinationPath, overwrite: true);
        File.SetLastWriteTimeUtc(destinationPath, sourceFile.LastWriteTimeUtc);
        counters.CopiedFileCount++;
    }

    private static bool FilesMatch(FileInfo sourceFile, FileInfo destinationFile)
    {
        sourceFile.Refresh();
        destinationFile.Refresh();
        return sourceFile.Length == destinationFile.Length &&
               sourceFile.LastWriteTimeUtc == destinationFile.LastWriteTimeUtc;
    }

    private static void DeleteDirectoryTree(DirectoryInfo directory, MirrorCounters counters)
    {
        if (IsReparsePoint(directory))
        {
            DeleteFileSystemEntry(directory, () => directory.Delete());
            counters.DeletedDirectoryCount++;
            return;
        }

        foreach (var childDirectory in EnumerateDirectories(directory))
        {
            DeleteDirectoryTree(childDirectory, counters);
        }

        foreach (var childFile in EnumerateFiles(directory))
        {
            DeleteFile(childFile, counters);
        }

        DeleteFileSystemEntry(directory, () => directory.Delete());
        counters.DeletedDirectoryCount++;
    }

    private static void DeleteFile(FileInfo file, MirrorCounters counters)
    {
        DeleteFileSystemEntry(file, file.Delete);
        counters.DeletedFileCount++;
    }

    private static void DeleteFileSystemEntry(FileSystemInfo entry, Action deleteAction)
    {
        try
        {
            deleteAction();
        }
        catch (UnauthorizedAccessException)
        {
            PrepareForDeletion(entry);
            deleteAction();
        }
        catch (IOException)
        {
            PrepareForDeletion(entry);
            deleteAction();
        }
    }

    private static void PrepareForDeletion(FileSystemInfo entry)
    {
        ClearRestrictedAttributes(entry);
        if (OperatingSystem.IsWindows())
        {
            GrantCurrentUserFullControl(entry.FullName, entry is DirectoryInfo);
        }
    }

    private static void ClearRestrictedAttributes(FileSystemInfo entry)
    {
        entry.Attributes &= ~(FileAttributes.ReadOnly | FileAttributes.Hidden | FileAttributes.System);
    }

    private static IEnumerable<DirectoryInfo> EnumerateDirectories(DirectoryInfo directory)
    {
        return EnumerateEntries(
            directory,
            static current => current.EnumerateDirectories().ToArray());
    }

    private static IEnumerable<FileInfo> EnumerateFiles(DirectoryInfo directory)
    {
        return EnumerateEntries(
            directory,
            static current => current.EnumerateFiles().ToArray());
    }

    private static T[] EnumerateEntries<T>(DirectoryInfo directory, Func<DirectoryInfo, T[]> enumerate)
    {
        try
        {
            return enumerate(directory);
        }
        catch (UnauthorizedAccessException)
        {
            PrepareForDeletion(directory);
            return enumerate(directory);
        }
        catch (IOException)
        {
            PrepareForDeletion(directory);
            return enumerate(directory);
        }
    }

    private static bool IsReparsePoint(FileSystemInfo entry)
    {
        return (entry.Attributes & FileAttributes.ReparsePoint) != 0;
    }

    private static void GrantCurrentUserFullControl(string path, bool isDirectory)
    {
        var currentIdentity = WindowsIdentity.GetCurrent();
        var currentUserName = currentIdentity?.Name;
        if (string.IsNullOrWhiteSpace(currentUserName))
        {
            return;
        }

        RunWindowsTool("takeown.exe", isDirectory
            ? ["/F", path, "/R", "/D", "Y"]
            : ["/F", path]);
        RunWindowsTool("icacls.exe", isDirectory
            ? [path, "/grant", $"{currentUserName}:F", "/T", "/C"]
            : [path, "/grant", $"{currentUserName}:F"]);
    }

    private static void RunWindowsTool(string fileName, IReadOnlyList<string> arguments)
    {
        var startInfo = new ProcessStartInfo
        {
            FileName = fileName,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardError = true,
            RedirectStandardOutput = true,
        };
        foreach (var argument in arguments)
        {
            startInfo.ArgumentList.Add(argument);
        }

        using var process = Process.Start(startInfo);
        process?.WaitForExit();
    }

    private sealed class MirrorCounters
    {
        public int CopiedFileCount { get; set; }
        public int SkippedFileCount { get; set; }
        public int DeletedFileCount { get; set; }
        public int CreatedDirectoryCount { get; set; }
        public int DeletedDirectoryCount { get; set; }

        public StageMirrorResult ToResult()
        {
            return new StageMirrorResult(
                CopiedFileCount,
                SkippedFileCount,
                DeletedFileCount,
                CreatedDirectoryCount,
                DeletedDirectoryCount);
        }
    }
}
