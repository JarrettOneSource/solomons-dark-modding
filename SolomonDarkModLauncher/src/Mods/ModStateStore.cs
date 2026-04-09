using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace SolomonDarkModLauncher.Mods;

internal sealed class ModStateStore
{
    private readonly string path_;
    private readonly Dictionary<string, PersistedModState> states_;

    private ModStateStore(string path, Dictionary<string, PersistedModState> states)
    {
        path_ = path;
        states_ = states;
    }

    public string Path => path_;

    public static ModStateStore Load(string path)
    {
        if (!File.Exists(path))
        {
            return new ModStateStore(path, new Dictionary<string, PersistedModState>(StringComparer.OrdinalIgnoreCase));
        }

        var json = File.ReadAllText(path);
        if (string.IsNullOrWhiteSpace(json))
        {
            return new ModStateStore(path, new Dictionary<string, PersistedModState>(StringComparer.OrdinalIgnoreCase));
        }

        var document = JsonSerializer.Deserialize<ModStateDocument>(
            json,
            new JsonSerializerOptions
            {
                PropertyNameCaseInsensitive = true
            }) ?? new ModStateDocument();

        var states = new Dictionary<string, PersistedModState>(StringComparer.OrdinalIgnoreCase);
        foreach (var pair in document.Mods)
        {
            if (string.IsNullOrWhiteSpace(pair.Key) || pair.Value is null)
            {
                continue;
            }

            states[pair.Key] = pair.Value;
        }

        return new ModStateStore(path, states);
    }

    public static void SetEnabledAtomic(string path, string modId, bool enabled)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        ArgumentException.ThrowIfNullOrWhiteSpace(modId);

        WithStateLock(path, () =>
        {
            var store = Load(path);
            store.SetEnabled(modId, enabled);
            store.Save();
        });
    }

    public bool IsEnabled(string modId)
    {
        return states_.TryGetValue(modId, out var state) && state.Enabled;
    }

    public void SetEnabled(string modId, bool enabled)
    {
        states_[modId] = new PersistedModState
        {
            Enabled = enabled
        };
    }

    public void Save()
    {
        var directoryPath = System.IO.Path.GetDirectoryName(path_);
        if (!string.IsNullOrWhiteSpace(directoryPath))
        {
            Directory.CreateDirectory(directoryPath);
        }

        var ordered = new Dictionary<string, PersistedModState>(StringComparer.OrdinalIgnoreCase);
        foreach (var pair in states_.OrderBy(pair => pair.Key, StringComparer.OrdinalIgnoreCase))
        {
            ordered[pair.Key] = pair.Value;
        }

        var json = JsonSerializer.Serialize(
            new ModStateDocument
            {
                Mods = ordered
            },
            new JsonSerializerOptions
            {
                WriteIndented = true
            });
        File.WriteAllText(path_, json);
    }

    private static void WithStateLock(string path, Action action)
    {
        var fullPath = System.IO.Path.GetFullPath(path);
        using var mutex = new Mutex(
            initiallyOwned: false,
            BuildMutexName(fullPath));
        if (!mutex.WaitOne(TimeSpan.FromSeconds(10)))
        {
            throw new IOException($"Timed out waiting for mod state lock: {fullPath}");
        }

        try
        {
            action();
        }
        finally
        {
            mutex.ReleaseMutex();
        }
    }

    private static string BuildMutexName(string fullPath)
    {
        var bytes = SHA256.HashData(Encoding.UTF8.GetBytes(fullPath.ToUpperInvariant()));
        return $"SolomonDarkModLauncher.ModState.{Convert.ToHexString(bytes)}";
    }

    private sealed class ModStateDocument
    {
        public Dictionary<string, PersistedModState> Mods { get; init; } = [];
    }

    private sealed class PersistedModState
    {
        public bool Enabled { get; init; } = true;
    }
}
