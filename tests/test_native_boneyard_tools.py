#!/usr/bin/env python3
"""Regression tests for the recovered native SyncBuffer/.boneyard grammar."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = REPOSITORY_ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from build_native_boneyard_catalog import build_entry  # noqa: E402
from inspect_native_boneyard import (  # noqa: E402
    Cursor,
    ParseError,
    build_summary,
    parse_sync_buffer,
    resolve_node,
)


FIXTURE = REPOSITORY_ROOT / "tests/fixtures/boneyards/flat_multiplayer_test.boneyard"
OBJECT_CATALOG = (
    REPOSITORY_ROOT / "docs/reverse-engineering/native-game-object-catalog.json"
)
BONEYARD_CATALOG = (
    REPOSITORY_ROOT / "docs/reverse-engineering/native-boneyard-catalog.json"
)


class NativeBoneyardToolsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        object_catalog = json.loads(OBJECT_CATALOG.read_text(encoding="utf-8"))
        cls.type_names = {
            entry["type_id"]: entry["class"] for entry in object_catalog["types"]
        }

    def test_fixture_parses_exactly_to_eof(self) -> None:
        data = FIXTURE.read_bytes()
        cursor = Cursor(data)
        root = parse_sync_buffer(cursor)
        self.assertEqual(cursor.offset, len(data))
        self.assertEqual(root.named_children, ())

        summary = build_summary(FIXTURE, data, root)
        self.assertEqual(summary["size"], 148413)
        self.assertEqual(
            summary["sha256"],
            "7c7d23f2fbfcdf73b5bb7f4af0f836cc9d199997fe9c7dd38183c7659b6d949d",
        )
        self.assertEqual(summary["anonymous_node_count"], 7721)
        self.assertEqual(summary["payload_bytes"], 86641)
        self.assertEqual(summary["maximum_anonymous_node_depth"], 9)

        layout = resolve_node(root.root, (0, 12, 0))
        self.assertEqual(len(layout.children), 14)

    def test_fixture_region_layout_matches_generated_catalog(self) -> None:
        rebuilt = build_entry("fixture/flat_multiplayer_test.boneyard", FIXTURE, self.type_names)
        catalog = json.loads(BONEYARD_CATALOG.read_text(encoding="utf-8"))
        checked_in = next(
            entry
            for entry in catalog["files"]
            if entry["label"] == "fixture/flat_multiplayer_test.boneyard"
        )
        self.assertEqual(rebuilt, checked_in)

        layout = rebuilt["region_layout"]
        self.assertEqual(layout["origin"], {"x": 1024.0, "y": 1024.0})
        self.assertEqual(layout["lists"]["scenery"]["count"], 0)
        self.assertEqual(layout["lists"]["roads"]["count"], 0)
        self.assertEqual(layout["lists"]["fences"]["count"], 0)
        self.assertEqual(layout["compact_decorations"]["count"], 0)
        self.assertEqual(
            layout["timelines"],
            [
                {
                    "name": "Survival Time line",
                    "uid": 36679,
                    "enabled_byte": 0,
                    "event_count": 571,
                    "event_type_counts": {"TimeLineEvent": 571},
                    "trailing_payload_bytes": 23,
                }
            ],
        )

    def test_truncated_container_is_rejected(self) -> None:
        cursor = Cursor(FIXTURE.read_bytes()[:-1])
        with self.assertRaises(ParseError):
            parse_sync_buffer(cursor)


if __name__ == "__main__":
    unittest.main()
