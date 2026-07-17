using System.Collections.ObjectModel;
using System.Diagnostics;
using System.Reflection;
using System.Text;
using Microsoft.Win32;
using SolomonDarkModLauncher.UI.Infrastructure;

namespace SolomonDarkModLauncher.UI.ViewModels;

internal sealed class MainWindowViewModel : ViewModelBase, IDisposable
{
    private readonly LauncherUiCommandClient client_;
    private readonly StringBuilder transcriptBuilder_ = new();
    private LauncherCliResponse? lastResponse_;
    private bool isBusy_;
    private bool hasError_;
    private string errorMessage_ = string.Empty;
    private string statusText_ = "Loading…";
    private string modSummaryText_ = string.Empty;
    private string commandPreviewText_ = string.Empty;
    private string transcriptText_ = string.Empty;
    private string instanceName_;
    private bool debugUiEnabled_;
    private string lobbyId_;
    private string gameDirectory_;
    private bool isGameReady_;
    private CancellationTokenSource? steamSessionMonitorCancellation_;
    private bool hasSteamSession_;
    private bool isSteamFriendConnected_;
    private string steamConnectionText_ = string.Empty;
    private bool isLobbyBrowserOpen_;
    private string lobbyBrowserSummaryText_ = string.Empty;
    private string lobbyBrowserStatusText_ = string.Empty;
    private string directoryLobbiesSignature_ = string.Empty;
    private string directoryUrl_;
    private CancellationTokenSource? lobbyBrowserPollCancellation_;

    public MainWindowViewModel(LauncherUiCommandClient client)
    {
        client_ = client;
        instanceName_ = client.InstanceName;
        debugUiEnabled_ = client.DebugUiEnabled;
        lobbyId_ = client.LobbyId;
        gameDirectory_ = client.GameDirectory;
        directoryUrl_ = client.DirectoryUrl;

        RefreshCommand = new RelayCommand(_ => _ = RefreshAsync(), _ => CanInteract());
        BrowseLobbiesCommand = new RelayCommand(_ => ToggleLobbyBrowser());
        RefreshLobbiesCommand = new RelayCommand(
            _ => _ = RefreshLobbyDirectoryAsync(CancellationToken.None),
            _ => IsLobbyBrowserOpen);
        HostSteamCommand = new RelayCommand(
            _ => _ = ExecuteActionAsync(
                LauncherUiCommandMode.HostSteam,
                "Creating lobby…"),
            _ => CanLaunch());
        JoinSteamCommand = new RelayCommand(
            _ => _ = ExecuteActionAsync(
                LauncherUiCommandMode.JoinSteam,
                string.IsNullOrWhiteSpace(LobbyId)
                    ? "Launching — waiting for your friend's invite…"
                    : $"Joining lobby {LobbyId}…"),
            _ => CanLaunch());
        LaunchSinglePlayerCommand = new RelayCommand(
            _ => _ = ExecuteActionAsync(
                LauncherUiCommandMode.LaunchSinglePlayer,
                "Launching…"),
            _ => CanLaunch());
        StageCommand = new RelayCommand(_ => _ = ExecuteActionAsync(LauncherUiCommandMode.Stage, "Staging mods…"), _ => CanLaunch());
        ApplyInstanceCommand = new RelayCommand(_ => _ = ApplyInstanceAsync(), _ => CanInteract());
        ChooseGameFolderCommand = new RelayCommand(_ => ChooseGameFolder(), _ => CanInteract());
        OpenModsFolderCommand = new RelayCommand(_ => OpenFolder(lastResponse_?.Configuration?.ModsRoot), _ => CanOpenFolder(lastResponse_?.Configuration?.ModsRoot));
        OpenStageFolderCommand = new RelayCommand(_ => OpenFolder(lastResponse_?.Configuration?.StageRoot), _ => CanOpenFolder(lastResponse_?.Configuration?.StageRoot));
        OpenProfileFolderCommand = new RelayCommand(_ => OpenFolder(lastResponse_?.Configuration?.ProfileRoot), _ => CanOpenFolder(lastResponse_?.Configuration?.ProfileRoot));
        OpenGameFolderCommand = new RelayCommand(_ => OpenFolder(GameDirectory), _ => CanOpenFolder(GameDirectory));

        UpdateLaunchPreview();
        if (string.IsNullOrWhiteSpace(GameDirectory))
        {
            StatusText = "Locate your game folder to get started";
        }
        else
        {
            _ = RefreshAsync();
        }
    }

    public ObservableCollection<ModItemViewModel> Mods { get; } = [];

    public ObservableCollection<DirectoryLobbyViewModel> DirectoryLobbies { get; } = [];

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

    public bool HasSteamSession
    {
        get => hasSteamSession_;
        private set => SetProperty(ref hasSteamSession_, value);
    }

    public bool IsSteamFriendConnected
    {
        get => isSteamFriendConnected_;
        private set => SetProperty(ref isSteamFriendConnected_, value);
    }

    public string SteamConnectionText
    {
        get => steamConnectionText_;
        private set => SetProperty(ref steamConnectionText_, value);
    }

