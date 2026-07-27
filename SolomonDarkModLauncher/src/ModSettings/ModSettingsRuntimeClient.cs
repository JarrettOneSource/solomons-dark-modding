using System.IO.Pipes;
using System.Text;
using System.Text.Json;

namespace SolomonDarkModLauncher.ModSettings;

public sealed record ModSettingsRuntimeResult
{
    public bool Ok { get; init; }
    public IReadOnlyList<string> Changed { get; init; } =
        Array.Empty<string>();
    public string Error { get; init; } = string.Empty;
}

public interface IModSettingsRuntimeClient
{
    Task<ModSettingsRuntimeResult> ReloadAsync(
        string pipeName,
        string modId,
        CancellationToken cancellationToken = default);
    Task<ModSettingsRuntimeResult> InvokeActionAsync(
        string pipeName,
        string modId,
        string entryKey,
        CancellationToken cancellationToken = default);
}

public sealed class ModSettingsRuntimeClient :
    IModSettingsRuntimeClient
{
    private const int MaximumResponseBytes = 1024 * 1024;
    private static readonly TimeSpan ConnectTimeout =
        TimeSpan.FromSeconds(5);
    private static readonly TimeSpan RequestTimeout =
        TimeSpan.FromSeconds(35);

    public async Task<ModSettingsRuntimeResult> ReloadAsync(
        string pipeName,
        string modId,
        CancellationToken cancellationToken = default)
    {
        ValidateModId(modId);
        var literal = EscapeLuaAscii(modId);
        var code =
            $"local r=sd.__settings_reload(\"{literal}\");" +
            "return r.ok and \"1\" or \"0\"," +
            "table.concat(r.changed or {},string.char(31))," +
            "r.error or \"\"";
        var response = await ExecuteAsync(
            pipeName,
            code,
            cancellationToken);
        if (!response.TransportOk)
        {
            return new ModSettingsRuntimeResult
            {
                Error = response.Error
            };
        }
        if (response.Results.Count < 3)
        {
            return new ModSettingsRuntimeResult
            {
                Error = "Loader returned an incomplete reload result."
            };
        }
        return new ModSettingsRuntimeResult
        {
            Ok = response.Results[0] == "1",
            Changed = response.Results[1].Length == 0
                ? Array.Empty<string>()
                : response.Results[1].Split(
                    '\u001f',
                    StringSplitOptions.RemoveEmptyEntries),
            Error = response.Results[2]
        };
    }

    public async Task<ModSettingsRuntimeResult> InvokeActionAsync(
        string pipeName,
        string modId,
        string entryKey,
        CancellationToken cancellationToken = default)
    {
        ValidateModId(modId);
        ValidateEntryKey(entryKey);
        var code =
            "local r=sd.__settings_invoke_action(" +
            $"\"{EscapeLuaAscii(modId)}\"," +
            $"\"{EscapeLuaAscii(entryKey)}\");" +
            "return r.ok and \"1\" or \"0\",r.error or \"\"";
        var response = await ExecuteAsync(
            pipeName,
            code,
            cancellationToken);
        if (!response.TransportOk)
        {
            return new ModSettingsRuntimeResult
            {
                Error = response.Error
            };
        }
        if (response.Results.Count < 2)
        {
            return new ModSettingsRuntimeResult
            {
                Error = "Loader returned an incomplete action result."
            };
        }
        return new ModSettingsRuntimeResult
        {
            Ok = response.Results[0] == "1",
            Error = response.Results[1]
        };
    }

    private static async Task<PipeResponse> ExecuteAsync(
        string pipeName,
        string code,
        CancellationToken cancellationToken)
    {
        var normalizedPipeName = NormalizePipeName(pipeName);
        var connected = false;
        using var requestTimeout =
            CancellationTokenSource.CreateLinkedTokenSource(
                cancellationToken);
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
                var count = await pipe.ReadAsync(
                    buffer,
                    requestTimeout.Token);
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
            return PipeResponse.Failure(
                "Loader returned an empty pipe response.");
        }
        try
        {
            using var document = JsonDocument.Parse(payload);
            var root = document.RootElement;
            var transportOk = root.GetProperty("ok").GetBoolean();
            var error = root.GetProperty("error").GetString() ??
                string.Empty;
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

    private static void ValidateModId(string modId)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(modId);
        if (modId.Length > 128 ||
            modId[0] is '.' or '_' or '-' ||
            modId[^1] is '.' or '_' or '-' ||
            modId.Any(character =>
                !((character >= 'a' && character <= 'z') ||
                  (character >= '0' && character <= '9') ||
                  character is '.' or '_' or '-')))
        {
            throw new ArgumentException(
                $"Invalid mod identifier '{modId}'.",
                nameof(modId));
        }
    }

    private static void ValidateEntryKey(string entryKey)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(entryKey);
        if (entryKey.Length > 48 ||
            entryKey.Any(character =>
                !((character >= 'a' && character <= 'z') ||
                  (character >= '0' && character <= '9') ||
                  character == '_')))
        {
            throw new ArgumentException(
                $"Invalid settings entry key '{entryKey}'.",
                nameof(entryKey));
        }
    }

    private static string EscapeLuaAscii(string value) =>
        value
            .Replace("\\", "\\\\", StringComparison.Ordinal)
            .Replace("\"", "\\\"", StringComparison.Ordinal);

    private sealed record PipeResponse(
        bool TransportOk,
        IReadOnlyList<string> Results,
        string Error)
    {
        public static PipeResponse Failure(string error) =>
            new(false, Array.Empty<string>(), error);
    }
}
