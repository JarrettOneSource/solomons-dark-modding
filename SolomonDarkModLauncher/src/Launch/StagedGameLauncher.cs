using System.Diagnostics;
using SolomonDarkModding.IO;
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
    internal const string TestBlankBoneyardEnvironmentVariable =
        "SDMOD_TEST_BLANK_BONEYARD";

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
        MultiplayerLaunchEnvironment.MaxParticipantsVariable,
        "SDMOD_LUA_EXEC_PIPE_NAME",
        "SDMOD_LOADING_SCREEN_CAPTURE_DIRECTORY",
        "SDMOD_MULTIPLAYER_QUICK_START_RUN",
        "SDMOD_MULTIPLAYER_QUICK_START_ELEMENT",
        "SDMOD_MULTIPLAYER_QUICK_START_DISCIPLINE",
        TestBlankBoneyardEnvironmentVariable
    };

    public static InjectedGame Launch(
        StageBuildResult stage,
        LauncherConfiguration configuration,
        bool temporaryProfile = false,
        bool freshInstall = false,
        bool showStockTutorial = false,
        bool disableAudio = false,
        bool headless = false,
        MultiplayerLaunchOptions? multiplayer = null,
        string? savegamesRootOverride = null,
        LaunchOptions? options = null)
    {
        ApplyTestSurvivalBoneyardOverride(stage);
        ApplyTestWaveOverride(stage);
        var retailGameAppDataPath = TryResolveRetailAppDataPath();
        options = IsolatedProfileBootstrapper.CreateLaunchOptions(
            configuration.Workspace,
            options?.EnvironmentOverrides,
            retailGameAppDataPath,
            temporaryProfile,
            savegamesRootOverride,
            freshInstall);
        var savegamesUsesDirectoryMirror = false;
        if (!string.IsNullOrWhiteSpace(options.SavegamesRootPath))
        {
            savegamesUsesDirectoryMirror =
                StageSandboxCompatibilityLinks.Materialize(stage.StageRootPath, options.SavegamesRootPath);
        }
        var profileStateReceipt =
            NativeMenuProfileStateProvenance.Materialize(
                stage.StageRootPath,
                options,
                freshInstall,
                !freshInstall &&
                    !string.IsNullOrWhiteSpace(retailGameAppDataPath) &&
                    Directory.Exists(retailGameAppDataPath));
        options = ApplySandboxEnvironment(configuration, options);
        options = TutorialLaunchEnvironment.Apply(
            options,
            showStockTutorial);
        options = HeadlessLaunchEnvironment.Apply(
            options,
            headless);
        options = AudioLaunchEnvironment.Apply(
            options,
            disableAudio || headless);
        options = MultiplayerLaunchEnvironment.Apply(
            options,
            multiplayer ?? MultiplayerLaunchOptions.Create(
                MultiplayerLaunchMode.Unspecified,
                null,
                null,
                MultiplayerLaunchOptions.DefaultMaxParticipants,
                openInviteDialog: true,
                LobbyHostOptions.CreateDefault()));
        var usesLocalTransport =
            MultiplayerLaunchEnvironment.IsLocalTransport(options);
        var publishDirectory = multiplayer?.Mode ==
                MultiplayerLaunchMode.Host &&
            (!usesLocalTransport ||
             IsLoopbackDirectory(
                 multiplayer.Host.DirectoryBaseUrl));
        options = ApplyDirectoryPublisherFlag(
            options,
            publishDirectory);
        options = ApplySteamBootstrap(configuration, stage, options);
        var launchToken = Guid.NewGuid().ToString("N");
        options = ApplyLaunchToken(options, launchToken);

        var startInfo = new ProcessStartInfo
        {
            FileName = stage.StageExecutablePath,
            WorkingDirectory = stage.StageRootPath,
            UseShellExecute = false,
            CreateNoWindow = headless,
            WindowStyle = headless
                ? ProcessWindowStyle.Hidden
                : ProcessWindowStyle.Normal
        };
        ApplyEnvironmentOverrides(startInfo, options.EnvironmentOverrides);
        LoaderStartupStatusMonitor.Reset(stage.StageRootPath);
        MultiplayerSessionStatusMonitor.Reset(stage.StageRootPath);

        var startedAtUtc = DateTimeOffset.UtcNow;
        var process = Process.Start(startInfo);
        if (process is null)
        {
            throw new InvalidOperationException("Failed to start the staged game process.");
        }

        try
        {
            var loaderPath = ResolveLoaderPath();
            WindowsDllInjector.Inject(
                process,
                loaderPath,
                waitForInputIdle: !disableAudio && !headless);
            var startupStatus = LoaderStartupStatusMonitor.WaitForCompletion(stage.StageRootPath, launchToken);
            if (!startupStatus.Success)
            {
                throw new InvalidOperationException(
                    $"SolomonDarkModLoader startup failed ({startupStatus.Code}): {startupStatus.Message}");
            }
            if (!usesLocalTransport &&
                (multiplayer?.Mode is MultiplayerLaunchMode.Host or MultiplayerLaunchMode.Join) &&
                (!startupStatus.SteamTransportReady ||
                 !startupStatus.MultiplayerFoundationReady))
            {
                throw new InvalidOperationException(
                    "Steam multiplayer did not initialize. Ensure the Steam client is running and logged in, " +
                    $"then retry. Loader status: {startupStatus.Message}");
            }

            MultiplayerSessionStatus? multiplayerSessionStatus = null;
            if (multiplayer?.Mode == MultiplayerLaunchMode.Host)
            {
                multiplayerSessionStatus =
                    MultiplayerSessionStatusMonitor.WaitForHostReady(
                        stage.StageRootPath,
                        launchToken,
                        process);
                if (publishDirectory)
                {
                    LobbyDirectoryPublisher.TryStart(
                        stage.StageRootPath,
                        process.Id,
                        launchToken,
                        multiplayer.Host,
                        stage.MultiplayerCompatibility.EnabledMods);
                }
            }
            else if (multiplayer?.Mode ==
                     MultiplayerLaunchMode.Join)
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

            return new InjectedGame(
                process.Id,
                launchToken,
                startedAtUtc,
                loaderPath,
                startupStatus,
                multiplayerSessionStatus,
                options.SavegamesRootPath,
                savegamesUsesDirectoryMirror,
                profileStateReceipt.ReceiptPath,
                profileStateReceipt.ProfileStateIdentitySha256,
                profileStateReceipt.BaselineMode);
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

    private static LaunchOptions ApplyDirectoryPublisherFlag(
        LaunchOptions options,
        bool enabled)
    {
        var environment = new Dictionary<string, string>(
            StringComparer.OrdinalIgnoreCase);
        if (options.EnvironmentOverrides is not null)
        {
            foreach (var pair in options.EnvironmentOverrides)
            {
                environment[pair.Key] = pair.Value;
            }
        }
        environment[
            MultiplayerLaunchEnvironment.DirectoryPublisherVariable] =
            enabled ? "1" : "0";
        return options with { EnvironmentOverrides = environment };
    }

    private static bool IsLoopbackDirectory(string value) =>
        Uri.TryCreate(value, UriKind.Absolute, out var uri) &&
        uri.IsLoopback;

    private static string? TryResolveRetailAppDataPath()
    {
        var appDataRoot = LauncherPathPolicy.TryGetKnownFolder(
            Environment.SpecialFolder.ApplicationData);
        if (string.IsNullOrWhiteSpace(appDataRoot))
        {
            return null;
        }

        var retailPath = Path.Combine(appDataRoot, "solomondark");
        return Directory.Exists(retailPath) ? retailPath : null;
    }

    internal static LaunchOptions ApplySteamBootstrap(
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
        // Stamp the staged game with the retail AppID after the desktop UI removes
        // any synthetic non-Steam shortcut identity from its CLI child.
        environmentOverrides["SteamAppId"] = configuration.Steam.AppId;
        environmentOverrides["SteamGameId"] = configuration.Steam.AppId;
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
        environmentOverrides["SDMOD_LUA_EXEC_PIPE_NAME"] =
            $"SolomonDarkModLoader_LuaExec_{configuration.Workspace.InstanceName}";

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
}
