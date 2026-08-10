from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from tools.import_native_menu_special_captures_v25 import (
    import_all,
    standardize_loader,
    standardize_loading,
)
from tools.native_menu_ambient_lifecycle import find_ambient_settled_window


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PROFILE_FIXTURES = (
    Path("tests/fixtures/webgame/native-menu-profile-state-baseline.json"),
    Path("tests/fixtures/webgame/native-menu-hub-bindings-v213.json"),
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _recorded_settlement(classification: dict[str, object]) -> dict[str, object]:
    return {
        "settled": True,
        "settle_latency_milliseconds": classification[
            "settle_latency_milliseconds"
        ],
        "stable_span_milliseconds": classification["stable_span_milliseconds"],
        "consecutive_structural_samples": classification[
            "consecutive_structural_samples"
        ],
        "total_semantic_samples": classification["total_semantic_samples"],
    }


def _loader_recording(instance: str, process_id: int) -> dict[str, object]:
    samples: list[dict[str, object]] = []
    for index in range(40):
        samples.append(
            {
                "elapsed_milliseconds": index * 55,
                "numerator": 10,
                "denominator": 10,
                "progress": 1.0,
                "complete": True,
                "reference_capture": "frame.bmp" if index == 0 else "",
                "elements": [
                    {
                        "art_id": "Loader.1",
                        "draw_kind": "sprite",
                        "rect": [10.0, 20.0, 30.0, 40.0],
                        "unclipped_rect": [10.0, 20.0, 30.0, 40.0],
                    }
                ],
            }
        )
    recording: dict[str, object] = {
        "schema": "solomon-dark-native-loader-capture-v1",
        "instance": instance,
        "process_id": process_id,
        "capture_method": "native loader hook",
        "samples": samples,
    }
    standardized, _ = standardize_loader(recording, "test loader")
    recording["settlement"] = _recorded_settlement(
        find_ambient_settled_window(standardized)
    )
    return recording


def _loading_recording(instance: str, process_id: int) -> dict[str, object]:
    samples: list[dict[str, object]] = []
    for index in range(40):
        samples.append(
            {
                "elapsed_milliseconds": index * 55,
                "reference_capture": "frame.bmp" if index == 0 else "",
                "layout": {
                    "sequence": 4,
                    "stage_id": "ready",
                    "progress": 1.0,
                    "viewport": [0.0, 0.0, 1600.0, 900.0],
                    "source_crop": [0.0, 0.0, 1600.0, 900.0],
                    "elements": [
                        {
                            "id": "background",
                            "kind": "art",
                            "art_id": "Loading.1",
                            "rect": [0.0, 0.0, 1600.0, 900.0],
                        },
                        {
                            "id": "status",
                            "kind": "text",
                            "text": "Ready",
                            "font": "Loading.Font",
                            "rect": [600.0, 700.0, 1000.0, 760.0],
                        },
                    ],
                },
            }
        )
    recording: dict[str, object] = {
        "schema": "solomon-dark-native-loading-capture-v1",
        "header": {
            "instance": instance,
            "pid": process_id,
            "capture_method": "native loading presenter",
        },
        "samples": samples,
    }
    standardized, _ = standardize_loading(recording, "test loading")
    recording["settlement"] = _recorded_settlement(
        find_ambient_settled_window(standardized)
    )
    return recording


class NativeMenuSpecialImportV25Tests(unittest.TestCase):
    def _initialize_repo(self, root: Path) -> None:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(
            ["git", "-C", str(root), "config", "user.email", "test@example.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(root), "config", "user.name", "Menufix Test"],
            check=True,
        )
        (root / "tracked.txt").write_text("fixture\n", encoding="utf-8")
        tracked = ["tracked.txt"]
        for relative in PROFILE_FIXTURES:
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPOSITORY_ROOT / relative, destination)
            tracked.append(relative.as_posix())
        subprocess.run(["git", "-C", str(root), "add", *tracked], check=True)
        subprocess.run(
            ["git", "-C", str(root), "commit", "-q", "-m", "fixture"],
            check=True,
        )

    def _stage_binaries(self, root: Path, instances: tuple[str, ...]) -> None:
        loader = root / "dist" / "launcher" / "SolomonDarkModLoader.dll"
        loader.parent.mkdir(parents=True)
        loader.write_bytes(b"loader-under-test")
        loader_hash = _sha256(loader)
        baseline = json.loads(
            (root / PROFILE_FIXTURES[0]).read_text(encoding="utf-8")
        )["profile_state"]
        for instance in instances:
            stage = root / "runtime" / "instances" / instance / "stage"
            stage.mkdir(parents=True)
            executable = stage / "SolomonDark.exe"
            executable.write_bytes(b"retail-game-under-test")
            _write_json(
                stage / ".sdmod" / "multiplayer-compatibility.json",
                {
                    "compatibility": {
                        "gameExecutable": {"sha256": _sha256(executable)},
                        "loader": {"sha256": loader_hash},
                    }
                },
            )
            _write_json(
                stage / ".sdmod" / "native-menu-profile-state.json",
                {
                    "schema": "solomon-dark-native-menu-profile-state-v1",
                    "profile_state_identity_sha256": baseline[
                        "profile_state_identity_sha256"
                    ],
                    "baseline_mode": baseline["baseline_mode"],
                    "source_sandbox_excluded": baseline[
                        "source_sandbox_excluded"
                    ],
                    "retail_appdata_seeded": baseline["retail_appdata_seeded"],
                    "files": baseline["files"],
                },
            )

    def _write_capture(
        self, root: Path, name: str, value: dict[str, object]
    ) -> Path:
        directory = root / "raw" / name
        directory.mkdir(parents=True)
        Image.new("RGB", (4, 4), (10, 20, 30)).save(
            directory / "frame.bmp", format="BMP"
        )
        path = directory / "capture.json"
        _write_json(path, value)
        return path

    def test_imports_two_independent_pairs_with_machine_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._initialize_repo(root)
            self._stage_binaries(root, ("menufx-test-a", "menufx-test-b"))
            _write_json(
                root / "tests" / "fixtures" / "webgame" / "menu-overlay-reference.json",
                {
                    "schema": "solomon-dark-native-menu-overlay-reference-v3",
                    "overlay_semantic_draw_multiset": [
                        {
                            "count": 1,
                            "payload": {
                                "kind": "art",
                                "text": "",
                                "action_id": "",
                                "art_id": "UI.NotPresent",
                                "font_id": "",
                                "text_style": "sprite",
                                "visible": True,
                                "interactive": False,
                                "rect": [1.0, 1.0, 2.0, 2.0],
                                "unclipped_rect": [1.0, 1.0, 2.0, 2.0],
                            },
                        }
                    ],
                },
            )
            loader_primary = self._write_capture(
                root, "loader-primary", _loader_recording("menufx-test-a", 101)
            )
            loader_confirmation = self._write_capture(
                root,
                "loader-confirmation",
                _loader_recording("menufx-test-b", 102),
            )
            loading_primary = self._write_capture(
                root, "loading-primary", _loading_recording("menufx-test-a", 201)
            )
            loading_confirmation = self._write_capture(
                root,
                "loading-confirmation",
                _loading_recording("menufx-test-b", 202),
            )
            output = root / "candidate"

            result = import_all(
                argparse.Namespace(
                    repo_root=root,
                    loader_primary=loader_primary,
                    loader_confirmation=loader_confirmation,
                    loading_primary=loading_primary,
                    loading_confirmation=loading_confirmation,
                    output_root=output,
                )
            )

            self.assertTrue(result["success"])
            self.assertEqual(result["paired_surface_count"], 2)
            commit = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            for stem in ("native-loader", "loading-screen"):
                fixture_path = output / "menu-layouts" / f"{stem}.json"
                confirmation_path = (
                    output
                    / "menu-animation-confirmations"
                    / f"{stem}.confirmation.json"
                )
                fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
                confirmation = json.loads(
                    confirmation_path.read_text(encoding="utf-8")
                )
                self.assertEqual(fixture["header"]["source"]["base_commit_sha"], commit)
                self.assertEqual(
                    fixture["header"]["settlement"]["settlement_spec"], "2.9"
                )
                self.assertNotEqual(
                    fixture["header"]["instance"],
                    confirmation["header"]["instance"],
                )
                self.assertEqual(
                    fixture["header"]["animation_confirmation"]["sha256"],
                    _sha256(confirmation_path),
                )
                self.assertEqual(len(confirmation["settled_window_samples"]), 40)
                self.assertTrue(
                    (output / "menu-reference-captures" / f"{stem}.png").is_file()
                )

    def test_special_pair_rejects_same_instance(self) -> None:
        from tools.import_native_menu_special_captures_v25 import (
            SpecialImportError,
            assert_independent_pair,
        )

        header = {
            "instance": "menufx-same",
            "process_id": 1,
            "source": {"base_commit_sha": "a" * 40},
        }
        confirmation = copy.deepcopy(header)
        confirmation["process_id"] = 2
        with self.assertRaisesRegex(
            SpecialImportError, "did not use a different fresh instance"
        ):
            assert_independent_pair(header, confirmation, "native_loader")


if __name__ == "__main__":
    unittest.main()
