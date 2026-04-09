using SolomonDarkModLauncher.Mods;

namespace SolomonDarkModLauncher.Staging;

internal sealed class RuntimeStageFlags
{
    public const string LoaderLuaEngineKey = "loader.lua_engine";
    public const string LoaderNativeModsKey = "loader.native_mods";
    public const string LoaderRuntimeTickServiceKey = "loader.runtime_tick_service";
    public const string LoaderDebugUiKey = "loader.debug_ui";
    public const string MultiplayerSteamBootstrapKey = "multiplayer.steam_bootstrap";
    public const string MultiplayerFoundationKey = "multiplayer.foundation";
    public const string MultiplayerServiceLoopKey = "multiplayer.service_loop";

    private static readonly HashSet<string> KnownFlagKeys = new(StringComparer.OrdinalIgnoreCase)
    {
        LoaderLuaEngineKey,
        LoaderNativeModsKey,
        LoaderRuntimeTickServiceKey,
        LoaderDebugUiKey,
        MultiplayerSteamBootstrapKey,
        MultiplayerFoundationKey,
        MultiplayerServiceLoopKey
    };

    private RuntimeStageFlags()
    {
    }

    public RuntimeStageProfile Profile { get; private init; }

    public bool LoaderLuaEngine { get; private set; }

    public bool LoaderNativeMods { get; private set; }

    public bool LoaderRuntimeTickService { get; private set; }

    public bool LoaderDebugUi { get; private set; }

    public bool MultiplayerSteamBootstrap { get; private set; }

    public bool MultiplayerFoundation { get; private set; }

    public bool MultiplayerServiceLoop { get; private set; }

    public string ProfileName => ToProfileName(Profile);

    public static RuntimeStageProfile ParseProfile(string? profileName)
    {
        if (string.IsNullOrWhiteSpace(profileName))
        {
            return RuntimeStageProfile.Full;
        }

        return profileName.Trim().ToLowerInvariant() switch
        {
            "full" => RuntimeStageProfile.Full,
            "bootstrap_only" or "bootstrap-only" => RuntimeStageProfile.BootstrapOnly,
            _ => throw new InvalidOperationException($"Unsupported runtime profile: {profileName}")
        };
    }

    public static string ToProfileName(RuntimeStageProfile profile)
    {
        return profile switch
        {
            RuntimeStageProfile.BootstrapOnly => "bootstrap_only",
            _ => "full"
        };
    }

    public static bool IsKnownFlagKey(string key)
    {
        return KnownFlagKeys.Contains(key);
    }

    public static RuntimeStageFlags Create(RuntimeStageOptions options)
    {
        var flags = options.Profile == RuntimeStageProfile.BootstrapOnly
            ? CreateBootstrapOnlyDefaults()
            : CreateFullDefaults();

        foreach (var pair in options.FlagOverrides)
        {
            flags.ApplyOverride(pair.Key, pair.Value);
        }

        flags.Normalize();
        return flags;
    }

    public bool ShouldStageRuntimeMod(DiscoveredMod mod)
    {
        if (!mod.RequiresRuntime)
        {
            return false;
        }

        return (mod.RequiresLuaRuntime && LoaderLuaEngine) ||
               (mod.RequiresNativeRuntime && LoaderNativeMods);
    }

    public IReadOnlyDictionary<string, bool> AsDictionary()
    {
        return new Dictionary<string, bool>(StringComparer.OrdinalIgnoreCase)
        {
            [LoaderLuaEngineKey] = LoaderLuaEngine,
            [LoaderNativeModsKey] = LoaderNativeMods,
            [LoaderRuntimeTickServiceKey] = LoaderRuntimeTickService,
            [LoaderDebugUiKey] = LoaderDebugUi,
            [MultiplayerSteamBootstrapKey] = MultiplayerSteamBootstrap,
            [MultiplayerFoundationKey] = MultiplayerFoundation,
            [MultiplayerServiceLoopKey] = MultiplayerServiceLoop
        };
    }

    private static RuntimeStageFlags CreateFullDefaults()
    {
        return new RuntimeStageFlags
        {
            Profile = RuntimeStageProfile.Full,
            LoaderLuaEngine = true,
            LoaderNativeMods = true,
            LoaderRuntimeTickService = true,
            LoaderDebugUi = true,
            MultiplayerSteamBootstrap = true,
            MultiplayerFoundation = true,
            MultiplayerServiceLoop = true
        };
    }

    private static RuntimeStageFlags CreateBootstrapOnlyDefaults()
    {
        return new RuntimeStageFlags
        {
            Profile = RuntimeStageProfile.BootstrapOnly,
            LoaderLuaEngine = false,
            LoaderNativeMods = false,
            LoaderRuntimeTickService = false,
            LoaderDebugUi = false,
            MultiplayerSteamBootstrap = true,
            MultiplayerFoundation = true,
            MultiplayerServiceLoop = true
        };
    }

    private void ApplyOverride(string key, bool value)
    {
        if (key.Equals(LoaderLuaEngineKey, StringComparison.OrdinalIgnoreCase))
        {
            LoaderLuaEngine = value;
            return;
        }

        if (key.Equals(LoaderNativeModsKey, StringComparison.OrdinalIgnoreCase))
        {
            LoaderNativeMods = value;
            return;
        }

        if (key.Equals(LoaderRuntimeTickServiceKey, StringComparison.OrdinalIgnoreCase))
        {
            LoaderRuntimeTickService = value;
            return;
        }

        if (key.Equals(LoaderDebugUiKey, StringComparison.OrdinalIgnoreCase))
        {
            LoaderDebugUi = value;
            return;
        }

        if (key.Equals(MultiplayerSteamBootstrapKey, StringComparison.OrdinalIgnoreCase))
        {
            MultiplayerSteamBootstrap = value;
            return;
        }

        if (key.Equals(MultiplayerFoundationKey, StringComparison.OrdinalIgnoreCase))
        {
            MultiplayerFoundation = value;
            return;
        }

        if (key.Equals(MultiplayerServiceLoopKey, StringComparison.OrdinalIgnoreCase))
        {
            MultiplayerServiceLoop = value;
        }
    }

    private void Normalize()
    {
        if (!LoaderNativeMods)
        {
            LoaderRuntimeTickService = false;
        }

        if (!MultiplayerFoundation)
        {
            MultiplayerServiceLoop = false;
        }
    }
}
