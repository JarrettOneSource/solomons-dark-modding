#!/usr/bin/env python3
"""Verify the portable Solomon Dark multiplayer beta ZIP."""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
VERSION_PROPS = ROOT / "Directory.Build.props"
PROTOCOL_HEADER = ROOT / "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h"
DEFAULT_OUTPUT = ROOT / "runtime/beta_release_artifact.json"
PACKAGE_PREFIX = "SolomonDarkMultiplayerBeta-v"
EXPECTED_PRODUCT = "Solomon Dark Multiplayer Beta"
EXPECTED_GAME_VERSION = "0.72.5"
EXPECTED_STEAM_APP_ID = 3362180
PE_I386 = 0x014C
PE_AMD64 = 0x8664


class ArtifactFailure(RuntimeError):
    pass


def read_match(path: Path, pattern: str, description: str) -> str:
    match = re.search(pattern, path.read_text(encoding="utf-8"), re.MULTILINE)
    if match is None:
        raise ArtifactFailure(f"could not read {description} from {path}")
    return match.group(1)


def declared_version() -> str:
    return read_match(VERSION_PROPS, r"<Version>([^<]+)</Version>", "version")


def expected_protocol_version() -> int:
    return int(
        read_match(
            PROTOCOL_HEADER,
            r"kProtocolVersion\s*=\s*(\d+)",
            "protocol version",
        )
    )


def pe_machine_zip_member(
    archive: zipfile.ZipFile,
    member: zipfile.ZipInfo,
    label: str,
) -> int:
    with archive.open(member) as handle:
        dos_header = handle.read(0x40)
        if len(dos_header) < 0x40 or dos_header[:2] != b"MZ":
            raise ArtifactFailure(f"{label} is not a PE image")
        pe_offset = struct.unpack_from("<I", dos_header, 0x3C)[0]
        if pe_offset + 6 > member.file_size:
            raise ArtifactFailure(f"{label} has an invalid PE header")
        handle.seek(pe_offset)
        pe_header = handle.read(6)
        if len(pe_header) != 6 or pe_header[:4] != b"PE\0\0":
            raise ArtifactFailure(f"{label} has an invalid PE header")
        return struct.unpack_from("<H", pe_header, 4)[0]


