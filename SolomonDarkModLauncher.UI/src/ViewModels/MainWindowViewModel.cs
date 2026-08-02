using System.Collections.ObjectModel;
using System.Diagnostics;
using System.Net.Http;
using System.Reflection;
using System.Text;
using System.Text.Json;
using System.Windows;
using SolomonDarkModding.Updates;
using SolomonDarkModLauncher.ModSettings;
using SolomonDarkModLauncher.UI.Infrastructure;
using SolomonDarkModLauncher.UI.ViewModels.ModSettings;
using SolomonDarkModLauncher.UI.Views;

namespace SolomonDarkModLauncher.UI.ViewModels;

internal sealed class MainWindowViewModel : ViewModelBase, IDisposable
{
    private readonly LauncherUiCommandClient client_;
    private readonly SteamWebsiteSessionClient steamWebsiteSessionClient_;
    private readonly CrashReportSubmissionClient crashReportSubmissionClient_;
    private readonly CloudSaveClient cloudSaveClient_;
    private readonly CloudSaveBackupCoordinator cloudSaveBackupCoordinator_;
    private readonly DiagnosticLogUploader diagnosticLogUploader_;
    private readonly SteamInviteListenerClient steamInviteListener_ = new();
    private readonly SteamLobbySessionClient steamLobbySession_ = new();
    private readonly LobbyLaunchState lobbyLaunchState_ = new();
    private readonly StringBuilder transcriptBuilder_ = new();
    private readonly CancellationTokenSource lifetimeCancellation_ = new();
    private LauncherCliResponse? lastResponse_;
    private bool isBusy_;
    private bool hasError_;
    private string errorMessage_ = string.Empty;
    private string statusText_ = "The launcher starts.";
    private bool isUpdateProgressVisible_;
    private string updateStatusText_ = string.Empty;
    private string updateProgressDetailText_ = string.Empty;
    private double updateProgressValue_;
    private bool isUpdateProgressError_;
    private bool isUpdateProgressComplete_;
    private string modSummaryText_ = string.Empty;
    private string commandPreviewText_ = string.Empty;
    private string transcriptText_ = string.Empty;
    private string instanceName_;
    private bool debugUiEnabled_;
    private bool showStockTutorial_;
    private bool disableAudio_;
    private bool headless_;
    private string lobbyId_;
    private string gameDirectory_;
    private bool isGameReady_;
    private CancellationTokenSource? steamSessionMonitorCancellation_;
    private bool isInLobby_;
    private string lobbyTitleText_ = string.Empty;
    private string lobbyIdText_ = string.Empty;
    private string lobbyPlayersLabel_ = string.Empty;
    private string lobbyBoneyardText_ = string.Empty;
    private string lobbyConnectionDetailsText_ = string.Empty;
    private string lobbyMembersSignature_ = string.Empty;
    private string directoryUrl_;
    private bool isHostSetupOpen_;
    private bool isHowToPlayOpen_;
    private bool hostPrivacyFriends_ = true;
    private string hostPlayerCountText_ = "4";
    private bool hostPrivacyPublic_;
    private ulong? pendingLobbyJoinId_;
    private int activeGameProcessId_;
    private CrashReportCapture? pendingCrashReport_;
    private bool isCrashPromptOpen_;
    private bool isCrashSubmitting_;
    private string crashReportMessage_ = string.Empty;
    private string crashSubmissionError_ = string.Empty;
    private string activeSaveName_ = string.Empty;
    private string activeSaveStatus_ = string.Empty;
    private string cloudAccountStatus_ = "Checking Steam link…";
    private bool isCloudLinked_;
    private string linkedAccountName_ = string.Empty;
    private string steamIdText_ = string.Empty;
    private DateTimeOffset lastCloudAccountRefreshUtc_;
    private CloudSaveGameSession? activeSaveSession_;
    private bool isLauncherUpdatePromptOpen_;
    private string availableLauncherVersion_ = string.Empty;
    private bool isSettingsOpen_;
    private bool isAccountBusy_;
    private bool isSendingLogs_;
    private string diagnosticsStatusText_ =
        "Send Logs uploads launcher and loader logs to private website storage.";
    private bool isModDownloadPromptOpen_;
    private string modDownloadPromptText_ = string.Empty;
    private string modDownloadPromptTitle_ = "This lobby uses mods";
    private string modDownloadPromptNote_ =
        "Downloads come from the website mod directory. Your own mod folders are not changed; the host's mod set is only used for this session.";
    private string modDownloadConfirmText_ = "Yes";
    private string modDownloadDeclineText_ = "No";
    private string? consentedJoinStatusText_;
    private LauncherInstallModActivation? pendingWebsiteModInstall_;
    private IReadOnlyList<string>? pendingLobbyMods_;
    private bool isJoiningLobby_;
    private bool launcherCloseStarted_;
    private string connectProgressText_ = string.Empty;
    private string connectProgressDetailText_ = string.Empty;
    private double connectProgressPercent_;
    private bool isConnectProgressVisible_;
    private bool isConnectProgressError_;
    private bool connectProgressCompleted_;
    private int connectProgressGeneration_;

    public MainWindowViewModel(LauncherUiCommandClient client)
    {
        client_ = client;
        steamWebsiteSessionClient_ = new SteamWebsiteSessionClient();
        crashReportSubmissionClient_ = new CrashReportSubmissionClient(
            steamWebsiteSessionClient_);
        cloudSaveClient_ = new CloudSaveClient(
            steamWebsiteSessionClient_,
            client_.SaveCatalog);
        cloudSaveBackupCoordinator_ = new CloudSaveBackupCoordinator(
            client_.SaveCatalog,
            cloudSaveClient_);
        diagnosticLogUploader_ = new DiagnosticLogUploader(steamWebsiteSessionClient_);
        instanceName_ = client.InstanceName;
        debugUiEnabled_ = client.DebugUiEnabled;
        showStockTutorial_ = client.ShowStockTutorial;
        disableAudio_ = client.DisableAudio;
        headless_ = client.Headless;
        lobbyId_ = client.LobbyId;
        gameDirectory_ = client.GameDirectory;
        directoryUrl_ = client.DirectoryUrl;

        RefreshCommand = new RelayCommand(_ => _ = RefreshAsync(), _ => CanInteract());
        HowToPlayCommand = new RelayCommand(_ => IsHowToPlayOpen = true);
        HostSteamCommand = new RelayCommand(
            _ =>
            {
                if (IsInLobby)
                {
                    _ = LeaveLiveSessionAsync();
                }
                else
                {
                    OpenHostSetup();
                }
            },
            _ => IsInLobby ? !IsBusy : CanStartNewGame());
        JoinSteamCommand = new RelayCommand(
            _ => ExecuteLobbyPrimaryAction(),
            _ => CanJoinLobbyId());
        LeaveLobbyCommand = new RelayCommand(
            _ => LeaveLobby(),
            _ => CanLeaveLobby);
        LaunchSinglePlayerCommand = new RelayCommand(
            _ => _ = ExecuteActionAsync(
                LauncherUiCommandMode.LaunchSinglePlayer,
                "The launcher starts the game."),
            _ => CanStartNewGame());
        StageCommand = new RelayCommand(_ => _ = ExecuteActionAsync(LauncherUiCommandMode.Stage, "The launcher prepares the mods."), _ => CanLaunch());
        ApplyInstanceCommand = new RelayCommand(_ => _ = ApplyInstanceAsync(), _ => CanInteract());
        ChooseGameFolderCommand = new RelayCommand(_ => ChooseGameFolder(), _ => CanInteract());
        OpenModsFolderCommand = new RelayCommand(_ => OpenFolder(lastResponse_?.Configuration?.ModsRoot), _ => CanOpenFolder(lastResponse_?.Configuration?.ModsRoot));
        OpenStageFolderCommand = new RelayCommand(_ => OpenFolder(lastResponse_?.Configuration?.StageRoot), _ => CanOpenFolder(lastResponse_?.Configuration?.StageRoot));
        OpenProfileFolderCommand = new RelayCommand(_ => OpenFolder(lastResponse_?.Configuration?.ProfileRoot), _ => CanOpenFolder(lastResponse_?.Configuration?.ProfileRoot));
        OpenGameFolderCommand = new RelayCommand(_ => OpenFolder(GameDirectory), _ => CanOpenFolder(GameDirectory));
        ManageSavesCommand = new RelayCommand(_ => OpenSaveManager(), _ => CanManageSaves());
        OpenWebsiteAccountCommand = new RelayCommand(_ => OpenWebsiteAccount());
        OpenSettingsCommand = new RelayCommand(
            _ => OpenSettings(),
            _ => !IsCrashPromptOpen && !IsModDownloadPromptOpen);
        RefreshAccountCommand = new RelayCommand(
            _ => _ = RefreshCloudAccountAsync(forceRefresh: true),
            _ => !isAccountBusy_);
        UnlinkAccountCommand = new RelayCommand(
            _ => _ = UnlinkAccountAsync(),
            _ => IsCloudLinked && !isAccountBusy_);
        SendLogsCommand = new RelayCommand(
            _ => _ = SendLogsAsync(),
            _ => !IsSendingLogs);
        ConfirmModDownloadCommand = new RelayCommand(
            _ => ConfirmModDownload(),
            _ => IsModDownloadPromptOpen && !IsBusy);
        DeclineModDownloadCommand = new RelayCommand(
            _ => DeclineModDownload(),
            _ => IsModDownloadPromptOpen && !IsBusy);
        SubmitCrashReportCommand = new RelayCommand(
            _ => _ = SubmitCrashReportAsync(),
            _ => IsCrashPromptOpen && !IsCrashSubmitting);
        DismissCrashReportCommand = new RelayCommand(
            _ => DismissCrashReport(),
            _ => IsCrashPromptOpen && !IsCrashSubmitting);
        InstallLauncherUpdateCommand = new RelayCommand(
            _ => AcceptLauncherUpdate(),
            _ => IsLauncherUpdatePromptOpen && !IsBusy);
        DismissLauncherUpdateCommand = new RelayCommand(
            _ => DismissLauncherUpdate(),
            _ => IsLauncherUpdatePromptOpen && !IsBusy);

        steamInviteListener_.NotificationReceived += OnSteamInviteNotification;
        steamLobbySession_.NotificationReceived += OnSteamLobbySessionNotification;
        steamInviteListener_.Start();

        UpdateLaunchPreview();
        UpdateActiveSaveSummary();
        _ = RefreshCloudAccountAsync(forceRefresh: false);
        if (string.IsNullOrWhiteSpace(GameDirectory))
        {
            StatusText = "Select your game folder.";
        }
        else
        {
            _ = RefreshAsync();
        }
    }

    public ObservableCollection<ModItemViewModel> Mods { get; } = [];

    public ObservableCollection<LobbyMemberViewModel> LobbyMembers { get; } = [];

    public ObservableCollection<string> LobbySharedMods { get; } = [];

