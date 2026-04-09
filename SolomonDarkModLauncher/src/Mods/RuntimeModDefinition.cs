namespace SolomonDarkModLauncher.Mods;

internal sealed class RuntimeModDefinition
{
    public string ApiVersion { get; init; } = string.Empty;
    public string EntryScript { get; init; } = string.Empty;
    public string EntryDll { get; init; } = string.Empty;
    public List<string> RequiredCapabilities { get; init; } = [];
    public List<string> OptionalCapabilities { get; init; } = [];

    public bool RequiresLuaRuntime => !string.IsNullOrWhiteSpace(EntryScript);
    public bool RequiresNativeRuntime => !string.IsNullOrWhiteSpace(EntryDll);
    public bool RequiresRuntime => RequiresLuaRuntime || RequiresNativeRuntime;

    public string RuntimeKind =>
        RequiresLuaRuntime && RequiresNativeRuntime ? "hybrid" :
        RequiresNativeRuntime ? "native" :
        RequiresLuaRuntime ? "lua" :
        "none";
}
