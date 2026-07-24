using SolomonDarkModding.Updates;

namespace SolomonDarkModLauncher.UI.Infrastructure;

internal sealed record UpdateProgressPresentation(
    double Value,
    string DetailText,
    bool IsError,
    bool IsComplete)
{
    public static UpdateProgressPresentation Create(UpdateProgress progress)
    {
        var value = 0.0;
        var detail = string.Empty;
        if (progress.Completed is { } completed)
        {
            if (progress.Total is > 0 and var total)
            {
                value = Math.Clamp(completed * 100.0 / total, 0.0, 100.0);
                detail = progress.Unit switch
                {
                    UpdateProgressUnit.Bytes =>
                        $"{value:0}% · {FormatSize(completed)} of {FormatSize(total)}",
                    UpdateProgressUnit.Items =>
                        $"{value:0}% · {completed} of {total}",
                    _ => $"{value:0}%"
                };
            }
            else if (progress.Unit == UpdateProgressUnit.Bytes)
            {
                detail = FormatSize(completed);
            }
            else if (progress.Unit == UpdateProgressUnit.Items)
            {
                detail = completed.ToString();
            }
        }

        return new UpdateProgressPresentation(
            value,
            detail,
            progress.Phase == UpdateProgressPhase.Failed,
            progress.Phase == UpdateProgressPhase.Completed);
    }

    private static string FormatSize(long bytes) => bytes switch
    {
        >= 1024L * 1024L * 1024L => $"{bytes / (1024.0 * 1024.0 * 1024.0):0.##} GB",
        >= 1024L * 1024L => $"{bytes / (1024.0 * 1024.0):0.##} MB",
        >= 1024L => $"{bytes / 1024.0:0.##} KB",
        _ => $"{bytes} bytes"
    };
}
