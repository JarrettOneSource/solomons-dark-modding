using System.Runtime.InteropServices;

namespace SolomonDarkModLauncher.UI.Infrastructure;

internal sealed record CrashReportArtifact(string SourcePath, string ArchivePath);

internal static class RuntimeDiagnosticPaths
{
    public static string LogsRoot(LauncherCliStage stage) =>
        Path.Combine(StageMetadataRoot(stage), "logs");

    public static string StartupStatus(LauncherCliStage stage) =>
        Path.Combine(StageMetadataRoot(stage), "startup-status.json");

    private static string StageMetadataRoot(LauncherCliStage stage) =>
        Path.Combine(Path.GetFullPath(stage.StageRoot), ".sdmod");
}

internal sealed record CrashReportMod(string Id, string Version);

internal sealed record CrashReportMetadata(
    Guid ClientReportId,
    string LaunchToken,
    DateTimeOffset StartedAtUtc,
    DateTimeOffset CrashedAtUtc,
    int? ExitCode,
    string LauncherVersion,
    string LoaderVersion,
    string GameVersion,
    string RuntimeProfile,
    string OperatingSystem,
    string ProcessArchitecture,
    string DotnetRuntime,
    IReadOnlyList<CrashReportMod> EnabledMods,
    bool HasCrashLog,
    int MinidumpCount,
    IReadOnlyList<string> Artifacts);

internal sealed record CrashReportCapture(
    CrashReportMetadata Metadata,
    IReadOnlyList<CrashReportArtifact> Artifacts)
{
    private static readonly TimeSpan FileTimestampTolerance = TimeSpan.FromSeconds(2);

    public string ExitCodeText => Metadata.ExitCode is { } exitCode
        ? $"0x{unchecked((uint)exitCode):X8}"
        : "unavailable";

    public static CrashReportCapture? TryCreate(
        LauncherCliResponse response,
        int? exitCode,
        string launcherVersion)
    {
        var launch = response.Launch;
        var stage = response.Stage;
        if (launch is null || stage is null ||
            launch.StartedAtUtc == default ||
            !IsLaunchToken(launch.LaunchToken))
        {
            return null;
        }

        var logsRoot = RuntimeDiagnosticPaths.LogsRoot(stage);
        var crashLogPath = Path.Combine(logsRoot, "solomondarkmodloader.crash.log");
        var crashLogIsCurrent = IsCurrentNonemptyFile(crashLogPath, launch.StartedAtUtc);
        var dumpPaths = Directory.Exists(logsRoot)
            ? Directory.EnumerateFiles(
                    logsRoot,
                    "solomondarkmodloader.crash.*.dmp",
                    SearchOption.TopDirectoryOnly)
                .Where(path => IsCurrentNonemptyFile(path, launch.StartedAtUtc))
                .OrderBy(path => path, StringComparer.OrdinalIgnoreCase)
                .ToArray()
            : [];

        if (exitCode is not { } code || code == 0)
        {
            if (!crashLogIsCurrent && dumpPaths.Length == 0)
            {
                return null;
            }
        }

        var artifacts = new List<CrashReportArtifact>();
        if (crashLogIsCurrent)
        {
            AddArtifact(artifacts, crashLogPath, "logs/crash.log");
        }
        foreach (var dumpPath in dumpPaths)
        {
            AddArtifact(
                artifacts,
                dumpPath,
                $"dumps/{Path.GetFileName(dumpPath)}");
        }

        AddArtifact(
            artifacts,
            Path.Combine(logsRoot, "solomondarkmodloader.log"),
            "logs/loader.log");
        AddArtifact(artifacts, stage.StageReportPath, "diagnostics/stage-report.json");
        AddArtifact(
            artifacts,
            RuntimeDiagnosticPaths.StartupStatus(stage),
            "diagnostics/startup-status.json");
        AddArtifact(
            artifacts,
            Path.Combine(stage.StageRoot, ".sdmod", "multiplayer-session-status.json"),
            "diagnostics/multiplayer-session-status.json");
        AddArtifact(
            artifacts,
            Path.Combine(stage.StageRoot, ".sdmod", "lobby-directory.log"),
            "diagnostics/lobby-directory.log");
        AddArtifact(
            artifacts,
            stage.StageRuntimeBootstrapPath,
            "configuration/runtime-bootstrap.json");
        AddArtifact(
            artifacts,
            stage.StageRuntimeFlagsPath,
            "configuration/runtime-flags.ini");
        AddArtifact(
            artifacts,
            stage.StageBinaryLayoutPath,
            "configuration/binary-layout.ini");
        AddArtifact(
            artifacts,
            stage.StageDebugUiConfigPath,
            "configuration/debug-ui.ini");

        var enabledMods = response.Mods
            .Where(mod => mod.Enabled)
            .OrderBy(mod => mod.Id, StringComparer.OrdinalIgnoreCase)
            .Select(mod => new CrashReportMod(mod.Id, mod.Version))
            .ToArray();
        var metadata = new CrashReportMetadata(
            Guid.NewGuid(),
            launch.LaunchToken,
            launch.StartedAtUtc,
            DateTimeOffset.UtcNow,
            exitCode,
            launcherVersion,
            launcherVersion,
            "0.72.5",
            response.Configuration?.RuntimeProfile ?? "unknown",
            RuntimeInformation.OSDescription,
            RuntimeInformation.ProcessArchitecture.ToString(),
            RuntimeInformation.FrameworkDescription,
            enabledMods,
            crashLogIsCurrent,
            dumpPaths.Length,
            artifacts.Select(artifact => artifact.ArchivePath).ToArray());
        return new CrashReportCapture(metadata, artifacts);
    }

    private static bool IsCurrentNonemptyFile(string path, DateTimeOffset startedAtUtc)
    {
        if (!File.Exists(path))
        {
            return false;
        }

        var info = new FileInfo(path);
        return info.Length > 0 &&
               info.LastWriteTimeUtc >= startedAtUtc.UtcDateTime - FileTimestampTolerance;
    }

    private static void AddArtifact(
        ICollection<CrashReportArtifact> artifacts,
        string? sourcePath,
        string archivePath)
    {
        if (string.IsNullOrWhiteSpace(sourcePath) || !File.Exists(sourcePath))
        {
            return;
        }

        artifacts.Add(new CrashReportArtifact(Path.GetFullPath(sourcePath), archivePath));
    }

    private static bool IsLaunchToken(string value) =>
        value.Length == 32 && value.All(character =>
            character is >= '0' and <= '9' or >= 'a' and <= 'f');
}
