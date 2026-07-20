using System.Collections.ObjectModel;
using System.Diagnostics;
using System.Reflection;
using System.Text;
using System.Windows;
using Microsoft.Win32;
using SolomonDarkModLauncher.UI.Infrastructure;

namespace SolomonDarkModLauncher.UI.ViewModels;

internal sealed class MainWindowViewModel : ViewModelBase, IDisposable
{
    private readonly LauncherUiCommandClient client_;
    private readonly SteamInviteListenerClient steamInviteListener_ = new();
    private readonly StringBuilder transcriptBuilder_ = new();
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

    public MainWindowViewModel(LauncherUiCommandClient client)
    {
        client_ = client;
        instanceName_ = client.InstanceName;
        debugUiEnabled_ = client.DebugUiEnabled;
        lobbyId_ = client.LobbyId;
        gameDirectory_ = client.GameDirectory;
        directoryUrl_ = client.DirectoryUrl;

        RefreshCommand = new RelayCommand(_ => _ = RefreshAsync(), _ => CanInteract());
        HowToPlayCommand = new RelayCommand(_ => IsHowToPlayOpen = true);
        HostSteamCommand = new RelayCommand(_ => OpenHostSetup(), _ => CanLaunch());
        JoinSteamCommand = new RelayCommand(
            _ => _ = ExecuteActionAsync(
                LauncherUiCommandMode.JoinSteam,
                $"The launcher joins lobby {LobbyId}."),
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

        steamInviteListener_.NotificationReceived += OnSteamInviteNotification;
        steamInviteListener_.Start();

        UpdateLaunchPreview();
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

    public bool IsHostSetupOpen
    {
        get => isHostSetupOpen_;
        private set => SetProperty(ref isHostSetupOpen_, value);
    }

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

    private bool CanInteract() => !IsBusy;

    private bool CanLaunch() =>
        CanInteract() && isGameReady_ && activeGameProcessId_ == 0;

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
        if (mode is LauncherUiCommandMode.HostSteam or LauncherUiCommandMode.JoinSteam &&
            multiplayer is not null)
        {
            StartSteamSessionMonitoring(invocation.Response, multiplayer);
        }
        var processId = invocation.Response.Launch?.ProcessId ?? 0;
        if (launchesGame && processId > 0)
        {
            activeGameProcessId_ = processId;
            RaiseCommandStates();
            _ = MonitorGameProcessExitAsync(processId);
        }
        StatusText = mode switch
        {
            LauncherUiCommandMode.ListMods => "Ready",
            LauncherUiCommandMode.Stage => "Stage ready",
            LauncherUiCommandMode.LaunchSinglePlayer => "Game started",
            LauncherUiCommandMode.HostSteam => "Ready",
            LauncherUiCommandMode.JoinSteam => "Ready",
            LauncherUiCommandMode.EnableMod => "Ready",
            LauncherUiCommandMode.DisableMod => "Ready",
            _ => "Ready"
        };
        IsBusy = false;
        TryLaunchPendingLobbyJoin();
    }

    private async Task MonitorGameProcessExitAsync(int processId)
    {
        while (IsProcessRunning(processId))
        {
            await Task.Delay(500);
        }

        await Application.Current.Dispatcher.InvokeAsync(() =>
        {
            if (activeGameProcessId_ != processId)
            {
                return;
            }

            activeGameProcessId_ = 0;
            RaiseCommandStates();
            StartSteamInviteListener();
            TryLaunchPendingLobbyJoin();
        });
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
        LobbyId = lobbyId.ToString();
        pendingLobbyJoinId_ = lobbyId;
        TryLaunchPendingLobbyJoin();
    }

    private void TryLaunchPendingLobbyJoin()
    {
        if (pendingLobbyJoinId_ is not { } lobbyId || !CanLaunch())
        {
            return;
        }

        pendingLobbyJoinId_ = null;
        LobbyId = lobbyId.ToString();
        _ = ExecuteActionAsync(
            LauncherUiCommandMode.JoinSteam,
            $"The launcher joins lobby {lobbyId}.");
    }

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
        StopSteamSessionMonitoring(clearStatus: false);
        steamInviteListener_.NotificationReceived -= OnSteamInviteNotification;
        steamInviteListener_.Dispose();
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
    }

    private void UpdateLaunchPreview()
    {
        CommandPreviewText = client_.BuildCommandPreview(LauncherUiCommandMode.HostSteam);
    }
}
