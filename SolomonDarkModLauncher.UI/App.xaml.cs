using System.Windows;
using SolomonDarkModLauncher.UI.Infrastructure;
using SolomonDarkModLauncher.UI.ViewModels;
using SolomonDarkModLauncher.UI.Views;

namespace SolomonDarkModLauncher.UI;

public partial class App : Application
{
    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);

        var client = new LauncherUiCommandClient();
        var viewModel = new MainWindowViewModel(client);
        var window = new MainWindow
        {
            DataContext = viewModel
        };

        MainWindow = window;
        window.Show();
    }
}
