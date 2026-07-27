using SolomonDarkModding.Updates;
using SolomonDarkModLauncher.UI.Infrastructure;

namespace SolomonDarkModLauncher.UI.ViewModels;

internal enum MatchLoadingStage
{
    InspectingHostMods,
    AwaitingModConsent,
    SynchronizingHostMods,
    PreparingSession,
    JoiningSteamLobby,
    LobbyReady,
    LaunchingGame
}

internal sealed class MatchLoadingProgress
{
    private const double ModSyncCompletedProgress = 27;

    private sealed record StageDefinition(
        MatchLoadingStage Stage,
        double Progress,
        string Label);

    private static readonly StageDefinition[] Stages =
    [
        new(
            MatchLoadingStage.InspectingHostMods,
            5,
            "Reading the host's grimoire…"),
        new(
            MatchLoadingStage.AwaitingModConsent,
            10,
            "Waiting for your mod choice…"),
        new(
            MatchLoadingStage.SynchronizingHostMods,
            14,
            "Syncing the host's mods…"),
        new(
            MatchLoadingStage.PreparingSession,
            28,
            "Preparing this session…"),
        new(
            MatchLoadingStage.JoiningSteamLobby,
            34,
            "Entering the Steam lobby…"),
        new(
            MatchLoadingStage.LobbyReady,
            40,
            "Steam lobby joined."),
        new(
            MatchLoadingStage.LaunchingGame,
            44,
            "Opening Solomon Dark…")
    ];

    public bool Active { get; private set; }
    public long Sequence { get; private set; }
    public double Value { get; private set; }
    public string Label { get; private set; } = string.Empty;
    public string Detail { get; private set; } = string.Empty;

    public string PercentText => $"{Value:0}%";

    public void Begin(MatchLoadingStage stage)
    {
        Active = true;
        Sequence++;
        Value = 0;
        Label = string.Empty;
        Detail = string.Empty;
        Advance(stage);
    }

    public void Advance(MatchLoadingStage stage)
    {
        if (!Active)
        {
            return;
        }

        var definition = DefinitionFor(stage);
        if (definition.Progress <= Value)
        {
            return;
        }

        Value = definition.Progress;
        Label = definition.Label;
        Detail = string.Empty;
    }

    public void ObserveModSync(UpdateProgress progress)
    {
        if (!Active ||
            progress.Scope !=
                UpdateProgressScope.LobbyModSync ||
            Value > ModSyncCompletedProgress)
        {
            return;
        }

        Advance(MatchLoadingStage.SynchronizingHostMods);
        if (progress.Phase == UpdateProgressPhase.Failed)
        {
            return;
        }

        var nextValue = ModSyncProgressValue(progress);
        if (nextValue < Value)
        {
            return;
        }
        Value = Math.Max(Value, nextValue);
        Label = progress.StatusText;
        Detail = UpdateProgressPresentation.Create(progress).DetailText;
    }

    public void End()
    {
        Active = false;
        Label = string.Empty;
        Detail = string.Empty;
    }

    private static StageDefinition DefinitionFor(MatchLoadingStage stage) =>
        Stages.Single(definition => definition.Stage == stage);

    private static double ModSyncProgressValue(UpdateProgress progress)
    {
        var fraction =
            progress.Completed is { } completed &&
            progress.Total is > 0 and var total
                ? Math.Clamp(completed / (double)total, 0, 1)
                : 0;
        return progress.Phase switch
        {
            UpdateProgressPhase.Downloading => 15 + (fraction * 7),
            UpdateProgressPhase.Verifying => 23,
            UpdateProgressPhase.Installing => 24 + (fraction * 3),
            UpdateProgressPhase.Completed => 27,
            _ => 14
        };
    }
}
