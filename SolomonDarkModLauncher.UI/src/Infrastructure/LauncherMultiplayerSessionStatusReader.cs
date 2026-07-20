using System.Text.Json;

namespace SolomonDarkModLauncher.UI.Infrastructure;

internal static class LauncherMultiplayerSessionStatusReader
{
    private const string StatusFileName = "multiplayer-session-status.json";
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true
    };

    public static async Task<LauncherCliMultiplayerSession?> ReadAsync(
        string stageRootPath,
        string expectedLaunchToken,
        CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(stageRootPath) ||
            string.IsNullOrWhiteSpace(expectedLaunchToken))
        {
            return null;
        }

        var statusPath = Path.Combine(stageRootPath, ".sdmod", StatusFileName);
        try
        {
            await using var stream = new FileStream(
                statusPath,
                FileMode.Open,
                FileAccess.Read,
                FileShare.ReadWrite | FileShare.Delete,
                bufferSize: 4096,
                FileOptions.Asynchronous | FileOptions.SequentialScan);
            var status = await JsonSerializer.DeserializeAsync<LauncherCliMultiplayerSession>(
                stream,
                JsonOptions,
                cancellationToken);
            return status is not null && string.Equals(
                status.LaunchToken,
                expectedLaunchToken,
                StringComparison.Ordinal)
                ? status
                : null;
        }
        catch (IOException)
        {
            return null;
        }
        catch (JsonException)
        {
            return null;
        }
    }
}
