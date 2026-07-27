using System.Windows;
using SolomonDarkModLauncher.UI.ViewModels;

namespace SolomonDarkModLauncher.UI.Views;

internal partial class LobbyRosterPreviewWindow : Window
{
    internal LobbyRosterPreviewWindow(LobbyRosterPreviewViewModel viewModel)
    {
        InitializeComponent();
        DataContext = viewModel;
    }
}
