namespace SolomonDarkModLauncher.UI.Infrastructure;

internal sealed record LauncherUiInvocationResult(
    IReadOnlyList<string> Arguments,
    LauncherCliResponse? Response,
    string Transcript,
    string? ErrorMessage)
{
    public bool Succeeded => Response?.Success == true && string.IsNullOrWhiteSpace(ErrorMessage);
}
