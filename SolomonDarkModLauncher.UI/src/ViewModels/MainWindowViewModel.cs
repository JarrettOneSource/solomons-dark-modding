using System.Collections.ObjectModel;
using System.Diagnostics;
using System.Text;
using SolomonDarkModLauncher.UI.Infrastructure;

namespace SolomonDarkModLauncher.UI.ViewModels;

internal sealed class MainWindowViewModel : ViewModelBase
{
    private readonly LauncherUiCommandClient client_;
    private readonly StringBuilder transcriptBuilder_ = new();
    private LauncherCliResponse? lastResponse_;
    private bool isBusy_;
    private bool hasError_;
    private string errorMessage_ = string.Empty;
    private string statusText_ = "Loading launcher state...";
    private string summaryText_ = string.Empty;
    private string modSummaryText_ = string.Empty;
    private string instanceSummaryText_ = string.Empty;
    private string commandPreviewText_ = string.Empty;
    private string transcriptText_ = string.Empty;
    private string instanceName_;
    private bool debugUiEnabled_;
    private string lobbyId_;

    public MainWindowViewModel(LauncherUiCommandClient client)
    {
        client_ = client;
        instanceName_ = client.InstanceName;
        debugUiEnabled_ = client.DebugUiEnabled;
        lobbyId_ = client.LobbyId;

        RefreshCommand = new RelayCommand(_ => _ = RefreshAsync(), _ => CanInteract());
        HostSteamCommand = new RelayCommand(
            _ => _ = ExecuteActionAsync(
                LauncherUiCommandMode.HostSteam,
                "Creating Steam lobby and launching host..."),
            _ => CanInteract());
        JoinSteamCommand = new RelayCommand(
            _ => _ = ExecuteActionAsync(
                LauncherUiCommandMode.JoinSteam,
                string.IsNullOrWhiteSpace(LobbyId)
                    ? "Launching and waiting for a Steam friend invite..."
                    : $"Joining Steam lobby {LobbyId}..."),
            _ => CanInteract());
        LaunchSinglePlayerCommand = new RelayCommand(
            _ => _ = ExecuteActionAsync(
                LauncherUiCommandMode.LaunchSinglePlayer,
                "Launching single player..."),
            _ => CanInteract());
        StageCommand = new RelayCommand(_ => _ = ExecuteActionAsync(LauncherUiCommandMode.Stage, "Building stage..."), _ => CanInteract());
        ApplyInstanceCommand = new RelayCommand(_ => _ = ApplyInstanceAsync(), _ => CanInteract());
        OpenModsFolderCommand = new RelayCommand(_ => OpenFolder(lastResponse_?.Configuration?.ModsRoot), _ => CanOpenFolder(lastResponse_?.Configuration?.ModsRoot));
        OpenStageFolderCommand = new RelayCommand(_ => OpenFolder(lastResponse_?.Configuration?.StageRoot), _ => CanOpenFolder(lastResponse_?.Configuration?.StageRoot));
        OpenProfileFolderCommand = new RelayCommand(_ => OpenFolder(lastResponse_?.Configuration?.ProfileRoot), _ => CanOpenFolder(lastResponse_?.Configuration?.ProfileRoot));
        OpenGameFolderCommand = new RelayCommand(_ => OpenFolder(lastResponse_?.Configuration?.GameDirectory), _ => CanOpenFolder(lastResponse_?.Configuration?.GameDirectory));

        UpdateLaunchPreview();
        _ = RefreshAsync();
    }

    public ObservableCollection<ModItemViewModel> Mods { get; } = [];

    public string Title => "Solomon Dark Mod Manager";
    public string Subtitle => "Standalone wrapper over the launcher CLI.";

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

    public string SummaryText
    {
        get => summaryText_;
        private set => SetProperty(ref summaryText_, value);
    }

    public string ModSummaryText
    {
        get => modSummaryText_;
        private set => SetProperty(ref modSummaryText_, value);
    }

