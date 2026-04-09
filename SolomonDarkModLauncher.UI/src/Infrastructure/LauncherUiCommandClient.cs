using System.Diagnostics;
using System.Text.Json;
using System.Text;

namespace SolomonDarkModLauncher.UI.Infrastructure;

internal sealed class LauncherUiCommandClient
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true
    };

    private string instanceName_ = "default";
    private bool debugUiEnabled_ = true;

    public string InstanceName => instanceName_;
    public bool DebugUiEnabled => debugUiEnabled_;

    public void UpdateInstance(string? instanceName)
    {
        instanceName_ = NormalizeInstanceName(instanceName);
    }

    public void UpdateDebugUiEnabled(bool enabled)
    {
        debugUiEnabled_ = enabled;
    }

    public string BuildCommandPreview(LauncherUiCommandMode mode, string? targetModId = null)
    {
        var arguments = BuildArguments(mode, targetModId);
        return $"SolomonDarkModLauncher.exe {string.Join(" ", arguments.Select(QuoteArgument))}";
    }

    public async Task<LauncherUiInvocationResult> InvokeAsync(
        LauncherUiCommandMode mode,
        string? targetModId = null,
        CancellationToken cancellationToken = default)
    {
        var arguments = BuildArguments(mode, targetModId);
        var executablePath = LauncherExecutableResolver.Resolve();
        var startInfo = new ProcessStartInfo(executablePath)
        {
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true
        };

        foreach (var argument in arguments)
        {
            startInfo.ArgumentList.Add(argument);
        }

        using var process = new Process { StartInfo = startInfo };
        process.Start();

        var stdoutTask = process.StandardOutput.ReadToEndAsync(cancellationToken);
        var stderrTask = process.StandardError.ReadToEndAsync(cancellationToken);
        await process.WaitForExitAsync(cancellationToken);

        var stdout = await stdoutTask;
        var stderr = await stderrTask;
        var rawPayload = string.IsNullOrWhiteSpace(stdout) ? stderr : stdout;

        LauncherCliResponse? response = null;
        string? errorMessage = null;
        if (!string.IsNullOrWhiteSpace(rawPayload))
        {
            try
            {
                response = JsonSerializer.Deserialize<LauncherCliResponse>(rawPayload, JsonOptions);
            }
            catch (JsonException ex)
            {
                errorMessage = $"Failed to parse launcher response: {ex.Message}";
            }
        }

        if (response?.Success == true && process.ExitCode == 0)
        {
            return new LauncherUiInvocationResult(
                arguments,
                response,
                response.Transcript ?? string.Empty,
                ErrorMessage: null);
        }

        errorMessage ??= response?.Error;
        if (string.IsNullOrWhiteSpace(errorMessage))
        {
            errorMessage = process.ExitCode == 0
                ? "Launcher returned no response."
                : $"Launcher exited with code {process.ExitCode}.";
        }

        return new LauncherUiInvocationResult(
            arguments,
            response,
            response?.Transcript ?? rawPayload.Trim(),
            errorMessage);
    }

    private IReadOnlyList<string> BuildArguments(LauncherUiCommandMode mode, string? targetModId)
    {
        var arguments = new List<string> { GetModeToken(mode), "--json" };

        if (mode is LauncherUiCommandMode.EnableMod or LauncherUiCommandMode.DisableMod)
        {
            arguments.Add(targetModId ?? throw new InvalidOperationException("A mod id is required for this command."));
        }

        if (!string.Equals(instanceName_, "default", StringComparison.Ordinal))
        {
            arguments.Add("--instance");
            arguments.Add(instanceName_);
        }

        if (!debugUiEnabled_)
        {
            arguments.Add("--runtime-flag");
            arguments.Add("loader.debug_ui=false");
        }

        return arguments;
    }

    private static string GetModeToken(LauncherUiCommandMode mode)
    {
        return mode switch
        {
            LauncherUiCommandMode.Launch => "launch",
            LauncherUiCommandMode.Stage => "stage",
            LauncherUiCommandMode.ListMods => "list-mods",
            LauncherUiCommandMode.EnableMod => "enable-mod",
            LauncherUiCommandMode.DisableMod => "disable-mod",
            _ => throw new InvalidOperationException($"Unsupported mode: {mode}")
        };
    }

    private static string NormalizeInstanceName(string? instanceName)
    {
        if (string.IsNullOrWhiteSpace(instanceName))
        {
            return "default";
        }

        var trimmed = instanceName.Trim();
        if (trimmed.Length == 0 || trimmed.Length > 64)
        {
            throw new InvalidOperationException(
                "Instance names may only use letters, digits, '.', '-', and '_' and must include at least one letter or digit.");
        }

        var builder = new StringBuilder(trimmed.Length);
        var hasLetterOrDigit = false;
        foreach (var character in trimmed)
        {
            if (char.IsLetterOrDigit(character))
            {
                builder.Append(char.ToLowerInvariant(character));
                hasLetterOrDigit = true;
                continue;
            }

            if (character is '.' or '-' or '_')
            {
                builder.Append(character);
                continue;
            }

            throw new InvalidOperationException(
                "Instance names may only use letters, digits, '.', '-', and '_' and must include at least one letter or digit.");
        }

        if (!hasLetterOrDigit)
        {
            throw new InvalidOperationException(
                "Instance names may only use letters, digits, '.', '-', and '_' and must include at least one letter or digit.");
        }

        return builder.ToString();
    }

    private static string QuoteArgument(string value)
    {
        if (value.Length == 0)
        {
            return "\"\"";
        }

        return value.Any(char.IsWhiteSpace)
            ? $"\"{value}\""
            : value;
    }
}
