"""Stock audio bootstrap and launch-time disable contracts."""

from __future__ import annotations

import struct
from pathlib import Path

from static_re_contract_support import (
    ABANDONWARE_BINARY,
    BINARY_LAYOUT,
    ROOT,
    StaticReTestFailure,
    read_text,
    sha256,
)


EXPECTED_BINARY_SHA256 = (
    "03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3"
)


def _read_pe_bytes(path: Path, virtual_address: int, size: int) -> bytes:
    data = path.read_bytes()
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise StaticReTestFailure(f"not a PE image: {path}")
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe_offset:pe_offset + 4] != b"PE\0\0":
        raise StaticReTestFailure(f"missing PE signature: {path}")

    number_of_sections = struct.unpack_from("<H", data, pe_offset + 6)[0]
    optional_header_size = struct.unpack_from("<H", data, pe_offset + 20)[0]
    optional_header = pe_offset + 24
    image_base = struct.unpack_from("<I", data, optional_header + 28)[0]
    rva = virtual_address - image_base
    section_offset = optional_header + optional_header_size
    for section_index in range(number_of_sections):
        header = section_offset + section_index * 40
        virtual_size, section_rva, raw_size, raw_offset = struct.unpack_from(
            "<IIII",
            data,
            header + 8,
        )
        section_size = max(virtual_size, raw_size)
        if section_rva <= rva and rva + size <= section_rva + section_size:
            file_offset = raw_offset + (rva - section_rva)
            return data[file_offset:file_offset + size]
    raise StaticReTestFailure(
        f"virtual range 0x{virtual_address:X}+0x{size:X} is not mapped by {path}"
    )


def test_stock_audio_bootstrap_and_settings_are_layout_backed() -> str:
    if not ABANDONWARE_BINARY.is_file():
        raise StaticReTestFailure(
            f"missing analyzed SolomonDark.exe: {ABANDONWARE_BINARY}"
        )
    binary_hash = sha256(ABANDONWARE_BINARY)
    if binary_hash != EXPECTED_BINARY_SHA256:
        raise StaticReTestFailure(
            "audio RE binary identity mismatch: "
            f"expected={EXPECTED_BINARY_SHA256} actual={binary_hash}"
        )

    layout_text = read_text(BINARY_LAYOUT)
    documentation_text = read_text(
        ROOT / "docs/reverse-engineering/native-audio-system.md"
    )
    required_layout_tokens = (
        "[audio.hooks]",
        "startup_coordinator=0x00407080",
        "load_persisted_volumes=0x00407190",
        "engine_initialize=0x004450D0",
        "engine_free=0x006B0186",
        "settings_apply=0x005D8FC0",
        "set_music_volume=0x00407340",
        "set_sound_volume=0x004073A0",
        "[audio.globals]",
        "manager=0x00B401A0",
        "engine_enabled=0x00B40239",
    )
    missing_layout = [
        token for token in required_layout_tokens if token not in layout_text
    ]
    if missing_layout:
        raise StaticReTestFailure(
            "audio binary layout is missing: " + ", ".join(missing_layout)
        )

    required_documentation_tokens = (
        "`BASS_Init(-1, 44100, 0, window, 0)`",
        "`Audio.SoundVolume`",
        "`Audio.MusicVolume`",
        "`Audio +0x78`",
        "`Audio +0x7C`",
        "`DAT_00B40239`",
        "`BASS_Free`",
        "Per-source muting is neither necessary nor complete.",
    )
    missing_documentation = [
        token
        for token in required_documentation_tokens
        if token not in documentation_text
    ]
    if missing_documentation:
        raise StaticReTestFailure(
            "native audio documentation is missing: "
            + ", ".join(missing_documentation)
        )

    instruction_contracts = (
        (
            0x004070A1,
            bytes.fromhex("E82AE00300"),
            "startup coordinator -> BASS initializer",
        ),
        (
            0x004070AE,
            bytes.fromhex("803D3902B40000"),
            "startup coordinator enabled-gate check",
        ),
        (
            0x004450D0,
            bytes.fromhex("E8B7B02600"),
            "BASS version query",
        ),
        (
            0x00445119,
            bytes.fromhex("E89EB02600"),
            "default-device BASS_Init",
        ),
        (
            0x0044512B,
            bytes.fromhex("E88CB02600"),
            "no-sound-device BASS_Init fallback",
        ),
        (
            0x00445143,
            bytes.fromhex("E8FCAF2600C6053902B40001"),
            "BASS_Start and enabled-gate write",
        ),
        (
            0x006B0186,
            bytes.fromhex("FF2558407800"),
            "BASS_Free import thunk",
        ),
        (
            0x00407349,
            bytes.fromhex("803D3902B40000"),
            "music-volume enabled-gate check",
        ),
        (
            0x004073A6,
            bytes.fromhex("803D3902B40000"),
            "sound-volume enabled-gate check",
        ),
        (
            0x005D9045,
            bytes.fromhex("E856E3E2FF"),
            "settings sound-volume setter call",
        ),
        (
            0x005D910F,
            bytes.fromhex("E82CE2E2FF"),
            "settings music-volume setter call",
        ),
    )
    mismatches: list[str] = []
    for address, expected, label in instruction_contracts:
        actual = _read_pe_bytes(ABANDONWARE_BINARY, address, len(expected))
        if actual != expected:
            mismatches.append(
                f"{label}@0x{address:08X} "
                f"expected={expected.hex()} actual={actual.hex()}"
            )
    if mismatches:
        raise StaticReTestFailure(
            "stock audio instruction contract mismatch: "
            + "; ".join(mismatches)
        )

    return (
        "stock BASS startup, no-sound fallback, global enabled gate, shutdown "
        "thunk, and settings volume writers match the analyzed executable"
    )
