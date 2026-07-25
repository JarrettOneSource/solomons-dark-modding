#!/usr/bin/env python3
"""Pixel contract for the native player-facing spectator HUD."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from verify_local_multiplayer_sync import VerifyFailure


HUD_REGION = (0.20, 0.04, 0.80, 0.16)
MINIMUM_VISIBLE_GOLD_PIXELS = 500
# A stock player-name label can enter this screen-space band when its actor is
# near the top edge. It measured 307 pixels in live acceptance; the product
# HUD text is consistently above 2,000 pixels.
MAXIMUM_HIDDEN_GOLD_PIXELS = 400


def _is_product_gold(red: int, green: int, blue: int) -> bool:
    return (
        red >= 150
        and green >= 100
        and blue <= 140
        and red >= green
        and green >= blue
    )


def inspect_spectator_product_hud_pixels(
    image_path: Path,
    *,
    expected_visible: bool,
) -> dict[str, Any]:
    path = Path(image_path)
    if not path.is_file() or path.stat().st_size == 0:
        raise VerifyFailure(
            f"spectator product HUD capture is missing: {path}"
        )

    with Image.open(path) as source:
        image = source.convert("RGB")
        left = int(image.width * HUD_REGION[0])
        top = int(image.height * HUD_REGION[1])
        right = int(image.width * HUD_REGION[2])
        bottom = int(image.height * HUD_REGION[3])
        crop = image.crop((left, top, right, bottom))
        pixels = crop.load()
        gold_pixels = sum(
            1
            for y in range(crop.height)
            for x in range(crop.width)
            if _is_product_gold(*pixels[x, y])
        )

    if (
        expected_visible
        and gold_pixels < MINIMUM_VISIBLE_GOLD_PIXELS
    ):
        raise VerifyFailure(
            "spectator product HUD was registered but its stock-style "
            f"text was not visible in the backbuffer: path={path} "
            f"gold_pixels={gold_pixels} "
            f"minimum={MINIMUM_VISIBLE_GOLD_PIXELS}"
        )
    if (
        not expected_visible
        and gold_pixels > MAXIMUM_HIDDEN_GOLD_PIXELS
    ):
        raise VerifyFailure(
            "spectator product HUD pixels appeared for a non-spectating "
            f"peer or outside its lifecycle: path={path} "
            f"gold_pixels={gold_pixels} "
            f"maximum={MAXIMUM_HIDDEN_GOLD_PIXELS}"
        )
    return {
        "path": str(path),
        "expected_visible": expected_visible,
        "matches": True,
        "gold_pixels": gold_pixels,
        "minimum_visible_gold_pixels":
            MINIMUM_VISIBLE_GOLD_PIXELS,
        "maximum_hidden_gold_pixels":
            MAXIMUM_HIDDEN_GOLD_PIXELS,
        "normalized_region": list(HUD_REGION),
    }
