using System.Text.Json;

namespace SolomonDarkModLauncher.UI.Infrastructure;

internal sealed record LocalSaveSlot(
    int Slot,
    string Name,
    string RootPath,
    string SavegamesRootPath,
    bool HasLocalData,
    DateTimeOffset? LastLocalWriteUtc,
    string? LastBackupFingerprint,
    DateTimeOffset? LastBackupAtUtc);

internal sealed class LocalSaveCatalog
{
    public const int SlotCount = 8;

    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        WriteIndented = true
    };

    private readonly LauncherUiSettingsStore settings_;

    public LocalSaveCatalog(LauncherUiSettingsStore settings)
    {
        settings_ = settings;
        Directory.CreateDirectory(settings_.SavesRoot);
        for (var slot = 0; slot < SlotCount; slot++)
        {
            EnsureSlot(slot);
        }
    }

    public string SavesRoot => settings_.SavesRoot;

    public int ActiveSlot => settings_.LoadActiveSaveSlot();

    public LocalSaveSlot Active => Get(ActiveSlot);

    public IReadOnlyList<LocalSaveSlot> List() =>
        Enumerable.Range(0, SlotCount).Select(Get).ToArray();

    public LocalSaveSlot Get(int slot)
    {
        ValidateSlot(slot);
        var rootPath = GetSlotRoot(slot);
        var savegamesRootPath = Path.Combine(rootPath, "savegames");
        var metadata = LoadMetadata(slot);
        var files = Directory.EnumerateFiles(
                savegamesRootPath,
                "*",
                SearchOption.AllDirectories)
            .ToArray();
        DateTimeOffset? lastWrite = files.Length == 0
            ? null
            : new DateTimeOffset(
                files.Max(File.GetLastWriteTimeUtc),
                TimeSpan.Zero);
        return new LocalSaveSlot(
            slot,
            metadata.Name,
            rootPath,
            savegamesRootPath,
            files.Length > 0,
            lastWrite,
            metadata.LastBackupFingerprint,
            metadata.LastBackupAtUtc);
    }

    public LocalSaveSlot Select(int slot)
    {
        ValidateSlot(slot);
        settings_.SaveActiveSaveSlot(slot);
        return Get(slot);
    }

    public LocalSaveSlot Rename(int slot, string name)
    {
        ValidateSlot(slot);
        name = name.Trim();
        if (name.Length is < 1 or > 40 || name.Any(char.IsControl))
        {
            throw new InvalidOperationException(
                "Save names must be 1–40 printable characters.");
        }

        var metadata = LoadMetadata(slot) with { Name = name };
        WriteMetadata(slot, metadata);
        return Get(slot);
    }

    public LocalSaveSlot Import(int slot, string sourceSavegamesRootPath)
    {
        ValidateSlot(slot);
        sourceSavegamesRootPath = Path.GetFullPath(sourceSavegamesRootPath);
        if (!Directory.Exists(Path.Combine(sourceSavegamesRootPath, "solomondark")))
        {
            throw new InvalidOperationException(
                "Select the savegames folder that contains the solomondark directory.");
        }

        SaveDirectoryMirror.Replace(
            sourceSavegamesRootPath,
            Path.Combine(GetSlotRoot(slot), "savegames"));
        ClearBackupReceipt(slot);
        return Get(slot);
    }

    public LocalSaveSlot ReplaceFromRestore(int slot, string sourceSavegamesRootPath)
    {
        ValidateSlot(slot);
        SaveDirectoryMirror.Replace(
            sourceSavegamesRootPath,
            Path.Combine(GetSlotRoot(slot), "savegames"));
        ClearBackupReceipt(slot);
        return Get(slot);
    }

    public LocalSaveSlot MarkBackedUp(
        int slot,
        string fingerprint,
        DateTimeOffset backedUpAtUtc)
    {
        ValidateSlot(slot);
        var metadata = LoadMetadata(slot) with
        {
            LastBackupFingerprint = fingerprint,
            LastBackupAtUtc = backedUpAtUtc
        };
        WriteMetadata(slot, metadata);
        return Get(slot);
    }

    private void ClearBackupReceipt(int slot)
    {
        var metadata = LoadMetadata(slot) with
        {
            LastBackupFingerprint = null,
            LastBackupAtUtc = null
        };
        WriteMetadata(slot, metadata);
    }

    private void EnsureSlot(int slot)
    {
        var rootPath = GetSlotRoot(slot);
        Directory.CreateDirectory(Path.Combine(rootPath, "savegames"));
        var metadataPath = GetMetadataPath(slot);
        if (!File.Exists(metadataPath))
        {
            WriteMetadata(slot, new SaveMetadata($"Save {slot + 1}", null, null));
        }
    }

    private SaveMetadata LoadMetadata(int slot)
    {
        EnsureSlot(slot);
        try
        {
            return JsonSerializer.Deserialize<SaveMetadata>(
                       File.ReadAllText(GetMetadataPath(slot)),
                       JsonOptions) ??
                   new SaveMetadata($"Save {slot + 1}", null, null);
        }
        catch (JsonException)
        {
            throw new InvalidDataException(
                $"The metadata for save {slot + 1} is not valid JSON.");
        }
    }

    private void WriteMetadata(int slot, SaveMetadata metadata)
    {
        var path = GetMetadataPath(slot);
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        var temporaryPath = path + ".tmp";
        File.WriteAllText(temporaryPath, JsonSerializer.Serialize(metadata, JsonOptions));
        File.Move(temporaryPath, path, overwrite: true);
    }

    private string GetSlotRoot(int slot) =>
        Path.Combine(settings_.SavesRoot, $"slot-{slot + 1}");

    private string GetMetadataPath(int slot) =>
        Path.Combine(GetSlotRoot(slot), "slot.json");

    private static void ValidateSlot(int slot)
    {
        if (slot is < 0 or >= SlotCount)
        {
            throw new ArgumentOutOfRangeException(nameof(slot));
        }
    }

    private sealed record SaveMetadata(
        string Name,
        string? LastBackupFingerprint,
        DateTimeOffset? LastBackupAtUtc);
}
