using System.Diagnostics;
using SolomonDarkModLauncher.Staging;
using SolomonDarkModLauncher.Steam;
using SolomonDarkModLauncher.Target;

namespace SolomonDarkModLauncher.Launch;

internal static class StagedGameLauncher
{
    internal const string TestSurvivalBoneyardOverrideEnvironmentVariable =
        "SDMOD_TEST_SURVIVAL_BONEYARD_OVERRIDE";
    internal const string TestWaveOverrideEnvironmentVariable =
        "SDMOD_TEST_WAVE_OVERRIDE";

    private static readonly string[] SandboxEnvironmentVariables =
    {
        "SDMOD_UI_SANDBOX_PRESET",
        "SDMOD_UI_SANDBOX_ARM_DELAY_MS",
        "SDMOD_UI_SANDBOX_SAFETY_TIMEOUT_MS",
        "SDMOD_TEST_AUTOSPAWN_BOT",
        "SDMOD_TEST_AUTOSPAWN_BOT_WIZARD_ID",
        "SDMOD_TEST_AUTOSPAWN_BOT_TRACE",
        "SDMOD_EXPERIMENTAL_REMOTE_WIZARD_SPAWN",
        "SDMOD_DISABLE_EXPERIMENTAL_REMOTE_WIZARD_SPAWN",
        "SDMOD_MULTIPLAYER_TRANSPORT",
        "SDMOD_MULTIPLAYER_ROLE",
        "SDMOD_MULTIPLAYER_LOCAL_PORT",
        "SDMOD_MULTIPLAYER_REMOTE_HOST",
        "SDMOD_MULTIPLAYER_REMOTE_PORT",
        "SDMOD_MULTIPLAYER_PARTICIPANT_ID",
        "SDMOD_MULTIPLAYER_PLAYER_NAME",
        "SDMOD_LUA_EXEC_PIPE_NAME"
    };

    public static InjectedGame Launch(
        StageBuildResult stage,
        LauncherConfiguration configuration,
        bool temporaryProfile = false,
        MultiplayerLaunchOptions? multiplayer = null,
        LaunchOptions? options = null)
    {
        ApplyTestSurvivalBoneyardOverride(stage);
        ApplyTestWaveOverride(stage);
        options = IsolatedProfileBootstrapper.CreateLaunchOptions(
            configuration.Workspace,
            options?.EnvironmentOverrides,
            TryResolveRetailAppDataPath(),
            temporaryProfile);
        if (options.TemporaryProfile && !string.IsNullOrWhiteSpace(options.SavegamesRootPath))
        {
            StageSandboxCompatibilityLinks.Materialize(stage.StageRootPath, options.SavegamesRootPath);
        }
        options = ApplySandboxEnvironment(configuration, options);
        multiplayer ??= MultiplayerLaunchOptions.Create(
                MultiplayerLaunchMode.Unspecified,
                null,
                null,
                MultiplayerLaunchOptions.DefaultMaxParticipants,
                openInviteDialog: true,
                LobbyHostOptions.CreateDefault(),
                joinTicket: null);
        var directorySecret = multiplayer.Mode == MultiplayerLaunchMode.Host
            ? LobbyDirectorySecret.Create()
            : null;
        options = MultiplayerLaunchEnvironment.Apply(
            options,
            multiplayer,
            directorySecret);
        options = ApplySteamBootstrap(configuration, stage, options);
        var launchToken = Guid.NewGuid().ToString("N");
        options = ApplyLaunchToken(options, launchToken);

        var startInfo = new ProcessStartInfo
        {
            FileName = stage.StageExecutablePath,
            WorkingDirectory = stage.StageRootPath,
            UseShellExecute = false
        };
        ApplyEnvironmentOverrides(startInfo, options.EnvironmentOverrides);
        LoaderStartupStatusMonitor.Reset(stage.StageRootPath);
        MultiplayerSessionStatusMonitor.Reset(stage.StageRootPath);

        var process = Process.Start(startInfo);
        if (process is null)
        {
            throw new InvalidOperationException("Failed to start the staged game process.");
        }

        try
        {
            var loaderPath = ResolveLoaderPath();
            WindowsDllInjector.Inject(process, loaderPath);
            var startupStatus = LoaderStartupStatusMonitor.WaitForCompletion(stage.StageRootPath, launchToken);
            if (!startupStatus.Success)
            {
                throw new InvalidOperationException(
                    $"SolomonDarkModLoader startup failed ({startupStatus.Code}): {startupStatus.Message}");
            }
            if (multiplayer.Mode is MultiplayerLaunchMode.Host or MultiplayerLaunchMode.Join &&
                (!startupStatus.SteamTransportReady ||
                 !startupStatus.MultiplayerFoundationReady))
            {
                throw new InvalidOperationException(
                    "Steam multiplayer did not initialize. Ensure the Steam client is running and logged in, " +
                    $"then retry. Loader status: {startupStatus.Message}");
            }

            MultiplayerSessionStatus? multiplayerSessionStatus = null;
            if (multiplayer.Mode == MultiplayerLaunchMode.Host)
            {
                multiplayerSessionStatus =
                    MultiplayerSessionStatusMonitor.WaitForHostReady(
                        stage.StageRootPath,
                        launchToken,
                        process);
            }
            else if (multiplayer.Mode == MultiplayerLaunchMode.Join)
            {
                multiplayerSessionStatus = multiplayer.LobbyId.HasValue
                    ? MultiplayerSessionStatusMonitor.WaitForConnectedJoin(
                        stage.StageRootPath,
                        launchToken,
                        process)
                    : MultiplayerSessionStatusMonitor.WaitForInvite(
                        stage.StageRootPath,
                        launchToken,
                        process);
            }

            if (multiplayer.Mode == MultiplayerLaunchMode.Host &&
                multiplayerSessionStatus is not null &&
                directorySecret is not null)
            {
                TryStartLobbyDirectoryPublisher(
                    stage.StageRootPath,
                    process.Id,
                    launchToken,
                    multiplayer.Host,
                    directorySecret);
            }

            return new InjectedGame(
                process.Id,
                loaderPath,
                startupStatus,
                multiplayerSessionStatus);
        }
        catch
        {
            TryTerminate(process);
            throw;
        }
    }

