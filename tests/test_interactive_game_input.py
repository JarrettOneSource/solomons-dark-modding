from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INTERACTIVE_INPUT_SCRIPT = ROOT / "scripts" / "Invoke-InteractiveGameInput.ps1"


class InteractiveTaskPowerPolicyTests(unittest.TestCase):
    def test_remote_interactive_actions_run_while_a_laptop_uses_battery(self) -> None:
        script = INTERACTIVE_INPUT_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("-AllowStartIfOnBatteries", script)
        self.assertIn("-DontStopIfGoingOnBatteries", script)


if __name__ == "__main__":
    unittest.main()
