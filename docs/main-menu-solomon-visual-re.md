# Main-menu Solomon visual

## Result

The large Solomon figure at the left of the stock main menu is not built from
the gameplay `Solomon.bundle` character parts. It is a title-specific
composition sourced entirely from:

- `images/Title.png`
- `images/Title.bundle`

The composition uses `Title.bundle` records 3, 8, and 11 through 15:

1. a black body/opening fill;
2. a separate pair of red eyes;
3. two copies of the current cloak frame;
4. two copies of the next cloak frame.

The cloak frames crossfade continuously. The whole composition is fixed-size
and anchored to the bottom-left of the render client. It does not scale or
recenter based on aspect ratio.

Extracted, pixel-verified layers are in
[`docs/assets/main-menu-solomon/`](assets/main-menu-solomon/). Regenerate them
with:

```bash
python3 tools/extract_main_menu_solomon.py
```

## Scope and evidence

Target:

- original 32-bit `SolomonDark.exe`;
- image base `0x00400000`;
- existing analyzed project `Decompiled Game/ghidra_project/SolomonDark.gpr`.

The investigation used the existing read-only Ghidra replica workflow and the
repository's bundle parser. Important native functions are:

| Address | Recovered role |
| --- | --- |
| `0x0058D940` | `MainMenu` constructor; installs vtable `0x007980CC`, starts the title theme, and calls `Title_Build` |
| `0x0059A9D0` | main-menu layout/resolution recomputation |
| `0x005A51B0` | main-menu tick and cloak-phase update |
| `0x00598780` | `MainMenu_Render`; draws the left Solomon and the rest of the title menu |
| `0x005A0960` | separate `MAIN MENU` / `HALL OF FAME` header renderer; not part of the left Solomon |
| `0x004F3210` | `Title_Build`; loads and parses the title atlas |
| `0x005AF5D0` | title-bundle constructor; installs vtable `0x00799F7C` and publishes `DAT_008199E0` |
| `0x00413030` | image-page-set loader |
| `0x004134B0` | `.bundle` metadata stream opener |
| `0x00413B10` | common sprite-record parser |
| `0x00413DE0` | runtime sprite/quad initializer |
| `0x00414EA0` | translated, uniformly scaled sprite draw |
| `0x004142E0` | unscaled sprite draw using its logical-canvas anchor |
| `0x0041FE50` | current render RGBA setter |
| `0x00441850` | PNG-to-BGRA decoder |
| `0x00440F70` | texture pixel upload |

The raw instructions at `0x005AF607` write `0x00799F7C` as the title-bundle
vtable. An older curated pseudo-source file names `0x00797CFC`; that older value
is stale.

## Asset-loading path

`MainMenu` construction calls `Title_Build`. The builder:

1. selects the base name `Title` or the optional high-resolution branch
   `Title@2X`;
2. asks `SpriteBundle_LoadImagePageSet` to probe `images\Title` and possible
   `images\Title-<n>` pages using the engine's supported image extensions;
3. opens `images\Title.bundle`;
4. consumes exactly 25 sprite records in fixed order.

The shipped data examined here contains only:

- `Title.png`: ordinary `2048 x 1024` RGBA PNG;
- `Title.bundle`: `1,125` bytes, exactly `25 * 45`;
- no `Title@2X` file and no suffixed title page.

The retail title path therefore uses the standard libpng decode into BGRA and
the 32-bit texture upload mode. There is no proprietary decompression for
`Title.bundle`: it is headerless, uncompressed little-endian metadata.

Each title record is:

```text
f32 atlas_x
f32 atlas_y
f32 atlas_width
f32 atlas_height
i32 logical_width
u32 logical_height
f32 content_width
f32 content_height
f32 center_offset_x
f32 center_offset_y
u8  rotated
u32 point_count
point_count * { f32 x, f32 y }
```

All 25 title records have `rotated = 0` and `point_count = 0`. The logical
placement of a trimmed crop is:

```text
trim_x = (logical_width  - content_width)  / 2 + center_offset_x
trim_y = (logical_height - content_height) / 2 + center_offset_y
```

The general bundle format and validation are documented in
[`tools/sprite-bundle-format.md`](../tools/sprite-bundle-format.md).

## Title bundle storage

Records 0 through 10 are inline runtime sprites, each `0xC4` bytes:

