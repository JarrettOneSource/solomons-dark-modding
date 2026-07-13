using System.Diagnostics;
using System.Text.Json;

namespace SolomonDarkModLauncher.Launch;

internal sealed record MultiplayerSessionStatus(
    string LaunchToken,
    bool Enabled,
    bool IsHost,
    string Phase,
    uint AppId,
    ulong LobbyId,
    uint MaxParticipants,
    uint AuthenticatedPeerCount,
    bool OverlayEnabled,
    bool InviteDialogOpened,
    bool RouteRelayed,
    int RoutePingMs,
    string StatusText,
    string ErrorText);

internal static class MultiplayerSessionStatusMonitor
{
    private const string StatusFileName = "multiplayer-session-status.json";
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true
    };

    public static void Reset(string stageRootPath)
    {
        var statusPath = GetStatusPath(stageRootPath);
        if (File.Exists(statusPath))
        {
            File.Delete(statusPath);
        }
    }

    public static MultiplayerSessionStatus WaitForHostReady(
        string stageRootPath,
        string expectedLaunchToken,
        Process process,
        int timeoutSeconds = 20) =>
        WaitFor(
            stageRootPath,
            expectedLaunchToken,
            process,
            status =>
                status.IsHost &&
                status.LobbyId != 0 &&
                status.Phase is "LobbyReady" or "Connected",
            "a ready Steam host lobby",
            timeoutSeconds);

    public static MultiplayerSessionStatus WaitForInvite(
        string stageRootPath,
        string expectedLaunchToken,
        Process process,
        int timeoutSeconds = 20) =>
        WaitFor(
            stageRootPath,
            expectedLaunchToken,
            process,
            status =>
                !status.IsHost &&
                status.Phase == "WaitingForInvite",
            "Steam invite wait mode",
            timeoutSeconds);

    public static MultiplayerSessionStatus WaitForConnectedJoin(
        string stageRootPath,
        string expectedLaunchToken,
        Process process,
        int timeoutSeconds = 30) =>
        WaitFor(
            stageRootPath,
            expectedLaunchToken,
            process,
            status =>
                !status.IsHost &&
                status.LobbyId != 0 &&
                status.Phase == "Connected" &&
                status.AuthenticatedPeerCount > 0,
            "an authenticated Steam host connection",
            timeoutSeconds);

    private static MultiplayerSessionStatus WaitFor(
        string stageRootPath,
        string expectedLaunchToken,
        Process process,
        Func<MultiplayerSessionStatus, bool> isComplete,
        string expectedMilestone,
        int timeoutSeconds)
    {
        var statusPath = GetStatusPath(stageRootPath);
        var deadline = DateTime.UtcNow.AddSeconds(timeoutSeconds);
        Exception? lastReadError = null;
        MultiplayerSessionStatus? lastStatus = null;

        while (DateTime.UtcNow < deadline)
        {
            if (process.HasExited)
            {
                throw new InvalidOperationException(
                    $"Solomon Dark exited before reaching {expectedMilestone}. " +
                    $"Last Steam status: {Describe(lastStatus)}");
            }

            if (File.Exists(statusPath))
            {
                try
                {
                    var status = JsonSerializer.Deserialize<MultiplayerSessionStatus>(
                        ReadAllTextShared(statusPath),
                        JsonOptions);
                    if (status is not null &&
                        string.Equals(
                            status.LaunchToken,
                            expectedLaunchToken,
                            StringComparison.OrdinalIgnoreCase))
                    {
                        lastStatus = status;
                        if (status.Phase == "Error")
                        {
                            var error = string.IsNullOrWhiteSpace(status.ErrorText)
                                ? status.StatusText
                                : status.ErrorText;
                            throw new InvalidOperationException(
                                $"Steam multiplayer failed: {error}");
                        }
                        if (isComplete(status))
                        {
                            return status;
                        }
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
            $"Steam multiplayer did not reach {expectedMilestone} within " +
            $"{timeoutSeconds} seconds. Status file: {statusPath}. " +
            $"Last Steam status: {Describe(lastStatus)}";
        if (lastReadError is not null)
        {
            message += $" Last read error: {lastReadError.Message}";
        }
        throw new InvalidOperationException(message);
    }

    private static string Describe(MultiplayerSessionStatus? status) =>
        status is null
            ? "unavailable"
            : $"phase={status.Phase}, lobby={status.LobbyId}, peers={status.AuthenticatedPeerCount}, error={status.ErrorText}";

    private static string ReadAllTextShared(string path)
    {
        using var stream = new FileStream(
            path,
            FileMode.Open,
            FileAccess.Read,
            FileShare.ReadWrite | FileShare.Delete);
        using var reader = new StreamReader(stream);
        return reader.ReadToEnd();
    }

    private static string GetStatusPath(string stageRootPath) =>
        Path.Combine(stageRootPath, ".sdmod", StatusFileName);
}
