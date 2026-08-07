from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.splice_native_menu_navigation_edges import (
    NavigationSpliceError,
    splice_navigation,
)


def recording(edge_ids: list[str], instance: str) -> dict[str, object]:
    return {
        "schema": "solomon-dark-native-menu-navigation-v2",
        "header": {
            "sessions": [
                {"instance": instance, "process_id": 1, "source": {"commit": "a"}}
            ]
        },
        "edges": [
            {
                "id": edge_id,
                "header": {"label": edge_id, "instance": instance},
                "source": f"{edge_id}-source",
                "destination": f"{edge_id}-destination",
            }
            for edge_id in edge_ids
        ],
    }


class NavigationEdgeSpliceTests(unittest.TestCase):
    def write(self, root: Path, name: str, value: object) -> Path:
        path = root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_replaces_exact_edge_and_preserves_census(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = self.write(root, "base.json", recording(["one", "two"], "base"))
            donor = self.write(root, "donor.json", recording(["fresh"], "donor"))
            output = root / "output.json"
            result = splice_navigation(base, donor, output, {"two": "fresh"})
            value = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result["edge_count"], 2)
            self.assertEqual([edge["id"] for edge in value["edges"]], ["one", "two"])
            self.assertEqual(value["edges"][1]["header"]["label"], "two")
            self.assertEqual(value["edges"][1]["source"], "fresh-source")
            self.assertEqual(len(value["header"]["sessions"]), 2)

    def test_refuses_ambiguous_donor_edge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = self.write(root, "base.json", recording(["one"], "base"))
            duplicate = recording(["fresh", "fresh"], "donor")
            donor = self.write(root, "donor.json", duplicate)
            with self.assertRaisesRegex(
                NavigationSpliceError, "donor navigation edge id 'fresh' is ambiguous"
            ):
                splice_navigation(base, donor, root / "output.json", {"one": "fresh"})

    def test_refuses_missing_exact_edge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = self.write(root, "base.json", recording(["one"], "base"))
            donor = self.write(root, "donor.json", recording(["fresh"], "donor"))
            with self.assertRaisesRegex(
                NavigationSpliceError, r"missing_targets=\['two'\]"
            ):
                splice_navigation(base, donor, root / "output.json", {"two": "fresh"})

    def test_refuses_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = self.write(root, "base.json", recording(["one"], "base"))
            donor = self.write(root, "donor.json", recording(["fresh"], "donor"))
            output = self.write(root, "output.json", {})
            with self.assertRaisesRegex(NavigationSpliceError, "output already exists"):
                splice_navigation(base, donor, output, {"one": "fresh"})


if __name__ == "__main__":
    unittest.main()
