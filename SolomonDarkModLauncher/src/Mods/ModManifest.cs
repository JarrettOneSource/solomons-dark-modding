namespace SolomonDarkModLauncher.Mods;

internal sealed class ModManifest
{
    public string Id { get; init; } = string.Empty;
    public string Name { get; init; } = string.Empty;
    public string Version { get; init; } = string.Empty;
    public int Priority { get; init; }
    public List<OverlayDefinition> Overlays { get; init; } = [];
    public RuntimeModDefinition Runtime { get; init; } = new();
    public List<string> RequiredMods { get; init; } = [];

    public bool RequiresRuntime => Runtime.RequiresRuntime;
    public bool RequiresLuaRuntime => Runtime.RequiresLuaRuntime;
    public bool RequiresNativeRuntime => Runtime.RequiresNativeRuntime;
    public string RuntimeKind => Runtime.RuntimeKind;
}
