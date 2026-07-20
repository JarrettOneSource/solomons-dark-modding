using Microsoft.Win32;

namespace SolomonDarkModLauncher.UI.Infrastructure;

internal static class LauncherProtocolRegistration
{
    private const string ProtocolKeyPath =
        @"Software\Classes\solomondarkrevived";

    public static void RegisterCurrentExecutable()
    {
        var executablePath = Environment.ProcessPath;
        if (string.IsNullOrWhiteSpace(executablePath) || !File.Exists(executablePath))
        {
            throw new InvalidOperationException(
                "The launcher cannot register website lobby links because its executable path is unavailable.");
        }

        using var protocolKey = Registry.CurrentUser.CreateSubKey(ProtocolKeyPath);
        protocolKey.SetValue(null, "URL:Solomon Dark Revived Lobby");
        protocolKey.SetValue("URL Protocol", string.Empty);

        using var iconKey = protocolKey.CreateSubKey("DefaultIcon");
        iconKey.SetValue(null, $"\"{executablePath}\",0");

        using var commandKey = protocolKey.CreateSubKey(@"shell\open\command");
        commandKey.SetValue(null, $"\"{executablePath}\" \"%1\"");
    }
}