```text
Title + 0x038, 0x0FC, 0x1C0, 0x284, 0x348, 0x40C,
        0x4D0, 0x594, 0x658, 0x71C, 0x7E0
```

Records 11 through 15 form the five-frame cloak vector:

```text
vector       Title + 0x8A4
data pointer Title + 0x8A8
count        Title + 0x8AC
sprite stride 0xC4
```

Records 16 through 24 form the grave-decoration vector at
`+0x8B4/+0x8B8/+0x8BC`. They do not contribute to Solomon.

## Exact Solomon records

| Record | Bundle offset | Layer | Atlas crop `(x,y,w,h)` | Logical canvas | Center offset | Trim origin |
| ---: | ---: | --- | --- | --- | --- | --- |
| 3 | `0x087` | black body/opening | `(0,231,104,249)` | `512 x 384` | `(-160, 39.5)` | `(44,107)` |
| 8 | `0x168` | red eyes | `(0,0,171,30)` | `1024 x 768` | `(-333.5,19)` | `(93,388)` |
| 11 | `0x1EF` | cloak frame 0 | `(172,655,183,327)` | `512 x 384` | `(-164.5,28.5)` | `(0,57)` |
| 12 | `0x21C` | cloak frame 1 | `(356,193,183,326)` | `512 x 384` | `(-164.5,29)` | `(0,58)` |
| 13 | `0x249` | cloak frame 2 | `(172,328,183,326)` | `512 x 384` | `(-164.5,29)` | `(0,58)` |
| 14 | `0x276` | cloak frame 3 | `(356,520,183,326)` | `512 x 384` | `(-164.5,29)` | `(0,58)` |
| 15 | `0x2A3` | cloak frame 4 | `(172,0,183,327)` | `512 x 384` | `(-164.5,28.5)` | `(0,57)` |

The extractor writes these exact crops and reopens every output PNG to confirm
that its RGBA pixels match the corresponding source-atlas crop.

`Solomon.bundle` contains 273 gameplay-character sprites, while
`SolomonRiff.bundle` contains 13 guitar-animation sprites. Their separate
builders are `0x004ED980` and `0x004EDE70`; neither is used by this title
composition.

## Render assembly

Let `H` be the current render-client height. The render code does not use the
client width for this figure.

### General scaled placement

For the body and cloak, the stock scaled helper uses a logical-canvas center
`(cx, cy)` and uniform scale `s`:

```text
left = group_x + cx + s * (trim_x - logical_width / 2)
top  = group_y + cy + s * (trim_y - logical_height / 2)
```

The outer Solomon group is translated by `(-40,+60)`. The body and cloak use:

```text
center = (512, H - 384)
scale  = 2
color  = white
rotation = 0
```

### Exact draw order and final crop rectangles

1. Draw record 3, the black body/opening:

   ```text
   left = 48
   top = H - 494
   size = 208 x 498
   alpha = 1
   ```

2. Push another translation of `(-10,-10)` and draw record 8, the eyes:

   ```text
   left = 50
   top = H - 370 + sin(theta)
   size = 171 x 30
   alpha = 1
   ```

3. Pop the inner translation.

4. Draw the current cloak frame twice:

   ```text
   frame 0 or 4: left=-40, top=H-594, size=366 x 654
   frame 1..3:   left=-40, top=H-592, size=366 x 652
   alpha = 1 - fraction^3
   ```

5. Draw the next cloak frame twice at its corresponding rectangle:

   ```text
   alpha = fraction
   ```

6. Restore white RGBA and pop the outer translation.

The duplicate cloak draws are intentional. To match the stock result exactly,
draw each selected frame twice with normal source-over alpha blending. Do not
replace the duplicate pair with a single draw unless the replacement also
accounts for every source pixel's own alpha.

The gold logo, title background, menu controls, grass, clouds, moon, and graves
are drawn by the same renderer but are separate from this composition. The
complete gold logo is `Title[9]`.

At a `900`-pixel client height, the resulting crop rectangles are:

```text
body:        (48,406) 208 x 498
eyes:        (50,530 + sin(theta)) 171 x 30
cloak 0/4:  (-40,306) 366 x 654
cloak 1..3: (-40,308) 366 x 652
```

The cloak extends 60 pixels below the client and is clipped by the viewport.

## Animation

The stock tick uses the global frame counter at `0x0081F658`:

```text
theta = global_tick * pi / 180
eye_y_offset = sin(theta)
```

