using System.Diagnostics;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using SolomonDarkModding.Updates;

namespace SolomonDarkModLauncher.UI.Infrastructure;

internal sealed record LauncherJsonReadResult(
    LauncherCliResponse? Response,
    string RawPayload,
    string Diagnostics);

internal static class LauncherJsonResponseReader
{
    private const int MaximumDiagnosticCharacters = 8192;
    private static readonly TimeSpan ResponseFlushTimeout = TimeSpan.FromSeconds(2);
    private static readonly JsonSerializerOptions ProgressJsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
        Converters =
        {
            new JsonStringEnumConverter(JsonNamingPolicy.CamelCase)
        }
    };

    public static async Task<LauncherJsonReadResult> ReadAsync(
        Process process,
        JsonSerializerOptions jsonOptions,
        CancellationToken cancellationToken,
        IProgress<UpdateProgress>? progress = null)
    {
        using var readCancellation =
            CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        var stdoutTask = ReadStreamAsync(
            process.StandardOutput,
            jsonOptions,
            readCancellation.Token,
            progress);
        var stderrTask = ReadStreamAsync(
            process.StandardError,
            jsonOptions,
            readCancellation.Token,
            progress);

        StreamReadResult? selected = null;
        try
        {
            await process.WaitForExitAsync(cancellationToken);
            selected = await WaitForResponseAsync(
                stdoutTask,
                stderrTask,
                cancellationToken);
        }
        finally
        {
            readCancellation.Cancel();
        }

        var stdout = await stdoutTask;
        var stderr = await stderrTask;
        selected ??= stdout.Response is not null
            ? stdout
            : stderr.Response is not null
                ? stderr
                : null;

        return new LauncherJsonReadResult(
            selected?.Response,
            selected?.RawPayload ?? string.Empty,
            JoinDiagnostics(stdout.Diagnostics, stderr.Diagnostics));
    }

    private static async Task<StreamReadResult?> WaitForResponseAsync(
        Task<StreamReadResult> stdoutTask,
        Task<StreamReadResult> stderrTask,
        CancellationToken cancellationToken)
    {
        var pending = new List<Task<StreamReadResult>> { stdoutTask, stderrTask };
        var timeoutTask = Task.Delay(ResponseFlushTimeout, cancellationToken);
        while (pending.Count > 0)
        {
            var candidates = pending.Cast<Task>().Append(timeoutTask).ToArray();
            var completed = await Task.WhenAny(candidates);
            if (completed == timeoutTask)
            {
                cancellationToken.ThrowIfCancellationRequested();
                return null;
            }

            var readTask = (Task<StreamReadResult>)completed;
            pending.Remove(readTask);
            var result = await readTask;
            if (result.Response is not null)
            {
                return result;
            }
        }

        return null;
    }

    private static async Task<StreamReadResult> ReadStreamAsync(
        StreamReader reader,
        JsonSerializerOptions jsonOptions,
        CancellationToken cancellationToken,
        IProgress<UpdateProgress>? progress)
    {
        var diagnostics = new StringBuilder();
        try
        {
            while (true)
            {
                var line = await reader.ReadLineAsync(cancellationToken);
                if (line is null)
                {
                    break;
                }
                if (TryParseResponse(line, jsonOptions, out var response))
                {
                    return new StreamReadResult(response, line, diagnostics.ToString());
                }
                if (TryParseUpdateProgress(line, out var updateProgress))
                {
                    progress?.Report(updateProgress!);
                    continue;
                }
                AppendDiagnostic(diagnostics, line);
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
        }

        return new StreamReadResult(null, string.Empty, diagnostics.ToString());
    }

    internal static bool TryParseUpdateProgress(
        string line,
        out UpdateProgress? progress)
    {
        progress = null;
        try
        {
            using var document = JsonDocument.Parse(line);
            if (document.RootElement.ValueKind != JsonValueKind.Object ||
                !document.RootElement.TryGetProperty("updateProgress", out _))
            {
                return false;
            }

            var envelope = JsonSerializer.Deserialize<ProgressEnvelope>(
                line,
                ProgressJsonOptions);
            progress = envelope?.UpdateProgress;
            return progress is not null;
        }
        catch (JsonException)
        {
            return false;
        }
    }

    private static bool TryParseResponse(
        string line,
        JsonSerializerOptions jsonOptions,
        out LauncherCliResponse? response)
    {
        response = null;
        try
        {
            using var document = JsonDocument.Parse(line);
            if (document.RootElement.ValueKind != JsonValueKind.Object ||
                !document.RootElement.TryGetProperty("success", out var success) ||
                success.ValueKind is not (JsonValueKind.True or JsonValueKind.False))
            {
                return false;
            }
            response = JsonSerializer.Deserialize<LauncherCliResponse>(line, jsonOptions);
            return response is not null;
        }
        catch (JsonException)
        {
            return false;
        }
    }

    private static void AppendDiagnostic(StringBuilder diagnostics, string line)
    {
        if (diagnostics.Length >= MaximumDiagnosticCharacters)
        {
            return;
        }
        if (diagnostics.Length > 0)
        {
            diagnostics.AppendLine();
        }
        var remaining = MaximumDiagnosticCharacters - diagnostics.Length;
        diagnostics.Append(line.AsSpan(0, Math.Min(line.Length, remaining)));
    }

    private static string JoinDiagnostics(string stdout, string stderr)
    {
        if (string.IsNullOrWhiteSpace(stdout))
        {
            return stderr.Trim();
        }
        if (string.IsNullOrWhiteSpace(stderr))
        {
            return stdout.Trim();
        }
        return $"{stdout.Trim()}\n{stderr.Trim()}";
    }

    private sealed record StreamReadResult(
        LauncherCliResponse? Response,
        string RawPayload,
        string Diagnostics);

    private sealed record ProgressEnvelope(
        UpdateProgress? UpdateProgress);
}
