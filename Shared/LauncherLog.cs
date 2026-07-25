using System.Diagnostics;
using System.IO;
using System.Text;

namespace SolomonDarkModding.IO;

internal static class LauncherLog
{
    public static string GetPath(string applicationDataRoot) =>
        Path.Combine(
            Path.GetFullPath(applicationDataRoot, AppContext.BaseDirectory),
            "logs",
            "launcher.log");

    public static void Write(
        string component,
        string message,
        string? applicationDataRoot = null)
    {
        var line =
            $"{DateTimeOffset.UtcNow:O} [{Sanitize(component)}] {Sanitize(message)}";
        Trace.WriteLine(line);

        try
        {
            applicationDataRoot ??=
                LauncherPathPolicy.ResolveApplicationDataRoot();
            var logPath = GetPath(applicationDataRoot);
            Directory.CreateDirectory(Path.GetDirectoryName(logPath)!);
            File.AppendAllText(
                logPath,
                line + Environment.NewLine,
                new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
        }
        catch (Exception exception) when (
            exception is IOException or
            UnauthorizedAccessException or
            ArgumentException or
            NotSupportedException or
            System.Security.SecurityException)
        {
            Trace.WriteLine(
                $"{DateTimeOffset.UtcNow:O} [launcher-log] " +
                $"Could not write the launcher log: {exception.Message}");
        }
    }

    private static string Sanitize(string value) =>
        value.Replace('\r', ' ').Replace('\n', ' ');
}
