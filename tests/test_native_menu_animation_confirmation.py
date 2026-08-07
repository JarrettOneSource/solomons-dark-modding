from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.attach_native_menu_animation_confirmation import attach
from tools.native_menu_ambient_lifecycle import classify_ambient_window
from tools.native_menu_settlement_v2 import SettlementV2Error


def _element() -> dict[str, object]:
    return {
        "id": "screen.art.ui_1.1",
        "kind": "art",
        "text": "",
        "action_id": "",
        "art_id": "UI.1",
        "font_id": "",
        "text_style": "sprite",
        "visible": True,
        "interactive": False,
        "draw_order": 1,
        "rect": [10.0, 20.0, 30.0, 40.0],
        "unclipped_rect": [10.0, 20.0, 30.0, 40.0],
    }


def _samples() -> list[dict[str, object]]:
    return [
        {
            "elapsed_milliseconds": index * 55,
            "captured_at_milliseconds": 1_000 + index * 55,
            "semantic_surface": "screen",
            "semantic_generation": 3,
            "native_surface": "screen",
            "native_generation": 3,
            "payload": {
                "generation": 7,
                "screen_id": "screen",
                "screen_title": "Screen",
                "capture_method": "native",
                "elements": [_element()],
            },
        }
        for index in range(40)
    ]


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class NativeMenuAnimationConfirmationTests(unittest.TestCase):
    def _recording(
        self,
        root: Path,
        name: str,
        instance: str,
        process_id: int,
    ) -> Path:
        samples = _samples()
        classification = classify_ambient_window(samples, label=name)
        trace_path = root / f"{name}.settlement.json"
        _write_json(
            trace_path,
            {
                "schema": "solomon-dark-native-menu-settlement-trace-v2",
                "label": name,
                "instance": instance,
                "settled_window_samples": samples,
            },
        )
        fixture_path = root / f"{name}.json"
        _write_json(
            fixture_path,
            {
                "schema": "solomon-dark-native-menu-layout-v2",
                "header": {
                    "label": "screen",
                    "instance": instance,
                    "process_id": process_id,
                    "source": {
                        "base_commit_sha": "1" * 40,
                        "source_tree_sha": "2" * 40,
                        "game_executable_sha256": "3" * 64,
                        "loader_dll_sha256": "4" * 64,
                    },
                    "capture_method": "native",
                    "captured_at_utc": "2026-08-07T00:00:00Z",
                    "settlement": {
                        "structural_sha256": classification["structural_sha256"]
                    },
                    "raw_recording": {
                        "evidence_filename": trace_path.name,
                        "sha256": _sha256(trace_path),
                        "bytes": trace_path.stat().st_size,
                    },
                },
                "layout": classification["layout"],
            },
        )
        return fixture_path

    def test_attachment_rederives_v29_window_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            primary = self._recording(root, "primary", "menufx-a", 101)
            confirmation = self._recording(
                root, "confirmation", "menufx-b", 202
            )
            output = root / "screen.confirmation.json"

            attach(primary, confirmation, output, root)

            attached = json.loads(output.read_text(encoding="utf-8"))
            updated_primary = json.loads(primary.read_text(encoding="utf-8"))
            self.assertEqual(
                attached["schema"],
                "solomon-dark-native-menu-animation-confirmation-v4",
            )
            self.assertEqual(
                attached["structural_sha256"],
                updated_primary["header"]["animation_confirmation"][
                    "confirmation_structural_sha256"
                ],
            )
            self.assertEqual(len(attached["settled_window_samples"]), 40)

    def test_attachment_rejects_layout_not_derived_from_trace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            primary = self._recording(root, "primary", "menufx-a", 101)
            confirmation = self._recording(
                root, "confirmation", "menufx-b", 202
            )
            value = json.loads(confirmation.read_text(encoding="utf-8"))
            changed = copy.deepcopy(value)
            changed["layout"]["elements"][0]["art_id"] = "UI.999"
            _write_json(confirmation, changed)

            with self.assertRaisesRegex(
                SettlementV2Error,
                "confirmation fixture layout is not derived from its settlement trace",
            ):
                attach(
                    primary,
                    confirmation,
                    root / "screen.confirmation.json",
                    root,
                )

    def test_trace_receipt_disambiguates_filename_collision_only_by_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            primary_dir = root / "primary"
            confirmation_dir = root / "confirmation"
            primary_dir.mkdir()
            confirmation_dir.mkdir()
            primary = self._recording(
                primary_dir, "screen", "menufx-a", 101
            )
            confirmation = self._recording(
                confirmation_dir, "screen", "menufx-b", 202
            )

            attach(
                primary,
                confirmation,
                root / "screen.confirmation.json",
                root,
            )

            duplicate = root / "duplicate" / "screen.settlement.json"
            duplicate.parent.mkdir()
            duplicate.write_bytes(
                primary_dir.joinpath("screen.settlement.json").read_bytes()
            )
            updated_primary = json.loads(primary.read_text(encoding="utf-8"))
            updated_primary["header"].pop("animation_confirmation")
            _write_json(primary, updated_primary)
            (root / "screen.confirmation.json").unlink()
            with self.assertRaisesRegex(
                SettlementV2Error,
                "primary settlement trace receipt resolves ambiguously",
            ):
                attach(
                    primary,
                    confirmation,
                    root / "screen.confirmation.json",
                    root,
                )


if __name__ == "__main__":
    unittest.main()