    public ObservableCollection<string> ModDownloadItems { get; } = [];

    public string Title => "Solomon Dark Revived";
    public string Version
    {
        get
        {
            var version = Assembly.GetEntryAssembly()?
                .GetCustomAttribute<AssemblyInformationalVersionAttribute>()?
                .InformationalVersion ?? "development";
            var metadataStart = version.IndexOf('+');
            return metadataStart < 0 ? version : version[..metadataStart];
        }
    }

    public bool IsBusy
    {
        get => isBusy_;
        private set
        {
            if (SetProperty(ref isBusy_, value))
            {
                OnPropertyChanged(nameof(HostButtonText));
                OnPropertyChanged(nameof(CanLeaveLobby));
                RaiseCommandStates();
            }
        }
    }

    public bool HasError
    {
        get => hasError_;
        private set => SetProperty(ref hasError_, value);
    }

    public string ErrorMessage
    {
        get => errorMessage_;
        private set => SetProperty(ref errorMessage_, value);
    }

    public string StatusText
    {
        get => statusText_;
        private set => SetProperty(ref statusText_, value);
    }

    public string ConnectProgressText
    {
        get => connectProgressText_;
        private set => SetProperty(ref connectProgressText_, value);
    }

    /// <summary>0–100 for the gold progress bar; derived from the loader's
    /// observed session phase, never from a timer.</summary>
    public double ConnectProgressPercent
    {
        get => connectProgressPercent_;
        private set => SetProperty(ref connectProgressPercent_, value);
    }

    public bool IsConnectProgressVisible
    {
        get => isConnectProgressVisible_;
        private set => SetProperty(ref isConnectProgressVisible_, value);
    }

    public bool IsConnectProgressError
    {
        get => isConnectProgressError_;
        private set => SetProperty(ref isConnectProgressError_, value);
    }

    public string ConnectProgressDetailText
    {
        get => connectProgressDetailText_;
        private set => SetProperty(ref connectProgressDetailText_, value);
    }

    public bool IsUpdateProgressVisible
    {
        get => isUpdateProgressVisible_;
        private set => SetProperty(ref isUpdateProgressVisible_, value);
    }

    public string UpdateStatusText
    {
        get => updateStatusText_;
        private set => SetProperty(ref updateStatusText_, value);
    }

    public string UpdateProgressDetailText
    {
        get => updateProgressDetailText_;
        private set => SetProperty(ref updateProgressDetailText_, value);
    }

    public double UpdateProgressValue
    {
        get => updateProgressValue_;
        private set => SetProperty(ref updateProgressValue_, value);
    }

    public bool IsUpdateProgressError
    {
        get => isUpdateProgressError_;
        private set => SetProperty(ref isUpdateProgressError_, value);
    }

    public bool IsUpdateProgressComplete
    {
        get => isUpdateProgressComplete_;
        private set => SetProperty(ref isUpdateProgressComplete_, value);
    }

    public bool IsInLobby
    {
        get => isInLobby_;
        private set
        {
            if (SetProperty(ref isInLobby_, value))
            {
                OnPropertyChanged(nameof(CanLeaveLobby));
                OnPropertyChanged(nameof(HostButtonText));
                HostSteamCommand.RaiseCanExecuteChanged();
            }
        }
    }

    public string LobbyTitleText
    {
        get => lobbyTitleText_;
        private set => SetProperty(ref lobbyTitleText_, value);
    }

    public string LobbyIdText
    {
        get => lobbyIdText_;
        private set => SetProperty(ref lobbyIdText_, value);
    }

    public string LobbyPlayersLabel
    {
        get => lobbyPlayersLabel_;
        private set => SetProperty(ref lobbyPlayersLabel_, value);
    }

    public string LobbyBoneyardText
    {
        get => lobbyBoneyardText_;
        private set => SetProperty(ref lobbyBoneyardText_, value);
    }

    public string LobbyConnectionDetailsText
    {
        get => lobbyConnectionDetailsText_;
        private set => SetProperty(ref lobbyConnectionDetailsText_, value);
    }

    public bool IsHowToPlayOpen
    {
        get => isHowToPlayOpen_;
        private set => SetProperty(ref isHowToPlayOpen_, value);
    }

    public bool IsSettingsOpen
    {
        get => isSettingsOpen_;
        private set
        {
            if (SetProperty(ref isSettingsOpen_, value))
            {
                RaiseCommandStates();
            }
        }
    }

    public bool IsModDownloadPromptOpen
    {
        get => isModDownloadPromptOpen_;
        private set
        {
            if (SetProperty(ref isModDownloadPromptOpen_, value))
            {
                RaiseCommandStates();
            }
        }
    }

    public string ModDownloadPromptText
    {
        get => modDownloadPromptText_;
        private set => SetProperty(ref modDownloadPromptText_, value);
    }

    public string ModDownloadPromptTitle
    {
        get => modDownloadPromptTitle_;
        private set => SetProperty(ref modDownloadPromptTitle_, value);
    }

    public string ModDownloadPromptNote
    {
        get => modDownloadPromptNote_;
        private set => SetProperty(ref modDownloadPromptNote_, value);
    }

    public string ModDownloadConfirmText
    {
        get => modDownloadConfirmText_;
        private set => SetProperty(ref modDownloadConfirmText_, value);
    }

    public string ModDownloadDeclineText
    {
        get => modDownloadDeclineText_;
        private set => SetProperty(ref modDownloadDeclineText_, value);
    }

    public bool IsSendingLogs
    {
        get => isSendingLogs_;
        private set
        {
            if (SetProperty(ref isSendingLogs_, value))
            {
                OnPropertyChanged(nameof(SendLogsButtonText));
                RaiseCommandStates();
            }
        }
    }

    public string SendLogsButtonText => IsSendingLogs ? "Sending…" : "Send Logs to Cloud";

    public string DiagnosticsStatusText
    {
        get => diagnosticsStatusText_;
        private set => SetProperty(ref diagnosticsStatusText_, value);
    }

    public string LinkedAccountDetailText => IsCloudLinked
        ? $"{linkedAccountName_} · Steam {steamIdText_}"
        : string.IsNullOrWhiteSpace(steamIdText_)
            ? "No website account is linked."
            : $"Steam {steamIdText_} · no website account linked";

    public bool IsHostSetupOpen
    {
        get => isHostSetupOpen_;
        private set => SetProperty(ref isHostSetupOpen_, value);
    }

    public bool IsCrashPromptOpen
    {
        get => isCrashPromptOpen_;
        private set
        {
            if (SetProperty(ref isCrashPromptOpen_, value))
            {
                RaiseCommandStates();
            }
        }
    }

    public bool IsCrashSubmitting
    {
        get => isCrashSubmitting_;
        private set
        {
            if (SetProperty(ref isCrashSubmitting_, value))
            {
                OnPropertyChanged(nameof(CrashSubmitButtonText));
                RaiseCommandStates();
            }
        }
    }

    public string CrashReportMessage
    {
        get => crashReportMessage_;
        private set => SetProperty(ref crashReportMessage_, value);
    }

    public string CrashSubmissionError
    {
        get => crashSubmissionError_;
        private set
        {
            if (SetProperty(ref crashSubmissionError_, value))
            {
                OnPropertyChanged(nameof(HasCrashSubmissionError));
            }
        }
    }

    public bool HasCrashSubmissionError => !string.IsNullOrWhiteSpace(CrashSubmissionError);

    public string CrashSubmitButtonText => IsCrashSubmitting ? "Submitting…" : "Submit Logs";

    public bool IsLauncherUpdatePromptOpen
    {
        get => isLauncherUpdatePromptOpen_;
        private set
        {
            if (SetProperty(ref isLauncherUpdatePromptOpen_, value))
            {
                RaiseCommandStates();
            }
        }
    }

    public string AvailableLauncherVersion
    {
        get => availableLauncherVersion_;
        private set => SetProperty(ref availableLauncherVersion_, value);
    }

    public string HostPlayerCountText
    {
        get => hostPlayerCountText_;
        set => SetProperty(ref hostPlayerCountText_, value);
    }

    // Solomon Dark allocates exactly four gameplay player/progression slots.
    public int HostPlayerCount =>
        int.TryParse(hostPlayerCountText_.Trim(), out var count)
            ? count
            : 0;

    public bool HostPrivacyFriends
    {
        get => hostPrivacyFriends_;
        set
        {
            if (SetProperty(ref hostPrivacyFriends_, value) && value)
            {
                HostPrivacyPublic = false;
            }
        }
    }

    public bool HostPrivacyPublic
    {
        get => hostPrivacyPublic_;
        set
        {
            if (SetProperty(ref hostPrivacyPublic_, value) && value)
            {
                HostPrivacyFriends = false;
            }
        }
    }

    public string DirectoryUrl
    {
        get => directoryUrl_;
        set
        {
            if (!SetProperty(ref directoryUrl_, value))
            {
                return;
            }

            try
            {
                client_.UpdateDirectoryUrl(directoryUrl_);
            }
            catch (Exception ex)
            {
                SetError(ex.Message);
                return;
            }

            ClearError();
            if (directoryUrl_ != client_.DirectoryUrl)
            {
                directoryUrl_ = client_.DirectoryUrl;
                OnPropertyChanged();
            }
        }
    }

    public string ModSummaryText
    {
        get => modSummaryText_;
        private set => SetProperty(ref modSummaryText_, value);
    }

    public string CommandPreviewText
    {
        get => commandPreviewText_;
        private set => SetProperty(ref commandPreviewText_, value);
    }

    public string TranscriptText
    {
        get => transcriptText_;
        private set => SetProperty(ref transcriptText_, value);
    }

    public string InstanceName
    {
        get => instanceName_;
        set => SetProperty(ref instanceName_, value);
    }

    public bool DebugUiEnabled
    {
        get => debugUiEnabled_;
        set
        {
            if (SetProperty(ref debugUiEnabled_, value))
            {
                client_.UpdateDebugUiEnabled(value);
                UpdateLaunchPreview();
            }
        }
    }

    public bool ShowStockTutorial
    {
        get => showStockTutorial_;
        set
        {
            if (SetProperty(ref showStockTutorial_, value))
            {
                client_.UpdateShowStockTutorial(value);
                UpdateLaunchPreview();
            }
        }
    }

    public bool DisableAudio
    {
        get => disableAudio_;
        set
        {
            if (SetProperty(ref disableAudio_, value))
            {
                client_.UpdateDisableAudio(value);
                UpdateLaunchPreview();
            }
        }
    }

    public bool Headless
    {
        get => headless_;
        set
        {
            if (SetProperty(ref headless_, value))
            {
                client_.UpdateHeadless(value);
                UpdateLaunchPreview();
            }
        }
    }

    public string LobbyId
    {
        get => lobbyId_;
        set
        {
            if (SetProperty(ref lobbyId_, value))
            {
                client_.UpdateLobbyId(value);
                UpdateLaunchPreview();
                JoinSteamCommand.RaiseCanExecuteChanged();
            }
        }
    }

