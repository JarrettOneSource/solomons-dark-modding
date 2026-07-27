using System.IO.Pipes;
using System.Text;
using System.Text.Json;

namespace SolomonDarkModLauncher.UI.Infrastructure;

internal sealed record LiveSessionLeaveResult(bool Ok, string Error);

/// <summary>
/// Sends privileged live-session commands to the owned game instance over the
/// loader's Lua exec pipe — the same transport <c>ModSettingsRuntimeClient</c>
/// uses. The loader acknowledges the request before it begins teardown, so a
/// successful reply means "leave accepted", not "session already gone"; the
/// session-status monitor observes the actual state change.
/// </summary>
internal sealed class LiveSessionRuntimeClient
{
    private const int MaximumResponseBytes = 64 * 1024;
    private static readonly TimeSpan ConnectTimeout = TimeSpan.FromSeconds(5);
    private static readonly TimeSpan RequestTimeout = TimeSpan.FromSeconds(15);

    public async Task<LiveSessionLeaveResult> LeaveAsync(
        string pipeName,
        CancellationToken cancellationToken = default)
    {
        const string code =
            "local r=sd.__session_leave();" +
            "return r.ok and \"1\" or \"0\",r.error or \"\"";
        var response = await ExecuteAsync(pipeName, code, cancellationToken);
        if (!response.TransportOk)
        {
            return new LiveSessionLeaveResult(false, response.Error);
        }
        if (response.Results.Count < 2)
        {
            return new LiveSessionLeaveResult(
                false,
                "Loader returned an incomplete leave result.");
        }
        return new LiveSessionLeaveResult(
            response.Results[0] == "1",
            response.Results[1]);
    }

    private static async Task<PipeResponse> ExecuteAsync(
        string pipeName,
        string code,
        CancellationToken cancellationToken)
    {
        var normalizedPipeName = NormalizePipeName(pipeName);
        var connected = false;
        using var requestTimeout =
            CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        requestTimeout.CancelAfter(RequestTimeout);
        try
        {
            await using var pipe = new NamedPipeClientStream(
                ".",
                normalizedPipeName,
                PipeDirection.InOut,
                PipeOptions.Asynchronous | PipeOptions.WriteThrough);
            using (var connectTimeout =
                   CancellationTokenSource.CreateLinkedTokenSource(
                       requestTimeout.Token))
            {
                connectTimeout.CancelAfter(ConnectTimeout);
                await pipe.ConnectAsync(connectTimeout.Token);
            }
            connected = true;
            pipe.ReadMode = PipeTransmissionMode.Message;

            var request = Encoding.UTF8.GetBytes(code);
            await pipe.WriteAsync(request, requestTimeout.Token);
            await pipe.FlushAsync(requestTimeout.Token);

            using var response = new MemoryStream();
            var buffer = new byte[4096];
            do
            {
                var count = await pipe.ReadAsync(buffer, requestTimeout.Token);
                if (count == 0)
                {
                    break;
                }
                if (response.Length + count > MaximumResponseBytes)
                {
                    return PipeResponse.Failure(
                        "Loader response exceeded the maximum pipe payload size.");
                }
                response.Write(buffer, 0, count);
            }
            while (!pipe.IsMessageComplete);

            return ParseResponse(response.ToArray());
        }
        catch (OperationCanceledException)
            when (!cancellationToken.IsCancellationRequested)
        {
            return PipeResponse.Failure(
                connected
                    ? "Timed out waiting for the owned game instance."
                    : "Timed out connecting to the owned game instance.");
        }
        catch (Exception exception) when (
            exception is IOException or UnauthorizedAccessException)
        {
            return PipeResponse.Failure(exception.Message);
        }
    }

    private static PipeResponse ParseResponse(byte[] payload)
    {
        if (payload.Length == 0)
        {
            return PipeResponse.Failure("Loader returned an empty pipe response.");
        }
        try
        {
            using var document = JsonDocument.Parse(payload);
            var root = document.RootElement;
            var transportOk = root.GetProperty("ok").GetBoolean();
            var error = root.GetProperty("error").GetString() ?? string.Empty;
            var results = root.GetProperty("results")
                .EnumerateArray()
                .Select(value => value.GetString() ?? string.Empty)
                .ToArray();
            return transportOk
                ? new PipeResponse(true, results, error)
                : PipeResponse.Failure(error);
        }
        catch (Exception exception) when (
            exception is JsonException or InvalidOperationException or
            KeyNotFoundException)
        {
            return PipeResponse.Failure(
                $"Loader returned invalid pipe JSON: {exception.Message}");
        }
    }

    private static string NormalizePipeName(string pipeName)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(pipeName);
        const string prefix = @"\\.\pipe\";
        var normalized = pipeName.StartsWith(
            prefix,
            StringComparison.OrdinalIgnoreCase)
            ? pipeName[prefix.Length..]
            : pipeName;
        if (normalized.Length == 0 ||
            normalized.Contains('\\') ||
            normalized.Contains('/'))
        {
            throw new ArgumentException(
                "Pipe name must be a local named-pipe leaf name.",
                nameof(pipeName));
        }
        return normalized;
    }

    private sealed record PipeResponse(
        bool TransportOk,
        IReadOnlyList<string> Results,
        string Error)
    {
        public static PipeResponse Failure(string error) =>
            new(false, Array.Empty<string>(), error);
    }
}
