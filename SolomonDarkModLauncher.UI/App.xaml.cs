using System.Windows;
using System.Text.Json;
using SolomonDarkModding.Updates;
using SolomonDarkModLauncher.UI.Infrastructure;
using SolomonDarkModLauncher.UI.ViewModels;
using SolomonDarkModLauncher.UI.Views;

namespace SolomonDarkModLauncher.UI;

public partial class App : Application
{
    private LauncherActivationBroker? activationBroker_;
    private LauncherRelease? pendingLauncherUpdate_;
    private string activationArgument_ = string.Empty;

    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        if (!LauncherStartupArguments.TryParse(
                e.Args,
                out var startupArguments))
        {
            MessageBox.Show(
                "The launcher received invalid startup arguments.",
                "Solomon Darker",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
            Shutdown(2);
            return;
        }
        startupArguments.ApplyTestIsolation();
        LauncherShell.UseSafeCurrentDirectory();

        // #71 visual-acceptance preview: render an actual session-status
        // roster in-process, before activation, registration, updates, or CLI
        // work can touch an installed launcher.
        var lobbyPreviewStatusPath =
            Environment.GetEnvironmentVariable("SDMOD_UI_LOBBY_PREVIEW_STATUS");
        if (!string.IsNullOrWhiteSpace(lobbyPreviewStatusPath))
        {
            try
            {
                var status = JsonSerializer.Deserialize<LauncherCliMultiplayerSession>(
                    File.ReadAllText(lobbyPreviewStatusPath),
                    new JsonSerializerOptions
                    {
                        PropertyNameCaseInsensitive = true
                    }) ?? throw new InvalidOperationException(
                        "Lobby preview status JSON was empty.");
                status.Members ??= [];
                var lobbyPreviewViewModel = new LobbyRosterPreviewViewModel(
                    status,
                    Environment.GetEnvironmentVariable(
                        "SDMOD_UI_LOBBY_PREVIEW_LABEL") ?? string.Empty);
                var previewWindow = new LobbyRosterPreviewWindow(
                    lobbyPreviewViewModel);
                previewWindow.ContentRendered += (_, _) =>
                {
                    var outputPath = Environment.GetEnvironmentVariable(
                        "SDMOD_UI_LOBBY_PREVIEW_RTB");
                    if (string.IsNullOrWhiteSpace(outputPath))
                    {
                        return;
                    }
                    RenderTargetBitmapCapture.Save(
                        previewWindow,
                        outputPath);
                    Shutdown(0);
                };
                MainWindow = previewWindow;
                previewWindow.Show();
            }
            catch (Exception exception) when (
                exception is IOException or
                UnauthorizedAccessException or
                JsonException or
                InvalidOperationException)
            {
                MessageBox.Show(
                    exception.Message,
                    "Lobby roster preview",
                    MessageBoxButton.OK,
                    MessageBoxImage.Error);
                Shutdown(2);
            }
            return;
        }

        // #61 visual-acceptance preview: SDMOD_UI_SETTINGS_PREVIEW=1 opens the
        // mod settings dialog against the stub source and exits with it —
        // before the activation broker, protocol registration, CLI client, or
        // self-update ever run, so a dev build can never disturb the real
        // launcher installation.
        if (Environment.GetEnvironmentVariable("SDMOD_UI_SETTINGS_PREVIEW") == "1"
            && ViewModels.ModSettings.StubModSettingsSource.Enabled)
        {
            string previewLog = Path.Combine(Path.GetTempPath(), "sdmod-ui-settings-preview.log");
            void Log(string line) =>
                File.AppendAllText(previewLog, $"{DateTime.Now:HH:mm:ss.fff} {line}{Environment.NewLine}");

            DispatcherUnhandledException += (_, args) =>
            {
                Log($"dispatcher exception: {args.Exception}");
                args.Handled = true;
            };

            try
            {
                Log("preview starting");

                // SDMOD_UI_SETTINGS_PREVIEW_REAL="<modsRoot>|<stageRoot>" runs
                // the dialog over the real #60 service chain instead of the stub.
                ViewModels.ModSettings.IModSettingsSource source;
                string? real = Environment.GetEnvironmentVariable("SDMOD_UI_SETTINGS_PREVIEW_REAL");
                if (real?.Split('|') is [{ } modsRoot, { } stageRoot])
                {
                    var manifestService = new SolomonDarkModLauncher.ModSettings.ModSettingsManifestService();
                    source = new ViewModels.ModSettings.ModSettingsSourceAdapter(
                        new SolomonDarkModLauncher.ModSettings.ModSettingsService(
                            modsRoot,
                            stageRoot,
                            new SolomonDarkModLauncher.ModSettings.ModSettingsDiscoveryService(manifestService),
                            new SolomonDarkModLauncher.ModSettings.ModSettingsStore(manifestService),
                            new SolomonDarkModLauncher.ModSettings.ModSettingsRuntimeClient(),
                            new SolomonDarkModLauncher.ModSettings.ModSettingsInstanceContext()));
                    Log($"preview using REAL services modsRoot={modsRoot} stageRoot={stageRoot}");
                }
                else
                {
                    source = new ViewModels.ModSettings.StubModSettingsSource();
                }

                var previewViewModel = new ViewModels.ModSettings.ModSettingsDialogViewModel(
                    source,
                    "bot.brain");
                if (Environment.GetEnvironmentVariable("SDMOD_UI_SETTINGS_PREVIEW_EXPAND") == "1")
                {
                    var firstRow = previewViewModel.AllEntries
                        .OfType<ViewModels.ModSettings.ListSettingViewModel>()
                        .FirstOrDefault()?.Items.FirstOrDefault();
                    if (firstRow is not null)
                    {
                        firstRow.IsExpanded = true;
                    }
                }

                var previewWindow = new ModSettingsWindow(previewViewModel);
                previewWindow.Loaded += (_, _) => Log("preview window loaded");
                previewWindow.ContentRendered += (_, _) =>
                {
                    Log("preview window content rendered");
                    string? rtbPath = Environment.GetEnvironmentVariable("SDMOD_UI_SETTINGS_PREVIEW_RTB");
                    if (string.IsNullOrEmpty(rtbPath))
                    {
                        return;
                    }

                    try
                    {
                        RenderTargetBitmapCapture.Save(
                            previewWindow,
                            rtbPath);
                        Log($"rtb saved {previewWindow.ActualWidth}x{previewWindow.ActualHeight} -> {rtbPath}");
                    }
                    catch (Exception ex)
                    {
                        Log($"rtb failed: {ex}");
                    }
                };
                MainWindow = previewWindow;
                previewWindow.Show();
                Log("preview window shown");
            }
            catch (Exception ex)
            {
                Log($"preview startup exception: {ex}");
                throw;
            }

            return;
        }

        activationBroker_ = new LauncherActivationBroker(
            startupArguments.TestScope);
        var activationArgument =
            startupArguments.ActivationArgument;
        activationArgument_ = activationArgument;
        if (!activationBroker_.IsPrimary)
        {
            if (!activationBroker_.ForwardActivation(activationArgument))
            {
                MessageBox.Show(
                    "The open launcher did not accept the lobby link. Close it and try again.",
                    "Solomon Darker",
                    MessageBoxButton.OK,
                    MessageBoxImage.Error);
            }
            Shutdown();
            return;
        }

        try
        {
            if (startupArguments.IsTestScoped)
            {
                LauncherProtocolRegistration.RegisterCurrentExecutable(
                    startupArguments.ProtocolCommandScopeArgument);
            }
            else
            {
                LauncherProtocolRegistration.RegisterCurrentExecutable();
            }
        }
        catch (Exception ex) when (ex is IOException or
                                   UnauthorizedAccessException or
                                   InvalidOperationException)
        {
            MessageBox.Show(
                ex.Message,
                "Solomon Darker",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
            Shutdown(2);
            return;
        }

        var client = new LauncherUiCommandClient();
        var viewModel = new MainWindowViewModel(client);
        var window = new MainWindow
        {
            DataContext = viewModel
        };
        window.Closed += (_, _) => viewModel.Dispose();
        viewModel.LauncherUpdateAccepted += (_, _) =>
            _ = InstallLauncherUpdateAsync(viewModel);

        MainWindow = window;
        window.Show();

        activationBroker_.StartListening(argument =>
            _ = Dispatcher.InvokeAsync(() =>
            {
                activationArgument_ = argument;
                Activate(window, viewModel, argument);
            }));
        Activate(window, viewModel, activationArgument);
        if (!startupArguments.IsTestScoped)
        {
            _ = CheckForLauncherUpdateAsync(viewModel);
        }
    }

    protected override void OnExit(ExitEventArgs e)
    {
        activationBroker_?.Dispose();
        activationBroker_ = null;
        base.OnExit(e);
    }

    private static void Activate(
        MainWindow window,
        MainWindowViewModel viewModel,
        string argument)
    {
        if (window.WindowState == WindowState.Minimized)
        {
            window.WindowState = WindowState.Normal;
        }
        window.Activate();

        if (argument.Length == 0)
        {
            return;
        }
        if (LauncherJoinUri.TryParse(argument, out var joinActivation))
        {
            viewModel.QueueWebsiteLobbyJoin(joinActivation);
            return;
        }
        if (LauncherJoinUri.TryParseInstallMod(
                argument,
                out var installActivation))
        {
            viewModel.QueueWebsiteModInstall(installActivation);
            return;
        }

        MessageBox.Show(
            window,
            "This Solomon Darker link is not valid.",
            "Solomon Darker",
            MessageBoxButton.OK,
            MessageBoxImage.Error);
    }

    private async Task CheckForLauncherUpdateAsync(
        MainWindowViewModel viewModel)
    {
        var release = await LauncherSelfUpdater.CheckAsync(viewModel.Version);
        if (release is null)
        {
            return;
        }

        pendingLauncherUpdate_ = release;
        viewModel.OfferLauncherUpdate(release.Version.Value);
    }

    private async Task InstallLauncherUpdateAsync(
        MainWindowViewModel viewModel)
    {
        if (pendingLauncherUpdate_ is not { } release)
        {
            return;
        }

        pendingLauncherUpdate_ = null;
        viewModel.BeginLauncherUpdate(release.Version.Value);
        try
        {
            await LauncherSelfUpdater.StartUpdateAsync(
                release,
                activationArgument_,
                new Progress<UpdateProgress>(viewModel.ReportUpdateProgress));
            Shutdown();
        }
        catch (Exception exception)
        {
            viewModel.ReportLauncherUpdateFailure(exception.Message);
        }
    }
}
