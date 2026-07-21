from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from multiplayer_pickup_geometry import (  # noqa: E402
    PickupGeometryRuntime,
    select_reachable_spawn_point,
)


class PickupGeometryTests(unittest.TestCase):
    def test_spawn_anchor_uses_position_after_native_scene_clamp(self) -> None:
        client_id = 2
        position = [1000.0, 1000.0]

        def capture_pair() -> dict[str, dict[str, str]]:
            x, y = position
            return {
                "client": {
                    "player.x": str(x),
                    "player.y": str(y),
                },
                "host": {
                    "player.x": "0.0",
                    "player.y": "0.0",
                    "participant.x": str(x),
                    "participant.y": str(y),
                },
            }

        def find_participant(
            values: dict[str, str], participant_id: int
        ) -> dict[str, float] | None:
            if participant_id != client_id:
                return None
            return {
                "x": float(values["participant.x"]),
                "y": float(values["participant.y"]),
            }

        def place_player(
            _pipe_name: str, x: float, y: float, _heading: float
        ) -> dict[str, str]:
            position[0] = min(x, 1200.0)
            position[1] = min(y, 1200.0)
            return {
                "after.x": str(x),
                "after.y": str(y),
            }

        runtime = PickupGeometryRuntime(
            client_pipe="client",
            client_participant_id=client_id,
            capture_pair=capture_pair,
            find_participant=find_participant,
            place_player=place_player,
            snap_to_nav=lambda _pipe_name, x, y: (x, y),
        )

        selected = select_reachable_spawn_point(
            runtime,
            pickup_suppression_radius=335.0,
            settle_seconds=0.0,
            timeout=1.0,
        )

        self.assertEqual((selected["snapped_x"], selected["snapped_y"]), (1200.0, 1200.0))
        self.assertNotEqual(
            (selected["nav_x"], selected["nav_y"]),
            (selected["snapped_x"], selected["snapped_y"]),
        )
        self.assertEqual(
            (
                selected["host_participant"]["x"],
                selected["host_participant"]["y"],
            ),
            (1200.0, 1200.0),
        )


if __name__ == "__main__":
    unittest.main()
