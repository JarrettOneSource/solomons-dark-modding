using System.Windows;
using SolomonDarkModLauncher.UI.Infrastructure;
using SolomonDarkModLauncher.UI.ViewModels;
using SolomonDarkModLauncher.UI.Views;

namespace SolomonDarkModLauncher.UI;

public partial class App : Application
{
    private LauncherActivationBroker? activationBroker_;

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

        MainWindow = window;
        window.Show();

        activationBroker_.StartListening(argument =>
            _ = Dispatcher.InvokeAsync(() =>
                Activate(window, viewModel, argument)));
        Activate(window, viewModel, activationArgument);
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
        if (!LauncherJoinUri.TryParse(argument, out var lobbyId))
        {
            MessageBox.Show(
                window,
                "This lobby link is not valid.",
                "Solomon Dark Revived",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
            return;
        }

        viewModel.QueueLobbyJoin(lobbyId);
    }
}
