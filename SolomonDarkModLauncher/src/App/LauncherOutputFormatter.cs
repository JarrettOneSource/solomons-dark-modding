using System.Text;
using SolomonDarkModLauncher.Commands;
using SolomonDarkModLauncher.Launch;
using SolomonDarkModLauncher.Mods;
using SolomonDarkModLauncher.Staging;
using SolomonDarkModLauncher.Target;

namespace SolomonDarkModLauncher.App;

internal static class LauncherOutputFormatter
{
    public static string FormatHelp()
    {
        return string.Join(Environment.NewLine,
        [
            "SolomonDarkModLauncher",
            string.Empty,
            "Commands:",
            "  launch               Mirror Solomon Dark into the stage root, stage enabled overlay or runtime mods, start the staged game, inject SolomonDarkModLoader.dll, and wait for loader startup completion.",
            "  stage                Mirror Solomon Dark into the stage root and stage enabled overlay or runtime mods without launching. A concrete multiplayer join also synchronizes the website host mod set.",
            "  list-mods            Discover overlay or runtime manifests and print enabled or disabled mods.",
            "  directory-auth       Verify the active Steam user with the lobby directory.",
            "  join-preview         Compare a lobby's website mod list against local mods without launching. Requires --lobby-id.",
            "  enable-mod <mod-id>  Persistently enable a discovered overlay or runtime mod.",
            "  disable-mod <mod-id> Persistently disable a discovered overlay or runtime mod.",
            string.Empty,
            "Options:",
            "  --json                  Emit structured JSON output for wrapper tools.",
            "  --instance <name>       Use a named launcher instance. Default uses runtime/; named instances use runtime/instances/<name>/.",
            "  --game-dir <path>       Override the Solomon Dark install directory.",
            "  --mods-root <path>      Override the mods directory.",
            "  --runtime-root <path>   Override the runtime directory used for staged files and mod state.",
            "  --stage-root <path>     Override the staged launch directory.",
            "  --runtime-profile <name> Select the staged runtime feature profile. Default: full. Supported: full, bootstrap_only.",
            "  --runtime-flag <k=v>    Override one staged runtime feature flag. May be passed multiple times.",
            "  --temporary-profile     Launch with a fresh temporary APPDATA/LOCALAPPDATA and staged savegames target.",
            "  --savegames-root <path> Use this launcher-owned directory for game saves.",
            "  --steam-appid <id>      Override steam_appid.txt. Default: 3362180.",
            "  --steam-api-dll <path>  Override the x86 steam_api.dll used when the mirrored game does not already ship one.",
            "  --multiplayer <mode>    Select off, host, or join.",
            "  --lobby-id <id>         Join a specific Steam lobby. Without this option, wait for a lobby selection through Steam.",
            "  --lobby-privacy <mode>  Host a public or friends-only Steam lobby. Default: friends.",
            "  --directory-url <url>   Override the HTTPS mod-directory origin used automatically before lobby joins.",
            "  --lobby-ticket <token>  Signed password-lobby ticket supplied by the website.",
            "  --invite-steam-id <id>  Host development option: send the lobby to one Steam user if the overlay is unavailable.",
            "  --max-players <2-4>     Set the host lobby capacity. Default: 4.",
            "  --no-invite-dialog      Host without automatically opening Steam's friend invite dialog.",
            "  --help                  Show this help text.",
            string.Empty,
            "Current scope:",
            "  overlay mods plus staged runtime-mod metadata",
            "  staged file mirroring",
            "  isolated profile roots under runtime/",
            "  x86 native loader injection on launch",
            "  public or friends-only Steam lobbies, invite/lobby-ID join flow, compatibility handshake, and Steam Networking Messages transport",
            "  optional website discovery that never carries gameplay traffic",
            "  staged runtime flags and Lua bootstrap manifests",
            "  embedded Lua runtime with sd.runtime, sd.events, sd.ui, sd.input, sd.hub, and sd.bots APIs",
            "  in-process memory-access layer and D3D9 overlay backbone for UI automation"
        ]);
    }

