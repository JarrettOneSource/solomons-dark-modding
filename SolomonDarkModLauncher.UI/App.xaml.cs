using System.Windows;
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

        if (e.Args.Length > 1)
        {
            MessageBox.Show(
                "The launcher received too many startup arguments.",
                "Solomon Dark Revived",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
            Shutdown(2);
            return;
        }

        activationBroker_ = new LauncherActivationBroker();
        var activationArgument = e.Args.Length == 1 ? e.Args[0] : string.Empty;
        activationArgument_ = activationArgument;
        if (!activationBroker_.IsPrimary)
        {
            if (!activationBroker_.ForwardActivation(activationArgument))
            {
                MessageBox.Show(
                    "The open launcher did not accept the lobby link. Close it and try again.",
                    "Solomon Dark Revived",
                    MessageBoxButton.OK,
                    MessageBoxImage.Error);
            }
            Shutdown();
            return;
        }

        try
        {
            LauncherProtocolRegistration.RegisterCurrentExecutable();
        }
        catch (Exception ex) when (ex is IOException or
                                   UnauthorizedAccessException or
                                   InvalidOperationException)
        {
            MessageBox.Show(
                ex.Message,
                "Solomon Dark Revived",
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
        _ = CheckForLauncherUpdateAsync(viewModel);
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
        if (!LauncherJoinUri.TryParse(argument, out var activation))
        {
            MessageBox.Show(
                window,
                "This lobby link is not valid.",
                "Solomon Dark Revived",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
            return;
        }

        viewModel.QueueWebsiteLobbyJoin(activation);
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
