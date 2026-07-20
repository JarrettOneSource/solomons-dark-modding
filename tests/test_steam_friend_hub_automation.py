from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from steam_friend_hub_automation import native_hub_surface_state


class NativeHubSurfaceStateTests(unittest.TestCase):
    def test_returns_surface_and_chat_state(self) -> None:
        def lua(endpoint: str, code: str, timeout: float) -> str:
            self.assertEqual(endpoint, "owner")
            self.assertIn("sd.hub.get_surface_state()", code)
            self.assertEqual(timeout, 5.0)
            return "surface_active=true\nchat_active=false\n"

        self.assertEqual(native_hub_surface_state(lua, "owner"), (True, False))


if __name__ == "__main__":
    unittest.main()