    public static string FormatExecution(LauncherCommandExecution execution)
    {
        var builder = new StringBuilder();

        switch (execution.Command.Mode)
        {
            case LauncherMode.ListMods:
                AppendConfiguration(builder, execution.Configuration);
                AppendModUpdates(builder, execution.ModUpdate);
                AppendModList(builder, execution.Catalog);
                break;
            case LauncherMode.Stage:
                AppendConfiguration(builder, execution.Configuration);
                AppendModUpdates(builder, execution.ModUpdate);
                AppendLobbyModSync(builder, execution.LobbyModSync);
                AppendModList(builder, execution.Catalog);
                AppendStageResult(builder, execution.StageResult!);
                break;
            case LauncherMode.Launch:
                AppendConfiguration(builder, execution.Configuration);
                AppendModUpdates(builder, execution.ModUpdate);
                AppendLobbyModSync(builder, execution.LobbyModSync);
                AppendModList(builder, execution.Catalog);
                AppendStageResult(builder, execution.StageResult!);
                AppendLaunchResult(builder, execution.LaunchedGame!);
                break;
            case LauncherMode.EnableMod:
            case LauncherMode.DisableMod:
                AppendModStateChange(builder, execution.ModStateChange!);
                AppendModList(builder, execution.Catalog);
                break;
            case LauncherMode.JoinPreview:
                AppendJoinPreview(builder, execution.JoinPreview!);
                break;
            default:
                throw new InvalidOperationException($"Unsupported mode: {execution.Command.Mode}");
        }

        return builder.ToString().TrimEnd();
    }

    public static string FormatError(Exception exception)
    {
        return exception.Message;
    }

    private static void AppendConfiguration(StringBuilder builder, LauncherConfiguration configuration)
    {
        var runtimeFlags = RuntimeStageFlags.Create(configuration.Runtime);

        builder.AppendLine($"Workspace: {configuration.Workspace.RootPath}");
        builder.AppendLine($"Instance: {configuration.Workspace.InstanceName}");
        builder.AppendLine($"Game: {configuration.Game.InstallDirectory}");
        builder.AppendLine($"Config root: {configuration.Workspace.ConfigRootPath}");
        builder.AppendLine($"Mods root: {configuration.Workspace.ModsRootPath}");
        builder.AppendLine($"Downloaded mod cache: {configuration.Workspace.ModCacheRootPath}");
        builder.AppendLine($"Mod state: {configuration.Workspace.ModStatePath}");
        builder.AppendLine($"Stage root: {configuration.Workspace.StageRootPath}");
        builder.AppendLine($"Profile root: {configuration.Workspace.ProfileRootPath}");
        builder.AppendLine($"Isolated APPDATA: {configuration.Workspace.IsolatedGameAppDataPath}");
        builder.AppendLine($"Runtime profile: {RuntimeStageFlags.ToProfileName(configuration.Runtime.Profile)}");
        builder.AppendLine($"Runtime flag overrides: {configuration.Runtime.HasOverrides}");
        builder.AppendLine($"Loader debug UI: {runtimeFlags.LoaderDebugUi}");
        builder.AppendLine($"Steam AppID: {configuration.Steam.AppId}");
        builder.AppendLine($"Steam API override: {configuration.Steam.ApiDllOverridePath ?? "(auto)"}");
        builder.AppendLine();
    }

