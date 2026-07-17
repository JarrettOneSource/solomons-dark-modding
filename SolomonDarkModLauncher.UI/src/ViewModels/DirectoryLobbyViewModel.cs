using SolomonDarkModLauncher.UI.Infrastructure;

namespace SolomonDarkModLauncher.UI.ViewModels;

internal sealed class DirectoryLobbyViewModel
{
    public DirectoryLobbyViewModel(
        DirectoryLobby lobby,
        Action<DirectoryLobbyViewModel> join,
        Action<DirectoryLobbyViewModel> openWebsite)
    {
        DirectoryId = lobby.Id;
        HostName = lobby.HostPlayer;
        LobbyId = lobby.Join?.LobbyId;
        BoneyardText = string.IsNullOrWhiteSpace(lobby.Game.BoneyardName)
            ? "Boneyard undecided"
            : lobby.Game.BoneyardName;
        DetailText = DescribeGame(lobby.Game);
        PlayersText = $"{lobby.Players} of {lobby.MaxPlayers}";
        IsPasswordProtected = lobby.Access == "password";
        IsFriendAccess = lobby.Access == "friend";
        AccessText = IsPasswordProtected ? "Password" : IsFriendAccess ? "Friends" : "Open";
        CanJoin = lobby.Join is not null;
        JoinCommand = new RelayCommand(_ => join(this), _ => CanJoin);
        OpenWebsiteCommand = new RelayCommand(_ => openWebsite(this));
    }

    public int DirectoryId { get; }
    public string HostName { get; }
    public string? LobbyId { get; }
    public string BoneyardText { get; }
    public string DetailText { get; }
    public string PlayersText { get; }
    public string AccessText { get; }
    public bool IsPasswordProtected { get; }
    public bool IsFriendAccess { get; }
    public bool CanJoin { get; }
    public RelayCommand JoinCommand { get; }
    public RelayCommand OpenWebsiteCommand { get; }

    private static string DescribeGame(DirectoryLobbyGame game)
    {
        var phase = game.Phase switch
        {
            "session" => "In session",
            "loading" => "Loading in",
            "results" => "Wrapping up",
            _ => "In hub"
        };

        var bits = new List<string> { phase };
        if (game.Wave is not null)
        {
            bits.Add($"Wave {game.Wave}");
        }
        if (!string.IsNullOrWhiteSpace(game.Difficulty))
        {
            bits.Add(game.Difficulty);
        }
        if (game.ElapsedSeconds is not null)
        {
            bits.Add(DescribeElapsed(game.ElapsedSeconds.Value));
        }
        if (bits.Count == 1 && !string.IsNullOrWhiteSpace(game.StatusText))
        {
            bits.Add(game.StatusText);
        }
        return string.Join(" · ", bits);
    }

    private static string DescribeElapsed(int seconds)
    {
        if (seconds < 60)
        {
            return $"{seconds}s in";
        }
        var minutes = seconds / 60;
        return minutes < 60 ? $"{minutes}m in" : $"{minutes / 60}h {minutes % 60}m in";
    }
}
