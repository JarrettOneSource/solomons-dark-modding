using System.Collections.ObjectModel;
using System.Diagnostics;
using System.Net.Http;
using System.Text.Json;
using System.Windows;
using Microsoft.Win32;
using SolomonDarkModLauncher.UI.Infrastructure;

namespace SolomonDarkModLauncher.UI.ViewModels;

internal sealed class SaveManagerViewModel : ViewModelBase
{
    private readonly LocalSaveCatalog catalog_;
    private readonly CloudSaveClient cloud_;
    private readonly string directoryUrl_;
    private readonly Action activeSaveChanged_;
    private CloudSaveAccountState? accountState_;
    private SaveSlotViewModel? selectedSave_;
    private string selectedName_ = string.Empty;
    private string accountStatus_ = "Checking the active Steam account…";
    private string errorText_ = string.Empty;
    private bool isBusy_;

    public SaveManagerViewModel(
        LocalSaveCatalog catalog,
        CloudSaveClient cloud,
        string directoryUrl,
        Action activeSaveChanged)
    {
        catalog_ = catalog;
        cloud_ = cloud;
        directoryUrl_ = directoryUrl;
        activeSaveChanged_ = activeSaveChanged;

        UseSelectedCommand = new RelayCommand(_ => UseSelected(), _ => CanMutate());
        RenameCommand = new RelayCommand(_ => Rename(), _ => CanRename());
        ImportCommand = new RelayCommand(_ => Import(), _ => CanMutate());
        RestoreCommand = new RelayCommand(_ => _ = RestoreAsync(), _ => CanRestore());
        OpenFolderCommand = new RelayCommand(_ => OpenFolder(), _ => SelectedSave is not null);
        OpenAccountCommand = new RelayCommand(_ => OpenAccount());
        RefreshCloudCommand = new RelayCommand(
            _ => _ = RefreshCloudAsync(forceRefresh: true),
            _ => !IsBusy);
        CloseCommand = new RelayCommand(_ => RequestClose?.Invoke(this, EventArgs.Empty));

        ReloadSlots(catalog_.ActiveSlot);
        _ = RefreshCloudAsync(forceRefresh: false);
    }

    public event EventHandler? RequestClose;

    public ObservableCollection<SaveSlotViewModel> Saves { get; } = [];

    public SaveSlotViewModel? SelectedSave
    {
        get => selectedSave_;
        set
        {
            if (SetProperty(ref selectedSave_, value))
            {
                SelectedName = value?.Name ?? string.Empty;
                RaiseCommandStates();
            }
        }
    }

    public string SelectedName
    {
        get => selectedName_;
        set
        {
            if (SetProperty(ref selectedName_, value))
            {
                RenameCommand.RaiseCanExecuteChanged();
            }
        }
    }

    public string AccountStatus
    {
        get => accountStatus_;
        private set => SetProperty(ref accountStatus_, value);
    }

    public string ErrorText
    {
        get => errorText_;
        private set
        {
            if (SetProperty(ref errorText_, value))
            {
                OnPropertyChanged(nameof(HasError));
            }
        }
    }

    public bool HasError => !string.IsNullOrWhiteSpace(ErrorText);

    public bool IsBusy
    {
        get => isBusy_;
        private set
        {
            if (SetProperty(ref isBusy_, value))
            {
                RaiseCommandStates();
            }
        }
    }

    public bool IsLinked => accountState_?.LinkedAccount is not null;

    public string AccountButtonText => IsLinked ? "Website Account" : "Link Account";

    public RelayCommand UseSelectedCommand { get; }
    public RelayCommand RenameCommand { get; }
    public RelayCommand ImportCommand { get; }
    public RelayCommand RestoreCommand { get; }
    public RelayCommand OpenFolderCommand { get; }
    public RelayCommand OpenAccountCommand { get; }
    public RelayCommand RefreshCloudCommand { get; }
    public RelayCommand CloseCommand { get; }

    private async Task RefreshCloudAsync(bool forceRefresh)
    {
        if (IsBusy)
        {
            return;
        }
        IsBusy = true;
        ErrorText = string.Empty;
        AccountStatus = "Checking the active Steam account…";
        try
        {
            accountState_ = await cloud_.GetAccountStateAsync(
                directoryUrl_,
                forceRefresh);
            AccountStatus = accountState_.LinkedAccount is { } account
                ? $"Cloud backup enabled for {account.Username}."
                : "Cloud backup is off. Link this Steam account on the website.";
            OnPropertyChanged(nameof(IsLinked));
            OnPropertyChanged(nameof(AccountButtonText));
            ReloadSlots(SelectedSave?.Slot ?? catalog_.ActiveSlot);
        }
        catch (Exception exception) when (
            exception is IOException or
            InvalidOperationException or
            HttpRequestException or
            JsonException or
            TaskCanceledException or
            System.ComponentModel.Win32Exception)
        {
            accountState_ = null;
            AccountStatus = "Cloud backup is unavailable; local saves still work.";
            ErrorText = exception.Message;
            ReloadSlots(SelectedSave?.Slot ?? catalog_.ActiveSlot);
        }
        finally
        {
            IsBusy = false;
        }
    }

