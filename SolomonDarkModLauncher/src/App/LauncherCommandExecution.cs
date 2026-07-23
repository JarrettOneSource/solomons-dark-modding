using SolomonDarkModLauncher.Commands;
using SolomonDarkModLauncher.Launch;
using SolomonDarkModLauncher.Mods;
using SolomonDarkModLauncher.Staging;
using SolomonDarkModLauncher.Target;

namespace SolomonDarkModLauncher.App;

internal sealed record LauncherCommandExecution(
    LauncherCommand Command,
    LauncherConfiguration Configuration,
    ModCatalog Catalog,
    WebsiteModUpdateResult? ModUpdate = null,
    LauncherModStateChange? ModStateChange = null,
    LobbyModSyncResult? LobbyModSync = null,
    StageBuildResult? StageResult = null,
    InjectedGame? LaunchedGame = null);
