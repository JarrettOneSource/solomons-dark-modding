using SolomonDarkModLauncher.Mods;
using SolomonDarkModLauncher.Target;

namespace SolomonDarkModLauncher.Manager;

internal sealed class ModManagerService
{
    private readonly LauncherConfiguration configuration_;

    public ModManagerService(LauncherConfiguration configuration)
    {
        configuration_ = configuration;
    }

    public string StatePath => configuration_.Workspace.ModStatePath;

    public ModCatalog LoadCatalog()
    {
        return ModCatalog.Load(
            configuration_.Workspace.ModsRootPath,
            ModStateStore.Load(configuration_.Workspace.ModStatePath));
    }

    public void SetEnabled(string modId, bool enabled)
    {
        var catalog = LoadCatalog();
        var mod = catalog.FindById(modId)
            ?? throw new InvalidOperationException($"Mod not found: {modId}");

        ModStateStore.SetEnabledAtomic(configuration_.Workspace.ModStatePath, mod.Manifest.Id, enabled);
    }
}
