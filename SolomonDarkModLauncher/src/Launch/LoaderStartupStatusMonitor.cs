using System.Text.Json;

namespace SolomonDarkModLauncher.Launch;

internal sealed record LoaderStartupStatus(
    bool Completed,
    bool Success,
    string Code,
    string Message)
{
    public string? LaunchToken { get; init; }
    public string? LogPath { get; init; }
    public string? RuntimeFlagsPath { get; init; }
    public string? RuntimeBootstrapPath { get; init; }
    public string? BinaryLayoutPath { get; init; }
    public bool BinaryLayoutLoaded { get; init; }
    public bool SteamTransportReady { get; init; }
    public bool MultiplayerFoundationReady { get; init; }
    public bool LuaEngineEnabled { get; init; }
    public bool LuaEngineInitialized { get; init; }
    public bool NativeModsEnabled { get; init; }
    public int NativeModCount { get; init; }
    public bool RuntimeTickServiceEnabled { get; init; }
    public bool RuntimeTickServiceRunning { get; init; }
}

internal static class LoaderStartupStatusMonitor
{
    private const string StartupStatusFileName = "startup-status.json";
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true
    };

    public static void Reset(string stageRootPath)
    {
        var statusPath = GetStatusPath(stageRootPath);
        if (!File.Exists(statusPath))
        {
            return;
        }

        File.Delete(statusPath);
    }

    public static LoaderStartupStatus WaitForCompletion(
        string stageRootPath,
        string expectedLaunchToken,
        int timeoutSeconds = 20)
    {
        var statusPath = GetStatusPath(stageRootPath);
        var deadline = DateTime.UtcNow.AddSeconds(timeoutSeconds);
        Exception? lastReadError = null;

        while (DateTime.UtcNow < deadline)
        {
            if (File.Exists(statusPath))
            {
                try
                {
                    var rawJson = ReadAllTextShared(statusPath);
                    var status = JsonSerializer.Deserialize<LoaderStartupStatus>(rawJson, JsonOptions);
                    if (status is not null &&
                        string.Equals(status.LaunchToken, expectedLaunchToken, StringComparison.OrdinalIgnoreCase) &&
                        status.Completed)
                    {
                        return status;
                    }
                }
                catch (IOException ex)
                {
                    lastReadError = ex;
                }
                catch (UnauthorizedAccessException ex)
                {
                    lastReadError = ex;
                }
                catch (JsonException ex)
                {
                    lastReadError = ex;
                }
            }

            Thread.Sleep(50);
        }

        var message =
            $"SolomonDarkModLoader did not report startup completion within {timeoutSeconds} seconds for launch token {expectedLaunchToken}. Status file: {statusPath}";
        if (lastReadError is not null)
        {
            message += $" Last read error: {lastReadError.Message}";
        }

        throw new InvalidOperationException(message);
    }

    private static string ReadAllTextShared(string path)
    {
        using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
        using var reader = new StreamReader(stream);
        return reader.ReadToEnd();
    }

    private static string GetStatusPath(string stageRootPath)
    {
        return Path.Combine(stageRootPath, ".sdmod", StartupStatusFileName);
    }
}
