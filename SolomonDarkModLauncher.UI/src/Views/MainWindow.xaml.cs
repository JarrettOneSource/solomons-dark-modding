using System.ComponentModel;
using System.Windows;
using System.Windows.Input;
using SolomonDarkModLauncher.UI.ViewModels;

namespace SolomonDarkModLauncher.UI.Views;

public partial class MainWindow : Window
{
    public MainWindow()
    {
        InitializeComponent();
        FitToWorkingArea(SystemParameters.WorkArea);

        StateChanged += (_, _) =>
        {
            MaximizeButton.Content = WindowState == WindowState.Maximized ? "\u2750" : "\u25A1";
        };
        Activated += (_, _) =>
        {
            if (DataContext is MainWindowViewModel viewModel)
            {
                viewModel.RefreshCloudAccountAfterActivation();
            }
        };
        Closing += MainWindow_Closing;
    }

    private void FitToWorkingArea(Rect workingArea)
    {
        const double screenMargin = 16.0;
        const double designMinimumWidth = 560.0;
        const double designMinimumHeight = 480.0;

        if (workingArea.Width <= 0.0 || workingArea.Height <= 0.0)
        {
            return;
        }

        var fittedWidth = Math.Min(Width, Math.Max(1.0, workingArea.Width - screenMargin));
        var fittedHeight = Math.Min(Height, Math.Max(1.0, workingArea.Height - screenMargin));
        MinWidth = Math.Min(designMinimumWidth, fittedWidth);
        MinHeight = Math.Min(designMinimumHeight, fittedHeight);
        MaxWidth = workingArea.Width;
        MaxHeight = workingArea.Height;
        Width = fittedWidth;
        Height = fittedHeight;
        Left = workingArea.Left + ((workingArea.Width - fittedWidth) / 2.0);
        Top = workingArea.Top + ((workingArea.Height - fittedHeight) / 2.0);
        WindowStartupLocation = WindowStartupLocation.Manual;
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

    private void MainWindow_Closing(object? sender, CancelEventArgs e)
    {
        if (DataContext is not MainWindowViewModel viewModel ||
            viewModel.CanCloseLauncher())
        {
            return;
        }
        e.Cancel = true;
        WindowState = WindowState.Minimized;
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
