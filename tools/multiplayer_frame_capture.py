#!/usr/bin/env python3
"""Capture the game's real D3D9 backbuffer through the debug Lua bridge."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from PIL import Image

from verify_local_multiplayer_sync import (
    VerifyFailure,
    lua,
    parse_key_values,
    path_for_powershell,
)


GamePathKind = Literal["windows", "proton"]


def path_for_game(path: Path, kind: GamePathKind) -> str:
    if kind == "windows":
        return path_for_powershell(path)
    if kind == "proton":
        return "Z:" + str(path.resolve()).replace("/", "\\")
    raise ValueError(f"unsupported game path kind: {kind}")


def convert_and_validate_backbuffer(
    raw_path: Path,
    output_path: Path,
    *,
    minimum_unique_colors: int = 1000,
    maximum_dominant_fraction: float = 0.70,
) -> dict[str, Any]:
    """Validate one captured frame and persist its normalized PNG."""

    if not raw_path.is_file() or raw_path.stat().st_size == 0:
        raise VerifyFailure(f"D3D9 backbuffer capture is missing: {raw_path}")

    with Image.open(raw_path) as raw:
        image = raw.convert("RGB")
        colors = image.getcolors(maxcolors=image.width * image.height)
        unique_colors = len(colors) if colors is not None else image.width * image.height
        dominant_fraction = (
            max(count for count, _ in colors) / float(image.width * image.height)
            if colors
            else 0.0
        )
        if (
            unique_colors < minimum_unique_colors
            or dominant_fraction >= maximum_dominant_fraction
        ):
            raise VerifyFailure(
                f"D3D9 backbuffer capture is blank or low-information: path={raw_path} "
                f"unique_colors={unique_colors} dominant_fraction={dominant_fraction:.4f}"
            )
        image.save(output_path)
        return {
            "width": image.width,
            "height": image.height,
            "unique_colors": unique_colors,
            "dominant_fraction": dominant_fraction,
        }


def capture_game_backbuffer(
    pipe_name: str,
    output_path: Path,
    *,
    game_path_kind: GamePathKind = "windows",
    minimum_unique_colors: int = 1000,
    maximum_dominant_fraction: float = 0.70,
) -> dict[str, Any]:
    raw_path = output_path.with_name(f"{output_path.stem}_backbuffer.bmp")
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.unlink(missing_ok=True)
    output_path.unlink(missing_ok=True)

    game_path = path_for_game(raw_path, game_path_kind)
    command = f"""
local ok, err = sd.debug.capture_backbuffer({json.dumps(game_path)})
print('ok=' .. tostring(ok))
print('error=' .. tostring(err or ''))
"""
    result = parse_key_values(lua(pipe_name, command, timeout=20.0))
    if result.get("ok") != "true":
        raise VerifyFailure(
            f"D3D9 backbuffer capture failed on {pipe_name}: result={result} path={raw_path}"
        )

    quality = convert_and_validate_backbuffer(
        raw_path,
        output_path,
        minimum_unique_colors=minimum_unique_colors,
        maximum_dominant_fraction=maximum_dominant_fraction,
    )

    raw_bytes = raw_path.stat().st_size
    raw_path.unlink(missing_ok=True)
    return {
        "pipe": pipe_name,
        "path": str(output_path),
        "bytes": output_path.stat().st_size,
        "raw_bmp_bytes": raw_bytes,
        "capture_method": "d3d9_backbuffer",
        "game_path_kind": game_path_kind,
        "quality": quality,
    }