def validate_archive(archive_path: Path, version: str) -> dict[str, Any]:
    if not archive_path.is_file():
        raise ArtifactFailure(f"beta archive does not exist: {archive_path}")

    release_name = f"{PACKAGE_PREFIX}{version}"
    root_prefix = f"{release_name}/"
    required_files = {
        "SolomonDarkMultiplayerBeta.exe",
        "README.txt",
        "THIRD-PARTY-NOTICES.txt",
        ".distribution-files.json",
        "solomon-dark-multiplayer.json",
        "SolomonDarkLauncherUpdater.exe",
        "launcher/SolomonDarkModLauncher.exe",
        "launcher/SolomonDarkModLoader.dll",
        "launcher/assets/steam/README.txt",
        "launcher/assets/steam/win32/steam_api.dll",
        "config/binary-layout.ini",
        "config/debug-ui.ini",
    }
    forbidden_extensions = {
        ".pdb",
        ".ilk",
        ".lib",
        ".exp",
        ".log",
        ".dmp",
        ".tmp",
        ".bak",
    }
    forbidden_directory_names = {
        ".git",
        ".pytest_cache",
        ".vs",
        "__pycache__",
        "runtime",
    }
    forbidden_names = {
        "solomondark.exe",
        "sb.exe",
        "info.dat",
        "loginusers.vdf",
        "ssfn",
    }

    with zipfile.ZipFile(archive_path) as archive:
        bad_zip_member = archive.testzip()
        if bad_zip_member is not None:
            raise ArtifactFailure(f"ZIP CRC check failed for {bad_zip_member}")

        file_members: dict[str, zipfile.ZipInfo] = {}
        file_members_casefolded: set[str] = set()
        for info in archive.infolist():
            normalized = info.filename.replace("\\", "/")
            pure_path = PurePosixPath(normalized)
            if pure_path.is_absolute() or ".." in pure_path.parts:
                raise ArtifactFailure(f"unsafe ZIP path: {info.filename}")
            if not normalized.startswith(root_prefix):
                raise ArtifactFailure(
                    f"ZIP member is outside the expected root {release_name}: {info.filename}"
                )
            if info.is_dir() or normalized.endswith("/"):
                continue
            relative = normalized[len(root_prefix) :]
            if not relative:
                raise ArtifactFailure(f"invalid empty ZIP member: {info.filename}")
            if relative in file_members:
                raise ArtifactFailure(f"duplicate ZIP member: {relative}")
            if relative.casefold() in file_members_casefolded:
                raise ArtifactFailure(
                    f"case-colliding ZIP member: {relative}"
                )
            file_members[relative] = info
            file_members_casefolded.add(relative.casefold())

        missing = sorted(required_files - file_members.keys())
        if missing:
            raise ArtifactFailure(f"archive is missing required files: {missing}")

        forbidden: list[str] = []
        for relative in file_members:
            path = PurePosixPath(relative)
            lower_name = path.name.lower()
            lower_parts = {part.lower() for part in path.parts}
            if path.suffix.lower() in forbidden_extensions:
                forbidden.append(relative)
            elif path.parts[0].casefold() == "mods":
                forbidden.append(relative)
            elif lower_name in forbidden_names or lower_name.startswith("ssfn"):
                forbidden.append(relative)
            elif forbidden_directory_names & lower_parts:
                forbidden.append(relative)
        if forbidden:
            raise ArtifactFailure(
                f"archive contains forbidden build/game/account artifacts: {sorted(forbidden)}"
            )

        marker = json.loads(
            archive.read(file_members["solomon-dark-multiplayer.json"]).decode(
                "utf-8-sig"
            )
        )
        expected_marker = {
            "schemaVersion": 2,
            "product": EXPECTED_PRODUCT,
            "version": version,
            "protocolVersion": expected_protocol_version(),
            "supportedGameVersion": EXPECTED_GAME_VERSION,
            "steamAppId": EXPECTED_STEAM_APP_ID,
            "defaultEnabledMods": [],
        }
        marker_mismatches = {
            key: {"actual": marker.get(key), "expected": expected}
            for key, expected in expected_marker.items()
            if marker.get(key) != expected
        }
        if marker_mismatches:
            raise ArtifactFailure(
                f"portable marker mismatches: {marker_mismatches}"
            )

        distribution_manifest = json.loads(
            archive.read(file_members[".distribution-files.json"]).decode(
                "utf-8-sig"
            )
        )
        distribution_files = distribution_manifest.get("files")
        if (
            distribution_manifest.get("schemaVersion") != 1
            or not isinstance(distribution_files, list)
            or not all(isinstance(path, str) for path in distribution_files)
            or len({path.casefold() for path in distribution_files})
            != len(distribution_files)
        ):
            raise ArtifactFailure("distribution file manifest is invalid")
        if set(distribution_files) != set(file_members):
            missing_files = sorted(set(file_members) - set(distribution_files))
            extra_files = sorted(set(distribution_files) - set(file_members))
            raise ArtifactFailure(
                "distribution file coverage mismatch: "
                f"missing={missing_files} extra={extra_files}"
            )

        binary_machines = {
            "SolomonDarkMultiplayerBeta.exe": PE_AMD64,
            "SolomonDarkLauncherUpdater.exe": PE_AMD64,
            "launcher/SolomonDarkModLauncher.exe": PE_I386,
            "launcher/SolomonDarkModLoader.dll": PE_I386,
            "launcher/assets/steam/win32/steam_api.dll": PE_I386,
        }
        actual_machines: dict[str, str] = {}
        for relative, expected_machine in binary_machines.items():
            machine = pe_machine_zip_member(
                archive,
                file_members[relative],
                relative,
            )
            actual_machines[relative] = f"0x{machine:04x}"
            if machine != expected_machine:
                raise ArtifactFailure(
                    f"{relative} machine is 0x{machine:04x}, expected 0x{expected_machine:04x}"
                )

        readme = archive.read(file_members["README.txt"]).decode("utf-8-sig")
        for required_text in (
            version,
            "HOW TO PLAY",
            "Host Game",
            "Choose Save",
            "Cloud backups are disabled until the Steam account is linked.",
            "Select the host's lobby through Steam",
            "Lobby ID",
            "Multiplayer supports 2-250 players; new lobbies default to four.",
            "The launcher does not store or package Steam credentials.",
        ):
            if required_text not in readme:
                raise ArtifactFailure(f"README.txt is missing: {required_text}")
        for removed_text in (
            "Join Friend FIRST",
            "Host & Invite Friends",
            "SHA-256",
            "Rush",
            "maximum of four players",
        ):
            if removed_text in readme:
                raise ArtifactFailure(
                    f"README.txt still contains removed text: {removed_text}"
                )

        return {
            "ok": True,
            "version": version,
            "release_name": release_name,
            "archive": str(archive_path.resolve()),
            "archive_size": archive_path.stat().st_size,
            "file_count": len(file_members),
            "distribution_files_verified": len(distribution_files),
            "binary_machines": actual_machines,
            "marker": marker,
            "forbidden_artifacts": [],
        }

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", nargs="?", type=Path)
    parser.add_argument("--version", default=declared_version())
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    archive_path = args.archive or (
        ROOT / "artifacts" / f"{PACKAGE_PREFIX}{args.version}.zip"
    )
    result: dict[str, Any] = {"ok": False}
    return_code = 1
    try:
        result = validate_archive(archive_path, args.version)
        return_code = 0
    except (ArtifactFailure, OSError, ValueError, zipfile.BadZipFile) as exc:
        result["error"] = str(exc)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return return_code


if __name__ == "__main__":
    sys.exit(main())
