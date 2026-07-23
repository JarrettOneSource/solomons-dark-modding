using System.Text.Json.Serialization;

namespace SolomonDarkModLauncher.Mods;

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
internal sealed class RuntimeModDefinition
{
    public string ApiVersion { get; init; } = string.Empty;
    public string EntryScript { get; init; } = string.Empty;
    public bool HotReload { get; init; }
    public List<string> RequiredCapabilities { get; init; } = [];
    public List<string> OptionalCapabilities { get; init; } = [];

    public bool RequiresLuaRuntime => !string.IsNullOrWhiteSpace(EntryScript);
    public bool RequiresRuntime => RequiresLuaRuntime;
    public string RuntimeKind => RequiresLuaRuntime ? "lua" : "none";
}
