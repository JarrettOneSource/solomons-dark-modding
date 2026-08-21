from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGER = ROOT / "scripts" / "package_website_mod.py"


class WebsiteModPackagerTests(unittest.TestCase):
    def test_lua_bots_publication_metadata_matches_current_package(self) -> None:
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
        self.assertEqual(listing["author"], "Generic")
        self.assertEqual(submission["expectedAuthor"], "Generic")
        listing_fields = submission["listing"]["fields"]
        version_fields = submission["version"]["fields"]
        self.assertEqual(listing_fields["name"], listing["name"])
        self.assertEqual(
            listing_fields["summary"],
            listing["tagline"],
        )
        self.assertEqual(
            listing_fields["description"],
            listing["description"],
        )
        self.assertTrue(
            listing["description"].endswith(
                "Requires v0.1.0-beta.29 or newer."
            )
        )
        self.assertEqual(version_fields["version"], "1.2.0")
        self.assertEqual(version_fields["changelog"], listing["changelog"])
        self.assertEqual(listing["manifestId"], manifest["id"])
        self.assertEqual(
            listing["minimumLoaderVersion"],
            "0.1.0-beta.29",
        )
        self.assertEqual(manifest["version"], "1.2.0")
        self.assertEqual(
            manifest["minimumLoaderVersion"],
            "0.1.0-beta.29",
        )
        self.assertNotIn("summary", manifest)
        self.assertNotIn("description", manifest)
        self.assertEqual(listing["screenshots"], [])
        for phrase in (
            "F9",
            "random offered skills",
            "10 percent",
            "80 percent",
            "extra ally row",
        ):
            self.assertIn(phrase, listing["changelog"])

    def test_invincibility_publication_metadata_is_player_facing(self) -> None:
        listing = json.loads(
            (
                ROOT
                / "docs"
                / "publication"
                / "invincibility-potion-listing.json"
            ).read_text(encoding="utf-8")
        )
        submission = json.loads(
            (
                ROOT
                / "docs"
                / "publication"
                / "invincibility-potion-submission.json"
            ).read_text(encoding="utf-8")
        )
        manifest = json.loads(
            (
                ROOT
                / "mods"
                / "lua_invincibility_potion_canary"
                / "manifest.json"
            ).read_text(encoding="utf-8")
        )
        create = submission["migration"]["create"]
        self.assertEqual(listing["author"], "Generic")
        self.assertEqual(submission["expectedAuthor"], "Generic")
        self.assertEqual(create["fields"]["name"], listing["name"])
        self.assertEqual(create["fields"]["summary"], listing["tagline"])
        self.assertEqual(
            create["fields"]["description"],
            listing["description"],
        )
        self.assertEqual(create["fields"]["version"], manifest["version"])
        self.assertEqual(listing["manifestId"], manifest["id"])
        self.assertEqual(
            listing["minimumLoaderVersion"],
            manifest["minimumLoaderVersion"],
        )
        self.assertEqual(submission["changelog"], listing["changelog"])
        self.assertNotIn("canary", listing["name"].lower())
        self.assertNotIn("canary", listing["description"].lower())
        self.assertNotIn("test", listing["description"].lower())

    def test_lua_bots_package_is_deterministic_and_hashes_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "first.zip"
            second = Path(temporary) / "second.zip"
            metadata = Path(temporary) / "metadata.json"
            for output in (first, second):
                result = subprocess.run(
                    [
                        sys.executable,
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
            self.assertEqual(details["version"], "1.2.0")
            self.assertEqual(
                details["minimumLoaderVersion"],
                "0.1.0-beta.29",
            )
            self.assertEqual(
                details["packageSha256"],
                hashlib.sha256(second.read_bytes()).hexdigest(),
            )
            submission = json.loads(
                (
                    ROOT
                    / "docs"
                    / "publication"
                    / "lua-bots-submission.json"
                ).read_text(encoding="utf-8")
            )
            files = submission["version"]["files"]
            self.assertEqual(files["packageSha256"], details["packageSha256"])
            self.assertEqual(files["contentSha256"], details["contentSha256"])

            aggregate = hashlib.sha256()
            with zipfile.ZipFile(second) as archive:
                self.assertEqual(
                    archive.namelist(),
                    sorted(archive.namelist()),
                )
                for required in (
                    "scripts/local_player.lua",
                    "scripts/policy.lua",
                    "scripts/policy_observation.lua",
                    "scripts/policy_spec.lua",
                    "scripts/policy_training.lua",
                    "scripts/policy_weights.lua",
                ):
                    self.assertIn(required, archive.namelist())
                self.assertFalse(
                    any(name.endswith(".py") for name in archive.namelist())
                )
                for name in archive.namelist():
                    content = archive.read(name)
                    aggregate.update(
                        f"{name}\0{hashlib.sha256(content).hexdigest()}\n".encode()
                    )
            self.assertEqual(details["contentSha256"], aggregate.hexdigest())

    def test_invincibility_potion_package_contains_custom_world_sprite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "invincibility-potion.zip"
            result = subprocess.run(
                [
                    sys.executable,
                    str(PACKAGER),
                    str(ROOT / "mods" / "lua_invincibility_potion_canary"),
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            details = json.loads(result.stdout)
            self.assertEqual(details["id"], "canary.lua.invincibility_potion")
            self.assertEqual(details["name"], "Invincibility Potion")
            self.assertEqual(details["version"], "0.3.0")
            self.assertEqual(
                details["minimumLoaderVersion"],
                "0.1.0-beta.29",
            )
            submission = json.loads(
                (
                    ROOT
                    / "docs"
                    / "publication"
                    / "invincibility-potion-submission.json"
                ).read_text(encoding="utf-8")
            )
            files = submission["migration"]["create"]["files"]
            self.assertEqual(files["packageSha256"], details["packageSha256"])
            self.assertEqual(files["contentSha256"], details["contentSha256"])
            with zipfile.ZipFile(output) as archive:
                names = archive.namelist()
                self.assertIn("sprites/invincibility_potion.png", names)
                self.assertIn("sprites/invincibility_potion.bundle", names)
                self.assertIn("sprites/invincibility_potion.json", names)
                manifest = json.loads(archive.read("manifest.json"))
            self.assertNotIn("author", manifest)

    def test_unknown_manifest_field_fails_before_package_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "mod"
            script = root / "scripts" / "main.lua"
            script.parent.mkdir(parents=True)
            script.write_text("print('test')\n", encoding="utf-8")
            manifest = {
                "id": "sample.strict-contract",
                "name": "Strict Contract",
                "version": "1.0.0",
                "summary": "Listing copy does not belong here.",
                "runtime": {
                    "apiVersion": "0.2.0",
                    "entryScript": "scripts/main.lua",
                    "requiredCapabilities": [],
                },
            }
            (root / "manifest.json").write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )
            output = Path(temporary) / "rejected.zip"
            result = subprocess.run(
                [sys.executable, str(PACKAGER), str(root), str(output)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "fields that are not part of the website package contract: "
                "summary",
                result.stderr,
            )
            self.assertFalse(output.exists())

    def test_version_override_does_not_mutate_source(self) -> None:
        source_manifest = ROOT / "mods" / "bot-brain" / "manifest.json"
        before = source_manifest.read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "update.zip"
            result = subprocess.run(
                [
                    sys.executable,
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
