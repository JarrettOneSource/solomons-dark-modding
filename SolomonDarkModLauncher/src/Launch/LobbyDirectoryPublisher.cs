using System.Diagnostics;
using System.Net.Http.Json;
using System.Reflection;
using System.Text.Json;

namespace SolomonDarkModLauncher.Launch;

internal sealed record LobbyPublisherConfiguration(
    string StageRootPath,
    int GameProcessId,
    string LaunchToken,
    LobbyHostOptions Host);

internal static class LobbyDirectoryPublisher
{
    public const string InternalCommand = "__publish-lobby";
    private const string SecretEnvironmentVariable = "SDMOD_LOBBY_DIRECTORY_SECRET";
    private const string SecretHeader = "X-SDR-Lobby-Secret";
    private static readonly TimeSpan HeartbeatInterval = TimeSpan.FromSeconds(20);
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);

    public static void Start(
        string stageRootPath,
        int gameProcessId,
        string launchToken,
        LobbyHostOptions host,
        string secret)
    {
        var runtimeDirectory = Path.Combine(stageRootPath, ".sdmod");
        Directory.CreateDirectory(runtimeDirectory);
        var configurationPath = Path.Combine(
            runtimeDirectory,
            $"lobby-publisher-{launchToken}.json");
        var configuration = new LobbyPublisherConfiguration(
            stageRootPath,
            gameProcessId,
            launchToken,
            host);
        File.WriteAllText(configurationPath, JsonSerializer.Serialize(configuration, JsonOptions));

        try
        {
            var startInfo = new ProcessStartInfo(ResolveLauncherExecutable())
            {
                UseShellExecute = false,
                CreateNoWindow = true,
                WorkingDirectory = AppContext.BaseDirectory
            };
            startInfo.ArgumentList.Add(InternalCommand);
            startInfo.ArgumentList.Add(configurationPath);
            startInfo.Environment[SecretEnvironmentVariable] = secret;
            if (Process.Start(startInfo) is null)
            {
                throw new InvalidOperationException("Failed to start the lobby directory publisher.");
            }
        }
        catch
        {
            File.Delete(configurationPath);
            throw;
        }
    }

    public static bool TryRun(string[] args, out int exitCode)
    {
        if (args.Length == 0 || !string.Equals(
                args[0],
                InternalCommand,
                StringComparison.Ordinal))
        {
            exitCode = 0;
            return false;
        }

        exitCode = RunAsync(args).GetAwaiter().GetResult();
        return true;
    }

    private static async Task<int> RunAsync(string[] args)
    {
        if (args.Length != 2)
        {
            return 2;
        }

        var configurationPath = Path.GetFullPath(args[1]);
        if (!IsPublisherConfigurationPath(configurationPath))
        {
            return 2;
        }

        LobbyPublisherConfiguration configuration;
        try
        {
            configuration = JsonSerializer.Deserialize<LobbyPublisherConfiguration>(
                    await File.ReadAllTextAsync(configurationPath),
                    JsonOptions)
                ?? throw new InvalidOperationException("Lobby publisher configuration is empty.");
        }
        finally
        {
            File.Delete(configurationPath);
        }

        var expectedPath = Path.GetFullPath(Path.Combine(
            configuration.StageRootPath,
            ".sdmod",
            $"lobby-publisher-{configuration.LaunchToken}.json"));
        if (configuration.GameProcessId <= 0 ||
            !string.Equals(configurationPath, expectedPath, StringComparison.OrdinalIgnoreCase))
        {
            return 2;
        }

        var secret = Environment.GetEnvironmentVariable(SecretEnvironmentVariable);
        Environment.SetEnvironmentVariable(SecretEnvironmentVariable, null);
        if (!LobbyDirectorySecret.IsValid(secret))
        {
            return 2;
        }

        var logPath = Path.Combine(
            configuration.StageRootPath,
            ".sdmod",
            "lobby-directory.log");
        using var client = new HttpClient
        {
            BaseAddress = new Uri(configuration.Host.DirectoryBaseUrl.TrimEnd('/') + "/"),
            Timeout = TimeSpan.FromSeconds(5)
        };

        ulong announcedLobbyId = 0;
        try
        {
            using var gameProcess = Process.GetProcessById(configuration.GameProcessId);
            while (!gameProcess.HasExited)
            {
                var status = MultiplayerSessionStatusMonitor.TryRead(
                    configuration.StageRootPath,
                    configuration.LaunchToken);
                if (status is { IsHost: true, LobbyId: not 0, LocalSteamId: not 0 } &&
                    status.Phase is "LobbyReady" or "Connected")
                {
                    var result = await AnnounceAsync(
                        client,
                        secret!,
                        configuration.Host,
                        status);
                    if (result is null)
                    {
                        AppendLog(logPath, "Directory heartbeat failed; Steam lobby remains active.");
                    }
                    else
                    {
                        if (announcedLobbyId == 0)
                        {
                            AppendLog(
                                logPath,
                                $"Published Steam lobby {status.LobbyId}; directory TTL={result.ExpiresInSeconds}s.");
                        }
                        announcedLobbyId = status.LobbyId;
                    }
                }

                await Task.Delay(HeartbeatInterval);
            }
        }
        catch (ArgumentException)
        {
            return 0;
        }
        catch (InvalidOperationException)
        {
            return 0;
        }
        finally
        {
            if (announcedLobbyId != 0)
            {
                await TryDelistAsync(client, secret!, announcedLobbyId);
            }
        }

        return 0;
    }

    private static async Task<AnnounceResponse?> AnnounceAsync(
        HttpClient client,
        string secret,
        LobbyHostOptions host,
        MultiplayerSessionStatus status)
    {
        var requestBody = new AnnounceRequest(
            status.LobbyId.ToString(),
            status.LocalSteamId.ToString(),
            string.IsNullOrWhiteSpace(status.PersonaName)
                ? $"Steam {status.LocalSteamId}"
                : status.PersonaName,
            MultiplayerLobbyPrivacyTokens.ToApiToken(host.Privacy),
            host.Password is null
                ? null
                : new PasswordDescriptor(
                    LobbyPasswordOptions.Algorithm,
                    LobbyPasswordOptions.Iterations,
                    host.Password.SaltHex,
                    host.Password.HashHex),
            status.FriendSteamIds
                .Where(steamId => steamId != 0)
                .Distinct()
                .Select(steamId => steamId.ToString())
                .ToArray(),
            checked((int)status.AuthenticatedPeerCount + 1),
            checked((int)status.MaxParticipants),
            new BuildDescriptor(
                status.AppId,
                status.ProtocolVersion,
                status.ManifestSha256,
                GetLauncherVersion()),
            new GameDescriptor(
                host.Game.Phase,
                host.Game.BoneyardId,
                host.Game.BoneyardName,
                host.Game.BoneyardSha256,
                host.Game.Wave,
                host.Game.Difficulty,
                host.Game.ElapsedSeconds,
                host.Game.StatusText));

        try
        {
            using var request = new HttpRequestMessage(HttpMethod.Post, "api/lobbies/announce")
            {
                Content = JsonContent.Create(requestBody, options: JsonOptions)
            };
            request.Headers.Add(SecretHeader, secret);
            using var response = await client.SendAsync(request);
            if (!response.IsSuccessStatusCode)
            {
                return null;
            }

            return await response.Content.ReadFromJsonAsync<AnnounceResponse>(JsonOptions);
        }
        catch (HttpRequestException)
        {
            return null;
        }
        catch (TaskCanceledException)
        {
            return null;
        }
    }

    private static async Task TryDelistAsync(HttpClient client, string secret, ulong lobbyId)
    {
        try
        {
            using var request = new HttpRequestMessage(
                HttpMethod.Delete,
                $"api/lobbies/{lobbyId}");
            request.Headers.Add(SecretHeader, secret);
            using var response = await client.SendAsync(request);
        }
        catch (HttpRequestException)
        {
        }
        catch (TaskCanceledException)
        {
        }
    }

    private static string ResolveLauncherExecutable()
    {
        var executable = Path.Combine(
            AppContext.BaseDirectory,
            OperatingSystem.IsWindows()
                ? "SolomonDarkModLauncher.exe"
                : "SolomonDarkModLauncher");
        return File.Exists(executable)
            ? executable
            : Environment.ProcessPath
                ?? throw new InvalidOperationException("Could not resolve the launcher executable.");
    }

    private static bool IsPublisherConfigurationPath(string path)
    {
        var directory = Path.GetDirectoryName(path);
        var fileName = Path.GetFileName(path);
        const string prefix = "lobby-publisher-";
        const string suffix = ".json";
        if (directory is null ||
            !string.Equals(Path.GetFileName(directory), ".sdmod", StringComparison.Ordinal) ||
            !fileName.StartsWith(prefix, StringComparison.Ordinal) ||
            !fileName.EndsWith(suffix, StringComparison.Ordinal))
        {
            return false;
        }

        var token = fileName[prefix.Length..^suffix.Length];
        return token.Length == 32 && token.All(character =>
            character is >= '0' and <= '9' or >= 'a' and <= 'f');
    }

    private static string GetLauncherVersion() =>
        typeof(LobbyDirectoryPublisher).Assembly
            .GetCustomAttribute<AssemblyInformationalVersionAttribute>()?
            .InformationalVersion ?? "unknown";

    private static void AppendLog(string path, string message)
    {
        try
        {
            File.AppendAllText(path, $"{DateTime.UtcNow:O} {message}{Environment.NewLine}");
        }
        catch (IOException)
        {
        }
        catch (UnauthorizedAccessException)
        {
        }
    }

    private sealed record AnnounceRequest(
        string LobbyId,
        string HostSteamId,
        string HostPlayer,
        string Privacy,
        PasswordDescriptor? Password,
        string[] FriendSteamIds,
        int Players,
        int MaxPlayers,
        BuildDescriptor Build,
        GameDescriptor Game);

    private sealed record PasswordDescriptor(
        string Algorithm,
        int Iterations,
        string Salt,
        string Hash);

    private sealed record BuildDescriptor(
        uint AppId,
        int ProtocolVersion,
        string ManifestSha256,
        string LoaderVersion);

    private sealed record GameDescriptor(
        string Phase,
        string? BoneyardId,
        string? BoneyardName,
        string? BoneyardSha256,
        int? Wave,
        string? Difficulty,
        int? ElapsedSeconds,
        string? StatusText);

    private sealed record AnnounceResponse(int Id, int ExpiresInSeconds);
}