The eye motion is vertical only, with an amplitude of one render pixel.

The cloak phase is the float at `MainMenu + 0x400`. Each main-menu tick:

```text
phase = (phase + 0.025 + 0.005 * sin(theta)) mod 5

current  = floor(phase)
fraction = phase - current
next     = (current + 1) mod 5

current_alpha = 1 - fraction^3
next_alpha    = fraction
```

There is no layer rotation and no non-white tint. The five cloak crops are
animation states, not independent body pieces.

The phase advance is tick-based rather than elapsed-time based. A website
should run it through a fixed-rate update accumulator, preferably 60 updates
per second, so a 144 Hz display does not make the cloak animate 2.4 times
faster.

## Website implementation

Canvas is the most direct match because the stock renderer uses ordered
source-over draws:

```js
let phase = 0;
let tick = 0;

function updateStockAnimation() {
  const theta = tick * Math.PI / 180;
  phase = (phase + 0.025 + 0.005 * Math.sin(theta)) % 5;
  tick += 1;
}

function drawLayer(ctx, image, x, y, width, height, alpha) {
  ctx.globalAlpha = alpha;
  ctx.drawImage(image, x, y, width, height);
}

function drawTwice(ctx, image, x, y, width, height, alpha) {
  drawLayer(ctx, image, x, y, width, height, alpha);
  drawLayer(ctx, image, x, y, width, height, alpha);
}

function renderSolomon(ctx, clientHeight, assets) {
  const theta = tick * Math.PI / 180;
  const current = Math.floor(phase);
  const fraction = phase - current;
  const next = (current + 1) % 5;

  ctx.save();
  ctx.globalCompositeOperation = "source-over";

  drawLayer(ctx, assets.body, 48, clientHeight - 494, 208, 498, 1);
  drawLayer(
    ctx,
    assets.eyes,
    50,
    clientHeight - 370 + Math.sin(theta),
    171,
    30,
    1
  );

  const drawCloak = (index, alpha) => {
    const edgeFrame = index === 0 || index === 4;
    drawTwice(
      ctx,
      assets.cloak[index],
      -40,
      clientHeight - (edgeFrame ? 594 : 592),
      366,
      edgeFrame ? 654 : 652,
      alpha
    );
  };

  drawCloak(current, 1 - fraction ** 3);
  drawCloak(next, fraction);
  ctx.restore();
}
```

For a high-DPI browser canvas, scale the backing buffer by
`window.devicePixelRatio`, scale the context by the same value, and continue
using CSS-pixel `clientHeight` in the formulas above. Clip to the canvas bounds.

The original figure is fixed-pixel:

- changing width adds or removes space to its right;
- changing height moves it vertically one-for-one;
- body and cloak remain at `2x`;
- eyes remain at `1x`;
- the renderer performs no Solomon-specific aspect correction.

If the site uses a letterboxed game-design canvas, apply that canvas's outer
scale and offset after assembling Solomon in this stock coordinate system.
That outer presentation transform is not part of `MainMenu_Render`.

## Extracted artifacts

- [`body.png`](assets/main-menu-solomon/body.png)
- [`eyes.png`](assets/main-menu-solomon/eyes.png)
- [`cloak-0.png`](assets/main-menu-solomon/cloak-0.png)
- [`cloak-1.png`](assets/main-menu-solomon/cloak-1.png)
- [`cloak-2.png`](assets/main-menu-solomon/cloak-2.png)
- [`cloak-3.png`](assets/main-menu-solomon/cloak-3.png)
- [`cloak-4.png`](assets/main-menu-solomon/cloak-4.png)
- [`contact-sheet.png`](assets/main-menu-solomon/contact-sheet.png)
- [`manifest.json`](assets/main-menu-solomon/manifest.json)

## Open questions and boundaries

- The binary contains a `Title@2X` selection branch, but the shipped data copy
  has no matching files. Its exact selection condition is not needed for the
  retail composition recovered here.
- Fullscreen scaling, DPI behavior, and any letterboxing applied outside the
  menu renderer are upstream concerns. The formulas above describe the
  renderer's own client-coordinate behavior.
- The exact fixed tick frequency depends on the surrounding game loop. The
  phase and eye formulas themselves are verified; the 60 Hz website accumulator
  is the practical reproduction choice, not a claim that the executable
  hardcodes 60 Hz in this function.
