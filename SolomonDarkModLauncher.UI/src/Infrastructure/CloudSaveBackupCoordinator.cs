using System.Net.Http;
using System.Text.Json;

namespace SolomonDarkModLauncher.UI.Infrastructure;

internal sealed record CloudSaveBackupStatus(
    string Message,
    bool IsError);

internal sealed class CloudSaveBackupCoordinator
{
    private readonly LocalSaveCatalog catalog_;
    private readonly CloudSaveClient cloud_;

    public CloudSaveBackupCoordinator(
        LocalSaveCatalog catalog,
        CloudSaveClient cloud)
    {
        catalog_ = catalog;
        cloud_ = cloud;
    }

    public CloudSaveGameSession Start(
        LauncherCliResponse response,
        string directoryUrl,
        Action<CloudSaveBackupStatus> statusChanged)
    {
        var launch = response.Launch ??
            throw new InvalidOperationException("The game launch response is incomplete.");
        var stage = response.Stage ??
            throw new InvalidOperationException("The staged game response is incomplete.");
        var save = catalog_.Active;
        if (string.IsNullOrWhiteSpace(launch.SavegamesRootPath) ||
            !PathsEqual(launch.SavegamesRootPath, save.SavegamesRootPath))
        {
            throw new InvalidOperationException(
                "The game did not launch with the selected local save.");
        }

        var effectiveSavegamesRootPath = launch.SavegamesUsesDirectoryMirror
            ? Path.Combine(stage.StageRoot, "savegames")
            : save.SavegamesRootPath;
        return new CloudSaveGameSession(
            catalog_,
            cloud_,
            save.Slot,
            save.SavegamesRootPath,
            effectiveSavegamesRootPath,
            launch.SavegamesUsesDirectoryMirror,
            directoryUrl,
            statusChanged);
    }

    private static bool PathsEqual(string first, string second) =>
        string.Equals(
            Path.GetFullPath(first).TrimEnd(Path.DirectorySeparatorChar),
            Path.GetFullPath(second).TrimEnd(Path.DirectorySeparatorChar),
            OperatingSystem.IsWindows()
                ? StringComparison.OrdinalIgnoreCase
                : StringComparison.Ordinal);
}

internal sealed class CloudSaveGameSession : IAsyncDisposable
{
    private static readonly TimeSpan BackupDebounce = TimeSpan.FromSeconds(3);

    private readonly LocalSaveCatalog catalog_;
    private readonly CloudSaveClient cloud_;
    private readonly int slot_;
    private readonly string localSavegamesRootPath_;
    private readonly string effectiveSavegamesRootPath_;
    private readonly bool usesDirectoryMirror_;
    private readonly string directoryUrl_;
    private readonly Action<CloudSaveBackupStatus> statusChanged_;
    private readonly SemaphoreSlim backupLock_ = new(1, 1);
    private readonly object debounceLock_ = new();
    private readonly FileSystemWatcher watcher_;
    private CancellationTokenSource? debounceCancellation_;
    private bool completed_;

    public CloudSaveGameSession(
        LocalSaveCatalog catalog,
        CloudSaveClient cloud,
        int slot,
        string localSavegamesRootPath,
        string effectiveSavegamesRootPath,
        bool usesDirectoryMirror,
        string directoryUrl,
        Action<CloudSaveBackupStatus> statusChanged)
    {
        catalog_ = catalog;
        cloud_ = cloud;
        slot_ = slot;
        localSavegamesRootPath_ = localSavegamesRootPath;
        effectiveSavegamesRootPath_ = effectiveSavegamesRootPath;
        usesDirectoryMirror_ = usesDirectoryMirror;
        directoryUrl_ = directoryUrl;
        statusChanged_ = statusChanged;

        Directory.CreateDirectory(effectiveSavegamesRootPath_);
        watcher_ = new FileSystemWatcher(effectiveSavegamesRootPath_)
        {
            IncludeSubdirectories = true,
            NotifyFilter =
                NotifyFilters.FileName |
                NotifyFilters.DirectoryName |
                NotifyFilters.LastWrite |
                NotifyFilters.Size
        };
        watcher_.Changed += OnSaveChanged;
        watcher_.Created += OnSaveChanged;
        watcher_.Deleted += OnSaveChanged;
        watcher_.Renamed += OnSaveChanged;
        watcher_.EnableRaisingEvents = true;
    }

    public async Task CompleteAsync(CancellationToken cancellationToken)
    {
        if (completed_)
        {
            return;
        }
        completed_ = true;
        watcher_.EnableRaisingEvents = false;
        CancelDebounce();

        await backupLock_.WaitAsync(cancellationToken);
        try
        {
            if (usesDirectoryMirror_)
            {
                SaveDirectoryMirror.Replace(
                    effectiveSavegamesRootPath_,
                    localSavegamesRootPath_);
            }
            await BackupCoreAsync(cancellationToken);
        }
        finally
        {
            backupLock_.Release();
        }
    }

    public async ValueTask DisposeAsync()
    {
        watcher_.Dispose();
        CancelDebounce();
        await Task.CompletedTask;
    }

    private void OnSaveChanged(object sender, FileSystemEventArgs args)
    {
        if (completed_ || usesDirectoryMirror_)
        {
            return;
        }

        CancellationToken cancellationToken;
        lock (debounceLock_)
        {
            debounceCancellation_?.Cancel();
            debounceCancellation_?.Dispose();
            debounceCancellation_ = new CancellationTokenSource();
            cancellationToken = debounceCancellation_.Token;
        }
        _ = BackupAfterQuietPeriodAsync(cancellationToken);
    }

    private async Task BackupAfterQuietPeriodAsync(CancellationToken cancellationToken)
    {
        try
        {
            await Task.Delay(BackupDebounce, cancellationToken);
            await backupLock_.WaitAsync(cancellationToken);
            try
            {
                await BackupCoreAsync(cancellationToken);
            }
            finally
            {
                backupLock_.Release();
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
        }
        catch (Exception exception) when (
            exception is IOException or
            UnauthorizedAccessException or
            InvalidDataException or
            InvalidOperationException or
            HttpRequestException or
            JsonException or
            TaskCanceledException)
        {
            statusChanged_(new CloudSaveBackupStatus(
                $"Cloud backup will retry after the game closes: {exception.Message}",
                IsError: true));
        }
    }

    private async Task BackupCoreAsync(CancellationToken cancellationToken)
    {
        var result = await cloud_.BackupAsync(directoryUrl_, slot_, cancellationToken);
        var message = result.Disposition switch
        {
            CloudBackupDisposition.Uploaded =>
                $"Save {slot_ + 1} backed up to the linked SDR account.",
            CloudBackupDisposition.Unchanged =>
                $"Save {slot_ + 1} is already backed up.",
            CloudBackupDisposition.NotLinked =>
                "Cloud backup is off until this Steam account is linked on the website.",
            CloudBackupDisposition.Empty =>
                $"Save {slot_ + 1} has no files to back up.",
            _ => "Cloud backup status is unavailable."
        };
        statusChanged_(new CloudSaveBackupStatus(message, IsError: false));
    }

    private void CancelDebounce()
    {
        lock (debounceLock_)
        {
            debounceCancellation_?.Cancel();
            debounceCancellation_?.Dispose();
            debounceCancellation_ = null;
        }
    }
}
