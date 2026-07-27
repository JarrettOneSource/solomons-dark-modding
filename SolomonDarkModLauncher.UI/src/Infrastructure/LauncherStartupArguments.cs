using SolomonDarkModding.IO;

namespace SolomonDarkModLauncher.UI.Infrastructure;

internal sealed record LauncherStartupArguments(
    string ActivationArgument,
    string TestScope)
{
    private const string TestScopePrefix =
        "--test-activation-scope=";

    public bool IsTestScoped => TestScope.Length != 0;

    public static bool TryParse(
        IReadOnlyList<string> arguments,
        out LauncherStartupArguments parsed)
    {
        parsed = null!;
        if (arguments.Count == 0)
        {
            parsed = new LauncherStartupArguments(
                string.Empty,
                string.Empty);
            return true;
        }
        if (arguments.Count == 1 &&
            !arguments[0].StartsWith(
                TestScopePrefix,
                StringComparison.Ordinal))
        {
            parsed = new LauncherStartupArguments(
                arguments[0],
                string.Empty);
            return true;
        }
        if (arguments.Count is < 1 or > 2 ||
            !arguments[0].StartsWith(
                TestScopePrefix,
                StringComparison.Ordinal) ||
            !TryNormalizeTestScope(
                arguments[0][TestScopePrefix.Length..],
                out var scope))
        {
            return false;
        }

        parsed = new LauncherStartupArguments(
            arguments.Count == 2
                ? arguments[1]
                : string.Empty,
            scope);
        return true;
    }

    public void ApplyTestIsolation()
    {
        if (!IsTestScoped)
        {
            return;
        }
        var dataRoot = Path.GetFullPath(Path.Combine(
            AppContext.BaseDirectory,
            ".sdmod-test-data",
            TestScope));
        Environment.SetEnvironmentVariable(
            LauncherPathPolicy
                .TestApplicationDataRootEnvironmentVariable,
            dataRoot);
    }

    public string ProtocolCommandScopeArgument =>
        IsTestScoped
        ? TestScopePrefix + TestScope
        : string.Empty;

    private static bool TryNormalizeTestScope(
        string value,
        out string scope)
    {
        scope = value.Trim();
        return scope.Length is >= 1 and <= 40 &&
            scope[0] is >= 'a' and <= 'z' or
                >= '0' and <= '9' &&
            scope[^1] is >= 'a' and <= 'z' or
                >= '0' and <= '9' &&
            !scope.Contains("--", StringComparison.Ordinal) &&
            scope.All(character =>
                character is >= 'a' and <= 'z' or
                    >= '0' and <= '9' or '-');
    }
}
