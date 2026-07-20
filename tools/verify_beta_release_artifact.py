#!/usr/bin/env python3
"""Verify the portable Solomon Dark multiplayer beta ZIP and its checksums."""

from __future__ import annotations

import argparse
import hashlib
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
GAME_INSTALLATION = ROOT / "SolomonDarkModLauncher/src/Target/GameInstallation.cs"
DEFAULT_OUTPUT = ROOT / "runtime/beta_release_artifact.json"
PACKAGE_PREFIX = "SolomonDarkMultiplayerBeta-v"
EXPECTED_PRODUCT = "Solomon Dark Multiplayer Beta"
EXPECTED_GAME_VERSION = "0.72.5"
EXPECTED_STEAM_APP_ID = 480
PE_I386 = 0x014C
PE_AMD64 = 0x8664


class ArtifactFailure(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def expected_game_hash() -> str:
    return read_match(
        GAME_INSTALLATION,
        r'SupportedExecutableSha256\s*=\s*\n?\s*"([0-9a-fA-F]{64})"',
        "supported game hash",
    ).lower()


def pe_machine(data: bytes, label: str) -> int:
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise ArtifactFailure(f"{label} is not a PE image")
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    if pe_offset + 6 > len(data) or data[pe_offset : pe_offset + 4] != b"PE\0\0":
        raise ArtifactFailure(f"{label} has an invalid PE header")
    return struct.unpack_from("<H", data, pe_offset + 4)[0]


def parse_checksum_manifest(data: bytes) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        data.decode("utf-8-sig").splitlines(), start=1
    ):
        if not raw_line.strip():
            continue
        match = re.fullmatch(r"([0-9a-f]{64})  ([^\r\n]+)", raw_line)
        if match is None:
            raise ArtifactFailure(
                f"checksums.txt line {line_number} has invalid syntax"
            )
        digest, relative_path = match.groups()
        if relative_path in checksums:
            raise ArtifactFailure(f"checksums.txt repeats {relative_path}")
        checksums[relative_path] = digest
    return checksums


def validate_archive(archive_path: Path, version: str) -> dict[str, Any]:
    if not archive_path.is_file():
        raise ArtifactFailure(f"beta archive does not exist: {archive_path}")

    release_name = f"{PACKAGE_PREFIX}{version}"
    root_prefix = f"{release_name}/"
    required_files = {
        "SolomonDarkMultiplayerBeta.exe",
        "README.txt",
        "THIRD-PARTY-NOTICES.txt",
        "solomon-dark-multiplayer.json",
        "checksums.txt",
        "launcher/SolomonDarkModLauncher.exe",
        "launcher/SolomonDarkModLoader.dll",
        "launcher/assets/steam/README.txt",
        "launcher/assets/steam/win32/steam_api.dll",
        "config/binary-layout.ini",
        "config/debug-ui.ini",
        "mods/README.md",
    }
    forbidden_extensions = {".pdb", ".ilk", ".lib", ".exp"}
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
            file_members[relative] = info

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
            elif lower_name in forbidden_names or lower_name.startswith("ssfn"):
                forbidden.append(relative)
            elif ".git" in lower_parts or "runtime" in lower_parts:
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
            "schemaVersion": 1,
            "product": EXPECTED_PRODUCT,
            "version": version,
            "protocolVersion": expected_protocol_version(),
            "supportedGameVersion": EXPECTED_GAME_VERSION,
            "supportedExecutableSha256": expected_game_hash(),
            "steamDevelopmentAppId": EXPECTED_STEAM_APP_ID,
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

        manifest = parse_checksum_manifest(
            archive.read(file_members["checksums.txt"])
        )
        expected_manifest_paths = set(file_members) - {"checksums.txt"}
        if set(manifest) != expected_manifest_paths:
            missing_checksums = sorted(expected_manifest_paths - set(manifest))
            extra_checksums = sorted(set(manifest) - expected_manifest_paths)
            raise ArtifactFailure(
                "content checksum coverage mismatch: "
                f"missing={missing_checksums} extra={extra_checksums}"
            )

        checksum_mismatches: list[str] = []
        for relative, expected_digest in manifest.items():
            actual_digest = sha256_bytes(archive.read(file_members[relative]))
            if actual_digest != expected_digest:
                checksum_mismatches.append(relative)
        if checksum_mismatches:
            raise ArtifactFailure(
                f"content checksum mismatches: {sorted(checksum_mismatches)}"
            )

        binary_machines = {
            "SolomonDarkMultiplayerBeta.exe": PE_AMD64,
            "launcher/SolomonDarkModLauncher.exe": PE_I386,
            "launcher/SolomonDarkModLoader.dll": PE_I386,
            "launcher/assets/steam/win32/steam_api.dll": PE_I386,
        }
        actual_machines: dict[str, str] = {}
        for relative, expected_machine in binary_machines.items():
            machine = pe_machine(archive.read(file_members[relative]), relative)
            actual_machines[relative] = f"0x{machine:04x}"
            if machine != expected_machine:
                raise ArtifactFailure(
                    f"{relative} machine is 0x{machine:04x}, expected 0x{expected_machine:04x}"
                )

        steam_api_digest = sha256_bytes(
            archive.read(file_members["launcher/assets/steam/win32/steam_api.dll"])
        )
        if marker.get("steamApiSha256") != steam_api_digest:
            raise ArtifactFailure(
                "portable marker Steam API digest does not match the bundled DLL"
            )

        readme = archive.read(file_members["README.txt"]).decode("utf-8-sig")
        for required_text in (
            version,
            "HOW TO PLAY",
            "Host Game",
            "Select the host's lobby through Steam",
            "Lobby ID",
            "The launcher does not store or package Steam credentials.",
        ):
            if required_text not in readme:
                raise ArtifactFailure(f"README.txt is missing: {required_text}")
        for removed_text in (
            "Join Friend FIRST",
            "Host & Invite Friends",
            expected_game_hash(),
            "SHA-256",
            "Rush",
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
            "archive_sha256": sha256_file(archive_path),
            "archive_size": archive_path.stat().st_size,
            "file_count": len(file_members),
            "content_checksums_verified": len(manifest),
            "binary_machines": actual_machines,
            "marker": marker,
            "forbidden_artifacts": [],
        }


def validate_outer_checksum(archive_path: Path, result: dict[str, Any]) -> None:
    checksum_path = archive_path.parent / "SHA256SUMS.txt"
    if not checksum_path.is_file():
        raise ArtifactFailure(f"release checksum file is missing: {checksum_path}")
    expected_line = f"{result['archive_sha256']}  {archive_path.name}"
    lines = [line.strip() for line in checksum_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if expected_line not in lines:
        raise ArtifactFailure(
            f"SHA256SUMS.txt does not contain the archive digest: {expected_line}"
        )
    result["outer_checksum"] = str(checksum_path.resolve())


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
        validate_outer_checksum(archive_path, result)
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
