# Solomon Dark sprite-bundle format

## Result

The common sprite descriptor is little-endian and headerless, but it is not
always a flat array of 45-byte records. A record has a 45-byte fixed header and
an optional point tail:

```text
record_size = 45 + 8 * point_count
```

Two files, `Fonts.bundle` and `ControlPanel.bundle`, also wrap common sprite
records in font-table sections. The extractor handles both stream forms.

## Common sprite record

| Offset | Size | Type | Meaning | Evidence |
| ---: | ---: | --- | --- | --- |
| `0x00` | 4 | `f32` | Atlas `x` | Values are integral in all 10,498 records and every decoded rectangle lies inside its sibling atlas. |
| `0x04` | 4 | `f32` | Atlas `y` | Same; `Title[0]` decodes to `y=558`. |
| `0x08` | 4 | `f32` | Packed rectangle width | `Title[0]` is `512`; all values are positive and fit the sibling PNG. |
| `0x0c` | 4 | `f32` | Packed rectangle height | `Title[0]` is `218`; all values are positive and fit the sibling PNG. |
| `0x10` | 4 | `i32` | Logical/untrimmed canvas width | It can be larger than the packed width. Together with the center offset it reconstructs the trimmed placement within an animation canvas. |
| `0x14` | 4 | `u32` | Logical/untrimmed canvas height | Same relationship as logical width; all observed values are positive. |
| `0x18` | 4 | `f32` | Trimmed content width | Equals the packed rectangle width in every retail record. |
| `0x1c` | 4 | `f32` | Trimmed content height | Equals the packed rectangle height in every retail record. |
| `0x20` | 4 | `f32` | Trimmed-content center offset X | Produces the original trim position with `(logical_width - content_width) / 2 + offset_x`. |
| `0x24` | 4 | `f32` | Trimmed-content center offset Y | Produces the original trim position with `(logical_height - content_height) / 2 + offset_y`. |
| `0x28` | 1 | `u8` | Rotated flag | Confirmed by the game's common-record loader. All 10,498 retail records contain `0`; the known values are `0` and `1`. |
| `0x29` | 4 | `u32` | Extra point count, `N` | Explains every variable-length common stream exactly. |
| `0x2d` | `8N` | `N * {f32 x, f32 y}` | Extra point vector list | Parsed by the game immediately after the fixed header. Its gameplay/rendering meaning is not needed for atlas cropping. |

The logical-canvas interpretation is visible in `Title[3]`: its logical
canvas is `512x384`, packed content is `104x249`, and its offsets are
`(-160, 39.5)`. The implied trim origin is therefore `(44, 107)`:

```text
(512 - 104) / 2 - 160  = 44
(384 - 249) / 2 + 39.5 = 107
```

The decompiled parser at `SpriteBundle_ReadNextSpriteRecord` (`0x00413B10`)
independently confirms the four leading floats, six following 32-bit values,
one rotation byte, unaligned point count, and vector tail.

`raw_meta_hex` in each manifest is the exact byte range from record offset
`0x10` through the end of its point tail. It is therefore `29 + 8N` bytes and
preserves every non-rectangle field.

## Mixed font-table wrapper

`Fonts.bundle` contains one common record followed by nine auxiliary groups.
`ControlPanel.bundle` contains 24 common records followed by one auxiliary
group. Each auxiliary group is:

```text
f32 group_metrics[3]

repeat:
    u16 left_id
    u16 right_id
    if left_id == 0 and right_id == 0: end kerning table
    f32 adjustment

repeat:
    u16 glyph_id
    if glyph_id == 0: end glyph table
    f32 glyph_metrics[3]
    common_sprite_record
```

The first table is identifiable directly from entries such as `(65, 86,
-1.0)`, or `A/V/-1`, and the second from sequential printable character IDs
followed by atlas-bounded common records. The three group-header floats and
three per-glyph floats are font metrics; their finer semantic names are not
required to locate or extract the embedded sprites.

The embedded glyph counts are:

- `ControlPanel`: `92`
- `Fonts`: `92, 92, 31, 92, 42, 26, 67, 92, 92` (`626` embedded records)

## Size cross-check

For every non-mixed file, the exact relationship is:

