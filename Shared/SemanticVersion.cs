namespace SolomonDarkModding.Versioning;

internal sealed class SemanticVersion : IComparable<SemanticVersion>
{
    private SemanticVersion(
        string major,
        string minor,
        string patch,
        string[] prerelease,
        string value)
    {
        Major = major;
        Minor = minor;
        Patch = patch;
        Prerelease = prerelease;
        Value = value;
    }

    private string Major { get; }
    private string Minor { get; }
    private string Patch { get; }
    public IReadOnlyList<string> Prerelease { get; }
    public string Value { get; }

    public static bool TryParse(string? value, out SemanticVersion? version)
    {
        version = null;
        if (string.IsNullOrWhiteSpace(value) || value.Length > 64)
        {
            return false;
        }

        var buildStart = value.IndexOf('+');
        var precedence = buildStart < 0 ? value : value[..buildStart];
        var build = buildStart < 0 ? null : value[(buildStart + 1)..];
        if (build is not null && !ValidIdentifiers(build, rejectNumericLeadingZero: false))
        {
            return false;
        }

        var prereleaseStart = precedence.IndexOf('-');
        var core = prereleaseStart < 0 ? precedence : precedence[..prereleaseStart];
        var prereleaseText = prereleaseStart < 0 ? null : precedence[(prereleaseStart + 1)..];
        if (prereleaseText is not null &&
            !ValidIdentifiers(prereleaseText, rejectNumericLeadingZero: true))
        {
            return false;
        }

        var parts = core.Split('.');
        if (parts.Length != 3 ||
            !ValidCorePart(parts[0]) ||
            !ValidCorePart(parts[1]) ||
            !ValidCorePart(parts[2]))
        {
            return false;
        }

        version = new SemanticVersion(
            parts[0],
            parts[1],
            parts[2],
            prereleaseText?.Split('.') ?? [],
            value);
        return true;
    }

    public int CompareTo(SemanticVersion? other)
    {
        if (other is null)
        {
            return 1;
        }

        var core = CompareNumericIdentifier(Major, other.Major);
        if (core == 0)
        {
            core = CompareNumericIdentifier(Minor, other.Minor);
        }
        if (core == 0)
        {
            core = CompareNumericIdentifier(Patch, other.Patch);
        }
        if (core != 0)
        {
            return core;
        }

        if (Prerelease.Count == 0 || other.Prerelease.Count == 0)
        {
            return Prerelease.Count == other.Prerelease.Count
                ? 0
                : Prerelease.Count == 0 ? 1 : -1;
        }

        for (var index = 0; index < Math.Min(Prerelease.Count, other.Prerelease.Count); index++)
        {
            var left = Prerelease[index];
            var right = other.Prerelease[index];
            var leftNumeric = left.All(char.IsAsciiDigit);
            var rightNumeric = right.All(char.IsAsciiDigit);
            var result = leftNumeric && rightNumeric
                ? CompareNumericIdentifier(left, right)
                : leftNumeric
                    ? -1
                    : rightNumeric
                        ? 1
                        : string.CompareOrdinal(left, right);
            if (result != 0)
            {
                return result;
            }
        }

        return Prerelease.Count.CompareTo(other.Prerelease.Count);
    }

    private static bool ValidCorePart(string value) =>
        value.Length > 0 &&
        (value.Length == 1 || value[0] != '0') &&
        value.All(char.IsAsciiDigit);

    private static int CompareNumericIdentifier(string left, string right) =>
        left.Length != right.Length
            ? left.Length.CompareTo(right.Length)
            : string.CompareOrdinal(left, right);

    private static bool ValidIdentifiers(string value, bool rejectNumericLeadingZero)
    {
        var identifiers = value.Split('.');
        return identifiers.All(identifier =>
            identifier.Length > 0 &&
            identifier.All(character =>
                char.IsAsciiLetterOrDigit(character) || character == '-') &&
            (!rejectNumericLeadingZero ||
             !identifier.All(char.IsAsciiDigit) ||
             identifier.Length == 1 ||
             identifier[0] != '0'));
    }
}