    public string HostButtonText =>
        IsBusy ? "Wait" : IsInLobby ? "Leave Lobby" : "Host Game";

    public string JoinGameButtonText => lobbyLaunchState_.PrimaryButtonText;

    public bool CanLeaveLobby =>
        lobbyLaunchState_.JoinedLobbyId.HasValue &&
        activeGameProcessId_ == 0 &&
        !IsBusy;

    public string ActiveSaveName
    {
        get => activeSaveName_;
        private set => SetProperty(ref activeSaveName_, value);
    }

    public string ActiveSaveStatus
    {
        get => activeSaveStatus_;
        private set => SetProperty(ref activeSaveStatus_, value);
    }

    public string CloudAccountStatus
    {
        get => cloudAccountStatus_;
        private set => SetProperty(ref cloudAccountStatus_, value);
    }

    public bool IsCloudLinked
    {
        get => isCloudLinked_;
        private set
        {
            if (SetProperty(ref isCloudLinked_, value))
            {
                OnPropertyChanged(nameof(AccountButtonText));
            }
        }
    }

    public string AccountButtonText => IsCloudLinked
        ? $"Account: {linkedAccountName_}"
        : "Link Account";

    public bool HasActiveGame => activeGameProcessId_ > 0;

    public string WorkspaceRoot => lastResponse_?.Configuration?.WorkspaceRoot ?? "(unresolved)";

    public string GameDirectory
    {
        get => gameDirectory_;
        private set
        {
            if (SetProperty(ref gameDirectory_, value))
            {
                OnPropertyChanged(nameof(GameDirectorySummary));
                OnPropertyChanged(nameof(HasGameDirectory));
            }
        }
    }

    public bool HasGameDirectory => !string.IsNullOrWhiteSpace(GameDirectory);

    public string GameDirectorySummary => string.IsNullOrWhiteSpace(GameDirectory)
        ? "Not set"
        : GameDirectory;

    public RelayCommand RefreshCommand { get; }
    public RelayCommand HowToPlayCommand { get; }
    public RelayCommand HostSteamCommand { get; }
    public RelayCommand JoinSteamCommand { get; }
    public RelayCommand LeaveLobbyCommand { get; }
    public RelayCommand LaunchSinglePlayerCommand { get; }
    public RelayCommand StageCommand { get; }
    public RelayCommand ApplyInstanceCommand { get; }
    public RelayCommand ChooseGameFolderCommand { get; }
    public RelayCommand OpenModsFolderCommand { get; }
    public RelayCommand OpenStageFolderCommand { get; }
    public RelayCommand OpenProfileFolderCommand { get; }
    public RelayCommand OpenGameFolderCommand { get; }
    public RelayCommand ManageSavesCommand { get; }
    public RelayCommand OpenWebsiteAccountCommand { get; }
    public RelayCommand OpenSettingsCommand { get; }
    public RelayCommand RefreshAccountCommand { get; }
    public RelayCommand UnlinkAccountCommand { get; }
    public RelayCommand SendLogsCommand { get; }
    public RelayCommand ConfirmModDownloadCommand { get; }
    public RelayCommand DeclineModDownloadCommand { get; }
    public RelayCommand SubmitCrashReportCommand { get; }
    public RelayCommand DismissCrashReportCommand { get; }
    public RelayCommand InstallLauncherUpdateCommand { get; }
    public RelayCommand DismissLauncherUpdateCommand { get; }

    public event EventHandler? LauncherUpdateAccepted;

    private bool CanInteractInSettings() =>
        !IsBusy &&
        !IsCrashPromptOpen &&
        !IsModDownloadPromptOpen &&
        !IsLauncherUpdatePromptOpen;

    private bool CanInteract() => CanInteractInSettings() && !IsSettingsOpen;

    private bool CanLaunch() =>
        CanInteract() && isGameReady_ && activeGameProcessId_ == 0;

    private bool CanStartNewGame() =>
        CanLaunch() &&
        !isJoiningLobby_ &&
        !lobbyLaunchState_.JoinedLobbyId.HasValue;

    private bool CanManageSaves() => CanInteractInSettings() && activeGameProcessId_ == 0;

    private bool CanJoinLobbyId() =>
        CanLaunch() &&
        !isJoiningLobby_ &&
        (lobbyLaunchState_.JoinedLobbyId.HasValue ||
         ulong.TryParse(LobbyId, out var lobbyId) && lobbyId != 0);

    private void ChooseGameFolder()
    {
        if (!LauncherShell.TrySelectFolder(
                "Select the Solomon Dark 0.72.5 folder that contains SolomonDark.exe",
                GameDirectory,
                AppContext.BaseDirectory,
                out var selectedPath))
        {
            return;
        }

        try
        {
            client_.UpdateGameDirectory(selectedPath);
        }
        catch (Exception ex)
        {
            SetError(ex.Message);
            return;
        }

        GameDirectory = client_.GameDirectory;
        isGameReady_ = false;
        RaiseCommandStates();
        _ = RefreshAsync();
    }

    private void OpenSaveManager()
    {
        var viewModel = new SaveManagerViewModel(
            client_.SaveCatalog,
            cloudSaveClient_,
            DirectoryUrl,
            () =>
            {
                UpdateActiveSaveSummary();
                UpdateLaunchPreview();
            });
        var window = new SaveManagerWindow(viewModel)
        {
            Owner = Application.Current.MainWindow
        };
        window.ShowDialog();
        UpdateActiveSaveSummary();
        UpdateLaunchPreview();
        _ = RefreshCloudAccountAsync(forceRefresh: true);
    }

    private void OpenWebsiteAccount()
    {
        if (!LauncherShell.TryOpenUri(
                $"{DirectoryUrl.TrimEnd('/')}/account"))
        {
            SetError("Couldn't open the account page.");
            return;
        }

        CloudAccountStatus =
            "Link Steam on the website, then return to the launcher.";
    }

    private void OpenSettings()
    {
        IsSettingsOpen = true;
        _ = RefreshCloudAccountAsync(forceRefresh: false);
    }

    public void CloseSettings()
    {
        IsSettingsOpen = false;
    }

    private async Task UnlinkAccountAsync()
    {
        if (isAccountBusy_)
        {
            return;
        }

        isAccountBusy_ = true;
        RaiseCommandStates();
        CloudAccountStatus = "Unlinking the Steam account…";
        try
        {
            await steamWebsiteSessionClient_.UnlinkAccountAsync(
                DirectoryUrl,
                lifetimeCancellation_.Token);
            CloudAccountStatus = "The Steam account was unlinked.";
        }
        catch (OperationCanceledException) when (lifetimeCancellation_.IsCancellationRequested)
        {
            return;
        }
        catch (Exception exception) when (
            exception is IOException or
            InvalidOperationException or
            HttpRequestException or
            JsonException or
            TaskCanceledException or
            System.ComponentModel.Win32Exception)
        {
            CloudAccountStatus = exception.Message;
        }
        finally
        {
            isAccountBusy_ = false;
            RaiseCommandStates();
        }

        await RefreshCloudAccountAsync(forceRefresh: true);
    }

    private async Task SendLogsAsync()
    {
        if (IsSendingLogs)
        {
            return;
        }

        IsSendingLogs = true;
        DiagnosticsStatusText = "Collecting and uploading logs…";
        try
        {
            var receipt = await diagnosticLogUploader_.SubmitAsync(
                lastResponse_,
                TranscriptText,
                Version,
                DirectoryUrl,
                lifetimeCancellation_.Token);
            DiagnosticsStatusText =
                $"Logs uploaded as {receipt.LogId} at {receipt.SubmittedAtUtc.LocalDateTime:g}.";
        }
        catch (OperationCanceledException) when (lifetimeCancellation_.IsCancellationRequested)
        {
        }
        catch (Exception exception) when (
            exception is IOException or
            UnauthorizedAccessException or
            InvalidDataException or
            InvalidOperationException or
            HttpRequestException or
            JsonException or
            TaskCanceledException or
            System.ComponentModel.Win32Exception)
        {
            DiagnosticsStatusText = $"The logs were not uploaded: {exception.Message}";
        }
        finally
        {
            IsSendingLogs = false;
        }
    }

    public void RefreshCloudAccountAfterActivation()
    {
        if (DateTimeOffset.UtcNow - lastCloudAccountRefreshUtc_ < TimeSpan.FromSeconds(10))
        {
            return;
        }
        _ = RefreshCloudAccountAsync(forceRefresh: true);
    }

    private async Task RefreshAsync()
    {
        await ExecuteUiCommandAsync(
            LauncherUiCommandMode.ListMods,
            statusText: "The launcher checks the mods.");
    }

    private async Task ApplyInstanceAsync()
    {
        try
        {
            client_.UpdateInstance(InstanceName);
        }
        catch (Exception ex)
        {
            SetError(ex.Message);
            return;
        }

        await ExecuteUiCommandAsync(
            LauncherUiCommandMode.ListMods,
            statusText: $"The launcher changes to instance '{InstanceName}'.");
    }

    private async Task ExecuteActionAsync(LauncherUiCommandMode mode, string statusText)
    {
        await ExecuteUiCommandAsync(mode, statusText);
    }