    private static void ApplyTestSurvivalBoneyardOverride(StageBuildResult stage)
    {
        var sourcePath = Environment.GetEnvironmentVariable(
            TestSurvivalBoneyardOverrideEnvironmentVariable);
        if (string.IsNullOrWhiteSpace(sourcePath))
        {
            return;
        }

        sourcePath = Path.GetFullPath(sourcePath);
        if (!File.Exists(sourcePath))
        {
            throw new FileNotFoundException(
                "Test survival boneyard override was not found.",
                sourcePath);
        }
        if (!string.Equals(
                Path.GetExtension(sourcePath),
                ".boneyard",
                StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException(
                $"Test survival boneyard override must be a .boneyard file: {sourcePath}");
        }

        var targetPaths = new[]
        {
            Path.Combine(
                stage.StageRootPath,
                "data",
                "levels",
                "survival.boneyard"),
            Path.Combine(
                stage.StageRootPath,
                "sandbox",
                "DarkCloud",
                "mylevels",
                "New Boneyard 1.boneyard"),
        };
        foreach (var targetPath in targetPaths)
        {
            var targetDirectory = Path.GetDirectoryName(targetPath)
                ?? throw new InvalidOperationException(
                    $"Test survival boneyard target has no directory: {targetPath}");
            Directory.CreateDirectory(targetDirectory);
            File.Copy(sourcePath, targetPath, overwrite: true);
        }
    }

    private static void ApplyTestWaveOverride(StageBuildResult stage)
    {
        var sourcePath = Environment.GetEnvironmentVariable(
            TestWaveOverrideEnvironmentVariable);
        if (string.IsNullOrWhiteSpace(sourcePath))
        {
            return;
        }

        sourcePath = Path.GetFullPath(sourcePath);
        if (!File.Exists(sourcePath))
        {
            throw new FileNotFoundException(
                "Test wave override was not found.",
                sourcePath);
        }
        if (!string.Equals(
                Path.GetExtension(sourcePath),
                ".txt",
                StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException(
                $"Test wave override must be a .txt file: {sourcePath}");
        }

        var targetPath = Path.Combine(stage.StageRootPath, "data", "wave.txt");
        var targetDirectory = Path.GetDirectoryName(targetPath)
            ?? throw new InvalidOperationException(
                $"Test wave target has no directory: {targetPath}");
        Directory.CreateDirectory(targetDirectory);
        File.Copy(sourcePath, targetPath, overwrite: true);
    }

    private static void ApplyEnvironmentOverrides(
        ProcessStartInfo startInfo,
        IReadOnlyDictionary<string, string>? environmentOverrides)
    {
        if (environmentOverrides is null)
        {
            return;
        }

        foreach (var pair in environmentOverrides)
        {
            startInfo.Environment[pair.Key] = pair.Value;
        }
    }

    private static string? TryResolveRetailAppDataPath()
    {
        var appDataRoot = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
        if (string.IsNullOrWhiteSpace(appDataRoot))
        {
            return null;
        }

        var retailPath = Path.Combine(appDataRoot, "solomondark");
        return Directory.Exists(retailPath) ? retailPath : null;
    }

    private static LaunchOptions ApplySteamBootstrap(
        LauncherConfiguration configuration,
        StageBuildResult stage,
        LaunchOptions options)
    {
        var environmentOverrides = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        if (options.EnvironmentOverrides is not null)
        {
            foreach (var pair in options.EnvironmentOverrides)
            {
                environmentOverrides[pair.Key] = pair.Value;
            }
        }

        environmentOverrides[SteamBootstrapConfiguration.EnableEnvironmentVariable] = configuration.Steam.Enabled ? "1" : "0";
        environmentOverrides[SteamBootstrapConfiguration.AppIdEnvironmentVariable] = configuration.Steam.AppId;
        environmentOverrides[SteamBootstrapConfiguration.AllowRestartEnvironmentVariable] = configuration.Steam.AllowRestartIfNecessary ? "1" : "0";
        environmentOverrides[MultiplayerCompatibilityMaterializer.FingerprintEnvironmentVariable] =
            stage.MultiplayerCompatibility.FingerprintSha256;

        if (!string.IsNullOrWhiteSpace(stage.SteamBootstrap.StageAppIdPath))
        {
            environmentOverrides[SteamBootstrapConfiguration.AppIdPathEnvironmentVariable] = stage.SteamBootstrap.StageAppIdPath;
        }

        if (!string.IsNullOrWhiteSpace(stage.SteamBootstrap.StageApiDllPath))
        {
            environmentOverrides[SteamBootstrapConfiguration.ApiDllPathEnvironmentVariable] = stage.SteamBootstrap.StageApiDllPath;
        }

        return options with { EnvironmentOverrides = environmentOverrides };
    }

    private static LaunchOptions ApplySandboxEnvironment(
        LauncherConfiguration configuration,
        LaunchOptions options)
    {
        var environmentOverrides = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        if (options.EnvironmentOverrides is not null)
        {
            foreach (var pair in options.EnvironmentOverrides)
            {
                environmentOverrides[pair.Key] = pair.Value;
            }
        }

        foreach (var variableName in SandboxEnvironmentVariables)
        {
            var value = Environment.GetEnvironmentVariable(variableName);
            if (!string.IsNullOrWhiteSpace(value))
            {
                environmentOverrides[variableName] = value;
            }
        }

        return options with { EnvironmentOverrides = environmentOverrides };
    }

    private static LaunchOptions ApplyLaunchToken(LaunchOptions options, string launchToken)
    {
        var environmentOverrides = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        if (options.EnvironmentOverrides is not null)
        {
            foreach (var pair in options.EnvironmentOverrides)
            {
                environmentOverrides[pair.Key] = pair.Value;
            }
        }

        environmentOverrides[LoaderLaunchContract.LaunchTokenEnvironmentVariable] = launchToken;
        return options with { EnvironmentOverrides = environmentOverrides };
    }

    private static string ResolveLoaderPath()
    {
        return Path.Combine(AppContext.BaseDirectory, "SolomonDarkModLoader.dll");
    }

    private static void TryTerminate(Process process)
    {
        try
        {
            if (!process.HasExited)
            {
                process.Kill(entireProcessTree: true);
            }
        }
        catch
        {
        }
    }

    private static void TryStartLobbyDirectoryPublisher(
        string stageRootPath,
        int gameProcessId,
        string launchToken,
        LobbyHostOptions host,
        string directorySecret)
    {
        try
        {
            LobbyDirectoryPublisher.Start(
                stageRootPath,
                gameProcessId,
                launchToken,
                host,
                directorySecret);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or InvalidOperationException)
        {
            var logPath = Path.Combine(stageRootPath, ".sdmod", "lobby-directory.log");
            try
            {
                File.AppendAllText(
                    logPath,
                    $"{DateTime.UtcNow:O} Could not start directory publisher: {ex.Message}{Environment.NewLine}");
            }
            catch (Exception logError) when (logError is IOException or UnauthorizedAccessException)
            {
            }
        }
    }
}
