using System.Windows;
using SolomonDarkModLauncher.UI.ViewModels;

namespace SolomonDarkModLauncher.UI.Views;

public partial class SaveManagerWindow : Window
{
    internal SaveManagerWindow(SaveManagerViewModel viewModel)
    {
        InitializeComponent();
        DataContext = viewModel;
        viewModel.RequestClose += OnRequestClose;
        Closed += (_, _) => viewModel.RequestClose -= OnRequestClose;
    }

    private void OnRequestClose(object? sender, EventArgs args)
    {
        DialogResult = true;
        Close();
    }
}
