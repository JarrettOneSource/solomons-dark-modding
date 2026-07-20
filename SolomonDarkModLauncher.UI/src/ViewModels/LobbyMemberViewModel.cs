using SolomonDarkModLauncher.UI.Infrastructure;

namespace SolomonDarkModLauncher.UI.ViewModels;

internal sealed class LobbyMemberViewModel
{
    public LobbyMemberViewModel(LauncherCliLobbyMember member)
    {
        Name = string.IsNullOrWhiteSpace(member.Name) ? "Remote Wizard" : member.Name;
        IsHost = member.IsHost;
        TagText = member.IsHost ? "Host" : member.IsLocal ? "You" : string.Empty;
    }

    public string Name { get; }
    public bool IsHost { get; }
    public string TagText { get; }
}
