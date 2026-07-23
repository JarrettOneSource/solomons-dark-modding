using System.Collections.ObjectModel;
using System.Diagnostics;
using System.Net.Http;
using System.Reflection;
using System.Text;
using System.Text.Json;
using System.Windows;
using Microsoft.Win32;
using SolomonDarkModLauncher.UI.Infrastructure;
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
    private readonly StringBuilder transcriptBuilder_ = new();
    private readonly CancellationTokenSource lifetimeCancellation_ = new();
    private LauncherCliResponse? lastResponse_;
    private bool isBusy_;
    private bool hasError_;
    private string errorMessage_ = string.Empty;
    private string statusText_ = "The launcher starts.";
    private string modSummaryText_ = string.Empty;
    private string commandPreviewText_ = string.Empty;
    private string transcriptText_ = string.Empty;
    private string instanceName_;
    private bool debugUiEnabled_;
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
    private bool isSettingsOpen_;
    private bool isAccountBusy_;
    private bool isSendingLogs_;
    private string diagnosticsStatusText_ =
        "Send Logs uploads launcher and loader logs to private website storage.";
    private bool isModDownloadPromptOpen_;
    private string modDownloadPromptText_ = string.Empty;
    private string? consentedJoinStatusText_;
    private IReadOnlyList<string>? pendingLobbyMods_;

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
        lobbyId_ = client.LobbyId;
        gameDirectory_ = client.GameDirectory;
        directoryUrl_ = client.DirectoryUrl;

        RefreshCommand = new RelayCommand(_ => _ = RefreshAsync(), _ => CanInteract());
        HowToPlayCommand = new RelayCommand(_ => IsHowToPlayOpen = true);
        HostSteamCommand = new RelayCommand(_ => OpenHostSetup(), _ => CanLaunch());
        JoinSteamCommand = new RelayCommand(
            _ => JoinLobbyDirect(),
            _ => CanJoinLobbyId());
        LaunchSinglePlayerCommand = new RelayCommand(
            _ => _ = ExecuteActionAsync(
                LauncherUiCommandMode.LaunchSinglePlayer,
                "The launcher starts the game."),
            _ => CanLaunch());
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

        steamInviteListener_.NotificationReceived += OnSteamInviteNotification;
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

    public bool IsInLobby
    {
        get => isInLobby_;
        private set => SetProperty(ref isInLobby_, value);
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

    public string HostButtonText => IsBusy ? "Wait" : "Host Game";

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

    private bool CanInteractInSettings() =>
        !IsBusy && !IsCrashPromptOpen && !IsModDownloadPromptOpen;

    private bool CanInteract() => CanInteractInSettings() && !IsSettingsOpen;

    private bool CanLaunch() =>
        CanInteract() && isGameReady_ && activeGameProcessId_ == 0;

    private bool CanManageSaves() => CanInteractInSettings() && activeGameProcessId_ == 0;

    private bool CanJoinLobbyId() =>
        CanLaunch() && ulong.TryParse(LobbyId, out var lobbyId) && lobbyId != 0;

    private void ChooseGameFolder()
    {
        var dialog = new OpenFolderDialog
        {
            Title = "Select the Solomon Dark 0.72.5 folder that contains SolomonDark.exe",
            Multiselect = false
        };
        if (!string.IsNullOrWhiteSpace(GameDirectory) && Directory.Exists(GameDirectory))
        {
            dialog.InitialDirectory = GameDirectory;
        }

        if (dialog.ShowDialog() != true)
        {
            return;
        }

        try
        {
            client_.UpdateGameDirectory(dialog.FolderName);
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
        try
        {
            Process.Start(new ProcessStartInfo($"{DirectoryUrl.TrimEnd('/')}/account")
            {
                UseShellExecute = true
            });
            CloudAccountStatus =
                "Link Steam on the website, then return to the launcher.";
        }
        catch (Exception exception) when (
            exception is InvalidOperationException or
            System.ComponentModel.Win32Exception)
        {
            SetError($"Could not open the website account page: {exception.Message}");
        }
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
        DiagnosticsStatusText = "Collecting logs and uploading them to the website…";
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

    private async Task ExecuteUiCommandAsync(
        LauncherUiCommandMode mode,
        string statusText,
        string? targetModId = null,
        LauncherHostOptions? hostOptions = null)
    {
        var launchesGame = mode is LauncherUiCommandMode.HostSteam or
            LauncherUiCommandMode.JoinSteam or
            LauncherUiCommandMode.LaunchSinglePlayer;
        if (launchesGame)
        {
            StopSteamInviteListener();
        }

        if (mode is LauncherUiCommandMode.HostSteam or
            LauncherUiCommandMode.JoinSteam or
            LauncherUiCommandMode.LaunchSinglePlayer or
            LauncherUiCommandMode.Stage)
        {
            StopSteamSessionMonitoring(clearStatus: true);
        }

        IsBusy = true;
        StatusText = statusText;
        CommandPreviewText = client_.BuildCommandPreview(mode, targetModId, hostOptions);
        LauncherUiInvocationResult invocation;
        try
        {
            invocation = await client_.InvokeAsync(mode, targetModId, hostOptions);
        }
        catch (Exception ex)
        {
            SetError(ex.Message);
            StatusText = "The command failed. Read the error message.";
            IsBusy = false;
            if (launchesGame)
            {
                StartSteamInviteListener();
            }
            TryLaunchPendingLobbyJoin();
            return;
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
            StatusText = "The command failed. Read the error message.";
            IsBusy = false;
            if (launchesGame)
            {
                StartSteamInviteListener();
            }
            TryLaunchPendingLobbyJoin();
            return;
        }

        ClearError();
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
        if (mode is LauncherUiCommandMode.HostSteam or LauncherUiCommandMode.JoinSteam &&
            multiplayer is not null)
        {
            StartSteamSessionMonitoring(invocation.Response, multiplayer);
        }
        var processId = invocation.Response.Launch?.ProcessId ?? 0;
        if (launchesGame && processId > 0)
        {
            activeGameProcessId_ = processId;
            OnPropertyChanged(nameof(HasActiveGame));
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
            LauncherUiCommandMode.ListMods => "Ready",
            LauncherUiCommandMode.Stage => "Stage ready",
            LauncherUiCommandMode.LaunchSinglePlayer => "Game started",
            LauncherUiCommandMode.HostSteam => "Ready",
            LauncherUiCommandMode.JoinSteam =>
                invocation.Response.LobbyModSync is { DownloadedModCount: > 0 } sync
                    ? $"Downloaded {sync.DownloadedModCount} host " +
                      (sync.DownloadedModCount == 1 ? "mod" : "mods") +
                      " from the website."
                    : "Ready",
            LauncherUiCommandMode.EnableMod => "Ready",
            LauncherUiCommandMode.DisableMod => "Ready",
            _ => "Ready"
        };
        IsBusy = false;
        TryLaunchPendingLobbyJoin();
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
            TryLaunchPendingLobbyJoin();
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
            $"Solomon Dark closed unexpectedly (exit code {crashReport.ExitCodeText}). " +
            $"The launcher captured {dumpText}, diagnostic logs, runtime configuration, " +
            "and the enabled-mod list. Submit these diagnostics to the Solomon Dark website? " +
            "The private report will be tied to your Steam identity.";
        StatusText = "A game crash was detected.";
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
            TryLaunchPendingLobbyJoin();
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
            StatusText = "The crash report was not submitted.";
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
        TryLaunchPendingLobbyJoin();
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

    public bool CanCloseLauncher()
    {
        if (!HasActiveGame)
        {
            return true;
        }
        StatusText =
            "The launcher stays open while the game runs so local and Proton saves can finish safely.";
        return false;
    }

    private void StartSteamSessionMonitoring(
        LauncherCliResponse response,
        LauncherCliMultiplayerSession initialStatus)
    {
        StopSteamSessionMonitoring(clearStatus: false);
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
        UpdateLobbyDetails(status);
        if (status.Phase == "Error" &&
            !string.IsNullOrWhiteSpace(status.ErrorText))
        {
            SetError($"Steam error: {status.ErrorText}");
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
                $"{member.SteamId}|{member.IsHost}|{member.IsLocal}|{member.Name}"));
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

        IsInLobby = true;
    }

    private void ClearLobbyDetails()
    {
        IsInLobby = false;
        LobbyTitleText = string.Empty;
        LobbyIdText = string.Empty;
        LobbyPlayersLabel = string.Empty;
        LobbyBoneyardText = string.Empty;
        LobbyConnectionDetailsText = string.Empty;
        lobbyMembersSignature_ = string.Empty;
        LobbyMembers.Clear();
        LobbySharedMods.Clear();
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

        var privacy = HostPrivacyPublic ? "public" : "friends";
        IsHostSetupOpen = false;

        await ExecuteUiCommandAsync(
            LauncherUiCommandMode.HostSteam,
            "The launcher starts the lobby.",
            hostOptions: new LauncherHostOptions(privacy));
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
        TryLaunchPendingLobbyJoin();
    }

    public void QueueWebsiteLobbyJoin(LauncherJoinActivation activation)
    {
        DirectoryUrl = activation.DirectoryBaseUrl;
        LobbyId = activation.LobbyId.ToString();
        client_.UseWebsiteLobbyJoin(activation.DirectoryBaseUrl, activation.Ticket);
        pendingLobbyJoinId_ = activation.LobbyId;
        TryLaunchPendingLobbyJoin();
    }

    private void JoinLobbyDirect()
    {
        client_.UseDirectLobbyJoin();
        _ = JoinLobbyWithModCheckAsync($"The launcher joins lobby {LobbyId}.");
    }

    private void TryLaunchPendingLobbyJoin()
    {
        if (pendingLobbyJoinId_ is not { } lobbyId || !CanLaunch())
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

        IsBusy = true;
        StatusText = "The launcher checks the host's mod list.";
        CommandPreviewText = client_.BuildCommandPreview(LauncherUiCommandMode.JoinPreview);
        LauncherUiInvocationResult invocation;
        try
        {
            invocation = await client_.InvokeAsync(LauncherUiCommandMode.JoinPreview);
        }
        catch (Exception ex)
        {
            SetError(ex.Message);
            StatusText = "The command failed. Read the error message.";
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
            await ExecuteUiCommandAsync(LauncherUiCommandMode.JoinSteam, joinStatusText);
            return;
        }

        if (preview.HostProtocolVersion is { } hostProtocol &&
            hostProtocol != preview.LocalProtocolVersion)
        {
            SetError(
                "The host is on a different Solomon Dark Revived version " +
                $"(host: {preview.HostLoaderVersion ?? "unknown"}, you: {Version}). " +
                "Both players need the same launcher version to play together.");
            StatusText = "Join canceled: the game versions do not match.";
            return;
        }

        if (preview.UnavailableCount > 0)
        {
            var unavailable = preview.Mods
                .Where(mod => mod.State == "unavailable")
                .Select(mod => $"{mod.DisplayName} {mod.Version}");
            SetError(
                "Mod list mismatch that can't be repaired automatically. The host has mods " +
                $"that are not available for download: {string.Join(", ", unavailable)}. " +
                "Ask the host to publish them on the website or disable them.");
            StatusText = "Join canceled: the host's mods are not downloadable.";
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
                if (mod.DownloadSizeBytes is { } size)
                {
                    line += $" — {FormatSize(size)}";
                }
                if (!string.IsNullOrWhiteSpace(mod.InstalledVersion))
                {
                    line += mod.InstalledVersion == mod.Version
                        ? " (replaces your local copy)"
                        : $" (you have {mod.InstalledVersion})";
                }
                ModDownloadItems.Add(line);
            }

            ModDownloadPromptText =
                "The host has mods enabled, would you like to download them to join?";
            consentedJoinStatusText_ = joinStatusText;
            StatusText = "Waiting for your mod download choice.";
            IsModDownloadPromptOpen = true;
            return;
        }

        StatusText = preview.Mods.Count == 0
            ? "The host plays without mods."
            : "Your mods already match the host.";
        await ExecuteUiCommandAsync(LauncherUiCommandMode.JoinSteam, joinStatusText);
    }

    private void ConfirmModDownload()
    {
        if (!IsModDownloadPromptOpen)
        {
            return;
        }

        var joinStatusText = consentedJoinStatusText_ ??
            $"The launcher joins lobby {LobbyId}.";
        consentedJoinStatusText_ = null;
        IsModDownloadPromptOpen = false;
        _ = ExecuteUiCommandAsync(
            LauncherUiCommandMode.JoinSteam,
            joinStatusText);
    }

    private void DeclineModDownload()
    {
        if (!IsModDownloadPromptOpen)
        {
            return;
        }

        consentedJoinStatusText_ = null;
        pendingLobbyMods_ = null;
        IsModDownloadPromptOpen = false;
        StatusText = "Join canceled. No mods were downloaded.";
        TryLaunchPendingLobbyJoin();
    }

    private static string FormatSize(long bytes) => bytes switch
    {
        >= 1024 * 1024 => $"{bytes / (1024.0 * 1024.0):0.#} MB",
        >= 1024 => $"{bytes / 1024.0:0.#} KB",
        _ => $"{bytes} bytes"
    };

    private void StopSteamInviteListener()
    {
        steamInviteListener_.Stop();
    }

    private void StartSteamInviteListener()
    {
        if (activeGameProcessId_ == 0)
        {
            steamInviteListener_.Start();
        }
    }

    private void StopSteamSessionMonitoring(bool clearStatus)
    {
        steamSessionMonitorCancellation_?.Cancel();
        steamSessionMonitorCancellation_?.Dispose();
        steamSessionMonitorCancellation_ = null;
        if (clearStatus)
        {
            ClearSteamSessionStatus();
        }
    }

    private void ClearSteamSessionStatus()
    {
        pendingLobbyMods_ = null;
        ClearLobbyDetails();
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
            "hub" => "In Hub",
            "session" => "In Match",
            "loading" => "Loading",
            "results" => "Results",
            _ => "Starting"
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
        }

        Mods.Clear();
        foreach (var mod in response.Mods)
        {
            var viewModel = new ModItemViewModel(mod);
            viewModel.ToggleRequested += OnModToggleRequested;
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

    private static bool CanOpenFolder(string? path)
    {
        return !string.IsNullOrWhiteSpace(path) && Directory.Exists(path);
    }

    private static void OpenFolder(string? path)
    {
        if (!CanOpenFolder(path))
        {
            return;
        }

        Process.Start(new ProcessStartInfo(path!) { UseShellExecute = true });
    }

    private void RaiseCommandStates()
    {
        RefreshCommand.RaiseCanExecuteChanged();
        HostSteamCommand.RaiseCanExecuteChanged();
        JoinSteamCommand.RaiseCanExecuteChanged();
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
    }

    private void UpdateLaunchPreview()
    {
        CommandPreviewText = client_.BuildCommandPreview(LauncherUiCommandMode.HostSteam);
    }
}
