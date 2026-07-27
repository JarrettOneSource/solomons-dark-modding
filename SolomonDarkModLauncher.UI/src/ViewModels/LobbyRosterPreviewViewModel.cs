using System.Collections.ObjectModel;
using SolomonDarkModLauncher.UI.Infrastructure;

namespace SolomonDarkModLauncher.UI.ViewModels;

internal sealed class LobbyRosterPreviewViewModel
{
    public LobbyRosterPreviewViewModel(
        LauncherCliMultiplayerSession status,
        string label)
    {
        var host = status.Members.FirstOrDefault(member => member.IsHost);
        var hostName = host is null || string.IsNullOrWhiteSpace(host.Name)
            ? "Remote Wizard"
            : host.Name;
        Title = status.IsHost ? "Your lobby" : $"{hostName}'s lobby";
        PreviewLabel = string.IsNullOrWhiteSpace(label)
            ? status.IsHost ? "Host roster" : "Client roster"
            : label;
        LobbyId = $"Lobby {status.LobbyId}";
        Players = status.MaxParticipants > 0
            ? $"Players: {status.Members.Count} of {status.MaxParticipants}"
            : "Players";
        Connection = status.Privacy switch
        {
            "public" => "Public · Connected",
            "friendsOnly" => "Friends Only · Connected",
            "local" => "Local proof · Connected",
            _ => "Connected"
        };
        foreach (var member in status.Members)
        {
            Members.Add(new LobbyMemberViewModel(member));
        }
    }

    public string Title { get; }
    public string PreviewLabel { get; }
    public string LobbyId { get; }
    public string Players { get; }
    public string Connection { get; }
    public ObservableCollection<LobbyMemberViewModel> Members { get; } = [];
}
