from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGER = ROOT / "scripts" / "package_website_mod.py"


class WebsiteModPackagerTests(unittest.TestCase):
    def test_submission_matches_listing_and_manifest(self) -> None:
        listing = json.loads(
            (
                ROOT
                / "docs"
                / "publication"
                / "lua-bots-listing.json"
            ).read_text(encoding="utf-8")
        )
        submission = json.loads(
            (
                ROOT
                / "docs"
                / "publication"
                / "lua-bots-submission.json"
            ).read_text(encoding="utf-8")
        )
        manifest = json.loads(
            (
                ROOT
                / "mods"
                / "bot-brain"
                / "manifest.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(submission["fields"]["name"], listing["name"])
        self.assertEqual(
            submission["fields"]["summary"],
            listing["tagline"],
        )
        self.assertEqual(
            submission["fields"]["description"],
            listing["description"],
        )
        self.assertTrue(
            listing["description"].endswith(
                "Requires v0.1.0-beta.21 or newer."
            )
        )
        self.assertEqual(
            submission["fields"]["version"],
            manifest["version"],
        )
        self.assertEqual(listing["manifestId"], manifest["id"])
        self.assertEqual(
            listing["minimumLoaderVersion"],
            manifest["minimumLoaderVersion"],
        )
        self.assertEqual(
            manifest["minimumLoaderVersion"],
            "0.1.0-beta.21",
        )
        self.assertEqual(listing["screenshots"], [])
        self.assertEqual(submission["files"]["screenshots"], [])

    def test_lua_bots_package_is_deterministic_and_hashes_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "first.zip"
            second = Path(temporary) / "second.zip"
            metadata = Path(temporary) / "metadata.json"
            for output in (first, second):
                result = subprocess.run(
                    [
                        "python3",
                        str(PACKAGER),
                        str(ROOT / "mods" / "bot-brain"),
                        str(output),
                        "--metadata-output",
                        str(metadata),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

            self.assertEqual(first.read_bytes(), second.read_bytes())
            details = json.loads(metadata.read_text())
            self.assertEqual(details["id"], "bot.brain")
            self.assertEqual(details["version"], "1.0.0")
            self.assertEqual(
                details["minimumLoaderVersion"],
                "0.1.0-beta.21",
            )
            self.assertEqual(
                details["packageSha256"],
                hashlib.sha256(second.read_bytes()).hexdigest(),
            )

            aggregate = hashlib.sha256()
            with zipfile.ZipFile(second) as archive:
                self.assertEqual(
                    archive.namelist(),
                    sorted(archive.namelist()),
                )
                for name in archive.namelist():
                    content = archive.read(name)
                    aggregate.update(
                        f"{name}\0{hashlib.sha256(content).hexdigest()}\n".encode()
                    )
            self.assertEqual(details["contentSha256"], aggregate.hexdigest())

    def test_version_override_does_not_mutate_source(self) -> None:
        source_manifest = ROOT / "mods" / "bot-brain" / "manifest.json"
        before = source_manifest.read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "update.zip"
            result = subprocess.run(
                [
                    "python3",
                    str(PACKAGER),
                    str(source_manifest.parent),
                    str(output),
                    "--version",
                    "1.0.1",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            with zipfile.ZipFile(output) as archive:
                packaged = json.loads(archive.read("manifest.json"))
            self.assertEqual(packaged["version"], "1.0.1")
        self.assertEqual(source_manifest.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
