using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using Microsoft.Win32;
using SolomonDarkModding.IO;

namespace SolomonDarkModLauncher.UI.Infrastructure;

internal static class LauncherShell
{
    public static bool TrySelectFolder(
        string title,
        string? preferredPath,
        string? contextualFallback,
        out string selectedPath)
    {
        selectedPath = string.Empty;
        var initialDirectory = ResolveDialogInitialDirectory(
            preferredPath,
            contextualFallback);
        if (initialDirectory is null)
        {
            LauncherLog.Write(
                "shell",
                "Folder picker was skipped because no readable non-shell default was available.");
            return false;
        }

        var dialog = new OpenFolderDialog
        {
            Title = title,
            Multiselect = false,
            InitialDirectory = initialDirectory,
            DefaultDirectory = initialDirectory,
            AddToRecent = false,
            DereferenceLinks = false
        };

        bool? result;
        try
        {
            result = dialog.ShowDialog();
        }
        catch (Exception exception) when (IsShellAccessFailure(exception))
        {
            LauncherLog.Write(
                "shell",
                $"Folder picker access failed and was dismissed: " +
                $"{exception.GetType().Name}: {exception.Message}");
            return false;
        }

        if (result != true)
        {
            return false;
        }

        var readableSelection = LauncherPathPolicy.ResolveReadableDirectory(
            [dialog.FolderName],
            LogRejectedPath);
        if (readableSelection is null)
        {
            return false;
        }

        selectedPath = readableSelection;
        return true;
    }

    internal static string? ResolveDialogInitialDirectory(
        string? preferredPath,
        string? contextualFallback,
        Func<string, bool>? canReadDirectory = null,
        Action<string>? rejectedPath = null)
    {
        rejectedPath ??= LogRejectedPath;
        return LauncherPathPolicy.ResolveReadableDirectory(
            [
                preferredPath,
                contextualFallback,
                LauncherPathPolicy.TryGetKnownFolder(
                    Environment.SpecialFolder.MyDocuments,
                    rejectedPath),
                LauncherPathPolicy.TryGetKnownFolder(
                    Environment.SpecialFolder.LocalApplicationData,
                    rejectedPath),
                AppContext.BaseDirectory
            ],
            rejectedPath,
            canReadDirectory);
    }

    public static bool TryOpenFolder(
        string? requestedPath,
        string? contextualFallback = null)
    {
        var path = ResolveDialogInitialDirectory(
            requestedPath,
            contextualFallback);
        if (path is null)
        {
            LauncherLog.Write(
                "shell",
                "Folder open was skipped because no readable fallback was available.");
            return false;
        }

        var startInfo = new ProcessStartInfo("explorer.exe")
        {
            WorkingDirectory = path,
            UseShellExecute = false,
            CreateNoWindow = true
        };
        startInfo.ArgumentList.Add(path);
        return TryStart(startInfo, $"folder {path}");
    }

    public static bool TryOpenUri(string value)
    {
        if (!Uri.TryCreate(value, UriKind.Absolute, out var uri) ||
            !string.Equals(
                uri.Scheme,
                Uri.UriSchemeHttp,
                StringComparison.OrdinalIgnoreCase) &&
            !string.Equals(
                uri.Scheme,
                Uri.UriSchemeHttps,
                StringComparison.OrdinalIgnoreCase))
        {
            LauncherLog.Write("shell", $"URI open was rejected: {value}");
            return false;
        }

        var workingDirectory = ResolveDialogInitialDirectory(
            preferredPath: null,
            contextualFallback: AppContext.BaseDirectory);
        if (workingDirectory is null)
        {
            LauncherLog.Write(
                "shell",
                "URI open was skipped because no readable working directory was available.");
            return false;
        }

        var startInfo = new ProcessStartInfo(uri.AbsoluteUri)
        {
            WorkingDirectory = workingDirectory,
            UseShellExecute = true,
            ErrorDialog = false
        };
        return TryStart(startInfo, $"URI {uri.GetLeftPart(UriPartial.Authority)}");
    }

    public static bool TryOpenTextFile(string path)
    {
        var fullPath = LauncherPathPolicy.NormalizeAbsolutePath(path);
        var directory = fullPath is null
            ? null
            : Path.GetDirectoryName(fullPath);
        var readableDirectory = LauncherPathPolicy.ResolveReadableDirectory(
            [directory],
            LogRejectedPath);
        if (fullPath is null ||
            readableDirectory is null ||
            !File.Exists(fullPath))
        {
            LauncherLog.Write(
                "shell",
                $"Text-file open was skipped because the file is unavailable: {path}");
            return false;
        }

        var startInfo = new ProcessStartInfo("notepad.exe")
        {
            WorkingDirectory = readableDirectory,
            UseShellExecute = false
        };
        startInfo.ArgumentList.Add(fullPath!);
        return TryStart(startInfo, $"text file {fullPath}");
    }

    public static void UseSafeCurrentDirectory()
    {
        var workingDirectory = ResolveDialogInitialDirectory(
            preferredPath: null,
            contextualFallback: AppContext.BaseDirectory);
        if (workingDirectory is null)
        {
            LauncherLog.Write(
                "shell",
                "The launcher working directory could not be moved to a safe path.");
            return;
        }

        try
        {
            Environment.CurrentDirectory = workingDirectory;
        }
        catch (Exception exception) when (
            exception is IOException or
            UnauthorizedAccessException or
            System.Security.SecurityException)
        {
            LauncherLog.Write(
                "shell",
                $"Could not set the launcher working directory: " +
                $"{exception.GetType().Name}: {exception.Message}");
        }
    }

    private static bool TryStart(
        ProcessStartInfo startInfo,
        string description)
    {
        try
        {
            if (Process.Start(startInfo) is not null)
            {
                return true;
            }

            LauncherLog.Write(
                "shell",
                $"Windows did not start {description}.");
        }
        catch (Exception exception) when (IsShellAccessFailure(exception))
        {
            LauncherLog.Write(
                "shell",
                $"Could not open {description}: " +
                $"{exception.GetType().Name}: {exception.Message}");
        }

        return false;
    }

    private static void LogRejectedPath(string message) =>
        LauncherLog.Write("shell", message);

    private static bool IsShellAccessFailure(Exception exception) =>
        exception is IOException or
        UnauthorizedAccessException or
        InvalidOperationException or
        Win32Exception or
        COMException or
        System.Security.SecurityException;
}
