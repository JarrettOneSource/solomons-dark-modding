using System.Diagnostics;
using SolomonDarkModLauncher.Staging;
using SolomonDarkModLauncher.Steam;
using SolomonDarkModLauncher.Target;

namespace SolomonDarkModLauncher.Launch;

internal static class StagedGameLauncher
{
    private static readonly string[] SandboxEnvironmentVariables =
    {
        "SDMOD_UI_SANDBOX_PRESET",
        "SDMOD_UI_SANDBOX_ARM_DELAY_MS",
        "SDMOD_UI_SANDBOX_SAFETY_TIMEOUT_MS",
        "SDMOD_TEST_AUTOSPAWN_BOT",
        "SDMOD_TEST_AUTOSPAWN_BOT_WIZARD_ID",
        "SDMOD_TEST_AUTOSPAWN_BOT_TRACE",
        "SDMOD_EXPERIMENTAL_REMOTE_WIZARD_SPAWN",
        "SDMOD_DISABLE_EXPERIMENTAL_REMOTE_WIZARD_SPAWN"
    };

    public static InjectedGame Launch(
        StageBuildResult stage,
        LauncherConfiguration configuration,
        LaunchOptions? options = null)
    {
        options = IsolatedProfileBootstrapper.CreateLaunchOptions(
            configuration.Workspace,
            options?.EnvironmentOverrides,
            TryResolveRetailAppDataPath());
        options = ApplySandboxEnvironment(configuration, options);
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

            return new InjectedGame(process.Id, loaderPath, startupStatus);
        }
        catch
        {
            TryTerminate(process);
            throw;
        }
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

        if (!string.IsNullOrWhiteSpace(stage.SteamBootstrap.StageAppIdPath))
        {
            environmentOverrides[SteamBootstrapConfiguration.AppIdPathEnvironmentVariable] = stage.SteamBootstrap.StageAppIdPath;
        }

        if (!string.IsNullOrWhiteSpace(stage.SteamBootstrap.StageApiDllPath))
        {
            environmentOverrides[SteamBootstrapConfiguration.ApiDllPathEnvironmentVariable] = stage.SteamBootstrap.StageApiDllPath;
        }

        return new LaunchOptions(environmentOverrides);
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

        return new LaunchOptions(environmentOverrides);
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
        return new LaunchOptions(environmentOverrides);
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
