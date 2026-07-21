#!/usr/bin/env python3
"""Regression tests for the recovered native audio registry and music table."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = REPOSITORY_ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from build_native_audio_catalog import parse_music_table, parse_registry  # noqa: E402


AUDIO_CATALOG = REPOSITORY_ROOT / "docs/reverse-engineering/native-audio-catalog.json"


class NativeAudioToolsTest(unittest.TestCase):
    def test_registry_parser_preserves_native_addresses_and_path(self) -> None:
        rows = parse_registry(
            "noise\n"
            "AUDIO_REGISTRY\t0\t004ee08a\t0078fd24\t004ee0a8\t"
            "0x004076d0\t[ESI + 0x18]\tsounds\\click\n"
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["registry_index"], 0)
        self.assertEqual(rows[0]["native_class"], "Sound")
        self.assertEqual(rows[0]["registry_member_offset"], "0x00000018")
        self.assertEqual(rows[0]["myapp_member_offset"], "0x00319EE0")
        self.assertEqual(rows[0]["path_without_extension"], "sounds\\click")
        self.assertEqual(rows[0]["category"], "root")

    def test_music_parser_preserves_song_scope_and_duplicate_channels(self) -> None:
        songs = parse_music_table(
            "// fixture\n"
            "song=first:0\n"
            "  track=base:1,2\n"
            "song=second:0x10\n"
            "  track=glory:29,31,31,32\n"
        )
        self.assertEqual([song["name"] for song in songs], ["first", "second"])
        self.assertEqual(songs[1]["module_offset"], 0x10)
        self.assertEqual(songs[1]["tracks"][0]["channels"], [29, 31, 31, 32])

    def test_checked_in_stock_catalog_invariants(self) -> None:
        catalog = json.loads(AUDIO_CATALOG.read_text(encoding="utf-8"))
        summary = catalog["summary"]
        self.assertEqual(summary["compiled_registry_entry_count"], 233)
        self.assertEqual(
            summary["compiled_class_counts"],
            {"Sound": 171, "SoundLoop": 22, "SoundStream": 40},
        )
        self.assertEqual(
            summary["compiled_segment_counts"],
            {
                "fixed_loops": 22,
                "fixed_one_shots": 111,
                "fixed_streams": 40,
                "grouped_variants": 60,
            },
        )
        self.assertEqual(summary["compiled_extension_counts"], {".wav": 233})
        self.assertEqual(summary["voice_file_count"], 70)
        self.assertEqual(summary["voice_with_dialogue_definition_count"], 34)
        self.assertEqual(summary["voice_without_dialogue_definition_count"], 36)
        self.assertEqual(summary["dynamic_sound_count"], 1)
        self.assertEqual(summary["wav_file_count"], 304)
        self.assertEqual(summary["music_song_count"], 12)
        self.assertEqual(summary["music_track_count"], 19)

        registry = catalog["compiled_registry"]
        self.assertEqual([entry["registry_index"] for entry in registry], list(range(233)))
        self.assertEqual(registry[0]["path_without_extension"], "sounds\\click")
        self.assertEqual(registry[110]["native_class"], "Sound")
        self.assertEqual(registry[111]["native_class"], "SoundStream")
        self.assertEqual(registry[151]["native_class"], "SoundLoop")
        self.assertEqual(registry[173]["registry_segment"], "grouped_variants")
        self.assertEqual(registry[-1]["registry_member_offset"], "0x000026D0")
        self.assertTrue(all(entry["file"]["path"].lower().endswith(".wav") for entry in registry))

        glory = next(
            track
            for song in catalog["music"]["songs"]
            if song["name"] == "combatprelude"
            for track in song["tracks"]
            if track["name"] == "glory"
        )
        self.assertEqual(glory["channels"], [25, 26, 27, 28, 29, 31, 31, 32])


if __name__ == "__main__":
    unittest.main()
