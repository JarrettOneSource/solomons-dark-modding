namespace SolomonDarkModLauncher.ModSettings;

public enum ModSettingsGameInstanceState
{
    NotRunning,
    RunningSolo,
    RunningHost,
    RunningClientInSession
}

public sealed record OwnedModSettingsInstance
{
    public ModSettingsGameInstanceState State { get; init; }
    public string PipeName { get; init; } = string.Empty;
}

public interface IModSettingsInstanceContext
{
    OwnedModSettingsInstance Current { get; }
    event EventHandler? Changed;
}

public sealed class ModSettingsInstanceContext : IModSettingsInstanceContext
{
    private OwnedModSettingsInstance _current = new();

    public OwnedModSettingsInstance Current => _current;

    public event EventHandler? Changed;

    public void Update(OwnedModSettingsInstance instance)
    {
        ArgumentNullException.ThrowIfNull(instance);
        if (instance.State != ModSettingsGameInstanceState.NotRunning)
        {
            ArgumentException.ThrowIfNullOrWhiteSpace(instance.PipeName);
        }
        if (_current == instance)
        {
            return;
        }
        _current = instance;
        Changed?.Invoke(this, EventArgs.Empty);
    }
}

public interface IModSettingsService
{
    IReadOnlyList<DiscoveredModSettings> Discover();
    DiscoveredModSettings GetSchema(string modId);
    ModSettingsSnapshot GetPersistedValues(string modId);
    Task<ModSettingsRuntimeResult> SaveAsync(
        string modId,
        IReadOnlyDictionary<string, ModSettingValue> values,
        CancellationToken cancellationToken = default);
    Task<ModSettingsRuntimeResult> InvokeActionAsync(
        string modId,
        string entryKey,
        CancellationToken cancellationToken = default);
    ModSettingsGameInstanceState InstanceState { get; }
    event EventHandler? InstanceStateChanged;
}

public sealed class ModSettingsService : IModSettingsService
{
    private readonly string _stageRootPath;
    private readonly string _modsRootPath;
    private readonly IModSettingsDiscoveryService _discovery;
    private readonly IModSettingsStore _store;
    private readonly IModSettingsRuntimeClient _runtime;
    private readonly IModSettingsInstanceContext _instanceContext;

    public ModSettingsService(
        string modsRootPath,
        string stageRootPath,
        IModSettingsDiscoveryService discovery,
        IModSettingsStore store,
        IModSettingsRuntimeClient runtime,
        IModSettingsInstanceContext instanceContext)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(modsRootPath);
        ArgumentException.ThrowIfNullOrWhiteSpace(stageRootPath);
        _modsRootPath = Path.GetFullPath(modsRootPath);
        _stageRootPath = Path.GetFullPath(stageRootPath);
        _discovery =
            discovery ?? throw new ArgumentNullException(nameof(discovery));
        _store = store ?? throw new ArgumentNullException(nameof(store));
        _runtime = runtime ?? throw new ArgumentNullException(nameof(runtime));
        _instanceContext = instanceContext ??
            throw new ArgumentNullException(nameof(instanceContext));
        _instanceContext.Changed += OnInstanceContextChanged;
    }

    public ModSettingsGameInstanceState InstanceState =>
        _instanceContext.Current.State;

    public event EventHandler? InstanceStateChanged;

    public IReadOnlyList<DiscoveredModSettings> Discover() =>
        _discovery.Discover(_modsRootPath);

    public DiscoveredModSettings GetSchema(string modId) =>
        FindMod(modId);

    public ModSettingsSnapshot GetPersistedValues(string modId)
    {
        var mod = FindMod(modId);
        return _store.Load(
            _stageRootPath,
            mod.ModId,
            RequireDefinition(mod));
    }

    public async Task<ModSettingsRuntimeResult> SaveAsync(
        string modId,
        IReadOnlyDictionary<string, ModSettingValue> values,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(values);
        var mod = FindMod(modId);
        var definition = RequireDefinition(mod);
        try
        {
            _store.Save(_stageRootPath, mod.ModId, definition, values);
        }
        catch (ModSettingsEntryValidationException exception)
        {
            return new ModSettingsRuntimeResult
            {
                EntryErrors =
                    new Dictionary<string, string>(StringComparer.Ordinal)
                    {
                        [exception.EntryKey] = exception.Message
                    },
                Error = "One or more settings are invalid."
            };
        }

        var instance = _instanceContext.Current;
        if (instance.State == ModSettingsGameInstanceState.NotRunning)
        {
            return new ModSettingsRuntimeResult { Ok = true };
        }
        return await _runtime.ReloadAsync(
            instance.PipeName,
            mod.ModId,
            cancellationToken);
    }

    public async Task<ModSettingsRuntimeResult> InvokeActionAsync(
        string modId,
        string entryKey,
        CancellationToken cancellationToken = default)
    {
        var mod = FindMod(modId);
        var entry = RequireDefinition(mod).Find(entryKey);
        if (entry is null || entry.Type != ModSettingType.Action)
        {
            return new ModSettingsRuntimeResult
            {
                Error = $"Unknown action setting '{entryKey}'."
            };
        }

        var instance = _instanceContext.Current;
        if (instance.State == ModSettingsGameInstanceState.NotRunning)
        {
            return new ModSettingsRuntimeResult
            {
                Error = "No owned game instance is running."
            };
        }
        if (entry.Scope == ModSettingScope.Host &&
            instance.State ==
                ModSettingsGameInstanceState.RunningClientInSession)
        {
            return new ModSettingsRuntimeResult
            {
                Error = "Host-scope action requires session authority."
            };
        }
        return await _runtime.InvokeActionAsync(
            instance.PipeName,
            mod.ModId,
            entryKey,
            cancellationToken);
    }

    private DiscoveredModSettings FindMod(string modId)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(modId);
        var matches = Discover()
            .Where(mod => string.Equals(
                mod.ModId,
                modId,
                StringComparison.Ordinal))
            .Take(2)
            .ToArray();
        return matches.Length switch
        {
            1 => matches[0],
            0 => throw new KeyNotFoundException(
                $"Mod settings schema '{modId}' was not found."),
            _ => throw new InvalidOperationException(
                $"Multiple staged mods declare identifier '{modId}'.")
        };
    }

    private static ModSettingsDefinition RequireDefinition(
        DiscoveredModSettings mod)
    {
        if (mod.Validation.Status != ModSettingsManifestStatus.Valid ||
            mod.Validation.Definition is null)
        {
            throw new InvalidOperationException(
                $"Mod '{mod.ModId}' has no valid settings definition: " +
                mod.Validation.Error);
        }
        return mod.Validation.Definition;
    }

    private void OnInstanceContextChanged(object? sender, EventArgs args) =>
        InstanceStateChanged?.Invoke(this, EventArgs.Empty);
}
