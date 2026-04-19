#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description='Overlay a nav-grid export onto a captured hub screenshot.')
    parser.add_argument('--screenshot', default='runtime/hub_scene_for_overlay.png', help='Screenshot path relative to repo root.')
    parser.add_argument('--grid', default='runtime/hub_nav_grid.png', help='Grid PNG path relative to repo root.')
    parser.add_argument('--output', default='runtime/hub_nav_grid_overlay.png', help='Output PNG path relative to repo root.')
    args = parser.parse_args()

    screenshot_path = (ROOT / args.screenshot).resolve()
    grid_path = (ROOT / args.grid).resolve()
    output_path = (ROOT / args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    screenshot = Image.open(screenshot_path).convert('RGBA')
    grid = Image.open(grid_path).convert('RGBA')

    base = screenshot.copy()
    draw = ImageDraw.Draw(base)
    font = ImageFont.load_default()

    max_inset_width = int(base.width * 0.45)
    scale = min(1.0, max_inset_width / grid.width)
    inset_size = (max(1, int(grid.width * scale)), max(1, int(grid.height * scale)))
    inset = grid.resize(inset_size, Image.Resampling.LANCZOS)

    alpha = inset.getchannel('A')
    inset.putalpha(alpha.point(lambda value: int(value * 0.88)))

    panel_padding = 12
    panel_x = 16
    panel_y = base.height - inset.height - 96
    panel_w = inset.width + panel_padding * 2
    panel_h = inset.height + 72

    panel = Image.new('RGBA', (panel_w, panel_h), (12, 12, 16, 210))
    panel_draw = ImageDraw.Draw(panel)
    panel_draw.rectangle((0, 0, panel_w - 1, panel_h - 1), outline=(220, 220, 220, 255), width=1)
    panel_draw.text((12, 10), 'Hub nav grid', fill=(240, 240, 240, 255), font=font)
    panel_draw.text((12, 26), 'Green/red = cell-center traversability only.', fill=(220, 220, 220, 255), font=font)
    panel_draw.text((12, 40), 'Player/bot can stand at valid points inside a red cell.', fill=(220, 220, 220, 255), font=font)
    panel.alpha_composite(inset, (panel_padding, 64))

    base.alpha_composite(panel, (panel_x, max(16, panel_y)))

    caption = 'Nav grid is coarse gameplay space, not a camera-projected mesh overlay.'
    draw.rounded_rectangle((16, 16, 16 + 430, 40), radius=8, fill=(12, 12, 16, 200), outline=(220, 220, 220, 220), width=1)
    draw.text((24, 23), caption, fill=(240, 240, 240, 255), font=font)

    base.convert('RGB').save(output_path)
    print(f'wrote {output_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
