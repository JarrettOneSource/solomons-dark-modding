from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MAIN_WINDOW_XAML = ROOT / "SolomonDarkModLauncher.UI/src/Views/MainWindow.xaml"
MAIN_WINDOW_CODE = ROOT / "SolomonDarkModLauncher.UI/src/Views/MainWindow.xaml.cs"


class LauncherSmallScreenTests(unittest.TestCase):
    def test_window_fits_working_area_and_keeps_content_scrollable(self) -> None:
        xaml = MAIN_WINDOW_XAML.read_text(encoding="utf-8")
        code = MAIN_WINDOW_CODE.read_text(encoding="utf-8")

        self.assertIn('x:Name="MainContentScrollViewer"', xaml)
        self.assertIn('MinWidth="560"', xaml)
        self.assertIn('MinHeight="480"', xaml)
        self.assertGreaterEqual(
            xaml.count('VerticalScrollBarVisibility="Auto"'),
            3,
            "main content and both modal cards must scroll on short displays",
        )

        for token in (
            "FitToWorkingArea(SystemParameters.WorkArea)",
            "const double screenMargin = 16.0;",
            "MinWidth = Math.Min(designMinimumWidth, fittedWidth);",
            "MinHeight = Math.Min(designMinimumHeight, fittedHeight);",
            "WindowStartupLocation = WindowStartupLocation.Manual;",
        ):
            self.assertIn(token, code)


if __name__ == "__main__":
    unittest.main()
