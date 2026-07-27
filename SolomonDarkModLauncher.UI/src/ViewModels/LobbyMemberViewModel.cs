using SolomonDarkModLauncher.UI.Infrastructure;

namespace SolomonDarkModLauncher.UI.ViewModels;

internal sealed class LobbyMemberViewModel
{
    public LobbyMemberViewModel(LauncherCliLobbyMember member)
    {
        Name = string.IsNullOrWhiteSpace(member.Name) ? "Remote Wizard" : member.Name;
        ParticipantId = member.ParticipantId;
        IsHost = member.IsHost;
        IsLocal = member.IsLocal;
        IsBot = member.IsBot;
        TagText = member.IsBot
            ? "BOT"
            : member.IsHost
                ? "HOST"
                : member.IsLocal
                    ? "YOU"
                    : string.Empty;
        TagUsesGold = member.IsBot || member.IsHost;
    }

    public string Name { get; }
    public ulong ParticipantId { get; }
    public bool IsHost { get; }
    public bool IsLocal { get; }
    public bool IsBot { get; }
    public string TagText { get; }
    public bool TagUsesGold { get; }
}
