namespace SolomonDarkModLauncher.Mods;

internal sealed record DiscoveredMod(
    string RootPath,
    string ManifestPath,
    ModManifest Manifest)
{
    public bool RequiresRuntime => Manifest.RequiresRuntime;
    public bool RequiresLuaRuntime => Manifest.RequiresLuaRuntime;
    public bool RequiresNativeRuntime => Manifest.RequiresNativeRuntime;
}
