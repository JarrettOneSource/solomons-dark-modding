using System.ComponentModel;
using System.Diagnostics;
using System.Net.Http.Json;
using System.Text.Json;
using SolomonDarkModLauncher.Infrastructure;
using SolomonDarkModLauncher.Mods;

namespace SolomonDarkModLauncher.Launch;

internal sealed record LobbyPublisherConfiguration(
    string StageRootPath,
    int GameProcessId,
    string LaunchToken,
    LobbyHostOptions Host,
    IReadOnlyList<MultiplayerModDescriptor> ActiveMods);

internal sealed record SessionTeardownRequest(
    string LaunchToken,
    string RequestedBy);

internal static class LobbyDirectoryPublisher
{
    public const string InternalCommand = "__publish-lobby";

    private const string SecretEnvironmentVariable = "SDMOD_LOBBY_DIRECTORY_SECRET";
    private const string SecretHeader = "X-SDR-Lobby-Secret";
    private static readonly TimeSpan PollInterval = TimeSpan.FromMilliseconds(100);
    private static readonly TimeSpan RetryInterval = TimeSpan.FromSeconds(1);
    private static readonly TimeSpan HeartbeatInterval = TimeSpan.FromSeconds(20);
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);

    public static bool TryStart(
        string stageRootPath,
        int gameProcessId,
        string launchToken,
        LobbyHostOptions host,
        IReadOnlyList<MultiplayerModDescriptor> activeMods)
    {
        var runtimeDirectory = Path.Combine(stageRootPath, ".sdmod");
        var logPath = Path.Combine(runtimeDirectory, "lobby-directory.log");
        var configurationPath = Path.Combine(
            runtimeDirectory,
            $"lobby-publisher-{launchToken}.json");

        try
        {
            Directory.CreateDirectory(runtimeDirectory);
            var configuration = new LobbyPublisherConfiguration(
                stageRootPath,
                gameProcessId,
                launchToken,
                host,
                activeMods);
            File.WriteAllText(
                configurationPath,
                JsonSerializer.Serialize(configuration, JsonOptions));

            var startInfo = new ProcessStartInfo(ResolveLauncherExecutable())
            {
                UseShellExecute = false,
                CreateNoWindow = true,
                WorkingDirectory = AppContext.BaseDirectory
            };
            startInfo.ArgumentList.Add(InternalCommand);
            startInfo.ArgumentList.Add(configurationPath);
            startInfo.Environment[SecretEnvironmentVariable] = LobbyDirectorySecret.Create();
            if (Process.Start(startInfo) is null)
            {
                throw new InvalidOperationException(
                    "The lobby directory publisher process did not start.");
            }

            return true;
        }
        catch (Exception ex) when (ex is IOException or
                                   UnauthorizedAccessException or
                                   InvalidOperationException or
                                   Win32Exception)
        {
            TryDelete(configurationPath);
            AppendLog(
                logPath,
                $"Directory publisher did not start: {ex.Message} " +
                "The Steam lobby remains available through direct invites and its lobby ID.");
            return false;
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
                ?? throw new InvalidOperationException(
                    "Lobby publisher configuration is empty.");
        }
        finally
        {
            TryDelete(configurationPath);
        }

        var expectedPath = Path.GetFullPath(Path.Combine(
            configuration.StageRootPath,
            ".sdmod",
            $"lobby-publisher-{configuration.LaunchToken}.json"));
        if (configuration.GameProcessId <= 0 ||
            !string.Equals(
                configurationPath,
                expectedPath,
                StringComparison.OrdinalIgnoreCase))
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
            BaseAddress = new Uri(
                configuration.Host.DirectoryBaseUrl.TrimEnd('/') + "/"),
            Timeout = TimeSpan.FromSeconds(5)
        };

        ulong announcedLobbyId = 0;
        string? lastAttemptedFingerprint = null;
        var teardownRequested = false;
        var nextDelistAttemptUtc = DateTime.MinValue;
        var nextHeartbeatUtc = DateTime.MinValue;
        try
        {
            using var gameProcess = Process.GetProcessById(configuration.GameProcessId);
            while (!gameProcess.HasExited)
            {
                teardownRequested = teardownRequested ||
                    HasValidTeardownRequest(configuration);
                if (teardownRequested &&
                    DateTime.UtcNow >= nextDelistAttemptUtc)
                {
                    nextDelistAttemptUtc =
                        DateTime.UtcNow + TimeSpan.FromMilliseconds(250);
                    if (announcedLobbyId == 0 ||
                        await TryDelistAsync(
                            client,
                            secret!,
                            announcedLobbyId))
                    {
                        WriteTeardownCompletion(
                            configuration,
                            announcedLobbyId,
                            delisted: true,
                            error: null);
                        announcedLobbyId = 0;
                        AppendLog(
                            logPath,
                            "Canonical session teardown stopped heartbeats and delisted the website lobby.");
                        return 0;
                    }
                    AppendLog(
                        logPath,
                        "Canonical session teardown could not delist the website lobby yet; retrying.");
                }

                var status = MultiplayerSessionStatusMonitor.TryRead(
                    configuration.StageRootPath,
                    configuration.LaunchToken);
                if (!teardownRequested &&
                    IsPublishableHostStatus(configuration.Host, status))
                {
                    var fingerprint = BuildStatusFingerprint(status!);
                    if (string.Equals(
                            fingerprint,
                            lastAttemptedFingerprint,
                            StringComparison.Ordinal) &&
                        DateTime.UtcNow < nextHeartbeatUtc)
                    {
                        await Task.Delay(PollInterval);
                        continue;
                    }
                    lastAttemptedFingerprint = fingerprint;
                    var result = await AnnounceAsync(
                        client,
                        secret!,
                        status!,
                        configuration.ActiveMods);
                    if (result is null)
                    {
                        nextHeartbeatUtc = DateTime.UtcNow + RetryInterval;
                        AppendLog(
                            logPath,
                            "Directory update failed. The Steam lobby remains active.");
                    }
                    else
                    {
                        if (announcedLobbyId == 0)
                        {
                            AppendLog(
                                logPath,
                                $"Published Steam lobby when the host game launched; " +
                                $"status={StatusTextForGamePhase(status!.GamePhase)}; " +
                                $"directory TTL={result.ExpiresInSeconds}s.");
                        }
                        announcedLobbyId = status!.LobbyId;
                        nextHeartbeatUtc =
                            DateTime.UtcNow + HeartbeatInterval;
                    }
                }

                await Task.Delay(PollInterval);
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
                var delisted = await TryDelistAsync(
                    client,
                    secret!,
                    announcedLobbyId);
                if (teardownRequested)
                {
                    WriteTeardownCompletion(
                        configuration,
                        announcedLobbyId,
                        delisted,
                        delisted
                            ? null
                            : "The website did not acknowledge the lobby delist.");
                }
            }
        }

        return 0;
    }

    internal static bool IsPublishableHostStatus(
        LobbyHostOptions host,
        MultiplayerSessionStatus? status)
    {
        if (status is not
            {
                IsHost: true,
                LobbyId: not 0,
                LocalSteamId: not 0,
                ProtocolVersion: > 0
            } ||
            status.Phase is not ("LobbyReady" or "Connected") ||
            status.SessionState is not (
                "not-in-game" or "in-hub" or "in-boneyard") ||
            status.GamePhase is not (
                "picking-loadout" or "hub" or "loading" or "session" or "results"))
        {
            return false;
        }

        return string.Equals(
            status.Privacy,
            MultiplayerLobbyPrivacyTokens.ToApiToken(host.Privacy),
            StringComparison.Ordinal);
    }

    internal static string BuildStatusFingerprint(
        MultiplayerSessionStatus status) =>
        string.Join(
            '|',
            status.LobbyId,
            status.LocalSteamId,
            status.GamePhase,
            status.SessionState,
            status.AuthenticatedPeerCount,
            status.MaxParticipants,
            status.Members.Length,
            status.StatusText);

    internal static string StatusTextForGamePhase(string gamePhase) =>
        gamePhase switch
        {
            "picking-loadout" => "Picking Loadout",
            "hub" => "In Hub",
            "loading" => "Loading",
            "session" => "In Match",
            "results" => "Results",
            _ => "Starting"
        };

    private static async Task<AnnounceResponse?> AnnounceAsync(
        HttpClient client,
        string secret,
        MultiplayerSessionStatus status,
        IReadOnlyList<MultiplayerModDescriptor> activeMods)
    {
        var memberCount = status.Members.Length > 0
            ? status.Members.Length
            : checked((int)status.AuthenticatedPeerCount + 1);
        var requestBody = new AnnounceRequest(
            status.LobbyId.ToString(),
            status.LocalSteamId.ToString(),
            string.IsNullOrWhiteSpace(status.PersonaName)
                ? "Steam host"
                : status.PersonaName,
            status.Privacy,
            status.FriendSteamIds
                .Where(steamId => steamId != 0 && steamId != status.LocalSteamId)
                .Distinct()
                .Select(steamId => steamId.ToString())
                .ToArray(),
            Math.Clamp(memberCount, 1, checked((int)status.MaxParticipants)),
            checked((int)status.MaxParticipants),
            new BuildDescriptor(
                status.AppId,
                status.ProtocolVersion,
                status.ManifestSha256,
                GetLauncherVersion()),
            new GameDescriptor(
                status.GamePhase,
                BoneyardId: null,
                BoneyardName: null,
                BoneyardSha256: null,
                Wave: null,
                Difficulty: null,
                ElapsedSeconds: null,
                StatusText: StatusTextForGamePhase(status.GamePhase)),
            activeMods);

        try
        {
            using var request = new HttpRequestMessage(
                HttpMethod.Post,
                "api/lobbies/announce")
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

    private static async Task<bool> TryDelistAsync(
        HttpClient client,
        string secret,
        ulong lobbyId)
    {
        try
        {
            using var request = new HttpRequestMessage(
                HttpMethod.Delete,
                $"api/lobbies/{lobbyId}");
            request.Headers.Add(SecretHeader, secret);
            using var response = await client.SendAsync(request);
            return response.IsSuccessStatusCode ||
                response.StatusCode == System.Net.HttpStatusCode.NotFound;
        }
        catch (HttpRequestException)
        {
            return false;
        }
        catch (TaskCanceledException)
        {
            return false;
        }
    }

    private static bool HasValidTeardownRequest(
        LobbyPublisherConfiguration configuration)
    {
        var requestPath = GetTeardownSignalPath(
            configuration,
            ".request.json");
        try
        {
            if (!File.Exists(requestPath))
            {
                return false;
            }
            var request = JsonSerializer.Deserialize<SessionTeardownRequest>(
                File.ReadAllText(requestPath),
                JsonOptions);
            return request is not null &&
                string.Equals(
                    request.LaunchToken,
                    configuration.LaunchToken,
                    StringComparison.Ordinal) &&
                string.Equals(
                    request.RequestedBy,
                    "loader",
                    StringComparison.Ordinal);
        }
        catch (IOException)
        {
            return false;
        }
        catch (UnauthorizedAccessException)
        {
            return false;
        }
        catch (JsonException)
        {
            return false;
        }
    }

    private static void WriteTeardownCompletion(
        LobbyPublisherConfiguration configuration,
        ulong lobbyId,
        bool delisted,
        string? error)
    {
        var completionPath = GetTeardownSignalPath(
            configuration,
            ".complete.json");
        var temporaryPath = GetTeardownSignalPath(
            configuration,
            ".complete.tmp");
        var requestPath = GetTeardownSignalPath(
            configuration,
            ".request.json");
        try
        {
            File.WriteAllText(
                temporaryPath,
                JsonSerializer.Serialize(
                    new
                    {
                        launchToken = configuration.LaunchToken,
                        lobbyId,
                        delisted,
                        error
                    },
                    JsonOptions));
            File.Move(
                temporaryPath,
                completionPath,
                overwrite: true);
            TryDelete(requestPath);
        }
        catch (IOException)
        {
            TryDelete(temporaryPath);
        }
        catch (UnauthorizedAccessException)
        {
            TryDelete(temporaryPath);
        }
    }

    private static string GetTeardownSignalPath(
        LobbyPublisherConfiguration configuration,
        string suffix) =>
        Path.Combine(
            configuration.StageRootPath,
            ".sdmod",
            $"session-teardown-{configuration.LaunchToken}{suffix}");

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
                ?? throw new InvalidOperationException(
                    "Could not resolve the launcher executable.");
    }

    private static bool IsPublisherConfigurationPath(string path)
    {
        var directory = Path.GetDirectoryName(path);
        var fileName = Path.GetFileName(path);
        const string prefix = "lobby-publisher-";
        const string suffix = ".json";
        if (directory is null ||
            !string.Equals(
                Path.GetFileName(directory),
                ".sdmod",
                StringComparison.Ordinal) ||
            !fileName.StartsWith(prefix, StringComparison.Ordinal) ||
            !fileName.EndsWith(suffix, StringComparison.Ordinal))
        {
            return false;
        }

        var token = fileName[prefix.Length..^suffix.Length];
        return token.Length == 32 && token.All(character =>
            character is >= '0' and <= '9' or >= 'a' and <= 'f');
    }

    private static string GetLauncherVersion() => LauncherVersionInfo.Informational;

    private static void AppendLog(string path, string message)
    {
        try
        {
            File.AppendAllText(
                path,
                $"{DateTime.UtcNow:O} {message}{Environment.NewLine}");
        }
        catch (IOException)
        {
        }
        catch (UnauthorizedAccessException)
        {
        }
    }

    private static void TryDelete(string path)
    {
        try
        {
            File.Delete(path);
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
        string[] FriendSteamIds,
        int Players,
        int MaxPlayers,
        BuildDescriptor Build,
        GameDescriptor Game,
        IReadOnlyList<MultiplayerModDescriptor> Mods);

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
