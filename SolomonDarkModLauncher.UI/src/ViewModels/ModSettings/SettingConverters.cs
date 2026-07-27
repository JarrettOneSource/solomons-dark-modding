using System.Globalization;
using System.Windows;
using System.Windows.Data;

namespace SolomonDarkModLauncher.UI.ViewModels.ModSettings;

internal static class SettingConverters
{
    public static readonly IValueConverter BoolToVisibility = new BoolToVisibilityConverter();
    public static readonly IValueConverter Invert = new InvertBoolConverter();

    private sealed class BoolToVisibilityConverter : IValueConverter
    {
        public object Convert(object? value, Type targetType, object? parameter, CultureInfo culture) =>
            value is true ? Visibility.Visible : Visibility.Collapsed;

        public object ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture) =>
            throw new NotSupportedException();
    }

    private sealed class InvertBoolConverter : IValueConverter
    {
        public object Convert(object? value, Type targetType, object? parameter, CultureInfo culture) =>
            value is not true;

        public object ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture) =>
            value is not true;
    }
}
