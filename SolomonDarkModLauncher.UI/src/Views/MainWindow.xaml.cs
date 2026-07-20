using System.Windows;
using System.Windows.Input;
using SolomonDarkModLauncher.UI.ViewModels;

namespace SolomonDarkModLauncher.UI.Views;

public partial class MainWindow : Window
{
    public MainWindow()
    {
        InitializeComponent();

        StateChanged += (_, _) =>
        {
            MaximizeButton.Content = WindowState == WindowState.Maximized ? "\u2750" : "\u25A1";
        };
    }

    private void MinimizeButton_Click(object sender, RoutedEventArgs e)
    {
        WindowState = WindowState.Minimized;
    }

    private void MaximizeButton_Click(object sender, RoutedEventArgs e)
    {
        WindowState = WindowState == WindowState.Maximized
            ? WindowState.Normal
            : WindowState.Maximized;
    }

    private void CloseButton_Click(object sender, RoutedEventArgs e)
    {
        Close();
    }

    private void HostSetupCreate_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not MainWindowViewModel viewModel)
        {
            return;
        }

        viewModel.ConfirmHostSetup();
    }

    private void HostSetupCancel_Click(object sender, RoutedEventArgs e)
    {
        CancelHostSetup();
    }

    private void HostSetupScrim_MouseLeftButtonDown(object sender, MouseButtonEventArgs e)
    {
        CancelHostSetup();
    }

    private void CancelHostSetup()
    {
        if (DataContext is MainWindowViewModel viewModel)
        {
            viewModel.CancelHostSetup();
        }
    }

    private void HowToPlayClose_Click(object sender, RoutedEventArgs e)
    {
        CloseHowToPlay();
    }

    private void HowToPlayScrim_MouseLeftButtonDown(object sender, MouseButtonEventArgs e)
    {
        CloseHowToPlay();
    }

    private void CloseHowToPlay()
    {
        if (DataContext is MainWindowViewModel viewModel)
        {
            viewModel.CloseHowToPlay();
        }
    }

    private void TitleBar_MouseLeftButtonDown(object sender, MouseButtonEventArgs e)
    {
        if (e.ClickCount == 2)
        {
            WindowState = WindowState == WindowState.Maximized
                ? WindowState.Normal
                : WindowState.Maximized;
            return;
        }

        DragMove();
    }
}
