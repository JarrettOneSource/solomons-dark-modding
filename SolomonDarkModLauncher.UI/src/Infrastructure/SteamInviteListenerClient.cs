using System.Diagnostics;
using System.Text.Json;

namespace SolomonDarkModLauncher.UI.Infrastructure;

internal sealed record SteamInviteNotification(
    string Kind,
    ulong? LobbyId,
    ulong? FriendSteamId,
    string FriendName,
    string Error);

internal sealed class SteamInviteListenerClient : IDisposable
{
    private const string EventPrefix = "SDMOD_STEAM_INVITE ";
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true
    };

    private readonly object gate_ = new();
    private Process? process_;
    private bool disposed_;

    public event EventHandler<SteamInviteNotification>? NotificationReceived;

    public void Start()
    {
        lock (gate_)
        {
            if (disposed_ || process_ is { HasExited: false })
            {
                return;
            }

            process_?.Dispose();
            var startInfo = new ProcessStartInfo(LauncherExecutableResolver.Resolve())
            {
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true
            };
            SteamShortcutChildEnvironment.RemoveFrom(startInfo);
            startInfo.ArgumentList.Add("__listen-steam-invites");
            startInfo.ArgumentList.Add(Environment.ProcessId.ToString());

            var process = new Process
            {
                StartInfo = startInfo,
                EnableRaisingEvents = true
            };
            process.Start();
            process_ = process;
            _ = ReadOutputAsync(process);
            _ = process.StandardError.ReadToEndAsync();
        }
    }

    public void Stop()
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
                process.Kill(entireProcessTree: false);
                process.WaitForExit(2000);
            }
        }
        catch (InvalidOperationException)
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
        Stop();
    }

    private async Task ReadOutputAsync(Process process)
    {
        try
        {
            while (await process.StandardOutput.ReadLineAsync() is { } line)
            {
                if (!line.StartsWith(EventPrefix, StringComparison.Ordinal))
                {
                    continue;
                }

                var payload = JsonSerializer.Deserialize<SteamInvitePayload>(
                    line[EventPrefix.Length..],
                    JsonOptions);
                if (payload is null || string.IsNullOrWhiteSpace(payload.Kind))
                {
                    continue;
                }

                NotificationReceived?.Invoke(
                    this,
                    new SteamInviteNotification(
                        payload.Kind,
                        ParseSteamId(payload.LobbyId),
                        ParseSteamId(payload.FriendSteamId),
                        payload.FriendName ?? string.Empty,
                        payload.Error ?? string.Empty));
            }
        }
        catch (InvalidOperationException)
        {
        }
        catch (JsonException)
        {
        }
    }

    private static ulong? ParseSteamId(string? value) =>
        ulong.TryParse(value, out var parsed) && parsed != 0 ? parsed : null;

    private sealed class SteamInvitePayload
    {
        public string Kind { get; set; } = string.Empty;
        public string? LobbyId { get; set; }
        public string? FriendSteamId { get; set; }
        public string? FriendName { get; set; }
        public string? Error { get; set; }
    }
}
