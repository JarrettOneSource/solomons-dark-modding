using System.Collections.ObjectModel;

namespace SolomonDarkModLauncher.Staging;

internal sealed class RuntimeStageOptions
{
    public static RuntimeStageOptions Default { get; } =
        new(RuntimeStageProfile.Full, new ReadOnlyDictionary<string, bool>(new Dictionary<string, bool>()));

    public RuntimeStageOptions(
        RuntimeStageProfile profile,
        IReadOnlyDictionary<string, bool> flagOverrides)
    {
        Profile = profile;
        FlagOverrides = flagOverrides;
    }

    public RuntimeStageProfile Profile { get; }

    public IReadOnlyDictionary<string, bool> FlagOverrides { get; }

    public bool HasOverrides => FlagOverrides.Count > 0;

    public static RuntimeStageOptions Create(
        string? profileName,
        IReadOnlyList<string>? rawFlagOverrides)
    {
        var profile = RuntimeStageFlags.ParseProfile(profileName);
        var overrides = new Dictionary<string, bool>(StringComparer.OrdinalIgnoreCase);

        if (rawFlagOverrides is not null)
        {
            foreach (var rawOverride in rawFlagOverrides)
            {
                var separatorIndex = rawOverride.IndexOf('=');
                if (separatorIndex <= 0 || separatorIndex >= rawOverride.Length - 1)
                {
                    throw new InvalidOperationException(
                        $"Invalid runtime flag override '{rawOverride}'. Expected <flag>=<true|false>.");
                }

                var key = rawOverride[..separatorIndex].Trim();
                var rawValue = rawOverride[(separatorIndex + 1)..].Trim();
                if (!RuntimeStageFlags.IsKnownFlagKey(key))
                {
                    throw new InvalidOperationException($"Unknown runtime flag override: {key}");
                }

                overrides[key] = ParseBooleanValue(rawValue, rawOverride);
            }
        }

        return new RuntimeStageOptions(
            profile,
            new ReadOnlyDictionary<string, bool>(overrides));
    }

    private static bool ParseBooleanValue(string rawValue, string rawOverride)
    {
        if (rawValue.Equals("1", StringComparison.OrdinalIgnoreCase) ||
            rawValue.Equals("true", StringComparison.OrdinalIgnoreCase) ||
            rawValue.Equals("yes", StringComparison.OrdinalIgnoreCase) ||
            rawValue.Equals("on", StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        if (rawValue.Equals("0", StringComparison.OrdinalIgnoreCase) ||
            rawValue.Equals("false", StringComparison.OrdinalIgnoreCase) ||
            rawValue.Equals("no", StringComparison.OrdinalIgnoreCase) ||
            rawValue.Equals("off", StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        throw new InvalidOperationException(
            $"Invalid runtime flag override '{rawOverride}'. Boolean values must be true/false, yes/no, on/off, or 1/0.");
    }
}