    private async Task<bool> ExecuteUiCommandAsync(
        LauncherUiCommandMode mode,
        string statusText,
        string? targetModId = null,
        LauncherHostOptions? hostOptions = null)
    {
        var launchesGame = LauncherUiCommandRouting.LaunchesGame(mode);
        if (launchesGame)
        {
            StopSteamInviteListener();
        }

        if (mode is LauncherUiCommandMode.HostSteam or
            LauncherUiCommandMode.PrepareSteamJoin or
            LauncherUiCommandMode.LaunchSinglePlayer or
            LauncherUiCommandMode.Stage)
        {
            StopSteamSessionMonitoring(
                clearStatus: true,
                preservePendingLobbyMods:
                    mode == LauncherUiCommandMode.PrepareSteamJoin);
        }
        else if (mode == LauncherUiCommandMode.LaunchSteamJoin)
        {
            StopSteamSessionMonitoring(clearStatus: false);
        }

        IsBusy = true;
        ClearUpdateProgress();
        StatusText = statusText;
        switch (mode)
        {
            case LauncherUiCommandMode.PrepareSteamJoin:
                ShowConnectProgress(
                    SessionConnectProgressMapper.PreparingLobby());
                break;
            case LauncherUiCommandMode.LaunchSteamJoin:
            case LauncherUiCommandMode.HostSteam:
                ShowConnectProgress(
                    SessionConnectProgressMapper.StagingGame());
                break;
        }
        CommandPreviewText = client_.BuildCommandPreview(mode, targetModId, hostOptions);
        LauncherUiInvocationResult invocation;
        try
        {
            var progress = new Progress<UpdateProgress>(ReportUpdateProgress);
            invocation = await client_.InvokeAsync(
                mode,
                targetModId,
                hostOptions,
                progress);
        }
        catch (Exception ex)
        {
            SetError(ex.Message);
            StatusText = "Command failed.";
            IsBusy = false;
            HideConnectProgress();
            if (launchesGame)
            {
                StartSteamInviteListener();
            }
            TryStartPendingLobbyJoin();
            return false;
        }

        AppendTranscript(invocation);

        if (!invocation.Succeeded || invocation.Response is null)
        {
            if (mode == LauncherUiCommandMode.ListMods)
            {
                isGameReady_ = false;
                RaiseCommandStates();
            }
            SetError(invocation.ErrorMessage ?? "The launcher command failed.");
            StatusText = "Command failed.";
            IsBusy = false;
            HideConnectProgress();
            if (launchesGame)
            {
                StartSteamInviteListener();
            }
            TryStartPendingLobbyJoin();
            return false;
        }

        var modUpdateError = invocation.Response.ModUpdate?.Error;
        var lobbySyncError = invocation.Response.LobbyModSync is
        {
            UsedWebsite: false,
            FallbackReason: { Length: > 0 } fallbackReason
        }
            ? fallbackReason
            : null;
        if (!string.IsNullOrWhiteSpace(modUpdateError))
        {
            SetError($"Mod update failed: {modUpdateError}");
            ReportUpdateProgress(new UpdateProgress(
                UpdateProgressPhase.Failed,
                $"Mod update failed: {modUpdateError}"));
        }
        else if (!string.IsNullOrWhiteSpace(lobbySyncError))
        {
            SetError($"Host mod sync failed: {lobbySyncError}");
            ReportUpdateProgress(new UpdateProgress(
                UpdateProgressPhase.Failed,
                $"Host mod sync failed: {lobbySyncError}"));
        }
        else
        {
            ClearError();
        }
        isGameReady_ = true;
        lastResponse_ = invocation.Response;
        UpdateFromResponse(invocation.Response);
        var multiplayer = invocation.Response.Launch?.MultiplayerSession;
        if (mode == LauncherUiCommandMode.HostSteam && multiplayer?.LobbyId > 0)
        {
            LobbyId = multiplayer.LobbyId.ToString();
        }
        if (mode == LauncherUiCommandMode.HostSteam)
        {
            pendingLobbyMods_ = invocation.Response.Mods
                .Where(mod => mod.Enabled)
                .Select(mod => $"{mod.Name} {mod.Version}")
                .ToArray();
        }
        if (mode is LauncherUiCommandMode.HostSteam or
                LauncherUiCommandMode.LaunchSteamJoin &&
            multiplayer is not null)
        {
            StartSteamSessionMonitoring(invocation.Response, multiplayer);
        }
        var processId = invocation.Response.Launch?.ProcessId ?? 0;
        if (launchesGame && processId > 0)
        {
            activeGameProcessId_ = processId;
            OnPropertyChanged(nameof(HasActiveGame));
            OnPropertyChanged(nameof(CanLeaveLobby));
            UpdateModSettingsInstance();
            RaiseCommandStates();
            try
            {
                activeSaveSession_ = cloudSaveBackupCoordinator_.Start(
                    invocation.Response,
                    DirectoryUrl,
                    OnCloudSaveBackupStatus);
            }
            catch (Exception exception) when (
                exception is IOException or InvalidOperationException)
            {
                SetError(exception.Message);
            }
            _ = MonitorGameProcessExitAsync(invocation.Response);
        }
        StatusText = mode switch
        {
            _ when !string.IsNullOrWhiteSpace(modUpdateError) =>
                "The mod update failed. Read the error message.",
            _ when !string.IsNullOrWhiteSpace(lobbySyncError) =>
                "Host mod sync failed. The launcher used your current mods.",
            LauncherUiCommandMode.ListMods when
                invocation.Response.ModUpdate?.UpdatedModCount > 0 =>
                invocation.Response.ModUpdate.UpdatedModCount == 1
                    ? "1 mod updated"
                    : $"{invocation.Response.ModUpdate.UpdatedModCount} mods updated",
            LauncherUiCommandMode.ListMods => "Ready",
            LauncherUiCommandMode.Stage => "Stage ready",
            LauncherUiCommandMode.LaunchSinglePlayer => "Game started",
            LauncherUiCommandMode.HostSteam => "Ready",
            LauncherUiCommandMode.PrepareSteamJoin =>
                invocation.Response.LobbyModSync is { DownloadedModCount: > 0 } sync
                    ? $"Downloaded {sync.DownloadedModCount} host " +
                      (sync.DownloadedModCount == 1 ? "mod" : "mods") +
                      " from the website."
                    : "Lobby prepared",
            LauncherUiCommandMode.LaunchSteamJoin => "Game started",
            LauncherUiCommandMode.EnableMod => "Ready",
            LauncherUiCommandMode.DisableMod => "Ready",
            _ => "Ready"
        };
        IsBusy = false;
        TryStartPendingLobbyJoin();
        return true;
    }

    private async Task MonitorGameProcessExitAsync(LauncherCliResponse response)
    {
        var processId = response.Launch?.ProcessId ?? 0;
        var cancellationToken = lifetimeCancellation_.Token;
        int? exitCode = null;
        try
        {
            using var process = Process.GetProcessById(processId);
            await process.WaitForExitAsync(cancellationToken);
            exitCode = process.ExitCode;
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            return;
        }
        catch (ArgumentException)
        {
        }
        catch (InvalidOperationException)
        {
        }

        try
        {
            await Task.Delay(200, cancellationToken);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            return;
        }

        LauncherCliMultiplayerSession? finalSessionStatus = null;
        if (!string.IsNullOrWhiteSpace(response.Stage?.StageRoot) &&
            !string.IsNullOrWhiteSpace(
                response.Launch?.LaunchToken))
        {
            finalSessionStatus =
                await LauncherMultiplayerSessionStatusReader.ReadAsync(
                    response.Stage.StageRoot,
                    response.Launch.LaunchToken,
                    cancellationToken);
        }

        string? saveCompletionError = null;
        var saveSession = activeSaveSession_;
        activeSaveSession_ = null;
        if (saveSession is not null)
        {
            try
            {
                await saveSession.CompleteAsync(cancellationToken);
            }
            catch (Exception exception) when (
                exception is IOException or
                UnauthorizedAccessException or
                InvalidDataException or
                InvalidOperationException or
                HttpRequestException or
                JsonException or
                TaskCanceledException)
            {
                saveCompletionError = exception.Message;
            }
            finally
            {
                await saveSession.DisposeAsync();
            }
        }

        var crashReport = CrashReportCapture.TryCreate(response, exitCode, Version);

        await Application.Current.Dispatcher.InvokeAsync(() =>
        {
            if (activeGameProcessId_ != processId)
            {
                return;
            }

            activeGameProcessId_ = 0;
            OnPropertyChanged(nameof(HasActiveGame));
            OnPropertyChanged(nameof(CanLeaveLobby));
            UpdateModSettingsInstance();
            ClearSteamSessionStatus();
            if (finalSessionStatus?.StatusText is
                "The host closed the lobby." or
                "The multiplayer host connection was lost.")
            {
                StatusText = finalSessionStatus.StatusText;
            }
            UpdateActiveSaveSummary();
            RaiseCommandStates();
            StartSteamInviteListener();
            if (!string.IsNullOrWhiteSpace(saveCompletionError))
            {
                SetError($"Save finalization needs attention: {saveCompletionError}");
                CloudAccountStatus =
                    "The launcher will retry cloud backup after the next save.";
            }
            if (crashReport is not null)
            {
                PresentCrashReport(crashReport);
            }
            TryStartPendingLobbyJoin();
        });
    }

    private void PresentCrashReport(CrashReportCapture crashReport)
    {
        pendingCrashReport_ = crashReport;
        CrashSubmissionError = string.Empty;
        var dumpText = crashReport.Metadata.MinidumpCount == 1
            ? "1 minidump"
            : $"{crashReport.Metadata.MinidumpCount} minidumps";
        CrashReportMessage =
            $"Solomon Dark crashed (exit code {crashReport.ExitCodeText}). " +
            $"Send a private report ({dumpText}, logs, and your enabled mods)? " +
            "It's tied to your Steam identity and only the developer can see it.";
        StatusText = "The game crashed.";
        IsCrashPromptOpen = true;

        if (Application.Current.MainWindow is { } window)
        {
            if (window.WindowState == WindowState.Minimized)
            {
                window.WindowState = WindowState.Normal;
            }
            window.Activate();
        }
    }

    private async Task SubmitCrashReportAsync()
    {
        if (pendingCrashReport_ is not { } report || IsCrashSubmitting)
        {
            return;
        }

        var cancellationToken = lifetimeCancellation_.Token;
        IsCrashSubmitting = true;
        CrashSubmissionError = string.Empty;
        StatusText = "Submitting the crash report…";
        try
        {
            var receipt = await crashReportSubmissionClient_.SubmitAsync(
                report,
                DirectoryUrl,
                cancellationToken);
            pendingCrashReport_ = null;
            IsCrashPromptOpen = false;
            StatusText = $"Crash report {receipt.ReportId} was submitted. Thank you.";
            TryStartPendingLobbyJoin();
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
        }
        catch (Exception ex) when (ex is IOException or
                                   UnauthorizedAccessException or
                                   InvalidDataException or
                                   InvalidOperationException or
                                   HttpRequestException or
                                   JsonException or
                                   UriFormatException or
                                   System.ComponentModel.Win32Exception or
                                   TaskCanceledException)
        {
            CrashSubmissionError = ex.Message;
            StatusText = "Crash report not sent.";
        }
        finally
        {
            IsCrashSubmitting = false;
        }
    }

    private void DismissCrashReport()
    {
        if (IsCrashSubmitting)
        {
            return;
        }

        pendingCrashReport_ = null;
        CrashSubmissionError = string.Empty;
        IsCrashPromptOpen = false;
        StatusText = "Crash report not sent.";
        TryStartPendingLobbyJoin();
    }

    private async Task RefreshCloudAccountAsync(bool forceRefresh)
    {
        lastCloudAccountRefreshUtc_ = DateTimeOffset.UtcNow;
        try
        {
            var state = await cloudSaveClient_.GetAccountStateAsync(
                DirectoryUrl,
                forceRefresh,
                lifetimeCancellation_.Token);
            linkedAccountName_ = state.LinkedAccount?.Username ?? string.Empty;
            steamIdText_ = state.SteamId;
            IsCloudLinked = state.LinkedAccount is not null;
            OnPropertyChanged(nameof(AccountButtonText));
            OnPropertyChanged(nameof(LinkedAccountDetailText));
            CloudAccountStatus = state.LinkedAccount is { } account
                ? $"Cloud backup enabled for {account.Username}."
                : "Cloud backup is off until this Steam account is linked.";
        }
        catch (OperationCanceledException) when (lifetimeCancellation_.IsCancellationRequested)
        {
        }
        catch (Exception exception) when (
            exception is IOException or
            InvalidOperationException or
            HttpRequestException or
            JsonException or
            TaskCanceledException or
            System.ComponentModel.Win32Exception)
        {
            linkedAccountName_ = string.Empty;
            IsCloudLinked = false;
            OnPropertyChanged(nameof(AccountButtonText));
            OnPropertyChanged(nameof(LinkedAccountDetailText));
            CloudAccountStatus =
                $"Cloud unavailable; local saves still work. {exception.Message}";
        }
    }