```text
file_size = 45 * sprite_count + 8 * total_point_count
```

Twenty file sizes happen to divide by 45. Nineteen of those are fixed-only
streams; `Faculty.bundle` also divides by 45 only because its 180 point vectors
add 1,440 bytes, itself divisible by 45. Six non-divisible files are ordinary
point-tailed streams. The remaining two are the mixed wrappers above.

| Atlas | Bytes | `bytes % 45` | Sprites | Points | Stream |
| --- | ---: | ---: | ---: | ---: | --- |
| BadGuys | 120057 | 42 | 2509 | 894 | points |
| Bonedit | 3780 | 0 | 84 | 0 | fixed |
| Clothes | 180444 | 39 | 3724 | 1608 | points |
| College | 24435 | 0 | 543 | 0 | fixed |
| ControlPanel | 6838 | 43 | 116 | 0 | mixed |
| Controls | 180 | 0 | 4 | 0 | fixed |
| Create | 1080 | 0 | 24 | 0 | fixed |
| DeadHawg | 15660 | 0 | 348 | 0 | fixed |
| Demon | 7668 | 18 | 116 | 306 | points |
| Faculty | 24975 | 0 | 523 | 180 | points |
| Fonts | 50069 | 29 | 627 | 0 | mixed |
| GameOver | 135 | 0 | 3 | 0 | fixed |
| Golem | 9405 | 0 | 209 | 0 | fixed |
| Heartmonger | 21852 | 27 | 380 | 594 | points |
| Inventory | 3780 | 0 | 84 | 0 | fixed |
| LevelPicker | 360 | 0 | 8 | 0 | fixed |
| Library | 1485 | 0 | 33 | 0 | fixed |
| Loader | 225 | 0 | 5 | 0 | fixed |
| Memoratorium | 3420 | 0 | 76 | 0 | fixed |
| NPCs | 9999 | 9 | 219 | 18 | points |
| Office | 1215 | 0 | 27 | 0 | fixed |
| Skills | 7470 | 0 | 166 | 0 | fixed |
| Solomon | 12285 | 0 | 273 | 0 | fixed |
| SolomonRiff | 585 | 0 | 13 | 0 | fixed |
| Storage | 1215 | 0 | 27 | 0 | fixed |
| Title | 1125 | 0 | 25 | 0 | fixed |
| UI | 5085 | 0 | 113 | 0 | fixed |
| Unholy | 11007 | 27 | 219 | 144 | points |

## Extraction validation and data anomalies

- All 10,498 decoded rectangles have finite integral coordinates, positive
  sizes, and lie inside their sibling PNG. No crop needed clamping.
- All fixed content-width/content-height values equal the rectangle width and
  height. All rotation bytes are zero.
- `Title[0]` is the purple-cloud sprite at `(807, 558, 512, 218)`.
- `Title[9]` is the complete gold logo at `(806, 128, 829, 395)`; it alone
  covers the requested approximate logo region `(800..1580, 130..500)`.
- Every atlas has one opaque-white `3x3` utility sprite. These records were
  retained like every other descriptor.
- There are 115 positive, in-bounds descriptors whose atlas pixels are fully
  transparent. They are overwhelmingly `1x1` placeholders and were extracted,
  not skipped:
  - `Bonedit`: 1 (`63`)
  - `Clothes`: 73 (`58`, `460-483`, `485-489`, `580-586`, `601-603`,
    `2046-2047`, `2952-2954`, `2956`, `2977-2979`, `3700-3723`)
  - `College`: 23 (`69`, `81`, `237-240`, `242`, `260`, `285-290`, `308`,
    `378-380`, `401-402`, `455`, `483-484`)
  - `DeadHawg`: 13 (`251-263`)
  - `Golem`: 5 (`81`, `83-84`, `94`, `96`)

## Running the extractor

`tools/extract_bundles.py` needs Python 3 with Pillow:

```bash
python3 tools/extract_bundles.py --images-dir <game>/images --output-dir <dest>
```

It writes per-atlas sprite PNGs, a `manifest.json` of decoded rectangles, and
an index-labeled contact sheet per atlas. `--images-dir` defaults to the
workspace's `SolomonDarkAbandonware/images` copy and `--output-dir` to `out/`
beside the script.
