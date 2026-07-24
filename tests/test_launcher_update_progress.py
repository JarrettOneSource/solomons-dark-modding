from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LauncherUpdateProgressTests(unittest.TestCase):
    def test_cli_progress_reaches_the_desktop_view_model(self) -> None:
        application = (
            ROOT / "SolomonDarkModLauncher/src/App/LauncherApplication.cs"
        ).read_text(encoding="utf-8")
        executor = (
            ROOT / "SolomonDarkModLauncher/src/App/LauncherCommandExecutor.cs"
        ).read_text(encoding="utf-8")
        client = (
            ROOT
            / "SolomonDarkModLauncher.UI/src/Infrastructure/LauncherUiCommandClient.cs"
        ).read_text(encoding="utf-8")
        reader = (
            ROOT
            / "SolomonDarkModLauncher.UI/src/Infrastructure/LauncherJsonResponseReader.cs"
        ).read_text(encoding="utf-8")
        view_model = (
            ROOT / "SolomonDarkModLauncher.UI/src/ViewModels/MainWindowViewModel.cs"
        ).read_text(encoding="utf-8")

        self.assertIn("LauncherJsonConsole.CreateProgressReporter()", application)
        self.assertIn("LauncherCommandExecutor.Execute(command, progress)", application)
        self.assertIn("UpdateProgressPhase.Failed", application)
        self.assertIn("LauncherJsonConsole.PrintProgress(", application)
        self.assertGreaterEqual(executor.count("progress)"), 2)
        self.assertIn('"--progress-json"', client)
        self.assertIn("progress?.Report(updateProgress!)", reader)
        self.assertIn(
            "new Progress<UpdateProgress>(ReportUpdateProgress)",
            view_model,
        )

    def test_all_package_update_paths_report_real_progress_and_failures(self) -> None:
        self_update = (
            ROOT
            / "SolomonDarkModLauncher.UI/src/Infrastructure/LauncherSelfUpdater.cs"
        ).read_text(encoding="utf-8")
        package_installer = (
            ROOT
            / "SolomonDarkModLauncher/src/Mods/WebsiteModPackageInstaller.cs"
        ).read_text(encoding="utf-8")
        mod_updater = (
            ROOT / "SolomonDarkModLauncher/src/Mods/WebsiteModUpdater.cs"
        ).read_text(encoding="utf-8")
        lobby_sync = (
            ROOT / "SolomonDarkModLauncher/src/Mods/LobbyModSynchronizer.cs"
        ).read_text(encoding="utf-8")
        updater_program = (
            ROOT / "SolomonDarkLauncherUpdater/Program.cs"
        ).read_text(encoding="utf-8")
        updater_form = (
            ROOT / "SolomonDarkLauncherUpdater/src/UpdateProgressForm.cs"
        ).read_text(encoding="utf-8")
        main_window = (
            ROOT / "SolomonDarkModLauncher.UI/src/Views/MainWindow.xaml"
        ).read_text(encoding="utf-8")

        for source in (self_update, package_installer):
            self.assertIn("UpdateProgressPhase.Downloading", source)
            self.assertIn("UpdateProgressUnit.Bytes", source)
            self.assertIn("UpdateProgressPhase.Verifying", source)
        self.assertIn("UpdateProgressPhase.Failed", mod_updater)
        self.assertIn("UpdateProgressPhase.Completed", mod_updater)
        self.assertIn("UpdateProgressPhase.Failed", lobby_sync)
        self.assertIn("UpdateProgressPhase.Completed", lobby_sync)
        self.assertIn("LauncherUpdateInstaller.Install(", updater_program)
        self.assertIn("UpdateProgressPhase.Restarting", updater_program)
        self.assertIn("UpdateProgressPhase.Completed", updater_program)
        self.assertIn("ShowFailure(", updater_form)
        self.assertIn("restartButton_", updater_form)
        self.assertIn(
            'Value="{Binding UpdateProgressValue, Mode=OneWay}"',
            main_window,
        )


if __name__ == "__main__":
    unittest.main()
