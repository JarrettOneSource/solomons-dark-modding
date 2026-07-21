#!/usr/bin/env python3
"""Build a deterministic catalog of Solomon Dark's native audio assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


AUDIO_REGISTRY_PREFIX = "AUDIO_REGISTRY\t"
AUDIO_BLOCK_MYAPP_OFFSET = 0x319EC8
AUDIO_BLOCK_SIZE = 0x26FC
SUPPORTED_SAMPLE_EXTENSIONS = (".ogg", ".caf", ".wav", ".mp3")

LOADER_CLASSES = {
    "0x004076d0": {"class": "Sound", "object_size": 0x2C},
    "0x00408220": {"class": "SoundLoop", "object_size": 0x60},
    "0x0040acf0": {"class": "SoundStream", "object_size": 0x08},
}

EXPECTED_SEGMENTS = (
    (0, 110, "Sound", 0x0018, 0x2C, "fixed_one_shots"),
    (111, 150, "SoundStream", 0x132C, 0x08, "fixed_streams"),
    (151, 172, "SoundLoop", 0x146C, 0x60, "fixed_loops"),
    (173, 232, "Sound", 0x1CAC, 0x2C, "grouped_variants"),
)

REGISTRY_ROW_RE = re.compile(
    r"^AUDIO_REGISTRY\t"
    r"(?P<index>\d+)\t"
    r"(?P<literal_ref>[0-9A-Fa-f]+)\t"
    r"(?P<literal_address>[0-9A-Fa-f]+)\t"
    r"(?P<load_call>[0-9A-Fa-f]+)\t"
    r"(?P<loader>0x[0-9A-Fa-f]+)\t"
    r"\[ESI \+ 0x(?P<offset>[0-9A-Fa-f]+)\]\t"
    r"(?P<path>sounds\\.+)$"
)

DIALOGUE_KEY_RE = re.compile(r"^\s*(?P<key>[A-Za-z0-9_.-]+)\s*=")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-root", type=Path, required=True)
    parser.add_argument("--registry-log", type=Path, required=True)
    parser.add_argument("--source-label", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def hex_address(value: int) -> str:
    return f"0x{value:08X}"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_metadata(path: Path, game_root: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {
        "path": path.relative_to(game_root).as_posix(),
        "size": len(data),
        "sha256": sha256_bytes(data),
    }


def parse_registry(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.startswith(AUDIO_REGISTRY_PREFIX):
            continue
        match = REGISTRY_ROW_RE.fullmatch(line.rstrip("\r"))
        if match is None:
            raise ValueError(f"malformed audio-registry row: {line!r}")
        loader = match.group("loader").lower()
        if loader not in LOADER_CLASSES:
            raise ValueError(f"unknown native audio loader: {loader}")
        relative_offset = int(match.group("offset"), 16)
        path_without_extension = match.group("path")
        parts = path_without_extension.split("\\")
        category = parts[1] if len(parts) > 2 else "root"
        rows.append(
            {
                "registry_index": int(match.group("index"), 10),
                "literal_reference": hex_address(int(match.group("literal_ref"), 16)),
                "literal_address": hex_address(int(match.group("literal_address"), 16)),
                "load_call": hex_address(int(match.group("load_call"), 16)),
                "loader": hex_address(int(loader, 16)),
                "native_class": LOADER_CLASSES[loader]["class"],
                "native_object_size": LOADER_CLASSES[loader]["object_size"],
                "registry_member_offset": hex_address(relative_offset),
                "myapp_member_offset": hex_address(AUDIO_BLOCK_MYAPP_OFFSET + relative_offset),
                "path_without_extension": path_without_extension,
                "category": category,
            }
        )
    return rows


def validate_registry_layout(rows: list[dict[str, Any]]) -> None:
    if len(rows) != 233:
        raise ValueError(f"expected 233 native registry rows, found {len(rows)}")
    if [row["registry_index"] for row in rows] != list(range(233)):
        raise ValueError("native audio registry indexes are not contiguous 0..232")

    for first, last, class_name, start, stride, segment in EXPECTED_SEGMENTS:
        for index in range(first, last + 1):
            row = rows[index]
            expected_offset = start + (index - first) * stride
            if row["native_class"] != class_name:
                raise ValueError(
                    f"registry index {index} is {row['native_class']}, expected {class_name}"
                )
            if int(row["registry_member_offset"], 16) != expected_offset:
                raise ValueError(
                    f"registry index {index} has offset {row['registry_member_offset']}, "
                    f"expected {hex_address(expected_offset)}"
                )
            row["registry_segment"] = segment


def casefold_file_map(game_root: Path) -> dict[str, list[Path]]:
    result: dict[str, list[Path]] = defaultdict(list)
    for path in game_root.rglob("*"):
        if path.is_file():
            key = path.relative_to(game_root).as_posix().casefold()
            result[key].append(path)
    return result


def bind_registry_files(
    rows: list[dict[str, Any]], game_root: Path, files: dict[str, list[Path]]
) -> None:
    for row in rows:
        base = row["path_without_extension"].replace("\\", "/")
        candidates: list[Path] = []
        for extension in SUPPORTED_SAMPLE_EXTENSIONS:
            candidates.extend(files.get((base + extension).casefold(), []))
        if len(candidates) != 1:
            raise ValueError(
                f"{row['path_without_extension']}: expected one installed audio file, "
                f"found {[path.as_posix() for path in candidates]}"
            )
        metadata = file_metadata(candidates[0], game_root)
        row["file"] = metadata
        row["resolved_extension"] = candidates[0].suffix.lower()


def dialogue_references(game_root: Path) -> dict[str, list[dict[str, Any]]]:
    references: dict[str, list[dict[str, Any]]] = defaultdict(list)
    dialogue_root = game_root / "data" / "dialogue"
    for path in sorted(dialogue_root.rglob("*.txt")):
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        for line_number, line in enumerate(text.splitlines(), 1):
            match = DIALOGUE_KEY_RE.match(line)
            if match is None:
                continue
            key = match.group("key")
            references[key.casefold()].append(
                {
                    "key": key,
                    "path": path.relative_to(game_root).as_posix(),
                    "line": line_number,
                }
            )
    return references


def build_voice_catalog(game_root: Path) -> list[dict[str, Any]]:
    references = dialogue_references(game_root)
    entries = []
    for path in sorted((game_root / "voices").glob("*.wav"), key=lambda item: item.name.casefold()):
        voice_id = path.stem
        entries.append(
            {
                "voice_id": voice_id,
                "native_path_format": "voices\\%s.wav",
                "definition_references": references.get(voice_id.casefold(), []),
                "file": file_metadata(path, game_root),
            }
        )
    return entries


def parse_music_table(text: str) -> list[dict[str, Any]]:
    songs: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line_number, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("//"):
            continue
        if line.casefold().startswith("song="):
            value = line.split("=", 1)[1]
            if ":" not in value:
                raise ValueError(f"music table line {line_number}: malformed song")
            name, raw_offset = value.rsplit(":", 1)
            current = {
                "name": name,
                "module_offset": int(raw_offset, 0),
                "source_line": line_number,
                "tracks": [],
            }
            songs.append(current)
            continue
        if line.casefold().startswith("track="):
            if current is None:
                raise ValueError(f"music table line {line_number}: track precedes song")
            value = line.split("=", 1)[1]
            if ":" not in value:
                raise ValueError(f"music table line {line_number}: malformed track")
            name, raw_channels = value.rsplit(":", 1)
            channels = [int(token.strip(), 0) for token in raw_channels.split(",")]
            current["tracks"].append(
                {
                    "name": name,
                    "channels": channels,
                    "source_line": line_number,
                }
            )
            continue
        raise ValueError(f"music table line {line_number}: unknown declaration {line!r}")
    return songs


def build_catalog(
    game_root: Path, registry_log: Path, source_label: str
) -> dict[str, Any]:
    game_root = game_root.resolve()
    registry_text = registry_log.read_text(encoding="utf-8", errors="replace")
    rows = parse_registry(registry_text)
    validate_registry_layout(rows)
    bind_registry_files(rows, game_root, casefold_file_map(game_root))

    voices = build_voice_catalog(game_root)
    dynamic_paths = sorted(
        (game_root / "dynamic_sounds").glob("*.wav"), key=lambda item: item.name.casefold()
    )
    dynamic_sounds = [
        {
            "native_loader": "SoundLoop_Load / 0x00408220",
            "native_consumer": "Polisher constructor / 0x0050B4F0",
            "file": file_metadata(path, game_root),
        }
        for path in dynamic_paths
    ]

    music_table_path = game_root / "music" / "music.txt"
    music_module_path = game_root / "music" / "music.mo3"
    music_table_text = music_table_path.read_text(encoding="utf-8-sig")
    songs = parse_music_table(music_table_text)

    canonical_registry = "\n".join(
        line.rstrip("\r")
        for line in registry_text.splitlines()
        if line.startswith(AUDIO_REGISTRY_PREFIX)
    ).encode("utf-8")
    class_counts = Counter(row["native_class"] for row in rows)
    segment_counts = Counter(row["registry_segment"] for row in rows)
    extension_counts = Counter(row["resolved_extension"] for row in rows)
    referenced_voice_count = sum(bool(entry["definition_references"]) for entry in voices)

    return {
        "schema": "solomon-dark-native-audio-catalog-v1",
        "source": {
            "label": source_label,
            "native_registry_builder": "0x004EE010",
            "native_registry_owner": "MyApp +0x319EC8",
            "native_registry_singleton": "DAT_008199D8",
            "native_registry_block_size": AUDIO_BLOCK_SIZE,
            "registry_row_sha256": sha256_bytes(canonical_registry),
            "supported_sample_extensions": list(SUPPORTED_SAMPLE_EXTENSIONS),
        },
        "summary": {
            "compiled_registry_entry_count": len(rows),
            "compiled_class_counts": dict(sorted(class_counts.items())),
            "compiled_segment_counts": dict(sorted(segment_counts.items())),
            "compiled_extension_counts": dict(sorted(extension_counts.items())),
            "voice_file_count": len(voices),
            "voice_with_dialogue_definition_count": referenced_voice_count,
            "voice_without_dialogue_definition_count": len(voices) - referenced_voice_count,
            "dynamic_sound_count": len(dynamic_sounds),
            "wav_file_count": len(rows) + len(voices) + len(dynamic_sounds),
            "music_song_count": len(songs),
            "music_track_count": sum(len(song["tracks"]) for song in songs),
        },
        "native_types": [
            {
                "name": "Audio",
                "vtable": "0x007DB6CC",
                "constructor": "0x00406DE0",
            },
            {
                "name": "Sound",
                "vtable": "0x007DB784",
                "constructor": "0x00407530",
                "loader": "0x004076D0",
            },
            {
                "name": "SoundLoop",
                "vtable": "0x007DB78C",
                "constructor": "0x00408040",
                "loader": "0x00408220",
            },
            {"name": "SoundEcho", "vtable": "0x007DB7AC", "constructor": "0x004084A0"},
            {"name": "SoundDelayed", "vtable": "0x007DB7CC", "constructor": "0x004085C0"},
            {
                "name": "Music",
                "vtable": "0x007DB7F0",
                "constructor": "0x004086E0",
                "loader": "0x004088A0",
            },
            {
                "name": "SoundStream",
                "vtable": "0x007DB810",
                "constructor": "0x0040AC60",
                "loader": "0x0040ACF0",
            },
            {"name": "AmbientSound", "vtable": "0x007DB818"},
        ],
        "compiled_registry": rows,
        "voices": voices,
        "dynamic_sounds": dynamic_sounds,
        "music": {
            "native_loader": "Music_Load / 0x004088A0",
            "table": file_metadata(music_table_path, game_root),
            "module": file_metadata(music_module_path, game_root),
            "songs": songs,
        },
    }


def main() -> int:
    args = parse_args()
    catalog = build_catalog(args.game_root, args.registry_log, args.source_label)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(catalog["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
