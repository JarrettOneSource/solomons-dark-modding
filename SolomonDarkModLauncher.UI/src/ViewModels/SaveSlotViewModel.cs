using SolomonDarkModLauncher.UI.Infrastructure;

namespace SolomonDarkModLauncher.UI.ViewModels;

internal sealed class SaveSlotViewModel
{
    public SaveSlotViewModel(
        LocalSaveSlot local,
        CloudSaveRemoteSlot? cloud,
        bool isActive)
    {
        Local = local;
        Cloud = cloud;
        IsActive = isActive;
    }

    public LocalSaveSlot Local { get; }
    public CloudSaveRemoteSlot? Cloud { get; }
    public int Slot => Local.Slot;
    public string Number => (Slot + 1).ToString();
    public string Name => Local.Name;
    public bool IsActive { get; }
    public bool HasLocalData => Local.HasLocalData;
    public bool HasCloudBackup => Cloud is not null;

    public string LocalStatus => Local.HasLocalData
        ? Local.LastLocalWriteUtc is { } updated
            ? $"Local · updated {updated.LocalDateTime:g}"
            : "Local save"
        : "Empty local slot";

    public string CloudStatus => Cloud is { } cloud
        ? $"Cloud · {cloud.FileCount} files · {cloud.UpdatedAtUtc.LocalDateTime:g}"
        : "No cloud backup";
}