    private static void AppendModList(StringBuilder builder, ModCatalog catalog)
    {
        builder.AppendLine($"Discovered mods: {catalog.DiscoveredMods.Count}");
        builder.AppendLine($"Enabled mods: {catalog.EnabledMods.Count}");

        foreach (var mod in catalog.DiscoveredMods)
        {
            var state = catalog.IsEnabled(mod) ? "enabled" : "disabled";
            var requiredMods = mod.Manifest.RequiredMods.Count == 0
                ? "-"
                : string.Join(",", mod.Manifest.RequiredMods);
            var runtimeSummary = mod.RequiresRuntime
                ? $"runtime={mod.Manifest.RuntimeKind}:{mod.Manifest.Runtime.ApiVersion}"
                : "runtime=-";
            var providedContracts = mod.Manifest.Provides.Count == 0
                ? "-"
                : string.Join(",", mod.Manifest.Provides);
            var requiredContracts = mod.Manifest.Requires.Count == 0
                ? "-"
                : string.Join(",", mod.Manifest.Requires);
            builder.AppendLine(
                $"- {mod.Manifest.Id} [{state}] priority={mod.Manifest.Priority} overlays={mod.Manifest.Overlays.Count} {runtimeSummary} requiredMods={requiredMods} provides={providedContracts} requires={requiredContracts}");
        }

        builder.AppendLine();
    }

    private static void AppendModUpdates(
        StringBuilder builder,
        WebsiteModUpdateResult? result)
    {
        if (result is null)
        {
            return;
        }

        if (result.Error is not null)
        {
            builder.AppendLine($"Mod update check skipped: {result.Error}");
            builder.AppendLine();
            return;
        }

        if (result.UpdatedModCount == 0)
        {
            builder.AppendLine("Installed Website mods are current.");
            builder.AppendLine();
            return;
        }

        foreach (var update in result.Updates)
        {
            builder.AppendLine(
                $"Updated {update.Id}: v{update.PreviousVersion} -> v{update.Version}");
        }
        builder.AppendLine();
    }

    private static void AppendLobbyModSync(
        StringBuilder builder,
        LobbyModSyncResult? result)
    {
        if (result is null)
        {
            return;
        }

        if (!result.UsedWebsite)
        {
            builder.AppendLine(
                "Website lobby mod metadata was unavailable; using the locally enabled mod set. " +
                "Steam will still enforce the exact multiplayer fingerprint.");
            builder.AppendLine($"Website fallback reason: {result.FallbackReason}");
            builder.AppendLine();
            return;
        }

        builder.AppendLine(
            $"Website lobby mods: required={result.RequiredModCount} " +
            $"manual={result.ReusedManualModCount} cached={result.ReusedCachedModCount} " +
            $"downloaded={result.DownloadedModCount}");
        builder.AppendLine();
    }

    private static void AppendJoinPreview(StringBuilder builder, LobbyJoinPreview preview)
    {
        builder.AppendLine($"Join preview for lobby {preview.LobbyId}:");
        if (!preview.UsedWebsite)
        {
            builder.AppendLine($"Website mod list unavailable: {preview.Error}");
            builder.AppendLine();
            return;
        }

        builder.AppendLine(
            $"Host build: protocol={preview.HostBuild?.ProtocolVersion?.ToString() ?? "unknown"} " +
            $"launcher={preview.HostBuild?.LoaderVersion ?? "unknown"}");
        builder.AppendLine(
            $"Host mods: total={preview.Mods.Count} installed={preview.InstalledCount} " +
            $"cached={preview.CachedCount} needDownload={preview.DownloadCount} " +
            $"unavailable={preview.UnavailableCount}");
        foreach (var mod in preview.Mods)
        {
            var installedHint = mod.InstalledVersion is null
                ? string.Empty
                : $" (installed: {mod.InstalledVersion})";
            var sizeHint = mod.DownloadSizeBytes is { } size
                ? $" {size} bytes"
                : string.Empty;
            builder.AppendLine(
                $"- {mod.Id} {mod.Version} [{mod.State}]{installedHint}{sizeHint}");
        }

        builder.AppendLine();
    }