    private void OnCloudSaveBackupStatus(CloudSaveBackupStatus status)
    {
        _ = Application.Current.Dispatcher.InvokeAsync(() =>
        {
            CloudAccountStatus = status.Message;
            UpdateActiveSaveSummary();
        });
    }

    private void UpdateActiveSaveSummary()
    {
        var save = client_.SaveCatalog.Active;
        ActiveSaveName = save.Name;
        ActiveSaveStatus = save.HasLocalData
            ? save.LastBackupAtUtc is not { } backup
                ? "Local · not backed up yet"
                : save.LastLocalWriteUtc > backup
                    ? "Local · changes pending cloud backup"
                    : $"Local · cloud backup {backup.LocalDateTime:g}"
            : "Empty local save";
    }

    public async Task PrepareForLauncherCloseAsync()
    {
        if (launcherCloseStarted_)
        {
            return;
        }
        launcherCloseStarted_ = true;
        if (!HasActiveGame)
        {
            return;
        }

        var processId = activeGameProcessId_;
        var expectedExecutablePath =
            lastResponse_?.Stage?.StageExecutablePath;
        if (!TryOpenOwnedStagedProcess(
                processId,
                expectedExecutablePath,
                out var process))
        {
            return;
        }

        using (process)
        using (var timeout = new CancellationTokenSource(
                   TimeSpan.FromMilliseconds(4000)))
        {
            StatusText = IsInLobby
                ? liveSessionIsHost_
                    ? "Closing the lobby before the launcher exits…"
                    : "Leaving the lobby before the launcher exits…"
                : "Closing the staged game before the launcher exits…";

            if (IsInLobby &&
                !string.IsNullOrWhiteSpace(modSettingsPipeName_))
            {
                try
                {
                    var result = await liveSessionClient_.LeaveAsync(
                        modSettingsPipeName_,
                        timeout.Token);
                    if (!result.Ok)
                    {
                        SetError(
                            string.IsNullOrWhiteSpace(result.Error)
                                ? "The staged game did not accept its shutdown request."
                                : $"Session shutdown failed: {result.Error}");
                    }
                }
                catch (OperationCanceledException)
                    when (timeout.IsCancellationRequested)
                {
                }
            }

            try
            {
                await process.WaitForExitAsync(timeout.Token);
            }
            catch (OperationCanceledException)
                when (timeout.IsCancellationRequested)
            {
            }

            if (!process.HasExited)
            {
                try
                {
                    process.CloseMainWindow();
                }
                catch (InvalidOperationException)
                {
                }
                catch (System.ComponentModel.Win32Exception)
                {
                }
                try
                {
                    using var gracefulFallback =
                        new CancellationTokenSource(
                            TimeSpan.FromMilliseconds(500));
                    await process.WaitForExitAsync(
                        gracefulFallback.Token);
                }
                catch (OperationCanceledException)
                {
                }
            }
            if (!process.HasExited)
            {
                try
                {
                    process.Kill(entireProcessTree: false);
                    process.WaitForExit(100);
                }
                catch (InvalidOperationException)
                {
                }
                catch (System.ComponentModel.Win32Exception)
                {
                }
            }
        }
    }

    private static bool TryOpenOwnedStagedProcess(
        int processId,
        string? expectedExecutablePath,
        out Process process)
    {
        process = null!;
        if (processId <= 0 ||
            string.IsNullOrWhiteSpace(expectedExecutablePath))
        {
            return false;
        }

        try
        {
            var candidate = Process.GetProcessById(processId);
            var actualPath = candidate.MainModule?.FileName;
            if (candidate.HasExited ||
                string.IsNullOrWhiteSpace(actualPath) ||
                !string.Equals(
                    Path.GetFullPath(actualPath),
                    Path.GetFullPath(expectedExecutablePath),
                    StringComparison.OrdinalIgnoreCase))
            {
                candidate.Dispose();
                return false;
            }
            process = candidate;
            return true;
        }
        catch (Exception exception) when (
            exception is ArgumentException or
            InvalidOperationException or
            System.ComponentModel.Win32Exception or
            IOException or
            UnauthorizedAccessException)
        {
            return false;
        }
    }

    private void StartSteamSessionMonitoring(
        LauncherCliResponse response,
        LauncherCliMultiplayerSession initialStatus)
    {
        StopSteamSessionMonitoring(clearStatus: false);
        ShowConnectProgress(SessionConnectProgressMapper.StartingGame());
        ApplySteamSessionStatus(initialStatus);

        var stageRootPath = response.Stage?.StageRoot;
        var processId = response.Launch?.ProcessId ?? 0;
        if (string.IsNullOrWhiteSpace(stageRootPath) ||
            string.IsNullOrWhiteSpace(initialStatus.LaunchToken) ||
            processId <= 0)
        {
            return;
        }

        var monitorCancellation = new CancellationTokenSource();
        steamSessionMonitorCancellation_ = monitorCancellation;
        _ = MonitorSteamSessionAsync(
            stageRootPath,
            initialStatus.LaunchToken,
            processId,
            monitorCancellation);
    }

