namespace SolomonDarkModLauncher.Launch;

internal static class NativeResumeSelector
{
    private const string ResumeKey = "Game.Resume";

    public static string? Materialize(
        string stageRootPath,
        string savegamesRootPath)
    {
        stageRootPath = Path.GetFullPath(stageRootPath);
        savegamesRootPath = Path.GetFullPath(savegamesRootPath);
        var settingsPath = Path.Combine(stageRootPath, "sandbox", "settings.txt");
        if (!File.Exists(settingsPath))
        {
            return null;
        }

        var profileRoot = Path.Combine(savegamesRootPath, "solomondark");
        var runsRoot = Path.Combine(profileRoot, "savegames");
        if (!Directory.Exists(runsRoot))
        {
            return null;
        }

        var text = File.ReadAllText(settingsPath);
        var newline = text.Contains("\r\n", StringComparison.Ordinal)
            ? "\r\n"
            : "\n";
        var finalNewline = text.EndsWith(newline, StringComparison.Ordinal);
        var lines = text.Split(
            ["\r\n", "\n"],
            StringSplitOptions.None).ToList();
        if (finalNewline && lines.Count > 0 && lines[^1].Length == 0)
        {
            lines.RemoveAt(lines.Count - 1);
        }

        var resumeIndex = lines.FindIndex(line =>
            line.StartsWith(ResumeKey + "=", StringComparison.Ordinal));
        var selectedRun = resumeIndex >= 0
            ? ExistingRunName(lines[resumeIndex], runsRoot)
            : null;
        selectedRun ??= UnambiguousRunName(runsRoot);
        if (selectedRun is null)
        {
            return null;
        }

        var nativeRunPath = Path.Combine(
            stageRootPath,
            "sandbox",
            "savegames",
            "solomondark",
            "savegames",
            selectedRun) + Path.DirectorySeparatorChar;
        var row = $"{ResumeKey}={nativeRunPath}";
        if (resumeIndex >= 0)
        {
            lines[resumeIndex] = row;
        }
        else
        {
            lines.Add(row);
        }

        var encoded = string.Join(newline, lines) + (finalNewline ? newline : string.Empty);
        var temporaryPath = settingsPath + ".resume.tmp";
        File.WriteAllText(temporaryPath, encoded);
        File.Move(temporaryPath, settingsPath, overwrite: true);
        return selectedRun;
    }

    private static string? ExistingRunName(string row, string runsRoot)
    {
        var value = row[(ResumeKey.Length + 1)..].TrimEnd(
            Path.DirectorySeparatorChar,
            Path.AltDirectorySeparatorChar);
        if (value.Length == 0)
        {
            return null;
        }
        var runName = Path.GetFileName(value);
        return IsSafeRunName(runName) &&
            File.Exists(Path.Combine(runsRoot, runName, "gamestate.sav"))
                ? runName
                : null;
    }

    private static string? UnambiguousRunName(string runsRoot)
    {
        var runs = Directory.EnumerateDirectories(runsRoot)
            .Select(Path.GetFileName)
            .Where(runName =>
                IsSafeRunName(runName) &&
                File.Exists(Path.Combine(runsRoot, runName!, "gamestate.sav")))
            .Order(StringComparer.OrdinalIgnoreCase)
            .ToArray();
        return runs.Length == 1 ? runs[0] : null;
    }

    private static bool IsSafeRunName(string? value) =>
        !string.IsNullOrWhiteSpace(value) &&
        value.Length <= 64 &&
        value.All(character =>
            char.IsAsciiLetterOrDigit(character) ||
            character is '.' or '_' or '-');
}
