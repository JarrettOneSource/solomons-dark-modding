using System.Text;

namespace SolomonDarkModLauncher.Workspace;

internal static class LauncherInstance
{
    public const string DefaultName = "default";

    public static string Normalize(string? instanceName)
    {
        if (TryNormalize(instanceName, out var normalized))
        {
            return normalized;
        }

        throw new InvalidOperationException(
            "Instance names may only use letters, digits, '.', '-', and '_' and must include at least one letter or digit.");
    }

    public static bool TryNormalize(string? instanceName, out string normalized)
    {
        if (string.IsNullOrWhiteSpace(instanceName))
        {
            normalized = DefaultName;
            return true;
        }

        var trimmed = instanceName.Trim();
        if (trimmed.Length == 0 || trimmed.Length > 64)
        {
            normalized = DefaultName;
            return false;
        }

        var builder = new StringBuilder(trimmed.Length);
        var hasLetterOrDigit = false;
        foreach (var character in trimmed)
        {
            if (char.IsLetterOrDigit(character))
            {
                builder.Append(char.ToLowerInvariant(character));
                hasLetterOrDigit = true;
                continue;
            }

            if (character is '.' or '-' or '_')
            {
                builder.Append(character);
                continue;
            }

            normalized = DefaultName;
            return false;
        }

        if (!hasLetterOrDigit)
        {
            normalized = DefaultName;
            return false;
        }

        normalized = builder.ToString();
        return true;
    }

    public static bool IsDefault(string? instanceName)
    {
        return string.Equals(Normalize(instanceName), DefaultName, StringComparison.Ordinal);
    }
}
