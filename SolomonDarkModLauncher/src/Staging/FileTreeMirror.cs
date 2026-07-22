using System.IO;
using System.Security.AccessControl;
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

        CopyStageFileWithAccessRecovery(
            sourceFile,
            destinationFile,
            destinationDirectoryPath,
            destinationPath);
        counters.CopiedFileCount++;
    }

    private static void CopyStageFileWithAccessRecovery(
        FileInfo sourceFile,
        FileInfo destinationFile,
        string destinationDirectoryPath,
        string destinationPath)
    {
        try
        {
            CopyStageFile(
                sourceFile,
                destinationFile,
                destinationDirectoryPath,
                destinationPath);
        }
        catch (UnauthorizedAccessException)
        {
            if (destinationFile.Exists)
            {
                PrepareForDeletion(destinationFile);
            }
            else
            {
                PrepareForDeletion(new DirectoryInfo(destinationDirectoryPath));
            }
            CopyStageFile(
                sourceFile,
                destinationFile,
                destinationDirectoryPath,
                destinationPath);
        }
    }

    private static void CopyStageFile(
        FileInfo sourceFile,
        FileInfo destinationFile,
        string destinationDirectoryPath,
        string destinationPath)
    {
        destinationFile.Refresh();
        if (destinationFile.Exists)
        {
            ClearRestrictedAttributes(destinationFile);
        }

        var tempPath = CreateTemporaryStagePath(
            destinationDirectoryPath,
            sourceFile.Name);
        try
        {
            File.Copy(sourceFile.FullName, tempPath, overwrite: false);
            ClearRestrictedAttributes(new FileInfo(tempPath));
            File.SetLastWriteTimeUtc(tempPath, sourceFile.LastWriteTimeUtc);
            File.Move(tempPath, destinationPath, overwrite: true);
        }
        finally
        {
            DeleteTemporaryStageFile(tempPath);
        }
    }

    private static bool FilesMatch(FileInfo sourceFile, FileInfo destinationFile)
    {
        sourceFile.Refresh();
        destinationFile.Refresh();
        return sourceFile.Length == destinationFile.Length &&
               sourceFile.LastWriteTimeUtc == destinationFile.LastWriteTimeUtc &&
               FilesHaveEqualContents(sourceFile, destinationFile);
    }

    private static bool FilesHaveEqualContents(
        FileInfo sourceFile,
        FileInfo destinationFile)
    {
        const int BufferSize = 128 * 1024;
        using var source = new FileStream(
            sourceFile.FullName,
            FileMode.Open,
            FileAccess.Read,
            FileShare.Read,
            BufferSize,
            FileOptions.SequentialScan);
        using var destination = new FileStream(
            destinationFile.FullName,
            FileMode.Open,
            FileAccess.Read,
            FileShare.Read,
            BufferSize,
            FileOptions.SequentialScan);
        var sourceBuffer = new byte[BufferSize];
        var destinationBuffer = new byte[BufferSize];
        var remaining = sourceFile.Length;
        while (remaining > 0)
        {
            var count = (int)Math.Min(BufferSize, remaining);
            source.ReadExactly(sourceBuffer.AsSpan(0, count));
            destination.ReadExactly(destinationBuffer.AsSpan(0, count));
            if (!sourceBuffer.AsSpan(0, count).SequenceEqual(
                    destinationBuffer.AsSpan(0, count)))
            {
                return false;
            }
            remaining -= count;
        }
        return true;
    }

    private static string CreateTemporaryStagePath(
        string destinationDirectoryPath,
        string fileName)
    {
        return Path.Combine(
            destinationDirectoryPath,
            $".{fileName}.{Guid.NewGuid():N}.sdmod.tmp");
    }

    private static void DeleteTemporaryStageFile(string tempPath)
    {
        var tempFile = new FileInfo(tempPath);
        tempFile.Refresh();
        if (!tempFile.Exists)
        {
            return;
        }
        ClearRestrictedAttributes(tempFile);
        tempFile.Delete();
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
        if (OperatingSystem.IsWindows())
        {
            GrantCurrentUserFullControl(entry.FullName, entry is DirectoryInfo);
        }
        ClearRestrictedAttributes(entry);
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
        return (entry.Attributes & FileAttributes.ReparsePoint) != 0 ||
               entry.LinkTarget is not null;
    }

    private static void GrantCurrentUserFullControl(string path, bool isDirectory)
    {
        var currentUser = WindowsIdentity.GetCurrent().User;
        if (currentUser is null)
        {
            return;
        }

        if (isDirectory)
        {
            var directory = new DirectoryInfo(path);
            var security = directory.GetAccessControl(
                AccessControlSections.Access | AccessControlSections.Owner);
            RepairAccessControl(security, currentUser, isDirectory: true);
            directory.SetAccessControl(security);
            return;
        }

        var file = new FileInfo(path);
        var fileSecurity = file.GetAccessControl(
            AccessControlSections.Access | AccessControlSections.Owner);
        RepairAccessControl(fileSecurity, currentUser, isDirectory: false);
        file.SetAccessControl(fileSecurity);
    }

    private static void RepairAccessControl(
        FileSystemSecurity security,
        SecurityIdentifier currentUser,
        bool isDirectory)
    {
        security.SetOwner(currentUser);
        var explicitRules = security.GetAccessRules(
            includeExplicit: true,
            includeInherited: false,
            typeof(SecurityIdentifier));
        foreach (FileSystemAccessRule rule in explicitRules)
        {
            if (rule.AccessControlType == AccessControlType.Deny &&
                rule.IdentityReference.Equals(currentUser))
            {
                security.RemoveAccessRuleSpecific(rule);
            }
        }

        var inheritanceFlags = isDirectory
            ? InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit
            : InheritanceFlags.None;
        security.AddAccessRule(new FileSystemAccessRule(
            currentUser,
            FileSystemRights.FullControl,
            inheritanceFlags,
            PropagationFlags.None,
            AccessControlType.Allow));
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
