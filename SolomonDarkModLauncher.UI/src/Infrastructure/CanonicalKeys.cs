using System.Windows.Input;

namespace SolomonDarkModLauncher.UI.Infrastructure;

/// <summary>
/// The canonical keybind namespace shared with the loader, per
/// docs/design/mod-settings-2026-07-27.md §1: A–Z, 0–9, F1–F24, SPACE, TAB,
/// ENTER, SHIFT, CTRL, ALT, UP, DOWN, LEFT, RIGHT, MOUSE3–MOUSE5, NONE.
/// </summary>
internal static class CanonicalKeys
{
    public const string None = "NONE";

    public static bool IsValid(string name)
    {
        if (string.IsNullOrEmpty(name))
        {
            return false;
        }

        if (name is None or "SPACE" or "TAB" or "ENTER" or "SHIFT" or "CTRL" or "ALT"
            or "UP" or "DOWN" or "LEFT" or "RIGHT" or "MOUSE3" or "MOUSE4" or "MOUSE5")
        {
            return true;
        }

        if (name.Length == 1)
        {
            char c = name[0];
            return c is >= 'A' and <= 'Z' or >= '0' and <= '9';
        }

        if (name.Length is 2 or 3 && name[0] == 'F'
            && int.TryParse(name.AsSpan(1), out int f))
        {
            return f is >= 1 and <= 24;
        }

        return false;
    }

    public static string? FromKey(Key key)
    {
        if (key is >= Key.A and <= Key.Z)
        {
            return ((char)('A' + (key - Key.A))).ToString();
        }

        if (key is >= Key.D0 and <= Key.D9)
        {
            return ((char)('0' + (key - Key.D0))).ToString();
        }

        if (key is >= Key.NumPad0 and <= Key.NumPad9)
        {
            return ((char)('0' + (key - Key.NumPad0))).ToString();
        }

        if (key is >= Key.F1 and <= Key.F24)
        {
            return $"F{key - Key.F1 + 1}";
        }

        return key switch
        {
            Key.Space => "SPACE",
            Key.Tab => "TAB",
            Key.Enter => "ENTER",
            Key.LeftShift or Key.RightShift => "SHIFT",
            Key.LeftCtrl or Key.RightCtrl => "CTRL",
            Key.LeftAlt or Key.RightAlt or Key.System => "ALT",
            Key.Up => "UP",
            Key.Down => "DOWN",
            Key.Left => "LEFT",
            Key.Right => "RIGHT",
            _ => null
        };
    }

    public static string? FromMouseButton(MouseButton button) => button switch
    {
        MouseButton.Middle => "MOUSE3",
        MouseButton.XButton1 => "MOUSE4",
        MouseButton.XButton2 => "MOUSE5",
        _ => null
    };

    public static string DisplayText(string name) => name switch
    {
        None => "Not bound",
        "MOUSE3" => "Middle Mouse",
        "MOUSE4" => "Mouse 4",
        "MOUSE5" => "Mouse 5",
        _ => name
    };
}
