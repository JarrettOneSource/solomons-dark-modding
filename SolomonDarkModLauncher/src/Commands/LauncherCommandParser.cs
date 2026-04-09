using SolomonDarkModLauncher.Workspace;

namespace SolomonDarkModLauncher.Commands;

internal static class LauncherCommandParser
{
    public static LauncherCommand Parse(string[] args)
    {
        var mode = LauncherMode.Launch;
        var showHelp = false;
        var jsonOutput = false;
        string? instanceName = null;
        string? targetModId = null;
        string? gameDir = null;
        string? modsRoot = null;
        string? runtimeRoot = null;
        string? stageRoot = null;
        string? runtimeProfile = null;
        var runtimeFlagOverrides = new List<string>();
        string? steamAppId = null;
        string? steamApiDll = null;

        for (var index = 0; index < args.Length; index++)
        {
            var arg = args[index];
            if (arg is "--help" or "-h" or "/?")
            {
                showHelp = true;
                continue;
            }

            if (arg is "launch" or "stage" or "list-mods")
            {
                mode = ParseMode(arg);
                continue;
            }

            if (arg == "--json")
            {
                jsonOutput = true;
                continue;
            }

            if (arg is "enable-mod" or "disable-mod")
            {
                mode = ParseMode(arg);
                targetModId = ReadValue(args, ref index, arg);
                continue;
            }

            if (arg == "--game-dir")
            {
                gameDir = ReadValue(args, ref index, arg);
                continue;
            }

            if (arg == "--instance")
            {
                instanceName = LauncherInstance.Normalize(ReadValue(args, ref index, arg));
                continue;
            }

            if (arg == "--mods-root")
            {
                modsRoot = ReadValue(args, ref index, arg);
                continue;
            }

            if (arg == "--stage-root")
            {
                stageRoot = ReadValue(args, ref index, arg);
                continue;
            }

            if (arg == "--runtime-root")
            {
                runtimeRoot = ReadValue(args, ref index, arg);
                continue;
            }

            if (arg == "--runtime-profile")
            {
                runtimeProfile = ReadValue(args, ref index, arg);
                continue;
            }

            if (arg == "--runtime-flag")
            {
                runtimeFlagOverrides.Add(ReadValue(args, ref index, arg));
                continue;
            }

            if (arg == "--steam-appid")
            {
                steamAppId = ReadValue(args, ref index, arg);
                continue;
            }

            if (arg == "--steam-api-dll")
            {
                steamApiDll = ReadValue(args, ref index, arg);
                continue;
            }

            throw new InvalidOperationException($"Unknown argument: {arg}");
        }

        return new LauncherCommand(
            mode,
            showHelp,
            jsonOutput,
            instanceName,
            gameDir,
            modsRoot,
            runtimeRoot,
            stageRoot,
            targetModId,
            runtimeProfile,
            runtimeFlagOverrides,
            steamAppId,
            steamApiDll);
    }

    private static LauncherMode ParseMode(string value)
    {
        return value switch
        {
            "launch" => LauncherMode.Launch,
            "stage" => LauncherMode.Stage,
            "list-mods" => LauncherMode.ListMods,
            "enable-mod" => LauncherMode.EnableMod,
            "disable-mod" => LauncherMode.DisableMod,
            _ => throw new InvalidOperationException($"Unsupported mode: {value}")
        };
    }

    private static string ReadValue(string[] args, ref int index, string optionName)
    {
        if (index + 1 >= args.Length)
        {
            throw new InvalidOperationException($"Missing value for {optionName}");
        }

        index++;
        return args[index];
    }
}
