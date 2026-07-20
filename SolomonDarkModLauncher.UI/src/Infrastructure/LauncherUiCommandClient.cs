using System.Diagnostics;
using System.Text.Json;
using System.Text;
using SolomonDarkModding.Distribution;

namespace SolomonDarkModLauncher.UI.Infrastructure;

internal sealed class LauncherUiCommandClient
{
    private static readonly string[] TestOnlyChildEnvironmentVariables =
    {
        "SDMOD_TEST_BLANK_BONEYARD",
        "SDMOD_TEST_SURVIVAL_BONEYARD_OVERRIDE",
        "SDMOD_TEST_WAVE_OVERRIDE"
    };

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true
    };

    private readonly LauncherUiSettingsStore settingsStore_ = new();
    private readonly string? runtimeRoot_;
    private string instanceName_ = "default";
    private bool debugUiEnabled_ = true;
    private string lobbyId_ = string.Empty;
    private string gameDirectory_;
    private string directoryUrl_;

    public LauncherUiCommandClient()
    {
        var workspaceRoot = WorkspaceRootLocator.FindRootPath(AppContext.BaseDirectory);
        gameDirectory_ = settingsStore_.LoadGameDirectory() ??
            FindDevelopmentGameDirectory(workspaceRoot) ??
            string.Empty;
        directoryUrl_ = settingsStore_.LoadDirectoryUrl() ??
            LobbyDirectoryClient.DefaultDirectoryUrl;
        var portableMarkerPath = Path.Combine(
            workspaceRoot,
            DistributionLayout.PortableRootMarkerFileName);
        runtimeRoot_ = File.Exists(portableMarkerPath)
            ? settingsStore_.RuntimeRoot
            : null;
    }

    public string InstanceName => instanceName_;
    public bool DebugUiEnabled => debugUiEnabled_;

    public string LobbyId => lobbyId_;

    public string GameDirectory => gameDirectory_;

    public void UpdateInstance(string? instanceName)
    {
        instanceName_ = NormalizeInstanceName(instanceName);
    }

    public void UpdateDebugUiEnabled(bool enabled)
    {
        debugUiEnabled_ = enabled;
    }

    public void UpdateLobbyId(string? lobbyId)
    {
        lobbyId_ = lobbyId?.Trim() ?? string.Empty;
    }

    public void UpdateGameDirectory(string gameDirectory)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(gameDirectory);
        var normalizedPath = Path.GetFullPath(gameDirectory.Trim());
        gameDirectory_ = normalizedPath;
        settingsStore_.SaveGameDirectory(normalizedPath);
    }

    public string DirectoryUrl => directoryUrl_;

    public void UpdateDirectoryUrl(string? directoryUrl)
    {
        var trimmed = directoryUrl?.Trim();
        if (string.IsNullOrEmpty(trimmed))
        {
            directoryUrl_ = LobbyDirectoryClient.DefaultDirectoryUrl;
            settingsStore_.SaveDirectoryUrl(null);
            return;
        }

        if (!Uri.TryCreate(trimmed, UriKind.Absolute, out var uri) ||
            uri.Scheme is not ("http" or "https"))
        {
            throw new InvalidOperationException(
                "Enter an absolute HTTP or HTTPS URL for the lobby directory.");
        }

        directoryUrl_ = trimmed;
        settingsStore_.SaveDirectoryUrl(trimmed);
    }

    public string BuildCommandPreview(
        LauncherUiCommandMode mode,
        string? targetModId = null,
        LauncherHostOptions? hostOptions = null)
    {
        var arguments = BuildArguments(mode, targetModId, hostOptions);
        return $"SolomonDarkModLauncher.exe {string.Join(" ", arguments.Select(QuoteArgument))}";
    }

    public async Task<LauncherUiInvocationResult> InvokeAsync(
        LauncherUiCommandMode mode,
        string? targetModId = null,
        LauncherHostOptions? hostOptions = null,
        CancellationToken cancellationToken = default)
    {
        var arguments = BuildArguments(mode, targetModId, hostOptions);
        var executablePath = LauncherExecutableResolver.Resolve();
        var startInfo = new ProcessStartInfo(executablePath)
        {
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true
        };
        foreach (var variableName in TestOnlyChildEnvironmentVariables)
        {
            startInfo.Environment.Remove(variableName);
        }

        foreach (var argument in arguments)
        {
            startInfo.ArgumentList.Add(argument);
        }

        using var process = new Process { StartInfo = startInfo };
        process.Start();

        var readResult = await LauncherJsonResponseReader.ReadAsync(
            process,
            JsonOptions,
            cancellationToken);
        var response = readResult.Response;
        string? errorMessage = null;

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
                ? "The launcher did not return a JSON response."
                : $"Launcher exited with code {process.ExitCode}.";
            if (!string.IsNullOrWhiteSpace(readResult.Diagnostics))
            {
                errorMessage += $" Output: {readResult.Diagnostics}";
            }
        }

        return new LauncherUiInvocationResult(
            arguments,
            response,
            response?.Transcript ?? readResult.RawPayload,
            errorMessage);
    }

    public async Task<LauncherCliDirectorySession> AuthenticateDirectoryAsync(
        CancellationToken cancellationToken)
    {
        var invocation = await InvokeAsync(
            LauncherUiCommandMode.AuthenticateDirectory,
            cancellationToken: cancellationToken);
        var session = invocation.Response?.DirectorySession;
        if (!invocation.Succeeded || session is null ||
            string.IsNullOrWhiteSpace(session.Token))
        {
            throw new InvalidOperationException(
                invocation.ErrorMessage ?? "The Steam account check failed.");
        }

        return session;
    }

    private IReadOnlyList<string> BuildArguments(
        LauncherUiCommandMode mode,
        string? targetModId,
        LauncherHostOptions? hostOptions = null)
    {
        var arguments = new List<string> { GetModeToken(mode), "--json" };

        if (mode == LauncherUiCommandMode.AuthenticateDirectory)
        {
            arguments.Add("--directory-url");
            arguments.Add(directoryUrl_);
            return arguments;
        }

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

        if (!string.IsNullOrWhiteSpace(gameDirectory_))
        {
            arguments.Add("--game-dir");
            arguments.Add(gameDirectory_);
        }

        if (!string.IsNullOrWhiteSpace(runtimeRoot_))
        {
            arguments.Add("--runtime-root");
            arguments.Add(runtimeRoot_);
        }

        switch (mode)
        {
            case LauncherUiCommandMode.LaunchSinglePlayer:
                arguments.Add("--multiplayer");
                arguments.Add("off");
                break;
            case LauncherUiCommandMode.HostSteam:
                arguments.Add("--multiplayer");
                arguments.Add("host");
                arguments.Add("--lobby-privacy");
                arguments.Add(hostOptions?.Privacy ?? "friends");
                arguments.Add("--directory-url");
                arguments.Add(directoryUrl_);
                break;
            case LauncherUiCommandMode.JoinSteam:
                arguments.Add("--multiplayer");
                arguments.Add("join");
                if (!string.IsNullOrWhiteSpace(lobbyId_))
                {
                    arguments.Add("--lobby-id");
                    arguments.Add(lobbyId_);
                }
                break;
        }

        return arguments;
    }

    private static string GetModeToken(LauncherUiCommandMode mode)
    {
        return mode switch
        {
            LauncherUiCommandMode.LaunchSinglePlayer => "launch",
            LauncherUiCommandMode.HostSteam => "launch",
            LauncherUiCommandMode.JoinSteam => "launch",
            LauncherUiCommandMode.AuthenticateDirectory => "directory-auth",
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
                "Instance names can contain only letters, numbers, periods, hyphens, and underscores. Include one or more letters or numbers.");
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
                "Instance names can contain only letters, numbers, periods, hyphens, and underscores. Include one or more letters or numbers.");
        }

        if (!hasLetterOrDigit)
        {
            throw new InvalidOperationException(
                "Instance names can contain only letters, numbers, periods, hyphens, and underscores. Include one or more letters or numbers.");
        }

        return builder.ToString();
    }

    private static string? FindDevelopmentGameDirectory(string workspaceRoot)
    {
        var candidate = Path.GetFullPath(Path.Combine(
            workspaceRoot,
            "..",
            "SolomonDarkAbandonware"));
        return File.Exists(Path.Combine(candidate, "SolomonDark.exe"))
            ? candidate
            : null;
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
