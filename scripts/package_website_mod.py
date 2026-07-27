#!/usr/bin/env python3
"""Build a deterministic Solomon Dark website mod package."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import zipfile
from pathlib import Path


SEMVER = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("mod_root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--version",
        help="Override manifest.version in the package without changing the source manifest.",
    )
    parser.add_argument("--metadata-output", type=Path)
    return parser.parse_args()


def load_entries(mod_root: Path, version: str | None) -> dict[str, bytes]:
    root = mod_root.resolve(strict=True)
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"missing manifest.json: {manifest_path}")

    entries: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ValueError(f"package links are not allowed: {relative}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError(f"unsupported package entry: {relative}")
        if "\\" in relative or any(part in ("", ".", "..") for part in relative.split("/")):
            raise ValueError(f"unsafe package path: {relative}")
        entries[relative] = path.read_bytes()

    manifest = json.loads(entries["manifest.json"])
    if not isinstance(manifest, dict):
        raise ValueError("manifest.json must contain an object")
    package_version = version if version is not None else manifest.get("version")
    if not isinstance(package_version, str) or not SEMVER.fullmatch(package_version):
        raise ValueError("manifest.version must use semantic versioning")
    minimum = manifest.get("minimumLoaderVersion")
    if minimum is not None and (
        not isinstance(minimum, str) or not SEMVER.fullmatch(minimum)
    ):
        raise ValueError("manifest.minimumLoaderVersion must use semantic versioning")
    if version is not None:
        manifest["version"] = version
        entries["manifest.json"] = (
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
        ).encode()
    return entries


def content_sha256(entries: dict[str, bytes]) -> str:
    aggregate = hashlib.sha256()
    for path, content in sorted(entries.items()):
        digest = hashlib.sha256(content).hexdigest()
        aggregate.update(f"{path}\0{digest}\n".encode())
    return aggregate.hexdigest()


def write_package(output: Path, entries: dict[str, bytes]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        output,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path, content in sorted(entries.items()):
            info = zipfile.ZipInfo(path, ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def main() -> int:
    args = parse_args()
    entries = load_entries(args.mod_root, args.version)
    manifest = json.loads(entries["manifest.json"])
    write_package(args.output, entries)
    result = {
        "id": manifest["id"],
        "name": manifest["name"],
        "version": manifest["version"],
        "minimumLoaderVersion": manifest.get("minimumLoaderVersion"),
        "packagePath": str(args.output.resolve()),
        "packageBytes": args.output.stat().st_size,
        "packageSha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        "contentSha256": content_sha256(entries),
        "files": [
            {
                "path": path,
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
            for path, content in sorted(entries.items())
        ],
    }
    rendered = json.dumps(result, indent=2) + "\n"
    if args.metadata_output is not None:
        args.metadata_output.parent.mkdir(parents=True, exist_ok=True)
        args.metadata_output.write_text(rendered)
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