    public string InstanceSummaryText
    {
        get => instanceSummaryText_;
        private set => SetProperty(ref instanceSummaryText_, value);
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

    public string HostButtonText => IsBusy ? "Working..." : "Host & Invite Friends";

    public string WorkspaceRoot => lastResponse_?.Configuration?.WorkspaceRoot ?? "(unresolved)";
    public string GameDirectory => lastResponse_?.Configuration?.GameDirectory ?? "(unresolved)";
    public string ModsRoot => lastResponse_?.Configuration?.ModsRoot ?? "(unresolved)";
    public string StageRoot => lastResponse_?.Configuration?.StageRoot ?? "(unresolved)";
    public string ProfileRoot => lastResponse_?.Configuration?.ProfileRoot ?? "(unresolved)";
    public string RuntimeProfile => lastResponse_?.Configuration?.RuntimeProfile ?? "(unresolved)";

    public RelayCommand RefreshCommand { get; }
    public RelayCommand HostSteamCommand { get; }
    public RelayCommand JoinSteamCommand { get; }
    public RelayCommand LaunchSinglePlayerCommand { get; }
    public RelayCommand StageCommand { get; }
    public RelayCommand ApplyInstanceCommand { get; }
    public RelayCommand OpenModsFolderCommand { get; }
    public RelayCommand OpenStageFolderCommand { get; }
    public RelayCommand OpenProfileFolderCommand { get; }
    public RelayCommand OpenGameFolderCommand { get; }

    private bool CanInteract() => !IsBusy;

    private async Task RefreshAsync()
    {
        await ExecuteUiCommandAsync(
            LauncherUiCommandMode.ListMods,
            statusText: "Refreshing mod catalog...");
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
            statusText: $"Switching to instance '{InstanceName}'...");
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
            StatusText = "Command failed";
            IsBusy = false;
            return;
        }

        AppendTranscript(invocation);

        if (!invocation.Succeeded || invocation.Response is null)
        {
            SetError(invocation.ErrorMessage ?? "Launcher command failed.");
            StatusText = "Command failed";
            IsBusy = false;
            return;
        }

        ClearError();
        lastResponse_ = invocation.Response;
        UpdateFromResponse(invocation.Response);
        var multiplayer = invocation.Response.Launch?.MultiplayerSession;
        if (mode == LauncherUiCommandMode.HostSteam && multiplayer?.LobbyId > 0)
        {
            LobbyId = multiplayer.LobbyId.ToString();
        }
        StatusText = mode switch
        {
            LauncherUiCommandMode.ListMods => "Catalog refreshed",
            LauncherUiCommandMode.Stage => "Stage completed",
            LauncherUiCommandMode.LaunchSinglePlayer => "Single-player game launched",
            LauncherUiCommandMode.HostSteam => DescribeSteamHost(multiplayer),
            LauncherUiCommandMode.JoinSteam => DescribeSteamJoin(multiplayer),
            LauncherUiCommandMode.EnableMod => "Mod enabled",
            LauncherUiCommandMode.DisableMod => "Mod disabled",
            _ => "Ready"
        };
        IsBusy = false;
    }

    private static string DescribeSteamHost(LauncherCliMultiplayerSession? multiplayer)
    {
        if (multiplayer is null || multiplayer.LobbyId == 0)
        {
            return "Steam host launched";
        }
        if (multiplayer.InviteDialogOpened)
        {
            return $"Steam lobby {multiplayer.LobbyId} ready; invite dialog opened";
        }
        return multiplayer.OverlayEnabled
            ? $"Steam lobby {multiplayer.LobbyId} ready; invite dialog did not open, " +
              "so share the Lobby ID or use Steam Friends"
            : $"Steam lobby {multiplayer.LobbyId} ready; Steam overlay unavailable, " +
              "so share the Lobby ID or use Steam Friends";
    }

    private static string DescribeSteamJoin(LauncherCliMultiplayerSession? multiplayer)
    {
        if (multiplayer?.Phase == "WaitingForInvite")
        {
            return "Steam client launched; waiting for a friend invite";
        }
        return multiplayer?.StatusText ?? "Steam lobby join launched";
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

        var discovered = response.Mods.Count;
        var enabled = response.Mods.Count(mod => mod.Enabled);
        ModSummaryText = $"{discovered} mod{(discovered == 1 ? string.Empty : "s")} discovered  ·  {enabled} enabled";
        SummaryText = ModSummaryText;
        var instance = response.Configuration?.Instance ?? client_.InstanceName;
        var runtimeProfile = response.Configuration?.RuntimeProfile ?? "(unresolved)";
        DebugUiEnabled = response.Configuration?.LoaderDebugUi ?? true;
        InstanceSummaryText =
            $"Instance {instance}  ·  runtime profile {runtimeProfile}  ·  debug UI {(DebugUiEnabled ? "on" : "off")}";

        OnPropertyChanged(nameof(WorkspaceRoot));
        OnPropertyChanged(nameof(GameDirectory));
        OnPropertyChanged(nameof(ModsRoot));
        OnPropertyChanged(nameof(StageRoot));
        OnPropertyChanged(nameof(ProfileRoot));
        OnPropertyChanged(nameof(RuntimeProfile));
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
            desiredState ? $"Enabling {mod.Id}..." : $"Disabling {mod.Id}...",
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
