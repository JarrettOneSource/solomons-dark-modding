namespace SolomonDarkModding.Updates;

internal enum UpdateProgressPhase
{
    Checking,
    Downloading,
    Verifying,
    Installing,
    Restarting,
    Completed,
    Failed
}

internal enum UpdateProgressUnit
{
    None,
    Bytes,
    Items
}

internal sealed record UpdateProgress(
    UpdateProgressPhase Phase,
    string StatusText,
    long? Completed = null,
    long? Total = null,
    UpdateProgressUnit Unit = UpdateProgressUnit.None);
