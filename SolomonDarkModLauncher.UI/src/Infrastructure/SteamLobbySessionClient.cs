using System.Diagnostics;
using System.Text.Json;

namespace SolomonDarkModLauncher.UI.Infrastructure;

internal sealed record SteamLobbySessionNotification(
    string Kind,
    ulong? LobbyId,
    ulong? HostSteamId,
    ulong? LocalSteamId,
    string Privacy,
    int MaxParticipants,
    IReadOnlyList<LauncherCliLobbyMember> Members,
    string Error);

internal sealed class SteamLobbySessionClient : IDisposable
{
    private const string EventPrefix = "SDMOD_STEAM_LOBBY ";
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true
    };

    private readonly object gate_ = new();
    private Process? process_;
    private bool disposed_;

    public event EventHandler<SteamLobbySessionNotification>? NotificationReceived;

    public void Join(ulong lobbyId)
    {
        if (lobbyId == 0)
        {
            throw new ArgumentOutOfRangeException(nameof(lobbyId));
        }

        Leave();
        lock (gate_)
        {
            ObjectDisposedException.ThrowIf(disposed_, this);
            var startInfo = new ProcessStartInfo(LauncherExecutableResolver.Resolve())
            {
                UseShellExecute = false,
                RedirectStandardInput = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true
            };
            SteamShortcutChildEnvironment.RemoveFrom(startInfo);
            startInfo.ArgumentList.Add("__join-steam-lobby");
            startInfo.ArgumentList.Add(Environment.ProcessId.ToString());
            startInfo.ArgumentList.Add(lobbyId.ToString());

            var process = new Process { StartInfo = startInfo };
            process.Start();
            process_ = process;
            _ = ReadOutputAsync(process, lobbyId);
            _ = process.StandardError.ReadToEndAsync();
        }
    }

    public void Leave()
    {
        Process? process;
        lock (gate_)
        {
            process = process_;
            process_ = null;
        }

        if (process is null)
        {
            return;
        }

        try
        {
            if (!process.HasExited)
            {
                process.StandardInput.WriteLine("leave");
                process.StandardInput.Flush();
                if (!process.WaitForExit(2000))
                {
                    process.Kill(entireProcessTree: false);
                    process.WaitForExit(2000);
                }
            }
        }
        catch (InvalidOperationException)
        {
        }
        catch (IOException)
        {
        }
        finally
        {
            process.Dispose();
        }
    }

    public void Dispose()
    {
        lock (gate_)
        {
            disposed_ = true;
        }
        Leave();
    }

    private async Task ReadOutputAsync(Process process, ulong lobbyId)
    {
        var terminalEventReceived = false;
        try
        {
            while (await process.StandardOutput.ReadLineAsync() is { } line)
            {
                if (!line.StartsWith(EventPrefix, StringComparison.Ordinal))
                {
                    continue;
                }

                var payload = JsonSerializer.Deserialize<SteamLobbyPayload>(
                    line[EventPrefix.Length..],
                    JsonOptions);
                if (payload is null || string.IsNullOrWhiteSpace(payload.Kind))
                {
                    continue;
                }

                terminalEventReceived = payload.Kind is
                    "error" or "disconnected" or "hostDeparted";
                NotificationReceived?.Invoke(
                    this,
                    new SteamLobbySessionNotification(
                        payload.Kind,
                        ParseSteamId(payload.LobbyId),
                        ParseSteamId(payload.HostSteamId),
                        ParseSteamId(payload.LocalSteamId),
                        payload.Privacy ?? string.Empty,
                        payload.MaxParticipants,
                        payload.Members.Select(member =>
                            new LauncherCliLobbyMember
                            {
                                SteamId = ParseSteamId(member.SteamId) ?? 0,
                                Name = member.Name ?? string.Empty,
                                IsHost = member.IsHost,
                                IsLocal = member.IsLocal
                            }).ToArray(),
                        payload.Error ?? string.Empty));
            }
        }
        catch (InvalidOperationException)
        {
        }
        catch (JsonException exception)
        {
            terminalEventReceived = true;
            NotificationReceived?.Invoke(
                this,
                new SteamLobbySessionNotification(
                    "error",
                    lobbyId,
                    null,
                    null,
                    string.Empty,
                    0,
                    [],
                    $"Steam returned an invalid lobby update: {exception.Message}"));
        }
        finally
        {
            var unexpectedExit = false;
            var shouldDisposeProcess = false;
            lock (gate_)
            {
                if (ReferenceEquals(process_, process))
                {
                    process_ = null;
                    unexpectedExit = !disposed_ && !terminalEventReceived;
                    shouldDisposeProcess = true;
                }
            }

            if (unexpectedExit)
            {
                NotificationReceived?.Invoke(
                    this,
                    new SteamLobbySessionNotification(
                        "disconnected",
                        lobbyId,
                        null,
                        null,
                        string.Empty,
                        0,
                        [],
                        "The Steam lobby connection closed before launch."));
            }

            if (shouldDisposeProcess)
            {
                process.Dispose();
            }
        }
    }

    private static ulong? ParseSteamId(string? value) =>
        ulong.TryParse(value, out var parsed) && parsed != 0 ? parsed : null;

    private sealed class SteamLobbyPayload
    {
        public string Kind { get; set; } = string.Empty;
        public string? LobbyId { get; set; }
        public string? HostSteamId { get; set; }
        public string? LocalSteamId { get; set; }
        public string? Privacy { get; set; }
        public int MaxParticipants { get; set; }
        public List<SteamLobbyMemberPayload> Members { get; set; } = [];
        public string? Error { get; set; }
    }

    private sealed class SteamLobbyMemberPayload
    {
        public string? SteamId { get; set; }
        public string? Name { get; set; }
        public bool IsHost { get; set; }
        public bool IsLocal { get; set; }
    }
}
