using System.Text.Json;
using Microsoft.Win32;

namespace SolomonDarkModLauncher.Launch;

internal static class SdrProtocolHandler
{
    private const string Scheme = "sdr";
    private const string RegistryPath = @"Software\Classes\sdr";

    public static bool TryRunManagement(string[] args, out int exitCode)
    {
        if (args.Length == 0 || !string.Equals(args[0], "protocol", StringComparison.OrdinalIgnoreCase))
        {
            exitCode = 0;
            return false;
        }

        var json = args.Any(argument => string.Equals(argument, "--json", StringComparison.OrdinalIgnoreCase));
        try
        {
            if (!OperatingSystem.IsWindows())
            {
                throw new PlatformNotSupportedException("sdr:// registration is supported on Windows only.");
            }

            if (args.Length < 2)
            {
                throw new InvalidOperationException("Use protocol register, protocol unregister, or protocol status.");
            }

            var action = args[1].ToLowerInvariant();
            var registered = action switch
            {
                "register" => Register(),
                "unregister" => Unregister(),
                "status" => IsRegistered(),
                _ => throw new InvalidOperationException(
                    "Use protocol register, protocol unregister, or protocol status.")
            };
            WriteResult(json, true, action, registered, null);
            exitCode = 0;
        }
        catch (Exception ex)
        {
            WriteResult(json, false, args.ElementAtOrDefault(1), false, ex.Message);
            exitCode = 1;
        }

        return true;
    }

    public static string[] TranslateOpenUri(string[] args)
    {
        if (args.Length == 0 || !string.Equals(args[0], "open-uri", StringComparison.OrdinalIgnoreCase))
        {
            return args;
        }

        if (args.Length != 2 || !Uri.TryCreate(args[1], UriKind.Absolute, out var uri) ||
            !string.Equals(uri.Scheme, Scheme, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException("open-uri requires one valid sdr:// URI.");
        }

        var command = uri.Host.ToLowerInvariant();
        if (command == "wait-for-invite")
        {
            if (uri.AbsolutePath != "/" || !string.IsNullOrEmpty(uri.Query))
            {
                throw new InvalidOperationException("The wait-for-invite URI cannot contain a path or query.");
            }

            return ["launch", "--multiplayer", "join"];
        }

        if (command != "join")
        {
            throw new InvalidOperationException("Unsupported sdr:// command.");
        }

        var lobbyText = uri.AbsolutePath.Trim('/');
        if (!ulong.TryParse(lobbyText, out var lobbyId) || lobbyId == 0)
        {
            throw new InvalidOperationException("The sdr:// join URI contains an invalid Steam lobby id.");
        }

        var translated = new List<string>
        {
            "launch",
            "--multiplayer",
            "join",
            "--lobby-id",
            lobbyId.ToString()
        };
        var ticket = ReadSingleQueryValue(uri, "ticket");
        if (ticket is not null)
        {
            translated.Add("--join-ticket");
            translated.Add(ticket);
        }

        return translated.ToArray();
    }

    private static bool Register()
    {
        var executablePath = ResolveLauncherExecutable();
        using var schemeKey = Registry.CurrentUser.CreateSubKey(RegistryPath, writable: true)
            ?? throw new InvalidOperationException("Could not create the current-user sdr:// registration.");
        schemeKey.SetValue(null, "URL:Solomon Dark Revived Lobby");
        schemeKey.SetValue("URL Protocol", string.Empty);
        using var iconKey = schemeKey.CreateSubKey("DefaultIcon", writable: true);
        iconKey?.SetValue(null, $"\"{executablePath}\",0");
        using var commandKey = schemeKey.CreateSubKey(@"shell\open\command", writable: true);
        commandKey?.SetValue(null, $"\"{executablePath}\" open-uri \"%1\"");
        return true;
    }

    private static bool Unregister()
    {
        Registry.CurrentUser.DeleteSubKeyTree(RegistryPath, throwOnMissingSubKey: false);
        return false;
    }

    private static bool IsRegistered()
    {
        using var commandKey = Registry.CurrentUser.OpenSubKey($@"{RegistryPath}\shell\open\command");
        var command = commandKey?.GetValue(null) as string;
        return command is not null && command.Contains(" open-uri ", StringComparison.OrdinalIgnoreCase);
    }

    private static string ResolveLauncherExecutable()
    {
        var path = Path.Combine(AppContext.BaseDirectory, "SolomonDarkModLauncher.exe");
        if (!File.Exists(path))
        {
            throw new FileNotFoundException(
                "SolomonDarkModLauncher.exe must be published before registering sdr://.",
                path);
        }

        return path;
    }

    private static string? ReadSingleQueryValue(Uri uri, string name)
    {
        string? value = null;
        foreach (var component in uri.Query.TrimStart('?').Split('&', StringSplitOptions.RemoveEmptyEntries))
        {
            var separator = component.IndexOf('=');
            var key = Uri.UnescapeDataString(separator < 0 ? component : component[..separator]);
            if (!string.Equals(key, name, StringComparison.Ordinal))
            {
                throw new InvalidOperationException($"Unsupported sdr:// query parameter '{key}'.");
            }

            if (value is not null)
            {
                throw new InvalidOperationException($"The sdr:// query parameter '{name}' may appear only once.");
            }

            value = Uri.UnescapeDataString(separator < 0 ? string.Empty : component[(separator + 1)..]);
        }

        return string.IsNullOrWhiteSpace(value) ? null : value;
    }

    private static void WriteResult(
        bool json,
        bool success,
        string? action,
        bool registered,
        string? error)
    {
        if (json)
        {
            Console.WriteLine(JsonSerializer.Serialize(new
            {
                success,
                action,
                scheme = "sdr",
                registered,
                error
            }, new JsonSerializerOptions(JsonSerializerDefaults.Web)));
            return;
        }

        if (!success)
        {
            Console.Error.WriteLine(error);
            return;
        }

        Console.WriteLine(registered ? "sdr:// is registered." : "sdr:// is not registered.");
    }
}
