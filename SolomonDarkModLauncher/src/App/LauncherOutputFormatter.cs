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
            "  stage                Mirror Solomon Dark into the stage root and stage enabled overlay or runtime mods without launching.",
            "  list-mods            Discover overlay or runtime manifests and print enabled or disabled mods.",
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
            "  --steam-appid <id>      Override the Steam AppID staged into steam_appid.txt. Default: 3362180.",
            "  --steam-api-dll <path>  Override the x86 steam_api.dll used when the mirrored game does not already ship one.",
            "  --help                  Show this help text.",
            string.Empty,
            "Current scope:",
            "  overlay mods plus staged runtime-mod metadata",
            "  staged file mirroring",
            "  isolated profile roots under runtime/",
            "  x86 native loader injection on launch",
            "  staged Steam bootstrap for SteamAPI initialization and future P2P transport work",
            "  staged runtime flags, runtime bootstrap manifests, and native-mod host plumbing",
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
                AppendModList(builder, execution.Catalog);
                break;
            case LauncherMode.Stage:
                AppendConfiguration(builder, execution.Configuration);
                AppendModList(builder, execution.Catalog);
                AppendStageResult(builder, execution.StageResult!);
                break;
            case LauncherMode.Launch:
                AppendConfiguration(builder, execution.Configuration);
                AppendModList(builder, execution.Catalog);
                AppendStageResult(builder, execution.StageResult!);
                AppendLaunchResult(builder, execution.LaunchedGame!);
                break;
            case LauncherMode.EnableMod:
            case LauncherMode.DisableMod:
                AppendModStateChange(builder, execution.ModStateChange!);
                AppendModList(builder, execution.Catalog);
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
            builder.AppendLine(
                $"- {mod.Manifest.Id} [{state}] priority={mod.Manifest.Priority} overlays={mod.Manifest.Overlays.Count} {runtimeSummary} requires={requiredMods}");
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
            $"Staged runtime mods: total={result.RuntimeMetadata.StagedRuntimeModCount} " +
            $"lua={result.RuntimeMetadata.StagedLuaModCount} native={result.RuntimeMetadata.StagedNativeModCount} " +
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
        builder.AppendLine();
    }
}