    private static void AppendStageResult(StringBuilder builder, StageBuildResult result)
    {
        builder.AppendLine($"Stage root ready: {result.StageRootPath}");
        builder.AppendLine($"Stage executable: {result.StageExecutablePath}");
        builder.AppendLine($"Stage report: {result.StageReportPath}");
        builder.AppendLine($"Stage config root: {result.StageConfigRootPath}");
        builder.AppendLine($"Stage binary layout: {result.StageBinaryLayoutPath}");
        builder.AppendLine($"Stage debug UI config: {result.StageDebugUiConfigPath}");
        builder.AppendLine($"Stage runtime root: {result.StageRuntimeRootPath}");
        builder.AppendLine($"Stage runtime bootstrap: {result.StageRuntimeBootstrapPath}");
        builder.AppendLine($"Stage runtime flags: {result.StageRuntimeFlagsPath}");
        builder.AppendLine(
            $"Stage mirror: copied={result.StageMirror.CopiedFileCount} skipped={result.StageMirror.SkippedFileCount} " +
            $"deletedFiles={result.StageMirror.DeletedFileCount} createdDirs={result.StageMirror.CreatedDirectoryCount} " +
            $"deletedDirs={result.StageMirror.DeletedDirectoryCount}");
        builder.AppendLine($"Enabled mods: {result.EnabledModCount}");
        builder.AppendLine($"Applied overlays: {result.AppliedOverlayCount}");
        builder.AppendLine(
            $"HUD labels: applied={result.HudLabels.Applied} label={result.HudLabels.Label} " +
            $"record={result.HudLabels.RecordIndex} rect={result.HudLabels.X},{result.HudLabels.Y}," +
            $"{result.HudLabels.Width}x{result.HudLabels.Height}");
        builder.AppendLine(
            $"Staged runtime mods: total={result.RuntimeMetadata.StagedRuntimeModCount} " +
            $"lua={result.RuntimeMetadata.StagedLuaModCount} " +
            $"profile={result.RuntimeMetadata.RuntimeProfileName}");
        builder.AppendLine($"Steam appid file: {result.SteamBootstrap.StageAppIdPath ?? "missing"}");
        builder.AppendLine($"Steam API dll: {result.SteamBootstrap.StageApiDllPath ?? "missing"}");
        builder.AppendLine();
    }

    private static void AppendModStateChange(StringBuilder builder, LauncherModStateChange change)
    {
        var verb = change.Enabled ? "Enabled" : "Disabled";
        builder.AppendLine($"{verb} mod: {change.ModId}");
        builder.AppendLine($"State file: {change.StatePath}");
        builder.AppendLine();
    }

    private static void AppendLaunchResult(StringBuilder builder, InjectedGame launchedGame)
    {
        builder.AppendLine("Launch request completed.");
        builder.AppendLine($"Process id: {launchedGame.ProcessId}");
        builder.AppendLine($"Injected loader: {launchedGame.LoaderPath}");
        builder.AppendLine($"Loader startup code: {launchedGame.StartupStatus.Code}");
        builder.AppendLine($"Loader startup message: {launchedGame.StartupStatus.Message}");
        builder.AppendLine($"Loader log: {launchedGame.StartupStatus.LogPath ?? "(unknown)"}");
        if (launchedGame.MultiplayerSessionStatus is { } session)
        {
            builder.AppendLine($"Steam session phase: {session.Phase}");
            builder.AppendLine($"Steam AppID: {session.AppId}");
            builder.AppendLine($"Steam lobby id: {session.LobbyId}");
            builder.AppendLine(
                $"Steam authenticated peers: {session.AuthenticatedPeerCount}; " +
                $"lobby capacity: {session.MaxParticipants}");
            builder.AppendLine(
                $"Steam overlay: {(session.OverlayEnabled ? "enabled" : "disabled")}; " +
                $"invite dialog: {(session.InviteDialogOpened ? "opened" : "not opened")}");
            builder.AppendLine(
                session.AuthenticatedPeerCount == 0
                    ? "Steam route: pending (no authenticated peer)"
                    : $"Steam route: {(session.RouteRelayed ? "SDR relay" : "direct-or-pending")}; " +
                      $"ping: {session.RoutePingMs} ms");
            builder.AppendLine($"Steam session status: {session.StatusText}");
            if (!string.IsNullOrWhiteSpace(session.ErrorText))
            {
                builder.AppendLine($"Steam session error: {session.ErrorText}");
            }
        }
        builder.AppendLine();
    }
}