    private async Task MonitorSteamSessionAsync(
        string stageRootPath,
        string launchToken,
        int processId,
        CancellationTokenSource monitorCancellation)
    {
        var cancellationToken = monitorCancellation.Token;
        try
        {
            while (!cancellationToken.IsCancellationRequested)
            {
                await Task.Delay(500, cancellationToken);
                if (!IsProcessRunning(processId))
                {
                    ClearSteamSessionStatus();
                    return;
                }

                var status = await LauncherMultiplayerSessionStatusReader.ReadAsync(
                    stageRootPath,
                    launchToken,
                    cancellationToken);
                cancellationToken.ThrowIfCancellationRequested();
                if (status is not null)
                {
                    ApplySteamSessionStatus(status);
                }
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
        }
        finally
        {
            if (ReferenceEquals(steamSessionMonitorCancellation_, monitorCancellation))
            {
                steamSessionMonitorCancellation_ = null;
                monitorCancellation.Dispose();
            }
        }
    }

    private void ApplySteamSessionStatus(LauncherCliMultiplayerSession status)
    {
        modSettingsSessionStatus_ = status;
        UpdateModSettingsInstance();
        UpdateLobbyDetails(status);
        if (status.Enabled)
        {
            ShowConnectProgress(
                SessionConnectProgressMapper.FromSessionStatus(status));
        }
        if (status.Phase == "Error" &&
            !string.IsNullOrWhiteSpace(status.ErrorText))
        {
            SetError($"Steam error: {status.ErrorText}");
        }
        if (status.StatusText is
            "The host closed the lobby." or
            "The multiplayer host connection was lost.")
        {
            StatusText = status.StatusText;
        }
    }

    private void UpdateLobbyDetails(LauncherCliMultiplayerSession status)
    {
        var inLobby = status.Enabled &&
            status.LobbyId != 0 &&
            status.Members.Count > 0 &&
            status.Phase is "Handshaking" or "LobbyReady" or "Connected";
        if (!inLobby)
        {
            ClearLobbyDetails();
            return;
        }

        var host = status.Members.FirstOrDefault(member => member.IsHost);
        var hostName = host is null || string.IsNullOrWhiteSpace(host.Name)
            ? "Remote Wizard"
            : host.Name;
        LobbyTitleText = status.IsHost ? "Your lobby" : $"{hostName}'s lobby";
        LobbyIdText = $"Lobby {status.LobbyId}";
        LobbyPlayersLabel = status.MaxParticipants > 0
            ? $"Players: {status.Members.Count} of {status.MaxParticipants}"
            : "Players";
        LobbyConnectionDetailsText = DescribeLobbyConnection(status);

        var membersSignature = string.Join(
            "\n",
            status.Members.Select(member =>
                $"{member.ParticipantId}|{member.IsHost}|{member.IsLocal}|{member.IsBot}|{member.Name}"));
        if (membersSignature != lobbyMembersSignature_)
        {
            lobbyMembersSignature_ = membersSignature;
            LobbyMembers.Clear();
            foreach (var member in status.Members)
            {
                LobbyMembers.Add(new LobbyMemberViewModel(member));
            }
        }

        if (LobbySharedMods.Count == 0 && pendingLobbyMods_ is { Count: > 0 } sharedMods)
        {
            foreach (var sharedMod in sharedMods)
            {
                LobbySharedMods.Add(sharedMod);
            }
        }

        liveSessionIsHost_ = status.IsHost;
        liveSessionMemberCount_ = status.Members.Count;
        IsInLobby = true;
    }

    private void ClearLobbyDetails()
    {
        isJoiningLobby_ = false;
        lobbyLaunchState_.Reset();
        OnPropertyChanged(nameof(JoinGameButtonText));
        OnPropertyChanged(nameof(CanLeaveLobby));
        IsInLobby = false;
        liveSessionIsHost_ = false;
        liveSessionMemberCount_ = 0;
        LobbyTitleText = string.Empty;
        LobbyIdText = string.Empty;
        LobbyPlayersLabel = string.Empty;
        LobbyBoneyardText = string.Empty;
        LobbyConnectionDetailsText = string.Empty;
        lobbyMembersSignature_ = string.Empty;
        LobbyMembers.Clear();
        LobbySharedMods.Clear();
        RaiseCommandStates();
    }

    private void OpenHostSetup()
    {
        HostPrivacyFriends = true;
        IsHostSetupOpen = true;
    }

    public void CancelHostSetup()
    {
        IsHostSetupOpen = false;
    }

    // #68 live-session leave over the loader's sd.__session_leave verb.
    private bool liveSessionIsHost_;
    private int liveSessionMemberCount_;
    private readonly LiveSessionRuntimeClient liveSessionClient_ = new();

    private async Task LeaveLiveSessionAsync()
    {
        if (IsBusy || !IsInLobby)
        {
            return;
        }

        var isHost = liveSessionIsHost_;
        var others = Math.Max(0, liveSessionMemberCount_ - 1);
        var message = !isHost
            ? "Leave this lobby?"
            : others switch
            {
                0 => "Close your lobby?",
                1 => "Close your lobby? One other player will be disconnected.",
                _ => $"Close your lobby? {others} other players will be disconnected."
            };
        if (MessageBox.Show(
                message,
                isHost ? "Close Lobby" : "Leave Lobby",
                MessageBoxButton.YesNo,
                MessageBoxImage.Warning) != MessageBoxResult.Yes)
        {
            return;
        }

        if (string.IsNullOrWhiteSpace(modSettingsPipeName_))
        {
            SetError("The game's command channel is not available yet.");
            return;
        }

        IsBusy = true;
        StatusText = isHost
            ? "The launcher closes the lobby."
            : "The launcher leaves the lobby.";
        try
        {
            var result = await liveSessionClient_.LeaveAsync(
                modSettingsPipeName_,
                lifetimeCancellation_.Token);
            if (result.Ok)
            {
                StatusText = isHost ? "Lobby closed." : "Left the lobby.";
            }
            else
            {
                SetError(string.IsNullOrWhiteSpace(result.Error)
                    ? "The game did not accept the leave request."
                    : $"Leave failed: {result.Error}");
            }
        }
        catch (OperationCanceledException)
            when (lifetimeCancellation_.IsCancellationRequested)
        {
        }
        finally
        {
            IsBusy = false;
        }
    }

    public void CloseHowToPlay()
    {
        IsHowToPlayOpen = false;
    }

    public async void ConfirmHostSetup()
    {
        if (IsBusy || !IsHostSetupOpen)
        {
            return;
        }

        var maxPlayers = HostPlayerCount;
        if (maxPlayers is < 2 or > 4)
        {
            SetError(
                "Player count must be 2-4.");
            return;
        }

        var privacy = HostPrivacyPublic ? "public" : "friends";
        IsHostSetupOpen = false;

        await ExecuteUiCommandAsync(
            LauncherUiCommandMode.HostSteam,
            "The launcher starts the lobby.",
            hostOptions: new LauncherHostOptions(privacy, maxPlayers));
    }

    private void OnSteamInviteNotification(
        object? sender,
        SteamInviteNotification notification)
    {
        _ = Application.Current.Dispatcher.InvokeAsync(() =>
            ApplySteamInviteNotification(notification));
    }

    private void ApplySteamInviteNotification(SteamInviteNotification notification)
    {
        switch (notification.Kind)
        {
            case "received" when notification.LobbyId is { } receivedLobbyId:
                LobbyId = receivedLobbyId.ToString();
                break;

            case "accepted" when notification.LobbyId is { } acceptedLobbyId:
                QueueLobbyJoin(acceptedLobbyId);
                break;
        }
    }

    public void QueueLobbyJoin(ulong lobbyId)
    {
        client_.UseDirectLobbyJoin();
        LobbyId = lobbyId.ToString();
        pendingLobbyJoinId_ = lobbyId;
        TryStartPendingLobbyJoin();
    }

    public void QueueWebsiteLobbyJoin(LauncherJoinActivation activation)
    {
        DirectoryUrl = activation.DirectoryBaseUrl;
        LobbyId = activation.LobbyId.ToString();
        client_.UseWebsiteLobbyJoin(activation.DirectoryBaseUrl, activation.Ticket);
        pendingLobbyJoinId_ = activation.LobbyId;
        TryStartPendingLobbyJoin();
    }

    public void QueueWebsiteModInstall(LauncherInstallModActivation activation)
    {
        if (IsBusy ||
            IsModDownloadPromptOpen ||
            IsCrashPromptOpen ||
            IsLauncherUpdatePromptOpen)
        {
            SetError(
                $"Busy right now - try the mod link for '{activation.Slug}' again in a moment.");
            StatusText = "Mod install didn't start.";
            return;
        }

        _ = PreviewWebsiteModInstallAsync(activation);
    }

    private async Task PreviewWebsiteModInstallAsync(
        LauncherInstallModActivation activation)
    {
        pendingWebsiteModInstall_ = null;
        DirectoryUrl = activation.DirectoryBaseUrl;
        var succeeded = await ExecuteUiCommandAsync(
            LauncherUiCommandMode.InstallModPreview,
            $"Checking mod '{activation.Slug}'…",
            activation.Slug);
        var preview = succeeded
            ? lastResponse_?.ModInstallPreview
            : null;
        if (preview is null)
        {
            return;
        }

        if (preview.Disposition is "current" or "newerInstalled")
        {
            StatusText = preview.Disposition == "current"
                ? $"{preview.Name} {preview.Version} is already installed and current."
                : $"{preview.Name} is already installed at newer version {preview.InstalledVersion}.";
            return;
        }

        var sourceHost = new Uri(activation.DirectoryBaseUrl).Authority;
        ModDownloadItems.Clear();
        var detail = $"{preview.Name} {preview.Version}";
        if (!string.IsNullOrWhiteSpace(preview.InstalledVersion))
        {
            detail += $" (updates {preview.InstalledVersion})";
        }
        ModDownloadItems.Add(detail);
        ModDownloadPromptTitle = preview.Disposition == "update"
            ? $"Update {preview.Name}"
            : $"Install {preview.Name}";
        ModDownloadPromptText = preview.Disposition == "update"
            ? $"Update {preview.Name} to {preview.Version} from {sourceHost}?"
            : $"Install {preview.Name} {preview.Version} from {sourceHost}?";
        ModDownloadPromptNote =
            "Downloads are verified before they're added to your Mods tab.";
        ModDownloadConfirmText = preview.Disposition == "update"
            ? "Update"
            : "Install";
        ModDownloadDeclineText = "Cancel";
        pendingWebsiteModInstall_ = activation;
        StatusText = "Waiting for your choice…";
        IsModDownloadPromptOpen = true;
    }

    private async Task InstallWebsiteModAsync(
        LauncherInstallModActivation activation)
    {
        var succeeded = await ExecuteUiCommandAsync(
            LauncherUiCommandMode.InstallMod,
            $"Installing mod '{activation.Slug}'…",
            activation.Slug);
        if (!succeeded)
        {
            return;
        }

        var preview = lastResponse_?.ModInstallPreview;
        var result = lastResponse_?.ModInstall;
        if (preview is null || result is null)
        {
            SetError("The launcher did not return a mod installation result.");
            StatusText = "Mod install didn't finish.";
            return;
        }
        StatusText = result.Changed
            ? $"{preview.Name} {preview.Version} is installed and available in the Mods tab."
            : $"{preview.Name} {preview.Version} is already installed and current.";
    }

    public void OfferLauncherUpdate(string version)
    {
        AvailableLauncherVersion = $"v{version}";
        IsLauncherUpdatePromptOpen = true;
    }

    private void AcceptLauncherUpdate()
    {
        if (!IsLauncherUpdatePromptOpen || IsBusy)
        {
            return;
        }

        IsLauncherUpdatePromptOpen = false;
        LauncherUpdateAccepted?.Invoke(this, EventArgs.Empty);
    }

    private void DismissLauncherUpdate()
    {
        if (!IsLauncherUpdatePromptOpen || IsBusy)
        {
            return;
        }

        IsLauncherUpdatePromptOpen = false;
        StatusText = "Launcher update postponed.";
        TryStartPendingLobbyJoin();
    }

    public void BeginLauncherUpdate(string version)
    {
        IsLauncherUpdatePromptOpen = false;
        ClearError();
        ClearUpdateProgress();
        IsBusy = true;
        StatusText =
            $"Launcher v{version} will restart automatically after installation.";
    }

    public void ReportUpdateProgress(UpdateProgress progress)
    {
        var presentation = UpdateProgressPresentation.Create(progress);
        IsUpdateProgressVisible = true;
        UpdateStatusText = progress.StatusText;
        UpdateProgressDetailText = presentation.DetailText;
        UpdateProgressValue = presentation.Value;
        IsUpdateProgressError = presentation.IsError;
        IsUpdateProgressComplete = presentation.IsComplete;
    }

    public void ReportLauncherUpdateFailure(string message)
    {
        ReportUpdateProgress(new UpdateProgress(
            UpdateProgressPhase.Failed,
            "The launcher update failed."));
        SetError(message);
        IsBusy = false;
        StatusText = "Update failed - this version keeps working.";
        TryStartPendingLobbyJoin();
    }

    private void ExecuteLobbyPrimaryAction()
    {
        if (lobbyLaunchState_.PrimaryAction == LobbyPrimaryAction.LaunchGame)
        {
            _ = LaunchJoinedLobbyAsync();
            return;
        }

        JoinLobbyDirect();
    }

    private static bool IsLocalUdpDevelopmentLaunch() =>
        string.Equals(
            Environment.GetEnvironmentVariable(
                "SDMOD_MULTIPLAYER_TRANSPORT"),
            "local_udp",
            StringComparison.OrdinalIgnoreCase);

    private void JoinLobbyDirect()
    {
        client_.UseDirectLobbyJoin();
        _ = JoinLobbyWithModCheckAsync($"The launcher joins lobby {LobbyId}.");
    }

    private void TryStartPendingLobbyJoin()
    {
        if (pendingLobbyJoinId_ is not { } lobbyId ||
            !CanLaunch() ||
            IsInLobby ||
            isJoiningLobby_)
        {
            return;
        }

        pendingLobbyJoinId_ = null;
        LobbyId = lobbyId.ToString();
        _ = JoinLobbyWithModCheckAsync($"The launcher joins lobby {lobbyId}.");
    }

    private async Task JoinLobbyWithModCheckAsync(string joinStatusText)
    {
        if (IsBusy || IsModDownloadPromptOpen)
        {
            return;
        }

        pendingLobbyMods_ = null;
        IsBusy = true;
        StatusText = "Checking the host's mods…";
        CommandPreviewText = client_.BuildCommandPreview(LauncherUiCommandMode.JoinPreview);
        LauncherUiInvocationResult invocation;
        try
        {
            invocation = await client_.InvokeAsync(LauncherUiCommandMode.JoinPreview);
        }
        catch (Exception ex)
        {
            SetError(ex.Message);
            StatusText = "Command failed.";
            IsBusy = false;
            return;
        }

        AppendTranscript(invocation);
        IsBusy = false;

        var preview = invocation.Response?.JoinPreview;
        if (preview is null || !preview.UsedWebsite || !invocation.Succeeded)
        {
            var reason = preview?.Error ?? invocation.ErrorMessage;
            StatusText = string.IsNullOrWhiteSpace(reason)
                ? "The website has no mod list for this lobby. Joining with your current mods."
                : $"Mod check unavailable ({reason.TrimEnd('.')}). Joining with your current mods.";
            await PrepareLobbyJoinAsync(joinStatusText);
            return;
        }

        if (preview.HostProtocolVersion is { } hostProtocol &&
            hostProtocol != preview.LocalProtocolVersion)
        {
            SetError(
                "The host is on a different Solomon Dark Revived version " +
                $"(host: {preview.HostLoaderVersion ?? "unknown"}, you: {Version}). " +
                "Both players need the same launcher version to play together.");
            StatusText = "Join canceled - game versions don't match.";
            return;
        }

        if (preview.UnavailableCount > 0)
        {
            var unavailable = preview.Mods
                .Where(mod => mod.State == "unavailable")
                .Select(mod => $"{mod.DisplayName} {mod.Version}");
            SetError(
                $"The host has unpublished mods: {string.Join(", ", unavailable)}. " +
                "They aren't on the mod directory yet, so they can't be downloaded " +
                "automatically. Ask the host to publish them, or install the same mod " +
                "files manually before joining.");
            StatusText = "Join canceled - the host has unpublished mods.";
            return;
        }

        pendingLobbyMods_ = preview.Mods
            .Select(mod => $"{mod.DisplayName} {mod.Version}")
            .ToArray();

        if (preview.DownloadCount > 0)
        {
            ModDownloadItems.Clear();
            foreach (var mod in preview.Mods.Where(mod => mod.State == "needsDownload"))
            {
                var line = $"{mod.DisplayName} {mod.Version}";
                if (!string.IsNullOrWhiteSpace(mod.InstalledVersion))
                {
                    line += mod.InstalledVersion == mod.Version
                        ? " (replaces your local copy)"
                        : $" (you have {mod.InstalledVersion})";
                }
                ModDownloadItems.Add(line);
            }

            ModDownloadPromptTitle = "This lobby uses mods";
            ModDownloadPromptText =
                "The host's game uses the mods listed below. Download them to join the lobby?";
            ModDownloadPromptNote =
                "Applies to this session only - your own mods aren't changed.";
            ModDownloadConfirmText = "Download and join";
            ModDownloadDeclineText = "Cancel";
            pendingWebsiteModInstall_ = null;
            consentedJoinStatusText_ = joinStatusText;
            StatusText = "Waiting for your choice…";
            IsModDownloadPromptOpen = true;
            return;
        }

        StatusText = preview.Mods.Count == 0
            ? "The host plays without mods."
            : "Your mods already match the host.";
        await PrepareLobbyJoinAsync(joinStatusText);
    }

    private void ConfirmModDownload()
    {
        if (!IsModDownloadPromptOpen)
        {
            return;
        }

        if (pendingWebsiteModInstall_ is { } activation)
        {
            pendingWebsiteModInstall_ = null;
            IsModDownloadPromptOpen = false;
            _ = InstallWebsiteModAsync(activation);
            return;
        }

        var joinStatusText = consentedJoinStatusText_ ??
            $"The launcher joins lobby {LobbyId}.";
        consentedJoinStatusText_ = null;
        IsModDownloadPromptOpen = false;
        _ = PrepareLobbyJoinAsync(joinStatusText);
    }

    private async Task PrepareLobbyJoinAsync(string joinStatusText)
    {
        if (!await ExecuteUiCommandAsync(
                LauncherUiCommandMode.PrepareSteamJoin,
                joinStatusText))
        {
            return;
        }

        if (IsLocalUdpDevelopmentLaunch())
        {
            await ExecuteUiCommandAsync(
                LauncherUiCommandMode.LaunchSteamJoin,
                $"Launching local game for lobby {LobbyId}…");
            return;
        }

        StartSteamLobbyMembership();
    }

    private void StartSteamLobbyMembership()
    {
        if (!ulong.TryParse(LobbyId, out var lobbyId) || lobbyId == 0)
        {
            SetError("Enter a valid Steam lobby ID.");
            StatusText = "Couldn't join the lobby.";
            return;
        }

        isJoiningLobby_ = true;
        OnPropertyChanged(nameof(CanLeaveLobby));
        RaiseCommandStates();
        StopSteamInviteListener();
        StatusText = $"Connecting to lobby {lobbyId}…";
        ShowConnectProgress(SessionConnectProgressMapper.JoiningLobby(lobbyId));
        try
        {
            steamLobbySession_.Join(lobbyId);
        }
        catch (Exception exception) when (
            exception is InvalidOperationException or
            IOException or
            System.ComponentModel.Win32Exception)
        {
            isJoiningLobby_ = false;
            HideConnectProgress();
            SetError(exception.Message);
            StatusText = "Couldn't join the lobby.";
            RaiseCommandStates();
            StartSteamInviteListener();
        }
    }

    private async Task LaunchJoinedLobbyAsync()
    {
        if (lobbyLaunchState_.JoinedLobbyId is not { } lobbyId || !CanLaunch())
        {
            return;
        }

        LobbyId = lobbyId.ToString();
        steamLobbySession_.Leave();
        StatusText = $"Launching game for lobby {lobbyId}…";
        var launched = await ExecuteUiCommandAsync(
            LauncherUiCommandMode.LaunchSteamJoin,
            StatusText);
        if (launched)
        {
            return;
        }

        ClearLobbyDetails();
        StartSteamInviteListener();
    }

    private void LeaveLobby()
    {
        if (!CanLeaveLobby)
        {
            return;
        }

        steamLobbySession_.Leave();
        pendingLobbyMods_ = null;
        ClearLobbyDetails();
        ClearError();
        StatusText = "You left the lobby.";
        StartSteamInviteListener();
        TryStartPendingLobbyJoin();
    }

    private void OnSteamLobbySessionNotification(
        object? sender,
        SteamLobbySessionNotification notification)
    {
        _ = Application.Current.Dispatcher.InvokeAsync(() =>
            ApplySteamLobbySessionNotification(notification));
    }

    private void ApplySteamLobbySessionNotification(
        SteamLobbySessionNotification notification)
    {
        if (notification.LobbyId is { } notificationLobbyId &&
            ulong.TryParse(LobbyId, out var currentLobbyId) &&
            currentLobbyId != notificationLobbyId)
        {
            return;
        }

        if (notification.Kind is "joined" or "status" &&
            notification.LobbyId is { } lobbyId)
        {
            isJoiningLobby_ = false;
            HideConnectProgress();
            lobbyLaunchState_.MarkJoined(lobbyId);
            OnPropertyChanged(nameof(JoinGameButtonText));
            OnPropertyChanged(nameof(CanLeaveLobby));
            UpdateLauncherLobbyDetails(notification);
            ClearError();
            StatusText =
                $"Joined lobby {lobbyId}. Click Launch Game when you are ready.";
            RaiseCommandStates();
            return;
        }

        if (notification.Kind is not ("error" or "disconnected" or "hostDeparted"))
        {
            return;
        }

        steamLobbySession_.Leave();
        isJoiningLobby_ = false;
        HideConnectProgress();
        pendingLobbyMods_ = null;
        ClearLobbyDetails();
        var message = string.IsNullOrWhiteSpace(notification.Error)
            ? "The Steam lobby connection ended before launch."
            : notification.Error;
        SetError(message);
        StatusText = message;
        StartSteamInviteListener();
        RaiseCommandStates();
    }

    private void UpdateLauncherLobbyDetails(
        SteamLobbySessionNotification notification)
    {
        var host = notification.Members.FirstOrDefault(member => member.IsHost);
        var hostName = host is null || string.IsNullOrWhiteSpace(host.Name)
            ? "Remote Wizard"
            : host.Name;
        LobbyTitleText = $"{hostName}'s lobby";
        LobbyIdText = $"Lobby {notification.LobbyId}";
        LobbyPlayersLabel = notification.MaxParticipants > 0
            ? $"Players: {notification.Members.Count} of {notification.MaxParticipants}"
            : "Players";
        var privacy = notification.Privacy switch
        {
            "public" => "Public",
            "friendsOnly" => "Friends Only",
            _ => "Steam Lobby"
        };
        LobbyConnectionDetailsText =
            $"{privacy} · Joined · Game not launched";

        var membersSignature = string.Join(
            "\n",
            notification.Members.Select(member =>
                $"{member.ParticipantId}|{member.IsHost}|{member.IsLocal}|{member.IsBot}|{member.Name}"));
        if (membersSignature != lobbyMembersSignature_)
        {
            lobbyMembersSignature_ = membersSignature;
            LobbyMembers.Clear();
            foreach (var member in notification.Members)
            {
                LobbyMembers.Add(new LobbyMemberViewModel(member));
            }
        }

        if (LobbySharedMods.Count == 0 &&
            pendingLobbyMods_ is { Count: > 0 } sharedMods)
        {
            foreach (var sharedMod in sharedMods)
            {
                LobbySharedMods.Add(sharedMod);
            }
        }

        IsInLobby = true;
    }

    private void DeclineModDownload()
    {
        if (!IsModDownloadPromptOpen)
        {
            return;
        }

        if (pendingWebsiteModInstall_ is not null)
        {
            pendingWebsiteModInstall_ = null;
            IsModDownloadPromptOpen = false;
            StatusText = "Mod installation canceled.";
            return;
        }

        consentedJoinStatusText_ = null;
        pendingLobbyMods_ = null;
        IsModDownloadPromptOpen = false;
        HideConnectProgress();
        StatusText = "Join canceled - nothing was downloaded.";
        TryStartPendingLobbyJoin();
    }

    private void StopSteamInviteListener()
    {
        steamInviteListener_.Stop();
    }

    private void StartSteamInviteListener()
    {
        if (activeGameProcessId_ == 0 &&
            !isJoiningLobby_ &&
            !lobbyLaunchState_.JoinedLobbyId.HasValue)
        {
            steamInviteListener_.Start();
        }
    }

    private void StopSteamSessionMonitoring(
        bool clearStatus,
        bool preservePendingLobbyMods = false)
    {
        steamSessionMonitorCancellation_?.Cancel();
        steamSessionMonitorCancellation_?.Dispose();
        steamSessionMonitorCancellation_ = null;
        if (clearStatus)
        {
            ClearSteamSessionStatus(preservePendingLobbyMods);
        }
    }

    private void ClearSteamSessionStatus(bool preservePendingLobbyMods = false)
    {
        if (!preservePendingLobbyMods)
        {
            pendingLobbyMods_ = null;
        }
        modSettingsSessionStatus_ = null;
        UpdateModSettingsInstance();
        ClearLobbyDetails();
        HideConnectProgress();
    }

    private void ShowConnectProgress(SessionConnectProgress progress)
    {
        ConnectProgressText = progress.Text;
        ConnectProgressPercent = progress.Fraction * 100.0;
        ConnectProgressDetailText = progress.IsError
            ? string.Empty
            : $"{Math.Round(progress.Fraction * 100.0)}%";
        IsConnectProgressError = progress.IsError;
        IsConnectProgressVisible = true;
        if (progress.IsComplete)
        {
            if (!connectProgressCompleted_)
            {
                connectProgressCompleted_ = true;
                _ = HideConnectProgressAfterDelayAsync(
                    ++connectProgressGeneration_);
            }
        }
        else
        {
            connectProgressCompleted_ = false;
        }
    }

    private async Task HideConnectProgressAfterDelayAsync(int generation)
    {
        try
        {
            await Task.Delay(
                TimeSpan.FromSeconds(4),
                lifetimeCancellation_.Token);
        }
        catch (OperationCanceledException)
        {
            return;
        }
        await Application.Current.Dispatcher.InvokeAsync(() =>
        {
            if (connectProgressGeneration_ == generation &&
                connectProgressCompleted_)
            {
                HideConnectProgress();
            }
        });
    }

    private void HideConnectProgress()
    {
        connectProgressGeneration_++;
        connectProgressCompleted_ = false;
        IsConnectProgressVisible = false;
        IsConnectProgressError = false;
        ConnectProgressText = string.Empty;
        ConnectProgressDetailText = string.Empty;
        ConnectProgressPercent = 0;
    }

    private static bool IsProcessRunning(int processId)
    {
        try
        {
            using var process = Process.GetProcessById(processId);
            return !process.HasExited;
        }
        catch (ArgumentException)
        {
            return false;
        }
    }

    public void Dispose()
    {
        lifetimeCancellation_.Cancel();
        if (activeSaveSession_ is { } saveSession)
        {
            activeSaveSession_ = null;
            saveSession.DisposeAsync().AsTask().GetAwaiter().GetResult();
        }
        StopSteamSessionMonitoring(clearStatus: false);
        steamInviteListener_.NotificationReceived -= OnSteamInviteNotification;
        steamLobbySession_.NotificationReceived -= OnSteamLobbySessionNotification;
        steamLobbySession_.Dispose();
        steamInviteListener_.Dispose();
        lifetimeCancellation_.Dispose();
    }

    private static string DescribeLobbyConnection(
        LauncherCliMultiplayerSession status)
    {
        var privacy = status.Privacy switch
        {
            "public" => "Public",
            "friendsOnly" => "Friends Only",
            _ => "Steam Lobby"
        };
        var gamePhase = status.GamePhase switch
        {
            "picking-loadout" => "Picking Loadout",
            "hub" => "In Hub",
            "session" => "In Match",
            "loading" => "Loading",
            "results" => "Results",
            _ => status.SessionState switch
            {
                "in-hub" => "In Hub",
                "in-boneyard" => "In Boneyard",
                "not-in-game" => "Not In Game",
                _ => "Starting"
            }
        };
        var connection = status.Phase == "Connected"
            ? "Connected"
            : status.Phase == "Handshaking" ? "Build Check" : "Lobby Ready";
        if (status.Phase == "Connected" && status.RoutePingMs > 0)
        {
            connection += $" · {status.RoutePingMs} ms";
        }

        return $"{privacy} · {gamePhase} · {connection}";
    }

    private void UpdateFromResponse(LauncherCliResponse response)
    {
        foreach (var mod in Mods)
        {
            mod.ToggleRequested -= OnModToggleRequested;
            mod.SettingsRequested -= OnModSettingsRequested;
        }

        EnsureModSettingsService(response.Configuration);

        Mods.Clear();
        foreach (var mod in response.Mods)
        {
            var viewModel = new ModItemViewModel(mod);
            viewModel.ToggleRequested += OnModToggleRequested;
            viewModel.SettingsRequested += OnModSettingsRequested;
            ApplyModSettingsState(viewModel);
            Mods.Add(viewModel);
        }

        var total = response.Mods.Count;
        var enabled = response.Mods.Count(mod => mod.Enabled);
        ModSummaryText = total == 0 ? string.Empty : $"Enabled mods: {enabled} of {total}";
        DebugUiEnabled = response.Configuration?.LoaderDebugUi ?? true;
        var resolvedGameDirectory = response.Configuration?.GameDirectory;
        if (!string.IsNullOrWhiteSpace(resolvedGameDirectory))
        {
            GameDirectory = resolvedGameDirectory;
            client_.UpdateGameDirectory(resolvedGameDirectory);
        }

        OnPropertyChanged(nameof(WorkspaceRoot));
        RaiseCommandStates();
    }

    private async void OnModToggleRequested(ModItemViewModel mod)
    {
        if (IsBusy)
        {
            mod.SetEnabledSilently(!mod.IsEnabled);
            return;
        }

        var desiredState = mod.IsEnabled;
        var mode = desiredState ? LauncherUiCommandMode.EnableMod : LauncherUiCommandMode.DisableMod;
        await ExecuteUiCommandAsync(
            mode,
            desiredState
                ? $"The launcher enables {mod.Name}."
                : $"The launcher disables {mod.Name}.",
            mod.Id);
    }

    // #61 mod-settings frontend over the #60 service layer.
    // SDMOD_UI_SETTINGS_STUB=1 substitutes the stub source for visual work.
    private readonly ModSettingsInstanceContext modSettingsInstanceContext_ = new();
    private IModSettingsService? modSettingsService_;
    private IModSettingsSource? settingsSource_ =
        StubModSettingsSource.Enabled ? new StubModSettingsSource() : null;
    private string modSettingsModsRoot_ = string.Empty;
    private string modSettingsStageRoot_ = string.Empty;
    private string modSettingsPipeName_ = string.Empty;
    private LauncherCliMultiplayerSession? modSettingsSessionStatus_;

    private void EnsureModSettingsService(LauncherCliConfiguration? configuration)
    {
        if (StubModSettingsSource.Enabled
            || configuration is null
            || string.IsNullOrWhiteSpace(configuration.ModsRoot)
            || string.IsNullOrWhiteSpace(configuration.StageRoot))
        {
            return;
        }

        if (modSettingsService_ is not null
            && configuration.ModsRoot == modSettingsModsRoot_
            && configuration.StageRoot == modSettingsStageRoot_)
        {
            return;
        }

        modSettingsModsRoot_ = configuration.ModsRoot;
        modSettingsStageRoot_ = configuration.StageRoot;
        modSettingsPipeName_ = string.IsNullOrWhiteSpace(configuration.Instance)
            ? "SolomonDarkModLoader_LuaExec"
            : $"SolomonDarkModLoader_LuaExec_{configuration.Instance}";

        var manifestService = new ModSettingsManifestService();
        modSettingsService_ = new ModSettingsService(
            configuration.ModsRoot,
            configuration.StageRoot,
            new ModSettingsDiscoveryService(manifestService),
            new ModSettingsStore(manifestService),
            new ModSettingsRuntimeClient(),
            modSettingsInstanceContext_);
        settingsSource_ = new ModSettingsSourceAdapter(modSettingsService_);
        UpdateModSettingsInstance();
    }

    private void UpdateModSettingsInstance()
    {
        var state = ModSettingsGameInstanceState.NotRunning;
        if (activeGameProcessId_ > 0)
        {
            state = modSettingsSessionStatus_ is { Enabled: true, LobbyId: not 0 } session
                ? session.IsHost
                    ? ModSettingsGameInstanceState.RunningHost
                    : ModSettingsGameInstanceState.RunningClientInSession
                : ModSettingsGameInstanceState.RunningSolo;
        }

        modSettingsInstanceContext_.Update(new OwnedModSettingsInstance
        {
            State = state,
            PipeName = state == ModSettingsGameInstanceState.NotRunning
                ? string.Empty
                : modSettingsPipeName_
        });
    }

    private void ApplyModSettingsState(ModItemViewModel mod)
    {
        if (settingsSource_ is null)
        {
            return;
        }

        try
        {
            ModSettingsSchema schema = settingsSource_.GetSchema(mod.Id);
            mod.SettingsState = schema.State;
            mod.SettingsValidationError = schema.ValidationError;
        }
        catch (KeyNotFoundException)
        {
            mod.SettingsState = ModSettingsBlockState.None;
            mod.SettingsValidationError = null;
        }
    }

    private void OnModSettingsRequested(ModItemViewModel mod)
    {
        if (settingsSource_ is null || !mod.HasSettings)
        {
            return;
        }

        var viewModel = new ModSettingsDialogViewModel(settingsSource_, mod.Id);
        var window = new ModSettingsWindow(viewModel)
        {
            Owner = Application.Current.MainWindow
        };
        window.ShowDialog();
    }

    private void AppendTranscript(LauncherUiInvocationResult invocation)
    {
        if (transcriptBuilder_.Length > 0)
        {
            transcriptBuilder_.AppendLine();
            transcriptBuilder_.AppendLine(new string('-', 56));
            transcriptBuilder_.AppendLine();
        }

        transcriptBuilder_.AppendLine($"[{DateTime.Now:HH:mm:ss}] SolomonDarkModLauncher.exe {string.Join(" ", invocation.Arguments)}");
        if (!string.IsNullOrWhiteSpace(invocation.Transcript))
        {
            transcriptBuilder_.AppendLine();
            transcriptBuilder_.AppendLine(invocation.Transcript.TrimEnd());
        }

        TranscriptText = transcriptBuilder_.ToString().TrimEnd();
    }

    private void SetError(string message)
    {
        HasError = true;
        ErrorMessage = message;
    }

    private void ClearError()
    {
        HasError = false;
        ErrorMessage = string.Empty;
    }

    private void ClearUpdateProgress()
    {
        IsUpdateProgressVisible = false;
        UpdateStatusText = string.Empty;
        UpdateProgressDetailText = string.Empty;
        UpdateProgressValue = 0;
        IsUpdateProgressError = false;
        IsUpdateProgressComplete = false;
    }

    private static bool CanOpenFolder(string? path)
    {
        return !string.IsNullOrWhiteSpace(path) && Directory.Exists(path);
    }

    private static void OpenFolder(string? path)
    {
        LauncherShell.TryOpenFolder(path);
    }

    private void RaiseCommandStates()
    {
        RefreshCommand.RaiseCanExecuteChanged();
        HostSteamCommand.RaiseCanExecuteChanged();
        JoinSteamCommand.RaiseCanExecuteChanged();
        LeaveLobbyCommand.RaiseCanExecuteChanged();
        LaunchSinglePlayerCommand.RaiseCanExecuteChanged();
        StageCommand.RaiseCanExecuteChanged();
        ApplyInstanceCommand.RaiseCanExecuteChanged();
        ChooseGameFolderCommand.RaiseCanExecuteChanged();
        OpenModsFolderCommand.RaiseCanExecuteChanged();
        OpenStageFolderCommand.RaiseCanExecuteChanged();
        OpenProfileFolderCommand.RaiseCanExecuteChanged();
        OpenGameFolderCommand.RaiseCanExecuteChanged();
        ManageSavesCommand.RaiseCanExecuteChanged();
        OpenSettingsCommand.RaiseCanExecuteChanged();
        RefreshAccountCommand.RaiseCanExecuteChanged();
        UnlinkAccountCommand.RaiseCanExecuteChanged();
        SendLogsCommand.RaiseCanExecuteChanged();
        ConfirmModDownloadCommand.RaiseCanExecuteChanged();
        DeclineModDownloadCommand.RaiseCanExecuteChanged();
        SubmitCrashReportCommand.RaiseCanExecuteChanged();
        DismissCrashReportCommand.RaiseCanExecuteChanged();
        InstallLauncherUpdateCommand.RaiseCanExecuteChanged();
        DismissLauncherUpdateCommand.RaiseCanExecuteChanged();
    }

    private void UpdateLaunchPreview()
    {
        CommandPreviewText = client_.BuildCommandPreview(LauncherUiCommandMode.HostSteam);
    }
}