    private void UseSelected()
    {
        if (SelectedSave is not { } selected)
        {
            return;
        }
        catalog_.Select(selected.Slot);
        ReloadSlots(selected.Slot);
        activeSaveChanged_();
    }

    private void Rename()
    {
        if (SelectedSave is not { } selected)
        {
            return;
        }
        try
        {
            catalog_.Rename(selected.Slot, SelectedName);
            ErrorText = string.Empty;
            ReloadSlots(selected.Slot);
            activeSaveChanged_();
        }
        catch (Exception exception) when (
            exception is IOException or InvalidOperationException or UnauthorizedAccessException)
        {
            ErrorText = exception.Message;
        }
    }

    private void Import()
    {
        if (SelectedSave is not { } selected)
        {
            return;
        }
        var dialog = new OpenFolderDialog
        {
            Title = "Select a savegames folder containing the solomondark directory",
            Multiselect = false
        };
        if (dialog.ShowDialog() != true)
        {
            return;
        }
        if (selected.HasLocalData &&
            MessageBox.Show(
                "Importing replaces this local save slot. Continue?",
                "Import Save",
                MessageBoxButton.YesNo,
                MessageBoxImage.Warning) != MessageBoxResult.Yes)
        {
            return;
        }

        try
        {
            catalog_.Import(selected.Slot, dialog.FolderName);
            ErrorText = string.Empty;
            ReloadSlots(selected.Slot);
            activeSaveChanged_();
        }
        catch (Exception exception) when (
            exception is IOException or
            InvalidDataException or
            InvalidOperationException or
            UnauthorizedAccessException)
        {
            ErrorText = exception.Message;
        }
    }

    private async Task RestoreAsync()
    {
        if (SelectedSave is not { } selected || !selected.HasCloudBackup)
        {
            return;
        }
        if (selected.HasLocalData &&
            MessageBox.Show(
                "Restoring replaces this local save slot with its cloud backup. Continue?",
                "Restore Cloud Save",
                MessageBoxButton.YesNo,
                MessageBoxImage.Warning) != MessageBoxResult.Yes)
        {
            return;
        }

        IsBusy = true;
        ErrorText = string.Empty;
        try
        {
            await cloud_.RestoreAsync(directoryUrl_, selected.Slot);
            ReloadSlots(selected.Slot);
            activeSaveChanged_();
        }
        catch (Exception exception) when (
            exception is IOException or
            InvalidDataException or
            InvalidOperationException or
            HttpRequestException or
            JsonException or
            UnauthorizedAccessException or
            TaskCanceledException or
            System.ComponentModel.Win32Exception)
        {
            ErrorText = exception.Message;
        }
        finally
        {
            IsBusy = false;
        }
    }

    private void OpenFolder()
    {
        if (SelectedSave is not { } selected)
        {
            return;
        }
        try
        {
            Process.Start(new ProcessStartInfo(selected.Local.SavegamesRootPath)
            {
                UseShellExecute = true
            });
            ErrorText = string.Empty;
        }
        catch (Exception exception) when (
            exception is InvalidOperationException or
            System.ComponentModel.Win32Exception)
        {
            ErrorText = $"Could not open the save folder: {exception.Message}";
        }
    }

    private void OpenAccount()
    {
        try
        {
            Process.Start(new ProcessStartInfo($"{directoryUrl_.TrimEnd('/')}/account")
            {
                UseShellExecute = true
            });
            AccountStatus =
                "Link Steam on the website, then return here and click Refresh Cloud.";
            ErrorText = string.Empty;
        }
        catch (Exception exception) when (
            exception is InvalidOperationException or
            System.ComponentModel.Win32Exception)
        {
            ErrorText = $"Could not open the website account page: {exception.Message}";
        }
    }

    private void ReloadSlots(int selectedSlot)
    {
        var remoteBySlot = (accountState_?.Saves ?? [])
            .ToDictionary(save => save.Slot);
        Saves.Clear();
        foreach (var local in catalog_.List())
        {
            remoteBySlot.TryGetValue(local.Slot, out var remote);
            Saves.Add(new SaveSlotViewModel(
                local,
                remote,
                local.Slot == catalog_.ActiveSlot));
        }
        SelectedSave = Saves.Single(save => save.Slot == selectedSlot);
    }

    private bool CanMutate() => !IsBusy && SelectedSave is not null;

    private bool CanRename() =>
        CanMutate() &&
        !string.IsNullOrWhiteSpace(SelectedName) &&
        SelectedName.Trim().Length <= 40;

    private bool CanRestore() =>
        CanMutate() && IsLinked && SelectedSave?.HasCloudBackup == true;

    private void RaiseCommandStates()
    {
        UseSelectedCommand.RaiseCanExecuteChanged();
        RenameCommand.RaiseCanExecuteChanged();
        ImportCommand.RaiseCanExecuteChanged();
        RestoreCommand.RaiseCanExecuteChanged();
        OpenFolderCommand.RaiseCanExecuteChanged();
        RefreshCloudCommand.RaiseCanExecuteChanged();
    }
}
