using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using SolomonDarkModLauncher.UI.Infrastructure;
using SolomonDarkModLauncher.UI.ViewModels.ModSettings;

namespace SolomonDarkModLauncher.UI.Views;

public partial class ModSettingsWindow : Window
{
    private readonly ModSettingsDialogViewModel viewModel_;

    internal ModSettingsWindow(ModSettingsDialogViewModel viewModel)
    {
        viewModel_ = viewModel;
        DataContext = viewModel;
        InitializeComponent();
    }

    protected override void OnPreviewKeyDown(KeyEventArgs e)
    {
        Key key = e.Key == Key.System ? e.SystemKey : e.Key;

        if (key is Key.Escape && viewModel_.TryHandleCaptureKey(null, isEscape: true, isClear: false))
        {
            e.Handled = true;
            return;
        }

        if (key is Key.Delete or Key.Back && viewModel_.TryHandleCaptureKey(null, isEscape: false, isClear: true))
        {
            e.Handled = true;
            return;
        }

        string? canonical = CanonicalKeys.FromKey(key);
        if (canonical is not null && viewModel_.TryHandleCaptureKey(canonical, isEscape: false, isClear: false))
        {
            e.Handled = true;
            return;
        }

        base.OnPreviewKeyDown(e);
    }

    protected override void OnPreviewMouseDown(MouseButtonEventArgs e)
    {
        string? canonical = CanonicalKeys.FromMouseButton(e.ChangedButton);
        if (canonical is not null && viewModel_.TryHandleCaptureKey(canonical, isEscape: false, isClear: false))
        {
            e.Handled = true;
            return;
        }

        base.OnPreviewMouseDown(e);
    }

    private void OnActionButtonClick(object sender, RoutedEventArgs e)
    {
        if ((sender as Button)?.DataContext is not ActionSettingViewModel action)
        {
            return;
        }

        if (action.Confirm)
        {
            MessageBoxResult result = MessageBox.Show(
                this,
                $"Run \"{action.Label}\" now?",
                action.Label,
                MessageBoxButton.YesNo,
                MessageBoxImage.Question);
            if (result != MessageBoxResult.Yes)
            {
                return;
            }
        }

        if (action.InvokeCommand.CanExecute(null))
        {
            action.InvokeCommand.Execute(null);
        }
    }

    private void OnResetClick(object sender, RoutedEventArgs e)
    {
        MessageBoxResult result = MessageBox.Show(
            this,
            "Reset every setting in this dialog to its default value?",
            "Reset to defaults",
            MessageBoxButton.YesNo,
            MessageBoxImage.Question);
        if (result == MessageBoxResult.Yes)
        {
            viewModel_.ResetCommand.Execute(null);
        }
    }

    private void OnCloseClick(object sender, RoutedEventArgs e)
    {
        Close();
    }

    protected override void OnClosing(System.ComponentModel.CancelEventArgs e)
    {
        if (viewModel_.AllEntries.Any(entry => entry.IsDirty))
        {
            MessageBoxResult result = MessageBox.Show(
                this,
                "Discard unsaved setting changes?",
                "Unsaved changes",
                MessageBoxButton.YesNo,
                MessageBoxImage.Warning);
            if (result != MessageBoxResult.Yes)
            {
                e.Cancel = true;
                return;
            }
        }

        base.OnClosing(e);
    }
}