    public bool IsLobbyBrowserOpen
    {
        get => isLobbyBrowserOpen_;
        private set
        {
            if (SetProperty(ref isLobbyBrowserOpen_, value))
            {
                RefreshLobbiesCommand.RaiseCanExecuteChanged();
            }
        }
    }

    public string LobbyBrowserSummaryText
    {
        get => lobbyBrowserSummaryText_;
        private set => SetProperty(ref lobbyBrowserSummaryText_, value);
    }

    public string LobbyBrowserStatusText
    {
        get => lobbyBrowserStatusText_;
        private set => SetProperty(ref lobbyBrowserStatusText_, value);
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
            if (IsLobbyBrowserOpen)
            {
                _ = RefreshLobbyDirectoryAsync(CancellationToken.None);
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
            }
        }
    }

    public string HostButtonText => IsBusy ? "Working…" : "Host Game";

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
    public RelayCommand BrowseLobbiesCommand { get; }
    public RelayCommand RefreshLobbiesCommand { get; }
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

    private bool CanLaunch() => CanInteract() && isGameReady_;

    private void ChooseGameFolder()
    {
        var dialog = new OpenFolderDialog
        {
            Title = "Choose the Solomon Dark 0.72.5 folder containing SolomonDark.exe",
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
            statusText: "Checking mods…");
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
            statusText: $"Switching to instance '{InstanceName}'…");
    }

    private async Task ExecuteActionAsync(LauncherUiCommandMode mode, string statusText)
    {
        await ExecuteUiCommandAsync(mode, statusText);
    }

    private async Task ExecuteUiCommandAsync(
        LauncherUiCommandMode mode,
        string statusText,
        string? targetModId = null)
    {
        if (mode is LauncherUiCommandMode.HostSteam or
            LauncherUiCommandMode.JoinSteam or
            LauncherUiCommandMode.LaunchSinglePlayer or
            LauncherUiCommandMode.Stage)
        {
            StopSteamSessionMonitoring(clearStatus: true);
        }

        IsBusy = true;
        StatusText = statusText;
        CommandPreviewText = client_.BuildCommandPreview(mode, targetModId);
        LauncherUiInvocationResult invocation;
        try
        {
            invocation = await client_.InvokeAsync(mode, targetModId);
        }
        catch (Exception ex)
        {
            SetError(ex.Message);
            StatusText = "Failed — see the message above";
            IsBusy = false;
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
            SetError(invocation.ErrorMessage ?? "Launcher command failed.");
            StatusText = "Failed — see the message above";
            IsBusy = false;
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
        StatusText = mode switch
        {
            LauncherUiCommandMode.ListMods => "Ready",
            LauncherUiCommandMode.Stage => "Stage built",
            LauncherUiCommandMode.LaunchSinglePlayer => "Game running",
            LauncherUiCommandMode.HostSteam => DescribeSteamHost(multiplayer),
            LauncherUiCommandMode.JoinSteam => DescribeSteamJoin(multiplayer),
            LauncherUiCommandMode.EnableMod => "Mod enabled",
            LauncherUiCommandMode.DisableMod => "Mod disabled",
            _ => "Ready"
        };
        IsBusy = false;
    }

    private void StartSteamSessionMonitoring(
        LauncherCliResponse response,
        LauncherCliMultiplayerSession initialStatus)
    {
        StopSteamSessionMonitoring(clearStatus: false);
        ApplySteamSessionStatus(initialStatus);

        var stageRuntimeRootPath = response.Stage?.StageRuntimeRootPath;
        var processId = response.Launch?.ProcessId ?? 0;
        if (string.IsNullOrWhiteSpace(stageRuntimeRootPath) ||
            string.IsNullOrWhiteSpace(initialStatus.LaunchToken) ||
            processId <= 0)
        {
            return;
        }

        var monitorCancellation = new CancellationTokenSource();
        steamSessionMonitorCancellation_ = monitorCancellation;
        _ = MonitorSteamSessionAsync(
            stageRuntimeRootPath,
            initialStatus.LaunchToken,
            processId,
            monitorCancellation);
    }

    private async Task MonitorSteamSessionAsync(
        string stageRuntimeRootPath,
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
                    stageRuntimeRootPath,
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
        HasSteamSession = status.Enabled;
        IsSteamFriendConnected =
            status.Enabled &&
            status.Phase == "Connected" &&
            status.AuthenticatedPeerCount > 0;

        if (IsSteamFriendConnected)
        {
            SteamConnectionText = status.AuthenticatedPeerCount == 1
                ? "Connected — 1 friend in the lobby"
                : $"Connected — {status.AuthenticatedPeerCount} friends in the lobby";
            return;
        }

        SteamConnectionText = status.Phase switch
        {
            "WaitingForInvite" => "Waiting for a Steam invite…",
            "JoiningLobby" => "Joining lobby…",
            "LobbyReady" when status.IsHost => "Lobby open — waiting for friends",
            "Error" when !string.IsNullOrWhiteSpace(status.ErrorText) =>
                $"Steam error — {status.ErrorText}",
            _ when !string.IsNullOrWhiteSpace(status.StatusText) => status.StatusText,
            _ => "Starting Steam session…"
        };
    }

    private void ToggleLobbyBrowser()
    {
        if (IsLobbyBrowserOpen)
        {
            CloseLobbyBrowser();
            return;
        }

        IsLobbyBrowserOpen = true;
        var pollCancellation = new CancellationTokenSource();
        lobbyBrowserPollCancellation_ = pollCancellation;
        _ = PollLobbyDirectoryAsync(pollCancellation);
    }

    private void CloseLobbyBrowser()
    {
        lobbyBrowserPollCancellation_?.Cancel();
        lobbyBrowserPollCancellation_?.Dispose();
        lobbyBrowserPollCancellation_ = null;
        IsLobbyBrowserOpen = false;
    }

    private async Task PollLobbyDirectoryAsync(CancellationTokenSource pollCancellation)
    {
        var cancellationToken = pollCancellation.Token;
        try
        {
            while (!cancellationToken.IsCancellationRequested)
            {
                await RefreshLobbyDirectoryAsync(cancellationToken);
                await Task.Delay(TimeSpan.FromSeconds(10), cancellationToken);
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
        }
    }

    private async Task RefreshLobbyDirectoryAsync(CancellationToken cancellationToken)
    {
        if (DirectoryLobbies.Count == 0)
        {
            LobbyBrowserStatusText = "Consulting the directory…";
        }

        DirectoryLobbyList list;
        try
        {
            list = await LobbyDirectoryClient.ListAsync(client_.DirectoryUrl, cancellationToken);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            return;
        }
        catch (Exception)
        {
            DirectoryLobbies.Clear();
            directoryLobbiesSignature_ = string.Empty;
            LobbyBrowserSummaryText = string.Empty;
            LobbyBrowserStatusText =
                "The lobby directory is unreachable. Steam invites and Lobby IDs still work.";
            return;
        }

        var signature = string.Join(
            "\n",
            list.Items.Select(lobby =>
                $"{lobby.Id}|{lobby.HostPlayer}|{lobby.Access}|{lobby.Players}|{lobby.MaxPlayers}|" +
                $"{lobby.Game.Phase}|{lobby.Game.BoneyardName}|{lobby.Game.Wave}|{lobby.Game.StatusText}"));
        if (signature != directoryLobbiesSignature_)
        {
            directoryLobbiesSignature_ = signature;
            DirectoryLobbies.Clear();
            foreach (var lobby in list.Items)
            {
                DirectoryLobbies.Add(new DirectoryLobbyViewModel(
                    lobby,
                    JoinDirectoryLobby,
                    OpenDirectoryLobbyOnWebsite));
            }
        }

        LobbyBrowserSummaryText = list.Items.Count == 0
            ? string.Empty
            : $"{list.Items.Count} open · {list.PlayerCount} playing";
        LobbyBrowserStatusText = list.Items.Count == 0
            ? "No open lobbies right now. Friends' games arrive as Steam invites either way."
            : string.Empty;
    }

    private void JoinDirectoryLobby(DirectoryLobbyViewModel lobby)
    {
        if (lobby.LobbyId is null || !CanLaunch())
        {
            return;
        }

        LobbyId = lobby.LobbyId;
        CloseLobbyBrowser();
        _ = ExecuteActionAsync(
            LauncherUiCommandMode.JoinSteam,
            $"Joining {lobby.HostName}'s lobby…");
    }

    private void OpenDirectoryLobbyOnWebsite(DirectoryLobbyViewModel lobby)
    {
        var baseUrl = client_.DirectoryUrl.TrimEnd('/');
        Process.Start(new ProcessStartInfo($"{baseUrl}/classes?lobby={lobby.DirectoryId}")
        {
            UseShellExecute = true
        });
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
        HasSteamSession = false;
        IsSteamFriendConnected = false;
        SteamConnectionText = string.Empty;
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
        CloseLobbyBrowser();
    }

    private static string DescribeSteamHost(LauncherCliMultiplayerSession? multiplayer)
    {
        if (multiplayer is null || multiplayer.LobbyId == 0)
        {
            return "Host running";
        }
        if (multiplayer.InviteDialogOpened)
        {
            return $"Lobby {multiplayer.LobbyId} open — pick friends in the Steam invite window";
        }
        return multiplayer.OverlayEnabled
            ? $"Lobby {multiplayer.LobbyId} open — invite friends via Steam, or share the Lobby ID"
            : $"Lobby {multiplayer.LobbyId} open — Steam overlay is off, so share the Lobby ID";
    }

    private static string DescribeSteamJoin(LauncherCliMultiplayerSession? multiplayer)
    {
        if (multiplayer?.Phase == "WaitingForInvite")
        {
            return "Game running — accept your friend's Steam invite";
        }
        return multiplayer?.StatusText ?? "Joining…";
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
        ModSummaryText = total == 0 ? string.Empty : $"{enabled} of {total} enabled";
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
            desiredState ? $"Enabling {mod.Name}…" : $"Disabling {mod.Name}…",
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
